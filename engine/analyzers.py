"""
Gleitcast Engine — Mixin: AnalyzersMixin.

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
import prompts
from prompts import format_foehn_llm_regional_guide
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
    _interpolate_wind_at_altitude,
)

logger = logging.getLogger(__name__)


class AnalyzersMixin:
    def _build_and_analyze_spot(self, spot, date_str: str, region_result: dict = None) -> dict:
        """Worker-Wrapper: Context bauen + kombinierte Safety+Flyability-Analyse.
        Returns combined result dict.  Includes a deterministic pre-filter that
        skips the LLM call for clearly not_safe days (saves ~50-60 % of API costs).

        region_result: vorab berechnete Region-Analyse fuer diesen Tag (kann None sein →
        Spot wird trotzdem analysiert, Streckenflug-Teil laeuft ohne Region-Kontext).
        """
        name = spot["name"]
        ctx = self._build_single_spot_context(spot, date_str, mode="dashboard", region_analysis_result=region_result)
        if not ctx:
            return {
                "spot": name, "date": date_str,
                "safety_status": "no_data", "phase": "combined",
                "summary": "Keine Wetterdaten fuer diesen Tag",
            }

        # ── Deterministischer Pre-Filter: offensichtliche not_safe ohne LLM ──
        prefilter = self._prefilter_not_safe(spot, date_str)
        if prefilter is not None:
            return prefilter

        return self._combined_analysis_single_spot_day(spot, date_str, ctx, region_result=region_result)

    def _prefilter_not_safe(self, spot, date_str: str):
        """Prueft anhand der deterministischen Cache-Daten ob ein Spot/Tag
        offensichtlich not_safe ist.  Gibt ein fertiges Result-Dict zurueck
        oder None wenn der LLM-Call noetig ist.

        Strategie: NUR bombensichere NO-GOs filtern. Grauzonen (z.B. wenige
        saubere Stunden, leichte Warnungen) gehen ans LLM — das kann
        nuanciert bewerten (Abgleiter-Tier, Kurzfenster o.ae.).

        Bombensichere Kriterien:
        1. Keine einzige WIND-OK Stunde  → Windrichtung ganztaegig falsch
        2. Ganztaegig Regen               → kein nutzbares Fenster
        3. Ganztaegig Gewitter            → objektiv nicht fliegbar
        4. Ganztaegig Sturmwarnung        → objektiv nicht fliegbar
        """
        name = spot["name"]
        cache_key = f"{name}|{date_str}"
        gust_info = self._ctx_gust_cache.get(cache_key)
        if not gust_info:
            return None  # Kein Cache → LLM entscheiden lassen

        wind_ok = gust_info.get("wind_ok_count", -1)
        wind_wrong = gust_info.get("wind_wrong_count", 0)
        rain_cnt = gust_info.get("rain_hours", 0)
        ts_h = gust_info.get("thunderstorm_hours", 0)
        sw_h = gust_info.get("strong_wind_warn_hours", 0)
        total_hours = wind_ok + wind_wrong if wind_ok >= 0 else 0
        max_gust = int(gust_info.get("max_surface_gust", 0) or 0)

        no_go = []
        summary_parts = []

        # Regel 1: Windrichtung ganztaegig falsch
        if wind_ok == 0 and total_hours > 0:
            no_go.append("Windrichtung: Ganztaegig ausserhalb des erlaubten Sektors")
            summary_parts.append(
                f"Die Windrichtung liegt den ganzen Tag ausserhalb des erlaubten Sektors "
                f"({spot.get('windrichtung', '?')}). Kein fliegbares Fenster."
            )

        # Regel 2: Ganztaegig Regen
        elif total_hours > 0 and rain_cnt >= total_hours - 2 and rain_cnt >= 4:
            no_go.append(f"Niederschlag: Regen in {rain_cnt} von {total_hours} Stunden")
            summary_parts.append(
                f"Nahezu ganztaegiger Niederschlag ({rain_cnt} von {total_hours} Stunden). "
                f"Kein nutzbares Flugfenster."
            )

        # Regel 3: Ganztaegig Gewitter
        elif total_hours > 0 and ts_h >= total_hours - 2 and ts_h >= 4:
            no_go.append(f"Gewitter: THUNDERSTORM in {ts_h} von {total_hours} Stunden")
            summary_parts.append(
                f"Praktisch ganztaegig Gewitter ({ts_h} von {total_hours} Stunden). "
                f"Kein fliegbares Fenster."
            )

        # Regel 4: Ganztaegig Sturmwarnung
        elif total_hours > 0 and sw_h >= total_hours - 2 and sw_h >= 4:
            no_go.append(f"Sturmwarnung: STRONG-WIND-WARN in {sw_h} von {total_hours} Stunden")
            summary_parts.append(
                f"Praktisch ganztaegig Sturmwarnung ({sw_h} von {total_hours} Stunden, "
                f"Spitzenboee {max_gust} km/h). Nicht fliegbar."
            )

        if not no_go:
            return None  # Kein klarer not_safe-Fall → LLM entscheiden lassen

        logger.info(
            f"Pre-Filter not_safe fuer {name}/{date_str}: "
            f"wind_ok={wind_ok}, rain={rain_cnt}/{total_hours}, ts={ts_h}, sw={sw_h}"
        )

        return {
            "spot": name,
            "date": date_str,
            "phase": "combined",
            "safety_status": "not_safe",
            "safe_window": "keins",
            "no_go_reasons": no_go,
            "caution_notes": [],
            "wind_summary": "",
            "wind_shear": "",
            "foehn_risk": "none",
            "summary": " ".join(summary_parts),
            "wind_ok_count": wind_ok,
            "wind_wrong_count": wind_wrong,
            # Flyability-Felder leer (not_safe → kein Teil 2)
            "fly_status": "",
            "flyability_tier": "",
            "flight_type": "",
            "flight_duration_estimate": "",
            "thermal_quality": "",
            "peak_climb_rate": 0,
            "xc_potential": "",
            "xc_details": "",
            "soaring_options": "",
            "bemerkung_check": "",
            "best_window": "keins",
            "flyability_limits": [],
            "highlights": [],
            "recommendation": "",
            "confidence": "high",
        }

    def _build_and_analyze_region(self, region, date_str: str) -> dict:
        """Worker-Wrapper: Context bauen + kombinierte Safety+Flyability-Analyse.
        Returns combined result dict."""
        ctx = self._build_single_region_context(region, date_str)
        if not ctx:
            return {
                "region": region["region"], "region_id": region["id"],
                "date": date_str, "safety_status": "no_data", "phase": "combined",
                "summary": "Keine Wetterdaten fuer diesen Tag",
            }
        return self._combined_analysis_single_region_day(region, date_str, ctx)

    def _combined_analysis_single_spot_day(self, spot, date_str: str, context: str, region_result: dict = None) -> dict:
        """Kombinierte Safety+Flyability-Analyse fuer einen Spot/Tag in einem LLM-Call."""
        name = spot["name"]
        if getattr(self, '_api_abort', None) and self._api_abort.is_set():
            reason = getattr(self, '_api_abort_reason', 'Analyse abgebrochen')
            return {"spot": name, "date": date_str, "safety_status": "error",
                    "phase": "combined",
                    "error": reason}
        try:
            if not context:
                return {"spot": name, "date": date_str, "safety_status": "error",
                        "phase": "combined", "error": "Keine Daten fuer diesen Tag"}

            messages = [
                {"role": "system", "content": prompts.SPOT_COMBINED_PROMPT},
                {"role": "user", "content": (
                    f"AKTUELLE LOKALZEIT: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ({_weekday_de(datetime.now())})\n\n"
                    f"{context}"
                )},
            ]

            # Retry-Logik: 1 Wiederholung bei Fehler
            last_err = None
            for attempt in range(2):
                try:
                    response = self.analysis_client.chat.completions.create(
                        model=self.analysis_model,
                        messages=messages,
                        temperature=0.2,
                        max_tokens=1100,
                        response_format={"type": "json_object"},
                    )
                    _log_prompt_cache_usage(response, label="spot_combined")
                    raw = response.choices[0].message.content
                    result = json.loads(raw)
                    last_err = None
                    break
                except Exception as api_err:
                    last_err = api_err
                    if _is_permanent_api_error(api_err):
                        self._api_abort_reason = _user_friendly_api_error(api_err)
                        if getattr(self, '_api_abort', None):
                            self._api_abort.set()
                        break
                    if attempt == 0:
                        logger.warning(f"Combined-Check fuer {name}/{date_str} Versuch 1 fehlgeschlagen: {api_err} — Retry in 3s")
                        time.sleep(3)
            if last_err:
                raise last_err
            return self._post_process_combined_spot(result, spot, date_str, region_result=region_result)

        except Exception as e:
            logger.error(f"Combined-Analyse fuer {name}/{date_str} fehlgeschlagen (nach 2 Versuchen): {e}")
            return {"spot": name, "date": date_str, "safety_status": "error", "phase": "combined", "error": str(e)}

    def run_spot_analyses(self, spot_names: list = None) -> dict:
        """Wrapper: konsumiert den Stream-Generator und gibt das finale Ergebnis zurueck."""
        last_result = None
        for evt in self.run_spot_analyses_stream(spot_names):
            if evt.get("event") == "error":
                return {"success": False, "error": evt["data"].get("message", "Unbekannt")}
            if evt.get("event") == "spot_done":
                last_result = evt["data"]
        if last_result:
            return {"success": True, **last_result}
        return {"success": False, "error": "Kein Ergebnis"}

    def _push_analyses_to_instantdb(self):
        """Pusht Spot-Analysen nach InstantDB (Hintergrund-Thread). Löscht zuerst alte Records."""
        try:
            self.instantdb.delete_all("spot_analyses")
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
                        "rating": float(entry.get("rating", 0.0) or 0.0),
                        "is_conditional": bool(entry.get("is_conditional", False)),
                        "conditional_reason": entry.get("conditional_reason", "") or "",
                    }
                    safety = entry.get("safety", {})
                    doc_data["safety_status"] = safety.get("safety_status", "error")
                    doc_data["error"] = safety.get("error", "")
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
                    for lbl_key in ("primary_no_go", "primary_caution", "primary_reducer", "primary_booster"):
                        doc_data[lbl_key] = safety.get(lbl_key, "") or ""

                    ss = safety.get("safety_status", "error")
                    fly = entry.get("flyability", {})
                    fly_status_merged = entry.get("fly_status", "")
                    # Phase 2 nur bei safe/conditional — sonst alte InstantDB-Felder explizit leeren (Merge behält sonst Altlasten)
                    if fly and fly_status_merged and ss in ("safe", "conditional"):
                        doc_data["fly_status"] = fly_status_merged
                        doc_data["flyability_tier"] = fly_status_merged
                        doc_data["flight_type"] = fly.get("flight_type", "")
                        doc_data["flight_duration"] = fly.get("flight_duration_estimate", "")
                        doc_data["xc_potential"] = fly.get("xc_potential", "")
                        doc_data["peak_climb_rate"] = fly.get("peak_climb_rate", 0)
                        doc_data["flyability_feedback"] = fly.get("recommendation", "")
                        for lkey in ("flyability_limits", "highlights"):
                            val = fly.get(lkey, [])
                            if isinstance(val, list):
                                val = val[:3]
                            doc_data[lkey] = json.dumps(val if isinstance(val, list) else [], ensure_ascii=False)
                    else:
                        doc_data["fly_status"] = ""
                        doc_data["flyability_tier"] = ""
                        doc_data["flight_type"] = ""
                        doc_data["flight_duration"] = ""
                        doc_data["xc_potential"] = ""
                        doc_data["peak_climb_rate"] = 0
                        doc_data["flyability_feedback"] = ""
                        doc_data["flyability_limits"] = "[]"
                        doc_data["highlights"] = "[]"
                        doc_data["fly_error"] = entry.get("fly_error", "")

                    # Streckenflug-Felder (TEIL 4 Synthese Spot + Region)
                    sf = entry.get("streckenflug") or {}
                    doc_data["streckenflug_tier"] = sf.get("tier", "kein_xc")
                    try:
                        doc_data["streckenflug_rating"] = int(sf.get("rating", 0) or 0)
                    except (TypeError, ValueError):
                        doc_data["streckenflug_rating"] = 0
                    doc_data["streckenflug_summary"] = sf.get("summary", "") or ""
                    doc_data["streckenflug_limiting_factor"] = sf.get("limiting_factor", "none")
                    doc_data["streckenflug_region_context_available"] = bool(sf.get("region_context_available", False))

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

    def _combined_analysis_single_region_day(self, region, date_str: str, context: str) -> dict:
        """Kombinierte Safety+Flyability-Analyse fuer eine Region/Tag in einem LLM-Call."""
        rname = region["region"]
        if getattr(self, '_api_abort', None) and self._api_abort.is_set():
            reason = getattr(self, '_api_abort_reason', 'Analyse abgebrochen')
            return {"region": rname, "region_id": region["id"], "date": date_str,
                    "safety_status": "error", "phase": "combined",
                    "error": reason}
        try:
            if not context:
                return {"region": rname, "date": date_str, "safety_status": "error",
                        "phase": "combined", "error": "Keine Daten"}

            messages = [
                {"role": "system", "content": prompts.REGION_COMBINED_PROMPT},
                {"role": "user", "content": (
                    f"AKTUELLE LOKALZEIT: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ({_weekday_de(datetime.now())})\n\n"
                    f"{context}"
                )},
            ]

            # Retry-Logik: 1 Wiederholung bei Fehler
            last_err = None
            for attempt in range(2):
                try:
                    response = self.analysis_client.chat.completions.create(
                        model=self.analysis_model,
                        messages=messages,
                        temperature=0.2,
                        max_tokens=1100,
                        response_format={"type": "json_object"},
                    )
                    _log_prompt_cache_usage(response, label="region_combined")
                    raw = response.choices[0].message.content
                    result = json.loads(raw)
                    last_err = None
                    break
                except Exception as api_err:
                    last_err = api_err
                    if _is_permanent_api_error(api_err):
                        logger.error(f"Region Combined-Check fuer {rname}/{date_str}: permanenter API-Fehler ({api_err}) — kein Retry")
                        self._api_abort_reason = _user_friendly_api_error(api_err)
                        if getattr(self, '_api_abort', None):
                            self._api_abort.set()
                        break
                    if attempt == 0:
                        logger.warning(f"Region Combined-Check fuer {rname}/{date_str} Versuch 1 fehlgeschlagen: {api_err} — Retry in 3s")
                        time.sleep(3)
            if last_err:
                raise last_err
            return self._post_process_combined_region(result, region, date_str)

        except Exception as e:
            logger.error(f"Region Combined-Analyse fuer {rname}/{date_str} fehlgeschlagen: {e}")
            return {"region": rname, "region_id": region["id"], "date": date_str,
                    "safety_status": "error", "phase": "combined", "error": str(e)}

    def run_region_analyses(self) -> dict:
        """Wrapper: konsumiert den Stream-Generator und gibt das finale Ergebnis zurueck."""
        last_result = None
        for evt in self.run_region_analyses_stream():
            if evt.get("event") == "error":
                return {"success": False, "error": evt["data"].get("message", "Unbekannt")}
            if evt.get("event") == "region_done":
                last_result = evt["data"]
        if last_result:
            return {"success": True, **last_result}
        return {"success": False, "error": "Kein Ergebnis"}

    def _push_region_analyses_to_instantdb(self):
        """Pusht Region-Analysen nach InstantDB. Löscht zuerst alte Records."""
        try:
            self.instantdb.delete_all("region_analyses")
            docs = {}
            for rid, days in self.region_analyses.items():
                for date_str, entry in days.items():
                    doc_id = self.instantdb.make_id(f"region_analysis.{rid}.{date_str}")
                    safety = entry.get("safety", {})
                    fly = entry.get("flyability", {})
                    ss = safety.get("safety_status", entry.get("safety_status", "error"))
                    fly_status_merged = entry.get("fly_status", "")

                    doc_data = {
                        "region_id": rid,
                        "region_name": entry.get("region_name", rid),
                        "date": date_str,
                        "status": entry.get("status", "error"),
                        "best_window": entry.get("best_window", "?"),
                        "updated_at": self.region_analyses_loaded_at.isoformat(),
                        "safety_status": ss,
                        "error": safety.get("error", entry.get("error", "")),
                        "safe_window": safety.get("safe_window", entry.get("safe_window", "keins")),
                        "safety_feedback": safety.get("summary", entry.get("summary", "")),
                        "foehn_risk": safety.get("foehn_risk", entry.get("foehn_risk", "none")),
                        "wind_summary": safety.get("wind_summary", entry.get("wind_summary", "")),
                        "rating": float(entry.get("rating", 0.0) or 0.0),
                        "is_conditional": bool(entry.get("is_conditional", False)),
                        "conditional_reason": entry.get("conditional_reason", "") or "",
                    }
                    for key in ["no_go_reasons", "caution_notes"]:
                        val = safety.get(key, entry.get(key, []))
                        if isinstance(val, list):
                            doc_data[key] = json.dumps(val, ensure_ascii=False)
                        else:
                            doc_data[key] = str(val)
                    for lbl_key in ("primary_no_go", "primary_caution", "primary_reducer", "primary_booster"):
                        doc_data[lbl_key] = safety.get(lbl_key, "") or ""

                    if fly and fly_status_merged and ss in ("safe", "conditional"):
                        doc_data["fly_status"] = fly_status_merged
                        doc_data["flyability_tier"] = fly_status_merged
                        doc_data["flight_type"] = fly.get("flight_type", "")
                        doc_data["flight_duration"] = fly.get("flight_duration_estimate", "")
                        doc_data["xc_potential"] = fly.get("xc_potential", "")
                        doc_data["peak_climb_rate"] = fly.get("peak_climb_rate", 0)
                        doc_data["flyability_feedback"] = fly.get("recommendation", "")
                        for lkey in ("flyability_limits", "highlights"):
                            val = fly.get(lkey, [])
                            if isinstance(val, list):
                                val = val[:3]
                            doc_data[lkey] = json.dumps(val if isinstance(val, list) else [], ensure_ascii=False)
                    else:
                        doc_data["fly_status"] = ""
                        doc_data["flyability_tier"] = ""
                        doc_data["flight_type"] = ""
                        doc_data["flight_duration"] = ""
                        doc_data["xc_potential"] = ""
                        doc_data["peak_climb_rate"] = 0
                        doc_data["flyability_feedback"] = ""
                        doc_data["flyability_limits"] = "[]"
                        doc_data["highlights"] = "[]"
                        doc_data["fly_error"] = entry.get("fly_error", "")

                    docs[doc_id] = doc_data

            if self.instantdb.batch_upsert("region_analyses", docs):
                logger.info(f"InstantDB: {len(docs)} Region-Analysen gepusht")
            else:
                logger.warning("InstantDB: Region-Analysen push fehlgeschlagen")
        except Exception as e:
            logger.error(f"InstantDB Region-Analysen-Push fehlgeschlagen: {e}")

    # ════════════════════════════════════════════════════════════════════════
    # WEEKLY BRIEFING — Wochen-Fazit aus Spot- und Region-Analysen
    # ════════════════════════════════════════════════════════════════════════

    def _weekly_briefing_cache_path(self) -> Path:
        return Path("data") / "weekly_briefing.json"

    def _save_weekly_briefing(self, data: dict) -> None:
        try:
            p = self._weekly_briefing_cache_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"Weekly-Briefing-Cache-Save fehlgeschlagen: {e}")

    def _load_weekly_briefing(self) -> dict | None:
        try:
            p = self._weekly_briefing_cache_path()
            if not p.is_file():
                return None
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Weekly-Briefing-Cache-Load fehlgeschlagen: {e}")
            return None

    def build_briefing_data(self) -> dict:
        """Aggregiert spot_analyses + region_analyses in eine Briefing-Struktur.
        Filter: zeigt nur green + violet (NO-GO und Abgleiter ausgeblendet).
        """
        from source_area import get_all_regions
        all_regions = get_all_regions()
        region_by_id = {r["id"]: r for r in all_regions}
        # Map spot_name → region_id ueber source_area
        # find_region_for_point returns the region DICT (not id) — extract .id
        from source_area import find_region_for_point
        spot_region = {}
        spot_elev = {}
        spot_coords = {}
        spot_windrichtung = {}
        for spot in self.spots:
            # load_spots() benutzt die Keys "latitude"/"longitude" (nicht lat/lon);
            # akzeptiere beide Varianten defensiv.
            spot_lat = spot.get("latitude", spot.get("lat"))
            spot_lon = spot.get("longitude", spot.get("lon"))
            try:
                region_obj = find_region_for_point(spot_lat, spot_lon)
            except Exception:
                region_obj = None
            spot_region[spot["name"]] = (region_obj or {}).get("id", "unknown")
            try:
                spot_elev[spot["name"]] = int(spot.get("elevation_m") or 0)
            except Exception:
                spot_elev[spot["name"]] = 0
            try:
                spot_coords[spot["name"]] = (float(spot_lat), float(spot_lon))
            except Exception:
                spot_coords[spot["name"]] = None
            spot_windrichtung[spot["name"]] = spot.get("windrichtung", "") or ""

        forecast_dates = self._get_forecast_dates() or []
        days_data = []
        for date_str in forecast_dates:
            # Spots fuer diesen Tag
            spot_entries = []
            nogo_count = 0
            bronze_count = 0
            conditional_count = 0
            # Pro-Region-Counts fuer dynamisches Filtern im Frontend.
            # Shape: { region_id: {"flyable": n, "bronze": n, "nogo": n, "conditional": n} }
            counts_by_region = {}
            def _bump_region(rid, key):
                c = counts_by_region.setdefault(
                    rid or "unknown",
                    {"flyable": 0, "bronze": 0, "nogo": 0, "conditional": 0},
                )
                c[key] = c.get(key, 0) + 1
            for spot_name, days in self.spot_analyses.items():
                if not spot_name or not str(spot_name).strip():
                    continue  # defensive: skip entries without a name
                entry = days.get(date_str)
                if not entry:
                    continue
                safety = entry.get("safety", {})
                ss = safety.get("safety_status", "")
                fly_status = entry.get("fly_status", "") or entry.get("flyability", {}).get("fly_status", "")
                rating = float(entry.get("rating", 0.0) or 0.0)
                is_cond = bool(entry.get("is_conditional", False))
                rid_spot_pre = spot_region.get(spot_name, "unknown")

                if ss == "not_safe":
                    nogo_count += 1
                    _bump_region(rid_spot_pre, "nogo")
                    continue
                if fly_status == "gray":
                    bronze_count += 1
                    _bump_region(rid_spot_pre, "bronze")
                    continue
                if ss == "conditional":
                    conditional_count += 1
                    _bump_region(rid_spot_pre, "conditional")
                if fly_status not in ("green", "violet"):
                    continue
                _bump_region(rid_spot_pre, "flyable")

                fly = entry.get("flyability", {}) or {}
                rid_spot = spot_region.get(spot_name, "unknown")
                region_name_spot = region_by_id.get(rid_spot, {}).get("region", "") if rid_spot != "unknown" else ""
                coords = spot_coords.get(spot_name)
                spot_entries.append({
                    "spot": spot_name,
                    "region_id": rid_spot,
                    "region_name": region_name_spot,
                    "elevation_m": spot_elev.get(spot_name, 0),
                    "lat": coords[0] if coords else None,
                    "lon": coords[1] if coords else None,
                    "windrichtung": spot_windrichtung.get(spot_name, ""),
                    "rating": rating,
                    "fly_status": fly_status,
                    "safety_status": ss,
                    "is_conditional": is_cond,
                    "conditional_reason": entry.get("conditional_reason", "") or "",
                    "peak_climb_rate": fly.get("peak_climb_rate", 0),
                    "flight_type": fly.get("flight_type", ""),
                    "flight_duration": fly.get("flight_duration_estimate", ""),
                    "xc_potential": fly.get("xc_potential", ""),
                    "best_window": fly.get("best_window", "") or entry.get("best_window", ""),
                    "recommendation": fly.get("recommendation", ""),
                    "safety_feedback": safety.get("summary", ""),
                    # Volle Voranalyse fuer Ausklapp-Ansicht im Briefing
                    "analysis_full": entry,
                })
            spot_entries.sort(key=lambda e: e["rating"], reverse=True)

            # Regionen fuer diesen Tag
            region_entries = []
            for rid, days in self.region_analyses.items():
                entry = days.get(date_str)
                if not entry:
                    continue
                safety = entry.get("safety", {})
                ss = safety.get("safety_status", "")
                fly_status = entry.get("fly_status", "") or entry.get("flyability", {}).get("fly_status", "")
                rating = float(entry.get("rating", 0.0) or 0.0)

                if ss == "not_safe" or fly_status == "gray":
                    continue
                if fly_status not in ("green", "violet"):
                    continue

                region_name = entry.get("region_name", region_by_id.get(rid, {}).get("region", rid))
                region_entries.append({
                    "region_id": rid,
                    "region_name": region_name,
                    "rating": rating,
                    "fly_status": fly_status,
                    "safety_status": ss,
                    "is_conditional": bool(entry.get("is_conditional", False)),
                })
            region_entries.sort(key=lambda e: e["rating"], reverse=True)

            days_data.append({
                "date": date_str,
                "weekday": _weekday_de(datetime.fromisoformat(date_str)),
                "top_spots": spot_entries,
                "top_regions": region_entries[:10],
                "counts": {
                    "spots_total": sum(1 for days in self.spot_analyses.values() if date_str in days),
                    "spots_flyable": len(spot_entries),
                    "spots_bronze": bronze_count,
                    "spots_nogo": nogo_count,
                    "spots_conditional": conditional_count,
                },
                # Pro-Region-Counts — damit das Frontend beim Region-Filter
                # die Statistiken dynamisch aggregieren kann (fliegbar/abgleiter/no-go/bedingt).
                "counts_by_region": counts_by_region,
            })

        return {
            "generated_at": datetime.now().isoformat(),
            "forecast_dates": forecast_dates,
            "days": days_data,
        }

    def generate_weekly_briefing(self) -> dict:
        """Erstellt das Wochen-Fazit via LLM (inkl. bester Wochentag, Regionen-Ranking, Tages-Highlights)."""
        if not self.analysis_client:
            return {"success": False, "error": f"Kein API-Key fuer Analyse-Provider '{self.analysis_provider}'"}
        data = self.build_briefing_data()
        if not data.get("days"):
            return {"success": False, "error": "Keine Analysedaten vorhanden"}

        # Kompakter LLM-Kontext: pro Tag Top-Spots + Top-Regionen + Counts
        lines = []
        for day in data["days"]:
            d = day["date"]; wd = day["weekday"]
            c = day["counts"]
            lines.append(f"\n═══ {wd} {d} ═══")
            lines.append(
                f"Counts: {c['spots_flyable']} fliegbar / {c['spots_bronze']} Abgleiter / "
                f"{c['spots_nogo']} NO-GO / {c['spots_conditional']} bedingt sicher"
            )
            if day["top_spots"]:
                lines.append("Top-Spots (green+violet):")
                for s in day["top_spots"][:10]:
                    cond = " [bedingt]" if s["is_conditional"] else ""
                    lines.append(
                        f"  {s['spot']} ({s['region_id']}): {s['rating']:.1f} "
                        f"{s['fly_status']} peak={s['peak_climb_rate']:.1f}m/s{cond}"
                    )
            else:
                lines.append("Top-Spots: keine green/violet Spots")
            if day["top_regions"]:
                lines.append("Top-Regionen (green+violet):")
                for r in day["top_regions"][:5]:
                    cond = " [bedingt]" if r["is_conditional"] else ""
                    lines.append(
                        f"  {r['region_name']}: {r['rating']:.1f} {r['fly_status']}{cond}"
                    )
        ctx = "\n".join(lines)

        try:
            response = self.analysis_client.chat.completions.create(
                model=self.analysis_model,
                messages=[
                    {"role": "system", "content": prompts.WEEKLY_BRIEFING_PROMPT},
                    {"role": "user", "content": (
                        f"AKTUELLE LOKALZEIT: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                        f"WOCHEN-DATEN:\n{ctx}\n"
                    )},
                ],
                temperature=0.4,
                max_tokens=1500,
                response_format={"type": "json_object"},
            )
            _log_prompt_cache_usage(response, label="weekly_briefing")
            raw = response.choices[0].message.content
            fazit = json.loads(raw)
            # Clamp week_rating
            wr = fazit.get("week_rating", 0.0)
            try:
                wr = float(wr)
            except (TypeError, ValueError):
                wr = 0.0
            fazit["week_rating"] = max(0.0, min(10.0, round(wr, 1)))

            result = {
                "success": True,
                "generated_at": data["generated_at"],
                "forecast_dates": data["forecast_dates"],
                "days": data["days"],
                "fazit": fazit,
            }
            self._save_weekly_briefing(result)
            return result
        except Exception as e:
            logger.error(f"Weekly-Briefing LLM-Call fehlgeschlagen: {e}")
            return {"success": False, "error": str(e)}

    # ── SSE Streaming generators ────────────────────────────────────────
    # Heartbeat: wait() mit Timeout statt as_completed() — verhindert
    # Connection-Timeout wenn ein einzelner LLM-Call lange dauert.

    _HEARTBEAT_INTERVAL = 15  # Sekunden zwischen Keepalive-Events
    _HEARTBEAT_EVENT = {"event": "heartbeat", "data": {}}

    def run_region_analyses_stream(self):
        """Generator: yields progress events for region analyses (combined Safety+Flyability)."""
        self._api_abort = threading.Event()  # Early-Abort bei permanentem API-Fehler
        self._api_abort_reason = 'Analyse abgebrochen'
        if not self.analysis_client:
            yield {"event": "error", "data": {"message": f"Kein API-Key fuer Analyse-Provider '{self.analysis_provider}'"}}
            return
        if not self.region_weather_data:
            yield {"event": "error", "data": {"message": "Keine Region-Wetterdaten geladen"}}
            return

        all_regions = get_all_regions()
        regions_with_data = [r for r in all_regions if r["id"] in self.region_weather_data]
        if not regions_with_data:
            yield {"event": "error", "data": {"message": "Keine Regionen mit Wetterdaten"}}
            return

        forecast_dates = self._get_forecast_dates()
        if not forecast_dates:
            yield {"event": "error", "data": {"message": "Keine Vorhersage-Tage verfuegbar"}}
            return

        regions_by_id = {r["id"]: r for r in regions_with_data}
        total = len(regions_with_data) * len(forecast_dates)

        # ── Single phase: region_combined ──
        yield {"event": "phase", "data": {"phase": "region_combined", "total": total}}

        combined_results = {}  # {rid: {date_str: result}}
        completed = 0

        with ThreadPoolExecutor(max_workers=config.LLM_MAX_WORKERS) as executor:
            futures = {}
            for region in regions_with_data:
                for date_str in forecast_dates:
                    future = executor.submit(self._build_and_analyze_region, region, date_str)
                    futures[future] = (region["id"], region["region"], date_str)

            remaining = set(futures.keys())
            while remaining:
                done, remaining = wait(remaining, timeout=self._HEARTBEAT_INTERVAL, return_when=FIRST_COMPLETED)
                if not done:
                    yield self._HEARTBEAT_EVENT
                    continue
                for future in done:
                    rid, rname, date_str = futures[future]
                    try:
                        result = future.result()
                    except Exception as e:
                        logger.error(f"Region Combined-Future {rid}/{date_str} fehlgeschlagen: {e}")
                        result = {"region_id": rid, "region": rname, "date": date_str,
                                  "safety_status": "error", "error": str(e)}
                    combined_results.setdefault(rid, {})[date_str] = result
                    completed += 1
                    yield {"event": "progress", "data": {
                        "phase": "region_combined", "name": rname, "date": date_str,
                        "completed": completed, "total": total,
                        "result": result.get("flyability_tier") or result.get("safety_status", "error"),
                    }}

        # ── Split + Merge (Abwaertskompatibilitaet: entry["safety"] + entry["flyability"]) ──
        merged = {}
        for rid, days in combined_results.items():
            merged[rid] = {}
            for date_str, result in days.items():
                safety_status = result.get("safety_status", "error")

                # Safety-Felder extrahieren
                safety = {
                    "safety_status": safety_status,
                    "safe_window": result.get("safe_window", "keins"),
                    "no_go_reasons": result.get("no_go_reasons", []),
                    "caution_notes": result.get("caution_notes", []),
                    "primary_no_go": result.get("primary_no_go"),
                    "primary_caution": result.get("primary_caution"),
                    "primary_reducer": result.get("primary_reducer"),
                    "primary_booster": result.get("primary_booster"),
                    "wind_summary": result.get("wind_summary", ""),
                    "wind_shear": result.get("wind_shear", ""),
                    "foehn_risk": result.get("foehn_risk", "none"),
                    "summary": result.get("summary", ""),
                    "region": result.get("region", ""),
                    "region_id": result.get("region_id", rid),
                    "date": date_str,
                    "wind_calm_count": result.get("wind_calm_count", 0),
                    "wind_moderate_count": result.get("wind_moderate_count", 0),
                    "wind_strong_count": result.get("wind_strong_count", 0),
                    "error": result.get("error", ""),
                }
                entry = {"safety": safety}

                # Rating / Conditional-Flag (Briefing) — top-level fuer einfachen Zugriff
                entry["rating"] = float(result.get("rating", 0.0) or 0.0)
                entry["is_conditional"] = bool(result.get("is_conditional", False))
                entry["conditional_reason"] = result.get("conditional_reason", "") or ""

                # Flyability-Felder extrahieren
                tier = result.get("flyability_tier") or result.get("fly_status") or ""
                if safety_status in ("safe", "conditional") and tier:
                    fly = {
                        "flyability_tier": tier,
                        "fly_status": tier,
                        "status": tier,
                        "flight_type": result.get("flight_type", ""),
                        "flight_duration_estimate": result.get("flight_duration_estimate", ""),
                        "thermal_quality": result.get("thermal_quality", ""),
                        "peak_climb_rate": result.get("peak_climb_rate", 0),
                        "xc_potential": result.get("xc_potential", ""),
                        "xc_details": result.get("xc_details", ""),
                        "best_window": result.get("best_window", ""),
                        "flyability_limits": result.get("flyability_limits", []),
                        "highlights": result.get("highlights", []),
                        "recommendation": result.get("recommendation", ""),
                        "confidence": result.get("confidence", ""),
                        "rating": entry["rating"],
                        "is_conditional": entry["is_conditional"],
                        "conditional_reason": entry["conditional_reason"],
                        "region": result.get("region", ""),
                        "region_id": result.get("region_id", rid),
                        "date": date_str,
                    }
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
                    entry["fly_error"] = result.get("error", "")
                else:
                    entry["fly_status"] = ""
                    entry["status"] = safety_status

                entry["best_window"] = result.get("best_window") or safety.get("safe_window", "keins")
                entry["recommendation"] = result.get("recommendation", "")
                entry["region_name"] = result.get("region", regions_by_id.get(rid, {}).get("region", rid))
                merged[rid][date_str] = entry

        self.region_analyses = merged
        self.region_analyses_loaded_at = datetime.now()
        self._save_region_analyses_cache()
        if self.instantdb:
            threading.Thread(target=self._push_region_analyses_to_instantdb, daemon=True).start()

        logger.info(f"Region-Analysen (stream) abgeschlossen: {total} LLM-Aufrufe (kombiniert)")

        yield {"event": "region_done", "data": {
            "regions_count": len(merged), "results_count": total, "dates": forecast_dates,
        }}

    def run_spot_analyses_stream(self, spot_names: list = None):
        """Generator: yields progress events for spot analyses (combined Safety+Flyability)."""
        self._api_abort = threading.Event()  # Early-Abort bei permanentem API-Fehler
        self._api_abort_reason = 'Analyse abgebrochen'
        # Caches von vorherigem Lauf leeren (sonst wachsen sie unbegrenzt)
        self._ctx_gust_cache.clear()
        self._ctx_tq_cache.clear()
        if not self.analysis_client:
            yield {"event": "error", "data": {"message": f"Kein API-Key fuer Analyse-Provider '{self.analysis_provider}'"}}
            return
        if not self.weather_data:
            yield {"event": "error", "data": {"message": "Keine Wetterdaten geladen"}}
            return

        if spot_names:
            spots_to_analyze = [s for s in self.spots if s["name"] in spot_names and s["name"] in self.weather_data]
        else:
            spots_to_analyze = [s for s in self.spots if s["name"] in self.weather_data]
        if not spots_to_analyze:
            yield {"event": "error", "data": {"message": "Keine zu analysierenden Spots gefunden"}}
            return

        forecast_dates = self._get_forecast_dates()
        if not forecast_dates:
            yield {"event": "error", "data": {"message": "Keine Vorhersage-Tage verfuegbar"}}
            return

        spots_by_name = {s["name"]: s for s in spots_to_analyze}

        # Pre-validation
        incomplete_spot_days = {}
        for spot in spots_to_analyze:
            name = spot["name"]
            spot_data = self.weather_data.get(name, {})
            hourly_data = spot_data.get("hourly_data", {})
            missing = validate_spot_data(name, hourly_data, config.FORECAST_DAYS)
            if missing:
                incomplete_spot_days[name] = set(missing)

        total = len(spots_to_analyze) * len(forecast_dates)
        skipped_no_data = 0

        # ── Single phase: spot_combined ──
        yield {"event": "phase", "data": {"phase": "spot_combined", "total": total}}

        combined_results = {}  # {spot_name: {date_str: result}}
        completed = 0

        # Sammle no_data-Eintraege vorab
        no_data_entries = {}
        for spot in spots_to_analyze:
            for date_str in forecast_dates:
                if date_str in incomplete_spot_days.get(spot["name"], set()):
                    no_data_entries.setdefault(spot["name"], {})[date_str] = {
                        "spot": spot["name"], "date": date_str,
                        "safety_status": "no_data", "phase": "combined",
                        "summary": "Wetterdaten unvollstaendig",
                    }
                    skipped_no_data += 1
                    completed += 1

        with ThreadPoolExecutor(max_workers=config.LLM_MAX_WORKERS) as executor:
            futures = {}
            for spot in spots_to_analyze:
                for date_str in forecast_dates:
                    if date_str in incomplete_spot_days.get(spot["name"], set()):
                        continue
                    future = executor.submit(self._build_and_analyze_spot, spot, date_str)
                    futures[future] = (spot["name"], date_str)

            remaining = set(futures.keys())
            while remaining:
                done, remaining = wait(remaining, timeout=self._HEARTBEAT_INTERVAL, return_when=FIRST_COMPLETED)
                if not done:
                    yield self._HEARTBEAT_EVENT
                    continue
                for future in done:
                    spot_name, date_str = futures[future]
                    try:
                        result = future.result()
                    except Exception as e:
                        logger.error(f"Combined-Future fuer {spot_name}/{date_str} fehlgeschlagen: {e}")
                        result = {"spot": spot_name, "date": date_str,
                                  "safety_status": "error", "error": str(e)}
                    combined_results.setdefault(spot_name, {})[date_str] = result
                    completed += 1
                    yield {"event": "progress", "data": {
                        "phase": "spot_combined", "name": spot_name, "date": date_str,
                        "completed": completed, "total": total,
                        "result": result.get("flyability_tier") or result.get("safety_status", "error"),
                    }}

        # ── Split + Merge (Abwaertskompatibilitaet: entry["safety"] + entry["flyability"]) ──
        merged = {}
        # Zuerst no_data-Eintraege einfuegen
        for spot_name, days in no_data_entries.items():
            for date_str, result in days.items():
                entry = {
                    "safety": result,
                    "fly_status": "",
                    "status": "no_data",
                    "best_window": "keins",
                    "recommendation": "",
                }
                merged.setdefault(spot_name, {})[date_str] = entry

        # Dann kombinierte Ergebnisse aufsplitten
        for spot_name, days in combined_results.items():
            for date_str, result in days.items():
                safety_status = result.get("safety_status", "error")

                # Safety-Felder extrahieren
                safety = {
                    "safety_status": safety_status,
                    "safe_window": result.get("safe_window", "keins"),
                    "no_go_reasons": result.get("no_go_reasons", []),
                    "caution_notes": result.get("caution_notes", []),
                    "primary_no_go": result.get("primary_no_go"),
                    "primary_caution": result.get("primary_caution"),
                    "primary_reducer": result.get("primary_reducer"),
                    "primary_booster": result.get("primary_booster"),
                    "wind_summary": result.get("wind_summary", ""),
                    "wind_shear": result.get("wind_shear", ""),
                    "foehn_risk": result.get("foehn_risk", "none"),
                    "summary": result.get("summary", ""),
                    "spot": result.get("spot", spot_name),
                    "date": date_str,
                    "wind_ok_count": result.get("wind_ok_count", 0),
                    "wind_wrong_count": result.get("wind_wrong_count", 0),
                    "error": result.get("error", ""),
                }
                entry = {"safety": safety}

                # Rating / Conditional-Flag (Briefing) — top-level fuer einfachen Zugriff
                entry["rating"] = float(result.get("rating", 0.0) or 0.0)
                entry["is_conditional"] = bool(result.get("is_conditional", False))
                entry["conditional_reason"] = result.get("conditional_reason", "") or ""

                # Flyability-Felder extrahieren
                tier = result.get("flyability_tier") or result.get("fly_status") or ""
                if safety_status in ("safe", "conditional") and tier:
                    fly = {
                        "flyability_tier": tier,
                        "fly_status": tier,
                        "status": tier,
                        "flight_type": result.get("flight_type", ""),
                        "flight_duration_estimate": result.get("flight_duration_estimate", ""),
                        "thermal_quality": result.get("thermal_quality", ""),
                        "peak_climb_rate": result.get("peak_climb_rate", 0),
                        "xc_potential": result.get("xc_potential", ""),
                        "xc_details": result.get("xc_details", ""),
                        "soaring_options": result.get("soaring_options", ""),
                        "bemerkung_check": result.get("bemerkung_check", ""),
                        "best_window": result.get("best_window", ""),
                        "flyability_limits": result.get("flyability_limits", []),
                        "highlights": result.get("highlights", []),
                        "recommendation": result.get("recommendation", ""),
                        "confidence": result.get("confidence", ""),
                        "rating": entry["rating"],
                        "is_conditional": entry["is_conditional"],
                        "conditional_reason": entry["conditional_reason"],
                        "spot": result.get("spot", spot_name),
                        "date": date_str,
                    }
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
                    entry["fly_error"] = result.get("error", "")
                else:
                    entry["fly_status"] = ""
                    entry["status"] = safety_status

                entry["streckenflug"] = result.get("streckenflug") or {
                    "tier": "kein_xc", "rating": 0,
                    "summary": "", "limiting_factor": "spot_not_flyable" if safety_status == "not_safe" else "none",
                    "region_context_available": False,
                }
                entry["best_window"] = result.get("best_window") or safety.get("safe_window", "keins")
                entry["recommendation"] = result.get("recommendation", "")
                merged.setdefault(spot_name, {})[date_str] = entry

        self.spot_analyses = merged
        self.analyses_loaded_at = datetime.now()
        self._analyses_stale = False
        self._save_analyses_cache()
        if self.instantdb:
            threading.Thread(target=self._push_analyses_to_instantdb, daemon=True).start()

        # Build per_day_counts + summary
        per_day_counts = {}
        for date_str in forecast_dates:
            safety_c = {"safe": 0, "conditional": 0, "not_safe": 0, "no_data": 0}
            fly_c = {"gray": 0, "green": 0, "violet": 0}
            err_n = 0
            for sn, days in merged.items():
                ent = days.get(date_str, {})
                ss = ent.get("safety", {}).get("safety_status", "error")
                if ss in safety_c:
                    safety_c[ss] += 1
                else:
                    err_n += 1
                ft = ent.get("fly_status") or ""
                if ft in fly_c:
                    fly_c[ft] += 1
            per_day_counts[date_str] = {"safety": safety_c, "fly": fly_c, "error": err_n}

        actual_calls = total - skipped_no_data
        logger.info(f"Spot-Analysen (stream) abgeschlossen: {actual_calls} LLM-Aufrufe (kombiniert)")

        yield {"event": "spot_done", "data": {
            "spots_count": len(merged), "results_count": actual_calls,
            "safety_count": total, "flyability_count": 0,
            "dates": forecast_dates, "per_day_counts": per_day_counts,
        }}

    # ════════════════════════════════════════════════════════════════════════
    # BATCH-API-MODUS (OpenAI Batch API — 50% guenstiger, asynchron)
    # ════════════════════════════════════════════════════════════════════════

    def _build_batch_jsonl(self, requests: list[dict]) -> str:
        """Baut JSONL-String fuer OpenAI Batch API.
        Jeder Request: {"custom_id": ..., "method": "POST", "url": "/v1/chat/completions",
                        "body": {model, messages, temperature, max_tokens, response_format}}
        """
        lines = []
        for req in requests:
            line = json.dumps(req, ensure_ascii=False)
            lines.append(line)
        return "\n".join(lines)

    def _submit_batch(self, jsonl_content: str, description: str) -> str:
        """Laedt JSONL hoch, erstellt Batch, gibt batch_id zurueck. Nur OpenAI."""
        if self.analysis_provider != "openai":
            raise RuntimeError(
                f"Batch-API ist nur fuer OpenAI verfuegbar, nicht fuer "
                f"'{self.analysis_provider}'. Bitte LLM_ANALYSIS_MODE=parallel setzen."
            )
        import io
        file_obj = io.BytesIO(jsonl_content.encode("utf-8"))
        file_obj.name = "batch_input.jsonl"
        uploaded = self.analysis_client.files.create(file=file_obj, purpose="batch")
        logger.info(f"Batch-Datei hochgeladen: {uploaded.id} ({description})")

        batch = self.analysis_client.batches.create(
            input_file_id=uploaded.id,
            endpoint="/v1/chat/completions",
            completion_window="24h",
            metadata={"description": description},
        )
        logger.info(f"Batch erstellt: {batch.id} ({description}), Status: {batch.status}")
        return batch.id

    def _poll_batch(self, batch_id: str, poll_interval: int = None) -> dict:
        """Pollt Batch bis abgeschlossen. Gibt {custom_id: parsed_json} zurueck."""
        if poll_interval is None:
            poll_interval = config.LLM_BATCH_POLL_INTERVAL

        while True:
            batch = self.analysis_client.batches.retrieve(batch_id)
            status = batch.status
            logger.info(f"Batch {batch_id}: Status={status}, "
                        f"completed={batch.request_counts.completed}/{batch.request_counts.total}, "
                        f"failed={batch.request_counts.failed}")

            if status == "completed":
                break
            elif status in ("failed", "expired", "cancelled"):
                error_msg = f"Batch {batch_id} fehlgeschlagen: Status={status}"
                if batch.errors and batch.errors.data:
                    error_msg += f", Fehler: {batch.errors.data[0].message}"
                raise RuntimeError(error_msg)
            time.sleep(poll_interval)

        # Ergebnisse herunterladen und parsen
        output_file_id = batch.output_file_id
        if not output_file_id:
            raise RuntimeError(f"Batch {batch_id} hat keine Output-Datei")

        content = self.analysis_client.files.content(output_file_id)
        results = {}
        for line in content.text.strip().split("\n"):
            if not line.strip():
                continue
            entry = json.loads(line)
            custom_id = entry["custom_id"]
            resp_body = entry.get("response", {}).get("body", {})
            choices = resp_body.get("choices", [])
            if choices:
                raw = choices[0].get("message", {}).get("content", "{}")
                try:
                    results[custom_id] = json.loads(raw)
                except json.JSONDecodeError:
                    results[custom_id] = {"error": f"JSON-Parse-Fehler: {raw[:200]}"}
            else:
                err = entry.get("error", {})
                results[custom_id] = {"error": err.get("message", "Keine Antwort")}
        logger.info(f"Batch {batch_id}: {len(results)} Ergebnisse geparst")
        return results

    def _post_process_combined_spot(self, result: dict, spot: dict, date_str: str, region_result: dict = None) -> dict:
        """Wendet ALLE Post-Processing-Schritte auf ein Spot-Combined-Ergebnis an:
        Safety-Overrides, Foehn-Filter, Flyability-Tier-Normalisierung, Downgrade/Upgrade,
        Rating + Conditional-Flag. Wird von Single-Call- UND Batch-Pfad genutzt.

        Erwartet `result` als rohes LLM-JSON (bereits mit json.loads geparsed).

        region_result: Region-Analyse fuer diesen Tag (optional). Wird genutzt,
        um einen 'violet' Spot auf 'green' zu begrenzen, wenn die Region selbst
        nicht 'violet' ist — ein Spot kann nicht legendaer sein, wenn die
        umliegende Region es nicht ist.
        """
        name = spot["name"]
        result["spot"] = name
        result["date"] = date_str
        result["phase"] = "combined"

        # ═══ SAFETY POST-PROCESSING ═══

        gust_info = self._ctx_gust_cache.get(f"{name}|{date_str}", {})
        if gust_info:
            result["wind_ok_count"] = gust_info.get("wind_ok_count", 0)
            result["wind_wrong_count"] = gust_info.get("wind_wrong_count", 0)

        # Hard override: 0 WIND-OK Stunden = immer not_safe
        wind_ok = result.get("wind_ok_count", -1)
        if isinstance(wind_ok, int) and wind_ok == 0 and result.get("safety_status") != "not_safe":
            logger.warning(f"Safety-Override fuer {name}/{date_str}: LLM gab '{result.get('safety_status')}' trotz 0 WIND-OK Stunden → not_safe")
            result["safety_status"] = "not_safe"
            result["safe_window"] = "keins"
            nogo = result.get("no_go_reasons", [])
            if not any("Windrichtung" in r for r in nogo):
                nogo.append("Keine Stunde mit korrekter Windrichtung")
            result["no_go_reasons"] = nogo

        # ALOFT-Override: Hoehenwind-/Boeen-Gefahr >= N Stunden → Safety-Downgrade.
        # Deckt den Fall "Bodenwind ruhig, aber auf Flughoehe Dauer-Sturm" ab.
        # Zwei Stufen:
        #   - NOTSAFE_HOURS: hart → not_safe (NO-GO), auch wenn LLM 'conditional' gab.
        #   - CONDITIONAL_HOURS (nur wenn NOT triggered): safe → conditional.
        if gust_info:
            aloft_d = gust_info.get("aloft_danger_hours", 0)
            aloft_gd = gust_info.get("aloft_gust_danger_hours", 0)
            nogo_thresh = config.ALOFT_DANGER_NOTSAFE_HOURS
            cond_thresh = config.ALOFT_DANGER_CONDITIONAL_HOURS
            kmh_thresh = config.ALOFT_DANGER_KMH

            if (aloft_d >= nogo_thresh or aloft_gd >= nogo_thresh) \
                    and result.get("safety_status") != "not_safe":
                logger.warning(
                    f"Aloft-Danger-NoGo-Override fuer {name}/{date_str}: LLM gab "
                    f"'{result.get('safety_status')}' trotz ALOFT-DANGER {aloft_d}h / "
                    f"ALOFT-GUST-DANGER {aloft_gd}h (Schwelle {nogo_thresh}h) → not_safe"
                )
                result["safety_status"] = "not_safe"
                result["safe_window"] = "keins"
                if not result.get("primary_no_go"):
                    result["primary_no_go"] = "ALOFT_DANGER"
                nogo = result.get("no_go_reasons", []) or []
                bits = []
                if aloft_d >= nogo_thresh:
                    bits.append(f"Hoehenwind >{kmh_thresh} km/h in {aloft_d}h")
                if aloft_gd >= nogo_thresh:
                    bits.append(f"Hoehenboeen >{kmh_thresh} km/h in {aloft_gd}h")
                nogo.append("Kraeftiger Hoehenwind im Flugbereich: " + ", ".join(bits))
                result["no_go_reasons"] = nogo
            elif (aloft_d >= cond_thresh or aloft_gd >= cond_thresh) \
                    and result.get("safety_status") == "safe":
                logger.warning(
                    f"Aloft-Danger-Override fuer {name}/{date_str}: LLM gab 'safe' "
                    f"trotz ALOFT-DANGER {aloft_d}h / ALOFT-GUST-DANGER {aloft_gd}h "
                    f"(Schwelle {cond_thresh}h) → conditional"
                )
                result["safety_status"] = "conditional"
                cn = result.get("caution_notes", []) or []
                bits = []
                if aloft_d >= cond_thresh:
                    bits.append(f"Hoehenwind >{kmh_thresh} km/h im Flugbereich in {aloft_d}h")
                if aloft_gd >= cond_thresh:
                    bits.append(f"Hoehenboeen >{kmh_thresh} km/h im Flugbereich in {aloft_gd}h")
                cn.append("Gefahr in der Hoehe: " + ", ".join(bits) + " — auch bei ruhigem Bodenwind pruefen.")
                result["caution_notes"] = cn

        # Boeen-Floor: Mindestens conditional wenn Boeen vorhanden
        if gust_info:
            gwarn = gust_info.get("gust_warn_hours", 0) + gust_info.get("aloft_gust_warn_hours", 0)
            gdanger = gust_info.get("gust_danger_hours", 0) + gust_info.get("aloft_gust_danger_hours", 0)

            if (gwarn > 0 or gdanger > 0) and result.get("safety_status") == "safe":
                max_gust = int(gust_info.get("max_surface_gust", 0) or 0)
                logger.warning(
                    f"Boeen-Floor-Override fuer {name}/{date_str}: LLM gab 'safe' "
                    f"trotz GUST-WARN {gwarn}h / GUST-DANGER {gdanger}h → conditional"
                )
                result["safety_status"] = "conditional"
                cn = result.get("caution_notes", []) or []
                has_gust_note = any(
                    any(kw in (n or "").lower() for kw in ["böen", "böe", "gust", "turbulenz"])
                    for n in cn
                )
                if not has_gust_note:
                    bits = []
                    sfc_warn = gust_info.get("gust_warn_hours", 0)
                    alo_warn = gust_info.get("aloft_gust_warn_hours", 0)
                    if sfc_warn > 0 and max_gust > 0:
                        bits.append(f"Bodenboeen bis ~{max_gust} km/h in {sfc_warn}h")
                    elif sfc_warn > 0:
                        bits.append(f"Bodenboeen ueber 30 km/h in {sfc_warn}h")
                    if alo_warn > 0:
                        bits.append(f"Hoehenboeen ueber 30 km/h im Flugbereich in {alo_warn}h")
                    if gust_info.get("gust_danger_hours", 0) > 0:
                        bits.append(f"Bodenboeen ueber 40 km/h in {gust_info['gust_danger_hours']}h")
                    if gust_info.get("aloft_gust_danger_hours", 0) > 0:
                        bits.append(f"Hoehenboeen ueber 40 km/h in {gust_info['aloft_gust_danger_hours']}h")
                    cn.append(
                        "Starke Boeen erkannt: " + ", ".join(bits) +
                        " — Trend und Fenster pruefen."
                    )
                result["caution_notes"] = cn

        # Overclaim-Ceiling: LLM darf nicht grundlos 'not_safe' sagen
        if gust_info and result.get("safety_status") == "not_safe":
            has_hard_warnings = gust_info.get("hard_warning_hours", 0) > 0
            clean_cnt = gust_info.get("clean_hours_count", 0)
            if not has_hard_warnings and clean_cnt >= 4:
                logger.warning(
                    f"Overclaim-Override fuer {name}/{date_str}: LLM gab 'not_safe' "
                    f"trotz {clean_cnt}h sauberen Stunden und 0 harten Warnungen → conditional"
                )
                result["safety_status"] = "conditional"
                cn = result.get("caution_notes", []) or []
                cn.append(
                    f"Automatische Korrektur: Die Wetterdaten zeigen {clean_cnt} saubere "
                    f"Flugstunden ohne harte Warnungen — bitte Meteogramm selbst pruefen."
                )
                result["caution_notes"] = cn
                result["no_go_reasons"] = []

        # Foehn-Richtungs-Override
        krit_foehn = spot.get("kritischer_foehn", "Süd")
        result = self._strip_irrelevant_foehn(result, krit_foehn)

        # ═══ FLYABILITY POST-PROCESSING ═══

        # Wenn not_safe: Flyability- und Streckenflug-Felder leeren
        if result.get("safety_status") == "not_safe":
            result["fly_status"] = ""
            result["flyability_tier"] = ""
            result["streckenflug"] = {
                "tier": "kein_xc", "rating": 0,
                "summary": "", "limiting_factor": "spot_not_flyable",
                "region_context_available": False,
            }
            # Rating trotzdem berechnen (für not_safe → 0)
            result["rating"] = _compute_rating_from_subratings(result, "", "not_safe")
            result["is_conditional"] = False
            result["conditional_reason"] = ""
            return result

        # Tier normalisieren
        tier = _normalize_flyability_tier(
            result.get("flyability_tier") or result.get("fly_status") or ""
        )
        result["flyability_tier"] = tier
        result["fly_status"] = tier

        # Tag-Sanitierung
        _sanitize_llm_result(result)

        # Deterministische Flyability-Overrides
        tq = self._ctx_tq_cache.get(f"{name}|{date_str}", {})
        if tq:
            tht = tq.get("thermal_hours_total", 0)
            rough_h = tq.get("rough_danger_h", 0)
            peak = tq.get("peak_climb_proxy", 0)
            prod_h = tq.get("productive_thermal_h", 0)

            # Downgrade: green/violet → gray
            if tier in ("green", "violet"):
                downgrade = False
                reason = ""
                if tht == 0 or peak < 0.3:
                    downgrade = True
                    reason = f"keine Thermik (peak={peak:.1f}, hours={tht})"
                elif tht > 0:
                    rough_pct = (rough_h / max(1, tht)) * 100
                    if rough_pct > 50:
                        downgrade = True
                        reason = f"ROUGH-UNUSABLE={rough_pct:.0f}% ({rough_h}/{tht}h, mech. gefaehrlich)"
                    elif prod_h < config.PRODUCTIVE_HOURS_DOWNGRADE:
                        downgrade = True
                        reason = f"Nur {prod_h}h produktive Thermik (min {config.PRODUCTIVE_HOURS_DOWNGRADE}h)"
                if downgrade:
                    result["fly_status"] = "gray"
                    result["flyability_tier"] = "gray"
                    logger.warning(
                        f"Flyability-Downgrade: {name}/{date_str} {tier}→gray ({reason})"
                    )

            # gray→green Upgrade
            final_tier = result.get("fly_status", result.get("flyability_tier", "gray"))
            if final_tier == "gray" and tht > 0:
                rough_pct = (rough_h / max(1, tht)) * 100
                if prod_h >= config.PRODUCTIVE_HOURS_FOR_GREEN and rough_pct < 50:
                    result["fly_status"] = "green"
                    result["flyability_tier"] = "green"
                    result["peak_climb_rate"] = round(peak, 1)
                    if peak >= 1.5:
                        result["flight_type"] = "Thermikflug"
                        result["flight_duration_estimate"] = f"2-3h Thermikflug (Peak {peak:.1f} m/s)"
                    else:
                        result["flight_type"] = "Soaring+Thermik"
                        result["flight_duration_estimate"] = f"1-2h Soaring/Thermik"
                    if prod_h >= 5:
                        result["xc_potential"] = "moderate"
                    result["recommendation"] = (
                        f"System-Korrektur: Die Daten zeigen {peak:.1f} m/s Peak-Thermik "
                        f"mit {prod_h}h produktiver Thermik (ROUGH-UNUSABLE nur {rough_pct:.0f}%). "
                        f"Gute Bedingungen fuer Thermikfluege."
                    )
                    logger.warning(
                        f"Flyability-Override: {name}/{date_str} gray→green "
                        f"(peak={peak:.1f}, ROUGH={rough_pct:.0f}%, productive_h={prod_h})"
                    )

        # ═══ REGION-GATING: violet nur wenn Region auch violet ═══
        # Ein Spot kann nicht 'legendaer' (violet) sein, wenn die umliegende
        # Region nicht mindestens ebenfalls violet ist. In dem Fall → green.
        current_tier = result.get("flyability_tier") or result.get("fly_status") or ""
        if current_tier == "violet" and region_result:
            region_tier = _normalize_flyability_tier(
                region_result.get("flyability_tier") or region_result.get("fly_status") or ""
            )
            if region_tier and region_tier != "violet":
                result["fly_status"] = "green"
                result["flyability_tier"] = "green"
                rname = region_result.get("region", "")
                logger.warning(
                    f"Flyability-Region-Gate: {name}/{date_str} violet→green "
                    f"(Region '{rname}' tier={region_tier}, nicht violet)"
                )

        # ═══ STRECKENFLUG POST-PROCESSING ═══
        final_tier = result.get("fly_status", result.get("flyability_tier", "gray")) or ""
        final_safety = result.get("safety_status", "")
        sf = result.get("streckenflug")
        if not isinstance(sf, dict):
            # LLM hat Feld nicht geliefert → Default aus Spot-Daten ableiten
            sf = {
                "tier": "kein_xc", "rating": 0,
                "summary": "", "limiting_factor": "none",
                "region_context_available": False,
            }
        # Whitelist-Validierung
        valid_tiers = {"kein_xc", "lokal", "moderat", "top"}
        if sf.get("tier") not in valid_tiers:
            sf["tier"] = "kein_xc"
        try:
            sf["rating"] = max(0, min(10, int(round(float(sf.get("rating", 0) or 0)))))
        except (TypeError, ValueError):
            sf["rating"] = 0
        sf["summary"] = str(sf.get("summary", "") or "")
        valid_limits = {
            "none", "spot_not_flyable", "spot_wind_direction",
            "region_wind_aloft", "weak_regional_thermals",
            "ceiling_low", "abgleiter_only",
        }
        if sf.get("limiting_factor") not in valid_limits:
            sf["limiting_factor"] = "none"
        sf["region_context_available"] = bool(sf.get("region_context_available", False))

        # Konsistenz-Check: Spot gray → Streckenflug muss kein_xc sein
        if final_tier == "gray" and sf["tier"] != "kein_xc":
            logger.info(
                f"Streckenflug-Konsistenz: {name}/{date_str} tier={sf['tier']} → kein_xc "
                f"(Spot fly_status=gray)"
            )
            sf["tier"] = "kein_xc"
            if sf["limiting_factor"] == "none":
                sf["limiting_factor"] = "abgleiter_only"
            sf["rating"] = 0

        # Abgleiter/Soaring → max kein_xc (keine Thermik-Grundlage fuer Strecke)
        if result.get("flight_type") in ("Abgleiter", "Soaring") and sf["tier"] != "kein_xc":
            sf["tier"] = "kein_xc"
            if sf["limiting_factor"] == "none":
                sf["limiting_factor"] = "abgleiter_only"
            sf["rating"] = 0

        result["streckenflug"] = sf

        # Rating + Conditional-Flag
        result["rating"] = _compute_rating_from_subratings(result, final_tier, final_safety)
        is_cond = bool(result.get("is_conditional", False))
        if final_safety == "not_safe":
            is_cond = False
        result["is_conditional"] = is_cond
        result["conditional_reason"] = (result.get("conditional_reason", "") or "") if is_cond else ""

        return result

    def _post_process_combined_region(self, result: dict, region: dict, date_str: str) -> dict:
        """Wendet ALLE Post-Processing-Schritte auf ein Region-Combined-Ergebnis an.
        Analog zu _post_process_combined_spot, aber mit Region-Wind-Tags (CALM/MODERATE/STRONG)
        statt WIND-OK/WRONG und ohne BOEEN-FLOOR-Override (gilt nur pro Spot).
        """
        rname = region["region"]
        result["region"] = rname
        result["region_id"] = region["id"]
        result["date"] = date_str
        result["phase"] = "combined"

        # ═══ SAFETY POST-PROCESSING ═══

        # Hard override: WIND-STRONG Mehrheit ohne WIND-CALM → not_safe
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
            if not any(kw in (r or "").lower() for r in nogo for kw in ["starker wind", "wind-strong", "zu stark"]):
                nogo.append(f"Durchgehend starker Wind ({strong} von {strong + moderate} Stunden), keine ruhige Phase")
            result["no_go_reasons"] = nogo

        # ALOFT-Override (Region): Höhenwind-Gefahr >= N Stunden → Safety-Downgrade.
        # Regionen haben keine Böen mehr (Apr 2026), daher nur ALOFT-DANGER (Wind).
        # Zwei Stufen:
        #   - NOTSAFE_HOURS: hart → not_safe (NO-GO), auch wenn LLM 'conditional' gab.
        #   - CONDITIONAL_HOURS (nur wenn NOT triggered): safe → conditional.
        region_gust_info = self._ctx_gust_cache.get(f"{rname}|{date_str}", {})
        if region_gust_info:
            aloft_d = region_gust_info.get("aloft_danger_hours", 0)
            nogo_thresh = config.ALOFT_DANGER_NOTSAFE_HOURS
            cond_thresh = config.ALOFT_DANGER_CONDITIONAL_HOURS
            kmh_thresh = config.ALOFT_DANGER_KMH

            if aloft_d >= nogo_thresh and result.get("safety_status") != "not_safe":
                logger.warning(
                    f"Region Aloft-Danger-NoGo-Override fuer {rname}/{date_str}: LLM gab "
                    f"'{result.get('safety_status')}' trotz ALOFT-DANGER {aloft_d}h "
                    f"(Schwelle {nogo_thresh}h) → not_safe"
                )
                result["safety_status"] = "not_safe"
                result["safe_window"] = "keins"
                if not result.get("primary_no_go"):
                    result["primary_no_go"] = "ALOFT_DANGER"
                nogo = result.get("no_go_reasons", []) or []
                nogo.append(
                    f"Kraeftiger Hoehenwind im Flugbereich: >{kmh_thresh} km/h in {aloft_d}h"
                )
                result["no_go_reasons"] = nogo
            elif aloft_d >= cond_thresh and result.get("safety_status") == "safe":
                logger.warning(
                    f"Region Aloft-Danger-Override fuer {rname}/{date_str}: LLM gab 'safe' "
                    f"trotz ALOFT-DANGER {aloft_d}h (Schwelle {cond_thresh}h) → conditional"
                )
                result["safety_status"] = "conditional"
                cn = result.get("caution_notes", []) or []
                cn.append(
                    f"Gefahr in der Höhe: Höhenwind >{kmh_thresh} km/h in {aloft_d}h — "
                    f"auch bei ruhigem Bodenwind prüfen."
                )
                result["caution_notes"] = cn

        # Foehn-Richtungs-Override
        krit_foehn = region.get("kritischer_foehn", "Beide")
        result = self._strip_irrelevant_foehn(result, krit_foehn)

        # ═══ FLYABILITY POST-PROCESSING ═══

        if result.get("safety_status") == "not_safe":
            result["fly_status"] = ""
            result["flyability_tier"] = ""
            result["rating"] = _compute_rating_from_subratings(result, "", "not_safe")
            result["is_conditional"] = False
            result["conditional_reason"] = ""
            return result

        tier = _normalize_flyability_tier(
            result.get("flyability_tier") or result.get("fly_status") or ""
        )
        result["flyability_tier"] = tier
        result["fly_status"] = tier

        _sanitize_llm_result(result)

        tq = self._ctx_tq_cache.get(f"{rname}|{date_str}", {})
        if tq:
            tht = tq.get("thermal_hours_total", 0)
            rough_h = tq.get("rough_danger_h", 0)
            peak = tq.get("peak_climb_proxy", 0)
            prod_h = tq.get("productive_thermal_h", 0)

            if tier in ("green", "violet"):
                downgrade = False
                reason = ""
                if tht == 0 or peak < 0.3:
                    downgrade = True
                    reason = f"keine Thermik (peak={peak:.1f}, hours={tht})"
                elif tht > 0:
                    rough_pct = (rough_h / max(1, tht)) * 100
                    if rough_pct > 50:
                        downgrade = True
                        reason = f"ROUGH-UNUSABLE={rough_pct:.0f}% ({rough_h}/{tht}h, mech. gefaehrlich)"
                    elif prod_h < config.PRODUCTIVE_HOURS_DOWNGRADE:
                        downgrade = True
                        reason = f"Nur {prod_h}h produktive Thermik (min {config.PRODUCTIVE_HOURS_DOWNGRADE}h)"
                if downgrade:
                    result["fly_status"] = "gray"
                    result["flyability_tier"] = "gray"
                    logger.warning(
                        f"Flyability-Downgrade: {rname}/{date_str} {tier}→gray ({reason})"
                    )

            final_tier = result.get("fly_status", result.get("flyability_tier", "gray"))
            if final_tier == "gray" and tht > 0:
                rough_pct = (rough_h / max(1, tht)) * 100
                if prod_h >= config.PRODUCTIVE_HOURS_FOR_GREEN and rough_pct < 50:
                    result["fly_status"] = "green"
                    result["flyability_tier"] = "green"
                    result["peak_climb_rate"] = round(peak, 1)
                    if peak >= 1.5:
                        result["flight_type"] = "Thermikflug"
                        result["flight_duration_estimate"] = f"2-3h Thermikflug (Peak {peak:.1f} m/s)"
                    else:
                        result["flight_type"] = "Soaring+Thermik"
                        result["flight_duration_estimate"] = f"1-2h Soaring/Thermik"
                    if prod_h >= 5:
                        result["xc_potential"] = "moderate"
                    result["recommendation"] = (
                        f"System-Korrektur: Die Daten zeigen {peak:.1f} m/s Peak-Thermik "
                        f"mit {prod_h}h produktiver Thermik (ROUGH-UNUSABLE nur {rough_pct:.0f}%). "
                        f"Gute Bedingungen fuer Thermikfluege in der Region."
                    )
                    logger.warning(
                        f"Flyability-Override: {rname}/{date_str} gray→green "
                        f"(peak={peak:.1f}, ROUGH={rough_pct:.0f}%, productive_h={prod_h})"
                    )

        final_tier = result.get("fly_status", result.get("flyability_tier", "gray")) or ""
        final_safety = result.get("safety_status", "")
        result["rating"] = _compute_rating_from_subratings(result, final_tier, final_safety)
        is_cond = bool(result.get("is_conditional", False))
        if final_safety == "not_safe":
            is_cond = False
        result["is_conditional"] = is_cond
        result["conditional_reason"] = (result.get("conditional_reason", "") or "") if is_cond else ""

        return result

    def run_all_analyses_batch_stream(self):
        """Batch-Modus zweiphasig: Phase 1 Region-Batch → Phase 2 Spot-Batch mit
        injiziertem Region-Kontext fuer Streckenflug-Synthese. Selbe LLM-Call-Anzahl
        wie Single-Phase, aber zwei Batch-Roundtrips (Regionen muessen fertig sein
        bevor Spots gebaut werden koennen).
        """
        if not self.analysis_client:
            yield {"event": "error", "data": {"message": f"Kein API-Key fuer Analyse-Provider '{self.analysis_provider}'"}}
            return
        if self.analysis_provider != "openai":
            yield {"event": "error", "data": {"message": (
                f"Batch-Modus nur mit ANALYSIS_PROVIDER=openai moeglich (aktuell: "
                f"'{self.analysis_provider}'). Bitte LLM_ANALYSIS_MODE=parallel setzen."
            )}}
            return

        from source_area import find_region_for_point as _find_region

        all_regions = get_all_regions()
        regions_with_data = [r for r in all_regions if r["id"] in self.region_weather_data] if self.region_weather_data else []
        spots_to_analyze = [s for s in self.spots if s["name"] in self.weather_data] if self.weather_data else []
        forecast_dates = self._get_forecast_dates()
        _now = datetime.now()
        now_str = f"{_now.strftime('%Y-%m-%d %H:%M:%S')} ({_weekday_de(_now)})"

        total_items = (len(regions_with_data) + len(spots_to_analyze)) * len(forecast_dates)
        yield {"event": "init", "data": {
            "mode": "batch",
            "regions_count": len(regions_with_data),
            "spots_count": len(spots_to_analyze),
            "days": len(forecast_dates),
            "total_calls": total_items,
        }}

        region_results: dict = {}
        spot_results: dict = {}

        # ══════════════════════════════════════════════════════════════
        # PHASE 1: Region-Batch
        # ══════════════════════════════════════════════════════════════
        yield {"event": "phase", "data": {"phase": "batch_build_regions", "total": 0}}
        region_requests: list = []
        region_meta: dict = {}

        for region in regions_with_data:
            rid = region["id"]
            for date_str in forecast_dates:
                ctx = self._build_single_region_context(region, date_str)
                if not ctx:
                    continue
                cid = f"region_combined|{rid}|{date_str}"
                region_requests.append({
                    "custom_id": cid,
                    "method": "POST",
                    "url": "/v1/chat/completions",
                    "body": {
                        "model": self.analysis_model,
                        "messages": [
                            {"role": "system", "content": prompts.REGION_COMBINED_PROMPT},
                            {"role": "user", "content": f"AKTUELLE LOKALZEIT: {now_str}\n\n{ctx}"},
                        ],
                        "temperature": 0.2,
                        "max_tokens": 1100,
                        "response_format": {"type": "json_object"},
                    },
                })
                region_meta[cid] = (rid, date_str, region)

        if region_requests:
            yield {"event": "phase", "data": {"phase": "batch_submit_regions", "total": len(region_requests)}}
            try:
                jsonl = self._build_batch_jsonl(region_requests)
                region_batch_id = self._submit_batch(jsonl, f"Regions ({len(region_requests)} Requests)")
            except Exception as e:
                logger.error(f"Region-Batch-Submit fehlgeschlagen: {e}")
                yield {"event": "error", "data": {"message": f"Region-Batch-Submit fehlgeschlagen: {e}"}}
                return

            yield {"event": "phase", "data": {"phase": "batch_poll_regions",
                                               "batch_id": region_batch_id,
                                               "total": len(region_requests)}}
            try:
                region_raw = self._poll_batch(region_batch_id)
            except Exception as e:
                logger.error(f"Region-Batch-Poll fehlgeschlagen: {e}")
                yield {"event": "error", "data": {"message": f"Region-Batch fehlgeschlagen: {e}"}}
                return

            for cid, raw_result in region_raw.items():
                m = region_meta.get(cid)
                if not m:
                    continue
                rid, date_str, region = m
                if raw_result.get("error"):
                    region_results.setdefault(rid, {})[date_str] = {
                        "safety_status": "error", "phase": "combined",
                        "date": date_str, "region": region["region"], "region_id": rid,
                        "error": raw_result["error"],
                    }
                    continue
                try:
                    processed = self._post_process_combined_region(raw_result, region, date_str)
                    region_results.setdefault(rid, {})[date_str] = processed
                except Exception as e:
                    logger.error(f"[BATCH-PHASE1] Post-Processing fuer {rid}/{date_str}: {e}")
                    region_results.setdefault(rid, {})[date_str] = {
                        "safety_status": "error", "phase": "combined",
                        "date": date_str, "region": region["region"], "region_id": rid,
                        "error": str(e),
                    }

            yield {"event": "progress", "data": {
                "phase": "batch_regions_done",
                "completed": len(region_raw),
                "total": len(region_requests),
            }}
            logger.info(f"[BATCH] Phase 1 fertig: {len(region_results)} Regionen analysiert")

        # ══════════════════════════════════════════════════════════════
        # PHASE 2: Spot-Batch mit injiziertem Region-Kontext
        # ══════════════════════════════════════════════════════════════
        yield {"event": "phase", "data": {"phase": "batch_build_spots", "total": 0}}

        # Pro-Spot Region-Mapping einmalig vorberechnen
        spot_region_map: dict = {}
        for spot in spots_to_analyze:
            try:
                reg = _find_region(spot["latitude"], spot["longitude"])
                spot_region_map[spot["name"]] = reg["id"] if reg else None
            except Exception as e:
                logger.warning(f"Region-Mapping fuer {spot['name']} fehlgeschlagen: {e}")
                spot_region_map[spot["name"]] = None

        spot_requests: list = []
        spot_meta: dict = {}

        for spot in spots_to_analyze:
            name = spot["name"]
            rid = spot_region_map.get(name)
            for date_str in forecast_dates:
                # Region-Ergebnis fuer diesen Spot/Tag raussuchen
                region_result = None
                if rid and rid in region_results:
                    rr = region_results[rid].get(date_str)
                    if rr and rr.get("safety_status") not in ("error", "no_data"):
                        region_result = rr

                ctx = self._build_single_spot_context(
                    spot, date_str, mode="analysis",
                    region_analysis_result=region_result,
                )
                if not ctx:
                    continue
                cid = f"spot_combined|{name}|{date_str}"
                spot_requests.append({
                    "custom_id": cid,
                    "method": "POST",
                    "url": "/v1/chat/completions",
                    "body": {
                        "model": self.analysis_model,
                        "messages": [
                            {"role": "system", "content": prompts.SPOT_COMBINED_PROMPT},
                            {"role": "user", "content": f"AKTUELLE LOKALZEIT: {now_str}\n\n{ctx}"},
                        ],
                        "temperature": 0.2,
                        "max_tokens": 1100,
                        "response_format": {"type": "json_object"},
                    },
                })
                spot_meta[cid] = (name, date_str, spot)

        if not spot_requests and not region_requests:
            yield {"event": "error", "data": {"message": "Keine Requests aufgebaut"}}
            return

        if spot_requests:
            yield {"event": "phase", "data": {"phase": "batch_submit_spots", "total": len(spot_requests)}}
            try:
                jsonl = self._build_batch_jsonl(spot_requests)
                spot_batch_id = self._submit_batch(jsonl, f"Spots ({len(spot_requests)} Requests)")
            except Exception as e:
                logger.error(f"Spot-Batch-Submit fehlgeschlagen: {e}")
                yield {"event": "error", "data": {"message": f"Spot-Batch-Submit fehlgeschlagen: {e}"}}
                return

            yield {"event": "phase", "data": {"phase": "batch_poll_spots",
                                               "batch_id": spot_batch_id,
                                               "total": len(spot_requests)}}
            try:
                spot_raw = self._poll_batch(spot_batch_id)
            except Exception as e:
                logger.error(f"Spot-Batch-Poll fehlgeschlagen: {e}")
                yield {"event": "error", "data": {"message": f"Spot-Batch fehlgeschlagen: {e}"}}
                return

            for cid, raw_result in spot_raw.items():
                m = spot_meta.get(cid)
                if not m:
                    continue
                name, date_str, spot = m
                if raw_result.get("error"):
                    spot_results.setdefault(name, {})[date_str] = {
                        "safety_status": "error", "phase": "combined",
                        "date": date_str, "spot": name,
                        "error": raw_result["error"],
                    }
                    continue
                try:
                    rid = spot_region_map.get(name)
                    region_result = None
                    if rid and rid in region_results:
                        rr = region_results[rid].get(date_str)
                        if rr and rr.get("safety_status") not in ("error", "no_data"):
                            region_result = rr
                    processed = self._post_process_combined_spot(raw_result, spot, date_str, region_result=region_result)
                    spot_results.setdefault(name, {})[date_str] = processed
                except Exception as e:
                    logger.error(f"[BATCH-PHASE2] Post-Processing fuer {name}/{date_str}: {e}")
                    spot_results.setdefault(name, {})[date_str] = {
                        "safety_status": "error", "phase": "combined",
                        "date": date_str, "spot": name,
                        "error": str(e),
                    }

            yield {"event": "progress", "data": {
                "phase": "batch_spots_done",
                "completed": len(spot_raw),
                "total": len(spot_requests),
            }}
            logger.info(f"[BATCH] Phase 2 fertig: {sum(len(d) for d in spot_results.values())} Spot-Ergebnisse")

        # ── Merge: Spot-Ergebnisse (identisch zu run_all_analyses_stream Merge) ──
        spot_merged: dict = {}
        for spot_name, days_dict in spot_results.items():
            spot_merged[spot_name] = {}
            for date_str, result in days_dict.items():
                safety_status = result.get("safety_status", "error")
                safety = {
                    "safety_status": safety_status,
                    "safe_window": result.get("safe_window", "keins"),
                    "no_go_reasons": result.get("no_go_reasons", []),
                    "caution_notes": result.get("caution_notes", []),
                    "primary_no_go": result.get("primary_no_go"),
                    "primary_caution": result.get("primary_caution"),
                    "primary_reducer": result.get("primary_reducer"),
                    "primary_booster": result.get("primary_booster"),
                    "wind_summary": result.get("wind_summary", ""),
                    "wind_shear": result.get("wind_shear", ""),
                    "foehn_risk": result.get("foehn_risk", "none"),
                    "summary": result.get("summary", ""),
                    "spot": result.get("spot", spot_name),
                    "date": date_str,
                    "wind_ok_count": result.get("wind_ok_count", 0),
                    "wind_wrong_count": result.get("wind_wrong_count", 0),
                    "error": result.get("error", ""),
                }
                entry = {"safety": safety}
                entry["rating"] = float(result.get("rating", 0.0) or 0.0)
                entry["is_conditional"] = bool(result.get("is_conditional", False))
                entry["conditional_reason"] = result.get("conditional_reason", "") or ""
                tier = result.get("flyability_tier") or result.get("fly_status") or ""
                if safety_status in ("safe", "conditional") and tier:
                    fly = {
                        "flyability_tier": tier, "fly_status": tier, "status": tier,
                        "flight_type": result.get("flight_type", ""),
                        "flight_duration_estimate": result.get("flight_duration_estimate", ""),
                        "thermal_quality": result.get("thermal_quality", ""),
                        "peak_climb_rate": result.get("peak_climb_rate", 0),
                        "xc_potential": result.get("xc_potential", ""),
                        "xc_details": result.get("xc_details", ""),
                        "soaring_options": result.get("soaring_options", ""),
                        "bemerkung_check": result.get("bemerkung_check", ""),
                        "best_window": result.get("best_window", ""),
                        "flyability_limits": result.get("flyability_limits", []),
                        "highlights": result.get("highlights", []),
                        "recommendation": result.get("recommendation", ""),
                        "confidence": result.get("confidence", ""),
                        "rating": entry["rating"],
                        "is_conditional": entry["is_conditional"],
                        "conditional_reason": entry["conditional_reason"],
                        "spot": result.get("spot", spot_name), "date": date_str,
                    }
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
                    entry["status"] = safety_status
                entry["streckenflug"] = result.get("streckenflug") or {
                    "tier": "kein_xc", "rating": 0,
                    "summary": "", "limiting_factor": "spot_not_flyable" if safety_status == "not_safe" else "none",
                    "region_context_available": False,
                }
                entry["best_window"] = result.get("best_window") or safety.get("safe_window", "keins")
                entry["recommendation"] = result.get("recommendation", "")
                spot_merged[spot_name][date_str] = entry

        self.spot_analyses = spot_merged
        self.analyses_loaded_at = datetime.now()
        self._analyses_stale = False
        self._save_analyses_cache()
        if self.instantdb:
            threading.Thread(target=self._push_analyses_to_instantdb, daemon=True).start()

        # ── Merge: Region-Ergebnisse ──
        regions_by_id = {r["id"]: r for r in regions_with_data}
        region_merged: dict = {}
        for rid, days_dict in region_results.items():
            region_merged[rid] = {}
            for date_str, result in days_dict.items():
                safety_status = result.get("safety_status", "error")
                safety = {
                    "safety_status": safety_status,
                    "safe_window": result.get("safe_window", "keins"),
                    "no_go_reasons": result.get("no_go_reasons", []),
                    "caution_notes": result.get("caution_notes", []),
                    "primary_no_go": result.get("primary_no_go"),
                    "primary_caution": result.get("primary_caution"),
                    "primary_reducer": result.get("primary_reducer"),
                    "primary_booster": result.get("primary_booster"),
                    "wind_summary": result.get("wind_summary", ""),
                    "wind_shear": result.get("wind_shear", ""),
                    "foehn_risk": result.get("foehn_risk", "none"),
                    "summary": result.get("summary", ""),
                    "region": result.get("region", ""),
                    "region_id": result.get("region_id", rid),
                    "date": date_str,
                    "wind_calm_count": result.get("wind_calm_count", 0),
                    "wind_moderate_count": result.get("wind_moderate_count", 0),
                    "wind_strong_count": result.get("wind_strong_count", 0),
                    "error": result.get("error", ""),
                }
                entry = {"safety": safety}
                entry["rating"] = float(result.get("rating", 0.0) or 0.0)
                entry["is_conditional"] = bool(result.get("is_conditional", False))
                entry["conditional_reason"] = result.get("conditional_reason", "") or ""
                tier = result.get("flyability_tier") or result.get("fly_status") or ""
                if safety_status in ("safe", "conditional") and tier:
                    fly = {
                        "flyability_tier": tier, "fly_status": tier, "status": tier,
                        "flight_type": result.get("flight_type", ""),
                        "flight_duration_estimate": result.get("flight_duration_estimate", ""),
                        "thermal_quality": result.get("thermal_quality", ""),
                        "peak_climb_rate": result.get("peak_climb_rate", 0),
                        "xc_potential": result.get("xc_potential", ""),
                        "xc_details": result.get("xc_details", ""),
                        "best_window": result.get("best_window", ""),
                        "flyability_limits": result.get("flyability_limits", []),
                        "highlights": result.get("highlights", []),
                        "recommendation": result.get("recommendation", ""),
                        "confidence": result.get("confidence", ""),
                        "rating": entry["rating"],
                        "is_conditional": entry["is_conditional"],
                        "conditional_reason": entry["conditional_reason"],
                        "region": result.get("region", ""),
                        "region_id": result.get("region_id", rid), "date": date_str,
                    }
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
                    entry["status"] = safety_status
                entry["best_window"] = result.get("best_window") or safety.get("safe_window", "keins")
                entry["recommendation"] = result.get("recommendation", "")
                entry["region_name"] = result.get("region", regions_by_id.get(rid, {}).get("region", rid))
                region_merged[rid][date_str] = entry

        self.region_analyses = region_merged
        self.region_analyses_loaded_at = datetime.now()
        self._save_region_analyses_cache()
        if self.instantdb:
            threading.Thread(target=self._push_region_analyses_to_instantdb, daemon=True).start()

        total_calls = len(requests)
        logger.info(f"Batch-Combined-Analysen abgeschlossen: {total_calls} Calls "
                    f"(Single-Phase, halbiert vs. vorher 2-Phasen)")

        yield {"event": "done", "data": {
            "success": True,
            "mode": "batch",
            "total_calls": total_calls,
            "combined_count": total_calls,
            "safety_count": total_calls,  # Rueckwaertskompatibilitaet UI
            "flyability_count": 0,
        }}

    def run_all_analyses_stream(self):
        """Orchestrator: Regionen + Spots PARALLEL in einem gemeinsamen Pool.
        Einzelne Phase: kombinierte Safety+Flyability-Calls fuer alle Spots/Regionen.
        Dispatcht zum Batch-Modus wenn config.LLM_ANALYSIS_MODE == 'batch'.
        """
        # Batch-API nur mit OpenAI. Bei anderem Provider automatisch auf parallel fallen.
        if config.LLM_ANALYSIS_MODE == "batch":
            if self.analysis_provider == "openai":
                yield from self.run_all_analyses_batch_stream()
                return
            logger.warning(
                "LLM_ANALYSIS_MODE=batch ignoriert — Batch-API nur fuer OpenAI verfuegbar, "
                "aktueller Analyse-Provider: '%s'. Falle auf parallel-Modus zurueck.",
                self.analysis_provider,
            )

        self._api_abort = threading.Event()
        self._api_abort_reason = 'Analyse abgebrochen'
        self._ctx_gust_cache.clear()
        self._ctx_tq_cache.clear()

        if not self.analysis_client:
            yield {"event": "error", "data": {"message": f"Kein API-Key fuer Analyse-Provider '{self.analysis_provider}'"}}
            return

        all_regions = get_all_regions()
        regions_with_data = [r for r in all_regions if r["id"] in self.region_weather_data] if self.region_weather_data else []
        spots_to_analyze = [s for s in self.spots if s["name"] in self.weather_data] if self.weather_data else []
        forecast_dates = self._get_forecast_dates()

        if not forecast_dates:
            yield {"event": "error", "data": {"message": "Keine Vorhersage-Tage verfuegbar"}}
            return

        regions_by_id = {r["id"]: r for r in regions_with_data}
        spots_by_name = {s["name"]: s for s in spots_to_analyze}
        n_days = len(forecast_dates)

        # Pre-validation fuer Spots
        from fetch_weather import validate_spot_data
        incomplete_spot_days = {}
        for spot in spots_to_analyze:
            name = spot["name"]
            spot_data = self.weather_data.get(name, {})
            hourly_data = spot_data.get("hourly_data", {})
            missing = validate_spot_data(name, hourly_data, config.FORECAST_DAYS)
            if missing:
                incomplete_spot_days[name] = set(missing)

        total = len(regions_with_data) * n_days + len(spots_to_analyze) * n_days

        yield {"event": "init", "data": {
            "regions_count": len(regions_with_data),
            "spots_count": len(spots_to_analyze),
            "days": n_days, "total_calls": total,
        }}

        try:
            # ══════════════════════════════════════════════════════════════
            # PHASE 1: Region-Analysen (Regionen-Kontext fuer Phase 2 erforderlich)
            # PHASE 2: Spot-Analysen (inkl. Streckenflug-Synthese mit Region-Kontext)
            # ══════════════════════════════════════════════════════════════
            from source_area import find_region_for_point as _find_region
            region_total = len(regions_with_data) * n_days
            spot_total = total - region_total

            spot_results = {}       # {spot_name: {date: result}}
            region_results = {}     # {rid: {date: result}}
            completed = 0
            skipped_no_data = 0

            # No-data Eintraege vorab sammeln
            for spot in spots_to_analyze:
                name = spot["name"]
                for date_str in forecast_dates:
                    if date_str in incomplete_spot_days.get(name, set()):
                        spot_results.setdefault(name, {})[date_str] = {
                            "spot": name, "date": date_str,
                            "safety_status": "no_data", "phase": "combined",
                            "summary": "Wetterdaten unvollstaendig",
                        }
                        skipped_no_data += 1
                        completed += 1

            # ── PHASE 1: Regionen ──
            yield {"event": "phase", "data": {"phase": "regions", "total": region_total}}
            logger.info(f"[UNIFIED] Phase 1 (Regionen): {region_total} Calls "
                        f"({len(regions_with_data)} Regionen x {n_days} Tage)")

            with ThreadPoolExecutor(max_workers=config.LLM_MAX_WORKERS) as executor:
                region_futures = {}
                for region in regions_with_data:
                    rid = region["id"]
                    for date_str in forecast_dates:
                        future = executor.submit(self._build_and_analyze_region, region, date_str)
                        region_futures[future] = (rid, date_str)

                remaining = set(region_futures.keys())
                while remaining:
                    done, remaining = wait(remaining, timeout=self._HEARTBEAT_INTERVAL, return_when=FIRST_COMPLETED)
                    if not done:
                        yield self._HEARTBEAT_EVENT
                        continue
                    for future in done:
                        rid, date_str = region_futures[future]
                        try:
                            result = future.result()
                        except Exception as e:
                            logger.error(f"Region-Future {rid}/{date_str}: {e}")
                            result = {"region_id": rid, "region": rid, "date": date_str, "safety_status": "error", "error": str(e)}
                        region_results.setdefault(rid, {})[date_str] = result
                        completed += 1
                        yield {"event": "progress", "data": {
                            "phase": "regions", "type": "region",
                            "name": rid, "date": date_str,
                            "completed": completed, "total": total,
                            "result": result.get("flyability_tier") or result.get("safety_status", "error"),
                        }}

            logger.info(f"[UNIFIED] Phase 1 fertig: {len(region_results)} Regionen analysiert")

            # ── PHASE 2: Spots (mit injiziertem Region-Kontext) ──
            yield {"event": "phase", "data": {"phase": "spots", "total": spot_total}}
            logger.info(f"[UNIFIED] Phase 2 (Spots): {spot_total} Calls "
                        f"({len(spots_to_analyze)} Spots x {n_days} Tage)")

            # Pro-Spot Region-Mapping einmalig vorberechnen (Point-in-Polygon)
            spot_region_map = {}  # spot_name → region_id oder None
            for spot in spots_to_analyze:
                try:
                    reg = _find_region(spot["latitude"], spot["longitude"])
                    spot_region_map[spot["name"]] = reg["id"] if reg else None
                except Exception as e:
                    logger.warning(f"Region-Mapping fuer {spot['name']} fehlgeschlagen: {e}")
                    spot_region_map[spot["name"]] = None

            with ThreadPoolExecutor(max_workers=config.LLM_MAX_WORKERS) as executor:
                spot_futures = {}
                for spot in spots_to_analyze:
                    name = spot["name"]
                    for date_str in forecast_dates:
                        if date_str in incomplete_spot_days.get(name, set()):
                            continue
                        # Region-Ergebnis fuer diesen Spot/Tag raussuchen (kann None sein bei Fehler)
                        rid = spot_region_map.get(name)
                        region_result = None
                        if rid and rid in region_results:
                            rr = region_results[rid].get(date_str)
                            # Nur erfolgreiche Region-Ergebnisse injizieren — Fehler/no_data → None → Spot laeuft ohne Kontext
                            if rr and rr.get("safety_status") not in ("error", "no_data"):
                                region_result = rr
                        future = executor.submit(self._build_and_analyze_spot, spot, date_str, region_result)
                        spot_futures[future] = (name, date_str)

                remaining = set(spot_futures.keys())
                while remaining:
                    done, remaining = wait(remaining, timeout=self._HEARTBEAT_INTERVAL, return_when=FIRST_COMPLETED)
                    if not done:
                        yield self._HEARTBEAT_EVENT
                        continue
                    for future in done:
                        name, date_str = spot_futures[future]
                        try:
                            result = future.result()
                        except Exception as e:
                            logger.error(f"Spot-Future {name}/{date_str}: {e}")
                            result = {"spot": name, "date": date_str, "safety_status": "error", "error": str(e)}
                        spot_results.setdefault(name, {})[date_str] = result
                        completed += 1
                        yield {"event": "progress", "data": {
                            "phase": "spots", "type": "spot",
                            "name": name, "date": date_str,
                            "completed": completed, "total": total,
                            "result": result.get("flyability_tier") or result.get("safety_status", "error"),
                        }}

            logger.info(f"[UNIFIED] Phase 2 fertig: {completed} Calls total")

            # ══════════════════════════════════════════════════════════════
            # MERGE + PERSIST: Spot-Ergebnisse
            # ══════════════════════════════════════════════════════════════
            spot_merged = {}
            for spot_name, days_dict in spot_results.items():
                spot_merged[spot_name] = {}
                for date_str, result in days_dict.items():
                    safety_status = result.get("safety_status", "error")
                    safety = {
                        "safety_status": safety_status,
                        "safe_window": result.get("safe_window", "keins"),
                        "no_go_reasons": result.get("no_go_reasons", []),
                        "caution_notes": result.get("caution_notes", []),
                        "primary_no_go": result.get("primary_no_go"),
                        "primary_caution": result.get("primary_caution"),
                        "primary_reducer": result.get("primary_reducer"),
                        "primary_booster": result.get("primary_booster"),
                        "wind_summary": result.get("wind_summary", ""),
                        "wind_shear": result.get("wind_shear", ""),
                        "foehn_risk": result.get("foehn_risk", "none"),
                        "summary": result.get("summary", ""),
                        "spot": result.get("spot", spot_name),
                        "date": date_str,
                        "wind_ok_count": result.get("wind_ok_count", 0),
                        "wind_wrong_count": result.get("wind_wrong_count", 0),
                        "error": result.get("error", ""),
                    }
                    entry = {"safety": safety}
                    # Rating / Conditional-Flag (Briefing)
                    entry["rating"] = float(result.get("rating", 0.0) or 0.0)
                    entry["is_conditional"] = bool(result.get("is_conditional", False))
                    entry["conditional_reason"] = result.get("conditional_reason", "") or ""
                    tier = result.get("flyability_tier") or result.get("fly_status") or ""
                    if safety_status in ("safe", "conditional") and tier:
                        fly = {
                            "flyability_tier": tier, "fly_status": tier, "status": tier,
                            "flight_type": result.get("flight_type", ""),
                            "flight_duration_estimate": result.get("flight_duration_estimate", ""),
                            "thermal_quality": result.get("thermal_quality", ""),
                            "peak_climb_rate": result.get("peak_climb_rate", 0),
                            "xc_potential": result.get("xc_potential", ""),
                            "xc_details": result.get("xc_details", ""),
                            "soaring_options": result.get("soaring_options", ""),
                            "bemerkung_check": result.get("bemerkung_check", ""),
                            "best_window": result.get("best_window", ""),
                            "flyability_limits": result.get("flyability_limits", []),
                            "highlights": result.get("highlights", []),
                            "recommendation": result.get("recommendation", ""),
                            "confidence": result.get("confidence", ""),
                            "rating": entry["rating"],
                            "is_conditional": entry["is_conditional"],
                            "conditional_reason": entry["conditional_reason"],
                            "spot": result.get("spot", spot_name), "date": date_str,
                        }
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
                        entry["status"] = safety_status
                    entry["streckenflug"] = result.get("streckenflug") or {
                        "tier": "kein_xc", "rating": 0,
                        "summary": "", "limiting_factor": "spot_not_flyable" if safety_status == "not_safe" else "none",
                        "region_context_available": False,
                    }
                    entry["best_window"] = result.get("best_window") or safety.get("safe_window", "keins")
                    entry["recommendation"] = result.get("recommendation", "")
                    spot_merged[spot_name][date_str] = entry

            self.spot_analyses = spot_merged
            self.analyses_loaded_at = datetime.now()
            self._analyses_stale = False
            self._save_analyses_cache()
            if self.instantdb:
                threading.Thread(target=self._push_analyses_to_instantdb, daemon=True).start()

            # ══════════════════════════════════════════════════════════════
            # MERGE + PERSIST: Region-Ergebnisse
            # ══════════════════════════════════════════════════════════════
            region_merged = {}
            for rid, days_dict in region_results.items():
                region_merged[rid] = {}
                for date_str, result in days_dict.items():
                    safety_status = result.get("safety_status", "error")
                    safety = {
                        "safety_status": safety_status,
                        "safe_window": result.get("safe_window", "keins"),
                        "no_go_reasons": result.get("no_go_reasons", []),
                        "caution_notes": result.get("caution_notes", []),
                        "primary_no_go": result.get("primary_no_go"),
                        "primary_caution": result.get("primary_caution"),
                        "primary_reducer": result.get("primary_reducer"),
                        "primary_booster": result.get("primary_booster"),
                        "wind_summary": result.get("wind_summary", ""),
                        "wind_shear": result.get("wind_shear", ""),
                        "foehn_risk": result.get("foehn_risk", "none"),
                        "summary": result.get("summary", ""),
                        "region": result.get("region", ""),
                        "region_id": result.get("region_id", rid),
                        "date": date_str,
                        "wind_calm_count": result.get("wind_calm_count", 0),
                        "wind_moderate_count": result.get("wind_moderate_count", 0),
                        "wind_strong_count": result.get("wind_strong_count", 0),
                        "error": result.get("error", ""),
                    }
                    entry = {"safety": safety}
                    # Rating / Conditional-Flag (Briefing)
                    entry["rating"] = float(result.get("rating", 0.0) or 0.0)
                    entry["is_conditional"] = bool(result.get("is_conditional", False))
                    entry["conditional_reason"] = result.get("conditional_reason", "") or ""
                    tier = result.get("flyability_tier") or result.get("fly_status") or ""
                    if safety_status in ("safe", "conditional") and tier:
                        fly = {
                            "flyability_tier": tier, "fly_status": tier, "status": tier,
                            "flight_type": result.get("flight_type", ""),
                            "flight_duration_estimate": result.get("flight_duration_estimate", ""),
                            "thermal_quality": result.get("thermal_quality", ""),
                            "peak_climb_rate": result.get("peak_climb_rate", 0),
                            "xc_potential": result.get("xc_potential", ""),
                            "xc_details": result.get("xc_details", ""),
                            "best_window": result.get("best_window", ""),
                            "flyability_limits": result.get("flyability_limits", []),
                            "highlights": result.get("highlights", []),
                            "recommendation": result.get("recommendation", ""),
                            "confidence": result.get("confidence", ""),
                            "rating": entry["rating"],
                            "is_conditional": entry["is_conditional"],
                            "conditional_reason": entry["conditional_reason"],
                            "region": result.get("region", ""),
                            "region_id": result.get("region_id", rid), "date": date_str,
                        }
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
                        entry["status"] = safety_status
                    entry["best_window"] = result.get("best_window") or safety.get("safe_window", "keins")
                    entry["recommendation"] = result.get("recommendation", "")
                    entry["region_name"] = result.get("region", regions_by_id.get(rid, {}).get("region", rid))
                    region_merged[rid][date_str] = entry

            self.region_analyses = region_merged
            self.region_analyses_loaded_at = datetime.now()
            self._save_region_analyses_cache()
            if self.instantdb:
                threading.Thread(target=self._push_region_analyses_to_instantdb, daemon=True).start()

            # ══════════════════════════════════════════════════════════════
            # DONE
            # ══════════════════════════════════════════════════════════════
            actual_calls = completed - skipped_no_data
            logger.info(f"[UNIFIED] Fertig: {actual_calls} LLM-Calls "
                        f"(kombiniert, Skipped: {skipped_no_data})")

            # Build per_day_counts for day chips in frontend
            per_day_counts = {}
            for date_str in forecast_dates:
                safety_c = {"safe": 0, "conditional": 0, "not_safe": 0, "no_data": 0}
                fly_c = {"gray": 0, "green": 0, "violet": 0}
                err_n = 0
                for sn, days_dict in spot_merged.items():
                    ent = days_dict.get(date_str, {})
                    ss = ent.get("safety", {}).get("safety_status", "error")
                    if ss in safety_c:
                        safety_c[ss] += 1
                    else:
                        err_n += 1
                    ft = ent.get("fly_status") or ""
                    if ft in fly_c:
                        fly_c[ft] += 1
                per_day_counts[date_str] = {"safety": safety_c, "fly": fly_c, "error": err_n}

            yield {"event": "done", "data": {
                "success": True,
                "total_calls": actual_calls,
                "safety_count": actual_calls,
                "flyability_count": 0,
                "skipped_no_data": skipped_no_data,
                "region_stats": {"regions_count": len(region_merged)},
                "spot_stats": {
                    "spots_count": len(spot_merged),
                    "dates": forecast_dates,
                    "per_day_counts": per_day_counts,
                },
            }}

        except GeneratorExit:
            logger.warning("[UNIFIED] Client hat Verbindung geschlossen (GeneratorExit)")
        except Exception as e:
            logger.exception("[UNIFIED] run_all_analyses_stream Fehler")
            yield {"event": "error", "data": {"message": str(e)}}

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
            lines.append(f"║  TAG: {date_str} ({_weekday_de(date_str)})")
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
                        fly.get("flyability_tier") or fly.get("fly_status") or fly.get("status")
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

                    fl_limits = fly.get("flyability_limits", [])
                    if fl_limits and isinstance(fl_limits, list):
                        lines.append(f"    Einschränkungen: {'; '.join(fl_limits)}")

                    fl_highlights = fly.get("highlights", [])
                    if fl_highlights and isinstance(fl_highlights, list):
                        lines.append(f"    Highlights: {'; '.join(fl_highlights)}")

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
            "VORANALYSEN — KURZÜBERSICHT (interne Datenbasis, BINDEND)",
            f"Stand: {self.analyses_loaded_at.isoformat() if self.analyses_loaded_at else 'unbekannt'}",
            "",
            "WICHTIG — HARTE REGELN (KEINE AUSNAHMEN):",
            "  • Die Fliegbarkeits-Einstufung (gray/green/violet) pro Spot+Tag ist das ERGEBNIS",
            "    einer detaillierten Einzelanalyse und DARF NICHT geändert werden.",
            "  • NIEMALS einen Spot von green auf violet hochstufen — auch nicht bei hohem Peak!",
            "    Die Voranalyse hat ALLE Faktoren (Thermik, Wind, Bewölkung, Turbulenztags) berücksichtigt.",
            "  • Wenn ein Spot als 'green' gelistet ist, nenne ihn 'fliegbar (green)' — NICHT 'legendär'.",
            "  • Spots/Tage unter 'SICHERHEIT nicht ok' (not_safe), 'DATEN UNVOLLSTÄNDIG' (no_data)",
            "    und 'Analyse fehlt/Fehler' sind für [RECOMMENDED: …] VERBOTEN.",
            "  • Diese Spots dürfen weder als Top-Pick, Alternative, 'vielleicht später' noch",
            "    als 'geht knapp' empfohlen werden. Die Voranalyse hat Veto-Recht.",
            "  • Du darfst diese Einteilung kommentieren und Nuancen benennen, aber niemals überstimmen.",
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
                fly = entry.get("flyability", {})
                pcr = fly.get("peak_climb_rate") or entry.get("peak_climb_rate")
                if ft == "violet":
                    violet.append((name, bw, pcr))
                elif ft == "green":
                    green_f.append((name, bw, pcr))
                elif ft == "gray":
                    gray_f.append((name, bw, pcr))
                elif ft:
                    green_f.append((name, bw, pcr))

            lines.append(f"─── {date_str} ({_weekday_de(date_str)}) ───")

            def _fmt_group(label: str, items: list):
                if not items:
                    return
                parts = []
                for n, w, pcr in items:
                    if pcr is not None:
                        parts.append(f"{n} (Fenster: {w}, Peak: {pcr} m/s)")
                    else:
                        parts.append(f"{n} (Fenster: {w})")
                lines.append(f"  {label}: " + "; ".join(parts))

            _fmt_group("FLIEGBARKEIT legendär (violet)", violet)
            _fmt_group("FLIEGBARKEIT fliegbar (green)", green_f)
            _fmt_group("FLIEGBARKEIT Abgleiter/mau (gray)", gray_f)

            if not_safe:
                if len(not_safe) <= 12:
                    lines.append(f"  SICHERHEIT nicht ok (NICHT EMPFEHLEN — Phase 2 entfällt): {', '.join(not_safe)}")
                else:
                    lines.append(
                        f"  SICHERHEIT nicht ok (NICHT EMPFEHLEN — Phase 2 entfällt): {', '.join(not_safe[:12])} "
                        f"… (+{len(not_safe) - 12} weitere)"
                    )
            if no_data:
                lines.append(f"  DATEN UNVOLLSTÄNDIG (NICHT EMPFEHLEN — keine Analyse): {', '.join(no_data)}")
            if errors:
                lines.append(f"  Analyse fehlt/Fehler (NICHT EMPFEHLEN): {', '.join(errors)}")

            # Kurz-Tipps: violet zuerst, dann green
            tips = []
            for bucket in (violet, green_f):
                for name, *_ in bucket:
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

                    for key in ["no_go_reasons", "caution_notes", "flyability_limits", "highlights"]:
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
                        "primary_no_go": entry.get("primary_no_go"),
                        "primary_caution": entry.get("primary_caution"),
                        "primary_reducer": entry.get("primary_reducer"),
                        "primary_booster": entry.get("primary_booster"),
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
                            "flyability_limits": entry.get("flyability_limits", []),
                            "highlights": entry.get("highlights", []),
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

