"""
Chat-Engine für Flychat.
Zentrale Klasse die Pilotenfragen beantwortet.
Globaler Wetterdaten-Kontext + Per-User Conversation History.
"""

import os
import json
import logging
import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed, wait, FIRST_COMPLETED
from datetime import datetime, timedelta
from pathlib import Path
from openai import OpenAI

import config
from spots import load_spots
from fetch_weather import fetch_all_spots, load_cached_weather, load_cached_weather_timestamp, is_cache_fresh, is_cache_complete, validate_spot_data
from foehn_indicators import (
    fetch_foehn_data,
    evaluate_foehn,
    build_foehn_llm_context,
)
from thermik_calculator import calculate_thermal_profile, calculate_dewpoint, get_terrain_zone
from gust_calculator import (
    estimate_altitude_gusts,
    collect_gust_anchors,
    estimate_altitude_gusts_multi_anchor,
    interpolate_gust_from_anchors,
    apply_oi_gust_correction,
    aggregate_spot_excess,
)
from prompts import (
    SYSTEM_PROMPT,
    CAPABILITIES_GUIDE,
    FOEHN_CHAT_KNOWLEDGE,
    SAFETY_CHECK_PROMPT,
    FLYABILITY_PROMPT,
    REGION_SAFETY_CHECK_PROMPT,
    REGION_FLYABILITY_PROMPT,
    SPOT_COMBINED_PROMPT,
    REGION_COMBINED_PROMPT,
    WEEKLY_NEWSPAPER_PROMPT,
    format_foehn_llm_regional_guide,
)
from source_area import get_all_regions, find_region_for_point
from station_observations import StationManager
import routing

logger = logging.getLogger(__name__)

MAX_HISTORY_MESSAGES = 40  # Max messages per conversation before trimming

# Token-Budget-Management: verhindert 400-Fehler bei gpt-4o-mini (128k Limit)
_MODEL_TOKEN_LIMITS = {
    "gpt-4o-mini": 128_000,
    "gpt-4o": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4": 8_192,
    "gpt-3.5-turbo": 16_385,
}
_DEFAULT_TOKEN_LIMIT = 128_000
# Reserve für System-Prompt, Tools, User-Frage, Response-Tokens, History
_TOKEN_BUDGET_RESERVE = 20_000


def _estimate_tokens(text: str) -> int:
    """Grobe Token-Schätzung: ~3.5 Zeichen pro Token für DE/Zahlen-Mix."""
    return int(len(text) / 3.5)


def _truncate_weather_context(context: str, max_tokens: int) -> str:
    """Kürzt den Roh-Wetterkontext progressiv bis er ins Token-Budget passt.

    Strategie: Forecast-Tage von hinten entfernen (Tag 5→4→3...).
    Fallback: Harter Zeichenlimit-Cut an Spot-Grenze.
    """
    if _estimate_tokens(context) <= max_tokens:
        return context

    # Alle vorkommenden Tage identifizieren (aus TAGESPROFIL-Zeilen)
    import re as _re
    day_pattern = _re.compile(r"═══ TAGESPROFIL (\d{4}-\d{2}-\d{2})")
    all_days = sorted(set(day_pattern.findall(context)))

    if len(all_days) <= 1:
        # Nur 1 Tag oder keine Tagesmarker → harter Cut
        max_chars = int(max_tokens * 3.5)
        truncated = context[:max_chars]
        # An letzter Spot-Grenze schneiden
        last_spot = truncated.rfind("═══ SPOT:")
        if last_spot > len(truncated) // 2:
            truncated = truncated[:last_spot]
        return truncated + f"\n\n[KONTEXT GEKÜRZT — Token-Limit erreicht]"

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
            "Wetterkontext gekürzt: %d→%d Tage (%d→%d geschätzte Tokens)",
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
        "Wetterkontext hart gekürzt: %d→%d Zeichen",
        len(context), len(truncated),
    )
    return truncated + f"\n\n[KONTEXT GEKÜRZT — Token-Limit erreicht]"


def _filter_context_by_days(context: str, keep_days: set, all_days: list) -> str:
    """Filtert den Wetterkontext: behält nur Zeilen für die angegebenen Tage."""
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


_WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


def _weekday_de(dt_or_str) -> str:
    """German weekday name from datetime or 'YYYY-MM-DD' string."""
    if isinstance(dt_or_str, str):
        dt_or_str = datetime.strptime(dt_or_str, "%Y-%m-%d")
    return _WOCHENTAGE[dt_or_str.weekday()]


