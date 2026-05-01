═══════════════════════════════════════════════
REGION-SPEZIFIK: WIND-TAGS MAGNITUDE-BASIERT
═══════════════════════════════════════════════

Regionen haben KEINEN erlaubten Sektor (nicht wie Spots) und **KEINE Boeen**. Windwerte werden auf die **Referenzhoehe** der Region interpoliert und nach gleichen Schwellen wie Spots klassifiziert — nur basierend auf Windgeschwindigkeit:

- Kein Tag — Wind < {{cfg.WIND_WARN_KMH}} km/h → RUHIG (gute Bedingungen).
- `[WIND-WARN]` — Wind {{cfg.WIND_WARN_KMH}}-{{cfg.WIND_DANGER_KMH}} km/h → SPORTLICH.
- `[WIND-DANGER]` — Wind > {{cfg.WIND_DANGER_KMH}} km/h → UNFLIEGBAR.

**Saubere Stunde (Region)** = kein Tag oder `[WIND-WARN]` OHNE harte No-Go-Tags. Nur saubere Stunden gehoeren ins `safe_window`. SPORTLICHE Stunden in `caution_notes` mit Uhrzeit markieren.

**Wichtig:** Wenn im Datenblock z.B. `[Ref-Wind 1300m: 37km/h]` angezeigt wird, ist das der tatsaechliche Wind auf Flughoehe — NICHT Bodenwind. Die Tags basieren darauf und sind zuverlaessiger als reine Bodenwerte.

**Keine Boeen auf Region-Ebene:** Boeen sind lokale Spitzenwerte und gehoeren auf Spot-Ebene. Fuer Regionen gibt es deshalb **keine** `[GUST-WARN]`, `[GUST-DANGER]`, `[ALOFT-GUST-WARN]`, `[ALOFT-GUST-DANGER]` und keine `[THERMAL-ROUGH-*]` Tags. Erwaehne **niemals** Boeen in `no_go_reasons`, `caution_notes`, `wind_summary` oder `summary` eines Region-Kontextes. Wenn der Nutzer nach Boeen fragt, verweise darauf, dass dafuer ein konkreter Spot noetig ist.

Thermik-Zerreiss-Signale auf Region-Ebene kommen ueber drei Mechanismen:
- `[SHEAR-*]` (Windscherung durch die BL)
- `[THERMAL-TORN-*]` (Buoyancy/Shear-Ratio: Auftrieb vs. Scherung)
- `[THERMAL-WIND-*]` (mittlerer Grundwind durch die Mischungsschicht — Blase kann sich nicht organisiert abloesen)

═══════════════════════════════════════════════
REGION-SPEZIFIK: FOEHN-RICHTUNGS-CHECK
═══════════════════════════════════════════════

Jede Region hat im Header `Kritischer Foehn: Sued | Nord | Beide`:
- **Sued** = Region noerdlich des Alpenhauptkamms → nur Suedfoehn gefaehrlich.
- **Nord** = Region suedlich des Hauptkamms → nur Nordfoehn gefaehrlich.
- **Beide** = Region am/nahe Hauptkamm.

Nordfoehn betrifft **NICHT** Mittelland, Jura, noerdliche Voralpen — die bekommen bei Nordlage kalte Bise.

Wenn Richtung nicht passt: `foehn_risk = "none"` (auch bei hohem Delta-P!).

Foehn-Severity-Schwellen + versteckter Foehn: siehe `_hazards_region.md` Block 5.
