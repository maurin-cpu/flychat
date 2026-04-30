"""Deterministische Decision-Engine fuer Safety- und Flyability-Felder.

Ziel (Stage-Inversion): Strukturentscheidungen, die deterministisch ableitbar sind
(Status, Risiko-Levels, kanonische Warntexte, Flyability-Tier), trifft Python aus den
Cache-Daten. Das LLM produziert nur noch Prosa (summary, recommendation, wind_summary,
flight_type, …).

Vorteil gegenueber dem alten Override-Pattern:
- Single source of truth: Schwellen + Texte stehen hier, nicht im Skill-Prompt UND im
  Override gleichzeitig.
- LLM-Compliance-Bugs (z.B. Foehn-Vorsicht im Summary, aber foehn_risk=none) werden
  strukturell unmoeglich, weil das LLM die Strukturfelder nicht mehr setzt.
- Jede Decision ist isoliert testbar (siehe tests/test_decision_engine.py).

Konventionen:
- Jede Decision-Funktion mutiert das `result`-Dict in-place und liefert ein
  Tracking-Label (str) zurueck, falls sie gefeuert hat — sonst None.
- Aufrufer schreibt das Label in `result["_decisions_applied"]` und logt.
- Pre-Filter (engine/analyzers.py:_prefilter_not_safe) bleibt separat, weil er den
  LLM-Call ersetzt statt das Result zu modifizieren.
"""

import logging
from dataclasses import dataclass
from typing import Optional

import config

logger = logging.getLogger(__name__)


# Zentrale Foehn-Keyword-Liste.
# Wird genutzt von:
#   - apply_foehn_decision() zum Bereinigen von LLM-Eintraegen in caution_notes/no_go_reasons
#   - _strip_irrelevant_foehn() (weather_context.py) zur Summary-Saeuberung bei
#     irrelevanter Foehn-Richtung
#   - region-map.js / meteogram.js (UI-Backstop) — JS-Seite haelt eigene Liste,
#     muss bei Aenderungen hier mitgezogen werden (siehe SAFETY_OVERRIDES.md).
FOEHN_KEYWORDS = (
    "föhn", "foehn", "fohn",
    "δp", "delta-p", "delta_p",
    "druckgradient",
)


@dataclass
class FoehnDecision:
    """Deterministische Foehn-Bewertung fuer einen Spot/Region/Tag.

    Alle Felder werden aus dem Output von foehn_indicators.evaluate_foehn()
    abgeleitet, das bereits richtungs-aware (kritischer_foehn) arbeitet.
    """
    risk: str                         # "none" | "moderate" | "high"
    caution_note: Optional[str]       # Text fuer caution_notes (nur bei moderate)
    no_go_reason: Optional[str]       # Text fuer no_go_reasons (nur bei high)
    primary_no_go: Optional[str]      # "FOEHN" (nur bei high)
    forces_status: Optional[str]      # None | "conditional_min" | "not_safe"
    delta_p_hpa: Optional[float]      # fuer Logging/Tracking
    direction: Optional[str]          # "Süd" | "Nord" | None — fuer Logging/Tracking


def compute_foehn_decision(foehn_eval: dict) -> FoehnDecision:
    """Wandelt evaluate_foehn-Output in eine deterministische Decision um.

    Schwellen (definiert in foehn_indicators.py):
      - level == "none"     → risk none, kein Status-Eingriff
      - level == "caution"  (ΔP 4-7 hPa, relevante Richtung) → risk moderate, Status >= conditional
      - level == "danger"   (ΔP ≥ 8 hPa, relevante Richtung) → risk high, Status = not_safe

    Richtungs-Filter (kritisch != aktiv) wird bereits in _format_foehn_info()
    abgefangen — der Cache liefert dann level="none".
    """
    if not foehn_eval:
        return FoehnDecision("none", None, None, None, None, None, None)

    level = foehn_eval.get("level", "none")
    delta_p = foehn_eval.get("delta_p_hpa")
    direction = foehn_eval.get("direction") or "Süd"
    delta_p_str = f"ΔP {delta_p} hPa" if delta_p is not None else "ΔP unbekannt"

    if level == "danger":
        return FoehnDecision(
            risk="high",
            caution_note=None,
            no_go_reason=f"Foehn-Gefahr: {direction}foehn {delta_p_str} (Flugverbot-Empfehlung)",
            primary_no_go="FOEHN",
            forces_status="not_safe",
            delta_p_hpa=delta_p,
            direction=direction,
        )
    if level == "caution":
        return FoehnDecision(
            risk="moderate",
            caution_note=f"Foehn-Vorsicht: {direction}foehn {delta_p_str} — an exponierten Stellen vorsichtig.",
            no_go_reason=None,
            primary_no_go=None,
            forces_status="conditional_min",
            delta_p_hpa=delta_p,
            direction=direction,
        )
    return FoehnDecision("none", None, None, None, None, delta_p, direction)


