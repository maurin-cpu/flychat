# Windscherung und Thermik-Qualitaet

> **Scope:** Quantitative Schwellenwerte, ab wann Grundwind, Boeen und
> Windscherung die Thermik soweit stoeren, dass sie an Qualitaet verliert
> oder unfliegbar wird. Basis fuer ein neues Label-System in `chat_engine.py`
> analog zu `[GUST-WARN]`, `[RAIN-WARN]`, `[ALOFT-DANGER]`.
>
> **Kontext:** Das Flychat-Modell berechnet heute ein Thermik-Rating
> (`rating 1..10`, `climb_rate` in m/s) ueber `thermik_calculator.py` rein
> aus der parcel-based Auftriebsenergie und Senkel-Gradienten. Der Effekt
> von Windscherung — also das mechanische Zerreissen der Blase — wird
> bisher nicht explizit modelliert. Die Pressure-Level-Winde liegen aber
> bereits interpoliert auf 100-m-Raster vor (Schritt 1 der Terrain-
> Kalibrierung), sodass die Scherung direkt ableitbar ist.
>
> **Basis-Dokumente:**
> - [`thermal_model_calibration.md`](thermal_model_calibration.md)
>   (Auftriebs-Seite)
> - [`altitude_gust_estimation.md`](altitude_gust_estimation.md)
>   (Hoehen-Boeen / Turbulenz-Exzess)
> - [`docs/BOEEN_MODELL.md`](../docs/BOEEN_MODELL.md)
>   (2-Produkt-Architektur W(z) / T(z))

---

## 1. Problemstellung

Eine Thermikblase ist ein thermodynamischer Aufwindkoerper, der seine
Energie aus dem Temperaturueberschuss gegenueber der Umgebung bezieht.
Dieser Aufwind hat eine charakteristische Vertikalgeschwindigkeit `w*`
(Deardorff-Geschwindigkeit) und einen horizontalen Durchmesser `D`
(typisch 100–800 m in unseren Breiten).

Der Horizontalwind in der Mischungsschicht wirkt auf die Blase auf zwei
verschiedene Arten, die **nicht verwechselt werden duerfen**:

1. **Horizontalversatz** (drift): Die Blase wird als Ganzes verschoben.
   Das ist **kein Qualitaetsverlust**, solange der Versatz raeumlich
   konsistent ist — der Pilot kreist einfach mit dem Wind mit. Die
   Blase bleibt zentrierbar, ihr Durchmesser und ihre Steigwerte bleiben
   erhalten.

2. **Scherung / Distortion**: Der Wind aendert sich mit der Hoehe.
   Die Blase wird oben anders versetzt als unten. Je nach Verhaeltnis
   von Vertikalgeschwindigkeit zu Scher-Rate wird die Blase zu einem
   gekippten Zylinder, dann zu einem schraegen Band, schliesslich in
   Fragmente zerrissen.

Dazu kommt ein dritter Effekt:

3. **Boeigkeit / mechanische Turbulenz**: Kurzskalige Fluktuationen
   im Wind mischen die Blase von aussen mit der Umgebungsluft und
   fressen ihren Kern von aussen auf. Das wirkt staerker, je kleiner
   der Blasen-Durchmesser ist.

Die Kernfrage: **Ab welchen Schwellwerten dieser drei Effekte wird
die Thermik messbar schlechter, und ab welchen Schwellwerten ist sie
nicht mehr fliegbar?**

---

## 2. Physikalische Grundlagen

### 2.1 Deardorff-Geschwindigkeit (Auftriebs-Skala)

Der Auftriebsterm ist durch die konvektive Geschwindigkeitsskala
definiert (Deardorff 1970):

```
w* = [(g/T0) × (Q0 / (rho × cp)) × zi]^(1/3)
```

mit:
- `g/T0` ≈ 0.033 m/s² K⁻¹ — Auftriebskonstante
- `Q0` — oberflaechlicher fuehlbarer Waermestrom H (W/m²)
- `zi` — Mischungsschicht-Hoehe (m)

