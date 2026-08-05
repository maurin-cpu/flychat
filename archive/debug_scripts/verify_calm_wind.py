#!/usr/bin/env python3
"""Verifiziert Hebel A (Flaute -> WIND-OK) gegen die LIVE-Prognose.

Auf dem Server ausfuehren (dort ist engine.weather_data mit der 5-Tage-Prognose
gefuellt; lokal ist es leer -> Skript meldet das und beendet).

Scannt alle Spots x Prognose-Tage und zaehlt die Flaute-Override-Stunden
(wind_speed < WIND_DIRECTION_IRRELEVANT_BELOW_KMH UND Richtung ausserhalb Sektor).
Baut fuer ein Sample den echten Spot-Kontext und prueft, dass [WIND-CALM] und
FLAUTE-STARTBAR tatsaechlich im Block erscheinen.

    python debug_scripts/verify_calm_wind.py
"""
import sys
sys.path.insert(0, '.')
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

from collections import defaultdict
import config
from chat_engine import WingcastEngine

THR = config.WIND_DIRECTION_IRRELEVANT_BELOW_KMH

engine = WingcastEngine()
wd = engine.weather_data or {}
if not wd:
    print("weather_data ist LEER — vermutlich lokal ohne Live-Fetch. "
          "Dieses Skript auf dem Server laufen lassen.")
    sys.exit(0)

spot_by_name = {s["name"]: s for s in engine.spots}

total_override_h = 0
total_wind_ok_h = 0
total_hours = 0
spots_hit = set()
samples = []  # (spot, date, hour_str, ws, wdir, sector)

for name, data in wd.items():
    if name == "_meta":
        continue
    spot = spot_by_name.get(name)
    if not spot or not spot.get("windrichtung"):
        continue
    sector = spot["windrichtung"]
    hourly = (data or {}).get("hourly_data", {})
    for ts, d in hourly.items():
        ws = d.get("wind_speed_10m")
        wdir = d.get("wind_direction_10m")
        if not isinstance(ws, (int, float)) or not isinstance(wdir, (int, float)):
            continue
        total_hours += 1
        is_ok = engine._is_wind_in_range(wdir, sector, wind_speed=ws)
        if is_ok:
            total_wind_ok_h += 1
        dir_only = engine._is_wind_in_range(wdir, sector)  # ohne Flaute-Bypass
        if ws < THR and not dir_only:
            total_override_h += 1
            spots_hit.add(name)
            if len(samples) < 8:
                date = ts.split("T")[0]
                hh = ts.split("T")[1][:5]
                samples.append((name, date, hh, ws, wdir, sector))

print("=" * 64)
print(f"VERIFY Hebel A — Flaute-Override (Schwelle < {THR} km/h)")
print("=" * 64)
print(f"Prognose-Stunden gescannt:        {total_hours}")
print(f"WIND-OK-Stunden gesamt:           {total_wind_ok_h}")
print(f"davon Flaute-Override (neu OK):   {total_override_h}")
print(f"betroffene Spots:                 {len(spots_hit)}")
print()
if samples:
    print("Beispiele (Spot | Tag | Std | Wind | Richtung | Sektor):")
    for name, date, hh, ws, wdir, sector in samples:
        print(f"  {name[:28]:<28} {date} {hh}  {ws:>4.1f}km/h  {wdir:>3.0f}deg  [{sector}]")
    print()
    # Echten Kontext fuer das erste Sample bauen und Marker pruefen
    s_name, s_date = samples[0][0], samples[0][1]
    ctx = engine._build_single_spot_context(spot_by_name[s_name], s_date, mode="dashboard") or ""
    print(f"Kontext-Check fuer {s_name} / {s_date}:")
    print(f"  [WIND-CALM] im Stundenblock : {'[WIND-CALM]' in ctx}")
    print(f"  FLAUTE-STARTBAR Hinweis     : {'FLAUTE-STARTBAR' in ctx}")
    for ln in ctx.splitlines():
        if "FLAUTE-STARTBAR" in ln:
            print("  >", ln.strip())
else:
    print("Kein Flaute-Override in der aktuellen Prognose — Feature inaktiv "
          "(kein Spot hat Flaute aus falscher Richtung). Logik trotzdem aktiv.")
