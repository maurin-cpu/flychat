"""
Score-Regression: Auswertung von labeled_examples.jsonl.

Phase 1 (MVP): rein statische Analyse der gesammelten Labels.
- Confusion-Matrix (LLM-Rating vs. Pilot-Korrektur)
- Treffer-Quote pro LLM-Rating
- Fehler-Muster nach Tier / Substanz-Bins

Phase 2 (spaeter): --rerun fuer LLM-Replay gegen aktuellen Skill.

Usage:
    python scripts/score_regression.py
    python scripts/score_regression.py --entity spot
    python scripts/score_regression.py --source production
    python scripts/score_regression.py --tier alpen
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

# Windows-Console: cp1252 erstickt an Unicode (Pfeil, em-dash). UTF-8 erzwingen.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config


JSONL_PATH = config.DATA_DIR / "labeled_examples.jsonl"


def load_labels() -> list[dict]:
    if not JSONL_PATH.exists():
        return []
    entries = []
    with open(JSONL_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return entries


def effective_rating(entry: dict) -> tuple[int | None, int | None, str | None]:
    """Returns (llm_rating, ground_truth_rating, label).

    Ground-Truth ist:
      - corrected_experience_rating wenn Korrektur vorhanden
      - sonst llm_rating wenn label == "richtig"
      - sonst None
    """
    llm = (entry.get("llm_output_full") or {}).get("experience_rating")
    fb = entry.get("user_feedback") or {}
    label = fb.get("label")
    corr = fb.get("corrected_experience_rating")
    if label == "richtig":
        return llm, llm, label
    if corr is not None:
        return llm, corr, label
    return llm, None, label


def filter_entries(entries, entity_type=None, source=None, tier=None):
    out = []
    for e in entries:
        if entity_type and e.get("entity_type") != entity_type:
            continue
        if source:
            src = (e.get("weather_input") or {}).get("aggregates_source") or "production"
            if src != source:
                continue
        if tier and e.get("terrain_tier") != tier:
            continue
        out.append(e)
    return out


def print_header(entries, args):
    print("=" * 60)
    print("SCORE-REGRESSION — Labeled-Examples-Auswertung")
    print("=" * 60)
    filters = []
    if args.entity:
        filters.append(f"entity={args.entity}")
    if args.source:
        filters.append(f"source={args.source}")
    if args.tier:
        filters.append(f"tier={args.tier}")
    if filters:
        print("Filter: " + ", ".join(filters))
    print(f"Datei: {JSONL_PATH}")
    print(f"Eingelesen: {len(entries)} Labels")

    by_kind = Counter(e.get("entity_type") for e in entries)
    by_source = Counter((e.get("weather_input") or {}).get("aggregates_source") or "production" for e in entries)
    by_tier = Counter(e.get("terrain_tier") for e in entries)

    print(f"  nach entity: " + ", ".join(f"{k}={v}" for k, v in by_kind.most_common()))
    print(f"  nach source: " + ", ".join(f"{k}={v}" for k, v in by_source.most_common()))
    print(f"  nach tier:   " + ", ".join(f"{k}={v}" for k, v in by_tier.most_common()))
    print()


def print_confusion_matrix(entries):
    """5x5 Matrix: LLM-Rating Zeile, Ground-Truth Spalte."""
    matrix = [[0] * 5 for _ in range(5)]  # matrix[llm-1][gt-1]
    unlabeled = 0
    no_llm = 0
    for e in entries:
        llm, gt, _ = effective_rating(e)
        if llm is None:
            no_llm += 1
            continue
        if gt is None:
            unlabeled += 1
            continue
        if not (1 <= llm <= 5 and 1 <= gt <= 5):
            continue
        matrix[llm - 1][gt - 1] += 1

    print("CONFUSION-MATRIX — Zeile = LLM-Rating, Spalte = Pilot-Ground-Truth")
    print("(Diagonale = Treffer, Off-Diagonal = Fehler)")
    print()
    print(f"{'LLM\\Pilot':<10s} {'1':>5s} {'2':>5s} {'3':>5s} {'4':>5s} {'5':>5s} {'Sum':>6s} {'Treff':>8s}")
    print("-" * 60)
    total_correct = 0
    total = 0
    for i in range(5):
        row = matrix[i]
        row_sum = sum(row)
        correct = row[i]
        total_correct += correct
        total += row_sum
        hit = f"{correct/row_sum*100:.0f}%" if row_sum else "–"
        cells = " ".join(f"{v:>5d}" for v in row)
        print(f"Rating {i+1:<3d} {cells} {row_sum:>6d} {hit:>8s}")
    print("-" * 60)
    overall = f"{total_correct/total*100:.0f}%" if total else "–"
    print(f"Total: {total_correct}/{total} korrekt ({overall})")
    if no_llm or unlabeled:
        print(f"  (ausgelassen: no_llm={no_llm}, ohne_groundtruth={unlabeled})")
    print()


def print_bias_direction(entries):
    """Wo geht's hin wenn falsch?"""
    direction = Counter()  # (llm, gt) -> count
    over_total = 0
    under_total = 0
    correct_total = 0
    for e in entries:
        llm, gt, _ = effective_rating(e)
        if llm is None or gt is None or not (1 <= llm <= 5 and 1 <= gt <= 5):
            continue
        if llm == gt:
            correct_total += 1
        elif llm > gt:
            over_total += 1
            direction[(llm, gt)] += 1
        else:
            under_total += 1
            direction[(llm, gt)] += 1

    total = correct_total + over_total + under_total
    if total == 0:
        return
    print("BIAS-RICHTUNG")
    print(f"  Richtig:           {correct_total:>3d} ({correct_total/total*100:>4.0f}%)")
    print(f"  KI zu optimistisch: {over_total:>3d} ({over_total/total*100:>4.0f}%)  <- KI gibt hoeheres Rating als Pilot")
    print(f"  KI zu pessimistisch: {under_total:>3d} ({under_total/total*100:>4.0f}%)")
    print()
    if direction:
        print("  Haeufigste Fehlerpaare (LLM → Pilot):")
        for (llm, gt), n in direction.most_common(8):
            arrow = "↓" if llm > gt else "↑"
            print(f"    {llm} {arrow} {gt}: {n}x")
        print()


