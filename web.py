"""
Flask Web-Server für Flychat.
Routes: Chat-API, Spots-API, Wetter-API, Meteogramm-API.
"""

import os
import json
import logging
import threading
from flask import Flask, render_template, request, jsonify, redirect, url_for, Response, stream_with_context
from datetime import datetime, timedelta

import config

logger = logging.getLogger(__name__)
from thermik_calculator import calculate_thermal_profile, calculate_dewpoint
from source_area import get_all_regions_geojson
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
    aggregate_spot_excess,
)
from source_area import find_region_for_point

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "flychat-dev-key")

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


def init_app(flychat_engine):
    """Setzt die globale Engine-Instanz."""
    global engine
    engine = flychat_engine


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


@app.route("/analyses")
def analyses_page():
    return render_template(
        "analyses.html",
        instantdb_app_id=config.INSTANTDB_APP_ID,
        forecast_days=config.FORECAST_DAYS,
    )


@app.route("/regionen")
def regionen_page():
    return render_template(
        "regionen.html",
        instantdb_app_id=config.INSTANTDB_APP_ID,
        forecast_days=config.FORECAST_DAYS,
    )


@app.route("/newspaper")
def newspaper_page():
    return render_template(
        "newspaper.html",
        instantdb_app_id=config.INSTANTDB_APP_ID,
        forecast_days=config.FORECAST_DAYS,
    )


@app.route("/api/newspaper", methods=["GET"])
def api_newspaper_get():
    """Liefert das zuletzt generierte Wochen-Fazit (Cache)."""
    data = engine._load_weekly_newspaper()
    if not data:
        # Falls kein Cache: nur die Rohdaten-Aggregation ohne LLM-Fazit
        aggregated = engine.build_newspaper_data()
        return jsonify({
            "success": True,
            "days": aggregated.get("days", []),
            "forecast_dates": aggregated.get("forecast_dates", []),
            "generated_at": aggregated.get("generated_at", ""),
            "fazit": None,
        })
    # Ergaenze lat/lon + region_id/region_name fuer Spots, falls der Cache alt ist.
    # So muss der Cache nicht zwingend neu generiert werden, damit die Mini-Karte
    # rendert UND der Regionen-Filter korrekt funktioniert (aelteres
    # chat_engine.py hatte einen Bug wo region_id immer "unknown" war).
    try:
        spot_coord_lookup = {}
        spot_region_lookup = {}  # spot_name -> (region_id, region_name)
        spot_wind_lookup = {}    # spot_name -> windrichtung (fuer alten Cache ohne Feld)
        for s in getattr(engine, "spots", []) or []:
            # load_spots() benutzt "latitude"/"longitude" als Keys (nicht lat/lon).
            lat = s.get("latitude", s.get("lat"))
            lon = s.get("longitude", s.get("lon"))
            try:
                lat_f = float(lat)
                lon_f = float(lon)
            except Exception:
                continue
            spot_coord_lookup[s["name"]] = (lat_f, lon_f)
            spot_wind_lookup[s["name"]] = s.get("windrichtung", "") or ""
            try:
                region = find_region_for_point(lat_f, lon_f)
                if region:
                    # Das Region-Dict hat Keys "id" + "region" (lesbarer Name),
                    # nicht "name"! Fallback: id als Name wenn region fehlt.
                    rid = region.get("id", "unknown")
                    rname = region.get("region") or region.get("name") or rid
                    spot_region_lookup[s["name"]] = (rid, rname)
            except Exception:
                pass

        for day in data.get("days", []) or []:
            for entry in day.get("top_spots", []) or []:
                spot_name = entry.get("spot")
                # lat/lon Fallback
                if entry.get("lat") is None or entry.get("lon") is None:
                    coords = spot_coord_lookup.get(spot_name)
                    if coords:
                        entry["lat"], entry["lon"] = coords
                # windrichtung Fallback (alter Cache hat das Feld nicht;
                # Frontend braucht es fuer den Startrichtungs-Sektor am Marker)
                if not entry.get("windrichtung"):
                    wr = spot_wind_lookup.get(spot_name)
                    if wr:
                        entry["windrichtung"] = wr
                # Region anreichern wenn fehlend oder "unknown" (alter Cache)
                needs_region = (
                    not entry.get("region_id")
                    or entry.get("region_id") == "unknown"
                    or not entry.get("region_name")
                )
                if needs_region:
                    reg = spot_region_lookup.get(spot_name)
                    if reg:
                        entry["region_id"] = reg[0]
                        entry["region_name"] = reg[1]

            # counts_by_region Fallback — alter Cache hat das Feld nicht.
            # Berechnung aus engine.spot_analyses, damit Frontend-Filter
            # korrekte fliegbar/abgleiter/nogo/bedingt-Werte anzeigen kann.
            if not day.get("counts_by_region"):
                date_str = day.get("date")
                cbr = {}
                if date_str and hasattr(engine, "spot_analyses"):
                    for spot_name, days in (engine.spot_analyses or {}).items():
                        if not spot_name or not str(spot_name).strip():
                            continue
                        e = days.get(date_str) if isinstance(days, dict) else None
                        if not e:
                            continue
                        rid_tuple = spot_region_lookup.get(spot_name)
                        rid = rid_tuple[0] if rid_tuple else "unknown"
                        c = cbr.setdefault(rid, {"flyable": 0, "bronze": 0, "nogo": 0, "conditional": 0})
                        safety = e.get("safety", {}) or {}
                        ss = safety.get("safety_status", "") or ""
                        fs = e.get("fly_status", "") or (e.get("flyability", {}) or {}).get("fly_status", "") or ""
                        if ss == "not_safe":
                            c["nogo"] += 1
                            continue
                        if fs == "gray":
                            c["bronze"] += 1
                            continue
                        if ss == "conditional":
                            c["conditional"] += 1
                        if fs in ("green", "violet"):
                            c["flyable"] += 1
                day["counts_by_region"] = cbr
    except Exception:
        pass
    return jsonify(data)


