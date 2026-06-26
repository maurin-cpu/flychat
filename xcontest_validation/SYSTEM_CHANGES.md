# System-Aenderungen waehrend XContest-Validierungs-Periode

Diese Datei dokumentiert grundsaetzliche Aenderungen am Wingcast-Vorhersage-System,
die waehrend des laufenden XContest-Validierungs-Workflows passiert sind. Wichtig
fuer die Interpretation von Validierungs-Ergebnissen ueber die Zeit: ein Drift
oder Sprung in der Treffer-Quote koennte ein System-Aenderung sein, nicht ein
echter Forecast-Trend.

## 2026-05-25 — Region-Thermik umgestellt auf Spot-Median

**Was sich geaendert hat:**
Region-Thermik-Output (max_height, climb_rate, lcl) wird ab heute aus dem **Median
der in-region Spot-Thermik-Werte** berechnet, nicht mehr aus einer
1-Refpoint-Aggregation der 7 Region-Refpoints.

**Was sich NICHT geaendert hat:**
- Spot-Vorhersagen (jeder Spot wird weiter individuell gerechnet, mit eigenen
  Pressure-Levels + Surface-Daten)
- Region-Wind (Median ueber 7 Refpoints)
- Region-Wolken (30%-Perzentil ueber 7 Refpoints)
- Region-Niederschlag (Hybrid-Filter ueber 16 dichte CVT-RPs)

**Warum:**
Refpoint-Aggregation hatte median |Bias| 794m gegen Spot-Median (Test ueber 23
Regionen, 2026-05-25), Stddev 474m — also nicht systematisch zu tief, sondern
richtungs-zufaellig. Wallis-Pilot-Realitaet 3500-4000m wurde von Status quo in
0/4 Wallis-Regionen getroffen, von Spot-Median in 4/4 (2 perfekt, 2 knapp daneben).

Refpoint-Median (Variante B) und Sheridan-Lapse (Variante D) verbesserten nur
kosmetisch (MAE 794 → 704m). Nur Spot-Median (Variante E) trifft Pilot-Realitaet
strukturell.

**Erwartete Effekte fuer XContest-Validierung ab 2026-05-25:**
- 14 Regionen werden um >200m angehoben (Wallis +500 bis +970m, Berner Voralpen +565m,
  Prättigau +878m, Ostschweiz +851m, etc.)
- 2 Regionen +100 bis +200m
- 5 Regionen werden um >200m gesenkt (Surselva −927m, Engadin Unter −308m, Oberwallis
  Goms −368m, etc.)
- 6 Regionen (Bodenseeraum, Jura Ost, Mittelland West/Ost, Seeland Emmental,
  Zentrales Mittelland) behalten Refpoint-Pfad als Fallback (n_spots < 3 Schwelle)

**Wenn Validierung vorher vs. nachher vergleicht:**
Wallis-Treffer-Rate sollte ab 2026-05-25 deutlich steigen. Surselva-Treffer-Rate
koennte sinken (wir sind dort von „zufaellig zu hoch" auf „strukturell korrekt"
zurueckgegangen — wenn Realitaet wirklich hoch war, sind wir jetzt zu tief).

**Code-Stellen:**
- `fetch_weather.py:_compute_region_spotmedian_thermals` (Aggregation)
- `thermik_calculator.compute_daily_thermals(..., spotmedian_override=...)` (Override-Mechanismus)
- Caller die durchreichen: `web.py:format_data_for_charts`, `web.py:api_region_weather`,
  `engine/weather_context.py:_build_single_region_context`, `engine/labeled_examples.py`

**Memory-Referenzen:**
- `region_thermik_spotmedian.md` (neue Architektur)
- `hochalpin_maxheight_bias.md` (RESOLVED — war eigentlich Region-Aggregation, kein Thermik-Bug)
- `docs/HOCHALPIN_MAXHEIGHT_BIAS.md` (Erratum-Hinweis am Anfang)

## 2026-06-07 — Region-Hoehen-Aggregation umgestellt von Median (P50) auf P75

