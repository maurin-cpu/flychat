"""
Test: Simuliert die Tag-Generierung für Mittelland West am 09.04.2026
mit den echten Werten aus dem Meteogramm des Users.
Prüft ob jede Stunde korrekt bewertet wird und was die
THERMIK-QUALITÄT-Zusammenfassung dem LLM zeigen würde.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from chat_engine import WingcastEngine

engine = WingcastEngine.__new__(WingcastEngine)

# ─── Echte Meteogramm-Daten Mittelland West, 09.04.2026 ───
# Aus dem User-Screenshot (safe window 10:00-16:00)
# Surface Wind / Böen aus "Wind / Böen" Zeile
# Thermik-Proxy aus "Thermik" Zeile

HOURS = [
    # (hour, wind_speed, wind_gusts, climb_rate, thermal_top_m)
    # climb_rate=None wenn kein Thermik-Wert angezeigt
    (10, 2, 6,   None, None),    # Noch keine Thermik
    (11, 3, 8,   None, None),    # Noch keine Thermik
    (12, 4, 9,   1.8,  1800),    # Erste Thermik
    (13, 5, 11,  1.9,  1900),
    (14, 7, 14,  2.0,  2000),    # Peak
    (15, 8, 16,  2.0,  2000),    # Peak
    (16, 8, 15,  1.6,  1800),
]

# Typisches PL-Profil für Mittelland West 700m
# (aus dem Höhenwindgitter des Meteogramms, ca. Stunde 14-15)
PL_BASE = {
    "geopotential_height_925hPa": 820,
    "wind_speed_925hPa": 11,
    "wind_direction_925hPa": 240,
    "geopotential_height_900hPa": 1020,
    "wind_speed_900hPa": 14,
    "wind_direction_900hPa": 245,
    "geopotential_height_850hPa": 1520,
    "wind_speed_850hPa": 18,
    "wind_direction_850hPa": 250,
    "geopotential_height_800hPa": 2050,
    "wind_speed_800hPa": 22,
    "wind_direction_800hPa": 255,
    "geopotential_height_700hPa": 3100,
    "wind_speed_700hPa": 28,
    "wind_direction_700hPa": 260,
}

ELEVATION = 700

print("=" * 70)
print("MITTELLAND WEST - 09.04.2026 - STÜNDLICHE TAG-SIMULATION")
print(f"Elevation: {ELEVATION}m | Zone: mittelland")
print(f"Schwellen: warn={config.SHEAR_THRESHOLDS['mittelland']['warn']}, "
      f"danger={config.SHEAR_THRESHOLDS['mittelland']['danger']}")
print("=" * 70)

# Zähler (wie im echten Code)
thermal_hours_total = 0
thermal_clean_h = 0
tq_rough_danger_h = 0
tq_rough_warn_h = 0
tq_torn_danger_h = 0
tq_torn_warn_h = 0
tq_shear_danger_h = 0
tq_shear_warn_h = 0
peak_climb = 0.0

for hour, ws, wg, climb, th_top in HOURS:
    print(f"\n-- {hour:02d}:00 -- Wind {ws}/{wg} km/h | ", end="")

    if climb is None or climb < config.THERMAL_QUALITY_MIN_CLIMB:
        print(f"Thermik: {'keine' if climb is None else f'{climb} m/s (< MIN_CLIMB)'}")
        print(f"  -> Keine Tags (Gate: keine Thermik)")
        continue

    print(f"Thermik: {climb} m/s bis {th_top}m")
    if climb > peak_climb:
        peak_climb = climb

    tags, debug = engine._thermal_quality_tags(
        wind_speed_10m=ws,
        wind_gusts_10m=wg,
        pl_data=PL_BASE,
        elevation_m=ELEVATION,
        thermal_top_m=th_top,
        climb_rate_ms=climb,
        region_id="mittelland_west",
        altitude_gusts=None,
    )

    shear_tags = [t for t in tags if "SHEAR" in t]
    rough_tags = [t for t in tags if "ROUGH" in t]
    torn_tags = [t for t in tags if "TORN" in t]

    du_dz = debug.get("du_dz")
    bs = debug.get("bs")
    gf = debug.get("gf")
    tq = debug.get("tq_ratio")

    print(f"  Column du/dz: {du_dz:.2f}" if du_dz else "  Column du/dz: N/A", end="")
    print(f" | BS: {bs:.1f}" if bs else " | BS: N/A", end="")
    print(f" | GF: {gf:.2f}" if gf else " | GF: N/A")

    if tq:
        tq_str = f"TQ {tq['clean']}/{tq['total']} sauber"
        if tq['tags']:
            tq_str += f", {dict(tq['tags'])}"
        print(f"  {tq_str}")

    all_tags = shear_tags + rough_tags + torn_tags
    if all_tags:
        print(f"  TAGS: {', '.join(all_tags)}")
    else:
        print(f"  TAGS: (keine) <- SAUBER")

    # Zähler aktualisieren (analog chat_engine.py)
    thermal_hours_total += 1
    tq_tags_this_hour = {t for t in tags if t.startswith(("[SHEAR-", "[THERMAL-TORN-", "[THERMAL-ROUGH-"))}
    if not tq_tags_this_hour:
        thermal_clean_h += 1
    else:
        if "[THERMAL-ROUGH-UNUSABLE]" in tq_tags_this_hour:
            tq_rough_danger_h += 1
        elif "[THERMAL-ROUGH-DEGRADED]" in tq_tags_this_hour:
            tq_rough_warn_h += 1
        if "[THERMAL-TORN-UNUSABLE]" in tq_tags_this_hour:
            tq_torn_danger_h += 1
        elif "[THERMAL-TORN-DEGRADED]" in tq_tags_this_hour:
            tq_torn_warn_h += 1
        if "[SHEAR-UNUSABLE]" in tq_tags_this_hour:
            tq_shear_danger_h += 1
        elif "[SHEAR-DEGRADED]" in tq_tags_this_hour:
            tq_shear_warn_h += 1

# ─── THERMIK-QUALITÄT Zusammenfassung (identisch zum echten Code) ───
print()
print("=" * 70)
print("THERMIK-QUALITÄT ZUSAMMENFASSUNG (was das LLM sieht)")
print("=" * 70)

tq_danger_h = tq_rough_danger_h + tq_torn_danger_h + tq_shear_danger_h
tq_warn_h = tq_rough_warn_h + tq_torn_warn_h + tq_shear_warn_h
tq_parts = []
if tq_rough_danger_h:
    tq_parts.append(f"ROUGH-UNUSABLE {tq_rough_danger_h}h")
if tq_torn_danger_h:
    tq_parts.append(f"TORN-UNUSABLE {tq_torn_danger_h}h")
if tq_shear_danger_h:
    tq_parts.append(f"SHEAR-UNUSABLE {tq_shear_danger_h}h")
if tq_rough_warn_h:
    tq_parts.append(f"ROUGH-DEGRADED {tq_rough_warn_h}h")
if tq_torn_warn_h:
    tq_parts.append(f"TORN-DEGRADED {tq_torn_warn_h}h")
if tq_shear_warn_h:
    tq_parts.append(f"SHEAR-DEGRADED {tq_shear_warn_h}h")
tq_parts.append(f"sauber {thermal_clean_h}h")

unusable_pct = round(100 * tq_danger_h / thermal_hours_total) if thermal_hours_total else 0

summary = (
    f"THERMIK-QUALITÄT: {', '.join(tq_parts)} von {thermal_hours_total} Thermik-Stunden. "
    f"UNUSABLE-Anteil: {unusable_pct}% ({tq_danger_h}/{thermal_hours_total}h). "
    f"Peak-Steigen (Proxy): {peak_climb:.1f} m/s."
)
print(f"\n-> {summary}")

# ─── Bewertung ───
print()
print("=" * 70)
print("ERWARTETE LLM-BEWERTUNG")
print("=" * 70)

if tq_danger_h > 0 and unusable_pct > 50:
    verdict = "GRAY (>50% UNUSABLE)"
elif tq_danger_h > 0:
    verdict = "GRAY/GREEN (UNUSABLE vorhanden aber <50%)"
elif tq_warn_h > 0 and thermal_clean_h == 0:
    verdict = "GREEN (100% DEGRADED, 0 sauber) — RISIKO dass LLM gray setzt"
elif tq_warn_h > 0:
    verdict = f"GREEN (DEGRADED nur auf {tq_warn_h}h, {thermal_clean_h}h sauber)"
else:
    verdict = "GREEN/VIOLET (alle Stunden sauber)"

print(f"\n  Peak: {peak_climb:.1f} m/s (Schwelle gray: <1.0)")
print(f"  UNUSABLE-Anteil: {unusable_pct}%")
print(f"  Saubere Stunden: {thermal_clean_h}/{thermal_hours_total}")
print(f"\n  -> Erwartung: {verdict}")
