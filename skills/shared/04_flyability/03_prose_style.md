═══════════════════════════════════════════════
PROSA-STIL (Flyability)
═══════════════════════════════════════════════

**TQ-Tags sind grundsaetzlich Safety-Domain** ([SHEAR-*], [THERMAL-ROUGH-*], [THERMAL-WIND-*]) — nicht in Flyability-Prosa erwaehnen. **AUSNAHME [THERMAL-TORN-UNUSABLE]:** zerrissene Thermik (Scherung zerreisst den Bart, nicht zentrierbar) ist Thermik-QUALITAET und gehoert in `thermal_quality`/`flyability_notes` — siehe `01_tags_flyability.md`. Bewertung beruht auf RATING-INPUTS (prod_h_strict, sustained_peak, working_height_agl, cloud_structure) und Pilot-Heuristik aus `_flight_subratings_*.md`; TORN ist dort via reduzierte prod_h bereits eingepreist — NICHT zusaetzlich abwerten.

─────────────────────────────────
KONSISTENZ: Text muss zum Rating passen
─────────────────────────────────

- **Rating 5 (xc_tag, inkl. Klassiker)** → POSITIV: "starker Tag", "XC-Tag", "Klassiker" (bei allen 3 Hammertag-Markern). NIE "unbrauchbar"/"Region meiden".
- **Rating 4 (starker)** → POSITIV ("kraftvoll", "lokal-XC moeglich").
- **Rating 3 (solid)** → POSITIV oder NEUTRAL ("solid", "Hausrunden moeglich"). Keine Schwach-Wortwahl.
- **Rating 2 (Suchtag)** → ehrlich als Suchtag ("Glueck noetig", "1-2h mit Glueck, sonst Abgleiter", "Kerne schwach + intermittent"). Nie "garantiert".
- **Rating 1 (abgleiter/Soaring)** → ehrlich unfliegbar fuer Thermik. Soaring-Moeglichkeit in `soaring_options`, Rating bleibt 1. NIE "grauer Tag" oder Tier-Farben.
- UNUSABLE-Randstunden (morgens/abends <1 m/s) als "morgens/abends ruppiger" — nicht ganzen Tag abwerten.

**Abgrenzung:** Boeen, Hoehenwind, Grundwind, mechanische Boeigkeit (ROUGH) = SAFETY, NIE in Flyability-Prosa. **AUSNAHME — zerrissene Thermik (TORN-UNUSABLE):** wenn die Scherung den Bart zerreisst (nicht zentrierbar), in `thermal_quality` benennen — das ist Thermik-Qualitaet, nicht Sicherheit. Keine rohen Wind-/Scherungs-Zahlen, nur die Konsequenz fuer die Thermik.

─────────────────────────────────
BEWOELKUNG: STRAHLUNG IST WAHRHEIT (Mai 2026)
─────────────────────────────────

Fuer Thermik-Bewertung zaehlt **Sonneneinstrahlung am Boden** (`Strahlung X W/m²` in Hour-Lines), NICHT Wolken-%:
- `climb_rate` wird aus `direct_radiation` + `diffuse_radiation` ueber H abgeleitet → Wolken-Daempfung steckt schon drin
- ICON-D2 `cloud_cover_mid` = flaechige Bedeckung, NICHT optische Dicke. Duenner Altostratus kann mid=100% sein bei 750 W/m²
- Doppelbestrafung der Engine ueber Wolken-% NICHT erlaubt

**Strahlungs-Referenz (Schweiz Fruehling/Sommer):**
- **swr ≥ 600 W/m² ODER direct ≥ 400 W/m²** → Sonne voll, Thermik normal
- **swr 400-600 ODER direct 250-400** → leichte Daempfung, Thermik arbeitet
- **swr < 400 UND direct < 250** → echt gedaempft, Thermik schwach bis tot

**Cu als Booster bleibt** (LLM-Bonus, Engine erfasst Latentwaerme nicht voll):
- **Tief (Cu humilis/mediocris, 12-50%)** = Thermik-Marker mit Latentwaerme-Boost → Plus in Prosa
- **Mittel (Altostratus, ≥30%)** = beschreibe was los ist, Strahlung entscheidet
- **Hoch (Cirrus)** = ignoriert (Transmissivitaet 70-85%)

**Label-Vergabe (informativ, kein Rating-Effekt):**
- `GUTE_EINSTRAHLUNG` (Booster, info): tief ≤50% mit Cu UND mittel ≤30%, ODER tief <30% UND mittel <30%
- `VIEL_BEWOELKUNG` (Reducer, info): >50% Thermikstunden mit tief ≥80% ODER mittel ≥70%
- `cu_clean_top` (Klassiker-Booster): tief 12-50% Cu UND mittel <30%

─────────────────────────────────
STRAHLUNGS-WERTE: INTERN NUTZEN, NIE AN USER
─────────────────────────────────

W/m²-Werte sind **dein internes Tool**. **NIEMALS Roh-Zahlen in user-facing Prosa.** Uebersetze:

| Strahlung | Schreibweise |
|---|---|
| swr ≥600 oder direct ≥400 | "kraftvolle Sonne", "klare Einstrahlung", "Sonne arbeitet voll" |
| 400-600 oder 250-400 | "Sonne kaempft sich durch", "leicht gedaempft" |
| <400 und <250 | "Sonne weitgehend weg", "trueber Tag" |

**Diskrepanz erklaeren** (haeufig: hohe Wolken-% trotz Sonne):
- `mittel 100%, Strahlung 750 W/m²` → "duenne Schleier-Bewoelkung, Sonne kommt klar durch", NICHT "100% mittel" oder "750 W/m²"
- `mittel 100%, Strahlung 280 W/m²` → "dichte Mittelbewoelkung, Sonne weitgehend weg"

**Ausnahme:** In `flyability_notes` (technische Diagnostik) duerfen Werte stehen. In `recommendation`/`thermal_quality`: nur Fliegersprache.
