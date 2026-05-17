"""
Gleitcast Engine — Konstanten + Pure-Helpers.

Alles in dieser Datei hat KEINE Abhaengigkeit zur Engine-Klasse/State.
Nur Konstanten + pure Funktionen. Damit trivial unit-testbar.

Extrahiert aus chat_engine.py (Phase 2 des Monolith-Splits).
"""

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger(__name__)


# ============================================================================
# Chat-History
# ============================================================================
MAX_HISTORY_MESSAGES = 40  # Max messages per conversation before trimming


# ============================================================================
# Token-Budget-Management: verhindert 400-Fehler bei grossen Kontexten.
# Konservativ auf *effektives* Input-Budget je Modell gesetzt (nicht das
# volle Context-Window, damit Output + Overhead Platz haben).
# ============================================================================
_MODEL_TOKEN_LIMITS = {
    # OpenAI
    "gpt-4o-mini":    128_000,
    "gpt-4o":         128_000,
    "gpt-4-turbo":    128_000,
    "gpt-4":            8_192,
    "gpt-3.5-turbo":   16_385,
    "gpt-4.1":        128_000,
    "gpt-4.1-mini":   128_000,
    "gpt-4.1-nano":   128_000,
    # Anthropic (Claude) — alle aktuellen Modelle haben 200k Context
    "claude-haiku-4-5":   200_000,
    "claude-sonnet-4-6":  200_000,
    "claude-opus-4-7":    200_000,
    "claude-3-5-haiku-latest":  200_000,
    "claude-3-5-sonnet-latest": 200_000,
    # Google Gemini — 1M Context bei 2.5-Reihe
    "gemini-2.5-flash":      1_000_000,
    "gemini-2.5-flash-lite": 1_000_000,
    "gemini-2.5-pro":        1_000_000,
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


class BatchCostTracker:
    """Aggregiert Token-Verbrauch pro Phase eines Analyse-Laufs.

    Nutzung:
        tracker = BatchCostTracker(mode="batch", provider="openai", model="gpt-4o-mini")
        tracker.record("region_safety", in_tok=86400, out_tok=3600, cached_tok=0, calls=12)
        ...
        tracker.write(Path("data/cost_telemetry.jsonl"))

    Schreibt eine JSONL-Zeile mit Tokens/Phase, Skip-Rate, USD-Schaetzung,
    Dauer. Preise stammen aus config.MODEL_PRICES.
    """

    def __init__(self, mode: str, provider: str, model: str, commit: str = ""):
        self.mode = mode
        self.provider = provider
        self.model = model
        self.commit = commit
        self.started = time.time()
        self.phases: dict = {}
        self.prefilter_skipped = 0
        self.errors = 0
        self._cost_cap_tripped = False

    def record(self, phase: str, in_tok: int = 0, out_tok: int = 0,
               cached_tok: int = 0, calls: int = 1):
        p = self.phases.setdefault(
            phase, {"calls": 0, "in_tok": 0, "out_tok": 0, "cached_tok": 0}
        )
        p["calls"] += int(calls)
        p["in_tok"] += int(in_tok or 0)
        p["out_tok"] += int(out_tok or 0)
        p["cached_tok"] += int(cached_tok or 0)

    def estimate_usd(self) -> float:
        try:
            import config  # late import to avoid circular
            prices = config.MODEL_PRICES.get(self.model)
        except Exception:
            prices = None
        if not prices:
            return 0.0
        in_key = "in_batch" if self.mode == "batch" else "in"
        out_key = "out_batch" if self.mode == "batch" else "out"
        total = 0.0
        for p in self.phases.values():
            non_cached_in = max(0, p["in_tok"] - p["cached_tok"])
            total += non_cached_in * prices.get(in_key, 0.0) / 1_000_000
            total += p["cached_tok"] * prices.get("cached_in", 0.0) / 1_000_000
            total += p["out_tok"] * prices.get(out_key, 0.0) / 1_000_000
        return round(total, 4)

    def check_cap(self, cap_usd: float) -> bool:
        """Returns True wenn Cap ueberschritten. Setzt _cost_cap_tripped flag."""
        if cap_usd <= 0:
            return False
        current = self.estimate_usd()
        if current > cap_usd:
            self._cost_cap_tripped = True
            logger.error(
                "[COST-BREAKER] Schwelle %s USD ueberschritten (aktuell %.2f USD). "
                "Lauf wird abgebrochen.", cap_usd, current,
            )
            return True
        return False

    def to_record(self) -> dict:
        total_in = sum(p["in_tok"] for p in self.phases.values())
        total_out = sum(p["out_tok"] for p in self.phases.values())
        total_cached = sum(p["cached_tok"] for p in self.phases.values())
        total_calls = sum(p["calls"] for p in self.phases.values())
        return {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "mode": self.mode,
            "provider": self.provider,
            "model": self.model,
            "commit": self.commit,
            "phases": self.phases,
            "prefilter_skipped": self.prefilter_skipped,
            "total_calls": total_calls,
            "total_in_tok": total_in,
            "total_out_tok": total_out,
            "total_cached_tok": total_cached,
            "est_usd": self.estimate_usd(),
            "duration_s": round(time.time() - self.started, 1),
            "errors": self.errors,
            "cost_cap_tripped": self._cost_cap_tripped,
        }

    def write(self, path: Path) -> dict:
        record = self.to_record()
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception as e:
            logger.warning("Konnte Cost-Telemetrie nicht schreiben (%s): %s", path, e)
        # Kompakte Log-Zeile fuer Quick-Glance im Journal
        cache_pct = (
            100.0 * record["total_cached_tok"] / record["total_in_tok"]
            if record["total_in_tok"] else 0.0
        )
        logger.info(
            "[COST] mode=%s model=%s calls=%d in=%d out=%d cached=%d (%.0f%%) "
            "skip=%d est=$%.3f dur=%.1fs",
            self.mode, self.model, record["total_calls"],
            record["total_in_tok"], record["total_out_tok"],
            record["total_cached_tok"], cache_pct,
            self.prefilter_skipped, record["est_usd"], record["duration_s"],
        )
        return record


def extract_usage_from_response(response) -> dict:
    """Extrahiert (in_tok, out_tok, cached_tok) aus einer LLM-Response.

    Funktioniert fuer:
      - OpenAI ChatCompletion: response.usage.prompt_tokens / completion_tokens
        / prompt_tokens_details.cached_tokens
      - Anthropic Messages: response.usage.input_tokens / output_tokens
        / cache_read_input_tokens
      - Stub via SimpleNamespace (Tests)

    Bei fehlenden Feldern: 0.
    """
    out = {"in_tok": 0, "out_tok": 0, "cached_tok": 0}
    try:
        usage = getattr(response, "usage", None)
        if usage is None:
            return out
        # OpenAI-Naming
        out["in_tok"] = int(getattr(usage, "prompt_tokens", 0) or 0)
        out["out_tok"] = int(getattr(usage, "completion_tokens", 0) or 0)
        details = getattr(usage, "prompt_tokens_details", None)
        if details is not None:
            out["cached_tok"] = int(getattr(details, "cached_tokens", 0) or 0)
        # Anthropic-Naming (falls OpenAI-Felder leer waren)
        if out["in_tok"] == 0:
            out["in_tok"] = int(getattr(usage, "input_tokens", 0) or 0)
        if out["out_tok"] == 0:
            out["out_tok"] = int(getattr(usage, "output_tokens", 0) or 0)
        if out["cached_tok"] == 0:
            out["cached_tok"] = int(getattr(usage, "cache_read_input_tokens", 0) or 0)
    except Exception:
        pass
    return out


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
# LLM-Error-Klassifikation (Provider-uebergreifend: OpenAI + Anthropic + Gemini)
# ============================================================================
_PERMANENT_ERROR_KEYWORDS = (
    # OpenAI
    "insufficient_quota", "invalid_api_key", "authentication",
    # Anthropic
    "authentication_error", "permission_error", "invalid api key",
    # Gemini / Google
    "permission_denied", "unauthenticated", "api key not valid",
    "api_key_invalid", "invalid_argument: api key",
    # DeepSeek (und generisch HTTP 402): leeres Guthaben → kein Retry sinnvoll
    "insufficient balance", "payment required", "payment_required",
)


def _is_permanent_api_error(err: Exception) -> bool:
    """Prueft ob ein LLM-Fehler permanent ist (kein Retry sinnvoll).
    insufficient_quota, authentication_error, invalid_api_key → sofort abbrechen.
    rate_limit, timeout, connection → transient, Retry lohnt sich."""
    err_str = str(err).lower()
    return any(kw in err_str for kw in _PERMANENT_ERROR_KEYWORDS)


# Provider-uebergreifende Retry-Hint-Pattern. Reihenfolge: spezifisch → generisch.
# - Gemini:    'retryDelay': '36s'  (strukturiertes detail) + "Please retry in 35.9s."
# - OpenAI:    "Please try again in 1.5s" / "in 250ms" / "in 1m30s"
# - Anthropic: "rate limited, retry after 30s" (selten im string, meist Header)
# - HTTP-Header-Style: "Retry-After: 30"
_RETRY_DELAY_RE = re.compile(r"['\"]retryDelay['\"]\s*:\s*['\"](\d+(?:\.\d+)?)s['\"]")
_RETRY_AFTER_HEADER_RE = re.compile(r"retry-after['\"]?\s*[:=]\s*['\"]?(\d+(?:\.\d+)?)", re.IGNORECASE)
_TRY_AGAIN_S_RE = re.compile(r"(?:try again|retry)(?:\s+in)?\s+(\d+(?:\.\d+)?)\s*s\b", re.IGNORECASE)
_TRY_AGAIN_MS_RE = re.compile(r"(?:try again|retry)(?:\s+in)?\s+(\d+(?:\.\d+)?)\s*ms\b", re.IGNORECASE)
_TRY_AGAIN_M_S_RE = re.compile(r"(?:try again|retry)(?:\s+in)?\s+(\d+)m(\d+(?:\.\d+)?)s", re.IGNORECASE)


def _extract_retry_after_seconds(err: Exception) -> float | None:
    """Extrahiert serverseitig vorgeschlagene Retry-Wartezeit aus dem Fehler.

    Provider-uebergreifend: Gemini ('retryDelay': '36s'), OpenAI ('try again in 1.5s'),
    Anthropic + generische HTTP-Header ('Retry-After: 30'). None = kein Hint vorhanden,
    der Aufrufer faellt auf exponentielles Backoff zurueck."""
    err_str = str(err)
    # 1. Gemini-strukturiert
    m = _RETRY_DELAY_RE.search(err_str)
    if m:
        try:
            return float(m.group(1))
        except (TypeError, ValueError):
            pass
    # 2. OpenAI "in 1m30s" Mischformat
    m = _TRY_AGAIN_M_S_RE.search(err_str)
    if m:
        try:
            return float(m.group(1)) * 60.0 + float(m.group(2))
        except (TypeError, ValueError):
            pass
    # 3. "try again in Xs" / "retry in Xs"
    m = _TRY_AGAIN_S_RE.search(err_str)
    if m:
        try:
            return float(m.group(1))
        except (TypeError, ValueError):
            pass
    # 4. Millisekunden
    m = _TRY_AGAIN_MS_RE.search(err_str)
    if m:
        try:
            return float(m.group(1)) / 1000.0
        except (TypeError, ValueError):
            pass
    # 5. HTTP-Header-Style "Retry-After: 30"
    m = _RETRY_AFTER_HEADER_RE.search(err_str)
    if m:
        try:
            return float(m.group(1))
        except (TypeError, ValueError):
            pass
    return None


def compute_retry_sleep(err: Exception, attempt: int, base: float = 3.0,
                        cap: float = 60.0) -> float:
    """Liefert Sleep-Sekunden fuer den naechsten Retry-Versuch.

    Bevorzugt Server-Hint (Gemini retryDelay, OpenAI 'try again in Xs',
    Anthropic/HTTP Retry-After), sonst exponentielles Backoff (base × 2^attempt)
    mit Cap. attempt=0 = nach 1. Fehlversuch."""
    hint = _extract_retry_after_seconds(err)
    if hint is not None:
        return min(max(hint, 1.0), cap) + 1.0  # +1s Puffer
    return min(base * (2 ** attempt), cap)


def _user_friendly_api_error(err: Exception) -> str:
    """Gibt eine benutzerfreundliche Fehlermeldung fuer permanente LLM-Fehler zurueck."""
    err_str = str(err).lower()
    if ("insufficient_quota" in err_str or "quota" in err_str
            or "insufficient balance" in err_str
            or "payment required" in err_str or "payment_required" in err_str):
        return "API-Budget aufgebraucht — bitte Provider-Guthaben aufladen"
    if any(kw in err_str for kw in ("invalid_api_key", "api_key_invalid", "api key not valid", "invalid api key")):
        return "Ungueltiger API-Key — bitte in den Einstellungen pruefen"
    if any(kw in err_str for kw in ("authentication", "unauthenticated", "permission_denied", "permission_error")):
        return "API-Authentifizierung fehlgeschlagen — bitte API-Key pruefen"
    return f"API-Fehler: {err}"


# ============================================================================
# Reasoning-Model-Erkennung + Token-Budget
# Reasoning-Modelle (deepseek-reasoner, deepseek-v4-pro, OpenAI o-Reihe)
# verbrennen einen Teil des max_tokens-Budgets fuer internes Reasoning,
# bevor sichtbarer Content erscheint. Mit 1500-2500 max_tokens bleibt nichts
# fuer den JSON-Output uebrig → finish_reason='length' + content='' →
# json.loads("") wirft JSONDecodeError. Wir bumpen das Budget pauschal.
# ============================================================================
_REASONING_MODEL_PATTERNS = (
    "reasoner",   # deepseek-reasoner
    "v4-pro",     # deepseek-v4-pro (Reasoning-Variante)
    "v4-flash",   # deepseek-v4-flash (Reasoning-Variante, kleineres MoE)
    "o1-", "o3-", "o4-",  # OpenAI Reasoning-Reihe
    "gemini-2.5-flash",   # Thinking standardmaessig aktiviert (nicht in flash-lite)
    "gemini-2.5-pro",     # Thinking standardmaessig aktiviert
)
_REASONING_TOKEN_HEADROOM = 6000  # +Tokens fuer Reasoning-Phase, robust gegen lange Kontexte


def _is_reasoning_model(model: str) -> bool:
    if not model:
        return False
    m = str(model).lower()
    return any(p in m for p in _REASONING_MODEL_PATTERNS) or m in ("o1", "o3", "o4")


def _resolve_max_tokens(model: str, base: int) -> int:
    """Bumpt max_tokens fuer Reasoning-Modelle damit der JSON-Output nicht
    durch den internen Reasoning-Verbrauch abgeschnitten wird."""
    if _is_reasoning_model(model):
        return base + _REASONING_TOKEN_HEADROOM
    return base


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


def _compute_safety_rating(result: dict) -> float:
    """Berechnet das Safety-Gesamtrating aus 5 LLM-Sub-Ratings nach dem
    **Weakest-Link-Prinzip** — der niedrigste Wert bestimmt das Resultat.

    RATING_CONCEPT v1.3 §3.5: Sicherheit ist asymmetrisch. Anders als bei
    der Fliegbarkeits-Aggregation (gewichteter Durchschnitt) darf hier ein
    perfekter Aspekt keinen schlechten kompensieren — sonst wuerde ein
    Tag mit "Wind 9, Gewitter-CAPE-WARN 2" als grosse 7/10 wirken, obwohl
    der einzelne kritische Aspekt den Tag definiert.

    8 Sub-Ratings (alle 1-10):
      - wind_safety_rating          (Bodenwind)
      - gust_safety_rating          (Boeen)
      - aloft_safety_rating         (Hoehenwind FL050-100)
      - foehn_safety_rating         (Foehn-Risiko synoptisch)
      - rain_safety_rating          (Niederschlag)
      - thunderstorm_safety_rating  (Gewitter)
      - cape_safety_rating          (Konvektionsenergie / Ueberentwicklung)
      - visibility_safety_rating    (Sicht / Wolkenbasis)

    Aggregation: `min(wind, gust, aloft, foehn, rain, thunderstorm, cape, visibility)`.

    Bei `safety_status = "not_safe"` setzt der LLM laut Skill alle 8 Werte
    auf 1 → Resultat 1.0 (analog Fliegbarkeit). Decision-Engine-Hard-Overrides
    (FoehnDanger, AloftNotSafe) erzwingen das auf der Status-Ebene zusaetzlich.

    Defaults bei fehlenden / invaliden Feldern: 5 (analog Fliegbarkeits-
    Sub-Ratings).
    """
    # Sub-Rating <=0 oder nicht-numerisch ist "nicht bewertbar" (z.B. Regionen
    # haben keine Gust-Daten → Skill-Schema laesst gust_safety_rating auf 0).
    # Solche Werte werden aus dem Weakest-Link-Min ausgeschlossen, sonst
    # wuerde ein "kein Datenmaterial"-Wert den Tag als unsicher markieren.
    def _maybe(v):
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        if f <= 0:
            return None
        return max(1.0, min(10.0, f))

    vals = [v for v in (
        _maybe(result.get("wind_safety_rating")),
        _maybe(result.get("gust_safety_rating")),
        _maybe(result.get("aloft_safety_rating")),
        _maybe(result.get("foehn_safety_rating")),
        _maybe(result.get("rain_safety_rating")),
        _maybe(result.get("thunderstorm_safety_rating")),
        _maybe(result.get("cape_safety_rating")),
        _maybe(result.get("visibility_safety_rating")),
    ) if v is not None]
    if not vals:
        return 5.0
    return round(min(vals), 1)


def _compute_safety_score(rating_0_10) -> int:
    """Skaliert das `safety_rating` (0-10) auf `safety_score` (0-100).

    Analog zu `_compute_experience_score` — kosmetische Skalierung fuer das
    UI. Robust gegen None / invalide Werte → liefert 0.
    """
    try:
        r = float(rating_0_10)
    except (TypeError, ValueError):
        return 0
    return max(0, min(100, round(r * 10)))


def derive_status_from_subs(result: dict):
    """Leitet `safety_status` deterministisch aus den 5 Safety-Sub-Ratings ab.

    Schwellen (am bestehenden `compute_safety_band`-Score-Threshold ausgerichtet:
    score<40 → amber entspricht rating<4):
      - min(subs) <= 2 → "not_safe"     (akut gefaehrlich, Skill-Anker 1)
      - min(subs) <= 3 → "conditional"  (grenzwertig kritisch)
      - min(subs) >= 4 → "safe"

    Sub-Ratings <=0 oder nicht-numerisch werden als "nicht bewertbar" behandelt
    und ausgeschlossen (analog `_compute_safety_rating`). Wenn keine
    bewertbaren Subs vorliegen, liefert die Funktion None — der Aufrufer soll
    dann nichts ueberschreiben.

    Diese Funktion ist die Konsistenz-Bruecke zwischen LLM-Sub-Ratings und
    LLM-Status: das LLM darf sich nicht selbst widersprechen (z.B. status=safe
    + wind_safety_rating=3). Aufrufer in `_post_process_safety_*` vergleicht
    den Output mit dem aktuellen `safety_status` und eskaliert (nie demoten),
    falls die Subs strenger sind.
    """
    def _maybe(v):
        try:
            f = float(v)
        except (TypeError, ValueError):
            return None
        if f <= 0:
            return None
        return max(1.0, min(10.0, f))

    vals = [v for v in (
        _maybe(result.get("wind_safety_rating")),
        _maybe(result.get("gust_safety_rating")),
        _maybe(result.get("aloft_safety_rating")),
        _maybe(result.get("foehn_safety_rating")),
        _maybe(result.get("rain_safety_rating")),
        _maybe(result.get("thunderstorm_safety_rating")),
        _maybe(result.get("cape_safety_rating")),
        _maybe(result.get("visibility_safety_rating")),
    ) if v is not None]

    if not vals:
        return None

    m = min(vals)
    if m <= 2:
        return "not_safe"
    if m <= 3:
        return "conditional"
    return "safe"


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
    ("THERMAL-WIND-UNUSABLE",  "Grundwind zerreisst Thermik"),
    ("THERMAL-WIND-DEGRADED",  "Grundwind stoert Thermik"),
    # Kurzformen (LLM kuerzt manchmal ab)
    ("TORN-UNUSABLE",          "Thermik zerrissen"),
    ("TORN-DEGRADED",          "Thermik unruhig"),
    ("ROUGH-FRAG",             "Thermik fragmentiert"),
    ("ROUGH-UNUSABLE",         "extreme Turbulenz"),
    ("ROUGH-DEGRADED",         "ruppige Thermik"),
    ("SHEAR-DEG",              "Hoehenscherung"),
    ("WIND-UNUSABLE",          "Grundwind zu stark fuer Thermik"),
    ("WIND-DEGRADED",          "starker Grundwind stoert Thermik"),
    # Wind / Boeen
    ("ALOFT-GUST-DANGER",      "gefaehrliche Hoehenboeen"),
    ("ALOFT-GUST-WARN",        "kraeftige Hoehenboeen"),
    ("ALOFT-WIND-DANGER",      "gefaehrlicher Hoehenwind"),
    ("ALOFT-WIND-WARN",        "kraeftiger Hoehenwind"),
    # Kurzformen (LLM kuerzt manchmal "ALOFT-WIND" als Sammelbegriff ab)
    ("ALOFT-GUST",             "Hoehenboeen"),
    ("ALOFT-WIND",             "Hoehenwind"),
    ("GUST-DANGER",            "gefaehrliche Boeen"),
    ("GUST-WARN",              "starke Boeen"),
    ("WIND-DANGER",            "starker Wind"),
    ("WIND-WARN",              "maessiger Wind"),
    ("WIND-WRONG",             "falsche Windrichtung"),
    ("WIND-OK",                "passende Windrichtung"),
    # Sonstiges
    ("RAIN-WARN",              "Regen"),
    ("CAPE-DANGER",            "Ueberentwicklungsgefahr"),
    ("CAPE-WARN",              "Ueberentwicklung moeglich"),
    ("OVERCAST-DANGER",        "dichte Wolkendecke"),
    ("THUNDERSTORM",           "Gewitter"),
    # Trend-Vokabular (interne Pattern-Codes, sollten nicht in der Antwort stehen)
    ("DURCHGEHEND_DANGER",     "durchgehend gefaehrlich"),
    ("DURCHGEHEND_WARN",       "durchgehend erhoeht"),
    ("EINGEKESSELT_KNAPP",     "knapp eingekesselt"),
    ("EINGEKESSELT",           "eingekesselt"),
    ("AUFKLAERUNG",            "Aufklaerung"),
    ("VEREINZELT",             "vereinzelt"),
    ("ZUNEHMEND",              "zunehmend"),
    ("ABNEHMEND",              "abnehmend"),
    ("STABIL",                 "stabil"),
    ("WIND-TREND",             "Wind-Verlauf"),
    ("GUST-TREND",             "Boeen-Verlauf"),
]

