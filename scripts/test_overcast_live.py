#!/usr/bin/env python3
"""Welche Spots ändert die neue OVERCAST-Regel auf den AKTUELLEN Daten?

Quellen:
  data/wetterdaten.json   - stündliche Wolkendaten (live, 5 Tage)
  spots.load_spots()      - windrichtung + elevation_m
  data/spot_analyses.json - gespeicherter (alter) Verdict zum Abgleich

ALT : cloud_base < elev+500  AND total_cover >= 75
NEU : cloud_base <= elev+100 AND (low>=80 OR (elev>=3000 AND mid>=80))

Clean-Window (aloft-blind): clean = WIND-OK(Sektor) AND NOT overcast;
safe <=> zusammenhängender Block >= 2h. Flip = Verdict alt != neu.
ACHTUNG: höhenwind-/böen-/regen-blind -> Liste = Kandidaten, nicht exakt.
"""
import json, re, ast
import config, spots

BUF, COVER, MIDBAND = (config.OVERCAST_DANGER_BASE_BUFFER_M,
                       config.OVERCAST_DANGER_COVER_PCT,
                       config.OVERCAST_MID_BAND_MIN_M)
FLIGHT_START, FLIGHT_END, MIN_HOURS, TOL = 6, 18, 2, 0.10

_src = open('engine/_common.py').read()
_m = re.search(r'COMPASS_POINTS\s*=\s*\{', _src); _s = _src.index('{', _m.start()); _d = 0
for _i in range(_s, len(_src)):
    if _src[_i] == '{': _d += 1
    elif _src[_i] == '}':
        _d -= 1
        if _d == 0: _e = _i+1; break
COMPASS_POINTS = ast.literal_eval(_src[_s:_e])

def parse_range(s):
    out = []
    for dj in (s or '').split('/'):
        ang = [COMPASS_POINTS[p.strip()] for p in dj.upper().split('-') if p.strip() in COMPASS_POINTS]
        if len(ang) == 1: out.append(((ang[0]-45) % 360, (ang[0]+45) % 360))
        elif len(ang) >= 2:
            for i in range(len(ang)-1):
                a, b = ang[i], ang[i+1]; out.append((b, a) if (b-a) % 360 > 180 else (a, b))
    return out

def is_in(wdir, sector):
    if not isinstance(wdir, (int, float)): return True
    r = parse_range(sector)
    if not r: return True
    for s, e in r:
        w = (e-s) % 360; w = 360-w if w > 180 else w; buf = w*TOL
        sb = (s-buf) % 360; eb = (e+buf) % 360
        if (sb <= eb and sb <= wdir <= eb) or (sb > eb and (wdir >= sb or wdir <= eb)): return True
    return False

def ovc_old(base, tot, elev):
    return isinstance(base, (int, float)) and isinstance(tot, (int, float)) and tot >= 75 and base < elev+500

def ovc_new(base, low, mid, elev):
    if not isinstance(base, (int, float)) or base > elev+BUF: return False
    return (isinstance(low, (int, float)) and low >= COVER) or \
           (elev >= MIDBAND and isinstance(mid, (int, float)) and mid >= COVER)

def longest(hs):
    if not hs: return 0
    hs = sorted(hs); best = run = 1
    for i in range(1, len(hs)):
        run = run+1 if hs[i] == hs[i-1]+1 else 1; best = max(best, run)
    return best

def verdict(c): return 'safe' if longest(c) >= MIN_HOURS else 'not_safe'

print('lade Spot-Stammdaten + wetterdaten.json ...')
spot_meta = {s['name']: s for s in spots.load_spots()}
wx = json.load(open('data/wetterdaten.json'))
try: stored = json.load(open('data/spot_analyses.json'))
except Exception: stored = {}

dates = sorted({ts[:10] for s in wx if s not in ('_meta', '_regions')
                for ts in (wx[s].get('hourly_data') or {})})
print('Forecast-Tage:', dates)

flips_safe, flips_notsafe = [], []
n = 0
for name, sdata in wx.items():
    if name in ('_meta', '_regions'): continue
    meta = spot_meta.get(name)
    if not meta: continue
    elev = meta.get('elevation_m'); sector = meta.get('windrichtung')
    if not isinstance(elev, (int, float)): continue
    hd = sdata.get('hourly_data') or {}
    for day in dates:
        co, cn = set(), set()
        for ts, h in hd.items():
            if not ts.startswith(day): continue
            try: hh = int(ts[11:13])
            except Exception: continue
            if not (FLIGHT_START <= hh < FLIGHT_END): continue
            wdir = h.get('wind_direction_10m'); base = h.get('cloud_base')
            low = h.get('cloud_cover_low'); mid = h.get('cloud_cover_mid'); tot = h.get('cloud_cover')
            ok = is_in(wdir, sector)
            if ok and not ovc_old(base, tot, elev): co.add(hh)
            if ok and not ovc_new(base, low, mid, elev): cn.add(hh)
        vo, vn = verdict(co), verdict(cn)
        n += 1
        if vo != vn:
            st = (stored.get(name, {}).get(day, {}).get('safety', {}) or {}).get('safety_status')
            rec = (day, name, int(elev), st)
            (flips_safe if vn == 'safe' else flips_notsafe).append(rec)

