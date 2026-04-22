# Wettbewerbsanalyse: Gleitschirm-Wetter-App mit KI/LLM

**Produkt:** Gleitcast -- KI/LLM-Integration in eine Gleitschirm-Wetter-App zur Gebietsfindung und Flugplanung
**Zielgruppe:** Gleitschirmpiloten
**Erstellt:** 2026-03-06
**Methodik:** Competitor & Alternative Pages Framework (Deep Research)

---

## TL;DR

Burnair ist ein starkes Ökosystem, aber teuer und Alpen-zentrisch. Windy ist der Industriestandard, aber ein reines Rohdaten-Tool ohne Interpretation. Paraglidable bietet die simpelste Antwort ("Kann ich fliegen?"), aber ohne Transparenz oder Details. Meteo-Parapente hat das beste Wettermodell, aber eine veraltete UI und keine Empfehlungen. **Kein einziges Tool beantwortet aktuell die zentrale Pilotenfrage: "Wo genau soll ich heute fliegen und warum?"** -- und genau das ist der USP von Gleitcast.

---

## Detaillierter Wettbewerbsvergleich

### 1. Burnair (burnair.ch)

**Positionierung:** All-in-One-Multitool für Gleitschirmpiloten (Schweiz/Alpen)
**Pricing:** Free (Basis-Safety) | EUR 59/Jahr Basic | EUR 129/Jahr Premium
**Apps:** burnair Map (iOS/Android) + burnair Go (iOS/Android)

**Stärken:**
- All-in-One-Ökosystem (Map + Go = Planung + Flug)
- KK7-Thermikdaten + Live-Thermik anderer Piloten
- XC-Routenvorschläge mit Schlüsselstellen-Erklärungen
- Starke Community (Academy, Events, Live-Tracking)
- Talwindsysteme visuell dargestellt
- Kabel-/Hindernisswarnungen
- Echtzeit-Regenradar (EURADCOM)

**Schwächen bei Dateninterpretation & UX:**
- Kein LLM/KI: Empfehlungen sind regelbasiert, nicht kontextadaptiv
- Zwei separate Apps (Map + Go) = fragmentierte UX
- EUR 129/Jahr für Premium = hohe Eintrittsbarriere
- Primär Schweiz/Alpen -- internationale Piloten bekommen weniger Wert
- Kein "Morning Briefing" als automatische, personalisierte Empfehlung
- Inhalte & Community überwiegend deutschsprachig

**Bewertung:** Stärkster direkter Wettbewerber -- aber kein KI-gestütztes "Wo soll ich hin?"-Feature.

---

### 2. Windy (windy.com)

**Positionierung:** Globale Wetter-Visualisierungsplattform (nicht PG-spezifisch)
**Pricing:** Free (mit Werbung) | ~USD 25/Jahr Premium
**Apps:** iOS + Android + Web

**Stärken:**
- Multi-Modell-Vergleich (GFS, ECMWF, ICON, AROME...)
- 35+ Wetterlayer, global verfügbar
- Sounding/Skew-T über Community-Plugin
- Starke Markenbekanntheit, riesige Nutzerbasis
- Webcam-Integration
- 12.100+ Paragliding-Spots weltweit (Qualität variiert)

**Schwächen bei Dateninterpretation & UX:**
- **Null Interpretation für Gleitschirmfliegen** -- reines Visualisierungstool
- Sounding-Plugin auf Mobil "quasi unbenutzbar" (Größenprobleme)
- Paragliding-Spots-Datenbank unzuverlässig (teils in CTR-Gebieten)
- 35+ Layer = Überforderung für Anfänger/Intermediate-Piloten
- Wiederholte Preiserhöhungen (24-35% in 2025) verärgern Community
- Keine Flyability-Scores, keine Gebietsempfehlungen

**Bewertung:** Der Platzhirsch -- aber ein generisches Wetter-Tool, das Piloten zwingt, selbst Meteorologen zu sein.

