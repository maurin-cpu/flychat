# Böen in der Höhe: Recherche, Methodenvergleich und Implementierung

## 1. Ausgangslage

Burnair zeigt Böen auf verschiedenen Höhenstufen (10m, 250m, 1500m, 2000m, 3000m, 4000m ASL).
Gleitcast zeigt aktuell nur Bodenböen (`wind_gusts_10m`) — in der Höhe nur mittleren Wind.

**Kernfrage:** Können Höhenböen direkt bezogen oder müssen sie berechnet werden?

---

## 2. Datenverfügbarkeit

### Open-Meteo API
- **Verfügbar:** `wind_gusts_10m` (Boden), `wind_speed_XXXhPa` + `wind_direction_XXXhPa` (13 Druckniveaus)
- **NICHT verfügbar:** `wind_gusts_XXXhPa` — existiert nicht in der API
- **TKE:** Nicht verfügbar in Open-Meteo

### NWP-Modelle (ECMWF IFS, GFS, ICON)
- Böen sind **diagnostische Variablen** — nur an der Oberfläche berechnet, NICHT auf Druckniveaus
- ECMWF berechnet Bodenböen aus: Oberflächenreibung, Windscherung, Stabilität, konvektiven Komponenten
- GFS nutzt PBL-Höhe und Wind am PBL-Top zur Böendiagnose
- **Kein NWP-Modell gibt Böen auf Druckniveaus aus**

### Kommerzielle Quellen
- **Burnair:** Zeigt Böen auf 6 Höhenstufen — Methode proprietär, nicht publiziert
- **XC Therm:** Nutzt Regtherm-Modell (Dr. Olivier Liechti, DWD) — keine Dokumentation zur Böenberechnung
- Beide verwenden vermutlich eigene Parameterisierungen oder kostenpflichtige Modelldaten

**Fazit: Höhenböen müssen berechnet werden.** Keine freie Datenquelle liefert sie direkt.

---

## 3. Wissenschaftliche Methoden

### 3.1 Gust Factor G(z) — Grundkonzept

```
G(z) = V_gust(z) / V_mean(z)
```

Der Gust Factor beschreibt das Verhältnis von Böenspitze zu mittlerem Wind. Gut dokumentiert:
- **Am Boden (10m):** G ≈ 1.3–1.8 (je nach Terrain und Stabilität)
- **Mit zunehmender Höhe:** G nimmt ab (logarithmisch/exponentiell)
- **In freier Atmosphäre (>PBL):** G → 1.0 (kaum Turbulenz)

**Einflussfaktoren:**
- Höhe über Grund (z)
- Rauhigkeitslänge (z₀) des Terrains
- Atmosphärische Stabilität
- Konvektion
- Mittlere Windgeschwindigkeit (inverser Zusammenhang)

**Quellen:**
- Variation of Gust Factors with Height (1968), J. Applied Meteorology
- Gust Factor Models (2024), Wiley, doi:10.1155/2024/9970264
- Gust factors over open water, Boundary-Layer Meteorology

### 3.2 Eurocode EN 1991-1-4 (Engineering Standard)

Definiert Turbulenzintensität als Funktion der Höhe:

```
I_v(z) = σ_v / v_m(z) = k_I / (c_o(z) × ln(z/z₀))
```

Böengeschwindigkeit:
```
v_gust(z) = v_mean(z) × (1 + g_p × I_v(z))
```

Wobei:
- `g_p` = Peak-Faktor (≈ 3.5 für 3s-Böe in 10min)
- `I_v(z)` = Turbulenzintensität (nimmt mit Höhe ab)
- `k_I` = Turbulenzfaktor (≈ 1.0)
- `c_o(z)` = Orographiefaktor
- `z₀` = Rauhigkeitslänge

**Terrain-Kategorien (z₀):**
| Kategorie | Beschreibung | z₀ (m) | z_min (m) |
|-----------|-------------|--------|-----------|
| 0 | See, Küste | 0.003 | 1 |
| I | Flaches Gelände | 0.01 | 1 |
| II | Mittel (Referenz) | 0.05 | 2 |
| III | Vorstädte, Wald | 0.3 | 5 |
| IV | Stadtgebiet | 1.0 | 10 |

**Quelle:** EN 1991-1-4:2005, Eurocode 1 — Einwirkungen auf Tragwerke, Teil 1-4: Windlasten

### 3.3 Exponentielles Abnahmemodell

Ansatz: Das turbulente Inkrement (Differenz Böe − Mittelwind) zerfällt exponentiell mit der Höhe:

```
G(z) = 1 + (G_10m - 1) × exp(-z / H_g)
```

