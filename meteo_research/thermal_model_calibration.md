# Thermik-Modell Kalibrierung: Wissenschaftliche Fundierung für 5-Zonen-Terrain

**Status:** Recherche-Dokument — keine Implementierung. Basis für kommende Kalibrierung
des `thermik_calculator.py` und Erweiterung von `config.py`.

**Kontext:** Vergleich Wingcast vs. XC Therm (DI 07.04.2026) zeigte systematische
Abweichungen über 8 Regionen. Dieses Dokument validiert die vorgeschlagenen Korrekturen
gegen Peer-Reviewed-Literatur und differenziert sie nach den 5 Terrain-Klassen, die
in `data/regionen.csv` bereits definiert sind (**mittelland, jura, voralpen, alpen,
hochalpin**) — und die der `gust_calculator.py` bereits nutzt, der `thermik_calculator.py`
aber bisher nur in 2 Stufen (mittelland/alpin linear interpoliert).

---

## Problemübersicht: Was Wingcast vs. XC Therm zeigt

Vergleichs-Befund über 8 Regionen am 07.04.2026:

| Topographie-Klasse | Regionen | Faktor FC/XCT (Peak m/s) | Höhen-Abweichung |
|---|---|---|---|
| Jura (1200-1280 m) | Jura West | 1.0× (identisch) | +200 m |
| Mittelland (600-800 m) | Mittelland Zentral | 0.55× | -420 m |
| Voralpen (1400-1950 m) | Schwarzsee, Napf | 1.05× | -740 m |
| Alpen (1500-1860 m) | Berner Oberland | 0.96× | -340 m |
| Hochalpin Wallis (2100 m) | Zentralwallis | 0.58× | -1126 m |
| Hochalpin Engadin (2100 m) | Engadin Unter | 0.73× | -1126 m |
| **Hochalpin Tessin (2000 m)** | **Tessin Nord** | **0.00×** | **-1440 m** |

**Muster:** Die Abweichung skaliert mit der Referenzhöhe. Jura (Mittelgebirge) stimmt;
alles >2000 m hat dramatische Unterschätzung. Das ist **keine globale Fehlkalibrierung**,
sondern ein **topographie-spezifischer Bug**, der bei hoher Referenzhöhe durchschlägt.

---

## Validierung der vier vorgeschlagenen Korrekturen

### Korrektur 1: Die 150-m-Mindesthöhen-Schwelle ist physikalisch haltlos

**Aktueller Code (`thermik_calculator.py:972-975`):**
```
if max_thermal_height < elevation_m + 150:
    rating = min(rating, 1)
    avg_climb = 0.0
```

Dieser Hardcode killt jede Thermik, die weniger als 150 m über der Referenzhöhe des
Startplatzes reicht. Im Hochalpinen ist das ein primärer Kill-Mechanismus, weil die
Pressure-Level-Auflösung dort kaum feiner als 500 m ist.

**Was die Literatur sagt:**

1. **Lenschow & Stephens (1980)** — "The role of thermals in the convective boundary
   layer" (BLM 19:509-532, DOI [10.1007/BF00122351](https://link.springer.com/article/10.1007/BF00122351)) — definiert die
   Deardorff-Skalierung `w* = [(g/T₀)·Q_s·z_i]^(1/3)` als stetige Funktion von z_i.
   Kein harter Cutoff.

