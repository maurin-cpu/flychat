"""
Flychat Engine — Konstanten + Pure-Helpers.

Alles in dieser Datei hat KEINE Abhaengigkeit zur Engine-Klasse/State.
Nur Konstanten + pure Funktionen. Damit trivial unit-testbar.

Extrahiert aus chat_engine.py (Phase 2 des Monolith-Splits).
"""

import logging
import re
from datetime import datetime

logger = logging.getLogger(__name__)


# ============================================================================
# Chat-History
# ============================================================================
MAX_HISTORY_MESSAGES = 40  # Max messages per conversation before trimming


# ============================================================================
# Token-Budget-Management: verhindert 400-Fehler bei gpt-4o-mini (128k Limit)
# ============================================================================
_MODEL_TOKEN_LIMITS = {
    "gpt-4o-mini": 128_000,
    "gpt-4o": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4": 8_192,
    "gpt-3.5-turbo": 16_385,
}
_DEFAULT_TOKEN_LIMIT = 128_000
# Reserve fuer System-Prompt, Tools, User-Frage, Response-Tokens, History
_TOKEN_BUDGET_RESERVE = 20_000


# ============================================================================
# Memory-Cache Hard-Cap (siehe chat_engine._ctx_gust_cache / _ctx_tq_cache)
# ============================================================================
_CTX_CACHE_MAX_ENTRIES = 20_000


# ============================================================================
# Tool-Loop Limits
# ============================================================================
MAX_TOOL_ITERATIONS = 5


# ============================================================================
# Token-Schaetzung + Kontext-Truncation
# ============================================================================
def _estimate_tokens(text: str) -> int:
    """Grobe Token-Schaetzung: ~3.5 Zeichen pro Token fuer DE/Zahlen-Mix."""
    return int(len(text) / 3.5)


def _log_prompt_cache_usage(response, label: str = "llm"):
    """Loggt Prompt-Cache-Hit-Rate aus OpenAI-Response (fuer gpt-4o/mini automatisch,
    50% Rabatt auf gecachte Tokens). Silent-Fail bei aelteren SDKs ohne
    prompt_tokens_details.
    """
    try:
        usage = getattr(response, "usage", None)
        if not usage:
            return
        details = getattr(usage, "prompt_tokens_details", None)
        cached = getattr(details, "cached_tokens", 0) if details else 0
        prompt = getattr(usage, "prompt_tokens", 0) or 0
        if prompt == 0:
            return
        ratio = cached / prompt if prompt else 0.0
        logger.info(
            "[cache:%s] prompt=%d cached=%d hit_rate=%.0f%%",
            label, prompt, cached, ratio * 100,
        )
    except Exception:
        pass


def _truncate_weather_context(context: str, max_tokens: int) -> str:
    """Kuerzt den Roh-Wetterkontext progressiv bis er ins Token-Budget passt.

    Strategie: Forecast-Tage von hinten entfernen (Tag 5→4→3...).
    Fallback: Harter Zeichenlimit-Cut an Spot-Grenze.
    """
    if _estimate_tokens(context) <= max_tokens:
        return context

    # Alle vorkommenden Tage identifizieren (aus TAGESPROFIL-Zeilen)
    day_pattern = re.compile(r"═══ TAGESPROFIL (\d{4}-\d{2}-\d{2})")
    all_days = sorted(set(day_pattern.findall(context)))

    if len(all_days) <= 1:
        # Nur 1 Tag oder keine Tagesmarker → harter Cut
        max_chars = int(max_tokens * 3.5)
        truncated = context[:max_chars]
        # An letzter Spot-Grenze schneiden
        last_spot = truncated.rfind("═══ SPOT:")
        if last_spot > len(truncated) // 2:
            truncated = truncated[:last_spot]
        return truncated + "\n\n[KONTEXT GEKÜRZT — Token-Limit erreicht]"

    # Progressiv letzte Tage entfernen
    days_to_keep = len(all_days)
    result = context
    while days_to_keep > 1 and _estimate_tokens(result) > max_tokens:
        days_to_keep -= 1
        keep_set = set(all_days[:days_to_keep])
        # Pro Spot nur Zeilen der behaltenen Tage behalten
        result = _filter_context_by_days(context, keep_set, all_days)

    if _estimate_tokens(result) <= max_tokens:
        logger.warning(
            "Wetterkontext gekuerzt: %d→%d Tage (%d→%d geschaetzte Tokens)",
            len(all_days), days_to_keep,
            _estimate_tokens(context), _estimate_tokens(result),
        )
        return result + f"\n\n[KONTEXT GEKÜRZT: {days_to_keep}/{len(all_days)} Vorhersagetage — Token-Limit]"

    # Fallback: harter Cut
    max_chars = int(max_tokens * 3.5)
    truncated = result[:max_chars]
    last_spot = truncated.rfind("═══ SPOT:")
    if last_spot > len(truncated) // 2:
        truncated = truncated[:last_spot]
    logger.warning(
        "Wetterkontext hart gekuerzt: %d→%d Zeichen",
        len(context), len(truncated),
    )
    return truncated + "\n\n[KONTEXT GEKÜRZT — Token-Limit erreicht]"


