# Plan: Niederschlag/Gewitter wirkt auf Fliegbarkeit (nicht nur Sicherheit)

**Status:** Planung abgeschlossen + zweimal revidiert (kritische Runde 2026-06-03, Deep-Research
2026-06-04). Implementierung NICHT gestartet.
**Erstellt:** 2026-06-03 — **Schwelle final entschieden:** 2026-06-04
**Branch:** `main` (Single-Branch-Workflow)

**Wiederaufnahme (HIER starten):**
1. Diese Datei lesen — alle Konzept-Entscheidungen sind getroffen (siehe „Entscheidungen").
2. Direkt mit Phase 1 (Spot-Schleife) beginnen. Reihenfolge: Spot → Region → Doku → Validierung.
3. Schwelle ist entschieden: `PRECIP_UNFLYABLE_MM` = **0.5** (einheitlich Spot + Region).
   Begründung siehe „Schwellen-Entscheidung (Deep-Research 2026-06-04)" unten — NICHT neu
   aufrollen. Im Replay (Phase 4) nur noch verifizieren, nicht den Wert suchen.

**Kurz-Summary der finalen Lösung:**
Produktiv-Zähler (`productive_thermal_h`, `productive_h_strict`, `strong_h`) + FLIEGBARKEITS-VERLAUF
in beiden Schleifen gaten mit `weather_unflyable = [THUNDERSTORM] OR precip >= 0.5 mm/h`.
KEIN CAPE-DANGER, KEIN Wind. Safety bleibt komplett unverändert. **Der Gate ist NICHT still**
(User-Vorgabe 2026-06-04): ausgeschlossene Stunden werden dem LLM sichtbar gemacht (Hint
`WETTER-GATE: Nh …` + Timeline-Label `nicht-fliegbar(Regen/Gewitter)`) und der Skill erlaubt dem
LLM, Regen/Gewitter als Fliegbarkeits-Grund zu benennen, wenn er eine Stunde unfliegbar macht.

---

## Schwellen-Entscheidung (Deep-Research 2026-06-04) — überschreibt frühere 2.5

**Frage:** „Kann eine Regenwolke nutzbare Thermik drunter haben — und bis zu welcher
Regenmenge?" Breit recherchiert (19 Quellen, 18/25 Claims adversarial bestätigt; Memory
`rain-thermals-research`, FAA Glider Handbook Ch.9, NWS spotterguide, AMS Glossary).

**Mechanistische Befunde:**
- **Steigen koexistiert mit Regen — aber NUR am versetzten Wolkenbasis-Inflow (cloud suck),
  NICHT unter dem Regenschacht.** Der Aufwind, der die Wolke speist, sitzt seitlich/vor dem
  Regen (Sonnenseite). Unter dem aktiven Schauer: Abwind (precip-drag + evaporative Kühlung →
  Cold Pool / Outflow / Gust Front). → Das erklärt die User-Beobachtung „Regen + Thermik
  gleichzeitig": das Steigen ist *neben* dem Regen, nicht dort wo gemessen wird.
- **Dieser Inflow ist in der Literatur primär als GEFAHR dokumentiert** (zieht Schirme in die
  Wolke = cloud suck), nicht als freundliche Arbeitsthermik.
- **Es gibt KEINEN belastbaren mm/h-Schwellwert** für den Steig-Kollaps. Der „ab ~2 mm/h"-Claim
  wurde adversarial gekillt (1-2). Der Übergang ist **stadien-basiert** (entwickelnd = nur
  Aufwind / kein Bodenregen → reif = getrennte Auf-/Abwind-Säulen, Bodenregen markiert
  Abwind-Beginn → zerfallend = abwind-dominiert), nicht mengenbasiert.
- **Regenrate ist ein schlechter Abwind-Proxy:** trockene Microbursts/Virga geben starken
  Abwind bei wenig Bodenregen. (Diesen Fall fängt der Gate prinzipbedingt nicht — Safety-seitig
  über CAPE/Gewitter teils abgedeckt, akzeptierter Trade-off.)

