# Regionale Thermik-Vorhersage: XC-Therm, Burnair & Best Practices

## Regtherm — Das Kern-Modell (Dr. Oliver Liechti)

Regtherm ist ein 1D-Konvektionsmodell, das seit 20+ Jahren operationell laeuft. Entwickelt von Dr. Oliver Liechti (Atmosphaerenphysiker und Segelflieger), urspruenglich als **ALPTHERM** (1994/95, mit Bruno Neininger), dann erweitert zu **REGTHERM** (2001) mit horizontaler Kopplung zwischen Nachbarregionen.

Bis Maerz 2024 lief Regtherm auf DWD-Servern. Danach lizenzierten sowohl XC Therm (Daniel Moser) als auch Burnair (Bernie Hertz) das Modell direkt von Liechti.

### Physikalisches Modell

1. **Energiebudget**: Berechnet Waermeaufnahme der Luft ueber einem Tal unter Beruecksichtigung des **Volumeneffekts** — engere Taeler heizen die darueberliegende Luftsaeule effizienter
2. **Input-Parameter**:
   - Radiosondenaufstieg der naechsten luvseitigen Station
   - Bodentemperatur/-feuchte in der Region
   - NWP-Vorhersagen (ICON-D2/EU)
   - Bodenfeuchte, Beschattung, Vegetationszustand
3. **Output** (30-Min-Intervalle):
   - Steigwerte (m/s)
   - Wolkenbasis (LCL)
   - Cumulusentwicklung (Groesse, Bedeckung)
   - Arbeitshöhe (Dicke der konvektiven Schicht mit durchgehendem Steigen)
   - Grenzschichtobergrenze
4. **Talwind-Kopplung** (REGTHERM-Innovation): Kompensationsstroemungen aus tiefer gelegenen Nachbarregionen transportieren feuchte Luft in alpine Taeler, veraendern Luftmasseneigenschaften und senken oft die Basis

> **Update Mai 2026**: Die peer-reviewed Literatur seit 2001 hat REGTHERMs Kopplungs-Konzept praezisiert. Siehe `meteo_research/inter_regional_coupling.md` fuer Henne 2005 (Mountain Venting), Lugauer/Winkler & Weissmann 2005 (Alpine Pumping als 42%-Phaenomen), TEAMx-PC22 (Advektion dominiert CBL-Wachstum) und Wagner 2023 (Steepness vs. Niederschlagseffizienz) — plus konkrete Umsetzungs-Optionen fuer unser System.

### Regionen-Definition

- **Topographische Kohaerenz**: Grenzen folgen Talverlaeufen, Gebirgskaemmen, Paessen
- **Kriterien**: Talbodenhoehe, Talvolumen, Gebirgskammverlauf, mittlere Gelaendehoehe
- **"So klein wie noetig"** um Luftmassenunterschiede zu erfassen, aber klar/nutzbar
- **1'354 Regionen** europaweit (Stand 2024): CH 44, AT 68, DE 130, FR 190, IT 160, ES 125
- Lokale Piloten wurden zur Verfeinerung der Grenzen konsultiert

### Referenzpunkte

- **1 Referenzpunkt pro Region** am Talboden
- Bewaehrt seit 20+ Jahren, aber bekannte Limitation: "Der Referenzpunkt ist nicht immer der repraesentativste Ort"

### PFD-Berechnung (Potenzielle Flugdistanz)

Pro 30-Min-Intervall:
1. **Steigphase**: Zeit fuer Aufstieg von H_min nach H_max mit modellierter Thermikstaerke
2. **Gleitphase**: Strecke waehrend Abstieg (Flugzeug-Polare/Sinkrate)
3. **Durchschnittsgeschwindigkeit** = Distanz / (Steigzeit + Gleitzeit)

Schwellwerte:
- Arbeitshöhe < 900m → 0 km fuer dieses Intervall
- Steigrate < 0.8 m/s → 0 km fuer dieses Intervall
- Wind > 30 km/h (Gleitschirm) → 0 km

**Nicht modelliert**: Foehn, Talwind-Rueckenwind, Niederschlag, Mikrometeo unterhalb Modellaufloesung.

