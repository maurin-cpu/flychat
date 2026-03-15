import json

with open("data/wetterdaten.json", "r", encoding="utf-8") as f:
    data = json.load(f)

for spot in ["Balderen", "Zugerberg"]:
    if spot not in data: continue
    hourly = data[spot].get("hourly_data", {})
    keys = list(hourly.keys())
    print(f"{spot} keys count: {len(keys)}")
    if keys:
        print(f"{spot} first: {keys[0]}, last: {keys[-1]}")
