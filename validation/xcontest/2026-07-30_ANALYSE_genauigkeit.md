# Genauigkeit Forecast vs. XContest — Spot- und Region-Ebene getrennt

> **Hinweis (10.08.2026):** Dieses Protokoll nennt die Regionsnamen im Stand
> **vor** der Umbenennung. Zuordnung alt→neu:
> `data/region_renames_2026-08.csv` · `docs/REGIONEN_UMBENENNUNG_2026-08.md`.
> Der Text bleibt bewusst unverändert — Befunde rückwirkend umzuschreiben
> würde sie fälschen.

**Stand**: 2026-07-30
**Werkzeug**: `scripts/xc_accuracy.py` (schreibt nichts, deterministisch wiederholbar)
**Basis**: 18 auswertbare Tage (27.05.–20.06.), 676 Spot-Tage, 256 Region-Tage
**Erst möglich durch**: `spot_aliases.csv` (Region-Zuordnung auch ohne DB-Spot) und
den `our_status`-Fix im Aggregator (s. u.)

---

## Methodik — und was sie bewusst nicht kann

Gemessen wird **einseitig**. XContest zeigt nur die guten Flüge: viele Flüge ab
Spot X beweisen, dass X fliegbar war. **Keine** Flüge ab X beweisen nichts — das
kann Wetter sein, aber genauso Wochentag, Pilotendichte oder Topografie.

Messbar sind damit nur die Fehler in *einer* Richtung:

| Metrik | Definition |
|---|---|
| Harter Fehlalarm | wir sagten `not_safe`, real wurde ab dem Spot geflogen |
| Unterschätzung | Flugeinschätzung ≤2, real ≥100 km |
| Treffer | Flugeinschätzung ≥4, real ≥100 km |

**Nicht messbar: Überschätzung.** Ein Tag ohne XContest-Flüge ist kein Beleg für
schlechte Bedingungen. Wer die Gegenrichtung will, braucht eine Nicht-Flug-Quelle
(Vereins-/Schulbetrieb, Livetrack24-Starts o. ä.) — XContest ist sie nicht.

**Datenbasis-Grenzen**: 26 Tage haben Rohdaten, 6 davon keinen Snapshot, 2 einen
Snapshot ohne `analysis`-Block. **Juli fehlt komplett** — alle Archivtage ab 01.07.
haben leere `spots[*].analysis` (I-015), die 49-Tage-Starkflugtabelle liegt zudem
nicht im Tages-TSV-Format vor.

---

## Befund 1 — die Region-Ebene ist deutlich besser kalibriert als die Spot-Ebene

Anteil `not_safe` an Tagen, an denen dort real geflogen wurde:

| Ebene | alle Flüge | nur Flüge ≥60 km |
|---|---|---|
| **Spot** | 32.7 % (221/676) | 17.7 % (23/130) |
| **Region** | 23.4 % (60/256) | **10.7 % (8/75)** |

An bewiesen starken Tagen sagt die Region-Ebene zu 64 % `safe`, die Spot-Ebene nur
zu 26 %. Der Aufschlag entsteht also im Spot-Layer, nicht im Regions-Layer — das
passt zu I-014 (safe Region + not_safe Spots in Masse).

## Befund 2 — die Flugeinschätzung funktioniert, der Sicherheits-Status nicht

Spot-Tage nach Flugeinschätzung (nur Tage mit validem `experience_rating`, n=496):

| rating | n | median km | max km | davon ≥100 km |
|---|---|---|---|---|
| 1 | 93 | 16.2 | 214.2 | 3 |
| 2 | 24 | 19.3 | 158.3 | 1 |
| 3 | 70 | 17.2 | 201.1 | 7 |
| 4 | 163 | 22.5 | 336.0 | 20 |
| 5 | 146 | 30.4 | 366.4 | 25 |

Bei real ≥100 km: **80.4 % Treffer** (rating ≥4), nur **7.1 % Unterschätzung**
(rating ≤2). Die Flugeinschätzung trägt also — die Medianwerte steigen monoton,
und die grossen Tage landen ganz überwiegend in 4/5.

Auf Region-Ebene dasselbe Bild (n=233): median 20.8 km bei rating 1 gegen 41.8 km
bei rating 5.

