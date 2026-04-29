"""Lokaler Smoke-Lauf: Wetterdaten holen + LLM-Analyse einmal durchziehen.

Aequivalent zu dem was der Daily-Scheduler macht, ABER:
- ohne Briefing-Versand
- ohne Mails
- nur die Pipeline-Schritte: refresh_weather() -> run_all_analyses_stream()

Schreibt nach den ueblichen Pfaden:
- data/<weather-cache>
- data/spot_analyses.json
- data/region_analyses.json
- data/cost_telemetry.jsonl  (eine neue Zeile)

Aufruf:
    GLEITCAST_SPOT_CSV=test python cost_testing/analyze_once.py
    # oder ohne ENV: nutzt config.py-Default (complete = 487 Spots, dauert lang)

Empfohlene lokale Variante (28 Spots, ~3-5 Min):
    export GLEITCAST_SPOT_CSV=test
    python cost_testing/analyze_once.py
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("analyze_once")

# .env automatisch laden, damit OPENAI_API_KEY etc. da sind
try:
    from dotenv import load_dotenv
    load_dotenv(_REPO / ".env")
except ImportError:
    logger.warning("python-dotenv nicht installiert — ENV muss manuell gesetzt sein")


def main() -> int:
    import config
    import config_overrides
    config_overrides.init()  # UI-Overlay anwenden (LLM_ANALYSIS_MODE etc.)

    logger.info("LLM_ANALYSIS_MODE=%s, ANALYSIS_PROVIDER=%s, MODEL=%s",
                config.LLM_ANALYSIS_MODE, config.ANALYSIS_PROVIDER,
                config.LLM_MODELS.get(config.ANALYSIS_PROVIDER, {}).get("analysis"))
    logger.info("Spot-CSV: %s", config.CSV_PATH)
    logger.info("Cost-Telemetry-Datei: %s", config.COST_TELEMETRY_PATH)

    from chat_engine import GleitcastEngine
    eng = GleitcastEngine()

    logger.info("=== Schritt 1: Wetterdaten holen ===")
    try:
        eng.refresh_weather()
    except Exception:
        logger.exception("Wetter-Refresh fehlgeschlagen")
        return 2

    logger.info("=== Schritt 2: LLM-Analyse ===")
    got_done = False
    last_error = None
    for evt in eng.run_all_analyses_stream():
        ev = (evt or {}).get("event")
        data = (evt or {}).get("data", {}) or {}
        if ev == "init":
            logger.info("INIT: %s", data)
        elif ev == "phase":
            logger.info("PHASE: %s", data.get("phase"))
        elif ev == "progress":
            logger.info("PROGRESS: %s/%s in %s",
                        data.get("completed"), data.get("total"), data.get("phase"))
        elif ev == "done":
            got_done = True
            logger.info("DONE: total_calls=%s safety=%s flyability=%s skip=%s est_usd=%s dur=%ss",
                        data.get("total_calls"), data.get("safety_count"),
                        data.get("flyability_count"), data.get("prefilter_skipped"),
                        data.get("est_usd"), data.get("duration_s"))
        elif ev == "error":
            last_error = data.get("message")
            logger.error("ERROR-Event: %s", last_error)

    if not got_done:
        logger.error("Lauf hat 'done' nicht erreicht (last_error=%s)", last_error)
        return 1

    logger.info("Analyse-Lauf abgeschlossen. Pruefe data/cost_telemetry.jsonl.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
