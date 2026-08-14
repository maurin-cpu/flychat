# Plan: OGN-Validierung — Real-Flug-Belege über OpenGliderNetwork

**Status:** Mitschnitt gebaut und lokal am Livestrom verifiziert, **noch nicht
auf dem Server in Betrieb**. Auswertung (Phase 2/3) nicht begonnen.
**Erstellt:** 2026-06-14 · **Überarbeitet:** 2026-08-14 (Methodik + Hausordnung)
**Branch:** `main` (Single-Branch-Workflow)

## Umsetzungsstand (14.08.2026)

**Entschieden:** nur Gleitschirm (Typ 7) und Delta (Typ 6) mitschreiben ·
Rohpunkte **30 Tage** halten · Umkreis **150 km um 46.8/8.2** (deckt die CH ab,
in der Messung bestätigt).

**Gebaut:** `ogn_collector.py` + `ogn-collector.service`. Ohne neue Abhängigkeit
— das APRS-Format wird direkt gelesen, verifiziert gegen echte Rohzeilen.
Geräte-Kennung nur als Hash (Salt in `data/ogn_salt.txt`, gitignored, darf nie
wechseln), Stealth-/No-Track-Geräte werden beim Eintreffen verworfen.

**Offen:** Inbetriebnahme auf dem Server, danach Phase 2 (Flüge bilden) und
Phase 3 (Auswertung).

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
2. Es ist noch **kein Code geschrieben**: weder `ogn_collector.py`, noch
   `data/ogn_tracks.db`, noch `validation/ogn/`.
3. Einstieg ist **Phase 0 (Archiv-Check)** — eine halbe Stunde Recherche, die
   den ganzen Zeitplan umwerfen kann.
4. Vor Phase 1 müssen die **Vorab-Entscheidungen** getroffen sein (Scope,
   Retention, Gate-Zahlen). Nicht raten, nicht überspringen.

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

1. **Geografischer Scope:** ganze CH oder nur unsere Spot-Regionen?
2. **Retention Rohpunkte:** 7 / 14 / 30 Tage? (Der Host hat knappen RAM, 2 GB
   Swap nachgerüstet; Beacon-Volumen wächst schnell.)
3. **Gate-Zahlen:** Vorschlag oben bestätigen oder ersetzen.
4. **Gap-Schwelle Sessionizing:** ab welcher Beacon-Lücke gilt ein Flug als
   beendet? (vor Phase 2)
5. **Terrain-/AGL-Quelle:** vorhandenes Spot-Terrain wiederverwendbar oder SRTM
   nachrüsten? (vor Phase 2)
6. **No-Track-Policy:** intern reicht das Respektieren des Flags plus Hashing;
   bei späterer öffentlicher Nutzung rechtliche Lage prüfen.

---

## Touch-Points (neu anzulegen, noch nichts davon existiert)
- `ogn_collector.py` — Daemon
- `ogn-collector.service` — systemd-Unit (entkoppelt von `wingcast.service`)
- `data/ogn_tracks.db` — SQLite (Wrapper im Stil `station_observations.py`)
- `ogn_sessions.py` — Roll-up, Hook in `scheduler.py`
- `validation/ogn/` — README + SCHEMA + PATTERNS + AUTO_REPORT nach Hausordnung
- `requirements.txt` — `ogn-client` ergänzen

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
