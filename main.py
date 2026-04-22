"""
Gleitcast - Entry Point.
Wetterdaten laden, Engine initialisieren, Flask starten.
"""

import os
import logging
import threading
import time
from datetime import datetime, timedelta

from dotenv import load_dotenv

load_dotenv()

import config
from chat_engine import GleitcastEngine
from instantdb_client import InstantDBClient
from web import app, init_app

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


def daily_refresh(engine, refresh_hour=6):
    """Hintergrund-Thread: Wetterdaten taeglich um refresh_hour Uhr neu laden."""
    while True:
        now = datetime.now()
        # Naechster Refresh-Zeitpunkt
        next_refresh = now.replace(hour=refresh_hour, minute=0, second=0, microsecond=0)
        if now >= next_refresh:
            next_refresh = next_refresh + timedelta(days=1)

        wait_seconds = (next_refresh - now).total_seconds()
        logger.info(f"Naechster Wetter-Refresh in {wait_seconds/3600:.1f}h ({next_refresh.strftime('%Y-%m-%d %H:%M')})")
        time.sleep(wait_seconds)

        logger.info("Starte taeglichen Wetter-Refresh...")
        try:
            engine.refresh_weather()
            logger.info("Wetter-Refresh erfolgreich.")
        except Exception as e:
            logger.error(f"Wetter-Refresh fehlgeschlagen: {e}")


def main():
    logger.info("=== Gleitcast startet ===")

    # InstantDB-Client: abgeschaltet wenn Supabase konfiguriert ist.
    # Supabase Realtime uebernimmt Frontend-Sync → InstantDB-Push ist redundant.
    instantdb = None
    supabase_active = bool(os.environ.get("SUPABASE_URL", "").strip()
                           and os.environ.get("SUPABASE_ANON_KEY", "").strip())
    if supabase_active:
        logger.info("Supabase aktiv → InstantDB deaktiviert (Realtime via Postgres)")
    elif config.INSTANTDB_ADMIN_TOKEN:
        instantdb = InstantDBClient(
            app_id=config.INSTANTDB_APP_ID,
            admin_token=config.INSTANTDB_ADMIN_TOKEN,
            api_url=config.INSTANTDB_API_URL,
        )
        logger.info("InstantDB-Client initialisiert (Fallback-Modus)")
    else:
        logger.info("Weder Supabase noch InstantDB konfiguriert — nur lokale JSON-Caches")

    # Engine initialisieren
    engine = GleitcastEngine(instantdb_client=instantdb)

    # Wetterdaten aus lokalem Cache laden (kein API-Call, nur JSON lesen)
    try:
        engine.load_weather_from_cache()
    except Exception as e:
        logger.error(f"Cache-Laden fehlgeschlagen: {e}")
        logger.info("Wetterdaten: Manuell via UI laden (Button 'Wetterdaten laden')")

    # Spots nach InstantDB synchronisieren
    if instantdb:
        try:
            engine.sync_spots_to_instantdb()
        except Exception as e:
            logger.error(f"InstantDB Spots-Sync fehlgeschlagen: {e}")

    # Flask-App mit Engine verbinden
    init_app(engine)

    # Hintergrund-Thread fuer taeglichen Refresh
    refresh_thread = threading.Thread(target=daily_refresh, args=(engine,), daemon=True)
    refresh_thread.start()

    # Hintergrund-Thread fuer Briefing-Versand Mo/Mi/Fr 06:30.
    # Mit GLEITCAST_BRIEFINGS=0 deaktivierbar (z.B. in Dev-Umgebung).
    briefings_enabled = os.environ.get("GLEITCAST_BRIEFINGS", "1").strip() != "0"
    if briefings_enabled:
        from scheduler import briefing_scheduler
        scheduler_thread = threading.Thread(
            target=briefing_scheduler, args=(engine,), daemon=True,
            name="briefing-scheduler",
        )
        scheduler_thread.start()
        logger.info("Briefing-Scheduler gestartet (Mo/Mi/Fr 06:30)")
    else:
        logger.info("Briefing-Scheduler deaktiviert (GLEITCAST_BRIEFINGS=0)")

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
