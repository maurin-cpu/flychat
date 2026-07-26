# Fronten aus Modelldaten ableiten — was die Literatur verlangt und was davon bei uns fehlte

**Erstellt:** 2026-07-26
**Anlass:** Fronten sollen auf der Synoptik-Karte erscheinen. Ein erster
Eigenversuch (`scripts/experiment_fronten_tfp.py`) lieferte Linien ohne
nachweisbares Können. Diese Recherche klärt, ob das am Verfahren liegt oder an
der Umsetzung.

---

## 1. Executive Summary

**Der Eigenversuch war die naive Variante — genau die, von der die Literatur
sagt, dass sie scheitert.** Fünf konkrete Abweichungen (Details in §3):

| | Eigenversuch 26.07. | Literatur-Standard |
|---|---|---|
| Grösse | Θe (äquivalentpotentiell) | **Θw** (Feuchttemperatur-Potential), 850 hPa |
| Glättung | 1× Gauss, σ = 1 Zelle | **8 Durchgänge** 5-Punkt-Mittel bei 0.75°, **96** bei 0.25° |
| Schwellen | fix (3 K/100 km), geraten | **Perzentile der Klimatologie** (TFP P25, Gradient P50) |
| Linien | mask-then-join | **contour-then-mask** — mask-then-join versagt ≤ 0.75° nachweislich |
| Mindestlänge | keine | **250 km**, kürzere Linien verworfen |
| Klassifikation | Advektions-Vorzeichen | **Frontgeschwindigkeit** (Hewson Gl. 13), ±1.5 m/s → warm/kalt/quasistationär |

Die fehlende Glättung und die fehlende Mindestlänge erklären das beobachtete
Bild (viele kurze Fragmente) unmittelbar. **Das Urteil „nicht machbar" ist
damit nicht haltbar — es galt meiner Implementierung, nicht dem Verfahren.**

**Aber:** Der realistische Zielmassstab ist viel niedriger als erwartet. Zwei
*unabhängige menschliche* Analysen desselben Termins stimmen bei der genauen
Frontlage nur zu **23–30 %** überein; auf die Frage „Front vorhanden ja/nein"
in einer groben Rasterzelle immerhin zu 84.8 %. Eine exakte Positionsgleichheit
mit der DWD-Karte ist also kein erreichbares Ziel — auch nicht für Profis.

**Es gibt fertigen Code**: `front_id` (R, offen, Zenodo-DOI) implementiert die
komplette Kette.

---

## 2. Eigene empirische Basis (was gemessen wurde)

`scripts/experiment_fronten_tfp.py`, 13 Termine, zwei Jahreszeiten:

- **Regen-Gegenprobe:** Trefferrate der Linien gegen Grundrate — Faktor im
  Mittel **0.95** (Spanne 0.47–1.63). Die Linien wussten nichts.
- **Auflösung:** 1.0° → 0.5° half nicht (mehr Linien, nicht bessere).
- **Gebirgs-Hypothese geprüft und verworfen:** Frontzellen lagen im Mittel auf
  180 m, das Gesamtfeld auf 170 m; Gebirgsanteil 8.3 % gegen 6.5 %. Kein
  dominanter Orographie-Artefakt in unserem Europa-Fenster — anders als die
  Literatur es für Anden/Grönland/Himalaya berichtet (§3.6).

---

## 3. Antworten auf die Forschungsfragen

### 3.1 Welche Grösse, welches Niveau? (high confidence)
**Θw (wet-bulb potential temperature) auf 850 hPa**, gerechnet aus Temperatur
und spezifischer Feuchte. Hewson (1998) begründet die Wahl damit, dass Θw den
Wasserdampfgehalt mitführt — und der Feuchtesprung macht viele Fronten aus.
Θe (was wir nahmen) ist verwandt, aber nicht die etablierte Grösse; alle
zitierten Klimatologien rechnen mit Θw.

