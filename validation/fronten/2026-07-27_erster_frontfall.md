# 2026-07-27 — Erster Frontfall: Kaltfront streift die Nordschweiz

**Lauf:** 2026072600 (00 UTC) · **Aussage-Stand:** 27.07. · **Befunde:**
`F-002`, `F-003` · **Urteil:** `unklar`

Erster echter Frontfall, seit die Ableitung existiert. Er kam ausschliesslich
dadurch zustande, dass die Handanalyse als früher Stützpunkt eingebaut wurde
(Plan §1i) — mit `--ohne-analyse` meldet derselbe Lauf **nichts**.

## Was wir gesagt haben

```
alpennordhang  Kaltfront  streift  Mon 27.07 02:58 MESZ ±6 h   1/327   80 km  ~Rand
```

## Was dafür spricht

| Weg | Befund |
|---|---|
| Rohabstände | am nördlichsten Spot (47.76 °N) Kaltfront um 00 UTC **104 km** entfernt, um 12 UTC **757 km** — in der Nacht abgezogen |
| Kartenbild | Analyse 00 UTC: Kaltfront von der Ostsee südwestwärts über Deutschland, knapp nördlich der Schweiz vorbei |
| DWD-Klartext `SXDL31` 08 UTC | Langwellentrog zieht ostwärts nach Polen, rückseitig subpolare Luft; Schauer „von der Deutschen Bucht bis zum Erzgebirge" — also im Norden, nicht bei uns |

## Warum das Urteil trotzdem `unklar` lautet

**Zirkularität.** Die 00-UTC-Handanalyse war unser *Stützpunkt* — sie kann den
daraus abgeleiteten Durchgang nicht bestätigen. Eine spätere, unabhängige
Analyse (12 UTC) lag zum Zeitpunkt der Auswertung nicht im Archiv, weil das
Archiv erst heute angelegt wurde und Open Data nur die jeweils aktuelle farbige
Karte führt.

Die drei Stützen oben machen den Fall **plausibel**, nicht verifiziert. Das ist
genau der Unterschied, den `verdict` festhalten soll: Wer die Zeile später
auswertet, darf sie nicht als Treffer zählen.

**Konsequenz für den Betrieb:** Zu beiden Analyseterminen abholen (00 und
12 UTC), sonst fehlt für jeden Fall die unabhängige Gegenprobe. Damit ist die
Zirkularität ab dem nächsten Fall vermeidbar.

## Was der Fall gebracht hat

Zwei Ausgabemängel wurden dadurch überhaupt sichtbar und sind behoben:

- **`F-002`** — 1 von 327 Spots wurde als Zonenaussage geführt. Ohne die neue
  Unterscheidung `streift` / `quert` (Schwelle 10 %) wäre daraus im Text ein
  „Kaltfrontdurchgang am Alpennordhang" geworden.
- **`F-003`** — der interpolierte Zeitpunkt lag 58 Minuten nach dem ersten
  Stützpunkt, also am Rand des Intervalls. Der wahre Durchgang kann davor
  gelegen haben. Solche Werte tragen jetzt die Markierung `~Rand`.

Ein Streifschuss am Zonenrand hat damit zwei Fehler aufgedeckt, die bei einem
grossen Frontdurchgang unbemerkt durchgelaufen wären — dort hätten viele Spots
angeschlagen und die Zahlen hätten überzeugend ausgesehen.
