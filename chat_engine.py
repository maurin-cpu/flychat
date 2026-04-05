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
from datetime import datetime, timedelta
from openai import OpenAI

import config
from spots import load_spots
from fetch_weather import fetch_all_spots, load_cached_weather, load_cached_weather_timestamp, is_cache_fresh, is_cache_complete, validate_spot_data
from foehn_indicators import (
    fetch_foehn_data,
    evaluate_foehn,
    build_foehn_llm_context,
)
from thermik_calculator import calculate_thermal_profile, calculate_dewpoint
from gust_calculator import (
    estimate_altitude_gusts,
    collect_gust_anchors,
    estimate_altitude_gusts_multi_anchor,
    interpolate_gust_from_anchors,
)
from prompts import (
    SYSTEM_PROMPT,
    FOEHN_CHAT_KNOWLEDGE,
    SAFETY_CHECK_PROMPT,
    FLYABILITY_PROMPT,
    REGION_SAFETY_CHECK_PROMPT,
    REGION_FLYABILITY_PROMPT,
    format_foehn_llm_regional_guide,
)
from source_area import get_all_regions, find_region_for_point

logger = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = 40  # Max messages per conversation before trimming

# Phase-2 Fliegbarkeit: gray / green / violet (Legacy: yellow/orange/green → gray/green/violet)
_FLYABILITY_TIERS = frozenset({"gray", "green", "violet"})


def _normalize_flyability_tier(raw: str | None) -> str:
    if not raw:
        return "green"
    r = str(raw).strip().lower()
    if r in _FLYABILITY_TIERS:
        return r
    legacy = {"yellow": "gray", "orange": "green", "green": "violet"}
    return legacy.get(r, "green")

COMPASS_POINTS = {
    "N": 0.0, "NNO": 22.5, "NO": 45.0, "ONO": 67.5,
    "O": 90.0, "OSO": 112.5, "SO": 135.0, "SSO": 157.5,
    "S": 180.0, "SSW": 202.5, "SW": 225.0, "WSW": 247.5,
    "W": 270.0, "WNW": 292.5, "NW": 315.0, "NNW": 337.5
}


def _compute_wind_trend(clean_hours: list[str], hourly_gusts: dict[str, float]) -> str:
    """
    Berechnet Windtendenz rund um das saubere Fenster.

    Returns z.B.:
        "WIND-TREND: VERSCHLECHTERUNG — Böen steigen nach Fenster von 37→57 km/h"
        "WIND-TREND: VERBESSERUNG — Böen fallen nach Fenster von 40→20 km/h"
        "WIND-TREND: EINGEKESSELT — Fenster liegt zwischen zwei Böen-Phasen (48→37→46 km/h)"
        "WIND-TREND: STABIL"
    """
    if not clean_hours or not hourly_gusts:
        return ""

    # Alle Stunden sortiert
    all_hours = sorted(hourly_gusts.keys())
    if not all_hours:
        return ""

    clean_set = set(clean_hours)
    first_clean = min(clean_set)
    last_clean = max(clean_set)

    # Böen VOR dem Fenster (bis zu 3 Stunden)
    pre_gusts = []
    for h in all_hours:
        if h >= first_clean:
            break
        pre_gusts.append(hourly_gusts[h])
    pre_gusts = pre_gusts[-3:]  # letzte 3 vor dem Fenster

    # Böen IM Fenster
    window_gusts = [hourly_gusts[h] for h in all_hours if h in clean_set and h in hourly_gusts]

    # Böen NACH dem Fenster (bis zu 3 Stunden)
    post_gusts = []
    past_window = False
    for h in all_hours:
        if h > last_clean:
            past_window = True
        if past_window and h in hourly_gusts:
            post_gusts.append(hourly_gusts[h])
            if len(post_gusts) >= 3:
                break

    if not window_gusts:
        return ""

    avg_window = sum(window_gusts) / len(window_gusts)
    avg_pre = sum(pre_gusts) / len(pre_gusts) if pre_gusts else 0
    avg_post = sum(post_gusts) / len(post_gusts) if post_gusts else 0
    max_post = max(post_gusts) if post_gusts else 0
    max_pre = max(pre_gusts) if pre_gusts else 0

    # Schwellenwerte
    DANGER_GUST = 40  # km/h

    pre_danger = avg_pre > DANGER_GUST
    post_danger = avg_post > DANGER_GUST

    if pre_danger and post_danger:
        return (
            f"WIND-TREND: EINGEKESSELT — Fenster liegt zwischen zwei Böen-Phasen "
            f"(vorher Ø{avg_pre:.0f}, Fenster Ø{avg_window:.0f}, nachher Ø{avg_post:.0f} km/h). "
            f"ERHÖHTES RISIKO: Verschlechterung nach dem Fenster sehr wahrscheinlich!"
        )
    elif post_danger and not pre_danger:
        return (
            f"WIND-TREND: VERSCHLECHTERUNG — Böen steigen nach dem Fenster stark an "
            f"(Fenster Ø{avg_window:.0f} → nachher Ø{avg_post:.0f} km/h, max {max_post:.0f} km/h). "
            f"ERHÖHTES RISIKO!"
        )
    elif pre_danger and not post_danger:
        return (
            f"WIND-TREND: VERBESSERUNG — Böen nehmen ab "
            f"(vorher Ø{avg_pre:.0f} → Fenster Ø{avg_window:.0f} → nachher Ø{avg_post:.0f} km/h). "
            f"Positiver Trend."
        )
    elif post_gusts and avg_post > avg_window + 10:
        return (
            f"WIND-TREND: LEICHTE VERSCHLECHTERUNG — Böen nehmen nach dem Fenster zu "
            f"(Fenster Ø{avg_window:.0f} → nachher Ø{avg_post:.0f} km/h)."
        )
    else:
        return "WIND-TREND: STABIL — Keine signifikante Verschlechterung nach dem Fenster."


