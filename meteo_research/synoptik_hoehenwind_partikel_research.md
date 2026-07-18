# Synoptik-Karte: Wind-Partikel-Layer — warum MSLP-Geostrophie über den Alpen scheitert und was Profis stattdessen zeigen

Stand: Juli 2026. Bezug: Der neue Wind-Partikel-Layer der Synoptik-Karte (`static/js/synoptic-wind.js`)
leitete den Wind geostrophisch aus dem MSLP-Grid ab. User-Befund 2026-07-17: Die angezeigte
Windrichtung über der Schweiz widerspricht dem (korrekten) Regionen-Höhenwind. Diese Recherche
validiert die Ursache und den Lösungsansatz (Deep-Research-Harness: 22 Quellen, 97 extrahierte
Claims, Top-25 adversarial verifiziert mit je 3 unabhängigen Prüfern — 24 bestätigt je 3-0,
1 verworfen 0-3).

---

## 1. Executive Summary

Der Befund ist kein Code-Bug (die Geostrophie-Mathematik in `synoptic-wind.js` wurde numerisch
verifiziert: zyklonale Zirkulation um Tiefs, antizyklonal um Hochs, über Atlantik/Flachland
±20–30° zum realen 850-hPa-Wind), sondern ein **fundamentales Physik-Problem des Ansatzes**:
Auf Meereshöhe reduzierter Bodendruck (MSLP) ist über hohem Gelände ein Rechenkonstrukt mit
dokumentierten Artefakten in **Betrag (bis Faktor 10) und Richtung** — am schlimmsten im Sommer
bei starker Aufheizung (Hitzetief über dem Alpenkörper, „Alpine Pumping", ~60–67 Tage/Jahr,
konzentriert in der Flugsaison). Empirisch gemessen (2026-07-13, Analysezeitpunkt des Grids):
MSLP-Geostrophie über der Schweiz ~132° (SE), realer 700-hPa-Wind ~250° (WSW) — fast
entgegengesetzt.

Die professionelle Standard-Lösung ist exakt der geplante Fix: **echten Druckflächen-Wind
anzeigen statt ihn aus Bodenisobaren abzuleiten**. Der stärkste Einzelbeleg: ECMWF publiziert
operationell genau die Kartenkombination, die wir bauen — MSLP-Isobaren + 850-hPa-Windfeld auf
einer Karte. Dass der Höhenwind dabei lokal Isobaren kreuzt, gilt nicht als verwirrend, sondern
ist etablierte Praxis. Für den Alpenraum und die Gleitschirm-Flughöhen (~500–4000 m) ist
**700 hPa (~3000 m)** eine gut begründete Niveau-Wahl (850 hPa liegt teils IM Gelände; DWD
bescheinigt der FL100-Karte hohe synoptische Aussagekraft; App-intern nutzt die
Wetterlage-Klassifikation bereits 700-hPa-Wind) — auch wenn ECMWF für sein Overlay 850 hPa und
als Steuerungsniveau 500 hPa nutzt: einen einheitlichen Kanon gibt es nicht.

Für die H/T-Zentren-Filterung ist der Literatur-Standard (IMILAST) **orographisches Masking**
(Zentren über >1000/1500 m Gelände verwerfen) plus Gradient-Schwellen — explizit gegen flache
Hitzetiefs. Wichtige Eigenbeobachtung: Unser reales Artefakt-Badge vom 17.07. lag bei
47.5N/5.0E (Burgund, <1000 m) — das grobe Grid (2.5°×3.5°) verschmiert das Alpen-Artefakt in
Nachbarzellen, wo eine Geländemaske es nicht erwischt. Der von uns entworfene
**Zirkulations-Check gegen das 700-hPa-Windfeld** (kein publizierter Standard, aber physikalisch
verwandt mit vertikalen Kohärenz-Checks) hat genau dieses Badge empirisch sauber gefiltert und
alle echten Zentren bestätigt. Empfehlung: beide Filter kombinieren.

---

## 2. Eigene empirische Validierung (Basis der Recherche-Fragen)

Alle Messungen vom 2026-07-17 gegen `data/synoptic_grid.json` (ECMWF IFS 0.25°, Lauf 13.07.)
und Open-Meteo-Punktabfragen (gleiches Modell):

**Die Geostrophie-Implementierung selbst ist korrekt:**

