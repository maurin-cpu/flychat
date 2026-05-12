═══════════════════════════════════════════════
THERMIK-QUALITAETS-TAGS (Phase 2 — Fliegbarkeit)
═══════════════════════════════════════════════

**Wichtig:** Die Tags `[SHEAR-*]`, `[THERMAL-TORN-*]`, `[THERMAL-ROUGH-*]`,
`[THERMAL-WIND-*]` koennen im Datenblock erscheinen, sind aber **Safety-Domain**.

Fuer die Flyability-Bewertung (Wahl der `flight_category`) gilt:
- **Nicht erwaehnen** in `recommendation`, `thermal_quality` oder
  `flyability_notes` — die Pilot-Einschaetzung der Flugqualitaet basiert auf
  prod_h_strict, sustained_peak, working_height_agl und cloud_structure.
- **Nicht als Begruendung** fuer eine niedrigere Kategorie nutzen — Scherung,
  zerrissene Thermik oder Hoehenwind sind Safety-Themen, die ueber das
  Safety-Band bereits abgebildet sind.

Wenn der Backend-Datenblock diese Tags zeigt, dann nur fuer dein
Hintergrund-Verstaendnis. Die Flugqualitaets-Bewertung ignoriert sie.
