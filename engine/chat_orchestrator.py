"""
Wingcast Engine — Mixin: ChatOrchestratorMixin.

Ausgeschnitten aus chat_engine.py (Monolith-Split). Methoden-Signaturen
unveraendert, Klasse wird via Mehrfachvererbung in WingcastEngine eingebunden.
"""

import copy
import json
import logging
import math
import os
import re

from engine.wording_guard import soften_clearance
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
import i18n
from prompts import format_foehn_llm_regional_guide
import routing
from engine._common import (
    MAX_HISTORY_MESSAGES, MAX_TOOL_ITERATIONS,
    _MODEL_TOKEN_LIMITS, _DEFAULT_TOKEN_LIMIT, _TOKEN_BUDGET_RESERVE,
    _CTX_CACHE_MAX_ENTRIES,
    _estimate_tokens,
    _log_prompt_cache_usage, _weekday_de,
    _is_permanent_api_error, _user_friendly_api_error,
    _FLYABILITY_TIERS, _normalize_flyability_tier,
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
#   4. get_spot_analysis              — Volle Einzel-Voranalyse (Spot + Tag)
#   5. get_spot_weather               — Rohe stuendliche Wetterdaten (Spot + Tag)
#   6. get_region_analysis            — Volle Großwetter-Voranalyse (Region + Tag)
#   7. get_region_weather             — Rohe stuendliche Wetterdaten (Region + Tag)
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
                "einer maximalen Fahrzeit erreichen kann. Berechnet die ECHTE Fahrzeit zu "
                "jedem Gebiet und liefert sie als `travel_minutes` mit, nach Fahrzeit "
                "sortiert, inklusive Voranalyse-Daten (Sicherheit, Fliegbarkeit) für deine "
                "Empfehlung. Nenne die Fahrzeit beim Spot ('Weissenstein, 28 Min.') — sie "
                "ist die Zahl, die den Piloten interessiert. Schätze niemals selbst eine "
                "Fahrzeit und rechne nie Luftlinien in Fahrzeiten um. Beachte ein `notes`-"
                "Feld in der Antwort: Dort stehen Gebiete, die NICHT berechnet werden "
                "konnten, mit dem Grund."
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
    {
        "type": "function",
        "function": {
            "name": "get_spot_analysis",
            "description": (
                "Liefert die VOLLSTÄNDIGE Einzel-Voranalyse für EINEN Spot an EINEM Tag "
                "(no_go_reasons, caution_notes, primary_no_go, wind_summary, voller "
                "Empfehlungstext, Flyability-Details, XC-Potenzial). Nutze dieses Tool, "
                "wenn der Pilot nach Details/Begründung zu einem konkreten Spot fragt "
                "(z.B. 'Warum ist Niederbauen morgen nur conditional?'), denn die "
                "Kurzübersicht im Kontext enthält pro Spot nur Rating/Fenster/Status, "
                "nicht die ausführliche Begründung."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "spot_name": {
                        "type": "string",
                        "description": "Exakter Spot-Name wie in der Kurzübersicht (z.B. 'Niederbauen').",
                    },
                    "date": {
                        "type": "string",
                        "description": "Datum im Format YYYY-MM-DD (siehe DATUM-MAPPING in der Anfrage).",
                    },
                },
                "required": ["spot_name", "date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_spot_weather",
            "description": (
                "Liefert die ROHEN, stündlichen Wetterdaten für EINEN Spot an EINEM Tag "
                "(Wind/Böen am Boden + Höhenwind pro Druckfläche, Wolken, Niederschlag, "
                "Strahlung, Thermik-Proxy mit Steigwerten und Basis pro Stunde). Nutze "
                "dieses Tool, wenn der Pilot konkrete meteorologische Werte/Verläufe will "
                "(z.B. 'Wie stark wird der Wind um 14 Uhr am Brienzer Rothorn?', "
                "'Wann kippt der Wind?', 'Wie hoch geht die Basis?') — also Daten, die "
                "über die bewertete Voranalyse hinausgehen."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "spot_name": {
                        "type": "string",
                        "description": "Exakter Spot-Name wie in der Kurzübersicht (z.B. 'Brienzer Rothorn').",
                    },
                    "date": {
                        "type": "string",
                        "description": "Datum im Format YYYY-MM-DD (siehe DATUM-MAPPING in der Anfrage).",
                    },
                },
                "required": ["spot_name", "date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_region_analysis",
            "description": (
                "Liefert die VOLLSTÄNDIGE Großwetter-Voranalyse für EINE Region an EINEM "
                "Tag (Sicherheits-Status, experience_rating, bestes Fenster, Peak-Steigen, "
                "voller Empfehlungstext, Föhn-Lage der Region). Nutze dieses Tool für "
                "Fragen zur Gesamtlage eines Gebiets (z.B. 'Wie ist die Großwetterlage im "
                "Berner Oberland morgen?' oder 'Lohnt sich die Region Tessin überhaupt?'). "
                "Für einen konkreten Startplatz stattdessen get_spot_analysis nehmen."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "region_name": {
                        "type": "string",
                        "description": "Regionsname wie in der Kurzübersicht (z.B. 'Berner Oberland').",
                    },
                    "date": {
                        "type": "string",
                        "description": "Datum im Format YYYY-MM-DD (siehe DATUM-MAPPING in der Anfrage).",
                    },
                },
                "required": ["region_name", "date"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_region_weather",
            "description": (
                "Liefert die ROHEN, stündlichen Wetterdaten für EINE Region an EINEM Tag "
                "(Wind/Böen am Boden + Höhenwind pro Druckfläche, Wolken, Niederschlag, "
                "Strahlung, regionale Thermik mit Basis — aggregiert über die Region, "
                "ohne Spot-Windrichtungs-Check). Nutze dieses Tool für meteorologische "
                "Detailfragen zur Großwetterlage eines Gebiets (z.B. 'Wie entwickelt sich "
                "der Höhenwind über dem Wallis?')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "region_name": {
                        "type": "string",
                        "description": "Regionsname wie in der Kurzübersicht (z.B. 'Wallis').",
                    },
                    "date": {
                        "type": "string",
                        "description": "Datum im Format YYYY-MM-DD (siehe DATUM-MAPPING in der Anfrage).",
                    },
                },
                "required": ["region_name", "date"],
            },
        },
    },
]



def _chat_user_message(context_block: str, question: str, format_hint: str) -> str:
    """User-Nachricht des Chats: Zeit, Datums-Zuordnung, Kontext, Frage.

    DE-Wortlaut unveraendert (validierte Fassung). EN bekommt dieselbe Nachricht
    auf Englisch — vorher war sie auch im EN-Modus deutsch (10.10.2026)."""
    now = datetime.now()
    today = now.date()
    en = i18n.get_current_lang() == "en"
    if en:
        labels = ("TODAY", "TOMORROW", "DAY AFTER TOMORROW", "+3 days", "+4 days", "+5 days", "+6 days")
        wd = lambda d: d.strftime("%A")  # noqa: E731
    else:
        labels = ("HEUTE", "MORGEN", "ÜBERMORGEN", "+3 Tage", "+4 Tage", "+5 Tage", "+6 Tage")
        wd = _weekday_de
    date_map = "\n".join(
        f"  {lbl} = {(today + timedelta(days=i)).isoformat()} ({wd(today + timedelta(days=i))})"
        for i, lbl in enumerate(labels)
    )
    sep = "==========================================================\n"
    if en:
        return (
            f"CURRENT TIME: {now.strftime('%Y-%m-%d %H:%M:%S')} ({wd(now)})\n"
            f"DATE MAPPING (binding — when the pilot says 'tomorrow', it always means the date given here):\n"
            f"{date_map}\n"
            "Background data for your answer (do not output verbatim as a full report):\n"
            + sep + f"{context_block}\n" + sep +
            "Answer the pilot's question **directly** and at an appropriate length — like in a "
            "short chat. No full table of all spots unless the pilot explicitly asks for an "
            "overview/table of **all** areas or a multi-line comparison.\n"
            'For **foehn questions**: derive the foehn situation only from the block "FÖHN-INDIKATOR" '
            '(ΔP, crest wind, level) — do not conclude from "all spots with severe alerts" that there '
            'is "no foehn".\n\n'
            f"Pilot's question: {question}{format_hint}"
        )
    return (
        f"AKTUELZEIT: {now.strftime('%Y-%m-%d %H:%M:%S')} ({wd(now)})\n"
        f"DATUM-MAPPING (verbindlich — wenn der Pilot 'morgen' sagt, ist immer das hier gemeinte Datum gemeint):\n"
        f"{date_map}\n"
        "Hintergrunddaten für deine Antwort (nicht wörtlich als Gesamtreport ausgeben):\n"
        + sep + f"{context_block}\n" + sep +
        "Beantworte die Frage des Piloten **direkt** und in angemessenem Umfang — wie in einem "
        "kurzen Chat. Keine vollständige Tabelle aller Spots, es sei denn der Pilot verlangt "
        "ausdrücklich eine Übersicht/Tabelle **aller** Gebiete oder einen mehrzeiligen Vergleich.\n"
        'Bei **Föhn-Fragen**: die Föhn-Lage nur aus dem Block „FÖHN-INDIKATOR" (ΔP, Kammwind, Level) '
        'ableiten — nicht aus „alle Spots mit schweren Warnhinweisen" schließen, dass es „keinen Föhn" gäbe.\n\n'
        f"Frage des Piloten: {question}{format_hint}"
    )

def _tool_status_message(name: str, args: dict) -> str:
    """Verständliche Statusmeldung in Alltagssprache für einen Tool-Aufruf.

    Wird während des Tool-Loops ans Frontend gestreamt, damit der Pilot sieht,
    was der Assistent gerade tut — nie technische Namen wie 'orchestrator'.
    """
    spot = (args.get("spot_name") or "").strip()
    region = (args.get("region_name") or "").strip()
    if name == "geocode_location":
        q = (args.get("query") or "").strip()
        return i18n.t("chat.tool.geocode", q=q) if q else i18n.t("chat.tool.geocode_noarg")
    if name == "find_spots_within_travel_time":
        mins = args.get("minutes")
        return (i18n.t("chat.tool.find_spots", mins=mins)
                if mins else i18n.t("chat.tool.find_spots_noarg"))
    if name == "clear_map_overlays":
        return i18n.t("chat.tool.clear_map")
    if name == "get_spot_analysis":
        return (i18n.t("chat.tool.spot_analysis", spot=spot)
                if spot else i18n.t("chat.tool.spot_analysis_noarg"))
    if name == "get_spot_weather":
        return i18n.t("chat.tool.spot_weather", spot=spot) if spot else i18n.t("chat.tool.spot_weather_noarg")
    if name == "get_region_analysis":
        return (i18n.t("chat.tool.region_analysis", region=region)
                if region else i18n.t("chat.tool.region_analysis_noarg"))
    if name == "get_region_weather":
        return (i18n.t("chat.tool.region_weather", region=region)
                if region else i18n.t("chat.tool.region_weather_noarg"))
    return i18n.t("chat.tool.default")


class ChatOrchestratorMixin:
    def _get_or_create_conversation(self, session_id: str) -> list:
        """Holt bestehende Conversation oder erstellt neue mit globalem Kontext."""
        if session_id in self.conversations:
            return self.conversations[session_id]["messages"]

        messages = [
            {
                "role": "system",
                "content": prompts.SYSTEM_PROMPT + "\n\n" + prompts.CAPABILITIES_GUIDE + "\n\n" + prompts.FOEHN_CHAT_KNOWLEDGE
                           + i18n.llm_lang_instruction(),
            },
        ]
        self.conversations[session_id] = {
            "messages": messages,
            "last_activity": datetime.now().isoformat(),
            "first_question": True,
        }
        return messages

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

        if not self.weather_context_str:
            return i18n.t("chat.loading_weather")

        # Kompakte Voranalysen-Uebersicht (alle Spots, vollstaendig aber kurz) ist der
        # Chat-Kontext. Fehlt sie, ehrlich "wird geladen" antworten — nicht die Roh-
        # Wetterdaten kippen (sprengt das Token-Limit).
        analyses_context = self._build_compact_analyses_for_chat()
        if not analyses_context:
            return i18n.t("chat.loading_analyses")

        messages = self._get_or_create_conversation(session_id)
        conv = self.conversations[session_id]

        # Erste Frage: Kontext automatisch mitsenden
        if conv["first_question"]:
            # Kompakte Analyse enthält keinen globalen Föhn-Block — immer anhängen, sonst
            # antwortet das Modell bei „Föhn?" ohne ΔP/Kammwind und rät falsch.
            foehn_snap = self._build_foehn_context_for_ai()
            context_block = analyses_context + "\n\n" + foehn_snap

            # Sicherheitsnetz: passt fuer das konfigurierte 1M-Modell muehelos. Bei zu
            # kleinem Modell-Limit NICHT still kuerzen (sonst fehlen Spots unbemerkt),
            # sondern sichtbar warnen.
            model_limit = _MODEL_TOKEN_LIMITS.get(self.chat_model, _DEFAULT_TOKEN_LIMIT)
            system_tokens = _estimate_tokens(messages[0]["content"]) if messages else 0
            context_budget = model_limit - _TOKEN_BUDGET_RESERVE - system_tokens
            if context_budget > 0 and _estimate_tokens(context_block) > context_budget:
                logger.warning(
                    "Chat-Kontext (%d geschaetzte Tokens) ueberschreitet das Budget (%d) "
                    "fuer Modell %s — Antwort kann fehlschlagen. Groesseres Kontextmodell waehlen.",
                    _estimate_tokens(context_block), context_budget, self.chat_model,
                )

            user_content = _chat_user_message(context_block, question_clean, format_hint)
            conv["first_question"] = False
        else:
            user_content = question_clean + format_hint

        messages.append({"role": "user", "content": user_content})

        # Token-Management: History trimmen wenn zu lang
        if len(messages) > MAX_HISTORY_MESSAGES:
            # Behalte System-Prompt + erste User-Message (mit Wetterdaten) + letzte N Messages
            messages[:] = messages[:2] + messages[-(MAX_HISTORY_MESSAGES - 2):]

        # LLM Chat Call (Provider abhaengig: OpenAI / Anthropic / Gemini)
        reply_reasoning = None
        try:
            response = self.chat_client.chat.completions.create(
                model=self.chat_model,
                messages=messages,
                temperature=0.7,
                max_tokens=6000,
            )
            _log_prompt_cache_usage(response, label="chat_answer")
            _msg = response.choices[0].message
            reply = soften_clearance(_msg.content, label="chat")
            reply_reasoning = getattr(_msg, "reasoning_content", None)
        except Exception as e:
            logger.error(f"Chat-LLM ({self.chat_provider}) Fehler: {e}")
            reply = i18n.t("chat.err.processing", error=e)

        # Strip FORMAT-HINT from stored user message to keep history clean
        if format_hint and messages:
            last_user = messages[-1]
            if last_user.get("role") == "user" and format_hint in last_user.get("content", ""):
                last_user["content"] = last_user["content"].replace(format_hint, "").rstrip()

        _assistant_msg = {"role": "assistant", "content": reply}
        if reply_reasoning:
            _assistant_msg["reasoning_content"] = reply_reasoning
        messages.append(_assistant_msg)
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
        # Region des Spots ermitteln (für Region-Analyse-Lookup pro Tag)
        spot_region_id = None
        spot_region_name = None
        try:
            lat = spot.get("latitude")
            lon = spot.get("longitude")
            if lat is not None and lon is not None:
                region_obj = find_region_for_point(lat, lon)
                if region_obj:
                    spot_region_id = region_obj.get("id")
                    spot_region_name = region_obj.get("region") or spot_region_id
        except Exception:
            pass
        if spot_region_id:
            entry["region_id"] = spot_region_id
        region_days = (self.region_analyses or {}).get(spot_region_id, {}) if spot_region_id else {}

        # Voranalysen pro Tag (kompakt) — Rating-Architektur v2.0
        analyses = self.spot_analyses.get(name, {}) if self.spot_analyses else {}
        if analyses:
            days_summary = {}
            for date_str, day in analyses.items():
                if not isinstance(day, dict):
                    continue
                safety = day.get("safety", {}) if isinstance(day.get("safety"), dict) else {}
                xc = day.get("streckenflug") if isinstance(day.get("streckenflug"), dict) else {}
                day_entry = {
                    "safety_status": safety.get("safety_status") or day.get("safety_status"),
                    "experience_rating": day.get("experience_rating"),
                    "streckenflug_rating": xc.get("rating"),
                    "best_window": day.get("best_window"),
                    "recommendation": (day.get("recommendation") or "")[:240],
                }
                # Region-Analyse für denselben Tag mitliefern, damit das LLM
                # Spot vs. Region direkt vergleichen kann (Cap-Check).
                rday = region_days.get(date_str) if isinstance(region_days, dict) else None
                if isinstance(rday, dict):
                    rsafety = rday.get("safety", {}) if isinstance(rday.get("safety"), dict) else {}
                    rfly = rday.get("flyability", {}) if isinstance(rday.get("flyability"), dict) else {}
                    day_entry["region_analysis"] = {
                        "region_name": rday.get("region_name") or spot_region_name,
                        "experience_rating": rday.get("experience_rating"),
                        "safety_status": rsafety.get("safety_status"),
                        "best_window": rday.get("best_window") or rfly.get("best_window"),
                        "peak_climb_rate": rfly.get("peak_climb_rate") or rday.get("peak_climb_rate"),
                    }
                days_summary[date_str] = day_entry
            if days_summary:
                entry["analyses"] = days_summary
        return entry

    def _resolve_spot_by_name(self, query: str) -> dict | None:
        """Findet den Spot-Dict zu einem (ggf. ungenauen) Namen aus self.spots.

        Reihenfolge: exakt → case-insensitive → Teilstring. None wenn nichts passt.
        """
        q = (query or "").strip()
        if not q:
            return None
        for s in self.spots:
            if s.get("name") == q:
                return s
        q_low = q.lower()
        for s in self.spots:
            if (s.get("name") or "").lower() == q_low:
                return s
        for s in self.spots:
            if q_low in (s.get("name") or "").lower():
                return s
        return None

    def _resolve_region_by_name(self, query: str) -> dict | None:
        """Findet den Region-Dict zu einem (ggf. ungenauen) Namen via get_all_regions().

        Match auf Anzeigename ODER id: exakt → case-insensitive → Teilstring.
        """
        q = (query or "").strip()
        if not q:
            return None
        try:
            regions = get_all_regions()
        except Exception:
            return None
        q_low = q.lower()
        # exakt (Name oder id)
        for r in regions:
            if r.get("region") == q or r.get("id") == q:
                return r
        # case-insensitive
        for r in regions:
            if (r.get("region") or "").lower() == q_low or (r.get("id") or "").lower() == q_low:
                return r
        # Teilstring
        for r in regions:
            if q_low in (r.get("region") or "").lower() or q_low in (r.get("id") or "").lower():
                return r
        return None

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

            # ----------------------------------------------------------------
            # Nur Fahrzeiten, keine Flaeche mehr. Warum (alles am 27.09.2026
            # gemessen, Befund in validation/chat/BEFUNDE.md §7):
            #
            #   Die Flaeche (Isochrone) deckelt bei 60 Minuten — feste Hausregel
            #   des Gratis-Dienstes. Genau daran scheiterte am 25.09. die Frage
            #   "1h30 ab Grenchen", und die App gab die Grenze als Ausfall aus.
            #
            #   Die Fahrzeit kennt diese Grenze nicht (gemessen bis 241 Minuten)
            #   und liefert dem Piloten ausserdem die Zahl, die ihn interessiert
            #   ("Weissenstein, 30 Min.") statt eines Vielecks auf der Karte.
            #
            # Zeitbudget, weil das Nachfuellen einzelner Wege 0.77 s je Ziel
            # kostet und der Dienst parallele Anfragen sperrt. Was das Budget
            # nicht mehr schafft, wird benannt und liegt beim naechsten Mal im
            # Speicher — vorgewaermt per scripts/prewarm_travel_times.py.
            # ----------------------------------------------------------------

            # 1 · Vorfilter per Luftlinie: Die Fahrstrecke ist immer laenger als
            #     die Luftlinie, also kann hier kein echter Treffer verloren gehen.
            max_km = routing.max_straight_line_km(minutes)
            kandidaten = [
                s for s in self.spots
                if s.get("latitude") is not None and s.get("longitude") is not None
                and routing.haversine_km(lat, lon, s["latitude"], s["longitude"]) <= max_km
            ]
            if not kandidaten:
                return {
                    "content": {
                        "origin": {"lat": lat, "lon": lon, "label": label},
                        "minutes": minutes, "mode": mode, "count": 0, "spots": [],
                        "note": (
                            f"Kein Fluggebiet liegt innerhalb von {minutes} Minuten — "
                            f"das naechste ist weiter als {max_km:.0f} km Luftlinie weg."
                        ),
                    },
                    "map_actions": [],
                }

            # 2 · Fahrzeiten holen (Sammelabfrage + Einzelwege im Budget).
            try:
                zeiten = routing.travel_times(
                    lat, lon,
                    [(s["latitude"], s["longitude"]) for s in kandidaten],
                    mode,
                    budget_seconds=config.TRAVEL_TIME_CHAT_BUDGET_S,
                )
            except (routing.RoutingError, ValueError) as e:
                # Der Hinweis geht als eigenes Ereignis an den Chat, nicht nur als
                # Anweisung an das LLM: Eine Prompt-Regel wird verletzt, sobald sie
                # unbequem ist, und dann steht der Pilot wieder vor einer Antwort,
                # die die Luecke verschweigt (25.09.2026, BEFUNDE.md §7).
                logger.warning("Reichweiten-Suche ohne Ergebnis: %s", e)
                return {
                    "content": {
                        "error": (
                            f"Fahrzeiten sind gerade nicht berechenbar ({e}). Sage das "
                            "offen und nenne die Gebiete in seiner Naehe ohne Fahrzeit — "
                            "schaetze keine und rechne keine Luftlinie um."
                        )
                    },
                    "map_actions": [{
                        "type": "map_action", "action": "showNotice",
                        "payload": {"text": i18n.t("chat.reach.none")},
                    }],
                }

            # 3 · Treffer nach Fahrzeit; was keine Zahl hat, wird benannt.
            map_actions_notice: list = []
            treffer, offen_gruende = [], {"budget": [], "limit": [], "no_route": []}
            for spot, z in zip(kandidaten, zeiten):
                m = z.get("minutes")
                if m is None:
                    offen_gruende.setdefault(z.get("reason") or "no_route", []).append(
                        spot.get("name", "")
                    )
                    continue
                if m <= minutes:
                    treffer.append((int(round(m)), spot))
            treffer.sort(key=lambda p: p[0])

            eintraege = []
            for m, spot in treffer:
                entry = self._build_spot_context_for_tool(spot)
                entry["travel_minutes"] = m
                eintraege.append(entry)

            notes = []
            if offen_gruende["budget"]:
                notes.append(
                    f"Fuer {len(offen_gruende['budget'])} weitere Gebiete war die Fahrzeit "
                    f"in der Antwortzeit nicht mehr zu berechnen. Sage dem Piloten in einem "
                    f"Satz, dass die Liste noch nicht vollstaendig ist und eine erneute "
                    f"Frage mehr Gebiete bringt — hier hilft ein zweiter Versuch wirklich."
                )
            if offen_gruende["limit"]:
                notes.append(
                    f"{len(offen_gruende['limit'])} Gebiete liegen weiter als die "
                    f"{config.VALHALLA_MAX_MATRIX_KM:.0f} km, die der Kartendienst je Route "
                    f"rechnet. Feste Grenze, kein Ausfall — biete dort keinen erneuten "
                    f"Versuch an."
                )
            if offen_gruende["no_route"]:
                notes.append(
                    f"{len(offen_gruende['no_route'])} Gebiete ohne Strassenverbindung im "
                    f"Modus '{mode}': " + ", ".join(offen_gruende["no_route"][:5])
                )

            # Sichtbare Rueckmeldung, unabhaengig vom Antworttext des Modells.
            # "budget" ist der Fall, in dem ein zweiter Versuch wirklich hilft —
            # "limit" der, in dem er nie hilft. Die zwei duerfen nie verwechselt
            # werden, das war der ganze Fehler vom 25.09.2026.
            hinweise = []
            if offen_gruende["budget"]:
                hinweise.append(i18n.t(
                    "chat.reach.partial",
                    fehlend=len(offen_gruende["budget"]),
                    gesamt=len(eintraege) + len(offen_gruende["budget"]),
                ))
            if offen_gruende["limit"]:
                hinweise.append(i18n.t(
                    "chat.reach.limit", anzahl=len(offen_gruende["limit"]),
                ))
            for text in hinweise:
                map_actions_notice.append({
                    "type": "map_action", "action": "showNotice",
                    "payload": {"text": text},
                })

            return {
                "content": {
                    "origin": {"lat": lat, "lon": lon, "label": label},
                    "minutes": minutes,
                    "mode": mode,
                    "count": len(eintraege),
                    "spots": eintraege,
                    "hinweis_fahrzeit": (
                        "travel_minutes ist die echte Fahrzeit in Minuten. Nenne sie beim "
                        "Spot ('Weissenstein, 30 Min.'); die Liste ist danach sortiert. "
                        "Schaetze niemals selbst eine Fahrzeit und rechne keine Luftlinie "
                        "in eine Fahrzeit um."
                    ),
                    **({"notes": notes} if notes else {}),
                },
                "map_actions": [
                    {"type": "map_action", "action": "setUserLocation",
                     "payload": {"lat": lat, "lon": lon, "label": label or "Standort"}},
                    {"type": "map_action", "action": "highlightSpots",
                     "payload": {"spots": [e["name"] for e in eintraege if e.get("name")]}},
                ] + map_actions_notice,
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

        if name == "get_spot_analysis":
            spot_query = (args.get("spot_name") or "").strip()
            date_str = (args.get("date") or "").strip()
            if not spot_query or not date_str:
                return {"content": {"error": "spot_name und date sind erforderlich"}, "map_actions": []}
            spot = self._resolve_spot_by_name(spot_query)
            if not spot:
                return {"content": {"error": f"Spot '{spot_query}' nicht gefunden"}, "map_actions": []}
            canonical = spot["name"]
            days = self.spot_analyses.get(canonical)
            if not days:
                return {"content": {"error": f"Keine Voranalyse für '{canonical}' vorhanden"}, "map_actions": []}
            entry = days.get(date_str)
            if not entry:
                return {
                    "content": {
                        "error": f"Keine Analyse für '{canonical}' am {date_str}",
                        "available_dates": sorted(days.keys()),
                    },
                    "map_actions": [],
                }
            return {
                "content": {"spot": canonical, "date": date_str, "analysis": entry},
                "map_actions": [],
            }

        if name == "get_spot_weather":
            spot_query = (args.get("spot_name") or "").strip()
            date_str = (args.get("date") or "").strip()
            if not spot_query or not date_str:
                return {"content": {"error": "spot_name und date sind erforderlich"}, "map_actions": []}
            spot = self._resolve_spot_by_name(spot_query)
            if not spot:
                return {"content": {"error": f"Spot '{spot_query}' nicht gefunden"}, "map_actions": []}
            canonical = spot["name"]
            try:
                ctx = self._build_single_spot_context(spot, date_str, mode="chat")
            except Exception as e:
                logger.error(f"get_spot_weather Fehler für {canonical}/{date_str}: {e}")
                return {"content": {"error": f"Wetterdaten konnten nicht aufbereitet werden: {e}"}, "map_actions": []}
            if not ctx or not ctx.strip():
                return {"content": {"error": f"Keine Wetterdaten für '{canonical}' am {date_str}"}, "map_actions": []}
            return {
                "content": {"spot": canonical, "date": date_str, "weather": ctx},
                "map_actions": [],
            }

        if name == "get_region_analysis":
            region_query = (args.get("region_name") or "").strip()
            date_str = (args.get("date") or "").strip()
            if not region_query or not date_str:
                return {"content": {"error": "region_name und date sind erforderlich"}, "map_actions": []}
            region = self._resolve_region_by_name(region_query)
            if not region:
                return {"content": {"error": f"Region '{region_query}' nicht gefunden"}, "map_actions": []}
            rid = region["id"]
            rname = region.get("region", rid)
            days = (self.region_analyses or {}).get(rid)
            if not days:
                return {"content": {"error": f"Keine Voranalyse für Region '{rname}' vorhanden"}, "map_actions": []}
            entry = days.get(date_str)
            if not entry:
                return {
                    "content": {
                        "error": f"Keine Analyse für Region '{rname}' am {date_str}",
                        "available_dates": sorted(days.keys()),
                    },
                    "map_actions": [],
                }
            return {
                "content": {"region": rname, "date": date_str, "analysis": entry},
                "map_actions": [],
            }

        if name == "get_region_weather":
            region_query = (args.get("region_name") or "").strip()
            date_str = (args.get("date") or "").strip()
            if not region_query or not date_str:
                return {"content": {"error": "region_name und date sind erforderlich"}, "map_actions": []}
            region = self._resolve_region_by_name(region_query)
            if not region:
                return {"content": {"error": f"Region '{region_query}' nicht gefunden"}, "map_actions": []}
            rname = region.get("region", region["id"])
            try:
                ctx = self._build_single_region_context(region, date_str)
            except Exception as e:
                logger.error(f"get_region_weather Fehler für {rname}/{date_str}: {e}")
                return {"content": {"error": f"Wetterdaten konnten nicht aufbereitet werden: {e}"}, "map_actions": []}
            if not ctx or not ctx.strip():
                return {"content": {"error": f"Keine Wetterdaten für Region '{rname}' am {date_str}"}, "map_actions": []}
            return {
                "content": {"region": rname, "date": date_str, "weather": ctx},
                "map_actions": [],
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

        if not self.weather_context_str:
            yield {
                "type": "text",
                "content": i18n.t("chat.loading_weather"),
            }
            yield {"type": "done"}
            return

        # Der Chat braucht die kompakte Voranalysen-Uebersicht (alle Spots, vollstaendig
        # aber kurz) als Kontext. Fehlt sie (Cache noch nicht geladen), antworten wir
        # ehrlich mit "wird geladen" — statt die kompletten Roh-Wetterdaten zu kippen,
        # die das Token-Limit des Modells sprengen.
        analyses_context = self._build_compact_analyses_for_chat()
        if not analyses_context:
            yield {
                "type": "text",
                "content": i18n.t("chat.loading_analyses"),
            }
            yield {"type": "done"}
            return

        messages = self._get_or_create_conversation(session_id)
        conv = self.conversations[session_id]

        def _build_full_user_content() -> str:
            """Volle User-Message: AKTUELZEIT + DATUM-MAPPING + Voranalysen-Kontext + Frage.
            Wird beim ersten Turn UND beim Reset-Retry verwendet."""
            foehn_snap = self._build_foehn_context_for_ai()
            context_block_local = analyses_context + "\n\n" + foehn_snap

            # Sicherheitsnetz: Die kompakte Uebersicht passt fuer das konfigurierte
            # Modell (1M Kontext) muehelos. Sollte sie ein kleineres Modell-Limit doch
            # sprengen, NICHT still kuerzen (sonst fehlen dem Berater Spots, ohne dass
            # es jemand merkt) — sondern sichtbar warnen.
            model_limit = _MODEL_TOKEN_LIMITS.get(self.chat_model, _DEFAULT_TOKEN_LIMIT)
            system_tokens = _estimate_tokens(messages[0]["content"]) if messages else 0
            context_budget = model_limit - _TOKEN_BUDGET_RESERVE - system_tokens
            if context_budget > 0 and _estimate_tokens(context_block_local) > context_budget:
                logger.warning(
                    "Chat-Kontext (%d geschaetzte Tokens) ueberschreitet das Budget (%d) "
                    "fuer Modell %s — Antwort kann fehlschlagen. Groesseres Kontextmodell waehlen.",
                    _estimate_tokens(context_block_local), context_budget, self.chat_model,
                )

            return _chat_user_message(context_block_local, question_clean, format_hint)

        if conv["first_question"]:
            user_content = _build_full_user_content()
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
        last_status = None  # letzte gestreamte Statusmeldung (gegen Doppelungen)
        reasoning_retry_done = False

        try:
            while True:
                if tool_iterations >= MAX_TOOL_ITERATIONS:
                    yield {
                        "type": "error",
                        "content": "Tool-Call-Limit erreicht. Bitte Frage neu formulieren.",
                    }
                    break

                try:
                    response = self.chat_client.chat.completions.create(
                        model=self.chat_model,
                        messages=messages,
                        tools=TOOLS,
                        tool_choice="auto",
                        temperature=0.7,
                        max_tokens=6000,
                    )
                except Exception as api_err:
                    # Recovery: alte Conversation-Files koennen Assistant-Messages ohne
                    # reasoning_content enthalten (gespeichert vor diesem Fix). DeepSeek
                    # Thinking-Mode lehnt das mit 400 ab. Einmaliger Reset + Retry mit
                    # voller Kontext-Message, damit der LLM nicht ohne Wetterdaten antwortet.
                    err_str = str(api_err)
                    if not reasoning_retry_done and "reasoning_content" in err_str:
                        logger.warning(
                            "Chat-API Error 'reasoning_content' — History wird zurueckgesetzt, retry mit vollem Kontext."
                        )
                        sys_msg = messages[0] if messages and messages[0].get("role") == "system" else None
                        new_messages = []
                        if sys_msg:
                            new_messages.append(sys_msg)
                        new_messages.append({"role": "user", "content": _build_full_user_content()})
                        messages[:] = new_messages
                        conv["first_question"] = False
                        reasoning_retry_done = True
                        continue
                    raise
                _log_prompt_cache_usage(response, label="chat_stream")
                choice = response.choices[0]
                msg = choice.message
                finish_reason = choice.finish_reason

                # Falls Tool-Calls angefordert wurden: dispatchen
                tool_calls = getattr(msg, "tool_calls", None) or []
                if tool_calls:
                    # DeepSeek-V4 Thinking-Mode: reasoning_content muss zurueck an die API
                    # (sonst Error 400 "reasoning_content must be passed back").
                    assistant_msg = {
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
                    }
                    reasoning = getattr(msg, "reasoning_content", None)
                    if reasoning:
                        assistant_msg["reasoning_content"] = reasoning
                    messages.append(assistant_msg)

                    for tc in tool_calls:
                        fn_name = tc.function.name
                        try:
                            fn_args = json.loads(tc.function.arguments or "{}")
                        except json.JSONDecodeError as e:
                            fn_args = {}
                            logger.warning(f"Tool {fn_name} arguments JSON invalid: {e}")

                        # Verständlicher Status in Alltagssprache, passend zum Tool.
                        # Spot-/Regionsnamen auf die kanonische Schreibweise auflösen,
                        # damit der Status nicht die (evtl. klein/ungenau) getippte
                        # Modell-Eingabe zeigt. Standort (geocode) bleibt der genannte
                        # Ort — vor dem Geocoding gibt es noch keine aufgelöste Form.
                        display_args = fn_args
                        _sp = fn_args.get("spot_name")
                        _rg = fn_args.get("region_name")
                        if _sp:
                            _r = self._resolve_spot_by_name(_sp)
                            if _r:
                                display_args = {**fn_args, "spot_name": _r["name"]}
                        elif _rg:
                            _r = self._resolve_region_by_name(_rg)
                            if _r:
                                display_args = {**fn_args, "region_name": _r.get("region", _rg)}
                        status_msg = _tool_status_message(fn_name, display_args)
                        if status_msg and status_msg != last_status:
                            yield {"type": "status", "content": status_msg}
                            last_status = status_msg

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
                reply_text = soften_clearance(msg.content or "", label="chat")
                final_msg = {"role": "assistant", "content": reply_text}
                final_reasoning = getattr(msg, "reasoning_content", None)
                if final_reasoning:
                    final_msg["reasoning_content"] = final_reasoning
                messages.append(final_msg)
                if reply_text:
                    yield {"type": "text", "content": reply_text}
                break

        except Exception as e:
            logger.error(f"Chat-LLM ({self.chat_provider}) Fehler (stream): {e}")
            yield {
                "type": "error",
                "content": i18n.t("chat.err.processing", error=e),
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

