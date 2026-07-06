"""
Flask Web-Server für Wingcast.
Routes: Chat-API, Spots-API, Wetter-API, Meteogramm-API.
"""

import os
import copy
import hashlib
import json
import logging
import math
import sys
import threading
from functools import wraps
from typing import Optional
from flask import Flask, render_template, request, jsonify, redirect, url_for, Response, \
    stream_with_context, session, send_from_directory
from datetime import datetime, timedelta

import config
import i18n

logger = logging.getLogger(__name__)


def _fm(key: str, **kwargs) -> str:
    """Flash-Message: uebersetzt key (DE/EN) und URL-encodet ihn fuer redirect ?ok=/?err=."""
    from urllib.parse import quote_plus
    return quote_plus(i18n.t(key, **kwargs))


from thermik_calculator import compute_daily_thermals
from source_area import get_all_regions_geojson, get_all_regions
from subscriber import get_manager_from_env as _get_subscriber_manager
from feedback import get_manager_from_env as _get_feedback_manager
from email_service import send_confirm_email, send_welcome_email, build_briefing_context
from fetch_weather import get_weather_for_location
from foehn_indicators import fetch_foehn_data, evaluate_foehn, FOEHN_STATIONS, \
    THRESHOLD_DELTA_P_CAUTION, THRESHOLD_DELTA_P_DANGER, THRESHOLD_HUMIDITY_LOW
from gust_calculator import (
    estimate_altitude_gusts,
    collect_gust_anchors,
    estimate_altitude_gusts_multi_anchor,
    get_scale_height,
    get_oi_scale_lengths,
    get_L_up,
    get_effective_L_up,
)
from source_area import find_region_for_point

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "wingcast-dev-key")

# Session-Cookie: 1 Jahr persistent (Magic-Link login soll nicht jeden Tag wiederholt werden)
app.permanent_session_lifetime = timedelta(days=365)

# Ensure JSON responses send raw UTF-8 characters (ä, ö, ü instead of \uXXXX)
app.config['JSON_AS_ASCII'] = False
app.json.ensure_ascii = False


# ---------------------------------------------------------------------------
# Day-Gating: anonyme Web-Besucher sehen 2 Tage, eingeloggte Subscriber 5 Tage.
# Eingeloggt = Session-Cookie 'sub_id' (gesetzt via Magic-Link oder /account/<token>).
# ---------------------------------------------------------------------------
ANON_FORECAST_DAYS = 1

def current_max_days() -> int:
    """Maximale sichtbare Vorhersage-Tage fuer aktuellen Request."""
    if session.get("sub_id"):
        return config.FORECAST_DAYS
    return min(ANON_FORECAST_DAYS, config.FORECAST_DAYS)


def _allowed_date_strs(max_days: int) -> set:
    """ISO-Date-Strings (YYYY-MM-DD) ab heute fuer max_days. Set fuer O(1) Lookup.

    Im Test-View wird das Snapshot-Datum (source_run_at) als "Heute" verwendet,
    damit eingefrorene Snapshots zeitlich konsistent bleiben (sonst rutscht das
    Datumsfenster taeglich weiter, waehrend die Test-Analysen am Snapshot-Tag
    eingefroren sind).
    """
    base = None
    try:
        from engine import test_mode
        if test_mode.is_view_active():
            base = test_mode.frozen_base_date()
    except Exception:
        base = None
    if base is None:
        base = datetime.now().date()
    return {(base + timedelta(days=i)).isoformat() for i in range(max(1, int(max_days)))}


def _gate_forecast(sorted_dates, *by_day_dicts):
    """Begrenzt sorted_dates + alle uebergebenen by_day-Dicts auf current_max_days.
    Returns: (truncated_dates_list, *truncated_dicts).
    Eingeloggte Subscriber sehen alles, Anonyme nur ANON_FORECAST_DAYS."""
    max_days = current_max_days()
    if len(sorted_dates) <= max_days:
        return (sorted_dates, *by_day_dicts)
    kept = sorted_dates[:max_days]
    kept_set = set(kept)
    truncated = tuple(
        {k: v for k, v in (bd or {}).items() if k in kept_set}
        for bd in by_day_dicts
    )
    return (kept, *truncated)


@app.context_processor
def _inject_i18n():
    """Stellt {{ t("key") }} und {{ lang }} in allen Templates bereit.
    lang = aktive globale Sprache (config.LANG), t = Uebersetzung mit DE-Fallback."""
    import i18n
    return {"t": i18n.t, "lang": i18n.get_current_lang(), "js_i18n": i18n.js_i18n()}


@app.context_processor
def _inject_session_flags():
    """Templates koennen via {% if is_logged_in %} pruefen.
    Plus: marketing_url + legal_urls fuer Footer-Links."""
    marketing = config.MARKETING_URL.rstrip("/")
    return {
        "is_logged_in": bool(session.get("sub_id")),
        "is_admin": _is_admin(),
        "session_email": session.get("email", ""),
        "marketing_url": marketing,
        "datenschutz_url": f"{marketing}/datenschutz",
        "impressum_url": f"{marketing}/impressum",
    }


def _is_admin() -> bool:
    """True wenn die Session mit der Admin-E-Mail eingeloggt ist (passwortlos).

    Admin = wer per Magic-Link als config.ADMIN_EMAIL eingeloggt ist.
    """
    email = (session.get("email") or "").strip().lower()
    return bool(email) and email == (config.ADMIN_EMAIL or "").strip().lower()


def _is_admin_session() -> bool:
    """True wenn die aktuelle Session via Admin-Login verifiziert wurde."""
    return bool(session.get("admin_debug"))


@app.context_processor
def _inject_analytics():
    """PostHog-Config fuer base.html. posthog_enabled steuert, ob Banner +
    Loader ueberhaupt gerendert werden (nur wenn ein Key konfiguriert ist).
    Das Script wird clientseitig erst nach Opt-in-Consent initialisiert."""
    return {
        "posthog_enabled": bool(config.POSTHOG_KEY),
        "posthog_key": config.POSTHOG_KEY,
        "posthog_host": config.POSTHOG_HOST,
        "posthog_ui_host": config.POSTHOG_UI_HOST,
    }


@app.context_processor
def _inject_test_mode_flag():
    """Globales Flag fuer den persistenten Test-Mode-Banner in base.html.

    Liest den Toggle bei jedem Request — leichtgewichtig, da nur eine
    JSON-Datei mit einem Bool-Feld geprueft wird.
    """
    try:
        from engine import test_mode
        return {
            "test_view_active": test_mode.is_view_active(),
            "admin_debug_active": _is_admin_session(),
        }
    except Exception:
        return {"test_view_active": False, "admin_debug_active": False}


# Cache-Busting für statische Files: liefert mtime des Files als Versions-String,
# der an Script-/Link-URLs angehängt wird (?v=...). Bei jeder Datei-Änderung ändert
# sich der Wert und der Browser muss zwingend neu laden.
@app.context_processor
def _inject_static_v():
    static_dir = os.path.join(app.root_path, "static")

    def static_v(filename):
        try:
            full = os.path.join(static_dir, filename)
            return str(int(os.path.getmtime(full)))
        except OSError:
            return "0"

    return {"static_v": static_v}


# Weather-API responses ändern sich nur beim Refresh (~1x/Tag).
# 60s Browser-Cache = sofortige Overlays beim Tab-Wechsel, ohne stale-Risiko.
_CACHEABLE_PREFIXES = ("/api/weather/", "/api/altitude-wind/",
                       "/api/region-weather/", "/api/region-altitude-wind/",
                       "/api/foehn", "/api/regionen-polygone")

@app.after_request
def _add_cache_headers(response):
    if request.path.startswith(_CACHEABLE_PREFIXES) and response.status_code == 200:
        response.headers["Cache-Control"] = "public, max-age=60"
    return response


# ---------------------------------------------------------------------------
# JSON-Error-Handler für /api/*
# Ohne dies liefert Flask bei Exceptions/404 eine HTML-Fehlerseite zurück,
# was im Frontend zu "Unexpected token '<'..."-Parse-Fehlern führt.
# Alle API-Routen antworten jetzt garantiert mit JSON.
# ---------------------------------------------------------------------------
from werkzeug.exceptions import HTTPException


def _is_api_request() -> bool:
    try:
        return request.path.startswith("/api/")
    except RuntimeError:
        return False


@app.errorhandler(HTTPException)
def _handle_http_exception(e):
    if _is_api_request():
        return jsonify({"error": e.description or e.name, "status": e.code}), e.code
    return e  # Default HTML-Handling für Seiten


@app.errorhandler(Exception)
def _handle_unexpected_exception(e):
    logger.exception("Unbehandelte Exception bei %s", getattr(request, "path", "?"))
    if _is_api_request():
        return jsonify({"error": "Serverfehler: " + str(e), "status": 500}), 500
    # Nicht-API: Flask-Default (HTML) weiterreichen
    raise e


# Global engine instance (set in main.py)
engine = None


def init_app(wingcast_engine):
    """Setzt die globale Engine-Instanz."""
    global engine
    engine = wingcast_engine


# ============================================================================
# SUBSCRIBER / E-MAIL-BRIEFING ROUTES (Stufe 1 — ohne Versand)
# ============================================================================

def _regions_for_form():
    """Liste der Regionen fuer das Subscribe-Formular. Sortiert nach Name."""
    regions = get_all_regions()
    simple = [{"id": r["id"], "region": r["region"]} for r in regions]
    simple.sort(key=lambda x: x["region"].lower())
    return simple


def _region_names(region_ids: list[str]) -> list[str]:
    """IDs -> Anzeigenamen. Unbekannte IDs werden durchgereicht."""
    lookup = {r["id"]: r["region"] for r in get_all_regions()}
    return [lookup.get(rid, rid) for rid in (region_ids or [])]


def _status_page(state: str, title: str, message: str = "", submessage: str = "",
                 http_code: int = 200):
    html = render_template(
        "subscribe_status.html",
        state=state, title=title, message=message, submessage=submessage,
    )
    return html, http_code


@app.route("/preview/briefing", methods=["GET"])
def preview_briefing():
    """Rendert das Briefing mit Demo-Subscriber (alle Regionen) und aktuellen
    echten Daten. Ohne Auth — fuer Landing-Page-Sample.
    """
    if engine is None:
        return _status_page(
            "error", "Vorschau nicht verfuegbar",
            "Der Wingcast-Service ist gerade nicht geladen.",
            http_code=503,
        )

    try:
        briefing_data = engine.build_briefing_data()
    except Exception as e:
        logger.exception("preview_briefing: build_briefing_data failed: %s", e)
        return _status_page(
            "error", "Vorschau nicht verfuegbar",
            "Die Wingcast-Daten konnten gerade nicht geladen werden.",
            http_code=503,
        )

    # Demo-Subscriber mit allen Regionen (so sieht man Spots aus der ganzen Schweiz)
    all_region_ids = [r["id"] for r in get_all_regions()]
    demo_subscriber = {
        "id": 0,
        "email": "vorschau@wingcast.ch",
        "regions": all_region_ids,
        "skill_level": "standard",
        "action_token": "demo",
    }

    ctx = build_briefing_context(demo_subscriber, briefing_data)
    # Vorschau-Links neutralisieren, damit niemand versehentlich '/unsubscribe/demo' klickt
    ctx["urls"]["unsubscribe"] = "#"
    ctx["urls"]["feedback_correct"] = "#"
    ctx["urls"]["feedback_wrong"] = "#"
    ctx["urls"]["account"] = "#"
    # Dashboard-Link darf bleiben — zeigt auf /briefing mit Filter

    return render_template("email/briefing.html", **ctx)


@app.route("/subscribe", methods=["GET"])
def subscribe_form():
    """Legacy-Route — Subscribe-Formular wurde entfernt. Direkt-URLs gehen zur Login-Seite."""
    return redirect("/login")


@app.route("/subscribe", methods=["POST"])
def subscribe_submit():
    """Legacy-Route — Subscribe-Formular gibt es nicht mehr. Anmeldung laeuft via
    Magic-Link auf /login. Antwort 410 Gone fuer alte Forms / Bookmarks."""
    return _status_page(
        state="error",
        title=i18n.t("status.gone_title"),
        message=i18n.t("status.gone_msg"),
        submessage=i18n.t("status.gone_sub"),
        http_code=410,
    )


@app.route("/confirm/<token>", methods=["GET"])
def subscribe_confirm(token):
    mgr = _get_subscriber_manager()
    if mgr is None:
        return _status_page(
            "error", i18n.t("status.confirm_fail_title"),
            i18n.t("status.service_unavail_retry"),
            http_code=503,
        )

    result = mgr.confirm(token)
    if result is None:
        # Vielleicht schon bestaetigt? Dann ist confirm_token NULL -> get_by_action_token wuerde gehen,
        # aber der Link kommt nicht vom Action-Token. Wir zeigen einfach "ungueltig/abgelaufen".
        return _status_page(
            "error", i18n.t("status.link_invalid_used_title"),
            i18n.t("status.link_invalid_used_msg"),
            http_code=404,
        )

    # Welcome-Mail (async, nicht blockierend)
    try:
        send_welcome_email(
            email=result["email"],
            action_token=result["action_token"],
            regions=_region_names(result.get("regions") or []),
            skill_level=result.get("skill_level", "standard"),
        )
    except Exception as e:
        logger.exception("Welcome-Mail-Versand fehlgeschlagen fuer %s: %s",
                         result["email"], e)

    return _status_page(
        "ok", i18n.t("status.sub_activated_title"),
        i18n.t("status.welcome_msg", email=result["email"]),
        submessage=i18n.t("status.first_wingcast_sub"),
    )


@app.route("/feedback/<token>/<verdict>", methods=["GET"])
def subscribe_feedback(token, verdict):
    """One-Click-Feedback aus Briefing-Mail. Akzeptiert correct|wrong.
    Rate-Limit: max 1 Eintrag pro Subscriber pro Kalendertag.
    """
    if verdict not in ("correct", "wrong"):
        return _status_page(
            "error", i18n.t("status.invalid_rating_title"),
            i18n.t("status.invalid_link_msg"),
            http_code=400,
        )

    mgr = _get_subscriber_manager()
    if mgr is None:
        return _status_page(
            "error", i18n.t("status.feedback_fail_title"),
            i18n.t("status.service_unavail"),
            http_code=503,
        )

    sub = mgr.get_by_action_token(token)
    if sub is None:
        return _status_page(
            "error", i18n.t("status.link_invalid_title"),
            i18n.t("status.feedback_link_invalid_msg"),
            http_code=404,
        )

    from datetime import date
    ok = mgr.record_feedback(sub["id"], date.today(), verdict)
    if not ok:
        return _status_page(
            "error", i18n.t("status.feedback_fail_title"),
            i18n.t("status.feedback_save_fail_msg"),
            http_code=500,
        )

    if verdict == "correct":
        return _status_page(
            "ok", i18n.t("status.feedback_confirm_title"),
            i18n.t("status.feedback_confirm_msg"),
        )
    return _status_page(
        "ok", i18n.t("status.feedback_thanks_title"),
        i18n.t("status.feedback_wrong_msg"),
        submessage=i18n.t("status.feedback_wrong_sub"),
    )


@app.route("/account", methods=["GET"])
def account_dispatch():
    """Zentrale Konto-Seite — nur fuer eingeloggte User.
    - Eingeloggt: redirect auf /account/<action_token> (Einstellungen)
    - Anonym: redirect zur Login-Seite (es gibt keine separate Abo-Seite mehr)"""
    sub_id = session.get("sub_id")
    logger.info("account_dispatch: sub_id=%s session_keys=%s host=%s cookies=%s",
                sub_id, list(session.keys()), request.host,
                list(request.cookies.keys()))
    if sub_id:
        mgr = _get_subscriber_manager()
        if mgr is not None:
            sub = mgr.get_session_user(sub_id)
            if sub and sub.get("action_token"):
                return redirect(f"/account/{sub['action_token']}")
            logger.warning("account_dispatch: sub_id=%s -> get_session_user None, clearing", sub_id)
        # Session zeigt auf nicht mehr existierenden User → Cookie loeschen
        session.clear()
    return redirect("/login")


@app.route("/account/<token>", methods=["GET"])
def account_page(token):
    mgr = _get_subscriber_manager()
    if mgr is None:
        return _status_page(
            "error", "Service nicht verfuegbar",
            "Bitte spaeter nochmal versuchen.",
            http_code=503,
        )
    sub = mgr.get_by_action_token(token)
    if sub is None:
        return _status_page(
            "error", "Link ungueltig",
            "Dieser Account-Link ist nicht (mehr) gueltig.",
            http_code=404,
        )
    # Auto-Login: Klick auf /account/<action_token> aus Briefing-Mail = implizite Authentifizierung
    session.permanent = True
    session["sub_id"] = sub["id"]
    session["email"] = sub["email"]

    from datetime import date as _date
    return render_template(
        "account.html",
        subscriber=sub,
        token=token,
        region_names=_region_names(sub.get("regions") or []),
        regions=_regions_for_form(),
        prefill_regions=set(sub.get("regions") or []),
        active_weekdays=set(sub.get("active_weekdays") or []),
        prefill_tiers=set(sub.get("min_tier_set") or []),
        prefill_min_rating=float(sub.get("min_rating") or 0.0),
        today_iso=_date.today().isoformat(),
        flash_ok=request.args.get("ok", ""),
        flash_error=request.args.get("err", ""),
    )


@app.route("/account/<token>/<action>", methods=["POST"])
def account_action(token, action):
    mgr = _get_subscriber_manager()
    if mgr is None:
        return redirect(f"/account/{token}?err={_fm('flash.service_unavailable')}")

    if action == "pause_14d" or action == "pause_30d":
        from datetime import date, timedelta
        days = 14 if action == "pause_14d" else 30
        until = date.today() + timedelta(days=days)
        ok = mgr.pause(token, until)
        if not ok:
            return redirect(f"/account/{token}?err={_fm('flash.pause_failed')}")
        return redirect(f"/account/{token}?ok={_fm('flash.paused_until', until=until.isoformat())}")

    if action == "resume":
        ok = mgr.resume(token)
        if not ok:
            return redirect(f"/account/{token}?err={_fm('flash.resume_failed')}")
        return redirect(f"/account/{token}?ok={_fm('flash.sub_active_again')}")

    if action == "unsubscribe":
        ok = mgr.unsubscribe(token)
        if not ok:
            return redirect(f"/account/{token}?err={_fm('flash.unsub_failed')}")
        # Session bleibt — User soll auf der Konto-Seite den Reaktivieren-Banner sehen
        return redirect(f"/account/{token}?ok={_fm('flash.unsubscribed')}")

    if action == "update":
        # Form-Daten: regions[], weekdays[], tiers[] (Checkboxes), min_rating (slider)
        regions = request.form.getlist("regions")
        weekdays_raw = request.form.getlist("weekdays")
        tiers = request.form.getlist("tiers")
        min_rating_raw = (request.form.get("min_rating") or "").strip()

        try:
            weekdays = [int(w) for w in weekdays_raw if w.strip().isdigit()]
        except ValueError:
            weekdays = []

        if not regions:
            return redirect(f"/account/{token}?err={_fm('flash.need_region')}")
        if not weekdays:
            return redirect(f"/account/{token}?err={_fm('flash.need_weekday')}")
        if not tiers:
            return redirect(f"/account/{token}?err={_fm('flash.need_tier')}")

        try:
            min_rating = float(min_rating_raw) if min_rating_raw else 0.0
        except ValueError:
            min_rating = 0.0

        ok = mgr.update_preferences(
            token,
            regions=regions,
            weekdays=weekdays,
            min_tier_set=tiers,
            min_rating=min_rating,
        )
        if not ok:
            return redirect(f"/account/{token}?err={_fm('flash.save_failed')}")

        # Pause-Range: paused_from + paused_until.
        # Beide leer -> Pause aufheben. Beide gesetzt + valide -> pause(until, from).
        from datetime import date as _date
        paused_from_raw = (request.form.get("paused_from") or "").strip()
        paused_until_raw = (request.form.get("paused_until") or "").strip()

        if paused_until_raw:
            try:
                until = _date.fromisoformat(paused_until_raw)
                from_date = None
                if paused_from_raw:
                    from_date = _date.fromisoformat(paused_from_raw)
                # Vergangenes Bis-Datum: ignorieren (kein Sinn)
                if until >= _date.today():
                    mgr.pause(token, until_date=until, from_date=from_date)
            except ValueError:
                pass  # Ungueltiges Datum -> ignorieren, andere Settings bleiben gespeichert
        else:
            # Bis leer -> Pause aufheben (no-op wenn nicht pausiert)
            mgr.resume(token)

        return redirect(f"/account/{token}?ok={_fm('flash.settings_saved')}")

    if action == "logout":
        session.clear()
        return redirect("/")

    if action == "reactivate":
        ok = mgr.reactivate(token)
        if not ok:
            return redirect(f"/account/{token}?err={_fm('flash.reactivate_failed')}")
        return redirect(f"/account/{token}?ok={_fm('flash.reactivated')}")

    if action == "feedback":
        msg = (request.form.get("message") or "").strip()
        if not msg:
            return redirect(f"/account/{token}?err={_fm('flash.need_message')}")
        ok = mgr.record_product_feedback(token, msg)
        if not ok:
            return redirect(f"/account/{token}?err={_fm('flash.feedback_save_failed')}")
        return redirect(f"/account/{token}?ok={_fm('flash.feedback_thanks')}")

    if action == "export":
        # DSG Art. 28: Datenherausgabe in maschinenlesbarem Format.
        # Liefert alle gespeicherten User-Daten als JSON-Download.
        sub = mgr.get_by_action_token(token)
        if sub is None:
            return redirect(f"/account/{token}?err={_fm('flash.account_not_found')}")
        # Feedback-Historie dazu
        feedback = []
        try:
            with mgr._cursor() as cur:
                cur.execute(
                    """SELECT briefing_date, verdict, created_at
                         FROM subscriber_feedback
                        WHERE subscriber_id = ?
                        ORDER BY created_at DESC""",
                    (sub["id"],),
                )
                for row in cur.fetchall():
                    feedback.append({
                        "briefing_date": row[0],
                        "verdict": row[1],
                        "created_at": row[2],
                    })
        except Exception as e:
            logger.error("export feedback fetch failed: %s", e)

        # action_token + login_token bewusst NICHT exportieren (Sicherheit)
        export = {
            "_exported_at": datetime.now().isoformat(),
            "_format_version": 1,
            "account": {
                "email": sub.get("email"),
                "status": sub.get("status"),
                "skill_level": sub.get("skill_level"),
                "regions": sub.get("regions") or [],
                "active_weekdays": sub.get("active_weekdays") or [],
                "min_tier_set": sub.get("min_tier_set") or [],
                "min_rating": sub.get("min_rating", 0.0),
                "paused_from": sub.get("paused_from"),
                "paused_until": sub.get("paused_until"),
            },
            "feedback_history": feedback,
        }
        body = json.dumps(export, indent=2, ensure_ascii=False, default=str)
        from datetime import date as _d
        filename = f"wingcast-export-{_d.today().isoformat()}.json"
        return Response(
            body,
            mimetype="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Cache-Control": "no-store",
            },
        )

    if action == "delete-account":
        # Self-Service Account-Loeschung: irreversibel, kaskadiert Feedback weg.
        # Token-Verifikation via DELETE WHERE action_token = ? — kein extra Lookup noetig.
        ok = mgr.delete_by_token(token)
        session.clear()
        if not ok:
            return _status_page(
                "error", i18n.t("status.delete_fail_title"),
                i18n.t("status.delete_fail_msg"),
                http_code=500,
            )
        return _status_page(
            "ok", i18n.t("status.account_deleted_title"),
            i18n.t("status.account_deleted_msg"),
            submessage=i18n.t("status.account_deleted_sub"),
        )

    return _status_page(
        "error", i18n.t("status.unknown_action_title"),
        i18n.t("status.unknown_action_msg"),
        http_code=400,
    )


