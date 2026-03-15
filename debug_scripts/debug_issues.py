import json

with open("data/wetterdaten.json", "r", encoding="utf-8") as f:
    data = json.load(f)

print("\n--- BRUNNIHÜTTE am 13.03. HÖHENWIND ---")
if "Brunnihütte" in data:
    pl_data = data["Brunnihütte"].get("pressure_level_data", {})
    for ts, values in sorted(pl_data.items()):
        if "2026-03-13" in ts:
            time_part = ts.split("T")[1]
            if "10:00" <= time_part <= "17:00":
                ws850 = values.get("wind_speed_850hPa", 0)
                ws700 = values.get("wind_speed_700hPa", 0)
                print(f"{time_part} | 850hPa: {ws850:.1f} km/h | 700hPa: {ws700:.1f} km/h")

print("\n--- ZUGERBERG am 12.03. RADIATION CHECK ---")
if "Zugerberg" in data:
    hourly = data["Zugerberg"].get("hourly_data", {})
    for ts, values in sorted(hourly.items()):
        if "2026-03-12" in ts:
            time_part = ts.split("T")[1]
            if "10:00" <= time_part <= "16:00":
                cc = values.get("cloud_cover")
                rad = values.get("direct_radiation")
                sw = values.get("shortwave_radiation")
                print(f"{time_part} | CC: {cc}% | DirectRad: {rad}W | TotalSW: {sw}W")
