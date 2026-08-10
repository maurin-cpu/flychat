# Regionale Referenzpunkte — Konzept

Dokumentation der **Aggregations-Logik** (wie aus 7 Punkten ein Regions-Wert
wird) und des **Platzierungs-Guides** (wo die Punkte gesetzt werden).

Die konkrete Liste der 7 empfohlenen Punkte pro Region steht separat in
`docs/REFPOINT_LISTE.md`.

Forschungsgrundlage: `meteo_research/region_refpoints_research.md`

---

## Ziel der Referenzpunkte

Pro Region (29 Polygone in der Schweiz) werden N=7 Punkte beim Wettermodell
abgefragt und zu einem Regions-Wert aggregiert. Die Punkte müssen die
**meteorologische Heterogenität** der Region abdecken, nicht ihre
**geometrische** Verteilung.

> **Merksatz**: Setze Punkte dorthin, wo das Wetter ANDERS ist — nicht dorthin,
> wo geometrisch noch Platz frei ist.

---

## Teil 1: Aggregations-Logik — wie aus 7 Punkten ein Regions-Wert wird

Jeder der 7 Referenzpunkte einer Region liefert ein vollständiges Wetterprofil
von Open-Meteo (Temperatur, Strahlung, Wolken, Wind, Niederschlag, Druckniveaus
etc.). Diese 7 Profile werden **parameter-spezifisch** aggregiert — jede
Variable hat eine eigene, physikalisch begründete Aggregationsregel.

### Übersicht: Aggregation pro Parameter-Klasse

| Parameter-Klasse | Methode | Begründung |
|---|---|---|
| **Thermik** (Temperatur, Strahlung, Druckniveaus, Feuchte) | **1 Best-Punkt** = höchste mittlere Strahlung während Flugstunden | Thermik wird AM Sonnenpunkt erzeugt, nicht gemittelt |
| **Wolken** (low/mid/high/total) | **30%-Perzentil** über alle 7 Punkte | NWP überschätzt Bewölkung systematisch in Bergen — Perzentil findet Blue Holes |
| **Niederschlag** (precipitation, rain) | **Hybrid: Max ohne Quorum wenn Peak ≥ 0.2 mm/h; sonst 30%-Quorum; < 0.05 mm/h = 0** | DWD-Standard (Ebert 2008 Neighborhood Method) — konvektive Einzelzellen kommen durch, Rauschen geclipt |
| **precipitation_probability** | **Max** über alle Punkte | POP ist bereits eine Wahrscheinlichkeit — höchste regionale Schauer-Chance konservativ |
| **precipitation_coverage** (neu, abgeleitet) | **Anteil RPs > 0.05 mm/h, 0.0–1.0** | Erlaubt späteres Decision-Tag RAIN-SCATTERED vs RAIN-WIDESPREAD |
| **Wind 10m** (Speed) | **Median** über alle 7 Punkte | Robust gegen einen einzelnen alpinen RP, der die Region dominiert |
| **Wind 10m** (Direction) | **Vektorielles Mittel** (zirkulär, geschwindigkeits-gewichtet) | Korrekt für 360°-Variablen |
| **Böen** (wind_gusts_10m) | **Wird NICHT aggregiert** auf Region-Ebene | Böen sind lokale Spitzen — nicht regional sinnvoll, gehören auf Spot-Ebene |

### 1.1 Thermik: Single-Best-Anchor

**Code**: `_best_thermal_rp_index()` in `fetch_weather.py:259`

Der thermische Anker wird so gewählt:

```python
# Für jeden der 7 RPs: mittlere shortwave_radiation während FLIGHT_HOURS_START..END berechnen
# Pick = RP mit dem höchsten Mittelwert
# Dieser RP wird an Position 0 verschoben
# _aggregate_regional_data() behält data_list[0] für ALLE Thermik-Parameter
```

Welche Parameter werden vom Best-Punkt übernommen (= NICHT aggregiert)?
- `temperature_2m`, `temperature_850hPa`, `temperature_700hPa` etc.
- `shortwave_radiation`, `direct_radiation`, `diffuse_radiation`
- `relative_humidity_2m`, `dew_point_2m`
- Alle `*_XhPa` Druckniveau-Felder (Wind aloft, Temperatur aloft)
- `surface_pressure`, `pressure_msl`
- `cape`, `convective_inhibition`, `lifted_index`

