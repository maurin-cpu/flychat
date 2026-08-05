"""Verifiziert die 4 Vorab-Fixes nach LLM-Run.

Liest data/spot_analyses.json + region_analyses.json und prueft pro Fix
die Cache-Konsistenz. Kein UI noetig.
"""
import io
import json
import sys
from collections import Counter

# Windows-Console: forciere UTF-8 statt cp1252
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

print("=" * 60)
print("VERIFIKATION FIX 1-4 - RATING_CONCEPT v1.3")
print("=" * 60)

spots = json.load(open('data/spot_analyses.json', encoding='utf-8'))
regions = json.load(open('data/region_analyses.json', encoding='utf-8'))

def _safety_status(e):
    """safety_status liegt im 'safety'-Sub-Dict (split-phase) oder top-level."""
    return e.get("safety_status") or e.get("safety", {}).get("safety_status") or ""

# Nur Eintraege mit gueltigem safety_status (also LLM-prozessiert) zaehlen.
def flat_entries(data, kind):
    out = []
    for name, days in data.items():
        for date, e in days.items():
            if not isinstance(e, dict): continue
            if _safety_status(e) in ("safe", "conditional", "not_safe"):
                out.append((kind, name, date, e))
    return out

spot_entries = flat_entries(spots, "spot")
region_entries = flat_entries(regions, "region")
all_entries = spot_entries + region_entries

print(f"\nTotal: {len(spot_entries)} Spot-Days, {len(region_entries)} Region-Days, "
      f"{len(all_entries)} kombiniert")

# ────────────────────────────────────────────────────────────
# FIX 1: gray-Bucket aufgespalten (Mech-Danger vs Low-Reward)
# ────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("FIX 1: decide_flyability_low_reward + decide_flyability_mech_danger")
print("=" * 60)

low_reward_count = 0
mech_danger_count = 0
old_downgrade_count = 0
for k, name, date, e in all_entries:
    deca = str(e.get("_decisions_applied", []))
    if "FlyabilityLowReward" in deca: low_reward_count += 1
    if "FlyabilityMechDanger" in deca: mech_danger_count += 1
    if "FlyabilityDowngrade(" in deca: old_downgrade_count += 1
print(f"  FlyabilityLowReward Tag:    {low_reward_count}")
print(f"  FlyabilityMechDanger Tag:   {mech_danger_count}")
print(f"  ALTER FlyabilityDowngrade:  {old_downgrade_count}  (sollte 0 sein)")

# Mech-Danger soll safety_band auf amber/red drueben
mech_amber_red = 0
mech_green = 0
for k, name, date, e in all_entries:
    if "FlyabilityMechDanger" in str(e.get("_decisions_applied", [])):
        band = e.get("safety_band", "")
        if band in ("amber", "red"): mech_amber_red += 1
        elif band == "green": mech_green += 1
print(f"  Mech-Danger → amber/red:    {mech_amber_red}")
print(f"  Mech-Danger → GREEN (BUG):  {mech_green}  (sollte 0 sein)")

# ────────────────────────────────────────────────────────────
# FIX 2: is_conditional deterministisch
# ────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("FIX 2: is_conditional deterministisch (Stage-Inversion)")
print("=" * 60)

bug_cond_no_flag = 0  # safety=conditional aber is_conditional=False
bug_notsafe_with_flag = 0  # safety=not_safe aber is_conditional=True
bug_safe_with_flag = 0  # safety=safe aber is_conditional=True
for k, name, date, e in all_entries:
    s = _safety_status(e)
    flag = bool(e.get("is_conditional", False))
    if s == "conditional" and not flag: bug_cond_no_flag += 1
    if s == "not_safe" and flag: bug_notsafe_with_flag += 1
    if s == "safe" and flag: bug_safe_with_flag += 1
print(f"  conditional ohne Flag:      {bug_cond_no_flag}  (sollte 0)")
print(f"  not_safe MIT Flag:          {bug_notsafe_with_flag}  (sollte 0)")
print(f"  safe MIT Flag:              {bug_safe_with_flag}  (sollte 0)")

# ────────────────────────────────────────────────────────────
# FIX 3: experience_score = rating × 10 + experience_stars
# ────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("FIX 3: experience_score + experience_stars")
print("=" * 60)

mismatch_count = 0
mismatches = []
for k, name, date, e in all_entries:
    r = e.get("rating")
    es = e.get("experience_score")
    if r is None or es is None: continue
    expected = round(float(r) * 10)
    if abs(int(es) - expected) > 1:
        mismatch_count += 1
        if len(mismatches) < 5:
            mismatches.append(f"{name}/{date}: rating={r}, score={es}, expected={expected}")
print(f"  Mismatches rating × 10 ≠ score:  {mismatch_count}  (sollte 0)")
for m in mismatches: print(f"    {m}")

# Stars-Verteilung pro Score-Bucket
star_per_score_bucket = Counter()
for k, name, date, e in all_entries:
    es = e.get("experience_score")
    st = e.get("experience_stars")
    if es is None or st is None: continue
    bucket = "0-20" if es <= 20 else "21-40" if es <= 40 else "41-60" if es <= 60 else "61-75" if es <= 75 else "76-89" if es <= 89 else "90-100"
    star_per_score_bucket[(bucket, st)] += 1