# ---------------------------------------------------------------------------
# Magic-Link Login (passwordless)
# ---------------------------------------------------------------------------
@app.route("/login", methods=["GET"])
def login_page():
    return render_template(
        "login.html",
        flash_ok=request.args.get("ok", ""),
        flash_error=request.args.get("err", ""),
    )


# --- Login-Rate-Limit ---------------------------------------------------------
# In-Memory-Tracker pro IP. Schuetzt vor Auto-Account-Spam und E-Mail-Bombing.
# Limits konservativ: 5/Min und 20/Stunde pro Client-IP. Reset rolling per Window.
_LOGIN_RATE_LIMIT_PER_MINUTE = 5
_LOGIN_RATE_LIMIT_PER_HOUR   = 20
_login_attempts: dict[str, list[float]] = {}
_login_attempts_lock = threading.Lock()


def _client_ip() -> str:
    """Client-IP. Vertraut X-Forwarded-For nur wenn unter Reverse-Proxy laeuft.
    Sonst remote_addr."""
    fwd = request.headers.get("X-Forwarded-For", "").split(",")[0].strip()
    return fwd or (request.remote_addr or "unknown")


def _check_login_rate_limit() -> Optional[str]:
    """Liefert Fehler-Message wenn Limit ueberschritten, sonst None.
    Cleanup nebenbei: alte Eintraege > 1h werden entfernt."""
    import time
    ip = _client_ip()
    now = time.time()
    with _login_attempts_lock:
        attempts = _login_attempts.setdefault(ip, [])
        # Cleanup: nur Eintraege der letzten Stunde behalten
        cutoff = now - 3600
        attempts[:] = [t for t in attempts if t > cutoff]

        per_minute = sum(1 for t in attempts if t > now - 60)
        per_hour = len(attempts)

        if per_minute >= _LOGIN_RATE_LIMIT_PER_MINUTE:
            return "Zu viele Login-Versuche. Bitte 1 Minute warten."
        if per_hour >= _LOGIN_RATE_LIMIT_PER_HOUR:
            return "Zu viele Login-Versuche in der letzten Stunde. Bitte spaeter erneut."

        attempts.append(now)
    return None


@app.route("/login", methods=["POST"])
def login_request():
    """E-Mail nehmen, One-Time-Token erzeugen, Magic-Link verschicken.
    Antwortet mit JSON bei Accept: application/json (fuer Modal/AJAX), sonst Redirect."""
    wants_json = "application/json" in (request.headers.get("Accept") or "")

    # Rate-Limit zuerst — schuetzt vor Auto-Account-Erstellung-Missbrauch
    rate_err = _check_login_rate_limit()
    if rate_err:
        if wants_json:
            return jsonify({"ok": False, "error": rate_err, "rate_limited": True}), 429
        return redirect(f"/login?err={rate_err.replace(' ', '+')}")

    email = (request.form.get("email") or "").strip().lower()
    if not email:
        if wants_json:
            return jsonify({"ok": False, "error": i18n.t("flash.login_need_email")}), 400
        return redirect(f"/login?err={_fm('flash.login_need_email')}")

    mgr = _get_subscriber_manager()
    if mgr is None:
        if wants_json:
            return jsonify({"ok": False, "error": i18n.t("flash.service_unavailable")}), 503
        return redirect(f"/login?err={_fm('flash.service_unavailable')}")

    result = mgr.create_login_token(email, ttl_minutes=30)
    # Bewusst KEIN Hinweis ob E-Mail registriert ist (Privacy / Enumeration-Schutz)
    if result is not None:
        try:
            from email_service import send_login_email
            send_login_email(email, result["login_token"])
        except Exception as e:
            logger.error("send_login_email failed: %s", e)

    msg = i18n.t("login.fallback_ok")
    if wants_json:
        return jsonify({"ok": True, "message": msg})
    return redirect(f"/login?ok={_fm('login.fallback_ok')}")


@app.route("/login/<token>", methods=["GET"])
def login_landing(token):
    """Landing-Page nach Klick auf Magic-Link aus Mail.

    Read-only: Token wird NICHT verbraucht. Grund: Mail-Prefetcher
    (Microsoft Defender / Safe Links bei Outlook/Hotmail, Mimecast,
    Proofpoint, Google) machen einen Scan-GET auf jeden Link bevor der
    User klickt. Wuerde der GET den Token verbrauchen, wuerde der
    eigentliche User-Klick mit "Link abgelaufen" scheitern.

    Stattdessen rendert dieser Handler eine kleine Bestaetigungsseite
    mit einem POST-Form-Button. Bots fuehren keine POSTs aus — nur der
    echte User-Klick verbraucht den Token in login_consume()."""
    mgr = _get_subscriber_manager()
    if mgr is None:
        return _status_page("error", i18n.t("status.service_unavail_title"),
                            i18n.t("status.try_later"), http_code=503)
    if not mgr.peek_login_token(token):
        return _status_page(
            "error", i18n.t("status.login_link_invalid_title"),
            i18n.t("status.login_link_invalid_msg"),
            submessage=i18n.t("status.request_new_link_sub"),
            http_code=400,
        )
    return render_template("login_confirm.html", token=token)


@app.route("/login/<token>", methods=["POST"])
def login_consume(token):
    mgr = _get_subscriber_manager()
    if mgr is None:
        return _status_page("error", i18n.t("status.service_unavail_title"),
                            i18n.t("status.try_later"), http_code=503)
    res = mgr.consume_login_token(token)
    if res is None:
        logger.warning("login_consume: token NOT consumed (already used or expired) "
                       "from host=%s ua=%r",
                       request.host, request.headers.get("User-Agent", "")[:80])
        return _status_page(
            "error", i18n.t("status.login_link_invalid_title"),
            i18n.t("status.login_link_invalid_msg"),
            submessage=i18n.t("status.request_new_link_sub"),
            http_code=400,
        )
    session.permanent = True
    session["sub_id"] = res["id"]
    session["email"] = res["email"]
    logger.info("login_consume: OK sub_id=%s email=%s host=%s",
                res["id"], res["email"], request.host)
    # Nach erfolgreichem Magic-Link-Login direkt auf die Konto-Seite leiten
    return redirect("/account")


@app.route("/logout", methods=["GET", "POST"])
def logout():
    session.clear()
    return redirect("/")


@app.route("/unsubscribe/<token>", methods=["GET"])
def subscribe_unsubscribe(token):
    mgr = _get_subscriber_manager()
    if mgr is None:
        return _status_page(
            "error", i18n.t("status.unsub_fail_title"),
            i18n.t("status.service_unavail_retry"),
            http_code=503,
        )

    ok = mgr.unsubscribe(token)
    if not ok:
        return _status_page(
            "error", i18n.t("status.link_invalid_title"),
            i18n.t("status.unsub_link_invalid_msg"),
            http_code=404,
        )

    return _status_page(
        "ok", i18n.t("status.unsubscribed_title"),
        i18n.t("status.unsubscribed_msg"),
        submessage=i18n.t("status.unsubscribed_sub"),
    )


# ============================================================================
# ADMIN-DASHBOARD (passwortlos: Admin = Session-E-Mail == config.ADMIN_EMAIL)
# ============================================================================

def _require_admin(f):
    """Admin-Gate ohne Passwort: Zugriff nur fuer die Admin-E-Mail-Session.

    Nicht eingeloggt -> /login. Eingeloggt, aber falsche E-Mail -> 403.
    API-Requests bekommen immer JSON 403.
    """
    @wraps(f)
    def wrapper(*args, **kwargs):
        if _is_admin():
            return f(*args, **kwargs)
        if _is_api_request():
            return jsonify({"error": "Admin-Zugriff erforderlich"}), 403
        if not session.get("sub_id"):
            return redirect("/login?err=Bitte+als+Admin+einloggen")
        return ("Kein Admin-Zugriff.", 403,
                {"Content-Type": "text/plain; charset=utf-8"})
    return wrapper


@app.route("/admin/enable-debug", methods=["POST"])
@_require_admin
def admin_enable_debug():
    session.permanent = True
    session["admin_debug"] = True
    return jsonify({"ok": True, "admin_debug": True})


@app.route("/admin/disable-debug", methods=["POST"])
@_require_admin
def admin_disable_debug():
    session.pop("admin_debug", None)
    return jsonify({"ok": True, "admin_debug": False})


@app.route("/admin", methods=["GET"])
@_require_admin
def admin_index():
    return redirect("/admin/subscribers")


@app.route("/admin/wetterlage_audit", methods=["GET"])
@app.route("/admin/wetterlage_audit/<date>", methods=["GET"])
@_require_admin
def admin_wetterlage_audit(date: str = None):
    """Zeigt das Audit-JSON eines Wetterlage-Casts.

    Ohne Datum: Liste aller verfuegbaren Audit-Files (latest first).
    Mit Datum: vollstaendiges Strukturfeld inkl. Roh-Snapshots, Decisions,
    LLM-Prompt-Input, LLM-Output, Post-Filter-Log.
    """
    import os, json as _json
    audit_dir = Path(config.SYNOPTIC_AUDIT_DIR)
    if not audit_dir.exists():
        return jsonify({"error": "No audit dir", "path": str(audit_dir)}), 404

    if date is None:
        # Liste verfuegbarer Dates
        files = sorted([f.stem for f in audit_dir.glob("*.json")], reverse=True)
        # Sentinel: latest cache (synoptic_context.json) auch zeigen
        cache_exists = Path(config.SYNOPTIC_CACHE_PATH).exists()
        return jsonify({
            "audit_dir": str(audit_dir),
            "available_dates": files,
            "current_cache_present": cache_exists,
            "view_url_pattern": "/admin/wetterlage_audit/<YYYY-MM-DD>",
        })

    path = audit_dir / f"{date}.json"
    if not path.exists():
        return jsonify({"error": f"No audit file for {date}",
                        "path": str(path)}), 404
    try:
        with open(path, "r", encoding="utf-8") as fp:
            data = _json.load(fp)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/admin/subscribers", methods=["GET"])
@_require_admin
def admin_subscribers():
    mgr = _get_subscriber_manager()
    if mgr is None:
        return _status_page("error", "Admin nicht verfuegbar",
                            "SubscriberManager konnte nicht initialisiert werden.",
                            http_code=503)
    return render_template(
        "admin/subscribers.html",
        stats_counts=mgr.count_by_status(),
        stats_feedback=mgr.count_feedback_overall(days=30),
        subscribers=mgr.list_recent(limit=50),
        flash_ok=request.args.get("ok", ""),
        flash_error=request.args.get("err", ""),
    )


@app.route("/admin/subscribers/send-test", methods=["POST"])
@_require_admin
def admin_send_test():
    from email_service import send_briefing_email
    mgr = _get_subscriber_manager()
    if mgr is None:
        return redirect("/admin/subscribers?err=Service+nicht+verfuegbar")

    email = (request.form.get("email") or "").strip()
    sub = mgr.get_by_email(email) if email else None
    if not sub:
        return redirect(f"/admin/subscribers?err=Subscriber+{email}+nicht+gefunden")

    if engine is None:
        return redirect("/admin/subscribers?err=Engine+noch+nicht+geladen")
    try:
        briefing_data = engine.build_briefing_data()
        send_briefing_email(sub, briefing_data, async_send=True)
    except Exception as e:
        logger.exception("admin_send_test: %s", e)
        return redirect(f"/admin/subscribers?err=Versand-Fehler:+{e}")

    return redirect(f"/admin/subscribers?ok=Test-Briefing+an+{email}+versendet")


@app.route("/admin/subscribers/trigger-all", methods=["POST"])
@_require_admin
def admin_trigger_all():
    if engine is None:
        return redirect("/admin/subscribers?err=Engine+noch+nicht+geladen")
    from scheduler import _send_briefings_once
    try:
        stats = _send_briefings_once(engine)
    except Exception as e:
        logger.exception("admin_trigger_all: %s", e)
        return redirect(f"/admin/subscribers?err=Fehler:+{e}")
    return redirect(
        f"/admin/subscribers?ok=Versand+abgeschlossen:+"
        f"sent={stats['sent']}+failed={stats['failed']}"
    )


@app.route("/admin/subscribers/<int:sub_id>/block", methods=["POST"])
@_require_admin
def admin_block(sub_id):
    mgr = _get_subscriber_manager()
    if mgr is None:
        return redirect("/admin/subscribers?err=Service+nicht+verfuegbar")
    ok = mgr.block(sub_id)
    if not ok:
        return redirect(f"/admin/subscribers?err=Sperre+fehlgeschlagen+fuer+%23{sub_id}")
    return redirect(f"/admin/subscribers?ok=Subscriber+%23{sub_id}+gesperrt")


@app.route("/admin/subscribers/<int:sub_id>/delete", methods=["POST"])
@_require_admin
def admin_delete(sub_id):
    """Hard-Delete eines Subscribers (irreversibel). Loescht auch Feedback-Rows
    via FK ON DELETE CASCADE. Browser-confirm() im Template ist die einzige
    Sicherheitsbarriere — bewusst keine Soft-Delete-Logik."""
    mgr = _get_subscriber_manager()
    if mgr is None:
        return redirect("/admin/subscribers?err=Service+nicht+verfuegbar")
    sub = mgr.get_by_id(sub_id)
    if sub is None:
        return redirect(f"/admin/subscribers?err=Subscriber+%23{sub_id}+nicht+gefunden")
    email = sub.get("email", "")
    ok = mgr.delete(sub_id)
    if not ok:
        return redirect(f"/admin/subscribers?err=Loeschen+fehlgeschlagen+fuer+%23{sub_id}")
    return redirect(f"/admin/subscribers?ok=Subscriber+%23{sub_id}+({email})+geloescht")


@app.route("/admin/feedback", methods=["GET"])
@_require_admin
def admin_feedback():
    """Übersicht aller drei Feedback-Quellen."""
    sub_mgr = _get_subscriber_manager()
    fb_mgr = _get_feedback_manager()

    only_comments = request.args.get("comments_only") == "1"
    only_dislikes = request.args.get("dislikes_only") == "1"

    return render_template(
        "admin/feedback.html",
        # Briefing-Verdict
        briefing_stats=sub_mgr.count_feedback_overall(days=30) if sub_mgr else None,
        briefing_list=sub_mgr.list_briefing_feedback(limit=100) if sub_mgr else [],
        # Produkt-Freitext
        product_list=sub_mgr.list_product_feedback(limit=100) if sub_mgr else [],
        # Spot/Region
        spot_region_stats=fb_mgr.admin_stats(days=30) if fb_mgr else None,
        spot_region_list=fb_mgr.admin_list(
            limit=200, only_with_comment=only_comments, only_dislike=only_dislikes,
        ) if fb_mgr else [],
        only_comments=only_comments,
        only_dislikes=only_dislikes,
        flash_ok=request.args.get("ok", ""),
        flash_error=request.args.get("err", ""),
    )


@app.route("/admin/feedback/spot-region/<int:fid>/delete", methods=["POST"])
@_require_admin
def admin_feedback_sr_delete(fid):
    mgr = _get_feedback_manager()
    if mgr is None:
        return redirect("/admin/feedback?err=Service+nicht+verfuegbar")
    ok = mgr.admin_delete(fid)
    qs = "ok=Geloescht" if ok else f"err=Loeschen+fehlgeschlagen+%23{fid}"
    return redirect(f"/admin/feedback?{qs}")


@app.route("/admin/feedback/briefing/<int:fid>/delete", methods=["POST"])
@_require_admin
def admin_feedback_briefing_delete(fid):
    mgr = _get_subscriber_manager()
    if mgr is None:
        return redirect("/admin/feedback?err=Service+nicht+verfuegbar")
    ok = mgr.delete_briefing_feedback(fid)
    qs = "ok=Geloescht" if ok else f"err=Loeschen+fehlgeschlagen+%23{fid}"
    return redirect(f"/admin/feedback?{qs}")


@app.route("/admin/feedback/product/<int:fid>/delete", methods=["POST"])
@_require_admin
def admin_feedback_product_delete(fid):
    mgr = _get_subscriber_manager()
    if mgr is None:
        return redirect("/admin/feedback?err=Service+nicht+verfuegbar")
    ok = mgr.delete_product_feedback(fid)
    qs = "ok=Geloescht" if ok else f"err=Loeschen+fehlgeschlagen+%23{fid}"
    return redirect(f"/admin/feedback?{qs}")


@app.route("/admin/config", methods=["GET"])
@_require_admin
def admin_config():
    import config_overrides
    return render_template(
        "admin/config.html",
        schema=config_overrides.SCHEMA,
        values=config_overrides.current_values(),
        defaults=config_overrides.default_values(),
        overlay=config_overrides.get_overrides(),
        flash_ok=request.args.get("ok", ""),
        flash_error=request.args.get("err", ""),
    )


@app.route("/admin/config/save", methods=["POST"])
@_require_admin
def admin_config_save():
    import config_overrides

    # Alle Form-Keys einsammeln. Checkboxen, die NICHT gecheckt sind, fehlen
    # komplett im Form → wir setzen sie explizit auf False fuer bool-Felder.
    schema_flat: dict = {}
    for _section, groups in config_overrides.SCHEMA.items():
        for _group, fields in groups.items():
            for f in fields:
                schema_flat[f["key"]] = f

    form_values: dict = {}
    for key, field in schema_flat.items():
        if field["type"] == "bool":
            form_values[key] = key in request.form  # check vorhanden = True
        elif field["type"] == "weekdays":
            # mehrere gleichnamige Checkboxen → getlist
            form_values[key] = request.form.getlist(key)
        else:
            if key in request.form:
                form_values[key] = request.form.get(key, "")

    try:
        changed = config_overrides.save_overrides(form_values)
    except Exception as e:
        logger.exception("admin_config_save: %s", e)
        return redirect(f"/admin/config?err=Fehler+beim+Speichern:+{e}")

    if not changed:
        return redirect("/admin/config?ok=Keine+Aenderungen")

    # Engine LLM-Clients neu laden, damit Modellwechsel ohne Neustart greifen.
    # Ohne dieses Reload behaelt die laufende Engine-Instanz die im __init__
    # gecachten chat_client/analysis_client (inkl. Provider+Modell) → ein
    # Wechsel auf z.B. claude-haiku-4-5 wuerde erst nach Neustart wirken.
    if engine is not None and ("CHAT_MODEL" in changed or "ANALYSIS_MODEL" in changed or "SYNOPTIC_MODEL" in changed):
        try:
            engine.reload_llm_clients()
        except Exception as e:
            logger.warning("admin_config_save: reload_llm_clients fehlgeschlagen: %s", e)

    # Sprachwechsel: In-Memory-Analysen aus dem jetzt aktiven sprachspezifischen
    # Cache neu laden (DE/EN getrennt). UI/Chat schalten sofort via t()/lang;
    # die Analyse-Texte kommen in der neuen Sprache beim naechsten Neu-Berechnen.
    if engine is not None and "LANG" in changed:
        try:
            engine.reload_analyses_for_lang()
        except Exception as e:
            logger.warning("admin_config_save: reload_analyses_for_lang fehlgeschlagen: %s", e)

    # Scheduler-Thread aufwecken, damit DAILY_RUN_* sofort greifen statt erst
    # beim naechsten planmaessigen Aufwachen.
    try:
        from scheduler import notify_config_changed
        notify_config_changed()
    except Exception as e:
        logger.warning("admin_config_save: notify_config_changed fehlgeschlagen: %s", e)

    msg = f"Gespeichert+und+sofort+aktiv+%28{len(changed)}+Werte%29"
    return redirect(f"/admin/config?ok={msg}")


# ============================================================================
# ADMIN · REFERENZPUNKTE (Region-Refpoints + Spot-Koordinaten)
# ============================================================================

# Plausibilitaets-Grenzen fuer CH-Koordinaten (generoes — Anker duerfen knapp
# ausserhalb des Polygons liegen, siehe docs/REFPOINT_KONZEPT.md).
_REFPOINT_LAT_MIN, _REFPOINT_LAT_MAX = 45.0, 48.5
_REFPOINT_LON_MIN, _REFPOINT_LON_MAX = 5.0, 11.5


