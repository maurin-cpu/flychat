# Schema-Dokumentation

Hier dokumentiert: `observations.csv` (primäre Validierungs-Datenpunkte) +
`sector_audit.csv` (abgeleitetes Arbeitsblatt für Sektor-Diskussion).

---

# observations.csv — Schema

Akkumulierte XContest-Validierung pro Spot+Tag. Eine Zeile = ein Spot an einem
Tag. Wird bei jedem XContest-Auszug appended (nie überschrieben), nicht
deduplizieren — Mehrfacheinträge für denselben Spot+Tag sind ein Signal (z.B.
History-Update bei besserem Wetterdaten-Match).

## Datenquellen pro Zeile

| Spaltengruppe | Quelle |
|---|---|
| `date`, `spot`, `region`, `launches`, `best_km`, `top_pilot`, `top_start_time`, `top_airtime` | XContest-Paste (User-Input) |
| `our_*` | `data/weather_archive/YYYY-MM-DD.json` → `spots[spot].analysis` |
| `wx_*` | `data/weather_archive/YYYY-MM-DD.json` → `spots[spot].daily_aggregates` |
| `finding_type`, `notes` | Beim Anlegen der Zeile vom Analysten (= Claude Code) gesetzt |

## Spalten

### XContest-Beobachtung
- `date` (YYYY-MM-DD) — Flugtag
- `spot` — Spot-Name wie in `data/wetterdaten.json` (Fuzzy-Mapping auf XContest-Startplatz)
- `region` — `analyse_region` aus `fluggebiete_complete.csv`
- `launches` — Anzahl Top-100-Flüge ab diesem Spot
- `best_km` — beste FAI-/Liga-Distanz an dem Tag ab diesem Spot
- `top_pilot` — Pilot des besten Flugs (optional, für Plausibilitäts-Check)
- `top_start_time` — Startzeit des besten Flugs (HH:MM)
- `top_airtime` — Flugzeit des besten Flugs (HH:MM)

### Unser Forecast (Snapshot-Stand)
- `our_safety_rating` — `safety_rating` 0-10 (0 = not_safe)
- `our_experience_rating` — 1-5
- `our_xc_rating` — XC-Signal 1-5. **≤2026-05-29**: `streckenflug.rating` (eigenes Feld).
  **≥2026-05-30**: `experience_rating` — die separate streckenflug-Note wurde abgekündigt
  und in die Flugeinschätzung integriert (XC steckt seither dort). Leer, wenn die
  Flugeinschätzung am Tag ein Stub war (29.05/09.06/10.06/20.06). Note-Feld trägt dann
  `xc_aus_flugeinschaetzung`.
- `our_status` — `safe` | `conditional` | `not_safe`
- `our_streckenflug_tier` / `our_streckenflug_limiting_factor` — nur ≤2026-05-29 befüllt
  (Feld danach abgekündigt → leer).
- `decisions_applied` — Pipe-getrennte Liste (`FoehnCaution(4.5)|GustFloor`)
- `no_go_reasons` — Pipe-getrennte Liste der Kanonischen No-Go-Strings

### Wetter-Tagesaggregate (Modell sagte für diesen Tag)
- `wx_climb_rate_max_ms` — Peak-Steigwert (m/s) Flugfenster
- `wx_max_thermal_height_m` — Max Thermik-Top (MSL)
- `wx_blh_max_m` — GFS-PBL Höhe Tagespeak
- `wx_wind_gust_max_kmh` — Peak-Böe Flugfenster
- `wx_wind_dir_dominant_deg` — Geschwindigkeits-gewichtete Vektor-Mittelrichtung
- `wx_t2m_max` — Tageshöchsttemperatur
- `wx_precip_sum_mm` — Niederschlag Tagessumme
- `wx_cloud_low_mean_pct` — Tiefe Wolken Mittel Flugfenster
- `wx_cape_max` — CAPE Tagespeak
- `wx_lifted_index_min` — LI Tagesminimum (negativer = instabiler)
- `wx_productive_thermal_h` — Anzahl Stunden ≥ 0.7 m/s climb_rate

### Klassifikation
- `finding_type` — eine von:
  - `confirm` — Forecast passt zur Realität
  - `underrated_region` — Region-Rating zu tief vs. Realität
  - `underrated_spot` — Spot-Rating zu tief
  - `false_positive_notsafe` — `our_status=not_safe`, real geflogen
  - `false_positive_caution` — übertrieben warning
  - `overrated` — wir zu optimistisch, niemand geflogen oder schlechtere Realität
  - `coverage_gap` — Spot fehlt in DB (dann sind `our_*` leer)
  - `bug` — z.B. `limiting_factor: region_context_missing`
- `notes` — Freitext-Kontext, was die Klassifikation begründet

## Was NICHT in der CSV steht

- **Stündliche Werte** → in `data/weather_archive/YYYY-MM-DD.json` unter
  `spots[spot].hourly_flight`. Bei Bedarf joinen über `(date, spot)`.
- **Volle Forecast-Texte / LLM-Summaries** → `spots[spot].analysis.tags` etc. im
  Archiv-JSON.
