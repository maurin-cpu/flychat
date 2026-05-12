═══════════════════════════════════════════════
PROSA-STIL (Flyability)
═══════════════════════════════════════════════

**Wichtig:** TQ-Tags (`[SHEAR-*]`, `[THERMAL-TORN-*]`, `[THERMAL-ROUGH-*]`,
`[THERMAL-WIND-*]`) sind **Safety-Domain** und gehoeren NICHT in die Flyability-
Prosa. Erwaehne sie weder in `thermal_quality`, `recommendation` noch in
`flyability_notes`.

Die Flugqualitaets-Bewertung beruht ausschliesslich auf den RATING-INPUTS
(prod_h_strict, sustained_peak, working_height_agl, cloud_structure) und der
Pilot-Heuristik aus `_flight_subratings_*.md`.

─────────────────────────────────
KONSISTENZ-PFLICHT (Text muss zum experience_rating passen!)
─────────────────────────────────

- **Rating 5/6 (xc_tag/klassiker)** → `thermal_quality` und `recommendation` MUESSEN positiv formuliert sein ("starker Tag", "XC-Tag", "fettes Streckenpotenzial", "Klassiker"). NICHT "unbrauchbar", "nicht empfohlen" oder "Region meiden".
- **Rating 4 (starker_thermikflug)** → POSITIV ("kraftvoller Thermiktag", "lokal-XC moeglich").
- **Rating 3 (solider_thermikflug)** → POSITIV oder NEUTRAL ("solider Thermiktag", "Hausrunden moeglich"). Keine Schwach-Tag-Wortwahl.
- **Rating 2 (kurzer_thermikflug)** → ehrlich als kurz/schwach beschreiben ("kurzer Thermikflug", "schwacher Tag", "1-3h").
- **Rating 1 (abgleiter / reines Soaring)** → ehrlich als unfliegbar fuer Thermik beschreiben ("Abgleiter", "kein Tag"). Bei Soaring-Moeglichkeit das in `soaring_options` erwaehnen, aber Rating bleibt 1. NIEMALS "grauer Tag" oder Tier-Farben.
- UNUSABLE-Randstunden (typisch morgens/abends mit <1 m/s Steigen) erwähne als "morgens/abends ruppiger" — nicht den ganzen Tag abwerten.

**Abgrenzung:** Boeen-Tags, Scherung, zerrissene Thermik = SAFETY. Schon in
Teil 1 behandelt. NICHT in Flyability-Texten erwaehnen.

─────────────────────────────────
BEWOELKUNGS-LABELS (Booster vs. Reducer — Matuszko/FAA)
─────────────────────────────────

- **`GUTE_EINSTRAHLUNG` (Booster)**: Optimale Cu-Bedeckung 12-{{cfg.VIOLET_CLOUD_LOW_MAX}}% (SCT) = staerkste Thermik. Latentwaerme-Boost, Cu markiert Einstiege, teils bewoelkter Himmel liefert sogar MEHR Solarenergie als wolkenlos (Streueffekt). Setzen wenn: max(tief, mittel) ≤ {{cfg.VIOLET_CLOUD_LOW_MAX}}% mit Cu-Charakter ODER klarer Himmel (<30%). Auch blauer Himmel (0%) ist Booster.
- **`VIEL_BEWOELKUNG` (Reducer)**: Ab ~{{cfg.PRODUCTIVE_LOW_CLOUD_MAX}}% max(tief, mittel) wird Sonne weitgehend blockiert, Thermik stirbt. Setzen wenn: max(tief, mittel) ≥ {{cfg.PRODUCTIVE_LOW_CLOUD_MAX}}% waehrend > 50% der Thermikstunden. Starke Ueberentwicklung (OD) mit Abschirmung gehoert auch hierher.
- **Neutralzone {{cfg.VIOLET_CLOUD_LOW_MAX}}-{{cfg.PRODUCTIVE_LOW_CLOUD_MAX}}%**: Weder Booster noch Reducer — Daempfung beginnt (FAA 5/10-Regel), Thermik noch vorhanden aber abnehmend.
- **Cirrus ignorieren**: Nur hohe Bewoelkung (tief + mittel <30%) → WEDER Reducer NOCH Booster (Cirrus laesst 70-85% Solarstrahlung durch).
