# Mindest-Banddicke für produktive Thermik-Stunden

> **Scope:** Physikalische Herleitung der Funktion
> `thermik_calculator.min_band_depth(climb_peak_ms, terrain_zone)`, die
> die alte fixe Konstante `config.PRODUCTIVE_BAND_DEPTH_MIN = 400` ersetzt.
>
> **Kontext:** Eine Stunde gilt als "produktiv", wenn sie mindestens drei
> zentrierbare Kurbeln mit Netto-Höhengewinn erlaubt. Das ist eine
> Geometrie-Bedingung an die Banddicke `band_depth = h_max − elevation`,
> NICHT eine reine Climb-Bedingung.
>
> **Verwandte Doku:**
> [`thermal_model_calibration.md`](thermal_model_calibration.md) für die
> Berechnung von `h_max` selbst,
> [`docs/THERMIK_TERRAIN_KALIBRIERUNG.md`](../docs/THERMIK_TERRAIN_KALIBRIERUNG.md)
> für die Terrain-Zonen-Definition.

---

## 1. Problemstellung

Die alte Konstante `PRODUCTIVE_BAND_DEPTH_MIN = 400 m` filterte alle
Stunden mit Bandtiefe < 400 m aus dem `productive_thermal_h`-Zähler. Zwei
Schwächen:

1. **Climb-unabhängig:** Eine Stunde mit 0.8 m/s Peak braucht weniger
   Banddicke als eine mit 2.5 m/s Peak (siehe Sektion 3) — der Pilot
   verbraucht im starken Bart mehr Höhe pro Kurbel und braucht mehr
   Kurbel-Reserve.
2. **Terrain-blind:** Im Hochgebirge stützt der Hang die Thermik, ein
   200-m-Bart über einer 1000-m-Wand ist nutzbar. Im Mittelland fehlt
   diese Stütze; dort braucht's mehr Reserve.

Empirisch zeigte sich, dass Jura-/Voralpen-Tage mit 1.5 m/s Peak und
~350 m Bandtiefe in der Praxis fliegbar sind (Pilotenberichte, eigene
Flüge), vom Modell aber als "band-flach" verworfen wurden.

---

## 2. Geometrie der zentrierbaren Kurbel

### 2.1 Sink-Polare und Kurbeldauer

Der EN-B-Standardschirm hat ein Trim-Sinken `sink_PG ≈ 1.0 m/s`. Im 360°
mit 45° Schräglage und 25 m Radius beträgt die Kurbeldauer:

```
turn_seconds = 2π × r / v_TAS
             = 2π × 25 / (~12.5)
             ≈ 7 s
```

(v_TAS bei 45° = v_trim × 1/cos(45°) ≈ 9 × 1.4 ≈ 12.5 m/s).

### 2.2 Peak vs. effektiver Steigwert

Der gemeldete `climb_peak_ms` ist der Spitzenwert in der Bartmitte. Der
Pilot fliegt aber nie genau im Zentrum — Bart-Wandern, Anflug-Fehler und
Schräglage bringen ihn in den Randbereich. Bei parabolischem Profil
(Standard-Modell, siehe `thermik_calculator._thermalRateAtAltitude`) ist
der Mittelwert über die mittlere Hälfte des Bartradius:

```
profile_factor = mean of (1 − r²/R²) over r ∈ [0, R/2]
               = 1 − (1/3) × (1/2)²
               ≈ 0.75
```

Effektives Steigen pro Kurbel: `avg_climb = profile_factor × peak`.

### 2.3 Netto-Höhengewinn pro Kurbel

```
net_per_turn = (avg_climb − sink_PG) × turn_seconds
             = (0.75 × peak − 1.0) × 7
```

Für `peak < 1/0.75 ≈ 1.33 m/s` wird `net_per_turn ≤ 0` — keine
Banddicke der Welt rettet die Stunde, der Schirm sinkt schneller als
die Luft steigt. Die Funktion gibt in diesem Fall `inf` zurück.

---

## 3. Banddicken-Bedingung

### 3.1 Zentrierungstoleranz

Der Pilot muss innerhalb der Banddicke `band_depth = h_max − elevation`
operieren. Untere Grenze: Startplatz (kein Kurbeln unter Hangkante).
Obere Grenze: `h_max` (Wolkenbasis oder Top der Mischung). Zusätzlich
braucht's an beiden Enden eine Zentrierungstoleranz:

```
centering_tol = 50 m (je Seite)
```

— deckt Bart-Wandern (≈ 30 m über 3 Kurbeln) und Anflug-Vertical (Pilot
trifft den Bart nicht punktgenau ab Startplatz).

### 3.2 Bedingung für drei Kurbeln

Drei Kurbeln müssen in das nutzbare Subband passen (Mitte 50 % des
Bands ist konservativ, da Inversionsdeckel oft "weicher" ist als
modellseitig vermutet):

```
3 × net_per_turn  ≤  0.5 × band_depth  −  2 × centering_tol
3 × (0.75 × peak − 1.0) × 7  ≤  0.5 × band_depth  −  100
```

Auflösen nach `band_depth`:

