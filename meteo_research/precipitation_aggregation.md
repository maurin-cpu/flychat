# Niederschlags-Aggregation: Forschungsgrundlage

## Zusammenfassung

Konvektive Schauer aus hochaufloesenden NWP-Modellen (ICON-D2, 2.2 km) erscheinen
als raeumlich verstreute Einzelzellen. Eine reine Quorum-Aggregation
("mindestens 30 % der Region-Referenzpunkte muessen Regen melden") filtert solche
Zellen systematisch heraus. Industrie-Standard ist die **Neighborhood Method**
(Ebert 2008): parallel **Maximum** (worst case) und **Fractional Coverage**
(Verteilungsinformation). DWD verwendet diesen Ansatz operationell seit 2012
fuer COSMO-DE-EPS und ICON-D2.

Gleitcast nutzt seit Mai 2026 einen **Hybrid-Filter**: hohe Peak-Werte
(≥ 0.2 mm/h) werden ohne Quorum durchgelassen, mittlere Werte unterliegen
weiterhin einem 30%-Quorum (Rauschunterdrueckung), Werte < 0.05 mm/h werden
auf 0 geclipt. `precipitation_coverage` (0.0-1.0) wird als zusaetzliches
Cache-Feld durchgereicht.

---

## 1. Das Problem mit reinem Quorum

### 1.1 ICON-D2 modelliert Konvektion explizit

ICON-D2 hat 2.2 km horizontale Aufloesung. Bei diesem Gitter wird Konvektion
nicht mehr parametrisiert, sondern explizit aufgeloest. Einzelne Schauerzellen
(Durchmesser 2-10 km, Lebensdauer 30-60 min) erscheinen als diskrete
Niederschlagsmuster im Output.

> "Precipitation became more aggregated with decreasing grid spacing. The
> areal mean daily precipitation amount for most of the cases decreases
> systematically across the model grid spacing."
> — Singh et al. 2021, *Quarterly Journal of the Royal Meteorological Society*

### 1.2 Geometrische Konsequenz

Eine Region wie "Zentrales Mittelland" (~30 km × 25 km, 7 Referenzpunkte) wird
bei einer typischen Schauerlage von **1-3 Zellen gleichzeitig** getroffen.
Statistisch:
- 1 Zelle in der Region → typisch 1 von 7 RPs nass (14 %)
- 2 Zellen → 1-3 RPs nass (14-43 %)
- 3 Zellen → 2-4 RPs nass (29-57 %)
- Flaechiger Frontregen → 6-7 RPs nass (>85 %)

Ein 30%-Quorum (alt) clipt damit **alle Schauerlagen mit 1-2 Zellen** auf 0.0.

### 1.3 Konkreter Fall (16.05.2026)

Region "Zentrales Mittelland", 7 Referenzpunkte. ICON-D2-Output zeigte
durchgaengig Schauerzellen zwischen 06:00 und 17:00. Pre-Hybrid-Cache:

| Stunde | Aggregat-Output | RP-Realitaet (rekonstruiert) |
|---|---|---|
| 06:00 - 11:00 | **0.0 mm/h** | je 1-2 RPs mit 0.2-0.5 mm/h |
| 12:00 | 0.1 mm/h | 3 RPs > 0 (Quorum knapp erfuellt) |
| 13:00 | 0.0 mm/h | 1-2 RPs mit 0.3-0.8 mm/h |
| 14:00 | 1.1 mm/h | 3+ RPs > 0 (Quorum erfuellt) |
| 15:00 - 17:00 | **0.0 mm/h** | je 1-2 RPs mit 0.4-0.8 mm/h |

xc-therm (Single-Grid-Point) zeigt fuer dieselben Stunden durchgehend `RS L`.
Der reine Quorum-Filter unterzeichnet die Schauerlage massiv.

---

## 2. Industrie-Standard: Neighborhood Method

### 2.1 Ebert (2008): Methodischer Rahmen

Elizabeth Ebert (Bureau of Meteorology Australia) etablierte 2008 die
**Neighborhood Method** als Standard fuer raeumliche Verifikation von
hochaufloesenden Niederschlagsvorhersagen. Kernidee:

