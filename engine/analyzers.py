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
from engine.decision_engine import (
    compute_foehn_decision, apply_foehn_decision,
    decide_wind_ok_zero, decide_aloft_not_safe, decide_aloft_conditional,
    decide_gust_floor, decide_overclaim_relax, decide_is_conditional,
    decide_wind_strong_majority,
    decide_flyability_low_reward, decide_flyability_mech_danger,
    decide_flyability_upgrade,
    decide_flyability_region_gate,
    compute_safety_band, compute_comfort_index,
    compute_legacy_flyability_tier,
    build_start_window, build_topic_tags, build_region_topic_tags,
)
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
    BatchCostTracker, extract_usage_from_response,
    _is_permanent_api_error, _user_friendly_api_error,
    _resolve_max_tokens,
    _FLYABILITY_TIERS, _normalize_flyability_tier,
    _compute_rating_from_subratings,
    _compute_experience_score, _compute_experience_stars, _compute_experience_rating,
    _compute_safety_rating, _compute_safety_score,
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
        """Worker-Wrapper: Split-Flow (Safety → Flyability) fuer einen Spot/Tag.
        Nutzt den 2-Phasen-Ansatz: Safety zuerst, Flyability nur bei safe/conditional.

        region_result: vorab berechnete Region-Analyse fuer diesen Tag (kann None sein →
        Spot wird trotzdem analysiert, Streckenflug-Teil laeuft ohne Region-Kontext).
        """
        name = spot["name"]
        ctx = self._build_single_spot_context(spot, date_str, mode="dashboard", region_analysis_result=region_result)
        if not ctx:
            return {
                "spot": name, "date": date_str,
                "safety_status": "no_data", "phase": "split",
                "summary": "Keine Wetterdaten fuer diesen Tag",
            }

        # ── Deterministischer Pre-Filter: offensichtliche not_safe ohne LLM ──
        prefilter = self._prefilter_not_safe(spot, date_str)
        if prefilter is not None:
            self._finalize_tags(prefilter, f"{name}|{date_str}", is_region=False)
            return prefilter

        # Phase 1: Safety
        safety_result = self._safety_analysis_single_spot_day(spot, date_str, ctx)
        if safety_result.get("safety_status") not in ("safe", "conditional"):
            # not_safe oder error → kein Flyability-Call
            ns_result = self._not_safe_minimal_flyability(safety_result, is_spot=True)
            self._finalize_tags(ns_result, f"{name}|{date_str}", is_region=False)
            return ns_result

        # Phase 2: Flyability (nur bei safe/conditional)
        fly_result = self._flyability_analysis_single_spot_day(spot, date_str, ctx, safety_result, region_result=region_result)
        merged = self._merge_safety_flyability(safety_result, fly_result)
        # Tag-System v4: deterministische Tag- und Window-Berechnung NACH allen
        # Decisions + Flyability-Merge (siehe docs/TAGS.md).
        self._finalize_tags(merged, f"{name}|{date_str}", is_region=False)
        return merged

    def _prefilter_not_safe(self, spot, date_str: str):
        """Prueft anhand der deterministischen Cache-Daten ob ein Spot/Tag
        offensichtlich not_safe ist.  Gibt ein fertiges Result-Dict zurueck
        oder None wenn der LLM-Call noetig ist.

        Strategie: NUR bombensichere NO-GOs filtern. Grauzonen (z.B. kurze
        Fenster mit leichten Warnungen) gehen ans LLM.

        Bombensichere Kriterien:
        1. Kein qualifizierendes Tagesfenster (active_window_start is None)
           → entweder Windrichtung ganztaegig falsch ODER alle WIND-OK-Stunden
             mit harten Warnungen ODER kein zusammenhaengender Block >= min.
        2. Ganztaegig Regen               → kein nutzbares Fenster
        3. Ganztaegig Gewitter            → objektiv nicht fliegbar
        """
        name = spot["name"]
        cache_key = f"{name}|{date_str}"
        gust_info = self._ctx_gust_cache.get(cache_key)
        if not gust_info:
            return None  # Kein Cache → LLM entscheiden lassen

        wind_ok = gust_info.get("wind_ok_count", -1)
        wind_wrong = gust_info.get("wind_wrong_count", 0)
        clean_count = gust_info.get("clean_hours_count", 0)
        active_start = gust_info.get("active_window_start")
        rain_cnt = gust_info.get("rain_hours", 0)
        ts_h = gust_info.get("thunderstorm_hours", 0)
        total_hours = wind_ok + wind_wrong if wind_ok >= 0 else 0

        no_go = []
        summary_parts = []
        # noAnalysisReason: kanonischer Grund-Tag fuer das schlanke UI-Panel
        # (RATING_CONCEPT v1.3 §8.6). Bei eindeutigen No-Gos zeigt das Frontend
        # nur Hero + Reason — kein Meteogramm, kein Detail-Akkordeon.
        na_reason = None

        # Regel 1: Kein qualifizierendes Tagesfenster — drei Unterfaelle fuer
        # Begruendungs-Differenzierung. active_window_start is None bedeutet:
        # kein zusammenhaengender Block sauberer Stunden >= CLEAN_WINDOW_MIN_HOURS.
        if active_start is None and total_hours > 0:
            if wind_ok == 0:
                no_go.append("Windrichtung: Ganztaegig ausserhalb des erlaubten Sektors")
                summary_parts.append(
                    f"Die Windrichtung liegt den ganzen Tag ausserhalb des erlaubten Sektors "
                    f"({spot.get('windrichtung', '?')}). Kein fliegbares Fenster."
                )
                na_reason = "wind_direction_mismatch"
            elif clean_count == 0:
                no_go.append(
                    "Start-Fenster: Alle Stunden mit passender Windrichtung haben harte "
                    "Warnungen (Sturm/Boeen/Regen/Gewitter)"
                )
                summary_parts.append(
                    f"Alle {wind_ok}h mit passender Windrichtung haben harte Warnungen — "
                    f"kein nutzbares Start-Fenster."
                )
                # Bewusst KEIN noAnalysis: Pilot will sehen warum es nicht geht.
            else:
                no_go.append(
                    f"Start-Fenster: Nur {clean_count}h sauber, kein zusammenhaengender Block "
                    f">= {config.CLEAN_WINDOW_MIN_HOURS}h"
                )
                summary_parts.append(
                    f"Saubere Stunden ({clean_count}h) bilden kein zusammenhaengendes "
                    f"Start-Fenster (Minimum {config.CLEAN_WINDOW_MIN_HOURS}h)."
                )

        # Regel 2: Ganztaegig Regen
        elif total_hours > 0 and rain_cnt >= total_hours - 2 and rain_cnt >= 4:
            no_go.append(f"Niederschlag: Regen in {rain_cnt} von {total_hours} Stunden")
            summary_parts.append(
                f"Nahezu ganztaegiger Niederschlag ({rain_cnt} von {total_hours} Stunden). "
                f"Kein nutzbares Flugfenster."
            )
            na_reason = "all_day_rain"

        # Regel 3: Ganztaegig Gewitter
        elif total_hours > 0 and ts_h >= total_hours - 2 and ts_h >= 4:
            no_go.append(f"Gewitter: prognostiziert in {ts_h} von {total_hours} Stunden")
            summary_parts.append(
                f"Praktisch ganztaegig Gewitter ({ts_h} von {total_hours} Stunden). "
                f"Kein fliegbares Fenster."
            )
            na_reason = "all_day_thunderstorm"

        # Regel 4 entfernt (Apr 2026): "Ganztaegig Sturmwarnung" wird jetzt vom
        # WIND-TREND-Override (analyzers.py ~L1296, _build_single_spot_context)
        # abgedeckt. DURCHGEHEND_DANGER und EINGEKESSELT mit Fenster <3h triggern
        # dort hartes not_safe — symmetrisch fuer Bodenwind und Hoehenwind.

        if not no_go:
            return None  # Kein klarer not_safe-Fall → LLM entscheiden lassen

        logger.info(
            f"Pre-Filter not_safe fuer {name}/{date_str}: "
            f"wind_ok={wind_ok}, rain={rain_cnt}/{total_hours}, ts={ts_h}"
        )

        result = {
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
        # noAnalysis-Flag fuer schlankes UI-Panel (RATING_CONCEPT v1.3 §8.6).
        # Nur bei eindeutigen No-Gos — Frontend versteckt dann das Meteogramm
        # und zeigt einen kompakten "Keine Analyse"-Block.
        if na_reason:
            result["noAnalysis"] = True
            result["noAnalysisReason"] = na_reason
        return result

    def _build_and_analyze_region(self, region, date_str: str) -> dict:
        """Worker-Wrapper: Split-Flow (Safety → Flyability) fuer eine Region/Tag.
        Nutzt den 2-Phasen-Ansatz: Safety zuerst, Flyability nur bei safe/conditional.
        """
        ctx = self._build_single_region_context(region, date_str)
        if not ctx:
            return {
                "region": region["region"], "region_id": region["id"],
                "date": date_str, "safety_status": "no_data", "phase": "split",
                "summary": "Keine Wetterdaten fuer diesen Tag",
            }

        rname = region["region"]
        # Phase 1: Safety
        safety_result = self._safety_analysis_single_region_day(region, date_str, ctx)
        if safety_result.get("safety_status") not in ("safe", "conditional"):
            ns_result = self._not_safe_minimal_flyability(safety_result, is_spot=False)
            self._finalize_tags(ns_result, f"{rname}|{date_str}", is_region=True)
            return ns_result

        # Phase 2: Flyability (nur bei safe/conditional)
        fly_result = self._flyability_analysis_single_region_day(region, date_str, ctx, safety_result)
        merged = self._merge_safety_flyability(safety_result, fly_result)
        self._finalize_tags(merged, f"{rname}|{date_str}", is_region=True)
        return merged

    # ═══════════════════════════════════════════════════════════════════════════
    # SPLIT-FLOW: Separate Safety- und Flyability-Calls (Hebel 1 Kostenreduktion)
    # ═══════════════════════════════════════════════════════════════════════════

    def _safety_analysis_single_spot_day(self, spot, date_str: str, context: str) -> dict:
        """Safety-only LLM-Call fuer einen Spot/Tag. Kleinerer Prompt (~7K tokens)."""
        name = spot["name"]
        if getattr(self, '_api_abort', None) and self._api_abort.is_set():
            reason = getattr(self, '_api_abort_reason', 'Analyse abgebrochen')
            return {"spot": name, "date": date_str, "safety_status": "error",
                    "phase": "safety", "error": reason}
        try:
            if not context:
                return {"spot": name, "date": date_str, "safety_status": "error",
                        "phase": "safety", "error": "Keine Daten fuer diesen Tag"}

            messages = [
                {"role": "system", "content": prompts.SPOT_SAFETY_PROMPT},
                {"role": "user", "content": (
                    f"AKTUELLE LOKALZEIT: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ({_weekday_de(datetime.now())})\n\n"
                    f"{context}"
                )},
            ]

            last_err = None
            for attempt in range(2):
                try:
                    response = self.analysis_client.chat.completions.create(
                        model=self.analysis_model,
                        messages=messages,
                        temperature=0.2,
                        max_tokens=_resolve_max_tokens(self.analysis_model, 1500),
                        response_format={"type": "json_object"},
                    )
                    self._record_call_usage(response, "spot_safety")
                    raw = response.choices[0].message.content
                    if not raw:
                        finish = getattr(response.choices[0], "finish_reason", "?")
                        raise RuntimeError(
                            f"LLM lieferte leeren Content (finish_reason={finish}) — "
                            f"vermutlich max_tokens zu klein fuer Reasoning-Modell {self.analysis_model}"
                        )
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
                        logger.warning(f"Safety-Check fuer {name}/{date_str} Versuch 1 fehlgeschlagen: {api_err} — Retry in 3s")
                        time.sleep(3)
            if last_err:
                raise last_err
            return self._post_process_safety_spot(result, spot, date_str)

        except Exception as e:
            logger.error(f"Safety-Analyse fuer {name}/{date_str} fehlgeschlagen: {e}")
            return {"spot": name, "date": date_str, "safety_status": "error", "phase": "safety", "error": str(e)}

    def _flyability_analysis_single_spot_day(self, spot, date_str: str, context: str,
                                              safety_result: dict, region_result: dict = None) -> dict:
        """Flyability-only LLM-Call fuer einen Spot/Tag. Nur bei safe/conditional aufrufen.
        Injiziert das Safety-Ergebnis als immutable Block in den User-Content.
        """
        name = spot["name"]
        if getattr(self, '_api_abort', None) and self._api_abort.is_set():
            reason = getattr(self, '_api_abort_reason', 'Analyse abgebrochen')
            return {"spot": name, "date": date_str, "safety_status": safety_result.get("safety_status", "error"),
                    "phase": "flyability", "error": reason}
        try:
            if not context:
                return {"spot": name, "date": date_str, "safety_status": safety_result.get("safety_status", "error"),
                        "phase": "flyability", "error": "Keine Daten fuer diesen Tag"}

            # Safety-Result als immutable Block injizieren
            safety_block = self._format_safety_injection(safety_result)

            messages = [
                {"role": "system", "content": prompts.SPOT_FLYABILITY_PROMPT},
                {"role": "user", "content": (
                    f"AKTUELLE LOKALZEIT: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ({_weekday_de(datetime.now())})\n\n"
                    f"{context}\n\n{safety_block}"
                )},
            ]

            last_err = None
            for attempt in range(2):
                try:
                    response = self.analysis_client.chat.completions.create(
                        model=self.analysis_model,
                        messages=messages,
                        temperature=0.2,
                        max_tokens=_resolve_max_tokens(self.analysis_model, 2500),
                        response_format={"type": "json_object"},
                    )
                    self._record_call_usage(response, "spot_fly")
                    raw = response.choices[0].message.content
                    if not raw:
                        finish = getattr(response.choices[0], "finish_reason", "?")
                        raise RuntimeError(
                            f"LLM lieferte leeren Content (finish_reason={finish}) — "
                            f"vermutlich max_tokens zu klein fuer Reasoning-Modell {self.analysis_model}"
                        )
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
                        logger.warning(f"Flyability-Check fuer {name}/{date_str} Versuch 1 fehlgeschlagen: {api_err} — Retry in 3s")
                        time.sleep(3)
            if last_err:
                raise last_err

            # Safety-Felder ins Ergebnis uebernehmen (fuer Post-Processing).
            # Inkl. Sub-Ratings + safety_rating/score/band (Vorab-Fix #4) + foehn_risk
            # damit _compute_safety_rating und _decisions_applied im Flyability-
            # Post-Process die korrekten Werte sehen (Bug: ohne Transfer fallen
            # Subs auf Default 5 zurueck, MIN ergibt 5 statt 9).
            result["safety_status"] = safety_result.get("safety_status", "")
            result["safe_window"] = safety_result.get("safe_window", "")
            for f in ("wind_safety_rating", "gust_safety_rating",
                      "aloft_safety_rating", "foehn_safety_rating",
                      "weather_safety_rating", "safety_rating", "safety_score",
                      "safety_band", "foehn_risk", "_decisions_applied",
                      "no_go_reasons", "caution_notes"):
                v = safety_result.get(f)
                if v is not None:
                    result[f] = v
            result["spot"] = name
            result["date"] = date_str
            result["phase"] = "flyability"

            return self._post_process_flyability_spot(result, spot, date_str, region_result=region_result)

        except Exception as e:
            logger.error(f"Flyability-Analyse fuer {name}/{date_str} fehlgeschlagen: {e}")
            return {"spot": name, "date": date_str, "safety_status": safety_result.get("safety_status", "error"),
                    "phase": "flyability", "error": str(e)}

    def _safety_analysis_single_region_day(self, region, date_str: str, context: str) -> dict:
        """Safety-only LLM-Call fuer eine Region/Tag."""
        rname = region["region"]
        if getattr(self, '_api_abort', None) and self._api_abort.is_set():
            reason = getattr(self, '_api_abort_reason', 'Analyse abgebrochen')
            return {"region": rname, "region_id": region["id"], "date": date_str,
                    "safety_status": "error", "phase": "safety", "error": reason}
        try:
            if not context:
                return {"region": rname, "region_id": region["id"], "date": date_str,
                        "safety_status": "error", "phase": "safety", "error": "Keine Daten fuer diesen Tag"}

            messages = [
                {"role": "system", "content": prompts.REGION_SAFETY_PROMPT},
                {"role": "user", "content": (
                    f"AKTUELLE LOKALZEIT: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ({_weekday_de(datetime.now())})\n\n"
                    f"{context}"
                )},
            ]

            last_err = None
            for attempt in range(2):
                try:
                    response = self.analysis_client.chat.completions.create(
                        model=self.analysis_model,
                        messages=messages,
                        temperature=0.2,
                        max_tokens=_resolve_max_tokens(self.analysis_model, 1500),
                        response_format={"type": "json_object"},
                    )
                    self._record_call_usage(response, "region_safety")
                    raw = response.choices[0].message.content
                    if not raw:
                        finish = getattr(response.choices[0], "finish_reason", "?")
                        raise RuntimeError(
                            f"LLM lieferte leeren Content (finish_reason={finish}) — "
                            f"vermutlich max_tokens zu klein fuer Reasoning-Modell {self.analysis_model}"
                        )
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
                        logger.warning(f"Region-Safety fuer {rname}/{date_str} Versuch 1 fehlgeschlagen: {api_err} — Retry in 3s")
                        time.sleep(3)
            if last_err:
                raise last_err
            return self._post_process_safety_region(result, region, date_str)

        except Exception as e:
            logger.error(f"Region-Safety-Analyse fuer {rname}/{date_str} fehlgeschlagen: {e}")
            return {"region": rname, "region_id": region["id"], "date": date_str,
                    "safety_status": "error", "phase": "safety", "error": str(e)}

    def _flyability_analysis_single_region_day(self, region, date_str: str, context: str,
                                                safety_result: dict) -> dict:
        """Flyability-only LLM-Call fuer eine Region/Tag. Nur bei safe/conditional aufrufen."""
        rname = region["region"]
        if getattr(self, '_api_abort', None) and self._api_abort.is_set():
            reason = getattr(self, '_api_abort_reason', 'Analyse abgebrochen')
            return {"region": rname, "region_id": region["id"], "date": date_str,
                    "safety_status": safety_result.get("safety_status", "error"),
                    "phase": "flyability", "error": reason}
        try:
            if not context:
                return {"region": rname, "region_id": region["id"], "date": date_str,
                        "safety_status": safety_result.get("safety_status", "error"),
                        "phase": "flyability", "error": "Keine Daten fuer diesen Tag"}

            safety_block = self._format_safety_injection(safety_result)

            messages = [
                {"role": "system", "content": prompts.REGION_FLYABILITY_PROMPT},
                {"role": "user", "content": (
                    f"AKTUELLE LOKALZEIT: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ({_weekday_de(datetime.now())})\n\n"
                    f"{context}\n\n{safety_block}"
                )},
            ]

            last_err = None
            for attempt in range(2):
                try:
                    response = self.analysis_client.chat.completions.create(
                        model=self.analysis_model,
                        messages=messages,
                        temperature=0.2,
                        max_tokens=_resolve_max_tokens(self.analysis_model, 2500),
                        response_format={"type": "json_object"},
                    )
                    self._record_call_usage(response, "region_fly")
                    raw = response.choices[0].message.content
                    if not raw:
                        finish = getattr(response.choices[0], "finish_reason", "?")
                        raise RuntimeError(
                            f"LLM lieferte leeren Content (finish_reason={finish}) — "
                            f"vermutlich max_tokens zu klein fuer Reasoning-Modell {self.analysis_model}"
                        )
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
                        logger.warning(f"Region-Flyability fuer {rname}/{date_str} Versuch 1 fehlgeschlagen: {api_err} — Retry in 3s")
                        time.sleep(3)
            if last_err:
                raise last_err

            # Safety-Felder ins Ergebnis uebernehmen — inkl. Sub-Ratings + safety_*
            # damit _compute_safety_rating und compute_safety_band im Flyability-
            # Post-Process die korrekten Werte sehen (Vorab-Fix #4 Bug-Fix).
            result["safety_status"] = safety_result.get("safety_status", "")
            result["safe_window"] = safety_result.get("safe_window", "")
            result["wind_calm_count"] = safety_result.get("wind_calm_count", 0)
            result["wind_moderate_count"] = safety_result.get("wind_moderate_count", 0)
            result["wind_strong_count"] = safety_result.get("wind_strong_count", 0)
            for f in ("wind_safety_rating", "gust_safety_rating",
                      "aloft_safety_rating", "foehn_safety_rating",
                      "weather_safety_rating", "safety_rating", "safety_score",
                      "safety_band", "foehn_risk", "_decisions_applied",
                      "no_go_reasons", "caution_notes"):
                v = safety_result.get(f)
                if v is not None:
                    result[f] = v
            result["region"] = rname
            result["region_id"] = region["id"]
            result["date"] = date_str
            result["phase"] = "flyability"

            return self._post_process_flyability_region(result, region, date_str)

        except Exception as e:
            logger.error(f"Region-Flyability-Analyse fuer {rname}/{date_str} fehlgeschlagen: {e}")
            return {"region": rname, "region_id": region["id"], "date": date_str,
                    "safety_status": safety_result.get("safety_status", "error"),
                    "phase": "flyability", "error": str(e)}

    @staticmethod
    def _format_safety_injection(safety_result: dict) -> str:
        """Formatiert ein Safety-Ergebnis als immutable Block fuer den Flyability-Prompt."""
        lines = [
            "### SICHERHEITSBEWERTUNG (IMMUTABLE)",
            f"safety_status: {safety_result.get('safety_status', '')}",
            f"safe_window: {safety_result.get('safe_window', '')}",
            f"no_go_reasons: {json.dumps(safety_result.get('no_go_reasons', []), ensure_ascii=False)}",
            f"caution_notes: {json.dumps(safety_result.get('caution_notes', []), ensure_ascii=False)}",
            f"foehn_risk: {safety_result.get('foehn_risk', 'none')}",
            f"wind_summary: {safety_result.get('wind_summary', '')}",
        ]
        # Region-spezifische Wind-Counts
        if "wind_calm_count" in safety_result:
            lines.append(f"wind_calm_count: {safety_result.get('wind_calm_count', 0)}")
            lines.append(f"wind_moderate_count: {safety_result.get('wind_moderate_count', 0)}")
            lines.append(f"wind_strong_count: {safety_result.get('wind_strong_count', 0)}")
        return "\n".join(lines)

    @staticmethod
    def _merge_safety_flyability(safety_result: dict, flyability_result: dict) -> dict:
        """Merged Safety + Flyability Ergebnisse ins Combined-Format fuer Downstream."""
        merged = {**safety_result}
        merged.update(flyability_result)
        # Phase-Marker: zeigt dass aus Split-Flow
        merged["phase"] = "split"
        return merged

    @staticmethod
    def _attach_rating_fields(entry: dict, result: dict) -> None:
        """Kopiert die RATING_CONCEPT v1.3/v1.4-Felder aus dem Engine-`result`
        ins persistierte Cache-`entry`. Wird in allen Stream-Cache-Buildern aufgerufen.

        Ohne diese Kopie landen die Werte zwar im LLM-Result, aber das
        Cache-Top-Level enthaelt nur Legacy-Felder — Frontend faellt auf
        legacy-Mapping zurueck und der User sieht das alte Rating.

        Nur Felder mit Wert (nicht None) werden uebernommen.
        """
        new_fields = (
            # Phase 1 — 2-Achsen
            "safety_band", "safety_score", "safety_rating",
            "experience_score", "experience_stars", "experience_rating",
            "comfort_index",
            # 5 Safety-Sub-Ratings (Vorab-Fix #4)
            "wind_safety_rating", "gust_safety_rating",
            "aloft_safety_rating", "foehn_safety_rating", "weather_safety_rating",
            # 4-5 Flyability-Sub-Ratings (Vorab-Fix #3 + v1.4 altitude)
            "thermal_rating", "window_rating", "wind_rating", "xc_rating",
            "altitude_rating",
            # noAnalysis-Pfad (§8.6)
            "noAnalysis", "noAnalysisReason",
            # Decision-Engine Tracking
            "_decisions_applied",
            # Tag-System v4 (siehe docs/TAGS.md)
            "tags", "start_window",
        )
        for k in new_fields:
            v = result.get(k)
            if v is not None:
                entry[k] = v

    def _finalize_tags(self, result: dict, label_key: str, is_region: bool = False) -> None:
        """Berechnet result["tags"] + result["start_window"] aus den Caches.

        MUSS aufgerufen werden NACH allen Decision-Engine-Schritten (Foehn,
        IsConditional, Flyability-Merge), damit foehn_risk, peak_climb_rate
        und xc_potential auf result final sind.

        Doku: docs/TAGS.md (Tag-System v4).

        Args:
          label_key: f"{name}|{date_str}" — Cache-Key fuer gust/tq.
          is_region: True fuer Regionen → reduzierte Topic-Liste, kein Window.
        """
        gust_info = self._ctx_gust_cache.get(label_key, {}) or {}
        tq = self._ctx_tq_cache.get(label_key, {}) or {}

        if is_region:
            result["tags"] = build_region_topic_tags(result, gust_info)
            # Regionen haben kein Spot-Startfenster (aggregiert ueber mehrere Spots)
            result["start_window"] = []
        else:
            result["tags"] = build_topic_tags(result, gust_info, tq)
            result["start_window"] = build_start_window(gust_info)

    @staticmethod
    def _not_safe_minimal_flyability(safety_result: dict, is_spot: bool = True) -> dict:
        """Erzeugt Minimal-Flyability-Werte fuer not_safe-Ergebnisse (kein LLM-Call noetig)."""
        result = {**safety_result}
        result["fly_status"] = ""
        result["flyability_tier"] = ""
        result["flight_type"] = ""
        result["flight_duration_estimate"] = ""
        result["thermal_quality"] = ""
        result["peak_climb_rate"] = 0
        result["xc_potential"] = ""
        result["xc_details"] = ""
        result["best_window"] = ""
        result["flyability_limits"] = []
        result["highlights"] = []
        result["recommendation"] = ""
        result["confidence"] = ""
        result["primary_reducer"] = None
        result["primary_booster"] = None
        result["thermal_rating"] = 1
        result["wind_rating"] = 1
        result["window_rating"] = 1
        result["xc_rating"] = 1
        result["is_conditional"] = False
        result["conditional_reason"] = ""
        result["rating"] = 0
        if is_spot:
            result["soaring_options"] = ""
            result["bemerkung_check"] = ""
            result["streckenflug"] = {
                "tier": "kein_xc", "rating": 0,
                "summary": "", "limiting_factor": "spot_not_flyable",
                "region_context_available": False,
            }
        return result

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

    def build_briefing_data(self, spot_analyses: dict | None = None,
                            region_analyses: dict | None = None) -> dict:
        """Aggregiert spot_analyses + region_analyses in eine Briefing-Struktur.

        Args:
            spot_analyses: Optionaler Override fuer self.spot_analyses
                (z. B. Test-Run-Output). Wenn None: nutzt self.spot_analyses.
            region_analyses: Analog fuer self.region_analyses.

        RATING_CONCEPT v1.3: liefert ALLE analysierten Spots/Regionen mit
        safety_band/experience_stars als Top-Level-Felder. Das Frontend
        filtert client-seitig ueber Sicherheits-Band + Stars-Slider.

        Legacy-Counts (spots_flyable/bronze/nogo/conditional) bleiben
        zusaetzlich erhalten fuer Backwards-Compat.
        """
        spot_src = spot_analyses if spot_analyses is not None else self.spot_analyses
        region_src = region_analyses if region_analyses is not None else self.region_analyses
        # Lokale Helfer fuer v1.3-Felder mit Legacy-Fallback (Cache vor v1.3
        # hat safety_band/experience_stars/experience_score nicht gesetzt).
        def _band_from_entry(e: dict) -> str:
            b = e.get("safety_band")
            if b in ("green", "amber", "red", "no_data"):
                return b
            ss = (e.get("safety") or {}).get("safety_status") or e.get("safety_status") or ""
            if ss == "not_safe":    return "red"
            if ss == "conditional": return "amber"
            if ss == "safe":        return "green"
            if ss in ("no_data", "error"): return "no_data"
            return "no_data"

        def _stars_from_entry(e: dict) -> int:
            v = e.get("experience_stars")
            if isinstance(v, int) and 0 <= v <= 5:
                return v
            try:
                r = float(e.get("rating") or 0.0)
            except (TypeError, ValueError):
                r = 0.0
            if r >= 9.0:  return 5
            if r >= 7.6:  return 4
            if r >= 6.1:  return 3
            if r >= 4.1:  return 2
            if r >= 2.1:  return 1
            return 0

        def _rating_from_entry(e: dict) -> int:
            v = e.get("experience_rating")
            if isinstance(v, int) and 0 <= v <= 10:
                return v
            score = _score_from_entry(e)
            return _compute_experience_rating(score)

        def _score_from_entry(e: dict) -> int:
            v = e.get("experience_score")
            if isinstance(v, (int, float)):
                return max(0, min(100, int(v)))
            try:
                r = float(e.get("rating") or 0.0)
            except (TypeError, ValueError):
                r = 0.0
            return max(0, min(100, int(round(r * 10))))
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
            # Legacy-Counts: bleiben fuer Backwards-Compat erhalten.
            nogo_count = 0
            bronze_count = 0
            conditional_count = 0
            # v1.3-Counts nach safety_band:
            band_counts = {"green": 0, "amber": 0, "red": 0, "no_data": 0}
            top_count = 0  # experience_stars >= 4 AND band != red

            # Pro-Region-Counts fuer dynamisches Filtern im Frontend.
            # Shape: { region_id: {"flyable","bronze","nogo","conditional",
            #                       "green","amber","red","no_data","top"} }
            counts_by_region = {}
            def _bump_region(rid, key):
                c = counts_by_region.setdefault(
                    rid or "unknown",
                    {"flyable": 0, "bronze": 0, "nogo": 0, "conditional": 0,
                     "green": 0, "amber": 0, "red": 0, "no_data": 0, "top": 0},
                )
                c[key] = c.get(key, 0) + 1

            for spot_name, days in spot_src.items():
                if not spot_name or not str(spot_name).strip():
                    continue  # defensive: skip entries without a name
                entry = days.get(date_str)
                if not entry:
                    continue
                safety = entry.get("safety", {}) or {}
                ss = safety.get("safety_status", "") or entry.get("safety_status", "")
                fly_status = entry.get("fly_status", "") or entry.get("flyability", {}).get("fly_status", "")
                try:
                    rating = float(entry.get("rating", 0.0) or 0.0)
                except (TypeError, ValueError):
                    rating = 0.0
                is_cond = bool(entry.get("is_conditional", False))
                rid_spot = spot_region.get(spot_name, "unknown")

                # v1.3-Felder: aus Cache priorisiert, sonst Legacy-Fallback.
                band = _band_from_entry(entry)
                stars = _stars_from_entry(entry)
                exp_score = _score_from_entry(entry)
                exp_rating = _rating_from_entry(entry)

                # Legacy-Bookkeeping fuer Backwards-Compat
                if ss == "not_safe":
                    nogo_count += 1
                    _bump_region(rid_spot, "nogo")
                elif fly_status == "gray":
                    bronze_count += 1
                    _bump_region(rid_spot, "bronze")
                else:
                    if ss == "conditional":
                        conditional_count += 1
                        _bump_region(rid_spot, "conditional")
                    if fly_status in ("green", "violet"):
                        _bump_region(rid_spot, "flyable")

                # v1.3-Bookkeeping
                band_counts[band] = band_counts.get(band, 0) + 1
                _bump_region(rid_spot, band)
                if stars >= 4 and band != "red":
                    top_count += 1
                    _bump_region(rid_spot, "top")

                fly = entry.get("flyability", {}) or {}
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
                    # RATING_CONCEPT v1.3/v1.4 — 2-Achsen Top-Level-Felder.
                    "safety_band": band,
                    "experience_stars": stars,
                    "experience_score": exp_score,
                    "experience_rating": exp_rating,
                    "safety_score": entry.get("safety_score"),
                    "comfort_index": entry.get("comfort_index"),
                    # Volle Voranalyse fuer Ausklapp-Ansicht im Briefing
                    "analysis_full": entry,
                })
            # Sortierung primaer safety_band (gruen → amber → no_data → rot),
            # sekundaer experience_score absteigend. Frontend wendet Filter an.
            _BAND_RANK = {"green": 0, "amber": 1, "no_data": 2, "red": 3}
            spot_entries.sort(key=lambda e: (
                _BAND_RANK.get(e.get("safety_band", "no_data"), 4),
                -int(e.get("experience_score") or 0),
                -float(e.get("rating") or 0.0),
            ))

            # Regionen fuer diesen Tag — RATING_CONCEPT v1.3:
            # alle analysierten Regionen mit safety_band/experience_stars,
            # Frontend filtert client-seitig.
            region_entries = []
            for rid, days in region_src.items():
                entry = days.get(date_str)
                if not entry:
                    continue
                safety = entry.get("safety", {}) or {}
                ss = safety.get("safety_status", "") or entry.get("safety_status", "")
                fly_status = entry.get("fly_status", "") or entry.get("flyability", {}).get("fly_status", "")
                try:
                    rating = float(entry.get("rating", 0.0) or 0.0)
                except (TypeError, ValueError):
                    rating = 0.0

                band_r = _band_from_entry(entry)
                stars_r = _stars_from_entry(entry)
                score_r = _score_from_entry(entry)
                rating_r = _rating_from_entry(entry)

                region_name = entry.get("region_name", region_by_id.get(rid, {}).get("region", rid))
                region_entries.append({
                    "region_id": rid,
                    "region_name": region_name,
                    "rating": rating,
                    "fly_status": fly_status,
                    "safety_status": ss,
                    "is_conditional": bool(entry.get("is_conditional", False)),
                    # v1.3/v1.4 Top-Level-Felder
                    "safety_band": band_r,
                    "experience_stars": stars_r,
                    "experience_score": score_r,
                    "experience_rating": rating_r,
                    "safety_score": entry.get("safety_score"),
                    "comfort_index": entry.get("comfort_index"),
                })
            region_entries.sort(key=lambda e: (
                _BAND_RANK.get(e.get("safety_band", "no_data"), 4),
                -int(e.get("experience_score") or 0),
                -float(e.get("rating") or 0.0),
            ))

            regions_meteo = []
            for rid, days in region_src.items():
                entry = days.get(date_str)
                if not entry:
                    continue
                safety = entry.get("safety", {})
                cn = safety.get("caution_notes", entry.get("caution_notes", []))
                if isinstance(cn, str):
                    try:
                        cn = json.loads(cn)
                    except Exception:
                        cn = [cn] if cn else []
                if not isinstance(cn, list):
                    cn = []
                regions_meteo.append({
                    "region_id": rid,
                    "region_name": entry.get("region_name",
                                            region_by_id.get(rid, {}).get("region", rid)),
                    "fly_status": entry.get("fly_status", "")
                                  or entry.get("flyability", {}).get("fly_status", ""),
                    "safety_status": safety.get("safety_status", entry.get("safety_status", "")),
                    "foehn_risk": safety.get("foehn_risk", entry.get("foehn_risk", "none")),
                    "wind_summary": safety.get("wind_summary", entry.get("wind_summary", "")),
                    "caution_notes": cn,
                })

            days_data.append({
                "date": date_str,
                "weekday": _weekday_de(datetime.fromisoformat(date_str)),
                "top_spots": spot_entries,
                "top_regions": region_entries[:10],
                "regions_meteo": regions_meteo,
                "counts": {
                    "spots_total": sum(1 for days in spot_src.values() if date_str in days),
                    # Legacy (Backwards-Compat — nicht mehr im Briefing-UI verwendet)
                    "spots_flyable": sum(1 for s in spot_entries if s.get("fly_status") in ("green", "violet")),
                    "spots_bronze": bronze_count,
                    "spots_nogo": nogo_count,
                    "spots_conditional": conditional_count,
                    # RATING_CONCEPT v1.3 — Safety-Band-Verteilung + Top-Sterne
                    "spots_green":   band_counts.get("green", 0),
                    "spots_amber":   band_counts.get("amber", 0),
                    "spots_red":     band_counts.get("red", 0),
                    "spots_no_data": band_counts.get("no_data", 0),
                    "spots_top":     top_count,
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
                max_tokens=_resolve_max_tokens(self.analysis_model, 1500),
                response_format={"type": "json_object"},
            )
            _log_prompt_cache_usage(response, label="weekly_briefing")
            raw = response.choices[0].message.content
            if not raw:
                finish = getattr(response.choices[0], "finish_reason", "?")
                raise RuntimeError(
                    f"LLM lieferte leeren Content (finish_reason={finish}) — "
                    f"vermutlich max_tokens zu klein fuer Reasoning-Modell {self.analysis_model}"
                )
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
                self._attach_rating_fields(entry, result)

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
                    err_msg = result.get("error") or safety.get("error", "")
                    entry["fly_error"] = err_msg
                    entry["error"] = err_msg
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
        self._ctx_foehn_cache.clear()
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
                self._attach_rating_fields(entry, result)

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
                    err_msg = result.get("error") or safety.get("error", "")
                    entry["fly_error"] = err_msg
                    entry["error"] = err_msg
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
                f"'{self.analysis_provider}'. Bitte OPENAI_ANALYSIS_MODE=parallel setzen."
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

    def _poll_batch(self, batch_id: str, poll_interval: int = None) -> tuple[dict, dict]:
        """Pollt Batch bis abgeschlossen.

        Returns: (results, usage_summary)
          results: {custom_id: parsed_json}
          usage_summary: {"calls": n, "in_tok": n, "out_tok": n, "cached_tok": n}
        """
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
        usage_sum = {"calls": 0, "in_tok": 0, "out_tok": 0, "cached_tok": 0}
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
            # Token-Usage pro Eintrag aufsummieren (auch bei JSON-Parse-Fehlern relevant)
            usage = resp_body.get("usage") or {}
            usage_sum["calls"] += 1
            usage_sum["in_tok"] += int(usage.get("prompt_tokens", 0) or 0)
            usage_sum["out_tok"] += int(usage.get("completion_tokens", 0) or 0)
            details = usage.get("prompt_tokens_details") or {}
            usage_sum["cached_tok"] += int(details.get("cached_tokens", 0) or 0)
        logger.info(
            f"Batch {batch_id}: {len(results)} Ergebnisse geparst, "
            f"in_tok={usage_sum['in_tok']:,} out_tok={usage_sum['out_tok']:,} "
            f"cached={usage_sum['cached_tok']:,}"
        )
        return results, usage_sum

    def _record_call_usage(self, response, phase_label: str) -> None:
        """Loggt Cache-Hit-Rate UND aggregiert Tokens auf self._cost_tracker
        (falls gesetzt durch run_all_analyses_stream).
        """
        _log_prompt_cache_usage(response, label=phase_label)
        tracker = getattr(self, "_cost_tracker", None)
        if tracker is None:
            return
        u = extract_usage_from_response(response)
        tracker.record(phase_label, u["in_tok"], u["out_tok"], u["cached_tok"], calls=1)

    def _apply_foehn_decision(self, result: dict, cache_key: str, label: str) -> None:
        """Wendet die deterministische Foehn-Decision (Stage-Inversion) auf das LLM-Result.

        Ersetzt das frueher hier eingebaute `_apply_foehn_override`-Pattern: anstatt das
        LLM-Result zu PRUEFEN und ggf. zu korrigieren, wird `foehn_risk` und der
        kanonische Caution/No-Go-Text autoritativ aus dem Cache abgeleitet. Das LLM darf
        diese Strukturfelder zwar weiter setzen, sie werden aber stets ueberschrieben.

        Mutiert `result` in-place und schreibt einen Tracking-Eintrag in
        `result["_decisions_applied"]` (Liste).
        """
        foehn_eval = self._ctx_foehn_cache.get(cache_key, {})
        decision = compute_foehn_decision(foehn_eval)
        applied = apply_foehn_decision(result, decision)
        if applied:
            result.setdefault("_decisions_applied", []).append(applied)
            logger.info(f"Decision-Engine fuer {label}: {applied}")

    def _post_process_safety_spot(self, result: dict, spot: dict, date_str: str) -> dict:
        """Safety-only Post-Processing fuer einen Spot.
        Wendet die Decision-Engine an (WindOk0, Aloft-NotSafe/Conditional, GustFloor,
        OverclaimRelax, Foehn) plus den Foehn-Prosa-Strip. Siehe docs/DECISIONS.md.
        """
        name = spot["name"]
        result["spot"] = name
        result["date"] = date_str
        result["phase"] = "safety"

        # Tag-Sanitierung VOR den Decisions: damit decide_*-Funktionen keine
        # bereits durchgesickerten Tag-Strings im Text nochmal finden, und damit
        # nachgelagerte Foehn-Strips/Backstops auf bereinigte Texte wirken.
        _sanitize_llm_result(result)

        gust_info = self._ctx_gust_cache.get(f"{name}|{date_str}", {})
        if gust_info:
            result["wind_ok_count"] = gust_info.get("wind_ok_count", 0)
            result["wind_wrong_count"] = gust_info.get("wind_wrong_count", 0)

        # Decision-Pipe (Reihenfolge ist semantisch wichtig — nachfolgende Decisions
        # bauen auf dem Status-Stand der vorherigen auf):
        # 1. WindOk0 (kann not_safe forcieren)
        # 2. AloftNotSafe (kann not_safe forcieren)
        # 3. AloftConditional (nur bei status=safe → conditional)
        # 4. GustFloor (nur bei status=safe → conditional)
        # 5. OverclaimRelax (kann not_safe→conditional demoten)
        # 6. FlyabilityMechDanger (rough_pct>50 → conditional + tier=gray, cross-cutting)
        # 7. Foehn-Decision (autoritativ: foehn_risk + ggf. Status anheben)
        # 8. IsConditional (deterministische Ableitung aus safety_status)
        decision_label = f"{name}/{date_str}"
        for fn in (
            decide_wind_ok_zero,
            decide_aloft_not_safe,
            decide_aloft_conditional,
            decide_gust_floor,
            decide_overclaim_relax,
        ):
            tag = fn(result, gust_info, decision_label)
            if tag:
                result.setdefault("_decisions_applied", []).append(tag)

        # FlyabilityMechDanger — Sub-Trigger B aus alter decide_flyability_downgrade,
        # umgesiedelt in die Safety-Pipe (RATING_CONCEPT v1.3 Vorab-Fix #1). Cross-cutting:
        # schreibt fly_status=gray UND flippt safety_status auf conditional. Braucht tq
        # statt gust_info, daher separater Aufruf.
        tq = self._ctx_tq_cache.get(f"{name}|{date_str}", {})
        tag = decide_flyability_mech_danger(result, tq, decision_label)
        if tag:
            result.setdefault("_decisions_applied", []).append(tag)

        # Foehn (eigene Cache-Quelle, daher separat)
        self._apply_foehn_decision(result, f"{name}|{date_str}", label=decision_label)

        # is_conditional deterministisch ableiten (A2: conditional/not_safe overriden,
        # safe laesst LLM-Soft-Warnungen wie tiefe Wolkenbasis durch). MUSS nach Foehn
        # laufen, damit safety_status final ist.
        tag = decide_is_conditional(result, decision_label)
        if tag:
            result.setdefault("_decisions_applied", []).append(tag)

        # Foehn-Richtungs-Strip: bereinigt Summary/wind_summary/wind_shear bei
        # irrelevantem aktivem Foehn (Strukturfelder hat apply_foehn_decision schon erledigt).
        krit_foehn = spot.get("kritischer_foehn", "Süd")
        result = self._strip_irrelevant_foehn(result, krit_foehn)

        return result

    def _post_process_flyability_spot(self, result: dict, spot: dict, date_str: str, region_result: dict = None) -> dict:
        """Flyability-only Post-Processing fuer einen Spot.
        Wendet Tier-Normalisierung, Downgrade/Upgrade, Region-Gating,
        Streckenflug-Validierung und Rating-Berechnung an.
        Wird vom Split-Flow (Flyability-Phase) genutzt.

        result: rohes Flyability-LLM-JSON (ohne Safety-Felder).
        """
        name = spot["name"]

        # Tag-Sanitierung ZUERST — laeuft auch fuer not_safe-Pfad, damit
        # zurueckgegebene Texte (auch wenn Flyability-Felder leer sind) sauber sind.
        _sanitize_llm_result(result)

        # Wenn not_safe (aus Safety-Phase): Flyability-Felder leeren
        if result.get("safety_status") == "not_safe":
            result["fly_status"] = ""
            result["flyability_tier"] = ""
            result["streckenflug"] = {
                "tier": "kein_xc", "rating": 0,
                "summary": "", "limiting_factor": "spot_not_flyable",
                "region_context_available": False,
            }
            result["rating"] = _compute_rating_from_subratings(
                result, "", "not_safe", include_altitude=True
            )
            result["experience_score"] = _compute_experience_score(result["rating"])
            result["experience_stars"] = _compute_experience_stars(result["experience_score"])
            result["experience_rating"] = _compute_experience_rating(result["experience_score"])
            result["safety_rating"] = _compute_safety_rating(result)
            result["safety_score"] = _compute_safety_score(result["safety_rating"])
            result["safety_band"] = compute_safety_band(result)
            result["is_conditional"] = False
            result["conditional_reason"] = ""
            return result

        # Tier normalisieren
        tier = _normalize_flyability_tier(
            result.get("flyability_tier") or result.get("fly_status") or ""
        )
        result["flyability_tier"] = tier
        result["fly_status"] = tier

        # Flyability-Decisions (Decision-Engine):
        # 1. LowReward green/violet → gray (Sub-Trigger A: keine Thermik, C: prod_h zu niedrig).
        #    Sub-Trigger B (rough_pct>50, mech. Klapper) ist bereits in der Safety-Pipe als
        #    decide_flyability_mech_danger ausgefuehrt (RATING_CONCEPT v1.3 Vorab-Fix #1).
        # 2. gray → green Upgrade (Thermik trotz LLM-gray objektiv tragfaehig)
        # 3. Region-Gate violet → green (Spot ohne Region-Konsens)
        tq = self._ctx_tq_cache.get(f"{name}|{date_str}", {})
        decision_label = f"{name}/{date_str}"
        for tag in (
            decide_flyability_low_reward(result, tq, decision_label),
            decide_flyability_upgrade(result, tq, decision_label),
            decide_flyability_region_gate(result, region_result, decision_label),
        ):
            if tag:
                result.setdefault("_decisions_applied", []).append(tag)

        final_safety = result.get("safety_status", "")

        # Rating + Experience-Scores (RATING_CONCEPT v1.3 Vorab-Fix #3): kosmetische
        # Skalierung des bewaehrten 0-10 ratings auf 0-100 + 1-5-Mapping (User-Sprache:
        # "Rating 1-5"). Spot: 5 Sub-Ratings inkl. altitude_rating.
        result["rating"] = _compute_rating_from_subratings(
            result, "", final_safety, include_altitude=True
        )
        result["experience_score"] = _compute_experience_score(result["rating"])
        result["experience_stars"] = _compute_experience_stars(result["experience_score"])
        result["experience_rating"] = _compute_experience_rating(result["experience_score"])

        # Safety-Aggregation (Vorab-Fix #4): Weakest-Link aus 5 LLM-Sub-Ratings.
        # Im Split-Flow liegen die Subs nur im Safety-Result — nur ueberschreiben
        # wenn vorhanden (Combined-Flow).
        _safety_subs = ("wind_safety_rating", "gust_safety_rating",
                        "aloft_safety_rating", "foehn_safety_rating",
                        "weather_safety_rating")
        if all(result.get(f) is not None for f in _safety_subs):
            result["safety_rating"] = _compute_safety_rating(result)
            result["safety_score"] = _compute_safety_score(result["safety_rating"])
        # safety_band: Hybrid aus Hard-Overrides + Score
        result["safety_band"] = compute_safety_band(result)
        # comfort_index: Texture-Wert 0-100 aus rough_pct
        result["comfort_index"] = compute_comfort_index(tq)

        # Phase 4b (RATING_CONCEPT v1.3 §9.7 Single Source of Truth):
        # flyability_tier wird abgeleitet aus (safety_band, experience_stars).
        # LLM-/Decision-tier wird damit zur Compat-View, nicht mehr selbst-entschieden.
        legacy_tier = compute_legacy_flyability_tier(result)
        result["flyability_tier"] = legacy_tier
        result["fly_status"] = legacy_tier
        final_tier = legacy_tier

        # Streckenflug-Konsistenz nutzt View-tier
        sf = result.get("streckenflug")
        if not isinstance(sf, dict):
            sf = {
                "tier": "kein_xc", "rating": 0,
                "summary": "", "limiting_factor": "none",
                "region_context_available": False,
            }
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

        if final_tier in ("gray", "") and sf["tier"] != "kein_xc":
            logger.info(
                f"Streckenflug-Konsistenz: {name}/{date_str} tier={sf['tier']} → kein_xc "
                f"(Spot fly_status={final_tier or 'leer'})"
            )
            sf["tier"] = "kein_xc"
            if sf["limiting_factor"] == "none":
                sf["limiting_factor"] = "abgleiter_only"
            sf["rating"] = 0

        if result.get("flight_type") in ("Abgleiter", "Soaring") and sf["tier"] != "kein_xc":
            sf["tier"] = "kein_xc"
            if sf["limiting_factor"] == "none":
                sf["limiting_factor"] = "abgleiter_only"
            sf["rating"] = 0

        result["streckenflug"] = sf

        is_cond = bool(result.get("is_conditional", False))
        if final_safety == "not_safe":
            is_cond = False
        result["is_conditional"] = is_cond
        result["conditional_reason"] = (result.get("conditional_reason", "") or "") if is_cond else ""

        return result

    def _post_process_safety_region(self, result: dict, region: dict, date_str: str) -> dict:
        """Safety-only Post-Processing fuer eine Region (Decision-Pipe + Foehn-Strip)."""
        rname = region["region"]
        result["region"] = rname
        result["region_id"] = region["id"]
        result["date"] = date_str
        result["phase"] = "safety"

        # Tag-Sanitierung VOR den Decisions (siehe _post_process_safety_spot).
        _sanitize_llm_result(result)

        region_gust_info = self._ctx_gust_cache.get(f"{rname}|{date_str}", {})
        decision_label = f"{rname}/{date_str}"

        # Decision-Pipe (Reihenfolge wie bei Spot, plus Region-spezifischer Wind-Strong-Check):
        # 1. WindStrongMajority (kann not_safe forcieren — region-spezifisch)
        # 2. AloftNotSafe (kann not_safe forcieren)
        # 3. AloftConditional (nur bei status=safe → conditional)
        # 4. FlyabilityMechDanger (rough_pct>50 → conditional + tier=gray, cross-cutting)
        # 5. Foehn (autoritativ)
        # 6. IsConditional (deterministische Ableitung)
        tag = decide_wind_strong_majority(result, decision_label)
        if tag:
            result.setdefault("_decisions_applied", []).append(tag)
        for fn in (decide_aloft_not_safe, decide_aloft_conditional):
            tag = fn(result, region_gust_info, decision_label)
            if tag:
                result.setdefault("_decisions_applied", []).append(tag)

        # FlyabilityMechDanger (Sub-Trigger B, RATING_CONCEPT v1.3 Vorab-Fix #1)
        tq = self._ctx_tq_cache.get(f"{rname}|{date_str}", {})
        tag = decide_flyability_mech_danger(result, tq, decision_label)
        if tag:
            result.setdefault("_decisions_applied", []).append(tag)

        # Foehn (eigene Cache-Quelle)
        self._apply_foehn_decision(result, f"{rname}|{date_str}", label=decision_label)

        # is_conditional deterministisch ableiten (A2-Logik, siehe decision_engine.decide_is_conditional)
        tag = decide_is_conditional(result, decision_label)
        if tag:
            result.setdefault("_decisions_applied", []).append(tag)

        # Foehn-Richtungs-Strip: bereinigt Summary-Felder bei irrelevantem aktivem Foehn
        krit_foehn = region.get("kritischer_foehn", "Beide")
        result = self._strip_irrelevant_foehn(result, krit_foehn)

        return result

    def _post_process_flyability_region(self, result: dict, region: dict, date_str: str) -> dict:
        """Flyability-only Post-Processing fuer eine Region.
        Wendet Tier-Normalisierung, Downgrade/Upgrade und Rating-Berechnung an.
        """
        rname = region["region"]

        # Tag-Sanitierung ZUERST — laeuft auch fuer not_safe-Pfad.
        _sanitize_llm_result(result)

        if result.get("safety_status") == "not_safe":
            result["fly_status"] = ""
            result["flyability_tier"] = ""
            result["rating"] = _compute_rating_from_subratings(result, "", "not_safe")
            result["experience_score"] = _compute_experience_score(result["rating"])
            result["experience_stars"] = _compute_experience_stars(result["experience_score"])
            result["experience_rating"] = _compute_experience_rating(result["experience_score"])
            result["safety_rating"] = _compute_safety_rating(result)
            result["safety_score"] = _compute_safety_score(result["safety_rating"])
            result["safety_band"] = compute_safety_band(result)
            result["is_conditional"] = False
            result["conditional_reason"] = ""
            return result

        tier = _normalize_flyability_tier(
            result.get("flyability_tier") or result.get("fly_status") or ""
        )
        result["flyability_tier"] = tier
        result["fly_status"] = tier

        # Flyability-Decisions (Region: kein Region-Gate, da Region selbst die Vergleichsbasis).
        # MechDanger ist bereits in der Safety-Pipe gelaufen — hier nur LowReward + Upgrade.
        tq = self._ctx_tq_cache.get(f"{rname}|{date_str}", {})
        decision_label = f"{rname}/{date_str}"
        for tag in (
            decide_flyability_low_reward(result, tq, decision_label),
            decide_flyability_upgrade(result, tq, decision_label),
        ):
            if tag:
                result.setdefault("_decisions_applied", []).append(tag)

        final_safety = result.get("safety_status", "")

        # Rating + Experience-Scores (Vorab-Fix #3 / v1.4: Rating 1-10 als Primaeranzeige)
        result["rating"] = _compute_rating_from_subratings(result, "", final_safety)
        result["experience_score"] = _compute_experience_score(result["rating"])
        result["experience_stars"] = _compute_experience_stars(result["experience_score"])
        result["experience_rating"] = _compute_experience_rating(result["experience_score"])

        # Safety-Aggregation: Weakest-Link ueber 5 Subs.
        # _compute_safety_rating toleriert fehlende/0-Subs intern via _maybe()
        # (nimmt min der vorhandenen, default 5.0 falls keiner). Regionen haben
        # z.B. keine Gust-Daten — gust_safety_rating=None ist Regelfall, kein
        # Fehler. Vorheriger all()-Guard liess in solchen Faellen safety_score
        # ungesetzt, sodass compute_safety_band auf 0 → amber zurueckfiel.
        result["safety_rating"] = _compute_safety_rating(result)
        result["safety_score"] = _compute_safety_score(result["safety_rating"])
        result["safety_band"] = compute_safety_band(result)
        result["comfort_index"] = compute_comfort_index(tq)

        # Phase 4b: flyability_tier abgeleitet aus 2-Achsen-Werten (§9.7)
        legacy_tier = compute_legacy_flyability_tier(result)
        result["flyability_tier"] = legacy_tier
        result["fly_status"] = legacy_tier

        is_cond = bool(result.get("is_conditional", False))
        if final_safety == "not_safe":
            is_cond = False
        result["is_conditional"] = is_cond
        result["conditional_reason"] = (result.get("conditional_reason", "") or "") if is_cond else ""

        return result

    def run_all_analyses_batch_stream(self):
        """Batch-Modus vierphasig (Split-Flow):
        Phase 1: Region-Safety → Phase 2: Region-Flyability (nur safe/conditional)
        Phase 3: Spot-Safety → Phase 4: Spot-Flyability (nur safe/conditional)

        Spart ~40-50% Kosten gegenueber Combined-Flow, weil der teure Flyability-Prompt
        nur fuer fliegbare Tage laeuft.
        """
        if not self.analysis_client:
            yield {"event": "error", "data": {"message": f"Kein API-Key fuer Analyse-Provider '{self.analysis_provider}'"}}
            return
        if self.analysis_provider != "openai":
            yield {"event": "error", "data": {"message": (
                f"Batch-Modus nur mit ANALYSIS_PROVIDER=openai moeglich (aktuell: "
                f"'{self.analysis_provider}'). Bitte OPENAI_ANALYSIS_MODE=parallel setzen."
            )}}
            return

        # Cache leeren — Pre-Filter braucht aktuelle Werte aus _build_single_spot_context
        self._ctx_gust_cache.clear()
        self._ctx_tq_cache.clear()
        self._ctx_foehn_cache.clear()

        from source_area import find_region_for_point as _find_region

        all_regions = get_all_regions()
        regions_with_data = [r for r in all_regions if r["id"] in self.region_weather_data] if self.region_weather_data else []
        spots_to_analyze = [s for s in self.spots if s["name"] in self.weather_data] if self.weather_data else []
        forecast_dates = self._get_forecast_dates()
        _now = datetime.now()
        now_str = f"{_now.strftime('%Y-%m-%d %H:%M:%S')} ({_weekday_de(_now)})"

        total_items = (len(regions_with_data) + len(spots_to_analyze)) * len(forecast_dates)
        yield {"event": "init", "data": {
            "mode": "batch_split",
            "regions_count": len(regions_with_data),
            "spots_count": len(spots_to_analyze),
            "days": len(forecast_dates),
            "total_calls": total_items,
        }}

        # Cost-Telemetrie: aggregiert Tokens pro Phase, schreibt am Ende eine
        # JSONL-Zeile nach config.COST_TELEMETRY_PATH.
        cost_tracker = BatchCostTracker(
            mode="batch", provider=self.analysis_provider, model=self.analysis_model,
        )

        region_safety_results: dict = {}   # {rid: {date_str: safety_result}}
        region_results: dict = {}           # {rid: {date_str: merged_result}}
        spot_safety_results: dict = {}      # {name: {date_str: safety_result}}
        spot_results: dict = {}             # {name: {date_str: merged_result}}

        # Region-Kontexte cachen (werden in Phase 1+2 gebraucht)
        region_contexts: dict = {}  # {f"{rid}|{date_str}": ctx}

        # ══════════════════════════════════════════════════════════════
        # PHASE 1: Region-Safety Batch
        # ══════════════════════════════════════════════════════════════
        yield {"event": "phase", "data": {"phase": "batch_region_safety", "total": 0}}
        region_safety_requests: list = []
        region_safety_meta: dict = {}

        for region in regions_with_data:
            rid = region["id"]
            for date_str in forecast_dates:
                ctx = self._build_single_region_context(region, date_str)
                if not ctx:
                    continue
                region_contexts[f"{rid}|{date_str}"] = ctx
                cid = f"region_safety|{rid}|{date_str}"
                region_safety_requests.append({
                    "custom_id": cid,
                    "method": "POST",
                    "url": "/v1/chat/completions",
                    "body": {
                        "model": self.analysis_model,
                        "messages": [
                            {"role": "system", "content": prompts.REGION_SAFETY_PROMPT},
                            {"role": "user", "content": f"AKTUELLE LOKALZEIT: {now_str}\n\n{ctx}"},
                        ],
                        "temperature": 0.2,
                        "max_tokens": _resolve_max_tokens(self.analysis_model, 1500),
                        "response_format": {"type": "json_object"},
                    },
                })
                region_safety_meta[cid] = (rid, date_str, region)

        if region_safety_requests:
            yield {"event": "phase", "data": {"phase": "batch_submit_region_safety", "total": len(region_safety_requests)}}
            try:
                jsonl = self._build_batch_jsonl(region_safety_requests)
                batch_id = self._submit_batch(jsonl, f"Region-Safety ({len(region_safety_requests)} Requests)")
            except Exception as e:
                logger.error(f"Region-Safety-Batch-Submit fehlgeschlagen: {e}")
                yield {"event": "error", "data": {"message": f"Region-Safety-Batch-Submit fehlgeschlagen: {e}"}}
                return

            yield {"event": "phase", "data": {"phase": "batch_poll_region_safety", "batch_id": batch_id, "total": len(region_safety_requests)}}
            try:
                raw_results, usage = self._poll_batch(batch_id)
                cost_tracker.record(
                    "region_safety",
                    in_tok=usage["in_tok"], out_tok=usage["out_tok"],
                    cached_tok=usage["cached_tok"], calls=usage["calls"],
                )
                if cost_tracker.check_cap(config.LLM_COST_CAP_USD):
                    cost_tracker.write(config.COST_TELEMETRY_PATH)
                    yield {"event": "error", "data": {"message": "Kosten-Cap erreicht — Batch gestoppt"}}
                    return
            except Exception as e:
                logger.error(f"Region-Safety-Batch-Poll fehlgeschlagen: {e}")
                cost_tracker.errors += 1
                cost_tracker.write(config.COST_TELEMETRY_PATH)
                yield {"event": "error", "data": {"message": f"Region-Safety-Batch fehlgeschlagen: {e}"}}
                return

            for cid, raw_result in raw_results.items():
                m = region_safety_meta.get(cid)
                if not m:
                    continue
                rid, date_str, region = m
                if raw_result.get("error"):
                    region_safety_results.setdefault(rid, {})[date_str] = {
                        "safety_status": "error", "phase": "safety",
                        "date": date_str, "region": region["region"], "region_id": rid,
                        "error": raw_result["error"],
                    }
                    continue
                try:
                    processed = self._post_process_safety_region(raw_result, region, date_str)
                    region_safety_results.setdefault(rid, {})[date_str] = processed
                except Exception as e:
                    logger.error(f"[BATCH-P1] Region-Safety Post-Processing fuer {rid}/{date_str}: {e}")
                    region_safety_results.setdefault(rid, {})[date_str] = {
                        "safety_status": "error", "phase": "safety",
                        "date": date_str, "region": region["region"], "region_id": rid,
                        "error": str(e),
                    }

            yield {"event": "progress", "data": {"phase": "batch_region_safety_done", "completed": len(raw_results), "total": len(region_safety_requests)}}
            logger.info(f"[BATCH] Phase 1 (Region-Safety) fertig: {sum(len(d) for d in region_safety_results.values())} Ergebnisse")

        # ══════════════════════════════════════════════════════════════
        # PHASE 2: Region-Flyability Batch (nur safe/conditional)
        # ══════════════════════════════════════════════════════════════
        region_fly_requests: list = []
        region_fly_meta: dict = {}

        for rid, dates in region_safety_results.items():
            for date_str, safety_res in dates.items():
                if safety_res.get("safety_status") not in ("safe", "conditional"):
                    # not_safe/error → kein Flyability-Call, Minimal-Werte setzen
                    region_results.setdefault(rid, {})[date_str] = self._not_safe_minimal_flyability(safety_res, is_spot=False)
                    continue
                # Kontext fuer Flyability (gleicher wie Safety + Safety-Injection)
                ctx = region_contexts.get(f"{rid}|{date_str}", "")
                if not ctx:
                    region_results.setdefault(rid, {})[date_str] = self._not_safe_minimal_flyability(safety_res, is_spot=False)
                    continue
                safety_block = self._format_safety_injection(safety_res)
                # Region-Objekt wiederfinden
                region_obj = next((r for r in regions_with_data if r["id"] == rid), None)
                if not region_obj:
                    continue

                cid = f"region_fly|{rid}|{date_str}"
                region_fly_requests.append({
                    "custom_id": cid,
                    "method": "POST",
                    "url": "/v1/chat/completions",
                    "body": {
                        "model": self.analysis_model,
                        "messages": [
                            {"role": "system", "content": prompts.REGION_FLYABILITY_PROMPT},
                            {"role": "user", "content": f"AKTUELLE LOKALZEIT: {now_str}\n\n{ctx}\n\n{safety_block}"},
                        ],
                        "temperature": 0.2,
                        "max_tokens": _resolve_max_tokens(self.analysis_model, 2500),
                        "response_format": {"type": "json_object"},
                    },
                })
                region_fly_meta[cid] = (rid, date_str, region_obj, safety_res)

        if region_fly_requests:
            yield {"event": "phase", "data": {"phase": "batch_submit_region_flyability", "total": len(region_fly_requests)}}
            try:
                jsonl = self._build_batch_jsonl(region_fly_requests)
                batch_id = self._submit_batch(jsonl, f"Region-Flyability ({len(region_fly_requests)} Requests)")
            except Exception as e:
                logger.error(f"Region-Flyability-Batch-Submit fehlgeschlagen: {e}")
                yield {"event": "error", "data": {"message": f"Region-Flyability-Batch-Submit fehlgeschlagen: {e}"}}
                return

            yield {"event": "phase", "data": {"phase": "batch_poll_region_flyability", "batch_id": batch_id, "total": len(region_fly_requests)}}
            try:
                raw_results, usage = self._poll_batch(batch_id)
                cost_tracker.record(
                    "region_fly",
                    in_tok=usage["in_tok"], out_tok=usage["out_tok"],
                    cached_tok=usage["cached_tok"], calls=usage["calls"],
                )
                if cost_tracker.check_cap(config.LLM_COST_CAP_USD):
                    cost_tracker.write(config.COST_TELEMETRY_PATH)
                    yield {"event": "error", "data": {"message": "Kosten-Cap erreicht — Batch gestoppt"}}
                    return
            except Exception as e:
                logger.error(f"Region-Flyability-Batch-Poll fehlgeschlagen: {e}")
                cost_tracker.errors += 1
                cost_tracker.write(config.COST_TELEMETRY_PATH)
                yield {"event": "error", "data": {"message": f"Region-Flyability-Batch fehlgeschlagen: {e}"}}
                return

            for cid, raw_result in raw_results.items():
                m = region_fly_meta.get(cid)
                if not m:
                    continue
                rid, date_str, region_obj, safety_res = m
                if raw_result.get("error"):
                    # Fallback: Safety-Ergebnis mit Minimal-Flyability
                    region_results.setdefault(rid, {})[date_str] = self._not_safe_minimal_flyability(safety_res, is_spot=False)
                    continue
                try:
                    # Safety-Felder ins Ergebnis uebernehmen
                    raw_result["safety_status"] = safety_res.get("safety_status", "")
                    raw_result["safe_window"] = safety_res.get("safe_window", "")
                    raw_result["wind_calm_count"] = safety_res.get("wind_calm_count", 0)
                    raw_result["wind_moderate_count"] = safety_res.get("wind_moderate_count", 0)
                    raw_result["wind_strong_count"] = safety_res.get("wind_strong_count", 0)
                    raw_result["region"] = region_obj["region"]
                    raw_result["region_id"] = rid
                    raw_result["date"] = date_str
                    processed = self._post_process_flyability_region(raw_result, region_obj, date_str)
                    # Merge: Safety + Flyability
                    merged = self._merge_safety_flyability(safety_res, processed)
                    self._finalize_tags(merged, f"{region_obj['region']}|{date_str}", is_region=True)
                    region_results.setdefault(rid, {})[date_str] = merged
                except Exception as e:
                    logger.error(f"[BATCH-P2] Region-Flyability Post-Processing fuer {rid}/{date_str}: {e}")
                    fallback = self._not_safe_minimal_flyability(safety_res, is_spot=False)
                    self._finalize_tags(fallback, f"{region_obj['region']}|{date_str}", is_region=True)
                    region_results.setdefault(rid, {})[date_str] = fallback

            yield {"event": "progress", "data": {"phase": "batch_region_flyability_done", "completed": len(raw_results), "total": len(region_fly_requests)}}
            logger.info(f"[BATCH] Phase 2 (Region-Flyability) fertig: {len(region_fly_requests)} Calls (uebersprungen: {sum(len(d) for d in region_safety_results.values()) - len(region_fly_requests)} not_safe)")

        # Regionen ohne Flyability-Call (alle not_safe) muessen trotzdem in region_results
        for rid, dates in region_safety_results.items():
            for date_str, safety_res in dates.items():
                if rid not in region_results or date_str not in region_results.get(rid, {}):
                    fallback = self._not_safe_minimal_flyability(safety_res, is_spot=False)
                    rname = safety_res.get("region", rid)
                    self._finalize_tags(fallback, f"{rname}|{date_str}", is_region=True)
                    region_results.setdefault(rid, {})[date_str] = fallback

        # ══════════════════════════════════════════════════════════════
        # PHASE 3: Spot-Safety Batch
        # ══════════════════════════════════════════════════════════════
        yield {"event": "phase", "data": {"phase": "batch_spot_safety", "total": 0}}

        # Pro-Spot Region-Mapping einmalig vorberechnen
        spot_region_map: dict = {}
        for spot in spots_to_analyze:
            try:
                reg = _find_region(spot["latitude"], spot["longitude"])
                spot_region_map[spot["name"]] = reg["id"] if reg else None
            except Exception as e:
                logger.warning(f"Region-Mapping fuer {spot['name']} fehlgeschlagen: {e}")
                spot_region_map[spot["name"]] = None

        spot_safety_requests: list = []
        spot_safety_meta: dict = {}
        spot_contexts: dict = {}  # {f"{name}|{date_str}": ctx}
        prefilter_count = 0

        for spot in spots_to_analyze:
            name = spot["name"]
            rid = spot_region_map.get(name)
            for date_str in forecast_dates:
                # Region-Ergebnis fuer Kontext-Builder (Streckenflug braucht es spaeter)
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
                    spot_results.setdefault(name, {})[date_str] = {
                        "spot": name, "date": date_str,
                        "safety_status": "no_data", "phase": "split",
                        "summary": "Keine Wetterdaten fuer diesen Tag",
                    }
                    continue

                spot_contexts[f"{name}|{date_str}"] = ctx

                # Deterministischer Pre-Filter
                prefilter = self._prefilter_not_safe(spot, date_str)
                if prefilter is not None:
                    spot_results.setdefault(name, {})[date_str] = prefilter
                    prefilter_count += 1
                    continue

                cid = f"spot_safety|{name}|{date_str}"
                spot_safety_requests.append({
                    "custom_id": cid,
                    "method": "POST",
                    "url": "/v1/chat/completions",
                    "body": {
                        "model": self.analysis_model,
                        "messages": [
                            {"role": "system", "content": prompts.SPOT_SAFETY_PROMPT},
                            {"role": "user", "content": f"AKTUELLE LOKALZEIT: {now_str}\n\n{ctx}"},
                        ],
                        "temperature": 0.2,
                        "max_tokens": _resolve_max_tokens(self.analysis_model, 1500),
                        "response_format": {"type": "json_object"},
                    },
                })
                spot_safety_meta[cid] = (name, date_str, spot)

        cost_tracker.prefilter_skipped = prefilter_count
        if prefilter_count:
            logger.info(
                f"[BATCH] Pre-Filter: {prefilter_count} Spots/Tage als not_safe markiert "
                f"(kein LLM-Call) — {len(spot_safety_requests)} Spots verbleiben fuer Safety-Batch"
            )

        if not spot_safety_requests and not region_safety_requests and not spot_results:
            yield {"event": "error", "data": {"message": "Keine Daten zum Verarbeiten"}}
            return

        if spot_safety_requests:
            yield {"event": "phase", "data": {"phase": "batch_submit_spot_safety", "total": len(spot_safety_requests)}}
            try:
                jsonl = self._build_batch_jsonl(spot_safety_requests)
                batch_id = self._submit_batch(jsonl, f"Spot-Safety ({len(spot_safety_requests)} Requests)")
            except Exception as e:
                logger.error(f"Spot-Safety-Batch-Submit fehlgeschlagen: {e}")
                yield {"event": "error", "data": {"message": f"Spot-Safety-Batch-Submit fehlgeschlagen: {e}"}}
                return

            yield {"event": "phase", "data": {"phase": "batch_poll_spot_safety", "batch_id": batch_id, "total": len(spot_safety_requests)}}
            try:
                raw_results, usage = self._poll_batch(batch_id)
                cost_tracker.record(
                    "spot_safety",
                    in_tok=usage["in_tok"], out_tok=usage["out_tok"],
                    cached_tok=usage["cached_tok"], calls=usage["calls"],
                )
                if cost_tracker.check_cap(config.LLM_COST_CAP_USD):
                    cost_tracker.write(config.COST_TELEMETRY_PATH)
                    yield {"event": "error", "data": {"message": "Kosten-Cap erreicht — Batch gestoppt"}}
                    return
            except Exception as e:
                logger.error(f"Spot-Safety-Batch-Poll fehlgeschlagen: {e}")
                cost_tracker.errors += 1
                cost_tracker.write(config.COST_TELEMETRY_PATH)
                yield {"event": "error", "data": {"message": f"Spot-Safety-Batch fehlgeschlagen: {e}"}}
                return

            for cid, raw_result in raw_results.items():
                m = spot_safety_meta.get(cid)
                if not m:
                    continue
                name, date_str, spot = m
                if raw_result.get("error"):
                    spot_safety_results.setdefault(name, {})[date_str] = {
                        "safety_status": "error", "phase": "safety",
                        "date": date_str, "spot": name,
                        "error": raw_result["error"],
                    }
                    continue
                try:
                    processed = self._post_process_safety_spot(raw_result, spot, date_str)
                    spot_safety_results.setdefault(name, {})[date_str] = processed
                except Exception as e:
                    logger.error(f"[BATCH-P3] Spot-Safety Post-Processing fuer {name}/{date_str}: {e}")
                    spot_safety_results.setdefault(name, {})[date_str] = {
                        "safety_status": "error", "phase": "safety",
                        "date": date_str, "spot": name,
                        "error": str(e),
                    }

            yield {"event": "progress", "data": {"phase": "batch_spot_safety_done", "completed": len(raw_results), "total": len(spot_safety_requests)}}
            logger.info(f"[BATCH] Phase 3 (Spot-Safety) fertig: {sum(len(d) for d in spot_safety_results.values())} Ergebnisse")

        # ══════════════════════════════════════════════════════════════
        # PHASE 4: Spot-Flyability Batch (nur safe/conditional)
        # ══════════════════════════════════════════════════════════════
        spot_fly_requests: list = []
        spot_fly_meta: dict = {}

        for name, dates in spot_safety_results.items():
            for date_str, safety_res in dates.items():
                if safety_res.get("safety_status") not in ("safe", "conditional"):
                    # not_safe/error → Minimal-Flyability
                    spot_results.setdefault(name, {})[date_str] = self._not_safe_minimal_flyability(safety_res, is_spot=True)
                    continue
                ctx = spot_contexts.get(f"{name}|{date_str}", "")
                if not ctx:
                    spot_results.setdefault(name, {})[date_str] = self._not_safe_minimal_flyability(safety_res, is_spot=True)
                    continue
                safety_block = self._format_safety_injection(safety_res)
                # Spot-Objekt wiederfinden
                spot_obj = next((s for s in spots_to_analyze if s["name"] == name), None)
                if not spot_obj:
                    continue

                cid = f"spot_fly|{name}|{date_str}"
                spot_fly_requests.append({
                    "custom_id": cid,
                    "method": "POST",
                    "url": "/v1/chat/completions",
                    "body": {
                        "model": self.analysis_model,
                        "messages": [
                            {"role": "system", "content": prompts.SPOT_FLYABILITY_PROMPT},
                            {"role": "user", "content": f"AKTUELLE LOKALZEIT: {now_str}\n\n{ctx}\n\n{safety_block}"},
                        ],
                        "temperature": 0.2,
                        "max_tokens": _resolve_max_tokens(self.analysis_model, 2500),
                        "response_format": {"type": "json_object"},
                    },
                })
                spot_fly_meta[cid] = (name, date_str, spot_obj, safety_res)

        if spot_fly_requests:
            yield {"event": "phase", "data": {"phase": "batch_submit_spot_flyability", "total": len(spot_fly_requests)}}
            try:
                jsonl = self._build_batch_jsonl(spot_fly_requests)
                batch_id = self._submit_batch(jsonl, f"Spot-Flyability ({len(spot_fly_requests)} Requests)")
            except Exception as e:
                logger.error(f"Spot-Flyability-Batch-Submit fehlgeschlagen: {e}")
                yield {"event": "error", "data": {"message": f"Spot-Flyability-Batch-Submit fehlgeschlagen: {e}"}}
                return

            yield {"event": "phase", "data": {"phase": "batch_poll_spot_flyability", "batch_id": batch_id, "total": len(spot_fly_requests)}}
            try:
                raw_results, usage = self._poll_batch(batch_id)
                cost_tracker.record(
                    "spot_fly",
                    in_tok=usage["in_tok"], out_tok=usage["out_tok"],
                    cached_tok=usage["cached_tok"], calls=usage["calls"],
                )
                if cost_tracker.check_cap(config.LLM_COST_CAP_USD):
                    cost_tracker.write(config.COST_TELEMETRY_PATH)
                    yield {"event": "error", "data": {"message": "Kosten-Cap erreicht — Batch gestoppt"}}
                    return
            except Exception as e:
                logger.error(f"Spot-Flyability-Batch-Poll fehlgeschlagen: {e}")
                cost_tracker.errors += 1
                cost_tracker.write(config.COST_TELEMETRY_PATH)
                yield {"event": "error", "data": {"message": f"Spot-Flyability-Batch fehlgeschlagen: {e}"}}
                return

            for cid, raw_result in raw_results.items():
                m = spot_fly_meta.get(cid)
                if not m:
                    continue
                name, date_str, spot_obj, safety_res = m
                if raw_result.get("error"):
                    fallback = self._not_safe_minimal_flyability(safety_res, is_spot=True)
                    self._finalize_tags(fallback, f"{name}|{date_str}", is_region=False)
                    spot_results.setdefault(name, {})[date_str] = fallback
                    continue
                try:
                    # Safety-Felder ins Ergebnis uebernehmen
                    raw_result["safety_status"] = safety_res.get("safety_status", "")
                    raw_result["safe_window"] = safety_res.get("safe_window", "")
                    raw_result["spot"] = name
                    raw_result["date"] = date_str

                    # Region-Result fuer Flyability-Post-Processing (Region-Gating)
                    rid = spot_region_map.get(name)
                    region_result = None
                    if rid and rid in region_results:
                        rr = region_results[rid].get(date_str)
                        if rr and rr.get("safety_status") not in ("error", "no_data"):
                            region_result = rr

                    processed = self._post_process_flyability_spot(raw_result, spot_obj, date_str, region_result=region_result)
                    # Merge: Safety + Flyability
                    merged = self._merge_safety_flyability(safety_res, processed)
                    self._finalize_tags(merged, f"{name}|{date_str}", is_region=False)
                    spot_results.setdefault(name, {})[date_str] = merged
                except Exception as e:
                    logger.error(f"[BATCH-P4] Spot-Flyability Post-Processing fuer {name}/{date_str}: {e}")
                    fallback = self._not_safe_minimal_flyability(safety_res, is_spot=True)
                    self._finalize_tags(fallback, f"{name}|{date_str}", is_region=False)
                    spot_results.setdefault(name, {})[date_str] = fallback

            yield {"event": "progress", "data": {"phase": "batch_spot_flyability_done", "completed": len(raw_results), "total": len(spot_fly_requests)}}
            logger.info(
                f"[BATCH] Phase 4 (Spot-Flyability) fertig: {len(spot_fly_requests)} Calls "
                f"(uebersprungen: {sum(len(d) for d in spot_safety_results.values()) - len(spot_fly_requests)} not_safe)"
            )

        # Spots ohne Flyability-Call (alle not_safe) muessen trotzdem in spot_results
        for name, dates in spot_safety_results.items():
            for date_str, safety_res in dates.items():
                if name not in spot_results or date_str not in spot_results.get(name, {}):
                    fallback = self._not_safe_minimal_flyability(safety_res, is_spot=True)
                    self._finalize_tags(fallback, f"{name}|{date_str}", is_region=False)
                    spot_results.setdefault(name, {})[date_str] = fallback

        logger.info(
            f"[BATCH] Split-Flow komplett: {sum(len(d) for d in spot_results.values())} Spot-Ergebnisse, "
            f"{sum(len(d) for d in region_results.values())} Region-Ergebnisse"
        )

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
                self._attach_rating_fields(entry, result)
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
                self._attach_rating_fields(entry, result)
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

        # Cost-Telemetrie schreiben (immer, auch ohne Fehler).
        cost_record = cost_tracker.write(config.COST_TELEMETRY_PATH)

        safety_count = sum(p["calls"] for k, p in cost_tracker.phases.items() if k.endswith("_safety"))
        fly_count    = sum(p["calls"] for k, p in cost_tracker.phases.items() if k.endswith("_fly"))
        total_calls  = safety_count + fly_count
        logger.info(
            f"Batch-Split-Analysen abgeschlossen: {total_calls} Calls "
            f"(Safety={safety_count}, Flyability={fly_count}, "
            f"Skip={cost_tracker.prefilter_skipped}, Kosten=${cost_record['est_usd']})"
        )

        yield {"event": "done", "data": {
            "success": True,
            "mode": "batch",
            "total_calls": total_calls,
            "safety_count": safety_count,
            "flyability_count": fly_count,
            "prefilter_skipped": cost_tracker.prefilter_skipped,
            "est_usd": cost_record["est_usd"],
            "duration_s": cost_record["duration_s"],
        }}

    def run_all_analyses_stream(self):
        """Orchestrator: Regionen + Spots PARALLEL in einem gemeinsamen Pool.
        Einzelne Phase: kombinierte Safety+Flyability-Calls fuer alle Spots/Regionen.
        Dispatcht zum Batch-Modus wenn config.OPENAI_ANALYSIS_MODE == 'batch'
        UND analysis_provider == 'openai'.
        """
        # Batch-API nur mit OpenAI. Bei anderem Provider automatisch auf parallel fallen.
        if config.OPENAI_ANALYSIS_MODE == "batch":
            if self.analysis_provider == "openai":
                yield from self.run_all_analyses_batch_stream()
                return
            logger.warning(
                "OPENAI_ANALYSIS_MODE=batch ignoriert — Batch-API nur fuer OpenAI verfuegbar, "
                "aktueller Analyse-Provider: '%s'. Falle auf parallel-Modus zurueck.",
                self.analysis_provider,
            )

        self._api_abort = threading.Event()
        self._api_abort_reason = 'Analyse abgebrochen'
        self._ctx_gust_cache.clear()
        self._ctx_tq_cache.clear()
        self._ctx_foehn_cache.clear()

        # Cost-Telemetrie fuer Parallel-Pfad. Wird von _record_call_usage()
        # in den per-Call-Methoden gefuettert.
        self._cost_tracker = BatchCostTracker(
            mode="parallel", provider=self.analysis_provider, model=self.analysis_model,
        )

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
            # MERGE + PERSIST: Region-Ergebnisse ZUERST.
            # Reihenfolge bewusst Region → Spot: wenn der Spot-Merge crasht,
            # bleiben Regionen im Cache erhalten (frueher gegenteilig — ein
            # spaeterer Crash konnte beide Caches inkonsistent machen).
            # Per-Eintrag-try/except: ein einzelner Bad-Result reisst nicht
            # die anderen Eintraege mit.
            # ══════════════════════════════════════════════════════════════
            region_merged = {}
            for rid, days_dict in region_results.items():
                region_merged[rid] = {}
                for date_str, result in days_dict.items():
                    try:
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
                        self._attach_rating_fields(entry, result)
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
                    except Exception as e:
                        logger.exception(f"Region-Merge fehlgeschlagen fuer {rid}/{date_str}: {e}")
                        # Diese Region/Tag-Kombination wird uebersprungen,
                        # der Rest des Merges laeuft weiter durch.

            self.region_analyses = region_merged
            self.region_analyses_loaded_at = datetime.now()
            self._save_region_analyses_cache()
            if self.instantdb:
                threading.Thread(target=self._push_region_analyses_to_instantdb, daemon=True).start()

            # ══════════════════════════════════════════════════════════════
            # MERGE + PERSIST: Spot-Ergebnisse (NACH Regionen, siehe oben).
            # ══════════════════════════════════════════════════════════════
            spot_merged = {}
            for spot_name, days_dict in spot_results.items():
                spot_merged[spot_name] = {}
                for date_str, result in days_dict.items():
                    try:
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
                        self._attach_rating_fields(entry, result)
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
                    except Exception as e:
                        logger.exception(f"Spot-Merge fehlgeschlagen fuer {spot_name}/{date_str}: {e}")
                        # Diese Spot/Tag-Kombination wird uebersprungen,
                        # der Rest des Merges laeuft weiter durch.

            self.spot_analyses = spot_merged
            self.analyses_loaded_at = datetime.now()
            self._analyses_stale = False
            self._save_analyses_cache()
            if self.instantdb:
                threading.Thread(target=self._push_analyses_to_instantdb, daemon=True).start()

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

            cost_record = self._cost_tracker.write(config.COST_TELEMETRY_PATH)

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
                "est_usd": cost_record["est_usd"],
                "duration_s": cost_record["duration_s"],
            }}

        except GeneratorExit:
            logger.warning("[UNIFIED] Client hat Verbindung geschlossen (GeneratorExit)")
            try:
                self._cost_tracker.write(config.COST_TELEMETRY_PATH)
            except Exception:
                pass
        except Exception as e:
            logger.exception("[UNIFIED] run_all_analyses_stream Fehler")
            try:
                self._cost_tracker.errors += 1
                self._cost_tracker.write(config.COST_TELEMETRY_PATH)
            except Exception:
                pass
            yield {"event": "error", "data": {"message": str(e)}}
        finally:
            self._cost_tracker = None

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

