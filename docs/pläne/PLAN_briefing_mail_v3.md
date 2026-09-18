# PLAN — Morgenbriefing-Mail v3: die Mail folgt der Piloten-Kette

**Stand:** 2026-09-09 · **Status:** Konzept entschieden, als **Vorschau-Seite**
umgesetzt (`scripts/preview_briefing_email.py` → `data/preview/briefing_preview.html`).
**Nicht in der App** — `email_service.py` und `templates/email/briefing.html`
sind unverändert. Übernahme in die versendete Mail erst auf ausdrückliche Ansage.

Umsetzung der Vorschau: `scripts/briefing_v3_context.py` (Datenschicht,
eigenständig — v2-Kontext und v2-Mail-Templates am 13.09. entfernt),
`templates/preview/briefing_preview_page.html` (Design-Seite, freies CSS). Es
gibt nur **eine** Vorschau: `data/preview/briefing_preview.html`. Rating-Farben aus `docs/RATING_FARBKONZEPT.md` v3.2.

---

## 1. Warum

Die bisherigen Entwürfe nannten **einzelne Spots** als Empfehlung und zeigten
die Synoptik als Zahlenraster. Beides widerspricht dem, was wir nachweislich
können und was Piloten brauchen.

### Wie Piloten Wetter beurteilen — die Kette ist überall dieselbe

> „Synoptic > mesoscale > microscale > reality." (r/freeflight)

| Stufe | SHV-Entscheidungsstrategie (Planung) | Flugschul-Briefings | DHV 3-Punkte |
|---|---|---|---|
| 1 | Grosswetterlage (Druckzentren, Isobaren) | Bodendruckkarte, MeteoSchweiz-Text | — |
| 2 | Fronten | DWD-Frontenkarte, „letzter guter Tag vor dem Umschwung" | trocken? |
| 3 | Föhn / Bise | ΔP Lugano–Zürich (≥ 4 hPa), Güttingen–Genf (≥ 2 hPa) | — |
| 4 | Wind gesamt / regional | 700 hPa × ⅔ = Bodenerwartung; Start > 20 km/h = Vorsicht | Wind ok? |
| 5 | Gewitter / Labilität | Emagram, CAPE, Überentwicklung | Thermik? |
| dann | Region → Spot → Luftraum (DABS) → Windsack vor Ort | | |

Quellen: Paragliding24-Checkliste, FLYwithMIKI, Flugschule Emmetten, SHV Meteo,
DHV Wetter, Burnair-Hilfe, Pararidge, SHV-App (lu-glidz 04/2026).

### Was keiner tut

Burnair (654 Regionen × 5 Tage als Farbkreise + PFD), XC Therm, Pararidge
(GO/CAUTION/NO-GO je Spot), Paraglidable — alle liefern Farben, Zahlen, Regeln.
**Niemand übersetzt die Kette in Sätze über Regionen hinweg.** In den Foren:
„by the time I've evaluated the fifth spot, I've forgotten the first" · „have a
friend who loves to find the right spot" · ein Pilot verschickt eine
Wochenprognose per WhatsApp und wird überrannt. Das ist unser USP: **die KI
erklärt, was der Code rechnet.**

### Was die Validierung erlaubt

| Aussage | Beleg | Verdikt |
|---|---|---|
| Region-Tagesqualität | 80–93 % Treffer bei Rating ≥ 4 · `validation/xcontest/2026-07-30_ANALYSE_genauigkeit.md:67-72,300` | tragend |
| Kein guter Tag verkannt | 15/15 · `…:159,176-178` | tragend |
| Thermik-Decke P75 | Bias +96 m · `validation/xcontest/TOPOUT_STICHPROBE.md:19-21` | tragend |
| Gewitter im Flugfenster | 90 % Erkennung, 54 % Fehlalarm live · `docs/GEWITTER.md:83-84`, `validation/gewitter/AUTO_REPORT.md:12` | mit Vorbehalt |
| Frontdurchgang | ~50 %, Timing −3 h · `validation/fronten/AUTO_REPORT.md:17-28` | Zeitraum, nie Uhrzeit |
| **Spot-Rangfolge** | Korrelation **0,01** · `…genauigkeit.md:266-290` | **raus** |
| `not_safe` je Spot | 33 % Fehlalarm · `…:48-49` | nur als Zählung |
| Steigen-Rangfolge zwischen Regionen | Perzentil 52 % = Zufall · `…49_TAGE.md:44-52` | nicht danach sortieren |

---

## 2. Die Entscheide (09.09.2026)

