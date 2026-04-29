"""Regression-Score: aktueller Pipeline gegen eingefrorenen Goldstandard.

Liest tests/golden/*.json (erzeugt von freeze_golden.py) und vergleicht
das aktuelle Engine-Output mit dem eingefrorenen Output.

Vergleichs-Felder + Gewichte (kalibriert nach gemessener LLM-Jitter mit
temperature=0.2 — Schwellen ueber natuerlicher Variation):

  safety_status      kritisch (10)  exakter Match
  flyability_tier    kritisch (10)  exakter Match
  safe_window        hoch     ( 5)  Stundenueberlappung >= 80%
  rating             hoch     ( 5)  |Delta| <= 1.0   (Jitter bis 0.6 gemessen)
  no_go_reasons      mittel   ( 3)  Jaccard >= 0.7   (sicherheitskritisch, streng)
  caution_notes      mittel   ( 3)  Jaccard >= 0.3   (Freitext, Jitter normal)
  streckenflug.tier  mittel   ( 3)  Differenz <= 1 Stufe in Reihenfolge
                                    top > moderat > lokal > kein_xc

Acceptance-Gate (Exit-Code != 0 wenn verletzt):
  - 0 kritische Regressionen
  - <= 6 hohe Regressionen  (statistisch sinnvoll bei 12-40 Cases)
  - Gewichteter Score >= 90% des Maximums

Aufruf:
    python debug_scripts/score_regression.py
    python debug_scripts/score_regression.py --report data/regression_2026-04-29.md
    python debug_scripts/score_regression.py --no-llm  # ueberspringt neue Analyse, vergleicht nur Output

Modi:
    Default: laedt Engine, sendet input von Golden an Pipeline, vergleicht mit golden output.
    --no-llm: vergleicht stattdessen aktuelles spot_analyses.json[name][date] gegen Golden.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

GOLDEN_DIR = _REPO / "tests" / "golden"

WEIGHTS = {
    "safety_status":   ("kritisch", 10),
    "flyability_tier": ("kritisch", 10),
    "safe_window":     ("hoch",      5),
    "rating":          ("hoch",      5),
    "no_go_reasons":   ("mittel",    3),
    "caution_notes":   ("mittel",    3),
    "streckenflug_tier": ("mittel",  3),
}


def _get_safety_status(entry: dict) -> str:
    return (entry.get("safety") or {}).get("safety_status") or entry.get("safety_status") or ""


def _get_safe_window(entry: dict) -> str:
    return (entry.get("safety") or {}).get("safe_window") or entry.get("safe_window") or ""


def _get_flyability_tier(entry: dict) -> str:
    fly = entry.get("flyability") or {}
    return fly.get("flyability_tier") or fly.get("fly_status") or entry.get("fly_status") or entry.get("flyability_tier") or ""


def _get_rating(entry: dict) -> float:
    try:
        return float(entry.get("rating", 0.0) or 0.0)
    except Exception:
        return 0.0


def _get_no_go_reasons(entry: dict) -> set:
    safety = entry.get("safety") or {}
    arr = safety.get("no_go_reasons") or entry.get("no_go_reasons") or []
    return set(arr) if isinstance(arr, list) else set()


def _get_caution_notes(entry: dict) -> set:
    safety = entry.get("safety") or {}
    arr = safety.get("caution_notes") or entry.get("caution_notes") or []
    return set(arr) if isinstance(arr, list) else set()


def _get_streckenflug_tier(entry: dict) -> str:
    sf = entry.get("streckenflug") or {}
    return sf.get("tier") or ""


def _hours_from_window(window_str: str) -> set[int]:
    """Parst '07:00-12:00' oder '07-12' oder '7,8,9,10,11' zu set([7,8,9,10,11])."""
    if not window_str or window_str.lower() in ("keins", "kein", ""):
        return set()
    hours = set()
    # Einfache Range
    m = re.match(r"\s*(\d{1,2}):?\d*\s*-\s*(\d{1,2}):?\d*\s*$", window_str)
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        if 0 <= a <= 23 and 0 <= b <= 23 and a <= b:
            return set(range(a, b + 1))
    # Komma-Liste
    for part in re.split(r"[,;]", window_str):
        part = part.strip()
        m = re.match(r"^(\d{1,2})", part)
        if m:
            try:
                hours.add(int(m.group(1)))
            except ValueError:
                pass
    return hours


def _jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


_STRECKENFLUG_RANK = {
    "top": 4, "moderat": 3, "lokal": 2, "kein_xc": 1, "": 0,
}


def _score_field(name: str, gold, current) -> tuple[bool, str]:
    """Returns (passed, reason). passed=True wenn Feld die Schwelle haelt."""
    if name in ("safety_status", "flyability_tier"):
        ok = (gold or "") == (current or "")
        return ok, f"gold={gold!r} got={current!r}"
    if name == "streckenflug_tier":
        # +/-1 Stufe Toleranz in der Reihenfolge top > moderat > lokal > kein_xc
        gr = _STRECKENFLUG_RANK.get(gold or "", 0)
        cr = _STRECKENFLUG_RANK.get(current or "", 0)
        diff = abs(gr - cr)
        return diff <= 1, f"gold={gold!r} got={current!r} stufen_diff={diff}"
    if name == "rating":
        delta = abs(_get_rating({"rating": gold}) - _get_rating({"rating": current}))
        return delta <= 1.0, f"|delta|={delta:.2f}"
    if name == "safe_window":
        ga, ca = _hours_from_window(gold), _hours_from_window(current)
        if not ga and not ca:
            return True, "beide leer"
        overlap = len(ga & ca) / max(1, len(ga | ca))
        return overlap >= 0.8, f"overlap={overlap:.0%} gold={sorted(ga)} got={sorted(ca)}"
    if name == "no_go_reasons":
        j = _jaccard(set(gold or []), set(current or []))
        return j >= 0.7, f"jaccard={j:.2f}"
    if name == "caution_notes":
        j = _jaccard(set(gold or []), set(current or []))
        return j >= 0.3, f"jaccard={j:.2f}"
    return True, "ungeprueft"


def _extract_for_compare(entry: dict) -> dict:
    return {
        "safety_status":     _get_safety_status(entry),
        "safe_window":       _get_safe_window(entry),
        "flyability_tier":   _get_flyability_tier(entry),
        "rating":            _get_rating(entry),
        "no_go_reasons":     list(_get_no_go_reasons(entry)),
        "caution_notes":     list(_get_caution_notes(entry)),
        "streckenflug_tier": _get_streckenflug_tier(entry),
    }


def _run_current_pipeline(input_ctx: str, spot_name: str, date_str: str) -> dict:
    """Sendet input_ctx an den Live-LLM-Stack und gibt das prozessierte Result zurueck."""
    from chat_engine import GleitcastEngine
    eng = GleitcastEngine()
    # spot_obj finden — Pipeline erwartet das volle Dict
    spot_obj = next((s for s in eng.spots if s["name"] == spot_name), None)
    if not spot_obj:
        return {"error": f"Spot {spot_name} nicht in spots.csv"}
    # Wir umgehen den weather_context-Builder und injizieren input_ctx direkt
    # ueber einen Monkey-Patch.
    eng._build_single_spot_context = lambda spot, d, **kw: input_ctx if (spot["name"] == spot_name and d == date_str) else ""
    # Jetzt rufen wir _combined_analysis_single_spot_day auf — dasselbe wie der
    # Live-Pfad in run_all_analyses_stream.
    return eng._combined_analysis_single_spot_day(spot_obj, date_str, input_ctx)


def main():
    ap = argparse.ArgumentParser(description="Regression-Score gegen Goldstandard")
    ap.add_argument("--report", default=None, help="Markdown-Report-Datei")
    ap.add_argument("--no-llm", action="store_true",
                    help="kein neuer LLM-Call, nur aktuelles spot_analyses.json vergleichen")
    ap.add_argument("--max-cases", type=int, default=0, help="auf N Cases beschraenken")
    args = ap.parse_args()

    if not GOLDEN_DIR.is_dir():
        print(f"FEHLER: {GOLDEN_DIR} fehlt — zuerst freeze_golden.py ausfuehren.", file=sys.stderr)
        return 2

    cases = sorted(GOLDEN_DIR.glob("spot_*.json"))
    if not cases:
        print(f"FEHLER: keine Goldstandard-Cases in {GOLDEN_DIR}.", file=sys.stderr)
        return 2
    if args.max_cases > 0:
        cases = cases[: args.max_cases]

    if args.no_llm:
        analyses_path = _REPO / "data" / "spot_analyses.json"
        current_all = json.loads(analyses_path.read_text(encoding="utf-8"))
    else:
        current_all = None  # per-case via Pipeline

    crit_regressions = 0
    high_regressions = 0
    total_score = 0
    max_score = 0
    rows: list[dict] = []

    for case_path in cases:
        gold_record = json.loads(case_path.read_text(encoding="utf-8"))
        spot, date_str = gold_record["spot"], gold_record["date"]
        gold = _extract_for_compare(gold_record["output"])

        if args.no_llm:
            current_entry = (current_all.get(spot) or {}).get(date_str)
            if not current_entry:
                rows.append({"spot": spot, "date": date_str, "skipped": True, "reason": "in current spot_analyses fehlt"})
                continue
        else:
            current_entry = _run_current_pipeline(gold_record["input"], spot, date_str)

        current = _extract_for_compare(current_entry)

        case_score = 0
        case_max = 0
        case_failures: list[str] = []
        for field, (severity, weight) in WEIGHTS.items():
            case_max += weight
            ok, reason = _score_field(field, gold[field], current[field])
            if ok:
                case_score += weight
            else:
                if severity == "kritisch":
                    crit_regressions += 1
                elif severity == "hoch":
                    high_regressions += 1
                case_failures.append(f"{field}({severity}): {reason}")

        total_score += case_score
        max_score += case_max
        rows.append({
            "spot": spot, "date": date_str,
            "score": case_score, "max": case_max,
            "failures": case_failures,
        })

    pct = 100.0 * total_score / max_score if max_score else 0.0
    print(f"\n=== Regression-Score ===")
    print(f"Cases:               {len(rows)}")
    print(f"Score:               {total_score}/{max_score}  ({pct:.1f}%)")
    print(f"Krit. Regressionen:  {crit_regressions}")
    print(f"Hohe Regressionen:   {high_regressions}")

    failed_cases = [r for r in rows if r.get("failures")]
    print(f"Cases mit Diff:      {len(failed_cases)}")
    for r in failed_cases[:10]:
        print(f"  {r['spot']}/{r['date']}: {r['score']}/{r['max']}")
        for f in r["failures"][:3]:
            print(f"     - {f}")

    if args.report:
        report_path = Path(args.report)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        with report_path.open("w", encoding="utf-8") as f:
            f.write(f"# Regression-Report — {datetime.now(timezone.utc).isoformat(timespec='seconds')}\n\n")
            f.write(f"- Cases: {len(rows)}\n")
            f.write(f"- Score: {total_score}/{max_score} ({pct:.1f}%)\n")
            f.write(f"- Kritische Regressionen: {crit_regressions}\n")
            f.write(f"- Hohe Regressionen: {high_regressions}\n\n")
            for r in failed_cases:
                f.write(f"## {r['spot']} / {r['date']}\n")
                f.write(f"Score: {r['score']}/{r['max']}\n\n")
                for fail in r["failures"]:
                    f.write(f"- {fail}\n")
                f.write("\n")
        print(f"Report geschrieben: {report_path}")

    # Acceptance-Gate (Schwellen kalibriert nach gemessener LLM-Jitter)
    gate_ok = (crit_regressions == 0) and (high_regressions <= 6) and (pct >= 90.0)
    print(f"\nAcceptance-Gate: {'PASS' if gate_ok else 'FAIL'}")
    return 0 if gate_ok else 1


if __name__ == "__main__":
    sys.exit(main())