def _filter_context_by_days(context: str, keep_days: set, all_days: list) -> str:
    """Filtert den Wetterkontext: behaelt nur Zeilen fuer die angegebenen Tage."""
    lines = context.split("\n")
    result_lines = []
    current_day = None
    drop_days = set(all_days) - keep_days

    for line in lines:
        # Spot-Header → immer behalten
        if line.startswith("═══ SPOT:"):
            current_day = None
            result_lines.append(line)
            continue

        # Tag wechseln wenn wir ein Datum in der Zeile erkennen
        for d in all_days:
            if d in line:
                current_day = d
                break

        if current_day and current_day in drop_days:
            continue

        result_lines.append(line)

    return "\n".join(result_lines)


# ============================================================================
# Datums-/Wochentag-Helfer
# ============================================================================
_WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


def _weekday_de(dt_or_str) -> str:
    """German weekday name from datetime or 'YYYY-MM-DD' string."""
    if isinstance(dt_or_str, str):
        dt_or_str = datetime.strptime(dt_or_str, "%Y-%m-%d")
    return _WOCHENTAGE[dt_or_str.weekday()]


# ============================================================================
# OpenAI-Error-Klassifikation
# ============================================================================
def _is_permanent_api_error(err: Exception) -> bool:
    """Prueft ob ein OpenAI-Fehler permanent ist (kein Retry sinnvoll).
    insufficient_quota, authentication_error, invalid_api_key → sofort abbrechen.
    rate_limit, timeout, connection → transient, Retry lohnt sich."""
    err_str = str(err).lower()
    return any(kw in err_str for kw in ("insufficient_quota", "invalid_api_key", "authentication"))


def _user_friendly_api_error(err: Exception) -> str:
    """Gibt eine benutzerfreundliche Fehlermeldung fuer permanente API-Fehler zurueck."""
    err_str = str(err).lower()
    if "insufficient_quota" in err_str:
        return "API-Budget aufgebraucht — bitte OpenAI-Guthaben aufladen"
    if "invalid_api_key" in err_str:
        return "Ungueltiger API-Key — bitte in den Einstellungen pruefen"
    if "authentication" in err_str:
        return "API-Authentifizierung fehlgeschlagen — bitte API-Key pruefen"
    return f"API-Fehler: {err}"


# ============================================================================
# FLYABILITY TIER + RATING (Briefing-Logik)
# ============================================================================
# Phase-2 Fliegbarkeit: gray / green / violet (Legacy: yellow→gray, orange→green)
_FLYABILITY_TIERS = frozenset({"gray", "green", "violet"})


def _normalize_flyability_tier(raw: str | None) -> str:
    if not raw:
        return ""
    r = str(raw).strip().lower()
    if r in _FLYABILITY_TIERS:
        return r
    legacy = {"yellow": "gray", "orange": "green"}
    return legacy.get(r, "")


