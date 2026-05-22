import sys
import os
from datetime import datetime
from pathlib import Path

# Pfade hinzufügen
sys.path.append(str(Path(__file__).parent.parent))

import config
from chat_engine import GleitcastEngine

def test_weather_context_filtering():
    engine = GleitcastEngine()
    engine.refresh_weather()
    
    context = engine._build_weather_context()
    now = datetime.now()
    now_str = now.strftime("%Y-%m-%d %H")
    
    print(f"Aktuelle Zeit: {now}")
    
    # Prüfe ob Daten von heute VOR jetzt drin sind
    lines = context.split("\n")
    found_past = False
    found_future = False
    
    for line in lines:
        if "Temp" in line and ":" in line:
            time_part = line.split(":")[0].strip() # 2026-03-08 10
            try:
                dt = datetime.strptime(time_part, "%Y-%m-%d %H")
                if dt.timestamp() < (now.timestamp() - 3600):
                    print(f"[ERROR] Vergangene Stunde gefunden: {line}")
                    found_past = True
                else:
                    found_future = True
            except ValueError:
                continue

    if not found_past and found_future:
        print("[SUCCESS] Filterung im LLM-Kontext funktioniert!")
    elif not found_future:
        print("[WARN] Keine Zukunftsdaten gefunden (evtl. nach 17:00 Uhr heute?)")
    else:
        print("[FAIL] Filterung fehlgeschlagen.")

if __name__ == "__main__":
    test_weather_context_filtering()
