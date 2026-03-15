import foehn_indicators
from datetime import datetime

r = foehn_indicators.get_foehn_for_dashboard(forecast_days=3)
if r["success"]:
    print(f"Worst level today/tomorrow: {r['foehn']['worst_level_today']}")
    for h in r['hourly']:
        if "2026-03-10" in h['time']:
             print(f"{h['time']} - Level: {h['level']}, Delta-P: {h['delta_p_hpa']}, Wind: {h['crest_wind_kmh']}")
else:
    print("Error:", r.get("error"))
