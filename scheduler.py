"""
Daily-Scheduler (Stufe 4).

Taeglicher Ablauf an konfigurierten Wochentagen (siehe config.DAILY_RUN_*):
  1. engine.refresh_weather()       — Wetterdaten neu laden
  2. engine.build_briefing_data()   — LLM-Analyse (innerhalb _send_briefings_once)
  3. Mails an aktive Subscriber versenden

Zusaetzlich:
  - Monats-Accuracy-Mail am 1. des Monats um 07:00
  - DWD-Frontenarchiv 4x taeglich (FRONTEN_STUNDEN, Plan §6 Schritt 7):
    Karten holen, Linien extrahieren, Aussagen ableiten, Validierung.
    Laeuft auf dem Hetzner-Server; die Daten bleiben server-lokal
    (gitignored wie wetterdaten.json) und werden per
    scripts/sync_from_server.ps1 geholt.

Laufzeit-Modi:
  - als Daemon-Thread (aus main.py aufgerufen): schlaeft bis zum naechsten
    Slot und fuehrt dann die Sequenz aus
  - als CLI (`python scheduler.py --now`): sendet sofort einmal, Exit

Umgebungsvariablen:
  WINGCAST_BRIEFINGS=0          -> Scheduler-Thread startet nicht
  WINGCAST_FRONTEN=0            -> Fronten-Slots werden nicht eingeplant
                                   (Reissleine ohne Deploy)
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

# Bis zu dieser Stunde wird ein ausgefallener Morgenlauf nachgeholt
# (_nachholen_falls_noetig). Spaeter friert ein Snapshot nicht mehr die
# Tagesprognose ein, sondern einen Nowcast auf einen fast abgelaufenen Tag.
NACHHOL_GRENZE_STUNDE = 12

# Bis zu dieser Stunde geht nach einem nachgeholten Lauf auch die Briefing-Mail
# noch raus. Die Grenze ist enger als NACHHOL_GRENZE_STUNDE, weil Archiv und
# Kunde verschiedene Massstaebe haben: fuers Archiv zaehlt, dass die Prognose
# eingefroren ist, fuer den Kunden, dass er den Tag noch planen kann. Ein
# Neustart-Ausfall ist typischerweise in einer knappen Stunde repariert
# (29.08.2026: Lauf abgeschnitten 06:03, Daten fertig 06:47) — das ist eine
# verspaetete Morgenmail, keine Mittagsmail.
NACHSENDE_GRENZE_STUNDE = 9

# DWD-Frontenarchiv (Plan §6 Schritt 7). Vier Laeufe taeglich.
#
# Warum viermal und nicht einmal: Der DWD haelt Open Data nur rund zwei Tage
# vor, und die farbige Handanalyse gibt es NUR als "LATEST" — sie wird alle
# 12 h ueberschrieben, die datierten Zwillinge sind schwarz-weiss und damit
# unbrauchbar. Ein verpasster Termin ist endgueltig weg. Bei hoechstens 6 h
# Abstand faellt kein 12-h-Termin durch, auch wenn ein Lauf scheitert.
#
# Die Stunden sind Ortszeit und muessen es nicht auf die Minute sein — der
# Abstand zaehlt, nicht die Lage. Das Skript ist idempotent, ein Lauf ohne
# neue Karten kostet einen Verzeichnisabruf.
#
# Bewusst NICHT auf 06:00 gelegt: dort laeuft der Daily-Run im selben Thread
# und haelt ihn waehrend der LLM-Analyse lange fest. Faellt ein Slot doch mal
# aus, weil ein Job ueberzieht, kostet das einen von vier — der naechste holt
# es nach, denn der DWD haelt rund zwei Tage vor.
FRONTEN_STUNDEN = (2, 8, 14, 20)
FRONTEN_MINUTE = 10

# Reissleine ohne Deploy: WINGCAST_FRONTEN=0 haelt die Kette an.
def _fronten_aktiv() -> bool:
    return os.environ.get("WINGCAST_FRONTEN", "1").strip() not in ("0", "false", "no")


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


def _next_fronten_time(now: datetime) -> datetime:
    """Naechster Fronten-Slot strikt NACH `now`."""
    for stunde in FRONTEN_STUNDEN:
        candidate = now.replace(hour=stunde, minute=FRONTEN_MINUTE,
                                second=0, microsecond=0)
        if candidate > now:
            return candidate
    return (now + timedelta(days=1)).replace(
        hour=FRONTEN_STUNDEN[0], minute=FRONTEN_MINUTE,
        second=0, microsecond=0)


def _next_event(now: datetime) -> Tuple[datetime, str]:
    """Gibt (Zeitpunkt, 'briefing'|'accuracy'|'fronten') fuers naechste Event."""
    kandidaten = [(_next_send_time(now), "briefing"),
                  (_next_accuracy_time(now), "accuracy")]
    if _fronten_aktiv():
        kandidaten.append((_next_fronten_time(now), "fronten"))
    return min(kandidaten, key=lambda k: k[0])


def _abbruch_hinweis(engine) -> Optional[str]:
    """Bekannter Abbruchgrund der letzten Analyse — nur als Zusatzinfo.

    Er steht in der Betriebsmeldung, damit man nicht im Log suchen muss. In die
    Versand-Entscheidung darf er NICHT einfliessen: die faellt allein an der
    Datenlage, sonst deckt sie nur die Ausfaelle ab, die wir schon kennen.
    """
    try:
        ereignis = getattr(engine, "_api_abort", None)
        if ereignis is not None and ereignis.is_set():
            return getattr(engine, "_api_abort_reason", None)
    except Exception:
        pass
    return None


def _melde_datenluecke(ohne_daten: list, luecken: list, days_count: int,
                       abbruchgrund: Optional[str] = None) -> None:
    """Meldet dem Betrieb, dass Briefings wegen fehlender Bewertungen ausfielen.

    Der Kunde bekommt in dem Fall nichts — also muss es wenigstens hier
    auffallen. Die Meldung nennt zuerst Zahlen; ein bekannter Abbruchgrund
    kommt als Zusatz dazu, nicht als Begruendung der Entscheidung.
    """
    if not ohne_daten and not luecken:
        return
    try:
        # Nur der Server alarmiert — siehe config.ops_produktion().
        erlaubt, grund = config.ops_produktion()
        if not erlaubt:
            logger.info("Scheduler: Datenluecken-Meldung unterdrueckt — %s", grund)
            return
        import email_service
        zeilen = [
            f"Prognosefenster: {days_count} Tage",
            f"Ohne Versand (keine einzige Bewertung): {len(ohne_daten)}",
            f"Versendet mit Luecken: {len(luecken)}",
            "",
        ]
        for email, cov in ohne_daten:
            zeilen.append(f"  KEIN VERSAND  {email} — 0 von {cov['cells']} "
                          f"Zellen bewertet ({cov['regions']} Regionen)")
        for email, cov in luecken:
            zeilen.append(f"  LUECKEN       {email} — {cov['cells_rated']} von "
                          f"{cov['cells']} Zellen, {cov['regions_rated']} von "
                          f"{cov['regions']} Regionen bewertet")
        zeilen += ["", "Gemessen wird die Datenlage, nicht die Ursache."]
        if abbruchgrund:
            zeilen.append(f"Bekannter Abbruchgrund der Analyse: {abbruchgrund}")
        else:
            zeilen.append("Kein Abbruchgrund gemeldet — Log des Morgenlaufs "
                          "pruefen (LLM-Analyse).")
        zeilen.append(f"Geprueft: {datetime.now().isoformat(timespec='seconds')}")
        text = "\n".join(zeilen)
        betreff = (f"[Wingcast] Briefing-Versand: {len(ohne_daten)} ohne Daten, "
                   f"{len(luecken)} mit Luecken")
        html = "<pre>" + text.replace("<", "&lt;").replace(">", "&gt;") + "</pre>"
        email_service.send_email(config.OPS_ALERT_EMAIL, betreff, html, text)
        logger.info("Scheduler: Datenluecken-Meldung an %s raus", config.OPS_ALERT_EMAIL)
    except Exception as e:
        # Wie beim Snapshot-Waechter: eine gescheiterte Meldung darf den Lauf
        # nie mitnehmen.
        logger.exception("Scheduler: Datenluecken-Meldung fehlgeschlagen: %s", e)


def _send_briefings_once(engine, nur_ohne_mail_heute: bool = False) -> dict:
    """Baut briefing_data einmal, loopt ueber aktive Subscriber.
    Returns: {'total': N, 'sent': n_sent, 'skipped': n_skipped, 'failed': n_failed}

    nur_ohne_mail_heute=True fuer den Nachversand nach einem ausgefallenen
    Morgenlauf: dann gehen Mails ausschliesslich an Abos, die heute noch keine
    bekommen haben. Ist der Stand nicht feststellbar, wird nichts versendet —
    eine fehlende Mail ist aergerlich, eine doppelte beschaedigt das Vertrauen.
    """
    from subscriber import get_manager_from_env
    from email_service import send_briefing_email, briefing_coverage

    mgr = get_manager_from_env()
    if mgr is None:
        logger.error("Scheduler: SubscriberManager konnte nicht initialisiert werden")
        return {"total": 0, "sent": 0, "skipped": 0, "failed": 0}

    subscribers = mgr.list_active()
    if nur_ohne_mail_heute:
        schon_versendet = mgr.ids_sent_today()
        if schon_versendet is None:
            logger.error("Scheduler: Nachversand abgebrochen — nicht feststellbar, "
                         "welche Abos heute schon eine Mail haben")
            return {"total": len(subscribers), "sent": 0,
                    "skipped": len(subscribers), "failed": 0,
                    "grund": "Versandstand nicht feststellbar"}
        vorher_n = len(subscribers)
        subscribers = [s for s in subscribers if s["id"] not in schon_versendet]
        logger.info("Scheduler: Nachversand — %d von %d Abos haben heute noch "
                    "keine Mail", len(subscribers), vorher_n)

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
    ohne_daten: list = []   # (email, coverage) — kein Versand
    mit_luecken: list = []  # (email, coverage) — versendet, aber unvollstaendig
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

        # Datenlage-Gate: ohne jede Bewertung geht nichts raus. Eine Mail ohne
        # Datengrundlage liest sich zwangslaeufig wie "diese Woche nichts
        # fliegbar" — der Kunde koennte den Ausfall nicht erkennen. Gemessen
        # wird die Abdeckung, nicht die Ursache des Ausfalls.
        cov = briefing_coverage(sub, briefing_data)
        if cov["state"] == "leer":
            skipped += 1
            ohne_daten.append((email, cov))
            logger.error("[BRIEF] -> %s (#%s) KEIN VERSAND (keine Bewertung: "
                         "0 von %d Zellen, %d Regionen x %d Tage)",
                         email, sub["id"], cov["cells"], cov["regions"], cov["days"])
            continue
        if cov["state"] == "teilweise":
            mit_luecken.append((email, cov))
            logger.warning("[BRIEF] -> %s (#%s) LUECKEN (%d von %d Zellen "
                           "bewertet, fehlende Regionen: %s)",
                           email, sub["id"], cov["cells_rated"], cov["cells"],
                           ", ".join(cov["missing_regions"]) or "keine")

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

    logger.info("Scheduler: fertig. sent=%d skipped=%d failed=%d / %d "
                "(ohne Daten: %d, mit Luecken: %d)",
                sent, skipped, failed, total, len(ohne_daten), len(mit_luecken))
    _melde_datenluecke(ohne_daten, mit_luecken, days_count,
                       _abbruch_hinweis(engine))
    return {"total": total, "sent": sent, "skipped": skipped, "failed": failed,
            "ohne_daten": len(ohne_daten), "mit_luecken": len(mit_luecken)}


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
    read-only auf wetterdaten.json + die aktuelle Analyse-Datei (deutsch oder
    englisch, siehe snapshot_weather), laeuft am Ende des Daily-Runs und
    beeinflusst Briefings nicht.
    """
    try:
        from scripts.snapshot_weather import build_snapshots, write_snapshots
        snapshots = build_snapshots(target_date=None, all_days=False)
        if not snapshots:
            logger.warning("Daily run: Snapshot — keine Snapshots erstellt "
                           "(heute nicht im Forecast-Fenster?)")
            return False
        written = write_snapshots(snapshots)
        # Ein Snapshot ohne Bewertungen ist der teure Fall: er sieht aus wie ein
        # normaler Archivtag, ist aber nie validierbar (Juli 2026: ein Monat
        # Historie still verloren). Darum als ERROR, nicht als Debug-Zeile.
        for day, snap in snapshots.items():
            m = snap.get("_meta", {})
            if not m.get("spots_with_analysis"):
                logger.error("Daily run: Snapshot %s enthaelt 0 Bewertungen "
                             "(Quelle=%s) — Tag ist nicht validierbar. Laeuft "
                             "die LLM-Analyse, und schreibt sie in die Datei, "
                             "die der Snapshot liest?",
                             day, m.get("spot_analysis_source") or "keine")
        logger.info("Daily run: Snapshot OK (%d Datei(en) geschrieben)", written)
        return True
    except Exception as e:
        logger.exception("Daily run: Snapshot fehlgeschlagen: %s", e)
        return False


