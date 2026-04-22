"""
Subscriber-Management fuer das E-Mail-Briefing (Stufe 1).

Spiegelt das Design von supabase_client.py:
  - Nutzt denselben Postgres-Pool via SUPABASE_DATABASE_URL
  - Soft-Fail: Fehler werden geloggt, None/leeres Dict zurueckgegeben
  - Keine Session/Auth — alle User-Aktionen passwordless via Tokens

Schema: migrations/002_subscribers.sql
"""

from __future__ import annotations

import logging
import re
import secrets
from contextlib import contextmanager
from typing import Optional

logger = logging.getLogger(__name__)

try:
    import psycopg
    from psycopg_pool import ConnectionPool
    _PSYCOPG_AVAILABLE = True
except ImportError:
    _PSYCOPG_AVAILABLE = False


# Simple RFC-5322-kompatible E-Mail-Validierung (bewusst pragmatisch, nicht vollstaendig).
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


def is_valid_email(email: str) -> bool:
    if not email or len(email) > 254:
        return False
    return bool(_EMAIL_RE.match(email.strip()))


def generate_token(nbytes: int = 24) -> str:
    """URL-safe Token (~32 Zeichen bei 24 Bytes). Kollisions-Chance vernachlaessigbar."""
    return secrets.token_urlsafe(nbytes)


