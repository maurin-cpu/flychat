"""Repariert die safety_rating-Falschberechnung im Cache.

Der Bug: Flyability-Post-Process berechnete _compute_safety_rating mit
defaults (5,5,5,5,5) statt den echten Subs → safety_rating=5.0 ueberall.
Subs selbst sind aber im Cache korrekt — also live nachrechnen.
"""
import io
import json
import sys

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from engine._common import _compute_safety_rating, _compute_safety_score

def repair(path):
    data = json.load(open(path, encoding='utf-8'))
    fixed_rating = 0
    fixed_cond = 0
    for k, days in data.items():
        for date, e in days.items():
            if not isinstance(e, dict): continue
            subs = ['wind_safety_rating', 'gust_safety_rating', 'aloft_safety_rating',
                    'foehn_safety_rating', 'rain_safety_rating', 'thunderstorm_safety_rating',
                    'cape_safety_rating', 'visibility_safety_rating']
            # Fix #4: safety_rating aus Subs neu berechnen
            if all(e.get(f) is not None for f in subs):
                old = e.get('safety_rating')
                new_rating = _compute_safety_rating(e)
                new_score = _compute_safety_score(new_rating)
                if old != new_rating:
                    e['safety_rating'] = new_rating
                    e['safety_score'] = new_score
                    fixed_rating += 1

            # Fix #2: is_conditional konsistent zu safety_status
            ss = e.get('safety_status') or e.get('safety', {}).get('safety_status') or ''
            old_flag = bool(e.get('is_conditional', False))
            if ss == 'conditional':
                new_flag = True
            elif ss in ('safe', 'not_safe', 'no_data', 'error'):
                new_flag = False
            else:
                continue  # unknown status, leave alone
            if new_flag != old_flag:
                e['is_conditional'] = new_flag
                fixed_cond += 1
    json.dump(data, open(path, 'w', encoding='utf-8'), ensure_ascii=False, indent=2)
    return fixed_rating, fixed_cond

r1, c1 = repair('data/region_analyses.json')
r2, c2 = repair('data/spot_analyses.json')
print(f"Repariert safety_rating: {r1} Regions + {r2} Spots")
print(f"Repariert is_conditional: {c1} Regions + {c2} Spots")
