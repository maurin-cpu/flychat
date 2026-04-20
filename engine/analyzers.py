"""
Flychat Engine — Mixin: AnalyzersMixin.

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
    _interpolate_wind_at_altitude,
)

logger = logging.getLogger(__name__)


class AnalyzersMixin:
    def _build_and_analyze_spot(self, spot, date_str: str) -> dict:
        """Worker-Wrapper: Context bauen + kombinierte Safety+Flyability-Analyse.
        Returns combined result dict.  Includes a deterministic pre-filter that
        skips the LLM call for clearly not_safe days (saves ~50-60 % of API costs)."""
        name = spot["name"]
        ctx = self._build_single_spot_context(spot, date_str, mode="dashboard")
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

        return self._combined_analysis_single_spot_day(spot, date_str, ctx)

    def _prefilter_not_safe(self, spot, date_str: str):
        """Prueft anhand der deterministischen Cache-Daten ob ein Spot/Tag
        offensichtlich not_safe ist.  Gibt ein fertiges Result-Dict zurueck
        oder None wenn der LLM-Call noetig ist.

        Kriterien (alle aus dem eigenen Regelwerk abgeleitet):
        1. Keine einzige WIND-OK Stunde  → falsche Windrichtung ganztaegig
        2. Weniger als 3 saubere Stunden → zu wenig selbst fuer Abgleiter
           (3 saubere Stunden = mindestens Bronze/Abgleiter-Tier moeglich →
            LLM entscheiden lassen statt hartem NO-GO)
        3. Ganztaegig Regen (>= total-2)  → kein nutzbares Fenster
        """
        name = spot["name"]
        cache_key = f"{name}|{date_str}"
        gust_info = self._ctx_gust_cache.get(cache_key)
        if not gust_info:
            return None  # Kein Cache → LLM entscheiden lassen

        wind_ok = gust_info.get("wind_ok_count", -1)
        wind_wrong = gust_info.get("wind_wrong_count", 0)
        clean_cnt = gust_info.get("clean_hours_count", -1)
        rain_cnt = gust_info.get("rain_hours", 0)
        hard_warn_h = gust_info.get("hard_warning_hours", 0)
        total_hours = wind_ok + wind_wrong if wind_ok >= 0 else 0
        max_gust = int(gust_info.get("max_surface_gust", 0) or 0)
        rain_hour_list = gust_info.get("rain_hour_list", [])

        no_go = []
        summary_parts = []

        # Regel 1: Keine WIND-OK Stunde
        if wind_ok == 0 and total_hours > 0:
            no_go.append("Windrichtung: Ganztaegig ausserhalb des erlaubten Sektors")
            summary_parts.append(
                f"Die Windrichtung liegt den ganzen Tag ausserhalb des erlaubten Sektors "
                f"({spot.get('windrichtung', '?')}). Kein fliegbares Fenster."
            )

        # Regel 2: Weniger als 3 saubere Stunden (zu wenig selbst fuer Abgleiter)
        # 3+ saubere Stunden fallen durch → LLM darf Bronze/Abgleiter-Tag bewerten.
        elif clean_cnt >= 0 and clean_cnt < 3 and total_hours > 0:
            reason_parts = []
            if wind_wrong > 0:
                reason_parts.append(f"falsche Windrichtung in {wind_wrong}h")
            if hard_warn_h > 0:
                reason_parts.append(f"harte Warnungen in {hard_warn_h}h")
                # Spezifischere Gruende
                gd = gust_info.get("gust_danger_hours", 0)
                ad = gust_info.get("aloft_gust_danger_hours", 0)
                if gd > 0:
                    no_go.append(f"Boeen: Bodenboeen ueber 40 km/h in {gd}h (max ~{max_gust} km/h)")
                if ad > 0:
                    no_go.append(f"Hoehenboeen: Ueber 40 km/h im Flugbereich in {ad}h")
                if rain_cnt > 0:
                    no_go.append(f"Niederschlag: Regen in {rain_cnt}h ({', '.join(rain_hour_list[:6])})")
            if not no_go:
                no_go.append(
                    f"Flugfenster: Nur {clean_cnt} saubere Stunden — "
                    f"zu wenig fuer Start/Landung (Minimum 3h)"
                )
            summary_parts.append(
                f"Nur {clean_cnt} von {total_hours} Stunden sind sauber "
                f"({', '.join(reason_parts) if reason_parts else 'diverse Einschraenkungen'}). "
                f"Kein ausreichendes Flugfenster vorhanden."
            )

        # Regel 3: Ganztaegig Regen
        elif total_hours > 0 and rain_cnt >= total_hours - 2 and rain_cnt >= 4:
            no_go.append(f"Niederschlag: Regen in {rain_cnt} von {total_hours} Stunden")
            summary_parts.append(
                f"Nahezu ganztaegiger Niederschlag ({rain_cnt} von {total_hours} Stunden). "
                f"Kein nutzbares Flugfenster."
            )

        if not no_go:
            return None  # Kein klarer not_safe-Fall → LLM entscheiden lassen

        logger.info(
            f"Pre-Filter not_safe fuer {name}/{date_str}: "
            f"wind_ok={wind_ok}, clean={clean_cnt}, rain={rain_cnt}/{total_hours}"
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

    def _combined_analysis_single_spot_day(self, spot, date_str: str, context: str) -> dict:
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
                {"role": "system", "content": SPOT_COMBINED_PROMPT},
                {"role": "user", "content": (
                    f"AKTUELLE LOKALZEIT: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ({_weekday_de(datetime.now())})\n\n"
                    f"{context}"
                )},
            ]

            # Retry-Logik: 1 Wiederholung bei Fehler
            last_err = None
            for attempt in range(2):
                try:
                    response = self.client.chat.completions.create(
                        model=self.model,
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
            result["spot"] = name
            result["date"] = date_str
            result["phase"] = "combined"

            # ═══ SAFETY POST-PROCESSING (identisch zu altem _safety_check_single_spot_day) ═══

            # Deterministische Zahlen aus Cache injizieren (Halluzinations-Schutz)
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

            # ═══ FLYABILITY POST-PROCESSING (identisch zu altem _flyability_single_spot_day) ═══

            # Wenn not_safe: Flyability-Felder leeren
            if result.get("safety_status") == "not_safe":
                result["fly_status"] = ""
                result["flyability_tier"] = ""
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
                tqd = tq.get("tq_danger_h", 0)
                rough_h = tq.get("rough_danger_h", 0)
                peak = tq.get("peak_climb_proxy", 0)
                prod_h = tq.get("productive_thermal_h", 0)

                # Downgrade: green/violet → gray
                # Nur bei: keine Thermik (peak<0.3), zu wenig produktive Stunden
                # ODER >50% THERMAL-ROUGH-UNUSABLE (mech. gefaehrlich, Klapper-Gefahr).
                # THERMAL-TORN/SHEAR-UNUSABLE triggern KEIN gray (nur Qualitaets-Issue).
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
                # Upgrade basiert auf productive_thermal_h (schliesst ROUGH-UNUSABLE bereits aus).
                # TORN/SHEAR-UNUSABLE verhindern Upgrade nicht mehr.
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

            # ═══ RATING & CONDITIONAL-FLAG POST-PROCESSING ═══
            final_tier = result.get("fly_status", result.get("flyability_tier", "gray")) or ""
            final_safety = result.get("safety_status", "")
            result["rating"] = _compute_rating_from_subratings(result, final_tier, final_safety)
            # is_conditional: bool normalisieren; bei not_safe immer False
            is_cond = bool(result.get("is_conditional", False))
            if final_safety == "not_safe":
                is_cond = False
            result["is_conditional"] = is_cond
            result["conditional_reason"] = (result.get("conditional_reason", "") or "") if is_cond else ""

            return result

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
                {"role": "system", "content": REGION_COMBINED_PROMPT},
                {"role": "user", "content": (
                    f"AKTUELLE LOKALZEIT: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ({_weekday_de(datetime.now())})\n\n"
                    f"{context}"
                )},
            ]

            # Retry-Logik: 1 Wiederholung bei Fehler
            last_err = None
            for attempt in range(2):
                try:
                    response = self.client.chat.completions.create(
                        model=self.model,
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

            # Foehn-Richtungs-Override
            krit_foehn = region.get("kritischer_foehn", "Beide")
            result = self._strip_irrelevant_foehn(result, krit_foehn)

            # ═══ FLYABILITY POST-PROCESSING ═══

            # Wenn not_safe: Flyability-Felder leeren
            if result.get("safety_status") == "not_safe":
                result["fly_status"] = ""
                result["flyability_tier"] = ""
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
            # Nur THERMAL-ROUGH-UNUSABLE (>50%) triggert gray; TORN/SHEAR-UNUSABLE
            # verschlechtern maximal violet→green, kein gray-Downgrade.
            tq = self._ctx_tq_cache.get(f"{rname}|{date_str}", {})
            if tq:
                tht = tq.get("thermal_hours_total", 0)
                tqd = tq.get("tq_danger_h", 0)
                rough_h = tq.get("rough_danger_h", 0)
                peak = tq.get("peak_climb_proxy", 0)
                prod_h = tq.get("productive_thermal_h", 0)
                # Downgrade green/violet → gray
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
                            f"Gute Bedingungen fuer Thermikfluege in der Region."
                        )
                        logger.warning(
                            f"Flyability-Override: {rname}/{date_str} gray→green "
                            f"(peak={peak:.1f}, ROUGH={rough_pct:.0f}%, productive_h={prod_h})"
                        )

            # ═══ RATING & CONDITIONAL-FLAG POST-PROCESSING ═══
            final_tier = result.get("fly_status", result.get("flyability_tier", "gray")) or ""
            final_safety = result.get("safety_status", "")
            result["rating"] = _compute_rating_from_subratings(result, final_tier, final_safety)
            is_cond = bool(result.get("is_conditional", False))
            if final_safety == "not_safe":
                is_cond = False
            result["is_conditional"] = is_cond
            result["conditional_reason"] = (result.get("conditional_reason", "") or "") if is_cond else ""

            return result

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
        if not self.client:
            return {"success": False, "error": "OPENAI_API_KEY nicht konfiguriert"}
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
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": WEEKLY_BRIEFING_PROMPT},
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
        if not self.client:
            yield {"event": "error", "data": {"message": "OPENAI_API_KEY nicht konfiguriert"}}
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
        if not self.client:
            yield {"event": "error", "data": {"message": "OPENAI_API_KEY nicht konfiguriert"}}
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
        """Laedt JSONL hoch, erstellt Batch, gibt batch_id zurueck."""
        import io
        file_obj = io.BytesIO(jsonl_content.encode("utf-8"))
        file_obj.name = "batch_input.jsonl"
        uploaded = self.client.files.create(file=file_obj, purpose="batch")
        logger.info(f"Batch-Datei hochgeladen: {uploaded.id} ({description})")

        batch = self.client.batches.create(
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
            batch = self.client.batches.retrieve(batch_id)
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

        content = self.client.files.content(output_file_id)
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

    def _apply_spot_safety_overrides(self, result: dict, name: str, date_str: str) -> dict:
        """Wendet deterministische Overrides auf Spot-Safety-Ergebnis an (identisch zu Parallel-Modus)."""
        result["spot"] = name
        result["date"] = date_str
        result["phase"] = "safety"

        # Gust-Cache-Injection
        gust_info = self._ctx_gust_cache.get(f"{name}|{date_str}", {})
        if gust_info:
            result["wind_ok_count"] = gust_info.get("wind_ok_count", 0)
            result["wind_wrong_count"] = gust_info.get("wind_wrong_count", 0)

        # Hard override: 0 WIND-OK = not_safe
        wind_ok = result.get("wind_ok_count", -1)
        if isinstance(wind_ok, int) and wind_ok == 0 and result.get("safety_status") != "not_safe":
            logger.warning(f"[BATCH] Safety-Override fuer {name}/{date_str}: 0 WIND-OK → not_safe")
            result["safety_status"] = "not_safe"
            result["safe_window"] = "keins"
            nogo = result.get("no_go_reasons", [])
            if not any("Windrichtung" in r for r in nogo):
                nogo.append("Keine Stunde mit korrekter Windrichtung")
            result["no_go_reasons"] = nogo

        # Boeen-Floor
        if gust_info:
            gwarn = gust_info.get("gust_warn_hours", 0) + gust_info.get("aloft_gust_warn_hours", 0)
            gdanger = gust_info.get("gust_danger_hours", 0) + gust_info.get("aloft_gust_danger_hours", 0)
            if (gwarn > 0 or gdanger > 0) and result.get("safety_status") == "safe":
                result["safety_status"] = "conditional"
                cn = result.get("caution_notes", []) or []
                cn.append("Starke Böen erkannt — Trend und Fenster prüfen.")
                result["caution_notes"] = cn

        # Overclaim-Ceiling
        if gust_info and result.get("safety_status") == "not_safe":
            if not gust_info.get("hard_warning_hours", 0) and gust_info.get("clean_hours_count", 0) >= 4:
                result["safety_status"] = "conditional"
                cn = result.get("caution_notes", []) or []
                cn.append(f"Automatische Korrektur: {gust_info['clean_hours_count']} saubere Flugstunden.")
                result["caution_notes"] = cn
                result["no_go_reasons"] = []

        # ─── Föhn-Richtungs-Override: Irrelevante Föhn-Warnungen entfernen ───
        spot = next((s for s in self.spots if s["name"] == name), None)
        if spot:
            krit_foehn = spot.get("kritischer_foehn", "Süd")
            result = self._strip_irrelevant_foehn(result, krit_foehn)

        # Tag-Sanitierung: Entfernt versehentlich verbliebene interne Tags
        _sanitize_llm_result(result)

        return result

    def _apply_region_safety_overrides(self, result: dict, rname: str, region: dict, date_str: str) -> dict:
        """Wendet deterministische Overrides auf Region-Safety-Ergebnis an."""
        result["region"] = rname
        result["region_id"] = region["id"]
        result["date"] = date_str
        result["phase"] = "safety"

        strong = result.get("wind_strong_count", 0)
        calm = result.get("wind_calm_count", 0)
        moderate = result.get("wind_moderate_count", 0)
        if (isinstance(strong, int) and isinstance(calm, int) and isinstance(moderate, int)
                and calm == 0 and strong > moderate
                and result.get("safety_status") in ("safe", "conditional")):
            logger.warning(f"[BATCH] Region Safety-Override fuer {rname}/{date_str}: "
                           f"{strong} WIND-STRONG, 0 WIND-CALM → not_safe")
            result["safety_status"] = "not_safe"
            result["safe_window"] = "keins"
            nogo = result.get("no_go_reasons", [])
            if not any(kw in (r or "").lower() for r in nogo for kw in ["starker wind", "wind-strong", "zu stark"]):
                nogo.append(f"Durchgehend starker Wind ({strong} von {strong + moderate} Stunden)")
            result["no_go_reasons"] = nogo

        # ─── Föhn-Richtungs-Override: Irrelevante Föhn-Warnungen entfernen ───
        krit_foehn = region.get("kritischer_foehn", "Beide")
        result = self._strip_irrelevant_foehn(result, krit_foehn)

        # Tag-Sanitierung: Entfernt versehentlich verbliebene interne Tags
        _sanitize_llm_result(result)

        return result

    def run_all_analyses_batch_stream(self):
        """Batch-Modus: Sammelt alle Requests, schickt als OpenAI-Batch, pollt bis fertig."""
        if not self.client:
            yield {"event": "error", "data": {"message": "OPENAI_API_KEY nicht konfiguriert"}}
            return

        all_regions = get_all_regions()
        regions_with_data = [r for r in all_regions if r["id"] in self.region_weather_data] if self.region_weather_data else []
        spots_to_analyze = [s for s in self.spots if s["name"] in self.weather_data] if self.weather_data else []
        forecast_dates = self._get_forecast_dates()
        _now = datetime.now()
        now_str = f"{_now.strftime('%Y-%m-%d %H:%M:%S')} ({_weekday_de(_now)})"

        total_items = (len(regions_with_data) + len(spots_to_analyze)) * len(forecast_dates) * 2
        yield {"event": "init", "data": {
            "mode": "batch",
            "regions_count": len(regions_with_data),
            "spots_count": len(spots_to_analyze),
            "days": len(forecast_dates),
            "total_calls": total_items,
        }}

        # ── Phase 1: Safety-Batch aufbauen ──
        yield {"event": "phase", "data": {"phase": "batch_safety_build", "total": 0}}
        safety_requests = []
        safety_meta = {}  # custom_id → (type, name/id, date_str, region_or_spot_dict)

        # Spot-Safety-Requests
        for spot in spots_to_analyze:
            name = spot["name"]
            for date_str in forecast_dates:
                ctx = self._build_single_spot_context(spot, date_str, mode="analysis")
                if not ctx:
                    continue
                cid = f"spot_safety|{name}|{date_str}"
                safety_requests.append({
                    "custom_id": cid,
                    "method": "POST",
                    "url": "/v1/chat/completions",
                    "body": {
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": SAFETY_CHECK_PROMPT},
                            {"role": "user", "content": f"AKTUELLE LOKALZEIT: {now_str}\n\n{ctx}"},
                        ],
                        "temperature": 0.2,
                        "max_tokens": 600,
                        "response_format": {"type": "json_object"},
                    },
                })
                safety_meta[cid] = ("spot", name, date_str, spot)

        # Region-Safety-Requests
        for region in regions_with_data:
            rid = region["id"]
            rname = region["region"]
            for date_str in forecast_dates:
                ctx = self._build_single_region_context(region, date_str)
                if not ctx:
                    continue
                cid = f"region_safety|{rid}|{date_str}"
                safety_requests.append({
                    "custom_id": cid,
                    "method": "POST",
                    "url": "/v1/chat/completions",
                    "body": {
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": REGION_SAFETY_CHECK_PROMPT},
                            {"role": "user", "content": f"AKTUELLE LOKALZEIT: {now_str}\n\n{ctx}"},
                        ],
                        "temperature": 0.2,
                        "max_tokens": 600,
                        "response_format": {"type": "json_object"},
                    },
                })
                safety_meta[cid] = ("region", rid, date_str, region)

        if not safety_requests:
            yield {"event": "error", "data": {"message": "Keine Safety-Requests aufgebaut"}}
            return

        # Batch einreichen
        yield {"event": "phase", "data": {"phase": "batch_safety_submit",
                                           "total": len(safety_requests)}}
        try:
            jsonl = self._build_batch_jsonl(safety_requests)
            safety_batch_id = self._submit_batch(jsonl, f"Safety-Check ({len(safety_requests)} Requests)")
        except Exception as e:
            logger.error(f"Batch-Submit fehlgeschlagen: {e}")
            yield {"event": "error", "data": {"message": f"Batch-Submit fehlgeschlagen: {e}"}}
            return

        # Polling
        yield {"event": "phase", "data": {"phase": "batch_safety_poll",
                                           "batch_id": safety_batch_id,
                                           "total": len(safety_requests)}}
        try:
            safety_raw = self._poll_batch(safety_batch_id)
        except Exception as e:
            logger.error(f"Batch-Poll fehlgeschlagen: {e}")
            yield {"event": "error", "data": {"message": f"Batch fehlgeschlagen: {e}"}}
            return

        # ── Safety-Ergebnisse parsen + Overrides anwenden ──
        spot_safety_results = {}
        region_safety_results = {}

        for cid, raw_result in safety_raw.items():
            meta = safety_meta.get(cid)
            if not meta:
                continue
            typ, name_or_id, date_str, obj = meta

            if raw_result.get("error"):
                if typ == "spot":
                    spot_safety_results.setdefault(name_or_id, {})[date_str] = {
                        "spot": name_or_id, "date": date_str,
                        "safety_status": "error", "phase": "safety",
                        "error": raw_result["error"],
                    }
                else:
                    region_safety_results.setdefault(name_or_id, {})[date_str] = {
                        "region": obj["region"], "region_id": name_or_id, "date": date_str,
                        "safety_status": "error", "phase": "safety",
                        "error": raw_result["error"],
                    }
                continue

            if typ == "spot":
                result = self._apply_spot_safety_overrides(raw_result, name_or_id, date_str)
                spot_safety_results.setdefault(name_or_id, {})[date_str] = result
            else:
                result = self._apply_region_safety_overrides(raw_result, obj["region"], obj, date_str)
                region_safety_results.setdefault(name_or_id, {})[date_str] = result

        yield {"event": "progress", "data": {
            "phase": "batch_safety_done",
            "completed": len(safety_raw),
            "total": len(safety_requests),
        }}

        # ── Phase 2: Flyability-Batch ──
        fly_requests = []
        fly_meta = {}

        # Spot-Flyability
        for spot in spots_to_analyze:
            name = spot["name"]
            for date_str in forecast_dates:
                safety = spot_safety_results.get(name, {}).get(date_str)
                if not safety or safety.get("safety_status") not in ("safe", "conditional"):
                    continue
                ctx = self._build_single_spot_context(spot, date_str, mode="analysis")
                if not ctx:
                    continue
                safe_window = safety.get("safe_window", "unbekannt")
                safety_status = safety.get("safety_status", "safe")
                caution_notes = safety.get("caution_notes", [])
                safety_context = (
                    f"\n═══ SICHERHEITSANALYSE (bereits geprüft) ═══\n"
                    f"Safety-Status: {safety_status}\n"
                    f"Sicheres Fenster: {safe_window}\n"
                )
                if caution_notes:
                    safety_context += f"Vorsichtshinweise: {', '.join(caution_notes)}\n"
                safety_context += (
                    "Analysiere NUR die Stunden innerhalb des sicheren Fensters.\n"
                    "Hinweis: 'conditional' (Orange) betrifft nur Gefahren/Vorsicht - "
                    "flyability_tier kann trotzdem 'violet' sein, wenn Thermik/XC aussergewoehnlich sind.\n"
                )
                cid = f"spot_fly|{name}|{date_str}"
                fly_requests.append({
                    "custom_id": cid,
                    "method": "POST",
                    "url": "/v1/chat/completions",
                    "body": {
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": FLYABILITY_PROMPT},
                            {"role": "user", "content": f"AKTUELLE LOKALZEIT: {now_str}\n\n{ctx}\n{safety_context}"},
                        ],
                        "temperature": 0.3,
                        "max_tokens": 500,
                        "response_format": {"type": "json_object"},
                    },
                })
                fly_meta[cid] = ("spot", name, date_str, spot, safety)

        # Region-Flyability
        regions_by_id = {r["id"]: r for r in regions_with_data}
        for rid, days in region_safety_results.items():
            region = regions_by_id.get(rid)
            if not region:
                continue
            rname = region["region"]
            for date_str, safety in days.items():
                if safety.get("safety_status") not in ("safe", "conditional"):
                    continue
                ctx = self._build_single_region_context(region, date_str)
                if not ctx:
                    continue
                safe_window = safety.get("safe_window", "unbekannt")
                safety_status = safety.get("safety_status", "safe")
                caution_notes = safety.get("caution_notes", [])
                safety_context = (
                    f"\n═══ SICHERHEITSANALYSE (bereits geprüft) ═══\n"
                    f"Safety-Status: {safety_status}\n"
                    f"Sicheres Fenster: {safe_window}\n"
                )
                if caution_notes:
                    safety_context += f"Vorsichtshinweise: {', '.join(caution_notes)}\n"
                safety_context += "Analysiere NUR die Stunden innerhalb des sicheren Fensters.\n"
                cid = f"region_fly|{rid}|{date_str}"
                fly_requests.append({
                    "custom_id": cid,
                    "method": "POST",
                    "url": "/v1/chat/completions",
                    "body": {
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": REGION_FLYABILITY_PROMPT},
                            {"role": "user", "content": f"AKTUELLE LOKALZEIT: {now_str}\n\n{ctx}\n{safety_context}"},
                        ],
                        "temperature": 0.3,
                        "max_tokens": 500,
                        "response_format": {"type": "json_object"},
                    },
                })
                fly_meta[cid] = ("region", rid, date_str, region, safety)

        spot_fly_results = {}
        region_fly_results = {}

        if fly_requests:
            yield {"event": "phase", "data": {"phase": "batch_fly_submit",
                                               "total": len(fly_requests)}}
            try:
                jsonl = self._build_batch_jsonl(fly_requests)
                fly_batch_id = self._submit_batch(jsonl, f"Flyability ({len(fly_requests)} Requests)")
            except Exception as e:
                logger.error(f"Flyability-Batch-Submit fehlgeschlagen: {e}")
                yield {"event": "error", "data": {"message": f"Flyability-Batch fehlgeschlagen: {e}"}}
                return

            yield {"event": "phase", "data": {"phase": "batch_fly_poll",
                                               "batch_id": fly_batch_id,
                                               "total": len(fly_requests)}}
            try:
                fly_raw = self._poll_batch(fly_batch_id)
            except Exception as e:
                logger.error(f"Flyability-Batch-Poll fehlgeschlagen: {e}")
                yield {"event": "error", "data": {"message": f"Flyability-Batch fehlgeschlagen: {e}"}}
                return

            for cid, raw_result in fly_raw.items():
                meta = fly_meta.get(cid)
                if not meta:
                    continue
                typ, name_or_id, date_str, obj, safety = meta

                if raw_result.get("error"):
                    err_entry = {
                        "date": date_str, "status": "error", "phase": "flyability",
                        "error": raw_result["error"],
                    }
                    if typ == "spot":
                        err_entry["spot"] = name_or_id
                        spot_fly_results.setdefault(name_or_id, {})[date_str] = err_entry
                    else:
                        err_entry["region"] = obj["region"]
                        err_entry["region_id"] = name_or_id
                        region_fly_results.setdefault(name_or_id, {})[date_str] = err_entry
                    continue

                tier = _normalize_flyability_tier(
                    raw_result.get("flyability_tier") or raw_result.get("fly_status") or raw_result.get("status")
                )
                raw_result["flyability_tier"] = tier
                raw_result["fly_status"] = tier
                raw_result["status"] = tier

                # Tag-Sanitierung
                _sanitize_llm_result(raw_result)

                # Deterministische Flyability-Overrides
                # Nur THERMAL-ROUGH-UNUSABLE (>50%) triggert gray; TORN/SHEAR-UNUSABLE
                # verschlechtern maximal violet→green, kein gray-Downgrade.
                cache_key = f"{name_or_id}|{date_str}" if typ == "spot" else f"{obj.get('region', name_or_id)}|{date_str}"
                tq = self._ctx_tq_cache.get(cache_key, {})
                if tq:
                    tht = tq.get("thermal_hours_total", 0)
                    tqd = tq.get("tq_danger_h", 0)
                    rough_h = tq.get("rough_danger_h", 0)
                    peak = tq.get("peak_climb_proxy", 0)
                    prod_h = tq.get("productive_thermal_h", 0)
                    # Downgrade green/violet → gray
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
                            old_tier = tier
                            raw_result["fly_status"] = "gray"
                            raw_result["flyability_tier"] = "gray"
                            raw_result["status"] = "gray"
                            tier = "gray"
                            logger.warning(
                                f"[BATCH] Flyability-Downgrade: {cache_key} {old_tier}→gray ({reason})"
                            )
                    # gray→green Upgrade: strengere Schwellen
                    if tier == "gray" and tht > 0:
                        rough_pct = (rough_h / max(1, tht)) * 100
                        if prod_h >= config.PRODUCTIVE_HOURS_FOR_GREEN and rough_pct < 50:
                            raw_result["fly_status"] = "green"
                            raw_result["flyability_tier"] = "green"
                            raw_result["status"] = "green"
                            # Textfelder korrigieren (LLM hat gray-konforme Werte)
                            raw_result["peak_climb_rate"] = round(peak, 1)
                            if peak >= 1.5:
                                raw_result["flight_type"] = "Thermikflug"
                                raw_result["flight_duration_estimate"] = f"2-3h Thermikflug (Peak {peak:.1f} m/s)"
                            else:
                                raw_result["flight_type"] = "Soaring+Thermik"
                                raw_result["flight_duration_estimate"] = f"1-2h Soaring/Thermik"
                            if prod_h >= 5:
                                raw_result["xc_potential"] = "moderate"
                            raw_result["recommendation"] = (
                                f"System-Korrektur: Die Daten zeigen {peak:.1f} m/s Peak-Thermik "
                                f"mit {prod_h}h produktiver Thermik (ROUGH-UNUSABLE nur {rough_pct:.0f}%). "
                                f"Gute Bedingungen fuer Thermikfluege."
                            )
                            logger.warning(
                                f"[BATCH] Flyability-Override: {cache_key} gray→green "
                                f"(peak={peak:.1f}, ROUGH={rough_pct:.0f}%, productive_h={prod_h})"
                            )

                # ═══ RATING: aus Sub-Ratings berechnen + Tier-Clamp ═══
                final_tier_batch = raw_result.get("fly_status", raw_result.get("flyability_tier", "gray")) or ""
                final_safety_batch = raw_result.get("safety_status", "")
                raw_result["rating"] = _compute_rating_from_subratings(
                    raw_result, final_tier_batch, final_safety_batch
                )

                if typ == "spot":
                    raw_result["spot"] = name_or_id
                    raw_result["date"] = date_str
                    raw_result["phase"] = "flyability"
                    spot_fly_results.setdefault(name_or_id, {})[date_str] = raw_result
                else:
                    raw_result["region"] = obj["region"]
                    raw_result["region_id"] = name_or_id
                    raw_result["date"] = date_str
                    raw_result["phase"] = "flyability"
                    region_fly_results.setdefault(name_or_id, {})[date_str] = raw_result

            yield {"event": "progress", "data": {
                "phase": "batch_fly_done",
                "completed": len(fly_raw),
                "total": len(fly_requests),
            }}

        # ── Merge: Spot-Ergebnisse (identisch zu run_spot_analyses_stream) ──
        spot_merged = {}
        for spot_name, days in spot_safety_results.items():
            spot_merged[spot_name] = {}
            for date_str, safety in days.items():
                entry = {"safety": safety}
                fly = spot_fly_results.get(spot_name, {}).get(date_str)
                safety_status = safety.get("safety_status", "error")
                if fly and not fly.get("error"):
                    tier = fly.get("flyability_tier", "")
                    if tier:
                        entry["flyability"] = fly
                        entry["fly_status"] = tier
                        entry["status"] = tier
                    else:
                        entry["fly_status"] = ""
                        entry["status"] = safety_status
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
                entry["best_window"] = safety.get("safe_window", "keins")
                entry["recommendation"] = ""
                if fly and not fly.get("error"):
                    entry["recommendation"] = fly.get("recommendation", "")
                    entry["best_window"] = fly.get("best_window", entry["best_window"])
                spot_merged[spot_name][date_str] = entry

        self.spot_analyses = spot_merged
        self.analyses_loaded_at = datetime.now()
        self._analyses_stale = False
        self._save_analyses_cache()
        if self.instantdb:
            threading.Thread(target=self._push_analyses_to_instantdb, daemon=True).start()

        # ── Merge: Region-Ergebnisse (identisch zu run_region_analyses_stream) ──
        region_merged = {}
        for rid, days in region_safety_results.items():
            region_merged[rid] = {}
            for date_str, safety in days.items():
                entry = {"safety": safety}
                fly = region_fly_results.get(rid, {}).get(date_str)
                safety_status = safety.get("safety_status", "error")
                if fly and not fly.get("error"):
                    tier = fly.get("flyability_tier", "")
                    if tier:
                        entry["flyability"] = fly
                        entry["fly_status"] = tier
                        entry["status"] = tier
                    else:
                        entry["fly_status"] = ""
                        entry["status"] = safety_status
                elif safety_status == "not_safe":
                    entry["fly_status"] = ""
                    entry["status"] = "not_safe"
                elif safety_status == "no_data":
                    entry["fly_status"] = ""
                    entry["status"] = "no_data"
                else:
                    entry["fly_status"] = ""
                    entry["status"] = safety_status
                entry["best_window"] = safety.get("safe_window", "keins")
                entry["recommendation"] = ""
                if fly and not fly.get("error"):
                    entry["recommendation"] = fly.get("recommendation", "")
                    entry["best_window"] = fly.get("best_window", entry["best_window"])
                entry["region_name"] = safety.get("region", rid)
                region_merged[rid][date_str] = entry

        self.region_analyses = region_merged
        self.region_analyses_loaded_at = datetime.now()
        self._save_region_analyses_cache()
        if self.instantdb:
            threading.Thread(target=self._push_region_analyses_to_instantdb, daemon=True).start()

        total_calls = len(safety_requests) + len(fly_requests)
        logger.info(f"Batch-Analysen abgeschlossen: {total_calls} Calls total")

        yield {"event": "done", "data": {
            "success": True,
            "mode": "batch",
            "total_calls": total_calls,
            "safety_count": len(safety_requests),
            "flyability_count": len(fly_requests),
        }}

    def run_all_analyses_stream(self):
        """Orchestrator: Regionen + Spots PARALLEL in einem gemeinsamen Pool.
        Einzelne Phase: kombinierte Safety+Flyability-Calls fuer alle Spots/Regionen.
        Dispatcht zum Batch-Modus wenn config.LLM_ANALYSIS_MODE == 'batch'.
        """
        if config.LLM_ANALYSIS_MODE == "batch":
            yield from self.run_all_analyses_batch_stream()
            return

        self._api_abort = threading.Event()
        self._api_abort_reason = 'Analyse abgebrochen'
        self._ctx_gust_cache.clear()
        self._ctx_tq_cache.clear()

        if not self.client:
            yield {"event": "error", "data": {"message": "OPENAI_API_KEY nicht konfiguriert"}}
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
            # SINGLE PHASE: Combined Safety+Flyability (Regionen + Spots)
            # ══════════════════════════════════════════════════════════════
            yield {"event": "phase", "data": {"phase": "all_safety", "total": total}}
            logger.info(f"[UNIFIED] Combined-Phase: {total} Calls "
                        f"({len(regions_with_data)} Regionen + {len(spots_to_analyze)} Spots x {n_days} Tage)")

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

            with ThreadPoolExecutor(max_workers=config.LLM_MAX_WORKERS) as executor:
                futures = {}

                # ── Spot submits ──
                for spot in spots_to_analyze:
                    name = spot["name"]
                    for date_str in forecast_dates:
                        if date_str in incomplete_spot_days.get(name, set()):
                            continue
                        future = executor.submit(self._build_and_analyze_spot, spot, date_str)
                        futures[future] = ("spot", name, date_str)

                # ── Region submits ──
                for region in regions_with_data:
                    rid = region["id"]
                    for date_str in forecast_dates:
                        future = executor.submit(self._build_and_analyze_region, region, date_str)
                        futures[future] = ("region", rid, date_str)

                # ── Ergebnisse einsammeln ──
                remaining = set(futures.keys())
                while remaining:
                    done, remaining = wait(remaining, timeout=self._HEARTBEAT_INTERVAL, return_when=FIRST_COMPLETED)
                    if not done:
                        yield self._HEARTBEAT_EVENT
                        continue
                    for future in done:
                        typ, name_or_id, date_str = futures[future]
                        try:
                            result = future.result()
                        except Exception as e:
                            logger.error(f"Combined-Future {typ}/{name_or_id}/{date_str}: {e}")
                            if typ == "spot":
                                result = {"spot": name_or_id, "date": date_str, "safety_status": "error", "error": str(e)}
                            else:
                                result = {"region_id": name_or_id, "region": name_or_id, "date": date_str, "safety_status": "error", "error": str(e)}
                        if typ == "spot":
                            spot_results.setdefault(name_or_id, {})[date_str] = result
                        else:
                            region_results.setdefault(name_or_id, {})[date_str] = result
                        completed += 1
                        yield {"event": "progress", "data": {
                            "phase": "all_safety", "type": typ,
                            "name": name_or_id, "date": date_str,
                            "completed": completed, "total": total,
                            "result": result.get("flyability_tier") or result.get("safety_status", "error"),
                        }}

            logger.info(f"[UNIFIED] Combined-Phase fertig: {completed} Calls")

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

