═══════════════════════════════════════════════
TAGES-OVERRIDE (kontextuelle Regeln, nach den Gefahrenbloecken)
═══════════════════════════════════════════════

**WICHTIG: Du rechnest NICHTS.** Das System liefert alle Zahlen im TAGESPROFIL — du liest und beurteilst.

─────────────────────────────────
OVERRIDE A — 35%-REGEL (Verhaeltnis ablesen)
─────────────────────────────────

Lies im TAGESPROFIL den Wert hinter `Verhaeltnis sauber/gesamt: X/Yh = Z%` (sauber = RUHIG + SPORTLICH):
- **Z < 35**: Tag ueberwiegend gefaehrlich. Selbst wenn ein 4h-Fenster existiert, ist der Pilot von Risikostunden umgeben → Status maximal **conditional**, eher **not_safe** falls eingekesselt.
- **Z zwischen 35 und 60**: Mischtag. Status kann `safe` sein, wenn das Fenster durchgehend RUHIG UND nicht eingekesselt ist.
- **Z > 60**: Normalfall — Status nach Standard-Logik.

**Pflicht:** Wenn `→ ACHTUNG Verhaeltnis < 35%` im TAGESPROFIL steht, MUSST du das in `caution_notes` oder `no_go_reasons` reflektieren.

─────────────────────────────────
OVERRIDE B — WIND-DIRECTION-KONTEXT (Spot-Modus)
─────────────────────────────────

Lies das Histogramm im TAGESPROFIL:
- `WIND-WRONG 8h` bei nur 4h sauber → klares Signal instabiler Bedingungen → max **conditional**.
- Windrichtung im sauberen Fenster knapp innerhalb des Buffers und kurz danach rausgedreht → in `caution_notes` mit Uhrzeit erwaehnen.

**Hinweis:** EINGEKESSELT-Muster und Wind-Trend-Bewertungen stehen jetzt zentral im TREND-VOKABULAR (`_hazard_blocks.md`). Wende sie pro Gefahrenblock an, nicht hier.

═══════════════════════════════════════════════
STATUS-ABLEITUNG (finaler Schritt Teil 1)
═══════════════════════════════════════════════

1. Finde ALLE zusammenhaengenden sauberen Fenster (RUHIG + SPORTLICH, Definition siehe KERNREGEL in `_hazard_blocks.md`).
2. Pro Gefahrenblock: Trend-Muster bestimmen (siehe TREND-VOKABULAR), EINGEKESSELT-Sonderfaelle pruefen.
3. Wende OVERRIDE A (35%-Regel) und OVERRIDE B (WIND-DIRECTION) an.
4. Leite Status ab:
   - **safe**: Mindestens EIN sauberes Fenster ≥ 4 Stunden direkt hintereinander UND Verhaeltnis ≥ 60% UND kein EINGEKESSELT-Sonderfall greift UND kein Foehn-Verbot.
   - **conditional**: Mindestens EIN sauberes Fenster mit 4 Stunden, davon mehrheitlich SPORTLICH ODER eingeschraenkt durch Verhaeltnis 35-60% / EINGEKESSELT-WARN-Fall / VORSICHTS-Tags. ODER nur 3 saubere Stunden am Stueck — dann je nach Thermik in diesen 3h:
     - Gute Thermik (Peak ≥ 1.0 m/s UND productive_thermal_h ≥ 2 in den 3h) → `flight_type: "Thermikflug"`, normale Tier-Bewertung.
     - Schwache/keine Thermik → `flight_type: "Abgleiter"`, `flyability_tier: "gray"`.
     - Auch wenn Stunden AUSSERHALB des 3h-Fensters UNFLIEGBAR sind, bleibt das 3h-Fenster nutzbar.
   - **not_safe**: KEIN sauberes Fenster mit mindestens 3 Stunden am Stueck, oder Verhaeltnis < 35% mit EINGEKESSELT-Muster, oder EINGEKESSELT-DANGER-Sonderfall greift (siehe TREND-VOKABULAR), oder Foehn/Gewitter dominiert.
