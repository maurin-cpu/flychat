"""Test: 400-800m working_height_agl darf NICHT mehr 'knapp' heissen.

Isoliert: backup spot_analyses.json, InstantDB-Push aus, 3 betroffene Spots
neu rechnen, Ueberhoehungs-Wortwahl pruefen, Datei wiederherstellen.
"""
import json
import logging
import re
import shutil
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

try:
    from dotenv import load_dotenv
    load_dotenv(_REPO / ".env")
except ImportError:
    pass

logging.basicConfig(level=logging.WARNING, format="%(asctime)s [%(levelname)s] %(message)s")

import config
import config_overrides
config_overrides.init()
from chat_engine import WingcastEngine

ANALYSES = config.DATA_DIR / "spot_analyses.json"
BAK = config.DATA_DIR / "spot_analyses.json.testbak"

# Spots, deren ALTE Analyse "nur knapp" sagte (400-800m-Band)
TEST_SPOTS = ["Obere Wengi", "Oberrieden", "Chaumont"]


def extract_ueberhoehung_sentence(text: str) -> str:
    if not text:
        return ""
    for sent in re.split(r"(?<=[.!?])\s+", text):
        if "berh" in sent and "Start" in sent:  # 'Ueberhoehung'/'Überhöhung'
            return sent.strip()
    return ""


def main() -> int:
    print(f"Backup {ANALYSES} -> {BAK}", flush=True)
    shutil.copy2(ANALYSES, BAK)
    try:
        eng = WingcastEngine()
        eng.load_weather_from_cache()
        eng.instantdb = None  # kein Push waehrend Test
        print(f"Rechne {TEST_SPOTS} neu ...", flush=True)
        res = eng.run_spot_analyses(spot_names=TEST_SPOTS)
        print("run result:", res.get("success"), flush=True)

        ok = True
        for spot in TEST_SPOTS:
            days = eng.spot_analyses.get(spot, {})
            if not days:
                print(f"\n### {spot}: KEIN Ergebnis"); ok = False; continue
            for date_str, entry in sorted(days.items()):
                fly = entry.get("flyability", {}) or {}
                rec = fly.get("recommendation", "") or entry.get("recommendation", "")
                xcd = (fly.get("xc_details") or "")
                agl = (entry.get("rating_inputs", {}) or {}).get("working_height_agl") \
                    or fly.get("working_height_agl")
                sent = extract_ueberhoehung_sentence(rec) or extract_ueberhoehung_sentence(xcd)
                bad = bool(re.search(r"\bnur knapp\b|berhoehung knapp|berhöhung knapp", (rec + " " + xcd)))
                flag = "  <-- 'knapp'!" if bad else ""
                print(f"\n### {spot} [{date_str}]  working_height_agl={agl}", flush=True)
                print(f"    Ueberhoehung: {sent or '(kein Satz gefunden)'}{flag}", flush=True)
                if bad:
                    ok = False
        print("\n=================================")
        print("PASS: keine Ueberhoehung als 'knapp'" if ok else "FAIL: 'knapp' noch vorhanden")
        print("=================================")
        return 0 if ok else 2
    finally:
        print(f"\nRestore {BAK} -> {ANALYSES}", flush=True)
        shutil.move(str(BAK), str(ANALYSES))


if __name__ == "__main__":
    raise SystemExit(main())
