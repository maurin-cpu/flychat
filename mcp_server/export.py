"""Export fuer den MCP-Server — laeuft IM App-Prozess (Engine im Speicher).

Schreibt nach data/mcp_export/build-<YYYYMMDD-HHMM>/ und setzt danach den
Pointer data/mcp_export/CURRENT atomar. Der MCP-Prozess liest nur diese Dateien.

Quellen (alles deterministisch, kein LLM):
  - engine._build_single_spot_context(spot, date, mode="dashboard")  -> Textblock
    + Nebeneffekt: _ctx_gust_cache / _ctx_tq_cache / _ctx_foehn_cache
  - web.format_data_for_charts / format_altitude_wind_for_charts      -> Meteogramm-Reihen
  - foehn_indicators.evaluate_foehn auf engine.foehn_data              -> Foehn-Zeitreihe
"""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import re
import shutil
import time
from datetime import datetime, timedelta

import config
from source_area import find_region_for_point, get_all_regions

from .screening import windows_from_hours

logger = logging.getLogger(__name__)

# Hoehenstufen ueber Startplatz fuer das Mini-Profil in der Screening-Zeile
PROFILE_AGL_STEPS = (0, 500, 1000, 1500, 2000, 3000)
PROFILE_HOURS = (9, 12, 15)
KEEP_BUILDS = 2

THRESHOLD_KEYS = (
    "FORECAST_DAYS", "FLIGHT_HOURS_START", "FLIGHT_HOURS_END",
    "WIND_WARN_KMH", "WIND_DANGER_KMH", "WIND_IDEAL_MIN_KMH", "WIND_IDEAL_MAX_KMH",
    "GUST_WARN_KMH", "GUST_DANGER_KMH",
    "CAPE_WARN_JKG", "CAPE_DANGER_JKG",
    "CLEAN_WINDOW_MIN_HOURS", "WIND_DIRECTION_TOLERANCE_PCT",
    "WIND_DIRECTION_IRRELEVANT_BELOW_KMH", "PRODUCTIVE_CLIMB_MIN",
)


def slugify(name: str) -> str:
    """Dateiname aus Spot-Namen: Umlaute mappen, Rest auf [a-z0-9-], Hash gegen Kollision."""
    s = name.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss"), ("é", "e"), ("è", "e"), ("à", "a")):
        s = s.replace(a, b)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:60]
    h = hashlib.md5(name.encode("utf-8")).hexdigest()[:6]
    return f"{s}-{h}"


def _thresholds_snapshot() -> dict:
    out = {}
    for k in THRESHOLD_KEYS:
        v = getattr(config, k, None)
        if v is not None:
            out[k] = v
    # Foehn-Schwellen leben in foehn_indicators
    try:
        import foehn_indicators as fi
        out["FOEHN_DELTA_P_CAUTION_HPA"] = fi.THRESHOLD_DELTA_P_CAUTION
        out["FOEHN_DELTA_P_DANGER_HPA"] = fi.THRESHOLD_DELTA_P_DANGER
    except Exception:
        pass
    return out


