# PLAN — Fronten auf der Synoptik-Karte

**Stand:** 2026-07-26 (Machbarkeit), **revidiert nach der Recherche**,
**regional nachgemessen am 2026-07-26 (§1c)**,
**Schritte 0–4 umgesetzt am 2026-07-27 (§1f–§1i), nach Challenge-Review neu
geordnet (§1h)**
**Status:** **Variante A (eigene Berechnung) erfüllt die Vorgabe nicht.** Nach
der Anforderung „keine Lücke, über den Alpen muss die Linie sitzen" wurden alle
Verfahren der Literatur implementiert und gemessen (§1d): Über den Alpen liegt
der Trefferfaktor auch an echten Fronttagen bei 0.70–0.88, also unter Zufall.
Ausserhalb der Alpen ist das Verfahren gut und wurde dabei sogar besser
(contour-then-mask, Atlantik 1.47 → 1.53). **Variante B ist umgesetzt und
funktioniert** (§1e): die Fronten lassen sich entgegen der Annahme in §2 als
Linien aus der DWD-Karte extrahieren — farbkodiert, Projektion auf 98.2 %
gefittet, 2.39 km/Pixel, GeoJSON. **Der Vorhersage-Einwand ist ebenfalls
erledigt** (§1f): die Extraktion beherrscht seit 27.07. auch die
ICON-Vorhersagekarten bis +108 h, und deren Fronten sind laut DWD-Doku **von
einem Meteorologen gezeichnet**, nicht gerechnet. Damit liegt eine
handanalysierte Frontenvorhersage vor — entgegen der früheren Annahme hier.

> **Revision:** Der Machbarkeitstest in §1 hat eine **falsch parametrierte**
> Implementierung widerlegt, nicht das Verfahren. Die Recherche
> (`meteo_research/fronten_detektion_research.md`) zeigt fünf Abweichungen vom
> Literatur-Standard — vor allem eine um Grössenordnungen zu schwache Glättung
> und einen fehlenden Mindestlängen-Filter. Variante A ist damit wieder offen
> und gewählt. §1 bleibt als Messprotokoll stehen, §3 ist überholt.
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

### Bewertung (revidiert)

Ursprüngliches Urteil: „nicht produktreif". **Das war ein Urteil über diese
Implementierung, nicht über das Verfahren.** Die Recherche danach ergab fünf
Abweichungen vom Standard — Θe statt Θw, eine um Grössenordnungen zu schwache
Glättung (1 Gauss statt 8 Durchgängen), geratene statt klimatologischer
Schwellen, mask-then-join statt contour-then-mask (versagt bei ≤ 0.75°
nachweislich) und kein 250-km-Längenfilter. Die beobachteten Kurzfragmente
sind genau das erwartete Bild dieser Fehler.

Was bleibt: Ein Frontsymbol ist eine starke Aussage, ein falsches über den
Alpen schlimmer als keines. Deshalb ist die Trennung lokaler von synoptischen
Fronten (Jenkner et al. 2010) Pflichtbestandteil, kein Extra.

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

## 1b. Zweiter Testlauf — Literatur-Verfahren (26.07.2026)

Dasselbe Skript, `--method hewson`: Θw statt Θe, 8 Glättungsdurchgänge,
Perzentil-Schwellen, Linie auf dem TFP-Maximum am warmen Rand statt auf der
Gradientenachse, versetzte Gradientenprüfung (ABZ), 250-km-Längenfilter,
Klassifikation über die Frontgeschwindigkeit (±1.5 m/s, mit quasistationärer
Klasse). Raster 0.75° — die publizierte ERA-Interim-Konfiguration, 34 Abrufe.

| Termin | naiv | **Hewson** |
|---|---|---|
| 24.07. | 0.97 | **1.21** |
| 25.07. | 0.87 | **1.30** |
| 26.07. | 1.11 | **1.63** |
| 01.05. | 1.14 | **1.69** |
| 02.05. | 1.63 | **1.19** |
| 03.05. | 0.74 | **1.13** |
| 04.05. | 1.05 | **1.34** |
| 05.05. | 0.71 | **1.41** |
| **Mittel** | **0.95** | **1.36** |

**Alle acht Termine liegen über 1** (naiv: 6 von 10 darunter). Die Linien
tragen jetzt Information.

**Sichtvergleich 25.07. 12 UTC gegen die DWD-Handanalyse:** eine durchgehende
Kaltfront vom Nordmeer über die Nordsee und Frankreich zur Biskaya, davor eine
Warmfront westlich Irlands — strukturell dieselbe Lage, die der DWD zeichnet.
Statt der Fragmente der ersten Fassung.

**Was noch fehlt:** Über Italien, Balkan und Türkei stehen weiterhin Linien,
wo die DWD-Analyse nichts hat. Das ist genau die Trennung *lokal* gegen
*synoptisch* aus Jenkner et al. (2010), die noch nicht implementiert ist.

## 1c. Dritter Testlauf — regional getrennt gemessen (26.07.2026)

Der Faktor 1.36 aus §1b ist ein Mittel über **ganz Europa**. Die Frage, die uns
interessiert, ist eine andere: taugt die Linie **dort, wo geflogen wird**?
`precip_check` bekam dafür ein `area`-Argument, das Treffer *und* Basisrate auf
ein Teilfenster einschränkt; gepoolt wird über die Rohzählungen aller 8 Termine,
nicht als Mittel der Tagesfaktoren — dafür sind die Fenster zu dünn besetzt.
Werkzeug: `scripts/experiment_fronten_sweep.py`.

| Konfiguration | Gesamt | Alpenraum | Südost | Atlantik |
|---|---|---|---|---|
| 850 hPa roh (Stand §1b) | 1714 Z. · **1.36x** | 41 Z. · **0.12x** | 162 Z. · 1.11x | 686 Z. · **1.47x** |
| 850 + Geländefilter 1500 m | 1615 · 1.39x | 19 · 0.00x | 145 · 1.18x | 685 · 1.48x |
| **850 + Geländefilter 1000 m** | 1379 · **1.42x** | **2** · — | 87 · 0.79x | **679 · 1.46x** |
| 850 + Geländefilter 800 m | 1325 · 1.43x | 0 · — | 68 · 0.81x | 673 · 1.47x |
| 700 hPa roh | 1763 · 1.20x | 47 · 0.64x | 206 · 1.21x | 566 · **1.18x** |
| 700 hPa + 1000 m | 1433 · 1.21x | 13 · 0.38x | 132 · 0.63x | 556 · 1.20x |

### Befund 1: Der gute Gesamtwert kam vom Atlantik

Über dem **Alpenraum lag der Faktor bei 0.12** — von 41 Frontzellen traf genau
**eine** Niederschlag, erwartbar wären bei 20.1 % Basisrate rund 8 gewesen.
Das ist nicht Rauschen: binomial **p = 0.0012**. Die Linien dort waren nicht
uninformativ, sie waren *gegenläufig* — schlechter als ein zufällig gesetzter
Punkt. Genau das Bild, das der Sichtvergleich gegen die DWD-Karte zeigte.

### Befund 2: Ursache ist das Niveau unter dem Gelände