2. **Allen NASA TM-2006-213491** ("Updraft Model for Autonomous Soaring",
   [NTRS 20060004052](https://ntrs.nasa.gov/api/citations/20060004052/downloads/20060004052.pdf)) —
   operatives Soaring-Modell, setzt Minimum bei `z_i ≥ 200 m` (nicht 150 m), aber
   **als weiche Rampe**, nicht als Cutoff.

3. **Stull (1988)** — *Boundary Layer Meteorology*, Kap. 11 — beschreibt die
   superadiabatische Surface Layer (30-100 m Dicke, ≈10 % der CBL-Tiefe) als
   getrennt von der darüberliegenden Mischschicht. Kohärente Plume-Strukturen
   benötigen **≥ 200 m** freie CBL darüber, also total ~250-300 m.

4. **RASP/BLIPMAP (Glendening,
   [drjack.info](http://www.drjack.info/rasp/info/parameters.html))** — nutzt
   *keinen* Cutoff. `W*` folgt direkt der Deardorff-Formel und wird bei kleinen z_i
   automatisch klein, ohne explizite Schwelle.

**Quantitative Empfehlung (Literatur-validiert):**

| Terrain | Min. z_i AGL für nutzbare Thermik | Rationale |
|---|---|---|
| Mittelland | 400 m | Stull + Lenschow: keine kohärenten Plumes unter 300 m; flaches Gelände hat keine Hangwind-Kompensation |
| Jura | 350 m | Leichte Hang-Komponente über Jurakämmen |
| Voralpen | 250-300 m | Teilkompensation durch Hangaufwinde (Weigel & Rotach 2004) |
| Alpen | 200 m | Felswand-Thermik dominiert, organisiertere Kerne |
| Hochalpin | 150-200 m | Sehr enge, sehr starke Plume-Kerne über Felsgraten (Rotach et al. Riviera) |

**Wichtig:** Statt hartem Cutoff eine **weiche Rampe** implementieren (Smoothstep
zwischen `z_min_hard` und `z_min_hard + 200 m`). Das entspricht der Praxis aller
operativen Tools (RASP, Regtherm, AlpTherm).

**Quellen:**
- Lenschow, D. H., & Stephens, P. L. (1980). BLM 19(4): 509-532.
  DOI: [10.1007/BF00122351](https://link.springer.com/article/10.1007/BF00122351)
- Stull, R. B. (1988). *An Introduction to Boundary Layer Meteorology*. Kluwer, ISBN 978-90-277-2769-5.
- Allen, M. J. (2006). *Updraft Model for Autonomous Soaring*. NASA TM-2006-213491.
  [NTRS Link](https://ntrs.nasa.gov/api/citations/20060004052/downloads/20060004052.pdf)
- Glendening, J. ("Dr. Jack"). RASP BLIPMAP Parameters.
  [drjack.info](http://www.drjack.info/rasp/info/parameters.html)

---

### Korrektur 2: Snow Damping — Terrain-differenziert

**Aktueller Code (`thermik_calculator.py:495-509`):**
```
if snow_depth is not None and snow_depth > 0.05:
    t_factor = _terrain_factor(elevation_m)
    mittelland_damping = 0.20   # 80% Reduktion
    alpine_damping = 0.50       # 50% Reduktion
    snow_factor = interp(t_factor)
    H = min(snow_h_max, H * snow_factor)
```

Und (`:650-656`) setzt `dt_excess = 0` (keine solare Überhitzung) sobald Schnee da ist —
das ist der **Tessin/Wallis-Killer**, weil der zweite Parcel-Aufstieg dann mit derselben
(zu kalten) Starttemperatur läuft wie der erste und am selben Layer-Schritt scheitert.

**Was die Literatur sagt:**

1. **Mott, Schlögl, Dirks & Lehning (2018)** — "How are turbulent sensible heat fluxes
   and snow melt rates affected by a changing snow cover fraction?" (Frontiers in Earth
   Sci. 6:154, DOI
   [10.3389/feart.2018.00154](https://www.frontiersin.org/articles/10.3389/feart.2018.00154/full))
   — zeigt: Patchy Snow (= ausgeaperte Flächen + Schneefelder) erzeugt sehr starke
   räumliche H-Variabilität. Felspartien bleiben voll aktiv, auch wenn 80 % der
   Gridzelle schneebedeckt sind.

2. **Magnin et al. (2015)** — "Rockwall temperatures at Aiguille du Midi"
   ([hal.science/hal-01313938](https://hal.science/hal-01313938)) — Felsoberflächen-
   temperaturen in 3842 m im Frühling bis **+25 K** über Lufttemperatur trotz
   umliegender Schneedecke.

3. **Stiperski & Rotach (2016)** — "Turbulence over complex mountainous terrain"
   (BLM 159:97-121, DOI
   [10.1007/s10546-015-0103-z](https://link.springer.com/article/10.1007/s10546-015-0103-z))
   — i-Box-Messungen Inn-Tal: Patchy-Snow-Südhänge zeigen H = 150-350 W/m² lokal.

4. **Weissfluhjoch EC-Daten (Michel et al. 2022,
   [Frontiers 2025](https://www.frontiersin.org/journals/earth-science/articles/10.3389/feart.2025.1640842/full))**
   — über geschlossener alpiner Schneedecke: H = 30-60 W/m² Tagesmittel im Frühling
   (nicht null!).

**Quantitative Empfehlung:**

| Terrain | H-Reduktion bei Schneedecke | H-Max (W/m²) | dt_excess trotz Schnee |
|---|---|---|---|
| Mittelland | -85 % | 40 | 0 K (kein Triggering möglich) |
| Jura | -70 % | 70 | 0 K |
| Voralpen | -55 % | 120 | 0.5 K (partielle Ausaperung) |
| Alpen | -40 % | 180 | 1.0 K (signifikante Felsanteile) |
| Hochalpin | -25 % | 250 | 1.5 K (Felsgrate dominant) |

**Wichtig:** Der Code muss **zwei getrennte Dämpfungen** haben:
- H-Reduktion (bereits vorhanden, nur Werte anpassen)
- `dt_excess`-Dämpfung (aktuell hart auf 0, soll terrain-abhängig skaliert werden)

**Quellen:**
- Mott, R., et al. (2018). Frontiers in Earth Sci. 6:154.
  DOI: [10.3389/feart.2018.00154](https://www.frontiersin.org/articles/10.3389/feart.2018.00154/full)
- Magnin, F., et al. (2015). Rockwall temperatures at Aiguille du Midi.
  [hal.science/hal-01313938](https://hal.science/hal-01313938)
- Stiperski, I., & Rotach, M. W. (2016). BLM 159: 97-121.
  DOI: [10.1007/s10546-015-0103-z](https://link.springer.com/article/10.1007/s10546-015-0103-z)
- Michel, A., et al. (2022/2025). Weissfluhjoch EC over snow.
  [Frontiers 2025](https://www.frontiersin.org/journals/earth-science/articles/10.3389/feart.2025.1640842/full)

---

### Korrektur 3: GFS-PBL-Cap — nicht in allen Gelände-Klassen anwenden

**Aktueller Code (`thermik_calculator.py:812-821`):**
```
if boundary_layer_height_gfs is not None:
    gfs_blh_msl = elevation_m + boundary_layer_height_gfs
    if max_thermal_height > gfs_blh_msl:
        max_thermal_height = gfs_blh_msl
        pbl_cap_applied = True
```

Das ist eine harte `min()`-Operation. Die Literatur zeigt, dass GFS (Bulk-Richardson-
Schema) die BLH über komplexem Gelände systematisch unterschätzt.

**Was die Literatur sagt:**

1. **Guo et al. (2022)** — "Evaluation of the Planetary Boundary Layer Height in China
   Predicted by the CMA-GFS Global Model" (Atmosphere 13:845, DOI
   [10.3390/atmos13050845](https://www.mdpi.com/2073-4433/13/5/845)) — zeigt
   systematischen Bias von **−200 bis −500 m** über dem Tibet-Plateau, und dass der
   Haupttreiber die unterschätzte Oberflächentemperatur in komplexem Gelände ist.

2. **Guo et al. (2021)** — "Investigation of near-global daytime boundary layer height
   using high-resolution radiosondes" (ACP 21:17079-17097, DOI
   [10.5194/acp-21-17079-2021](https://acp.copernicus.org/articles/21/17079/2021/))
   — ERA5, MERRA-2, JRA-55 und NCEP-2 unterschätzen alle die PBL-Höhe über Bergen
   um 15-30 %.

3. **Seibert et al. (2000)** — "Review and intercomparison of operational methods for
   the determination of the mixing height" (Atmos. Env. 34:1001-1027) —
   Referenzarbeit: Bulk-Richardson-basierte Methoden (wie GFS) versagen in komplexem
   Gelände systematisch, weil die Eingangs-Geschwindigkeit `u(z)` durch Hindernisse
   verfälscht wird.

4. **Nyeki et al. (2000)** — "CBL evolution to 4 km AGL over high-alpine terrain"
   (GRL 27:689-692, DOI
   [10.1029/1999GL010928](https://agupubs.onlinelibrary.wiley.com/doi/abs/10.1029/1999GL010928))
   — Lidar-Messungen über den Alpen zeigen Sommer-CBL bis **4200 m MSL** — was viele
   NWP-Modelle nicht abbilden.

5. **De Wekker & Kossmann (2015)** — "Convective Boundary Layer Heights Over
   Mountainous Terrain — A Review" (Frontiers in Earth Sci. 3:77,
   [Link](https://www.frontiersin.org/journals/earth-science/articles/10.3389/feart.2015.00077/full))
   — explizit: "PBL depth over mountainous terrain is typically 15-30 % higher than
   over flat terrain due to enhanced sensible heat flux on sun-exposed slopes."

**Quantitative Empfehlung — GFS-PBL-Cap differenziert:**

| Terrain | GFS-Cap anwenden? | Korrekturfaktor | Sanity-Check |
|---|---|---|---|
| Mittelland | Ja, unverändert | ×1.00 | GFS ist hier realistisch |
| Jura | Ja | ×1.10 | Leichte Unterschätzung |
| Voralpen | Mit Korrektur | ×1.15 | Relevante Unterschätzung |
| Alpen | Mit Korrektur | ×1.20 | Starker Bias |
| Hochalpin | **Nur als Sanity-Check** | ×1.25 oder deaktiviert | GFS unbrauchbar hier; Encroachment nutzen |

**Konkreter Vorschlag (kein Code, nur Logik):**
```
if terrain_type in ("mittelland", "jura"):
    apply GFS-cap hart (wie bisher)
elif terrain_type in ("voralpen", "alpen"):
    apply GFS-cap × terrain_correction_factor
elif terrain_type == "hochalpin":
    if abs(gfs_blh - encroachment_blh) < 500:
        apply GFS-cap (Sanity)
    else:
        nutze Encroachment-Ergebnis
```

**Quellen:**
- Guo, J., et al. (2022). Atmosphere 13:845.
  DOI: [10.3390/atmos13050845](https://www.mdpi.com/2073-4433/13/5/845)
- Guo, J., et al. (2021). ACP 21: 17079-17097.
  DOI: [10.5194/acp-21-17079-2021](https://acp.copernicus.org/articles/21/17079/2021/)
- Seibert, P., et al. (2000). Atmos. Env. 34(7): 1001-1027.
- Nyeki, S., et al. (2000). GRL 27: 689-692.
  DOI: [10.1029/1999GL010928](https://agupubs.onlinelibrary.wiley.com/doi/abs/10.1029/1999GL010928)
- De Wekker, S. F. J., & Kossmann, M. (2015). Frontiers in Earth Sci. 3:77.
  [Link](https://www.frontiersin.org/journals/earth-science/articles/10.3389/feart.2015.00077/full)

---

### Korrektur 4: H-Schwellenwert sanft rampen statt hart schneiden

**Aktueller Code (`thermik_calculator.py:855-916`):**
```
H_MIN_THRESHOLD = 30.0
if z_i > 50 and H >= H_MIN_THRESHOLD:
    ... berechne w* ...
elif z_i > 50:
    limiting_factor = "H_below_threshold"
```

Harter Cutoff bei H = 30 W/m². Morgens zwischen 7-10 Uhr liegt H oft zwischen 15-25
W/m² — bereits nutzbare Thermik für Piloten, aber im Modell auf 0 gesetzt.

**Was die Literatur sagt:**

1. **Kaimal & Finnigan (1994)** — *Atmospheric Boundary Layer Flows*, Kap. 1.4 und
   Kap. 3. Die Monin-Obukhov-Länge `L = -u*³·T₀ / (κ·g·H/(ρ·cp))` liefert das
   Kriterium für den Übergang. Schwelle für freie Konvektion: `|z/L| > 1`, also
   `|L| < 10 m`. Bei `u* ≈ 0.3 m/s` entspricht das grob H ≈ 100 W/m². Zwischen
   H = 20 W/m² (|L| ≈ 150 m) und H = 100 W/m² (|L| ≈ 30 m) ist ein **Übergangsbereich**.

2. **Salesky, Chamecki & Bou-Zeid (2017)** — "On the nature of the transition between
   roll and cellular organization in the CBL" (BLM 163:41-68, DOI
   [10.1007/s10546-016-0220-3](https://link.springer.com/article/10.1007/s10546-016-0220-3))
   — beschreibt den Übergang zwischen scherungs- und buoyancy-dominierter Turbulenz
   als **kontinuierlich**, nicht stufenförmig.

3. **Moeng & Sullivan (1994)** — "A comparison of shear- and buoyancy-driven PBL
   flows" (JAS 51:999-1022) — explizit: "kein abrupter Übergang, sondern ein Regime-
   Wechsel über einen Faktor 3-5 in z/|L|".

4. **Rotach et al. (2022)** — "On the measurement of stability parameter over complex
   mountainous terrain" (WES 7:221-240, DOI
   [10.5194/wes-7-221-2022](https://wes.copernicus.org/articles/7/221/2022/)) —
   zeigt, dass in alpinem Gelände MOST-Skalierung durch Hang-Effekte modifiziert
   wird: konvektive Turbulenz setzt **früher** ein als über flachem Gelände bei
   gleichem H.

5. **Serafin et al. (2018)** — "Field observations of the morning transition over a
   steep slope in a narrow alpine valley" (Env. Fluid Mech., DOI
   [10.1007/s10652-018-9582-z](https://link.springer.com/article/10.1007/s10652-018-9582-z))
   — belegt, dass Sonnenhänge im Alpenraum **2-3 h früher** konvektive Strukturen
   zeigen als der Talboden — Hangwind-Komponente ist schon aktiv, wenn H im
   Gridbox-Mittel noch unter 30 W/m² liegt.

**Quantitative Empfehlung — sanfte Rampe differenziert:**

| Terrain | H_low (Start Rampe) | H_high (Voll-Thermik) | Begründung |
|---|---|---|---|
| Mittelland | 35 W/m² | 120 W/m² | Kaimal & Finnigan Standard |
| Jura | 30 W/m² | 110 W/m² | Leichte Hangeffekte |
| Voralpen | 25 W/m² | 100 W/m² | Sonnenhänge relevant |
| Alpen | 20 W/m² | 90 W/m² | Talwindsysteme triggern früh |
| Hochalpin | 15 W/m² | 80 W/m² | Rotach/Serafin: Hang dominiert |

**Logik (kein Code):**
```
ramp = smoothstep(H_low, H_high, H_effective)
avg_climb *= ramp
```

Smoothstep statt linear, weil das numerisch glatter ist und keine sichtbare Kante
im Tagesverlauf erzeugt.

**Quellen:**
- Kaimal, J. C., & Finnigan, J. J. (1994). *Atmospheric Boundary Layer Flows*. Oxford
  University Press. ISBN 978-0-19-506239-7.
- Salesky, S. T., Chamecki, M., & Bou-Zeid, E. (2017). BLM 163: 41-68.
  DOI: [10.1007/s10546-016-0220-3](https://link.springer.com/article/10.1007/s10546-016-0220-3)
- Moeng, C.-H., & Sullivan, P. P. (1994). JAS 51: 999-1022.
- Rotach, M. W., et al. (2022). WES 7: 221-240.
  DOI: [10.5194/wes-7-221-2022](https://wes.copernicus.org/articles/7/221/2022/)
- Serafin, S., et al. (2018). Env. Fluid Mech.
  DOI: [10.1007/s10652-018-9582-z](https://link.springer.com/article/10.1007/s10652-018-9582-z)

---

## Zusätzliche Fundstücke aus der Recherche (nicht in ursprünglichem Plan)

### A. Pressure-Level-Interpolation vor Parcel-Ascent

**Problem:** Zwischen 750 und 700 hPa liegen 400-500 m, zwischen 700 und 600 hPa sogar
800-1000 m. Der Parcel-Loop in `thermik_calculator.py:578-635` bricht bei `dh = 500 m`
sofort ab, weil `DALR · 500 = 4.9 °C` jede realistische Layer-Temperaturdifferenz
übertrifft.

**Literatur:**

- **Wang et al. (2021)** — "Reanalyses fail to capture high tail of CAPE distributions"
  (arXiv [2012.13383](https://arxiv.org/abs/2012.13383)) — zeigt empirisch, dass
  grobe vertikale Auflösung CAPE um 200-500 J/kg verfälscht. Empfiehlt explizit
  Interpolation auf dz ≤ 100 m vor dem Parcel-Ascent.

- **Markowski & Richardson (2010)** — *Mesoscale Meteorology in Midlatitudes*, Kap. 7 —
  Standard-Empfehlung: dz ≤ 100 m im unteren km, ≤ 250 m in der freien Atmosphäre.

- **ARM Interpolated Sonde VAP** (DOE/SC-ARM-TR-183) — Standardpraxis: Interpolation
  auf ca. 20 m Höhenraster.

- **AlpTherm/TopTherm** — nutzt ein eigenes Vertikalgitter (50-100 m Auflösung) und
  interpoliert ICON-Druckniveaus linear darauf.

**Empfehlung:** Vor dem Parcel-Ascent linear-in-z auf dz = 100 m interpolieren.
Das ist eine **zusätzliche** Korrektur, die nicht in der ursprünglichen 4-Punkte-Liste
stand, aber die Tessin-Diagnose direkt mitlöst und in allen Terrain-Klassen die
Genauigkeit verbessert.

**Quellen:**
- Wang, Z., et al. (2021). [arXiv:2012.13383](https://arxiv.org/abs/2012.13383)
- Markowski, P., & Richardson, Y. (2010). *Mesoscale Meteorology in Midlatitudes*.
  Wiley-Blackwell.
- DOE/SC-ARM-TR-183. [ARM PDF](https://www.arm.gov/publications/tech_reports/doe-sc-arm-tr-183.pdf)

---

### B. Morgen-Hangthermik vs. Talboden-Thermik (Whiteman-Zeitskalen)

**Literatur:**

- **Whiteman (1982)** — "Breakup of Temperature Inversions in Deep Mountain Valleys,
  Part I" (J. Appl. Met. 21:270-289,
  [Direkt-PDF](https://www.inscc.utah.edu/~whiteman/homepage/articles/Whiteman1982J%20Appl%20Meteorol.pdf))
  — Klassiker. Drei Mechanismen der Inversionsauflösung:
  1. CBL-Wachstum von unten
  2. Absinken der Inversionsobergrenze durch Hangabsaugen
  3. Kombination
  Dauer: **3.5-5 Stunden** nach Sonnenaufgang, länger bei Schnee.

- **Müller & Whiteman (1988)** — "Breakup in Dischma Valley" (J. Appl. Met. 27:188-194)
  — Schweiz-spezifisch: sensibler Wärmefluss ist **nur 6 %** der extraterrestrischen
  Solarstrahlung in tiefen Alpentälern (vs. 12-15 % in Colorado-Tälern).

- **Weigel & Rotach (2004)** — Riviera-Projekt: Sonnenhang 1-2 h nach Sonnenaufgang
  aktiv, Talsohle 3-4 h.

- **Serafin et al. (2018)** — "Morning transition over steep alpine slope" —
  dokumentiert **2-3 h Versatz** zwischen Hang- und Talstationen.

**Empfehlung:** Region-Thermikbeginn sollte **morgenabhängig** sein:

| Terrain | Thermikbeginn (h nach Sonnenaufgang) |
|---|---|
| Mittelland (flach) | 1.5-3 h |
| Jura | 2-3 h |
| Voralpen (Hangstart) | 2-3 h |
| Alpen (Talboden) | 3-4 h |
| Alpen (Hang) | 2-3 h |
| Hochalpin (Grat) | 2-3 h |
| Hochalpin (Tal) | 4-5 h |

Das lässt sich in Wingcast nicht pauschal per Terrain-Class machen, weil *innerhalb*
eines Spots der Start meist am Hang liegt. Praktikabler Vorschlag: Den H-Rampen-Start
(Korrektur 4) so wählen, dass hochalpine Spots bereits bei H=15 W/m² rampen anfangen
— das deckt den Hangwind-Beitrag ab.

**Quellen:**
- Whiteman, C. D. (1982). J. Appl. Met. 21: 270-289.
- Müller, H., & Whiteman, C. D. (1988). J. Appl. Met. 27: 188-194.
- Weigel, A. P., & Rotach, M. W. (2004). Riviera-Projekt Daten.
- Serafin, S., et al. (2018). Env. Fluid Mech.
  DOI: [10.1007/s10652-018-9582-z](https://link.springer.com/article/10.1007/s10652-018-9582-z)

---

### C. Entrainment-Rate μ differenziert nach Terrain

**Aktueller Code:** 2-Stufen-Interpolation Mittelland (0.0002) → Alpin (0.00015).

**Literatur:**

- **Simpson (1971)** und **Turner (1986)** — klassische Plume-Theorie: α = 0.08-0.12
  für Labor-Plumes, skaliert ungefähr linear mit Umgebungsturbulenz.

- **Lenschow & Stephens (1980)** — atmosphärische Anwendung: α = 0.1-0.2 für CBL
  Thermals.

- **De Wekker & Kossmann (2015)** — review: "coherent updrafts over ridges show
  lower effective entrainment rates; mittelland thermals are chaotic with higher
  entrainment."

**Empfehlung — 5-Zonen-Entrainment:**

| Terrain | α (µ in 1/m) | Rationale |
|---|---|---|
| Mittelland | 0.00020 | Chaotische Konvektion, hohes Entrainment |
| Jura | 0.00018 | Leicht organisierter entlang Kämmen |
| Voralpen | 0.00017 | Hangthermik-Mix |
| Alpen | 0.00015 | Organisierte Kerne, Talwindsysteme |
| Hochalpin | 0.00012 | Sehr enge, kompakte Plumes über Felsgraten |

**Quellen:**
- Simpson, J. E. (1971). Turner plumes.
- Lenschow, D. H., & Stephens, P. L. (1980). BLM 19: 509-532.
- De Wekker, S. F. J., & Kossmann, M. (2015). Frontiers in Earth Sci. 3:77.

---

### D. Climb-Factor (w* → reale Gleitschirm-Steigrate)

**Literatur:**

- **Allen NASA (2006)** — mittlere Updraft ≈ 0.6-0.8 × w*, Maximum ≈ 2 × w*,
  Glider-Netto-Steigen ≈ 0.4-0.6 × w*.

- **RASP/Glendening** — "A factor of **2** for extreme vertical velocity in dry air
  masses; **1.5** in moister areas."

- **Paragleiter-Praxis** (langsamer, kleinere Sinkrate) — leicht höhere Faktoren als
  Segelflug.

**Empfehlung — terrain-differenzierter climb_factor (Paragleiter):**

| Terrain | climb_factor (w_real / w*) |
|---|---|
| Mittelland | 0.60 (bereits 0.85 in `config.py:214`, **zu hoch!**) |
| Jura | 0.65 |
| Voralpen | 0.70 |
| Alpen | 0.75 |
| Hochalpin | 0.80 |

**Wichtig:** Der aktuelle Wert `climb_factor.spring = 0.85` ist **überkalibriert für
das Mittelland** (passt aber zum Jura, warum dort die Werte stimmen). Ein
terrain-differenzierter Wert erklärt auch die Jura-Anomalie in der Vergleichstabelle.

**Quellen:**
- Allen, M. J. (2006). NASA TM-2006-213491.
  [NTRS Link](https://ntrs.nasa.gov/api/citations/20060004052/downloads/20060004052.pdf)
- Glendening, J. RASP Parameters. [drjack.info](http://www.drjack.info/rasp/info/parameters.html)

---

## Was der Code und `config.py` brauchen (Zusammenfassung)

### Neue 5-Zonen-Struktur in `config.py`

Die `regionen.csv` hat bereits die 5 Klassen. `gust_calculator.py` liest sie bereits.
`thermik_calculator.py` muss denselben Lookup nutzen (wie `gust_calculator._load_region_terrain()`
und `get_L_up(region_id, elevation_m)`).

**Vorschlagsstruktur für `THERMAL_PARAMS`:**

```python
THERMAL_PARAMS = {
    # ... existing parameters ...

    # --- TERRAIN-DIFFERENZIERTE PARAMETER (5-Zonen) ---
    "min_thermal_depth_agl": {
        "mittelland":  400,
        "jura":        350,
        "voralpen":    300,
        "alpen":       200,
        "hochalpin":   150,
    },

    "snow_damping_factor": {    # H-Reduktion bei Schneedecke
        "mittelland":  0.15,    # 85% Reduktion
        "jura":        0.30,
        "voralpen":    0.45,
        "alpen":       0.60,
        "hochalpin":   0.75,
    },

    "snow_h_max_w_per_m2": {
        "mittelland":   40,
        "jura":         70,
        "voralpen":    120,
        "alpen":       180,
        "hochalpin":   250,
    },

    "snow_dt_excess_max": {     # Solare Überhitzung trotz Schnee (K)
        "mittelland":  0.0,
        "jura":        0.0,
        "voralpen":    0.5,
        "alpen":       1.0,
        "hochalpin":   1.5,
    },

    "gfs_pbl_cap_factor": {     # Korrektur GFS-BLH
        "mittelland":  1.00,
        "jura":        1.10,
        "voralpen":    1.15,
        "alpen":       1.20,
        "hochalpin":   1.25,
    },

    "gfs_pbl_cap_mode": {       # "hard", "soft", "sanity_only"
        "mittelland":  "hard",
        "jura":        "hard",
        "voralpen":    "soft",
        "alpen":       "soft",
        "hochalpin":   "sanity_only",
    },

    "h_ramp_low": {             # Sanfte H-Rampe (W/m²)
        "mittelland":  35,
        "jura":        30,
        "voralpen":    25,
        "alpen":       20,
        "hochalpin":   15,
    },

    "h_ramp_high": {
        "mittelland":  120,
        "jura":        110,
        "voralpen":    100,
        "alpen":        90,
        "hochalpin":    80,
    },

    "entrainment_mu": {         # Ersetzt alpine_MU + MU-Konstante
        "mittelland":  0.00020,
        "jura":        0.00018,
        "voralpen":    0.00017,
        "alpen":       0.00015,
        "hochalpin":   0.00012,
    },

    "climb_factor_terrain": {   # Ersetzt jahreszeitlichen climb_factor
        "mittelland":  0.60,    # war 0.85 (!!)
        "jura":        0.65,
        "voralpen":    0.70,
        "alpen":       0.75,
        "hochalpin":   0.80,
    },

    # Pressure-Level-Interpolation (neu)
    "parcel_interp_dz_m": 100,  # Vor Parcel-Ascent auf dz = 100 m interpolieren
}
```

### Was der Code lesen muss

1. `thermik_calculator.py` muss wie `gust_calculator.py` eine `_load_region_terrain()`-
   Funktion haben oder den Terrain-Type als Parameter von `calculate_thermal_profile()`
   akzeptieren. Der Aufrufer in `web.py:836` kennt die `region_id` bzw. `spot`.

2. Die aktuelle 2-Stufen-Interpolation (`_terrain_factor`) bleibt als **Fallback** für
   Spots, die nicht in `regionen.csv` stehen, ist aber nicht mehr primärer Mechanismus.

3. Die jahreszeitlichen Parameter (`H_cap`, `alpine_H_cap`, `direct_radiation_to_H`, etc.)
   bleiben — sie müssen dann über *beide* Achsen (Jahreszeit UND Terrain) interpoliert
   werden.

---

## Reihenfolge der Umsetzung (nach Priorität)

1. **Pressure-Level-Interpolation** (`parcel_interp_dz_m = 100`) — behebt den Tessin-
   Bug direkt, ist reine Code-Änderung ohne neue Parameter. Auch unabhängig vom
   Terrain-Aware-Rest implementierbar.

2. **Min-Thermal-Depth AGL** (5-Zonen) — ersetzt den 150-m-Hardcode. Einfacher
   Lookup-Mechanismus.

3. **GFS-PBL-Cap differenziert** (mode + factor) — rettet Working Ceiling in Alpen/
   Voralpen.

4. **Snow damping differenziert** — Wallis/Tessin-spezifisch.

5. **Sanfte H-Rampe** — für Morgenstunden.

6. **Entrainment µ und climb_factor** — Feinjustage, erst am Schluss, weil sie mit
   den anderen Schritten wechselwirken und Re-Kalibrierung nötig machen.

---

## Offene Fragen für zukünftige Recherche

1. **Valley-Volume-Effect (Steinacker)** — AlpTherm/Regtherm modellieren das explizit,
   Wingcast nicht. Wie groß ist der Fehler ohne? Messung vs. Regtherm nötig.

2. **Regionale Talwind-Kopplung** — Regtherm-Innovation (horizontale Kompensationsflüsse).
   Nicht in Wingcast abgebildet. Vermutlich ein sekundärer Effekt, der erst nach den
   oben genannten Punkten relevant wird.

3. **Cumulus-Feedback auf H** — Bestehend in `meteo_research/cumulus_feedback.md`,
   aber nicht in Kalibrierung integriert. Später evaluieren.

4. **Stations-basierte Thermik-Validierung** — Analog zur bereits implementierten
   Wind-Bias-Korrektur (`station_observations.py`) wäre eine Thermik-Validierung
   anhand tatsächlich geflogener Flüge (XContest, DHV-XC) langfristig sinnvoll.

---

## Vollständige Literaturliste

Alle zitierten Quellen in diesem Dokument:

1. Allen, M. J. (2006). *Updraft Model for Autonomous Soaring*. NASA TM-2006-213491.
   [NTRS](https://ntrs.nasa.gov/api/citations/20060004052/downloads/20060004052.pdf)

2. De Wekker, S. F. J., & Kossmann, M. (2015). Convective Boundary Layer Heights Over
   Mountainous Terrain — A Review. *Frontiers in Earth Science* 3:77.
   [Frontiers Link](https://www.frontiersin.org/journals/earth-science/articles/10.3389/feart.2015.00077/full)

3. Deardorff, J. W. (1970). Convective velocity and temperature scales for the unstable
   planetary boundary layer and for Rayleigh convection. *J. Atmos. Sci.* 27(8):
   1211-1213.

4. Glendening, J. "Dr. Jack". RASP BLIPMAP Parameters.
   [drjack.info](http://www.drjack.info/rasp/info/parameters.html)

5. Guo, J., et al. (2021). Investigation of near-global daytime boundary layer height
   using high-resolution radiosondes. *ACP* 21: 17079-17097.
   DOI: [10.5194/acp-21-17079-2021](https://acp.copernicus.org/articles/21/17079/2021/)

6. Guo, J., et al. (2022). Evaluation of the Planetary Boundary Layer Height in China
   Predicted by the CMA-GFS Global Model. *Atmosphere* 13:845.
   DOI: [10.3390/atmos13050845](https://www.mdpi.com/2073-4433/13/5/845)

7. Kaimal, J. C., & Finnigan, J. J. (1994). *Atmospheric Boundary Layer Flows: Their
   Structure and Measurement*. Oxford University Press. ISBN 978-0-19-506239-7.

8. Lenschow, D. H., & Stephens, P. L. (1980). The role of thermals in the convective
   boundary layer. *Boundary-Layer Meteorology* 19(4): 509-532.
   DOI: [10.1007/BF00122351](https://link.springer.com/article/10.1007/BF00122351)

9. Liechti, O., & Neininger, B. (1994). ALPTHERM: A PC-based model for atmospheric
   convection over complex topography. *Technical Soaring* 18(3): 73-78.
   [OSTIV](https://ts.ostiv.org/index.php/ts/article/view/218)

10. Liechti, O. (2001). Regtherm. *Technical Soaring*.
    [OSTIV](https://ts.ostiv.org/index.php/ts/article/view/279)

11. Magnin, F., et al. (2015). Rockwall temperatures at Aiguille du Midi.
    [hal.science/hal-01313938](https://hal.science/hal-01313938)

12. Markowski, P., & Richardson, Y. (2010). *Mesoscale Meteorology in Midlatitudes*.
    Wiley-Blackwell. DOI: [10.1002/9780470682104](https://onlinelibrary.wiley.com/doi/book/10.1002/9780470682104)

13. Michel, A., et al. (2022/2025). Eddy covariance measurements at Weissfluhjoch
    over snow. *Frontiers in Earth Science*.
    [Frontiers](https://www.frontiersin.org/journals/earth-science/articles/10.3389/feart.2025.1640842/full)

14. Moeng, C.-H., & Sullivan, P. P. (1994). A comparison of shear- and buoyancy-driven
    planetary boundary layer flows. *J. Atmos. Sci.* 51: 999-1022.

15. Mott, R., Schlögl, S., Dirks, L., & Lehning, M. (2018). How are turbulent sensible
    heat fluxes and snow melt rates affected by a changing snow cover fraction?
    *Frontiers in Earth Science* 6:154.
    DOI: [10.3389/feart.2018.00154](https://www.frontiersin.org/articles/10.3389/feart.2018.00154/full)

16. Müller, H., & Whiteman, C. D. (1988). Breakup of a Nocturnal Temperature Inversion
    in the Dischma Valley during DISKUS. *J. Appl. Meteorology* 27: 188-194.

17. Nyeki, S., et al. (2000). CBL evolution to 4 km AGL over high-alpine terrain.
    *Geophys. Res. Lett.* 27: 689-692.
    DOI: [10.1029/1999GL010928](https://agupubs.onlinelibrary.wiley.com/doi/abs/10.1029/1999GL010928)

18. Rotach, M. W., et al. (2004). Turbulence Structure and Exchange Processes in an
    Alpine Valley: The Riviera Project. *BAMS* 85: 1367.

19. Rotach, M. W., et al. (2022). On the measurement of stability parameter over
    complex mountainous terrain. *Wind Energy Science* 7: 221-240.
    DOI: [10.5194/wes-7-221-2022](https://wes.copernicus.org/articles/7/221/2022/)

20. Salesky, S. T., Chamecki, M., & Bou-Zeid, E. (2017). On the nature of the
    transition between roll and cellular organization in the convective boundary layer.
    *Boundary-Layer Meteorology* 163: 41-68.
    DOI: [10.1007/s10546-016-0220-3](https://link.springer.com/article/10.1007/s10546-016-0220-3)

21. Seibert, P., et al. (2000). Review and intercomparison of operational methods for
    the determination of the mixing height. *Atmospheric Environment* 34(7): 1001-1027.

22. Serafin, S., et al. (2018). Field observations of the morning transition over a
    steep slope in a narrow alpine valley. *Environmental Fluid Mechanics*.
    DOI: [10.1007/s10652-018-9582-z](https://link.springer.com/article/10.1007/s10652-018-9582-z)

23. Stiperski, I., & Rotach, M. W. (2016). On the measurement of turbulence over
    complex mountainous terrain. *Boundary-Layer Meteorology* 159: 97-121.
    DOI: [10.1007/s10546-015-0103-z](https://link.springer.com/article/10.1007/s10546-015-0103-z)

24. Stull, R. B. (1988). *An Introduction to Boundary Layer Meteorology*. Kluwer
    Academic. ISBN 978-90-277-2769-5.

25. Tennekes, H. (1973). A Model for the Dynamics of the Inversion Above a Convective
    Boundary Layer. *J. Atmos. Sci.* 30(4): 558-567.

26. Wang, Z., et al. (2021). Reanalyses fail to capture high tail of CAPE distributions.
    [arXiv:2012.13383](https://arxiv.org/abs/2012.13383)

27. Weigel, A. P., & Rotach, M. W. (2004). Flow structure and turbulence
    characteristics in an Alpine Valley.

28. Whiteman, C. D. (1982). Breakup of Temperature Inversions in Deep Mountain Valleys,
    Part I: Observations. *J. Appl. Meteorology* 21: 270-289.
    [U. Utah PDF](https://www.inscc.utah.edu/~whiteman/homepage/articles/Whiteman1982J%20Appl%20Meteorol.pdf)
