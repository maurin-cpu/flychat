# Topographische Heizung: Recherche-Ergebnisse

## Solargeometrie: 30-Grad-SW-Hang im Marz bei 47N

### Berechnete Strahlungsverhaltnisse

Formel: S_hang / S_flach = cos(theta) / sin(alpha)

Am Marz-Aquinoktium (Deklination = 0) bei 47N:
- **Sonnenhochstwinkeel Mittag**: alpha = 90 - 47 = 43 Grad
- sin(alpha) = 0.682

Fur 30-Grad-Sudhang zur Mittagszeit:
- cos(theta) = sin(43+30) = sin(73) = 0.956
- **Verstarkungs-Ratio = 0.956 / 0.682 = 1.40** (40% mehr Direktstrahlung)

Fur SW-Hang (Azimut 225):
- Maximale Verstarkung um ~14:00 wenn Sonne nach SW wandert
- Peak-Verstarkung: ~1.35-1.40x

**Fazit: Ein 30-Grad-Sudhang bekommt im Marz 35-45% mehr Direktstrahlung als Flachland.**

## Warum Fels besonders effektiv heizt

| Eigenschaft | Fels | Gras/Boden |
|------------|------|-----------|
| Albedo | 0.10-0.20 | 0.20-0.25 |
| Feuchtigkeit | ~0 | 10-40% |
| Verdunstung (LE) | ~0 | Signifikant |
| Bowen-Ratio | >>5 | 1-3 |
| Warmeleitfahigkeit | 2-3 W/(mK) | 1.0-1.5 W/(mK) |
| Warmekapazitat | ~800 J/(kgK) | 1000-1500 J/(kgK) |

Fels: Niedrigere Albedo, keine Verdunstung, heizt schneller auf.
Nachteil: Hohere Warmeleitfahigkeit leitet etwas Warme in die Tiefe ab.
Netto: Deutlich mehr H pro Watt Strahlung.

## Bewertung unserer Parameter

### topo_bonus_max (aktuell: 1.3)
- Physik gibt 1.40+ fur 30-Grad-Hange im Marz
- Ein Cap von 1.3 schneidet den realen Bonus ab
- **Vorschlag: 1.4** (physikalisch korrekt, konservative Seite)

### topo_bonus_H_fraction (aktuell: 0.30)
"Wie viel vom Hang-Strahlungsbonus wird tatsachlich Thermik?"

**Argumente fur hoher (0.40-0.50):**
- Fels hat keine Verdunstung -> fast alles wird H
- Niedrigere Albedo -> mehr Absorption
- Topographic Amplification Factor (TAF): Taler/Hange konzentrieren Heizung

**Argumente fur tiefer (0.20-0.35):**
- Nicht alle Hangheizung erzeugt nutzbare Thermik
- Viel geht in anabatischen Hangwind (Schichtaufwind am Hang) statt in Thermik-Ablosungen
- Thermische Tragheit: Ein Teil heizt den Fels selbst
- Spot hat einen Azimut/Winkel, reale Hangflachen variieren

**Vorschlag: 0.40** - Kompromiss, anerkennt die Effizienz von Fels, berucksichtigt aber dass nicht alles Thermik wird.

## Topographic Amplification Factor (TAF)

Aus der Meteorologie: Taler und Berge konzentrieren die Heizung in ein kleineres Luftvolumen als Flachland. Das ist ein zusatzlicher Effekt uber den reinen Strahlungsbonus hinaus. Unser Modell erfasst das nicht direkt, aber der erhohte alpine H_cap kompensiert teilweise.

## Quellen
- PVEducation - Solar Radiation on Tilted Surfaces
- AMS Glossary - Topographic Amplification Factor
- Zardi & Whiteman - Diurnal Mountain Wind Systems
- Valley Volume Effect (ACP 2025)
