# Stationsdaten-basierte Bias-Korrektur

## Übersicht

NWP-Modelle (ICON-D2, CH1, CH2) haben im alpinen Gelände systematische Böen-Fehler von ±10–15 km/h. Die Bias-Korrektur lernt aus dem Vergleich zwischen Forecast und echter Messung und korrigiert zukünftige Forecasts automatisch.

**Prinzip:** Wenn das Modell am Niesen konstant 7 km/h zu wenig Böen vorhersagt, werden zukünftige Forecasts um 7 km/h angehoben.

---

## Datenquelle: winds.mobi

- **API:** `https://winds.mobi/api/2.3/`
- **Stationen:** ~500 in der Schweiz (MeteoSwiss, SLF, Holfuy, Pioupiou)
- **Kein API-Key nötig**, kostenlos
- **Liefert:** Windrichtung, Mittelwind, Böen (max), Temperatur
- **Nur Echtzeit** + begrenzte Historie (kein Forecast)
- Dieselbe Datenquelle wie Burnair

---

## Station-Discovery

Bei der Erstinitialisierung (oder manuell via `/api/stations/discover`) werden für jeden Spot die nächsten Stationen gesucht.

**Kriterien:**
- Maximale Distanz: 30 km (`STATION_SEARCH_RADIUS_KM`)
- Maximale Höhendifferenz: 300 m (`STATION_MAX_ELEV_DIFF_M`)
- Bis zu 3 Stationen pro Spot (`STATION_MAX_PER_SPOT`)
- Sortierung: nächste zuerst

**Ergebnis:** Tabelle `spot_station_map` mit Zuordnung Spot → Station(en).

---

## Observation-Collection

Bei jedem `refresh_weather()` werden die aktuellen Messwerte aller gemappten Stationen geholt:

1. Alle Station-IDs aus `spot_station_map` laden
2. Pro Station: `GET /stations/{id}/` → aktuelle Messwerte
3. Messwerte (wind_avg, wind_max, wind_direction, temperature) in `observations` Tabelle speichern
4. Auf volle Stunde gerundet (für Matching mit Forecast-Stunden)

**Einheiten-Konversion:** winds.mobi liefert m/s → wird in km/h umgerechnet.

---

## Backfill bei Lücken

Wenn die DB neu ist oder lange offline war:

1. **Observation-Backfill:** winds.mobi Historic-Daten für die letzten 14 Tage holen
2. **Forecast-Backfill:** Open-Meteo `past_days=14` für ICON-D2 → historische Modellwerte
3. **Paare erstellen:** Stundengenaues Matching → `forecast_pairs` füllen

So steht der Bias ab dem ersten Refresh zur Verfügung.

---

## Forecast-Observation Pairing

Pro Refresh werden neue Paare erstellt:

```
Für jeden Spot:
  Für jede gemappte Station:
    forecast_gust = weather_data[spot][aktueller_zeitstempel].wind_gusts_10m
    observed_gust = observations[station][aktueller_zeitstempel].wind_max
    → Paar in forecast_pairs speichern
```

Ein Paar enthält:
- `spot_name`, `timestamp`, `station_id`
- `forecast_gust` — Was das Modell vorhergesagt hat (km/h)
- `observed_gust` — Höhenkorrigierte Station-Böe (km/h): `forecast + excess × decay`
- `model` — Welches Modell (default: `icon_d2`)

---

## Bias-Berechnung

Der Bias wird **live** aus den Paaren berechnet (nicht gecacht):

```python
error = observed_gust - forecast_gust  # positiv = Modell unterschätzt

bias = Σ(weight_i × error_i) / Σ(weight_i)
weight_i = alpha^(n - 1 - i)           # Jüngere Paare stärker gewichtet
```

**Parameter:**
- `alpha = 0.85` — Exponentieller Gewichtungsfaktor
- `lookback_days = 14` — Nur Paare der letzten 14 Tage
- `min_pairs = 5` — Mindestanzahl bevor Bias angewendet wird

**Beispiel:** 10 Paare, Fehler [+8, +5, +10, +7, +6, +8, +9, +7, +8, +6]
→ Bias ≈ +7.5 km/h (Modell unterschätzt Böen am Niesen im Schnitt um 7.5 km/h)

---

## Höhenkorrektur (Expositions-Anpassung)

Stationen auf exponierten Berggipfeln messen systematisch stärkere Böen als am (tieferen/geschützteren) Startplatz erwartet. Ohne Korrektur würde der Bias verfälscht.

### Das Problem (vor April 2026)

Die alte Formel verwendete den **Stations-Grundwind** als Basis:

```
adjusted = station_avg + excess × exp(-dz / H_g)     ← ALT, FALSCH
```

