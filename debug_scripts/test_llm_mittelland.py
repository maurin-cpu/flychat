"""
Test: Ruft das LLM mit dem echten Region-Kontext fuer Mittelland West auf.
Baut den Kontext so auf wie _build_single_region_context + _flyability_single_region_day.
"""
import sys
import os
import json
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv()

from openai import OpenAI
from prompts import REGION_FLYABILITY_PROMPT
import config
from chat_engine import FlychatEngine

# --- Init Engine mit echten Wetterdaten ---
api_key = os.environ.get("OPENAI_API_KEY")
model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
if not api_key:
    print("FEHLER: OPENAI_API_KEY nicht gesetzt")
    sys.exit(1)

client = OpenAI(api_key=api_key, timeout=120.0)

print(f"Model: {model}")
print(f"Shear-Schwellen Mittelland: {config.SHEAR_THRESHOLDS['mittelland']}")
print()

# --- Engine laden um echten Kontext zu bauen ---
print("Lade FlychatEngine mit gecachten Wetterdaten...")
engine = FlychatEngine()
engine.load_weather_from_cache()

from source_area import get_all_regions

all_regions = get_all_regions()

# Finde Mittelland West Region
target_region = None
for r in all_regions:
    if r.get("id") == "mittelland_west":
        target_region = r
        break

if not target_region:
    print("FEHLER: Region mittelland_west nicht gefunden!")
    sys.exit(1)

print(f"Region: {target_region['region']} (id={target_region['id']}, elev={target_region.get('elevation_ref')}m)")

# Datum: heute
date_str = datetime.now().strftime("%Y-%m-%d")
print(f"Datum: {date_str}")
print()

# --- Kontext bauen (echter Code-Pfad) ---
print("Baue Region-Kontext...")
context = engine._build_single_region_context(target_region, date_str)

if not context:
    print(f"Kein Kontext fuer {date_str} - pruefe region_weather_data...")
    rwd = engine.region_weather_data
    print(f"  region_weather_data keys: {list(rwd.keys())[:5]}...")
    if "mittelland_west" in rwd:
        mw = rwd["mittelland_west"]
        print(f"  mittelland_west keys: {list(mw.keys())[:3]}")
        if "hourly" in mw:
            ts_list = list(mw["hourly"].keys())[:3]
            print(f"  hourly timestamps: {ts_list}")
    else:
        print("  mittelland_west NICHT in region_weather_data!")
        print(f"  Verfuegbare Regionen: {list(rwd.keys())}")

    # Versuche anderen Tag
    for d_offset in [0, 1, 2]:
        alt_date = datetime.now()
        from datetime import timedelta
        alt_date = (alt_date + timedelta(days=d_offset)).strftime("%Y-%m-%d")
        alt_ctx = engine._build_single_region_context(target_region, alt_date)
        if alt_ctx:
            print(f"\n  Kontext gefunden fuer {alt_date}!")
            context = alt_ctx
            date_str = alt_date
            break
        else:
            print(f"  Kein Kontext fuer {alt_date}")

    if not context:
        print("\nKein Kontext fuer kein Datum gefunden. Abbruch.")
        sys.exit(1)

# Kontext anzeigen (ASCII-safe)
print("=" * 70)
print("KONTEXT (was das LLM sieht):")
print("=" * 70)
lines = context.split("\n")
# Zeige nur die Zusammenfassung (letzte ~30 Zeilen)
display_lines = lines[-30:] if len(lines) > 30 else lines
if len(lines) > 30:
    print(f"... ({len(lines) - 30} Zeilen uebersprungen) ...\n")
for line in display_lines:
    try:
        print(line)
    except UnicodeEncodeError:
        print(line.encode("ascii", "replace").decode("ascii"))

# --- Safety-Result simulieren (aus dem User-Screenshot) ---
safety_result = {
    "safety_status": "safe",
    "safe_window": "10:00-16:00",
    "caution_notes": [],
}

safety_context = (
    f"\n=== SICHERHEITSANALYSE (bereits geprueft) ===\n"
    f"Safety-Status: {safety_result['safety_status']}\n"
    f"Sicheres Fenster: {safety_result['safe_window']}\n"
    f"Analysiere NUR die Stunden innerhalb des sicheren Fensters.\n"
)

full_user_msg = (
    f"AKTUELLE LOKALZEIT: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    f"{context}\n{safety_context}"
)

# --- LLM Call ---
print()
print("=" * 70)
print("LLM CALL...")
print("=" * 70)

messages = [
    {"role": "system", "content": REGION_FLYABILITY_PROMPT},
    {"role": "user", "content": full_user_msg},
]

response = client.chat.completions.create(
    model=model,
    messages=messages,
    temperature=0.3,
    max_tokens=500,
    response_format={"type": "json_object"},
)

raw = response.choices[0].message.content
print(f"\nRaw LLM Response:\n{raw}")

try:
    result = json.loads(raw)
    print()
    print("=" * 70)
    print("ERGEBNIS")
    print("=" * 70)
    fly_status = result.get("fly_status") or result.get("flyability_tier") or result.get("status")
    print(f"  fly_status:     {fly_status}")
    print(f"  flight_type:    {result.get('flight_type', 'N/A')}")
    print(f"  peak_climb:     {result.get('peak_climb_rate', 'N/A')} m/s")
    print(f"  xc_potential:   {result.get('xc_potential', 'N/A')}")
    print(f"  best_window:    {result.get('best_window', 'N/A')}")
    print(f"  confidence:     {result.get('confidence', 'N/A')}")
    print(f"  thermal_quality: {result.get('thermal_quality', 'N/A')}")
    print(f"  recommendation: {result.get('recommendation', 'N/A')}")

    if fly_status == "green":
        print("\n  >>> PASS: LLM bewertet GREEN (Gut)")
    elif fly_status == "violet":
        print("\n  >>> PASS: LLM bewertet VIOLET (Legendaer)")
    elif fly_status == "gray":
        print("\n  >>> FAIL: LLM bewertet immer noch GRAY (Schwach)!")
    else:
        print(f"\n  >>> UNBEKANNT: fly_status = {fly_status}")

except json.JSONDecodeError as e:
    print(f"JSON Parse Error: {e}")