def _export_dates(engine) -> list[str]:
    """Tage im Forecast-Fenster (heute .. heute+FORECAST_DAYS-1), die Daten haben."""
    today = datetime.now().date()
    allowed = {(today + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(config.FORECAST_DAYS)}
    present: set[str] = set()
    for name, sd in engine.weather_data.items():
        if name.startswith("_") or not isinstance(sd, dict):
            continue
        for ts in sd.get("hourly_data", {}):
            present.add(ts[:10])
        if len(present) >= len(allowed):
            break
    return sorted(allowed & present)


def _num(v, nd=1):
    if v is None:
        return None
    try:
        return round(float(v), nd)
    except (TypeError, ValueError):
        return None


def _series_for_day(engine, spot, spot_data, date_str, chart_day, hours) -> dict:
    """Stundenreihen 06-17 aus Rohdaten + Chart-Daten. Listen gleich lang wie `hours`."""
    hourly = spot_data.get("hourly_data", {})
    pl = spot_data.get("pressure_level_data", {})
    sector = spot.get("windrichtung")
    by_time = {}
    for key in ("wind", "thermik", "cloudbase", "precipitation"):
        for e in chart_day.get(key, []):
            by_time.setdefault(e["time"][:13], {})[key] = e

    s = {k: [] for k in ("wind", "gust", "dir", "wind_ok", "aloft700", "aloft700_dir",
                         "aloft850", "climb", "top", "base", "low", "mid", "rain", "cape", "sw", "temp")}
    for h in hours:
        ts = f"{date_str}T{h:02d}:00"
        hd = hourly.get(ts, {})
        pd = pl.get(ts, {})
        c = by_time.get(ts[:13], {})
        w, t, cb, pr = c.get("wind", {}), c.get("thermik", {}), c.get("cloudbase", {}), c.get("precipitation", {})
        ws = w.get("speed", hd.get("wind_speed_10m"))
        wd = w.get("direction", hd.get("wind_direction_10m"))
        s["wind"].append(_num(ws, 0))
        s["gust"].append(_num(w.get("gusts", hd.get("wind_gusts_10m")), 0))
        s["dir"].append(_num(wd, 0))
        s["wind_ok"].append(bool(engine._is_wind_in_range(wd, sector, wind_speed=ws)))
        s["aloft700"].append(_num(pd.get("wind_speed_700hPa"), 0))
        s["aloft700_dir"].append(_num(pd.get("wind_direction_700hPa"), 0))
        s["aloft850"].append(_num(pd.get("wind_speed_850hPa"), 0))
        s["climb"].append(_num(t.get("climb_rate"), 1))
        s["top"].append(_num(t.get("max_height"), 0))
        s["base"].append(_num(cb.get("height", hd.get("cloud_base")), 0))
        s["low"].append(_num(cb.get("cover_low", hd.get("cloud_cover_low")), 0))
        s["mid"].append(_num(cb.get("cover_mid", hd.get("cloud_cover_mid")), 0))
        s["rain"].append(_num(pr.get("amount", hd.get("precipitation")), 1))
        s["cape"].append(_num(t.get("cape", hd.get("cape")), 0))
        s["sw"].append(_num(hd.get("shortwave_radiation"), 0))
        s["temp"].append(_num(hd.get("temperature_2m"), 1))
    s["hours"] = list(hours)
    return s


def _trim_altitude(alt_day: list, elev: float, hours) -> list:
    """Hoehenprofile auf Flugstunden, Startplatz..+3500 m und gerundete Felder kuerzen.

    Ungekuerzt sind das ~200 KB pro Spot (24 h x 250-m-Raster x 6 Felder)."""
    keep = set(hours)
    out = []
    for e in alt_day or []:
        if e.get("hour") not in keep:
            continue
        levels = []
        for L in e.get("profiles", []):
            alt = L.get("altitude")
            if alt is None or alt < elev - 250 or alt > elev + 3500:
                continue
            levels.append({"alt": int(alt), "ws": _num(L.get("wind_speed"), 0), "wd": _num(L.get("wind_direction"), 0),
                           "tx": _num(L.get("turbulence_excess"), 0), "t": _num(L.get("temperature"), 0)})
        out.append({"hour": e["hour"], "levels": levels})
    return out


def _mini_profiles(alt_day: list, elev: float) -> dict:
    """{'09': [[agl, speed, dir, excess], ...]} an PROFILE_HOURS, Stufen PROFILE_AGL_STEPS."""
    out = {}
    by_hour = {e["hour"]: e["profiles"] for e in (alt_day or [])}
    for h in PROFILE_HOURS:
        levels = by_hour.get(h)
        if not levels:
            continue
        rows = []
        for agl in PROFILE_AGL_STEPS:
            target = elev + agl
            lvl = min(levels, key=lambda L: abs((L.get("altitude") or 0) - target))
            if abs((lvl.get("altitude") or 0) - target) > 200:
                continue
            rows.append([agl, _num(lvl.get("wind_speed"), 0), _num(lvl.get("wind_direction"), 0),
                         _num(lvl.get("turbulence_excess"), 0)])
        if rows:
            out[f"{h:02d}"] = rows
    return out


def _row(spot, slug, region_id, date_str, model, gust, tq, foehn, series, profiles, region_thunder_pct) -> dict:
    def g(k, d=0):
        v = gust.get(k)
        return d if v is None else v
    vals = [v for v in series["temp"] if v is not None]
    covers = [v for v in series["low"] if v is not None]
    ok_winds = [w for w, ok in zip(series["wind"], series["wind_ok"]) if ok and w is not None]
    capes = [v for v in series["cape"] if v is not None]
    rains = [v for v in series["rain"] if v is not None]
    return {
        "spot": spot["name"], "slug": slug, "fluggebiet": spot.get("fluggebiet"),
        "region": spot.get("analyse_region") or spot.get("region"), "region_id": region_id,
        "date": date_str, "elev": spot.get("elevation_m"), "sector": spot.get("windrichtung"),
        "foehn_crit": spot.get("kritischer_foehn"), "lat": spot.get("latitude"), "lon": spot.get("longitude"),
        "model": model,
        "wind_ok_h": g("wind_ok_count"), "wind_wrong_h": g("wind_wrong_count"),
        "clean_h": g("clean_hours_count"), "longest_clean_h": g("longest_clean_run_hours"),
        "window_start": gust.get("active_window_start"),
        "clean_windows": windows_from_hours(gust.get("clean_hour_list") or []),
        "hard_warn_h": g("hard_warning_hours"), "wind_warn_h": g("wind_warn_hours"),
        "wind_danger_h": g("wind_danger_hours"), "gust_max": _num(gust.get("max_surface_gust"), 0),
        "gust_warn_h": g("gust_warn_hours"), "gust_danger_h": g("gust_danger_hours"),
        "aloft_warn_h": g("aloft_warn_hours"), "aloft_danger_h": g("aloft_danger_hours"),
        "aloft_gust_danger_h": g("aloft_gust_danger_hours"), "aloft_pattern": gust.get("aloft_pattern"),
        "wind_swing_deg": gust.get("max_wind_swing_deg"),
        "rain_h": g("rain_hours"), "rain_win_h": g("rain_in_window_h"),
        "rain_sandwiched": bool(gust.get("rain_sandwiched")), "max_dry_gap": gust.get("max_dry_gap"),
        "thunder_h": g("thunderstorm_hours"), "thunder_win_h": g("thunderstorm_in_window_h"),
        "cloud_below_to_h": g("cloud_at_or_below_takeoff_h"), "cloud_near_to_h": g("cloud_near_takeoff_h"),
        "min_base_m": _num(gust.get("min_cloud_base_active_h"), 0),
        "thermal_h": tq.get("thermal_hours_total", 0), "prod_h": tq.get("productive_thermal_h", 0),
        "prod_strict_h": tq.get("productive_h_strict", 0), "peak_climb": _num(tq.get("peak_climb_proxy"), 1),
        "sustained_peak": _num(tq.get("sustained_peak_mps"), 1), "work_height_agl": tq.get("working_height_agl_m", 0),
        "rough_danger_h": tq.get("rough_danger_h", 0), "cloud_structure": tq.get("cloud_structure"),
        "low_cloud_pct": _num(tq.get("avg_low_cloud_thermal_h"), 0), "band_shallow_h": tq.get("band_too_shallow_h", 0),
        "foehn_level": foehn.get("level", "unknown"), "foehn_dp": _num(foehn.get("delta_p_hpa"), 1),
        "foehn_dir": foehn.get("direction"),
        "t_max": max(vals) if vals else None,
        "cloud_mean_pct": _num(sum(covers) / len(covers), 0) if covers else None,
        "sun_h": sum(1 for v in series["sw"] if (v or 0) >= 400),
        "wind_mean_ok": _num(sum(ok_winds) / len(ok_winds), 0) if ok_winds else None,
        "cape_max": max(capes) if capes else None,
        "precip_mm": _num(sum(rains), 1) if rains else None,
        "region_thunder_pct": region_thunder_pct,
        "series": series,
        "profiles": profiles,
    }


def _foehn_export(engine, dates: list[str]) -> dict:
    """Foehn-Zeitreihe je Tag (Flugstunden), beide Richtungen bewertet."""
    from foehn_indicators import evaluate_foehn
    raw = getattr(engine, "foehn_data", None)
    if not raw or "nord" not in raw or "sued" not in raw:
        return {"available": False, "days": {}}
    times = raw["nord"].get("hourly", {}).get("time", [])
    days: dict = {d: [] for d in dates}
    for i, ts in enumerate(times):
        d = ts[:10]
        if d not in days:
            continue
        h = int(ts[11:13])
        if not (config.FLIGHT_HOURS_START <= h < config.FLIGHT_HOURS_END):
            continue
        ev = evaluate_foehn(raw["nord"], raw["sued"], time_index=i, kritischer_foehn="Beide")
        days[d].append({
            "hour": h, "level": ev.get("level"), "direction": ev.get("foehn_direction"),
            "delta_p": _num(ev.get("delta_p_hpa"), 1), "crest_wind": _num(ev.get("crest_wind_kmh"), 0),
            "crest_dir": _num(ev.get("crest_dir_deg"), 0), "humidity_nord": _num(ev.get("humidity_nord"), 0),
        })
    return {"available": True, "days": days, "stations": raw["nord"].get("station_note")}


def _region_thunder_pct(engine, region_id, date_str):
    try:
        te = engine.region_weather_data.get(region_id, {}).get("thunder_ensemble", {}).get(date_str)
        if isinstance(te, dict):
            for k in ("probability_pct", "pct", "share_pct", "max_pct"):
                if te.get(k) is not None:
                    return _num(te[k], 0)
        elif isinstance(te, (int, float)):
            return _num(te, 0)
    except Exception:
        pass
    return None


def _write_json(path: str, obj) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, separators=(",", ":"))


