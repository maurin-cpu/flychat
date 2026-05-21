"""Sector-Audit: kombiniert observations.csv (False-Positives) mit DB-Sektor und
gemessenem Wind zu sector_audit.csv."""
import csv, json, os
from pathlib import Path

# Direction codes -> degrees (centers)
DIR = {
    'N': 0, 'NNO': 22.5, 'NO': 45, 'ONO': 67.5,
    'O': 90, 'OSO': 112.5, 'SO': 135, 'SSO': 157.5,
    'S': 180, 'SSW': 202.5, 'SW': 225, 'WSW': 247.5,
    'W': 270, 'WNW': 292.5, 'NW': 315, 'NNW': 337.5,
}


def parse_sector(text):
    """'NW-NO' -> (315.0, 45.0). Returns (None, None) if unparseable."""
    if not text or '-' not in text:
        return None, None
    parts = text.split('-')
    if len(parts) != 2:
        return None, None
    a = DIR.get(parts[0].strip())
    b = DIR.get(parts[1].strip())
    return a, b


def short_arc(a, b):
    """Returns (start, end, width_deg) of the SHORTER arc between a and b."""
    cw = (b - a) % 360  # clockwise from a to b
    ccw = (a - b) % 360
    if cw <= ccw:
        return a, b, cw
    else:
        return b, a, ccw


def in_sector(wind, a, b):
    """True if wind is in the short arc from a to b. Returns (in, width)."""
    start, end, width = short_arc(a, b)
    # delta clockwise from start
    delta = (wind - start) % 360
    return delta <= width, width


def angular_dist(wind, a, b):
    """Minimum angular distance to either edge of the sector (signed: negative if inside)."""
    inside, width = in_sector(wind, a, b)
    if inside:
        # how far inside (negative number)
        start, end, _ = short_arc(a, b)
        d_start = (wind - start) % 360
        d_end = (end - wind) % 360
        return -min(d_start, d_end)
    # outside — distance to nearest edge
    d_a = min((wind - a) % 360, (a - wind) % 360)
    d_b = min((wind - b) % 360, (b - wind) % 360)
    return min(d_a, d_b)


def classify(in_sec, edge_dist, gust, no_go, launches, best_km):
    """Heuristic verdict."""
    nogo_txt = (no_go or '').lower()
    sektor_filter = 'windrichtung' in nogo_txt and 'ausserhalb' in nogo_txt
    block_filter = 'kein zusammenhaengender block' in nogo_txt or 'nur ' in nogo_txt and 'sauber' in nogo_txt
    harte_warnungen = 'harte warnungen' in nogo_txt

    if in_sec and sektor_filter:
        return "FILTER-BUG: Wind IM Sektor, Engine sagt aussen → Code-Bug"
    if in_sec and block_filter:
        return "BLOCK-FILTER zu hart: Wind passt, nur Stunden-Block scheitert (I-007)"
    if in_sec and harte_warnungen:
        return "HARTE-WARNUNGEN-FILTER: Wind im Sektor, harte Warnungen blocken"
    if not in_sec:
        try:
            g = float(gust) if gust else 0
        except: g = 0
        if g < 20:
            return f"I-008 + SEKTOR: Wind {edge_dist:.0f}° ausserhalb, aber Gust {g:.0f} schwach"
        if edge_dist < 20:
            return f"SEKTOR ZU ENG: Wind nur {edge_dist:.0f}° ausserhalb (Toleranz ±15-20° würde reichen)"
        if edge_dist < 50:
            return f"SEKTOR MITTEL: Wind {edge_dist:.0f}° ausserhalb — Spot hat evtl. weitere Variante"
        return f"MULTI-VARIANTE FEHLT: Wind {edge_dist:.0f}° ausserhalb — Spot hat anderen Hang in Realitaet"
    return "?"


# Load weather_archive snapshots to enrich with DB-sector per spot
archives = {}
for arch in Path('data/weather_archive').glob('2026-05-*.json'):
    date_str = arch.stem
    try:
        d = json.load(open(arch, encoding='utf-8'))
        archives[date_str] = d.get('spots', {})
    except Exception as e:
        print(f"WARN: konnte {arch} nicht lesen: {e}")