def _snapshot_pruefen(nachgeholt: Optional[bool] = None) -> dict:
    """Waechter nach jedem Lauf: liegt HEUTE brauchbar im Archiv?

    Der Snapshot-Code meldet Ausfaelle bisher nur als Logzeile — gesehen hat
    sie niemand (Juli 2026: 29 Tage ohne Regionsebene, gefunden erst Wochen
    spaeter). Hier geht daraus eine Mail an config.OPS_ALERT_EMAIL raus,
    derselbe Weg wie beim Frontenalarm.
    """
    try:
        from scripts.snapshot_wache import pruefe_und_melde
        b = pruefe_und_melde(nachgeholt=nachgeholt)
        if b.get("maengel"):
            logger.error("Snapshot-Wache: %s hat Maengel: %s — %s", b["tag"],
                         ", ".join(b["maengel"]), b.get("meldung", "keine Meldung"))
        else:
            logger.info("Snapshot-Wache: %s in Ordnung (%d Startplaetze, "
                        "%d bewertet, %d Regionen)", b["tag"], b["spots"],
                        b["spots_bewertet"], b["regionen"])
        return b
    except Exception as e:
        logger.exception("Snapshot-Wache fehlgeschlagen: %s", e)
        return {}


def _briefings_heute() -> Optional[int]:
    """Wie viele Briefing-Mails sind heute schon raus? None = nicht feststellbar.

    Trennt die beiden Ausfallbilder, die man sonst verwechselt: faellt nur der
    Snapshot-Schritt aus, hat der Kunde seine Mail laengst; faellt der ganze
    Morgenlauf aus, fehlt beides. Die Meldung soll das sagen, nicht raten.
    """
    try:
        from subscriber import get_manager_from_env
        mgr = get_manager_from_env()
        if mgr is None:
            return None
        n = mgr.count_sent_today()
        return None if n < 0 else n
    except Exception as e:
        logger.warning("Snapshot-Nachlauf: Briefing-Stand nicht feststellbar: %s", e)
        return None


