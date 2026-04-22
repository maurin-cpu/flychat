"""
Test: Prüft ob die neuen Shear-Schwellen für Mittelland/Jura korrekt greifen.
Simuliert typische Windprofile und prüft welche Tags generiert werden.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from chat_engine import GleitcastEngine

engine = GleitcastEngine.__new__(GleitcastEngine)  # ohne __init__

print("=" * 70)
print("SHEAR THRESHOLDS TEST")
print("=" * 70)
print()
print("Aktuelle Schwellen:")
for zone, t in config.SHEAR_THRESHOLDS.items():
    print(f"  {zone:15s}: warn={t['warn']}, danger={t['danger']}")
print()

# ──────────────────────────────────────────────────────────────────
# Testszenarien: (name, zone, elevation, surface_wind, surface_gusts,
#                 climb_rate, pl_winds, expected_column_tag)
# pl_winds: [(altitude_m, wind_speed_kmh), ...]
# ──────────────────────────────────────────────────────────────────

SCENARIOS = [
    # --- Mittelland: typischer guter Tag ---
    {
        "name": "Mittelland West - ruhiger Tag (SOLL: KEIN Shear-Tag)",
        "elevation": 700,
        "surface_wind": 8,
        "surface_gusts": 16,
        "climb_rate": 2.0,
        "region_id": "mittelland_west",
        "pl_profile": {
            "geopotential_height_925hPa": 800,
            "wind_speed_925hPa": 10,
            "wind_direction_925hPa": 240,
            "geopotential_height_900hPa": 1000,
            "wind_speed_900hPa": 14,
            "wind_direction_900hPa": 245,
            "geopotential_height_850hPa": 1500,
            "wind_speed_850hPa": 20,
            "wind_direction_850hPa": 250,
            "geopotential_height_800hPa": 2000,
            "wind_speed_800hPa": 22,
            "wind_direction_800hPa": 255,
        },
        "thermal_top": 2000,
        "expect_shear": None,  # kein Tag erwartet
    },
    {
        "name": "Mittelland West - windiger Tag (SOLL: SHEAR-DEGRADED)",
        "elevation": 700,
        "surface_wind": 12,
        "surface_gusts": 25,
        "climb_rate": 2.0,
        "region_id": "mittelland_west",
        "pl_profile": {
            "geopotential_height_925hPa": 800,
            "wind_speed_925hPa": 18,
            "wind_direction_925hPa": 240,
            "geopotential_height_900hPa": 1000,
            "wind_speed_900hPa": 25,
            "wind_direction_900hPa": 245,
            "geopotential_height_850hPa": 1500,
            "wind_speed_850hPa": 35,
            "wind_direction_850hPa": 250,
            "geopotential_height_800hPa": 2000,
            "wind_speed_800hPa": 40,
            "wind_direction_800hPa": 255,
        },
        "thermal_top": 2000,
        "expect_shear": "[SHEAR-DEGRADED]",
    },
    {
        "name": "Mittelland West - Föhn/Sturm (SOLL: SHEAR-UNUSABLE)",
        "elevation": 700,
        "surface_wind": 15,
        "surface_gusts": 35,
        "climb_rate": 1.5,
        "region_id": "mittelland_west",
        "pl_profile": {
            "geopotential_height_925hPa": 800,
            "wind_speed_925hPa": 25,
            "wind_direction_925hPa": 180,
            "geopotential_height_900hPa": 1000,
            "wind_speed_900hPa": 35,
            "wind_direction_900hPa": 190,
            "geopotential_height_850hPa": 1500,
            "wind_speed_850hPa": 50,
            "wind_direction_850hPa": 200,
            "geopotential_height_800hPa": 2000,
            "wind_speed_800hPa": 65,
            "wind_direction_800hPa": 210,
        },
        "thermal_top": 1800,
        "expect_shear": "[SHEAR-UNUSABLE]",
    },
    # --- Jura: typischer Tag ---
    {
        "name": "Jura West - normaler Tag (SOLL: KEIN Shear-Tag)",
        "elevation": 1200,
        "surface_wind": 10,
        "surface_gusts": 18,
        "climb_rate": 2.0,
        "region_id": "jura_west",
        "pl_profile": {
            "geopotential_height_900hPa": 1050,
            "wind_speed_900hPa": 12,
            "wind_direction_900hPa": 240,
            "geopotential_height_850hPa": 1500,
            "wind_speed_850hPa": 18,
            "wind_direction_850hPa": 250,
            "geopotential_height_800hPa": 2000,
            "wind_speed_800hPa": 22,
            "wind_direction_800hPa": 255,
        },
        "thermal_top": 2500,
        "expect_shear": None,
    },
    # --- Alpen: unverändert ---
    {
        "name": "Berner Oberland - normaler Tag (SOLL: KEIN Shear-Tag)",
        "elevation": 1800,
        "surface_wind": 5,
        "surface_gusts": 12,
        "climb_rate": 2.5,
        "region_id": "berner_oberland",
        "pl_profile": {
            "geopotential_height_850hPa": 1500,
            "wind_speed_850hPa": 8,
            "wind_direction_850hPa": 240,
            "geopotential_height_800hPa": 2000,
            "wind_speed_800hPa": 12,
            "wind_direction_800hPa": 250,
            "geopotential_height_700hPa": 3100,
            "wind_speed_700hPa": 20,
            "wind_direction_700hPa": 260,
        },
        "thermal_top": 3500,
        "expect_shear": None,
    },
    {
        "name": "Berner Oberland - Scherung (SOLL: SHEAR-DEGRADED)",
        "elevation": 1800,
        "surface_wind": 8,
        "surface_gusts": 15,
        "climb_rate": 2.5,
        "region_id": "berner_oberland",
        "pl_profile": {
            "geopotential_height_850hPa": 1500,
            "wind_speed_850hPa": 10,
            "wind_direction_850hPa": 240,
            "geopotential_height_800hPa": 2000,
            "wind_speed_800hPa": 18,
            "wind_direction_800hPa": 250,
            "geopotential_height_700hPa": 3100,
            "wind_speed_700hPa": 35,
            "wind_direction_700hPa": 260,
        },
        "thermal_top": 3500,
        "expect_shear": "[SHEAR-DEGRADED]",
    },
]


def run_test(scenario):
    """Führt einen einzelnen Test aus."""
    tags, debug = engine._thermal_quality_tags(
        wind_speed_10m=scenario["surface_wind"],
        wind_gusts_10m=scenario["surface_gusts"],
        pl_data=scenario["pl_profile"],
        elevation_m=scenario["elevation"],
        thermal_top_m=scenario["thermal_top"],
        climb_rate_ms=scenario["climb_rate"],
        region_id=scenario["region_id"],
        altitude_gusts=None,
    )

    shear_tags = [t for t in tags if "SHEAR" in t]
    rough_tags = [t for t in tags if "ROUGH" in t]
    torn_tags = [t for t in tags if "TORN" in t]

    expected = scenario["expect_shear"]
    if expected is None:
        ok = len(shear_tags) == 0
    else:
        ok = expected in shear_tags

    return ok, tags, debug, shear_tags, rough_tags, torn_tags


print("-" * 70)
all_ok = True
for sc in SCENARIOS:
    ok, tags, debug, shear_tags, rough_tags, torn_tags = run_test(sc)
    status = "PASS" if ok else "FAIL"
    if not ok:
        all_ok = False

    print(f"\n[{status}] {sc['name']}")
    print(f"  Zone: {debug['zone']}, Elevation: {sc['elevation']}m")
    print(f"  Surface: {sc['surface_wind']}/{sc['surface_gusts']} km/h, Climb: {sc['climb_rate']} m/s")
    print(f"  Column du/dz: {debug['du_dz']:.2f} km/h/100m" if debug['du_dz'] else "  Column du/dz: N/A")
    print(f"  BS ratio: {debug['bs']:.1f}" if debug['bs'] else "  BS ratio: N/A")
    print(f"  Gust factor: {debug['gf']:.2f}" if debug['gf'] else "  Gust factor: N/A")

    zone = debug["zone"]
    thresh = config.SHEAR_THRESHOLDS.get(zone, {})
    print(f"  Schwellen ({zone}): warn={thresh.get('warn')}, danger={thresh.get('danger')}")

    print(f"  SHEAR-Tags:  {shear_tags if shear_tags else '(keine)'}")
    print(f"  ROUGH-Tags:  {rough_tags if rough_tags else '(keine)'}")
    print(f"  TORN-Tags:   {torn_tags if torn_tags else '(keine)'}")
    print(f"  Erwartet:    {sc['expect_shear'] if sc['expect_shear'] else '(kein Shear-Tag)'}")

    # TQ ratio
    tq = debug.get("tq_ratio")
    if tq:
        print(f"  TQ-Ratio:    {tq['clean']}/{tq['total']} sauber, Tags: {dict(tq['tags']) if tq['tags'] else 'keine'}")

print()
print("=" * 70)
if all_ok:
    print("ALLE TESTS BESTANDEN")
else:
    print("EINIGE TESTS FEHLGESCHLAGEN")
    sys.exit(1)