Typische Werte ueber CH-Gelaende im Fruehling:
- Flachland (H=150 W/m², zi=1500 m): `w* ≈ 1.5 m/s`
- Voralpen  (H=250 W/m², zi=2200 m): `w* ≈ 2.0 m/s`
- Hochalpin (H=350 W/m², zi=3000 m): `w* ≈ 2.5 m/s`

Im Peak einer gut organisierten Blase ist die tatsaechliche
Vertikalgeschwindigkeit `w_peak ≈ 1.5..2.5 × w*`, weil `w*` ein
raum-zeitlicher Mittelwert ueber die ganze Schicht ist.

### 2.2 Scher-Skala

Die relevante Windscherung ist der Gradient des Horizontalwind-
Betrages durch die Mischungsschicht:

```
dU/dz = (U_top − U_sfc) / zi    [m/s / m]
```

In der internationalen Literatur wird Scherung meist in **m/s pro km**
gemessen, oder wie in der praktischen Segelflug-Meteorologie in
**km/h pro 100 m**. Umrechnung:

```
1 km/h / 100 m  =  2.78 m/s / km
2 km/h / 100 m  =  5.56 m/s / km  ← Zerreiss-Schwelle nach meteoblue
3 km/h / 100 m  =  8.33 m/s / km  ← kritisch
```

### 2.3 Buoyancy-over-Shear-Ratio (B/S)

Das in der Segelflug-Meteorologie etablierte Kriterium stammt von
Jack Glendening (RASP / BLIPMAP) und vergleicht die Turbulenzproduktion
aus Auftrieb gegen die aus Scherung:

```
B/S = Produktion_Buoyancy / Produktion_Shear
```

Physikalisch entspricht das dem Kehrwert einer Art umgekehrten
Richardson-Zahl fuer die konvektive Grenzschicht. Glendening gibt
folgende empirische Schwellen an (RASP `B/S` Parameter):

| B/S       | Interpretation                          | Segelflug      | Gleitschirm    |
|-----------|-----------------------------------------|----------------|----------------|
| > 10      | Scherung vernachlaessigbar              | exzellent      | exzellent      |
| 5 – 10    | Scherung wird spuerbar                  | gut bis ok     | gut            |
| 3 – 5     | Scherung dominiert, Blasen kippen       | schwierig      | noch fliegbar  |
| < 3       | Blasen zerrissen                        | unfliegbar     | sehr ruppig    |
| < 1       | Kein kohaerenter Auftrieb               | unfliegbar     | unfliegbar     |

Der GS-Bereich vertraegt kleinere B/S weil er auch in kurzen,
kleinraeumigen Teilen noch kreisen kann — ein Segler braucht grosse,
runde Baerte.

### 2.4 Gust-to-Mean Ratio (Boeigkeitsfaktor)

Fuer die mechanische Durchmischung ist nicht der Absolutwind relevant,
sondern die **Amplitude der Fluktuationen** relativ zur Thermik-
Vertikalgeschwindigkeit:

```
GF = (gust − mean) / w*
```

Empirische Schwellen aus der Hangsoar-Literatur (Whiteman 2000,
Stull 1988):

| GF          | Effekt                                            |
|-------------|---------------------------------------------------|
| < 1         | Turbulenz schwaecher als Auftrieb, Blase intakt   |
| 1 – 2       | Blase fleckig, "Schweizer Kaese" im Kern          |
| 2 – 3       | Blase fragmentiert, nur noch Brocken              |
| > 3         | Keine kohaerente Blase mehr                       |

Faustformel des `gust_calculator.py` heute:
`turbulence_excess = max(0, wind_gusts_10m - W(10m))`. Dieser Exzess
`delta_gust` ist der Zaehler von GF. Den Nenner `w*` liefert das
Thermik-Modell bereits als `climb_rate` (= peak-w proxy).

### 2.5 Blasen-Groesse als Schutzfaktor

Groessere Blasen sind widerstandsfaehiger, weil ihr Verhaeltnis von
Volumen (Auftrieb ~ D³) zu Oberflaeche (Mischung ~ D²) mit `D`
waechst. Das erklaert, warum:

- **Flachland-Blasen (D ≈ 100–300 m)** schon bei 15–20 km/h Grundwind
  zerfasern — ihre Verweildauer in der scherenden Stroemung ist kurz.
- **Alpine Schlaeuche (D ≈ 300–800 m, aus Hangwindsystemen
  organisiert)** bis 25–30 km/h Grundwind und 2–3 km/h/100 m
  Scherung aushalten.

Dieses Skalen-Argument deckt sich 1:1 mit den Terrain-Zonen des
Flychat-Modells: `L_up` aus `gust_calculator.py` (mittelland=350 m,
hochalpin=750 m) ist die Turbulenz-Zerfallsskala (≈1.0–1.5×H_g,
Letson et al. 2019), nicht die Schwerewellen-Kohärenzskala.

---

## 3. Quantitative Schwellen (Synthese)

### 3.1 Grundwind in der Mischungsschicht

Der relevante Grundwind ist nicht das 10-m-Boden-Niveau, sondern der
**mittlere Wind ueber die Mischungsschicht**. Praktisch: Mittelwert
von `wind_speed_900hPa` bis `wind_speed_700hPa` (je nach BLH), oder
einfacher das 850-hPa-Niveau als Referenz fuer BLH ≈ 1500 m.

| Mittelwind BL | Effekt                                          | Zone-Modifikator       |
|---------------|-------------------------------------------------|------------------------|
| < 10 km/h     | Thermik stationaer, klassisch zentrierbar       | alle gleich            |
| 10 – 20 km/h  | **Optimum** — Abloesung sauber, gut organisiert | alle gleich            |
| 20 – 30 km/h  | Deutlicher Versatz, kleine Blasen zerfasern     | Flachland kritisch     |
| 30 – 40 km/h  | Nur grosse alpine Schlaeuche halten             | Hochalpin noch machbar |
| > 40 km/h     | Keine fliegbare Thermik                         | alle gleich            |

### 3.2 Vertikale Scherung durch die BL

Operationelle Zerreiss-Schwelle nach meteoblue und der
Segelflug-Literatur:

```
dU/dz < 1 km/h / 100 m   →  Thermik steht senkrecht
dU/dz < 2 km/h / 100 m   →  geneigt, aber geschlossen
dU/dz ≥ 2 km/h / 100 m   →  stark verformt, schwer nutzbar
dU/dz ≥ 3 km/h / 100 m   →  fragmentiert
```

Beispiel: Bodenwind 10 km/h, 850-hPa-Wind (ca 1500 m) 40 km/h.
Differenz = 30 km/h, Distanz = 1500 m. `dU/dz = 2 km/h / 100 m`.
Exakt der Grenzwert.

### 3.3 B/S-Ratio aus Flychat-Daten

Konkrete Formel, die mit den heute verfuegbaren Groessen berechenbar
ist:

```
w*       = climb_rate                           [m/s] — aus thermik_calculator
zi       = max_thermal_height − elevation_m     [m]   — aus thermik_calculator
U_top    = mean(wind_speed bei zi)              [m/s] — aus pressure_level_data
U_sfc    = wind_speed_10m                       [m/s] — aus hourly_data

dU_dz    = (U_top − U_sfc) / zi                 [1/s]

B_prod   = w*³ / zi                             [m²/s³]   (~Deardorff)
S_prod   = (dU_dz)² × |U_top − U_sfc|           [m²/s³]   (Shear Production)

B/S      = B_prod / S_prod                      [dimensionslos]
```

**Einfacher Praxis-Proxy** ohne Produktions-Formeln (fuer schnellen
Ueberschlag auf jeder Stunde):

```
simple_BS = w* / dU_dz × 100            [dimensionslos]
```

mit `dU_dz` in `km/h / 100 m` und `w*` in m/s. Eichung:
`w* = 2 m/s`, `dU_dz = 1 km/h / 100 m` → `simple_BS = 200` (sehr gut),
`w* = 2 m/s`, `dU_dz = 2 km/h / 100 m` → `simple_BS = 100` (mittel),
`w* = 1 m/s`, `dU_dz = 2 km/h / 100 m` → `simple_BS = 50` (schlecht).

