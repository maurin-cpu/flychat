"""
Subscriber-Management fuer das E-Mail-Briefing.

Persistenz: SQLite (data/subscribers.db) — gleiches Muster wie station_observations.py.
Soft-Fail: Fehler werden geloggt, None/leeres Dict zurueckgegeben.
Keine Session/Auth — alle User-Aktionen passwordless via Tokens.

Schema-Unterschiede vs. ursprünglicher Postgres-Variante:
  - regions ist JSON-String statt TEXT[] (SQLite kennt keine Arrays)
  - Timestamps als ISO-Text (CURRENT_TIMESTAMP), kein TIMESTAMPTZ
  - Auto-resume verwendet datetime('now') statt CURRENT_DATE
  - Datums-Arithmetik fuer Feedback: datetime('now', '-N days')
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# Simple RFC-5322-kompatible E-Mail-Validierung (bewusst pragmatisch, nicht vollstaendig).
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def is_valid_email(email: str) -> bool:
    if not email or len(email) > 254:
        return False
    return bool(_EMAIL_RE.match(email.strip()))


def generate_token(nbytes: int = 24) -> str:
    """URL-safe Token (~32 Zeichen bei 24 Bytes). Kollisions-Chance vernachlaessigbar."""
    return secrets.token_urlsafe(nbytes)


# Schreib-Lock: SQLite serialisiert Writes ohnehin, aber expliziter Lock vermeidet
# busy-waits und macht das Verhalten unter Threads deterministisch.
_WRITE_LOCK = threading.Lock()


class SubscriberManager:
    """CRUD fuer subscribers + subscriber_feedback (SQLite)."""

    def __init__(self, db_path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    @contextmanager
    def _cursor(self, write: bool = False):
        """Yields cursor. Commits am Ende, rollback bei Exception.
        write=True nimmt den globalen Schreib-Lock."""
        if write:
            _WRITE_LOCK.acquire()
        conn = self._connect()
        try:
            cur = conn.cursor()
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
            if write:
                _WRITE_LOCK.release()

    @staticmethod
    def _migrate_add_column(conn, table: str, column: str, definition: str):
        """Idempotentes ADD COLUMN — pruef vorhandene Spalten via PRAGMA table_info."""
        cur = conn.execute(f"PRAGMA table_info({table})")
        existing = {row[1] for row in cur.fetchall()}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    # Region-ID-Renames (CSV/GeoJSON-Sync 2026-04: alte GeoJSON-IDs ohne CSV-Match
    # auf gemeinsame snake_case-Form gebracht). Idempotent: WHERE LIKE matcht nichts
    # mehr, sobald der Rename gelaufen ist.
    _REGION_ID_RENAMES = (
        ("urner_alpen",        "bodenseeraum"),
        ("chur_mittelbuenden", "praettigau_davos"),
        ("suedbuenden",        "rheintal"),
    )

    @classmethod
    def _migrate_rename_region_ids(cls, conn):
        for old, new in cls._REGION_ID_RENAMES:
            old_token = f'"{old}"'
            new_token = f'"{new}"'
            cur = conn.execute(
                "UPDATE subscribers "
                "SET regions = REPLACE(regions, ?, ?) "
                "WHERE regions LIKE ?",
                (old_token, new_token, f"%{old_token}%"),
            )
            if cur.rowcount:
                logger.info(
                    "Region-ID-Migration: %r -> %r in %d subscriber-Zeile(n) ersetzt",
                    old, new, cur.rowcount,
                )

    def _init_db(self):
        conn = self._connect()
        try:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS subscribers (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    email           TEXT UNIQUE NOT NULL,
                    -- regions als JSON-Array (SQLite hat keine native Array-Spalte)
                    regions         TEXT NOT NULL DEFAULT '[]',
                    skill_level     TEXT NOT NULL DEFAULT 'standard'
                                    CHECK (skill_level IN ('beginner', 'standard', 'expert')),
                    status          TEXT NOT NULL DEFAULT 'pending'
                                    CHECK (status IN ('pending', 'active', 'paused', 'unsubscribed')),
                    -- Pause-Zeitraum (Range): paused_from <= heute <= paused_until -> aktuell pausiert.
                    -- paused_from > heute -> zukuenftige Pause (User ist noch aktiv).
                    paused_from     TEXT,                                       -- ISO 'YYYY-MM-DD' oder NULL
                    paused_until    TEXT,                                       -- ISO 'YYYY-MM-DD' oder NULL
                    confirm_token   TEXT UNIQUE,
                    action_token    TEXT UNIQUE NOT NULL,
                    -- Wochentage als CSV '0,1,2,3,4,5,6' (0=Mo, 6=So); leer = keine Versandtage
                    active_weekdays TEXT NOT NULL DEFAULT '0,1,2,3,4,5,6',
                    -- Welche Qualitaets-Tiers im Briefing erscheinen sollen (JSON-Array)
                    -- Default: violet+green+conditional (gray/bronze opt-in)
                    min_tier_set    TEXT NOT NULL DEFAULT '["violet","green","conditional"]',
                    -- Mindest-Rating fuer Briefing-Listing (0.0..10.0); 0 = alle
                    min_rating      REAL NOT NULL DEFAULT 0.0,
                    -- Magic-Link Login (One-Time-Token, 30min Gueltigkeit)
                    login_token            TEXT UNIQUE,
                    login_token_expires_at TEXT,
                    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
                    confirmed_at    TEXT,
                    last_sent_at    TEXT,
                    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
                );

                -- Idempotente Migrationen fuer bestehende DBs (ALTER TABLE ADD COLUMN ist safe)
            """)
            self._migrate_add_column(conn, "subscribers", "active_weekdays",
                                     "TEXT NOT NULL DEFAULT '0,1,2,3,4,5,6'")
            self._migrate_add_column(conn, "subscribers", "paused_from", "TEXT")
            self._migrate_add_column(conn, "subscribers", "min_tier_set",
                                     "TEXT NOT NULL DEFAULT '[\"violet\",\"green\",\"conditional\"]'")
            self._migrate_add_column(conn, "subscribers", "min_rating",
                                     "REAL NOT NULL DEFAULT 0.0")
            self._migrate_add_column(conn, "subscribers", "login_token", "TEXT")
            self._migrate_add_column(conn, "subscribers", "login_token_expires_at", "TEXT")
            conn.executescript("""

                CREATE INDEX IF NOT EXISTS idx_subscribers_status_active
                    ON subscribers (status) WHERE status = 'active';
                CREATE INDEX IF NOT EXISTS idx_subscribers_confirm_token
                    ON subscribers (confirm_token) WHERE confirm_token IS NOT NULL;
                CREATE INDEX IF NOT EXISTS idx_subscribers_action_token
                    ON subscribers (action_token);
                CREATE INDEX IF NOT EXISTS idx_subscribers_login_token
                    ON subscribers (login_token) WHERE login_token IS NOT NULL;

                CREATE TABLE IF NOT EXISTS subscriber_feedback (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    subscriber_id   INTEGER NOT NULL REFERENCES subscribers(id) ON DELETE CASCADE,
                    briefing_date   TEXT NOT NULL,                              -- 'YYYY-MM-DD'
                    verdict         TEXT NOT NULL CHECK (verdict IN ('correct', 'wrong')),
                    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
                );

                CREATE INDEX IF NOT EXISTS idx_subscriber_feedback_subscriber
                    ON subscriber_feedback (subscriber_id);
                CREATE INDEX IF NOT EXISTS idx_subscriber_feedback_date
                    ON subscriber_feedback (briefing_date);

                -- Freitext-Produkt-Feedback (separat von briefing-spezifischem subscriber_feedback)
                CREATE TABLE IF NOT EXISTS product_feedback (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    subscriber_id   INTEGER NOT NULL REFERENCES subscribers(id) ON DELETE CASCADE,
                    message         TEXT NOT NULL,
                    created_at      TEXT NOT NULL DEFAULT (datetime('now'))
                );
                CREATE INDEX IF NOT EXISTS idx_product_feedback_subscriber
                    ON product_feedback (subscriber_id);
                CREATE INDEX IF NOT EXISTS idx_product_feedback_created
                    ON product_feedback (created_at);

                -- updated_at automatisch pflegen
                CREATE TRIGGER IF NOT EXISTS trg_subscribers_updated
                    AFTER UPDATE ON subscribers FOR EACH ROW
                BEGIN
                    UPDATE subscribers SET updated_at = datetime('now') WHERE id = OLD.id;
                END;
            """)
            self._migrate_rename_region_ids(conn)
            conn.commit()
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _regions_to_db(regions) -> str:
        return json.dumps(list(regions or []), ensure_ascii=False)

    @staticmethod
    def _regions_from_db(text) -> list:
        if not text:
            return []
        try:
            val = json.loads(text)
            return list(val) if isinstance(val, list) else []
        except (ValueError, TypeError):
            return []

    _VALID_TIERS = ("violet", "green", "conditional", "gray")

    @staticmethod
    def _tiers_to_db(tiers) -> str:
        """Akzeptiert Liste von Tier-Strings, liefert JSON-Array. Filtert ungueltige."""
        valid = SubscriberManager._VALID_TIERS
        clean = [t for t in (tiers or []) if t in valid]
        return json.dumps(clean, ensure_ascii=False)

    @staticmethod
    def _tiers_from_db(text) -> list:
        if not text:
            return []
        try:
            val = json.loads(text)
            valid = SubscriberManager._VALID_TIERS
            return [t for t in val if t in valid] if isinstance(val, list) else []
        except (ValueError, TypeError):
            return []

    @staticmethod
    def _weekdays_to_db(weekdays) -> str:
        """Akzeptiert Liste von Ints 0..6 oder None. Output: CSV '0,2,4'."""
        if not weekdays:
            return ""
        clean = sorted({int(w) for w in weekdays if 0 <= int(w) <= 6})
        return ",".join(str(w) for w in clean)

    @staticmethod
    def _weekdays_from_db(text) -> list:
        """CSV '0,2,4' -> [0, 2, 4]. Leerer String -> []."""
        if not text:
            return []
        try:
            return sorted({int(p) for p in text.split(",") if p.strip().isdigit()})
        except (ValueError, AttributeError):
            return []

    @staticmethod
    def _date_to_db(d) -> Optional[str]:
        """Akzeptiert datetime.date / ISO-String 'YYYY-MM-DD' / None."""
        if d is None:
            return None
        if hasattr(d, "isoformat"):
            return d.isoformat()
        return str(d)

    def _row_to_subscriber(self, row, keys: tuple) -> Optional[dict]:
        if row is None:
            return None
        out = dict(zip(keys, row))
        if "regions" in out:
            out["regions"] = self._regions_from_db(out["regions"])
        if "active_weekdays" in out:
            out["active_weekdays"] = self._weekdays_from_db(out["active_weekdays"])
        if "min_tier_set" in out:
            out["min_tier_set"] = self._tiers_from_db(out["min_tier_set"])
        return out

    # ------------------------------------------------------------------
    # CREATE / CONFIRM
    # ------------------------------------------------------------------
    def create(
        self,
        email: str,
        regions: list,
        skill_level: str = "standard",
    ) -> Optional[dict]:
        """
        Legt einen pending-Subscriber an. Wenn E-Mail schon existiert:
          - Status 'unsubscribed' -> resubscribe (neues confirm_token, status='pending')
          - Sonst -> None zurueckgeben (Aufrufer zeigt "bereits registriert")
        """
        email_norm = (email or "").strip().lower()
        if not is_valid_email(email_norm):
            logger.warning("create: ungueltige E-Mail '%s'", email_norm)
            return None
        if not regions:
            logger.warning("create: keine Regionen fuer %s", email_norm)
            return None
        if skill_level not in ("beginner", "standard", "expert"):
            skill_level = "standard"

        confirm_token = generate_token()
        action_token = generate_token()
        regions_json = self._regions_to_db(regions)

        try:
            with self._cursor(write=True) as cur:
                cur.execute(
                    "SELECT id, status FROM subscribers WHERE email = ?",
                    (email_norm,),
                )
                existing = cur.fetchone()

                if existing:
                    sub_id, status = existing
                    if status == "unsubscribed":
                        cur.execute(
                            """
                            UPDATE subscribers
                               SET regions = ?,
                                   skill_level = ?,
                                   status = 'pending',
                                   confirm_token = ?,
                                   action_token = ?,
                                   paused_until = NULL,
                                   confirmed_at = NULL
                             WHERE id = ?
                         RETURNING id, email, confirm_token, action_token
                            """,
                            (regions_json, skill_level, confirm_token, action_token, sub_id),
                        )
                        row = cur.fetchone()
                        return self._row_to_subscriber(
                            row, ("id", "email", "confirm_token", "action_token")
                        )
                    return None

                cur.execute(
                    """
                    INSERT INTO subscribers
                        (email, regions, skill_level, confirm_token, action_token)
                    VALUES (?, ?, ?, ?, ?)
                    RETURNING id, email, confirm_token, action_token
                    """,
                    (email_norm, regions_json, skill_level, confirm_token, action_token),
                )
                row = cur.fetchone()
                return self._row_to_subscriber(
                    row, ("id", "email", "confirm_token", "action_token")
                )
        except Exception as e:
            logger.error("create(%s) failed: %s", email_norm, e)
            return None

    def get_by_confirm_token(self, token: str) -> Optional[dict]:
        if not token:
            return None
        try:
            with self._cursor() as cur:
                cur.execute(
                    """
                    SELECT id, email, regions, skill_level, status, action_token
                      FROM subscribers
                     WHERE confirm_token = ?
                    """,
                    (token,),
                )
                row = cur.fetchone()
                return self._row_to_subscriber(
                    row,
                    ("id", "email", "regions", "skill_level", "status", "action_token"),
                )
        except Exception as e:
            logger.error("get_by_confirm_token failed: %s", e)
            return None

    def confirm(self, token: str) -> Optional[dict]:
        """Aktiviert den Subscriber, loescht confirm_token. Idempotent."""
        if not token:
            return None
        try:
            with self._cursor(write=True) as cur:
                cur.execute(
                    """
                    UPDATE subscribers
                       SET status = 'active',
                           confirmed_at = COALESCE(confirmed_at, datetime('now')),
                           confirm_token = NULL
                     WHERE confirm_token = ?
                RETURNING id, email, regions, skill_level, action_token
                    """,
                    (token,),
                )
                row = cur.fetchone()
                return self._row_to_subscriber(
                    row, ("id", "email", "regions", "skill_level", "action_token")
                )
        except Exception as e:
            logger.error("confirm failed: %s", e)
            return None

    # ------------------------------------------------------------------
    # ACTION TOKEN
    # ------------------------------------------------------------------
    def get_by_action_token(self, token: str) -> Optional[dict]:
        if not token:
            return None
        try:
            with self._cursor() as cur:
                cur.execute(
                    """
                    SELECT id, email, regions, skill_level, status,
                           paused_from, paused_until,
                           active_weekdays, min_tier_set, min_rating
                      FROM subscribers
                     WHERE action_token = ?
                    """,
                    (token,),
                )
                row = cur.fetchone()
                return self._row_to_subscriber(
                    row,
                    ("id", "email", "regions", "skill_level", "status",
                     "paused_from", "paused_until",
                     "active_weekdays", "min_tier_set", "min_rating"),
                )
        except Exception as e:
            logger.error("get_by_action_token failed: %s", e)
            return None

    def unsubscribe(self, token: str) -> bool:
        if not token:
            return False
        try:
            with self._cursor(write=True) as cur:
                cur.execute(
                    "UPDATE subscribers SET status = 'unsubscribed' WHERE action_token = ?",
                    (token,),
                )
                return cur.rowcount > 0
        except Exception as e:
            logger.error("unsubscribe failed: %s", e)
            return False

    def pause(self, token: str, until_date, from_date=None) -> bool:
        """Pausiert Briefing fuer einen Zeitraum [from_date, until_date].
        - from_date None oder <= heute -> Pause beginnt heute (sofort wirksam)
        - from_date in Zukunft        -> geplante Pause (Status bleibt 'active' bis dahin,
                                          Wechsel passiert automatisch in list_active)
        - until_date Pflicht
        """
        until_str = self._date_to_db(until_date)
        from_str = self._date_to_db(from_date) if from_date else None
        if not token or not until_str:
            return False
        # Validierung: until >= from
        if from_str and from_str > until_str:
            logger.warning("pause: from > until ignored")
            return False
        try:
            with self._cursor(write=True) as cur:
                # Wenn Pause schon JETZT gilt, status='paused' direkt setzen.
                # Wenn nur in Zukunft, status bleibt 'active' (Pause greift via list_active).
                # Vereinfachung: status sagt nichts ueber "aktuell pausiert" aus, wenn
                # Range-Felder gesetzt sind. list_active prueft die Range.
                from datetime import date as _d
                today = _d.today().isoformat()
                effective_from = from_str or today
                new_status = "paused" if effective_from <= today else "active"
                cur.execute(
                    """
                    UPDATE subscribers
                       SET status = ?,
                           paused_from = ?,
                           paused_until = ?
                     WHERE action_token = ?
                       AND status IN ('active', 'paused')
                    """,
                    (new_status, effective_from, until_str, token),
                )
                return cur.rowcount > 0
        except Exception as e:
            logger.error("pause failed: %s", e)
            return False

    def resume(self, token: str) -> bool:
        """Hebt Pause auf — auch geplante zukuenftige Pausen. Setzt beide Datums-Felder zurueck."""
        if not token:
            return False
        try:
            with self._cursor(write=True) as cur:
                cur.execute(
                    """
                    UPDATE subscribers
                       SET status = 'active',
                           paused_from = NULL,
                           paused_until = NULL
                     WHERE action_token = ?
                       AND status IN ('paused', 'active')
                    """,
                    (token,),
                )
                return cur.rowcount > 0
        except Exception as e:
            logger.error("resume failed: %s", e)
            return False

    # ------------------------------------------------------------------
    # LIST / FEEDBACK
    # ------------------------------------------------------------------
    def list_active(self) -> list:
        """Alle Subscriber, an die heute versendet werden soll.
        Range-aware: pausiert NUR wenn paused_from <= heute <= paused_until.
        Geplante Zukunfts-Pause -> User ist heute noch aktiv.
        Vergangene Pause -> auto-Cleanup (status='active', dates=NULL)."""
        try:
            with self._cursor(write=True) as cur:
                # Auto-Cleanup: Pause vorbei (paused_until < heute) -> reaktivieren
                cur.execute(
                    """
                    UPDATE subscribers
                       SET status = 'active',
                           paused_from = NULL,
                           paused_until = NULL
                     WHERE status = 'paused'
                       AND paused_until IS NOT NULL
                       AND paused_until < date('now')
                    """
                )
                # Auto-Aktivierung: geplante Pause beginnt heute -> status='paused'
                cur.execute(
                    """
                    UPDATE subscribers
                       SET status = 'paused'
                     WHERE status = 'active'
                       AND paused_from IS NOT NULL
                       AND paused_from <= date('now')
                       AND paused_until IS NOT NULL
                       AND paused_until >= date('now')
                    """
                )
                # Versand: status='active' UND nicht in aktiver Pause-Range
                cur.execute(
                    """
                    SELECT id, email, regions, skill_level, action_token, active_weekdays,
                           min_tier_set, min_rating
                      FROM subscribers
                     WHERE status = 'active'
                       AND NOT (paused_from IS NOT NULL
                                AND paused_until IS NOT NULL
                                AND paused_from <= date('now')
                                AND paused_until >= date('now'))
                     ORDER BY id
                    """
                )
                rows = cur.fetchall()
                keys = ("id", "email", "regions", "skill_level", "action_token",
                        "active_weekdays", "min_tier_set", "min_rating")
                return [self._row_to_subscriber(r, keys) for r in rows]
        except Exception as e:
            logger.error("list_active failed: %s", e)
            return []

    def record_feedback(self, subscriber_id: int, briefing_date, verdict: str) -> bool:
        if verdict not in ("correct", "wrong"):
            return False
        date_str = self._date_to_db(briefing_date)
        try:
            with self._cursor(write=True) as cur:
                cur.execute(
                    """
                    INSERT INTO subscriber_feedback
                        (subscriber_id, briefing_date, verdict)
                    VALUES (?, ?, ?)
                    """,
                    (subscriber_id, date_str, verdict),
                )
                return True
        except Exception as e:
            logger.error("record_feedback failed: %s", e)
            return False

    def get_feedback_stats(self, subscriber_id: int, days: int = 30) -> dict:
        """Zaehlt correct/wrong-Feedbacks der letzten `days` Tage."""
        try:
            with self._cursor() as cur:
                cur.execute(
                    f"""
                    SELECT verdict, COUNT(*)
                      FROM subscriber_feedback
                     WHERE subscriber_id = ?
                       AND created_at >= datetime('now', '-{int(days)} days')
                     GROUP BY verdict
                    """,
                    (subscriber_id,),
                )
                counts = {v: n for v, n in cur.fetchall()}
                correct = counts.get("correct", 0)
                wrong = counts.get("wrong", 0)
                total = correct + wrong
                accuracy = round(100 * correct / total) if total > 0 else None
                return {
                    "total": total, "correct": correct, "wrong": wrong,
                    "accuracy_pct": accuracy, "window_days": days,
                }
        except Exception as e:
            logger.error("get_feedback_stats(%s) failed: %s", subscriber_id, e)
            return {"total": 0, "correct": 0, "wrong": 0, "accuracy_pct": None,
                    "window_days": days}

    # ------------------------------------------------------------------
    # ADMIN-QUERIES
    # ------------------------------------------------------------------
    def count_by_status(self) -> dict:
        # registered_no_sub: Account existiert (status='active'), aber keine
        # Regionen gewaehlt -> registriert, aber kein Briefing-Abo.
        # subscribed: aktive Accounts MIT mindestens einer Region (echtes Abo).
        base = {"active": 0, "pending": 0, "paused": 0, "unsubscribed": 0,
                "registered_no_sub": 0, "subscribed": 0}
        try:
            with self._cursor() as cur:
                cur.execute("SELECT status, COUNT(*) FROM subscribers GROUP BY status")
                for status, n in cur.fetchall():
                    if status in base:
                        base[status] = n
                # Aktive ohne Regionen (leer / NULL / '[]') = nur registriert
                cur.execute(
                    """
                    SELECT COUNT(*) FROM subscribers
                     WHERE status = 'active'
                       AND (regions IS NULL OR regions = '' OR regions = '[]')
                    """
                )
                base["registered_no_sub"] = cur.fetchone()[0]
                base["subscribed"] = base["active"] - base["registered_no_sub"]
                return base
        except Exception as e:
            logger.error("count_by_status failed: %s", e)
            return base

    def list_recent(self, limit: int = 50) -> list:
        """Neueste Subscriber zuerst."""
        try:
            with self._cursor() as cur:
                cur.execute(
                    """
                    SELECT id, email, regions, skill_level, status,
                           paused_until, created_at, confirmed_at, last_sent_at
                      FROM subscribers
                     ORDER BY created_at DESC
                     LIMIT ?
                    """,
                    (int(limit),),
                )
                rows = cur.fetchall()
                keys = ("id", "email", "regions", "skill_level", "status",
                        "paused_until", "created_at", "confirmed_at", "last_sent_at")
                return [self._row_to_subscriber(r, keys) for r in rows]
        except Exception as e:
            logger.error("list_recent failed: %s", e)
            return []

    def count_feedback_overall(self, days: int = 30) -> dict:
        try:
            with self._cursor() as cur:
                cur.execute(
                    f"""
                    SELECT verdict, COUNT(*) FROM subscriber_feedback
                     WHERE created_at >= datetime('now', '-{int(days)} days')
                     GROUP BY verdict
                    """
                )
                counts = {v: n for v, n in cur.fetchall()}
                correct = counts.get("correct", 0)
                wrong = counts.get("wrong", 0)
                total = correct + wrong
                return {
                    "total": total, "correct": correct, "wrong": wrong,
                    "accuracy_pct": round(100 * correct / total) if total > 0 else None,
                    "window_days": days,
                }
        except Exception as e:
            logger.error("count_feedback_overall failed: %s", e)
            return {"total": 0, "correct": 0, "wrong": 0,
                    "accuracy_pct": None, "window_days": days}

    def list_briefing_feedback(self, limit: int = 100) -> list:
        """Neueste Briefing-Verdicts (correct/wrong) inkl. Subscriber-E-Mail."""
        try:
            with self._cursor() as cur:
                cur.execute(
                    """
                    SELECT f.id, f.subscriber_id, s.email, f.briefing_date,
                           f.verdict, f.created_at
                      FROM subscriber_feedback f
                      LEFT JOIN subscribers s ON s.id = f.subscriber_id
                     ORDER BY f.created_at DESC
                     LIMIT ?
                    """,
                    (int(limit),),
                )
                rows = cur.fetchall()
                keys = ("id", "subscriber_id", "email", "briefing_date",
                        "verdict", "created_at")
                return [dict(zip(keys, r)) for r in rows]
        except Exception as e:
            logger.error("list_briefing_feedback failed: %s", e)
            return []

    def list_product_feedback(self, limit: int = 100) -> list:
        """Neueste Freitext-Produktfeedbacks inkl. Subscriber-E-Mail."""
        try:
            with self._cursor() as cur:
                cur.execute(
                    """
                    SELECT pf.id, pf.subscriber_id, s.email, pf.message, pf.created_at
                      FROM product_feedback pf
                      LEFT JOIN subscribers s ON s.id = pf.subscriber_id
                     ORDER BY pf.created_at DESC
                     LIMIT ?
                    """,
                    (int(limit),),
                )
                rows = cur.fetchall()
                keys = ("id", "subscriber_id", "email", "message", "created_at")
                return [dict(zip(keys, r)) for r in rows]
        except Exception as e:
            logger.error("list_product_feedback failed: %s", e)
            return []

    def delete_briefing_feedback(self, feedback_id: int) -> bool:
        try:
            with self._cursor(write=True) as cur:
                cur.execute(
                    "DELETE FROM subscriber_feedback WHERE id = ?",
                    (int(feedback_id),),
                )
                return cur.rowcount > 0
        except Exception as e:
            logger.error("delete_briefing_feedback failed: %s", e)
            return False

    def delete_product_feedback(self, feedback_id: int) -> bool:
        try:
            with self._cursor(write=True) as cur:
                cur.execute(
                    "DELETE FROM product_feedback WHERE id = ?",
                    (int(feedback_id),),
                )
                return cur.rowcount > 0
        except Exception as e:
            logger.error("delete_product_feedback failed: %s", e)
            return False

    def get_by_id(self, subscriber_id: int) -> Optional[dict]:
        try:
            with self._cursor() as cur:
                cur.execute(
                    """
                    SELECT id, email, regions, skill_level, status, action_token
                      FROM subscribers WHERE id = ?
                    """,
                    (subscriber_id,),
                )
                row = cur.fetchone()
                return self._row_to_subscriber(
                    row, ("id", "email", "regions", "skill_level", "status", "action_token")
                )
        except Exception as e:
            logger.error("get_by_id(%s) failed: %s", subscriber_id, e)
            return None

    def block(self, subscriber_id: int) -> bool:
        try:
            with self._cursor(write=True) as cur:
                cur.execute(
                    "UPDATE subscribers SET status='unsubscribed' WHERE id = ?",
                    (subscriber_id,),
                )
                return cur.rowcount > 0
        except Exception as e:
            logger.error("block(%s) failed: %s", subscriber_id, e)
            return False

    def delete(self, subscriber_id: int) -> bool:
        """Hard-Delete: Subscriber-Row entfernen. Feedback-Rows kaskadieren via FK
        ON DELETE CASCADE (siehe Schema). Irreversibel."""
        if not subscriber_id:
            return False
        try:
            with self._cursor(write=True) as cur:
                cur.execute(
                    "DELETE FROM subscribers WHERE id = ?",
                    (int(subscriber_id),),
                )
                return cur.rowcount > 0
        except Exception as e:
            logger.error("delete(%s) failed: %s", subscriber_id, e)
            return False

    def delete_by_token(self, action_token: str) -> bool:
        """Self-Service Delete via action_token (DSGVO/Privacy: User loescht selbst).
        Cascade analog zu delete()."""
        if not action_token:
            return False
        try:
            with self._cursor(write=True) as cur:
                cur.execute(
                    "DELETE FROM subscribers WHERE action_token = ?",
                    (action_token,),
                )
                return cur.rowcount > 0
        except Exception as e:
            logger.error("delete_by_token failed: %s", e)
            return False

    def get_by_email(self, email: str) -> Optional[dict]:
        email_norm = (email or "").strip().lower()
        if not email_norm:
            return None
        try:
            with self._cursor() as cur:
                cur.execute(
                    """
                    SELECT id, email, regions, skill_level, status, action_token
                      FROM subscribers WHERE email = ?
                    """,
                    (email_norm,),
                )
                row = cur.fetchone()
                return self._row_to_subscriber(
                    row, ("id", "email", "regions", "skill_level", "status", "action_token")
                )
        except Exception as e:
            logger.error("get_by_email failed: %s", e)
            return None

    # ------------------------------------------------------------------
    # PREFERENCES (Selbst-Service ueber Account-Page)
    # ------------------------------------------------------------------
    def update_preferences(
        self,
        action_token: str,
        regions=None,
        weekdays=None,
        skill_level=None,
        min_tier_set=None,
        min_rating=None,
    ) -> bool:
        """Partielle Updates: nur uebergebene Felder werden geschrieben.
        - regions: Liste von Region-IDs oder None
        - weekdays: Liste von Ints 0..6 oder None
        - skill_level: 'beginner'|'standard'|'expert' oder None
        - min_tier_set: Liste aus 'violet','green','conditional','gray' oder None
        - min_rating: float 0.0..10.0 oder None
        Mindestens eine Region, ein Wochentag und ein Tier bleiben Pflicht (sonst False)."""
        if not action_token:
            return False
        sets = []
        params = []
        if regions is not None:
            if not regions:
                logger.warning("update_preferences: leere Regionen abgelehnt")
                return False
            sets.append("regions = ?")
            params.append(self._regions_to_db(regions))
        if weekdays is not None:
            if not weekdays:
                logger.warning("update_preferences: leere Wochentage abgelehnt")
                return False
            sets.append("active_weekdays = ?")
            params.append(self._weekdays_to_db(weekdays))
        if skill_level is not None:
            if skill_level not in ("beginner", "standard", "expert"):
                logger.warning("update_preferences: ungueltiges skill_level '%s'", skill_level)
                return False
            sets.append("skill_level = ?")
            params.append(skill_level)
        if min_tier_set is not None:
            cleaned = [t for t in min_tier_set if t in self._VALID_TIERS]
            if not cleaned:
                logger.warning("update_preferences: leere/invalide Tier-Liste abgelehnt")
                return False
            sets.append("min_tier_set = ?")
            params.append(self._tiers_to_db(cleaned))
        if min_rating is not None:
            try:
                r = float(min_rating)
            except (TypeError, ValueError):
                logger.warning("update_preferences: ungueltiges min_rating '%s'", min_rating)
                return False
            r = max(0.0, min(10.0, r))
            sets.append("min_rating = ?")
            params.append(r)
        if not sets:
            return False
        params.append(action_token)
        try:
            with self._cursor(write=True) as cur:
                cur.execute(
                    f"UPDATE subscribers SET {', '.join(sets)} WHERE action_token = ?",
                    params,
                )
                return cur.rowcount > 0
        except Exception as e:
            logger.error("update_preferences failed: %s", e)
            return False

    # ------------------------------------------------------------------
    # MAGIC-LINK LOGIN
    # ------------------------------------------------------------------
    def create_login_token(self, email: str, ttl_minutes: int = 30) -> Optional[dict]:
        """Erzeugt One-Time-Login-Token fuer einen Account.
        Liefert {id, email, login_token, is_new} oder None (ungueltige E-Mail).

        Verhalten:
          - User existiert mit status active/paused/unsubscribed -> Token gesetzt, is_new=False
          - User existiert NICHT -> Account wird automatisch angelegt (status='active',
            leere Regionen), Token gesetzt, is_new=True. Klick auf den Link aus der Mail
            beweist E-Mail-Besitz (= Verifikation). Dieser Pfad ersetzt die alte
            /subscribe-Seite — der Login-Flow ist jetzt zugleich der Onboarding-Flow.
          - User existiert als 'pending' -> behandelt wie "neu" (frische Token)
        """
        email_norm = (email or "").strip().lower()
        if not is_valid_email(email_norm):
            return None
        token = generate_token()
        try:
            with self._cursor(write=True) as cur:
                # Versuche: existierenden Account aktualisieren
                cur.execute(
                    f"""
                    UPDATE subscribers
                       SET login_token = ?,
                           login_token_expires_at = datetime('now', '+{int(ttl_minutes)} minutes')
                     WHERE email = ?
                       AND status IN ('active', 'paused', 'unsubscribed')
                 RETURNING id, email, login_token
                    """,
                    (token, email_norm),
                )
                row = cur.fetchone()
                if row is not None:
                    return {"id": row[0], "email": row[1], "login_token": row[2], "is_new": False}

                # Kein bestaetigter Account vorhanden -> neu anlegen.
                # status='active' direkt (Magic-Link-Klick = E-Mail verifiziert).
                # regions leer -> Scheduler skipt (siehe scheduler.py), bis User Settings speichert.
                action_token = generate_token()
                cur.execute(
                    f"""
                    INSERT INTO subscribers
                        (email, regions, skill_level, status, action_token,
                         login_token, login_token_expires_at, confirmed_at)
                    VALUES (?, '[]', 'standard', 'active', ?,
                            ?, datetime('now', '+{int(ttl_minutes)} minutes'),
                            datetime('now'))
                 RETURNING id, email, login_token
                    """,
                    (email_norm, action_token, token),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return {"id": row[0], "email": row[1], "login_token": row[2], "is_new": True}
        except sqlite3.IntegrityError as e:
            # Race-Condition: zwei gleichzeitige Login-Requests fuer dieselbe E-Mail
            # -> der zweite landet im UNIQUE-conflict. Re-try via SELECT.
            logger.warning("create_login_token race for %s: %s", email_norm, e)
            return None
        except Exception as e:
            logger.error("create_login_token failed: %s", e)
            return None

    def peek_login_token(self, token: str) -> bool:
        """Read-only: prueft ob Token existiert + nicht abgelaufen ist, OHNE ihn zu
        verbrauchen. Wird auf der GET-Landing-Page genutzt — verhindert dass
        Mail-Prefetcher (Microsoft Defender / Safe Links / etc.) den Token
        durch den initialen Scan-GET unbrauchbar macht. Der eigentliche Login
        passiert via POST in consume_login_token()."""
        if not token:
            return False
        try:
            with self._cursor() as cur:
                cur.execute(
                    """
                    SELECT 1 FROM subscribers
                     WHERE login_token = ?
                       AND login_token_expires_at IS NOT NULL
                       AND login_token_expires_at > datetime('now')
                       AND status IN ('active', 'paused', 'unsubscribed')
                     LIMIT 1
                    """,
                    (token,),
                )
                return cur.fetchone() is not None
        except Exception as e:
            logger.error("peek_login_token failed: %s", e)
            return False

    def consume_login_token(self, token: str) -> Optional[dict]:
        """Verifiziert + verbraucht Token (One-Time). Liefert {id, email} oder None.
        Auch Unsubscribed-User koennen sich einloggen (zur Reaktivierung).

        WICHTIG: Wird NUR aus POST aufgerufen — GET ist read-only via
        peek_login_token(), sonst killen Mail-Prefetcher den Token vor dem
        eigentlichen User-Klick."""
        if not token:
            return None
        try:
            with self._cursor(write=True) as cur:
                cur.execute(
                    """
                    UPDATE subscribers
                       SET login_token = NULL, login_token_expires_at = NULL
                     WHERE login_token = ?
                       AND login_token_expires_at IS NOT NULL
                       AND login_token_expires_at > datetime('now')
                       AND status IN ('active', 'paused', 'unsubscribed')
                 RETURNING id, email
                    """,
                    (token,),
                )
                row = cur.fetchone()
                if row is None:
                    return None
                return {"id": row[0], "email": row[1]}
        except Exception as e:
            logger.error("consume_login_token failed: %s", e)
            return None

    def get_session_user(self, sub_id: int) -> Optional[dict]:
        """Fuer Session-Cookie -> Subscriber-Lookup. Liefert auch Unsubscribed
        (die koennen reaktivieren). Nur 'pending' -> None (E-Mail unverifiziert)."""
        if not sub_id:
            return None
        try:
            with self._cursor() as cur:
                cur.execute(
                    """
                    SELECT id, email, regions, skill_level, status, action_token,
                           active_weekdays, min_tier_set, min_rating
                      FROM subscribers
                     WHERE id = ?
                       AND status IN ('active', 'paused', 'unsubscribed')
                    """,
                    (int(sub_id),),
                )
                row = cur.fetchone()
                return self._row_to_subscriber(
                    row,
                    ("id", "email", "regions", "skill_level", "status", "action_token",
                     "active_weekdays", "min_tier_set", "min_rating"),
                )
        except Exception as e:
            logger.error("get_session_user(%s) failed: %s", sub_id, e)
            return None

    def record_product_feedback(self, action_token: str, message: str) -> bool:
        """Persistiert Freitext-Produktfeedback (in-product, kein E-Mail-Versand).
        Eindringt-Cap 4000 Zeichen — laenger wird einfach gekuerzt."""
        if not action_token or not message:
            return False
        msg = (message or "").strip()[:4000]
        if not msg:
            return False
        try:
            with self._cursor(write=True) as cur:
                cur.execute("SELECT id FROM subscribers WHERE action_token = ?", (action_token,))
                row = cur.fetchone()
                if row is None:
                    return False
                cur.execute(
                    "INSERT INTO product_feedback (subscriber_id, message) VALUES (?, ?)",
                    (row[0], msg),
                )
                return True
        except Exception as e:
            logger.error("record_product_feedback failed: %s", e)
            return False

    def reactivate(self, action_token: str) -> bool:
        """Holt einen abgemeldeten Account zurueck: status='unsubscribed' -> 'active'.
        Setzt etwaige Pause-Range zurueck (frischer Start)."""
        if not action_token:
            return False
        try:
            with self._cursor(write=True) as cur:
                cur.execute(
                    """
                    UPDATE subscribers
                       SET status = 'active',
                           paused_from = NULL,
                           paused_until = NULL
                     WHERE action_token = ?
                       AND status = 'unsubscribed'
                    """,
                    (action_token,),
                )
                return cur.rowcount > 0
        except Exception as e:
            logger.error("reactivate failed: %s", e)
            return False

    def mark_sent(self, subscriber_id: int) -> bool:
        try:
            with self._cursor(write=True) as cur:
                cur.execute(
                    "UPDATE subscribers SET last_sent_at = datetime('now') WHERE id = ?",
                    (subscriber_id,),
                )
                return True
        except Exception as e:
            logger.error("mark_sent failed: %s", e)
            return False

    def close(self):
        """Kompatibilitaet — SQLite-Verbindungen werden pro Operation geoeffnet/geschlossen."""
        return


def get_manager_from_env() -> Optional[SubscriberManager]:
    """Factory: liefert SubscriberManager mit SQLite-Pfad aus config."""
    try:
        import config
        return SubscriberManager(config.SUBSCRIBERS_DB_PATH)
    except Exception as e:
        logger.error("SubscriberManager init failed: %s", e)
        return None
