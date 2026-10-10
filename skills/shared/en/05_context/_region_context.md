═══════════════════════════════════════════════
REGION SPECIFICS: MAGNITUDE-BASED WIND TAGS
═══════════════════════════════════════════════

Regions have NO allowed sector (unlike spots) and **NO gusts**. Wind values are interpolated to the region's **reference altitude** and classified using the same thresholds as spots — based on wind speed only:

- No tag — wind < {{cfg.WIND_WARN_KMH}} km/h → CALM (good conditions).
- `[WIND-WARN]` — wind {{cfg.WIND_WARN_KMH}}-{{cfg.WIND_DANGER_KMH}} km/h → SPORTY.
- `[WIND-DANGER]` — wind > {{cfg.WIND_DANGER_KMH}} km/h → UNFLYABLE.

**Clean hour (region)** = no tag or `[WIND-WARN]` WITHOUT hard no-go tags. Only clean hours belong in the `safe_window`. Flag SPORTY hours in `caution_notes` with the time.

**Important:** If the data block shows e.g. `[Ref-Wind 1300m: 37km/h]` (reference wind), that is the actual wind at flying altitude — NOT surface wind. The tags are based on it and are more reliable than pure surface values.

**No gusts at region level:** Gusts are local peak values and belong at spot level. For regions there are therefore **no** `[GUST-WARN]`, `[GUST-DANGER]`, `[ALOFT-GUST-WARN]`, `[ALOFT-GUST-DANGER]` and no `[THERMAL-ROUGH-*]` tags. **Never** mention gusts in `no_go_reasons`, `caution_notes`, `wind_summary` or `summary` of a region context. If the user asks about gusts, point out that a specific spot is needed for that.

Thermal-tearing signals at region level come via three mechanisms:
- `[SHEAR-*]` (wind shear through the BL)
- `[THERMAL-TORN-*]` (buoyancy/shear ratio: lift vs. shear)
- `[THERMAL-WIND-*]` (mean background wind through the mixing layer — the bubble cannot detach in an organized way)

═══════════════════════════════════════════════
REGION SPECIFICS: FOEHN DIRECTION CHECK
═══════════════════════════════════════════════

Each region has in its header `Kritischer Foehn: Sued | Nord | Beide` (critical foehn: south | north | both):
- **`Sued`** = region north of the main Alpine ridge → only south foehn triggers the warning.
- **`Nord`** = region south of the main ridge → only north foehn triggers the warning.
- **`Beide`** = region on/near the main ridge.

North foehn does **NOT** affect the Mittelland, the Jura, the northern Prealps — they get cold Bise in a northerly situation.

If the direction does not match: `foehn_risk = "none"` (even with a high delta-P!).

Foehn severity thresholds + hidden foehn: see `_hazards_region.md` block 5.
