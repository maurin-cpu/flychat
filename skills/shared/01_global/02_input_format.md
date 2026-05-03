═══════════════════════════════════════════════
INPUT-FORMAT — WIE LIEST DU DEN DATENBLOCK?
═══════════════════════════════════════════════

Der User-Block liefert dir drei Zonen: **Stunden-Zeilen**, **Drucklevel-Werte** und den **TAGESPROFIL-Block** am Ende. Lerne diese zuerst — danach kannst du die Regeln anwenden.

═══════════════════════════════════════════════
DREI TAG-KATEGORIEN (KATEGORISCH GETRENNT!)
═══════════════════════════════════════════════

Jeder Tag in eckigen Klammern gehoert zu **genau einer** dieser drei Kategorien:

**KATEGORIE 1 — STARTBARKEITS-FILTER** (Spot only) — `[WIND-OK]` / `[WIND-WRONG]`
Diese Tags sind weder Hazards noch Fliegbarkeits-Signale. Sie gehoeren zur eigenen Kategorie **Tagesfenster** — vollstaendige Regeln in `_tagesfenster.md`. Der Code hat den Datenblock bereits ab dem ersten qualifizierenden Start-Fenster zugeschnitten.

**KATEGORIE 2 — HAZARD-TAGS** (echte Sicherheits-Signale)
Volle Liste mit Schwellen siehe `_tags_safety.md` (in Safety-Calls geladen). Diese koennen Status druecken, in `caution_notes`/`no_go_reasons` landen und Sub-Ratings beeinflussen.

**KATEGORIE 3 — THERMIK-QUALITAETS-TAGS** (nur Fliegbarkeit, nie Sicherheit)
`[SHEAR-*]`, `[THERMAL-TORN-*]`, `[THERMAL-WIND-*]`, `[THERMAL-ROUGH-*]`. Volle Liste mit Mechanismen siehe `_tags_flyability.md` (in Flyability-Calls geladen).

─────────────────────────────────
A) STUNDEN-ZEILEN (Bodendaten + Tags)
─────────────────────────────────

Pro Stunde bekommst du eine Zeile mit Bodenwind, Bewoelkung, Niederschlag, CAPE, Wolkenbasis — und eine Liste von **Tags** in eckigen Klammern. Im Spot-Kontext enthaelt die Zeile zusaetzlich Boeen (Turbulenzrisiko). Im Region-Kontext gibt es **keine Boeen-Werte** — nur Windstaerke.

Welche Tags wann auftauchen und welche Schwellen sie reissen — siehe phasen-spezifische Tag-Files (`_tags_safety.md`, `_tags_flyability.md`).

─────────────────────────────────
B) DRUCKLEVEL-WERTE (Flugschicht-Zeile)
─────────────────────────────────

Format: `pressure(altitude_m)MARKER: wind/boeen km/h aus dir°`

**Marker verstehen:**
- `*` = **Flugbereich** (Spot-Hoehe bis Thermik+1000m, inkl. Lid-Zone) — HIER feuern die [ALOFT-*]-Tags. Trend-Bewertung ({{cfg.WIND_WARN_KMH}}-{{cfg.WIND_DANGER_KMH}} km/h = WARN, > {{cfg.WIND_DANGER_KMH}} km/h = DANGER) gilt voll.
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
- **Trend-Labels (falls vorhanden):** AUFKLAERUNG / ZUNEHMEND / EINGEKESSELT / DURCHGEHEND (WARN/DANGER) / VEREINZELT / STABIL — vollstaendige Definitionen siehe TREND-VOKABULAR in `_hazards_*.md`. Wende sie pro Gefahrenblock an (Regen, Wind, Boeen, CAPE, Wolken). Foehn ist ausgenommen (severity-pauschal, kein Trend).
- **Eigene Trend-Zeilen:** Direkt nach TAGESPROFIL koennen `NIEDERSCHLAG-TREND`, `GUST-TREND` (nur Spots) und `WIND-TREND` stehen. `WIND-TREND` umfasst Bodenwind UND Hoehenwind summiert (gleiche Schwellen WARN/DANGER), `GUST-TREND` umfasst Boden- und Hoehenboeen summiert. Sie liefern dir das **Muster** (z.B. AUFKLAERUNG, ZUNEHMEND, DURCHGEHEND_DANGER) und die **Fakten** (Stunden, Zeitpunkte). Sie sind PFLICHT-Input fuer deinen Status. Den Status leitest du aus dem Muster ab (Mapping siehe `_hazards_*.md` Block 4 fuer Wind, Block 3 fuer Boeen, TREND-VOKABULAR fuer den Rest) — nicht aus einem mitgelieferten Satz, denn die Trend-Zeile enthaelt **keine fertigen Handlungs-Saetze** zum Abschreiben.

**Deine Pflicht:** Diese Werte lesen, nicht selber berechnen. Wenn BOEEN-FLOOR steht, ist das verbindlich. Wenn "Verhaeltnis < 35%" steht, MUSS das in `caution_notes` oder `no_go_reasons`.
