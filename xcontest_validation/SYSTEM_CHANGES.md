# System-Aenderungen waehrend XContest-Validierungs-Periode

Diese Datei dokumentiert grundsaetzliche Aenderungen am Gleitcast-Vorhersage-System,
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