> "Spatial neighborhood does not require strict matching between grid points
> but considers forecasts within a certain radius around a grid point as
> accurate. Various properties of the forecast within a neighborhood can
> be assessed for similarity to the observations, including the mean value,
> fractional coverage, occurrence of a forecast event sufficiently near an
> observed event, and so on."

Standardisierte Aggregationsfunktionen innerhalb des Neighborhoods:

| Funktion | Beste Anwendung |
|---|---|
| **Mean** | Stratiforme, grossraeumige Niederschlaege (Front, Warmluftadvektion) |
| **Maximum** | **Konvektive Schauer, Gewitter, lokal begrenzte Zellen** |
| **Fractional Coverage** | Verteilungsinformation (verstreut vs flaechig) |
| **Percentile (z.B. 90%)** | Kompromiss zwischen Mean und Max, robust gegen Ausreisser |

### 2.2 DWD-Operationspraxis (seit 2012)

DWD betreibt fuer COSMO-DE-EPS und ICON-D2-EPS operationelles
**Upscaling + Smoothing** auf Niederschlagsvorhersagen. Standardgroessen:

- **Box-Groesse**: 10×10 bis 25×25 Gitterpunkte (28-70 km)
- **Metriken**: Maximum, Fractional Coverage, Probability-of-Exceedance pro Schwelle
- **Schwellen**: 0.1, 1.0, 2.5, 10, 25 mm/h (WMO-Standard)

> "Upscaled probabilities refer to larger areas rather than individual grid
> points... The benefit comes from enlarging the area of reference to a 40 km
> square, which makes probabilistic forecasts more interpretable for
> forecasters. ROC areas increase linearly with window size up to 25 by 25
> grid points (70 km)."
> — Ben Bouallègue 2014, *Meteorological Applications*

Wichtig: DWD liefert immer **Maximum UND Coverage parallel**, nie einen
einzelnen aggregierten Wert.

### 2.3 ECMWF, NOAA, MAP D-PHASE

Konsensus in der internationalen Verifikations-Community:

- **ECMWF Forecast User Guide** (Sektion Convective Precipitation): probabilistische
  Behandlung, keine Mittelung.
- **NOAA HRRR / GFA**: "composite radar combines strongest echo per elevation
  into one image" — Maximum-Reduktion fuer Aviation-Produkte.
- **MAP D-PHASE Neighborhood Verification** (Schweizer Alpenraum): Maximum +
  Fractional Coverage als Standardmetriken fuer COSMO-2 und COSMO-1.

### 2.4 Aviation: TAF/METAR/AIM

ICAO Annex 3 / FAA AIM: konvektiver Niederschlag wird **probabilistisch +
worst-case** kommuniziert, nicht als raeumlicher Mittelwert.

- `PROB30 TEMPO 1216 SHRA` = 30 % Wahrscheinlichkeit fuer Schauer 12-16Z
- "Scattered showers" (`SHRA SCT`) = < 50 % Bedeckung
- "Isolated showers" = < 25 % Bedeckung

Beide Kategorien sind explizit **flugrelevant** — auch verstreute Zellen
muessen kommuniziert werden, weil Outflow und Boeen am Schauerrand
flugbeschraenkend sind.

---

## 3. Schwellenbegruendung fuer Gleitcast

### 3.1 WMO/Aviation-Intensitaetsklassen

| Intensitaet (mm/h) | WMO/Aviation-Bezeichnung | Flug-Relevanz |
|---|---|---|
| 0.00 - 0.05 | "Trace" (numerisches Rauschen) | Irrelevant |
| 0.05 - 0.20 | Drizzle / Spritzer | Sichtbar, kaum nass |
| **0.20 - 0.50** | **Light precipitation (`RS L`)** | **Schirm wird klamm, Pilot spuert es** |
| 0.50 - 2.50 | Light shower (DWD-Operational) | Schirm nass, Outflow ~5 km |
| 2.50 - 10.0 | Moderate shower | Flugabbruch |
| > 10.0 | Heavy / TS | Lebensgefahr |

### 3.2 Konfigurierbare Schwellen (`config.py`)

