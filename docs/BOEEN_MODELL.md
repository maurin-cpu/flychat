# Böen-Modell: Wie Wingcast Höhenböen berechnet

## Was berechnen wir?

Wingcast schätzt für jede Region und jeden Spot ein vertikales Böenprofil von 0 bis 4000m MSL in 250m-Schritten. Das Profil zeigt, wie stark die Böen auf jeder Höhe sind — entscheidend für die Flugplanung (Startplatzwahl, Sicherheit in der Höhe).

Das Ergebnis ist **monoton steigend**: Böen nehmen mit der Höhe nie ab. Physik: Mehr Höhe = mehr Exposition, weniger Terrain-Abschirmung.

---

## Datenquellen

| Quelle | Was sie liefert | Wo im Profil |
|--------|----------------|--------------|
| Open-Meteo Drucklevel (ICON-D2) | `wind_speed`, `wind_direction`, `temperature` auf 13 Druckniveaus (1000–600 hPa, ca. 100–4200m) | Freie Atmosphäre: Windprofil über das ganze Grid |
| Open-Meteo Bodendaten (ICON-D2) | `wind_gusts_10m`, `wind_speed_10m` am Referenzpunkt | Surface Anchor: Böen-Exzess am Boden |
| Spot-Wetterdaten (ICON-D2) | `wind_gusts_10m`, `wind_speed_10m` pro Spot | Zusätzliche Ankerpunkte (optional) |
| `regionen.csv` | `terrain_type` pro Region | Steuert Skalenhöhe H_g und OI-Korrelationslänge |

### Druckniveaus

```
1000, 975, 950, 925, 900, 875, 850, 825, 800, 775, 750, 700, 600 hPa
```

Nicht alle Niveaus haben Daten in ICON-D2 — fehlende werden übersprungen.

---

## Kernkonzept: Böen-Exzess

Böen setzen sich zusammen aus:

```
Böe = Mittlerer Wind + Böen-Exzess
```

Der **Böen-Exzess** ist die Differenz zwischen Böe und mittlerem Wind. Er entsteht durch Turbulenz (Terrain-Rauigkeit, Konvektion, Schwerewellen). In der freien Atmosphäre gibt es keine Terrain-Turbulenz, also konvergiert der Exzess gegen Null und die Böe nähert sich dem mittleren Wind.

---

## Die 3 Schritte des Regionsprofils

### Schritt 1: Drucklevel-Interpolation aufs Grid

Die Drucklevel-Daten liegen auf unregelmässigen Höhen. Sie werden linear auf ein regelmässiges Grid interpoliert (0–4000m, 250m-Schritte).

Das ergibt pro Gridpunkt:
- `wind_speed` — rein aus Drucklevel-Daten (freie Atmosphäre)
- `wind_direction` — rein aus Drucklevel-Daten
- `temperature` — rein aus Drucklevel-Daten
- `gust_bg` — Background-Böen aus dem exponentiellen Decay-Modell (siehe unten)

**Wichtig:** Der Surface-Anchor-Bodenwind wird hier **nicht** ins Windprofil eingefügt. Der Bodenwind (10m AGL) ist terrain-geschützt und viel tiefer als der freie Atmosphärenwind auf gleicher Höhe MSL. Ihn einzusetzen würde eine künstliche V-Form erzeugen.

### Schritt 2: Optimal Interpolation (OI) — Böen-Korrektur

Die OI korrigiert die Modell-Böen anhand von Beobachtungen (Anker).

#### a) Anker vorbereiten

Ein **Anker** ist ein Punkt, an dem Open-Meteo eine Boden-Böe liefert. Typisch: der Regions-Referenzpunkt (z.B. 1300m MSL für Glarnerland/Walensee).

**Wichtig — Regions-Boden­wind aus mehreren Referenzpunkten:**
Eine Region hat 4 Referenzpunkte (RPs) im GeoJSON. Früher wurde der Anker aus dem **ersten** RP genommen, was bei heterogenen Regionen wie "Mittelland Zentral" zu Verzerrungen führte: lag RP 1 zufällig in einem alpinen Modellpixel (z.B. Eriz auf 1662m), bestimmte dieser eine Punkt den gesamten Regions-Anker, obwohl die anderen 3 RPs im flachen Mittelland (~500m) lagen.

Heute wird `wind_speed_10m` als **Median über alle 4 RPs** gebildet und `wind_direction_10m` vektoriell gemittelt (zirkulär korrekt). `wind_gusts_10m` wird auf Region-Ebene **NICHT** aggregiert (Apr 2026) — Böen sind lokale Spitzenwerte und gehören auf Spot-Ebene. Implementiert in `_aggregate_wind_across_points()` in `fetch_weather.py`. Der Median ist robust gegen einen einzelnen Ausreisser-RP. Erst danach läuft die OI/Gauss-Kernel-Pipeline. Für Spots gilt das nicht — Spots nutzen ihren eigenen Punkt direkt.

