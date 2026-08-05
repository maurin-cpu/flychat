"""Check all spot API endpoints for errors."""
import json
import urllib.request
import urllib.error

status_url = "http://localhost:5000/api/status"
resp = urllib.request.urlopen(status_url)
status = json.loads(resp.read())
spots = [s for s in status["weather_spots"] if not s.startswith("_")]

print(f"Checking {len(spots)} spots...")
errors = []
for spot in spots:
    try:
        url = f"http://localhost:5000/api/altitude-wind/{urllib.parse.quote(spot)}"
        resp = urllib.request.urlopen(url, timeout=15)
        data = json.loads(resp.read())
        dates = data.get("dates", [])
        today_data = data.get("data", {}).get("2026-04-12", [])
        if not dates or "2026-04-12" not in dates:
            errors.append(f"  {spot}: NO today in dates! dates={dates}")
        elif len(today_data) == 0:
            errors.append(f"  {spot}: today date exists but 0 entries!")
        else:
            hours_6_18 = [e for e in today_data if 6 <= e["hour"] <= 18]
            if len(hours_6_18) == 0:
                errors.append(f"  {spot}: no hours 6-18!")
    except Exception as e:
        errors.append(f"  {spot}: EXCEPTION {e}")

if errors:
    print(f"\n{len(errors)} PROBLEMS found:")
    for e in errors:
        print(e)
else:
    print("All spots OK!")
