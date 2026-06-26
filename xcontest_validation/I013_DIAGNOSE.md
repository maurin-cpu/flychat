# I-013 Root-Cause-Diagnose — Pre-Filter-Instabilität (not_safe ⇄ conditional)

**Status: reine Diagnose, kein Code-Eingriff.** Erstellt aus den Snapshots 27.–30.05.2026
(Replay der Stundenwerte gegen den realen Code). Grundlage: `xcontest_validation/2026-05-27..30.md`.

## Frage

Warum stuft der Pre-Filter **denselben Spot** bei nahezu gleicher Wetterlage mal `not_safe`,
mal `conditional` ein? (Brunni 4 Tage: not_safe/not_safe/conditional/conditional; Niesen
27. conditional / 28.+30. not_safe — bei jeweils gegenüberliegendem Tageswind.)

## Antwort (1 Satz)

Die binäre `not_safe`-Entscheidung hängt allein daran, ob es **≥ 2 zusammenhängende
windschwache Morgenstunden** gibt, deren (bei Flaute meteorologisch bedeutungslose) Richtung
zufällig den erlaubten Sektor streift — **das reale Nachmittags-Flugfenster geht gar nicht in
das Gate ein**.

## Code-Pfad

1. **`chat_engine.py:545` `_is_wind_in_range(wind_dir, sektor)`** — prüft **nur die Richtung**,
   **ohne Mindestwind-Schwelle**. Einzel-Sektoren (`SW`, `SO`, `W`) bekommen ±45° (`:610`) plus
   `config.WIND_DIRECTION_TOLERANCE_PCT`-Puffer.
2. **`weather_context.py:1591`** ruft das pro Stunde auf → `wind_ok_hours`. Eine Stunde mit
   **0.7 km/h** Wind zählt als WIND-OK, sobald die Richtung passt. Ohne harte Warnung (niedrige
   Böe) ist sie zusätzlich „clean" (`:2029`).
3. **`weather_context.py:182` `_determine_active_window_start(clean_hours, CLEAN_WINDOW_MIN_HOURS)`**
   — gibt einen Fenster-Start zurück, sobald **≥ `CLEAN_WINDOW_MIN_HOURS` (=2, `config.py`)**
   zusammenhängende clean-Stunden existieren.