def _nachversand_falls_rechtzeitig(engine, nachher: dict) -> dict:
    """Nach einem nachgeholten Lauf die ausgefallenen Briefing-Mails senden.

    Drei Bedingungen, alle am messbaren Ergebnis festgemacht, nicht an der
    vermuteten Ausfallursache:
      1. Die Datenkette steht (keine Maengel im Snapshot-Befund). Auf einer
         halben Datenlage waere die Mail schlechter als keine.
      2. Es ist noch vor NACHSENDE_GRENZE_STUNDE.
      3. Der Versandstand je Abo ist feststellbar (prueft _send_briefings_once).

    Returns ein dict fuer die Waechter-Meldung: {'sent': n} oder {'grund': ...}.
    """
    if nachher.get("maengel"):
        grund = ("Datenkette blieb unvollstaendig (%s)"
                 % ", ".join(nachher["maengel"]))
        logger.warning("Nachversand: kein Versand — %s", grund)
        return {"sent": 0, "grund": grund}

    jetzt = datetime.now()
    if jetzt.hour >= NACHSENDE_GRENZE_STUNDE:
        grund = (f"Daten erst um {jetzt.strftime('%H:%M')} fertig, Grenze fuer "
                 f"eine Morgenmail ist {NACHSENDE_GRENZE_STUNDE:02d}:00")
        logger.warning("Nachversand: kein Versand — %s", grund)
        return {"sent": 0, "grund": grund}

    logger.warning("Nachversand: sende Briefings nach (%s) — nur an Abos ohne "
                   "heutige Mail", jetzt.strftime("%H:%M"))
    try:
        stats = _send_briefings_once(engine, nur_ohne_mail_heute=True)
    except Exception as e:
        logger.exception("Nachversand: fehlgeschlagen: %s", e)
        return {"sent": 0, "grund": f"Nachversand-Exception: {e}"}

    stats["zeit"] = jetzt.strftime("%H:%M")
    logger.info("Nachversand: fertig. sent=%d skipped=%d failed=%d",
                stats.get("sent", 0), stats.get("skipped", 0),
                stats.get("failed", 0))
    return stats