```
band_depth  ≥  2 × [3 × 7 × (0.75 × peak − 1.0)]  +  200
            =  42 × (0.75 × peak − 1.0)  +  200
            =  31.5 × peak  −  42  +  200
            =  31.5 × peak  +  158
```

### 3.3 Safety-Faktor

Reale Bedingungen sind schlechter als die ideale Geometrie:

- **Turbulenz-Scallop:** Aufwindkern wandert, Pilot verliert pro Bart
  ≈ 20 m Höhe durch Re-Zentrieren.
- **Anflug-Verlust:** Übergang zwischen Bärten kostet Höhe (G/R 8 → 50 m
  Verlust pro 400 m horizontal).
- **Eintritts-Marge:** Erste Kurbel "fängt" den Bart oft nicht sofort.

Empirische Pauschale: **safety_factor = 1.4**. Damit:

```
min_band_base  =  1.4 × (31.5 × peak + 158)
               =  44.1 × peak  +  221.2
```

---

## 4. Terrain-Differenzierung

Im Gebirge ist der Bart von Hangthermik gestützt — Aufwindkern hängt
am Felsgrat, wandert weniger horizontal, ist robuster gegen Wind.
Pilotenberichte und Standard-Literatur (Martens "Thermal Flying" Kap.
7; Pagen "Understanding the Sky") sind hier konsistent: Hochalpine
Bärte sind über Hänge gut zentrierbar mit dünner Banddicke.

Im Flachland fehlt die Hang-Stütze; freie konvektive Bärte über
ebenem Gelände driften, mäandern und zerfallen schneller. Mittelland-
Piloten brauchen mehr Reserve.

Empirische Terrain-Faktoren (multiplikativ auf `min_band_base`):

| Zone        | Faktor | Begründung                                       |
|-------------|--------|--------------------------------------------------|
| mittelland  | 1.00   | Volle Reserve, keine Stütze, freier Konvektion   |
| jura        | 0.90   | Hangstütze schwach (kleine Hügel), Reserve hoch  |
| voralpen    | 0.80   | Klare Hangstütze, mittlere Robustheit            |
| alpen       | 0.65   | Robuste Hangbärte, Pilot fliegt enger am Grat    |
| hochalpin   | 0.50   | Felswand-Bärte, sehr gut zentrierbar             |

---

## 5. Konkrete Werte

Beispielrechnung für drei typische Peak-Climbs:

| peak [m/s] | base [m] | mittelland | jura | voralpen | alpen | hochalpin |
|------------|----------|------------|------|----------|-------|-----------|
| 1.0        | inf      | inf        | inf  | inf      | inf   | inf       |
| 1.5        | 287      | 287        | 258  | 230      | 187   | 144       |
| 2.0        | 309      | 309        | 278  | 248      | 201   | 155       |
| 2.5        | 331      | 331        | 298  | 265      | 215   | 166       |
| 3.0        | 354      | 354        | 318  | 283      | 230   | 177       |
| 4.0        | 398      | 398        | 358  | 318      | 259   | 199       |

(`base = 1.4 × (31.5 × peak + 158)`)

**Vergleich alte Konstante:** Die fixe Schwelle `400 m` lag damit für
fast alle realen Climb-Werte zu hoch — Mittelland erst bei ≈ 4 m/s
Peak, Hochalpin nie. Das matcht das beobachtete Verhalten ("zu viele
band-flach-False-Positives").

---

## 6. Implementierung

Code: `thermik_calculator.py` → `min_band_depth(climb_peak_ms, terrain_zone)`.

Verwendet in `engine/weather_context.py` an vier Stellen:

1. **Spot, produktive Stunde** (`_build_single_spot_context`):
   `band_usable = band_depth >= min_band_depth(h_climb, spot_terrain_zone)`
2. **Spot, Flyability-Timeline:** gleicher Check für `is_productive` +
   "band-flach"-Reason im Soaring-Fallback.
3. **Region, produktive Stunde** (`_build_single_region_context`):
   `band_usable_r = band_depth_r >= min_band_depth(h_climb, region_terrain_zone)`
4. **Region, Flyability-Timeline:** gleicher Check für `is_productive_r` +
   "band-flach"-Reason.

Die alte Konstante `config.PRODUCTIVE_BAND_DEPTH_MIN` wurde entfernt
(Kommentar in `config.py` als Migrations-Marker erhalten).

---

## 7. Quellen

- **Martens, B.:** *Thermal Flying — A Guide for Beginners and Experts*,
  Kap. 7 (Kurbelgeometrie, Sink-Polare EN-B).
- **Pagen, D.:** *Understanding the Sky*, Kap. "Working Thermals"
  (Bart-Wandern, Hangthermik-Stütze).
- **Eigene Flugauswertung:** Jura-/Voralpen-Tage 2024–2026 mit
  1.5–2.0 m/s Peak und 300–400 m Bandtiefe (XContest, eigenes Logbook).
- **Schirm-Daten:** Trim-Sinken ≈ 1.0 m/s für EN-B-Mittelklasse
  (Herstellerangaben Ozone Rush 6, Skywalk Tequila 6).
