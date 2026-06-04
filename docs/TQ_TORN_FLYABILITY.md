# TORN: Scherung zerreißt die Thermik → wirkt auf die Fliegbarkeit

**Status:** Umgesetzt 2026-06-04. Beschreibt das **laufende** Verhalten.
**Code:** `engine/weather_context.py` (`_calculate_segment_shear`, `_thermal_quality_tags`,
beide Kontext-Loops), Skills `skills/shared/04_flyability/*`.
**Vorgeschichte:** ging aus dem verworfenen „Band-Cap"-Plan hervor (siehe Anhang).

---

## Was das Feature tut

Wenn der Wind die Thermik in der Höhe **zerreißt** (`[THERMAL-TORN-UNUSABLE]`), gilt diese
Stunde nicht mehr als produktive Thermik-Stunde, und das LLM benennt die Scherung ehrlich
in der Flyability-Prosa. Drei Bausteine:

1. **10m-Anker-Fix** — die Scherungs-Berechnung lässt den reibungsverfälschten Bodenwind weg.
2. **Binär-Gate** — tiefes echtes TORN zählt nicht als produktiv (wie ROUGH/WIND).
3. **Prosa-Pflicht** — das LLM erwähnt „Scherung zerreißt den Bart" in `thermal_quality`.

---

## Baustein 1 — 10m-Anker-Fix

