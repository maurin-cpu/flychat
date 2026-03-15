import json
with open('data/wetterdaten.json', 'r', encoding='utf-8') as f:
    d = json.load(f)
for ts, hr in d['Brunnihütte']['hourly_data'].items():
    if ts.startswith('2026-03-12'):
        print(f"{ts[-8:-3]}: cover={hr.get('cloud_cover')}%")
