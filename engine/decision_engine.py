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
        wie tiefe Wolkenbasis oder Hoehen-Turbulenz, siehe `_safety_experience.md`
        Trigger 1+2) — die Engine ueberschreibt nur fuer conditional + not_safe.
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


def compute_safety_band(result: dict) -> str:
    """Leitet `safety_band` (green/amber/red) aus `safety_score` + Decision-
    Engine-Hard-Overrides ab.

    RATING_CONCEPT v1.3 §3.1 — Hybrid: Strukturelle Sicherheits-Decisions
    (Foehn, Aloft, etc.) haben Vorrang vor dem LLM-Score. Wenn ein
    Foehndurchbruch erkannt wird, ist der Tag rot, egal was das LLM zu Wind
    und Boeen sagt. Erst wenn keine Hard-Override greift, entscheidet der
    Score (gebildet via Weakest-Link aus 5 Sub-Ratings, siehe
    `_compute_safety_rating`).

    Reihenfolge:
      1. Hard-Override → red:
         - safety_status == "not_safe"
         - "FoehnDanger" in _decisions_applied
         - "AloftNotSafe" in _decisions_applied
      2. Hard-Override → amber:
         - safety_status == "conditional"
         - "FoehnCaution" in _decisions_applied
         - foehn_risk >= 4.0 (numerisch, falls vorhanden)
         - GustFloor / AloftConditional / WindStrongMajority in _decisions_applied
      3. Score-basiert:
         - safety_score < 40 → amber (LLM-Sub-Ratings selbst sehen Probleme)
         - sonst → green
    """
    # _decisions_applied tolerieren als List ODER String (Cache-Quirk)
    decisions = result.get("_decisions_applied", [])
    if isinstance(decisions, str):
        decisions_str = decisions
        decisions_list = [decisions]
    else:
        decisions_list = list(decisions or [])
        decisions_str = " ".join(str(d) for d in decisions_list)

    status = result.get("safety_status", "")

    # Hard red
    if status == "not_safe":
        return "red"
    if "FoehnDanger" in decisions_str:
        return "red"
    if any(str(d).startswith("AloftNotSafe") for d in decisions_list):
        return "red"

    # Hard amber
    if status == "conditional":
        return "amber"
    if "FoehnCaution" in decisions_str:
        return "amber"
    try:
        foehn_risk_num = float(result.get("foehn_risk", 0) or 0)
    except (TypeError, ValueError):
        foehn_risk_num = 0
    if foehn_risk_num >= 4.0:
        return "amber"
    if any(str(d).startswith(("GustFloor", "AloftConditional", "WindStrongMajority"))
           for d in decisions_list):
        return "amber"

    # Score-basierter Fallback
    # safety_score fehlt (None) + status=safe → green: fehlende Sub-Ratings ≠ schlechter Score.
    # Nur explizit gesetzter Score < 40 rechtfertigt amber.
    score_raw = result.get("safety_score")
    if score_raw is None:
        return "green" if status == "safe" else "amber"
    try:
        score = int(score_raw or 0)
    except (TypeError, ValueError):
        score = 0
    if score < 40:
        return "amber"
    return "green"