_TAG_NATURAL_MAP = {tag.upper(): natural for tag, natural in _TAG_NATURAL}

# Regex matcht nur Tag (mit optionalen Klammern + optionalem Doppelpunkt).
# Trailing Stunden-Angaben wie "6h" oder "13-16h" werden BEWUSST nicht gefressen,
# damit Zeit-/Dauer-Information erhalten bleibt: "ALOFT-WIND-DANGER: 6h"
# wird zu "gefaehrlicher Hoehenwind: 6h" (lesbar) statt nur "gefaehrlicher Hoehenwind".
_TAG_SANITIZE_RE = re.compile(
    r'\[?(?:'
    + '|'.join(re.escape(tag) for tag, _ in _TAG_NATURAL)
    + r')\]?',
    re.IGNORECASE
)

# Suffixe in Composita wie "ALOFT-WIND-WARN-Stunden" oder "GUST-Phase".
# Werden nach dem Tag-Replace zu Leerzeichen, damit "-Stunden" nicht direkt
# am uebersetzten Begriff klebt: "kraeftiger Hoehenwind-Stunden" -> "kraeftiger Hoehenwind Stunden".
_COMPOUND_SUFFIX_RE = re.compile(
    r'(\w)-(Stunden|Phase|Phasen|Periode|Periode|Zeit|Fenster)\b',
    re.IGNORECASE,
)


