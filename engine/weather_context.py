"""
Flychat Engine — Mixin: WeatherContextMixin.

Ausgeschnitten aus chat_engine.py (Monolith-Split). Methoden-Signaturen
unveraendert, Klasse wird via Mehrfachvererbung in FlychatEngine eingebunden.
"""

import copy
import json
import logging
import math
import os
import re
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, wait, FIRST_COMPLETED
from datetime import datetime, timedelta
from pathlib import Path

import config
from spots import load_spots
from fetch_weather import (
    fetch_all_spots, load_cached_weather, load_cached_weather_timestamp,
    is_cache_fresh, is_cache_complete, validate_spot_data,
)
from foehn_indicators import (
    fetch_foehn_data, evaluate_foehn, build_foehn_llm_context,
)
from thermik_calculator import (
    calculate_thermal_profile, calculate_dewpoint, get_terrain_zone,
)
from gust_calculator import (
    estimate_altitude_gusts, collect_gust_anchors,
    estimate_altitude_gusts_multi_anchor,
    apply_oi_gust_correction, aggregate_spot_excess, get_L_up,
    interpolate_gust_from_anchors,
)
from station_observations import StationManager
from source_area import (
    get_reference_points, _load_regions, find_region_for_point,
    get_all_regions,
)
from prompts import (
    SYSTEM_PROMPT, SAFETY_CHECK_PROMPT, FLYABILITY_PROMPT,
    REGION_SAFETY_CHECK_PROMPT, REGION_FLYABILITY_PROMPT,
    SPOT_COMBINED_PROMPT, REGION_COMBINED_PROMPT,
    WEEKLY_BRIEFING_PROMPT, CAPABILITIES_GUIDE, FOEHN_CHAT_KNOWLEDGE,
    format_foehn_llm_regional_guide,
)
from engine._common import (
    MAX_HISTORY_MESSAGES, MAX_TOOL_ITERATIONS,
    _MODEL_TOKEN_LIMITS, _DEFAULT_TOKEN_LIMIT, _TOKEN_BUDGET_RESERVE,
    _CTX_CACHE_MAX_ENTRIES,
    _estimate_tokens, _truncate_weather_context, _filter_context_by_days,
    _log_prompt_cache_usage, _weekday_de,
    _is_permanent_api_error, _user_friendly_api_error,
    _FLYABILITY_TIERS, _normalize_flyability_tier,
    _TIER_RATING_RANGES, _clamp_rating_to_tier, _compute_rating_from_subratings,
    _TAG_NATURAL, _TAG_NATURAL_MAP, _TAG_SANITIZE_RE,
    _sanitize_llm_text, _sanitize_llm_result,
    _LABEL_KEYS_NO_GO, _LABEL_KEYS_CONDITIONAL,
    _LABEL_KEYS_REDUCER, _LABEL_KEYS_BOOSTER,
    _NO_GO_RANK, _CONDITIONAL_RANK,
    _KEYWORD_TO_KEY_NO_GO, _KEYWORD_TO_KEY_CAUTION,
    _pick_key_from_list, _validate_key, _derive_primary_labels,
    COMPASS_POINTS, _compute_wind_trend, _detect_rain_sandwich,
    _detect_gust_trend, _format_gust_trend_text,
    _interpolate_wind_at_altitude,
)

logger = logging.getLogger(__name__)


