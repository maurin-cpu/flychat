# Höhenwinde als Föhn-Indikator

## Kernproblem: "Versteckter Föhn" (Hidden Foehn)

Bei Föhn bilden sich oft **Kaltluftseen** in den lee-seitigen Tälern. Der warme Föhnwind
fährt über den kalten, dichten Kaltluftsee hinweg. Die Folge:

- **Bodenstationen melden Ruhe** (sie befinden sich im Kaltluftsee)
- **Höhenwinde (850hPa, 700hPa) zeigen starken alpenquerenden Wind**
- Extrem starke Windscherung an der Inversionsgrenze

> "Die warme Föhnluft bewegt sich über den Kaltluftsee. Nur Höhenstationen zeigen den Föhn."
> — Chill Out Paragliding

**Gefahr für Gleitschirmfliegen**: Piloten starten bei vermeintlich ruhigen Bedingungen
und geraten in der Höhe in Föhnturbulenz. Landeanflüge durch die Scherungszone sind
besonders gefährlich (abnehmender Gegenwind → Strömungsabriss).

## Drei Föhn-Typen (Jansing et al. 2022, Weather & Climate Dynamics)

### 1. Tiefer Föhn (Deep Foehn)
- 700hPa Wind **> 18 km/h** aus Süd (135-225°)
- Südliche Strömung durch mehrere Schichten bis unter 2000m
- SW-Winde ~50 km/h bei 500hPa
- Klassisch, stark, gut am Druckgradienten erkennbar

### 2. Flacher Föhn (Shallow Foehn)
- 700hPa Wind **< 18 km/h** — schwacher Kammwind
- Angetrieben durch Temperaturunterschiede, nicht Druckgradient
- **Trotzdem gefährlich** durch lokale Kanalisierung
- Kann schon ab **2 hPa** Delta-P auftreten!

### 3. Gegenstrom-Föhn (Counter-flow Foehn)
- 700hPa Wind > 18 km/h, aber aus **West/Nordwest (240-360°)**
- Starke Westwinde ~90 km/h bei 500hPa
- Antizyklonische Scherung zwischen 700hPa und 500hPa
- Weniger intuitiv, aber real und dokumentiert

## Schwellwerte für Erkennung

### Druckgradient (Lugano minus Zürich, Südföhn)

| Delta-P (hPa) | Bedeutung |
|---|---|
| >= 3 | Föhntendenz in den Alpen |
| >= 4 | **Föhndurchbruch in Alpentälern** (wichtigste Schwelle) |
| >= 5 | Föhn erreicht Vorland |
| >= 8 | **Föhndurchbruch ins Flachland** (extrem) |

### Höhenwind-Kriterien

| Parameter | Vorsicht | Gefahr |
|---|---|---|
| Wind 850hPa (~1500m) | > 30 km/h aus Süd | > 50 km/h |
| Wind 700hPa (~3000m) | > 54 km/h (15 m/s) aus Süd | > 90 km/h |
| Verhältnis Höhe/Boden | > 3:1 bei Südwind oben | > 5:1 |
| Windrichtung 850hPa | SSW-SW (180-225°) | — |

### Kombiniertes Kriterium

**Versteckter Föhn**: Wind bei 850hPa > 30 km/h aus Süd (135-225°) **UND** Bodenwind < 10 km/h
→ Verhältnis > 3:1 mit südlicher Richtung in der Höhe = starker Hinweis auf Föhn mit Kaltluftsee.

## Wichtige Erkenntnis: Druckgradient allein reicht nicht

- Föhn kann schon ab **2 hPa** Delta-P auftreten (Temperaturunterschiede treiben den Fluss)
- In solchen Fällen ist das **Höhenwind-Profil zuverlässiger** als der Druckgradient
- Temperaturunterschiede von 3-4°C auf 800hPa zwischen Süd- und Nordseite können
  Föhnströmung unabhängig von Drucksystemen auslösen

## "Föhnfinger" auf 800hPa (~2000m)

Bei 800hPa erscheinen Föhnströme als "fingerartige Streifen mit deutlichen Windspitzen"
in hochaufgelösten Modelldaten (ICON-D2). Am besten sichtbar auf Windy.com bei 800hPa.

## Relevanz für Wingcast

### Was bereits implementiert ist (`foehn_indicators.py`)
- Druckgradient (Lugano/Zürich)
- Kammwind (700hPa Geschwindigkeit + Richtung) — **Achtung: über Zürich, nicht am Kamm**
- Luftfeuchtigkeit als Bestätigungsindikator
- seit 27.09.2026: Südföhn-Δp-Trigger nur bei 700-hPa-Wind im Südhalbkreis 90–270°