- **0-Launches-Spots** → werden NICHT als Zeile erfasst (siehe README). Nur wenn
  XContest min. 1 Top-Flug zeigt, gibt es eine Zeile.

## Pipe-Trenner statt Komma in Listen

Listen wie `decisions_applied` und `no_go_reasons` werden Pipe-getrennt (`|`)
serialisiert, damit CSV-Parser nicht stolpern. Beim Auswerten splitten auf `|`.

## Akkumulation, nicht Replace

Auch wenn derselbe Tag mehrfach analysiert wird (z.B. erst Forecast-Vergleich
am Morgen, dann Nachbesserung abends), wird **angehängt**. Bei späterer
Auswertung kann nach `(date, spot)` aggregiert werden — die jüngste Zeile
gewinnt, oder alle Zeilen werden behalten für Audit-Trail.

---

# sector_audit.csv — Schema

Abgeleitetes Arbeitsblatt für die Sektor-Diskussion. Filtert observations.csv auf
False-Positives (`finding_type ∈ {false_positive_notsafe, false_positive_caution}`),
parst den DB-Sektor (`windrichtung` aus weather_archive/`fluggebiete_complete.csv`)
zu Grad-Range, berechnet die Differenz zur gemessenen Wind-Richtung und klassifiziert
das Befund.

**Wird nicht manuell gepflegt — wird neu erzeugt aus observations.csv +
data/weather_archive/ per `python scripts/generate_sector_audit.py`.**

## Spalten

### Identität
- `date`, `spot`, `region`, `elevation_m`, `terrain_type` — kopiert aus observations.csv
  bzw. Spot-Stammdaten im Snapshot

### DB-Sektor (Spot-Eigenschaft)
- `db_sektor_text` — Original-String wie in CSV/DB, z.B. `"NW-NO"`, `"SSW-SSO"`
- `db_sektor_range_deg` — geparst zu Grad-Range mit Kürzester-Bogen-Konvention,
  z.B. `"315-45°"` (durch Norden) oder `"157-202°"` (durch Süden)
- `db_sektor_width_deg` — Breite der Range in Grad (typisch 45-90°)

### Gemessen (Tagesaggregat aus Forecast)
- `measured_wind_dir_deg` — `wx_wind_dir_dominant_deg` aus observations.csv
- `measured_gust_kmh` — `wx_wind_gust_max_kmh` aus observations.csv

### Geometrische Analyse
- `in_sector` — `yes` wenn gemessene Richtung im kürzeren Bogen liegt, sonst `no`
- `edge_distance_deg` — minimale Winkel-Distanz zur nächsten Sektor-Kante (immer ≥0).
  Bei `in_sector=yes` ist's die Distanz zum **näheren Sektor-Rand** (= wie tief drin).
  Bei `in_sector=no` ist's die Distanz **bis zum nächsten Sektor-Rand**.

### Kontext-Reproduktion
- `no_go_reason`, `launches`, `best_km`, `top_pilot`, `top_start_time`,
  `finding_type` — wie observations.csv

### Klassifikation
- `verdict` — heuristische Einordnung. Mögliche Werte:
  - **`FILTER-BUG (Code)`** — `in_sector=yes` aber no_go sagt "Sektor ausserhalb" →
    echter Code-Bug, Parser/Filter inkonsistent
  - **`BLOCK-FILTER (I-007)`** — `in_sector=yes` aber no_go sagt "Nur Xh sauber" →
    Wind passt, Block-Pflicht scheitert (I-007)
  - **`HARTE-WARNUNGEN-Filter`** — `in_sector=yes` aber no_go sagt "harte Warnungen"
  - **`I-008 (Wind schwach, Sektor egal)`** — `in_sector=no` ABER Gust <20 km/h →
    bei schwachem Wind sollte Sektor-Check nicht hart greifen
  - **`SEKTOR ZU ENG (<20° ausserhalb)`** — Wind nur knapp ausserhalb, Toleranz
    ±15-20° würde reichen
  - **`SEKTOR MITTEL (20-50° ausserhalb)`** — Spot hat evtl. weitere Variante mit
    anderer Hauptrichtung
  - **`MULTI-VARIANTE FEHLT (>50° ausserhalb)`** — Spot hat real einen anderen Hang
    (z.B. Brunnihütte W-SW vs. real N-Hang), DB-Eintrag fehlt
  - **`PARSE-FAIL (Sektor nicht lesbar)`** — DB-Sektor leer/unbekannt
- `notes` — gekürzt aus observations.csv (max 120 Zeichen)

## Konvention "Kürzerer Bogen"

Sektor "NW-NO" hat zwei mögliche Interpretationen:
- 315° → 45° clockwise (durch Norden, 90° breit) — **gewählt**
- 45° → 315° clockwise (durch Süden, 270° breit) — verworfen

Algorithmus: nimm die schmalere der beiden Bögen. Funktioniert für alle gängigen
2-Richtungs-Sektoren in unserer DB.

## Wann neu erzeugen?

Nach jedem `observations.csv`-Append → `python scripts/generate_sector_audit.py`.
Datei wird **überschrieben**, nicht angehängt (im Gegensatz zu observations.csv).
