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

**Hinweis:** EINGEKESSELT-Muster und Wind-Trend-Bewertungen stehen zentral im TREND-VOKABULAR (`_hazard_blocks.md`). Wende sie pro Gefahrenblock an, nicht hier. Die alte OVERRIDE B (WIND-DIRECTION-KONTEXT) ist **entfallen** — sie wurde durch die Start-Fenster-Regel in Block 2 (`_hazard_blocks.md`) abgeloest.

═══════════════════════════════════════════════
STATUS-ABLEITUNG (finaler Schritt Teil 1)
═══════════════════════════════════════════════

1. Lies die Zeile `Laengstes zusammenhaengendes Start-Fenster: Xh` aus der WIND-ZUSAMMENFASSUNG. **Diese Zahl ist verbindlich** (System-berechnet, X = zusammenhaengende saubere Stunden = WIND-OK + keine DANGER-Tags).
2. Pro Gefahrenblock: Trend-Muster bestimmen (siehe TREND-VOKABULAR), EINGEKESSELT-Sonderfaelle pruefen.
3. Wende OVERRIDE A (35%-Regel) an.
4. Leite Status nach Start-Fenster-Regel ab:
   - **safe**: Start-Fenster ≥ {{cfg.CLEAN_WINDOW_GREEN_HOURS}}h UND Verhaeltnis ≥ 60% UND kein EINGEKESSELT-Sonderfall greift UND kein Foehn-Verbot. WIND-WRONG-Stunden NACH dem Fenster sind kein Hindernis — sie werden ggf. via Richtungsdreher-Anmerkung in `caution_notes` erwaehnt, nicht als Downgrade.
   - **conditional**: Start-Fenster {{cfg.CLEAN_WINDOW_MIN_HOURS}}h bis < {{cfg.CLEAN_WINDOW_GREEN_HOURS}}h ODER Fenster ≥ {{cfg.CLEAN_WINDOW_GREEN_HOURS}}h aber mehrheitlich SPORTLICH ODER Verhaeltnis 35-60% ODER EINGEKESSELT-WARN-Fall.
     - Thermik in diesen Stunden entscheidet ueber `flight_type`: Peak ≥ 1.0 m/s + productive_thermal_h ≥ 2 → "Thermikflug"; sonst "Abgleiter" (`flyability_tier: "gray"`).
     - Stunden AUSSERHALB des Fensters duerfen UNFLIEGBAR oder WIND-WRONG sein — das Fenster bleibt nutzbar.
   - **not_safe**: Start-Fenster < {{cfg.CLEAN_WINDOW_MIN_HOURS}}h ODER Verhaeltnis < 35% mit EINGEKESSELT-Muster ODER EINGEKESSELT-DANGER-Sonderfall greift ODER Foehn/Gewitter dominiert.