def build_export(engine, out_root: str | None = None) -> str:
    """Schreibt einen kompletten Export und setzt CURRENT. Liefert den Build-Pfad."""
    # web importiert Flask — im App-Prozess ohnehin geladen; hier nur die reinen Formatter.
    from web import format_data_for_charts, format_altitude_wind_for_charts, _group_chart_by_day, _group_profiles_by_day

    t0 = time.time()
    out_root = out_root or os.path.join(config.DATA_DIR, "mcp_export")
    os.makedirs(out_root, exist_ok=True)
    build_name = "build-" + datetime.now().strftime("%Y%m%d-%H%M")
    build_dir = os.path.join(out_root, build_name)
    for sub in ("blocks", "meteogram", "altitude"):
        os.makedirs(os.path.join(build_dir, sub), exist_ok=True)

    dates = _export_dates(engine)
    hours = list(range(config.FLIGHT_HOURS_START, config.FLIGHT_HOURS_END))
    for d in dates:
        os.makedirs(os.path.join(build_dir, "blocks", d), exist_ok=True)

    spots_out, rows, models_by_date = [], [], {d: {} for d in dates}
    n_blocks = 0
    for spot in engine.spots:
        name = spot["name"]
        sd = engine.weather_data.get(name)
        if not sd or not sd.get("hourly_data"):
            continue
        slug = slugify(name)
        region = find_region_for_point(spot.get("latitude"), spot.get("longitude"))
        region_id = region["id"] if region else None
        elev = sd.get("elevation_m") or spot.get("elevation_m") or 0

        spots_out.append({
            "name": name, "slug": slug, "fluggebiet": spot.get("fluggebiet"),
            "region": spot.get("analyse_region") or spot.get("region"), "region_id": region_id,
            "lat": spot.get("latitude"), "lon": spot.get("longitude"), "elev": elev,
            "windrichtung": spot.get("windrichtung"), "kritischer_foehn": spot.get("kritischer_foehn"),
            "terrain_type": spot.get("terrain_type"), "slope_azimuth": spot.get("slope_azimuth"),
            "slope_angle": spot.get("slope_angle"),
            "bemerkungen_flug": spot.get("bemerkungen_flug"), "bemerkung_flug_effekt": spot.get("bemerkung_flug_effekt"),
            "bemerkungen_sicherheit": spot.get("bemerkungen_sicherheit"),
            "bemerkung_sicherheit_effekt": spot.get("bemerkung_sicherheit_effekt"),
            "bemerkungen_sonstiges": spot.get("bemerkungen_sonstiges"),
        })

        # Meteogramm + Hoehenwind einmal pro Spot (wie /api/weather + /api/altitude-wind)
        hourly, pl = sd.get("hourly_data", {}), sd.get("pressure_level_data", {})
        chart = format_data_for_charts(hourly, pl, elevation_ref=elev,
                                       slope_azimuth=spot.get("slope_azimuth"),
                                       slope_angle=spot.get("slope_angle"), region_id=region_id)
        _, chart_by_day = _group_chart_by_day(chart)
        anchors = {}
        for ts, hd in hourly.items():
            gu, ws, wd = hd.get("wind_gusts_10m"), hd.get("wind_speed_10m"), hd.get("wind_direction_10m")
            if gu is not None and ws is not None:
                anchors[ts] = {"elevation_m": elev, "gust_kmh": float(gu), "wind_speed_kmh": float(ws),
                               "wind_direction_10m": float(wd) if wd is not None else None}
        alt = format_altitude_wind_for_charts(copy.deepcopy(pl), hourly, elev, region_id,
                                              surface_anchor_by_time=anchors)
        _, alt_by_day = _group_profiles_by_day(alt)
        _write_json(os.path.join(build_dir, "meteogram", slug + ".json"),
                    {d: chart_by_day.get(d, {}) for d in dates})
        _write_json(os.path.join(build_dir, "altitude", slug + ".json"),
                    {d: _trim_altitude(alt_by_day.get(d, []), elev, hours) for d in dates})

        for d in dates:
            block = engine._build_single_spot_context(spot, d, mode="dashboard")
            with open(os.path.join(build_dir, "blocks", d, slug + ".txt"), "w", encoding="utf-8") as fh:
                fh.write(block)
            n_blocks += 1
            key = f"{name}|{d}"
            gust = engine._ctx_gust_cache.get(key, {})
            tq = engine._ctx_tq_cache.get(key, {})
            foehn = getattr(engine, "_ctx_foehn_cache", {}).get(key, {})
            model = (sd.get("data_sources") or {}).get(d)
            if model:
                models_by_date[d][model] = models_by_date[d].get(model, 0) + 1
            series = _series_for_day(engine, spot, sd, d, chart_by_day.get(d, {}), hours)
            profiles = _mini_profiles(alt_by_day.get(d, []), elev)
            rows.append(_row(spot, slug, region_id, d, model, gust, tq, foehn, series, profiles,
                             _region_thunder_pct(engine, region_id, d)))

    with open(os.path.join(build_dir, "screening.jsonl"), "w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False, separators=(",", ":")) + "\n")

    regions = []
    counts = {}
    for s in spots_out:
        counts[s["region_id"]] = counts.get(s["region_id"], 0) + 1
    for r in get_all_regions():
        regions.append({"id": r.get("id"), "name": r.get("region"), "terrain_type": r.get("terrain_type"),
                        "kritischer_foehn": r.get("kritischer_foehn"), "spot_count": counts.get(r.get("id"), 0)})
    _write_json(os.path.join(build_dir, "spots.json"), spots_out)
    _write_json(os.path.join(build_dir, "regions.json"), regions)
    _write_json(os.path.join(build_dir, "foehn.json"), _foehn_export(engine, dates))
    _write_json(os.path.join(build_dir, "meta.json"), {
        "built_at": datetime.now().isoformat(timespec="seconds"),
        "last_updated": engine.weather_data.get("_meta", {}).get("last_updated"),
        "dates": dates, "hours": hours, "forecast_days": config.FORECAST_DAYS,
        "thresholds": _thresholds_snapshot(),
        "models_by_date": models_by_date,
        "counts": {"spots": len(spots_out), "rows": len(rows), "blocks": n_blocks},
        "profile_agl_steps": list(PROFILE_AGL_STEPS), "profile_hours": list(PROFILE_HOURS),
        "duration_s": round(time.time() - t0, 1),
    })

    # Pointer atomar setzen, alte Builds aufraeumen
    tmp = os.path.join(out_root, "CURRENT.tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(build_name)
    os.replace(tmp, os.path.join(out_root, "CURRENT"))
    builds = sorted(b for b in os.listdir(out_root) if b.startswith("build-"))
    for old in builds[:-KEEP_BUILDS]:
        shutil.rmtree(os.path.join(out_root, old), ignore_errors=True)
    logger.info("MCP-Export: %s (%d Spots, %d Zeilen, %.1fs)", build_name, len(spots_out), len(rows), time.time() - t0)
    return build_dir