Die Skalenhöhe H_g beschreibt, wie schnell die bodennahe Turbulenz mit der Höhe abklingt:
- **Literatur (flach):** H_g = 300–600m (Letson et al. 2019)
- **Implementiert (kalibriert gegen Burnair):**
  - Mittelland: 350m | Jura: 380m | Voralpen: 420m | Alpen: 450m | Hochalpin: 500m
- Kalibriert: Surselva 4500m + Haslital 3000m (April 2026)

**Quellen:**
- Letson et al. (2019): Skalenhöhen 300–600m für flaches Gelände
- ECMWF IFS Dokumentation: Exponentieller Zerfall des turbulenten Anteils

### 3.4 ECMWF Konvektiver Böenterm

Ab IFS Zyklus 35r1 trennt ECMWF Böen in mechanischen und konvektiven Anteil:

```
U_gust_conv = α_mix × max(0, U_850 - U_950)
```

- Konvektive Abwinde transportieren schnellere Höhenluft zum Boden
- α_mix = 0.6 (original), 0.3 (ab Cy47r3, konservativer)
- Kann mit CAPE skaliert werden: `G_conv_scale = √(CAPE / CAPE_ref)`

**Für Gleitcast relevant bei:**
- CAPE > 100 J/kg (Thermiktage)
- Gewitterlagen (CAPE > 800 J/kg)

**Quelle:** ECMWF Technical Memoranda, IFS Documentation Cy47r3

### 3.5 Deaves-Harris-Modell

- Basis für AS/NZS 1170.2 (Australischer Windstandard)
- Peak-Faktor ~3.7, nimmt mit Höhe ab
- Genauer als einfaches logarithmisches Profil in der Grenzschicht
- Berücksichtigt Grenzschichthöhe explizit

**Quelle:** Deaves & Harris (1978), A mathematical model of the structure of strong winds

### 3.6 Brasseur-Methode (Bergspezifisch)

- Schätzt Böen durch "Herabmischen" schnellerer Luft aus der Höhe
- **Besonders gut in komplexem Gelände (Alpen!)**
- Energetisches Kriterium: Turbulente kinetische Energie > Auftriebswiderstand
- Berücksichtigt lokale thermische Schichtung direkt
- Nachteil: Braucht TKE-Profile (bei Open-Meteo nicht verfügbar)

**Quelle:** Brasseur (2001), Development and application of a physical approach to estimating wind gusts

### 3.7 WMO-Standards

- Böe = **3-Sekunden-Maximum** in 10-Minuten-Messperiode
- Umrechnungsfaktoren 10min → 1min: 1.21 (Land), 1.11 (Küste onshore)
- Standardmesshöhe: 10m

**Quelle:** WMO Guide to Meteorological Instruments and Methods of Observation

### 3.8 Turbulenzintensität und Böenfaktor

Zwischen Böenfaktor und Turbulenzintensität besteht eine nahezu lineare Korrelation:

```
G = U + g × σ_u
TI = σ_u / U
```

- `g` = normalisierter Peak-Faktor (2.5–3.5, robust: 3.0)
- `σ_u` = Standardabweichung der Windgeschwindigkeit
- TI nimmt mit Höhe ab → G nimmt mit Höhe ab

Messungen an Masten (z.B. Høvsøre):
- 10m: G ≈ 1.4
- 100m: G ≈ 1.2
- Turbulenzintensität ist der dominierende Faktor, nicht der Peak-Faktor

---

## 4. Methodenvergleich für Gleitcast

### 4.1 Eurocode (logarithmisch) vs. Exponential

Beide Methoden nutzen den Boden-Gust-Factor als Anker. Der Unterschied liegt in der Höhenabnahme:

```
Eurocode:     G(z) = 1 + (G_sfc - 1) × [1/ln(z/z₀)] / [1/ln(10/z₀)]
Exponential:  G(z) = 1 + (G_sfc - 1) × exp(-z_agl / H_g)
```

**Numerischer Vergleich (G_surface = 1.67, Mittelland):**

| z_agl | Eurocode (z₀=0.3) | Exponential (H_g=350) | Erhaltenes Δ |
|-------|-------------------|-----------------------|-------------|
| 100m  | 1.404             | 1.504                 | Expo: 75%   |
| 500m  | 1.317             | 1.161                 | Expo: 24%   |
| 1000m | 1.290             | 1.039                 | Expo: 6%    |
| 2000m | 1.267             | 1.002                 | Expo: 0.3%  |
| 3000m | 1.255             | 1.000                 | Expo: ~0%   |