| Check | Ergebnis |
|---|---|
| Zirkulation um Badge-Tief 55N/40E (geostrophisch) | zyklonal (CCW) ✓ — N: Ost, S: West, E: Süd, W: Nordwind |
| Zirkulation um Badge-Hoch 60N/-2E (geostrophisch) | antizyklonal (CW) ✓ |
| Atlantik 50N/-20E vs. realer 850-hPa-Wind | aus 61–72° vs. real 44–80° — ±20–30°, brauchbar |

**Über der Schweiz versagt der Ansatz:**

| Zeitpunkt | MSLP-Geostrophie (46.8N/8.2E) | Real 700 hPa (ECMWF) |
|---|---|---|
| 13.07. 00 UTC | 25.7 km/h aus 132° (SE) | 15.8 km/h aus 222° (SW) |
| 13.07. 12 UTC | 15.9 km/h aus 150° (SSE) | 22.8 km/h aus 253° (WSW) |
| 17.07. 00 UTC | 9.7 km/h aus 176° (S) | 35.3 km/h aus 244° (WSW) |

Ursache im MSLP-Feld direkt sichtbar: 13.07. 12 UTC steigt der reduzierte Druck über den Alpen
von West (1012 hPa bei 1.5E) nach Ost (1020 hPa bei 15.5E) → geostrophisch Südwind. Das ist die
Hitzetief-/Reduktions-Signatur, nicht die Höhenströmung.

**Der echte 700-hPa-Wind zirkuliert korrekt um alle TIEFEN Badge-Zentren** (55N/40E-Tief:
72/255/217/30° an N/S/E/W-Punkten; 60N/-2E-Hoch antizyklonal) — tiefe Systeme reichen durch die
Troposphäre. **Ausnahme: das flache Tief-Badge 47.5N/5.0E vom 17.07.** (Gradient 2.6 hPa):
nördlich davon weht real Westwind (267°) statt des für ein echtes Tief nötigen Ostwinds → keine
Höhen-Zirkulation → Artefakt/flaches Thermiktief. Genau solche Badges muss die Zentren-Erkennung
künftig filtern.

---

## 3. Antworten auf die fünf Forschungsfragen

### 3.1 Ist MSLP-Geostrophie über Gebirge nachweislich unzuverlässig? — JA (high confidence)