def apply_foehn_decision(result: dict, decision: FoehnDecision) -> Optional[str]:
    """Wendet eine FoehnDecision autoritativ auf ein LLM-Result an.

    1. foehn_risk wird kompromisslos ueberschrieben (Python ist single source of truth).
    2. LLM-Eintraege mit Foehn-Keywords werden aus caution_notes/no_go_reasons gestrichen.
    3. Bei moderate/high wird der kanonische Text eingefuegt + safety_status angehoben.

    Liefert ein kurzes Tracking-Label zurueck (z.B. "FoehnCaution(4.5)") oder None,
    falls keine Aenderung am Status erfolgt ist. Wird in analyzers.py in
    result["_decisions_applied"] mitgeschrieben fuer Debugging/Transparenz.
    """
    # 1. foehn_risk autoritativ setzen
    result["foehn_risk"] = decision.risk

    # 2. LLM-Foehn-Eintraege aus den Listen-Feldern entfernen
    for key in ("caution_notes", "no_go_reasons"):
        items = result.get(key, []) or []
        result[key] = [
            i for i in items
            if not any(kw in (i or "").lower() for kw in FOEHN_KEYWORDS)
        ]

    # 3. Status anheben + kanonischen Text einfuegen
    if decision.forces_status == "not_safe":
        if result.get("safety_status") != "not_safe":
            result["safety_status"] = "not_safe"
            result["safe_window"] = "keins"
        if not result.get("primary_no_go"):
            result["primary_no_go"] = decision.primary_no_go
        if decision.no_go_reason:
            result["no_go_reasons"].append(decision.no_go_reason)
        return f"FoehnDanger({decision.delta_p_hpa})"

    if decision.forces_status == "conditional_min":
        if result.get("safety_status") == "safe":
            result["safety_status"] = "conditional"
        if decision.caution_note:
            result["caution_notes"].append(decision.caution_note)
        return f"FoehnCaution({decision.delta_p_hpa})"

    # decision.risk == "none": foehn_risk wurde geleert, evtl. Saeuberung der Listen
    # erfolgt — aber kein Status-Eingriff. Kein Tracking-Eintrag.
    return None


# ════════════════════════════════════════════════════════════════════
# SPOT — Safety-Decisions
# ════════════════════════════════════════════════════════════════════

def decide_wind_ok_zero(result: dict, gust_info: dict, label: str) -> Optional[str]:
    """Spot: Windrichtung ganztaegig ausserhalb des erlaubten Sektors → not_safe.

    Trigger: `wind_ok_count == 0`. Falls Status bereits not_safe ist, kein Eingriff.
    """
    wind_ok = gust_info.get("wind_ok_count", -1) if gust_info else -1
    if not (isinstance(wind_ok, int) and wind_ok == 0 and result.get("safety_status") != "not_safe"):
        return None

    logger.info(f"Decision WindOk0 fuer {label}: 0 WIND-OK Stunden → not_safe")
    result["safety_status"] = "not_safe"
    result["safe_window"] = "keins"
    nogo = result.get("no_go_reasons", []) or []
    if not any("Windrichtung" in (r or "") for r in nogo):
        nogo.append("Keine Stunde mit korrekter Windrichtung")
    result["no_go_reasons"] = nogo
    return "WindOk0"


