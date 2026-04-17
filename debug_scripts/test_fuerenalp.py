import urllib.request, json
try:
    data = json.loads(urllib.request.urlopen("http://localhost:5000/api/weather/F%C3%BCrenalp").read())
    if "error" in data:
        print("API Error:", data["error"])
    else:
        dates = data.get("dates", [])
        print("Vorhandene Tage für Fürenalp:", dates)
except Exception as e:
    print("Error:", e)