print('\nSpot/Tag analysiert:', n)
print('\n=== KANDIDATEN not_safe -> safe (Fehlalarm "Wolke über Platz" weg): %d ===' % len(flips_safe))
for day, name, elev, st in sorted(flips_safe):
    print('  %s  %-40s %4dm  [Cache=%s]' % (day, name[:40], elev, st))
print('\n=== KANDIDATEN safe -> not_safe (neue "dichte Decke unter Platz"-Sperre): %d ===' % len(flips_notsafe))
for day, name, elev, st in sorted(flips_notsafe):
    print('  %s  %-40s %4dm  [Cache=%s]' % (day, name[:40], elev, st))

# ─── Verfeinerung: Kandidaten nach gespeichertem not_safe-Grund klassifizieren ───
print('\n\n=== VERFEINERUNG der not_safe->safe-Kandidaten (warum war Cache not_safe?) ===')
from collections import Counter
cls = Counter(); examples = {}
for day, name, elev, st in flips_safe:
    saf = (stored.get(name, {}).get(day, {}).get('safety', {}) or {})
    pno = saf.get('primary_no_go')
    reasons = saf.get('no_go_reasons') or []
    rtext = ' | '.join(reasons)
    if st != 'not_safe':
        key = 'Cache nicht not_safe (%s)' % st
    elif pno:
        key = 'primary_no_go=%s -> bleibt not_safe' % pno
    elif re.search(r'Start-Fenster|sauber|Block', rtext):
        key = 'Clean-Window (Wolken/Wind) -> ECHTER Flip wahrscheinlich'
    elif reasons:
        key = 'anderer Grund: %s' % (reasons[0][:45])
    else:
        key = 'kein no_go_reason gespeichert'
    cls[key] += 1
    examples.setdefault(key, []).append('%s %s' % (day, name[:30]))
for k, c in cls.most_common():
    print('  %3d  %s' % (c, k))
    for ex in examples[k][:3]:
        print('         z.B. %s' % ex)

# ─── Bessere Schätzung: Höhenwind-Stop im Cache-Tag = Flip unwahrscheinlich ───
print('\n=== ECHTE-FLIP-SCHÄTZUNG via Cache-Tags (WIND_ALOFT stop versteckt sich im Clean-Window) ===')
likely, blocked_aloft, other = [], [], []
for day, name, elev, st in flips_safe:
    rec = stored.get(name, {}).get(day, {}) or {}
    tags = rec.get('tags') or []
    aloft_stop = any(t.get('topic') == 'WIND_ALOFT' and t.get('severity') == 'stop' for t in tags)
    wind_stop = any(t.get('topic') in ('WIND_GROUND',) and t.get('severity') == 'stop' for t in tags)
    if st != 'not_safe':
        other.append((day, name))
    elif aloft_stop or wind_stop:
        blocked_aloft.append((day, name, elev))
    else:
        likely.append((day, name, elev))
print('  %3d  bleiben vermutlich not_safe (Cache hat WIND_ALOFT/WIND stop-Tag)' % len(blocked_aloft))
print('  %3d  ECHTER Flip wahrscheinlich (kein Höhenwind-/Wind-Stop im Cache)' % len(likely))
print('  %3d  Cache nicht not_safe' % len(other))
print('\n--- die wahrscheinlich ECHTEN Flips (kein Höhenwind-Stop), pro Tag ---')
from collections import Counter
pc = Counter(d for d, n, e in likely)
print('  pro Tag:', dict(sorted(pc.items())))
for day, name, elev in sorted(likely)[:60]:
    print('  %s  %-40s %4dm' % (day, name[:40], elev))

# ─── Regen-Check: RAIN-WARN ist auch ein hard_warning (mein Filter ignoriert es) ───
print('\n=== REGEN-bereinigte Schätzung (RAIN-WARN sperrt clean_hours ebenfalls) ===')
def rain_hours(name, day):
    hd = (wx.get(name) or {}).get('hourly_data') or {}
    c = 0
    for ts, h in hd.items():
        if not ts.startswith(day): continue
        try: hh = int(ts[11:13])
        except Exception: continue
        if not (FLIGHT_START <= hh < FLIGHT_END): continue
        p = h.get('precipitation')
        if isinstance(p, (int, float)) and p > 0: c += 1
    return c
likely_set = {(d, n) for d, n, e in likely}
dry, wet = [], []
for day, name, elev in likely:
    (wet if rain_hours(name, day) >= 3 else dry).append((day, name, elev))
print('  %3d  bleiben vermutlich not_safe (>=3h Regen in Flugstunden)' % len(wet))
print('  %3d  ECHTER Flip wahrscheinlich (trocken + kein Höhenwind-Stop)' % len(dry))
from collections import Counter
print('  trockene echte Flips pro Tag:', dict(sorted(Counter(d for d, n, e in dry).items())))
import io
with open('data/overcast_flip_candidates.txt', 'w') as f:
    f.write('# wahrscheinliche not_safe->safe Flips (trocken, kein Hoehenwind-Stop)\n')
    for day, name, elev in sorted(dry):
        f.write('%s  %-42s %5dm\n' % (day, name, elev))
print('  -> volle Liste: data/overcast_flip_candidates.txt')