def _sanitize_llm_text(text: str) -> str:
    """Ersetzt versehentlich verbliebene interne Tags durch kurze deutsche Begriffe."""
    if not text or not isinstance(text, str):
        return text

    def _replace_tag(m):
        raw = m.group(0)
        core = re.sub(r'[\[\]]', '', raw).strip()
        return _TAG_NATURAL_MAP.get(core.upper(), '')

    cleaned = _TAG_SANITIZE_RE.sub(_replace_tag, text)
    # Composita-Suffix entkleben ("Hoehenwind-Stunden" -> "Hoehenwind Stunden").
    cleaned = _COMPOUND_SUFFIX_RE.sub(r'\1 \2', cleaned)
    # Doppelpunkt-Ketten zusammenfuehren ("Wind: : 6h" -> "Wind: 6h").
    cleaned = re.sub(r':\s*:\s*', ': ', cleaned)
    cleaned = re.sub(r'\s{2,}', ' ', cleaned)
    cleaned = re.sub(r',\s*,', ',', cleaned)
    cleaned = re.sub(r'^\s*,\s*', '', cleaned)
    cleaned = re.sub(r'\s*,\s*$', '', cleaned)
    # Klammer-Reste wie "()" oder "( )" nach komplettem Tag-Replace tilgen.
    cleaned = re.sub(r'\(\s*\)', '', cleaned)
    return cleaned.strip()


