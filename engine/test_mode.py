"""
Test-Mode-Helper.

Stellt drei Schichten bereit:

1. **Frozen Weather** — Snapshot der aktuellen `data/wetterdaten.json` als
   Mock-Datei in `data/mocks/wetterdaten.json`. Wird als Eingabe fuer
   Test-Analysen verwendet, damit man nicht jedes Mal die Open-Meteo API
   schlagen muss.

2. **Test-Run-Output** — Test-Analysen schreiben nach
   `data/test_runs/latest/spot_analyses.json` und `region_analyses.json`,
   damit Prod-Files unangetastet bleiben.

3. **View-Toggle** — Wenn `TEST_VIEW_ACTIVE` gesetzt, serviert das Frontend
   (`/api/analyses`, `/api/region-analyses`) aus dem Test-Run-Ordner statt
   aus den Prod-Files. Persistiert in `data/test_mode.json`.

Der Test-Run-Orchestrator (`run_test_analyses_stream`) nutzt einen
Snapshot/Restore-Pattern auf der Engine-Instanz, sodass nach dem Lauf
keine Test-Daten in der Live-Engine zurueckbleiben.
"""

from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterator

import config

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pfade
# ---------------------------------------------------------------------------

MOCKS_DIR: Path = config.DATA_DIR / "mocks"
FROZEN_WEATHER_PATH: Path = MOCKS_DIR / "wetterdaten.json"
FROZEN_META_PATH: Path = MOCKS_DIR / "_meta.json"

TEST_RUNS_DIR: Path = config.DATA_DIR / "test_runs"
TEST_RUN_LATEST_DIR: Path = TEST_RUNS_DIR / "latest"
TEST_RUN_SPOT_ANALYSES_PATH: Path = TEST_RUN_LATEST_DIR / "spot_analyses.json"
TEST_RUN_REGION_ANALYSES_PATH: Path = TEST_RUN_LATEST_DIR / "region_analyses.json"
TEST_RUN_META_PATH: Path = TEST_RUN_LATEST_DIR / "_meta.json"

STATE_PATH: Path = config.DATA_DIR / "test_mode.json"

TEST_CSV_PATH: Path = config.DATA_DIR / "fluggebiete_test.csv"


# ---------------------------------------------------------------------------
# State (View-Toggle)
# ---------------------------------------------------------------------------

def _read_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("test_mode state konnte nicht gelesen werden: %s", e)
        return {}


def _write_state(state: dict[str, Any]) -> None:
    config.atomic_write_json(STATE_PATH, state)


def is_view_active() -> bool:
    """Liefert True, wenn das Frontend aus dem Test-Run-Ordner servieren soll."""
    return bool(_read_state().get("view_active", False))


def set_view_active(active: bool) -> dict[str, Any]:
    state = _read_state()
    state["view_active"] = bool(active)
    state["set_at"] = datetime.now().isoformat(timespec="seconds")
    _write_state(state)
    logger.info("Test-View-Toggle: view_active=%s", active)
    return state


# ---------------------------------------------------------------------------
# Frozen Weather
# ---------------------------------------------------------------------------

def frozen_weather_exists() -> bool:
    return FROZEN_WEATHER_PATH.exists()