def _is_permanent_api_error(err: Exception) -> bool:
    """Prüft ob ein OpenAI-Fehler permanent ist (kein Retry sinnvoll).
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
# OPENAI TOOL SCHEMAS (Phase 1: Standort-basierte Spot-Filterung)
# ============================================================================
# Drei Tools für den Chat-Use-Case:
#   1. geocode_location — Adresse / Stadt → Koordinaten
#   2. find_spots_within_travel_time — Isochrone + Spot-Filter (Hauptfunktion)
#   3. clear_map_overlays — Karten-Overlays zurücksetzen
#
# Nach Erhalt eines Tool-Calls dispatcht answer_stream() an _dispatch_tool(),
# yieldet sofort map_action-Events ans Frontend und ruft danach erneut OpenAI auf.

TOOLS: list = [
    {
        "type": "function",
        "function": {
            "name": "geocode_location",
            "description": (
                "Geokodiert eine vom Piloten genannte Adresse oder Stadt zu Koordinaten. "
                "Verwende dieses Tool wenn der Pilot einen Standort nennt (z.B. 'Zürich', "
                "'Bern', 'Bahnhofstrasse 5 Luzern') und wir wissen müssen wo er ist, "
                "BEVOR wir mit find_spots_within_travel_time die erreichbaren Spots suchen."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Adresse, Stadt oder Ortsname (z.B. 'Zürich' oder 'Bern Bahnhof')."
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_spots_within_travel_time",
            "description": (
                "Findet alle Fluggebiete, die der Pilot von einem Startpunkt aus innerhalb "
                "einer maximalen Reisezeit erreichen kann. Berechnet eine Isochrone (erreichbare "
                "Zone) per Valhalla, zeichnet sie automatisch auf der Karte ein und filtert die "
                "Spots, die darin liegen. Liefert die Liste der erreichbaren Spots zurück, "
                "inklusive Voranalyse-Daten (Sicherheit, Fliegbarkeit) für deine Empfehlung."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "lat": {
                        "type": "number",
                        "description": "Latitude des Startpunkts (WGS84). Aus geocode_location.",
                    },
                    "lon": {
                        "type": "number",
                        "description": "Longitude des Startpunkts (WGS84). Aus geocode_location.",
                    },
                    "minutes": {
                        "type": "integer",
                        "description": "Maximale Reisezeit in Minuten (z.B. 60, 90, 120).",
                        "minimum": 1,
                        "maximum": 360,
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["auto", "bicycle", "pedestrian"],
                        "description": (
                            "Verkehrsmittel: 'auto' für Auto, 'bicycle' für Velo, "
                            "'pedestrian' für zu Fuss. Default 'auto'."
                        ),
                    },
                    "label": {
                        "type": "string",
                        "description": (
                            "Optional: Anzeigename des Startpunkts für die Karte (z.B. 'Zürich'). "
                            "Wird neben dem Pin angezeigt."
                        ),
                    },
                },
                "required": ["lat", "lon", "minutes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clear_map_overlays",
            "description": (
                "Entfernt alle dynamischen Overlays von der Karte (Isochrone, "
                "User-Standort-Pin, Spot-Highlights). Verwende wenn der Pilot "
                "'Karte zurücksetzen', 'alles löschen', 'reset karte' o.ä. sagt."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
]


# Hard limit gegen Endlosschleifen im Tool-Call-Loop (Risk-Mitigation aus Plan)
MAX_TOOL_ITERATIONS = 5

# Phase-2 Fliegbarkeit: gray / green / violet (Legacy: yellow/orange/green → gray/green/violet)
_FLYABILITY_TIERS = frozenset({"gray", "green", "violet"})


def _normalize_flyability_tier(raw: str | None) -> str:
    if not raw:
        return ""
    r = str(raw).strip().lower()
    if r in _FLYABILITY_TIERS:
        return r
    legacy = {"yellow": "gray", "orange": "green"}
    return legacy.get(r, "")


# ══════════════════════════════════════════════════════════════════
# Tier-Gated Rating (Newspaper)
# Wertebereiche sind VERBINDLICH und werden auf LLM-Output geclampt:
#   not_safe → 0.0
#   gray     → 2.0 - 4.9
#   green    → 5.0 - 8.4
#   violet   → 8.5 - 10.0
# ══════════════════════════════════════════════════════════════════
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

# Lookup-Dict fuer schnellen Zugriff (uppercase key → natuerlicher Text)
_TAG_NATURAL_MAP = {tag.upper(): natural for tag, natural in _TAG_NATURAL}

# Regex zum Ersetzen interner Tags durch natuerliche Sprache in LLM-Antworten.
# Matcht z.B. "ALOFT-GUST-WARN 1h", "[SHEAR-DEGRADED]", "GUST-DANGER 3h",
# sowie Kurzformen wie "TORN-DEGRADED", "ROUGH-DEGRADED", "SHEAR-DEG".
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
        # Klammern und Whitespace entfernen, trailing "3h" etc. abschneiden
        core = re.sub(r'[\[\]]', '', raw).strip()
        core = re.sub(r'\s+\d+h?$', '', core).strip()
        return _TAG_NATURAL_MAP.get(core.upper(), '')

    cleaned = _TAG_SANITIZE_RE.sub(_replace_tag, text)
    # Doppelte Leerzeichen und Kommas aufraeumen
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


# ══════════════════════════════════════════════════════════════
# Primary-Label-System (siehe static/js/label-catalog.js)
# ══════════════════════════════════════════════════════════════

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
    # Durchsuche alle Eintraege; erstes Match gewinnt
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

    # Validieren
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

    # Zusammenhaengende trockene Abschnitte finden
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

    # Laengstes trockenes Fenster
    longest = max(dry_stretches, key=len)
    dry_start = longest[0]
    dry_end = longest[-1]

    # Eingekesselt = Regen VOR und NACH dem trockenen Fenster
    rain_before = any(h < dry_start for h in rain_hours)
    rain_after = any(h > dry_end for h in rain_hours)

    return {
        "is_sandwiched": rain_before and rain_after,
        "max_dry_gap": len(longest),
        "dry_start": dry_start,
        "dry_end": dry_end,
    }


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
        self._analyses_stale = False  # True nach Wetter-Refresh, bis neue Analysen da sind
        self.region_weather_data = {}
        self.region_analyses = {}
        self.region_analyses_loaded_at = None
        # Fix B: Tracking ob letzter refresh_weather() echt war oder Stale-Fallback
        self.last_refresh_stale = False
        self.last_refresh_status_reason = None

        # Cache fuer Boeen-Floor Enforcement (Post-hoc LLM-Override):
        # Key = f"{spot_name}|{date_str}", Value = dict mit gust-warn/danger Zaehlern.
        # Wird in _build_single_spot_context geschrieben (Main-Thread, sequentiell)
        # und in _safety_check_single_spot_day gelesen (Worker-Threads). Thread-safe,
        # weil Keys vor dem Submit gesetzt sind und danach nur gelesen werden.
        self._ctx_gust_cache = {}
        # Cache fuer Thermik-Qualitaet (Flyability-Override bei falschem gray):
        # Key = f"{name}|{date_str}", Value = dict mit thermal_hours_total, tq_danger_h, peak_climb_proxy
        self._ctx_tq_cache = {}

        api_key = os.environ.get("OPENAI_API_KEY")
        self.model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
        self.client = OpenAI(api_key=api_key, timeout=120.0) if api_key else None

        # History-Persistenz
        self.history_dir = config.HISTORY_DIR
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self._load_all_conversations()

        # Analyse-Persistenz
        self.analyses_file = config.DATA_DIR / "spot_analyses.json"
        self.region_analyses_file = config.DATA_DIR / "region_analyses.json"
        self._load_analyses_cache()

        # Stationsdaten + Bias-Korrektur
        try:
            self.station_manager = StationManager(config.STATION_DB_PATH, self.spots)
            if self.station_manager.needs_discovery():
                print("[ENGINE] Erste Station-Discovery wird durchgeführt...")
                self.station_manager.discover_stations()
                if self.station_manager.needs_backfill():
                    print("[ENGINE] Backfill historischer Stationsdaten...")
                    self.station_manager.backfill_observations()
        except Exception as e:
            logger.error(f"StationManager Init fehlgeschlagen: {e}")
            self.station_manager = None

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
        """Lädt Spot- und Region-Analysen aus Datei und pusht nach InstantDB."""
        loaded_any = False
        if self.analyses_file.exists():
            try:
                with open(self.analyses_file, "r", encoding="utf-8") as f:
                    self.spot_analyses = json.load(f)
                    self.analyses_loaded_at = datetime.fromtimestamp(self.analyses_file.stat().st_mtime)
                print(f"[ENGINE] {len(self.spot_analyses)} Spot-Analysen aus Cache geladen.")
                loaded_any = True
            except Exception as e:
                logger.error(f"Fehler beim Laden des Spot-Analyse-Caches: {e}")
        if self.region_analyses_file.exists():
            try:
                with open(self.region_analyses_file, "r", encoding="utf-8") as f:
                    self.region_analyses = json.load(f)
                    self.region_analyses_loaded_at = datetime.fromtimestamp(
                        self.region_analyses_file.stat().st_mtime)
                print(f"[ENGINE] {len(self.region_analyses)} Region-Analysen aus Cache geladen.")
                loaded_any = True
            except Exception as e:
                logger.error(f"Fehler beim Laden des Region-Analyse-Caches: {e}")
        # Push nach InstantDB damit Frontend-Subscriptions sofort Daten haben
        if loaded_any and self.instantdb:
            if self.spot_analyses:
                threading.Thread(target=self._push_analyses_to_instantdb, daemon=True).start()
            if self.region_analyses:
                threading.Thread(target=self._push_region_analyses_to_instantdb, daemon=True).start()

    def _save_analyses_cache(self):
        """Speichert Spot-Analysen in Datei."""
        try:
            with open(self.analyses_file, "w", encoding="utf-8") as f:
                json.dump(self.spot_analyses, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Fehler beim Speichern des Spot-Analyse-Caches: {e}")

    def _save_region_analyses_cache(self):
        """Speichert Region-Analysen in Datei."""
        try:
            with open(self.region_analyses_file, "w", encoding="utf-8") as f:
                json.dump(self.region_analyses, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Fehler beim Speichern des Region-Analyse-Caches: {e}")

    def _clear_analyses_cache(self):
        """Löscht Analyse-Cache (bei fehlenden/veralteten Wetterdaten)."""
        try:
            if self.analyses_file.exists():
                self.analyses_file.unlink()
            if self.region_analyses_file.exists():
                self.region_analyses_file.unlink()
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

        # Fix B: Reset stale-tracking am Start jedes Refresh-Versuchs
        self.last_refresh_stale = False
        self.last_refresh_status_reason = None

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

        # Fix B: Stale-Cache-Fallback erkennen und SOFORT abbrechen.
        # fetch_all_spots() markiert via _meta.fetch_status, wenn der echte Fetch
        # fehlschlug und nur der alte Cache zurückgegeben wurde. In diesem Fall:
        # - Föhn/Stations/Context NICHT neu bauen (Daten haben sich nicht geändert)
        # - Analysen NICHT löschen (Daten sind unverändert, alte Analysen sind valid)
        # - last_refresh_stale Flag setzen für API-Endpoint
        fetch_status = (self.weather_data or {}).get("_meta", {}).get("fetch_status")
        if fetch_status == "stale_cache":
            reason = (self.weather_data or {}).get("_meta", {}).get("fetch_status_reason", "unknown")
            print(f"[WARN] Wetter-Refresh fehlgeschlagen ({reason}) — überspringe Föhn/Stations/Context, alte Daten bleiben unverändert")
            self.last_refresh_stale = True
            self.last_refresh_status_reason = reason
            return

        # KRITISCH: Wenn keine Wetterdaten verfügbar sind, alte Analysen löschen!
        if not self.weather_data or len([k for k in self.weather_data if not k.startswith("_")]) == 0:
            print("[WARNUNG] Keine Wetterdaten verfügbar - lösche alte Analysen zur Sicherheit")
            self.spot_analyses = {}
            self.region_analyses = {}
            self._clear_analyses_cache()
            return

        # 2. Alte Analysen BEHALTEN bis neue generiert werden.
        # Verhindert Token-Overflow: ohne Analysen wird der riesige Roh-Wetterkontext
        # (~500k Zeichen bei 487 Spots) an das LLM geschickt → 147k Tokens → Error 400.
        # Die alten Analysen sind zwar nicht mehr 100% aktuell, aber immer noch besser
        # als der Fallback auf Rohdaten, der das Token-Limit sprengt.
        # Cleanup passiert erst in run_spot_analyses() / run_combined_analyses() wenn
        # neue Ergebnisse vorliegen.
        if self.spot_analyses:
            print(f"[ENGINE] Behalte {len(self.spot_analyses)} alte Spot-Analysen bis neue generiert werden")
            self._analyses_stale = True
        else:
            self._analyses_stale = False

        # 3. Föhn-Daten holen
        try:
            self.foehn_data = fetch_foehn_data(forecast_days=config.FORECAST_DAYS)
        except Exception as e:
            logger.error(f"Föhn-Daten fehlgeschlagen: {e}")
            self.foehn_data = None

        # 3b. Stationsdaten sammeln + Bias-Korrektur anwenden (Spots + Regionen)
        if self.station_manager:
            try:
                self.station_manager.collect_observations()
                self.station_manager.create_pairs(self.weather_data)
                self.station_manager.apply_bias_correction(self.weather_data)
                # Region-Bias: nur ueber Spots innerhalb des Polygons
                try:
                    from source_area import _load_regions
                    regions_with_polygons = _load_regions()
                    if regions_with_polygons and self.region_weather_data:
                        self.station_manager.apply_bias_correction_to_regions(
                            self.region_weather_data, regions_with_polygons
                        )
                except Exception as e:
                    logger.error(f"Region-Bias-Korrektur fehlgeschlagen: {e}")
            except Exception as e:
                logger.error(f"Station Bias-Korrektur fehlgeschlagen: {e}")

        # 4. Kontext-String bauen
        self.weather_context_str = self._build_weather_context()
        self.weather_loaded_at = datetime.now()

        # 5. Conversations NICHT komplett resetten, aber Cache markieren
        for conv in self.conversations.values():
             conv["first_question"] = True

        # 6. An InstantDB pushen (non-blocking)
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
                    "[STRONG-WIND-WARN]", "[RAIN-WARN]", "[CAPE-WARN]", "[OVERCAST-DANGER]",
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
                        warnings.append("[CAPE-WARN]")
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
                                     "[RAIN-WARN]", "[CAPE-WARN]", "[STRONG-WIND-WARN]", "[OVERCAST-DANGER]"}
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
                    warnings.append("[CAPE-WARN]")
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

            # Klassifiziere saubere vs. gewarnte Stunden (nach allen Warnungen)
            # WICHTIG: Die Thermik-Qualitaets-Tags (SHEAR / THERMAL-TORN / THERMAL-ROUGH)
            # gehoeren hier NICHT rein. Sie betreffen die Fliegbarkeit (kann ich Thermik
            # fliegen?), nicht die Sicherheit (kann ich starten und heil wieder landen?).
            # Eine Stunde mit SHEAR-UNUSABLE + WIND-OK + keine Boeen bleibt sicher fliegbar
            # (Abgleiter), sie ist nur thermisch wertlos. Die LLM-Fliegbarkeits-Phase
            # (flyability.md) interpretiert die Tags und degradiert auf gray/green.
            hard_warnings = {
                "[GUST-DANGER]", "[ALOFT-DANGER]", "[ALOFT-GUST-DANGER]",
                "[RAIN-WARN]", "[CAPE-WARN]", "[STRONG-WIND-WARN]",
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
            lines.append(f"⚠ Gewarnete WIND-OK Stunden ({len(warned_hours)}): {', '.join(warned_hours)} (WIND-OK aber WIND/GUST/ALOFT/RAIN/CAPE/PL-WARN!)")
        if len(clean_hours) >= 3:
            lines.append(f"→ {len(clean_hours)} saubere Stunden: safety_status eher safe oder conditional (Grün/Orange).")
        elif clean_hours:
            lines.append(f"→ Nur {len(clean_hours)} saubere Stunden: Status sollte maximal conditional sein.")
        elif wind_ok_hours and not clean_hours:
            lines.append(f"→ ACHTUNG: Alle {len(wind_ok_hours)} WIND-OK-Stunden haben harte Warnungen (WIND/GUST/ALOFT/RAIN/CAPE)! Status sollte NOT_SAFE sein!")
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
                "[STRONG-WIND-WARN]", "[RAIN-WARN]", "[CAPE-WARN]", "[OVERCAST-DANGER]",
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
            "[WIND-STRONG]", "[RAIN-WARN]", "[CAPE-WARN]", "[OVERCAST-DANGER]",
        ]
        hard_warning_hours = sum(tag_counts.get(t, 0) for t in hard_warning_tags)

        # Cache fuer deterministische Zahlen-Injektion in _safety_check_single_spot_day.
        # LLM darf diese NICHT selber schreiben (Halluzinations-Schutz).
        self._ctx_gust_cache[f"{name}|{date_str}"] = {
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
        }

        # Rain-Sandwich-Erkennung fuer Prefilter + NIEDERSCHLAG-TREND
        all_hours_sorted = sorted(hourly_gusts.keys()) or sorted(set(wind_ok_hours + wind_wrong_hours))
        rain_pattern = _detect_rain_sandwich(rain_hours, all_hours_sorted)
        self._ctx_gust_cache[f"{name}|{date_str}"]["rain_sandwiched"] = rain_pattern["is_sandwiched"]
        self._ctx_gust_cache[f"{name}|{date_str}"]["max_dry_gap"] = rain_pattern["max_dry_gap"]

        # Cache fuer deterministische Flyability-Override
        # rough_danger_h = THERMAL-ROUGH-UNUSABLE + FRAGMENTED → einziger gray-Trigger.
        # tq_danger_h bleibt Summe aller UNUSABLE/FRAGMENTED fuer Text-Hinweise.
        self._ctx_tq_cache[f"{name}|{date_str}"] = {
            "thermal_hours_total": thermal_hours_total,
            "tq_danger_h": tq_rough_danger_h + tq_torn_danger_h + tq_shear_danger_h,
            "rough_danger_h": tq_rough_danger_h,
            "peak_climb_proxy": peak_climb_proxy,
            "productive_thermal_h": productive_thermal_h,
            "clean_hours_count": len(clean_hours),
        }

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
                    warnings.append("[CAPE-WARN]")
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

            # Klassifiziere saubere vs. gewarnte Stunden
            hard_warnings = {"[GUST-DANGER]", "[ALOFT-DANGER]", "[ALOFT-GUST-DANGER]", "[RAIN-WARN]", "[CAPE-WARN]", "[WIND-STRONG]", "[OVERCAST-DANGER]"}
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

        self._ctx_tq_cache[f"{rname}|{date_str}"] = {
            "thermal_hours_total": thermal_hours_total,
            "tq_danger_h": tq_rough_danger_h + tq_torn_danger_h + tq_shear_danger_h,
            "rough_danger_h": tq_rough_danger_h,
            "peak_climb_proxy": peak_climb_proxy,
            "productive_thermal_h": productive_thermal_h,
            "clean_hours_count": len(clean_hours),
            "rain_sandwiched": rain_pattern["is_sandwiched"],
            "max_dry_gap": rain_pattern["max_dry_gap"],
            "rain_cnt": len(rain_hours),
        }

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
                "[WIND-STRONG]", "[RAIN-WARN]", "[CAPE-WARN]", "[OVERCAST-DANGER]",
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

        # Foehn: regionsspezifisch (Süd/Nord/Beide)
        krit_foehn = region.get("kritischer_foehn", "Beide")
        lines.append("")
        lines.append(self._format_foehn_info(date_str=date_str, kritischer_foehn=krit_foehn))

        return "\n".join(lines)

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
        2. Weniger als 4 saubere Stunden → kein 3h-Fenster moeglich
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

        # Regel 2: Weniger als 4 saubere Stunden (kein 3h-Fenster moeglich)
        elif clean_cnt >= 0 and clean_cnt < 4 and total_hours > 0:
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
                    f"kein durchgehendes 3h-Fenster moeglich"
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
    # WEEKLY NEWSPAPER — Wochen-Fazit aus Spot- und Region-Analysen
    # ════════════════════════════════════════════════════════════════════════

    def _weekly_newspaper_cache_path(self) -> Path:
        return Path("data") / "weekly_newspaper.json"

    def _save_weekly_newspaper(self, data: dict) -> None:
        try:
            p = self._weekly_newspaper_cache_path()
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            logger.warning(f"Weekly-Newspaper-Cache-Save fehlgeschlagen: {e}")

    def _load_weekly_newspaper(self) -> dict | None:
        try:
            p = self._weekly_newspaper_cache_path()
            if not p.is_file():
                return None
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"Weekly-Newspaper-Cache-Load fehlgeschlagen: {e}")
            return None

    def build_newspaper_data(self) -> dict:
        """Aggregiert spot_analyses + region_analyses in eine Newspaper-Struktur.
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
                    # Volle Voranalyse fuer Ausklapp-Ansicht im Newspaper
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
                "top_spots": spot_entries[:20],
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

    def generate_weekly_newspaper(self) -> dict:
        """Erstellt das Wochen-Fazit via LLM (inkl. bester Wochentag, Regionen-Ranking, Tages-Highlights)."""
        if not self.client:
            return {"success": False, "error": "OPENAI_API_KEY nicht konfiguriert"}
        data = self.build_newspaper_data()
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
                    {"role": "system", "content": WEEKLY_NEWSPAPER_PROMPT},
                    {"role": "user", "content": (
                        f"AKTUELLE LOKALZEIT: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
                        f"WOCHEN-DATEN:\n{ctx}\n"
                    )},
                ],
                temperature=0.4,
                max_tokens=1500,
                response_format={"type": "json_object"},
            )
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
            self._save_weekly_newspaper(result)
            return result
        except Exception as e:
            logger.error(f"Weekly-Newspaper LLM-Call fehlgeschlagen: {e}")
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

                # Rating / Conditional-Flag (Newspaper) — top-level fuer einfachen Zugriff
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

                # Rating / Conditional-Flag (Newspaper) — top-level fuer einfachen Zugriff
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
                    # Rating / Conditional-Flag (Newspaper)
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
                    # Rating / Conditional-Flag (Newspaper)
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
                "content": SYSTEM_PROMPT + "\n\n" + CAPABILITIES_GUIDE + "\n\n" + FOEHN_CHAT_KNOWLEDGE,
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

        # FORMAT-HINT aus der Frage extrahieren (wird ans LLM gesendet, aber nicht in History gespeichert)
        format_hint = ""
        hint_match = re.search(r'\s*\[FORMAT-HINT:\s*[^\]]*\]', question)
        if hint_match:
            format_hint = hint_match.group(0)
            question_clean = question[:hint_match.start()] + question[hint_match.end():]
            question_clean = question_clean.strip()
        else:
            question_clean = question

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
                # antwortet das Modell bei „Föhn?" ohne ΔP/Kammwind und rät falsch.
                foehn_snap = self._build_foehn_context_for_ai()
                context_block = analyses_context + "\n\n" + foehn_snap
            else:
                context_block = self.weather_context_str

            # Token-Budget: Kontext kürzen falls er das Modell-Limit sprengt
            model_limit = _MODEL_TOKEN_LIMITS.get(self.model, _DEFAULT_TOKEN_LIMIT)
            system_tokens = _estimate_tokens(messages[0]["content"]) if messages else 0
            context_budget = model_limit - _TOKEN_BUDGET_RESERVE - system_tokens
            if context_budget > 0 and _estimate_tokens(context_block) > context_budget:
                context_block = _truncate_weather_context(context_block, context_budget)

            user_content = (
                f"AKTUELZEIT: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ({_weekday_de(datetime.now())})\n"
                "Hintergrunddaten für deine Antwort (nicht wörtlich als Gesamtreport ausgeben):\n"
                "==========================================================\n"
                f"{context_block}\n"
                "==========================================================\n"
                "Beantworte die Frage des Piloten **direkt** und in angemessenem Umfang — wie in einem "
                "kurzen Chat. Keine vollständige Tabelle aller Spots, es sei denn der Pilot verlangt "
                "ausdrücklich eine Übersicht/Tabelle **aller** Gebiete oder einen mehrzeiligen Vergleich.\n"
                'Bei **Föhn-Fragen**: die Föhn-Lage nur aus dem Block „FÖHN-INDIKATOR" (ΔP, Kammwind, Level) '
                'ableiten — nicht aus „alle Spots nicht sicher" schließen, dass es „keinen Föhn" gäbe.\n\n'
                f"Frage des Piloten: {question_clean}{format_hint}"
            )
            conv["first_question"] = False
        else:
            user_content = question_clean + format_hint

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

        # Strip FORMAT-HINT from stored user message to keep history clean
        if format_hint and messages:
            last_user = messages[-1]
            if last_user.get("role") == "user" and format_hint in last_user.get("content", ""):
                last_user["content"] = last_user["content"].replace(format_hint, "").rstrip()

        messages.append({"role": "assistant", "content": reply})
        conv["last_activity"] = datetime.now().isoformat()
        self._save_conversation(session_id)

        return reply

    # ========================================================================
    # PHASE 1: TOOL-USE + STREAMING
    # ========================================================================

    def _build_spot_context_for_tool(self, spot: dict) -> dict:
        """Baut einen kompakten Spot-Eintrag für die Tool-Antwort an den LLM.

        Enthält Stammdaten + (falls vorhanden) Voranalyse-Kurzfassung pro Tag.
        Wird vom find_spots_within_travel_time Tool verwendet.
        """
        name = spot.get("name", "")
        entry = {
            "name": name,
            "fluggebiet": spot.get("fluggebiet", ""),
            "region": spot.get("region", ""),
            "elevation_m": spot.get("elevation_m"),
            "windrichtung": spot.get("windrichtung", ""),
            "latitude": spot.get("latitude"),
            "longitude": spot.get("longitude"),
        }
        # Voranalysen pro Tag (kompakt)
        analyses = self.spot_analyses.get(name, {}) if self.spot_analyses else {}
        if analyses:
            days_summary = {}
            for date_str, day in analyses.items():
                if not isinstance(day, dict):
                    continue
                safety = day.get("safety", {}) if isinstance(day.get("safety"), dict) else {}
                days_summary[date_str] = {
                    "safety_status": safety.get("safety_status") or day.get("safety_status"),
                    "fly_status": day.get("fly_status"),
                    "best_window": day.get("best_window"),
                    "recommendation": (day.get("recommendation") or "")[:240],
                }
            if days_summary:
                entry["analyses"] = days_summary
        return entry

    def _dispatch_tool(self, name: str, args: dict) -> dict:
        """Führt einen Tool-Call aus und gibt ein dispatch-Resultat zurück.

        Returns Dict mit:
            - "content": JSON-serialisierbares Resultat für den OpenAI tool-message
            - "map_actions": Liste von Map-Action-Events, die sofort ans Frontend
              gestreamt werden sollen (oder leere Liste).
        """
        if name == "geocode_location":
            query = (args.get("query") or "").strip()
            if not query:
                return {"content": {"error": "Leere Query"}, "map_actions": []}
            try:
                result = routing.geocode(query)
            except routing.RoutingError as e:
                return {
                    "content": {"error": f"Geocoding fehlgeschlagen: {e}"},
                    "map_actions": [],
                }
            if result is None:
                return {
                    "content": {"error": f"Ort '{query}' nicht gefunden"},
                    "map_actions": [],
                }
            return {"content": result, "map_actions": []}

        if name == "find_spots_within_travel_time":
            try:
                lat = float(args["lat"])
                lon = float(args["lon"])
                minutes = int(args["minutes"])
            except (KeyError, TypeError, ValueError) as e:
                return {
                    "content": {"error": f"Ungültige Parameter: {e}"},
                    "map_actions": [],
                }
            mode = (args.get("mode") or "auto").lower()
            label = (args.get("label") or "").strip()

            try:
                iso = routing.isochrone(lat, lon, minutes, mode)
            except (routing.RoutingError, ValueError) as e:
                return {
                    "content": {
                        "error": (
                            f"Routing-Service ist aktuell nicht erreichbar ({e}). "
                            "Bitte in ein paar Minuten erneut versuchen."
                        )
                    },
                    "map_actions": [],
                }

            try:
                matched = routing.spots_in_polygon(iso, self.spots)
            except routing.RoutingError as e:
                return {
                    "content": {"error": f"Spot-Filter fehlgeschlagen: {e}"},
                    "map_actions": [],
                }

            spot_entries = [self._build_spot_context_for_tool(s) for s in matched]
            spot_names = [s["name"] for s in matched if s.get("name")]

            mode_label = {
                "auto": "Auto",
                "bicycle": "Velo",
                "pedestrian": "zu Fuss",
            }.get(mode, mode)
            iso_label = f"{minutes} min {mode_label}"

            map_actions = [
                {
                    "type": "map_action",
                    "action": "drawIsochrone",
                    "payload": {"geojson": iso, "label": iso_label},
                },
                {
                    "type": "map_action",
                    "action": "setUserLocation",
                    "payload": {"lat": lat, "lon": lon, "label": label or "Standort"},
                },
                {
                    "type": "map_action",
                    "action": "highlightSpots",
                    "payload": {"spots": spot_names},
                },
            ]

            return {
                "content": {
                    "origin": {"lat": lat, "lon": lon, "label": label},
                    "minutes": minutes,
                    "mode": mode,
                    "count": len(spot_entries),
                    "spots": spot_entries,
                },
                "map_actions": map_actions,
            }

        if name == "clear_map_overlays":
            return {
                "content": {"ok": True},
                "map_actions": [
                    {
                        "type": "map_action",
                        "action": "clearAllOverlays",
                        "payload": {},
                    }
                ],
            }

        return {
            "content": {"error": f"Unbekanntes Tool '{name}'"},
            "map_actions": [],
        }

    def answer_stream(self, session_id: str, question: str):
        """Streaming-Variante von answer() mit Tool-Use.

        Generator: yieldet Events der Form
            {"type": "text",       "content": "..."}      # finaler Antworttext
            {"type": "map_action", "action": "...",       # Map-Update
                                   "payload": {...}}
            {"type": "status",     "content": "..."}      # optionale Statusnachricht
            {"type": "error",      "content": "..."}      # Fehler
            {"type": "done"}                              # Stream-Ende
        """
        if not self.client:
            yield {"type": "error", "content": "OPENAI_API_KEY nicht konfiguriert."}
            yield {"type": "done"}
            return

        # FORMAT-HINT extrahieren (analog answer())
        format_hint = ""
        hint_match = re.search(r'\s*\[FORMAT-HINT:\s*[^\]]*\]', question)
        if hint_match:
            format_hint = hint_match.group(0)
            question_clean = question[:hint_match.start()] + question[hint_match.end():]
            question_clean = question_clean.strip()
        else:
            question_clean = question

        self._ensure_weather_context()
        if not self.weather_context_str:
            yield {
                "type": "text",
                "content": "Wetterdaten werden geladen... Bitte versuche es gleich nochmal.",
            }
            yield {"type": "done"}
            return

        self._ensure_spot_analyses()

        messages = self._get_or_create_conversation(session_id)
        conv = self.conversations[session_id]

        if conv["first_question"]:
            analyses_context = self._build_compact_analyses_for_chat()
            if analyses_context:
                foehn_snap = self._build_foehn_context_for_ai()
                context_block = analyses_context + "\n\n" + foehn_snap
            else:
                context_block = self.weather_context_str

            # Token-Budget: Kontext kürzen falls er das Modell-Limit sprengt
            model_limit = _MODEL_TOKEN_LIMITS.get(self.model, _DEFAULT_TOKEN_LIMIT)
            system_tokens = _estimate_tokens(messages[0]["content"]) if messages else 0
            context_budget = model_limit - _TOKEN_BUDGET_RESERVE - system_tokens
            if context_budget > 0 and _estimate_tokens(context_block) > context_budget:
                context_block = _truncate_weather_context(context_block, context_budget)

            user_content = (
                f"AKTUELZEIT: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ({_weekday_de(datetime.now())})\n"
                "Hintergrunddaten für deine Antwort (nicht wörtlich als Gesamtreport ausgeben):\n"
                "==========================================================\n"
                f"{context_block}\n"
                "==========================================================\n"
                "Beantworte die Frage des Piloten **direkt** und in angemessenem Umfang — wie in einem "
                "kurzen Chat. Keine vollständige Tabelle aller Spots, es sei denn der Pilot verlangt "
                "ausdrücklich eine Übersicht/Tabelle **aller** Gebiete oder einen mehrzeiligen Vergleich.\n"
                'Bei **Föhn-Fragen**: die Föhn-Lage nur aus dem Block „FÖHN-INDIKATOR" (ΔP, Kammwind, Level) '
                'ableiten — nicht aus „alle Spots nicht sicher" schließen, dass es „keinen Föhn" gäbe.\n\n'
                f"Frage des Piloten: {question_clean}{format_hint}"
            )
            conv["first_question"] = False
        else:
            user_content = question_clean + format_hint

        messages.append({"role": "user", "content": user_content})

        # History trimmen
        if len(messages) > MAX_HISTORY_MESSAGES:
            messages[:] = messages[:2] + messages[-(MAX_HISTORY_MESSAGES - 2):]

        # ───── Tool-Call-Loop ────────────────────────────────────────────────
        reply_text = ""
        tool_iterations = 0
        emitted_status = False

        try:
            while True:
                if tool_iterations >= MAX_TOOL_ITERATIONS:
                    yield {
                        "type": "error",
                        "content": "Tool-Call-Limit erreicht. Bitte Frage neu formulieren.",
                    }
                    break

                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    tools=TOOLS,
                    tool_choice="auto",
                    temperature=0.7,
                    max_tokens=2000,
                )
                choice = response.choices[0]
                msg = choice.message
                finish_reason = choice.finish_reason

                # Falls Tool-Calls angefordert wurden: dispatchen
                tool_calls = getattr(msg, "tool_calls", None) or []
                if tool_calls:
                    # Assistant-Message mit tool_calls in History anhängen
                    messages.append({
                        "role": "assistant",
                        "content": msg.content or "",
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments,
                                },
                            }
                            for tc in tool_calls
                        ],
                    })

                    # Optional: einmaliger Status-Hinweis vor dem ersten Tool
                    if not emitted_status:
                        yield {
                            "type": "status",
                            "content": "Ich suche erreichbare Spots…",
                        }
                        emitted_status = True

                    for tc in tool_calls:
                        fn_name = tc.function.name
                        try:
                            fn_args = json.loads(tc.function.arguments or "{}")
                        except json.JSONDecodeError as e:
                            fn_args = {}
                            logger.warning(f"Tool {fn_name} arguments JSON invalid: {e}")

                        dispatch = self._dispatch_tool(fn_name, fn_args)

                        # Map-Actions sofort an Frontend streamen
                        for action in dispatch.get("map_actions", []):
                            yield action

                        # Tool-Resultat als tool-message in History
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "name": fn_name,
                            "content": json.dumps(
                                dispatch.get("content", {}), ensure_ascii=False
                            ),
                        })

                    tool_iterations += 1
                    continue  # nächste LLM-Iteration

                # Kein Tool-Call mehr → finale Antwort
                reply_text = msg.content or ""
                messages.append({"role": "assistant", "content": reply_text})
                if reply_text:
                    yield {"type": "text", "content": reply_text}
                break

        except Exception as e:
            logger.error(f"OpenAI API Fehler (stream): {e}")
            yield {
                "type": "error",
                "content": f"Fehler bei der Verarbeitung: {e}",
            }

        # FORMAT-HINT aus letzter user-message strippen (analog answer())
        if format_hint:
            for m in reversed(messages):
                if m.get("role") == "user" and isinstance(m.get("content"), str) and format_hint in m["content"]:
                    m["content"] = m["content"].replace(format_hint, "").rstrip()
                    break

        conv["last_activity"] = datetime.now().isoformat()
        try:
            self._save_conversation(session_id)
        except Exception as e:
            logger.error(f"_save_conversation fehlgeschlagen: {e}")

        yield {"type": "done"}

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

    def _is_wind_in_range(self, wind_dir, sector_str, buffer=0):
        """Prüft ob Windrichtung im erlaubten Sektor liegt (strikt)."""
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