Daraus berechnet `thermik_calculator.py` später `climb_rate`, `max_height`,
`thermal_quality` — alles basiert auf DEM EINEN Best-Punkt.

**Warum Single-Best statt Median/Max?**
- Thermik entsteht lokal an Sonnenhängen, nicht regional. Ein Median über
  Schatten- und Sonnenseite würde die echte Thermik unterschätzen.
- Max über climb_rate wäre theoretisch besser — aber climb_rate wird erst NACH
  der Aggregation berechnet. Strahlung ist der Vor-Indikator und korreliert
  ≈linear mit w*.

### 1.2 Wolken: 30%-Perzentil

**Code**: `_aggregate_regional_data()` in `fetch_weather.py:307-335`

Schritt-für-Schritt:
1. Für jeden RP einen **Score** berechnen: `score = low*1.0 + mid*0.7 + high*0.25`
   (gewichtet nach Auswirkung auf Einstrahlung — tiefe Wolken dämpfen am
   stärksten, Cirrus kaum)
2. Die 7 Scores aufsteigend sortieren
3. **Target-Index = `int(0.3 × n)`** picken (bei n=7 → Index 2, also der
   drittsonnigste Punkt)
4. Die `cloud_cover_low/mid/high/total`-Werte DIESES Punkts in den Output
   übernehmen

**Physik**: NWP-Modelle überschätzen Bewölkung in komplexem Terrain
systematisch (Quelle: Mishra et al. 2020 sowie Modell-Validierung MeteoSchweiz).
Das 30%-Perzentil ist robust gegen diesen Bias und findet **Blue Holes** —
regionale Sonnenfenster, die in den meisten Punkten als "bewölkt" prognostiziert
werden, aber irgendwo aufbrechen.

**Konsequenz**: Wenn 4 von 7 Punkten 80% Bewölkung melden und 3 Punkte 30%,
nimmt die Aggregation den **drittsonnigsten** (Index 2) = etwa 30-40%. Die
Region zeigt also Sonne, weil die statistisch existierende Wolkenlücke
gefunden wird.

### 1.3 Niederschlag: Hybrid-Filter (Neighborhood Method)

**Code**: `_aggregate_regional_data()` in `fetch_weather.py:343-385`

**Hintergrund — warum nicht reines Quorum:** ICON-D2 (2.2 km Aufloesung) modelliert
Konvektion explizit. Eine einzelne Schauerzelle (2-10 km Durchmesser) trifft typisch
nur 1-2 von N Referenzpunkten. Ein reines 30%-Quorum (alt) hat solche Zellen
systematisch geclipt — der heutige Fall (16.05.2026, Zentrales Mittelland 1.1 mm an
1 von 7 RPs → wurde als 0.0 ausgegeben) war die Konsequenz.

**Industrie-Standard:** Ebert (2008) "Neighborhood Method", DWD operational seit
2012 fuer COSMO-DE-EPS und ICON-D2: parallel **Maximum** (konservativer Peak) und
**Fractional Coverage** (Verteilungsinformation) innerhalb der Region-Box berechnen.

**Logik pro Stunde (precipitation, rain in mm/h):**
1. `peak = max(valid_vals)`, `coverage = n_wet / n_total` (n_wet = RPs mit Wert > NOISE_MM)
2. Wenn `peak ≥ PRECIP_SIGNIFICANT_MM` (0.2 mm/h) → **peak** ausgeben (echte Zelle, kein Quorum noetig)
3. Sonst wenn `peak > PRECIP_NOISE_MM` (0.05 mm/h) **UND** `coverage ≥ 30%` → **peak** ausgeben (flaechiger leichter Regen)
4. Sonst → **0.0** (isolierter Trace-Wert oder reines Modell-Rauschen)
5. `precipitation_coverage` wird in allen Faellen als 0.0-1.0 gespeichert

**`precipitation_probability` (POP):** Einfach `max()` ueber alle RPs — POP ist
schon eine Wahrscheinlichkeit, konservativ heisst hier "hoechste regionale
Schauer-Chance".