def compute_comfort_index(tq: dict) -> int:
    """Berechnet `comfort_index` (0-100) aus `rough_pct`.

    RATING_CONCEPT v1.3 §3.3: "Texture"-Wert im Spot-Panel — wie glatt (100)
    oder klapprig (0) sich der Tag anfuehlt. Beeinflusst **nicht** das
    Experience-Rating — wird nur als zusaetzliche Pill angezeigt.

    Formel:
      rough_pct = rough_danger_h / thermal_hours_total * 100
      comfort_index = 100 - rough_pct

    Hinweis: Optional koennte hier zusaetzlich ein gust_factor-Penalty
    angewendet werden (RATING_CONCEPT §3.3 Skizze). Der Wert ist aber heute
    nicht im _ctx_tq_cache verfuegbar, daher wird primaer rough_pct verwendet.
    Erweiterbar wenn avg_gust_factor pro Tag gepflegt wird.

    Returns 100 wenn keine TQ-Daten — optimistischer Fallback (gibt keine
    falschen "klapprig"-Hinweise bei Datenluecken).
    """
    if not tq:
        return 100
    tht = tq.get("thermal_hours_total", 0) or 0
    rough_h = tq.get("rough_danger_h", 0) or 0
    if tht <= 0:
        return 100
    rough_pct = (rough_h / tht) * 100
    base = 100 - rough_pct
    return max(0, min(100, round(base)))


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
# FLYABILITY — Safety-Decision (Mech-Danger)
# ════════════════════════════════════════════════════════════════════
# Hinweis (RATING_CONCEPT v1.5): Flyability-Tier wird vom LLM direkt gesetzt.
# Es gibt keine `decide_flyability_low_reward`, `decide_flyability_upgrade`
# oder `decide_flyability_region_gate` mehr. Reine Reward-Korrekturen wurden
# entfernt — der LLM-Output ist autoritativ. Inkonsistenzen (z.B. peak 0.1 m/s
# bei rating 7) werden bewusst sichtbar, statt sie via Code zu kaschieren.
# `decide_flyability_mech_danger` bleibt, weil mech. Klappern eine SAFETY-
# Eskalation ist (safe→conditional), nicht reine Tier-Korrektur.


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


# ════════════════════════════════════════════════════════════════════
# TAG-SYSTEM v4 — Start-Fenster + Topic-Tags
# Doku: docs/TAGS.md (Sync-Pflicht!)
# ════════════════════════════════════════════════════════════════════

def build_start_window(gust_info: dict) -> list:
    """Liefert Stundenliste fuer das WINDOW-Visual.

    Das Startfenster nutzt ausschliesslich Boden-Wind/Boeen + Windrichtung —
    keine Hoehenwerte, kein Foehn, kein Regen. Schwellen aus config.py.

    Die per-hour Klassifikation passiert in weather_context.py waehrend der
    Stunden-Iteration (dort liegt die Rohdaten-Hand). Diese Funktion liest
    die vorberechnete Liste aus dem gust_info-Cache und gibt sie zurueck.
    """
    if not gust_info:
        return []
    raw = gust_info.get("start_window_hours") or []
    out = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        hour = entry.get("hour")
        state = entry.get("state")
        if not isinstance(hour, int) or state not in ("startbar", "sportlich", "blockiert", "neutral"):
            continue
        out.append({"hour": hour, "state": state})
    return out


def _fmt_hour_range(hours: list) -> str:
    """Komprimiert eine Liste von hour-ints/strings zu '13-16 h' oder leer."""
    if not hours:
        return ""
    nums = []
    for h in hours:
        if isinstance(h, str) and h.endswith(":00"):
            try:
                nums.append(int(h.split(":")[0]))
            except ValueError:
                continue
        elif isinstance(h, int):
            nums.append(h)
    if not nums:
        return ""
    nums = sorted(set(nums))
    start, end = nums[0], nums[-1]
    if start == end:
        return f"{start:02d} h"
    return f"{start:02d}-{end + 1:02d} h"


def _make_tag(topic: str, severity: str, label: str, value: str = "", time: str = "") -> dict:
    return {"topic": topic, "severity": severity, "label": label, "value": value, "time": time}


# Topics, die das LLM produzieren darf (Hybrid v5 — siehe docs/TAGS.md).
# Backend-Topics (WIND_GROUND, WIND_ALOFT, RAIN, THUNDERSTORM, FOEHN, TURBULENCE)
# sind NICHT in dieser Whitelist — das LLM darf sie nicht ueberschreiben.
LLM_TAG_TOPIC_WHITELIST = frozenset({
    "CLOUDS", "THERMAL", "XC",
    "INVERSION", "BASE", "WINDOW", "SUNSHINE", "CONVERGENCE",
})

# STOP und WARN sind Backend-Hoheit — Sicherheits-Schweregrade sind nicht
# verhandelbar. LLM darf nur REDUCER (Fliegbarkeits-Minderer) und GOOD
# (Pluspunkte) setzen. Siehe docs/TAGS.md "Severity-Hoheit".
LLM_TAG_SEVERITY_WHITELIST = frozenset({"reducer", "good"})

