"""DWD-Fronten fuer die Karten: die passende Frontkarte zu einem Zeitpunkt.

Quelle ist das Archiv, das der Scheduler 4x taeglich fuellt
(data/dwd_fronten_archiv/):
  analyse/dwdc_YYYYMMDDHHMM.geojson                 Bodenanalyse, gueltig zur Dateizeit (UTC)
  vorhersage/dwd_fronten_<LAUF>_<VORLAUF>.geojson   ICON-Vorhersagekarte, gueltig LAUF + VORLAUF h

Beide sind aus den DWD-Karten vektorisiert (GeoNutzV, "© Deutscher Wetterdienst,
vektorisiert und damit veraendert") — die Namensnennung gehoert in jede Anzeige.

Die Karte der App zeigt einen Zeitpunkt (Timestep, lokale CH-Zeit). Dazu passt die
Frontkarte, deren Gueltigkeit am naechsten liegt; von den Vorhersagen nur der
juengste Lauf. Liegt keine innerhalb MAX_OFFSET_H, gibt es keine Fronten — eine
Front von einem ganz anderen Zeitpunkt waere falsch, nicht ungenau.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import config

logger = logging.getLogger(__name__)

ARCHIVE_DIR = config.DATA_DIR / "dwd_fronten_archiv"
MAX_OFFSET_H = 12

_ANALYSE_RE = re.compile(r"dwdc_(\d{12})\.geojson$")
_FORECAST_RE = re.compile(r"dwd_fronten_(\d{12})_(\d{3})\.geojson$")


def _utc(stamp: str) -> datetime:
    return datetime.strptime(stamp, "%Y%m%d%H%M").replace(tzinfo=timezone.utc)


def available_front_maps(archive_dir: Optional[Path] = None) -> list[dict]:
    """Alle nutzbaren Frontkarten: Analysen + juengster Vorhersage-Lauf.

    Returns: [{"path", "kind": "analyse"|"vorhersage", "valid": datetime(UTC),
               "lead_h": int}]
    """
    base = Path(archive_dir or ARCHIVE_DIR)
    maps = []
    for p in sorted((base / "analyse").glob("dwdc_*.geojson")):
        m = _ANALYSE_RE.search(p.name)
        if m:
            maps.append({"path": p, "kind": "analyse", "valid": _utc(m.group(1)),
                         "lead_h": 0})
    forecasts = []
    for p in sorted((base / "vorhersage").glob("dwd_fronten_*_*.geojson")):
        m = _FORECAST_RE.search(p.name)
        if m:
            run, lead = _utc(m.group(1)), int(m.group(2))
            forecasts.append({"path": p, "kind": "vorhersage", "run": run,
                              "valid": run + timedelta(hours=lead), "lead_h": lead})
    if forecasts:
        latest = max(f["run"] for f in forecasts)
        maps.extend(f for f in forecasts if f["run"] == latest)
    return maps


def select_front_map(target: datetime, archive_dir: Optional[Path] = None,
                     max_offset_h: float = MAX_OFFSET_H) -> Optional[dict]:
    """Frontkarte mit der Gueltigkeit am naechsten an `target` (tz-aware).

    Bei gleichem Abstand gewinnt die Analyse (gemessen statt gerechnet).
    Returns: {"geojson", "kind", "valid" (ISO, UTC), "lead_h", "offset_h"} oder None.
    """
    if target.tzinfo is None:
        raise ValueError("target braucht eine Zeitzone")
    target = target.astimezone(timezone.utc)
    maps = available_front_maps(archive_dir)
    if not maps:
        return None
    best = min(maps, key=lambda m: (abs((m["valid"] - target).total_seconds()),
                                    m["kind"] != "analyse"))
    offset_h = abs((best["valid"] - target).total_seconds()) / 3600
    if offset_h > max_offset_h:
        return None
    try:
        geojson = json.loads(best["path"].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        logger.warning("Frontkarte nicht lesbar: %s", best["path"])
        return None
    return {"geojson": geojson, "kind": best["kind"],
            "valid": best["valid"].isoformat(), "lead_h": best["lead_h"],
            "offset_h": round(offset_h, 1)}


def _local_tz():
    """Europe/Zurich; auf dem Windows-Dev-PC ohne tzdata die Rechnerzone (dort
    ohnehin die Schweizer) — gleicher Fallback wie im Briefing."""
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo("Europe/Zurich")
    except Exception:
        return datetime.now().astimezone().tzinfo


def select_for_timestep(ts: str, archive_dir: Optional[Path] = None) -> Optional[dict]:
    """Wie select_front_map, aber fuer einen Karten-Timestep in lokaler CH-Zeit
    ("2026-09-16T12:00" — so liefert /api/synoptic/grid die Timesteps)."""
    try:
        local = datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return None
    if local.tzinfo is None:
        local = local.replace(tzinfo=_local_tz())
    return select_front_map(local, archive_dir)


def available_valid_times_local(archive_dir: Optional[Path] = None) -> list[str]:
    """Gueltigkeiten aller nutzbaren Frontkarten als lokale Timestep-Strings
    ("YYYY-MM-DDTHH:MM", CH-Zeit) — dasselbe Format wie grid.timesteps. Die
    Synoptik-Seite blendet damit Zeitpunkte ohne Frontkarte aus."""
    tz = _local_tz()
    out = sorted({m["valid"].astimezone(tz).strftime("%Y-%m-%dT%H:%M")
                  for m in available_front_maps(archive_dir)})
    return out
