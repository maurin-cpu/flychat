"""
Band-Cap-Potenzial fuer REGIONEN.
Frage (User-Hypothese): Bei den gerissenen Region-Stunden — wie oft sitzt
der Riss HOCH genug, dass darunter noch ein FLIEGBARES Band bleibt
(>= min_band_depth)? Wenn oft → Band-Cap lohnt sich fuer Regionen
(anders als bei Spots, wo der Riss direkt ueberm Startplatz sitzt).

Misst pro Region-Thermik-Stunde mit Riss IM Band:
  - tear_alt   = unterstes zerrissenes Segment (anker-frei, du_dz>=warn, B/S<=danger)
  - band_below = tear_alt - elev_ref
  - rel        = (tear_alt - elev_ref) / (thermal_top - elev_ref)
  - usable     = band_below >= min_band_depth(climb, zone)
"""
import sys, os
from statistics import median
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from chat_engine import WingcastEngine
from source_area import _load_regions
from thermik_calculator import get_terrain_zone, min_band_depth

MIN_CLIMB = config.THERMAL_QUALITY_MIN_CLIMB
PROD_MIN = config.PRODUCTIVE_CLIMB_MIN
BS_DANGER = config.BS_RATIO_THRESHOLDS["danger"]
CLIMB_FLOOR = 0.3

engine = WingcastEngine()
engine.load_weather_from_cache()
orig_tq = engine._thermal_quality_tags
recs = []


def wrapped(wind_speed_10m, wind_gusts_10m, pl_data, elevation_m, thermal_top_m,
            climb_rate_ms, region_id=None, altitude_gusts=None):
    res = orig_tq(wind_speed_10m, wind_gusts_10m, pl_data, elevation_m,
                  thermal_top_m, climb_rate_ms, region_id, altitude_gusts)
    try:
        climb, elev, ttop = climb_rate_ms, elevation_m, thermal_top_m
        if not (isinstance(climb, (int, float)) and climb >= PROD_MIN):
            return res
        if not (isinstance(ttop, (int, float)) and ttop > elev):
            return res
        zone = get_terrain_zone(elev, region_id)
        warn = config.SHEAR_THRESHOLDS.get(zone, config.SHEAR_THRESHOLDS["alpen"])["warn"]
        segs, _ = engine._calculate_segment_shear(
            wind_speed_10m, pl_data, elev, ttop, include_surface_anchor=False)
        torn = []
        for s in segs:
            if s["alt_hi"] > ttop:           # nur Segmente IM nutzbaren Band
                continue
            du = s["du_dz"]
            if du < warn:                    # mein Shear-Guard
                continue
            seg_mid = (s["alt_lo"] + s["alt_hi"]) / 2
            lc = max(engine._parabolic_climb(seg_mid, elev, ttop, climb), CLIMB_FLOOR)
            if du > 0 and (lc / du) * 100.0 <= BS_DANGER:
                torn.append(s)
        if not torn:
            return res
        tear_alt = min(t["alt_lo"] for t in torn)
        band_below = tear_alt - elev
        rel = band_below / (ttop - elev)
        need = min_band_depth(climb, zone)
        recs.append({"zone": zone, "tear_alt": tear_alt, "band_below": band_below,
                     "rel": rel, "need": need, "usable": band_below >= need,
                     "ttop": ttop, "elev": elev, "climb": climb})
    except Exception:
        pass
    return res


engine._thermal_quality_tags = wrapped

regions = [r for r in _load_regions() if r["id"] in engine.region_weather_data]
dates = sorted({ts.split("T")[0]
                for ts in engine.region_weather_data[regions[0]["id"]].get("hourly_data", {})})
for region in regions:
    for d in dates:
        try:
            engine._build_single_region_context(region, d)
        except Exception:
            pass

n = len(recs)
print("=" * 64)
print(f"REGION Band-Cap-Potenzial — {n} Stunden mit Riss IM nutzbaren Band")
print("=" * 64)
if n:
    usable = [r for r in recs if r["usable"]]
    print(f"Median rel-Hoehe des Risses : {median(r['rel'] for r in recs):.2f}  "
          f"(0=Boden, 1=Top)")
    print(f"Median Band UNTER dem Riss  : {median(r['band_below'] for r in recs):.0f} m")
    print(f"Stunden mit FLIEGBAREM Band darunter (>= min_band_depth): "
          f"{len(usable)} / {n}  ({100*len(usable)/n:.0f}%)")
    print()
    print("Verteilung rel-Hoehe:")
    for lo, hi in [(0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.01)]:
        c = sum(1 for r in recs if lo <= r["rel"] < hi)
        bar = "#" * c
        print(f"  {lo:.1f}-{hi:.1f}: {c:>3} {bar}")
    print()
    # --- Foehn-Proxy: nach Saeulen-TIEFE schichten (Foehn = tiefe Saeule) ---
    print("FOEHN-PROXY — Band-Cap-Potenzial nach Saeulen-Tiefe (Top - elev_ref):")
    print(f"{'Tiefe':<14}{'n Risse':>8}{'% fliegb. drunter':>20}{'Med rel':>10}{'Med Band':>10}")
    buckets = [("flach <1000m", 0, 1000), ("mittel 1000-1800", 1000, 1800),
               ("tief >1800m", 1800, 99999)]
    for label, lo, hi in buckets:
        grp = [r for r in recs if lo <= (r["ttop"] - r["elev"]) < hi]
        if not grp:
            print(f"{label:<14}{0:>8}{'-':>20}{'-':>10}{'-':>10}")
            continue
        u = sum(1 for r in grp if r["usable"])
        print(f"{label:<14}{len(grp):>8}{f'{u}/{len(grp)} = {100*u/len(grp):.0f}%':>20}"
              f"{median(r['rel'] for r in grp):>10.2f}"
              f"{median(r['band_below'] for r in grp):>10.0f}")
    print()
    print("Beispiele mit fliegbarem Band darunter:")
    for r in sorted(usable, key=lambda x: -x["band_below"])[:8]:
        print(f"  {r['zone']:<10} Riss@{r['tear_alt']:.0f}m  Band darunter "
              f"{r['band_below']:.0f}m (braucht {r['need']:.0f})  "
              f"rel={r['rel']:.2f}  climb={r['climb']:.1f}  Top={r['ttop']:.0f}")
else:
    print("Kein Riss im nutzbaren Band gefunden.")
