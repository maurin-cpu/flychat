═══════════════════════════════════════════════
TEIL 2: ERLEBNIS / FLIEGBARKEIT (2-Achsen-Welt)
═══════════════════════════════════════════════

**Architektur:** Die App hat **zwei orthogonale Achsen**:
- `safety_band` (green/amber/red) = Sicherheit (siehe `_safety_subratings.md`).
- `experience_stars` (0–5) = **Rating** des Tages — abgeleitet aus deinem
  Gesamt-`rating` (kommt aus den Fliegbarkeits-Sub-Ratings thermal/window/wind/xc[/altitude],
  siehe `_flight_subratings_*.md`). User-Sprache: "Rating 1–5".

**Deine Aufgabe ist es, konsistente Sub-Ratings zu vergeben.** Das `rating`-Gesamt
und der `flyability_tier` (gray/green/violet) werden von der Engine deterministisch
daraus abgeleitet — du wählst keinen Tier mehr selbst.

`flyability_tier` / `fly_status` ist ein **abgeleiteter Compat-Wert** für das
Frontend-Glyph (Bronze-/Grün-/Violett-Marker). Die View berechnet ihn am Ende
der Pipeline aus (`safety_band`, `experience_stars`):

| safety_band | experience_stars | → flyability_tier |
|---|---|---|
| `red` | egal | `""` (keine Empfehlung) |
| `green` | ≥ 4 (≈ rating ≥ 7.6) | `violet` |
| `green` oder `amber` | ≥ 2 (≈ rating ≥ 4.1) | `green` |
| sonst | < 2 | `gray` |

Du DARFST `fly_status` weiterhin im JSON setzen (für Backward-Compat); wenn ja,
folge mechanisch dieser Mapping-Regel — **nicht** aus eigenen Tier-Schwellen.
Die View überschreibt deinen Wert ohnehin.

