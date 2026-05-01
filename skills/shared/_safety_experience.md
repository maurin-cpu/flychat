═══════════════════════════════════════════════
TEIL 2: ERLEBNIS / FLIEGBARKEIT (2-Achsen-Welt)
═══════════════════════════════════════════════

**Architektur (RATING_CONCEPT v1.3 + Phase 4b):** Die App hat **zwei orthogonale Achsen**:
- `safety_band` (green/amber/red) = Sicherheit (siehe `_safety_subratings.md`).
- `experience_stars` (0–5) = **Rating** des Tages — abgeleitet aus deinem
  Gesamt-`rating` (kommt aus den Fliegbarkeits-Sub-Ratings thermal/window/wind/xc,
  siehe `_subratings_tables.md`). User-Sprache: "Rating 1–5".

`flyability_tier` (gray/green/violet) ist seit Phase 4b **abgeleitet** aus
(safety_band, experience_stars) — die Engine berechnet ihn am Ende der Pipeline
selbst. Du DARFST `flyability_tier` weiterhin nach den Tier-Regeln unten setzen
(als Compat-Hilfe), der Wert wird aber von der View ueberschrieben. Wichtig
fuer dich: vergib **konsistente Sub-Ratings**, dann faellt der Tier automatisch
richtig raus.

Sprich in den Prosa-Feldern ueber **Rating** und **Sicherheit**, nicht ueber
Tier-Farben.

**GATE:** Wenn `safety_status = not_safe` → Teil 2 komplett ueberspringen. Setze alle Flyability-Felder auf Minimal-Werte (siehe JSON-Schema der jeweiligen Analyse).

Analysiere NUR die Stunden innerhalb des sicheren Fensters (`safe_window` aus Teil 1).

─────────────────────────────────
NUMERIK-REGEL (verbindlich)
─────────────────────────────────

- Alle Zahlenwerte aus dem TAGESPROFIL EXAKT uebernehmen.
- `peak_climb_rate` = der im TAGESPROFIL genannte `Peak-Steigen (Proxy)` direkt 1:1 (z.B. 2.6 m/s → 2.6, NICHT auf 2.0/2.5/3.0 runden).
- Keine Abrundung, kein Aufrunden, keine "Konservativitaet bei Zahlen".
- Konservativitaet gilt NUR fuer die Tier-Wahl, NICHT fuer Zahlenfelder.
- Bei Abweichung zwischen TAGESPROFIL und Meteogramm-Grid → TAGESPROFIL gewinnt.

**Prosa-Sprache (User-Sprache):**
Der `fly_status`-Enum-Wert im JSON heisst `"gray" / "green" / "violet"` (Code-Kompatibilitaet — NICHT aendern!). In deinen Prosa-Feldern (`recommendation`, `thermal_quality`, `summary`) sprich primaer in **Rating-Sprache** ("Rating 1", "Rating 3", "Top-Tag mit Rating 5") oder beschreibe das Erlebnis konkret ("Abgleiter", "solider Thermiktag", "fettes XC-Potential"). Die alte Tier-Prosa ("Bronze-Tag" / "Abgleiter-Tag") bleibt erlaubt fuer Rueckwaertskompatibilitaet — niemals aber "grauer Tag".

─────────────────────────────────
TIER-DEFINITIONEN (steuert flyability_tier-Compat-Output)
─────────────────────────────────

**BRONZE / Rating 0–1 (Abgleiter / kaum fliegbar)** — Enum-Wert: `"gray"`. Vier harte Kriterien, nur eines muss erfuellt sein:
1. Peak-Thermik < {{cfg.PRODUCTIVE_CLIMB_MIN}} m/s, ODER
2. tiefe Wolken ≥ {{cfg.PRODUCTIVE_LOW_CLOUD_MAX}}% ODER mittlere Wolken ≥ {{cfg.PRODUCTIVE_MID_CLOUD_MAX}}% waehrend Thermikstunden — Stunde zaehlt nicht als produktiv. Wenn dadurch < {{cfg.PRODUCTIVE_HOURS_DOWNGRADE}} produktive Stunden bleiben → Bronze, ODER
3. **THERMAL-ROUGH-UNUSABLE** in > 50% der Thermik-Stunden (mechanische Klapper-Gefahr, nur Spots), ODER
4. **THERMAL-WIND-UNUSABLE** in > 50% der Thermik-Stunden (BL-Grundwind zu stark → Thermikblase organisiert sich nicht, Research Abschnitt 3.1). Gilt fuer Spots UND Regionen.

