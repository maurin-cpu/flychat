"""
Gleitcast Engine — Mixin: ChatOrchestratorMixin.

Ausgeschnitten aus chat_engine.py (Monolith-Split). Methoden-Signaturen
unveraendert, Klasse wird via Mehrfachvererbung in GleitcastEngine eingebunden.
"""

import copy
import json
import logging
import math
import os
import re
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, wait, FIRST_COMPLETED
from datetime import datetime, timedelta
from pathlib import Path

import config
from spots import load_spots
from fetch_weather import (
    fetch_all_spots, load_cached_weather, load_cached_weather_timestamp,
    is_cache_fresh, is_cache_complete, validate_spot_data,
)
from foehn_indicators import (
    fetch_foehn_data, evaluate_foehn, build_foehn_llm_context,
)
from thermik_calculator import (
    calculate_thermal_profile, calculate_dewpoint, get_terrain_zone,
)
from gust_calculator import (
    estimate_altitude_gusts, collect_gust_anchors,
    estimate_altitude_gusts_multi_anchor,
    apply_oi_gust_correction, aggregate_spot_excess, get_L_up,
    interpolate_gust_from_anchors,
)
from station_observations import StationManager
from source_area import (
    get_reference_points, _load_regions, find_region_for_point,
    get_all_regions,
)
import prompts
from prompts import format_foehn_llm_regional_guide
import routing
from engine._common import (
    MAX_HISTORY_MESSAGES, MAX_TOOL_ITERATIONS,
    _MODEL_TOKEN_LIMITS, _DEFAULT_TOKEN_LIMIT, _TOKEN_BUDGET_RESERVE,
    _CTX_CACHE_MAX_ENTRIES,
    _estimate_tokens, _truncate_weather_context, _filter_context_by_days,
    _log_prompt_cache_usage, _weekday_de,
    _is_permanent_api_error, _user_friendly_api_error,
    _FLYABILITY_TIERS, _normalize_flyability_tier,
    _compute_rating_from_subratings,
    _TAG_NATURAL, _TAG_NATURAL_MAP, _TAG_SANITIZE_RE,
    _sanitize_llm_text, _sanitize_llm_result,
    _LABEL_KEYS_NO_GO, _LABEL_KEYS_CONDITIONAL,
    _LABEL_KEYS_REDUCER, _LABEL_KEYS_BOOSTER,
    _NO_GO_RANK, _CONDITIONAL_RANK,
    _KEYWORD_TO_KEY_NO_GO, _KEYWORD_TO_KEY_CAUTION,
    _pick_key_from_list, _validate_key, _derive_primary_labels,
    COMPASS_POINTS, _compute_wind_trend, _detect_rain_sandwich,
    _interpolate_wind_at_altitude,
)

logger = logging.getLogger(__name__)


