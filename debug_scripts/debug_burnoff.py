import json

with open("data/wetterdaten.json", "r", encoding="utf-8") as f:
    data = json.load(f)

for spot in ["Balderen"]:
    print(f"\n--- {spot} am 12.03. ---")
    if spot not in data: continue
    
    hourly = data[spot].get("hourly_data", {})
    for ts in sorted(hourly.keys()):
        values = hourly[ts]
        if "2026-03-12" in ts:
            time_part = ts.split("T")[1]
            if "10:00" <= time_part <= "17:00":
                cc = values.get("cloud_cover")
                ccl = values.get("cloud_cover_low")
                print(f"{ts[-8:-3]} | CC: {cc}% | CCL: {ccl}%")

    print(f"\n--- {spot} am 13.03. ---")
    for ts in sorted(hourly.keys()):
        values = hourly[ts]
        if "2026-03-13" in ts:
            time_part = ts.split("T")[1]
            if "10:00" <= time_part <= "17:00":
                cc = values.get("cloud_cover")
                ccl = values.get("cloud_cover_low")
                print(f"{ts[-8:-3]} | CC: {cc}% | CCL: {ccl}%")