**Schwellen-Begruendung (konfigurierbar in `config.py`):**
- `PRECIP_SIGNIFICANT_MM = 0.2` — WMO/Aviation "light precipitation": ab dieser
  Intensitaet spuert der Pilot Naesse am Schirm. Bewusst niedriger als die DWD-
  Operationsschwelle 0.5 (false-negative-averse fuer Aviation).
- `PRECIP_NOISE_MM = 0.05` — unter Modell-Trace-Niveau, filtert numerische Spikes.
- `PRECIP_COVERAGE_QUORUM = 0.3` — alter 30%-Schwellwert bleibt als Fallback fuer
  Werte zwischen NOISE und SIGNIFICANT.

**Konsequenz:**
- 1 von 7 RPs zeigt 0.8 mm/h → durchgelassen (war vorher 0.0).
- 1 von 7 RPs zeigt 0.03 mm/h → 0.0 (Rauschen).
- 5 von 7 RPs zeigen 0.1 mm/h → durchgelassen (Quorum greift).
- 1 von 7 RPs zeigt 0.1 mm/h → 0.0 (isolierter Trace, kein Quorum).

### 1.4 Wind: Median + Vektor-Mittel

**Code**: `_aggregate_wind_across_points()` in `fetch_weather.py:192`

- **Speed (km/h)**: Median über alle 7 RPs (robust gegen Ausreisser, z.B. einen
  einzelnen Gipfelpunkt in einer sonst tieferen Region)
- **Direction (°)**: vektoriell gemittelt (zirkulär korrekt), gewichtet mit der
  Speed des jeweiligen Punkts:
  ```python
  u = Σ(speed × sin(dir)) / n
  v = Σ(speed × cos(dir)) / n
  mean_dir = atan2(u, v) mod 360°
  ```

**Warum vektoriell?** Arithmetisches Mittel von 350° und 10° wäre 180° (falsch
— sollte 0° sein). Vektor-Mittel liefert korrekt 0°.

**Böen** werden auf Region-Ebene NICHT aggregiert (Apr 2026). Stattdessen
werden Bodenwind-Exzesse über alle Region-RPs via `aggregate_spot_excess()`
gemedianiert und am Region-Referenzpunkt als Single-Anchor angesetzt — siehe
`docs/BOEEN_MODELL.md` Schritt 2c.

### 1.5 Daten-Fluss-Diagramm

```
7 RPs × Open-Meteo Query → 7 Wetterprofile
            ↓
   _best_thermal_rp_index → Best-RP an Position 0
            ↓
   _aggregate_regional_data
   ├─ Thermik-Params: data_list[0] behalten
   ├─ Wolken: 30%-Perzentil-Pick
   ├─ Niederschlag: Hybrid (Peak≥0.2mm ohne Quorum; sonst 30%; <0.05mm=0)
   └─ precipitation_coverage: Anteil RPs > 0.05mm (0.0-1.0)
            ↓
   _aggregate_wind_across_points
   ├─ wind_speed_10m: Median
   └─ wind_direction_10m: vektor-Mittel
            ↓
   Aggregierter Region-Profile (1 Wetterprofil)
            ↓
   _process_spot_weather (gleiche Pipeline wie Spot)
   ├─ thermik_calculator: climb_rate, max_height, TQ-Tags
   ├─ gust_calculator: T(z) Turbulenz-Risiko
   └─ Decision-Engine: safety_status, foehn_risk, flyability_tier
```

### 1.6 Praktische Konsequenzen für die Punkt-Wahl

| Aggregations-Regel | Was du beim Punkt-Setzen beachten musst |
|---|---|
| Thermik = Best-Strahlungs-RP | Mindestens **1 S-Punkt auf Flughöhe** muss im Set sein — sonst findet der Algorithmus keinen realistischen Anker |
| Wolken = 30%-Perzentil | Mindestens **2-3 RPs auf verschiedenen Aspekten/Höhen** — sonst kein Perzentil-Spread möglich |
| Niederschlag Hybrid-Filter | Eine einzige RP-Zelle mit Peak ≥ 0.2 mm/h reicht bereits — konvektive Schauer kommen durch, egal ob 1 oder 5 von 7 RPs nass sind. Nur Trace-Werte (0.05-0.2 mm/h) brauchen noch das 30%-Quorum |
| Wind-Median | Höhenstreuung der RPs vermeiden, wenn das Polygon nicht wirklich heterogen ist — sonst dominiert ein hoher RP den Median nach oben |
| Föhn-Anker | Für Föhn-Wind-Decisions ist der Median wichtig: 4+ von 7 Punkten müssen Föhn-Speed sehen, damit `FoehnCaution` triggert |

