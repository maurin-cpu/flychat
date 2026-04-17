# Grenzschichthoehe (BLH): Modellierung und Tagesverlauf

## Das Problem: Springende BLH im Parcel-Verfahren

Unser Thermik-Modell berechnet die Thermik-Obergrenze (BLH) jede Stunde unabhaengig
via Parcel-Methode: ein Luftpaket steigt trockenadiabatisch auf, bis es kuehler wird
als die Umgebung. Kleine Aenderungen im Temperaturprofil (z.B. Inversion wird 0.3°C
schwaecher) koennen bewirken, dass das Paket durchbricht oder nicht → grosse BLH-Spruenge.

XC-Therm, Burnair und RASP zeigen dagegen eine glatte Glockenform. Ursache: sie nutzen
entweder NWP-Modell-BLH (intern geglaettet) oder ein Encroachment-Modell (physikalisch glatt).

## Tagesverlauf der konvektiven Grenzschicht (CBL)

Der typische Tagesverlauf folgt der kumulierten Bodenheizung:

1. **Morgen (Sonnenaufgang bis ~10:00)**: Sonnenstrahlung heizt den Boden. Kleine
   Konvektionszellen beginnen, die naechtliche Inversionsschicht (Residual Layer)
   aufzuloesen. CBL waechst von 50-200m auf einige Hundert Meter.

2. **Vormittag (10:00-13:00)**: Schnellstes Wachstum. Die CBL frisst sich durch die
   Residual Layer in die freie Atmosphaere. Wachstumsrate ~200-400m/h.

3. **Nachmittag (13:00-16:00)**: BLH erreicht Maximum (1-3km in Mitteleuropa).
   Wachstum verlangsamt sich weil: (a) das Integral nur langsam waechst, und
   (b) die capping-Inversion staerker wird je tiefer man in die stabile Schicht vordringt.

4. **Spaetnachmittag/Abend (16:00-Sonnenuntergang)**: Heizung sinkt, BLH waechst kaum
   noch oder gar nicht. Die letzten Thermiken werden schwaecher. Eine stabile naechtliche
   Grenzschicht bildet sich am Boden, waehrend die gemischte Luft darueber als
   Residual Layer bestehen bleibt.

**Schluessel-Einsicht**: Die BLH-Kurve ist glatt und glockenfoermig weil sie das
INTEGRAL des Waermeflusses abbildet, nicht den momentanen Wert.

## Das Encroachment-Modell (Carson 1973 / Tennekes 1973)

### Grundannahmen (Zero-Order Jump Slab Model)

- Die CBL ist **durchmischt**: potentielle Temperatur θ_m ist homoegen mit der Hoehe
- Am CBL-Top gibt es einen **Temperatursprung** Δθ (Inversion)
- Die **freie Atmosphaere** ueber der CBL hat einen konstanten Gradienten γ_θ
- **Entrainment**: Am CBL-Top wird waermere Luft von oben eingemischt

### Die drei gekoppelten Gleichungen

**1. Temperaturbudget der Mischungsschicht:**
```
d(θ_m)/dt = [w'θ'_s - w'θ'_h] / h
```

**2. Inversion-Staerke:**
```
d(Δθ)/dt = γ_θ · dh/dt - d(θ_m)/dt
```

**3. Entrainment-Closure:**
```
w'θ'_h = -A · w'θ'_s     (A = 0.2, Entrainment-Verhaeltnis)
```

### Die analytische Loesung

Aus den drei Gleichungen folgt die **Encroachment-Formel** (Tennekes 1973):

```
h(t)² = h₀² + [2·(1+2A) / γ_θ] × ∫₀ᵗ w'θ'_s(t') dt'
```

Wobei:
- h₀ = initiale BLH (~100m bei Tagesbeginn)
- A = 0.2 (Entrainment-Ratio, Stull 1988, Driedonks 1982)
- (1+2A) = 1.4 → CBL waechst 40% schneller als reine Encroachment
- γ_θ = potentieller Temperatur-Gradient der freien Atmosphaere (K/m)
- w'θ'_s = H / (ρ·cp) = kinematischer sensibler Waermefluss (K·m/s)

### Umrechnung: H → kinematischer Flux

```
w'θ'_s = H / (ρ · cp)
```
Beispiel: H = 200 W/m² → w'θ'_s = 200 / (1.1 × 1005) = 0.181 K·m/s

### γ_θ: Potentieller Temperatur-Gradient

γ_θ misst die Stabilitaet der freien Atmosphaere ueber der BLH:
```
γ_θ = dT/dz + DALR    (DALR = 0.0098 K/m)
```

| Bedingung | dT/dz (K/km) | γ_θ (K/km) | Bedeutung |
|-----------|--------------|------------|-----------|
| Standardatmosphaere | -6.5 | 3.3 | Normal |
| Typisch Fruehling CH | -5 bis -7 | 2.8 - 4.8 | Leicht stabil |
| Guter Sommertag | -7 bis -8 | 1.8 - 2.8 | Wenig stabil → gute Thermik |
| Subsidenz-Inversion | +5 bis +15 | 15 - 25 | Sehr stabil → Deckel! |

**Groesseres γ_θ = stabilere Atmosphaere = langsameres BLH-Wachstum.**

### Beispielrechnung

Fruehlings-Tag, γ_θ = 0.005 K/m, Elevation 850m MSL:

