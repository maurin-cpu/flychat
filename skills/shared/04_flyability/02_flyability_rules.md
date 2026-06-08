═══════════════════════════════════════════════
TEIL 2: ERLEBNIS / FLIEGBARKEIT (Rating 1–5, v2.1)
═══════════════════════════════════════════════

**Architektur (RATING_ARCHITECTURE v3.0):** Zwei orthogonale Achsen:
- `safety.safety_status` (safe/conditional/not_safe) — siehe `_safety_subratings.md`
- `experience_rating` (1-5) — siehe `_flight_subratings_*.md`

Streckenflug ist **keine eigene Achse mehr**. Die XC-Aussage wandert als Pflicht-Satz in `xc_details`, der Region-Cap auf `experience_rating` regelt die Plausibilitaet (Spot-Rating 4/5 nur wenn Region passt UND `working_height_at_spot_m` ausreicht — Details in `_flight_subratings_spot.md`).

**Du rechnest nicht, du urteilst.** Denke in 5 Pilot-Kategorien (abgleiter, kurzer_thermikflug, solid, stark, xc_tag) und vergib die entsprechende Zahl 1-5. "Klassiker-Tag" = Prosa-Auszeichnung in Rating 5, keine eigene Stufe.

**Flugqualitaet unabhaengig von Safety.** Auch bei `safety_status = not_safe` vergibst du korrektes Thermik-Rating. UI handhabt App separat.

─────────────────────────────────
RATING-SKALA
─────────────────────────────────

| Rating | Kategorie | Bedeutung |
|---|---|---|
| **1** | abgleiter | Kein Thermikflug — auch reine Soaring-Tage |
| **2** | kurzer_thermikflug | Suchtag: 1-2h mit Glueck, sonst Abgleiter |
| **3** | solider_thermikflug | 3-4h ordentlich, Hausrunde |
| **4** | starker_thermikflug | 4-5h gut, lokal-XC (Peak ≥ 2.0 + Booster) |
| **5** | xc_tag | Peak ≥ 2.5, 50-150km+. Bei allen 3 Hammertag-Markern: Prosa "Klassiker" |

Details siehe `_flight_subratings_*.md`.

─────────────────────────────────
PROSA-STIL
─────────────────────────────────

In `recommendation`, `thermal_quality`, `summary` Erlebnis-Begriffe ("Abgleiter", "solid", "stark", "XC-Tag", "Klassiker") passend zum Rating. NIEMALS "grauer Tag", "violetter Tag", "Rating 4".

Analysiere NUR Stunden innerhalb `safe_window` (aus Teil 1).

─────────────────────────────────
NUMERIK-REGEL
─────────────────────────────────

- Alle Zahlen aus TAGESPROFIL EXAKT uebernehmen.
- `peak_climb_rate` = `Peak-Steigen (Proxy)` 1:1 (z.B. 2.6 → 2.6, NICHT runden).
- Konservativitaet gilt fuer Rating-Wahl, NICHT fuer Zahlenfelder.

─────────────────────────────────
CONDITIONAL-FLAG
─────────────────────────────────

Decision-Engine setzt `is_conditional` deterministisch:
- `safety_status == "conditional"` → `is_conditional = true`
- `safety_status == "not_safe"` → `is_conditional = false`

Du setzt `is_conditional = true` selbst NUR wenn `safety_status = "safe"` UND:
1. **Starke Hoehen-Turbulenz**: T > W + 10 km/h in produktiven Hoehen

Wolkenbasis nahe/über dem Startplatz ist KEIN conditional-Grund mehr (Status bleibt
grün). Eine tiefe Decke knapp über Platz erzeugt deterministisch ein CLOUDS-`reducer`-
Tag ("Basis nahe Startplatz") — fliegbar, nur eingeschränkte Arbeitshöhe; die Abstufung
machst du über das Rating, nicht über den Status. Eine geschlossene Decke AUF/UNTER
Platz ist bereits deterministisch `not_safe` (OVERCAST-DANGER), kommt hier nicht an.

Bei `experience_rating ≤ 2`: `is_conditional = false` (Schwach-Tag ist keine Bedingt-Fliegbar-Situation).