**Warum falsch?** Der Grundwind auf einem Gipfel ist durch terrain-spezifischen Speed-Up
(Bernoulli-Effekt, Strömungsbeschleunigung über Kuppen) systematisch viel höher als am
Hang/Tal. Beispiel Uetliberg (1016m) → Balderen (730m):
- Station misst: Grundwind 69 km/h, Böe 79 km/h → Exzess 10 km/h
- Alte Korrektur: 69 + 10 × 0.49 = **73.9 km/h** → Bias +56 km/h (gecappt auf +15)
- Modell sagt: 18 km/h (stimmt mit Burnair überein)
- **Ergebnis:** Böen im Meteogramm um 15 km/h zu hoch

**Betroffene Spots** (Bias >+10 km/h, alle durch Gipfel-/Gratstationen verursacht):
| Spot | Bias (alt) | Hauptverursacher | Elev-Diff |
|---|---|---|---|
| Forstberg | +25.1 → cap +15 | Alpler Tor, Wasserbergfirst | +163m, +150m |
| Rüti | +24.4 → cap +15 | Schwengimatt DC-Falk | +282m |
| Weissenstein | +23.1 → cap +15 | Flugschule Jura Thal | +203m |
| Balderen | +16.9 → cap +15 | Uetliberg | +286m |
| Rotmoos | +16.5 → cap +15 | Sattel, SZ | +245m |
| First | +13.2 | Männlichen | +221m |

**Betroffene Regionen** (über Spot-Anker im Altitude-Grid):
- Mittelland Ost, Jura Zentral, Berner Alpen, Zentrale Voralpen, Zentralschweizer Alpen

### Die Lösung (ab April 2026)

Statt den Gipfel-Grundwind als Basis zu verwenden, wird der **Modell-Forecast** als
Basis genommen. Nur der **Turbulenz-Exzess** (Böe minus Grundwind an der Station) wird
höhenkorrigiert auf den Forecast aufgeschlagen.

```
excess = max(0, station_gust - station_avg)
adjusted = forecast_gust + excess × exp(-dz / H_g)   ← NEU, KORREKT
```

**Wissenschaftliche Grundlage:** Brasseur 2001 (Royal Met. Institute Belgium) empfiehlt
genau diesen Ansatz: Modellwert als Referenz, Stationsdaten nur für die Exzess-Korrektur.
DWD MOSMIX und NOAA MOS verwenden dieselbe Philosophie — Stationsdaten korrigieren den
Modell-Fehler, nicht den Modell-Wert.

Wobei:
- `dz = station_alt - spot_alt` (nur wenn Station höher als Spot, sonst keine Korrektur)
- `H_g = 400m` (Skalenhöhe für exponentiellen Exzess-Zerfall, `BIAS_ELEV_DECAY_HG`)
- `forecast_gust` = Modell-Böenvorhersage am Spot für dieselbe Stunde
- `station_avg` = gemessener Mittelwind an der Station (aus `observations.wind_avg`)

**Beispiel Balderen** (Uetliberg-Station 1016m, Spot 730m, Modell 18 km/h):
- Station misst: 79 km/h Böe, 69 km/h Grundwind → Exzess = 10 km/h
- `dz = 286m`, `decay = exp(-286/400) = 0.49`
- `adjusted = 18 + 10 × 0.49 = 22.9 km/h` (statt 73.9 → realistisch)
- Bias = 22.9 - 18 = **+4.9 km/h** (statt +56 → vernünftig)

**Beispiel First** (Männlichen-Station 2341m, Spot 2120m, Modell 25 km/h):
- `excess = max(0, gust - avg)`, `dz = 221m`, `decay = exp(-221/400) = 0.58`
- Nur der Turbulenz-Exzess wird gedämpft und auf den Modellwert aufgeschlagen

**Keine Änderung** für Stationen auf gleicher oder niedrigerer Höhe als der Spot:
dort wird die Station-Böe direkt verwendet (konservativ).

---

## Korrektur-Anwendung

Die Korrektur wird in `apply_bias_correction()` angewendet, **vor** dem Gauss-Kernel:

```
wind_gusts_10m_korrigiert = wind_gusts_10m + capped_bias
```

**Sicherheitslimits:**
- Bias wird auf **±15 km/h** begrenzt (`BIAS_MAX_CORRECTION`)
- Korrekturen unter ±0.5 km/h werden ignoriert (Rauschen)

Der korrigierte Wert fliesst dann in die Höhenböen-Berechnung:

```
Modell-Forecast → Multi-Modell-Merge (max) → Bias-Korrektur (±15 cap) → Gauss-Kernel → Höhenprofil
```

Das Original bleibt als `wind_gusts_10m_raw` erhalten.

---

## Region-Bias-Korrektur

Spots haben einen direkten Bias aus eigenen `forecast_pairs`. Regionen haben keine eigenen Stationen — ihr Bias wird **abgeleitet aus den Spots, die im Regions-Polygon liegen**.

**Verfahren** (`apply_bias_correction_to_regions()` in `station_observations.py`):

