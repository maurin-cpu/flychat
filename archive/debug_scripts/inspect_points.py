import json

def inspect_points_16_03():
    with open('data/wetterdaten.json', 'r', encoding='utf-8') as f:
        data = json.load(f)
    
    balderen = data['Balderen']
    ref_points = balderen.get('reference_points', [])
    
    print(f"--- Regional Cloud Distribution for Balderen (16.03. 10:00 vs 11:00) ---")
    
    # Actually, the reference points are just coordinates. 
    # To see the raw data for EACH point, I'd need to have them saved or re-fetch them.
    # But I can look at the sorted logic in fetch_weather.py if I were to re-run it with debug.
    
    # Wait, the current wetterdaten.json only has the AGGREGATED result for Balderen.
    # To really see the 5 points, I'd need to look at the logs or re-fetch.
    
    # Let's check the logs of the last fetch.
    pass

if __name__ == "__main__":
    inspect_points_16_03()
