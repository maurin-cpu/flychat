# Plan: Binärer Thermik-Entscheid statt regionaler Feinabstufung

**Stand:** 2026-07-26 · **Status:** Befundlage belegt, **Umsetzung nicht gestartet** · **Betroffener Code:** `skills/shared/de/04_flyability/`, `docs/RATING_ARCHITECTURE.md`, `scripts/validate_climb_onesided.py`, Frontend-Darstellung der Regions-Thermik · **Ground Truth:** `validation/xcontest/`

**Wiederaufnahme (HIER starten):**
1. Diese Datei lesen, dann `validation/xcontest/2026-07-26_ANALYSE_49_TAGE.md` und `PATTERNS.md` I-016.
2. **Eiserne Regel** wie in den anderen Plänen: keine Schwelle von Hand setzen — jede Schwelle gegen `validation/xcontest/` kalibrieren. Unsere Steigskala liegt faktisch zwischen 1.5 und 3.1 m/s; jede intuitiv gesetzte Schwelle über 3.0 schaltet ein Feature faktisch ab.
3. **Gotcha, der schon zweimal zugeschlagen hat:** Der `regions`-Block im Archiv nutzt sanitisierte Keys (`berner_oberland`, `alpstein`), die Flugdaten die rohe `analyse_region` (`Berner Oberland`, `Alpstein / Ostschweiz`). Direkter Vergleich liefert stille Nulltreffer. Immer über ein Loose-Mapping (Unterstrich→Leerzeichen, `ae/oe/ue`→`a/o/u`, Präfixabgleich) gehen. Vgl. Spot-Namen-Sanitize-Gotcha.
4. Reihenfolge: **PA zuerst** — ohne die Code-Analyse ist der Umfang von P1 nicht bestimmbar. Danach P1 (Produktaussage ehrlich machen). **P0 ist Voraussetzung für die Nachjustierung**, nicht für P1.

---

## Worum geht es?

Die Validierung über 49 Tage (18.05.–25.07.2026, ~500 Regionstage mit realen XContest-Flügen) hat gezeigt:

> Unsere **regionale Feinabstufung der Thermik trägt kein Signal** — die Rangfolge der Regionen trifft nicht besser als Zufall. Der **grobe Binärentscheid auf dem Rating trägt Signal** — Faktor 2.4× bis 4×.

Konsequenz: Wir behaupten heute eine räumliche Auflösung, die die Daten nicht hergeben. Der Plan macht die Produktaussage deckungsgleich mit der Beleglage — nicht mehr, aber auch nicht weniger.

**Kernaussage im Produkt künftig:** Eine Region hat an einem Tag entweder gute Bedingungen (man fliegt) oder nicht (man fliegt tendenziell weniger). Keine Rangliste der 23 Regionen.

---

## Befundlage (belegt, nicht vermutet)

**Was nicht trägt** — Perzentil-Rang bewiesen guter Regionen in unserer Tagesrangliste, 233 Fälle (`scripts/validate_climb_onesided.py`):

| Ranking-Grösse | Median-Perzentil | Klassen-Lift oben |
|---|---|---|
| unser Steigen | 52 % (Zufall) | 0.97 |
| max. Thermikhöhe | 57 % (schlechter) | 0.78 |
| produktive Thermikstunden | 48 % | 1.00 |
| *wenig Böen (Kontrolle)* | *39 %* | *1.23* |
| *wenig Regen (Kontrolle)* | *39 %* | *1.13* |

Robust gegen alle geprüften Einwände: identisch bei Masse statt Einzelflug (Median aller Flüge, ≥3 Flüge >60 km → 52–57 %), identisch in grober Klassenlogik statt feiner Rangfolge, identisch bei 60 km und 100 km Messlatte, unverändert nach Ausschluss dünner Tage.

**Warum die Feinabstufung nicht tragen kann:** Spannweite Steigen über alle Regionen 0.92 m/s pro Tag, nur 3 unterscheidbare Klassen im 0.5-m/s-Raster, 91 % der Regionen haben einen Nachbarn näher als 0.1 m/s. Ein Rangschritt trennt 0.04 m/s.

