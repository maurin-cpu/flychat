# Gleitcast Rating-Konzept: Risk vs Reward Trennung

**Status**: Draft v1.3 – Konzept aktualisiert nach Preview-Iteration, bereit fuer Implementation
**Autor**: Alex (PM)
**Datum**: 2026-04-30
**Version**: 1.3 (v1.0 Konzept, v1.1 UI-Scan-Optimierung, v1.2 Konsistenz-Check, v1.3 Preview-Erkenntnisse)

---

## Aenderungen in v1.3 (Preview-Iteration)

Nach Bau und Review der Preview (`docs/rating_preview.html`) wurden vier Designentscheidungen geaendert:

1. **Pilotenprofil-Filter wird zurueckgestellt** (war §2.2, §8.5 zentraler Pfeiler). Begruendung: vereinfacht Phase 1, vermeidet Profil-Disclaimer-Diskussion. Kann als v1.5 zurueckkommen — siehe §10 Backlog. Im Code keine Hooks.
2. **Sub-Rating-Symmetrie**: Das bewaehrte 4-Sub-Rating-Pattern (heute nur fuer Fliegbarkeit) wird auf Safety ausgedehnt — siehe neue §3.5. Symmetrische Achsen mit unterschiedlicher Aggregation: Experience nutzt gewichteten Durchschnitt, Safety nutzt **Weakest-Link (MIN)** weil Sicherheit asymmetrisch ist. **5 Safety-Sub-Ratings** (wind/gust/aloft/foehn/weather — letzteres deckt Niederschlag/Gewitter/CAPE/Sicht ab). Bedingt einen vierten Vorab-Fix (§9.4 Fix 4).
3. **Region-Tab als Leaflet-Karte** (statt Card-Grid mit 7-Tage-Tabelle aus altem §4.3). Polygone aus `data/regionen_polygone_mapped.geojson`, gefaerbt nach `safety_band`. Klick oeffnet Region-Overlay. 2D-Scatter wird zur **regionen-aggregierten Bubble-Matrix** im Briefing-Tab (war 2D-Scatter mit 488 Spots → unleserlich).
4. **Rote Spots koennen `noAnalysis`-Zustand haben** — wenn Bedingungen so eindeutig nicht fliegbar sind, dass keine vertiefte Auswertung erstellt wird (z.B. Windrichtung passt grundsaetzlich nicht). Spot-Panel zeigt dann Hero + minimalen "Keine Analyse"-Block, kein Meteogramm. Siehe §8.6 Update.

---

## Wie hier weiterarbeiten (Resumption Guide)

Dieser Abschnitt ist der **Wiedereinstieg fuer eine neue Session**. Lies ihn zuerst, dann TL;DR, dann gezielt die Sektion(en), an denen du arbeitest.

### Was wurde entschieden (kurzfassung)

- **2-Achsen-Modell** fuer Spot-/Region-Bewertung statt heutigem vermischtem `flyability_tier`.
- Achse 1: **`safety_band`** = `green` / `amber` / `red` — rein Sicherheit (Wind, Boeen, Foehn, Aloft).
- Achse 2: **`experience_score`** (0–100, dargestellt als 1–5 Sterne) — Erlebniswert (Steigen, produktive Stunden, XC-Potential).
- Hilfsachse: **`comfort_index`** (0–100) — nur "Texture" im Spot-Panel, nicht Primaer.
- **Karten-Marker**: Single-Glyph (Sektion 8.2) — innerer Kreis = Safety-Farbe, weisse Ziffer 1–5 = Stars, bei `red` weisses Kreuz statt Ziffer. Wind-Sektor bleibt unveraendert.
- **Pilotenprofil**-Schalter (Beginner / Intermediate / Advanced / Pro) lebt in der bestehenden Karten-Legende (`map.js:115`), aendert nur Opacity der Marker — nicht die Rohdaten.

### 4 Vorab-Fixes vor Phase-1-Implementation (BLOCKER)

Aus Sektion 9.4 — diese muessen ZUERST passieren, sonst baut Phase 1 auf Sand. **Reihenfolge v1.3: 2 → 1 → 3 → 4** (von einfach zu komplex, jeder Fix testbar fuer sich).

1. **`decide_flyability_downgrade` aufspalten** (`engine/decision_engine.py:361`):
   - Heute drei verschiedene Trigger im selben Bucket (keine Thermik / Klapper-Gefahr / wenig produktiv).
   - Aufteilen: rough_pct > 50 → wirkt auf `safety_band` (amber/red); restliche Quality-Trigger → wirkt auf `experience_score`.
2. **`is_conditional` aus LLM-Hand nehmen**: Heute LLM-gesetzt, verletzt Stage-Inversion. Muss von Decision-Engine deterministisch ueberschrieben werden, analog zu `safety_status`.
3. **`rating`-Feld** (`engine/_common.py:421`) als Quelle fuer `experience_score` wiederverwenden, NICHT neu erfinden. Es existiert bereits ein deterministisches 0–10-Rating aus 4 Sub-Ratings — restrukturieren statt neu bauen.
4. **NEU v1.3 — Safety-Sub-Ratings einfuehren** (siehe §3.5): Symmetrie-Erweiterung. LLM-Prompt gibt 4 Safety-Sub-Ratings (wind/gust/aloft/foehn, je 1–10), neue Aggregations-Funktion `_compute_safety_rating` in `engine/_common.py`, neue Cache-Felder. Decision-Engine Hard-Overrides bleiben Vorrang vor Score.

**Empfohlene Implementierungs-Reihenfolge** (geaendert v1.3 von 1→2→3 auf 2→1→3→4):
- Fix 2 zuerst (kleinster Eingriff, klaert Stage-Inversion-Pattern)
- Fix 1 danach (Refactor mit Tests, baut auf sauberer Stage-Inversion auf)
- Fix 3 danach (Skalierung des bestehenden Ratings, kein LLM-Eingriff)
- Fix 4 zuletzt (LLM-Prompt-Aenderung, broaderer Impact, profitiert von etablierten Test-Patterns aus 1-3)

### Migration in 3 Phasen (aus Sektion 9.6)

| Phase | Inhalt | Aufwand |
|-------|--------|---------|
| Vorab-Fixes | 3 Decision-Engine-Refactorings (oben), Tests | 2–3 Tage |
| Phase 1 | Server liefert `safety_band` + `experience_stars` + `comfort_index`; UI-Karte + Spot-Panel umstellen; `flyability_tier` bleibt im Cache | 5–7 Tage |
| Phase 2 | Chat-Engine + Mail-Templates auf neue Sprache; `flyability_tier` deprecaten | 4–6 Tage |
| **Total** | Solo-Entwickler, ueber 2–3 Monate verteilt | **12–16 Tage** |

### Pflicht vor Code (aus Sektion 7 + 8.10)

- 5 User-Interviews mit Mock-Up der neuen Glyphe (Lesbarkeit Ziffer auf 9px Marker, Color-Blind-Test).
- 1h Anwaltsgespraech zu Disclaimern: "amber/4 Sterne" ist aktivere Empfehlung als heutiges violet — Haftungsperspektive Schweiz.
- Entscheidung: Soft Cutover oder Klassisch/Neu-Toggle? Empfehlung Soft Cutover (Sektion 8.7), aber Validierung fehlt.

### Wichtigste Dateien fuer die Implementation

- `engine/decision_engine.py` — alle `decide_*`-Funktionen, insbesondere `decide_flyability_downgrade:361`
- `engine/_common.py:421` — bestehendes `rating`-Feld
- `engine/analyzers.py` — `_post_process_*`, schreibt `caution_notes` / `no_go_reasons`
- `engine/weather_context.py` — Cache-Befuellung, productive_thermal_h, rough_pct
- `engine/chat_orchestrator.py` + `prompts.py` — Chat-Engine-Sprache (Phase 2)
- `static/js/map.js:174,245,500,528` — `mapSafetyAndQualityToStyle`, `createSpotIcon`, Rating-Badge
- `static/js/meteogram.js` — `renderAnalysisView` (Spot-Panel)
- `static/css/style.css:52,86` — `--color-safety-*` Tokens, Tier-Tokens
- `templates/index.html` — Layout
- `docs/DECISIONS.md` — kanonische Decision-Tabelle (muss bei Aufspaltung aus Vorab-Fix 1 mitziehen)

### Offene Fragen (zu entscheiden vor Phase 1)

1. Welche Schwellen genau fuer `experience_score` → 1/2/3/4/5 Sterne? Sektion 8.3 nennt Beispiel-Werte, sind aber nicht final.
2. Wie wird `productive_thermal_h` mit `peak_climb_rate` gewichtet im `experience_score`? Heute gibt es 4 Sub-Ratings im `rating`-Feld — diese behalten oder neu mischen?
3. Werden `caution_notes` und `no_go_reasons` aufgeteilt nach Achse (safety vs. experience), oder bleiben sie als gemeinsame Liste mit Tag pro Eintrag?
4. Pilotenprofil-Default: `Intermediate` — ist das richtig, oder sollte das System aus historischen Klick-Mustern lernen (Phase 3)?

### Was NICHT umgekippt wird

- Decision-Engine-Pattern (Stage-Inversion: LLM → Decision-Engine ueberschreibt) bleibt unveraendert.
- `_decisions_applied`-Tracking bleibt unveraendert, lediglich Decisions wirken auf neue Achsen.
- Open-Meteo-Datenfluss + Cache-Struktur (`wetterdaten.json`) unveraendert.
- Wind-Sektor auf Karten-Marker unveraendert.

### Wie weitermachen in einer neuen Session

1. **Diese Datei lesen**, Sektion 8 (UI v1.1) + Sektion 9 (Konsistenz v1.2) im Detail.
2. `docs/DECISIONS.md` lesen — gibt den Stand der Decision-Engine.
3. Entscheidung: Beginnen mit Vorab-Fix 1 (`decide_flyability_downgrade` aufspalten)? Wenn ja, Tests in `tests/test_decision_engine.py` ergaenzen, dann implementieren.
4. Falls die Strategie geaendert werden soll: TL;DR + Sektion 2 + 9.7 sind die "Definition of Concept" — alles andere folgt daraus.

---

## TL;DR

Das heutige `flyability_tier` (green/violet/gray) vermischt Sicherheit und Erlebnis und ist deswegen fuer ambitionierte Piloten paternalistisch. Empfehlung:

**Zwei-Achsen-Modell mit Pilotenprofil-Filter.** Server liefert deterministisch zwei separate Scores pro Spot/Tag:

1. `safety_band` – `green` / `amber` / `red` (Wind, Boeen, Foehn, Aloft – aus bestehendem `safety_status` + Decisions)
2. `experience_score` – Punktzahl 0–100 (Steigen, produktive Stunden, XC-Potential, Comfort – aus `peak_climb_rate`, `productive_thermal_h`, `tq_danger_h` ohne rough)

Plus ein dritter Hilfswert:
3. `comfort_index` – 0–100, getrennt vom Erlebnis (rough_pct, Turbulenz-Profil) – nicht primaerer Score, aber als "Texture" anzeigen.

**Karte**: Farbe = Safety-Band (Risiko), Sterne 1–5 = Erlebnis (Reward). Doppel-Encoding wie bei Magicseaweed (Sterne fuer Swell + ausgegraute Sterne fuer Wind), aber explizit getrennt: Form/Farbe = Sicherheit, Fuellung = Potential.

**Pilotenprofil** (Beginner / Intermediate / Advanced / Pro) verschiebt nur Schwellen und Filterung – aendert nichts an den Rohdaten. Pro-Pilot sieht "amber + 5 Sterne" als attraktivsten Tag des Monats; Beginner sieht nur green-Tage.

`flyability_tier` bleibt im Cache als legacy/fallback, ist aber im UI nicht mehr Primaer-Signal.

---

## 1. Benchmark-Recherche

### 1.1 Burnair (direkter Wettbewerber Schweiz)

- 5-stufiges Farbschema fuer Thermik (ganzer Tag + halbstuendlich)
- **Wind**: separat dargestellt – Pfeil mit innerer Fuellfarbe (Mittelwind) + Rand (Boeen). Trennung Mittelwind/Boeen ist visuell sauber.
- **Algorithmus**: ueber 40 Faktoren, eigene "Thermikeinschaetzung", aber weiterhin **ein** Gesamt-Tier
- **Disclaimer**: "Farben entsprechen dem Skill-Level eines durchschnittlichen Piloten, saisonal angepasst"
- **Schwaeche** (aus Sicht Gleitcast-User): Auch Burnair vermischt Safety + Quality in einem Tier, sagt aber explizit "fuer durchschnittlichen Piloten" – keine Pilot-Profil-Adaption
- Kein expliziter Sicherheit-vs-Erlebnis-Split sichtbar

