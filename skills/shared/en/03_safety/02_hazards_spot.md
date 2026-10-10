═══════════════════════════════════════════════
CORE RULE — hour classification
═══════════════════════════════════════════════

Every hour:
- **CALM** — no WARN/DANGER tags
- **SPORTY** — ≥1 WARN tag (WIND/ALOFT-WIND/GUST/ALOFT-GUST/CAPE), no DANGER
- **UNFLYABLE** — ≥1 DANGER tag (RAIN-WARN, WIND/ALOFT-WIND/GUST/ALOFT-GUST-DANGER, CAPE-DANGER, THUNDERSTORM, OVERCAST-DANGER)

**Day-window layer** (see `_tagesfenster.md`): The data block only contains hours from day start onwards. Assess safety only **within** the active day.

**"Clean hour" (safety)** = not UNFLYABLE. `[WIND-WRONG]` plays no role here.
**"Clean window"** = consecutive clean hours within the active day.

**`safe_window`:**
- = flyable hours (CALM + SPORTY), regardless of wind direction.
- SPORTY hours MUST appear in `caution_notes` with time + reason.
- NEVER put UNFLYABLE hours in the `safe_window`. `[WIND-WRONG]` does NOT interrupt the window.

═══════════════════════════════════════════════
TREND VOCABULARY (7 patterns)
═══════════════════════════════════════════════

Every hazard block (rain, wind, gusts, upper wind, CAPE, clouds) follows one of these patterns. Foehn = exception (severity-based across the board, Block 5).