```python
PRECIP_SIGNIFICANT_MM = 0.2     # Peak >= 0.2 → durchlassen ohne Quorum
PRECIP_NOISE_MM       = 0.05    # Peak <  0.05 → auf 0 clipen
PRECIP_COVERAGE_QUORUM = 0.3    # Bei NOISE..SIGNIFICANT: 30%-Quorum
```

**`SIGNIFICANT_MM = 0.2`** ist bewusst niedriger als die DWD-Operationsschwelle
0.5 mm/h. Aviation-Konservatismus: bei Paragliding ist false-negative deutlich
gefaehrlicher als false-positive. Eine verpasste Schauerwarnung kann zum
nassen Schirm und Outflow im Flugfenster fuehren. Ein zu fruehzeitiger
Schauerhinweis fuehrt lediglich zu "weniger fliegen heute".

**`NOISE_MM = 0.05`** filtert reine Float-Spikes und numerische Artefakte ohne
echte physikalische Bedeutung. Werte zwischen Noise und Significant
(0.05-0.2 mm/h) sind plausibel als Drizzle interpretierbar — daher Quorum
als Fallback (mehrere RPs muessen unabhaengig melden, sonst eher
Modell-Artefakt).

**`COVERAGE_QUORUM = 0.3`** ist der alte 30%-Schwellwert, beibehalten als
Stratiform-Schutz im mittleren Wertebereich.

---

## 4. Implementierung

### 4.1 Algorithmus pro Stunde (precipitation, rain)

```python
peak = max(valid_vals)
n_wet = sum(1 for v in valid_vals if v > PRECIP_NOISE_MM)
coverage = n_wet / len(valid_vals)

if peak >= PRECIP_SIGNIFICANT_MM:
    output = peak                                    # konvektive Zelle
elif peak > PRECIP_NOISE_MM and coverage >= 0.3:
    output = peak                                    # stratiform leicht
else:
    output = 0.0                                     # Rauschen / isolierter Trace
```

`precipitation_probability` (POP) wird vereinfacht als `max()` ueber alle RPs
genommen — POP ist bereits eine Wahrscheinlichkeit, max() liefert die
hoechste regionale Schauer-Chance konservativ.

### 4.2 Coverage als neues Cache-Feld

`precipitation_coverage` (0.0-1.0) wird parallel zu `precipitation` pro Stunde
gespeichert. Es ist KEIN Open-Meteo-API-Parameter, sondern wird in
`_aggregate_regional_data` berechnet und in `_process_spot_weather` aus dem
aggregierten Source ins finale `hourly_data` uebernommen.

Anwendungen (geplant, noch nicht implementiert):
- **Decision-Engine-Tags**: `RAIN-SCATTERED` (coverage < 30 %, peak ≥ 0.2)
  vs `RAIN-WIDESPREAD` (coverage ≥ 70 %)
- **LLM-Kontext**: "lokaler Schauer 1/7 Punkte" vs "flaechig 6/7 Punkte"
- **UI-Visualisierung**: Heatmap-Marker auf Region-Karte

### 4.3 Wo

| Datei | Funktion / Zeile | Zweck |
|---|---|---|
| `config.py` | L189-217 (neue Sektion) | Schwellen-Konstanten exponiert |
| `fetch_weather.py` | `_aggregate_regional_data` L287-386 | Hybrid-Filter + Coverage-Befuellung |
| `fetch_weather.py` | `_process_spot_weather` L474-497 | Coverage ins hourly_data uebernehmen |
| `docs/REFPOINT_KONZEPT.md` | Sektion 1.3 | Operative Kurzbeschreibung |

---

## 5. Verifikation

### 5.1 Unit-Tests (manuell verifiziert Mai 2026)

| Fall | Input | Erwartet | Output |
|---|---|---|---|
| Konvektive Zelle | 1/7 RP mit 1.1 mm/h, 6 trocken | peak durchgelassen | **1.1** ✓ |
| Rauschen | 1/7 RP mit 0.03 mm/h, 6 trocken | 0 (Noise-Clip) | **0.0** ✓ |
| Stratiform leicht | 5/7 RPs mit 0.1 mm/h, 2 trocken | peak (Quorum greift) | **0.1** ✓ |
| Isolierter Trace | 1/7 RP mit 0.1 mm/h, 6 trocken | 0 (kein Quorum) | **0.0** ✓ |
| Coverage-Feld | 5/7 nass | 0.71 | **0.71** ✓ |
| Coverage trocken | 0/7 nass | 0.0 | **0.0** ✓ |