850 hPa liegt bei ≈ 1457 m Standardhöhe, also **im Alpengelände**. Was das
Modell dort liefert, ist keine Luftmasse, sondern eine Extrapolation unter den
Boden; ihre Gradienten folgen der Topographie statt der Wetterlage. Das ist die
in §3.6 der Recherche dokumentierte Quelle der Gebirgs-Fehlfronten.

`terrain_filter()` setzt daher die Trennung lokal/synoptisch um: Frontzellen
über zu hohem Gelände verwerfen (eine Zelle Puffer, der Gradienten-Stencil
liest die Nachbarn mit), **danach den 250-km-Längenfilter erneut anwenden** —
eine synoptische Front zieht über das Gebirge hinweg und bleibt beidseits lang
genug, eine lokale zerfällt in Stummel und fällt heraus.

**Kontrollgruppe Atlantik**: 686 → 679 Zellen, Faktor 1.47 → 1.46. Der Filter
trifft Artefakte, nicht Fronten. Das ist der Beleg, dass hier nicht einfach
weggeschnitten wurde, bis die Zahl stimmte.

### Befund 3: 700 hPa ist nicht die Lösung

Naheliegende Alternative — dasselbe Verfahren über dem Gelände rechnen. Getestet
mit eigenem Abruf (68 Calls). Der Alpenraum bessert sich auf 0.64x, bleibt aber
**unter 1**, und der Atlantik bricht von 1.47 auf 1.18 ein. Das bestätigt die
Literatur: 850 hPa ist das Frontniveau, 700 hPa verliert das Signal. Verworfen.

### Bewertung — was das ehrlich heisst

Der Filter **unterdrückt** die Alpen-Fehlmeldungen, er **repariert** sie nicht.
Auch bei 1500 m sind die verbleibenden 19 Zellen noch sämtlich trocken. Erst
wenn ein grosser Teil des Fensters gesperrt wird, verschwinden sie:

| Schwelle | zeichenbarer Anteil Alpenfenster |
|---|---|
| 1500 m | 45 % |
| **1000 m** | **32 %** |
| 800 m | 14 % |

Stand heute gilt also: **Über den Alpen können wir Fronten nicht detektieren.
Wir können nur verhindern, dass wir dort Falsches zeichnen.** Eine synoptische
Front bliebe über Mittelland, Po-Ebene und Vorland sichtbar und bekäme über dem
Alpenhauptkamm eine Lücke.

**Empfohlene Konfiguration: 850 hPa + Geländefilter 1000 m.** Bester Gesamtwert
bei intakter Kontrollgruppe und praktisch stummgeschaltetem Alpenraum, ohne das
Fenster so weit zu sperren wie bei 800 m.

**Offen bleibt Südost** (Süditalien, Balkan, Türkei): 0.79x, also weiter unter 1.
Ausserhalb des Nutzergebiets, aber auf der Europakarte sichtbar. Zu beachten:
dort ist die Regen-Gegenprobe selbst verfälscht — Staulagen an den Gebirgen
erzeugen Niederschlag, eine topographiefolgende Fehllinie trifft ihn also
zufällig. Deshalb steigt der Südost-Wert *ohne* Filter (1.11x) und sinkt *mit*
ihm. Für dieses Fenster braucht es ein anderes Mass als Regen.

### Reproduzieren

```bash
python scripts/experiment_fronten_tfp.py --start 2026-05-01 --end 2026-05-05 \
       --res 0.75 --hours 14 --method hewson --cache --maxelev 1000
python scripts/experiment_fronten_sweep.py     # alle Konfigurationen gepoolt
```

## 1d. Vierter Testlauf — die Alpenfrage direkt gestellt (26.07.2026)

Vorgabe: *keine Lücke über den Alpen, dort muss die Linie sitzen.* Also
recherchiert, was die Literatur dafür anbietet, alles implementiert und
gemessen. Werkzeuge: `experiment_fronten_sweep.py`,
`experiment_fronten_alpentage.py`.

### Der Messfehler in §1c, der zuerst korrigiert werden musste

Die 8 Termine aus §1b/§1c waren **Hochdrucktage** — die Θw-Spanne über dem
Alpenfenster lag bei 2–3 K auf 1000 km. Über den Alpen lag in diesem Sample
**nie eine Front**. Der Faktor 0.12 dort war damit eine *Fehlalarmrate*, keine
Trefferquote; die Frage „sitzt eine echte Front richtig?" war nie gestellt.

Behoben mit einem längeren Zeitraum: **87 Tage (01.05.–26.07.2026), 14 Uhr
lokal, ein einziger Abruf über 34 Calls** — die Kosten hängen an der Rasterzahl,
nicht an der Tagesanzahl. Das war die ganze Zeit billig zu haben.

Front-Tage werden **unabhängig vom Detektor** bestimmt (sonst benotet er sich
selbst): kräftiger Θw-Gradient im Alpenfenster **und** Luftmassenwechsel
≥ 1.5 K in 24 h. Ergebnis: 4 strenge, 11 mittlere, 28 weite Front-Tage.

### Ergebnis auf echten Alpen-Fronttagen

| Abgrenzung | Tage | Zellen | Regen auf Linie | Basisrate | Faktor | p |
|---|---|---|---|---|---|---|
| streng | 4 | 34 | 32 % | 46 % | **0.70x** | 0.074 |
| mittel | 11 | 84 | 35 % | 45 % | **0.76x** | 0.028 |
| weit | 19 | 130 | 38 % | 46 % | **0.84x** | 0.060 |
| sehr weit | 28 | 199 | 39 % | 44 % | **0.88x** | 0.074 |

**Auch wenn eine Front über den Alpen liegt, sitzt unsere Linie im trockeneren
Teil des Fensters.** Vier unabhängige Abgrenzungen, alle unter 1 — kein
Schwellenartefakt.

### Was alles versucht und gemessen wurde

| Ansatz | Quelle | Alpen | Atlantik (Kontrolle) |
|---|---|---|---|
| Stand 26.07. (mask-then-join) | Hewson 1998 | 0.12x | 1.47x |
| Geländefilter 1000 m | §3.6 | 0 Zellen (stumm) | 1.46x |
| 700 hPa statt 850 | naheliegend | 0.64x | **1.18x** — bricht ein |
| **contour-then-mask** | Sansom & Catto §3.4 | 0.13x | **1.52x** |
| Jenkner-Ringkriterium | Jenkner 2010 | **0.13x — wirkungslos** | 1.53x |
| Positions-Brücke über den Kamm | Handanalyse-Praxis | 0.12–0.23x | 1.53x |
| Bodenfelder 2 m statt 850 hPa | DWD-Referenz *ist* Bodenkarte | 0.73–1.10x | — |

Zwei Befunde sind dabei wertvoll, auch wenn sie die Alpenfrage nicht lösen:

1. **contour-then-mask ist ein echter Gewinn** und war trotz §3.4 bis heute
   nicht umgesetzt (wir hatten weiter mask-then-join). Atlantik 1.47 → 1.53
   bei **20 % weniger Zellen** — schärfere Linien, nicht mehr Linien. Ebenso
   die Länge jetzt als Summe der Segmente statt Endpunkt-Abstand (die
   Korrektur, die Sansom & Catto 2024 selbst vorgenommen haben).
