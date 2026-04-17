"""Test: Prüft ob alle Regionen Höhenböen haben."""
import requests
import json
import sys

BASE = "http://localhost:5000"

REGIONS = [
    "seeland_emmental", "mittelland_west", "mittelland_ost", "genferseeregion",
    "jura_ost", "jura_west", "jura_zentral",
    "mittelland_zentral", "glarnerland_walensee", "schwarzsee_gantrisch",
    "suedbuenden", "urner_alpen", "waadtlaender_alpen", "alpstein",
    "tessin_zentral", "chur_mittelbuenden", "berner_oberland",
    "zentralschweizer_voralpen",
    "berner_voralpen", "freiburger_voralpen", "mattertal_saastal", "tessin_nord",
    "zentralwallis", "engadin_unter", "unterwallis", "oberwallis_goms",
    "surselva", "zentrales_mittelland", "engadin_ober",
]


def check_region(region_id):
    """Prüft eine Region auf Böen-Daten."""
    url = f"{BASE}/api/region-altitude-wind/{region_id}"
    try:
        resp = requests.get(url, timeout=10)
    except requests.exceptions.ConnectionError:
        return None, "Server nicht erreichbar"

    if resp.status_code != 200:
        return None, f"HTTP {resp.status_code}"

    data = resp.json()
    dates = data.get("dates", [])
    if not dates:
        return None, "Keine Daten"

    # Statistik über alle Stunden des ersten Tages
    first_day = dates[0]
    hours = data.get("data", {}).get(first_day, [])

    total_cells = 0
    cells_with_gusts = 0  # wind_gusts > wind_speed + 1
    cells_with_gust_field = 0
    cells_missing_gust_field = 0
    max_gust_diff = 0
    sample_no_gust = []

    for h in hours:
        for level in h.get("profiles", []):
            total_cells += 1
            ws = level.get("wind_speed", 0)
            wg = level.get("wind_gusts")

            if wg is None:
                cells_missing_gust_field += 1
                sample_no_gust.append(level)
            else:
                cells_with_gust_field += 1
                diff = wg - ws
                if diff > max_gust_diff:
                    max_gust_diff = diff
                if round(wg) > round(ws) + 1:
                    cells_with_gusts += 1

    return {
        "total": total_cells,
        "with_gust_field": cells_with_gust_field,
        "missing_gust_field": cells_missing_gust_field,
        "visible_gusts": cells_with_gusts,
        "max_diff": round(max_gust_diff, 1),
        "pct_visible": round(100 * cells_with_gusts / total_cells, 1) if total_cells else 0,
        "sample_no_gust": sample_no_gust[:2],
    }, None


def main():
    print(f"Prüfe {len(REGIONS)} Regionen auf Höhenböen...\n")
    print(f"{'Region':<30} {'Cells':>6} {'Gust?':>6} {'Sichtbar':>8} {'%':>6} {'MaxDiff':>8} {'Status'}")
    print("-" * 85)

    problems = []
    for rid in REGIONS:
        result, error = check_region(rid)
        if error:
            print(f"{rid:<30} {'':>6} {'':>6} {'':>8} {'':>6} {'':>8} FEHLER: {error}")
            if error == "Server nicht erreichbar":
                print("\n>>> Server läuft nicht! Bitte starten mit: python main.py")
                sys.exit(1)
            problems.append((rid, error))
            continue

        status = "OK" if result["visible_gusts"] > 0 else "KEINE BÖEN!"
        if result["missing_gust_field"] > 0:
            status = f"MISSING ({result['missing_gust_field']}x)"

        print(f"{rid:<30} {result['total']:>6} {result['with_gust_field']:>6} "
              f"{result['visible_gusts']:>8} {result['pct_visible']:>5}% "
              f"{result['max_diff']:>7} {status}")

        if result["visible_gusts"] == 0:
            problems.append((rid, "Keine sichtbaren Böen"))
        if result["missing_gust_field"] > 0:
            problems.append((rid, f"{result['missing_gust_field']} Levels ohne wind_gusts Feld"))

    print("\n" + "=" * 85)
    if problems:
        print(f"\n{len(problems)} Probleme gefunden:")
        for rid, issue in problems:
            print(f"  - {rid}: {issue}")
    else:
        print("\nAlle Regionen haben Böen-Daten!")


if __name__ == "__main__":
    main()
