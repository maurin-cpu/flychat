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
- `Bemerkung Flug: …`         — flight/quality-relevant notes (time of day, season, launch/landing logistics, wind specifics for flight quality).
- `Bemerkung Sicherheit: …`   — safety-relevant notes (obstacles, power lines, rotor/turbulence, closed landing fields, flight bans, nature reserves).

In the **safety phase**: process only `Bemerkung Sicherheit`.
In the **flyability phase**: process only `Bemerkung Flug`.

**Step 2 — EXTRACT:**
For each site-note trigger, identify: (a) parameter (wind/direction/precipitation/season/time of day/thermals), (b) threshold, (c) affected phase (launch/flight/landing/soaring/thermals), (d) which hours of the day trigger it in the current data block.

**Step 3 — FINE-TUNE: change only the affected fields, leave the rest**

| Affected aspect | Target field(s) |
|---|---|
| Launch ban / landing zone / ridge-soaring exclusion (SAFETY) | `no_go_reasons` (if whole day) or `caution_notes` (partial hours), shorten `safe_window`, possibly `primary_no_go` |
| Spot-specific turbulence/collapse (SAFETY/BOTH) | `caution_notes` with time, `wind_shear` or `wind_summary`, status at least `conditional` |
| Minimum wind for soaring not reached (FLYABILITY) | `flight_type = "Abgleiter"`, short `flight_duration_estimate`, `soaring_options` explains why, honest `recommendation`, `xc_potential = "low"`, `experience_rating = 1` |
| Minimum wind reached → soaring possible (FLYABILITY) | `flight_type = "Soaring"` or `"Soaring+Thermik"`, `soaring_options` with a concrete assessment, `experience_rating = 1` (pure soaring counts as a sled ride; soaring possibility only in prose) |
| Thermal limitation (time of day/season, FLYABILITY) | `thermal_quality`, lower `peak_climb_rate` if needed, choose a correspondingly lower `experience_rating`, adjust `best_window` |
| `bemerkung_check` (flyability JSON) | ALWAYS: short summary of which site note applied and which fields were fine-tuned |

**Examples:**
- *Balderen, forecast 8-12 km/h, site note "minimum wind 15 km/h for soaring"*: FLYABILITY. Override: `flight_type="Abgleiter"`, short duration, `xc_potential="low"`, `experience_rating=1`, `recommendation`: "Wind too weak for soaring at Balderen — sled ride possible." Safety fields unchanged.
- *Spot with "risk of collapse with south-foehn congestion", south foehn active*: BOTH. Safety → `caution_notes`, flyability → `thermal_quality` mentions broken thermals.
- *"Landing field closed in rain", RAIN-WARN hours*: SAFETY. → `no_go_reasons`, `safe_window` ends before the rain.
