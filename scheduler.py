"""
Daily-Scheduler (Stufe 4).

Taeglicher Ablauf an konfigurierten Wochentagen (siehe config.DAILY_RUN_*):
  1. engine.refresh_weather()       — Wetterdaten neu laden
  2. engine.build_briefing_data()   — LLM-Analyse (innerhalb _send_briefings_once)
  3. Mails an aktive Subscriber versenden

Zusaetzlich: Monats-Accuracy-Mail am 1. des Monats um 07:00.

Laufzeit-Modi:
  - als Daemon-Thread (aus main.py aufgerufen): schlaeft bis zum naechsten
    Slot und fuehrt dann die Sequenz aus
  - als CLI (`python scheduler.py --now`): sendet sofort einmal, Exit

Umgebungsvariablen:
  GLEITCAST_BRIEFINGS=0          -> Scheduler-Thread startet nicht
  SCHEDULER_TEST_MODE=1          -> Thread wartet nur 30s bis zum ersten Lauf
                                    (fuer Integrations-Tests)
  GLEITCAST_SMTP_DRY_RUN=1       -> Mails werden als HTML in tempdir geschrieben
                                    statt per SMTP gesendet (von email_service)
"""

from __future__ import annotations

import logging
import os
import time as time_mod
from datetime import datetime, time, timedelta
from typing import Optional, Tuple

import config

logger = logging.getLogger(__name__)

# Monats-Accuracy-Mail: 1. des Monats um 07:00
ACCURACY_HOUR = 7
ACCURACY_MINUTE = 0


def _next_send_time(now: datetime) -> datetime:
    """Naechster konfigurierter Wochentag zur konfigurierten Uhrzeit, strikt NACH `now`."""
    for days_ahead in range(0, 8):
        candidate = (now + timedelta(days=days_ahead)).replace(
            hour=config.DAILY_RUN_HOUR, minute=config.DAILY_RUN_MINUTE,
            second=0, microsecond=0,
        )
        if candidate.weekday() in config.DAILY_RUN_WEEKDAYS and candidate > now:
            return candidate
    # Fallback wenn DAILY_RUN_WEEKDAYS leer ist
    return now + timedelta(hours=24)


def _next_accuracy_time(now: datetime) -> datetime:
    """Naechster 1. des Monats um 07:00 strikt NACH `now`."""
    candidate = now.replace(day=1, hour=ACCURACY_HOUR, minute=ACCURACY_MINUTE,
                            second=0, microsecond=0)
    if candidate > now:
        return candidate
    # Nachsten Monats-1.
    year, month = now.year, now.month + 1
    if month > 12:
        year += 1
        month = 1
    return datetime(year, month, 1, ACCURACY_HOUR, ACCURACY_MINUTE, 0)


def _next_event(now: datetime) -> Tuple[datetime, str]:
    """Gibt (Zeitpunkt, 'briefing'|'accuracy') fuer das naechste Event zurueck."""
    b = _next_send_time(now)
    a = _next_accuracy_time(now)
    if a < b:
        return a, "accuracy"
    return b, "briefing"


def _send_briefings_once(engine) -> dict:
    """Baut briefing_data einmal, loopt ueber aktive Subscriber.
    Returns: {'total': N, 'sent': n_sent, 'skipped': n_skipped, 'failed': n_failed}
    """
    from subscriber import get_manager_from_env
    from email_service import send_briefing_email

    mgr = get_manager_from_env()
    if mgr is None:
        logger.error("Scheduler: SUPABASE_DATABASE_URL nicht gesetzt")
        return {"total": 0, "sent": 0, "skipped": 0, "failed": 0}

    subscribers = mgr.list_active()
    total = len(subscribers)
    if total == 0:
        logger.info("Scheduler: keine aktiven Subscriber")
        return {"total": 0, "sent": 0, "skipped": 0, "failed": 0}

    logger.info("Scheduler: baue Briefing-Daten fuer %d Subscriber ...", total)
    if engine is None:
        logger.error("Scheduler: keine Engine uebergeben")
        return {"total": total, "sent": 0, "skipped": 0, "failed": total}

    try:
        briefing_data = engine.build_briefing_data()
    except Exception as e:
        logger.exception("Scheduler: build_briefing_data fehlgeschlagen: %s", e)
        return {"total": total, "sent": 0, "skipped": 0, "failed": total}

    days_count = len(briefing_data.get("days", []))
    logger.info("Scheduler: briefing_data = %d Tage", days_count)

    sent = 0
    skipped = 0
    failed = 0
    for sub in subscribers:
        email = sub.get("email")
        try:
            ok = send_briefing_email(sub, briefing_data, async_send=False)
            if ok:
                mgr.mark_sent(sub["id"])
                sent += 1
                logger.info("[BRIEF] -> %s (#%s) OK", email, sub["id"])
            else:
                failed += 1
                logger.error("[BRIEF] -> %s (#%s) FAIL (send_email returned False)",
                             email, sub["id"])
        except Exception as e:
            failed += 1
            logger.exception("[BRIEF] -> %s (#%s) EXCEPTION: %s", email, sub["id"], e)

    logger.info("Scheduler: fertig. sent=%d skipped=%d failed=%d / %d",
                sent, skipped, failed, total)
    return {"total": total, "sent": sent, "skipped": skipped, "failed": failed}