def decide_aloft_not_safe(result: dict, gust_info: dict, label: str) -> Optional[str]:
    """Spot/Region: Hoehenwind-Gefahr im Flugbereich → not_safe.

    Trigger:
      - `aloft_danger_hours >= WIND_TREND_NOTSAFE_HOURS`, ODER
      - aloft-Pattern == DURCHGEHEND_DANGER, ODER
      - aloft-Pattern == EINGEKESSELT mit zu kleinem Calm-Gap.
    """
    if not gust_info:
        return None
    aloft_d = gust_info.get("aloft_danger_hours", 0)
    aloft_pattern = gust_info.get("aloft_pattern")
    nogo_thresh = config.WIND_TREND_NOTSAFE_HOURS

    triggers = aloft_d >= nogo_thresh
    if aloft_pattern:
        plabel = aloft_pattern.get("pattern_label", "")
        calm_gap = aloft_pattern.get("max_calm_gap", 0)
        if plabel == "DURCHGEHEND_DANGER":
            triggers = True
        elif plabel == "EINGEKESSELT" and calm_gap < nogo_thresh:
            triggers = True
        else:
            triggers = False

    if not (triggers and result.get("safety_status") != "not_safe"):
        return None

    pattern_str = aloft_pattern.get("pattern_label", "-") if aloft_pattern else "-"
    logger.info(
        f"Decision AloftNotSafe fuer {label}: ALOFT-DANGER {aloft_d}h "
        f"(Schwelle {nogo_thresh}h, Trend={pattern_str}) → not_safe"
    )
    result["safety_status"] = "not_safe"
    result["safe_window"] = "keins"
    if not result.get("primary_no_go"):
        result["primary_no_go"] = "ALOFT_DANGER"
    nogo = result.get("no_go_reasons", []) or []
    nogo.append(f"Kraeftiger Hoehenwind im Flugbereich: >{config.WIND_DANGER_KMH} km/h in {aloft_d}h")
    result["no_go_reasons"] = nogo
    return f"AloftNotSafe({aloft_d}h)"


def decide_aloft_conditional(result: dict, gust_info: dict, label: str) -> Optional[str]:
    """Spot: Hoehenwind-Vorsicht → conditional, falls LLM safe gab.

    Triggert nur, wenn `decide_aloft_not_safe` nicht schon gefeuert hat — daher der
    Status-Check auf `safe`.
    """
    if not gust_info:
        return None
    aloft_d = gust_info.get("aloft_danger_hours", 0)
    aloft_gd = gust_info.get("aloft_gust_danger_hours", 0)
    cond_thresh = config.WIND_TREND_CONDITIONAL_HOURS

    if not ((aloft_d >= cond_thresh or aloft_gd >= cond_thresh)
            and result.get("safety_status") == "safe"):
        return None

    kmh_thresh = config.WIND_DANGER_KMH
    gust_kmh_thresh = config.GUST_DANGER_KMH
    logger.info(
        f"Decision AloftConditional fuer {label}: ALOFT-DANGER {aloft_d}h / "
        f"ALOFT-GUST-DANGER {aloft_gd}h (Schwelle {cond_thresh}h) → conditional"
    )
    result["safety_status"] = "conditional"
    cn = result.get("caution_notes", []) or []
    bits = []
    if aloft_d >= cond_thresh:
        bits.append(f"Hoehenwind >{kmh_thresh} km/h im Flugbereich in {aloft_d}h")
    if aloft_gd >= cond_thresh:
        bits.append(f"Hoehenboeen >{gust_kmh_thresh} km/h im Flugbereich in {aloft_gd}h")
    if aloft_d >= cond_thresh and aloft_gd >= cond_thresh:
        head = "Gefahr in der Hoehe (Wind und Boeen)"
    elif aloft_gd >= cond_thresh:
        head = "Kraeftige Hoehenboeen"
    else:
        head = "Gefahr in der Hoehe"
    cn.append(head + ": " + ", ".join(bits) + " — auch bei ruhigem Bodenwind pruefen.")
    result["caution_notes"] = cn
    return f"AloftConditional({aloft_d}h)"