2. **Jenkners Ringkriterium greift bei uns nicht.** Die Alpenpunkte sind keine
   kleinen geschlossenen Ringe um Berge, sondern Teile **langer Linien**. Es
   ist also eine echte Front da — sie wird über dem Gebirge nur falsch
   platziert. Genau deshalb half auch die Positions-Brücke nicht: man kann eine
   Linie nicht auf eine Front schieben, deren Lage das Feld nicht kennt.

### Urteil

**Mit Open-Meteo-Rasterdaten auf 0.75° lässt sich nicht belegen, dass eine
Front über den Alpen richtig sitzt.** Alle Wege, die die Literatur anbietet,
sind implementiert und gemessen; keiner bringt den Alpenwert über 1. Der
physikalische Grund bleibt unverändert: 850 hPa liegt im Gelände, und keine
Auflösung ändert daran etwas — Jenkner (2010) hatte über den Alpen Erfolg mit
COSMO auf **geländefolgenden Modellflächen**, die Open-Meteo nicht ausliefert.

Damit ist die Vorgabe „keine Lücke, es muss sitzen" mit **eigener Berechnung
nicht erfüllbar**. Übrig bleibt Variante B aus §3: die handanalysierte
DWD-Bodenkarte als eigenes Element. Dort sind die Fronten über den Alpen
richtig, weil ein Mensch sie gezeichnet hat — und die Karte ist unter GeoNutzV
mit Quellenangabe frei nutzbar.

### Reproduzieren

```bash
python scripts/experiment_fronten_sweep.py       # alle Verfahren, gepoolt
python scripts/experiment_fronten_alpentage.py   # Treffer vs. Fehlalarm Alpen
```

## 1e. Variante B umgesetzt: Fronten aus der DWD-Karte extrahiert (26.07.2026)

§2 hielt fest, die Fronten liessen sich aus dem PNG „nicht als Linien
herauslösen (Projektion unbekannt, Symbole und Beschriftung in denselben
Farben)". **Beides war eine Annahme, und beide sind falsch.** Gemessen:

**Die Karte ist farbkodiert.** Drei reine Farben, sonst ist nichts im Bild
farbig — grün-dominante Pixel: exakt null. Isobaren, Stationsmeldungen,
Küsten und Beschriftung sind durchweg Grau.

| | RGB | Pixel (26.07. 12 UTC) |
|---|---|---|
| Kaltfront | (0, 0, 255) | 47 349 |
| Warmfront | (255, 0, 0) | 45 702 |
| Okklusion | (238, 130, 238) | 38 052 |

**Die Projektion ist bestimmbar.** Der Nordpol liegt im Bild (Meridianfächer),
es ist eine Polarstereographie. Gefittet gegen eine Referenz-Landmaske aus der
Höhen-API — dieselbe Infrastruktur, die das Frontexperiment schon nutzt:

```
rho = 4625.0 · tan(45° − lat/2)        Pol bei Pixel (2960.8, 339.7)
alpha = 100° − lon                     → Zentralmeridian 10° Ost, senkrecht nach unten
```

**98.2 % Übereinstimmung** der Land-See-Maske. Der Wert 100.000° ist exakt
getroffen, was für einen echten Treffer spricht. Auflösung **2.39 km/Pixel** —
25× feiner als unser eigenes 0.75°-Raster. Kontrollpunkte (Zürich, Rom,
Gibraltar, Reykjavík, Nordkap) landen an den richtigen Stellen.

**Die Kalibrierung ist einmalig**, das Layout ist fix. Sie wird bei jedem Lauf
gegen die Landmaske geprüft (`check_projection`); fällt der Wert unter 93 %,
bricht das Skript ab, statt falsche Linien zu liefern.

### Kette und die zwei Fallen darin

`scripts/experiment_dwd_fronten_extraktion.py`: Farbmasken → Skelett
(Zhang-Suen) → Längsachse → lat/lon → GeoJSON. Zwei Dinge kosteten Anläufe:

1. **Astbeschnitt zerschnitt die Linien.** Die Frontsymbole hängen als kurze
   Seitenäste am Skelett; mein erster Beschnitt löschte den Kreuzungspunkt
   mit, wodurch jedes Dreieck die Front in zwei Teile zerlegte.
2. **Zhang-Suen hinterlässt Treppenartefakte** — gemessen 2563 Knoten vom Grad
   3 und 1352 vom Grad 4. Ein einfacher Graphlauf bricht daran ständig ab.
   Gelöst über die **Längsachse je Komponente** (doppelte Breitensuche): sie
   läuft durch die Artefakte hindurch, und die Symbole fallen als kürzere
   Seitenwege von selbst heraus. Danach wird die Achse entfernt und der Rest
   erneut geprüft, damit am Okklusionspunkt auch der dritte Arm überlebt.

**Typ pro Abschnitt, nicht pro Linie.** Eine gezeichnete Linie wechselt
unterwegs zwischen kalt und warm (Stationärfronten, und die Kette
Warmfront–Okklusion–Kaltfront). Ein Mehrheitstyp je Linie hätte genau die
Information weggemittelt, auf die es ankommt.

### Ergebnis

26.07. 12 UTC: **23 Frontabschnitte**, längste 2486 km. Rückprojektion auf die
Karte zeigt die extrahierten Linien exakt auf den gezeichneten Fronten, mit
richtiger Typzuordnung (`data/_experiment_fronten/check_overlay.png`).
Gegenprobe auf der Karte vom 25.07.: läuft durch, Wächter ebenfalls 98.2 %.

### Der Vorhersage-Einwand ist erledigt: `ico_tkb_na`

Der erste Durchgang durch `forecasts/icon/` fand nur ICON-Produktkarten und
schloss daraus, es gebe keine Frontenvorhersage. Das war zu früh aufgegeben —
die Produktkürzel wurden nicht einzeln geprüft. Von den fünf Produkten in
`forecasts/icon/global/na/` trägt **`tkb` die drei Frontfarben**:

> „Vorhersage Bodendruck (hPa) · für: So. 26.07.26 12 UTC ·
> Basis: ICON 25.07.26 00+036 h · © Deutscher Wetterdienst"

| | |
|---|---|
| Vorlaufzeiten | **+36, +48, +60, +84, +108 h** (bis 4.5 Tage) |
| Basis | 00-UTC-Lauf, je Vorlauf eine Karte |
| Verfügbar | +036 ab ~03:30 UTC, +048/+060 ~05:20, +084/+108 ~06:15 |
| Grösse | 1280 × 910, **5.7 km/Pixel** bei 47 °N |
| Inhalt | Fronten, Isobaren, Druckzentren, **orange Trog-/Konvergenzlinien** |

Eigene Kalibrierung, dieselbe Projektionsfamilie (Zentralmeridian 10° Ost):

```
rho = 1934.0 · tan(45° − lat/2)        Pol bei Pixel (814.1, −181.2), ausserhalb des Bildes
alpha = 100.12° − lon
```

**98.66 % Übereinstimmung** der Land-See-Maske; Land = (222,222,222),
See = Weiss — noch sauberer trennbar als bei der Analysekarte.

