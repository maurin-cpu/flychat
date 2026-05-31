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

### 3. `sector_audit.csv` — Abgeleitetes Arbeitsblatt für Sektor-Diskussion

Filtert alle False-Positives aus `observations.csv` und reichert sie mit dem
**DB-Sektor des Spots** (aus `data/weather_archive/`) sowie einer geometrischen
Differenz zur **gemessenen Wind-Richtung** an. Klassifiziert pro Zeile, ob:

- der Sektor zu eng ist (Toleranz erweitern)
- eine zweite Spot-Variante in DB fehlt (anderer Hang)
- der Wind eigentlich im Sektor liegt (FILTER-BUG oder I-007 Block)
- bei schwachem Wind der Sektor-Check irrelevant ist (I-008)

Wird **überschrieben** (nicht appended) per:

```bash
python scripts/generate_sector_audit.py
```

→ nach jedem `observations.csv`-Append neu erzeugen. Schema siehe `SCHEMA.md`.

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

- `YYYY-MM-DD.md` — eine Datei pro analysiertem XContest-Tag (manuell/kuratiert)
- `observations.csv` — strukturierte Daten, append-only
- `sector_audit.csv` — abgeleitet, überschrieben (`scripts/generate_sector_audit.py`)
- `PATTERNS.md` — akkumulierter Issue-Tracker (manuell)
- `_raw/YYYY-MM-DD.tsv` — kompakte Rohdaten pro Tag (`launch⇥km⇥start⇥airtime⇥pilot`), Provenance
- `_raw/_obs_YYYY-MM-DD.csv` — vom Aggregator erzeugte Kandidaten-Zeilen (vor Append in observations.csv)
- `README.md` / `SCHEMA.md` — diese Datei / Spaltendefinitionen

## Halb-automatische Aggregation (ab 27.05.2026)

`scripts/xc_aggregate.py` ersetzt das manuelle Auszaehlen bei Gross-Tagen:
1. XContest-Paste → kompakte TSV in `_raw/YYYY-MM-DD.tsv` (eine Zeile pro Flug).
2. `PYTHONUTF8=1 python scripts/xc_aggregate.py 2026-05-27 ...` aggregiert pro Spot
   (launches, best_km, top_pilot), mappt XContest→PGE (Dict im Script), joint `our_*`/`wx_*`
   aus `weather_archive` und klassifiziert `finding_type`. Output: `_raw/_obs_*.csv` + Konsolen-Digest.
3. Review der `_obs_*.csv`, dann append in `observations.csv`, dann `generate_sector_audit.py`.

> ⚠ **Snapshot-Vollstaendigkeit pruefen (I-015)**: Frueh-Morgen-Snapshots (~06:15) koennen den
> XC-/Experience-LLM-Pass noch nicht enthalten (`streckenflug_rating` 0 oder auf 0/1 gedeckelt).
> `DATE_FLAGS` im Aggregator blankt dann `our_xc_rating`/`our_experience_rating` und unterdrueckt
> `underrated_spot`. **Nur Safety/Status ist an solchen Tagen validierbar.** Pruefe pro neuem Tag
> die xc-Verteilung im Snapshot, bevor du `DATE_FLAGS` setzt.

Tages-MDs + observations.csv-Zeilen + PATTERNS-Updates sind manuell konsistent zu halten.
`sector_audit.csv` ist deterministisch ableitbar — neu erzeugen nach jedem
observations.csv-Append.
