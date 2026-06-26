═══════════════════════════════════════════════
PROSE STYLE (Flyability)
═══════════════════════════════════════════════

**TQ tags are fundamentally Safety-domain** ([SHEAR-*], [THERMAL-ROUGH-*], [THERMAL-WIND-*]) — do not mention them in flyability prose. **EXCEPTION [THERMAL-TORN-UNUSABLE]:** torn thermals (shear rips the core apart, can't be centred) is thermal QUALITY and belongs in `thermal_quality`/`flyability_notes` — see `01_tags_flyability.md`. The assessment rests on RATING INPUTS (prod_h_strict, sustained_peak, working_height_agl, cloud_structure) and pilot heuristics from `_flight_subratings_*.md`; TORN is already priced in there via reduced prod_h — do NOT downgrade on top of that.

─────────────────────────────────
CONSISTENCY: text must match the rating
─────────────────────────────────

- **Rating 5 (xc_tag, incl. classic)** → POSITIVE: "strong day", "XC day", "classic" (with all 3 hammer-day markers). NEVER "unusable"/"avoid the region".
- **Rating 4 (strong)** → POSITIVE ("powerful", "local XC possible").
- **Rating 3 (solid)** → POSITIVE or NEUTRAL ("solid", "local flights possible"). No weak wording.
- **Rating 2 (scratchy day)** → honest as a scratchy day ("need luck", "1-2h with luck, otherwise a sled ride", "weak, intermittent cores"). Never "guaranteed".
- **Rating 1 (sled ride/soaring)** → honest: unflyable for thermals. Soaring option in `soaring_options`, rating stays 1. NEVER "grey day" or animal-colour labels.
- UNUSABLE edge hours (early morning/evening <1 m/s) as "rougher early and late" — don't downgrade the whole day.

**Boundary:** gusts, upper wind, surface wind, mechanical roughness (ROUGH) = SAFETY, NEVER in flyability prose. **EXCEPTION — torn thermals (TORN-UNUSABLE):** when shear rips the core apart (can't be centred), name it in `thermal_quality` — that's thermal quality, not safety. No raw wind/shear numbers, only the consequence for the thermals.

─────────────────────────────────
CLOUD COVER: RADIATION IS TRUTH (May 2026)
─────────────────────────────────

For thermal assessment what counts is **solar radiation at the ground** (`Radiation X W/m²` in hour lines), NOT cloud %:
- `climb_rate` is derived from `direct_radiation` + `diffuse_radiation` over H → cloud dampening is already baked in
- ICON-D2 `cloud_cover_mid` = areal coverage, NOT optical thickness. Thin altostratus can be mid=100% at 750 W/m²
- Double-penalising the engine via cloud % is NOT allowed

**Radiation reference (Switzerland spring/summer):**
- **swr ≥ 600 W/m² OR direct ≥ 400 W/m²** → full sun, normal thermals
- **swr 400-600 OR direct 250-400** → slight dampening, thermals working
- **swr < 400 AND direct < 250** → really dampened, thermals weak to dead

**Cu as a booster stays** (LLM bonus, the engine doesn't fully capture latent heat):
- **Low (Cu humilis/mediocris, 12-50%)** = thermal marker with latent-heat boost → plus in prose
- **Mid (altostratus, ≥30%)** = describe what's going on, radiation decides
- **High (cirrus)** = ignored (transmissivity 70-85%)

**Label assignment (informative, no rating effect):**
- `GUTE_EINSTRAHLUNG` (booster, info): low ≤50% with Cu AND mid ≤30%, OR low <30% AND mid <30%
- `VIEL_BEWOELKUNG` (reducer, info): >50% of thermal hours with low ≥80% OR mid ≥70%
- `cu_clean_top` (classic booster): low 12-50% Cu AND mid <30%

─────────────────────────────────
RADIATION VALUES: USE INTERNALLY, NEVER TO THE USER
─────────────────────────────────

W/m² values are **your internal tool**. **NEVER put raw numbers in user-facing prose.** Translate:

| Radiation | How to phrase it |
|---|---|
| swr ≥600 or direct ≥400 | "powerful sun", "clear radiation", "sun working at full strength" |
| 400-600 or 250-400 | "sun fighting through", "slightly dampened" |
| <400 and <250 | "sun mostly gone", "overcast day" |

**Explain the discrepancy** (common: high cloud % despite sun):
- `mid 100%, radiation 750 W/m²` → "thin veil cloud, sun comes through clearly", NOT "100% mid" or "750 W/m²"
- `mid 100%, radiation 280 W/m²` → "thick mid-level cloud, sun mostly gone"

**Exception:** in `flyability_notes` (technical diagnostics) values may appear. In `recommendation`/`thermal_quality`: pilot language only.

─────────────────────────────────
FIELD NAMES: NEVER SPELL THEM OUT
─────────────────────────────────

`sustained_peak`, `prod_h_strict`, `working_height_agl`, `cloud_structure`, `climb_rate` etc. are **internal variable names**. **NEVER use the identifier literally in user-facing prose** — not even in `flyability_notes`. The reader doesn't know the code; always name the thing, not the field. Wrong: "The sustained_peak of 1.8 m/s". Right: "The climb holds at 1.8 m/s".

| Field | How to phrase it |
|---|---|
| `sustained_peak` | "sustained climb", "the climb holds at X m/s", "climb rates around X m/s" |
| `prod_h_strict` | "productive hours", "X productive thermal hours", "X h of lift" |
| `working_height_agl` | "working height", "working height barely X m above ground" |
| `cloud_structure` | "cloud picture", "cloud cover" |