**Kernproblem Eurocode:** Die logarithmische Funktion konvergiert zu langsam gegen G=1.0.
Bei 3000m AGL behält der Eurocode noch 38% des Gust-Deltas — physikalisch unrealistisch
für die freie Atmosphäre. Das liegt daran, dass der Eurocode für Gebäudestatik bis ~200m
entwickelt wurde, nicht für Flughöhen von 2000–4000m AGL.

**Vorteil Exponential:** Konvergiert natürlich gegen 1.0, kein harter PBL-Cutoff nötig.
Bodennah (100m) etwas höhere Werte — realistischer, da dort die Turbulenz am stärksten ist.

### 4.2 Bewertung aller Methoden

| Methode | Stärke | Schwäche | Für Gleitcast |
|---------|--------|----------|-------------|
| Eurocode (log) | Gut dokumentiert, robust bis 200m | Konvergiert zu langsam über 1000m | ❌ Ungeeignet für Flughöhen |
| Exponential | Natürliche Konvergenz, einfach | Kein konvektiver Term | ✅ **Gewählt** |
| ECMWF konvektiv | Fängt Thermik-Downdrafts ab | Braucht CAPE-Kalibrierung | ⏳ Optionale Erweiterung |
| Deaves-Harris | Explizites PBL-Modell | Komplexer, kaum Mehrwert | ❌ Overengineered |
| Brasseur | Ideal für Alpen | Braucht TKE (nicht verfügbar) | ❌ Daten fehlen |

---

## 5. Implementierte Methode (gust_calculator.py)

### Gewählter Ansatz: Exponentielles Abnahmemodell mit terrain-abhängiger Skalenhöhe

**Schritt 1 — Gust Factor am Boden (bekannt):**
```
G_surface = wind_gusts_10m / wind_speed_10m
```
Liefert den tatsächlichen, modellberechneten Gust Factor am Boden (Anker).

**Schritt 2 — Skalenhöhe aus Terrain (data/regionen.csv):**
```
mittelland:  H_g = 350m   (Wald/Siedlung, lokale Turbulenz)
jura:        H_g = 380m   (Ketten/Kämme, Ridge-Turbulenz)
voralpen:    H_g = 420m   (Hügelland, steile Talflanken)
alpen:       H_g = 450m   (Alpentäler, kanalisierte Winde)
hochalpin:   H_g = 500m   (Gletscherwind, max. Reichweite)
```
Kalibriert gegen 2 Burnair-Referenzpunkte (Surselva 4500m, Haslital 3000m).
Werte liegen im Literaturbereich (Letson 2019: 300–600m für flach).

**Schritt 3 — Absolute Böendifferenz am Boden:**
```
ΔG_surface = wind_gusts_10m - wind_speed_10m   (km/h, max 30)
```

**Schritt 4 — Böen in der Höhe (ADDITIV):**
```
V_gust(z) = V_mean(z) + ΔG_surface × exp(-z_agl / H_g)
```

**Warum additiv statt multiplikativ?**
Das alte multiplikative Modell (`V_gust = V_mean × G`) versagte bei hochalpinen Spots
wo Höhenwind >> Bodenwind. Beispiel Haslital (2200m): Bodenwind 5 km/h, Böen 12 → G=2.4.
Auf 1500m MSL (unter Terrain!): Höhenwind 36 × G=2.4 = 86 km/h — absurd.
Das additive Modell projiziert nur die absolute Differenz (7 km/h) die mit Höhe abklingt.

### Guards

- **z_agl < 0** (unter Terrain): `V_gust = V_mean` — keine Böen (interpolierte Daten)
- **z_agl > PBL × 1.2**: `V_gust = V_mean` — über Grenzschicht, keine Turbulenz
- **ΔG_surface max 30 km/h** — darüber Konvektion/Sturm, Modell nicht gültig

### Terrain-Zuordnung H_g

Aus `data/regionen.csv` (29 Regionen, 5 Terrain-Typen):
- **mittelland**: H_g = 350m — Wald/Siedlung, lokale Turbulenz zerfällt schnell
- **jura**: H_g = 380m — Jura-Ketten, Ridge-Turbulenz
- **voralpen**: H_g = 420m — Hügelland bis steile Talflanken
- **alpen**: H_g = 450m — Alpentäler, Kalkfelsen, kanalisierte Winde
- **hochalpin**: H_g = 500m — Freie Exposition, Gletscherwind

Fallback (kein terrain_type): lineare Interpolation aus Elevation (350m bei ≤800m, 500m bei ≥1800m).

### Höhe über Grund (z_agl)

```
z_agl = altitude_msl - elevation_m
```
- Für Spots: `elevation_m` aus CSV
- Für Regionen: `elevation_ref` aus GeoJSON

