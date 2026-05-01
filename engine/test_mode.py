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
from datetime import datetime
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


def freeze_current_weather() -> dict[str, Any]:
    """Kopiert die Test-Spot-Eintraege aus `wetterdaten.json` nach `data/mocks/`.

    Filtert auf die Spot-Namen aus `fluggebiete_test.csv` — der Snapshot
    enthaelt damit nur die Test-Spots (~28) statt aller ~487 Spots, was
    Disk-Platz spart und exakt dem entspricht, was der Test-Lauf nachher
    auch verwendet. Regionen (`_regions`) und `_meta` bleiben vollstaendig
    erhalten, weil Regionen alle mitanalysiert werden.

    Wirft FileNotFoundError, wenn keine aktuellen Wetterdaten vorhanden sind.
    """
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

    # Filter: nur Test-Spots + alle `_*`-Specials (`_regions`, `_meta`, ...)
    filtered: dict[str, Any] = {
        k: v for k, v in data.items()
        if k.startswith("_") or k in test_names
    }
    kept_spots = sum(1 for k in filtered.keys() if not k.startswith("_"))
    missing = sorted(test_names - set(filtered.keys()))

    regions = filtered.get("_regions") or {}
    regions_count = len(regions) if isinstance(regions, dict) else 0
    src_meta = filtered.get("_meta") or {}
    source_run_at = src_meta.get("last_updated") or src_meta.get("generated_at") if isinstance(src_meta, dict) else None

    # `_meta.spots_count` an gefilterte Realitaet anpassen, damit Konsumenten
    # nicht denken da seien noch alle Spots drin.
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
        "spot_count": kept_spots,
        "region_count": regions_count,
        "total_source_spots": total_source_spots,
        "test_set_size": len(test_names),
        "missing_test_spots": missing,
    }
    config.atomic_write_json(FROZEN_META_PATH, meta)
    logger.info(
        "Frozen Weather (Test-Set) geschrieben: %s (%d von %d Test-Spots, %d Regionen, gefiltert aus %d Source-Spots)",
        FROZEN_WEATHER_PATH, kept_spots, len(test_names), regions_count, total_source_spots,
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

def run_test_analyses_stream(engine, *, use_frozen_input: bool) -> Iterator[dict[str, Any]]:
    """Stream-Generator fuer einen Test-Lauf mit isoliertem Output.

    Filtert die Spots auf die Eintraege aus `fluggebiete_test.csv`, leitet die
    Output-Pfade auf `data/test_runs/latest/` um, und (optional) ersetzt das
    Live-Wetter durch den Frozen-Snapshot. Restauriert den Engine-State nach
    dem Lauf — egal ob Erfolg oder Fehler.

    Args:
        engine: GleitcastEngine-Instanz (typischerweise das globale `engine` aus web.py).
        use_frozen_input: True = Frozen-Snapshot laden; False = aktuell geladene
            `engine.weather_data` weiterverwenden.

    Yields die SSE-Events von `engine.run_all_analyses_stream()` plus zwei
    eigene Events am Anfang/Ende: `test_init` und `test_done`.
    """
    snapshot = {
        "analyses_file": engine.analyses_file,
        "region_analyses_file": engine.region_analyses_file,
        "spots": engine.spots,
        "weather_data": engine.weather_data,
        "region_weather_data": engine.region_weather_data,
        "spot_analyses": engine.spot_analyses,
        "region_analyses": engine.region_analyses,
        "weather_context_str": getattr(engine, "weather_context_str", None),
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

        n_spots = len(engine.spots)
        n_regions = len(engine.region_weather_data) if engine.region_weather_data else 0

        yield {"event": "test_init", "data": {
            "n_spots": n_spots,
            "n_regions": n_regions,
            "use_frozen_weather": use_frozen_input,
            "started_at": started_at.isoformat(timespec="seconds"),
        }}

        if n_spots == 0:
            yield {"event": "error",
                   "data": {"message": "Keine Test-Spots im Wetter-Datensatz gefunden — Frozen-Snapshot zu Test-CSV inkompatibel?"}}
            return

        engine.spot_analyses = {}
        engine.region_analyses = {}

        yield from engine.run_all_analyses_stream()

        write_test_run_meta({
            "run_at": started_at.isoformat(timespec="seconds"),
            "completed_at": datetime.now().isoformat(timespec="seconds"),
            "used_frozen_weather": use_frozen_input,
            "n_spots": n_spots,
            "n_regions": n_regions,
        })
        yield {"event": "test_done", "data": {"n_spots": n_spots, "n_regions": n_regions}}
    finally:
        for k, v in snapshot.items():
            setattr(engine, k, v)


# ---------------------------------------------------------------------------
# Goldstandard / Regression-Reports
# ---------------------------------------------------------------------------

_COST_TESTING_DIR: Path = Path(__file__).resolve().parent.parent / "cost_testing"
GOLDEN_DIR: Path = _COST_TESTING_DIR / "golden"
REPORTS_DIR: Path = _COST_TESTING_DIR / "reports"
FREEZE_GOLDEN_SCRIPT: Path = _COST_TESTING_DIR / "freeze_golden.py"
SCORE_REGRESSION_SCRIPT: Path = _COST_TESTING_DIR / "score_regression.py"


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
    }
