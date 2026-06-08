import json
import os

input_file = r'c:\Users\user\OneDrive\Projekte\wingcast\data\regionen_referenzpunkte.geojson'
output_file = r'c:\Users\user\OneDrive\Projekte\wingcast\data\referenzpunkte_visuell.geojson'

# Lade die Originaldatei
with open(input_file, 'r', encoding='utf-8') as f:
    data = json.load(f)

new_features = []

for feature in data['features']:
    # Behalte das Original für die Region (Polygon)
    new_features.append(feature)
    
    # Erstelle nun für jeden Referenzpunkt ein eigenständiges Punkt-Feature
    if 'properties' in feature and 'reference_points' in feature['properties']:
        points = feature['properties']['reference_points']
        region_name = feature['properties'].get('name', 'Unbekannt')
        region_id = feature['properties'].get('id', 'unbekannt')
        
        for i, point in enumerate(points):
            # WICHTIG: In der Quelldatei scheinen die Punkte [Lat, Lon] zu sein,
            # aber GeoJSON verlangt [Lon, Lat] für die Geometrie.
            lat, lon = point
            
            point_feature = {
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [lon, lat]
                },
                "properties": {
                    "name": f"Ref {i+1}: {region_name}",
                    "region_id": region_id,
                    "is_reference_point": True,
                    "original_lat": lat,
                    "original_lon": lon
                }
            }
            new_features.append(point_feature)

# Erstelle die neue FeatureCollection
new_geojson = {
    "type": "FeatureCollection",
    "features": new_features
}

# Speichere die Datei
with open(output_file, 'w', encoding='utf-8') as f:
    json.dump(new_geojson, f, indent=2, ensure_ascii=False)

print(f"Erfolgreich erstellt: {output_file}")
