# Föhn-Prognose verbessern — Recherche (Stand 27.09.2026)

Auftrag: bestehende Forschung (`meteo_research/`) sichten, Literatur und
offene Daten prüfen, Schweizer Föhntäler bewerten, Verbesserungswege
vorschlagen. Die Idee „Referenzpunkte in Föhntälern" war der Auslöser; sie
wird hier als eine von mehreren Optionen bewertet.

---

## Für den Manager

1. **Unser Föhn ist heute national, nicht regional.** Eine Druckdifferenz
   Lugano–Zürich plus Höhenwind über Zürich ergibt EINE Föhnstärke für alle
   29 Regionen; regional unterscheidet nur ein statisches Etikett
   (Süd/Nord/Beide). Ob der Föhn in einem Tal am Boden ankommt, wissen wir
   nicht. Ob unsere Warnung stimmt, haben wir noch nie gemessen.
2. **Die Wahrheit liegt gratis bereit.** MeteoSchweiz berechnet an
   39 Stationen alle 10 Minuten einen amtlichen Föhnindex (0 = kein Föhn,
   1 = Föhnmischluft, 2 = Föhn) und publiziert ihn als Open Data —
   laufend UND rückwirkend bis 2020, für Süd- und Nordföhn. Damit ist Föhn
   das einzige unserer Gefahrenthemen mit direkter, stundenscharfer
   Wahrheit (Gewitter: keine Blitzdaten; Fronten: über den Alpen nicht
   berechenbar).
3. **Die Methode der Wahrheit ist dokumentiert und auf Modelldaten
   übertragbar.** MeteoSchweiz vergleicht die potentielle Temperatur an der
   Talstation mit der Kammstation Gütsch, dazu Windsektor, Windstärke,
   Feuchte. Genau diese Grössen liefert unser Wettermodell an jedem
   Punkt. Ein „Modell-Föhnindex" pro Tal ist also die konkrete, prüfbare
   Form der Talpunkt-Idee — und er wird mit derselben Definition gegen die
   Station gemessen.
4. **Reihenfolge: erst messen, dann bauen.** Schritt 1 ist ein Backtest der
   heutigen Warnung gegen die Stationen (2 Jahre rückwirkend möglich,
   weil das deterministische Modell historisch abrufbar ist). Erst dann
   entscheidet sich, ob der Modell-Föhnindex den Aufwand wert ist.
5. ~~Live-Föhnindex anzeigen~~ — verworfen (27.09.): wir zeigen einen
   eingefrorenen Morgenstand, keine Live-Daten; ein Live-Symbol würde das
   Konzept aufweichen. Der Index bleibt Wahrheit für die Prüfung.

**Nachtrag 27.09.2026 — Backtest ist gerechnet** (`validation/foehn/`,
Befunde in `PATTERNS.md`): Trefferquote in Reuss/Rheintal/Glarus 93–99 %,
aber 60–85 % der Warnstunden ohne Föhn am Boden; inneralpin (Andeer, Visp,
Davos) wird jede zweite Föhnstunde verpasst, weil Föhn dort bei Δp < 4 hPa
auftritt; Regionen mit `kritischer_foehn = Beide` erhalten an 53 % aller
Tage eine Föhnwarnung (Nordföhn-Warnung an 36 % der Tage).

---

## 1. Ist-Zustand Wingcast

Quelle: `foehn_indicators.py`, `engine/analyzers.py:_apply_foehn_decision`,
`data/regionen.csv`.

- Eingaben: Druck Lugano − Druck Zürich (Δp), 700-hPa-Wind über **Zürich**
  (Stärke, Richtung), Feuchte und Böigkeit **in Zürich**.
- Schwellen: Δp ≥ 4 hPa → caution, ≥ 8 → danger; Kammwind ≥ 54 km/h →
  caution.
- Regionalisierung: nur über `kritischer_foehn` (Süd/Nord/Beide) — ein
  Filter, keine Messung. Alle Regionen erhalten dieselbe Stärke.
