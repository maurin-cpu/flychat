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

### 4. Sammel-Analysen und aggregierte Rohdaten (ab 2026-07-26)

Wenn ein Befund **tagesübergreifend** ist, entsteht statt vieler dünner Tages-`.md`
eine Sammel-Analyse: `YYYY-MM-DD_ANALYSE_<thema>.md` (erste: `2026-07-26_ANALYSE_49_TAGE.md`).

Zugehörige Rohdaten-Ablage: `_raw/strong_flights_<von>_<bis>.tsv` mit
`date, launch, km, airtime` — pro Tag und Startplatz **nur der beste
Gleitschirmflug ab 60 km**, HG/RW/Starrflügler bereits ausgefiltert.

> ⚠ Bewusste Verkürzung: Flüge **unter 60 km** und die **Flugzahl pro Startplatz**
> sind für die so erfassten Tage nicht abgelegt. Für Tage im Format des
> Paste-Parsers (`_raw/YYYY-MM-DD.tsv`, alle Flüge) gilt das nicht. Wer die
> Niveau-Prüfung mit einer tieferen Schwelle als 60 km wiederholen will, braucht
> zuerst die vollständigen Tages-TSVs.

Auswertungs-Skripte:
- `scripts/validate_climb_onesided.py` — der **gültige** einseitige Test
  (Perzentil-Rang bewiesen guter Regionen) plus Kontroll-Test mit Wind/Regen.
- `scripts/validate_climb_vs_xcontest.py` — Rang-Korrelation und Niveau-Prüfung
  via Kurbel-Gleit-Inversion. **Achtung**: dessen rohe Rang-Korrelation verletzt
  die 0-Launches-Regel und darf nicht als Befund zitiert werden.
- `scripts/build_observations_from_strong.py` — erzeugt `observations.csv`-Zeilen
  aus der Starkflug-Tabelle + Archiv (`notes` trägt `auto_from_strong_flights`;
  `launches` und `top_start_time` bleiben dort leer).

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

## Bekannte Daten-Lücken

| Tag | Status | Grund |
|---|---|---|
| **2026-06-11** | ⚠ nicht analysiert | Kein `weather_archive/2026-06-11.json`-Snapshot |
| **2026-06-20** | ⚠ nicht analysiert | Snapshot kaputt: `status=error` 487/494 (06:05-Run vor Analyse-Pass) |

**2026-06-20** — Snapshot existiert, ist aber **vor dem Analyse-Pass** gezogen
(`snapshot_at` 06:05): `status=error` bei 487/494 Spots, `experience_rating` und
`streckenflug_rating` komplett gedeckelt. Weder Safety, Exp noch XC validierbar →
`xc_aggregate.py` für 20.06 **nicht** ausgeführt, keine Zeilen in `observations.csv`.
Rohdaten `_raw/2026-06-20.tsv` (15 Flüge) als Provenance erhalten.

> **XC-Feld ab 30.05 abgekündigt (I-015, richtiggestellt):** Das separate `streckenflug_rating`
> wurde ab **30.05.2026** in die Flugeinschätzung integriert → ab dann nur noch 0/1-Stub, das
> **XC-Signal steckt in `experience_rating`**. `xc_aggregate.py` liest XC ab diesem Datum aus
> `experience_rating` (`XC_FROM_EXPERIENCE_SINCE`). XC ist damit ab 30.05 **validierbar** — nur
> Tage mit Stub-Flugeinschätzung (29.05/09.06/10.06/20.06) bleiben XC-blind. Details: PATTERNS I-015.

**11.06.2026** — Rohdaten vorhanden (`_raw/2026-06-11.tsv`, 81 Flüge), aber **kein
Wetter-Snapshot**: `snapshot_weather.py` wurde an dem Tag nicht ausgeführt, und
`wetterdaten.json` (rollend) sowie `spot_analyses.json` wurden seither überschrieben
(nie committet). Ohne Snapshot kann `xc_aggregate.py` die `our_*`/`wx_*`-Spalten
nicht joinen → keine Zeilen in `observations.csv`.

**Rekonstruktion geprüft (2026-06-20): nicht faithful möglich.** Die zwei nötigen
Inputs — der Forecast-Stand und die Modell-Ratings vom Flug-Morgen — existieren
nirgends mehr (kein wetterdaten/spot_analyses-Backup vom 11.06, nicht in Git-History,
`data/history/` leer, kein foehn_cache). `station_observations.db` hat nur 35 Mess-
Zeilen vom 11.06 — Punktmessungen, nicht das 494-Spot-Grid mit Status/Ratings.
ERA5-Reanalyse + Neu-Lauf wäre möglich, ist aber methodisch unsauber: vergleicht
*heutiges* Modell auf *tatsächlichem* Wetter statt den as-issued Forecast vom
11.06-Morgen — kein vergleichbarer Validierungspunkt. **11.06 bleibt Lücke**;
TSV als Provenance erhalten. Lehre: `snapshot_weather.py` täglich sicherstellen.

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

> ⚠ **XC-Quelle & Stub-Tage (I-015)**: Ab **30.05.2026** ist `streckenflug_rating` abgekündigt
> (nur noch 0/1-Stub) — der Aggregator liest XC dann automatisch aus `experience_rating`
> (`XC_FROM_EXPERIENCE_SINCE`). Pro neuem Tag prüfen, ob die **Flugeinschätzung** echt ist
> (`experience_rating` mit Spread 1–5) oder ein Stub (alle 1) — bei Stub `DATE_FLAGS` mit
> `exp_ok:False` setzen, dann ist der Tag XC-/Exp-blind (nur Safety/Status validierbar).
> Solche Stub-Tage: 29.05, 09.06, 10.06, 20.06.

Tages-MDs + observations.csv-Zeilen + PATTERNS-Updates sind manuell konsistent zu halten.
`sector_audit.csv` ist deterministisch ableitbar — neu erzeugen nach jedem
observations.csv-Append.
