═══════════════════════════════════════════════
DAY WINDOW — already determined by the system
═══════════════════════════════════════════════

The data block contains only hours from the **day start** onward — the point from which a qualifying launch window (≥ {{cfg.CLEAN_WINDOW_MIN_HOURS}}h continuously clean) begins. The header `═══ TAGESFENSTER ═══` (day window) with `Tag aktiv ab HH:00` (day active from HH:00) is **authoritative**.

──────────────────────────────────
WHAT DOES "DAY START" MEAN?
──────────────────────────────────

The code has checked: first window of clean hours (spot: WIND-OK without DANGER. Region: no DANGER) with length ≥ {{cfg.CLEAN_WINDOW_MIN_HOURS}}h → its start hour = day start. No window → day already filtered out as `not_safe`, you don't see it.

Hours before the day start were omitted (surface wind outside the sector or hard warnings active). The header states the reason.

──────────────────────────────────
YOUR TASK: WINDOW NARRATIVE
──────────────────────────────────

1. **HOW MANY WINDOWS?**
   - 1 long one: describe normally.
   - 2+ with a DANGER break: name the fragmentation in `summary` ("two usable windows, showers/thunderstorms in between").

2. **HOW LONG?**
   - ≥ 4h: full-day flying, normal assessment.
   - 2-3h: in `caution_notes` ("only Xh flyable").
   - < {{cfg.CLEAN_WINDOW_MIN_HOURS}}h: never reaches you — the pre-filter has already set `not_safe`.

3. **WIND SHIFT AFTER DAY START?**
   - `[WIND-WRONG]` after day start = surface wind shifts during the day, the pilot is already in the air. NO hazard, NO status effect.
   - If the shift >2h touches landing aspects: optionally in `caution_notes` as a sober landing note ("return wind invalid from HH:00"), no risk language.

──────────────────────────────────
WHAT YOU DO NOT DO
──────────────────────────────────

- Do not question the day start — the code determined it deterministically.
- Do not add/reconstruct/lament hours before the day start.
- Do not derive `not_safe` from window length — the code has checked the minimum condition.
- NEVER frame `[WIND-WRONG]` within the active day as "danger"/"risk"/"warning".

──────────────────────────────────
EXAMPLES
──────────────────────────────────

**Case 1 — one long continuous window:** `Tag aktiv ab 11:00`, hours 11-17 clean.
→ `summary`: "Six hours of continuous flight window between 11:00 and 17:00."

**Case 2 — two windows with a break:** `Tag aktiv ab 10:00`, 10-12 clean, 13-14 [RAIN-WARN], 15-17 clean.
→ `summary`: "Two windows: 10:00-12:00 and 15:00-17:00, with a shower phase in between."

**Case 3 — wind shifts within the active day (spot):** `Tag aktiv ab 11:00`, 11-14 [WIND-OK], 15-17 [WIND-WRONG].
→ `summary`: "Four-hour launch window until 15:00, after that the surface wind shifts."
→ Optional `caution_notes`: "Return wind outside the sector from 15:00 — check landing options."
→ `safety_status` remains unaffected.
