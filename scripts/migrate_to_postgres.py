"""
One-shot Migrations-Script: Laedt die bestehenden JSON-Files in Postgres.

Voraussetzungen:
  1. Schema installiert: migrations/001_initial_schema.sql im Supabase SQL Editor ausgefuehrt
  2. .env enthaelt SUPABASE_DATABASE_URL (Pooler-URL, Port 6543)
  3. psycopg installiert: `pip install -r requirements.txt`

Ausfuehren:
    python scripts/migrate_to_postgres.py

Idempotent: Kann beliebig oft laufen (UPSERT statt INSERT). Alte Daten werden
ueberschrieben, neue hinzugefuegt.

Was migriert wird:
  - data/wetterdaten.json     → weather_meta + forecasts + regions_forecasts
  - data/spot_analyses.json   → spot_analyses
  - data/region_analyses.json → region_analyses

Was NICHT migriert wird:
  - data/station_observations.db  (bleibt SQLite lokal)
  - data/weekly_briefing.json     (separat, nicht im Scope)
"""

import json
import logging
import sys
import time
from pathlib import Path

# Projektroot zum Python-Path hinzufuegen, damit "import supabase_client" klappt
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from supabase_client import get_client_from_env  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def load_json(path: Path):
    if not path.exists():
        logger.warning("File fehlt: %s — ueberspringen", path)
        return None
    logger.info("Lese %s (%.1f MB)...", path.name, path.stat().st_size / 1_048_576)
    t0 = time.time()
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    logger.info("  gelesen in %.1fs", time.time() - t0)
    return data


def migrate_weather(client, wetter_path: Path):
    """wetterdaten.json → weather_meta + forecasts + regions_forecasts."""
    data = load_json(wetter_path)
    if not data:
        return

    # _meta
    meta = data.get("_meta")
    if meta:
        ok = client.upsert_weather_meta(meta)
        logger.info("weather_meta: %s", "OK" if ok else "FAIL")

    # _regions
    regions = data.get("_regions") or {}
    if regions:
        t0 = time.time()
        n = client.upsert_regions_forecasts(regions)
        logger.info("regions_forecasts: %d Zeilen in %.1fs", n, time.time() - t0)

    # Spots (alles ausser _meta / _regions)
    spots = {k: v for k, v in data.items() if not k.startswith("_")}
    if spots:
        t0 = time.time()
        n = client.upsert_forecasts(spots)
        logger.info("forecasts: %d Spots in %.1fs", n, time.time() - t0)


def migrate_spot_analyses(client, path: Path):
    data = load_json(path)
    if not data:
        return
    t0 = time.time()
    n = client.upsert_spot_analyses(data)
    logger.info("spot_analyses: %d Zeilen in %.1fs", n, time.time() - t0)


def migrate_region_analyses(client, path: Path):
    data = load_json(path)
    if not data:
        return
    t0 = time.time()
    n = client.upsert_region_analyses(data)
    logger.info("region_analyses: %d Zeilen in %.1fs", n, time.time() - t0)


def main():
    client = get_client_from_env()
    if client is None:
        logger.error(
            "SUPABASE_DATABASE_URL nicht gesetzt. "
            "Bitte .env ergaenzen (siehe .env.example) und erneut ausfuehren."
        )
        sys.exit(1)

    if not client.ping():
        logger.error("Datenbank nicht erreichbar. DATABASE_URL pruefen.")
        sys.exit(2)
    logger.info("DB-Verbindung OK")

    data_dir = PROJECT_ROOT / "data"

    logger.info("=" * 60)
    logger.info("Schritt 1/3: Wetterdaten")
    logger.info("=" * 60)
    migrate_weather(client, data_dir / "wetterdaten.json")

    logger.info("=" * 60)
    logger.info("Schritt 2/3: Spot-Analysen")
    logger.info("=" * 60)
    migrate_spot_analyses(client, data_dir / "spot_analyses.json")

    logger.info("=" * 60)
    logger.info("Schritt 3/3: Region-Analysen")
    logger.info("=" * 60)
    migrate_region_analyses(client, data_dir / "region_analyses.json")

    # Post-Check: Zeilen-Counts
    logger.info("=" * 60)
    logger.info("Verify")
    logger.info("=" * 60)
    try:
        with client._cursor() as (_, cur):
            for table in ("weather_meta", "forecasts", "regions_forecasts",
                          "spot_analyses", "region_analyses"):
                cur.execute(f"SELECT COUNT(*) FROM {table}")
                n = cur.fetchone()[0]
                logger.info("  %s: %d Zeilen", table, n)
    except Exception as e:
        logger.error("Verify fehlgeschlagen: %s", e)

    client.close()
    logger.info("Fertig.")


if __name__ == "__main__":
    main()
