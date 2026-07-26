# PLAN — Fronten auf der Synoptik-Karte

**Stand:** 2026-07-26
**Status:** Machbarkeit geprüft — **Entscheidung offen** (Variante A/B/C unten)
**Betrifft:** `engine/synoptic_grid.py` · `static/js/synoptic-map.js` ·
`static/js/synoptic-embed.js` · `skills/synoptic_overview.md` (Verbotsliste)

**Anlass:** Auf der Wetterlage-Karte fehlen die Fronten. Ein Plan dazu existierte
nicht (gesucht in `docs/pläne/`, `docs/`, `meteo_research/`, der Git-Historie
inkl. gelöschter Dateien und den Nachbar-Repos) — dieses Dokument ist er.

---

## 0. Warum das kein Darstellungsthema ist

Zwei Befunde aus dem Bestand, bevor irgendetwas gezeichnet wird:

1. **Es gibt keine Frontdaten.** `fetch_grid_pressure` holt ausschliesslich
   `pressure_msl` und den 700-hPa-Wind. Fronten sind Temperatur- und
   Feuchtegradienten — aus dem Druckfeld allein nicht ableitbar.
2. **Der Textteil verbietet Frontbegriffe.** „Kaltfront", „Warmfront",
   „Okklusion", „Frontdurchgang", „präfrontal", „postfrontal" stehen in
   `_FORBIDDEN_PATTERNS` (`engine/synoptic_llm.py`) und auf der Verbotsliste im
   Skill — genau weil nichts im System sie belegen konnte. Eine Karte mit
   Kaltfront neben einem Text, der sie nicht nennen darf, ist ein Widerspruch,
   der mitentschieden werden muss.

---

## 1. Machbarkeitstest: Fronten selbst ableiten

**Werkzeug:** `scripts/experiment_fronten_tfp.py` (reproduzierbar, Rohdaten
werden gecacht). Verfahren nach Literatur-Standard:

1. 850-hPa-Temperatur + relative Feuchte auf ein regelmässiges Europa-Raster
2. daraus äquivalentpotentielle Temperatur Θe (Bolton 1980)
3. Thermal Front Parameter `TFP = -∇|∇Θe| · (∇Θe/|∇Θe|)` (Hewson 1998) —
   die Frontlinie liegt auf dem Nulldurchgang entlang der Gradientenrichtung
4. Warm/Kalt aus der Advektion `-(u,v)·∇Θe`

**Gegenprobe ohne Fremdkarte:** Eine echte Front führt ein Niederschlagsband mit
sich. Gemessen wird, wie oft die abgeleitete Linie Niederschlag trifft, relativ
zur Grundrate desselben Feldes. Faktor 1.0 = die Linie weiss nichts.

### Ergebnis

| Zeitraum | Auflösung | Faktor Regen auf Linie / Basisrate |
|---|---|---|
| 22.–26.07.2026 (5 Tage, 12 UTC) | 1.0° | 0.68 · 0.47 · 0.97 · 0.87 · 1.11 |
| 01.–05.05.2026 (5 Tage, 12 UTC) | 1.0° | 1.14 · 1.63 · 0.74 · 1.05 · 0.71 |
| 01.–03.05.2026 (3 Tage, 12 UTC) | 0.5° | 1.38 · 0.83 · 0.68 |

**Mittel über 13 Termine, zwei Jahreszeiten, zwei Auflösungen: ≈ 0.95.** Die
Linien treffen Niederschlag so oft wie ein zufällig gewählter Punkt. Die
doppelte Auflösung half nicht: schärfere Gradienten (max |∇Θe| 6.8 → 10.4
K/100 km), mehr Linien (112 → 412 Zellen), aber nicht bessere.

### Sichtvergleich gegen die handanalysierte DWD-Bodenkarte

Referenz: DWD Open Data, `ana_bwkman` (Berliner Wetterkarte), 25.07.2026 12 UTC.

- **DWD:** im Europa-Fenster **ein** Frontensystem — Warmfront/Kaltfront/
  Okklusion um Irland, Britische Inseln und Nordmeer. Mittel- und Südeuropa:
  keine Fronten, Hochdruck.
