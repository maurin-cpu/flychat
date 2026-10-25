# Wetterlage-Block (Synoptik)

Status: v2.0 „Flugwetter-Zonen" (Juli 2026), Basis v1.0 (Mai 2026).
**Seit 25.10.2026 ohne KI-Text:** Der LLM-Pfad (Lead, Gefahren-Sätze,
Tagessätze, Validator mit Korrekturrunden) ist entfernt. Das Briefing baut
alle Texte aus festen Bausteinen und zeigt die Warnungen nur als Labels
(`docs/BRIEFING.md` §5).
Aufruf: 1×/Tag vom Scheduler im Daily-Cycle, kurz vor Versand des Casts.
Ziel: Kompakte Einordnung der Grosswetterlage in Pilotensprache —
zuoberst im Wingcast und in der E-Mail.

## v2.0 — was sich geaendert hat

Der Block beantwortet zwei Fragen, alles andere ist raus:
1. **Tagesachse** — wie wandert das Wetter ueber den Tag durch die Schweiz?
2. **Wochenachse** — wie stellt sich die Lage ueber die Tage um?

| | v1.0 | v2.0 |
|---|---|---|
| Raum | 2 Toepfe (Alpennord/-sued), Lat/Lon-Heuristik | **4 Flugwetter-Zonen**, Region ist atomar |
| Zeit | Tagespauschale (Tagessumme/-maximum) | **4 Tagesfenster** (6-10/10-14/14-18/18-21) |
| Peak | `peak_mm` = Maximum ueber alle Spots | **`p90_mm`** traegt das Bild, `max_mm` separat |
| Verlagerung | — | **Zugbahn-Detektor** aus Einsetz-Zeiten |
| Text | lead + flache Tagesliste | lead (Druckzentren→Stroemung als Kette) + 4 Zonen-Bloecke |
| Lob-Gate | nur wenn BEIDE Alpenseiten windkritisch | **pro Zone** |

**Ausloeser (25.07.2026):** Der Block sagte *„widespread rain … plan a rest
day"* fuer einen Tag, der bis 15:00 landesweit trocken war (Anteil nasser
Spots pro Stunde: 0.00 bis 14:00, Maximum 0.24 um 19:00). Ursache:
`wet_share` zaehlte Tagessummen, `peak_mm=35.6` war ein einzelner
Hochalpen-Spot. Zusaetzlich lag im damaligen Topf „Alpensued" das Wallis
mit 63 von 97 Spots — Aussagen ueber „den Sueden" beschrieben faktisch
ueberwiegend das Wallis.

### Die 4 Zonen

| Zone-ID | Label | Charakter |
|---|---|---|
| `alpennordhang` | Alpennordhang | Stau-Land bei NW-Anstroemung, inkl. Voralpen/Mittelland/Jura |
| `wallis` | Wallis | von Westen abgeschirmt, Lee bei NW-Stau |
| `tessin` | Tessin | Alpensuedseite, Lee (boeig) bei Nordfoehn |
| `graubuenden_engadin` | Graubuenden & Engadin | inneralpin, eigene Talwindsysteme |

**Zuordnung:** Spalte `zone` in `data/regionen.csv` (29 Regionen). Spots
erben die Zone ueber ihr `analyse_region`-Feld
(`fluggebiete_dhv.csv`) — Kette **Spot → Region → Zone → CH**.
**Eine Region wird NIE aufgeteilt**: damit ist die Synoptik spaeter sauber
auf Regionen-Analysen herunterbrechbar. Neue Region = ein CSV-Eintrag,
kein Code-Change (`build_spot_zone_map`).

Die Zone ist die kleinste **Erzaehl**-Einheit — keine Fluggebiete, keine
Spot-Namen im Text. Ausnahme: der Zugbahn-Detektor teilt den Alpennordhang
intern in West/Ost (Laenge 8.0°) — reine Messung, kein Textbaustein.

**Recherche-Grundlage:**
- `meteo_research/synoptic_pilot_needs.md` — was Schweizer Piloten aus der
  Synoptik wirklich brauchen, welche Begriffe verstanden werden, welche
  Fallstricke vermieden werden muessen.
