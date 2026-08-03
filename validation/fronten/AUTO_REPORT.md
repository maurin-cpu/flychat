# Auto-Validierung — erzeugt, nicht von Hand gepflegt

Stand 2026-08-02 18:10 UTC, erzeugt von `scripts/validate_fronten.py`. Befunde gehoeren nach `PATTERNS.md`, Handurteile nach `handurteile.csv` — die werden bei jedem Lauf ueber die Maschinenzeilen gelegt. `observations.csv` und dieser Bericht gehoeren der Maschine und werden neu geschrieben.

## Bestand

- **11 unabhaengige Beobachtung(en)** aus 18 Zeile(n) in `observations.csv` (11 automatisch beurteilt). Mehrere Zeilen zum selben Lauf und Ereignis sind Wiederholungen derselben Messung; Quoten und Median unten zaehlen sie einmal.
- Analyse-Abdeckung: 27.07 00:00 – 27.07 12:00 UTC, 29.07 12:00 – 02.08 12:00 UTC
- Ist-Ereignisse in der Analyse-Kette: 2
- neu beurteilt in diesem Lauf: 0, neue verpasste Fronten: 0
- **6 Zeile(n) warten auf Analysen** — leer heisst NICHT GEPRUEFT, nicht "kein Befund"

## Urteile

| Urteil | Beobachtungen |
|---|---|
| `getroffen` | 2 |
| `keine_front` | 1 |
| `verpasst` | 1 |
| `zu_frueh` | 1 |

## Systematik (Vorzeichen von `delta_h`)

- n = 3 Beobachtung(en) aus 2 Frontdurchgang/-gaengen, Median -10.5 h, Spanne -12.4 … +2.9 h
- Lesart: wir sagen zu SPAET an (positiv = die Front kam spaeter als angesagt)

Eine systematische Schieflage waere korrigierbar, Rauschen nicht. Unterscheidbar wird beides erst ab rund 10 FRONTDURCHGAENGEN — mehrere Laeufe zum selben Durchgang erhoehen n, aber nicht die Zahl der Wetterlagen. Die Zahl steht hier als Richtungshinweis, nicht als Beleg.

## Lauf-Jitter (braucht keine Ist-Lage)

| Zone | Typ | angesagt fuer | Spanne | Schnappschuesse | fehlt in (Lauf/Stand) |
|---|---|---|---|---|---|
| alpennordhang | kalt | 27.07 00:58 UTC | 0.0 h | 4 | — |
| alpennordhang | kalt | 27.07 16:03 UTC | 0.0 h | 3 | 20260726/20260727, 20260726/20260728, 20260726/20260729, 20260726/20260730 |
| alpennordhang | kalt | 06.08 10:48 UTC | 0.0 h | 1 | — |
| alpennordhang | trog | 30.07 12:26 UTC | 0.0 h | 1 | 20260727/20260727, 20260727/20260728, 20260727/20260729, 20260727/20260730, 20260728/20260730, 20260730/20260730 |
| alpennordhang | warm | 02.08 07:03 UTC | 0.0 h | 1 | 20260729/20260730, 20260730/20260730 |
| alpennordhang | warm | 06.08 11:37 UTC | 0.0 h | 1 | — |
| graubuenden_engadin | kalt | 27.07 15:50 UTC | 0.0 h | 3 | 20260726/20260727, 20260726/20260728, 20260726/20260729, 20260726/20260730 |
| graubuenden_engadin | warm | 02.08 11:02 UTC | 0.0 h | 1 | 20260729/20260730, 20260730/20260730 |
| tessin | warm | 02.08 11:34 UTC | 0.0 h | 1 | 20260729/20260730, 20260730/20260730 |
| wallis | warm | 02.08 09:01 UTC | 0.0 h | 1 | 20260729/20260730, 20260730/20260730 |

`fehlt in` = Laeufe, die den Zeitpunkt abgedeckt haben, aber keine Aussage dazu machten. Das ist der haertere Jitter: nicht eine verschobene Zeit, sondern eine verschwundene Front.

## Verpasste Fronten (Gegenlauf ueber die Analysen)

- graubuenden_engadin / kalt — Ist-Durchgang 2026-07-27T05:17+00:00

## Die 0-Front-Regel

Frontfreie Tage erzeugen keine Zeile. Jede Quote hier gilt nur fuer Tage, an denen wir etwas behauptet haben; wie oft wir eine Front uebersehen, beantwortet allein der Gegenlauf oben.
