# Plan: OGN-Validierung — Real-Flug-Belege über OpenGliderNetwork

**Status:** Mitschnitt seit 14.08.2026 in Betrieb, **Phase 2 (Verdichtung)
seit 17.08.2026 fertig und im Scheduler**. Offen ist Phase 3 (Auswertung in
`validation/ogn/`).
**Erstellt:** 2026-06-14 · **Überarbeitet:** 2026-08-17 (Phase 2 umgesetzt)
**Branch:** `main` (Single-Branch-Workflow)

## Umsetzungsstand Phase 2 (17.08.2026)

**Gebaut:** `ogn_sessions.py` (+ Hook in `scheduler.py._daily_run`, Tests in
`tests/test_ogn_sessions.py`). Aus Rohpunkten entstehen Flüge mit Steig- und
Höhenwerten, dazu die Empfangslage je Region. Idempotent und
`--backfill`-fähig; das Pruning der Rohpunkte läuft bewusst **nur hier** —
erst verdichten, dann wegwerfen.

**Ertrag an den ersten vier Tagen** — und er folgt dem Wetter fast eins zu eins:

| Tag | Flüge | Geräte | Regionen | Dauer P50 | Steigen P75 (Median) | Regen (Ø Region) |
|---|---:|---:|---:|---:|---:|---:|
| 14.08. | 1682 | 970 | 26 | 33 min | 2.01 m/s | 9.3 mm |
| 15.08. | 1299 | 936 | 26 | 30 min | 1.81 m/s | 8.4 mm |
| 16.08. | 352 | 276 | 23 | 28 min | 1.71 m/s | 14.9 mm |
| 17.08. | 2 | 2 | 1 | 11 min | 1.31 m/s | 32.0 mm |

Zum Vergleich: die P50→P75-Umstellung der Basishöhe hängt bis heute an
**16** XContest-Topouts. Ein einziger starker Tag liefert hier über 1000 Flüge.

### Was ein Flugdatensatz enthält — und was davon trägt

Nicht jedes Feld ist gleich belastbar. Der Unterschied entsteht durch die
Empfangslücken (gemessen am 14./15.08., 2981 Flüge):

| Feld | belastbar? |
|---|---|
| **Steigen P75** (`climb_p75`) | **ja** — lückenrobust, siehe unten |
| **erreichte Höhe** (`max_alt_m`, `max_height_agl_m`) | **ja** |
| Startpunkt (`launch_lat/lon`, `launch_spot`, `region`) | nur bei bodennahem Start — **33 %** |
| Landepunkt (`landing_lat/lon`, `landing_region`) | nur bei bodennaher Landung — **23 %** |
| Dauer, Streckenlänge | **nein** — systematisch zu kurz |
| `climb_max` | fragil, hängt an einem Einzelwert |

**Start UND Landung zusammen haben nur 13 %** der Flüge; **57 % sind reine
Bruchstücke** (weder Start noch Landung empfangen). Genau deshalb stehen
`takeoff_agl_m` und `landing_agl_m` in der Tabelle: Ohne sie ist nicht
entscheidbar, ob eine Koordinate ein echter Start-/Landeplatz ist oder bloss
die Stelle, an der der Empfang ein- bzw. aussetzte. **335 Flüge landen am
Boden, starten aber in der Luft** — die sähen ohne diese Felder wie
einwandfreie Startpunkte aus.

Die Landekoordinate fehlte zunächst ganz (nachgetragen 17.08.): gespeichert
war nur die Höhe über Grund bei der Landung, nicht der Ort. Sie ist eigenes
Neuland — **54 von 64 Landeplätzen mit ≥ 3 Landungen liegen mehr als 1 km von
jedem Startplatz entfernt**, sind also eigenständige Landewiesen, die in einer
Startplatz-Liste gar nicht vorkommen können. 22 % der vollständigen Flüge
landen in einer anderen Region, als sie gestartet sind; 11 % sind
Toplandungen (< 300 m vom Start).

### Die zwei Schwellenwerte — abgelesen, nicht geraten

Beide wurden an 1414 Geräten / 1.12 Mio. Punkten des 15.08. gemessen
(Sonden als Wegwerf-Code, bewusst nicht im Repo):

- **Sendepause = Flugende: 300 s.** 99.85 % aller Punktabstände desselben
  Geräts liegen darunter. Mit 60 s zerfällt ein Flug an jeder Empfangslücke
  (9.4 Sessions je Gerät, Dauer-Median 9 min); ab 600 s werden echte
  Zweitflüge zusammengeklebt.
- **Boden vs. Luft: Bewegungsfenster ±60 s.** Ein eingeschaltetes Gerät heisst
  nicht „fliegt" — am Startplatz stehen Instrumente im P90 noch 10 Minuten
  herum, im P99 fast 50. Geprüft wird Strecke **oder** Höhenänderung: Soaring
  am Hang bewegt sich kaum horizontal, ein Transport im Auto kaum vertikal.

### Drei Defekte, die der erste Lauf über echte Daten zeigte

Alle drei hätten stille Falschzahlen erzeugt und wären beim Draufschauen nicht
aufgefallen. Jeder ist im Code behoben **und** in `tests/test_ogn_sessions.py`
festgenagelt:

1. **Positionssprünge** — ein „Flug" ergab 911 km in 56 min (~975 km/h).
   Einzelne Beacons sitzen weit neben der Bahn. Jetzt Geschwindigkeitsfilter
   mit Neu-Verankerung, damit ein falscher Ankerpunkt nicht den Rest kappt.