def _validate_latlon(lat, lon):
    """Wirft ValueError mit klarer Message wenn lat/lon nicht numerisch oder ausserhalb CH-Bounds."""
    try:
        lat_f = float(lat); lon_f = float(lon)
    except (TypeError, ValueError):
        raise ValueError(f"lat/lon nicht numerisch: lat={lat!r}, lon={lon!r}")
    if not (_REFPOINT_LAT_MIN <= lat_f <= _REFPOINT_LAT_MAX):
        raise ValueError(f"lat={lat_f} ausserhalb [{_REFPOINT_LAT_MIN}, {_REFPOINT_LAT_MAX}]")
    if not (_REFPOINT_LON_MIN <= lon_f <= _REFPOINT_LON_MAX):
        raise ValueError(f"lon={lon_f} ausserhalb [{_REFPOINT_LON_MIN}, {_REFPOINT_LON_MAX}]")
    return lat_f, lon_f


@app.route("/admin/reference-points", methods=["GET"])
@_require_admin
def admin_reference_points():
    return render_template(
        "admin/reference_points.html",
        show_osm_peaks=config.SHOW_OSM_PEAKS,
    )


@app.route("/api/admin/refpoints/regions", methods=["GET"])
@_require_admin
def admin_api_refpoints_regions():
    """JSON: alle Regionen mit id, name, polygon-GeoJSON, reference_points."""
    import source_area
    source_area.invalidate_cache()  # immer frische Werte fuer Editor liefern
    from shapely.geometry import mapping
    regions = source_area.get_all_regions()
    out = []
    for r in regions:
        try:
            geom = mapping(r["polygon"])
        except Exception:
            geom = None
        out.append({
            "id": r["id"],
            "name": r.get("region") or r["id"],
            "terrain_type": r.get("terrain_type"),
            "elevation_ref": r.get("elevation_ref"),
            "polygon": geom,
            "reference_points": r.get("reference_points", []),
        })
    out.sort(key=lambda x: (x.get("name") or "").lower())
    return jsonify({"regions": out})


@app.route("/api/admin/refpoints/spots", methods=["GET"])
@_require_admin
def admin_api_refpoints_spots():
    """JSON: alle Spots mit composite ID + lat/lon/elevation."""
    from spots import load_spots, make_spot_id
    spots = load_spots()
    out = []
    for s in spots:
        sid = make_spot_id(s["region"], s["fluggebiet"], s["name"])
        out.append({
            "id": sid,
            "region": s["region"],
            "fluggebiet": s["fluggebiet"],
            "site_name": s["name"],
            "lat": s["latitude"],
            "lon": s["longitude"],
            "elevation_m": s["elevation_m"],
            "windrichtung": s.get("windrichtung"),
            "analyse_region": s.get("analyse_region"),
        })
    out.sort(key=lambda x: (x["region"].lower(), x["fluggebiet"].lower(), x["site_name"].lower()))
    return jsonify({"spots": out})