# Wertebereiche sind VERBINDLICH und werden auf LLM-Output geclampt:
#   not_safe → 0.0   |  gray → 2.0-4.9  |  green → 5.0-8.4  |  violet → 8.5-10.0
_TIER_RATING_RANGES = {
    "gray":   (2.0, 4.9),
    "green":  (5.0, 8.4),
    "violet": (8.5, 10.0),
}


def _clamp_rating_to_tier(tier: str, rating, safety_status: str = "") -> float:
    """Clampt das LLM-Rating auf den Tier-Bereich. not_safe → 0.0."""
    if safety_status == "not_safe":
        return 0.0
    try:
        r = float(rating)
    except (TypeError, ValueError):
        r = 0.0
    rng = _TIER_RATING_RANGES.get(tier)
    if not rng:
        return 0.0
    lo, hi = rng
    if r < lo:
        r = lo
    elif r > hi:
        r = hi
    return round(r, 1)


def _compute_rating_from_subratings(result: dict, tier: str, safety_status: str = "") -> float:
    """Berechnet das Gesamtrating deterministisch aus 4 LLM-Sub-Ratings.

    G-Eval-Ansatz: Das LLM vergibt 4 Einzel-Ratings (thermal, window, wind, xc),
    die App berechnet daraus gewichtet das Gesamtrating. Das LLM ist gut im
    Beurteilen einzelner Aspekte, schlecht im Zusammenrechnen.

    Gewichte: thermal 35%, window 25%, wind 25%, xc 15%.
    Ergebnis wird anschliessend auf den Tier-Korridor geclampt.
    """
    def _clamp(v, lo, hi):
        try:
            v = float(v)
        except (TypeError, ValueError):
            v = 5.0
        return max(lo, min(hi, v))

    thermal = _clamp(result.get("thermal_rating", 5), 1, 10)
    window  = _clamp(result.get("window_rating", 5), 1, 10)
    wind    = _clamp(result.get("wind_rating", 5), 1, 10)
    xc      = _clamp(result.get("xc_rating", 5), 1, 10)
    raw = 0.35 * thermal + 0.25 * window + 0.25 * wind + 0.15 * xc
    return _clamp_rating_to_tier(tier, raw, safety_status)


# ============================================================================
# TAG-NATURAL MAPPING + SANITIZATION (LLM-Output-Cleanup)
# ============================================================================
# Mapping interner Tags auf kurze, natuerliche deutsche Begriffe.
# Laengere Varianten zuerst, damit z.B. THERMAL-TORN-DEGRADED vor TORN-DEGRADED matcht.
_TAG_NATURAL = [
    # Thermik-Qualitaet (lange Form zuerst)
    ("THERMAL-TORN-UNUSABLE",  "Thermik zerrissen"),
    ("THERMAL-TORN-DEGRADED",  "Thermik unruhig"),
    ("THERMAL-ROUGH-FRAGMENTED", "Thermik fragmentiert"),
    ("THERMAL-ROUGH-UNUSABLE", "extreme Turbulenz"),
    ("THERMAL-ROUGH-DEGRADED", "ruppige Thermik"),
    ("SHEAR-UNUSABLE",         "starke Scherung"),
    ("SHEAR-DEGRADED",         "Hoehenscherung"),
    # Kurzformen (LLM kuerzt manchmal ab)
    ("TORN-UNUSABLE",          "Thermik zerrissen"),
    ("TORN-DEGRADED",          "Thermik unruhig"),
    ("ROUGH-FRAG",             "Thermik fragmentiert"),
    ("ROUGH-UNUSABLE",         "extreme Turbulenz"),
    ("ROUGH-DEGRADED",         "ruppige Thermik"),
    ("SHEAR-DEG",              "Hoehenscherung"),
    # Wind / Boeen
    ("ALOFT-GUST-DANGER",      "gefaehrliche Hoehenboeen"),
    ("ALOFT-GUST-WARN",        "kraeftige Hoehenboeen"),
    ("ALOFT-DANGER",           "gefaehrlicher Hoehenwind"),
    ("ALOFT-WARN",             "kraeftiger Hoehenwind"),
    ("GUST-DANGER",            "gefaehrliche Boeen"),
    ("GUST-WARN",              "starke Boeen"),
    ("STRONG-WIND-WARN",       "zu starker Grundwind"),
    ("WIND-STRONG",            "starker Wind"),
    ("WIND-MODERATE",          "maessiger Wind"),
    ("WIND-WRONG",             "falsche Windrichtung"),
    ("WIND-CALM",              "ruhiger Wind"),
    ("WIND-OK",                "passende Windrichtung"),
    # Sonstiges
    ("RAIN-WARN",              "Regen"),
    ("CAPE-WARN",              "Ueberentwicklung"),
    ("OVERCAST-DANGER",        "dichte Wolkendecke"),
]