class SubscriberManager:
    """CRUD fuer subscribers + subscriber_feedback."""

    def __init__(self, database_url: str, min_size: int = 1, max_size: int = 3):
        if not _PSYCOPG_AVAILABLE:
            raise RuntimeError(
                "psycopg nicht installiert. Siehe requirements.txt "
                "(psycopg[binary,pool]>=3.1.0)."
            )
        self.database_url = database_url
        self._pool: Optional[ConnectionPool] = None
        self._pool_args = dict(min_size=min_size, max_size=max_size)

    def _get_pool(self) -> "ConnectionPool":
        if self._pool is None:
            self._pool = ConnectionPool(
                self.database_url,
                min_size=self._pool_args["min_size"],
                max_size=self._pool_args["max_size"],
                kwargs={"autocommit": False, "prepare_threshold": None},
                open=True,
            )
        return self._pool

    @contextmanager
    def _cursor(self):
        pool = self._get_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                yield conn, cur

    # ------------------------------------------------------------------
    # CREATE / CONFIRM
    # ------------------------------------------------------------------
    def create(
        self,
        email: str,
        regions: list[str],
        skill_level: str = "standard",
    ) -> Optional[dict]:
        """
        Legt einen pending-Subscriber an. Wenn E-Mail schon existiert:
          - Status 'unsubscribed' -> resubscribe (neues confirm_token, status='pending')
          - Sonst -> None zurueckgeben (Aufrufer zeigt "bereits registriert")

        Returns dict mit id, email, confirm_token, action_token oder None.
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

        try:
            with self._cursor() as (conn, cur):
                # Resubscribe-Case: wenn schon 'unsubscribed' existiert, ueberschreiben.
                cur.execute(
                    "SELECT id, status FROM subscribers WHERE email = %s",
                    (email_norm,),
                )
                existing = cur.fetchone()

                if existing:
                    sub_id, status = existing
                    if status == "unsubscribed":
                        cur.execute(
                            """
                            UPDATE subscribers
                               SET regions = %s,
                                   skill_level = %s,
                                   status = 'pending',
                                   confirm_token = %s,
                                   action_token = %s,
                                   paused_until = NULL,
                                   confirmed_at = NULL
                             WHERE id = %s
                         RETURNING id, email, confirm_token, action_token
                            """,
                            (regions, skill_level, confirm_token, action_token, sub_id),
                        )
                        row = cur.fetchone()
                        conn.commit()
                        return _row_to_dict(row, ("id", "email", "confirm_token", "action_token"))
                    else:
                        # pending/active/paused -> keine neue Registrierung zulassen
                        return None

                cur.execute(
                    """
                    INSERT INTO subscribers
                        (email, regions, skill_level, confirm_token, action_token)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id, email, confirm_token, action_token
                    """,
                    (email_norm, regions, skill_level, confirm_token, action_token),
                )
                row = cur.fetchone()
                conn.commit()
                return _row_to_dict(row, ("id", "email", "confirm_token", "action_token"))
        except Exception as e:
            logger.error("create(%s) failed: %s", email_norm, e)
            return None

    def get_by_confirm_token(self, token: str) -> Optional[dict]:
        if not token:
            return None
        try:
            with self._cursor() as (_, cur):
                cur.execute(
                    """
                    SELECT id, email, regions, skill_level, status, action_token
                      FROM subscribers
                     WHERE confirm_token = %s
                    """,
                    (token,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return _row_to_dict(
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
            with self._cursor() as (conn, cur):
                cur.execute(
                    """
                    UPDATE subscribers
                       SET status = 'active',
                           confirmed_at = COALESCE(confirmed_at, NOW()),
                           confirm_token = NULL
                     WHERE confirm_token = %s
                RETURNING id, email, regions, skill_level, action_token
                    """,
                    (token,),
                )
                row = cur.fetchone()
                conn.commit()
                if not row:
                    return None
                return _row_to_dict(
                    row, ("id", "email", "regions", "skill_level", "action_token")
                )
        except Exception as e:
            logger.error("confirm failed: %s", e)
            return None

    # ------------------------------------------------------------------
    # ACTION TOKEN (persistent, pro Subscriber einer)
    # ------------------------------------------------------------------
    def get_by_action_token(self, token: str) -> Optional[dict]:
        if not token:
            return None
        try:
            with self._cursor() as (_, cur):
                cur.execute(
                    """
                    SELECT id, email, regions, skill_level, status, paused_until
                      FROM subscribers
                     WHERE action_token = %s
                    """,
                    (token,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return _row_to_dict(
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
            with self._cursor() as (conn, cur):
                cur.execute(
                    "UPDATE subscribers SET status = 'unsubscribed' "
                    "WHERE action_token = %s",
                    (token,),
                )
                affected = cur.rowcount
                conn.commit()
                return affected > 0
        except Exception as e:
            logger.error("unsubscribe failed: %s", e)
            return False

    def pause(self, token: str, until_date) -> bool:
        """until_date = datetime.date oder ISO-String 'YYYY-MM-DD'."""
        if not token or not until_date:
            return False
        try:
            with self._cursor() as (conn, cur):
                cur.execute(
                    """
                    UPDATE subscribers
                       SET status = 'paused',
                           paused_until = %s
                     WHERE action_token = %s
                       AND status IN ('active', 'paused')
                    """,
                    (until_date, token),
                )
                affected = cur.rowcount
                conn.commit()
                return affected > 0
        except Exception as e:
            logger.error("pause failed: %s", e)
            return False

    def resume(self, token: str) -> bool:
        if not token:
            return False
        try:
            with self._cursor() as (conn, cur):
                cur.execute(
                    """
                    UPDATE subscribers
                       SET status = 'active',
                           paused_until = NULL
                     WHERE action_token = %s
                       AND status = 'paused'
                    """,
                    (token,),
                )
                affected = cur.rowcount
                conn.commit()
                return affected > 0
        except Exception as e:
            logger.error("resume failed: %s", e)
            return False

    # ------------------------------------------------------------------
    # LIST / FEEDBACK
    # ------------------------------------------------------------------
    def list_active(self) -> list[dict]:
        """Alle aktiven Subscriber (fuer Versand-Loop).
        'paused' wird automatisch wieder active wenn paused_until <= heute.
        """
        try:
            with self._cursor() as (conn, cur):
                # Auto-resume: paused -> active wenn Datum erreicht
                cur.execute(
                    """
                    UPDATE subscribers
                       SET status = 'active', paused_until = NULL
                     WHERE status = 'paused'
                       AND paused_until IS NOT NULL
                       AND paused_until <= CURRENT_DATE
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
                conn.commit()
                return [
                    _row_to_dict(r, ("id", "email", "regions", "skill_level", "action_token"))
                    for r in rows
                ]
        except Exception as e:
            logger.error("list_active failed: %s", e)
            return []

    def record_feedback(self, subscriber_id: int, briefing_date, verdict: str) -> bool:
        if verdict not in ("correct", "wrong"):
            return False
        try:
            with self._cursor() as (conn, cur):
                cur.execute(
                    """
                    INSERT INTO subscriber_feedback
                        (subscriber_id, briefing_date, verdict)
                    VALUES (%s, %s, %s)
                    """,
                    (subscriber_id, briefing_date, verdict),
                )
                conn.commit()
                return True
        except Exception as e:
            logger.error("record_feedback failed: %s", e)
            return False

    def get_feedback_stats(self, subscriber_id: int, days: int = 30) -> dict:
        """Zaehlt correct/wrong-Feedbacks der letzten `days` Tage.
        Returns: {"total": N, "correct": N, "wrong": N, "accuracy_pct": 0-100 | None}
        """
        try:
            with self._cursor() as (_, cur):
                cur.execute(
                    """
                    SELECT verdict, COUNT(*)
                      FROM subscriber_feedback
                     WHERE subscriber_id = %s
                       AND created_at >= NOW() - (%s || ' days')::interval
                     GROUP BY verdict
                    """,
                    (subscriber_id, str(days)),
                )
                rows = cur.fetchall()
                counts = {v: n for v, n in rows}
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
        """Returns {'active': N, 'pending': N, 'paused': N, 'unsubscribed': N}.
        Fehlende Statuswerte sind 0.
        """
        base = {"active": 0, "pending": 0, "paused": 0, "unsubscribed": 0}
        try:
            with self._cursor() as (_, cur):
                cur.execute(
                    "SELECT status, COUNT(*) FROM subscribers GROUP BY status"
                )
                for status, n in cur.fetchall():
                    base[status] = n
                return base
        except Exception as e:
            logger.error("count_by_status failed: %s", e)
            return base

    def list_recent(self, limit: int = 50) -> list[dict]:
        """Neueste Subscriber zuerst. Fuer Admin-Tabelle."""
        try:
            with self._cursor() as (_, cur):
                cur.execute(
                    """
                    SELECT id, email, regions, skill_level, status,
                           paused_until, created_at, confirmed_at, last_sent_at
                      FROM subscribers
                     ORDER BY created_at DESC
                     LIMIT %s
                    """,
                    (limit,),
                )
                rows = cur.fetchall()
                keys = ("id", "email", "regions", "skill_level", "status",
                        "paused_until", "created_at", "confirmed_at", "last_sent_at")
                return [dict(zip(keys, r)) for r in rows]
        except Exception as e:
            logger.error("list_recent failed: %s", e)
            return []

    def count_feedback_overall(self, days: int = 30) -> dict:
        """Aggregierte Feedback-Zahlen ueber ALLE Subscriber.
        Returns: {'total': N, 'correct': N, 'wrong': N, 'accuracy_pct': 0-100|None}
        """
        try:
            with self._cursor() as (_, cur):
                cur.execute(
                    """
                    SELECT verdict, COUNT(*) FROM subscriber_feedback
                     WHERE created_at >= NOW() - (%s || ' days')::interval
                     GROUP BY verdict
                    """,
                    (str(days),),
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
            with self._cursor() as (_, cur):
                cur.execute(
                    """
                    SELECT id, email, regions, skill_level, status, action_token
                      FROM subscribers WHERE id = %s
                    """,
                    (subscriber_id,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return _row_to_dict(
                    row, ("id", "email", "regions", "skill_level", "status", "action_token")
                )
        except Exception as e:
            logger.error("get_by_id(%s) failed: %s", subscriber_id, e)
            return None

    def block(self, subscriber_id: int) -> bool:
        """Admin-Aktion: setzt status='unsubscribed' per ID."""
        try:
            with self._cursor() as (conn, cur):
                cur.execute(
                    "UPDATE subscribers SET status='unsubscribed' WHERE id = %s",
                    (subscriber_id,),
                )
                affected = cur.rowcount
                conn.commit()
                return affected > 0
        except Exception as e:
            logger.error("block(%s) failed: %s", subscriber_id, e)
            return False

    def get_by_email(self, email: str) -> Optional[dict]:
        email_norm = (email or "").strip().lower()
        if not email_norm:
            return None
        try:
            with self._cursor() as (_, cur):
                cur.execute(
                    """
                    SELECT id, email, regions, skill_level, status, action_token
                      FROM subscribers WHERE email = %s
                    """,
                    (email_norm,),
                )
                row = cur.fetchone()
                if not row:
                    return None
                return _row_to_dict(
                    row, ("id", "email", "regions", "skill_level", "status", "action_token")
                )
        except Exception as e:
            logger.error("get_by_email failed: %s", e)
            return None

    def mark_sent(self, subscriber_id: int) -> bool:
        try:
            with self._cursor() as (conn, cur):
                cur.execute(
                    "UPDATE subscribers SET last_sent_at = NOW() WHERE id = %s",
                    (subscriber_id,),
                )
                conn.commit()
                return True
        except Exception as e:
            logger.error("mark_sent failed: %s", e)
            return False

    def close(self):
        if self._pool is not None:
            self._pool.close()
            self._pool = None


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _row_to_dict(row, keys):
    if row is None:
        return None
    return dict(zip(keys, row))


def get_manager_from_env() -> Optional[SubscriberManager]:
    """Factory analog supabase_client.get_client_from_env()."""
    import os
    url = os.environ.get("SUPABASE_DATABASE_URL", "").strip()
    if not url:
        return None
    try:
        return SubscriberManager(url)
    except Exception as e:
        logger.error("SubscriberManager init failed: %s", e)
        return None