Für den Anker wird der **Böen-Exzess relativ zum freien Atmosphärenwind** berechnet:

```
ws_free_atm = interpolierter Drucklevel-Wind bei Ankerhöhe
exzess = anchor_gust - ws_free_atm
```

Beispiel Glarnerland 10:00:
```
ws_free_atm bei 1300m = 10.4 km/h  (interpoliert aus Drucklevel-Daten)
anchor_gust           = 36.7 km/h  (Open-Meteo wind_gusts_10m)
→ exzess             = 26.3 km/h
```

Warum relativ zum freien Atmosphärenwind und nicht zum Bodenwind? Weil die OI den Exzess auf das Drucklevel-Windprofil addiert. Der Referenzrahmen muss derselbe sein, sonst gibt es Doppelzählung oder Unterkorrektur.

Falls Spots in der Region liegen, werden deren Bodenböen als zusätzliche Anker hinzugefügt (gleiche Logik: Exzess relativ zum freien Wind auf Spot-Höhe).

#### b) Gauss-Kernel: Exzess verteilen

An jedem Gridpunkt wird der Anker-Exzess per asymmetrischem Gauss-Kernel gewichtet:

```
Für jede Höhe z im Grid:
    w_sum = 0
    excess_sum = 0
    Für jeden Anker bei z_a mit Exzess e:
        dz = z - z_a
        L  = L_up   falls dz >= 0  (Gridpunkt über Anker)
             L_down falls dz <  0  (Gridpunkt unter Anker)
        w  = exp(-dz² / (2 × L²))
        w_sum    += w
        excess_sum += w × e

    gewichteter_exzess = excess_sum / w_sum
    korrigierte_böe = max(modell_böe, wind_speed + gewichteter_exzess)
```

Der Kernel ist **asymmetrisch** — das ist der Schlüssel:

- **L_up (aufwärts)**: Breit. Wie weit die Boden-Turbulenz nach oben reicht. Terrain-abhängig (siehe unten).
- **L_down (abwärts)**: Eng = H_g. Turbulenz zerfällt nach unten schnell.

#### c) Terrain-abhängige Korrelationslängen

Die entscheidende Frage: Wie weit reicht der Boden-Böenexzess nach oben?

| Terrain | L_up | Faktor | Physik |
|---------|------|--------|--------|
| Mittelland | 350m | 1.0 × H_g | Nur Oberflächenrauigkeit (Wald, Siedlung) |
| Jura | 450m | 1.2 × H_g | Ridge-Turbulenz an Jurakämmen |
| Voralpen | 550m | 1.3 × H_g | Talflanken |
| Alpen | 650m | 1.4 × H_g | Alpentäler |
| Hochalpin | 750m | 1.5 × H_g | Freie Exposition |

Referenzen:
- Letson et al. 2019: Turbulenz-Zerfallshöhe H_g = 300–600m → L_up ≈ 1.0–1.5 × H_g
- Dörnbrack & Nappo 1997: Kohärenzskala 2000–3000m (Schwerewellen-Phasenkopplung, NICHT Turbulenz-Decay)
- Validierung: Burnair-Vergleich zeigt Übereinstimmung mit L_up ≈ H_g

#### d) BLH-Kopplung — terrain-abhängig

L_up beschreibt vertikale Turbulenz-**Kohärenz** (Reibung, Schwerewellen). BLH (Boundary Layer Height) beschreibt thermische **Durchmischung**. Das sind zwei verschiedene physikalische Mechanismen — sie dürfen nicht blind ineinander gerechnet werden.

Frühere Implementierung war `L_up_eff = max(L_up_terrain, BLH)`. Das funktionierte im Hochalpinen, überzeichnete aber im Mittelland die Höhen-Böen massiv: Eine Bodenböe von 18 km/h wurde mit `L_up = 2200 m` (statt 350 m) bis auf 4000 m hochgereicht, obwohl die Turbulenz-Zerfallsskala im flachen Terrain physikalisch viel kürzer ist.

Aktuelle Logik (`get_effective_L_up` in `gust_calculator.py`):

```
L_up_eff = max(L_up_terrain, coupling × BLH)
```

mit terrain-abhängigem Kopplungsfaktor:

| Terrain | Coupling | Begründung |
|---------|----------|------------|
| Mittelland | 0.0 | Rein reibungsbestimmt — kein BLH-Boost |
| Jura | 0.05 | Minimaler Ridge-Effekt |
| Voralpen | 0.15 | Moderate Kopplung |
| Alpen | 0.20 | Alpentäler, begrenzte BLH-Erweiterung |
| Hochalpin | 0.25 | Freie Exposition, moderater Boost |

Physik dahinter:
- **Flach (Mittelland/Jura):** Konvektive Aufwinde durchmischen die unteren Hundert Meter, transportieren aber **keine Reibungs-Turbulenz** in die freie Atmosphäre. Die Reibungs-Skala bleibt das limitierende Mass.
- **Bergland (Voralpen aufwärts):** Mountain-Venting und orographisch erzwungene Konvektion koppeln die PBL aktiv an die freie Atmosphäre. Schwerewellen transportieren Boden-Turbulenz nach oben. Hier ist BLH ein berechtigter Boost.

**Beispiel Mittelland Ost, 13:00, BLH = 2200 m**:
- Alt: `L_up = max(1050, 0.0 × 2200) = 1050 m` → Bodenböe auf 3000m noch ~1.3% Anteil
- Neu: `L_up = max(350, 0.0 × 2200) = 350 m` → Bodenböe auf 1000m AGL nur noch ~1.7% Anteil

**Beispiel Hochalpin (Wallis-Pass), 13:00, BLH = 2500 m**:
- Alt: `L_up = max(2500, 1.0 × 2500) = 2500 m`
- Neu: `L_up = max(750, 0.25 × 2500) = 750 m` → drastisch reduziert, Burnair-konform

### Schritt 3: ~~Running Maximum~~ — entfernt (Apr 2026)

Früher wurde nach der OI-Korrektur ein Running-Maximum von unten nach oben angewandt, um Monotonie zu erzwingen. Diese Safety-Layer wurde entfernt:

- **Problem**: Zog lokale Wind-Dips (W(z)-Shear in Übergangsschichten) künstlich hoch und propagierte Bodenböen-Ausreißer bis in die freie Atmosphäre (36 km/h Mittelland-Artefakt auf 4 km). Der nachträgliche PBL-Cap war nur ein Pflaster.
- **Physik-Check**: Stull 1988 beschreibt vertikalen Impulstransport *innerhalb* der Mischungsschicht, aber die Turbulenz-**Amplitude** nimmt mit Distanz vom Boden ab — genau das was der Gauss-Kernel bereits modelliert. Running-Max interpretierte "Böen nehmen mit Höhe nicht ab" zu streng.
- **Ersatz**: Der OI-Gauss-Kernel (Schritt 2) plus PBL-Sigmoid-Blend erzeugen bereits eine physikalisch monoton abklingende T(z)-Kurve. Die Asymmetrie L_up ≠ L_down bleibt dadurch intakt.

T(z) folgt jetzt reiner Gauss-Decay aus dem Anker. Oberhalb PBL → T(z) → W(z).

---

## Beispiel: Glarnerland/Walensee, 10:00

Anker: 1300m MSL, Böe 36.7 km/h, freier Wind 10.4 km/h → Exzess 26.3 km/h

| Höhe | Wind (Drucklevel) | OI-Exzess | Böe (T(z) = ws + Exzess) |
|------|-------------------|-----------|--------------------------|
| 0m | 10.4 | 0.2 | 10.6 |
| 500m | 10.4 | 4.1 | 14.5 |
| 1000m | 10.4 | 20.8 | 31.2 |
| 1250m | 10.4 | 25.9 | 36.3 |
| 1500m | 10.3 | 22.0 | 32.3 |
| 2000m | 16.8 | 14.2 | 31.0 |
| 2500m | 25.2 | 7.6 | 32.8 |
| 3000m | 31.0 | 3.1 | 34.1 |
| 3500m | 40.0 | 1.0 | 41.0 |
| 4000m | 50.0 | 0.2 | 50.2 |

Der Exzess ist überall monoton abnehmend. Die Gesamtböe konvergiert in grosser Höhe zum reinen Höhenwind (kein Turbulenz-Exzess in der freien Atmosphäre).

---

## Skalenhöhe H_g: Exponentieller Turbulenz-Zerfall

H_g bestimmt, wie schnell der Böen-Exzess mit der Distanz vom Terrain abnimmt:

```
decay = exp(-distanz / H_g)
```

| Terrain | H_g | Physik |
|---------|-----|--------|
| Mittelland | 350m | Wald/Siedlung, lokale Turbulenz zerfällt schnell |
| Jura | 380m | Kämme erzeugen moderate orographische Effekte |
| Voralpen | 420m | Hügelland bis steile Talflanken |
| Alpen | 450m | Alpentäler, Kalkfelsen, kanalisierte Winde |
| Hochalpin | 500m | Freie Exposition, Gletscherwind |