def _nachholen_falls_noetig(engine) -> None:
    """Beim Start pruefen, ob der heutige Daily-Run ausgefallen ist — und ihn
    fuer die Datenkette nachholen.

    Warum das noetig ist: `_next_send_time` liefert immer den naechsten Termin
    STRIKT NACH jetzt. Startet der Dienst um 06:03 neu — der Normalfall bei
    einem Deploy am Morgen —, faellt der 06:00-Lauf ersatzlos aus, und der
    Archivtag ist endgueltig weg (die Prognose von heute Morgen existiert
    nirgends sonst). Genau so sind zwischen Mai und Juli 2026 neun Tage
    verschwunden, zusaetzlich zum abgeschnittenen 23.06.

    Nachgeholt wird die Datenkette (Wetter -> LLM-Analyse -> Snapshot) und —
    wenn die Daten stehen und es noch vor NACHSENDE_GRENZE_STUNDE ist — auch
    der Briefing-Versand, ausschliesslich an Abos ohne heutige Mail. Frueher
    unterblieb der Versand ganz, mit zwei Begruendungen, die beide nicht
    tragen: ein Doppelversand ist ausschliessbar (last_sent_at je Abo, siehe
    subscriber.ids_sent_today), und "Morgenmail um 11:00" war die falsche
    Vorstellung von der Verspaetung — der Nachlauf startet, sobald der Dienst
    wieder laeuft. Was bleibt, ist die Zeitgrenze; nach ihr meldet der
    Waechter den ausgefallenen Versand, statt ihn nachzuholen.
    """
    from scripts import snapshot_wache

    now = datetime.now()
    heute = now.date().isoformat()

    # Nur auf dem Server. Ein Entwicklungsrechner hat kein aktuelles Archiv,
    # findet den Tag also immer "fehlend" — und wuerde vormittags eine volle
    # LLM-Analyse nachziehen (rund 1500 Aufrufe, echte Kosten) fuer ein
    # Archiv, das dort niemanden interessiert.
    erlaubt, grund = config.ops_produktion()
    if not erlaubt:
        logger.info("Snapshot-Nachlauf uebersprungen — %s", grund)
        return

    if now.weekday() not in config.DAILY_RUN_WEEKDAYS:
        return
    slot = now.replace(hour=config.DAILY_RUN_HOUR, minute=config.DAILY_RUN_MINUTE,
                       second=0, microsecond=0)
    if now <= slot:
        return                      # der heutige Lauf steht noch bevor

    vorher = snapshot_wache.befund(heute)
    if not vorher["maengel"]:
        return                      # Lauf ist gelaufen, alles da

    if not snapshot_wache.nachhol_versuch_offen(heute):
        logger.warning("Snapshot-Nachlauf: fuer %s bereits versucht — kein "
                       "zweiter Anlauf (Schutz gegen Neustart-Schleife)", heute)
        return
    # Vermerk VOR dem Lauf: startet der Dienst wiederholt neu, weil etwas
    # anderes kaputt ist, darf das nicht jedes Mal eine volle LLM-Analyse kosten.
    snapshot_wache.vermerke_nachhol_versuch(heute)

    if now.hour >= NACHHOL_GRENZE_STUNDE:
        # Nach der Mittagsgrenze friert ein Snapshot nicht mehr die
        # Tagesprognose ein, sondern einen Nowcast auf einen fast abgelaufenen
        # Tag. Als Beleg ist das wertlos — dann lieber ehrlich melden.
        logger.error("Snapshot-Nachlauf: %s fehlt (%s), aber es ist %02d:%02d — "
                     "nach %02d:00 ist der Tag als Prognose-Beleg nicht mehr "
                     "zu retten. Kein Nachlauf.", heute, ", ".join(vorher["maengel"]),
                     now.hour, now.minute, NACHHOL_GRENZE_STUNDE)
        _snapshot_pruefen(nachgeholt=False)
        return

    logger.warning("Snapshot-Nachlauf: %s fehlt (%s) — hole Wetter, Analyse und "
                   "Snapshot nach (ohne Briefing-Versand)",
                   heute, ", ".join(vorher["maengel"]))
    try:
        engine.refresh_weather()
        logger.info("Snapshot-Nachlauf: Wetter-Refresh OK")
    except Exception as e:
        logger.exception("Snapshot-Nachlauf: Wetter-Refresh fehlgeschlagen — "
                         "weiter mit Cache-Daten: %s", e)
    _run_llm_analysis(engine)
    _run_snapshot()

    nachher = snapshot_wache.befund(heute)
    # Versandstand VOR dem Nachversand festhalten: danach steht der Zaehler auf
    # den gerade verschickten Mails und die Meldung wuerde "Versand in Ordnung"
    # sagen — genau die Verwechslung, die _briefing_lage aufloesen soll.
    briefings_vorher = _briefings_heute()
    nachversand = _nachversand_falls_rechtzeitig(engine, nachher)
    logger.info("Snapshot-Nachlauf: %s",
                snapshot_wache.melde_nachlauf(vorher, nachher, briefings_vorher,
                                              nachversand=nachversand))
    if nachher["maengel"]:
        logger.error("Snapshot-Nachlauf: %s bleibt unvollstaendig (%s)",
                     heute, ", ".join(nachher["maengel"]))


