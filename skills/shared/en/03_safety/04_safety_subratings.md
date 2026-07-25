═══════════════════════════════════════════════
SAFETY SUB-RATINGS (8 individual ratings, 1-10)
═══════════════════════════════════════════════

You assign 8 individual safety ratings: wind, gust, aloft, foehn, rain, thunderstorm, cape, visibility.

**Aggregation (weakest-link):** `safety_rating = min(all 8)`, then `safety_score = safety_rating × 10`. Perfect wind does not compensate for thunderstorm risk.

**Override architecture:** Foehn (`foehn_risk=high`) and upper-level wind (`ALOFT-NOT-SAFE`) are overridden by the decision engine. You rate the other hazards yourself (rain, thunderstorm, CAPE, visibility). SubRatingFloor: rating ≤ 2 → `not_safe`, ≤ 3 → `conditional`.

**Factor in the trend — MANDATORY:** Every rating is forward-looking. Rate the **worst plausible** state including the trend. Wind calm at first, building to 35 km/h from 14h → lower rating than a steady 18 km/h.

**Scale anchors (1, 5, 10) — values 2-4, 6-9 by context:**
- **1** = acutely dangerous
- **5** = borderline, noticeable risk
- **10** = unremarkable

**Use the full range** — deliberately distinguish between 6, 7, 8.

─────────────────────────────────
THE 8 SUB-RATINGS
─────────────────────────────────

**wind_safety_rating** — surface/mean wind during productive hours including trend.

**IMPORTANT**: Do NOT rate the wind direction — direction is launchability (daily window), not safety. Wrong sector / wind shift is NOT a safety issue.
**FORBIDDEN**: rating ≤5 because of `[WIND-WRONG]`/wind shift — if the wind speed itself is green, minimum **7**.

Default-ideal {{cfg.WIND_IDEAL_MIN_KMH}}-{{cfg.WIND_IDEAL_MAX_KMH}} km/h. Too WEAK a wind is NOT a safety issue (the soaring minimum wind belongs to the flyability phase via `Rating-Regel Flug`) — here only too-strong/gusty wind counts. Apply the `Rating-Regel Sicherheit` from the data block (e.g. rotor in specific wind situations).
- 1: Stormy ({{cfg.WIND_DANGER_KMH}}+ km/h), building trend
- 5: Borderline (>{{cfg.WIND_WARN_KMH}} km/h OR building OR a weather trigger from `Rating-Regel Sicherheit` active)
- 10: In the ideal range, steady all day

**gust_safety_rating** — gust factor + gust peaks during productive hours including trend.
- 1: Extreme gusts, factor >2.0, peaks >{{cfg.GUST_DANGER_KMH}} km/h, or GUST-DANGER tags
- 5: Active: factor 1.5-1.7, peaks from {{cfg.GUST_WARN_KMH}} km/h OR gusts building
- 10: Calm: factor <1.3, no peaks >25 km/h

**aloft_safety_rating** — upper-level wind 700-850 hPa. Can indicate the onset of foehn.
- 1: Upper-level storm: ALOFT-NOT-SAFE or several ALOFT-DANGER
- 5: Elevated: ALOFT-CONDITIONAL OR a clear building trend
- 10: Weak, no aloft tags, steady

**foehn_safety_rating** — synoptic risk from ΔP + inflow + trigger. At `foehn_risk=high` the engine auto-sets `not_safe`. At `moderate` you distinguish "mildly moderate" vs "almost danger".
- 1: Acute breakthrough (high) or clearly imminent
- 5: Caution (moderate) OR build-up detectable
- 10: No foehn situation

**rain_safety_rating** — precipitation during flying hours + trend.
- 1: Boxed in (rain before AND after the window, <3h dry → always 1, ≥4h → 1-2)
- 5: Late rain (after mid-window, pilot lands safely) OR clearing (rain ends before the window starts)
- 10: No precipitation

**thunderstorm_safety_rating** — model thunderstorm forecast. A day with a thunderstorm tops out at **4** — a thunderstorm is never compatible with `safe`.
- 1: Thunderstorm building/within the window OR boxed in
- 4: Evening only (well after the window) OR clearing (before the window)
- 10: No signs of thunderstorms

**cape_safety_rating** — CAPE over the course of the day. 800 J/kg = elevated, 1500 J/kg = extreme instability.
- 1: CAPE >1500 J/kg building OR active during the window
- 5: CAPE 800-1500 J/kg with precipitation OR >1500 with clearing before the window
- 10: CAPE <800 J/kg

**visibility_safety_rating** — cloud base at/below launch altitude (cloud-entry risk). Mid/high clouds are not a safety issue.
- 1: Base steady at/below launch OR sinking during the window
- 5: Base lifting, clearing in progress
- 10: Base clearly above launch

─────────────────────────────────
USAGE RULES
─────────────────────────────────

**Fill in `hazard_notes` FIRST** (before ratings + prose). One concrete sentence per field — this is your structured reasoning. Examples:
- `"wind": "INCREASING — 12 km/h in the morning, building to 40 km/h from 14h, WIND-DANGER 14-17h."` → wind 2
- `"wind": "STEADY — 15-20 km/h all day."` → wind 8
- `"foehn": "BUILDING — ΔP 4.2→7.8 hPa south until 14h, 850 hPa 38 km/h south."` → foehn 2
- `"foehn": "NO-FOEHN — ΔP <2 hPa."` → foehn 10
- `"rain": "CLEARING — rain 08-09h, dry from 10h."` → rain 8
- `"rain": "BOXED-IN — rain 07-09h + 16-18h, dry window 7h."` → rain 3
- `"thunderstorm": "EVENING-ONLY — from 19h, after the window closes."` → thunderstorm 6
- `"cape": "BUILDING — CAPE 1200 J/kg 14-16h with active precipitation."` → cape 3

FORBIDDEN: generic placeholders ("unremarkable" with no reference), empty strings.

**When `safety_status = not_safe`**: set all 8 to `1`. Otherwise contradictions in the UI ("red, but wind 8/10").

**When `safety_status = conditional`**: typically at least one rating 3-6, others can be 7-8 (e.g. foehn caution in otherwise calm weather).

─────────────────────────────────
CONSISTENCY REQUIREMENT (HARD)
─────────────────────────────────

`safety_status`, the 8 sub-ratings AND the prose MUST form a consistent picture. The engine checks via `SubRatingFloor` and corrects (corrections = bug signal in telemetry).

**Rule 1** — sub-ratings bind the status:
- `min(subs) ≤ 2` → `safety_status` MUST be `not_safe`
- `min(subs) ≤ 3` → MUST be at least `conditional`
- At `safety_status = safe`, ALL 8 MUST be ≥ 4

**Rule 2** — prose must match the status. **Sentence 1** of the reasoning follows the reasoning principle in `03_status_derivation.md`.

**Consequence**: Read the sub-ratings before finalizing. If one is ≤3, correct `safety_status` AND the prose. NOT permitted: low sub-rating + `safe` status + "safe day" prose.
