═══════════════════════════════════════════════
THERMIK-QUALITAETS-TAGS (Phase 2 — Fliegbarkeit)
═══════════════════════════════════════════════

Diese Tags gelten ausschliesslich fuer **Fliegbarkeit (Teil 2)**. Sie duerfen NIEMALS als Grund fuer `not_safe` oder `conditional` verwendet werden — Sicherheit ist bereits in Phase 1 entschieden.

- `[SHEAR-DEGRADED]` / `[SHEAR-UNUSABLE]` — **Windscherung**: Wind dreht/beschleunigt mit Hoehe, Blase wird gekippt. Auswirkung: ruppige Aufstiege, Klapper-Risiko *(Spot + Region)*.
- `[THERMAL-TORN-DEGRADED]` / `[THERMAL-TORN-UNUSABLE]` — **Buoyancy/Shear-Ratio schlecht**: Auftrieb zu schwach gegenueber Scherung, Blase zerrissen. Auswirkung: zerfetzte Thermik, schwer zentrierbar *(Spot + Region)*.
- `[THERMAL-ROUGH-DEGRADED]` / `[THERMAL-ROUGH-UNUSABLE]` — **ruppige Thermik durch Boeigkeit** (Gust-Factor). Auswirkung: mechanische Klapper-Gefahr in der Steigphase *(nur Spots — braucht Boeen-Daten)*.
- `[THERMAL-WIND-DEGRADED]` / `[THERMAL-WIND-UNUSABLE]` — **mittlerer Grundwind durch die Mischungsschicht zu stark**, Blase organisiert sich nicht. Quelle: BL-Mean-Wind gegen zone-abhaengige Schwelle (Research Abschnitt 3.1) *(Spot + Region)*.

**DEGRADED**-Suffix = sportlicher, aber fliegbar. **UNUSABLE**-Suffix = Thermik praktisch unbrauchbar fuer entsprechende Stunde.

`THERMAL-ROUGH-FRAGMENTED` (separate Variante) = Thermik zu schwach, nicht gefaehrlich. Geht in Qualitaets-Bewertung ein, aber nicht als Klapper-Trigger.

Diese Tags erscheinen im Kontext-String und fliessen in deine Sub-Rating-Bewertung ein — DEGRADED = sportlich aber fliegbar, UNUSABLE = Thermik praktisch unbrauchbar fuer diese Stunde.
