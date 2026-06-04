# Plan — TORN (Scherung zerreißt Thermik) wirkt auf die Fliegbarkeit

**Status:** Untersuchung abgeschlossen, Lösung geschwenkt. Band-Cap-Modell **verworfen**
zugunsten einer **simplen Binär-Regel**. Bau noch nicht gestartet.
**Erstellt:** 2026-05-23 · **Neu gefasst:** 2026-06-03 · **Geschwenkt:** 2026-06-04
**Branch:** `main` (Single-Branch-Workflow)

---

## Kurzfassung (TL;DR)

Heute beeinflusst das `[THERMAL-TORN-UNUSABLE]`-Tag (Wind zerreißt die Thermik in
der Höhe) das Rating **nicht** — es ist nur Prosa. Es **soll** eine Stunde, in der
die Thermik tief zerrissen ist, nicht mehr als „produktive Flugstunde" zählen.

Das ursprünglich geplante **Band-Cap-Modell** (ausrechnen, bis zu welcher Höhe die
Thermik noch nutzbar ist) ist **verworfen** — die Untersuchung zeigte, dass es
praktisch dasselbe Ergebnis liefert wie eine **simple Binär-Regel**, bei viel mehr
Aufwand. Der eigentliche Gewinn liegt woanders: im **10m-Anker-Fix** (entfernt 43 %
Fehlalarm an der Wurzel).

**Neue Lösung in drei Schritten:**
1. **10m-Anker-Fix** — den reibungsverfälschten Bodenwind aus der SHEAR/TORN-Rechnung
   nehmen (Start/WIND/ROUGH behalten ihn). Vorbedingung & größter Einzelgewinn.
2. **Binär-Regel** — anker-korrigiertes, tiefes, echtes TORN-PL → Stunde nicht
   produktiv (genau wie ROUGH/WIND es schon machen).
3. **Prosa-Pflicht** — das LLM muss die zerreißende Scherung in der Flyability-Prosa
   **erwähnen** (Thermik-Qualität ist Flyability-Domäne, anders als Regen).

---

## Was die Untersuchung ergeben hat (2026-06-03/04)

Drei Debug-Läufe über den echten Engine-Pfad (`debug_scripts/test_torn_*.py`,
Capture-Hook auf `_thermal_quality_tags`, Live-Cache: 495 Spots × 5 Tage):

### Befund 1 — 43 % des Roh-TORN ist ein 10m-Anker-Artefakt (`test_torn_cap_position.py`)
Die Scherungs-Treppe verankert ihren untersten Punkt am Startplatz mit dem
**10m-Bodenwind** (roh von Open-Meteo). Dieser Wind ist von der **Bodenreibung
gebremst** → der Sprung zum freien Höhenwind sieht aus wie starke Scherung, ist aber
reine Reibung. **43 %** aller TORN-Meldungen stammen aus genau diesem einen Segment.

### Befund 2 — das echte (PL-only) TORN ist selten und sitzt sehr tief
Nach Abzug des Ankers: echtes TORN nur **~1 %** der Thermikstunden, **10 %** bei
Höhenwind ≥30 km/h, **19 %** bei ≥40 km/h. Es sitzt **sehr tief** (Median rel-Höhe
0.12–0.15, fast nie im oberen Drittel). → Unter dem Riss bleibt fast nie genug Band
für `min_band_depth` übrig. Der Band-Cap würde die Stunde also **killen statt senken**
= dasselbe wie eine Binär-Regel. **Darum Band-Cap auf HOLD.**

### Befund 3 — das tiefe TORN ist ECHT, kein Climb-Artefakt (`test_torn_shear_vs_climb.py`, 83 Fälle)
Verdacht war: Die parabolische Steigrate ist am Säulenboden klein → B/S klein →
falsches TORN. Ergebnis eindeutig: **100 % shear-getrieben, 0 % Climb-Artefakt.**
- 86 % SHEAR-ECHT (`du_dz` ≥ danger, Median 4.37 vs. Schwelle 3.0), 14 % SHEAR-WARN.
- Der `CLIMB_FLOOR` (0.3) wird **nie** ausgelöst (0 % gefloored; bei rel 0.15 ist die
  Steigrate noch ~1.7 m/s).