Quelle: [burnair.ch/meteoservice](https://www.burnair.ch/meteoservice/), [burnair Help Center – Farben in der Wolkenprognose](https://help.burnair.cloud/hc/de/articles/360018676938-Was-bedeuten-die-Farben-in-der-Wolkenprognose)

### 1.2 Paraglidable

- **Zwei explizite Achsen**: `Flyability` (kann man fliegen?) und `Crossability` (XC-Tag?)
- Neuronales Netz, ~200 Wetterparameter, trainiert auf 2 Mio Fluegen aus 10 Jahren XContest-Datenbank
- Macht Risiko-vs-Erlebnis nicht explizit, aber **trennt** "kann ich fliegen" (= eher Safety/Conditions) von "lohnt es sich" (= XC-Potential)
- Schwaeche: ML-Black-Box, schwer erklaerbar warum ein Tag schlecht ist – Gleitcast hat hier mit Decision-Engine-Tags (`_decisions_applied`) einen klaren Vorteil

Quelle: [paraglidable.com](https://paraglidable.com/), [GitHub AntoineMeler/Paraglidable](https://github.com/AntoineMeler/Paraglidable)

### 1.3 White Risk / SLF (Lawinen)

- **Gefahrenstufe 1–5** (Risiko) ist **getrennt** von der **Schneequalitaet** (Erlebnis)
- Subdivision der Gefahrenstufen mit `+` `=` `-` ab Stufe 2 – feinere Aufloesung wo es zaehlt
- **Wichtige Erkenntnis fuer Gleitcast**: SLF subdividiert NICHT bei Nassschnee – wenn die Aussage unzuverlaessig ist, lassen sie die Praezision weg, statt Schein-Genauigkeit zu liefern. Lehre: Bei Foehn-Tagen (sehr unsichere Modelle) sollten wir auch eher zu konservativen Bands greifen.
- White Risk app + Schneeprofil getrennt – aehnlich der Trennung die wir wollen

Quelle: [SLF Danger Levels](https://www.slf.ch/en/avalanche-bulletin-and-snow-situation/about-the-avalanche-bulletin/danger-levels/), [SLF Subdivision of Danger Levels](https://www.slf.ch/en/news/subdivision-of-danger-levels-in-the-avalanche-bulletin/)

### 1.4 Skitourenguru

- Berechnet **pro Streckenabschnitt** Risiko – nicht ein Wert pro Tour
- **Gibt Bergfuehrer-Niveau-Beratung** statt one-size-fits-all – schliesst weniger Routen pauschal aus, weist auf kritische Stellen hin
- Lehre fuer Gleitcast: Pro-User wollen die kritischen Stellen sehen, nicht ein Gesamt-NoGo. Im Gleitcast-Aequivalent waere das pro Stunde / pro Hoehenstufe – haben wir bereits in der Engine, aber im UI nur als Meteogramm.

Quelle: [skitourenguru.ch/rating-view](https://www.skitourenguru.ch/rating-view), [Bluewin – Skitourenguru](https://www.bluewin.ch/en/news/skitourenguru-tool-helps-to-choose-safe-ski-touring-routes-3069477.html)

### 1.5 Magicseaweed (Surf)

- **Doppel-Encoding mit Sternen**: Gefuellte Sterne = Swell-Power, ausgegraute Sterne = Wind-Penalty
- Beispiel: 2 gefuellte + 2 ausgegraute = "guter Swell aber Onshore-Wind" – Pilot sieht beides auf einen Blick
- Black star fuer Big-Wave-Spots = anderer Massstab
- **Stark fuer Gleitcast**: Visualisiert Wind als Modifier auf Erlebnis, ohne ein einzelnes Gesamt-Tier zu erzwingen. Genau das, was wir wollen – Erlebnis-Sterne + Sicherheits-Modifier separat sichtbar.

Quelle: [Magicseaweed Star Rating](https://magicseaweed.com/docs/forecasting/66/star-rating/10134/)

### 1.6 Surfline

- 7 Stufen "Very Poor" bis "Epic" – einfacher als Magicseaweed, aber wieder ein Gesamt-Score
- Manuell von Forecasters korrigiert wenn Modell daneben liegt
- Schwaeche: kein Risiko-Split

Quelle: [Surfline Ratings & Colors](https://support.surfline.com/hc/en-us/articles/36277684017819-Surf-Ratings-Colors)

### 1.7 British Climbing E-Grades

- **Adjectival Grade (E1–E11)**: Risiko/Absicherung/Konsequenz eines Sturzes
- **Technical Grade (4c–7b)**: Schwierigkeit der Bewegung
- **Beide werden zusammen genannt** und die Kombination tells the story:
  - `E1 6a` = normales Risiko fuer 6a (gut absicherbar)
  - `E1 4c` = einfache Bewegungen mit miserabler Absicherung (unangenehm)
  - `E5 6a` = gleiche Bewegung wie E1 6a aber Sturz = Tod
- **Goldstandard fuer Risk-vs-Reward-Trennung**, weil beide Achsen unabhaengig sind und Kletterer gelernt haben, beide zu lesen.
- Lehre fuer Gleitcast: Ein Tag wird vollstaendig durch zwei Achsen beschrieben – `safety_band x experience_score`. "Amber 4 Sterne" = unser Aequivalent zu "E5 6a".

Quelle: [Wikipedia Grade (climbing)](https://en.wikipedia.org/wiki/Grade_(climbing)), [BMC UK Trad Grades](https://www.thebmc.co.uk/en/a-brief-explanation-of-uk-traditional-climbing-grades), [UKC Articles – Extending the UK Grading System](https://www.ukclimbing.com/articles/features/extending_the_uk_grading_system-3068)

### 1.8 FATMAP / Gaia GPS

- Reine **Rohdaten-Visualisierung**: Slope-Angle 25°–45°+ farbcodiert, Aspect, Elevation – keine Aggregation, keine Empfehlung
- Bewusste Designentscheidung: "Wir geben dir die Daten, die Entscheidung gehoert dir"
- Lehre fuer Gleitcast: Pro-User wollen die Rohdaten sehen koennen (haben wir im Meteogramm, gut). Aggregation darf nicht der einzige Pfad sein.

Quelle: [FATMAP Avalanche Tool](https://fatmap.zendesk.com/hc/en-us/articles/115001419425-Avalanche-Tool-Terrain-Layer-)

### 1.9 Synthese – Was funktioniert, was nicht

| Pattern | Vorteil | Nachteil | Fuer Gleitcast geeignet? |
|---------|---------|----------|--------------------------|
| Single Score (Burnair Tier) | Schneller Scan | Paternalistisch, vermischt Achsen | Nur als Default fuer Beginner |
| Zwei Sterne-Sets (Magicseaweed) | Beides sichtbar | Begrenzte Aufloesung (5 Steps) | Sehr gut – als Karten-Visualisierung |
| Zwei-Buchstaben-Grade (Climbing E) | Maximal informativ | Erfordert Lernen | Gut – als Spot-Panel-Detail |
| Gefahrenstufe + getrennte Qualitaet (SLF) | Kompetenz-orientiert | Erfordert Bildung | Gut – Pflicht-Disclaimer |
| Pure Rohdaten (FATMAP) | Maximale User-Souveraenitaet | Ueberfordert Anfaenger | Als Pro-Modus / Detail-Tab |
| ML Black-Box (Paraglidable) | Lernt aus echten Fluegen | Nicht erklaerbar | Nicht – wir haben Decision-Engine, das ist unser USP |
| Pilot-Profil-Filter | Adaptiv pro User | Kann Risiko-Sortierung verzerren | Sehr gut – als Schwellenwert-Adjuster |

---

## 2. Empfehlung – Konkrete Loesung

### 2.1 Stellungnahme zu Geminis Vorschlaegen

| Gemini-Vorschlag | Bewertung | Begruendung |
|------------------|-----------|-------------|
| **Sterne (Potential) + Farbe (Risiko) parallel** | **Stark uebernehmen** | Magicseaweed-Pattern, klettererprobt, Doppel-Encoding ohne Aufdraengen |
| **Lawinen-Modell: Gefahrenstufe + Schneequalitaet getrennt** | **Stark uebernehmen** | SLF macht das aus gutem Grund – Risiko ist nicht Erlebnis |
| **Climbing E-Grade: Adjectival + Technical** | **Konzeptionell uebernehmen, nicht woertlich** | E-Grades sind zu fachsprachlich; Sterne+Farbe sind die intuitive Entsprechung |
| **2D-Scatter: X=Anspruch Y=Genuss** | **Ablehnen als Primaer-UI** | Scatter erfordert kognitive Last, schlecht auf Karte. **Akzeptieren** als Pro-Detail-Ansicht (Wochenuebersicht im Region-Panel) |
| **Pilot-Skill-Filter (Beginner/Advanced/Pro)** | **Uebernehmen** | Bewaehrt aus Lawinen-/Climbing-Apps – einfach umzusetzen, hoher Wert |
| **Rohdaten-Kategorien (XC/Comfort/Technical)** | **Mittel uebernehmen** | Drei Achsen sind zu viel fuer Karten-View. Aber als **Spot-Panel-Detail-Tabs** wertvoll. |
| **Drei-Achsen-Modell** | **Eher ablehnen als Default** | Komplexitaet > Nutzen fuer 80% der Sessions. Drei Werte schauen, vergleichen, gewichten = Cognitive Load. **Aber**: dritter Wert (Comfort) als Detail im Spot-Panel anzeigen, nicht auf Karte. |

### 2.2 Empfohlene Loesung: 2-Achsen + Pilot-Profil + Comfort-Texture

Genauer Aufbau:

**Achse 1: `safety_band`** (kategorial, 3 Stufen)
- `green` – fliegbar fuer alle Pilotenprofile
- `amber` – fliegbar fuer Advanced/Pro, Caution-Notes vorhanden
- `red` – nicht fliegbar oder nur fuer Pro mit klarem Wissen warum

**Achse 2: `experience_score`** (0–100, dargestellt als 0–5 Sterne)
- 0–20 = 0 Sterne (kein Flug/Abgleiter)
- 21–40 = 1 Stern (kurzer Flug moeglich)
- 41–60 = 2 Sterne (lokaler Flug, Bart hier-da)
- 61–75 = 3 Sterne (solide Thermik, lokal-XC)
- 76–89 = 4 Sterne (XC moeglich, gute Bedingungen)
- 90–100 = 5 Sterne (Top-Tag, fettes XC-Potential)

**Achse 3 (Texture, nicht primaer): `comfort_index`** (0–100)
- Wird nur im Spot-Panel als Begleitwert gezeigt: "4 Sterne / amber / Comfort 35"
- Niedrig = mechanisch ruppig (rough_pct hoch, Scherung)
- Wirkt sich NICHT auf experience_score aus (sonst Doppelzaehlung)

**~~Pilot-Profil-Filter~~** (DEFERRED v1.3 — siehe §10 Backlog)

> **DEFERRED**: Pilotenprofil-Filter (Beginner/Intermediate/Advanced/Pro) wurde nach Preview-Review zurueckgestellt.
> - **Grund**: vereinfacht v1.0-Launch, vermeidet Profil-Disclaimer-Pflicht (Anwaltsgespraech), reduziert Code-Pfade.
> - **Wo es zurueckkommen kann**: §10 Backlog. Architektur ist so gebaut, dass Profil-Filter spaeter rein CSS-/Sortier-Layer wird (keine Backend-Aenderungen).
> - **Konsequenz fuer v1.0**: Karte zeigt alle Marker in voller Saturierung, keine Beginner-Daempfung. User entscheidet selbst.

Profil aenderte NUR Visualisierung und Sortierung. Backend-Werte sind fuer alle Profile identisch.

### 2.3 Begruendung – Trade-offs

**Warum nicht 3 Achsen als Default?** Drei Werte vergleichen heisst drei Werte gewichten. Aus der UX-Forschung zu Multi-Score-Systemen (z.B. NASA-TLX) weiss man, dass 3+ Dimensionen schnelle Scans verhindern. Magicseaweed reduziert deshalb auf 2 Sterne-Sets, nicht 3. Wir haben Comfort als dritte Information – aber nicht als dritte Hauptachse.

**Warum nicht ML-Black-Box wie Paraglidable?** Unsere Decision-Engine ist deterministisch und erklaerbar. `_decisions_applied` listet exakt warum ein Tag amber ist. Diese Erklaerbarkeit ist USP – Aufgeben fuer ML-Score waere strategischer Rueckschritt. Ausserdem kein Trainings-Datensatz vorhanden (zu wenige Fluege pro CH-Spot).

**Warum behalten wir `flyability_tier` im Cache?** Backwards-compat fuer Chat-Engine, Email-Subscribers, externe Integrationen. Aber UI-Primaer wird `safety_band` + `experience_score`.

**Risiko der Empfehlung**: Pro-Pilot fliegt amber-Tag, hat Vorfall, klagt App. Mitigation = Disclaimer + explizites Pilot-Profil-Setting (User wird Bestaetigen "ich bin Advanced" gefragt + AGB) + Detail-Caution-Notes weiterhin sichtbar. Schweiz hat hohe Eigenverantwortungs-Tradition (vgl. SLF-Bulletin), das traegt.

---

## 3. Mapping bestehender Felder -> neues Konzept

### 3.1 `safety_band` Berechnung (v1.3 — Hybrid: Sub-Ratings + Hard-Override)

> **CHANGED v1.3**: Hybrid-Ansatz statt rein kategorial. Die `safety_band`-Ableitung folgt jetzt demselben Sub-Rating-Pattern wie `experience_score` (§3.2), behaelt aber die deterministischen Hard-Overrides der Decision-Engine.

**Zweistufige Berechnung:**

**Stufe 1 — Numerischer `safety_score` (0–100) aus 4 LLM-Sub-Ratings** (siehe §3.5 fuer Definition):
```python
def compute_safety_score(spot_day):
    safety_rating_0_10 = spot_day.get("safety_rating", 0)  # aus _compute_safety_rating
    return round(safety_rating_0_10 * 10)
```

**Stufe 2 — `safety_band` aus Score + Hard-Overrides** (deterministisch, Decision-Engine):
```python
def compute_safety_band(spot_day):
    score = spot_day.get("safety_score", 0) or 0
    decisions = spot_day.get("_decisions_applied", [])

    # Hard red — Decision-Engine ueberschreibt Score
    if spot_day.get("safety_status") == "not_safe":
        return "red"
    if "FoehnDanger" in str(decisions):
        return "red"
    if any(d.startswith("AloftNotSafe") for d in decisions):
        return "red"

    # Hard amber — Decision-Engine
    if spot_day.get("safety_status") == "conditional":
        return "amber"
    if "FoehnCaution" in str(decisions) or spot_day.get("foehn_risk", 0) >= 4.0:
        return "amber"
    if any(d.startswith(("GustFloor", "AloftConditional", "WindStrongMajority")) for d in decisions):
        return "amber"

    # Score-basiert (kein Decision-Override aktiv)
    if score < 40:
        return "amber"  # LLM-Sub-Ratings selbst sehen Probleme
    return "green"
```

**Logik-Begruendung:**
- **Decision-Engine (Hard-Overrides) hat Vorrang** — strukturelle Sicherheits-Regeln (Foehn, Aloft) sind unabhaengig vom LLM-Urteil. Wenn ein Foehndurchbruch erkannt wird, ist der Spot rot, egal was das LLM zu Wind/Boeen sagt.
- **Score wirkt nur, wenn keine Hard-Override greift** — ist die letzte Stufe, die das LLM in die Endbewertung einbringt.
- **Symmetrie zu Experience**: gleiche Architektur, gleiches Pattern — leichter zu erklaeren, leichter zu warten.

**Note**: `OverclaimRelax` wirkt bereits auf `safety_status`, deshalb keine zusaetzliche Logik noetig. `WindOk0` ist ebenfalls bereits verarbeitet.

### 3.2 `experience_score` Berechnung (v1.3 — bestehendes Sub-Rating-Pattern)

> **CHANGED v1.3**: Die urspruengliche Formel (climb_pts + prod_pts + xc_bonus - quality_penalty) wird **superseded**. Stattdessen wird das bereits bewaehrte 4-Sub-Rating-Pattern aus `engine/_common.py:421` wiederverwendet. Begruendung: §9.4 Vorab-Fix 3 — "Restrukturieren statt neu bauen", LLM-G-Eval-Prinzip ist im Code etabliert.

**Quelle**: Bestehendes `rating`-Feld (`engine/_common.py:421`, `_compute_rating_from_subratings`)

**Wie es heute funktioniert (unveraendert):**
Das LLM vergibt 4 Einzel-Ratings, jedes auf Skala 1–10:

| Sub-Rating | Was es bewertet |
|------------|-----------------|
| `thermal_rating` | Qualitaet der Thermik (Steigwerte, Kontinuitaet) |
| `window_rating` | Groesse des fliegbaren Zeitfensters |
| `wind_rating` | Wind-Qualitaet (Anstroemung, Konsistenz, nicht zu schwach/stark fuer Genuss) |
| `xc_rating` | XC-Streckenflug-Potential |

**Aggregation** (deterministisch im Server, kein LLM):
```
rating_0_10 = 0.35 × thermal + 0.25 × window + 0.25 × wind + 0.15 × xc
```
Anschliessend Clamping auf Tier-Korridor (gray=0–4, green=4–7.5, violet=7.5–10).

**Neu in v1.3 — Skalierung auf experience_score (0–100):**
```python
def compute_experience_score(spot_day):
    # Bestehendes 0-10 rating wiederverwenden
    rating_0_10 = spot_day.get("rating", 0) or 0
    return round(rating_0_10 * 10)  # 0–10 → 0–100
```

**Mapping auf Sterne** (Schwellen aus §8.3, koennen spaeter mit Cache-Daten kalibriert werden):
- 0–20 = 0 Sterne
- 21–40 = 1 Stern
- 41–60 = 2 Sterne
- 61–75 = 3 Sterne
- 76–89 = 4 Sterne
- 90–100 = 5 Sterne

**Vorteile dieser Wahl:**
- Keine neue LLM-Prompt-Aenderung noetig — Sub-Ratings existieren bereits
- Bewaehrte Aggregations-Gewichte (35/25/25/15) bleiben
- Chat-Engine + Mail-Templates lesen weiterhin denselben `rating`-Wert
- `experience_score` ist nur eine kosmetische Skalierung × 10

**Was NICHT mehr in `experience_score` einfliesst (zur Klarstellung):**
- `rough_pct` — gehoert zu `comfort_index` (siehe §3.3) bzw. `safety_band` wenn ROUGH-UNUSABLE
- Direkte `peak_climb_rate` / `productive_thermal_h` — diese sind im `thermal_rating` und `window_rating` des LLM bereits implizit beruecksichtigt

**Backwards-Compat**: Das bestehende `rating`-Feld bleibt erhalten. `experience_score` ist ein **zusaetzliches Feld** (`= rating × 10`), keine Ersetzung.

### 3.3 `comfort_index` Berechnung

**Input-Felder:**
- `rough_pct` (0–100)
- Turbulenz-Profil T(z) Maxima auf typischen Fluhoehen
- Boenfaktor (Gust-Factor)

**Formel-Skizze:**
```python
def compute_comfort_index(spot_day):
    rough = spot_day.get("rough_pct", 0) or 0
    gust_factor = spot_day.get("avg_gust_factor", 1.0) or 1.0

    # Base from rough percentage (inverted)
    base = 100 - rough  # 0% rough = 100 comfort, 50% rough = 50 comfort

    # Penalty for high gust factor
    if gust_factor > 1.7:
        base -= 20
    elif gust_factor > 1.4:
        base -= 10

    return max(0, min(100, base))
```

### 3.4 Mapping-Tabelle (Uebersicht — v1.3)

| Neues Feld | Quelle | Berechnungsort |
|------------|--------|----------------|
| `safety_score` (0–100) | 4 Safety-Sub-Ratings (§3.5) ueber `_compute_safety_rating` × 10 | `engine/_common.py` (neu: `_compute_safety_rating`) + skaliert in `decision_engine.py` |
| `safety_band` (green/amber/red) | `safety_score` + Decision-Engine Hard-Overrides | `engine/decision_engine.py` (neu: `compute_safety_band`) |
| `experience_score` (0–100) | Bestehendes `rating`-Feld × 10 (§3.2) | `engine/decision_engine.py` (neu: `compute_experience_score`) |
| `experience_stars` (0–5) | `experience_score` mit §8.3-Schwellen | UI (Frontend Mapping) |
| `comfort_index` (0–100) | `rough_pct`, Turbulenz-Profil, Gust-Factor (§3.3) | `engine/decision_engine.py` (neu: `compute_comfort_index`) |

Alle Werte werden in den bestehenden Cache-Output (`spot_analyses.json`, `region_analyses.json`) als zusaetzliche Felder geschrieben. Existierende Felder bleiben unveraendert (`rating`, `safety_status`, `flyability_tier` bleiben fuer Backwards-Compat).

### 3.5 Sub-Rating-Symmetrie — Safety-Sub-Ratings (NEU v1.3, finalisiert)

**Hintergrund**: Im bestehenden Code (`engine/_common.py:421`) gibt es bereits 4 LLM-Sub-Ratings fuer **Fliegbarkeit/Erlebnis** (thermal/window/wind/xc) mit deterministischer Aggregation. Dieses Pattern hat sich bewaehrt: das LLM ist gut im Einzelbeurteilen, schlecht im Gewichten/Aggregieren.

**Erkenntnis aus Preview-Iteration v1.3**: Das gleiche Pattern fehlt fuer **Safety**. Heute liefert das LLM nur eine kategoriale `safety_status` (safe/conditional/not_safe) — keine numerische Granularitaet, keine Aspekt-Trennung. Wenn das LLM zwischen "leicht vorsichtig" und "stark vorsichtig" unterscheiden will, muss es das in `caution_notes` als Freitext rein. Nicht aggregierbar, nicht ranking-faehig.

**Finalisierung v1.3** (nach Implementation-Iteration mit User-Feedback): **Fuenf** Safety-Sub-Ratings, aggregiert per **Weakest-Link-Prinzip (MIN)**:

| Sub-Rating | Was es bewertet | Skala |
|------------|-----------------|-------|
| `wind_safety_rating` | Bodenwind/Mittelwind am Startplatz: Spot-Bemerkung beachten, Default-Idealbereich `WIND_IDEAL_MIN_KMH`–`WIND_IDEAL_MAX_KMH` | 1–10 |
| `gust_safety_rating` | Boenfaktor und Boen-Spitzen, Schwellen aus `GUST_WARN_KMH` / `GUST_DANGER_KMH` | 1–10 |
| `aloft_safety_rating` | Hoehenwind FL050–100 (kann Foehn-Anriss anzeigen, auch wenn boden ruhig) | 1–10 |
| `foehn_safety_rating` | Foehn-Risiko (synoptisch: Druckgefaelle, Anstroemung, Trigger) | 1–10 |
| `weather_safety_rating` (NEU) | Niederschlag, Gewitter, CAPE/Ueberentwicklung, Sicht-Beeintraechtigung beim Start/Landen (Wolken-Basis ≤ Startplatzhoehe) | 1–10 |

**Trends** sind in jedem Sub-Rating eingerechnet (forward-looking): das LLM bewertet den schlechtesten plausiblen Zustand der produktiven Stunden, nicht den Snapshot.

**Aggregation: Weakest-Link statt gewichteter Durchschnitt**
```python
def _compute_safety_rating(result: dict) -> float:
    """Weakest-Link-Aggregation. Sicherheit ist asymmetrisch — ein perfekter
    Aspekt darf keinen schlechten kompensieren. Beispiel: Wind 9, Gewitter-CAPE-WARN
    Rating 2 sollte NICHT als 7/10 daherkommen (gewichteter Durchschnitt), sondern
    als 2/10 — das einzelne kritische Element bestimmt den Tag.
    """
    def _clamp(v, lo, hi):
        try: v = float(v)
        except (TypeError, ValueError): v = 5.0
        return max(lo, min(hi, v))
    wind    = _clamp(result.get("wind_safety_rating", 5),    1, 10)
    gust    = _clamp(result.get("gust_safety_rating", 5),    1, 10)
    aloft   = _clamp(result.get("aloft_safety_rating", 5),   1, 10)
    foehn   = _clamp(result.get("foehn_safety_rating", 5),   1, 10)
    weather = _clamp(result.get("weather_safety_rating", 5), 1, 10)
    return round(min(wind, gust, aloft, foehn, weather), 1)
```

**Begruendung MIN statt Gewichten**: Bei Sicherheit gilt das Weakest-Link-Prinzip — wenn ein einzelner Aspekt akut gefaehrlich ist (z.B. CAPE knapp unter DANGER), ist der Tag entsprechend einzustufen, egal wie gut die anderen 4 Aspekte sind. Gewichteter Durchschnitt wuerde solche kritischen Einzelaspekte "wegmitteln".

**Was sich aendert vs. heute:**

| Heute | v1.3 |
|-------|------|
| 1 LLM-Output: `safety_status` (3 Kategorien) | 5 LLM-Outputs: 5 Sub-Ratings (1–10 je) |
| `safety_status` direkt von LLM | `safety_status` weiterhin von LLM **als Plausibilitaets-Check**, plus Decision-Engine ueberschreibt deterministisch |
| Keine Granularitaet zwischen "knapp safe" und "komfortabel safe" | `safety_score` 0–100 zeigt diese Differenz |
| `caution_notes` muss alles tragen | `caution_notes` bleibt fuer Begruendungen, aber Score traegt Quantifizierung |
| Bewertung von Niederschlag/Gewitter/CAPE nur in `safety_status` und `caution_notes` | Plus numerischer Gradient via `weather_safety_rating` (Hard-Override-Faelle wie THUNDERSTORM, RAIN-WARN-DANGER, CAPE-DANGER bleiben binaer) |

**Architektur-Symmetrie nach v1.3:**

```
Experience-Achse:                Safety-Achse:
  4 LLM-Sub-Ratings              5 LLM-Sub-Ratings
  (thermal/window/wind/xc)       (wind/gust/aloft/foehn/weather)
       ↓                              ↓
  Gewichteter Durchschnitt       Weakest-Link (MIN)
  (35/25/25/15)
       ↓                              ↓
  rating (0-10)                  safety_rating (0-10)
       ↓                              ↓
  × 10                           × 10
       ↓                              ↓
  experience_score (0-100)       safety_score (0-100)
       ↓                              ↓
  experience_stars (0-5)         safety_band (green/amber/red)
                                       ↑
                                 Decision-Engine
                                 Hard-Overrides
                                 (FoehnDanger/AloftNotSafe/THUNDERSTORM/
                                  RAIN-WARN/CAPE-DANGER/OVERCAST-DANGER)
```

**Asymmetrie zwischen den Achsen ist beabsichtigt:**
- Experience: gewichteter Durchschnitt — gute Aspekte kompensieren weniger gute (Top-Thermik macht maessigen Wind ertraeglich)
- Safety: MIN — kein Aspekt darf einen anderen kompensieren (ein einzelner kritischer Punkt = der Tag ist eingeschraenkt)

**Wolken-Logik in `weather_safety_rating`** (User-Feedback v1.3): Bewoelkung ist NUR ein Sicherheits-Thema, wenn die Sicht beim Start/Landen blockiert wird — d.h. Wolken-Basis ≤ Startplatzhoehe (Cloud-Entry-Risiko, kein Visual Reference). Hohe oder mittlere Wolken weit ueber dem Spot sind irrelevant und gehoeren zu `thermal_rating` (Fliegbarkeit), nicht zu Safety.

**Spot-Bemerkung-Logik in `wind_safety_rating`** (User-Feedback v1.3): Default-Idealbereich `WIND_IDEAL_MIN_KMH`–`WIND_IDEAL_MAX_KMH` (typisch 5–20 km/h fuer Thermik-Spots). Soaring-Spots wie Balderen brauchen einen MINDESTWIND aus der Spot-Bemerkung — die Bewertung muss diesen Spot-spezifischen Anforderung folgen, nicht dem Default.

**Implementations-Status** (siehe §9.4 Vorab-Fix #4):
1. ✅ Prompt erweitert: LLM gibt 5 zusaetzliche Sub-Ratings aus
2. ✅ `_compute_safety_rating()` + `_compute_safety_score()` in `engine/_common.py` (MIN-Aggregation)
3. ✅ `safety_rating` und `safety_score` werden im Cache geschrieben (`engine/analyzers.py` 4 Sites)
4. ✅ `_safety_subratings.md` Skill-File mit Trend-Logik, Spot-Bemerkung, Cloud-Entry-Praezisierung
5. ✅ `WIND_IDEAL_MIN_KMH` / `WIND_IDEAL_MAX_KMH` in `config.py`
6. ✅ Tests in `TestSafetyRating` (13 Cases — MIN-Verhalten, Defaults, Clamping, Score-Skalierung)
7. ⏳ `compute_safety_band()` (mit Hard-Override-Logik aus §3.1) — Phase 1 Frontend-Build

**Backwards-Compat:**
- `safety_status` bleibt unveraendert vom LLM
- `caution_notes` und `no_go_reasons` bleiben unveraendert
- Decision-Engine Hard-Overrides bleiben unveraendert
- Neu hinzu: `safety_rating`, `safety_score`, `wind_safety_rating`, `gust_safety_rating`, `aloft_safety_rating`, `foehn_safety_rating`, `weather_safety_rating` als zusaetzliche Felder im Cache

---

## 4. UI-Konzept

### 4.1 Karte (`map.js`)

> **Hinweis**: Dieser Abschnitt wurde durch Sektion 8 (UI-Optimierung fuer schnellen Scan) ueberarbeitet. Der hier beschriebene Outer-Ring + Inner-Stars-Marker mit Toggle-Reihen ist konzeptionell richtig, aber zu komplex fuer den 1-Sekunden-Scan. Der finale Marker ist in **Sektion 8.2** definiert. Die folgenden Absaetze bleiben als Begruendungs-Historie erhalten.

**Heute**: ein farbiger Spot-Marker pro Spot, Farbe = `flyability_tier` (green/violet/gray)

**Vorschlag (superseded by Sektion 8.2)**: Spot-Marker mit zwei visuellen Layern:
- **Outer Ring** = Sicherheits-Farbe (`safety_band`): green/amber/red
- **Inner Fill / Symbol** = Experience-Sterne (1–5, kompakt als Sternreihe oder als Fuell-Hoehe)

ASCII-Skizze (ein Marker):
```
   _____
  |  4* |       <- Inner: 4 Sterne (experience_score 76-89)
  |_____|
    AMB          <- Outer ring: amber

bzw kompakt als Icon:
  [O]      green outer + 5 stars inner = green/5*
  [O]      amber outer + 4 stars inner = amber/4*
  [O]      red outer + X (x-cross statt Stars) = red/0*
```

**Pilot-Profil-Filter wirkt auf Karte** (superseded by Sektion 8.2 + 8.5):
- Beginner: red-Marker = ausgegraut + nicht klickbar; amber-Marker = ausgegraut + klickbar mit Warnung
- Intermediate (default): red ausgegraut, amber halb-saturiert, green voll
- Advanced/Pro: alle voll saturiert, Sortier-Toggle "Safety zuerst" / "Experience zuerst"

**Toggle oben rechts auf Karte** (superseded by Sektion 8.5 — kein Toggle, Profil sitzt diskret im Header):
- `[Sicherheits-Vorrang]` (Default): Marker-Reihenfolge nach Safety, dann Experience
- `[Erlebnis-Vorrang]` (Pro/Advanced): Marker primaer nach Experience, Safety als Outer-Ring
- `[Pilotenprofil: Intermediate v]` Dropdown

### 4.2 Spot-Panel

> **Hinweis**: Dieser Abschnitt wurde durch **Sektion 8.4** verfeinert (klare 2-Sekunden-Hierarchie). Das hier gezeigte Panel ist im Prinzip richtig, aber die Hierarchie der Information war zu flach (drei gleichgewichtige Bloecke). Sektion 8.4 macht "Sicherheit + Stars" zur Hero-Zeile und schiebt Comfort + Decisions in tiefere Ebenen.

Wenn User einen Spot anklickt, oeffnet sich Side-Panel:

```
+----------------------------------------------------+
| FIESCH-KUEHBODEN                              [x] |
| Donnerstag 1.5.                                    |
+----------------------------------------------------+
| Sicherheit:    AMBER                               |
|   - Foehnrisiko 4.5 (CautionFoehn)                 |
|   - Hoehenwind 850 hPa: 35 km/h                    |
|                                                    |
| Erlebnis:      ****-  (82 / 100)                   |
|   - Peak Steigen 1.9 m/s                           |
|   - Produktive Stunden 5h (10-15 Uhr)              |
|   - XC-Potential: hoch                             |
|                                                    |
| Comfort:       45 / 100  (rough_pct 30%)           |
|   - Klapperrisiko vormittags niedrig               |
|   - Boenfaktor 1.6 (mittel)                        |
+----------------------------------------------------+
| Tabs: [Meteogramm] [Windverlauf] [Decisions]      |
+----------------------------------------------------+
| Empfehlung fuer dein Profil (Advanced):           |
|   "Lohnender Tag fuer dich. Foehnstrip beachten,  |
|    nach 14 Uhr engmaschig monitoren. XC moeglich  |
|    Richtung Goms."                                 |
+----------------------------------------------------+
```

**Tab "Decisions"** (neu): Listet alle gefeuerten Decisions aus `_decisions_applied` mit Klartext-Erklaerung. Diese Transparenz ist USP gegenueber Burnair/Paraglidable.

### 4.3 Regionen-Tab — Leaflet-Karte (v1.3)

> **CHANGED v1.3**: Urspruenglich war hier eine 7-Tage-Tabelle + 2D-Scatter geplant. Nach Preview-Iteration: **Regionen-Tab wird zur primaeren Leaflet-Karte** (analog `static/js/region-map.js`). Der 2D-Scatter wandert in den Briefing-Tab und wird **regionen-aggregiert** (Bubble-Matrix mit ~7-10 Bubbles statt 488 Spot-Punkten — siehe §4.4).

**Konzept**: Regionen-Tab ist eine **interaktive CH-Karte mit allen Region-Polygonen** aus `data/regionen_polygone_mapped.geojson` (29 Regionen). Polygone sind nach `safety_band` der Region (heutiger Tag) eingefaerbt. Klick oeffnet ein Region-Overlay mit Tagesbriefing.

**Layout-Komponenten**:

1. **Karte** (full-width Container, ~640px hoch desktop / ~540px mobile)
   - Leaflet (gleiche Version wie restliche App: 1.9.4)
   - Tile-Layer dezent: CartoDB Positron Light (passt zum Light-Theme)
   - Region-Polygone aus GeoJSON, gefaerbt nach `safety_band`:
     - `green` → fill `#22c55e` 42%, stroke `#15803d`
     - `amber` → fill `#f59e0b` 42%, stroke `#92400e`
     - `red`   → fill `#ef4444` 40%, stroke `#991b1b`, dashed border (klare Sperr-Visualisierung)
     - `gray`/no_data → grau 30%, dashed
   - **Region-Label im Polygon-Centroid**: Region-Name + Sterne in Safety-Farbe
   - Hover: erhoehe `fillOpacity` auf 0.65, Tooltip mit Region · Verdict · Stars · Score

2. **Tag-Pill oben links** (glass effect): zeigt aktuell betrachteten Tag (Default = heute)

3. **Karten-Legende unten links** (glass): 4 Swatches (green/amber/red/gray) + Beschriftung

4. **Region-Overlay** (slide-in von rechts, 380px desktop; full-screen Bottom-Sheet mobile):
   - Header: Region-Name + Subline (Hauptort + Hoehe + Tagesthema)
   - Summary: Verdict-Pill, Sterne-Symbole, Score
   - 7-Tage-Sparkline (analog zu §4.3 alte Tabelle, aber kompakt — 7 farbige Pills in Row, "Heute" hervorgehoben)
   - **Top Spots heute** in der Region: Liste mit Marker-Glyph + Name + Stars + Score, klickbar (oeffnet Spot-Detail-Tab)
   - CTA "Im Briefing oeffnen →" (springt in Briefing-Tab + scrollt zur Region)
   - Backdrop hinter Overlay auf Mobile, klickbar zum Schliessen

5. **Klick-Verhalten**:
   - Klick auf Polygon → oeffnet Region-Overlay
   - Klick auf "Im Briefing oeffnen" → wechselt zu Briefing-Tab und scrollt zur Region
   - ESC/Backdrop-Klick / X-Button → schliesst Overlay

**Code-Anker**:
- Frontend-Implementierung: neue `static/js/regions-tab.js` (oder Erweiterung von `region-map.js`)
- Reuse: `region-map.js` Style-Funktionen + Tile-Layer-Konfig
- Daten-Endpoint: `region_analyses.json` (existiert)
- GeoJSON: `data/regionen_polygone_mapped.geojson` (existiert, Inline in Preview, in Produktion via Static-Endpoint)

**Mobile-Responsivitaet**:
- Karte nimmt fast Vollbild ein
- Region-Overlay = Bottom-Sheet mit Drag-Handle (oder Vollbild-Modal)
- Tap auf Polygon eindeutig (Polygone sind grossflaechig — keine Tap-Konflikte)

**Was sich vs. bestehender `regionen.html` aendert:**
- Heute: Karte + Chat-Sidebar (50/50 Split)
- v1.3: Karte mit Overlay-bei-Klick (kein Chat-Splitscreen) — Chat bleibt in `regionen.html` als separate Page erhalten, der Regionen-Tab in der neuen UI ist eine **Map-only-Variante** fuer den Tagesbriefing-Use-Case.

### 4.4 Risk-Reward-Bubble-Matrix (im Briefing-Tab)

> **NEU v1.3**: Die urspruenglich in §4.3 platzierte 2D-Scatter wandert in den Briefing-Tab. Bei 488 Spots ist Spot-Granularitaet visuell unbrauchbar — daher **Region-Aggregation**.

**Konzept**: Bubble-Chart mit den 29 Regionen statt der 488 Spots.

**Achsen**:
- X-Achse: Mittlerer `experience_score` der Region heute (0–100)
- Y-Achse: 3 Sicherheits-Baender (gruen oben, amber mitte, rot unten) — kategorial, mit Hintergrund-Banding

**Bubble**:
- Position: (Ø-Score, Band)
- Groesse: proportional zur Spot-Anzahl in der Region (28–48px Durchmesser)
- Farbe: Safety-Band der Region
- Beschriftung: Region-Kurzname unter Bubble + Spot-Anzahl als Zahl in Bubble
- Klick → springt zur Region im Region-Tab oder Region-Block im Briefing

**Nutzen fuer Pro-User**:
"Welche Region heute hat das beste Verhaeltnis Risiko-zu-Erlebnis?" → die Bubble oben rechts (gruen + Score 80+) ist die Antwort. Klassische Risk-Reward-Matrix, nur regionen-aggregiert.

### 4.4 Drei Pilot-Beispiele durchgespielt

Annahme Donnerstag 1.5., drei Spots: Fiesch-Kuehboden, Uetliberg, Atzmaennig.

| Spot | safety_band | experience_score | stars | comfort_index | _decisions_applied |
|------|-------------|------------------|-------|---------------|---------------------|
| Fiesch | amber | 82 | 4 | 45 | `[FoehnCaution(4.5), GustFloor]` |
| Uetliberg | green | 35 | 1 | 70 | `[]` |
| Atzmaennig | green | 65 | 3 | 85 | `[]` |

**Beginner-Pilot** sieht auf Karte:
- Fiesch: ausgegraut (amber, gesperrt), klickbar mit roter Warnung "Nicht fuer Beginner-Profil"
- Uetliberg: green/1*, voll sichtbar – wird als Top-Empfehlung angezeigt
- Atzmaennig: green/3*, voll sichtbar – Top-Empfehlung

Beginner faehrt nach Atzmaennig. Korrekt.

**Advanced-Pilot** sieht:
- Fiesch: amber/4*, voll saturiert mit Foehn-Hinweis
- Uetliberg: green/1*, sichtbar aber visuell klein (nur 1 Stern)
- Atzmaennig: green/3*

Advanced-Pilot vergleicht: Fiesch ist amber, aber 4 Sterne. Atzmaennig ist green, 3 Sterne. Klickt Fiesch, liest Decisions: "Foehnrisiko 4.5, Hoehenwind 35 km/h auf 850 hPa". Entscheidet bewusst. **Das ist der entscheidende Use-Case, der heute nicht funktioniert.**

**Pro-Pilot mit "Erlebnis-Vorrang"** sieht:
- Fiesch ganz oben (4 Sterne, dominant), amber-Ring als Erinnerung
- Atzmaennig zweite Position (3 Sterne)
- Uetliberg unten (1 Stern)
- Selbst red-Tag wuerde sichtbar sein, aber mit klarem rotem Ring + Klick erforderlich

---

## 5. Migration Path

### 5.1 Was bleibt

- `safety_status`, `flyability_tier`, alle bestehenden Strukturfelder **bleiben** im Cache
- Decision-Engine (`engine/decision_engine.py`) bleibt vollstaendig wie heute
- Cache-Format (`spot_analyses.json`, `region_analyses.json`) wird **erweitert**, nicht ersetzt
- Chat-Engine kann weiter `flyability_tier` lesen (kein Breaking Change)

### 5.2 Was kommt neu

**Server-Seite (`engine/decision_engine.py`)**:
- Drei neue Funktionen: `compute_safety_band`, `compute_experience_score`, `compute_comfort_index`
- Aufruf in `_post_process_spot` und `_post_process_region` _nach_ allen bestehenden Decisions (wegen `OverclaimRelax`-Reihenfolge)
- Neue Cache-Felder: `safety_band`, `experience_score`, `comfort_index`
- Tests in `tests/test_decision_engine.py` (mind. 6 neue Tests pro Funktion: jede safety_band-Stufe, Experience-Schwellen, Comfort-Edge-Cases)
- Tabellenzeile in `docs/DECISIONS.md` ergaenzen (RatingBand, ExperienceScore, ComfortIndex)

**Frontend (`static/js/map.js`, neue `static/js/spot-panel.js`)**:
- Marker-Renderer: Zwei-Layer-Encoding (Outer Ring + Inner Stars/Symbol)
- Pilot-Profil-Toggle in Settings (localStorage)
- Filter-Logik in `map.js` basierend auf `safety_band` und Profil
- Spot-Panel-Refactor: drei-Spalten-Layout (Sicherheit / Erlebnis / Comfort)

**Skill-Sync (Pflicht aus MEMORY.md)**:
- `skills/chat_capabilities_guide.md` aktualisieren: neue Felder dokumentieren, damit LLM-Berater sie nutzt
- Chat-System-Prompt anpassen: bei Empfehlungen "Sicherheit" und "Erlebnis" als getrennte Konzepte ansprechen, nicht "Tier"

### 5.3 Was wird entfernt / deprecated

- **Nichts hart entfernt** in Phase 1. `flyability_tier` bleibt im Cache.
- **Phase 2 (3–6 Monate spaeter)**: Wenn Akzeptanz validiert, `flyability_tier` aus UI-Primaer-Sicht entfernen. Bleibt im Cache fuer Chat-Engine + Subscriber-Mails.
- **Email-Subscriber-Mails**: muessen separat geupdated werden (eigener Migration-Step), da heute auf `flyability_tier` basieren.

### 5.4 Ist Server-Refactor noetig?

**Ja, aber minimal.** Drei neue Funktionen, aufgerufen am Ende der bestehenden post-processing-Pipeline. Keine Aenderung an Decisions, keine Aenderung an LLM-Aufrufen, kein neuer API-Endpoint noetig (Felder einfach in bestehender `/api/analyses`-Response).

**Geschaetzter Aufwand**:
- Server (decision_engine + Tests): 2–3 Tage
- Frontend (Map-Marker + Panel-Refactor): 4–5 Tage
- Pilot-Profil-Setting + Filter-Logik: 2 Tage
- Skill-Sync + Doku: 1 Tag
- **Total: 2 Wochen Solo-Entwickler-Aufwand**

---

## 6. Risiken & Offene Fragen

### 6.1 Haftung Schweizer Kontext

**Risiko**: Pro-Pilot fliegt amber-Tag, Vorfall, klagt Gleitcast wegen "Empfehlung".

**Mitigation**:
- AGB / Disclaimer beim ersten Pilot-Profil-Setup ("Ich bestaetige, dass ich Pilot mit Brevet/Schein bin und Eigenverantwortung trage")
- Burnair-Sprachlinie kopieren: "Vorhersagen erfolgen nach bestem Wissen, ohne Gewaehr, keine Haftung"
- SLF-Pattern: Wenn Modelle unsicher (z.B. Foehn), explizit "Modellunsicherheit hoch" anzeigen statt Schein-Praezision
- amber-Spots zeigen IMMER `_decisions_applied` Klartext – User sieht selbst warum

**Offene Frage**: Brauchen wir Versicherungs-Abklaerung mit Anwalt? Aktuell defacto aehnlich Burnair, aber pro-Profil-Bewerbung "amber 4 Sterne" ist aktivere Empfehlung als heute. **Empfehlung**: Vor Launch 1h Anwaltsgespraech zu Disclaimers.

### 6.2 UI-Komplexitaet fuer Hobby-Piloten

**Risiko**: Beginner sieht amber/4* Marker und denkt "den nehme ich".

**Mitigation**:
- Pilot-Profil = **erste Pflicht-Eingabe** beim ersten App-Besuch (kein Skip)
- Beginner-Profil sperrt amber/red-Spots aktiv (Klick = Modal "Dein Profil ist Beginner. Dieser Tag erfordert Advanced. Profil wechseln?")
- Default-Profil = Intermediate (eher konservativ als zu offensiv)
- Onboarding-Tooltip beim ersten Marker-Klick: "Aussenring = Sicherheit, Sterne = Flugerlebnis"

**Offene Frage**: Wie sollen Subscriber-Mails aussehen? Heute verwenden sie `flyability_tier`. Vorschlag: Mail bekommt User-Profil-aware-Empfehlung ("Fuer dein Intermediate-Profil sind heute folgende Spots optimal: ..."). Aufwand-Punkt.

### 6.3 A/B-Test Moeglichkeit

**Vorschlag**:
- Phase 1 (Woche 1–4): Server liefert neue Felder, UI zeigt sie aber **noch nicht primaer**. Stattdessen ein "Beta"-Toggle in Settings: "Neues Rating-Modell ausprobieren". Logging: welche User toggeln, wie lange bleiben sie an, kommen sie zurueck zum alten Tier.
- Phase 2 (Woche 5–8): Wenn Beta-Akzeptanz > 70% bei Power-Usern, default umstellen. Alte Tier-Ansicht als Legacy-Toggle.
- Phase 3 (Monat 3+): Tier-Toggle nur noch fuer Admin/Debug.

**Erfolgs-Metriken**:
- Pro-Profil-User klicken oefter auf amber-Marker (heute kaum sichtbar gemacht)
- Beginner-Profil-User loesen weniger amber-Marker-Klicks aus (= keine Verleitung)
- Spot-Panel-Verweildauer steigt (= mehr Information genutzt)
- Chat-Engine-Anfragen "lohnt sich der Tag?" sinken (= die Frage beantwortet die UI selbst)

### 6.4 Konflikte / Widersprueche aus der Recherche

**Konflikt 1**: Magicseaweed nutzt _kombinierte_ Sterne (Wind reduziert Sterne), waehrend wir _trennen_ wollen. Stellungnahme: Magicseaweed-Pattern war richtig fuer Surf, weil Onshore-Wind Wellenqualitaet _direkt_ ruiniert. Beim Fliegen ist amber-Wind nicht "schlechtere Thermik", sondern "gleiche Thermik aber gefaehrlicher". Daher Trennung berechtigt.

**Konflikt 2**: Burnair macht One-Tier-System gut, hat zufriedene Nutzerbasis. Stellungnahme: Burnair-User sind durchschnittlich erfahrener (Brevetierte) und akzeptieren paternalistische Defaults. Gleitcast positioniert sich als _adaptiver_ – User-Profil ist USP. Wenn Gleitcast nur "Burnair done better" werden will, ist das Konzept kein Gewinn. Aber wenn "Burnair fuer Pros + Beginner gleichzeitig", dann schon.

**Konflikt 3**: Paraglidable hat 2 Achsen (Flyability + Crossability). Crossability ueberschneidet sich konzeptionell mit unserem `experience_score`. Stellungnahme: Crossability ist _XC-spezifisch_ (Distanz). Wir wollen `experience_score` breiter (Genuss + XC). Bewusst breiter, weil 80% der CH-Piloten kein XC fliegen, aber lange thermische Stunden trotzdem geniessen.

### 6.5 Offene Fragen fuer User-Validierung (Pflicht vor Implementation)

- [ ] Mind. 5 User-Interviews: 3 Beginner/Intermediate + 2 Pro – Mock-Up vorzeigen (Figma oder Skizze), Reaktion einfangen
- [ ] Wuerden Pros das Pilot-Profil ehrlich setzen oder immer "Pro" waehlen um alles zu sehen? (Risiko: Profil-Filter wertlos)
- [ ] Sind 5 Sterne genug Aufloesung oder zu grob? Magicseaweed nutzt 5, klettert zu E11 – 0–100-Anzeige (wie SLF +/-) als Detail moeglich
- [ ] Mail-Subscriber: Wollen sie pro-Profil-personalisierte Mails oder One-Mail-fits-all?

---

## 7. Empfohlene naechste Schritte

1. **User-Interviews** (1 Woche): 5 Piloten aus eigenem Umfeld + Schweizer FB-Gruppen, Mock-Up zeigen, Akzeptanz testen
2. **Decision-Engine-Erweiterung** (3 Tage): Drei neue Funktionen + Tests + Cache-Felder
3. **Frontend-Prototyp Beta-Toggle** (5 Tage): Neue Karten-Marker, Spot-Panel-Refactor, Pilot-Profil-Setting
4. **Skill-Sync + Doku** (1 Tag): `chat_capabilities_guide.md`, `DECISIONS.md`, Help-Center-Eintrag
5. **Beta-Phase** (4 Wochen): Logging an, Akzeptanz messen, iterieren
6. **GA-Rollout** (Woche 9+): Default umstellen, alter Tier als Legacy-Toggle

**Erfolgs-Gate fuer GA**: Pro-Profil-User-Anteil >15%, amber-Marker-Klickrate >Beginner-Klickrate (= Profil-Filter funktioniert), Subscriber-Mail-Open-Rate stabil oder besser.

---

---

## 8. UI-Optimierung fuer schnellen Scan (Iteration v1.1)

**Status**: Refinement nach User-Feedback 2026-04-30
**Trigger**: "Das Ganze muss sich in das bestehende Konzept einbetten, und Flieger muessen schnell und intuitiv sehen koennen, wie gut der Startplatz oder die Region ist."

### 8.0 Zielbild

Pilot oeffnet die App, schaut 1 Sekunde auf die Karte mit ~28 Spots, erkennt sofort: **wo ist heute fliegbar UND lohnend?**

Heute funktioniert das mit drei Tier-Farben (green/violet/gray). Das geht schnell, ist aber paternalistisch (vgl. TL;DR). Die Iteration v1.0 (Sektion 4.1) hat zwei Achsen visuell getrennt — schnell scannen wurde dadurch langsamer. v1.1 muss beides koennen: **zwei Achsen UND 1-Sekunden-Scan**.

### 8.1 Drei Loesungsoptionen — Bewertung

#### Option A: Single-Glyph-Strategie

Ein zusammengesetzter Marker, der Safety + Experience in einer Glyph kodiert. Beispielsweise:
- **Sterne-Anzahl (0–5)** = Erlebnis
- **Sterne-Farbe** = Safety (green/amber/red)

Pilot liest **eine** Sache (Sterne), kriegt aber **beide** Infos. Wie Magicseaweed, aber mit Safety in der Sterne-Farbe statt in einem zweiten Sterne-Set.

**Pro:** Eine kognitive Operation. Schneller Scan trivial: "Wo sind viele gruene Sterne?". Visuelles Pattern bekannt aus Bewertungs-UIs.
**Contra:** Was bedeutet 0 Sterne? Was bedeutet rote Sterne? Bei red-Tagen: keine Sterne, nur eine Sperr-Glyphe — dann ist es trotzdem implizit zwei-glyphen. Sterne sind im 12px-Format auf einer Leaflet-Karte schwer lesbar.

#### Option B: Adaptive Marker (Profil-driven)

Marker zeigt automatisch das, was fuer den eingestellten Pilot relevant ist:
- Beginner-Profil: nur Safety-Farbe (= heutiges Verhalten, kein Mehraufwand)
- Intermediate: Safety-Farbe primaer, dezent Stern-Hint im Inneren bei 4–5 Sternen
- Advanced/Pro: gleichgewichtig — Outer-Ring Safety, Inner-Fill Experience

**Pro:** Beginner-User sehen identisches UI wie heute (kein Migrations-Schock). Pro-User bekommen volle Information. Komplexitaet skaliert mit User-Bereitschaft.
**Contra:** Setzt voraus, dass der User sein Profil ehrlich setzt (siehe offene Frage 6.5). Drei verschiedene Marker-Renderings im Code = Test- und Wartungsaufwand. Bei A/B-Vergleich auf der gleichen Karte (Beginner zeigt seine Karte einem Pro) entstehen Verwirrungen.

#### Option C: Two-Layer-Toggle

Karte hat einen Toggle "Sicherheit / Erlebnis / Beides". Default = "Beides" mit klarer Hierarchie (eine Achse dominant, andere subtle).

**Pro:** User-Souveraenitaet. Gut fuer Pros, die zwischen Modi wechseln.
**Contra:** Toggle = ein zusaetzlicher Klick und eine kognitive Last fuer 80% der Sessions. User vergisst die Einstellung. Default-Modus muss trotzdem gut sein. **Verschiebt das Problem nur, loest es nicht.**

#### Empfehlung: Option B (Adaptive Marker), aber simpler als oben skizziert

Das obige Adaptive-Schema mit drei verschiedenen Renderings ist zu komplex. Vereinfachte Variante:

> **Final**: Single-Glyph-Strategie (Option A) mit **2 Profil-driven Anpassungen** statt drei verschiedenen Renderings.
>
> - **Eine Glyph fuer alle**: Innerer Kreis = Safety-Farbe, **Stern-Anzahl als Outer-Ring-Segmentierung** (0–5 Striche um den Marker, wie eine Akku-Anzeige).
> - **Profil verschiebt nur Filter/Sortierung**, NICHT den Marker selbst.
> - Beginner-Profil: red und amber-Marker werden auf 35% Opacity gedimmt, klickbar bleiben sie.
> - Pro-Profil: alle Marker voll saturiert.

Begruendung: Eine Glyphe (1-Sekunden-Scan: "Wo gruene Marker mit vollem Outer-Ring?"). Die Stern-Outer-Ring-Idee ist neu — sie nutzt die ohnehin vorhandene Markierung der Windrichtungs-Sektor (siehe `map.js:267`, dort liegt schon ein Sektor um den Marker). Wir ersetzen die "Akku-Anzeige" nicht den Wind-Sektor — beides koexistiert.

**Korrektur nach Re-Read von map.js**: Der Wind-Sektor liegt bereits aussen um den Marker (`sectorOuter = radius + 9`). Wir koennen dort keine Stern-Stricheln drueberlegen, ohne Verwirrung zu stiften. Daher modifizierte finale Loesung in Sektion 8.2.

### 8.2 Finale Karten-Glyphe (definitiv)

**Konzept**: Bestehende Marker-Anatomie minimal erweitern, statt eine zweite Schicht hinzufuegen.

**Heutige Glyphe** (aus `map.js:245-324`):
```
        [Wind-Sektor]
            ___
           /   \
          | RED |     <- Inner Circle: Safety-Farbe
           \___/
```

**Neue Glyphe v1.1** — 1 zusaetzliches visuelles Element:

```
        [Wind-Sektor]                  [Wind-Sektor]
            ___                            ___
           /   \                          /   \
          |GRN 4|     <- Inner Circle    |AMB  |    <- bei red: keine Zahl
           \___/         + Stern-Zahl     \___/
                         als Ziffer
```

Wir ersetzen den heutigen "Glow" + "Warning Triangle" mit einer **Stern-Ziffer** im Inneren des Markers. Die Ziffer 1–5 erscheint als kleine bold weisse Zahl auf dem farbigen Inner Circle (wie ein Cluster-Marker bei Leaflet, vgl. `markercluster`-Plugin).

**Regeln:**
- **Inner Circle Farbe** = `safety_band` (green/amber/red)
- **Inner Ziffer** = `experience_stars` (1–5), nur sichtbar bei `safety_band != red` und `stars >= 1`
- Wenn 0 Sterne (Abgleiter): keine Ziffer, dafuer Punkt-Glyphe (heutiger leere Marker)
- Wenn red: keine Ziffer, stattdessen weisses Kreuz (heutiges Stripe-Pattern weicht — Kreuz ist klarer auf 14px)
- Wind-Sektor: bleibt unveraendert (bewaehrt fuer Wind-Pruefung)

**ASCII-Skizze des fertigen Markers**:
```
   _________________________________________________________
  |                                                         |
  |     ___           ___           ___           ___       |
  |    /   \         /   \         /   \         /   \      |
  |   |GRN 5|       |GRN 3|       |AMB 4|       |RED ✕|     |
  |    \___/         \___/         \___/         \___/      |
  |     Sa            Atz           Fie           So        |
  |                                                         |
  |   GREEN/5*       GREEN/3*       AMBER/4*      RED       |
  |   "Top-Tag"      "lokal ok"     "lohnt fuer  "fliege   |
  |                                  Pros"        nicht"    |
  |_________________________________________________________|
```

**Konkrete CSS / Hex-Werte (wiederverwendet aus `style.css`):**

| Element | Quelle | Hex |
|---------|--------|-----|
| Safety green Fill | `--color-safety-excellent` | `#22c55e` |
| Safety green Stroke | (manuell, dunkler) | `#15803d` |
| Safety amber Fill | `--color-safety-marginal` | `#f59e0b` |
| Safety amber Stroke | (manuell) | `#92400e` |
| Safety red Fill | `--color-safety-critical` | `#ef4444` |
| Safety red Stroke | (manuell) | `#991b1b` |
| Stern-Ziffer Color | (white auf Fuellfarbe) | `#ffffff` |
| Stern-Ziffer Font | (Inter bold, 9px) | — |
| Wind-Sektor | bleibt wie heute (`stroke` mit opacity 0.5) | — |

**Pseudo-CSS** (in `map.js` SVG-Generator):
```javascript
// Bei radius=6 (default), center=22:
// 1. Inner Circle (heute schon)
html += '<circle cx="22" cy="22" r="6" fill="#22c55e" stroke="#15803d" />';

// 2. NEU: Stern-Ziffer (ersetzt Glow + Warning-Triangle)
if (stars > 0 && safetyBand !== 'red') {
    html += '<text x="22" y="25" text-anchor="middle" fill="#ffffff" ' +
            'font-size="9" font-weight="700" font-family="Inter,sans-serif">' +
            stars + '</text>';
}

// 3. NEU: Kreuz bei red (statt Stripes)
if (safetyBand === 'red') {
    html += '<path d="M19 19 L25 25 M25 19 L19 25" stroke="#ffffff" stroke-width="2" />';
}
```

**Markergroesse**: bleibt unveraendert (44×44 SVG, 6–8 Radius). Mobile Tap-Area unveraendert (44×44 transparent hit-area bleibt).

**Hover (Desktop)**: Bestehender Tooltip wird erweitert um eine Zeile:
```
ATZMAENNIG
Toggenburg (Alpen Zentral)
1320m MSL | Wind: NW
● Sicher · 3 Sterne · Comfort 85
```

**Click**: oeffnet Spot-Panel (siehe Sektion 8.4 fuer ueberarbeiteten Inhalt).

### 8.3 Beispiele — 5 reale Schweizer Spots am gleichen Tag

Annahme: Donnerstag 1.5., Foehnsituation in den Alpen, Mittelland im Lee.

| Spot | safety_band | experience_score | Stars | comfort_index | Resultat-Glyphe |
|------|-------------|------------------|-------|---------------|-----------------|
| Fiesch (1071m, Wallis) | amber | 82 | 4 | 45 | `[AMB 4]` — amber Inner, weisse "4" |
| Niesen (2362m, BE) | red | 35 | 1 | 20 | `[RED ✕]` — rot mit weissem Kreuz |
| Pfaender (1064m, A) | green | 88 | 5 | 80 | `[GRN 5]` — grun, weisse "5" |
| Uetliberg (730m, ZH) | green | 38 | 1 | 70 | `[GRN 1]` — gruen, weisse "1" |
| Verbier (2200m, VS) | amber | 70 | 3 | 50 | `[AMB 3]` — amber, weisse "3" |

**Was Pilot in 1 Sekunde sieht (volle Karte, 28 Spots)**:
- Visueller Fokus geht zu **gruene 5er** — sofort. Pfaender springt heraus.
- **Gruene 4er und 3er** sind die naechste Stufe — kommt klar als "lohnt sich".
- **Amber 4er** (Fiesch) ist orange UND hat eine 4 — Pilot weiss "Foehn aber stark"; Pro-User klickt, Beginner erkennt amber als Warnung.
- **Rotes Kreuz** (Niesen) ist sofort als No-Go erkennbar.
- **Gruene 1er und 2er** (Uetliberg, Atzmaennig) sind sicher aber nicht spannend — niedrige Prioritaet visuell.

**Vergleich heute vs. v1.0 vs. v1.1**:

| Dimension | Heute (Tier) | v1.0 (Outer-Ring + Inner-Stars) | v1.1 (Single-Glyph mit Ziffer) |
|-----------|--------------|---------------------------------|-------------------------------|
| Visuelle Dichte | 1 Farbe | 2 Layer (Ring + Inner) | 1 Layer (Inner mit Ziffer) |
| Scan-Zeit fuer "wo lohnt sich's" | < 1s | 2–3s | < 1s |
| Risk-vs-Reward-Trennung | nein | ja, sehr explizit | ja, kompakt |
| Code-Aenderung in `map.js` | — | Refactor des Marker-Generators | +20 Zeilen im bestehenden Generator |
| A11y (Farbblindheit) | OK (Stripe + Triangle) | OK aber komplex | OK (Ziffer ist Text, immer lesbar) |

### 8.4 Karten-Legende (Mikro-Copy)

Heutige Legende (aus `map.js:115-137`) hat 6 Punkte (Sicher/Top/Abgleiter/Vorsicht/Nicht sicher/Keine Daten). Wir reduzieren auf 5 Symbole + Mikro-Copy.

**Neue Legende**:
```
+--------------------------------------+
| Legende                          [×] |
+--------------------------------------+
| ● 5     Top-Tag, lohnt sich         |
| ● 3     Solider Tag                 |
| ● 1     Sicher, kurzer Flug         |
| ● 4     Vorsicht — Pro-Tag          |
| ● ✕     Nicht fliegbar              |
| ●       Keine Daten                 |
+--------------------------------------+
| Profil: [ Intermediate ▾ ]          |
+--------------------------------------+
```

Mikro-Copy-Regeln (max 5 Worte je Symbol):
- **Gruen 5**: "Top-Tag, lohnt sich"
- **Gruen 3**: "Solider Tag"
- **Gruen 1**: "Sicher, kurzer Flug"
- **Amber 4** (Beispiel mit hoher Stern-Zahl): "Vorsicht — Pro-Tag"
- **Rot Kreuz**: "Nicht fliegbar"
- **Grau leer**: "Keine Daten"

**Zusatz im Tooltip** (nicht in Legende, um sie kompakt zu halten): klickbarer Link "Wie funktioniert das?" der ein Modal mit Sektion 1 (Benchmark) und Sektion 2 (Erklaerung) oeffnet — fuer interessierte User.

### 8.5 ~~Pilotenprofil — wo lebt der Schalter?~~ (DEFERRED v1.3)

> **DEFERRED v1.3** — Der gesamte §8.5-Inhalt wird zurueckgestellt. Begruendung siehe §2.2-Banner. Sektion bleibt erhalten als Referenz fuer die Wieder-Einfuehrung in v1.5 (siehe §10 Backlog).

**Beobachtung aus `index.html`**: Es gibt eine Top-Navbar (60px hoch, fixed) und eine Mobile-Bottom-Nav. Der Header hat heute Day-Tabs und einen Title — aber keinen User-Profil-Bereich. Settings koennten dort einziehen.

**Empfehlung**: **Diskreter Schalter im Karten-Footer / in der Karten-Legende**, NICHT im Header.

Begruendung:
- Header ist heute frei von User-Settings — wuerde dort Aufmerksamkeit stehlen.
- Legende sitzt unten links auf der Karte (`map.js:115`, position `bottomleft`). Sie ist ohnehin der Erklaer-Ort — Pilot lernt "ah, dort steht was die Marker bedeuten" und gleich daneben: "und mein Profil bestimmt mit, was ich sehe".
- Mobile: Legende ist defaultmaessig collapsed (`map.js:117`). Profil-Toggle ebenso — er ist da, drueckt sich aber nicht auf.

**Konkret**:
- **In Legende eingebettet** (siehe Mockup oben, `Profil: [Intermediate ▾]`)
- **Persistenz**: localStorage (gleicher Mechanismus wie `STORAGE_KEY` fuer Sidebar-Width)
- **Default**: `Intermediate` — bewusst konservativ (besser als zu offensiv, vgl. SLF-Pattern)
- **Kein erzwungenes Onboarding-Modal beim ersten Besuch** — das schreckt ab. Stattdessen: Bei Standard-Default `Intermediate` zeigen wir EINEN Onboarding-Tooltip beim ersten Marker-Klick: "Tipp: stell dein Pilotenprofil unten in der Legende ein, dann wird die Karte fuer dich gefiltert. [verstanden] / [spaeter]"

**Vier Profile, vier Auswirkungen**:

| Profil | Glyphe-Rendering | Filterung |
|--------|------------------|-----------|
| Beginner | unveraendert | red + amber: 35% Opacity, klickbar mit Modal-Warnung |
| Intermediate (default) | unveraendert | red: 45% Opacity, amber: 80% Opacity |
| Advanced | unveraendert | alle voll saturiert |
| Pro | unveraendert | alle voll saturiert + Sortier-Toggle "Stars first" verfuegbar |

**Wichtig**: Profil aendert NIE die Glyphe selbst (`safety_band` und Stern-Ziffer sind fuer alle Profile identisch). Es aendert **nur Opacity** und Filter-Sortierung. Das vereinfacht den Code drastisch — eine einzige Glyphe, profilbasierte CSS-Klasse `marker-dimmed`.

### 8.6 Spot-Panel — Hierarchie der Information

Heutiges Panel zeigt Decision-Notes + Meteogramm + Windverlauf. Mit dem neuen Konzept kommen Stars + Comfort hinzu. **Sektion 4.2 (drei gleichgewichtige Bloecke) wird hier ueberarbeitet** — wir brauchen klare 2-Sekunden-Hierarchie.

#### Wireframe vor (heute)

```
+----------------------------------------------------+
| FIESCH-KUEHBODEN                              [×] |
| Toggenburg, 1071m | Wind: SW                       |
| [Rating-Badge: 7.8/10 violet]                      |
+----------------------------------------------------+
| [Meteogramm-Tabs: Heute | Fr | Sa | ...]          |
+----------------------------------------------------+
| [Meteogramm-Chart, full width]                    |
+----------------------------------------------------+
| [Decision-Notes / Caution-Notes als Liste]        |
+----------------------------------------------------+
```

#### Wireframe nach (v1.1)

```
+----------------------------------------------------+
| FIESCH-KUEHBODEN                              [×] |
| Toggenburg, 1071m | Wind: SW                       |
+----------------------------------------------------+
|                                                    |
|        [AMB 4]      <-- HERO: gleiche Glyphe       |
|                          wie auf der Karte         |
|        Vorsicht                                    |
|        4 Sterne · 82/100                           |
|                                                    |
|        Foehnrisiko 4.5 — fliegbar fuer Pros        |
|                                                    |
+----------------------------------------------------+
| [Tabs: Meteogramm | Windverlauf | Details]        |
+----------------------------------------------------+
| [aktiver Tab-Inhalt]                              |
+----------------------------------------------------+
| ▾ Erweitert (collapsed default)                   |
|   Comfort: 45/100 — mechanisch ruppig              |
|   Decisions: FoehnCaution(4.5), GustFloor          |
|   Empfehlung Profil Advanced: ...                  |
+----------------------------------------------------+
```

**Hierarchie der Information (was sieht User in den ersten 2 Sekunden)**:

1. **Hero-Block (Sekunde 1)**: Die GLEICHE Glyphe wie auf der Karte, gross zentriert, mit Klartext-Label "Vorsicht · 4 Sterne · 82/100". Pilot rekognosziert sofort: "Ja, das ist der Marker, den ich angeklickt habe." Continuity = Trust.
2. **Subtitle (Sekunde 2)**: Ein-Satz-Zusammenfassung warum: "Foehnrisiko 4.5 — fliegbar fuer Pros". Diese Zeile generiert die Decision-Engine bereits (canonical caution_notes oder rationale).
3. **Tabs**: Meteogramm bleibt erste Wahl (heute ebenso). Windverlauf bleibt. NEU: **Tab "Details"** mit Comfort-Index + voller Decision-Liste — fuer Pros, die Tiefe wollen.
4. **Erweitert-Akkordeon (collapsed default)**: Zeigt Comfort, alle Decisions, Profil-spezifische Empfehlung. Wird automatisch auf `expanded` gesetzt, wenn Pilot-Profil `Pro` ist (Profil-driven Defaults).

**Was sich konkret aendert vs. heutiges Panel** (in `static/js/meteogram.js` `renderAnalysisView`):
- Aktuelles Rating-Badge (`ratingBadgeEl`, `meteogram.js:528`) wird zur Hero-Glyphe — gleicher Renderer wie Karten-Marker, nur skaliert (60×60 statt 14×14).
- Decision-Notes-Liste wandert in Akkordeon "Erweitert" oder Tab "Details".
- Comfort-Index erscheint nur im Akkordeon — ist **bewusst nicht prominent**, weil er nicht primaere Score ist (vgl. Sektion 2.2).

#### Sonderfall: Rote Spots ohne Analyse (NEU v1.3)

**Hintergrund**: Nicht jeder rote Spot hat eine vertiefte Analyse. Wenn die Bedingungen so eindeutig nicht fliegbar sind, dass eine Auswertung keinen Mehrwert bringt — z.B. Windrichtung passt grundsaetzlich nicht zum Startplatz — wird **keine detaillierte LLM-Analyse erstellt**. Der Spot ist einfach rot.

**Wie wird das gekennzeichnet?**
- Cache-Feld `noAnalysis: true` (oder `analysis_skipped: true` — Naming TBD bei Implementation)
- Optional: `noAnalysisReason` (kanonischer Grund-Tag, z.B. `"wind_direction_mismatch"`, `"out_of_season"`)

**UI-Verhalten im Spot-Panel** (siehe `docs/rating_preview.html` als Referenz):
- Header bleibt: Name, Region, Hoehe, Wind
- Hero-Block bleibt: Glyphe, Verdict ("Nicht fliegbar"), Score, Rationale (kann z.B. lauten: "Spot ist heute nicht fliegbar. Falsche Anstroemung — keine vertiefte Auswertung.")
- **Statt Decision-Hero / Best-Window / Alerts**: ein einzelner kompakter Block:
  ```
  ⊘  Keine Analyse
     Windrichtung passt nicht zur Startrichtung — keine
     detaillierte Analyse erstellt.
  ```
- **Kein Meteogramm** — die Daten sind irrelevant fuer den Use-Case "fliege ich heute"
- "Andere Spots heute"-Strip bleibt (User soll Alternative finden)

**Abgrenzung zu rotem Spot mit Analyse**:
- Rot mit Analyse (z.B. Niesen-Foehn): zeigt vollen Decision-Hero + Caution-Notes + Foehn-Risiko-Wert + Meteogramm — User versteht WARUM
- Rot ohne Analyse: zeigt nur "geht nicht heute, aus diesem grundsaetzlichen Grund" — User braucht keine Detaildiagnose

**Implementierungs-Hinweis**: Der `noAnalysis`-Pfad wird vermutlich in der Engine vor dem LLM-Call entschieden — z.B. wenn Wind-Richtung-Filter den Spot bereits aussortiert. Spart LLM-Calls und macht UI klarer.

### 8.7 Migration — wie verhindern wir, dass Bestands-User verwirrt sind?

Heute kennen User die green/violet/gray-Ampel in 3 Levels. v1.1 hat 6 Zustaende (gruen 1–5, amber 1–5, red). Migration muss sanft sein.

**Empfohlene Strategie**: **Soft Cutover mit kontextueller Hilfe** — kein A/B-Toggle, keine Hard-Migration.

**Phase 1 (Launch-Tag)**:
- Karte zeigt sofort die neuen Glyphen.
- **Welcome-Banner oben auf der Karte** (verschwindet nach 1× Klick "verstanden", localStorage):
  ```
  ✦ Neu: Sterne im Marker zeigen, wie lohnend ein Tag ist.
    Farbe = Sicherheit (gruen/orange/rot), Zahl = Erlebnis (1–5).
    [verstanden]   [Mehr erfahren]
  ```
- **Onboarding-Tooltip beim ersten Marker-Klick** (auch nur 1×): "Stell dein Pilotenprofil in der Legende ein, dann wird die Karte fuer dich gefiltert."

**Phase 2 (Woche 2–4)**:
- Logging: wieviele User klicken "Mehr erfahren", wieviele setzen Profil ungleich Default, Bounce-Rate auf Karte.
- Wenn Bounce-Rate auf Karte ≥ +10% vs. Vorwoche: Rollback-Trigger, neuer Welcome-Banner mit klareren Erklaerungen.

**Phase 3 (Monat 2)**:
- Klassische Tier-Ansicht NICHT mehr verfuegbar als Toggle. Begruendung: zwei parallele UI-Modi sind Wartungsalbtraum fuer Solo-Entwickler.
- `flyability_tier` bleibt im Cache fuer Email-Subscribers + Chat-Engine (Backwards-Compat, vgl. Sektion 5.1).

**Was ich NICHT empfehle**:
- ❌ "Klassische Ansicht / Neue Ansicht"-Toggle: doppelter UI-Code, geteilter Test-Aufwand, Solo-Entwickler kann das nicht halten.
- ❌ Hard-Cutover ohne Welcome-Banner: User sehen Marker-Aenderung ohne Erklaerung, Verwirrung garantiert.
- ❌ Erzwungenes Onboarding-Modal beim ersten Besuch nach Update: nervig, hohe Bounce-Rate.

### 8.8 Was wird aus dem alten Konzept gestrichen / geaendert?

Diese Stellen in der bestehenden `RATING_CONCEPT.md` sind durch v1.1 superseded — markiert, nicht geloescht:

| Sektion | Ueberholt durch | Was bleibt |
|---------|-----------------|-----------|
| 4.1 "Outer Ring + Inner Stars" Marker-Konzept | Sektion 8.2 (Single-Glyph mit Ziffer) | Das Prinzip "Safety-Farbe + Experience-Mass in einer Glyphe" bleibt — nur die visuelle Umsetzung wird simpler |
| 4.1 Toggle-Reihen "Sicherheits-Vorrang / Erlebnis-Vorrang" oben rechts | Sektion 8.5 (kein Toggle, Profil sitzt in Legende) | Profil-driven Filterung bleibt, kommt nur ohne Toggle aus |
| 4.2 Spot-Panel mit drei gleichgewichtigen Bloecken (Sicherheit / Erlebnis / Comfort) | Sektion 8.6 (Hero-Glyphe + Akkordeon-Hierarchie) | Drei Achsen werden weiterhin angezeigt, aber **gewichtet**: Safety+Stars Hero, Comfort im Akkordeon |
| 4.3 Region-Panel + 2D-Scatter | unveraendert (Region-Panel ist Wochenuebersicht, kein 1-Sekunden-Scan-Use-Case) | komplett gueltig |
| 5.2 Frontend-Aufwand "Marker-Renderer: Zwei-Layer-Encoding" | Sektion 8.2 "+20 Zeilen im bestehenden Generator" | Server-Aufwand bleibt unveraendert, Frontend ist deutlich kleiner |
| 7. naechste Schritte: "Schritt 3: Frontend-Prototyp 5 Tage" | reduziert auf ~3 Tage durch Single-Glyph-Vereinfachung | Phase-Plan grundsaetzlich gueltig |

**Konkrete Saetze, die als "superseded by Sektion 8.X" markiert sind** (im obigen Edit bereits eingefuegt):
- Sektion 4.1 Eingangs-Hinweis-Box: zeigt User, dass diese Sektion ueberholt ist
- Sektion 4.1 "Outer Ring" Vorschlag: superseded
- Sektion 4.1 Pilot-Profil-Filter Liste: superseded
- Sektion 4.1 Toggle-Reihe: superseded
- Sektion 4.2 Eingangs-Hinweis: superseded by 8.6

### 8.9 Aufwand-Update fuer Solo-Entwickler

| Schritt | Sektion 5.2 (alt) | Sektion 8 (v1.1) | Delta |
|---------|--------------------|--------------------|-------|
| Server (decision_engine + Tests) | 2–3 Tage | 2–3 Tage | unveraendert |
| Frontend Marker | im 4–5 Tage Block | ~1.5 Tage | **−2.5 Tage** |
| Frontend Spot-Panel-Refactor | im 4–5 Tage Block | ~1.5 Tage (Hero-Glyphe + Akkordeon) | unveraendert |
| Pilot-Profil-Toggle in Legende | 2 Tage | 1 Tag (in Legende statt eigenem Modal) | **−1 Tag** |
| Welcome-Banner + Onboarding-Tooltip | nicht eingeplant | 0.5 Tage | **+0.5 Tage** |
| Skill-Sync + Doku | 1 Tag | 1 Tag | unveraendert |
| **Total** | **2 Wochen** | **~7–8 Tage** | **−3 Tage** |

Der Single-Glyph-Ansatz spart Solo-Entwickler-Zeit, weil er auf der bestehenden `createSpotIcon`-Funktion aufbaut, statt sie zu refaktorieren.

### 8.10 Validation-Checkpoints (vor Build)

Bevor implementiert wird, muessen folgende Punkte geklaert sein:

- [ ] **Lesbarkeit der Stern-Ziffer**: Mockup mit 9px Inter-Bold weiss auf `#22c55e` testen (Retina + non-Retina Display, mobiles Squinting). Falls < 4mm Lese-Distanz nicht reicht, auf Sterne als Mini-Glyphen zurueckfallen (5 winzige Punkte).
- [ ] **Welcome-Banner-Wording**: 5 Bestands-User testen — verstehen sie nach 5 Sekunden was die Glyphe bedeutet?
- [ ] **A11y-Test**: Color-Blind-Simulator (Protanopia, Deuteranopia, Tritanopia) — die Stern-Ziffer ist das primaere unique-identification-Element bei Color-Blind-Usern. Reicht das?
- [ ] **Mobile Tap-Test**: Glyphe auf 6"-Display in Karten-Zoom 8 (CH-Uebersicht) — sind benachbarte Spots noch unterscheidbar?

---

## 9. Konsistenz mit bestehendem Rating-System (Iteration v1.2)

**Status**: Pflicht-Konsistenzpruefung nach User-Frage 2026-04-30:
*"Ist das harmonisch in unser bestehendes Rating mit no-go / conditional / gruen etc. eingebettet? Passen diese Konzepte zusammen?"*

**Vorgehen**: Code-Lesen statt Vermuten. Geprueft wurden `engine/decision_engine.py`,
`engine/analyzers.py` (Post-Process-Pipeline), `engine/_common.py`
(Tier-Ranges + Rating-Berechnung), `docs/DECISIONS.md`,
`skills/shared/_flyability_tiers.md`, `skills/chat_capabilities_guide.md`.

**Ergebnis vorab**: Das v1.1-Konzept ist **konzeptuell richtig**, hat aber
**drei Bloss-Stellen** gegenueber dem bestehenden System, die korrigiert
werden muessen, bevor implementiert wird. Sie sind in 9.4 und 9.5 dokumentiert.

### 9.1 Status quo: was bedeutet was heute?

Das heutige System hat **drei separate Strukturfelder**, die unterschiedlich
befuellt werden und unterschiedlich wirken. Sie sind nicht so klar getrennt,
wie es Sektion 1 dieses Dokuments suggeriert.

| Feld                  | Werte                                  | Quelle / wer schreibt                                                                  | Wirkung im UI                              |
| --------------------- | -------------------------------------- | -------------------------------------------------------------------------------------- | ------------------------------------------ |
| `safety_status`       | `safe` / `conditional` / `not_safe` / `no_data` | LLM (Phase 1 Safety) → Decision-Engine ueberschreibt autoritativ                                              | Karten-Marker: rote Stripe = not_safe; sonst implizit ueber `flyability_tier` |
| `flyability_tier` (= `fly_status` = `status`) | `gray` / `green` / `violet` / `""` (bei not_safe) | LLM (Phase 2 Flyability) → Decision-Engine ueberschreibt: Downgrade, Upgrade, Region-Gate | **Primaere Marker-Farbe** auf der Karte    |
| `rating`              | float 0.0–10.0                         | Deterministisch berechnet aus 4 LLM-Sub-Ratings (`thermal_rating`, `window_rating`, `wind_rating`, `xc_rating`) via `_compute_rating_from_subratings` (`engine/_common.py:421`), dann via `_clamp_rating_to_tier` auf Tier-Korridor geclampt | Briefing-Sortierung; Spot-Panel-Badge "7.8/10 violet" (heute Iteration v1.0 noch sichtbar) |
| `is_conditional`      | bool                                   | LLM (mit Skill-Regeln aus `_flyability_tiers.md`) — **NICHT von Decision-Engine ueberschrieben** | Conditional-Badge im Briefing/Map         |
| `foehn_risk`          | `none` / `moderate` / `high`           | Decision-Engine autoritativ aus `_ctx_foehn_cache`                                     | Foehn-Badge UI-Backstop in `region-map.js`/`meteogram.js` |
| `_decisions_applied`  | Liste von Tags                         | Decision-Engine schreibt jeden gefeuerten `decide_*` rein                              | Heute nicht im UI, in v1.1 als "Decisions"-Tab geplant |
| `caution_notes`       | Liste Strings                          | LLM + Decision-Engine ergaenzt kanonische Eintraege                                    | Tooltip-Detail / Spot-Panel               |
| `no_go_reasons`       | Liste Strings                          | LLM + Decision-Engine ergaenzt kanonische Eintraege                                    | Spot-Panel-Hero bei not_safe              |
| `primary_no_go`       | String-Key                             | LLM oder Decision-Engine (`primary_no_go=FOEHN`/`ALOFT_DANGER`)                        | UI-Badge bei not_safe                     |

**Wichtigste Erkenntnis aus dem Code**:

`safety_status` und `flyability_tier` sind heute **nicht orthogonal**, sondern
gestaffelt:

1. `_post_process_flyability_spot` (`engine/analyzers.py:1685`) **leert** bei
   `safety_status == "not_safe"` saemtliche Flyability-Felder (Hard-Gate).
   Es gibt also **keinen** Spot-Tag mit `safety_status=not_safe AND flyability_tier=green`.
2. Umgekehrt kann `safety_status=conditional` mit jeder `flyability_tier`
   kombiniert werden.
3. `rating` ist auf Tier-Korridore geclampt: `gray=2.0-4.9 / green=5.0-8.4 /
   violet=8.5-10.0` (`_TIER_RATING_RANGES`, `_common.py:395`). Damit ist Rating
   **nicht unabhaengig** vom Tier — es ist eine feinere Aufloesung INNERHALB des Tiers.

**Korrektur an Sektion 1 dieses Dokuments**:
Das TL;DR sagt "`flyability_tier` vermischt Sicherheit und Erlebnis". Das
stimmt fuer den Tier-Wert selbst nur teilweise. Was hier wirklich
vermischt: `decide_flyability_downgrade` (`decision_engine.py:361`) triggert
**unter anderem** auf `rough_pct > 50` — das ist eine Mechanik-/Sicherheits-Bewertung,
die den Tier nach unten zieht. Komfort/Mechanik ist heute also bereits in
`flyability_tier` mit drin, nicht (wie Sektion 1 implizit andeutet) erst durch
das neue `comfort_index` zu erfassen.

### 9.2 Mapping bestehend → neu (definitiv)

| Bestehend (heute)                              | Neu (v1.1/v1.2)                                                                | Mapping-Typ           |
| ---------------------------------------------- | ------------------------------------------------------------------------------ | --------------------- |
| `safety_status = safe`                         | `safety_band = green`                                                          | 1:1                   |
| `safety_status = conditional`                  | `safety_band = amber`                                                          | 1:1                   |
| `safety_status = not_safe`                     | `safety_band = red` (UI-Label "Nicht fliegbar")                                | 1:1                   |
| `safety_status = no_data`                      | `safety_band = neutral` (grauer Marker, keine Glyphe)                          | 1:1                   |
| `flyability_tier = green`, peak gut, prod_h ok | `safety_band = green/amber` (je nach safety_status) + `experience_stars = 3-4` | abgeleitet aus rating |
| `flyability_tier = violet`                     | `safety_band` aus safety_status + `experience_stars = 4-5`                     | abgeleitet aus rating |
| `flyability_tier = gray`                       | **zwei Faelle**: (a) "sicher aber langweilig" → green/1-2 Sterne; (b) "Klapper-/Wind-UNUSABLE > 50%" → amber oder red — siehe 9.4 Bruch 1 | KEIN 1:1, abhaengig vom Down-Grade-Grund |
| `rating = 7.8` (greens range 5.0-8.4)          | `experience_stars = 4` (via Schwellen 0-20/21-40/.../90-100)                   | Schwellenmapping      |
| `is_conditional = true`                        | wird zu `safety_band = amber` (siehe 9.4 Bruch 3)                              | umgewidmet            |
| `_decisions_applied = ["FoehnCaution(4.5)"]`   | Drives `safety_band` upgrade (none→amber)                                      | bleibt — Decision-Engine ist Quelle |
| `_decisions_applied = ["FoehnDanger(8.0)"]`    | Drives `safety_band = red`                                                     | bleibt — Decision-Engine ist Quelle |
| `caution_notes` (canonical)                    | Bleibt 1:1; im Spot-Panel unter Akkordeon "Erweitert" oder im Hero-Subtitle    | bleibt                |
| `no_go_reasons` (canonical)                    | Bleibt; im Spot-Panel-Hero bei `safety_band = red` ueber den Marker            | bleibt                |
| `primary_no_go` (Key wie "FOEHN")              | Bleibt; im UI-Backstop fuer Foehn-Badge                                        | bleibt                |
| `productive_thermal_h`                         | Input fuer `experience_score` (Komponente prod_pts)                            | Source                |
| `peak_climb_rate`                              | Input fuer `experience_score` (Komponente climb_pts)                           | Source                |
| `tq_danger_h` (gesamt, ohne rough)             | Input fuer `experience_score` (Quality-Penalty)                                | Source                |
| `rough_danger_h` / `rough_pct`                 | **Korrigiert in v1.2**: Input fuer `comfort_index` UND triggert weiter `decide_flyability_downgrade` (= safety_band-relevant ueber Decision-Engine). Siehe 9.4 Bruch 2. | Source — doppelt verwendet |
| `_TIER_RATING_RANGES` (gray 2-4.9, green 5-8.4, violet 8.5-10) | **Aufloesen** — `rating` wird abgeleitete View-Funktion; siehe 9.7 | Streichkandidat       |
| `flyability_tier`                              | **Bleibt im Cache als Compatibility-View** fuer Chat + Mail; UI nutzt `safety_band`+`experience_stars` | Legacy-View           |
| `streckenflug.tier` (kein_xc/lokal/moderat/top) | Bleibt; im Spot-Panel-Detail unter "XC-Potenzial"                              | bleibt                |

### 9.3 Decision-Engine: was wirkt jetzt auf welche Achse?

Pro Decision: heutige Wirkung → kuenftige Wirkung (v1.2). Reihenfolge wie in
`docs/DECISIONS.md` Sektion 3-5.

| Decision                          | Heutige Wirkung                                  | Wirkung in v1.2 (Achse)                | Bemerkung |
| --------------------------------- | ------------------------------------------------ | -------------------------------------- | --------- |
| Pre-Filter `_prefilter_not_safe`  | safety_status = not_safe (LLM-Bypass)           | safety_band = red                      | 1:1       |
| `decide_wind_ok_zero`             | safety_status → not_safe                         | safety_band → red                      | 1:1       |
| `decide_aloft_not_safe`           | safety_status → not_safe                         | safety_band → red                      | 1:1       |
| `decide_aloft_conditional`        | safety_status safe → conditional                 | safety_band green → amber              | 1:1       |
| `decide_gust_floor`               | safety_status safe → conditional                 | safety_band green → amber              | 1:1       |
| `decide_overclaim_relax`          | safety_status not_safe → conditional (DEMOTE)    | safety_band red → amber                | 1:1, einziger Demote |
| `decide_wind_strong_majority` (Region) | safety_status → not_safe                    | safety_band → red                      | 1:1       |
| `apply_foehn_decision` (caution)  | foehn_risk=moderate, safety_status mind. conditional | foehn_risk bleibt, safety_band mind. amber | 1:1   |
| `apply_foehn_decision` (danger)   | foehn_risk=high, safety_status=not_safe          | foehn_risk bleibt, safety_band = red   | 1:1       |
| `decide_flyability_downgrade` (3 Sub-Trigger) | flyability_tier green/violet → gray  | **gespalten** (siehe 9.4 Bruch 2):     | Bruch     |
| – Sub-Trigger A: keine Thermik (peak<0.3 oder hours==0) | → gray                          | → experience_stars = 0-1, safety_band unveraendert | reine Reward-Frage |
| – Sub-Trigger B: rough_pct > 50 (mech. Klapper) | → gray                            | → safety_band amber + experience_stars-Cap | sicherheitsrelevant! |
| – Sub-Trigger C: prod_h < PRODUCTIVE_HOURS_DOWNGRADE | → gray                       | → experience_stars = 0-2, safety_band unveraendert | reine Reward-Frage |
| `decide_flyability_upgrade` (gray→green) | flyability_tier gray → green              | experience_stars rauf, kein safety_band-Effekt | nur Reward |
| `decide_flyability_region_gate` (Spot violet → green wenn Region nicht violet) | flyability_tier violet → green | experience_stars-Cap fuer Spots ohne Region-Konsens | nur Reward |
| Hard-Gate `_post_process_flyability_spot:1685` (not_safe → fly_status="") | Flyability-Felder geleert | experience_stars = 0 + Felder geleert | bleibt — safety_band red gibt eh keine Stars |

### 9.4 Brueche und ihre Aufloesung

**Bruch 1: `flyability_tier = gray` ist heute zwei verschiedene Dinge.**

Ein `gray`-Spot kann aus drei verschiedenen Gruenden grau sein
(`decide_flyability_downgrade`):
- (A) Keine Thermik → "sicher aber Abgleiter, wenig Spass"
- (B) ROUGH/WIND-UNUSABLE > 50% → "es klappert, gefaehrlich"
- (C) Zu wenige produktive Stunden → "Mau-Tag"

Heute landen alle drei im selben `gray`-Bucket. In v1.2 muessen sie
unterschiedlich gemappt werden:
- Fall A und C: `safety_band = green/amber` (je nach `safety_status`) +
  `experience_stars = 0-2`. Karte zeigt: "sicher fliegbar, aber lohnt sich nicht".
- Fall B: `safety_band = amber` (mechanisches Risiko ist Sicherheits-Thema, nicht
  Reward-Thema) + `experience_stars` Cap auf 1-2. Karte zeigt: "Vorsicht,
  Klapperrisiko, kein Spass".

**Aufloesung**: `decide_flyability_downgrade` aufspalten in `decide_flyability_low_reward`
(A+C) und `decide_flyability_mech_danger` (B). Letzterer schreibt zusaetzlich auf
`safety_band` (oder triggert ein neues `decide_safety_mech_rough_amber`).
**Code-Aufwand**: ~20 Zeilen in `decision_engine.py`, +2 Tests.

**Bruch 2: rough_pct ist heute ein Safety-Eingang, im v1.0-Konzept ein
Comfort-Eingang.**

Sektion 3.2 sagt:
> *"`rough_pct` geht NICHT in experience_score ein. Rough = mechanisches
> Klappern = Sicherheitsthema = `safety_band`-Sache (bereits via
> `_decisions_applied` und `safety_status` abgedeckt, da ROUGH-UNUSABLE in
> `safety_status` bewertet wird)."*

Das ist **falsch im Bezug auf den heutigen Code**. ROUGH-UNUSABLE wirkt heute
auf `flyability_tier` via `decide_flyability_downgrade`, **nicht** auf
`safety_status`. Es gibt keine `decide_*`-Funktion, die rough auf safety
schreibt.

**Aufloesung**: Bruch 1 ist die Loesung. Wenn wir
`decide_flyability_mech_danger` einfuehren und der ROUGH-Subtrigger
`safety_band = amber` setzt, dann stimmt die Aussage von Sektion 3.2 nachher.
Voraussetzung: Bruch 1 wird umgesetzt, bevor `comfort_index` produktiv wird.

**Bruch 3: `is_conditional` und `safety_band = amber` ueberlappen.**

`is_conditional` wird heute vom LLM gesetzt (Skill-Regeln aus
`_flyability_tiers.md`), wenn:
- Foehn-Indikator = "caution"
- TQ-Tags 10-50% (mittleres Klapperrisiko)
- Tiefe Wolkenbasis < Startplatz + 500m

Das ueberlappt fast 1:1 mit dem v1.0-amber-Konzept. Allerdings ist
`is_conditional` heute NICHT von der Decision-Engine ueberschrieben — der LLM
darf das Flag setzen, wie er will. Das ist eine Inkonsistenz mit dem Stage-Inversion-Pattern.

**Aufloesung-Vorschlag**: `is_conditional` wird **ersetzt** durch
`safety_band == "amber"`. Dazu:
- `is_conditional` wird in der Decision-Engine **abgeleitet** aus
  `safety_band == "amber"` UND nicht weiter vom LLM uebernommen.
- Skill `_flyability_tiers.md` Sektion "CONDITIONAL-FLAG" wird gestrichen
  (LLM soll das Flag nicht mehr setzen).
- Im Cache bleibt `is_conditional = bool` als Compatibility-Feld
  (Briefing-Frontend liest es).

**Bruch 4: `_TIER_RATING_RANGES` macht Rating und Tier nicht orthogonal.**

Heute clampt `_clamp_rating_to_tier` (`_common.py:402`) das LLM-Rating in
den Tier-Korridor. Gray-Spots koennen also nie ueber 4.9 sein, violet nie
unter 8.5.

In v1.2 soll `experience_score` (0-100) unabhaengig vom Tier berechnet
werden. Das wuerde bedeuten: ein "gray, 4 Sterne, score 78" ist plausibel
(Fall A: keine Thermik → wenige Sterne, also passt) — aber ein "violet, 1
Stern, score 18" ist nicht moeglich (violet = stark XC, hohe Stars).

**Aufloesung**: Da `flyability_tier` ohnehin durch `safety_band` +
`experience_stars` ersetzt wird, ist `_TIER_RATING_RANGES` ohne Funktion
sobald die Migration steht. Solange `flyability_tier` als Compat-View
existiert (bis Mail/Chat umgestellt sind), wird die Tier-Range-Klemme weiter
angewendet. Nach der Mail/Chat-Migration kann `_clamp_rating_to_tier`
gestrichen werden.

**Bruch 5: gray→green Override und gray→green Decision-Upgrade sind redundant in v1.2.**

Das aktuelle System hat eine Override-Logik (`decide_flyability_upgrade`,
`decision_engine.py:400`): gray → green wenn `productive_thermal_h ≥
PRODUCTIVE_HOURS_FOR_GREEN` AND `rough_pct < 50`. Die schreibt auch
`peak_climb_rate`, `flight_type`, `recommendation` neu.

In v1.2 ist diese Logik teilweise obsolet:
- `experience_stars` werden ohnehin direkt aus `productive_thermal_h` und
  `peak_climb_rate` berechnet — kein gray→green-Trick mehr noetig fuer das
  Reward-Mass.
- Die Text-Felder (peak_climb_rate, flight_type, recommendation) muessen
  weiter ueberschrieben werden, solange das LLM diese Felder produziert. Fuer
  `flyability_tier` als Compat-View gilt: wenn experience_stars >= 3 und
  safety_band <= amber → tier = green (sonst gray).

**Aufloesung**: `decide_flyability_upgrade` bleibt zunaechst aktiv (Phase 1),
aber wird durch eine reine Compat-Funktion `compute_legacy_flyability_tier`
ersetzt (Phase 2), die aus `safety_band` + `experience_stars` rueckwaerts
auf gray/green/violet mappt. Dann werden beide `decide_flyability_*` zur
reinen View-Logik.

**Bruch 6 (NEU v1.3): Asymmetrie zwischen Experience- und Safety-Achse.**

Heute hat die Experience-Seite ein bewaehrtes 4-Sub-Rating-Pattern
(`engine/_common.py:421`), die Safety-Seite nur eine kategoriale `safety_status`
(safe/conditional/not_safe). Konsequenzen:

- **Keine Granularitaet**: Zwischen "knapp safe" und "komfortabel safe" kein
  numerischer Unterschied. Pro-User koennen nicht nach Safety-Score sortieren.
- **`safety_status` direkt vom LLM**: Verletzt das fuer Experience etablierte
  Hybrid-Pattern (LLM beurteilt Aspekte, App aggregiert). Decision-Engine
  ueberschreibt zwar via Hard-Decisions, aber das LLM-Urteil zwischen den
  Hard-Faellen bleibt unaggregiert.
- **`caution_notes` muessen Quantitaet tragen**: "leichter Foehn-Einfluss" vs
  "deutlicher Foehn-Einfluss" landet als Freitext, nicht als Score.

**Aufloesung**: 4 Safety-Sub-Ratings einfuehren (siehe §3.5), parallel zu den
4 Fliegbarkeits-Sub-Ratings:
- `wind_safety_rating`, `gust_safety_rating`, `aloft_safety_rating`,
  `foehn_safety_rating` — je 1-10 vom LLM
- Neue Aggregations-Funktion `_compute_safety_rating` (Gewichte 30/25/25/20)
- Skalierung × 10 → `safety_score` (0-100)
- `safety_band` aus Score + Decision-Engine-Hard-Overrides (Hard-Override hat
  Vorrang)

**Code-Aufwand**:
- LLM-Prompt erweitern (`prompts.py`) — 4 zusaetzliche Output-Felder, ~30 Zeilen
- `engine/_common.py` — neue Funktion `_compute_safety_rating`, ~20 Zeilen, +
  4 Tests
- `engine/decision_engine.py` — `compute_safety_band` integriert Score + Hard-
  Overrides, ~25 Zeilen, +5 Tests
- Skill `_flyability_tiers.md` (oder neu `_safety_subratings.md`) — Anweisung an
  LLM, was die 4 Safety-Sub-Ratings bedeuten, ~50 Zeilen Skill-Doku

**Voraussetzung**: Bruch 1, 2, 3 erst aufgeloest (saubere Stage-Inversion bevor
neue LLM-Outputs eingefuehrt werden).

**Risiko**: Mehrere LLM-Outputs erhoehen Antwort-Token-Anzahl leicht. Pro Spot
4 zusaetzliche Felder × ~10 Token ≈ 40 Token mehr. Bei 28 Spots × 7 Tagen ≈
8000 zusaetzliche Output-Token pro Run. Akzeptabel.

### 9.5 Chat-Engine + Mail-Subscriber: was passiert mit der Legacy-Sprache?

**Befund aus `skills/chat_capabilities_guide.md`**:

| Section | Quelltext (verkuerzt) | Sprache         |
| ------- | --------------------- | --------------- |
| 1.3     | "Fliegbarkeit: Bronze / Gruen / Violett (JSON-Enum gray/green/violet)" | Bronze/Gruen/Violett (UI-Sprache) + Enum |
| 2.2     | RECOMMENDED-Tag `status`: `green` (Standard, = Gruen), `violet` (= Violett), `gray` (= Bronze/Abgleiter) | Beides |
| 4       | "Sortieren: Violett > Gruen > Bronze (Enum: violet > green > gray)" | Beides |
| 5       | "Balderen: conditional", "First: safe" | safety_status |
| 7       | "Alternative bei not_safe: ..." | safety_status |

**Befund aus `skills/shared/_flyability_tiers.md`**:
- Skill ist 100% in Tier-Sprache (Bronze/Gruen/Violett) verfasst.
- Erklaert TIER-DEFINITIONEN, TQ-DOWNGRADE-REGEL, CONDITIONAL-FLAG.
- Setzt `flyability_tier` (Enum) und `is_conditional`.

**Befund aus Mail-Subscribers**: Es gibt aktuell keine eigenstaendigen
Mail-Templates im Repo (Suche `templates/email` ergab nichts);
Subscriber-Mails werden vermutlich durch `subscriber.py` aus den
`spot_analyses.json`-Strukturen erzeugt. Das muss vor der Implementation
gegengeprueft werden — wenn Mails Tier-Sprache nutzen, ist das ein zweiter
Migrationspunkt.

**Befund aus `chat_engine.py` System-Prompt** (laut MEMORY.md):
Der Capabilities-Guide wird via `prompts.py → CAPABILITIES_GUIDE` in den
System-Prompt injiziert. Aenderungen am Guide propagieren also direkt in
jede Chat-Antwort.

**Empfehlung — Zwei-Phasen-Migration**:

| Phase   | UI                                  | Cache                                   | Chat-Engine                                | Mail                                  |
| ------- | ----------------------------------- | --------------------------------------- | ------------------------------------------ | ------------------------------------- |
| Phase 1 | safety_band + experience_stars (neu) | beide Felder (neu + flyability_tier als Compat-View) | unveraendert (spricht weiter Bronze/Gruen/Violett) | unveraendert |
| Phase 2 | dito                                | dito                                    | umgestellt: `_flyability_tiers.md` ersetzt durch `_safety_experience.md`; `chat_capabilities_guide.md` Sections 1.3/2.2/4 umformuliert | Templates auf safety_band/experience_stars umgestellt |
| Phase 3 | dito                                | `flyability_tier` deprecated, dann entfernt; `_TIER_RATING_RANGES` entfernt; `_clamp_rating_to_tier` entfernt | dito | dito |

**Konkrete Reihenfolge der Files in Phase 2**:
1. Skill: `skills/shared/_flyability_tiers.md` → neu schreiben als `_safety_experience.md`
2. Capabilities: `skills/chat_capabilities_guide.md` Sections 1.3, 2.2, 4 umformulieren
3. RECOMMENDED-Tag in `static/js/chat.js` und `chat-charts.js`: status-Argument akzeptiert neu `safety=red|amber|green` und `stars=N` zusaetzlich zur alten `green|violet|gray`-Sprache. Kompatibel uebersetzen.
4. Mail-Renderer (Subscriber): pruefen, ob green/violet/gray in den Templates auftaucht und auf safety_band+stars umstellen.

**Wichtig**: Phase 2 darf NICHT vor Phase 1 stattfinden. Sonst sieht der User
auf der Karte amber/4-Sterne, in der Mail steht "violet" — und das ist
genau der Sprach-Bruch, den der User in seiner Frage befuerchtet.

### 9.6 Migration-Plan v2 (verfeinert nach Konsistenz-Pruefung)

**Ablehnen**: Der "Soft Cutover" aus Sektion 8.7 ist unter Phase 1 alleine
machbar — der gleichzeitige Cut von UI + Chat + Mail waere ein
Big-Bang-Risiko, das ein Solo-Entwickler nicht halten kann.

**Empfehlung**: 3-Phasen statt 1-Phase.

#### Phase 1 — UI-Switch + Decision-Engine-Erweiterung (Woche 1-2)

Ziel: Karte und Spot-Panel auf safety_band+experience_stars umgestellt.
Cache enthaelt **beide** Welten — `flyability_tier` bleibt unveraendert
befuellt (Compat).

Aufgaben:
1. **Bruch 1 aufloesen**: `decide_flyability_downgrade` aufspalten in
   `decide_flyability_low_reward` (A+C) und `decide_flyability_mech_danger` (B).
   Letzterer triggert ein neues `decide_safety_mech_rough_amber`, das auf
   `safety_band` = amber wirkt.
2. **Bruch 3 aufloesen**: `is_conditional` von Decision-Engine ableiten lassen
   (`is_conditional = (safety_band == "amber")`); im Skill-Prompt Anweisung
   streichen.
3. Drei neue Decision-Funktionen: `compute_safety_band`, `compute_experience_score`,
   `compute_comfort_index` in `engine/decision_engine.py`.
4. Aufruf am Ende von `_post_process_safety_*` und `_post_process_flyability_*`
   in `engine/analyzers.py` (nach allen bestehenden Decisions).
5. Cache-Felder `safety_band`, `experience_score`, `experience_stars`,
   `comfort_index` zusaetzlich zu den bestehenden persistieren.
6. Tests: 8+ neue Tests in `tests/test_decision_engine.py`.
7. Doku: `docs/DECISIONS.md` neue Tabellenzeilen + `docs/RATING_CONCEPT.md`
   v1.2-Eintrag.
8. Frontend: Marker-Renderer in `static/js/map.js` (siehe Sektion 8.2),
   Spot-Panel-Hero (Sektion 8.6), Welcome-Banner (Sektion 8.7).
9. Chat-Engine: NICHT angefasst.

Ergebnis: User sieht neue Karte. Chat-Empfehlungen klingen gleich wie heute
(Bronze/Gruen/Violett). Es gibt einen Mini-Sprach-Bruch zwischen Karte
("amber/4 Sterne") und Chat ("Tag ist Gruen"), aber er ist in den meisten
Faellen aequivalent (amber+4 ≈ green) und durch das Welcome-Banner erklaerbar.

#### Phase 2 — Chat-Engine-Umstellung (Woche 3-4)

1. Neuer Skill `skills/shared/_safety_experience.md` ersetzt
   `_flyability_tiers.md`.
2. `skills/chat_capabilities_guide.md` Sections 1.3, 2.2, 4 umformulieren.
3. RECOMMENDED-Tag erweitern: `[RECOMMENDED: SpotName | safety=amber, stars=4]`.
4. `chat-charts.js`: Tag-Parser erweitern (rueckwaerts-kompatibel auf
   green/violet/gray).
5. Mail-Subscriber-Templates checken (`subscriber.py` und etwaige
   HTML-Templates) — falls vorhanden, parallel umstellen.

#### Phase 3 — Legacy aufraumen (Monat 2-3)

1. `flyability_tier`-Feld als deprecated markieren (Compat-View bleibt).
2. `_TIER_RATING_RANGES` und `_clamp_rating_to_tier` entfernen — `rating`
   wird aus `experience_score` linear abgeleitet.
3. `decide_flyability_upgrade` umbenannt in `compute_legacy_flyability_tier`,
   nur noch View-Funktion.
4. Tests bereinigen.

**Aufwand-Update v1.3 gegenueber Sektion 8.9**:
- Vorab-Fixes 2 + 1 + 3 + **4 (NEU)**: 4-5 Tage (Fix 4 ist der groesste, weil LLM-Prompt + neue Aggregation + Skill-Doku)
- Phase 1: 8-10 Tage (Decision-Engine, Cache-Output, Frontend-Glyphe, Welcome-Banner)
- Phase 2 (NEU v1.3): Regionen-Tab als Leaflet-Karte (siehe §4.3 v1.3) — 3-4 Tage
- Phase 3 (war 2): Chat-Engine-Umstellung — 3-4 Tage
- Phase 4 (war 3): Legacy aufraumen — 1-2 Tage
- **Gesamt: ~19-25 Tage** ueber 2-3 Kalendermonate (war 12-16, +Safety-Sub-Ratings + Regionen-Tab)

### 9.7 Empfehlung: Single Source of Truth

**Neue Default-Architektur (ab Phase 3)**:

Decision-Engine produziert **ausschliesslich**:
1. `safety_band` (`green` / `amber` / `red` / `neutral`)
2. `experience_score` (0-100)
3. `experience_stars` (1-5, abgeleitet aus experience_score via Schwellen)
4. `comfort_index` (0-100)
5. `_decisions_applied` (Tracking, unveraendert)
6. `caution_notes`, `no_go_reasons`, `primary_no_go` (Listen, unveraendert)
7. `foehn_risk` (unveraendert)

**Compat-View-Funktionen** (im Cache mit-persistiert, fuer Chat/Mail/Briefing):
- `flyability_tier`: berechnet aus (safety_band, experience_stars). Regel:
  `red → ""`, `experience_stars >= 4 AND safety_band == "green" → "violet"`,
  `experience_stars >= 2 → "green"`, sonst `"gray"`.
- `safety_status`: 1:1 abgeleitet aus safety_band (green→safe, amber→conditional,
  red→not_safe).
- `is_conditional`: `safety_band == "amber"`.
- `rating`: linear aus experience_score (z.B. `rating = experience_score / 10`),
  ggf. mit Saturation bei not_safe = 0.

**Pro Single Source of Truth**: Es ist klar, wer schreibt und wer liest.
Heute setzt LLM einige Felder, Decision-Engine ueberschreibt einige, andere
sind LLM-only (`is_conditional`!) — das ist die Quelle des Bruchs 3.

**Contra (ehrlich)**: Der Compat-Layer ist zusaetzlicher Code. Wenn die
Phase-2-Migration zu lange dauert (z.B. Mail-Templates sind manuell und
viele Subscriber haben Custom-Konfigurationen), bleibt der Compat-Layer
laenger als geplant. Das ist akzeptabel, solange er als View-Funktion
implementiert ist, nicht als doppelte Schreib-Logik.

**Klare Stellungnahme**: **Decision-Engine produziert kuenftig
safety_band + experience_stars + comfort_index als Source of Truth**;
flyability_tier, safety_status, is_conditional, rating sind abgeleitete
View-Werte. Damit ist das Konzept v1.1 harmonisch in das bestehende System
eingebettet — vorausgesetzt, die Brueche 1-5 in 9.4 werden vor der
Implementation aufgeloest.

---

## 10. Backlog (post-v1.0)

Features, die im urspruenglichen Konzept enthalten waren, aber nach Preview-Iteration v1.3 zurueckgestellt wurden. Hier dokumentiert, damit sie nicht verloren gehen.

### 10.1 Pilotenprofil-Filter (v1.5-Kandidat)

**Ursprung**: §2.2, §8.5 — Beginner / Intermediate / Advanced / Pro mit unterschiedlicher Saturierung/Filterung der Marker.

**Warum zurueckgestellt** (Entscheid 2026-04-30):
- Vereinfacht v1.0-Launch erheblich (kein Profil-State, kein Onboarding-Tooltip, keine localStorage-Persistenz, keine vier verschiedenen Render-Pfade)
- Vermeidet Pflicht-Anwaltsgespraech zu Profil-Disclaimer ("ich bin Advanced" als rechtsbindende Selbstdeklaration)
- Reduziert Test-Matrix (4 Profile × N Spots = viel Edge-Cases)
- Risiko-Mitigation in v1.0 erfolgt allein ueber `safety_band` (rot ist rot fuer alle)

**Voraussetzungen fuer Wieder-Einfuehrung** (alles separat zu klaeren):
1. Anwaltsgespraech: ist eine Advanced/Pro-Selbstdeklaration in CH haftungsrechtlich relevant?
2. User-Research: woher weiss System, dass der User ehrlich angibt? (vgl. offene Frage 6.5)
3. UX-Test: 5 User mit Mockup, ob sie das Profil bewusst setzen oder ignorieren

**Architektur-Hinweis**: v1.3-Implementierung baut so, dass Profil-Filter **rein im Frontend** als CSS-Saturierung + Sortier-Logik nachgeruestet werden kann. Backend-Werte (`safety_band`, `experience_score`) bleiben profil-unabhaengig — wie urspruenglich in §2.2 dokumentiert. Code-Aufwand fuer spaetere Wieder-Einfuehrung: ~1-2 Tage Frontend.

### 10.2 Pure-Rohdaten-Modus / Pro-Detail-Tab

**Ursprung**: §1.9 Synthese-Tabelle — FATMAP-Pattern (Rohdaten ohne Aggregation, "die Entscheidung gehoert dir").

**Status**: nicht prioritaer fuer v1.0. Spot-Panel hat bereits Meteogramm + Windverlauf + Caution-Notes. Ein zusaetzlicher "Pure Data"-Tab waere nice-to-have fuer Pro-User, aber kein Launch-Blocker.

### 10.3 Lernen aus Klick-Mustern

**Ursprung**: §"Offene Fragen" Punkt 4 — System erschliesst Pilotenprofil aus Verhalten statt User-Setting.

**Status**: setzt voraus, dass Profil-Filter wieder eingefuehrt wird (10.1) und dass es ein User-Account-System gibt, das Klick-Historie persistiert. Bestehende `account.html` deutet auf Account-System hin — vor Implementation: Telemetrie-Strategie kennen (vgl. `cost_telemetry.jsonl`).

---

## 11. Implementierungs-Status (Stand 2026-05-01)

Sektion ergänzt nach vollstaendiger Umsetzung der Phasen 1–4. Single Source of Truth fuer "was ist durch, was nicht".

### 11.1 Phasen-Uebersicht

| Phase | Inhalt | Status | Commits |
|-------|--------|--------|---------|
| Vorab-Fixes 1–4 | decide_flyability_downgrade-Split, is_conditional deterministisch, experience_score, Safety-Sub-Ratings | ✅ | siehe Memory |
| Phase 1 | UI-Switch + Decision-Engine-Erweiterung (compute_safety_band, compute_experience_score, compute_comfort_index, neue Cache-Felder, Marker-Glyphe, Spot-Panel-Hero) | ✅ | mehrere Commits |
| Phase 2 | Region-Tab als Leaflet-Karte mit Region-Overlay, 7-Tage-Sparkline, Top-Spots-Liste, Briefing-CTA | ✅ | `ccaf79a`, `d329c9b`, etc. |
| Phase 3 | Chat-Engine-Umstellung: Skill `_flyability_tiers.md` → `_safety_experience.md`, chat_capabilities_guide.md auf 2-Achsen-Sprache, RECOMMENDED-Tag-Parser akzeptiert `safety=…, stars=N`, Mail-Templates auf 2-Achsen | ✅ | `dfd1618` |
| Phase 4a | Legacy-Cleanup: `_TIER_RATING_RANGES` + `_clamp_rating_to_tier` aus _common.py entfernt, defensive Imports in 4 Files weg, neue View-Funktion `compute_legacy_flyability_tier` (§9.7) mit 11 Tests | ✅ | `2562920` |
| Phase 4b | Pipeline-Restructuring: View-Funktion in Pipeline aktiv, Tier-Schreibe aus allen `decide_flyability_*` raus (Cross-Cutting bleibt: mech_danger eskaliert Safety, upgrade korrigiert Text-Felder); User-Sprache "Rating 1–5" statt "Sterne" in Skill + Capabilities-Guide | ✅ | `87ae63b` |
| §4.4 | Risk-Reward-Bubble-Matrix im Briefing-Tab: regionen-aggregiert (29 Bubbles, X = Ø-experience_score, Y = safety_band-Bänder, Größe = Spot-Anzahl, Klick → springt zur Region) — `aggregateRegionsForBubbleMatrix` + `renderBubbleMatrix` in `static/js/briefing.js` | ✅ | UI-Refactor |

### 11.2 Nicht umgesetzt / Backlog (alles bewusst zurueckgestellt)

- **§10.1 Pilotenprofil-Filter** — DEFERRED, siehe §10.1.
- **§10.2 Pure-Rohdaten-Modus / Pro-Detail-Tab** — nicht prioritaer.
- **§10.3 Lernen aus Klick-Mustern** — setzt Account-System voraus.

### 11.3 Architektur nach Phase 4b (Single Source of Truth, §9.7)

```
LLM (Spot-/Region-Analyse)
  │
  │  produziert: 4 Flyability-Sub-Ratings + 5 Safety-Sub-Ratings
  │              + LLM-tier (Compat-Hilfe, wird ueberschrieben)
  │              + Caution-Notes / No-Go-Reasons / Recommendation-Texte
  ▼
Decision-Engine (deterministisch)
  │  - decide_flyability_low_reward / mech_danger / upgrade / region_gate
  │    → Tags, Safety-Eskalation, Text-Korrekturen
  │  - decide_aloft_*, decide_gust_floor, decide_overclaim_relax, _apply_foehn_decision
  │    → safety_status / no_go_reasons / caution_notes
  ▼
Compute-Funktionen (View-Layer)
  │  - _compute_rating_from_subratings → rating (0-10)
  │  - _compute_experience_score / _compute_experience_stars → 0-100 / 0-5 ("Rating")
  │  - _compute_safety_rating / _compute_safety_score → MIN-Aggregation 0-10 / 0-100
  │  - compute_safety_band → green/amber/red (Hybrid)
  │  - compute_comfort_index → 0-100 (Texture)
  │  - compute_legacy_flyability_tier → gray/green/violet/'' (abgeleitet)
  ▼
Cache (spot_analyses.json / region_analyses.json)
  │
  ▼
Frontend (Karten-Glyphe + Spot-Panel + Region-Tab + Briefing + Chat)
```

**Eintrittspunkt fuer Aenderungen**: Sub-Ratings (LLM) bzw. Decisions (Engine).
Tier ist abgeleitet, nicht selbst-entschieden — eine Aenderung am Tier muss
ueber die zugrundeliegenden Achsen (safety_band, experience_stars) erfolgen.

---

## Quellen

- [Burnair Meteoservice](https://www.burnair.ch/meteoservice/)
- [Burnair Help Center – Wolkenprognose Farben](https://help.burnair.cloud/hc/de/articles/360018676938-Was-bedeuten-die-Farben-in-der-Wolkenprognose)
- [Paraglidable.com](https://paraglidable.com/)
- [GitHub AntoineMeler/Paraglidable](https://github.com/AntoineMeler/Paraglidable)
- [SLF Avalanche Bulletin – Danger Levels](https://www.slf.ch/en/avalanche-bulletin-and-snow-situation/about-the-avalanche-bulletin/danger-levels/)
- [SLF News – Subdivision of Danger Levels](https://www.slf.ch/en/news/subdivision-of-danger-levels-in-the-avalanche-bulletin/)
- [Skitourenguru Rating View](https://www.skitourenguru.ch/rating-view)
- [Bluewin – Skitourenguru hilft sichere Routen waehlen](https://www.bluewin.ch/en/news/skitourenguru-tool-helps-to-choose-safe-ski-touring-routes-3069477.html)
- [Magicseaweed – Star Rating Documentation](https://magicseaweed.com/docs/forecasting/66/star-rating/10134/)
- [Surfline – Surf Ratings & Colors](https://support.surfline.com/hc/en-us/articles/36277684017819-Surf-Ratings-Colors)
- [Wikipedia – Grade (climbing)](https://en.wikipedia.org/wiki/Grade_(climbing))
- [BMC – UK Traditional Climbing Grades](https://www.thebmc.co.uk/en/a-brief-explanation-of-uk-traditional-climbing-grades)
- [UKC – Extending the UK Grading System](https://www.ukclimbing.com/articles/features/extending_the_uk_grading_system-3068)
- [FATMAP – Avalanche Tool / Terrain Layer](https://fatmap.zendesk.com/hc/en-us/articles/115001419425-Avalanche-Tool-Terrain-Layer-)
- [Windy.app – How to read surf forecast](https://windy.app/blog/how-to-read-a-surf-forecast.html)
- [The Surf Tribe – Why star rating isn't enough](https://www.thesurftribe.com/surf-blog/how-to-read-a-surf-forecast-and-why-the-star-rating-isnt-enough)
