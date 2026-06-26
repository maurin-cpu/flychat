"""Goldstandard-Test-Set einfrieren — fuer Regressions-Pruefung.

Liest aktuelle Analysen (data/spot_analyses.json) + den dazu passenden
Wetter-Kontext und legt pro Case eine JSON-Datei in cost_testing/golden/ ab.

Format:
    cost_testing/golden/spot_<name>_<date>.json:
    {
        "spot":   "<name>",
        "date":   "YYYY-MM-DD",
        "frozen_at": "<ISO timestamp>",
        "frozen_at_commit": "<git sha>",
        "input": "<weather_context string, exakt wie an LLM uebergeben>",
        "output": { ...komplettes Analyse-Result aus spot_analyses.json... }
    }

Aufruf:
    python cost_testing/freeze_golden.py --limit 40
    python cost_testing/freeze_golden.py --safety safe --limit 8
    python cost_testing/freeze_golden.py --spot Balderen --date 2026-04-30

Auf dem Server ausfuehren, wo data/spot_analyses.json + frische Wetterdaten
(weather_data Cache) vorliegen. Lokal ohne diese Daten gibt es ein leeres
Set zurueck.

Strategie fuer "ausgewogenes Set":
    Default-Mix bei --balance:
      - 8 safe (gruen)
      - 8 conditional (gelb)
      - 8 not_safe (LLM-Output, nicht pre-filtered)
      - 8 edge (foehn_risk != none ODER conditional_reason vorhanden)
      - 8 random aus dem Rest

Re-Run:
    Skript ueberschreibt nur Cases die schon nicht existieren (sicher).
    Mit --force werden bestehende ueberschrieben.
"""
from __future__ import annotations

import argparse
import json
import random
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

# Repo-Root in sys.path damit chat_engine importierbar ist
_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

import config  # noqa: E402

GOLDEN_DIR = Path(__file__).resolve().parent / "golden"
ANALYSES_PATH = _REPO / "data" / "spot_analyses.json"


def _git_sha() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=_REPO, text=True,
            stderr=subprocess.DEVNULL,
        )
        return out.strip()
    except Exception:
        return "unknown"


def _safety_of(entry: dict) -> str:
    if not isinstance(entry, dict):
        return "unknown"
    safety = entry.get("safety") or {}
    return safety.get("safety_status") or entry.get("safety_status") or "unknown"


def _filter_day(timestamped: dict, date_str: str) -> dict:
    """Reduziert hourly_data/pressure_level_data auf einen einzelnen Tag.

    Schluessel sind ISO-Timestamps wie '2026-05-01T13:00'. Wir matchen
    auf den 'YYYY-MM-DD'-Praefix.
    """
    if not isinstance(timestamped, dict):
        return {}
    return {ts: v for ts, v in timestamped.items() if isinstance(ts, str) and ts.startswith(date_str)}


def _build_weather_snapshot(eng, spot_name: str, date_str: str) -> dict:
    """Baut den minimalen Wetter-Snapshot fuer das Review-Meteogramm.

    Enthaelt nur die Stunden des Test-Tages plus Spot-Geometrie. Wird im
    Goldfile mitgespeichert, damit das Review-UI das Meteogramm rendern
    kann — auch wenn der Tag laengst nicht mehr im Live-Forecast liegt.
    """
    weather = (eng.weather_data or {}).get(spot_name) or {}
    if not weather:
        return {}
    hourly = _filter_day(weather.get("hourly_data") or {}, date_str)
    pressure = _filter_day(weather.get("pressure_level_data") or {}, date_str)
    if not hourly:
        return {}
    spot_obj = next((s for s in (eng.spots or []) if s.get("name") == spot_name), {}) or {}
    return {
        "elevation_m": weather.get("elevation_m") or spot_obj.get("elevation_m"),
        "latitude": weather.get("latitude") or spot_obj.get("latitude"),
        "longitude": weather.get("longitude") or spot_obj.get("longitude"),
        "slope_azimuth": spot_obj.get("slope_azimuth"),
        "slope_angle": spot_obj.get("slope_angle"),
        "windrichtung": spot_obj.get("windrichtung"),
        "ideal_wind_max": spot_obj.get("ideal_wind_max"),
        "hourly_data": hourly,
        "pressure_level_data": pressure,
    }


def _is_edge(entry: dict) -> bool:
    safety = entry.get("safety") or {}
    if (safety.get("foehn_risk") or "none") not in ("none", ""):
        return True
    if entry.get("is_conditional"):
        return True
    return False