- **90 % zerreißen sogar den Säulen-Peak-Kern** (`peak_climb/du_dz·100 ≤ 60`) — der
  härteste Echtheits-Test. → Das tiefe TORN ist **vertrauenswürdig**. Eine
  `CLIMB_FLOOR`/B/S-Boden-Sanierung als Vorbedingung ist **nicht** nötig.

### Befund 4 — der Volumen-Impact ist klein und treffsicher (`test_torn_spot_impact.py`)
Über alle 6637 Thermikstunden:
- Regel greift bei **83 Std = 1,3 %** aller Thermikstunden.
- Betroffen sind **39 von 495 Spots = 8 %**; **92 % der Spots merken nichts.**
- Median-Wegfall bei betroffenen Spots: **9 % ihrer Stunden** (~1 Stunde/Tag).
- **0 Spots** verlieren einen ganzen Flugtag.
- Die betroffenen Spots sind **exponierte Jura-Kämme** (Hasenmatt, Grenchenberg,
  Chasseral, Boezingenberg …) — physikalisch genau dort, wo Stark-Wind die Thermik
  zerreißt. Kein wahlloser Flächenbrand → starkes Zeichen, dass das Signal echt ist.

> **Caveat:** Die 5 Tage sind *eine* Wetterlage (eher windig). Föhntag → mehr Fälle
> (aber dann real & richtig), Schwachwind-Lage → 0 Fälle. Vor dem Scharfschalten über
> mehr Wetterlagen gegentesten.

---

## Lösung Schritt 1 — 10m-Anker-Fix (Vorbedingung, größter Gewinn)

**File:** `engine/weather_context.py`, `_calculate_segment_shear` (L866).

Der Surface-Anker `(elevation_m, wind_speed_10m)` (L887) darf für die **SHEAR/TORN**-
Auswertung **nicht** mitgeführt werden — sonst kappt reine Reibungs-Scherung
fälschlich am Boden (Befund 1). Die unterste *gewertete* Stufe liegt dann erst
zwischen zwei Druckflächen.

```
HEUTE — mit 10m-Anker (erzeugt 43 % Schein-TORN)

  1900 m ── 800 hPa   22 km/h ──┐
  1500 m ── 850 hPa   24 km/h ──┤  ← echte Höhenwinde (frei, ungebremst)
  ┄┄┄┄┄┄ Reibungsschicht ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄
  1010 m ── 10m-Wind    9 km/h ──┘  ◄── ANKER (von Bodenreibung gebremst)
  1000 m ── Start ───────────────────
            └─ Segment 10m→850 hPa: Sprung 9→24 km/h ⇒ Schein-Scherung
               ⇒ falsches TORN-UNU direkt über dem Start            ✖

FIX — Anker nur für TORN/SHEAR weglassen

  1900 m ── 800 hPa   22 km/h ──┐
  1500 m ── 850 hPa   24 km/h ──┘  ◄── unterste GEWERTETE Stufe (frei ↔ frei)
  ┄┄┄┄┄┄ Reibungsschicht ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄
  1010 m ── 10m-Wind    9 km/h       bleibt für Start · WIND · ROUGH
  1000 m ── Start ───────────────────
            └─ TORN wird erst zwischen zwei Höhenwinden bewertet
               ⇒ kein Reibungs-Artefakt, nur echte Scherung zählt   ✓
```

**Wichtig — chirurgisch, nicht global:**
- **Nur** SHEAR/TORN verlieren den Anker.
- **ROUGH** (Böigkeit), **WIND** (BL-Mittelwind) und **Startbarkeit** behalten den
  10m-Wind unverändert — sie *wollen* den echten Bodenwind. Die bodennahe Ruppigkeit
  ist über die **Böen (ROUGH)** ohnehin schon abgedeckt; sie ein zweites Mal als
  Höhen-Scherung zu zählen wäre Doppelzählung.