# Pro-Topic erlaubte Severities, die das LLM setzen darf. Ergaenzt
# LLM_TAG_SEVERITY_WHITELIST (welches die globale Obergrenze ist) — z.B. INVERSION
# darf nur REDUCER, CONVERGENCE nur GOOD, XC nur GOOD. Siehe Quellen-Matrix in
# docs/TAGS.md.
LLM_TAG_TOPIC_SEVERITY = {
    "CLOUDS":      frozenset({"reducer", "good"}),
    "THERMAL":     frozenset({"reducer", "good"}),
    "XC":          frozenset({"good"}),
    "INVERSION":   frozenset({"reducer"}),
    "BASE":        frozenset({"reducer", "good"}),
    "WINDOW":      frozenset({"reducer", "good"}),
    "SUNSHINE":    frozenset({"reducer", "good"}),
    "CONVERGENCE": frozenset({"good"}),
}


def validate_llm_tags(llm_tags, result: dict, *, log_prefix: str = "") -> list:
    """Filtert vom LLM produzierte Tags gegen Whitelist + Daten-Plausibilitaet.

    Verworfen wird:
    - Topic nicht in LLM_TAG_TOPIC_WHITELIST (Halluzination)
    - Severity nicht in LLM_TAG_SEVERITY_WHITELIST (STOP/WARN nur Backend)
    - Severity nicht in pro-Topic-Whitelist (z.B. CONVERGENCE darf nur good,
      INVERSION nur reducer — siehe LLM_TAG_TOPIC_SEVERITY)
    - Falsches Schema (kein dict, kein topic/severity)
    - Duplikat-Topic (erstes Vorkommen gewinnt; finaler Merge dedupliziert nochmal)
    - Daten-Sanity:
        * THERMAL good erfordert peak_climb_rate >= 1.0 m/s
        * CLOUDS good erfordert avg_low_mid <= 60 %
        * BASE good erfordert min_cloud_base_active_h - peak_height_m > 800 m
        * BASE reducer erfordert min_cloud_base_active_h - elevation_m < 600 m

    Returns: bereinigte Liste (gleicher Schema wie build_topic_tags).
    """
    if not isinstance(llm_tags, list):
        if llm_tags is not None:
            logger.warning(
                "%svalidate_llm_tags: llm_tags ist kein Array (%s) — verworfen",
                log_prefix, type(llm_tags).__name__,
            )
        return []

    peak_climb = result.get("peak_climb_rate")
    avg_low_mid = result.get("avg_low_mid")
    if avg_low_mid is None:
        low = result.get("avg_cloud_low")
        mid = result.get("avg_cloud_mid")
        if isinstance(low, (int, float)) and isinstance(mid, (int, float)):
            avg_low_mid = (low + mid) / 2

    # BASE-Sanity-Daten (optional — wenn nicht vorhanden, wird Sanity uebersprungen)
    cloud_base_min = result.get("min_cloud_base_active_h")
    elevation_m = result.get("elevation_m")
    peak_height_m = result.get("peak_height_m")

    cleaned: list[dict] = []
    seen_topics: set[str] = set()

    for raw in llm_tags:
        if not isinstance(raw, dict):
            logger.info("%svalidate_llm_tags: drop — kein dict: %r", log_prefix, raw)
            continue
        topic = raw.get("topic")
        severity = raw.get("severity")
        label = raw.get("label") or topic or ""
        value = raw.get("value") or ""
        time = raw.get("time") or ""

        if not isinstance(topic, str) or topic not in LLM_TAG_TOPIC_WHITELIST:
            logger.info(
                "%svalidate_llm_tags: drop — topic nicht in Whitelist: %r",
                log_prefix, topic,
            )
            continue
        if not isinstance(severity, str) or severity not in LLM_TAG_SEVERITY_WHITELIST:
            logger.info(
                "%svalidate_llm_tags: drop %s — severity ungueltig (STOP/WARN nur Backend): %r",
                log_prefix, topic, severity,
            )
            continue
        # Pro-Topic-Severity-Matrix (z.B. INVERSION darf nur reducer, nicht good)
        allowed_for_topic = LLM_TAG_TOPIC_SEVERITY.get(topic)
        if allowed_for_topic is not None and severity not in allowed_for_topic:
            logger.info(
                "%svalidate_llm_tags: drop %s %s — fuer dieses Topic nicht erlaubt (erlaubt: %s)",
                log_prefix, topic, severity, sorted(allowed_for_topic),
            )
            continue
        if topic in seen_topics:
            logger.info(
                "%svalidate_llm_tags: drop %s — Duplikat (first wins)",
                log_prefix, topic,
            )
            continue

        # Daten-Sanity
        if topic == "THERMAL" and severity == "good":
            if not isinstance(peak_climb, (int, float)) or peak_climb < 1.0:
                logger.info(
                    "%svalidate_llm_tags: drop THERMAL good — peak_climb_rate=%s zu niedrig",
                    log_prefix, peak_climb,
                )
                continue
        if topic == "CLOUDS" and severity == "good":
            if isinstance(avg_low_mid, (int, float)) and avg_low_mid > 60:
                logger.info(
                    "%svalidate_llm_tags: drop CLOUDS good — avg_low_mid=%s zu hoch",
                    log_prefix, avg_low_mid,
                )
                continue
        if topic == "BASE":
            if not isinstance(cloud_base_min, (int, float)):
                logger.info(
                    "%svalidate_llm_tags: drop BASE %s — cloud_base nicht verfuegbar",
                    log_prefix, severity,
                )
                continue
            if severity == "reducer" and isinstance(elevation_m, (int, float)):
                if cloud_base_min - elevation_m >= 600:
                    logger.info(
                        "%svalidate_llm_tags: drop BASE reducer — Basis %sm liegt %sm ueber Startplatz (kein Reducer)",
                        log_prefix, cloud_base_min, cloud_base_min - elevation_m,
                    )
                    continue
            if severity == "good" and isinstance(peak_height_m, (int, float)):
                if cloud_base_min - peak_height_m <= 800:
                    logger.info(
                        "%svalidate_llm_tags: drop BASE good — Basis %sm nur %sm ueber Gipfel (kein Booster)",
                        log_prefix, cloud_base_min, cloud_base_min - peak_height_m,
                    )
                    continue

        cleaned.append(_make_tag(topic, severity, str(label), str(value), str(time)))
        seen_topics.add(topic)

    return cleaned