class WeatherContextMixin:
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

            # Region-ID für Terrain-Klassifikation (einmal pro Spot)
            spot_region = find_region_for_point(spot["latitude"], spot["longitude"])
            spot_region_id = spot_region["id"] if spot_region else None

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

            # Per-Tag-Tracking für TAGESPROFIL-Block
            day_state = {"tag_counts": {}, "clean": 0, "total": 0, "day": None}

            def _emit_day_profile(state):
                """Hängt eine TAGESPROFIL-Zeile für einen abgeschlossenen Tag an."""
                if state["total"] == 0:
                    return
                clean_pct = (state["clean"] / state["total"]) * 100
                major_tags_order = [
                    "[GUST-DANGER]", "[ALOFT-DANGER]", "[ALOFT-GUST-DANGER]",
                    "[STRONG-WIND-WARN]", "[RAIN-WARN]", "[CAPE-DANGER]", "[CAPE-WARN]", "[THUNDERSTORM]", "[OVERCAST-DANGER]",
                    "[SHEAR-UNUSABLE]", "[THERMAL-TORN-UNUSABLE]", "[THERMAL-ROUGH-UNUSABLE]",
                    "[THERMAL-ROUGH-FRAGMENTED]",
                    "[GUST-WARN]", "[ALOFT-WARN]", "[ALOFT-GUST-WARN]",
                    "[SHEAR-DEGRADED]", "[THERMAL-TORN-DEGRADED]", "[THERMAL-ROUGH-DEGRADED]",
                    "[WIND-WRONG]",
                ]
                hist_parts = []
                for t in major_tags_order:
                    cnt = state["tag_counts"].get(t, 0)
                    if cnt > 0:
                        hist_parts.append(f"{t.strip('[]')} {cnt}h")
                hist_str = (" | Hauptgefahren: " + ", ".join(hist_parts)) if hist_parts else ""
                warn = ""
                if 0 < clean_pct < 35:
                    warn = "  → ACHTUNG <35%: Tag überwiegend gefährlich, max. conditional!"
                hourly_lines.append(
                    f"  ═══ TAGESPROFIL {state['day']} ({_weekday_de(state['day'])}): "
                    f"{state['clean']}/{state['total']}h sauber = {clean_pct:.0f}%"
                    f"{hist_str}{warn}"
                )

            for timestamp in sorted_times:
                current_day = timestamp[:10]
                if current_day != prev_day:
                    # Vorherigen Tag abschließen
                    _emit_day_profile(day_state)
                    day_state = {"tag_counts": {}, "clean": 0, "total": 0, "day": current_day}
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
                        region_id=spot_region_id,
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
                low_cl = float(data.get("cloud_cover_low") or 0)
                mid_cl = float(data.get("cloud_cover_mid") or 0)
                high_cl = float(data.get("cloud_cover_high") or 0)
                precip = data.get("precipitation", "N/A")
                sunshine = data.get("sunshine_duration", "N/A")
                sunshine_str = f"{sunshine / 3600:.2f}h" if isinstance(sunshine, (int, float)) and sunshine > 0 else "0h"

                # Wind-Check (Boden-10m bestimmt WIND-OK/WRONG)
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
                    # Display levels mit 3 Klassen (siehe _build_single_spot_context):
                    #   * = Flugbereich, ~ = Buffer (thermik+1500m), kein Marker = 850/700 Föhn-Anker
                    buffer_top = effective_ceiling + 500
                    display_levels_set = set()
                    for level in config.PRESSURE_LEVELS:
                        h_val = pl_data.get(f"geopotential_height_{level}hPa")
                        if h_val is None:
                            continue
                        if spot["elevation_m"] <= h_val <= buffer_top:
                            display_levels_set.add(level)
                    display_levels_set.add(850)
                    display_levels_set.add(700)

                    display_levels = []
                    for level in sorted(display_levels_set, reverse=True):
                        h_val = pl_data.get(f"geopotential_height_{level}hPa")
                        ws = pl_data.get(f"wind_speed_{level}hPa")
                        wd = pl_data.get(f"wind_direction_{level}hPa")
                        if h_val is not None and ws is not None:
                            display_levels.append({"pressure": level, "altitude": h_val,
                                                   "wind_speed": ws, "wind_direction": wd})

                    if display_levels:
                        display_with_gusts = estimate_altitude_gusts(
                            wind_speed_10m=wind_speed,
                            wind_gusts_10m=wind_gusts,
                            pressure_levels_data=display_levels,
                            elevation_m=spot["elevation_m"],
                            boundary_layer_height=data.get("boundary_layer_height"),
                        )
                        for lv in display_with_gusts:
                            alt = lv["altitude"]
                            in_range = spot["elevation_m"] <= alt <= effective_ceiling
                            in_buffer = effective_ceiling < alt <= buffer_top
                            if in_range:
                                marker = "*"
                            elif in_buffer:
                                marker = "~"
                            else:
                                marker = ""
                            ws_val = lv["wind_speed"]
                            g_val = lv.get("wind_gusts")
                            wd_val = lv.get("wind_direction")
                            if g_val is not None and g_val > ws_val + 2:
                                wind_str = f"{ws_val:.0f}/{g_val:.0f}"
                            else:
                                wind_str = f"{ws_val:.0f}"
                            dir_str = f" aus {wd_val:.0f}°" if wd_val is not None else ""
                            alt_wind_info += f" | {lv['pressure']}hPa({int(alt)}m){marker}: {wind_str}km/h{dir_str}"
                            if in_range:
                                if ws_val > 40:
                                    aloft_danger = True
                                elif ws_val > 30:
                                    aloft_warn = True
                                if g_val is not None:
                                    # T(z) > 40 km/h im Flugbereich = DANGER,
                                    # unabhängig vom Modellwind W(z).
                                    # Turbulenzrisiko >40 km/h ist ein Sicherheits-
                                    # problem auch bei moderatem Grundwind.
                                    if g_val > 40:
                                        aloft_gust_danger = True
                                    elif g_val > 30:
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
                        # CAPE-DANGER (hart): extreme Instabilitaet oder CAPE + Regen/Schauer (aktive Ueberentwicklung)
                        # CAPE-WARN (soft): Potenzial vorhanden, aber Modell prognostiziert keinen Trigger → conditional
                        if cape > 1500 or "[RAIN-WARN]" in warnings:
                            warnings.append("[CAPE-DANGER]")
                        else:
                            warnings.append("[CAPE-WARN]")
                except Exception:
                    pass

                # WMO weather_code 95/96/99 = Gewitter (deterministisches Modellsignal)
                try:
                    wcode = data.get("weather_code")
                    if isinstance(wcode, (int, float)) and int(wcode) in (95, 96, 99):
                        warnings.append("[THUNDERSTORM]")
                except Exception:
                    pass

                # OVERCAST-DANGER: nur wenn Wolkenbasis gefährlich nahe an Flughöhe
                if (cloud_base_raw is not None
                        and isinstance(cloud_base_raw, (int, float))
                        and isinstance(cloud_cover, (int, float))
                        and cloud_cover >= 75
                        and cloud_base_raw < spot["elevation_m"] + 500):
                    warnings.append("[OVERCAST-DANGER]")

                warning_str = " " + " ".join(warnings) if warnings else ""

                # Tag-Histogram pro Tag für TAGESPROFIL
                for w in warnings:
                    day_state["tag_counts"][w] = day_state["tag_counts"].get(w, 0) + 1
                if not is_ok:
                    day_state["tag_counts"][wind_status] = day_state["tag_counts"].get(wind_status, 0) + 1
                # "Clean" = WIND-OK ohne harte Warnungen
                hard_warnings_set = {"[GUST-DANGER]", "[ALOFT-DANGER]", "[ALOFT-GUST-DANGER]",
                                     "[RAIN-WARN]", "[CAPE-DANGER]", "[THUNDERSTORM]", "[STRONG-WIND-WARN]", "[OVERCAST-DANGER]"}
                has_hard = bool(hard_warnings_set & set(warnings))
                if is_ok and not has_hard:
                    day_state["clean"] += 1
                day_state["total"] += 1

                # Surface gust excess for LLM context
                sfc_excess = ""
                if isinstance(wind_gusts, (int, float)) and isinstance(wind_speed, (int, float)):
                    exc = max(0, wind_gusts - wind_speed)
                    sfc_excess = f", Exzess +{exc:.0f}km/h"

                hourly_lines.append(
                    f"{time_str}: Temp {temp}°C | Wind {wind_speed}km/h aus {wind_dir}° (Turbulenzrisiko {wind_gusts}km/h{sfc_excess}) {wind_status}{warning_str} | "
                    f"Wolkenbasis {cloud_base} | Bewölkung {cloud_cover}% (tief {low_cl:.0f}%, mittel {mid_cl:.0f}%, hoch {high_cl:.0f}%) | Sonne {sunshine_str}{alt_wind_info}{thermal_info}"
                )

            # Letzten Tag noch abschließen
            _emit_day_profile(day_state)

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
        cumulative_bf=0.0, peak_H=0.0, peak_sw=0.0, region_id=None,
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
            region_id=region_id,
        )
        return therm

    def _calculate_wind_shear(self, wind_speed_10m, pl_data, elevation_m, thermal_top_m):
        """
        Berechnet die vertikale Windscherung dU/dz durch die Thermikschicht.

        Returns: (dU_dz_kmh_per_100m, u_top_kmh, u_sfc_kmh) oder (None, None, None)
        falls keine pressure levels verfuegbar.

        Basis: meteo_research/wind_shear_thermal_quality.md Abschnitt 3.2/3.3.
        """
        if not isinstance(wind_speed_10m, (int, float)):
            return (None, None, None)
        if not pl_data or not isinstance(thermal_top_m, (int, float)):
            return (None, None, None)
        if thermal_top_m <= elevation_m:
            return (None, None, None)

        # Sammle alle pressure-level Winde zwischen elevation und thermal_top
        winds_in_layer = []
        for level in config.PRESSURE_LEVELS:
            h_val = pl_data.get(f"geopotential_height_{level}hPa")
            ws_val = pl_data.get(f"wind_speed_{level}hPa")
            if h_val is None or ws_val is None:
                continue
            if elevation_m <= h_val <= thermal_top_m:
                winds_in_layer.append((h_val, ws_val))

        if len(winds_in_layer) < 1:
            return (None, None, None)

        # Waehle den hoechsten Punkt in der Schicht als U_top
        winds_in_layer.sort(key=lambda x: x[0])
        h_top, u_top = winds_in_layer[-1]

        # Distanz vom 10 m ueber Grund (~ wind_speed_10m Referenz) bis h_top
        dz_m = h_top - elevation_m
        if dz_m < 200:
            # Zu duenne Schicht fuer belastbare Scherungs-Schaetzung
            return (None, None, None)

        du_kmh = abs(u_top - wind_speed_10m)
        du_dz_kmh_per_100m = (du_kmh / dz_m) * 100.0
        return (du_dz_kmh_per_100m, u_top, wind_speed_10m)

    def _calculate_segment_shear(self, wind_speed_10m, pl_data, elevation_m, thermal_top_m):
        """
        Berechnet Windscherung pro Segment zwischen konsekutiven Levels.

        Sammelt Surface-Anker (elevation_m, wind_speed_10m) + alle PL-Windpunkte
        innerhalb [elevation_m, thermal_top_m]. Berechnet dU/dz zwischen
        aufeinanderfolgenden Levels.

        Returns: (segments, column_shear)
            segments: list of dicts with keys: alt_lo, alt_hi, du_dz, wind_lo, wind_hi
            column_shear: (du_dz_kmh_per_100m, u_top, u_sfc) fuer Rueckwaertskompatibilitaet
        """
        empty = ([], (None, None, None))
        if not isinstance(wind_speed_10m, (int, float)):
            return empty
        if not pl_data or not isinstance(thermal_top_m, (int, float)):
            return empty
        if thermal_top_m <= elevation_m:
            return empty

        # Sammle Windpunkte: Surface-Anker + pressure levels in der Schicht
        points = [(elevation_m, wind_speed_10m)]
        for level in config.PRESSURE_LEVELS:
            h_val = pl_data.get(f"geopotential_height_{level}hPa")
            ws_val = pl_data.get(f"wind_speed_{level}hPa")
            if h_val is None or ws_val is None:
                continue
            if elevation_m < h_val <= thermal_top_m:
                points.append((h_val, ws_val))

        if len(points) < 2:
            return empty

        points.sort(key=lambda x: x[0])

        # Segmente zwischen konsekutiven Levels
        MIN_SEGMENT_DZ = 50  # m
        segments = []
        for i in range(len(points) - 1):
            h_lo, w_lo = points[i]
            h_hi, w_hi = points[i + 1]
            dz = h_hi - h_lo
            if dz < MIN_SEGMENT_DZ:
                continue
            du_kmh = abs(w_hi - w_lo)
            du_dz = (du_kmh / dz) * 100.0
            segments.append({
                "alt_lo": h_lo,
                "alt_hi": h_hi,
                "du_dz": du_dz,
                "wind_lo": w_lo,
                "wind_hi": w_hi,
            })

        # Column shear fuer Rueckwaertskompatibilitaet
        h_bottom, w_bottom = points[0]
        h_top, w_top = points[-1]
        total_dz = h_top - h_bottom
        if total_dz < 200:
            column_shear = (None, None, None)
        else:
            col_du_dz = (abs(w_top - w_bottom) / total_dz) * 100.0
            column_shear = (col_du_dz, w_top, w_bottom)

        return (segments, column_shear)

    def _calculate_bs_ratio(self, climb_rate_ms, du_dz_kmh_per_100m):
        """
        Einfacher B/S-Proxy nach meteo_research/wind_shear_thermal_quality.md 3.3:
            simple_BS = w* / dU_dz * 100
        mit w* in m/s und dU_dz in km/h/100m. Die Eichung (siehe config.py
        BS_RATIO_THRESHOLDS) bildet die Standardform ab: ≥100 gut, ≤60 zerrissen.

        Returns: float oder None bei unbrauchbaren Eingaben.
        """
        if not isinstance(climb_rate_ms, (int, float)) or climb_rate_ms <= 0:
            return None
        if not isinstance(du_dz_kmh_per_100m, (int, float)) or du_dz_kmh_per_100m <= 0:
            return None
        return (climb_rate_ms / du_dz_kmh_per_100m) * 100.0

    def _calculate_gust_factor(self, wind_speed_10m, wind_gusts_10m, climb_rate_ms):
        """
        Boeigkeitsfaktor relativ zur Thermik-Vertikalgeschwindigkeit:
            GF = mechanical_excess / w*
        Konvektive Baseline (BETA × w*) wird abgezogen (Panofsky et al. 1977).
        Abschnitt 3.4 + 3.5 im Research-Dokument.

        Returns: float oder None.
        """
        if not isinstance(wind_speed_10m, (int, float)):
            return None
        if not isinstance(wind_gusts_10m, (int, float)):
            return None
        if not isinstance(climb_rate_ms, (int, float)) or climb_rate_ms <= 0:
            return None
        delta_ms = max(0.0, (wind_gusts_10m - wind_speed_10m) / 3.6)
        # Konvektive Baseline abziehen (Panofsky et al. 1977):
        # Auf Thermiktagen stammt ein Teil des Böen-Excess aus der
        # Konvektion selbst (≈ BETA × w*), nicht aus mechanischer Störung.
        mechanical_ms = max(0.0, delta_ms - config.CONVECTIVE_GUST_BETA * climb_rate_ms)
        if mechanical_ms <= 0:
            return None
        return mechanical_ms / climb_rate_ms

    @staticmethod
    def _parabolic_climb(alt, elevation_m, max_height_m, peak_climb_ms):
        """Lokale Steigrate aus parabolischem Profil (0 an Basis/Top, Peak in Mitte)."""
        if alt <= elevation_m or alt >= max_height_m or peak_climb_ms <= 0:
            return 0.0
        mid = (elevation_m + max_height_m) / 2
        half = (max_height_m - elevation_m) / 2
        if half <= 0:
            return 0.0
        return max(0.0, peak_climb_ms * (1 - ((alt - mid) / half) ** 2))

    def _thermal_quality_tags(
        self,
        wind_speed_10m,
        wind_gusts_10m,
        pl_data,
        elevation_m,
        thermal_top_m,
        climb_rate_ms,
        region_id=None,
        altitude_gusts=None,
    ):
        """
        Berechnet die 7 Thermik-Qualitaets-Tags pro Stunde:
            [SHEAR-DEGRADED]/[SHEAR-UNUSABLE]
            [THERMAL-TORN-DEGRADED]/[THERMAL-TORN-UNUSABLE]
            [THERMAL-ROUGH-DEGRADED]/[THERMAL-ROUGH-FRAGMENTED]/[THERMAL-ROUGH-UNUSABLE]

        Zusaetzlich: Per-Segment-Klassifikation fuer TQ-Ratio.
        Jedes Segment (zwischen konsekutiven Windlevels) bekommt eigene Tags.
        tq_ratio = {"total": N, "clean": M, "tags": {"SHEAR-DEG": k, ...}}

        Returns: (list_of_tags, debug_dict).
        """
        tags = []
        debug = {"du_dz": None, "bs": None, "gf": None, "zone": None, "tq_ratio": None}

        # Gate: keine Thermik -> keine Qualitaets-Tags
        if (not isinstance(climb_rate_ms, (int, float))
                or climb_rate_ms < config.THERMAL_QUALITY_MIN_CLIMB):
            return (tags, debug)

        terrain_zone = get_terrain_zone(elevation_m, region_id)
        debug["zone"] = terrain_zone

        # --- Per-Segment Shear ---
        shear_cfg = config.SHEAR_THRESHOLDS.get(
            terrain_zone, config.SHEAR_THRESHOLDS["alpen"]
        )
        segments, column_shear = self._calculate_segment_shear(
            wind_speed_10m, pl_data, elevation_m, thermal_top_m
        )
        du_dz = column_shear[0]
        debug["du_dz"] = du_dz

        # Column-level SHEAR tags (Rueckwaertskompatibilitaet)
        if du_dz is not None:
            if du_dz >= shear_cfg["danger"]:
                tags.append("[SHEAR-UNUSABLE]")
            elif du_dz >= shear_cfg["warn"]:
                tags.append("[SHEAR-DEGRADED]")

        # --- B/S Ratio (Thermik zerrissen) ---
        bs = self._calculate_bs_ratio(climb_rate_ms, du_dz)
        debug["bs"] = bs
        if bs is not None:
            if bs <= config.BS_RATIO_THRESHOLDS["danger"]:
                tags.append("[THERMAL-TORN-UNUSABLE]")
            elif bs <= config.BS_RATIO_THRESHOLDS["warn"]:
                tags.append("[THERMAL-TORN-DEGRADED]")

        # --- Gust Factor (Thermik ruppig) ---
        surface_gf = self._calculate_gust_factor(wind_speed_10m, wind_gusts_10m, climb_rate_ms)
        debug["gf"] = surface_gf

        # Per-altitude GF: Turbulenz-Exzess auf jeder Hoehenstufe vs. Peak-Steigrate.
        gf_altitude = {}
        worst_gf = surface_gf
        # Mechanischen Exzess mitfuehren fuer FRAGMENTED vs UNUSABLE Unterscheidung
        surface_mechanical_ms = (surface_gf * climb_rate_ms) if surface_gf is not None else None
        worst_mechanical_ms = surface_mechanical_ms
        if altitude_gusts and thermal_top_m and elevation_m:
            for lv in altitude_gusts:
                alt = lv.get("altitude")
                t_excess = lv.get("turbulence_excess")
                if alt is None or t_excess is None:
                    continue
                if not (elevation_m < alt < thermal_top_m):
                    continue
                local_excess_ms = t_excess / 3.6
                # Konvektive Baseline abziehen (gleicher Ansatz wie Surface-GF)
                local_mechanical_ms = max(0.0, local_excess_ms - config.CONVECTIVE_GUST_BETA * climb_rate_ms)
                if local_mechanical_ms <= 0:
                    continue
                local_gf = local_mechanical_ms / climb_rate_ms
                gf_altitude[int(alt)] = round(local_gf, 2)
                if worst_gf is None or local_gf > worst_gf:
                    worst_gf = local_gf
                    worst_mechanical_ms = local_mechanical_ms
        debug["gf_altitude"] = gf_altitude

        if worst_gf is not None:
            if worst_gf >= config.GUST_FACTOR_THRESHOLDS["danger"]:
                if worst_mechanical_ms is not None and worst_mechanical_ms < config.GF_DANGER_MIN_MECHANICAL_MS:
                    tags.append("[THERMAL-ROUGH-FRAGMENTED]")
                else:
                    tags.append("[THERMAL-ROUGH-UNUSABLE]")
            elif worst_gf >= config.GUST_FACTOR_THRESHOLDS["warn"]:
                tags.append("[THERMAL-ROUGH-DEGRADED]")

        # --- Per-Segment Klassifikation fuer TQ-Ratio ---
        # Jedes Segment bekommt eigene Tags basierend auf lokaler Scherung,
        # lokaler B/S-Ratio (mit parabolischer Steigrate) und worst GF im Segment.
        CLIMB_FLOOR = 0.3  # m/s — verhindert false-positives am Saeulenrand
        seg_results = []
        for seg in segments:
            seg_tags = []
            # Lokale Scherung
            if seg["du_dz"] >= shear_cfg["danger"]:
                seg_tags.append("SHEAR-UNU")
            elif seg["du_dz"] >= shear_cfg["warn"]:
                seg_tags.append("SHEAR-DEG")

            # Lokale B/S: Steigrate am Segment-Mittelpunkt
            seg_mid = (seg["alt_lo"] + seg["alt_hi"]) / 2
            local_climb = self._parabolic_climb(
                seg_mid, elevation_m, thermal_top_m, climb_rate_ms
            )
            local_climb = max(local_climb, CLIMB_FLOOR)
            if seg["du_dz"] > 0:
                local_bs = (local_climb / seg["du_dz"]) * 100.0
                if local_bs <= config.BS_RATIO_THRESHOLDS["danger"]:
                    seg_tags.append("TORN-UNU")
                elif local_bs <= config.BS_RATIO_THRESHOLDS["warn"]:
                    seg_tags.append("TORN-DEG")

            # Lokaler worst GF: suche altitude_gusts innerhalb des Segments
            seg_worst_gf = None
            seg_worst_mech_ms = None
            if altitude_gusts:
                for lv in altitude_gusts:
                    alt = lv.get("altitude")
                    t_excess = lv.get("turbulence_excess")
                    if alt is None or t_excess is None:
                        continue
                    if seg["alt_lo"] <= alt <= seg["alt_hi"]:
                        local_excess_ms = t_excess / 3.6
                        local_mech_ms = max(0.0, local_excess_ms - config.CONVECTIVE_GUST_BETA * max(local_climb, CLIMB_FLOOR))
                        if local_mech_ms <= 0:
                            continue
                        lf = local_mech_ms / max(local_climb, CLIMB_FLOOR)
                        if seg_worst_gf is None or lf > seg_worst_gf:
                            seg_worst_gf = lf
                            seg_worst_mech_ms = local_mech_ms
            # Surface GF gilt nur fuer das unterste Segment
            if seg["alt_lo"] == elevation_m and surface_gf is not None:
                if seg_worst_gf is None or surface_gf > seg_worst_gf:
                    seg_worst_gf = surface_gf
                    seg_worst_mech_ms = surface_mechanical_ms
            if seg_worst_gf is not None:
                if seg_worst_gf >= config.GUST_FACTOR_THRESHOLDS["danger"]:
                    if seg_worst_mech_ms is not None and seg_worst_mech_ms < config.GF_DANGER_MIN_MECHANICAL_MS:
                        seg_tags.append("ROUGH-FRAG")
                    else:
                        seg_tags.append("ROUGH-UNU")
                elif seg_worst_gf >= config.GUST_FACTOR_THRESHOLDS["warn"]:
                    seg_tags.append("ROUGH-DEG")

            seg_results.append({"alt_lo": seg["alt_lo"], "alt_hi": seg["alt_hi"], "tags": seg_tags})

        # TQ-Ratio Zaehlung
        if seg_results:
            n_total = len(seg_results)
            n_clean = sum(1 for s in seg_results if not s["tags"])
            tag_counts = {}
            for s in seg_results:
                for t in s["tags"]:
                    tag_counts[t] = tag_counts.get(t, 0) + 1
            debug["tq_ratio"] = {"total": n_total, "clean": n_clean, "tags": tag_counts}

        return (tags, debug)

    @staticmethod
    def _format_tq_ratio(tq_ratio):
        """
        Formatiert tq_ratio-Dict als kompakten String fuer LLM-Kontext.
        Input:  {"total": 8, "clean": 7, "tags": {"SHEAR-DEG": 1}}
        Output: "TQ 7/8 sauber, 1/8 SHEAR-DEG"
        Wenn alles sauber → leerer String (kein Extra-Text an guten Stunden).
        """
        if not tq_ratio:
            return ""
        total = tq_ratio.get("total", 0)
        clean = tq_ratio.get("clean", 0)
        tag_counts = tq_ratio.get("tags", {})
        if total <= 0:
            return ""
        if clean == total:
            return f"TQ {clean}/{total} sauber"
        parts = [f"TQ {clean}/{total} sauber"]
        for tag, count in sorted(tag_counts.items()):
            parts.append(f"{count}/{total} {tag}")
        return ", ".join(parts)

    def _calculate_thermal_for_hour(self, data, pl_data, elevation_m, timestamp, spot, prev_max_h=None, region_id=None):
        """Berechnet Thermik-Proxy für eine Stunde eines Spots."""
        therm = self._calculate_thermal_raw(data, pl_data, elevation_m, timestamp, spot, prev_max_h, region_id=region_id)

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
        foehn_dir = ev.get("foehn_direction", "none")

        # Prüfe ob die Föhn-Richtung für diesen Standort irrelevant ist
        direction_irrelevant = (
            foehn_dir != "none" and (
                (kritischer_foehn == "Süd" and foehn_dir == "Nord") or
                (kritischer_foehn == "Nord" and foehn_dir == "Süd")
            )
        )

        if ev["level"] == "none" and direction_irrelevant:
            # Föhn aktiv aber Richtung NICHT relevant für diesen Standort
            lines = [
                "═══ FÖHN-INDIKATOR ═══",
                f"KEIN FÖHN-RISIKO für diesen Standort.",
                f"Aktiver {foehn_dir}föhn (ΔP {ev['delta_p_hpa']} hPa) betrifft diesen Standort NICHT "
                f"(Kritischer Föhn: {kritischer_foehn} — nur {kritischer_foehn}föhn wäre hier gefährlich).",
                "→ foehn_risk = none. KEINE Föhn-Einträge in caution_notes oder no_go_reasons.",
            ]
        elif ev["level"] == "none":
            lines = [
                "═══ FÖHN-INDIKATOR ═══",
                "Kein Föhn aktiv. foehn_risk = none.",
            ]
        else:
            # Relevanter Föhn — vollständige Info anzeigen
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

    def _get_active_foehn_direction(self) -> str:
        """Bestimmt die aktuell dominante Föhn-Richtung: 'Süd', 'Nord', oder 'none'."""
        if not self.foehn_data:
            return "none"
        nord = self.foehn_data.get("nord", {})
        sued = self.foehn_data.get("sued", {})
        p_nord = nord.get("hourly", {}).get("pressure_msl", [])
        p_sued = sued.get("hourly", {}).get("pressure_msl", [])
        if not p_nord or not p_sued:
            return "none"
        max_dp_sued = 0.0  # P(Süd) - P(Nord) → Südföhn
        max_dp_nord = 0.0  # P(Nord) - P(Süd) → Nordföhn
        for pn, ps in zip(p_nord, p_sued):
            if pn is not None and ps is not None:
                dp = ps - pn
                if dp > max_dp_sued:
                    max_dp_sued = dp
                if -dp > max_dp_nord:
                    max_dp_nord = -dp
        if max_dp_sued >= 2:
            return "Süd"
        if max_dp_nord >= 2:
            return "Nord"
        return "none"

    def _strip_irrelevant_foehn(self, result: dict, kritischer_foehn: str) -> dict:
        """Entfernt Föhn-Warnungen aus LLM-Ergebnis wenn die Richtung nicht zum Standort passt."""
        if kritischer_foehn == "Beide":
            return result

        foehn_risk = result.get("foehn_risk", "none")
        if foehn_risk in ("none", "", None):
            return result

        active_dir = self._get_active_foehn_direction()
        if active_dir == "none":
            return result

        # Prüfe: Ist die aktive Richtung irrelevant für diesen Standort?
        is_irrelevant = (
            (kritischer_foehn == "Süd" and active_dir == "Nord") or
            (kritischer_foehn == "Nord" and active_dir == "Süd")
        )
        if not is_irrelevant:
            return result

        logger.warning(
            f"Föhn-Override: {active_dir}föhn aktiv aber Standort nur für "
            f"{kritischer_foehn}föhn empfindlich → foehn_risk=none"
        )
        result["foehn_risk"] = "none"

        # Föhn-Einträge aus caution_notes und no_go_reasons entfernen
        foehn_keywords = ["föhn", "foehn", "fohn", "δp", "delta-p", "delta_p", "druckgradient"]
        for key in ("caution_notes", "no_go_reasons"):
            items = result.get(key, [])
            if isinstance(items, list):
                result[key] = [
                    item for item in items
                    if not any(kw in (item or "").lower() for kw in foehn_keywords)
                ]

        return result

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
            f"WETTERDATEN FÜR: {name} — TAG: {date_str} ({_weekday_de(date_str)}) (Stand: {updated})",
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

        # Region-ID für Terrain-Klassifikation (einmal pro Spot)
        spot_region = find_region_for_point(spot["latitude"], spot["longitude"])
        spot_region_id = spot_region["id"] if spot_region else None

        sorted_times = sorted(hourly_data.keys())
        now = datetime.now()
        has_data = False
        wind_ok_hours = []
        wind_wrong_hours = []
        clean_hours = []       # WIND-OK ohne harte Warnungen
        warned_hours = []      # WIND-OK aber mit harten Warnungen (GUST/ALOFT/RAIN/CAPE)
        hourly_gusts = {}      # hour_str → gust value für Trend-Analyse
        rain_hours = []        # Stunden mit Niederschlag
        gust_hours = []        # Stunden mit GUST/ALOFT-GUST WARN/DANGER (fuer BOEEN-TREND)
        tag_counts = {}        # tag_name -> count über den ganzen Tag (für Tagesprofil)
        # Thermik-Qualitaets-Zaehler
        thermal_hours_total = 0  # Stunden mit climb > 0.3 m/s
        thermal_clean_h = 0     # Thermik-Stunden ohne Quality-Tags
        tq_rough_danger_h = 0
        tq_rough_warn_h = 0
        tq_torn_danger_h = 0
        tq_torn_warn_h = 0
        tq_shear_danger_h = 0
        tq_shear_warn_h = 0
        peak_climb_proxy = 0.0
        productive_thermal_h = 0   # Stunden mit climb>=0.7 + max(low,mid)<=70% + kein UNUSABLE

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
            h_climb = None
            h_max_h = None
            try:
                therm = self._calculate_thermal_raw(
                    data, pressure_level_data.get(timestamp, {}),
                    elevation_m, timestamp, spot,
                    region_id=spot_region_id,
                )
                if therm and "error" not in therm:
                    h_climb = therm["climb_rate"]
                    if isinstance(h_climb, (int, float)) and h_climb > peak_climb_proxy:
                        peak_climb_proxy = h_climb
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
            low_cl = float(data.get("cloud_cover_low") or 0)
            mid_cl = float(data.get("cloud_cover_mid") or 0)
            high_cl = float(data.get("cloud_cover_high") or 0)

            # Wind-Check (Boden-10m bestimmt WIND-OK/WRONG)
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
            display_with_gusts = None
            pl_data = pressure_level_data.get(timestamp, {})
            if pl_data:
                # Display levels mit 3 Klassen:
                #   * = Flugbereich (elevation bis effective_ceiling = thermik+1000m): harte Tags
                #   ~ = Buffer-Zone (effective_ceiling bis effective_ceiling+500m = thermik+1500m): nur Info
                #   ohne Marker: 850/700 hPa als Föhn-Anker
                buffer_top = effective_ceiling + 500
                display_levels_set = set()
                for level in config.PRESSURE_LEVELS:
                    h_val = pl_data.get(f"geopotential_height_{level}hPa")
                    if h_val is None:
                        continue
                    if spot["elevation_m"] <= h_val <= buffer_top:
                        display_levels_set.add(level)
                # Always include 850/700 for foehn detection
                display_levels_set.add(850)
                display_levels_set.add(700)

                display_levels = []
                for level in sorted(display_levels_set, reverse=True):
                    h_val = pl_data.get(f"geopotential_height_{level}hPa")
                    ws = pl_data.get(f"wind_speed_{level}hPa")
                    wd = pl_data.get(f"wind_direction_{level}hPa")
                    if h_val is not None and ws is not None:
                        display_levels.append({"pressure": level, "altitude": h_val,
                                               "wind_speed": ws, "wind_direction": wd})

                if display_levels:
                    display_with_gusts = estimate_altitude_gusts(
                        wind_speed_10m=wind_speed,
                        wind_gusts_10m=wind_gusts,
                        pressure_levels_data=display_levels,
                        elevation_m=spot["elevation_m"],
                        boundary_layer_height=data.get("boundary_layer_height"),
                    )
                    for lv in display_with_gusts:
                        alt = lv["altitude"]
                        in_range = spot["elevation_m"] <= alt <= effective_ceiling
                        in_buffer = effective_ceiling < alt <= buffer_top
                        if in_range:
                            marker = "*"
                        elif in_buffer:
                            marker = "~"
                        else:
                            marker = ""
                        ws_val = lv["wind_speed"]
                        g_val = lv.get("wind_gusts")
                        wd_val = lv.get("wind_direction")
                        if g_val is not None and g_val > ws_val + 2:
                            wind_str = f"{ws_val:.0f}/{g_val:.0f}"
                        else:
                            wind_str = f"{ws_val:.0f}"
                        dir_str = f" aus {wd_val:.0f}°" if wd_val is not None else ""
                        alt_wind_info += f" | {lv['pressure']}hPa({int(alt)}m){marker}: {wind_str}km/h{dir_str}"
                        # Set ALOFT tags only for in-range (*) levels
                        if in_range:
                            if ws_val > 40:
                                aloft_danger = True
                            elif ws_val > 30:
                                aloft_warn = True
                            if g_val is not None:
                                # T(z) > 40 km/h im Flugbereich = DANGER,
                                # unabhängig vom Modellwind W(z).
                                # Turbulenzrisiko >40 km/h ist ein Sicherheits-
                                # problem auch bei moderatem Grundwind.
                                if g_val > 40:
                                    aloft_gust_danger = True
                                elif g_val > 30:
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
                    # CAPE-DANGER (hart): extreme Instabilitaet oder CAPE + Regen (aktive Ueberentwicklung)
                    # CAPE-WARN (soft): Potenzial vorhanden, aber kein Trigger → conditional
                    if cape > 1500 or "[RAIN-WARN]" in warnings:
                        warnings.append("[CAPE-DANGER]")
                    else:
                        warnings.append("[CAPE-WARN]")
            except Exception:
                pass

            # WMO weather_code 95/96/99 = Gewitter (deterministisches Modellsignal)
            try:
                wcode = data.get("weather_code")
                if isinstance(wcode, (int, float)) and int(wcode) in (95, 96, 99):
                    warnings.append("[THUNDERSTORM]")
            except Exception:
                pass

            # OVERCAST-DANGER: nur wenn Wolkenbasis gefährlich nahe an Flughöhe
            if (cloud_base_raw is not None
                    and isinstance(cloud_base_raw, (int, float))
                    and isinstance(cloud_cover, (int, float))
                    and cloud_cover >= 75
                    and cloud_base_raw < elevation_m + 500):
                warnings.append("[OVERCAST-DANGER]")

            # Thermik-Qualitaets-Tags (Scherung / Zerrissenheit / Boeigkeit).
            # Basis: meteo_research/wind_shear_thermal_quality.md
            # Nur aktiv wenn Thermik existiert — ohne climb_rate sind die
            # Boeen-Risiken bereits durch [GUST-*] und [ALOFT-*] abgedeckt.
            tq_info = ""
            try:
                quality_tags, quality_debug = self._thermal_quality_tags(
                    wind_speed_10m=wind_speed,
                    wind_gusts_10m=wind_gusts,
                    pl_data=pressure_level_data.get(timestamp, {}),
                    elevation_m=elevation_m,
                    thermal_top_m=h_max_h,
                    climb_rate_ms=h_climb,
                    region_id=spot.get("region_id"),
                    altitude_gusts=display_with_gusts,
                )
                for tag in quality_tags:
                    if tag not in warnings:
                        warnings.append(tag)
                tq_str = self._format_tq_ratio(quality_debug.get("tq_ratio"))
                if tq_str:
                    tq_info = f" | {tq_str}"
            except Exception as e:
                logging.warning(
                    "Thermik-Quality-Tag-Berechnung fehlgeschlagen für %s: %s",
                    name, e
                )

            # Thermik-Qualitaets-Zaehler aktualisieren
            if isinstance(h_climb, (int, float)) and h_climb >= config.THERMAL_QUALITY_MIN_CLIMB:
                thermal_hours_total += 1
                tq_tags_this_hour = {t for t in warnings if t.startswith(("[SHEAR-", "[THERMAL-TORN-", "[THERMAL-ROUGH-"))}
                # THERMAL-ROUGH-UNUSABLE und THERMAL-ROUGH-FRAGMENTED blockieren den
                # Produktiv-Zaehler. THERMAL-TORN und SHEAR sind reine Qualitaets-Issues
                # und duerfen die Fliegbarkeit NICHT auf gray kippen.
                rough_unusable_this_hour = (
                    "[THERMAL-ROUGH-UNUSABLE]" in tq_tags_this_hour
                    or "[THERMAL-ROUGH-FRAGMENTED]" in tq_tags_this_hour
                )
                if (h_climb >= config.PRODUCTIVE_CLIMB_MIN
                        and max(low_cl, mid_cl) <= config.PRODUCTIVE_CLOUD_MAX
                        and not rough_unusable_this_hour):
                    productive_thermal_h += 1
                if not tq_tags_this_hour:
                    thermal_clean_h += 1
                else:
                    if "[THERMAL-ROUGH-UNUSABLE]" in tq_tags_this_hour or "[THERMAL-ROUGH-FRAGMENTED]" in tq_tags_this_hour:
                        tq_rough_danger_h += 1
                    elif "[THERMAL-ROUGH-DEGRADED]" in tq_tags_this_hour:
                        tq_rough_warn_h += 1
                    if "[THERMAL-TORN-UNUSABLE]" in tq_tags_this_hour:
                        tq_torn_danger_h += 1
                    elif "[THERMAL-TORN-DEGRADED]" in tq_tags_this_hour:
                        tq_torn_warn_h += 1
                    if "[SHEAR-UNUSABLE]" in tq_tags_this_hour:
                        tq_shear_danger_h += 1
                    elif "[SHEAR-DEGRADED]" in tq_tags_this_hour:
                        tq_shear_warn_h += 1

            warning_str = " " + " ".join(warnings) if warnings else ""

            # Tag-Histogram: zähle alle Warnungen + WIND-WRONG für Tagesprofil
            for w in warnings:
                tag_counts[w] = tag_counts.get(w, 0) + 1
            if not is_ok:
                tag_counts[wind_status] = tag_counts.get(wind_status, 0) + 1

            gust_tags = {"[GUST-WARN]", "[GUST-DANGER]",
                         "[ALOFT-GUST-WARN]", "[ALOFT-GUST-DANGER]"}
            if gust_tags & set(warnings):
                gust_hours.append(hour_str)

            # Klassifiziere saubere vs. gewarnte Stunden (nach allen Warnungen)
            # WICHTIG: Die Thermik-Qualitaets-Tags (SHEAR / THERMAL-TORN / THERMAL-ROUGH)
            # gehoeren hier NICHT rein. Sie betreffen die Fliegbarkeit (kann ich Thermik
            # fliegen?), nicht die Sicherheit (kann ich starten und heil wieder landen?).
            # Eine Stunde mit SHEAR-UNUSABLE + WIND-OK + keine Boeen bleibt sicher fliegbar
            # (Abgleiter), sie ist nur thermisch wertlos. Die LLM-Fliegbarkeits-Phase
            # (flyability.md) interpretiert die Tags und degradiert auf gray/green.
            hard_warnings = {
                "[GUST-DANGER]", "[ALOFT-DANGER]", "[ALOFT-GUST-DANGER]",
                "[RAIN-WARN]", "[CAPE-DANGER]", "[THUNDERSTORM]", "[STRONG-WIND-WARN]",
                "[OVERCAST-DANGER]",
            }
            has_hard_warn = bool(hard_warnings & set(warnings))
            if is_ok and not has_hard_warn:
                clean_hours.append(hour_str)
            elif is_ok and has_hard_warn:
                warned_hours.append(hour_str)

            # Surface gust excess for LLM context
            sfc_excess = ""
            if isinstance(wind_gusts, (int, float)) and isinstance(wind_speed, (int, float)):
                exc = max(0, wind_gusts - wind_speed)
                sfc_excess = f", Exzess +{exc:.0f}km/h"

            lines.append(
                f"{time_str}: Temp {temp}°C | Wind {wind_speed}km/h aus {wind_dir}° (Turbulenzrisiko {wind_gusts}km/h{sfc_excess}) {wind_status}{warning_str} | "
                f"Wolkenbasis {cloud_base} | Bewölkung {cloud_cover}% (tief {low_cl:.0f}%, mittel {mid_cl:.0f}%, hoch {high_cl:.0f}%) | FLUGBEREICH: {elevation_m}–{effective_ceiling}m MSL{alt_wind_info}{thermal_info}{tq_info}"
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
            lines.append(f"⚠ Gewarnete WIND-OK Stunden ({len(warned_hours)}): {', '.join(warned_hours)} (WIND-OK aber WIND/GUST/ALOFT/RAIN/CAPE/THUNDERSTORM/PL-WARN!)")
        if len(clean_hours) >= 3:
            lines.append(f"→ {len(clean_hours)} saubere Stunden: safety_status eher safe oder conditional (Grün/Orange).")
        elif clean_hours:
            lines.append(f"→ Nur {len(clean_hours)} saubere Stunden: Status sollte maximal conditional sein.")
        elif wind_ok_hours and not clean_hours:
            lines.append(f"→ ACHTUNG: Alle {len(wind_ok_hours)} WIND-OK-Stunden haben harte Warnungen (WIND/GUST/ALOFT/RAIN/CAPE/THUNDERSTORM)! Status sollte NOT_SAFE sein!")
        else:
            lines.append(f"→ Kein fliegbares Fenster. Status sollte not_safe sein.")

        # ─── TAGESPROFIL: Ganzheitliche Sicht für LLM-Bewertung ───
        total_actual = len(wind_ok_hours) + len(wind_wrong_hours)
        if total_actual > 0:
            clean_pct = (len(clean_hours) / total_actual) * 100
            lines.append("")
            lines.append("═══ TAGESPROFIL (für ganzheitliche Beurteilung) ═══")
            lines.append(
                f"Flugfenster ausgewertet: {total_actual}h "
                f"(zwischen {config.FLIGHT_HOURS_START:02d}:00 und {config.FLIGHT_HOURS_END:02d}:00)"
            )
            lines.append(
                f"Verhältnis sauber/gesamt: {len(clean_hours)}/{total_actual}h = {clean_pct:.0f}%"
            )
            # Histogramm der Hauptgefahren über den ganzen Tag
            major_tags_order = [
                "[GUST-DANGER]", "[ALOFT-DANGER]", "[ALOFT-GUST-DANGER]",
                "[STRONG-WIND-WARN]", "[RAIN-WARN]", "[CAPE-DANGER]", "[CAPE-WARN]", "[THUNDERSTORM]", "[OVERCAST-DANGER]",
                "[SHEAR-UNUSABLE]", "[THERMAL-TORN-UNUSABLE]", "[THERMAL-ROUGH-UNUSABLE]",
                "[THERMAL-ROUGH-FRAGMENTED]",
                "[GUST-WARN]", "[ALOFT-WARN]", "[ALOFT-GUST-WARN]",
                "[SHEAR-DEGRADED]", "[THERMAL-TORN-DEGRADED]", "[THERMAL-ROUGH-DEGRADED]",
                "[WIND-WRONG]",
            ]
            hist_parts = []
            for t in major_tags_order:
                cnt = tag_counts.get(t, 0)
                if cnt > 0:
                    hist_parts.append(f"{t.strip('[]')} {cnt}h")
            if hist_parts:
                lines.append(f"Hauptgefahren am Tag: {', '.join(hist_parts)}")
            # Verdict-Hinweis bei niedrigem Verhältnis
            if 0 < clean_pct < 35:
                lines.append(
                    f"→ ACHTUNG Verhältnis < 35%: Tag ist überwiegend gefährlich. "
                    f"Auch wenn ein 4h-Fenster existiert, prüfe ob es eingekesselt ist. "
                    f"Status maximal conditional, oft eher not_safe."
                )

        # ─── BÖEN-INFO: Zusammenfassung für LLM-Bewertung ───
        gust_warn_h = tag_counts.get("[GUST-WARN]", 0)
        aloft_gust_warn_h = tag_counts.get("[ALOFT-GUST-WARN]", 0)
        gust_danger_h = tag_counts.get("[GUST-DANGER]", 0)
        aloft_gust_danger_h = tag_counts.get("[ALOFT-GUST-DANGER]", 0)
        max_surface_gust = max(hourly_gusts.values()) if hourly_gusts else 0

        # "Harte Warnungen" = alles was eine Stunde objektiv unfliegbar macht
        hard_warning_tags = [
            "[GUST-DANGER]", "[ALOFT-DANGER]", "[ALOFT-GUST-DANGER]",
            "[WIND-STRONG]", "[RAIN-WARN]", "[CAPE-DANGER]", "[THUNDERSTORM]", "[OVERCAST-DANGER]",
        ]
        hard_warning_hours = sum(tag_counts.get(t, 0) for t in hard_warning_tags)

        # Cache fuer deterministische Zahlen-Injektion in _safety_check_single_spot_day.
        # LLM darf diese NICHT selber schreiben (Halluzinations-Schutz).
        self._ctx_cache_put(self._ctx_gust_cache, f"{name}|{date_str}", {
            "gust_warn_hours": gust_warn_h,
            "aloft_gust_warn_hours": aloft_gust_warn_h,
            "gust_danger_hours": gust_danger_h,
            "aloft_gust_danger_hours": aloft_gust_danger_h,
            "max_surface_gust": max_surface_gust,
            "wind_ok_count": len(wind_ok_hours),
            "wind_wrong_count": len(wind_wrong_hours),
            "clean_hours_count": len(clean_hours),
            "hard_warning_hours": hard_warning_hours,
            "rain_hours": len(rain_hours),
            "rain_hour_list": rain_hours,
        })

        # Rain-Sandwich-Erkennung fuer Prefilter + NIEDERSCHLAG-TREND
        all_hours_sorted = sorted(hourly_gusts.keys()) or sorted(set(wind_ok_hours + wind_wrong_hours))
        rain_pattern = _detect_rain_sandwich(rain_hours, all_hours_sorted)
        self._ctx_gust_cache[f"{name}|{date_str}"]["rain_sandwiched"] = rain_pattern["is_sandwiched"]
        self._ctx_gust_cache[f"{name}|{date_str}"]["max_dry_gap"] = rain_pattern["max_dry_gap"]

        # Cache fuer deterministische Flyability-Override
        # rough_danger_h = THERMAL-ROUGH-UNUSABLE + FRAGMENTED → einziger gray-Trigger.
        # tq_danger_h bleibt Summe aller UNUSABLE/FRAGMENTED fuer Text-Hinweise.
        self._ctx_cache_put(self._ctx_tq_cache, f"{name}|{date_str}", {
            "thermal_hours_total": thermal_hours_total,
            "tq_danger_h": tq_rough_danger_h + tq_torn_danger_h + tq_shear_danger_h,
            "rough_danger_h": tq_rough_danger_h,
            "peak_climb_proxy": peak_climb_proxy,
            "productive_thermal_h": productive_thermal_h,
            "clean_hours_count": len(clean_hours),
        })

        if gust_danger_h > 0 or aloft_gust_danger_h > 0:
            danger_bits = []
            if gust_danger_h > 0:
                danger_bits.append(f"Bodenböen >40 km/h in {gust_danger_h}h")
            if aloft_gust_danger_h > 0:
                danger_bits.append(f"Höhenböen >40 km/h in {aloft_gust_danger_h}h")
            lines.append(
                f"→ BÖEN-INFO: {', '.join(danger_bits)}. "
                f"Prüfe den WIND-TREND: Wenn Böen nachlassen und 4+ saubere Stunden am Rand "
                f"(nicht eingekesselt) bleiben, ist conditional möglich. "
                f"Sonst not_safe. PFLICHT: Böen MIT Zahlen in no_go_reasons oder caution_notes."
            )
        elif gust_warn_h > 0 or aloft_gust_warn_h > 0:
            warn_bits = []
            if gust_warn_h > 0:
                warn_bits.append(f"Bodenböen >30 km/h in {gust_warn_h}h (max ~{int(max_surface_gust)} km/h)")
            if aloft_gust_warn_h > 0:
                warn_bits.append(f"Höhenböen >30 km/h in {aloft_gust_warn_h}h im Flugbereich")
            lines.append(
                f"→ BÖEN-INFO: {', '.join(warn_bits)}. "
                f"Status DARF NICHT 'safe' sein — mindestens conditional. "
                f"PFLICHT: Böen-Hinweis MIT Zahlen in caution_notes nennen."
            )

        # ──��� THERMIK-QUALITÄT: Zusammenfassung für LLM (analog BÖEN-FLOOR) ───
        if thermal_hours_total > 0:
            tq_danger_h = tq_rough_danger_h + tq_torn_danger_h + tq_shear_danger_h
            tq_warn_h = tq_rough_warn_h + tq_torn_warn_h + tq_shear_warn_h
            tq_parts = []
            if tq_rough_danger_h:
                tq_parts.append(f"ROUGH-UNUSABLE {tq_rough_danger_h}h")
            if tq_torn_danger_h:
                tq_parts.append(f"TORN-UNUSABLE {tq_torn_danger_h}h")
            if tq_shear_danger_h:
                tq_parts.append(f"SHEAR-UNUSABLE {tq_shear_danger_h}h")
            if tq_rough_warn_h:
                tq_parts.append(f"ROUGH-DEGRADED {tq_rough_warn_h}h")
            if tq_torn_warn_h:
                tq_parts.append(f"TORN-DEGRADED {tq_torn_warn_h}h")
            if tq_shear_warn_h:
                tq_parts.append(f"SHEAR-DEGRADED {tq_shear_warn_h}h")
            tq_parts.append(f"sauber {thermal_clean_h}h")
            unusable_pct = round(100 * tq_danger_h / thermal_hours_total)
            rough_pct = round(100 * tq_rough_danger_h / thermal_hours_total)
            lines.append(
                f"→ THERMIK-QUALITÄT (NUR Fliegbarkeit/Phase 2, NICHT Sicherheit!): "
                f"{', '.join(tq_parts)} von {thermal_hours_total} Thermik-Stunden. "
                f"ROUGH-UNUSABLE-Anteil: {rough_pct}% ({tq_rough_danger_h}/{thermal_hours_total}h), "
                f"Gesamt-UNUSABLE-Anteil: {unusable_pct}% ({tq_danger_h}/{thermal_hours_total}h). "
                f"Peak-Steigen (Proxy): {peak_climb_proxy:.1f} m/s."
            )
            if tq_rough_danger_h > 0 and rough_pct > 50:
                lines.append(
                    f"  ROUGH-UNUSABLE > 50%: Mechanisch extrem boeig (Klapper-Gefahr im Bart). "
                    f"Falls du green/violet gewählt hast → degradiere zu gray (Abgleiter). "
                    f"Falls bereits gray → bleibt gray. Hat KEINEN Einfluss auf safety_status."
                )
            if (tq_torn_danger_h > 0 or tq_shear_danger_h > 0):
                lines.append(
                    f"  TORN-/SHEAR-UNUSABLE sind reine Qualitaets-Issues (zerrissene/gekippte Thermik). "
                    f"Sie degradieren MAXIMAL violet→green. KEIN gray-Downgrade wegen TORN/SHEAR. "
                    f"Der Tag bleibt Thermikflug-tauglich, Bart-Zentrierung ist nur schwieriger."
                )
        else:
            lines.append(
                "→ THERMIK-QUALITÄT (NUR Fliegbarkeit/Phase 2, NICHT Sicherheit!): "
                "KEINE THERMIK-STUNDEN — Peak-Steigen (Proxy): 0.0 m/s. "
                "Kein nutzbarer Aufwind im gesamten Flugfenster. fly_status = gray (Abgleiter)."
            )

        # ─── PRODUKTIVE-THERMIK: Stunden mit Climb + klarer Sicht ───
        if thermal_hours_total > 0:
            lines.append(
                f"→ PRODUKTIVE-THERMIK: {productive_thermal_h}h "
                f"(Climb ≥{config.PRODUCTIVE_CLIMB_MIN} m/s, Wolken ≤{config.PRODUCTIVE_CLOUD_MAX}%, "
                f"kein ROUGH-UNUSABLE). Min für green-Tag: {config.PRODUCTIVE_HOURS_FOR_GREEN}h. "
                f"HINWEIS: TORN-/SHEAR-UNUSABLE zählen MIT (Bart-Zentrierung schwieriger, aber fliegbar)."
            )

        # Wind-Trend nach dem sauberen Fenster
        trend = _compute_wind_trend(clean_hours, hourly_gusts)
        if trend:
            lines.append(trend)

        # Niederschlag-Trend
        # all_hours_sorted already computed above (rain_pattern section)
        if rain_hours and all_hours_sorted:
            if rain_pattern["is_sandwiched"] and rain_pattern["max_dry_gap"] < 4:
                lines.append(
                    f"NIEDERSCHLAG-TREND: EINGEKESSELT — Trockenes Fenster nur "
                    f"{rain_pattern['max_dry_gap']}h ({rain_pattern['dry_start']}-{rain_pattern['dry_end']}) "
                    f"zwischen Regenperioden. Regen in {', '.join(rain_hours)}. "
                    f"NICHT FLIEGBAR: Zu kurz und zu riskant — Regen kommt zurueck! "
                    f"→ safety_status sollte not_safe sein. primary_no_go = EINGEKESSELT"
                )
            else:
                last_rain = max(rain_hours)
                dry_after = [h for h in all_hours_sorted if h > last_rain]
                if rain_pattern["is_sandwiched"]:
                    lines.append(
                        f"NIEDERSCHLAG-TREND: EINGEKESSELT (knapp) — Trockenes Fenster "
                        f"{rain_pattern['max_dry_gap']}h ({rain_pattern['dry_start']}-{rain_pattern['dry_end']}) "
                        f"zwischen Regenperioden. KRITISCH: Regen kommt zurück! "
                        f"Pilot startet in verschlechternde Bedingungen. "
                        f"→ Maximal conditional, eher not_safe. "
                        f"In no_go_reasons/caution_notes begruenden!"
                    )
                elif len(dry_after) >= 4:
                    lines.append(
                        f"NIEDERSCHLAG-TREND: AUFKLÄRUNG — Regen nur {', '.join(rain_hours)}, "
                        f"ab {dry_after[0]} trocken ({len(dry_after)} trockene Stunden). "
                        f"Regen zieht ab, danach stabil trocken. "
                        f"→ Trockene Stunden normal bewerten, safe_window dort setzen."
                    )
                elif dry_after:
                    lines.append(
                        f"NIEDERSCHLAG-TREND: SPÄTE AUFKLÄRUNG — Regen bis {last_rain}, "
                        f"nur {len(dry_after)} trockene Stunden danach. "
                        f"→ Maximal conditional."
                    )
                else:
                    lines.append(
                        f"NIEDERSCHLAG-TREND: REGEN BIS ABEND — Letzte Regenstunde: {last_rain}. "
                        f"Kein trockenes Fenster. → not_safe."
                    )
        elif rain_hours:
            lines.append(
                f"NIEDERSCHLAG-TREND: GANZTÄGIG — Regen in {len(rain_hours)} Stunden. "
                f"→ not_safe."
            )

        # Boeen-Trend (analog Niederschlag-Trend)
        if gust_hours and all_hours_sorted:
            gust_pattern = _detect_gust_trend(gust_hours, all_hours_sorted)
            gust_trend_text = _format_gust_trend_text(gust_pattern, gust_hours)
            if gust_trend_text:
                lines.append(gust_trend_text)

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
            f"WETTERDATEN FUER REGION: {rname} — TAG: {date_str} ({_weekday_de(date_str)}) (Stand: {updated})",
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
        gust_hours = []        # Stunden mit GUST/ALOFT-GUST WARN/DANGER (fuer BOEEN-TREND)
        tag_counts = {}        # tag_name → count (für Tagesprofil-Histogramm)
        # Thermik-Qualitaets-Zaehler
        thermal_hours_total = 0
        thermal_clean_h = 0
        tq_rough_danger_h = 0
        tq_rough_warn_h = 0
        tq_torn_danger_h = 0
        tq_torn_warn_h = 0
        tq_shear_danger_h = 0
        tq_shear_warn_h = 0
        peak_climb_proxy = 0.0
        productive_thermal_h = 0   # Stunden mit climb>=0.7 + max(low,mid)<=70% + kein UNUSABLE

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
            h_climb = None
            h_max_h = None
            try:
                therm = self._calculate_thermal_raw(
                    data, pressure_level_data.get(timestamp, {}),
                    elev_ref, timestamp, dummy_spot,
                    region_id=rid,
                )
                if therm and "error" not in therm:
                    h_climb = therm["climb_rate"]
                    if isinstance(h_climb, (int, float)) and h_climb > peak_climb_proxy:
                        peak_climb_proxy = h_climb
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
            low_cl = float(data.get("cloud_cover_low") or 0)
            mid_cl = float(data.get("cloud_cover_mid") or 0)
            high_cl = float(data.get("cloud_cover_high") or 0)

            # Single-Anchor mit Multi-Spot-aggregiertem Bodenexzess
            # (Apr 2026 Refactor — siehe MEMORY.md):
            # Spot-Höhen sind keine Höhenmessungen der freien Atmosphäre.
            # Stattdessen aggregieren wir die 10m-Bodenexzesse aller Spots
            # in der Region via Median (ausreißer-immun) zu einem robusten
            # Region-Exzess. Das Höhenprofil entsteht via Gauss-Decay um
            # diesen einzelnen Anker.
            pl_data = pressure_level_data.get(timestamp, {})
            anchors = []
            if isinstance(wind_gusts_surface, (int, float)) and isinstance(wind_speed_surface, (int, float)):
                ws_f = float(wind_speed_surface)
                ref_excess = max(0.0, float(wind_gusts_surface) - ws_f)
                excesses = [ref_excess]
                # Spot-Bodenexzesse der Region einsammeln
                if region_polygon and region_spots:
                    for spot in region_spots:
                        spot_data = self.weather_data.get(spot["name"])
                        if not spot_data:
                            continue
                        hd = spot_data.get("hourly_data", {}).get(timestamp)
                        if not hd:
                            continue
                        spot_ws = hd.get("wind_speed_10m")
                        spot_gust = hd.get("wind_gusts_10m")
                        if spot_ws is None or spot_gust is None:
                            continue
                        excesses.append(max(0.0, float(spot_gust) - float(spot_ws)))
                agg_excess = aggregate_spot_excess(excesses)
                anchors = [{
                    "elevation_m": elev_ref,
                    "gust_kmh": ws_f + agg_excess,
                    "wind_speed_kmh": ws_f,
                    "source": f"Ref-{rname}+{len(excesses)}sp",
                }]

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
            display_with_gusts = None

            if pl_data:
                # Display levels mit 3 Klassen (siehe _build_single_spot_context):
                #   * = Flugbereich, ~ = Buffer (thermik+1500m), kein Marker = 850/700 Föhn-Anker
                buffer_top = effective_ceiling + 500
                display_levels_set = set()
                for level in config.PRESSURE_LEVELS:
                    h_val = pl_data.get(f"geopotential_height_{level}hPa")
                    if h_val is None:
                        continue
                    if elev_ref <= h_val <= buffer_top:
                        display_levels_set.add(level)
                display_levels_set.add(850)
                display_levels_set.add(700)

                display_levels = []
                for level in sorted(display_levels_set, reverse=True):
                    h_val = pl_data.get(f"geopotential_height_{level}hPa")
                    ws = pl_data.get(f"wind_speed_{level}hPa")
                    wd = pl_data.get(f"wind_direction_{level}hPa")
                    if h_val is not None and ws is not None:
                        display_levels.append({"pressure": level, "altitude": h_val,
                                               "wind_speed": ws, "wind_direction": wd})

                if display_levels:
                    if anchors:
                        display_with_gusts = estimate_altitude_gusts_multi_anchor(
                            anchors=anchors,
                            pressure_levels_data=display_levels,
                            elevation_ref=elev_ref,
                            boundary_layer_height=data.get("boundary_layer_height"),
                            region_id=rid,
                        )
                        # OI-Korrektur (spiegelt das Chart in web.format_altitude_wind_for_charts):
                        # Region-Klassifizierer und Frontend-Meteogramm sehen damit identische Werte.
                        # Ohne diesen Schritt würde der Klassifizierer Roh-Werte aus der Multi-Anchor-
                        # Extrapolation sehen, das Chart dagegen die OI-geglätteten — Inkonsistenz.
                        display_with_gusts = apply_oi_gust_correction(
                            pressure_levels=display_with_gusts,
                            anchors=anchors,
                            elevation_ref=elev_ref,
                            boundary_layer_height=data.get("boundary_layer_height"),
                            region_id=rid,
                        )
                    else:
                        display_with_gusts = estimate_altitude_gusts(
                            wind_speed_10m=wind_speed_surface,
                            wind_gusts_10m=wind_gusts_surface,
                            pressure_levels_data=display_levels,
                            elevation_m=elev_ref,
                            boundary_layer_height=data.get("boundary_layer_height"),
                        )
                    for lv in display_with_gusts:
                        alt = lv["altitude"]
                        in_range = elev_ref <= alt <= effective_ceiling
                        in_buffer = effective_ceiling < alt <= buffer_top
                        if in_range:
                            marker = "*"
                        elif in_buffer:
                            marker = "~"
                        else:
                            marker = ""
                        ws_val = lv["wind_speed"]
                        g_val = lv.get("wind_gusts")
                        wd_val = lv.get("wind_direction")
                        if g_val is not None and g_val > ws_val + 2:
                            wind_str = f"{ws_val:.0f}/{g_val:.0f}"
                        else:
                            wind_str = f"{ws_val:.0f}"
                        dir_str = f" aus {wd_val:.0f}°" if wd_val is not None else ""
                        alt_wind_info += f" | {lv['pressure']}hPa({int(alt)}m){marker}: {wind_str}km/h{dir_str}"
                        if in_range:
                            if ws_val > 40:
                                aloft_danger = True
                            elif ws_val > 30:
                                aloft_warn = True
                            if g_val is not None:
                                # T(z) > 40 km/h im Flugbereich = DANGER,
                                # unabhängig vom Modellwind W(z).
                                # Turbulenzrisiko >40 km/h ist ein Sicherheits-
                                # problem auch bei moderatem Grundwind.
                                if g_val > 40:
                                    aloft_gust_danger = True
                                elif g_val > 30:
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
                    # CAPE-DANGER (hart): extreme Instabilitaet oder CAPE + Regen (aktive Ueberentwicklung)
                    # CAPE-WARN (soft): Potenzial vorhanden, aber kein Trigger → conditional
                    if cape > 1500 or "[RAIN-WARN]" in warnings:
                        warnings.append("[CAPE-DANGER]")
                    else:
                        warnings.append("[CAPE-WARN]")
            except Exception:
                pass

            # WMO weather_code 95/96/99 = Gewitter (deterministisches Modellsignal)
            try:
                wcode = data.get("weather_code")
                if isinstance(wcode, (int, float)) and int(wcode) in (95, 96, 99):
                    warnings.append("[THUNDERSTORM]")
            except Exception:
                pass

            # OVERCAST-DANGER: nur wenn Wolkenbasis gefährlich nahe an Flughöhe
            if (cloud_base_raw is not None
                    and isinstance(cloud_base_raw, (int, float))
                    and isinstance(cloud_cover, (int, float))
                    and cloud_cover >= 75
                    and cloud_base_raw < elev_ref + 500):
                warnings.append("[OVERCAST-DANGER]")

            # Thermik-Qualitaets-Tags (Scherung / Zerrissenheit / Boeigkeit)
            # Analog zum Spot-Pfad — fehlte bisher im Region-Pfad.
            # WICHTIG: Immer echten 10m-Bodenwind verwenden, NICHT den
            # effektiven wind_speed (kann Hoehenwind enthalten).
            # Scherung = Windaenderung mit Hoehe, braucht echten Surface-Anker.
            tq_info = ""
            try:
                quality_tags, quality_debug = self._thermal_quality_tags(
                    wind_speed_10m=wind_speed_surface,
                    wind_gusts_10m=wind_gusts_surface,
                    pl_data=pl_data,
                    elevation_m=elev_ref,
                    thermal_top_m=h_max_h,
                    climb_rate_ms=h_climb,
                    region_id=rid,
                    altitude_gusts=display_with_gusts,
                )
                for tag in quality_tags:
                    if tag not in warnings:
                        warnings.append(tag)
                tq_str = self._format_tq_ratio(quality_debug.get("tq_ratio"))
                if tq_str:
                    tq_info = f" | {tq_str}"
            except Exception as e:
                logging.warning(
                    "Thermik-Quality-Tag-Berechnung fehlgeschlagen für Region %s: %s",
                    rname, e
                )

            # Thermik-Qualitaets-Zaehler aktualisieren
            if isinstance(h_climb, (int, float)) and h_climb >= config.THERMAL_QUALITY_MIN_CLIMB:
                thermal_hours_total += 1
                tq_tags_this_hour = {t for t in warnings if t.startswith(("[SHEAR-", "[THERMAL-TORN-", "[THERMAL-ROUGH-"))}
                # THERMAL-ROUGH-UNUSABLE und THERMAL-ROUGH-FRAGMENTED blockieren den
                # Produktiv-Zaehler. THERMAL-TORN und SHEAR sind reine Qualitaets-Issues
                # und duerfen die Fliegbarkeit NICHT auf gray kippen.
                rough_unusable_this_hour = (
                    "[THERMAL-ROUGH-UNUSABLE]" in tq_tags_this_hour
                    or "[THERMAL-ROUGH-FRAGMENTED]" in tq_tags_this_hour
                )
                if (h_climb >= config.PRODUCTIVE_CLIMB_MIN
                        and max(low_cl, mid_cl) <= config.PRODUCTIVE_CLOUD_MAX
                        and not rough_unusable_this_hour):
                    productive_thermal_h += 1
                if not tq_tags_this_hour:
                    thermal_clean_h += 1
                else:
                    if "[THERMAL-ROUGH-UNUSABLE]" in tq_tags_this_hour or "[THERMAL-ROUGH-FRAGMENTED]" in tq_tags_this_hour:
                        tq_rough_danger_h += 1
                    elif "[THERMAL-ROUGH-DEGRADED]" in tq_tags_this_hour:
                        tq_rough_warn_h += 1
                    if "[THERMAL-TORN-UNUSABLE]" in tq_tags_this_hour:
                        tq_torn_danger_h += 1
                    elif "[THERMAL-TORN-DEGRADED]" in tq_tags_this_hour:
                        tq_torn_warn_h += 1
                    if "[SHEAR-UNUSABLE]" in tq_tags_this_hour:
                        tq_shear_danger_h += 1
                    elif "[SHEAR-DEGRADED]" in tq_tags_this_hour:
                        tq_shear_warn_h += 1

            warning_str = " " + " ".join(warnings) if warnings else ""

            # Tag-Histogram für Tagesprofil
            for w in warnings:
                tag_counts[w] = tag_counts.get(w, 0) + 1
            if wind_status == "[WIND-STRONG]":
                tag_counts["[WIND-STRONG]"] = tag_counts.get("[WIND-STRONG]", 0) + 1
            elif wind_status == "[WIND-MODERATE]":
                tag_counts["[WIND-MODERATE]"] = tag_counts.get("[WIND-MODERATE]", 0) + 1

            gust_tags = {"[GUST-WARN]", "[GUST-DANGER]",
                         "[ALOFT-GUST-WARN]", "[ALOFT-GUST-DANGER]"}
            if gust_tags & set(warnings):
                gust_hours.append(hour_str)

            # Klassifiziere saubere vs. gewarnte Stunden
            hard_warnings = {"[GUST-DANGER]", "[ALOFT-DANGER]", "[ALOFT-GUST-DANGER]", "[RAIN-WARN]", "[CAPE-DANGER]", "[THUNDERSTORM]", "[WIND-STRONG]", "[OVERCAST-DANGER]"}
            has_hard_warn = bool(hard_warnings & set(warnings)) or wind_status == "[WIND-STRONG]"
            if not has_hard_warn:
                clean_hours.append(hour_str)
            else:
                warned_hours.append(hour_str)

            # Wind-Werte formatieren (koennen Floats sein nach Interpolation)
            ws_fmt = f"{wind_speed:.0f}" if isinstance(wind_speed, float) else str(wind_speed)
            wd_fmt = f"{wind_dir:.0f}" if isinstance(wind_dir, float) else str(wind_dir)
            wg_fmt = f"{wind_gusts:.0f}" if isinstance(wind_gusts, float) else str(wind_gusts)

            # Surface gust excess for LLM context
            sfc_excess = ""
            if isinstance(wind_gusts, (int, float)) and isinstance(wind_speed, (int, float)):
                exc = max(0, wind_gusts - wind_speed)
                sfc_excess = f", Exzess +{exc:.0f}km/h"

            lines.append(
                f"{time_str}: Temp {temp}°C | Wind {ws_fmt}km/h aus {wd_fmt}° (Turbulenzrisiko {wg_fmt}km/h{sfc_excess}) {wind_status}{ref_wind_info}{warning_str} | "
                f"Wolkenbasis {cloud_base} | Bewoelkung {cloud_cover}% (tief {low_cl:.0f}%, mittel {mid_cl:.0f}%, hoch {high_cl:.0f}%) | FLUGBEREICH: {elev_ref}–{effective_ceiling}m MSL{alt_wind_info}{thermal_info}{tq_info}"
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

        # Cache fuer deterministische Flyability-Override
        # rough_danger_h = THERMAL-ROUGH-UNUSABLE + FRAGMENTED → einziger gray-Trigger.
        # tq_danger_h bleibt Summe aller UNUSABLE/FRAGMENTED fuer Text-Hinweise.
        # Rain-Sandwich-Erkennung fuer Region-Override + NIEDERSCHLAG-TREND
        all_hours_sorted_region = sorted(hourly_gusts.keys()) or sorted(set(calm_hours + moderate_hours + strong_hours))
        rain_pattern = _detect_rain_sandwich(rain_hours, all_hours_sorted_region)

        self._ctx_cache_put(self._ctx_tq_cache, f"{rname}|{date_str}", {
            "thermal_hours_total": thermal_hours_total,
            "tq_danger_h": tq_rough_danger_h + tq_torn_danger_h + tq_shear_danger_h,
            "rough_danger_h": tq_rough_danger_h,
            "peak_climb_proxy": peak_climb_proxy,
            "productive_thermal_h": productive_thermal_h,
            "clean_hours_count": len(clean_hours),
            "rain_sandwiched": rain_pattern["is_sandwiched"],
            "max_dry_gap": rain_pattern["max_dry_gap"],
            "rain_cnt": len(rain_hours),
        })

        # ─── TAGESPROFIL: Ganzheitliche Sicht für LLM-Bewertung ───
        total_actual = len(calm_hours) + len(moderate_hours) + len(strong_hours)
        if total_actual > 0:
            clean_pct = (len(clean_hours) / total_actual) * 100
            lines.append("")
            lines.append("═══ TAGESPROFIL (für ganzheitliche Beurteilung) ═══")
            lines.append(
                f"Flugfenster ausgewertet: {total_actual}h "
                f"(zwischen {config.FLIGHT_HOURS_START:02d}:00 und {config.FLIGHT_HOURS_END:02d}:00)"
            )
            lines.append(
                f"Verhaeltnis sauber/gesamt: {len(clean_hours)}/{total_actual}h = {clean_pct:.0f}%"
            )
            major_tags_order = [
                "[GUST-DANGER]", "[ALOFT-DANGER]", "[ALOFT-GUST-DANGER]",
                "[WIND-STRONG]", "[RAIN-WARN]", "[CAPE-DANGER]", "[CAPE-WARN]", "[THUNDERSTORM]", "[OVERCAST-DANGER]",
                "[SHEAR-UNUSABLE]", "[THERMAL-TORN-UNUSABLE]", "[THERMAL-ROUGH-UNUSABLE]",
                "[THERMAL-ROUGH-FRAGMENTED]",
                "[GUST-WARN]", "[ALOFT-WARN]", "[ALOFT-GUST-WARN]",
                "[SHEAR-DEGRADED]", "[THERMAL-TORN-DEGRADED]", "[THERMAL-ROUGH-DEGRADED]",
                "[WIND-MODERATE]",
            ]
            hist_parts = []
            for t in major_tags_order:
                cnt = tag_counts.get(t, 0)
                if cnt > 0:
                    hist_parts.append(f"{t.strip('[]')} {cnt}h")
            if hist_parts:
                lines.append(f"Hauptgefahren am Tag: {', '.join(hist_parts)}")
            if 0 < clean_pct < 35:
                lines.append(
                    f"→ ACHTUNG Verhaeltnis < 35%: Tag ist ueberwiegend gefaehrlich. "
                    f"Auch wenn ein 4h-Fenster existiert, pruefe ob es eingekesselt ist. "
                    f"Status maximal conditional, oft eher not_safe."
                )

        # ─── THERMIK-QUALITÄT: Zusammenfassung für LLM (analog BÖEN-FLOOR) ───
        if thermal_hours_total > 0:
            tq_danger_h = tq_rough_danger_h + tq_torn_danger_h + tq_shear_danger_h
            tq_warn_h = tq_rough_warn_h + tq_torn_warn_h + tq_shear_warn_h
            tq_parts = []
            if tq_rough_danger_h:
                tq_parts.append(f"ROUGH-UNUSABLE {tq_rough_danger_h}h")
            if tq_torn_danger_h:
                tq_parts.append(f"TORN-UNUSABLE {tq_torn_danger_h}h")
            if tq_shear_danger_h:
                tq_parts.append(f"SHEAR-UNUSABLE {tq_shear_danger_h}h")
            if tq_rough_warn_h:
                tq_parts.append(f"ROUGH-DEGRADED {tq_rough_warn_h}h")
            if tq_torn_warn_h:
                tq_parts.append(f"TORN-DEGRADED {tq_torn_warn_h}h")
            if tq_shear_warn_h:
                tq_parts.append(f"SHEAR-DEGRADED {tq_shear_warn_h}h")
            tq_parts.append(f"sauber {thermal_clean_h}h")
            unusable_pct = round(100 * tq_danger_h / thermal_hours_total)
            rough_pct = round(100 * tq_rough_danger_h / thermal_hours_total)
            lines.append(
                f"→ THERMIK-QUALITÄT (NUR Fliegbarkeit/Phase 2, NICHT Sicherheit!): "
                f"{', '.join(tq_parts)} von {thermal_hours_total} Thermik-Stunden. "
                f"ROUGH-UNUSABLE-Anteil: {rough_pct}% ({tq_rough_danger_h}/{thermal_hours_total}h), "
                f"Gesamt-UNUSABLE-Anteil: {unusable_pct}% ({tq_danger_h}/{thermal_hours_total}h). "
                f"Peak-Steigen (Proxy): {peak_climb_proxy:.1f} m/s."
            )
            if tq_rough_danger_h > 0 and rough_pct > 50:
                lines.append(
                    f"  ROUGH-UNUSABLE > 50%: Mechanisch extrem boeig (Klapper-Gefahr im Bart). "
                    f"Falls du green/violet gewählt hast → degradiere zu gray (Abgleiter). "
                    f"Falls bereits gray → bleibt gray. Hat KEINEN Einfluss auf safety_status."
                )
            if (tq_torn_danger_h > 0 or tq_shear_danger_h > 0):
                lines.append(
                    f"  TORN-/SHEAR-UNUSABLE sind reine Qualitaets-Issues (zerrissene/gekippte Thermik). "
                    f"Sie degradieren MAXIMAL violet→green. KEIN gray-Downgrade wegen TORN/SHEAR. "
                    f"Der Tag bleibt Thermikflug-tauglich, Bart-Zentrierung ist nur schwieriger."
                )
        else:
            lines.append(
                "→ THERMIK-QUALITÄT (NUR Fliegbarkeit/Phase 2, NICHT Sicherheit!): "
                "KEINE THERMIK-STUNDEN — Peak-Steigen (Proxy): 0.0 m/s. "
                "Kein nutzbarer Aufwind im gesamten Flugfenster. fly_status = gray (Abgleiter)."
            )

        # ─── PRODUKTIVE-THERMIK: Stunden mit Climb + klarer Sicht ───
        if thermal_hours_total > 0:
            lines.append(
                f"→ PRODUKTIVE-THERMIK: {productive_thermal_h}h "
                f"(Climb ≥{config.PRODUCTIVE_CLIMB_MIN} m/s, Wolken ≤{config.PRODUCTIVE_CLOUD_MAX}%, "
                f"kein ROUGH-UNUSABLE). Min für green-Tag: {config.PRODUCTIVE_HOURS_FOR_GREEN}h. "
                f"HINWEIS: TORN-/SHEAR-UNUSABLE zählen MIT (Bart-Zentrierung schwieriger, aber fliegbar)."
            )

        # Wind-Trend nach dem sauberen Fenster
        trend = _compute_wind_trend(clean_hours, hourly_gusts)
        if trend:
            lines.append(trend)

        # Niederschlag-Trend (all_hours_sorted_region bereits oben berechnet)
        if rain_hours and all_hours_sorted_region:
            if rain_pattern["is_sandwiched"] and rain_pattern["max_dry_gap"] < 4:
                lines.append(
                    f"NIEDERSCHLAG-TREND: EINGEKESSELT — Trockenes Fenster nur "
                    f"{rain_pattern['max_dry_gap']}h ({rain_pattern['dry_start']}-{rain_pattern['dry_end']}) "
                    f"zwischen Regenperioden. Regen in {', '.join(rain_hours)}. "
                    f"NICHT FLIEGBAR: Zu kurz und zu riskant — Regen kommt zurueck! "
                    f"→ safety_status sollte not_safe sein. primary_no_go = EINGEKESSELT"
                )
            else:
                last_rain = max(rain_hours)
                dry_after = [h for h in all_hours_sorted_region if h > last_rain]
                if rain_pattern["is_sandwiched"]:
                    lines.append(
                        f"NIEDERSCHLAG-TREND: EINGEKESSELT (knapp) — Trockenes Fenster "
                        f"{rain_pattern['max_dry_gap']}h ({rain_pattern['dry_start']}-{rain_pattern['dry_end']}) "
                        f"zwischen Regenperioden. KRITISCH: Regen kommt zurueck! "
                        f"Pilot startet in verschlechternde Bedingungen. "
                        f"→ Maximal conditional, eher not_safe. "
                        f"In no_go_reasons/caution_notes begruenden!"
                    )
                elif len(dry_after) >= 4:
                    lines.append(
                        f"NIEDERSCHLAG-TREND: AUFKLAERUNG — Regen nur {', '.join(rain_hours)}, "
                        f"ab {dry_after[0]} trocken ({len(dry_after)} trockene Stunden). "
                        f"Regen zieht ab, danach stabil trocken. "
                        f"→ Trockene Stunden normal bewerten, safe_window dort setzen."
                    )
                elif dry_after:
                    lines.append(
                        f"NIEDERSCHLAG-TREND: SPAETE AUFKLAERUNG — Regen bis {last_rain}, "
                        f"nur {len(dry_after)} trockene Stunden danach. "
                        f"→ Maximal conditional."
                    )
                else:
                    lines.append(
                        f"NIEDERSCHLAG-TREND: REGEN BIS ABEND — Letzte Regenstunde: {last_rain}. "
                        f"Kein trockenes Fenster. → not_safe."
                    )
        elif rain_hours:
            lines.append(
                f"NIEDERSCHLAG-TREND: GANZTAEGIG — Regen in {len(rain_hours)} Stunden. "
                f"→ not_safe."
            )

        # Boeen-Trend (analog Niederschlag-Trend)
        if gust_hours and all_hours_sorted_region:
            gust_pattern = _detect_gust_trend(gust_hours, all_hours_sorted_region)
            gust_trend_text = _format_gust_trend_text(gust_pattern, gust_hours)
            if gust_trend_text:
                lines.append(gust_trend_text)

        # Foehn: regionsspezifisch (Süd/Nord/Beide)
        krit_foehn = region.get("kritischer_foehn", "Beide")
        lines.append("")
        lines.append(self._format_foehn_info(date_str=date_str, kritischer_foehn=krit_foehn))

        return "\n".join(lines)