- **E1 Kette statt Datenstruktur.** Tag = Karte → Lage → Fronten → Föhn/Bise →
  Höhenwind (mit ⅔-Bodenerwartung) → Labilität → Warnungen → Regionen.
- **E2 Regionen statt Spots, zählen statt küren.** Klassen je Spot:
  **top & sicher** (Rating 4–5, grün) · **top mit Vorsicht** (4–5, amber) ·
  **nicht sicher** (rot) · **unter Top** (≤ 3, Sky). Balken + Text je Region und je Tag.
  Hero = Region mit den meisten Top-&-sicher-Spots. Kein Spot-Name in der Mail.
- **E3 Jede Zahl bekommt einen Satz — aber kurz.** Unter „Lage" **ein** Satz zur
  Gesamtlage Schweiz (erster Satz des Wochen-Leads) + Tages-Hinweis, **keine
  Zonen**; Fronten/Föhn/Bise/Höhenwind/Labilität je ein kurzer deterministischer
  Satz; Warnungen mit Satz inkl. Zahl; je Region **ein knapper Satz** (erster
  Satz der `recommendation`, ≤ 150 Zeichen). Vertrauen sichtbar. (Nachschärfung
  09.09. abends: Fliesstext war zu lang.)
- **E4 Woche ohne Fliesstext, Tag knapp.** Tages-Karten mit Urteil, Zählung
  der Abo-Regionen, Kontextzeile „CH x/29", Druck immer, Höhenwind, das eine
  Auffällige, `flight_hint` nur ≤ 60 Zeichen. Darunter die **Tabelle Region ×
  Tag mit vollen Namen** (Zelle = Rating 1–5 in der Klassenfarbe, sortiert nach
  bester Klasse der Woche) — Balken und Kürzel-Kacheln wurden zweimal nicht als
  Regionen gelesen. **Kein Wochen-Absatz** mehr. Regionen als kompakte Zeilen (Name · Fenster · Rating ·
  Zählung · ein Satz · Link) — lesbar bei 4 wie bei 29 Regionen. Keine
  Steigen-/Stunden-Mittelwerte je Region: ein Median über Spots mit 8 h und
  Spots mit 0 h sagt nichts.
- **Synoptik-Karte immer, aus der App** (Entscheid 14.09.): Screenshot von
  `#bfSynoptic` auf der Kartenseite `/synoptik/karte?day=N` — dieselbe
  Gleitcast-Karte (`synoptic-embed.js`, Druckbänder, Isobaren, H/T, Stand 12:00),
  aber per `data-ausschnitt="festland"` enger auf das europäische Festland und
  per `data-wind="pfeile"` mit den statischen 700-hPa-Pfeilen aus
  `synoptic-wind.js`. Die Minikarte auf `/briefing` bleibt unverändert.
  `scripts/synoptik_snapshot.js` (Playwright) läuft auf dem Server; die Vorschau
  schickt es per SSH hin und holt das PNG. Lokal testen ohne Deploy: App lokal
  starten, `ssh -R 15055:127.0.0.1:5055 …` und die Kartenseite über den Tunnel
  fotografieren. Der frühere
  Nachbau (Alpen-Ausschnitt, DWD-Fronten, lokales Chrome über `file://`) lieferte
  leere Bilder und wich von der App ab — entfernt. Die DWD-Fronten bleiben als
  Satz in der Kette (Stufe 2).

### Nachschärfung 13.09. (annotiertes PDF des Users)

- **Tages-Karten:** Druck/Höhenwind oben, dann Regionen; die Zählung nennt die
  Top-Regionen beim Namen („Top & sicher: …" / „Top mit Vorsicht: …").
- **Lage in 3 Sätzen** — Sätze des Wochen-Leads, die einen anderen Wochentag
  nennen, fallen raus.
- ~~Warnungen = Warn-Labels der App je Region~~ — ersetzt am 15.09., siehe unten.

### Entscheid 15.09.: Warnungen gelten für die ganze Schweiz

- **Zuerst die Gesamteinschätzung:** Schalter-Zeile Regen · Gewitter · Föhn ·
  Bise · Starker Wind (ja/nein). **Der Code schaltet** —
  `engine/synoptic_llm.hazard_checks()` aus `precip_zones` (Nässe ≥
  `SYNOPTIC_HAZARD_RAIN_WET_SHARE`), `gewitter_share`/`konvektion`, `foehn`,
  `bise`, `wind_zones` (verblasen/stark eingeschränkt).