**Umsetzung:** Flag oder separater Aufruf von `_calculate_segment_shear`, der den
ersten Punkt (Surface-Anker) für die TORN-Segmente weglässt. `_calculate_bl_mean_wind`
und `_calculate_gust_factor` bleiben unangetastet.

**Trade-off (akzeptiert):** Eine echte *gerichtete* Scherschicht direkt über dem Start
wird ggf. erst ab der ersten Druckfläche erkannt — selten, im Plan bewusst akzeptiert.
(Böen sagen „ruppig", aber nicht „Richtungsdrehung mit der Höhe".)

**Sofort-Nutzen unabhängig vom Rating:** verbessert schon heute das Prosa-TORN-Tag
(43 % weniger Fehlalarm).

**Verify:** `test_torn_cap_position.py` re-runnen → Anteil Anker-TORN fällt auf 0;
PL-only-TORN bleibt unverändert.

---

## Lösung Schritt 2 — Binär-Regel auf das anker-korrigierte TORN

**File:** `engine/weather_context.py` — die Produktiv-Zähler + Fliegbarkeits-Timeline,
analog zum bestehenden ROUGH/WIND-Gate.

**Regel:** Hat die Stunde tief in der Säule ein echtes (PL-only, anker-korrigiertes)
`TORN-UNU`-Segment → Stunde zählt **nicht** als produktiv (`productive_thermal_h`,
`productive_h_strict`, `strong_h`) und erscheint in der Timeline nicht als `produktiv`.
Genau der Mechanismus, den ROUGH-UNUSABLE / WIND-UNUSABLE schon nutzen — **kein neues
Konzept, kein deterministischer Tier-Override.**

**Optionale Sicherung (Peak-Kern-Verschärfung):** Nur gaten, wenn der Riss auch den
**Säulen-Peak-Kern** zerreißt (`peak_climb/du_dz·100 ≤ 60`). Das siebt die ~10 %
Grenzfälle aus, bei denen die lokal schwache Steigrate mitspielt (Befund 3), und macht
die Regel komplett unabhängig von der parabolischen Boden-Steigrate. Empfehlung: zuerst
ohne, beim Replay entscheiden, ob nötig.

**Arbeitsteilung Code ↔ LLM unverändert:** Code gated deterministisch
(`productive_thermal_h` sinkt), LLM erzählt nur ehrlich, **straft nicht nochmal**
(keine Doppelbestrafung — das war die alte Wack-a-Mole-Falle).

**Verify:**
- Vignette: tiefes echtes TORN → Stunde fällt aus den Produktiv-Zählern.
- Vignette: TORN nur hoch oben / nur SHEAR ohne TORN → bleibt produktiv.
- `tests/test_decision_engine.py` (32 Tests) grün halten; geänderte Erwartungswerte
  bewusst updaten + im Kommentar begründen.
- Replay über mehr Wetterlagen (Caveat Befund 4).

---

## Lösung Schritt 3 — LLM MUSS die Scherung in der Prosa erwähnen

**File:** `engine/weather_context.py` — der LLM-Kontext-Block `→ THERMIK-QUALITÄT`
(Spot ~L2370–2412, Region spiegelbildlich).

**Anforderung (User 2026-06-04):** Wenn Scherung auftritt, die die Thermik zerreißt
(oder zu zerreißen droht), soll das LLM das **aktiv ansprechen** — nicht nur den
Produktiv-Zähler still senken. Das ist **legitime Flyability-Prosa** (Thermik-Qualität),
**im Gegensatz zu Regen/Gewitter**, das NICHT in die Flyability-Prosa darf (Safety-Domäne,
siehe `[[niederschlag-flyability-plan]]`). Scherung/Zerreißen gehört genau in
`thermal_quality` / `flyability_notes`.

**Zwei Änderungen am bestehenden Hinweis-Block (L2407–2412):**
1. **Alten Text korrigieren.** Heute steht dort: *„TORN-/SHEAR-UNUSABLE sind reine
   Qualitäts-Issues … degradieren MAXIMAL violet→green … Der Tag bleibt tauglich."* Das
   widerspricht der neuen Binär-Regel. Neu: tiefes TORN **senkt die Produktiv-Stunden**
   (wie WIND-UNUSABLE), und die ehrliche `productive_thermal_h` trägt die Strafe — das
   LLM erzählt, straft aber nicht zusätzlich am Tier.