**Folgerung:** Das verlässliche Signal ist **„erreicht Regen den Boden am Spot"** (≈ binär),
nicht die Menge. Die alte 2.5 (WMO „Moderate shower = Flugabbruch") war eine **Safety/Abbruch-
Grenze ohne mechanistische Basis als Steig-Kollaps-Punkt** und ließe genau die leichten
Schauer (0.5–2.5) als „produktiv" durch, in denen der Spot schon im Abwind sein kann.

**Entscheidung (User 2026-06-04):** `PRECIP_UNFLYABLE_MM = 0.5` mm/h (DWD light-shower = echter
Schauer vs. Niesel/Rauschen), **einheitlich** für Spot und Region.
- *Spot-`precipitation`* = Regen AM Spot → 0.5 trifft „echter Regen auf diesen Punkt" sauber.
- *Region-`precipitation`* = Hybrid-gefilterter **Peak über die RPs** → ein einzelner nasser RP
  könnte hier gaten, obwohl daneben (versetzter Inflow) real gestiegen wird. Bewusst trotzdem
  einheitlich 0.5 gewählt (Simplizität, eine Konstante); im Replay beobachten, ob Region dadurch
  zu aggressiv degradiert — falls ja, später Coverage-Bedingung oder höherer Region-Wert.

---

## Ziel in einem Satz

Eine Stunde, in der es **regnet oder gewittert**, ist keine fliegbare Stunde — sie darf
nicht mehr als „produktive Thermik-Stunde" gezählt werden und damit das Flyability-Tier
(`gray`/`green`/`violet`) künstlich aufblähen.

## Hintergrund / Motivation

**User-Beobachtung 2026-06-03:** Niederschlag beeinflusst aktuell **nur** die Sicherheit
(`safety_status`), aber nicht die Fliegbarkeit. In einer Regenstunde kann man physisch
nicht in der Luft sein — die Stunde sollte also auch flyability-seitig nicht als nutzbar gelten.

**Code-Befund (`engine/weather_context.py`):**

Es gibt zwei orthogonale Achsen:
- **Safety** (`safety_status`): Wind/Böen/**Regen/Gewitter**/CAPE → `[RAIN-WARN]`,
  `[THUNDERSTORM]`, `NIEDERSCHLAG-TREND`, `GEWITTER-TREND`, `SICHERHEITS-VERLAUF`. ✅ funktioniert.
- **Flyability** (`fly_status`/Tier): Thermik-Reward → Kernmetrik `productive_thermal_h`.

`productive_thermal_h` (und die Schwester-Zähler `productive_h_strict`, `strong_h`) zählen eine
Stunde als produktiv, wenn:
- `h_climb >= PRODUCTIVE_CLIMB_MIN` (0.7 m/s),
- kein `THERMAL-ROUGH-UNUSABLE` / `THERMAL-WIND-UNUSABLE`,
- ausreichendes Höhenband (`min_band_depth`).

→ **Niederschlag/Gewitter ist KEIN Gate.** Eine Regenstunde mit berechnetem Climb (Gewitter
haben hohen Climb!) zählt heute voll als „produktive Flyability-Stunde". Das ist der Bug.

**Wie das Tier heute entsteht (wichtig — Doku teils veraltet):**
Laut `engine/decision_engine.py:509-513` (RATING_CONCEPT v1.5) gibt es **keinen
deterministischen Tier-Override mehr** (kein gray→green Upgrade / green→gray Downgrade im Code).
Das **LLM setzt das Tier direkt**, gefüttert durch:
- den Hint `→ PRODUKTIVE-THERMIK: Nh` (`weather_context.py:2433` Spot / `:3484` Region),
- `→ RATING-INPUTS: prod_h_strict=…, strong_h=…`,
- die stündlichen `hour_lines` (zeigen Regen bereits via `[RAIN-WARN]` + precip-Suffix),
- den `FLIEGBARKEITS-VERLAUF` (per-Stunde `is_productive` → Klasse `produktiv`).

⇒ Der wirksame Hebel ist die **Zähler-/Timeline-Quelle**: Wenn `productive_thermal_h` Regenstunden
ausschließt, sieht das LLM eine ehrliche Zahl und wählt seltener fälschlich `green`/`violet`.

**Design-Leitplanke — REVIDIERT 2026-06-04 (User-Vorgabe):**
Frühere Annahme war ein rein *stiller* Gate (Regen taucht nie in der Flyability-Prosa auf, weil
Safety-Domäne; `skills/shared/04_flyability/04_flight_subratings_*.md:17`). **Das ist jetzt
überholt:** Wenn der Regen/Gewitter-Gate dazu führt, dass eine Stunde nicht (mehr) fliegbar ist,
**muss das LLM das in seiner Analyse berücksichtigen und benennen können** — z.B. „die Thermik
wäre tragfähig, aber Regen zwischen 13–15 Uhr macht diese Stunden unfliegbar → effektiv nur 3
nutzbare Stunden". Sonst sinkt nur die Zahl, ohne dass die Begründung konsistent ist.

Wichtige Abgrenzung (löst den Konflikt mit der alten Leitplanke auf):
- **Erlaubt/erwünscht:** Regen/Gewitter als *Fliegbarkeits*-Grund nennen, wenn er der Auslöser ist,
  warum eine Stunde nicht produktiv/fliegbar ist („in der Luft kann man bei Regen nicht steigen").
- **Weiterhin vermeiden:** Regen als reine *Safety*-Warnung in der Flyability-Prosa doppeln
  (Böen/Gefahr/„Schirm nass" — das bleibt Safety-Domäne).

Konsequenz für die Umsetzung: Der Gate darf **nicht still** sein. Das LLM braucht ein klares,
maschinenlesbares Signal, (a) **dass** Stunden wegen Wetter ausgeschlossen wurden, (b) **welche**
und (c) **warum** (Regen vs. Gewitter) — siehe Touch-Points (Hint + Timeline-Label) und D3/D4 unten.

---

## Kern-Idee — bestehendes Konzept wiederverwenden (kein neues Flag)

**Analyse-Ergebnis (2026-06-03):** Das System hat bereits ein etabliertes „diese Stunde ist nicht
fliegbar"-Konzept — die **harten Danger-Tag-Sets**. Sie treiben das **Tagesfenster**:
„fliegbares Fenster = zusammenhängende saubere Stunden = WIND-OK + kein DANGER-Tag"
(`skills/shared/02_tagesfenster/01_tagesfenster.md`). `[RAIN-WARN]` und `[THUNDERSTORM]` sind
**bereits Mitglieder** dieses Sets und zerschneiden das Fenster schon heute (Skill-Beispiel Fall 2).
Wir übernehmen die *Idee* (Wetter macht eine Stunde nicht-fliegbar), verfeinern aber den
Regen-Trigger zu einer Mengen-Schwelle (siehe unten) statt das Safety-Binär 1:1 zu erben.

Verifiziert — dieselbe Tag-Menge ist im Code an **fünf** Stellen dupliziert:
`hard_warnings_set` (Z.775, Clean-Anker), `safety_hard_tags` (Z.1934, Spot-SICHERHEITS-VERLAUF),
`hard_warnings` (Z.2059, Spot-Fenster-Slicing), `safety_hard_r` (Z.3116, Region-SICHERHEITS-VERLAUF),
`hard_warnings` (Z.3208, Region-Fenster-Slicing).

**Der Bug ist eine Inkonsistenz, kein fehlendes Konzept:** `productive_thermal_h` und der
FLIEGBARKEITS-VERLAUF werden *unabhängig* vom Tagesfenster über *alle* Flugstunden berechnet
(`weather_context.py:1542-1556` iteriert alle `FLIGHT_HOURS`). Sie kreditieren damit Stunden, die
dasselbe System bereits als nicht-fliegbar (Fenster-Lücke) deklariert hat.

→ **Wir erfinden KEIN `precip_blocks_flight`** und erben **NICHT** das binäre `[RAIN-WARN]`
(`precip > 0`, Safety-konservativ). Stattdessen: Gewitter immer, Regen erst ab einer
**flugtechnischen Mengen-Schwelle** (Revision nach Kritik 2026-06-03):

```python
# config.py — neue Konstante (Wert revidiert 2.5 → 0.5 nach Deep-Research, s.o.)
PRECIP_UNFLYABLE_MM = 0.5   # mm/h — "echter Regen erreicht den Boden am Spot". KEIN belastbarer
                            # mm/h-Steig-Kollaps-Wert existiert; Signal ist binaer-artig
                            # (Regen am Boden = reife/zerfallende Abwind-Phase lokal). 0.5 =
                            # DWD light-shower (echter Schauer vs. Niesel/Rauschen). Nutzbares
                            # Steigen sitzt am versetzten Inflow NEBEN dem Regen — nicht dort wo
                            # precip gemessen wird. Quelle: memory rain-thermals-research.

# weather_context.py — in beiden Schleifen, precip ist lokal vorhanden
weather_unflyable = (
    "[THUNDERSTORM]" in warnings
    or (isinstance(precip, (int, float)) and precip >= config.PRECIP_UNFLYABLE_MM)
)
```

und hängen `and not weather_unflyable` an die Produktiv-Bedingungen + die Timeline-Klassifikation.

> **Warum 0.5 mm/h (revidiert von 2.5):** Siehe „Schwellen-Entscheidung (Deep-Research 2026-06-04)"
> oben. Kurz: es gibt keinen mechanistisch fundierten mm/h-Steig-Kollaps-Punkt; das verlässliche
> Signal ist „Regen erreicht den Boden am Spot" (≈ binär). 0.5 liegt knapp über dem Rausch-Floor
> (echter Schauer, kein Niesel). Die frühere 2.5 war eine umgedeutete Safety/Abbruch-Grenze und
> ließe leichte Schauer (0.5–2.5) fälschlich als produktiv durch, obwohl der Spot unter so einem
> Schacht schon im Abwind sein kann. Der „Regen-Sandwich"-Schutz (aufgelockerter Tag bleibt green)
> kommt vom **Per-Stunde-Gate**, NICHT von der Höhe der Schwelle — trockene Stunden (precip≈0)
> bleiben unabhängig vom Wert produktiv. Safety bleibt unberührt — `[RAIN-WARN]`/
> `NIEDERSCHLAG-TREND` feuern weiter ab `precip > 0`.
>
> **CAPE-DANGER bewusst NICHT im Gate** (Revision nach Kritik). CAPE-DANGER =
> `cape > 1500 J/kg` ODER (`cape > 800` UND Regen) (`config.py:856-857`, `weather_context.py:1789`).
> Der „UND Regen"-Zweig ist redundant zur Mengen-Schwelle; der „`cape > 1500` ohne Regen"-Zweig
> trifft **trockene Boom-Tage** (hoher Climb, fliegbar) — die würde das Gate fälschlich auf gray
> ziehen. CAPE-DANGER trägt nur Schaden bei. GUST/WIND/ALOFT/OVERCAST-DANGER bleiben ebenfalls
> **bewusst ausserhalb** (eigene Pfade: THERMAL-WIND-UNUSABLE etc.).

**Wichtige erwünschte Nebenwirkung:** Regen-Sandwich/Aufklärung wird automatisch korrekt
behandelt — nur die nassen Stunden fallen raus, ein trockener Nachmittag bleibt produktiv und
das Tier bleibt `green`. Kein Ganztags-Holzhammer.

**Bewusste Kopplung Safety→Flyability:** Der FLIEGBARKEITS-VERLAUF ist im Code als „unabhängig von
Safety" deklariert (`weather_context.py:1956`). Diese Änderung koppelt absichtlich das schmale
Wetter-Subset ein — Begründung: bei nennenswertem Regen/Gewitter kann man physisch nicht
in der Luft sein, das ist keine reine Reward-Frage. Orthogonalität bleibt für alles andere erhalten.
Regen/Gewitter dürfen in der Flyability-Analyse **als Fliegbarkeits-Grund** erscheinen, wenn sie
eine Stunde unfliegbar machen (User-Vorgabe 2026-06-04) — aber nicht als doppelte Safety-Warnung
(siehe revidierte Design-Leitplanke oben).

---

## Touch-Points (Implementierungs-Schritte)

> **Scope-Disziplin (Karpathy §2):** Kern = ein lokales `weather_unflyable`-Flag plus
> `and not weather_unflyable` an den bestehenden Bedingungen. Wegen der LLM-Sichtbarkeits-Vorgabe
> kommt **ein** schmaler Zähler/Sammler dazu: pro Schleife die wetterbedingt ausgeschlossenen
> Stunden mitzählen + Grund (Regen/Gewitter) sammeln, um Hint-Zeile (`WETTER-GATE: Nh …`) und
> Timeline-Label zu speisen. KEINE weitere Abstraktion, KEIN neues Tag-System — `[THUNDERSTORM]`/
> precip-Schwelle wiederverwenden. Hint-Erweiterung bleibt eine Zeile.

### Phase 1 — Spot-Schleife (`_build_single_spot_context`)

1. **Produktiv-Gate** (~Z.1872–1896): `weather_unflyable` einmal berechnen (vor dem Produktiv-Block;
   `warnings` ist ab ~Z.1810 vollständig) und an alle drei Zähler hängen — `productive_thermal_h`,
   `productive_h_strict`, `strong_h`.
   - `band_too_shallow_h` bleibt unangetastet (reiner Diagnose-Zähler).
2. **FLIEGBARKEITS-VERLAUF** (~Z.1966 `is_productive`): `and not weather_unflyable` ergänzen,
   damit eine Regenstunde nicht als `produktiv(x.x)` in der Timeline erscheint. **Gegatete Stunden
   bekommen ein explizites Label mit Grund** (D3 jetzt entschieden: Option b), z.B.
   `nicht-fliegbar(Regen)` / `nicht-fliegbar(Gewitter)` — damit das LLM in der Timeline sieht,
   welche Stunden warum rausfielen (statt irreführend „soaring").
3. **Hint-Text** (~Z.2433 `→ PRODUKTIVE-THERMIK`): (a) Bedingungs-Klammer um „kein Regen
   ≥0.5 mm/h, kein Gewitter" erweitern UND (b) die **Anzahl wetterbedingt ausgeschlossener
   Stunden explizit ausweisen**, damit der Gate NICHT still ist, z.B.
   `→ WETTER-GATE: 2h ausgeschlossen (Regen 13–14 Uhr, Gewitter 15 Uhr)`. So kann das LLM die
   reduzierte Produktiv-Zahl in der Analyse korrekt begründen (User-Vorgabe 2026-06-04).

### Phase 2 — Region-Schleife (`_build_region_context`)

Spiegelbildlich — inkl. der LLM-Sichtbarkeit aus Schritt 2+3:
4. Produktiv-Gate (~Z.3050–3078): `productive_thermal_h`, `productive_h_strict`, `strong_h`.
5. `is_productive_r` Timeline (~Z.3147): Gate + explizites `nicht-fliegbar(Regen/Gewitter)`-Label.
6. Hint-Text (~Z.3484): Bedingungs-Klammer erweitern + `WETTER-GATE: Nh ausgeschlossen (…)`-Zeile.

> Region-Sonderfall (D2): Region-`precipitation` ist der Hybrid-gefilterte **Peak über die RPs**
> (`fetch_weather.py`), nicht die Fläche. Die Mengen-Schwelle `>= PRECIP_UNFLYABLE_MM` wirkt damit
> auch hier sinnvoll: eine 0.1-mm-Einzelzelle gated nicht, eine kräftige Zelle (auch wenn nur am
> Peak-RP) schon. Bewusst KEINE extra `precipitation_class`-Logik — die Menge regelt es.

### Phase 3 — Skill-Prompt (LLM-Sichtbarkeit, D4) + Doku

7. **Skill-Prompt** `skills/shared/04_flyability/04_flight_subratings_{spot,region}.md` (~Z.17,
   die alte „kein Regen in Flyability-Prosa"-Leitplanke): umformulieren → das LLM SOLL Regen/
   Gewitter als *Fliegbarkeits*-Grund nennen, wenn `WETTER-GATE`/`nicht-fliegbar(…)` Stunden
   ausschließt („bei Regen kein nutzbares Steigen"), aber nicht als doppelte Safety-Warnung.
8. `docs/FLYABILITY_TIER_LOGIK.md`: Definition `productive_thermal_h` um die Wetter-Bedingung
   ergänzen (Tabelle Z.45–52 + Cache Z.142) + neuen `WETTER-GATE`-Hint dokumentieren.
9. Code-Kommentar bei den Zählern erweitern (parallel zur ROUGH-UNUSABLE-Begründung).

### Phase 4 — Validierung

10. `python -m pytest tests/test_decision_engine.py tests/test_few_shot.py` (grün halten).
11. Replay auf bekanntem Regentag (z.B. `scripts/replay_problem_cases.py` /
    `debug_scripts/check_fuerenalp_rain.py`): vorher/nachher `productive_thermal_h` vergleichen
    UND prüfen, dass die `recommendation`/`flyability`-Prosa die Regen-Stunden korrekt als Grund
    benennt (nicht nur die Zahl sinkt).
12. Smoke-Test: Tag mit Regen-Sandwich → trockener Nachmittag bleibt produktiv (kein Over-Kill).

---

## Entscheidungen

- **Gate-Konzept (revidiert nach Kritik 2026-06-03):** Gewitter (`[THUNDERSTORM]`) immer + Regen
  ab Mengen-Schwelle (`precip >= PRECIP_UNFLYABLE_MM`). **NICHT** das binäre `[RAIN-WARN]`,
  **NICHT** CAPE-DANGER. Wind-DANGER bleibt ausserhalb. ✅ entschieden.
- **D1 — Regen-Schwelle:** `PRECIP_UNFLYABLE_MM = 0.5 mm/h` (einheitlich Spot + Region).
  ✅ **entschieden 2026-06-04** nach Deep-Research (s. „Schwellen-Entscheidung" oben). Revidiert
  von der früheren 2.5 — die war eine umgedeutete Safety/Abbruch-Grenze; es gibt keinen
  mechanistisch fundierten mm/h-Steig-Kollaps-Punkt, das Signal ist „Regen am Boden" (≈ binär).
- **D2 — Region-Granularität (offen, klein):** Region-`precipitation` ist der Hybrid-gefilterte
  Peak über RPs → mit 0.5 gated bereits ein einzelner kräftigerer nasser RP die ganze Region,
  obwohl der versetzte Inflow daneben real steigen könnte. Bewusst trotzdem einheitlich 0.5
  (Simplizität). *Im Replay beobachten:* falls Region zu aggressiv auf gray degradiert → später
  Coverage-Bedingung (`precipitation_coverage`) oder höherer Region-Wert. Vorerst keine extra Logik.
- **D3 — Timeline-Label:** ✅ **entschieden 2026-06-04 → Option (b)** (umgekehrt zur früheren
  Empfehlung, wegen LLM-Sichtbarkeits-Vorgabe). Gegatete Stunde bekommt ein **explizites Label mit
  Grund** statt des irreführenden `soaring`: `nicht-fliegbar(Regen)` bzw. `nicht-fliegbar(Gewitter)`
  (Spot `weather_context.py:1989` / Region `:3170`). Damit sieht das LLM in der Timeline direkt,
  welche Stunde warum als nicht-fliegbar fiel — Voraussetzung dafür, dass es das in der Analyse
  begründen kann. Der parallele SICHERHEITS-VERLAUF (`DANGER(RAIN)`) bleibt zusätzlich bestehen.
- **D4 — Skill-Prompt:** ✅ **revidiert 2026-06-04 → JA, verankern.** Der Skill
  (`04_flight_subratings_*.md`) muss explizit erlauben/instruieren: Wenn Regen/Gewitter eine Stunde
  unfliegbar macht, das in der Flyability-Begründung benennen (als *Fliegbarkeits*-Grund: „bei Regen
  kein Steigen", NICHT als doppelte Safety-Warnung). Gegen-Vorgabe zur alten Leitplanke
  „kein Regen in Flyability-Prosa" — siehe revidierte Design-Leitplanke. Zähler-Gate + Hint allein
  reichen NICHT mehr, weil das LLM die Reduktion sonst nicht erklären darf.

## Nicht im Scope

- Kein neuer deterministischer Tier-Override (v1.5 hat den bewusst entfernt).
- Keine Änderung an Safety-Logik (`NIEDERSCHLAG-TREND`/`GEWITTER-TREND` bleiben wie sie sind).
- ~~Keine Regen-Erwähnung in Flyability-Freitextfeldern.~~ **Aufgehoben 2026-06-04:** Regen/Gewitter
  DARF in der Flyability-Begründung stehen, wenn er der Grund für eine unfliegbare Stunde ist
  (siehe revidierte Design-Leitplanke + D4) — nur nicht als doppelte Safety-Warnung.

## Risiken

- DeepSeek V4 Flash ist autoritativ fürs Tier — der Zähler-Gate wirkt nur, wenn das LLM dem
  `PRODUKTIVE-THERMIK`-Hint folgt (tut es laut Memory `[[region-safety-cap]]` für V4 Flash, nicht
  für gpt-4o-mini). Bei Modell-Wechsel re-validieren.
- Cache: `_ctx_tq_cache` wird beim nächsten Build überschrieben — keine Migration nötig,
  aber alte Snapshots zeigen bis zum Refresh die alten (höheren) Werte.
- **Stundenmittel vs. kurzer Guss:** `precipitation` ist ein Stunden­mittel (mm/h). Mit der
  niedrigen 0.5-Schwelle ist das weniger kritisch als bei 2.5 — schon ein kurzer Schauer hebt das
  Stundenmittel meist über 0.5. Reine Sub-10-Minuten-Spitzen können noch darunter mitteln; bei
  konvektiven Lagen fängt `[THUNDERSTORM]` die schlimmsten Fälle separat ab. Akzeptierter
  Trade-off (kein Sub-Stunden-Signal im Modell).
- **Versetzter Inflow / dry microburst nicht erfasst:** Der Gate sieht nur „Regen am Spot". Echtes
  Steigen NEBEN dem Regen (Inflow) wird korrekt nicht gegated, solange dort precip≈0 ist — gut.
  Aber trockene Microbursts/Virga (starker Abwind, wenig Bodenregen) rutschen durch; das ist
  Safety-Domäne (CAPE/Gewitter), bewusst nicht im Flyability-Gate. Prinzipielle Grenze der
  Regenrate als Proxy (Memory `[[rain-thermals-research]]`).
- **Region evtl. zu aggressiv:** Peak-über-RPs + 0.5 → eine kräftige Einzelzelle kann die ganze
  Region degradieren. Im Replay (Phase 4) gezielt prüfen; ggf. Coverage-Bedingung nachrüsten (D2).