- **Dann je aktiver Gefahr ein KI-Satz:** wo in der Schweiz (Synoptik-Zonen,
  Alpennord/-süd), woher/wohin (Zugbahn), wann. Neues Skill-Feld
  `llm_overview.hazards` im selben LLM-Aufruf; der Validator lehnt Themen ab,
  die der Code nicht schaltet, und Sätze ohne Ortsbezug. Darunter der
  Code-Satz mit Zahl.
- **Tagesverlauf statt Tagespauschale (16.09.):** Zu jeder Gefahr rechnet
  `hazard_checks()` die betroffenen Tagesfenster je Zone
  (`SYNOPTIC_DAY_WINDOWS`, Schwellen `SYNOPTIC_HAZARD_WINDOW_*`) und daraus
  `day_shape` (`ganztags` / `ab` / `bis` / `nur` / `spanne` / `wechselnd`)
  sowie `tomorrow` (Folgetag-Trend, Schwelle
  `SYNOPTIC_HAZARD_TREND_RATIO`). Beides geht als `day_shape`/`windows`/
  `tomorrow` in den LLM-Payload; der Validator verlangt eine Tageszeit im
  Satz, sobald `day_shape` nicht `ganztags` ist (`no_time`). Der Code-Satz
  zeigt es unabhaengig vom LLM: "Zeitfenster: Alpennordhang ab Mittag,
  Tessin nur Abend. Folgetag: schwaecher." Begruendung: ein verregneter
  Nachmittag ist kein verlorener Tag — die Pauschale macht ihn dazu
  (Vorfall 25.07.2026).