Quellen: [REGTHERM 2001 (Technical Soaring)](https://ts.ostiv.org/index.php/ts/article/view/279), [ALPTHERM (Technical Soaring)](https://ts.ostiv.org/index.php/ts/article/view/218)

---

## XC Therm (xctherm.com)

### Modell-Input

| Modell | Aufloesung | Reichweite | Verwendung |
|--------|-----------|------------|-----------|
| ICON-D2 | 2.2 km | 48h | Tag 0-1 (DACH) |
| ICON-EU | 6.5 km | 120h | Tag 2-5 |
| ICON-CH1 | 1.0 km | 45h | Wind/Wetter (Abo) |
| ICON-CH2 | 2.1 km | 120h | Wind/Wetter (Abo) |

### Darstellung

- Interaktive Karte mit farbigen Region-Polygonen
- PFD-Werte (km) als Zahl auf der Region
- Farbintensitaet repraesentiert PFD-Groesse
- Keine Safety-Gewichtung: Hohe PFD kann bei gefaehrlichen Bedingungen angezeigt werden

### Update-Frequenz

- ICON-D2 basiert: bis 6x taeglich (01:45, 04:30, 14:00, 20:00 UTC)
- ICON-EU basiert: bis 3x taeglich (00:30, 03:30, 06:15 UTC)

Quellen: [XC Therm Regtherm](https://xctherm.com/en/regtherm), [XC Therm FAQ](https://xctherm.com/en/faq)

---

## Burnair (burnair.ch)

### Schluessel-Unterschied: Safety-gewichteter Algorithmus

Burnair nutzt Regtherm als Basis, legt aber einen eigenen **proprietaeren 40-Parameter-Algorithmus** darueber:

- Thermikstaerke
- Wolkenbasis
- **Windgradienten ueber die GESAMTE Region** (nicht nur am Referenzpunkt — "4D"-Analyse)
- Niederschlag, Inversionen, Gewitterrisiko, Boenintensitaet
- Saisonale Kalibrierung ("Hammertag im Winter hat andere Kriterien als im Hochsommer")
- Unterscheidung Flachland vs. Gebirge
- Jaehrliche Verfeinerung anhand tatsaechlich geflogener Distanzen

### 5-Farben-System

| Farbe | Bedeutung |
|-------|-----------|
| **Blau** | Potenzieller "Hammertag" — exzellente XC-Bedingungen |
| **Gruen** | Gute XC-Region |
| **Gelb** | Regionale Thermikfluege moeglich |
| **Grau** | Schwache Thermik, Abgleiter-Potenzial |
| **Rot/Pink** | Fliegen NICHT empfohlen; Gefahrenwarnung |

**Wichtig**: Farbe kann PFD widersprechen! Region mit PFD=100km kann ROT sein wegen gefaehrlichem Wind (z.B. Nordfoehn im Tessin erzeugt starke Thermik aber extrem gefaehrliche Flugbedingungen).

### Referenzpunkte

- **2 Referenzpunkte pro Region** (graue Kreise auf Karte):
  - Doppelring: ICON-D2 Referenzpunkt
  - Einzelring mit Punkt: ICON-EU Referenzpunkt
- "Algorithmus 2" scannt die gesamte Region fuer Windwerte

### Regionseinteilung

Burnair unterteilt Regionen feiner als XC-Therm. Beispiele:
- "Westliche Voralpen" → Freiburger Voralpen + Emmental + Zentrale Voralpen
- "Berner Oberland" → 3 separate Gebiete
- Alpstein als eigenstaendige Region ("eigenes Luftmassensystem")

Quellen: [burnair Thermik-Prognosen](https://www.burnair.ch/portfolio-item/thermik-prognosen/), [burnair Neue Regionen 2024](https://www.burnair.ch/2024/01/01/neue-regionen-thermik-prognose-2024/), [burnair Verfeinerte Regionen](https://www.burnair.ch/2024/06/20/verfeinerte-thermik-prognosen-regionen/), [burnair Help: PFD vs. Farben](https://help.burnair.cloud/hc/de/articles/4404397322129)

---

## Best Practices fuer regionale Thermik-Vorhersagen

### Referenzpunkte: Wie viele?

| Ansatz | Punkte/Region | Pro | Contra |
|--------|--------------|-----|--------|
| Regtherm | 1 (Talboden) | Einfach, bewaehrt | Ungenau bei untypischem Referenzpunkt |
| Burnair | 2 (ICON-D2 + EU) | Besser, modellspezifisch | Immer noch potenziell ungenau |
| **Wingcast** | **4 (raeumlich verteilt)** | Beste Wolken-/Niederschlagsaggregation | Mehr Datenpunkte im Batch |

### Referenzpunkt-Verteilung

1. **Raeumliche Streuung**: Punkte sollen maximalen Mindestabstand zueinander haben (Greedy-Algorithmus wie in `scripts/create_regionen_geojson.py`)
2. **Hoehenrepraesentation**: `elevation_ref` soll typische Flug-/Starthoehe der Region repraesentieren
3. **Topographische Kohaerenz**: Region darf keine grossen Luftmassengrenzen (Kammlinien, Paesse) ueberqueren
4. **Ueberganszonen**: Grenzen zwischen Regionen sind weiche Uebergaenge, keine harten Linien (SLF-Prinzip: "Es gibt keine klar definierten Grenzen, sondern Uebergangsbereiche")

### Aggregation: Cloud vs. Thermik

**Wolken**: 30th-Perzentil ueber alle Referenzpunkte → findet regionale "Blue Holes" (bewaehrter Regtherm-Ansatz)

**Thermik**: Am Referenzpunkt berechnen, NICHT raeumlich mitteln. Thermik haengt stark von der lokalen Elevation und dem Temperaturprofil ab. Wingcast nutzt korrekterweise die `elevation_ref` der Region als Startpunkt fuer Parcel-Ascent.

**Niederschlag**: Regionale Signifikanz — nur wenn >= 2 von N Punkten Niederschlag melden (vermeidet isolierte Modell-Artefakte).

### Aufloesung: Signal vs. Rauschen

| Ansatz | Aufloesung | Eignung |
|--------|-----------|---------|
| Regtherm (regional) | ~50-100 km Regionen | Leicht interpretierbar, erfasst Tal-Effekte |
| RASP/WRF (Gitter) | 2-6 km | Guter Kompromiss Detail/Interpretierbarkeit |
| Meteo-Parapente (fein) | 2.5 km | Hohe raeumliche Aufloesung, schwer schnell lesbar |
| ICON-D2 (roh) | 2.2 km | Hoechste Aufloesung, erfordert Post-Processing |

Regtherm argumentiert explizit, dass **regionale Aggregation besser als rohe Gitter-Anzeige** ist fuer Pilotenentscheidungen:
- Thermische Zirkulationssysteme (Hang-/Talwind) erzeugen homogene Bedingungen innerhalb von Taelern
- Ein gut gewaehlter Einzelwert ist handlungsfaehiger als ein verrauschtes Gitter
- Talwind-Kopplungseffekte gehen bei reinen Gitter-Ansaetzen verloren

### MeteoSwiss / SLF Analogie

- SLF teilt die Schweiz in **149 Warnregionen** ein (Lawinenbulletin)
- Grenzen werden als **Uebergangszonen** behandelt, nicht harte Linien
- Nutzer nahe Grenzen sollen beide angrenzenden Prognosen konsultieren
- MeteoSwiss plant mit GLORI-A Projekt 500m-Aufloesung fuer alpine Haupttaeler

---

## Wingcast-Positionierung im Vergleich

| Feature | XC Therm | Burnair | **Wingcast** |
|---------|----------|---------|-------------|
| Kern-Modell | Regtherm (lizenziert) | Regtherm + 40-Param-Algo | Eigenes Parcel-Ascent + Encroachment |
| Referenzpunkte/Region | 1 | 2 | **4** (raeumlich verteilt) |
| Wolken-Aggregation | Modell-intern | Modell-intern | **30th-Perzentil** (findet Blue Holes) |
| Safety-Integration | Keine (PFD only) | 40-Param safety-gewichtet | **2-Phasen LLM** (Safety + Flyability) |
| Datenquelle | ICON-D2/EU (DWD direkt) | ICON-D2/EU + AROME | Open-Meteo (ICON-D2/EU/CH1) |
| Farbsystem | PFD-basiert (1 Achse) | 5 Farben (1 Achse, safety-gewichtet) | **2 Achsen** (Safety × Flyability) |
| CH-Regionen | 44 | ~50-60 (feiner unterteilt) | **29** (unsere Polygone) |
| Update-Frequenz | 3-6x taeglich | 3-6x taeglich | On-Demand (Nutzer-gesteuert) |

### Wingcast-Vorteile

1. **Mehr Referenzpunkte** als beide Konkurrenten → bessere raeumliche Abdeckung
2. **Explizite Safety-Flyability-Trennung** → Region kann "conditional + violet" sein (starke Thermik trotz Vorsicht)
3. **LLM-basierte Analyse** → natuerlichsprachliche Erklaerungen statt nur Zahlen/Farben
4. **Transparente Methodik** → Nutzer sieht Stuendliche Daten + KI-Erklaerung

### Wingcast-Limitierungen vs. Konkurrenz

1. **Kein Volumeneffekt** — Regtherm modelliert Tal-Volumen-Heizung explizit
2. **Keine Talwind-Kopplung** — Regtherm beruecksichtigt horizontale Kompensationsstroemungen
3. **Geringere Update-Frequenz** — On-Demand statt automatisch 3-6x taeglich
4. **Weniger Regionen** (29 vs. 44-60) — koennte spaeter verfeinert werden