**Zeitplan für ein 06:00-Briefing** (= 04:00 UTC im Sommer): der kürzeste
Vorlauf ist +36 h, es gibt kein +12/+24. Für *heute* Mittag nimmt man deshalb
die **+036-Karte des gestrigen 00-UTC-Laufs** (liegt noch auf dem Server), für
*morgen* die +036 des heutigen Laufs. Beides um 06:00 verfügbar. Die
hochauflösende Analysekarte (§1e, 2.39 km/px) liefert zusätzlich die Ist-Lage.

### Was offen bleibt
- **Fremdes Layout.** Ändert der DWD die Karte, bricht die Extraktion. Der
  Wächter fängt das ab, aber dann fehlen die Fronten, bis nachkalibriert ist.
- **Lizenz.** GeoNutzV: Quellenangabe „© Deutscher Wetterdienst" Pflicht, und
  weil eine Vektorisierung eine Veränderung ist, zusätzlich ein
  Änderungshinweis. Beides steckt bereits in den GeoJSON-Properties.

### Reproduzieren

```bash
# Analysekarte (Ist-Lage), holt LATEST
python scripts/experiment_dwd_fronten_extraktion.py
python scripts/experiment_dwd_fronten_extraktion.py --png <datei.png>

# Vorhersagekarten (ab 27.07., §1f)
python scripts/experiment_dwd_fronten_extraktion.py --profil vorhersage --step 36
python scripts/experiment_dwd_fronten_extraktion.py --profil vorhersage \
       --lauf 2026072600 --alle-steps --overlay
```

## 1f. Schritt 0 und 1 umgesetzt (27.07.2026)

### Schritt 0 beantwortet: die Vorhersage-Fronten sind von Hand gezeichnet

