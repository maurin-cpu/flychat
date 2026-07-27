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
