"""
Ad-hoc-Test fuer den neuen REGION-SAFETY-CAP:
1. Holt Live-Wetter fuer Spots aus mehreren foehn-/alpenexponierten Regionen.
2. Sucht OHNE LLM den (Region, Tag) mit dem staerksten synoptischen Signal
   (Hoehenwind/Foehn) anhand der Tags im Region-Kontext.
3. Laesst dort die echte Pipeline laufen: Region-Analyse + 4 Spot-Analysen.
4. Zeigt pro Spot Safety-Status, die 8 Sub-Ratings, das summary und die
   Flug-Einschaetzung (recommendation/xc_details) — plus die Region zum Abgleich.
"""
import os
import sys
import io
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

from dotenv import load_dotenv
load_dotenv()

import config
from chat_engine import GleitcastEngine
from source_area import get_all_regions, find_region_for_point
from foehn_indicators import fetch_foehn_data
import fetch_weather

CANDIDATE_REGION_NAMES = [
    "Unterwallis", "Prättigau - Davos", "Engadin Unter",
    "Waadtländer Alpen", "Tessin Zentral", "Berner Voralpen",
]
SPOTS_PER_REGION_FETCH = 6  # Puffer, damit >=4 mit Wetter uebrigbleiben

print(f"Analysis: provider={config.ANALYSIS_PROVIDER} model={config.ANALYSIS_MODEL}")

eng = GleitcastEngine()
all_spots = eng.spots

# --- Spots je Kandidatenregion sammeln (per analyse_region-Name) ---
fetch_spots = []
for s in all_spots:
    if (s.get("analyse_region") in CANDIDATE_REGION_NAMES):
        fetch_spots.append(s)
# pro Region kappen
from collections import defaultdict
buckets = defaultdict(list)
for s in fetch_spots:
    buckets[s["analyse_region"]].append(s)
fetch_spots = []
for rname, lst in buckets.items():
    fetch_spots.extend(lst[:SPOTS_PER_REGION_FETCH])
USE_CACHE = os.environ.get("USE_CACHE", "1") == "1"
if USE_CACHE and eng.load_weather_from_cache():
    print("Wetter aus Cache geladen (kein API-Call).")
    weather_data = eng.weather_data
    region_weather_data = eng.region_weather_data
else:
    print(f"Hole Wetter fuer {len(fetch_spots)} Spots aus {len(buckets)} Regionen...")
    result = fetch_weather.fetch_all_spots(fetch_spots, save_to_file=True)
    if isinstance(result, tuple):
        weather_data, region_weather_data = result
    else:
        weather_data = result
        region_weather_data = result.pop("_regions", {}) if isinstance(result, dict) else {}
    eng.weather_data = weather_data
    eng.region_weather_data = region_weather_data
try:
    eng.foehn_data = fetch_foehn_data(forecast_days=config.FORECAST_DAYS)
except Exception as e:
    print("Foehn-Daten:", e)
    eng.foehn_data = None

n_spot_keys = len([k for k in weather_data if not k.startswith("_")])
print(f"Wetter geladen: {n_spot_keys} Spots, {len(region_weather_data)} Regionen mit Daten")

# --- Forecast-Daten bestimmen (Engine-Logik) ---
forecast_dates = eng._get_forecast_dates() or []
print(f"Forecast-Daten: {forecast_dates}")

# --- Kandidatenregionen → Region-Objekte ---
all_regions = get_all_regions()
name_to_region = {r["region"]: r for r in all_regions}
cand_regions = [name_to_region[n] for n in CANDIDATE_REGION_NAMES if n in name_to_region
                and name_to_region[n]["id"] in region_weather_data]

# --- Ohne LLM: synoptisches Signal je (Region, Tag) scoren ---
SIGNAL_MARKERS = {
    "ALOFT-WIND-DANGER": 4, "ALOFT-WIND-WARN": 2, "ALOFT-CONDITIONAL": 2,
    "ALOFT-NOT-SAFE": 5, "SHEAR-DANGER": 3, "SHEAR-WARN": 1,
    "WIND-DANGER": 2, "WIND-WARN": 1,
}
scored = []
for region in cand_regions:
    for date_str in forecast_dates:
        try:
            ctx = eng._build_single_region_context(region, date_str)
        except Exception:
            ctx = None
        if not ctx:
            continue
        score = sum(ctx.count(m) * w for m, w in SIGNAL_MARKERS.items())
        # grobes Foehn-Signal aus Kontexttext
        low = ctx.lower()
        if "foehn" in low or "föhn" in low:
            score += low.count("hpa") * 1
        scored.append((score, region["region"], region["id"], date_str))

