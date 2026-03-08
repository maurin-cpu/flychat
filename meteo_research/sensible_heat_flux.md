# Sensibler Warmefluss (H): Recherche-Ergebnisse

## Energiebilanz am Boden

Die Sonnenenergie am Boden wird aufgeteilt in:
- **H** (sensibler Warmefluss): Heizung der Luft -> treibt Thermik
- **LE** (latenter Warmefluss): Verdunstung von Wasser -> keine Thermik
- **G** (Bodenwarmefluss): Erwarmung des Bodens

Das Verhaltnis H/LE heisst Bowen-Ratio (B). Hoher B = mehr Thermik pro Sonnenwatt.

## Gemessene H-Werte im Marz (Zentraleuropa)

### Mittelland (~500m)
- Vegetation im Marz: Schlafend, braunes Gras, teilweise nackter Boden
- Bodenfeuchte: Maessig bis hoch (Schneeschmelze, Fruhlingsregen)
- Bowen-Ratio: 1.0-3.0 an trockenen Tagen
- Nettostrahlung Mittag (klar): ~350-450 W/m2
- **Typischer H-Peak: 150-250 W/m2**
- **Starker Tag (trocken, klar): bis 260 W/m2**

Referenz: Iowa Feldmessungen (ahnliche Bedingungen - schlafende Vegetation):
- Rn Peak: ~300 W/m2, H Peak: ~200 W/m2
- H/Rn ~ 0.67, Bowen ~ 2.0

### Alpen (~2000m)
- Oberflachen: Fels, Geroll, sparlisches Alpengras (schlafend), Schneeflecken
- Felsoberflachen: Praktisch keine Feuchtigkeit -> B >> 5 (fast alles wird H)
- Albedo Fels: 0.10-0.20 (dunkler als Gras mit 0.20-0.25)
- Atmosphare dunner -> 5-10% mehr Globalstrahlung als im Tal
- **H uber sonnenexponierten Felswanden: 250-350 W/m2 physikalisch realistisch**
- **Uber gemischtem Terrain (Fels+Schnee): 200-280 W/m2**

Referenz: PERMOS-Studie (Jahresmittel 7-18 W/m2, aber das inkludiert Nacht+Winter -> nicht vergleichbar mit Peak)

## Bewertung unserer aktuellen H-Caps

| Terrain | Aktuell | Realistischer Peak | Vorschlag |
|---------|---------|-------------------|-----------|
| Mittelland spring | 220 W/m2 | 200-260 W/m2 | **250 W/m2** |
| Alpin spring | 280 W/m2 | 280-350 W/m2 | **310 W/m2** |

Die aktuellen Caps schneiden die besten ~10-15% der Fruhlingstage ab. Die vorgeschlagenen Werte sind physikalisch fundiert, reprasentieren aber das obere Ende und greifen nur an den starksten Tagen.

## Strahlungskoeffizienten

Unser Modell schatzt H aus Strahlung weil Open-Meteo H nicht liefert:
`H = direct_radiation * dir_coeff + diffuse_radiation * diff_coeff`

### Bewertung
- Physikalisch solider Ansatz (etabliert in Fernerkundungs-ET-Modellen: SEBAL, METRIC)
- Spring `direct_radiation_to_H = 0.25` ergibt bei 500 W/m2 Direktstrahlung nur 125 W/m2
- Mit Diffus (~150 W/m2 * 0.10 = 15 W/m2) total ~140 W/m2
- Das ist **etwas tief** fur die besten Marz-Tage (200+ erwartet)

| Parameter | Aktuell | Vorschlag |
|-----------|---------|-----------|
| direct_radiation_to_H (spring) | 0.25 | **0.28** |

## ICON-CH1 und H-Werte

- ICON-Modell berechnet ASHFL_S (sensible heat flux) intern
- Open-Meteo API liefert diesen Parameter aber NICHT
- Unsere Schatzung aus Strahlung ist daher der richtige Ansatz
- MeteoSwiss Open Data konnte ASHFL_S enthalten (nicht verifiziert)

## Quellen
- Swiss FluxNet (ETH Zurich): https://www.swissfluxnet.ethz.ch/
- PERMOS Energy Balance: https://essd.copernicus.org/articles/14/1531/2022/
- Open-Meteo API Docs: https://open-meteo.com/en/docs
- MeteoSwiss ICON-CH1 Docs: https://opendatadocs.meteoswiss.ch/
- Nebraska Grassland Heat Flux Study: Nature Scientific Reports 2024
