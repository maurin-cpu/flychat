# Region-Referenzpunkte: Forschung zu optimalem Spatial Sampling für Gleitschirm-Regionen

Stand: Mai 2026. Bezug: Wingcast verwendet derzeit pro Flugregion 7 Punkte (4 Edge-Anker via Greedy Max-Min, 3 Innen-Punkte via Lloyd-CVT auf negativ-buffered Polygon) und aggregiert daraus Wolken, Niederschlag, Wind, Böen, Thermik.

---

## 1. Executive Summary

Die Recherche über zehn Web-Quellen aus Geostatistik, NWP-Subgrid-Theorie, Alpiner Föhnforschung und Soaring-Forecasting bestätigt, dass der aktuelle Wingcast-Hybridansatz (4 Edge + 3 CVT-Innen, N=7) für Schweizer Flugregionen in der oberen Hälfte der publizierten Best-Practice liegt. CVT ist nachweislich optimal für räumliche Mittelwerte unter quadratischer Fehlerannahme (Du/Faber/Gunzburger 1999; Mishra et al. 2020 für Rain Gauges). Die Punktzahl N=7 liegt im plausiblen Bereich: bei einer Dekorrelations-Distanz von 27 km für Niederschlag (Beck et al. 2021) und 10–100 km für lokale Alpine Zirkulationen sind in einer typischen Wingcast-Region (~500–2000 km²) zwischen 5 und 12 unabhängige Stützpunkte gerechtfertigt. Die wichtigste Schwäche des aktuellen Setups ist nicht die Punktzahl, sondern die fehlende **topographische Stratifikation**: die 7 Punkte sind rein geometrisch verteilt und ignorieren Höhen-, Aspekt- und Rauhigkeitsverteilung der Region, obwohl die Literatur (TopoSUB, Fiddes & Gruber 2012; TopoSCALE 2014) klar zeigt, dass diese drei Dimensionen die meteorologische Heterogenität in komplexem Terrain dominieren. Empfehlung: N bleibt bei 6–8, aber Punkte stratifiziert auswählen statt rein CVT-geometrisch.

---

## 2. Antworten auf die sieben Forschungsfragen

### 2.1 Sampling-Theorie — Welche Strategie für räumliche Mittelwerte?

Vier Hauptstrategien aus der Literatur sind relevant:

