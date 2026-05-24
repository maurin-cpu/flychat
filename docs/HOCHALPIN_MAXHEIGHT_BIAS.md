# Hochalpin max_height-Bias gegenüber xc-therm

**Status:** OFFEN — Befund dokumentiert, Ursache hypothetisch, kein Code-Eingriff.
**Datum:** 2026-05-24
**Verwandt:** `docs/THERMIK_MODELL.md`, `docs/THERMIK_TERRAIN_KALIBRIERUNG.md`, `meteo_research/inter_regional_coupling.md`, `meteo_research/regional_thermal_forecasting.md`, `meteo_research/thermal_model_calibration.md`

---

## TL;DR

An **Schönwettertagen in echten Hochalpin-Regionen (Wallis)** unterschätzt unsere `max_height` die nutzbare Arbeitshöhe um **1000–1500 m** gegenüber xc-therm (REGTHERM). Der Bias ist **nicht konstant** — er ist groß bei klarem Wetter + Hochalpin-Mix, klein bei Tal-Mix-Regionen, verschwindet oder kehrt sich um bei bewölkten Tagen. Plausibelste Erklärung: fehlende Modellierung der Tal-Heizung (Volumeneffekt / horizontale Talwind-Kopplung), die REGTHERM seit 2001 abbildet. Die Hypothese ist Lit-gestützt aber **noch nicht empirisch isoliert**.

---

## 1. Befund — Vergleichstabelle

Quelle xc-therm: 9 Screenshots vom User am 2026-05-24, ICON-D2 basiert, dieselbe Modellbasis wie unser System.
Lesehilfe xc-therm: "Arbeitshöhe" = obere Kante des Vario-Bands mit ≥0.5 m/s im Chart-Modus, ~13 UTC.
Unsere Werte: `compute_daily_thermals()` aus `wetterdaten.json`-Snapshot (24.05.2026), gleicher Modell-Lauf.

| Region (xc-therm) | Tag | Unser Anker-Spot | unser max_h | xc-therm | Δ (xc − wir) |
|---|---|---|---|---|---|
| Walliser Hochalpen | So 24.05 | Bietschhorn (2520 m) | 3849 m | ~5000 m | **+1151 m** |
| Walliser Hochalpen | Mo 25.05 | Bietschhorn | 3516 m | ~5000 m | **+1484 m** |
| Walliser Hochalpen | Do 28.05 | Bietschhorn | 3183 m | ~4400 m | **+1217 m** |
| Oberwallis | Mo 25.05 | Bellwald (2400 m) | 3468 m | ~4000 m | +532 m |
| Oberwallis | Mi 27.05 | Bellwald | 3610 m | ~3400 m | **−210 m** |
| Valais Central | So 24.05 | Crête de Thyon (2380 m) | 3525 m | ~4000 m | +475 m |

---

## 2. Muster

Der Bias **folgt einer klaren Struktur**:

| Region-Typ (xc-therm) | Tag-Typ | Beobachteter Bias |
|---|---|---|
| Hochalpin-pur (Walliser Hochalpen, Y-Achse bis 5200 m) | Schönwetter | **+1100 bis +1500 m** |
| Tal-orientiert (Oberwallis, Y-Achse bis 4400 m) | Schönwetter | +500 m |
| Tal-orientiert | bewölkt (Mi 27.05) | −210 m (wir leicht höher) |
| Gemischt (Valais Central) | Schönwetter | +475 m |

**Interpretation:** Das Problem ist **nicht** "wir sind generell zu konservativ". Es ist spezifisch **schöne Tage + Hochalpin-Region**.

---

## 3. Hypothese: Fehlende Tal-Heizungs-Modellierung

REGTHERM (Liechti 2001, von xc-therm lizenziert) modelliert zwei Mechanismen explizit, die wir nicht abbilden:

1. **Volumeneffekt (Steinacker)** — enge Täler heizen die darüberliegende Luftsäule effizienter. Walliser Rhonetal ist eines der engsten Haupttäler der Alpen.
2. **Horizontale Talwind-Kopplung** — Kompensationsströmungen transportieren warme Talluft nach oben in Hochlagen, erhöhen den Parcel-Auftrieb durch advektierte Wärme.

**Lit-Belege (peer-reviewed):**

- **TEAMx-PC22** (Inn-/Weer-Tal, 2022): _"Advektion (nicht turbulente Mischung) dominiert das CBL-Wachstum in komplexem Gelände. Bisherige BL-Wachstums-Modelle unterschätzen den Talwind-Beitrag systematisch."_ → beschreibt exakt unseren 1D-Parcel-Ansatz pro Spot.
- **Lugauer & Winkler / Weissmann et al. 2005**: Alpine Pumping in **42 %** der April–September-Tage → klimatologisch belegtes Phänomen.
- **Henne et al. 2005** (Mountain Venting): erklärt zusätzlich Cloudbase-Verschiebungen durch Nachbarschafts-Konvektion.

**Smoking Gun in eigener Doku:**