---

## Teil 2: Platzierungs-Guide — wo die Punkte gesetzt werden

---

## Die 5 Funktionen, die abgedeckt sein müssen

Mit 7 Punkten lassen sich diese 5 Funktionen abdecken (Mehrfachbelegung OK):

### 1. Talboden-Punkt(e) — Stau, Nebel, Kaltluftsee

- **Wo**: Geographische Tal-Mitte, NICHT am Talausgang
- **Höhe**: Talboden-Niveau der Region (z.B. 600-1000m im Mittelland, 1200-1500m
  in Hochtälern wie Saastal)
- **Erfasst**: Bodennebel-Auflösung, Niederschlags-Stau, Inversions-Persistenz,
  Kaltluftsee-Bildung
- **Bei langen Tal-Regionen** (Wallis, Engadin, Reusstal): 2 Punkte entlang der
  Talachse (Ein- und Ausgang)

### 2. Flughöhe-Punkt — Thermik-Plafond, Wolkenbasis-Realität

- **Wo**: S-/SO-exponierte Flanke auf typischer Flughöhe
- **Höhe**: 1500-2500m AGL (regions-abhängig)
- **Erfasst**: nutzbare Wolkenbasis (LCL), Cumulus-Entwicklung, Thermik-Stärke
- **Das ist der "wo fliegen die Leute tatsächlich"-Punkt**

### 3. Kamm-/Gipfel-Punkt — Höhenwind, Lee-Turbulenz, Wellen

- **Wo**: Repräsentativer Hauptkamm der Region (NICHT der höchste Gipfel)
- **Höhe**: typische Kammhöhe der Region (2500-3000m in Voralpen, 3000-3500m
  in Hochalpen)
- **Erfasst**: freier Höhenwind, Lee-Turbulenz-Quelle, Wellen-Entstehung

### 4. Föhn-Strom-Punkt — kritisch bei Föhn-Exposition

Nur relevant wenn `kritischer_foehn` in `regionen.csv` gesetzt ist.

- **Wo**: Lee-Seite der Hauptbarriere zur kritischen Föhnrichtung
- **Erfasst**: Föhn-Durchbruch (typischerweise hier als erstes spürbar)
- **Konkrete Beispiele**:

| Region | Kritischer Föhn | Empfohlene Anker-Position |
|---|---|---|
| Mittelland Ost | S-Föhn | Alpennord-Fuss (Linth-Gebiet, Glarner Tor) |
| Plateau | S-Föhn | Saanen, Diemtigtal-Ausgang |
| Emmental | S-Föhn | Brienzersee-Nord, Thunersee-Nord |
| Innerschweiz | S-Föhn | Vierwaldstättersee-Nordufer |
| Lötschental | N-Föhn | Brig/Visp am Talausgang |
| Tessin | N-Föhn | Magadinoebene |
| Engadin | N-Föhn | Maloja-Pass / St. Moritz-Ebene |

### 5. Konvektions-Kontrast-Punkt — Wolkenlücken erkennen

- **Wo**: N/NW-exponierte Lage ODER schattiger Talkessel
- **Erfasst**: Tagesgang-Asymmetrie, Schatten-Sonnen-Kontrast → ermöglicht
  Erkennung von **Blue Holes** (Wolkenlücken durch lokale Konvektion)
- **Warum wichtig**: Ohne Schatten-Kontrast-Punkt sieht die Aggregation alle
  Punkte als "sonnig" wenn sie alle S-exponiert sind — Wolkenfeld-Heterogenität
  geht verloren

---

## Verteilungs-Regel: Höhe + Aspekt + Position

### Höhen-Verteilung (Faustregel)

| Region-Typ | Tal | Flughöhe | Kamm |
|---|---|---|---|
| Hochalpin (Wallis-Süd, Bernina) | 1× | 3× | 3× |
| Alpin (Emmental) | 2× | 3× | 2× |
| Voralpen (Innerschweiz, Säntis) | 2× | 3× | 2× |
| Jura | 2× | 3× | 2× |
| Mittelland (flach) | — | Aspekt-Variation 7× | — |

