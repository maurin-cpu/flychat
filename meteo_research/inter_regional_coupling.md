# Inter-Regional Coupling: Moisture Advection, Alpine Pumping & Mountain Venting

> **Kontext**: Liechtis REGTHERM-Paper (2001) postulierte horizontale Kopplung benachbarter Konvektionsregionen ueber Druckgradienten aus differentieller Heizung. Seither hat die peer-reviewte Literatur die Mechanik praezisiert. Dieses Dokument fasst zusammen, was **wissenschaftlich belegt** ist (mit Quellen) und was **operationell umsetzbar** ist fuer unser System.
>
> **Begleitdokument**: `regional_thermal_forecasting.md` (REGTHERM/XC-Therm/Burnair).

---

## 1. Was Liechti 2001 modelliert hat — Stand heute

REGTHERM erweiterte das 1D-ALPTHERM um horizontale Kopplung benachbarter Polygone via Druckgradienten aus differentieller Heizung. Liechti unterscheidet drei Kopplungs-Typen:

1. **Kuesten-Kopplung** (Seebrise, surface characteristics differ)
2. **Becken-zu-Erhebung-Kopplung** (Volumeneffekt, Rhein-Becken ↔ Schwarzwald)
3. **Tal-Ketten** (A-B-C-D entlang Hauptachse, z.B. Po-Plain → Bergamo → Valtellina → Engadin via Maloja)

**Was Liechti richtig vorhersagte**:
- Aspiration kuehler/feuchter Luft "oeffnet" die Konvektion in der warmen Region — keine geschlossene Vertikalbilanz mehr
- Wolkenbedeckung tendenziell in Becken reduziert, ueber elevated terrain erhoeht (trockenes Luftmassen-Regime)
- In feuchten Luftmassen verschiebt sich gute Thermik in tiefer liegende Regionen
- Maloja-Wind als aerologische (nicht hydrologische) Kopplung Po-Plain → Engadin

**Was Liechti **nicht** lieferte**:
- Quantifizierte Schwellenwerte (kein "wenn Δq > X g/kg, dann ΔCloudbase = Y m")
- Validierungsmetriken (keine publizierten Skill-Scores)
- Fallback-Verhalten bei Datenluecken

REGTHERM bleibt eine **physikalisch motivierte Heuristik**, keine verifizierte Vorhersage-Engine im modernen Sinn.

---

## 2. Peer-reviewed Befunde seit 2001 — die drei robusten Saeulen

### 2.1 Alpine Pumping (Mountain-Plain Circulation)

Die Alpen als waermespeichernder Block saugen tagsueber Luft aus dem Vorland an. **Bestbelegt aller Inter-Regional-Effekte**.

- **Lugauer & Winkler (Bayerische Foehnstudie)**: Thermisches Windsystem an **42 % der April–September-Tage** mit Globalstrahlung > 20 MJ/m². Eindringtiefe ~100 km ins Vorland.
- **Weissmann et al. 2005 (Monthly Weather Review, VERTIKATOR)**: Doppler-Lidar-Messungen zeigen **1–4 m/s Stroemung Richtung Alpen, bis 1500 m tief, bis ~80 km Eindringtiefe**. Maximum am Nachmittag.
- **Graf et al. 2016 (Frontiers in Earth Science)**: Klimatologie des Alpine Pumping ueber 30 Jahre, bestaetigt Persistenz des Phaenomens.

**Implikationen fuer CH**:
- An Schoenwettertagen wird Mittelland-Luft systematisch in die Voralpen/Alpen transportiert
- Feuchte des Mittellands erreicht alpine Region am Nachmittag
- Effekt ist klimatologisch belegt, nicht spekulativ

**Trigger-Bedingungen aus Literatur**:
1. Hohe Einstrahlung (> 20 MJ/m² Tagessumme, ≈ Schoenwetter)
2. Schwacher synoptischer Wind (< 5 m/s auf 700 hPa)
3. Konvergente Bodenwinde Richtung Alpen-Hauptachse