2. **Prosa-Pflicht ergänzen.** Klartext-Anweisung: *„Erwähne in der Flyability-Prosa,
   dass die Scherung die Thermik in N Stunden zerreißt/zu zerreißen droht (Bart schwer
   bis nicht zentrierbar). Benenne es konkret — nicht verschweigen."* Gilt für
   TORN-UNUSABLE (zerreißt) **und** spürbares TORN-/SHEAR-DEGRADED (droht zu zerreißen,
   „könnte die Thermik zerstören").

**Arbeitsteilung bleibt:** Strafe = via gesenkter `productive_thermal_h` (Schritt 2),
Prosa = ehrliche Benennung (Schritt 3). Keine Doppelbestrafung am Tier.

**Verify:**
- Vignette mit tiefem TORN → die Flyability-Prosa (`thermal_quality`/`flyability_notes`)
  benennt die Scherung explizit.
- Gegenprobe: Regen-Stunde → Scherungs-Prosa erscheint, aber **kein** Regen in der
  Flyability-Prosa (Domänen-Trennung gewahrt).
- DeepSeek V4 Flash folgt Prompt-Regeln zuverlässig, gpt-4o-mini nicht (Memory
  `[[region-safety-cap]]`) — bei Modellwechsel re-validieren.

---

## Meteo-Fundierung (Web-Recherche 2026-06-03, weiterhin gültig)

Die Schwellen der einzelnen Mechanismen sind belegt und bleiben unverändert:

| Mechanismus | Was es physikalisch ist | Schwelle | Quelle |
|---|---|---|---|
| **SHEAR** | Wind ändert sich mit Höhe → kippt/verbiegt Blase | `dU/dz` ≥ 2 km/h/100 m | meteoblue |
| **TORN** | Scherung gewinnt gegen Auftrieb → Kern zerfällt | `B/S` ≤ Schwelle | Glendening/RASP |
| **ROUGH** | Mechanische Turbulenz/Böigkeit frisst Blase von außen | Böenfaktor `GF` ≥ ½ | Whiteman, Stull |
| **WIND** | Starker Grundwind → Blase löst sich nicht ab | BL-Mittelwind ≥ Zone-Schwelle | DHV, Whiteman |

**Kern-Befund:** Scherung deckelt die Thermik in einer Höhe; ob man durchsteigt, hängt
von der Thermik-Stärke ab — *„strong thermals can remain fairly well organized …; weak
thermals are ripped to shreds"* (FAA). **Genau das misst B/S** (Auftrieb ÷ Scherung).

Quellen: Glendening/RASP (B/S), meteoblue (2 km/h/100 m), FAA Glider Handbook Ch. 9,
Soaring Skyways, XC Skies. Intern: `meteo_research/wind_shear_thermal_quality.md`.

---

## Mechanismus-Glossar (4 unabhängige Effekte — die Trennung trägt die Lösung)

| Tag | Maß | Wirkung im Rating | Bodenwind? |
|---|---|---|---|
| **ROUGH** | `GF` = mechan. Böen ÷ Steigwert | blockt produktiv + `rough_pct>50%`→conditional | **ja** (Böen) |
| **SHEAR** | `dU/dz` absolut | nur LLM-Prosa/Komfort, deckelt nichts | **nein** (Anker raus) |
| **TORN** | `B/S` = Steigwert ÷ Scherung | **Binär-Gate** (Stunde nicht produktiv) | **nein** (Anker raus) |
| **WIND** | BL-Mittelwind | Boden-Gate (Stunde nicht produktiv) | **ja** |

- **SHEAR und TORN nicht doppelt zählen** — beide kommen aus `dU/dz`. TORN (B/S)
  enthält den Scher-Effekt schon relativ zur Thermik-Stärke. → TORN gated, SHEAR Prosa.
- **Datenherkunft:** `wind_speed_10m` ist ein **roher Open-Meteo-Wert** (CH-Surface-
  Params), nichts von uns Gerechnetes; die Reibungsbremsung steckt im Modell selbst.
  Auf Region-Ebene Median über die Referenzpunkte, sonst spot-roh.

---

## Bewusst NICHT (mehr) im Plan

- ❌ **Band-Cap-Modell** (`usable_top_m`, gekapptes Band gegen `min_band_depth`) —
  verworfen, siehe Anhang. Liefert dasselbe wie die Binär-Regel, bei mehr Aufwand.
- ❌ 66 %-Segment-Schwelle / 150 m-Durchstieg-Toleranz (schon früher gestrichen).
- ❌ SHEAR als Sperre (würde `dU/dz` doppelt zählen → nur Prosa).
- ❌ Deterministischer Rating-/Tier-Cap (Rating setzt das LLM; Wirkung nur via Inputs).
- ❌ LLM-Dämpfungsregel „−1 Stufe pro Mechanismus" (Doppelbestrafung).
- ❌ `CLIMB_FLOOR`/B/S-Boden-Sanierung als Vorbedingung (Befund 3: nicht nötig).
- ❌ Display-Höhe überschreiben (rohe Physik bleibt sichtbar).

---

## Reihenfolge

1. **Schritt 1 — 10m-Anker-Fix** (`_calculate_segment_shear`), `test_torn_cap_position.py`
   verifizieren.
2. **Schritt 2 — Binär-Regel** an den Produktiv-Zählern + Timeline; Tests grün.
3. **Schritt 3 — LLM-Hinweis korrigieren + Prosa-Pflicht** (alten „reine Qualitäts-Issue"-
   Text ersetzen, Scherung aktiv benennen lassen).
4. **Replay über mehr Wetterlagen** (Föhn + Schwachwind) → ggf. Peak-Kern-Verschärfung.
5. Doku/Tests synchronisieren (Sync-Pflicht).

---

## Sync-Pflicht

- `docs/RATING_ARCHITECTURE.md` — TORN als deterministisches Produktiv-Gate (wie ROUGH/WIND).
- `docs/DECISIONS.md` — Band-Cap verworfen + Begründung; Anker-Fix; Binär-Regel.
- `docs/TAGS.md` — TORN-Wirkung aktualisieren; Anker-Sonderbehandlung dokumentieren.
- `memory/` — `[[tq-band-cap-plan]]` ist aktuell (Befunde drin).
- `score_regression.py` — falls neue Cache-Felder, Reverse-Parser ergänzen.

---

## Anhang — VERWORFEN: Band-Cap-Modell (Herleitung, für Nachvollziehbarkeit)

Die ursprüngliche Idee: nicht binär killen, sondern das **nutzbare Band** rechnen —
saubere Höhe von unten bis zur ersten Zerreiß-Decke (`usable_top_m` = `alt_lo` des
tiefsten `TORN-UNU`-Segments), verglichen gegen die kalibrierte `min_band_depth`. TORN
hätte die erreichbare Höhe **gedeckelt** statt die Stunde komplett zu streichen.

```
2400 m ── Top ──            │ ▓ clean, aber UNERREICHBAR ▓ │
1300 m ── TORN-UNU = Decke ─┼──────────────────────────────┼
                            │ ░ nutzbares Band = 300 m ░    │
1000 m ── Start ────────────┴──────────────────────────────┘
```

**Warum verworfen (Befund 2):** Das echte TORN sitzt bei rel ~0.12–0.15 — so tief, dass
unter der Decke fast nie `≥ min_band_depth` übrig bleibt. Der Cap killt die Stunde in der
Praxis ohnehin → identisch zur Binär-Regel, nur mit deutlich mehr Code (4 Touch-Points,
`usable_top_m`-Felder, Cap-Aggregate, Reverse-Parser, LLM-Cap-Prosa). Bei viel mehr
Aufwand und Risiko derselbe Effekt. Falls echte Vignetten später ein *abgestuftes*
Verhalten beweisen (TORN hoch oben, das die Höhe nur senkt), kann der Cap reaktiviert
werden — bis dahin reicht die Binär-Regel.
