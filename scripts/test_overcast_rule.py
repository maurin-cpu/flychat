#!/usr/bin/env python3
"""Test der neuen OVERCAST-Regel gegen die alte, über alle Archiv-Tage/Spots.

ALT  : cloud_base < elev+500  AND  total_cover >= 75              (weather_context.py:1816)
NEU  : cloud_base <= elev+100 AND  cover[band(base)] >= 80        (dichte Decke auf/unter Platz)
       band: low wenn base<3000m sonst mid (3000-8000m)

Clean-Window-Verdict (aloft-blind rekonstruiert):
  clean_h = WIND-OK (Sektor) AND NOT overcast
  safe  <=> es gibt einen zusammenhängenden Block >= CLEAN_WINDOW_MIN_HOURS in clean_h
  (nur die Wolken-/Wind-Ursache; Aloft/Gust/Regen aus Archiv nicht verfügbar)

Validierung: 'alt'-Rekonstruktion vs. gespeicherter analysis.safety_status.
"""
import json, glob, re, ast, sys

FLIGHT_START, FLIGHT_END = 6, 18      # config.FLIGHT_HOURS_*
MIN_HOURS = 2                         # config.CLEAN_WINDOW_MIN_HOURS
TOL = 0.10                            # config.WIND_DIRECTION_TOLERANCE_PCT
NEW_LOW_THRESH = 80                   # dichte Decke
NEW_BASE_BUFFER = 100

# echte COMPASS_POINTS aus engine/_common.py
_src = open('engine/_common.py').read()
_m = re.search(r'COMPASS_POINTS\s*=\s*\{', _src)
_start = _src.index('{', _m.start()); _depth = 0
for _i in range(_start, len(_src)):
    if _src[_i] == '{': _depth += 1
    elif _src[_i] == '}':
        _depth -= 1
        if _depth == 0: _end = _i + 1; break
COMPASS_POINTS = ast.literal_eval(_src[_start:_end])

def parse_range(s):
    out = []
    for dj in (s or '').split('/'):
        dj = dj.strip()
        if not dj: continue
        ang = [COMPASS_POINTS[p.strip()] for p in dj.upper().split('-') if p.strip() in COMPASS_POINTS]
        if len(ang) == 1:
            out.append(((ang[0]-45) % 360, (ang[0]+45) % 360))
        elif len(ang) >= 2:
            for i in range(len(ang)-1):
                a, b = ang[i], ang[i+1]
                out.append((b, a) if (b-a) % 360 > 180 else (a, b))
    return out

def is_in(wdir, sector):
    if not isinstance(wdir, (int, float)): return True
    ranges = parse_range(sector)
    if not ranges: return True
    for s, e in ranges:
        w = (e-s) % 360; w = 360-w if w > 180 else w; buf = w*TOL
        sb = (s-buf) % 360; eb = (e+buf) % 360
        if sb <= eb:
            if sb <= wdir <= eb: return True
        else:
            if wdir >= sb or wdir <= eb: return True
    return False

def overcast_old(base, total, elev):
    return isinstance(base, (int, float)) and isinstance(total, (int, float)) \
        and total >= 75 and base < elev + 500

def overcast_new(base, low, mid, elev, thresh=NEW_LOW_THRESH):
    # Gefahr: dichte Decke AUF oder UNTER Startplatzhöhe.
    #  - "unter mir" (Talstratus, muss zum Landen durch): immer die TIEFE Schicht.
    #  - "Start in Wolke" bei hochalpinem Platz (elev>=3000): zusätzlich die MITTLERE.
    # cloud_base<=elev+Puffer stellt sicher, dass die Decke wirklich bis Platzhöhe reicht.
    if not isinstance(base, (int, float)): return False
    if base > elev + NEW_BASE_BUFFER: return False        # Wolke nur über Platz -> keine Sperre
    dense = (isinstance(low, (int, float)) and low >= thresh)
    if elev >= 3000 and isinstance(mid, (int, float)) and mid >= thresh:
        dense = True
    return dense