### 2.2 Mountain Venting (Henne et al. 2005)

Konvektive Aktivitaet ueber den Alpen exportiert systematisch Grenzschichtmasse in die freie Troposphaere.

- **Henne et al. 2005 (J. Appl. Meteor. Climatol.)**: An Schoenwettertagen werden **~30 % der alpinen Grenzschichtmasse pro Stunde ueber 2500 m gehoben**.
- Im Lee (Payerne → Milano) entsteht eine signifikante **Feuchteschicht zwischen 2500–4000 m MSL**.
- Verstaerkt bei hoher Strahlung, niedriger Stabilitaet, konvektiver Aktivitaet.

**Implikationen fuer CH**:
- Erklaert, warum Wolkenbasis in Alpen-Regionen am Nachmittag sinkt, obwohl Boden-q konstant bleibt
- Die advektierte Feuchteschicht ist **oberhalb** der lokalen LCL — verschiebt das effektive Kondensationsniveau nach unten
- Unser aktuelles Parcel-Modell sieht diese Schicht nicht, weil sie aus Nachbar-Konvektion stammt

### 2.3 Mountain-Plain Moisture Gradient (TEAMx-PC22)

TEAMx-PC22 (Inn-/Weer-Tal, Sommer 2022) zeigt: **Advektion (nicht turbulente Mischung) dominiert das CBL-Wachstum in komplexem Gelaende**. Bisherige BL-Wachstums-Modelle unterschaetzen den Talwind-Beitrag systematisch.

- Feuchtegradient Vorland → Lee typischerweise **+1 g/kg im Mittel** (Henne, Weissmann)
- Talwind-Feuchteadvektion am Nachmittag ist signifikant fuer alpine CBL-Eigenschaften

---

## 3. Was die Wissenschaft nach 2001 zu Steepness-Effekten sagt

**Wagner et al. 2023 (Weather and Climate Dynamics)**: Steile Berge erzeugen staerkere Updrafts, aber **schmaelere Updraft-Zonen → mehr Entrainment trockener Luft → geringere Niederschlagseffizienz**.

- Effizienz faellt von **11–12 %** (sanfte Haenge) auf **0.03–5.5 %** (steile Haenge)
- Konvektion wird durch **Feuchteadvektion**, nicht durch Vertikalgeschwindigkeit limitiert
- Implikation: Unser hochalpine-Tier-Parameter (kleineres MU = weniger Entrainment) ist **physikalisch falsch herum** fuer sehr steile Spots

**Caveat**: Wagner untersucht Niederschlagseffizienz, nicht direkt nutzbare Steighoehe. Uebertragung auf XC-Performance erfordert Kalibrierung.

---

## 4. Was operationelle Forecasts (2024/25) machen

Stand der Recherche zu SkySight, TopMeteo, XCSkies, Burnair, RASP/BLIPMAP, Soaringmeteo:

| System | Datenbasis | Inter-Regional-Coupling? |
|--------|-----------|--------------------------|
| SkySight | WRF 2 km | Implizit ueber NWP, keine Heuristik on top |
| TopMeteo | ICON/COSMO | Implizit ueber NWP |
| XCSkies | WRF | Implizit |
| RASP/BLIPMAP | WRF | Implizit |
| Soaringmeteo | GFS 25 km + COSMO 7/WRF 2 km | Explizit ohne Zwischen-Heuristik |
| Burnair | ICON-CH1/CH2/D2 | 40-Param Safety-Algo, aber keine explizite Regions-Kopplung |
| XC-Therm | ICON-D2/EU + REGTHERM lizenziert | **Einziger** mit expliziter Regions-Kopplung (REGTHERM) |

**Konsequenz**: Niemand publiziert Lookup-Tabellen "Region A feucht + Wind aus B → Region C Cloudbase −X m". Diese existieren nicht in der peer-reviewed Literatur. Operationelle Systeme verlassen sich auf 2-km-NWP, das die Effekte implizit aufloest.