def _interpolate_wind_at_altitude(pl_data: dict, target_alt: float, pressure_levels: list) -> tuple:
    """
    Interpoliert Windgeschwindigkeit und -richtung auf einer Zielhöhe aus Drucklevel-Daten.

    Returns (wind_speed, wind_direction) oder (None, None) wenn keine Daten vorhanden.
    """
    levels = []
    for level in pressure_levels:
        h = pl_data.get(f"geopotential_height_{level}hPa")
        ws = pl_data.get(f"wind_speed_{level}hPa")
        wd = pl_data.get(f"wind_direction_{level}hPa")
        if h is not None and ws is not None:
            levels.append((h, ws, wd))

    if not levels:
        return None, None

    levels.sort(key=lambda x: x[0])

    # Zielhöhe unter dem tiefsten Level → tiefstes Level verwenden
    if target_alt <= levels[0][0]:
        return levels[0][1], levels[0][2]

    # Zielhöhe über dem höchsten Level → höchstes Level verwenden
    if target_alt >= levels[-1][0]:
        return levels[-1][1], levels[-1][2]

    # Lineare Interpolation zwischen den umschliessenden Levels
    for i in range(len(levels) - 1):
        h_low, ws_low, wd_low = levels[i]
        h_high, ws_high, wd_high = levels[i + 1]
        if h_low <= target_alt <= h_high:
            dh = h_high - h_low
            if dh == 0:
                return ws_low, wd_low
            frac = (target_alt - h_low) / dh
            ws_interp = ws_low + frac * (ws_high - ws_low)
            # Windrichtung: nächstes Level verwenden (Richtungsinterpolation ist komplex)
            wd_interp = wd_low if frac < 0.5 else wd_high
            return ws_interp, wd_interp

    return None, None


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
        self.region_weather_data = {}
        self.region_analyses = {}
        self.region_analyses_loaded_at = None

        api_key = os.environ.get("OPENAI_API_KEY")
        self.model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        self.client = OpenAI(api_key=api_key) if api_key else None

        # History-Persistenz
        self.history_dir = config.HISTORY_DIR
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self._load_all_conversations()

        # Analyse-Persistenz
        self.analyses_file = config.DATA_DIR / "spot_analyses.json"
        self._load_analyses_cache()

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

    def _load_analyses_cache(self):
        """Lädt Spot-Analysen aus Datei."""
        if self.analyses_file.exists():
            try:
                with open(self.analyses_file, "r", encoding="utf-8") as f:
                    self.spot_analyses = json.load(f)
                    self.analyses_loaded_at = datetime.fromtimestamp(self.analyses_file.stat().st_mtime)
                print(f"[ENGINE] {len(self.spot_analyses)} Spot-Analysen aus Cache geladen.")
            except Exception as e:
                logger.error(f"Fehler beim Laden des Analyse-Caches: {e}")

    def _save_analyses_cache(self):
        """Speichert Spot-Analysen in Datei."""
        try:
            with open(self.analyses_file, "w", encoding="utf-8") as f:
                json.dump(self.spot_analyses, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Fehler beim Speichern des Analyse-Caches: {e}")

    def _clear_analyses_cache(self):
        """Löscht Analyse-Cache (bei fehlenden/veralteten Wetterdaten)."""
        try:
            if self.analyses_file.exists():
                self.analyses_file.unlink()
                print("[ENGINE] Analyse-Cache gelöscht (Wetterdaten fehlen)")
        except Exception as e:
            logger.error(f"Fehler beim Löschen des Analyse-Caches: {e}")

    def load_weather_from_cache(self):
        """Lädt Wetterdaten aus lokalem JSON-Cache (kein API-Call).
        Wird beim Serverstart aufgerufen, damit Meteogramme sofort verfügbar sind."""
        cached = load_cached_weather()
        if not cached:
            logger.info("[ENGINE] Kein Wetter-Cache vorhanden")
            return False

        self.weather_data = cached
        self.region_weather_data = cached.pop("_regions", {}) if "_regions" in cached else {}

        # Föhn-Daten separat laden (kleiner API-Call, schnell)
        try:
            self.foehn_data = fetch_foehn_data(forecast_days=config.FORECAST_DAYS)
        except Exception as e:
            logger.error(f"Föhn-Daten fehlgeschlagen: {e}")
            self.foehn_data = None

        self.weather_context_str = self._build_weather_context()
        self.weather_loaded_at = load_cached_weather_timestamp()

        # Analysen-Cache laden
        self._load_analyses_cache()

        spot_count = len([k for k in self.weather_data if not k.startswith("_")])
        logger.info(f"[ENGINE] Wetterdaten aus Cache geladen ({spot_count} Spots)")
        return True

    def refresh_weather(self, force=False):
        """Wetterdaten für alle Spots holen + Kontext-String bauen."""
        print("[ENGINE] Lade Wetterdaten für alle Spots...")
        self.spots = load_spots() # Reload spots to pick up CSV changes

        # 1. Wetterdaten holen (oder Cache nutzen)
        if not force and is_cache_fresh(max_age_hours=12) and is_cache_complete():
            print("[ENGINE] Nutze gecachte Wetterdaten (vollständig)")
            cached = load_cached_weather()
            self.weather_data = cached
            self.region_weather_data = cached.pop("_regions", {}) if cached else {}
        else:
            if not force:
                print("[ENGINE] Cache unvollständig oder veraltet — lade neue Wetterdaten von API...")
            else:
                print("[ENGINE] Force-Refresh — lade neue Wetterdaten von API...")
            result = fetch_all_spots(self.spots)
            if isinstance(result, tuple):
                self.weather_data, self.region_weather_data = result
            else:
                self.weather_data = result
                self.region_weather_data = result.pop("_regions", {}) if result else {}

        # KRITISCH: Wenn keine Wetterdaten verfügbar sind, alte Analysen löschen!
        if not self.weather_data or len([k for k in self.weather_data if not k.startswith("_")]) == 0:
            print("[WARNUNG] Keine Wetterdaten verfügbar - lösche alte Analysen zur Sicherheit")
            self.spot_analyses = {}
            self.region_analyses = {}
            self._clear_analyses_cache()
            return

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

        # 6. Automatische Analyse für neue/fehlende Spots (wenn LLM verfügbar)
        if self.client:
            new_spots = [s["name"] for s in self.spots if s["name"] not in self.spot_analyses]
            if new_spots:
                print(f"[ENGINE] Neue Spots ohne Analyse gefunden ({len(new_spots)}): {new_spots}. Starte Hintergrund-Analyse...")
                threading.Thread(target=self.run_spot_analyses, kwargs={"spot_names": new_spots}, daemon=True).start()

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
            
            prev_max_h = None
            prev_day = None
            cumulative_bf = 0.0
            peak_H = 0.0
            peak_sw = 0.0

            for timestamp in sorted_times:
                current_day = timestamp[:10]
                if current_day != prev_day:
                    prev_max_h = None
                    cumulative_bf = 0.0
                    peak_H = 0.0
                    peak_sw = 0.0
                    prev_day = current_day
                    
                try:
                    dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                    # Vorhersage gemäss config.FORECAST_DAYS (Kalendertage ab heute)
                    last_forecast_day = datetime.now().date() + timedelta(
                        days=config.FORECAST_DAYS - 1
                    )
                    if dt.date() > last_forecast_day:
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
                effective_ceiling = spot["elevation_m"] + 1000
                try:
                    therm = self._calculate_thermal_raw(
                        data, pressure_level_data.get(timestamp, {}),
                        elevation_m, timestamp, spot, prev_max_h,
                        cumulative_bf=cumulative_bf,
                        peak_H=peak_H,
                        peak_sw=peak_sw,
                    )
                    if therm and "error" not in therm:
                        h_climb = therm["climb_rate"]
                        h_max_h = therm["max_height"]
                        prev_max_h = h_max_h
                        diag = therm.get("diagnostics", {})
                        cumulative_bf += diag.get("buoyancy_contribution", 0)
                        peak_H = max(peak_H, diag.get("sensible_heat_flux", 0) or 0)
                        sw = data.get("shortwave_radiation")
                        if sw is not None:
                            peak_sw = max(peak_sw, sw)
                        effective_ceiling = max(effective_ceiling, h_max_h + 1000)
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
                # Check absolute base wind limit against spot's recommended maximum
                ideal_wind_max = spot.get("ideal_wind_max", 30)
                if isinstance(wind_speed, (int, float)) and wind_speed > ideal_wind_max:
                    warnings.append("[STRONG-WIND-WARN]")

                if isinstance(wind_gusts, (int, float)) and isinstance(wind_speed, (int, float)):
                    if (wind_gusts > 30 and wind_gusts - wind_speed > 15) or wind_gusts > 35:
                        warnings.append("[GUST-WARN]")
                
                if isinstance(precip, (int, float)) and precip > 0.05:
                    warnings.append("[RAIN-WARN]")

                # Höhenwind-Info für Föhn-Erkennung und Warnungen (Thermik-basiert)
                alt_wind_info = ""
                aloft_warn = False
                aloft_danger = False
                aloft_gust_warn = False
                aloft_gust_danger = False

                pl_data = pressure_level_data.get(timestamp, {})
                if pl_data:
                    # Build levels for gust calculation
                    alt_levels = []
                    for level in [850, 700]:
                        h_val = pl_data.get(f"geopotential_height_{level}hPa")
                        ws = pl_data.get(f"wind_speed_{level}hPa")
                        wd = pl_data.get(f"wind_direction_{level}hPa")
                        if h_val is not None and ws is not None:
                            alt_levels.append({"pressure": level, "altitude": h_val,
                                               "wind_speed": ws, "wind_direction": wd})

                    # Compute altitude gusts for display levels
                    if alt_levels:
                        alt_levels_with_gusts = estimate_altitude_gusts(
                            wind_speed_10m=wind_speed,
                            wind_gusts_10m=wind_gusts,
                            pressure_levels_data=alt_levels,
                            elevation_m=spot["elevation_m"],
                            boundary_layer_height=data.get("boundary_layer_height"),
                        )
                        for lv in alt_levels_with_gusts:
                            gust_str = ""
                            if lv.get("wind_gusts") is not None and lv["wind_gusts"] > lv["wind_speed"] + 2:
                                gust_str = f" (Böen {lv['wind_gusts']:.0f}km/h)"
                            wd_val = lv.get("wind_direction")
                            if wd_val is not None:
                                alt_wind_info += f" | {lv['pressure']}hPa({int(lv['altitude'])}m): {lv['wind_speed']:.0f}km/h{gust_str} aus {wd_val:.0f}°"

                    for level in config.PRESSURE_LEVELS:
                        h_val = pl_data.get(f"geopotential_height_{level}hPa")
                        ws = pl_data.get(f"wind_speed_{level}hPa")
                        if h_val is not None and ws is not None:
                            if spot["elevation_m"] <= h_val <= effective_ceiling:
                                if ws > 40:
                                    aloft_danger = True
                                elif ws > 30:
                                    aloft_warn = True

                    # Gust warnings for altitude levels in flying range
                    all_fly_levels = []
                    for level in config.PRESSURE_LEVELS:
                        h_val = pl_data.get(f"geopotential_height_{level}hPa")
                        ws = pl_data.get(f"wind_speed_{level}hPa")
                        if h_val is not None and ws is not None and spot["elevation_m"] <= h_val <= effective_ceiling:
                            all_fly_levels.append({"pressure": level, "altitude": h_val, "wind_speed": ws})

                    if all_fly_levels:
                        fly_with_gusts = estimate_altitude_gusts(
                            wind_speed_10m=wind_speed,
                            wind_gusts_10m=wind_gusts,
                            pressure_levels_data=all_fly_levels,
                            elevation_m=spot["elevation_m"],
                            boundary_layer_height=data.get("boundary_layer_height"),
                        )
                        for lv in fly_with_gusts:
                            g = lv.get("wind_gusts", 0)
                            if g > 40:
                                aloft_gust_danger = True
                            elif g > 30:
                                aloft_gust_warn = True

                if aloft_danger:
                    if "[ALOFT-DANGER]" not in warnings:
                        warnings.append("[ALOFT-DANGER]")
                elif aloft_warn:
                    if "[ALOFT-WARN]" not in warnings:
                        warnings.append("[ALOFT-WARN]")

                if aloft_gust_danger:
                    if "[ALOFT-GUST-DANGER]" not in warnings:
                        warnings.append("[ALOFT-GUST-DANGER]")
                elif aloft_gust_warn:
                    if "[ALOFT-GUST-WARN]" not in warnings:
                        warnings.append("[ALOFT-GUST-WARN]")

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

        # Föhn: Snapshot + aufbereitete Zeitreihe für die KI
        lines.append(self._build_foehn_context_for_ai())

        return "\n".join(lines)

    def _build_foehn_context_for_ai(self) -> str:
        """Regionaler Föhn-Guide, dann Snapshot, dann Zeitreihe (für LLM)."""
        guide = format_foehn_llm_regional_guide()
        head = self._format_foehn_info(date_str=None, kritischer_foehn="Beide")
        if not self.foehn_data:
            return guide + "\n\n" + head
        try:
            series = build_foehn_llm_context(
                self.foehn_data["nord"], self.foehn_data["sued"]
            )
        except Exception as e:
            logger.warning("build_foehn_llm_context fehlgeschlagen: %s", e)
            series = ""
        if series:
            return guide + "\n\n" + head + "\n\n" + series
        return guide + "\n\n" + head

    def _calculate_thermal_raw(
        self, data, pl_data, elevation_m, timestamp, spot, prev_max_h=None,
        cumulative_bf=0.0, peak_H=0.0, peak_sw=0.0,
    ):
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
            boundary_layer_height_gfs=data.get("boundary_layer_height_gfs"),
            previous_max_height=prev_max_h,
            cumulative_buoyancy=cumulative_bf,
            peak_H=peak_H,
            peak_shortwave=peak_sw,
        )
        return therm

    def _calculate_thermal_for_hour(self, data, pl_data, elevation_m, timestamp, spot, prev_max_h=None):
        """Berechnet Thermik-Proxy für eine Stunde eines Spots."""
        therm = self._calculate_thermal_raw(data, pl_data, elevation_m, timestamp, spot, prev_max_h)

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

    def _format_foehn_info(self, date_str: str = None, kritischer_foehn: str = "Süd") -> str:
        """Formatiert Föhn-Indikatoren als Text. Sucht bei Angabe eines Datums das Maximum."""
        if not self.foehn_data:
            return "═══ FÖHN-INDIKATOR ═══\nKeine Föhn-Daten verfügbar."

        nord = self.foehn_data.get("nord", {})
        sued = self.foehn_data.get("sued", {})
        times = nord.get("hourly", {}).get("time", [])

        if not nord or not sued or not times:
            return "═══ FÖHN-INDIKATOR ═══\nKeine Föhn-Daten verfügbar."

        target_index = None
        if date_str:
            target_indices = []
            for i, t in enumerate(times):
                if t.startswith(date_str):
                    try:
                        dt_obj = datetime.fromisoformat(t.replace("Z", "+00:00"))
                        if config.FLIGHT_HOURS_START <= dt_obj.hour < config.FLIGHT_HOURS_END:
                            target_indices.append(i)
                    except Exception:
                        pass
            
            if target_indices:
                worst_idx = target_indices[0]
                max_delta = -999
                for i in target_indices:
                    ev_tmp = evaluate_foehn(nord, sued, time_index=i, kritischer_foehn=kritischer_foehn)
                    dp = ev_tmp.get("delta_p_hpa") or 0
                    if dp > max_delta:
                        max_delta = dp
                        worst_idx = i
                target_index = worst_idx

        ev = evaluate_foehn(nord, sued, time_index=target_index, kritischer_foehn=kritischer_foehn)
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
        """Kalendertage ab heute, Anzahl config.FORECAST_DAYS (wie Open-Meteo / fetch_weather).

        Nicht aus Stunden 10–17 in den Rohdaten ableiten: dort kann der letzte Vorhersagetag
        fehlen (Zeitzonen/Parsing), obwohl die API 5 Tage liefert.
        """
        today = datetime.now().date()
        return [
            (today + timedelta(days=i)).strftime("%Y-%m-%d")
            for i in range(config.FORECAST_DAYS)
        ]

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
        clean_hours = []       # WIND-OK ohne harte Warnungen
        warned_hours = []      # WIND-OK aber mit harten Warnungen (GUST/ALOFT/RAIN/CAPE)
        hourly_gusts = {}      # hour_str → gust value für Trend-Analyse
        rain_hours = []        # Stunden mit Niederschlag

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
            effective_ceiling = spot["elevation_m"] + 1000
            try:
                therm = self._calculate_thermal_raw(
                    data, pressure_level_data.get(timestamp, {}),
                    elevation_m, timestamp, spot
                )
                if therm and "error" not in therm:
                    h_climb = therm["climb_rate"]
                    h_max_h = therm["max_height"]
                    effective_ceiling = max(effective_ceiling, h_max_h + 1000)
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
            # Check absolute base wind limit against spot's recommended maximum
            ideal_wind_max = spot.get("ideal_wind_max", 30)
            if isinstance(wind_speed, (int, float)) and wind_speed > ideal_wind_max:
                warnings.append("[STRONG-WIND-WARN]")

            if isinstance(wind_gusts, (int, float)) and isinstance(wind_speed, (int, float)):
                if wind_gusts > 40:
                    warnings.append("[GUST-DANGER]")
                elif (wind_gusts > 30 and wind_gusts - wind_speed > 15) or wind_gusts > 30:
                    warnings.append("[GUST-WARN]")
            
            try:
                precip = data.get("precipitation")
                if isinstance(precip, (int, float)) and precip > 0:
                    warnings.append("[RAIN-WARN]")
            except Exception:
                pass

            hour_str = f"{dt.hour:02d}:00"
            if "[RAIN-WARN]" in warnings:
                rain_hours.append(hour_str)
            if isinstance(wind_gusts, (int, float)):
                hourly_gusts[hour_str] = wind_gusts
            if is_ok:
                wind_ok_hours.append(hour_str)
            else:
                wind_wrong_hours.append(hour_str)

            # Höhenwind-Info für Föhn-Erkennung und Warnungen (Thermik-basiert)
            alt_wind_info = ""
            aloft_warn = False
            aloft_danger = False
            aloft_gust_warn = False
            aloft_gust_danger = False

            pl_data = pressure_level_data.get(timestamp, {})
            if pl_data:
                # Build levels for gust calculation (display levels)
                alt_levels = []
                for level in [850, 700]:
                    h_val = pl_data.get(f"geopotential_height_{level}hPa")
                    ws = pl_data.get(f"wind_speed_{level}hPa")
                    wd = pl_data.get(f"wind_direction_{level}hPa")
                    if h_val is not None and ws is not None:
                        alt_levels.append({"pressure": level, "altitude": h_val,
                                           "wind_speed": ws, "wind_direction": wd})

                # Compute altitude gusts for display levels
                if alt_levels:
                    alt_levels_with_gusts = estimate_altitude_gusts(
                        wind_speed_10m=wind_speed,
                        wind_gusts_10m=wind_gusts,
                        pressure_levels_data=alt_levels,
                        elevation_m=elevation_m,
                        boundary_layer_height=data.get("boundary_layer_height"),
                    )
                    for lv in alt_levels_with_gusts:
                        gust_str = ""
                        if lv.get("wind_gusts") is not None and lv["wind_gusts"] > lv["wind_speed"] + 2:
                            gust_str = f" (Böen {lv['wind_gusts']:.0f}km/h)"
                        wd_val = lv.get("wind_direction")
                        if wd_val is not None:
                            alt_wind_info += f" | {lv['pressure']}hPa({int(lv['altitude'])}m): {lv['wind_speed']:.0f}km/h{gust_str} aus {wd_val:.0f}°"
                else:
                    for level in [850, 700]:
                        h_val = pl_data.get(f"geopotential_height_{level}hPa")
                        ws = pl_data.get(f"wind_speed_{level}hPa")
                        wd = pl_data.get(f"wind_direction_{level}hPa")
                        if h_val is not None and ws is not None and wd is not None:
                            alt_wind_info += f" | {level}hPa({int(h_val)}m): {ws:.0f}km/h aus {wd:.0f}°"

                for level in config.PRESSURE_LEVELS:
                    h_val = pl_data.get(f"geopotential_height_{level}hPa")
                    ws = pl_data.get(f"wind_speed_{level}hPa")
                    if h_val is not None and ws is not None:
                        if spot["elevation_m"] <= h_val <= effective_ceiling:
                            if ws > 40:
                                aloft_danger = True
                            elif ws > 30:
                                aloft_warn = True

                # Gust warnings for altitude levels in flying range
                all_fly_levels = []
                for level in config.PRESSURE_LEVELS:
                    h_val = pl_data.get(f"geopotential_height_{level}hPa")
                    ws = pl_data.get(f"wind_speed_{level}hPa")
                    if h_val is not None and ws is not None and spot["elevation_m"] <= h_val <= effective_ceiling:
                        all_fly_levels.append({"pressure": level, "altitude": h_val, "wind_speed": ws})

                if all_fly_levels:
                    fly_with_gusts = estimate_altitude_gusts(
                        wind_speed_10m=wind_speed,
                        wind_gusts_10m=wind_gusts,
                        pressure_levels_data=all_fly_levels,
                        elevation_m=spot["elevation_m"],
                        boundary_layer_height=data.get("boundary_layer_height"),
                    )
                    for lv in fly_with_gusts:
                        g = lv.get("wind_gusts", 0)
                        if g > 40:
                            aloft_gust_danger = True
                        elif g > 30:
                            aloft_gust_warn = True

            if aloft_danger:
                if "[ALOFT-DANGER]" not in warnings:
                    warnings.append("[ALOFT-DANGER]")
            elif aloft_warn:
                if "[ALOFT-WARN]" not in warnings:
                    warnings.append("[ALOFT-WARN]")

            if aloft_gust_danger:
                if "[ALOFT-GUST-DANGER]" not in warnings:
                    warnings.append("[ALOFT-GUST-DANGER]")
            elif aloft_gust_warn:
                if "[ALOFT-GUST-WARN]" not in warnings:
                    warnings.append("[ALOFT-GUST-WARN]")

            try:
                cape = data.get("cape")
                if isinstance(cape, (int, float)) and cape > 800:
                    warnings.append("[CAPE-WARN]")
            except Exception:
                pass

            warning_str = " " + " ".join(warnings) if warnings else ""

            # Klassifiziere saubere vs. gewarnte Stunden (nach allen Warnungen)
            hard_warnings = {"[GUST-DANGER]", "[ALOFT-DANGER]", "[ALOFT-GUST-DANGER]", "[RAIN-WARN]", "[CAPE-WARN]", "[STRONG-WIND-WARN]"}
            has_hard_warn = bool(hard_warnings & set(warnings))
            if is_ok and not has_hard_warn:
                clean_hours.append(hour_str)
            elif is_ok and has_hard_warn:
                warned_hours.append(hour_str)

            lines.append(
                f"{time_str}: Temp {temp}°C | Wind {wind_speed}km/h aus {wind_dir}° (Böen {wind_gusts}km/h) {wind_status}{warning_str} | "
                f"Wolkenbasis {cloud_base} | Bewölkung {cloud_cover}% | FLUGBEREICH: {elevation_m}–{effective_ceiling}m MSL{alt_wind_info}{thermal_info}"
            )

        if not has_data:
            return ""

        # Wind-Tag-Zusammenfassung (damit die LLM es nicht übersehen kann)
        lines.append("")
        lines.append("═══ WIND-ZUSAMMENFASSUNG (verbindlich!) ═══")
        lines.append(f"[WIND-OK] Stunden ({len(wind_ok_hours)}): {', '.join(wind_ok_hours) if wind_ok_hours else 'KEINE'}")
        lines.append(f"[WIND-WRONG] Stunden ({len(wind_wrong_hours)}): {', '.join(wind_wrong_hours) if wind_wrong_hours else 'KEINE'}")
        lines.append(f"Saubere Stunden ({len(clean_hours)}): {', '.join(clean_hours) if clean_hours else 'KEINE'} (WIND-OK ohne harte Warnungen)")
        if warned_hours:
            lines.append(f"⚠ Gewarnete WIND-OK Stunden ({len(warned_hours)}): {', '.join(warned_hours)} (WIND-OK aber WIND/GUST/ALOFT/RAIN/CAPE-WARN!)")
        if len(clean_hours) >= 3:
            lines.append(f"→ {len(clean_hours)} saubere Stunden: safety_status eher safe oder conditional (Grün/Orange).")
        elif clean_hours:
            lines.append(f"→ Nur {len(clean_hours)} saubere Stunden: Status sollte maximal conditional sein.")
        elif wind_ok_hours and not clean_hours:
            lines.append(f"→ ACHTUNG: Alle {len(wind_ok_hours)} WIND-OK-Stunden haben harte Warnungen (WIND/GUST/ALOFT/RAIN/CAPE)! Status sollte NOT_SAFE sein!")
        else:
            lines.append(f"→ Kein fliegbares Fenster. Status sollte not_safe sein.")

        # Wind-Trend nach dem sauberen Fenster
        trend = _compute_wind_trend(clean_hours, hourly_gusts)
        if trend:
            lines.append(trend)

        # Niederschlag-Trend
        all_hours_sorted = sorted(hourly_gusts.keys()) or sorted(set(wind_ok_hours + wind_wrong_hours))
        if rain_hours and all_hours_sorted:
            last_rain = max(rain_hours)
            dry_after = [h for h in all_hours_sorted if h > last_rain]
            if len(dry_after) >= 4:
                lines.append(
                    f"NIEDERSCHLAG-TREND: AUFKLÄRUNG — Regen nur {', '.join(rain_hours)}, "
                    f"ab {dry_after[0]} trocken ({len(dry_after)} trockene Stunden). "
                    f"Nachmittag potenziell fliegbar!"
                )
            elif dry_after:
                lines.append(
                    f"NIEDERSCHLAG-TREND: SPÄTE AUFKLÄRUNG — Regen bis {last_rain}, "
                    f"nur {len(dry_after)} trockene Stunden danach."
                )
            else:
                lines.append(f"NIEDERSCHLAG-TREND: REGEN BIS ABEND — Letzte Regenstunde: {last_rain}")
        elif rain_hours:
            lines.append(f"NIEDERSCHLAG-TREND: GANZTÄGIG — Regen in {len(rain_hours)} Stunden")

        # Föhn-Info anhängen
        lines.append("")
        krit_foehn = spot.get("kritischer_foehn", "Süd")
        lines.append(self._format_foehn_info(date_str=date_str, kritischer_foehn=krit_foehn))

        return "\n".join(lines)

    def _get_spots_in_region(self, region):
        """Findet Spots innerhalb des Region-Polygons via Point-in-Polygon."""
        from shapely.geometry import Point
        polygon = region.get("polygon")
        if polygon is None:
            return []
        result = []
        for spot in self.spots:
            pt = Point(spot["longitude"], spot["latitude"])
            if polygon.contains(pt):
                result.append(spot)
        return result

    def _build_single_region_context(self, region, date_str: str) -> str:
        """
        Baut Wetterkontext fuer EINE Region an EINEM Tag.
        Aehnlich wie _build_single_spot_context(), aber:
        - Kein Windrichtungs-Check (keine erlaubte Richtung)
        - Stattdessen WIND-CALM/MODERATE/STRONG Tags
        - Foehn: regionsspezifisch (Süd/Nord/Beide)
        """
        rid = region["id"]
        rname = region["region"]
        elev_ref = region.get("elevation_ref", 1200)

        region_data = self.region_weather_data.get(rid)
        if not region_data:
            return ""

        meta = self.weather_data.get("_meta", {})
        updated = meta.get("last_updated", "unbekannt")

        krit_foehn = region.get("kritischer_foehn", "Beide")
        lines = [
            f"WETTERDATEN FUER REGION: {rname} — TAG: {date_str} (Stand: {updated})",
            f"═══ REGION: {rname} (Referenzhoehe: {elev_ref}m MSL, Kritischer Foehn: {krit_foehn}) ═══",
        ]

        hourly_data = region_data.get("hourly_data", {})
        pressure_level_data = region_data.get("pressure_level_data", {})

        sorted_times = sorted(hourly_data.keys())
        has_data = False
        calm_hours = []
        moderate_hours = []
        strong_hours = []
        clean_hours = []
        warned_hours = []
        hourly_gusts = {}      # hour_str → gust value für Trend-Analyse
        rain_hours = []        # Stunden mit Niederschlag

        # Dummy spot dict for _calculate_thermal_raw compatibility
        dummy_spot = {
            "name": rname,
            "elevation_m": elev_ref,
            "slope_azimuth": None,
            "slope_angle": None,
        }

        # Multi-Anchor: Spots in Region finden (fuer Boeen-Interpolation)
        region_spots = self._get_spots_in_region(region)
        region_polygon = region.get("polygon")

        for timestamp in sorted_times:
            try:
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                if dt.strftime("%Y-%m-%d") != date_str:
                    continue
                if not (config.FLIGHT_HOURS_START <= dt.hour < config.FLIGHT_HOURS_END):
                    continue
            except Exception:
                continue

            has_data = True
            data = hourly_data[timestamp]
            time_str = timestamp.replace("T", " ")[:16]

            # Thermik berechnen
            thermal_info = ""
            effective_ceiling = elev_ref + 1000
            try:
                therm = self._calculate_thermal_raw(
                    data, pressure_level_data.get(timestamp, {}),
                    elev_ref, timestamp, dummy_spot
                )
                if therm and "error" not in therm:
                    h_climb = therm["climb_rate"]
                    h_max_h = therm["max_height"]
                    effective_ceiling = max(effective_ceiling, h_max_h + 1000)
                    lcl = therm.get("lcl")
                    lcl_str = f", LCL/Basis {lcl}m" if lcl else ""
                    thermal_info = f" | THERMIK-PROXY: {h_climb} m/s bis {h_max_h}m MSL{lcl_str} (Guete: {therm['rating']}/10)"
            except Exception as e:
                thermal_info = f" | Thermik-Fehler: {e}"

            temp = data.get("temperature_2m", "N/A")
            wind_speed_surface = data.get("wind_speed_10m", "N/A")
            wind_dir_surface = data.get("wind_direction_10m", "N/A")
            wind_gusts_surface = data.get("wind_gusts_10m", "N/A")
            cloud_base_raw = data.get("cloud_base")
            cloud_base = f"{cloud_base_raw}m" if cloud_base_raw is not None else "wolkenfrei"
            cloud_cover = data.get("cloud_cover", "N/A")

            # Multi-Anchor Böen: Spots + Referenzpunkt als Ankerpunkte
            pl_data = pressure_level_data.get(timestamp, {})
            anchors = []
            # Referenzpunkt-Anker aus Region-Wetterdaten
            ref_anchor = None
            if isinstance(wind_gusts_surface, (int, float)) and isinstance(wind_speed_surface, (int, float)):
                ref_anchor = {
                    "elevation_m": elev_ref,
                    "gust_kmh": float(wind_gusts_surface),
                    "wind_speed_kmh": float(wind_speed_surface),
                    "source": f"Ref-{rname}",
                }
            if region_polygon:
                anchors = collect_gust_anchors(
                    region_polygon, region_spots, self.weather_data, timestamp,
                    ref_anchor=ref_anchor,
                )

            wind_speed = wind_speed_surface
            wind_dir = wind_dir_surface
            wind_gusts = wind_gusts_surface
            ref_wind_info = ""

            if anchors:
                # Multi-Anchor: Böen auf Referenzhöhe aus echten Spot-Daten interpolieren
                anchor_gust, anchor_ws = interpolate_gust_from_anchors(anchors, elev_ref)
                if anchor_gust is not None and isinstance(wind_speed_surface, (int, float)):
                    # Effektiver Wind: max(Boden, Anker-Interpolation)
                    if anchor_ws is not None and anchor_ws > wind_speed_surface:
                        wind_speed = anchor_ws
                    wind_gusts = max(
                        wind_gusts_surface if isinstance(wind_gusts_surface, (int, float)) else 0,
                        anchor_gust,
                    )
                    ref_wind_info = f" [Anker-Boeen {elev_ref}m: {anchor_gust:.0f}km/h, {len(anchors)} Anker]"
                elif anchor_gust is not None:
                    wind_speed = anchor_ws if anchor_ws is not None else wind_speed_surface
                    wind_gusts = anchor_gust
                    ref_wind_info = f" [Anker-Boeen {elev_ref}m: {anchor_gust:.0f}km/h]"
            else:
                # Fallback: Drucklevel-Interpolation (altes Verfahren)
                ref_ws, ref_wd = _interpolate_wind_at_altitude(pl_data, elev_ref, config.PRESSURE_LEVELS)
                if ref_ws is not None and isinstance(wind_speed_surface, (int, float)):
                    if ref_ws > wind_speed_surface:
                        wind_speed = ref_ws
                        if ref_wd is not None:
                            wind_dir = ref_wd
                        ref_gusts_estimate = ref_ws * 1.3
                        if isinstance(wind_gusts_surface, (int, float)):
                            wind_gusts = max(wind_gusts_surface, ref_gusts_estimate)
                        else:
                            wind_gusts = ref_gusts_estimate
                    ref_wind_info = f" [Ref-Wind {elev_ref}m: {ref_ws:.0f}km/h"
                    if ref_wd is not None:
                        ref_wind_info += f" aus {ref_wd:.0f}°"
                    ref_wind_info += "]"
                elif ref_ws is not None:
                    wind_speed = ref_ws
                    wind_dir = ref_wd if ref_wd is not None else "N/A"
                    ref_gusts_estimate = ref_ws * 1.3
                    wind_gusts = ref_gusts_estimate
                    ref_wind_info = f" [Ref-Wind {elev_ref}m: {ref_ws:.0f}km/h]"

            # Wind-Staerke Tags (basierend auf effektivem Wind = max aus Boden und Referenzhoehe)
            hour_str = f"{dt.hour:02d}:00"
            if isinstance(wind_gusts, (int, float)):
                hourly_gusts[hour_str] = wind_gusts
            if isinstance(wind_speed, (int, float)) and isinstance(wind_gusts, (int, float)):
                if wind_speed > 30 or wind_gusts > 40:
                    wind_status = "[WIND-STRONG]"
                    strong_hours.append(hour_str)
                elif wind_speed > 20 or wind_gusts > 30:
                    wind_status = "[WIND-MODERATE]"
                    moderate_hours.append(hour_str)
                else:
                    wind_status = "[WIND-CALM]"
                    calm_hours.append(hour_str)
            elif isinstance(wind_speed, (int, float)):
                if wind_speed > 30:
                    wind_status = "[WIND-STRONG]"
                    strong_hours.append(hour_str)
                elif wind_speed > 20:
                    wind_status = "[WIND-MODERATE]"
                    moderate_hours.append(hour_str)
                else:
                    wind_status = "[WIND-CALM]"
                    calm_hours.append(hour_str)
            else:
                wind_status = "[WIND-CALM]"
                calm_hours.append(hour_str)

            warnings = []
            if isinstance(wind_gusts, (int, float)):
                if wind_gusts > 40:
                    warnings.append("[GUST-DANGER]")
                elif wind_gusts > 30:
                    warnings.append("[GUST-WARN]")

            try:
                precip = data.get("precipitation")
                if isinstance(precip, (int, float)) and precip > 0:
                    warnings.append("[RAIN-WARN]")
                    rain_hours.append(hour_str)
            except Exception:
                pass

            # Hoehenwind mit Böen
            alt_wind_info = ""
            aloft_warn = False
            aloft_danger = False
            aloft_gust_warn = False
            aloft_gust_danger = False

            if pl_data:
                # Build levels for gust calculation (display levels)
                alt_levels = []
                for level in [850, 700]:
                    h_val = pl_data.get(f"geopotential_height_{level}hPa")
                    ws = pl_data.get(f"wind_speed_{level}hPa")
                    wd = pl_data.get(f"wind_direction_{level}hPa")
                    if h_val is not None and ws is not None:
                        alt_levels.append({"pressure": level, "altitude": h_val,
                                           "wind_speed": ws, "wind_direction": wd})

                # Compute altitude gusts for display levels
                if alt_levels:
                    if anchors:
                        alt_levels_with_gusts = estimate_altitude_gusts_multi_anchor(
                            anchors=anchors,
                            pressure_levels_data=alt_levels,
                            elevation_ref=elev_ref,
                            boundary_layer_height=data.get("boundary_layer_height"),
                            region_id=rid,
                        )
                    else:
                        alt_levels_with_gusts = estimate_altitude_gusts(
                            wind_speed_10m=wind_speed_surface,
                            wind_gusts_10m=wind_gusts_surface,
                            pressure_levels_data=alt_levels,
                            elevation_m=elev_ref,
                            boundary_layer_height=data.get("boundary_layer_height"),
                        )
                    for lv in alt_levels_with_gusts:
                        gust_str = ""
                        if lv.get("wind_gusts") is not None and lv["wind_gusts"] > lv["wind_speed"] + 2:
                            gust_str = f" (Boeen {lv['wind_gusts']:.0f}km/h)"
                        wd_val = lv.get("wind_direction")
                        if wd_val is not None:
                            alt_wind_info += f" | {lv['pressure']}hPa({int(lv['altitude'])}m): {lv['wind_speed']:.0f}km/h{gust_str} aus {wd_val:.0f}°"
                else:
                    for level in [850, 700]:
                        h_val = pl_data.get(f"geopotential_height_{level}hPa")
                        ws = pl_data.get(f"wind_speed_{level}hPa")
                        wd = pl_data.get(f"wind_direction_{level}hPa")
                        if h_val is not None and ws is not None and wd is not None:
                            alt_wind_info += f" | {level}hPa({int(h_val)}m): {ws:.0f}km/h aus {wd:.0f}°"

                for level in config.PRESSURE_LEVELS:
                    h_val = pl_data.get(f"geopotential_height_{level}hPa")
                    ws = pl_data.get(f"wind_speed_{level}hPa")
                    if h_val is not None and ws is not None:
                        if elev_ref <= h_val <= effective_ceiling:
                            if ws > 40:
                                aloft_danger = True
                            elif ws > 30:
                                aloft_warn = True

                # Gust warnings for altitude levels in flying range
                all_fly_levels = []
                for level in config.PRESSURE_LEVELS:
                    h_val = pl_data.get(f"geopotential_height_{level}hPa")
                    ws = pl_data.get(f"wind_speed_{level}hPa")
                    if h_val is not None and ws is not None and elev_ref <= h_val <= effective_ceiling:
                        all_fly_levels.append({"pressure": level, "altitude": h_val, "wind_speed": ws})

                if all_fly_levels:
                    if anchors:
                        fly_with_gusts = estimate_altitude_gusts_multi_anchor(
                            anchors=anchors,
                            pressure_levels_data=all_fly_levels,
                            elevation_ref=elev_ref,
                            boundary_layer_height=data.get("boundary_layer_height"),
                            region_id=rid,
                        )
                    else:
                        fly_with_gusts = estimate_altitude_gusts(
                            wind_speed_10m=wind_speed_surface,
                            wind_gusts_10m=wind_gusts_surface,
                            pressure_levels_data=all_fly_levels,
                            elevation_m=elev_ref,
                            boundary_layer_height=data.get("boundary_layer_height"),
                        )
                    for lv in fly_with_gusts:
                        g = lv.get("wind_gusts", 0)
                        if g > 40:
                            aloft_gust_danger = True
                        elif g > 30:
                            aloft_gust_warn = True

            if aloft_danger:
                warnings.append("[ALOFT-DANGER]")
            elif aloft_warn:
                warnings.append("[ALOFT-WARN]")

            if aloft_gust_danger:
                warnings.append("[ALOFT-GUST-DANGER]")
            elif aloft_gust_warn:
                warnings.append("[ALOFT-GUST-WARN]")

            try:
                cape = data.get("cape")
                if isinstance(cape, (int, float)) and cape > 800:
                    warnings.append("[CAPE-WARN]")
            except Exception:
                pass

            if isinstance(cloud_cover, (int, float)) and cloud_cover >= 80:
                warnings.append("[OVERCAST-WARN]")

            warning_str = " " + " ".join(warnings) if warnings else ""

            # Klassifiziere saubere vs. gewarnte Stunden
            hard_warnings = {"[GUST-DANGER]", "[ALOFT-DANGER]", "[ALOFT-GUST-DANGER]", "[RAIN-WARN]", "[CAPE-WARN]", "[WIND-STRONG]"}
            has_hard_warn = bool(hard_warnings & set(warnings)) or wind_status == "[WIND-STRONG]"
            if not has_hard_warn:
                clean_hours.append(hour_str)
            else:
                warned_hours.append(hour_str)

            # Wind-Werte formatieren (koennen Floats sein nach Interpolation)
            ws_fmt = f"{wind_speed:.0f}" if isinstance(wind_speed, float) else str(wind_speed)
            wd_fmt = f"{wind_dir:.0f}" if isinstance(wind_dir, float) else str(wind_dir)
            wg_fmt = f"{wind_gusts:.0f}" if isinstance(wind_gusts, float) else str(wind_gusts)

            lines.append(
                f"{time_str}: Temp {temp}°C | Wind {ws_fmt}km/h aus {wd_fmt}° (Boeen {wg_fmt}km/h) {wind_status}{ref_wind_info}{warning_str} | "
                f"Wolkenbasis {cloud_base} | Bewoelkung {cloud_cover}% | FLUGBEREICH: {elev_ref}–{effective_ceiling}m MSL{alt_wind_info}{thermal_info}"
            )

        if not has_data:
            return ""

        # Zusammenfassung
        lines.append("")
        lines.append("═══ WIND-ZUSAMMENFASSUNG (verbindlich!) ═══")
        lines.append(f"[WIND-CALM] Stunden ({len(calm_hours)}): {', '.join(calm_hours) if calm_hours else 'KEINE'}")
        lines.append(f"[WIND-MODERATE] Stunden ({len(moderate_hours)}): {', '.join(moderate_hours) if moderate_hours else 'KEINE'}")
        lines.append(f"[WIND-STRONG] Stunden ({len(strong_hours)}): {', '.join(strong_hours) if strong_hours else 'KEINE'} (NICHT FLIEGBAR)")
        lines.append(f"Saubere Stunden ({len(clean_hours)}): {', '.join(clean_hours) if clean_hours else 'KEINE'}")
        if warned_hours:
            lines.append(f"Gewarnte Stunden ({len(warned_hours)}): {', '.join(warned_hours)}")

        flyable = len(calm_hours) + len(moderate_hours)
        if len(clean_hours) >= 3:
            lines.append(f"→ {len(clean_hours)} saubere Stunden: safety_status eher safe oder conditional.")
        elif clean_hours:
            lines.append(f"→ Nur {len(clean_hours)} saubere Stunden: Status sollte maximal conditional sein.")
        elif flyable > 0 and not clean_hours:
            lines.append(f"→ ACHTUNG: Alle fliegbaren Stunden haben harte Warnungen! Status sollte NOT_SAFE sein!")
        else:
            lines.append(f"→ Kein fliegbares Fenster. Status sollte not_safe sein.")

        # Wind-Trend nach dem sauberen Fenster
        trend = _compute_wind_trend(clean_hours, hourly_gusts)
        if trend:
            lines.append(trend)

        # Niederschlag-Trend
        all_hours_sorted = sorted(hourly_gusts.keys()) or sorted(set(calm_hours + moderate_hours + strong_hours))
        if rain_hours and all_hours_sorted:
            last_rain = max(rain_hours)
            dry_after = [h for h in all_hours_sorted if h > last_rain]
            if len(dry_after) >= 4:
                lines.append(
                    f"NIEDERSCHLAG-TREND: AUFKLAERUNG — Regen nur {', '.join(rain_hours)}, "
                    f"ab {dry_after[0]} trocken ({len(dry_after)} trockene Stunden). "
                    f"Nachmittag potenziell fliegbar!"
                )
            elif dry_after:
                lines.append(
                    f"NIEDERSCHLAG-TREND: SPAETE AUFKLAERUNG — Regen bis {last_rain}, "
                    f"nur {len(dry_after)} trockene Stunden danach."
                )
            else:
                lines.append(f"NIEDERSCHLAG-TREND: REGEN BIS ABEND — Letzte Regenstunde: {last_rain}")
        elif rain_hours:
            lines.append(f"NIEDERSCHLAG-TREND: GANZTAEGIG — Regen in {len(rain_hours)} Stunden")

        # Foehn: regionsspezifisch (Süd/Nord/Beide)
        krit_foehn = region.get("kritischer_foehn", "Beide")
        lines.append("")
        lines.append(self._format_foehn_info(date_str=date_str, kritischer_foehn=krit_foehn))

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

            # Hard override: 0 WIND-OK Stunden = immer not_safe
            wind_ok = result.get("wind_ok_count", -1)
            if isinstance(wind_ok, int) and wind_ok == 0 and result.get("safety_status") != "not_safe":
                logger.warning(f"Safety-Override für {name}/{date_str}: LLM gab '{result.get('safety_status')}' trotz 0 WIND-OK Stunden → not_safe")
                result["safety_status"] = "not_safe"
                result["safe_window"] = "keins"
                nogo = result.get("no_go_reasons", [])
                if not any("Windrichtung" in r for r in nogo):
                    nogo.append("Keine Stunde mit korrekter Windrichtung")
                result["no_go_reasons"] = nogo

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
            safety_context += (
                "Analysiere NUR die Stunden innerhalb des sicheren Fensters.\n"
                "Hinweis: „conditional“ (Orange) betrifft nur Gefahren/Vorsicht — "
                "flyability_tier kann trotzdem „violet“ sein, wenn Thermik/XC außergewöhnlich sind.\n"
            )

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
            tier = _normalize_flyability_tier(
                result.get("flyability_tier") or result.get("status")
            )
            result["flyability_tier"] = tier
            result["status"] = tier  # Abwärtskompatibilität (gleiche Bedeutung wie früher „status“)
            result["spot"] = name
            result["date"] = date_str
            result["phase"] = "flyability"
            return result

        except Exception as e:
            logger.error(f"Flyability-Analyse für {name}/{date_str} fehlgeschlagen: {e}")
            return {"spot": name, "date": date_str, "status": "error", "phase": "flyability", "error": str(e)}

    def run_spot_analyses(self, spot_names: list = None) -> dict:
        """Zweiphasen-Orchestrierung: Safety → Filter → Flyability."""
        if not self.client:
            return {"success": False, "error": "OPENAI_API_KEY nicht konfiguriert"}

        if not self.weather_data:
            return {"success": False, "error": "Keine Wetterdaten geladen"}

        if spot_names:
            spots_to_analyze = [s for s in self.spots if s["name"] in spot_names and s["name"] in self.weather_data]
        else:
            spots_to_analyze = [s for s in self.spots if s["name"] in self.weather_data]

        if not spots_to_analyze:
            return {"success": False, "error": "Keine zu analysierenden Spots gefunden"}

        forecast_dates = self._get_forecast_dates()
        if not forecast_dates:
            return {"success": False, "error": "Keine Vorhersage-Tage verfügbar"}

        spots_by_name = {s["name"]: s for s in spots_to_analyze}

        # ── PRE-VALIDATION: Vollständigkeit pro Spot prüfen ──
        incomplete_spot_days = {}  # {spot_name: set(date_strs)}
        for spot in spots_to_analyze:
            name = spot["name"]
            spot_data = self.weather_data.get(name, {})
            hourly_data = spot_data.get("hourly_data", {})
            missing = validate_spot_data(name, hourly_data, config.FORECAST_DAYS)
            if missing:
                incomplete_spot_days[name] = set(missing)
                logger.warning(f"Unvollständige Daten für {name}: {', '.join(missing)} — keine KI-Analyse für diese Tage")

        # ── PHASE 1: Safety-Checks (alle Spots parallel) ──
        total_safety = len(spots_to_analyze) * len(forecast_dates)
        skipped_no_data = 0
        logger.info(f"Phase 1 (Safety): {len(spots_to_analyze)} Spots × {len(forecast_dates)} Tage = {total_safety} Aufrufe")

        safety_results = {}  # {spot_name: {date_str: safety_dict}}

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {}
            for spot in spots_to_analyze:
                for date_str in forecast_dates:
                    # Unvollständige Daten → kein LLM-Call
                    if date_str in incomplete_spot_days.get(spot["name"], set()):
                        safety_results.setdefault(spot["name"], {})[date_str] = {
                            "spot": spot["name"],
                            "date": date_str,
                            "safety_status": "no_data",
                            "phase": "safety",
                            "summary": "Wetterdaten unvollständig — keine KI-Analyse möglich (Modell-Update?)",
                        }
                        skipped_no_data += 1
                        continue

                    ctx = self._build_single_spot_context(spot, date_str, mode="dashboard")
                    if ctx:
                        future = executor.submit(self._safety_check_single_spot_day, spot, date_str, ctx)
                        futures[future] = (spot["name"], date_str)
                    else:
                        safety_results.setdefault(spot["name"], {})[date_str] = {
                            "spot": spot["name"],
                            "date": date_str,
                            "safety_status": "no_data",
                            "phase": "safety",
                            "summary": "Keine Wetterdaten für diesen Tag",
                        }

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

        logger.info(f"Phase 1 fertig. {len(flyability_tasks)} von {total_safety} Spot/Tag-Kombis sind sicher → Phase 2 ({skipped_no_data} übersprungen wegen fehlender Daten)")

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
        merged = self.spot_analyses.copy()
        for spot_name, days in safety_results.items():
            merged[spot_name] = {}
            for date_str, safety in days.items():
                entry = {"safety": safety}
                fly = flyability_results.get(spot_name, {}).get(date_str)
                # Fliegbarkeit getrennt von Sicherheit: fly_status = gray|green|violet; nur bei not_safe fehlt sie
                safety_status = safety.get("safety_status", "error")
                if fly:
                    tier = _normalize_flyability_tier(
                        fly.get("flyability_tier") or fly.get("status")
                    )
                    fly["flyability_tier"] = tier
                    fly["status"] = tier
                    entry["flyability"] = fly
                    entry["fly_status"] = tier
                    entry["status"] = tier
                elif safety_status == "not_safe":
                    entry["fly_status"] = ""
                    entry["status"] = "not_safe"
                elif safety_status == "no_data":
                    entry["fly_status"] = ""
                    entry["status"] = "no_data"
                elif safety_status == "error":
                    entry["fly_status"] = ""
                    entry["status"] = "error"
                else:
                    entry["fly_status"] = ""
                    entry["status"] = "error"
                entry["best_window"] = safety.get("safe_window", "keins")
                entry["recommendation"] = ""
                if fly:
                    entry["recommendation"] = fly.get("recommendation", "")
                    entry["best_window"] = fly.get("best_window", entry["best_window"])
                merged[spot_name][date_str] = entry

        self.spot_analyses = merged
        self.analyses_loaded_at = datetime.now()
        self._save_analyses_cache()

        if self.instantdb:
            threading.Thread(target=self._push_analyses_to_instantdb, daemon=True).start()

        # Summary: Sicherheit und Fliegbarkeit getrennt
        per_day_counts = {}
        for date_str in forecast_dates:
            safety_c = {"safe": 0, "conditional": 0, "not_safe": 0, "no_data": 0}
            fly_c = {"gray": 0, "green": 0, "violet": 0}
            err_n = 0
            for spot_name, days in merged.items():
                ent = days.get(date_str, {})
                ss = ent.get("safety", {}).get("safety_status", "error")
                if ss in safety_c:
                    safety_c[ss] += 1
                else:
                    err_n += 1
                ft = ent.get("fly_status") or ""
                if ft in fly_c:
                    fly_c[ft] += 1
            per_day_counts[date_str] = {
                "safety": safety_c,
                "fly": fly_c,
                "error": err_n,
            }

        actual_safety_calls = total_safety - skipped_no_data
        total_calls = actual_safety_calls + len(flyability_tasks)
        logger.info(f"Spot-Analysen abgeschlossen: {total_calls} LLM-Aufrufe ({actual_safety_calls} Safety + {len(flyability_tasks)} Flyability, {skipped_no_data} übersprungen wegen fehlender Daten)")

        results_summary = {}
        for spot_name, days in merged.items():
            results_summary[spot_name] = {}
            for date_str, entry in days.items():
                results_summary[spot_name][date_str] = {
                    "status": entry.get("status", "error"),
                    "safety_status": entry.get("safety", {}).get("safety_status", "error"),
                    "fly_status": entry.get("fly_status", ""),
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

                    ss = safety.get("safety_status", "error")
                    fly = entry.get("flyability", {})
                    # Phase 2 nur bei safe/conditional — sonst alte InstantDB-Felder explizit leeren (Merge behält sonst Altlasten)
                    if fly and ss in ("safe", "conditional"):
                        doc_data["fly_status"] = _normalize_flyability_tier(
                            fly.get("flyability_tier") or fly.get("status")
                        )
                        doc_data["flight_type"] = fly.get("flight_type", "")
                        doc_data["flight_duration"] = fly.get("flight_duration_estimate", "")
                        doc_data["xc_potential"] = fly.get("xc_potential", "")
                        doc_data["peak_climb_rate"] = fly.get("peak_climb_rate", 0)
                        doc_data["flyability_feedback"] = fly.get("recommendation", "")
                    else:
                        doc_data["fly_status"] = ""
                        doc_data["flight_type"] = ""
                        doc_data["flight_duration"] = ""
                        doc_data["xc_potential"] = ""
                        doc_data["peak_climb_rate"] = 0
                        doc_data["flyability_feedback"] = ""

                    docs[doc_id] = doc_data

            if self.instantdb.batch_upsert("spot_analyses", docs):
                logger.info(f"InstantDB: {len(docs)} Spot-Analysen gepusht")
            else:
                logger.warning("InstantDB: Spot-Analysen push fehlgeschlagen")
        except Exception as e:
            logger.error(f"InstantDB Analysen-Push fehlgeschlagen: {e}")

    # ════════════════════════════════════════════════════════════════════════
    # REGION-ANALYSE (spiegelt Spot-Analyse-Flow)
    # ════════════════════════════════════════════════════════════════════════

    def _safety_check_single_region_day(self, region, date_str: str, context: str) -> dict:
        """Phase 1: Sicherheitscheck fuer eine Region/Tag via LLM."""
        rname = region["region"]
        try:
            if not context:
                return {"region": rname, "date": date_str, "safety_status": "error", "error": "Keine Daten"}

            messages = [
                {"role": "system", "content": REGION_SAFETY_CHECK_PROMPT},
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
            result["region"] = rname
            result["region_id"] = region["id"]
            result["date"] = date_str
            result["phase"] = "safety"

            # Hard override: Wenn WIND-STRONG die Mehrheit ausmacht und keine
            # einzige WIND-CALM Stunde existiert, ist der Tag nicht fliegbar.
            strong = result.get("wind_strong_count", 0)
            calm = result.get("wind_calm_count", 0)
            moderate = result.get("wind_moderate_count", 0)
            if (isinstance(strong, int) and isinstance(calm, int) and isinstance(moderate, int)
                    and calm == 0 and strong > moderate
                    and result.get("safety_status") in ("safe", "conditional")):
                logger.warning(
                    f"Region Safety-Override fuer {rname}/{date_str}: LLM gab "
                    f"'{result.get('safety_status')}' trotz {strong} WIND-STRONG, "
                    f"0 WIND-CALM, {moderate} WIND-MODERATE → not_safe"
                )
                result["safety_status"] = "not_safe"
                result["safe_window"] = "keins"
                nogo = result.get("no_go_reasons", [])
                if not any("WIND-STRONG" in r for r in nogo):
                    nogo.append(f"Ueberwiegend WIND-STRONG ({strong} von {strong + moderate} Stunden), keine ruhige Phase")
                result["no_go_reasons"] = nogo

            return result

        except Exception as e:
            logger.error(f"Region Safety-Check fuer {rname}/{date_str} fehlgeschlagen: {e}")
            return {"region": rname, "region_id": region["id"], "date": date_str,
                    "safety_status": "error", "phase": "safety", "error": str(e)}

    def _flyability_single_region_day(self, region, date_str: str, safety_result: dict, context: str) -> dict:
        """Phase 2: Flugtauglichkeit fuer eine bereits als sicher eingestufte Region/Tag."""
        rname = region["region"]
        try:
            if not context:
                return {"region": rname, "date": date_str, "status": "error", "error": "Keine Daten"}

            safe_window = safety_result.get("safe_window", "unbekannt")
            safety_status = safety_result.get("safety_status", "safe")
            caution_notes = safety_result.get("caution_notes", [])

            safety_context = (
                f"\n═══ SICHERHEITSANALYSE (bereits geprueft) ═══\n"
                f"Safety-Status: {safety_status}\n"
                f"Sicheres Fenster: {safe_window}\n"
            )
            if caution_notes:
                safety_context += f"Vorsichtshinweise: {', '.join(caution_notes)}\n"
            safety_context += "Analysiere NUR die Stunden innerhalb des sicheren Fensters.\n"

            messages = [
                {"role": "system", "content": REGION_FLYABILITY_PROMPT},
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
            tier = _normalize_flyability_tier(
                result.get("flyability_tier") or result.get("status")
            )
            result["flyability_tier"] = tier
            result["status"] = tier
            result["region"] = rname
            result["region_id"] = region["id"]
            result["date"] = date_str
            result["phase"] = "flyability"
            return result

        except Exception as e:
            logger.error(f"Region Flyability fuer {rname}/{date_str} fehlgeschlagen: {e}")
            return {"region": rname, "region_id": region["id"], "date": date_str,
                    "status": "error", "phase": "flyability", "error": str(e)}

    def run_region_analyses(self) -> dict:
        """Zweiphasen-Orchestrierung fuer Regionen: Safety → Filter → Flyability."""
        if not self.client:
            return {"success": False, "error": "OPENAI_API_KEY nicht konfiguriert"}

        if not self.region_weather_data:
            return {"success": False, "error": "Keine Region-Wetterdaten geladen"}

        all_regions = get_all_regions()
        regions_with_data = [r for r in all_regions if r["id"] in self.region_weather_data]

        if not regions_with_data:
            return {"success": False, "error": "Keine Regionen mit Wetterdaten"}

        forecast_dates = self._get_forecast_dates()
        if not forecast_dates:
            return {"success": False, "error": "Keine Vorhersage-Tage verfuegbar"}

        regions_by_id = {r["id"]: r for r in regions_with_data}

        # ── PHASE 1: Safety-Checks ──
        total_safety = len(regions_with_data) * len(forecast_dates)
        logger.info(f"Region Phase 1 (Safety): {len(regions_with_data)} Regionen × {len(forecast_dates)} Tage = {total_safety}")

        safety_results = {}  # {region_id: {date_str: safety_dict}}

        with ThreadPoolExecutor(max_workers=3) as executor:
            futures = {}
            for region in regions_with_data:
                for date_str in forecast_dates:
                    ctx = self._build_single_region_context(region, date_str)
                    if ctx:
                        future = executor.submit(
                            self._safety_check_single_region_day, region, date_str, ctx
                        )
                        futures[future] = (region["id"], date_str)
                    else:
                        safety_results.setdefault(region["id"], {})[date_str] = {
                            "region": region["region"], "region_id": region["id"],
                            "date": date_str, "safety_status": "no_data",
                            "phase": "safety", "summary": "Keine Wetterdaten fuer diesen Tag",
                        }

            for future in as_completed(futures):
                rid, date_str = futures[future]
                try:
                    result = future.result()
                except Exception as e:
                    logger.error(f"Region Safety-Future {rid}/{date_str} fehlgeschlagen: {e}")
                    result = {"region_id": rid, "date": date_str, "safety_status": "error", "error": str(e)}
                safety_results.setdefault(rid, {})[date_str] = result

        # ── FILTER ──
        flyability_tasks = []
        for rid, days in safety_results.items():
            for date_str, safety in days.items():
                status = safety.get("safety_status", "error")
                if status in ("safe", "conditional"):
                    flyability_tasks.append((regions_by_id[rid], date_str, safety))

        logger.info(f"Region Phase 1 fertig. {len(flyability_tasks)} von {total_safety} sicher → Phase 2")

        # ── PHASE 2: Flyability ──
        flyability_results = {}

        if flyability_tasks:
            with ThreadPoolExecutor(max_workers=3) as executor:
                futures = {}
                for region, date_str, safety in flyability_tasks:
                    ctx = self._build_single_region_context(region, date_str)
                    future = executor.submit(
                        self._flyability_single_region_day, region, date_str, safety, ctx
                    )
                    futures[future] = (region["id"], date_str)

                for future in as_completed(futures):
                    rid, date_str = futures[future]
                    try:
                        result = future.result()
                    except Exception as e:
                        logger.error(f"Region Flyability-Future {rid}/{date_str} fehlgeschlagen: {e}")
                        result = {"region_id": rid, "date": date_str, "status": "error", "error": str(e)}
                    flyability_results.setdefault(rid, {})[date_str] = result

        # ── MERGE ──
        merged = {}
        for rid, days in safety_results.items():
            merged[rid] = {}
            for date_str, safety in days.items():
                entry = {"safety": safety}
                fly = flyability_results.get(rid, {}).get(date_str)
                safety_status = safety.get("safety_status", "error")
                if fly:
                    tier = _normalize_flyability_tier(
                        fly.get("flyability_tier") or fly.get("status")
                    )
                    fly["flyability_tier"] = tier
                    fly["status"] = tier
                    entry["flyability"] = fly
                    entry["fly_status"] = tier
                    entry["status"] = tier
                elif safety_status == "not_safe":
                    entry["fly_status"] = ""
                    entry["status"] = "not_safe"
                elif safety_status == "no_data":
                    entry["fly_status"] = ""
                    entry["status"] = "no_data"
                else:
                    entry["fly_status"] = ""
                    entry["status"] = "error"
                entry["best_window"] = safety.get("safe_window", "keins")
                entry["recommendation"] = ""
                if fly:
                    entry["recommendation"] = fly.get("recommendation", "")
                    entry["best_window"] = fly.get("best_window", entry["best_window"])
                entry["region_name"] = safety.get("region", regions_by_id.get(rid, {}).get("region", rid))
                merged[rid][date_str] = entry

        self.region_analyses = merged
        self.region_analyses_loaded_at = datetime.now()

        if self.instantdb:
            threading.Thread(target=self._push_region_analyses_to_instantdb, daemon=True).start()

        total_calls = total_safety + len(flyability_tasks)
        logger.info(f"Region-Analysen abgeschlossen: {total_calls} LLM-Aufrufe")

        return {
            "success": True,
            "results_count": total_calls,
            "regions_count": len(merged),
            "dates": forecast_dates,
        }

    def _push_region_analyses_to_instantdb(self):
        """Pusht Region-Analysen nach InstantDB."""
        try:
            docs = {}
            for rid, days in self.region_analyses.items():
                for date_str, entry in days.items():
                    doc_id = self.instantdb.make_id(f"region_analysis.{rid}.{date_str}")
                    safety = entry.get("safety", {})
                    fly = entry.get("flyability", {})
                    ss = safety.get("safety_status", "error")

                    doc_data = {
                        "region_id": rid,
                        "region_name": entry.get("region_name", rid),
                        "date": date_str,
                        "status": entry.get("status", "error"),
                        "best_window": entry.get("best_window", "?"),
                        "updated_at": self.region_analyses_loaded_at.isoformat(),
                        "safety_status": ss,
                        "safe_window": safety.get("safe_window", "keins"),
                        "safety_feedback": safety.get("summary", ""),
                        "foehn_risk": safety.get("foehn_risk", "none"),
                        "wind_summary": safety.get("wind_summary", ""),
                    }
                    for key in ["no_go_reasons", "caution_notes"]:
                        val = safety.get(key, [])
                        if isinstance(val, list):
                            doc_data[key] = json.dumps(val, ensure_ascii=False)
                        else:
                            doc_data[key] = str(val)

                    if fly and ss in ("safe", "conditional"):
                        doc_data["fly_status"] = _normalize_flyability_tier(
                            fly.get("flyability_tier") or fly.get("status")
                        )
                        doc_data["flight_type"] = fly.get("flight_type", "")
                        doc_data["flight_duration"] = fly.get("flight_duration_estimate", "")
                        doc_data["xc_potential"] = fly.get("xc_potential", "")
                        doc_data["peak_climb_rate"] = fly.get("peak_climb_rate", 0)
                        doc_data["flyability_feedback"] = fly.get("recommendation", "")
                    else:
                        doc_data["fly_status"] = ""
                        doc_data["flight_type"] = ""
                        doc_data["flight_duration"] = ""
                        doc_data["xc_potential"] = ""
                        doc_data["peak_climb_rate"] = 0
                        doc_data["flyability_feedback"] = ""

                    docs[doc_id] = doc_data

            if self.instantdb.batch_upsert("region_analyses", docs):
                logger.info(f"InstantDB: {len(docs)} Region-Analysen gepusht")
            else:
                logger.warning("InstantDB: Region-Analysen push fehlgeschlagen")
        except Exception as e:
            logger.error(f"InstantDB Region-Analysen-Push fehlgeschlagen: {e}")

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

            for name in sorted(self.weather_data.keys()):
                if name == "_meta": continue
                entry = self.spot_analyses.get(name, {}).get(date_str)
                if not entry:
                    continue

                safety = entry.get("safety", {})
                safety_status = safety.get("safety_status", "error")

                if safety_status == "error":
                    lines.append(f"  {name}: FEHLER — {safety.get('error', entry.get('error', 'unbekannt'))}")
                    continue

                status_label = {
                    "safe": "SICHER (Grün)",
                    "conditional": "BEDINGT SICHER (Orange)",
                    "not_safe": "NICHT SICHER (Rot)",
                    "no_data": "KEINE DATEN (unvollständig)",
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
                lines.append("─── PHASE 2: FLIEGBARKEIT (gray/grün/violett — unabhängig von Sicherheitsfarbe) ───")
                lines.append("")

                for name in safe_spots_today:
                    entry = self.spot_analyses[name].get(date_str, {})
                    fly = entry.get("flyability", {})

                    if not fly:
                        lines.append(f"  {name}: Keine Flyability-Daten")
                        continue

                    ft = _normalize_flyability_tier(
                        fly.get("flyability_tier") or fly.get("status")
                    )
                    status_label = {
                        "gray": "GRAU (Abgleiter/mau)",
                        "green": "GRÜN (fliegbar)",
                        "violet": "VIOLETT (legendär / starkes XC)",
                    }.get(ft, ft)

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

    def _build_compact_analyses_for_chat(self) -> str:
        """Kurzfassung der Voranalysen für den Chat — verhindert 'immer alle Spots als Tabelle'."""
        if not self.spot_analyses:
            return ""

        lines = [
            "VORANALYSEN — KURZÜBERSICHT (interne Datenbasis)",
            f"Stand: {self.analyses_loaded_at.isoformat() if self.analyses_loaded_at else 'unbekannt'}",
            "",
        ]

        all_dates = set()
        for days in self.spot_analyses.values():
            all_dates.update(days.keys())
        sorted_dates = sorted(all_dates)

        for date_str in sorted_dates:
            violet, green_f, gray_f = [], [], []
            not_safe, errors, no_data = [], [], []

            for name in sorted(self.weather_data.keys()):
                if name == "_meta": continue
                entry = self.spot_analyses.get(name, {}).get(date_str)
                if not entry:
                    continue
                safety = entry.get("safety", {})
                ss = safety.get("safety_status", "error")
                bw = entry.get("best_window", "?")
                if ss == "no_data":
                    no_data.append(name)
                    continue
                if ss == "error":
                    errors.append(name)
                    continue
                if ss == "not_safe":
                    not_safe.append(name)
                    continue
                ft = entry.get("fly_status") or ""
                if ft == "violet":
                    violet.append((name, bw))
                elif ft == "green":
                    green_f.append((name, bw))
                elif ft == "gray":
                    gray_f.append((name, bw))
                elif ft:
                    green_f.append((name, bw))

            lines.append(f"─── {date_str} ───")

            def _fmt_group(label: str, items: list):
                if not items:
                    return
                parts = [f"{n} (Fenster: {w})" for n, w in items]
                lines.append(f"  {label}: " + "; ".join(parts))

            _fmt_group("FLIEGBARKEIT legendär (violet)", violet)
            _fmt_group("FLIEGBARKEIT fliegbar (green)", green_f)
            _fmt_group("FLIEGBARKEIT Abgleiter/mau (gray)", gray_f)

            if not_safe:
                if len(not_safe) <= 12:
                    lines.append(f"  SICHERHEIT nicht ok (Phase 2 entfällt): {', '.join(not_safe)}")
                else:
                    lines.append(
                        f"  SICHERHEIT nicht ok (Phase 2 entfällt): {', '.join(not_safe[:12])} "
                        f"… (+{len(not_safe) - 12} weitere)"
                    )
            if no_data:
                lines.append(f"  DATEN UNVOLLSTÄNDIG (keine Analyse): {', '.join(no_data)}")
            if errors:
                lines.append(f"  Analyse fehlt/Fehler: {', '.join(errors)}")

            # Kurz-Tipps: violet zuerst, dann green
            tips = []
            for bucket in (violet, green_f):
                for name, _ in bucket:
                    if len(tips) >= 3:
                        break
                    ent = self.spot_analyses.get(name, {}).get(date_str, {})
                    rec = (ent.get("recommendation") or "").strip()
                    if not rec:
                        fly = ent.get("flyability") or {}
                        rec = (fly.get("recommendation") or "").strip()
                    if rec:
                        one = rec.replace("\n", " ").strip()
                        if len(one) > 160:
                            one = one[:157] + "…"
                        tips.append(f"    • {name}: {one}")
                if len(tips) >= 3:
                    break
            if tips:
                lines.append("  Kurz-Empfehlungen (Auszug):")
                lines.extend(tips)

            lines.append("")

        lines.append(
            "(Die vollständigen Einzelanalysen pro Spot stecken in dieser Kurzfassung nicht "
            "Wort für Wort — bei Detailfragen zu einem Namen kannst du gezielt vertiefen.)"
        )
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
                    ss = safety.get("safety_status", "error")
                    fs_raw = entry.get("fly_status") or ""
                    if ss in ("not_safe", "no_data"):
                        fs_raw = ""
                    elif not fs_raw and ss not in ("not_safe", "no_data", "error"):
                        legacy = entry.get("status") or ""
                        if legacy not in ("not_safe", "no_data", "error", ""):
                            fs_raw = legacy
                    fs = _normalize_flyability_tier(fs_raw) if fs_raw else ""
                    if ss == "not_safe":
                        st = "not_safe"
                        fs = ""
                    elif ss == "no_data":
                        st = "no_data"
                        fs = ""
                    elif fs:
                        st = fs
                    else:
                        st = entry.get("status", "error")
                    merged_entry = {
                        "safety": safety,
                        "status": st,
                        "fly_status": fs,
                        "best_window": entry.get("best_window", "?"),
                        "recommendation": entry.get("recommendation", ""),
                    }
                    if fs:
                        merged_entry["flyability"] = {
                            "flyability_tier": fs,
                            "status": fs,
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
            {
                "role": "system",
                "content": SYSTEM_PROMPT + "\n\n" + FOEHN_CHAT_KNOWLEDGE,
            },
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
            # Voranalysen vorhanden? → Kurzübersicht (Chat-tauglich), sonst Roh-Wetterkontext
            analyses_context = self._build_compact_analyses_for_chat()
            if analyses_context:
                # Kompakte Analyse enthält keinen globalen Föhn-Block — immer anhängen, sonst
                # antwortet das Modell bei „Föhn?“ ohne ΔP/Kammwind und rät falsch.
                foehn_snap = self._build_foehn_context_for_ai()
                context_block = analyses_context + "\n\n" + foehn_snap
            else:
                context_block = self.weather_context_str

            user_content = (
                f"AKTUELZEIT: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                "Hintergrunddaten für deine Antwort (nicht wörtlich als Gesamtreport ausgeben):\n"
                "==========================================================\n"
                f"{context_block}\n"
                "==========================================================\n"
                "Beantworte die Frage des Piloten **direkt** und in angemessenem Umfang — wie in einem "
                "kurzen Chat. Keine vollständige Tabelle aller Spots, es sei denn der Pilot verlangt "
                "ausdrücklich eine Übersicht/Tabelle **aller** Gebiete oder einen mehrzeiligen Vergleich.\n"
                "Bei **Föhn-Fragen**: die Föhn-Lage nur aus dem Block „FÖHN-INDIKATOR“ (ΔP, Kammwind, Level) "
                "ableiten — nicht aus „alle Spots nicht sicher“ schließen, dass es „keinen Föhn“ gäbe.\n\n"
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
                    "has_weather": spot_name in self.weather_data,
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
