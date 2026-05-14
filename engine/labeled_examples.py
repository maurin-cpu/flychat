"""
Labeled-Examples-Pool fuer Few-Shot-Pipeline Schritt 1.

Append-only JSONL in data/labeled_examples.jsonl. PATCH/DELETE rewriten die
Datei atomar via .tmp + os.replace, geschuetzt durch fcntl/threading-Lock.

Siehe docs/FEW_SHOT_PIPELINE.md und C:/Users/user/.claude/plans/typed-wandering-truffle.md.
"""

from __future__ import annotations

import csv
import json
import logging
import os
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

import config

logger = logging.getLogger(__name__)

JSONL_PATH = config.DATA_DIR / "labeled_examples.jsonl"
LOCK_PATH = config.DATA_DIR / "labeled_examples.jsonl.lock"
REGIONEN_CSV = config.DATA_DIR / "regionen.csv"

VALID_LABELS = ("richtig", "zu_optimistisch", "zu_pessimistisch")
VALID_SAFETY_STATUS = ("safe", "conditional", "not_safe")
VALID_ENTITY_TYPES = ("region", "spot")

# analysis_id = <kind>_<slug>_<YYYY-MM-DD>. Slug ist lowercase a-z0-9_.
# Kind unterscheidet region vs. spot — beide nutzen denselben Speicher,
# Aggregates und Backstops sind aber kind-spezifisch.
_ANALYSIS_ID_RE = re.compile(r"^(region|spot)_([a-z0-9_]+)_(\d{4}-\d{2}-\d{2})$")
_FOEHN_DECISION_RE = re.compile(r"^Foehn(?:Caution|Danger)\(([\d.]+)\)$")

_module_lock = threading.Lock()

try:
    import fcntl  # POSIX only
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False


# ---------------------------------------------------------------------------
# Lock-Context (Process- + Thread-Safe)
# ---------------------------------------------------------------------------

class _FileLock:
    """fcntl.flock auf Linux, threading.Lock-Fallback auf Windows."""

    def __init__(self, path: Path):
        self.path = path
        self._fh = None

    def __enter__(self):
        _module_lock.acquire()
        if _HAS_FCNTL:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = open(self.path, "a+")
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc, tb):
        if self._fh is not None:
            try:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass
            self._fh.close()
            self._fh = None
        _module_lock.release()


# ---------------------------------------------------------------------------
# Region-Tier-Mapping (aus regionen.csv)
# ---------------------------------------------------------------------------

_TIER_CACHE: dict[str, dict[str, str]] | None = None
_SPOT_META_CACHE: dict[str, dict[str, str]] | None = None  # slug -> meta
_SPOT_SLUG_TO_NAME: dict[str, str] | None = None  # slug -> original site_name