def _peak_bin(peak):
    if peak is None:
        return "n/a"
    if peak < 1.0:
        return "<1.0"
    if peak < 1.5:
        return "1.0-1.5"
    if peak < 2.0:
        return "1.5-2.0"
    if peak < 2.5:
        return "2.0-2.5"
    if peak < 3.0:
        return "2.5-3.0"
    return ">=3.0"


def _wh_bin(wh):
    if wh is None:
        return "n/a"
    if wh < 500:
        return "<500m"
    if wh < 800:
        return "500-800m"
    if wh < 1200:
        return "800-1200m"
    if wh < 1800:
        return "1200-1800m"
    return ">=1800m"


def _prodh_bin(p):
    if p is None:
        return "n/a"
    if p < 3:
        return "<3h"
    if p < 6:
        return "3-6h"
    if p < 9:
        return "6-9h"
    if p < 12:
        return "9-12h"
    return ">=12h"


def print_error_patterns(entries):
    """Wo (welche Wetter-Substanz) liegen die Fehler-Cluster?"""
    # Sammle nur Falsch-Bewertungen (LLM > GT) — der dominante Bias.
    over_cases = []
    for e in entries:
        llm, gt, _ = effective_rating(e)
        if llm is None or gt is None or llm <= gt:
            continue
        agg = (e.get("weather_input") or {}).get("aggregates") or {}
        over_cases.append({
            "llm": llm,
            "gt": gt,
            "tier": e.get("terrain_tier") or "?",
            "peak": agg.get("sustained_peak_mps"),
            "wh": agg.get("working_height_agl_m"),
            "prod_h": agg.get("productive_h_strict"),
            "cloud": agg.get("cloud_structure"),
        })

    if not over_cases:
        return

    print(f"FEHLER-MUSTER bei {len(over_cases)} zu-optimistisch-Cases (LLM > Pilot)")
    print()

    # Gruppe pro LLM-Rating-Stufe (4 und 5 sind die dominanten Problemzonen).
    by_llm = defaultdict(list)
    for c in over_cases:
        by_llm[c["llm"]].append(c)

    for llm in sorted(by_llm.keys(), reverse=True):
        cases = by_llm[llm]
        if len(cases) < 3:
            continue
        print(f"── LLM-Rating {llm} → falsch (n={len(cases)}) ──")
        # Tier-Verteilung
        tiers = Counter(c["tier"] for c in cases)
        print(f"  Tier:  " + ", ".join(f"{t}={n}" for t, n in tiers.most_common()))
        # Peak-Bins
        peaks = Counter(_peak_bin(c["peak"]) for c in cases)
        print(f"  Peak:  " + ", ".join(f"{k}={v}" for k, v in sorted(peaks.items())))
        # Working-Height-Bins
        whs = Counter(_wh_bin(c["wh"]) for c in cases)
        print(f"  WH:    " + ", ".join(f"{k}={v}" for k, v in sorted(whs.items())))
        # Prod-h-Bins
        ph = Counter(_prodh_bin(c["prod_h"]) for c in cases)
        print(f"  ProdH: " + ", ".join(f"{k}={v}" for k, v in sorted(ph.items())))
        # Cloud-Struct
        cs = Counter((c["cloud"] or "n/a") for c in cases)
        print(f"  Cloud: " + ", ".join(f"{k}={v}" for k, v in cs.most_common()))
        print()


