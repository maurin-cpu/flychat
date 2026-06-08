"""Test: Analysiert einen einzelnen Spot und prueft ob hazard_notes + flyability_notes im Ergebnis sind."""
from __future__ import annotations
import json, logging, sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("test_hazard_notes")

try:
    from dotenv import load_dotenv
    load_dotenv(_REPO / ".env")
except ImportError:
    pass

import config_overrides
config_overrides.init()

import datetime
from chat_engine import WingcastEngine
from spots import load_spots

eng = WingcastEngine()
eng.load_weather_from_cache()

# Spot laden
spots = load_spots()
TARGET = "Balderen"
spot = next((s for s in spots if s["name"] == TARGET), None)
if spot is None:
    logger.error("Spot '%s' nicht gefunden", TARGET)
    sys.exit(1)

date_str = "2026-05-09"
logger.info("Analysiere %s für %s ...", TARGET, date_str)

result = eng._build_and_analyze_spot(spot, date_str)

logger.info("=== ERGEBNIS ===")
logger.info("safety_status: %s", result.get("safety_status"))
logger.info("hazard_notes vorhanden: %s", "hazard_notes" in result)
logger.info("flyability_notes vorhanden: %s", "flyability_notes" in result)

hn = result.get("hazard_notes")
fn = result.get("flyability_notes")
if hn:
    logger.info("hazard_notes.rain: %s", hn.get("rain", "FEHLT"))
    logger.info("hazard_notes.wind: %s", hn.get("wind", "FEHLT"))
    logger.info("hazard_notes keys: %s", list(hn.keys()))
else:
    logger.warning("hazard_notes = %s", hn)

if fn:
    logger.info("flyability_notes.thermal: %s", fn.get("thermal", "FEHLT"))
    logger.info("flyability_notes keys: %s", list(fn.keys()))
else:
    logger.info("flyability_notes = %s (bei not_safe erwartet)", fn)

out = {
    "hazard_notes": result.get("hazard_notes"),
    "flyability_notes": result.get("flyability_notes"),
    "safety_status": result.get("safety_status"),
    "summary": result.get("summary", ""),
}
with open("debug_scripts/hazard_notes_output.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)
logger.info("Ergebnis geschrieben nach debug_scripts/hazard_notes_output.json")
