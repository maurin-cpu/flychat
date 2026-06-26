═══════════════════════════════════════════════
DAY OVERRIDE (after hazard blocks)
═══════════════════════════════════════════════

**You compute NOTHING.** The system provides all numbers in the DAY PROFILE.

─────────────────────────────────
OVERRIDE A — 35% RULE
─────────────────────────────────

Read `Ratio clean/total: X/Yh = Z%` (clean = CALM + SPORTY):
- **Z < 35**: Day predominantly dangerous. Even with a 4h window → max **conditional**, more likely **not_safe** if boxed in.
- **Z 35-60**: Mixed day. `safe` possible if the window is continuously CALM AND not boxed in.
- **Z > 60**: Normal case.

**Mandatory:** With `→ CAUTION Ratio < 35%` it MUST be reflected in `caution_notes` or `no_go_reasons`.

BOXED IN + wind trend in TREND VOCABULARY (`_hazards_*.md`). OVERRIDE B (WIND-DIRECTION) has been dropped — the launch-window rule in Block 2 replaces it.

═══════════════════════════════════════════════
STATUS DERIVATION (final step, part 1)
═══════════════════════════════════════════════

1. Read `Longest window: Xh` from WINDOW INFO. Binding.
2. Per hazard block: determine the trend pattern, check BOXED IN special cases.
3. Apply OVERRIDE A (35%).
4. Status per launch-window rule:
   - **safe**: window ≥{{cfg.CLEAN_WINDOW_MIN_HOURS}}h AND ratio ≥60% AND no BOXED IN special case AND no foehn no-go AND window mostly CALM.
   - **conditional**: window ≥{{cfg.CLEAN_WINDOW_MIN_HOURS}}h, but window mostly SPORTY OR ratio 35-60% OR BOXED IN-WARN OR active WARN day (GUST-WARN, ALOFT-WARN, CAPE-WARN, GUST-FLOOR=conditional, foehn ΔP 4-7). **NEVER `conditional` solely because of a short window size** — < {{cfg.CLEAN_WINDOW_MIN_HOURS}}h is always `not_safe`.
   - **not_safe**: window < {{cfg.CLEAN_WINDOW_MIN_HOURS}}h OR ratio <35% with BOXED IN OR BOXED IN-DANGER OR foehn/thunderstorm dominates.

═══════════════════════════════════════════════
REASONING PRINCIPLE FOR SENTENCE 1 IN `summary`
═══════════════════════════════════════════════

The derivation says **which status**. The reasoning says **what you fill sentence 1 with** — phrased yourself in pilot language, with concrete numbers. No schema, no placeholders.

**Principle per status:**

- **`not_safe`** → name the **dominant hazard** (matches `primary_no_go`) with value + time.
  - *Example (do not copy):* "Not safe due to foehn breakthrough, ΔP 8.4 hPa South from 11:00 — pressure gradient clearly above the no-go threshold."

- **`conditional`** → name **the factor that pulled the day down from `safe`**. Exactly one derivation point took effect — name it with numbers.
  - **NEVER** the window, calm hours, or absent hazards as the reasoning — the window is the precondition for the day not being `not_safe` in the first place.
  - *Example:* "Conditionally safe due to strong gusts 28-34 km/h from 13:00 — calm hours stay in the minority."

- **`safe`** → name **the setup that makes the day relaxed**. Look at the highest safety sub-ratings — that tells you what carries the day. Concrete, in pilot language.
  - **NEVER** "the day is classified as safe" (says nothing), "because no problems" (negative), audit-speak, or mere window existence. NO thermal/cross-country content — that belongs in Flyability.
  - *Example:* "Clean west wind 8-12 km/h all day in the right direction, altitude wind moderate around 22 km/h at 2500m — a calm setup for flying."

Examples are inspiration, not a mandatory schema. What matters is the **What** (limiting factor / dominant hazard / supporting setup), not the **How**.
