# PATTERNS — Höhenwind-Richtung vs. Stärke

## 05.11.2026 — erster Backtest (01.01.–04.11.2026, 307 Tage, 6 Stationen)

Zahlen: `AUTO_REPORT.md`. „Daneben“ = Richtungsfehler >45° (Pfeil zeigt in einen
Nachbarsektor oder weiter weg). Zufall wäre 75 % daneben.

**Kachel-Ebene (Vektor-Mittel über die Stationen, Test B):**

| Modellstärke | Pfeil daneben |
|---|---|
| unter 5 km/h | 48 % |
| 5–10 km/h | 29 % |
| 10–15 km/h | 13 % |
| ab 15 km/h | 0–19 % |

**Einzelpunkt (Test A):** Unter 5 km/h ist die Richtung reiner Zufall (73 %
daneben bei 75 % Zufall), 5–10 km/h 58 %, ab 15 km/h rund 30 %. Der Rest ist
Gelände (Gornergrat, Gütsch).

**Befund:** Die Schwelle **10 km/h** ist belegt. Darunter liegt der Pfeil in 1 von 3
(5–10 km/h) bis 1 von 2 Fällen (<5 km/h) falsch, darüber in höchstens 1 von 5.
Die Einigkeit der Stationen (R < 0.7 → rund 50 % daneben) wirkt ähnlich stark,
hat aber nur 21 Fälle. Als zweites Kriterium möglich, als alleiniges zu dünn.

## 05.11.2026 — Schwellen der Kachel-Labels (`kachel_schwellen.py`, `schwellen.json`)

171 Messpunkte (jeder 3. Spot, ICON-D2 700 hPa, 12:00), 308 Tage, Wahrheit 6 Gipfelstationen.
Richtung = Vektor-Mittel nur der Punkte mit Wind (≥10 km/h).

| Label | Regel | Tage | Befund |
|---|---|---|---|
| ↗ SW | sonst | 189 | Pfeil 19 % daneben |
| ↗ SW · teils schwach | ≥20 % der Punkte <10 km/h | 66 | „teils schwach“ stimmt in 91 % der Fälle (≥2 Gipfel schwach gemessen); Pfeil 27 % daneben |
| 〰 Richtung wechselt | Einigkeit R der Punkte mit Wind < 0,9 | 32 | ein Pfeil läge hier 41 % daneben (R 0,8–0,9: 42 %, ab 0,9: 21 %) |
| 〰 Kaum Wind · Richtung wechselt | <20 % der Punkte mit Wind | 21 | 62 % davon auch an den Gipfeln ruhig gemessen |

- R ist über ~170 dichte Punkte fast immer hoch (90 % der Tage > 0,9). Die frühere
  Stationsschwelle 0,7 griffe nur an 3 Tagen. Darum **0,9**.
- „Kaum Wind“ ist die schwächste Regel: Die Gipfel messen oft mehr Wind als das Modell
  auf 700 hPa. Höhere Schwellen zeigen das Label öfter, aber seltener richtig (40 % bei 60 %).
- Nachtrag (User-Entscheid): „teils schwach“ ab **30 %** — falsches „teils schwach“
  ist der gefährlichere Fehler; bei strenger Wahrheit (≥3 von 6 Gipfeln schwach)
  stimmt es dann in 76 % (10 %: 68 %, 20 %: 71 %).
- Einigkeit je Region statt je Punkt (`einigkeit_regionen.py`, Median der u/v je Region,
  jede Region eine Stimme, Ø 18 Regionen mit Wind): Schwelle **0,85** trennt am klarsten:
  11 Tage darunter, Pfeil dort 55 % daneben gegen 22 % darüber, in beiden Halbjahren
  erhöht (43 % / 75 %). Punkt-Einigkeit 0,9 trennt im Mittel ähnlich (41 % vs 21 %),
  schwankt aber zwischen den Halbjahren (27 % / 57 %). Richtung aus Punkten oder Regionen
  gleich gut (23 % / 24 % daneben). Weiter dünn (11 Tage) → im März nachmessen.
- Anteile je Region statt je Punkt (`anteile_regionen.py`): praktisch gleich gut.
  „Kaum Wind“ <20 %: Region 60 % richtig (Punkt 62 %); „teils schwach“ ≥30 %: Region
  76 % (Punkt 76 %), in beiden Halbjahren gleich. Kein Genauigkeitsgewinn — Regionen
  lohnen sich nur wegen der einheitlichen Logik (alle drei Regeln auf derselben Basis)
  und weil dicht besetzte Regionen nicht mehr Gewicht bekommen.
- „Kaum Wind“ verbessern (`kaum_wind.py`): andere Regeln (Anteil <30 %, stärkste
  Region <15/<20 km/h, Mittel <10 km/h) sind alle schlechter als Anteil <20 %. Mit
  breiterer Wahrheit (15 exponierte Gipfel ≥2100 m inkl. Matro/Tessin, Diablerets,
  Titlis, Eggishorn; ruhig = höchstens 20 % messen ≥10 km/h) stimmt „Kaum Wind“ in
  **75 %** (83 % / 62 % je Halbjahr) statt 60 %: Die Schwäche lag zum Teil an den nur
  6 Vergleichsgipfeln, nicht an der Regel. → Regel bleibt, künftig mit 15 Gipfeln messen.
- Grenzen: 6 alpine Gipfel als Wahrheit gegen Punkte über der ganzen Schweiz (inkl.
  Jura/Mittelland); Stichprobe statt aller Spots (Kontingent der freien API).

## 05.11.2026 — Gegenprobe mit Wetterballonen (`radiosonde.py`, `RADIOSONDE_REPORT.md`)

