"""
TQ Band-Cap — VOLUMEN-Impact der TORN-PL-Binaerregel ueber ALLE Spots.

Frage: Wenn 'tiefes echtes TORN -> Stunde nicht produktiv' fuer jeden Spot gilt —
wie viele Spots/Stunden kippen wirklich? Trifft es 'jeden Spot' oder ist es
eng konzentriert auf echte Stark-Wind-Situationen?

Zaehlt pro Thermik-Stunde:
  - hat sie echtes PL-only TORN-UNU tief in der Saeule? (= wuerde die Regel greifen)
  - und mit Peak-Kern-Verschaerfung (bs_peak<=60)?  (= robuster Filter)
Aggregiert nach Spot.

Laeuft ueber denselben echten Capture-Pfad wie test_torn_shear_vs_climb.py.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from chat_engine import GleitcastEngine

CLIMB_FLOOR = 0.3
BS_DANGER = config.BS_RATIO_THRESHOLDS["danger"]   # 60
MIN_CLIMB = config.THERMAL_QUALITY_MIN_CLIMB

# pro (spot) : [thermik_std, torn_std, torn_peak_std]
from collections import defaultdict
per_spot = defaultdict(lambda: [0, 0, 0])
total = [0, 0, 0]   # thermik_std, torn_std, torn_peak_std
CURRENT = {"spot": "?"}

engine = GleitcastEngine()
engine.load_weather_from_cache()
orig_tq = engine._thermal_quality_tags


def _seg_torn(s, elevation, thermal_top, climb):
    seg_mid = (s["alt_lo"] + s["alt_hi"]) / 2
    raw = engine._parabolic_climb(seg_mid, elevation, thermal_top, climb)
    lc = max(raw, CLIMB_FLOOR)
    return s["du_dz"] > 0 and (lc / s["du_dz"]) * 100.0 <= BS_DANGER


def _capture(wind10, pl_data, elevation, thermal_top, climb):
    if not isinstance(climb, (int, float)) or climb < MIN_CLIMB:
        return
    if not isinstance(thermal_top, (int, float)) or thermal_top <= elevation:
        return
    segments, _ = engine._calculate_segment_shear(wind10, pl_data, elevation, thermal_top)
    if not segments:
        return

    # Es IST eine bewertbare Thermik-Stunde
    total[0] += 1
    per_spot[CURRENT["spot"]][0] += 1

    torn_pl = [s for s in segments
               if _seg_torn(s, elevation, thermal_top, climb)
               and abs(s["alt_lo"] - elevation) >= 1.0]
    if not torn_pl:
        return

    # Regel wuerde greifen
    total[1] += 1
    per_spot[CURRENT["spot"]][1] += 1

    # Peak-Kern-Verschaerfung: tiefstes TORN-Segment zerreisst auch den Peak-Kern?
    seg = min(torn_pl, key=lambda s: s["alt_lo"])
    bs_peak = (climb / seg["du_dz"]) * 100.0
    if bs_peak <= BS_DANGER:
        total[2] += 1
        per_spot[CURRENT["spot"]][2] += 1


def wrapped_tq(wind_speed_10m, wind_gusts_10m, pl_data, elevation_m,
               thermal_top_m, climb_rate_ms, region_id=None, altitude_gusts=None):
    res = orig_tq(wind_speed_10m, wind_gusts_10m, pl_data, elevation_m,
                  thermal_top_m, climb_rate_ms, region_id, altitude_gusts)
    try:
        _capture(wind_speed_10m, pl_data, elevation_m, thermal_top_m, climb_rate_ms)
    except Exception:
        pass
    return res


engine._thermal_quality_tags = wrapped_tq

wd = engine.weather_data or {}
spots_with_data = [s for s in engine.spots if s.get("name") in wd]
dates = sorted({ts.split("T")[0]
                for s in spots_with_data[:1]
                for ts in wd.get(s["name"], {}).get("hourly_data", {})})
print(f"Spots: {len(spots_with_data)} | Tage: {len(dates)} ({dates[0]}..{dates[-1]})")
print("Baue Kontexte ...")
for spot in spots_with_data:
    CURRENT["spot"] = spot["name"]
    for d in dates:
        try:
            engine._build_single_spot_context(spot, d)
        except Exception:
            pass


def pct(a, b):
    return f"{100*a/b:.1f}%" if b else "-"


th, torn, torn_peak = total
spots_total = len(spots_with_data)
spots_any_torn = sum(1 for v in per_spot.values() if v[1] > 0)
spots_any_peak = sum(1 for v in per_spot.values() if v[2] > 0)

print()
print("=" * 72)
print("VOLUMEN-IMPACT der TORN-PL-Binaerregel ueber alle Spots")
print("=" * 72)
print(f"Bewertbare Thermik-Stunden gesamt:        {th}")
print(f"  davon Regel greift (tiefes TORN-PL):    {torn}  ({pct(torn, th)} aller Thermik-Std)")
print(f"  davon mit Peak-Kern-Verschaerfung:      {torn_peak}  ({pct(torn_peak, th)} aller Thermik-Std)")
print()
print(f"Spots gesamt:                             {spots_total}")
print(f"  Spots mit >=1 betroffener Stunde:       {spots_any_torn}  ({pct(spots_any_torn, spots_total)} der Spots)")
print(f"  Spots mit >=1 (Peak-verschaerft):       {spots_any_peak}  ({pct(spots_any_peak, spots_total)} der Spots)")
print()

# Wie hart trifft es die betroffenen Spots? Anteil ihrer Std, der wegfaellt.
affected = [(name, v) for name, v in per_spot.items() if v[1] > 0]
affected.sort(key=lambda kv: kv[1][1], reverse=True)
print("Betroffene Spots — wie viele IHRER Thermik-Std fallen weg:")
print(f"  {'Spot':<36} {'Th-Std':>6} {'TORN':>5} {'Anteil':>7} {'Peak':>5}")
for name, v in affected[:20]:
    print(f"  {name[:36]:<36} {v[0]:>6} {v[1]:>5} {pct(v[1], v[0]):>7} {v[2]:>5}")
if len(affected) > 20:
    print(f"  ... und {len(affected) - 20} weitere Spots")
print()

# Verteilung: wie gross ist der Wegfall-Anteil pro betroffenem Spot?
fracs = sorted(v[1] / v[0] for _, v in affected if v[0] > 0)
if fracs:
    medf = fracs[len(fracs) // 2]
    allday = sum(1 for f in fracs if f >= 0.99)
    print(f"Wegfall-Anteil pro betroffenem Spot: median {medf*100:.0f}% | "
          f"Spots mit Total-Wegfall (>=99%): {allday}")
print()
print("VERDIKT:")
if spots_any_torn <= 0.15 * spots_total and torn <= 0.05 * th:
    print(f"  Eng konzentriert: nur {pct(spots_any_torn, spots_total)} der Spots, "
          f"{pct(torn, th)} der Thermik-Std. KEIN Flaechenbrand.")
elif spots_any_torn >= 0.5 * spots_total:
    print(f"  Breit: {pct(spots_any_torn, spots_total)} der Spots betroffen -> "
          f"vor Einbau Wegfall-Anteil pro Spot genau pruefen.")
else:
    print(f"  Mittel: {pct(spots_any_torn, spots_total)} der Spots, "
          f"{pct(torn, th)} der Std. Peak-Verschaerfung halbiert das Risiko.")