def _load_region_meta() -> dict[str, dict[str, str]]:
    """region_id -> {terrain_type, elevation_ref, kritischer_foehn}. Lazy cached."""
    global _TIER_CACHE
    if _TIER_CACHE is not None:
        return _TIER_CACHE
    meta: dict[str, dict[str, str]] = {}
    try:
        with open(REGIONEN_CSV, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                rid = (row.get("id") or "").strip()
                if not rid:
                    continue
                meta[rid] = {
                    "terrain_type": (row.get("terrain_type") or "").strip(),
                    "elevation_ref": (row.get("elevation_ref") or "").strip(),
                    "kritischer_foehn": (row.get("kritischer_foehn") or "").strip(),
                    "region_name": (row.get("region_name") or "").strip(),
                }
    except FileNotFoundError:
        logger.warning("regionen.csv nicht gefunden: %s", REGIONEN_CSV)
    _TIER_CACHE = meta
    return meta


def slugify_spot(name: str) -> str:
    """site_name -> a-z0-9_-Slug. Mirror in static/js/analysis-view.js halten.

    Umlaute werden expandiert (ae/oe/ue/ss), alle anderen Nicht-Alphanumeric
    werden zu Underscores zusammengezogen.
    """
    if not name:
        return ""
    s = name.lower()
    s = s.replace("\u00e4", "ae").replace("\u00f6", "oe").replace("\u00fc", "ue")
    s = s.replace("\u00df", "ss")
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def _load_spot_meta() -> dict[str, dict[str, str]]:
    """slug -> {site_name, terrain_type, elevation_m, kritischer_foehn}. Lazy cached.

    Quelle: fluggebiete_complete.csv via spots.load_spots() — wir
    importieren lazy um Zirkulaer-Imports zu vermeiden.
    """
    global _SPOT_META_CACHE, _SPOT_SLUG_TO_NAME
    if _SPOT_META_CACHE is not None and _SPOT_SLUG_TO_NAME is not None:
        return _SPOT_META_CACHE
    from spots import load_spots
    meta: dict[str, dict[str, str]] = {}
    slug_to_name: dict[str, str] = {}
    try:
        for spot in load_spots():
            name = spot.get("name") or ""
            slug = slugify_spot(name)
            if not slug:
                continue
            slug_to_name[slug] = name
            meta[slug] = {
                "site_name": name,
                "terrain_type": (spot.get("terrain_type") or "").strip(),
                "elevation_m": str(spot.get("elevation_m") or ""),
                "kritischer_foehn": (spot.get("kritischer_foehn") or "").strip(),
                "analyse_region": (spot.get("analyse_region") or "").strip(),
            }
    except Exception as exc:
        logger.warning("Spot-Meta konnte nicht geladen werden: %s", exc)
    _SPOT_META_CACHE = meta
    _SPOT_SLUG_TO_NAME = slug_to_name
    return meta


def resolve_spot_name(slug: str) -> str | None:
    """Slug -> originaler site_name. None falls unbekannt."""
    _load_spot_meta()
    return (_SPOT_SLUG_TO_NAME or {}).get(slug)


def _terrain_tier_for(kind: str, entity_id: str) -> str:
    if kind == "spot":
        return _load_spot_meta().get(entity_id, {}).get("terrain_type", "")
    return _load_region_meta().get(entity_id, {}).get("terrain_type", "")


def _elevation_for(kind: str, entity_id: str) -> int | None:
    if kind == "spot":
        raw = _load_spot_meta().get(entity_id, {}).get("elevation_m", "")
    else:
        raw = _load_region_meta().get(entity_id, {}).get("elevation_ref", "")
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def _foehn_direction_for(kind: str, entity_id: str) -> str:
    if kind == "spot":
        return _load_spot_meta().get(entity_id, {}).get("kritischer_foehn", "")
    return _load_region_meta().get(entity_id, {}).get("kritischer_foehn", "")


# ---------------------------------------------------------------------------
# Weather-Slice + Aggregates
# ---------------------------------------------------------------------------

def _extract_weather_slice(kind: str, entity_id: str, target_date: str) -> dict[str, Any]:
    """Hourly + pressure-level slice fuer Region oder Spot an einem Datum.

    Liest data/wetterdaten.json frisch (kein In-Memory-Cache, da
    Snapshot-Erzeugung selten). Bei fehlender Entitaet oder fehlendem
    Datum: leerer Slice.

    Region: liegt unter ``_regions[region_id]``. Spot: liegt direkt auf
    Top-Level keyed by site_name — wir resolven Slug -> site_name.
    """
    from fetch_weather import load_cached_weather

    raw = load_cached_weather() or {}
    if kind == "spot":
        site_name = resolve_spot_name(entity_id)
        node = raw.get(site_name) if site_name else None
    else:
        node = (raw.get("_regions") or {}).get(entity_id)
    node = node or {}
    hourly_all = node.get("hourly_data") or {}
    plev_all = node.get("pressure_level_data") or {}

    prefix = f"{target_date}T"
    hourly_day = {ts: v for ts, v in hourly_all.items() if ts.startswith(prefix)}
    plev_day = {ts: v for ts, v in plev_all.items() if ts.startswith(prefix)}

    return {
        "hourly": hourly_day,
        "pressure_levels": plev_day,
    }


def _safe_max(values: list) -> float | None:
    vals = [v for v in values if v is not None]
    return max(vals) if vals else None


def _safe_mean(values: list) -> float | None:
    vals = [v for v in values if v is not None]
    return round(sum(vals) / len(vals), 2) if vals else None


def _parse_foehn_peak(decisions: list[str]) -> float | None:
    """Extrahiert numerischen Foehn-Score aus FoehnCaution/FoehnDanger-Tags."""
    peak: float | None = None
    for tag in decisions or ():
        m = _FOEHN_DECISION_RE.match(str(tag))
        if m:
            try:
                val = float(m.group(1))
                peak = val if peak is None else max(peak, val)
            except ValueError:
                continue
    return peak


def _compute_aggregates(
    slice_: dict[str, Any],
    decisions: list[str],
    kind: str,
    entity_id: str,
) -> dict[str, Any]:
    """11 Aggregat-Felder gemaess Schema. Felder ohne Quelle = None."""
    hourly = slice_.get("hourly") or {}
    plev = slice_.get("pressure_levels") or {}

    def _h_col(name: str) -> list:
        return [h.get(name) for h in hourly.values()]

    def _plev_col(name: str) -> list:
        return [h.get(name) for h in plev.values()]

    wind_10m_vals = _h_col("wind_speed_10m")
    gust_vals = _h_col("wind_gusts_10m")
    gust_excess = []
    for w, g in zip(wind_10m_vals, gust_vals):
        if w is not None and g is not None:
            gust_excess.append(g - w)

    return {
        "wind_10m_max": _safe_max(wind_10m_vals),
        "wind_850hpa_mean": _safe_mean(_plev_col("wind_speed_850hPa")),
        "gust_excess_max": _safe_max(gust_excess),
        "foehn_risk_peak": _parse_foehn_peak(decisions),
        "foehn_direction_dominant": _foehn_direction_for(kind, entity_id) or None,
        "climb_peak": None,
        "productive_thermal_h": None,
        "blh_max": _safe_max(_h_col("boundary_layer_height")),
        "low_cloud_max": _safe_max(_h_col("cloud_cover_low")),
        "mid_cloud_max": _safe_max(_h_col("cloud_cover_mid")),
        "rough_pct": None,
    }


# ---------------------------------------------------------------------------
# Snapshot-Builder
# ---------------------------------------------------------------------------

def parse_analysis_id(analysis_id: str) -> tuple[str, str, str] | None:
    """``<kind>_<slug>_<YYYY-MM-DD>`` -> (kind, slug, date). None bei Mismatch.

    kind ist entweder "region" oder "spot". Backwards-Compat:
    bestehende Eintraege haben `analysis_id = region_<slug>_<date>` und
    matchen weiterhin.
    """
    m = _ANALYSIS_ID_RE.match(analysis_id or "")
    if not m:
        return None
    return m.group(1), m.group(2), m.group(3)


def build_snapshot(
    kind: str,
    entity_id: str,
    target_date: str,
    analysis_entry: dict[str, Any],
    label_payload: dict[str, Any],
) -> dict[str, Any]:
    """Vollstaendiger JSONL-Eintrag.

    Fuer kind="region": analysis_entry kommt aus
    engine.region_analyses[region_id][target_date].
    Fuer kind="spot": aus engine.spot_analyses[site_name][target_date].
    """
    weather = _extract_weather_slice(kind, entity_id, target_date)
    decisions = list(analysis_entry.get("_decisions_applied") or [])
    aggregates = _compute_aggregates(weather, decisions, kind, entity_id)

    analysis_id = f"{kind}_{entity_id}_{target_date}"
    timestamp = datetime.now().isoformat(timespec="seconds")
    model_id = getattr(config, "ANALYSIS_MODEL", "") or "step1-unknown"

    # Fuer Spots speichern wir den originalen site_name als spot_or_region_id,
    # damit Admin-UI + Detail-Modal direkt auflisten/laden koennen.
    if kind == "spot":
        spot_or_region_id = resolve_spot_name(entity_id) or entity_id
    else:
        spot_or_region_id = entity_id

    return {
        "analysis_id": analysis_id,
        "source": "production",
        "timestamp": timestamp,
        "schema_version": "v2.0",
        "model_id": model_id,
        "prompt_hash": "step1-pending",
        "spot_or_region_id": spot_or_region_id,
        "entity_type": kind,
        "entity_slug": entity_id,
        "terrain_tier": _terrain_tier_for(kind, entity_id),
        "target_date": target_date,
        "weather_input": {
            "hourly": weather.get("hourly") or {},
            "aggregates": aggregates,
            "elevation_m": _elevation_for(kind, entity_id),
            "month": int(target_date.split("-")[1]) if "-" in target_date else None,
        },
        "decisions_applied": decisions,
        "llm_output_full": analysis_entry,
        "user_feedback": _build_user_feedback(label_payload),
    }


def _build_user_feedback(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalisiert das eingehende Feedback. Annahme: Validation lief vorher."""
    label = payload.get("label")
    fb: dict[str, Any] = {
        "label": label,
        "correction_text": (payload.get("correction_text") or "")[:500] or None,
        "corrected_experience_rating": None,
        "corrected_safety_status": None,
    }
    if label != "richtig":
        rating = payload.get("corrected_experience_rating")
        if isinstance(rating, int) and 1 <= rating <= 6:
            fb["corrected_experience_rating"] = rating
        status = payload.get("corrected_safety_status")
        if status in VALID_SAFETY_STATUS:
            fb["corrected_safety_status"] = status
    return fb


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_payload(payload: dict[str, Any]) -> tuple[bool, str | None]:
    """Returns (ok, error_message). Erwartet Felder der POST-Payload."""
    analysis_id = payload.get("analysis_id")
    if not parse_analysis_id(analysis_id or ""):
        return False, "analysis_id must match '(region|spot)_<slug>_<YYYY-MM-DD>'"

    label = payload.get("label")
    if label not in VALID_LABELS:
        return False, f"label must be one of {VALID_LABELS}"

    if label != "richtig":
        rating = payload.get("corrected_experience_rating")
        rating_ok = isinstance(rating, int) and 1 <= rating <= 6
        status = payload.get("corrected_safety_status")
        status_ok = status in VALID_SAFETY_STATUS
        if not (rating_ok or status_ok):
            return False, ("corrected_experience_rating (1-6) or "
                           "corrected_safety_status required for correction labels")

    return True, None


def validate_patch(payload: dict[str, Any]) -> tuple[bool, str | None]:
    """PATCH: zumindest eines der Felder muss da sein und valide."""
    if "label" in payload and payload["label"] not in VALID_LABELS:
        return False, f"label must be one of {VALID_LABELS}"
    if "corrected_experience_rating" in payload:
        r = payload["corrected_experience_rating"]
        if r is not None and not (isinstance(r, int) and 1 <= r <= 6):
            return False, "corrected_experience_rating must be int 1..6 or null"
    if "corrected_safety_status" in payload:
        s = payload["corrected_safety_status"]
        if s is not None and s not in VALID_SAFETY_STATUS:
            return False, f"corrected_safety_status must be one of {VALID_SAFETY_STATUS} or null"
    return True, None


# ---------------------------------------------------------------------------
# Storage (read/write)
# ---------------------------------------------------------------------------

def load_all() -> list[dict[str, Any]]:
    """Alle Eintraege lesen. Beschaedigte Zeilen werden uebersprungen + geloggt."""
    if not JSONL_PATH.exists():
        return []
    entries: list[dict[str, Any]] = []
    with open(JSONL_PATH, encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError as exc:
                logger.warning("Beschaedigte JSONL-Zeile %d uebersprungen: %s",
                               line_no, exc)
    return entries


def load_by_id(analysis_id: str) -> dict[str, Any] | None:
    for entry in load_all():
        if entry.get("analysis_id") == analysis_id:
            return entry
    return None


def _atomic_write_all(entries: list[dict[str, Any]]) -> None:
    """Schreibt die komplette Liste atomar via .tmp + os.replace."""
    JSONL_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = JSONL_PATH.with_suffix(".jsonl.tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        for entry in entries:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    os.replace(tmp_path, JSONL_PATH)


def append_or_replace(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Eintrag anlegen oder ersetzen (Dedup ueber analysis_id).

    Liest die ganze Datei, filtert den alten Eintrag raus, schreibt alles
    neu via Atomic-Replace. Genug fuer <10 MB Pool-Groesse.
    """
    analysis_id = snapshot.get("analysis_id")
    with _FileLock(LOCK_PATH):
        existing = load_all()
        kept = [e for e in existing if e.get("analysis_id") != analysis_id]
        kept.append(snapshot)
        _atomic_write_all(kept)
    return snapshot


def patch_entry(analysis_id: str, changes: dict[str, Any]) -> dict[str, Any] | None:
    """Patcht den user_feedback-Block eines bestehenden Eintrags."""
    with _FileLock(LOCK_PATH):
        entries = load_all()
        updated: dict[str, Any] | None = None
        for e in entries:
            if e.get("analysis_id") != analysis_id:
                continue
            fb = dict(e.get("user_feedback") or {})
            if "label" in changes:
                fb["label"] = changes["label"]
            if "corrected_experience_rating" in changes:
                fb["corrected_experience_rating"] = changes["corrected_experience_rating"]
            if "corrected_safety_status" in changes:
                fb["corrected_safety_status"] = changes["corrected_safety_status"]
            if "correction_text" in changes:
                txt = changes["correction_text"]
                fb["correction_text"] = (txt or "")[:500] or None
            e["user_feedback"] = fb
            e["timestamp"] = datetime.now().isoformat(timespec="seconds")
            updated = e
            break
        if updated is None:
            return None
        _atomic_write_all(entries)
    return updated


def delete_entry(analysis_id: str) -> bool:
    with _FileLock(LOCK_PATH):
        entries = load_all()
        kept = [e for e in entries if e.get("analysis_id") != analysis_id]
        if len(kept) == len(entries):
            return False
        _atomic_write_all(kept)
    return True