| Stunde | H (W/m²) | w'θ' (K·m/s) | cum (K·m) | h_enc AGL (m) | h_enc MSL (m) |
|--------|----------|---------------|-----------|----------------|----------------|
| 09:00  | 50       | 0.045         | 163       | 302            | 1152           |
| 10:00  | 120      | 0.109         | 554       | 557            | 1407           |
| 11:00  | 200      | 0.181         | 1206      | 822            | 1672           |
| 12:00  | 250      | 0.226         | 2021      | 1065           | 1915           |
| 13:00  | 240      | 0.217         | 2804      | 1254           | 2104           |
| 14:00  | 200      | 0.181         | 3456      | 1393           | 2243           |
| 15:00  | 130      | 0.118         | 3880      | 1476           | 2326           |
| 16:00  | 60       | 0.054         | 4076      | 1513           | 2363           |
| 17:00  | 15       | 0.014         | 4125      | 1522           | 2372           |
| 18:00  | 0        | 0             | 4125      | 1522           | 2372           |

→ Glatte Kurve: schnelles Wachstum morgens, Verlangsamung nachmittags, Plateau abends.

### Umgang mit Inversionen

Starke Inversionen ergeben ein grosses γ_θ lokal. Im Slab-Modell:
- `dh/dt = A · w'θ'_s / Δθ` → bei grossem Δθ waechst h kaum
- Die BLH "steckt" unter der Inversion bis genug Waerme akkumuliert ist

### Abendlicher Verfall

Das Encroachment-Modell beschreibt NUR das Wachstum. BLH sinkt nie (h ~ sqrt(cum)).
Der Abfall kommt von aussen:
- Die Mischungsschicht wird zur **Residual Layer** (bleibt in der Hoehe)
- Am Boden bildet sich eine **stabile naechtliche Grenzschicht**
- Die **nutzbare Thermikhoehe** sinkt weil die letzten Thermiken zu schwach werden
- → Im Modell: Parcel-Methode gibt niedrigere Werte, Thermal Inertia glaettet

## Wie professionelle Tools BLH berechnen

### RASP / DrJack
Nutzt WRF-Modell mit YSU-PBL-Schema. Die BLH wird intern im Modell berechnet
(Bulk-Richardson-Zahl). RASP extrahiert nur W* via Deardorff:
```
W* = [(g/θ_v) · w'θ'_v_s · h]^(1/3)
```
Die Glaette kommt vom WRF-Modell (6-Sekunden-Zeitschritte, intern geglaettet).

### XC-Therm / Regtherm
Nutzt ICON-EU/ICON-D2 Modelloutput. Die BLH kommt direkt aus dem NWP-Modell.
Regtherm ergaenzt mit regionaler Segmentierung, Bewolkungseffekten, Talwind-Korrekturen.

### AlpTherm (Liechti & Neininger 1994)
Speziell fuer die Alpen entwickelt. Nutzt ein **Energiebudget-Modell** (= Encroachment):
Mitternachts-Sounding als Anfangsbedingung, dann vorwaerts-Integration der akkumulierten
Heizung. Beruecksichtigt den "Volumeneffekt" alpiner Taeler (kleineres Luftvolumen
erwaermt sich schneller).

### Soaringmeteo
Nutzt GFS/WRF Modell-BLH direkt. Berechnet nur W* aus der vorgegebenen BLH.

### Unser Ansatz: Hybrid Parcel + Encroachment

**Strategie**: `final_BLH = min(parcel_BLH, encroachment_BLH)`

- **Parcel-Methode**: Detektiert lokale Inversionen und Profilaenderungen
- **Encroachment-Modell**: Liefert eine physikalisch glatte Obergrenze
- **min()**: Nimmt das konservativere Ergebnis

Tagesverlauf:
- Morgens: Encroachment limitiert (noch zu wenig kumulierte Waerme)
- Mittags: Beide stimmen ungefaehr ueberein
- Nachmittags: Encroachment plateautiert, Parcel sinkt → Parcel gewinnt
- Abends: Parcel + Thermal Inertia bestimmen den Verfall

## Quellen

- Tennekes, H. (1973): "A Model for the Dynamics of the Inversion Above a Convective
  Boundary Layer." J. Atmos. Sci., 30(4), 558-567.
- Carson, D.J. (1973): "The Development of a Dry Inversion-Capped Convectively Unstable
  Boundary Layer." Quart. J. Roy. Meteor. Soc., 99, 450-467.
- Stull, R.B. (1988): "An Introduction to Boundary Layer Meteorology." Kluwer, 666pp.
- Driedonks, A.G.M. (1982): "Sensitivity Analysis of the Equations for a Convective
  Mixed Layer." Boundary-Layer Meteorol., 22, 475-480.
- Batchvarova, E. & Gryning, S.E. (1991): "Applied Model for the Growth of the Daytime
  Mixed Layer." Boundary-Layer Meteorol., 56, 261-274.
- Liechti, O. & Neininger, B. (1994): "AlpTherm: A PC-Based Model for Atmospheric
  Convection over Complex Topography." Technical Soaring, 18(3), 73-78.
- DrJack RASP Parameters: http://www.drjack.info/rasp/info/parameters.html
- CBL Lecture Notes (Ghent): https://boundary-layer-meteo.github.io/lectures/11_cbl.html
- MXL Python Model: https://github.com/LukeEcomod/MXL
- CLASS Model: https://github.com/classmodel/modelpy
- Soaringmeteo: https://github.com/soaringmeteo/soaringmeteo