def decide_gust_floor(result: dict, gust_info: dict, label: str) -> Optional[str]:
    """Spot: zu viele GUST-WARN/DANGER-Stunden → conditional, falls LLM safe gab."""
    if not gust_info:
        return None
    gust_floor_hours = config.WIND_TREND_NOTSAFE_HOURS
    gwarn = gust_info.get("gust_warn_hours", 0) + gust_info.get("aloft_gust_warn_hours", 0)
    gdanger = gust_info.get("gust_danger_hours", 0) + gust_info.get("aloft_gust_danger_hours", 0)

    if not ((gwarn >= gust_floor_hours or gdanger >= gust_floor_hours)
            and result.get("safety_status") == "safe"):
        return None

    max_gust = int(gust_info.get("max_surface_gust", 0) or 0)
    logger.info(
        f"Decision GustFloor fuer {label}: GUST-WARN {gwarn}h / "
        f"GUST-DANGER {gdanger}h → conditional"
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
        cn.append("Starke Boeen erkannt: " + ", ".join(bits) + " — Trend und Fenster pruefen.")
    result["caution_notes"] = cn
    return "GustFloor"


def decide_overclaim_relax(result: dict, gust_info: dict, label: str) -> Optional[str]:
    """Spot: LLM hat not_safe gesagt, obwohl keine harten Warnungen + saubere Stunden
    vorliegen → relax auf conditional. Einziger Decision-Pfad, der DEMOTIERT (nicht
    eskaliert).
    """
    if not gust_info or result.get("safety_status") != "not_safe":
        return None
    has_hard_warnings = gust_info.get("hard_warning_hours", 0) > 0
    clean_cnt = gust_info.get("clean_hours_count", 0)
    if has_hard_warnings or clean_cnt < 4:
        return None

    logger.info(
        f"Decision OverclaimRelax fuer {label}: LLM gab 'not_safe' trotz {clean_cnt}h "
        f"saubere Stunden, 0 harte Warnungen → conditional"
    )
    result["safety_status"] = "conditional"
    cn = result.get("caution_notes", []) or []
    cn.append(
        f"Automatische Korrektur: Die Wetterdaten zeigen {clean_cnt} saubere "
        f"Flugstunden ohne harte Warnungen — bitte Meteogramm selbst pruefen."
    )
    result["caution_notes"] = cn
    result["no_go_reasons"] = []
    return f"OverclaimRelax({clean_cnt}h)"


def decide_is_conditional(result: dict, label: str) -> Optional[str]:
    """Setzt `is_conditional` deterministisch basierend auf `safety_status`.

    A2-Logik (RATING_CONCEPT v1.3, Vorab-Fix #2):
      - safety_status == "conditional"  → is_conditional = True (Engine-Override).
        Der LLM darf das Flag bei `safe` weiterhin selbst setzen (Soft-Warnungen
        wie tiefe Wolkenbasis oder Hoehen-Turbulenz, siehe `_flyability_tiers.md`
        Trigger 3+4) — die Engine ueberschreibt nur fuer conditional + not_safe.
      - safety_status == "not_safe"     → is_conditional = False (Sanity-Clamp).
        Korrigiert LLM-Fehler. `conditional_reason` wird ebenfalls geleert.
      - safety_status == "safe"         → kein Override. LLM behaelt Hand.

    MUSS nach allen safety-aendernden Decisions laufen (Aloft, Gust, Overclaim,
    Foehn), damit `safety_status` final ist.

    Returns: Tag-String wenn Engine `is_conditional` von False auf True
    angehoben hat (= meaningful state change), sonst None. Der Clamp-Pfad
    (not_safe → False) emittiert keinen Tag, da reines Cleanup.
    """
    status = result.get("safety_status")

    if status == "conditional":
        if not result.get("is_conditional"):
            result["is_conditional"] = True
            logger.info(
                f"Decision IsConditional fuer {label}: safety_status=conditional → "
                f"is_conditional=True (von LLM nicht gesetzt)"
            )
            return f"IsConditional({label})"
        return None  # bereits True — kein Tag, idempotent

    if status == "not_safe":
        if result.get("is_conditional"):
            logger.info(
                f"Decision IsConditional-Clamp fuer {label}: safety_status=not_safe → "
                f"is_conditional=False erzwungen (LLM hatte True gesetzt)"
            )
            result["is_conditional"] = False
            result["conditional_reason"] = ""
        return None  # Clamp emittiert keinen Tag — reines Cleanup

    # status == "safe": LLM-Soft-Warnungen (Trigger 3+4) bleiben unangetastet
    return None


# ════════════════════════════════════════════════════════════════════
# REGION — Safety-Decisions
# ════════════════════════════════════════════════════════════════════

def decide_wind_strong_majority(result: dict, label: str) -> Optional[str]:
    """Region: WIND-STRONG-Mehrheit ohne CALM → not_safe.

    Trigger: `calm == 0 AND strong > moderate`. Liest die Counts direkt aus
    `result` (vom LLM kommend, deterministisch nachfuellbar).
    """
    strong = result.get("wind_strong_count", 0)
    calm = result.get("wind_calm_count", 0)
    moderate = result.get("wind_moderate_count", 0)
    if not (isinstance(strong, int) and isinstance(calm, int) and isinstance(moderate, int)
            and calm == 0 and strong > moderate
            and result.get("safety_status") in ("safe", "conditional")):
        return None

    logger.info(
        f"Decision WindStrongMajority fuer {label}: {strong} WIND-STRONG, "
        f"0 WIND-CALM, {moderate} WIND-MODERATE → not_safe"
    )
    result["safety_status"] = "not_safe"
    result["safe_window"] = "keins"
    nogo = result.get("no_go_reasons", []) or []
    if not any(any(kw in (r or "").lower() for kw in ["starker wind", "wind-strong", "zu stark"]) for r in nogo):
        nogo.append(
            f"Durchgehend starker Wind ({strong} von {strong + moderate} Stunden), keine ruhige Phase"
        )
    result["no_go_reasons"] = nogo
    return f"WindStrongMajority({strong})"


# ════════════════════════════════════════════════════════════════════
# FLYABILITY — Tier-Decisions
# ════════════════════════════════════════════════════════════════════

def decide_flyability_low_reward(result: dict, tq: dict, label: str) -> Optional[str]:
    """Spot/Region: tier green/violet → gray, wenn Thermik objektiv schwach
    (= reine Erlebnis-/Reward-Frage, KEINE Sicherheits-Implikation).

    Sub-Trigger (RATING_CONCEPT v1.3 §9.4 Bruch 1, Aufgespalten von alter
    `decide_flyability_downgrade`):
      A) keine Thermik: peak < 0.3 oder thermal_hours_total == 0
      C) zu wenig produktiv: prod_h < PRODUCTIVE_HOURS_DOWNGRADE (NUR wenn rough_pct ≤ 50)

    Sub-Trigger B (rough_pct > 50, mech. Klapper) ist NICHT hier — siehe
    `decide_flyability_mech_danger`. Dadurch: low_reward fasst NIE
    `safety_status` an.
    """
    if not tq:
        return None
    tier = result.get("flyability_tier") or result.get("fly_status") or ""
    if tier not in ("green", "violet"):
        return None

    tht = tq.get("thermal_hours_total", 0)
    rough_h = tq.get("rough_danger_h", 0)
    peak = tq.get("peak_climb_proxy", 0)
    prod_h = tq.get("productive_thermal_h", 0)
    rough_pct = (rough_h / max(1, tht)) * 100 if tht else 0

    reason_tag = ""
    reason_text = ""
    if tht == 0 or peak < 0.3:
        reason_tag = "no_thermals"
        reason_text = f"keine Thermik (peak={peak:.1f}, hours={tht})"
    elif rough_pct <= 50 and prod_h < config.PRODUCTIVE_HOURS_DOWNGRADE:
        reason_tag = "low_productive"
        reason_text = f"Nur {prod_h}h produktive Thermik (min {config.PRODUCTIVE_HOURS_DOWNGRADE}h)"

    if not reason_tag:
        return None

    logger.info(f"Decision FlyabilityLowReward fuer {label}: {tier}→gray ({reason_text})")
    result["fly_status"] = "gray"
    result["flyability_tier"] = "gray"
    return f"FlyabilityLowReward({tier}→gray, {reason_tag})"


def decide_flyability_mech_danger(result: dict, tq: dict, label: str) -> Optional[str]:
    """Spot/Region: ROUGH-UNUSABLE > 50% der Thermikstunden → mechanische
    Klapper-Gefahr (= SAFETY-Thema, nicht reine Reward-Frage).

    Sub-Trigger B aus alter `decide_flyability_downgrade`. Cross-cutting Update:
      - Tier wird auf "gray" gesetzt (war Verhalten der alten Funktion)
      - safety_status wird von "safe" auf "conditional" eskaliert (NEU v1.3)
      - caution_note "mechanisches Klappern" wird angehaengt (NEU v1.3)

    Begruendung Cross-Cutting (RATING_CONCEPT v1.3 §3.5 Sub-Rating-Symmetrie):
    Mechanisches Klappern ist objektiv beides — die Thermik wird unbrauchbar
    (Reward) UND der Pilot bekommt Klapper (Safety). Ein einziger Decide schreibt
    beide Achsen, statt doppelte Logik in zwei separaten Funktionen.

    MUSS in der Safety-Pipe (vor `decide_is_conditional`) laufen, damit
    `is_conditional` automatisch via Stage-Inversion auf True gezogen wird.
    """
    if not tq:
        return None
    tht = tq.get("thermal_hours_total", 0)
    rough_h = tq.get("rough_danger_h", 0)
    if tht == 0:
        return None
    rough_pct = (rough_h / tht) * 100
    if rough_pct <= 50:
        return None

    logger.info(
        f"Decision FlyabilityMechDanger fuer {label}: "
        f"ROUGH-UNUSABLE={rough_pct:.0f}% ({rough_h}/{tht}h)"
    )

    # Tier-Downgrade (cross-cutting — schreibt fly_status obwohl in Safety-Pipe)
    tier = result.get("flyability_tier") or result.get("fly_status") or ""
    if tier in ("green", "violet"):
        result["fly_status"] = "gray"
        result["flyability_tier"] = "gray"

    # Safety-Eskalation: nur safe → conditional (kein Demote von not_safe)
    if result.get("safety_status") == "safe":
        result["safety_status"] = "conditional"

    # Caution-Note (immer, unabhaengig von vorherigem safety_status — der Pilot
    # soll auch bei not_safe oder bei bereits conditional die Begruendung sehen)
    cn = result.get("caution_notes", []) or []
    note = f"Mechanisches Klappern: ROUGH-UNUSABLE in {rough_pct:.0f}% der Thermikstunden"
    if not any("Klappern" in (n or "") for n in cn):
        cn.append(note)
    result["caution_notes"] = cn

    return f"FlyabilityMechDanger({rough_pct:.0f}%)"


def decide_flyability_upgrade(result: dict, tq: dict, label: str) -> Optional[str]:
    """Spot/Region: tier gray → green Upgrade, wenn Thermik trotz LLM-gray
    objektiv ausreichend ist.

    Trigger: productive_thermal_h ≥ PRODUCTIVE_HOURS_FOR_GREEN UND rough_pct < 50.
    Schreibt zusaetzlich peak_climb_rate, flight_type, recommendation neu.
    """
    if not tq:
        return None
    final_tier = result.get("fly_status") or result.get("flyability_tier") or ""
    if final_tier != "gray":
        return None

    tht = tq.get("thermal_hours_total", 0)
    if tht <= 0:
        return None
    rough_h = tq.get("rough_danger_h", 0)
    peak = tq.get("peak_climb_proxy", 0)
    prod_h = tq.get("productive_thermal_h", 0)
    rough_pct = (rough_h / max(1, tht)) * 100

    if not (prod_h >= config.PRODUCTIVE_HOURS_FOR_GREEN and rough_pct < 50):
        return None

    logger.info(
        f"Decision FlyabilityUpgrade fuer {label}: gray→green "
        f"(peak={peak:.1f}, ROUGH={rough_pct:.0f}%, productive_h={prod_h})"
    )
    result["fly_status"] = "green"
    result["flyability_tier"] = "green"
    result["peak_climb_rate"] = round(peak, 1)
    if peak >= 1.5:
        result["flight_type"] = "Thermikflug"
        result["flight_duration_estimate"] = f"2-3h Thermikflug (Peak {peak:.1f} m/s)"
    else:
        result["flight_type"] = "Soaring+Thermik"
        result["flight_duration_estimate"] = "1-2h Soaring/Thermik"
    if prod_h >= 5:
        result["xc_potential"] = "moderate"
    result["recommendation"] = (
        f"System-Korrektur: Die Daten zeigen {peak:.1f} m/s Peak-Thermik "
        f"mit {prod_h}h produktiver Thermik (ROUGH-UNUSABLE nur {rough_pct:.0f}%). "
        f"Gute Bedingungen fuer Thermikfluege."
    )
    return f"FlyabilityUpgrade(gray→green,peak={peak:.1f})"


def decide_flyability_region_gate(result: dict, region_result: dict, label: str) -> Optional[str]:
    """Spot: tier violet darf nur stehen, wenn die Region auch violet ist.

    Spot ohne starken Region-Konsens → violet→green.
    """
    if not region_result:
        return None
    current_tier = result.get("flyability_tier") or result.get("fly_status") or ""
    if current_tier != "violet":
        return None

    region_tier_raw = region_result.get("flyability_tier") or region_result.get("fly_status") or ""
    from engine._common import _normalize_flyability_tier
    region_tier = _normalize_flyability_tier(region_tier_raw)
    if not region_tier or region_tier == "violet":
        return None

    rname = region_result.get("region", "")
    logger.info(
        f"Decision FlyabilityRegionGate fuer {label}: violet→green "
        f"(Region '{rname}' tier={region_tier}, nicht violet)"
    )
    result["fly_status"] = "green"
    result["flyability_tier"] = "green"
    return f"FlyabilityRegionGate(violet→green)"
