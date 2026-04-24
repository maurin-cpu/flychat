"""
Flask Web-Server für Gleitcast.
Routes: Chat-API, Spots-API, Wetter-API, Meteogramm-API.
"""

import os
import copy
import json
import logging
import math
import threading
from functools import wraps
from flask import Flask, render_template, request, jsonify, redirect, url_for, Response, stream_with_context
from datetime import datetime, timedelta

import config

logger = logging.getLogger(__name__)
from thermik_calculator import compute_daily_thermals
from source_area import get_all_regions_geojson, get_all_regions
from subscriber import get_manager_from_env as _get_subscriber_manager
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
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "gleitcast-dev-key")

# Ensure JSON responses send raw UTF-8 characters (ä, ö, ü instead of \uXXXX)
app.config['JSON_AS_ASCII'] = False
app.json.ensure_ascii = False


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


@app.context_processor
def _inject_supabase_creds():
    """Macht SUPABASE_URL + SUPABASE_ANON_KEY in allen Templates verfuegbar.
    Leer wenn nicht konfiguriert → Frontend-Code faellt auf /api/* Polling zurueck.
    """
    return {
        "supabase_url": os.environ.get("SUPABASE_URL", "").strip(),
        "supabase_anon_key": os.environ.get("SUPABASE_ANON_KEY", "").strip(),
    }


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


