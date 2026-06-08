# Wetterlage-Block (Synoptik)

Status: Implementation Mai 2026 (v1.0)
Aufruf: 1×/Tag vom Scheduler im Daily-Cycle, kurz vor Versand des Casts.
Ziel: Kompakte 5-Tages-Einordnung der Grosswetterlage in Pilotensprache —
zuoberst im Wingcast und in der E-Mail.

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

### Skill-Prompt (`skills/synoptic_overview.md`)
- Whitelist: erlaubte Source-Keys + erlaubte Phänomen-Begriffe
- Verbotsliste explizit: Kaltfront, Warmfront, Okklusion, Frontdurchgang,
  präfrontal, postfrontal, Trog, Rücken, Geopotential, Vorticity, hPa-Werte
- Source-Tag-Pflicht pro Statement (`sources: [...]`)
- Konfidenz-Decay: Tag 4-5 darf nur weiche Sprache ("Tendenz", "dürfte")

### Post-Filter (`engine/synoptic_llm.py`)
1. **Regex-Verbotsfilter**: `\bkaltfront\b`, `\btrog\b`, `\d{3,4}\s?hPa`, ...
2. **Source-Validierung**: jedes Statement muss `sources` haben, alle Keys
   müssen aus der Whitelist sein
3. **Region-Validierung**: erwähnte Region-Labels müssen für **diesen** Cast
   detektiert worden sein (sonst Erfindung)
4. **Leerer Output** nach Filter → Block wird ausgelassen, kein Fallback

Verworfene Statements werden mit Grund geloggt (`Post-Filter verworfen:
forbidden_term:\\bkaltfront\\b — '...'`) für Debug.

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
  und Tag-Tabs. Kurzfassung sichtbar, "Detail"-Toggle für Langfassung.
- **Admin** (`/admin/wetterlage_audit/<date>`): zeigt Audit-JSON für
  Nachvollziehbarkeit (welcher Klassifikator hat was entschieden mit welchen
  Inputs).

## Tests

- `tests/test_synoptic_context.py` — 62 Tests:
  - Helper (Sektoren, Vektor-Mittel, MSL-Reduktion)
  - Aggregation, Basis-Detektoren, höhere Klassifikatoren
  - Build-Pipeline (None-Fälle)
- `tests/test_synoptic_llm.py` — 13 Tests:
  - Post-Filter (Verbotsbegriffe, Source-Validierung, Region-Mention-Check)
  - Payload-Builder (keine Rohzahlen an LLM)
  - Provenance-Stripping

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