### Guards und Randfälle

- `wind_speed_10m ≤ 0`: G nicht berechenbar → V_gust = V_mean
- `ΔG_surface` auf max 30 km/h geclampt (darüber Konvektion/Sturm)
- `z_agl < 1`: Boden-G verwenden
- `G(z) ≥ 1.0`: Böe kann nicht kleiner als Mittelwind sein

---

## 6. Mögliche Erweiterung: Konvektiver CAPE-Term

An Thermiktagen mit hohem CAPE können Downdrafts schnellere Höhenluft nach unten mischen.
Das rein mechanische Modell unterschätzt Böen in diesen Situationen.

**ECMWF-Ansatz adaptiert:**
```
G_conv(z) = √(CAPE / 1000) × α_mix × max(0, V_max_BL - V_z)
```
- `α_mix = 0.3` (konservativer ECMWF-Wert ab Cy47r3)
- `V_max_BL` = Windmaximum innerhalb der Grenzschicht
- Nur aktiv wenn CAPE > 50–100 J/kg

**Bewertung:** Genuiner Mehrwert an starken Thermiktagen und Gewitterlagen.
Alle Daten (CAPE, Windprofile) sind in Open-Meteo verfügbar.
Aktuell nicht implementiert — als optionale zweite Iteration geplant.

---

## 7. Validierung

### Plausibilitätschecks (additives Modell, ΔG_surface = 22 km/h):
- **Unter Terrain:** Keine Böen (reine Interpolation) ✅
- **z_agl=0 (Boden):** Voller Aufschlag (+22 km/h) ✅
- **300m AGL:** Mittelland +9.4, Hochalpin +12.1 km/h ✅
- **800m AGL:** Mittelland +2.2, Hochalpin +4.4 km/h ✅
- **1300m AGL:** Mittelland +0.5, Hochalpin +1.6 km/h ✅
- **2300m AGL:** ~0 (freie Atmosphäre) ✅
- **Über PBL:** Keine Böen ✅

### Erwartete Werte (additiv, ΔG=22 km/h):
| Höhe AGL | Δ Mittelland (H_g=350) | Δ Hochalpin (H_g=500) | Böe bei V_mean=25km/h |
|----------|------------------------|------------------------|----------------------|
| 0m       | +22.0                  | +22.0                  | 47 / 47 km/h         |
| 300m     | +9.4                   | +12.1                  | 34 / 37 km/h         |
| 800m     | +2.2                   | +4.4                   | 27 / 29 km/h         |
| 1300m    | +0.5                   | +1.6                   | 26 / 27 km/h         |
| 2300m    | +0.03                  | +0.2                   | 25 / 25 km/h         |

### Kalibrierung gegen Burnair (4 Iterationen):

| Iteration | Modell | H_g hochalpin | Surselva 4500m | Haslital 3000m | Burnair Ref |
|-----------|--------|--------------|----------------|----------------|-------------|
| v1 | multiplikativ | 1500 | 72 km/h | ~45 km/h | 50 / 30 |
| v2 | multiplikativ | 900 | 56 km/h | ~40 km/h | 50 / 30 |
| v3 | multiplikativ | 500 | ~51 km/h | ~31 km/h | 50 / 30 |
| **v4** | **additiv** | **500** | **48.2 km/h** | **29.4 km/h** | **50 / 30** |

**Fazit:** Wechsel von multiplikativ zu additiv löst das Kernproblem: Höhenwind >> Bodenwind
erzeugte mit dem Faktor-Modell absurde Werte (Wind 36 × G=2.5 = 89 km/h bei 1500m MSL
für einen 2200m-Spot). Das additive Modell projiziert nur die absolute Böendifferenz
(max 30 km/h) die exponentiell abklingt. H_g=350–500m im Literaturbereich.

---

## 8. Quellen

1. **EN 1991-1-4:2005** — Eurocode 1, Windlasten (Engineering Standard)
2. **Deaves & Harris (1978)** — Mathematical model of strong wind structure
3. **Brasseur (2001)** — Physical approach to wind gust estimation
4. **WMO Guide** — Meteorological Instruments and Methods of Observation
5. **Variation of Gust Factors with Height (1968)** — J. Applied Meteorology, 7(3)
6. **Gust Factor Models (2024)** — Wiley, doi:10.1155/2024/9970264
7. **ECMWF IFS Documentation** — confluence.ecmwf.int, Cy35r1+ konvektiver Böenterm
8. **Letson et al. (2019)** — Skalenhöhen für exponentiellen Turbulenz-Zerfall
9. **Høvsøre Mast Measurements** — Vertikale Böenfaktor-Profile bis 100m