### 3.2 Wie stark wird geglättet? (high confidence) — **der entscheidende Punkt**
Acht Durchgänge eines 5-Punkt-Mittels auf 0.75°. Bei 0.25° (ERA5) sind
**96 Durchgänge** nötig, um dieselben Schwellen-Quantile zu erreichen. Das ist
Grössenordnungen mehr als unser einzelner Gauss mit σ = 1 Zelle. Ohne diese
Glättung erzeugt jedes Rauschen im Temperaturfeld eigene TFP-Nulldurchgänge —
exakt die Fragmente, die wir gesehen haben.

### 3.3 Welche Schwellen? (high confidence)
Nicht geraten, sondern **aus der Klimatologie als Perzentile**:
- TFP-Schwelle = 25. Perzentil der TFP-Verteilung ≈ **−1.6 × 10⁻¹¹ K m⁻²**
  (Nordhemisphäre, ausser Tropen)
- Gradient-Schwelle („adjacent baroclinic zone", ABZ) = 50. Perzentil
  ≈ **7.5 × 10⁻⁶ K m⁻¹** = 0.75 K/100 km

Wichtig: Die ABZ-Bedingung wird **nicht am Linienpunkt** geprüft, sondern eine
halbe Gitterweite in Richtung des stärksten Gradientenanstiegs versetzt — die
Front muss eine kräftige Baroklinzone *neben* sich haben.

### 3.4 Wie entstehen die Linien? (high confidence)
**contour-then-mask**: erst die Nulllinie des Frontlokators (∇·∇∇Θw = 0) als
Kontur ziehen, dann die Maskierungskriterien auf die Konturpunkte
interpolieren. Der umgekehrte Weg (mask-then-join, unser Weg) **versagt bei
Auflösungen ≤ 0.75° nachweislich**, weil das TFP-Kriterium dort oft nur eine
Gitterzelle breit erfüllt ist und die Linien zerfallen.
Danach: **Fronten unter 250 km Gesamtlänge werden verworfen.**

### 3.5 Warm, kalt, stationär? (high confidence)
Über die **Frontgeschwindigkeit** nach Hewson (1998) Gl. 13:
`V · ∇∇Θw / |∇∇Θw|` mit V = Wind auf 850 hPa.
`> +1.5 m/s` = Warmfront, `< −1.5 m/s` = Kaltfront, dazwischen
**quasistationär**. Unsere Advektions-Heuristik kannte keine stationäre Klasse
und hat damit jede Linie zwangsweise in warm oder kalt gepresst.

### 3.6 Was macht das Gebirge? (high/medium confidence)
TFP-Basisverfahren melden nachweislich **Fehl-Fronten entlang von
Gebirgszügen** (Anden, Grönland, Himalaya, Antarktisküste), die in manuellen
Analysen fehlen. Für den Alpenraum existiert eine eigene Arbeit:
**Jenkner et al. (2010)**, COSMO-Reanalyse mit 7 km Maschenweite über
Mitteleuropa. Deren Verfahren ist ausdrücklich so gebaut, dass es „gegen die
Folgen kleiner Gitterweiten unempfindlich" ist, und es **trennt lokale von
synoptischen Fronten** — lokale Fronten sind thermisch/orographisch erzeugt
und gehören nicht in eine Grosswetterlagen-Karte. Diese Trennung ist für uns
Pflicht, nicht Kür: Unsere Nutzer fliegen genau dort.

### 3.7 Welche Genauigkeit ist überhaupt erreichbar? (high confidence)
- Zwei **unabhängige manuelle** Analysen stimmen bei der genauen Frontposition
  nur zu **23–30 %** überein, bei „Front ja/nein" in einer groben Zelle zu
  **84.8 %**.
- Ein U-Net (Deep Learning, 0.25°, neun Modellniveaus) erreicht gegen DWD/NWS
  einen **Critical Success Index von 66.9–68.3 %** — aktueller Stand der
  Technik, braucht aber gelabelte Trainingsdaten.

Konsequenz für die Validierung gegen den DWD-Text: Die Frage muss lauten
„liegt heute eine Front über dem Alpenraum, welchen Typs, wohin zieht sie" —
nicht „stimmt die Linie auf 50 km genau". Letzteres schaffen Menschen
untereinander nicht.

### 3.8 Gibt es fertigen Code? (high confidence)
Ja: **`front_id`** (R, quelloffen, ohne Kompilierung lauffähig),
GitHub `phil-sansom/front_id`, Zenodo-DOI `10.5281/zenodo.7278068`. Umfasst
contour-then-mask, Perzentil-Schwellen, Längenfilter und
Geschwindigkeitsklassifikation. Als Referenz zum Nachbauen in Python
brauchbar, auch wenn wir R nicht produktiv einsetzen wollen.

---

## 4. Konsequenzen für unser Design

1. **Variante A („selbst rechnen") ist wieder offen.** Der Machbarkeitstest hat
   eine falsch parametrierte Implementierung widerlegt, nicht das Verfahren.
2. **Auflösung ist bezahlbar.** Die publizierte ERA-Interim-Konfiguration läuft
   auf **0.75°** — über unserem Europa-Fenster sind das ~3000 Rasterpunkte,
   rund 34 Open-Meteo-Calls. Der 0.25°-Weg (96 Glättungsdurchgänge) wäre mit
   ~300 Calls je Termin dagegen teuer.
3. **Die Alpen-Trennung (lokal vs. synoptisch) muss eingeplant werden**, sonst
   liefert die Karte genau dort Fehlalarme, wo sie gelesen wird.
4. **Validierung gegen den DWD-Text** (`SXDL31`/`SXDL33`, frei unter GeoNutzV)
   ist der richtige Massstab — aber auf der Ebene Vorhandensein/Typ/Richtung,
   nicht Position. Das deckt sich mit den 23–30 % Positionsübereinstimmung
   zwischen Profis.
5. **Die Verbotsliste im Textgenerator kann erst fallen, wenn das
   Strukturfeld die Front trägt** — also nach erfolgreicher Umsetzung, und dann
   mit denselben Belegpflichten wie bei Föhn und Gewitter.

---

## 5. Offene Fragen

- Liefert Open-Meteo `specific_humidity_850hPa` oder muss Θw aus Temperatur +
  relativer Feuchte gerechnet werden? (Für Θe haben wir es bereits getan.)
- Perzentil-Schwellen brauchen eine **Klimatologie** — über welchen Zeitraum
  bilden wir sie, und wie oft wird sie nachgeführt?
- Reicht ein Termin pro Tag (Analysezeit des Casts) oder braucht die
  Verlagerungs-Aussage zwei Termine?

---

## Quellen

- [Sansom & Catto (2024), *Objective identification of meteorological fronts and climatologies from ERA-Interim and ERA5*, Geoscientific Model Development 17, 6137](https://gmd.copernicus.org/articles/17/6137/2024/) — Rezeptur, Schwellen, Code
- [Jenkner et al. (2010), *Detection and climatology of fronts in a high-resolution model reanalysis over the Alps*, Meteorological Applications 17, 1–18](https://rmets.onlinelibrary.wiley.com/doi/abs/10.1002/met.142) — Alpenraum, lokal vs. synoptisch
- [Niebler et al. (2022), *Automated detection and classification of synoptic-scale fronts from atmospheric data grids*, Weather and Climate Dynamics 3, 113](https://wcd.copernicus.org/articles/3/113/2022/) — U-Net, Fehlerbild der TFP-Verfahren, Übereinstimmungsraten
- [Hewson (1998), *Objective fronts*, Meteorological Applications 5, 37–65](https://rmets.onlinelibrary.wiley.com/doi/abs/10.1017/S1350482798000553) — Grundlagenarbeit (TFP, Gl. 13)
- [Lagerquist et al. (2019), *Deep Learning for Spatially Explicit Prediction of Synoptic-Scale Fronts*, Weather and Forecasting 34](https://journals.ametsoc.org/view/journals/wefo/34/4/waf-d-18-0183_1.xml)
- [`front_id` — Referenzimplementierung (R)](https://github.com/phil-sansom/front_id)
- [DWD Open Data — Analysekarten und Textprodukte](https://opendata.dwd.de/weather/)
