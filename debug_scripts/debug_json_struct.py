import json
with open('data/wetterdaten.json', 'r', encoding='utf-8') as f:
    d = json.load(f)
    print(type(d))
    if isinstance(d, dict):
        print(list(d.keys())[:5])
        if 'Brunnihütte' in d:
             print(type(d['Brunnihütte']))
             if isinstance(d['Brunnihütte'], list):
                 print(len(d['Brunnihütte']))
                 print(d['Brunnihütte'][0]['date'])
             elif isinstance(d['Brunnihütte'], dict):
                 print(list(d['Brunnihütte'].keys())[:5])