Die Proxy-Schwellen muessen zur Standardform `B/S ≥ 10 = gut`
skaliert werden — siehe naechster Abschnitt.

### 3.4 Boeigkeitsfaktor

```
delta_gust  = wind_gusts_10m − wind_speed_10m       [km/h]
GF          = (delta_gust / 3.6) / climb_rate        [dimensionslos]
```

Schwellen aus Abschnitt 2.4:

| GF      | Label        |
|---------|--------------|
| < 1     | ok           |
| 1 – 2   | WARN         |
| ≥ 2     | DANGER       |

### 3.5 Konvektive Boeen-Korrektur

**Problem:** NWP-Modelle (ICON/COSMO) diagnostizieren `wind_gusts_10m` ueber
eine Parametrisierung, die sowohl mechanische als auch konvektive Turbulenz
erfasst. Auf ruhigen Thermiktagen (z.B. 8 km/h Mittelwind, 20 km/h Boeen,
2.0 m/s Steigen) stammt ein Grossteil des Boeen-Excess nicht aus schaedlicher
mechanischer Turbulenz, sondern aus der thermischen Konvektion selbst.

**COSMO/ICON Boeen-Diagnostik:**
```
V_gust = V_mean + alpha * sigma_u
```
wobei `alpha ≈ 3.0` (COSMO-Standard, Schulz & Heise 2003).

**Konvektiver Anteil (Panofsky et al. 1977):**
In freier Konvektion (Mixed-Layer Similarity) gilt:
```
sigma_u / w* ≈ 0.6
```
Damit wird der konvektive Beitrag zur Boen-Geschwindigkeit:
```
V_conv = alpha * 0.6 * w* ≈ 1.8 * w*
```

**Korrektur:**
Vor der GF-Berechnung wird die konvektive Baseline abgezogen:
```
total_excess    = (wind_gusts_10m - wind_speed_10m) / 3.6   [m/s]
conv_baseline   = BETA * climb_rate                          [m/s]  (BETA = 1.8)
mechanical_exc  = max(0, total_excess - conv_baseline)       [m/s]
GF              = mechanical_exc / climb_rate                [dimensionslos]
```

Wenn `mechanical_exc <= 0`, wird kein GF-Tag gesetzt (rein konvektive Boeen).

**Validierung (Beispielrechnungen):**

| Szenario           | Wind/Gust (km/h) | w* (m/s) | total_exc | conv_base | mech_exc | GF   | Tag            |
|--------------------|-------------------|----------|-----------|-----------|----------|------|----------------|
| Ruhiger Thermiktag | 8 / 20            | 2.0      | 3.33      | 3.60      | 0        | —    | sauber         |
| Mässig boeig       | 12 / 30           | 2.0      | 5.00      | 3.60      | 1.40     | 0.70 | sauber         |
| Windig             | 20 / 45           | 2.0      | 6.94      | 3.60      | 3.34     | 1.67 | DEGRADED       |
| Lee-Turbulenz      | 12 / 40           | 1.5      | 7.78      | 2.70      | 5.08     | 3.39 | UNUSABLE       |
| Schwache Thermik   | 4 / 14            | 0.7      | 2.78      | 1.26      | 1.52     | 2.17 | UNUSABLE (ok)  |

Die Schwellen (warn=1.0, danger=2.0) bleiben unveraendert — die Korrektur
verschiebt die Berechnung, nicht die Grenzwerte.

**Quellen:**
- Panofsky, H.A., et al. (1977): The characteristics of turbulent velocity
  components in the surface layer under convective conditions. *Boundary-Layer
  Meteorol.*, 11, 355–361.
- Schulz, J.P. & Heise, E. (2003): A new scheme for diagnosing near-surface
  convective gusts. COSMO Newsletter No. 3.
- `config.py`: `CONVECTIVE_GUST_BETA = 1.8`

---

## 4. Terrain-Differenzierung

Die Schwellen sind **terrain-abhaengig**, weil die Blasen-Groesse
(und damit die Widerstandsfaehigkeit gegen Scherung und Boeigkeit)
mit dem Gelaende skaliert. Vorschlag in Anlehnung an die bestehenden
5 Zonen aus `data/regionen.csv`:

