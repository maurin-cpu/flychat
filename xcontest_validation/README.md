# XContest Validation — Forecast vs. Realität

## Zweck

Wir sammeln hier laufend Auszüge der XContest-Tageswertung (Top-N Flüge Schweiz) und
gleichen sie mit unseren Region- und Spot-Ratings für denselben Tag ab. Ziel ist, über
Zeit ein Daten-Korpus aufzubauen, mit dem wir systematische Forecast-Fehler
identifizieren und die Kalibrierung optimieren können.

## Wichtige Einschränkung — was XContest sagt und was nicht

- XContest zeigt **nur die guten Flüge** (typischerweise ab ~40 km, je nach Liga).
- **Viele Flüge ab Spot X** = Spot war an dem Tag mit hoher Sicherheit gut fliegbar
  (Lower Bound auf Bedingungen).
- **Wenige oder keine Flüge ab Spot X** ≠ Spot war schlecht. Mögliche Gründe für
  Abwesenheit:
  - Wenige Piloten in der Region
  - Topografie macht 40+ km Strecken unattraktiv
  - Wochentag / Wetter-Vorbericht hat Piloten anderswohin gelockt
  - Spot fehlt in unserer DB (Coverage-Lücke)

→ **Wir leiten aus "0 Launches" keine Aussage über unser Rating ab.**

## Was wir pro Tag dokumentieren

**Zwei parallele Outputs:**

### 1. `YYYY-MM-DD.md` — Narrative Analyse (für Menschen)

1. **Rohdaten-Zusammenfassung**: Top-N Flüge mit Startplatz, Distanz, Airtime, Startzeit
2. **Region-Vergleich**: Tabelle Launches-pro-Region × unser Rating (safety/exp/xc/status)
3. **Spot-Vergleich**: Tabelle Launches-pro-Spot × unser Rating
4. **Findings**, gegliedert in:
   - Confirms (Rating passt zur Realität)
   - Underrated (wir zu vorsichtig — Rating tiefer als Real-Performance)
   - False-Positives (wir not_safe / harte Warnung, aber Spot war fliegbar)
   - Coverage-Gaps (produktive Spots fehlen in unserer DB)
   - Bugs / Anomalien (z.B. `limiting_factor: region_context_missing`)

### 2. `observations.csv` — Strukturierte Datenpunkte (für ML/Stats)

Eine Zeile pro Spot+Tag. Schema und Spaltendefinitionen: siehe `SCHEMA.md`.

Wird bei jeder Analyse **appended** (nicht überschrieben). Pro XContest-Auszug
entstehen ~20-50 Zeilen. Über Zeit wird das die Basis für:

- Bias-Analyse (welche Regionen / Decisions sind systematisch falsch?)
- ML-Postprocessing-Training (XGBoost auf Forecast→Realität-Residuen)
- Saisonale Muster (Frühling overforecast, Föhn unterforecast?)

## Was wir in `PATTERNS.md` akkumulieren

Wiederkehrende Issues über mehrere Tage — pro Issue:
- Welche Spots/Regionen
- Wie oft schon gesehen (Tageszähler)
- Mögliche Ursache (welche Decision/Regel feuert?)
- Status (offen / in Untersuchung / gefixt / nicht reproduzierbar)

So wird die Datei selbst zum Optimierungs-Backlog.

## Methodik im Detail

- **Datenquelle**: Manuelle Eingabe via Chat (User postet XContest-Top-100-Auszug,
  ggf. historisch — daher Snapshot-Pflicht der Wetterdaten, siehe unten)
- **Region-Mapping**: Spotname → Region via `data/fluggebiete_complete.csv`
  (Spalte `analyse_region`); für nicht-gelistete Spots manuelles Mapping basierend
  auf Geografie
- **Spot-Mapping**: Lookup in `data/weather_archive/YYYY-MM-DD.json` → `spots[...]`;
  bei Nicht-Treffer fuzzy-match (Prefix) und Variante-Namen prüfen
- **Rating-Quelle**: `data/weather_archive/YYYY-MM-DD.json` → `spots[spot].analysis`
  und `regions[region]` (eingefrorener Forecast-Stand des jeweiligen Tags)
- **Wetter-Quelle**: gleiches Archiv → `spots[spot].daily_aggregates` (Tagessummen)
  und `spots[spot].hourly_flight` (08-20 stündlich, inkl. Thermik)

## Wetterdaten-Snapshot — Warum und Wie

`data/wetterdaten.json` ist eine **rollende Forecast-Datei**, die bei jeder
Aktualisierung überschrieben wird. Ohne Snapshot wäre der Forecast für Tag X
verloren, sobald X+1 läuft.

**Lösung**: `scripts/snapshot_weather.py` friert pro Forecast-Tag eine
kompakte JSON-Datei ein (`data/weather_archive/YYYY-MM-DD.json`, ~11 MB),
inklusive:

- Tages-Aggregate (Wind, Wolken, Niederschlag, climb_rate Peak, max_height, BLH, CAPE, LI, …)
- Stündliche Werte 08-20 inkl. Thermik (climb_rate, max_height, rating)
- Rating-Snapshot pro Spot (safety, status, streckenflug, decisions_applied, no_go_reasons)
- Region-Rating-Snapshot

**Manuell triggern:**

```bash
python scripts/snapshot_weather.py                # alle verfügbaren Tage
python scripts/snapshot_weather.py 2026-05-18     # ein spezifischer Tag
python scripts/snapshot_weather.py --overwrite    # bestehende Snapshots ersetzen
```

**Wann triggern?** Möglichst zeitnah zum Forecast-Run (z.B. nach jedem Update
von `wetterdaten.json` morgens), damit der eingefrorene Stand möglichst nah am
"Pilot-Morgen-Forecast" liegt. Historische XContest-Daten können später
problemlos analysiert werden, solange für den entsprechenden Tag ein
Snapshot existiert.

## Sample-Größe Roadmap

- ≥10 Tage: erste belastbare Muster sichtbar
- ≥30 Tage: regionale Verteilung statistisch tragfähig
- ≥3 Monate: Saisonale Muster, Kalibrierungs-Empfehlungen pro Terrain-Tier möglich

## File-Convention

- `YYYY-MM-DD.md` — eine Datei pro analysiertem XContest-Tag
- `PATTERNS.md` — akkumulierter Issue-Tracker, wird bei jeder Analyse aktualisiert
- `README.md` — diese Datei

Keine Auto-Generierung, kein Skript. Manuell, aber konsistent dokumentiert.