@app.route("/api/admin/refpoints/region/<region_id>", methods=["POST"])
@_require_admin
def admin_api_refpoints_save_region(region_id: str):
    """Body: {points: [[lat,lon], ...×7]}. Persistiert in GeoJSON + invalidiert Cache."""
    import source_area
    data = request.get_json(silent=True) or {}
    points = data.get("points")
    if not isinstance(points, list) or len(points) != 7:
        return jsonify({"ok": False, "error": "Erwarte 7 Punkte als 'points'-Liste"}), 400

    validated = []
    for i, p in enumerate(points):
        if not isinstance(p, (list, tuple)) or len(p) != 2:
            return jsonify({"ok": False, "error": f"Punkt {i} muss [lat, lon] sein"}), 400
        try:
            lat, lon = _validate_latlon(p[0], p[1])
        except ValueError as e:
            return jsonify({"ok": False, "error": f"Punkt {i}: {e}"}), 400
        validated.append([round(lat, 4), round(lon, 4)])

    try:
        source_area.update_reference_points(region_id, validated)
    except (ValueError, FileNotFoundError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("admin refpoints region save: %s", e)
        return jsonify({"ok": False, "error": f"Server-Fehler: {e}"}), 500

    return jsonify({"ok": True, "region_id": region_id, "points": validated})


@app.route("/api/admin/refpoints/spot", methods=["POST"])
@_require_admin
def admin_api_refpoints_save_spot():
    """Body: {id, lat, lon}. Persistiert in CSV + reloadet Spots-Cache."""
    from spots import update_spot_coords
    data = request.get_json(silent=True) or {}
    spot_id = (data.get("id") or "").strip()
    if not spot_id:
        return jsonify({"ok": False, "error": "spot id fehlt"}), 400
    try:
        lat, lon = _validate_latlon(data.get("lat"), data.get("lon"))
    except ValueError as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    try:
        updated_row = update_spot_coords(spot_id, lat, lon)
    except (ValueError, FileNotFoundError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    except Exception as e:
        logger.exception("admin refpoints spot save: %s", e)
        return jsonify({"ok": False, "error": f"Server-Fehler: {e}"}), 500

    # Engine-Spotliste neu laden, damit naechster Wetter-Lauf neue Koords nutzt.
    if engine is not None:
        try:
            engine.reload_spots()
        except Exception as e:
            logger.warning("admin refpoints spot save: reload_spots fehlgeschlagen: %s", e)

    return jsonify({
        "ok": True,
        "id": spot_id,
        "lat": round(lat, 4),
        "lon": round(lon, 4),
        "site_name": updated_row.get("site_name"),
    })


# ============================================================================
# ADMIN · TESTING (Mock-Daten, Test-Analysen, Goldstandard)
# ============================================================================

@app.route("/admin/testing", methods=["GET"])
@_require_admin
def admin_testing():
    from engine import test_mode
    return render_template(
        "admin/testing.html",
        status=test_mode.status_bundle(),
        forecast_days_max=config.FORECAST_DAYS,
        total_spots=len(engine.spots) if engine.spots else 0,
        flash_ok=request.args.get("ok", ""),
        flash_error=request.args.get("err", ""),
    )


@app.route("/admin/testing/freeze-weather", methods=["POST"])
@_require_admin
def admin_testing_freeze_weather():
    from engine import test_mode
    spot_set = (request.form.get("spot_set") or "test").strip().lower()
    if spot_set not in ("test", "complete"):
        return redirect("/admin/testing?err=Ungueltiges+spot_set")
    try:
        meta = test_mode.freeze_current_weather(spot_set=spot_set)
    except FileNotFoundError as e:
        return redirect(f"/admin/testing?err={str(e).replace(' ', '+')}")
    except Exception as e:
        logger.exception("freeze_weather: %s", e)
        return redirect(f"/admin/testing?err=Einfrieren+fehlgeschlagen:+{e}")
    set_lbl = "Komplett" if meta.get("spot_set") == "complete" else "Test-Set"
    msg = f"Snapshot+gesetzt+%28{set_lbl}:+{meta.get('spot_count', 0)}+Spots,+{meta.get('region_count', 0)}+Regionen%29"
    return redirect(f"/admin/testing?ok={msg}")


@app.route("/admin/testing/discard-frozen", methods=["POST"])
@_require_admin
def admin_testing_discard_frozen():
    from engine import test_mode
    deleted = test_mode.discard_frozen_weather()
    if deleted:
        return redirect("/admin/testing?ok=Snapshot+geloescht")
    return redirect("/admin/testing?err=Kein+Snapshot+vorhanden")


@app.route("/admin/testing/toggle-view", methods=["POST"])
@_require_admin
def admin_testing_toggle_view():
    from engine import test_mode
    active = (request.form.get("active") or "").strip() == "1"
    if active and not test_mode.TEST_RUN_SPOT_ANALYSES_PATH.exists() \
       and not test_mode.TEST_RUN_REGION_ANALYSES_PATH.exists():
        return redirect("/admin/testing?err=Kein+Test-Lauf+vorhanden+-+Toggle+nicht+moeglich")
    test_mode.set_view_active(active)
    msg = "Test-Ansicht+aktiviert" if active else "Test-Ansicht+deaktiviert"
    return redirect(f"/admin/testing?ok={msg}")


@app.route("/admin/testing/refresh-frozen", methods=["POST"])
@_require_admin
def admin_testing_refresh_frozen():
    """Holt frische Wetterdaten von der Live-API und friert sie als neuen Snapshot ein.

    Zwei Schritte in einem Klick: `engine.refresh_weather(force=True)` + Freeze.
    Achtung: API-Weight wird verbraucht. Falls der Refresh fehlschlaegt, bleibt der
    bestehende Snapshot unangetastet.
    """
    from engine import test_mode
    spot_set = (request.form.get("spot_set") or "test").strip().lower()
    if spot_set not in ("test", "complete"):
        return redirect("/admin/testing?err=Ungueltiges+spot_set")
    if engine is None:
        return redirect("/admin/testing?err=Engine+noch+nicht+geladen")
    try:
        engine.refresh_weather(force=True)
    except Exception as e:
        logger.exception("refresh-frozen: Wetter-Refresh fehlgeschlagen")
        return redirect(f"/admin/testing?err=Wetter-Refresh+fehlgeschlagen:+{e}")

    if getattr(engine, "last_refresh_stale", False):
        return redirect("/admin/testing?err=Live-Refresh+lieferte+nur+Stale-Cache+-+Snapshot+nicht+aktualisiert")

    try:
        meta = test_mode.freeze_current_weather(spot_set=spot_set)
    except Exception as e:
        logger.exception("refresh-frozen: Freeze fehlgeschlagen")
        return redirect(f"/admin/testing?err=Freeze+fehlgeschlagen:+{e}")
    set_lbl = "Komplett" if meta.get("spot_set") == "complete" else "Test-Set"
    msg = f"Snapshot+vom+Live+aktualisiert+%28{set_lbl}:+{meta.get('spot_count', 0)}+Spots,+{meta.get('region_count', 0)}+Regionen%29"
    return redirect(f"/admin/testing?ok={msg}")


def _run_test_analysis_in_background(eng, q, *, use_frozen_input: bool, spot_set: str = "test", n_days: int | None = None):
    """Background-Worker fuer den Test-Analysen-Stream. Schreibt Events in `q`."""
    from engine import test_mode
    global _analysis_running, _analysis_completed, _analysis_error, _analysis_result
    try:
        for evt in test_mode.run_test_analyses_stream(
            eng,
            use_frozen_input=use_frozen_input,
            spot_set=spot_set,
            n_days=n_days,
        ):
            q.put(evt)
            if evt.get("event") == "done":
                data = evt.get("data", {})
                rs = data.get("region_stats") or {}
                ss = data.get("spot_stats") or {}
                _analysis_result = {
                    "regions_count": rs.get("regions_count", 0),
                    "spots_count": ss.get("spots_count", 0),
                    "total_calls": data.get("total_calls", 0),
                    "test_run": True,
                }
                _analysis_completed = True
            elif evt.get("event") == "error":
                _analysis_error = (evt.get("data", {}) or {}).get("message", "unbekannter Fehler")
    except Exception as e:
        logger.exception("[TEST-ANALYSIS-BG] Fehler im Test-Analyse-Thread")
        q.put({"event": "error", "data": {"message": str(e)}})
        _analysis_error = str(e)
    finally:
        q.put(None)
        _analysis_running = False
        logger.info("[TEST-ANALYSIS-BG] Test-Analyse-Thread beendet")


@app.route("/admin/testing/run-test-analysis")
@_require_admin
def admin_testing_run_test_analysis():
    """SSE-Endpoint: startet einen Test-Analysen-Lauf im Background.

    Query:
        input=frozen|live (default frozen)
        spot_set=test|complete (default test)
        n_days=1..FORECAST_DAYS (default = FORECAST_DAYS, also alle Tage)
    Schreibt nach `data/test_runs/latest/`. Nutzt denselben Lock wie die
    Live-Analyse, damit nichts parallel laeuft.
    """
    from engine import test_mode

    global _analysis_running, _analysis_completed, _analysis_error, _analysis_result, _analysis_queue

    input_source = (request.args.get("input") or "frozen").strip().lower()
    use_frozen = input_source != "live"

    spot_set = (request.args.get("spot_set") or "test").strip().lower()
    if spot_set not in ("test", "complete"):
        return Response(
            f'event: error\ndata: {{"message": "Ungueltiges spot_set: {spot_set}"}}\n\n',
            mimetype="text/event-stream", headers={"Cache-Control": "no-cache"},
        )

    n_days_raw = (request.args.get("n_days") or "").strip()
    n_days: int | None = None
    if n_days_raw:
        try:
            n_days = int(n_days_raw)
        except ValueError:
            return Response(
                f'event: error\ndata: {{"message": "n_days muss Integer sein, war: {n_days_raw}"}}\n\n',
                mimetype="text/event-stream", headers={"Cache-Control": "no-cache"},
            )
        if n_days < 1 or n_days > config.FORECAST_DAYS:
            return Response(
                f'event: error\ndata: {{"message": "n_days={n_days} ausserhalb 1..{config.FORECAST_DAYS}"}}\n\n',
                mimetype="text/event-stream", headers={"Cache-Control": "no-cache"},
            )

    if spot_set == "complete" and use_frozen:
        return Response(
            'event: error\ndata: {"message": "Komplett-Set + Frozen nicht moeglich — Snapshot enthaelt nur Test-Spots."}\n\n',
            mimetype="text/event-stream", headers={"Cache-Control": "no-cache"},
        )

    with _analysis_lock:
        if _analysis_running:
            return Response(
                "event: error\ndata: {\"message\": \"Eine Analyse laeuft bereits\"}\n\n",
                mimetype="text/event-stream",
                headers={"Cache-Control": "no-cache"},
            )
        _analysis_running = True
        _analysis_completed = False
        _analysis_error = None
        _analysis_result = None
        _analysis_queue = _queue_mod.Queue()

    t = threading.Thread(
        target=_run_test_analysis_in_background,
        args=(engine, _analysis_queue),
        kwargs={
            "use_frozen_input": use_frozen,
            "spot_set": spot_set,
            "n_days": n_days,
        },
        daemon=True,
    )
    t.start()

    def generate():
        yield "retry: 300000\n\n"
        try:
            while True:
                try:
                    evt = _analysis_queue.get(timeout=15)
                except _queue_mod.Empty:
                    if not _analysis_running:
                        break
                    yield "event: heartbeat\ndata: {}\n\n"
                    continue
                if evt is None:
                    break
                event_type = evt.get("event", "message")
                if event_type == "heartbeat":
                    yield "event: heartbeat\ndata: {}\n\n"
                    continue
                data = evt.get("data", {})
                yield f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        except GeneratorExit:
            logger.warning("[TEST-SSE] Client disconnected — Test-Analyse laeuft im Background weiter")
        except Exception as e:
            logger.exception("[TEST-SSE] stream Fehler")
            yield f"event: error\ndata: {json.dumps({'message': str(e)}, ensure_ascii=False)}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def _run_cost_testing_subprocess(script_path, extra_args, timeout=600):
    """Faehrt ein Skript aus cost_testing/ als Subprocess.

    Returns: (returncode, stdout, stderr, duration_s).
    """
    import subprocess
    import time
    cmd = [sys.executable, str(script_path)] + list(extra_args)
    started = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(config.PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        duration = time.monotonic() - started
        return proc.returncode, proc.stdout, proc.stderr, duration
    except subprocess.TimeoutExpired as e:
        duration = time.monotonic() - started
        return -1, e.stdout or "", f"TIMEOUT nach {timeout}s", duration


@app.route("/admin/testing/freeze-golden", methods=["POST"])
@_require_admin
def admin_testing_freeze_golden():
    """Wraps cost_testing/freeze_golden.py als Subprocess.

    Form-Felder: limit (int, default 20), force (checkbox).
    """
    from engine import test_mode
    try:
        limit = int(request.form.get("limit") or 20)
    except ValueError:
        limit = 20
    limit = max(1, min(limit, 200))
    force = (request.form.get("force") or "").strip() == "1"

    args = ["--limit", str(limit)]
    if force:
        args.append("--force")

    logger.info("[FREEZE-GOLDEN] START limit=%d, force=%s", limit, force)
    rc, stdout, stderr, duration = _run_cost_testing_subprocess(
        test_mode.FREEZE_GOLDEN_SCRIPT, args, timeout=180,
    )
    logger.info("[FREEZE-GOLDEN] DONE rc=%d after %.1fs", rc, duration)
    if rc != 0:
        snippet = (stderr or stdout or "")[-300:].replace("\n", " | ").replace("&", "+")
        return redirect(f"/admin/testing?err=Freeze-Golden+rc%3D{rc}+({duration:.1f}s):+{snippet}")

    summary = test_mode.golden_summary()
    msg = f"Goldstandard+aktualisiert+%28{summary.get('count', 0)}+Cases,+{duration:.1f}s%29"
    return redirect(f"/admin/testing?ok={msg}")


@app.route("/admin/testing/run-regression", methods=["POST"])
@_require_admin
def admin_testing_run_regression():
    """Wraps cost_testing/score_regression.py als Subprocess.

    Form-Felder:
      - mode: 'no_llm' (default) = nur Cache vergleichen, schnell.
              'with_llm' = Pipeline neu fahren, langsam (mehrere Min).
      - max_cases: int, optional. 0 = alle.
    """
    from engine import test_mode
    import datetime as _dt

    mode = (request.form.get("mode") or "no_llm").strip()
    try:
        max_cases = int(request.form.get("max_cases") or 0)
    except ValueError:
        max_cases = 0
    max_cases = max(0, max_cases)

    test_mode.REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = _dt.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    report_name = f"reg_{mode}_{ts}.md"
    report_path = test_mode.REPORTS_DIR / report_name
    queue_path = test_mode.REPORTS_DIR / f"reg_{mode}_{ts}_queue.json"

    args = ["--report", str(report_path), "--queue-output", str(queue_path)]
    if mode == "no_llm":
        args.append("--no-llm")
    if max_cases > 0:
        args.extend(["--max-cases", str(max_cases)])

    timeout = 180 if mode == "no_llm" else 1500
    case_hint = f"{max_cases} Cases" if max_cases > 0 else "alle Cases"
    logger.info(
        "[REGRESSION] START mode=%s, %s, model=%s, timeout=%ds, report=%s",
        mode, case_hint, config.ANALYSIS_MODEL, timeout, report_name,
    )
    rc, stdout, stderr, duration = _run_cost_testing_subprocess(
        test_mode.SCORE_REGRESSION_SCRIPT, args, timeout=timeout,
    )
    # rc != 0 bei score_regression.py heisst FAIL — Report wurde trotzdem geschrieben.
    status_word = "PASS" if rc == 0 else "FAIL"
    logger.info(
        "[REGRESSION] DONE %s rc=%d after %.1fs, report=%s",
        status_word, rc, duration, report_name,
    )
    if rc != 0 and stderr:
        logger.warning("[REGRESSION] stderr tail: %s", stderr[-500:])
    qs = f"ok=Regression+{status_word}+%28{duration:.1f}s%29+%E2%86%92+{report_name}"
    if rc != 0 and queue_path.exists():
        qs += "+-+Review-Queue+verfuegbar"
    return redirect(f"/admin/testing?{qs}")


@app.route("/admin/testing/review/start", methods=["POST"])
@_require_admin
def admin_testing_review_start():
    """Startet eine Review-Session aus der juengsten queue-JSON-Datei.

    Form: sample_size (int, default 10).
    """
    from engine import test_mode
    try:
        sample_size = int(request.form.get("sample_size") or test_mode.REVIEW_DEFAULT_SAMPLE_SIZE)
    except ValueError:
        sample_size = test_mode.REVIEW_DEFAULT_SAMPLE_SIZE
    sample_size = max(1, min(sample_size, 50))

    queue_json = test_mode.latest_queue_json()
    if queue_json is None:
        return redirect("/admin/testing?err=Keine+Queue-Datei+gefunden+-+erst+Regression+laufen+lassen")

    try:
        result = test_mode.start_review_session(queue_json, sample_size=sample_size)
    except (FileNotFoundError, ValueError) as e:
        return redirect(f"/admin/testing?err=Review-Start+fehlgeschlagen:+{e}")

    return redirect(f"/admin/testing/review/{result['session_id']}")


@app.route("/admin/testing/review/<session_id>", methods=["GET"])
@_require_admin
def admin_testing_review_show(session_id):
    """Rendert die Side-by-Side-Review-UI fuer eine Session."""
    from engine import test_mode
    session = test_mode.load_review_session(session_id)
    if session is None:
        return ("Review-Session nicht gefunden", 404, {"Content-Type": "text/plain; charset=utf-8"})

    # Vorabaggregation fuer Anzeige (kein finalize, nur Counts)
    cases = session.get("cases") or []
    counts = {
        "better": sum(1 for c in cases if c.get("verdict") == test_mode.VERDICT_BETTER),
        "same":   sum(1 for c in cases if c.get("verdict") == test_mode.VERDICT_SAME),
        "worse":  sum(1 for c in cases if c.get("verdict") == test_mode.VERDICT_WORSE),
        "open":   sum(1 for c in cases if c.get("verdict") is None),
    }
    return render_template(
        "admin/testing_review.html",
        session=session,
        counts=counts,
        flash_ok=request.args.get("ok", ""),
        flash_error=request.args.get("err", ""),
    )


@app.route("/admin/testing/review/<session_id>/<int:case_idx>/verdict", methods=["POST"])
@_require_admin
def admin_testing_review_verdict(session_id, case_idx):
    """Speichert ein Verdict (better/same/worse) fuer einen einzelnen Case."""
    from engine import test_mode
    verdict = (request.form.get("verdict") or "").strip()
    comment = request.form.get("comment") or ""
    try:
        test_mode.save_verdict(session_id, case_idx, verdict, comment)
    except ValueError as e:
        return redirect(f"/admin/testing/review/{session_id}?err={e}")
    return redirect(f"/admin/testing/review/{session_id}?ok=Case+%23{case_idx}+gespeichert#case-{case_idx + 1}")


@app.route("/admin/testing/review/<session_id>/finalize", methods=["POST"])
@_require_admin
def admin_testing_review_finalize(session_id):
    """Aggregiert alle Verdicts → PASS/FAIL/AMBIGUOUS."""
    from engine import test_mode
    try:
        result = test_mode.finalize_session(session_id)
    except ValueError as e:
        return redirect(f"/admin/testing/review/{session_id}?err={e}")
    if result["verdict"] == "INCOMPLETE":
        return redirect(f"/admin/testing/review/{session_id}?err=Noch+{result['n_unreviewed']}+Cases+offen")
    msg = f"Session+{result['verdict']}+%28{result['n_better']}/{result['n_same']}/{result['n_worse']}%29"
    return redirect(f"/admin/testing/review/{session_id}?ok={msg}")


@app.route("/admin/testing/review/<session_id>/promote", methods=["POST"])
@_require_admin
def admin_testing_review_promote(session_id):
    """Aktualisiert die Goldstandard-Files mit den `better`-Outputs der Session."""
    from engine import test_mode
    try:
        result = test_mode.promote_to_gold(session_id)
    except ValueError as e:
        return redirect(f"/admin/testing/review/{session_id}?err={e}")
    msg = f"{result['n_promoted']}+Cases+in+Goldstandard+uebernommen"
    if result.get("errors"):
        msg += f"+%28{len(result['errors'])}+Fehler%29"
    return redirect(f"/admin/testing/review/{session_id}?ok={msg}")


@app.route("/admin/testing/reports/<path:name>", methods=["GET"])
@_require_admin
def admin_testing_report(name):
    """Rendert einen Regression-Report als preformatted Text."""
    from engine import test_mode
    text = test_mode.read_report(name)
    if text is None:
        return ("Report nicht gefunden", 404, {"Content-Type": "text/plain; charset=utf-8"})
    return render_template(
        "admin/testing_report.html",
        report_name=name,
        report_text=text,
    )


@app.route("/admin/testing/review/<session_id>/<int:case_idx>/meteo.json", methods=["GET"])
@_require_admin
def admin_testing_review_meteogram(session_id, case_idx):
    """Liefert Meteogramm-Daten fuer einen Review-Case.

    Quelle ist der `weather_snapshot` aus dem Goldfile (per
    cost_testing/freeze_golden.py mitgespeichert) und vom Score-Regression-
    Lauf in die Session uebernommen. Konvertiert die Roh-Daten via
    format_data_for_charts / format_altitude_wind_for_charts ins gleiche
    Format wie /api/weather + /api/altitude-wind, damit das vorhandene
    Meteogram-Modul (static/js/meteogram.js) sie rendern kann.

    Falls kein Snapshot vorhanden ist (alte Goldfiles vor dem Refactor),
    wird 410 + Hinweis zurueckgegeben.
    """
    from engine import test_mode
    session = test_mode.load_review_session(session_id)
    if session is None:
        return jsonify({"error": "Session nicht gefunden"}), 404
    cases = session.get("cases") or []
    if not (0 <= case_idx < len(cases)):
        return jsonify({"error": "Case-Index ungueltig"}), 404
    case = cases[case_idx]
    snap = case.get("weather_snapshot") or {}
    if not snap or not snap.get("hourly_data"):
        return jsonify({
            "error": "Kein Wetter-Snapshot im Goldfile. "
                     "Mit `python cost_testing/freeze_golden.py --force` neu einfrieren."
        }), 410

    hourly = snap.get("hourly_data") or {}
    pressure = snap.get("pressure_level_data") or {}
    elevation_m = snap.get("elevation_m") or 850
    date_str = case.get("date") or ""

    chart_data = format_data_for_charts(
        hourly, pressure,
        elevation_ref=elevation_m,
        slope_azimuth=snap.get("slope_azimuth"),
        slope_angle=snap.get("slope_angle"),
        region_id=None,
    )

    # Surface-Anchor fuer Hoehenwind-Profile (analog /api/altitude-wind).
    surface_anchor_by_time = {}
    for ts, hd in hourly.items():
        gust = hd.get("wind_gusts_10m")
        ws = hd.get("wind_speed_10m")
        wd = hd.get("wind_direction_10m")
        if gust is not None and ws is not None:
            surface_anchor_by_time[ts] = {
                "elevation_m": elevation_m,
                "gust_kmh": float(gust),
                "wind_speed_kmh": float(ws),
                "wind_direction_10m": float(wd) if wd is not None else None,
            }

    alt_data = format_altitude_wind_for_charts(
        pressure, hourly, elevation_m, None,
        surface_anchor_by_time=surface_anchor_by_time,
    )

    # Tagesweise Gruppierung — Snapshot enthaelt nur EINEN Tag, deshalb
    # einfach nach date_str filtern (keine "heute+zukunft"-Logik wie in
    # _group_chart_by_day, weil unser Datum in der Vergangenheit liegen kann).
    wx_day = {"wind": [], "precipitation": [], "thermik": [], "cloudbase": []}
    for key in wx_day.keys():
        for entry in chart_data.get(key, []) or []:
            t = entry.get("time", "")
            if isinstance(t, str) and t.startswith(date_str):
                wx_day[key].append(entry)

    # Format-Hinweis: meteogram.js (renderChart) erwartet pro Profil ein
    # Objekt mit {time, levels}. Hier nur Profile des Test-Tages durchreichen.
    alt_day = []
    for profile in alt_data.get("profiles", []) or []:
        t = profile.get("time", "")
        if isinstance(t, str) and t.startswith(date_str):
            alt_day.append({
                "time": t,
                "levels": profile.get("levels", []),
            })

    # Bodenwind-Serie (terrain-korrigiert) — Meteogram zeichnet damit den
    # unteren Wind-Track. Wir stellen sie nur fuer den Test-Tag bereit.
    ground_wind = []
    for ts, hd in sorted(hourly.items()):
        if not (isinstance(ts, str) and ts.startswith(date_str)):
            continue
        try:
            hour = int(ts[11:13])
        except Exception:
            continue
        ground_wind.append({
            "hour": hour,
            "wind_speed_kmh": _safe_float(hd.get("wind_speed_10m")),
            "wind_gust_kmh": _safe_float(hd.get("wind_gusts_10m")),
            "wind_direction_deg": _safe_float(hd.get("wind_direction_10m")),
        })

    return jsonify({
        "spot_name": case.get("spot"),
        "date": date_str,
        "elevation_m": elevation_m,
        "windrichtung": snap.get("windrichtung"),
        "ideal_wind_max": snap.get("ideal_wind_max"),
        "wxDay": wx_day,
        "altDay": alt_day,
        "ground_wind": ground_wind,
        "thresholds": _tier_thresholds(),
    })


# ============================================================================
# LABELED EXAMPLES — Few-Shot-Pipeline Schritt 1 (Admin-only, Regionen)
# ============================================================================

@app.route("/admin/labeled-examples", methods=["GET"])
@_require_admin
def admin_labeled_examples():
    """Verwaltungs-Seite fuer den Few-Shot-Pool."""
    from engine import labeled_examples as le
    entries = le.load_all()
    entries.sort(key=lambda e: e.get("timestamp") or "", reverse=True)
    return render_template("admin/labeled_examples.html", entries=entries)


@app.route("/api/admin/labeled-examples", methods=["POST"])
@_require_admin
def api_labeled_examples_create():
    """Speichert einen Region- oder Spot-Analyse-Fall als Labeled Example."""
    from engine import labeled_examples as le

    payload = request.get_json(silent=True) or {}
    ok, err = le.validate_payload(payload)
    if not ok:
        return jsonify({"ok": False, "error": err}), 400

    parsed = le.parse_analysis_id(payload["analysis_id"])
    if parsed is None:
        return jsonify({"ok": False, "error": "invalid analysis_id"}), 400
    kind, entity_id, target_date = parsed

    if engine is None:
        return jsonify({"ok": False, "error": "engine not ready"}), 503

    if kind == "region":
        if not getattr(engine, "region_analyses", None):
            return jsonify({"ok": False, "error": "engine not ready"}), 503
        analysis_entry = (engine.region_analyses.get(entity_id) or {}).get(target_date)
    else:  # spot
        if not getattr(engine, "spot_analyses", None):
            return jsonify({"ok": False, "error": "engine not ready"}), 503
        site_name = le.resolve_spot_name(entity_id)
        if not site_name:
            return jsonify({"ok": False, "error": f"unknown spot slug '{entity_id}'"}), 404
        analysis_entry = (engine.spot_analyses.get(site_name) or {}).get(target_date)

    if not analysis_entry:
        return jsonify({"ok": False, "error": "analysis not in cache"}), 404

    snap = le.build_snapshot(kind, entity_id, target_date, analysis_entry, payload)
    le.append_or_replace(snap)
    return jsonify({
        "ok": True,
        "analysis_id": snap["analysis_id"],
        "stored_at": snap["timestamp"],
    })


@app.route("/api/admin/labeled-examples", methods=["GET"])
@_require_admin
def api_labeled_examples_list():
    """Alle Eintraege (fuer Verwaltungs-Tabelle / Client-Filter)."""
    from engine import labeled_examples as le
    entries = le.load_all()
    entries.sort(key=lambda e: e.get("timestamp") or "", reverse=True)
    return jsonify({"ok": True, "entries": entries, "count": len(entries)})


@app.route("/api/admin/labeled-examples/<analysis_id>", methods=["GET"])
@_require_admin
def api_labeled_examples_get(analysis_id):
    from engine import labeled_examples as le
    entry = le.load_by_id(analysis_id)
    if entry is None:
        return jsonify({"ok": False, "error": "not found"}), 404
    return jsonify({"ok": True, "entry": entry})


@app.route("/api/admin/labeled-examples/<analysis_id>/meteogram", methods=["GET"])
@_require_admin
def api_labeled_examples_meteogram(analysis_id):
    """Meteogramm-Daten aus dem eingebetteten Wetter-Snapshot eines Labels.

    Liefert {wx, alt} im selben Format wie /api/weather/<spot> + /api/altitude-wind/<spot>
    (bzw. Region-Pendants), aber gefiltert auf das target_date des Labels und
    OHNE today-Filter. Damit funktioniert das Meteogramm auch fuer Labels,
    deren target_date nicht mehr im Live-Forecast-Fenster liegt.

    Voraussetzung: Label hat weather_input.pressure_levels eingebettet
    (ab build_snapshot mit Schema-Erweiterung Mai 2026). Alte Labels ohne
    eingebettete pressure_levels: 404 → Frontend faellt auf Live-API zurueck.
    """
    from engine import labeled_examples as le
    entry = le.load_by_id(analysis_id)
    if entry is None:
        return jsonify({"error": "not found"}), 404

    wi = entry.get("weather_input") or {}
    hourly_data = wi.get("hourly") or {}
    pressure_level_data = wi.get("pressure_levels") or {}
    if not hourly_data or not pressure_level_data:
        return jsonify({"error": "no embedded weather snapshot"}), 404

    target_date = entry.get("target_date") or ""
    entity_type = entry.get("entity_type")
    is_region = (entity_type != "spot")

    slope_az = None
    slope_an = None
    windrichtung = None
    ideal_wind_max = None
    if is_region:
        region_id = entry.get("entity_slug")
        from engine.labeled_examples import _load_region_meta
        rmeta = _load_region_meta().get(region_id, {})
        try:
            elevation_m = int(rmeta.get("elevation_ref") or 1200)
        except (TypeError, ValueError):
            elevation_m = 1200
    else:
        site_name = entry.get("spot_or_region_id")
        spot_info = None
        for s in engine.spots:
            if s.get("name") == site_name:
                spot_info = s
                break
        elevation_m = (spot_info.get("elevation_m") if spot_info else None) or 850
        slope_az = spot_info.get("slope_azimuth") if spot_info else None
        slope_an = spot_info.get("slope_angle") if spot_info else None
        windrichtung = spot_info.get("windrichtung") if spot_info else None
        ideal_wind_max = spot_info.get("ideal_wind_max") if spot_info else None
        region = None
        if spot_info:
            region = find_region_for_point(spot_info.get("lat") or 0, spot_info.get("lon") or 0)
        region_id = region["id"] if region else None

    # Mai 2026: Region-Labels reichen Spot-Median-Override aus dem Snapshot weiter,
    # damit historische Anzeigen die korrekte Thermik (max_h aus Spots) zeigen.
    spotmedian_override = wi.get("thermals_spotmedian") if is_region else None

    chart_data = format_data_for_charts(
        hourly_data, pressure_level_data,
        elevation_ref=elevation_m,
        slope_azimuth=slope_az,
        slope_angle=slope_an,
        region_id=region_id,
        spotmedian_override=spotmedian_override,
    )
    if is_region:
        for w in chart_data.get("wind", []):
            w["gusts"] = None

    wx_by_day = {target_date: {"wind": [], "precipitation": [], "thermik": [], "cloudbase": []}}
    for key in ("wind", "precipitation", "thermik", "cloudbase"):
        for ent in chart_data.get(key, []):
            try:
                ds = datetime.fromisoformat(ent["time"]).strftime("%Y-%m-%d")
            except Exception:
                continue
            if ds == target_date:
                wx_by_day[target_date][key].append(ent)

    if is_region:
        alt_data = format_altitude_wind_for_charts(
            pressure_level_data, region_id=region_id,
        )
    else:
        surface_anchor_by_time = {}
        for ts, hd in hourly_data.items():
            gust = hd.get("wind_gusts_10m")
            ws = hd.get("wind_speed_10m")
            wd = hd.get("wind_direction_10m")
            if gust is not None and ws is not None:
                surface_anchor_by_time[ts] = {
                    "elevation_m": elevation_m,
                    "gust_kmh": float(gust),
                    "wind_speed_kmh": float(ws),
                    "wind_direction_10m": float(wd) if wd is not None else None,
                }
        alt_data = format_altitude_wind_for_charts(
            pressure_level_data, hourly_data, elevation_m, region_id,
            surface_anchor_by_time=surface_anchor_by_time,
        )

    alt_by_day = {target_date: []}
    for profile in alt_data.get("profiles", []) if isinstance(alt_data, dict) else []:
        try:
            dt = datetime.fromisoformat(profile["time"])
            ds = dt.strftime("%Y-%m-%d")
        except Exception:
            continue
        if ds == target_date:
            alt_by_day[target_date].append({"hour": dt.hour, "profiles": profile["levels"]})

    wx_payload = {
        "elevation_m": elevation_m,
        "dates": [target_date],
        "data": wx_by_day,
        "stale": False,
        "expected_days": 1,
        "thresholds": _tier_thresholds(),
    }
    if is_region:
        wx_payload["region_id"] = region_id
        wx_payload["region_name"] = entry.get("spot_or_region_id") or region_id
        wx_payload["elevation_ref"] = elevation_m
        wx_payload["is_region"] = True
    else:
        wx_payload["spot_name"] = entry.get("spot_or_region_id")
        wx_payload["windrichtung"] = windrichtung
        wx_payload["ideal_wind_max"] = ideal_wind_max

    alt_payload = {
        "elevation_m": elevation_m,
        "dates": [target_date],
        "data": alt_by_day,
    }

    return jsonify({"ok": True, "wx": wx_payload, "alt": alt_payload})


@app.route("/api/admin/labeled-examples/<analysis_id>", methods=["PATCH"])
@_require_admin
def api_labeled_examples_patch(analysis_id):
    from engine import labeled_examples as le
    payload = request.get_json(silent=True) or {}
    ok, err = le.validate_patch(payload)
    if not ok:
        return jsonify({"ok": False, "error": err}), 400
    updated = le.patch_entry(analysis_id, payload)
    if updated is None:
        return jsonify({"ok": False, "error": "not found"}), 404
    return jsonify({"ok": True, "entry": updated})


@app.route("/api/admin/labeled-examples/<analysis_id>", methods=["DELETE"])
@_require_admin
def api_labeled_examples_delete(analysis_id):
    from engine import labeled_examples as le
    if not le.delete_entry(analysis_id):
        return jsonify({"ok": False, "error": "not found"}), 404
    return jsonify({"ok": True})


# ============================================================================
# FEEDBACK API (Spot/Region — anonym via localStorage client_id)
# ============================================================================

def _hash_ip(ip: str) -> Optional[str]:
    """Salted SHA-256 der IP fuer Missbrauchs-Korrelation ohne Klartext-Speicherung."""
    if not ip:
        return None
    salt = (config.FEEDBACK_SALT or "wingcast-feedback")[:32]
    return hashlib.sha256(f"{salt}:{ip}".encode("utf-8")).hexdigest()[:32]


@app.route("/api/feedback", methods=["POST"])
def api_feedback_submit():
    """Anonymer Feedback-Submit. JSON-Body:
        target_type: 'spot' | 'region'
        target_id:   Spot-Name oder Region-Slug
        target_date: 'YYYY-MM-DD' oder null
        vote:        'up' | 'down' | null  (mind. eines von vote/comment muss da sein)
        comment:     string (max 4000 chars) oder null
        client_id:   localStorage UUID (8-64 Zeichen, [A-Za-z0-9_-])
    """
    mgr = _get_feedback_manager()
    if mgr is None:
        return jsonify({"error": "Feedback-Service nicht verfuegbar"}), 503

    payload = request.get_json(silent=True) or {}
    fid = mgr.record(
        target_type=payload.get("target_type"),
        target_id=payload.get("target_id"),
        target_date=payload.get("target_date"),
        vote=payload.get("vote"),
        comment=payload.get("comment"),
        client_id=payload.get("client_id"),
        subscriber_id=session.get("sub_id"),
        user_agent=(request.user_agent.string or "")[:300],
        ip_hash=_hash_ip(_client_ip()),
    )
    if fid is None:
        return jsonify({"error": "Ungueltige Eingabe"}), 400

    agg = mgr.aggregate(
        payload.get("target_type"),
        (payload.get("target_id") or "").strip(),
        (payload.get("target_date") or "").strip() or None,
    )
    return jsonify({"id": fid, "aggregate": agg}), 200


@app.route("/api/feedback/<target_type>/<path:target_id>", methods=["GET"])
def api_feedback_get(target_type, target_id):
    """Liest eigene Stimme + Aggregat. Query: ?date=YYYY-MM-DD&client_id=..."""
    mgr = _get_feedback_manager()
    if mgr is None:
        return jsonify({"error": "Feedback-Service nicht verfuegbar"}), 503

    target_date = (request.args.get("date") or "").strip() or None
    client_id = (request.args.get("client_id") or "").strip()

    own = mgr.get_own(target_type, target_id, target_date, client_id) if client_id else None
    agg = mgr.aggregate(target_type, target_id, target_date)
    return jsonify({"own": own, "aggregate": agg}), 200


@app.route("/api/feedback/<int:feedback_id>", methods=["DELETE"])
def api_feedback_delete(feedback_id):
    """Eigene Stimme entfernen. Query: ?client_id=..."""
    mgr = _get_feedback_manager()
    if mgr is None:
        return jsonify({"error": "Feedback-Service nicht verfuegbar"}), 503
    client_id = (request.args.get("client_id") or "").strip()
    if not client_id:
        return jsonify({"error": "client_id fehlt"}), 400
    ok = mgr.delete_own(feedback_id, client_id)
    if not ok:
        return jsonify({"error": "Nicht gefunden oder nicht berechtigt"}), 404
    return jsonify({"ok": True}), 200


# ============================================================================
# PAGE ROUTES
# ============================================================================

@app.route("/")
def index():
    return render_template(
        "index.html",
        forecast_days=current_max_days(),
        show_reference_points=config.SHOW_REFERENCE_POINTS,
        show_precip_refpoints=config.SHOW_PRECIP_REFPOINTS,
        show_osm_peaks=config.SHOW_OSM_PEAKS,
    )


@app.route("/chat")
def chat_page():
    return render_template(
        "index.html",
        forecast_days=current_max_days(),
        show_reference_points=config.SHOW_REFERENCE_POINTS,
        show_precip_refpoints=config.SHOW_PRECIP_REFPOINTS,
        show_osm_peaks=config.SHOW_OSM_PEAKS,
    )


@app.route("/map")
def map_page():
    return render_template(
        "index.html",
        forecast_days=current_max_days(),
        show_reference_points=config.SHOW_REFERENCE_POINTS,
        show_precip_refpoints=config.SHOW_PRECIP_REFPOINTS,
        show_osm_peaks=config.SHOW_OSM_PEAKS,
    )


@app.route("/regionen")
def regionen_page():
    return render_template(
        "regionen.html",
        forecast_days=current_max_days(),
        show_reference_points=config.SHOW_REFERENCE_POINTS,
        show_precip_refpoints=config.SHOW_PRECIP_REFPOINTS,
        show_osm_peaks=config.SHOW_OSM_PEAKS,
    )


@app.route("/og-image/briefing.png")
def og_image_briefing():
    """Dynamisches OpenGraph-Bild fuer Link-Previews.

    Query-Params: tier (violet|green|conditional|gray|none), title, subtitle.
    Rendert ein 1200x630 PNG mit Tier-Farbverlauf + Wingcast-Branding + Text.
    Fallback auf statisches Default-Design wenn keine Params.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        logger.warning("og_image_briefing: Pillow nicht installiert, 502 Response")
        return Response("OG-Image-Generator nicht verfuegbar (Pillow fehlt)",
                        status=502, mimetype="text/plain")

    tier = (request.args.get("tier") or "none").lower()
    title = (request.args.get("title") or "Wingcast – Flugwetter").strip()
    subtitle = (request.args.get("subtitle") or
                "Praezise Thermik- und Wind-Prognose fuer die Schweizer Berge.").strip()

    # Tier -> Gradient-Farben (Hex -> RGB)
    tier_colors = {
        "violet":      ("#6d28d9", "#a78bfa"),
        "green":       ("#15803d", "#4ade80"),
        "conditional": ("#b45309", "#fbbf24"),
        "gray":        ("#475569", "#94a3b8"),
        "none":        ("#1e293b", "#475569"),
    }
    top_hex, bot_hex = tier_colors.get(tier, tier_colors["none"])

    def _hex_to_rgb(h: str) -> tuple[int, int, int]:
        h = h.lstrip("#")
        return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))

    W, H = 1200, 630
    top_rgb = _hex_to_rgb(top_hex)
    bot_rgb = _hex_to_rgb(bot_hex)

    # Vertikaler Gradient via Line-Fill
    img = Image.new("RGB", (W, H), top_rgb)
    draw = ImageDraw.Draw(img)
    for y in range(H):
        t = y / (H - 1)
        r = int(top_rgb[0] + (bot_rgb[0] - top_rgb[0]) * t)
        g = int(top_rgb[1] + (bot_rgb[1] - top_rgb[1]) * t)
        b = int(top_rgb[2] + (bot_rgb[2] - top_rgb[2]) * t)
        draw.line([(0, y), (W, y)], fill=(r, g, b))

    # Dunkler Schleier unten fuer Text-Kontrast
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay)
    odraw.rectangle([0, int(H * 0.55), W, H], fill=(0, 0, 0, 110))
    img = Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")
    draw = ImageDraw.Draw(img)

    # Fonts — Fallback-Kette (Windows/Linux/macOS)
    def _load_font(size: int):
        candidates = [
            "C:\\Windows\\Fonts\\segoeuib.ttf",     # Segoe UI Bold
            "C:\\Windows\\Fonts\\arialbd.ttf",       # Arial Bold
            "C:\\Windows\\Fonts\\segoeui.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            "/System/Library/Fonts/Helvetica.ttc",
        ]
        for path in candidates:
            try:
                return ImageFont.truetype(path, size)
            except (OSError, IOError):
                continue
        return ImageFont.load_default()

    brand_font = _load_font(42)
    title_font = _load_font(72)
    sub_font   = _load_font(36)

    # Brand-Header oben links
    draw.text((60, 50), "WINGCAST", font=brand_font, fill=(255, 255, 255))
    draw.line([(60, 110), (260, 110)], fill=(255, 255, 255, 200), width=4)

    # Titel mittig-unten — Zeilenumbruch bei >30 Zeichen
    def _wrap(text: str, max_chars: int) -> list[str]:
        words = text.split()
        lines, cur = [], ""
        for w in words:
            if len(cur) + len(w) + 1 <= max_chars:
                cur = (cur + " " + w).strip()
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines[:2]  # max 2 Zeilen

    title_lines = _wrap(title, 28)
    title_y = int(H * 0.60)
    for line in title_lines:
        draw.text((60, title_y), line, font=title_font, fill=(255, 255, 255))
        title_y += 82

    # Subtitle
    sub_lines = _wrap(subtitle, 48)
    sub_y = title_y + 16
    for line in sub_lines:
        draw.text((60, sub_y), line, font=sub_font, fill=(226, 232, 240))
        sub_y += 48

    import io
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    buf.seek(0)
    return Response(buf.getvalue(), mimetype="image/png",
                    headers={"Cache-Control": "public, max-age=600"})


@app.route("/briefing")
def briefing_page():
    # OG-Meta: wenn ?regions=...&day=... gesetzt, dynamische Titel/Beschreibung
    # fuer hübsche Link-Previews (WhatsApp, iMessage, Telegram, ...).
    regions_q = (request.args.get("regions") or "").strip()
    day_q = request.args.get("day")
    spot_q = (request.args.get("spot") or "").strip()
    og = _build_briefing_og(regions_q, day_q, spot_q)
    from engine import test_mode
    return render_template(
        "briefing.html",
        forecast_days=current_max_days(),
        og=og,
        debug_mode=test_mode.is_view_active() or _is_admin_session(),
    )


def _build_briefing_og(regions_csv: str, day_str: str | None, spot_name: str = "") -> dict:
    """Baut OG-Meta-Daten fuer die Briefing-Seite aus Query-Params.

    - Fallback: generische Site-Description wenn keine Filter gesetzt.
    - Mit Filter: peekt briefing_data und baut Title aus bestem Spot / Tag-Tier.
    """
    base_url = request.url_root.rstrip("/")
    title = "Wingcast – Flugwetter für Gleitschirmpiloten"
    desc  = "Präzise Thermik- und Wind-Prognose für die Schweizer Berge."
    img   = f"{base_url}/og-image/briefing.png"

    region_ids = [r.strip() for r in regions_csv.split(",") if r.strip()] if regions_csv else []
    try:
        day_idx = int(day_str) if day_str is not None and day_str != "" else None
    except ValueError:
        day_idx = None

    if not region_ids or engine is None:
        return {"title": title, "description": desc, "image": img, "url": request.url}

    try:
        briefing_data = engine.build_briefing_data()
    except Exception:
        logger.exception("_build_briefing_og: build_briefing_data failed")
        return {"title": title, "description": desc, "image": img, "url": request.url}

    days = briefing_data.get("days", []) or []
    region_names = _region_names(region_ids)
    region_label = region_names[0] if len(region_names) == 1 else f"{len(region_names)} Regionen"

    # Spot/Tag ermitteln
    target_day = None
    if day_idx is not None and 0 <= day_idx < len(days):
        target_day = days[day_idx]

    my_spots_per_day = []
    for d in days:
        spots = [s for s in (d.get("top_spots") or [])
                 if s.get("region_id") in region_ids]
        my_spots_per_day.append((d, spots))

    # Besten Spot finden (optional gefiltert auf spot_q)
    def _spot_rank(s):
        from email_service import _TIER_RANK, _spot_tier
        return (_TIER_RANK.get(_spot_tier(s), -1), float(s.get("rating") or 0))

    best_spot = None
    best_day  = None
    if target_day is not None:
        spots = [s for s in (target_day.get("top_spots") or [])
                 if s.get("region_id") in region_ids
                 and (not spot_name or s.get("spot") == spot_name)]
        if spots:
            best_spot = max(spots, key=_spot_rank)
            best_day  = target_day
    if best_spot is None:
        # Ueber alle Tage besten Spot finden
        flat = [(d, s) for d, spots in my_spots_per_day for s in spots]
        if spot_name:
            flat = [(d, s) for d, s in flat if s.get("spot") == spot_name]
        if flat:
            best_day, best_spot = max(flat, key=lambda pair: _spot_rank(pair[1]))

    from email_service import _TIER_META, _spot_tier, _date_label, _rating_for_spot
    if best_spot and best_day:
        tier = _spot_tier(best_spot)
        meta = _TIER_META.get(tier, _TIER_META["gray"])
        rating = _rating_for_spot(best_spot)  # v1.4: Integer 1-10
        label = _date_label(best_day.get("date", ""))
        day_short = label.get("short", "")
        title = f"{best_spot.get('spot','')} – {day_short} {meta['label']} {rating}"
        desc = f"{region_label} · {meta['label']} · Rating {rating} · Wingcast"
        tier_param = tier
    else:
        tier_param = "none"
        title = f"Wingcast – {region_label}"
        desc = "Kein fliegbares Fenster in dieser Region im aktuellen Zeitraum."

    # Dynamisches OG-Image mit Tier-Farbe + Headline
    from urllib.parse import urlencode, quote
    img_params = {
        "tier": tier_param,
        "title": title[:80],
        "subtitle": desc[:100],
    }
    img = f"{base_url}/og-image/briefing.png?{urlencode(img_params, quote_via=quote)}"

    return {"title": title, "description": desc, "image": img, "url": request.url}


@app.route("/api/briefing", methods=["GET"])
def api_briefing_get():
    """Liefert die Tages-Aggregation + Wetterlage-Synoptik fuer den Wingcast.
    Days/Spots werden immer frisch aus spot_analyses gebaut, der Wetterlage-
    Block kommt aus dem Synoptik-Cache (1×/Tag refreshed).

    Test-View-aware: wenn `test_mode.is_view_active()` aktiv ist, werden
    Spots/Regionen aus `data/test_runs/latest/` gelesen — gleiche Logik
    wie /api/analyses und /api/region-analyses.
    """
    from engine import test_mode
    if test_mode.is_view_active():
        spot_data, region_data, _ = test_mode.load_test_run_analyses()
        aggregated = engine.build_briefing_data(
            spot_analyses=spot_data, region_analyses=region_data
        )
        aggregated["_test_view"] = True
    else:
        aggregated = engine.build_briefing_data()
    return jsonify({
        "success": True,
        "days": aggregated.get("days", []),
        "forecast_dates": aggregated.get("forecast_dates", []),
        "generated_at": aggregated.get("generated_at", ""),
        "wetterlage": aggregated.get("wetterlage"),
        "test_view": aggregated.get("_test_view", False),
    })


@app.route("/api/briefing/generate", methods=["POST"])
def api_briefing_generate():
    """Triggert manuell den Wetterlage-Block (Synoptik) refresh
    (1× extra API-Call ECMWF + optional 1× Foehn-API + 1× LLM-Call).
    Schlaegt der Refresh fehl oder fehlt der analysis_client, wird der
    Block einfach uebersprungen — kein Fallback-Text, kein
    Halluzinationsrisiko.
    """
    wetterlage_status = "skipped"
    try:
        from engine.synoptic_llm import refresh_synoptic_overview
        from fetch_weather import load_cached_weather
        wcache = load_cached_weather()
        if wcache and engine.synoptic_client:
            sctx = refresh_synoptic_overview(
                wcache, engine.synoptic_client, engine.synoptic_model,
            )
            if sctx:
                wetterlage_status = (
                    "ok" if sctx.get("llm_overview") else "no_llm_overview"
                )
            else:
                wetterlage_status = "build_failed"
        else:
            wetterlage_status = (
                "no_weather_cache" if not wcache else "no_synoptic_client"
            )
    except Exception as e:
        logger.exception("api_briefing_generate: Wetterlage-Refresh fehlgeschlagen: %s", e)
        wetterlage_status = f"error: {e.__class__.__name__}"

    success = wetterlage_status == "ok"
    payload = {
        "success": success,
        "wetterlage_refresh": wetterlage_status,
    }
    if not success:
        payload["error"] = f"Wetterlage-Refresh: {wetterlage_status}"
    return jsonify(payload), (200 if success else 500)


# ============================================================================
# SYNOPTIK-KARTE (/synoptik)
# ============================================================================

@app.route("/synoptik")
def synoptik_page():
    """Interaktive Bodendruckkarte (Isobaren + H/T-Zentren, Met-Office-Stil)."""
    return render_template("synoptik.html", forecast_days=current_max_days())


@app.route("/api/synoptic/grid", methods=["GET"])
def api_synoptic_grid():
    """Liefert das dichte Druckraster + Zentren fuer die Synoptik-Karte.

    Grid kommt aus data/synoptic_grid.json (1x/Tag vom Scheduler refreshed).
    Fehlt der Cache (Erst-Deploy), wird EIN Inline-Refresh versucht.
    Dazu der Wetterlage-Textblock aus dem Synoptik-Cache (nur die fuer die
    Seite noetigen Felder — nicht das ganze Strukturfeld).
    """
    from engine.synoptic_grid import load_synoptic_grid_cache, refresh_synoptic_grid
    from engine.synoptic_context import load_synoptic_cache

    grid = load_synoptic_grid_cache()
    if grid is None:
        try:
            grid = refresh_synoptic_grid()
        except Exception:
            logger.exception("api_synoptic_grid: Inline-Refresh fehlgeschlagen")
            grid = None
    if grid is None:
        return jsonify({"success": False,
                        "error": "Kein Synoptik-Grid verfuegbar"}), 503

    # Nur die konfigurierten Tage ausliefern (FORECAST_DAYS inkl. Override).
    # Bewusst KEIN Login-Gating wie im Briefing: die Synoptik ist grobe
    # Uebersichtsinfo, kein Premium-Spot-Detail.
    allowed = _allowed_date_strs(config.FORECAST_DAYS)
    kept = [ts for ts in grid.get("timesteps", []) if ts[:10] in allowed]
    grid = dict(grid,
                timesteps=kept,
                values={ts: grid["values"][ts] for ts in kept},
                centers={ts: grid.get("centers", {}).get(ts, []) for ts in kept})

    wetterlage = None
    sctx = load_synoptic_cache()
    if sctx:
        wetterlage = {
            "lage_label": sctx.get("lage_label"),
            "llm_overview": sctx.get("llm_overview"),
            "forecast_dates": sctx.get("forecast_dates"),
            "generated_at": sctx.get("generated_at"),
        }

    return jsonify({"success": True, "grid": grid, "wetterlage": wetterlage})


@app.route("/api/synoptic/grid/refresh", methods=["POST"])
def api_synoptic_grid_refresh():
    """Triggert manuell den Grid-Refresh (5 gebatchte Open-Meteo-Calls)."""
    from engine.synoptic_grid import refresh_synoptic_grid
    status = "ok"
    try:
        result = refresh_synoptic_grid()
        if result is None:
            status = "fetch_failed"
    except Exception as e:
        logger.exception("api_synoptic_grid_refresh: %s", e)
        status = f"error: {e.__class__.__name__}"

    success = status == "ok"
    payload = {"success": success, "grid_refresh": status}
    if not success:
        payload["error"] = f"Grid-Refresh: {status}"
    return jsonify(payload), (200 if success else 500)


# ============================================================================
# CHAT API
# ============================================================================

def _require_login_json(view_func):
    """Decorator: Endpoint nur fuer eingeloggte User. Sonst 401 mit JSON-Body
    {error: ..., login_required: true} — Frontend kann das auswerten."""
    @wraps(view_func)
    def wrapper(*args, **kwargs):
        if not session.get("sub_id"):
            return jsonify({
                "error": "Login erforderlich",
                "login_required": True,
                "message": "Logge dich ein, um den Chat-Berater (Beta) zu nutzen.",
            }), 401
        return view_func(*args, **kwargs)
    return wrapper


def _chat_session_id():
    """Chat-History ist an den eingeloggten User gebunden — nicht an eine
    Client-/localStorage-ID. Dadurch ist der Verlauf geräteübergreifend,
    isoliert pro User und nur für den jeweiligen User sichtbar."""
    return f"user_{session['sub_id']}"


@app.route("/api/chat", methods=["POST"])
@_require_login_json
def api_chat():
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": i18n.t("chat.err.no_message")}), 400

    message = data["message"].strip()
    session_id = _chat_session_id()

    if not message:
        return jsonify({"error": i18n.t("chat.err.empty_message")}), 400

    # Phase 1: Streaming-Variante (Tool-Use + Map-Actions) wenn Client opt-in
    accept = request.headers.get("Accept", "")
    if "application/x-ndjson" in accept:
        def generate():
            try:
                for event in engine.answer_stream(session_id, message):
                    yield json.dumps(event, ensure_ascii=False) + "\n"
            except Exception as e:
                logger.exception("answer_stream Fehler")
                err_event = {"type": "error", "content": str(e)}
                yield json.dumps(err_event, ensure_ascii=False) + "\n"
                yield json.dumps({"type": "done"}, ensure_ascii=False) + "\n"

        return Response(
            stream_with_context(generate()),
            mimetype="application/x-ndjson",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",  # disable nginx buffering
            },
        )

    # Legacy Pfad: einmalige JSON-Antwort
    reply = engine.answer(session_id, message)
    return jsonify({"reply": reply, "session_id": session_id})


@app.route("/api/reset-chat", methods=["POST"])
@_require_login_json
def api_reset_chat():
    """Setzt die Konversation des eingeloggten Users zurück."""
    engine.reset_conversation(_chat_session_id())
    return jsonify({"success": True})


@app.route("/api/chat-history", methods=["GET"])
@_require_login_json
def api_chat_history():
    """Gibt dem eingeloggten User seinen eigenen Chat-Verlauf zurück
    (nur user/assistant, ohne System-Prompt und internes Wetter-Prelude)."""
    return jsonify({"messages": engine.public_history(_chat_session_id())})




@app.route("/api/run-analyses", methods=["POST"])
def api_run_analyses():
    """Startet die LLM Spot-Analyse für alle Spots."""
    try:
        result = engine.run_spot_analyses()
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def _format_spot_analyses_flat(spot_analyses: dict, loaded_at: Optional[str], allowed_dates: set) -> dict:
    """Baut die flache Spot-Analysen-Repraesentation fuer /api/analyses.

    Identisches Format fuer Live- und Test-View, damit das Frontend den
    Unterschied nicht bemerkt — bis auf das `_test_view`-Flag im Wrapper.
    """
    flat: dict = {}
    for spot_name, days in spot_analyses.items():
        flat[spot_name] = {}
        for date_str, entry in days.items():
            if date_str not in allowed_dates:
                continue
            safety = entry.get("safety", {})
            fly = entry.get("flyability", {})
            doc = {
                "spot": spot_name,
                "date": date_str,
                "status": entry.get("status", "error"),
                "safety_status": safety.get("safety_status", "error"),
                "safe_window": safety.get("safe_window", "keins"),
                "best_window": entry.get("best_window", "?"),
                "safety_feedback": safety.get("summary", ""),
                "error": safety.get("error", ""),
                "foehn_risk": safety.get("foehn_risk", "none"),
                "wind_summary": safety.get("wind_summary", ""),
                "updated_at": loaded_at,
                "experience_rating": int(entry.get("experience_rating", 1) or 1),
                "is_conditional": bool(entry.get("is_conditional", False)),
            }
            for key in ("no_go_reasons", "caution_notes"):
                val = safety.get(key, [])
                doc[key] = json.dumps(val, ensure_ascii=False) if isinstance(val, list) else str(val)
            for lbl_key in ("primary_no_go", "primary_caution", "primary_reducer", "primary_booster"):
                doc[lbl_key] = safety.get(lbl_key) or None
            ss = safety.get("safety_status", "error")
            if ss in ("safe", "conditional"):
                # Fallback aus entry top-level wenn fly nested leer/fehlt.
                doc["flight_type"] = fly.get("flight_type") or entry.get("flight_type", "")
                doc["flight_duration"] = fly.get("flight_duration_estimate") or entry.get("flight_duration_estimate", "")
                doc["xc_potential"] = fly.get("xc_potential") or entry.get("xc_potential", "")
                doc["peak_climb_rate"] = fly.get("peak_climb_rate") or entry.get("peak_climb_rate", 0)
                doc["flyability_feedback"] = fly.get("recommendation") or entry.get("recommendation", "")
                for lkey in ("flyability_limits", "highlights"):
                    val = fly.get(lkey, [])
                    if isinstance(val, list):
                        val = val[:3]
                    doc[lkey] = json.dumps(val if isinstance(val, list) else [], ensure_ascii=False)
            else:
                doc["fly_error"] = entry.get("fly_error", "")
            sf = entry.get("streckenflug") or {}
            doc["streckenflug_rating"] = int(sf.get("rating", 1) or 1)
            doc["streckenflug_limiting_factor"] = sf.get("limiting_factor", "none")
            # RATING_ARCHITECTURE v2.1 — experience_rating (1-5) als Primaerwert
            for k in ("safety_rating", "experience_rating",
                      "noAnalysis", "noAnalysisReason"):
                v = entry.get(k)
                if v is not None:
                    doc[k] = v
            # Tag-System v4 (siehe docs/TAGS.md): tags + start_window durchreichen
            for k in ("tags", "start_window"):
                v = entry.get(k)
                if isinstance(v, list):
                    doc[k] = v
            # Debug-Felder: hazard_notes + flyability_notes (intern, nur zur Verifikation)
            hn = safety.get("hazard_notes")
            if isinstance(hn, dict):
                doc["hazard_notes"] = hn
            fn = fly.get("flyability_notes") if fly else None
            if isinstance(fn, dict):
                doc["flyability_notes"] = fn
            flat[spot_name][date_str] = doc
    return flat


@app.route("/api/analyses")
def api_analyses():
    """Gibt Spot-Analysen im flachen Format zurück.

    Wenn die Test-Ansicht aktiv ist, werden die Analysen aus
    `data/test_runs/latest/spot_analyses.json` gelesen statt aus dem
    Live-Engine-Cache. Prod-Daten bleiben unangetastet.
    """
    from engine import test_mode
    allowed_dates = _allowed_date_strs(current_max_days())

    if test_mode.is_view_active():
        spot_analyses, _, mtime = test_mode.load_test_run_analyses()
        loaded_at = mtime.isoformat() if mtime else None
        flat = _format_spot_analyses_flat(spot_analyses, loaded_at, allowed_dates)
        return jsonify({
            "spot_analyses": flat,
            "analyses_count": len(flat),
            "_test_view": True,
        })

    loaded_at = engine.analyses_loaded_at.isoformat() if engine.analyses_loaded_at else None
    flat = _format_spot_analyses_flat(engine.spot_analyses, loaded_at, allowed_dates)
    return jsonify({"spot_analyses": flat, "analyses_count": len(flat)})


@app.route("/api/spot-debug/<spot_name>/<date_str>")
def api_spot_debug(spot_name: str, date_str: str):
    """Gibt Debug-Felder fuer einen Spot/Tag zurück (Sub-Ratings, hazard_notes, _decisions_applied).
    Nur im Test-View oder wenn DEBUG-Modus aktiv."""
    from engine import test_mode
    if not test_mode.is_view_active() and not _is_admin_session():
        return jsonify({"error": "Nur im Test- oder Admin-Debug-Modus verfügbar"}), 403

    if test_mode.is_view_active():
        spot_analyses, _, _ = test_mode.load_test_run_analyses()
    else:
        spot_analyses = engine.spot_analyses

    days = spot_analyses.get(spot_name, {})
    entry = days.get(date_str)
    if not entry:
        return jsonify({"error": f"Keine Analyse für {spot_name} / {date_str}"}), 404

    safety = entry.get("safety", {})
    fly = entry.get("flyability", {})

    # Sub-Ratings koennen je nach Analysepfad oben-level oder in safety-Sub-Dict liegen
    def _sub(key):
        v = entry.get(key)
        if v is None:
            v = safety.get(key)
        return v

    sub_ratings = {k: _sub(k) for k in (
        "wind_safety_rating", "gust_safety_rating", "aloft_safety_rating",
        "foehn_safety_rating", "rain_safety_rating", "thunderstorm_safety_rating",
        "cape_safety_rating", "visibility_safety_rating",
    )}
    fly_sub_ratings = {k: entry.get(k) for k in (
        "thermal_rating", "altitude_rating", "xc_rating",
        "window_rating", "wind_rating",
    )}

    def _top(key):
        v = entry.get(key)
        if v is None:
            v = safety.get(key)
        return v

    return jsonify({
        "spot": spot_name,
        "date": date_str,
        "safety_status": _top("safety_status"),
        "safety_rating": _top("safety_rating"),
        "foehn_risk": _top("foehn_risk"),
        "experience_rating": entry.get("experience_rating"),
        "sub_ratings": sub_ratings,
        "hazard_notes": safety.get("hazard_notes"),
        "flyability_notes": fly.get("flyability_notes") if fly else None,
        "wind_summary": safety.get("wind_summary"),
        "wind_shear": safety.get("wind_shear"),
        "_decisions_applied": entry.get("_decisions_applied", []),
    })


@app.route("/api/region-debug/<region_id>/<date_str>")
def api_region_debug(region_id: str, date_str: str):
    """Gibt Debug-Felder fuer eine Region/Tag zurück (Sub-Ratings, hazard_notes,
    flyability_notes, _decisions_applied). Nur im Test-View oder Admin-Debug."""
    from engine import test_mode
    if not test_mode.is_view_active() and not _is_admin_session():
        return jsonify({"error": "Nur im Test- oder Admin-Debug-Modus verfügbar"}), 403

    if test_mode.is_view_active():
        _, region_analyses, _ = test_mode.load_test_run_analyses()
    else:
        region_analyses = engine.region_analyses

    days = region_analyses.get(region_id, {})
    entry = days.get(date_str)
    if not entry:
        return jsonify({"error": f"Keine Analyse für {region_id} / {date_str}"}), 404

    safety = entry.get("safety", {}) or {}
    fly = entry.get("flyability", {}) or {}

    def _sub(key):
        v = entry.get(key)
        if v is None:
            v = safety.get(key)
        return v

    sub_ratings = {k: _sub(k) for k in (
        "wind_safety_rating", "aloft_safety_rating",
        "foehn_safety_rating", "rain_safety_rating", "thunderstorm_safety_rating",
        "cape_safety_rating", "visibility_safety_rating",
    )}

    def _top(key):
        v = entry.get(key)
        if v is None:
            v = safety.get(key)
        return v

    return jsonify({
        "region_id": region_id,
        "date": date_str,
        "safety_status": _top("safety_status"),
        "safety_rating": _top("safety_rating"),
        "foehn_risk": _top("foehn_risk"),
        "experience_rating": entry.get("experience_rating"),
        "sub_ratings": sub_ratings,
        "hazard_notes": safety.get("hazard_notes"),
        "flyability_notes": fly.get("flyability_notes"),
        "wind_summary": safety.get("wind_summary"),
        "wind_shear": safety.get("wind_shear"),
        "_decisions_applied": entry.get("_decisions_applied", []),
    })


@app.route("/api/spot-context/<spot_name>/<date_str>")
def api_spot_context(spot_name: str, date_str: str):
    """Liefert den EXAKTEN Wetter-Kontext-Text, den die KI fuer diesen Spot/Tag
    sieht (Dataview). Ruft denselben Builder wie die Analyse auf
    (_build_single_spot_context, mode="dashboard") — Single Source of Truth.
    Oeffentlich: zeigt nur Wetterdaten, kein test/admin-Gate."""
    spot = next((s for s in engine.spots if s["name"] == spot_name), None)
    if not spot:
        return jsonify({"error": f"Spot '{spot_name}' nicht gefunden"}), 404

    # Gecachte Region-Analyse fuer diesen Tag mitgeben, damit der Text 1:1 dem
    # entspricht, was die KI bei der Spot-Analyse gesehen hat (inkl. Region-Block).
    region_result = None
    region = find_region_for_point(spot["latitude"], spot["longitude"])
    if region:
        region_result = (engine.region_analyses.get(region["id"]) or {}).get(date_str)

    text = engine._build_single_spot_context(
        spot, date_str, mode="dashboard", region_analysis_result=region_result
    )
    if not text:
        return jsonify({"error": f"Keine Wetterdaten fuer {spot_name} / {date_str}"}), 404

    return jsonify({"spot": spot_name, "date": date_str, "text": text})


@app.route("/api/region-context/<region_id>/<date_str>")
def api_region_context(region_id: str, date_str: str):
    """Liefert den EXAKTEN Wetter-Kontext-Text, den die KI fuer diese Region/Tag
    sieht (Dataview). Ruft denselben Builder wie die Analyse auf
    (_build_single_region_context) — Single Source of Truth. Oeffentlich."""
    region = next((r for r in get_all_regions() if r["id"] == region_id), None)
    if not region:
        return jsonify({"error": f"Region '{region_id}' nicht gefunden"}), 404

    text = engine._build_single_region_context(region, date_str)
    if not text:
        return jsonify({"error": f"Keine Wetterdaten fuer {region_id} / {date_str}"}), 404

    return jsonify({"region_id": region_id, "date": date_str, "text": text})


@app.route("/api/run-region-analyses", methods=["POST"])
def api_run_region_analyses():
    """Startet die LLM Region-Analyse fuer alle Regionen."""
    try:
        result = engine.run_region_analyses()
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


def _format_region_analyses_flat(region_analyses: dict, loaded_at: Optional[str], allowed_dates: set) -> dict:
    """Baut die flache Region-Analysen-Repraesentation fuer /api/region-analyses."""
    flat: dict = {}
    for rid, days in region_analyses.items():
        flat[rid] = {}
        for date_str, entry in days.items():
            if date_str not in allowed_dates:
                continue
            safety = entry.get("safety", {})
            fly = entry.get("flyability", {})
            fly_status = entry.get("fly_status", "")
            ss = safety.get("safety_status", entry.get("safety_status", "error"))
            doc = {
                "region_id": rid,
                "region_name": entry.get("region_name", rid),
                "date": date_str,
                "status": entry.get("status", "error"),
                "safety_status": ss,
                "safe_window": safety.get("safe_window", entry.get("safe_window", "keins")),
                "best_window": entry.get("best_window", "?"),
                "safety_feedback": safety.get("summary", entry.get("summary", "")),
                "foehn_risk": safety.get("foehn_risk", entry.get("foehn_risk", "none")),
                "wind_summary": safety.get("wind_summary", entry.get("wind_summary", "")),
                "updated_at": loaded_at,
                "experience_rating": int(entry.get("experience_rating", 1) or 1),
                "is_conditional": bool(entry.get("is_conditional", False)),
            }
            # RATING_ARCHITECTURE v2.0
            for k in ("safety_rating",):
                v = entry.get(k)
                if v is not None:
                    doc[k] = v
            for key in ("no_go_reasons", "caution_notes"):
                val = safety.get(key, entry.get(key, []))
                doc[key] = json.dumps(val, ensure_ascii=False) if isinstance(val, list) else str(val)
            for lbl_key in ("primary_no_go", "primary_caution", "primary_reducer", "primary_booster"):
                doc[lbl_key] = safety.get(lbl_key) or None
            if ss in ("safe", "conditional"):
                # Fallback aus entry top-level wenn fly leer (Region-Cache hat
                # recommendation oft direkt top-level, kein flyability nested).
                doc["recommendation"] = fly.get("recommendation") or entry.get("recommendation", "")
                doc["flyability_feedback"] = doc["recommendation"]
                doc["peak_climb_rate"] = fly.get("peak_climb_rate") or entry.get("peak_climb_rate", 0)
                doc["flight_type"] = fly.get("flight_type") or entry.get("flight_type", "")
                fn = fly.get("flyability_notes") or entry.get("flyability_notes")
                if fn:
                    doc["flyability_notes"] = fn
            else:
                doc["fly_error"] = entry.get("fly_error", "")
            hn = safety.get("hazard_notes") or entry.get("hazard_notes")
            if hn:
                doc["hazard_notes"] = hn
            # Tag-System v4 (siehe docs/TAGS.md): tags + start_window durchreichen
            for k in ("tags", "start_window"):
                v = entry.get(k)
                if isinstance(v, list):
                    doc[k] = v
            flat[rid][date_str] = doc
    return flat


@app.route("/api/region-analyses")
def api_region_analyses():
    """Gibt Region-Analysen im flachen Format zurück.

    Wenn die Test-Ansicht aktiv ist, kommen die Daten aus
    `data/test_runs/latest/region_analyses.json` statt aus dem Live-Cache.
    """
    from engine import test_mode
    allowed_dates = _allowed_date_strs(current_max_days())

    if test_mode.is_view_active():
        _, region_analyses, mtime = test_mode.load_test_run_analyses()
        loaded_at = mtime.isoformat() if mtime else None
        flat = _format_region_analyses_flat(region_analyses, loaded_at, allowed_dates)
        return jsonify({
            "region_analyses": flat,
            "analyses_count": len(flat),
            "_test_view": True,
        })

    loaded_at = engine.region_analyses_loaded_at.isoformat() if engine.region_analyses_loaded_at else None
    flat = _format_region_analyses_flat(engine.region_analyses, loaded_at, allowed_dates)
    return jsonify({"region_analyses": flat, "analyses_count": len(flat)})


import queue as _queue_mod

# ── Analyse-State: Background-Thread + Event-Queue ──
# Die Analyse laeuft in einem eigenen Thread und pusht Events in eine Queue.
# Der SSE-Endpoint liest aus der Queue. Wenn der Client disconnected, laeuft
# die Analyse trotzdem weiter. Der Polling-Endpoint kann den Status abfragen.
_analysis_lock = threading.Lock()
_analysis_running = False
_analysis_completed = False
_analysis_error = None
_analysis_result = None
_analysis_queue = None  # queue.Queue — wird bei Start erstellt


def _run_analysis_in_background(eng, q):
    """Laeuft in eigenem Thread, pusht Events in die Queue."""
    global _analysis_running, _analysis_completed, _analysis_error, _analysis_result
    try:
        for evt in eng.run_all_analyses_stream():
            q.put(evt)
            # Bei done-Event: Ergebnis cachen
            if evt.get("event") == "done":
                data = evt.get("data", {})
                rs = data.get("region_stats") or {}
                ss = data.get("spot_stats") or {}
                _analysis_result = {
                    "regions_count": rs.get("regions_count", 0),
                    "spots_count": ss.get("spots_count", 0),
                    "total_calls": data.get("total_calls", 0),
                }
                _analysis_completed = True
    except Exception as e:
        logger.exception("[ANALYSIS-BG] Fehler im Analyse-Thread")
        q.put({"event": "error", "data": {"message": str(e)}})
        _analysis_error = str(e)
    finally:
        q.put(None)  # Sentinel: "fertig"
        _analysis_running = False
        logger.info("[ANALYSIS-BG] Analyse-Thread beendet (completed=%s)", _analysis_completed)


@app.route("/api/analyses-status")
def api_analyses_status():
    """Polling-Endpoint: Status der laufenden/letzten Analyse."""
    if _analysis_running:
        return jsonify({"running": True, "completed": False})
    if _analysis_completed and _analysis_result:
        return jsonify({
            "running": False, "completed": True,
            "regions_count": _analysis_result.get("regions_count", 0),
            "spots_count": _analysis_result.get("spots_count", 0),
            "total_calls": _analysis_result.get("total_calls", 0),
        })
    return jsonify({"running": False, "completed": False,
                     "error": _analysis_error})


@app.route("/api/run-all-analyses-stream")
def api_run_all_analyses_stream():
    """SSE-Endpoint: Startet Analyse im Background-Thread, streamt Events aus Queue."""
    global _analysis_running, _analysis_completed, _analysis_error, _analysis_result, _analysis_queue

    with _analysis_lock:
        if _analysis_running:
            logger.warning("[SSE] Analyse laeuft bereits, lehne zweiten Request ab")
            return Response(
                "event: error\ndata: {\"message\": \"Analyse läuft bereits\"}\n\n",
                mimetype="text/event-stream",
                headers={"Cache-Control": "no-cache"},
            )

        _analysis_running = True
        _analysis_completed = False
        _analysis_error = None
        _analysis_result = None
        _analysis_queue = _queue_mod.Queue()

    # Analyse in Background-Thread starten
    t = threading.Thread(
        target=_run_analysis_in_background,
        args=(engine, _analysis_queue),
        daemon=True,
    )
    t.start()

    def generate():
        yield "retry: 300000\n\n"
        try:
            while True:
                try:
                    evt = _analysis_queue.get(timeout=15)
                except _queue_mod.Empty:
                    # Heartbeat wenn Queue leer (Thread arbeitet noch)
                    if not _analysis_running:
                        break
                    yield "event: heartbeat\ndata: {}\n\n"
                    continue
                if evt is None:
                    break  # Sentinel: Thread ist fertig
                event_type = evt.get("event", "message")
                if event_type == "heartbeat":
                    yield "event: heartbeat\ndata: {}\n\n"
                    continue
                data = evt.get("data", {})
                yield f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        except GeneratorExit:
            logger.warning("[SSE] Client disconnected — Analyse laeuft im Background weiter")
        except Exception as e:
            logger.exception("[SSE] analyses stream Fehler")
            yield f"event: error\ndata: {json.dumps({'message': str(e)}, ensure_ascii=False)}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def _run_single_stream_in_background(eng, q, stream_attr, done_event):
    """Konsumiert einen einzelnen Analyse-Stream (Spots ODER Regionen) im Thread.

    stream_attr: 'run_spot_analyses_stream' oder 'run_region_analyses_stream'.
    done_event:  'spot_done' bzw. 'region_done' — nach dem cachen wir Counts.
    """
    global _analysis_running, _analysis_completed, _analysis_error, _analysis_result
    try:
        gen = getattr(eng, stream_attr)()
        for evt in gen:
            q.put(evt)
            if evt.get("event") == done_event:
                data = evt.get("data", {})
                _analysis_result = {
                    "spots_count": data.get("spots_count", 0),
                    "regions_count": data.get("regions_count", 0),
                    "results_count": data.get("results_count", 0),
                }
                _analysis_completed = True
    except Exception as e:
        logger.exception("[ANALYSIS-BG] Fehler im Analyse-Thread (%s)", stream_attr)
        q.put({"event": "error", "data": {"message": str(e)}})
        _analysis_error = str(e)
    finally:
        q.put(None)
        _analysis_running = False
        logger.info("[ANALYSIS-BG] %s beendet (completed=%s)", stream_attr, _analysis_completed)


def _start_single_analysis_stream(stream_attr, done_event):
    """Gemeinsame Logik fuer Spot- und Region-SSE-Streams."""
    global _analysis_running, _analysis_completed, _analysis_error, _analysis_result, _analysis_queue

    with _analysis_lock:
        if _analysis_running:
            return Response(
                "event: error\ndata: {\"message\": \"Eine Analyse laeuft bereits\"}\n\n",
                mimetype="text/event-stream",
                headers={"Cache-Control": "no-cache"},
            )
        _analysis_running = True
        _analysis_completed = False
        _analysis_error = None
        _analysis_result = None
        _analysis_queue = _queue_mod.Queue()

    t = threading.Thread(
        target=_run_single_stream_in_background,
        args=(engine, _analysis_queue, stream_attr, done_event),
        daemon=True,
    )
    t.start()

    def generate():
        yield "retry: 300000\n\n"
        try:
            while True:
                try:
                    evt = _analysis_queue.get(timeout=15)
                except _queue_mod.Empty:
                    if not _analysis_running:
                        break
                    yield "event: heartbeat\ndata: {}\n\n"
                    continue
                if evt is None:
                    break
                event_type = evt.get("event", "message")
                if event_type == "heartbeat":
                    yield "event: heartbeat\ndata: {}\n\n"
                    continue
                data = evt.get("data", {})
                yield f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
        except GeneratorExit:
            logger.warning("[SSE] Client disconnected — Analyse laeuft im Background weiter")
        except Exception as e:
            logger.exception("[SSE] single analysis stream Fehler")
            yield f"event: error\ndata: {json.dumps({'message': str(e)}, ensure_ascii=False)}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.route("/api/run-analyses-stream")
def api_run_analyses_stream():
    """SSE-Endpoint: startet Spot-Analyse im Background-Thread, streamt Progress."""
    return _start_single_analysis_stream("run_spot_analyses_stream", "spot_done")


@app.route("/api/run-region-analyses-stream")
def api_run_region_analyses_stream():
    """SSE-Endpoint: startet Region-Analyse im Background-Thread, streamt Progress."""
    return _start_single_analysis_stream("run_region_analyses_stream", "region_done")


@app.route("/api/regionen-polygone")
def api_regionen_polygone():
    """Region-GeoJSON angereichert mit Analyse-Daten fuer Karten-Faerbung."""
    geojson = get_all_regions_geojson()
    # Analyse-Status an Features anhaengen
    for feature in geojson.get("features", []):
        rid = feature.get("properties", {}).get("id")
        if rid and rid in engine.region_analyses:
            feature["properties"]["analyses"] = engine.region_analyses[rid]
    return jsonify(geojson)


@app.route("/api/regionen-precip-refpoints")
def api_regionen_precip_refpoints():
    """Niederschlags-Referenzpunkte (16 pro Region, CVT-verteilt).

    Wird nur fuer die Niederschlags-Aggregation verwendet (Coverage-Stat
    fuer widespread/scattered/isolated). Geometrie und Polygon-Daten stehen
    NICHT in dieser Datei — nur die Punkte.
    """
    path = os.path.join(os.path.dirname(__file__), "data", "regionen_referenzpunkte_precip.geojson")
    if not os.path.exists(path):
        return jsonify({"type": "FeatureCollection", "features": []})
    with open(path, "r", encoding="utf-8") as f:
        return jsonify(json.load(f))


@app.route("/api/refresh-spots", methods=["POST"])
def api_refresh_spots():
    """Laedt Spots neu aus CSV."""
    try:
        count = engine.reload_spots()
        return jsonify({"success": True, "spots_count": count})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/refresh-weather", methods=["POST"])
def api_refresh_weather():
    """Erzwingt einen Neustart des Wetter-Downloads und baut den Kontext neu.

    Fix #1+B: Erkennt stille Stale-Returns von fetch_all_spots() via expliziten
    `engine.last_refresh_stale` Flag (gesetzt in chat_engine.refresh_weather()).
    Wenn der Refresh fehlschlug, kommt schnell ein HTTP 503 + ehrlicher Reason
    zurück — statt fälschlicher Erfolgsmeldung nach Minuten von Retry-Wartezeit.
    """
    try:
        engine.refresh_weather(force=True)
        spot_names = [k for k in engine.weather_data.keys() if not k.startswith("_")]

        if len(spot_names) == 0:
            return jsonify({
                "success": False,
                "stale": True,
                "reason": "no_data",
                "error": "API-Tageslimit erreicht. Keine Wetterdaten verfügbar. Alle alten Analysen wurden zur Sicherheit gelöscht. Bitte morgen erneut versuchen."
            }), 503

        new_ts = engine.weather_data.get("_meta", {}).get("last_updated")

        # Fix B: Expliziter Stale-Flag aus dem Engine. Setzt refresh_weather()
        # wenn fetch_all_spots() stille auf den alten Cache zurückgefallen ist.
        if getattr(engine, "last_refresh_stale", False):
            reason = getattr(engine, "last_refresh_status_reason", "unknown") or "unknown"
            reason_msgs = {
                "api_pre_check_failed": "Open-Meteo API nicht erreichbar (Pre-Check fehlgeschlagen)",
                "daily_limit_exceeded": "Open-Meteo Tageslimit erreicht",
            }
            human_reason = reason_msgs.get(reason)
            if not human_reason:
                if reason.startswith("batch_failed"):
                    # Echten Fehler aus dem Reason extrahieren statt Rate-Limit zu vermuten
                    detail = reason.replace("batch_failed: ", "")
                    human_reason = f"Batch-Download fehlgeschlagen ({detail})"
                else:
                    human_reason = reason
            return jsonify({
                "success": False,
                "stale": True,
                "reason": reason,
                "error": (
                    "Wetter-Refresh fehlgeschlagen: " + human_reason + ". "
                    "Es werden weiterhin die alten (vortägigen) Daten verwendet — "
                    "die alten Analysen bleiben gültig."
                ),
                "last_updated": new_ts,
                "spots_count": len(spot_names),
            }), 503

        return jsonify({
            "success": True,
            "message": "Wetterdaten und Thermik neu berechnet.",
            "spots_count": len(spot_names),
            "last_updated": new_ts,
        })
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/admin/snapshot-weather", methods=["POST"])
@_require_admin
def api_admin_snapshot_weather():
    """Friert den Forecast fuer HEUTE in data/weather_archive/YYYY-MM-DD.json ein.

    Default: nur der aktuelle Tag (D=0). Forecast-Tage in der Zukunft werden
    bewusst NICHT gespeichert — wir validieren was ein Pilot am Flug-Morgen
    vor sich hatte, kein D+3-Forecast der spaeter revidiert wird.

    Verhalten: ueberschreibt IMMER. Damit reflektiert der Snapshot stets den
    juengsten Stand von Wetter-Refresh + LLM-Analysen.

    Optionaler Body {"date": "YYYY-MM-DD"} fuer manuelles Backfill eines
    spezifischen Tags im aktuellen Forecast-Fenster.
    """
    try:
        from scripts.snapshot_weather import build_snapshots, write_snapshots

        body = request.get_json(silent=True) or {}
        target_date = body.get("date") or None

        snapshots = build_snapshots(target_date=target_date, all_days=False)
        if not snapshots:
            return jsonify({
                "success": False,
                "error": "Kein Snapshot moeglich — Forecast-Fenster leer oder Datum nicht verfuegbar.",
            }), 500

        write_snapshots(snapshots)

        first = next(iter(snapshots.values()))
        spots_count = len(first["spots"])
        regions_count = len(first["regions"])
        spots_with_analysis = sum(
            1 for s in first["spots"].values() if s.get("analysis")
        )

        return jsonify({
            "success": True,
            "message": f"Snapshot aktualisiert fuer {', '.join(sorted(snapshots.keys()))}.",
            "spots_count": spots_count,
            "regions_count": regions_count,
            "spots_with_analysis": spots_with_analysis,
            "dates": sorted(snapshots.keys()),
            "results_count": len(snapshots),
        })
    except Exception as e:
        logger.exception("api_admin_snapshot_weather failed")
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# STATUS API (Debug)
# ============================================================================

@app.route("/api/status")
def api_status():
    spot_names = [k for k in engine.weather_data.keys() if k != "_meta"]
    return jsonify({
        "weather_loaded": bool(engine.weather_data),
        "spots_count": len(engine.spots),
        "weather_spots": spot_names,
        "weather_loaded_at": engine.weather_loaded_at.isoformat() if engine.weather_loaded_at else None,
        "analyses_count": len(engine.spot_analyses),
        "analyses_loaded_at": engine.analyses_loaded_at.isoformat() if engine.analyses_loaded_at else None,
    })


def _tier_thresholds():
    """Single source of truth for meteogram color tiers.

    Four metrics, each with WARN (calm→caution) and DANGER (caution→danger)
    thresholds in km/h, mirroring the Python tag logic in weather_context.py.
    Frontend uses these to color cells consistently with the LLM rating.
    """
    return {
        "ground_wind": {"warn": config.WIND_WARN_KMH, "danger": config.WIND_DANGER_KMH},
        "ground_gust": {"warn": config.GUST_WARN_KMH, "danger": config.GUST_DANGER_KMH},
        "aloft_wind": {"warn": config.WIND_WARN_KMH, "danger": config.WIND_DANGER_KMH},
        "aloft_gust": {"warn": config.GUST_WARN_KMH, "danger": config.GUST_DANGER_KMH},
    }


@app.route("/api/thresholds")
def api_thresholds():
    return jsonify({"tiers": _tier_thresholds()})


# ============================================================================
# STATIONS API (Bias-Korrektur)
# ============================================================================

@app.route("/api/stations/status")
def api_stations_status():
    """Übersicht: Stationen, Paare, Bias pro Spot."""
    if not engine.station_manager:
        return jsonify({"error": "StationManager nicht initialisiert"}), 503
    try:
        status = engine.station_manager.get_status()
        return jsonify(status)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/stations/discover", methods=["POST"])
def api_stations_discover():
    """Stationen neu suchen (manuell)."""
    if not engine.station_manager:
        return jsonify({"error": "StationManager nicht initialisiert"}), 503
    try:
        count = engine.station_manager.discover_stations()
        return jsonify({"success": True, "mappings_count": count})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/stations/collect", methods=["POST"])
def api_stations_collect():
    """Beobachtungen holen (manuell)."""
    if not engine.station_manager:
        return jsonify({"error": "StationManager nicht initialisiert"}), 503
    try:
        count = engine.station_manager.collect_observations()
        return jsonify({"success": True, "observations_count": count})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


# ============================================================================
# SPOTS API
# ============================================================================

@app.route("/api/spots")
def api_spots():
    return jsonify(engine.get_spots_geojson())


@app.route("/api/regionen")
def api_regionen():
    """Gibt alle Regionen als GeoJSON FeatureCollection zurück (für Karten-Overlay)."""
    return jsonify(get_all_regions_geojson())


@app.route("/api/osm_peaks/<tier>")
def api_osm_peaks(tier):
    """Serviert die OSM-Peaks GeoJSON-Files (major | minor).

    Quelle: scripts/fetch_osm_peaks.py (Overpass-API → data/osm_peaks_*.geojson).
    Daten aendern sich faktisch nie — long cache.
    """
    if tier not in ("major", "minor"):
        return jsonify({"error": "tier must be 'major' or 'minor'"}), 404
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    resp = send_from_directory(data_dir, f"osm_peaks_{tier}.geojson",
                               mimetype="application/geo+json")
    # Berge bewegen sich nicht — aggressiv cachen (1 Woche), Browser nutzt If-Modified-Since
    resp.headers["Cache-Control"] = "public, max-age=604800"
    return resp


def _group_chart_by_day(chart_data):
    """Gruppiert chart_data (wind/precipitation/thermik/cloudbase) nach Tagen (heute+zukunft)."""
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    dates = set()
    for entry in chart_data.get("wind", []):
        try:
            date_str = datetime.fromisoformat(entry["time"]).strftime("%Y-%m-%d")
            if date_str >= today_str:
                dates.add(date_str)
        except Exception:
            pass
    max_date_str = (now.date() + timedelta(days=config.FORECAST_DAYS - 1)).strftime("%Y-%m-%d")
    sorted_dates = [d for d in sorted(dates) if d <= max_date_str]
    by_day = {d: {"wind": [], "precipitation": [], "thermik": [], "cloudbase": []} for d in sorted_dates}
    for key in ("wind", "precipitation", "thermik", "cloudbase"):
        for entry in chart_data.get(key, []):
            try:
                date_str = datetime.fromisoformat(entry["time"]).strftime("%Y-%m-%d")
                if date_str in by_day:
                    by_day[date_str][key].append(entry)
            except Exception:
                pass
    return sorted_dates, by_day


def _group_profiles_by_day(alt_data):
    """Gruppiert Höhenwind-Profile nach Tagen (heute+zukunft)."""
    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")
    by_day = {}
    for profile in alt_data.get("profiles", []):
        try:
            dt = datetime.fromisoformat(profile["time"])
            date_str = dt.strftime("%Y-%m-%d")
            if date_str >= today_str:
                if date_str not in by_day:
                    by_day[date_str] = []
                by_day[date_str].append({"hour": dt.hour, "profiles": profile["levels"]})
        except Exception:
            pass
    max_date_str = (now.date() + timedelta(days=config.FORECAST_DAYS - 1)).strftime("%Y-%m-%d")
    sorted_dates = [d for d in sorted(by_day.keys()) if d <= max_date_str]
    by_day = {d: by_day[d] for d in sorted_dates if d in by_day}
    return sorted_dates, by_day


def _safe_float(v):
    return float(v) if v is not None else None


def _ground_wind_by_day(hourly_data, elevation_m, sorted_dates, ch1=False):
    """Extrahiert Bodenwind (10m, terrain-korrigiert) pro Tag/Stunde.

    Dies ist der sicherheitsrelevante Startwind — nicht der freie Höhenwind.
    Open-Meteo `wind_direction_10m` ist bereits terrain-korrigiert (Talwind,
    Hangeffekte via ICON Surface Scheme), `wind_direction_XhPa` nicht.
    Bei ch1=True werden CH1-Modellwerte als primäre Felder geliefert.
    """
    suffix = "_ch1" if ch1 else ""
    ws_key = f"wind_speed_10m{suffix}"
    wd_key = f"wind_direction_10m{suffix}"
    wg_key = f"wind_gusts_10m{suffix}"
    result = {d: [] for d in sorted_dates}
    if not hourly_data:
        return result
    for timestamp, hd in hourly_data.items():
        try:
            dt = datetime.fromisoformat(timestamp)
        except Exception:
            continue
        date_str = dt.strftime("%Y-%m-%d")
        if date_str not in result:
            continue
        ws = hd.get(ws_key)
        wd = hd.get(wd_key)
        wg = hd.get(wg_key)
        if ws is None and wd is None and wg is None:
            continue
        result[date_str].append({
            "hour": dt.hour,
            "wind_speed": _safe_float(ws),
            "wind_direction": _safe_float(wd),
            "wind_gusts": _safe_float(wg),
            "elevation_m": elevation_m,
        })
    for d in result:
        result[d].sort(key=lambda x: x["hour"])
    return result


def _stale_meta():
    """Returns (last_updated, is_stale) from weather cache metadata."""
    cache_meta = engine.weather_data.get("_meta", {}) if engine.weather_data else {}
    return cache_meta.get("last_updated"), None  # is_stale set by caller from len(dates)


@app.route("/api/region-weather/<region_id>")
def api_region_weather(region_id):
    """Wetterdaten fuer eine Region, formatiert fuer Meteogramm."""
    region_data = engine.region_weather_data.get(region_id)
    if not region_data:
        return jsonify({"error": f"Region '{region_id}' nicht gefunden"}), 404

    hourly_data = region_data.get("hourly_data", {})
    pressure_level_data = region_data.get("pressure_level_data", {})
    elevation_ref = region_data.get("elevation_ref", 1200)
    spotmedian_override = region_data.get("thermals_spotmedian")

    chart_data = format_data_for_charts(hourly_data, pressure_level_data, elevation_ref=elevation_ref,
                                        region_id=region_id, spotmedian_override=spotmedian_override)

    # Regionen haben keine Böen (Apr 2026): gusts = null.
    # Frontend (meteogram.js) interpretiert null korrekt: hasRealGust=false →
    # keine Gust-Label, keine Gust-Warnungen. Tooltip zeigt "Böen: -".
    for w in chart_data.get("wind", []):
        w["gusts"] = None

    sorted_dates, by_day = _group_chart_by_day(chart_data)
    last_updated, _ = _stale_meta()
    sorted_dates, by_day = _gate_forecast(sorted_dates, by_day)

    return jsonify({
        "region_id": region_id,
        "region_name": region_data.get("region_name", region_id),
        "elevation_ref": elevation_ref,
        "dates": sorted_dates,
        "data": by_day,
        "stale": len(sorted_dates) < current_max_days(),
        "last_updated": last_updated,
        "expected_days": current_max_days(),
        "is_region": True,
        "thresholds": _tier_thresholds(),
        # Quellen-Tracking pro Tag (ch1/ch2/d2/eu) — siehe docs/WETTERMODELLE.md.
        "data_sources": region_data.get("data_sources", {}),
    })


@app.route("/api/region-altitude-wind/<region_id>")
def api_region_altitude_wind(region_id):
    """Hoehenwind-Profile fuer eine Region, formatiert fuer Meteogramm."""
    region_data = engine.region_weather_data.get(region_id)
    if not region_data:
        return jsonify({"error": f"Region '{region_id}' nicht gefunden"}), 404

    pressure_level_data = region_data.get("pressure_level_data", {})
    hourly_data = region_data.get("hourly_data", {})
    elevation_ref = region_data.get("elevation_ref", 1200)

    # Region-Höhenprofil: KEINE Böen-Addition am Höhenprofil.
    # Begründung: Die Referenzhöhe ist ein einzelner Punkt, während die
    # Startplätze innerhalb der Region stark variierende Höhen haben.
    # Ein Single-Anchor + Gauss-Kernel erzeugt eine sichtbare "Böen-Beule"
    # an der Referenzhöhe (und Dämpfung darüber/darunter) — das verrät
    # die Berechnungsstelle optisch und ist physikalisch für eine Region
    # nicht aussagekräftig. Altitude-Böen sind nur für einzelne Startplätze
    # sinnvoll (api_altitude_wind), wo das Ankerlevel = Boden ist.
    # Das Bodenband bleibt erhalten (separater _ground_wind_by_day-Pfad).
    alt_data = format_altitude_wind_for_charts(
        pressure_level_data, region_id=region_id,
    )

    sorted_dates, by_day = _group_profiles_by_day(alt_data)
    ground_wind = _ground_wind_by_day(hourly_data, elevation_ref, sorted_dates)
    # Regionen haben keine Böen (Apr 2026): Bodenband ohne wind_gusts.
    for day_entries in ground_wind.values():
        for e in day_entries:
            e["wind_gusts"] = None
    last_updated, _ = _stale_meta()
    sorted_dates, by_day, ground_wind = _gate_forecast(sorted_dates, by_day, ground_wind)

    return jsonify({
        "region_id": region_id,
        "elevation_m": elevation_ref,
        "dates": sorted_dates,
        "data": by_day,
        "ground_wind": ground_wind,
        "stale": len(sorted_dates) < current_max_days(),
        "last_updated": last_updated,
        "expected_days": current_max_days(),
        "is_region": True,
    })


# ============================================================================
# WEATHER API (für Meteogramm)
# ============================================================================

def _ensure_spot_weather(spot_name):
    """
    Stellt sicher, dass Wetterdaten für den Spot vorhanden sind.
    Falls nicht (z.B. vorheriger Fetch fehlgeschlagen): On-Demand-Fetch.
    """
    if spot_name in engine.weather_data:
        return engine.weather_data[spot_name]
    spot = next((s for s in engine.spots if s["name"] == spot_name), None)
    if not spot:
        return None
    result = get_weather_for_location(spot_name, spot["latitude"], spot["longitude"])
    if result is None or result[0] is None:
        return None
    hourly_data, pressure_level_data, ref_points = result
    engine.weather_data[spot_name] = {
        "latitude": spot["latitude"],
        "longitude": spot["longitude"],
        "elevation_m": spot["elevation_m"],
        "hourly_data": hourly_data,
        "pressure_level_data": pressure_level_data,
        "reference_points": ref_points,
    }
    return engine.weather_data[spot_name]


@app.route("/api/weather/<spot_name>")
def api_weather(spot_name):
    """Wetterdaten für einen Spot, formatiert für D3.js Meteogramm."""
    spot_data = _ensure_spot_weather(spot_name)
    if not spot_data:
        return jsonify({"error": f"Spot '{spot_name}' nicht gefunden"}), 404

    hourly_data = spot_data.get("hourly_data", {})
    pressure_level_data = spot_data.get("pressure_level_data", {})
    elevation_m = spot_data.get("elevation_m", 850)

    # Finde den Spot für slope_azimuth/angle und Region-ID
    spot_info = None
    for s in engine.spots:
        if s["name"] == spot_name:
            spot_info = s
            break

    spot_region = find_region_for_point(spot_data.get("latitude", 0), spot_data.get("longitude", 0))
    spot_region_id = spot_region["id"] if spot_region else None

    chart_data = format_data_for_charts(
        hourly_data, pressure_level_data,
        elevation_ref=elevation_m,
        slope_azimuth=spot_info.get("slope_azimuth") if spot_info else None,
        slope_angle=spot_info.get("slope_angle") if spot_info else None,
        region_id=spot_region_id,
    )

    sorted_dates, by_day = _group_chart_by_day(chart_data)
    last_updated, _ = _stale_meta()
    sorted_dates, by_day = _gate_forecast(sorted_dates, by_day)

    return jsonify({
        "spot_name": spot_name,
        "elevation_m": elevation_m,
        "dates": sorted_dates,
        "data": by_day,
        "stale": len(sorted_dates) < current_max_days(),
        "last_updated": last_updated,
        "expected_days": current_max_days(),
        "windrichtung": (spot_info.get("windrichtung") if spot_info else None),
        "ideal_wind_max": (spot_info.get("ideal_wind_max") if spot_info else None),
        "thresholds": _tier_thresholds(),
        # Quellen-Tracking pro Tag (ch1 / ch2 / d2 / eu) — siehe
        # _process_spot_weather + docs/WETTERMODELLE.md. Frontend rendert
        # daraus den Modell-Badge im Meteogramm-Header.
        "data_sources": spot_data.get("data_sources", {}),
    })


@app.route("/api/altitude-wind/<spot_name>")
def api_altitude_wind(spot_name):
    """Höhenwind-Profile für einen Spot, formatiert für Meteogramm."""
    spot_data = _ensure_spot_weather(spot_name)
    if not spot_data:
        return jsonify({"error": f"Spot '{spot_name}' nicht gefunden"}), 404

    pressure_level_data = spot_data.get("pressure_level_data", {})
    hourly_data = spot_data.get("hourly_data", {})
    elevation_m = spot_data.get("elevation_m")

    # Region-ID für Terrain-Typ Lookup
    region_id = None
    region = find_region_for_point(spot_data.get("latitude", 0), spot_data.get("longitude", 0))
    if region:
        region_id = region["id"]

    # Surface anchor: Bodenböen als Ankerpunkt ins Höhenprofil einspeisen
    # (gleiche Logik wie Region-Route — ohne dies fehlt OI-Korrektur + Running Max)
    surface_anchor_by_time = {}
    ch1_anchor_by_time = {}
    has_ch1 = False
    for timestamp, hour_data in hourly_data.items():
        gust = hour_data.get("wind_gusts_10m")
        ws = hour_data.get("wind_speed_10m")
        wd = hour_data.get("wind_direction_10m")
        if gust is not None and ws is not None:
            surface_anchor_by_time[timestamp] = {
                "elevation_m": elevation_m,
                "gust_kmh": float(gust),
                "wind_speed_kmh": float(ws),
                "wind_direction_10m": float(wd) if wd is not None else None,
            }
        # CH1 surface anchor (falls vorhanden)
        ch1_gust = hour_data.get("wind_gusts_10m_ch1")
        ch1_ws = hour_data.get("wind_speed_10m_ch1")
        ch1_wd = hour_data.get("wind_direction_10m_ch1")
        if ch1_gust is not None and ch1_ws is not None:
            has_ch1 = True
            ch1_anchor_by_time[timestamp] = {
                "elevation_m": elevation_m,
                "gust_kmh": float(ch1_gust),
                "wind_speed_kmh": float(ch1_ws),
                "wind_direction_10m": float(ch1_wd) if ch1_wd is not None else None,
            }

    alt_data = format_altitude_wind_for_charts(
        pressure_level_data, hourly_data, elevation_m, region_id,
        surface_anchor_by_time=surface_anchor_by_time,
    )

    sorted_dates, by_day = _group_profiles_by_day(alt_data)
    ground_wind = _ground_wind_by_day(hourly_data, elevation_m, sorted_dates)
    last_updated, _ = _stale_meta()

    # CH1-Höhenprofil: gleiche PL-Daten, aber CH1-Bodenböen als Anker.
    # WICHTIG 1: Deep-copy der PL-Daten, da format_altitude_wind_for_charts
    #   die Level-Dicts mutiert (wind_gusts, turbulence_excess etc.)
    # WICHTIG 2: hourly_data muss CH1-Oberflächenwerte enthalten, damit
    #   estimate_altitude_gusts (Step 1 in format_altitude_wind_for_charts)
    #   das CH1-Böenprofil als Background berechnet. Sonst wird der D2-
    #   Background per max() beibehalten und CH1 < D2 wird ignoriert.
    ch1_by_day = None
    ch1_ground_wind = None
    if has_ch1:
        # hourly_data mit CH1-Surface-Werten für Step 1
        ch1_hourly = {}
        for ts, hd in hourly_data.items():
            ch1_hd = dict(hd)  # shallow copy pro Stunde
            ch1_ws = hd.get("wind_speed_10m_ch1")
            ch1_g = hd.get("wind_gusts_10m_ch1")
            ch1_wd = hd.get("wind_direction_10m_ch1")
            if ch1_ws is not None:
                ch1_hd["wind_speed_10m"] = ch1_ws
            if ch1_g is not None:
                ch1_hd["wind_gusts_10m"] = ch1_g
            if ch1_wd is not None:
                ch1_hd["wind_direction_10m"] = ch1_wd
            ch1_hourly[ts] = ch1_hd

        pl_copy = copy.deepcopy(pressure_level_data)
        ch1_alt_data = format_altitude_wind_for_charts(
            pl_copy, ch1_hourly, elevation_m, region_id,
            surface_anchor_by_time=ch1_anchor_by_time,
        )
        _, ch1_by_day = _group_profiles_by_day(ch1_alt_data)
        ch1_ground_wind = _ground_wind_by_day(
            hourly_data, elevation_m, sorted_dates, ch1=True,
        )

    sorted_dates, by_day, ground_wind, ch1_by_day_g, ch1_ground_wind_g = _gate_forecast(
        sorted_dates, by_day, ground_wind, ch1_by_day or {}, ch1_ground_wind or {},
    )
    if ch1_by_day is not None:
        ch1_by_day = ch1_by_day_g
    if ch1_ground_wind is not None:
        ch1_ground_wind = ch1_ground_wind_g

    return jsonify({
        "spot_name": spot_name,
        "elevation_m": elevation_m,
        "dates": sorted_dates,
        "data": by_day,
        "ground_wind": ground_wind,
        "data_ch1": ch1_by_day,
        "ground_wind_ch1": ch1_ground_wind,
        "stale": len(sorted_dates) < current_max_days(),
        "last_updated": last_updated,
        "expected_days": current_max_days(),
    })


# ============================================================================
# FÖHN API
# ============================================================================

@app.route("/api/foehn")
def api_foehn():
    """Föhn-Zeitreihe: stündliche Delta-P, Kammwind, Feuchte für Diagramm.

    Admin-only (passwortlos via config.ADMIN_EMAIL-Session)."""
    if not _is_admin():
        return jsonify({"error": "Föhndiagramm nur für Admin"}), 403
    raw = None
    if engine and engine.foehn_data:
        raw = engine.foehn_data
    else:
        raw = fetch_foehn_data(forecast_days=config.FORECAST_DAYS)

    if not raw:
        return jsonify({"error": "Föhn-Daten nicht verfügbar"}), 503

    nord = raw["nord"]
    sued = raw["sued"]
    h_nord = nord.get("hourly", {})
    h_sued = sued.get("hourly", {})
    times = h_nord.get("time", [])

    if not times:
        return jsonify({"error": "Keine Zeitreihe"}), 503

    now = datetime.now()
    today_str = now.strftime("%Y-%m-%d")

    by_day = {}
    for i, t in enumerate(times):
        try:
            dt = datetime.fromisoformat(t.replace("Z", "+00:00"))
        except Exception:
            continue

        date_str = dt.strftime("%Y-%m-%d")
        if date_str < today_str:
            continue

        p_nord = _safe_get(h_nord.get("pressure_msl"), i)
        p_sued = _safe_get(h_sued.get("pressure_msl"), i)
        delta_p = round(p_sued - p_nord, 1) if p_nord is not None and p_sued is not None else None

        wind_700 = _safe_get(h_nord.get("wind_speed_700hPa"), i)
        dir_700 = _safe_get(h_nord.get("wind_direction_700hPa"), i)
        rh_nord = _safe_get(h_nord.get("relative_humidity_2m"), i)

        # Determine level via evaluate_foehn
        ev = evaluate_foehn(nord, sued, time_index=i)

        entry = {
            "time": t,
            "hour": dt.hour,
            "delta_p": delta_p,
            "level": ev["level"],
            "crest_wind_kmh": round(wind_700, 0) if wind_700 is not None else None,
            "crest_dir_deg": round(dir_700, 0) if dir_700 is not None else None,
            "humidity_nord": round(rh_nord, 0) if rh_nord is not None else None,
        }

        if date_str not in by_day:
            by_day[date_str] = []
        by_day[date_str].append(entry)

    sorted_dates = sorted(by_day.keys())
    sorted_dates, by_day = _gate_forecast(sorted_dates, by_day)

    return jsonify({
        "dates": sorted_dates,
        "data": by_day,
        "thresholds": {
            "delta_p_caution": THRESHOLD_DELTA_P_CAUTION,
            "delta_p_danger": THRESHOLD_DELTA_P_DANGER,
            "humidity_low": THRESHOLD_HUMIDITY_LOW,
        },
        "stations": FOEHN_STATIONS,
    })


def _safe_get(arr, i):
    """Sicher einen Wert aus einer Liste holen."""
    if arr is None or not isinstance(arr, list) or i >= len(arr):
        return None
    return arr[i]


# ============================================================================
# DATA FORMATTING (adaptiert von uetliberg_ticker/web.py)
# ============================================================================

def format_data_for_charts(hourly_data, pressure_level_data=None, elevation_ref=None,
                           slope_azimuth=None, slope_angle=None, region_id=None,
                           spotmedian_override=None):
    """Formatiert Daten für D3.js Charts inkl. Thermik-Physik.

    spotmedian_override (Mai 2026): nur fuer Regionen. Ueberschreibt max_height /
    climb_rate / lcl pro Stunde mit Spot-Median. Siehe fetch_weather.py
    _compute_region_spotmedian_thermals fuer Motivation.
    """
    chart_data = {"wind": [], "precipitation": [], "thermik": [], "cloudbase": []}
    sorted_times = sorted(hourly_data.keys())

    elev_ref = elevation_ref if elevation_ref is not None else 850

    # Stateful Thermik-Berechnung über alle Stunden — identisch zu
    # _build_single_spot_context / _build_single_region_context, damit
    # Anzeige und LLM-Kontext dieselben Werte sehen.
    daily_thermals = compute_daily_thermals(
        hourly_data,
        pressure_level_data,
        elev_ref,
        config.PRESSURE_LEVELS,
        slope_azimuth=slope_azimuth,
        slope_angle=slope_angle,
        region_id=region_id,
        spotmedian_override=spotmedian_override,
    )

    for timestamp in sorted_times:
        data = hourly_data[timestamp]
        try:
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            time_str = dt.strftime("%Y-%m-%dT%H:%M:%S")

            # Wind
            wind_speed = data.get("wind_speed_10m")
            wind_gusts = data.get("wind_gusts_10m")
            wind_direction = data.get("wind_direction_10m")
            if wind_speed is not None and wind_direction is not None:
                chart_data["wind"].append({
                    "time": time_str,
                    "speed": wind_speed,
                    "gusts": wind_gusts if wind_gusts is not None else wind_speed,
                    "direction": wind_direction,
                    "speed_ch1": data.get("wind_speed_10m_ch1"),
                    "gusts_ch1": data.get("wind_gusts_10m_ch1"),
                    "direction_ch1": data.get("wind_direction_10m_ch1"),
                })

            # Niederschlag
            precipitation = data.get("precipitation", 0)
            precip_prob = data.get("precipitation_probability", 0)
            if precipitation is not None:
                chart_data["precipitation"].append({
                    "time": time_str,
                    "amount": precipitation,
                    "probability": precip_prob if precip_prob is not None else 0,
                    "weather_code": data.get("weather_code"),
                    # 16-RP Coverage-Klasse (widespread/scattered/isolated/dry)
                    # damit das Meteogramm pro Stunde die Tropfen-Anzahl variieren kann.
                    "klass": data.get("precipitation_class"),
                    "coverage": data.get("precipitation_coverage"),
                    "n_rps": data.get("precipitation_n_rps"),
                })

            # Thermik — aus stateful daily_thermals lesen
            cape = data.get("cape", 0)
            therm_climb = 0
            therm_rating = 0
            therm_max_h = None
            therm_lcl = None
            therm_diagnostics = {}
            therm_warnings = []

            therm = daily_thermals.get(timestamp)
            if therm and "error" not in therm:
                therm_climb = therm["climb_rate"]
                therm_rating = therm["rating"]
                therm_max_h = therm["max_height"]
                therm_lcl = therm.get("lcl")
                therm_diagnostics = therm.get("diagnostics", {})
                therm_warnings = therm.get("data_warnings", [])

            # TORN-Status (Thermik vom Höhenwind zerrissen) für die Anzeige.
            # Spiegelt die TQ-Tag-Logik der Rating-Pipeline (_thermal_quality_tags,
            # weather_context.py) auf der ROHEN max_height (vor dem Wolkenbasis-Cap
            # unten). Reine Anzeige: die Säule bleibt auf voller Höhe, das
            # Meteogramm markiert nur die zerrissenen Stunden. Die Produktiv-/
            # Working-Height-Kappung passiert unverändert im Rating-Pfad.
            torn_level = None
            if engine is not None and therm_climb and therm_max_h:
                try:
                    tq_tags, _tq_dbg = engine._thermal_quality_tags(
                        wind_speed_10m=data.get("wind_speed_10m"),
                        wind_gusts_10m=data.get("wind_gusts_10m"),
                        pl_data=(pressure_level_data or {}).get(timestamp, {}),
                        elevation_m=elev_ref,
                        thermal_top_m=therm_max_h,
                        climb_rate_ms=therm_climb,
                        region_id=region_id,
                    )
                    if "[THERMAL-TORN-UNUSABLE]" in tq_tags:
                        torn_level = "unusable"
                    elif "[THERMAL-TORN-DEGRADED]" in tq_tags:
                        torn_level = "degraded"
                except Exception:
                    torn_level = None

            # Wolkenbasis + Schichten
            cloud_base = data.get("cloud_base")
            cloud_cover = data.get("cloud_cover")
            cloud_cover_low = data.get("cloud_cover_low")
            cloud_cover_mid = data.get("cloud_cover_mid")
            cloud_cover_high = data.get("cloud_cover_high")

            # FLIEGBARKEITS-CAP: Thermik nicht ueber die Wolkenbasis anzeigen.
            # Bevorzugt tatsaechliche Wolkenbasis (Open-Meteo cloud_base, wenn Cumuli
            # existieren). Fallback: theoretische LCL (Bolton, aus Thermik-Modul).
            # Oberhalb beides: VFR-Flug nicht erlaubt -> nicht als fliegbar zaehlen.
            cloud_limit = None
            if cloud_base and cloud_base > elev_ref:
                cloud_limit = cloud_base
            elif therm_lcl and therm_lcl > elev_ref:
                cloud_limit = therm_lcl
            if therm_max_h and cloud_limit and therm_max_h > cloud_limit:
                therm_max_h = cloud_limit

            if cape is not None:
                chart_data["thermik"].append({
                    "time": time_str,
                    "cape": cape,
                    "climb_rate": therm_climb,
                    "rating": therm_rating,
                    "max_height": therm_max_h,
                    "lcl": therm_lcl,
                    "diagnostics": therm_diagnostics,
                    "data_warnings": therm_warnings,
                    # Thermik zerrissen (Höhenwind-Scherung) — nur Anzeige-Flag,
                    # Höhe bleibt unangetastet. None | "degraded" | "unusable".
                    "torn": torn_level is not None,
                    "torn_level": torn_level,
                })

            if cloud_base is not None or cloud_cover is not None:
                chart_data["cloudbase"].append({
                    "time": time_str,
                    "height": cloud_base,
                    "cover": cloud_cover,
                    "cover_low": cloud_cover_low,
                    "cover_mid": cloud_cover_mid,
                    "cover_high": cloud_cover_high,
                    "weather_code": data.get("weather_code"),
                })
        except Exception:
            continue

    return chart_data


def _interp_scalar(pts, x):
    """Linear interpolation of a scalar value from sorted (x, y) pairs."""
    if not pts:
        return 0
    if x <= pts[0][0]:
        return pts[0][1]
    if x >= pts[-1][0]:
        return pts[-1][1]
    for i in range(len(pts) - 1):
        if pts[i][0] <= x <= pts[i + 1][0]:
            dh = pts[i + 1][0] - pts[i][0]
            frac = (x - pts[i][0]) / dh if dh > 0 else 0
            return pts[i][1] + frac * (pts[i + 1][1] - pts[i][1])
    return pts[-1][1]


def _interp_ws(pts, x):
    """Linear interpolation of (wind_speed, direction, temperature) from sorted tuples."""
    if not pts:
        return 0, 0, 0
    if x <= pts[0][0]:
        return pts[0][1], pts[0][2], pts[0][3]
    if x >= pts[-1][0]:
        return pts[-1][1], pts[-1][2], pts[-1][3]
    for i in range(len(pts) - 1):
        if pts[i][0] <= x <= pts[i + 1][0]:
            lo, hi = pts[i], pts[i + 1]
            dh = hi[0] - lo[0]
            frac = (x - lo[0]) / dh if dh > 0 else 0
            return (
                lo[1] + frac * (hi[1] - lo[1]),
                lo[2] + frac * (hi[2] - lo[2]),
                lo[3] + frac * (hi[3] - lo[3]),
            )
    return pts[-1][1], pts[-1][2], pts[-1][3]


def _oi_gust_correction(grid_alts, grid_gusts, grid_ws, anchors, L_up, L_down):
    """Optimal Interpolation des Böen-Exzesses aus Anker-Beobachtungen.

    Der beobachtete Böen-Exzess (gust - wind) an Ankerpunkten wird per
    asymmetrischem Gauss-Kernel auf das Höhenprofil verteilt:
    - Aufwärts: terrain-abhängiger Kernel (L_up aus TERRAIN_OI_L_UP)
      Flach (mittelland): 1.0×H_g ≈ 350m (Oberflächenrauigkeit)
      Bergig (voralpen+): 1.3-1.5×H_g ≈ 550-750m (Turbulenz-Zerfallsskala,
      Letson et al. 2019)
    - Abwärts: enger Kernel (L_down = H_g, Turbulenz zerfällt schnell)

    Args:
        grid_alts: Liste der Grid-Höhen (m MSL)
        grid_gusts: Liste der Modell-Böen (km/h) auf dem Grid
        grid_ws: Liste der Wind-Geschwindigkeiten (km/h) auf dem Grid
        anchors: Liste [{elevation_m, gust_kmh, wind_speed_kmh}, ...]
        L_up: Korrelationslänge aufwärts (m), aus get_oi_scale_lengths()
        L_down: Korrelationslänge abwärts (m), typisch = H_g

    Returns:
        Liste der korrigierten Böen (km/h), gleiche Länge wie grid_alts
    """
    import math

    if not anchors or L_up <= 0:
        return list(grid_gusts)

    # Beobachteter Böen-Exzess an jedem Anker
    obs_excess = []
    for a in anchors:
        excess = max(0, a["gust_kmh"] - a.get("wind_speed_kmh", 0))
        obs_excess.append((a["elevation_m"], excess))

    corrected = []
    for z, gust_bg, ws in zip(grid_alts, grid_gusts, grid_ws):
        w_sum = 0.0
        excess_sum = 0.0
        for z_a, exc in obs_excess:
            dz = z - z_a
            # Asymmetrischer Kernel: breit aufwärts (BLH), eng abwärts (H_g)
            L = L_up if dz >= 0 else L_down
            w = math.exp(-(dz * dz) / (2 * L * L))
            w_sum += w
            excess_sum += w * exc
        excess_weighted = excess_sum / max(1.0, w_sum)
        gust_from_obs = ws + excess_weighted
        corrected.append(max(gust_bg, gust_from_obs))

    return corrected


def format_altitude_wind_for_charts(pressure_level_data, hourly_data=None, elevation_m=None,
                                    region_id=None, gust_anchors_by_time=None,
                                    surface_anchor_by_time=None):
    """Formatiert Höhenwind-Daten für D3.js Altitude Profile Chart.

    Args:
        pressure_level_data: Druckniveau-Daten pro Timestamp
        hourly_data: Stündliche Bodendaten (für wind_speed_10m, wind_gusts_10m, boundary_layer_height)
        elevation_m: Spot-Elevation in m MSL (für Höhenböen-Berechnung)
        region_id: Regions-ID für terrain_type Lookup (optional)
        gust_anchors_by_time: Dict {timestamp: [anchor, ...]} für Multi-Anchor-Modell (optional)
        surface_anchor_by_time: Dict {timestamp: {elevation_m, gust_kmh, wind_speed_kmh}}
            Referenzpunkt-Bodenböen als Ankerpunkt ins Höhenprofil (optional, für Regionen)
    """
    chart_data = {"profiles": []}
    sorted_times = sorted(pressure_level_data.keys())

    # Grid: 0-GRID_MAX in 250m steps, dynamisch nach Spot-Höhe.
    # Frontend (meteogram.js) rendert bei elevation>=1800m bis 5000m MSL —
    # ohne dynamischen GRID_MAX blieben obere Zellen leer (z.B. Laucheralp
    # 1981m verlor die Zeilen 4250-5000m MSL). Buffer = elevation + 3100m
    # gibt ≥3km Headroom über Startplatz bei alpinen Spots. Für Regionen
    # (kein elevation_m) Fallback 5500m (deckt Engadin Ober 2450m ab).
    GRID_STEP = 250
    if elevation_m is not None:
        GRID_MAX = max(4000, math.ceil((elevation_m + 3100) / GRID_STEP) * GRID_STEP)
    else:
        GRID_MAX = 5500

    for timestamp in sorted_times:
        data = pressure_level_data[timestamp]
        try:
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            profile = {"time": dt.isoformat(), "levels": []}

            for level in config.PRESSURE_LEVELS:
                height = data.get(f"geopotential_height_{level}hPa")
                wind_speed = data.get(f"wind_speed_{level}hPa")
                wind_direction = data.get(f"wind_direction_{level}hPa")
                temperature = data.get(f"temperature_{level}hPa")

                if height is not None:
                    profile["levels"].append({
                        "pressure": level,
                        "altitude": height,
                        "wind_speed": wind_speed if wind_speed is not None else 0.0,
                        "wind_direction": wind_direction if wind_direction is not None else 0,
                        "temperature": temperature if temperature is not None else 0,
                    })

            # Compute altitude gusts (turbulence risk T(z))
            if hourly_data and elevation_m is not None and profile["levels"]:
                surface = hourly_data.get(timestamp, {})
                anchors = gust_anchors_by_time.get(timestamp, []) if gust_anchors_by_time else []

                if anchors:
                    # Multi-Anchor-Modell: Spots als Böen-Ankerpunkte
                    profile["levels"] = estimate_altitude_gusts_multi_anchor(
                        anchors=anchors,
                        pressure_levels_data=profile["levels"],
                        elevation_ref=elevation_m,
                        boundary_layer_height=surface.get("boundary_layer_height"),
                        region_id=region_id,
                    )
                else:
                    # Fallback: Einzel-Referenzpunkt-Modell
                    profile["levels"] = estimate_altitude_gusts(
                        wind_speed_10m=surface.get("wind_speed_10m"),
                        wind_gusts_10m=surface.get("wind_gusts_10m"),
                        pressure_levels_data=profile["levels"],
                        elevation_m=elevation_m,
                        boundary_layer_height=surface.get("boundary_layer_height"),
                        region_id=region_id,
                    )

            # Surface anchor: re-grid onto 0-4000m and apply kernel-based gust correction.
            #
            # Method (kernel-weighted correction):
            # 1. Interpolate pressure-level model data onto regular grid
            # 2. Collect all anchor points (surface + spot anchors)
            # 3. Compute residuals: observed_gust - model_gust at each anchor
            # 4. Distribute corrections smoothly via Gaussian kernel.
            #    L_up = get_effective_L_up(...) — terrain-gewichteter BLH-Boost
            #    statt blindem max(L_up_terrain, BLH). Im Mittelland kein Boost
            #    (Reibungs-Skala), im Hochalpinen voller Boost (Schwerewellen).
            # 5. Result: model is pulled toward observations, no V-shape artifacts
            anchor = surface_anchor_by_time.get(timestamp) if surface_anchor_by_time else None
            if anchor and profile["levels"]:
                elev_anchor = anchor["elevation_m"]

                levels = sorted(profile["levels"], key=lambda l: l["altitude"])

                # Wind/dir/temp: Drucklevel-Daten (freie Atmosphäre) für die Höhe,
                # aber am Boden (0m AGL) wird der 10m-Bodenwind verwendet.
                # Grund: Open-Meteo Bodenwind ist terrain-korrigiert (Talwind/
                # Hangeffekte), während PL-Wind an gleicher Höhe freie Atmosphäre
                # zeigt. Für den Startplatz ist der Bodenwind die relevante Grösse.
                ws_pts = []
                for lv in levels:
                    ws_pts.append((
                        lv["altitude"],
                        lv.get("wind_speed", 0),
                        lv.get("wind_direction", 0),
                        lv.get("temperature", 0),
                    ))

                # Gust support points from gust_calculator (model background)
                gust_pts = sorted(
                    [(lv["altitude"], lv.get("wind_gusts", lv.get("wind_speed", 0)))
                     for lv in levels],
                    key=lambda x: x[0],
                )

                # Build grid: wind_speed/dir/temp + model gusts
                # Am Boden (0m AGL) wird der 10m-Bodenwind eingesetzt statt
                # PL-Interpolation — er reflektiert die realen Startbedingungen.
                sfc_ws = anchor.get("wind_speed_kmh")
                sfc_dir = anchor.get("wind_direction_10m")
                grid_alts = []
                grid_gusts_bg = []
                grid_ws = []
                grid_dir = []
                grid_temp = []
                for grid_alt in range(0, GRID_MAX + 1, GRID_STEP):
                    ws_val, dir_val, temp_val = _interp_ws(ws_pts, grid_alt)
                    gust_val = _interp_scalar(gust_pts, grid_alt)
                    # 0m AGL = Startplatz: Bodenwind statt PL-Interpolation
                    if grid_alt == 0 and sfc_ws is not None:
                        ws_val = sfc_ws
                    if grid_alt == 0 and sfc_dir is not None:
                        dir_val = sfc_dir
                    grid_alts.append(grid_alt)
                    grid_gusts_bg.append(gust_val)
                    grid_ws.append(ws_val)
                    grid_dir.append(dir_val)
                    grid_temp.append(temp_val)

                # OI-Anker: Böen-Exzess relativ zum freiatmosphärischen Wind
                # (nicht zum Boden-Wind). So wird der Exzess korrekt auf das
                # Drucklevel-Windprofil addiert ohne Doppelzählung.
                ws_free_atm = _interp_scalar(
                    [(p[0], p[1]) for p in ws_pts], elev_anchor
                )
                oi_anchors = [{
                    "elevation_m": elev_anchor,
                    "gust_kmh": anchor["gust_kmh"],
                    "wind_speed_kmh": ws_free_atm,
                }]
                spot_anchors = gust_anchors_by_time.get(timestamp, []) if gust_anchors_by_time else []
                for sa in spot_anchors:
                    sa_ws_free = _interp_scalar(
                        [(p[0], p[1]) for p in ws_pts], sa["elevation_m"]
                    )
                    oi_anchors.append({
                        "elevation_m": sa["elevation_m"],
                        "gust_kmh": sa["gust_kmh"],
                        "wind_speed_kmh": sa_ws_free,
                    })

                # Kernel correlation lengths (terrain-abhängig):
                # L_up: Turbulenz-Zerfallsskala (voralpen/alpen: 1.3-1.4×H_g),
                #   im Bergland zusätzlich BLH-gewichtet (siehe get_effective_L_up).
                #   Im flachen Mittelland fliesst BLH NICHT ein, weil Reibungs-
                #   Korrelationslänge und konvektive Mischschicht zwei verschiedene
                #   Phänomene sind.
                # L_down = H_g: Turbulenz-Zerfall abwärts
                _, L_down = get_oi_scale_lengths(elev_anchor, region_id)
                sfc = hourly_data.get(timestamp, {}) if hourly_data else {}
                blh = sfc.get("boundary_layer_height") or sfc.get("boundary_layer_height_gfs") or 0
                L_up = get_effective_L_up(elev_anchor, region_id, blh)
                grid_gusts_oi = _oi_gust_correction(
                    grid_alts, grid_gusts_bg, grid_ws, oi_anchors, L_up, L_down,
                )

                # Assemble grid levels with 2-Produkt fields
                grid_levels = []
                for i, grid_alt in enumerate(grid_alts):
                    gust_final = max(grid_gusts_oi[i], grid_ws[i])
                    excess = round(gust_final - grid_ws[i], 1)
                    grid_levels.append({
                        "altitude": grid_alt,
                        "wind_speed": round(grid_ws[i], 1),
                        "wind_gusts": round(gust_final, 1),
                        "turbulence_excess": max(0, excess),
                        "wind_direction": round(grid_dir[i]),
                        "temperature": round(grid_temp[i], 1),
                    })

                # Running-Maximum wurde entfernt: OI-Gauss + PBL-Sigmoid liefern
                # bereits eine monoton abklingende T(z)-Kurve. Running-Max zog
                # lokale Wind-Dips (W(z)-Shear) künstlich hoch und verletzte die
                # Asymmetrie von L_up/L_down. Früher propagierte es Ausreißer
                # bis 4 km Höhe (36 km/h Mittelland-Artefakt); der PBL-Cap war
                # nur Pflaster. Jetzt folgt T(z) reiner Gauss-Decay aus Anker.
                profile["levels"] = grid_levels

            # Top-Extrapolation: Regionen (kein Surface-Anchor-Re-Grid) enden
            # mit dem höchsten Pressure-Level (~4200m MSL bei 600 hPa). Für hoch
            # gelegene Regionen will das Frontend bis 5000m MSL rendern — ohne
            # synthetisches Top-Level blieben obere Zellen leer. Wir padden mit
            # den Werten des höchsten tatsächlichen Levels (konstante Fortsetzung
            # = konservativ, Wind ändert in diesen 1-2 km kaum). Nur wenn noch
            # nicht re-gridded (levels ohne "wind_gusts" Feld = PL-Rohdaten).
            if profile["levels"] and "wind_gusts" not in profile["levels"][-1]:
                levels_sorted = sorted(profile["levels"], key=lambda l: l["altitude"])
                top = levels_sorted[-1]
                if top["altitude"] < GRID_MAX - GRID_STEP:
                    profile["levels"].append({
                        "pressure": top.get("pressure"),
                        "altitude": GRID_MAX,
                        "wind_speed": top.get("wind_speed", 0),
                        "wind_direction": top.get("wind_direction", 0),
                        "temperature": top.get("temperature", 0),
                    })

            # Ensure turbulence fields exist on all levels + add turbulence_risk alias
            for lv in profile["levels"]:
                if "turbulence_excess" not in lv:
                    lv["turbulence_excess"] = round(
                        lv.get("wind_gusts", lv.get("wind_speed", 0)) - lv.get("wind_speed", 0), 1
                    )
                lv["turbulence_risk"] = lv.get("wind_gusts", lv.get("wind_speed", 0))

            if len(profile["levels"]) >= 2:
                chart_data["profiles"].append(profile)
        except Exception:
            continue

    return chart_data