| Zone       | dU/dz WARN (km/h/100m) | dU/dz DANGER | BL-Mean WARN | BL-Mean DANGER |
|------------|------------------------|--------------|--------------|----------------|
| mittelland | 1.0                    | 1.5          | 20           | 28             |
| jura       | 1.2                    | 2.0          | 22           | 30             |
| voralpen   | 1.5                    | 2.5          | 25           | 32             |
| alpen      | 1.8                    | 2.8          | 28           | 35             |
| hochalpin  | 2.0                    | 3.0          | 30           | 38             |

Begruendung: Die hochalpin-Zone hat `L_up = 750 m` (groesste
Blasen, organisierte Hangwindsysteme), Mittelland hat `L_up = 350 m`
(kleinste Blasen). Die Schwelle skaliert grob mit
`sqrt(L_up/L_up_ref)` analog zur Turbulenz-Abklinglaenge.

Die Boeigkeits-Schwellen (GF) bleiben zonen-unabhaengig, weil GF
bereits durch `w*` normiert ist — das Terrain ist damit implizit
eingerechnet (groessere Zonen haben groesseres `w*`).

---

## 5. Vorschlag Label-System (Umsetzungs-Scope)

Analog zu den bestehenden Tags in `chat_engine.py` Zeile 1105–1229
(`[GUST-WARN]`, `[GUST-DANGER]`, `[ALOFT-WARN]`, `[ALOFT-DANGER]`,
`[RAIN-WARN]`, `[CAPE-WARN]`, `[OVERCAST-DANGER]`) sollen pro Stunde
drei neue Tags berechnet werden:

| Tag                      | Bedingung                                     | Quelle          |
|--------------------------|-----------------------------------------------|-----------------|
| `[SHEAR-DEGRADED]`           | `dU/dz` ueber Zone-WARN-Schwelle              | Abschnitt 3.2   |
| `[SHEAR-UNUSABLE]`         | `dU/dz` ueber Zone-DANGER-Schwelle            | Abschnitt 3.2   |
| `[THERMAL-TORN-DEGRADED]`    | `B/S < 5` **und** `climb_rate > 0`            | Abschnitt 3.3   |
| `[THERMAL-TORN-UNUSABLE]`  | `B/S < 3` **und** `climb_rate > 0`            | Abschnitt 3.3   |
| `[THERMAL-ROUGH-DEGRADED]`   | `GF ≥ 1` **und** `climb_rate > 0`             | Abschnitt 3.4   |
| `[THERMAL-ROUGH-UNUSABLE]` | `GF ≥ 2` **und** `climb_rate > 0`             | Abschnitt 3.4   |

Die `climb_rate > 0` Vorbedingung verhindert False-Positives in
Morgenstunden ohne Thermik — Scherung ohne Thermik ist kein
Problem fuer das Thermikfliegen (sie ist dann nur eine Boeen-Sache,
die bereits durch `[GUST-WARN]` / `[ALOFT-WARN]` abgedeckt ist).

### 5.1 Integration in `hard_warnings`

Das `hard_warnings`-Set in Zeile 1249 steuert, ob eine WIND-OK-Stunde
als "clean" oder "warned" gilt. Vorschlag fuer das Downgrade:

```python
hard_warnings = {
    "[GUST-DANGER]", "[ALOFT-DANGER]", "[ALOFT-GUST-DANGER]",
    "[RAIN-WARN]", "[CAPE-WARN]", "[STRONG-WIND-WARN]",
    "[OVERCAST-DANGER]",
    # NEU:
    "[SHEAR-UNUSABLE]",
    "[THERMAL-TORN-UNUSABLE]",
    "[THERMAL-ROUGH-UNUSABLE]",
}
```

Die WARN-Varianten kommen bewusst nicht ins hard-set, weil Thermik-
Qualitaetsverlust allein noch kein Sicherheits-NoGo ist — der Pilot
soll gewarnt werden, aber die Stunde nicht automatisch aus dem
"clean"-Zaehler fallen.