def _run_gewitter_validation() -> bool:
    """Gewitter-Abgleich: Warnung (Freeze) gegen SMN-Messung.

    NICHT der Vortag: MeteoSchweiz fuehrt die Zehnminuten-Dateien erst am
    Folgetag gegen 11:00 UTC nach. Der 06:00-Lauf sah vom Vortag nur
    00:00-01:50 und schrieb den Rest als ereignislos ins Scoreboard (am
    03.08.2026 real passiert, gefunden 04.08.). Darum den juengsten
    vollstaendig publizierten Tag validieren — im Morgenlauf ist das D-2.

    Schreibt validation/gewitter/{messwerte,urteile}/ + Scoreboard +
    AUTO_REPORT (Konvention: validation/README.md). Failure-tolerant wie der
    Snapshot — eine ausgefallene Validierung stoppt nie den Wetterlauf.
    Idempotent: existierende Messwerte werden wiederverwendet.
    """
    try:
        import datetime as _dt
        from scripts.validate_gewitter_daily import (
            letzter_vollstaendiger_tag, rebuild_scoreboard, validate_day,
            write_report)
        from scripts import validation_common as vc
        day = letzter_vollstaendiger_tag(_dt.datetime.now())
        stations = vc.smn_stations_by_region()
        if not validate_day(day, stations):
            logger.warning("Daily run: Gewitter-Validierung %s ohne Ergebnis "
                           "(kein Freeze oder keine SMN-Daten)", day)
            return False
        write_report(rebuild_scoreboard())
        logger.info("Daily run: Gewitter-Validierung %s OK", day)
        return True
    except Exception as e:
        logger.exception("Daily run: Gewitter-Validierung fehlgeschlagen: %s", e)
        return False