2. **Geräte am Boden** — 364 min „Flug" mit 3.8 km und 1 m über Grund. Das
   Höhen-Rauschen allein riss die Spannen-Schwelle. Zwei unabhängige Merkmale
   entlarven es: Höhe über Grund und **zurückgelegte Bahn** (ein Schirm fliegt
   ~30 km/h durch die Luft, auch beim Soaring; das Instrument kam auf
   0.6 km/h). Der Bahn-Filter kostet real nur 3 von 1302 Flügen — er trifft
   genau die Liegengebliebenen.
3. **Höhe über Grund bis −1214 m** — und genau die speiste die
   Empfangs-Kennzahl. Unplausible Werte werden jetzt als *unbekannt* geführt
   statt als Zahl: lieber eine fehlende Messung als eine erfundene. Sonst
   „bestätigt" eine geschönte Empfangslage exakt den Defekt, den wir suchen.

### Erledigte Vorab-Entscheidungen

- **#4 Gap-Schwelle:** 300 s (Begründung oben).
- **#5 Terrain/AGL:** Open-Meteo-Elevation, auf ~100 m gerastert in der Tabelle
  `terrain` gecacht. Kein SRTM-Download, keine neue Abhängigkeit. Ein starker
  Tag braucht rund 3000 neue Rasterzellen ≈ 30 API-Aufrufe; danach greift der
  Cache. **Achtung:** ohne den Key aus `.env` läuft es in den freien Endpunkt
  und dort ins Rate-Limit (429) — also mit `./.venv/bin/python` starten.

### Korrigierte Zahlen

- **Speicherbedarf: rund 222 MB pro starkem Sommertag** (gemessen: 454 MB für
  2.66 Mio. Punkte = 171 Byte/Punkt). Die Schätzung von 75 MB im Abschnitt
  unten war **dreimal zu tief**.

### Aufbewahrung: 7 Tage statt 30 (Entscheid 17.08.2026)

30 Tage hätten an einer Schönwetterserie bis **6.7 GB** bedeutet — ein Drittel
des freien Plattenplatzes für Rohmaterial, das nach der Verdichtung niemand
mehr braucht. Jetzt: **7 Tage, gut 1.5 GB im schlimmsten Fall.**

Die Verkürzung legte ein Risiko frei, das bei 30 Tagen nur theoretisch war:
**der Collector räumte eigenständig auf**, ohne zu wissen, ob die Verdichtung
gelaufen ist. Bei einer Woche Frist hätte ein stiller Ausfall die Rohdaten
gelöscht, bevor er auffällt. Die Zuständigkeit ist deshalb neu geteilt:

| | wer | wann | was |
|---|---|---|---|
| **Regelbetrieb** | `ogn_sessions.prune_beacons` | täglich nach dem Roll-up | nur Tage, die im **`rollup_log`** stehen — also nachweislich verdichtet sind |
| **Notbremse** | `ogn_collector._prune` | täglich | alles älter als `HARD_LIMIT_DAYS` = 30, **mit Fehlermeldung im Log** |

Fällt die Verdichtung aus, wachsen die Rohpunkte also absichtlich weiter,
statt still zu verschwinden — man kann den Ausfall nachholen
(`ogn_sessions.py --backfill`). Erst nach Wochen greift die Notbremse gegen
eine volllaufende Platte, und sie meldet sich dabei. `--report` und der
Scheduler nennen unverdichtete Tage beim Namen; das ist bei kurzer Frist die
Zahl, auf die man schaut.

Am Trockenlauf gegen die echte Datenbank belegt: hätte die Verdichtung den
15.08. verpasst, blieben dessen **1 123 655 Rohpunkte** geschützt stehen statt
gelöscht zu werden.

**Was man wissen muss:** SQLite gibt gelöschten Platz nicht ans Dateisystem
zurück. Die Datei bleibt auf ihrem Höchststand (rund 1.7 GB bei 7 vollen
Tagen) und füllt ihn danach wieder auf — das ist die Obergrenze, nicht der
laufende Verbrauch.

- **17 % der Flüge starten ausserhalb unserer Regionspolygone.** Unsere
  29 Regionen kacheln die Schweiz nicht lückenlos, und der 150-km-Filter reicht
  ins Ausland. Diese Flüge sind für den Regionsvergleich schlicht nicht
  verwendbar — kein Fehler, aber eine Grenze, die in Phase 3 sichtbar bleiben
  muss.

### Sind die Flüge trotz Empfangslücken brauchbar? (geprüft 17.08.)

Ja — für das, wozu wir sie brauchen. Die Lücken sind erheblich (53 % der Flüge
sind über 10 % ihrer Dauer blind, 14 % über die Hälfte), aber sie treffen die
Felder ungleich:

- **Das Steigen bleibt stabil.** Der saubere Test läuft *innerhalb* einer
  Region, wo die echten Bedingungen gleich sind: dort ist der Unterschied
  zwischen gut und schlecht empfangenen Flügen **±0.00 m/s im Median**, und
  6 von 14 Regionen zeigen ihn in die eine, 8 in die andere Richtung. Auch der
  Gesamtwert bewegt sich kaum (1.91 m/s ungefiltert, 1.81 unter dem
  strengsten Filter). Grund: Das Steigen misst das Instrument des Piloten
  selbst und meldet es je Punkt — fehlende Punkte **verdünnen** die Stichprobe,
  sie **verschieben** sie nicht. Dauer und Strecke sind dagegen aufsummiert,
  da fehlt jede Lücke direkt.
- **Zwischen Regionen** korreliert schlechter Empfang mit höherem Steigen
  (Rangkorrelation +0.57). Das ist keine Verzerrung, sondern Überlagerung:
  Wo der Empfang am schlechtesten ist (Wallis, Berner Alpen), sind die
  Thermiken tatsächlich am stärksten. Der Innerhalb-Test oben schliesst die
  Messfehler-Erklärung aus.
