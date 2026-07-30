# Auto-Validierung — erzeugt, nicht von Hand gepflegt

Stand 2026-07-30 18:04 UTC, erzeugt von `scripts/validate_fronten.py`. Befunde gehoeren nach `PATTERNS.md`, Urteile duerfen in `observations.csv` von Hand ueberschrieben werden — dieser Bericht wird bei jedem Lauf neu geschrieben.

## Bestand

- 11 Zeile(n) in `observations.csv`, davon 10 automatisch beurteilt
- Analyse-Abdeckung: 27.07 00:00 – 27.07 12:00 UTC
- Ist-Ereignisse in der Analyse-Kette: 2
- neu beurteilt in diesem Lauf: 0, neue verpasste Fronten: 0
- **0 Zeile(n) warten auf Analysen** — leer heisst NICHT GEPRUEFT, nicht "kein Befund"

## Urteile

| Urteil | Zeilen |
|---|---|
| `getroffen` | 9 |
| `verpasst` | 1 |
| `zu_frueh` | 1 |

## Systematik (Vorzeichen von `delta_h`)

- n = 10, Median -10.5 h, Spanne -12.4 … +2.9 h
- Lesart: wir sagen zu SPAET an (positiv = die Front kam spaeter als angesagt)

Eine systematische Schieflage waere korrigierbar, Rauschen nicht. Ab n < 10 ist beides nicht unterscheidbar — die Zahl steht hier als Richtungshinweis, nicht als Beleg.

## Lauf-Jitter (braucht keine Ist-Lage)

| Zone | Typ | angesagt fuer | Spanne | Laeufe | fehlt in |
|---|---|---|---|---|---|
| alpennordhang | kalt | 27.07 00:58 UTC | 0.0 h | 4 | — |
| alpennordhang | kalt | 27.07 16:03 UTC | 0.0 h | 3 | Stand 20260727, Stand 20260728, Stand 20260729, Stand 20260730 |
| graubuenden_engadin | kalt | 27.07 15:50 UTC | 0.0 h | 3 | Stand 20260727, Stand 20260728, Stand 20260729, Stand 20260730 |

`fehlt in` = Laeufe, die den Zeitpunkt abgedeckt haben, aber keine Aussage dazu machten. Das ist der haertere Jitter: nicht eine verschobene Zeit, sondern eine verschwundene Front.

## Verpasste Fronten (Gegenlauf ueber die Analysen)

- graubuenden_engadin / kalt — Ist-Durchgang 2026-07-27T05:17+00:00

## Die 0-Front-Regel

Frontfreie Tage erzeugen keine Zeile. Jede Quote hier gilt nur fuer Tage, an denen wir etwas behauptet haben; wie oft wir eine Front uebersehen, beantwortet allein der Gegenlauf oben.