4. **`analyzers.py:173` `_prefilter_not_safe`**: `active_start is None and total_hours > 0`
   → bei `wind_ok == 0` hartes `not_safe` („Windrichtung ganztägig ausserhalb"). Sonst kein
   Pre-Filter → Spot geht als `conditional` weiter.

→ **`wind_ok == 0` ⇒ not_safe; ≥ 2 zusammenhängende clean-Stunden ⇒ conditional.** Dazwischen
liegt die gesamte Kippung. Keine Hysterese, kein Wind-Stärke-Gate.

## Beleg 1 — Brunni (Sektor SO-S-SW-W = 135–270°)

Stündliche Bodenwind-Richtung (08–19 h) aus den Snapshots:

| Tag | In-Sektor-Std | welche (dir / Windspeed) | Nachmittag 13–18 h (reales XC-Fenster) | wind_ok | **Status** | Real (XContest) |
|---|---|---|---|---|---|---|
| 27.05 | **0** | – | NW 316–349°, Gust 31–40 | 0 | **not_safe** | 2 Launches |
| 28.05 | **0** | – | N 340–357°, Gust 38–44 | 0 | **not_safe** | 2 Launches |
| 29.05 | **2** | 09:00 (135°/3.6) · 10:00 (270°/**0.7**) | N 331–355°, Gust 21–39 | 2 | **conditional** | 6 Launches |
| 30.05 | **2** | 09:00 (153°/2.4) · 10:00 (194°/**1.5**) | N 331–343°, Gust 24–32 | 2 | **conditional** | **71 Launches** |

Die kippenden Stunden am 29./30. sind **09:00 + 10:00 bei Windgeschwindigkeit 0.7–3.6 km/h**
(Flaute / Tal-Hangwind-Drehen). Das **Nachmittagsfenster ist an allen 4 Tagen praktisch identisch**
(N/NW, Gust 30–44). Die Klassifikation kippt also an 2 quasi-windstillen Morgenstunden, nicht an
den realen Flugbedingungen.

## Beleg 2 — Niesen-2280 (Sektor SW, ±45° → ~180–270°)

| Tag | In-Sektor-Std | welche (dir / Windspeed) | wind_ok | **Status** | Real |
|---|---|---|---|---|---|
| 27.05 | **3** | 08:00 (262°/5.1) · 09:00 (270°/4.0) · 10:00 (278°/**2.5**) | 3 | **conditional** | 11×, **336 km Tagessieger** |
| 28.05 | **0** | – | 0 | **not_safe** | 1×, **256 km** |
| 30.05 | **0** | – | 0 | **not_safe** | 4×, 52 km |

Niesen war am 27. nur `conditional`, weil der **2.5–5 km/h schwache Morgenwind** 3 h lang bei
262–278° lag (im SW±45+Toleranz-Band). Am 28./30. lag der ebenso schwache Morgenwind woanders →
`wind_ok=0` → hartes not_safe. **Identische Messerschneide wie Brunni.**

## Die zwei Wurzel-Hebel (zur Diskussion — NICHT implementiert)

**Hebel A — kein Wind-Stärke-Gate auf den Richtungs-Check** (`_is_wind_in_range`,
`chat_engine.py:545` / Aufruf `weather_context.py:1591`). Stunden mit < ~5–8 km/h sollten für die
Sektor-Klassifikation neutral sein (bei Flaute ist die Richtung Thermik-/Talwind-Rauschen, kein
Gradient). Das ist exakt **I-008**, hier auf die Zeile festgenagelt. Wirkung wäre **symmetrisch**:
die windschwachen Morgenstunden würden weder fälschlich „rettend" (Niesen 27., Brunni 29./30.)
noch fälschlich blockierend zählen.

**Hebel B — binäres Hard-Gate ohne Hysterese** (`_prefilter_not_safe`, `analyzers.py:173`).
Der Sprung von „1 clean-Stunde" auf „2 clean-Stunden" (= `CLEAN_WINDOW_MIN_HOURS`) flippt den
ganzen Tag von hartem not_safe auf conditional. Denkbar: weiche Stufe (z.B. Grenzfälle ans LLM
statt Hard-not_safe), oder das Gate an das **reale Tag-Maximum-Fenster** statt an Randstunden
koppeln.

**Sekundär — Single-Sided-/±45°-Sektoren** (I-006): Niesen `SW`, Weissenstein `SO`, Haldigrat
`SW`, Mägisserhorn `W`. Diese schmalen Sektoren sind genau die instabilsten — jede Drehung ist
entweder „komplett draussen" oder knapp drin. Hebel A+B entschärfen das Symptom; die schmalen
Sektoren sind die strukturelle Ursache dahinter.

## Empfohlene Verifikation vor einem Fix

- `WIND_DIRECTION_TOLERANCE_PCT` und `CLEAN_WINDOW_MIN_HOURS` aus `config.py` gegenchecken
  (aktuell: Einzelsektor ±45° + Prozent-Puffer; Block-Minimum 2 h).
- Ein Wind-Stärke-Gate (Hebel A) gegen die 6 Validierungstage **gegenrechnen**: Würde es echte
  Gefahrentage fälschlich öffnen? (Erwartung: nein — es betrifft nur Flaute-Stunden, deren
  Richtung ohnehin irrelevant ist.)
- `debug_weissenstein_wind.py` existiert bereits als Spot-Wind-Debugger — als Vorlage für einen
  Brunni-27.-vs-30.-Replay nutzbar.
