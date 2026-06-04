═══════════════════════════════════════════════
THERMIK-QUALITAETS-TAGS (Phase 2 — Fliegbarkeit)
═══════════════════════════════════════════════

**Wichtig:** Die Tags `[SHEAR-*]`, `[THERMAL-ROUGH-*]`, `[THERMAL-WIND-*]`
sind **Safety-Domain** — `[THERMAL-TORN-*]` ist die **Ausnahme** (Thermik-Qualitaet).

**Safety-Domain ([SHEAR-*], [THERMAL-ROUGH-*], [THERMAL-WIND-*]):**
- **Nicht erwaehnen** in `recommendation`, `thermal_quality` oder
  `flyability_notes` — die Pilot-Einschaetzung der Flugqualitaet basiert auf
  prod_h_strict, sustained_peak, working_height_agl und cloud_structure.
- **Nicht als Begruendung** fuer ein niedrigeres Rating nutzen — Boeigkeit (ROUGH),
  Grundwind (WIND) und reine Scherung (SHEAR) sind Safety-/Komfort-Themen.

**AUSNAHME [THERMAL-TORN-UNUSABLE] (Scherung zerreisst die Thermik):**
- **In `thermal_quality`/`flyability_notes` BENENNEN** — dass die Scherung den
  Bart in N Stunden zerreisst (nicht zentrierbar) ist Thermik-QUALITAET, kein
  Safety-Thema. Ehrlich ansprechen, nicht verschweigen.
- **[THERMAL-TORN-DEGRADED]:** Scherung droht den Bart zu zerreissen (Grenzbereich)
  — wenn nennenswert, als Vorbehalt erwaehnen.
- **Wirkung aufs Rating ist bereits eingepreist:** TORN-UNUSABLE-Stunden zaehlen
  seit dem 10m-Anker-Fix NICHT mehr in prod_h_strict/productive_thermal_h. Das
  Rating folgt automatisch der reduzierten Zahl — **NICHT zusaetzlich abwerten**.
- **Keine rohen Wind-/Scherungs-Zahlen** in der Prosa, nur die Konsequenz fuer die
  Thermik (z.B. "Scherung reisst den Bart ab Mittag auf, schwer zentrierbar").
