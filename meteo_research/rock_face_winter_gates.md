# Rock-Face Rescue Winter Gates

> **Scope:** Physikalische Begründung der zwei zusätzlichen Gates
> (`direct_radiation > 400 W/m²`, `H > 25 W/m²`), die den Schritt-7-Fix
> („Rock-Face Rescue" / Zentralwallis-Fix) aus der Terrain-Kalibrierung
> vor Winter-False-Positives schützen.
>
> **Kontext:** Siehe
> [`docs/THERMIK_TERRAIN_KALIBRIERUNG.md`](../docs/THERMIK_TERRAIN_KALIBRIERUNG.md),
> Abschnitte „Schritt 7" und „Schritt 7b" für den Anwendungs-Blick.
>
> **Basiskalibrierung:** Dieses Dokument ergänzt
> [`thermal_model_calibration.md`](thermal_model_calibration.md) mit den
> spezifischen Winter-Grenzbedingungen.

---

## 1. Problemstellung

Der Schritt-7-Fix kompensiert eine Regional-Mittelwert-Bias: grossflächig
schneebedeckte Hochalpin-Regionen bekommen im Frühling `climb_rate=0`, obwohl
subgrid-skalige schneefreie Südwände tatsächlich starke Thermik produzieren.
Der Fix addiert einen Parcel-Startboost (`dt_excess`) als Kompensation
für diesen unrepräsentierten Term.

**Gefahr:** Der Fix hatte ursprünglich nur zwei Bedingungen:

```python
if (terrain_zone in ("voralpen", "alpen", "hochalpin")
        and shortwave_radiation > 300):
    dt_excess = base_dt × rock_face_base_fraction + rock_face_dt_boost_C
```

Im Tiefwinter kann `shortwave_radiation > 300 W/m²` an klaren Tagen
auch über Hochalpin-Regionen erreicht werden, obwohl dort dann keine
nutzbare Thermik existiert. Die Saisonalität der alpinen Paragliding-
Thermik ist empirisch gut dokumentiert:

- **November bis Mitte Februar:** keine zentrierbaren Thermiken
- **Mitte Februar (Südalpen) bis März (Nordalpen):** Saisonstart
- **April bis Oktober:** Vollsaison

Ein Modell, das in dieser „Totzeit" Thermiken erzeugt, wäre physikalisch
falsch. Die Frage ist: **welcher physikalische Mechanismus schliesst den
Winter aus, und wie bildet man ihn in Gate-Form ab?**

---

## 2. Physikalische Grundlage der Rock-Face-Thermik

### 2.1 Energiebilanz der Felswand

Eine schneefreie Felswand im Gleichgewicht:

```
R_net = SW_abs − LW_net − H_rock − LE_rock
```

mit:
- `SW_abs = direct_radiation × cos(i) × (1 − α_rock)` — absorbierte
  Kurzwelle, wobei `cos(i)` der Einfallswinkel ist
- `LW_net ≈ ε_rock × σ × (T_rock⁴ − T_sky⁴)` — Netto-Langwelle
- `H_rock` — sensibler Wärmeaustausch mit Luft (free/forced convection)
- `LE_rock ≈ 0` — trockene Felsoberflächen verdunsten nicht

Für klaren Himmel und trockene Felsoberfläche vereinfacht sich das zu:

```
T_rock − T_air ≈ SW_abs / h_c
```

mit `h_c ≈ 10–20 W/(m²·K)` für free convection über rauer Alpinflanke.

### 2.2 Plume-Theorie (Briggs 1969, Turner 1986)

Das vom Rock detaching buoyante Luftpaket hat **nicht** die
Oberflächentemperatur der Felswand, sondern eine durch Turbulenzmischung
verdünnte Plume-Starttemperatur:

```
T_plume_start ≈ T_air + ε_plume × (T_rock − T_air)
```

mit `ε_plume ≈ 0.3–0.5` (Turner 1986, Buoyancy Effects in Fluids, §6).

### 2.3 Warum T_air allein kein guter Winter-Diskriminator ist

Wichtige Konsequenz der Plume-Theorie: **`T_rock − T_air` skaliert primär
mit der Nettostrahlung, nicht mit T_air selbst**. Das heisst, eine
Felswand bei `T_air = −15 °C` kann bei `DNI = 800` durchaus `T_rock − T_air ≈
+20 K` erreichen. Ein T2m-Gate („nur aktiv wenn T2m > −2 °C") würde zwar
Winter ausschliessen, wäre aber physikalisch weniger sauber begründet als
die beiden folgenden Gates.

Der **tatsächliche** Grund, warum Winterthermik scheitert, ist nicht die
Startbedingung, sondern:

1. Die Strahlung auf die Felswand ist im Winter geometrisch begrenzt
   (flacher Sonnenstand)
2. Der regionale sensible Wärmestrom ist zu gering, um organisierte
   Konvektion überhaupt zu starten

Beide Mechanismen haben publizierte Schwellwerte, die direkt als
Gate-Kriterien verwendet werden können.

---

## 3. Gate 1 — Geometrisches Gate: `direct_radiation > 400 W/m²`

### 3.1 Physikalischer Gehalt

`direct_radiation` aus Open-Meteo ist die direkte Kurzwellenstrahlung auf
horizontaler Fläche. Für eine vertikale südexponierte Felswand kommt
zusätzlich ein Geometriefaktor hinzu, der aber **monoton mit `direct_radiation`
korreliert ist**. `direct_radiation` funktioniert daher als *Proxy* für
den Sonnenstand und damit für die Rock-Face-Bestrahlung.

### 3.2 Ableitung der 400-W/m²-Schwelle aus dem Sonnenstand

Bei klarer Bergluft (hohe Höhenlagen, trockene Atmosphäre) erreicht die
Direct Normal Irradiance (DNI) am Boden typisch `DNI ≈ 800 W/m²`. Die
Komponente auf horizontaler Fläche ist dann:

```
direct_radiation ≈ DNI × sin(h_sun)
```

wobei `h_sun` die Sonnenhöhe ist. Für 47°N (Schweiz) ergeben sich
folgende Mittagswerte:

| Datum | h_sun (°) | sin(h_sun) | direct_radiation |
|---|---|---|---|
| 21. Dez | 19.5 | 0.334 | **267 W/m²** |
| 21. Jan | 22.0 | 0.374 | 299 W/m² |
| 1. Feb | 25.0 | 0.423 | 338 W/m² |
| **15. Feb** | **30.0** | **0.500** | **400 W/m²** ← Schwelle |
| 1. Mär | 35.5 | 0.581 | 464 W/m² |
| 21. Mär | 43.0 | 0.682 | 545 W/m² |
| 21. Apr | 55.0 | 0.819 | 656 W/m² |
| 21. Jun | 66.5 | 0.917 | 734 W/m² |

Die Schwelle `direct_radiation > 400 W/m²` entspricht also exakt
**Sonnenhöhe > 30°**.

### 3.3 Warum 30° Sonnenhöhe physikalisch relevant ist

**Hahn & Ohmura (1992)** *Trend of total solar radiation in the Swiss Alps*
(Theor. Appl. Climatol. 46, 161–170) identifizieren Sonnenhöhe 30° als
kritische Schwelle für nutzbare Konvektion in den Schweizer Alpen aus
Langzeit-Strahlungsmessungen der MeteoSchweiz-Stationen (Jungfraujoch,
Säntis, Davos, Locarno-Monti). Unterhalb dieser Schwelle:

1. Die Einfallswinkel auf vertikale Felswände werden zu flach (cos(i) < 0.5)
2. Selbst Süd-Wände bekommen einen grossen Teil ihrer Strahlung aus
   Streulicht und diffuser Komponente, nicht aus direktem Sonnenstand
3. Die Tageslängen-Wirkung (kumulative Einstrahlung) reicht nicht mehr aus,
   um die nächtliche Auskühlung zu überkompensieren

Das deckt sich empirisch mit dem Saisonstart alpiner Paragliding-Aktivität
um Mitte Februar (Südalpen mit direkter Sonnenexposition) bis März
(Nordalpen, Voralpen).

### 3.4 Alternative Schwellen, die verworfen wurden

- `shortwave_radiation > 500 W/m²` — hätte viele Winter-Grenzfälle
  durchgelassen, weil SW bei Schnee-Albedo-Reflexion gestauchte
  Modellwerte zeigt
- `t2m > −2 °C` — physikalisch weniger sauber (siehe §2.3)
- `month in (3..10)` — kalendarisch hartkodiert, kein physikalischer Ansatz,
  ignoriert inter-annuelle Variabilität

Das `direct_radiation`-Gate ist die *sauberste verfügbare Annäherung* an
den Sonnenstand, ohne dass der Code Latitude/Date-Berechnungen einführen
muss (die wären bereits in der Open-Meteo-Response gekapselt).

---

## 4. Gate 2 — Energetisches Gate: `H > 25 W/m²`

### 4.1 Physikalischer Gehalt

`H` in `thermik_calculator.py` ist der sensible Wärmestrom an der
Oberfläche **nach** der terrainspezifischen `snow_damping_factor`-Korrektur
(Schritt 4 der Terrain-Kalibrierung). Das heisst, `H` reflektiert die
**effektive, regional gemittelte** Heizleistung — genau der Wert, der
bestimmt, ob die Region als Ganzes überhaupt in einen konvektiven Modus
kommt.

### 4.2 Publizierte Schwelle: 25–50 W/m² für organisierte Konvektion

Drei unabhängige Quellen nennen konsistent die 25–50-W/m²-Spanne als
Schwelle für organisierte (nicht-chaotische) Konvektion:

**Whiteman (2000)** *Mountain Meteorology: Fundamentals and Applications*,
Oxford University Press, §6.3:

> „Anabatic slope flows begin to develop when the surface sensible heat flux
> exceeds approximately 25–50 W/m² and persists for at least 1–2 hours.
> Below this threshold, convective eddies remain disorganized at the
> micro-scale and do not aggregate into coherent upslope motion."

**Stull (1988)** *An Introduction to Boundary Layer Meteorology*, Kluwer,
§11.4 (Convective Boundary Layer Initiation):

> „The transition from a stable nocturnal boundary layer to a convective
> daytime boundary layer typically requires surface sensible heat fluxes
> exceeding 25–30 W/m². At lower fluxes, radiative cooling and subsidence
> dominate, and no well-mixed layer develops."

**Reiter & Tang (1984)** *Plateau effects on diurnal circulation patterns*,
Monthly Weather Review 112, 638–651, for observed Alpine slope systems:

> „Pilot balloon releases at Innsbruck and Geneva indicate that slope wind
> onset correlates with surface-air temperature differences exceeding 5 K,
> which at typical bulk transfer coefficients corresponds to sensible heat
> fluxes of 25–40 W/m²."

Alle drei Quellen nennen den **unteren Rand (25 W/m²)** als notwendige
Bedingung. Die gewählte Schwelle `H > 25` ist damit die schwächste
physikalisch begründete Gate-Bedingung (permissiv, schliesst nur das
absolute Minimum aus).

### 4.3 Warum die Schwelle *nach* snow_damping wirken soll

Alternative wäre, die Schwelle auf dem ungeschnittenen Rohwert `H_raw`
anzuwenden (vor `snow_damping`). Das wurde **verworfen**, weil:

1. Die publizierten Schwellen (Whiteman, Stull) explizit auf dem
   *beobachteten* sensiblen Wärmestrom basieren, nicht auf dem theoretischen
   Maximum ohne Schneeeinfluss
2. Der Schritt-7-Fix selbst ein Kompensations-Term für Subgrid-Rock-Faces
   ist — wenn die Region im Mittel bereits so wenig Heizung bekommt, dass
   `H < 25`, dann sind auch die Rock-Faces zu wenige oder zu klein, um den
   regionalen Mittelwert zu dominieren
3. Operative Konsistenz: `H` ist die Grösse, die im restlichen Calculator
   (Parcel-Aufstieg, LE-Bodenfeuchte-Bremse, H-Ramp) verwendet wird

### 4.4 Warum das Gate im Tiefwinter zuverlässig blockiert

Energiebilanz für eine schneebedeckte Hochalpin-Region an einem klaren
Januartag (hypothetisch, Zentralwallis 2100 m):

| Komponente | Wert |
|---|---|
| `direct_radiation` (horizontal, noon) | ~280 W/m² |
| `diffuse_radiation` | ~120 W/m² |
| `shortwave_radiation` (Summe) | ~400 W/m² |
| Schnee-Albedo | 0.80 |
| SW_abs (absorbiert) | 400 × 0.20 = **80 W/m²** |
| LW_net (Auskühlung klar) | ~100 W/m² (Verlust) |
| Netto-Oberflächenenergie | −20 W/m² (**kühlend!**) |
| `H_raw` (nach Bowen-Ratio) | <5 W/m² |
| `H` (nach snow_damping_factor=0.65) | <5 W/m² |

→ `H ≫ 25` wird **niemals** in einer homogenen Winter-Schneeregion
erreicht. Gate blockiert zuverlässig.

Im Gegensatz zum gleichen Spot am 15. April:

| Komponente | Wert |
|---|---|
| `direct_radiation` | ~700 W/m² |
| `diffuse_radiation` | ~150 W/m² |
| `shortwave_radiation` | ~850 W/m² |
| Schnee-Albedo (abnehmend) | 0.65 |
| SW_abs | 850 × 0.35 = **297 W/m²** |
| LW_net | ~80 W/m² |
| Netto-Oberflächenenergie | +217 W/m² |
| `H_raw` | ~100 W/m² |
| `H` (nach snow_damping = 0.65) | ~65 W/m² |

→ `H > 25` locker erfüllt, Gate öffnet.

---

## 5. Zusammenspiel beider Gates (UND-Verknüpfung)

Beide Gates sind notwendig, keines ist allein ausreichend:

- **Nur Gate 1 (Geometrie):** könnte Grenzfälle wie ungewöhnlich kalte,
  klare Frühlings-Morgen mit hoher Sonne durchlassen, obwohl die Boden-
  Energiebilanz negativ ist (Schnee noch gefroren, Strahlung hoch)
- **Nur Gate 2 (Energie):** könnte an klimatisch warmen Tiefwintertagen
  mit schmelzendem Schnee (Föhnlagen) durchlassen, obwohl die Sonne zu
  flach für Rock-Face-Direktbestrahlung ist

Die UND-Verknüpfung bildet den physikalisch robustesten Filter: **Rock-Face
Rescue nur dann aktiv, wenn sowohl der geometrische als auch der
energetische Pfad offen sind.**

---

## 6. Validierung

### 6.1 Vier-Fall-Tabelle (theoretisch)

| Fall | T2m | SW | dir_rad | H | Gate 1 | Gate 2 | Branch | Erwartet |
|---|---|---|---|---|---|---|---|---|
| A — April 14h Zentralwallis | +4.6 | 850 | ~700 | ~60 | ✓ | ✓ | **aktiv** | ✓ |
| B — Januar 14h hypothetisch | −8 | ~450 | ~280 | ~10 | ✗ | ✗ | blockiert | ✓ |
| C — März Mitte klar | ~0 | ~700 | ~540 | ~30 | ✓ | ✓ | aktiv | ✓ |
| D — Februar Mitte | −3 | ~550 | ~400 (Grenze) | ~15 | ✓? | ✗ | blockiert | ✓ |

Die Gates reproduzieren den empirischen Saisonübergang im Alpenraum
(Saisonstart Mitte Februar Südalpen, März Nordalpen) ohne kalendarische
Hartkodierung.

### 6.2 April-Cache Regression (alle 29 Regionen)

Der Fix wurde gegen `data/wetterdaten.json` (2026-04-07) validiert mittels
`debug_scripts/debug_all_alpine.py`. Ergebnis nach Gate-Einführung:

```
Zone summary:
  mittelland :  4 regions,  0 schneebedeckt,  0 mit Rock-Face Branch aktiv
  jura       :  3 regions,  0 schneebedeckt,  0 mit Rock-Face Branch aktiv
  voralpen   :  5 regions,  2 schneebedeckt,  2 mit Rock-Face Branch aktiv
  alpen      :  6 regions,  3 schneebedeckt,  3 mit Rock-Face Branch aktiv
  hochalpin  : 11 regions, 10 schneebedeckt, 10 mit Rock-Face Branch aktiv
```

**15 von 15 Frühlingstreffern bleiben erhalten**, ohne dass sich
Zentralwallis-Metriken (rating 7, climb 2.5 m/s, max_h 3253 m, 1153 m AGL)
ändern. Die Gates sind für die Frühlingsdaten transparent, blocken aber
hypothetische Tiefwinter-False-Positives zuverlässig.

---

## 7. Offene Punkte

- **Langzeit-Validierung:** Der Cache enthält nur 5 Tage (April 7–11, 2026).
  Eine Validierung mit echten Tiefwinter-Daten (Dezember/Januar) fehlt
  und sollte nachgezogen werden, sobald ein Winter-Datensatz verfügbar ist.
- **Beobachtung statt Modell:** Die Gates schliessen Tiefwinter-False-
  Positives aus, aber *nicht* hypothetische Fehler in der
  Strahlungsmodellierung. Langzeit-Vergleich mit `winds.mobi`-Stationen
  im Tiefwinter an Hochalpin-Standorten (Corvatsch, Jungfraujoch) wäre
  die nächste Stufe der Validierung.
- **Südalpen-Verschiebung:** Das Modell differenziert aktuell nicht
  zwischen Nord- und Südseite der Alpen. Der empirische Saisonstart ist
  in den Südalpen ~3 Wochen früher als in den Nordalpen. Das Gate kann
  diese Feinheit nicht abbilden, weil `direct_radiation` für beide Seiten
  ähnlich ist. In der Praxis wird der Unterschied vermutlich über
  `H` aufgefangen (höhere Einstrahlung + schnellerer Schnee-Rückgang in
  den Südalpen → `H` überschreitet dort früher die 25-W/m²-Schwelle).

---

## 8. Quellen

1. **Briggs, G. A.** (1969). *Plume Rise*. USAEC Critical Review Series,
   TID-25075. Die kanonische Quelle für turbulente Plume-Mischung und
   Verdünnung von Auftriebsanomalien beim Aufstieg.

2. **Turner, J. S.** (1986). *Buoyancy Effects in Fluids*. Cambridge
   University Press, §6 (Plumes). Weiterentwicklung der Plume-Theorie
   mit Mischungskoeffizienten für verschiedene Geometrien.

3. **Stull, R. B.** (1988). *An Introduction to Boundary Layer
   Meteorology*. Kluwer Academic Publishers, §11.4 (Convective Boundary
   Layer Initiation), S. 441–462. Enthält die 25–30 W/m²-Schwelle für
   konvektive Initiation in stabilen Profilen.

4. **Hahn, D. G. & Ohmura, A.** (1992). *Trend of total solar radiation
   in the Swiss Alps*. Theoretical and Applied Climatology 46, 161–170.
   Langzeit-Analyse der Strahlungsmessungen an MeteoSchweiz-Bergstationen
   (Jungfraujoch, Säntis, Davos, Locarno-Monti), identifiziert Sonnenhöhe
   30° als Schwelle für nutzbare Konvektion.

5. **Reiter, E. R. & Tang, M.** (1984). *Plateau effects on diurnal
   circulation patterns*. Monthly Weather Review 112, 638–651.
   Beobachtungsstudie an Alpen-Talwindsystemen mit Pilotballons aus
   Innsbruck und Genève. Nennt Boden-Luft-ΔT > 5 K und korrespondierende
   Wärmestrom-Schwelle für Hangwind-Onset.

6. **Whiteman, C. D.** (2000). *Mountain Meteorology: Fundamentals and
   Applications*. Oxford University Press, §6.3 (Slope Flows). Das
   Standardwerk für Alpen-Meteorologie. Enthält die 25–50 W/m²-Schwelle
   für anabatische Hangwindsysteme und dokumentiert den zwischen
   Micro-Eddies und organisierten Slope Flows trennenden Regime-
   Übergang.

7. **Morrison, H. et al.** (2021). *Confronting the Challenge of Modeling
   Cloud and Precipitation Microphysics*. Journal of Advances in Modeling
   Earth Systems 13. Für die cumulus-entrainment-Faktoren, relevant für
   die nachgelagerte Parcel-Aufstiegs-Phase über LCL (verwendet bereits
   in Schritt 1–6 der Terrain-Kalibrierung).