**Was trägt** — Rate bewiesen guter Regionstage, 37 Tage mit Rating (18.05.–30.06.):

| Gruppe | Regionstage | ≥ 60 km geliefert | ≥ 100 km |
|---|---|---|---|
| `experience_rating` 4–5 | 506 | **23 %** | **16 %** |
| `experience_rating` 1–3 | 456 | 10 % | 4 % |
| `streckenflug_rating` 4–5 (bester Spot) | 97 | **41 %** | **23 %** |
| `streckenflug_rating` 0 | 250 | 7 % | 3 % |

**Nicht bloss Tageseffekt** — derselbe Vergleich innerhalb desselben Tages, Regionen gegen Regionen: 4–5 liefert 21 % vs. 1–3 mit 13 % (≥60 km); bei ≥100 km 15 % vs. 5 %. Das ist echte räumliche Trennschärfe.

**Feinstufung rechtfertigt genau diesen Schnitt:**

| Rating | geliefert ≥60 km | Median-Bestleistung |
|---|---|---|
| 1 | 11 % | 42 km |
| 2 | 3 % | 13 km |
| 3 | 8 % | 31 km |
| 4 | 17 % | 43 km |
| 5 | **31 %** | **75 km** |

Die untere Hälfte ist nicht monoton (1 liefert mehr als 3) — Stufen 1–3 tragen keine verwertbare Information und gehören zusammengefasst. Oben ist der Sprung real: 5 ist rund doppelt so gut wie 4.

**Warum der Binärentscheid funktioniert, wo die Steigrate versagt:** `experience_rating` ist laut `docs/RATING_ARCHITECTURE.md` die **Fliegbarkeits**-Achse, nicht die Thermik-Achse — es enthält Wind und Regen, also genau die Felder, die nachweislich trennen. Plus: zwei Klassen statt 23 Ränge behaupten keine Auflösung, die nicht da ist.

---

## Entscheidung

1. **Binär kommunizieren:** `experience_rating` 4–5 = gute Bedingungen, 1–3 = eingeschränkt. Keine regionale Thermik-Rangfolge mehr.
2. **Rating 5 gesondert behandeln** — substanziell besser als 4, rechtfertigt eine eigene Aussage.
3. **Nicht „Thermik-Boost" nennen.** Der Indikator misst Fliegbarkeit (Thermik *plus* Wind *plus* Regen), nicht Thermikstärke. Ein windiger Tag mit starker Thermik fällt korrekt auf „eingeschränkt" — als Thermikaussage wäre das falsch etikettiert. Vorschlag: *„gute Bedingungen" / „eingeschränkt"*, Wording final mit Produkt.
4. **Wind und Regen weiter fein ausweisen** — dort tragen die Daten die Auflösung.

---

## PA — Umfassende Code-Analyse (erster Schritt, blockiert P1)

**Ohne diesen Schritt wird P1 unvollständig.** Das Rating steckt an deutlich mehr Stellen als in den Skills — es wird angezeigt, sortiert, gefiltert, in Sterne gemappt, per localStorage persistiert und ins E-Mail-Briefing gerendert. Erst wenn die vollständige Liste steht, ist der Umfang von P1 bestimmbar und schätzbar.

**Liefergegenstand:** Änderungsliste pro Fundstelle mit Klassifikation *(muss binär / bleibt fein / entfällt / Migration nötig)* und Aufwandsschätzung. Erst danach P1 planen.

### Bekannte Anknüpfpunkte — Startliste, ausdrücklich nicht abschliessend