def merge_topic_tags(backend_tags: list, llm_tags: list) -> list:
    """Mergt Backend- und LLM-Tags zu kanonischer Liste.

    - Backend-Tags haben Vorrang bei Topic-Konflikt (sollte nicht passieren wenn
      Whitelist sauber ist, aber als Belt-and-Suspenders).
    - Pro Topic genau ein Tag mit hoechster Severity.
    - Reihenfolge nach TAG_TOPIC_ORDER (siehe docs/TAGS.md).
    """
    # Severity-Rang: stop > warn > reducer > good (kleinere Zahl = wichtiger).
    # "info" als Legacy-Severity wird auf "reducer" gemappt (siehe docs/TAGS.md
    # Migrations-Eintrag 2026-05-05).
    sev_rank = {"stop": 0, "warn": 1, "reducer": 2, "info": 2, "good": 3}
    by_topic: dict[str, dict] = {}
    for t in (backend_tags or []) + (llm_tags or []):
        if not isinstance(t, dict):
            continue
        topic = t.get("topic")
        if not isinstance(topic, str):
            continue
        prev = by_topic.get(topic)
        if prev is None or sev_rank.get(t.get("severity"), 9) < sev_rank.get(prev.get("severity"), 9):
            by_topic[topic] = t
    order = [
        "WIND_GROUND", "WIND_ALOFT", "FOEHN", "RAIN", "THUNDERSTORM",
        "CLOUDS", "BASE", "THERMAL", "XC", "INVERSION", "WINDOW",
        "SUNSHINE", "CONVERGENCE", "TURBULENCE",
    ]
    return [by_topic[t] for t in order if t in by_topic] + [
        by_topic[t] for t in by_topic if t not in order
    ]