### 5.2 Histogramm-Integration

Die neuen Tags werden in `major_tags_order` (Zeile 1301–1306)
aufgenommen, sodass sie im Tagesprofil als Histogramm auftauchen
und das LLM sie in die Gesamtbewertung einbeziehen kann.

### 5.3 Interpretation durch das LLM

Der bestehende System-Prompt (`prompts.py`) instruiert das LLM, die
Tags zu interpretieren. Die **Trennung zwischen Display und Chat**
ist hier zentral: das Meteogramm zeigt dem Piloten weiterhin den
rohen `climb_rate` und die rohen Windwerte (damit der erfahrene
Pilot selbst urteilen kann), aber die KI-Analyse muss die Tags in
natuerlicher Sprache uebersetzen.

#### Formulierungs-Regeln fuer das LLM

Der Prompt erhaelt folgende Interpretations-Anweisungen als neue
Regel im Analyse-Abschnitt:

> **Wind-Scherung und Thermik-Qualitaet**
>
> Wenn in einer Stunde einer der Tags `[SHEAR-DEGRADED]`, `[SHEAR-UNUSABLE]`,
> `[THERMAL-TORN-DEGRADED]`, `[THERMAL-TORN-UNUSABLE]`, `[THERMAL-ROUGH-DEGRADED]`
> oder `[THERMAL-ROUGH-UNUSABLE]` auftritt, darfst du den rohen
> `climb_rate` aus `THERMIK-PROXY` **nicht** als fliegbares Steigen
> verkaufen. Der Wert sagt nur aus, wie viel Energie die Parcel-
> Physik erlauben wuerde; er beruecksichtigt die mechanische
> Zerruettung durch den Wind nicht.
>
> Verwende stattdessen diese Formulierungen:

| Tag-Kombination                                    | Chat-Formulierung                                                                                             |
|----------------------------------------------------|---------------------------------------------------------------------------------------------------------------|
| `[SHEAR-DEGRADED]` allein                              | „Wind dreht/nimmt mit Hoehe zu, Thermik wird gekippt. Bart-Zentrierung schwieriger."                          |
| `[SHEAR-UNUSABLE]` allein                            | „Starke Windscherung zerreisst die Thermik. Steigwerte auf dem Display sind theoretisch, real nicht nutzbar." |
| `[THERMAL-TORN-DEGRADED]`                              | „Thermik durch Wind gestoert — kleine, fleckige Baerte, schwer zu zentrieren."                                |
| `[THERMAL-TORN-UNUSABLE]`                            | „Thermik zerrissen. Kein organisiertes Steigen mehr, nur noch Brocken. Fuer Thermikflug nicht zu empfehlen."  |
| `[THERMAL-ROUGH-DEGRADED]`                             | „Thermik ruppig wegen Boeigkeit. Steigen geht, aber unruhig."                                                 |
| `[THERMAL-ROUGH-UNUSABLE]`                           | „Thermik extrem ruppig, Klapper-Gefahr im Bart."                                                              |
| `[SHEAR-UNUSABLE]` + `[THERMAL-TORN-UNUSABLE]`         | „Wind zerreisst die Thermik vollstaendig. Trotz guter Parcel-Werte ist Thermikflug nicht sinnvoll; allenfalls Abgleiter im Leebereich." |
| `[GUST-WARN]` + `[THERMAL-ROUGH-DEGRADED]`             | „Boeig am Boden und in der Thermik — nur erfahrene Piloten, ruhigere Fenster abwarten."                       |

#### Beispiel-Szenarien fuer die KI-Analyse

**Szenario A** — Foehn-Lage, Alpennordseite, elev 1800 m:
```
14:00: Wind 12km/h aus 220° (Turbulenzrisiko 22km/h, Exzess +10km/h)
       [WIND-OK] [SHEAR-UNUSABLE] [THERMAL-TORN-UNUSABLE]
       THERMIK-PROXY: 2.1 m/s bis 3400m MSL (Guete: 7/10)
```
KI-Analyse soll **nicht** sagen *„2.1 m/s Thermik bis 3400 m, Guete 7/10"*,
sondern:

