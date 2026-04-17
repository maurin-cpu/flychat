#!/usr/bin/env python3
"""Debug: Weissenstein Wind-Analyse für Montag 6.04"""
import sys
sys.path.insert(0, '.')

from chat_engine import FlychatEngine

# Initialize engine
engine = FlychatEngine()

# Get Weissenstein spot
spot = None
for s in engine.spots:
    if s['name'] == 'Weissenstein':
        spot = s
        break

if not spot:
    print("Spot 'Weissenstein' nicht gefunden!")
    sys.exit(1)

print(f"=== WEISSENSTEIN DEBUG ===")
print(f"Favorable Wind: {spot['windrichtung']}")
print(f"Spot-ID: {spot.get('fluggebiet')}")
print()

# Get weather data for Monday
spot_name = 'Weissenstein'
if spot_name in engine.weather_data:
    weather = engine.weather_data[spot_name]
    hourly = weather.get('hourly_data', {})

    monday_data = hourly.get('2026-04-06', {})

    if monday_data:
        print("=== MONTAG 6.04.2026 - WIND DATEN ===")
        print(f"{'Zeit':<8} | {'°':<5} | {'Richt.':<6} | {'Speed':<8} | {'Gusts':<8} | WIND-TAG")
        print("-" * 75)

        for hour in range(6, 20):
            time_key = f'2026-04-06T{hour:02d}:00:00'
            if time_key in monday_data:
                data = monday_data[time_key]
                wd = data.get('wind_direction_10m', 0)
                ws = data.get('wind_speed_10m', 0)
                wg = data.get('wind_gusts_10m', 0)

                # Convert degrees to cardinal
                dirs = ['N','NNO','NO','ONO','O','OSO','SO','SSO','S','SSW','SW','WSW','W','WNW','NW','NNW']
                idx = int((wd + 11.25) / 22.5) % 16
                card = dirs[idx]

                # Check if wind is in range
                is_ok = engine._is_wind_in_range(wd, spot['windrichtung'])
                tag = "[WIND-OK]" if is_ok else "[WIND-WRONG]"

                print(f"{hour:02d}:00    | {wd:5.0f} | {card:<6} | {ws:5.1f}km/h | {wg:5.1f}km/h | {tag}")
    else:
        print("Keine Daten für 2026-04-06!")
else:
    print(f"Keine Wetterdaten für {spot_name}!")

print()
print("=== SPOT CONTEXT PREVIEW ===")
context = engine._build_single_spot_context(spot, '2026-04-06')
# Print first 2000 chars of context
print(context[:2000])
print("...")
