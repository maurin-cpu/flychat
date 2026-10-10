═══════════════════════════════════════════════
HAZARD TAGS (safety signals, phase 1)
═══════════════════════════════════════════════

Each hour carries one or more of these tags in square brackets. They are the **only** tags allowed to influence safety_status, safe_window, no_go_reasons and sub-ratings.

**Hard no-go tags = DANGER level** (hour becomes UNFLYABLE, NEVER belongs in the safe_window):
- `[RAIN-WARN]` — precipitation ≥ 0.05 mm/h
- `[WIND-DANGER]` — surface wind > {{cfg.WIND_DANGER_KMH}} km/h
- `[ALOFT-WIND-DANGER]` — upper wind in the flight layer > {{cfg.WIND_DANGER_KMH}} km/h (auto no-go trigger from {{cfg.WIND_TREND_NOTSAFE_HOURS}}h/day with `DURCHGEHEND_DANGER` (continuous danger) trend)
- `[GUST-DANGER]` — surface gusts > {{cfg.GUST_DANGER_KMH}} km/h *(spots only)*
- `[ALOFT-GUST-DANGER]` — turbulence in the flight layer > {{cfg.GUST_DANGER_KMH}} km/h *(spots only)*
- `[THUNDERSTORM]` — model forecasts thunderstorm (weather_code 95/96/99)
- `[CAPE-DANGER]` — CAPE > {{cfg.CAPE_DANGER_JKG}} J/kg OR CAPE + rain active
- `[OVERCAST-DANGER]` — dense cloud cover close to flying altitude

**Soft caution tags = WARN level** (hour becomes SPORTY, stays flyable for experienced pilots, status at least conditional):
- `[WIND-WARN]` — surface wind {{cfg.WIND_WARN_KMH}}-{{cfg.WIND_DANGER_KMH}} km/h
- `[ALOFT-WIND-WARN]` — upper wind in the flight layer {{cfg.WIND_WARN_KMH}}-{{cfg.WIND_DANGER_KMH}} km/h
- `[GUST-WARN]` — surface gusts elevated (WARN level) *(spots only)*
- `[ALOFT-GUST-WARN]` — turbulence in the flight layer elevated (WARN level) *(spots only)*
- `[CAPE-WARN]` — CAPE elevated (WARN level) without trigger

**Direction tags (spot mode) — own category day window, see `_tagesfenster.md`:**
- `[WIND-OK]` — wind direction within the allowed spot sector (incl. 10° buffer).
- `[WIND-WRONG]` — wind direction outside the sector. **No hazard, no status effect.** In the data block you only see these tags **after** the day start (wind shift during the day — landing aspect, not a safety signal).

**Region mode:** Regions have no sector and no gusts, only wind strength at reference altitude. The tags are the same as for spots:
- No tag (wind < {{cfg.WIND_WARN_KMH}} km/h) → CALM
- `[WIND-WARN]` — wind {{cfg.WIND_WARN_KMH}}-{{cfg.WIND_DANGER_KMH}} km/h → SPORTY
- `[WIND-DANGER]` — wind > {{cfg.WIND_DANGER_KMH}} km/h → UNFLYABLE

═══════════════════════════════════════════════
HOUR CLASSIFICATION (flight hazard)
═══════════════════════════════════════════════

- `CALM` = NO hazard tags = comfortable.
- `SPORTY` = ≥1 WARN tag, NO DANGER = flyable for experienced pilots.
- `UNFLYABLE` = ≥1 DANGER tag (RAIN-WARN, WIND-DANGER, ALOFT-WIND-DANGER, GUST-DANGER, ALOFT-GUST-DANGER, THUNDERSTORM, CAPE-DANGER, OVERCAST-DANGER).

`[WIND-WRONG]` is NOT DANGER and NOT a hazard — see `_tagesfenster.md`.

- **Clean hour** = not UNFLYABLE + for spots additionally `[WIND-OK]`. The only kind of hour in which a pilot can launch safely.
- `safe_window` = continuous block of clean hours within the active day.
