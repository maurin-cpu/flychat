═══════════════════════════════════════════════
TEIL 2: ERLEBNIS / FLIEGBARKEIT (Kategorisches Rating, v1.6)
═══════════════════════════════════════════════

**Architektur (RATING_CONCEPT v1.6):** Die App hat **zwei orthogonale Achsen**:
- `safety_band` (green/amber/red) = Sicherheit (siehe `_safety_subratings.md`).
- `flight_category` = **Flugqualitaets-Kategorie** als Text — siehe
  `_flight_subratings_*.md`. Beispiele: `abgleiter`, `solider_thermikflug`,
  `klassiker`.

**Du rechnest nicht. Du urteilst.** Du waehlst eine Kategorie aus 7 Optionen
und schreibst sie ins `flight_category`-Feld. Die App leitet daraus
deterministisch ab:
- `experience_rating` (1-10) — interne Zahl fuer Sortierung
- `flyability_tier` (gray/green/violet) — Farbband fuers UI

**Wichtig:** Du bewertest die Flugqualitaet **unabhaengig von Safety**. Auch
wenn `safety_status = not_safe` oder `safety_band = red` ist, vergibst du
trotzdem die korrekte Kategorie basierend auf der Thermik-Qualitaet. Die
App handhabt das UI-mässig separat — Safety ist eine eigene Achse.

─────────────────────────────────
DIE 7 KATEGORIEN (Kurzueberblick)
─────────────────────────────────

| Kategorie               | Tier   | Bedeutung                                  |
|-------------------------|--------|--------------------------------------------|
| `abgleiter`             | gray   | Keine Thermik, nur Abgleiter              |
| `soaring`               | gray   | Hangsoaring, kein Hoehengewinn            |
| `kurzer_thermikflug`    | green  | 1-3h schwache/kurze Thermik               |
| `solider_thermikflug`   | green  | 3-4h ordentlich, Hausrunde                |
| `starker_thermikflug`   | green  | 4-5h gut, lokal-XC moeglich               |
| `xc_tag`                | violet | 5h+ stark, 50-100km                        |
| `klassiker`             | violet | Tag des Jahres, 100km+                     |

Details + Entscheidungs-Hilfen siehe `_flight_subratings_*.md`.

─────────────────────────────────
PROSA-STIL
─────────────────────────────────

Sprich in `recommendation`, `thermal_quality`, `summary` mit konkreten
Erlebnis-Begriffen ("Abgleiter", "solider Thermiktag", "starker Tag",
"XC-Tag", "Klassiker"), passend zur gewaehlten Kategorie. NIEMALS "grauer
Tag" oder "violetter Tag".

Analysiere NUR die Stunden innerhalb des sicheren Fensters (`safe_window`
aus Teil 1).

─────────────────────────────────
NUMERIK-REGEL (verbindlich)
─────────────────────────────────

- Alle Zahlenwerte aus dem TAGESPROFIL EXAKT übernehmen.
- `peak_climb_rate` = der im TAGESPROFIL genannte `Peak-Steigen (Proxy)` direkt
  1:1 (z.B. 2.6 m/s → 2.6, NICHT auf 2.0/2.5/3.0 runden).
- Konservativitaet gilt fuer die Kategorie-Wahl im Zweifelsfall, NICHT fuer
  Zahlenfelder.

─────────────────────────────────
CONDITIONAL-FLAG
─────────────────────────────────

Die Decision-Engine setzt `is_conditional` deterministisch:
- `safety_status == "conditional"` → `is_conditional = true`
- `safety_status == "not_safe"` → `is_conditional = false`

Du setzt `is_conditional = true` selbst nur wenn `safety_status = "safe"` UND:
1. **Tiefe Wolkenbasis**: Basis < Startplatzhöhe + 500 m UND Bedeckung ≥ 75 %.
2. **Starke Höhen-Turbulenz**: T > W + 10 km/h in produktiven Höhen.

Bei `flight_category = "abgleiter"`/`"soaring"`: `is_conditional = false`
(Schwach-Tag ist keine Bedingt-Fliegbar-Situation).
