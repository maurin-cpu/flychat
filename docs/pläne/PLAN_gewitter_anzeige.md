# PLAN Gewitter-Anzeige — Stand 2026-08-01

Arbeitsstand nach einem Tag Recherche und Messung. Alles hier ist reproduzierbar
(Skripte unten). Nächster Arbeitstag: 2026-08-02.

---

## 1. Ausgangslage — was wir heute tun

Ein Gewitter ist bei uns **allein** der WMO-Wettercode 95/96/99, dreifach
implementiert (`engine/weather_context.py:819`, `:1936`, `:3213`). Es gilt als
harte DANGER-Warnung, drückt `thunderstorm_safety_rating` auf 1 und damit über
den Weakest-Link (`engine/_common.py:466`) auf `not_safe`.

Daneben, davon getrennt und ohne Gate:
- **CAPE** als Überentwicklungs-Risiko, `CAPE_WARN_JKG = 800`,
  `CAPE_DANGER_JKG = 1500`, Deckel `CAPE_LID_CIN_JKG = 150` (`config.py:1043`)
- **ICON-CH2-EPS-Ensemble** (21 Member, nur `weather_code`), nur für Regionen,
  nur `warn`-Kachel ab 15 % (`ensemble_thunder.py`, `decision_engine.py:1072`)
- **Lifted Index** wird geholt (`GFS_SUPPLEMENTARY_PARAMS`, `config.py:343`),
  aber **nur im Thermik-Rechner** genutzt, nie für Gewitter

Regions-Aggregation seit 31.07.: schwerster Code über alle Referenzpunkte,
kein Quorum, dazu `thunder_coverage` / `thunder_class` (isolated / scattered /
widespread) — bisher nur beschreibend im Text, nicht im Gate.

---

## 2. Recherche — die belegten Kernbefunde

Details in Memory `gewitter-konkurrenz-recherche`. Kurz:

**Es gibt kaum Konkurrenz.** Meteo-Parapente, XC Therm, burnair und
Paraglidable haben **kein** Gewitterprodukt. Austro Control hat Alptherm
(halbstündliche TS-Codes pro Region) im April 2024 abgeschaltet, der Nachfolger
hat keine Gewittervariable mehr. Nur Skysight („Overdevelopment") und XC Skies
(CAPE + LI + Stufen „Likely/Possible/Scattered") machen etwas.

**Niemand nutzt Prozentzahlen.** PWC-Wettkämpfe 1/2/3, XC Skies
Likely/Possible/Scattered, DHV „evtl./einige/etliche/häufige", Austro Control
4-stufige *Prognosesicherheit* getrennt vom Ereignis, meteoblue verweigert die
Zahl definitorisch. Unsere Kachel „Gewitterrisiko 40 %" ist branchenunüblich.

**Die Szene entscheidet an der Überentwicklung, nicht am Blitz.** DHV-Lehre
(Schwaniz, DHV-info 146): Abbruch bei Cu congestus — „Jetzt sollte schon
niemand mehr in der Luft sein!" Im Segelflug gilt der **Lifted Index als
primärer Überentwicklungs-Indikator**, CAPE nur als Schwere-Indikator. Deckt
sich mit Kunz (2007, NHESS 7, 327): LI schlägt CAPE bei der binären
Gewitterfrage (HSS 0,57).

**Gefahrenzone 20–50 km, nicht Punkt.** Böenwalze bis 20 km (in Alpentälern
kanalisiert), FAA empfiehlt 32 km. Reale Vorwarnzeit 15–20 min; Wettkämpfe
stoppen 30–60 min vor der Böenfront. Radar/Blitzortung haben für Wärmegewitter
~0 Vorwarnzeit.

**Kritik, die uns trifft** (Schwaniz, DHV-info 192): automatisierte Prognosen
geben „vermeintlich punktgenau" heraus, „an solchen Tagen ist die Trefferquote
dieser Berichte gering", und sie zeigen „Unsicherheiten nicht auf".

**Methodik** (Memory-Detail in der Recherche): DWD skaliert Ensemble-
Wahrscheinlichkeiten bewusst von 2 km auf **20 km Radius** hoch. LPI aus
COSMO-D2 wird erst ab **~220 km** Skala nützlich (FSS ≥ 0,5), Ensemblespread
nur 110 km → überkonfident. CIN-Literatur: < 25 schwach, 50–100 stark, > 200
unterdrückt; Tagesgang entscheidend, Morgenwert kein Veto für den Nachmittag.

---

## 3. Datenlage — was wir haben und was nicht

**Keine freie Wahrheit. Nicht erneut anrennen.** (Memory
`gewitter-wahrheit-datenlage`)
- MeteoSchweiz Open Data: **kein Blitzdatensatz** (Kategorien A–E)
- Augenbeobachtungen A8 (~20 Standorte): Parameterliste heruntergeladen,
  27 Werte — **kein Gewitter**, nur `w3p002d0` Tag mit Hagel, Regen, Schnee,
  Nebel
- Blitzortung.org: Rohdaten nur für Betreiber einer eigenen VLF-Station
- Hagelradar D3 (POH/MESHS) wäre auf Anfrage zu haben — **vom User am
  01.08. verworfen, machen wir nicht**
- Meteomatics (St. Gallen) hätte echte Entladungen, Preis unbekannt — offen

**Was wir haben:**

| Quelle | Inhalt | Umfang |
|---|---|---|
| `data/weather_archive/*.json` | Tages-Snapshots, Spots stündlich mit `lifted_index`, `cape`, `convective_inhibition`, `weather_code` | 61 Tage, 18.05.–31.07., 621 MB, 29 555 Spot-Tage, ~384 000 Stunden |
| `data/lpi_archive/lpi_icon_d2.json` | `lightning_potential` + CAPE/CIN/Code aus **icon_d2** | 494 Spots, 01.05.–01.08., 2232 Std, 43,8 MB |

**Lücken:** Regionen haben im Archiv fast keine historischen Stundenwerte
(nur ~29 Regions-Tage) und **keinen** Lifted Index — der kommt aus einem
GFS-Call, den wir nur für Spots machen. Kalibrierung daher auf Spot-Ebene,
Übertrag auf Regionen danach.

**Dringlichkeit:** Open-Meteo hält `past_days` max. 92 Tage. Das Fenster
wandert täglich. **Ohne täglichen Mitschnitt ist jede Saison rückwirkend
verloren.** Für 2026 am 01.08. gesichert.

---

## 4. Messergebnisse

### 4.1 Wie oft feuert unser Wettercode (Archiv, 61 Tage)

- **Spots: 11,7 %** der Spot-Tage haben einen Gewittercode (3464 von 29 555),
  10 979 Gewitterstunden
- **Regionen: 0** — aber nur, weil die historischen Regions-Stundenwerte
  fehlen; dazu kam der Aggregations-Bug, der bis 31.07. den Wettercode verlor
  (Commit 47968a5). Die Beobachtung „wir zeigen nie einen Blitz" war für
  Regionen also korrekt.

### 4.2 Werteverteilung (Spots, ~384 000 Stunden)

| Wert | Median | P90 | P99 |
|---|---|---|---|
| Lifted Index | −0,7 | +4,4 (P90) / −3,6 (P10) | — |
| CAPE | 20 | 630 | 1560 |
| CIN | 0 | 53 | 184 |

**Folge:** Unser CIN-Deckel bei 150 liegt bei ~P98 — er greift in unter 2 %
der Stunden und tut praktisch nichts. `CAPE_WARN 800` ≈ P95,
`CAPE_DANGER 1500` ≈ P99.

### 4.3 Zwei-Modell-Vergleich — der zentrale Befund

`python scripts/compare_thunder_models.py`

**Auf Region+Tag (1582 Regionstage):**

| | Anteil |
|---|---|
| beide melden Gewitter | 6,6 % (104) |
| nur unser Wettercode (ICON-CH) | 13,7 % (217) |
| nur Blitzpotenzial (ICON-D2) | 7,5 % (119) |
| keiner | 72,2 % (1142) |

- Von unseren Gewitter-Regionstagen bestätigt LPI **32 %**
- Von den LPI-Regionstagen fängt unser Code **47 %**
- Anzeige heute 20,3 % → mit LPI **27,8 %** (+119 Regionstage)

**Auf Spot+Stunde (356 148 Stunden):** beide 0,02 %, nur Code 3,00 %,
nur LPI 0,35 %. Übereinstimmung 1 %. → **Punktvergleich ist aussagelos**
(double penalty), nur als Gegenprobe behalten (`--level spot`).

### 4.4 Indexwerte in LPI-Stunden vs. Rest

| | mit LPI > 0 (n=1284) | ohne (n=354 864) |
|---|---|---|
| CAPE Median | 60 | 30 |
| CIN Median | 10 | 0 |
| **Lifted Index Median** | **−2,1** | **−0,9** |

Richtung stimmt, Trennschärfe schwach — die Verteilungen überlappen stark.
LI trennt am deutlichsten, was zur Literatur passt.

**Gotcha:** LPI am Einzelpunkt ist fast immer 0. Eine Stichprobe mit nur 20
Rasterpunkten fand bloss 61 positive Stunden und liess den Mai leer erscheinen
— mit allen 494 Spots ist er vollständig da. **LPI nie am Punkt lesen.**

---

## 5. Der Vorschlag (vom User am 01.08. inhaltlich abgenommen, Bau offen)

**Aus zwei unabhängigen Modellen drei Stufen.** Die Übereinstimmung ist kein
Gütemass — sie sagt nicht, wer recht hat —, sondern ein Sicherheitsmass.

| Stufe | Bedingung | Anteil | Anzeige |
|---|---|---|---|
| **sicher** | beide melden | 6,6 % | Blitz deutlich, Fliegbarkeit sperren |
| **möglich** | nur eines meldet | 21,2 % | Blitz abgeschwächt + Text „ein Modell sieht Gewitter, das andere nicht" |
| **nichts** | keines | 72,2 % | keine Anzeige |

Löst beide Probleme: mehr Blitze als heute (20,3 % → 27,8 %) **und** sichtbare
Unsicherheit — der meistgenannte Kritikpunkt der Piloten.

### Was gebaut werden muss

1. **LPI in den Tageslauf** — zusätzlicher `icon_d2`-Abruf für die
   Region-Referenzpunkte. Ohne das gibt es keine Live-Daten, nur Archiv.
   Erledigt zugleich das Archiv-Problem aus §3.
2. **Zwei-Modell-Logik** → drei Stufen, in `engine/weather_context.py` und
   `engine/decision_engine.py`
3. **Darstellung** — Blitz voll vs. abgeschwächt in `meteogram.js`
   (`stormAt`, `web.py:4065–4189`), Kachel-Text, i18n

### Später, aus der Recherche abgeleitet, noch nicht gemessen

- Abbruchpunkt vom Blitz auf die **Überentwicklung** vorziehen, Lifted Index
  als Primärindikator (haben wir bereits im Fetch)
- **Prozent → ordinale Stufen** (branchenkonform, löst das
  Referenzklassen-Problem)
- **CIN-Deckel** auf Stundenwert umstellen, Schwelle 150 → 50–100.
  Achtung: CIN darf nur **dämpfen**, nie abschalten — in den Alpen drücken
  Talwind-Konvergenzen die Luft mechanisch durch den Deckel, und ein mittlerer
  Deckel macht das Nachmittagsgewitter *heftiger*, nicht harmloser
- `thunder_coverage` ins Gate: isolierter Einzeltreffer → `conditional`
  statt `not_safe`

---

## 6. Reproduzierbarkeit

```bash
# LPI rueckwirkend ziehen (Fenster wandert! max 92 Tage)
python scripts/fetch_lpi_archive.py
python scripts/fetch_lpi_archive.py --past-days 60

# Zwei-Modell-Vergleich
python scripts/compare_thunder_models.py                # Region+Tag (Default)
python scripts/compare_thunder_models.py --level spot   # Gegenprobe

# Bestehend, gegen MeteoSchweiz-Stationen (Wahrheit = Starkregen-Ersatz, schwach)
python scripts/validate_thunder_vs_stations.py --past-days 60
```

Beide neuen Skripte sind **uncommittet** (Stand 01.08.), ebenso
`data/lpi_archive/`.

## 7. Offene Entscheide für 02.08.

1. Zwei-Modell-Logik bauen — ja/nein
2. LPI in den Tageslauf aufnehmen (zusätzlicher API-Call pro Tag)
3. Meteomatics anfragen für echte Blitzdaten — oder dauerhaft ohne Wahrheit
   arbeiten
4. `data/lpi_archive/` committen (43,8 MB) oder ausserhalb von Git ablegen

---

# TEIL B — Stand 2026-08-02: die Anzeige ist zu laut, nicht zu leise

## 8. Korrektur an §5

**§5 war auf der falschen Quelle gemessen.** Die Zahlen aus §4.3 (Anzeige
heute 20,3 % der Regionstage, mit LPI 27,8 %) beziehen sich **allein auf den
deterministischen Wettercode** im Archiv. Der Blitz im Meteogramm hat aber
**drei** Quellen (`web.py:4171`), und im Betrieb feuert fast nur die dritte.

Gemessen am aktuellen Datenstand (`data/wetterdaten.json`, 02.08. 17:18,
29 Regionen, 137 Regionstage, 1507 Flugstunden 09–20 Uhr):

| Quelle des Blitz-Symbols | Stunden | Anteil |
|---|---|---|
| nur Ensemble (ICON-CH2-EPS) | 215 | 99,1 % |
| nur Wettercode | 1 | 0,5 % |
| beide | 1 | 0,5 % |

**217 Blitzstunden auf 36 % aller Regionstage.** Der deterministische Code,
um den sich die ganze Messung vom 01.08. drehte, ist für Regionen praktisch
stumm (2 von 1507 Stunden). Die Richtung „wir zeigen zu wenig" gilt damit
**nur für Spots**, nicht für Regionen. Für Regionen gilt das Gegenteil.

## 9. Warum es „Blitz ohne Wolke" gibt — drei Mechanismen

**(a) Ein Tageswert wird auf Stunden gemalt.** `probability_pct` ist der
Anteil der 21 Member, die **irgendwann** zwischen 09 und 20 Uhr an
**irgendeinem** der 16 Referenzpunkte zünden (`ensemble_thunder.py:133`).
Diese Grösse ist im Sommer nahezu gesättigt — **Median über alle Blitzstunden:
95 %**. Liegt sie über 50 %, bekommt das komplette Schwerpunktfenster einen
Blitz, und das Fenster umfasst alle Stunden mit mindestens der *halben*
Spitzenzustimmung. **53 der 217 Blitzstunden entstehen allein so.**

**(b) Nichts prüft die Stunde selbst.** Das Ensemble kennt nur Wettercodes.
Bewölkung, Niederschlag und CAPE derselben Stunde stammen aus dem
deterministischen Lauf und werden **nie gegengelesen**. Die beiden müssen sich
nicht einig sein — und sind es meist nicht:

| Prüfung an den 217 Blitzstunden | Anteil |
|---|---|
| kein Niederschlag (< 0,1 mm) | 85 % |
| Bewölkung < 50 % | 53 % |
| tiefe Bewölkung < 30 % | 74 % |
| **trocken UND < 50 % Bewölkung** | **50 %** |

Beispiele: Tessin Zentral 04.08. 14:00 — Blitz bei **2 % Bewölkung, 0 mm
Regen**. Rheintal 04.08. 11:00 — Blitz bei **0 % Bewölkung**. Waadtländer
Alpen 04.08. 11:00 — Blitz bei 7 % Bewölkung und CAPE 150.

**(c) Kein Quorum über die Fläche.** Der Regions-Wettercode ist der schwerste
Code über alle 16 Referenzpunkte ohne Mindestanzahl (`fetch_weather.py:542`).
`thunder_coverage` wird bereits berechnet, ist aber rein beschreibend. Heute
kaum sichtbar (2 Stunden, beide `isolated`), wird aber sofort relevant, sobald
der Code wieder greift.

**Nebenbefund:** Der Ensemble-Blitz ist laut, hat aber **keine Konsequenz** —
er steuert nur das Symbol, nicht das Flugsicherheits-Rating. Sperren tut nur
der Wettercode. Symbol und Bewertung erzählen heute zwei Geschichten.

## 10. Zielbild

Vorgabe des Users (02.08.): **Der laute Blitz muss selten und belastbar
sein** — so zurückhaltend, wie MeteoSchweiz eine feste Gewittergefahr
ausgibt. Unsicherheit gehört sichtbar, aber leise.

Das dreht die Rolle der Zwei-Modell-Logik aus §5 um: Übereinstimmung dient
**nicht** dazu, mehr Blitze zu zeigen, sondern dazu, die **harte** Stufe zu
verdienen. Der zweite Kanal wird zum Filter, nicht zum Verstärker.

Wichtig zur Datenlage: Wir haben von DWD (ICON-D2) und MeteoSchweiz
(ICON-CH1/CH2/CH2-EPS) **Modelle**, keine amtlichen Warnungen und keine
Blitzmessung. Zwei Modellfamilien ersetzen keine Wahrheit — sie machen nur
Uneinigkeit sichtbar.

## 11. Der Plan — fünf Schritte, nach Hebelwirkung sortiert

Alle Zahlen gemessen am aktuellen Bestand, Nenner 137 Regionstage.

### Schritt 1 — Stundenwahrheit statt Tageswert
Die Füllung des Schwerpunktfensters aus `probability_pct` entfällt
(`web.py:4107–4117`). Das Symbol kommt nur noch aus dem **stündlichen**
Member-Anteil. Der Tageswert bleibt für den **Text** erhalten
(„Gewitterneigung am Nachmittag") — dort ist eine Tagesaussage richtig, am
Stundensymbol ist sie falsch.
→ 217 auf **164 Stunden**, 36 % auf **31 % der Regionstage**.

### Schritt 2 — Plausibilitätsanker: kein Blitz ohne Konvektionssignatur
Ein Blitz erscheint nur, wenn der deterministische Lauf in **derselben
Stunde** überhaupt etwas zeigt: (Niederschlag ≥ 0,1 mm **oder** Bewölkung
≥ 50 %) **und** CAPE ≥ 300 J/kg. Nur die Anzeige wird gedämpft, der Text
darf weiter warnen.
→ mit Schritt 1 zusammen: **62 Stunden, 19 % der Regionstage**.
Damit verschwindet „Blitz bei 2 % Bewölkung" per Konstruktion.

| Variante | Stunden | Regionstage |
|---|---|---|
| heute | 217 | 36 % |
| S1 | 164 | 31 % |
| S1+S2 | 62 | 19 % |
| S1+S2, Stundenschwelle 50 % | 52 | 16 % |
| S1+S2, Stundenschwelle 60 % | 44 | 13 % |
| S1+S2, Stundenschwelle 70 % | 34 | 10 % |

Die Stundenschwelle (heute 40 %) ist der Stellknopf für „wie konservativ".

### Schritt 3 — Zwei Stufen statt einer
| Stufe | Bedingung | Anzeige | Wirkung |
|---|---|---|---|
| **hart** | beide Modellfamilien einig (MeteoSchweiz-Signal **und** DWD-Blitzpotenzial) **und** Anker erfüllt | Blitz voll | Fliegbarkeit sperren |
| **weich** | nur eine Quelle, Anker erfüllt | kleines/graues Symbol + Satz „ein Modell sieht Gewitter, das andere nicht" | keine Sperre, Hinweis im Text |
| **nichts** | keine Quelle oder Anker fehlt | nichts | — |

Löst zugleich den Nebenbefund aus §9: Symbol und Rating sagen wieder
dasselbe. **Voraussetzung:** Blitzpotenzial (ICON-D2) im Tageslauf — der
Schritt aus §5.1, jetzt Vorbedingung statt Kür.

### Schritt 4 — Flächen-Quorum für den deterministischen Code
`thunder_coverage` ins Gate: `isolated` (ein einzelner Referenzpunkt) führt
nur zur **weichen** Stufe, nicht zur harten. Kleiner Eingriff, heute fast
wirkungslos, aber Absicherung gegen den Fall, dass ein Randpunkt die ganze
Region beblitzt.

### Schritt 5 — Eichmass statt Bauchgefühl
Eine Zielgrösse festlegen: **Anteil der Regionstage mit hartem Blitz.**
Als Referenz prüfen, wie oft MeteoSchweiz tatsächlich eine Gewitterwarnung
ausgibt und ob dieser Feed maschinenlesbar ist. Das ist keine Wahrheit, aber
eine fachlich verteidigte Häufigkeit — genau der konservative Massstab aus
§10. Dazu weiterhin nötig: täglicher Mitschnitt des Blitzpotenzials, sonst
gibt es keine Rückschau (§3, Fenster wandert).

## 12. Offene Entscheide

1. **Reihenfolge:** Schritt 1+2 sofort (reine Anzeige-Logik, keine neuen
   Daten, Wirkung von 36 % auf 19 %) — oder erst nach Schritt 3?
2. **Stundenschwelle:** bei 40 % belassen (19 %) oder auf 50–60 % anheben
   (16 % / 13 %)?
3. **Anker-Schwellen:** Bewölkung 50 % und CAPE 300 sind gesetzt, nicht
   hergeleitet. Gegen das Archiv nachziehen?
4. **CAPE-Kachel:** Prozentzahl beibehalten oder auf ordinale Stufen
   umstellen (§5, branchenkonform)?
5. **Lifted Index:** wird geholt, aber nirgends verwendet — als
   Überentwicklungs-Indikator aktivieren? Für Regionen fehlt er im Abruf.
6. Meteomatics anfragen (unverändert offen aus §7).

## 12a. UMGESETZT am 02.08.2026 — alle vier Schritte

Alles committet und deployt. Reihenfolge und Wirkung:

| Schritt | Was | Wirkung |
|---|---|---|
| 1 | Tagesfenster-Füllung raus, Blitz nur aus Stundenwerten | 217 → 164 Std |
| 2 | Plausibilitätsanker: (Regen ODER Wolken) UND Instabilität | 164 → 62 Std, 36 % → 19 % der Regionstage |
| — | **Analyse-Text und Kachel auf dieselbe Regel** wie das Symbol | 20 → 6 Regionen mit Gewitterwarnung |
| 3 | Mindestanteil 2 von 7 Referenzpunkten im Ensemble | Blitzmenge nochmals etwa halbiert |
| 4 | Lifted Index für Regionen abgerufen und genutzt | Höhenkorrektur, siehe unten |

**Die eine gemeinsame Regel** liegt jetzt in `ensemble_thunder.is_ensemble_storm_hour`
und wird von Meteogramm, Kachel und LLM-Kontext gemeinsam benutzt. Vorher hatte
jede Schicht ihre eigene Rechnung — deshalb warnte Seeland/Emmental im Text bei
24 %, während das Meteogramm daneben keinen einzigen Blitz zeigte.

**CAPE bleibt in der Analyse** (Überentwicklung, unverändert). Neu steht daneben
der Lifted Index mit der ausdrücklichen Anweisung an die KI, bei hoch gelegenen
Regionen ihm zu folgen und nicht dem niedrigen CAPE-Wert.

**CIN bleibt bewusst draussen** — in den Alpen drücken Talwind-Konvergenzen die
Luft mechanisch durch den Deckel, ein CIN-Filter würde Blitze ausgerechnet an
den gefährlichsten Tagen unterdrücken.

## 12b. Erster Modellvergleich — XC Therm gegen uns

Vollständige Daten und Regionszuordnung: Kapitel 12b-1 weiter unten.
**Ohne diese Zuordnung vergleicht man Namen statt Gebiete** — am 02.08. führte
das zu zwei Fehlschlüssen (Zentralschweizer Voralpen ist *nicht* Urner Alpen;
Tessin Zentral ist Alpi Ticinesi, nicht Sopra Ceneri).

| | vor dem Umbau | danach |
|---|---|---|
| Übereinstimmung | 17 von 24 | **18 von 24** |
| nur wir (Fehlalarm) | 5 | **3** |
| nur XC Therm (verpasst) | 2 | 3 |

Aufgelöst: Berner Oberland und Freiburger Voralpen. Verloren: Tessin Zentral —
der Mindestanteil schneidet nicht nur Fehlalarme weg.

**Vorbehalt:** Es war ein neuer Wetterlauf. Logikänderung und geändertes Wetter
stecken zusammen in den Zahlen. Eine saubere Messung braucht denselben Tag auf
beiden Seiten.

## 12b-1. Die Vergleichsdaten vom 02.08. — vollständig

Alles steht hier im Klartext. **Bewusst keine separaten Datendateien** — jeder
weitere Vergleichstag kommt als eigener Abschnitt in dieses Dokument.

### Regionszuordnung — zuerst lesen

**Ohne diese Tabelle vergleicht man Namen statt Gebiete.** Am 02.08. führte das
zu zwei Fehlschlüssen: Zentralschweizer Voralpen ist *nicht* Urner Alpen
(sondern Zentrale Voralpen), und Tessin Zentral ist Alpi Ticinesi, *nicht*
Sopra Ceneri. Beide Male drehte sich das Urteil um.

| Wingcast | XC Therm | Sicherheit |
|---|---|---|
| Bodenseeraum | Bodenseeraum | sicher |
| Zentrales Mittelland | Zentrales Mittelland | sicher |
| Mittelland Ost | Östliches Mittelland | sicher |
| Seeland / Emmental | Emmental | sicher |
| Glarnerland / Walensee | Glarner Alpen | sicher |
| Berner Oberland | Berner Oberland | sicher |
| Zentralschweizer Voralpen | **Zentrale Voralpen** | sicher |
| Freiburger Voralpen | Freiburger Voralpen | sicher |
| Prättigau - Davos | Prättigau-Davos | sicher |
| Surselva | Surselva | sicher |
| Engadin Ober | Oberengadin | sicher |
| Genferseeregion | Lac Léman | sicher |
| Zentralwallis | Valais Central | sicher |
| Oberwallis / Goms | Oberwallis | sicher |
| Unterwallis | Bas-Valais | sicher |
| Jura West | Neuenburger Jura | sicher |
| Jura Zentral | Berner Jura | geschätzt |
| Jura Ost | Tafeljura | geschätzt |
| Mittelland Zentral | Ober Aargau | geschätzt |
| Mittelland West | Plateau | geschätzt |
| Ostschweiz | Rheintal | geschätzt |
| Alpstein / Ostschweiz | Östliche Voralpen | geschätzt |
| Mattertal / Saastal | Walliser Hochalpen | geschätzt |
| Tessin Nord | Sopra Ceneri | geschätzt |
| Tessin Zentral | **Alpi Ticinesi** | geschätzt |

Ohne Entsprechung bei XC Therm: Berner Voralpen, Schwarzsee/Gantrisch,
Waadtländer Alpen, Engadin Unter. Ohne Entsprechung bei uns: Urner Alpen,
Berner Alpen, Hinterrhein, Bassa Valtellina, Valsesia/Val d'Ossola.

**Namensfalle:** Unser „Mittelland Zentral" liegt nicht im Mittelland — seine
Referenzpunkte liegen im Entlebuch/Pilatus-Gebiet auf 1400 m. Daneben gibt es
eine eigene Region „Zentrales Mittelland". Immer über Koordinaten zuordnen.

### XC Therm am 02.08. — mit Gewitter

Glarner Alpen 16:00–18:30 · Oberengadin 13:00–15:30 · Oberwallis 14:00–15:30 ·
Alpi Ticinesi 13:00–14:30 · Bassa Valtellina 12:00–13:30 · Urner Alpen
17:00–17:30 · Berner Alpen 19:00–19:30 · Valsesia/Val d'Ossola 16:00–16:30

**Ohne Gewitter:** Bodenseeraum, Zentrales Mittelland, Tafeljura, Berner Jura,
Ober Aargau, Neuenburger Jura, Plateau, Freiburger Voralpen, Berner Oberland,
Emmental, Surselva, Hinterrhein, Prättigau-Davos, Östliche Voralpen, Östliches
Mittelland, Zentrale Voralpen, Walliser Hochalpen, Bas-Valais, Valais Central,
Sopra Ceneri, Lac Léman. **Nicht erfasst:** Rheintal.

### Wingcast am 02.08. — drei Stände desselben Tages

**(a) Live vor dem Umbau**, Analyse-Panel, 20 von 29 Regionen — Tageswert mit
Schwerpunktfenster, Erwähnung ab 15 %:
Alpstein 11–17 (100 %) · Ostschweiz 12–17 (100 %) · Glarnerland 12–17 (100 %) ·
Mittelland Zentral 12–17 (100 %) · Zentralschweizer Voralpen 13–17 (100 %) ·
Tessin Zentral 12–17 (100 %) · Mittelland Ost 13–17 (100 %) · Berner Oberland
12–17 (76 %) · Berner Voralpen 14–17 (76 %) · Freiburger Voralpen 14–17 (76 %) ·
Prättigau-Davos 13–17 (76 %) · Schwarzsee/Gantrisch 13–16 (81 %) · Surselva
12:00 (81 %) · Zentrales Mittelland 15–17 (67 %) · Tessin Nord 16–17 (48 %) ·
Jura Ost 14–17 (38 %) · Engadin Unter 13:00 (38 %) · Genferseeregion 12–14
(33 %) · Oberwallis/Goms 16:00 (29 %) · Seeland/Emmental 15–17 (24 %)

**(b) Nach Stundenlogik und Anker**, 9 Regionen, 27 Stunden:
Tessin Zentral 12–18 · Ostschweiz 12–18 · Alpstein 12–16 · Berner Voralpen
15–18 · Glarnerland 16–18 · Zentralschweizer Voralpen 13–14 und 17–18 ·
Mittelland Zentral 14–16 · Freiburger Voralpen 16–17 · Berner Oberland 17–18

**(c) Nach Mindestanteil und Lifted Index**, neuer Lauf 20:35, 6 Regionen,
20 Stunden:
Ostschweiz 13–18 · Alpstein 12–16 und 17–18 · Glarnerland 14–18 ·
Zentralschweizer Voralpen 15–18 · Berner Voralpen 16–18 · Mittelland Zentral
13–14

### Auswertung

| | Stand (b) | Stand (c) |
|---|---|---|
| Übereinstimmung | 17 von 24 | 18 von 24 |
| nur wir | 5 | 3 |
| nur XC Therm | 2 | 3 |

Aufgelöst durch den Mindestanteil: Berner Oberland, Freiburger Voralpen.
Verloren: Tessin Zentral — XC Therm hatte dort Gewitter.

### Höhenbefund — die Erklärung für die Schieflage

Gemessen am Bestand vom 02.08., 11–19 Uhr:

| Höhenlage | CAPE-Median | bestes Ensemble-Stundenmittel |
|---|---|---|
| unter 1000 m | 640 | 24 % |
| 1000–1900 m | 860 | 69 % |
| über 1900 m | 295 | 12 % |

CAPE wird vom Boden aufwärts gerechnet und ist zwischen Regionen
unterschiedlicher Höhe nicht vergleichbar. Alle acht Hochalpenregionen hatten
100 % Bewölkung — die Wolken sind da, der Energiewert sieht sie nicht.

## 12b-2. Wie ein Blitz heute entsteht — die vollständige Kette

Dieses Kapitel ist bewusst redundant: **Es soll ohne jedes Vorwissen und ohne
Gedächtnis aus einer früheren Sitzung lesbar sein.**

**Quellen (Stand 02.08.):**

| Quelle | Anbieter | Wofür |
|---|---|---|
| `weather_code` 95/96/99 | MeteoSchweiz ICON-CH1/CH2 | harter Gewittercode, ein Lauf |
| Ensemble ICON-CH2-EPS, 21 Member | MeteoSchweiz | Anteil der Läufe mit Gewitter, **nur Regionen** |
| CAPE, CIN, Bewölkung, Regen | MeteoSchweiz | Plausibilitätsprüfung |
| Lifted Index | GFS | höhenunabhängige Instabilität, **seit 02.08. auch für Regionen** |
| Blitzpotenzial | DWD ICON-D2 | **noch nicht im Tageslauf**, nur im Archiv |

**Der Entscheidungsweg pro Stunde und Region:**

1. Sagt der deterministische Code 95/96/99? → **Blitz, ungeprüft.** Begründung:
   Wolken, Regen und dieser Code stammen aus derselben Rechnung, können sich
   also nicht widersprechen. (Betraf am 02.08. genau 2 von 1507 Stunden — für
   Regionen ist dieser Weg praktisch stumm.)
2. Sonst: Wie viele der 21 Ensemble-Läufe zeigen **in dieser Stunde** Gewitter?
   Ein Lauf zählt erst, wenn **mindestens 2 der 7 Referenzpunkte** zünden
   (`ENSEMBLE_THUNDER_POINT_QUORUM`). Unter 40 % der Läufe → kein Blitz.
3. Plausibilitätsanker: **Instabilität** (CAPE ≥ 300 **oder** Lifted Index
   ≤ −1) **und** (Regen ≥ 0,1 mm **oder** Bewölkung ≥ 50 %), alles aus
   derselben Stunde. Nicht erfüllt → kein Blitz.
4. Erfüllt → Blitz im Meteogramm, Kachel im Analyse-Panel, Erwähnung im
   KI-Text. **Alle drei über dieselbe Funktion**
   (`ensemble_thunder.is_ensemble_storm_hour`).

**Was der Blitz NICHT tut:** Er sperrt die Fliegbarkeit nicht. Gesperrt wird
weiter nur über den deterministischen Code. Symbol und Bewertung erzählen
damit weiterhin nicht ganz dieselbe Geschichte — offener Punkt.

**Bewusst nicht verwendet:** CIN (Talwind-Konvergenzen drücken die Luft
mechanisch durch den Deckel; ein mittlerer Deckel macht das Nachmittagsgewitter
heftiger statt harmloser). CAPE als alleiniges Instabilitätsmass (höhenabhängig,
zwischen Regionen nicht vergleichbar).

**Wo die Zahlen herkommen — und wo nicht:** Keine einzige Schwelle ist gegen
gemessene Blitze kalibriert. Es gibt **keine freie Gewitterwahrheit** (§3,
nicht erneut anrennen). Alle Schwellen sind plausibel gesetzt und gegen die
Häufigkeitsverteilung geprüft, mehr nicht. Das ist die Schwachstelle des ganzen
Bauwerks.

## 12b-3. Offene Unzufriedenheit mit der Herleitung (User, 02.08.)

Der User ist mit der Gewitteranalyse **nicht zufrieden — ausdrücklich mit der
Herleitung, nicht mit der Darstellung.** Am 03.08. zuerst klären, was genau
gemeint ist. Die aus unserer Sicht schwächsten Glieder der Kette:

1. **Keine Wahrheit, nirgends.** Wir vergleichen Modelle mit Modellen. XC Therm
   ist ein einzelner Lauf, unser Ensemble sind 21 — Uneinigkeit sagt nicht, wer
   recht hat. Ohne Blitzmessung bleibt jede Schwelle Setzung.
2. **Die 40-%-Schwelle ist frei gewählt.** Sie entscheidet über jeden Blitz und
   ist an nichts geeicht.
3. **Der Mindestanteil von 2 ist ebenso gesetzt.** Er hat am 02.08. zwei
   Fehlalarme beseitigt und einen Treffer gekostet (Tessin) — n = 1 Tag.
4. **Der Anker ist ein Notbehelf.** Er prüft nur, ob eine Stunde ein Gewitter
   überhaupt hergibt. Er sagt nichts darüber, ob eines kommt.
5. **Der blinde Fleck im Hochgebirge ist unerklärt.** Oberengadin: 0 % im
   Ensemble, während XC Therm 2,5 h Gewitter zeigt. Solange wir nicht wissen,
   warum, ist die ganze Kette dort wertlos.
6. **Wir leiten aus Wettercodes ab, nicht aus Physik.** Die Szene entscheidet
   an der Überentwicklung (Lifted Index), nicht am Blitz — §5 „Später". Wir
   haben den Lifted Index jetzt, benutzen ihn aber nur als Türsteher, nicht als
   Primärindikator.

## 12d. UMGESETZT am 03.08.2026 — Anker verschärft (Regen-Pflicht)

Erster **Saison-Backtest** (15.05.–02.08., 2'320 Regionstage gegen
SwissMetNet-Signaturen) → Anker-Nässe-Bedingung von „Regen ODER Wolke 50 %"
auf **Regen-Pflicht** verschärft. Kostet 1 Gewittertag von 113, drittelt das
Fehlalarm-Potenzial (61 % → 24 % Durchlass an stillen Tagen); am Lauf vom
02.08.: 33 → 15 Blitzstunden. **Alle Zahlen und Befunde: `docs/GEWITTER.md`
§0c** (dort auch: det. Code erkennt nur 13 % → Ensemble-Entscheid bestätigt;
Wolkentop als künftige weiche Stufe; Abend > Flugfenster).

Damit erledigt aus diesem Plan: §11 Schritt 1–4 (02.08.) + Anker-Härtung.
§12c.4 (DWD-Blitzpotenzial/LPI) ist **gestrichen** — LPI erkannte im
Backtest 0 von 4 Gewittern des Testtags; `data/lpi_archive/` gelöscht.

**Ebenfalls umgesetzt 03.08.: der tägliche Mess-Abgleich.** Neue Struktur
`validation/` (Umzug von `fronten_validation/` + `xcontest_validation/`,
Konvention in `validation/README.md`), Domäne `validation/gewitter/`
(Grenzen im dortigen README), gemeinsame Lib `scripts/validation_common.py`,
Tages-Skript `scripts/validate_gewitter_daily.py` (Scheduler: morgens für
den Vortag; Scoreboard eicht die Schwellen 40/50/60 % parallel). Erster
validierter Tag: 02.08. — beide Abend-Gewitter korrekt als „verpasst",
die 5 Flugzeit-Fehlalarme korrekt erkannt. Messbasis Zehnminutenwerte
(Stundenwerte verwässern die Signatur — beide reale Gewitter fielen auf
Stundenbasis unter die Schwellen).

**Einziger offener Punkt: die weiche Überentwicklungs-Stufe** (Wolkentop
ICON-EU, Top ≤ −20 °C @ ≥ 75 % Punkte + weicher Anker, hohler Blitz,
sperrt nie — Kennzahlen in `docs/GEWITTER.md` §0c). **Dieser Plan wird
gelöscht**, sobald sie umgesetzt und in `docs/` dokumentiert ist.

## 12c. Offen — hier geht es am 03.08. weiter

1. **Vergleich für Montag ziehen.** XC Therm für 03.08. abgreifen (kommt vom
   User, wir kommen an die Seite nicht ran), unsere Werte danebenstellen und
   als neues Kapitel 12b-1b hier eintragen — Aufbau wie 12b-1. Erst mit zwei
   Tagen lässt sich sagen, ob die Verbesserung echt ist oder Tagesrauschen.
2. **Blinder Fleck Hochalpen.** Oberengadin meldet im Ensemble **0 %**, während
   XC Therm dort 2,5 h Gewitter zeigt. Der Lifted Index hat das nicht behoben —
   das Problem sitzt im Modellsignal, nicht im Filter. Nächster Schritt:
   nachsehen, was ICON-CH2-EPS an diesen Punkten überhaupt liefert.
3. **Zeitfenster zu breit.** Wo beide Gewitter sehen, nennt XC Therm 30–150
   Minuten, wir 3–6 Stunden. Stellknopf ist die Stundenschwelle (heute 40 %).
4. **Hohler Blitz bei Modell-Uneinigkeit** (ursprünglich Schritt 3). Symbol gab
   es früher für CAPE-Überentwicklung, `meteogram.js:1043`. Braucht das
   DWD-Blitzpotenzial im Tageslauf. Nach dem Vergleich wäre das heute der
   Normalfall — 3 von 6 Regionen wären hohl.
5. **Prozent → ordinale Stufen.** Bewusst zurückgestellt („Feinheiten"), aber
   branchenkonform: niemand sonst nennt Gewitter-Prozente.
6. **Tessin-Verlust prüfen.** Ist der Mindestanteil von 2 zu streng, oder war
   es der neue Lauf? Am 03.08. mitmessen.
7. Unverändert offen aus §7: Meteomatics anfragen, `data/lpi_archive/`
   committen oder auslagern.

## 13. Reproduzierbarkeit Teil B

Messskripte liegen im Scratchpad dieser Sitzung (`audit_bolts.py`,
`audit_bolts2.py`, `audit_bolts3.py`) und lesen `data/wetterdaten.json`.
Sie replizieren die Anzeige-Logik aus `web.py:4171` eins zu eins. Vor dem
Bau nach `scripts/` übernehmen, damit die Wirkung nach dem Umbau erneut
messbar ist.
