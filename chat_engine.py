"""
Chat-Engine für Gleitcast.
Zentrale Klasse die Pilotenfragen beantwortet.
Globaler Wetterdaten-Kontext + Per-User Conversation History.
"""

import os
import json
import logging
import re
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed, wait, FIRST_COMPLETED
from datetime import datetime, timedelta
from pathlib import Path

import config
from llm_client import build_client
from spots import load_spots
from fetch_weather import fetch_all_spots, load_cached_weather, load_cached_weather_timestamp, is_cache_fresh, is_cache_complete, validate_spot_data
from foehn_indicators import (
    fetch_foehn_data,
    evaluate_foehn,
    build_foehn_llm_context,
)
from thermik_calculator import calculate_thermal_profile, calculate_dewpoint, get_terrain_zone
from gust_calculator import (
    estimate_altitude_gusts,
    collect_gust_anchors,
    estimate_altitude_gusts_multi_anchor,
    interpolate_gust_from_anchors,
    apply_oi_gust_correction,
    aggregate_spot_excess,
)
from prompts import (
    SYSTEM_PROMPT,
    CAPABILITIES_GUIDE,
    FOEHN_CHAT_KNOWLEDGE,
    SPOT_COMBINED_PROMPT,
    REGION_COMBINED_PROMPT,
    WEEKLY_BRIEFING_PROMPT,
    format_foehn_llm_regional_guide,
)
from source_area import get_all_regions, find_region_for_point
from station_observations import StationManager
import routing

logger = logging.getLogger(__name__)

# ============================================================================
# Konstanten + Pure-Helpers → engine/_common.py (Phase 2 Refactor)
# Re-Exports fuer Backwards-Compatibility (bestehender Code importiert aus chat_engine).
# ============================================================================
from engine._common import (
    MAX_HISTORY_MESSAGES,
    _MODEL_TOKEN_LIMITS,
    _DEFAULT_TOKEN_LIMIT,
    _TOKEN_BUDGET_RESERVE,
    _CTX_CACHE_MAX_ENTRIES,
    MAX_TOOL_ITERATIONS,
    _estimate_tokens,
    _log_prompt_cache_usage,
    _truncate_weather_context,
    _filter_context_by_days,
    _WOCHENTAGE,
    _weekday_de,
    _is_permanent_api_error,
    _user_friendly_api_error,
)

# ============================================================================
# OPENAI TOOL SCHEMAS (Phase 1: Standort-basierte Spot-Filterung)
# ============================================================================
# Drei Tools für den Chat-Use-Case:
#   1. geocode_location — Adresse / Stadt → Koordinaten
#   2. find_spots_within_travel_time — Isochrone + Spot-Filter (Hauptfunktion)
#   3. clear_map_overlays — Karten-Overlays zurücksetzen
#
# Nach Erhalt eines Tool-Calls dispatcht answer_stream() an _dispatch_tool(),
# yieldet sofort map_action-Events ans Frontend und ruft danach erneut OpenAI auf.

# TOOLS ist jetzt in engine/chat_orchestrator.py definiert (wird dort genutzt).
# Re-Export fuer Rueckwaertskompat falls externer Code `from chat_engine import TOOLS` nutzt.
from engine.chat_orchestrator import TOOLS  # noqa: F401


# ============================================================================
# Flyability-Tier + Rating, Tag-Sanitization, Primary-Labels, Wind-Trend,
# Rain-Sandwich, Altitude-Interpolation → alle nach engine._common (Phase 2).
# Re-Exports fuer Backwards-Compat innerhalb dieses Moduls.
# ============================================================================
from engine._common import (
    _FLYABILITY_TIERS,
    _normalize_flyability_tier,
    _TIER_RATING_RANGES,
    _clamp_rating_to_tier,
    _compute_rating_from_subratings,
    _TAG_NATURAL, _TAG_NATURAL_MAP, _TAG_SANITIZE_RE,
    _sanitize_llm_text, _sanitize_llm_result,
    _LABEL_KEYS_NO_GO, _LABEL_KEYS_CONDITIONAL,
    _LABEL_KEYS_REDUCER, _LABEL_KEYS_BOOSTER,
    _NO_GO_RANK, _CONDITIONAL_RANK,
    _KEYWORD_TO_KEY_NO_GO, _KEYWORD_TO_KEY_CAUTION,
    _pick_key_from_list, _validate_key, _derive_primary_labels,
    COMPASS_POINTS,
    _compute_wind_trend,
    _detect_rain_sandwich,
    _interpolate_wind_at_altitude,
)