> „14 Uhr: Bodenwind zwar in der richtigen Richtung, aber der
> 850-hPa-Wind steigt steil auf ~45 km/h. Die Scherung zerreisst
> die Thermik. Das Parcel-Modell meldet zwar 2.1 m/s, real bleibt
> davon fuer den Piloten nichts Zentrierbares uebrig. **Nicht als
> Thermiktag zaehlen** — hoechstens Abgleiter."

**Szenario B** — Sommertag, Voralpen, elev 1500 m:
```
13:00: Wind 18km/h aus 290° (Turbulenzrisiko 28km/h, Exzess +10km/h)
       [WIND-OK] [THERMAL-ROUGH-DEGRADED]
       THERMIK-PROXY: 2.4 m/s bis 2800m MSL (Guete: 8/10)
```
KI-Analyse:

> „13 Uhr: kraeftige Thermik bis 2800 m, aber boeig. Die Baerte
> gehen gut, sind aber unruhig — erfahrene Piloten haben eine gute
> Stunde, Einsteiger sollten den ruhigeren Vormittag bevorzugen."

**Szenario C** — Schoener Fruehlingstag, alles sauber:
```
12:00: Wind 8km/h aus 180° (Turbulenzrisiko 12km/h, Exzess +4km/h)
       [WIND-OK]
       THERMIK-PROXY: 1.8 m/s bis 2400m MSL (Guete: 7/10)
```
KI-Analyse bleibt wie heute:

> „12 Uhr: saubere Thermik bis 2400 m mit 1.8 m/s. Optimale
> Bedingungen — kaum Wind, wenig Turbulenz."

#### Regel fuer die `safety_status`-Einordnung

Wenn in einer Stunde `[THERMAL-TORN-UNUSABLE]` **oder**
`[SHEAR-UNUSABLE]` **ohne** gleichzeitigen `[GUST-DANGER]` oder
`[ALOFT-DANGER]` auftritt, bleibt die Stunde theoretisch fliegbar,
aber **nicht als Thermikstunde**. Der Prompt muss das LLM anweisen,
solche Stunden in der Zusammenfassung explizit als *„nur Abgleiter,
keine Thermik"* zu klassifizieren, statt sie pauschal im
clean/warned-Zaehler einzuordnen.

---

## 6. Validierung und offene Fragen

### 6.1 Was gut abgesichert ist

- Die `2 km/h / 100 m` Scher-Schwelle stammt aus mehreren unabhaengigen
  Quellen (meteoblue, Soaring Skyways, Dr. Jack) und ist
  quantitativ konsistent.
- Die B/S-Ratio-Schwellen (5 / 10) sind durch Jack Glendenings
  langjaehrige RASP-Validierung gegen US-Segelflug-Daten abgesichert.
- Die Terrain-Skalierung folgt derselben Logik wie die bereits
  validierte `L_up`-Differenzierung im `gust_calculator.py`.

### 6.2 Was noch offen ist

- **Kalibrierung der Zonen-Schwellen** in Abschnitt 4 ist ein
  Literatur-Transfer, kein direkter Messwert. Eine Validierung gegen
  eigene winds.mobi-Daten und Flychat-Historie waere wuenschenswert.
- **Unabhaengigkeit der Tags**: Wenn `dU/dz` hoch ist, ist B/S meist
  auch klein. Die drei Tags koennten korrelieren und zu doppelter
  Bestrafung fuehren. Empfehlung: in einer ersten Iteration alle drei
  loggen, aber im Tagesprofil zusammenfassen als *„Wind zerreisst
  Thermik"* (Oberkategorie), das die drei Quellen vereinigt.
- **Richtungs-Scherung**: Nur `|dU|` wird behandelt, nicht die
  Richtungs-Aenderung. Eine starke Richtungs-Scherung (z.B. Talwind
  unten, Gradientwind oben) kippt die Blase genauso. Zweite Iteration
  koennte `|d(U_vec)/dz|` statt `|dU/dz|` nehmen.

---

## 7. Quellen