**GRUEN / Rating 2–3 (fliegbar, solider Thermiktag)** — Enum-Wert: `"green"`.
- Peak-Thermik ca. 1-2.5 m/s, ordentliche bis gute Basis.
- 1-4h Flug moeglich, lokale Thermikfluege, evtl. kurze Strecken.

**VIOLETT / Rating 4–5 (legendaer / Top-XC)** — Enum-Wert: `"violet"`. **ALLE** Kriterien muessen erfuellt sein:
- Peak-Thermik ≥ **{{cfg.VIOLET_PEAK_MIN}} m/s** (aus `Peak-Steigen (Proxy)`).
- Produktive Thermik ≥ **{{cfg.VIOLET_HOURS_MIN}}h** (aus `PRODUKTIVE-THERMIK`).
- ROUGH-UNUSABLE < **{{cfg.VIOLET_ROUGH_MAX}}%** der Thermikstunden.
- Gesamt-UNUSABLE < **{{cfg.VIOLET_UNUSABLE_MAX}}%** der Thermikstunden.
- Ø tiefe Wolken ≤ **{{cfg.VIOLET_CLOUD_LOW_MAX}}%** (ueber Thermikstunden) — optimale Cu-Zone, keine Ueberentwicklung.
- Ø mittlere Wolken ≤ **{{cfg.VIOLET_CLOUD_MID_MAX}}%** — keine Altostratus-Daempfung (Quelle: `meteo_research/cloud_cover_thermal_impact.md` Sektion 6).
- 4+ Stunden Flug, starkes XC-Potential.

**Shortcut:** Wenn das TAGESPROFIL den Hint `→ VIOLETT-Kandidat: ...` enthaelt, sind alle harten Schwellen bereits erfuellt — du DARFST violet waehlen. Setze dann `peak_climb_rate` EXAKT auf den dort genannten Peak-Wert.

**Faustregel bei Unsicherheit:** Gruen waehlen (konservativ). Bronze NUR wenn eines der drei harten Kriterien erfuellt ist.

─────────────────────────────────
TQ-DOWNGRADE-REGEL (EINMAL, verbindlich)
─────────────────────────────────

**Bewertungsreihenfolge:**

1. **ZUERST** bewertest du die Thermik-Staerke anhand Peak m/s, Wolken und Basis → Bronze, Gruen oder Violett.
2. **DANACH** pruefst du die UNUSABLE-Downgrade-Regeln:
   - Ist dein Tier **Gruen oder Violett** UND **ROUGH-UNUSABLE > 50%** (Klapper-Gefahr, Spots) ODER **WIND-UNUSABLE > 50%** (BL-Grundwind reisst Blase auseinander, Spots + Regionen)? → **degradiere zu Bronze**.
   - Beide ≤ 50% → aendere NICHTS, behalte Bronze/Gruen/Violett.
   - Keines der beiden macht einen Bronze-Tag NICHT zu Gruen.
3. **SHEAR-UNUSABLE und THERMAL-TORN-UNUSABLE** (beliebig viel) fuehren **NIE zu Bronze**, nur zu **Violett → Gruen** (reine Qualitaets-Issue, kein Sicherheitsrisiko).
4. DEGRADED-Varianten aller Typen: **Violett → Gruen**, nie Bronze.