- `meteo_research/wetterlagen_pilotenwissen.md` — vertieftes Hintergrundwissen
  zu Hoch/Tief/Foehn/Bise/Alpenkamm/regionalen Spezialitaeten. Wird via
  `prompts.WETTERLAGEN_PILOTENWISSEN` an den LLM gehaengt fuer fundierte
  Interpretation. WICHTIG: Wissensbasis dient nur der Interpretation
  detektierter Lagen, nicht zum Erfinden — Stage-Inversion-Prinzip bleibt.

## Kernprinzip — Halluzinations-Schutz

Jede Aussage muss bis zur Rohzahl rückverfolgbar sein. Architektur folgt dem
**Stage-Inversion-Pattern** aus `engine/decision_engine.py`:

1. Deterministische Klassifikatoren (`decide_*`) entscheiden alle
   Strukturfelder aus Wetterdaten und Druckraster.
2. Die Texte im Briefing entstehen aus festen Textbausteinen
   (`scripts/briefing_v3_context.py`), kein Modell formuliert frei.
3. Bei Fehler in der Pipeline: Block wird **weggelassen**, kein Fallback-Text.

## Datenfluss

```
wetterdaten.json
    ↓
aggregate_ch_daily_snapshot()           ← CH-Mittel über ~495 Spots (12:00 lokal)
    ↓ snapshots [{date, msl_hpa, t850_c, gh850_m, wind_700}]
    │
    ├─ decide_pressure_influence()      ← Hoch/Tief/Übergang + Linear-Trend
    ├─ decide_flow_overhead()           ← 700hPa Vektor-Mittel + Drehungs-Erkennung
    ├─ decide_t850_trend()              ← Sprung-Detektion (≥4 K) + Gesamttrend
    └─ decide_schneefallgrenze()        ← saisonal (Mär–Mai + Okt–Nov)

fetch_europe_pressure_grid()            ← Mini-API-Call ECMWF-IFS, 15 Europa-Punkte
    ↓ grid [{lat, lon, label, msl_by_day}]
    │
    ├─ find_pressure_centers()          ← lokale Min/Max mit ≥5 hPa Gradient
    ├─ decide_bise()                    ← ΔP NE↔S + 700hPa-Wind NE-Sektor
    └─ decide_vb_lage()                 ← Tief in Norditalien-Box

fetch_foehn_data() (foehn_indicators.py)
    ↓
decide_foehn_summary()                  ← Pro Tag: ≥1h caution+ im Flugfenster → aktiv (wie Regionen)

weather_cache (alle Spots)
    ↓ Lat/Lon-Klassifikation
decide_precip_pattern_nord_sued()       ← getrennt Alpennord vs. Alpensüd
decide_wind_pattern_nord_sued()         ← (beide v1.0: bleiben im Audit-JSON,
                                           gehen NICHT mehr an den LLM)

weather_cache + build_spot_zone_map()   ← Spot → analyse_region → zone
    ↓
decide_precip_pattern_zones()           ← 4 Zonen × Tag × 4 Tagesfenster
decide_wind_pattern_zones()             ← wind_class/Anteile + Fenster-Verlauf
decide_zugbahn()                        ← Einsetz-Zeiten → Verlagerungsrichtung

ALLES KOMBINIERT:
    ↓
decide_lage_label()                     ← Föhn > Vb > Bise > Strömung > Hoch/Tief

build_synoptic_context()
    ↓
data/synoptic_context.json (Cache)
data/synoptic_audit/<date>.json (Audit)
    ↓
build_briefing_data() → briefing_data["wetterlage"]
    ↓
UI (briefing.js) + Email (email_service.py)
```

## Klassifikatoren — Schwellen und Quellen

Alle Schwellen in `config.py` unter `SYNOPTIC_*`.

### `decide_pressure_influence`
- `>= 1020 hPa` → Hochdruck
- `<= 1010 hPa` → Tiefdruck
- `<= 1000 hPa` → starker Tiefdruck
- Trend: Linear-Fit über die Woche, `|slope| < 2 hPa/Tag` = stabil