from engine.weather_context import WeatherContextMixin
from engine.analyzers import AnalyzersMixin
from engine.chat_orchestrator import ChatOrchestratorMixin


class GleitcastEngine(ChatOrchestratorMixin, AnalyzersMixin, WeatherContextMixin):
    def __init__(self, instantdb_client=None):
        self.spots = load_spots()
        self.weather_data = {}
        self.weather_context_str = ""
        self.weather_loaded_at = None
        self.foehn_data = None
        self.conversations = {}
        self.instantdb = instantdb_client
        self.spot_analyses = {}
        self.analyses_loaded_at = None
        self._analyses_stale = False  # True nach Wetter-Refresh, bis neue Analysen da sind
        self.region_weather_data = {}
        self.region_analyses = {}
        self.region_analyses_loaded_at = None
        # Fix B: Tracking ob letzter refresh_weather() echt war oder Stale-Fallback
        self.last_refresh_stale = False
        self.last_refresh_status_reason = None

        # Cache fuer Boeen-Floor Enforcement (Post-hoc LLM-Override):
        # Key = f"{spot_name}|{date_str}", Value = dict mit gust-warn/danger Zaehlern.
        # Wird in _build_single_spot_context geschrieben (Main-Thread, sequentiell)
        # und in _safety_check_single_spot_day gelesen (Worker-Threads). Thread-safe,
        # weil Keys vor dem Submit gesetzt sind und danach nur gelesen werden.
        self._ctx_gust_cache = {}
        # Cache fuer Thermik-Qualitaet (Flyability-Override bei falschem gray):
        # Key = f"{name}|{date_str}", Value = dict mit thermal_hours_total, tq_danger_h, peak_climb_proxy
        self._ctx_tq_cache = {}

        # LLM-Clients: Chat + Analyse getrennt konfigurierbar (config.py).
        # Hybrid-Setup moeglich (z.B. Chat=anthropic, Analyse=openai).
        self.chat_provider = config.CHAT_PROVIDER
        self.analysis_provider = config.ANALYSIS_PROVIDER
        self.chat_model = config.get_model(self.chat_provider, "chat")
        self.analysis_model = config.get_model(self.analysis_provider, "analysis")
        self.chat_client = build_client(
            self.chat_provider, config.get_api_key(self.chat_provider), timeout=120.0
        )
        # Wenn Chat- und Analyse-Provider identisch sind UND gleicher Key → Client teilen
        if (
            self.analysis_provider == self.chat_provider
            and self.chat_client is not None
        ):
            self.analysis_client = self.chat_client
        else:
            self.analysis_client = build_client(
                self.analysis_provider,
                config.get_api_key(self.analysis_provider),
                timeout=120.0,
            )

        # Rueckwaertskompatibilitaet: self.client/self.model zeigen auf CHAT-Slot.
        # Bestehender Code, der self.client/self.model noch direkt nutzt, bleibt funktional.
        self.client = self.chat_client
        self.model = self.chat_model
        logger.info(
            "LLM-Setup: chat=%s/%s, analysis=%s/%s",
            self.chat_provider, self.chat_model,
            self.analysis_provider, self.analysis_model,
        )

        # History-Persistenz
        self.history_dir = config.HISTORY_DIR
        self.history_dir.mkdir(parents=True, exist_ok=True)
        self._load_all_conversations()

        # Analyse-Persistenz
        self.analyses_file = config.DATA_DIR / "spot_analyses.json"
        self.region_analyses_file = config.DATA_DIR / "region_analyses.json"
        self._load_analyses_cache()

        # Stationsdaten + Bias-Korrektur
        try:
            self.station_manager = StationManager(config.STATION_DB_PATH, self.spots)
            if self.station_manager.needs_discovery():
                print("[ENGINE] Erste Station-Discovery wird durchgeführt...")
                self.station_manager.discover_stations()
                if self.station_manager.needs_backfill():
                    print("[ENGINE] Backfill historischer Stationsdaten...")
                    self.station_manager.backfill_observations()
        except Exception as e:
            logger.error(f"StationManager Init fehlgeschlagen: {e}")
            self.station_manager = None

    def _load_all_conversations(self):
        """Lädt alle Conversations aus dem history-Verzeichnis."""
        for filename in os.listdir(self.history_dir):
            if filename.endswith(".json"):
                session_id = filename[:-5]
                try:
                    with open(self.history_dir / filename, "r", encoding="utf-8") as f:
                        self.conversations[session_id] = json.load(f)
                except Exception as e:
                    logger.error(f"Fehler beim Laden der History {session_id}: {e}")

    def _ctx_cache_put(self, cache: dict, key: str, value):
        """Setzt cache[key]=value mit Hard-Cap-Guard gegen Leaks bei Clear-Fehlern."""
        if len(cache) >= _CTX_CACHE_MAX_ENTRIES and key not in cache:
            logger.warning(
                "ctx-cache Overflow (%d Eintraege) — force-clear zur Vermeidung eines Leaks",
                len(cache),
            )
            cache.clear()
        cache[key] = value

    def _save_conversation(self, session_id: str):
        """Speichert eine Conversation als JSON."""
        if session_id not in self.conversations:
            return
        try:
            with open(self.history_dir / f"{session_id}.json", "w", encoding="utf-8") as f:
                json.dump(self.conversations[session_id], f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Fehler beim Speichern der History {session_id}: {e}")

    def _get_pg_client(self):
        """Lazy Postgres-Client Getter (identisch zu fetch_weather._get_pg_client)."""
        try:
            from fetch_weather import _get_pg_client
            return _get_pg_client()
        except Exception:
            return None

    def _load_analyses_cache(self):
        """Laedt Spot- und Region-Analysen.
        Primaer aus Postgres, Fallback auf JSON-Files. Pusht bei Erfolg nach InstantDB.
        """
        loaded_any = False

        client = self._get_pg_client()
        pg_loaded = False
        if client is not None:
            try:
                spot_pg = client.get_all_spot_analyses()
                region_pg = client.get_all_region_analyses()
                if spot_pg:
                    self.spot_analyses = spot_pg
                    self.analyses_loaded_at = datetime.now()
                    print(f"[ENGINE] {len(spot_pg)} Spot-Analysen aus Postgres geladen.")
                    loaded_any = True
                    pg_loaded = True
                if region_pg:
                    self.region_analyses = region_pg
                    self.region_analyses_loaded_at = datetime.now()
                    print(f"[ENGINE] {len(region_pg)} Region-Analysen aus Postgres geladen.")
                    loaded_any = True
                    pg_loaded = True
            except Exception as e:
                logger.error(f"Postgres-Load Analysen fehlgeschlagen, nutze JSON-Fallback: {e}")

        # Fallback auf JSON wenn Postgres leer oder nicht verfuegbar
        if not pg_loaded:
            if self.analyses_file.exists():
                try:
                    with open(self.analyses_file, "r", encoding="utf-8") as f:
                        self.spot_analyses = json.load(f)
                        self.analyses_loaded_at = datetime.fromtimestamp(self.analyses_file.stat().st_mtime)
                    print(f"[ENGINE] {len(self.spot_analyses)} Spot-Analysen aus JSON-Cache geladen.")
                    loaded_any = True
                except Exception as e:
                    logger.error(f"Fehler beim Laden des Spot-Analyse-Caches: {e}")
            if self.region_analyses_file.exists():
                try:
                    with open(self.region_analyses_file, "r", encoding="utf-8") as f:
                        self.region_analyses = json.load(f)
                        self.region_analyses_loaded_at = datetime.fromtimestamp(
                            self.region_analyses_file.stat().st_mtime)
                    print(f"[ENGINE] {len(self.region_analyses)} Region-Analysen aus JSON-Cache geladen.")
                    loaded_any = True
                except Exception as e:
                    logger.error(f"Fehler beim Laden des Region-Analyse-Caches: {e}")

        # Push nach InstantDB damit Frontend-Subscriptions sofort Daten haben
        if loaded_any and self.instantdb:
            if self.spot_analyses:
                threading.Thread(target=self._push_analyses_to_instantdb, daemon=True).start()
            if self.region_analyses:
                threading.Thread(target=self._push_region_analyses_to_instantdb, daemon=True).start()

    def _save_analyses_cache(self):
        """Speichert Spot-Analysen (Postgres primaer, JSON-File als Fallback/Backup)."""
        # 1. Postgres
        client = self._get_pg_client()
        if client is not None:
            try:
                client.upsert_spot_analyses(self.spot_analyses)
            except Exception as e:
                logger.error(f"Postgres-Save Spot-Analysen fehlgeschlagen: {e}")
        # 2. JSON (Backup/Fallback)
        try:
            config.atomic_write_json(self.analyses_file, self.spot_analyses)
        except Exception as e:
            logger.error(f"Fehler beim Speichern des Spot-Analyse-Caches: {e}")

    def _save_region_analyses_cache(self):
        """Speichert Region-Analysen (Postgres primaer, JSON-File als Fallback/Backup)."""
        client = self._get_pg_client()
        if client is not None:
            try:
                client.upsert_region_analyses(self.region_analyses)
            except Exception as e:
                logger.error(f"Postgres-Save Region-Analysen fehlgeschlagen: {e}")
        try:
            config.atomic_write_json(self.region_analyses_file, self.region_analyses)
        except Exception as e:
            logger.error(f"Fehler beim Speichern des Region-Analyse-Caches: {e}")

    def _clear_analyses_cache(self):
        """Löscht Analyse-Cache (bei fehlenden/veralteten Wetterdaten)."""
        try:
            if self.analyses_file.exists():
                self.analyses_file.unlink()
            if self.region_analyses_file.exists():
                self.region_analyses_file.unlink()
            # Auch Postgres leeren damit kein Zombie-State zurueckbleibt
            client = self._get_pg_client()
            if client is not None:
                try:
                    client.delete_spot_analyses()
                    client.delete_region_analyses()
                except Exception as e:
                    logger.error(f"Postgres-Clear Analysen fehlgeschlagen: {e}")
            print("[ENGINE] Analyse-Cache gelöscht (Wetterdaten fehlen)")
        except Exception as e:
            logger.error(f"Fehler beim Löschen des Analyse-Caches: {e}")

    def load_weather_from_cache(self):
        """Lädt Wetterdaten aus lokalem JSON-Cache (kein API-Call).
        Wird beim Serverstart aufgerufen, damit Meteogramme sofort verfügbar sind."""
        cached = load_cached_weather()
        if not cached:
            logger.info("[ENGINE] Kein Wetter-Cache vorhanden")
            return False

        self.weather_data = cached
        self.region_weather_data = cached.pop("_regions", {}) if "_regions" in cached else {}

        # Föhn-Daten separat laden (kleiner API-Call, schnell)
        try:
            self.foehn_data = fetch_foehn_data(forecast_days=config.FORECAST_DAYS)
        except Exception as e:
            logger.error(f"Föhn-Daten fehlgeschlagen: {e}")
            self.foehn_data = None

        self.weather_context_str = self._build_weather_context()
        self.weather_loaded_at = load_cached_weather_timestamp()

        # Analysen-Cache laden
        self._load_analyses_cache()

        spot_count = len([k for k in self.weather_data if not k.startswith("_")])
        logger.info(f"[ENGINE] Wetterdaten aus Cache geladen ({spot_count} Spots)")
        return True

    def refresh_weather(self, force=False):
        """Wetterdaten für alle Spots holen + Kontext-String bauen."""
        print("[ENGINE] Lade Wetterdaten für alle Spots...")
        self.spots = load_spots() # Reload spots to pick up CSV changes

        # Fix B: Reset stale-tracking am Start jedes Refresh-Versuchs
        self.last_refresh_stale = False
        self.last_refresh_status_reason = None

        # 1. Wetterdaten holen (oder Cache nutzen)
        if not force and is_cache_fresh(max_age_hours=12) and is_cache_complete():
            print("[ENGINE] Nutze gecachte Wetterdaten (vollständig)")
            cached = load_cached_weather()
            self.weather_data = cached
            self.region_weather_data = cached.pop("_regions", {}) if cached else {}
        else:
            if not force:
                print("[ENGINE] Cache unvollständig oder veraltet — lade neue Wetterdaten von API...")
            else:
                print("[ENGINE] Force-Refresh — lade neue Wetterdaten von API...")
            result = fetch_all_spots(self.spots)
            if isinstance(result, tuple):
                self.weather_data, self.region_weather_data = result
            else:
                self.weather_data = result
                self.region_weather_data = result.pop("_regions", {}) if result else {}

        # Fix B: Stale-Cache-Fallback erkennen und SOFORT abbrechen.
        # fetch_all_spots() markiert via _meta.fetch_status, wenn der echte Fetch
        # fehlschlug und nur der alte Cache zurückgegeben wurde. In diesem Fall:
        # - Föhn/Stations/Context NICHT neu bauen (Daten haben sich nicht geändert)
        # - Analysen NICHT löschen (Daten sind unverändert, alte Analysen sind valid)
        # - last_refresh_stale Flag setzen für API-Endpoint
        fetch_status = (self.weather_data or {}).get("_meta", {}).get("fetch_status")
        if fetch_status == "stale_cache":
            reason = (self.weather_data or {}).get("_meta", {}).get("fetch_status_reason", "unknown")
            print(f"[WARN] Wetter-Refresh fehlgeschlagen ({reason}) — überspringe Föhn/Stations/Context, alte Daten bleiben unverändert")
            self.last_refresh_stale = True
            self.last_refresh_status_reason = reason
            return

        # KRITISCH: Wenn keine Wetterdaten verfügbar sind, alte Analysen löschen!
        if not self.weather_data or len([k for k in self.weather_data if not k.startswith("_")]) == 0:
            print("[WARNUNG] Keine Wetterdaten verfügbar - lösche alte Analysen zur Sicherheit")
            self.spot_analyses = {}
            self.region_analyses = {}
            self._clear_analyses_cache()
            return

        # 2. Alte Analysen BEHALTEN bis neue generiert werden.
        # Verhindert Token-Overflow: ohne Analysen wird der riesige Roh-Wetterkontext
        # (~500k Zeichen bei 487 Spots) an das LLM geschickt → 147k Tokens → Error 400.
        # Die alten Analysen sind zwar nicht mehr 100% aktuell, aber immer noch besser
        # als der Fallback auf Rohdaten, der das Token-Limit sprengt.
        # Cleanup passiert erst in run_spot_analyses() / run_combined_analyses() wenn
        # neue Ergebnisse vorliegen.
        if self.spot_analyses:
            print(f"[ENGINE] Behalte {len(self.spot_analyses)} alte Spot-Analysen bis neue generiert werden")
            self._analyses_stale = True
        else:
            self._analyses_stale = False

        # 3. Föhn-Daten holen
        try:
            self.foehn_data = fetch_foehn_data(forecast_days=config.FORECAST_DAYS)
        except Exception as e:
            logger.error(f"Föhn-Daten fehlgeschlagen: {e}")
            self.foehn_data = None

        # 3b. Stationsdaten sammeln + Bias-Korrektur anwenden (Spots + Regionen)
        if self.station_manager:
            try:
                self.station_manager.collect_observations()
                self.station_manager.create_pairs(self.weather_data)
                self.station_manager.apply_bias_correction(self.weather_data)
                # Region-Bias: nur ueber Spots innerhalb des Polygons
                try:
                    from source_area import _load_regions
                    regions_with_polygons = _load_regions()
                    if regions_with_polygons and self.region_weather_data:
                        self.station_manager.apply_bias_correction_to_regions(
                            self.region_weather_data, regions_with_polygons
                        )
                except Exception as e:
                    logger.error(f"Region-Bias-Korrektur fehlgeschlagen: {e}")
            except Exception as e:
                logger.error(f"Station Bias-Korrektur fehlgeschlagen: {e}")

        # 4. Kontext-String bauen
        self.weather_context_str = self._build_weather_context()
        self.weather_loaded_at = datetime.now()

        # 5. Conversations NICHT komplett resetten, aber Cache markieren
        for conv in self.conversations.values():
             conv["first_question"] = True

        # 6. An InstantDB pushen (non-blocking)
        if self.instantdb:
            threading.Thread(target=self._push_to_instantdb, daemon=True).start()

        print(f"[ENGINE] Wetterdaten geladen ({len(self.weather_data) - 1} Spots)")

    def _push_to_instantdb(self):
        """Pusht Wetter-Kontext und Summary nach InstantDB (laeuft im Hintergrund)."""
        try:
            timestamp = self.weather_loaded_at.isoformat() if self.weather_loaded_at else datetime.now().isoformat()
            data = {
                "matrix_text": self.weather_context_str,
                "updated_at": timestamp,
            }

            global_id = self.instantdb.make_id("weather_state.global")
            self.instantdb.upsert("weather_state", global_id, data)
            logger.info("InstantDB: weather_state gepusht")

            # Keine automatische Summary mehr
            # summary = self._generate_summary()
            # if summary:
            #     self.instantdb.upsert("weather_state", "global", {"summary_text": summary})
            #     logger.info("InstantDB: summary_text gepusht")

        except Exception as e:
            logger.error(f"InstantDB push fehlgeschlagen: {e}")

    def analyze_weather(self) -> str:
        """Manuelle Analyse wurde deaktiviert."""
        return "Die Vor-Zusammenfassung wurde deaktiviert. Nutze bitte den Chat für eine direkte Analyse der Daten."

    def reload_spots(self):
        """Laedt Spots neu aus CSV und synchronisiert nach InstantDB."""
        self.spots = load_spots()
        logger.info(f"Spots neu geladen: {len(self.spots)} Spots aus CSV")
        self.sync_spots_to_instantdb()
        return len(self.spots)

    def sync_spots_to_instantdb(self):
        """Pusht alle Spots einmalig nach InstantDB."""
        if not self.instantdb:
            return

        docs = {}
        for spot in self.spots:
            spot_id = self.instantdb.make_id(f"spot.{spot['name']}")
            docs[spot_id] = {
                "name": spot["name"],
                "elevation": spot["elevation_m"],
                "wind_ok": spot["windrichtung"],
                "ideal_wind_min": spot.get("ideal_wind_min"),
                "ideal_wind_max": spot.get("ideal_wind_max"),
                "slope_azimuth": spot["slope_azimuth"],
                "slope_angle": spot["slope_angle"],
                "kritischer_foehn": spot["kritischer_foehn"],
                "lat": spot["latitude"],
                "lon": spot["longitude"],
                "bemerkung": spot.get("bemerkung", ""),
            }

        if self.instantdb.batch_upsert("spots", docs):
            logger.info(f"InstantDB: {len(docs)} Spots synchronisiert")
        else:
            logger.warning("InstantDB: Spots-Sync fehlgeschlagen")

    def reset_conversation(self, session_id: str):
        """Conversation zurücksetzen."""
        if session_id in self.conversations:
            del self.conversations[session_id]

        # Datei löschen
        path = self.history_dir / f"{session_id}.json"
        if path.exists():
            path.unlink()

    def cleanup_old_conversations(self, max_age_hours=24):
        """Entfernt inaktive Conversations."""
        now = datetime.now()
        to_remove = []
        for sid, conv in self.conversations.items():
            try:
                last = datetime.fromisoformat(conv["last_activity"])
                age = (now - last).total_seconds() / 3600
                if age > max_age_hours:
                    to_remove.append(sid)
            except Exception:
                to_remove.append(sid)
        for sid in to_remove:
            del self.conversations[sid]
        if to_remove:
            print(f"[ENGINE] {len(to_remove)} alte Conversations bereinigt")

    def get_spots_geojson(self):
        """Gibt alle Spots als GeoJSON FeatureCollection zurück."""
        from source_area import get_reference_points

        features = []
        for spot in self.spots:
            spot_name = spot["name"]
            ref_points = None
            if spot_name in self.weather_data and "reference_points" in self.weather_data[spot_name]:
                ref_points = self.weather_data[spot_name]["reference_points"]
            if ref_points is None:
                ref_points = get_reference_points(
                    spot_name, spot["latitude"], spot["longitude"], quiet=True
                )

            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [spot["longitude"], spot["latitude"]],
                },
                "properties": {
                    "name": spot["name"],
                    "region": spot["region"],
                    "fluggebiet": spot["fluggebiet"],
                    "elevation_m": spot["elevation_m"],
                    "windrichtung": spot["windrichtung"],
                    "bemerkung": spot.get("bemerkung", ""),
                    "reference_points": ref_points,
                    "has_weather": spot_name in self.weather_data,
                },
            })
        return {"type": "FeatureCollection", "features": features}

    def _is_wind_in_range(self, wind_dir, sector_str, buffer=None):
        """Prüft ob Windrichtung im erlaubten Sektor liegt.

        buffer: Absolute Toleranz in Grad pro Sektorgrenze. `None` (default) →
        Toleranz wird aus `config.WIND_DIRECTION_TOLERANCE_PCT` (Prozent der
        Sektorbreite) berechnet und für jeden Sektor separat skaliert.
        """
        if not isinstance(wind_dir, (int, float)) or not sector_str:
            return True # Fallback: LLM soll entscheiden wenn Daten fehlen

        ranges = self._parse_wind_range(sector_str)
        if not ranges:
            return True

        tolerance_pct = getattr(config, "WIND_DIRECTION_TOLERANCE_PCT", 0.0)

        for start, end in ranges:
            if buffer is None:
                width = (end - start) % 360
                if width > 180:
                    width = 360 - width
                buf = width * tolerance_pct
            else:
                buf = buffer

            s_buf = (start - buf) % 360
            e_buf = (end + buf) % 360

            if s_buf <= e_buf:
                if s_buf <= wind_dir <= e_buf:
                    return True
            else: # Wrap around
                if wind_dir >= s_buf or wind_dir <= e_buf:
                    return True
        return False

    def _parse_wind_range(self, range_str):
        """Konvertiert 'NW-SW' oder 'O' in [(Winkel_Start, Winkel_Ende)]."""
        parts = re.split(r'[-/]', range_str.upper())
        angles = []
        for p in parts:
            p = p.strip()
            if p in COMPASS_POINTS:
                angles.append(COMPASS_POINTS[p])
            else:
                # Versuche nur Buchstaben zu extrahieren (falls 'NW (leicht)' drinstünde)
                match = re.search(r'([A-Z]+)', p)
                if match and match.group(1) in COMPASS_POINTS:
                    angles.append(COMPASS_POINTS[match.group(1)])
        
        if len(angles) == 1:
            # Einzelsektor: Gib +/- 45 Grad Bereich
            return [( (angles[0]-45)%360, (angles[0]+45)%360 )]
        elif len(angles) >= 2:
            # Mehrere Teile: Erzeuge Sektoren
            res = []
            for i in range(len(angles)-1):
                start, end = angles[i], angles[i+1]
                # Richtungsentscheidung: Der kleinere Weg (<= 180 Grad)
                diff = (end - start) % 360
                if diff > 180:
                    # Tausche start/end um den kleineren Sektor zu nehmen
                    res.append((end, start))
                else:
                    res.append((start, end))
            return res
        return []