### 5.2 Erwartete Aenderungen im Live-Cache

Nach erstem Refresh mit aktiviertem Hybrid-Filter sollten bei konvektiven
Wetterlagen (Mai-September dominant) folgende Effekte messbar sein:

- **Zentrales Mittelland am 16.05.2026**: statt 2 Stunden mit precip > 0
  jetzt 6-10 Stunden (deckungsgleicher zu xc-therms `RS L`-Pattern 06-17h).
- **Stratiforme Lagen (Front, Warmsektor)**: praktisch unveraendert, weil dort
  Coverage meist > 50 % und Peak-Werte hoch.
- **Trockene Tage**: keine Aenderung, alle Werte bleiben 0.

### 5.3 Rueckschritte / Edge-Cases

- **API-Schemata**: `precipitation_coverage` ist neues Feld im Cache. Konsumenten,
  die explizit alle Feld-Keys typed parsen, koennten brechen. Aktuelle
  Konsumenten (briefing.js, meteogram.js, chat-charts.js, weather_context.py)
  iterieren ueber bekannte Keys → kein Bruch erwartet.
- **JSON-Persistenz**: Cache-File `wetterdaten.json` waechst um ~5 % durch
  zusaetzliches Feld (1 Float pro Stunde pro Spot/Region). Akzeptabel.
- **Open-Meteo-Mocks** (`data/mocks/`): muessen nicht angepasst werden, da
  Coverage post-API berechnet wird.

---

## 6. Referenzen

### 6.1 Wissenschaftliche Grundlagen

- **Ebert, E. E. (2008)** — *Fuzzy verification of high-resolution gridded
  forecasts: A review and proposed framework.* Meteorological Applications, 15(1), 51-64.
  Begruendete die Neighborhood Method als Standard.
- **Singh, V. et al. (2021)** — *Sensitivity of convective precipitation to
  model grid spacing and land-surface resolution in ICON.* Quarterly Journal
  of the Royal Meteorological Society. https://rmets.onlinelibrary.wiley.com/doi/full/10.1002/qj.4046
- **Ben Bouallègue, Z. (2014)** — *Spatial techniques applied to precipitation
  ensemble forecasts: from verification results to probabilistic products.*
  Meteorological Applications. https://rmets.onlinelibrary.wiley.com/doi/10.1002/met.1435
- **Roberts, N. M. & Lean, H. W. (2008)** — *Scale-selective verification of
  rainfall accumulations from high-resolution forecasts of convective events.*
  Monthly Weather Review, 136(1), 78-97. Definierte Fractions Skill Score (FSS).

### 6.2 Operationelle Dokumentation

- DWD ICON-D2-EPS: https://www.dwd.de/EN/research/weatherforecasting/num_modelling/04_ensemble_methods/ensemble_prediction/ensemble_prediction_en.html
- DWD ICON-D2 Aviation: https://www.dwd.de/EN/specialusers/aviation/teaser/news/39_cosmo_icon_thema.html
- ECMWF Forecast User Guide (Convective Cloud Processes): https://confluence.ecmwf.int/pages/viewpage.action?pageId=255094117
- NOAA Aviation Weather GFA: https://aviationweather.gov/gfa/help/
- FAA AIM Chapter 7 (Safety of Flight): https://www.faa.gov/air_traffic/publications/atpubs/aim_html/chap7_section_1.html

---

## Changelog

- **Mai 2026**: Migration von 30%-Quorum zu Hybrid-Filter (DWD-Standard).
  Konvektive Einzelzellen werden nicht mehr geclipt. `precipitation_coverage`
  als zusaetzliches Cache-Feld eingefuehrt. Trigger: Bug-Report 16.05.2026
  ("Zentrales Mittelland zeigt 0 Regen trotz xc-therm `RS L` ganztags").