### `decide_flow_overhead`
- 8 Pilotenkompass-Sektoren (Nord/Nordost/...) à 45°
- Stärke: schwach (<15) / mässig (15-30) / kräftig (30-50) / stürmisch (>50)
- Rotation: ≥90° Drehung zwischen aufeinanderfolgenden Tagen + Sektor-Wechsel

### `find_pressure_centers`
- Lokales Min/Max gegen 4 nächste Nachbarn (Haversine)
- Mindest-Gradient: `5 hPa` zur Nachbar-Durchschnittsmessung
- Schwächere Verteilungen werden verworfen (keine Erfindung)

### `decide_bise`
- ΔP `(Skandinavien Süd + Mitteleuropa + Osteuropa)` − `(Westmittelmeer + Adria + Norditalien)` ≥ 4 hPa
- UND 700hPa-Wind aus Sektor 30°-90° (NE)
- UND 700hPa-Speed ≥ 15 km/h
- Stärke: ≥10 hPa = stark, ≥6 hPa = mittel, sonst schwach

### `decide_vb_lage`
- Tief-Zentrum in Box (40-46°N, 5-18°O)
- MSL ≤ 1010 hPa
- "ausgeprägt" wenn ≥2 Tage aktiv

### `decide_foehn_summary`
- Quelle: `foehn_indicators.fetch_foehn_data` (eigener API-Call, 2 Punkte)
- Pro Tag: Stunden im Flugfenster `FLIGHT_HOURS_START..END` (06–18) prüfen,
  aktiv ab `SYNOPTIC_FOEHN_ACTIVE_MIN_HOURS` (1) Stunde caution+ — dieselbe
  Regel wie die Regions-Analyse (`_format_foehn_info`: schlimmste Stunde im
  Flugfenster). Damit gilt: **hat eine Region Föhn, zeigt ihn auch die
  Synoptik.** Früher 10–16 Uhr und ≥2 h — am 16.09.2026 zeigte Oberwallis
  „Föhn mässig“ (1 h Nordföhn), die Synoptik keinen Föhn.
- Umgekehrt darf die Synoptik Föhn zeigen, den eine Region wegen ihrer
  `kritischer_foehn`-Richtung ausblendet — der Föhn ist real, nur dort
  unkritisch.
- Richtungen: Süd / Nord / wechselnd
- Bei API-Fehler: `source="fetch_failed"`, Block läuft trotzdem weiter

### `decide_precip_pattern_nord_sued`
Spot-Klassifikation:
- `lat < 46.45 AND lon > 8.5` → alpensued (Tessin)
- `lat < 46.35 AND 6.5 < lon < 8.5` → alpensued (Wallis-Haupttal)
- alles andere → alpennord

**Pure-LLM-Variante (Mai 2026):** keine deterministische Charakter-Klassifikation
mehr. Aggregation liefert pro Seite und Tag nur die Rohwerte:
- `peak_mm`: max. stündliche Niederschlagsmenge über alle Spots
- `wet_share`: Anteil Spots mit total_mm >= 0.5 (DRY_MM)
- `max_cape`: max. CAPE (J/kg) — Konvektions-Indikator
- `max_coverage`: max. precipitation_coverage (0–1) — DWD-Confidence
- `n_spots`: Anzahl Spots auf dieser Seite

