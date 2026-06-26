═══════════════════════════════════════════════
HAZARD-TAGS (Sicherheits-Signale, Phase 1)
═══════════════════════════════════════════════

Pro Stunde stehen ein oder mehrere dieser Tags in eckigen Klammern. Sie sind die **einzigen** Tags, die safety_status, safe_window, no_go_reasons und Sub-Ratings beeinflussen duerfen.

**Harte No-Go-Tags = DANGER-Level** (Stunde wird UNFLIEGBAR, gehoert NIEMALS ins safe_window):
- `[RAIN-WARN]` — Niederschlag ≥ 0.05 mm/h
- `[WIND-DANGER]` — Bodenwind > {{cfg.WIND_DANGER_KMH}} km/h
- `[ALOFT-WIND-DANGER]` — Hoehenwind in Flugschicht > {{cfg.WIND_DANGER_KMH}} km/h (Auto-NoGo-Trigger ab {{cfg.WIND_TREND_NOTSAFE_HOURS}}h/Tag bei DURCHGEHEND_DANGER-Trend)
- `[GUST-DANGER]` — Bodenboeen > {{cfg.GUST_DANGER_KMH}} km/h *(nur Spots)*
- `[ALOFT-GUST-DANGER]` — Turbulenz in Flugschicht > {{cfg.GUST_DANGER_KMH}} km/h *(nur Spots)*
- `[THUNDERSTORM]` — Modell sagt Gewitter (weather_code 95/96/99)
- `[CAPE-DANGER]` — CAPE > {{cfg.CAPE_DANGER_JKG}} J/kg ODER CAPE + Regen aktiv
- `[OVERCAST-DANGER]` — Dichte Wolkendecke nahe Flughoehe

**Weiche Vorsichts-Tags = WARN-Level** (Stunde wird SPORTLICH, bleibt fliegbar fuer erfahrene Piloten, Status mind. conditional):
- `[WIND-WARN]` — Bodenwind {{cfg.WIND_WARN_KMH}}-{{cfg.WIND_DANGER_KMH}} km/h
- `[ALOFT-WIND-WARN]` — Hoehenwind in Flugschicht {{cfg.WIND_WARN_KMH}}-{{cfg.WIND_DANGER_KMH}} km/h
- `[GUST-WARN]` — Bodenboeen erhoeht (WARN-Level) *(nur Spots)*
- `[ALOFT-GUST-WARN]` — Turbulenz in der Flugschicht erhoeht (WARN-Level) *(nur Spots)*
- `[CAPE-WARN]` — CAPE erhoeht (WARN-Level) ohne Trigger

**Richtungs-Tags (Spot-Modus) — eigene Kategorie Tagesfenster, siehe `_tagesfenster.md`:**
- `[WIND-OK]` — Windrichtung im erlaubten Spot-Sektor (inkl. 10° Buffer).
- `[WIND-WRONG]` — Windrichtung ausserhalb des Sektors. **Kein Hazard, kein Status-Effekt.** Im Datenblock siehst du diese Tags nur **nach** Tagesbeginn (Wind-Dreh im Tagesverlauf — Lande-Aspekt, kein Sicherheits-Signal).

**Region-Modus:** Regionen haben keinen Sektor und keine Boeen, nur Wind-Staerke auf Referenzhoehe. Tags sind dieselben wie bei Spots:
- Kein Tag (Wind < {{cfg.WIND_WARN_KMH}} km/h) → RUHIG
- `[WIND-WARN]` — Wind {{cfg.WIND_WARN_KMH}}-{{cfg.WIND_DANGER_KMH}} km/h → SPORTLICH
- `[WIND-DANGER]` — Wind > {{cfg.WIND_DANGER_KMH}} km/h → UNFLIEGBAR

═══════════════════════════════════════════════
STUNDEN-KLASSIFIKATION (Flug-Gefahr)
═══════════════════════════════════════════════

- `RUHIG` = KEINE Hazard-Tags = komfortabel.
- `SPORTLICH` = ≥1 WARN-Tag, KEIN DANGER = fliegbar erfahren.
- `UNFLIEGBAR` = ≥1 DANGER-Tag (RAIN-WARN, WIND-DANGER, ALOFT-WIND-DANGER, GUST-DANGER, ALOFT-GUST-DANGER, THUNDERSTORM, CAPE-DANGER, OVERCAST-DANGER).

`[WIND-WRONG]` ist KEIN DANGER und KEIN Hazard — siehe `_tagesfenster.md`.

- **Saubere Stunde** = nicht UNFLIEGBAR + bei Spots zusaetzlich `[WIND-OK]`. Einzige Stundenart, in der ein Pilot sicher starten kann.
- `safe_window` = zusammenhaengender Block sauberer Stunden im aktiven Tag.