def frozen_weather_meta() -> dict[str, Any] | None:
    """Meta-Info zum aktuell eingefrorenen Wetter-Snapshot. None falls nicht vorhanden."""
    if not FROZEN_META_PATH.exists():
        return None
    try:
        with open(FROZEN_META_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def frozen_base_date() -> date | None:
    """Snapshot-Datum (= source_run_at) als date. Anchor fuer "Heute" im Test-Modus.

    Wird sowohl beim Test-Lauf (`_get_forecast_dates`-Patch) als auch im
    Frontend-Filter (`/api/analyses` + `/api/region-analyses`) verwendet,
    damit die Test-Ansicht zeitlich eingefroren bleibt. None wenn kein
    Snapshot oder source_run_at fehlt/ungueltig.
    """
    meta = frozen_weather_meta()
    if not meta:
        return None
    raw = meta.get("source_run_at") or meta.get("frozen_at")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:
        return None


def freeze_current_weather(spot_set: str = "test") -> dict[str, Any]:
    """Kopiert Wetterdaten aus `wetterdaten.json` nach `data/mocks/`.

    Args:
        spot_set: "test" (default, nur Spots aus `fluggebiete_test.csv`, ~28 Spots,
            ~22 MB) oder "complete" (alle Spots, ~487, ~380 MB).

    Regionen (`_regions`) und `_meta` bleiben in beiden Modi vollstaendig erhalten.
    Wirft FileNotFoundError, wenn keine aktuellen Wetterdaten vorhanden sind.
    Wirft ValueError bei unbekanntem spot_set.
    """
    if spot_set not in ("test", "complete"):
        raise ValueError(f"Ungueltiges spot_set: {spot_set!r} (erlaubt: 'test', 'complete')")

    src = config.WEATHER_JSON_PATH
    if not src.exists():
        raise FileNotFoundError(f"Keine Wetterdaten zum Einfrieren gefunden: {src}")

    MOCKS_DIR.mkdir(parents=True, exist_ok=True)

    with open(src, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError(f"wetterdaten.json hat unerwartetes Format: {type(data).__name__}")

    test_names = load_test_spot_names()
    total_source_spots = sum(1 for k in data.keys() if not k.startswith("_"))

    if spot_set == "test":
        # Filter: nur Test-Spots + alle `_*`-Specials (`_regions`, `_meta`, ...)
        filtered: dict[str, Any] = {
            k: v for k, v in data.items()
            if k.startswith("_") or k in test_names
        }
        missing = sorted(test_names - set(filtered.keys()))
    else:
        filtered = dict(data)
        missing = []
    kept_spots = sum(1 for k in filtered.keys() if not k.startswith("_"))

    regions = filtered.get("_regions") or {}
    regions_count = len(regions) if isinstance(regions, dict) else 0
    src_meta = filtered.get("_meta") or {}
    source_run_at = src_meta.get("last_updated") or src_meta.get("generated_at") if isinstance(src_meta, dict) else None

    # `_meta.spots_count` an Realitaet anpassen, damit Konsumenten nicht denken
    # da seien (un)gefilterte Spots drin.
    if isinstance(src_meta, dict):
        src_meta = dict(src_meta)
        src_meta["spots_count"] = kept_spots
        src_meta["filtered_from_total"] = total_source_spots
        filtered["_meta"] = src_meta

    config.atomic_write_json(FROZEN_WEATHER_PATH, filtered)

    meta: dict[str, Any] = {
        "frozen_at": datetime.now().isoformat(timespec="seconds"),
        "source_run_at": source_run_at,
        "source_path": str(src),
        "spot_set": spot_set,
        "spot_count": kept_spots,
        "region_count": regions_count,
        "total_source_spots": total_source_spots,
        "test_set_size": len(test_names),
        "missing_test_spots": missing,
    }
    config.atomic_write_json(FROZEN_META_PATH, meta)
    logger.info(
        "Frozen Weather (%s) geschrieben: %s (%d Spots, %d Regionen, gefiltert aus %d Source-Spots)",
        spot_set, FROZEN_WEATHER_PATH, kept_spots, regions_count, total_source_spots,
    )
    return meta


def discard_frozen_weather() -> bool:
    """Loescht den eingefrorenen Snapshot + Meta. Gibt True zurueck wenn etwas geloescht wurde."""
    deleted = False
    for p in (FROZEN_WEATHER_PATH, FROZEN_META_PATH):
        if p.exists():
            try:
                p.unlink()
                deleted = True
            except OSError as e:
                logger.warning("Konnte %s nicht loeschen: %s", p, e)
    if deleted:
        logger.info("Frozen Weather verworfen.")
    return deleted


# ---------------------------------------------------------------------------
# Test-Run-Output
# ---------------------------------------------------------------------------

def test_run_meta() -> dict[str, Any] | None:
    """Meta zum letzten Test-Lauf. None falls noch nie gelaufen."""
    if not TEST_RUN_META_PATH.exists():
        return None
    try:
        with open(TEST_RUN_META_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def ensure_test_run_dir() -> Path:
    TEST_RUN_LATEST_DIR.mkdir(parents=True, exist_ok=True)
    return TEST_RUN_LATEST_DIR


def write_test_run_meta(meta: dict[str, Any]) -> None:
    ensure_test_run_dir()
    config.atomic_write_json(TEST_RUN_META_PATH, meta)


def load_test_run_analyses() -> tuple[dict[str, Any], dict[str, Any], datetime | None]:
    """Liest spot_analyses + region_analyses aus dem Test-Run-Ordner.

    Returns: (spot_analyses, region_analyses, mtime). Leere Dicts wenn die
    jeweilige Datei nicht existiert. mtime ist die juengere von beiden.
    """
    spot_data: dict[str, Any] = {}
    region_data: dict[str, Any] = {}
    mtimes: list[float] = []
    for path, target in (
        (TEST_RUN_SPOT_ANALYSES_PATH, "spot"),
        (TEST_RUN_REGION_ANALYSES_PATH, "region"),
    ):
        if not path.exists():
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                if target == "spot":
                    spot_data = data
                else:
                    region_data = data
            mtimes.append(path.stat().st_mtime)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Test-Run-Datei %s konnte nicht gelesen werden: %s", path, e)
    mtime = datetime.fromtimestamp(max(mtimes)) if mtimes else None
    return spot_data, region_data, mtime


def load_frozen_weather() -> dict[str, Any]:
    """Laedt den Frozen-Snapshot. Wirft FileNotFoundError, wenn nicht vorhanden."""
    if not FROZEN_WEATHER_PATH.exists():
        raise FileNotFoundError(f"Kein Frozen-Snapshot: {FROZEN_WEATHER_PATH}")
    with open(FROZEN_WEATHER_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Test-Spots-Filter
# ---------------------------------------------------------------------------

def load_test_spot_names() -> set[str]:
    """Liest die Spot-Namen aus `data/fluggebiete_test.csv`.

    Spalte `site_name` wird als Identifier verwendet (gleicher Key wie in
    `wetterdaten.json` und in den Analyse-Dicts).
    """
    if not TEST_CSV_PATH.exists():
        logger.warning("Test-CSV nicht gefunden: %s", TEST_CSV_PATH)
        return set()
    import csv
    names: set[str] = set()
    try:
        with open(TEST_CSV_PATH, "r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = (row.get("site_name") or "").strip()
                if name:
                    names.add(name)
    except (OSError, csv.Error) as e:
        logger.warning("Konnte Test-CSV nicht lesen: %s", e)
    return names


# ---------------------------------------------------------------------------
# Status-Bundle (fuer UI)
# ---------------------------------------------------------------------------

def run_test_analyses_stream(
    engine,
    *,
    use_frozen_input: bool,
    spot_set: str = "test",
    n_days: int | None = None,
) -> Iterator[dict[str, Any]]:
    """Stream-Generator fuer einen Test-Lauf mit isoliertem Output.

    Filtert die Spots (default: nur `fluggebiete_test.csv`), leitet die
    Output-Pfade auf `data/test_runs/latest/` um, und (optional) ersetzt das
    Live-Wetter durch den Frozen-Snapshot. Restauriert den Engine-State nach
    dem Lauf — egal ob Erfolg oder Fehler.

    Args:
        engine: WingcastEngine-Instanz (typischerweise das globale `engine` aus web.py).
        use_frozen_input: True = Frozen-Snapshot laden; False = aktuell geladene
            `engine.weather_data` weiterverwenden.
        spot_set: "test" (default, ~28 Spots aus fluggebiete_test.csv) oder
            "complete" (alle Spots). "complete" + use_frozen_input ist verboten,
            weil der Frozen-Snapshot nur Test-Spots enthaelt.
        n_days: Begrenzt die Anzahl Vorhersagetage (1..config.FORECAST_DAYS).
            None = unveraendert (alle Tage). Patched `_get_forecast_dates` auf
            der Engine-Instanz fuer die Dauer des Laufs.

    Yields die SSE-Events von `engine.run_all_analyses_stream()` plus zwei
    eigene Events am Anfang/Ende: `test_init` und `test_done`.
    """
    if spot_set not in ("test", "complete"):
        yield {"event": "error",
               "data": {"message": f"Ungueltiges spot_set: {spot_set!r} (erlaubt: 'test', 'complete')"}}
        return
    if spot_set == "complete" and use_frozen_input:
        fw_meta = frozen_weather_meta() or {}
        if fw_meta.get("spot_set") != "complete":
            yield {"event": "error",
                   "data": {"message": "Komplett-Set + Frozen-Snapshot nicht moeglich — der vorhandene Snapshot ist nur das Test-Set. Bitte zuerst einen Komplett-Snapshot einfrieren oder 'Live API' waehlen."}}
            return
    if n_days is not None:
        if not isinstance(n_days, int) or n_days < 1 or n_days > config.FORECAST_DAYS:
            yield {"event": "error",
                   "data": {"message": f"Ungueltiges n_days={n_days!r} (erlaubt: 1..{config.FORECAST_DAYS})"}}
            return

    snapshot = {
        # analyses_file/region_analyses_file sind sprach-dynamische Properties mit
        # Override-Setter. Test-Mode setzt unten einen Test-Pfad-Override; Restore =
        # None -> Property rechnet wieder aus dem aktiven LANG-Cache (kein Pinnen).
        "analyses_file": None,
        "region_analyses_file": None,
        "spots": engine.spots,
        "weather_data": engine.weather_data,
        "region_weather_data": engine.region_weather_data,
        "spot_analyses": engine.spot_analyses,
        "region_analyses": engine.region_analyses,
        "weather_context_str": getattr(engine, "weather_context_str", None),
        "_get_forecast_dates": engine._get_forecast_dates,
    }

    started_at = datetime.now()
    try:
        ensure_test_run_dir()
        engine.analyses_file = TEST_RUN_SPOT_ANALYSES_PATH
        engine.region_analyses_file = TEST_RUN_REGION_ANALYSES_PATH

        if use_frozen_input:
            if not frozen_weather_exists():
                yield {"event": "error",
                       "data": {"message": "Kein Frozen-Snapshot vorhanden. Bitte erst einfrieren."}}
                return
            try:
                cached = load_frozen_weather()
            except (json.JSONDecodeError, OSError) as e:
                yield {"event": "error",
                       "data": {"message": f"Frozen-Snapshot fehlerhaft: {e}"}}
                return
            engine.weather_data = cached
            engine.region_weather_data = cached.pop("_regions", {}) if "_regions" in cached else {}
            try:
                engine.weather_context_str = engine._build_weather_context()
            except Exception:
                logger.exception("weather_context Rebuild aus Frozen-Snapshot fehlgeschlagen")

        # Spot-Set anwenden
        if spot_set == "test":
            test_names = load_test_spot_names()
            if not test_names:
                yield {"event": "error",
                       "data": {"message": "Test-Spot-Liste leer (data/fluggebiete_test.csv)."}}
                return
            engine.spots = [s for s in snapshot["spots"] if s.get("name") in test_names]
            if engine.weather_data:
                engine.weather_data = {
                    k: v for k, v in engine.weather_data.items()
                    if k.startswith("_") or k in test_names
                }
        # spot_set == "complete": kein Filter — engine.spots/weather_data bleiben

        # Datums-Anker: Wenn Frozen-Snapshot verwendet wird, soll "Heute" das
        # source_run_at-Datum sein (sonst analysieren wir Tage, fuer die der
        # Snapshot keine Wetterdaten hat). Bei Live-Input bleibt heute = heute.
        base_date: date | None = frozen_base_date() if use_frozen_input else None
        days_limit = n_days if n_days is not None else config.FORECAST_DAYS
        if base_date is not None:
            engine._get_forecast_dates = lambda: [
                (base_date + timedelta(days=i)).strftime("%Y-%m-%d")
                for i in range(days_limit)
            ]
        elif n_days is not None:
            original_dates = snapshot["_get_forecast_dates"]
            engine._get_forecast_dates = lambda: original_dates()[:n_days]

        n_spots = len(engine.spots)
        n_regions = len(engine.region_weather_data) if engine.region_weather_data else 0
        n_days_effective = len(engine._get_forecast_dates() or [])

        yield {"event": "test_init", "data": {
            "n_spots": n_spots,
            "n_regions": n_regions,
            "n_days": n_days_effective,
            "spot_set": spot_set,
            "use_frozen_weather": use_frozen_input,
            "started_at": started_at.isoformat(timespec="seconds"),
        }}

        if n_spots == 0:
            msg = ("Keine Test-Spots im Wetter-Datensatz gefunden — Frozen-Snapshot zu Test-CSV inkompatibel?"
                   if spot_set == "test"
                   else "Keine Spots im Wetter-Datensatz gefunden — Live-Wetter geladen?")
            yield {"event": "error", "data": {"message": msg}}
            return

        engine.spot_analyses = {}
        engine.region_analyses = {}

        yield from engine.run_all_analyses_stream()

        write_test_run_meta({
            "run_at": started_at.isoformat(timespec="seconds"),
            "completed_at": datetime.now().isoformat(timespec="seconds"),
            "used_frozen_weather": use_frozen_input,
            "spot_set": spot_set,
            "n_spots": n_spots,
            "n_regions": n_regions,
            "n_days": n_days_effective,
        })
        yield {"event": "test_done", "data": {
            "n_spots": n_spots, "n_regions": n_regions, "n_days": n_days_effective,
        }}
    finally:
        for k, v in snapshot.items():
            setattr(engine, k, v)


# ---------------------------------------------------------------------------
# Goldstandard / Regression-Reports / Review-Queue
# ---------------------------------------------------------------------------

_COST_TESTING_DIR: Path = Path(__file__).resolve().parent.parent / "cost_testing"
GOLDEN_DIR: Path = _COST_TESTING_DIR / "golden"
REPORTS_DIR: Path = _COST_TESTING_DIR / "reports"
REVIEW_QUEUE_DIR: Path = _COST_TESTING_DIR / "review_queue"
FREEZE_GOLDEN_SCRIPT: Path = _COST_TESTING_DIR / "freeze_golden.py"
SCORE_REGRESSION_SCRIPT: Path = _COST_TESTING_DIR / "score_regression.py"

REVIEW_DEFAULT_SAMPLE_SIZE = 10


def golden_summary() -> dict[str, Any]:
    """Anzahl Cases + juengstes mtime im Goldstandard-Ordner."""
    if not GOLDEN_DIR.exists():
        return {"count": 0, "newest": None}
    cases = list(GOLDEN_DIR.glob("spot_*.json"))
    if not cases:
        return {"count": 0, "newest": None}
    newest = max(cases, key=lambda p: p.stat().st_mtime)
    return {
        "count": len(cases),
        "newest": datetime.fromtimestamp(newest.stat().st_mtime).isoformat(timespec="seconds"),
    }


def list_reports(limit: int = 30) -> list[dict[str, Any]]:
    """Listet Regression-Reports in `cost_testing/reports/`, neueste zuerst."""
    if not REPORTS_DIR.exists():
        return []
    files = sorted(
        REPORTS_DIR.glob("*.md"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )[:limit]
    out = []
    for p in files:
        # Erste Zeile des Reports als Vorschau (typischerweise "# Titel ... PASS/FAIL")
        first_line = ""
        try:
            with open(p, "r", encoding="utf-8") as f:
                first_line = (f.readline() or "").strip().lstrip("# ").strip()
        except OSError:
            pass
        out.append({
            "name": p.name,
            "stem": p.stem,
            "mtime": datetime.fromtimestamp(p.stat().st_mtime).isoformat(timespec="seconds"),
            "size_kb": round(p.stat().st_size / 1024.0, 1),
            "first_line": first_line[:120],
        })
    return out


def read_report(name: str) -> str | None:
    """Liest einen Report-Text. None wenn der Name ungueltig ist (Path-Traversal-Schutz)."""
    safe = Path(name).name
    if safe != name or not safe.endswith(".md"):
        return None
    p = REPORTS_DIR / safe
    if not p.exists() or not p.is_file():
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


# ---------------------------------------------------------------------------
# Review-Queue
# ---------------------------------------------------------------------------
#
# Datenfluss:
#   1. score_regression.py wird mit --queue-output PATH aufgerufen → schreibt
#      eine JSON mit allen Diff-Cases (input, gold_output, current_output, severities).
#   2. start_review_session(queue_json_path, sample_size) liest diese Datei,
#      wendet Stratified Sampling an, schreibt eine Session-Datei nach
#      `cost_testing/review_queue/<session_id>.json`.
#   3. UI rendert die Session, der User klickt pro Case "besser/gleich/schlechter".
#      save_verdict() persistiert in derselben Session-Datei.
#   4. finalize_session() aggregiert Verdicts → PASS/FAIL.
#   5. promote_to_gold() ueberschreibt Goldstandard-Files mit den neuen Outputs
#      fuer Cases, die als "besser" markiert wurden.

VERDICT_BETTER = "better"
VERDICT_SAME = "same"
VERDICT_WORSE = "worse"
_VALID_VERDICTS = (VERDICT_BETTER, VERDICT_SAME, VERDICT_WORSE)

# Anteil "besser+gleich" der reviewten Stichprobe, ab dem die Session als PASS gilt.
REVIEW_PASS_THRESHOLD = 0.80
# Anteil "schlechter", ab dem die Session als FAIL gilt.
REVIEW_FAIL_THRESHOLD = 0.20


def _stratified_sample(diff_cases: list[dict[str, Any]], sample_size: int) -> list[dict[str, Any]]:
    """Waehlt eine Stichprobe aus den Diff-Cases.

    Regeln:
    - Alle `kritisch`-Cases werden zwingend aufgenommen (Sicherheitskritisch).
    - Restliche Slots werden stratifiziert nach `gold_safety_status` aufgefuellt
      (max 2 pro Bucket safe/conditional/not_safe), Rest random.
    """
    if not diff_cases or sample_size <= 0:
        return []

    selected: list[dict[str, Any]] = []
    seen_keys: set[tuple[str, str]] = set()

    def _key(c: dict[str, Any]) -> tuple[str, str]:
        return (c.get("spot", ""), c.get("date", ""))

    # 1. Pflicht: alle kritischen Diffs
    for c in diff_cases:
        if c.get("max_severity") == "kritisch":
            k = _key(c)
            if k not in seen_keys:
                selected.append(c)
                seen_keys.add(k)
    if len(selected) >= sample_size:
        return selected[:sample_size]

    # 2. Stratifiziert: max 2 pro safety_status-Bucket
    buckets: dict[str, list[dict[str, Any]]] = {}
    for c in diff_cases:
        if _key(c) in seen_keys:
            continue
        bucket = c.get("gold_safety_status") or "unknown"
        buckets.setdefault(bucket, []).append(c)

    for bucket_name, items in buckets.items():
        for c in items[:2]:
            if len(selected) >= sample_size:
                return selected
            k = _key(c)
            if k not in seen_keys:
                selected.append(c)
                seen_keys.add(k)

    # 3. Auffuellen mit Rest (nach max_severity sortiert: hoch > mittel)
    remaining = [c for c in diff_cases if _key(c) not in seen_keys]
    sev_rank = {"kritisch": 0, "hoch": 1, "mittel": 2, "info": 3}
    remaining.sort(key=lambda c: sev_rank.get(c.get("max_severity", "info"), 9))
    for c in remaining:
        if len(selected) >= sample_size:
            break
        selected.append(c)
        seen_keys.add(_key(c))

    return selected


def start_review_session(queue_json_path: Path, sample_size: int = REVIEW_DEFAULT_SAMPLE_SIZE) -> dict[str, Any]:
    """Liest eine queue-JSON-Datei (Output von score_regression.py --queue-output)
    und erzeugt eine Review-Session.

    Returns: dict mit `session_id` + `session_path` + `n_cases` + `n_total_diffs`.
    Wirft FileNotFoundError, wenn die queue-Datei nicht existiert oder leer ist.
    """
    if not queue_json_path.exists():
        raise FileNotFoundError(f"Queue-Datei nicht vorhanden: {queue_json_path}")
    with open(queue_json_path, "r", encoding="utf-8") as f:
        queue = json.load(f)

    diff_cases = queue.get("cases") or []
    if not diff_cases:
        raise ValueError("Queue-Datei enthaelt keine Diff-Cases — nichts zu reviewen.")

    sampled = _stratified_sample(diff_cases, sample_size)

    REVIEW_QUEUE_DIR.mkdir(parents=True, exist_ok=True)
    session_id = "rv_" + datetime.now().strftime("%Y-%m-%d_%H%M%S")
    session_path = REVIEW_QUEUE_DIR / f"{session_id}.json"

    session: dict[str, Any] = {
        "session_id": session_id,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "queue_source": str(queue_json_path),
        "report_path": queue.get("report_path"),
        "regression_mode": queue.get("mode"),
        "regression_summary": {
            "total_cases": queue.get("total_cases"),
            "diff_count": queue.get("diff_count"),
            "crit_regressions": queue.get("crit_regressions"),
            "high_regressions": queue.get("high_regressions"),
            "score_pct": queue.get("score_pct"),
            "gate_ok": queue.get("gate_ok"),
        },
        "sample_size": len(sampled),
        "total_diffs": len(diff_cases),
        "finalized_at": None,
        "verdict": None,
        "cases": [],
    }
    for idx, c in enumerate(sampled):
        session["cases"].append({
            "idx": idx,
            "spot": c.get("spot"),
            "date": c.get("date"),
            "max_severity": c.get("max_severity"),
            "fail_fields": c.get("fail_fields") or [],
            "gold_safety_status": c.get("gold_safety_status"),
            "current_safety_status": c.get("current_safety_status"),
            "input": c.get("input"),
            "gold_output": c.get("gold_output"),
            "current_output": c.get("current_output"),
            "weather_snapshot": c.get("weather_snapshot") or {},
            "case_path": c.get("case_path"),
            "verdict": None,
            "comment": "",
            "reviewed_at": None,
        })

    config.atomic_write_json(session_path, session)
    logger.info("Review-Session gestartet: %s (%d von %d Diffs)",
                session_id, len(sampled), len(diff_cases))
    return {
        "session_id": session_id,
        "session_path": str(session_path),
        "n_cases": len(sampled),
        "n_total_diffs": len(diff_cases),
    }


def load_review_session(session_id: str) -> dict[str, Any] | None:
    """Liest eine Review-Session. None wenn ungueltig (Path-Traversal-Schutz)."""
    safe = Path(session_id).name
    if safe != session_id or not safe.startswith("rv_"):
        return None
    p = REVIEW_QUEUE_DIR / f"{safe}.json"
    if not p.exists():
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else None
    except (json.JSONDecodeError, OSError):
        return None


def _save_review_session(session: dict[str, Any]) -> None:
    sid = session["session_id"]
    p = REVIEW_QUEUE_DIR / f"{sid}.json"
    config.atomic_write_json(p, session)


def save_verdict(session_id: str, case_idx: int, verdict: str, comment: str = "") -> dict[str, Any]:
    """Speichert ein Verdict fuer einen Case in einer Session.

    Wirft ValueError bei ungueltigem session_id, case_idx oder verdict.
    """
    if verdict not in _VALID_VERDICTS:
        raise ValueError(f"Verdict muss in {_VALID_VERDICTS} sein, war: {verdict!r}")
    session = load_review_session(session_id)
    if session is None:
        raise ValueError(f"Session nicht gefunden: {session_id}")
    cases = session.get("cases") or []
    if not (0 <= case_idx < len(cases)):
        raise ValueError(f"case_idx {case_idx} ausserhalb [0,{len(cases)})")
    cases[case_idx]["verdict"] = verdict
    cases[case_idx]["comment"] = (comment or "").strip()[:500]
    cases[case_idx]["reviewed_at"] = datetime.now().isoformat(timespec="seconds")
    _save_review_session(session)
    return cases[case_idx]


def finalize_session(session_id: str) -> dict[str, Any]:
    """Aggregiert alle Verdicts der Session zu einem Gesamtergebnis.

    Returns: {
        verdict: "PASS" | "FAIL" | "AMBIGUOUS",
        n_better, n_same, n_worse, n_unreviewed,
        better_pct, worse_pct,
        rationale: str,
    }
    """
    session = load_review_session(session_id)
    if session is None:
        raise ValueError(f"Session nicht gefunden: {session_id}")
    cases = session.get("cases") or []
    if not cases:
        raise ValueError("Session hat keine Cases.")

    n_better = sum(1 for c in cases if c.get("verdict") == VERDICT_BETTER)
    n_same = sum(1 for c in cases if c.get("verdict") == VERDICT_SAME)
    n_worse = sum(1 for c in cases if c.get("verdict") == VERDICT_WORSE)
    n_unreviewed = sum(1 for c in cases if c.get("verdict") is None)
    n_total = len(cases)

    # Wenn noch Cases unrevidiert sind, koennen wir nicht final sagen
    if n_unreviewed > 0:
        return {
            "verdict": "INCOMPLETE",
            "n_better": n_better, "n_same": n_same, "n_worse": n_worse,
            "n_unreviewed": n_unreviewed, "n_total": n_total,
            "better_pct": 0.0, "worse_pct": 0.0,
            "rationale": f"{n_unreviewed} von {n_total} Cases noch nicht reviewt.",
        }

    better_or_same_pct = (n_better + n_same) / n_total
    worse_pct = n_worse / n_total

    if worse_pct >= REVIEW_FAIL_THRESHOLD:
        verdict = "FAIL"
        rationale = (f"{n_worse}/{n_total} Cases als schlechter bewertet "
                     f"({worse_pct:.0%} >= {REVIEW_FAIL_THRESHOLD:.0%} FAIL-Schwelle).")
    elif better_or_same_pct >= REVIEW_PASS_THRESHOLD:
        verdict = "PASS"
        rationale = (f"{n_better} besser + {n_same} gleich = "
                     f"{better_or_same_pct:.0%} >= {REVIEW_PASS_THRESHOLD:.0%} PASS-Schwelle.")
    else:
        verdict = "AMBIGUOUS"
        rationale = ("Knapp unter PASS-Schwelle und ueber FAIL-Schwelle. "
                     "Empfehlung: weitere Stichprobe ziehen.")

    session["verdict"] = verdict
    session["finalized_at"] = datetime.now().isoformat(timespec="seconds")
    _save_review_session(session)

    return {
        "verdict": verdict,
        "n_better": n_better, "n_same": n_same, "n_worse": n_worse,
        "n_unreviewed": 0, "n_total": n_total,
        "better_pct": round(better_or_same_pct, 3),
        "worse_pct": round(worse_pct, 3),
        "rationale": rationale,
    }


def promote_to_gold(session_id: str) -> dict[str, Any]:
    """Aktualisiert den Goldstandard mit den neuen Outputs aller Cases, die als
    `better` reviewt wurden. Cases mit `same` oder `worse` bleiben unangetastet.

    Returns: {n_promoted, n_skipped, errors: [...]}
    """
    session = load_review_session(session_id)
    if session is None:
        raise ValueError(f"Session nicht gefunden: {session_id}")
    if session.get("verdict") not in ("PASS", "AMBIGUOUS"):
        raise ValueError(f"Promote nur erlaubt wenn Session PASS/AMBIGUOUS ist, war: {session.get('verdict')}")

    n_promoted = 0
    n_skipped = 0
    errors: list[str] = []

    for case in session.get("cases") or []:
        if case.get("verdict") != VERDICT_BETTER:
            n_skipped += 1
            continue
        case_path_str = case.get("case_path")
        if not case_path_str:
            errors.append(f"Case {case.get('spot')}/{case.get('date')}: keine case_path")
            continue
        case_path = Path(case_path_str)
        if not case_path.exists():
            errors.append(f"Goldstandard-Datei nicht mehr da: {case_path}")
            continue
        try:
            with open(case_path, "r", encoding="utf-8") as f:
                gold_record = json.load(f)
            gold_record["output"] = case.get("current_output") or {}
            gold_record["promoted_at"] = datetime.now().isoformat(timespec="seconds")
            gold_record["promoted_from_session"] = session_id
            config.atomic_write_json(case_path, gold_record)
            n_promoted += 1
        except (OSError, json.JSONDecodeError) as e:
            errors.append(f"{case_path.name}: {e}")

    # Markieren in der Session
    session["promoted_at"] = datetime.now().isoformat(timespec="seconds")
    session["promoted_count"] = n_promoted
    _save_review_session(session)

    logger.info("Review-Session %s: %d Cases promoted, %d skipped, %d errors",
                session_id, n_promoted, n_skipped, len(errors))
    return {"n_promoted": n_promoted, "n_skipped": n_skipped, "errors": errors}


def list_review_sessions(limit: int = 20) -> list[dict[str, Any]]:
    """Listet Review-Sessions, neueste zuerst."""
    if not REVIEW_QUEUE_DIR.exists():
        return []
    files = sorted(
        REVIEW_QUEUE_DIR.glob("rv_*.json"),
        key=lambda p: p.stat().st_mtime, reverse=True,
    )[:limit]
    out = []
    for p in files:
        try:
            with open(p, "r", encoding="utf-8") as f:
                s = json.load(f)
            cases = s.get("cases") or []
            n_reviewed = sum(1 for c in cases if c.get("verdict") is not None)
            out.append({
                "session_id": s.get("session_id"),
                "created_at": s.get("created_at"),
                "n_cases": len(cases),
                "n_reviewed": n_reviewed,
                "verdict": s.get("verdict"),
                "promoted_count": s.get("promoted_count"),
            })
        except (OSError, json.JSONDecodeError):
            continue
    return out


def latest_queue_json() -> Path | None:
    """Findet die juengste *_queue.json in REPORTS_DIR (geschrieben von score_regression.py)."""
    if not REPORTS_DIR.exists():
        return None
    candidates = list(REPORTS_DIR.glob("*_queue.json"))
    if not candidates:
        return None
    return max(candidates, key=lambda p: p.stat().st_mtime)


def status_bundle() -> dict[str, Any]:
    """Konsolidierter Status fuer das Admin-Testing-Template."""
    fw_meta = frozen_weather_meta()
    tr_meta = test_run_meta()
    state = _read_state()

    # Alter des Frozen-Snapshots in Stunden (fuer rote Warnung)
    age_hours: float | None = None
    if fw_meta and fw_meta.get("frozen_at"):
        try:
            ts = datetime.fromisoformat(fw_meta["frozen_at"])
            age_hours = round((datetime.now() - ts).total_seconds() / 3600.0, 1)
        except (TypeError, ValueError):
            pass

    return {
        "view_active": bool(state.get("view_active", False)),
        "view_set_at": state.get("set_at"),
        "frozen_weather": {
            "exists": frozen_weather_exists(),
            "meta": fw_meta,
            "age_hours": age_hours,
        },
        "test_run": {
            "exists": TEST_RUN_SPOT_ANALYSES_PATH.exists() or TEST_RUN_REGION_ANALYSES_PATH.exists(),
            "meta": tr_meta,
        },
        "test_csv": {
            "path": str(TEST_CSV_PATH),
            "exists": TEST_CSV_PATH.exists(),
            "spot_count": len(load_test_spot_names()),
        },
        "golden": golden_summary(),
        "reports": list_reports(limit=15),
        "review_sessions": list_review_sessions(limit=10),
        "latest_queue_json": str(latest_queue_json()) if latest_queue_json() else None,
    }
