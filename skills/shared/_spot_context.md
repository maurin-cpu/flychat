═══════════════════════════════════════════════
SPOT-SPEZIFIK: WIND-TAGS RICHTUNGSBASIERT
═══════════════════════════════════════════════

Im Spot-Modus hat der Startplatz einen erlaubten **Sektor** (Kompassbereich). Die Richtungs-Tags `[WIND-OK]` / `[WIND-WRONG]` sind **Startbarkeits-Filter, keine Hazards** — vollstaendige Regeln im STARTBARKEITS-FILTER-Block in `_input_map.md`.

**Saubere Stunde (Spot)** = `[WIND-OK]` UND kein DANGER-Tag. Nur saubere Stunden gehoeren ins `safe_window`. SPORTLICHE Stunden (mit WARN-Tag innen) dort explizit in `caution_notes` mit Uhrzeit markieren.

**Fuer Flyability:** Nur `[WIND-OK]`-Stunden innerhalb des `safe_window` sind fuer Thermik-/Flugqualitaets-Einschaetzung relevant.

═══════════════════════════════════════════════
SPOT-BEMERKUNGEN (Override-Layer)
═══════════════════════════════════════════════

Der Datenblock enthaelt **Bemerkungen** (z.B. "Mindestwind 15 km/h fuer Soaring", "bei Suedstau Abloesungsgefahr", "Landewiese bei Regen gesperrt"). Bemerkungen sind spot-spezifisches Lokalwissen und **ueberschreiben generische Regeln**. Behandle sie als Nachjustierungs-Schritt — erst normal bewerten, dann Bemerkung anwenden.

**Schritt 1 — KLASSIFIZIEREN: Was ist betroffen?**
- **SAFETY** — Bedingung beeinflusst, ob der Flug sicher moeglich ist (Startverbot, Landezone, gefaehrliche Wettersituation). Beispiele: "bei Nordlage gesperrt", "Landewiese bei Regen gesperrt", "bei Suedstau Abloesungsgefahr".
- **FLYABILITY** — Bedingung beeinflusst Flugqualitaet, aber Flug bleibt grundsaetzlich sicher. Beispiele: "Mindestwind 15 km/h fuer Soaring", "Thermik schwach bis 11h".
- **BEIDES** — Bedingung hat beide Komponenten getrennt.

In der Safety-Phase: nur SAFETY/BEIDES-Anteil verarbeiten, FLYABILITY ignorieren.
In der Flyability-Phase: nur FLYABILITY/BEIDES-Anteil verarbeiten, SAFETY ist bereits durch Phase 1 abgedeckt.

**Schritt 2 — EXTRAHIEREN:**
Pro Bemerkungs-Trigger identifiziere: (a) Parameter (Wind/Richtung/Niederschlag/Jahreszeit/Tageszeit/Thermik), (b) Schwellwert, (c) betroffene Phase (Start/Flug/Landung/Soaring/Thermik), (d) welche Tagesstunden triggern im aktuellen Datenblock.

**Schritt 3 — NACHJUSTIEREN: Nur betroffene Felder aendern, Rest bleibt**

| Betroffener Aspekt | Zielfeld(er) |
|---|---|
| Startverbot / Landezone / Hangflug-Ausschluss (SAFETY) | `no_go_reasons` (wenn ganzer Tag) oder `caution_notes` (Teilstunden), `safe_window` verkuerzen, ggf. `primary_no_go` |
| Spot-spezifische Turbulenz/Abloesung (SAFETY/BEIDES) | `caution_notes` mit Uhrzeit, `wind_shear` oder `wind_summary`, Status mind. `conditional` |
| Mindestwind fuer Soaring nicht erreicht (FLYABILITY) | `flight_type = "Abgleiter"`, `flight_duration_estimate` kurz, `soaring_options` erklaert warum, `recommendation` ehrlich, `xc_potential = "low"`, `xc_rating` 1–3 |
| Mindestwind erreicht → Soaring moeglich (FLYABILITY) | `flight_type = "Soaring"` oder `"Soaring+Thermik"`, `soaring_options` mit konkreter Einschaetzung |
| Thermik-Einschraenkung (Tageszeit/Saison, FLYABILITY) | `thermal_quality`, `peak_climb_rate` ggf. runter, `thermal_rating` anpassen, `best_window` anpassen |
| `bemerkung_check` (Flyability-JSON) | IMMER: kurze Zusammenfassung welche Bemerkung griff und welche Felder nachjustiert wurden |

**Beispiele:**
- *Balderen, Prognose 8-12 km/h, Bemerkung "Mindestwind 15 km/h fuer Soaring"*: FLYABILITY. Override: `flight_type="Abgleiter"`, kurze Dauer, `xc_potential="low"`, `recommendation`: "Wind zu schwach fuer Soaring am Balderen — Abgleiter moeglich." Safety-Felder unveraendert.
- *Spot mit "bei Suedstau Abloesungsgefahr", Foehn-Sued aktiv*: BEIDES. Safety → `caution_notes`, Flyability → `thermal_quality` erwaehnt zerrissene Thermik.
- *"Landewiese bei Regen gesperrt", RAIN-WARN-Stunden*: SAFETY. → `no_go_reasons`, `safe_window` endet vor Regen.