def init_app(gleitcast_engine):
    """Setzt die globale Engine-Instanz."""
    global engine
    engine = gleitcast_engine


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
            "Der Briefing-Service ist gerade nicht geladen.",
            http_code=503,
        )

    try:
        briefing_data = engine.build_briefing_data()
    except Exception as e:
        logger.exception("preview_briefing: build_briefing_data failed: %s", e)
        return _status_page(
            "error", "Vorschau nicht verfuegbar",
            "Die Briefing-Daten konnten gerade nicht geladen werden.",
            http_code=503,
        )

    # Demo-Subscriber mit allen Regionen (so sieht man Spots aus der ganzen Schweiz)
    all_region_ids = [r["id"] for r in get_all_regions()]
    demo_subscriber = {
        "id": 0,
        "email": "vorschau@gleitcast.ch",
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
    return render_template(
        "subscribe.html",
        regions=_regions_for_form(),
        prefill_email="",
        prefill_regions=set(),
        prefill_level="standard",
        flash_error=request.args.get("err", ""),
        flash_ok="",
    )


@app.route("/subscribe", methods=["POST"])
def subscribe_submit():
    email = (request.form.get("email") or "").strip()
    regions = request.form.getlist("regions")
    skill_level = request.form.get("skill_level", "standard")

    # Re-render mit Fehlermeldung + Prefill
    def _rerender(err: str):
        return render_template(
            "subscribe.html",
            regions=_regions_for_form(),
            prefill_email=email,
            prefill_regions=set(regions),
            prefill_level=skill_level,
            flash_error=err,
            flash_ok="",
        ), 400

    if not email:
        return _rerender("Bitte gib deine E-Mail-Adresse ein.")
    if not regions:
        return _rerender("Bitte waehle mindestens eine Region aus.")

    mgr = _get_subscriber_manager()
    if mgr is None:
        logger.error("/subscribe POST: SUPABASE_DATABASE_URL nicht konfiguriert")
        return _rerender("Der Abo-Service ist gerade nicht verfuegbar. Bitte spaeter nochmal.")

    result = mgr.create(email=email, regions=regions, skill_level=skill_level)
    if result is None:
        # Haeufigster Grund: E-Mail bereits aktiv/pending
        return _rerender(
            "Diese E-Mail ist bereits registriert oder ungueltig. "
            "Falls du den Bestaetigungs-Link nicht findest, schreib uns."
        )

    # Bestaetigungs-Mail versenden (async, damit der Request nicht auf SMTP wartet)
    try:
        send_confirm_email(result["email"], result["confirm_token"])
    except Exception as e:
        logger.exception("Confirm-Mail-Versand fehlgeschlagen fuer %s: %s",
                         result["email"], e)
        # Subscriber bleibt als 'pending' in der DB. Admin kann Token manuell rausziehen.

    return _status_page(
        state="ok",
        title="Fast geschafft!",
        message=f"Wir haben eine Bestaetigungs-E-Mail an {result['email']} geschickt.",
        submessage="Klicke auf den Link in der E-Mail, um dein Abo zu aktivieren. "
                   "Kein Mail erhalten? Schau im Spam-Ordner.",
    )


@app.route("/confirm/<token>", methods=["GET"])
def subscribe_confirm(token):
    mgr = _get_subscriber_manager()
    if mgr is None:
        return _status_page(
            "error", "Bestaetigung fehlgeschlagen",
            "Der Service ist gerade nicht verfuegbar. Bitte spaeter nochmal.",
            http_code=503,
        )

    result = mgr.confirm(token)
    if result is None:
        # Vielleicht schon bestaetigt? Dann ist confirm_token NULL -> get_by_action_token wuerde gehen,
        # aber der Link kommt nicht vom Action-Token. Wir zeigen einfach "ungueltig/abgelaufen".
        return _status_page(
            "error", "Link ungueltig oder bereits verwendet",
            "Dieser Bestaetigungs-Link ist abgelaufen oder wurde bereits benutzt.",
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
        "ok", "Abo aktiviert!",
        f"Willkommen bei Gleitcast, {result['email']}.",
        submessage="Dein erstes Briefing kommt am naechsten Montag, Mittwoch oder Freitag um 06:30.",
    )


@app.route("/feedback/<token>/<verdict>", methods=["GET"])
def subscribe_feedback(token, verdict):
    """One-Click-Feedback aus Briefing-Mail. Akzeptiert correct|wrong.
    Rate-Limit: max 1 Eintrag pro Subscriber pro Kalendertag.
    """
    if verdict not in ("correct", "wrong"):
        return _status_page(
            "error", "Ungueltige Bewertung",
            "Dieser Link ist ungueltig.",
            http_code=400,
        )

    mgr = _get_subscriber_manager()
    if mgr is None:
        return _status_page(
            "error", "Feedback fehlgeschlagen",
            "Der Service ist gerade nicht verfuegbar.",
            http_code=503,
        )

    sub = mgr.get_by_action_token(token)
    if sub is None:
        return _status_page(
            "error", "Link ungueltig",
            "Dieser Feedback-Link ist nicht (mehr) gueltig.",
            http_code=404,
        )

    from datetime import date
    ok = mgr.record_feedback(sub["id"], date.today(), verdict)
    if not ok:
        return _status_page(
            "error", "Feedback fehlgeschlagen",
            "Dein Feedback konnte nicht gespeichert werden. Versuch's spaeter nochmal.",
            http_code=500,
        )

    if verdict == "correct":
        return _status_page(
            "ok", "Danke fuer die Bestaetigung!",
            "Dein Feedback hilft uns, die Vorhersage zu verbessern.",
        )
    return _status_page(
        "ok", "Danke fuer dein Feedback!",
        "Schade, dass die Vorhersage nicht gepasst hat. Wir lernen daraus.",
        submessage="Mehr Details kannst du uns gerne per E-Mail-Antwort schicken.",
    )


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
    return render_template(
        "account.html",
        subscriber=sub,
        token=token,
        region_names=_region_names(sub.get("regions") or []),
        flash_ok=request.args.get("ok", ""),
        flash_error=request.args.get("err", ""),
    )


@app.route("/account/<token>/<action>", methods=["POST"])
def account_action(token, action):
    mgr = _get_subscriber_manager()
    if mgr is None:
        return redirect(f"/account/{token}?err=Service+nicht+verfuegbar")

    if action == "pause_14d" or action == "pause_30d":
        from datetime import date, timedelta
        days = 14 if action == "pause_14d" else 30
        until = date.today() + timedelta(days=days)
        ok = mgr.pause(token, until)
        if not ok:
            return redirect(f"/account/{token}?err=Pause+fehlgeschlagen")
        return redirect(f"/account/{token}?ok=Pausiert+bis+{until.isoformat()}")

    if action == "resume":
        ok = mgr.resume(token)
        if not ok:
            return redirect(f"/account/{token}?err=Fortsetzen+fehlgeschlagen")
        return redirect(f"/account/{token}?ok=Abo+wieder+aktiv")

    if action == "unsubscribe":
        ok = mgr.unsubscribe(token)
        if not ok:
            return redirect(f"/account/{token}?err=Abmelden+fehlgeschlagen")
        return _status_page(
            "ok", "Abgemeldet",
            "Du bekommst keine Briefings mehr. Schade, dass du gehst!",
            submessage="Du kannst dich jederzeit wieder anmelden.",
        )

    return _status_page(
        "error", "Unbekannte Aktion",
        "Diese Aktion ist nicht erlaubt.",
        http_code=400,
    )


@app.route("/unsubscribe/<token>", methods=["GET"])
def subscribe_unsubscribe(token):
    mgr = _get_subscriber_manager()
    if mgr is None:
        return _status_page(
            "error", "Abmeldung fehlgeschlagen",
            "Der Service ist gerade nicht verfuegbar. Bitte spaeter nochmal.",
            http_code=503,
        )

    ok = mgr.unsubscribe(token)
    if not ok:
        return _status_page(
            "error", "Link ungueltig",
            "Dieser Abmelde-Link ist nicht (mehr) gueltig.",
            http_code=404,
        )

    return _status_page(
        "ok", "Abgemeldet",
        "Du bekommst keine Briefings mehr. Schade, dass du gehst!",
        submessage="Du kannst dich jederzeit wieder anmelden.",
    )


# ============================================================================
# ADMIN-DASHBOARD (HTTP Basic Auth via ADMIN_PASSWORD env)
# ============================================================================

def _require_admin(f):
    """HTTP-Basic-Auth-Decorator. Nur Password-Check, User-Feld ignoriert."""
    @wraps(f)
    def wrapper(*args, **kwargs):
        expected = (config.ADMIN_PASSWORD or "").strip()
        if not expected:
            return ("Admin deaktiviert (ADMIN_PASSWORD nicht gesetzt)",
                    503, {"Content-Type": "text/plain; charset=utf-8"})
        auth = request.authorization
        if not auth or (auth.password or "") != expected:
            return Response(
                "Admin-Bereich — Zugriff nur mit Passwort.\n",
                401,
                {"WWW-Authenticate": 'Basic realm="Gleitcast Admin"',
                 "Content-Type": "text/plain; charset=utf-8"},
            )
        return f(*args, **kwargs)
    return wrapper


@app.route("/admin", methods=["GET"])
@_require_admin
def admin_index():
    return redirect("/admin/subscribers")


@app.route("/admin/subscribers", methods=["GET"])
@_require_admin
def admin_subscribers():
    mgr = _get_subscriber_manager()
    if mgr is None:
        return _status_page("error", "Admin nicht verfuegbar",
                            "SUPABASE_DATABASE_URL nicht konfiguriert.",
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
# PAGE ROUTES
# ============================================================================

@app.route("/")
def index():
    return render_template(
        "index.html",
        instantdb_app_id=config.INSTANTDB_APP_ID,
        forecast_days=config.FORECAST_DAYS,
        show_reference_points=config.SHOW_REFERENCE_POINTS,
    )


@app.route("/chat")
def chat_page():
    return render_template(
        "index.html",
        instantdb_app_id=config.INSTANTDB_APP_ID,
        forecast_days=config.FORECAST_DAYS,
        show_reference_points=config.SHOW_REFERENCE_POINTS,
    )


@app.route("/map")
def map_page():
    return render_template(
        "index.html",
        instantdb_app_id=config.INSTANTDB_APP_ID,
        forecast_days=config.FORECAST_DAYS,
        show_reference_points=config.SHOW_REFERENCE_POINTS,
    )


@app.route("/regionen")
def regionen_page():
    return render_template(
        "regionen.html",
        instantdb_app_id=config.INSTANTDB_APP_ID,
        forecast_days=config.FORECAST_DAYS,
    )


@app.route("/og-image/briefing.png")
def og_image_briefing():
    """Dynamisches OpenGraph-Bild fuer Link-Previews.

    Query-Params: tier (violet|green|conditional|gray|none), title, subtitle.
    Rendert ein 1200x630 PNG mit Tier-Farbverlauf + Gleitcast-Branding + Text.
    Fallback auf statisches Default-Design wenn keine Params.
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        logger.warning("og_image_briefing: Pillow nicht installiert, 502 Response")
        return Response("OG-Image-Generator nicht verfuegbar (Pillow fehlt)",
                        status=502, mimetype="text/plain")

    tier = (request.args.get("tier") or "none").lower()
    title = (request.args.get("title") or "Gleitcast – Flugwetter").strip()
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
    draw.text((60, 50), "GLEITCAST", font=brand_font, fill=(255, 255, 255))
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
    return render_template(
        "briefing.html",
        instantdb_app_id=config.INSTANTDB_APP_ID,
        forecast_days=config.FORECAST_DAYS,
        og=og,
    )


def _build_briefing_og(regions_csv: str, day_str: str | None, spot_name: str = "") -> dict:
    """Baut OG-Meta-Daten fuer die Briefing-Seite aus Query-Params.

    - Fallback: generische Site-Description wenn keine Filter gesetzt.
    - Mit Filter: peekt briefing_data und baut Title aus bestem Spot / Tag-Tier.
    """
    base_url = request.url_root.rstrip("/")
    title = "Gleitcast – Flugwetter für Gleitschirmpiloten"
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

    from email_service import _TIER_META, _spot_tier, _date_label
    if best_spot and best_day:
        tier = _spot_tier(best_spot)
        meta = _TIER_META.get(tier, _TIER_META["gray"])
        rating = float(best_spot.get("rating") or 0)
        label = _date_label(best_day.get("date", ""))
        day_short = label.get("short", "")
        title = f"{best_spot.get('spot','')} – {day_short} {meta['label']} {rating:.1f}"
        desc = f"{region_label} · {meta['label']} · Rating {rating:.1f} · Gleitcast-Briefing"
        tier_param = tier
    else:
        tier_param = "none"
        title = f"Gleitcast – {region_label}"
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
    """Liefert das Wochen-Fazit.  Days/Spots werden immer frisch aus
    spot_analyses gebaut, das LLM-Fazit kommt aus dem Cache."""
    cached = engine._load_weekly_briefing()
    aggregated = engine.build_briefing_data()
    fazit = (cached or {}).get("fazit")
    return jsonify({
        "success": True,
        "days": aggregated.get("days", []),
        "forecast_dates": aggregated.get("forecast_dates", []),
        "generated_at": aggregated.get("generated_at", ""),
        "fazit": fazit,
    })


@app.route("/api/briefing/generate", methods=["POST"])
def api_briefing_generate():
    """Triggert die LLM-Wochenzusammenfassung (neu generieren)."""
    result = engine.generate_weekly_briefing()
    status = 200 if result.get("success") else 500
    return jsonify(result), status


# ============================================================================
# CHAT API
# ============================================================================

@app.route("/api/chat", methods=["POST"])
def api_chat():
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": "Keine Nachricht"}), 400

    message = data["message"].strip()
    session_id = data.get("session_id", "default")

    if not message:
        return jsonify({"error": "Leere Nachricht"}), 400

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
def api_reset_chat():
    """Setzt die aktuelle Konversation zurück."""
    data = request.get_json(silent=True) or {}
    session_id = data.get("session_id")
    if session_id:
        engine.reset_conversation(session_id)
        return jsonify({"success": True})
    return jsonify({"success": False, "error": "Keine Session-ID"}), 400




@app.route("/api/run-analyses", methods=["POST"])
def api_run_analyses():
    """Startet die LLM Spot-Analyse für alle Spots."""
    try:
        result = engine.run_spot_analyses()
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/analyses")
def api_analyses():
    """Gibt Spot-Analysen im flachen Format zurück (wie InstantDB-Subscription)."""
    flat = {}
    loaded_at = engine.analyses_loaded_at.isoformat() if engine.analyses_loaded_at else None
    for spot_name, days in engine.spot_analyses.items():
        flat[spot_name] = {}
        for date_str, entry in days.items():
            safety = entry.get("safety", {})
            fly = entry.get("flyability", {})
            fly_status = entry.get("fly_status", "")
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
                "rating": float(entry.get("rating", 0.0) or 0.0),
                "is_conditional": bool(entry.get("is_conditional", False)),
                "conditional_reason": entry.get("conditional_reason", "") or "",
            }
            for key in ("no_go_reasons", "caution_notes"):
                val = safety.get(key, [])
                doc[key] = json.dumps(val, ensure_ascii=False) if isinstance(val, list) else str(val)
            for lbl_key in ("primary_no_go", "primary_caution", "primary_reducer", "primary_booster"):
                doc[lbl_key] = safety.get(lbl_key) or None
            ss = safety.get("safety_status", "error")
            if fly and fly_status and ss in ("safe", "conditional"):
                doc["fly_status"] = fly_status
                doc["flyability_tier"] = fly_status
                doc["flight_type"] = fly.get("flight_type", "")
                doc["flight_duration"] = fly.get("flight_duration_estimate", "")
                doc["xc_potential"] = fly.get("xc_potential", "")
                doc["peak_climb_rate"] = fly.get("peak_climb_rate", 0)
                doc["flyability_feedback"] = fly.get("recommendation", "")
                for lkey in ("flyability_limits", "highlights"):
                    val = fly.get(lkey, [])
                    if isinstance(val, list):
                        val = val[:3]
                    doc[lkey] = json.dumps(val if isinstance(val, list) else [], ensure_ascii=False)
            else:
                doc["fly_status"] = ""
                doc["flyability_tier"] = ""
                doc["fly_error"] = entry.get("fly_error", "")
            sf = entry.get("streckenflug") or {}
            doc["streckenflug_tier"] = sf.get("tier", "kein_xc")
            doc["streckenflug_rating"] = int(sf.get("rating", 0) or 0)
            doc["streckenflug_summary"] = sf.get("summary", "") or ""
            doc["streckenflug_limiting_factor"] = sf.get("limiting_factor", "none")
            doc["streckenflug_region_context_available"] = bool(sf.get("region_context_available", False))
            flat[spot_name][date_str] = doc
    return jsonify({"spot_analyses": flat, "analyses_count": len(flat)})


@app.route("/api/run-region-analyses", methods=["POST"])
def api_run_region_analyses():
    """Startet die LLM Region-Analyse fuer alle Regionen."""
    try:
        result = engine.run_region_analyses()
        return jsonify(result)
    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/region-analyses")
def api_region_analyses():
    """Gibt Region-Analysen im flachen Format zurück."""
    flat = {}
    loaded_at = engine.region_analyses_loaded_at.isoformat() if engine.region_analyses_loaded_at else None
    for rid, days in engine.region_analyses.items():
        flat[rid] = {}
        for date_str, entry in days.items():
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
                "rating": float(entry.get("rating", 0.0) or 0.0),
                "is_conditional": bool(entry.get("is_conditional", False)),
                "conditional_reason": entry.get("conditional_reason", "") or "",
            }
            for key in ("no_go_reasons", "caution_notes"):
                val = safety.get(key, entry.get(key, []))
                doc[key] = json.dumps(val, ensure_ascii=False) if isinstance(val, list) else str(val)
            for lbl_key in ("primary_no_go", "primary_caution", "primary_reducer", "primary_booster"):
                doc[lbl_key] = safety.get(lbl_key) or None
            if fly and fly_status and ss in ("safe", "conditional"):
                doc["fly_status"] = fly_status
                doc["flyability_tier"] = fly_status
                doc["recommendation"] = fly.get("recommendation", "")
                doc["peak_climb_rate"] = fly.get("peak_climb_rate", 0)
                doc["flight_type"] = fly.get("flight_type", "")
            else:
                doc["fly_status"] = ""
                doc["flyability_tier"] = ""
                doc["fly_error"] = entry.get("fly_error", "")
            flat[rid][date_str] = doc
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


@app.route("/api/refresh-spots", methods=["POST"])
def api_refresh_spots():
    """Laedt Spots neu aus CSV und synchronisiert nach InstantDB."""
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
        "ground_wind": {"warn": config.WIND_MODERATE_KMH, "danger": config.WIND_STRONG_KMH},
        "ground_gust": {"warn": config.GUST_WARN_KMH, "danger": config.GUST_DANGER_KMH},
        "aloft_wind": {"warn": config.ALOFT_WARN_KMH, "danger": config.ALOFT_DANGER_KMH},
        "aloft_gust": {"warn": config.ALOFT_GUST_WARN_KMH, "danger": config.ALOFT_GUST_DANGER_KMH},
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

    chart_data = format_data_for_charts(hourly_data, pressure_level_data, elevation_ref=elevation_ref,
                                        region_id=region_id)

    # Regionen haben keine Böen (Apr 2026): gusts = null.
    # Frontend (meteogram.js) interpretiert null korrekt: hasRealGust=false →
    # keine Gust-Label, keine Gust-Warnungen. Tooltip zeigt "Böen: -".
    for w in chart_data.get("wind", []):
        w["gusts"] = None

    sorted_dates, by_day = _group_chart_by_day(chart_data)
    last_updated, _ = _stale_meta()

    return jsonify({
        "region_id": region_id,
        "region_name": region_data.get("region_name", region_id),
        "elevation_ref": elevation_ref,
        "dates": sorted_dates,
        "data": by_day,
        "stale": len(sorted_dates) < config.FORECAST_DAYS,
        "last_updated": last_updated,
        "expected_days": config.FORECAST_DAYS,
        "is_region": True,
        "thresholds": _tier_thresholds(),
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

    return jsonify({
        "region_id": region_id,
        "elevation_m": elevation_ref,
        "dates": sorted_dates,
        "data": by_day,
        "ground_wind": ground_wind,
        "stale": len(sorted_dates) < config.FORECAST_DAYS,
        "last_updated": last_updated,
        "expected_days": config.FORECAST_DAYS,
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

    return jsonify({
        "spot_name": spot_name,
        "elevation_m": elevation_m,
        "dates": sorted_dates,
        "data": by_day,
        "stale": len(sorted_dates) < config.FORECAST_DAYS,
        "last_updated": last_updated,
        "expected_days": config.FORECAST_DAYS,
        "windrichtung": (spot_info.get("windrichtung") if spot_info else None),
        "ideal_wind_max": (spot_info.get("ideal_wind_max") if spot_info else None),
        "thresholds": _tier_thresholds(),
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

    return jsonify({
        "spot_name": spot_name,
        "elevation_m": elevation_m,
        "dates": sorted_dates,
        "data": by_day,
        "ground_wind": ground_wind,
        "data_ch1": ch1_by_day,
        "ground_wind_ch1": ch1_ground_wind,
        "stale": len(sorted_dates) < config.FORECAST_DAYS,
        "last_updated": last_updated,
        "expected_days": config.FORECAST_DAYS,
    })


# ============================================================================
# FÖHN API
# ============================================================================

@app.route("/api/foehn")
def api_foehn():
    """Föhn-Zeitreihe: stündliche Delta-P, Kammwind, Feuchte für Diagramm."""
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
                           slope_azimuth=None, slope_angle=None, region_id=None):
    """Formatiert Daten für D3.js Charts inkl. Thermik-Physik."""
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
