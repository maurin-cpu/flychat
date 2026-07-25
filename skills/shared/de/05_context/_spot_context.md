═══════════════════════════════════════════════
SPOT-SPEZIFIK: SEKTOR + TAGESFENSTER
═══════════════════════════════════════════════

Im Spot-Modus hat der Startplatz einen erlaubten **Sektor** (Kompassbereich). Die Richtungs-Tags `[WIND-OK]` / `[WIND-WRONG]` gehoeren zur eigenen Kategorie **Tagesfenster** — siehe `_tagesfenster.md`. Der Code hat den Datenblock bereits ab dem ersten qualifizierenden Start-Fenster zugeschnitten.

**Saubere Stunde (Spot)** = `[WIND-OK]` UND kein DANGER-Tag. Nur saubere Stunden gehoeren ins `safe_window`. SPORTLICHE Stunden (mit WARN-Tag innen) dort explizit in `caution_notes` mit Uhrzeit markieren.

**Fuer Flyability:** Nur `[WIND-OK]`-Stunden innerhalb des `safe_window` sind fuer Thermik-/Flugqualitaets-Einschaetzung relevant.

═══════════════════════════════════════════════
SPOT-BEMERKUNGEN (Override-Layer)
═══════════════════════════════════════════════

Der Datenblock enthaelt **Bemerkungen** (z.B. "Soaring nur bei Bise 15-25 km/h", "bei Suedstau Abloesungsgefahr"). Bemerkungen sind spot-spezifisches Lokalwissen und **ueberschreiben generische Regeln**. Behandle sie als Nachjustierungs-Schritt — erst normal bewerten, dann Bemerkung anwenden.

**Format im Datenblock**:
- `Bemerkung Flug: …`             — flug-/qualitaetsrelevanter Rohtext.
- `Rating-Regel Flug: …`          — die daraus **operationalisierte Regel** (Bedingung → Rating-Wirkung), direkt unter der Bemerkung.
- `Bemerkung Sicherheit: …`       — sicherheitsrelevanter Rohtext (Hindernisse, Rotor/Lee, Sperren, Verbote, Anspruch).
- `Rating-Regel Sicherheit: …`    — die operationalisierte Safety-Wirkung (WETTER-TRIGGER/STATISCH/SPERRE/… → caution/no_go/safe_window).

In der **Safety-Phase**: nur `Bemerkung Sicherheit` + `Rating-Regel Sicherheit` verarbeiten.
In der **Flyability-Phase**: nur `Bemerkung Flug` + `Rating-Regel Flug` verarbeiten.

**Die `Rating-Regel`-Zeile ist VERBINDLICH.** Sie nimmt dir die Interpretation ab: Schwellen und Wirkung stehen fertig da. Pruefe nur noch, welche Stunden im Datenblock die Bedingung erfuellen, und wende die genannte Wirkung an (Caps/Gates gelten auch gegen anderslautende generische Rating-Regeln, siehe `_flight_subratings_spot.md` HARTE SCHRANKEN). Fehlt die `Rating-Regel`-Zeile, operationalisiere die Bemerkung selbst:

**Schritt 2 — EXTRAHIEREN (nur wenn keine Rating-Regel-Zeile da ist):**
Pro Bemerkungs-Trigger identifiziere: (a) Parameter (Wind/Richtung/Niederschlag/Jahreszeit/Tageszeit/Thermik), (b) Schwellwert, (c) betroffene Phase (Start/Flug/Landung/Soaring/Thermik), (d) welche Tagesstunden triggern im aktuellen Datenblock.

**Schritt 3 — NACHJUSTIEREN: Nur betroffene Felder aendern, Rest bleibt**

| Betroffener Aspekt | Zielfeld(er) |
|---|---|
| Startverbot / Landezone / Hangflug-Ausschluss (SAFETY) | `no_go_reasons` (wenn ganzer Tag) oder `caution_notes` (Teilstunden), `safe_window` verkuerzen, ggf. `primary_no_go` |
| Spot-spezifische Turbulenz/Abloesung (SAFETY/BEIDES) | `caution_notes` mit Uhrzeit, `wind_shear` oder `wind_summary`, Status mind. `conditional` |
| Mindestwind fuer Soaring nicht erreicht (FLYABILITY) | `flight_type = "Abgleiter"`, `flight_duration_estimate` kurz, `soaring_options` erklaert warum, `recommendation` ehrlich, `xc_potential = "low"`, `experience_rating` gemaess `Rating-Regel Flug` kappen (typisch graduell: knapp unter Minimum → Cap 2-3, deutlich darunter → 1) |
| Mindestwind erreicht → Soaring moeglich (FLYABILITY) | `flight_type = "Soaring"` oder `"Soaring+Thermik"`, `soaring_options` mit konkreter Einschaetzung, `experience_rating = 1` (reines Soaring zaehlt als abgleiter; Soaring-Moeglichkeit nur in Prosa) |
| Thermik-Einschraenkung (Tageszeit/Saison, FLYABILITY) | `thermal_quality`, `peak_climb_rate` ggf. runter, `experience_rating` entsprechend tiefer waehlen, `best_window` anpassen |
| `bemerkung_check` (Flyability-JSON) | IMMER: kurze Zusammenfassung welche Bemerkung griff und welche Felder nachjustiert wurden |

**Beispiele:**
- *Baldern, Prognose 8-12 km/h, Rating-Regel "Soaring erst ab 15 km/h; unter 15 → Cap 2-3, unter 10 → 1"*: FLYABILITY. Bei 8 km/h (unter 10 in den meisten Stunden): `experience_rating=1`, `flight_type="Abgleiter"`, `xc_potential="low"`, `recommendation`: "Wind zu schwach fuer Soaring am Baldern — Abgleiter moeglich." Bei 12 km/h: Cap 2-3 anwenden — egal wie gut die Thermik-Inputs sind. Safety-Felder unveraendert.
- *Spot mit "bei Suedstau Abloesungsgefahr", Foehn-Sued aktiv*: BEIDES. Safety → `caution_notes`, Flyability → `thermal_quality` erwaehnt zerrissene Thermik.
- *"Landewiese bei Regen gesperrt", RAIN-WARN-Stunden*: SAFETY. → `no_go_reasons`, `safe_window` endet vor Regen.