**Mindest-Spreizung**: Höchster Punkt soll mindestens 800m über dem tiefsten
liegen (sonst keine vertikale Information).

### Aspekt-Verteilung

Mindestens **2 verschiedene Expositionen** pro Region:
- 3-4 Punkte S/SO/SW-exponiert (Hauptthermik-Hänge)
- 2-3 Punkte mit Kontrast: N, NE, NW oder talboden (schattig/flach)

### Mindest-Abstand

Punkte müssen **≥ 2 km auseinander** sein (ICON-D2 Auflösung ~2 km — zwei
nähere Punkte liefern denselben Grid-Wert, redundant).

---

## Region-Typ-Heuristik

### Talregion (Wallis, Engadin, Reusstal)
**Priorität**: Talachsen-Sampling + Lee-Punkt für Föhn
- 2-3 Punkte entlang Talachse (Tal-Eingang, Tal-Mitte, Tal-Ausgang)
- 2 Punkte auf Talflanken (Süd-Hang + Nord-Hang)
- 1 Punkt auf Hauptkamm
- 1 Föhn-Strom-Anker am kritischen Talausgang

### Voralpen-Massiv (Emmental, Säntis, Pilatus-Gebiet)
**Priorität**: S-Flanken-Hotspots + N-Schattenkontrast + Kamm
- 3 Punkte auf S-exponierten Hauptflanken (in unterschiedlicher Höhe)
- 1-2 Punkte auf N-exponierten Hängen
- 1 Punkt Kammlinie
- 1-2 Punkte Talböden

