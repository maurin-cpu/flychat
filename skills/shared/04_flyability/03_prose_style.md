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
BEWOELKUNG: STRAHLUNG IST WAHRHEIT — WOLKEN-% SIND NUR INFO (Mai 2026)
─────────────────────────────────

**Grundregel:** Fuer die Bewertung der Thermik-Produktivitaet zaehlt die **Sonneneinstrahlung am Boden** (Werte `Strahlung X W/m² (direkt Y)` in jeder Hour-Line), NICHT die Bewoelkungs-Prozente. Begruendung:

- Die `climb_rate` der Thermik-Engine wird bereits aus `direct_radiation` + `diffuse_radiation` ueber den sensiblen Waermefluss H abgeleitet. Wolken-Daempfung steckt also physikalisch in climb_rate drin.
- ICON-D2 `cloud_cover_mid` ist **flaechige Bedeckung**, nicht **optische Dicke**. Duenner Altostratus kann mid=100% zeigen und trotzdem 750 W/m² durchlassen — die Strahlung sagt was wirklich am Boden ankommt.
- Eine Bewertung der Thermik nochmal ueber Wolken-% waere Doppelbestrafung der eigenen Engine-Rechnung. Tu das NICHT.

**Strahlungs-Referenz (Schweiz Frühling/Sommer, indikativ):**
- **swr ≥ 600 W/m² ODER direct ≥ 400 W/m²** → Sonne kommt voll durch, Thermik laeuft normal
- **swr 400-600 W/m² ODER direct 250-400 W/m²** → leichte bis maessige Daempfung, Thermik gedaempft aber arbeitet
- **swr < 400 W/m² UND direct < 250 W/m²** → Sonne wirklich gedaempft (dichter Altostratus oder Stratus), Thermik schwach bis tot
- Hinweis: Schwellen sind grobe Orientierung; absoluter Sonnenstand variiert saisonal. Im Winter sind die Werte deutlich niedriger.

**Wolken-% bleiben relevant — aber nur fuer:**
- **Cu-Marker-Beschreibung** (tief 12-50% = "schoene Cumulus-Tag", Latentwaerme-Boost wird vom Modell nicht voll erfasst → Bonus-Wert fuer Pilot)
- **Sicht-Beschreibung** ("bedeckter Himmel", "viel Hochbewoelkung")
- **Cloud-Entry-Sicherheit** (Wolkenbasis-Proximity, OVERCAST-DANGER)
- Sie sind NICHT Rating-Killer und NICHT Productivity-Gate.

**WICHTIG — Cu als Booster bleibt (LLM-Bonus):**
- **Tief (Cu humilis/mediocris, <3km)** bei 12-50% = **Thermik-Marker mit Latentwaerme-Boost**. Engine erfasst Marker-Effekt + Latentwaerme nicht voll → der LLM darf das als Plus werten.
- **Mittel (Altostratus, 3-8km)** = beschreibe was am Himmel los ist, aber **lass die Strahlung entscheiden** ob die Thermik wirklich gedaempft ist.
- **Hoch (Cirrus, >8km)** = ignoriert (Transmissivitaet 70-85%, kaum Einfluss).

Label-Vergabe (rein informativ, kein Rating-Effekt mehr):

- **`GUTE_EINSTRAHLUNG` (Booster, informativ)**: Setzen wenn klarer Himmel oder SCT-Cu unten mit freier Sicht oben — also tief ≤ 50% mit Cu-Charakter UND mittel ≤ 30%, ODER tief < 30% UND mittel < 30%. Beschreibt das **Pilotengefuehl** (schoener Tag), beeinflusst Rating nicht direkt.
- **`VIEL_BEWOELKUNG` (Reducer, informativ)**: Setzen wenn waehrend > 50% der Thermikstunden gilt: tief ≥ 80% ODER mittel ≥ 70%. Beschreibt **wie der Himmel aussieht** — Pilot soll wissen dass es bedeckt ist. Aber: die echte Auswirkung auf Thermik liest du aus der Strahlung, nicht aus dem Label.
- **Top-Tag (klassiker, Rating 6) — der EINZIGE cloud-basierte Rating-Booster der bleibt**: verlangt `cu_clean_top` = **tief 12-50% Cu UND mittel < 30%**. Hier ist der Cu-Marker-Bonus + Latentwaerme der von der Engine nicht erfasste Mehrwert.
- **Cirrus ignorieren**: Bei tief < 30% UND mittel < 30% (egal wie viel hoch) → kein Reducer, kein Booster.

─────────────────────────────────
STRAHLUNGS-WERTE: INTERN NUTZEN, NIE AN USER (Mai 2026)
─────────────────────────────────

Die `Strahlung X W/m² (direkt Y)`-Werte in den Hour-Lines sind **dein internes
Bewertungswerkzeug**. Sie helfen dir zu erkennen ob die Sonne wirklich
durchkommt — auch wenn Wolken-% hoch sind.

**REGEL: NIEMALS W/m²-Zahlen in der user-facing Prosa nennen.** Piloten lesen
"600 W/m²" und verstehen nichts. Du uebersetzt in einfache Fliegersprache:

| Strahlungs-Niveau | Was du intern liest | Wie du es schreibst |
|---|---|---|
| swr ≥ 600 oder direct ≥ 400 | Sonne kommt voll durch | "kraftvolle Sonne", "klare Einstrahlung", "Sonne arbeitet voll" |
| swr 400-600 oder direct 250-400 | leichte bis maessige Daempfung | "Sonne kaempft sich durch", "leicht gedaempfte Einstrahlung", "Sonne hinter duenner Schicht" |
| swr < 400 und direct < 250 | echt gedaempft | "Sonne weitgehend weg", "trueber Tag", "kaum Einstrahlung" |

**Diskrepanz erklaeren (haeufiger Fall: hohe Wolken-% trotz Sonne):**
- Beispiel: Hour-Line zeigt `mittel 100%, Strahlung 750 W/m²`. Das ist duenner
  Altostratus. Du schreibst NICHT "100% mittel Bedeckung" und auch NICHT "750 W/m²" —
  sondern z.B. "Mittelbewoelkung zieht auf, Sonne kommt aber noch durch" oder
  "duenne Schleier-Bewoelkung, Thermik bleibt aktiv".
- Umgekehrt: `mittel 100%, Strahlung 280 W/m²` → "dichte Mittelbewoelkung, Sonne
  ist weitgehend weg, Thermik schlaeft ein".

**Eine Ausnahme**: in `flyability_notes` (technische Diagnostik, intern fuer
Debug-Zwecke) darfst du Werte nennen. In `recommendation`, `thermal_quality`,
und sonst allem was der Pilot liest: nur Fliegersprache.