@app.route("/api/newspaper/generate", methods=["POST"])
def api_newspaper_generate():
    """Triggert die LLM-Wochenzusammenfassung (neu generieren)."""
    result = engine.generate_weekly_newspaper()
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


def _ground_wind_by_day(hourly_data, elevation_m, sorted_dates):
    """Extrahiert Bodenwind (10m, terrain-korrigiert) pro Tag/Stunde.

    Dies ist der sicherheitsrelevante Startwind — nicht der freie Höhenwind.
    Open-Meteo `wind_direction_10m` ist bereits terrain-korrigiert (Talwind,
    Hangeffekte via ICON Surface Scheme), `wind_direction_XhPa` nicht.
    """
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
        ws = hd.get("wind_speed_10m")
        wd = hd.get("wind_direction_10m")
        wg = hd.get("wind_gusts_10m")
        if ws is None and wd is None and wg is None:
            continue
        result[date_str].append({
            "hour": dt.hour,
            "wind_speed": float(ws) if ws is not None else None,
            "wind_direction": float(wd) if wd is not None else None,
            "wind_gusts": float(wg) if wg is not None else None,
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

    # Multi-Spot-Bodenexzess (Apr 2026 Refactor):
    # Statt Spot-Höhen als vertikale Anker zu nutzen (10m-Bodenmessung ist
    # KEINE Höhenmessung der freien Atmosphäre!), aggregieren wir die Boden-
    # exzesse aller Spots in der Region zu einem robusten Region-Wert.
    # Das Höhenprofil wird dann via Single-Anchor + Gauss-Decay aufgebaut.
    gust_anchors_by_time = None  # Multi-Anker deaktiviert
    spot_excesses_by_time = {}    # {timestamp: [excess1, excess2, ...]}

    region_info = find_region_for_point(
        region_data.get("latitude", 0), region_data.get("longitude", 0)
    )
    if region_info is None:
        # Fallback: Region aus source_area per ID suchen
        from source_area import get_all_regions
        for r in get_all_regions():
            if r["id"] == region_id:
                region_info = r
                break

    if region_info and region_info.get("polygon"):
        from shapely.geometry import Point as ShapelyPoint
        region_polygon = region_info["polygon"]
        region_spots = [
            s for s in engine.spots
            if region_polygon.contains(ShapelyPoint(s["longitude"], s["latitude"]))
        ]
        # Sammle Bodenexzess (gust_10m - wind_10m) pro Stunde von allen Spots.
        # Die Werte werden später via aggregate_spot_excess (Median bei ≥3,
        # Mittel bei 2, Pass-through bei 1) zu einem robusten Region-Exzess.
        for spot in region_spots:
            spot_data = engine.weather_data.get(spot["name"])
            if not spot_data:
                continue
            for ts, hd in spot_data.get("hourly_data", {}).items():
                ws = hd.get("wind_speed_10m")
                gust = hd.get("wind_gusts_10m")
                if ws is None or gust is None:
                    continue
                excess = max(0.0, float(gust) - float(ws))
                spot_excesses_by_time.setdefault(ts, []).append(excess)

    # Surface anchor: ein einziger Anker am Region-Referenzpunkt mit
    # aggregiertem Multi-Spot-Bodenexzess. Der Region-Center-Exzess fliesst
    # mit ein, sodass auch Regionen ohne Spots einen sauberen Wert liefern.
    surface_anchor_by_time = {}
    for timestamp, hour_data in hourly_data.items():
        gust = hour_data.get("wind_gusts_10m")
        ws = hour_data.get("wind_speed_10m")
        wd = hour_data.get("wind_direction_10m")
        if gust is None or ws is None:
            continue

        ws_f = float(ws)
        ref_excess = max(0.0, float(gust) - ws_f)
        excesses = list(spot_excesses_by_time.get(timestamp, []))
        excesses.append(ref_excess)
        agg_excess = aggregate_spot_excess(excesses)
        aggregated_gust = ws_f + agg_excess

        surface_anchor_by_time[timestamp] = {
            "elevation_m": elevation_ref,
            "gust_kmh": aggregated_gust,
            "wind_speed_kmh": ws_f,
            "wind_direction_10m": float(wd) if wd is not None else None,
        }

    alt_data = format_altitude_wind_for_charts(
        pressure_level_data, hourly_data, elevation_ref, region_id,
        gust_anchors_by_time=gust_anchors_by_time,
        surface_anchor_by_time=surface_anchor_by_time,
    )

    sorted_dates, by_day = _group_profiles_by_day(alt_data)
    ground_wind = _ground_wind_by_day(hourly_data, elevation_ref, sorted_dates)
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

    alt_data = format_altitude_wind_for_charts(
        pressure_level_data, hourly_data, elevation_m, region_id,
        surface_anchor_by_time=surface_anchor_by_time,
    )

    sorted_dates, by_day = _group_profiles_by_day(alt_data)
    ground_wind = _ground_wind_by_day(hourly_data, elevation_m, sorted_dates)
    last_updated, _ = _stale_meta()

    return jsonify({
        "spot_name": spot_name,
        "elevation_m": elevation_m,
        "dates": sorted_dates,
        "data": by_day,
        "ground_wind": ground_wind,
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

    prev_max_h = None
    prev_day = None
    cumulative_bf = 0.0       # Kumulierter Buoyancy-Flux (Encroachment-Modell)
    peak_H = 0.0              # Tages-Maximum des sensiblen Wärmeflusses
    peak_sw = 0.0             # Tages-Maximum der Globalstrahlung (W/m²)

    for timestamp in sorted_times:
        current_day = timestamp[:10]
        if current_day != prev_day:
            prev_max_h = None
            cumulative_bf = 0.0       # Reset pro Tag
            peak_H = 0.0             # Reset pro Tag
            peak_sw = 0.0            # Reset pro Tag
            prev_day = current_day
            
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

            # Thermik
            cape = data.get("cape", 0)
            p_levels = []
            if pressure_level_data and timestamp in pressure_level_data:
                for level in config.PRESSURE_LEVELS:
                    h_val = pressure_level_data[timestamp].get(f"geopotential_height_{level}hPa")
                    t_val = pressure_level_data[timestamp].get(f"temperature_{level}hPa")
                    if h_val is not None and t_val is not None:
                        p_levels.append({"pressure": level, "height": h_val, "temp": t_val})

            surf_temp = data.get("temperature_2m")
            surf_dew = calculate_dewpoint(surf_temp, data.get("relative_humidity_2m", 50))
            elev_ref = elevation_ref if elevation_ref is not None else 850

            therm_climb = 0
            therm_rating = 0
            therm_max_h = None
            therm_diagnostics = {}
            therm_warnings = []

            if surf_temp is not None and p_levels:
                therm = calculate_thermal_profile(
                    surface_temp=surf_temp,
                    surface_dewpoint=surf_dew,
                    elevation_m=elev_ref,
                    pressure_levels_data=p_levels,
                    boundary_layer_height_agl=data.get("boundary_layer_height"),
                    sunshine_duration_s=data.get("sunshine_duration"),
                    surface_sensible_heat_flux=data.get("surface_sensible_heat_flux"),
                    surface_latent_heat_flux=data.get("surface_latent_heat_flux"),
                    shortwave_radiation=data.get("shortwave_radiation"),
                    direct_radiation=data.get("direct_radiation"),
                    diffuse_radiation=data.get("diffuse_radiation"),
                    soil_moisture=data.get("soil_moisture_0_to_1cm"),
                    soil_temperature=data.get("soil_temperature_0cm"),
                    updraft=data.get("updraft"),
                    et0=data.get("et0_fao_evapotranspiration"),
                    vpd=data.get("vapour_pressure_deficit"),
                    lifted_index=data.get("lifted_index"),
                    convective_inhibition=data.get("convective_inhibition"),
                    snow_depth=data.get("snow_depth"),
                    timestamp=timestamp,
                    slope_azimuth=slope_azimuth,
                    slope_angle=slope_angle,
                    low_cloud=data.get("cloud_cover_low", 0),
                    mid_cloud=data.get("cloud_cover_mid", 0),
                    high_cloud=data.get("cloud_cover_high", 0),
                    boundary_layer_height_gfs=data.get("boundary_layer_height_gfs"),
                    previous_max_height=prev_max_h,
                    cumulative_buoyancy=cumulative_bf,
                    peak_H=peak_H,
                    peak_shortwave=peak_sw,
                    region_id=region_id,
                )
                if "error" not in therm:
                    therm_climb = therm["climb_rate"]
                    therm_rating = therm["rating"]
                    therm_max_h = therm["max_height"]
                    prev_max_h = therm_max_h
                    therm_diagnostics = therm.get("diagnostics", {})
                    therm_warnings = therm.get("data_warnings", [])
                    # Buoyancy akkumulieren (Encroachment-Modell)
                    cumulative_bf += therm_diagnostics.get("buoyancy_contribution", 0)
                    # Peak-H für H-skalierte Inertia tracken
                    current_H = therm_diagnostics.get("sensible_heat_flux", 0)
                    peak_H = max(peak_H, current_H)
                    sw = data.get("shortwave_radiation")
                    if sw is not None:
                        peak_sw = max(peak_sw, sw)

            # Wolkenbasis + Schichten
            cloud_base = data.get("cloud_base")
            cloud_cover = data.get("cloud_cover")
            cloud_cover_low = data.get("cloud_cover_low")
            cloud_cover_mid = data.get("cloud_cover_mid")
            cloud_cover_high = data.get("cloud_cover_high")

            # Nutzbare Thermikhoehe an Wolkenbasis kappen
            if (therm_max_h and cloud_base and cloud_base > elev_ref
                    and therm_max_h > cloud_base):
                therm_max_h = cloud_base

            if cape is not None:
                chart_data["thermik"].append({
                    "time": time_str,
                    "cape": cape,
                    "climb_rate": therm_climb,
                    "rating": therm_rating,
                    "max_height": therm_max_h,
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

    # Grid: 0-4000m in 250m steps
    GRID_STEP = 250
    GRID_MAX = 4000

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

                # Running Maximum nur INNERHALB der Grenzschicht (PBL × 1.2)
                # als Safety-Layer. Über der PBL gibt es keine Boden-getriebene
                # Turbulenz mehr → Böe folgt der natürlichen Gauss-Decay (= Wind).
                # Vorher wurde der Max-Wert unbegrenzt nach oben durchgezogen,
                # was Höhen-Böen auf 4 km systematisch überschätzte (z.B.
                # 36 km/h statt physikalisch korrekter ~21 km/h).
                pbl_cap_alt = ((elevation_m or 0) + blh * 1.2) if blh > 0 else float("inf")

                running_max = 0.0
                for lv in grid_levels:
                    if lv["altitude"] <= pbl_cap_alt:
                        # In/an der PBL: Running-Max anwenden (Sicherheit)
                        running_max = max(running_max, lv["wind_gusts"])
                        lv["wind_gusts"] = running_max
                    # Über PBL: wind_gusts bleibt der OI-Wert (decayed → Wind)
                    lv["turbulence_excess"] = round(lv["wind_gusts"] - lv["wind_speed"], 1)

                profile["levels"] = grid_levels

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