### Hochalpin (Bernina, Wallis-Süd)
**Priorität**: Höhen-Variation entlang Hauptkamm
- Wenige Talböden (gibt's kaum)
- Fokus auf Flanken- und Kamm-Variation
- Mehrere Höhenstufen entlang einer N-S-Kammachse

### Mittelland-Hügel (Jura, Napf, Zürcher Oberland)
**Priorität**: Aspekt-Diversität > Höhe (Reliefenergie zu klein)
- Punkte verteilt nach Hauptwind-Achse (W/NW als Stau-Luv, SO als Lee)
- Wald-/Wiese-/Siedlungs-Bedeckung diversifizieren

### Föhn-Tor (Linthebene, Glarus, Magadino)
**Priorität**: 2 Föhn-Strom-Anker entlang Föhnachse
- 1 Anker am Engpass (wo Föhn beschleunigt)
- 1 Anker am Ausströmgebiet (wo Föhn ankommt)
- Übrige Punkte konventionell verteilt

---

## Anti-Patterns

| Anti-Pattern | Warum problematisch |
|---|---|
| Alle 7 Punkte auf gleicher Höhe | Keine vertikale Information, Kamm-Wind unsichtbar |
| Alle Punkte S-exponiert | Kein Schatten-Kontrast, Blue Holes unsichtbar |
| Punkte < 2 km auseinander | ICON-D2 Auflösung — redundant, Aggregation gewichtet doppelt |
| Reine Polygon-Centroid als Hauptpunkt | In CH meist hochalpin/unbewohnt, klimatologisch nicht typisch |
| Alle 4 Edge-Punkte unbesehen behalten | Greedy Max-Min hat in einigen Regionen Punkte am Gletscherrand / Talschluss gesetzt — klimatologisch nicht typisch |
| Punkt auf einem Gewässer (Seemitte) | Falsche Oberflächen-Bilanz (Wasser ≠ Land), liefert verzerrte Werte |
| Identische Position für 2+ Punkte | Aggregation sieht das nicht als Duplikat |

---

## Checkliste pro Region

Beim manuellen Setzen für jede Region durchgehen:

- [ ] Typische Flughöhe (1500-2500m) abgedeckt?
- [ ] ≥ 2 verschiedene Aspekte (z.B. S + N oder S + W)?
- [ ] Talboden für Stau/Nebel-Erkennung vorhanden?
- [ ] Föhn-Lee abgedeckt (falls `kritischer_foehn` gesetzt)?
- [ ] Höhenspanne zwischen höchstem und tiefstem Punkt ≥ 800 m?
- [ ] Alle Punkte mind. 2 km voneinander entfernt?
- [ ] Kein Punkt auf einem grossen Gewässer (Seemitte > 1 km²)?
- [ ] Liegen alle Punkte im klimatologisch repräsentativen Teil (kein
  randständiges Geometrie-Eck)?
- [ ] Mindestens ein Punkt nahe einem etablierten Flugschul-/Startplatz-Gebiet
  der Region?

---

## Workflow zum manuellen Setzen

1. Region öffnen: Karte unter `/regionen` oder direkt in
   `data/regionen_referenzpunkte.geojson`
2. Polygon-Geometrie und kritische Topographie prüfen (z.B. via
   [map.geo.admin.ch](https://map.geo.admin.ch))
3. 7 Punkte gemäss Checkliste auswählen — als `[lat, lon]`-Paare
4. In `scripts/create_regionen_geojson.py` → `MANUAL_REFERENCE_POINTS`-Dict
   eintragen (analog zu `mittelland_ost`):
   ```python
   MANUAL_REFERENCE_POINTS = {
       "mittelland_ost": [
           [47.3214, 8.4956],   # Balderen
           [47.2891, 8.6234],   # Pfannenstiel
           # ...
       ],
       "neue_region": [
           [lat1, lon1],  # Talboden Mitte
           [lat2, lon2],  # S-Flanke Flughöhe
           # ...
       ],
   }
   ```
5. Skript ausführen: `python scripts/create_regionen_geojson.py`
6. Flask neu starten (Cache-Invalidierung in `source_area._load_regions()`)
7. Wetter-Refresh auslösen oder Daily-Job abwarten
8. Verifikation auf `/regionen`-Karte (`SHOW_REFERENCE_POINTS`-Toggle)

---

## Sonderfall: Föhn-kritische Regionen

Wenn `kritischer_foehn` in `regionen.csv` gesetzt ist, sollte **mindestens 1
der 7 Punkte** explizit am Föhn-Strom-Anker liegen. Dieser Punkt sieht den
Föhn-Durchbruch typischerweise als erstes — die Aggregation greift das via
Wind-Stärke-Mehrheit auf und triggert `FoehnCaution`/`FoehnDanger` (siehe
`docs/DECISIONS.md`).

Wenn 2 Föhn-Richtungen kritisch sind (selten — z.B. Glarus mit S- und N-Föhn),
**2 Anker** setzen.

---

## Wann manuelle Punkte besser sind als CVT-Algorithmus

| Situation | Bevorzugt |
|---|---|
| Region mit klarem Föhn-Tor | Manuell |
| Region mit asymmetrischer Topographie (z.B. lange schmale Täler) | Manuell |
| Region mit lokalen Wetter-Eigenheiten (z.B. Bisenwind-Korridor) | Manuell |
| Gleichmässig geformte Mittelland-Hügel | CVT-Hybrid OK |
| Region mit wenig Topographie | CVT-Hybrid OK |

**Faustregel**: Wenn du die Region kennst und 3+ meteorologische Eigenheiten
nennen kannst, setze manuell. Sonst CVT-Hybrid als Default.

---

## Anhang: S-Flughöhe-Anker pro Region — siehe REFPOINT_LISTE.md

Die früher hier stehende Tabelle mit dem empfohlenen S-Flughöhe-Anker pro
Region ist Bestandteil der vollständigen 7-Punkte-Liste geworden und steht
jetzt in `docs/REFPOINT_LISTE.md` (Spalte "Flughöhe" pro Region).

**Zweck (zur Erinnerung)**: Der Thermik-Anker einer Region wird vom Algorithmus
`_best_thermal_rp_index` (`fetch_weather.py:259`) gewählt — er pickt unter den
N=7 Referenzpunkten denjenigen mit der höchsten mittleren `shortwave_radiation`
während der Flugstunden. Damit dieser Pick **realistisch** ausfällt, muss
mindestens **1 S-exponierter Punkt auf typischer Flughöhe** im Set sein.

→ Die vollständige Tabelle (S-Anker + 6 weitere Punkte pro Region) steht in
`docs/REFPOINT_LISTE.md`.
