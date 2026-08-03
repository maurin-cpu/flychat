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

**Status:** `gefixt 31.07.` · **Beobachtet:** Schadensfall im Lauf 2026072700

Das Verfahren verfolgte den „nächsten Punkt einer Frontlinie gleichen Typs"
**über alle Linien gemeinsam**. Auf den Karten liegen aber 13–19 Abschnitte
gleichzeitig, und nichts stellte sicher, dass es dieselbe Front ist. Löst sich
die nähere auf, rückt die nächste nach — und der Sprung wird als Verlagerung
gelesen.

**Der Schadensfall.** Lauf 27.07. 00 UTC, Punkt Alpennordhang. Die
Handanalyse 12 UTC zeigt die nächste Kaltfront **440 km südöstlich**
(13.5 O / 45.9 N) — der Durchgang am Morgen war vorbei, die Front zog ab. Auf
der Folgekarte (+36 h) ist die nächste Kaltfront eine **völlig andere**, 1652 km
**nordwestlich** über dem Atlantik (−8.4 O / 56.5 N). Das Verfahren verband
beide zu einer Bewegung: 2048 km in 24 h = **85 km/h**, knapp unter der
90-km/h-Schranke, und meldete `Kaltfront quert alpennordhang 27.07 16:03 UTC,
34/327 Spots` plus `graubuenden_engadin streift, 2/76`. Beide Fronten haben die
Schweiz in diesem Fenster nie berührt.

Das Geschwindigkeitsgate half nicht und konnte nicht helfen: bei 12 h Stützweite
erlaubt es einen Sprung von **1080 km** — darin liegt halb Europa. Es siebt das
Absurde, nicht das Falsche.

**Der Fix.** `passages_for_point()` verfolgt jetzt **je Linie** statt global.
Zu jeder Linie der Folgekarte wird die Vorgängerlinie mit dem nächstgelegenen
Aufpunkt gesucht: steht dort bereits eine Linie, wo diese steht, ist **sie** die
Fortsetzung — nicht eine weit entfernte, die sich womöglich aufgelöst hat. Eine
aufgelöste Front hat damit keinen Nachfolger und erzeugt nichts mehr. Nebenbei
wird jede Linie einzeln bewertet statt nur die global nächste; ein echter
Durchgang kann so nicht mehr von einer näheren, aber unbeteiligten Linie
verdeckt werden.

**Selbsttest** (`--selftest`, Fälle 5–7, gebaut innerhalb des erlaubten
Tempobands — ein absurder Sprung würde nur bestätigen, was Fall 3 zeigt):

- **5** Zwei Fronten gleichen Typs, die nähere löst sich auf → kein Durchgang.
  Vor dem Fix gemeldet, **ununterscheidbar** von Fall 1: gleiche Zeit
  (17:54 UTC), gleicher Querabstand (0 km). Nichts in der Ausgabe hätte den
  Unterschied verraten.
- **6** Front wechselt den Typ entlang der Linie, eine fernere gleichen Typs
  bleibt stehen → kein Phantom-Durchgang. Vor dem Fix gemeldet.
- **7** Endpunkt-Rückzug zwischen zwei Karten (Südende 44 → 48 N) verkippt die
  Zugrichtung → Zeit muss bei der Geometrie bleiben. War **schon vorher in
  Ordnung** (Abweichung 29 min); die Endpunkt-Sorge aus §1h Befund 2 hat sich
  nicht bestätigt.

**Was offen bleibt.** Die Zuordnung geht über die Lage des Aufpunkts, nicht über
Länge und Form der Linie. Zwei Fronten, die sich *tatsächlich* nahekommen,
können weiterhin verwechselt werden — das braucht echte Frontverfolgung und ist
erst nötig, wenn ein Fall es zeigt. Ebenso ungeprüft bleibt die Gegenrichtung:
wie oft der strengere Zuordnungstest jetzt eine **echte** Front verwirft.

**Altlast in den Daten.** `observations.csv` enthält die vor dem Fix erzeugten
Phantom-Zeilen (27.07 16:03 UTC alpennordhang, 15:50 UTC graubuenden_engadin).
Sie werden nicht automatisch überschrieben, weil die Uhrzeit Teil des Schlüssels
ist. Im `AUTO_REPORT` standen sie bereits als härtester Jitter markiert —
„nicht eine verschobene Zeit, sondern eine verschwundene Front", in 4 von 7
Läufen gar nicht vorhanden. Rückblickend war das der Vorbote dieses Befunds.

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