_TAG_NATURAL_MAP = {tag.upper(): natural for tag, natural in _TAG_NATURAL}

_TAG_SANITIZE_RE = re.compile(
    r'\[?(?:'
    + '|'.join(re.escape(tag) for tag, _ in _TAG_NATURAL)
    + r')\]?(?:\s+\d+h)?',
    re.IGNORECASE
)


def _sanitize_llm_text(text: str) -> str:
    """Ersetzt versehentlich verbliebene interne Tags durch kurze deutsche Begriffe."""
    if not text or not isinstance(text, str):
        return text

    def _replace_tag(m):
        raw = m.group(0)
        core = re.sub(r'[\[\]]', '', raw).strip()
        core = re.sub(r'\s+\d+h?$', '', core).strip()
        return _TAG_NATURAL_MAP.get(core.upper(), '')

    cleaned = _TAG_SANITIZE_RE.sub(_replace_tag, text)
    cleaned = re.sub(r'\s{2,}', ' ', cleaned)
    cleaned = re.sub(r',\s*,', ',', cleaned)
    cleaned = re.sub(r'^\s*,\s*', '', cleaned)
    cleaned = re.sub(r'\s*,\s*$', '', cleaned)
    return cleaned.strip()


def _sanitize_llm_result(result: dict) -> dict:
    """Sanitiert alle Text-Felder eines LLM-Ergebnisses von internen Tags."""
    for key in ("summary", "recommendation", "thermal_quality", "wind_summary", "wind_shear",
                "xc_details", "soaring_options", "safety_feedback"):
        if key in result and isinstance(result[key], str):
            result[key] = _sanitize_llm_text(result[key])
    for key in ("caution_notes", "no_go_reasons", "flyability_limits", "highlights"):
        if key in result and isinstance(result[key], list):
            result[key] = [_sanitize_llm_text(item) for item in result[key] if _sanitize_llm_text(item)]
    _derive_primary_labels(result)
    return result


# ============================================================================
# PRIMARY-LABEL SYSTEM
# ============================================================================
_LABEL_KEYS_NO_GO = {
    "FOEHN", "GEWITTER", "STURM", "ALOFT_DANGER", "STRONG_WIND",
    "REGEN", "SCHNEE", "OVERCAST", "SICHT", "VEREISUNG", "EINGEKESSELT"
}
_LABEL_KEYS_CONDITIONAL = {
    "STARKER_WIND", "WINDRICHTUNG", "TURBULENZ", "SHEAR_WIND",
    "GUST_SPREAD", "KURZES_FENSTER", "TREND_SCHLECHTER"
}
_LABEL_KEYS_REDUCER = {
    "VIEL_BEWOELKUNG", "SCHWACHE_THERMIK", "TIEFE_BASIS",
    "KURZES_FLUGFENSTER", "KALT", "FEUCHT", "INVERSION"
}
_LABEL_KEYS_BOOSTER = {
    "XC_BEDINGUNGEN", "STARKE_THERMIK", "HOHE_BASIS", "GUTE_EINSTRAHLUNG",
    "RUECKENWIND_XC", "STABILE_KALTFRONT", "LANGES_FENSTER", "KONVERGENZ"
}

