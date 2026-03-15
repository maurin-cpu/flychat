import json

with open("data/wetterdaten.json", "r", encoding="utf-8") as f:
    d = json.load(f)

spot_data = d.get("Brunnihütte", {})
day_data = spot_data.get("2026-03-12", {})
if "hourly_data" in day_data:
    for ts, hr in day_data["hourly_data"].items():
        print(f"{ts}: cover={hr.get('cloud_cover')}%")
else:
    print("no data")