---

### 3. Paraglidable (paraglidable.com)

**Positionierung:** KI-basierte Flugbedingungsvorhersage
**Pricing:** Komplett kostenlos, Open Source (GPL v3)
**Apps:** Android + Web (kein iOS)

**Stärken:**
- KI-basierter Flyability-Score (neuronales Netz, ~200 Parameter, ~2 Mio. Flüge als Trainingsdaten)
- Crossability-Score (XC-Potenzial separat)
- Simpelste Antwort auf "Kann ich fliegen?" im gesamten Markt
- 10-Tages-Vorhersage
- Integration mit where2fly
- Windy-Plugin verfügbar

**Schwächen bei Dateninterpretation & UX:**
- **Black-Box-KI**: Zeigt Score, aber nicht WARUM -- Piloten lernen nichts
- Kein Detail: Keine Windgeschwindigkeiten, Thermikstärke, Wolkenbasis
- Nur Europa
- Keine iOS-App (nur Android + Web)
- Ein-Mann-Projekt -- Nachhaltigkeitsrisiko
- Keine Echtzeit-Daten (nur Modellprognosen)
- Kein Konfidenzniveau -- wie sicher ist die Vorhersage?

**Bewertung:** Der konzeptionell nächste Wettbewerber -- beweist, dass Piloten KI-Interpretation WOLLEN. Aber zu oberflächlich, zu intransparent, zu limitiert.

---

### 4. Meteo-Parapente (meteo-parapente.com)

**Positionierung:** Spezialisierte Gleitschirm-Meteorologie mit eigenem Wettermodell
**Pricing:** Free (Basis) | ~EUR 36/Jahr (Contributor)
**Apps:** iOS + Android + Web

**Stärken:**
- **Eigenes proprietäres Wettermodell** (2.5 km Auflösung, konvektionsauflösend)
- Beste Thermik-Velocity-Maps im Markt
- Grenzschichthöhen-Karten (direkt relevant für max. Flughöhe)
- Windgramm in Metern statt Druckleveln (pilotenfreundlicher)
- EUR 36/Jahr = sehr fair bepreist
- 4x tägliche Updates
- 24+ europäische Länder
- KI-basierte Modell-Synchronisation

**Schwächen bei Dateninterpretation & UX:**
- **Keine Go/No-Go-Empfehlung** -- Piloten müssen selbst interpretieren
- Veraltete UI ("Jahre hinter anderen Apps")
- Favoriten nur lokal gespeichert -- kein Cloud-Sync
- Farbcodes/Legenden schlecht dokumentiert
- Nur Europa
- Niederschlagsvorhersage als bekannte Schwäche
- Keine Community-Features, kein Live-Tracking

**Bewertung:** Bestes Daten-Fundament, schlechteste UX. Ideal als Datenquelle -- aber nicht als Endnutzer-Erlebnis.

---

### 5. Allgemeine Wetter-Apps (yr.no, Meteoblue, WeatherPro)

**Relevanz für Gleitschirmfliegen:**
- **yr.no:** Exzellent für Grundwetter, komplett kostenlos, keine Werbung. Aber null Flug-Relevanz (kein Höhenwind, keine Thermik)
- **Meteoblue:** Einziger General-App mit Thermik-Prognose & Sounding -- aber Feature schwer auffindbar. Eigenes Wettermodell. MultiModel-Vergleich.
- **WeatherPro:** Irrelevant für Gleitschirmfliegen

**Schwächen für Paragliding-Nutzung:**
- Kein Höhenwind (nur Bodenlevel)
- Keine Thermik-Prognosen (außer Meteoblue)
- Keine Luftrauminformationen
- Keine Start-/Landeplatz-Datenbanken
- Wind ohne Kontext ("12 km/h" -- ist das sicher für Paragliding?)

**Bewertung:** Ergänzungstools, keine echte Konkurrenz.

