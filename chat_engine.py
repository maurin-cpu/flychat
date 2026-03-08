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
from datetime import datetime
from openai import OpenAI

import config
from spots import load_spots
from fetch_weather import fetch_all_spots, load_cached_weather, is_cache_fresh
from foehn_indicators import fetch_foehn_data, evaluate_foehn
from thermik_calculator import calculate_thermal_profile, calculate_dewpoint
from prompts import SYSTEM_PROMPT

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

        api_key = os.environ.get("OPENAI_API_KEY")
        self.model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        self.client = OpenAI(api_key=api_key) if api_key else None

    def refresh_weather(self):
        """Wetterdaten für alle Spots holen + Kontext-String bauen."""
        print("[ENGINE] Lade Wetterdaten für alle Spots...")
        self.spots = load_spots() # Reload spots to pick up CSV changes

        # 1. Wetterdaten holen (oder Cache nutzen)
        if is_cache_fresh(max_age_hours=12):
            print("[ENGINE] Nutze gecachte Wetterdaten")
            self.weather_data = load_cached_weather()
        else:
            self.weather_data = fetch_all_spots(self.spots)

        # 2. Föhn-Daten holen
        try:
            self.foehn_data = fetch_foehn_data(forecast_days=2)
        except Exception as e:
            logger.error(f"Föhn-Daten fehlgeschlagen: {e}")
            self.foehn_data = None

        # 3. Kontext-String bauen
        self.weather_context_str = self._build_weather_context()
        self.weather_loaded_at = datetime.now()

        # 4. Alle Conversations resetten (Daten sind veraltet)
        self.conversations = {}

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
            lines.append(
                f"Höhe: {spot['elevation_m']}m MSL | "
                f"Windrichtung erlaubt: {spot['windrichtung']} | "
                f"Idealer Wind: {spot['ideal_wind_min']}-{spot['ideal_wind_max']} km/h | "
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

                hourly_lines.append(
                    f"{time_str}: Temp {temp}°C | Wind {wind_speed}km/h aus {wind_dir}° (Böen {wind_gusts}km/h) {wind_status} | "
                    f"Wolkenbasis {cloud_base} | Bewölkung {cloud_cover}% | Sonne {sunshine_str}{thermal_info}"
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
        """Führt die LLM-Analyse manuell durch und pusht Summary nach InstantDB."""
        if not self.client:
            return "Fehler: OpenAI Client nicht initialisiert."
        logger.info("[ENGINE] Starte manuelle LLM-Wetteranalyse...")
        summary = self._generate_summary()

        if self.instantdb and summary:
            global_id = self.instantdb.make_id("weather_state.global")
            self.instantdb.upsert("weather_state", global_id, {"summary_text": summary})
            logger.info("InstantDB: summary_text (manuell) gepusht")

        return summary if summary else "Analyse abgeschlossen, aber kein Fazit generiert."

    def _generate_summary(self) -> str | None:
        """Generiert ein kurzes KI-Fazit der aktuellen Wetterlage."""
        if not self.client or not self.weather_context_str:
            return None

        try:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": "Du bist ein Gleitschirm-Wetter-Experte. Fasse die Wetterlage in 2-3 Saetzen zusammen. Fokus auf Flugbedingungen."},
                    {"role": "user", "content": f"Fasse diese Wetterdaten kurz zusammen:\n\n{self.weather_context_str[:4000]}"},
                ],
                temperature=0.5,
                max_tokens=300,
            )
            return response.choices[0].message.content
        except Exception as e:
            logger.error(f"Summary-Generierung fehlgeschlagen: {e}")
            return None

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
                "ideal_wind_min": spot["ideal_wind_min"],
                "ideal_wind_max": spot["ideal_wind_max"],
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

        messages = self._get_or_create_conversation(session_id)
        conv = self.conversations[session_id]

        # Erste Frage: Wetterdaten-Kontext automatisch mitsenden
        if conv["first_question"]:
            user_content = (
                f"AKTUELLE LOKALZEIT: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                "Hier sind die aktuellen Wetterdaten und Analysen für deine Beratung:\n"
                "==========================================================\n"
                f"{self.weather_context_str}\n"
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

        return reply

    def reset_conversation(self, session_id: str):
        """Conversation zurücksetzen."""
        if session_id in self.conversations:
            del self.conversations[session_id]

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
        features = []
        for spot in self.spots:
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
