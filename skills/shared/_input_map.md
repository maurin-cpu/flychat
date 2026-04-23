═══════════════════════════════════════════════
INPUT-KARTE — WIE LIEST DU DEN DATENBLOCK?
═══════════════════════════════════════════════

Der User-Block liefert dir drei Zonen: **Stunden-Zeilen**, **Drucklevel-Werte** und den **TAGESPROFIL-Block** am Ende. Lerne diese zuerst — danach kannst du die Regeln anwenden.

─────────────────────────────────
A) STUNDEN-ZEILEN (Bodendaten + Tags)
─────────────────────────────────

Pro Stunde bekommst du eine Zeile mit Bodenwind, Bewoelkung, Niederschlag, CAPE, Wolkenbasis — und eine Liste von **Tags** in eckigen Klammern. Im Spot-Kontext enthaelt die Zeile zusaetzlich Boeen (Turbulenzrisiko). Im Region-Kontext gibt es **keine Boeen-Werte** (Apr 2026 Refactor) — nur Windstaerke.

**Harte No-Go-Tags = DANGER-Level** (Stunde wird UNFLIEGBAR, gehoert NIEMALS ins safe_window):
- `[RAIN-WARN]` — Niederschlag ≥ 0.05 mm/h
- `[GUST-DANGER]` — Bodenboeen > {{cfg.GUST_DANGER_KMH}} km/h *(nur Spots)*
- `[ALOFT-DANGER]` — Wind in Flugschicht > {{cfg.ALOFT_DANGER_KMH}} km/h (= NO-GO-Trigger ab {{cfg.ALOFT_DANGER_NOTSAFE_HOURS}}h/Tag)
- `[ALOFT-GUST-DANGER]` — Turbulenz in Flugschicht > {{cfg.ALOFT_GUST_DANGER_KMH}} km/h *(nur Spots)*
- `[STRONG-WIND-WARN]` — Grundwind ueber Spot-Maximum *(nur Spots)*
- `[THUNDERSTORM]` — Modell sagt Gewitter (weather_code 95/96/99)
- `[CAPE-DANGER]` — CAPE > {{cfg.CAPE_DANGER_JKG}} J/kg ODER CAPE + Regen aktiv
- `[OVERCAST-DANGER]` — Dichte Wolkendecke nahe Flughoehe

**Weiche Vorsichts-Tags = WARN-Level** (Stunde wird SPORTLICH, bleibt fliegbar fuer erfahrene Piloten, Status mind. conditional):
- `[GUST-WARN]` — Bodenboeen {{cfg.GUST_WARN_KMH}}-{{cfg.GUST_DANGER_KMH}} km/h *(nur Spots)*
- `[ALOFT-WARN]` — Flugschicht-Wind {{cfg.ALOFT_WARN_KMH}}-{{cfg.ALOFT_DANGER_KMH}} km/h (sportlich, noch fliegbar)
- `[ALOFT-GUST-WARN]` — Flugschicht-Turbulenz {{cfg.ALOFT_GUST_WARN_KMH}}-{{cfg.ALOFT_GUST_DANGER_KMH}} km/h *(nur Spots)*
- `[CAPE-WARN]` — CAPE {{cfg.CAPE_WARN_JKG}}-{{cfg.CAPE_DANGER_JKG}} J/kg ohne Trigger

**Richtungs-Tags (Spot-Modus):**
- `[WIND-OK]` — Windrichtung liegt im erlaubten Spot-Sektor (inkl. 10° Buffer)
- `[WIND-WRONG]` — Windrichtung ausserhalb des Spot-Sektors → Stunde UNFLIEGBAR

**Magnitude-Tags (Region-Modus):** Regionen haben keinen Sektor und keine Boeen, nur Wind-Staerke auf Referenzhoehe.
- `[WIND-CALM]` — Wind < {{cfg.WIND_MODERATE_KMH}} km/h → RUHIG
- `[WIND-MODERATE]` — Wind {{cfg.WIND_MODERATE_KMH}}-{{cfg.WIND_STRONG_KMH}} km/h → SPORTLICH (= WARN-Level fuer Regionen)
- `[WIND-STRONG]` — Wind > {{cfg.WIND_STRONG_KMH}} km/h → UNFLIEGBAR (= DANGER-Level fuer Regionen)

**Stunden-Klassifikation** (siehe KERNREGEL in `_hazard_blocks.md`):
- `RUHIG` = Windrichtung passt + KEINE Tags = komfortabel.
- `SPORTLICH` = Windrichtung passt + ≥1 WARN-Tag, KEIN DANGER = fliegbar erfahren.
- `UNFLIEGBAR` = ≥1 DANGER-Tag ODER Windrichtung falsch.
- "Sauber" = RUHIG ODER SPORTLICH. `safe_window` = sauberes Fenster.