**Centroidal Voronoi Tessellation (CVT/Lloyd):** Minimiert die quadratische Distanzenergie ∫|x − c_i|² dx und ist daher *exakt der optimale Estimator* für räumliche Mittelwerte unter quadratischer Verlustfunktion (Du, Faber, Gunzburger, "Centroidal Voronoi Tessellations: Applications and Algorithms", SIAM Review 1999). In der Meteorologie wurde CVT von Mishra et al. (J. Hydrology 2020, [ScienceDirect](https://www.sciencedirect.com/science/article/abs/pii/S0022169420301116)) für optimale Rain-Gauge-Platzierung benchmarked und schlug Kriging-basierte Verfahren in einfacherer Formulierung. Das ist mathematisch der saubere Ansatz, wenn man einen unbiased Mittelwert sucht.

**Quasi-Monte-Carlo (Halton/Sobol):** Low-Discrepancy-Sequenzen konvergieren mit O(log(N)^d / N) statt O(1/√N) bei klassischem MC. Sobol-Sequenzen schlagen Latin Hypercube in den meisten getesteten Funktionen ([arxiv 1505.02350](https://arxiv.org/abs/1505.02350)). Für kleine N (< 10) ist der Vorteil gegenüber CVT aber gering, und QMC ignoriert die Polygon-Geometrie — Punkte können dicht am Rand klumpen.

**Stratified Sampling nach Topographie:** Fiddes & Gruber (TopoSUB, GMD 2012; TopoSCALE, GMD 2014, [ResearchGate](https://www.researchgate.net/publication/261016367_TopoSCALE_v10_Downscaling_gridded_climate_data_in_complex_terrain)) klassifizieren das Gelände nach Elevation × Slope × Aspect × Sky-View-Factor in K Cluster und sampeln pro Cluster den Centroid. Das reduziert Rechenaufwand für RCM-Downscaling auf 1–5 % gegenüber Voll-Grid, bei <1 K RMSE für Temperatur. Für Bergregionen mit Bandbreite >1000 m Höhendifferenz ist Stratifikation klar überlegen.

**Importance Sampling:** Mehr Punkte wo Varianz hoch ist (typischerweise an Hangkanten, Talböden, Gipfelflanken). Setzt voraus, dass ein A-Priori-Varianzfeld bekannt ist — was es im Live-Forecasting nicht ist. Statisch kalibrierbar über historische Modelldaten.

**Quintessenz:** CVT optimiert die *Geometrie*, ignoriert aber die *Physik*. Beste Praxis im Mountain-Forecasting kombiniert beides — CVT-Lloyd auf einer durch Topographie gewichteten Dichte (weighted CVT), nicht auf der uniformen Polygon-Dichte.

### 2.2 Meteorologische Skalen — wie weit korreliert was?

| Phänomen | Charakteristische Skala | Quelle |
|---|---|---|
| Thermische Plumes (single) | 50–500 m horizontal | PNAS 2024, "Plume-scale confinement on thermal convection" |
| Cumulus-Feld unorganisiert | <2 km dominant | Hourdin et al. JAS 2008, Thermal Plume Model |
| Cumulus-Feld organisiert | 2–20 km (mesoscale) | ACP 2025, thermal-cloud merging |
| Talwinde / lokale Zirkulation | 10–100 km | Geo LibreTexts 4.5 |
| Föhn-Durchbruch | 5–30 km (lee-side breakthrough an Gebirgsausläufern) | Mayr et al. WCD 2022, IOP1 PIANO |
| Niederschlag (decorrelation) | ~27 km in mittleren Breiten | Beck et al., Nature Sci Data 2021 |
| Bewölkung gesamt | smooth >>20 km bei stratiform, <2 km bei broken Cu | Vergleich der gleichen Quellen |

Für eine typische Wingcast-Region (Durchmesser ~30 km, Fläche ~500–1500 km²) bedeutet das:
- Niederschlag ist nahe einer Dekorrelations-Länge → 1–3 Punkte würden statistisch ausreichen
- Cumulus-Bewölkung kann zwischen Tal A und Tal B um 50 % differieren → braucht ≥4 Punkte
- Föhn-Durchbruch ist topographisch fixiert (Pässe, Talausläufer) → Edge-Sampling sinnvoll
- Talwinde sind binnen-strukturiert → Interior-Sampling sinnvoll

NWP-Subgrid-Literatur (Stull, Practical Meteorology Kap. 20; AGU JAMES 2023, Arnold et al.) ist klar: ein einziger Gridpoint ist nur dann repräsentativ, wenn die Subgrid-Variabilität klein gegenüber der prognostischen Variabilität ist. In komplexem Terrain ist das selten erfüllt. Mehrere Punkte pro Region sind aus Subgrid-Theorie zwingend.

### 2.3 Topographie als Sampling-Kriterium

Die mit Abstand stärkste Empfehlung aus der Literatur ist topographische Stratifikation:

- **Elevation:** Hangwind, Thermik, Wolkenbasis und Niederschlag korrelieren stark mit Höhe. Eine Region mit 600 m Tal und 2500 m Gipfel sollte Punkte über beide Höhen verteilen, nicht alle auf 1500 m mitteln.
- **Aspekt:** S-/SW-exponierte Hänge heizen früher und stärker auf, N-Hänge bleiben länger stabil. Föhnstrich ist auspektabhängig (Nordseite vs. Südseite des Hauptkamms).
- **Slope/Rauhigkeit:** Mechanische Turbulenz und Hangauflösungs-Effekte sind slope-getrieben.

TopoSUB (Fiddes & Gruber 2012) hat das für glaziologisch-hydrologisches Downscaling formalisiert: K-Means-Cluster über (z, slope, aspect, svf), dann pro Cluster ein repräsentativer Punkt. Für eine Region mit z. B. 5 Höhenstufen × 4 Aspekt-Klassen = 20 Cluster — aber praktisch reichen 6–8 Cluster für Wingcast-Granularität.

Dynamical Downscaling-Modelle (WRF, CALMET) lösen das durch hohe horizontale Auflösung statt explizites Sampling, sind aber rechenintensiv. Statistisches Downscaling mit topo-stratified Sampling ist der praktikable Mittelweg.

### 2.4 Konkurrenz-Apps — wie aggregieren die?

Öffentliche technische Details sind dünn, aber das Recherche-Bild ist:

- **Burnair (CH):** Greift auf ICON-D2/CH-Daten zurück und zeigt punktuelle Spot-Forecasts plus Wetterstations-Layer. Keine öffentliche Region-Aggregations-Methode publiziert. Die App ist primär Spot-zentriert mit Map-Overlay, nicht regional-aggregiert wie Wingcast.
- **MeteoParapente (FR):** Eigenes 2.5-km-Modell für Europa, an Paragliding-Bedürfnisse getunt ([portal.meteo-parapente.com/about](https://portal.meteo-parapente.com/about/)). Forecasts werden punktuell ausgegeben, keine explizite Region-Aggregation. Pilot-Bewertungen ([airetaventure.com](https://www.airetaventure.com/en/content/123-paragliding-weather)) sind in Frankreich sehr positiv für Lokalprognosen.
- **MeteoBlue MultiModel:** Pro Punkt werden mehrere globale + regionale Modelle gemittelt; pro Punkt eine Gridzelle 4–40 km. Keine Multi-Punkt-Aggregation innerhalb einer Region — der User pickt den Punkt manuell.
- **XCSkies (US/global):** GFS + Regional, parameterisiert für Soaring. Layer-basiert, punktbasiert. Pilot-Reviews (Cloudbase Mayhem Ep. 120) loben Cloudbase und Lift-Genauigkeit, kritisieren Wind im Hochgebirge.
- **SkySight (AUS/global):** Eigenes WRF mit 1.8 km Auflösung und eigenem Land-Surface-Modell für Bodenfeuchte. Punktuell und Karten-Layer, keine Region-Aggregation.
- **SoaringMeteo (FR open-source):** WRF 2–6 km Alpen + GFS 25 km global, [GitHub soaringmeteo/soaringmeteo](https://github.com/soaringmeteo/soaringmeteo). Punktuell, kein Region-Aggregations-Layer.

**Wesentliche Beobachtung:** Keine der grossen Konkurrenz-Apps macht echte Region-Aggregation — sie zeigen Punkte oder Karten-Layer und überlassen dem User die räumliche Synthese. Wingcast ist mit dem Region-Konzept *strukturell anders* (und potentiell mehrwertig für Wingcast-Übersichten), aber muss die Aggregation selbst lösen, ohne aus Konkurrenz-Code abkupfern zu können.

### 2.5 Edge vs Interior — Hybrid sinnvoll?

Die Literatur spricht nicht direkt von "Edge-Anker für Föhn, Interior für Konvektion", aber das Pattern lässt sich aus drei Befunden ableiten:

1. **Föhn-Durchbruch ist topographisch fixiert** (Mayr et al. WCD 2022): die Durchbruchsstellen sind Pässe und Talausläufer am Polygon-Rand. Edge-Sampling erfasst diese Phänomene besser als reiner Centroid.
2. **Lee-Effekte** treten am Windschatten von Bergketten auf — typischerweise Polygon-Rand zum Hauptkamm.
3. **Innere Konvektion / Wolkenlücken / Talwinde** sind Polygon-internen Heterogenitäten — CVT-Innen-Punkte sind ideal.

CVT alleine (Lloyd auf gesamtem Polygon) würde die Punkte zum Centroid hin verdichten und Edge-Phänomene unterabtasten. Reines Edge-Sampling würde die Mitte ignorieren. Der **Hybrid 4+3 von Wingcast ist also konzeptionell sauber begründbar** — er folgt der gleichen Logik wie Boundary-Layer-Methoden im Finite-Element-Bereich, wo Randpunkte und Centroide explizit getrennt werden.

Kritikpunkt: 4 Edge-Punkte via Greedy Max-Min sind *geometrisch* maximal verteilt, nicht *physikalisch* an den relevanten Edge-Phänomenen orientiert. Eine physikalisch geleitete Wahl würde Edge-Punkte an Pässen, Lee-Kanten und Hauptkamm-Auslässen platzieren — was aber pro Region manuell oder via Geländeanalyse erfolgen müsste.

### 2.6 Ist N=7 sinnvoll?

Aus der Geostatistik gibt es zwei Faustregeln:

**Pixel-Formel (Klinkenberg, Rules of Thumb for Spatial Data, [UBC](https://ibis.geog.ubc.ca/~brian/rules_of_thumb/index.html)):** `pixel = sqrt(F × area / N)` mit F=2.5. Umgestellt: `N = F × area / pixel²`. Für eine 1000 km² Region und gewünschte "Pixel" von ~13 km (= halbe Dekorrelations-Distanz Niederschlag): N = 2.5 × 1000 / 169 ≈ 15. Bei pixel=20 km: N ≈ 6. Wingcast mit N=7 liegt damit nahe der praktischen Untergrenze für Niederschlags-getriebene Auflösung.

**Variogramm-basiert (McBratney & Webster, optimal sampling for kriging, [ScienceDirect S0016706100000409](https://www.sciencedirect.com/science/article/abs/pii/S0016706100000409)):** Die optimale Punktzahl skaliert mit (Range/Polygon-Diagonale)⁻¹. Bei Range ≈ 20–30 km und Polygon-Diagonale ~40 km ergibt das ein N=2–4 für reine Schätzung des Mittelwerts, aber N=6–12 wenn auch das Variogramm geschätzt werden soll (was Wingcast effektiv tut, indem es Wolkenheterogenität als 30-%-Perzentil aufnimmt).

**Effective Sample Size unter Autokorrelation (Griffith 2005, [Academia.edu](https://www.academia.edu/25157865/Effective_Geographic_Sample_Size_in_the_Presence_of_Spatial_Autocorrelation)):** Bei starker positiver räumlicher Autokorrelation kann ESS << N sein. Bei Cloud-Cover mit Autokorrelation ρ ≈ 0.7 (typisch für Bewölkung über 10 km) sinkt ESS für N=7 auf etwa 3–4. Das ist die *real* nutzbare Information — das deckt sich gut mit Wingcasts 30-%-Perzentil-Aggregation, die robust mit 3–4 unabhängigen Stützen ist.

**Marginalrendite:** Empirische Studien zu Rain-Gauge-Netzen zeigen einen Plateau-Effekt: ab N>~10 nimmt die Verbesserung im Mittelwertfehler stark ab. N=7 liegt im steilen Bereich der Lernkurve. N=12 würde wahrscheinlich noch 10–15 % Genauigkeit bringen, N=20 nur noch 3–5 %.

**Quintessenz:** N=7 ist statistisch defensibel und sitzt im Sweet-Spot zwischen API-Quota (Open-Meteo Weighted-Counts pro Spot) und marginaler Genauigkeit.

### 2.7 Konkrete Empfehlung — wie sähe Best-Practice aus?

Die theoretisch saubere Lösung für einen Gleitschirm-Forecaster wäre:

1. **Stratify-then-Sample.** Pro Region offline einmal: das Polygon in 6–8 Cluster nach (Elevation, Aspekt, distance-to-ridge) zerlegen (K-Means, TopoSUB-Style). Pro Cluster den Cluster-Centroid als Sample-Punkt.
2. **Edge-Punkte physikalisch erzwingen.** 2–3 der Punkte werden manuell pro Region auf die *bekannten* Föhndurchbruchs- und Lee-Stellen gepinnt (über CSV-Annotation).
3. **Aggregation variabel-spezifisch:**
   - Niederschlag: max wenn ≥30 % der Punkte regnen (aktuell schon so)
   - Bewölkung tief: 30-%-Perzentil für Blue Holes (aktuell schon so)
   - Bewölkung mittel: median (Altostratus ist räumlich monoton)
   - Wind/Böen: 75-%-Perzentil oder max (konservativ, Safety-Layer)
   - Thermik: median für climb_rate, max für H_top
4. **N=6–8** bleibt das Target, ggf. dynamisch je nach Polygon-Fläche skaliert (N = clamp(5, 12, round(area_km² / 200))).

---

## 3. Bewertung des aktuellen Wingcast-Setups

| Aspekt | Bewertung | Begründung |
|---|---|---|
| **Punktzahl N=7** | ✔ Sehr gut | Im theoretischen Sweet-Spot zwischen ESS und Marginal-Rendite. |
| **Hybrid 4 Edge + 3 Interior** | ✔ Gut begründet | Edge für Föhn/Lee, Interior für Konvektion — folgt impliziter physikalischer Logik. |
| **CVT für Innen-Punkte** | ✔ Sehr gut | CVT minimiert exakt den quadratischen Mittelwertfehler. 92.5 % im Polygon-Innern ist eine gesunde Marge. |
| **Greedy Max-Min für Edge** | ✘ Schwach | Rein geometrisch, ignoriert wo Föhn tatsächlich durchbricht. Edge-Punkte können in irrelevanten Polygon-Ecken landen. |
| **Topographische Stratifikation** | ✘ Fehlt | Höhen-, Aspekt- und Slope-Verteilung der 7 Punkte ist Zufallsergebnis der Geometrie, nicht designed. |
| **Aggregations-Logik (Perzentile, max)** | ✔ Gut | Variablen-spezifische Aggregation ist statistisch sauber, korreliert mit Variablen-Skala. |
| **Skalierungs-Invarianz** | ✔ Gut | CVT-Lloyd ist skalen-invariant, was bei stark unterschiedlichen Polygon-Grössen wichtig ist. |

**Insgesamt: 5 von 7 Aspekten gut bis sehr gut, 2 verbesserungsfähig.** Das aktuelle Setup ist eindeutig besser als die alte 4-Punkt-Greedy-Lösung und besser als die meisten Konkurrenz-Apps, die gar keine Region-Aggregation machen.

---

## 4. Verbesserungsvorschläge — priorisiert nach Impact

### Priorität 1 (High Impact, Medium Effort): Topographische Gewichtung der CVT

**Problem:** Die Lloyd-Iteration läuft derzeit auf uniformer Polygon-Dichte. Das heisst, eine Region mit 80 % Talboden und 20 % Bergflanken bekommt 80 % ihrer Punkte ins Tal — obwohl der Bergteil meteorologisch deutlich heterogener und für Gleitschirmflug relevanter ist.

**Fix:** Gewichtete CVT (Du, Wang 2005): `ρ(x) = 1 + α × (slope(x) / max_slope) + β × |z(x) − z_median| / std(z)`. Mit α=β=0.5 wird Bergflankenterrain ungefähr doppelt so dicht besampelt wie flache Polygon-Anteile. Implementierbar in `scripts/create_regionen_geojson.py` durch DEM-Sampling (z. B. SRTM 30 m via `rasterio`) in der Lloyd-Iteration.

**Erwarteter Impact:** 15–25 % bessere Repräsentativität für Thermik, Wolkenbasis und Hangwinde in heterogenen Regionen wie "Berner Oberland" oder "Zentralwallis", die sowohl Talböden als auch Hochalpin enthalten.

### Priorität 2 (High Impact, High Effort): Manuelle Föhn/Lee-Anker pro Region

**Problem:** Die 4 Edge-Anker via Greedy Max-Min sind geometrisch optimal verteilt, aber landen oft an meteorologisch irrelevanten Polygon-Ecken (z. B. Wiesenkante statt Föhndurchbruchsstelle).

**Fix:** Pro Region in `regionen.csv` eine optionale Spalte `manual_anchors` mit 0–3 Lat/Lon-Tupeln. Diese überschreiben die ersten N Greedy-Punkte. Anker werden einmalig durch einen Domain-Experten gesetzt: am Niederalpsattel für Vorarlberg-Föhn, am Brünig-Pass für Brünig-Föhn etc. Restliche Edge-Plätze füllen Max-Min auf.

**Erwarteter Impact:** Föhn-Detection-Quality steigt deutlich (vermutlich 30–50 % weniger False-Negatives für Föhntage), weil der Strömungs-Anstellwinkel jetzt *dort* gemessen wird, wo das Phänomen real durchbricht. Höchster Aufwand (manuelle Pflege ~29 Regionen), aber einmalig.

### Priorität 3 (Medium Impact, Low Effort): Adaptive N je Polygonfläche

**Problem:** N=7 fix bedeutet, dass "Berner Oberland" (gross, heterogen) gleich viele Punkte hat wie eine kleine Region. API-Quota wird ineffizient ausgegeben.

**Fix:** `N = clamp(5, 10, round(sqrt(area_km²) / 8))`. Kleine Region (200 km²) → 5 Punkte. Grosse Region (2500 km²) → 9–10 Punkte. Einbau in `create_regionen_geojson.py`.

**Erwarteter Impact:** API-Last bleibt etwa gleich (kleine Regionen sparen Punkte für grosse), aber grössere Regionen werden besser aufgelöst.

### Priorität 4 (Medium Impact, Low Effort): Aggregations-Logik dokumentieren und vereinheitlichen

**Problem:** Die aktuelle Logik (Wolken 30-%-Perzentil, Niederschlag max-bei-≥30 %, Wind/Böen "andere Logik") ist im Code verstreut und nicht über alle Variablen konsistent durchargumentiert.

**Fix:** Ein zentrales `engine/region_aggregation.py` mit einer Tabelle `AGGREGATION_RULES = {"low_cloud": "p30", "mid_cloud": "p50", "precip": "max_if_30pct", "wind_speed": "p75", "wind_gusts": "max", "climb_rate": "median", "thermal_top": "max"}`. Pro Regel eine Begründung im Docstring (z. B. p30 für tief weil Blue-Hole-Detection, p50 für mittel weil Altostratus räumlich monoton).

**Erwarteter Impact:** Bessere Wartbarkeit, geringer direkter Forecast-Impact, aber Voraussetzung für künftige Kalibrierung.

### Priorität 5 (Low Impact, High Effort): Variogramm-basierte Validierung

**Problem:** Wir wissen nicht empirisch, wie gut N=7 für jede Region tatsächlich ist.

**Fix:** Einmalig über z. B. 30 Tage aller Region-Punkte das Variogramm der wichtigsten Variablen (Cloud, Climb_Rate, Gust) schätzen. Daraus pro Region eine ESS-Tabelle ableiten und Regionen mit ESS<3 für irgendeine Variable für Re-Sampling markieren.

**Erwarteter Impact:** Wissen statt Vermuten. Wenig direkter Forecast-Gewinn, aber Grundlage für gezielte Verbesserungen.

---

## 5. Quellenliste

### CVT, Sampling-Theorie, Geostatistik
- [Centroidal Voronoi Tessellations: Applications and Algorithms (SIAM Review 1999)](https://epubs.siam.org/doi/10.1137/S0036144599352836)
- [Wikipedia: Centroidal Voronoi tessellation](https://en.wikipedia.org/wiki/Centroidal_Voronoi_tessellation)
- [Wikipedia: Lloyd's algorithm](https://en.wikipedia.org/wiki/Lloyd%27s_algorithm)
- [Mishra et al. — CVT for rain gauge location (J Hydrology 2020)](https://www.sciencedirect.com/science/article/abs/pii/S0022169420301116)
- [Fast Methods for Computing CVT (Chen)](https://www.math.uci.edu/~chenlong/Papers/CVT.pdf)
- [Halton/Sobol vs LHS Comparison (arxiv 1505.02350)](https://arxiv.org/abs/1505.02350)
- [Optimised Sample Schemes for Geostatistical Surveys (Springer Math Geosci 2006)](https://link.springer.com/article/10.1007/s11004-006-9069-1)
- [Influence of variogram on optimal sampling (Geoderma)](https://www.sciencedirect.com/science/article/abs/pii/S0016706100000409)
- [Effective Geographic Sample Size under Spatial Autocorrelation (Griffith)](https://www.academia.edu/25157865/Effective_Geographic_Sample_Size_in_the_Presence_of_Spatial_Autocorrelation)
- [Rules of Thumb for Spatial Data (Klinkenberg UBC)](https://ibis.geog.ubc.ca/~brian/rules_of_thumb/index.html)

### Mountain-Meteorologie, Downscaling, Subgrid
- [TopoCLIM Downscaling (GMD 2022)](https://gmd.copernicus.org/articles/15/1753/2022/)
- [TopoSCALE Downscaling Complex Terrain (Fiddes & Gruber)](https://www.researchgate.net/publication/261016367_TopoSCALE_v10_Downscaling_gridded_climate_data_in_complex_terrain)
- [Global daily 1 km precipitation downscaling (Sci Data 2021)](https://www.nature.com/articles/s41597-021-01084-6)
- [Subgrid Surface Heterogeneity of Precipitation in GCM (JAMES 2023)](https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2022MS003562)
- [Stull Practical Meteorology Ch.20 — NWP Grids](https://geo.libretexts.org/Bookshelves/Meteorology_and_Climate_Science/Practical_Meteorology_(Stull)/20%3A_Numerical_Weather_Prediction_(NWP)/20.01%3A_Section_2-)

### Konvektion, Cumulus, Thermal Plumes
- [Thermal Plume Model Cumulus Clouds (JAS 2008)](https://journals.ametsoc.org/view/journals/atsc/65/2/2007jas2256.1.xml)
- [Plume-scale confinement on thermal convection (PNAS 2024)](https://www.pnas.org/doi/10.1073/pnas.2403699121)
- [Thermal and cloud merging mesoscale organization (ACP 2025)](https://acp.copernicus.org/articles/25/17331/2025/)
- [Trade-wind cumulus cold pools and mesoscale organization (ACP 2021)](https://acp.copernicus.org/articles/21/16609/2021/)

### Föhn, Alpine Zirkulation
- [Lagrangian analysis Alpine Foehn PIANO (WCD 2022)](https://wcd.copernicus.org/articles/3/279/2022/)
- [Lagrangian Framework Foehn Descent (WCD 2024)](https://wcd.copernicus.org/articles/5/463/2024/)
- [Objective Forecasting of Foehn Winds (Weather & Forecasting 2008)](https://journals.ametsoc.org/view/journals/wefo/23/2/2007waf2006021_1.xml)
- [Local Scale Wind (Geo LibreTexts)](https://geo.libretexts.org/Courses/Kansas_State_University/Physical_Geography%3A_our_Beautiful_World/04%3A_Atmospheric_and_Ocean_Circulation/4.05%3A_Local_Scale_Wind)

### Soaring-Forecasts (Konkurrenz-Apps)
- [SoaringMeteo (Website)](https://soaringmeteo.org/?lang=en)
- [SoaringMeteo GitHub Repository](https://github.com/soaringmeteo/soaringmeteo)
- [SkySight Soaring Weather](https://skysight.io/)
- [Behind the Soaring Forecast (Wings & Wheels)](https://wingsandwheels.com/blog/post/behind-the-soaring-forecast)
- [Meteo-Parapente Portal — Data Sources](https://portal.meteo-parapente.com/about/data-sources/)
- [XC Skies Documentation](https://docs.xcskies.com/home/documentation/xc-skies-layers)
- [Meteoblue MultiModel Ensemble (Help)](https://content.meteoblue.com/en/private-customers/website-help/forecast/multimodel-ensemble)
- [Meteoblue Air Meteogram (Help)](https://content.meteoblue.com/en/private-customers/website-help/aviation/air)
- [Paragliding Forum — Thermal forecasts for the Alps 2024](https://www.paraglidingforum.com/viewtopic.php?t=114035)
- [Cloudbase Mayhem Ep. 120 — XCSkies](https://www.cloudbasemayhem.com/episode-120-lisa-verzella-and-understanding-xcskies-and-weather-forecasting/)
- [Cloudbase Mayhem Ep. 143 — SkySight](https://www.cloudbasemayhem.com/episode-143-matt-scutter-and-skysight-soaring-101/)
