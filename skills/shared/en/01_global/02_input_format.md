═══════════════════════════════════════════════
INPUT FORMAT — HOW DO YOU READ THE DATA BLOCK?
═══════════════════════════════════════════════

Three zones: **hour lines**, **pressure-level values**, **`TAGESPROFIL` (day profile) block** at the end.

═══════════════════════════════════════════════
THREE TAG CATEGORIES (categorically separate)
═══════════════════════════════════════════════

Every tag in square brackets belongs to **exactly one**:

**CATEGORY 1 — LAUNCHABILITY FILTER** (spot only): `[WIND-OK]` / `[WIND-WRONG]`. No hazard, no flyability signal — its own category **day window** (see `_tagesfenster.md`).

**CATEGORY 2 — HAZARD TAGS** (safety signals): see `_tags_safety.md`. Can push the status down, end up in `caution_notes`/`no_go_reasons`, influence sub-ratings.

**CATEGORY 3 — THERMAL QUALITY TAGS** (flyability only): `[SHEAR-*]`, `[THERMAL-TORN-*]`, `[THERMAL-WIND-*]`, `[THERMAL-ROUGH-*]`. See `_tags_flyability.md`.

─────────────────────────────────
A) HOUR LINES
─────────────────────────────────

Per hour: surface wind, cloud cover, precipitation, CAPE, cloud base + tags in square brackets. Spot context: additionally gusts (turbulence risk). Region: NO gusts.

─────────────────────────────────
B) PRESSURE-LEVEL VALUES
─────────────────────────────────

Format: `pressure(altitude_m)MARKER: wind/boeen km/h aus dir°` (wind/gusts km/h from dir°)

**Markers:**
- `*` = **flight range** (spot altitude up to thermal top+1000m, incl. lid). [ALOFT-*] tags fire here. Thresholds: {{cfg.WIND_WARN_KMH}}-{{cfg.WIND_DANGER_KMH}} = WARN, > {{cfg.WIND_DANGER_KMH}} = DANGER.
- `~` = **buffer zone** (500m above the flight range). No hard tags. Gusts >50 km/h there → note in `caution_notes`. Buffer calmer than the flight layer → all-clear.
- **No marker** = 850/700 hPa as foehn anchor. Relevant only as a foehn indicator.

─────────────────────────────────
C) `TAGESPROFIL` block (at the end)
─────────────────────────────────

The system has counted and flagged everything:

- `Verhaeltnis sauber/gesamt: X/Yh = Z%` (ratio clean/total) — share of clean hours (CALM + SPORTY)
- `Hauptgefahren am Tag: GUST-DANGER 4h, ALOFT-DANGER 2h, ...` (main hazards of the day) — histogram (regions without GUST-*)
- `→ PRODUKTIVE-THERMIK: Nh` (productive thermals) — climb ≥{{cfg.PRODUCTIVE_CLIMB_MIN}}, low <{{cfg.PRODUCTIVE_LOW_CLOUD_MAX}}%, mid <{{cfg.PRODUCTIVE_MID_CLOUD_MAX}}%, no ROUGH-UNUSABLE/WIND-UNUSABLE (regions: without ROUGH)
- `→ BOEEN-FLOOR: MINDEST-STATUS = '...'` (gust floor: minimum status) — spot only, system-enforced, non-negotiable
- `→ ACHTUNG Verhaeltnis < 35%: ...` (caution: ratio < 35%) — optional, MUST go into caution_notes/no_go_reasons
- `THERMIK-QUALITAET-Block` (thermal quality block) — counters for SHEAR/TORN/ROUGH-UNUSABLE + TQ ratio
- **Trend labels:** `AUFKLAERUNG`/`ZUNEHMEND`/`EINGEKESSELT`/`DURCHGEHEND`/`VEREINZELT`/`STABIL` (clearing/increasing/boxed in/continuous/isolated/stable; definitions in `_hazards_*.md`). Apply per hazard block. Foehn excepted (severity across the board).
- **Separate trend lines:** `NIEDERSCHLAG-TREND` (precipitation trend), `GUST-TREND` (spot only), `WIND-TREND` (surface + aloft summed). MANDATORY input for the status. Mapping see `_hazards_*.md`. Trend lines contain **no ready-made sentences** to copy.

**Mandatory:** Read the values, do not compute them yourself. `BOEEN-FLOOR` is binding. "`Verhaeltnis` < 35%" MUST go into caution_notes/no_go_reasons.
