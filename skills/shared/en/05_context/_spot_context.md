═══════════════════════════════════════════════
SPOT SPECIFICS: SECTOR + DAY WINDOW
═══════════════════════════════════════════════

In spot mode the launch site has an allowed **sector** (compass range). The directional tags `[WIND-OK]` / `[WIND-WRONG]` belong to their own category **day window** — see `_tagesfenster.md`. The code has already trimmed the data block to start at the first qualifying launch window.

**Clean hour (spot)** = `[WIND-OK]` AND no DANGER tag. Only clean hours belong in the `safe_window`. SPORTY hours (with a WARN tag inside) must be explicitly flagged there in `caution_notes` with the time.

**For flyability:** Only `[WIND-OK]` hours within the `safe_window` are relevant for the thermal / flight quality assessment.

═══════════════════════════════════════════════
SITE NOTES (override layer)
═══════════════════════════════════════════════

The data block contains **site notes** (e.g. "minimum wind 15 km/h for soaring", "risk of collapse with south-foehn congestion", "landing field closed in rain"). Site notes are spot-specific local knowledge and **override generic rules**. Treat them as a fine-tuning step — first assess normally, then apply the site note.

**Format in the data block**:
- `Bemerkung Flug: …`             — flight/quality-relevant raw text.
- `Rating-Regel Flug: …`          — the **operationalized rule** derived from it (condition → rating effect), directly below the note.
- `Bemerkung Sicherheit: …`       — safety-relevant raw text (obstacles, rotor/lee, closures, bans, required skill level).
- `Rating-Regel Sicherheit: …`    — the operationalized safety effect (WETTER-TRIGGER/STATISCH/SPERRE/… → caution/no_go/safe_window).

In the **safety phase**: process only `Bemerkung Sicherheit` + `Rating-Regel Sicherheit`.
In the **flyability phase**: process only `Bemerkung Flug` + `Rating-Regel Flug`.

**The `Rating-Regel` line is BINDING.** It removes the interpretation step: thresholds and effect are stated. You only check which hours in the data block meet the condition and apply the stated effect (caps/gates also hold against conflicting generic rating rules, see `_flight_subratings_spot.md` HARD LIMITS). If the `Rating-Regel` line is missing, operationalize the note yourself:

**Step 2 — EXTRACT (only if no Rating-Regel line is present):**
For each site-note trigger, identify: (a) parameter (wind/direction/precipitation/season/time of day/thermals), (b) threshold, (c) affected phase (launch/flight/landing/soaring/thermals), (d) which hours of the day trigger it in the current data block.

**Step 3 — FINE-TUNE: change only the affected fields, leave the rest**

| Affected aspect | Target field(s) |
|---|---|
| Launch ban / landing zone / ridge-soaring exclusion (SAFETY) | `no_go_reasons` (if whole day) or `caution_notes` (partial hours), shorten `safe_window`, possibly `primary_no_go` |
| Spot-specific turbulence/collapse (SAFETY/BOTH) | `caution_notes` with time, `wind_shear` or `wind_summary`, status at least `conditional` |
| Minimum wind for soaring not reached (FLYABILITY) | `flight_type = "Abgleiter"`, short `flight_duration_estimate`, `soaring_options` explains why, honest `recommendation`, `xc_potential = "low"`, cap `experience_rating` per `Rating-Regel Flug` (typically graded: just below minimum → cap 2-3, well below → 1) |
| Minimum wind reached → soaring possible (FLYABILITY) | `flight_type = "Soaring"` or `"Soaring+Thermik"`, `soaring_options` with a concrete assessment, `experience_rating = 1` (pure soaring counts as a sled ride; soaring possibility only in prose) |
| Thermal limitation (time of day/season, FLYABILITY) | `thermal_quality`, lower `peak_climb_rate` if needed, choose a correspondingly lower `experience_rating`, adjust `best_window` |
| `bemerkung_check` (flyability JSON) | ALWAYS: short summary of which site note applied and which fields were fine-tuned |

**Examples:**
- *Baldern, forecast 8-12 km/h, rating rule "soaring from 15 km/h; below 15 → cap 2-3, below 10 → 1"*: FLYABILITY. At 8 km/h (below 10 in most hours): `experience_rating=1`, `flight_type="Abgleiter"`, `xc_potential="low"`, `recommendation`: "Wind too weak for soaring at Baldern — sled ride possible." At 12 km/h: apply cap 2-3 — no matter how good the thermal inputs are. Safety fields unchanged.
- *Spot with "risk of collapse with south-foehn congestion", south foehn active*: BOTH. Safety → `caution_notes`, flyability → `thermal_quality` mentions broken thermals.
- *"Landing field closed in rain", RAIN-WARN hours*: SAFETY. → `no_go_reasons`, `safe_window` ends before the rain.