def _send_accuracy_once() -> dict:
    """Loopt aktive Subscriber und verschickt Monats-Accuracy-Mails.
    Skippt Subscriber mit <3 Feedbacks im Zeitfenster.
    """
    from subscriber import get_manager_from_env
    from email_service import send_accuracy_email

    mgr = get_manager_from_env()
    if mgr is None:
        logger.error("Accuracy-Scheduler: SUPABASE_DATABASE_URL nicht gesetzt")
        return {"total": 0, "sent": 0, "skipped": 0, "failed": 0}

    subs = mgr.list_active()
    sent = skipped = failed = 0
    for sub in subs:
        try:
            stats = mgr.get_feedback_stats(sub["id"], days=30)
            ok = send_accuracy_email(sub, stats, async_send=False)
            if ok:
                sent += 1
                logger.info("[ACCURACY] -> %s (#%s) OK (%s%%)",
                            sub["email"], sub["id"], stats.get("accuracy_pct"))
            else:
                skipped += 1
        except Exception as e:
            failed += 1
            logger.exception("[ACCURACY] -> %s (#%s): %s",
                             sub["email"], sub["id"], e)
    logger.info("Accuracy-Scheduler: total=%d sent=%d skipped=%d failed=%d",
                len(subs), sent, skipped, failed)
    return {"total": len(subs), "sent": sent, "skipped": skipped, "failed": failed}


def _daily_run(engine) -> dict:
    """Sequenzieller Daily-Job: refresh_weather -> build_briefing_data -> Mails.

    refresh_weather wird auch bei Fehler nicht blockierend — Briefings laufen
    dann mit den zuletzt gecachten Daten, statt ganz auszufallen.
    """
    logger.info("Daily run: starte Wetter-Refresh...")
    try:
        engine.refresh_weather()
        logger.info("Daily run: Wetter-Refresh OK")
    except Exception as e:
        logger.exception("Daily run: Wetter-Refresh fehlgeschlagen — Briefings "
                         "laufen mit Cache-Daten weiter: %s", e)

    logger.info("Daily run: starte LLM-Analyse + Briefing-Versand...")
    return _send_briefings_once(engine)


def briefing_scheduler(engine) -> None:
    """Daemon-Thread-Entry: dispatcht Daily-Run (konfig. Tage + Uhrzeit) UND
    Monats-Accuracy (1. des Monats 07:00). Einheitlicher Sleep-Loop.
    """
    test_mode = os.environ.get("SCHEDULER_TEST_MODE", "").strip() in ("1", "true", "yes")
    if test_mode:
        logger.warning("Scheduler: SCHEDULER_TEST_MODE aktiv — erster Lauf in 30s, "
                       "danach normaler Zeitplan")

    first_iter = True
    while True:
        now = datetime.now()

        if first_iter and test_mode:
            wait_seconds = 30
            next_event_type = "briefing"
            logger.info("Scheduler: test-mode Wartezeit 30s (event=briefing)")
        else:
            next_run, next_event_type = _next_event(now)
            wait_seconds = (next_run - now).total_seconds()
            logger.info("Scheduler: naechstes Event=%s um %s (in %.1fh)",
                        next_event_type, next_run.strftime("%Y-%m-%d %H:%M"),
                        wait_seconds / 3600)

        first_iter = False
        time_mod.sleep(max(1, wait_seconds))

        try:
            if next_event_type == "accuracy":
                _send_accuracy_once()
            else:
                _daily_run(engine)
        except Exception as e:
            logger.exception("Scheduler: uncaught exception during %s: %s",
                             next_event_type, e)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _cli_now() -> int:
    """`python scheduler.py --now`: baut Engine + sendet einmal. Exit 0 bei Erfolg."""
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    # .env laden, wie main.py es tut
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    from chat_engine import GleitcastEngine
    eng = GleitcastEngine()
    try:
        eng.load_weather_from_cache()
    except Exception as e:
        logger.warning("load_weather_from_cache: %s", e)

    # Flask-App-Context ist noetig fuer render_template
    from web import app as flask_app
    with flask_app.app_context(), flask_app.test_request_context():
        stats = _send_briefings_once(eng)

    print(f"[DONE] total={stats['total']} sent={stats['sent']} "
          f"skipped={stats['skipped']} failed={stats['failed']}")
    return 0 if stats["failed"] == 0 else 1


if __name__ == "__main__":
    import argparse
    import sys

    ap = argparse.ArgumentParser(description="Gleitcast Briefing-Scheduler")
    ap.add_argument("--now", action="store_true",
                    help="Einmaliger Sofort-Versand der Briefings.")
    ap.add_argument("--accuracy-now", action="store_true",
                    help="Einmaliger Sofort-Versand der Monats-Accuracy-Mails.")
    ap.add_argument("--next", action="store_true",
                    help="Zeigt die naechsten geplanten Events (briefing + accuracy).")
    args = ap.parse_args()

    if args.next:
        now = datetime.now()
        print(f"Briefing: {_next_send_time(now).strftime('%Y-%m-%d %H:%M')}")
        print(f"Accuracy: {_next_accuracy_time(now).strftime('%Y-%m-%d %H:%M')}")
        sys.exit(0)
    if args.now:
        sys.exit(_cli_now())
    if args.accuracy_now:
        logging.basicConfig(level=logging.INFO,
                            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        try:
            from dotenv import load_dotenv; load_dotenv()
        except ImportError:
            pass
        from web import app as flask_app
        with flask_app.app_context(), flask_app.test_request_context():
            stats = _send_accuracy_once()
        print(f"[DONE] accuracy: total={stats['total']} sent={stats['sent']} "
              f"skipped={stats['skipped']} failed={stats['failed']}")
        sys.exit(0 if stats["failed"] == 0 else 1)
    ap.print_help()
    sys.exit(0)