def longest_run(hours_set):
    """längster zusammenhängender Stunden-Run (Stunden als ints)."""
    if not hours_set: return 0
    hs = sorted(hours_set); best = run = 1
    for i in range(1, len(hs)):
        run = run+1 if hs[i] == hs[i-1]+1 else 1
        best = max(best, run)
    return best

def verdict(clean_hours):
    return 'safe' if longest_run(clean_hours) >= MIN_HOURS else 'not_safe'

def analyze_spot(spot, thresh=NEW_LOW_THRESH):
    elev = spot.get('elevation_m'); sector = spot.get('windrichtung')
    hf = spot.get('hourly_flight') or {}
    if not isinstance(elev, (int, float)): return None
    clean_old, clean_new = set(), set()
    for t, h in hf.items():
        try: hh = int(t[:2])
        except Exception: continue
        if not (FLIGHT_START <= hh < FLIGHT_END): continue
        wdir = h.get('wind_direction_10m'); base = h.get('cloud_base')
        low = h.get('cloud_cover_low'); mid = h.get('cloud_cover_mid'); tot = h.get('cloud_cover')
        ok = is_in(wdir, sector)
        if ok and not overcast_old(base, tot, elev): clean_old.add(hh)
        if ok and not overcast_new(base, low, mid, elev, thresh): clean_new.add(hh)
    return verdict(clean_old), verdict(clean_new), elev

def run(files, thresh):
    val_match = val_total = n = 0
    to_safe, to_notsafe = [], []
    for f in files:
        day = f.split('/')[-1].replace('.json', '')
        d = json.load(open(f))
        for name, spot in (d.get('spots') or {}).items():
            res = analyze_spot(spot, thresh)
            if not res: continue
            v_old, v_new, elev = res
            n += 1
            stored = (spot.get('analysis') or {}).get('safety_status')
            if stored in ('safe', 'not_safe'):
                val_total += 1
                if stored == v_old: val_match += 1
            if v_old != v_new:
                rec = (day, name, int(elev), v_old, v_new, stored)
                (to_safe if v_new == 'safe' else to_notsafe).append(rec)
    return n, val_match, val_total, to_safe, to_notsafe

def main():
    files = sorted(glob.glob('data/weather_archive/2026-*.json'))
    print('Archiv-Tage:', [f.split('/')[-1] for f in files])

    print('\n--- SCHWELLEN-SENSITIVITÄT (dichte Decke ab x% tiefe Bewölkung) ---')
    print('thr | not_safe->safe | safe->not_safe')
    for thr in (75, 80, 85):
        n, vm, vt, ts, tn = run(files, thr)
        print(' %2d%% |      %3d       |      %3d' % (thr, len(ts), len(tn)))

    THR = 80
    n, vm, vt, to_safe, to_notsafe = run(files, THR)
    print('\nSpot/Tag-Kombinationen analysiert:', n)
    if vt:
        print('VALIDIERUNG (alt-Rekonstruktion vs. gespeicherter Verdict): %d/%d = %.0f%% Übereinstimmung'
              % (vm, vt, 100*vm/vt))
        print('  (Differenz = aloft-/gust-/regen-blinde Rekonstruktion)')
    print('\n=== bei %d%%: KIPPT not_safe -> safe (Fehlalarm "Wolke über Platz" weg): %d ===' % (THR, len(to_safe)))
    for day, name, elev, vo, vn, st in sorted(to_safe)[:30]:
        print('  %s  %-36s %4dm  [gespeichert=%s]' % (day, name[:36], elev, st))
    if len(to_safe) > 30: print('  ... +%d weitere' % (len(to_safe)-30))
    print('\n=== bei %d%%: KIPPT safe -> not_safe (neue "dichte Decke unter Platz"-Sperre): %d ===' % (THR, len(to_notsafe)))
    for day, name, elev, vo, vn, st in sorted(to_notsafe)[:30]:
        print('  %s  %-36s %4dm  [gespeichert=%s]' % (day, name[:36], elev, st))
    if len(to_notsafe) > 30: print('  ... +%d weitere' % (len(to_notsafe)-30))

if __name__ == '__main__':
    main()