def _run_fronten() -> bool:
    """Holt die DWD-Frontenkarten und laesst die Validierung darueber laufen.

    Als Subprozess und nicht per Import: das Archivskript startet selbst
    Unterprozesse fuer Extraktion und Zeitachse und laeuft im Extremfall
    Minuten. Ein eigener Prozess kann hart abgebrochen werden, ohne den
    Scheduler-Thread des laufenden Webdienstes mitzunehmen.

    Failure-tolerant wie der Grid-Refresh: ein Fehler hier darf den
    Briefing-Versand nie blockieren. Ausfaelle meldet das Skript selbst per
    Mail an config.OPS_ALERT_EMAIL (scripts/fronten_alarm.py).
    """
    import subprocess
    import sys
    from pathlib import Path

    skript = Path(__file__).resolve().parent / "scripts" / "archive_dwd_fronten.py"
    try:
        p = subprocess.run([sys.executable, str(skript)],
                           capture_output=True, text=True, timeout=3600)
    except subprocess.TimeoutExpired:
        logger.error("Fronten: Archivlauf nach 60 min abgebrochen")
        return False
    except Exception as e:
        logger.exception("Fronten: Archivlauf nicht startbar: %s", e)
        return False

    letzte = (p.stdout or "").strip().splitlines()[-3:]
    if p.returncode == 0:
        logger.info("Fronten: Archivlauf ok — %s", " | ".join(letzte))
        return True
    logger.error("Fronten: Archivlauf rc=%s — %s | %s", p.returncode,
                 " | ".join(letzte), (p.stderr or "").strip()[-300:])
    return False


