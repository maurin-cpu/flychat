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
                    paused_until    TEXT,                                       -- ISO-Date 'YYYY-MM-DD' oder NULL
                    confirm_token   TEXT UNIQUE,
                    action_token    TEXT UNIQUE NOT NULL,
                    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
                    confirmed_at    TEXT,
                    last_sent_at    TEXT,
                    updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
                );

                CREATE INDEX IF NOT EXISTS idx_subscribers_status_active
                    ON subscribers (status) WHERE status = 'active';
                CREATE INDEX IF NOT EXISTS idx_subscribers_confirm_token
                    ON subscribers (confirm_token) WHERE confirm_token IS NOT NULL;
                CREATE INDEX IF NOT EXISTS idx_subscribers_action_token
                    ON subscribers (action_token);

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

                -- updated_at automatisch pflegen
                CREATE TRIGGER IF NOT EXISTS trg_subscribers_updated
                    AFTER UPDATE ON subscribers FOR EACH ROW
                BEGIN
                    UPDATE subscribers SET updated_at = datetime('now') WHERE id = OLD.id;
                END;
            """)
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
                    SELECT id, email, regions, skill_level, status, paused_until
                      FROM subscribers
                     WHERE action_token = ?
                    """,
                    (token,),
                )
                row = cur.fetchone()
                return self._row_to_subscriber(
                    row,
                    ("id", "email", "regions", "skill_level", "status", "paused_until"),
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

    def pause(self, token: str, until_date) -> bool:
        """until_date = datetime.date oder ISO-String 'YYYY-MM-DD'."""
        until_str = self._date_to_db(until_date)
        if not token or not until_str:
            return False
        try:
            with self._cursor(write=True) as cur:
                cur.execute(
                    """
                    UPDATE subscribers
                       SET status = 'paused',
                           paused_until = ?
                     WHERE action_token = ?
                       AND status IN ('active', 'paused')
                    """,
                    (until_str, token),
                )
                return cur.rowcount > 0
        except Exception as e:
            logger.error("pause failed: %s", e)
            return False

    def resume(self, token: str) -> bool:
        if not token:
            return False
        try:
            with self._cursor(write=True) as cur:
                cur.execute(
                    """
                    UPDATE subscribers
                       SET status = 'active',
                           paused_until = NULL
                     WHERE action_token = ?
                       AND status = 'paused'
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
        """Alle aktiven Subscriber. 'paused' -> 'active' wenn paused_until <= heute."""
        try:
            with self._cursor(write=True) as cur:
                cur.execute(
                    """
                    UPDATE subscribers
                       SET status = 'active', paused_until = NULL
                     WHERE status = 'paused'
                       AND paused_until IS NOT NULL
                       AND paused_until <= date('now')
                    """
                )
                cur.execute(
                    """
                    SELECT id, email, regions, skill_level, action_token
                      FROM subscribers
                     WHERE status = 'active'
                     ORDER BY id
                    """
                )
                rows = cur.fetchall()
                keys = ("id", "email", "regions", "skill_level", "action_token")
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
        base = {"active": 0, "pending": 0, "paused": 0, "unsubscribed": 0}
        try:
            with self._cursor() as cur:
                cur.execute("SELECT status, COUNT(*) FROM subscribers GROUP BY status")
                for status, n in cur.fetchall():
                    if status in base:
                        base[status] = n
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