# ============================================================================
# TOOL SCHEMAS (Standort-basierte Spot-Filterung via Isochrone)
# ============================================================================
# Drei Tools:
#   1. geocode_location               — Adresse/Stadt → Koordinaten
#   2. find_spots_within_travel_time  — Isochrone + Spot-Filter (Hauptfunktion)
#   3. clear_map_overlays             — Map-Overlays zuruecksetzen
# Nach Erhalt eines Tool-Calls dispatcht answer_stream() an _dispatch_tool(),
# yieldet Map-Action-Events sofort ans Frontend und ruft danach erneut das LLM.
TOOLS: list = [
    {
        "type": "function",
        "function": {
            "name": "geocode_location",
            "description": (
                "Geokodiert eine vom Piloten genannte Adresse oder Stadt zu Koordinaten. "
                "Verwende dieses Tool wenn der Pilot einen Standort nennt (z.B. 'Zürich', "
                "'Bern', 'Bahnhofstrasse 5 Luzern') und wir wissen müssen wo er ist, "
                "BEVOR wir mit find_spots_within_travel_time die erreichbaren Spots suchen."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Adresse, Stadt oder Ortsname (z.B. 'Zürich' oder 'Bern Bahnhof')."
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_spots_within_travel_time",
            "description": (
                "Findet alle Fluggebiete, die der Pilot von einem Startpunkt aus innerhalb "
                "einer maximalen Reisezeit erreichen kann. Berechnet eine Isochrone (erreichbare "
                "Zone) per Valhalla, zeichnet sie automatisch auf der Karte ein und filtert die "
                "Spots, die darin liegen. Liefert die Liste der erreichbaren Spots zurück, "
                "inklusive Voranalyse-Daten (Sicherheit, Fliegbarkeit) für deine Empfehlung."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "lat": {
                        "type": "number",
                        "description": "Latitude des Startpunkts (WGS84). Aus geocode_location.",
                    },
                    "lon": {
                        "type": "number",
                        "description": "Longitude des Startpunkts (WGS84). Aus geocode_location.",
                    },
                    "minutes": {
                        "type": "integer",
                        "description": "Maximale Reisezeit in Minuten (z.B. 60, 90, 120).",
                        "minimum": 1,
                        "maximum": 360,
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["auto", "bicycle", "pedestrian"],
                        "description": (
                            "Verkehrsmittel: 'auto' für Auto, 'bicycle' für Velo, "
                            "'pedestrian' für zu Fuss. Default 'auto'."
                        ),
                    },
                    "label": {
                        "type": "string",
                        "description": (
                            "Optional: Anzeigename des Startpunkts für die Karte (z.B. 'Zürich'). "
                            "Wird neben dem Pin angezeigt."
                        ),
                    },
                },
                "required": ["lat", "lon", "minutes"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "clear_map_overlays",
            "description": (
                "Entfernt alle dynamischen Overlays von der Karte (Isochrone, "
                "User-Standort-Pin, Spot-Highlights). Verwende wenn der Pilot "
                "'Karte zurücksetzen', 'alles löschen', 'reset karte' o.ä. sagt."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
            },
        },
    },
]


class ChatOrchestratorMixin:
    def _get_or_create_conversation(self, session_id: str) -> list:
        """Holt bestehende Conversation oder erstellt neue mit globalem Kontext."""
        if session_id in self.conversations:
            return self.conversations[session_id]["messages"]

        messages = [
            {
                "role": "system",
                "content": prompts.SYSTEM_PROMPT + "\n\n" + prompts.CAPABILITIES_GUIDE + "\n\n" + prompts.FOEHN_CHAT_KNOWLEDGE,
            },
        ]
        self.conversations[session_id] = {
            "messages": messages,
            "last_activity": datetime.now().isoformat(),
            "first_question": True,
        }
        return messages

    def _ensure_weather_context(self):
        """Stellt sicher dass weather_context_str vorhanden ist. Fallback: InstantDB."""
        if self.weather_context_str:
            return
        if not self.instantdb:
            return
        try:
            global_id = self.instantdb.make_id("weather_state.global")
            result = self.instantdb.query("weather_state")
            if result and "weather_state" in result:
                for entry in result["weather_state"]:
                    matrix = entry.get("matrix_text")
                    if matrix:
                        self.weather_context_str = matrix
                        logger.info("Wetterdaten aus InstantDB weather_state geladen")
                        return
        except Exception as e:
            logger.error(f"InstantDB weather_state Fallback fehlgeschlagen: {e}")

    def answer(self, session_id: str, question: str) -> str:
        """Beantwortet eine Pilotenfrage. Wetterdaten sind im Kontext."""
        if not self.chat_client:
            return f"Fehler: Kein API-Key fuer Chat-Provider '{self.chat_provider}' konfiguriert."

        # FORMAT-HINT aus der Frage extrahieren (wird ans LLM gesendet, aber nicht in History gespeichert)
        format_hint = ""
        hint_match = re.search(r'\s*\[FORMAT-HINT:\s*[^\]]*\]', question)
        if hint_match:
            format_hint = hint_match.group(0)
            question_clean = question[:hint_match.start()] + question[hint_match.end():]
            question_clean = question_clean.strip()
        else:
            question_clean = question

        # Sicherstellen dass Wetterdaten verfügbar sind (Fallback: InstantDB)
        self._ensure_weather_context()

        if not self.weather_context_str:
            return "Wetterdaten werden geladen... Bitte versuche es gleich nochmal."

        # Spot-Analysen aus InstantDB laden falls lokal nicht vorhanden
        self._ensure_spot_analyses()

        messages = self._get_or_create_conversation(session_id)
        conv = self.conversations[session_id]

        # Erste Frage: Kontext automatisch mitsenden
        if conv["first_question"]:
            # Voranalysen vorhanden? → Kurzübersicht (Chat-tauglich), sonst Roh-Wetterkontext
            analyses_context = self._build_compact_analyses_for_chat()
            if analyses_context:
                # Kompakte Analyse enthält keinen globalen Föhn-Block — immer anhängen, sonst
                # antwortet das Modell bei „Föhn?" ohne ΔP/Kammwind und rät falsch.
                foehn_snap = self._build_foehn_context_for_ai()
                context_block = analyses_context + "\n\n" + foehn_snap
            else:
                context_block = self.weather_context_str

            # Token-Budget: Kontext kürzen falls er das Modell-Limit sprengt
            model_limit = _MODEL_TOKEN_LIMITS.get(self.chat_model, _DEFAULT_TOKEN_LIMIT)
            system_tokens = _estimate_tokens(messages[0]["content"]) if messages else 0
            context_budget = model_limit - _TOKEN_BUDGET_RESERVE - system_tokens
            if context_budget > 0 and _estimate_tokens(context_block) > context_budget:
                context_block = _truncate_weather_context(context_block, context_budget)

            user_content = (
                f"AKTUELZEIT: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ({_weekday_de(datetime.now())})\n"
                "Hintergrunddaten für deine Antwort (nicht wörtlich als Gesamtreport ausgeben):\n"
                "==========================================================\n"
                f"{context_block}\n"
                "==========================================================\n"
                "Beantworte die Frage des Piloten **direkt** und in angemessenem Umfang — wie in einem "
                "kurzen Chat. Keine vollständige Tabelle aller Spots, es sei denn der Pilot verlangt "
                "ausdrücklich eine Übersicht/Tabelle **aller** Gebiete oder einen mehrzeiligen Vergleich.\n"
                'Bei **Föhn-Fragen**: die Föhn-Lage nur aus dem Block „FÖHN-INDIKATOR" (ΔP, Kammwind, Level) '
                'ableiten — nicht aus „alle Spots nicht sicher" schließen, dass es „keinen Föhn" gäbe.\n\n'
                f"Frage des Piloten: {question_clean}{format_hint}"
            )
            conv["first_question"] = False
        else:
            user_content = question_clean + format_hint

        messages.append({"role": "user", "content": user_content})

        # Token-Management: History trimmen wenn zu lang
        if len(messages) > MAX_HISTORY_MESSAGES:
            # Behalte System-Prompt + erste User-Message (mit Wetterdaten) + letzte N Messages
            messages[:] = messages[:2] + messages[-(MAX_HISTORY_MESSAGES - 2):]

        # LLM Chat Call (Provider abhaengig: OpenAI / Anthropic / Gemini)
        try:
            response = self.chat_client.chat.completions.create(
                model=self.chat_model,
                messages=messages,
                temperature=0.7,
                max_tokens=2000,
            )
            _log_prompt_cache_usage(response, label="chat_answer")
            reply = response.choices[0].message.content
        except Exception as e:
            logger.error(f"Chat-LLM ({self.chat_provider}) Fehler: {e}")
            reply = f"Entschuldigung, es gab einen Fehler bei der Verarbeitung: {e}"

        # Strip FORMAT-HINT from stored user message to keep history clean
        if format_hint and messages:
            last_user = messages[-1]
            if last_user.get("role") == "user" and format_hint in last_user.get("content", ""):
                last_user["content"] = last_user["content"].replace(format_hint, "").rstrip()

        messages.append({"role": "assistant", "content": reply})
        conv["last_activity"] = datetime.now().isoformat()
        self._save_conversation(session_id)

        return reply

    # ========================================================================
    # PHASE 1: TOOL-USE + STREAMING
    # ========================================================================

    def _build_spot_context_for_tool(self, spot: dict) -> dict:
        """Baut einen kompakten Spot-Eintrag für die Tool-Antwort an den LLM.

        Enthält Stammdaten + (falls vorhanden) Voranalyse-Kurzfassung pro Tag.
        Wird vom find_spots_within_travel_time Tool verwendet.
        """
        name = spot.get("name", "")
        entry = {
            "name": name,
            "fluggebiet": spot.get("fluggebiet", ""),
            "region": spot.get("region", ""),
            "elevation_m": spot.get("elevation_m"),
            "windrichtung": spot.get("windrichtung", ""),
            "latitude": spot.get("latitude"),
            "longitude": spot.get("longitude"),
        }
        # Voranalysen pro Tag (kompakt)
        analyses = self.spot_analyses.get(name, {}) if self.spot_analyses else {}
        if analyses:
            days_summary = {}
            for date_str, day in analyses.items():
                if not isinstance(day, dict):
                    continue
                safety = day.get("safety", {}) if isinstance(day.get("safety"), dict) else {}
                days_summary[date_str] = {
                    "safety_status": safety.get("safety_status") or day.get("safety_status"),
                    "fly_status": day.get("fly_status"),
                    "best_window": day.get("best_window"),
                    "recommendation": (day.get("recommendation") or "")[:240],
                }
            if days_summary:
                entry["analyses"] = days_summary
        return entry

    def _dispatch_tool(self, name: str, args: dict) -> dict:
        """Führt einen Tool-Call aus und gibt ein dispatch-Resultat zurück.

        Returns Dict mit:
            - "content": JSON-serialisierbares Resultat für den OpenAI tool-message
            - "map_actions": Liste von Map-Action-Events, die sofort ans Frontend
              gestreamt werden sollen (oder leere Liste).
        """
        if name == "geocode_location":
            query = (args.get("query") or "").strip()
            if not query:
                return {"content": {"error": "Leere Query"}, "map_actions": []}
            try:
                result = routing.geocode(query)
            except routing.RoutingError as e:
                return {
                    "content": {"error": f"Geocoding fehlgeschlagen: {e}"},
                    "map_actions": [],
                }
            if result is None:
                return {
                    "content": {"error": f"Ort '{query}' nicht gefunden"},
                    "map_actions": [],
                }
            return {"content": result, "map_actions": []}

        if name == "find_spots_within_travel_time":
            try:
                lat = float(args["lat"])
                lon = float(args["lon"])
                minutes = int(args["minutes"])
            except (KeyError, TypeError, ValueError) as e:
                return {
                    "content": {"error": f"Ungültige Parameter: {e}"},
                    "map_actions": [],
                }
            mode = (args.get("mode") or "auto").lower()
            label = (args.get("label") or "").strip()

            try:
                iso = routing.isochrone(lat, lon, minutes, mode)
            except (routing.RoutingError, ValueError) as e:
                return {
                    "content": {
                        "error": (
                            f"Routing-Service ist aktuell nicht erreichbar ({e}). "
                            "Bitte in ein paar Minuten erneut versuchen."
                        )
                    },
                    "map_actions": [],
                }

            try:
                matched = routing.spots_in_polygon(iso, self.spots)
            except routing.RoutingError as e:
                return {
                    "content": {"error": f"Spot-Filter fehlgeschlagen: {e}"},
                    "map_actions": [],
                }

            spot_entries = [self._build_spot_context_for_tool(s) for s in matched]
            spot_names = [s["name"] for s in matched if s.get("name")]

            mode_label = {
                "auto": "Auto",
                "bicycle": "Velo",
                "pedestrian": "zu Fuss",
            }.get(mode, mode)
            iso_label = f"{minutes} min {mode_label}"

            map_actions = [
                {
                    "type": "map_action",
                    "action": "drawIsochrone",
                    "payload": {"geojson": iso, "label": iso_label},
                },
                {
                    "type": "map_action",
                    "action": "setUserLocation",
                    "payload": {"lat": lat, "lon": lon, "label": label or "Standort"},
                },
                {
                    "type": "map_action",
                    "action": "highlightSpots",
                    "payload": {"spots": spot_names},
                },
            ]

            return {
                "content": {
                    "origin": {"lat": lat, "lon": lon, "label": label},
                    "minutes": minutes,
                    "mode": mode,
                    "count": len(spot_entries),
                    "spots": spot_entries,
                },
                "map_actions": map_actions,
            }

        if name == "clear_map_overlays":
            return {
                "content": {"ok": True},
                "map_actions": [
                    {
                        "type": "map_action",
                        "action": "clearAllOverlays",
                        "payload": {},
                    }
                ],
            }

        return {
            "content": {"error": f"Unbekanntes Tool '{name}'"},
            "map_actions": [],
        }

    def answer_stream(self, session_id: str, question: str):
        """Streaming-Variante von answer() mit Tool-Use.

        Generator: yieldet Events der Form
            {"type": "text",       "content": "..."}      # finaler Antworttext
            {"type": "map_action", "action": "...",       # Map-Update
                                   "payload": {...}}
            {"type": "status",     "content": "..."}      # optionale Statusnachricht
            {"type": "error",      "content": "..."}      # Fehler
            {"type": "done"}                              # Stream-Ende
        """
        if not self.chat_client:
            yield {
                "type": "error",
                "content": f"Kein API-Key fuer Chat-Provider '{self.chat_provider}' konfiguriert.",
            }
            yield {"type": "done"}
            return

        # FORMAT-HINT extrahieren (analog answer())
        format_hint = ""
        hint_match = re.search(r'\s*\[FORMAT-HINT:\s*[^\]]*\]', question)
        if hint_match:
            format_hint = hint_match.group(0)
            question_clean = question[:hint_match.start()] + question[hint_match.end():]
            question_clean = question_clean.strip()
        else:
            question_clean = question

        self._ensure_weather_context()
        if not self.weather_context_str:
            yield {
                "type": "text",
                "content": "Wetterdaten werden geladen... Bitte versuche es gleich nochmal.",
            }
            yield {"type": "done"}
            return

        self._ensure_spot_analyses()

        messages = self._get_or_create_conversation(session_id)
        conv = self.conversations[session_id]

        if conv["first_question"]:
            analyses_context = self._build_compact_analyses_for_chat()
            if analyses_context:
                foehn_snap = self._build_foehn_context_for_ai()
                context_block = analyses_context + "\n\n" + foehn_snap
            else:
                context_block = self.weather_context_str

            # Token-Budget: Kontext kürzen falls er das Modell-Limit sprengt
            model_limit = _MODEL_TOKEN_LIMITS.get(self.chat_model, _DEFAULT_TOKEN_LIMIT)
            system_tokens = _estimate_tokens(messages[0]["content"]) if messages else 0
            context_budget = model_limit - _TOKEN_BUDGET_RESERVE - system_tokens
            if context_budget > 0 and _estimate_tokens(context_block) > context_budget:
                context_block = _truncate_weather_context(context_block, context_budget)

            user_content = (
                f"AKTUELZEIT: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ({_weekday_de(datetime.now())})\n"
                "Hintergrunddaten für deine Antwort (nicht wörtlich als Gesamtreport ausgeben):\n"
                "==========================================================\n"
                f"{context_block}\n"
                "==========================================================\n"
                "Beantworte die Frage des Piloten **direkt** und in angemessenem Umfang — wie in einem "
                "kurzen Chat. Keine vollständige Tabelle aller Spots, es sei denn der Pilot verlangt "
                "ausdrücklich eine Übersicht/Tabelle **aller** Gebiete oder einen mehrzeiligen Vergleich.\n"
                'Bei **Föhn-Fragen**: die Föhn-Lage nur aus dem Block „FÖHN-INDIKATOR" (ΔP, Kammwind, Level) '
                'ableiten — nicht aus „alle Spots nicht sicher" schließen, dass es „keinen Föhn" gäbe.\n\n'
                f"Frage des Piloten: {question_clean}{format_hint}"
            )
            conv["first_question"] = False
        else:
            user_content = question_clean + format_hint

        messages.append({"role": "user", "content": user_content})

        # History trimmen
        if len(messages) > MAX_HISTORY_MESSAGES:
            messages[:] = messages[:2] + messages[-(MAX_HISTORY_MESSAGES - 2):]

        # ───── Tool-Call-Loop ────────────────────────────────────────────────
        reply_text = ""
        tool_iterations = 0
        emitted_status = False

        try:
            while True:
                if tool_iterations >= MAX_TOOL_ITERATIONS:
                    yield {
                        "type": "error",
                        "content": "Tool-Call-Limit erreicht. Bitte Frage neu formulieren.",
                    }
                    break

                response = self.chat_client.chat.completions.create(
                    model=self.chat_model,
                    messages=messages,
                    tools=TOOLS,
                    tool_choice="auto",
                    temperature=0.7,
                    max_tokens=2000,
                )
                _log_prompt_cache_usage(response, label="chat_stream")
                choice = response.choices[0]
                msg = choice.message
                finish_reason = choice.finish_reason

                # Falls Tool-Calls angefordert wurden: dispatchen
                tool_calls = getattr(msg, "tool_calls", None) or []
                if tool_calls:
                    # Assistant-Message mit tool_calls in History anhängen
                    messages.append({
                        "role": "assistant",
                        "content": msg.content or "",
                        "tool_calls": [
                            {
                                "id": tc.id,
                                "type": "function",
                                "function": {
                                    "name": tc.function.name,
                                    "arguments": tc.function.arguments,
                                },
                            }
                            for tc in tool_calls
                        ],
                    })

                    # Optional: einmaliger Status-Hinweis vor dem ersten Tool
                    if not emitted_status:
                        yield {
                            "type": "status",
                            "content": "Ich suche erreichbare Spots…",
                        }
                        emitted_status = True

                    for tc in tool_calls:
                        fn_name = tc.function.name
                        try:
                            fn_args = json.loads(tc.function.arguments or "{}")
                        except json.JSONDecodeError as e:
                            fn_args = {}
                            logger.warning(f"Tool {fn_name} arguments JSON invalid: {e}")

                        dispatch = self._dispatch_tool(fn_name, fn_args)

                        # Map-Actions sofort an Frontend streamen
                        for action in dispatch.get("map_actions", []):
                            yield action

                        # Tool-Resultat als tool-message in History
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc.id,
                            "name": fn_name,
                            "content": json.dumps(
                                dispatch.get("content", {}), ensure_ascii=False
                            ),
                        })

                    tool_iterations += 1
                    continue  # nächste LLM-Iteration

                # Kein Tool-Call mehr → finale Antwort
                reply_text = msg.content or ""
                messages.append({"role": "assistant", "content": reply_text})
                if reply_text:
                    yield {"type": "text", "content": reply_text}
                break

        except Exception as e:
            logger.error(f"Chat-LLM ({self.chat_provider}) Fehler (stream): {e}")
            yield {
                "type": "error",
                "content": f"Fehler bei der Verarbeitung: {e}",
            }

        # FORMAT-HINT aus letzter user-message strippen (analog answer())
        if format_hint:
            for m in reversed(messages):
                if m.get("role") == "user" and isinstance(m.get("content"), str) and format_hint in m["content"]:
                    m["content"] = m["content"].replace(format_hint, "").rstrip()
                    break

        conv["last_activity"] = datetime.now().isoformat()
        try:
            self._save_conversation(session_id)
        except Exception as e:
            logger.error(f"_save_conversation fehlgeschlagen: {e}")

        yield {"type": "done"}

