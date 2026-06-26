═══════════════════════════════════════════════
INPUT-FORMAT — WIE LIEST DU DEN DATENBLOCK?
═══════════════════════════════════════════════

Drei Zonen: **Stunden-Zeilen**, **Drucklevel-Werte**, **TAGESPROFIL-Block** am Ende.

═══════════════════════════════════════════════
DREI TAG-KATEGORIEN (kategorisch getrennt)
═══════════════════════════════════════════════

Jeder Tag in eckigen Klammern gehoert zu **genau einer**:

**KATEGORIE 1 — STARTBARKEITS-FILTER** (Spot only): `[WIND-OK]` / `[WIND-WRONG]`. Kein Hazard, kein Fliegbarkeits-Signal — eigene Kategorie **Tagesfenster** (siehe `_tagesfenster.md`).

**KATEGORIE 2 — HAZARD-TAGS** (Safety-Signale): siehe `_tags_safety.md`. Koennen Status druecken, in `caution_notes`/`no_go_reasons` landen, Sub-Ratings beeinflussen.

**KATEGORIE 3 — THERMIK-QUALITAETS-TAGS** (nur Fliegbarkeit): `[SHEAR-*]`, `[THERMAL-TORN-*]`, `[THERMAL-WIND-*]`, `[THERMAL-ROUGH-*]`. Siehe `_tags_flyability.md`.

─────────────────────────────────
A) STUNDEN-ZEILEN
─────────────────────────────────

Pro Stunde: Bodenwind, Bewoelkung, Niederschlag, CAPE, Wolkenbasis + Tags in eckigen Klammern. Spot-Kontext: zusaetzlich Boeen (Turbulenzrisiko). Region: KEINE Boeen.

─────────────────────────────────
B) DRUCKLEVEL-WERTE
─────────────────────────────────

Format: `pressure(altitude_m)MARKER: wind/boeen km/h aus dir°`

**Marker:**
- `*` = **Flugbereich** (Spot-Hoehe bis Thermik+1000m, inkl. Lid). [ALOFT-*]-Tags feuern hier. Schwellen: {{cfg.WIND_WARN_KMH}}-{{cfg.WIND_DANGER_KMH}} = WARN, > {{cfg.WIND_DANGER_KMH}} = DANGER.
- `~` = **Buffer-Zone** (500m ueber Flugbereich). Keine harten Tags. Boeen >50 km/h dort → Hinweis in `caution_notes`. Buffer ruhiger als Flugschicht → Entwarnung.
- **Kein Marker** = 850/700 hPa als Foehn-Anker. Nur als Foehn-Indikator relevant.

─────────────────────────────────
C) TAGESPROFIL-Block (am Ende)
─────────────────────────────────

System hat alles gezaehlt und geflagged:

- `Verhaeltnis sauber/gesamt: X/Yh = Z%` — Anteil sauberer Stunden (RUHIG + SPORTLICH)
- `Hauptgefahren am Tag: GUST-DANGER 4h, ALOFT-DANGER 2h, ...` — Histogramm (Regionen ohne GUST-*)
- `→ PRODUKTIVE-THERMIK: Nh` — Climb ≥{{cfg.PRODUCTIVE_CLIMB_MIN}}, tief <{{cfg.PRODUCTIVE_LOW_CLOUD_MAX}}%, mittel <{{cfg.PRODUCTIVE_MID_CLOUD_MAX}}%, kein ROUGH-UNUSABLE/WIND-UNUSABLE (Regionen: ohne ROUGH)
- `→ BOEEN-FLOOR: MINDEST-STATUS = '...'` — Spot only, System-erzwungen, nicht verhandelbar
- `→ ACHTUNG Verhaeltnis < 35%: ...` — optional, MUSS in caution_notes/no_go_reasons
- `THERMIK-QUALITAET-Block` — Zaehler fuer SHEAR/TORN/ROUGH-UNUSABLE + TQ-Ratio
- **Trend-Labels:** AUFKLAERUNG/ZUNEHMEND/EINGEKESSELT/DURCHGEHEND/VEREINZELT/STABIL (Definitionen in `_hazards_*.md`). Pro Gefahrenblock anwenden. Foehn ausgenommen (severity-pauschal).
- **Eigene Trend-Zeilen:** `NIEDERSCHLAG-TREND`, `GUST-TREND` (Spot only), `WIND-TREND` (Boden + Hoehe summiert). PFLICHT-Input fuer Status. Mapping siehe `_hazards_*.md`. Trend-Zeilen enthalten **keine fertigen Saetze** zum Abschreiben.

**Pflicht:** Werte lesen, nicht selber berechnen. BOEEN-FLOOR verbindlich. "Verhaeltnis < 35%" MUSS in caution_notes/no_go_reasons.