**Thermik-Qualitaets-Tags** (gelten NUR fuer Teil 2 Fliegbarkeit, NIE fuer Sicherheit):
- `[SHEAR-DEGRADED]` / `[SHEAR-UNUSABLE]` — Windscherung: Wind dreht/beschleunigt mit Hoehe, Blase wird gekippt (Spot + Region).
- `[THERMAL-TORN-DEGRADED]` / `[THERMAL-TORN-UNUSABLE]` — Buoyancy/Shear-Ratio schlecht: Auftrieb zu schwach gegenueber Scherung, Blase zerrissen (Spot + Region).
- `[THERMAL-ROUGH-DEGRADED]` / `[THERMAL-ROUGH-UNUSABLE]` — ruppige Thermik durch Boeigkeit (Gust-Factor) *(nur Spots — braucht Boeen)*.
- `[THERMAL-WIND-DEGRADED]` / `[THERMAL-WIND-UNUSABLE]` — mittlerer Grundwind durch die Mischungsschicht zu stark, Blase organisiert sich nicht (Spot + Region). Quelle: BL-Mean-Wind gegen zone-abhaengige Schwelle (Research Abschnitt 3.1).

─────────────────────────────────
B) DRUCKLEVEL-WERTE (Flugschicht-Zeile)
─────────────────────────────────

Format: `pressure(altitude_m)MARKER: wind/boeen km/h aus dir°`

**Marker verstehen:**
- `*` = **Flugbereich** (Spot-Hoehe bis Thermik+1000m, inkl. Lid-Zone) — HIER feuern die [ALOFT-*]-Tags. Trend-Bewertung ({{cfg.ALOFT_WARN_KMH}}-{{cfg.ALOFT_DANGER_KMH}} km/h steigend = WARN, > {{cfg.ALOFT_DANGER_KMH}} km/h = DANGER) gilt voll.
- `~` = **Buffer-Zone** (500m ueber dem Flugbereich) — KEINE harten Tags, aber wenn dort Boeen > 50 km/h: Hinweis in `caution_notes` ("scharfer Hoehensturm direkt ueber Thermikspitze"). Wenn Buffer ruhiger als Flugbereich: Entwarnung.
- **Kein Marker** = nur 850/700 hPa als Foehn-Anker. Fuer direkte Sicherheit irrelevant ausser als Foehn-Indikator.

─────────────────────────────────
C) TAGESPROFIL-Block (am Ende des Datenblocks)
─────────────────────────────────

Hier hat das System bereits alles gezaehlt und geflagged:

- `Verhaeltnis sauber/gesamt: X/Yh = Z%` — Anteil sauberer Stunden (RUHIG + SPORTLICH) im Flugfenster
- `Hauptgefahren am Tag: GUST-DANGER 4h, ALOFT-DANGER 2h, ...` — Histogramm der Gefahren (Regionen: ohne GUST-* Eintraege)
- `→ PRODUKTIVE-THERMIK: Nh` — produktive Thermikstunden (Climb ≥{{cfg.PRODUCTIVE_CLIMB_MIN}} + tief <{{cfg.PRODUCTIVE_LOW_CLOUD_MAX}}% + mittel <{{cfg.PRODUCTIVE_MID_CLOUD_MAX}}% + kein ROUGH-UNUSABLE + kein WIND-UNUSABLE). Regionen: ROUGH-UNUSABLE-Kriterium faellt weg (keine Boeen), aber WIND-UNUSABLE ist Pflicht-Filter.
- `→ BOEEN-FLOOR: MINDEST-STATUS = 'conditional'` oder `'not_safe'` — vom System **erzwungener** Mindeststatus (nicht verhandelbar!) *(nur Spots)*
- `→ ACHTUNG Verhaeltnis < 35%: ...` — optionaler Warnhinweis
- `THERMIK-QUALITAET-Block`: Zaehler fuer SHEAR/TORN/ROUGH-UNUSABLE-Stunden + TQ-Ratio pro Stunde (Regionen: kein ROUGH)
- **Trend-Labels (falls vorhanden):** AUFKLAERUNG / ZUNEHMEND / EINGEKESSELT / DURCHGEHEND (WARN/DANGER) / VEREINZELT / STABIL — vollstaendige Definitionen siehe TREND-VOKABULAR in `_hazard_blocks.md`. Wende sie pro Gefahrenblock an (Regen, Bodenwind, Boeen, Hoehenwind, CAPE, Wolken). Foehn ist ausgenommen (severity-pauschal, kein Trend).

**Deine Pflicht:** Diese Werte lesen, nicht selber berechnen. Wenn BOEEN-FLOOR steht, ist das verbindlich. Wenn "Verhaeltnis < 35%" steht, MUSS das in `caution_notes` oder `no_go_reasons`.