def build_topic_tags(result: dict, gust_info: dict, tq: dict) -> list:
    """Baut die kanonische Tag-Liste fuer einen Spot/Tag.

    Ein Topic = ein Tag = die hoechste zutreffende Severity.
    Frontend liest aus result["tags"] und rendert deterministisch.
    Schwellen kommen aus config.py — keine Hardcodes hier.

    Severity-Reihenfolge: stop > warn > good > info.
    Pro Topic wird genau eine Severity vergeben (oder gar kein Tag).

    Vollstaendige Spec: docs/TAGS.md (Sync-Pflicht!).
    """
    tags: list[dict] = []
    gi = gust_info or {}
    tq = tq or {}
    notsafe_h = config.WIND_TREND_NOTSAFE_HOURS

    # ── WIND_GROUND (Bodenwind/Boeen) ────────────────────────────────
    gust_warn = int(gi.get("gust_warn_hours", 0) or 0)
    gust_danger = int(gi.get("gust_danger_hours", 0) or 0)
    wind_warn = int(gi.get("wind_warn_hours", 0) or 0)
    wind_danger = int(gi.get("wind_danger_hours", 0) or 0)
    wind_ok = int(gi.get("wind_ok_count", 0) or 0)
    wind_wrong = int(gi.get("wind_wrong_count", 0) or 0)
    max_gust = int(gi.get("max_surface_gust", 0) or 0)

    if gust_danger >= notsafe_h or wind_danger >= notsafe_h:
        # STOP: Boeen oder Wind im DANGER-Bereich ueber Schwellen-Stunden
        if gust_danger >= notsafe_h:
            label = "Boeen"
            value = f"{max_gust} km/h" if max_gust else f">{config.GUST_DANGER_KMH} km/h"
            time = f"{gust_danger}h"
        else:
            label = "Wind"
            value = f">{config.WIND_DANGER_KMH} km/h"
            time = f"{wind_danger}h"
        tags.append(_make_tag("WIND_GROUND", "stop", label, value, time))
    elif wind_ok == 0 and wind_wrong > 0:
        # STOP: Richtung ganztaegig falsch
        tags.append(_make_tag("WIND_GROUND", "stop", "Wind", "Richtung falsch", "ganztags"))
    elif gust_warn >= 1 or wind_warn >= 1 or gust_danger >= 1 or wind_danger >= 1:
        # WARN: Boeen/Wind im sportlichen Bereich (oder kurze DANGER-Spitze unter Stunden-Schwelle)
        if gust_warn + gust_danger >= wind_warn + wind_danger:
            label = "Boeen"
            value = f"{max_gust} km/h" if max_gust else f">{config.GUST_WARN_KMH} km/h"
            time = f"{gust_warn + gust_danger}h"
        else:
            label = "Wind"
            value = f">{config.WIND_WARN_KMH} km/h"
            time = f"{wind_warn + wind_danger}h"
        tags.append(_make_tag("WIND_GROUND", "warn", label, value, time))
    elif wind_ok > wind_wrong and gust_warn == 0 and wind_warn == 0:
        # GOOD: Richtung passt + ruhig
        tags.append(_make_tag("WIND_GROUND", "good", "Wind", "Richtung OK, ruhig", ""))

    # ── WIND_ALOFT (Hoehenwind/-boeen) ───────────────────────────────
    aloft_w = int(gi.get("aloft_warn_hours", 0) or 0)
    aloft_d = int(gi.get("aloft_danger_hours", 0) or 0)
    aloft_gw = int(gi.get("aloft_gust_warn_hours", 0) or 0)
    aloft_gd = int(gi.get("aloft_gust_danger_hours", 0) or 0)

    if aloft_d >= notsafe_h or aloft_gd >= notsafe_h:
        h = max(aloft_d, aloft_gd)
        tags.append(_make_tag(
            "WIND_ALOFT", "stop", "Hoehenwind",
            f">{config.WIND_DANGER_KMH} km/h", f"{h}h"
        ))
    elif aloft_w >= 1 or aloft_gw >= 1 or aloft_d >= 1 or aloft_gd >= 1:
        h = max(aloft_w + aloft_d, aloft_gw + aloft_gd)
        tags.append(_make_tag(
            "WIND_ALOFT", "warn", "Hoehenwind",
            f">{config.WIND_WARN_KMH} km/h", f"{h}h"
        ))
    elif aloft_w == 0 and aloft_d == 0 and aloft_gw == 0 and aloft_gd == 0:
        tags.append(_make_tag("WIND_ALOFT", "good", "Hoehenwind", "ruhig", ""))

    # ── FOEHN ────────────────────────────────────────────────────────
    foehn = (result.get("foehn_risk") or "").lower()
    if foehn == "high":
        tags.append(_make_tag("FOEHN", "stop", "Foehn", "stark", ""))
    elif foehn == "moderate":
        tags.append(_make_tag("FOEHN", "warn", "Foehn", "moderat", ""))
    # low/none → kein Tag

    # ── RAIN ─────────────────────────────────────────────────────────
    rain_h = int(gi.get("rain_hours", 0) or 0)
    if rain_h >= 1:
        rain_list = gi.get("rain_hour_list") or []
        # "warn" wenn Regen NUR nach dem Flugfenster; "stop" wenn Regen im Fenster
        rain_in_win = int(gi.get("rain_in_window_h", rain_h) or rain_h)
        rain_sev = "stop" if rain_in_win > 0 else "warn"
        tags.append(_make_tag(
            "RAIN", rain_sev, "Regen", "Niederschlag", _fmt_hour_range(rain_list)
        ))

    # ── THUNDERSTORM ─────────────────────────────────────────────────
    thunder_h = int(gi.get("thunderstorm_hours", 0) or 0)
    if thunder_h >= 1:
        thunder_in_win = int(gi.get("thunderstorm_in_window_h", thunder_h) or thunder_h)
        thunder_sev = "stop" if thunder_in_win > 0 else "warn"
        tags.append(_make_tag(
            "THUNDERSTORM", thunder_sev, "Gewitter", "Modell-Gewitter", f"{thunder_h}h"
        ))

    # ── CLOUDS — STOP (Safety) + REDUCER (Basis nahe Platz) ──────────
    # STOP: dichte Decke auf/unter Startplatz (Sicht/IFR, "in den Wolken").
    # REDUCER: tiefe Decke knapp ÜBER Platz (Basis nahe Startplatz) →
    # eingeschränkte Arbeitshöhe, fliegbar/grün, KEIN Status-Downgrade.
    # CLOUDS-REDUCER (Bedeckung daempft Thermik) und GOOD liefert zusätzlich
    # das LLM via llm_tags — Merge nimmt pro Topic die höchste Severity.
    cloud_at_or_below_h = int(gi.get("cloud_at_or_below_takeoff_h", 0) or 0)
    cloud_near_h = int(gi.get("cloud_near_takeoff_h", 0) or 0)
    cloud_base_min = gi.get("min_cloud_base_active_h")
    elev = gi.get("elevation_m")
    if cloud_at_or_below_h >= 2:
        time = "ganztags" if cloud_at_or_below_h >= 6 else f"{cloud_at_or_below_h}h"
        if isinstance(cloud_base_min, (int, float)) and isinstance(elev, (int, float)):
            value = f"Basis {int(cloud_base_min)}m ≤ Startplatz {int(elev)}m"
        else:
            value = "Startplatz in Wolken"
        tags.append(_make_tag("CLOUDS", "stop", "Bewoelkung", value, time))
    elif cloud_near_h >= 1:
        time = f"{cloud_near_h}h"
        if isinstance(cloud_base_min, (int, float)) and isinstance(elev, (int, float)):
            value = f"Basis {int(cloud_base_min)}m nahe Startplatz {int(elev)}m"
        else:
            value = "Wolkenrand am Startplatz"
        tags.append(_make_tag("CLOUDS", "reducer", "Bewoelkung", value, time))
    # CLOUDS good (+ Bedeckungs-reducer) kommen zusätzlich vom LLM (llm_tags).

    # ── THERMAL / XC / BASE / INVERSION / WINDOW / SUNSHINE / CONVERGENCE ─
    # Hybrid v5 (siehe docs/TAGS.md): Diese Topics liefert das LLM via
    # `result["llm_tags"]` und werden im Merge-Schritt eingespeist.

    # ── TURBULENCE (REDUCER — Fliegbarkeits-Minderer, kein Sicherheitsthema) ─
    rough_h = int(tq.get("rough_danger_h", 0) or 0)
    if rough_h >= 1:
        time = "ganztags" if rough_h >= 6 else f"{rough_h}h"
        tags.append(_make_tag(
            "TURBULENCE", "reducer", "Klappern", "mech. ruppig", time
        ))

    return tags


