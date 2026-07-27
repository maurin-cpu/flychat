# Fronten-Validierung — Wiederkehrende Muster

Akkumulierter Befundtracker der Frontenableitung. Eigener Namensraum `F-0xx`,
damit keine Verwechslung mit den XContest-Befunden `I-0xx` entsteht.

**Status-Werte**: `offen` / `in-untersuchung` / `gefixt` / `nicht-reproduzierbar`

Datenbasis ab **2026-07-27**. Vorher existierte keine Frontenableitung.

---

## F-001 — Phantom-Durchgänge durch entfernte Fronten

**Status:** `gefixt` (2026-07-27) · **Beobachtet:** 1 Lauf (2026072700)

Die erste Fassung der Zeitachse meldete Kaltfront-Durchgänge für **alle vier
Zonen** — Mittwochvormittag, mit Zonenfenstern, durchweg plausibel aussehend.
Die nächste Kaltfront war zu **jedem** der fünf Termine zwischen **501 und
1707 km** entfernt. Es gab keinen Durchgang.

**Ursache:** Der Durchgang wurde allein am Vorzeichenwechsel der Längsprojektion
erkannt (Front wechselt von „vor uns" nach „hinter uns", gemessen am nächsten
Punkt der Frontlinie). Bei einer langen, entfernten Front wandert dieser Punkt
aber *die Linie entlang*, während sie zieht — das Vorzeichen kippt, ohne dass
die Front näher kommt.

**Behoben durch** den Querabstand im Moment des Durchgangs (`MAX_LATERAL_KM`
= 100). Bei reiner Verlagerung bleibt er konstant, während die Längskomponente
durch null geht — er ist damit genau der Abstand, den die Front beim Passieren
seitlich noch hat. Regression als Fall 3 in `--selftest` festgenagelt.

**Lehre, allgemein:** Ein Verfahren, das nur „nichts gefunden" liefern kann,
ist nicht geprüft — und eines, das plausible Zahlen liefert, ist es auch nicht.
Erst die Gegenprobe an einer unabhängigen Grösse (hier: der schlichte Abstand)
trennt das eine vom anderen.

---

## F-002 — Streifschuss am Zonenrand wurde als Zonenaussage geführt

**Status:** `gefixt` (2026-07-27) · **Beobachtet:** 1 Fall (Lauf 2026072600)

Der erste echte Frontfall (Kaltfront in der Nacht auf 27.07., knapp nördlich
der Schweiz) betraf **1 von 327** Spots des Alpennordhangs — den nördlichsten,
bei 47.76 °N. Die Ausgabe führte ihn als Zonenzeile. Unverändert wäre daraus im
Text ein „Kaltfrontdurchgang am Alpennordhang" geworden.

**Behoben durch** `MIN_ZONE_SHARE` = 10 %: darunter heisst es `streift`, darüber
`quert`. Die Schwelle ist gesetzt, nicht kalibriert — steht auf der Prüfliste,
sobald genug Fälle vorliegen.

---

## F-003 — Zeitpunkte am Rand des Stützintervalls sind Randwerte

**Status:** `gefixt` (2026-07-27, Markierung) · **Beobachtet:** 1 Fall

Derselbe Fall interpolierte den Durchgang auf 00:58 UTC — 58 Minuten nach dem
ersten Stützpunkt. Das bedeutet: die Front war zum Stützzeitpunkt praktisch
schon am Ort, der wahre Durchgang kann **davor** gelegen haben, also vor dem
ersten Stützpunkt und damit ausserhalb des Betrachtungsfensters.

Solche Werte tragen jetzt die Markierung `~Rand` (`randwert` in
`observations.csv`) und dürfen nicht als Zeitangabe verwendet werden. Sie sagen
nur: „ungefähr zu Beginn des Fensters oder früher".

---

## F-004 — Front-Identität zwischen zwei Karten ist nicht sichergestellt

**Status:** `offen` · **Beobachtet:** noch kein Schadensfall

Das Verfahren verfolgt den „nächsten Punkt einer Frontlinie gleichen Typs"
zwischen zwei Terminen. Auf den Karten liegen aber **13–19 Abschnitte
gleichzeitig**. Nichts stellt sicher, dass es dieselbe Front ist. Bekannte
ungeprüfte Fälle:

- Front A löst sich auf, Front B nähert sich von anderer Seite → scheinbare
  Bewegung, die den Punkt überstreicht. Das Geschwindigkeitsgate (3–90 km/h)
  hilft nur zufällig: 600 km in 12 h = 50 km/h und passiert es.
- Stationärfronten wechseln den Typ **entlang** der Linie (rot/blau
  alternierend). Dieselbe Front kann an unserer Länge auf Karte 1 `kalt`, auf
  Karte 2 `warm` heissen → Durchgang wird für beide Typen verpasst.
- Linien-Endpunkte: die Projektion klemmt auf das Segmentende, die Zerlegung
  längs/quer wird dort systematisch schief.

Nächster Schritt: `--selftest` um diese drei Fälle erweitern, danach entscheiden,
ob eine echte Frontverfolgung (Zuordnung über Länge, Form und Lage) nötig ist.

---

## F-005 — Zeitliche Genauigkeit ist quellenbegrenzt, Systematik unbekannt

**Status:** `offen` · **braucht Fälle**

Stützweite 12 h (+36/+48/+60), danach 24 h. Die lineare Interpolation
unterstellt gleichförmige Verlagerung. Ob unsere Zeiten **systematisch** zu früh
liegen — Verdacht: Fronten bremsen am Alpenkamm — ist unbekannt und nur an
echten Durchgängen messbar. Kernzahl dafür ist `delta_h` in `observations.csv`.

Solange die Systematik unbekannt ist, gilt für die Ausgabe: nie eine Uhrzeit,
immer ein Tagesfenster (Plan §6, Regel 1 und 2).

**Erste Messung (27.07., n = 1):** `delta_h` = **+2.7 h** aus der Auto-Validierung
(Ist-Durchgang 03:39 UTC gegen Ansage 00:58 UTC) — von Hand aus Abstand und
Tempo gerechnet waren es +2.9 h. Zwei Wege, dasselbe Vorzeichen: **zu früh
angesagt**, wie vermutet. Ein Fall belegt nichts, aber die Richtung stimmt mit
der Bremshypothese überein.

---

## F-006 — Ausdehnung unterschätzt: Streifschuss angesagt, Zonendurchgang eingetreten

**Status:** `offen` · **Beobachtet:** 1 Fall (27.07.2026), erster Fund des
Gegenlaufs

Für die Nacht auf den 27.07. sagten wir am Alpennordhang einen **Streifschuss**
an: 1 von 327 Spots, also ausdrücklich keine Zonenaussage (F-002). Die Kette der
Handanalysen (00 → 12 UTC) zeigt für dieselbe Kaltfront:

| | Ansage | Ist-Lage |
|---|---|---|
| Alpennordhang | `streift`, 1/327 Spots, 00:58 UTC | `quert`, **92/327** Spots, 03:39 UTC |
| Graubünden/Engadin | *keine Aussage* | `quert`, **72/76** Spots, 05:17 UTC |

Der Zeitfehler ist mit +2.7 h klein (F-005). Der **Ausdehnungsfehler** ist es
nicht: aus einem Randkontakt wurde ein Durchgang durch zwei Zonen. Genau diese
Fehlerart würde der Vorhersage-Seite allein nie auffallen — sie ist der Grund
für den Gegenlauf über die Analysen (`verdict = verpasst`).

**Was das noch nicht ist.** Ein Beleg: n = 1. Die Ist-Kette besteht aus **einer
einzigen** Kartenpaarung (00/12 UTC), die Front-Identität dazwischen ist
ungeprüft (F-004), und die Ist-Seite benutzt dasselbe geometrische Verfahren wie
die Vorhersage — ein Methodenfehler beträfe beide Seiten, nur die Eingangsdaten
sind unabhängig. Der Verdacht ist trotzdem konkret genug, um ihn zu benennen:
**die Vorhersagekarten haben 12 h Stützweite, und eine Front, die zwischen zwei
Terminen durchzieht, hinterlässt auf ihnen nur einen Randkontakt.** Wäre das die
Ursache, wären Streifschüsse systematisch untertrieben — prüfbar an den nächsten
Fällen, sobald das Archiv sie liefert.