---

## Schwächenmatrix: Wo alle versagen

| Schwäche | Burnair | Windy | Paraglidable | Meteo-Parapente | General |
|---|---|---|---|---|---|
| **Keine personalisierte Gebietsempfehlung** | Teilweise | Komplett | Teilweise | Komplett | Komplett |
| **Keine natürlichsprachliche Erklärung** | Ja | Ja | Ja | Ja | Ja |
| **Informationsüberflutung** | Mittel | Extrem | Nein | Hoch | Nein |
| **Expertise-Barriere hoch** | Mittel | Sehr hoch | Niedrig | Hoch | N/A |
| **Kein "Morning Briefing"** | Ja | Ja | Ja | Ja | Ja |
| **Kein "Warum?" bei Empfehlung** | Teilweise | N/A | Ja (Black-Box) | N/A | N/A |

---

## Vergleichstabelle: Alle Wettbewerber auf einen Blick

| Dimension | Burnair | Windy | Paraglidable | Meteo-Parapente | General Apps |
|---|---|---|---|---|---|
| **Target Audience** | Swiss/Alpine Piloten, alle Levels | Outdoor-Enthusiasten, intermediate+ Piloten | Casual Piloten, schnelle Antwort | Intermediate-Advanced Piloten (Europa) | Allgemein |
| **Pricing** | EUR 59-129/Jahr | Free; ~USD 25/Jahr Premium | Free | ~EUR 36/Jahr | Free bis Low-Cost |
| **Coverage** | Primär Alpen/Europa | Global | Nur Europa | 24+ europäische Länder | Global |
| **Interpretationslevel** | Hoch (Empfehlungen, XC-Vorschläge) | Niedrig (nur Rohdaten) | Sehr hoch (KI Flyability-Score) | Mittel (PG-kontextualisiert) | Keine bis niedrig |
| **Thermikdaten** | KK7-Karten, Live-Thermik | Via Plugins/Soundings | Im KI-Score eingebettet | Proprietäre Thermik-Velocity-Maps | Nur Meteoblue |
| **Live-Daten** | Windstationen, Live-Tracking, Radar | Wetterstationen, Radar | Keine | Keine | Wetterstationen |
| **Social/Community** | Stark (Tracking, Events, Academy) | Forum/Plugin-Community | Keine | Keine | Keine |
| **Mobile Apps** | iOS + Android (2 Apps) | iOS + Android | Nur Android | iOS + Android | iOS + Android |
| **Eigenes Wettermodell** | Nein (nutzt KK7 etc.) | Nein (aggregiert Modelle) | Nein (Drittanbieter + KI) | Ja (proprietär, 2.5km) | Meteoblue: ja |
| **Unique Strength** | All-in-One mit Live-Tracking & Community | Modellvergleich & globale Abdeckung | Simpelste Antwort auf "Kann ich fliegen?" | Bestes PG-spezifisches Atmosphärenmodell | Kostenlos, breit verfügbar |
| **Biggest Weakness** | Swiss-zentrisch, teuer | Keine PG-Interpretation, unzuverlässige Spots | Black-Box, nur Europa, kein Detail | Nur Europa, veraltete UI | Keine PG-Relevanz |

---

## Positionierungsmatrix

```
                    HOHE INTERPRETATION
                          |
                    [GLEITCAST]
                     KI + LLM
                    "Wo & Warum"
                          |
     Paraglidable --------+
     (Score ohne           |
      Erklärung)           |
                           |
EINFACH --------+----------+----------+-------- KOMPLEX
                |          |          |
                |          |     Burnair
                |          |     (Ökosystem)
                |          |
                |     Meteo-Parapente
                |     (beste Daten,
                |      schlechte UX)
                |          |
                +----------+
                           |
                        Windy
                    (Rohdaten-King)
                           |
                  NIEDRIGE INTERPRETATION
```

---

