"""
TQ Band-Cap — Schritt: shear-getrieben vs. climb-getrieben (Next Step aus TQ_TORN_FLYABILITY.md).

Frage: Die echten PL-only TORN-UNU-Faelle (~118 / 1% laut Schritt 0) — sind sie
von ECHTER Scherung getrieben (du_dz hoch genug, dass auch ein starker Kern zerreisst)
oder ein climb-getriebenes Rest-Artefakt (Parabel drueckt local_climb nahe 0 → B/S
klein, obwohl du_dz physikalisch unter der SHEAR-Schwelle liegt)?

Mechanik (engine/weather_context.py:1156-1167):
    local_climb = max(parabolic_climb(seg_mid), 0.3)   # CLIMB_FLOOR
    local_bs    = (local_climb / du_dz) * 100
    TORN-UNU    <=> local_bs <= 60   (BS_DANGER)

Mit local_climb am Floor (0.3) feuert TORN schon ab du_dz >= 0.5 km/h/100m —
weit unter SHEAR-warn (1.5-2.0). Das ist der Artefakt-Verdacht.

Diskriminator pro tiefstem TORN-PL-Segment:
  - du_dz vs. zonen-SHEAR-Schwellen (warn/danger)   → echte Scherungs-Staerke
  - parabol. local_climb gefloored?                 → Parabel-Naehe-Boden-Effekt
  - bs_peak = (peak_climb / du_dz)*100 <= 60 ?       → zerreisst es auch den STAERKSTEN Kern?
  - bs_raw  = (raw_climb  / du_dz)*100 <= 60 ?       → ueberlebt TORN ohne den Floor?

Klassifikation pro Stunde (tiefstes TORN-PL-Segment):
  SHEAR-ECHT   : du_dz >= danger   (echte Gefahren-Scherung, klimb-unabhaengig)
  SHEAR-WARN   : warn <= du_dz < danger
  CLIMB-ARTEF  : du_dz < warn      (TORN nur durch kleinen Climb-Nenner)

Laeuft ueber den ECHTEN Pfad (_build_single_spot_context) mit Capture-Hook,
analog test_torn_cap_position.py.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from chat_engine import GleitcastEngine
from thermik_calculator import get_terrain_zone

CLIMB_FLOOR = 0.3
BS_DANGER = config.BS_RATIO_THRESHOLDS["danger"]   # 60
MIN_CLIMB = config.THERMAL_QUALITY_MIN_CLIMB

records = []
CURRENT = {"spot": "?"}

engine = GleitcastEngine()
engine.load_weather_from_cache()
orig_tq = engine._thermal_quality_tags


def _seg_torn(s, elevation, thermal_top, climb):
    """Repliziert die TORN-UNU-Bedingung aus _thermal_quality_tags (gefloored)."""
    seg_mid = (s["alt_lo"] + s["alt_hi"]) / 2
    raw = engine._parabolic_climb(seg_mid, elevation, thermal_top, climb)
    lc = max(raw, CLIMB_FLOOR)
    return s["du_dz"] > 0 and (lc / s["du_dz"]) * 100.0 <= BS_DANGER


def _capture(wind10, pl_data, elevation, thermal_top, climb, region_id):
    if not isinstance(climb, (int, float)) or climb < MIN_CLIMB:
        return
    if not isinstance(thermal_top, (int, float)) or thermal_top <= elevation:
        return
    segments, _ = engine._calculate_segment_shear(wind10, pl_data, elevation, thermal_top)
    if not segments:
        return

    # PL-only TORN (ohne 10m-Anker-Segment), wie in Schritt 0
    torn_pl = [s for s in segments
               if _seg_torn(s, elevation, thermal_top, climb)
               and abs(s["alt_lo"] - elevation) >= 1.0]
    if not torn_pl:
        return

    zone = get_terrain_zone(elevation, region_id)
    shear_cfg = config.SHEAR_THRESHOLDS.get(zone, config.SHEAR_THRESHOLDS["alpen"])
    warn, danger = shear_cfg["warn"], shear_cfg["danger"]

    # Tiefstes TORN-PL-Segment = die Decke, die im Band-Cap zaehlen wuerde
    seg = min(torn_pl, key=lambda s: s["alt_lo"])
    du_dz = seg["du_dz"]
    seg_mid = (seg["alt_lo"] + seg["alt_hi"]) / 2
    raw_lc = engine._parabolic_climb(seg_mid, elevation, thermal_top, climb)
    floored = raw_lc < CLIMB_FLOOR
    rel = max(0.0, min(1.0, (seg["alt_lo"] - elevation) / (thermal_top - elevation)))

    bs_floor = (max(raw_lc, CLIMB_FLOOR) / du_dz) * 100.0
    bs_raw = (raw_lc / du_dz) * 100.0 if raw_lc > 0 else float("inf")
    bs_peak = (climb / du_dz) * 100.0  # mit Saeulen-Peak-Steigrate

    if du_dz >= danger:
        klass = "SHEAR-ECHT"
    elif du_dz >= warn:
        klass = "SHEAR-WARN"
    else:
        klass = "CLIMB-ARTEF"

    records.append({
        "spot": CURRENT["spot"], "zone": zone,
        "du_dz": du_dz, "warn": warn, "danger": danger,
        "peak_climb": climb, "raw_lc": raw_lc, "floored": floored,
        "rel": rel, "bs_floor": bs_floor, "bs_raw": bs_raw, "bs_peak": bs_peak,
        "klass": klass,
        "torn_survives_no_floor": bs_raw <= BS_DANGER,
        "torn_tears_peak": bs_peak <= BS_DANGER,
        "n_torn_pl_segs": len(torn_pl),
    })


def wrapped_tq(wind_speed_10m, wind_gusts_10m, pl_data, elevation_m,
               thermal_top_m, climb_rate_ms, region_id=None, altitude_gusts=None):
    res = orig_tq(wind_speed_10m, wind_gusts_10m, pl_data, elevation_m,
                  thermal_top_m, climb_rate_ms, region_id, altitude_gusts)
    try:
        _capture(wind_speed_10m, pl_data, elevation_m, thermal_top_m, climb_rate_ms, region_id)
    except Exception:
        pass
    return res


engine._thermal_quality_tags = wrapped_tq

wd = engine.weather_data or {}
spots_with_data = [s for s in engine.spots if s.get("name") in wd]
dates = sorted({ts.split("T")[0]
                for s in spots_with_data[:1]
                for ts in wd.get(s["name"], {}).get("hourly_data", {})})
print(f"Spots: {len(spots_with_data)} | Tage: {dates}")
print("Baue Kontexte ...")
for spot in spots_with_data:
    CURRENT["spot"] = spot["name"]
    for d in dates:
        try:
            engine._build_single_spot_context(spot, d)
        except Exception:
            pass


def pct(a, b):
    return f"{100*a/b:.0f}%" if b else "-"


def med(xs):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else float("nan")


n = len(records)
print()
print("=" * 72)
print("SHEAR-getrieben vs. CLIMB-getrieben  —  echte PL-only TORN-UNU-Faelle")
print("=" * 72)
print(f"Echte TORN-PL-Stunden erfasst: {n}")
if not n:
    print("Keine echten TORN-PL-Faelle im Cache (Schwachwind-Lage). Foehn-Tag noetig.")
    sys.exit(0)

for k in ("SHEAR-ECHT", "SHEAR-WARN", "CLIMB-ARTEF"):
    rows = [r for r in records if r["klass"] == k]
    if not rows:
        print(f"\n{k:<12}: 0")
        continue
    floored = sum(1 for r in rows if r["floored"])
    surv = sum(1 for r in rows if r["torn_survives_no_floor"])
    tears = sum(1 for r in rows if r["torn_tears_peak"])
    print(f"\n{k:<12}: {len(rows)} ({pct(len(rows), n)})")
    print(f"   du_dz       median {med([r['du_dz'] for r in rows]):.2f} km/h/100m "
          f"(Schwellen warn~{med([r['warn'] for r in rows]):.1f} / danger~{med([r['danger'] for r in rows]):.1f})")
    print(f"   rel-Hoehe   median {med([r['rel'] for r in rows]):.2f}")
    print(f"   peak-climb  median {med([r['peak_climb'] for r in rows]):.2f} m/s")
    print(f"   raw local   median {med([r['raw_lc'] for r in rows]):.2f} m/s   "
          f"| gefloored(<0.3): {floored} ({pct(floored, len(rows))})")
    print(f"   ueberlebt OHNE Floor (bs_raw<=60):  {surv} ({pct(surv, len(rows))})")
    print(f"   zerreisst PEAK-Kern (bs_peak<=60):  {tears} ({pct(tears, len(rows))})")

# Gesamt-Aggregat
print()
print("-" * 72)
echt = sum(1 for r in records if r["klass"] in ("SHEAR-ECHT", "SHEAR-WARN"))
artef = sum(1 for r in records if r["klass"] == "CLIMB-ARTEF")
floored_all = sum(1 for r in records if r["floored"])
tears_all = sum(1 for r in records if r["torn_tears_peak"])
surv_all = sum(1 for r in records if r["torn_survives_no_floor"])
print(f"GESAMT: shear-getrieben (warn+danger): {echt} ({pct(echt, n)})  |  "
      f"climb-artefakt (du_dz<warn): {artef} ({pct(artef, n)})")
print(f"        gefloored: {floored_all} ({pct(floored_all, n)})  |  "
      f"ueberlebt ohne Floor: {surv_all} ({pct(surv_all, n)})  |  "
      f"zerreisst Peak-Kern: {tears_all} ({pct(tears_all, n)})")
print()
print("VERDIKT:")
if tears_all >= 0.5 * n:
    print(f"  Mehrheit ({pct(tears_all, n)}) zerreisst sogar den Peak-Kern -> TORN echt, "
          f"vertrauenswuerdig. Simple Binaer-Regel auf TORN-PL ist solide.")
elif artef >= 0.5 * n:
    print(f"  Mehrheit ({pct(artef, n)}) ist climb-getrieben (du_dz < SHEAR-warn) -> tiefes TORN "
          f"unzuverlaessig. Erst CLIMB_FLOOR / B/S-Boden sanieren, dann Regel.")
else:
    print(f"  Gemischt: {pct(echt, n)} shear-getrieben, {pct(artef, n)} climb-artefakt. "
          f"Eine du_dz>=warn-Bedingung am TORN-Tag wuerde die Artefakte aussieben.")