Der Defekt sitzt woanders: **ein Drittel aller geflogenen Spot-Tage stand auf
`not_safe`** — der Status widerspricht der Flugeinschätzung, die auf denselben
Daten funktioniert.

## Befund 3 — die Fehlalarme haben zwei Hauptquellen

Primärer `no_go`-Grund der 221 Fehlalarme:

| Grund | Anteil | bei Flügen ≥60 km (n=23) |
|---|---|---|
| Start-Fenster ("nur Xh sauber, kein Block") | 33.0 % | 21.7 % |
| Windrichtung ("ganztägig ausserhalb Sektor") | 29.4 % | **43.5 %** |
| Gewitter | 16.7 % | 13.0 % |
| Höhenwind | 10.0 % + 2.3 % | 4.3 % |
| Böen | 4.5 % + 1.4 % | 8.7 % |

Je stärker der Flug, desto dominanter die **Windrichtung** — das ist genau der
Sektor-Komplex aus I-006/I-009 (zu enge Sektoren, fehlende Startvarianten am
anderen Hang). Die härtesten Einzelfälle:

| Tag | Spot | real | unser no_go |
|---|---|---|---|
| 28.05. | Niesen-2280 | 256 km | Windrichtung ganztägig ausserhalb Sektor |
| 18.06. | Ebenalp | 214 km | Gewitter 13–17 h |
| 29.05. | Disentis Caischavedra | 168 km | Start-Fenster: nur 1 h sauber |
| 29.05. | Verbier Ruinettes | 161 km | Böen 41–44 km/h |
| 27.05. | Weissenstein | 158 km | Verhältnis sauber/gesamt 17 % |
| 14.06. | Dent de Jaman | 114 km | Höhenwind >30 km/h in 4 h |

## Befund 4 — die Fehlalarmrate ist stark tagesabhängig, nicht gleichverteilt

| Tag | Spots | not_safe |
|---|---|---|
| 17.06. | 29 | 6.9 % |
| 18.06. | 86 | 9.3 % |
| 16.06. | 30 | 13.3 % |
| … | | |
| 15.06. | 19 | 63.2 % |
| 14.06. | 25 | 72.0 % |
| 19.06. | 37 | **81.1 %** |

An ruhigen Tagen liegt der Filter richtig, an bewegten Tagen sperrt er flächig,
während real geflogen wird. Ein globales Nachjustieren der Schwellen würde die
guten Tage verschlechtern — die Arbeit muss an den Tagen mit Wind/Scherung
ansetzen.

## Befund 5 — regionale Schieflage im Sicherheits-Status

`not_safe`-Anteil an Region-Tagen mit Flügen ≥60 km (nur Regionen mit ≥3 Tagen):

| Region | Tage | not_safe | median km an diesen Tagen |
|---|---|---|---|
| Freiburger Voralpen | 9 | 33.3 % | **180.8** |
| Mittelland Zentral | 3 | 33.3 % | 96.7 |
| Schwarzsee / Gantrisch | 3 | 33.3 % | 107.7 |
| Jura Zentral | 5 | 20.0 % | 85.1 |
| Unterwallis | 6 | 16.7 % | 143.4 |
| Berner Oberland | 7 | 14.3 % | 80.6 |
| Oberwallis / Goms, Jura West, Berner Voralpen, ZS Voralpen, Glarnerland, Alpstein, Genferseeregion | 3–5 | 0.0 % | 81–264 |

„Freiburger Voralpen" ist der auffälligste Fall: an einem Drittel der Tage
`not_safe`, und ausgerechnet an Tagen mit im Median 181 km. Zur Erinnerung — der
Regionsname ist irreführend, das Polygon deckt u. a. Kandersteg ab
(`docs/pläne/PLAN_regionen_umbenennung.md`).

Das ist eine **andere** Schieflage als die aus `2026-07-26_ANALYSE_49_TAGE.md`:
dort ging es um die Thermik-Rangfolge (Jura Zentral zu hoch), hier um den
Sicherheits-Status. Beide Befunde stehen nebeneinander, keiner ersetzt den anderen.

## Befund 6 — Flugvolumen als Gegensignal: wir überschätzen nicht (15 Tage)

