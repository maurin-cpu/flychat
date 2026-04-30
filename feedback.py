"""
Spot- und Region-Feedback (Like/Dislike + Kommentar).

Persistenz: SQLite (data/feedback.db) — gleiches Muster wie subscriber.py.
Anonym: Client-IDs werden im localStorage gehalten (UUID), nicht an Subscribers
gebunden. Eingeloggte Subscriber koennen optional ihre subscriber_id
mitsenden, dann wird sie zusaetzlich gespeichert.

Upsert-Semantik: pro (target_type, target_id, target_date, client_id) gibt es
genau einen Eintrag. Ein zweiter Klick ueberschreibt vote/comment.
"""

from __future__ import annotations

import logging
import re
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Schreib-Lock analog SubscriberManager (SQLite serialisiert ohnehin, aber
# expliziter Lock vermeidet busy-waits unter Threads).
_WRITE_LOCK = threading.Lock()

# Erlaubte Werte
_VALID_TARGET_TYPES = ("spot", "region")
_VALID_VOTES = ("up", "down")

_CLIENT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_TARGET_ID_RE = re.compile(r"^[A-Za-z0-9_\-\u00C0-\u024F\s]{1,80}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

COMMENT_MAX_LEN = 4000


def is_valid_client_id(client_id: str) -> bool:
    return bool(client_id) and bool(_CLIENT_ID_RE.match(client_id))


def is_valid_target_id(target_id: str) -> bool:
    return bool(target_id) and bool(_TARGET_ID_RE.match(target_id))


def is_valid_date(d: str) -> bool:
    return bool(d) and bool(_DATE_RE.match(d))


class FeedbackManager:
    """CRUD fuer spot_region_feedback (SQLite)."""

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
                CREATE TABLE IF NOT EXISTS spot_region_feedback (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_type     TEXT NOT NULL CHECK (target_type IN ('spot', 'region')),
                    target_id       TEXT NOT NULL,            -- Spot-Name oder Region-Slug
                    target_date     TEXT,                     -- 'YYYY-MM-DD' oder NULL (allgemeines Feedback)
                    vote            TEXT CHECK (vote IN ('up', 'down')),  -- NULL erlaubt: nur Kommentar
                    comment         TEXT,                     -- NULL erlaubt: nur Vote
                    client_id       TEXT NOT NULL,            -- localStorage UUID (anonym)
                    subscriber_id   INTEGER,                  -- optional, wenn eingeloggt
                    user_agent      TEXT,
                    ip_hash         TEXT,                     -- nur Hash, nie Klartext-IP
                    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
                    UNIQUE (target_type, target_id, target_date, client_id)
                );

                CREATE INDEX IF NOT EXISTS idx_feedback_target
                    ON spot_region_feedback (target_type, target_id, target_date);
                CREATE INDEX IF NOT EXISTS idx_feedback_created
                    ON spot_region_feedback (created_at);
                CREATE INDEX IF NOT EXISTS idx_feedback_client
                    ON spot_region_feedback (client_id);

                CREATE TRIGGER IF NOT EXISTS trg_feedback_updated
                    AFTER UPDATE ON spot_region_feedback FOR EACH ROW
                BEGIN
                    UPDATE spot_region_feedback SET updated_at = datetime('now')
                     WHERE id = OLD.id;
                END;
            """)
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _normalize_inputs(target_type, target_id, target_date, vote, comment, client_id):
        target_type = (target_type or "").strip()
        target_id = (target_id or "").strip()
        target_date = (target_date or "").strip() or None
        vote = (vote or "").strip().lower() or None
        comment = (comment or "").strip() or None
        client_id = (client_id or "").strip()
        return target_type, target_id, target_date, vote, comment, client_id

    def record(
        self,
        target_type: str,
        target_id: str,
        target_date: Optional[str],
        vote: Optional[str],
        comment: Optional[str],
        client_id: str,
        subscriber_id: Optional[int] = None,
        user_agent: Optional[str] = None,
        ip_hash: Optional[str] = None,
    ) -> Optional[int]:
        """Upsert pro (target_type, target_id, target_date, client_id).
        Returns row-id on success, None on failure."""
        target_type, target_id, target_date, vote, comment, client_id = \
            self._normalize_inputs(target_type, target_id, target_date, vote, comment, client_id)

        if target_type not in _VALID_TARGET_TYPES:
            return None
        if not is_valid_target_id(target_id):
            return None
        if target_date is not None and not is_valid_date(target_date):
            return None
        if vote is not None and vote not in _VALID_VOTES:
            return None
        if not is_valid_client_id(client_id):
            return None
        if vote is None and not comment:
            # leeres Feedback ablehnen
            return None
        if comment:
            comment = comment[:COMMENT_MAX_LEN]
        if user_agent:
            user_agent = user_agent[:300]

        try:
            with self._cursor(write=True) as cur:
                cur.execute(
                    """
                    INSERT INTO spot_region_feedback
                        (target_type, target_id, target_date, vote, comment,
                         client_id, subscriber_id, user_agent, ip_hash)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT (target_type, target_id, target_date, client_id)
                    DO UPDATE SET
                        vote = excluded.vote,
                        comment = excluded.comment,
                        subscriber_id = COALESCE(excluded.subscriber_id, spot_region_feedback.subscriber_id),
                        user_agent = excluded.user_agent,
                        ip_hash = excluded.ip_hash
                    """,
                    (target_type, target_id, target_date, vote, comment,
                     client_id, subscriber_id, user_agent, ip_hash),
                )
                cur.execute(
                    """
                    SELECT id FROM spot_region_feedback
                     WHERE target_type = ? AND target_id = ?
                       AND (target_date IS ? OR target_date = ?)
                       AND client_id = ?
                    """,
                    (target_type, target_id, target_date, target_date, client_id),
                )
                row = cur.fetchone()
                return int(row[0]) if row else None
        except Exception as e:
            logger.error("FeedbackManager.record failed: %s", e)
            return None

    def get_own(self, target_type: str, target_id: str,
                target_date: Optional[str], client_id: str) -> Optional[dict]:
        """Eigene Stimme abrufen (fuer UI-Hydration)."""
        if not is_valid_client_id(client_id):
            return None
        try:
            with self._cursor() as cur:
                cur.execute(
                    """
                    SELECT id, vote, comment, created_at, updated_at
                      FROM spot_region_feedback
                     WHERE target_type = ? AND target_id = ?
                       AND (target_date IS ? OR target_date = ?)
                       AND client_id = ?
                    """,
                    (target_type, target_id, target_date, target_date, client_id),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return {
                    "id": row[0], "vote": row[1], "comment": row[2],
                    "created_at": row[3], "updated_at": row[4],
                }
        except Exception as e:
            logger.error("FeedbackManager.get_own failed: %s", e)
            return None

    def aggregate(self, target_type: str, target_id: str,
                  target_date: Optional[str]) -> dict:
        """Aggregat: Anzahl up/down fuer (target_type, target_id, target_date)."""
        try:
            with self._cursor() as cur:
                cur.execute(
                    """
                    SELECT vote, COUNT(*) FROM spot_region_feedback
                     WHERE target_type = ? AND target_id = ?
                       AND (target_date IS ? OR target_date = ?)
                       AND vote IS NOT NULL
                     GROUP BY vote
                    """,
                    (target_type, target_id, target_date, target_date),
                )
                counts = {v: int(n) for v, n in cur.fetchall()}
                up = counts.get("up", 0)
                down = counts.get("down", 0)
                return {"up": up, "down": down, "total": up + down}
        except Exception as e:
            logger.error("FeedbackManager.aggregate failed: %s", e)
            return {"up": 0, "down": 0, "total": 0}

    def delete_own(self, feedback_id: int, client_id: str) -> bool:
        """Eigene Stimme loeschen — pruef client_id-Match."""
        if not is_valid_client_id(client_id):
            return False
        try:
            with self._cursor(write=True) as cur:
                cur.execute(
                    "DELETE FROM spot_region_feedback "
                    "WHERE id = ? AND client_id = ?",
                    (int(feedback_id), client_id),
                )
                return cur.rowcount > 0
        except Exception as e:
            logger.error("FeedbackManager.delete_own failed: %s", e)
            return False

    # ------------------------------------------------------------------
    # ADMIN-QUERIES
    # ------------------------------------------------------------------
    def admin_list(self, limit: int = 200,
                   only_with_comment: bool = False,
                   only_dislike: bool = False) -> list:
        """Neueste Feedbacks zuerst. Optionale Filter."""
        clauses = []
        params: list = []
        if only_with_comment:
            clauses.append("comment IS NOT NULL AND TRIM(comment) <> ''")
        if only_dislike:
            clauses.append("vote = 'down'")
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        try:
            with self._cursor() as cur:
                cur.execute(
                    f"""
                    SELECT id, target_type, target_id, target_date, vote, comment,
                           client_id, subscriber_id, created_at, updated_at
                      FROM spot_region_feedback
                      {where}
                     ORDER BY created_at DESC
                     LIMIT ?
                    """,
                    (*params, int(limit)),
                )
                rows = cur.fetchall()
                keys = ("id", "target_type", "target_id", "target_date", "vote",
                        "comment", "client_id", "subscriber_id",
                        "created_at", "updated_at")
                return [dict(zip(keys, r)) for r in rows]
        except Exception as e:
            logger.error("FeedbackManager.admin_list failed: %s", e)
            return []

    def admin_stats(self, days: int = 30) -> dict:
        """Aggregat ueber alle Targets in den letzten N Tagen."""
        try:
            with self._cursor() as cur:
                cur.execute(
                    f"""
                    SELECT
                        SUM(CASE WHEN vote = 'up' THEN 1 ELSE 0 END) AS up,
                        SUM(CASE WHEN vote = 'down' THEN 1 ELSE 0 END) AS down,
                        SUM(CASE WHEN comment IS NOT NULL AND TRIM(comment) <> ''
                                 THEN 1 ELSE 0 END) AS with_comment,
                        COUNT(*) AS total
                      FROM spot_region_feedback
                     WHERE created_at >= datetime('now', '-{int(days)} days')
                    """
                )
                row = cur.fetchone() or (0, 0, 0, 0)
                up, down, with_comment, total = (int(x or 0) for x in row)
                return {
                    "up": up, "down": down,
                    "with_comment": with_comment, "total": total,
                    "window_days": days,
                }
        except Exception as e:
            logger.error("FeedbackManager.admin_stats failed: %s", e)
            return {"up": 0, "down": 0, "with_comment": 0, "total": 0,
                    "window_days": days}

    def admin_delete(self, feedback_id: int) -> bool:
        """Admin-Loeschen ohne client_id-Pruefung (Spam/Missbrauch)."""
        try:
            with self._cursor(write=True) as cur:
                cur.execute(
                    "DELETE FROM spot_region_feedback WHERE id = ?",
                    (int(feedback_id),),
                )
                return cur.rowcount > 0
        except Exception as e:
            logger.error("FeedbackManager.admin_delete failed: %s", e)
            return False

    def close(self):
        return


_singleton: Optional[FeedbackManager] = None
_singleton_lock = threading.Lock()


def get_manager_from_env() -> Optional[FeedbackManager]:
    """Factory: liefert FeedbackManager (Singleton) mit SQLite-Pfad aus config."""
    global _singleton
    if _singleton is not None:
        return _singleton
    with _singleton_lock:
        if _singleton is not None:
            return _singleton
        try:
            import config
            db_path = getattr(config, "FEEDBACK_DB_PATH", None)
            if db_path is None:
                # Fallback: gleicher Ordner wie SUBSCRIBERS_DB_PATH
                db_path = Path(config.SUBSCRIBERS_DB_PATH).parent / "feedback.db"
            _singleton = FeedbackManager(db_path)
            return _singleton
        except Exception as e:
            logger.error("FeedbackManager init failed: %s", e)
            return None
