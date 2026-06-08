"""
Föhn-Test Cache-Builder (Handoff docs/TQ_TORN_FLYABILITY.md, Stand 2026-06-07).

Baut einen wetterdaten.json-foermigen Cache fuer EINEN Tag (Default 2026-05-28,
staerkster Foehn-Label, Score 5.9) ueber ALLE Regionen + Spots des Live-Caches,
damit die Band-Cap-Diagnostik (region/spot_band_cap_potential, verify_band_cap,
test_torn_regions_echtheit) ueber den ECHTEN Engine-Pfad laufen kann.

METHODEN-ABWEICHUNG ggue. Handoff ("Weg 2 = ERA5-Archiv"):
  ERA5 (archive-api) liefert fuer 28.05.2026 KEINE Druckflaechen-Winde (alle null —
  Reanalyse-Lag, null sogar zurueck bis Januar). Die Forecast-API (api.open-meteo.com)
  mit explizitem start_date/end_date liefert dagegen volle, non-null PL-Winde+Hoehen
  +CAPE+BLH fuer den Zieltag (operationelles best_match-Archiv, ~ICON/IFS). Das ist
  echtes Hoehenwind-Material fuer den realen Foehntag und naeher am Live-ICON-System
  als ERA5 — der Handoff-Caveat "ERA5 != ICON, nur qualitativ" gilt unveraendert.

Quelle der Geometrie: der Live-Cache selbst (reference_points + elevation_ref je
Region, lat/lon/elev je Spot) — keine Cherry-Picks, ALLE Regionen werden gezogen,
damit die Diagnostik tiefe Saeulen/Risse natuerlich aufdeckt.

Schreibt: data/foehn_cache_<DATE>.json  (Live-Cache NICHT angefasst).
"""
import sys, os, json, time, math, urllib.request, urllib.parse
from statistics import median

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

DATE = sys.argv[1] if len(sys.argv) > 1 else "2026-05-28"
REGIONS_ONLY = "regions-only" in sys.argv[2:]
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                   "data", f"foehn_cache_{DATE}.json")
API = "https://api.open-meteo.com/v1/forecast"

LEVELS = config.PRESSURE_LEVELS
PL_KEYS, SURF_KEYS = [], list(config.CH_SURFACE_PARAMS) + ["boundary_layer_height"]
for L in LEVELS:
    PL_KEYS += [f"wind_speed_{L}hPa", f"wind_direction_{L}hPa",
                f"geopotential_height_{L}hPa", f"temperature_{L}hPa"]
HOURLY = SURF_KEYS + PL_KEYS
DIR_KEYS = {f"wind_direction_{L}hPa" for L in LEVELS} | {"wind_direction_10m"}


def fetch_points(coords):
    """coords: list of (lat,lon). Returns list of hourly-dicts aligned to input."""
    params = {
        "latitude": ",".join(f"{c[0]:.4f}" for c in coords),
        "longitude": ",".join(f"{c[1]:.4f}" for c in coords),
        "start_date": DATE, "end_date": DATE,
        "hourly": ",".join(HOURLY), "timezone": config.TIMEZONE,
    }
    url = API + "?" + urllib.parse.urlencode(params)
    for attempt in range(6):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "flychat-foehn-test"})
            data = json.load(urllib.request.urlopen(req, timeout=60))
            break
        except urllib.error.HTTPError as e:
            if attempt == 5:
                raise
            time.sleep(20 if e.code == 429 else 3 * (attempt + 1))
        except Exception:
            if attempt == 5:
                raise
            time.sleep(3 * (attempt + 1))
    if isinstance(data, dict):
        data = [data]
    return data


def circ_median(vals):
    vals = [v for v in vals if isinstance(v, (int, float))]
    if not vals:
        return None
    s = sum(math.sin(math.radians(v)) for v in vals)
    c = sum(math.cos(math.radians(v)) for v in vals)
    return round((math.degrees(math.atan2(s, c)) + 360) % 360, 1)


