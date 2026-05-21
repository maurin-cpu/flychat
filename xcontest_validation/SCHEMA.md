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
- `our_xc_rating` — `streckenflug.rating` 1-5
- `our_status` — `safe` | `conditional` | `not_safe`
- `our_streckenflug_tier` — z.B. `xc_high`, `local_only`, …
- `our_streckenflug_limiting_factor` — z.B. `region_context_missing`, `wind_aloft_high`
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
