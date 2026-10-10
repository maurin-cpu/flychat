═══════════════════════════════════════════════
THERMAL QUALITY TAGS (phase 2 — flyability)
═══════════════════════════════════════════════

**Important:** The tags `[SHEAR-*]`, `[THERMAL-ROUGH-*]`, `[THERMAL-WIND-*]`
are **safety domain** — `[THERMAL-TORN-*]` is the **exception** (thermal quality).

**Safety domain ([SHEAR-*], [THERMAL-ROUGH-*], [THERMAL-WIND-*]):**
- **Do not mention** in `recommendation`, `thermal_quality` or
  `flyability_notes` — the pilot's assessment of flight quality is based on
  prod_h_strict, sustained_peak, working_height_agl and cloud_structure.
- **Do not use as justification** for a lower rating — gustiness (ROUGH),
  background wind (WIND) and pure shear (SHEAR) are safety/comfort topics.

**EXCEPTION [THERMAL-TORN-UNUSABLE] (shear tears the thermals apart):**
- **NAME it in `thermal_quality`/`flyability_notes`** — that the shear tears
  the core apart in N hours (not centerable) is thermal QUALITY, not a
  safety topic. Address it honestly, do not conceal it.
- **[THERMAL-TORN-DEGRADED]:** shear threatens to tear the core apart (borderline)
  — if significant, mention it as a caveat.
- **Effect on the rating is already priced in:** since the 10m anchor fix, TORN-UNUSABLE hours
  NO LONGER count in prod_h_strict/productive_thermal_h. The
  rating automatically follows the reduced number — **do NOT downgrade additionally**.
- **No raw wind/shear numbers** in the prose, only the consequence for the
  thermals (e.g. "shear tears the core apart from midday, hard to center").