Die Scherung (`dU/dz`) wird aus einer Höhen-Treppe von Windpunkten berechnet. Der unterste
Punkt („Anker") saß früher auf Startplatz-Höhe mit dem **10m-Bodenwind**. Dieser Wind ist
von der Bodenreibung gebremst → der Sprung zum freien Höhenwind sah aus wie starke Scherung,
war aber Reibung. Das erzeugte ein **Schein-TORN direkt über dem Start**.

```
HEUTE — Anker für SHEAR/TORN weggelassen

  1900 m ── 800 hPa   22 km/h ──┐
  1500 m ── 850 hPa   24 km/h ──┘  ◄── unterste GEWERTETE Stufe (frei ↔ frei)
  ┄┄┄┄┄┄ Reibungsschicht ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄
  1010 m ── 10m-Wind    9 km/h       bleibt für Start · WIND · ROUGH
  1000 m ── Start ───────────────────
```

`_calculate_segment_shear(..., include_surface_anchor=False)` wird **nur** für SHEAR/TORN
aufgerufen. **Startbarkeit, WIND (BL-Mittelwind) und ROUGH (Böigkeit) nutzen den 10m-Wind
unverändert** — sie wollen den echten Bodenwind; die bodennahe Ruppigkeit ist über die Böen
(ROUGH) ohnehin abgedeckt.

**Wirkung (Messung über 495 Spots × 5 Tage):** TORN-Segmente fielen von **2686 → 83 Std**
(≈ 97 % der rohen Treffer waren das Reibungs-Artefakt). Das verbliebene TORN ist nachweislich
echt (siehe „Warum vertrauenswürdig").

*Trade-off:* Eine echte *gerichtete* Scherschicht direkt über dem Start wird ggf. erst ab
der ersten Druckfläche erkannt — selten, bewusst akzeptiert.

---

## Baustein 2 — Binär-Gate auf die Produktiv-Stunden

In beiden Kontext-Loops (Spot + Region):

```python
torn_unusable_this_hour = "[THERMAL-TORN-UNUSABLE]" in tq_tags_this_hour
```

`productive_thermal_h`, `productive_h_strict` und `strong_h` zählen eine Stunde nur, wenn
`not torn_unusable_this_hour` — genau wie `not rough_unusable_this_hour` (ROUGH/WIND). Der
`band_too_shallow_h`-Diagnosezähler bleibt unangetastet.

**Warum binär (und nicht das aufwändige Band-Cap-Modell):** Das echte TORN sitzt sehr tief
(Median rel-Höhe ~0.12–0.15). Unter dem Riss bleibt fast nie genug Band für `min_band_depth`
übrig → ein Höhen-Cap würde die Stunde in der Praxis ohnehin streichen = identisch zur
Binär-Regel, nur mit viel mehr Code. Siehe Anhang.

**Wirkung:** 73 Std / 35 Spots fallen aus der Produktivität (exponierte Jura-Kämme —
Hasenmatt, Grenchenberg, Boezingenberg, Pleiades …). 92 % der Spots unberührt, kein Spot
verliert einen ganzen Tag. Das Gate nutzt den **Spalten-Tag** `[THERMAL-TORN-UNUSABLE]`
(konsistent mit der Fliegbarkeits-Timeline, konservative Teilmenge der 83 per-Segment-Fälle).

---

## Baustein 3 — Prosa-Pflicht (TORN ist Flyability-Domäne)

Der Engine-Kontextblock `→ THERMIK-QUALITÄT` weist das LLM an:
- TORN-UNUSABLE **nicht zusätzlich** am Tier zu strafen (die Strafe steckt schon in der
  gesenkten `productive_thermal_h`),
- aber die Scherung **ehrlich in der Flyability-Prosa zu benennen** („Scherung reißt den
  Bart auf, nicht zentrierbar").

**Domänen-Trennung (wichtig):** Anders als die übrigen TQ-Tags ist TORN eine **Ausnahme** —
es ist *Thermik-Qualität* und gehört in `thermal_quality`/`flyability_notes`. SHEAR (geneigte
Blase), ROUGH (Böigkeit), WIND (Grundwind) sowie Böen/Höhenwind bleiben **Safety-Domäne** und
tauchen NICHT in der Flyability-Prosa auf. Regen/Gewitter ebenfalls nicht.

Geregelt in: `01_tags_flyability.md`, `03_prose_style.md`, `04_flight_subratings_spot/region.md`,
`00_template_spot/region.md`. Keine rohen Wind-/Scherungs-Zahlen in der Prosa — nur die
Konsequenz für die Thermik.

> Befolgt zuverlässig von DeepSeek V4 Flash (Tier-autoritativ), nicht von gpt-4o-mini. Bei
> Modellwechsel re-validieren.

---

## Warum das tiefe TORN vertrauenswürdig ist

Untersuchung 2026-06-04 (`debug_scripts/test_torn_shear_vs_climb.py`, 83 Fälle):
- **100 % shear-getrieben, 0 % Climb-Artefakt.** 86 % SHEAR-ECHT (`du_dz` ≥ danger, Median
  4.37 vs. Schwelle 3.0), 14 % SHEAR-WARN.
- Der `CLIMB_FLOOR` (0.3 m/s) wird **nie** ausgelöst — bei rel 0.15 ist die parabolische
  Steigrate noch ~1.7 m/s.
- **90 % zerreißen sogar den Säulen-Peak-Kern** (`peak_climb/du_dz·100 ≤ 60`) — d.h. die
  Scherung würde selbst eine kräftige Thermik zerreißen, nicht nur die schwache am Boden.

**Caveat:** Die 83/73 Fälle stammen aus *einer* (windigen) Wetterlage. Ein Föhntag liefert
mehr (dann real & richtig), eine Schwachwind-Lage 0. Vor endgültiger Abnahme über mehr
Wetterlagen replayen.

Meteo-Fundierung: Scherung deckelt die Thermik in einer Höhe; ob man durchsteigt, hängt von
der Thermik-Stärke ab (*„weak thermals are ripped to shreds"*, FAA). Genau das misst B/S
(Auftrieb ÷ Scherung). Quellen in `meteo_research/wind_shear_thermal_quality.md`.

---

## Datenherkunft

`wind_speed_10m` ist ein **roher Open-Meteo-Wert** (CH-Surface-Params), nichts von uns
Gerechnetes — die Reibungsbremsung steckt im Modell selbst. Auf Region-Ebene Median über die
Referenzpunkte, sonst spot-roh.

---

## Verifikation

| Skript | Befund |
|---|---|
| `debug_scripts/verify_anchor_fix.py` | 0 Anker-Segmente; TORN 2686 → 83 Std |
| `debug_scripts/verify_torn_gate.py` | 73 Std / 35 Spots aus Produktivität gegated |
| `debug_scripts/test_torn_shear_vs_climb.py` | 100 % shear-getrieben, 90 % zerreißen Peak-Kern |
| `debug_scripts/test_torn_spot_impact.py` | 1,3 % der Thermikstunden, 8 % Spots, kein Ganztag |
| `tests/test_decision_engine.py` u.a. | grün (2 vorbestehende, unabhängige Failures) |

End-to-end (Hasenmatt 2026-06-06): `THERMIK-QUALITÄT … TORN-UNUSABLE 2h`, Hinweis-Zeile
„Scherung zerreisst die organisierte Thermikblase" erscheint, `productive_thermal_h` gesenkt.

---

## Offen

- **Replay über mehr Wetterlagen** (Föhn + Schwachwind) vor endgültiger Abnahme.
- Optionale **Peak-Kern-Verschärfung** (`peak_climb/du_dz·100 ≤ 60` zusätzlich zur
  Gate-Bedingung) — siebt die ~10 % Grenzfälle aus; beim Replay entscheiden, ob nötig.

---

## Anhang — VERWORFEN: Band-Cap-Modell

Die ursprüngliche Idee: nicht binär killen, sondern das **nutzbare Band** rechnen (saubere
Höhe von unten bis zur ersten Zerreiß-Decke `usable_top_m`, verglichen gegen `min_band_depth`).
TORN hätte die erreichbare Höhe **gedeckelt** statt die Stunde zu streichen.

**Verworfen, weil** das echte TORN bei rel ~0.12–0.15 sitzt — so tief, dass unter der Decke
fast nie `≥ min_band_depth` bleibt. Der Cap killt die Stunde praktisch ohnehin → identisch zur
Binär-Regel, nur mit deutlich mehr Code (4 Touch-Points, `usable_top_m`-Felder, Cap-Aggregate,
Reverse-Parser, LLM-Cap-Prosa). Falls echte Vignetten später ein *abgestuftes* Verhalten
beweisen (TORN hoch oben, das nur die Höhe senkt), kann der Cap reaktiviert werden.