# Load observations
rows = list(csv.DictReader(open('xcontest_validation/observations.csv', encoding='utf-8')))

# Filter to false-positives only
fps = [r for r in rows if r['finding_type'] in ('false_positive_notsafe', 'false_positive_caution')]

print(f"Gesamt FP-Zeilen: {len(fps)}")

audit_rows = []
for r in fps:
    spot = r['spot']
    date = r['date']
    arch_spots = archives.get(date, {})
    spot_info = arch_spots.get(spot, {})
    sektor_text = spot_info.get('windrichtung') or ''
    elevation = spot_info.get('elevation_m')
    terrain = spot_info.get('terrain_type')

    try:
        wind = float(r['wx_wind_dir_dominant_deg']) if r['wx_wind_dir_dominant_deg'] else None
    except: wind = None

    a, b = parse_sector(sektor_text)
    if wind is None or a is None or b is None:
        in_sec = None
        width = None
        edge_dist = None
        sektor_range = ''
        verdict = "PARSE-FAIL"
    else:
        in_sec, width = in_sector(wind, a, b)
        edge_dist = angular_dist(wind, a, b)
        start, end, _ = short_arc(a, b)
        sektor_range = f"{int(start)}-{int(end)}°"
        verdict = classify(in_sec, abs(edge_dist), r.get('wx_wind_gust_max_kmh'), r.get('no_go_reasons'), r.get('launches'), r.get('best_km'))

    audit_rows.append({
        'date': date,
        'spot': spot,
        'region': r.get('region', ''),
        'elevation_m': elevation if elevation is not None else '',
        'terrain_type': terrain or '',
        'db_sektor_text': sektor_text,
        'db_sektor_range_deg': sektor_range,
        'db_sektor_width_deg': f"{int(width)}" if width is not None else '',
        'measured_wind_dir_deg': f"{int(wind)}" if wind is not None else '',
        'in_sector': 'yes' if in_sec else ('no' if in_sec is False else ''),
        'edge_distance_deg': f"{abs(edge_dist):.0f}" if edge_dist is not None else '',
        'measured_gust_kmh': r.get('wx_wind_gust_max_kmh', ''),
        'no_go_reason': r.get('no_go_reasons', ''),
        'launches': r.get('launches', ''),
        'best_km': r.get('best_km', ''),
        'top_pilot': r.get('top_pilot', ''),
        'top_start_time': r.get('top_start_time', ''),
        'finding_type': r.get('finding_type', ''),
        'verdict': verdict,
        'notes': r.get('notes', '')[:120],
    })

# Sort by date then by best_km desc
def km_sort(r):
    try: return -float(r['best_km'])
    except: return 0
audit_rows.sort(key=lambda r: (r['date'], km_sort(r)))

# Write
COLS = ['date', 'spot', 'region', 'elevation_m', 'terrain_type',
        'db_sektor_text', 'db_sektor_range_deg', 'db_sektor_width_deg',
        'measured_wind_dir_deg', 'in_sector', 'edge_distance_deg', 'measured_gust_kmh',
        'no_go_reason', 'launches', 'best_km', 'top_pilot', 'top_start_time',
        'finding_type', 'verdict', 'notes']

out_path = 'xcontest_validation/sector_audit.csv'
with open(out_path, 'w', encoding='utf-8', newline='') as f:
    w = csv.DictWriter(f, fieldnames=COLS, quoting=csv.QUOTE_MINIMAL)
    w.writeheader()
    for r in audit_rows:
        w.writerow(r)

print(f"\nGeschrieben: {out_path}  ({len(audit_rows)} Zeilen)")

# Print verdict-Histogramm
from collections import Counter
print("\nVerdict-Histogramm:")
for v, c in Counter(r['verdict'] for r in audit_rows).most_common():
    print(f"  {c:3d}x  {v}")