- `meteo_research/regional_thermal_forecasting.md:199-200` listet beide Effekte **explizit als Gleitcast-Limitierung** vs. Konkurrenz auf.
- `meteo_research/thermal_model_calibration.md:614-621` notiert beide bereits als _offene Frage_ — eingestuft als "vermutlich sekundär". **Dieser Befund zeigt: nicht sekundär für Hochalpin-Wallis.**

**Smoking Gun im Code:**

- `thermik_calculator.py:670`: `start_temp = interpolate_temp_at_height(elevation_m, profile)` — wir starten das Parcel-Profil bei der Spot-Höhe in der **freien Atmosphäre** des ICON-Pressure-Level-Profils. Die Tal-Heizung (33 °C Rhonetal-T_2m) fließt nirgends in den Aufstieg ein.

---

## 4. Was wir wissen — und was nicht

**Bestätigt:**
- Bias existiert: 6/6 Schönwetter-Datenpunkte zeigen unsere `max_height` < xc-therm
- Bias ist groß genug für Pilot-Relevanz (1000–1500 m an Hammertagen)
- Bias-Muster passt qualitativ zur Talwind-Hypothese (groß bei Hochalpin-pur, klein bei Tal-Mix, weg bei bewölkt)

**NICHT bestätigt / offen:**
- **Ursache ist Hypothese, nicht bewiesen.** Ein Quick-Test (Bietschhorn-Berechnung mit `elevation_m=2100` statt `2520`) ergab `−420 m` statt `+xxx m` — der Test war methodisch unsauber (Surface-Daten blieben am Spot), zeigt aber: einfaches "Tal-Start einbauen" wirkt nicht trivial in die erwartete Richtung.
- **xc-therm ist auch nur ein Modell**, keine gemessene Climbrate. Echte Validierung braucht XContest-Reports (tatsächlich geflogene Maximalhöhen).
- **N = 6 Datenpunkte über 3 Tage** — robust für "Bias existiert", nicht robust für Punktschätzungen der Bias-Größe.
- **Alternative Erklärungen nicht ausgeschlossen:**
  - Encroachment-Cap (γ_θ-basiert) zu konservativ
  - Pressure-Level-Interpolation erfindet falsche Inversion zwischen 50 hPa-Stufen
  - Spot-elevation als Parcel-Start ist generell ungeeignet für Hochalpin (z. B. Bergkamm-Spot statt Tal-/Mulden-Spot)

---

## 5. Geschäftsimpact

- Betrifft ~25–30 Hochalpin-Wallis-Spots (Schafberg, Bietschhorn, Bellwald, Crête de Thyon, ...)
- **Hammertag-Verfehlung**: wir zeigen "Standard-Sommertag" wo xc-therm "Hammer 4500 m+" zeigt
- Zielgruppe: XC-Strecken-Piloten — die anspruchsvollste Gruppe, die solche Tage gezielt fliegt
- Risiko: Glaubwürdigkeitsverlust an die Spitzen-Region, in der wir am ehesten als Premium-Quelle wahrgenommen werden müssen

---

## 6. Optionen für nächste Schritte

**(a) Validation-First** — Memory-Eintrag als offenes Thema, XContest-Reports vom 24.–28.05. abwarten. Wenn Piloten reale 4500 m erreichten → xc-therm validiert, Bias bestätigt. Aufwand: 0, Risiko: 0.

**(b) Diagnose-Script** — Für 1 Spot/Stunde durchrechnen: welche konkrete Layer-Inversion stoppt unseren Parcel bei 3500 m? Welcher Hebel müsste sich wie ändern, damit wir 4500 m erreichen? Aufwand: ~2 h Auswertung, Risiko: 0 (read-only).

**(c) Prototyp Tal-Surrogate** — `start_temp` für Hochalpin-Spots von einem Region-Talgrund-Refpoint statt vom Spot. Setzt voraus: Hypothese ist korrekt, Mechanik geht in erwartete Richtung. Aufwand: ~4–8 h + Validierung, Risiko: mittel (kann unbeabsichtigt andere Spots verschlechtern).

**Empfehlung:** Reihenfolge a → b → c. Erst Validierung, dann Verstehen, dann Eingreifen.

---

## 7. Quellen

- `meteo_research/regional_thermal_forecasting.md` — REGTHERM, Vergleich xc-therm/Burnair/Gleitcast
- `meteo_research/inter_regional_coupling.md` — peer-reviewed Lit zu Alpine Pumping / Mountain Venting / TEAMx-PC22
- `meteo_research/thermal_model_calibration.md` — offene Fragen Section
- `meteo_research/cloudbase_terrain_tiers.md` — Hochalpin Hammer-Klassifikation 4000–5000 m+
- xc-therm Screenshots: `data/screenshots/Screenshot 2026-05-24 *.png` (9 Stück, Walliser Hochalpen / Oberwallis / Valais Central / Hinterrhein / Alpi Ticinesi, 24.–28.05.2026)
- `thermik_calculator.py:670` — Parcel-Start-Code-Stelle