def _select_balanced(rows: list[tuple], n: int) -> list[tuple]:
    """rows = [(name, date, entry), ...]. Gibt eine ausgewogene Stichprobe zurueck."""
    by_status = {"safe": [], "conditional": [], "not_safe": [], "edge": [], "other": []}
    for r in rows:
        _, _, entry = r
        if _is_edge(entry):
            by_status["edge"].append(r)
            continue
        s = _safety_of(entry)
        by_status.setdefault(s, by_status["other"]).append(r)

    per_bucket = max(1, n // 5)
    out: list[tuple] = []
    rng = random.Random(42)  # deterministisch
    for bucket in ("safe", "conditional", "not_safe", "edge"):
        pool = by_status.get(bucket, [])
        rng.shuffle(pool)
        out.extend(pool[:per_bucket])
    # Auffuellen aus dem Rest
    rng.shuffle(by_status["other"])
    out.extend(by_status["other"])
    # Truncate / unique
    seen = set()
    uniq = []
    for r in out:
        key = (r[0], r[1])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(r)
        if len(uniq) >= n:
            break
    return uniq


def _build_engine():
    """Instanziert WingcastEngine mit gecachten Wetterdaten (kein neuer Fetch).
    Erfordert dass weather_data lokal verfuegbar ist (z.B. fetch_weather hat es schon geladen).
    """
    from chat_engine import WingcastEngine
    eng = WingcastEngine()
    # Wetterdaten laden (gecacht). Wenn das fehlschlaegt, ist input leer.
    try:
        loaded = eng.load_weather_from_cache()
        if not loaded:
            print("WARN: load_weather_from_cache() hat False zurueckgegeben — "
                  "Cache wahrscheinlich leer.", file=sys.stderr)
    except Exception as e:
        print(f"WARN: Weather-Cache konnte nicht geladen werden: {e}", file=sys.stderr)
    # Analysen laden
    if not eng.spot_analyses and ANALYSES_PATH.is_file():
        eng.spot_analyses = json.loads(ANALYSES_PATH.read_text(encoding="utf-8"))
    return eng


def main():
    ap = argparse.ArgumentParser(description="Goldstandard-Cases einfrieren")
    ap.add_argument("--limit", type=int, default=40, help="max Anzahl Cases (default 40)")
    ap.add_argument("--balance", action="store_true", default=True,
                    help="ausgewogene Mischung (default an)")
    ap.add_argument("--safety", choices=["safe", "conditional", "not_safe", "any"],
                    default="any", help="nur Cases mit diesem safety_status")
    ap.add_argument("--spot", default=None, help="nur ein bestimmter Spot")
    ap.add_argument("--date", default=None, help="nur ein bestimmtes Datum YYYY-MM-DD")
    ap.add_argument("--force", action="store_true",
                    help="bestehende Goldstandard-Files ueberschreiben")
    ap.add_argument("--dry-run", action="store_true", help="nur listen, nicht schreiben")
    args = ap.parse_args()

    if not ANALYSES_PATH.is_file():
        print(f"FEHLER: {ANALYSES_PATH} nicht vorhanden. "
              f"Auf Server ausfuehren wo Analysen gecacht sind.", file=sys.stderr)
        return 1

    eng = _build_engine()
    if not eng.spot_analyses:
        print("FEHLER: Keine Analysen geladen.", file=sys.stderr)
        return 1
    if not eng.weather_data:
        print("WARN: Keine Wetterdaten geladen — Input wird leer sein. "
              "Skript trotzdem fortsetzen? (Strg+C zum Abbrechen)", file=sys.stderr)

    rows: list[tuple[str, str, dict]] = []
    for name, dates in eng.spot_analyses.items():
        if args.spot and name != args.spot:
            continue
        for date_str, entry in dates.items():
            if args.date and date_str != args.date:
                continue
            if args.safety != "any" and _safety_of(entry) != args.safety:
                continue

            # Nur Cases mit vorhandenen Wetterdaten in den Pool aufnehmen
            weather = (eng.weather_data or {}).get(name) or {}
            hourly = _filter_day(weather.get("hourly_data") or {}, date_str)
            if not hourly:
                continue

            rows.append((name, date_str, entry))

    if not rows:
        print("Keine passenden Cases gefunden.", file=sys.stderr)
        return 1

    selected = _select_balanced(rows, args.limit) if args.balance else rows[: args.limit]

    GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
    sha = _git_sha()
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    written = 0
    skipped = 0
    no_input = 0
    for name, date_str, entry in selected:
        safe_name = name.replace("/", "_").replace(" ", "_")
        out_path = GOLDEN_DIR / f"spot_{safe_name}_{date_str}.json"
        if out_path.exists() and not args.force:
            skipped += 1
            continue

        # Spot-Objekt finden (fuer _build_single_spot_context)
        spot_obj = next((s for s in eng.spots if s["name"] == name), None)
        ctx = ""
        if spot_obj:
            try:
                ctx = eng._build_single_spot_context(spot_obj, date_str) or ""
            except Exception as e:
                print(f"WARN: Kontext-Bau fehlgeschlagen fuer {name}/{date_str}: {e}",
                      file=sys.stderr)
        if not ctx:
            no_input += 1
            print(f"SKIP: Kein Kontext fuer {name}/{date_str} (Wetterdaten fehlen oder unvollstaendig)",
                  file=sys.stderr)
            continue

        weather_snapshot = _build_weather_snapshot(eng, name, date_str)
        record = {
            "spot": name,
            "date": date_str,
            "frozen_at": ts,
            "frozen_at_commit": sha,
            "safety_status": _safety_of(entry),
            "input": ctx,
            "output": entry,
            "weather_snapshot": weather_snapshot,
        }
        if args.dry_run:
            print(f"[dry-run] would write {out_path.name} "
                  f"(input={len(ctx)} chars, status={record['safety_status']})")
        else:
            out_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        written += 1

    print(f"\nFreeze-Report (commit={sha}, ts={ts}):")
    print(f"  Cases gewaehlt:   {len(selected)}")
    print(f"  Geschrieben:      {written}")
    print(f"  Uebersprungen:    {skipped} (Datei existiert, --force ueberspringen)")
    print(f"  Ohne Input-Kontext: {no_input} (vermutlich fehlende weather_data)")
    print(f"  Zielordner:       {GOLDEN_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
