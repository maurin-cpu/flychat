# Gewitter- & Blitzvorhersage — Konzept & Recherche

Fundierte Grundlage dafür, **was wir für die Gewitter-/Blitzvorhersage beachten
müssen**, welche Daten wir haben, wo die Lücken sind und welche Schritte sich
lohnen. Verbindet die meteorologische Theorie, die Open-Meteo-Datenlage und die
Validierung der fertigen Blitz-Prognose (LPI).

> **Sync-Pflicht (an Claude):** Bei Änderungen an den CAPE-/Gewitter-Schwellen
> (`config.py`: `CAPE_WARN_JKG`, `CAPE_DANGER_JKG`, `SYNOPTIC_PRECIP_CAPE_*`),
> an der Tag-Ableitung (`skills/shared/*/03_safety/01_tags_safety.md`,
> `docs/TAGS.md`), an der CIN-Bremse (`thermik_calculator.py`) oder an den
> abgerufenen Wetterparametern (`config.py`: `CH_SURFACE_PARAMS`,
> `GFS_SUPPLEMENTARY_PARAMS`): diese Doku nachziehen und Changelog ergänzen.

Letzte Aktualisierung: 2026-07-31 (Regions-Aggregation repariert + Ensemble, §0b)

---

## 0b. Regions-Aggregation repariert + Ensemble ergänzt (2026-07-31)