**Was sich geaendert hat:**
Region-Thermik-Output **max_height** und **lcl** werden ab heute aus dem **75.
Perzentil** der in-region Spot-Werte berechnet, nicht mehr aus dem Median (P50).
Aggregations-Mechanismus (Spot-basiert statt Refpoint, ab n_spots>=3) bleibt
unveraendert — nur der Perzentil-Wert steigt von P50 auf P75.

**Was sich NICHT geaendert hat:**
- **climb_rate** bleibt Median (P50) — Steig-Groesse, gegen Topout nicht pruefbar.
- Wind / Wolken / Niederschlag (weiter Refpoint-aggregiert).
- Spot-Vorhersagen (unveraendert individuell gerechnet).
- Override-Key heisst aus Kompat-Gruenden weiter `thermals_spotmedian` (in
  Snapshots/Archiven persistiert) — seit heute ein Misnomer (ist P75 fuer Hoehen).

**Warum — Beleg mit echten Metern:**
16 reale XContest-Topouts (Max-Hoehe MSL) vom 28.-30.05.2026 (User-abgelesen,
`_raw/topout_altitudes_2026-05-28_30.tsv`) gegen die Region-Vorhersage der
Launch-Region (`debug_scripts/topout_vs_percentile.py`):

| Aggregator | max_height mean Bias | median Bias | mean \|Bias\| | Topout > Vorhersage |
|--|--|--|--|--|
| P50 (alt) | **−300 m** | **−371 m** | 476 m | **13 / 16** |
| **P75 (neu)** | +44 m | +96 m | **321 m** | 7 / 16 |
| best30 | +151 m | +252 m | 376 m | 5 / 16 |

P50 unterschaetzte die erreichte Decke systematisch (Median 371m zu tief; in 13/16
Fluegen stieg der Pilot HOEHER als vorhergesagt). Bei der Basis (lcl) erzeugte P50
**7/16 physikalisch unmoegliche Faelle** (vorhergesagte Wolkenbasis UNTER der real
erflogenen Hoehe) — P75 nur 5/16, best30 3/16. P75 ist nahezu bias-frei und hat
den kleinsten absoluten Fehler; best30 ueberschiesst. Bestaetigt den A/B-Test vom
2026-06-04 (`debug_scripts/ab_region_percentile.py`) jetzt mit Meter-Validierung.

**Caveats (in Ergebnis-Interpretation beachten):**
- XContest zeigt die *besten* Tracks des Tages → Topout = erreichbare Decke starker
  Tage. P75 zielt bewusst auf dieses XC-Niveau. Die 3 Gegenbeispiele (P50 reichte)
  waren alle kurze/schwache Fluege (<35 km) — P50 genuegt an schwachen Tagen,
  unterschaetzt an starken XC-Tagen.
- Topout wird irgendwo auf der Route erreicht, nicht zwingend ueber der Launch-
  Region; bei den 3 langen Fluegen (>160 km) ist die Region nur ein Anker. Signal
  ist trotz dieses Rauschens klar.

**Erwartete Effekte fuer XContest-Validierung ab 2026-06-07:**
- Region max_height/lcl steigen gegenueber vorher (P75 > P50): mittlere Anhebung
  in der Stichprobe ~+340m bei max_height, ~+220m bei lcl.
- Treffer-Rate an starken XC-Tagen sollte steigen; an schwachen Tagen evtl. leichte
  Ueberschaetzung (auf der sicheren XC-Seite). Ein Sprung in der Treffer-Quote ab
  diesem Datum ist diese Aenderung, kein Forecast-Trend.

**Code-Stellen:**
- `fetch_weather.py:_spot_p75` (neuer P75-Helper, = validierte agg_p75)
- `fetch_weather.py:_compute_region_spotmedian_thermals` (max_height/lcl -> _spot_p75)
- Override-Durchreichung unveraendert (`thermals_spotmedian`-Key).

**Validierungs-Artefakte:**
- `xcontest_validation/_raw/topout_altitudes_2026-05-28_30.tsv` (16 Roh-Topouts)
- `xcontest_validation/TOPOUT_STICHPROBE.md` (Auswertung)
- `debug_scripts/topout_vs_percentile.py` (Analyse-Skript)

**Memory-Referenzen:**
- `region-thermik-perzentil.md` (P50->P75 Empfehlung, jetzt Meter-validiert + umgesetzt)