- **Die Regionszuordnung** stimmt in 88 % (Start- vs. Hochpunkt-Region);
  65 % der Flüge bleiben ganz in einer Region.

**Bleibt als Grenze:** Flüge, die wir *gar nie* hören, kann keine Auswertung
von innen sichtbar machen. Die Grundregel gilt weiter — Anwesenheit ist ein
Beleg, Abwesenheit sagt nichts.

### Nächster Schritt: Phase 3
`validation/ogn/` nach Hausordnung anlegen und gegen den Prognose-Freeze
rechnen. Die Empfangslage (`coverage`) liegt dafür bereits vor: am 15.08.
hörten **25 von 26** Regionen Flüge unter 300 m über Grund.

Drei Vorgaben aus der Lückenmessung:
1. **Qualitätstor** setzen (Vorschlag: Blindzeit ≤ 25 % und tiefster Punkt
   ≤ 200 m über Grund) — das lässt 41 % der Flüge übrig, 12 Regionen mit je
   ≥ 20 vollständigen Flügen in nur zwei Tagen.
2. Das Steigen der Region des **Hochpunkts** gutschreiben, nicht der des
   Starts. Das behebt die 12 % Fehlzuordnung.
3. **Dauer und Strecke gar nicht erst** als Prüfgrössen verwenden.

### Beobachtung am Rande, die noch keiner Erklärung hat
Unter den zehn längsten Flügen des 15.08. stammen **sieben vom Weissenstein
(Jura Zentral)**, mit Dauern bis 5.9 h. Das ist genau die Region, die in der
XContest-Auswertung mit Perzentil 100 % auffällt. Ob das echte
Jura-Soaring-Bedingungen sind oder ein Artefakt (SafeSky-Handys, Segelflug
unter Gleitschirm-Kennung), ist **offen** und vor jeder Kalibrierung zu klären.

## Umsetzungsstand Phase 1 (14.08.2026)

**Entschieden:** nur Gleitschirm (Typ 7) und Delta (Typ 6) mitschreiben ·
Rohpunkte ~~30 Tage~~ **7 Tage** halten (revidiert 17.08., siehe oben) ·
Umkreis **150 km um 46.8/8.2** (deckt die CH ab,
in der Messung bestätigt).

**Gebaut:** `ogn_collector.py` + `ogn-collector.service`. Ohne neue Abhängigkeit
— das APRS-Format wird direkt gelesen, verifiziert gegen echte Rohzeilen.
Geräte-Kennung nur als Hash (Salt in `data/ogn_salt.txt`, gitignored, darf nie
wechseln), Stealth-/No-Track-Geräte werden beim Eintreffen verworfen.

**Offen:** ~~Phase 2 (Flüge bilden)~~ — erledigt 17.08., siehe oben. Phase 3
(Auswertung) steht noch aus.

**Erste Zahlen vom laufenden Dienst** (14.08., 11:13–11:16, Mittagsbetrieb):
2482 Punkte, **126 verschiedene Geräte**, 98 % Gleitschirm, Höhen 694–3890 m,
maximales Steigen **6.84 m/s**. Morgens um 09:21 waren es 14 Geräte — der
Tagesgang ist also gross, und die Verbreitungsfrage ist praktisch beantwortet
(das Gate verlangte rund 40 Geräte).

