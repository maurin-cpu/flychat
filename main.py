"""
Gleitcast - Entry Point.
Wetterdaten laden, Engine initialisieren, Flask starten.
"""

import os
import logging
import threading

from dotenv import load_dotenv

load_dotenv()

import config
import config_overrides
config_overrides.init()  # Snapshottet Defaults + wendet data/config_overrides.json an
from chat_engine import GleitcastEngine
from web import app, init_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    logger.info("=== Gleitcast startet ===")

    # Engine initialisieren
    engine = GleitcastEngine()

    # Wetterdaten aus lokalem Cache laden (kein API-Call, nur JSON lesen)
    try:
        engine.load_weather_from_cache()
    except Exception as e:
        logger.error(f"Cache-Laden fehlgeschlagen: {e}")
        logger.info("Wetterdaten: Manuell via UI laden (Button 'Wetterdaten laden')")

    # Flask-App mit Engine verbinden
    init_app(engine)

    # Hintergrund-Thread fuer Daily-Run (Wetter-Refresh -> LLM-Analyse -> Mails).
    # Zeitplan via config.DAILY_RUN_{WEEKDAYS,HOUR,MINUTE}.
    # Mit GLEITCAST_BRIEFINGS=0 deaktivierbar — dann findet AUCH KEIN taeglicher
    # Wetter-Refresh mehr statt (Cache bleibt stale bis zum naechsten Restart).
    briefings_enabled = os.environ.get("GLEITCAST_BRIEFINGS", "1").strip() != "0"
    if briefings_enabled:
        from scheduler import briefing_scheduler
        scheduler_thread = threading.Thread(
            target=briefing_scheduler, args=(engine,), daemon=True,
            name="daily-scheduler",
        )
        scheduler_thread.start()
        logger.info(
            "Daily-Scheduler gestartet: Wochentage=%s, Uhrzeit=%02d:%02d",
            sorted(config.DAILY_RUN_WEEKDAYS),
            config.DAILY_RUN_HOUR, config.DAILY_RUN_MINUTE,
        )
    else:
        logger.info("Daily-Scheduler deaktiviert (GLEITCAST_BRIEFINGS=0)")

    # Flask starten
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "true").lower() == "true"
    # Reloader DEAKTIVIERT: Der Watchdog auf Windows/OneDrive erkennt staendig
    # Dateiänderungen (OneDrive-Sync, Cache-Writes, sogar Python-Stdlib) und
    # startet den Server neu — das killt laufende SSE-Verbindungen und Analysen.
    # Debug-Modus (Debugger, Tracebacks) bleibt aktiv.
    use_reloader = os.environ.get("FLASK_RELOADER", "false").lower() == "true"
    logger.info(f"Flask startet auf Port {port} (debug={debug}, reloader={use_reloader})")
    app.run(host="0.0.0.0", port=port, debug=debug, use_reloader=use_reloader)


if __name__ == "__main__":
    main()
