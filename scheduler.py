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
  WINGCAST_BRIEFINGS=0          -> Scheduler-Thread startet nicht
  SCHEDULER_TEST_MODE=1          -> Thread wartet nur 30s bis zum ersten Lauf
                                    (fuer Integrations-Tests)
  WINGCAST_SMTP_DRY_RUN=1       -> Mails werden als HTML in tempdir geschrieben
                                    statt per SMTP gesendet (von email_service)
"""

from __future__ import annotations

import logging
import os
import threading
import time as time_mod
from datetime import datetime, time, timedelta
from typing import Optional, Tuple

import config

logger = logging.getLogger(__name__)

# Signal zum sofortigen Neu-Berechnen des naechsten Slots (z.B. nach Admin-Config-Save).
_wake_event = threading.Event()


def notify_config_changed() -> None:
    """Signalisiert dem Scheduler-Thread, dass sich DAILY_RUN_* geaendert hat.
    Der Thread wacht aus seinem Sleep auf und rechnet den naechsten Slot neu."""
    _wake_event.set()


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
        logger.error("Scheduler: SubscriberManager konnte nicht initialisiert werden")
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

    # Wetterlage-Block (Synoptik) 1x/Tag refreshen, bevor build_briefing_data laeuft.
    # Schlaegt der Refresh fehl, faellt der Block aus dem Cast — kein Fallback-Text.
    try:
        from engine.synoptic_llm import refresh_synoptic_overview
        from fetch_weather import load_cached_weather
        wcache = load_cached_weather()
        if wcache and engine.synoptic_client:
            sctx = refresh_synoptic_overview(
                wcache, engine.synoptic_client, engine.synoptic_model,
            )
            if sctx:
                logger.info("Scheduler: Wetterlage refreshed (lage=%s, llm_overview=%s)",
                            sctx.get("lage_label", {}).get("value"),
                            "ok" if sctx.get("llm_overview") else "fehlt")
            else:
                logger.info("Scheduler: Wetterlage konnte nicht erzeugt werden — Block faellt aus")
    except Exception as e:
        logger.exception("Scheduler: Wetterlage-Refresh Exception: %s", e)
        # weiter mit Briefing, ohne Wetterlage-Block

    # Synoptik-Grid (/synoptik-Druckkarte) 1x/Tag refreshen — eigenes
    # try/except: ein Grid-Fehler darf Briefing-Mails nie blockieren.
    try:
        from engine.synoptic_grid import refresh_synoptic_grid
        grid = refresh_synoptic_grid()
        if grid:
            logger.info("Scheduler: Synoptik-Grid refreshed (%d Timesteps)",
                        len(grid.get("timesteps", [])))
        else:
            logger.info("Scheduler: Synoptik-Grid-Refresh fehlgeschlagen — alter Cache bleibt")
    except Exception as e:
        logger.exception("Scheduler: Synoptik-Grid-Refresh Exception: %s", e)

    try:
        briefing_data = engine.build_briefing_data()
    except Exception as e:
        logger.exception("Scheduler: build_briefing_data fehlgeschlagen: %s", e)
        return {"total": total, "sent": 0, "skipped": 0, "failed": total}

    days_count = len(briefing_data.get("days", []))
    logger.info("Scheduler: briefing_data = %d Tage", days_count)

    from datetime import datetime as _dt
    today_weekday = _dt.now().weekday()  # 0=Mo, 6=So

    sent = 0
    skipped = 0
    failed = 0
    for sub in subscribers:
        email = sub.get("email")

        # Auto-erstellte Accounts (per Magic-Link ohne Region-Auswahl) haben
        # leere regions -> kein sinnvolles Briefing moeglich, ueberspringen.
        if not sub.get("regions"):
            skipped += 1
            logger.info("[BRIEF] -> %s (#%s) SKIP (keine Regionen ausgewaehlt)",
                        email, sub["id"])
            continue

        # Wochentag-Filter: Subscriber kann pro Wochentag opt-in/out
        # active_weekdays kommt aus list_active(); leere Liste = NIE versenden
        weekdays = sub.get("active_weekdays")
        if weekdays is None:
            # Defensive: alte DB ohne Spalte -> alle Tage
            weekdays = [0, 1, 2, 3, 4, 5, 6]
        if today_weekday not in weekdays:
            skipped += 1
            logger.info("[BRIEF] -> %s (#%s) SKIP (weekday %d not in %s)",
                        email, sub["id"], today_weekday, weekdays)
            continue

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
        logger.error("Accuracy-Scheduler: SubscriberManager konnte nicht initialisiert werden")
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


def _run_llm_analysis(engine) -> bool:
    """Drained run_all_analyses_stream() einmal. Returns True wenn 'done' Event kam.

    Failure-tolerant: bei Exception oder 'error'-Event wird False geliefert und
    der Daily-Job laeuft mit den alten Analysen weiter.
    """
    try:
        got_done = False
        last_error = None
        for evt in engine.run_all_analyses_stream():
            ev = (evt or {}).get("event")
            if ev == "done":
                got_done = True
                data = evt.get("data", {}) or {}
                logger.info("Daily run: LLM-Analyse done (total_calls=%s, mode=%s)",
                            data.get("total_calls"), data.get("mode"))
            elif ev == "error":
                last_error = (evt.get("data", {}) or {}).get("message")
                logger.error("Daily run: LLM-Analyse error: %s", last_error)
        if not got_done:
            logger.error("Daily run: LLM-Analyse beendet ohne 'done' "
                         "(last_error=%s) — Briefings laufen mit alten Analysen",
                         last_error)
        return got_done
    except Exception as e:
        logger.exception("Daily run: LLM-Analyse-Exception — Briefings laufen "
                         "mit alten Analysen weiter: %s", e)
        return False


def _run_snapshot() -> bool:
    """Friert den heutigen Forecast in data/weather_archive/YYYY-MM-DD.json ein.

    Failure-tolerant: Exception wird geloggt, nicht propagiert. Snapshot ist
    read-only auf wetterdaten.json + spot_analyses.json + region_analyses.json,
    laeuft am Ende des Daily-Runs und beeinflusst Briefings nicht.
    """
    try:
        from scripts.snapshot_weather import build_snapshots, write_snapshots
        snapshots = build_snapshots(target_date=None, all_days=False)
        if not snapshots:
            logger.warning("Daily run: Snapshot — keine Snapshots erstellt "
                           "(heute nicht im Forecast-Fenster?)")
            return False
        written = write_snapshots(snapshots)
        logger.info("Daily run: Snapshot OK (%d Datei(en) geschrieben)", written)
        return True
    except Exception as e:
        logger.exception("Daily run: Snapshot fehlgeschlagen: %s", e)
        return False


def _daily_run(engine) -> dict:
    """Sequenzieller Daily-Job: refresh_weather -> LLM-Analyse -> Briefings -> Snapshot.

    Jeder Schritt ist failure-tolerant: Wenn Wetter-Refresh oder LLM-Analyse
    scheitern, werden Briefings trotzdem mit den zuletzt gecachten Daten/Analysen
    versendet, statt ganz auszufallen. Snapshot laeuft am Ende und friert den
    Stand fuer XContest-Validierung ein.
    """
    logger.info("Daily run: starte Wetter-Refresh...")
    try:
        engine.refresh_weather()
        logger.info("Daily run: Wetter-Refresh OK")
    except Exception as e:
        logger.exception("Daily run: Wetter-Refresh fehlgeschlagen — Briefings "
                         "laufen mit Cache-Daten weiter: %s", e)

    logger.info("Daily run: starte LLM-Analyse...")
    _run_llm_analysis(engine)

    logger.info("Daily run: starte Briefing-Versand...")
    stats = _send_briefings_once(engine)

    logger.info("Daily run: starte Snapshot (Forecast einfrieren)...")
    _run_snapshot()

    return stats


def briefing_scheduler(engine) -> None:
    """Daemon-Thread-Entry: dispatcht Daily-Run (konfig. Tage + Uhrzeit) UND
    Monats-Accuracy (1. des Monats 07:00). Einheitlicher Sleep-Loop.

    Jobs werden innerhalb eines Flask-App-Contexts ausgefuehrt, damit
    render_template (Mailversand) funktioniert.
    """
    test_mode = os.environ.get("SCHEDULER_TEST_MODE", "").strip() in ("1", "true", "yes")
    if test_mode:
        logger.warning("Scheduler: SCHEDULER_TEST_MODE aktiv — erster Lauf in 30s, "
                       "danach normaler Zeitplan")

    # Flask-App einmalig laden — wird pro Job-Aufruf mit app_context() gewrapped.
    from web import app as flask_app

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
        woke_early = _wake_event.wait(timeout=max(1, wait_seconds))
        _wake_event.clear()
        if woke_early:
            logger.info("Scheduler: Config-Aenderung signalisiert — rechne naechsten Slot neu")
            continue  # kein Job ausfuehren, zurueck zum Anfang und Slot neu berechnen

        try:
            with flask_app.app_context(), flask_app.test_request_context():
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
    """`python scheduler.py --now`: voller Daily-Zyklus (Refresh -> LLM-Analyse
    -> Briefings). Exit 0 bei Erfolg (keine Mail-Failures)."""
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

    # .env laden, wie main.py es tut
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    from chat_engine import WingcastEngine
    eng = WingcastEngine()
    try:
        eng.load_weather_from_cache()
    except Exception as e:
        logger.warning("load_weather_from_cache: %s", e)

    # Flask-App-Context ist noetig fuer render_template
    from web import app as flask_app
    with flask_app.app_context(), flask_app.test_request_context():
        stats = _daily_run(eng)

    print(f"[DONE] total={stats['total']} sent={stats['sent']} "
          f"skipped={stats['skipped']} failed={stats['failed']}")
    return 0 if stats["failed"] == 0 else 1


if __name__ == "__main__":
    import argparse
    import sys

    ap = argparse.ArgumentParser(description="Wingcast Briefing-Scheduler")
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
