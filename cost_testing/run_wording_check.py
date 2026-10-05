"""KI-Analyse auf Testdaten (Frozen-Snapshot, Test-Spot-Set, 1 Tag) laufen lassen
und die Prosa auf Urteilswoerter pruefen. Schreibt nach data/test_runs/latest/.

Aufruf: PYTHONIOENCODING=utf-8 python cost_testing/run_wording_check.py
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import config_overrides  # noqa: E402
config_overrides.init()

from chat_engine import WingcastEngine  # noqa: E402
from engine import test_mode  # noqa: E402

JUDGMENT = re.compile(
    r"\b(safe|unsafe|safely|dangerous|perfect|ideal|excellent|relaxed|recommend\w*|"
    r"sicher\w*|gef(ae|ä)hrlich|perfekt|ideal|empf(e|o)hl\w*|Freigabe)\b", re.IGNORECASE)
FIELDS = ("summary", "recommendation", "wind_summary", "thermal_quality", "xc_details", "safety_feedback")
LISTS = ("caution_notes", "no_go_reasons", "flyability_limits", "highlights")


def main() -> int:
    engine = WingcastEngine()
    t0 = time.time()
    n = 0
    for ev in test_mode.run_test_analyses_stream(engine, use_frozen_input=True, spot_set="test", n_days=1):
        name = ev.get("event")
        data = ev.get("data") or {}
        if name in ("test_init", "test_done", "error", "done", "complete"):
            print(f"[{time.time()-t0:6.0f}s] {name}: {json.dumps(data, ensure_ascii=False)[:200]}")
        else:
            n += 1
            if n % 10 == 0:
                print(f"[{time.time()-t0:6.0f}s] {n} Events ... {name}")
    spots, regions, ts = test_mode.load_test_run_analyses()
    print(f"\n=== Lauf fertig: {len(spots)} Spots, {len(regions)} Regionen, {ts}\n")

    hits = 0
    def _scan(label: str, res: dict):
        nonlocal hits
        for f in FIELDS:
            v = res.get(f)
            if isinstance(v, str):
                for m in JUDGMENT.finditer(v):
                    hits += 1
                    s = max(0, m.start() - 50); e = min(len(v), m.end() + 50)
                    print(f"  !! {label} / {f}: …{v[s:e]}…")
        for f in LISTS:
            for item in res.get(f) or []:
                if isinstance(item, str) and JUDGMENT.search(item):
                    hits += 1
                    print(f"  !! {label} / {f}[]: {item[:140]}")

    def _walk(coll: dict, kind: str):
        for name, days in coll.items():
            if not isinstance(days, dict):
                continue
            for d, res in days.items():
                if not isinstance(res, dict):
                    continue
                for part in ("safety", "flyability"):
                    sub = res.get(part)
                    if isinstance(sub, dict):
                        _scan(f"{kind} {name} {d} [{part}]", sub)
                _scan(f"{kind} {name} {d}", res)

    _walk(spots, "Spot")
    _walk(regions, "Region")
    print(f"\n=== Urteilswoerter gefunden: {hits}")

    # drei Beispiel-Summaries zum Lesen
    print("\n=== Beispiele (Safety-Summary):")
    shown = 0
    for name, days in list(spots.items()):
        for d, res in days.items():
            s = (res.get("safety") or {}).get("summary") or res.get("safety_feedback") or res.get("summary")
            st = (res.get("safety") or {}).get("safety_status") or res.get("safety_status")
            if s:
                print(f"\n[{name} {d} — {st}]\n{s}")
                shown += 1
            if shown >= 4:
                break
        if shown >= 4:
            break
    return 0


if __name__ == "__main__":
    sys.exit(main())