**Beispiele:**
- Peak 0.8 m/s, ROUGH-UNUSABLE 25% → **Bronze** (Peak < 1, ROUGH irrelevant).
- Peak 1.7 m/s, ROUGH-UNUSABLE 25% → **Gruen** (Thermik gut, ROUGH unter 50%).
- Peak 2.0 m/s, ROUGH-UNUSABLE 60% → **Bronze** (Thermik waere Gruen, aber Klapper-Gefahr).
- Peak 2.0 m/s, WIND-UNUSABLE 70% → **Bronze** (Grundwind reisst Thermik auseinander, Abgleiter).
- Peak 2.0 m/s, SHEAR-UNUSABLE 80%, ROUGH-UNUSABLE 0%, WIND-UNUSABLE 0% → **Gruen** (SHEAR allein macht kein Bronze).
- Peak 2.8 m/s, THERMAL-TORN-DEGRADED → **Gruen** (nicht Violett, aber kein Bronze).
- Peak 2.8 m/s, WIND-DEGRADED 60% → **Gruen** (DEGRADED degradiert nur Violet→Green).

**Konsequenzen bei Downgrade wegen ROUGH-UNUSABLE > 50% ODER WIND-UNUSABLE > 50%:**
- `flight_type` → "Abgleiter" statt "Thermikflug".
- `peak_climb_rate` → maximal 1.0 m/s eintragen (sonst echter Peak).
- `xc_potential` → "low".

**Konsequenzen bei SHEAR/TORN-UNUSABLE allein (Tier bleibt max green):**
- `flight_type` bleibt "Thermikflug".
- `peak_climb_rate` unveraendert.
- `xc_potential` kann "moderate" bleiben (Wind hilft bei Strecke).
- Text beschreibt "Thermik anspruchsvoll, Bart-Zentrierung schwierig".

─────────────────────────────────
PRODUKTIVE-THERMIK-Check (aus TAGESPROFIL)
─────────────────────────────────

Wenn im TAGESPROFIL `→ PRODUKTIVE-THERMIK: Nh` steht:
- **N ≥ {{cfg.PRODUCTIVE_HOURS_FOR_GREEN}}** → Gruen/Violett moeglich.
- **N < {{cfg.PRODUCTIVE_HOURS_DOWNGRADE}}** → fly_status MUSS `"gray"` (Bronze) sein.
- **{{cfg.PRODUCTIVE_HOURS_DOWNGRADE}} ≤ N < {{cfg.PRODUCTIVE_HOURS_FOR_GREEN}}** → Grenzfall, abhaengig von Peak und Wind.

─────────────────────────────────
CONDITIONAL-FLAG (visuelles Badge)
─────────────────────────────────

**Hinweis (RATING_CONCEPT v1.3 / Vorab-Fix #2)**: Die Decision-Engine setzt `is_conditional` deterministisch in folgenden Faellen — du musst dich darum **nicht** kuemmern:
- `safety_status == "conditional"` → `is_conditional = true` (automatisch).
- `safety_status == "not_safe"` → `is_conditional = false` (automatisch).

Du setzt `is_conditional = true` nur dann selbst, wenn `safety_status = "safe"` ist UND eine der folgenden **Soft-Warnungen** zutrifft (sonst lass es auf `false`):

1. **Tiefe Wolkenbasis**: Basis < Startplatzhoehe + 500m UND Bedeckung ≥ 75%.
2. **Starke Hoehen-Turbulenz**: Turbulenzrisiko deutlich ueber Grundwind in produktiven Hoehen (T > W + 10 km/h).

Diese zwei Trigger erkennt die Engine nicht — nur dein Wetter-Urteil sieht sie. **Bei Bronze (`fly_status="gray"`) gilt weiterhin: `is_conditional = false`** (Bronze ist keine Bedingt-Fliegbar-Situation, sondern Schwach-Tag).

**Frueher** waren auch Foehn-Vorsicht und TQ-Tags 10-50% in dieser Liste — diese werden jetzt von der Decision-Engine ueber `safety_status` abgedeckt (Foehn-Engine setzt `conditional`, Aloft/Gust-Engines auch). Du musst sie nicht mehr selbst flaggen.

Das Rating aendert sich durch `is_conditional` NICHT — nur das Flag sorgt fuer einen ⚠ Hinweis im UI. `conditional_reason` = max 1 Satz Begruendung wenn `is_conditional = true`, sonst leer.