Kalibriert gegen Burnair-Referenzwerte:
- Haslital 3000m MSL (z_agl=800m): Burnair ~30 km/h → H_g ≈ 500 für hochalpin
- Surselva 4500m MSL (z_agl=2300m): Burnair ~50 km/h → bestätigt H_g ≈ 500

Referenz: Letson et al. 2019 — Skalenhöhen 300–600m für flaches Terrain.

Fallback ohne bekannten Terrain-Typ: Lineare Interpolation aus Elevation (800m MSL → H_g=350, 1800m MSL → H_g=500).

---

## Spot-Profil vs. Regions-Profil

### Spot-Profil (einzelner Flugspot)

Verwendet `estimate_altitude_gusts()` oder `estimate_altitude_gusts_multi_anchor()` direkt auf den Drucklevel-Daten. Kein Regridding, kein OI, kein Running Maximum.

Modell: `Böe(z) = wind_speed(z) + delta_surface × exp(-|z_agl| / H_g)`

### Regions-Profil (Regionen-Seite)

Das Regionsprofil existiert in **zwei gleichwertigen Varianten**, die denselben OI-Kernel verwenden, sich aber im Sampling-Gitter unterscheiden:

**A. Chart-Pfad** (`web.py → format_altitude_wind_for_charts()`)
1. Drucklevel → 250m-Grid-Interpolation (0–4000m AGL)
2. OI-Korrektur auf dem Grid mit Surface Anchor + Spot Anchors (`_oi_gust_correction()`)
3. Running Maximum bottom-to-top

**B. Chat/LLM-Klassifizierer-Pfad** (`chat_engine.py → _build_single_region_context()`)
1. `estimate_altitude_gusts_multi_anchor()` direkt auf Pressure-Levels
2. `apply_oi_gust_correction()` auf denselben Pressure-Levels (kein Grid)
3. Running Maximum bottom-to-top

Beide Pfade liefern praktisch dieselben Werte (Mittel-Diff ≈ 0.25 km/h, siehe `debug_scripts/find_chart_chat_diff.py`). Die kleine Rest-Diff stammt nur daher, dass das Chart auf einem feineren 250m-Grid smoothed wird, während der Klassifizierer genau auf den ~13 Pressure-Level-Höhen rechnet. Das ist **gewollt** — so sieht der LLM dieselben Böenwerte wie der Benutzer im Chart.

Der OI-Ansatz fusioniert Modell-Background (Drucklevel) mit Beobachtungen (Anker) — ein Standardverfahren in der Meteorologie (Gandin 1963).

---

## Klassifizierung: ALOFT-GUST-DANGER (UND-Regel)

Der Chat/LLM-Klassifizierer (`chat_engine.py → _build_single_region_context()`) prüft pro Region und Stunde, ob im Flughöhenbereich `[elevation_ref, elevation_ref + 1000m]` ein Höhenwind-Risiko besteht. Die Klassifizierung `ALOFT-GUST-DANGER` wird nur ausgelöst, wenn **beide** Bedingungen gleichzeitig erfüllt sind:

```
g_val > 40 km/h  AND  ws_val > 30 km/h
```

- `g_val` — OI-korrigierter Böenwert auf dem Pressure-Level (nach `apply_oi_gust_correction()`)
- `ws_val` — Mittelwind auf dem Pressure-Level (rein aus ICON-D2, unkorrigiert)

**Begründung für das UND:**
Eine hohe Böenzahl allein reicht nicht — in thermisch durchmischten, synoptisch schwachen Lagen kann der Kernel einen Exzess hochskalieren, obwohl der eigentliche Mittelwind harmlos ist (z.B. 15 km/h Mittelwind + 35 km/h Exzess → 50 km/h Böe). Solche Situationen sind kein Höhenwind-Problem, sondern typisches Mittelland-Turbulenz-Verhalten und sollten den Klassifizierer nicht triggern.

Umgekehrt fängt die UND-Regel echte Höhenwind-Lagen sauber: dort ist **der Mittelwind** schon stark (>30 km/h), und die Böen liegen darüber.

Der Check läuft auf exakt denselben Werten, die auch im Chart angezeigt werden (siehe OI-Konsistenz oben), so dass Chart und LLM-Klassifizierung nie auseinanderlaufen können.

---

## Dateien

