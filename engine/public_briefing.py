"""Oeffentliches Schweiz-Briefing fuer wingcast.ch/flugwetter-schweiz.

Der Scheduler legt nach dem Morgenlauf je Sprache eine schlanke JSON unter
data/public_briefing/briefing.<lang>.json ab. web.py liefert sie ueber
GET /api/public/briefing?lang=de unveraendert aus — kein Rechnen pro Request,
keine Sprachumschaltung im Web-Thread, keine Rohdaten nach draussen.

Inhalt = Whitelist ueber scripts.briefing_v3_context.build_chain_all_days():
Tageskachel, Warnungen Schweiz, je Kettenschritt Fazit/Status/Zahlen/Zonen.
Alles, was die App ohne Login ohnehin zeigt — nur ohne die internen Felder
(Druckzentren, attempts/unresolved, Strukturfeld). Plan:
docs/plaene/PLAN_briefing_webseite.md
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import config
import i18n

logger = logging.getLogger(__name__)

VERSION = 1

# Kettenschritte in der Reihenfolge des Mails; Schluessel = Feld in `chain`.
_STEPS = ("lage", "fronts", "foehn", "wind", "stability", "sonne", "thermik", "modelle")
# Je Schritt nur diese Felder. `num` sind die Zonentabellen (Sonne, Thermik),
# `labile` steuert den Gewitter-Hinweis auf der Webseite.
_STEP_FIELDS = ("fazit", "status", "status_label", "facts", "num", "labile")
_TILE_FIELDS = ("tier", "band", "status", "rating", "n", "pressure_hpa",
                "wind_arrow", "wind_sector", "wind_strength", "wind_hot")
_WARN_FIELDS = ("any", "checks", "entries", "has_ki")


def path_for(lang: str) -> Path:
    return Path(config.PUBLIC_BRIEFING_DIR) / f"briefing.{lang}.json"


def _slim_step(v) -> Optional[dict]:
    if not isinstance(v, dict):
        return None
    return {k: v[k] for k in _STEP_FIELDS if k in v}


def slim_chain(analyse: dict, days: int) -> dict:
    """Whitelist ueber das Ergebnis von build_chain_all_days()."""
    dates = [d for d in (analyse.get("dates") or []) if d][:days]
    by_date: dict = {}
    for d in dates:
        e = (analyse.get("by_date") or {}).get(d) or {}
        chain = e.get("chain")
        tile = e.get("tile") or {}
        w = e.get("warnings") or {}
        by_date[d] = {
            "tile": {k: tile.get(k) for k in _TILE_FIELDS if k in tile},
            "warnings": {k: w.get(k) for k in _WARN_FIELDS if k in w} or None,
            "chain": None if not isinstance(chain, dict) else {
                "situation": chain.get("situation", ""),
                "day_hint": chain.get("day_hint", ""),
                **{k: _slim_step(chain.get(k)) for k in _STEPS},
            },
        }
    return {
        "version": VERSION,
        "lang": analyse.get("lang", ""),
        "generated_at": analyse.get("generated_at", ""),
        "labels": dict(analyse.get("labels") or {}),
        "source": analyse.get("source", ""),
        "dates": dates,
        "by_date": by_date,
    }


def build_public_briefing(lang: str, wetterlage: Optional[dict],
                          briefing_data: dict) -> Optional[dict]:
    """Kette in `lang` rechnen (thread-lokal) und auf die Whitelist kuerzen."""
    if not wetterlage:
        return None
    from scripts.briefing_v3_context import build_chain_all_days
    dates = list(briefing_data.get("forecast_dates") or [])
    with i18n.lang_override(lang):
        analyse = build_chain_all_days(wetterlage, dates,
                                       days=briefing_data.get("days") or [])
    out = slim_chain(analyse, config.PUBLIC_BRIEFING_DAYS)
    out["lang"] = lang
    out["written_at"] = datetime.now().isoformat(timespec="seconds")
    return out


def write_public_briefing(lang: str, payload: dict) -> Path:
    from engine.synoptic_context import _atomic_write_json
    p = path_for(lang)
    _atomic_write_json(p, payload)
    return p


def load_public_briefing(lang: str) -> Optional[dict]:
    p = path_for(lang)
    if not p.exists():
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("load_public_briefing(%s): %s", lang, e)
        return None


def age_hours(payload: Optional[dict]) -> Optional[float]:
    """Alter des Wetterlage-Blocks in Stunden (generated_at ist Wanduhrzeit CH)."""
    if not payload:
        return None
    try:
        gen = datetime.fromisoformat(str(payload.get("generated_at") or ""))
    except ValueError:
        return None
    if gen.tzinfo is not None:
        gen = gen.replace(tzinfo=None)
    return (datetime.now() - gen).total_seconds() / 3600.0


def write_all(wetterlage_by_lang: dict, briefing_data: dict) -> dict:
    """Je Sprache aus PUBLIC_BRIEFING_LANGS die JSON schreiben.

    Fehlt die frische Wetterlage einer Sprache (Lauf fehlgeschlagen), wird
    der letzte Cache dieser Sprache genommen; das Alter prueft der Endpunkt.
    Ein Fehler je Sprache bleibt bei dieser Sprache."""
    from engine.synoptic_context import load_synoptic_cache
    server = i18n.get_server_lang()
    done: dict = {}
    for lang in config.PUBLIC_BRIEFING_LANGS:
        if lang not in i18n.SUPPORTED:
            continue
        try:
            wl = wetterlage_by_lang.get(lang) or load_synoptic_cache(
                None if lang == server else lang)
            payload = build_public_briefing(lang, wl, briefing_data)
            if payload is None:
                logger.info("public_briefing(%s): keine Wetterlage — uebersprungen", lang)
                continue
            done[lang] = write_public_briefing(lang, payload)
            logger.info("public_briefing(%s): %d Tage -> %s", lang,
                        len(payload.get("dates") or []), done[lang])
        except Exception as e:
            logger.exception("public_briefing(%s) fehlgeschlagen: %s", lang, e)
    return done
