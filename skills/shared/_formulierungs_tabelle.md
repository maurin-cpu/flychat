═══════════════════════════════════════════════
FORMULIERUNGS-TABELLE (TQ-Tags → natuerliche Sprache)
═══════════════════════════════════════════════

**WICHTIG:** In der JSON-Antwort NIEMALS die Tags selbst nennen (`[SHEAR-UNUSABLE]` etc.). Uebersetze in natuerliche Saetze, die ein Pilot sofort versteht.

Nutze diese Tabelle als Vorlage fuer `thermal_quality` und `recommendation`:

| Tag-Kombination                                    | Formulierung                                                                                              |
|----------------------------------------------------|-----------------------------------------------------------------------------------------------------------|
| `[SHEAR-DEGRADED]` allein                          | "Wind nimmt mit der Hoehe zu, die Thermik wird gekippt — Bart-Zentrierung schwieriger."                   |
| `[SHEAR-UNUSABLE]` allein                          | "Starke Windscherung zerreisst die Thermik. Die angezeigten Steigwerte sind theoretisch, real nicht nutzbar." |
| `[THERMAL-TORN-DEGRADED]`                          | "Thermik durch Wind gestoert — kleine, fleckige Baerte, schwer zu zentrieren."                            |
| `[THERMAL-TORN-UNUSABLE]`                          | "Thermik vom Wind zerrissen. Kein organisiertes Steigen mehr, nur noch Brocken."                          |
| `[THERMAL-ROUGH-DEGRADED]` *(nur Spots)*           | "Thermik ruppig wegen Boeigkeit. Steigen geht, aber unruhig."                                             |
| `[THERMAL-ROUGH-UNUSABLE]` *(nur Spots)*           | "Thermik extrem ruppig, Klapper-Gefahr im Bart."                                                          |
| `[THERMAL-WIND-DEGRADED]`                          | "Starker Grundwind in der Mischungsschicht — Blasen werden versetzt, kleine zerfasern. Bart schwer zu zentrieren." |
| `[THERMAL-WIND-UNUSABLE]`                          | "Grundwind so stark, dass sich keine organisierte Thermik bildet. Parcel-Steigen ist theoretisch, nicht nutzbar." |
| `[SHEAR-UNUSABLE]` + `[THERMAL-TORN-UNUSABLE]`     | "Wind zerreisst die Thermik vollstaendig. Trotz guter Parcel-Werte ist Thermikflug nicht sinnvoll; allenfalls Abgleiter im Leebereich." |
| `[THERMAL-WIND-UNUSABLE]` + `[SHEAR-UNUSABLE]`     | "Starker Grundwind plus Scherung — Thermik weder organisiert noch kohaerent. Abgleiter."                  |
| `[GUST-WARN]` + `[THERMAL-ROUGH-DEGRADED]` *(nur Spots)* | "Boeig am Boden und in der Thermik — nur erfahrene Piloten, ruhigere Fenster abwarten."             |

─────────────────────────────────
KONSISTENZ-PFLICHT (Text muss zum Status passen!)
─────────────────────────────────

- `fly_status = "green"` oder `"violet"` (Gruen/Violett) → `thermal_quality` und `recommendation` MUESSEN positiv formuliert sein. NICHT "unbrauchbar", "nicht empfohlen" oder "Region meiden" schreiben.
- `fly_status = "gray"` (**Bronze / Abgleiter**) → ehrlich als schwach/unfliegbar beschreiben. Sprachgebrauch: "Bronze-Tag" oder "Abgleiter-Tag" — NIEMALS "grauer Tag".
- UNUSABLE-Randstunden (typisch morgens/abends mit <1 m/s Steigen) erwaehne als "morgens/abends ruppiger" — nicht den ganzen Tag abwerten.

**Abgrenzung:** Die Boeen-Tags `[GUST-*]` / `[ALOFT-*]` sind schon in Teil 1 behandelt. Die Thermik-Qualitaets-Tags zielen ausschliesslich auf die Nutzbarkeit des Auftriebs.

**Region-Kontext (Apr 2026):** Regionen haben keine Boeen mehr. `[THERMAL-ROUGH-*]` Tags existieren dort nicht. Thermik-Zerreiss-Signale kommen ueber drei Mechanismen:
- `[SHEAR-*]` — Windscherung (dU/dz)
- `[THERMAL-TORN-*]` — Buoyancy/Shear-Ratio
- `[THERMAL-WIND-*]` — mittlerer BL-Grundwind zu stark fuer Organisation der Blase
Erwaehne in Region-Analysen keine Boeigkeit und keine Klapper-Gefahr — nur diese drei Mechanismen.

─────────────────────────────────
BEWOELKUNGS-LABELS (Booster vs. Reducer — Matuszko/FAA)
─────────────────────────────────

- **`GUTE_EINSTRAHLUNG` (Booster)**: Optimale Cu-Bedeckung 12-50% (SCT) = staerkste Thermik. Latentwaerme-Boost, Cu markiert Einstiege, teils bewoelkter Himmel liefert sogar MEHR Solarenergie als wolkenlos (Streueffekt). Setzen wenn: max(tief, mittel) ≤ 50% mit Cu-Charakter ODER klarer Himmel (<30%). Auch blauer Himmel (0%) ist Booster.
- **`VIEL_BEWOELKUNG` (Reducer)**: Ab ~80% max(tief, mittel) wird Sonne weitgehend blockiert, Thermik stirbt. Setzen wenn: max(tief, mittel) ≥ 80% waehrend > 50% der Thermikstunden. Starke Ueberentwicklung (OD) mit Abschirmung gehoert auch hierher.
- **Neutralzone 50-80%**: Weder Booster noch Reducer — Daempfung beginnt (FAA 5/10-Regel), Thermik noch vorhanden aber abnehmend.
- **Cirrus ignorieren**: Nur hohe Bewoelkung (tief + mittel <30%) → WEDER Reducer NOCH Booster (Cirrus laesst 70-85% Solarstrahlung durch).