1. **`AUFKLAERUNG`** (clearing) — hazard in the morning, moves out → assess clean hours normally, **safe**/**conditional**.
2. **`ZUNEHMEND`** (increasing) — starts calm, builds up → max **conditional**, `safe_window` on the morning.
3. **`EINGEKESSELT`** (boxed in) — clean window between two hazard phases → see next section.
4. **`DURCHGEHEND` (WARN)** (persistent) — ≥75% WARN, no DANGER → **conditional** (sporty).
5. **`DURCHGEHEND` (DANGER)** — ≥75% DANGER → **not_safe**.
6. **`VEREINZELT`** (isolated) — isolated hazard hours → mostly **conditional**, time in `caution_notes`.
7. **`STABIL`** (stable) — consistently calm → no status effect. Only in `caution_notes` if it is an active all-clear or descriptive.

─────────────────────────────────
`EINGEKESSELT` — 3 questions
─────────────────────────────────

**Question 1 — Severity OUTSIDE:** WARN level → starting point `conditional`. DANGER → `not_safe`.

**Question 2 — Window length (CALM + SPORTY consecutive):**
- **< 3h** → one level stricter
- **3-4h** → starting point stays
- **≥ 4h** → DANGER starting point may go to `conditional` (pilot lands ≥30 min before the return)

**Question 3 — Window INSIDE:** Continuously CALM → full size counts. Interspersed with SPORTY hours → compute effective size (4h, 2h SPORTY = effectively 2h), one level stricter.

─────────────────────────────────
`EINGEKESSELT` — decisions + special cases
─────────────────────────────────

- **WARN outside** → at least `conditional`. Extreme combination (<3h AND interspersed with SPORTY) → `not_safe`.
- **DANGER outside + ≥4h + CALM inside** → `conditional`, pilot lands before the return.
- **DANGER outside + 3-4h + CALM inside** → `conditional` borderline. With additional risks → `not_safe`.
- **DANGER outside + <3h** OR **DANGER outside + interspersed with SPORTY** → `not_safe`, `primary_no_go = EINGEKESSELT`.

**Special case 1 — Upper wind:** Second hazard phase worse than the first (escalating) → one level stricter. Symmetric → rule applies 1:1.

**Special case 2 — Ground hazards (ground gusts, ground wind, rain):** Stricter thresholds, since the landing is directly affected.
- **<5h** → always `not_safe`, even with CALM inside.
- **≥5h + CALM inside** → `conditional` possible (land ≥90 min before the return).
- **≥5h + interspersed with SPORTY** → `not_safe`.

═══════════════════════════════════════════════
7 HAZARD BLOCKS
═══════════════════════════════════════════════

─────────────────────────────────
BLOCK 1 — RAIN & FRONT
─────────────────────────────────

`[RAIN-WARN]` → hour UNFLYABLE (counts directly as DANGER, no WARN split). Affects the landing → **Special case 2** for `EINGEKESSELT`.

A clean window between rain phases is NOT automatically safe — the trend pattern determines the status.

─────────────────────────────────
BLOCK 2 — GROUND WIND
─────────────────────────────────

**Tags (spots + regions):**
- No tag (< {{cfg.WIND_WARN_KMH}} km/h) → calm
- `[WIND-WARN]` → sporty ({{cfg.WIND_WARN_KMH}}-{{cfg.WIND_DANGER_KMH}} km/h)
- `[WIND-DANGER]` → unflyable (> {{cfg.WIND_DANGER_KMH}} km/h, real flight hazard)

Filter tags `[WIND-OK]`/`[WIND-WRONG]` are handled separately in `_tagesfenster.md` — they are NOT hazards.

**Trend:** Ground wind + upper wind share the `WIND-TREND` line (same thresholds). No separate ground-wind trend. Mapping see Block 4.

**Safety window rule (mandatory):** A day can have several windows. **The day status counts the longest one** (`Laengstes Fenster: Xh` (longest window) in the `TAGESPROFIL` (day profile)).
- **≥ {{cfg.CLEAN_WINDOW_MIN_HOURS}}h** consecutively clean → `safe`/`conditional` possible.
- **< {{cfg.CLEAN_WINDOW_MIN_HOURS}}h** → `not_safe`.

"Consecutive" = directly following one another. A DANGER hour in between splits the window (`[WIND-WRONG]` does NOT split it). The system provides the numbers — do not recount them yourself.

─────────────────────────────────
BLOCK 3 — GUSTS (ground + aloft, spots only)
─────────────────────────────────

**Tags (same thresholds):**
- `[GUST-WARN]`/`[ALOFT-GUST-WARN]` → sporty. Day at least `conditional` if ≥3h.
- `[GUST-DANGER]`/`[ALOFT-GUST-DANGER]` → DANGER level (> {{cfg.GUST_DANGER_KMH}} km/h). No auto no-go — the LLM decides based on trend + window.

**GROUNDING (MANDATORY):** Gust statements are ONLY allowed if the `TAGESPROFIL` line `Hauptgefahren am Tag:` (main hazards of the day) explicitly shows `GUST-WARN/DANGER Nh` or `ALOFT-GUST-WARN/DANGER Nh` with N≥1. Otherwise do not invent km/h values — use `max_surface_gust` from the data block.

**GUST FLOOR (system-enforced):** If `→ BOEEN-FLOOR (hart, System-erzwungen): MINDEST-STATUS = 'conditional'` (gust floor, hard, system-enforced: minimum status):
- `safety_status` MUST be at least `conditional` (never `safe`).
- `caution_notes` MUST contain a gust sentence with a concrete number.
- Also applies with weak base wind (large gust excess = turbulence signal).

**GUST-TREND mapping** (ground + aloft combined):
- **`DURCHGEHEND_DANGER`** → preferably `not_safe`, `primary_no_go = STARKE_BOEEN`. Only with a clearly clean 4h+ `AUFKLAERUNG` → `conditional` possible.
- **`EINGEKESSELT` with DANGER + window <{{cfg.WIND_TREND_NOTSAFE_HOURS}}h** → preferably `not_safe` (Special case 2, ground).
- **`DURCHGEHEND_WARN` / `EINGEKESSELT_KNAPP` / `VEREINZELT`** → max `conditional`.
- **`AUFKLAERUNG`** → clean hours as normal, `conditional` is sufficient.

**Hour guidelines:**
- `[GUST-DANGER]` ≥3h → preferably `not_safe` except `AUFKLAERUNG` with a clean window.
- `[GUST-WARN]` ≥3h → at least `conditional`. Persistent WARN is NOT `not_safe`, only sporty.

**Gust spread:** A large difference wind ↔ gusts = turbulence indicator, mention it even without a tag.

─────────────────────────────────
BLOCK 4 — UPPER WIND (FLIGHT LAYER)
─────────────────────────────────

**Tags** (only for altitudes with marker `*` in the flight range):
- `[ALOFT-WIND-DANGER]` → unflyable. **From {{cfg.WIND_TREND_NOTSAFE_HOURS}}h/day (or ground wind > {{cfg.WIND_DANGER_KMH}} km/h ≥{{cfg.WIND_TREND_NOTSAFE_HOURS}}h) → hard NO-GO** (post-processing forces `not_safe`). EXCEPT if `WIND-TREND` shows `AUFKLAERUNG`/`VEREINZELT`/`EINGEKESSELT_KNAPP` with window ≥{{cfg.WIND_TREND_NOTSAFE_HOURS}}h → max `conditional`.
- `[ALOFT-WIND-WARN]` → sporty.
- `[ALOFT-GUST-WARN/DANGER]` → see Block 3 (spots only).

**Regions:** Only ALOFT-WIND-* and WIND-*. No gust tags at region level.

**Buffer zone (`~`, 500m above the flight range):**
- Gusts >50 km/h there → `caution_notes` ("sharp upper-level storm directly above the thermal top").
- Buffer calmer than the flight layer → all-clear.

**WIND-TREND mapping** (ground wind + upper wind combined):
- **`DURCHGEHEND_DANGER`** → `not_safe`, `primary_no_go = WIND_DANGER`.
- **`DURCHGEHEND_WARN`** → max `conditional`, WARN character in `caution_notes` without inventing km/h.
- **`EINGEKESSELT (mit DANGER)` + window <{{cfg.WIND_TREND_NOTSAFE_HOURS}}h** → `not_safe`, `primary_no_go = EINGEKESSELT-WIND`.
- **`EINGEKESSELT` (WARN) / `EINGEKESSELT_KNAPP`** → max `conditional`, time window in `caution_notes`.
- **`AUFKLAERUNG`** → NOT `not_safe`, even with DANGER in the morning. `safe_window` on the window afterwards.
- **`ZUNEHMEND`** → max `conditional`, `safe_window` on the calm morning.
- **`VEREINZELT`** → with DANGER hours max `conditional`.

The trend line gives pattern + facts — **you** derive the status, do not copy ready-made sentences.

**Vertical wind veering:** veers within the vertical column → shear → in `wind_shear`, rather `conditional`.

**With a clear deterioration trend without hard tags** (wind 30+ and rising, foehn indications, sharp buffer wind): you MUST set `conditional`/`not_safe` with a justification. Conversely: 850/700 brutal but flight range calm → no safety problem.

─────────────────────────────────
BLOCK 5 — FOEHN
─────────────────────────────────

**Exception:** Severity-based across the board, NO trend, NO window concept. Foehn is a property of the air mass.

**Direction check FIRST:**
- Spot has `Kritischer Foehn: Sued | Nord | Beide` (critical foehn: south | north | both).
- `Sued` = north of the main Alpine ridge → only south foehn triggers the alert.
- `Nord` = south of it → only north foehn.
- North foehn does NOT affect the Swiss Plateau/Jura/northern Pre-Alps (they get cold Bise).
- Indicator `nicht kritisch` (not critical) or `Kein Foehn` (no foehn) → `foehn_risk = "none"`, ignore.

**Severity (only if the direction matches):**
- ΔP < 4 hPa → `foehn_risk = "none"`, no status influence.
- ΔP 4-7 hPa → `foehn_risk = "moderate"`, max `conditional`, foehn in `caution_notes` with ΔP.
- ΔP ≥ 8 hPa → `foehn_risk = "high"`, `not_safe`, `primary_no_go = FOEHN`.

**Hidden foehn** (even with low ΔP):
- Upper wind (850/700 hPa) strong, ground wind weak — ratio > 3:1.
- 850 hPa > {{cfg.WIND_DANGER_KMH}} km/h with ground wind < 10 km/h.
- Upper-wind direction MUST be the foehn direction.
- With hidden foehn: at least `conditional` with a justification.

─────────────────────────────────
BLOCK 6 — CONVECTION / OVERDEVELOPMENT
─────────────────────────────────

**Keep strictly separate — do not lump together as "thunderstorm":**

- `[THUNDERSTORM]` → model forecasts a thunderstorm (weather_code 95/96/99).
  - Within the flight window ({{cfg.FLIGHT_HOURS_START}}-{{cfg.FLIGHT_HOURS_END}}h) → `not_safe`, `primary_no_go = GEWITTER`.
  - At/after the end of the window + clean hours before → max `conditional`, `safe_window` on the calm morning, thunderstorm in `caution_notes`. NO `not_safe` solely because of an evening thunderstorm.
  - In `summary` as **"thunderstorm"** with time.

- `[CAPE-DANGER]` → unflyable. CAPE > {{cfg.CAPE_DANGER_JKG}} J/kg OR CAPE + active rain.
  → `not_safe`, **"overdevelopment risk"** / "active overdevelopment" — NOT "thunderstorm". `primary_no_go = UEBERENTWICKLUNG`.

- `[CAPE-WARN]` → CAPE > {{cfg.CAPE_WARN_JKG}} J/kg without precipitation/lightning.
  → max `conditional` (NOT `not_safe` solely because of CAPE-WARN). `caution_notes`: "overdevelopment possible" with time + CAPE value. CAPE-WARN hours may go into the `safe_window`.

─────────────────────────────────
BLOCK 7 — CLOUDS & VISIBILITY
─────────────────────────────────

- `[OVERCAST-DANGER]` → unflyable (dense cover close to flight altitude, cloud-entry risk).

**Cloud base:** < launch altitude → LAUNCH BAN. < 1000m MSL critical. Rule of thumb: base > 1000m above launch = unproblematic.

**Cloud cover differentiation:**
- **High (cirrus)**: no safety risk (base 6000-10'000m).
- **Mid (altostratus)**: usually no safety risk (base 3000-6000m).
- **Low**: check the base! A few hundred metres above launch → hazard.

Cloud cover reduces thermals → flyability topic (Part 2), NOT a safety topic.