Nachtrag auf Hinweis aus der Praxis: Piloten fliegen auch an unsicheren Tagen,
aber die **Anzahl** Flüge verrät den Tag. Das relativiert das „Überschätzung ist
nicht messbar" oben — als Indiz, nicht als Beweis.

Der Einwand dagegen ist der Wochentag, und er stimmt: Wochenende 184 Flüge im
Median gegen 111 an Werktagen. Der Wetter-Effekt ist aber um ein Vielfaches
grösser — an zwei Donnerstagen 15 bzw. 648 Flüge, an zwei Dienstagen 3 bzw. 68.
**Faktor 40 innerhalb desselben Wochentags gegen Faktor 1.7 zwischen den
Wochentagen.** Damit ist die Flugzahl als grobes Tagessignal brauchbar.

Wichtig für die Auswertung: Tage mit Stub-Flugeinschätzung (`exp_ok=False`) und
der kaputte 20.06.-Snapshot müssen raus — deren Tagesnote von 1.0 ist ein
Artefakt und würde die Korrelation künstlich verbessern.

Ergebnis über 15 gültige Tage — **Rang-Korrelation Flugzahl ↔ Tagesnote 0.58**:

| Datum | Tag | Flüge | unsere Note | Befund |
|---|---|---|---|---|
| 18.06. | Do | 648 | 4.34 | |
| 30.05. | Sa | 538 | 4.31 | |
| 07.06. | So | 482 | 3.59 | |
| 27.05. | Mi | 292 | 4.03 | |
| **13.06.** | **Sa** | **236** | **1.59** | **stark unterschätzt** |
| 28.05. | Do | 139 | 4.17 | |
| … | | | | |
| **14.06.** | **So** | **104** | **1.10** | **stark unterschätzt** |
| 15.06. | Mo | 71 | 2.14 | unterschätzt |
| 12.06. | Fr | 17 | 1.69 | |

Zwei Aussagen daraus:

1. **Kein einziger überschätzter Tag.** Es gibt keinen Tag, an dem wir gut
   gesagt hätten und real kaum geflogen wurde. Die vier grössten Flugtage sind
   exakt unsere vier bestbewerteten Tage.
2. **Die Pessimismus-Schlagseite zeigt sich auch auf Tagesebene**: am 13.06.
   Note 1.59 bei 236 Flügen, am 14.06. Note 1.10 bei 104 Flügen. Das sind
   dieselben Tage, die auf Spot-Ebene 72–81 % Fehlalarme hatten.

**Grenzen**: 15 Tage sind wenig, und die Stichprobe enthält kaum echte
Grenzfall-Tage. Feiertage, Ferien und Wettkämpfe sind nicht kontrolliert.
Die Aussage „wir überschätzen nicht" gilt für diesen Zeitraum, nicht generell.

## Befund 7 — die Sicherheitssperre erzwingt die Flugnote 1 (Absicht, bleibt vorerst)