# Ranking fuer Heuristik-Fallback (niedriger = wichtiger)
_NO_GO_RANK = [
    "FOEHN", "GEWITTER", "STURM", "ALOFT_DANGER", "STRONG_WIND",
    "REGEN", "SCHNEE", "OVERCAST", "SICHT", "VEREISUNG", "EINGEKESSELT"
]
_CONDITIONAL_RANK = [
    "STARKER_WIND", "WINDRICHTUNG", "TURBULENZ", "SHEAR_WIND",
    "GUST_SPREAD", "KURZES_FENSTER", "TREND_SCHLECHTER"
]

# Keyword → Key Mapping fuer Heuristik-Fallback (aus no_go_reasons/caution_notes)
_KEYWORD_TO_KEY_NO_GO = [
    (r'\bf[oö]hn', "FOEHN"),
    (r'\bgewitter|blitz|cape', "GEWITTER"),
    (r'\bsturm', "STURM"),
    (r'\bh[oö]henwind|h[oö]henboee|aloft', "ALOFT_DANGER"),
    (r'\b(starker? wind|wind.*stark|grundwind.*hoch|strong.?wind)', "STRONG_WIND"),
    (r'\bregen|niederschlag|rain', "REGEN"),
    (r'\bschnee|snow', "SCHNEE"),
    (r'\bovercast|wolkendecke|bew[oö]lkt.*tief|basis.*unter', "OVERCAST"),
    (r'\bsicht|nebel|fog', "SICHT"),
    (r'\bvereisung|icing', "VEREISUNG"),
    (r'\beingekesselt|kein fenster|fenster fehlt', "EINGEKESSELT"),
]
_KEYWORD_TO_KEY_CAUTION = [
    (r'\bwindrichtung|wind.*falsch|grenzwert.*richtung', "WINDRICHTUNG"),
    (r'\b(scherung|shear)', "SHEAR_WIND"),
    (r'\bturbulenz|ruppig|rau(h)?', "TURBULENZ"),
    (r'\bb[oö]ig|gust.?spread|gust.?exzess', "GUST_SPREAD"),
    (r'\bkurzes fenster|fenster kurz', "KURZES_FENSTER"),
    (r'\bverschlechter|trend.*schlecht', "TREND_SCHLECHTER"),
    (r'\bstarker? wind|wind.*stark', "STARKER_WIND"),
]


def _pick_key_from_list(items: list, keyword_map: list) -> str | None:
    """Heuristik: Erstes Listen-Element → Key per Keyword-Matching."""
    if not items:
        return None
    for item in items:
        if not isinstance(item, str):
            continue
        lower = item.lower()
        for pattern, key in keyword_map:
            if re.search(pattern, lower):
                return key
    return None


def _validate_key(raw, allowed_set: set) -> str | None:
    """Validiert einen primary_* Key gegen die erlaubte Menge."""
    if not raw or not isinstance(raw, str):
        return None
    k = raw.strip().upper()
    if not k or k in ("NULL", "NONE", "-"):
        return None
    return k if k in allowed_set else None