# Heuristik fuer Restcheck: GROSSBUCHSTABEN-WORT-MIT-BINDESTRICH (mind. 4 Zeichen),
# das wie ein interner Code aussieht. Nur zum Loggen — wir mutieren den Text nicht
# noch einmal, damit echte Eigennamen/Abkuerzungen unberuehrt bleiben.
_LEFTOVER_TAG_RE = re.compile(r'\b[A-Z]{2,}(?:[-_][A-Z]{2,}){1,}\b')


def _warn_leftover_tags(result: dict, label: str = "") -> None:
    """Loggt eine Warnung, falls nach Sanitierung noch interne Codes in Texten stehen."""
    fields = ("summary", "recommendation", "thermal_quality", "wind_summary", "wind_shear",
              "xc_details", "soaring_options", "safety_feedback")
    list_fields = ("caution_notes", "no_go_reasons", "flyability_limits", "highlights")
    leftovers = []
    for key in fields:
        val = result.get(key)
        if isinstance(val, str):
            for m in _LEFTOVER_TAG_RE.findall(val):
                leftovers.append(f"{key}: {m}")
    for key in list_fields:
        val = result.get(key)
        if isinstance(val, list):
            for item in val:
                if isinstance(item, str):
                    for m in _LEFTOVER_TAG_RE.findall(item):
                        leftovers.append(f"{key}[]: {m}")
    if leftovers:
        prefix = f"[{label}] " if label else ""
        logger.warning(f"{prefix}Resttags nach Sanitizer: {', '.join(sorted(set(leftovers)))}")