- Briefing: `Foehn=<low|mod|high>` ist das Maximum über alle Regionen.
- Ausgabe im Prognose-Archiv: nur `foehn_risk` pro Spot/Region — die
  Eingaben (Δp, Kammwind) werden nicht eingefroren.
- Kein `docs/FOEHN.md`; Föhn ist das einzige Gefahrenthema ohne Konzept-Dokument.

Bestehende eigene Recherche (`foehn_altitude_winds.md`, `wetterlagen_pilotenwissen.md`,
`region_refpoints_research.md`) hält bereits fest:

- **Versteckter Föhn**: Kaltluftsee im Tal, Bodenstation ruhig, 850/700 hPa
  stürmisch → Verhältnis Höhenwind/Bodenwind > 3:1 bei Südströmung als
  Warnsignal. Empfohlen, **nicht umgesetzt**.
- Föhn tritt schon ab **2 hPa** Δp auf (flacher Föhn); Δp allein reicht nicht.
- Föhndurchbruch ist topographisch fixiert (Pässe, Talausgänge); Skala
  5–30 km → die geometrisch gesetzten Edge-Referenzpunkte treffen diese
  Stellen zufällig oder gar nicht. Empfohlen: manuelle Föhn-Anker pro Region
  („Priorität 2, High Impact") — **nicht umgesetzt**.

---

## 2. Was die Literatur sagt

### 2.1 Der amtliche Föhnindex (Dürr 2008, Arbeitsbericht MeteoSchweiz 223)

Automatische Föhnbestimmung alle 10 Minuten aus Stationsdaten. Kern:

- **Referenz am Alpenkamm: Gütsch ob Andermatt (GUE, 2282 m).** Föhn nur,
  wenn das Stundenmittel der Windrichtung am Gütsch im Sektor **90–240°**
  liegt. Für Wallis-Stationen dient der Grosse St. Bernhard (Ostwind),
  für Rheintal/Bodensee zusätzlich Hinterrhein.
- **Δθ = θ(Tal) − θ(Gütsch)** (potentielle Temperatur). Föhnluft steigt
  trockenadiabatisch ab → θ bleibt erhalten; die Talluft darf also nicht
  deutlich potentiell kälter sein als der Kamm. Schwelle stationsabhängig,
  z. B. Altdorf ≥ −4.0 K, Vaduz ≥ −2.8 K, Sion ≥ −4.5 K.
- **Föhneinsatz**: Δθ ≥ x UND (Wind ≥ x ODER Böe ≥ x) UND Feuchte ≤ x UND
  Windrichtung im stationstypischen Föhnsektor.
  Altdorf: Wind ≥ 3.7 m/s oder Böe ≥ 6.2 m/s, RH ≤ 54 %, Sektor 60–240°.
- **Föhnfortdauer**: ohne Windkriterium (überbrückt Flauten), nur Δθ, Feuchte,
  Sektor. Ende, sobald ein Kriterium oder der Gütsch-Sektor verletzt ist.
- **Index 1 „Föhnmischluft"**: Δθ schwächer, Richtung streuender — Föhn mit
  Kaltluft aus Seitentälern (Chur vormittags, Sion fast die Hälfte aller
  Föhnstunden).
- Validierung gegen manuelle Auswertung: Altdorf ±3.6 % (sehr gut), Vaduz
  −20 % (Δθ-Schwelle zu streng). Die Methode gilt „streng genommen nur für
  Stationen in Tallagen oder am Talausgang, wo die Strömung kanalisiert ist".

Der Bericht behandelt nur Südföhn. Die heute publizierten OGD-Daten
enthalten aber auch an Alpensüdseite-Stationen (Piotta, Magadino, Lugano,
Poschiavo …) einen Index — MeteoSchweiz hat das Verfahren also auf
Nordföhn ausgedehnt; dessen Kriterien habe ich nicht dokumentiert gefunden.

### 2.2 Föhnklimatologie der Schweizer Täler (Gutermann, Dürr, Richner, Bader 2012)

- Föhnhäufigkeit ist zu **−0.96 korreliert mit der Höhendifferenz** zwischen
  dem massgebenden Passübergang und der Station: je tiefer die Station
  unter dem Pass, desto seltener bricht Föhn durch. Dazu horizontaler
  Abstand zum Hauptkamm und Talausrichtung relativ zum Druckgradienten
  (Ost-West-Täler wie Interlaken, Sion: selten).
- Föhntermine pro Jahr 1984–2008 (Index um 6/12/18 UTC), Verhältnis zu
  Altdorf = 100 %: Davos 151 %, Visp 146 %, Chur 123 %, Vaduz 83 %,
  Engelberg 47 %, Sion 40 %, Glarus 38 %, St. Gallen 33 %, Aigle 12 %,
  Interlaken 10 %, Luzern 8 %, Wädenswil 6 %, Güttingen 5 %, Zürich 2 Termine.
  Föhnstunden 1991–2000 (Dürr): Altdorf 478 h/Jahr, Visp 577, Chur 459,
  Vaduz 388, St. Gallen 191, Glarus 178, Sion 148, Aigle 72, Interlaken 44.
- Lokaleffekte: **Bad Ragaz** häufiger als Chur (Massendivergenz an der
  Verzweigung Seeztal/St. Galler Rheintal → Absinken); **Meiringen** nur gut
  halb so oft wie Altdorf (Talverengung Kirchet), **Guttannen** im oberen
  Haslital doppelt so oft wie Altdorf; **Interlaken** zehnmal seltener als
  Meiringen; Glarus halb so oft wie Tierfehd; **Heiden** (800 m) öfter als
  das St. Galler Rheintal darunter, weil oberhalb des Kaltluftsees.
- Jahresgang: April/Mai Maximum, August Minimum (Verhältnis 5.3:1),
  Nebenmaximum Oktober. Tagesgang: Nachmittag Maximum, nachts hebt der
  Kaltluftsee den Föhn vom Boden ab.

### 2.3 Föhntypen (Jansing et al. 2022, COSMO-1-Analysen 2015–2020, Altdorf)

- 89 % **tiefer Föhn** (700 hPa > 5 m/s aus 90–270°), 6 % **flacher Föhn**
  (Kammwind ≤ 5 m/s, temperaturgetrieben), 4 % **Gegenstromföhn**
  (Westwind 240–360° am Kamm, antizyklonale Scherung).
- Flacher und Gegenstromföhn reichen nur in die grossen S–N-Transekte
  (Reuss, Rhein), nicht ins Vorland. Unser 700-hPa-Kriterium (Südsektor,
  ≥ 54 km/h) verpasst beide Typen systematisch.

### 2.4 Kann ein Modell den Föhn am Talboden? (Tian et al. 2024, 2026)

- COSMO-1 (1.1 km): **Kaltbias am Boden während Föhn −1.8 K** in den
  Nordföhntälern (5-Jahres-Klimatologie), −3 K im Rheintal bei starken
  Fällen; bekannte Fehler: zu früher/zu später Durchbruch, zu feucht nach
  dem Durchbruch, Föhn am Bodensee hält zu lange an. Signatur am klarsten in
  Altdorf, Vaduz, Altenrhein; in Chur/Bad Ragaz schwächer (Tagesgang überlagert).
- **ICON schlägt COSMO**: Kaltbias −1.5 K statt −3 K, bessere Einsatz-/
  Endzeiten, bessere Ausdehnung. Open-Meteo `icon_ch1` ist ICON-CH1 — wir
  sitzen auf dem besseren Modell.
- Konsequenz für einen Modell-Föhnindex: der Kaltbias macht Δθ zu negativ →
  Durchbrüche würden **verpasst**, nicht erfunden. Die Δθ-Schwelle muss am
  Modell kalibriert werden, nicht von der Station übernommen.

### 2.5 Statistische Verfahren

- **Sprenger et al. 2017**: AdaBoost auf COSMO-7-Feldern, Ziel Föhn in
  Altdorf: Trefferquote 88 %, korrekte Alarme 66 % — besser als der
  klassische Druckgradient.
- **Aichinger-Rosenberger et al. 2022**: ML auf GNSS-Feuchtegradienten,
  Altdorf: POD 0.71–0.85, CAR 0.74–0.80.
- **Stauffer, Zeileis, Mayr 2024**: Föhnwahrscheinlichkeit pro Stunde aus
  ERA5-Reanalyse (30 km!) an sechs Stationen CH/AT, Nord- und Südföhn, bis
  1940 rekonstruiert. Zeigt: schon grobe Modellfelder tragen das Signal, wenn
  man sie gegen Stationswahrheit trainiert.
- Alle drei setzen voraus, was wir noch nicht haben: **Paare Modell ↔
  Stationsindex**. Der Backtest (Schritt 1 unten) erzeugt genau diese Paare.

---

## 3. Wahrheitsdaten: der offene Föhnindex

- Parameter `wcc006s0` (Föhnindex, Code 0/1/2) im SwissMetNet-OGD,
  `https://data.geo.admin.ch/ch.meteoschweiz.ogd-smn/<abk>/ogd-smn_<abk>_t_recent.csv`
  (laufendes Jahr) und `…_t_historical_2020-2029.csv` (ab 01.01.2020).
  Stationskürzel klein geschrieben. Zugriff wie in `scripts/validation_common.py`.
- Geprüft 27.09.2026: 39 Stationen führen den Index; Altdorf 2020–2025:
  315 648 Zehnminutenwerte, 12 648 davon Föhn (= 2108 h). Gütsch selbst
  hat keinen Index (Referenz).
- Lizenz OGD MeteoSchweiz (Quellenangabe).

### 3.1 Föhnstunden 2026 (01.01.–26.09.) je Station, Zuordnung zu unseren Regionen

Rangliste nach Stunden mit Index 2; „Misch" = Index 1; „Ri" = mittlere
Windrichtung während Föhn (zeigt Süd- vs. Nordföhn). Region per
Punkt-in-Polygon gegen `regionen_polygone_mapped.geojson`.

| Abk | Station | m ü.M. | Föhn-h | Misch-h | Ri | Wingcast-Region | Typ |
|---|---|---|---|---|---|---|---|
| PIO | Piotta | 990 | 875 | 127 | 274 | Leventina / Blenio | Nord |
| ROB | Poschiavo/Robbia | 1078 | 806 | 173 | 47 | — (Puschlav, keine Region) | Nord |
| VIO | Vicosoprano | 1089 | 616 | 249 | 73 | — (Bergell, keine Region) | Nord |
| SBE | S. Bernardino | 1639 | 451 | 164 | 312 | Locarnese / Bellinzonese | Nord |
| COM | Acquarossa/Comprovasco | 575 | 418 | 220 | 340 | Leventina / Blenio | Nord |
| VIS | Visp | 639 | 374 | 21 | 110 | Oberwallis / Goms | Süd(-ost) |
| CEV | Cevio | 417 | 344 | 137 | 15 | Leventina / Blenio | Nord |
| AND | Andeer | 987 | 318 | 120 | 184 | Mittelbünden | Süd |
| RAG | Bad Ragaz | 497 | 296 | 170 | 130 | Rheintal | Süd |
| MAG | Magadino/Cadenazzo | 203 | 277 | 210 | 82 | Locarnese / Bellinzonese | Nord |
| SBO | Stabio | 351 | 249 | 160 | 21 | — (Mendrisiotto) | Nord |
| ELM | Elm | 958 | 237 | 140 | 132 | Glarner Alpen | Süd |
| LUG | Lugano | 273 | 234 | 139 | 22 | — (Sottoceneri) | Nord |
| CHU | Chur | 556 | 212 | 249 | 204 | Rheintal | Süd |
| DAV | Davos | 1594 | 194 | 46 | 194 | Prättigau - Davos | Süd |
| EVI | Evionnaz | 482 | 188 | 35 | 159 | Waadtländer Alpen | Süd |
| ALT | Altdorf | 438 | 186 | 36 | 150 | Zentralschweizer Alpen | Süd |
| MVE | Montana | 1423 | 181 | 19 | 63 | Unterwallis | Süd(-ost) |
| GRO | Grono | 324 | 163 | 98 | 13 | Locarnese / Bellinzonese | Nord |
| OTL | Locarno/Monti | 367 | 131 | 74 | 144 | Locarnese / Bellinzonese | Nord* |
| VAD | Vaduz | 457 | 110 | 49 | 176 | Rheintal | Süd |
| ABO | Adelboden | 1321 | 79 | 4 | 216 | Berner Oberland | Süd |
| MER | Meiringen | 589 | 67 | 5 | 114 | Berner Alpen | Süd |
| HOE | Hörnli | 1133 | 48 | 4 | 182 | Alpstein / Toggenburg | Süd |
| ENG | Engelberg | 1036 | 35 | 8 | 92 | Zentralschweizer Alpen | Süd |
| GLA | Glarus | 517 | 30 | 2 | 143 | Glarner Alpen | Süd |
| STG | St. Gallen | 776 | 27 | 26 | 149 | Bodenseeraum | Süd |
| SIO | Sion | 482 | 25 | 37 | 78 | Unterwallis | Süd(-ost) |
| OBR | Oberriet/Kriessern | 409 | 19 | 7 | 195 | Rheintal | Süd |
| EIN | Einsiedeln | 911 | 10 | 1 | 204 | Zentrale Voralpen | Süd |
| ARH | Altenrhein | 398 | 8 | 3 | 184 | Rheintal | Süd |
| AIG | Aigle | 381 | 8 | 4 | 129 | Waadtländer Alpen | Süd |
| LUZ | Luzern | 454 | 6 | 10 | 137 | Zentrale Voralpen | Süd |
| WAE | Wädenswil | 485 | 5 | 2 | 190 | Mittelland Ost | Süd |
| SMA | Zürich/Fluntern | 604 | 2 | 1 | 174 | Mittelland Ost | Süd |
| GIH | Giswil | 471 | 2 | 0 | 202 | Zentralschweizer Alpen | Süd |
| EBK | Ebnat-Kappel | 623 | 2 | 3 | 153 | Alpstein / Toggenburg | Süd |
| INT | Interlaken | 578 | 2 | 3 | 67 | Berner Alpen | Süd |
| GUT | Güttingen | 440 | 0 | 4 | — | Bodenseeraum | Süd |

\* Locarno/Monti mit Richtung 144 bei Nordföhn ist ein Hangstations-Effekt
(Monti liegt am Hang über Locarno); nicht als Talboden-Wahrheit nehmen.

Lesehilfe: 2026 war bisher ein Nordföhn-Jahr (Südtessin/Südbünden führen);
Jan–Sep ohne das Herbstmaximum, deshalb Altdorf mit 186 h unter dem
langjährigen Mittel (~480 h). Für die Bewertung der Täler gilt die
Klimatologie in 2.2, nicht ein einzelnes Jahr.

### 3.2 Bewertung der Föhntäler aus Wingcast-Sicht

Kriterien: Föhnhäufigkeit (Klimatologie + 2026), Talboden-Station als
Wahrheit vorhanden, Flugspots in der Region betroffen, Signalqualität der
Station (Tian 2024: Altdorf/Vaduz klar, Chur/Ragaz überlagert).

**Klasse A — kanalisierte Südföhntäler mit klarer Wahrheit (zuerst):**

| Tal | Wahrheit | Region | Bemerkung |
|---|---|---|---|
| Reusstal / Urnerland | ALT (+ ENG als Seitental) | Zentralschweizer Alpen | Referenzstation der Schweiz, 160 Jahre Reihe, klarste Signatur |
| Churer Rheintal – Sarganserland | CHU, RAG | Rheintal | häufigstes Föhntal der Nordseite; Ragaz > Chur wegen Talverzweigung; Chur viel Mischluft → Index 1 mitführen |
| St. Galler Rheintal | VAD, OBR, ARH | Rheintal | Vaduz klar; talabwärts nimmt Föhn stark ab — zwei Punkte nötig (Vaduz / Altenrhein) |
| Glarnerland | GLA, ELM | Glarner Alpen | Elm (oben) häufig, Glarus (unten) selten → Höhenabhängigkeit exakt messbar |
| Haslital | MER | Berner Alpen | Guttannen wäre besser (2× Altdorf), hat aber keinen Index; Kirchet-Engstelle |
| Domleschg / Schams | AND | Mittelbünden | 318 h, klar Süd |
| Davos / Prättigau | DAV | Prättigau - Davos | häufigste inneralpine Station (151 % Altdorf) |

**Klasse B — Wallis (Ost-West-Tal, Föhn bei SE-Höhenwind):**

| Tal | Wahrheit | Region | Bemerkung |
|---|---|---|---|
| Oberwallis Visp–Brig | VIS | Oberwallis / Goms | 577 h/Jahr, mehr als Altdorf; Föhn aus E/SE — unser Südsektor 135–225° trifft ihn nur teilweise |
| Mittelwallis Sion | SIO, MVE | Unterwallis | Sion ~40 % Altdorf, fast die Hälfte Mischluft — schwieriger Fall |
| Unterwallis Martigny–Chablais | EVI, AIG | Waadtländer Alpen | Evionnaz 188 h |

**Klasse C — Nordföhn (Alpensüdseite):**

| Tal | Wahrheit | Region | Bemerkung |
|---|---|---|---|
| Leventina / Blenio / Maggia | PIO, COM, CEV | Leventina / Blenio | Piotta 875 h — stärkstes Föhnsignal des Jahres überhaupt |
| Magadinoebene / Misox | MAG, GRO, SBE | Locarnese / Bellinzonese | Magadino viel Mischluft |
| Puschlav, Bergell, Sottoceneri | ROB, VIO, LUG, SBO | **keine Wingcast-Region** | Wahrheit vorhanden, aber ausserhalb unserer Polygone |

**Ohne Stationswahrheit:** Oberengadin (Malojawind — kein Index),
Surselva, Lötschental, Walliser Hochalpen, Freiburger Voralpen, Emmental.
Dort bleibt nur der Kammwind als Näherung.

**Konsistenz-Check `kritischer_foehn`:** Rheintal/Zentralschweiz/Glarus/
Berner Alpen = Süd ✓; Leventina/Locarnese = Nord ✓; Prättigau, Mittelbünden,
Ober-/Unterwallis = Beide — die Stationen zeigen 2026 dort praktisch nur
Süd(-ost)föhn. „Beide" ist vertretbar (Nordföhn kommt vor), kostet aber
Warnungen bei Nordlagen, die im Wallis meist fliegbar sind. Mit den
Stationsdaten lässt sich das pro Region beziffern.

---

## 4. Optionen zur Verbesserung — bewertet

### Option 1 — Messen, was wir haben (Backtest)  ·  Pflicht, zuerst

Unsere nationale Warnung (`foehn_risk` je Region und Tag) gegen den
Stationsindex der zugeordneten Föhnstationen legen: Trefferquote,
Fehlalarme, Zeitversatz. Zwei Datenquellen:

- **Vorwärts** seit 02.08.2026 aus dem Prognose-Archiv (nur `foehn_risk`,
  Eingaben fehlen). Wenig Föhn in Aug/Sep → dünne Basis.
- **Rückwärts 2024–2026**: Δp und Kammwind aus Open-Meteo
  `historical-forecast-api` (icon_ch1 ist deterministisch → 1:1
  rekonstruierbar, anders als das Ensemble) für Zürich/Lugano neu rechnen und
  gegen den historischen Index (seit 2020) stellen. Das liefert **zwei
  Föhnfrühlinge** mit je ~400–700 Föhnstunden in Altdorf.

Ergebnis ist eine Zahl je Region: „Warnung bei X % der Föhnstunden am
Boden, Y % Fehlalarme". Aufwand 1–2 Tage, Werkzeug analog
`validation/gewitter/`. Nebenprodukt: die Paare Modell ↔ Index für Option 5.

### Option 2 — Modell-Föhnindex pro Tal (Dürr-Methode auf Modelldaten)  ·  Kern

Das ist die Talpunkt-Idee, verankert an der amtlichen Definition:

- Pro Föhntal ein **Talpunkt** (auf der Station, damit die Wahrheit exakt
  dort liegt) und ein **Kammpunkt** (Gütsch für Nordseite, Grosser
  St. Bernhard für Wallis, analog für Nordföhn). Beides Modell-Gitterpunkte
  von Open-Meteo icon_ch1: T, p, RH, Wind, Böe, Richtung, stündlich.
- Berechnung Δθ, Windsektor, ff/fx, RH nach Dürr; Schwellen **am Modell
  kalibriert** (Kaltbias −1.5 K → Δθ-Schwelle verschieben), Kalibrierung
  und Prüfung getrennt (2024 lernen, 2025/26 prüfen).
- Ausgabe pro Tal und Stunde: „Föhn am Boden ja/nein/Mischluft" + Einsatz-
  und Endzeit. Kombiniert mit dem Kammwind ergibt das die Aussage, die dem
  Piloten fehlt: **Föhn oben, unten noch Kaltluftsee** vs. **Föhn durch**.
- Architektur: **eigene Punkt-Ebene** (eigene GeoJSON, Loader, API, Karte)
  wie die Niederschlags-Referenzpunkte — NICHT in die 7 Regions-
  Referenzpunkte, deren Wind-Median und Thermik-Anker ein Talboden-Punkt
  verzerren würde (`docs/REFPOINT_KONZEPT.md`).
- Kosten: ~25 Punkte (Tal + Kamm) in einem Multi-Point-Abruf, marginal;
  Chunk-Grösse im Datenbezug beachten.
- Risiko: Modelle unterschätzen kanalisierten Talwind, Durchbruch ±1–2 h
  unscharf (Tian 2024). Beides wird durch Option 1/2 gemessen, nicht geglaubt.

### Option 3 — Regionale Druckdifferenzen statt nur Lugano–Zürich  ·  günstig

- Lugano–Altdorf, Lugano–Chur, Lugano–Kloten für die Nordseite; Wallis über
  die Achse Grosser St. Bernhard (Ostwind) bzw. Aosta–Sion; Nordföhn als
  negatives Δp Zürich–Lugano mit eigenen Schwellen.
- Schwellen aus Option 1 ableiten (heute 4/8 hPa „Gemini-Empfehlung", nie
  gemessen). Flacher Föhn ab 2 hPa nur in den grossen Transekten.

### Option 4 — Versteckter Föhn pro Spot (Höhenwindprofil)  ·  günstig, schon recherchiert

Verhältnis 850/700-hPa-Wind zu Bodenwind mit Südkomponente oben > 3:1 →
Warnung „Föhn über dem Kaltluftsee" (`foehn_altitude_winds.md`). Daten
sind je Spot bereits im Abruf; LLM-Kontext und Decision-Tag fehlen.
Wirkt genau dort, wo Option 2 „Föhn oben, unten nicht" sagt.

### Option 5 — Statistisches Lernen (Sprenger-Stil)  ·  später

Klassifikator auf Modellfeldern gegen Stationsindex; braucht die Paare aus
Option 1/2 und mindestens zwei Frühlinge. Erst sinnvoll, wenn Option 2
als Regelwerk ausgereizt ist.

### Option 6 — Live-Föhnindex anzeigen  ·  VERWORFEN

Widerspricht dem Produktkonzept (eingefrorener Morgenstand, keine
Live-Daten). Der Index dient ausschliesslich der Validierung.

### Empfohlene Reihenfolge

1. Option 1 (Backtest) — **erledigt 27.09.2026**, siehe `validation/foehn/PATTERNS.md`.
2. Entscheid anhand der Zahlen: Option 3 (Schwellen) sofort; Option 2
   (Modell-Föhnindex) für die Klasse-A-Täler, dann B und C.
3. Option 4 als Spot-Ergänzung; `docs/FOEHN.md` anlegen.
4. Option 5 frühestens nach zwei gemessenen Föhnfrühlingen.

Was NICHT zu erwarten ist: eine stundenscharfe Durchbruchszeit. Realistisch
sind „Föhn am Boden im Tal X am Nachmittag wahrscheinlich" mit ±1–2 h.

---

## Quellen

- Dürr, B. (2008): Automatisiertes Verfahren zur Bestimmung von Föhn in
  Alpentälern. Arbeitsbericht MeteoSchweiz 223.
  https://www.meteoswiss.admin.ch/dam/jcr:3ed2aec8-0901-417a-acc3-8be11cce440a/Foehnindex_Arbeitsbericht_223_Automatisiertes_Verfahren_zur_Bestimmung_von_Foehn_in_Alpentaelern_de.pdf
- Gutermann, Dürr, Richner, Bader (2012): Föhnklimatologie Altdorf: die
  lange Reihe (1864–2008), Vergleich mit anderen Stationen. Fachbericht
  MeteoSchweiz 241.
  https://www.meteoswiss.admin.ch/dam/jcr:698b5cdf-92cf-491a-8d88-c844113aa8d6/Foehnklimatologie_Altdorf_die_lange_Reihe_1864-2008_und_ihre_Weiterfuehrung_Vergleich_mit_anderen_Stationen_de.pdf
- MeteoSchweiz OGD SwissMetNet, Parameter `wcc006s0` (Föhnindex 10 min):
  https://opendata.swiss/de/dataset/messwerte-fohnindex-10-min-wert ·
  https://opendatadocs.meteoswiss.ch/a-data-groundbased/a1-automatic-weather-stations
- MeteoSchweiz: Föhnindex / Föhnhäufigkeit (Web, JS-gerendert):
  https://www.meteoswiss.admin.ch/weather/weather-and-climate-from-a-to-z/foehn-index.html ·
  https://www.meteoswiss.admin.ch/weather/weather-and-climate-from-a-to-z/foehn-frequency.html
- Jansing, Papritz, Sprenger et al. (2022): Classification of Alpine south
  foehn based on 5 years of kilometre-scale analysis data. WCD 3, 1113.
  https://wcd.copernicus.org/articles/3/1113/2022/
- Tian, Quimbayo Duarte, Schmidli (2024): A station-based evaluation of
  near-surface south foehn evolution in COSMO-1. QJRMS 150, 290–317.
  https://rmets.onlinelibrary.wiley.com/doi/10.1002/qj.4597
- Tian, Quimbayo Duarte, Singh, Schmidli (2026): Comparison of two NWP
  models in simulating south foehn in the Alpine Rhine Valley. QJRMS.
  https://rmets.onlinelibrary.wiley.com/doi/10.1002/qj.70122
- Sprenger, Schemm, Oechslin, Jenkner (2017): Nowcasting Foehn Wind Events
  Using the AdaBoost Machine Learning Algorithm. Wea. Forecasting 32.
  https://journals.ametsoc.org/view/journals/wefo/32/3/waf-d-16-0208_1.xml
- Aichinger-Rosenberger et al. (2022): Machine learning-based prediction of
  Alpine foehn events using GNSS troposphere products. AMT 15, 5821.
  https://amt.copernicus.org/articles/15/5821/2022/
- Stauffer, Zeileis, Mayr (2024): Long-Term Foehn Reconstruction Combining
  Unsupervised and Supervised Learning. Int. J. Climatol.
  https://rmets.onlinelibrary.wiley.com/doi/10.1002/joc.8673
- MeteoSchweiz-Blogs: Föhn in den Alpen (03/2024), Der April bringt am
  meisten Föhn (04/2024), Ein Jahr mit vielen Föhnstunden (11/2024).
  https://www.meteoschweiz.admin.ch/ueber-uns/meteoschweiz-blog/de/2024/03/foehn-in-den-alpen.html
- SRF Meteo: Nordföhn vs. Südföhn.
  https://www.srf.ch/meteo/meteo-stories/wetterwissen-nordfoehn-vs-suedfoehn-die-unterschiede
- Eigene Recherche: `meteo_research/foehn_altitude_winds.md`,
  `region_refpoints_research.md`, `wetterlagen_pilotenwissen.md`,
  `synoptic_pilot_needs.md`, `model_comparison.md`.