Die Entscheidung von §0 („Gewitter = `weather_code`") war richtig, aber auf
Regionsebene kam sie nie an. Zwei Defekte, beide belegt:

### Defekt 1 — Regionsaggregation verlor den `weather_code` (behoben)

`_aggregate_regional_data()` aggregierte nur `CLOUD_PARAMS` und
`PRECIP_USE_MIN`. Alles andere — auch `weather_code` — blieb auf
`data_list[0]`, also **einem** von 7–16 Referenzpunkten in einem bis zu 40 km
breiten Polygon. Zündete die Zelle an einem anderen Punkt, existierte sie für
die Region nicht. Verschärfend: `weather_code` steht in
`config.CH_SURFACE_PARAMS`, der Surface-Override in `_process_spot_weather()`
holte den Wert also erneut aus einer RP0-Quelle.

**Fix:** neuer Parameter `aggregate_weather_code` (Default `False`). Gesetzt
wird er an den vier Region-Aufrufen (thermal, fallback, ch1, ch2) — damit
greift er auch im Surface-Override. Der Spot-Pfad bleibt unangetastet: dort
*ist* `data_list[0]` der Startplatz, und der Spot-Pfad war mit 92.6 % gesund.

Aggregiert wird nach **Schweregrad, nicht numerisch** — die WMO-Skala ist nicht
monoton nach Gefahr sortiert (75 starker Schneefall > 65 starker Regen,
45 Nebel > 3 bedeckt). Rangfolge: `_WMO_SEVERITY_TIERS` in `fetch_weather.py`.

**Messung** (`scripts/measure_region_weather_code.py`, ICON-CH2, 60 Tage,
29 Regionen, 203 Referenzpunkte): von 90 Gewitterstunden erreichten bisher
**15 die Anzeige — 16.7 %**. Mit dem Fix: 100 %.

### Defekt 2 — nur ein deterministischer Lauf (ergänzt, nicht ersetzt)

Für Konvektion ist ein Einzellauf die unzuverlässigste verfügbare Information.
Belegfall Engelberg (46.82/8.40), 02.08.2026, Fenster 11–20 h, gemessen am
31.07.2026:

| Quelle | Gewitter | CAPE max | Regen |
|---|---|---|---|
| ICON-CH2 deterministisch | keins (Code 0) | 430 | 0.0 mm |
| ICON-CH2-EPS (21 Member) | 3 Member Code 95 | median 720 / max 1570 | 4 Member ≥ 1 mm/h |

Auch ICON-D2, ICON-EU, ECMWF und GFS zünden deterministisch keine Zelle.

**Ergänzung:** `ensemble_thunder.py` berechnet je Region und Tag den Anteil der
Member mit Code 95/96/99 im Flugfenster und liefert Schwerpunkt-Fenster dazu.
Das Ergebnis steht in `_regions[rid]["thunder_ensemble"]` und erscheint im
Regions-Kontext als Zeile `GEWITTER-ENSEMBLE`.

> **Ausdrücklich eine weiche Warnstufe.** Kein Fliegbarkeits-Gate, kein No-Go,
> kein `not_safe` allein daraus. Das harte Gate bleibt der deterministische
> `weather_code`.

Die Schwellen (`config.ENSEMBLE_THUNDER_MENTION_PCT` = 20 / `_ELEVATED_` = 40 /
`_HIGH_` = 60) sind **nicht kalibriert** — Startpunkt, kein Messergebnis. Vor
einem Livegang gegen Stationsmessungen prüfen.

API-Eigenheit: Der Ensemble-Endpunkt läuft **nur ohne** unseren Kunden-Key
(mit Key: HTTP 403, „requires API Professional or Enterprise plan"). Es gelten
also freie Rate-Limits — daher kleine Chunks, nur `weather_code` als
Standardvariable, Backoff bei 429. Fällt der Abruf aus, läuft der Wetterlauf
ohne Ensemble weiter.

### Validierung — gegen Messungen, nie gegen Modelle

`scripts/validate_thunder_vs_stations.py` vergleicht beide Varianten desselben
Codepfads gegen MeteoSchweiz-Stundenmessungen (OGD-SMN, frei).

Vorgeschaltet ist ein **Zeitachsen-Beweis**: `reference_timestamp` ist UTC und
bezeichnet die Stunde *davor*. Das Skript verschiebt die Messreihe um −3…+3 h
gegen die Modelltemperatur; liegt das Minimum nicht bei 0 h, bricht es ab.
Gemessen: Minimum bei 0 h, Restabweichung 1.85 K (der konstante Höhenversatz
Station↔Referenzpunkt wird vorher herausgerechnet — geprüft wird der Tagesgang,
nicht die absolute Temperatur).

Ergebnis über 5300 Regions-Tage (123 Stationen, 26 Regionen, 60 Tage):

| | Treffer | Verpasst | Fehlalarm | Quote |
|---|---|---|---|---|
| Regen ALT | 504 | 1374 | 184 | 26.8 % |
| Regen NEU | 504 | 1374 | 184 | 26.8 % |
| Gewitter ALT | 7 | 391 | 8 | 1.8 % |
| Gewitter NEU | 42 | 356 | 23 | 10.6 % |

Regen ist **identisch** — die Änderung fasst Niederschlag nicht an (zusätzlich
durch `tests/test_weather_code_aggregation.py` abgesichert). Gewitter-Treffer
versechsfachen sich; markierte Regions-Tage steigen von 15 auf 65 von 5300.

Zwei Einschränkungen, die beim Lesen mitgehören:
1. Der Gewitter-Indikator („Station meldet ≥ 5 mm in einer Stunde") ist
   **schwach** — offene Blitzdaten gibt es nicht, Starkregen entsteht auch ohne
   Gewitter. Ein Teil der „Fehlalarme" dürften echte Gewitter sein, die an
   keiner Station 5 mm abgeladen haben.
2. Die absoluten Regen-Quoten sind **nicht** mit den 86 %/91 % aus der
   Analysesession vom 30.07. vergleichbar: dort wurde Station gegen Station
   gepaart, hier Regions-Tag gegen „irgendeine Station der Region", und ohne
   die 16-Punkte-Niederschlagsüberschreibung der Produktion. Aussagekräftig ist
   hier allein der Vergleich ALT↔NEU.

### Kein Quorum — anders als beim Regen, und zwar bewusst

Naheliegende Frage: soll das Gewitter dieselbe Quorums-Logik bekommen wie der
Niederschlag? Antwort aus den Daten: **den beschreibenden Teil ja, den
unterdrückenden nein.**

Der Regen-Filter hat zwei Teile, und nur einer davon filtert:
1. Ein **Quorum** — aber nur im Rauschband 0.05–0.2 mm/h. Ab
   `PRECIP_SIGNIFICANT_MM` („echte Zelle") lässt der Filter auch **einen
   einzelnen** Referenzpunkt durch. Ein Gewitter ist per Definition eine echte
   Zelle, fällt also nie ins Rauschband. Unter der Logik des Regens gilt für
   Gewitter also gar kein Quorum.
2. Eine **Flächen-Beschreibung** (`precipitation_class`) — die unterdrückt
   nichts, sie beschreibt.

Gemessen (60 Tage, ICON-CH2, 29 Regionen à 7 Referenzpunkte):

| gleichzeitig zündende RPs | Stunden | Anteil |
|---|---|---|
| 1 von 7 | 76 | 84.4 % |
| 2 von 7 | 10 | 11.1 % |
| 3 von 7 | 3 | 3.3 % |
| 4 von 7 | 1 | 1.1 % |

Konvektion ist punktförmig — das ist Physik, kein Artefakt. Ein Quorum würde
fast alles löschen:

| Variante | Treffer | Fehlalarm | Quote | Präzision |
|---|---|---|---|---|
| irgendein RP (gewählt) | 42 | 23 | 10.6 % | 64.6 % |
| ≥ 2 RPs | 10 | 3 | 2.5 % | 76.9 % |
| Quorum 30 % | 2 | 2 | 0.5 % | 50.0 % |
| Quorum 40 % | 2 | 2 | 0.5 % | 50.0 % |

Ein 30-%-Quorum liesse von 42 Treffern **2** übrig — schlechter als der alte,
kaputte Zustand (7). Für rund 12 Punkte Präzision würden wir 85 % des Signals
wegwerfen. Bei einer Sicherheitswarnung ist das der falsche Tausch.

**Übernommen wurde daher die Beschreibung:** `thunder_coverage` +
`thunder_class` (`classify_thunder_pattern`), mit denselben Schwellen wie beim
Niederschlag — `widespread` ≥ 70 %, `scattered` ≥ 40 %, sonst `isolated`.
Das Flächenbild erscheint im `GEWITTER-TREND` und wandert mit dem
`weather_code` durch das Tier-Voting (es steht daher in der
Surface-Override-Liste, nicht bei den Thermal-Ableitungen — sonst beschriebe
es einen anderen Modelllauf als den angezeigten Code).

`isolated` heisst **nicht harmlos**: die Zelle ist real und zieht. Es heisst,
dass die räumliche Unsicherheit innerhalb der Region gross ist — und genau das
soll der Text sagen dürfen.

### Defekt 3 — Modell verpasst Gewitter auch echt (offen)

An einzelnen Tagen liefert das Modell null Gewitterstunden, obwohl Stationen
16–44 mm in einer Stunde massen. Das ist keine Pipeline-, sondern eine
Modellschwäche. Nur relevant, falls das Ensemble nicht ausreicht — vor einer
weiteren Massnahme erst das Ensemble kalibrieren.

### Nebenbefund: Archiv seit 01.07. ohne Bewertungen

Beim Aufsetzen der Validierung fiel auf, dass das Archiv seit dem 01.07. für
**Spots und Regionen** null Bewertungen enthielt (24 Tage). Ursache: der
Englisch-Flip schrieb die Analysen in `*_en.json`, das Snapshot-Skript las den
fest verdrahteten deutschen Pfad. Behoben in `scripts/snapshot_weather.py`
(sprach-unabhängige Quellenwahl + Alarm bei 0 Bewertungen, jetzt auch für
Regionen). Zusätzlich archiviert der Snapshot jetzt die Regions-**Wetterwerte**
(inkl. `weather_code`, Gewitterstunden, Ensemble) — vorher standen dort nur die
LLM-Bewertungen, womit sich Regions-Änderungen gar nicht überprüfen liessen.

---

## ENTSCHEIDUNG (2026-06-27): Gewitter = weather_code, schlanke Fassung

Nach dem Daten-Check (§4a) und Abwägung wurde entschieden, **konsistent nur
ICON-CH** zu nutzen und das Gewitter-Urteil **allein auf `weather_code`
95/96/99** zu stützen:

- **LPI / ICON-D2 / `thunderstorm_probability` verworfen** — LPI gibt es nur von
  ICON-D2 (Modell-Mix, nur ~48 h), `thunderstorm_probability` liefert keine
  Daten (§4a). `weather_code` ist ein **vollwertiger 5-Tage-Forecast aus ICON-CH**
  (CH2, 120 h), aktiv (7082× Code 95 in 21 Tagen) und das fertige, integrierte
  Gewitter-Urteil des Modells.
- **CAPE wird als Gewitter-Auslöser entmachtet** — es war die Ursache der
  „CAPE bei blauem Himmel"-Fehlalarme. CAPE bleibt ein
  Überentwicklungs-/Flugbarkeits-Hinweis (Safety-Sub-Rating), ist aber **kein
  Gewitter/Blitz** mehr.
- **Frontend: zwei Blitze → einer.** Der „hohle" CAPE-Blitz im Meteogramm
  entfällt; nur der gefüllte `weather_code`-Blitz bleibt.
- **Bewusster Verzicht:** keine CAPE-Vorwarnung („geladenes Gewehr", §6/§7) —
  der Code springt erst, wenn das Gewitter da ist. Für eine 3–5-Tage-Vorhersage
  vertretbar; bei Bedarf später als gezielte Vorwarnung nachrüstbar.

WMO-Codes: **95** = Gewitter (leicht/mässig, ohne Hagel), **96** = Gewitter mit
leichtem Hagel, **99** = Gewitter mit schwerem Hagel. Alle drei → ein Label
„Gewitter".

**Finale Variante (2026-06-27): CAPE bleibt als Überentwicklungs-Signal**
(nicht ganz entfernt) — Gewitter = weather_code, CAPE = eigenes Flugbarkeits-
Risiko (Böenfront/Cloud-Suck), NIE Gewitter.

Umgesetzte Eingriffe (Code geändert, noch nicht committet):
1. **Synoptik** `engine/synoptic_context.py` — pro Spot `has_ts`, pro Seite
   `gewitter_share` (Anteil Spots mit wc 95/96/99) + `max_wc` aggregiert.
2. **Synoptik-KI** `engine/synoptic_llm.py` — `gewitter_share`+`max_wc` an die KI.
3. **Synoptik-Prompt** `skills/synoptic_overview.md` (DE+EN) — Gewitter aus
   `gewitter_share`/weather_code; CAPE = Instabilität/Überentwicklung, nie
   Gewitter allein. i18n gestempelt.
4. **E-Mail** `email_service.py` — `"cape "` aus den 2 Gewitter-Keyword-Buckets.
5. **No-Go-Heuristik** `engine/_common.py` — `cape`→`UEBERENTWICKLUNG` statt
   `GEWITTER`; `UEBERENTWICKLUNG` als gültiges No-Go-Label aufgenommen.
6. **Meteogramm** `static/js/meteogram.js` — hohler CAPE-Blitz entfernt (ein Blitz).
7. **config.py** — tote `SYNOPTIC_PRECIP_CAPE_*` als DEPRECATED markiert.

Das `[THUNDERSTORM]`-Tag (`weather_context.py:751`) basiert bereits auf
`weather_code` — unverändert. Safety-Skills trennen CAPE schon als
„Überentwicklung" — unverändert.

---

## 0a. Verifikation (2026-06-28)

- **Unit-Tests:** `tests/test_synoptic_context.py` um zwei gezielte Fälle
  ergänzt — `test_high_cape_alone_is_no_gewitter` (CAPE 3000 ohne wc 95/96/99 →
  `gewitter_share == 0.0`) und `test_weather_code_drives_gewitter_share`
  (wc 96 → `gewitter_share == 1.0`, unabhängig von CAPE). Beweist die
  Kern-Invariante des Umbaus. **64 Tests grün** (`test_synoptic_context.py` +
  `test_synoptic_llm.py`: 78 grün).
- **Golden-Regression:** lokal **nicht aussagekräftig** — das eingefrorene
  Golden-Set (`cost_testing/golden/`) ist von Mai (2026-05-0x), die lokale
  `data/spot_analyses.json` von Ende Juni → null Datums-Überlappung, `--no-llm`
  ergibt `0/0`. Ein frisches Golden-Run kostet LLM. Vertretbar, weil die
  Änderung für die **gescorten** Felder verhaltens-neutral ist: `synoptic_llm.py`
  reicht nur additiv 2 Felder durch, und in `_common.py` wandert `cape` von
  `GEWITTER` nach `UEBERENTWICKLUNG` — **beide** sind No-Go-Labels, also bleiben
  `safety_status`/`flyability_tier` gleich. Der Synoptik-Prompt selbst ist nicht
  Teil des Golden-Scorings.

Status: committet auf `feat/gewitter-weather-code`. Tote CIN-Bremse
(§8 Bonus) im selben Branch entfernt (Deckel schon via Parcel-Methode modelliert).

---

## TL;DR

- **CAPE allein reicht nicht.** CAPE ist nur der *Treibstoff* (verfügbare
  Auftriebsenergie). Ob es ein Gewitter gibt, entscheiden drei Zutaten
  **gleichzeitig**: Instabilität (CAPE) **+** Feuchte **+** Auslöser/Hebung
  (Doswell-Ingredients). Fehlt eine, kein Gewitter — daher „CAPE, aber blauer
  Himmel".
- **Blitz braucht eine vierte Stufe.** Eine Wolke kann konvektieren und regnen
  und trotzdem nie blitzen. Blitz braucht eine **tiefe Mischphasen-Zone**
  (unterkühltes Wasser + Eis + Graupel zwischen −10 und −25 °C) — praktisch:
  **Wolkentop ≤ −20 °C** und ein starker Aufwind, der Graupel über das
  −15-°C-Niveau hebt.
- **Datenlücke bei uns:** Wir messen die „Höhe/Kälte der Wolke" nicht und
  trennen damit *Schauer* nicht sauber von *Gewitter mit Blitz*.
- **Zwei fertige Felder liegen ungenutzt im selben Datenpaket:**
  `lightning_potential` (LPI, ICON-D2) und `thunderstorm_probability` (GFS).
- **LPI ist nützlich, aber kein Orakel:** flächiges Tagessignal (gut),
  nicht spotgenau, im Bergland zu nervös, nur ~48 h Reichweite.
- **CAPE bleibt nötig** — LPI ersetzt es nicht (siehe §6).

---

## 1. Meteorologie: die drei Zutaten (Ingredients-based forecasting)

Operationeller Standard (Doswell, Brooks & Maddox 1996): tiefe feuchte
Konvektion = **Instabilität + Feuchte + Hebung** (+ Scherung für Organisation).
Die Stärke des Modells: **fehlt eine einzige Zutat, gibt es kein Gewitter** —
egal wie gut die anderen sind. CAPE ist nur die quantifizierte „Instabilität",
deshalb per Konstruktion notwendig, aber nicht hinreichend.

| Gate | Was | Schwelle (Standard) | Relevanz |
|---|---|---|---|
| **Deckel / CIN** | Konvektionssperre („Lid") | CIN ≳ 150–200 J/kg → ohne starken Trigger kein Gewitter | **Das ist „CAPE + klarer Himmel":** hohes CAPE unter einem Deckel = blockiert. Der Deckel kann die Energie sogar aufstauen → bei Durchbruch heftiger. |
| **Trigger / Hebung** | Auslöser, der den Deckel durchbricht | Alpen: thermisch/orografisch über Graten am Nachmittag, Fronten, Konvergenzlinien | Thermik muss stark genug sein, die CIN zu überwinden (MeteoSchweiz: Inversion kappt Cumuli oft bis ~4 km). |
| **Feuchte-Tiefe** | nicht nur am Boden | T−Td-Spread > ~12–15 °C → hohe Basis, schwache Wolke; trockene Mittelschicht (RH 700–500 hPa niedrig) → Entrainment killt Aufwind | Feuchter Boden unter trockener Mittelschicht = flache Cu, die verdunsten — kein Sturm. |

Hilfsgrößen: **LCL** = Wolkenbasis (hoher T−Td-Spread → hohe, schwache Basis);
**LFC** = ab wo freier Aufstieg beginnt; **EL** = Gleichgewichtsniveau ≈
**Wolkentop** — die wichtigste Einzelzahl für die Blitz-Frage (§2).

---

## 2. Blitz-spezifische Physik (das eigentliche Kernthema)

Ladungstrennung entsteht durch **nicht-induktive Aufladung (NIC)**: Kollisionen
von Eiskristallen und **Graupel** in Gegenwart von **unterkühltem Wasser**. Alle
drei müssen im selben Volumen koexistieren — fehlt eines (z. B. „warme" Wolke,
die nie vereist), bricht die Elektrifizierung zusammen.

- **Ladungszone:** zwischen 0 °C und −40 °C, Hauptzone **−15 bis −25 °C**.
- **Daraus die einzig blitz-spezifischen Prädiktoren:**
  - **Wolkentop-Temperatur ≤ −20 °C** (notwendig), **≤ −30 °C → wahrscheinlich**,
    **≤ −40 °C → hoch**. (Satelliten-Klimatologie: CG-Blitzdichte steigt stark
    ab Top-Temp < −55 °C, Molinié 2004.)
  - **Cold-cloud depth** = Wolkentop − Gefrierniveau (0 °C). Je tiefer die
    Mischphasen-Zone, desto mehr Aufladung.
  - **Aufwind stark genug, Graupel über −15 °C zu heben** — Proxy:
    W_max = √(2·CAPE).
  - **LPI (Lightning Potential Index, Yair/Lynn 2010)** = physikbasierter
    Goldstandard: Aufwind² gewichtet mit dem Mischphasen-Anteil, integriert über
    0…−20 °C. **Graupel ist zwingend** — kein Graupel ⇒ LPI ≈ 0.

---

## 3. Operationelle Indizes (sekundär, regionsabhängig)

Für die Alpen am ehesten **LI, K, KO, CAPE/CIN**; die US-Indizes
(SWEAT, Total-Totals) übergewichten Scherung und neigen zu Fehlalarmen bei
Luftmassen-Gewittern. **Kein Index ist allein verlässlich** — nur in
Kombination und regional kalibriert.

| Index | Schwellen (Gewitter) | Bemerkung |
|---|---|---|
| **Lifted Index (LI)** | ≤ −2 marginal · ≤ −5 groß · ≤ −8 extrem | Netto-Auftrieb auf 500 hPa; ignoriert Deckel/Top |
| **K-Index** | >25 verstreut · >30 zahlreich | Luftmassen-Gewitter; belohnt Mittelschicht-Feuchte |
| **KO-Index** (DWD/Europa) | <2 wahrscheinlich · 2–6 möglich · >6 keine | europa-getunt; gut wo Boden-Paket schlecht definiert |
| **Total Totals** | 44–50 wahrscheinlich · >56 zahlreich schwer | kann bei trockenen Tieflagen Fehlalarm geben |
| **CAPE × 0–6 km Scherung** | > ~20 000 m³/s³ → signifikant schwer | Organisations-/Severity-Signal, nicht für reinen Blitz nötig |

---

## 4. Unsere Datenlage (Open-Meteo)

Drucklevel ziehen wir von **ICON-D2** (2.2 km, deckt CH, Tag 1–2) + ICON-EU
(Tag 3–5). Surface u. a. CAPE, CIN, `weather_code`, `cloud_base`, `updraft`
(D2-spezifisch); LI + CIN per **GFS-Supplement**.

**Vorhanden:** CAPE · CIN · LI (GFS) · `updraft` (D2) · `weather_code` ·
`cloud_base` · vollständige T/RH/Wind-Drucklevels (1000–600 hPa, ICON-D2/EU).

**Lücken — genau auf der Blitz-Seite:**

| Was fehlt | Bei Open-Meteo verfügbar? | Aufwand |
|---|---|---|
| **`lightning_potential` (LPI)** | ✅ **ICON-D2** (Zentraleuropa) — Modell, das wir für PL **schon abfragen** | niedrig |
| **`thunderstorm_probability`** | ✅ **GFS** — den wir für LI/CIN **schon supplementieren** | niedrig |
| **`convective_cloud_top` / `_base`** | ✅ DWD/ICON-D2 | niedrig |
| **Gefrierniveau (0 °C)** | `freezing_level_height` (D2) **oder** aus unseren PL-Temps + Geopotential ableitbar | mittel |
| **Wolkentop-Temp / cold-cloud depth** | ableitbar: EL aus PL-Profil → Temp am Top | mittel |

### 4a. Empirischer Daten-Check (2026-06-27, Live-API + Archiv)

Gegen die Live-Open-Meteo-API und `data/weather_archive/2026-06-27.json` geprüft:

| Feld / Modell | Befund |
|---|---|
| **CIN von ICON-CH** | ✅ **`meteoswiss_icon_ch1` UND `_ch2` liefern `convective_inhibition` voll** (24/24, echte Werte). Merge füllt GFS nur bei `None` (`fetch_weather.py:758-762`) → unser CIN kommt **primär aus ICON-CH**. `-1`-Sentinel trat nicht auf (Werte 0 oder positiv), trotzdem abfangen. |
| **CIN-Vorzeichen** | ⚠️ Open-Meteo liefert CIN **positiv** (z. B. 154, 29, 105 J/kg; je grösser, desto stärker der Deckel). |
| **CIN-Bremse im Thermik** | 🗑️ **entfernt 2026-06-28** (`thermik_calculator.py`): Block prüfte `convective_inhibition < -100` / `< -50` → feuerte nie (Open-Meteo liefert CIN positiv, empirisch 10 525 Archiv-Werte alle positiv 1–431 J/kg). **Statt das Vorzeichen zu fixen ganz entfernt**, weil der Deckel bereits in `calculate_thermal_profile` modelliert wird (Penetrative Convection: Overshoot-Budget vs. CIN-Kosten stoppt die Blase an der Inversion → senkt `max_thermal_height`). Ein separater Modell-CIN-Abzug wäre Doppelzählung. Das Deckel-**Gate** für CAPE-Tags (§8 A1) ist davon unberührt (positive Schwelle `CIN > ~150`). |
| **`lightning_potential` (LPI)** | ✅ `icon_d2` liefert Werte (heute 0.0 = kein Gewitter, korrekt). Einbaubar — Modell fragen wir für PL schon ab. |
| **`thunderstorm_probability`** | ❌ `gfs_seamless` / `gfs_global` / `gfs_graphcast025` → **alle `None`**. Für unsere Koordinaten nicht verfügbar → **gestrichen** (Paket B2 entfällt). |
| **`lifted_index`, CIN bei `icon_d2`** | ❌ `icon_d2` liefert beide **leer** → bestätigt, dass das GFS-Supplement für LI nötig ist. |

**Wichtiger Vorbehalt:** `weather_code`-Gewitter (95/96/99) wird vom Modell aus
**CAPE + LI** berechnet. ICON-CH1 liefert **kein LI** → Gewitter-Codes der
CH-Modelle sind potenziell unzuverlässig; unser **GFS-LI-Supplement ist nötig**,
nicht Kür. Hagel-Codes 96/99 gibt es nur über ICON-D2.
(ECMWF IFS taugt laut Open-Meteo gar nicht für Gewitter — „barely no
information about atmospheric stability".)

---

## 5. Wie verlässlich ist die LPI-Blitz-Prognose für die Alpen?

LPI ist eine **Modell-Prognose**, kein Sensor (≠ Blitz-*Messung* wie
MeteoSchweiz-Blitznetz/Blitzortung). Open-Meteo serviert die **grid-scale LPI
nach Lynn & Yair (2010)** aus ICON-D2 (J/kg, ~48 h, Update alle 3 h).

**Validierungslage (ehrlich):**

- **Gut:** Auf Region-/Jahresebene korreliert LPI stark mit echten Blitzen
  (r ≈ 0,85 gegen LINET, DWD-Report 010). Schlägt einfache CAPE-Proxys und die
  Konvektionsregen-Heuristik, weil die Wolkenphysik (Graupel) eingeht.
- **Einschränkungen fürs Bergland:**
  1. **Nur flächig skillful (~150–220 km), nicht spotgenau** (COSMO-D2 FSS,
     ASR 2022). „Region heute" ja — „Spot um 14:00" nein.
  2. **Überschätzt im Alpenraum die Fläche** und erzeugt **Fehl-Signale über
     Graten/Gipfeln** (orografisches Aufwind-Artefakt; in Malečić 2023 mussten
     diese herausgefiltert werden).
  3. **Zeitlich nur same-day (0–24 h) verlässlich:** Onset ~1 h zu früh, abends
     Unterschätzung, nachts Überschätzung. Tag 2 wackelig, **Tag 3–5 kein LPI**.
  4. **Verschiebung statt Miss:** Zellen sind meist falsch platziert/getimt, nicht
     ausgelassen (Doppelstrafe-Effekt) — „trockener" Punkt neben „Blitz-Punkt"
     ist Unsicherheit, keine saubere Entwarnung.
- **Ehrlich:** Es gibt **keine** veröffentlichte POD/FAR/CSI speziell für die
  Schweiz; nur Zentraleuropa-/Kroatien-Studien.

**Empfehlung:** als **zusätzliche Stimme** nutzen, nicht als alleiniges Orakel.
Flächig auswerten (nicht eine Gitterzelle), **fail-safe** (Fehlen eines Signals
ist schwächere Entwarnung als ein Signal eine Warnung ist), Grate-Ausreißer
dämpfen, mit CAPE + Trigger gegenprüfen, J/kg **nicht roh** zeigen, sondern
bucketn (Start ~7 / ~12 / ~24 J/kg) und gegen Schweizer Blitzdaten kalibrieren.

---

## 6. Brauchen wir CAPE noch, wenn wir die Blitz-Prognose haben? — Ja.

LPI **ersetzt CAPE nicht**:

| Grund | Warum |
|---|---|
| **LPI deckt nur die oberste Stufe ab** | Es flaggt nur **Blitz**. Die für Piloten ebenso gefährliche **Überentwicklung/Schauer** (Regen, Böen, Abwinde — ohne Blitz) sieht LPI nicht. Diese Stufe erkennen wir nur über CAPE/CIN/Feuchte. |
| **CAPE arbeitet auch woanders** | CAPE steckt in der **Thermik-Berechnung** (`thermik_calculator.py`: Overshoot-Budget, CIN-Bremse) — unabhängig von Gewitter. Fällt nicht weg. |
| **Reichweite** | LPI nur ~48 h. Für **Tag 3–5** gibt es **kein LPI** — da ist CAPE/CIN das einzige Gewitter-Signal. |
| **Sie ergänzen sich** | LPI wird aus CAPE-getriebenen Aufwinden berechnet — eine nachgelagerte Schätzung, kein Ersatz. Literatur rät ausdrücklich, LPI **nicht solo** zu nutzen, sondern mit CAPE + Trigger gegenzuprüfen (DWD baut dafür eigens die MLPI-/KO-Korrektur ein). |

**Bild:** CAPE = Treibstoffstand; LPI = fertiges Warnlämpchen. Das Lämpchen ist
praktisch, leuchtet aber nur für die schlimmste Stufe, nur ~2 Tage, und ist im
Bergland etwas zu nervös. → Treibstoffstand behalten, Lämpchen **zusätzlich**
dazu. Zwei unabhängige Quellen, die sich absichern = genau richtig für eine
Sicherheits-App.

---

## 7. Was im Code aktuell passiert (Ist-Stand)

- **`[THUNDERSTORM]`** — echtes Gewitter-Signal aus `weather_code` 95/96/99
  (`skills/shared/*/03_safety/01_tags_safety.md`). DANGER-Level → Stunde
  unfliegbar.
- **`[CAPE-DANGER]`** — CAPE > `CAPE_DANGER_JKG` (1500 J/kg) **oder** CAPE +
  aktiver Regen. DANGER-Level.
- **`[CAPE-WARN]`** — CAPE erhöht (`CAPE_WARN_JKG` = 800 J/kg) **ohne Trigger**.
  WARN-Level, bleibt fliegbar — korrekt als reines Potenzial gelabelt.
- **CIN/Deckel im Thermik** — kein separater Rating-Abzug mehr (Block am
  2026-06-28 entfernt). Der Deckel wirkt über `calculate_thermal_profile`
  (Penetrative Convection: Overshoot-Budget vs. CIN-Kosten) direkt auf
  `max_thermal_height`. Greift **nur im Thermik-Rating**, nicht bei den
  Safety-CAPE-Tags.
- **Synoptik** — `config.py` `SYNOPTIC_PRECIP_CAPE_KONVEKTIV` (300) /
  `SYNOPTIC_PRECIP_CAPE_GEWITTER` (800) für Niederschlags-Charakterisierung.

**~~Bekannter Etiketten-Bug~~ ✅ behoben 2026-06-28:** `email_service.py`
bucketete `"cape "` in denselben „Gewitter"-Topf. → Reines CAPE-WARN erschien
fälschlich als **„Gewitter"**. Fix: `"cape "` aus den Gewitter-Buckets entfernt
(Gewitter-Umbau) **+ eigenes „Überentwicklung"-Label** in `_SAFETY_KEYWORDS` /
`_PHENOMENON_KEYWORDS` (A2).

---

## 8. Empfohlene Schritte (gestuft)

**Beschlossener Umfang (A+B, nach Daten-Check §4a angepasst):**
1. ~~**A1 — Deckel-Gate für CAPE-Tags**~~ ✅ **erledigt 2026-06-28**
   (`weather_context.py`, 3× CAPE-Block): naked-CAPE-Fehlalarme gekillt. Das
   weiche `[CAPE-WARN]` wird unterdrückt, wenn **`CIN > config.CAPE_LID_CIN_JKG`
   (150, positiv!) ohne Trigger** (gedeckelt). `[CAPE-DANGER]` unangetastet;
   ohne CIN-Wert keine Unterdrückung (fail-safe). CIN-Daten aus ICON-CH (§4a).
2. ~~**A2 — E-Mail-Bucket entkoppeln**~~ ✅ **erledigt 2026-06-28**
   (`email_service.py`): CAPE-WARN ≠ „Gewitter", eigenes Label „Überentwicklung"
   in `_SAFETY_KEYWORDS` + `_PHENOMENON_KEYWORDS`.
3. **B1 — `lightning_potential` (ICON-D2)** dazunehmen (`config.py:276` /
   `fetch_weather.py:831`), als **unabhängige Stimme** neben `weather_code`,
   fail-safe & flächig (§5).
4. ~~**Bonus — CIN-Bremse-Bug fixen**~~ ✅ **erledigt 2026-06-28 — Block entfernt**
   statt Vorzeichen gefixt (`thermik_calculator.py`): griff vorher nie (§4a), und
   der Deckel wird ohnehin schon in `calculate_thermal_profile` modelliert
   (Penetrative Convection) → separater Abzug = Doppelzählung. Kein Rating-Effekt.

**~~B2 `thunderstorm_probability`~~ — GESTRICHEN:** Open-Meteo liefert für unsere
Koordinaten nur `None` (§4a).

**Mittelfristig (gründliche Lösung, später):**
5. **Blitz-Gate selbst rechnen** — Gefrierniveau + Wolkentop-Temperatur aus den
   ICON-D2-Drucklevels → **cold-cloud depth**. Trennt *Schauer* von *Gewitter
   mit Blitz* (Top ≤ −20 °C als notwendiges Kriterium).

**Sauberes 3-Stufen-Tiering fürs UI (Zielbild):**
- **Cumulus** (CAPE>0, Top > −10 °C) → Thermik, kein Sturm.
- **Überentwicklung/Schauer** (Zutaten erfüllt, Top −10…−20 °C) → Regen/Böen,
  Piloten-Vorsicht, **kein Blitz**.
- **Gewitter/Blitz** (Top ≤ −20 °C + große cold-cloud depth + starker Aufwind +
  LPI/`weather_code`) → Blitzrisiko.

**Querschnitt:** Schwellen **saisonal gegen Schweizer Verifikationsdaten**
(MeteoSchweiz/EUCLID/Blitzortung) kalibrieren — die J/kg-Skala ist
modell-/konfigurationsabhängig.

---

## Quellen

**Meteorologie / Physik**
- Doswell, Brooks & Maddox 1996, *Flash Flood Forecasting: An Ingredients-Based
  Methodology*, Wea. Forecasting 11 — https://www.nssl.noaa.gov/users/brooks/public_html/papers/ffingred.pdf
- NWS Skew-T-Parameter & Schwellen — https://www.weather.gov/source/zhu/ZHU_Training_Page/convective_parameters/skewt/skewtinfo.html
- NWS Lightning Electrification — https://www.weather.gov/safety/lightning-science-electrification
- MeteoSchweiz, Wie Gewitter entstehen — https://www.meteoswiss.admin.ch/weather/weather-and-climate-from-a-to-z/thunderstorms/how-thunderstorms-form.html
- Yair et al. 2010, LPI (JGR) — https://agupubs.onlinelibrary.wiley.com/doi/abs/10.1029/2008JD010868
- Molinié et al. 2004, Wolkentop-Temp vs. CG-Blitz (JGR) — https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2003JD003593
- EUMETRAIN Stabilitäts-Indizes / KO-Index — https://resources.eumetrain.org/data/1/15/stability.htm · https://resources.eumetrain.org/data/2/20/Content/theory_ko.htm

**Open-Meteo Datenlage**
- DWD ICON / ICON-D2 — https://open-meteo.com/en/docs/dwd-api
- MeteoSwiss ICON-CH1/CH2 — https://open-meteo.com/en/docs/meteoswiss-api
- GFS (inkl. `thunderstorm_probability`) — https://open-meteo.com/en/docs/gfs-api

**LPI-Validierung**
- DWD *Reports on ICON* 010, Schröder/Göcke/Köhler 2022 (LPI/MLPI-Formel,
  LINET-Verifikation r≈0,85, Doppelstrafe, Tagesgang) — https://www.dwd.de/EN/ourservices/reports_on_icon/pdf_einzelbaende/2022_10.pdf
- Bağ Fırat et al. 2022, ASR 19, 29–40 (COSMO-D2 LPI Skill-Scale ~220 km vs.
  EUCLID) — https://asr.copernicus.org/articles/19/29/2022/
- Malečić et al. 2023, WCD 4, 905–923 (Alpen-Adria 2.2 km LPI, Flächen-Überbias,
  orografische Artefakte) — https://wcd.copernicus.org/articles/4/905/2023/
- Saleh et al. 2023, E&SS (LPI > CAPE×precip für Blitz-Lokalisierung) — https://agupubs.onlinelibrary.wiley.com/doi/full/10.1029/2023EA003104

> **Vorbehalt zu Schwellen:** Die genannten Index-/LPI-Schwellen sind die
> publizierten Standardbereiche, aber klima-/regionsabhängig. Vor produktivem
> Vertrauen gegen eigene Schweizer Verifikationsdaten über eine Saison kalibrieren.