Bewertung („Hitzegewitter", „Landregen", „trocken") machte bis 25.10.2026
der LLM in `skills/synoptic_overview.md`; heute nennen die Bausteine in
`scripts/briefing_v3_context.py` die Daten ohne solche Etiketten. Frühere if/elif-Kaskade mit char-Labels
(Schauer/Gewitter/flaechig/trocken) wurde im Mai 2026 entfernt, weil
Edge-Cases (z.B. hohe CAPE + niedriger wet_share = Hitzegewitter) sich
nicht sauber in starre Schwellen pressen liessen.

### `decide_precip_pattern_zones` (v2.0)
Pro Tag, Zone und Tagesfenster (`SYNOPTIC_DAY_WINDOWS`):
- `wet_share`: Anteil Spots mit ≥ `SYNOPTIC_PRECIP_WINDOW_WET_MM` (0.2 mm/h)
  in einer Fensterstunde — im Tages-Aggregat weiterhin Tagessumme ≥ 0.5 mm
- `p90_mm` / `max_mm`: 90. Perzentil bzw. Maximum der Spot-Stundenmaxima
- `gewitter_share`: Anteil Spots mit weather_code 95/96/99, **3 Nachkomma-
  stellen** — 1 Zelle unter 327 Spots (0.003) darf nicht auf 0.0 runden,
  sonst kippt die Skill-Regel „Gewitter nur bei > 0"
- `max_wc`, `max_cape`, `max_coverage` (Tages-Aggregat)

### `decide_wind_pattern_zones` (v2.0)
Tages-Kennzahlen identisch zu `_aggregate_wind_side` (Kernstunden 10-17,
`wind_class` autoritativ) — nur der Raumschnitt sind die 4 Zonen.
Zusaetzlich `windows[*].share_wind_crit` fuer den Tagesverlauf des Windes.

### `decide_zugbahn` (v2.0)
- Gruppen: die 4 Zonen, Alpennordhang intern West/Ost geteilt
- `onset` = erste Stunde (6-20), in der ≥ `SYNOPTIC_ZUGBAHN_ONSET_SHARE`
  (10 %) der Gruppen-Spots nass sind; Gruppe braucht ≥ 5 Spots
- Richtung nur bei ≥ `SYNOPTIC_ZUGBAHN_MIN_DIFF_H` (2 h) Versatz
  (`west_nach_ost` / `ost_nach_west` / `sued_nach_nord` / `nord_nach_sued`),
  sonst `"gleichzeitig"`; `null` wenn hoechstens eine Gruppe anspringt
- Trockener Tag → keine Verlagerungsaussage (Payload laesst `zugbahn` weg)

### `decide_schneefallgrenze`
- Nur Monate `{3, 4, 5, 10, 11}` (sonst `None`)
- Formel: `SSG = gh850_m + (T850_c - 1) / 0.0065`
- (Lapse-Rate 6.5 K/km, Schneefall bei +1 °C)

### `decide_lage_label` (Hierarchie)
1. Föhn aktiv → Südfoehnlage / Nordfoehnlage / Foehnlage (wechselnd)
2. Vb aktiv → Genua-Tief (Label **ohne** das Kürzel „Vb" — van-Bebber-
   Zugbahnnummer, im Cast unverständlich; der i18n-Key hängt am Wert:
   `js.lage.<value>`, beim Ändern beide Seiten nachziehen)
3. Bise aktiv → Bisenlage
4. Strömung ≠ schwach → Westlage / Nordwestlage / Suedwestlage / ...
5. Hochdruck dominant → Hochdrucklage
6. Tiefdruck dominant → Tiefdrucklage
7. Übergangslage → Übergangslage

## Provenance pro Strukturfeld

Jedes klassifizierte Feld trägt:
- `value`: das klassifizierte Label
- `decided_by`: Funktionsname (z.B. `"decide_pressure_influence"`)
- `inputs`: die eingegangenen Datenwerte (z.B. `{"msl_by_day": [1023, 1024, ...]}`)
- `thresholds`: die angewendeten Schwellen aus `config.py`

Damit ist jede Aussage rückwärts auflösbar bis zur Rohzahl. Audit-Logs unter
`data/synoptic_audit/<date>.json` (30 Tage Rotation).

## Gefahren-Schalter (`hazard_checks`)

`engine/synoptic_llm.py:hazard_checks()` entscheidet je `forecast_dates`-Tag
über `RAIN` (Nässe ≥ `SYNOPTIC_HAZARD_RAIN_WET_SHARE` in einer Zone),
`THUNDER` (`gewitter_share` > 0 oder `konvektion.gewitter`), `FOEHN`
(`foehn.per_day` bzw. Talpunkte) und `WIND` (`wind_class` verblasen/stark
eingeschränkt). Das Briefing zeigt daraus die Warnungs-Labels; erklärt wird
jede Gefahr im passenden Block der Kette. `llm_overview` im Cache ist `null`
(Feld bleibt für ältere Leser).

Bis 25.10.2026 schrieb hier ein LLM (Skill `synoptic_overview.md`) Lead,
Gefahren- und Tagessätze, geprüft von einem Validator mit bis zu 4
Korrekturrunden. Er brauchte im Oktober fast täglich alle Runden, die Sätze
wiederholten nur die Blöcke — darum entfernt (Code und Skill, siehe Git).

## Integration

- **Scheduler** (`scheduler.py`): `refresh_synoptic_overview()` läuft vor
  `build_briefing_data()` im Daily-Cycle. Fehler werden geloggt aber stoppen
  den Versand nicht.
- **Briefing-Data** (`engine/analyzers.py:build_briefing_data`): lädt
  `data/synoptic_context.json` und packt es in `briefing_data["wetterlage"]`.
- **Email + App-Briefing** (`email_service.py` → `scripts/briefing_v3_context.py`):
  Kette aus Textbausteinen, Warnungen als Labels.
- **Synoptik-Seite** (`/synoptik`): seit 04.10.2026 nur die interaktive
  Druckkarte, keine Wetterlage-Texte mehr.
- **Admin** (`/admin/wetterlage_audit/<date>`): zeigt Audit-JSON für
  Nachvollziehbarkeit (welcher Klassifikator hat was entschieden mit welchen
  Inputs).

## Vorher/Nachher prüfen

`python scripts/preview_briefing_email.py` rendert das Briefing aus den
lokalen Caches (`docs/BRIEFING.md`).

## Tests

- `tests/test_synoptic_context.py` — 81 Tests:
  - Helper (Sektoren, Vektor-Mittel, MSL-Reduktion)
  - Aggregation, Basis-Detektoren, höhere Klassifikatoren
  - Build-Pipeline (None-Fälle)
  - v2.0: Zonen-Mapping (alle Spots auflösbar, jede Zone hat Spots),
    P90-Ausreisser-Resistenz, Tagesfenster erhalten die Zeitachse,
    `gewitter_share` rundet 1/200 nicht weg, Zugbahn (Richtung /
    "gleichzeitig" / trockener Tag / Mindest-Spotzahl)
- `tests/test_synoptic_llm.py` — Gefahren-Schalter: Schwellen, Tagesform,
  Zeitfenster, Föhn-Verlauf, Ausblick
- `tests/test_foehn_tal_briefing.py` — Föhn-Talwerte im Briefing

## Lebenszyklus eines Casts

1. `06:00` Scheduler triggert Daily-Cycle
2. `refresh_weather()` läuft, schreibt `wetterdaten.json`
3. `refresh_synoptic_overview()`:
   - `aggregate_ch_daily_snapshot()` → 5 CH-Mittel
   - `fetch_europe_pressure_grid()` → 15 Europa-Punkte (ECMWF-IFS)
   - Alle `decide_*` feuern, schreiben Tags in `_synoptic_decisions_applied`
   - `synoptic_context.json` + `synoptic_audit/<date>.json`
4. `build_briefing_data()` lädt Wetterlage und packt sie ins Result
5. `send_briefing_email()` versendet
6. Web-UI lädt `/api/briefing` und rendert den Block

## Audit nachvollziehen

Beispiel: User sieht im Cast *"Hochdruck dominiert die Woche mit schwacher
Westströmung"*. Audit-Trail:

1. `GET /admin/wetterlage_audit/2026-05-17` öffnen
2. `lage_label`: `{value: "Hochdrucklage", trigger: "pressure_influence=Hochdruck"}`
3. `pressure_influence`: `{value: "Hochdruck", trend: "aufbauend",
   slope_hpa_per_day: 2.77, decided_by: "decide_pressure_influence",
   inputs: {msl_by_day: [1022.8, 1022.8, 1025.0, 1030.3, 1032.9]},
   thresholds: {hoch_hpa: 1020, ...}}`
4. `flow_overhead`: `{value: "West", strength: "schwach",
   inputs: {wind_700_by_day: [...]}}`

→ Jede Aussage rückführbar bis zur Rohzahl — die Texte entstehen aus
festen Bausteinen über genau diesen Feldern.