**81 von 81** gesperrten Spot-Tagen haben `experience_rating` exakt 1 — auch die
mit 214 km. Keine Streuung, keine Ausnahme. Ursache steht im Code, für Spot und
Region identisch (`engine/analyzers.py`, „RATING_ARCHITECTURE v2.1"):

```
if result.get("safety_status") == "not_safe":
    result["experience_rating"] = 1
    ... return result          # die eigentliche Bewertung wird übersprungen
```

Widerspruch zur eigenen Vorgabe: der Prompt sagt wörtlich „PHASE 2: FLIEGBARKEIT
(experience_rating 1–5, **unabhängig von Sicherheits-Status**)" — der Code koppelt
sie dann hart.

**Folge**: jeder Fehlalarm kostet zwei Aussagen. Von den schlechten Noten bei
bewiesen guten Bedingungen sind die meisten keine Fehleinschätzung, sondern
erzwungen — bei Flügen ≥60 km sind 7 von 9 Fällen erzwungen, bei Masse+Distanz
3 von 4.

Was ein Entkoppeln brächte (ohne jede Änderung am Bewertungsmodell):

| Kennzahl | heute | entkoppelt |
|---|---|---|
| Masse+Distanz → Note 4/5 | 74 % | 82 % |
| Masse+Distanz → falsche Note 1–2 | 13 % | 4 % |
| ≥60 km → Note 4/5 | 80 % | 86 % |
| ≥60 km → falsche Note 1–2 | 8.7 % | 2.1 % |

> **Entscheid User 30.07.: war Absicht, bleibt vorerst so.** Für die Auswertung
> heisst das: die gemessenen Zahlen sind die erlebten Zahlen. Und es heisst, dass
> ein Fix der Sperre beide Kennzahlen gleichzeitig hebt — ein Hebel, zwei Effekte.

## Befund 8 — gegen die dumme Regel gemessen (Tagesebene)

Kein Wettbewerber veröffentlicht Trefferquoten. Der belastbare Massstab ist
deshalb die naive Regel. Über 15 Tage, bei denen beide Fehlerrichtungen prüfbar
sind (9 real gut, 6 real schlecht):

| Methode | Trefferquote |
|---|---|
| immer „guter Tag" sagen | 60 % |
| nur Steigwert, nachträglich optimale Schwelle | 67 % |
| **unser System** | **67 %** |

Auf Tagesebene schlagen wir eine einzelne Kennzahl **nicht**. Zwei Einordnungen
dazu, beide nötig:

1. Die Steigwert-Schwelle wurde auf denselben Daten optimiert — sie ist
   geschmeichelt.
2. Die Tagesfrage ist nicht die Produktfrage. „Ist heute gut in der Schweiz"
   steht in jedem Wetterbericht.

**Aber der Vergleich ist unfair zugunsten der dummen Regel**, weil sie nie warnt
und die meisten Tage gut sind. Entscheidend ist die Warnung:

| | warnt | davon berechtigt | schlechte Tage erkannt |
|---|---|---|---|
| dumme Regel | nie | — | 0 % |
| **unser System** | 5 von 15 Tagen | **60 %** | **50 %** |

Bei mutigerer Schwelle (Warnung unter 60 % guter Regionen) stiege die Erkennung
auf 83 % bei gleichbleibender Trefferquote (62 %) — **unsere Warnungen sind nicht
zu häufig, sie stehen an den falschen Tagen.** Die beiden Fehlwarnungen (13./14.06.)
sind wieder die Tage mit Modell-Steigwert 2.9/2.8 m/s, überschrieben von der Sperre.
Ohne sie stünde es 5 von 5.

Robustheitsprüfung: mit der Definition „Tagesnote = mittlere Regionsnote, 4–5 gut /
1–3 schlecht" kommen exakt dieselben Zahlen heraus (67 % / 60 % / 50 %). Das
Ergebnis hängt nicht daran, wo man die Grenze zieht.

## Befund 9 — Spot-Ebene: räumliche Trennschärfe NICHT nachweisbar

Die eigentliche Produktfrage lautet nicht „ist heute gut", sondern „welcher Berg
ist heute besser". Vier Tests, alle innerhalb desselben Tages:

| Test | unsere Note | roher Steigwert |
|---|---|---|
| Rangkorrelation mit bester Distanz je Spot | 0.01 | 0.03 |
| Rangkorrelation mit Pilotenzahl je Spot | −0.02 | −0.03 |
| dito, normiert auf die übliche Beliebtheit | 0.05 | 0.02 |
| Flugwahrscheinlichkeit Note 4–5 vs. 1–2 | 10.4 % vs. 9.7 % (1.1×) | — |

Gegenprobe: es liegt **nicht** an fehlender Streuung. Innerhalb eines Tages
vergeben wir das ganze Spektrum (27.05.: 33× Note 1, 111× Note 5; mittlere
Streuung 1.29 Notenpunkte). Wir differenzieren kräftig — die Differenzierung
trifft nur nicht.

**Ehrliche Einordnung**: der rohe Steigwert schneidet genauso ab. Wenn eine rein
physikalische Grösse ebenfalls bei null landet, sagt das auch etwas über den Test:

- Piloten fahren zum Hausberg, nicht zum besten Berg (Fahrzeit, Verein, Kollegen)
- die Distanz misst zur Hälfte den Piloten, nicht den Ort
- die schlecht bewerteten Spots tauchen gar nicht erst auf (0-Launches-Regel) —
  gerade unsere womöglich richtigen Warnungen sind unsichtbar

**Fazit**: „nicht nachweisbar" ist nicht „widerlegt", aber deutlich weniger als
erhofft. Belastbar ist die **Region** (81 %). Für die Spot-Frage bräuchte es
andere Daten — Flüge desselben Piloten an verschiedenen Orten, oder Livetrack mit
Steigwerten statt nur Distanzen. Mit XContest-Distanzen ist sie nicht entscheidbar.

**Produktkonsequenz**: Region in den Vordergrund, Spot als Detail. Wir sollten
nicht suggerieren, wir wüssten, dass Spot A heute besser ist als Spot B.

## Befund 10 — entkoppelt gerechnet: zwei Systeme, das schlechtere übermalt das bessere

Annahme (User, 30.07.): `not_safe` sagt nichts über die Thermik. Wo gesperrt wurde,
liegt **keine** Flugbewertung vor — nicht die Note 1. Alles neu gerechnet, gesperrte
Fälle als „keine Aussage" behandelt statt als Note 1:

| Kennzahl | Spot | Region |
|---|---|---|
| Masse+Distanz → Note 4/5 | **82 %** | **93 %** |
| dabei falsche Note 1–2 | 4 % | **0 %** |
| alle Flüge ≥60 km → Note 4/5 | 86 % | 89 % |

Tagesebene, Tagesnote nur aus nicht gesperrten Regionen:

| | mit Zwangsnote | entkoppelt |
|---|---|---|
| Trefferquote | 67 % | **73 %** |
| zu pessimistisch | 2 Tage | **0 Tage** |
| zu optimistisch | 3 Tage | 4 Tage |

Der 13./14.06. kippen: die nicht gesperrten Regionen sagten dort Note 4 — richtig.
**Das Thermikmodell hat an keinem der 15 Tage einen guten Tag verkannt.**

**Zwei Vorbehalte, beide wichtig:**

1. Der Pessimismus verschwindet nicht durch Können, sondern weil nur noch eine
   Fehlerrichtung übrig bleibt. Ohne die Sperre gibt es **kein Warninstrument** —
   jeder Tag bekommt Note 4, auch die schlechten (3 → 4 zu optimistische Tage).
   Die Sperre ist zugleich Störung *und* das Einzige, was heute warnt.
2. Am 14.06. war nur **1 von 29** Regionen ungesperrt, am 13.06. 5 von 29. Die
   Tagesnote steht dort auf sehr dünnem Fundament — Richtung belastbar, Präzision nicht.

**Konsequenz für die Priorisierung**: das Thermikmodell braucht keine Arbeit
(93 % auf Regionsebene). Die Arbeit liegt vollständig in der Sicherheitsprüfung,
konkret der Windrichtungs-Regel. Und in der Anzeige: „thermisch ein 5er-Tag, aber
dieser Startplatz geht bei diesem Wind nicht" wäre dieselbe Warnung mit einer
Aussage, die stimmt.

---

## Nebenbefund: `our_status` wurde nie geschrieben (behoben)

`xc_aggregate.py` las `status` aus dem Snapshot, nutzte ihn für `finding_type` —
schrieb aber die Spalte `our_status` nie in die Zeile. Alle maschinell erzeugten
Zeilen seit 27.05. haben die Spalte leer; gefüllt sind nur die 327 Zeilen der 14
handkuratierten Tage. Fix: `row["our_status"] = status` in `build_rows`.

**Folge**: jede frühere Auswertung, die auf `observations.csv.our_status` filterte,
hat auf 18 % der Daten gearbeitet, ohne dass das auffiel. `observations.csv` ist
noch nicht neu aufgebaut — die Historie trägt die Lücke weiter.

## Was daraus folgt (Reihenfolge)

1. **Sektor-Komplex vor Schwellen-Tuning**: 43.5 % der harten Fehlalarme sind
   Windrichtung. `sector_audit.csv` ist dafür das vorhandene Arbeitsblatt.
2. **Start-Fenster-Regel (I-007)** ist der zweite Block — „nur 1 h sauber" bei
   einem 168-km-Tag ist keine haltbare Aussage.
3. **Erst danach** Region-Ebene anfassen — die ist mit 10.7 % das schwächste
   Problem der drei.
4. `observations.csv` neu aufbauen, damit die Historie `our_status` und die
   Alias-Auflösung trägt.
