"""Dichtes Europa/NE-Atlantik-Druckraster fuer die Synoptik-Karte (/synoptik).

Liefert die Datenbasis der interaktiven Bodendruckkarte (Isobaren +
H/T-Zentren im Met-Office-Stil): pressure_msl auf einem regulaeren
Raster (config.SYNOPTIC_GRID_*, ecmwf_ifs025) zu den Ausgabezeiten
00/06/12/18 LOKALZEIT (config.TIMEZONE) ueber FORECAST_DAYS Tage.

Abgrenzung zu engine/synoptic_context.py:
  - synoptic_context: 15 grobe Punkte mit Region-Labels -> deterministische
    Klassifikatoren + LLM-Text (Wetterlage-Block).
  - synoptic_grid: dichtes Raster OHNE Labels -> reine Visualisierungsdaten.
    Kein LLM-Input, keine decide_*-Klassifikation.

Halluzinations-/Konsistenz-Regeln analog synoptic_context:
  - Chunk-Fehler nach 1 Retry -> ganzer Refresh bricht ab, alter Cache
    bleibt stehen (keine Teil-Grids, nichts wird erfunden).
  - Zentren unterhalb der Gradient-Schwelle werden verworfen.

Cache: data/synoptic_grid.json (kompakt geschrieben), Format:
  {generated_at, model, attribution, meta, timesteps, values, winds,
   elevations, centers}
  meta   = {lat0, lon0, dlat, dlon, ny, nx}  (row-major ab NW-Ecke,
           dlat negativ -> y waechst nach Sueden, passend zu d3-contours)
  values = {timestep: [float|None] * (ny*nx)}        (pressure_msl, hPa)
  winds  = {timestep: {u: [float|None], v: [float|None]}}  (700 hPa, m/s)
  elevations = [float|None] * (ny*nx)                (Gelaende, m; fuer Masking)
  centers= {timestep: [{type, lat, lon, msl_hpa, gradient_hpa, decided_by}]}
"""

import json
import logging
import math
import os
import tempfile
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

import requests

import config
from engine.synoptic_context import _haversine_km

logger = logging.getLogger(__name__)

# Verhindert parallele Fetches (Thundering-Herd bei leerem Cache / Erst-Deploy):
# es laeuft immer nur EIN Refresh gleichzeitig.
_refresh_lock = threading.Lock()


# ============================================================================
# RASTER-GEOMETRIE
# ============================================================================

def build_grid_meta() -> dict:
    """Baut die Raster-Metadaten aus den config-Konstanten.

    Row-major ab NW-Ecke: erster Punkt (LAT_MAX, LON_MIN), lat absteigend.
    """
    ny = int(round((config.SYNOPTIC_GRID_LAT_MAX - config.SYNOPTIC_GRID_LAT_MIN)
                   / config.SYNOPTIC_GRID_DLAT)) + 1
    nx = int(round((config.SYNOPTIC_GRID_LON_MAX - config.SYNOPTIC_GRID_LON_MIN)
                   / config.SYNOPTIC_GRID_DLON)) + 1
    return {
        "lat0": config.SYNOPTIC_GRID_LAT_MAX,
        "lon0": config.SYNOPTIC_GRID_LON_MIN,
        "dlat": -config.SYNOPTIC_GRID_DLAT,
        "dlon": config.SYNOPTIC_GRID_DLON,
        "ny": ny,
        "nx": nx,
    }


def _grid_points(meta: dict) -> list[tuple[float, float]]:
    """Alle Rasterpunkte als (lat, lon), row-major NW -> SE."""
    points = []
    for j in range(meta["ny"]):
        lat = round(meta["lat0"] + j * meta["dlat"], 4)
        for i in range(meta["nx"]):
            lon = round(meta["lon0"] + i * meta["dlon"], 4)
            points.append((lat, lon))
    return points


def _cell_latlon(meta: dict, j: int, i: int) -> tuple[float, float]:
    """(lat, lon) der Zelle in Zeile j, Spalte i."""
    return (meta["lat0"] + j * meta["dlat"], meta["lon0"] + i * meta["dlon"])


# ============================================================================
# FETCH (Open-Meteo, gechunkt)
# ============================================================================

