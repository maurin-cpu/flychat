"""
Supabase / Postgres Client fuer Gleitcast.

Ersetzt die JSON-Files (wetterdaten.json, spot_analyses.json, region_analyses.json)
und den InstantDB-Push-Pfad durch eine gemanagte Postgres-DB mit Supabase-Realtime.

Design:
  - Methoden liefern die gleiche Datenstruktur wie vorher die JSON-Files
    → minimaler Refactor im bestehenden Code
  - Soft-Fail: Bei DB-Fehler wird geloggt + None/Leeres zurueckgegeben
    → Aufrufer kann Fallback auf JSON-File ausfuehren
  - Connection-Pooling via psycopg_pool (min=1, max=5)

Schema: siehe migrations/001_initial_schema.sql
"""

import json
import logging
from contextlib import contextmanager
from typing import Any

logger = logging.getLogger(__name__)

try:
    import psycopg
    from psycopg.types.json import Jsonb
    from psycopg_pool import ConnectionPool
    _PSYCOPG_AVAILABLE = True
except ImportError:
    _PSYCOPG_AVAILABLE = False


class SupabaseClient:
    """Postgres-Client via psycopg3. Alle Methoden soft-fail."""

    def __init__(self, database_url: str, min_size: int = 1, max_size: int = 5):
        if not _PSYCOPG_AVAILABLE:
            raise RuntimeError(
                "psycopg nicht installiert. Siehe requirements.txt "
                "(psycopg[binary,pool]>=3.1.0)."
            )
        self.database_url = database_url
        # Lazy-Pool: erst bei erstem Zugriff oeffnen, damit Imports nicht
        # beim App-Start blockieren wenn DB offline.
        self._pool = None
        self._pool_lock_args = dict(min_size=min_size, max_size=max_size)

    def _get_pool(self) -> "ConnectionPool":
        if self._pool is None:
            # prepare_threshold=None deaktiviert automatische Prepared Statements.
            # Noetig fuer Supabase Transaction Pooler (pgbouncer), weil Connections
            # zwischen Clients geteilt werden → "prepared statement already exists".
            self._pool = ConnectionPool(
                self.database_url,
                min_size=self._pool_lock_args["min_size"],
                max_size=self._pool_lock_args["max_size"],
                kwargs={"autocommit": False, "prepare_threshold": None},
                open=True,
            )
        return self._pool

    @contextmanager
    def _cursor(self):
        """Yields (conn, cur). Commits bei Success, rollbackt bei Exception."""
        pool = self._get_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                yield conn, cur

    def ping(self) -> bool:
        """True wenn DB erreichbar."""
        try:
            with self._cursor() as (_, cur):
                cur.execute("SELECT 1")
                return cur.fetchone()[0] == 1
        except Exception as e:
            logger.error("Supabase ping failed: %s", e)
            return False

    # ========================================================================
    # WEATHER_META (single row)
    # ========================================================================
    def upsert_weather_meta(self, meta: dict) -> bool:
        """Ersetzt den _meta-Block aus wetterdaten.json."""
        try:
            with self._cursor() as (conn, cur):
                cur.execute(
                    """
                    INSERT INTO weather_meta (id, last_updated, spots_count,
                        forecast_days, fetch_status, fetch_status_reason, payload)
                    VALUES ('global', %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO UPDATE SET
                        last_updated = EXCLUDED.last_updated,
                        spots_count = EXCLUDED.spots_count,
                        forecast_days = EXCLUDED.forecast_days,
                        fetch_status = EXCLUDED.fetch_status,
                        fetch_status_reason = EXCLUDED.fetch_status_reason,
                        payload = EXCLUDED.payload
                    """,
                    (
                        meta.get("last_updated"),
                        meta.get("spots_count"),
                        meta.get("forecast_days"),
                        meta.get("fetch_status"),
                        meta.get("fetch_status_reason"),
                        Jsonb(meta),
                    ),
                )
                conn.commit()
                return True
        except Exception as e:
            logger.error("upsert_weather_meta failed: %s", e)
            return False

    def get_weather_meta(self) -> dict | None:
        try:
            with self._cursor() as (_, cur):
                cur.execute("SELECT payload FROM weather_meta WHERE id='global'")
                row = cur.fetchone()
                return row[0] if row else None
        except Exception as e:
            logger.error("get_weather_meta failed: %s", e)
            return None

    # ========================================================================
    # FORECASTS (per spot)
    # ========================================================================
    def upsert_forecasts(self, forecasts: dict[str, dict]) -> int:
        """Schreibt alle Spot-Forecasts in einem Batch. `forecasts` = {spot_name: spot_data}.

        Ersetzt den pro-Spot-Teil von wetterdaten.json.
        """
        if not forecasts:
            return 0
        rows = []
        for name, data in forecasts.items():
            rows.append((
                name,
                data.get("latitude"),
                data.get("longitude"),
                data.get("elevation_m"),
                Jsonb(data),
            ))
        try:
            with self._cursor() as (conn, cur):
                cur.executemany(
                    """
                    INSERT INTO forecasts (spot_name, latitude, longitude, elevation_m, payload)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (spot_name) DO UPDATE SET
                        latitude = EXCLUDED.latitude,
                        longitude = EXCLUDED.longitude,
                        elevation_m = EXCLUDED.elevation_m,
                        payload = EXCLUDED.payload
                    """,
                    rows,
                )
                conn.commit()
                return len(rows)
        except Exception as e:
            logger.error("upsert_forecasts failed (%d rows): %s", len(rows), e)
            return 0

    def get_all_forecasts(self) -> dict[str, dict]:
        """Liefert {spot_name: spot_data_dict}. Leer bei Fehler."""
        try:
            with self._cursor() as (_, cur):
                cur.execute("SELECT spot_name, payload FROM forecasts")
                return {name: payload for name, payload in cur.fetchall()}
        except Exception as e:
            logger.error("get_all_forecasts failed: %s", e)
            return {}

    def get_forecast(self, spot_name: str) -> dict | None:
        try:
            with self._cursor() as (_, cur):
                cur.execute("SELECT payload FROM forecasts WHERE spot_name = %s", (spot_name,))
                row = cur.fetchone()
                return row[0] if row else None
        except Exception as e:
            logger.error("get_forecast(%s) failed: %s", spot_name, e)
            return None

    # ========================================================================
    # REGIONS_FORECASTS (per region)
    # ========================================================================
    def upsert_regions_forecasts(self, regions: dict[str, dict]) -> int:
        if not regions:
            return 0
        rows = []
        for rid, data in regions.items():
            rows.append((
                rid,
                data.get("region_name"),
                data.get("elevation_ref"),
                Jsonb(data),
            ))
        try:
            with self._cursor() as (conn, cur):
                cur.executemany(
                    """
                    INSERT INTO regions_forecasts (region_id, region_name, elevation_ref, payload)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (region_id) DO UPDATE SET
                        region_name = EXCLUDED.region_name,
                        elevation_ref = EXCLUDED.elevation_ref,
                        payload = EXCLUDED.payload
                    """,
                    rows,
                )
                conn.commit()
                return len(rows)
        except Exception as e:
            logger.error("upsert_regions_forecasts failed: %s", e)
            return 0

    def get_all_regions_forecasts(self) -> dict[str, dict]:
        try:
            with self._cursor() as (_, cur):
                cur.execute("SELECT region_id, payload FROM regions_forecasts")
                return {rid: payload for rid, payload in cur.fetchall()}
        except Exception as e:
            logger.error("get_all_regions_forecasts failed: %s", e)
            return {}

    # ========================================================================
    # SPOT_ANALYSES (per spot × date)
    # ========================================================================
    def upsert_spot_analyses(self, analyses: dict[str, dict[str, dict]]) -> int:
        """`analyses` = {spot_name: {date_str: payload}}. Format wie spot_analyses.json."""
        if not analyses:
            return 0
        rows = []
        for spot_name, by_date in analyses.items():
            if not isinstance(by_date, dict):
                continue
            for date_str, payload in by_date.items():
                rows.append((spot_name, date_str, Jsonb(payload)))
        if not rows:
            return 0
        try:
            with self._cursor() as (conn, cur):
                cur.executemany(
                    """
                    INSERT INTO spot_analyses (spot_name, analysis_date, payload)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (spot_name, analysis_date) DO UPDATE SET
                        payload = EXCLUDED.payload
                    """,
                    rows,
                )
                conn.commit()
                return len(rows)
        except Exception as e:
            logger.error("upsert_spot_analyses failed (%d rows): %s", len(rows), e)
            return 0

    def get_all_spot_analyses(self) -> dict[str, dict[str, dict]]:
        """Liefert {spot_name: {date_str: payload}} — Format wie spot_analyses.json."""
        try:
            with self._cursor() as (_, cur):
                cur.execute(
                    "SELECT spot_name, to_char(analysis_date, 'YYYY-MM-DD'), payload "
                    "FROM spot_analyses"
                )
                result: dict[str, dict[str, dict]] = {}
                for spot, date_str, payload in cur.fetchall():
                    result.setdefault(spot, {})[date_str] = payload
                return result
        except Exception as e:
            logger.error("get_all_spot_analyses failed: %s", e)
            return {}

    def delete_spot_analyses(self) -> bool:
        try:
            with self._cursor() as (conn, cur):
                cur.execute("DELETE FROM spot_analyses")
                conn.commit()
                return True
        except Exception as e:
            logger.error("delete_spot_analyses failed: %s", e)
            return False

    # ========================================================================
    # REGION_ANALYSES (per region × date)
    # ========================================================================
    def upsert_region_analyses(self, analyses: dict[str, dict[str, dict]]) -> int:
        if not analyses:
            return 0
        rows = []
        for region_id, by_date in analyses.items():
            if not isinstance(by_date, dict):
                continue
            for date_str, payload in by_date.items():
                rows.append((region_id, date_str, Jsonb(payload)))
        if not rows:
            return 0
        try:
            with self._cursor() as (conn, cur):
                cur.executemany(
                    """
                    INSERT INTO region_analyses (region_id, analysis_date, payload)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (region_id, analysis_date) DO UPDATE SET
                        payload = EXCLUDED.payload
                    """,
                    rows,
                )
                conn.commit()
                return len(rows)
        except Exception as e:
            logger.error("upsert_region_analyses failed (%d rows): %s", len(rows), e)
            return 0

    def get_all_region_analyses(self) -> dict[str, dict[str, dict]]:
        try:
            with self._cursor() as (_, cur):
                cur.execute(
                    "SELECT region_id, to_char(analysis_date, 'YYYY-MM-DD'), payload "
                    "FROM region_analyses"
                )
                result: dict[str, dict[str, dict]] = {}
                for rid, date_str, payload in cur.fetchall():
                    result.setdefault(rid, {})[date_str] = payload
                return result
        except Exception as e:
            logger.error("get_all_region_analyses failed: %s", e)
            return {}

    def delete_region_analyses(self) -> bool:
        try:
            with self._cursor() as (conn, cur):
                cur.execute("DELETE FROM region_analyses")
                conn.commit()
                return True
        except Exception as e:
            logger.error("delete_region_analyses failed: %s", e)
            return False

    def close(self):
        if self._pool is not None:
            self._pool.close()
            self._pool = None


def get_client_from_env() -> SupabaseClient | None:
    """Factory: liest SUPABASE_DATABASE_URL aus os.environ, gibt None wenn nicht gesetzt."""
    import os
    url = os.environ.get("SUPABASE_DATABASE_URL", "").strip()
    if not url:
        return None
    try:
        return SupabaseClient(url)
    except Exception as e:
        logger.error("SupabaseClient init failed: %s", e)
        return None