print(f"\n  Stars-Verteilung pro Score-Bucket (Konzept §8.3):")
print(f"    Erwartung: 0-20→0★, 21-40→1★, 41-60→2★, 61-75→3★, 76-89→4★, 90-100→5★")
for (bucket, stars), cnt in sorted(star_per_score_bucket.items()):
    print(f"    {bucket}: {stars}★  → {cnt} Eintraege")

# ────────────────────────────────────────────────────────────
# FIX 4: 5 Safety-Sub-Ratings + Weakest-Link MIN
# ────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("FIX 4: 5 Safety-Sub-Ratings + MIN-Aggregation")
print("=" * 60)

sub_fields = ['wind_safety_rating', 'gust_safety_rating', 'aloft_safety_rating',
              'foehn_safety_rating', 'rain_safety_rating', 'thunderstorm_safety_rating',
              'cape_safety_rating', 'visibility_safety_rating']

with_all_subs = 0
without_subs = 0
for k, name, date, e in all_entries:
    if all(e.get(f) is not None for f in sub_fields):
        with_all_subs += 1
    elif _safety_status(e) != "no_data":
        without_subs += 1
print(f"  Eintraege mit allen 5 Sub-Ratings:  {with_all_subs}")
print(f"  Eintraege OHNE Sub-Ratings (BUG):    {without_subs}  (sollte 0)")

# MIN-Aggregation: safety_rating = min(5 subs) +/- 0.2
min_violations = 0
violations = []
for k, name, date, e in all_entries:
    subs = [e.get(f) for f in sub_fields]
    if not all(isinstance(v, (int, float)) for v in subs): continue
    sr = e.get("safety_rating")
    if sr is None: continue
    expected = min(subs)
    if abs(float(sr) - expected) > 0.2:
        min_violations += 1
        if len(violations) < 5:
            violations.append(f"{name}/{date}: subs={subs}, rating={sr}, min={expected}")
print(f"  MIN-Aggregation Verletzungen:        {min_violations}  (sollte 0)")
for v in violations: print(f"    {v}")

# ────────────────────────────────────────────────────────────
# BONUS: Altitude-Rating (v1.4) bei Spots
# ────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("BONUS v1.4: altitude_rating (nur Spots)")
print("=" * 60)

spot_with_alt = 0
spot_without_alt = 0
region_with_alt = 0
for k, name, date, e in all_entries:
    has = isinstance(e.get("altitude_rating"), (int, float))
    if k == "spot":
        if has: spot_with_alt += 1
        elif _safety_status(e) not in ("no_data",): spot_without_alt += 1
    else:
        if has: region_with_alt += 1
print(f"  Spots mit altitude_rating:    {spot_with_alt}")
print(f"  Spots OHNE (BUG):              {spot_without_alt}")
print(f"  Regions MIT altitude (BUG):   {region_with_alt}  (sollte 0 sein)")

# Stichprobe altitude_rating-Werte
alt_dist = Counter()
for k, name, date, e in spot_entries:
    if isinstance(e.get("altitude_rating"), (int, float)):
        alt_dist[int(e["altitude_rating"])] += 1
print(f"  Verteilung altitude_rating (Spots):")
for v in sorted(alt_dist):
    print(f"    {v}: {alt_dist[v]}")

# ────────────────────────────────────────────────────────────
# BONUS: comfort_index
# ────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("BONUS: comfort_index")
print("=" * 60)
with_comfort = 0
without_comfort_safe = 0
for k, name, date, e in all_entries:
    if isinstance(e.get("comfort_index"), (int, float)):
        with_comfort += 1
    elif _safety_status(e) in ("safe", "conditional"):
        without_comfort_safe += 1
print(f"  Eintraege mit comfort_index:       {with_comfort}")
print(f"  safe/conditional OHNE (BUG):        {without_comfort_safe}")

# ────────────────────────────────────────────────────────────
# BONUS: safety_band-Verteilung
# ────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("BONUS: safety_band-Verteilung")
print("=" * 60)
band_dist = Counter(e.get("safety_band", "missing") for k, n, d, e in all_entries)
for b, c in band_dist.most_common():
    print(f"  {b}: {c}")

# ────────────────────────────────────────────────────────────
# BONUS: noAnalysis-Flag
# ────────────────────────────────────────────────────────────
print("\n" + "=" * 60)
print("BONUS: noAnalysis-Flag (RATING_CONCEPT v1.3 §8.6)")
print("=" * 60)
na_count = Counter()
for k, name, date, e in all_entries:
    if e.get("noAnalysis"):
        na_count[e.get("noAnalysisReason", "?")] += 1
for reason, c in na_count.most_common():
    print(f"  {reason}: {c}")
if not na_count:
    print(f"  Kein Spot mit noAnalysis (kann normal sein wenn alle Spots am Tag relevant sind)")

print("\n" + "=" * 60)
print("DONE")
print("=" * 60)