def _run_ogn_sessions() -> bool:
    """OGN-Rohpunkte des Vortags zu Fluegen verdichten (Phase 2).

    Der Collector laeuft als eigener Daemon (ogn-collector.service) und schreibt
    nur Rohpunkte; hier entstehen daraus Fluege mit Steig- und Hoehenwerten.
    Der Vortag ist sicher abgeschlossen — der laufende Tag waere es nicht.

    Failure-tolerant wie Snapshot und Gewitter: eine ausgefallene Verdichtung
    darf den Wetterlauf nie stoppen. Idempotent — der Tag wird vor dem Schreiben
    geleert, ein zweiter Lauf ist harmlos.

    Das Pruning der Rohpunkte laeuft bewusst NUR hier und nicht im Collector-
    Takt: erst verdichten, dann wegwerfen.
    """
    try:
        import datetime as _dt
        import ogn_sessions
        if not ogn_sessions.DB_PATH.exists():
            logger.info("Daily run: keine OGN-Datenbank — uebersprungen")
            return False
        gestern = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()
        conn = ogn_sessions._connect()
        try:
            ogn_sessions.init_db(conn)
            res = ogn_sessions.run_day(conn, gestern)
            weg = ogn_sessions.prune_beacons(conn)
            offen = ogn_sessions.unverdichtete_tage(conn)
        finally:
            conn.close()
        logger.info("Daily run: OGN %s — %d Fluege, %d Regionen, "
                    "%d Rohpunkte geloescht",
                    gestern, res["fluege"], res["regionen"], weg)
        # Bei 7 Tagen Aufbewahrung ist ein Rueckstand die Zahl, die zaehlt:
        # was hier auflaeuft, ist noch da — aber nicht mehr lange.
        if offen:
            logger.warning("Daily run: OGN — %d Tage unverdichtet (%s). "
                           "Nachholen mit: ogn_sessions.py --backfill",
                           len(offen), ", ".join(offen[:5]))
        return True
    except Exception as e:
        logger.exception("Daily run: OGN-Verdichtung fehlgeschlagen: %s", e)
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
    _snapshot_pruefen()

    logger.info("Daily run: starte Gewitter-Validierung (letzter komplett "
                "publizierter Tag)...")
    _run_gewitter_validation()

    logger.info("Daily run: starte OGN-Verdichtung (Vortag)...")
    _run_ogn_sessions()

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

    # Erst nachholen, dann in den Schlaf: ein Neustart nach 06:00 hat sonst
    # gerade den Archivtag gekostet. Failure-tolerant wie jeder Job hier — ein
    # Fehler beim Nachholen darf den Scheduler nicht am Starten hindern.
    if not test_mode:
        try:
            with flask_app.app_context(), flask_app.test_request_context():
                _nachholen_falls_noetig(engine)
        except Exception as e:
            logger.exception("Scheduler: Nachhol-Pruefung fehlgeschlagen: %s", e)

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
                elif next_event_type == "fronten":
                    _run_fronten()
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