def _target_timesteps(forecast_dates: list[str]) -> list[str]:
    """Timestep-Keys 'YYYY-MM-DDTHH:00' (LOKALZEIT, config.TIMEZONE) fuer alle
    Tage x SYNOPTIC_GRID_HOURS_LOCAL — konsistent mit den Meteogramm-Zeiten."""
    return [
        f"{d}T{h:02d}:00"
        for d in forecast_dates
        for h in config.SYNOPTIC_GRID_HOURS_LOCAL
    ]


def _winddir_to_uv(speed_kmh: float, dir_deg: float) -> tuple[float, float]:
    """Meteorologische Windrichtung (Grad, woher) + Geschwindigkeit (km/h) ->
    u/v-Komponenten in m/s (u = ostwaerts, v = nordwaerts).

    dir = 270 (Westwind, weht von West nach Ost) -> u>0, v~0.
    dir =   0 (Nordwind, weht von Nord nach Sued) -> u~0, v<0.
    """
    ms = speed_kmh / 3.6
    rad = dir_deg * math.pi / 180.0
    u = -ms * math.sin(rad)
    v = -ms * math.cos(rad)
    return round(u, 1), round(v, 1)


def fetch_grid_pressure(forecast_dates: list[str]) -> Optional[dict]:
    """Holt pressure_msl + 700-hPa-Wind fuer das dichte Raster via gechunkte
    Open-Meteo-Calls; sammelt zusaetzlich die Gelaende-Elevation je Punkt.

    Der 700-hPa-Wind (~3000 m) wird als u/v-Komponenten (m/s) je Timestep
    abgelegt — u/v statt speed/dir, weil das JS bilinear interpoliert und
    Winkel-Interpolation ueber die 360°-Naht fehleranfaellig waere. Die
    Elevation (aus dem Open-Meteo-Payload, pro Location, nicht in `hourly`)
    dient dem orographischen Masking der H/T-Zentren.

    Returns:
        {"timesteps": [...],
         "values": {ts: [float|None]*N},
         "winds": {ts: {"u": [float|None]*N, "v": [float|None]*N}},
         "elevations": [float|None]*N} — oder None, wenn ein Chunk auch nach
        Retry fehlschlaegt (kein Teil-Grid).
    """
    if not forecast_dates:
        return None

    meta = build_grid_meta()
    points = _grid_points(meta)
    timesteps = _target_timesteps(forecast_dates)

    values: dict[str, list] = {ts: [] for ts in timesteps}
    winds: dict[str, dict] = {ts: {"u": [], "v": []} for ts in timesteps}
    elevations: list = []
    chunk_size = config.SYNOPTIC_GRID_CHUNK_SIZE

    for start in range(0, len(points), chunk_size):
        chunk = points[start:start + chunk_size]
        params = {
            "latitude": ",".join(str(lat) for lat, _ in chunk),
            "longitude": ",".join(str(lon) for _, lon in chunk),
            "hourly": "pressure_msl,wind_speed_700hPa,wind_direction_700hPa",
            "models": "ecmwf_ifs025",  # globales Modell — deckt 65°W ab
            "start_date": forecast_dates[0],
            "end_date": forecast_dates[-1],
            "timezone": config.TIMEZONE,  # hourly-Times kommen in Lokalzeit
        }
        params = config.with_api_key(params)

        payload = None
        for attempt in (1, 2):  # 1 Retry pro Chunk
            try:
                r = requests.get(config.API_URL, params=params,
                                 timeout=config.API_TIMEOUT)
                r.raise_for_status()
                payload = r.json()
                break
            except (requests.RequestException, ValueError) as e:
                logger.warning(
                    "fetch_grid_pressure: Chunk %d Versuch %d fehlgeschlagen: %s",
                    start // chunk_size, attempt, e,
                )
        if payload is None:
            logger.warning("fetch_grid_pressure: Chunk %d endgueltig fehlgeschlagen "
                           "— Refresh abgebrochen, alter Cache bleibt",
                           start // chunk_size)
            return None

        if isinstance(payload, dict):
            payload = [payload]
        if not isinstance(payload, list) or len(payload) != len(chunk):
            logger.warning("fetch_grid_pressure: unerwartetes Payload-Format "
                           "(Chunk %d: %d statt %d Locations)",
                           start // chunk_size,
                           len(payload) if isinstance(payload, list) else -1,
                           len(chunk))
            return None

        for loc in payload:
            hourly = loc.get("hourly", {}) or {}
            times = hourly.get("time", []) or []
            msls = hourly.get("pressure_msl", []) or []
            wspd = hourly.get("wind_speed_700hPa", []) or []
            wdir = hourly.get("wind_direction_700hPa", []) or []
            time_index = {t: k for k, t in enumerate(times)}
            elev = loc.get("elevation")
            elevations.append(round(float(elev), 1) if elev is not None else None)
            for ts in timesteps:
                idx = time_index.get(ts)
                val = msls[idx] if idx is not None and idx < len(msls) else None
                values[ts].append(round(float(val), 1) if val is not None else None)

                sp = wspd[idx] if idx is not None and idx < len(wspd) else None
                di = wdir[idx] if idx is not None and idx < len(wdir) else None
                if sp is not None and di is not None:
                    u, v = _winddir_to_uv(float(sp), float(di))
                else:
                    u, v = None, None
                winds[ts]["u"].append(u)
                winds[ts]["v"].append(v)

    # Timesteps ohne jeden MSLP-Wert (z.B. Modell-Horizont ueberschritten)
    # droppen — winds MUSS dieselben Keys behalten (sonst KeyError downstream).
    kept = [ts for ts in timesteps
            if any(v is not None for v in values[ts])]
    if not kept:
        logger.warning("fetch_grid_pressure: kein Timestep hat gueltige Daten")
        return None
    return {
        "timesteps": kept,
        "values": {ts: values[ts] for ts in kept},
        "winds": {ts: winds[ts] for ts in kept},
        "elevations": elevations,
    }


# ============================================================================
# H/T-ZENTREN AUF DEM DICHTEN RASTER
# ============================================================================

def _smooth_3x3(meta: dict, vals: list) -> list:
    """Eine 3x3-Mittelwert-Glaettungsiteration, None-tolerant."""
    ny, nx = meta["ny"], meta["nx"]
    out = list(vals)
    for j in range(ny):
        for i in range(nx):
            acc, n = 0.0, 0
            for dj in (-1, 0, 1):
                for di in (-1, 0, 1):
                    jj, ii = j + dj, i + di
                    if 0 <= jj < ny and 0 <= ii < nx:
                        v = vals[jj * nx + ii]
                        if v is not None:
                            acc += v
                            n += 1
            out[j * nx + i] = (acc / n) if n else None
    return out


def _circulation_ok(meta: dict, winds_ts: Optional[dict], j: int, i: int,
                    radius: int, is_min: bool) -> Optional[bool]:
    """Prueft, ob das 700-hPa-Windfeld um die Zelle (j,i) zyklonal (fuer ein
    Tief) bzw. antizyklonal (fuer ein Hoch) zirkuliert.

    Mittelt die Tangentialkomponente (CCW-positiv) des Winds auf dem
    Fensterrand-Ring. Tief -> Mittel >= +MIN_TANGENTIAL; Hoch -> <= -MIN.
    Returns True/False, oder None wenn der Check mangels Winddaten / zu weniger
    gueltiger Ring-Samples nicht anwendbar ist (dann NICHT als Filter zaehlen —
    kein Silent-Kill bei Datenluecken).
    """
    if not winds_ts:
        return None
    u_arr = winds_ts.get("u")
    v_arr = winds_ts.get("v")
    if not u_arr or not v_arr:
        return None
    ny, nx = meta["ny"], meta["nx"]
    rad = math.pi / 180.0
    lat_c = meta["lat0"] + j * meta["dlat"]
    # signierte Meter-Abstaende pro Zellschritt (dlat negativ -> dj>0 = suedwaerts);
    # dx cos(lat)-korrigiert, sonst ist die Tangentialrichtung bei hohen Breiten
    # verzerrt (gleiches Muster wie dxM in der alten computeField).
    dxM = meta["dlon"] * 111320.0 * math.cos(lat_c * rad)
    dyM = meta["dlat"] * 111320.0
    acc, n = 0.0, 0
    for dj in range(-radius, radius + 1):
        for di in range(-radius, radius + 1):
            if max(abs(dj), abs(di)) != radius:  # nur Fensterrand-Ring
                continue
            jj, ii = j + dj, i + di
            if not (0 <= jj < ny and 0 <= ii < nx):
                continue
            u = u_arr[jj * nx + ii]
            v = v_arr[jj * nx + ii]
            if u is None or v is None:
                continue
            rx = di * dxM      # ostwaerts
            ry = dj * dyM      # nordwaerts (dyM negativ)
            r = math.hypot(rx, ry)
            if r == 0:
                continue
            # CCW-Tangential-Einheitsvektor t = (-ry, rx)/|r|; Wind = (u, v)
            acc += (u * (-ry) + v * rx) / r
            n += 1
    if n < 4:
        return None
    mean_tang = acc / n
    thr = config.SYNOPTIC_GRID_CENTER_MIN_TANGENTIAL_MS
    return mean_tang >= thr if is_min else mean_tang <= -thr


def find_grid_pressure_centers(meta: dict, vals: list,
                               winds_ts: Optional[dict] = None,
                               elevations: Optional[list] = None) -> list[dict]:
    """Detektiert H/T-Zentren auf dem dichten Raster.

    Algorithmus (Dense-Grid-Variante von find_pressure_centers):
      1. eine 3x3-Glaettungsiteration (unterdrueckt Ein-Zellen-Rauschen)
      2. Kandidat = striktes Min/Max im (2R+1)^2-Fenster,
         R = SYNOPTIC_GRID_CENTER_WINDOW_CELLS
      3. Gradient-Check: |Mittel des Fensterrands - Zentrum| >=
         SYNOPTIC_GRID_CENTER_MIN_GRADIENT_HPA — sonst verworfen
      4. Artefakt-Doppelfilter (nur wenn Daten vorhanden):
         (a) orographisches Masking (elevations > MAX_ELEV_M -> verworfen)
         (b) Zirkulations-Check gegen das 700-hPa-Feld (winds_ts) — flache
             Hitzetief-Artefakte ohne Hoehen-Zirkulation fallen weg
      5. Suppression: nach Gradient absteigend, Kandidaten naeher als
         SYNOPTIC_GRID_CENTER_MIN_DIST_KM an einem staerkeren Zentrum fallen weg
      6. aeusserster Zellring ausgeschlossen (Randextrema = Domaingrenze)

    winds_ts/elevations sind optional — fehlen sie (alter Cache, Tests), wird
    nur nach Gradient beurteilt (rueckwaertskompatibel).

    msl_hpa im Ergebnis ist der UNGEGLAETTETE Originalwert der Zelle
    (Kerndruck soll dem Modellwert entsprechen, nicht dem Glaettungsartefakt).
    """
    ny, nx = meta["ny"], meta["nx"]
    radius = config.SYNOPTIC_GRID_CENTER_WINDOW_CELLS
    min_gradient = config.SYNOPTIC_GRID_CENTER_MIN_GRADIENT_HPA
    min_dist_km = config.SYNOPTIC_GRID_CENTER_MIN_DIST_KM
    max_elev = config.SYNOPTIC_GRID_CENTER_MAX_ELEV_M

    smooth = _smooth_3x3(meta, vals)
    candidates = []

    for j in range(1, ny - 1):          # aeusserster Ring ausgeschlossen
        for i in range(1, nx - 1):
            center = smooth[j * nx + i]
            if center is None:
                continue
            is_min, is_max = True, True
            ring_acc, ring_n = 0.0, 0
            for dj in range(-radius, radius + 1):
                for di in range(-radius, radius + 1):
                    if dj == 0 and di == 0:
                        continue
                    jj, ii = j + dj, i + di
                    if not (0 <= jj < ny and 0 <= ii < nx):
                        continue
                    v = smooth[jj * nx + ii]
                    if v is None:
                        continue
                    if v <= center:
                        is_min = False
                    if v >= center:
                        is_max = False
                    if max(abs(dj), abs(di)) == radius:  # Fensterrand
                        ring_acc += v
                        ring_n += 1
            if ring_n == 0 or not (is_min or is_max):
                continue
            ring_mean = ring_acc / ring_n
            gradient = (ring_mean - center) if is_min else (center - ring_mean)
            if gradient < min_gradient:
                continue

            # (a) orographisches Masking gegen Hoehen-Artefakte
            if elevations is not None:
                ev = elevations[j * nx + i]
                if ev is not None and ev > max_elev:
                    continue
            # (b) Zirkulations-Check gegen das 700-hPa-Feld
            circ = _circulation_ok(meta, winds_ts, j, i, radius, is_min)
            if circ is False:
                continue

            lat, lon = _cell_latlon(meta, j, i)
            raw = vals[j * nx + i]
            candidates.append({
                "type": "Tief" if is_min else "Hoch",
                "lat": round(lat, 2),
                "lon": round(lon, 2),
                "msl_hpa": round(raw if raw is not None else center, 1),
                "gradient_hpa": round(gradient, 1),
                "decided_by": ("find_grid_pressure_centers+circ"
                               if circ is True else "find_grid_pressure_centers"),
            })

    # Suppression: staerkste Zentren zuerst, schwaechere Nachbarn verwerfen
    candidates.sort(key=lambda c: c["gradient_hpa"], reverse=True)
    centers: list[dict] = []
    for c in candidates:
        if all(_haversine_km(c["lat"], c["lon"], k["lat"], k["lon"]) >= min_dist_km
               for k in centers):
            centers.append(c)
    return centers


# ============================================================================
# REFRESH + CACHE I/O
# ============================================================================

def _atomic_write_json_compact(path: Path, data: dict) -> None:
    """Atomic Write wie synoptic_context._atomic_write_json, aber kompakt
    (separators statt indent) — das Grid-File waere mit indent ~4x groesser."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", delete=False,
        dir=str(path.parent), suffix=".tmp",
    )
    try:
        json.dump(data, tmp, ensure_ascii=False, separators=(",", ":"))
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp.close()
        os.replace(tmp.name, path)
    except Exception:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass
        raise


def refresh_synoptic_grid() -> Optional[dict]:
    """Holt das Raster fuer heute..heute+FORECAST_DAYS-1, detektiert Zentren
    pro Timestep und schreibt den Cache. Returns das Ergebnis oder None.

    Serialisiert ueber _refresh_lock: laeuft schon ein Refresh, warten wir
    darauf und liefern den frisch geschriebenen Cache, statt selbst erneut die
    (teuren) Open-Meteo-Calls abzufeuern.
    """
    if not _refresh_lock.acquire(blocking=False):
        with _refresh_lock:  # auf den laufenden Refresh warten
            return load_synoptic_grid_cache()
    try:
        # "today" in config.TIMEZONE (nicht Server-Lokalzeit): die Timestep-Keys
        # sind Lokalzeit; auf UTC-Servern kippt "today" sonst nahe Mitternacht
        # um einen Tag und das Tagesset waere versetzt.
        today = datetime.now(ZoneInfo(config.TIMEZONE)).date()
        forecast_dates = [
            (today + timedelta(days=k)).isoformat()
            for k in range(config.FORECAST_DAYS)
        ]

        meta = build_grid_meta()
        fetched = fetch_grid_pressure(forecast_dates)
        if fetched is None:
            return None

        centers = {
            ts: find_grid_pressure_centers(
                meta, fetched["values"][ts],
                winds_ts=fetched["winds"].get(ts),
                elevations=fetched["elevations"],
            )
            for ts in fetched["timesteps"]
        }

        result = {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "model": "ecmwf_ifs025",
            "attribution": "Open-Meteo",
            "timezone": config.TIMEZONE,
            "meta": meta,
            "timesteps": fetched["timesteps"],
            "values": fetched["values"],
            "winds": fetched["winds"],
            "elevations": fetched["elevations"],
            "centers": centers,
        }
        _atomic_write_json_compact(config.SYNOPTIC_GRID_CACHE_PATH, result)
        logger.info("refresh_synoptic_grid: %d Timesteps, %d Punkte, Cache %s",
                    len(result["timesteps"]), meta["ny"] * meta["nx"],
                    config.SYNOPTIC_GRID_CACHE_PATH)
        return result
    finally:
        _refresh_lock.release()


def load_synoptic_grid_cache() -> Optional[dict]:
    """Laedt den letzten Grid-Cache. Kein API-Call hier."""
    path = Path(config.SYNOPTIC_GRID_CACHE_PATH)
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("load_synoptic_grid_cache: %s", e)
        return None