### Was fehlt / ergänzt werden sollte
- **Verhältnis Bodenwind zu Höhenwind pro Spot** (versteckter Föhn)
- Pro Spot die Höhenwinde bei 850/800hPa mit dem Bodenwind vergleichen
- Im LLM-Kontext die relevanten Höhenwinde mitliefern
- Prompt-Hinweis: grosses Verhältnis + südliche Strömung in Höhe = Föhn-Warnung

### Nachtrag 27.09.2026 — was der Backtest zu diesem Dokument sagt

Quelle: `validation/foehn/PATTERNS.md` (1000 Tage gegen den MeteoSchweiz-
Föhnindex), Recherche `foehn_valley_forecasting.md`.

- **Schwellentabelle bestätigt, für die grossen Täler.** Δp während Föhn
  in Altdorf: P10 4.4, Median 7.4 hPa; bei ≥ 4 hPa werden 94 % der
  Föhnstunden erkannt. Die Faustregel „4 hPa = Durchbruch in die Alpentäler"
  hält.
- **„Föhn schon ab 2 hPa" bestätigt — aber nur inneralpin.** Visp, Andeer,
  Davos haben 42–52 % ihrer Föhnstunden bei Δp < 4, Andeer 24 % bei < 2.
  In Altdorf/Glarus sind es < 6 % bzw. 0.5 %. Der Satz „Druckgradient
  allein reicht nicht" gilt also ortsabhängig: inneralpin ja, in den
  kanalisierten Nordföhntälern nein.
- **Der „Kammwind" dieses Dokuments ist keiner.** `foehn_indicators` liest
  700 hPa **über Zürich**. Als Pflichtbedingung (≥ 30 km/h) halbiert er die
  Trefferquote in Altdorf (93 → 53 %) — d. h. bei der Hälfte aller echten
  Föhnstunden weht über Zürich auf 700 hPa fast nichts. Die Höhenwind-
  Kriterien der Tabelle oben (850 hPa > 30 km/h aus Süd usw.) sind darum
  nur sinnvoll, wenn sie **am Spot oder am Kamm** (Gütsch-Äquivalent)
  abgefragt werden — genau das, was der Abschnitt „Was fehlt" verlangt und
  was weiterhin nicht gebaut ist.
- **Versteckter Föhn ist die Hauptquelle der Fehlalarme.** 60–85 % der
  Warnstunden haben keinen Föhn am Talboden; ein Teil davon ist Föhn über
  dem Kaltluftsee. Die Talstation kann das nicht trennen — der hier
  vorgeschlagene Höhen/Boden-Vergleich pro Spot ist der Weg, es zu
  unterscheiden. Bleibt offen.
- **Föhntypen (Jansing 2022) quantifiziert:** Der bestehende enge Sektor
  135–225° verpasst SW-Föhn (225–270°) und Gegenstromföhn; der Halbkreis
  90–270° ist seit 27.09. die Bedingung für den Δp-Trigger, der
  Kammwind-Trigger nutzt weiterhin 135–225°.

## Quellen

- [Jansing et al. (2022) - Classification of Alpine south foehn, Weather and Climate Dynamics](https://wcd.copernicus.org/articles/3/1113/2022/)
- [MeteoSwiss - Foehn](https://www.meteoswiss.admin.ch/weather/weather-and-climate-from-a-to-z/foehn.html)
- [MeteoSwiss - Foehn Index](https://www.meteoswiss.admin.ch/weather/weather-and-climate-from-a-to-z/foehn-index.html)
- [EUMETRAIN - Foehn Satellite Manual](https://resources.eumetrain.org/satmanu/CMs/Fh/print.htm)
- [lu-glidz - Foehn bei kleinem Druckgradient](https://lu-glidz.blogspot.com/2022/12/fohn-bei-kleinem-druckgradient.html)
- [Chill Out Paragliding - Kaltluftsee verschleiert Foehn](https://chilloutparagliding.com/infos/news-reports/kaltluft-verschleiert-foehn/)
- [meteoblue - Foehn (Part 3/3)](https://www.meteoblue.com/en/blog/article/show/40350_Weather+Phenomenon+-+Foehn+(Part+3%2F3))
- [SKYbrary - Mountain Waves](https://skybrary.aero/articles/mountain-waves)
- [Chamonix Paragliding Weather](https://flyddiction.com/en/chamonix-paragliding-weather/)
