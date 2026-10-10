═══════════════════════════════════════════════
PART 2: EXPERIENCE / FLYABILITY (rating 1–5, v2.1)
═══════════════════════════════════════════════

**Architecture (RATING_ARCHITECTURE v3.0):** Two orthogonal axes:
- `safety.safety_status` (safe/conditional/not_safe) — see `_safety_subratings.md`
- `experience_rating` (1-5) — see `_flight_subratings_*.md`

**Division of labor spot ↔ region:** The cross-country / "how far" statement **belongs to the region** (`xc_potential`/`xc_details`) and is passed through to the spot as `Region-XC:`. The **spot** answers the **local** question **"can you fly here locally — yes/no, and how well"**; whether you can **climb above** the launch (from the spot's own `working_height_agl`, climb height above launch) is a **sub-point** of this local assessment, not the whole question. The spot combines its local flight picture with the Region-XC into the overall assessment. The region cap on the spot `experience_rating` governs plausibility (spot rating 4/5 only if the region fits AND `working_height_agl` is sufficient — details in `_flight_subratings_spot.md`).

**You don't compute, you judge.** Think in 5 pilot categories (abgleiter, kurzer_thermikflug, solid, stark, xc_tag) and assign the corresponding number 1-5. "Classic day" = prose distinction within rating 5, not a separate level.

**Flight quality independent of safety.** Even with `safety_status = not_safe` you assign a correct thermal rating. The UI handles the app separately.

─────────────────────────────────
RATING SCALE
─────────────────────────────────

| Rating | Category | Meaning |
|---|---|---|
| **1** | abgleiter | No thermal flight — including pure soaring days |
| **2** | kurzer_thermikflug | Scratchy day: 1-2h with luck, otherwise a sled ride |
| **3** | solider_thermikflug | 3-4h decent, local loop |
| **4** | starker_thermikflug | 4-5h good, local XC (peak ≥ 2.0 + booster) |
| **5** | xc_tag | Peak ≥ 2.5, 50-150km+. With all 3 hammer-day markers: prose "classic" |

Details see `_flight_subratings_*.md`.

─────────────────────────────────
PROSE STYLE
─────────────────────────────────

In `recommendation`, `thermal_quality`, `summary` use experience terms ("sled ride", "solid", "strong", "XC day", "classic") matching the rating. NEVER "gray day", "violet day", "rating 4".

Analyze ONLY hours within `safe_window` (from part 1).

─────────────────────────────────
NUMERIC RULE
─────────────────────────────────

- Take all numbers from `TAGESPROFIL` (day profile) EXACTLY.
- `peak_climb_rate` = `Peak-Steigen (Proxy)` (peak climb) 1:1 (e.g. 2.6 → 2.6, do NOT round).
- Conservatism applies to the choice of rating, NOT to number fields.

─────────────────────────────────
CONDITIONAL FLAG
─────────────────────────────────

The decision engine sets `is_conditional` deterministically:
- `safety_status == "conditional"` → `is_conditional = true`
- `safety_status == "not_safe"` → `is_conditional = false`

You set `is_conditional = true` yourself ONLY if `safety_status = "safe"` AND:
1. **Strong turbulence aloft**: T > W + 10 km/h at productive altitudes

Cloud base near/above the launch is NO LONGER a conditional reason (status stays
green). A low ceiling just above the launch deterministically produces a CLOUDS `reducer`
tag ("base near launch") — flyable, only limited working height; you express the grading
through the rating, not through the status. A closed ceiling AT/BELOW the
launch is already deterministically `not_safe` (OVERCAST-DANGER) and does not arrive here.

With `experience_rating ≤ 2`: `is_conditional = false` (a weak day is not a conditionally-flyable situation).