**Pilot-Folklore aus Foren** (nicht wissenschaftlich validiert):
- SkySight tendiert in Alpen zu optimistischen Cloudbase-Werten am Morgen
- Modelle schwaecheln bei Talbodenfeuchte (zu trocken ueber Fluessen, zu feucht ueber Gipfeln)
- "Bei Westwind und feuchtem Mittelland Vorsicht in den Berner Voralpen" — plausibel, ohne Zahlen-Backing

---

## 5. Schweizer Spezifika — Befundlage

| Phaenomen | Quantitative Studie? | Mechanik plausibel? | Operationell nutzbar? |
|-----------|---------------------|---------------------|------------------------|
| Alpine Pumping Mittelland→Voralpen | Ja (Lugauer/Winkler, Weissmann) | Ja | **Ja** |
| Mountain Venting Alpen | Ja (Henne 2005) | Ja | Ja (als Cloudbase-Caveat) |
| Maloja-Wind (Po → Engadin) | Phaenomenologisch dokumentiert, **keine quantitative Cloudbase-Studie** | Ja (analog Alpine Pumping) | Bedingt (als Heuristik) |
| Mittelland → Voralpen Feuchtebruecke | Keine CH-spezifische Studie, aber Alpine-Pumping-Befunde uebertragbar | Ja | Ja |
| Bodensee/Genfersee-Brisen auf Konvektion | Keine quantitative Studie | Schwach (Talwind ueberlagert) | Nein |
| Po → Tessin/Wallis | Klimatologie zu Sued-Stau, aber **nicht zur Feuchtebruecke** | Plausibel | Bedingt |

**Ehrliche Einschaetzung**: Fuer die spezifisch-schweizerischen Inter-Regional-Effekte gibt es **viel Folklore und wenig Zahlen**. Die robusteste Saeule ist Alpine Pumping als Tages-Indikator.

---

## 6. Was REGTHERM ueberholt hat — und was nicht

**Ueberholt durch moderne NWP**:
- "Synoptische Modelle loesen Taeler nicht auf" — falsch. ICON-CH1 (1 km), CH2 (2 km), AROME-Alps (1.3 km) loesen Schweizer Taeler auf, sind teils konvektions-permittierend
- "Parametrisierung statt explizite Konvektion" — CH1 ist convection-permitting
- 1D→2D als Architektur-Sprung ist 2001-Denken. Heute hat man 3D NWP mit 1 km

**Nicht ueberholt — bleibt unser Bereich**:
- Auch 1-km-NWP gibt **keine Climbrates fuer 50–200 m breite Thermiken** (sub-grid)
- Die **systematische Wirkung** der Inter-Regional-Advektion auf das Parcel-Profil wird in operationellen Modellen nicht explizit ausgegeben
- Open-Meteo APIs exponieren CBL-Transport nicht direkt
- Unser pro-Spot-isolierter Ansatz ignoriert diesen Effekt vollstaendig

---

## 7. Konkrete Umsetzungs-Optionen — nach Quellenstaerke

### Option A: Alpine-Pumping-Tag-Flag (HOECHSTE Quellenstaerke)

**Quellen**: Lugauer/Winkler, Weissmann 2005, Graf 2016.

**Diagnostik**:
1. Globalstrahlung > 20 MJ/m² Tagessumme (Schoenwetter)
2. Synoptischer Wind < 5 m/s auf 700 hPa
3. Bodenwind-Konvergenz Richtung Alpen-Hauptachse

**Ausgabe**: Boolean Flag pro Tag + Caveat-Text im Wetterlage-Block:
- Mittelland-Spots: "Feuchteexport, am Nachmittag Cu-Reduktion moeglich"
- Alpen-Spots: "Feuchteimport, Cloudbase kann frueher sinken als Spot-Forecast zeigt"

**Erwartete Trefferquote**: 42 % der warmen Halbjahres-Tage.

**Risiko**: Niedrig. Kein Eingriff in Ratings, nur Zusatz-Info.

### Option B: Feuchteadvektions-Indikator zwischen Nachbar-Regionen (MITTLERE Quellenstaerke)