- **Ton: Wetterbericht, nicht Zonen-Protokoll (16.09.):** Der KI-Satz ist
  Fliesstext mit einem Vorgang ("ab Mittag greift Regen auf die
  Alpennordseite ueber"), nie "<Gebiet>: <Zustand>". Der Validator lehnt
  Doppelpunkt und Aufzaehlungszeichen im Gefahren-Satz ab (`enumeration`).
  Auch der Code-Satz fasst Raeume zusammen statt Zonen aufzuzaehlen:
  4 Zonen = "landesweit", 3 = "ueberall ausser im Tessin", Ortsangabe im
  Satz ("verblasen am Alpennordhang"), gleiche Zeitfenster gebuendelt.
  Vorbild: MeteoSchweiz/meteo.ch-Prognosetext.
- **Tagesrein (16.09., korrigiert):** Die Warnungen stehen in Sektion 2
  ("Heute im Detail") — der Gefahren-Satz gilt AUSSCHLIESSLICH fuer diesen
  Tag. Kein "Folgetag", kein Wochentag, kein "morgen" (Validator-Regel
  `cross_day`); dieselbe Logik, die `_situation_sentences()` beim Lead schon
  anwendet. Mehrtages-Entwicklung gehoert in den `lead` bzw. in Sektion 1.
  `facts["tomorrow"]` wird weiter berechnet, geht aber weder an den LLM noch
  in die Tages-Warnbox — Reserve fuer eine 3-Tage-Sektion.
- **Foehn mit Tagesverlauf (16.09.):** `decide_foehn_summary` liefert je Tag
  `nord_windows`/`sued_windows` (Stunden + Spitze je Tagesfenster). Daraus
  in `hazard_checks`: `day_shape` (ab wann greift er durch), `course`
  (`zunehmend`/`abflauend`/`gleich` INNERHALB des Tages, Spitze vor
  Stundenzahl) und `lee_gust_kmh` (Boeen-P90 im Lee als sichtbare Spur in
  den Winddaten). Skill verlangt alle drei im Satz: wie stark, wie es sich
  ueber den Tag entwickelt, woran man es sieht. Alte Caches ohne die Felder
  schalten die Zusaetze einfach ab.
- **Zonen mit unterschiedlichem Verlauf (16.09.):** `day_shape` = `gemischt`,
  sobald die Zonen zeitlich auseinanderlaufen — die Vereinigung ihrer Fenster
  ("ganztags") war falsch (Vorschau: Wind am Alpennordhang ganztags, KI schrieb
  "all day" auch fuer Wallis/Graubuenden). Validator: bei `gemischt` mindestens
  zwei Zeitangaben (`time_not_differentiated`), und je Zone darf der genannte
  Beginn nicht SPAETER liegen als ihr erstes Fenster (`onset_too_late` — zu spaet
  gewarnt ist die gefaehrliche Richtung). Code-Zeile: eine Gruppe ohne Ort, zwei
  Gruppen beide mit Ort, ab drei nur der frueheste Einsatz ("Zeitlich gestaffelt:
  ab Vormittag am Alpennordhang, anderswo spaeter"). Unterbrochene Verlaeufe
  nennen jeden Abschnitt ("am Vormittag und wieder ab Nachmittag").
- **Entscheide 16.09. (User):**
  1. Kein Urteil im Tagessatz — der Pilot entscheidet. Statt des Zonen-Hinweises
     ("No usable window") fasst `_day_summaries()` die Gefahren-Schalter in einen
     Satz: "Regen und starker Wind erschweren das Fliegen." (Sektion 1 + 2).
  3. Hoehenwind: dazu steht, was der Wert ist — "Mittelwert ueber alle Schweizer
     Spots, 12 Uhr" (Vektor-Mittel, gegenlaeufige Winde heben sich auf).
  4. Warn-Chips der Regionen in Klartext (`_chip_text`): "Wolken bis auf
     Starthoehe" statt "Clouds Base 1400m ≤ region ref 1500m".
  5. Keine deutschen Reste in der englischen Mail: Lage-Label, Zugbahn-Namen,
     Druckzentren (`ctr_*`, Test prueft jeden Punkt aus EUROPE_PRESSURE_GRID).
  6. Kein Platzhalter bei Regionen ohne Satz. 7. Kein Schnitt mitten im Wort.
  - KI-Saetze kurz: Gefahren-Satz GENAU ein Satz, max 25 Woerter
    (`HAZARD_MAX_WORDS`); neues LLM-Feld `day_lines` — je Tag ein Satz, max 20
    Woerter (`DAY_LINE_MAX_WORDS`), ersetzt in "Lage" die drei Lead-Saetze. Beide
    ohne Urteil ueber das Fliegen (`verdict`), Validator erzwingt Laenge und Satzzahl.
  - Sprach-Drift behoben: Korrektur-Nachricht nennt die Ausgabesprache, Validator
    meldet deutschen Text im EN-Modus (`wrong_language`). Vorfall 16.09.: nach zwei
    Korrekturrunden kam der ganze Block deutsch zurueck.
  - Code-Zeile ohne Zeiten, sobald ein KI-Satz da ist (der nennt sie, geprueft
    auf zu spaeten Beginn) — nur Ausmass und Zahlen; ohne KI-Satz wie bisher mit Zeiten.
  - Lage-Label je Tag (`decide_lage_label_for_day`, gleiche Hierarchie aus den
    per_day-Feldern): 16.09. "South-westerly flow" statt "North foehn" (Foehn erst Do).
  - Betreff in der Sprache der Kacheln: "Do und Fr sicher" / "Heute mit Vorsicht" /
    "Kein sicherer Tag" statt "fliegbar" — kein Urteil.
  - Hoehenwind zusaetzlich regional (`decide_aloft_regional`, neues Kontextfeld
    `aloft_regional`): je Region und Stunde der Median ueber ihre Spots (Schutz vor
    Einzelspot-Ausreissern, Regionen unter `SYNOPTIC_ALOFT_REGION_MIN_SPOTS` = 3
    zaehlen nicht), davon die Spitze 06-18 Uhr, dann die staerkste Region. Eine
    Region genuegt. 16.09.: Mittel 18 km/h, regional bis 59 km/h (Jura Zentral).
  2. Tages-Einstufung aus den Abo-Regionen statt aus dem besten Startplatz
     (`_day_verdict`): Not safe, wenn MEHR als die Haelfte Not safe ist; Safe,
     wenn MINDESTENS die Haelfte Safe ist; sonst Caution. Zahl = Mittelwert der
     Regions-Bewertungen, gerundet. Schwellen: `BRIEFING_DAY_*_SHARE`. Betreff
     folgt derselben Einstufung. Nur v3 — `email_service` (laufende Mail) ist
     unveraendert.
- **Keine Regionsliste in den Warnungen** — die Regionen folgen danach, ihre
  Warn-Chips bleiben in den Regionszeilen.
- Ohne `hazards` im Cache (älterer Lauf) zeigt die Vorschau Schalter +
  Code-Satz. Neuen Skill lokal testen:
  `python scripts/preview_synoptik_zonen.py` →
  `python scripts/preview_briefing_email.py --synoptik data/_preview_synoptik_zonen.json`.
- **Regionen einzeln, kompakt:** Name · Fenster · Rating, Warn-Chips, ein Satz
  (max. 2 Zeilen), Text-Link. Spot-Balken und Spot-Zählung je Region entfallen
  (Zählung steht in den Tages-Karten).

---

## 2b. Design-System der Vorschau (ui-ux-pro-max, 09.09.)

Abgeleitet mit dem Skill `ui-ux-pro-max` (Marketing-Repo): Muster
**„Real-Time / Operations"** (Statusfarben, datendicht aber scannbar), Stil
**„Executive Dashboard"** (wenige grosse Kennzahlen, Ampel-Indikatoren,
Ein-Seiten-Überblick) mit Flat-Disziplin (keine Gradienten/Schatten als Zierde).

| Token | Wert | Herkunft |
|---|---|---|
| Primär / vivid / light | `#0369a1` / `#075985` / `#e0f2fe` | Aviation Blue der App (`static/css/style.css`) |
| Akzent (Warnung) | `#d97706` auf `#fef3c7` | Weather-App-Palette, WCAG-korrigiert |
| Text / sekundär / gedämpft | `#1e293b` / `#475569` / `#64748b` | App-Tokens, alle ≥ 4.5:1 auf Weiss |
| Schrift | **Lexend** (Text, auf Lesbarkeit entworfen) + **Fira Code** (Zahlen, tabular) | Pairing „Corporate Trust" / „Dashboard Data" |
| Skala | 12 (nur Mono-Labels) · 14 · 16 (Basis) · 18 · 24 · 32 | Regel `font-scale`, `readable-font-size` |
| Abstände / Radien | 4 · 8 · 12 · 16 · 24 · 32 / 8 · 12 · 16 | Regel `spacing-scale` |
| Icons | Inline-SVG (Lucide-Pfade: sun, alert-triangle, x-circle, help-circle, chevron) | Regel `no-emoji-icons` |
| Interaktion | Tippziele ≥ 44 px, `cursor:pointer`, Hover 150 ms, `:focus-visible`, eine Einstiegsanimation, `prefers-reduced-motion` | Regeln §1, §2, §7 |
| Rating-Farben | unverändert Palette v3.2 | `docs/RATING_FARBKONZEPT.md` |

## 3. Datenbausteine

| Block | Quelle | Stand |
|---|---|---|
| Lage, Zentren, Trend | `synoptic_context.json`: `lage_label`, `pressure_centers_per_day`, `pressure_influence` | da |
| Fronten | `data/dwd_fronten_archiv/analyse/dwdc_*.geojson`, `vorhersage/dwd_fronten_*_0xx.geojson`, `validation/fronten/aussagen/passagen_*.json` (Scheduler 4×/Tag) | da, Quelle DWD |
| Föhn / Bise | `foehn.per_day[]`, `bise.per_day[]` | da |
| Höhenwind | `flow_overhead.per_day[]` | da |
| Labilität | `t850_trend`, `konvektion.per_day[].zones`, `confidence_per_day` | da |
| Sätze je Tag | `llm_overview.zones[].days[]`, `long_with_sources[].flight_hint` | da (zonenbezogen) |
| Zählung je Region | aus `top_spots[]` (`safety_band` × `experience_rating`) | da |
| Steigen / Arbeitshöhe / Stunden | `top_spots[].analysis_full._rating_inputs` → Median/P75 je Region | da |
| Region-Satz | `top_regions[].recommendation` | da (heute 0/29, Folgetage 23–29/29) |
| Startrichtung je Region, Luftraum/DABS | — | weglassen |

**Offen für die App-Übernahme:** i18n-Keys (`_L3` in `briefing_v3_context.py`),
Karten-Screenshot 1×/Tag im Versand-Job erzeugen und als Inline-Bild (CID) anhängen
(Mail-Clients laden kein JS, `data:`-Bilder blocken Gmail/Outlook),
~~Carto-Key in den App-Karten~~ (16.09. gebaut: `CARTO_API_KEY` → `wcCartoUrl()` an 19 Kachel-URLs, Parameter heißt `key`; Key liegt lokal und auf dem Server im `.env`. Live seit 16.09., Commit `d07b0a8`),
Fronten-Feed aus dem Validierungs-Zweig in die Produktionskette heben.
(Erledigt 15.09.: schweizweite Gefahren-Sätze als LLM-Feld `hazards`.)

---

## 4. Prüfen

```
python scripts/preview_briefing_email.py                          # heute
python scripts/preview_briefing_email.py --tag 2026-09-11         # Tag mit Sätzen
python scripts/preview_briefing_email.py --regions berner_alpen,jura_zentral,oberwallis_goms,tessin_sopraceneri
```

Kein Spot-Name in der Seite · Streifen mit `FORECAST_DAYS` Spalten und einem
Segment je Abo-Region · Karte mit Isobaren, H/T, Fronten und Stand · Kette in der
Reihenfolge 1–5 · Warnsatz mit Zahl · Region-Zählung summiert auf die Spot-Zahl ·
Leerzustand statt erfundener Prosa.