| Bereich | Fundstelle | Was zu klären ist |
|---|---|---|
| **Briefing-Filter** | `static/js/briefing.js:63` — `LS_MIN_RATING_KEY = "wingcast.briefing.minRating6"`, Filterlogik ab Z. 235 / 886 / 1079, Reset Z. 2294 | Nutzer filtert heute auf einer 1–5-Skala. Wird der Filter binär, ändert sich seine Semantik. **Migration nötig:** es existiert bereits eine Legacy-Kette (v1.4 `minRating10` 0–10 → v2.0 `minRating6` 0–6, Z. 64/144) — eine dritte Migration muss sauber aufgesetzt werden, sonst sitzen Bestandsnutzer auf einem Filterwert, den es nicht mehr gibt. |
| **E-Mail-Briefing** | `email_service.py:76` (Rating→Sterne), `:82` `_rating_display`, `:88` `_rating_for_spot`, `:403` Tier-Ableitung, `:404` `has_violet` bei `>= 5` | Sterne-Darstellung und Tier-Logik hängen direkt an der Feinstufung. |
| **Regions-Karte** | `static/js/region-map.js:662` (Deep-Link), `:707` `entries.sort(b.rating - a.rating)` | **Das ist die regionale Rangfolge in Reinform** — genau die Aussage, die der Befund nicht deckt. Kernkandidat für den Umbau. |
| **Spot-Karte** | `static/js/map.js:261` — Rating-Ziffer 1–6 im Marker | Kommentar nennt noch 1–6, Architektur ist 1–5. Bei der Gelegenheit prüfen. |
| **Analyse-Ansicht** | `static/js/analysis-view.js:586` — `experience_rating`-Feld | Debug/Admin-Sicht, vermutlich „bleibt fein". |
| **Rating-Erzeugung** | `engine/analyzers.py:2053` — Kopplung `experience_rating <= 2 && sf["rating"] > 2` | Bestehende Querlogik zwischen Fliegbarkeit und Streckenflug; muss zur Binärlogik passen. |
| **Skills** | `skills/shared/de/04_flyability/00_template_region.md`, `04_flight_subratings_region.md`, ggf. `02_flyability_rules.md` | Formulierungen, die regionale Feinabstufung suggerieren. |
| **Snapshot/Export** | `scripts/snapshot_weather.py:254`, `scripts/xc_aggregate.py:177/296/299` | Archivformat **nicht** verändern — die Validierung braucht die Feinstufen weiter. Nur die Darstellung wird binär. |
| **Doku** | `docs/RATING_ARCHITECTURE.md`, `docs/RATING_CONCEPT.md`, `docs/RATING_FARBKONZEPT.md`, `docs/FLYABILITY_TIER_LOGIK.md` | Farb- und Tier-Konzept hängt an 1–5. |
| **i18n** | `i18n.py`, englische Skills | Vgl. `docs/ENGLISCH_LOKALISIERUNG_PLAN.md`. |

### Scoping-Frage, die die Analyse zwingend beantworten muss

**Der Befund ist auf Regionsebene erhoben, nicht auf Spot-Ebene.** Validiert wurde die regionale Thermik-Rangfolge. Ob das Spot-Rating und der Spot-Filter im Briefing ebenfalls zusammengefasst gehören, ist mit diesen Daten **nicht** belegt — auf Spot-Ebene schlägt die 0-Launch-Regel viel härter zu (Pilotendichte, Erreichbarkeit), eine saubere Prüfung bräuchte einen eigenen Test.

Vorschlag zur Entscheidung in PA: **Umbau zunächst nur auf Regionsebene**, Spot-Rating bleibt unangetastet, bis dafür eine eigene Beleglage existiert. Sonst weiten wir einen belegten Befund auf einen unbelegten Bereich aus — genau der Fehler, der bei I-017 schon einmal passiert ist.

### Vorgehen

1. Vollständige Fundstellen-Suche über Backend, Frontend, Skills, Doku, Tests, E-Mail — die Tabelle oben als Startpunkt, nicht als Ergebnis.
2. Jede Fundstelle klassifizieren: *muss binär / bleibt fein / entfällt / Migration nötig*.
3. Region-vs-Spot-Scoping entscheiden und im Plan festhalten.
4. Migrationspfad für den Briefing-Filter festlegen (Bestandsnutzer mit gespeichertem `minRating6`).
5. Erst dann P1 mit definiertem Umfang aufsetzen.

---

## P0 — Datenbasis reparieren (Voraussetzung für Nachjustierung)

Ohne P0 lässt sich die Schwelle nicht sauber nachziehen; P1 blockiert es nicht.