- **Unsere Ableitung:** trifft die atlantische Frontalzone grob, zeichnet aber
  zusätzlich Linien über Italien, Balkan, Spanien und der Türkei — dort, wo die
  DWD-Analyse nichts hat. Also **Falschmeldungen genau über dem Alpenraum**,
  dem Gebiet unserer Nutzer.

### Bewertung

Das naive TFP-Verfahren ist **nicht produktreif**. Es findet Gradientenachsen,
aber unterscheidet nicht zwischen einer Front und einem harmlosen
Temperaturgefälle. Ein Frontsymbol ist eine starke Aussage — ein falsches über
den Alpen ist schlimmer als gar keines.

Belastbar wäre erst die vollständige operationelle Kette (Linien-Ausdünnung,
Kohärenz- und Längenfilter, Maskierung über die Verlagerungsgeschwindigkeit,
mehrere Niveaus, native Modellauflösung). Das ist ein Forschungsprojekt mit
offenem Ausgang, kein Feature.

---

## 2. Der Fund, der die Lage ändert: DWD Open Data

`https://opendata.dwd.de/weather/charts/analysis/` liefert die **handanalysierte**
Bodenkarte als PNG — mit Fronten, Isobaren, Druckzentren:

- `ana_bwkman_dwdc` = Mitteleuropa, `ana_bwkman_dwdna` = Nordatlantik
- 4× täglich (00/06/12/18 UTC), plus `LATEST`-Datei
- Lizenz: GeoNutzV — freie Nutzung **mit Quellenangabe** („© Deutscher
  Wetterdienst"), bei Veränderung zusätzlich ein Änderungshinweis
- Format: PNG 4379 × 3269, eigenes Layout mit Stationsmeldungen

Damit ist eine korrekte, meteorologisch geprüfte Frontendarstellung ohne
Eigenentwicklung verfügbar — aber als **Bild**, nicht als Daten. Die Fronten
lassen sich daraus nicht als Linien auf unsere Karte legen (Projektion
unbekannt, Symbole und Beschriftung in denselben Farben). Nutzbar ist die Karte
nur als Ganzes oder als Ausschnitt.

---

## 3. Varianten zur Entscheidung

| | Variante | Aufwand | Was der Nutzer sieht |
|---|---|---|---|
| **A** | Eigene Ableitung produktreif machen | hoch, Ausgang offen | Fronten auf unserer Karte — frühestens nach der vollen Hewson-Kette samt neuer Validierung |
| **B** | DWD-Bodenkarte als eigenes Element | gering | Handanalysierte Fronten, klar als DWD-Karte gekennzeichnet, neben unserer Karte statt darin |
| **C** | Keine Fronten | keiner | Stand wie heute |

**Empfehlung: B.** Die Frage lautet „Wo steht die Front?", nicht „Können wir
Fronten selbst rechnen?". Variante B beantwortet sie sofort und richtig; A
riskiert falsche Symbole über dem Alpenraum. Fällt die Entscheidung auf B, ist
zu klären:

- Platzierung: eigener Abschnitt unter der Wetterlage oder verlinkt
- Ausschnitt: `dwdc` (Mitteleuropa) reicht; Zuschnitt = Veränderung → Hinweis
- Ausfall: DWD nicht erreichbar → Element ausblenden, nie leerer Rahmen
- Alter sichtbar machen (Analysezeit steht in der Karte selbst)

**Die Text-Verbotsliste bleibt in allen drei Varianten unverändert.** Auch bei B
bekommt der Textgenerator keine Frontdaten — ein PNG ist keine Datenquelle. Der
Block darf weiterhin nicht von Kaltfronten sprechen.

---

## 4. Reproduzieren

```bash
python scripts/experiment_fronten_tfp.py --start 2026-05-01 --end 2026-05-05 \
       --res 1.0 --hours 14 --gmin 3.0
python scripts/experiment_fronten_tfp.py --cache ...   # ohne neuen Fetch
```

`--hours` ist **Lokalzeit** (`config.TIMEZONE`); für den Vergleich mit
12-UTC-Karten also `--hours 14` im Sommer. Ausgabe (PNG + `summary.json`) landet
in `data/_experiment_fronten/`, gitignored.

Referenzkarte:
```bash
curl -o dwd.png "https://opendata.dwd.de/weather/charts/analysis/\
Z__C_EDZW_LATEST_tka01%2Cana_bwkman_dwdc_O_000000_000000_LATEST_WV12.png"
```