def build_region_topic_tags(result: dict, gust_info: dict) -> list:
    """Region-Variante (kein TURBULENCE/Boeen — Regionen aggregieren ohne Spot-Boeen).

    Nutzt die gleichen Topic-IDs/Severities wie build_topic_tags, laesst aber
    Spot-spezifische Topics weg (TURBULENCE braucht tq, Boeen braucht
    Spot-Bias-Korrektur). WIND_GROUND wird hier auf reine Wind-Geschwindigkeit
    reduziert.
    """
    tags: list[dict] = []
    gi = gust_info or {}
    notsafe_h = config.WIND_TREND_NOTSAFE_HOURS

    wind_warn = int(gi.get("wind_warn_hours", 0) or 0)
    wind_danger = int(gi.get("wind_danger_hours", 0) or 0)
    wind_ok = int(gi.get("wind_ok_count", 0) or 0)
    wind_wrong = int(gi.get("wind_wrong_count", 0) or 0)

    if wind_danger >= notsafe_h:
        tags.append(_make_tag(
            "WIND_GROUND", "stop", "Wind", f">{config.WIND_DANGER_KMH} km/h", f"{wind_danger}h"
        ))
    elif wind_ok == 0 and wind_wrong > 0:
        tags.append(_make_tag("WIND_GROUND", "stop", "Wind", "Richtung falsch", "ganztags"))
    elif wind_warn >= 1 or wind_danger >= 1:
        tags.append(_make_tag(
            "WIND_GROUND", "warn", "Wind", f">{config.WIND_WARN_KMH} km/h", f"{wind_warn + wind_danger}h"
        ))
    elif wind_ok > wind_wrong:
        tags.append(_make_tag("WIND_GROUND", "good", "Wind", "Richtung OK, ruhig", ""))

    # WIND_ALOFT identisch
    aloft_w = int(gi.get("aloft_warn_hours", 0) or 0)
    aloft_d = int(gi.get("aloft_danger_hours", 0) or 0)
    if aloft_d >= notsafe_h:
        tags.append(_make_tag(
            "WIND_ALOFT", "stop", "Hoehenwind", f">{config.WIND_DANGER_KMH} km/h", f"{aloft_d}h"
        ))
    elif aloft_w >= 1 or aloft_d >= 1:
        tags.append(_make_tag(
            "WIND_ALOFT", "warn", "Hoehenwind", f">{config.WIND_WARN_KMH} km/h", f"{aloft_w + aloft_d}h"
        ))

    # FOEHN
    foehn = (result.get("foehn_risk") or "").lower()
    if foehn == "high":
        tags.append(_make_tag("FOEHN", "stop", "Foehn", "stark", ""))
    elif foehn == "moderate":
        tags.append(_make_tag("FOEHN", "warn", "Foehn", "moderat", ""))

    # RAIN — Coverage-Klassen (widespread/scattered/isolated) aus 16-RP Aggregation.
    # Topic-ID bleibt "RAIN" (Frontend-Kompatibilitaet), Differenzierung im value-Feld
    # und Severity:
    #   widespread im Fenster → stop ("flaechig")
    #   scattered  im Fenster → stop ("verstreut")
    #   isolated   im Fenster → warn ("vereinzelt")  ← Pilot kann eine Zelle umfliegen
    #   alles nur ausserhalb Fenster → warn (wie bisher)
    # Fallback wenn 16-RP-Daten fehlen: alte Binary-Logik.
    rain_h = int(gi.get("rain_hours", 0) or 0)
    if rain_h >= 1:
        rain_list = gi.get("rain_hour_list") or []
        rain_in_win = int(gi.get("rain_in_window_h", rain_h) or rain_h)
        widespread_h = int(gi.get("rain_widespread_h", 0) or 0)
        scattered_h = int(gi.get("rain_scattered_h", 0) or 0)
        isolated_h = int(gi.get("rain_isolated_h", 0) or 0)

        # Dominante Klasse (Tag-Level): hoechste auftretende Klasse gewinnt.
        # Klasse wird als zusaetzliches Feld im Tag mitgegeben — Frontend rendert
        # daraus ein eigenes SVG-Icon (siehe static/js/briefing.js, rain-glyph).
        if widespread_h > 0:
            klasse_label = "flaechig"
            klasse = "widespread"
        elif scattered_h > 0:
            klasse_label = "verstreut"
            klasse = "scattered"
        elif isolated_h > 0:
            klasse_label = "vereinzelt"
            klasse = "isolated"
        else:
            # Fallback: 16-RP-Daten nicht vorhanden (alte Cache-Eintraege).
            klasse_label = None
            klasse = None

        # Severity-Bestimmung
        if rain_in_win == 0:
            rain_sev = "warn"
        elif klasse == "isolated":
            rain_sev = "warn"
        else:
            # widespread, scattered, oder unbekannt (Legacy-Fallback) → stop
            rain_sev = "stop"

        value_str = klasse_label if klasse_label else "Niederschlag"
        rain_tag = _make_tag(
            "RAIN", rain_sev, "Regen", value_str, _fmt_hour_range(rain_list)
        )
        # Klassen-Marker fuer Frontend-Icon. Optional — wenn None, rendert das
        # Frontend einen Default-Tropfen.
        if klasse:
            rain_tag["rain_class"] = klasse
        tags.append(rain_tag)

    # THUNDERSTORM
    thunder_h = int(gi.get("thunderstorm_hours", 0) or 0)
    if thunder_h >= 1:
        thunder_in_win = int(gi.get("thunderstorm_in_window_h", thunder_h) or thunder_h)
        thunder_sev = "stop" if thunder_in_win > 0 else "warn"
        tags.append(_make_tag(
            "THUNDERSTORM", thunder_sev, "Gewitter", "Modell-Gewitter", f"{thunder_h}h"
        ))

    # ── CLOUDS — STOP (Safety) + REDUCER (Basis nahe Ref), Region-Pfad ─
    # Region nutzt elev_ref als Referenz fuer "Startplatz" — gleiche Logik
    # wie Spot-Pfad. CLOUDS-Bedeckungs-reducer/GOOD zusätzlich via llm_tags.
    cloud_at_or_below_h = int(gi.get("cloud_at_or_below_takeoff_h", 0) or 0)
    cloud_near_h = int(gi.get("cloud_near_takeoff_h", 0) or 0)
    cloud_base_min = gi.get("min_cloud_base_active_h")
    elev = gi.get("elevation_m")
    if cloud_at_or_below_h >= 2:
        time = "ganztags" if cloud_at_or_below_h >= 6 else f"{cloud_at_or_below_h}h"
        if isinstance(cloud_base_min, (int, float)) and isinstance(elev, (int, float)):
            value = f"Basis {int(cloud_base_min)}m ≤ Region-Ref {int(elev)}m"
        else:
            value = "Region in Wolken"
        tags.append(_make_tag("CLOUDS", "stop", "Bewoelkung", value, time))
    elif cloud_near_h >= 1:
        time = f"{cloud_near_h}h"
        if isinstance(cloud_base_min, (int, float)) and isinstance(elev, (int, float)):
            value = f"Basis {int(cloud_base_min)}m nahe Region-Ref {int(elev)}m"
        else:
            value = "Wolkenrand auf Region-Hoehe"
        tags.append(_make_tag("CLOUDS", "reducer", "Bewoelkung", value, time))

    # XC / BASE / THERMAL etc. liefert das LLM via result["llm_tags"] (Hybrid v5).

    return tags