scored.sort(reverse=True)
print("\nTop synoptische Signal-Kandidaten (Score, Region, Datum):")
for sc, rname, rid, ds in scored[:8]:
    print(f"  {sc:4d}  {rname:22s} {ds}")

# Spots je Region (point-in-polygon) vorberechnen
spots_by_rid = defaultdict(list)
for s in all_spots:
    if s["name"] not in weather_data:
        continue
    try:
        reg = find_region_for_point(s["latitude"], s["longitude"])
    except Exception:
        reg = None
    if reg:
        spots_by_rid[reg["id"]].append(s)

def fly_candidates(rid, date_str):
    """Spots der Region, die den deterministischen Pre-Filter PASSIEREN
    (also den LLM erreichen) — nur dort kann der Region-Cap greifen."""
    out = []
    for s in spots_by_rid.get(rid, []):
        ctx = eng._build_single_spot_context(s, date_str, mode="dashboard", region_analysis_result=None)
        if not ctx:
            continue
        if eng._prefilter_not_safe(s, date_str) is None:
            out.append(s)
    return out

# Ersten Kandidaten mit synopt. Signal UND >=4 fliegbaren Spots waehlen
win = None
for sc, rname, rid, ds in scored:
    if sc <= 0:
        break
    cands = fly_candidates(rid, ds)
    print(f"  Pruefe {rname} {ds}: Score {sc}, {len(cands)} Spots erreichen LLM")
    if len(cands) >= 4:
        win = (rname, rid, ds, cands)
        break
if win is None:
    # Fallback: Kandidat mit den meisten fliegbaren Spots
    best_n = -1
    for sc, rname, rid, ds in scored[:10]:
        cands = fly_candidates(rid, ds)
        if len(cands) > best_n:
            best_n = len(cands)
            win = (rname, rid, ds, cands)
win_rname, win_rid, win_date, win_spots = win
win_region = name_to_region[win_rname]
win_spots = win_spots[:4]
print(f"\n>>> Gewaehlt: Region '{win_rname}' (id={win_rid}) am {win_date}")
print(f"4 Test-Spots (erreichen LLM): {[s['name'] for s in win_spots]}")

# --- Region-Analyse (LLM) ---
print(f"\n=== Region-Analyse '{win_rname}' {win_date} (LLM) ===")
region_result = eng._build_and_analyze_region(win_region, win_date)
rs = region_result.get("safety", region_result) if isinstance(region_result.get("safety"), dict) else region_result
print(f"  safety_status: {rs.get('safety_status')}  primary_no_go: {rs.get('primary_no_go')}")
print(f"  foehn_risk: {rs.get('foehn_risk')}")
print("  Sub-Ratings: " + ", ".join(
    f"{k.replace('_safety_rating','')}={rs.get(k)}" for k in
    ["aloft","foehn","thunderstorm","cape","rain","visibility","wind","gust"]
    for k in [f"{k}_safety_rating"]
))
print("  wind_summary:", rs.get("wind_summary"))
print("  summary:", rs.get("summary"))

# --- Spot-Analysen (LLM) ---
def show(res, spot_name):
    sa = res.get("safety", res) if isinstance(res.get("safety"), dict) else res
    fl = res.get("flyability", res) if isinstance(res.get("flyability"), dict) else res
    print("\n" + "=" * 78)
    print(f"SPOT: {spot_name}")
    print("=" * 78)
    print(f"  safety_status: {res.get('safety_status') or sa.get('safety_status')}")
    subs = ["aloft","foehn","thunderstorm","cape","rain","visibility","wind","gust"]
    print("  Safety-Sub-Ratings: " + ", ".join(
        f"{s}={sa.get(s+'_safety_rating')}" for s in subs))
    print("  primary_no_go:", sa.get("primary_no_go"), " primary_caution:", sa.get("primary_caution"))
    print("  SAFETY summary:\n   ", (sa.get("summary") or "").strip())
    print("  experience_rating:", fl.get("experience_rating"))
    print("  FLYABILITY recommendation:\n   ", (fl.get("recommendation") or "").strip())
    print("  xc_details:\n   ", (fl.get("xc_details") or "").strip())

for s in win_spots[:4]:
    try:
        res = eng._build_and_analyze_spot(s, win_date, region_result)
    except Exception as e:
        import traceback; traceback.print_exc()
        res = {"spot": s["name"], "error": str(e)}
    show(res, s["name"])

print("\nFertig.")
