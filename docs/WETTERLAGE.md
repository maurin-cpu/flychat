# Wetterlage-Block (Synoptik)

Status: v2.0 „Flugwetter-Zonen" (Juli 2026), Basis v1.0 (Mai 2026)
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
2. LLM bekommt **nur** die klassifizierten Felder, **keine** Rohzahlen.
3. Skill-Prompt enthält Whitelist + Verbotsliste.
4. Post-Filter prüft jedes Output-Statement gegen Verbotsbegriffe und Source-Tags.
5. Bei Fehler in der Pipeline: Block wird **weggelassen**, kein Fallback-Text.

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
decide_foehn_summary()                  ← Pro Tag: ≥2h caution+ → aktiv

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
generate_synoptic_overview()            ← LLM-Call mit skills/synoptic_overview.md
    ↓ Post-Filter (Verbotsbegriffe, Sources, Region-Validierung)
short + long Prosa-Versionen
    ↓
data/synoptic_context.json (Re-write mit llm_overview)
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
- Pro Tag: Stunden 10-16 lokal prüfen, ≥2h caution+ → aktiv
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

Bewertung („Hitzegewitter", „Landregen", „trocken") macht der LLM in
`skills/synoptic_overview.md`. Frühere if/elif-Kaskade mit char-Labels
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
2. Vb aktiv → Vb-/Genua-Tief
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

## Halluzinations-Schutz im LLM-Pfad

### Skill-Prompt (`skills/synoptic_overview.md`, EN: `skills/en/`)
- Whitelist: erlaubte Strukturfeld-Quellen + erlaubte Phänomen-Begriffe
- Verbotsliste explizit: Kaltfront, Warmfront, Okklusion, Frontdurchgang,
  präfrontal, postfrontal, Trog, Rücken, Geopotential, Vorticity, hPa-Werte
- Konfidenz-Decay: `level=low` nur weiche Sprache ("Tendenz", "dürfte")
- v2.0: **Konsistenz-Pflicht** für die Druckzentren→Strömungs-Kette — passt
  die Zentren-Lage nicht zu `flow_overhead.sector`, wird die Herleitung
  weggelassen statt erfunden

### Ausgabe-Format (v2.0)
```json
{"lead": "...",
 "zones": [{"zone": "alpennordhang",
            "days": [{"text": "...", "flight_hint": "..."}]}]}
```
Zuordnung `days[i] ↔ forecast_dates[i]` per Position, Zonen über die
`zone`-ID (nicht über die Reihenfolge). `_finalize` sortiert nach
`config.SYNOPTIC_ZONES`, nicht nach LLM-Reihenfolge.

### Validierung (`engine/synoptic_llm.py:_validate`)
1. **Regex-Verbotsfilter**: `\bkaltfront\b`, `\btrog\b`, `\d{3,4}\s?hPa`, ...
2. **Zonen-Vollständigkeit**: alle 4 Zonen, keine doppelt, keine unbekannte
   ID; pro Zone `len(days) == len(forecast_dates)`
3. **Region-Validierung**: erwähnte Region-Labels müssen für **diesen** Cast
   detektiert worden sein (sonst Erfindung)
4. **Föhn-Lee pro Zone**: bei `foehn.side="Nord"` darf `tessin`, bei
   `"Sued"` dürfen `alpennordhang`/`wallis` nicht als ruhig/geschützt
   gelten — greift auch ohne Regionen-Token im Satz (die Zone *ist* die
   Ortsangabe)
5. **Lob-Gate pro Zone**: Lob-Vokabular in einer Zone mit
   `wind_class ∈ {verblasen, stark_eingeschraenkt}` → Korrekturrunde
   (v1.0 prüfte nur, ob BEIDE Alpenseiten windkritisch waren — eine
   verblasene Zone neben einer ruhigen rutschte durch)
6. **Föhn nur an Föhntagen**: `foehn.active` gilt für den ganzen Zeitraum,
   die Gefahr aber nur an `days_affected`. Jedes Föhn-Wort an einem Tag
   ohne aktiven Föhn ist ein Fehler (DE-Lauf 26.07.: „Föhnschneisen
   kritisch" an einem föhnfreien Samstag)
7. **Gewitter nur mit Signal**: `gewitter_share == 0` in der Zone → das
   Wort „Gewitter"/„thunderstorm" ist unzulässig. Hohe CAPE allein heisst
   „labile Luft". Die Regel stand im Skill, war aber nirgends verankert.

Fehler → Korrekturrunde (max 4 Versuche) → chirurgisches Bereinigen der
besten Version + Admin-Mail. Kein stilles Löschen.

Die Fehlermeldung an den LLM ist **prescriptiv, nicht nur verbietend**:
bei Föhn-Lee steht das gefundene Wort und ein Ersatz-Baumuster darin, bei
erfundenen Druckzentren die Positivliste der erlaubten `region_label`.
Grund: Am 25.07.2026 fiel das Modell auf das blosse Verbot hin zweimal in
dieselbe Formulierung zurück (3/3 Versuche verbraucht, keine Reserve) und
ersetzte eine erfundene Region durch die nächste erfundene.

### Legacy-Kompatibilität
`short` (Mail-Lead) unverändert. `long_with_sources` wird weiterhin
befüllt — mit der **grössten Zone** (Alpennordhang), nicht mit einer
Flach-Verkettung aller vier (die hätte 4× dieselben Wochentage).
`briefing.js` bevorzugt `zones` und fällt darauf zurück.

## Integration

- **Scheduler** (`scheduler.py`): `refresh_synoptic_overview()` läuft vor
  `build_briefing_data()` im Daily-Cycle. Fehler werden geloggt aber stoppen
  den Versand nicht.
- **Briefing-Data** (`engine/analyzers.py:build_briefing_data`): lädt
  `data/synoptic_context.json` und packt es in `briefing_data["wetterlage"]`.
- **Email** (`email_service.py`): wenn `wetterlage.llm_overview.short`
  existiert → ersetzt `week_lead`. Sonst Fallback auf
  `_week_summary_llm` (alter 1-2-Satz-Lead).
- **UI** (`static/js/briefing.js:renderWetterlage`): Block oben vor Fazit
  und Tag-Tabs. Kurzfassung (`short`) sichtbar, "Detail"-Toggle zeigt die
  4 Zonen-Abschnitte (`.bf-wetterlage-zone` mit Überschrift + Tages-Blöcken).
- **Admin** (`/admin/wetterlage_audit/<date>`): zeigt Audit-JSON für
  Nachvollziehbarkeit (welcher Klassifikator hat was entschieden mit welchen
  Inputs).

## Vorher/Nachher prüfen

`python scripts/preview_synoptik_zonen.py` erzeugt den Zonen-Block aus dem
aktuellen Wettercache, ohne Prod-Caches zu überschreiben, und zeigt:
1. **Rohdaten-Faktencheck** — `wet_share`/`p90_mm` je Zone/Tag/Fenster,
   `wind_class`, Zugbahn-Einsetzzeiten
2. den **alten** Block aus `synoptic_context.json`
3. den **neuen** Zonen-Block (LLM-Call)

`--no-llm` überspringt den LLM-Call (nur Strukturfeld + Faktencheck).
Ergebnis landet in `data/_preview_synoptik_zonen.json` (gitignored).

## Tests

- `tests/test_synoptic_context.py` — 81 Tests:
  - Helper (Sektoren, Vektor-Mittel, MSL-Reduktion)
  - Aggregation, Basis-Detektoren, höhere Klassifikatoren
  - Build-Pipeline (None-Fälle)
  - v2.0: Zonen-Mapping (alle Spots auflösbar, jede Zone hat Spots),
    P90-Ausreisser-Resistenz, Tagesfenster erhalten die Zeitachse,
    `gewitter_share` rundet 1/200 nicht weg, Zugbahn (Richtung /
    "gleichzeitig" / trockener Tag / Mindest-Spotzahl)
- `tests/test_synoptic_llm.py` — 42 Tests:
  - Validierung (Verbotsbegriffe inkl. CAPE-Jargon, Region-Mention-Check,
    Zonen-Vollständigkeit/Duplikate/unbekannte IDs)
  - Föhn-Lee **pro Zone** (Lee verboten, Stau-Zone erlaubt)
  - Föhn-Erwähnung nur an `days_affected`; Gewitter nur bei
    `gewitter_share > 0` (und kein Fehlalarm ohne `precip_zones`)
  - Korrektur-Nachrichten sind prescriptiv (nennen Wort + Ersatzmuster
    bzw. die erlaubten `region_label`)
  - Lob-Gate **pro Zone** (verblasene Zone ≠ ruhige Nachbarzone)
  - `_finalize`: Zonen-Reihenfolge aus Config, Wochentag-Präfixe,
    EN-Modus (Wochentage + Zonen-Labels), Prune, Legacy-Felder
  - Payload-Builder (Zonen + Fenster + Zugbahn drin, altes Nord/Süd raus)

LLM-Calls selbst werden **nicht** getestet (Integration, kein Unit-Test).

## Lebenszyklus eines Casts

1. `06:00` Scheduler triggert Daily-Cycle
2. `refresh_weather()` läuft, schreibt `wetterdaten.json`
3. `refresh_synoptic_overview()`:
   - `aggregate_ch_daily_snapshot()` → 5 CH-Mittel
   - `fetch_europe_pressure_grid()` → 15 Europa-Punkte (ECMWF-IFS)
   - Alle `decide_*` feuern, schreiben Tags in `_synoptic_decisions_applied`
   - `synoptic_context.json` + `synoptic_audit/<date>.json`
   - `generate_synoptic_overview()` → LLM-Call mit Skill
   - Post-Filter → verworfene Sätze werden geloggt
   - Cache wird re-written mit `llm_overview`
4. `build_briefing_data()` lädt Wetterlage und packt sie ins Result
5. `send_briefing_email()` versendet — short-Text als Lead
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

→ Jede Aussage rückführbar bis zur Rohzahl. Kein "der LLM hat sich was
ausgedacht" möglich, weil der LLM nur das Strukturfeld zu sehen bekommt
und der Post-Filter alles ausserhalb der Whitelist verwirft.