def print_top_offenders(entries, n=10):
    """Top-N falsch-bewertete Cases mit Detail-Daten — fuer Stichproben-Review."""
    over_cases = []
    for e in entries:
        llm, gt, _ = effective_rating(e)
        if llm is None or gt is None or llm == gt:
            continue
        agg = (e.get("weather_input") or {}).get("aggregates") or {}
        over_cases.append({
            "id": e.get("analysis_id"),
            "name": e.get("spot_or_region_id"),
            "date": e.get("target_date"),
            "tier": e.get("terrain_tier") or "?",
            "llm": llm,
            "gt": gt,
            "diff": llm - gt,
            "peak": agg.get("sustained_peak_mps"),
            "wh": agg.get("working_height_agl_m"),
            "prod_h": agg.get("productive_h_strict"),
            "cloud": agg.get("cloud_structure"),
        })
    if not over_cases:
        return
    # Sortiere nach absolutem Diff (groesste Fehler zuerst), dann nach Peak
    over_cases.sort(key=lambda c: (-abs(c["diff"]), -(c["peak"] or 0)))
    print(f"TOP-{min(n, len(over_cases))} FEHL-BEWERTUNGEN (sortiert nach Differenz)")
    print()
    print(f"{'Name':<26s} {'Datum':<11s} {'Tier':<10s} {'LLM→GT':>7s} {'peak':>5s} {'prodH':>6s} {'wh':>6s} {'cloud':<14s}")
    print("-" * 100)
    for c in over_cases[:n]:
        nm = (c["name"] or "")[:26]
        arrow = f"{c['llm']}→{c['gt']}"
        peak = f"{c['peak']:.1f}" if c['peak'] is not None else "–"
        wh = f"{c['wh']}m" if c['wh'] is not None else "–"
        ph = f"{c['prod_h']}h" if c['prod_h'] is not None else "–"
        cloud = (c['cloud'] or "–")[:14]
        print(f"{nm:<26s} {c['date']:<11s} {c['tier']:<10s} {arrow:>7s} {peak:>5s} {ph:>6s} {wh:>6s} {cloud:<14s}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Score-Regression — Auswertung Labeled-Examples")
    parser.add_argument("--entity", choices=["spot", "region"], default=None,
                        help="Nur Spots oder nur Regionen (default: beides)")
    parser.add_argument("--source", choices=["production", "backfill_approx"], default=None,
                        help="Nur Production- oder nur Backfill-Cases (default: alle)")
    parser.add_argument("--tier", default=None,
                        help="Filter auf Tier (mittelland|jura|voralpen|alpen|hochalpin)")
    parser.add_argument("--top", type=int, default=10,
                        help="Top-N Fehl-Bewertungen anzeigen (default: 10)")
    args = parser.parse_args()

    entries = load_labels()
    if not entries:
        print(f"Keine Labels gefunden unter {JSONL_PATH}")
        sys.exit(1)

    entries = filter_entries(entries, args.entity, args.source, args.tier)
    if not entries:
        print("Filter ergeben leere Menge.")
        sys.exit(1)

    print_header(entries, args)
    print_confusion_matrix(entries)
    print_bias_direction(entries)
    print_error_patterns(entries)
    print_top_offenders(entries, n=args.top)


if __name__ == "__main__":
    main()