## Glasklarer USP

### "Der erste KI-Co-Pilot, der dir sagt WO du fliegen sollst, WARUM und WANN -- in einem Satz."

| USP-Element | Was es bedeutet | Warum kein Wettbewerber das hat |
|---|---|---|
| **Personalisierte Gebietsempfehlung** | "Fliege heute ab 13 Uhr am Brauneck -- SW-Wind 15 km/h, Thermik bis 2.200m, Basis bei 2.500m" | Burnair zeigt Daten pro Gebiet, empfiehlt aber nicht DAS Gebiet. Paraglidable zeigt einen Score, aber nicht WO. |
| **Natürlichsprachliche Erklärung (LLM)** | "Die Südwestlage bringt heute trockene Luft in die Nordalpen. Das Brauneck profitiert von der Hangexposition und dem Talwind aus dem Isartal." | Kein Tool erklärt das "Warum" in verständlicher Sprache. Alle zeigen Karten/Zahlen. |
| **Transparente KI** | Zeigt die Datenbasis hinter der Empfehlung + Konfidenz-Level | Paraglidable ist eine Black Box. Gleitcast sagt "85% sicher, weil 3 von 4 Modellen übereinstimmen." |
| **Kontextuelle Entscheidungshilfe** | Berücksichtigt Pilot-Level, Fahrtstrecke, Tageszeit-Präferenzen | Kein Tool berücksichtigt den individuellen Piloten. Alle zeigen allen dasselbe. |

---

## Positioning Statement

> **Gleitcast ist der KI-Co-Pilot für Gleitschirmflieger. Während andere Apps dir Wetterdaten zeigen, sagt dir Gleitcast wo du heute fliegen sollst -- und erklärt dir warum. Statt 7 Webseiten in 30 Sekunden zur besten Entscheidung.**

---

## Strategische Positionierung

### Wer Gleitcast NICHT sein sollte:
- Kein zweites Windy (Rohdaten-Visualisierung)
- Kein zweites Burnair (All-in-One-Ökosystem mit Live-Tracking)
- Kein zweites Meteo-Parapente (eigenes Wettermodell)

### Wer Gleitcast sein sollte:
- Die **Intelligenz-Schicht** die auf bestehenden Datenquellen aufbaut
- Das **ChatGPT für Flugwetter** -- natürlichsprachliche Interaktion
- Der **Entscheidungs-Beschleuniger** der 45 Minuten Analyse auf 30 Sekunden reduziert

### Komplementäre Positionierung statt Konfrontation:
Stärkster strategischer Zug: Sich NICHT als Ersatz, sondern als **Ergänzungsschicht** positionieren, die bestehende Daten intelligent zusammenführt.

> "Gleitcast nutzt Daten von Meteo-Parapente, ECMWF, GFS und mehr -- und macht daraus eine klare Empfehlung."

---

## Marktlücken & Chancen

1. **Die Interpretationslücke ist die größte Chance:** Kein Tool bridget aktuell die Lücke zwischen "hier sind die Wetterdaten" und "hier ist was das für DEINEN Flug heute an DIESEM Gebiet bedeutet"
2. **Mobile-First Erlebnis fehlt:** Windy-Plugins brechen auf Mobil, Paraglidable hat kein iOS, Meteo-Parapente hat veraltete UI, Burnair braucht zwei Apps
3. **Geografische Fragmentierung:** Meteo-Parapente, Paraglidable und Burnair sind Europa-only. Globale PG-spezifische Interpretation existiert nicht
4. **Zahlungsbereitschaft existiert:** Burnair beweist EUR 129/Jahr, Meteo-Parapente EUR 36/Jahr. Piloten zahlen für echten Mehrwert
5. **Community-Features sind unterentwickelt:** Nur Burnair hat echte Social-Features. Piloten sind inherent sozial (geteilte Startplätze, Safety-Tracking, XC-Koordination)