Wahrheit: Radiosonden 12 UTC, 700 hPa (IGRA2): Payerne, Stuttgart, München, Novara-Cameri;
305 Termine. Der Ballon misst die freie Luft — genau das, was die Kachel zeigt.

**Kernbefund: Die Gipfel waren der falsche Massstab für die Richtung.** ICON-D2 an den
Ballon-Orten: 5–10 km/h 18 % daneben, 10–15 km/h 8 %, ab 15 km/h 1–2 %, unter 5 km/h 47 %
(Gipfel: 58 % / 45 % / 30 %). Stärke-Bias ICON−Ballon −1 km/h. Die Gipfel-„Fehler“ sind
überwiegend Hang-/Thermikwind am Messort (Literatur: Gipfel bei schwacher Grossströmung
von der freien Luft entkoppelt).

| Kachel | Ballon: Pfeil daneben |
|---|---|
| heutige Kachel, Mittel 0–5 km/h | 38 % |
| heutige Kachel, 5–10 km/h | 30 % |
| heutige Kachel, 10–15 km/h | 13 % |
| heutige Kachel, ab 15 km/h | 2 % |
| neu „↗ SW“ | 2 % (206 Tage) |
| neu „↗ SW · teils schwach“ | 27 % (52 Tage) |
| neu „Richtung wechselt“ (Pfeil wäre) | 19 % (27 Tage) |

- 10-km/h-Grenze auch mit Ballonen bestätigt.
- ECMWF als Zweitmeinung bringt nichts: ICON-D2 und ECMWF liegen nur an 1 von 257
  Pfeil-Tagen > 45° auseinander.
- „Kaum Wind“ / „teils schwach“ sind mit Ballonen NICHT prüfbar: nur Payerne liegt in der
  Schweiz, die anderen drei ausserhalb der Alpen (dort oft mehr Wind). Payerne war an
  9 von 15 „Kaum Wind“-Terminen unter 10 km/h, ICON an den Ballon-Orten passte durchwegs.

## 05.11.2026 — Backtest aller fünf Anzeigen (`kachel_backtest.py`, `kachel_backtest.json`)

305 Ballon-Termine (12 UTC), Labels je Region zur selben Stunde, Regel-Reihenfolge wie im Skript.

| Anzeige | Auslöser | Anteil | Backtest |
|---|---|---|---|
| ↗ SW | sonst | 68 % | Richtung stimmt 98 % (Ballone) |
| ↗ SW · teils schwach | ≥30 % Regionen <10 km/h | 17 % | Richtung 73 %; „teils schwach“ 94 % (15 Gipfel) |
| 〰 Richtung wechselt | Einigkeit Regionen <0,85 | 9 % | Ballone ohne klare Richtung nur 56 %; ein Pfeil wäre 78 % richtig gewesen |
| 〰 Richtung wechselt · stellenweise stärker | <20 % Regionen mit Wind, aber nicht ganztags schwach | 5 % | Ballone ohne klare Richtung 40 %, irgendwo ≥15 km/h 67 % |
| 〰 Schwache Höhenströmung | alle Regionen 06–17 Uhr <15 km/h | 1 % (2 Tage) | nicht prüfbar (1 von 2) |

- „Richtung wechselt“ (Einigkeit) ist gegen Ballone schlechter als der Pfeil, den es ersetzt
  (56 % vs. 78 %) → streichen; die Gipfel-Messung, auf der 0,85 beruhte, war der falsche Massstab.
- 4 Ballone (3 ausserhalb der Alpen) erkennen „keine klare Richtung“ nur grob — die beiden
  wechselt-Labels sind damit nur grob prüfbar.

## 05.11.2026 — Synoptik-Karte gegen Ballone (`karte_vs_ballon.py`)

Nachbau der Karte: ECMWF 700 hPa auf dem Raster 2,5° × 3,5°, u/v bilinear. Gegen Radiosonden 12 UTC.

| Kartenstärke | Karte daneben | ECMWF direkt am Ballon-Ort |
|---|---|---|
| 0–5 km/h | 65 % | 29 % |
| 5–10 km/h | 33 % | 20 % |
| 10–15 km/h | 15 % | 9 % |
| 15–20 km/h | 14 % | 1 % |
| 20–25 km/h | 6 % | 1 % |
| ab 25 km/h | 0–3 % | 0–2 % |
| gesamt | 10 % | 4 % |

- Das grobe Raster verdoppelt den Fehler; bis 20 km/h deutlich schlechter als das Modell selbst.
- 05.11. (Lauf vom Abend, 12 Uhr): Karte über der Schweiz 13–31 km/h aus S (166–183°) —
  kein Nord-/Westwind. Das vom User gesehene „Nordwind“ ist damit nicht nachgestellt.

## Umgesetzt 05.11.2026 (User-Entscheid: zwei Fälle)

- **↗ Sektor**: Richtung je Region (`decide_flow_tile`), nur Regionen ≥ 10 km/h, 12 Uhr —
  gegen Ballone 92 % richtig (alle Tage ohne Schwachwind-Fall).
- **〰 Schwacher Wind · Richtung unklar**: < 20 % der Regionen mit Wind (~5 % der Tage);
  ein Pfeil läge dort nur in 57 % richtig. „Schwach“ hält: Modell < 10 km/h → Ballon < 15 km/h in 90 %.
- Nicht umgesetzt: „teils schwach“, „Richtung wechselt“ (Einigkeit), Gebietstabelle, Karten-Raster.
- Föhn-Block: bei 0 von 4 Zeichen nur noch die Druckzeile.
- Nachmessen: März 2027 mit `kachel_backtest.py` gegen Radiosonden.