1. Für jede Region mit Polygon iterieren.
2. Alle Spots durchgehen und per Point-in-Polygon-Test (shapely) prüfen, ob der Spot **geografisch innerhalb** des Polygons liegt.
3. **Höhenfilter** anwenden: Nur Spots mit `|spot.elevation_m − region.elevation_ref| ≤ 600 m` zählen.
4. Aus den verbleibenden Spot-Biases den **Median** bilden (robust gegen Ausreisser).
5. Mindestens 2 Spots nach Filter sind nötig, sonst keine Korrektur.
6. Median wird gleich behandelt wie ein Spot-Bias: Cap ±15 km/h, Threshold |bias| ≥ 0.5 km/h.
7. Auf alle stündlichen `wind_gusts_10m` der Region angewandt; Originalwert bleibt als `wind_gusts_10m_raw`.

**Warum der Höhenfilter ±600 m?**
Bias-Werte sind ortsspezifisch. Ein Pilatus-Bias auf 2059 m beschreibt die Modellabweichung an einem exponierten Bergspitzen-Pixel und sagt nichts darüber aus, wie ICON-D2 sich auf 1400 m im selben Polygon verhält. Ohne Filter würde z.B. die Region "Zentrale Voralpen" (`elev_ref` 1400 m, voralpenähnliche Klassifizierung) durch positive Berggipfel-Biases nach oben verzerrt — genau das Gegenteil dessen, was wir wollen. Mit dem ±600 m Filter bleiben nur Spots, deren Modell­auflösungs­situation der Region ähnelt.

**Aufruf-Reihenfolge** in `chat_engine.refresh_weather()`:

```
1. self.station_manager.apply_bias_correction(self.weather_data)         # Spots
2. regions_with_polygons = source_area._load_regions()
3. self.station_manager.apply_bias_correction_to_regions(                # Regionen
       self.region_weather_data, regions_with_polygons
   )
```

**Vollständige Pipeline für Regionen:**

```
4 Referenzpunkte                                            (GeoJSON)
   ↓ Open-Meteo Batch-Fetch pro RP
4× Wind/Gust/Direction
   ↓ _aggregate_wind_across_points()  ← Median über RPs
1× Regions-Bodenwind/-böe
   ↓ apply_bias_correction_to_regions()  ← Median Spot-Biases im Polygon
1× korrigierte Regions-Bodenböe
   ↓ OI-Gauss-Kernel
Höhenprofil 0–4000 m
   ↓ Running Maximum
finales Profil
```

**Logging:**
- `[STATIONS] Region-Bias {rid}: ±X km/h (n=Y Spots im Polygon)` — bei jeder angewandten Korrektur
- `Region-Bias {rid}: uebersprungen (nur N Spots im Hoehenfilter, K durch Hoehe ausgeschlossen)` — wenn Filter zu wenig Spots übrig lässt

---

## SQLite Schema

```sql
-- Alle bekannten Stationen
stations (id, name, latitude, longitude, altitude, provider, last_seen)

-- Welche Stationen gehören zu welchem Spot
spot_station_map (spot_name, station_id, distance_km, elevation_diff_m)

-- Gemessene Werte (Wind, Böen, Richtung, Temperatur)
observations (station_id, timestamp, wind_avg, wind_max, wind_direction, temperature)

-- Forecast vs. Beobachtung Paare
forecast_pairs (spot_name, timestamp, station_id, forecast_gust, observed_gust, model)
```

**Dateipfad:**
- Lokal: `data/station_observations.db`
- Vercel: `/tmp/wingcast/station_observations.db`

---

## Fehlerbehandlung

| Situation | Verhalten |
|-----------|-----------|
| winds.mobi nicht erreichbar | Warnung loggen, Forecast unkorrigiert |
| Station meldet keine Daten | Kein Pairing für diesen Spot |
| Zu wenig Paare (<5) | Kein Bias anwenden, raw Forecast bleibt |
| SQLite-Fehler | Loggen, System läuft weiter ohne Bias |
| Kein Internet beim Startup | SQLite-Daten reichen, kein Backfill |

---

## API-Endpoints

| Endpoint | Methode | Funktion |
|----------|---------|----------|
| `/api/stations/status` | GET | Übersicht: Stationen, Paare, Bias pro Spot |
| `/api/stations/discover` | POST | Stationen neu suchen |
| `/api/stations/collect` | POST | Beobachtungen manuell holen |

---

## Dateien-Übersicht

| Datei | Funktion |
|-------|----------|
| `station_observations.py` | `StationManager`: Discovery, Collection, Backfill, Pairing, Bias (Spots **und** Regionen) |
| `config.py` | Settings: API-URL, Suchradius, Bias-Parameter, DB-Pfad |
| `chat_engine.py` | Integration: Init, collect/pair/correct in `refresh_weather()` (ruft auch `apply_bias_correction_to_regions()`) |
| `source_area.py` | Lädt Regions-Polygone für Point-in-Polygon-Test (`_load_regions()`) |
| `web.py` | API-Endpoints für Status/Discovery/Collection |
| `data/station_observations.db` | SQLite-Datenbank (persistiert über Neustarts) |