**Mechanismus:** MSLP ist über erhöhtem Gelände keine Messgröße, sondern eine Extrapolation
P_MSL = P_stn·exp(z_stn/(a·T*v)) mit einer *erfundenen* virtuellen Temperatur für die nicht
existierende Luftsäule unter Grund ([Stull, Practical Meteorology Kap. 9](https://geo.libretexts.org/Bookshelves/Meteorology_and_Climate_Science/Practical_Meteorology_(Stull)/09%3A_Weather_Reports_and_Map_Analysis/9.00%3A_Sea-level_Pressure_Reduction)).
Warme Bedingungen → künstlich zu niedriger reduzierter Druck; sommerliche Aufheizung über den
Alpen erzeugt/verstärkt so fiktive Hitzetief-Signaturen ([NOAA TA 86-10](https://repository.library.noaa.gov/view/noaa/33735)).
Nuance: reale Hitzetiefs haben eine physikalische Komponente — der Artefakt-Anteil verzerrt sie,
erfindet sie nicht komplett.

**Größenordnung:** Dokumentiert sind spuriose Geostrophie-Maxima von 30–35 m/s ohne reales
Windmaximum entlang der Sierra Nevada (Pauley 1998, *Wea. Forecasting*: „No satisfactory
solution was found for regions with steep terrain gradients"); ~130 kt angezeigter
geostrophischer Wind bei real 10–20 kt im Lee der Rockies (**Faktor 10**, NOAA TA 86-10);
~10 mb Diskrepanz zwischen benachbarten Hochlagen-Stationen; die „Plateau-Korrektur" kann
**sogar die Richtung** der MSL-Gradienten ändern ([Mohr 2004, MWR](https://journals.ametsoc.org/view/journals/mwre/132/8/1520-0493_2004_132_1952_pwtmsl_2.0.co_2.xml)).
Ab ~300 m Stationshöhe gilt das Verfahren als zu unsicher für schwache Mesoskalen-Features.
Kritischste Situationen: Sommer, starke Aufheizung, große horizontale Temperaturgradienten.

**Alpen-Spezifik:** Das tageszeitliche flache Hitzetief über den Alpen („Alpine Pumping":
nachts thermisches Hoch, tags thermisches Tief bei Schönwetter) ist real, wiederkehrend und
häufig: ~60 Tage/Jahr im Modell, 67 beobachtet, Windumkehr an 77–81 % dieser Tage — konzentriert
in der Flugsaison ([Graf et al. 2016, Frontiers, DWD-Autoren](https://www.frontiersin.org/journals/earth-science/articles/10.3389/feart.2016.00005/full)).
Auch die Alpen-Forschung selbst meidet hydrostatische Reduktion für Druckvergleiche über
Höhendifferenzen (Perturbations-Methode, [ETH-Arbeit Bieri 2011](http://iacweb.ethz.ch/doc/publications/MTsbieri.pdf)).

*Caveat:* Die quantitativen Fallstudien stammen aus US-Gebirgen; Übertragung auf die Alpen ist
Analogie über gleiches Gelände-Regime (die Papers formulieren generisch für steiles Gelände).
**Nicht zitieren:** die Quantifizierung „450 km Verschiebung / 40 gpm zu tief" des
US-Sommer-Hitzetiefs — dieser Claim wurde adversarial verworfen (0-3).

### 3.2 Welches Niveau zeigen Profis als „übergeordnete Strömung"? (high/medium confidence)

Professionelle Produkte zeigen **immer Druckflächen-Wind, nie MSLP-abgeleiteten Wind**:

| Anbieter | Praxis |
|---|---|
| ECMWF | [MSLP + **850-hPa**-Wind kombiniert](https://charts.ecmwf.int/products/medium-mslp-wind850) (operationell, live verifiziert); [**500 hPa** als explizites „steering level"](https://charts.ecmwf.int/products/medium-z500-t850) |
| DWD Luftfahrt | [850/700/500 hPa (FL050/100/180)](https://www.dwd.de/DE/fachnutzer/luftfahrt/download/produkte/hoehenwetterkarten/hoehenwetterkarten.pdf?__blob=publicationFile&v=3) mit Isohypsen + Wind |
| NWS/NOAA | empfiehlt bei Gebirgs-MSLP-Problemen explizit Druckflächen-Analysen („not derived from reduction to sea level techniques") |

**Ein kanonisches Niveau existiert nicht** — 850, 700 und 500 hPa sind alle in operationellem
Gebrauch, je nach Zweck. **Für unseren Fall ist 700 hPa gut begründet** (medium confidence, da
Inferenz, keine wörtliche Institutions-Empfehlung):

- 850 hPa (~1500 m) liegt teils **im** Alpengelände; 700 hPa liegt über dem Großteil des
  Hauptkamms und mitten im Gleitschirm-Flughöhenband (500–4000 m).
- DWD: „Relativ viel Aussagekraft hat die Karte Geopotential und Feuchte FL 100 [700 hPa]" und
  „der Wind weht oberhalb der Bodenreibungsschicht immer parallel zu den Isohypsen. Dies ist
  bereits in FL 050 gegeben, **Abstriche von dieser Regel nur im höheren Bergland (Alpen)**."
- App-intern: `engine/synoptic_context.py` klassifiziert die Wetterlage bereits aus
  700-hPa-Wind (`wind_700`), die Bise-Erkennung ebenso — **interne Konsistenz** von Karte,
  Wetterlage-Callout und Regionen-Höhenwind schlägt den ECMWF-Präzedenzfall (850).

### 3.3 Ist die Kombi Bodendruck-Isobaren + Höhenwind auf EINER Karte okay? — JA (high confidence)

Direktbeleg: ECMWFs operationelles Europa-Produkt „Mean sea level pressure and 850 hPa wind
speed" überlagert exakt MSLP-Isobaren mit einem Druckflächen-Windfeld. Dass der Höhenwind lokal
Bodenisobaren kreuzt (baroklin, v. a. über den Alpen), hindert ECMWF nicht an der Kombination;
ein Beleg, dass dies als verwirrend/unzulässig gälte, wurde nicht gefunden. Der DWD trennt in
seiner Hobbymet-Suite Boden- und Höhenkarten — beide Konventionen koexistieren.

### 3.4 Wie filtert man flache thermische Tiefs aus der H/T-Erkennung? (high confidence)

Standard der Zyklonen-Tracking-Literatur ([IMILAST, Neu et al. 2013, BAMS](https://journals.ametsoc.org/view/journals/bams/94/4/bams-d-11-00154.1.xml)):

1. **Orographisches Masking:** 6 von 15 Vergleichs-Algorithmen eliminieren schlicht alle
   Zentren über Gelände >1000 m bzw. >1500 m MSL (u. a. Wernli/Schwierz 2006 mit >1500 m);
   die Projekt-Vergleiche schlossen Gebirge >1500 m ganz aus.
2. **Gradient-/Laplace-Schwellen und Mindest-Zugstrecke** — im IMILAST-Wortlaut explizit
   „to eliminate shallow heat lows".

Flache Tiefs (teils sommerliche Hitzetiefs) sind die am wenigsten robust detektierten Features
überhaupt — ihre Behandlung erklärt Zählspannen von ~6.000 bis ~21.000 NH-Winterzyklonen
zwischen Methoden.

**Unser Zirkulations-Check** (mittlere Tangentialkomponente des 700-hPa-Winds auf einem Ring um
den Kandidaten; Tief ohne zyklonale Höhen-Zirkulation → verworfen) ist **nicht als publizierter
Standard belegt** — Abwesenheit eines Belegs ist aber kein Beleg der Untauglichkeit; er ist
physikalisch verwandt mit vertikalen Kohärenz-Checks. Entscheidender Punkt aus der eigenen
Empirie (Abschnitt 2): Das reale Artefakt-Badge lag bei 47.5N/5.0E **unter 1000 m Gelände** —
Masking allein hätte es nicht gefiltert, der Zirkulations-Check schon. Auf dem groben Grid
verschmiert die Alpen-Signatur in Nachbarzellen. → **Beide Filter kombinieren.**

### 3.5 Einwände gegen Höhenwind-Partikel über Bodendruckkarte für Laien/Piloten? (low confidence)

Keine direkte UX-/Risikoforschung gefunden. Beobachtbare Profi-Praxis: das Windniveau wird
**immer explizit im Produkttitel/Legende benannt** (ECMWF: „850 hPa wind speed"; DWD: „FL 050
mit Temperatur und Wind"); windy.com u. a. lassen das Niveau wählen. Daraus als
Minimal-Standard: Partikel-Layer prominent labeln („Höhenwind 700 hPa / ~3000 m"), klar
abgegrenzt vom Bodenwind — für Piloten ist die Verwechslung startentscheidungs- und damit
sicherheitsrelevant.

---

## 4. Konsequenzen für das Design (→ `docs/pläne/PLAN_synoptik_hoehenwind.md`)

1. **Echten 700-hPa-Wind fetchen** (gleiche gechunkte Open-Meteo-Calls wie `pressure_msl`),
   Geostrophie-Ableitung im Partikel-Layer ersetzen.
2. **H/T-Zentren doppelt filtern:** orographisches Masking (Literatur-Standard) +
   Zirkulations-Check gegen das gefetchte 700-hPa-Feld (fängt versetzte Artefakte,
   empirisch validiert). Bestehende Gradient-Schwelle bleibt.
3. **Labeling:** Niveau explizit in Legende + Hint; Farbskala an reale 700-hPa-Verteilung
   kalibrieren (stärker als der gedämpfte Geostrophie-Output).
4. Bewusste, fachlich korrekte Rest-Inkonsistenz: Partikel kreuzen lokal Isobaren (baroklin).

## 5. Offene Fragen

- Was zeigen windy.com, meteoblue, wetter3, Met Office konkret als Default-„Überblickswind"?
  (Keine belastbaren Claims überlebt; direkter Produktvergleich steht aus.)
- Wie groß sind MSLP-Artefakte konkret in modernen Reanalysen/Modellen über den Alpen
  (ERA5/ICON/IFS-Modell-MSLP statt Stations-Reduktion)? Die US-Fallstudien sind älter und
  stationsbasiert; unsere Empirie (Abschnitt 2) zeigt aber, dass auch Modell-MSLP von ECMWF
  IFS die Richtungs-Artefakte trägt.
- Ist der Zirkulations-Check irgendwo publiziert/validiert, oder wäre ein Geopotential-
  Kohärenz-Check (Hoskins/Hodges-Familie) die belegbarere Alternative?
- UX-Forschung zur Verwechslungsgefahr Bodenwind vs. Höhenwind bei animierten Partikel-Layern.
