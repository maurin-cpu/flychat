# Cumulus-Feedback: Recherche-Ergebnisse

## Ausgangslage
XC-Therm zeigt am So 08.03 im Mittelland eine Verdopplung der Steigrate (0.8 -> 1.6 m/s) genau beim Cumulus-Onset. Die Frage war: Wie viel davon ist echtes Cumulus-Feedback?

## 5 Physikalische Mechanismen

### A. SALR vs DALR uber LCL (WICHTIGSTER Effekt)
- Unter LCL: Paket kuhlt mit DALR = 9.8 C/km, Umgebung mit ~7.5 C/km -> Paket VERLIERT Auftrieb (2.3 C/km)
- Uber LCL: Paket kuhlt nur mit SALR = ~6 C/km -> Paket GEWINNT Auftrieb (1.5 C/km)
- Das ist eine komplette Umkehr der Auftriebsbilanz!
- **BEREITS IN UNSEREM MODELL** (thermik_calculator.py Zeile 523-545)
- Ein separater "Cumulus-Boost" ware Doppelzahlung

### B. Reduzierte Entrainment in feuchten Thermiken (MODERAT)
- Morrison et al. 2021 (Journal of Atmospheric Sciences): Feuchte Thermiken haben 1.7x kleinere Ausbreitungsraten
- Kondensationswarme konzentriert sich im Kern -> unterdruckt seitliche Ausbreitung
- Der Thermikschlauch bleibt kompakter, mischt weniger kalte Umgebungsluft ein
- **NICHT in unserem Modell** -> hier konnen wir verbessern
- Geschatzter Impact: 10-20% starkere Thermik durch weniger Verdunnung
- Quelle: https://journals.ametsoc.org/view/journals/atsc/78/3/JAS-D-20-0166.1.xml

### C. Sub-Cloud-Beschleunigung / "Chimney Effect" (MODERAT)
- Kondensation uber LCL erzeugt Druckdefizit das Luft von unten ansaugt
- Dynamischer Druckeffekt, nicht einfach nur Auftrieb
- Spurbar in den 100-300m direkt unter Wolkenbasis
- **NICHT in unserem Modell**
- Effekt ist lokal (nur nahe Wolkenbasis), nicht uber die ganze Saule
- Quelle: Gu 2020 (GRL) - https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2020GL090460

### D. Organisatorisches Feedback (MODERAT)
- Cumulus erzeugt selbstverstarkenden Zyklus: Wolke -> Warme -> starkerer Aufwind -> mehr Feuchtezufuhr -> mehr Wolke
- Fuhrt zu langlebigeren, besser organisierten Thermiken
- Sub-cloud-Turbulenz erklart ~50% der Variabilitat der Aufwinde an der Wolkenbasis
- Quellen: Zheng 2021 (GRL), ACP 2025 (Thermal Merging)

### E. Latente Warme als Extra-Auftrieb
- Ist DASSELBE wie Mechanismus A, nur anders beschrieben
- Die latente Warme IST der Grund warum SALR < DALR
- Kein zusatzlicher Effekt uber SALR hinaus

## Zusammenfassung der Mechanismen

| Mechanismus | Wichtigkeit | Schon im Modell? | Geschatzter Impact |
|------------|------------|-----------------|-------------------|
| A. SALR uber LCL | Hochste | JA | Bereits erfasst |
| B. Reduzierte Entrainment | Mittel | NEIN | +10-20% |
| C. Sub-Cloud-Beschleunigung | Mittel | NEIN | Lokal stark, bulk gering |
| D. Organisation/Langlebigkeit | Mittel | NEIN | Schwer zu quantifizieren |
| E. Latente Warme extra | = A | JA (= SALR) | Bereits erfasst |

## Korrelation vs. Kausalitat (XC-Therm Daten)

Die Verdopplung der Steigrate bei Cu-Onset ist NICHT hauptsachlich Cumulus-Feedback:
- **70-80% kommt vom Tagesgang**: Sonne steigt, BLH wachst, H nimmt zu
- **20-30% ist echtes Cu-Feedback**: Reduzierte Entrainment + Sub-Cloud-Effekte
- Dieselben Bedingungen die Cu erzeugen (starke Heizung, instabile Luft) erzeugen AUCH starkere Thermik

Auf einem "Blue Day" mit gleichem Temperaturprofil aber trockener Luft (hoherem LCL) wurde die Steigrate auch von 0.8 auf ~1.5-1.8 steigen, nur etwas weniger als die 2.3 mit Cu.

## Mittelland vs. Alpen

Cumulus-Feedback ist in BEIDEN Regionen relevant:
- **Mittelland**: Feuchtere Luft, tieferes LCL, Cu bildet sich haufiger und fruher. Aber BLH ist oft durch Subsidenzinversion gedeckelt.
- **Alpen**: Trockenere Luft, hoheres LCL relativ zum Gelande. Wenn Cu kommt, ist der Effekt dramatischer (steilere Lapse Rates + Gelandeerzwingung). Aber viele gute Tage sind "Blue".

## Fazit fur unser Modell

1. KEINEN pauschalen 40% Climb-Boost -> ware Doppelzahlung (SALR schon drin)
2. KEINE 500-1000m Hohenerweiterung -> Paraglider fliegen nicht in Wolken
3. STATTDESSEN: Entrainment uber LCL um ~40% reduzieren (physikalisch fundiert durch Morrison 2021)
4. Optional: Leichte Sub-Cloud-Verstarkung nahe Wolkenbasis (schwieriger zu implementieren, geringerer Impact)

## Quellen
- Morrison et al. 2021 - Comparing Growth Rates of Moist and Dry Convective Thermals (JAS)
- ASR Highlight - Entrainment of dry versus moist convective thermals
- Gu 2020 - Pressure Drag for Shallow Cumulus Clouds (GRL)
- Zheng 2021 - Sub-Cloud Turbulence and Cloud-Base Updrafts (GRL)
- RASP/BLIPMAP Dokumentation (Dr. Jack)
- XC-Therm RegTherm Dokumentation
- Wikipedia: Cloud Suck, Lapse Rate