Sprich in den Prosa-Feldern (`recommendation`, `thermal_quality`, `summary`)
über **Rating 1–5** und konkrete Erlebnis-Begriffe ("Abgleiter", "solider
Thermiktag", "fettes XC-Potential"), **nicht** über Tier-Farben. NIEMALS
"grauer Tag".

**GATE:** Wenn `safety_status = not_safe` → Teil 2 komplett überspringen.
Setze alle Flyability-Felder auf Minimal-Werte (siehe JSON-Schema der jeweiligen
Analyse).

Analysiere NUR die Stunden innerhalb des sicheren Fensters (`safe_window` aus
Teil 1).

─────────────────────────────────
NUMERIK-REGEL (verbindlich)
─────────────────────────────────

- Alle Zahlenwerte aus dem TAGESPROFIL EXAKT übernehmen.
- `peak_climb_rate` = der im TAGESPROFIL genannte `Peak-Steigen (Proxy)` direkt
  1:1 (z.B. 2.6 m/s → 2.6, NICHT auf 2.0/2.5/3.0 runden).
- Keine Abrundung, kein Aufrunden, keine "Konservativität bei Zahlen".
- Konservativität gilt NUR für die Sub-Rating-Wahl (lieber 5 als 7 wenn unsicher),
  NICHT für Zahlenfelder.
- Bei Abweichung zwischen TAGESPROFIL und Meteogramm-Grid → TAGESPROFIL gewinnt.

─────────────────────────────────
SUB-RATING-ANKER aus Datenblock-Fakten
─────────────────────────────────

Diese Schwellen verankern, **wo deine Sub-Ratings landen müssen**, damit das
daraus berechnete `rating` und der View-Tier konsistent rauskommen. Sie ersetzen
die alte unabhängige Tier-Wahl.

**Schwacher Tag (rating ≈ 0–4 → View-tier `gray` / "Bronze") — `thermal_rating`
MUSS 1–3 wenn EINES der vier Kriterien zutrifft:**

1. Peak-Thermik < {{cfg.PRODUCTIVE_CLIMB_MIN}} m/s, ODER
2. Tiefe Wolken ≥ {{cfg.PRODUCTIVE_LOW_CLOUD_MAX}}% ODER mittlere Wolken ≥
   {{cfg.PRODUCTIVE_MID_CLOUD_MAX}}% während Thermikstunden — sodass produktive
   Stunden < {{cfg.PRODUCTIVE_HOURS_DOWNGRADE}} bleiben, ODER
3. **THERMAL-ROUGH-UNUSABLE** in > 50% der Thermik-Stunden (Klapper-Gefahr,
   nur Spots), ODER
4. **THERMAL-WIND-UNUSABLE** in > 50% der Thermik-Stunden (BL-Grundwind reißt
   Blase auseinander — Spots + Regionen).

Bei Schwach-Tag zusätzlich: `window_rating` 1–4, `xc_rating` 1–3.

**Solider Tag (rating ≈ 4–7 → View-tier `green`) — `thermal_rating` 4–7 wenn:**
- Peak-Thermik ca. 1–2.5 m/s, ordentliche bis gute Basis.
- 1–4h Flug möglich, lokale Thermikflüge, evtl. kurze Strecken.

**Top-Tag (rating ≥ 7.6 → View-tier `violet` bei `safety_band=green`) —
`thermal_rating` 8–10 wenn ALLE erfüllt:**
- Peak-Thermik ≥ **{{cfg.VIOLET_PEAK_MIN}} m/s** (aus `Peak-Steigen (Proxy)`).
- Produktive Thermik ≥ **{{cfg.VIOLET_HOURS_MIN}}h** (aus `PRODUKTIVE-THERMIK`).
- ROUGH-UNUSABLE < **{{cfg.VIOLET_ROUGH_MAX}}%** der Thermikstunden.
- Gesamt-UNUSABLE < **{{cfg.VIOLET_UNUSABLE_MAX}}%** der Thermikstunden.
- Ø tiefe Wolken ≤ **{{cfg.VIOLET_CLOUD_LOW_MAX}}%** (über Thermikstunden) —
  optimale Cu-Zone, keine Überentwicklung.
- Ø mittlere Wolken ≤ **{{cfg.VIOLET_CLOUD_MID_MAX}}%** — keine Altostratus-Dämpfung
  (Quelle: `meteo_research/cloud_cover_thermal_impact.md` Sektion 6).
- 4+ Stunden Flug, starkes XC-Potential.
- Auch `window_rating` und `xc_rating` entsprechend hoch (≥ 7).

**Shortcut:** Wenn das TAGESPROFIL den Hint `→ VIOLETT-Kandidat: ...` enthält,
sind alle harten Schwellen bereits erfüllt — du DARFST hohe Sub-Ratings (8–10)
vergeben. Setze dann `peak_climb_rate` EXAKT auf den dort genannten Peak-Wert.

**Faustregel bei Unsicherheit:** Mittlere Sub-Ratings wählen (5–6, konservativ).
Niedrige Sub-Ratings (1–3) NUR wenn eines der vier Schwach-Tag-Kriterien
erfüllt ist.

─────────────────────────────────
TQ-DOWNGRADE-REGEL (wirkt auf Sub-Ratings)
─────────────────────────────────

**Bewertungsreihenfolge:**

1. **ZUERST** vergib `thermal_rating` anhand Peak m/s, Wolken und Basis nach
   den Sub-Rating-Ankern oben.
2. **DANACH** prüfst du die UNUSABLE-Downgrade-Regeln und korrigierst dein
   `thermal_rating` nach unten:
   - **ROUGH-UNUSABLE > 50%** (Klapper-Gefahr, Spots) ODER
     **WIND-UNUSABLE > 50%** (BL-Grundwind reißt Blase auseinander, Spots + Regionen)
     → senke `thermal_rating` auf 1–3 (Schwach-Bereich).
   - **SHEAR-UNUSABLE und THERMAL-TORN-UNUSABLE** (beliebig viel) → senke
     `thermal_rating` maximal auf 5–6, NIE in den Schwach-Bereich (reine
     Qualitäts-Issue, kein Sicherheitsrisiko).
   - DEGRADED-Varianten aller Typen: senke maximal um 1–2 Punkte (typisch von
     8 auf 6), nie in den Schwach-Bereich.

**Beispiele (thermal_rating-Anker):**
- Peak 0.8 m/s, ROUGH-UNUSABLE 25% → **thermal_rating 2** (Peak < 1, Schwach-Tag).
- Peak 1.7 m/s, ROUGH-UNUSABLE 25% → **thermal_rating 6** (solide, ROUGH unter 50%).
- Peak 2.0 m/s, ROUGH-UNUSABLE 60% → **thermal_rating 3** (wäre 7, aber Klapper-Downgrade).
- Peak 2.0 m/s, WIND-UNUSABLE 70% → **thermal_rating 3** (Grundwind zerreißt, Schwach-Tag).
- Peak 2.0 m/s, SHEAR-UNUSABLE 80%, ROUGH=0%, WIND=0% → **thermal_rating 5**
  (SHEAR allein nicht in Schwach-Bereich).
- Peak 2.8 m/s, THERMAL-TORN-DEGRADED → **thermal_rating 6** (nicht Top, aber kein
  Schwach-Tag).
- Peak 2.8 m/s, WIND-DEGRADED 60% → **thermal_rating 6** (DEGRADED reduziert
  nur leicht).

**Konsequenzen bei Schwach-Bereich-Downgrade (ROUGH/WIND-UNUSABLE > 50%):**
- `flight_type` → "Abgleiter" statt "Thermikflug".
- `peak_climb_rate` → maximal 1.0 m/s eintragen (sonst echter Peak).
- `xc_potential` → "low".
- `xc_rating` → 1–3.

**Konsequenzen bei SHEAR/TORN-UNUSABLE allein (thermal_rating bleibt 5–6):**
- `flight_type` bleibt "Thermikflug".
- `peak_climb_rate` unverändert.
- `xc_potential` kann "moderate" bleiben (Wind hilft bei Strecke).
- Text beschreibt "Thermik anspruchsvoll, Bart-Zentrierung schwierig".

─────────────────────────────────
PRODUKTIVE-THERMIK-Check (aus TAGESPROFIL)
─────────────────────────────────

Wenn im TAGESPROFIL `→ PRODUKTIVE-THERMIK: Nh` steht:
- **N ≥ {{cfg.PRODUCTIVE_HOURS_FOR_GREEN}}** → `window_rating` 7–10 möglich,
  `thermal_rating` darf 5–10 sein.
- **N < {{cfg.PRODUCTIVE_HOURS_DOWNGRADE}}** → `thermal_rating` MUSS 1–3,
  `window_rating` MUSS 1–4 (Schwach-Tag).
- **{{cfg.PRODUCTIVE_HOURS_DOWNGRADE}} ≤ N < {{cfg.PRODUCTIVE_HOURS_FOR_GREEN}}**
  → Grenzfall, `thermal_rating` typisch 4–5, `window_rating` 4–6 abhängig
  von Peak und Wind.

─────────────────────────────────
CONDITIONAL-FLAG (visuelles Badge)
─────────────────────────────────

**Hinweis**: Die Decision-Engine setzt `is_conditional` deterministisch in
folgenden Fällen — du musst dich darum **nicht** kümmern:
- `safety_status == "conditional"` → `is_conditional = true` (automatisch).
- `safety_status == "not_safe"` → `is_conditional = false` (automatisch).

Du setzt `is_conditional = true` nur dann selbst, wenn `safety_status = "safe"`
ist UND eine der folgenden **Soft-Warnungen** zutrifft (sonst lass es auf
`false`):

1. **Tiefe Wolkenbasis**: Basis < Startplatzhöhe + 500 m UND Bedeckung ≥ 75 %.
2. **Starke Höhen-Turbulenz**: Turbulenzrisiko deutlich über Grundwind in
   produktiven Höhen (T > W + 10 km/h).

Diese zwei Trigger erkennt die Engine nicht — nur dein Wetter-Urteil sieht sie.
**Bei Schwach-Tag (thermal_rating ≤ 3) gilt weiterhin: `is_conditional = false`**
— ein schwacher Tag ist keine Bedingt-Fliegbar-Situation, sondern ein
Schwach-Tag.

Das Rating ändert sich durch `is_conditional` NICHT — nur das Flag sorgt für
einen ⚠ Hinweis im UI. `conditional_reason` = max 1 Satz Begründung wenn
`is_conditional = true`, sonst leer.
