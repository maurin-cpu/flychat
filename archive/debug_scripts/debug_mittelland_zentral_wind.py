"""Debug Mittelland Zentral Bodenwind: was kommt aus Open-Meteo pro RP,
was wird aggregiert, wie sieht der xc-therm-Vergleich aus.

Verwendung: python debug_scripts/debug_mittelland_zentral_wind.py
"""
import sys
import math
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests

REGION_ID = "mittelland_zentral"
TARGET_DATE = "2026-04-22"
# xc-therm-Stunden in UTC
TARGET_HOURS_UTC = [13, 14, 15]

# RPs aus regionen_referenzpunkte.geojson (Mittelland Zentral / Napf)
REFS = [
    (46.8918, 7.9715),   # West (Napf)
    (47.1582, 8.8999),   # Ost
    (47.0694, 8.3694),   # Mitte
    (47.025,  8.6346),   # Mitte-Ost
]

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"


def fetch_rp(lat, lon):
    params = {
        "latitude": lat,
        "longitude": lon,
        "hourly": "wind_speed_10m,wind_direction_10m,wind_gusts_10m,surface_pressure",
        "timezone": "Europe/Zurich",
        "models": "icon_d2",
        "start_date": TARGET_DATE,
        "end_date": TARGET_DATE,
        "wind_speed_unit": "kmh",
    }
    r = requests.get(OPEN_METEO_URL, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def median(vals):
    s = sorted(vals)
    n = len(s)
    if n == 0:
        return None
    return s[n // 2] if n % 2 else (s[n // 2 - 1] + s[n // 2]) / 2


def vector_mean_dir(speeds, dirs):
    us, vs = [], []
    for sp, dr in zip(speeds, dirs):
        if sp is None or dr is None:
            continue
        rad = math.radians(dr)
        us.append(sp * math.sin(rad))
        vs.append(sp * math.cos(rad))
    if not us:
        return None
    u_avg = sum(us) / len(us)
    v_avg = sum(vs) / len(vs)
    return (math.degrees(math.atan2(u_avg, v_avg)) + 360) % 360


def main():
    print(f"\n=== Region '{REGION_ID}' Bodenwind Debug ===")
    print(f"Datum: {TARGET_DATE}, Modell: ICON-D2 (pure, keine Multi-Modell-Max)")
    print(f"Lokalzeit = UTC + 2 (CEST)\n")

    rp_data = []
    for i, (lat, lon) in enumerate(REFS):
        try:
            j = fetch_rp(lat, lon)
            rp_data.append((lat, lon, j))
            print(f"RP{i+1} ({lat:.4f}, {lon:.4f}) Elev={j.get('elevation', '?')}m")
        except Exception as e:
            print(f"RP{i+1} FEHLER: {e}")

    print()
    for hour_utc in TARGET_HOURS_UTC:
        hour_local = hour_utc + 2
        ts_local = f"{TARGET_DATE}T{hour_local:02d}:00"
        print(f"--- {hour_utc:02d}:00 UTC = {hour_local:02d}:00 lokal ---")
        speeds, dirs, gusts = [], [], []
        for i, (lat, lon, j) in enumerate(rp_data):
            h = j.get("hourly", {})
            times = h.get("time", [])
            try:
                idx = times.index(ts_local)
            except ValueError:
                print(f"  RP{i+1}: keine Daten")
                continue
            ws = h["wind_speed_10m"][idx]
            wd = h["wind_direction_10m"][idx]
            wg = h["wind_gusts_10m"][idx]
            print(f"  RP{i+1} ({lat:.3f},{lon:.3f}): "
                  f"speed={ws:>5.1f} km/h  dir={wd:>5.0f}°  gust={wg:>5.1f} km/h")
            speeds.append(ws)
            dirs.append(wd)
            gusts.append(wg)
        if speeds:
            med_speed = median(speeds)
            med_gust = median(gusts)
            mean_dir = vector_mean_dir(speeds, dirs)
            print(f"  -> AGG: median(speed)={med_speed:.1f}  vec_dir={mean_dir:.0f}°  "
                  f"median(gust)={med_gust:.1f}  max(gust)={max(gusts):.1f}")
            print(f"     min(speed)={min(speeds):.1f}  max(speed)={max(speeds):.1f}  "
                  f"spread={max(speeds)-min(speeds):.1f}")
        print()


if __name__ == "__main__":
    main()