**P0.1 — Regions-Level-Matching (grösster Hebel, rein technisch)**
Heute werden 58 % der XContest-Flüge einem Spot zugeordnet. Auf Regionsebene — die einzige Ebene, die die Auswertung braucht — sind Namen toleranter auflösbar: mehrdeutige Namen, deren Kandidaten alle in derselben Region liegen, werden eindeutig. Gemessener Gewinn: **+756 Zeilen, Abdeckung 58 % → 76 %**. Gewonnen u. a. Brunni (139), Amisbühl (104), Cimetta (58), Jaman (57), Niederbauen (47), Montoz (31), Moléson (29).
Umsetzung: Loose-Normalisierung (Unterstrich/Bindestrich/Leerzeichen vereinheitlichen, `ae/oe/ue`→`a/o/u`, Klammer- und Höhenzusätze strippen, Präfixabgleich für XContest-Abschneidungen inkl. `…`). Als `scripts/match_launch_region.py` mit Testfällen, dann in `validate_climb_onesided.py` einhängen.

**P0.2 — Fehlende Startplätze nacherfassen (~15)**
853 Zeilen (20 %) haben gar keinen Kandidaten im Bestand — kein Matching kann das heilen. Priorität nach Fluganzahl: Mentschelen (58), **Leysin** (47), Grandvillard (34), **Gornergrat** (34), Le Cernil (29), Caquerelle (29), Balderen (22), Niederwil (20), Gnipen (19). Wichtig, weil die Lücken regional clustern (Caquerelle = Jura — ausgerechnet die Region im Zentrum des Befunds).
Rest: 98 Zeilen echt mehrdeutig (v. a. „Scheidegg" — Rigi-Scheidegg und Alp Scheidegg liegen in verschiedenen Regionen), 61 Zeilen ohne Startplatzangabe in der Quelle.

**P0.3 — Juli-Rating-Lücke schliessen**
Alle 24 Archivtage ab 01.07. haben leeren `spots[*].analysis` und keinen `regions[*].experience_rating` — der LLM-Pass läuft asynchron nach dem Wetter-Run (I-015). Damit ist der Binärentscheid für Juli nicht validierbar. Klären, ob der Snapshot-Zeitpunkt verschoben oder der Snapshot nachgezogen werden kann.

**P0.4 — Tagesbilanz für alle Archivtage, auch die Nullflug-Tage**
Der aktuelle Datensatz enthält **nur Tage, an denen geflogen wurde** — 34 von 49 Tagen lieferten ohnehin ≥100 km. Ein Ja/Nein-Entscheid wird aber vor allem daran gemessen, ob er das **Nein** trifft, und genau diese Tage fehlen. 11 der 60 Archivtage haben keine Flugdaten (22.05., 23.05., 09.06., 20.06., 29./30.06., 01.07., 04.07., 15.07., 17.07., 21.07.) — unbekannt, ob dort niemand flog oder nur nichts erfasst wurde.
Umsetzung: pro Tag **eine Zahl** nacherfassen (nationale Flugzahl + Tagesbestleistung), für alle 60 Tage. Kleiner Aufwand, ohne den bleibt jede Trefferquote geschönt.

---

## P1 — Binärentscheid im Produkt (setzt PA voraus, unabhängig von P0)

> Umfang wird erst durch PA bestimmt. Die folgenden Punkte sind der bekannte Kern, nicht die vollständige Liste.

**P1.1** Schwelle als benannte Konstante an einer Stelle definieren (nicht in Skills verstreut), Default 4.
**P1.2** Regions-Skills auf Binäraussage umstellen: `skills/shared/de/04_flyability/00_template_region.md` und `04_flight_subratings_region.md`. Formulierungen entfernen, die eine regionale Thermik-Rangfolge suggerieren.
**P1.3** Frontend: Regions-Thermik nicht mehr als abgestufte Zahl darstellen. Wind/Regen bleiben fein.
**P1.4** Rating 5 als eigene Stufe im Wording ausweisen.
**P1.5** Englische Entsprechungen mitziehen (vgl. `docs/ENGLISCH_LOKALISIERUNG_PLAN.md`).
**P1.6** Briefing-Filter umstellen inkl. **Migration bestehender `minRating6`-Werte** aus localStorage (`static/js/briefing.js`) — Bestandsnutzer dürfen nicht auf einem toten Filterwert sitzen bleiben.
**P1.7** E-Mail-Briefing nachziehen (`email_service.py`: Sterne-Mapping, Tier-Ableitung, `has_violet`).
**P1.8** Regions-Sortierung in `static/js/region-map.js:707` auflösen oder auf die Binärgruppen umstellen — das ist die regionale Rangfolge, die der Befund nicht deckt.
**P1.9** Doku nachziehen: `docs/RATING_ARCHITECTURE.md`, `RATING_CONCEPT.md`, `RATING_FARBKONZEPT.md`, `FLYABILITY_TIER_LOGIK.md`.

---

## P2 — Validator-Verankerung

Lehre aus dem Synoptik-Zonen-Projekt: **Skill-Regeln ohne Validator-Verankerung werden verletzt.** Also nicht nur Prompt-Text ändern, sondern einen Code-Check ergänzen, der eine regionale Thermik-Feinabstufung in der Ausgabe erkennt und fehlschlagen lässt. Plus Regressionstest auf die Binärlogik.

---

## P3 — Re-Validierung nach P0

Nach P0 die Auswertung erneut fahren und die Schwelle **aus den Daten** nachziehen statt zu setzen. Dann auch beantwortbar:
- Trägt der Binärentscheid auch die Nein-Seite (P0.4)?
- Hält er im Juli (P0.3)?
- Verschiebt sich der Schnittpunkt bei 76–90 % Datenabdeckung (P0.1/P0.2)?

---

## Abgrenzung — was dieser Plan NICHT tut

Er macht die **Aussage ehrlich**, er **repariert die Prognose nicht**. Zwei Defekte bleiben offen und gehören in die bestehenden Pläne:

1. **Räumlich:** Unsere Steigprognose folgt im Wesentlichen der Geländehöhe (rho +0.72 zwischen mittlerer Starthöhe und mittlerer Steigprognose der Region). Das Streckenpotenzial folgt der Geländeform — der Jura hat mit 1183 m die tiefsten Startplätze und real schwächere Thermik, liefert aber wegen der geraden Kammlinie 300-km-Flüge. Möglicherweise prognostizieren wir korrekt, nur die falsche Grösse. → `PLAN_potential_flight_distance.md`
2. **Zeitlich innerhalb einer Region:** Auch dort, wo der Geländeeffekt entfällt, trennt die Prognose nur schwach zwischen guten und schlechten Tagen (Median rho +0.14 über 21 Regionen, 6 davon negativ). Das ist eine echte Prognoseschwäche. → `PLAN_thermikmodell_optimierung.md`

Nicht beantwortbar bleibt vorerst, ob unsere **absoluten Steigwerte** der Höhe nach stimmen: XContest-IGC-Daten sind zugangsgeschützt, wir sehen nur Distanzen. Unbeantwortet, nicht negativ beantwortet.

---

## Werkzeuge

| Zweck | Datei | Status |
|---|---|---|
| Einseitiger Perzentil-Test + Kontrolle | `scripts/validate_climb_onesided.py` | vorhanden |
| Rang-Korrelation, Niveau-Prüfung | `scripts/validate_climb_vs_xcontest.py` | vorhanden — rohe Rang-Korrelation verletzt die 0-Launch-Regel, nicht zitieren |
| observations.csv aus Starkflug-Tabelle | `scripts/build_observations_from_strong.py` | vorhanden |
| Regions-Level-Matching | `scripts/match_launch_region.py` | **P0.1, zu erstellen** |
| Binärtest auf dem Rating | `scripts/validate_rating_binary.py` | **zu erstellen** (Prototyp existiert nur im Scratchpad) |
| Within-Region-Zeitreihentest | `scripts/validate_within_region.py` | **zu erstellen** (Prototyp existiert nur im Scratchpad) |

**0-Launch-Regel** (gilt für jede Auswertung hier): Wenige oder keine Flüge ab Spot X ≠ Spot war schlecht. Zulässig ist nur *weite Flüge ab X ⇒ X war gut*. Alle Raten in diesem Plan sind Untergrenzen, keine Wahrscheinlichkeiten.
