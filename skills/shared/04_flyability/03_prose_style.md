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

**WICHTIG — tief und mittel wirken physikalisch UNTERSCHIEDLICH:**
- **Tief (Cu humilis/mediocris, <3km)** = bimodal: 12-50% = Thermik-Marker (Booster, Latentwaerme-Boost). ≥80% = Sonne blockiert (Killer).
- **Mittel (Altostratus/Altocumulus, 3-8km)** = monoton daempfend: jedes % reduziert Einstrahlung, KEIN Sweet Spot. Ab 30% spuerbar, ab 70% Thermik stark gedaempft, ab 90% praktisch tot.
- **Hoch (Cirrus, >8km)** = ignoriert (Transmissivitaet 70-85%).

Wende daher tief und mittel mit getrennten Schwellen an (NICHT `max(tief, mittel)`):

- **`GUTE_EINSTRAHLUNG` (Booster)**: Optimale SCT-Cu unten MIT klarer Sicht nach oben — staerkste Thermik. Setzen wenn: **tief ≤ 50% mit Cu-Charakter UND mittel ≤ 30%** ODER klarer Himmel (tief < 30% UND mittel < 30%). Cu markiert Einstiege, Latentwaerme-Boost, Streueffekt liefert sogar MEHR Solarenergie als wolkenlos. Auch blauer Himmel (0%) ist Booster.
- **`VIEL_BEWOELKUNG` (Reducer)**: Sonne wird signifikant blockiert. Setzen wenn waehrend > 50% der Thermikstunden gilt: **tief ≥ 80% (Cu-Overcast/Stratus von unten) ODER mittel ≥ 70% (Altostratus-Decke von oben)**. Starke Ueberentwicklung (OD) mit Abschirmung gehoert auch hierher.
- **Neutralzone**: tief 50-80% ODER mittel 30-70% (und kein Reducer-Trigger) — Daempfung beginnt, Thermik noch vorhanden aber abnehmend.
- **Top-Tag (klassiker, Rating 6)**: STRENGER als Booster — verlangt `cu_clean_top` = **tief 12-50% Cu UND mittel < 30%**. Mehr Altostratus oben verschattet selbst starke Thermik.
- **Cirrus ignorieren**: Bei tief < 30% UND mittel < 30% (egal wie viel hoch) → Cirrus ist kein Reducer und kein Booster (laesst 70-85% Solarstrahlung durch).
