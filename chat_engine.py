"""
Chat-Engine für Flychat.
Zentrale Klasse die Pilotenfragen beantwortet.
Globaler Wetterdaten-Kontext + Per-User Conversation History.
"""

import os
import json
import logging
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from openai import OpenAI

import config
from spots import load_spots
from fetch_weather import fetch_all_spots, load_cached_weather, is_cache_fresh
from foehn_indicators import fetch_foehn_data, evaluate_foehn
from thermik_calculator import calculate_thermal_profile, calculate_dewpoint
from prompts import SYSTEM_PROMPT, SAFETY_CHECK_PROMPT, FLYABILITY_PROMPT

logger = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = 40  # Max messages per conversation before trimming

COMPASS_POINTS = {
    "N": 0.0, "NNO": 22.5, "NO": 45.0, "ONO": 67.5,
    "O": 90.0, "OSO": 112.5, "SO": 135.0, "SSO": 157.5,
    "S": 180.0, "SSW": 202.5, "SW": 225.0, "WSW": 247.5,
    "W": 270.0, "WNW": 292.5, "NW": 315.0, "NNW": 337.5
}


class FlychatEngine:
    def __init__(self, instantdb_client=None):
        self.spots = load_spots()
        self.weather_data = {}
        self.weather_context_str = ""
        self.weather_loaded_at = None
        self.foehn_data = None
        self.conversations = {}
        self.instantdb = instantdb_client
        self.spot_analyses = {}
        self.analyses_loaded_at = None

        api_key = os.environ.get("OPENAI_API_KEY")
        self.model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        self.client = OpenAI(api_key=api_key) if api_key else None

        # History-Persistenz
        self.history_dir = config.HISTORY_DIR
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self._load_all_conversations()

    def _load_all_conversations(self):
        """Lädt alle Conversations aus dem history-Verzeichnis."""
        for filename in os.listdir(self.history_dir):
            if filename.endswith(".json"):
                session_id = filename[:-5]
                try:
                    with open(self.history_dir / filename, "r", encoding="utf-8") as f:
                        self.conversations[session_id] = json.load(f)
                except Exception as e:
                    logger.error(f"Fehler beim Laden der History {session_id}: {e}")

    def _save_conversation(self, session_id: str):
        """Speichert eine Conversation als JSON."""
        if session_id not in self.conversations:
            return
        try:
            with open(self.history_dir / f"{session_id}.json", "w", encoding="utf-8") as f:
                json.dump(self.conversations[session_id], f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Fehler beim Speichern der History {session_id}: {e}")

    def refresh_weather(self, force=False):
        """Wetterdaten für alle Spots holen + Kontext-String bauen."""
        print("[ENGINE] Lade Wetterdaten für alle Spots...")
        self.spots = load_spots() # Reload spots to pick up CSV changes

        # 1. Wetterdaten holen (oder Cache nutzen)
        if not force and is_cache_fresh(max_age_hours=12):
            print("[ENGINE] Nutze gecachte Wetterdaten")
            self.weather_data = load_cached_weather()
        else:
            print("[ENGINE] Lade neue Wetterdaten von API...")
            self.weather_data = fetch_all_spots(self.spots)

        # 2. Föhn-Daten holen
        try:
            self.foehn_data = fetch_foehn_data(forecast_days=config.FORECAST_DAYS)
        except Exception as e:
            logger.error(f"Föhn-Daten fehlgeschlagen: {e}")
            self.foehn_data = None

        # 3. Kontext-String bauen
        self.weather_context_str = self._build_weather_context()
        self.weather_loaded_at = datetime.now()

        # 4. Conversations NICHT komplett resetten, aber Cache markieren
        for conv in self.conversations.values():
             conv["first_question"] = True

        # 5. An InstantDB pushen (non-blocking)
        if self.instantdb:
            threading.Thread(target=self._push_to_instantdb, daemon=True).start()

        print(f"[ENGINE] Wetterdaten geladen ({len(self.weather_data) - 1} Spots)")

    def _build_weather_context(self) -> str:
        """Formatiert ALLE Spot-Daten + Thermik + Föhn als einen Text-Block."""
        if not self.weather_data:
            return "Keine Wetterdaten verfügbar."

        meta = self.weather_data.get("_meta", {})
        updated = meta.get("last_updated", "unbekannt")

        lines = [
            f"AKTUELLE WETTERDATEN (Stand: {updated})",
            f"Vorhersagezeitraum: {config.FORECAST_DAYS} Tage, "
            f"Flugstunden {config.FLIGHT_HOURS_START}:00-{config.FLIGHT_HOURS_END}:00",
            "",
        ]

        # Pro Spot
        for spot in self.spots:
            name = spot["name"]
            spot_data = self.weather_data.get(name)
            if not spot_data:
                continue

            lines.append(f"═══ SPOT: {name} ({spot['fluggebiet']}, {spot['region']}) ═══")
            spot_info_idx = len(lines)
            wind_ranges = self._parse_wind_range(spot["windrichtung"])
            if wind_ranges:
                range_parts = []
                for start, end in wind_ranges:
                    range_parts.append(f"{start:.0f}°-{end:.0f}°")
                wind_degrees = " (" + ", ".join(range_parts) + ")"
            else:
                wind_degrees = ""
            lines.append(
                f"Höhe: {spot['elevation_m']}m MSL | "
                f"Windrichtung erlaubt: {spot['windrichtung']}{wind_degrees} | "
                f"Max. Wind: {spot['ideal_wind_max']} km/h | "
                f"Kritischer Föhn: {spot['kritischer_foehn']}"
            )
            if spot.get("bemerkung"):
                lines.append(f"Bemerkung: {spot['bemerkung']}")

            hourly_data = spot_data.get("hourly_data", {})
            pressure_level_data = spot_data.get("pressure_level_data", {})
            elevation_m = spot["elevation_m"]

            # Peak-Werte für Zusammenfassung finden
            max_climb = 0.0
            max_climb_h = 0
            
            # Formatiere Stundendaten (nur Flugstunden)
            sorted_times = sorted(hourly_data.keys())
            hourly_lines = []
            for timestamp in sorted_times:
                try:
                    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    # Nur heute und morgen anzeigen (Begrenzung der Token)
                    if dt.date() > datetime.now().date() and len(hourly_lines) > 14:
                        continue
                    if not (config.FLIGHT_HOURS_START <= dt.hour < config.FLIGHT_HOURS_END):
                        continue
                except Exception:
                    continue

                data = hourly_data[timestamp]
                time_str = timestamp.replace("T", " ")[:16]

                # ... (Rest der Zeilen bleibt gleich, aber wir sammeln sie erst)
                # Thermik-Proxy berechnen
                thermal_info = ""
                h_climb = 0.0
                h_max_h = 0
                try:
                    therm = self._calculate_thermal_raw(
                        data, pressure_level_data.get(timestamp, {}),
                        elevation_m, timestamp, spot
                    )
                    if therm and "error" not in therm:
                        h_climb = therm["climb_rate"]
                        h_max_h = therm["max_height"]
                        if h_climb > max_climb:
                            max_climb = h_climb
                            max_climb_h = h_max_h
                        
                        lcl = therm.get("lcl")
                        lcl_str = f", LCL/Basis {lcl}m" if lcl else ""
                        thermal_info = f" | THERMIK-PROXY: {h_climb} m/s bis {h_max_h}m MSL{lcl_str} (Güte: {therm['rating']}/10)"
                except Exception as e:
                    thermal_info = f" | Thermik-Fehler: {e}"

                temp = data.get("temperature_2m", "N/A")
                wind_speed = data.get("wind_speed_10m", "N/A")
                wind_dir = data.get("wind_direction_10m", "N/A")
                wind_gusts = data.get("wind_gusts_10m", "N/A")
                cloud_base_raw = data.get("cloud_base")
                cloud_base = f"{cloud_base_raw}m" if cloud_base_raw is not None else "wolkenfrei"
                cloud_cover = data.get("cloud_cover", "N/A")
                precip = data.get("precipitation", "N/A")
                sunshine = data.get("sunshine_duration", "N/A")
                sunshine_str = f"{sunshine / 3600:.2f}h" if isinstance(sunshine, (int, float)) and sunshine > 0 else "0h"

                # Wind-Check
                is_ok = self._is_wind_in_range(wind_dir, spot["windrichtung"])
                wind_status = "[WIND-OK]" if is_ok else "[WIND-WRONG]"

                warnings = []
                if isinstance(wind_gusts, (int, float)) and isinstance(wind_speed, (int, float)):
                    if wind_gusts - wind_speed > 15:
                        warnings.append("[GUST-WARN]")
                
                if isinstance(precip, (int, float)) and precip > 0:
                    warnings.append("[RAIN-WARN]")

                # Höhenwind-Info für Föhn-Erkennung (850hPa / ~1500m)
                alt_wind_info = ""
                pl_data = pressure_level_data.get(timestamp, {})
                if pl_data:
                    for level in [850, 700]:
                        h_val = pl_data.get(f"geopotential_height_{level}hPa")
                        ws = pl_data.get(f"wind_speed_{level}hPa")
                        wd = pl_data.get(f"wind_direction_{level}hPa")
                        if h_val is not None and ws is not None and wd is not None:
                            alt_wind_info += f" | {level}hPa({int(h_val)}m): {ws:.0f}km/h aus {wd:.0f}°"
                            # Sehr vorsichtige Schwellenwerte für Paraglider (Lee-Turbulenz Gefahr)
                            if (level == 850 and ws > 30) or (level == 700 and ws > 30):
                                if "[ALOFT-WARN]" not in warnings:
                                    warnings.append("[ALOFT-WARN]")

                try:
                    cape = data.get("cape")
                    if isinstance(cape, (int, float)) and cape > 800:
                        warnings.append("[CAPE-WARN]")
                except Exception:
                    pass

                if isinstance(cloud_cover, (int, float)) and cloud_cover >= 80:
                    warnings.append("[OVERCAST-WARN]")

                warning_str = " " + " ".join(warnings) if warnings else ""

                hourly_lines.append(
                    f"{time_str}: Temp {temp}°C | Wind {wind_speed}km/h aus {wind_dir}° (Böen {wind_gusts}km/h) {wind_status}{warning_str} | "
                    f"Wolkenbasis {cloud_base} | Bewölkung {cloud_cover}% | Sonne {sunshine_str}{alt_wind_info}{thermal_info}"
                )

            # Füge Peak-Info in den Info-Bereich ein
            lines[spot_info_idx] += f" | PEAK-THERMIK: {max_climb} m/s bis {max_climb_h}m MSL"
            lines.extend(hourly_lines)
            lines.append("")

        # Föhn-Info
        lines.append(self._format_foehn_info())

        return "\n".join(lines)

    def _calculate_thermal_raw(self, data, pl_data, elevation_m, timestamp, spot):
        """Berechnet Thermik-Proxy für eine Stunde eines Spots und gibt das Roh-Ergebnis zurück."""
        p_levels = []
        for level in config.PRESSURE_LEVELS:
            h_val = pl_data.get(f"geopotential_height_{level}hPa")
            t_val = pl_data.get(f"temperature_{level}hPa")
            if h_val is not None and t_val is not None:
                p_levels.append({"pressure": level, "height": h_val, "temp": t_val})

        surf_dew = calculate_dewpoint(
            data.get("temperature_2m"), data.get("relative_humidity_2m", 50)
        )

        therm = calculate_thermal_profile(
            surface_temp=data.get("temperature_2m"),
            surface_dewpoint=surf_dew,
            elevation_m=elevation_m,
            pressure_levels_data=p_levels,
            boundary_layer_height_agl=data.get("boundary_layer_height"),
            sunshine_duration_s=data.get("sunshine_duration"),
            surface_sensible_heat_flux=data.get("surface_sensible_heat_flux"),
            surface_latent_heat_flux=data.get("surface_latent_heat_flux"),
            shortwave_radiation=data.get("shortwave_radiation"),
            direct_radiation=data.get("direct_radiation"),
            diffuse_radiation=data.get("diffuse_radiation"),
            soil_moisture=data.get("soil_moisture_0_to_1cm"),
            soil_temperature=data.get("soil_temperature_0cm"),
            updraft=data.get("updraft"),
            et0=data.get("et0_fao_evapotranspiration"),
            vpd=data.get("vapour_pressure_deficit"),
            lifted_index=data.get("lifted_index"),
            convective_inhibition=data.get("convective_inhibition"),
            snow_depth=data.get("snow_depth"),
            timestamp=timestamp,
            slope_azimuth=spot.get("slope_azimuth"),
            slope_angle=spot.get("slope_angle"),
            low_cloud=data.get("cloud_cover_low", 0),
            mid_cloud=data.get("cloud_cover_mid", 0),
            high_cloud=data.get("cloud_cover_high", 0),
        )
        return therm

    def _calculate_thermal_for_hour(self, data, pl_data, elevation_m, timestamp, spot):
        """Berechnet Thermik-Proxy für eine Stunde eines Spots."""
        therm = self._calculate_thermal_raw(data, pl_data, elevation_m, timestamp, spot)

        if "error" not in therm:
            climb = therm["climb_rate"]
            max_h = therm["max_height"]
            lcl = therm.get("lcl")
            lcl_str = f", LCL/Basis {lcl}m" if lcl else ""
            return (
                f" | THERMIK-PROXY: {climb} m/s bis {max_h}m MSL"
                f"{lcl_str} (Güte: {therm['rating']}/10)"
            )
        return ""

    def _format_foehn_info(self) -> str:
        """Formatiert Föhn-Indikatoren als Text."""
        if not self.foehn_data:
            return "═══ FÖHN-INDIKATOR ═══\nKeine Föhn-Daten verfügbar."

        nord = self.foehn_data.get("nord", {})
        sued = self.foehn_data.get("sued", {})

        if not nord or not sued:
            return "═══ FÖHN-INDIKATOR ═══\nKeine Föhn-Daten verfügbar."

        ev = evaluate_foehn(nord, sued)
        lines = [
            "═══ FÖHN-INDIKATOR ═══",
            f"Level: {ev['label']} | Delta-P: {ev['delta_p_hpa']} hPa | "
            f"Kammwind: {ev['crest_wind_kmh']} km/h aus {ev['crest_dir_deg']}°",
            f"Luftfeuchtigkeit Nord: {ev['humidity_nord']}%",
            ev["message"],
        ]
        if ev.get("indicators"):
            for ind in ev["indicators"]:
                lines.append(f"  - {ind}")
        return "\n".join(lines)

    def _get_forecast_dates(self) -> list:
        """Ermittelt verfügbare Vorhersage-Tage aus den Wetterdaten (nur Heute + Zukunft)."""
        dates = set()
        now = datetime.now()
        today_str = now.strftime("%Y-%m-%d")
        
        for spot_name, spot_data in self.weather_data.items():
            if spot_name == "_meta":
                continue
            for timestamp in spot_data.get("hourly_data", {}).keys():
                try:
                    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    date_str = dt.strftime("%Y-%m-%d")
                    # Nur heute und Zukunft
                    if date_str >= today_str:
                        if config.FLIGHT_HOURS_START <= dt.hour < config.FLIGHT_HOURS_END:
                            dates.add(date_str)
                except Exception:
                    pass
        return sorted(dates)

    def _build_single_spot_context(self, spot, date_str: str, mode: str = "chat") -> str:
        """
        Baut Wetterkontext für EINEN Spot an EINEM Tag.
        mode="chat": Filtert vergangene Stunden aus (für aktuelle Anfragen).
        mode="dashboard": Zeigt alle Stunden des Tages (10-17) für die Analyse.
        """
        if not self.weather_data:
            return ""

        name = spot["name"]
        spot_data = self.weather_data.get(name)
        if not spot_data:
            return f"Keine Wetterdaten für {name} verfügbar."

        meta = self.weather_data.get("_meta", {})
        updated = meta.get("last_updated", "unbekannt")

        # Erlaubten Windsektor als Gradzahlen berechnen
        wind_ranges = self._parse_wind_range(spot["windrichtung"])
        if wind_ranges:
            range_parts = []
            for start, end in wind_ranges:
                range_parts.append(f"{start:.0f}°-{end:.0f}°")
            wind_degrees = " (" + ", ".join(range_parts) + " inkl. 10° Buffer)"
        else:
            wind_degrees = ""

        lines = [
            f"WETTERDATEN FÜR: {name} — TAG: {date_str} (Stand: {updated})",
            f"═══ SPOT: {name} ({spot['fluggebiet']}, {spot['region']}) ═══",
            f"Höhe: {spot['elevation_m']}m MSL | "
            f"Windrichtung erlaubt: {spot['windrichtung']}{wind_degrees} | "
            f"Max. Wind: {spot['ideal_wind_max']} km/h | "
            f"Kritischer Föhn: {spot['kritischer_foehn']}",
        ]
        if spot.get("bemerkung"):
            lines.append(f"Bemerkung: {spot['bemerkung']}")

        hourly_data = spot_data.get("hourly_data", {})
        pressure_level_data = spot_data.get("pressure_level_data", {})
        elevation_m = spot["elevation_m"]

        sorted_times = sorted(hourly_data.keys())
        now = datetime.now()
        has_data = False
        wind_ok_hours = []
        wind_wrong_hours = []

        for timestamp in sorted_times:
            try:
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                # Nur den angefragten Tag
                if dt.strftime("%Y-%m-%d") != date_str:
                    continue
                
                # Im Chat-Modus: Vergangene Stunden ausblenden
                if mode == "chat":
                    if dt.timestamp() < (now.timestamp() - 3600):
                        continue
                
                # Immer: Nur Flugstunden
                if not (config.FLIGHT_HOURS_START <= dt.hour < config.FLIGHT_HOURS_END):
                    continue
            except Exception:
                continue

            has_data = True
            data = hourly_data[timestamp]
            time_str = timestamp.replace("T", " ")[:16]

            thermal_info = ""
            try:
                therm = self._calculate_thermal_raw(
                    data, pressure_level_data.get(timestamp, {}),
                    elevation_m, timestamp, spot
                )
                if therm and "error" not in therm:
                    h_climb = therm["climb_rate"]
                    h_max_h = therm["max_height"]
                    lcl = therm.get("lcl")
                    lcl_str = f", LCL/Basis {lcl}m" if lcl else ""
                    thermal_info = f" | THERMIK-PROXY: {h_climb} m/s bis {h_max_h}m MSL{lcl_str} (Güte: {therm['rating']}/10)"
            except Exception as e:
                thermal_info = f" | Thermik-Fehler: {e}"

            temp = data.get("temperature_2m", "N/A")
            wind_speed = data.get("wind_speed_10m", "N/A")
            wind_dir = data.get("wind_direction_10m", "N/A")
            wind_gusts = data.get("wind_gusts_10m", "N/A")
            cloud_base_raw = data.get("cloud_base")
            cloud_base = f"{cloud_base_raw}m" if cloud_base_raw is not None else "wolkenfrei"
            cloud_cover = data.get("cloud_cover", "N/A")

            is_ok = self._is_wind_in_range(wind_dir, spot["windrichtung"])
            wind_status = "[WIND-OK]" if is_ok else "[WIND-WRONG]"

            warnings = []
            if isinstance(wind_gusts, (int, float)) and isinstance(wind_speed, (int, float)):
                if wind_gusts - wind_speed > 15:
                    warnings.append("[GUST-WARN]")
            
            try:
                precip = data.get("precipitation")
                if isinstance(precip, (int, float)) and precip > 0:
                    warnings.append("[RAIN-WARN]")
            except Exception:
                pass

            hour_str = f"{dt.hour:02d}:00"
            if is_ok:
                wind_ok_hours.append(hour_str)
            else:
                wind_wrong_hours.append(hour_str)

            # Höhenwind-Info für Föhn-Erkennung (850hPa / ~1500m)
            alt_wind_info = ""
            pl_data = pressure_level_data.get(timestamp, {})
            if pl_data:
                for level in [850, 700]:
                    h_val = pl_data.get(f"geopotential_height_{level}hPa")
                    ws = pl_data.get(f"wind_speed_{level}hPa")
                    wd = pl_data.get(f"wind_direction_{level}hPa")
                    if h_val is not None and ws is not None and wd is not None:
                        alt_wind_info += f" | {level}hPa({int(h_val)}m): {ws:.0f}km/h aus {wd:.0f}°"
                        if (level == 850 and ws > 35) or (level == 700 and ws > 45):
                            if "[ALOFT-WARN]" not in warnings:
                                warnings.append("[ALOFT-WARN]")

            try:
                cape = data.get("cape")
                if isinstance(cape, (int, float)) and cape > 800:
                    warnings.append("[CAPE-WARN]")
            except Exception:
                pass

            if isinstance(cloud_cover, (int, float)) and cloud_cover >= 80:
                warnings.append("[OVERCAST-WARN]")

            warning_str = " " + " ".join(warnings) if warnings else ""

            lines.append(
                f"{time_str}: Temp {temp}°C | Wind {wind_speed}km/h aus {wind_dir}° (Böen {wind_gusts}km/h) {wind_status}{warning_str} | "
                f"Wolkenbasis {cloud_base} | Bewölkung {cloud_cover}%{alt_wind_info}{thermal_info}"
            )

        if not has_data:
            return ""

        # Wind-Tag-Zusammenfassung (damit die LLM es nicht übersehen kann)
        lines.append("")
        lines.append("═══ WIND-ZUSAMMENFASSUNG (verbindlich!) ═══")
        lines.append(f"[WIND-OK] Stunden ({len(wind_ok_hours)}): {', '.join(wind_ok_hours) if wind_ok_hours else 'KEINE'}")
        lines.append(f"[WIND-WRONG] Stunden ({len(wind_wrong_hours)}): {', '.join(wind_wrong_hours) if wind_wrong_hours else 'KEINE'}")
        if wind_ok_hours:
            lines.append(f"→ Es gibt ein fliegbares Fenster! Status sollte green oder orange sein.")
        else:
            lines.append(f"→ Kein fliegbares Fenster. Status sollte not_safe sein.")

        # Föhn-Info anhängen
        lines.append("")
        lines.append(self._format_foehn_info())

        return "\n".join(lines)

    def _safety_check_single_spot_day(self, spot, date_str: str, context: str) -> dict:
        """Phase 1: Reiner Sicherheitscheck für einen Spot/Tag via LLM."""
        name = spot["name"]
        try:
            if not context:
                return {"spot": name, "date": date_str, "safety_status": "error", "error": "Keine Daten für diesen Tag"}

            messages = [
                {"role": "system", "content": SAFETY_CHECK_PROMPT},
                {"role": "user", "content": (
                    f"AKTUELLE LOKALZEIT: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                    f"{context}"
                )},
            ]

            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.2,
                max_tokens=400,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content
            result = json.loads(raw)
            result["spot"] = name
            result["date"] = date_str
            result["phase"] = "safety"
            return result

        except Exception as e:
            logger.error(f"Safety-Check für {name}/{date_str} fehlgeschlagen: {e}")
            return {"spot": name, "date": date_str, "safety_status": "error", "phase": "safety", "error": str(e)}

    def _flyability_single_spot_day(self, spot, date_str: str, safety_result: dict, context: str) -> dict:
        """Phase 2: Flugtauglichkeit für einen bereits als sicher eingestuften Spot/Tag."""
        name = spot["name"]
        try:
            if not context:
                return {"spot": name, "date": date_str, "status": "error", "error": "Keine Daten für diesen Tag"}

            safe_window = safety_result.get("safe_window", "unbekannt")
            safety_status = safety_result.get("safety_status", "safe")
            caution_notes = safety_result.get("caution_notes", [])

            safety_context = (
                f"\n═══ SICHERHEITSANALYSE (bereits geprüft) ═══\n"
                f"Safety-Status: {safety_status}\n"
                f"Sicheres Fenster: {safe_window}\n"
            )
            if caution_notes:
                safety_context += f"Vorsichtshinweise: {', '.join(caution_notes)}\n"
            safety_context += "Analysiere NUR die Stunden innerhalb des sicheren Fensters.\n"

            messages = [
                {"role": "system", "content": FLYABILITY_PROMPT},
                {"role": "user", "content": (
                    f"AKTUELLE LOKALZEIT: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                    f"{context}\n{safety_context}"
                )},
            ]

            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.3,
                max_tokens=500,
                response_format={"type": "json_object"},
            )
            raw = response.choices[0].message.content
            result = json.loads(raw)
            result["spot"] = name
            result["date"] = date_str
            result["phase"] = "flyability"
            return result

        except Exception as e:
            logger.error(f"Flyability-Analyse für {name}/{date_str} fehlgeschlagen: {e}")
            return {"spot": name, "date": date_str, "status": "error", "phase": "flyability", "error": str(e)}

    def run_spot_analyses(self) -> dict:
        """Zweiphasen-Orchestrierung: Safety → Filter → Flyability."""
        if not self.client:
            return {"success": False, "error": "OPENAI_API_KEY nicht konfiguriert"}

        if not self.weather_data:
            return {"success": False, "error": "Keine Wetterdaten geladen"}

        spots_to_analyze = [s for s in self.spots if s["name"] in self.weather_data]
        missing = [s["name"] for s in self.spots if s["name"] not in self.weather_data]
        if missing:
            logger.warning(f"Keine Wetterdaten für {len(missing)} Spots: {missing} – lade Wetter neu...")
            try:
                self.refresh_weather(force=True)
                spots_to_analyze = [s for s in self.spots if s["name"] in self.weather_data]
            except Exception as e:
                logger.error(f"Wetter-Refresh fehlgeschlagen: {e}")
        if not spots_to_analyze:
            return {"success": False, "error": "Keine Spots mit Wetterdaten"}

        forecast_dates = self._get_forecast_dates()
        if not forecast_dates:
            return {"success": False, "error": "Keine Vorhersage-Tage verfügbar"}

        spots_by_name = {s["name"]: s for s in spots_to_analyze}

        # ── PHASE 1: Safety-Checks (alle Spots parallel) ──
        total_safety = len(spots_to_analyze) * len(forecast_dates)
        logger.info(f"Phase 1 (Safety): {len(spots_to_analyze)} Spots × {len(forecast_dates)} Tage = {total_safety} Aufrufe")

        safety_results = {}  # {spot_name: {date_str: safety_dict}}

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {}
            for spot in spots_to_analyze:
                for date_str in forecast_dates:
                    ctx = self._build_single_spot_context(spot, date_str, mode="dashboard")
                    if ctx:
                        future = executor.submit(self._safety_check_single_spot_day, spot, date_str, ctx)
                        futures[future] = (spot["name"], date_str)

            for future in as_completed(futures):
                spot_name, date_str = futures[future]
                try:
                    result = future.result()
                except Exception as e:
                    logger.error(f"Safety-Future für {spot_name}/{date_str} fehlgeschlagen: {e}")
                    result = {"spot": spot_name, "date": date_str, "safety_status": "error", "error": str(e)}
                safety_results.setdefault(spot_name, {})[date_str] = result

        # ── FILTER: Welche Spot/Tag-Kombis brauchen Phase 2? ──
        flyability_tasks = []
        for spot_name, days in safety_results.items():
            for date_str, safety in days.items():
                status = safety.get("safety_status", "error")
                if status in ("safe", "conditional"):
                    flyability_tasks.append((spots_by_name[spot_name], date_str, safety))

        logger.info(f"Phase 1 fertig. {len(flyability_tasks)} von {total_safety} Spot/Tag-Kombis sind sicher → Phase 2")

        # ── PHASE 2: Flyability (nur sichere Spots parallel) ──
        flyability_results = {}  # {spot_name: {date_str: flyability_dict}}

        if flyability_tasks:
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = {}
                for spot, date_str, safety in flyability_tasks:
                    ctx = self._build_single_spot_context(spot, date_str, mode="dashboard")
                    future = executor.submit(self._flyability_single_spot_day, spot, date_str, safety, ctx)
                    futures[future] = (spot["name"], date_str)

                for future in as_completed(futures):
                    spot_name, date_str = futures[future]
                    try:
                        result = future.result()
                    except Exception as e:
                        logger.error(f"Flyability-Future für {spot_name}/{date_str} fehlgeschlagen: {e}")
                        result = {"spot": spot_name, "date": date_str, "status": "error", "error": str(e)}
                    flyability_results.setdefault(spot_name, {})[date_str] = result

        # ── MERGE: Beide Phasen zusammenführen ──
        merged = {}
        for spot_name, days in safety_results.items():
            merged[spot_name] = {}
            for date_str, safety in days.items():
                entry = {"safety": safety}
                fly = flyability_results.get(spot_name, {}).get(date_str)
                if fly:
                    entry["flyability"] = fly
                # Abgeleiteter Gesamtstatus für Abwärtskompatibilität
                safety_status = safety.get("safety_status", "error")
                if safety_status == "not_safe":
                    entry["status"] = "not_safe"
                elif safety_status == "error":
                    entry["status"] = "error"
                elif fly:
                    entry["status"] = fly.get("status", "orange")
                else:
                    entry["status"] = "orange"
                entry["best_window"] = safety.get("safe_window", "keins")
                entry["recommendation"] = ""
                if fly:
                    entry["recommendation"] = fly.get("recommendation", "")
                    entry["best_window"] = fly.get("best_window", entry["best_window"])
                merged[spot_name][date_str] = entry

        self.spot_analyses = merged
        self.analyses_loaded_at = datetime.now()

        if self.instantdb:
            threading.Thread(target=self._push_analyses_to_instantdb, daemon=True).start()

        # Summary bauen
        per_day_counts = {}
        for date_str in forecast_dates:
            counts = {"green": 0, "orange": 0, "yellow": 0, "not_safe": 0, "error": 0}
            for spot_name, days in merged.items():
                s = days.get(date_str, {}).get("status", "error")
                if s in counts:
                    counts[s] += 1
                else:
                    counts["error"] += 1
            per_day_counts[date_str] = counts

        total_calls = total_safety + len(flyability_tasks)
        logger.info(f"Spot-Analysen abgeschlossen: {total_calls} LLM-Aufrufe ({total_safety} Safety + {len(flyability_tasks)} Flyability)")

        results_summary = {}
        for spot_name, days in merged.items():
            results_summary[spot_name] = {}
            for date_str, entry in days.items():
                results_summary[spot_name][date_str] = {
                    "status": entry.get("status", "error"),
                    "safety_status": entry.get("safety", {}).get("safety_status", "error"),
                    "best_window": entry.get("best_window", "?"),
                    "recommendation": entry.get("recommendation", ""),
                }

        return {
            "success": True,
            "results_count": total_calls,
            "safety_count": total_safety,
            "flyability_count": len(flyability_tasks),
            "spots_count": len(merged),
            "dates": forecast_dates,
            "per_day_counts": per_day_counts,
            "results_summary": results_summary,
        }

    def _push_analyses_to_instantdb(self):
        """Pusht Spot-Analysen nach InstantDB (Hintergrund-Thread)."""
        try:
            docs = {}
            for spot_name, days in self.spot_analyses.items():
                for date_str, entry in days.items():
                    doc_id = self.instantdb.make_id(f"spot_analysis.{spot_name}.{date_str}")
                    doc_data = {
                        "spot": spot_name,
                        "date": date_str,
                        "status": entry.get("status", "error"),
                        "best_window": entry.get("best_window", "?"),
                        "updated_at": self.analyses_loaded_at.isoformat(),
                    }
                    safety = entry.get("safety", {})
                    doc_data["safety_status"] = safety.get("safety_status", "error")
                    doc_data["safe_window"] = safety.get("safe_window", "keins")
                    doc_data["safety_feedback"] = safety.get("summary", "")
                    for key in ["no_go_reasons", "caution_notes"]:
                        val = safety.get(key, [])
                        if isinstance(val, list):
                            doc_data[key] = json.dumps(val, ensure_ascii=False)
                        else:
                            doc_data[key] = str(val)
                    doc_data["foehn_risk"] = safety.get("foehn_risk", "none")
                    doc_data["wind_summary"] = safety.get("wind_summary", "")

                    fly = entry.get("flyability", {})
                    if fly:
                        doc_data["fly_status"] = fly.get("status", "")
                        doc_data["flight_type"] = fly.get("flight_type", "")
                        doc_data["flight_duration"] = fly.get("flight_duration_estimate", "")
                        doc_data["xc_potential"] = fly.get("xc_potential", "")
                        doc_data["peak_climb_rate"] = fly.get("peak_climb_rate", 0)
                        doc_data["flyability_feedback"] = fly.get("recommendation", "")

                    docs[doc_id] = doc_data

            if self.instantdb.batch_upsert("spot_analyses", docs):
                logger.info(f"InstantDB: {len(docs)} Spot-Analysen gepusht")
            else:
                logger.warning("InstantDB: Spot-Analysen push fehlgeschlagen")
        except Exception as e:
            logger.error(f"InstantDB Analysen-Push fehlgeschlagen: {e}")

    def _build_analyses_context(self) -> str:
        """Formatiert Voranalysen zweistufig: Sicherheit zuerst, dann Flugtauglichkeit."""
        if not self.spot_analyses:
            return ""

        lines = [
            "VORANALYSEN (Zweiphasen-Analyse: Sicherheit → Flugtauglichkeit)",
            f"Stand: {self.analyses_loaded_at.isoformat() if self.analyses_loaded_at else 'unbekannt'}",
            "",
        ]

        all_dates = set()
        for days in self.spot_analyses.values():
            all_dates.update(days.keys())
        sorted_dates = sorted(all_dates)

        for date_str in sorted_dates:
            lines.append(f"╔══════════════════════════════════════════╗")
            lines.append(f"║  TAG: {date_str}")
            lines.append(f"╚══════════════════════════════════════════╝")

            # ── BLOCK 1: SICHERHEITSÜBERSICHT ──
            lines.append("")
            lines.append("─── PHASE 1: SICHERHEITSCHECK ───")
            lines.append("")

            safe_spots_today = []

            for name in sorted(self.spot_analyses.keys()):
                entry = self.spot_analyses[name].get(date_str)
                if not entry:
                    continue

                safety = entry.get("safety", {})
                safety_status = safety.get("safety_status", entry.get("status", "?"))

                if safety_status == "error":
                    lines.append(f"  {name}: FEHLER — {safety.get('error', entry.get('error', 'unbekannt'))}")
                    continue

                status_label = {
                    "safe": "SICHER",
                    "conditional": "BEDINGT SICHER",
                    "not_safe": "NICHT SICHER",
                }.get(safety_status, safety_status)

                safe_window = safety.get("safe_window", entry.get("best_window", "?"))
                lines.append(f"  {name}: {status_label} (Fenster: {safe_window})")

                no_go = safety.get("no_go_reasons", [])
                if isinstance(no_go, str):
                    no_go = [no_go] if no_go else []
                if no_go:
                    lines.append(f"    NO-GO: {', '.join(no_go)}")

                caution = safety.get("caution_notes", [])
                if isinstance(caution, str):
                    caution = [caution] if caution else []
                if caution:
                    lines.append(f"    Vorsicht: {', '.join(caution)}")

                wind_summary = safety.get("wind_summary", "")
                if wind_summary:
                    lines.append(f"    Wind: {wind_summary}")

                wind_shear = safety.get("wind_shear", "")
                if wind_shear:
                    lines.append(f"    Höhenwind: {wind_shear}")

                foehn_risk = safety.get("foehn_risk", "none")
                if foehn_risk not in ("none", ""):
                    lines.append(f"    Föhn-Risiko: {foehn_risk}")

                if safety_status in ("safe", "conditional"):
                    safe_spots_today.append(name)

            # ── BLOCK 2: FLUGTAUGLICHKEIT (nur sichere Spots) ──
            if safe_spots_today:
                lines.append("")
                lines.append("─── PHASE 2: FLUGTAUGLICHKEIT (nur sichere Spots) ───")
                lines.append("")

                for name in safe_spots_today:
                    entry = self.spot_analyses[name].get(date_str, {})
                    fly = entry.get("flyability", {})

                    if not fly:
                        lines.append(f"  {name}: Keine Flyability-Daten")
                        continue

                    fly_status = fly.get("status", "?")
                    status_label = {
                        "green": "GRÜN",
                        "orange": "ORANGE",
                        "yellow": "GELB",
                    }.get(fly_status, fly_status)

                    lines.append(f"  ═══ {name}: {status_label} ═══")

                    flight_type = fly.get("flight_type", "")
                    duration = fly.get("flight_duration_estimate", "?")
                    lines.append(f"    Flugtyp: {flight_type} | Dauer: {duration}")

                    thermal = fly.get("thermal_quality", "")
                    if thermal:
                        lines.append(f"    Thermik: {thermal}")

                    peak = fly.get("peak_climb_rate", 0)
                    lines.append(f"    Peak-Steigen: {peak} m/s")

                    xc = fly.get("xc_potential", "low")
                    xc_details = fly.get("xc_details", "")
                    lines.append(f"    XC-Potenzial: {xc}")
                    if xc_details:
                        lines.append(f"    XC-Details: {xc_details}")

                    soaring = fly.get("soaring_options", "")
                    if soaring:
                        lines.append(f"    Soaring: {soaring}")

                    bemerkung = fly.get("bemerkung_check", "")
                    if bemerkung:
                        lines.append(f"    Bemerkungen: {bemerkung}")

                    rec = fly.get("recommendation", "")
                    if rec:
                        lines.append(f"    Empfehlung: {rec}")

                    conf = fly.get("confidence", "")
                    if conf:
                        lines.append(f"    Konfidenz: {conf}")

                    lines.append("")
            else:
                lines.append("")
                lines.append("─── PHASE 2: Entfällt (keine sicheren Spots an diesem Tag) ───")
                lines.append("")

        return "\n".join(lines)

    def _ensure_spot_analyses(self):
        """Lädt Spot-Analysen aus InstantDB falls lokal nicht vorhanden."""
        if self.spot_analyses:
            return
        if not self.instantdb:
            return
        try:
            result = self.instantdb.query("spot_analyses")
            if result and "spot_analyses" in result:
                for entry in result["spot_analyses"]:
                    spot_name = entry.get("spot")
                    date_str = entry.get("date")
                    if not (spot_name and date_str):
                        continue

                    for key in ["no_go_reasons", "caution_notes"]:
                        if key in entry and isinstance(entry[key], str):
                            try:
                                entry[key] = json.loads(entry[key])
                            except Exception:
                                pass

                    # Rekonstruiere die zweiphasige Struktur aus dem flachen InstantDB-Format
                    safety = {
                        "safety_status": entry.get("safety_status", "error"),
                        "safe_window": entry.get("safe_window", "keins"),
                        "no_go_reasons": entry.get("no_go_reasons", []),
                        "caution_notes": entry.get("caution_notes", []),
                        "foehn_risk": entry.get("foehn_risk", "none"),
                        "wind_summary": entry.get("wind_summary", ""),
                    }
                    merged_entry = {
                        "safety": safety,
                        "status": entry.get("status", "error"),
                        "best_window": entry.get("best_window", "?"),
                        "recommendation": entry.get("recommendation", ""),
                    }
                    if entry.get("fly_status"):
                        merged_entry["flyability"] = {
                            "status": entry.get("fly_status", ""),
                            "flight_type": entry.get("flight_type", ""),
                            "flight_duration_estimate": entry.get("flight_duration", ""),
                            "xc_potential": entry.get("xc_potential", ""),
                            "peak_climb_rate": entry.get("peak_climb_rate", 0),
                        }

                    self.spot_analyses.setdefault(spot_name, {})[date_str] = merged_entry

                if self.spot_analyses:
                    first_days = next(iter(self.spot_analyses.values()))
                    first_entry = next(iter(first_days.values()))
                    updated = first_entry.get("safety", {}).get("updated_at") or entry.get("updated_at")
                    if updated:
                        try:
                            self.analyses_loaded_at = datetime.fromisoformat(updated)
                        except Exception:
                            pass
                    total = sum(len(days) for days in self.spot_analyses.values())
                    logger.info(f"Spot-Analysen aus InstantDB geladen: {len(self.spot_analyses)} Spots, {total} Einträge")
        except Exception as e:
            logger.error(f"InstantDB spot_analyses Fallback fehlgeschlagen: {e}")

    def _push_to_instantdb(self):
        """Pusht Wetter-Kontext und Summary nach InstantDB (laeuft im Hintergrund)."""
        try:
            timestamp = self.weather_loaded_at.isoformat() if self.weather_loaded_at else datetime.now().isoformat()
            data = {
                "matrix_text": self.weather_context_str,
                "updated_at": timestamp,
            }

            global_id = self.instantdb.make_id("weather_state.global")
            self.instantdb.upsert("weather_state", global_id, data)
            logger.info("InstantDB: weather_state gepusht")

            # Keine automatische Summary mehr
            # summary = self._generate_summary()
            # if summary:
            #     self.instantdb.upsert("weather_state", "global", {"summary_text": summary})
            #     logger.info("InstantDB: summary_text gepusht")

        except Exception as e:
            logger.error(f"InstantDB push fehlgeschlagen: {e}")

    def analyze_weather(self) -> str:
        """Manuelle Analyse wurde deaktiviert."""
        return "Die Vor-Zusammenfassung wurde deaktiviert. Nutze bitte den Chat für eine direkte Analyse der Daten."

    def reload_spots(self):
        """Laedt Spots neu aus CSV und synchronisiert nach InstantDB."""
        self.spots = load_spots()
        logger.info(f"Spots neu geladen: {len(self.spots)} Spots aus CSV")
        self.sync_spots_to_instantdb()
        return len(self.spots)

    def sync_spots_to_instantdb(self):
        """Pusht alle Spots einmalig nach InstantDB."""
        if not self.instantdb:
            return

        docs = {}
        for spot in self.spots:
            spot_id = self.instantdb.make_id(f"spot.{spot['name']}")
            docs[spot_id] = {
                "name": spot["name"],
                "elevation": spot["elevation_m"],
                "wind_ok": spot["windrichtung"],
                "ideal_wind_min": spot.get("ideal_wind_min"),
                "ideal_wind_max": spot.get("ideal_wind_max"),
                "slope_azimuth": spot["slope_azimuth"],
                "slope_angle": spot["slope_angle"],
                "kritischer_foehn": spot["kritischer_foehn"],
                "lat": spot["latitude"],
                "lon": spot["longitude"],
                "bemerkung": spot.get("bemerkung", ""),
            }

        if self.instantdb.batch_upsert("spots", docs):
            logger.info(f"InstantDB: {len(docs)} Spots synchronisiert")
        else:
            logger.warning("InstantDB: Spots-Sync fehlgeschlagen")

    def _get_or_create_conversation(self, session_id: str) -> list:
        """Holt bestehende Conversation oder erstellt neue mit globalem Kontext."""
        if session_id in self.conversations:
            return self.conversations[session_id]["messages"]

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
        ]
        self.conversations[session_id] = {
            "messages": messages,
            "last_activity": datetime.now().isoformat(),
            "first_question": True,
        }
        return messages

    def _ensure_weather_context(self):
        """Stellt sicher dass weather_context_str vorhanden ist. Fallback: InstantDB."""
        if self.weather_context_str:
            return
        if not self.instantdb:
            return
        try:
            global_id = self.instantdb.make_id("weather_state.global")
            result = self.instantdb.query("weather_state")
            if result and "weather_state" in result:
                for entry in result["weather_state"]:
                    matrix = entry.get("matrix_text")
                    if matrix:
                        self.weather_context_str = matrix
                        logger.info("Wetterdaten aus InstantDB weather_state geladen")
                        return
        except Exception as e:
            logger.error(f"InstantDB weather_state Fallback fehlgeschlagen: {e}")

    def answer(self, session_id: str, question: str) -> str:
        """Beantwortet eine Pilotenfrage. Wetterdaten sind im Kontext."""
        if not self.client:
            return "Fehler: OPENAI_API_KEY nicht konfiguriert."

        # Sicherstellen dass Wetterdaten verfügbar sind (Fallback: InstantDB)
        self._ensure_weather_context()

        if not self.weather_context_str:
            return "Wetterdaten werden geladen... Bitte versuche es gleich nochmal."

        # Spot-Analysen aus InstantDB laden falls lokal nicht vorhanden
        self._ensure_spot_analyses()

        messages = self._get_or_create_conversation(session_id)
        conv = self.conversations[session_id]

        # Erste Frage: Kontext automatisch mitsenden
        if conv["first_question"]:
            # Voranalysen vorhanden? → Kompakte Analysen statt Rohdaten
            analyses_context = self._build_analyses_context()
            if analyses_context:
                context_block = analyses_context
            else:
                context_block = self.weather_context_str

            user_content = (
                f"AKTUELLE LOKALZEIT: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                "Hier sind die aktuellen Wetterdaten und Analysen für deine Beratung:\n"
                "==========================================================\n"
                f"{context_block}\n"
                "==========================================================\n\n"
                f"Frage des Piloten: {question}"
            )
            conv["first_question"] = False
        else:
            user_content = question

        messages.append({"role": "user", "content": user_content})

        # Token-Management: History trimmen wenn zu lang
        if len(messages) > MAX_HISTORY_MESSAGES:
            # Behalte System-Prompt + erste User-Message (mit Wetterdaten) + letzte N Messages
            messages[:] = messages[:2] + messages[-(MAX_HISTORY_MESSAGES - 2):]

        # OpenAI API Call
        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=messages,
                temperature=0.7,
                max_tokens=2000,
            )
            reply = response.choices[0].message.content
        except Exception as e:
            logger.error(f"OpenAI API Fehler: {e}")
            reply = f"Entschuldigung, es gab einen Fehler bei der Verarbeitung: {e}"

        messages.append({"role": "assistant", "content": reply})
        conv["last_activity"] = datetime.now().isoformat()
        self._save_conversation(session_id)

        return reply

    def reset_conversation(self, session_id: str):
        """Conversation zurücksetzen."""
        if session_id in self.conversations:
            del self.conversations[session_id]

        # Datei löschen
        path = self.history_dir / f"{session_id}.json"
        if path.exists():
            path.unlink()

    def cleanup_old_conversations(self, max_age_hours=24):
        """Entfernt inaktive Conversations."""
        now = datetime.now()
        to_remove = []
        for sid, conv in self.conversations.items():
            try:
                last = datetime.fromisoformat(conv["last_activity"])
                age = (now - last).total_seconds() / 3600
                if age > max_age_hours:
                    to_remove.append(sid)
            except Exception:
                to_remove.append(sid)
        for sid in to_remove:
            del self.conversations[sid]
        if to_remove:
            print(f"[ENGINE] {len(to_remove)} alte Conversations bereinigt")

    def get_spots_geojson(self):
        """Gibt alle Spots als GeoJSON FeatureCollection zurück."""
        from source_area import get_reference_points

        features = []
        for spot in self.spots:
            spot_name = spot["name"]
            ref_points = None
            if spot_name in self.weather_data and "reference_points" in self.weather_data[spot_name]:
                ref_points = self.weather_data[spot_name]["reference_points"]
            if ref_points is None:
                ref_points = get_reference_points(
                    spot_name, spot["latitude"], spot["longitude"], quiet=True
                )

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [spot["longitude"], spot["latitude"]],
                },
                "properties": {
                    "name": spot["name"],
                    "region": spot["region"],
                    "fluggebiet": spot["fluggebiet"],
                    "elevation_m": spot["elevation_m"],
                    "windrichtung": spot["windrichtung"],
                    "bemerkung": spot.get("bemerkung", ""),
                    "reference_points": ref_points,
                },
            })
        return {"type": "FeatureCollection", "features": features}

    def _is_wind_in_range(self, wind_dir, sector_str, buffer=10):
        """Prüft ob Windrichtung im erlaubten Sektor liegt (inkl. Buffer)."""
        if not isinstance(wind_dir, (int, float)) or not sector_str:
            return True # Fallback: LLM soll entscheiden wenn Daten fehlen
            
        ranges = self._parse_wind_range(sector_str)
        if not ranges:
            return True
            
        for start, end in ranges:
            # Buffer anwenden
            s_buf = (start - buffer) % 360
            e_buf = (end + buffer) % 360
            
            if s_buf <= e_buf:
                if s_buf <= wind_dir <= e_buf:
                    return True
            else: # Wrap around
                if wind_dir >= s_buf or wind_dir <= e_buf:
                    return True
        return False

    def _parse_wind_range(self, range_str):
        """Konvertiert 'NW-SW' oder 'O' in [(Winkel_Start, Winkel_Ende)]."""
        parts = re.split(r'[-/]', range_str.upper())
        angles = []
        for p in parts:
            p = p.strip()
            if p in COMPASS_POINTS:
                angles.append(COMPASS_POINTS[p])
            else:
                # Versuche nur Buchstaben zu extrahieren (falls 'NW (leicht)' drinstünde)
                match = re.search(r'([A-Z]+)', p)
                if match and match.group(1) in COMPASS_POINTS:
                    angles.append(COMPASS_POINTS[match.group(1)])
        
        if len(angles) == 1:
            # Einzelsektor: Gib +/- 45 Grad Bereich
            return [( (angles[0]-45)%360, (angles[0]+45)%360 )]
        elif len(angles) >= 2:
            # Mehrere Teile: Erzeuge Sektoren
            res = []
            for i in range(len(angles)-1):
                start, end = angles[i], angles[i+1]
                # Richtungsentscheidung: Der kleinere Weg (<= 180 Grad)
                diff = (end - start) % 360
                if diff > 180:
                    # Tausche start/end um den kleineren Sektor zu nehmen
                    res.append((end, start))
                else:
                    res.append((start, end))
            return res
        return []
