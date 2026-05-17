"""
Gleitcast Engine — Mixin: WeatherContextMixin.

Ausgeschnitten aus chat_engine.py (Monolith-Split). Methoden-Signaturen
unveraendert, Klasse wird via Mehrfachvererbung in GleitcastEngine eingebunden.
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
    get_terrain_zone, compute_daily_thermals, min_band_depth,
)
from gust_calculator import (
    estimate_altitude_gusts, collect_gust_anchors,
    aggregate_spot_excess, get_L_up,
    interpolate_gust_from_anchors,
)
from station_observations import StationManager
from source_area import (
    get_reference_points, _load_regions, find_region_for_point,
    get_all_regions,
)
from prompts import (
    SYSTEM_PROMPT,
    CAPABILITIES_GUIDE, FOEHN_CHAT_KNOWLEDGE,
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
    _TAG_NATURAL, _TAG_NATURAL_MAP, _TAG_SANITIZE_RE,
    _sanitize_llm_text, _sanitize_llm_result,
    _LABEL_KEYS_NO_GO, _LABEL_KEYS_CONDITIONAL,
    _LABEL_KEYS_REDUCER, _LABEL_KEYS_BOOSTER,
    _NO_GO_RANK, _CONDITIONAL_RANK,
    _KEYWORD_TO_KEY_NO_GO, _KEYWORD_TO_KEY_CAUTION,
    _pick_key_from_list, _validate_key, _derive_primary_labels,
    COMPASS_POINTS, _compute_wind_trend, _detect_rain_sandwich,
    _detect_gust_trend, _format_gust_trend_text,
    _detect_aloft_trend, _format_aloft_trend_text,
    _interpolate_wind_at_altitude,
)

logger = logging.getLogger(__name__)


def _classify_cloud_structure(avg_low: float, avg_mid: float, avg_high: float) -> str:
    """Klassifiziert die Bewoelkungsstruktur fuer das Quality-Rating.

    Quelle: meteo_research/cloud_cover_thermal_impact.md Sektion 6:
    Cirrus (>6000m, Transmissivitaet 70-85%) ist thermisch irrelevant —
    nur tief+mittel zaehlen. Massgebliche Metrik: max(tief, mittel).

    Kategorien (RATING_CONCEPT v1.6):
      - cu_clean_top      : tief 12-50% Cu-Marker, mittel <30% → BONUS-Tag,
                            hohe Cirrus-Bewoelkung egal (wird ignoriert)
      - blue              : tief+mittel <15% (klarer Himmel ohne Cu-Marker)
      - cirrus_overcast   : tief+mittel <30%, hoch >70% (kein Cu unten, aber
                            Cirrus dominiert oben → Thermik normal)
      - overdevelopment   : tief+mittel kombiniert >70% (Spread)
      - overcast          : tief ODER mittel >80% (massive Daempfung)
      - mixed             : alles andere
    """
    low_plus_mid = avg_low + avg_mid
    if avg_low >= 80 or avg_mid >= 80:
        return "overcast"
    if low_plus_mid >= 70:
        return "overdevelopment"
    # cu_clean_top zuerst pruefen (hat Vorrang vor cirrus_overcast wenn Cu da):
    # Hohe Cirrus-Bewoelkung ist egal — solange tief Cu + mittel klar ist, ist es Bonus.
    if 12 <= avg_low <= 50 and avg_mid < 30:
        return "cu_clean_top"
    if low_plus_mid < 30 and avg_high >= 70:
        return "cirrus_overcast"
    if low_plus_mid < 15:
        return "blue"
    return "mixed"


def _median(values: list) -> float:
    if not values:
        return 0.0
    vs = sorted(values)
    n = len(vs)
    if n % 2 == 1:
        return float(vs[n // 2])
    return (vs[n // 2 - 1] + vs[n // 2]) / 2.0


def _compute_sustained_peak(hourly_climbs: list, window: int = 2) -> float:
    """Sustained Peak = max climb that lasts ≥ `window` consecutive hours.

    Definiert als: max ueber alle Stunden des Minimums der nachfolgenden
    `window` Stunden. Z.B. window=2 → max(min(h, h+1)) → der hoechste Wert,
    der mindestens 2 Stunden gehalten wird. Verhindert dass Einzel-Spikes
    als "Peak" zaehlen.

    RATING_CONCEPT v1.5: Quality-Matrix nutzt sustained_peak statt
    peak_climb_proxy (Einzelhoechstwert), weil die LLM sonst Spikes als
    Tageskennzahl interpretiert.
    """
    if not hourly_climbs or window < 1:
        return 0.0
    if len(hourly_climbs) < window:
        return float(min(hourly_climbs))
    best = 0.0
    for i in range(len(hourly_climbs) - window + 1):
        seg_min = min(hourly_climbs[i:i + window])
        if seg_min > best:
            best = seg_min
    return round(best, 2)


def _angular_diff(a: float, b: float) -> float:
    """Kuerzester Winkel zwischen zwei Richtungen in Grad (0-180).
    Zirkulaere Differenz: 350° zu 10° = 20°, nicht 340°.
    """
    d = abs(float(a) - float(b)) % 360.0
    return d if d <= 180.0 else 360.0 - d


def _list_consecutive_runs(hour_strs: list[str]) -> list[tuple[int, int]]:
    """Findet ALLE Bloecke zusammenhaengender Stunden.
    Input: ['10:00','11:00','13:00','14:00','15:00'] → [(10, 11), (13, 15)].
    Return: Liste von (start_hour, end_hour) Tupeln (beide inklusiv).
    """
    if not hour_strs:
        return []
    try:
        hours = sorted(set(int(h.split(":")[0]) for h in hour_strs))
    except (ValueError, IndexError):
        return []
    runs: list[tuple[int, int]] = []
    run_start = hours[0]
    prev = hours[0]
    for h in hours[1:]:
        if h - prev == 1:
            prev = h
        else:
            runs.append((run_start, prev))
            run_start = h
            prev = h
    runs.append((run_start, prev))
    return runs


def _longest_consecutive_run(hour_strs: list[str]) -> int:
    """Laenge des laengsten Blocks zusammenhaengender Stunden (in h).
    Input: ['10:00','11:00','13:00','14:00','15:00'] → 3 (13-15).
    """
    runs = _list_consecutive_runs(hour_strs)
    if not runs:
        return 0
    return max(end - start + 1 for start, end in runs)


def _determine_active_window_start(
    clean_hours: list[str],
    min_hours: int,
) -> int | None:
    """Erste Stunde, ab der ein Start-Fenster >= min_hours beginnt.

    "Sauber" = WIND-OK + ohne DANGER-Tag (vom Caller bereits klassifiziert).
    Returns: int hour (0-23) der Run-Startstunde, oder None falls kein
    qualifizierendes Fenster existiert.

    Beispiel:
      clean_hours=['10:00','12:00','13:00','14:00'], min_hours=3
      → Erster qualifizierender Run ist 12-14 (3h) → return 12
    """
    runs = _list_consecutive_runs(clean_hours)
    for start, end in runs:
        if (end - start + 1) >= min_hours:
            return start
    return None


def _format_clean_windows(hour_strs: list[str]) -> str:
    """Formatiert alle sauberen Fenster als Lesbare Liste.
    Input: ['10:00','11:00','13:00','14:00','15:00']
    Output: '10:00-12:00 (2h), 13:00-16:00 (3h)'  (End-Stunde exklusiv dargestellt = Stunden-Anzahl)
    """
    runs = _list_consecutive_runs(hour_strs)
    if not runs:
        return "KEINE"
    parts = []
    for start, end in runs:
        length = end - start + 1
        # Ende als "naechste Stunde" fuer intuitive Lesbarkeit (14-16 = 2h Fenster)
        parts.append(f"{start:02d}:00-{end + 1:02d}:00 ({length}h)")
    return ", ".join(parts)


def _max_wind_direction_swing(
    hourly_wind_dirs: dict,
    window_hours: int | None = None,
) -> tuple[float, str, str, int]:
    """Groesster Richtungsdreher innerhalb eines beliebigen Fensters von bis zu
    ``window_hours`` Stunden. Erfasst sowohl abrupte 1h-Spruenge als auch
    langsames Drehen ueber mehrere Stunden (z.B. 120° ueber 3h, wo keine einzelne
    Stunde alleine die Schwelle reisst — der Wind ist trotzdem unbestaendig).

    Returns (max_swing_deg, start_hour_str, end_hour_str, span_hours).
    Bei span_hours == 1 ist es ein klassischer Stunde-zu-Stunde-Dreher.
    """
    if not hourly_wind_dirs:
        return (0.0, "", "", 0)
    if window_hours is None:
        try:
            window_hours = int(getattr(config, "WIND_DIRECTION_SWING_WINDOW_H", 3))
        except Exception:
            window_hours = 3
    window_hours = max(1, window_hours)
    try:
        items = sorted(
            ((int(k.split(":")[0]), k, v) for k, v in hourly_wind_dirs.items() if isinstance(v, (int, float))),
            key=lambda x: x[0],
        )
    except (ValueError, IndexError):
        return (0.0, "", "", 0)
    max_swing = 0.0
    start_hour = ""
    end_hour = ""
    span = 0
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            h_diff = items[j][0] - items[i][0]
            if h_diff <= 0:
                continue
            if h_diff > window_hours:
                break
            swing = _angular_diff(items[i][2], items[j][2])
            if swing > max_swing:
                max_swing = swing
                start_hour = items[i][1]
                end_hour = items[j][1]
                span = h_diff
    return (max_swing, start_hour, end_hour, span)


def _format_region_context_block(region_result: dict, spot_region: dict) -> str:
    """Formatiert ein Region-Analyse-Ergebnis als kompakten Kontext-Block fuer den
    Spot-Prompt (Teil 4 Streckenflug). Bei fehlendem Ergebnis wird ein expliziter
    "nicht verfuegbar"-Hinweis erzeugt, damit das LLM erkennt, dass es die
    Streckenflug-Bewertung nur auf Spot-Daten stuetzen muss.
    """
    header = "### REGION-KONTEXT (bereits analysiert) ###"
    region_name = (spot_region or {}).get("region") or (spot_region or {}).get("id") or "unbekannte Region"
    if not region_result or not isinstance(region_result, dict):
        return (
            f"{header}\n"
            f"Region-Kontext: nicht verfuegbar (Region: {region_name}).\n"
            f"→ Bewerte Streckenflug NUR anhand der Spot-Daten. "
            f"streckenflug.tier max 'moderat', region_context_available=false, "
            f"summary erwaehnt explizit: 'Region-Kontext fehlt — reine Spot-Einschaetzung.'"
        )

    safety = region_result.get("safety") if isinstance(region_result.get("safety"), dict) else {}
    fly = region_result.get("flyability") if isinstance(region_result.get("flyability"), dict) else {}

    def _g(key, default=None):
        """Bevorzugt nested safety/flyability, faellt zurueck auf flat."""
        if key in safety:
            return safety.get(key, default)
        if key in fly:
            return fly.get(key, default)
        return region_result.get(key, default)

    ss = _g("safety_status", "error")

    parts = [
        header,
        f"Region: {region_result.get('region_name') or region_result.get('region') or region_name}",
        f"Safety-Status: {ss} | Safe-Window: {_g('safe_window', '?')}",
        (
            f"Wind-Stunden (Region-weit): CALM={_g('wind_calm_count', 0)}h, "
            f"MODERATE={_g('wind_moderate_count', 0)}h, "
            f"STRONG={_g('wind_strong_count', 0)}h"
        ),
        f"Foehn-Risiko: {_g('foehn_risk', 'none')}",
    ]
    if _g("wind_summary"):
        parts.append(f"Wind-Zusammenfassung: {_g('wind_summary')}")
    if _g("wind_shear"):
        parts.append(f"Wind-Shear: {_g('wind_shear')}")

    fly_tier = _g("fly_status") or _g("flyability_tier") or ""
    if ss in ("safe", "conditional") and fly_tier:
        parts.append(
            f"Region-Fly-Status: {fly_tier} | "
            f"Flugtyp: {_g('flight_type', '?')} | "
            f"Peak-Climb: {_g('peak_climb_rate', 0)} m/s"
        )
        tq = _g("thermal_quality")
        if tq:
            parts.append(f"Region-Thermik: {tq}")
        xc_pot = _g("xc_potential")
        xc_det = _g("xc_details")
        if xc_pot or xc_det:
            parts.append(f"Region-XC: {xc_pot or '?'} — {xc_det or ''}")
    else:
        parts.append("Region-Fliegbarkeit: nicht fliegbar (not_safe) — Streckenflug.tier muss 'kein_xc' sein.")

    summary = _g("summary")
    if summary:
        parts.append(f"Region-Summary: {summary}")

    parts.append(
        "→ Nutze diesen Block AUSSCHLIESSLICH fuer TEIL 4 (Streckenflug). "
        "Konflikt-Check: Spot fliegbar + Region WIND-STRONG>=2h oder Foehn → "
        "streckenflug.tier max 'lokal', limiting_factor='region_wind_aloft'."
    )
    return "\n".join(parts)


def _check_aloft_in_band(level_data, lower_alt, upper_alt, has_gusts=True):
    """
    Bestimmt max W(z) und max T(z) im Flugband [lower_alt, upper_alt] durch
    lineare Interpolation zwischen Drucklevels — konsistent mit Meteogramm.

    Statt rohe PL-Punkte zu pruefen (knife-edge: ein Spike auf 600 hPa knapp
    ueber Thermik-Top kann Tag triggern, ohne im Meteogramm sichtbar zu sein),
    wird der **interpolierte Wind-Verlauf** innerhalb des Bands ausgewertet.
    Da W(z) zwischen PLs linear ist, liegt das Maximum zwingend an den
    Bandgrenzen oder an PL-Knoten innerhalb des Bands → endliche Kandidaten.

    level_data: Liste von Dicts mit 'altitude', 'wind_speed', optional
    'wind_gusts' (=T(z) aus estimate_altitude_gusts).
    Returns: (max_wind, max_gust). Beide None, falls Band leer/ungueltig.
    """
    if not level_data or upper_alt <= lower_alt:
        return None, None

    pts = sorted(
        [(lv["altitude"], lv["wind_speed"], lv.get("wind_gusts")) for lv in level_data
         if lv.get("altitude") is not None and lv.get("wind_speed") is not None],
        key=lambda x: x[0]
    )
    if not pts:
        return None, None

    def _interp(z):
        if z <= pts[0][0]:
            return pts[0][1], pts[0][2]
        if z >= pts[-1][0]:
            return pts[-1][1], pts[-1][2]
        for i in range(len(pts) - 1):
            h0, w0, g0 = pts[i]
            h1, w1, g1 = pts[i + 1]
            if h0 <= z <= h1:
                if h1 == h0:
                    return w0, g0
                f = (z - h0) / (h1 - h0)
                w = w0 + f * (w1 - w0)
                g = None if (g0 is None or g1 is None) else g0 + f * (g1 - g0)
                return w, g
        return None, None

    candidates = [lower_alt, upper_alt]
    for h, _, _ in pts:
        if lower_alt < h < upper_alt:
            candidates.append(h)

    max_w = None
    max_g = None
    for z in candidates:
        w, g = _interp(z)
        if w is not None and (max_w is None or w > max_w):
            max_w = w
        if has_gusts and g is not None and (max_g is None or g > max_g):
            max_g = g
    return max_w, max_g


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

            # Stateful Thermik-Berechnung über alle Stunden (Single Source of Truth
            # mit Meteogramm und Single-Day-Context).
            daily_thermals = compute_daily_thermals(
                hourly_data,
                pressure_level_data,
                elevation_m,
                config.PRESSURE_LEVELS,
                slope_azimuth=spot.get("slope_azimuth"),
                slope_angle=spot.get("slope_angle"),
                region_id=spot_region_id,
            )

            # Peak-Werte für Zusammenfassung finden
            max_climb = 0.0
            max_climb_h = 0

            # Formatiere Stundendaten (nur Flugstunden)
            sorted_times = sorted(hourly_data.keys())
            hourly_lines = []

            prev_day = None

            # Per-Tag-Tracking für TAGESPROFIL-Block
            day_state = {"tag_counts": {}, "clean": 0, "total": 0, "day": None}

            def _emit_day_profile(state):
                """Hängt eine TAGESPROFIL-Zeile für einen abgeschlossenen Tag an."""
                if state["total"] == 0:
                    return
                clean_pct = (state["clean"] / state["total"]) * 100
                major_tags_order = [
                    "[GUST-DANGER]", "[ALOFT-WIND-DANGER]", "[ALOFT-GUST-DANGER]",
                    "[WIND-DANGER]", "[RAIN-WARN]", "[CAPE-DANGER]", "[CAPE-WARN]", "[THUNDERSTORM]", "[OVERCAST-DANGER]",
                    "[SHEAR-UNUSABLE]", "[THERMAL-TORN-UNUSABLE]", "[THERMAL-ROUGH-UNUSABLE]", "[THERMAL-WIND-UNUSABLE]",
                    "[THERMAL-ROUGH-FRAGMENTED]",
                    "[GUST-WARN]", "[ALOFT-WIND-WARN]", "[ALOFT-GUST-WARN]",
                    "[SHEAR-DEGRADED]", "[THERMAL-TORN-DEGRADED]", "[THERMAL-ROUGH-DEGRADED]", "[THERMAL-WIND-DEGRADED]",
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

                # Thermik-Proxy aus stateful Berechnung lesen
                thermal_info = ""
                h_climb = 0.0
                h_max_h = 0
                effective_ceiling = spot["elevation_m"] + 1000
                try:
                    therm = daily_thermals.get(timestamp)
                    if therm and "error" not in therm:
                        h_climb = therm["climb_rate"]
                        thermal_top_raw = therm["max_height"]
                        lcl = therm.get("lcl")
                        if isinstance(thermal_top_raw, (int, float)) and isinstance(lcl, (int, float)):
                            h_max_h = min(thermal_top_raw, lcl)
                        else:
                            h_max_h = thermal_top_raw
                        effective_ceiling = max(effective_ceiling, h_max_h + 1000)
                        if h_climb > max_climb:
                            max_climb = h_climb
                            max_climb_h = h_max_h

                        lcl_str = f", LCL/Basis {lcl}m" if lcl else ""
                        thermal_info = f" | THERMIK-PROXY: {h_climb} m/s bis {h_max_h}m MSL{lcl_str}"
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
                # Strahlung am Boden — die relevante Groesse fuer Thermik (Mai 2026).
                # Cloud-% beschreiben Bedeckung, swr/direct sagen was am Boden ankommt.
                swr_raw = data.get("shortwave_radiation")
                direct_raw = data.get("direct_radiation")
                if isinstance(swr_raw, (int, float)):
                    if isinstance(direct_raw, (int, float)):
                        sunshine_str += f", {int(round(swr_raw))} W/m² (direkt {int(round(direct_raw))})"
                    else:
                        sunshine_str += f", {int(round(swr_raw))} W/m²"

                # Wind-Check (Boden-10m bestimmt WIND-OK/WRONG)
                is_ok = self._is_wind_in_range(wind_dir, spot["windrichtung"])
                wind_status = "[WIND-OK]" if is_ok else "[WIND-WRONG]"

                warnings = []

                # Bodenwind-Magnitude (universelle Schwellen, Boden + Hoehe gleich).
                # ideal_wind_max aus CSV wird nicht mehr verwendet (Apr 2026 Harmonisierung).
                if isinstance(wind_speed, (int, float)):
                    if wind_speed > config.WIND_DANGER_KMH:
                        warnings.append("[WIND-DANGER]")
                    elif wind_speed > config.WIND_WARN_KMH:
                        warnings.append("[WIND-WARN]")

                if isinstance(wind_gusts, (int, float)) and isinstance(wind_speed, (int, float)):
                    if wind_gusts > config.GUST_DANGER_KMH:
                        warnings.append("[GUST-DANGER]")
                    elif wind_gusts > config.GUST_WARN_KMH:
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

                        # ALOFT-Tag-Trigger: interpoliertes W(z) und T(z) im
                        # realistischen Flugband (Thermik-Top + 300m statt
                        # +1000m). Verhindert false-positives durch PL-Spikes
                        # weit ueber dem Thermik-Top, die im Meteogramm nicht
                        # sichtbar sind. Fallback elev+1000m falls keine
                        # Thermik (entspricht altem Verhalten).
                        if h_max_h and h_max_h > 0:
                            real_ceiling = h_max_h + 300
                        else:
                            real_ceiling = effective_ceiling
                        max_w, max_g = _check_aloft_in_band(
                            display_with_gusts,
                            spot["elevation_m"],
                            real_ceiling,
                            has_gusts=True,
                        )
                        if max_w is not None:
                            if max_w > config.WIND_DANGER_KMH:
                                aloft_danger = True
                            elif max_w > config.WIND_WARN_KMH:
                                aloft_warn = True
                        if max_g is not None:
                            if max_g > config.GUST_DANGER_KMH:
                                aloft_gust_danger = True
                            elif max_g > config.GUST_WARN_KMH:
                                aloft_gust_warn = True

                if aloft_danger:
                    if "[ALOFT-WIND-DANGER]" not in warnings:
                        warnings.append("[ALOFT-WIND-DANGER]")
                elif aloft_warn:
                    if "[ALOFT-WIND-WARN]" not in warnings:
                        warnings.append("[ALOFT-WIND-WARN]")

                if aloft_gust_danger:
                    if "[ALOFT-GUST-DANGER]" not in warnings:
                        warnings.append("[ALOFT-GUST-DANGER]")
                elif aloft_gust_warn:
                    if "[ALOFT-GUST-WARN]" not in warnings:
                        warnings.append("[ALOFT-GUST-WARN]")

                try:
                    cape = data.get("cape")
                    if isinstance(cape, (int, float)) and cape > config.CAPE_WARN_JKG:
                        # CAPE-DANGER (hart): extreme Instabilitaet oder CAPE + Regen/Schauer (aktive Ueberentwicklung)
                        # CAPE-WARN (soft): Potenzial vorhanden, aber Modell prognostiziert keinen Trigger → conditional
                        if cape > config.CAPE_DANGER_JKG or "[RAIN-WARN]" in warnings:
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

                # Tag-Histogram pro Tag für TAGESPROFIL — nur echte Hazard-Tags.
                # WIND-WRONG ist KEIN Hazard, sondern ein Startbarkeits-Filter
                # (siehe STARTBARKEIT-Block) und wird hier bewusst nicht gezählt.
                for w in warnings:
                    day_state["tag_counts"][w] = day_state["tag_counts"].get(w, 0) + 1
                # "Clean" = WIND-OK ohne harte Warnungen
                hard_warnings_set = {"[GUST-DANGER]", "[ALOFT-WIND-DANGER]", "[ALOFT-GUST-DANGER]",
                                     "[RAIN-WARN]", "[CAPE-DANGER]", "[THUNDERSTORM]", "[WIND-DANGER]", "[OVERCAST-DANGER]"}
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

    def _calculate_bl_mean_wind(self, wind_speed_10m, pl_data, elevation_m, thermal_top_m):
        """
        Mittlerer Horizontalwind durch die Mischungsschicht (km/h).
        Mechanismus D aus meteo_research/wind_shear_thermal_quality.md Abschnitt 3.1:
        Ab einer bestimmten Grundwind-Staerke kann sich die Thermikblase gar nicht
        erst organisiert abloesen — unabhaengig von Scherung oder Boeigkeit.

        Verfahren: Surface-Wind (10m) + alle PL-Winde mit
        `elevation_m < h_val <= thermal_top_m` einsammeln, arithmetisches Mittel.
        Ohne PL-Samples in der Schicht: Fallback auf 850 hPa (nur wenn Hoehe nahe
        der BL — sonst return None).

        Returns: float km/h oder None.
        """
        if not isinstance(wind_speed_10m, (int, float)):
            return None
        if not pl_data or not isinstance(thermal_top_m, (int, float)):
            return None
        if thermal_top_m <= elevation_m:
            return None

        samples = [float(wind_speed_10m)]
        for level in config.PRESSURE_LEVELS:
            h_val = pl_data.get(f"geopotential_height_{level}hPa")
            ws_val = pl_data.get(f"wind_speed_{level}hPa")
            if h_val is None or ws_val is None:
                continue
            if elevation_m < h_val <= thermal_top_m:
                samples.append(float(ws_val))

        # Mindestens 2 Samples (Surface + 1 PL) sonst unzuverlaessig.
        if len(samples) < 2:
            # Fallback: 850 hPa, falls innerhalb sinnvoller Schicht-Naehe
            h_850 = pl_data.get("geopotential_height_850hPa")
            ws_850 = pl_data.get("wind_speed_850hPa")
            if (h_850 is not None and ws_850 is not None
                    and elevation_m < h_850 <= thermal_top_m + 500):
                samples.append(float(ws_850))
            if len(samples) < 2:
                return None

        return sum(samples) / len(samples)

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
        debug = {"du_dz": None, "bs": None, "gf": None, "zone": None,
                 "tq_ratio": None, "bl_mean_wind": None}

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

        # --- BL-Mean-Wind (Thermik-Organisation durch Grundwind gestoert) ---
        # Mechanismus D aus wind_shear_thermal_quality.md Abschnitt 3.1:
        # Grosse mittlere Windgeschwindigkeit durch die BL verhindert, dass
        # sich die Blase organisiert abloest — unabhaengig von Scherung/Boeen.
        # Ersetzt fuer Regionen die ROUGH-Familie (die Boeen braucht).
        bl_mean_wind = self._calculate_bl_mean_wind(
            wind_speed_10m, pl_data, elevation_m, thermal_top_m
        )
        debug["bl_mean_wind"] = bl_mean_wind
        if bl_mean_wind is not None:
            bl_cfg = config.BL_MEAN_WIND_THRESHOLDS.get(
                terrain_zone, config.BL_MEAN_WIND_THRESHOLDS["alpen"]
            )
            if bl_mean_wind >= bl_cfg["danger"]:
                tags.append("[THERMAL-WIND-UNUSABLE]")
            elif bl_mean_wind >= bl_cfg["warn"]:
                tags.append("[THERMAL-WIND-DEGRADED]")

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

    def _format_foehn_info(self, date_str: str = None, kritischer_foehn: str = "Süd", cache_key: str = None) -> str:
        """Formatiert Föhn-Indikatoren als Text. Sucht bei Angabe eines Datums das Maximum.

        Wenn cache_key gesetzt ist, wird das ausgewertete Föhn-Level zusätzlich in
        self._ctx_foehn_cache abgelegt (Snapshot der worst-case Stunde des Tages) und
        steht dem deterministischen Föhn-Override im Post-Processing zur Verfügung.
        """
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

        # Cache fuer deterministischen Foehn-Override (analyzers.py).
        # Nur "relevante" Auswertung speichern (= passend zur kritischen Richtung).
        # Irrelevante Richtung → level "none", damit der Override nichts triggert.
        if cache_key is not None and hasattr(self, "_ctx_foehn_cache"):
            cached_level = "none" if direction_irrelevant else ev.get("level", "none")
            self._ctx_cache_put(self._ctx_foehn_cache, cache_key, {
                "level": cached_level,
                "delta_p_hpa": ev.get("delta_p_hpa"),
                "direction": foehn_dir,
                "kritischer_foehn": kritischer_foehn,
                "crest_wind_kmh": ev.get("crest_wind_kmh"),
                "crest_dir_deg": ev.get("crest_dir_deg"),
            })

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
        """Bereinigt Freitext-Felder (summary/wind_summary/wind_shear), wenn aktiver
        Foehn fuer den Standort irrelevant ist.

        Strukturierte Felder (foehn_risk, caution_notes, no_go_reasons) werden bereits
        von engine/decision_engine.apply_foehn_decision() autoritativ verwaltet —
        diese Methode kuemmert sich nur noch um die LLM-Prosa, weil das LLM Foehn-Hinweise
        manchmal ueber den Fliesstext leakt, auch wenn die Strukturfelder korrekt sind.
        """
        if kritischer_foehn == "Beide":
            return result

        active_dir = self._get_active_foehn_direction()
        if active_dir == "none":
            return result

        is_irrelevant = (
            (kritischer_foehn == "Süd" and active_dir == "Nord") or
            (kritischer_foehn == "Nord" and active_dir == "Süd")
        )
        if not is_irrelevant:
            return result

        # Sentence-Level-Filter: Saetze mit Foehn-Keywords aus den Prosa-Feldern droppen.
        from engine.decision_engine import FOEHN_KEYWORDS
        for key in ("summary", "wind_summary", "wind_shear"):
            text = result.get(key)
            if not isinstance(text, str) or not text.strip():
                continue
            sentences = re.split(r"(?<=[\.\!\?])\s+", text)
            kept = [
                s for s in sentences
                if s.strip() and not any(kw in s.lower() for kw in FOEHN_KEYWORDS)
            ]
            new_text = " ".join(kept).strip()
            if new_text != text.strip():
                logger.info(
                    f"Foehn-Strip (Prosa) fuer {result.get('spot') or result.get('region') or '?'}/"
                    f"{result.get('date', '?')}: {active_dir}foehn irrelevant — Satz aus '{key}' entfernt"
                )
                result[key] = new_text

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

    def _build_single_spot_context(self, spot, date_str: str, mode: str = "chat", region_analysis_result: dict = None) -> str:
        """
        Baut Wetterkontext für EINEN Spot an EINEM Tag.
        mode="chat": Filtert vergangene Stunden aus (für aktuelle Anfragen).
        mode="dashboard": Zeigt alle Stunden des Tages (10-17) für die Analyse.
        region_analysis_result: optional, bereits berechnete Region-Analyse für diesen Tag.
            Wird als Kontext-Block am Ende angehängt für die Streckenflug-Bewertung.
            None oder leer → Block "Region-Kontext: nicht verfügbar" wird angehängt.
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
        spot_terrain_zone = get_terrain_zone(elevation_m, spot_region_id)

        # Stateful Thermik-Berechnung über alle Stunden (Single Source of Truth:
        # gleiche climb_rate / max_height wie im Meteogramm). Thermal Inertia,
        # Encroachment-Cap und H-skalierte Verfallsrate wirken nur mit State-
        # Carry-Over korrekt.
        daily_thermals = compute_daily_thermals(
            hourly_data,
            pressure_level_data,
            elevation_m,
            config.PRESSURE_LEVELS,
            slope_azimuth=spot.get("slope_azimuth"),
            slope_angle=spot.get("slope_angle"),
            region_id=spot_region_id,
        )

        sorted_times = sorted(hourly_data.keys())
        now = datetime.now()
        has_data = False
        # Hour-Lines werden gepuffert (mit dt.hour als Sortier-/Filter-Schluessel),
        # damit nach der Schleife auf das aktive Tagesfenster zugeschnitten werden
        # kann (Stunden vor erstem Start-Fenster wegfiltern, transparenter Header).
        hour_lines: list[tuple[int, str]] = []
        wind_ok_hours = []
        wind_wrong_hours = []
        clean_hours = []       # WIND-OK ohne harte Warnungen
        warned_hours = []      # WIND-OK aber mit harten Warnungen (GUST/ALOFT/RAIN/CAPE)
        hourly_gusts = {}      # hour_str → gust value für Trend-Analyse
        hourly_wind_dirs = {}  # hour_str → wind_direction_10m (für Richtungsdreher-Metrik)
        # Startfenster-Klassifikation pro Stunde (siehe docs/TAGS.md, "Startfenster"):
        # rein bodenbasiert (wind_speed_10m + wind_gusts_10m + Richtung), KEIN Aloft/Foehn/Regen.
        start_window_hours_list = []   # [{"hour": int, "state": "startbar"|"sportlich"|"blockiert"|"neutral"}]
        rain_hours = []        # Stunden mit Niederschlag (innerhalb + nach Flugfenster)
        rain_in_window_h = 0   # Regen-Stunden strikt INNERHALB des Flugfensters
        thunderstorm_in_window_h = 0  # Gewitter-Stunden strikt INNERHALB des Flugfensters
        gust_hours = []        # Stunden mit GUST/ALOFT-GUST WARN/DANGER (fuer BOEEN-TREND)
        gust_danger_hours = [] # Nur DANGER-Level (>40 km/h Boden oder Flugraum)
        aloft_hours = []       # Stunden mit ALOFT-WARN/DANGER (fuer HOEHENWIND-TREND)
        aloft_danger_hours_list = []  # Nur [ALOFT-WIND-DANGER] (> WIND_DANGER_KMH)
        tag_counts = {}        # tag_name -> count über den ganzen Tag (für Tagesprofil)
        safety_timeline = []       # (hour_str, klass, label) - SICHERHEITS-VERLAUF (Wind/Boeen/Regen/CAPE/Gewitter)
        fly_timeline = []          # (hour_str, klass, label) - FLIEGBARKEITS-VERLAUF (Thermik-Qualitaet)
        altitude_segment_lines = []  # Pro Stunde eine Zeile mit Hoehen-Safety-Map
        # Thermik-Qualitaets-Zaehler
        thermal_hours_total = 0  # Stunden mit climb > 0.3 m/s
        thermal_clean_h = 0     # Thermik-Stunden ohne Quality-Tags
        tq_rough_danger_h = 0
        tq_rough_warn_h = 0
        tq_torn_danger_h = 0
        tq_torn_warn_h = 0
        tq_shear_danger_h = 0
        tq_shear_warn_h = 0
        tq_wind_danger_h = 0
        tq_wind_warn_h = 0
        peak_climb_proxy = 0.0
        productive_thermal_h = 0   # Stunden mit climb>=0.7 + low<=80% + mid<=90% + kein ROUGH-UNUSABLE
        band_too_shallow_h = 0     # Stunden mit climb>=0.7 aber Band zu duenn (<MIN_DEPTH)
        # Rating-Inputs (RATING_CONCEPT v1.5): pre-computed Werte fuer Quality-Matrix.
        # Strengere Schwelle als productive_thermal_h, weil das Rating "echte" Thermik
        # erwartet (≥1.5 m/s), nicht nur die Decision-Schwelle 0.7 m/s.
        _hourly_climbs = []        # alle climb-Werte im Fly-Fenster (fuer sustained Peak)
        productive_h_strict = 0    # Stunden mit climb >= 1.5 m/s + Cloud-OK + kein ROUGH-UNUSABLE
        # Cloud-Akkumulatoren NUR ueber Thermikstunden (climb>=0.3) — analog zur Logik
        # bei productive_thermal_h: Morgenwolken ohne Thermik zaehlen nicht mit.
        # Fuer Violett-Check (XC-Tag braucht saubere Sonne).
        cloud_low_sum = 0.0
        cloud_mid_sum = 0.0
        cloud_high_sum = 0.0      # v1.6: fuer cloud_structure-Klassifikation (Cirrus etc.)
        _prod_tops_agl = []       # v1.6: Thermik-Top AGL ueber Stunden mit prod_h_strict
        _prod_climbs = []         # v1.6: climb-Werte waehrend prod_h_strict Stunden (fuer avg)
        strong_h = 0              # v1.6: Stunden mit climb >= 2.0 m/s (starke Thermik)
        # CLOUDS-Sicht-Zaehler (alle Flugstunden, nicht nur Thermikstunden):
        # Wolkenbasis auf/unter Startplatz mit hoher Bedeckung = Sicherheits-STOP/WARN
        # (siehe docs/TAGS.md — Bewoelkung-Sicherheits-Branch).
        cloud_at_or_below_takeoff_h = 0   # Basis ≤ elev+100 UND tief+mittel ≥ 90
        cloud_near_takeoff_h = 0          # elev+100 < Basis ≤ elev+300 UND tief+mittel ≥ 75
        min_cloud_base_active_h = None    # niedrigste Wolkenbasis ueber Flugstunden (None=wolkenfrei)

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
                therm = daily_thermals.get(timestamp)
                if therm and "error" not in therm:
                    h_climb = therm["climb_rate"]
                    if isinstance(h_climb, (int, float)) and h_climb > peak_climb_proxy:
                        peak_climb_proxy = h_climb
                    # Rating v1.5: climb-Verlauf fuer sustained-Peak (Rolling-Min ueber 2h Fenster).
                    _hourly_climbs.append(
                        float(h_climb) if isinstance(h_climb, (int, float)) else 0.0
                    )
                    # h_max_h = FLIEGBARE Thermik-Obergrenze, gecappt bei LCL (Wolkenbasis)
                    # Oberhalb der Wolkenbasis ist VFR-Flug nicht erlaubt → nicht als
                    # fliegbare Thermik zaehlen. Raw-Parcel-Top bleibt in therm["max_height"].
                    thermal_top_raw = therm["max_height"]
                    lcl = therm.get("lcl")
                    if isinstance(thermal_top_raw, (int, float)) and isinstance(lcl, (int, float)):
                        h_max_h = min(thermal_top_raw, lcl)
                    else:
                        h_max_h = thermal_top_raw
                    effective_ceiling = max(effective_ceiling, h_max_h + 1000)
                    lcl_str = f", LCL/Basis {lcl}m" if lcl else ""
                    thermal_info = f" | THERMIK-PROXY: {h_climb} m/s bis {h_max_h}m MSL{lcl_str}"
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
            # Strahlung am Boden — die eigentlich relevante Groesse fuer Thermik
            # (Mai 2026). Wolken-% beschreiben nur die Bedeckung; Strahlung sagt was
            # vom Sonnenlicht tatsaechlich am Boden ankommt — bei duennem Altostratus
            # kann mid=100% trotzdem mit swr>800 W/m² einhergehen.
            swr_raw = data.get("shortwave_radiation")
            direct_raw = data.get("direct_radiation")
            sun_str = "Strahlung n/a"
            if isinstance(swr_raw, (int, float)):
                if isinstance(direct_raw, (int, float)):
                    sun_str = f"Strahlung {int(round(swr_raw))} W/m² (direkt {int(round(direct_raw))})"
                else:
                    sun_str = f"Strahlung {int(round(swr_raw))} W/m²"

            # CLOUDS-Sicht-Aggregation (siehe docs/TAGS.md):
            # Wolken auf/unter Startplatz mit hoher Bedeckung = Sicherheitsthema (STOP/WARN).
            if isinstance(cloud_base_raw, (int, float)):
                if min_cloud_base_active_h is None or cloud_base_raw < min_cloud_base_active_h:
                    min_cloud_base_active_h = cloud_base_raw
                low_mid_cover = low_cl + mid_cl
                if cloud_base_raw <= elevation_m + 100 and low_mid_cover >= 90:
                    cloud_at_or_below_takeoff_h += 1
                elif elevation_m + 100 < cloud_base_raw <= elevation_m + 300 and low_mid_cover >= 75:
                    cloud_near_takeoff_h += 1

            # Wind-Check (Boden-10m bestimmt WIND-OK/WRONG)
            is_ok = self._is_wind_in_range(wind_dir, spot["windrichtung"])
            wind_status = "[WIND-OK]" if is_ok else "[WIND-WRONG]"

            warnings = []

            # Bodenwind-Magnitude (universelle Schwellen, Boden + Hoehe gleich).
            # ideal_wind_max aus CSV wird nicht mehr verwendet (Apr 2026 Harmonisierung).
            if isinstance(wind_speed, (int, float)):
                if wind_speed > config.WIND_DANGER_KMH:
                    warnings.append("[WIND-DANGER]")
                elif wind_speed > config.WIND_WARN_KMH:
                    warnings.append("[WIND-WARN]")

            if isinstance(wind_gusts, (int, float)) and isinstance(wind_speed, (int, float)):
                if wind_gusts > config.GUST_DANGER_KMH:
                    warnings.append("[GUST-DANGER]")
                elif wind_gusts > config.GUST_WARN_KMH:
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
                rain_in_window_h += 1
            if isinstance(wind_gusts, (int, float)):
                hourly_gusts[hour_str] = wind_gusts
            if isinstance(wind_dir, (int, float)):
                hourly_wind_dirs[hour_str] = wind_dir
            if is_ok:
                wind_ok_hours.append(hour_str)
            else:
                wind_wrong_hours.append(hour_str)

            # Startfenster-State pro Stunde (siehe docs/TAGS.md). Schwellen aus config.py.
            if not isinstance(wind_speed, (int, float)) or not isinstance(wind_gusts, (int, float)):
                sw_state = "neutral"
            elif (not is_ok
                  or wind_speed > config.WIND_DANGER_KMH
                  or wind_gusts > config.GUST_DANGER_KMH):
                sw_state = "blockiert"
            elif (wind_speed > config.WIND_WARN_KMH
                  or wind_gusts > config.GUST_WARN_KMH):
                sw_state = "sportlich"
            else:
                sw_state = "startbar"
            start_window_hours_list.append({"hour": dt.hour, "state": sw_state})

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

                    # ALOFT-Tag-Trigger: interpoliertes W(z)/T(z) im Flugband.
                    # Realistisches Band = elev bis Thermik-Top + 300m
                    # (statt +1000m). Verhindert false-positives durch PL-
                    # Spikes weit ueber dem Thermik-Top, die im Meteogramm
                    # nicht sichtbar sind. Fallback elev+1000m falls keine
                    # Thermik (entspricht altem Verhalten).
                    if h_max_h and h_max_h > 0:
                        real_ceiling = h_max_h + 300
                    else:
                        real_ceiling = effective_ceiling
                    max_w, max_g = _check_aloft_in_band(
                        display_with_gusts,
                        spot["elevation_m"],
                        real_ceiling,
                        has_gusts=True,
                    )
                    if max_w is not None:
                        if max_w > config.WIND_DANGER_KMH:
                            aloft_danger = True
                        elif max_w > config.WIND_WARN_KMH:
                            aloft_warn = True
                    if max_g is not None:
                        if max_g > config.GUST_DANGER_KMH:
                            aloft_gust_danger = True
                        elif max_g > config.GUST_WARN_KMH:
                            aloft_gust_warn = True

            if aloft_danger:
                if "[ALOFT-WIND-DANGER]" not in warnings:
                    warnings.append("[ALOFT-WIND-DANGER]")
            elif aloft_warn:
                if "[ALOFT-WIND-WARN]" not in warnings:
                    warnings.append("[ALOFT-WIND-WARN]")

            if aloft_gust_danger:
                if "[ALOFT-GUST-DANGER]" not in warnings:
                    warnings.append("[ALOFT-GUST-DANGER]")
            elif aloft_gust_warn:
                if "[ALOFT-GUST-WARN]" not in warnings:
                    warnings.append("[ALOFT-GUST-WARN]")

            try:
                cape = data.get("cape")
                if isinstance(cape, (int, float)) and cape > config.CAPE_WARN_JKG:
                    # CAPE-DANGER (hart): extreme Instabilitaet oder CAPE + Regen (aktive Ueberentwicklung)
                    # CAPE-WARN (soft): Potenzial vorhanden, aber kein Trigger → conditional
                    if cape > config.CAPE_DANGER_JKG or "[RAIN-WARN]" in warnings:
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
                cloud_low_sum += low_cl
                cloud_mid_sum += mid_cl
                cloud_high_sum += high_cl  # v1.6 fuer cloud_structure-Klassifikation
                tq_tags_this_hour = {t for t in warnings if t.startswith(("[SHEAR-", "[THERMAL-TORN-", "[THERMAL-ROUGH-", "[THERMAL-WIND-"))}
                # THERMAL-ROUGH-UNUSABLE (mechanische Klapper-Gefahr, nur Spots) ODER
                # THERMAL-WIND-UNUSABLE (Grundwind zu stark, Blase organisiert sich nicht,
                # Research 3.1) blockieren den Produktiv-Zaehler. FRAGMENTED ist "zu schwach,
                # nicht gefaehrlich" — gehoert damit nicht in den Gefahren-Topf.
                # SHEAR/TORN bleiben reine Qualitaets-Issues (Bart schwer zentrierbar,
                # aber Thermik existiert) und blockieren produktive Stunden nicht.
                rough_unusable_this_hour = (
                    "[THERMAL-ROUGH-UNUSABLE]" in tq_tags_this_hour
                    or "[THERMAL-WIND-UNUSABLE]" in tq_tags_this_hour
                )
                # Bewoelkung wird NICHT mehr als Productivity-Gate verwendet (Mai 2026).
                # Begruendung: die Thermik-Engine (thermik_calculator.py) berechnet climb_rate
                # bereits aus direct/diffuse_radiation — die Wolken-Daempfung steckt also
                # physikalisch ueber H (sensible heat flux) bereits in climb. Ein zusaetzlicher
                # Cloud-Cover-Gate waere Doppelbestrafung (siehe thermik_calculator.py:1367-1369:
                # "W*-Deardorff beinhaltet die Bewoelkungsdaempfung bereits ... wir duerfen
                # hier nicht nochmals kuenstlich mit einem sun_factor multiplizieren").
                # Zusaetzlich: ICON-D2 cloud_cover_mid ist flaechige Bedeckung, nicht optische
                # Dicke — bei duennem Altostratus zeigt mid=100% trotz swr>800 W/m². Strahlung
                # ist der verlaesslichere Proxy und ist in climb bereits eingepreist.
                # Bewoelkung bleibt fuer Labels (VIEL_BEWOELKUNG/GUTE_EINSTRAHLUNG/cu_clean_top)
                # und LLM-Prosa relevant — nur nicht als Productivity-Gate.
                # Band-Tiefe: Mindest-Banddicke aus Physik-Heuristik (3 zentrierbare
                # Kurbeln mit Netto-Steigen), climb-abhaengig und terrain-differenziert.
                # Siehe thermik_calculator.min_band_depth + meteo_research/band_depth_calibration.md.
                band_depth = (h_max_h - elevation_m) if isinstance(h_max_h, (int, float)) else 0
                _min_band = min_band_depth(h_climb, spot_terrain_zone)
                band_usable = band_depth >= _min_band
                if (h_climb >= config.PRODUCTIVE_CLIMB_MIN
                        and not rough_unusable_this_hour
                        and band_usable):
                    productive_thermal_h += 1
                elif (h_climb >= config.PRODUCTIVE_CLIMB_MIN
                        and not rough_unusable_this_hour
                        and not band_usable):
                    band_too_shallow_h += 1
                # Rating-Input v1.5: strenge Produktivitaets-Schwelle (≥1.5 m/s)
                if (h_climb >= 1.5
                        and not rough_unusable_this_hour
                        and band_usable):
                    productive_h_strict += 1
                    _prod_climbs.append(float(h_climb))
                    # v1.6: Thermik-Top AGL fuer working_height-Median tracken.
                    # h_max_h ist MSL (bereits LCL-gecappt). AGL = MSL - elevation.
                    if isinstance(h_max_h, (int, float)):
                        _agl = max(0, h_max_h - elevation_m)
                        _prod_tops_agl.append(_agl)
                # v1.6: zusaetzlich Stunden mit starker Thermik (≥2.0 m/s) zaehlen
                if h_climb >= 2.0 and not rough_unusable_this_hour and band_usable:
                    strong_h += 1
                if not tq_tags_this_hour:
                    thermal_clean_h += 1
                else:
                    # Nur echtes UNUSABLE als Gefahrenzaehler; FRAGMENTED als eigener Warn-Zaehler.
                    if "[THERMAL-ROUGH-UNUSABLE]" in tq_tags_this_hour:
                        tq_rough_danger_h += 1
                    elif "[THERMAL-ROUGH-FRAGMENTED]" in tq_tags_this_hour:
                        tq_rough_warn_h += 1
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
                    if "[THERMAL-WIND-UNUSABLE]" in tq_tags_this_hour:
                        tq_wind_danger_h += 1
                    elif "[THERMAL-WIND-DEGRADED]" in tq_tags_this_hour:
                        tq_wind_warn_h += 1

            warning_str = " " + " ".join(warnings) if warnings else ""

            # Tag-Histogram: zähle nur echte Hazard-Tags für TAGESPROFIL.
            # WIND-WRONG ist KEIN Hazard, sondern ein Startbarkeits-Filter
            # (siehe STARTBARKEIT-Block) und wird hier bewusst nicht gezählt —
            # sonst landet er in "Hauptgefahren am Tag:" und wird vom LLM
            # als Sicherheits-/Flyability-Warnung fehlinterpretiert.
            for w in warnings:
                tag_counts[w] = tag_counts.get(w, 0) + 1
            if "[THUNDERSTORM]" in warnings:
                thunderstorm_in_window_h += 1

            # ─── STUNDENVERLAUF: klassifiziere diese Stunde ───
            # ─── SICHERHEITS-VERLAUF: nur Safety-Tags (Wind/Boeen/Regen/CAPE/Gewitter) ───
            safety_hard_tags = {"[GUST-DANGER]", "[ALOFT-WIND-DANGER]", "[ALOFT-GUST-DANGER]",
                                "[RAIN-WARN]", "[CAPE-DANGER]", "[THUNDERSTORM]",
                                "[WIND-DANGER]", "[OVERCAST-DANGER]"}
            safety_warn_tags = {"[GUST-WARN]", "[ALOFT-WIND-WARN]", "[ALOFT-GUST-WARN]",
                                "[CAPE-WARN]"}
            s_hard = [t for t in warnings if t in safety_hard_tags]
            s_warn = [t for t in warnings if t in safety_warn_tags]
            if not is_ok:
                s_klass = "wind-wrong"
                s_label = "WIND-WRONG"
            elif s_hard:
                s_klass = "danger"
                s_label = "DANGER(" + "+".join(t.strip("[]").replace("-WARN", "").replace("-DANGER", "") for t in s_hard) + ")"
            elif s_warn:
                s_klass = "warn"
                s_label = "WARN(" + "+".join(t.strip("[]").replace("-WARN", "").replace("-DANGER", "") for t in s_warn) + ")"
            else:
                s_klass = "clean"
                s_label = "clean"
            safety_timeline.append((hour_str, s_klass, s_label))

            # ─── FLIEGBARKEITS-VERLAUF: nur Thermik-Qualitaet + Produktivitaet ───
            # Unabhaengig von Safety — hier geht es rein um "kann man thermisch fliegen?"
            tq_tags_this_hour_fly = {t for t in warnings if t.startswith(("[SHEAR-", "[THERMAL-TORN-", "[THERMAL-ROUGH-", "[THERMAL-WIND-"))}
            unusable_hits = [t for t in tq_tags_this_hour_fly if t.endswith("-UNUSABLE]")]
            fragmented_hits = [t for t in tq_tags_this_hour_fly if t.endswith("-FRAGMENTED]")]
            degraded_hits = [t for t in tq_tags_this_hour_fly if t.endswith("-DEGRADED]")]
            has_thermal = isinstance(h_climb, (int, float)) and h_climb >= config.THERMAL_QUALITY_MIN_CLIMB
            # Bewoelkung NICHT mehr im Productivity-Check (Mai 2026, siehe ausfuehrliche
            # Begruendung im Spot-Loop oben ~Zeile 1789): climb_rate ist bereits
            # strahlungsabgeleitet, Cloud-Gate waere Doppelbestrafung.
            _min_band_tl = min_band_depth(h_climb, spot_terrain_zone)
            is_productive = (
                has_thermal
                and h_climb >= config.PRODUCTIVE_CLIMB_MIN
                and "[THERMAL-ROUGH-UNUSABLE]" not in unusable_hits
                and "[THERMAL-WIND-UNUSABLE]" not in unusable_hits
                and isinstance(h_max_h, (int, float))
                and (h_max_h - elevation_m) >= _min_band_tl
            )
            if not has_thermal:
                f_klass = "keine-thermik"
                f_label = "keine-thermik"
            elif unusable_hits:
                f_klass = "unusable"
                f_label = "UNUSABLE(" + "+".join(t.strip("[]").replace("THERMAL-", "").replace("-UNUSABLE", "") for t in unusable_hits) + ")"
            elif is_productive:
                f_klass = "produktiv"
                f_label = f"produktiv({h_climb:.1f})"
            elif fragmented_hits or degraded_hits:
                # FRAGMENTED = schwache Thermik (eigene Kategorie, kein UNUSABLE-Gefahr)
                f_klass = "degraded"
                parts = [t.strip("[]").replace("THERMAL-", "").replace("-FRAGMENTED", "-FRAG") for t in fragmented_hits]
                parts += [t.strip("[]").replace("THERMAL-", "").replace("-DEGRADED", "") for t in degraded_hits]
                f_label = "degraded(" + "+".join(parts) + ")"
            else:
                # Thermik vorhanden aber nicht produktiv (Band zu duenn oder schwacher Climb).
                # "wolken" als Ablehnungsgrund entfaellt — Wolken sind kein Productivity-Gate mehr.
                reason = []
                if isinstance(h_max_h, (int, float)) and (h_max_h - elevation_m) < _min_band_tl:
                    reason.append("band-flach")
                if h_climb < config.PRODUCTIVE_CLIMB_MIN:
                    reason.append("schwach")
                f_klass = "soaring"
                f_label = "soaring(" + "+".join(reason) + ")" if reason else "soaring"
            fly_timeline.append((hour_str, f_klass, f_label))

            # ─── HOEHEN-SEGMENTE: kompakte Safety-Map pro Stunde ───
            if display_with_gusts:
                seg_parts = []
                any_warn = False
                for lv in display_with_gusts:
                    alt = lv["altitude"]
                    if not (elevation_m <= alt <= effective_ceiling):
                        continue
                    ws_val = lv["wind_speed"]
                    g_val = lv.get("wind_gusts")
                    top_val = max(ws_val, g_val) if g_val is not None else ws_val
                    if top_val > 40:
                        cls = "DANGER"
                        any_warn = True
                    elif top_val > 30:
                        cls = "WARN"
                        any_warn = True
                    else:
                        cls = "OK"
                    seg_parts.append(f"{int(alt)}m:{cls}")
                if seg_parts and any_warn:
                    top_str = f"{int(h_max_h)}m" if isinstance(h_max_h, (int, float)) else "?"
                    altitude_segment_lines.append(
                        f"{hour_str} | Band {elevation_m}-{int(effective_ceiling)}m (Thermik-Top {top_str}): "
                        + " · ".join(seg_parts)
                    )

            gust_tags = {"[GUST-WARN]", "[GUST-DANGER]",
                         "[ALOFT-GUST-WARN]", "[ALOFT-GUST-DANGER]"}
            gust_danger_tags = {"[GUST-DANGER]", "[ALOFT-GUST-DANGER]"}
            warn_set = set(warnings)
            if gust_tags & warn_set:
                gust_hours.append(hour_str)
                if gust_danger_tags & warn_set:
                    gust_danger_hours.append(hour_str)

            # Wind-Trend: Stunden mit Wind WARN/DANGER (Boden + Hoehe summiert).
            # Phase 3: Bodenwind und Hoehenwind teilen sich denselben Trend, weil
            # die Schwellen identisch sind (WIND_WARN_KMH / WIND_DANGER_KMH).
            wind_warn_hour = (
                "[WIND-WARN]" in warn_set or "[WIND-DANGER]" in warn_set
                or "[ALOFT-WIND-WARN]" in warn_set or "[ALOFT-WIND-DANGER]" in warn_set
            )
            wind_danger_hour = (
                "[WIND-DANGER]" in warn_set or "[ALOFT-WIND-DANGER]" in warn_set
            )
            if wind_warn_hour:
                aloft_hours.append(hour_str)
                if wind_danger_hour:
                    aloft_danger_hours_list.append(hour_str)

            # Klassifiziere saubere vs. gewarnte Stunden (nach allen Warnungen)
            # WICHTIG: Die Thermik-Qualitaets-Tags (SHEAR / THERMAL-TORN / THERMAL-ROUGH)
            # gehoeren hier NICHT rein. Sie betreffen die Fliegbarkeit (kann ich Thermik
            # fliegen?), nicht die Sicherheit (kann ich starten und heil wieder landen?).
            # Eine Stunde mit SHEAR-UNUSABLE + WIND-OK + keine Boeen bleibt sicher fliegbar
            # (Abgleiter), sie ist nur thermisch wertlos. Die LLM-Fliegbarkeits-Phase
            # (flyability.md) interpretiert die Tags und degradiert auf gray/green.
            hard_warnings = {
                "[GUST-DANGER]", "[ALOFT-WIND-DANGER]", "[ALOFT-GUST-DANGER]",
                "[RAIN-WARN]", "[CAPE-DANGER]", "[THUNDERSTORM]", "[WIND-DANGER]",
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

            hour_lines.append((
                dt.hour,
                f"{time_str}: Temp {temp}°C | Wind {wind_speed}km/h aus {wind_dir}° (Turbulenzrisiko {wind_gusts}km/h{sfc_excess}) {wind_status}{warning_str} | "
                f"Wolkenbasis {cloud_base} | Bewölkung {cloud_cover}% (tief {low_cl:.0f}%, mittel {mid_cl:.0f}%, hoch {high_cl:.0f}%) | {sun_str} | FLUGBEREICH: {elevation_m}–{effective_ceiling}m MSL{alt_wind_info}{thermal_info}{tq_info}"
            ))

        if not has_data:
            return ""

        # ─── Aktives Tagesfenster bestimmen + Stunden-Slicing ───
        # Im Dashboard-Modus (Analyse): Stunden vor dem ersten Start-Fenster
        # weglassen und Header anhaengen, der das transparent macht. Damit sieht
        # das LLM weder WIND-WRONG-Stunden vor Tagesbeginn noch muss es darueber
        # spekulieren ("warum fehlen Stunden?"). Im Chat-Modus bleibt alles
        # sichtbar — der User fragt evtl. retrospektiv nach dem Morgen.
        active_start: int | None = None
        if mode == "dashboard":
            active_start = _determine_active_window_start(
                clean_hours, config.CLEAN_WINDOW_MIN_HOURS
            )

        if active_start is not None and active_start > config.FLIGHT_HOURS_START:
            # Filter: nur Stunden ab active_start
            kept_lines = [s for h, s in hour_lines if h >= active_start]
            skipped_until = active_start - 1
            # Begruendung fuer uebersprungene Stunden: liegt es an Windrichtung
            # (WIND-WRONG vor active_start) oder an harten Warnungen (WIND-OK
            # aber DANGER-Tag)? Wir schauen die wind_ok_hours/wind_wrong_hours an.
            ww_before = [h for h in wind_wrong_hours if int(h.split(":")[0]) < active_start]
            wo_before = [h for h in wind_ok_hours if int(h.split(":")[0]) < active_start]
            if ww_before and not wo_before:
                reason = "Windrichtung ausserhalb Sektor"
            elif wo_before and not ww_before:
                reason = "harte Warnungen (WIND/GUST/RAIN/CAPE/THUNDERSTORM)"
            else:
                reason = "Mischung aus falscher Windrichtung und harten Warnungen"
            lines.append("")
            lines.append(f"═══ TAGESFENSTER ═══")
            lines.append(
                f"Tag aktiv ab {active_start:02d}:00 (erstes Start-Fenster "
                f">= {config.CLEAN_WINDOW_MIN_HOURS}h)."
            )
            lines.append(
                f"Stunden {config.FLIGHT_HOURS_START:02d}:00-{skipped_until:02d}:00 "
                f"weggelassen: {reason}. Kein Datenfehler — diese Stunden waren "
                f"nicht startbar und sind fuer die Bewertung irrelevant."
            )
            lines.append("")
            lines.extend(kept_lines)
        else:
            # Kein Slicing (Chat-Modus, oder dashboard mit active_start am
            # Tagesbeginn / kein qualifizierendes Fenster). Alle Hour-Lines
            # uebernehmen wie bisher.
            lines.extend(s for _h, s in hour_lines)

        # Fenster-Info fuer LLM-Narrative (kompakt — Filter/Slicing ist bereits
        # oben im TAGESFENSTER-Header passiert, hier nur Beschreibungs-Material).
        longest_clean_run = _longest_consecutive_run(clean_hours)
        clean_windows_fmt = _format_clean_windows(clean_hours)
        max_swing_deg, max_swing_start, max_swing_hour, max_swing_span = _max_wind_direction_swing(hourly_wind_dirs)

        lines.append("")
        lines.append("═══ FENSTER-INFO (fuer summary/caution_notes) ═══")
        lines.append(f"Saubere Fenster (WIND-OK + ohne DANGER): {clean_windows_fmt}")
        lines.append(f"Laengstes Fenster: {longest_clean_run}h")
        if warned_hours:
            lines.append(
                f"WIND-OK-Stunden mit harten Warnungen ({len(warned_hours)}): "
                f"{', '.join(warned_hours)} (gehoeren NICHT ins safe_window)"
            )

        # Richtungsdreher-Anmerkung (nur wind_summary, KEIN Status-Downgrade)
        # Erfasst sowohl abrupte 1h-Spruenge als auch langsames Drehen ueber
        # bis zu WIND_DIRECTION_SWING_WINDOW_H Stunden (Wind unbestaendig).
        if max_swing_deg >= config.WIND_DIRECTION_SWING_NOTE_DEG and max_swing_hour:
            if max_swing_span <= 1:
                span_txt = f"Max Stunden-Wechsel {int(round(max_swing_deg))}° um {max_swing_hour}"
            else:
                span_txt = (
                    f"Max Richtungsdreher {int(round(max_swing_deg))}° "
                    f"zwischen {max_swing_start} und {max_swing_hour} "
                    f"({max_swing_span}h Drift)"
                )
            lines.append(
                f"→ ANMERKUNG Richtungsdreher: {span_txt} "
                f"(>= {config.WIND_DIRECTION_SWING_NOTE_DEG}°-Schwelle). "
                f"In wind_summary erwaehnen (NICHT in caution_notes — Drehung ist Tagesverlauf-Info, "
                f"keine Sicherheits-Warnung). KEIN Status-Downgrade, KEINE Tier-Aenderung "
                f"(safety_status + fly_status/flyability_tier bleiben wie ermittelt: "
                f"violet bleibt violet, green bleibt green, gray/bronze bleibt gray/bronze)."
            )

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
            # Histogramm der Hauptgefahren über den ganzen Tag.
            # WIND-WRONG ist hier bewusst NICHT enthalten (Startbarkeits-Filter,
            # nicht Hazard — wird im STARTBARKEIT-Block separat ausgewiesen).
            major_tags_order = [
                "[GUST-DANGER]", "[ALOFT-WIND-DANGER]", "[ALOFT-GUST-DANGER]",
                "[WIND-DANGER]", "[RAIN-WARN]", "[CAPE-DANGER]", "[CAPE-WARN]", "[THUNDERSTORM]", "[OVERCAST-DANGER]",
                "[SHEAR-UNUSABLE]", "[THERMAL-TORN-UNUSABLE]", "[THERMAL-ROUGH-UNUSABLE]", "[THERMAL-WIND-UNUSABLE]",
                "[THERMAL-ROUGH-FRAGMENTED]",
                "[GUST-WARN]", "[ALOFT-WIND-WARN]", "[ALOFT-GUST-WARN]",
                "[SHEAR-DEGRADED]", "[THERMAL-TORN-DEGRADED]", "[THERMAL-ROUGH-DEGRADED]", "[THERMAL-WIND-DEGRADED]",
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

        # ─── SICHERHEITS-VERLAUF: Sequenz pro Flugstunde (fuer safety_status) ───
        # Wenn der Datenblock auf das aktive Tagesfenster zugeschnitten wurde,
        # zeigen wir die Verlaeufe ebenfalls nur ab Tagesbeginn — sonst sieht
        # das LLM "10:00:WIND-WRONG" obwohl die Stunde fuer es gar nicht
        # existieren soll.
        def _filter_timeline_entries(timeline):
            if active_start is None or active_start <= config.FLIGHT_HOURS_START:
                return timeline
            return [(h, k, l) for (h, k, l) in timeline if int(h.split(":")[0]) >= active_start]

        safety_timeline_filtered = _filter_timeline_entries(safety_timeline)
        fly_timeline_filtered = _filter_timeline_entries(fly_timeline)

        if safety_timeline_filtered:
            lines.append("")
            lines.append("═══ SICHERHEITS-VERLAUF (Wind/Boeen/Regen/CAPE/Gewitter — beeinflusst safety_status) ═══")
            seq_parts = [f"{h}:{lbl}" for (h, _k, lbl) in safety_timeline_filtered]
            lines.append(" · ".join(seq_parts))
            lines.append(
                "→ Erkenne Trends und eingekesselte Stunden (gute Stunde zwischen "
                "zwei gefaehrlichen = NICHT als stabiles Fenster werten)."
            )

        # ─── FLIEGBARKEITS-VERLAUF: Sequenz pro Flugstunde (fuer fly_status) ───
        if fly_timeline_filtered:
            lines.append("")
            lines.append("═══ FLIEGBARKEITS-VERLAUF (Thermik-Qualitaet — beeinflusst fly_status, NICHT safety) ═══")
            seq_parts_f = [f"{h}:{lbl}" for (h, _k, lbl) in fly_timeline_filtered]
            lines.append(" · ".join(seq_parts_f))
            lines.append(
                "→ produktiv = nutzbare Thermik · soaring = nur Hangsoaring moeglich · "
                "degraded = ruppig aber fliegbar · unusable = Thermik unbrauchbar (Klapper/Scherung) · "
                "keine-thermik = kein Steigen."
            )

        # ─── HOEHEN-SEGMENTE: Safety-Karte pro Stunde (nur wenn Gefahr im Band) ───
        if altitude_segment_lines:
            lines.append("")
            lines.append("═══ HOEHEN-SEGMENTE im Flugbereich (Gefahr nach Hoehe, Safety) ═══")
            for seg_line in altitude_segment_lines:
                lines.append(seg_line)
            lines.append(
                "→ DANGER/WARN im Flugbereich (*) = relevante Sicherheits-Gefahr. Pruefe, ob die "
                "gefaehrliche Hoehe im genutzten Kurbelband liegt (Start bis Thermik-Top)."
            )

        # ─── BÖEN-INFO: Zusammenfassung für LLM-Bewertung ───
        gust_warn_h = tag_counts.get("[GUST-WARN]", 0)
        aloft_gust_warn_h = tag_counts.get("[ALOFT-GUST-WARN]", 0)
        gust_danger_h = tag_counts.get("[GUST-DANGER]", 0)
        aloft_gust_danger_h = tag_counts.get("[ALOFT-GUST-DANGER]", 0)
        aloft_warn_h = tag_counts.get("[ALOFT-WIND-WARN]", 0)
        aloft_danger_h = tag_counts.get("[ALOFT-WIND-DANGER]", 0)
        max_surface_gust = max(hourly_gusts.values()) if hourly_gusts else 0

        # "Harte Warnungen" = alles was eine Stunde objektiv unfliegbar macht
        hard_warning_tags = [
            "[GUST-DANGER]", "[ALOFT-WIND-DANGER]", "[ALOFT-GUST-DANGER]",
            "[WIND-DANGER]", "[RAIN-WARN]", "[CAPE-DANGER]", "[THUNDERSTORM]", "[OVERCAST-DANGER]",
        ]
        hard_warning_hours = sum(tag_counts.get(t, 0) for t in hard_warning_tags)

        # Cache fuer deterministische Zahlen-Injektion in _safety_check_single_spot_day.
        # LLM darf diese NICHT selber schreiben (Halluzinations-Schutz).
        # Aktives Tagesfenster fuer Pre-Filter und Cross-Checks. None = kein
        # qualifizierendes Fenster → Pre-Filter triggert not_safe.
        active_window_start = _determine_active_window_start(
            clean_hours, config.CLEAN_WINDOW_MIN_HOURS
        )

        self._ctx_cache_put(self._ctx_gust_cache, f"{name}|{date_str}", {
            "gust_warn_hours": gust_warn_h,
            "aloft_gust_warn_hours": aloft_gust_warn_h,
            "gust_danger_hours": gust_danger_h,
            "aloft_gust_danger_hours": aloft_gust_danger_h,
            "aloft_warn_hours": aloft_warn_h,
            "aloft_danger_hours": aloft_danger_h,
            "max_surface_gust": max_surface_gust,
            "wind_ok_count": len(wind_ok_hours),
            "wind_wrong_count": len(wind_wrong_hours),
            "clean_hours_count": len(clean_hours),
            "longest_clean_run_hours": longest_clean_run,
            "active_window_start": active_window_start,
            "max_wind_swing_deg": round(max_swing_deg, 1),
            "max_wind_swing_hour": max_swing_hour,
            "max_wind_swing_start": max_swing_start,
            "max_wind_swing_span_h": max_swing_span,
            "hard_warning_hours": hard_warning_hours,
            "thunderstorm_hours": tag_counts.get("[THUNDERSTORM]", 0),
            "thunderstorm_in_window_h": thunderstorm_in_window_h,
            "wind_danger_hours": tag_counts.get("[WIND-DANGER]", 0),
            "wind_warn_hours": tag_counts.get("[WIND-WARN]", 0),
            "aloft_wind_warn_hours": tag_counts.get("[ALOFT-WIND-WARN]", 0),
            "aloft_wind_danger_hours": tag_counts.get("[ALOFT-WIND-DANGER]", 0),
            "rain_hours": len(rain_hours),
            "rain_in_window_h": rain_in_window_h,
            "rain_hour_list": rain_hours,
            "start_window_hours": start_window_hours_list,
            # CLOUDS-Sicht (siehe docs/TAGS.md): Wolken auf/unter Startplatz =
            # Sicherheitsthema (STOP/WARN). Werte werden in build_topic_tags
            # gegen Schwellen geprueft — kein Hardcode hier.
            "elevation_m": elevation_m,
            "cloud_at_or_below_takeoff_h": cloud_at_or_below_takeoff_h,
            "cloud_near_takeoff_h": cloud_near_takeoff_h,
            "min_cloud_base_active_h": min_cloud_base_active_h,
        })

        # Rain-Sandwich-Erkennung fuer Prefilter + NIEDERSCHLAG-TREND
        all_hours_sorted = sorted(hourly_gusts.keys()) or sorted(set(wind_ok_hours + wind_wrong_hours))
        rain_pattern = _detect_rain_sandwich(rain_hours, all_hours_sorted)
        self._ctx_gust_cache[f"{name}|{date_str}"]["rain_sandwiched"] = rain_pattern["is_sandwiched"]
        self._ctx_gust_cache[f"{name}|{date_str}"]["max_dry_gap"] = rain_pattern["max_dry_gap"]

        # Cache fuer deterministische Flyability-Override
        # rough_danger_h = NUR THERMAL-ROUGH-UNUSABLE → echter gray-Trigger.
        # FRAGMENTED bedeutet "Thermik zu schwach, nicht gefaehrlich" (siehe config.py)
        # und zaehlt daher in tq_rough_warn_h (wie DEGRADED), nicht in danger_h.
        # tq_danger_h bleibt Summe aller UNUSABLE fuer Text-Hinweise.
        self._ctx_cache_put(self._ctx_tq_cache, f"{name}|{date_str}", {
            "thermal_hours_total": thermal_hours_total,
            "tq_danger_h": tq_rough_danger_h + tq_torn_danger_h + tq_shear_danger_h + tq_wind_danger_h,
            "rough_danger_h": tq_rough_danger_h,
            "wind_danger_h": tq_wind_danger_h,
            "peak_climb_proxy": peak_climb_proxy,
            "productive_thermal_h": productive_thermal_h,
            "productive_h_strict": productive_h_strict,
            "sustained_peak_mps": _compute_sustained_peak(_hourly_climbs, window=2),
            "working_height_agl_m": round(_median(_prod_tops_agl)) if _prod_tops_agl else 0,
            "cloud_structure": _classify_cloud_structure(
                (cloud_low_sum / thermal_hours_total) if thermal_hours_total > 0 else 0.0,
                (cloud_mid_sum / thermal_hours_total) if thermal_hours_total > 0 else 0.0,
                (cloud_high_sum / thermal_hours_total) if thermal_hours_total > 0 else 0.0,
            ),
            "avg_low_cloud_thermal_h": (cloud_low_sum / thermal_hours_total) if thermal_hours_total > 0 else 0.0,
            "avg_mid_cloud_thermal_h": (cloud_mid_sum / thermal_hours_total) if thermal_hours_total > 0 else 0.0,
            "band_too_shallow_h": band_too_shallow_h,
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
            tq_danger_h = tq_rough_danger_h + tq_torn_danger_h + tq_shear_danger_h + tq_wind_danger_h
            tq_warn_h = tq_rough_warn_h + tq_torn_warn_h + tq_shear_warn_h + tq_wind_warn_h
            tq_parts = []
            if tq_rough_danger_h:
                tq_parts.append(f"ROUGH-UNUSABLE {tq_rough_danger_h}h")
            if tq_torn_danger_h:
                tq_parts.append(f"TORN-UNUSABLE {tq_torn_danger_h}h")
            if tq_shear_danger_h:
                tq_parts.append(f"SHEAR-UNUSABLE {tq_shear_danger_h}h")
            if tq_wind_danger_h:
                tq_parts.append(f"WIND-UNUSABLE {tq_wind_danger_h}h")
            if tq_rough_warn_h:
                tq_parts.append(f"ROUGH-DEGRADED {tq_rough_warn_h}h")
            if tq_torn_warn_h:
                tq_parts.append(f"TORN-DEGRADED {tq_torn_warn_h}h")
            if tq_shear_warn_h:
                tq_parts.append(f"SHEAR-DEGRADED {tq_shear_warn_h}h")
            if tq_wind_warn_h:
                tq_parts.append(f"WIND-DEGRADED {tq_wind_warn_h}h")
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
            if tq_wind_danger_h > 0:
                wind_pct = round(100 * tq_wind_danger_h / thermal_hours_total)
                lines.append(
                    f"  WIND-UNUSABLE in {tq_wind_danger_h}h ({wind_pct}%): Mittlerer BL-Wind "
                    f"ueber Danger-Schwelle — Thermikblase kann sich nicht organisiert "
                    f"abloesen. Zaehlt WIE ROUGH-UNUSABLE in den Produktiv-Zaehler "
                    f"(blockiert green/violet). Der Tag wird dadurch gray (Abgleiter, falls "
                    f"Soaring moeglich) — KEIN Einfluss auf safety_status."
                )
        else:
            lines.append(
                "→ THERMIK-QUALITÄT (NUR Fliegbarkeit/Phase 2, NICHT Sicherheit!): "
                "KEINE THERMIK-STUNDEN — Peak-Steigen (Proxy): 0.0 m/s. "
                "Kein nutzbarer Aufwind im gesamten Flugfenster. fly_status = gray (Abgleiter)."
            )

        # ─── PRODUKTIVE-THERMIK: Stunden mit Climb + ausreichend Band ───
        if thermal_hours_total > 0:
            _sust_peak = _compute_sustained_peak(_hourly_climbs, window=2)
            lines.append(
                f"→ PRODUKTIVE-THERMIK: {productive_thermal_h}h "
                f"(Climb ≥{config.PRODUCTIVE_CLIMB_MIN} m/s, ausreichendes Höhenband, "
                f"kein ROUGH-UNUSABLE, kein WIND-UNUSABLE). "
                f"Min für green-Tag: {config.PRODUCTIVE_HOURS_FOR_GREEN}h. "
                f"HINWEIS: Bewoelkungs-% sind KEIN Productivity-Gate mehr (Mai 2026) — "
                f"die Sonnen-Daempfung steckt bereits in climb_rate ueber die strahlungs"
                f"basierte H-Berechnung. TORN-/SHEAR-UNUSABLE und ROUGH-FRAGMENTED zaehlen "
                f"MIT (Bart-Zentrierung schwieriger bzw. schwache Thermik, aber fliegbar)."
            )
            # Rating-Inputs (RATING_CONCEPT v1.6): explizit fuer Kategorien-Wahl.
            _wh = round(_median(_prod_tops_agl)) if _prod_tops_agl else 0
            _avg_climb_prod = round(sum(_prod_climbs) / len(_prod_climbs), 1) if _prod_climbs else 0.0
            _avg_low = (cloud_low_sum / thermal_hours_total) if thermal_hours_total > 0 else 0.0
            _avg_mid = (cloud_mid_sum / thermal_hours_total) if thermal_hours_total > 0 else 0.0
            _avg_high = (cloud_high_sum / thermal_hours_total) if thermal_hours_total > 0 else 0.0
            _cloud_struct = _classify_cloud_structure(_avg_low, _avg_mid, _avg_high)
            lines.append(
                f"→ RATING-INPUTS: prod_h_strict={productive_h_strict}h (Climb ≥1.5 m/s), "
                f"strong_h={strong_h}h (Climb ≥2.0 m/s), "
                f"avg_climb_prod={_avg_climb_prod:.1f} m/s (Durchschnitt waehrend prod_h_strict), "
                f"sustained_peak={_sust_peak:.1f} m/s (max über 2h, kein Einzelspike), "
                f"working_height_agl={_wh}m (Median Thermik-Top ueber produktive Stunden), "
                f"cloud_structure={_cloud_struct} "
                f"(tief={_avg_low:.0f}% mittel={_avg_mid:.0f}% hoch={_avg_high:.0f}%). "
                f"Diese Werte nutzt die Kategorien-Wahl direkt — nicht selbst nachzaehlen."
            )

            # ─── VIOLETT-Kandidat-Check (XC-Tag) ───
            # Nur Hint anzeigen wenn ALLE harten Schwellen erfuellt. LLM entscheidet final.
            avg_low = cloud_low_sum / thermal_hours_total
            avg_mid = cloud_mid_sum / thermal_hours_total
            _unusable_pct = 100.0 * tq_danger_h / thermal_hours_total
            _rough_pct = 100.0 * tq_rough_danger_h / thermal_hours_total
            _is_violet_candidate = (
                peak_climb_proxy >= config.VIOLET_PEAK_MIN
                and productive_thermal_h >= config.VIOLET_HOURS_MIN
                and _rough_pct < config.VIOLET_ROUGH_MAX
                and _unusable_pct < config.VIOLET_UNUSABLE_MAX
                and avg_low <= config.VIOLET_CLOUD_LOW_MAX
                and avg_mid <= config.VIOLET_CLOUD_MID_MAX
            )
            if _is_violet_candidate:
                lines.append(
                    f"→ VIOLETT-Kandidat: Peak {peak_climb_proxy:.1f} m/s, "
                    f"produktiv {productive_thermal_h}h, ROUGH {_rough_pct:.0f}%, "
                    f"UNUSABLE {_unusable_pct:.0f}%, Ø tief {avg_low:.0f}%, Ø mittel {avg_mid:.0f}%. "
                    f"Alle Violett-Schwellen erfüllt (Peak≥{config.VIOLET_PEAK_MIN}, "
                    f"prod≥{config.VIOLET_HOURS_MIN}h, ROUGH<{config.VIOLET_ROUGH_MAX}%, "
                    f"UNUSABLE<{config.VIOLET_UNUSABLE_MAX}%, Ø tief≤{config.VIOLET_CLOUD_LOW_MAX}%, "
                    f"Ø mittel≤{config.VIOLET_CLOUD_MID_MAX}% — optimale Cu-Zone, keine Altostratus-Dämpfung). "
                    f"fly_status = violet erlaubt (nur wenn Rating≥{config.VIOLET_RATING_MIN} — Decision-Engine setzt final)."
                )

        # Wind-Trend nach dem sauberen Fenster
        trend = _compute_wind_trend(clean_hours, hourly_gusts)
        if trend:
            lines.append(trend)

        # Niederschlag-Trend
        # all_hours_sorted already computed above (rain_pattern section)
        # Regen nur NACH dem Flugfenster (rain_in_window_h == 0): kein Sicherheitsmalus,
        # aber explizit erwaehnen damit Pilot vorbereitet ist.
        _all_rain_after_window = (
            rain_hours
            and rain_in_window_h == 0
            and all(int(h.split(":")[0]) >= config.FLIGHT_HOURS_END for h in rain_hours)
        )
        if rain_hours and all_hours_sorted:
            if _all_rain_after_window:
                lines.append(
                    f"NIEDERSCHLAG-TREND: NACH FLUGZEIT — Regen erst ab {min(rain_hours)}, "
                    f"nach Ende des Flugfensters ({config.FLIGHT_HOURS_END:02d}:00). "
                    f"Flugfenster selbst bleibt trocken. Kein Sicherheitsmalus fuer das Fenster. "
                    f"→ safety_status NICHT verschlechtern wegen Regen nach Flugzeit. "
                    f"In hazard_notes['rain'] PFLICHT erwaehnen: 'NACH-FLUGZEIT — Regen ab "
                    f"{min(rain_hours)}, nach Flugabschluss. Flugfenster unberührt.' "
                    f"rain_safety_rating = 8 (kein Einfluss aufs Fenster, aber informieren)."
                )
            elif rain_pattern["is_sandwiched"] and rain_pattern["max_dry_gap"] < 4:
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
                    first_rain = min(rain_hours)
                    dry_before = [h for h in all_hours_sorted if h < first_rain]
                    if len(dry_before) >= 4:
                        lines.append(
                            f"NIEDERSCHLAG-TREND: ZUNEHMEND — {len(dry_before)} trockene Stunden "
                            f"({dry_before[0]}–{dry_before[-1]}), dann Regen ab {first_rain}. "
                            f"→ Maximal conditional. Frühes Fenster nutzbar, Landung vor {first_rain} planen."
                        )
                    else:
                        lines.append(
                            f"NIEDERSCHLAG-TREND: REGEN BIS ABEND — Letzte Regenstunde: {last_rain}. "
                            f"Kein trockenes Fenster. → not_safe."
                        )
        elif rain_hours:
            if _all_rain_after_window:
                lines.append(
                    f"NIEDERSCHLAG-TREND: NACH FLUGZEIT — Regen erst ab {min(rain_hours)}, "
                    f"nach Ende des Flugfensters ({config.FLIGHT_HOURS_END:02d}:00). "
                    f"Flugfenster trocken. → safety_status NICHT verschlechtern. "
                    f"In hazard_notes['rain'] erwaehnen. rain_safety_rating = 8."
                )
            else:
                lines.append(
                    f"NIEDERSCHLAG-TREND: GANZTÄGIG — Regen in {len(rain_hours)} Stunden. "
                    f"→ not_safe."
                )

        # Gewitter-Trend
        if thunderstorm_in_window_h > 0:
            lines.append(
                f"GEWITTER-TREND: IM FLUGFENSTER — Modell-Gewitter in {thunderstorm_in_window_h}h "
                f"im Flugfenster ({config.FLIGHT_HOURS_START:02d}–{config.FLIGHT_HOURS_END:02d}h). "
                f"DANGER-Niveau. → safety_status mindestens conditional, meist not_safe. "
                f"In hazard_notes['thunderstorm'] und caution_notes erwaehnen."
            )

        # Boeen-Trend (analog Niederschlag-Trend)
        if gust_hours and all_hours_sorted:
            gust_pattern = _detect_gust_trend(gust_hours, all_hours_sorted, gust_danger_hours)
            gust_trend_text = _format_gust_trend_text(gust_pattern, gust_hours)
            if gust_trend_text:
                lines.append(gust_trend_text)

        # Wind-Trend (Boden + Hoehe summiert) — siehe weather_context.py-Sammelstelle
        # weiter oben: aloft_hours enthaelt jetzt auch Bodenwind WARN/DANGER-Stunden.
        if aloft_hours and all_hours_sorted:
            aloft_pattern = _detect_aloft_trend(aloft_hours, all_hours_sorted, aloft_danger_hours_list)
            aloft_trend_text = _format_aloft_trend_text(
                aloft_pattern, aloft_hours,
                danger_kmh=config.WIND_DANGER_KMH,
                warn_kmh=config.WIND_WARN_KMH,
            )
            if aloft_trend_text:
                lines.append(aloft_trend_text)
            # Cache fuer analyzers.py WIND-TREND-Override
            self._ctx_gust_cache[f"{name}|{date_str}"]["aloft_pattern"] = aloft_pattern

        # Föhn-Info anhängen
        lines.append("")
        krit_foehn = spot.get("kritischer_foehn", "Süd")
        lines.append(self._format_foehn_info(
            date_str=date_str,
            kritischer_foehn=krit_foehn,
            cache_key=f"{name}|{date_str}",
        ))

        # Region-Kontext für Streckenflug-Bewertung (TEIL 4)
        lines.append("")
        lines.append(_format_region_context_block(region_analysis_result, spot_region))

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
        region_terrain_zone = get_terrain_zone(elev_ref, rid)

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

        # Stateful Thermik-Berechnung über alle Stunden (Single Source of Truth:
        # gleiche climb_rate / max_height wie im Meteogramm). Siehe
        # _build_single_spot_context für Motivation (Inertia/Encroachment).
        daily_thermals = compute_daily_thermals(
            hourly_data,
            pressure_level_data,
            elev_ref,
            config.PRESSURE_LEVELS,
            region_id=rid,
        )

        sorted_times = sorted(hourly_data.keys())
        has_data = False
        # Hour-Lines werden gepuffert (mit dt.hour-Schluessel) damit das aktive
        # Tagesfenster nach der Schleife herausgeschnitten werden kann (Stunden
        # vor erstem qualifizierenden Fenster weglassen).
        hour_lines: list[tuple[int, str]] = []
        calm_hours = []
        moderate_hours = []
        strong_hours = []
        clean_hours = []
        warned_hours = []
        hourly_winds = {}      # hour_str → Windgeschwindigkeit für Trend-Analyse (Regionen haben keine Böen)
        rain_hours = []        # Stunden mit Niederschlag (innerhalb + nach Flugfenster)
        rain_in_window_h = 0   # Regen-Stunden strikt INNERHALB des Flugfensters
        thunderstorm_in_window_h = 0  # Gewitter-Stunden strikt INNERHALB des Flugfensters
        aloft_hours = []       # Stunden mit ALOFT-WARN/DANGER (fuer HOEHENWIND-TREND, Region)
        aloft_danger_hours_list = []  # Nur [ALOFT-WIND-DANGER] (> WIND_DANGER_KMH)
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
        tq_wind_danger_h = 0
        tq_wind_warn_h = 0
        peak_climb_proxy = 0.0
        productive_thermal_h = 0   # Stunden mit climb>=0.7 + low<=80% + mid<=90% + kein ROUGH-UNUSABLE
        band_too_shallow_h = 0     # Stunden mit climb>=0.7 aber Band zu duenn (<MIN_DEPTH)
        # Rating-Inputs (RATING_CONCEPT v1.5): pre-computed Werte fuer Quality-Matrix.
        # Strengere Schwelle als productive_thermal_h, weil das Rating "echte" Thermik
        # erwartet (≥1.5 m/s), nicht nur die Decision-Schwelle 0.7 m/s.
        _hourly_climbs = []        # alle climb-Werte im Fly-Fenster (fuer sustained Peak)
        productive_h_strict = 0    # Stunden mit climb >= 1.5 m/s + Cloud-OK + kein ROUGH-UNUSABLE
        # Cloud-Akkumulatoren NUR ueber Thermikstunden (climb>=0.3) — fuer Violett-Check.
        cloud_low_sum = 0.0
        cloud_mid_sum = 0.0
        cloud_high_sum = 0.0      # v1.6: fuer cloud_structure-Klassifikation (Cirrus etc.)
        _prod_tops_agl = []       # v1.6: Thermik-Top AGL ueber Stunden mit prod_h_strict
        _prod_climbs = []         # v1.6: climb-Werte waehrend prod_h_strict Stunden (fuer avg)
        strong_h = 0              # v1.6: Stunden mit climb >= 2.0 m/s (starke Thermik)
        # CLOUDS-Sicht-Zaehler (alle Flugstunden) — Region nutzt elev_ref als Referenz.
        cloud_at_or_below_takeoff_h = 0
        cloud_near_takeoff_h = 0
        min_cloud_base_active_h = None
        safety_timeline = []       # (hour_str, klass, label) - SICHERHEITS-VERLAUF (Region)
        fly_timeline = []          # (hour_str, klass, label) - FLIEGBARKEITS-VERLAUF (Region)
        altitude_segment_lines = []  # Pro Stunde eine Hoehen-Safety-Zeile

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
                therm = daily_thermals.get(timestamp)
                if therm and "error" not in therm:
                    h_climb = therm["climb_rate"]
                    if isinstance(h_climb, (int, float)) and h_climb > peak_climb_proxy:
                        peak_climb_proxy = h_climb
                    # Rating v1.5: climb-Verlauf fuer sustained-Peak (Rolling-Min ueber 2h Fenster).
                    _hourly_climbs.append(
                        float(h_climb) if isinstance(h_climb, (int, float)) else 0.0
                    )
                    # h_max_h = FLIEGBARE Thermik-Obergrenze, gecappt bei LCL (Wolkenbasis)
                    # Oberhalb der Wolkenbasis ist VFR-Flug nicht erlaubt → nicht als
                    # fliegbare Thermik zaehlen. Raw-Parcel-Top bleibt in therm["max_height"].
                    thermal_top_raw = therm["max_height"]
                    lcl = therm.get("lcl")
                    if isinstance(thermal_top_raw, (int, float)) and isinstance(lcl, (int, float)):
                        h_max_h = min(thermal_top_raw, lcl)
                    else:
                        h_max_h = thermal_top_raw
                    effective_ceiling = max(effective_ceiling, h_max_h + 1000)
                    lcl_str = f", LCL/Basis {lcl}m" if lcl else ""
                    thermal_info = f" | THERMIK-PROXY: {h_climb} m/s bis {h_max_h}m MSL{lcl_str}"
            except Exception as e:
                thermal_info = f" | Thermik-Fehler: {e}"

            temp = data.get("temperature_2m", "N/A")
            wind_speed_surface = data.get("wind_speed_10m", "N/A")
            wind_dir_surface = data.get("wind_direction_10m", "N/A")
            cloud_base_raw = data.get("cloud_base")
            cloud_base = f"{cloud_base_raw}m" if cloud_base_raw is not None else "wolkenfrei"
            cloud_cover = data.get("cloud_cover", "N/A")
            low_cl = float(data.get("cloud_cover_low") or 0)
            mid_cl = float(data.get("cloud_cover_mid") or 0)
            # Strahlung am Boden — die relevante Groesse fuer Thermik (Mai 2026).
            # Siehe Spot-Context oben fuer ausfuehrliche Begruendung.
            swr_raw = data.get("shortwave_radiation")
            direct_raw = data.get("direct_radiation")
            sun_str = "Strahlung n/a"
            if isinstance(swr_raw, (int, float)):
                if isinstance(direct_raw, (int, float)):
                    sun_str = f"Strahlung {int(round(swr_raw))} W/m² (direkt {int(round(direct_raw))})"
                else:
                    sun_str = f"Strahlung {int(round(swr_raw))} W/m²"
            high_cl = float(data.get("cloud_cover_high") or 0)

            # CLOUDS-Sicht-Aggregation (siehe docs/TAGS.md), Region-Pfad:
            if isinstance(cloud_base_raw, (int, float)):
                if min_cloud_base_active_h is None or cloud_base_raw < min_cloud_base_active_h:
                    min_cloud_base_active_h = cloud_base_raw
                low_mid_cover = low_cl + mid_cl
                if cloud_base_raw <= elev_ref + 100 and low_mid_cover >= 90:
                    cloud_at_or_below_takeoff_h += 1
                elif elev_ref + 100 < cloud_base_raw <= elev_ref + 300 and low_mid_cover >= 75:
                    cloud_near_takeoff_h += 1

            # Regionen: KEINE Böen (Apr 2026 Refactor).
            # Böen sind lokale Spitzenwerte und gehören auf Spot-Ebene.
            # Auf Region-Ebene wird nur der Wind bewertet. Thermik-Zerreiß-
            # Signale kommen aus SHEAR, BS-Ratio und (Phase 2) BL-Mean-Wind.
            pl_data = pressure_level_data.get(timestamp, {})
            wind_speed = wind_speed_surface
            wind_dir = wind_dir_surface
            ref_wind_info = ""

            # Ref-Wind aus Drucklevel-Interpolation: Starker Wind auf
            # Referenzhöhe (auch wenn Boden windstill) zählt für WIND-STRONG.
            ref_ws, ref_wd = _interpolate_wind_at_altitude(pl_data, elev_ref, config.PRESSURE_LEVELS)
            if ref_ws is not None and isinstance(wind_speed_surface, (int, float)):
                if ref_ws > wind_speed_surface:
                    wind_speed = ref_ws
                    if ref_wd is not None:
                        wind_dir = ref_wd
                ref_wind_info = f" [Ref-Wind {elev_ref}m: {ref_ws:.0f}km/h"
                if ref_wd is not None:
                    ref_wind_info += f" aus {ref_wd:.0f}°"
                ref_wind_info += "]"
            elif ref_ws is not None:
                wind_speed = ref_ws
                wind_dir = ref_wd if ref_wd is not None else "N/A"
                ref_wind_info = f" [Ref-Wind {elev_ref}m: {ref_ws:.0f}km/h]"

            # Wind-Staerke Tags (basierend auf effektivem Wind = max aus Boden und Referenzhoehe)
            # Regionen haben keine Böen, Klassifikation nur aus wind_speed.
            hour_str = f"{dt.hour:02d}:00"
            if isinstance(wind_speed, (int, float)):
                hourly_winds[hour_str] = wind_speed
                if wind_speed > config.WIND_DANGER_KMH:
                    wind_status = "[WIND-DANGER]"
                    strong_hours.append(hour_str)
                elif wind_speed > config.WIND_WARN_KMH:
                    wind_status = "[WIND-WARN]"
                    moderate_hours.append(hour_str)
                else:
                    wind_status = "[WIND-CALM]"
                    calm_hours.append(hour_str)
            else:
                wind_status = "[WIND-CALM]"
                calm_hours.append(hour_str)

            warnings = []

            try:
                precip = data.get("precipitation")
                if isinstance(precip, (int, float)) and precip > 0:
                    warnings.append("[RAIN-WARN]")
                    rain_hours.append(hour_str)
                    rain_in_window_h += 1
            except Exception:
                pass

            # Hoehenwind (Regionen: ohne Böen).
            alt_wind_info = ""
            aloft_warn = False
            aloft_danger = False
            display_levels_out = None

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
                    # Regionen: kein Böen-Höhenprofil.
                    # Nur wind_speed + wind_direction pro Drucklevel.
                    display_levels_out = display_levels
                    for lv in display_levels_out:
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
                        wd_val = lv.get("wind_direction")
                        dir_str = f" aus {wd_val:.0f}°" if wd_val is not None else ""
                        alt_wind_info += f" | {lv['pressure']}hPa({int(alt)}m){marker}: {ws_val:.0f}km/h{dir_str}"

                    # ALOFT-Tag-Trigger: interpoliertes W(z) im Flugband.
                    # Realistisches Band = elev_ref bis Thermik-Top + 300m
                    # (statt +1000m). Verhindert false-positives durch PL-
                    # Spikes weit ueber dem Thermik-Top, die im Meteogramm
                    # nicht sichtbar sind. Fallback elev_ref+1000m falls
                    # keine Thermik (entspricht altem Verhalten).
                    if h_max_h and h_max_h > 0:
                        real_ceiling = h_max_h + 300
                    else:
                        real_ceiling = effective_ceiling
                    max_w, _ = _check_aloft_in_band(
                        display_levels_out,
                        elev_ref,
                        real_ceiling,
                        has_gusts=False,
                    )
                    if max_w is not None:
                        if max_w > config.WIND_DANGER_KMH:
                            aloft_danger = True
                        elif max_w > config.WIND_WARN_KMH:
                            aloft_warn = True

            if aloft_danger:
                warnings.append("[ALOFT-WIND-DANGER]")
                aloft_hours.append(hour_str)
                aloft_danger_hours_list.append(hour_str)
            elif aloft_warn:
                warnings.append("[ALOFT-WIND-WARN]")
                aloft_hours.append(hour_str)

            # Wind-Trend (Region): Bodenwind-Tags auch in aloft_hours summieren,
            # damit der Trend Boden + Hoehe gemeinsam abbildet.
            if wind_status == "[WIND-DANGER]":
                if hour_str not in aloft_hours:
                    aloft_hours.append(hour_str)
                if hour_str not in aloft_danger_hours_list:
                    aloft_danger_hours_list.append(hour_str)
            elif wind_status == "[WIND-WARN]":
                if hour_str not in aloft_hours:
                    aloft_hours.append(hour_str)

            try:
                cape = data.get("cape")
                if isinstance(cape, (int, float)) and cape > config.CAPE_WARN_JKG:
                    # CAPE-DANGER (hart): extreme Instabilitaet oder CAPE + Regen (aktive Ueberentwicklung)
                    # CAPE-WARN (soft): Potenzial vorhanden, aber kein Trigger → conditional
                    if cape > config.CAPE_DANGER_JKG or "[RAIN-WARN]" in warnings:
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

            # Thermik-Qualitaets-Tags (Scherung / Zerrissenheit).
            # Regionen: keine Böen → keine ROUGH-Tags, nur SHEAR + TORN.
            # WICHTIG: Immer echten 10m-Bodenwind verwenden, NICHT den
            # effektiven wind_speed (kann Hoehenwind enthalten).
            # Scherung = Windaenderung mit Hoehe, braucht echten Surface-Anker.
            tq_info = ""
            try:
                quality_tags, quality_debug = self._thermal_quality_tags(
                    wind_speed_10m=wind_speed_surface,
                    wind_gusts_10m=None,
                    pl_data=pl_data,
                    elevation_m=elev_ref,
                    thermal_top_m=h_max_h,
                    climb_rate_ms=h_climb,
                    region_id=rid,
                    altitude_gusts=None,
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
                cloud_low_sum += low_cl
                cloud_mid_sum += mid_cl
                cloud_high_sum += high_cl  # v1.6 fuer cloud_structure-Klassifikation
                tq_tags_this_hour = {t for t in warnings if t.startswith(("[SHEAR-", "[THERMAL-TORN-", "[THERMAL-ROUGH-", "[THERMAL-WIND-"))}
                # THERMAL-ROUGH-UNUSABLE (mechanische Klapper-Gefahr, nur Spots) ODER
                # THERMAL-WIND-UNUSABLE (Grundwind zu stark, Blase organisiert sich nicht,
                # Research 3.1) blockieren den Produktiv-Zaehler. FRAGMENTED ist "zu schwach,
                # nicht gefaehrlich" — gehoert damit nicht in den Gefahren-Topf.
                # SHEAR/TORN bleiben reine Qualitaets-Issues (Bart schwer zentrierbar,
                # aber Thermik existiert) und blockieren produktive Stunden nicht.
                rough_unusable_this_hour = (
                    "[THERMAL-ROUGH-UNUSABLE]" in tq_tags_this_hour
                    or "[THERMAL-WIND-UNUSABLE]" in tq_tags_this_hour
                )
                # Bewoelkung wird NICHT mehr als Productivity-Gate verwendet (Mai 2026).
                # Siehe ausfuehrliche Begruendung im Spot-Loop oben (~Zeile 1789).
                # Kurz: climb_rate ist bereits strahlungsabgeleitet (H aus direct/diffuse) →
                # zusaetzlicher Cloud-Gate waere Doppelbestrafung der eigenen Berechnung.
                band_depth_r = (h_max_h - elev_ref) if isinstance(h_max_h, (int, float)) else 0
                _min_band_r = min_band_depth(h_climb, region_terrain_zone)
                band_usable_r = band_depth_r >= _min_band_r
                if (h_climb >= config.PRODUCTIVE_CLIMB_MIN
                        and not rough_unusable_this_hour
                        and band_usable_r):
                    productive_thermal_h += 1
                elif (h_climb >= config.PRODUCTIVE_CLIMB_MIN
                        and not rough_unusable_this_hour
                        and not band_usable_r):
                    band_too_shallow_h += 1
                # Rating-Input v1.5 (Bug-Fix Mai 2026): strenge Produktivitaets-Schwelle
                # (≥1.5 m/s) wurde im Region-Loop bisher nie inkrementiert — daher hatten
                # alle Regionen permanent productive_h_strict=0 und working_height_agl_m=0,
                # was das Skill-Rating fuer Regionen blind machte. Hier analog zum Spot-Loop
                # nachgezogen (siehe ~Zeile 1810-1828).
                if (h_climb >= 1.5
                        and not rough_unusable_this_hour
                        and band_usable_r):
                    productive_h_strict += 1
                    _prod_climbs.append(float(h_climb))
                    # Thermik-Top AGL fuer working_height-Median tracken.
                    # h_max_h ist MSL (bereits LCL-gecappt). AGL = MSL - elev_ref.
                    if isinstance(h_max_h, (int, float)):
                        _agl = max(0, h_max_h - elev_ref)
                        _prod_tops_agl.append(_agl)
                # v1.6: zusaetzlich Stunden mit starker Thermik (≥2.0 m/s) zaehlen
                if h_climb >= 2.0 and not rough_unusable_this_hour and band_usable_r:
                    strong_h += 1
                if not tq_tags_this_hour:
                    thermal_clean_h += 1
                else:
                    # Nur echtes UNUSABLE als Gefahrenzaehler; FRAGMENTED als eigener Warn-Zaehler.
                    if "[THERMAL-ROUGH-UNUSABLE]" in tq_tags_this_hour:
                        tq_rough_danger_h += 1
                    elif "[THERMAL-ROUGH-FRAGMENTED]" in tq_tags_this_hour:
                        tq_rough_warn_h += 1
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
                    if "[THERMAL-WIND-UNUSABLE]" in tq_tags_this_hour:
                        tq_wind_danger_h += 1
                    elif "[THERMAL-WIND-DEGRADED]" in tq_tags_this_hour:
                        tq_wind_warn_h += 1

            warning_str = " " + " ".join(warnings) if warnings else ""

            # Tag-Histogram für Tagesprofil
            for w in warnings:
                tag_counts[w] = tag_counts.get(w, 0) + 1
            if "[THUNDERSTORM]" in warnings:
                thunderstorm_in_window_h += 1
            if wind_status == "[WIND-DANGER]":
                tag_counts["[WIND-DANGER]"] = tag_counts.get("[WIND-DANGER]", 0) + 1
            elif wind_status == "[WIND-WARN]":
                tag_counts["[WIND-WARN]"] = tag_counts.get("[WIND-WARN]", 0) + 1

            # ─── SICHERHEITS-VERLAUF (Region) ───
            # Regionen haben keine Böen → keine GUST-*/ALOFT-GUST-* Tags möglich.
            safety_hard_r = {"[ALOFT-WIND-DANGER]",
                             "[RAIN-WARN]", "[CAPE-DANGER]", "[THUNDERSTORM]",
                             "[WIND-DANGER]", "[OVERCAST-DANGER]"}
            safety_warn_r = {"[ALOFT-WIND-WARN]", "[CAPE-WARN]"}
            s_hard_r = [t for t in warnings if t in safety_hard_r]
            s_warn_r = [t for t in warnings if t in safety_warn_r]
            if wind_status == "[WIND-DANGER]" and "[WIND-DANGER]" not in s_hard_r:
                s_hard_r.append("[WIND-DANGER]")
            if s_hard_r:
                s_klass_r = "danger"
                s_label_r = "DANGER(" + "+".join(t.strip("[]").replace("-WARN", "").replace("-DANGER", "") for t in s_hard_r) + ")"
            elif s_warn_r or wind_status == "[WIND-WARN]":
                s_klass_r = "warn"
                bits = [t.strip("[]").replace("-WARN", "").replace("-DANGER", "") for t in s_warn_r]
                if wind_status == "[WIND-WARN]" and "WIND" not in bits:
                    bits.append("WIND")
                s_label_r = "WARN(" + "+".join(bits) + ")" if bits else "WARN"
            else:
                s_klass_r = "clean"
                s_label_r = "clean"
            safety_timeline.append((hour_str, s_klass_r, s_label_r))

            # ─── FLIEGBARKEITS-VERLAUF (Region) ───
            tq_tags_r = {t for t in warnings if t.startswith(("[SHEAR-", "[THERMAL-TORN-", "[THERMAL-ROUGH-", "[THERMAL-WIND-"))}
            unusable_r = [t for t in tq_tags_r if t.endswith("-UNUSABLE]")]
            fragmented_r = [t for t in tq_tags_r if t.endswith("-FRAGMENTED]")]
            degraded_r = [t for t in tq_tags_r if t.endswith("-DEGRADED]")]
            has_thermal_r = isinstance(h_climb, (int, float)) and h_climb >= config.THERMAL_QUALITY_MIN_CLIMB
            # Bewoelkung NICHT mehr im Productivity-Check (Mai 2026, siehe Begruendung im
            # Spot-Loop oben): climb_rate ist strahlungsabgeleitet → kein Cloud-Doppelgate.
            _min_band_r_tl = min_band_depth(h_climb, region_terrain_zone)
            is_productive_r = (
                has_thermal_r
                and h_climb >= config.PRODUCTIVE_CLIMB_MIN
                and "[THERMAL-ROUGH-UNUSABLE]" not in unusable_r
                and "[THERMAL-WIND-UNUSABLE]" not in unusable_r
                and isinstance(h_max_h, (int, float))
                and (h_max_h - elev_ref) >= _min_band_r_tl
            )
            if not has_thermal_r:
                f_klass_r = "keine-thermik"
                f_label_r = "keine-thermik"
            elif unusable_r:
                f_klass_r = "unusable"
                f_label_r = "UNUSABLE(" + "+".join(t.strip("[]").replace("THERMAL-", "").replace("-UNUSABLE", "") for t in unusable_r) + ")"
            elif is_productive_r:
                f_klass_r = "produktiv"
                f_label_r = f"produktiv({h_climb:.1f})"
            elif fragmented_r or degraded_r:
                # FRAGMENTED = schwache Thermik (eigene Kategorie, kein UNUSABLE-Gefahr)
                f_klass_r = "degraded"
                parts_r = [t.strip("[]").replace("THERMAL-", "").replace("-FRAGMENTED", "-FRAG") for t in fragmented_r]
                parts_r += [t.strip("[]").replace("THERMAL-", "").replace("-DEGRADED", "") for t in degraded_r]
                f_label_r = "degraded(" + "+".join(parts_r) + ")"
            else:
                # "wolken" als Ablehnungsgrund entfaellt — Wolken sind kein Productivity-Gate mehr.
                reason_r = []
                if isinstance(h_max_h, (int, float)) and (h_max_h - elev_ref) < _min_band_r_tl:
                    reason_r.append("band-flach")
                if h_climb < config.PRODUCTIVE_CLIMB_MIN:
                    reason_r.append("schwach")
                f_klass_r = "soaring"
                f_label_r = "soaring(" + "+".join(reason_r) + ")" if reason_r else "soaring"
            fly_timeline.append((hour_str, f_klass_r, f_label_r))

            # ─── HOEHEN-SEGMENTE (Region) ───
            if display_levels_out:
                seg_parts_r = []
                any_warn_r = False
                for lv in display_levels_out:
                    alt = lv["altitude"]
                    if not (elev_ref <= alt <= effective_ceiling):
                        continue
                    ws_val = lv["wind_speed"]
                    if ws_val > config.WIND_DANGER_KMH:
                        cls = "DANGER"
                        any_warn_r = True
                    elif ws_val > config.WIND_WARN_KMH:
                        cls = "WARN"
                        any_warn_r = True
                    else:
                        cls = "OK"
                    seg_parts_r.append(f"{int(alt)}m:{cls}")
                if seg_parts_r and any_warn_r:
                    top_str_r = f"{int(h_max_h)}m" if isinstance(h_max_h, (int, float)) else "?"
                    altitude_segment_lines.append(
                        f"{hour_str} | Band {elev_ref}-{int(effective_ceiling)}m (Thermik-Top {top_str_r}): "
                        + " · ".join(seg_parts_r)
                    )

            # Klassifiziere saubere vs. gewarnte Stunden
            # Regionen: keine GUST-/ALOFT-GUST-Tags in hard_warnings.
            hard_warnings = {"[ALOFT-WIND-DANGER]", "[RAIN-WARN]", "[CAPE-DANGER]", "[THUNDERSTORM]", "[WIND-DANGER]", "[OVERCAST-DANGER]"}
            has_hard_warn = bool(hard_warnings & set(warnings)) or wind_status == "[WIND-DANGER]"
            if not has_hard_warn:
                clean_hours.append(hour_str)
            else:
                warned_hours.append(hour_str)

            # Wind-Werte formatieren (koennen Floats sein nach Interpolation)
            ws_fmt = f"{wind_speed:.0f}" if isinstance(wind_speed, float) else str(wind_speed)
            wd_fmt = f"{wind_dir:.0f}" if isinstance(wind_dir, float) else str(wind_dir)

            # WIND-CALM ist intern, wird nicht als Tag gezeigt (= keine Tags = ruhig).
            wind_status_print = "" if wind_status == "[WIND-CALM]" else f" {wind_status}"
            hour_lines.append((
                dt.hour,
                f"{time_str}: Temp {temp}°C | Wind {ws_fmt}km/h aus {wd_fmt}°{wind_status_print}{ref_wind_info}{warning_str} | "
                f"Wolkenbasis {cloud_base} | Bewoelkung {cloud_cover}% (tief {low_cl:.0f}%, mittel {mid_cl:.0f}%, hoch {high_cl:.0f}%) | {sun_str} | FLUGBEREICH: {elev_ref}–{effective_ceiling}m MSL{alt_wind_info}{thermal_info}{tq_info}"
            ))

        if not has_data:
            return ""

        # ─── Aktives Tagesfenster bestimmen + Stunden-Slicing ───
        # Wie im Spot-Builder: Stunden vor dem ersten qualifizierenden Fenster
        # (>= CLEAN_WINDOW_MIN_HOURS sauber) weglassen, transparenter Header.
        active_start = _determine_active_window_start(
            clean_hours, config.CLEAN_WINDOW_MIN_HOURS
        )

        if active_start is not None and active_start > config.FLIGHT_HOURS_START:
            kept_lines = [s for h, s in hour_lines if h >= active_start]
            skipped_until = active_start - 1
            lines.append("")
            lines.append("═══ TAGESFENSTER ═══")
            lines.append(
                f"Tag aktiv ab {active_start:02d}:00 (erstes Fenster "
                f">= {config.CLEAN_WINDOW_MIN_HOURS}h ohne harte Warnungen)."
            )
            lines.append(
                f"Stunden {config.FLIGHT_HOURS_START:02d}:00-{skipped_until:02d}:00 "
                f"weggelassen: harte Warnungen (z.B. Wind > {config.WIND_DANGER_KMH} km/h, "
                f"Regen, Gewitter). Kein Datenfehler — diese Stunden waren nicht nutzbar."
            )
            lines.append("")
            lines.extend(kept_lines)
        else:
            lines.extend(s for _h, s in hour_lines)

        # Fenster-Info fuer LLM-Narrative (kompakt — Filter bereits oben passiert).
        longest_clean_run_region = _longest_consecutive_run(clean_hours)
        clean_windows_region_fmt = _format_clean_windows(clean_hours)
        lines.append("")
        lines.append("═══ FENSTER-INFO (fuer summary/caution_notes) ═══")
        lines.append(f"Saubere Fenster (kein DANGER): {clean_windows_region_fmt}")
        lines.append(f"Laengstes Fenster: {longest_clean_run_region}h")
        if warned_hours:
            lines.append(
                f"Stunden mit harten Warnungen ({len(warned_hours)}): "
                f"{', '.join(warned_hours)} (gehoeren NICHT ins safe_window)"
            )

        # Cache fuer deterministische Flyability-Override
        # rough_danger_h = NUR THERMAL-ROUGH-UNUSABLE → echter gray-Trigger.
        # FRAGMENTED bedeutet "Thermik zu schwach, nicht gefaehrlich" (siehe config.py)
        # und zaehlt daher in tq_rough_warn_h (wie DEGRADED), nicht in danger_h.
        # tq_danger_h bleibt Summe aller UNUSABLE fuer Text-Hinweise.
        # Rain-Sandwich-Erkennung fuer Region-Override + NIEDERSCHLAG-TREND
        all_hours_sorted_region = sorted(hourly_winds.keys()) or sorted(set(calm_hours + moderate_hours + strong_hours))
        rain_pattern = _detect_rain_sandwich(rain_hours, all_hours_sorted_region)

        self._ctx_cache_put(self._ctx_tq_cache, f"{rname}|{date_str}", {
            "thermal_hours_total": thermal_hours_total,
            "tq_danger_h": tq_rough_danger_h + tq_torn_danger_h + tq_shear_danger_h + tq_wind_danger_h,
            "rough_danger_h": tq_rough_danger_h,
            "wind_danger_h": tq_wind_danger_h,
            "peak_climb_proxy": peak_climb_proxy,
            "productive_thermal_h": productive_thermal_h,
            "productive_h_strict": productive_h_strict,
            "sustained_peak_mps": _compute_sustained_peak(_hourly_climbs, window=2),
            "working_height_agl_m": round(_median(_prod_tops_agl)) if _prod_tops_agl else 0,
            "cloud_structure": _classify_cloud_structure(
                (cloud_low_sum / thermal_hours_total) if thermal_hours_total > 0 else 0.0,
                (cloud_mid_sum / thermal_hours_total) if thermal_hours_total > 0 else 0.0,
                (cloud_high_sum / thermal_hours_total) if thermal_hours_total > 0 else 0.0,
            ),
            "avg_low_cloud_thermal_h": (cloud_low_sum / thermal_hours_total) if thermal_hours_total > 0 else 0.0,
            "avg_mid_cloud_thermal_h": (cloud_mid_sum / thermal_hours_total) if thermal_hours_total > 0 else 0.0,
            "band_too_shallow_h": band_too_shallow_h,
            "clean_hours_count": len(clean_hours),
            "rain_sandwiched": rain_pattern["is_sandwiched"],
            "max_dry_gap": rain_pattern["max_dry_gap"],
            "rain_cnt": len(rain_hours),
        })

        # Region-Aloft-Cache (Wind-only, keine Böen) für ALOFT-Override in
        # _post_process_safety_region. Regionen haben keine GUST-Tags mehr,
        # der Cache enthält nur wind-basierte Höhenwind-Zähler.
        # aloft_pattern: trend-aware Klassifikation (AUFKLAERUNG / EINGEKESSELT / ...),
        # damit der Override sauberes Nachmittagsfenster nicht killt (Bug Apr 2026).
        aloft_pattern_region = None
        if aloft_hours and all_hours_sorted_region:
            aloft_pattern_region = _detect_aloft_trend(
                aloft_hours, all_hours_sorted_region, aloft_danger_hours_list
            )
        # Aktives Tagesfenster fuer Region (analog Spot — Pre-Filter und
        # Konsistenz-Check zwischen Code-Slicing und LLM-Sicht).
        active_window_start_region = _determine_active_window_start(
            clean_hours, config.CLEAN_WINDOW_MIN_HOURS
        )
        self._ctx_cache_put(self._ctx_gust_cache, f"{rname}|{date_str}", {
            "aloft_warn_hours": tag_counts.get("[ALOFT-WIND-WARN]", 0),
            "aloft_danger_hours": tag_counts.get("[ALOFT-WIND-DANGER]", 0),
            "aloft_pattern": aloft_pattern_region,
            "active_window_start": active_window_start_region,
            "clean_hours_count": len(clean_hours),
            "longest_clean_run_hours": longest_clean_run_region,
            "rain_hours": len(rain_hours),
            "rain_in_window_h": rain_in_window_h,
            "rain_hour_list": rain_hours,
            "thunderstorm_hours": tag_counts.get("[THUNDERSTORM]", 0),
            "thunderstorm_in_window_h": thunderstorm_in_window_h,
            # CLOUDS-Sicht (siehe docs/TAGS.md), Region nutzt elev_ref:
            "elevation_m": elev_ref,
            "cloud_at_or_below_takeoff_h": cloud_at_or_below_takeoff_h,
            "cloud_near_takeoff_h": cloud_near_takeoff_h,
            "min_cloud_base_active_h": min_cloud_base_active_h,
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
            # Regionen haben keine Böen → keine GUST-*/ALOFT-GUST-*/THERMAL-ROUGH-* Tags.
            # THERMAL-WIND-* ersetzen ROUGH-* auf Region-Ebene (BL-Mean-Wind statt GF).
            major_tags_order = [
                "[ALOFT-WIND-DANGER]",
                "[WIND-DANGER]", "[RAIN-WARN]", "[CAPE-DANGER]", "[CAPE-WARN]", "[THUNDERSTORM]", "[OVERCAST-DANGER]",
                "[SHEAR-UNUSABLE]", "[THERMAL-TORN-UNUSABLE]", "[THERMAL-WIND-UNUSABLE]",
                "[ALOFT-WIND-WARN]",
                "[SHEAR-DEGRADED]", "[THERMAL-TORN-DEGRADED]", "[THERMAL-WIND-DEGRADED]",
                "[WIND-WARN]",
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

        # ─── SICHERHEITS-VERLAUF (Region) ───
        # Filterung wie im Spot-Builder: Verlaeufe nur ab Tagesbeginn zeigen.
        def _filter_timeline_entries_region(timeline):
            if active_start is None or active_start <= config.FLIGHT_HOURS_START:
                return timeline
            return [(h, k, l) for (h, k, l) in timeline if int(h.split(":")[0]) >= active_start]

        safety_timeline_filtered = _filter_timeline_entries_region(safety_timeline)
        fly_timeline_filtered = _filter_timeline_entries_region(fly_timeline)

        if safety_timeline_filtered:
            lines.append("")
            lines.append("═══ SICHERHEITS-VERLAUF (Wind/Boeen/Regen/CAPE/Gewitter — beeinflusst safety_status) ═══")
            seq_parts = [f"{h}:{lbl}" for (h, _k, lbl) in safety_timeline_filtered]
            lines.append(" · ".join(seq_parts))
            lines.append(
                "→ Erkenne Trends und eingekesselte Stunden (gute Stunde zwischen "
                "zwei gefaehrlichen = NICHT als stabiles Fenster werten)."
            )

        # ─── FLIEGBARKEITS-VERLAUF (Region) ───
        if fly_timeline_filtered:
            lines.append("")
            lines.append("═══ FLIEGBARKEITS-VERLAUF (Thermik-Qualitaet — beeinflusst fly_status, NICHT safety) ═══")
            seq_parts_f = [f"{h}:{lbl}" for (h, _k, lbl) in fly_timeline_filtered]
            lines.append(" · ".join(seq_parts_f))
            lines.append(
                "→ produktiv = nutzbare Thermik · soaring = nur Hangsoaring moeglich · "
                "degraded = ruppig aber fliegbar · unusable = Thermik unbrauchbar (Klapper/Scherung) · "
                "keine-thermik = kein Steigen."
            )

        # ─── HOEHEN-SEGMENTE (Region) ───
        if altitude_segment_lines:
            lines.append("")
            lines.append("═══ HOEHEN-SEGMENTE im Flugbereich (Gefahr nach Hoehe, Safety) ═══")
            for seg_line in altitude_segment_lines:
                lines.append(seg_line)
            lines.append(
                "→ DANGER/WARN im Flugbereich = relevante Sicherheits-Gefahr. Pruefe, ob die "
                "gefaehrliche Hoehe im genutzten Kurbelband liegt (Referenzhoehe bis Thermik-Top)."
            )

        # ─── THERMIK-QUALITÄT: Zusammenfassung für LLM (analog BÖEN-FLOOR) ───
        if thermal_hours_total > 0:
            tq_danger_h = tq_rough_danger_h + tq_torn_danger_h + tq_shear_danger_h + tq_wind_danger_h
            tq_warn_h = tq_rough_warn_h + tq_torn_warn_h + tq_shear_warn_h + tq_wind_warn_h
            tq_parts = []
            if tq_rough_danger_h:
                tq_parts.append(f"ROUGH-UNUSABLE {tq_rough_danger_h}h")
            if tq_torn_danger_h:
                tq_parts.append(f"TORN-UNUSABLE {tq_torn_danger_h}h")
            if tq_shear_danger_h:
                tq_parts.append(f"SHEAR-UNUSABLE {tq_shear_danger_h}h")
            if tq_wind_danger_h:
                tq_parts.append(f"WIND-UNUSABLE {tq_wind_danger_h}h")
            if tq_rough_warn_h:
                tq_parts.append(f"ROUGH-DEGRADED {tq_rough_warn_h}h")
            if tq_torn_warn_h:
                tq_parts.append(f"TORN-DEGRADED {tq_torn_warn_h}h")
            if tq_shear_warn_h:
                tq_parts.append(f"SHEAR-DEGRADED {tq_shear_warn_h}h")
            if tq_wind_warn_h:
                tq_parts.append(f"WIND-DEGRADED {tq_wind_warn_h}h")
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
            if tq_wind_danger_h > 0:
                wind_pct = round(100 * tq_wind_danger_h / thermal_hours_total)
                lines.append(
                    f"  WIND-UNUSABLE in {tq_wind_danger_h}h ({wind_pct}%): Mittlerer BL-Wind "
                    f"ueber Danger-Schwelle — Thermikblase kann sich nicht organisiert "
                    f"abloesen. Zaehlt WIE ROUGH-UNUSABLE in den Produktiv-Zaehler "
                    f"(blockiert green/violet). Der Tag wird dadurch gray (Abgleiter, falls "
                    f"Soaring moeglich) — KEIN Einfluss auf safety_status."
                )
        else:
            lines.append(
                "→ THERMIK-QUALITÄT (NUR Fliegbarkeit/Phase 2, NICHT Sicherheit!): "
                "KEINE THERMIK-STUNDEN — Peak-Steigen (Proxy): 0.0 m/s. "
                "Kein nutzbarer Aufwind im gesamten Flugfenster. fly_status = gray (Abgleiter)."
            )

        # ─── PRODUKTIVE-THERMIK: Stunden mit Climb + ausreichend Band ───
        if thermal_hours_total > 0:
            _sust_peak = _compute_sustained_peak(_hourly_climbs, window=2)
            lines.append(
                f"→ PRODUKTIVE-THERMIK: {productive_thermal_h}h "
                f"(Climb ≥{config.PRODUCTIVE_CLIMB_MIN} m/s, ausreichendes Höhenband, "
                f"kein ROUGH-UNUSABLE, kein WIND-UNUSABLE). "
                f"Min für green-Tag: {config.PRODUCTIVE_HOURS_FOR_GREEN}h. "
                f"HINWEIS: Bewoelkungs-% sind KEIN Productivity-Gate mehr (Mai 2026) — "
                f"die Sonnen-Daempfung steckt bereits in climb_rate ueber die strahlungs"
                f"basierte H-Berechnung. TORN-/SHEAR-UNUSABLE und ROUGH-FRAGMENTED zaehlen "
                f"MIT (Bart-Zentrierung schwieriger bzw. schwache Thermik, aber fliegbar)."
            )
            # Rating-Inputs (RATING_CONCEPT v1.6): explizit fuer Kategorien-Wahl.
            _wh = round(_median(_prod_tops_agl)) if _prod_tops_agl else 0
            _avg_climb_prod = round(sum(_prod_climbs) / len(_prod_climbs), 1) if _prod_climbs else 0.0
            _avg_low = (cloud_low_sum / thermal_hours_total) if thermal_hours_total > 0 else 0.0
            _avg_mid = (cloud_mid_sum / thermal_hours_total) if thermal_hours_total > 0 else 0.0
            _avg_high = (cloud_high_sum / thermal_hours_total) if thermal_hours_total > 0 else 0.0
            _cloud_struct = _classify_cloud_structure(_avg_low, _avg_mid, _avg_high)
            lines.append(
                f"→ RATING-INPUTS: prod_h_strict={productive_h_strict}h (Climb ≥1.5 m/s), "
                f"strong_h={strong_h}h (Climb ≥2.0 m/s), "
                f"avg_climb_prod={_avg_climb_prod:.1f} m/s (Durchschnitt waehrend prod_h_strict), "
                f"sustained_peak={_sust_peak:.1f} m/s (max über 2h, kein Einzelspike), "
                f"working_height_agl={_wh}m (Median Thermik-Top ueber produktive Stunden), "
                f"cloud_structure={_cloud_struct} "
                f"(tief={_avg_low:.0f}% mittel={_avg_mid:.0f}% hoch={_avg_high:.0f}%). "
                f"Diese Werte nutzt die Kategorien-Wahl direkt — nicht selbst nachzaehlen."
            )

            # ─── VIOLETT-Kandidat-Check (XC-Tag) ───
            # Nur Hint anzeigen wenn ALLE harten Schwellen erfuellt. LLM entscheidet final.
            avg_low = cloud_low_sum / thermal_hours_total
            avg_mid = cloud_mid_sum / thermal_hours_total
            _unusable_pct = 100.0 * tq_danger_h / thermal_hours_total
            _rough_pct = 100.0 * tq_rough_danger_h / thermal_hours_total
            _is_violet_candidate = (
                peak_climb_proxy >= config.VIOLET_PEAK_MIN
                and productive_thermal_h >= config.VIOLET_HOURS_MIN
                and _rough_pct < config.VIOLET_ROUGH_MAX
                and _unusable_pct < config.VIOLET_UNUSABLE_MAX
                and avg_low <= config.VIOLET_CLOUD_LOW_MAX
                and avg_mid <= config.VIOLET_CLOUD_MID_MAX
            )
            if _is_violet_candidate:
                lines.append(
                    f"→ VIOLETT-Kandidat: Peak {peak_climb_proxy:.1f} m/s, "
                    f"produktiv {productive_thermal_h}h, ROUGH {_rough_pct:.0f}%, "
                    f"UNUSABLE {_unusable_pct:.0f}%, Ø tief {avg_low:.0f}%, Ø mittel {avg_mid:.0f}%. "
                    f"Alle Violett-Schwellen erfüllt (Peak≥{config.VIOLET_PEAK_MIN}, "
                    f"prod≥{config.VIOLET_HOURS_MIN}h, ROUGH<{config.VIOLET_ROUGH_MAX}%, "
                    f"UNUSABLE<{config.VIOLET_UNUSABLE_MAX}%, Ø tief≤{config.VIOLET_CLOUD_LOW_MAX}%, "
                    f"Ø mittel≤{config.VIOLET_CLOUD_MID_MAX}% — optimale Cu-Zone, keine Altostratus-Dämpfung). "
                    f"fly_status = violet erlaubt (nur wenn Rating≥{config.VIOLET_RATING_MIN} — Decision-Engine setzt final)."
                )

        # Wind-Trend nach dem sauberen Fenster (Regionen: Windgeschwindigkeit statt Böen)
        trend = _compute_wind_trend(
            clean_hours, hourly_winds,
            value_label="Wind", danger_threshold=30,
        )
        if trend:
            lines.append(trend)

        # Niederschlag-Trend (all_hours_sorted_region bereits oben berechnet)
        _all_rain_after_window_r = (
            rain_hours
            and rain_in_window_h == 0
            and all(int(h.split(":")[0]) >= config.FLIGHT_HOURS_END for h in rain_hours)
        )
        if rain_hours and all_hours_sorted_region:
            if _all_rain_after_window_r:
                lines.append(
                    f"NIEDERSCHLAG-TREND: NACH FLUGZEIT — Regen erst ab {min(rain_hours)}, "
                    f"nach Ende des Flugfensters ({config.FLIGHT_HOURS_END:02d}:00). "
                    f"Flugfenster selbst bleibt trocken. Kein Sicherheitsmalus fuer das Fenster. "
                    f"→ safety_status NICHT verschlechtern wegen Regen nach Flugzeit. "
                    f"In hazard_notes['rain'] PFLICHT erwaehnen: 'NACH-FLUGZEIT — Regen ab "
                    f"{min(rain_hours)}, nach Flugabschluss. Flugfenster unberührt.' "
                    f"rain_safety_rating = 8 (kein Einfluss aufs Fenster, aber informieren)."
                )
            elif rain_pattern["is_sandwiched"] and rain_pattern["max_dry_gap"] < 4:
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
                    first_rain = min(rain_hours)
                    dry_before = [h for h in all_hours_sorted_region if h < first_rain]
                    if len(dry_before) >= 4:
                        lines.append(
                            f"NIEDERSCHLAG-TREND: ZUNEHMEND — {len(dry_before)} trockene Stunden "
                            f"({dry_before[0]}–{dry_before[-1]}), dann Regen ab {first_rain}. "
                            f"→ Maximal conditional. Fruehes Fenster nutzbar, Landung vor {first_rain} planen."
                        )
                    else:
                        lines.append(
                            f"NIEDERSCHLAG-TREND: REGEN BIS ABEND — Letzte Regenstunde: {last_rain}. "
                            f"Kein trockenes Fenster. → not_safe."
                        )
        elif rain_hours:
            if _all_rain_after_window_r:
                lines.append(
                    f"NIEDERSCHLAG-TREND: NACH FLUGZEIT — Regen erst ab {min(rain_hours)}, "
                    f"nach Ende des Flugfensters ({config.FLIGHT_HOURS_END:02d}:00). "
                    f"Flugfenster trocken. → safety_status NICHT verschlechtern. "
                    f"In hazard_notes['rain'] erwaehnen. rain_safety_rating = 8."
                )
            else:
                lines.append(
                    f"NIEDERSCHLAG-TREND: GANZTAEGIG — Regen in {len(rain_hours)} Stunden. "
                    f"→ not_safe."
                )

        # Gewitter-Trend (Region)
        if thunderstorm_in_window_h > 0:
            lines.append(
                f"GEWITTER-TREND: IM FLUGFENSTER — Modell-Gewitter in {thunderstorm_in_window_h}h "
                f"im Flugfenster ({config.FLIGHT_HOURS_START:02d}–{config.FLIGHT_HOURS_END:02d}h). "
                f"DANGER-Niveau. → safety_status mindestens conditional, meist not_safe. "
                f"In hazard_notes['thunderstorm'] und caution_notes erwaehnen."
            )

        # Hoehenwind-Trend (analog Boeen-Trend in Spots)
        if aloft_pattern_region:
            aloft_trend_text = _format_aloft_trend_text(
                aloft_pattern_region, aloft_hours,
                danger_kmh=config.WIND_DANGER_KMH,
                warn_kmh=config.WIND_WARN_KMH,
            )
            if aloft_trend_text:
                lines.append(aloft_trend_text)

        # Foehn: regionsspezifisch (Süd/Nord/Beide)
        krit_foehn = region.get("kritischer_foehn", "Beide")
        lines.append("")
        lines.append(self._format_foehn_info(
            date_str=date_str,
            kritischer_foehn=krit_foehn,
            cache_key=f"{rname}|{date_str}",
        ))

        return "\n".join(lines)