def med(vals, key):
    vals = [v for v in vals if isinstance(v, (int, float))]
    if not vals:
        return None
    return circ_median(vals) if key in DIR_KEYS else round(median(vals), 2)


def to_series(point_responses):
    """Median-aggregate N point responses into single hourly_data + pl_data series."""
    times = point_responses[0]["hourly"]["time"]
    hourly_data, pl_data = {}, {}
    for i, ts in enumerate(times):
        h_entry, p_entry = {}, {}
        for key in HOURLY:
            vals = [pr["hourly"].get(key, [None] * len(times))[i] for pr in point_responses]
            m = med(vals, key)
            (p_entry if "hPa" in key else h_entry)[key] = m
        hourly_data[ts] = h_entry
        pl_data[ts] = p_entry
    return hourly_data, pl_data


def main():
    print(f"[foehn] Ziel-Datum {DATE}  | {len(HOURLY)} hourly-Params  | TZ {config.TIMEZONE}")
    live = json.load(open(config.WEATHER_JSON_PATH))
    out = {"_meta": {"foehn_test": True, "date": DATE,
                     "source": "open-meteo forecast API (past-date best_match), NOT ERA5",
                     "note": "PL winds non-null; ERA5 archive had null PL winds for this date"}}

    # --- Regionen: alle, je Region ein Multi-Point-Call ueber die reference_points ---
    regions = live.get("_regions", {})
    out_regions = {}
    for i, (rid, r) in enumerate(regions.items(), 1):
        rps = r.get("reference_points") or []
        if not rps:
            print(f"  [region {i}/{len(regions)}] {rid}: keine reference_points, skip")
            continue
        coords = [(p[0], p[1]) for p in rps]
        try:
            resp = fetch_points(coords)
            hd, pd = to_series(resp)
            out_regions[rid] = {
                "region_id": rid, "region_name": r.get("region_name", rid),
                "elevation_ref": r.get("elevation_ref"),
                "hourly_data": hd, "pressure_level_data": pd,
                "reference_points": rps,
                "data_sources": {DATE: "openmeteo_forecast_pastdate"},
            }
            print(f"  [region {i}/{len(regions)}] {rid}: {len(coords)} RP -> "
                  f"{len(hd)}h  (elev_ref {r.get('elevation_ref')})")
        except Exception as e:
            print(f"  [region {i}/{len(regions)}] {rid}: FEHLER {e}")
        time.sleep(1.3)
    out["_regions"] = out_regions

    # --- Spots: alle, in Batches von 40 (ein Punkt je Spot) ---
    spot_items = [] if REGIONS_ONLY else [(k, v) for k, v in live.items()
                  if not k.startswith("_") and isinstance(v, dict)
                  and isinstance(v.get("latitude"), (int, float))]
    BATCH = 40
    n_ok = 0
    for b in range(0, len(spot_items), BATCH):
        chunk = spot_items[b:b + BATCH]
        coords = [(v["latitude"], v["longitude"]) for _, v in chunk]
        try:
            resp = fetch_points(coords)
            for (name, v), pr in zip(chunk, resp):
                hd, pd = to_series([pr])
                out[name] = {
                    "latitude": v["latitude"], "longitude": v["longitude"],
                    "elevation_m": v.get("elevation_m", pr.get("elevation")),
                    "hourly_data": hd, "pressure_level_data": pd,
                    "reference_points": v.get("reference_points", [[v["latitude"], v["longitude"]]]),
                    "data_sources": {DATE: "openmeteo_forecast_pastdate"},
                }
                n_ok += 1
            print(f"  [spots {b}-{b+len(chunk)}/{len(spot_items)}] ok")
        except Exception as e:
            print(f"  [spots {b}-{b+len(chunk)}] FEHLER {e}")
        time.sleep(1.5)

    json.dump(out, open(OUT, "w"), ensure_ascii=False)
    sz = os.path.getsize(OUT) / 1e6
    print(f"[foehn] geschrieben: {OUT}  ({sz:.1f} MB) | "
          f"{len(out_regions)} Regionen, {n_ok} Spots")


if __name__ == "__main__":
    main()