- Glendening, J. (2004+). *RASP BLIPMAP Prediction Parameters and
  Description.* [drjack.info/BLIP/INFO/parameter_details.html](http://www.drjack.info/BLIP/INFO/parameter_details.html)
  — **B/S-Ratio 5/10-Schwellen**
- Glendening, J. *RASP Parameter Info.*
  [drjack.info/rasp/info/parameters.html](http://www.drjack.info/rasp/info/parameters.html)
- meteoblue. *Thermal Forecast Help.*
  [content.meteoblue.com/en/private-customers/website-help/aviation/thermal-forecast](https://content.meteoblue.com/en/private-customers/website-help/aviation/thermal-forecast)
  — **2 km/h / 100 m Scher-Schwelle**
- DHV-Info. *Turbulenzen bei Thermik und beim Streckenfliegen.*
  [dhv.de — 17_2011_174](https://www.dhv.de/media/jahre/2024/07_wetter/Wetterwissen/DHVmagazin_Artikel/Thermik/17_2011_174_thermik_turbulenzen.pdf)
- DHV-Info. *Flachlandfliegen ist anders.*
  [dhv.de — 5_2014_185](https://www.dhv.de/media/jahre/2024/02_fliegen/Lehrmaterial/Artikel/Flugtechnik/Spezialthemen/5_2014_185_flugtechnik_flachland_teil_3.pdf)
- DHV-Info. *Thermikgradient als wichtige Wettergroesse.*
  [issuu — DHV 48885fed](https://issuu.com/dhv-info/docs/48885fed/s/11795857)
- DHV-Info. *Thermiklaunen im Flachland.*
  [dhv.de — 18_2013_180](https://www.dhv.de/media/jahre/2024/07_wetter/Wetterwissen/DHVmagazin_Artikel/Thermik/18_2013_180_flachlandthermik.pdf)
- Soaring Skyways. *The Role of Wind Direction Changes With Altitude:
  Shear and Thermal Marking.*
  [soaringskyways.com/wind-shear-and-thermals](https://soaringskyways.com/wind-shear-and-thermals/)
- Flybubble. *Catching the Drift: Thermals and Wind.*
  [flybubble.com/blog/thermal-drift](https://flybubble.com/blog/thermal-drift)
- Paragliding Lessons. *Common Wind Shear Patterns.*
  [paragliding-lessons.com/common-wind-shear-patterns2](https://www.paragliding-lessons.com/common-wind-shear-patterns2/)
- SkyNomad. *Beginners Meteorology.*
  [skynomad.com/articles/beginners_meteorology.html](https://www.skynomad.com/articles/beginners_meteorology.html)
- Deardorff, J. W. (1970). *Convective velocity and temperature scales
  for the unstable planetary boundary layer and for Rayleigh
  convection.* J. Atmos. Sci., 27, 1211–1213. — **w\* Definition**
- Stull, R. B. (1988). *An Introduction to Boundary Layer Meteorology.*
  Kluwer. Kapitel 11 (Convective Mixed Layer) und 14 (Thunderstorm
  Fundamentals, Wind Shear Section).
- Whiteman, C. D. (2000). *Mountain Meteorology: Fundamentals and
  Applications.* Oxford University Press. Kapitel 6 (Diurnal Mountain
  Winds).
- Stull, R. B. *Practical Meteorology: An Algebra-based Survey of
  Atmospheric Science.* Open-Access. Kapitel 11 (Thermal Wind) und
  14 (Wind Shear in the Environment).
  [geo.libretexts.org — Stull Practical Meteorology](https://geo.libretexts.org/Bookshelves/Meteorology_and_Climate_Science/Practical_Meteorology_(Stull)/)
- FAA. *Chapter 16 Soaring Weather.*
  [faa.gov — AC 00-6A Chap 16](https://www.faa.gov/documentLibrary/media/Advisory_Circular/AC%2000-6A%20Chap%2016-index.pdf)
- CFI Notebook. *Thermal Soaring.*
  [cfinotebook.net — thermal soaring](https://www.cfinotebook.net/notebook/aircraft-operations/gliding/thermal-soaring)