Die offene Frage aus §6 („Ist `tkb` handgezeichnet oder automatisch? Wenn
automatisch, könnte es das Alpenproblem aus §1d teilen") ist erledigt — und
zwar aus der Quelle selbst, nicht durch eine eigene Messung:

> „Die Fronten werden vom Meteorologen hauptsächlich anhand überlagerter
> Temperatur- und Feuchtefelder aus verschiedenen Höhen (zum Beispiel aus
> 1,5 und 3 Kilometern Höhe) eingetragen."
> — DWD, *Allgemeines zum Thema Analyse- und Kurzfrist-Prognosekarten*

Die Isobaren und Druckzentren kommen maschinell aus dem Modell und werden vom
Meteorologen überarbeitet; die **Fronten** trägt er ein. Dass es genau unser
Produkt betrifft, belegt die Produktseite: Gebiet „Nordatlantik-Europa", Modell
ICON, Vorlaufzeiten **+36 (12 Uhr Vortag), +36 (00 UTC), +48, +60, +84, +108**,
Inhalt „Bodenwetter mit Fronten, Luftdruckzentren, Wettersymbolen". Das ist
deckungsgleich mit `ico_tkb_na`.

**Unabhängige Bestätigung unseres eigenen Befunds aus §1d.** Zu den rein
maschinell erzeugten Karten schreibt der DWD:

> „Weil die Frontenanalyse per Rechner zu ungenau ist, fehlen Fronten auf
> maschinell erstellten Karten."

Der DWD verzichtet also aus demselben Grund auf automatische Fronten, aus dem
wir Variante A verworfen haben. Damit ist die Alpen-Sorge für `tkb`
gegenstandslos: es steckt eine menschliche Analyse dahinter.

Nebenbefund zur Farblegende: **rot = Warmfront, blau = Kaltfront, pink =
Okklusion, gelb = Konvergenz.** Unsere vierte Farbklasse (orange) ist damit
als Konvergenz-/Trogachse bestätigt.

Quellen: `dwd.de/DE/fachnutzer/hobbymet/wetter_europa/allgemeines_analyse_prognosekarten_europa_neu.html`,
`…/wetter_welt/allgemeines_welt-prognosesekarten.html`,
`dwd.de/DE/leistungen/hobbymet_wk_europa/hobbyeuropakarten.html`

### Schritt 1 umgesetzt: Extraktion beherrscht beide Karten

`scripts/experiment_dwd_fronten_extraktion.py` hat jetzt zwei Kartenprofile
(`--profil analyse|vorhersage`):

| | Analyse | Vorhersage `tkb` |
|---|---|---|
| Grösse | 4379 × 3269 | 1280 × 910 |
| Massstab | 2.39 km/px | 5.71 km/px |
| Wächter gemessen | 98.2 % | 98.2–98.5 % |
| Klassen | kalt, warm, okklusion | + **trog** (orange) |

Vier Dinge, die dabei nötig waren:

1. **Schwellen von Pixeln auf Kilometer umgestellt.** Die Karten
   unterscheiden sich im Massstab um Faktor 2.4; die in Pixeln kalibrierten
   Schwellen (70/120/60 px) hätten auf der gröberen Karte kaum noch gefiltert.
   Sie stehen jetzt als 167/287/143 km im Code und werden pro Profil aus der
   Projektion in Pixel zurückgerechnet — der Massstab wird **abgeleitet**
   (`km_per_px()`), nicht eingetippt. Gegenprobe: 2.388 und 5.71 km/px, exakt
   die im §1e-Anhang gemessenen Werte.
2. **Eigene Land-See-Erkennung je Karte.** Die Vorhersagekarte hat Land exakt
   (222,222,222) und See reines Weiss — sauberer als die Analysekarte.
3. **Störflächen ausblenden.** Der Legendentext der Vorhersagekarte ist
   orange; ohne Sperre für Legendenkasten, Beschriftungsstreifen und Logo
   wäre er als Trogachse extrahiert worden.
4. **LATEST wird nie gecacht**, datierte Karten immer — sonst arbeitet man
   unbemerkt auf einer alten Karte.

**Verifikation.** Regressionslauf auf der Analysekarte vom 26.07.:
23 Abschnitte, Geometrien **bitgleich** mit dem Ergebnis von gestern — der
Umbau hat den bestehenden Pfad nicht verändert. Auf den Vorhersagekarten
13–19 Abschnitte je Karte; das Kontrollbild (`--overlay`, extrahierte Punkte
in Grün, weil auf beiden Karten null grün-dominante Pixel liegen) zeigt die
Linien exakt auf den gezeichneten Fronten, Trogachse inklusive.

Neu: `--lauf YYYYMMDDHH`, `--step`, `--alle-steps`, `--overlay`. Datierte
Karten werden über das Verzeichnislisting aufgelöst, weil der Dateiname einen
nicht vorhersagbaren Erzeugungszeitstempel trägt.

### Zwei Randbefunde

- **Kein `tkb` für Mitteleuropa.** Geprüft: `global/ce`, `global/eu` und
  `eu_nest/{alpen,ce,cex}` führen kein Frontenprodukt. Die Nordatlantik-Karte
  mit 5.71 km/px ist die einzige Quelle — für eine Aussage „Front quert Zone
  gegen 14 Uhr" reicht das, für Meter-Genauigkeit nicht. Braucht es auch nicht
  (§2b).
- **Vorhaltezeit rund zwei Tage.** Auf Open Data lagen am 27.07. nur die Läufe
  vom 26. und 27.07., jeweils 00 UTC. **Für den Betrieb belanglos** — wir
  holen die Karte des Tages am selben Tag. Es betrifft nur zwei Randfälle:
  ein ausgefallener Lauf lässt sich nach zwei Tagen nicht mehr nachholen, und
  ein späterer Gütevergleich (Vorhersage gegen eingetretene Lage) braucht ein
  eigenes Archiv, das ab Inbetriebnahme mitläuft. Kein Grund, deswegen jetzt
  etwas zu bauen.

### Was diese elf Karten belegen — und was nicht

**Belegt:** Auf der Gesamtkarte ist immer etwas gezeichnet — 13 bis 19
Abschnitte je Karte, nie null. Darauf kann die Alarmregel „Zeichnung weg"
aufsetzen (§6), ohne dass es dafür eine Klimatologie braucht.

**Nicht belegt:** In unserem Gebiet (43–50 °N, 2–18 °E) lag genau **ein**
Frontabschnitt, über den Alpen keiner. Daraus folgt keine Grundrate — der
Zeitraum 27.–31.07.2026 ist eine stabile Hochdrucklage, die Karten zeigen
durchgehend „H" über Mitteleuropa. Die Frage „wie oft sieht der Nutzer
überhaupt eine Front?" bleibt damit offen. Sie ist eine **Produktfrage**
(lohnt die Ebene?), keine Voraussetzung für den Bau: an frontfreien Tagen
bleibt die Ebene leer, und das ist kein Fehlerfall.

## 1g. Schritt 2 umgesetzt: Durchgangszeit je Zone (27.07.2026)

`scripts/experiment_fronten_zeitachse.py` — aus mehreren Vorlaufzeiten wird
die Frage beantwortet, die den Piloten interessiert: **wann** quert die Front
seine Zone.

**Verfahren.** Für jeden Spot und jede Karte wird der nächste Punkt auf einer
Frontlinie gesucht. Aus zwei aufeinanderfolgenden Karten ergibt sich die
Zugrichtung (Bewegung dieses Punktes). Die Lage des Spots wird darauf zerlegt
in **längs** (positiv = Front steht bevor, negativ = durch) und **quer**.
Kippt das Vorzeichen der Längskomponente, lag der Durchgang dazwischen; der
Zeitpunkt wird linear interpoliert.

**Pro Spot, nicht pro Zone.** Der Alpennordhang ist rund 270 km breit; eine
Front mit 40 km/h braucht dafür etwa sieben Stunden. Ein einzelner Zeitpunkt
für die ganze Zone wäre Scheingenauigkeit. Ausgegeben wird ein Fenster:
Median über die Spots plus 10-/90-Perzentil — das ist zugleich die Zeit, die
die Front zum Queren der Zone braucht.

### Der Fehler, den das Verfahren zuerst hatte

Die erste Fassung meldete für den Lauf vom 27.07. **Kaltfront-Durchgänge in
allen vier Zonen** — sauber aussehende Zeiten, Mittwoch früh bis Mittag,
Zonenfenster und alles. Gegenprobe an den Rohdaten: die nächste Kaltfront war
zu **jedem** der fünf Termine zwischen **501 und 1707 km** entfernt. Es gab
keinen Durchgang.

Ursache: Der nächste Punkt einer weit entfernten, langen Frontlinie rutscht
an ihr entlang, während sie zieht. Dadurch kippt das Vorzeichen der
Längsprojektion, ohne dass die Front je in die Nähe kommt. Die Längsrichtung
allein ist also kein Durchgangsnachweis.

Behoben über den **Querabstand im Moment des Durchgangs**: bei reiner
Verlagerung bleibt er konstant, während die Längskomponente durch null geht —
er ist damit genau der Abstand, den die Front beim Passieren seitlich noch
hat. Schwelle 100 km (Grössenordnung einer Zone, unter der Streuung zweier
menschlicher Frontanalysen aus §2b). Danach: null Durchgänge, im Einklang mit
der direkten Abstandsmessung.

**Lehre, die über diesen Fall hinausgeht:** Ein Verfahren, das nur „nichts
gefunden" liefern kann, ist nicht geprüft — und eines, das plausible Zahlen
liefert, ist es auch nicht. Erst die Gegenprobe an einer unabhängigen Grösse
(hier: der schlichte Abstand) trennt das eine vom anderen.

### Selbsttest statt Warten auf eine Front

`--selftest` prüft die Zeitrechnung an synthetischen Fronten, weil echte
Frontlagen nicht auf Bestellung kommen:

| | Fall | Erwartung |
|---|---|---|
| 1 | Nord-Süd-Front zieht 5 °O → 11 °O in 12 h | Durchgang bei 7.95 °O nach 5.9 h — **auf die Minute getroffen** |
| 2 | Dieselbe Front 10 Breitengrade nördlich | kein Durchgang |
| 3 | Lange schräge Front weit westlich, zieht ostwärts | kein Durchgang (**Regression auf den obigen Fehler**) |
| 4 | Zwei Durchgänge 40 h auseinander | zwei Ereignisse, nicht ein gemittelter |

### Was noch offen ist

- **Kein echter Frontfall geprüft.** Der Zeitraum 27.–31.07. ist eine stabile
  Hochdrucklage; beide verfügbaren Läufe liefern null Durchgänge. Die
  Zeitrechnung ist damit synthetisch verifiziert, aber nicht an einer realen
  Lage. Das ist der erste Punkt für den nächsten Frontdurchgang — und der
  Grund, das Archivieren früh anzuwerfen (Vorhaltezeit ~2 Tage).
- **Stützweite 12 h, ab +60 h sogar 24 h.** Die lineare Interpolation
  unterstellt gleichförmige Verlagerung. Bei 12 h vertretbar, bei 24 h
  schwach. Die Ausgabe weist die halbe Stützweite als Unschärfe mit aus, damit
  aus „Mittwoch 10:17" niemand eine Punktprognose macht.
- **Zwei Fronttypen an derselben Zone** werden getrennt gemeldet. Ob die
  Ausgabe die Kette Warmfront → Okklusion → Kaltfront als *ein* Ereignis
  zusammenfassen soll, ist eine Darstellungsfrage für Schritt 4/5.

### Reproduzieren

```bash
python scripts/experiment_fronten_zeitachse.py --selftest
python scripts/experiment_fronten_zeitachse.py --lauf 2026072700
python scripts/experiment_fronten_zeitachse.py --lauf 2026072700 --typ kalt \
       --max-seitlich-km 150
```

Setzt die extrahierten GeoJSON des Laufs voraus (§1f, `--alle-steps`).

## 1h. Challenge-Review (27.07.2026, zweite Meinung) — Befunde und Neuordnung

§1f/§1g wurden adversarial gegengelesen. Fünf Befunde, die die Reihenfolge in
§6 ändern:

1. **Morgen-Lücke (Konstruktionsfehler).** Der 00-UTC-Lauf beginnt bei +36 h —
   die früheste Vorhersagekarte gilt für **heute 12 UTC**. Innerhalb eines
   Laufs existiert kein Stützpunkt vor heute Mittag; ein Durchgang am
   Briefing-Vormittag ist für die Zeitrechnung unsichtbar. Lösung: die
   **00-UTC-Handanalyse als frühen Stützpunkt** einhängen (Extraktion läuft
   bereits). Gemessen 27.07.: die *datierten* Analysekarten auf Open Data sind
   Schwarz-Weiss (null Frontfarben) — nutzbar ist nur die farbige
   LATEST-Karte; ihre Gültigkeitszeit steht im Verzeichnislisting. Wer alle
   12-h-Analysen will, muss also **regelmässig** holen.
2. **Schritt 2 ist gebaut, nicht bewährt.** Null echte Treffer bisher; die
   Front-Identität zwischen zwei Karten (13–19 Abschnitte gleichzeitig!) ist
   nur durch Geschwindigkeits- und Querabstands-Gate plausibilisiert.
   Ungetestete Fälle: zwei Fronten gleichen Typs (eine löst sich auf), Front
   wechselt den Typ entlang der Linie, Endpunkt-Effekte.
3. **Schritt 0 ist Doku, nicht Messung.** Quelle sind Hobby-Seiten des DWD
   (möglicherweise veraltet), zusammengefasst von einem Kleinmodell. Die
   billige Messung — tkb +36 gegen die Handanalyse derselben Gültigkeitszeit —
   steht aus und läuft ab jetzt über das Archiv von selbst auf.
4. **Prioritäts-Inversion Archiv.** Vorhaltezeit ~2 Tage; jeder Tag ohne
   Archiv verliert den nächsten Frontfall als Testdatensatz. Gehört VOR alles
   Weitere.
5. **Alarm-Blindstelle Legende.** Verschiebt der DWD den Legendenkasten,
   bleibt die Landmaske perfekt, aber der orange Legendentext wird als
   Trogachse extrahiert. Billige Invariante: die erwarteten Legendenfarben
   müssen INNERHALB der Sperrzone liegen, sonst Alarm.

**Validierungskonzept (ersetzt die Stufen-Tabelle in §6 Regel 3):** Der
Schiedsrichter ist im Haus — die Handanalyse selbst. Sie erscheint alle 12 h,
ist von Meteorologen nach Messungen gezeichnet, und wir extrahieren sie schon.

| Prüfung | beantwortet | Kosten |
|---|---|---|
| Vorhersage gegen **spätere Handanalyse** | war die Front da, wo wir sie ansagten? Zeitfehler? Systematik? | ~0, alles vorhanden |
| **Lauf gegen Vorlauf** (heutige vs. gestrige Ansage für denselben Tag) | Stabilität; springt die Aussage, ist sie unreif zum Anzeigen | 0 |
| **Textbulletin SXDL31** (liegt auf Open Data: `weather/text_forecasts/txt/`) | sagt der DWD-Meteorologe dasselbe im Klartext? | klein |
| Stationsmessungen MeteoSchweiz | exakte Durchgangsstunde | mittel; **letzte** Stufe, evtl. nie nötig |

Der Charme: einmal aufgesetzt, wird jede Front der nächsten Wochen automatisch
zum Testfall — der Qualitätsnachweis liegt vor, bevor die Ebene live geht.

## 1i. Schritte 3 und 4 umgesetzt — und der erste echte Frontfall (27.07.2026)

### Archiv (§6 Schritt 3)

`scripts/archive_dwd_fronten.py` — idempotent, sammelt pro Lauf ein:
farbige LATEST-Handanalyse (PNG + GeoJSON, Gültigkeitszeit aus dem
Verzeichnislisting nachgetragen), alle datierten `tkb`-Karten samt GeoJSON,
sowie die `SXDL31`-Klartextbulletins. Ablage `data/dwd_fronten_archiv/`
(gitignored). Die Extraktion läuft als Subprozess über das bestehende Skript —
kein zweiter Codepfad.

Erster Lauf: 11 GeoJSON, 11 PNG, 5 Bulletins. Zweiter Lauf: „Nichts Neues".

**Wichtige Messung dabei:** die *datierten* Analysekarten auf Open Data sind
**Schwarz-Weiss** (null Frontfarben-Pixel, geprüft an `dwdc_202607270000`).
Nutzbar ist allein die farbige LATEST-Karte. Das Archiv muss deshalb
regelmässig laufen, sonst fehlen Analysetermine unwiederbringlich.

**Nachtrag — auch unsere eigenen Aussagen werden archiviert.** Die
extrahierten Linien allein genügen für den späteren Abgleich nicht:
verglichen wird nicht Linie gegen Linie, sondern **was wir gesagt haben**
gegen **was eingetreten ist**. `experiment_fronten_zeitachse.py --json`
schreibt die abgeleiteten Aussagen strukturiert weg (Zone, Typ,
quert/streift, Median und Fenster in UTC, betroffene Spots, seitlicher
Abstand, Stützweite, Randwert-Flag) samt der verwendeten Stützpunkte und
Parameter. Das Archiv ruft es je Lauf **einmal pro Kalendertag** auf und
überschreibt Bestehendes nie — dadurch entsteht nebenbei die Zeitreihe für
den **Lauf-Jitter**: dieselbe Zielzeit, aus immer kürzerer Vorlaufzeit
beurteilt. Ablage `aussagen/passagen_<lauf>_stand_<tag>.json`.

### Morgen-Lücke geschlossen (§6 Schritt 4)

`load_run()` zieht jetzt zusätzlich die Handanalysen der letzten 24 h vor der
ersten Vorhersagekarte als Stützpunkte heran (`--ohne-analyse` schaltet es
ab). Damit deckt die Zeitachse den Briefing-Vormittag ab, für den innerhalb
eines 00-UTC-Laufs kein Stützpunkt existiert.

### Der erste echte Frontfall — und was er gelehrt hat

Sofort nach dem Einbau meldete der Lauf 26.07. einen Treffer:

```
alpennordhang  Kaltfront  streift  Mon 27.07 02:58 ±6 h   1/327   80 km  ~Rand
```

Gegenprobe auf drei Wegen, alle drei stützen ihn:
- **Rohabstände:** am nördlichsten Spot (47.76 °N) lag die Kaltfront um
  00 UTC 104 km entfernt, um 12 UTC 757 km — sie ist in der Nacht abgezogen.
- **Kartenbild:** die Analyse 00 UTC zeigt die Kaltfront von der Ostsee
  südwestwärts über Deutschland, knapp nördlich der Schweiz vorbei.
- **DWD-Klartext** (`SXDL31`, 27.07. 08 UTC): Langwellentrog zieht ostwärts
  nach Polen, rückseitig subpolare Luft, Schauer „von der Deutschen Bucht bis
  zum Erzgebirge" — also im Norden, nicht bei uns.

**Der Gegenbeweis zur Morgen-Lücke:** derselbe Lauf mit `--ohne-analyse`
meldet **nichts**. Ohne den neuen Stützpunkt wäre das Ereignis unsichtbar
geblieben — der Befund aus §1h ist damit nicht nur theoretisch belegt.

**Zwei Ausgabemängel, die der Fall offengelegt hat, beide behoben:**

1. **1 von 327 Spots ist keine Zonenaussage.** Neu wird ab `MIN_ZONE_SHARE`
   = 10 % betroffener Spots von *quert* gesprochen, darunter von *streift*.
   Ohne diese Trennung würde aus einem Streifschuss am Zonenrand im Text ein
   „Kaltfrontdurchgang am Alpennordhang".
2. **Zeitpunkte am Rand des Stützintervalls sind Randwerte, keine Messwerte.**
   Fällt die Interpolation in die äussersten 10 % eines Intervalls, war die
   Front zum Randtermin bereits am Ort — der wahre Durchgang kann davor
   liegen. Markierung `~Rand`.

**Was der Fall NICHT belegt:** dass die Zeitrechnung bei einem Durchgang
*quer* durch eine Zone stimmt. Dafür fehlt weiterhin ein Fall mit vielen
betroffenen Spots. Das Archiv sammelt ab jetzt automatisch mit.

**Und was er ebenfalls nicht belegt — Zirkularität.** Die 00-UTC-Handanalyse
war unser *Stützpunkt* und kann den daraus abgeleiteten Durchgang nicht
bestätigen. Eine unabhängige spätere Analyse lag noch nicht im Archiv. Urteil
in `observations.csv` deshalb `unklar`, nicht `getroffen`. **Betriebsfolge: zu
beiden Analyseterminen abholen (00 und 12 UTC)** — sonst fehlt jedem Fall die
unabhängige Gegenprobe.

### Erkenntnisspeicher `fronten_validation/` (nach Vorbild `xcontest_validation/`)

Aufgesetzt 27.07. Trennlinie nach gemessener Grösse: **Git hält die Erkenntnis,
die Platte den Rohstoff.**

| versioniert in `fronten_validation/` | ausserhalb (`data/dwd_fronten_archiv/`) |
|---|---|
| `observations.csv` — eine Zeile je vorhergesagtem Durchgang + Verifikation | Analysekarte PNG (~5 MB je Termin → 150–300 MB/Monat) |
| `PATTERNS.md` — Befunde `F-001`…`F-005`, eigener Namensraum gegen die XContest-`I-0xx` | Vorhersagekarten PNG (~1 MB/Tag) |
| `SCHEMA.md`, `README.md`, ereignisbezogene Notizen | ausgelesene Linien ganz Europa (~115 KB/Tag) |
| `aussagen/` — unsere Aussage-Schnappschüsse (~1 KB/Tag) | |

`scripts/build_fronten_observations.py` überträgt die Schnappschüsse
idempotent in die Tabelle (Schlüssel Lauf + Stand + Zone + Typ + Zeit) und
überschreibt von Hand gefüllte Verifikationsspalten nie. Es läuft am Ende von
`archive_dwd_fronten.py` automatisch mit.

**Unterschied zu XContest, bewusst:** dort kuratiert ein Mensch die
Datenbasis, hier füllt sie sich automatisch — der Mensch schreibt nur die
Befunde. Und: **leere Verifikationsspalten heissen „nicht geprüft", nicht
„kein Befund"**; nur Zeilen mit `verdict` dürfen in eine Trefferquote.
Analog zur 0-Launch-Regel gilt eine **0-Front-Regel**: frontfreie Tage
erzeugen keine Zeile, die Tabelle sagt daher nichts darüber, wie oft wir eine
Front *übersehen* — das braucht den Gegenlauf über die Analysen.

Fünf Befunde sind bereits eingetragen: `F-001` Phantom-Durchgänge (gefixt),
`F-002` Streifschuss als Zonenaussage (gefixt), `F-003` Randwerte (gefixt),
`F-004` Front-Identität zwischen zwei Karten (**offen**), `F-005` zeitliche
Systematik unbekannt (**offen, braucht Fälle**).

## 2b. Entschieden: eigene Berechnung, DWD-Text als Gegenprobe

Der DWD-Text (`SXDL31` Kurzfrist, `SXDL33` Mittelfrist) benennt Fronten,
Trogachsen und Grosswetterlage im Klartext und ist frei unter GeoNutzV. Er
wird **nicht** als Quelle in den Wetterlage-Block gemischt — das würde das
Grundprinzip brechen, dass der Textgenerator nur sagen darf, was unser
Strukturfeld belegt. Er dient als **unabhängige Gegenprobe** unserer eigenen
Berechnung.

**Massstab der Gegenprobe:** Vorhandensein, Typ und Zugrichtung — nicht die
exakte Position. Zwei unabhängige *menschliche* Analysen stimmen bei der
genauen Frontlage nur zu 23–30 % überein (bei „Front ja/nein" in grober Zelle
zu 84.8 %). Eine Positionsgleichheit mit der DWD-Karte anzustreben wäre ein
Ziel, das Profis untereinander verfehlen.

Der Umsetzungsteil (Fetch, Klimatologie für die Perzentil-Schwellen,
Alpen-Trennung lokal/synoptisch, Darstellung, Validierungslauf) ist noch zu
schreiben. Grundlage: `meteo_research/fronten_detektion_research.md` §3–§5.

## 6. Umsetzung — Auftrag und Reihenfolge (Stand 26.07.2026, Abend)

**Entschieden:** Variante B mit den DWD-Karten. Einmal täglich um 06:00, Fronten
auf unserer Karte, und das Strukturfeld trägt sie, damit der Wetterlage-Text sie
nennen darf.

**Entscheid zur Verbotsliste:** Die Sperre für „Kaltfront", „Warmfront",
„Okklusion", „Frontdurchgang", „präfrontal", „postfrontal" in
`engine/synoptic_llm.py` **fällt, sobald die Daten im Strukturfeld liegen** —
dann ist der Begriff belegt und darf erwähnt werden. Es bleibt bei der
Belegpflicht wie bei Föhn und Gewitter: ohne Frontobjekt für den Tag kein
Frontwort, sonst erfindet das Modell Fronten an ruhigen Tagen.

**Reihenfolge** (LLM-Anbindung bewusst zuletzt, weil nur sie bestehendes
Verhalten ändert):

1. ~~Extraktion auf die Vorhersagekarten `ico_tkb_na` erweitern~~ —
   **erledigt 27.07., siehe §1f.** Zwei Kartenprofile, Trogachse als vierte
   Klasse, Schwellen geografisch statt in Pixeln, Analysepfad regressionsfest.
2. ~~Zeitachse: aus zwei aufeinanderfolgenden Vorlaufzeiten ableiten, **wann**
   eine Front eine Zone überquert.~~ **erledigt 27.07., siehe §1g.**
   Durchgangszeit je Spot, Ausgabe als Zonenfenster; synthetisch verifiziert,
   an einer realen Frontlage noch nicht (kein Frontfall im Zeitraum).
3. ~~**Archivierung sofort**~~ **erledigt 27.07., §1i** —
   `scripts/archive_dwd_fronten.py`, idempotent, Analyse + tkb + Bulletins.
   **Bis der Scheduler steht (Schritt 7): 1–2× täglich anstossen**, sonst
   fehlen Analysetermine unwiederbringlich.
4. ~~**Morgen-Lücke schliessen**~~ **erledigt 27.07., §1i** — Handanalysen der
   letzten 24 h als Stützpunkte in `load_run()`; Gegenbeweis mit
   `--ohne-analyse` erbracht.
5. **Auto-Validierung**: Vorhersage gegen spätere Handanalyse + Lauf-Jitter
   (Konzept §1h). Erster Anwendungsfall: die nachgeholte Schritt-0-Messung.
6. **Härtung**: Selbsttest um adversariale Fälle erweitern, Legenden-Invariante
   in den Wächter (§1h Befunde 2 und 5).
7. Cache + Scheduler: neben `refresh_synoptic_grid()`, ein Lauf um 06:00.
   Für heute die +036 des gestrigen 00-UTC-Laufs, für morgen die von heute.
   Ausfall-Alarm wie unten.
8. Karte: zusätzliche Ebene in `synoptic-map.js` und `synoptic-embed.js`,
   Quellenangabe „© Deutscher Wetterdienst" plus Änderungshinweis sichtbar.
9. Strukturfeld: `decide_front_passage()` in `synoptic_context.py`.
10. Verbotsliste lockern, mit Belegpflicht und Tests.

**Ausfall-Alarm per Mail — Vorgabe vom 27.07.2026, gehört zu Schritt 3**

Wir hängen an einer fremden Quelle. Bricht sie weg, darf das nicht still
passieren: **Warnmail an `info@wingcast.ch`**, sobald die Kette nicht mehr
liefert.

*Empfänger.* Der einzige bestehende Alarm (`engine/synoptic_llm.py:703`
`_notify_admin()`) geht an `config.ADMIN_EMAIL`, und das steht auf
`mutschgito@hotmail.com` (`config.py:1062`). Also **eigene Konstante**
`config.OPS_ALERT_EMAIL`, Default `info@wingcast.ch`, per Env überschreibbar —
nicht `ADMIN_EMAIL` umbiegen, sonst zieht der Wetterlage-Alarm ungefragt mit um.
Versandweg unverändert: `email_service.send_email_async()`.

*Auslöser — drei klar unterscheidbare Fälle:*

| Fall | Erkennung | Bedeutung |
|---|---|---|
| **Quelle weg** | Download schlägt fehl, HTTP-Fehler, Datei fehlt oder ist kein lesbares PNG | DWD-Server oder Pfad geändert |
| **Layout geändert** | Wächter `check_projection()` unter Schwelle (93 % Analyse / eigene Schwelle `tkb`) | Karte da, aber unsere Kalibrierung passt nicht mehr — der gefährlichste Fall, weil er ohne Wächter falsche Linien produziert |
| **Zeichnung weg** | 0 Abschnitte auf der **gesamten** Karte | Farbschema oder Zeichenweise geändert |

*Zum dritten Fall — der Bezugsrahmen entscheidet.* „Keine Front **in unserem
Gebiet**" ist ein völlig normaler Zustand (stabile Hochdrucklage) und darf
niemals alarmieren; die Kartenebene bleibt dann einfach leer. „Keine Front auf
der **gesamten** Karte" ist etwas anderes: der Ausschnitt reicht von Grönland
bis Nordafrika, dort ist praktisch immer irgendwo eine Front gezeichnet —
gemessen 27.07. über elf Karten: 13 bis 19 Abschnitte, nie null. Die Regel
zählt deshalb ganzkartig, und damit braucht sie keine Vorab-Klimatologie.

Sollte die Ganzkarten-Null wider Erwarten doch vorkommen, meldet sie sich
selbst — als Fehlalarm, der die Regel korrigiert. Das ist der billigere Weg
als eine Messkampagne vorab.

*Betriebsverhalten:*
- **Eine Mail pro Lauf**, nicht eine pro Karte — sonst fünf Mails, wenn der
  ganze Lauf scheitert.
- **Keine Wiederholung**: Zustand in der Cache-Datei mitführen, erneut melden
  erst bei Zustandswechsel oder nach 7 Tagen Dauerausfall. Ein täglich
  gleicher Alarm wird nach einer Woche ignoriert.
- **Entwarnung** senden, wenn es wieder läuft — sonst weiss niemand, ob der
  Fehler noch offen ist.
- Inhalt: welcher Fall, welche URL, Wächterwert gegen Schwelle, Zeitpunkt, und
  ob die Ebene deshalb ausgeblendet ist.
- Das Produktverhalten bleibt davon unberührt: Ebene ausblenden statt falsche
  Linien, kein leerer Rahmen, und der Text darf mangels Frontobjekt ohnehin
  kein Frontwort verwenden (Belegpflicht greift von selbst).

**Umgang mit der Restunschärfe (Vorgabe für Schritt 4–6)**

Erfinden können wir keine Front — es wird nur nachgezeichnet, was gezeichnet
ist. Das Restrisiko liegt darin, eine **echte** Front zeitlich oder räumlich
falsch einzuordnen. Vier Regeln:

1. **Gröber ausgeben als gerechnet.** Nie eine Uhrzeit, sondern die
   bestehenden `SYNOPTIC_DAY_WINDOWS` (morning/midday/afternoon/evening).
   Kein neues Vokabular, und die Körnung passt zur Quelle.
2. **Körnung an die Vorlaufzeit koppeln.** Für heute (aus der +036, kürzeste
   verfügbare Karte) ein Tagesfenster, bei Bedarf zwei benachbarte, wenn die
   Zone breit genug ist, dass die Front mehrere Fenster braucht. Ab Tag 2
   (24-h-Stützweite) nur noch halbtags — „im Lauf des Vormittags".
3. **Gegenprobe nach dem Konzept in §1h:** Schiedsrichter ist die spätere
   Handanalyse (plus Lauf-Jitter und SXDL31-Bulletin); Stationsmessungen nur
   als letzte Stufe, falls die Karten-Schichten nicht reichen. Erst diese
   Messung beantwortet, ob unsere Zeiten **systematisch** zu früh liegen
   (Verdacht: Fronten bremsen am Alpenkamm — Vermutung, nicht gemessen).
4. **Im Zweifel nichts.** Fällt der Wächter, fehlt die Karte oder ist die
   Front unklar: keine Ebene, kein Frontwort, Warnmail. Die Belegpflicht
   sorgt dafür von selbst — ohne Frontobjekt kein Frontbegriff.

**Offene Punkte, die beim Bauen zu klären sind:**
- ~~Ist `tkb` handgezeichnet oder automatisch?~~ **Beantwortet 27.07.:
  handgezeichnet, belegt aus der DWD-Doku — §1f.**
- ~~Wächter gegen stilles Brechen auch für die Vorhersagekarten.~~
  **Erledigt**, eigene Schwelle je Profil, gemessen 98.2–98.5 %.
- Was zeigt die Karte an Tagen ohne Front? Leere Ebene, kein leerer Rahmen.
- **Grundrate „Karte ohne Front in unserem Gebiet"** über einen längeren
  Zeitraum messen — braucht die Alarmregel und die Darstellung gleichermassen
  (§1f, letzter Abschnitt). Vorhaltezeit auf Open Data ist nur ~2 Tage, also
  ab jetzt mitarchivieren, sonst dauert die Messung so lange wie der Zeitraum.

## 3. Varianten zur Entscheidung (überholt — Variante A ist gewählt)

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
