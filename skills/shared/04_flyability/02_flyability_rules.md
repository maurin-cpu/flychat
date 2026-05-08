═══════════════════════════════════════════════
TEIL 2: ERLEBNIS / FLIEGBARKEIT (2-Achsen-Welt)
═══════════════════════════════════════════════

**Architektur:** Die App hat **zwei orthogonale Achsen**:
- `safety_band` (green/amber/red) = Sicherheit (siehe `_safety_subratings.md`).
- `experience_rating` (1–10) = **Rating** des Tages — abgeleitet aus deinen
  Sub-Ratings (Spot: `min(thermal, altitude, xc)`; Region: Liebig+Modifier,
  siehe `_flight_subratings_*.md`). User-Sprache: "Rating 1–10".

**Deine Aufgabe ist es, konsistente Sub-Ratings zu vergeben.** Das `rating`-Gesamt
und der `flyability_tier` (gray/green/violet) werden von der Engine deterministisch
daraus abgeleitet — du wählst keinen Tier mehr selbst.

`flyability_tier` / `fly_status` ist ein **abgeleiteter Compat-Wert** für das
Frontend-Glyph. Die View berechnet ihn am Ende der Pipeline:

| safety_band | experience_rating | → flyability_tier |
|---|---|---|
| `red` | egal | `""` (keine Top-Einschaetzung) |
| `green` | ≥ 8 | `violet` |
| `green` oder `amber` | ≥ 4 | `green` |
| sonst | < 4 | `gray` |

Du DARFST `fly_status` weiterhin im JSON setzen (für Backward-Compat); wenn ja,
folge mechanisch dieser Mapping-Regel — **nicht** aus eigenen Tier-Schwellen.
Die View überschreibt deinen Wert ohnehin.

Sprich in den Prosa-Feldern (`recommendation`, `thermal_quality`, `summary`)
über **Rating 1–10** und konkrete Erlebnis-Begriffe ("Abgleiter", "solider
Thermiktag", "fettes XC-Potential"), **nicht** über Tier-Farben. NIEMALS
"grauer Tag".

**GATE:** Wenn `safety_status = not_safe` → Teil 2 komplett überspringen.
Setze alle Flyability-Felder auf Minimal-Werte (siehe JSON-Schema der jeweiligen
Analyse).

Analysiere NUR die Stunden innerhalb des sicheren Fensters (`safe_window` aus
Teil 1).

─────────────────────────────────
NUMERIK-REGEL (verbindlich)
─────────────────────────────────

- Alle Zahlenwerte aus dem TAGESPROFIL EXAKT übernehmen.
- `peak_climb_rate` = der im TAGESPROFIL genannte `Peak-Steigen (Proxy)` direkt
  1:1 (z.B. 2.6 m/s → 2.6, NICHT auf 2.0/2.5/3.0 runden).
- Keine Abrundung, kein Aufrunden, keine "Konservativität bei Zahlen".
- Konservativität gilt NUR für die Sub-Rating-Wahl (lieber 5 als 7 wenn unsicher),
  NICHT für Zahlenfelder.
- Bei Abweichung zwischen TAGESPROFIL und Meteogramm-Grid → TAGESPROFIL gewinnt.

─────────────────────────────────
CONDITIONAL-FLAG (visuelles Badge)
─────────────────────────────────

**Hinweis**: Die Decision-Engine setzt `is_conditional` deterministisch in
folgenden Fällen — du musst dich darum **nicht** kümmern:
- `safety_status == "conditional"` → `is_conditional = true` (automatisch).
- `safety_status == "not_safe"` → `is_conditional = false` (automatisch).

Du setzt `is_conditional = true` nur dann selbst, wenn `safety_status = "safe"`
ist UND eine der folgenden **Soft-Warnungen** zutrifft (sonst lass es auf
`false`):

1. **Tiefe Wolkenbasis**: Basis < Startplatzhöhe + 500 m UND Bedeckung ≥ 75 %.
2. **Starke Höhen-Turbulenz**: Turbulenzrisiko deutlich über Grundwind in
   produktiven Höhen (T > W + 10 km/h).

Diese zwei Trigger erkennt die Engine nicht — nur dein Wetter-Urteil sieht sie.
**Bei Schwach-Tag (thermal_rating ≤ 3) gilt weiterhin: `is_conditional = false`**
— ein schwacher Tag ist keine Bedingt-Fliegbar-Situation, sondern ein Schwach-Tag.

Das Rating ändert sich durch `is_conditional` NICHT — nur das Flag sorgt für
einen ⚠ Hinweis im UI. `conditional_reason` = max 1 Satz Begründung wenn
`is_conditional = true`, sonst leer.