def _sanitize_llm_result(result: dict) -> dict:
    """Sanitiert alle Text-Felder eines LLM-Ergebnisses von internen Tags."""
    for key in ("summary", "recommendation", "thermal_quality", "wind_summary", "wind_shear",
                "xc_details", "soaring_options", "safety_feedback"):
        if key in result and isinstance(result[key], str):
            result[key] = _sanitize_llm_text(result[key])
    for key in ("caution_notes", "no_go_reasons", "flyability_limits", "highlights"):
        if key in result and isinstance(result[key], list):
            result[key] = [_sanitize_llm_text(item) for item in result[key] if _sanitize_llm_text(item)]
    # Streckenflug-Block (verschachtelt) auch reinigen.
    sf = result.get("streckenflug")
    if isinstance(sf, dict):
        for key in ("summary", "limiting_factor"):
            if key in sf and isinstance(sf[key], str):
                sf[key] = _sanitize_llm_text(sf[key])
    label = f"{result.get('spot') or result.get('region') or '?'}/{result.get('date') or '?'}"
    _warn_leftover_tags(result, label=label)
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
    "STARKER_WIND", "TURBULENZ", "SHEAR_WIND",
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
    "STARKER_WIND", "TURBULENZ", "SHEAR_WIND",
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


def _compute_wind_trend(
    clean_hours: list[str],
    hourly_values: dict[str, float],
    value_label: str = "Böen",
    danger_threshold: float = 40,
) -> str:
    """Berechnet Windtendenz rund um das saubere Fenster.

    value_label: "Böen" (Spot, Default) oder "Wind" (Region, keine Böen).
    danger_threshold: km/h, ab der der Wert als gefährlich gilt
        (40 für Böen, 30 für Wind-only).

    Returns z.B.:
        "WIND-TREND: VERSCHLECHTERUNG — Böen steigen nach Fenster von 37→57 km/h"
        "WIND-TREND: STABIL"
    """
    if not clean_hours or not hourly_values:
        return ""

    all_hours = sorted(hourly_values.keys())
    if not all_hours:
        return ""

    clean_set = set(clean_hours)
    first_clean = min(clean_set)
    last_clean = max(clean_set)

    # Werte VOR dem Fenster (bis zu 3 Stunden)
    pre_vals = []
    for h in all_hours:
        if h >= first_clean:
            break
        pre_vals.append(hourly_values[h])
    pre_vals = pre_vals[-3:]

    # Werte IM Fenster
    window_vals = [hourly_values[h] for h in all_hours if h in clean_set and h in hourly_values]

    # Werte NACH dem Fenster (bis zu 3 Stunden)
    post_vals = []
    past_window = False
    for h in all_hours:
        if h > last_clean:
            past_window = True
        if past_window and h in hourly_values:
            post_vals.append(hourly_values[h])
            if len(post_vals) >= 3:
                break

    if not window_vals:
        return ""

    avg_window = sum(window_vals) / len(window_vals)
    avg_pre = sum(pre_vals) / len(pre_vals) if pre_vals else 0
    avg_post = sum(post_vals) / len(post_vals) if post_vals else 0
    max_post = max(post_vals) if post_vals else 0

    pre_danger = avg_pre > danger_threshold
    post_danger = avg_post > danger_threshold

    if pre_danger and post_danger:
        return (
            f"WIND-TREND: EINGEKESSELT — Fenster liegt zwischen zwei {value_label}-Phasen "
            f"(vorher Ø{avg_pre:.0f}, Fenster Ø{avg_window:.0f}, nachher Ø{avg_post:.0f} km/h). "
            f"ERHÖHTES RISIKO: Verschlechterung nach dem Fenster sehr wahrscheinlich!"
        )
    elif post_danger and not pre_danger:
        return (
            f"WIND-TREND: VERSCHLECHTERUNG — {value_label} steigen nach dem Fenster stark an "
            f"(Fenster Ø{avg_window:.0f} → nachher Ø{avg_post:.0f} km/h, max {max_post:.0f} km/h). "
            f"ERHÖHTES RISIKO!"
        )
    elif pre_danger and not post_danger:
        return (
            f"WIND-TREND: VERBESSERUNG — {value_label} nehmen ab "
            f"(vorher Ø{avg_pre:.0f} → Fenster Ø{avg_window:.0f} → nachher Ø{avg_post:.0f} km/h). "
            f"Positiver Trend."
        )
    elif post_vals and avg_post > avg_window + 10:
        return (
            f"WIND-TREND: LEICHTE VERSCHLECHTERUNG — {value_label} nehmen nach dem Fenster zu "
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


def _detect_gust_trend(gust_hours: list, all_hours_sorted: list,
                       gust_danger_hours: list = None) -> dict:
    """Erkennt Boeen-Trendmuster ueber den Tag (Boden + Hoehe summiert).

    Boeen-Stunden = Stunden mit irgendeinem der Tags
    [GUST-WARN], [GUST-DANGER], [ALOFT-GUST-WARN], [ALOFT-GUST-DANGER].
    gust_danger_hours: Untermenge mit Tags >40 km/h (DANGER-Level).

    Returns dict mit:
        is_sandwiched, max_calm_gap, calm_start, calm_end,
        gusts_before_calm, gusts_after_calm, gust_count, danger_count, total_count,
        pattern_label: AUFKLAERUNG | ZUNEHMEND | EINGEKESSELT | EINGEKESSELT_KNAPP
                       | DURCHGEHEND_DANGER | DURCHGEHEND_WARN | VEREINZELT | KEIN.
    """
    total = len(all_hours_sorted or [])
    danger_count = len(gust_danger_hours or [])
    if not gust_hours or not all_hours_sorted:
        return {
            "is_sandwiched": False,
            "max_calm_gap": total,
            "calm_start": all_hours_sorted[0] if all_hours_sorted else "",
            "calm_end": all_hours_sorted[-1] if all_hours_sorted else "",
            "gusts_before_calm": False,
            "gusts_after_calm": False,
            "gust_count": 0,
            "danger_count": 0,
            "total_count": total,
            "pattern_label": "KEIN",
        }

    gust_set = set(gust_hours)
    calm_stretches = []
    current_calm = []
    for h in all_hours_sorted:
        if h not in gust_set:
            current_calm.append(h)
        else:
            if current_calm:
                calm_stretches.append(current_calm[:])
            current_calm = []
    if current_calm:
        calm_stretches.append(current_calm)

    gc = len(gust_hours)
    danger_majority = danger_count >= max(3, int(0.5 * gc))

    if not calm_stretches:
        return {
            "is_sandwiched": False,
            "max_calm_gap": 0,
            "calm_start": "",
            "calm_end": "",
            "gusts_before_calm": False,
            "gusts_after_calm": False,
            "gust_count": gc,
            "danger_count": danger_count,
            "total_count": total,
            "pattern_label": "DURCHGEHEND_DANGER" if danger_majority else "DURCHGEHEND_WARN",
        }

    longest = max(calm_stretches, key=len)
    calm_start = longest[0]
    calm_end = longest[-1]
    gusts_before = any(h < calm_start for h in gust_hours)
    gusts_after = any(h > calm_end for h in gust_hours)
    is_sand = gusts_before and gusts_after
    calm_gap = len(longest)

    if gc >= max(1, int(0.75 * total)) or calm_gap < 2:
        label = "DURCHGEHEND_DANGER" if danger_majority else "DURCHGEHEND_WARN"
    elif is_sand and calm_gap < 4:
        label = "EINGEKESSELT"
    elif is_sand:
        label = "EINGEKESSELT_KNAPP"
    elif gusts_before and not gusts_after:
        label = "AUFKLAERUNG"
    elif gusts_after and not gusts_before:
        label = "ZUNEHMEND"
    else:
        label = "VEREINZELT"

    return {
        "is_sandwiched": is_sand,
        "max_calm_gap": calm_gap,
        "calm_start": calm_start,
        "calm_end": calm_end,
        "gusts_before_calm": gusts_before,
        "gusts_after_calm": gusts_after,
        "gust_count": gc,
        "danger_count": danger_count,
        "total_count": total,
        "pattern_label": label,
    }


def _format_gust_trend_text(gust_pattern: dict, gust_hours: list) -> str:
    """Erzeugt GUST-TREND Text-Zeile fuer LLM-Kontext (analog NIEDERSCHLAG-TREND).

    Pattern-Klassifikation:
      DURCHGEHEND  — boeige Stunden >= 75% des Tages oder ruhiges Fenster < 2h
      EINGEKESSELT — Boeen vor UND nach ruhigem Fenster (< 4h Gap)
      EINGEKESSELT (knapp) — wie oben aber Gap 4-5h
      AUFKLAERUNG  — boeig nur frueh, danach ruhig (keine Rueckkehr)
      ZUNEHMEND    — ruhig morgens, boeig nachmittags
      VEREINZELT   — boeige Stunden gestreut, lange ruhige Phase vorhanden

    Severitaet: not_safe nur bei DANGER-Mehrheit (>40 km/h Bodenboeen ODER
    >40 km/h Hoehenboeen im Flugraum). Reine WARN-Level (30-40 km/h) →
    max conditional, sportlich.
    """
    if not gust_hours:
        return ""

    gc = gust_pattern.get("gust_count", 0)
    tc = gust_pattern.get("total_count", 0)
    dc = gust_pattern.get("danger_count", 0)
    if tc == 0 or gc == 0:
        return ""

    gusts_before = gust_pattern.get("gusts_before_calm", False)
    gusts_after = gust_pattern.get("gusts_after_calm", False)
    is_sand = gust_pattern.get("is_sandwiched", False)
    calm_gap = gust_pattern.get("max_calm_gap", 0)
    calm_start = gust_pattern.get("calm_start", "")
    calm_end = gust_pattern.get("calm_end", "")

    danger_majority = dc >= max(3, int(0.5 * gc))

    if gc >= max(1, int(0.75 * tc)) or calm_gap < 2:
        if danger_majority:
            return (
                f"GUST-TREND: DURCHGEHEND_DANGER — Boeige Stunden in {gc} von {tc}h, "
                f"davon {dc}h DANGER-Level (Boden oder Flugraum). "
                f"Laengstes ruhiges Fenster {calm_gap}h."
            )
        return (
            f"GUST-TREND: DURCHGEHEND_WARN — Boeige Stunden in {gc} von {tc}h auf WARN-Level, "
            f"laengstes ruhiges Fenster {calm_gap}h."
        )

    if is_sand and calm_gap < 4:
        if danger_majority:
            return (
                f"GUST-TREND: EINGEKESSELT (mit DANGER) — Ruhiges Fenster {calm_gap}h "
                f"({calm_start}-{calm_end}) zwischen boeigen Phasen "
                f"({gc}h boeig, davon {dc}h DANGER-Level)."
            )
        return (
            f"GUST-TREND: EINGEKESSELT (WARN-Level) — Ruhiges Fenster {calm_gap}h "
            f"({calm_start}-{calm_end}) zwischen boeigen Phasen ({gc}h auf WARN-Level)."
        )

    if is_sand:
        return (
            f"GUST-TREND: EINGEKESSELT_KNAPP — Ruhiges Fenster {calm_gap}h "
            f"({calm_start}-{calm_end}) zwischen boeigen Phasen ({gc}h insgesamt)."
        )

    if gusts_before and not gusts_after:
        return (
            f"GUST-TREND: AUFKLAERUNG — Boeig frueh ({gc}h, bis {calm_start}), "
            f"danach ruhig ({calm_gap}h ab {calm_start})."
        )

    if gusts_after and not gusts_before:
        return (
            f"GUST-TREND: ZUNEHMEND — Ruhig morgens ({calm_gap}h, bis {calm_end}), "
            f"danach {gc}h boeig."
        )

    return (
        f"GUST-TREND: VEREINZELT — {gc}h boeige Phasen verteilt, "
        f"laengstes ruhiges Fenster {calm_gap}h ({calm_start}-{calm_end})."
    )


def _detect_aloft_trend(aloft_hours: list, all_hours_sorted: list,
                        aloft_danger_hours: list = None) -> dict:
    """Erkennt Wind-Trendmuster ueber den Tag (Boden + Hoehe summiert, analog _detect_gust_trend).

    aloft_hours = Stunden mit [WIND-WARN] / [WIND-DANGER] / [ALOFT-WIND-WARN] / [ALOFT-WIND-DANGER].
    aloft_danger_hours: Untermenge mit [WIND-DANGER] / [ALOFT-WIND-DANGER] (> WIND_DANGER_KMH).
    Funktionsname historisch (war frueher nur Hoehenwind), liefert jetzt aber den WIND-TREND.

    Returns dict mit:
        is_sandwiched: bool — ruhiges Fenster zwischen zwei Wind-Phasen (Boden+Hoehe)
        max_calm_gap: int — laengstes zusammenhaengendes ruhiges Fenster (Stunden)
        calm_start: str — Beginn des laengsten ruhigen Fensters
        calm_end: str — Ende
        aloft_before_calm: bool — Hoehenwind-Stunden vor dem laengsten ruhigen Fenster
        aloft_after_calm: bool — Hoehenwind-Stunden nach dem laengsten ruhigen Fenster
        aloft_count: int — Anzahl Hoehenwind-Stunden (WARN + DANGER)
        danger_count: int — Anzahl Stunden mit DANGER-Level (> WIND_DANGER_KMH)
        total_count: int — Gesamtanzahl Stunden im Fenster
        pattern_label: str — AUFKLAERUNG | ZUNEHMEND | EINGEKESSELT | EINGEKESSELT_KNAPP
                             | DURCHGEHEND_DANGER | DURCHGEHEND_WARN | VEREINZELT | KEIN
    """
    total = len(all_hours_sorted or [])
    danger_count = len(aloft_danger_hours or [])
    if not aloft_hours or not all_hours_sorted:
        return {
            "is_sandwiched": False,
            "max_calm_gap": total,
            "calm_start": all_hours_sorted[0] if all_hours_sorted else "",
            "calm_end": all_hours_sorted[-1] if all_hours_sorted else "",
            "aloft_before_calm": False,
            "aloft_after_calm": False,
            "aloft_count": 0,
            "danger_count": 0,
            "total_count": total,
            "pattern_label": "KEIN",
        }

    aloft_set = set(aloft_hours)
    calm_stretches = []
    current_calm = []
    for h in all_hours_sorted:
        if h not in aloft_set:
            current_calm.append(h)
        else:
            if current_calm:
                calm_stretches.append(current_calm[:])
            current_calm = []
    if current_calm:
        calm_stretches.append(current_calm)

    ac = len(aloft_hours)

    if not calm_stretches:
        return {
            "is_sandwiched": False,
            "max_calm_gap": 0,
            "calm_start": "",
            "calm_end": "",
            "aloft_before_calm": False,
            "aloft_after_calm": False,
            "aloft_count": ac,
            "danger_count": danger_count,
            "total_count": total,
            "pattern_label": "DURCHGEHEND_DANGER" if danger_count >= max(3, int(0.5 * ac)) else "DURCHGEHEND_WARN",
        }

    longest = max(calm_stretches, key=len)
    calm_start = longest[0]
    calm_end = longest[-1]
    aloft_before = any(h < calm_start for h in aloft_hours)
    aloft_after = any(h > calm_end for h in aloft_hours)
    is_sand = aloft_before and aloft_after
    calm_gap = len(longest)
    danger_majority = danger_count >= max(3, int(0.5 * ac))

    # Pattern-Klassifikation (parallel zu _format_gust_trend_text)
    if ac >= max(1, int(0.75 * total)) or calm_gap < 2:
        label = "DURCHGEHEND_DANGER" if danger_majority else "DURCHGEHEND_WARN"
    elif is_sand and calm_gap < 4:
        label = "EINGEKESSELT"
    elif is_sand:
        label = "EINGEKESSELT_KNAPP"
    elif aloft_before and not aloft_after:
        label = "AUFKLAERUNG"
    elif aloft_after and not aloft_before:
        label = "ZUNEHMEND"
    else:
        label = "VEREINZELT"

    return {
        "is_sandwiched": is_sand,
        "max_calm_gap": calm_gap,
        "calm_start": calm_start,
        "calm_end": calm_end,
        "aloft_before_calm": aloft_before,
        "aloft_after_calm": aloft_after,
        "aloft_count": ac,
        "danger_count": danger_count,
        "total_count": total,
        "pattern_label": label,
    }


def _format_aloft_trend_text(aloft_pattern: dict, aloft_hours: list,
                             danger_kmh: float = 30, warn_kmh: float = 20) -> str:
    """Erzeugt WIND-TREND Text-Zeile fuer LLM-Kontext (analog GUST-TREND).

    Pattern-Klassifikation: siehe _detect_aloft_trend → pattern_label.
    Severitaet: not_safe nur bei DURCHGEHEND_DANGER oder EINGEKESSELT mit DANGER
    und Fenster < 3h. AUFKLAERUNG darf conditional bleiben, auch wenn morgens
    DANGER war. ZUNEHMEND → max conditional (Pilot landet frueh).
    """
    if not aloft_hours:
        return ""

    ac = aloft_pattern.get("aloft_count", 0)
    tc = aloft_pattern.get("total_count", 0)
    dc = aloft_pattern.get("danger_count", 0)
    if tc == 0 or ac == 0:
        return ""

    calm_gap = aloft_pattern.get("max_calm_gap", 0)
    calm_start = aloft_pattern.get("calm_start", "")
    calm_end = aloft_pattern.get("calm_end", "")
    label = aloft_pattern.get("pattern_label", "")

    if label == "DURCHGEHEND_DANGER":
        return (
            f"WIND-TREND: DURCHGEHEND_DANGER — Wind (Boden+Hoehe) in {ac} von {tc}h, "
            f"davon {dc}h DANGER-Level. Laengstes ruhiges Fenster {calm_gap}h."
        )
    if label == "DURCHGEHEND_WARN":
        return (
            f"WIND-TREND: DURCHGEHEND_WARN — Wind (Boden+Hoehe) in {ac} von {tc}h auf WARN-Level, "
            f"laengstes ruhiges Fenster {calm_gap}h."
        )
    if label == "EINGEKESSELT":
        if dc >= max(1, int(0.3 * ac)):
            return (
                f"WIND-TREND: EINGEKESSELT (mit DANGER) — Ruhiges Fenster {calm_gap}h "
                f"({calm_start}-{calm_end}) zwischen Wind-Phasen (Boden+Hoehe) "
                f"({ac}h Hoehenwind, davon {dc}h DANGER-Level)."
            )
        return (
            f"WIND-TREND: EINGEKESSELT (WARN-Level) — Ruhiges Fenster {calm_gap}h "
            f"({calm_start}-{calm_end}) zwischen Wind-Phasen (Boden+Hoehe) ({ac}h auf WARN-Level)."
        )
    if label == "EINGEKESSELT_KNAPP":
        return (
            f"WIND-TREND: EINGEKESSELT_KNAPP — Ruhiges Fenster {calm_gap}h "
            f"({calm_start}-{calm_end}) zwischen Wind-Phasen (Boden+Hoehe) ({ac}h insgesamt)."
        )
    if label == "AUFKLAERUNG":
        return (
            f"WIND-TREND: AUFKLAERUNG — Wind frueh ({ac}h, bis {calm_start}, "
            f"davon {dc}h DANGER-Level), danach ruhig ({calm_gap}h ab {calm_start})."
        )
    if label == "ZUNEHMEND":
        return (
            f"WIND-TREND: ZUNEHMEND — Ruhig morgens ({calm_gap}h, bis {calm_end}), "
            f"danach {ac}h Wind (Boden+Hoehe), davon {dc}h DANGER-Level."
        )
    return (
        f"WIND-TREND: VEREINZELT — {ac}h Wind-Phasen (Boden+Hoehe) verteilt "
        f"(davon {dc}h DANGER-Level), laengstes ruhiges Fenster {calm_gap}h "
        f"({calm_start}-{calm_end})."
    )


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