**Quellen**: Henne 2005, TEAMx-PC22.

**Diagnostik**: q_v auf 850 hPa (oder BL-Mittel) upwind (10–30 km gegen Wind) minus q_v am Spot.

**Schwelle**: ≥ +1 g/kg upwind UND Bodenwind > 1.5 m/s aus dieser Richtung → "Cloudbase tendenziell tiefer als Parcel-Rechnung"

**Voraussetzung**: Adjazenz-Graph zwischen Regionen (aus bestehenden Polygonen ableitbar).

**Risiko**: Mittel. Doppelzaehlungs-Risiko, wenn ICON-CH2 den Effekt teilweise schon aufloest.

### Option C: Wagner-Steepness-Modifier (NEUARTIG, gut publiziert)

**Quelle**: Wagner et al. 2023 WCD.

**Diagnostik**: Pro Spot Hangwinkel berechnen (aus DEM oder elevation_ref-Gradient).

**Modifikator**: Bei Hangwinkel > 20 % UND hochalpiner Zone → effektive nutzbare Steighoehe reduzieren (Faktor noch zu kalibrieren).

**Risiko**: Hoch. Greift in bestehende Thermik-Berechnung ein, braucht XContest-Validierung.

### Was NICHT zu bauen ist

- **Voller 2D-Druckgradient-Solver** (REGTHERM-Style) — disproportional zum Nutzen, massive Kalibrierungs-Schulden, ICON-CH2 macht das implizit besser
- **Region-zu-Region-Lookup-Tabellen** — existieren nirgends in der Literatur, Doppelzaehlungs-Risiko
- **Aktive Advektions-Simulation in der CBL** — Open-Meteo gibt die noetigen Layer nicht sauber raus

---

## 8. Quellen

### Peer-reviewed
- [Henne et al. 2005 — Climatology of Mountain Venting–Induced Elevated Moisture Layers, J. Appl. Meteor. Climatol.](https://journals.ametsoc.org/view/journals/apme/44/5/jam2217.1.xml)
- [Weissmann et al. 2005 — Alpine Mountain–Plain Circulation, Monthly Weather Review (VERTIKATOR)](https://journals.ametsoc.org/view/journals/mwre/133/11/mwr3012.1.xml)
- [Graf et al. 2016 — Identification and Climatology of Alpine Pumping, Frontiers in Earth Science](https://www.frontiersin.org/journals/earth-science/articles/10.3389/feart.2016.00005/full)
- [De Wekker & Kossmann 2015 — Convective Boundary Layer Heights over Mountainous Terrain (Review), Frontiers in Earth Science](https://www.frontiersin.org/journals/earth-science/articles/10.3389/feart.2015.00077/full)
- [Wagner et al. 2023 — Adverse impact of terrain steepness on orographic convection, Weather and Climate Dynamics](https://wcd.copernicus.org/articles/4/725/2023/)
- [TEAMx-PC22 Alpine Field Campaign Overview, arXiv 2401.06500](https://arxiv.org/abs/2401.06500)

### Operationelle Systeme
- [Soaringmeteo Modell-Dokumentation](https://soaringmeteo.org/?lang=en)
- [RASP BLIPMAP Parameters](http://www.drjack.info/rasp/info/parameters.html)
- [REGTHERM 2001 — Liechti, OSTIV Technical Soaring](https://ts.ostiv.org/index.php/ts/article/view/279)
- [XC Therm Regtherm](https://xctherm.com/en/regtherm)

### Schweizer Kontext
- [MeteoSwiss — Gewitterklimatologie](https://www.meteoswiss.admin.ch/weather/weather-and-climate-from-a-to-z/thunderstorms/thunderstorm-and-lightning-frequency-in-switzerland.html)
- [MeteoSwiss — Land- und Seewinde](https://www.meteoswiss.admin.ch/weather/weather-and-climate-from-a-to-z/land-and-sea-breezes.html)
- [Maloja Wind — SKYbrary](https://skybrary.aero/articles/maloja-wind)