| Datei | Funktion |
|-------|----------|
| `gust_calculator.py` | Kern-Algorithmen: `estimate_altitude_gusts()`, `estimate_altitude_gusts_multi_anchor()`, `apply_oi_gust_correction()`, `collect_gust_anchors()`, `get_scale_height()`, `get_oi_scale_lengths()` |
| `web.py` → `format_altitude_wind_for_charts()` | Orchestrierung: Grid-Aufbau, OI-Korrektur (`_oi_gust_correction()`), Running Maximum, Chart-Datenformat |
| `web.py` → `_oi_gust_correction()` | OI-Kernel (Chart-Pfad): Gauss-gewichtete Verteilung des Böen-Exzesses auf das 250m-Grid |
| `chat_engine.py` → `_build_single_region_context()` | Chat/LLM-Klassifizierer: ruft `estimate_altitude_gusts_multi_anchor()` + `apply_oi_gust_correction()` direkt auf Pressure-Levels (kein Grid) |
| `station_observations.py` | Stationsdaten-Sammlung, Forecast-Observation Pairing, Bias-Berechnung |
| `data/regionen.csv` | Terrain-Typ pro Region (mittelland, jura, voralpen, alpen, hochalpin) |
| `data/station_observations.db` | SQLite: Stationen, Beobachtungen, Forecast-Paare (für Bias-Korrektur) |
| `config.py` | Druckniveaus (`PRESSURE_LEVELS`), API-Parameter, Multi-Modell-Konstanten, Station-Settings |

---

## Multi-Modell Böen-Vergleich und Bias-Korrektur

Zusätzlich zum bestehenden Höhenprofil-Modell wird die Qualität der Boden-Böen (`wind_gusts_10m`) durch zwei Massnahmen verbessert:

### 1. Multi-Modell Vergleich (CH1 + CH2 + ICON-D2)

Statt sich auf ein einziges Modell zu verlassen, werden Bodenböen von 3 Modellen geholt:

| Modell | Auflösung | Horizont | Rolle |
|--------|-----------|----------|-------|
| ICON-D2 | 2 km | 2 Tage | Hauptmodell (Wind + Pressure Levels) |
| ICON-CH1 | 1 km | ~33h | Höchste Auflösung, beste Geländeeffekte |
| ICON-CH2 | 2 km | 5 Tage | MeteoSwiss-Version, Vergleich Tag 0–5 |

**Merge-Strategie:** `wind_gusts_10m` = Maximum aller verfügbaren Modelle (konservativ/sicher für Piloten). Einzelwerte bleiben als `_ch1`/`_ch2`/`_d2` Felder für Transparenz erhalten.

**API-Budget:** CH1 ≈ 1.2 + CH2 ≈ 3.0 = ~4.2 gewichtet zusätzlich pro Lauf (vernachlässigbar).

### 2. Stationsdaten-basierte Bias-Korrektur

Laufend werden ICON-D2 Forecasts mit echten Stationsmessungen verglichen (via winds.mobi API, ~500 CH-Stationen). Daraus wird ein Korrektur-Bias pro Spot berechnet (exponentiell gewichteter Mittelwert der Fehler, letzte 14 Tage).

Der korrigierte `wind_gusts_10m` Wert fliesst in den Gauss-Kernel für die Höhenböen-Berechnung ein — die gesamte Kette profitiert von der Korrektur.

**Auch Regionen erhalten eine Bias-Korrektur**: Dafür werden alle Spots ermittelt, die geografisch im Regions-Polygon liegen UND innerhalb ±600m der `elevation_ref` der Region. Aus deren Spot-Biases wird der Median gebildet und auf die Regions-Böen angewandt (mit derselben ±15 km/h Cap und 0.5 km/h Threshold wie bei Spots). Der Höhenfilter verhindert, dass exponierte Gipfelspots eine Mittelland-Region verzerren.

Details: Siehe [STATION_BIAS_KORREKTUR.md](STATION_BIAS_KORREKTUR.md)

---

## Referenzen

- **Stull 1988**: *An Introduction to Boundary Layer Meteorology* — Mixed-layer Turbulenztheorie, Begründung für monoton steigende Böen
- **Letson et al. 2019**: Skalenhöhen 300–600m für flaches Terrain (Gust-Decay)
- **Dörnbrack & Nappo 1997**: Vertikale Kohärenzskala orographischer Schwerewellen (2000–3000m)
- **Sharman et al. 2012**: Turbulenz-Transport über Bergzonen
- **Gandin 1963**: Optimal Interpolation in der Meteorologie
- **ECMWF IFS Cy35r1+**: Konvektiver Böenterm (Parametrisierung)
- **Burnair**: Schweizer Gleitschirm-Wetterdienst (Kalibrierungsdaten)
