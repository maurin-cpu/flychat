═══════════════════════════════════════════════
CORE RULE — Hour classification
═══════════════════════════════════════════════

Every hour:
- **CALM** — no WARN/DANGER tags
- **SPORTY** — ≥1 WARN tag (WIND, ALOFT-WIND, CAPE), no DANGER
- **UNFLYABLE** — ≥1 DANGER tag (RAIN-WARN, WIND/ALOFT-WIND-DANGER, CAPE-DANGER, THUNDERSTORM, OVERCAST-DANGER)

**Region has no sector** → LAUNCHABLE is given as long as `[WIND-DANGER]` does not apply.

**"Clean hour"** = not UNFLYABLE. **"Clean window"** = several consecutive clean hours.

**`safe_window`:**
- = flyable hours (CALM + SPORTY).
- SPORTY hours MUST appear in `caution_notes` with time + reason.
- UNFLYABLE hours NEVER go into `safe_window`.

═══════════════════════════════════════════════
TREND VOCABULARY (7 patterns)
═══════════════════════════════════════════════

Every hazard block (rain, wind, upper wind, CAPE, clouds) follows one of these patterns. Foehn = exception (flat by severity, Block 4).

1. **`AUFKLAERUNG`** (clearing) — hazard in the morning, moves out → clean hours normal, **safe**/**conditional**.
2. **`ZUNEHMEND`** (increasing) — starts calm, builds up → max **conditional**, `safe_window` on the morning.
3. **`EINGEKESSELT`** (boxed in) — clean window between two hazard phases → see next section.
4. **`DURCHGEHEND` (WARN)** (persistent) — ≥75% WARN, no DANGER → **conditional** (sporty).
5. **`DURCHGEHEND` (DANGER)** — ≥75% DANGER → **not_safe**.
6. **`VEREINZELT`** (isolated) — isolated hazard hours → usually **conditional**, time in `caution_notes`.
7. **`STABIL`** (stable) — consistently calm → no status effect. Only in `caution_notes` if an active all-clear or descriptive.

─────────────────────────────────
EINGEKESSELT — 3 questions
─────────────────────────────────

**Question 1 — Severity OUTSIDE:** WARN → starting point `conditional`. DANGER → `not_safe`.

**Question 2 — Window length (CALM + SPORTY consecutive):**
- **< 3h** → one level stricter
- **3-4h** → starting point stays
- **≥ 4h** → DANGER starting point may go to `conditional` (pilot lands ≥30 min before the hazard returns)

**Question 3 — Window INSIDE:** Continuously CALM → full size counts. Interspersed with SPORTY hours → compute effective size (4h, 2h SPORTY = effectively 2h), one level stricter.

─────────────────────────────────
EINGEKESSELT — Decisions + special cases
─────────────────────────────────

- **WARN outside** → at least `conditional`. Extreme combination (<3h AND interspersed with SPORTY) → `not_safe`.
- **DANGER outside + ≥4h + CALM inside** → `conditional`, pilot lands before the hazard returns.
- **DANGER outside + 3-4h + CALM inside** → `conditional` borderline. With additional risks → `not_safe`.
- **DANGER outside + <3h** OR **DANGER outside + interspersed with SPORTY** → `not_safe`, `primary_no_go = EINGEKESSELT`.

**Special case 1 — Upper wind:** Second hazard phase worse than the first (escalating) → one level stricter. Symmetric → rule 1:1.

**Special case 2 — Ground hazards (ground wind, rain):** Stricter thresholds.
- **<5h** → always `not_safe`, even if CALM inside.
- **≥5h + CALM inside** → `conditional` possible (land ≥90 min before the hazard returns).
- **≥5h + interspersed with SPORTY** → `not_safe`.

═══════════════════════════════════════════════
HAZARD BLOCKS (Region: 6 blocks, NO gusts)
═══════════════════════════════════════════════

─────────────────────────────────
BLOCK 1 — RAIN & FRONT
─────────────────────────────────

`[RAIN-WARN]` → hour UNFLYABLE (counts as DANGER). Affects the landing → **Special case 2** for EINGEKESSELT.

A clean window between rain phases is NOT automatically safe — the trend pattern determines the status.

─────────────────────────────────
BLOCK 2 — GROUND WIND (strength, no sector)
─────────────────────────────────

**Tags:**
- No tag (< {{cfg.WIND_WARN_KMH}} km/h) → calm
- `[WIND-WARN]` → sporty ({{cfg.WIND_WARN_KMH}}-{{cfg.WIND_DANGER_KMH}} km/h)
- `[WIND-DANGER]` → unflyable (> {{cfg.WIND_DANGER_KMH}} km/h)

**Trend:** Ground wind + upper wind share `WIND-TREND` (same thresholds). Mapping see Block 3.

The system provides the numbers — do not recount them yourself.

─────────────────────────────────
BLOCK 3 — UPPER WIND (FLIGHT LAYER)
─────────────────────────────────

**Tags** (only for altitudes marked `*` within the flight range):
- `[ALOFT-WIND-DANGER]` → unflyable. **From {{cfg.WIND_TREND_NOTSAFE_HOURS}}h/day (or ground wind > {{cfg.WIND_DANGER_KMH}} km/h for ≥{{cfg.WIND_TREND_NOTSAFE_HOURS}}h) → hard NO-GO** (post-processing forces `not_safe`). EXCEPT when `WIND-TREND` shows AUFKLAERUNG/VEREINZELT/EINGEKESSELT_KNAPP with a window ≥{{cfg.WIND_TREND_NOTSAFE_HOURS}}h → max `conditional`.
- `[ALOFT-WIND-WARN]` → sporty.

**WIND-TREND mapping** (ground wind + upper wind combined):
- **`DURCHGEHEND_DANGER`** (persistently dangerous) → `not_safe`, `primary_no_go = WIND_DANGER`.
- **`DURCHGEHEND_WARN`** (persistently elevated) → max `conditional`, WARN character in `caution_notes` without inventing km/h.
- **EINGEKESSELT (with DANGER) + window <{{cfg.WIND_TREND_NOTSAFE_HOURS}}h** → `not_safe`, `primary_no_go = EINGEKESSELT-WIND`.
- **EINGEKESSELT (WARN) / `EINGEKESSELT_KNAPP`** (narrowly boxed in) → max `conditional`, time window in `caution_notes`.
- **AUFKLAERUNG** → NOT `not_safe`, even with DANGER in the morning. `safe_window` on the window afterwards.
- **ZUNEHMEND** → max `conditional`, `safe_window` on the calm morning.
- **VEREINZELT** → with DANGER hours max `conditional`.

The trend line gives pattern + facts — **you** derive the status, do not copy ready-made sentences.

**Vertical wind veer:** turns within the vertical column → shear → in `wind_shear`, rather `conditional`.

**With a clear deterioration trend without hard tags** (wind 30+ and rising, foehn signs): you MUST set `conditional`/`not_safe` with reasoning. Conversely: 850/700 brutal but flight range calm → no safety problem.

─────────────────────────────────
BLOCK 4 — FOEHN
─────────────────────────────────

**Exception:** Flat by severity, NO trend, NO window concept. Foehn is a property of the air mass.

**Direction check FIRST** (see `_region_context.md`):
- Region has `Kritischer Foehn: Sued | Nord | Beide` (critical foehn: south | north | both).
- If the direction does not match: `foehn_risk = "none"`, ignore.

**Severity (only if the direction matches):**
- ΔP < 4 hPa → `foehn_risk = "none"`, no status effect.
- ΔP 4-7 hPa → `foehn_risk = "moderate"`, max `conditional`, foehn in `caution_notes` with ΔP.
- ΔP ≥ 8 hPa → `foehn_risk = "high"`, `not_safe`, `primary_no_go = FOEHN`.

**Hidden foehn** (even with low ΔP):
- Upper wind (850/700 hPa) strong, ground wind weak — ratio > 3:1.
- 850 hPa > {{cfg.WIND_DANGER_KMH}} km/h with ground wind < 10 km/h.
- Upper wind direction MUST be the foehn direction.
- With hidden foehn: at least `conditional` with reasoning.

─────────────────────────────────
BLOCK 5 — CONVECTION / OVERDEVELOPMENT
─────────────────────────────────

**Keep strictly separate — do not lump together as "thunderstorm":**

- `[THUNDERSTORM]` → model forecasts a thunderstorm (weather_code 95/96/99).
  - Within the flight window ({{cfg.FLIGHT_HOURS_START}}-{{cfg.FLIGHT_HOURS_END}}h) → `not_safe`, `primary_no_go = GEWITTER`.
  - At/after the window end + clean hours before → max `conditional`, `safe_window` on the calm morning, thunderstorm in `caution_notes`. NO `not_safe` solely because of an evening thunderstorm.
  - In `summary` as **"thunderstorm"** with time.

- `[CAPE-DANGER]` → unflyable. CAPE > {{cfg.CAPE_DANGER_JKG}} J/kg OR CAPE + rain active.
  → `not_safe`, **"overdevelopment risk"** — NOT "thunderstorm". `primary_no_go = UEBERENTWICKLUNG`.

- `[CAPE-WARN]` → CAPE > {{cfg.CAPE_WARN_JKG}} J/kg without precipitation/lightning.
  → max `conditional` (NOT `not_safe` on its own). `caution_notes`: "overdevelopment possible" with time + CAPE value. CAPE-WARN hours may go into `safe_window`.

─────────────────────────────────
BLOCK 6 — CLOUDS & VISIBILITY
─────────────────────────────────

- `[OVERCAST-DANGER]` → unflyable (dense cover close to flight altitude).

**Cloud base:** < 1000m MSL critical. Rule of thumb: base high enough above the region reference = unproblematic.

**Cloud cover differentiation:**
- **High (cirrus)**: no safety risk (base 6000-10'000m).
- **Mid (altostratus)**: usually no safety risk (base 3000-6000m).
- **Low**: check the base!

Cloud cover reduces thermals → a flyability topic (Part 2), NOT a safety topic.