**Speicherbedarf:** ~~hochgerechnet rund 75 MB pro Tag~~ — **überholt.** Die
echte Messung nach vier Sammeltagen ergab **222 MB pro starkem Tag** (siehe
„Korrigierte Zahlen" oben). Auch diese Schätzung war noch dreimal zu tief; alle
früheren Zahlen in diesem Abschnitt sind es erst recht.

### Nächster Schritt (Phase 2) — am 17.08. so abgearbeitet
Bewusst nicht am 14.08. gebaut: Die zwei Schwellenwerte des Verdichters — ab
welcher Sendepause ein Flug endet, und wie Boden von Luft getrennt wird — lassen
sich nur an **abgeschlossenen** Flügen ablesen. Der Ablauf hat sich bewährt,
besonders Schritt 3: er hat alle drei Defekte gefunden.
1. ✅ Aus dem vollen Tag die tatsächlichen Pausen- und Startmuster abgelesen.
2. ✅ `ogn_sessions.py` gebaut, rückwirkend über alle Tage laufen lassen.
3. ✅ Ergebnis gegen die Wirklichkeit geprüft — drei Defekte gefunden und
   behoben (siehe oben). **Ohne diesen Schritt wären 911-km-Flüge und
   Geräte am Boden als Belege in die Kalibrierung gegangen.**
4. ✅ Geländefrage geklärt: kein DEM im Repo, daher Open-Meteo-Elevation mit
   eigenem Raster-Cache.

### Was die ersten echten Daten gezeigt haben
- **Ein eingeschaltetes Gerät heisst nicht „fliegt".** Am Morgen stehen viele
  Instrumente am Startplatz und senden. Der Sessionizer muss Boden von Luft
  trennen (Bewegung/Höhenänderung), sonst ist jede Airtime-Zahl Unsinn.
- **Gerätekennungen sind nicht einheitlich lang** — Naviter sendet 8 statt
  6 Hex-Zeichen. Ein zu enges Muster schneidet sie ab und erzeugt stille
  Fehlzählungen. Im Collector berücksichtigt.
- **Nicht alles ist ein FANET-Instrument.** Es funken auch Handy-Apps
  (SafeSky) unter Gleitschirm-Kennung. Für die Verbreitungsfrage zählt das mit,
  für Steigwerte ist es unsicherer — bei der Auswertung im Blick behalten.
- Steigwerte kommen als Fuss/Minute und rechnen sich sauber um (Stichprobe:
  `-811fpm` → −4.12 m/s). Kanal funktioniert.

**Wiederaufnahme (HIER starten):**
1. Diese Datei lesen. Die beiden wichtigsten Abschnitte sind
   **„Was OGN sagen kann — und was nicht"** und **„Die zwei Verzerrungen"**.
   Beide dürfen nicht aufgeweicht werden.
2. Der Einstieg ist **Phase 3**. Phase 0–2 sind erledigt; es laufen
   `ogn_collector.py` (Daemon) und `ogn_sessions.py` (täglich im Scheduler),
   die Tabellen `beacons`, `flights`, `coverage`, `terrain` sind gefüllt.
   Was noch fehlt, ist ausschliesslich `validation/ogn/`.
3. Vor der ersten Kalibrierung die **Weissenstein-Auffälligkeit** klären
   (Abschnitt „Beobachtung am Rande"). Sie sitzt genau auf dem Defekt, den wir
   messen wollen — sie zuerst zu glauben wäre die bequemste Art, sich zu irren.

---

## Was OGN sagen kann — und was nicht

**OGN ist eine einseitige Beweisquelle.** Kein empfangener Flug heisst nie
„der Tag war schlecht" — er heisst „wir haben nichts gesehen". Zulässig ist
ausschliesslich der umgekehrte Schluss: Wo geflogen, gestiegen und Höhe
gemacht wurde, dort waren die Bedingungen gut.

Das ist dasselbe Prinzip wie bei `validation/xcontest/`, aber aus anderem
Grund und mit anderer Datenbasis:

| | **validation/xcontest** | **validation/ogn** |
|---|---|---|
| Beobachtungseinheit | deklarierter Rekordflug (≥ ~40 km, hochgeladen) | Roh-Telemetrie eines Trackers (jeder empfangene Flug) |
| Erfasst auch | nein: nur die langen Flüge | ja: Soaring, kurze Hops, Sledrides, Top-Landungen |
| Befüllung | **manuell** (`_raw/_paste_*.txt`) | automatisch (Daemon) |
| Verzerrung | Upload-Motivation + Distanz-Attraktivität | Geräte-Adoption **und Empfangs-Abdeckung** |
| Inferenz bei Anwesenheit | Untergrenze „Bedingungen waren XC-tauglich" | direkter Messwert des Flugs (Steigen/Höhe/Airtime) |
| Inferenz bei Absenz | **uninformativ** | **uninformativ** |

### Die drei Messgrössen, nach Belastbarkeit sortiert

1. **Steigwerte und erreichte Höhe** — das Fundament. Direkt gemessen,
   unabhängig davon, ob zehn oder hundert Leute unterwegs waren. Sie treffen
   genau den bekannten offenen Defekt: die *systematische regionale Schieflage*
   der Thermik-Bewertung. Die P50→P75-Umstellung der Basishöhe hängt bis heute
   an **16** XContest-Topouts — OGN kann Hunderte liefern.
2. **Aktivität (Anzahl Flüge/Airtime)** — nur als **Kontext**, nie als
   Bewertung. Siehe unten, „Warum Flugzahlen verdorben sind".
3. **Distanz** — am fragilsten. Bricht der Empfang mitten im Flug ab, zerfällt
   eine Strecke in Bruchstücke. Beiwerk, kein Beleg.

### Warum Flugzahlen als Massstab verdorben sind

Die Zahl der Flüge misst dreierlei mit:
- **Wochentag** — am Wochenende fliegen deutlich mehr Leute als am Dienstag.
- **Ferien und Feiertage.**
- **Die Prognose selbst** — Piloten fahren nur raus, wenn die Vorhersage gut
  aussieht. Damit misst die Flugzahl teilweise das Modell statt das Wetter:
  die Modell-gegen-Modell-Falle aus der Lehre vom 02.08., nur besser getarnt.

**Die Abkürzung, die das löst:** nicht absolut zählen, sondern **Regionen am
selben Tag gegeneinander**. Wochentag, Ferien und allgemeine Wetterstimmung
wirken auf alle Regionen gleich und fallen beim Tagesvergleich heraus. Übrig
bleibt die Frage, die uns interessiert: Wo war an diesem Tag überdurchschnittlich
viel los, und deckt sich das mit unserer Rangliste? Das funktioniert **ab dem
ersten Tag** und braucht keine Historie.

Der absolute Normalwert („für einen Dienstag im Mai ist das aussergewöhnlich
viel") bleibt ein Ziel für **später** — er braucht eine ganze Saison und ist
kein Fundament für den Start.

---

## Die zwei Verzerrungen

**1. Geräte-Adoption.** Nicht jeder trägt einen FANET-/FLARM-Tracker. Betrifft
das Ob, nicht das Wie — durch die Einseitigkeit oben abgedeckt.

**2. Empfangs-Abdeckung — der gefährliche.** OGN sieht nur, was eine
Bodenstation hört. In den Alpen hängt das an Stationsdichte und Sichtlinie: ein
Schirm tief im Tal wird nicht empfangen, ein hoher Flug schon. Diese Lücke
**korreliert mit dem Gelände, ist also regional strukturiert**.

Warum das hier besonders heikel ist: Der bekannte Kern-Defekt ist eine
*regionale* Schieflage (Jura Zentral vs. Prättigau). Eine regional strukturierte
Empfangslücke kann exakt so ein Muster **erzeugen** — wir würden einen Defekt
„bestätigen", der in Wahrheit im Messgerät sitzt.

**Wie weit die Verzerrung trägt:**
- Auf die **Ja/Nein-Aussage**: harmlos. Ein empfangener Flug ist ein Beweis.
  Lücken kosten Belege, sie erfinden keine falschen.
- Auf die **Zahlenwerte**: gefährlich. Hören wir in einer Region nur die hohen
  Flüge, sieht sie beim Steig-/Höhenvergleich besser aus, als sie war.

**Gegenmassnahme, ab Tag 1 mitgeplant (nicht nachträglich):** Die Empfangslage
lässt sich aus denselben Daten messen — Empfänger-Kennungen und -Positionen pro
Region, Verteilung der *tiefsten* empfangenen Höhen über Grund je Region. Damit
wird sie eine bekannte, stabile Grösse, mit der man rechnet, statt ein blinder
Fleck. Regionen mit unvergleichbarer Abdeckung werden nicht verglichen.

---

## Grundvoraussetzung: OGN ist ein Live-Stream

OGN hält **kein abfragbares Archiv** des Roh-Streams. Daten kommen über einen
kontinuierlichen APRS-TCP-Stream (`aprs.glidernet.org`), auf dem man dauerhaft
verbunden bleiben muss. Nicht mitgeschnitten = für immer weg. Daraus folgt ein
**dauerhaft laufender Collector-Daemon** (eigener systemd-Service), KEIN
Cron-Pull. „Regelmässig" betrifft nur die tägliche *Aggregation*.

**Aber:** Ob es Dritt-Quellen mit Vergangenheit gibt (Tages-Flugbücher,
Archive im OGN-Umfeld), ist **ungeprüft** — siehe Phase 0. Falls ja, entfällt
das wochenlange Warten komplett.

Gleitschirm ist über das **Aircraft-Type-Feld** unterscheidbar (FANET 1 /
FLARM 7), Delta (FANET 2 / FLARM 6) und Segelflug (FANET 4 / FLARM 1) ebenso.
Der Typ ist **selbstdeklariert**; für FANET-Instrumente (Skytraxx/XCTracer/
Syride = genau die Zielgruppe) i. d. R. korrekt. „unknown" (0) ist eine reale
Restklasse, die weder als Gleitschirm gezählt noch sicher ausgeschlossen wird.

---

## Einordnung in die Hausordnung

Seit 03.08.2026 gilt: **eine Domäne = ein Unterordner unter `validation/`**,
mit `README.md` (inkl. Pflicht-Abschnitt „Grenzen des Richters"), `SCHEMA.md`,
`PATTERNS.md`, `AUTO_REPORT.md`. OGN ist dort bereits als Kandidat eingetragen.

- Zielort ist **`validation/ogn/`** — kein eigener Ordner im Repo-Root.
  (Der ursprüngliche Plan wollte `ogn_validation/` parallel dazu; das war der
  Stand vor der Konvention.)
- **Urteile folgen dem gemeinsamen Schema** aus `scripts/validation_common.py`
  (Datum · Objekt · vorhergesagt · eingetreten · Urteil · Zeitfenster) — damit
  bleiben die AUTO_REPORTs über Domänen hinweg vergleichbar.
- **Prognosen werden nicht lokal gesammelt**, sondern aus dem zentralen Freeze
  `data/weather_archive/YYYY-MM-DD.json` gelesen. Fehlt dort ein Feld, wird es
  dort ergänzt. Der Freeze ist seit 02.08. lückenlos und bewacht.
- Die Trennung zu `validation/xcontest/` bleibt strikt: eigenes Schema, kein
  Merge auf Datenebene. Querverbindungen nur **lesend** in der Analyse
  („XContest sagt 0, OGN sagt 5 Sessions à 2 h — andere Geschichte").

---

## Architektur (Ziel nach Phase 3)

```
aprs.glidernet.org ──APRS-TCP (24/7)──► ogn-collector.service   (NEU, eigener Daemon)
                                        ogn_collector.py
                                        - python-ogn-client
                                        - Server-Filter: BBox + Range
                                        - alle aircraft_type, Gleitschirm markiert
                                        - device_id NUR gehasht (Salt in config)
                                        - no-track-/stealth-Flag respektieren
                                        - Empfänger-Kennung mitschreiben
                                        - Auto-Reconnect
                                                 │ INSERT roh
                                                 ▼
                                        data/ogn_tracks.db (SQLite, WAL,
                                        Klassen-Muster wie station_observations.py)
                                          • beacons   (Rohpunkte, hochvolumig)
                                          • flights   (aggregierte Sessions)
                                          • coverage  (Empfangslage je Region)
                                                 │ täglich (Hook in scheduler.py)
                                                 ▼
                                        ogn_sessions.py
                                        - Beacons→Flüge (Gap-Split)
                                        - Startpunkt→Spot/Region
                                        - Steig-Aggregate, max Höhe, AGL, Airtime
                                        - Empfangs-Kennzahlen je Region fortschreiben
                                        - Roh-Beacons prunen (> Retention)
                                                 │
                                                 ▼
                                        validation/ogn/  (Hausordnung, s.o.)
                                        - liest data/weather_archive/
                                        - Urteile im gemeinsamen Schema
```

### Bausteine

**1. `ogn_collector.py` — Daemon (`ogn-collector.service`)**
- `python-ogn-client` (`ogn.client.AprsClient` + `parse`).
- **Server-seitiger APRS-Filter** (BBox + Range) — Volumen runter, bevor es ankommt.
- Speichert **alle** `aircraft_type` (Gleitschirm markiert), damit Delta/Segelflug
  als Vergleichsbasis dienen.
- **`device_id` wird beim Eintreffen gesalzen gehasht.** Für „wie viele
  verschiedene Geräte" reicht das vollständig — und es nimmt der
  No-Track-/Datenschutzfrage die Schärfe, ohne etwas zu kosten.
  **Der Salt wird einmal gesetzt (`config`) und nie rotiert.** Ein Wechsel
  macht dasselbe Gerät zu zwei Geräten und zerstört rückwirkend jede
  Geräte-Zählung. Gehört in die Betriebs-Doku, nicht nur in den Code.
- Respektiert das No-Track-/Stealth-Flag **beim Eintreffen**, nicht erst in der
  Anzeige.
- **Empfänger-Kennung wird mitgeschrieben** — Grundlage der Empfangs-Messung.
- Auto-Reconnect (sonst Datenloch). systemd nach Vorbild `wingcast.service`,
  aber **entkoppelt** vom Webserver: `Restart=always`, `RestartSec=10`.

**2. `data/ogn_tracks.db` — SQLite (`_connect()`, WAL, `data/*.db`)**
- `beacons`: `device_hash, ts, lat, lon, alt_m, climb_rate, aircraft_type, receiver`.
- `flights`: `device_hash, date, launch_lat, launch_lon, launch_spot_id, region_id,
  takeoff_ts, landing_ts, duration_min, max_alt_m, max_height_agl_m,
  **climb_p75, climb_max**, aircraft_type`.
  → Die Steig-Aggregate fehlten im alten Plan, obwohl sie der Hauptzweck sind.
- `coverage`: je Region und Tag — aktive Empfänger, tiefste empfangene AGL-Höhe,
  Beacon-Dichte. Die Rechengrundlage gegen den Empfangs-Bias.
- Retention: `beacons` nach Roll-up prunen; `flights` und `coverage` dauerhaft.

**3. `ogn_sessions.py` — täglicher Roll-up (Hook in `scheduler.py`)**
- Beacons pro Gerät zu Flügen gruppieren (Split bei Zeit-Gap).
- Startpunkt → Spot/Region. **Kein neues shapely nötig:**
  `scripts/validation_common.py` hat `load_region_polygons()` und
  `_point_in_poly()` bereits abhängigkeitsfrei.
- **Achtung Regionen-Umbenennung vom 10.08.2026:** ausschliesslich die neuen ids
  schreiben. Die Migration darf nie ein zweites Mal laufen.
- Steigwerte glätten, bevor aggregiert wird — Roh-Beacons enthalten auch Sinken
  zwischen den Bärten. Aggregiert wird über positive Segmente.
- Höhe über Grund braucht einen Terrain-Lookup (Quelle offen, s.u.).

**4. `validation/ogn/` — der eigentliche Zweck**
Pro Tag gegen den Prognose-Freeze:
- **Steigen/Höhe gemessen vs. vorhergesagt**, je Region — die Kalibrierung.
- **Tages-Rangvergleich der Regionen** (relativer Aktivitätsanteil, nicht
  Absolutzahlen) gegen unsere Rangliste.
- Beides nur für Regionen mit vergleichbarer Empfangslage.

---

## Phasen

### Phase 0 — Archiv-Check (zuerst, eine halbe Stunde)
Gibt es doch eine Quelle für **vergangene** Flugdaten (Tages-Flugbücher,
Dritt-Archive im OGN-Umfeld, andere Live-Tracking-Netze mit History)?

**Eine gefundene Quelle zählt nur, wenn sie alle vier Punkte erfüllt:**
1. Gleitschirm ist von Segelflug/Delta unterscheidbar.
2. Pro Flug mindestens die **maximale Höhe**; Steigwerte oder ein Höhenverlauf,
   aus dem sich Steigen ableiten lässt, sind der eigentliche Gewinn.
3. Startort genau genug für die **Regions-Zuordnung** (Koordinate oder
   eindeutiger Startplatzname).
4. Deckt **Tage ab 02.08.2026** ab — davor trägt unser Prognose-Archiv keine
   verwertbaren Bewertungen (01.07.–01.08. gar keine), ein Vergleich wäre
   gegenstandslos.

- **Alle vier erfüllt** → wir rechnen sofort gegen den Freeze, das Gate ist an
  einem Nachmittag entschieden statt in einer Saison. Der Daemon wird dann erst
  später gebaut, für den laufenden Betrieb.
- **Sonst** → Phase 1 wie geplant.

#### ERGEBNIS (geprüft 14.08.2026): keine brauchbare Archiv-Quelle

Geprüft wurden OGN FlightBook, KTrax, die OGN-IGC-Ablage, PureTrack und SkyLines:

| Quelle | Befund | Fällt raus wegen |
|---|---|---|
| **OGN FlightBook** (`flightbook.glidernet.org/api`) | Datums-Endpunkt vorhanden (`/api/logbook/<ICAO>/<date>`), liefert max. Höhe + Höhe über Grund + Dauer | **flugplatz-gebunden** (ICAO-Codes), Startplätze am Berg gibt es dort nicht; Luftfahrzeug-Klassen 1–6 ohne Gleitschirm |
| **KTrax** (`ktrax.kisstech.ch`) | inhaltlich am nächsten dran — zeigt genau unsere Felder (max. Höhe über Start, mittleres Steigen), CSV-Export tages- und jahresweise | **kostenpflichtig** (API nur für Abo-Kunden, Schlüssel auf Anfrage, max. 1 Abfrage/Minute); Gleitschirm-Filter nur für Geräte, die **im OGN-Geräteregister eingetragen** sind — freiwillig, also lückenhaft |
| **OGN-IGC-Ablage** | — | Dateien **nur 24 h** vorgehalten (Datenschutz-Policy), nur für registrierte Geräte mit gesetztem Tracking-Flag |
| **PureTrack** | bündelt OGN + XContest-Live, IGC-Download | **6 Tage** Verlauf für zahlende Nutzer, 1 Tag sonst — kein Archiv |
| **SkyLines** (`api.skylines.aero`) | offene API, 60 Abfragen/h ohne Anmeldung, Flugdatenbank mit Historie | segelflug-lastig, Gleitschirm-Abdeckung Schweiz unklar — **einziger verbliebener Gratis-Kandidat**, aber vermutlich zu dünn |

**Fazit:** Es gibt keine freie, abfragbare Vergangenheit, die unsere vier
Kriterien erfüllt. Der Grund ist strukturell: Roh-Telemetrie ist Personendaten,
und alle Betreiber löschen sie schnell oder verkaufen den Zugang.
→ **Phase 1 gilt** (selbst mitschneiden, vorwärts).

#### Direktmessung am Stream (14.08.2026, 09:21–09:24 MESZ)

Statt zu diskutieren, ob Gleitschirme im Netz sichtbar sind: 150 Sekunden am
öffentlichen APRS-Stream mitgehört, Filter 150 km um 46.8/8.2 (deckt die CH
praktisch ganz ab), 14 122 Zeilen. Gezählt wurden **eindeutige Geräte** je Typ;
Stealth-/No-Track-Geräte ausgeschlossen.

| Typ | Geräte | Höhen min/median/max (m MSL) |
|---|---:|---|
| Motorflug | 74 | 262 / 1684 / 12722 |
| Jet | 68 | 212 / 4591 / 13059 |
| unbekannt | 38 | 266 / 2518 / 64941 |
| Helikopter | 23 | 447 / 2084 / 3157 |
| **Gleitschirm** | **14** | **462 / 883 / 2491** |
| Segelflug | 12 | 362 / 1094 / 1612 |
| Delta | 1 | 2284 / 2298 / 2309 |

**Was das belegt:**
- Gleitschirme sind im Stream **klar als eigener Typ erkennbar** und in
  brauchbarer Zahl vorhanden — und zwar **um 09:21 morgens**, vor dem
  eigentlichen Thermiktag. Der Tagesspitzenwert liegt deutlich höher.
- Der Empfang reicht bis **462 m** hinunter — wir hören nicht nur die Hohen.
  (Noch MSL, nicht über Grund; die regionale Aufschlüsselung steht aus.)
- Die Restklasse „unbekannt" ist real (38 Geräte) und teils unplausibel
  (64 km Höhe) — sie taugt weder als Gleitschirm noch als sicherer Ausschluss,
  wie im Plan angenommen.

**Folge für das Gate:** Die vorgeschlagene Schwelle (≥ 5 Geräte an 8 von 15
Spots) verlangt rund 40 Geräte, regional gestreut, an einem Tag. Ob das
realistisch ist, zeigt erst eine Messung zur Tageszeit mit der meisten
Aktivität. **Die Zahlen erst danach festzurren.**

Messskript: Wegwerf-Code im Scratchpad, bewusst nicht im Repo.

**Zwei billige Nebenwege, die das Gate beschleunigen können:**
1. **KTrax anfragen** — was kostet ein Zugang, und liegt Schweizer
   Gleitschirm-Historie seit August überhaupt vor? Eine E-Mail. Wäre die
   Abkürzung, falls die Antwort gut ausfällt.
2. **Live nachschauen statt sammeln** — auf öffentlichen Kartenansichten
   (z. B. glidertracker) lässt sich am **nächsten guten Flugtag** von Hand
   abzählen, wie viele FANET-Gleitschirme in unseren Regionen überhaupt
   auftauchen. Das beantwortet die Verbreitungsfrage grob in Stunden statt
   Wochen — reicht nicht als Gate, aber als Vorentscheid, ob sich der Collector
   lohnt.

### Phase 1 — Adoptions- und Empfangs-Gate
- Nur Collector + `beacons` + `coverage`. **Kein Sessionizer, keine Validierung.**
- Ausgezählt wird an **guten Flugtagen**, nicht über Kalenderwochen — zwei
  schlechte Wochen sehen aus wie fehlende Verbreitung.
- **Zeitfenster:** Wir sind Mitte August. Entweder das Gate läuft in dieser
  Saison, oder es verschiebt sich faktisch auf 2027.
- **Das Gate braucht Zahlen** (Vorschlag, vor Start zu bestätigen). Bestanden,
  wenn **beide** Bedingungen erfüllt sind:
  - **Adoption:** über mindestens **3 gute Flugtage** an mindestens **8 der
    15 Referenz-Spots** je **≥ 5 verschiedene** Gleitschirm-Geräte.
  - **Empfang:** in **≥ 2/3 der Regionen** werden nachweislich Flüge **unter
    300 m über Grund** empfangen. Hören wir nur die hohen, sind die Steig- und
    Höhenwerte systematisch geschönt und regional unvergleichbar.

  Wird das verfehlt: **Stopp**, Erkenntnis dokumentieren, kein Weiterbau.
  Ein Gate ohne Zahl geht immer auf.

**Die beiden Begriffe im Gate, damit sie nicht auslegbar sind:**
- **„gute Flugtage"** — wird **nicht** aus unserer eigenen Prognose bestimmt,
  sonst messen wir uns selbst. Definition: ein Tag zählt, wenn
  `validation/xcontest/_raw/strong_flights_*.tsv` an ihm Flüge ≥ 60 km aus
  **mindestens 3 verschiedenen Regionen** ausweist. Unabhängige Beobachtung,
  liegt bereits im Haus. Fehlt der Paste für den Tag, ersatzweise über
  SwissMetNet: trocken und Böen unter Schwelle in der Mehrheit der Regionen.
- **„15 Referenz-Spots" — regional gestreut, nicht die Top 15 insgesamt.**
  Eine reine Bestenliste würde sich in drei, vier starken Regionen ballen und
  die Verbreitung nur dort messen, wo ohnehin viel läuft. Stattdessen:
  **pro Region der meistbeflogene Startplatz**, aus den 15 aktivsten Regionen
  laut `validation/xcontest/_raw/strong_flights_*.tsv` der Saison 2026 — also
  15 Spots aus 15 verschiedenen Regionen.
  Wird beim Gate-Start **einmal festgeschrieben** und danach nicht mehr
  angepasst.

  **Grenze, die man kennen muss:** In sehr flugschwachen Regionen ist auch der
  beste Startplatz dünn. Fällt das Gate dort durch, sagt das nichts über die
  Tracker-Verbreitung, sondern nur über die allgemeine Aktivität. Regionen ohne
  ausreichende Grundaktivität in der Referenz-Saison bleiben deshalb ausserhalb
  der 15 — sie sind an dieser Frage schlicht nicht messbar.

### Phase 2 — Sessionizer + Spot/Region-Zuordnung
- `ogn_sessions.py`, `flights`-Tabelle inkl. Steig-Aggregaten, Retention/Pruning.

### Phase 3 — Validierungs-Ebene
- `validation/ogn/` nach Hausordnung, Hook im Scheduler wie die anderen Domänen
  (morgens für den Vortag, failure-tolerant, `--backfill`-fähig).
- Später, wenn eine Saison Daten liegt: absoluter Aktivitäts-Normalwert je
  Region und Wochentag.

---

## Vorab-Entscheidungen (vor Phase 1 nötig, nicht erst vor Phase 2)

Die ersten drei betreffen das, was der Collector schreibt — sie können nicht
warten, denn Phase 1 schreibt bereits Rohdaten.

1. ✅ **Geografischer Scope:** 150 km um 46.8/8.2, serverseitig gefiltert.
2. ✅ **Retention Rohpunkte: 7 Tage** (17.08.). Die Volumenschätzung, auf der
   die ursprüngliche 30-Tage-Wahl beruhte, war dreimal zu tief — und
   weggeworfen wird nur, was verdichtet ist. Siehe „Aufbewahrung" oben.
3. ⬜ **Gate-Zahlen:** Vorschlag oben bestätigen oder ersetzen.
4. ✅ **Gap-Schwelle Sessionizing: 300 s**, an echten Daten abgelesen.
5. ✅ **Terrain-/AGL-Quelle:** Open-Meteo-Elevation mit eigenem Raster-Cache
   (kein SRTM-Download, keine neue Abhängigkeit).
6. ⬜ **No-Track-Policy:** intern reicht das Respektieren des Flags plus Hashing;
   bei späterer öffentlicher Nutzung rechtliche Lage prüfen.

---

## Touch-Points
- ✅ `ogn_collector.py` — Daemon
- ✅ `ogn-collector.service` — systemd-Unit (entkoppelt von `wingcast.service`)
- ✅ `data/ogn_tracks.db` — SQLite, Tabellen `beacons`, `flights`, `coverage`,
  `terrain` (server-lokal, gitignored)
- ✅ `ogn_sessions.py` — Roll-up, Hook in `scheduler.py._daily_run`
- ✅ `tests/test_ogn_sessions.py` — hält die drei gefundenen Defekte fest
- ⬜ `validation/ogn/` — README + SCHEMA + PATTERNS + AUTO_REPORT nach Hausordnung
- ~~`requirements.txt` — `ogn-client` ergänzen~~ — **entfällt**: das APRS-Format
  wird direkt gelesen, keine neue Abhängigkeit.

## Änderungen gegenüber der Fassung vom 14.06.2026
- Empfangs-Abdeckung als zweite, regional strukturierte Verzerrung aufgenommen;
  `coverage`-Tabelle und Messung ab Tag 1 ergänzt.
- Hauptzweck von „Fehlalarm-Jagd bei `not_safe`" auf **Steig-/Höhen-Kalibrierung**
  verschoben. Dass jemand geflogen ist, widerlegt keine Sicherheitswarnung —
  Leute fliegen auch bei Grenzbedingungen.
- Flugzahlen als Bewertungsmassstab verworfen (Wochentag, Ferien, Zirkularität
  über die Prognose); stattdessen Regionen-Vergleich innerhalb desselben Tages.
- `climb_p75` / `climb_max` in `flights` ergänzt (fehlten, obwohl Hauptzweck).
- Zielort auf `validation/ogn/` korrigiert (Hausordnung seit 03.08.), gemeinsames
  Urteils-Schema und zentraler Prognose-Freeze verbindlich gemacht.
- Gate mit Zahlen versehen und auf gute Flugtage statt Kalenderwochen bezogen;
  Saison-Fenster benannt.
- Entscheidungen zu Scope/Retention/Gate von „vor Phase 1" auf „vor dem ersten
  geschriebenen Rohdatensatz" vorgezogen.
- Phase 0 (Archiv-Check) neu vorangestellt.
- `device_id` wird gehasht; Empfänger-Kennung wird mitgeschrieben; shapely
  entfällt (`validation_common.py` kann es bereits); Hinweis auf die neuen
  Regions-ids seit 10.08.
- Nachgeschärft am 14.08.: „gute Flugtage", „15 Referenz-Spots" und die
  Empfangs-Schwelle sind jetzt definiert statt auslegbar; Phase 0 hat
  Annahme-Kriterien; Salt-Rotation als Fallstrick festgehalten.
- Referenz-Spots auf **regionale Streuung** umgestellt (ein Spot je Region statt
  Top-15-Bestenliste) — eine Bestenliste hätte in wenigen starken Regionen
  geballt und die Empfangsfrage, die regional ist, gar nicht geprüft.