def _derive_primary_labels(result: dict) -> None:
    """Validiert und ergaenzt primary_no_go/caution/reducer/booster im LLM-Ergebnis.

    - Ungueltige Keys werden auf None gesetzt.
    - Fehlende primary_no_go/caution werden heuristisch aus den Listen abgeleitet.
    - primary_reducer/booster bleiben None wenn LLM keinen Key liefert (kein Fallback).
    """
    if not isinstance(result, dict):
        return

    safety = result.get("safety_status", "")

    p_no_go = _validate_key(result.get("primary_no_go"), _LABEL_KEYS_NO_GO)
    p_caution = _validate_key(result.get("primary_caution"), _LABEL_KEYS_CONDITIONAL)
    p_reducer = _validate_key(result.get("primary_reducer"), _LABEL_KEYS_REDUCER)
    p_booster = _validate_key(result.get("primary_booster"), _LABEL_KEYS_BOOSTER)

    # Fallback fuer NO-GO: aus no_go_reasons ableiten
    if safety == "not_safe" and not p_no_go:
        p_no_go = _pick_key_from_list(result.get("no_go_reasons", []), _KEYWORD_TO_KEY_NO_GO)
    # Bei not_safe die anderen Kategorien leeren (gem. UI-Regel: nur 1 Label)
    if safety == "not_safe":
        p_caution = None
        p_reducer = None
        p_booster = None

    # Fallback fuer CONDITIONAL: aus caution_notes ableiten
    if safety == "conditional" and not p_caution:
        p_caution = _pick_key_from_list(result.get("caution_notes", []), _KEYWORD_TO_KEY_CAUTION)

    # Bei safe sollen NO_GO und CONDITIONAL nicht gesetzt sein
    if safety == "safe":
        p_no_go = None
        p_caution = None

    result["primary_no_go"] = p_no_go
    result["primary_caution"] = p_caution
    result["primary_reducer"] = p_reducer
    result["primary_booster"] = p_booster


# ============================================================================
# COMPASS + WIND
# ============================================================================
COMPASS_POINTS = {
    "N": 0.0, "NNO": 22.5, "NO": 45.0, "ONO": 67.5,
    "O": 90.0, "OSO": 112.5, "SO": 135.0, "SSO": 157.5,
    "S": 180.0, "SSW": 202.5, "SW": 225.0, "WSW": 247.5,
    "W": 270.0, "WNW": 292.5, "NW": 315.0, "NNW": 337.5
}


def _compute_wind_trend(clean_hours: list[str], hourly_gusts: dict[str, float]) -> str:
    """Berechnet Windtendenz rund um das saubere Fenster.

    Returns z.B.:
        "WIND-TREND: VERSCHLECHTERUNG — Böen steigen nach Fenster von 37→57 km/h"
        "WIND-TREND: STABIL"
    """
    if not clean_hours or not hourly_gusts:
        return ""

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
    pre_gusts = pre_gusts[-3:]

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


def _detect_rain_sandwich(rain_hours: list, all_hours_sorted: list) -> dict:
    """Erkennt ob trockene Stunden zwischen Regenperioden eingekesselt sind.

    Returns dict mit:
        is_sandwiched: bool — trockenes Fenster zwischen zwei Regenperioden
        max_dry_gap: int — laengstes zusammenhaengendes trockenes Fenster (Stunden)
        dry_start: str — Beginn des laengsten trockenen Fensters
        dry_end: str — Ende des laengsten trockenen Fensters
    """
    if not rain_hours or not all_hours_sorted:
        return {"is_sandwiched": False, "max_dry_gap": len(all_hours_sorted or []),
                "dry_start": "", "dry_end": ""}

    rain_set = set(rain_hours)

    dry_stretches = []
    current_dry = []
    for h in all_hours_sorted:
        if h not in rain_set:
            current_dry.append(h)
        else:
            if current_dry:
                dry_stretches.append(current_dry[:])
            current_dry = []
    if current_dry:
        dry_stretches.append(current_dry)

    if not dry_stretches:
        return {"is_sandwiched": False, "max_dry_gap": 0,
                "dry_start": "", "dry_end": ""}

    longest = max(dry_stretches, key=len)
    dry_start = longest[0]
    dry_end = longest[-1]

    rain_before = any(h < dry_start for h in rain_hours)
    rain_after = any(h > dry_end for h in rain_hours)

    return {
        "is_sandwiched": rain_before and rain_after,
        "max_dry_gap": len(longest),
        "dry_start": dry_start,
        "dry_end": dry_end,
    }


def _interpolate_wind_at_altitude(pl_data: dict, target_alt: float, pressure_levels: list) -> tuple:
    """Interpoliert Windgeschwindigkeit und -richtung auf einer Zielhoehe aus Drucklevel-Daten.

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

    if target_alt <= levels[0][0]:
        return levels[0][1], levels[0][2]

    if target_alt >= levels[-1][0]:
        return levels[-1][1], levels[-1][2]

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
