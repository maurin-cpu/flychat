# Thermik-Modell: Wie Gleitcast die Thermik berechnet

## Was berechnen wir?

Gleitcast schätzt für jeden Flugspot stündlich drei Werte:

1. **Thermikhöhe** (m MSL) — Bis wohin reicht die nutzbare Thermik?
2. **Steigrate** (m/s) — Wie stark trägt es im Kern?
3. **Rating** (0–10) — Wie gut ist die Thermik insgesamt?

Diese Werte sind *Schätzungen* auf Basis physikalischer Modelle, keine Messungen.

### Prinzipien: Energiekette und Modelltreue

- **Eine Kette:** Kurzwellige Strahlung und (falls vorhanden) sensibler Wärmefluss aus dem
  NWP → **H** als Motor → Grenzschicht / Thermikhöhe → Steigrate (Deardorff w*).
  **Bewölkung** ist im Modell bereits in der Einstrahlung und damit in **H** enthalten —
  es gibt keine zweite, parallele „Wolken skaliert H nochmal“-Komponente für die Steigrate.
- **Keine Doppelstrafe:** Der Abend-Faktor „konvektiver Vigor“ vergleicht Tages-**H** und
  Tages-**Globalstrahlung** mit dem aktuellen Wert. Weil beides stark zusammenhängt, wird
  **ein** gemeinsamer Dämpfungsfaktor verwendet: das **Minimum** von H/Peak und SW/Peak —
  nicht das Produkt (das würde denselben Effekt zweimal zählen).
- **Regen / sehr feuchte Tage:** Niederschlag und Feuchte wirken im ICON über weniger Sonne,
  latenten Fluss und Grenzschicht. Gleitcast fügt **kein** separates „Regen-Veto“ auf H hinzu.
  Andere Dienste (z. B. XC Therm, Burnair) zeigen an solchen Tagen oft noch **sehr schwache**
  Thermikwerte — das ist mit kleinem **H** und den übrigen Modellgrenzen vereinbar.
- **Bewölkungs-Index (Sun Index):** dient der Einordnung und kann das **Rating** bei extremer
  Bewölkung deckeln — die **Steigrate** kommt weiter aus H/Deardorff und wird nicht willkürlich
  auf 0 gesetzt, wenn das Modell noch schwachen Auftrieb liefert.

---

## Datenquellen

| Quelle | Modell | Wofür |
|--------|--------|-------|
| Open-Meteo API | **ICON-D2** (DWD) | Thermik, Strahlung, Wolken, Bodenfeuchte |
| Open-Meteo API | **MeteoSwiss ICON-CH1** | Wind (lokal präziser für die Schweiz) |
| Open-Meteo API | **GFS** (NOAA) | Cross-Check: Grenzschichthöhe (BLH) als Sicherheits-Cap |

Alle Daten sind stündlich aufgelöst. Druckniveau-Daten (Temperaturprofil) kommen von
1000 bis 600 hPa in 13 Stufen.

### Zeitzone (Schweiz)

Alle Vorhersage-Zeitstempel in Gleitcast sind **Lokalzeit für die Schweiz**:

- In `config.py` ist `TIMEZONE = "Europe/Zurich"` gesetzt.
- Jeder Open-Meteo-Aufruf übergibt diese Timezone. Open-Meteo liefert die `time`-Achse dann als **Wanduhrzeit in dieser Zone** (MESZ im Sommer, MEZ im Winter), nicht als UTC.
- Die gespeicherten Keys wie `2026-04-03T16:00` bedeuten daher **16:00 Uhr Schweizer Lokalzeit**, nicht 16:00 UTC.
- Im Meteogramm werden dieselben Stunden angezeigt (JavaScript interpretiert ISO-Zeiten ohne `Z` als lokale Zeit im Browser — in der CH üblicherweise identisch zu Zürich).

**Vergleich mit anderen Tools:** Manche Karten (z. B. XC Therm) schreiben in der Kopfzeile „UTC“ für den **Modell-Lauf** (wann das Modell gerechnet wurde), zeigen die **Stunden in der Tabelle** aber oft in **Nutzer-Lokalzeit** (Schweiz). Dann entspricht „16:00“ dort ebenfalls 16:00 MESZ/MEZ — vergleichbar mit unserem `…T16:00` ohne UTC-Verschiebung.

---

## Berechnungs-Pipeline (Schritt für Schritt)

### Schritt 1: Starttemperatur bestimmen (Elevated Heat Source)

Die API liefert `temperature_2m`, aber das ist die Temperatur am Modell-Gitterpunkt —
oft im Tal. Für einen Startplatz auf 1800m nehmen wir stattdessen die **interpolierte
Temperatur auf Starthöhe** aus dem vertikalen Temperaturprofil (Druckniveau-Daten).

Stell dir vor, du liest ein Thermometer auf Starthöhe ab, nicht im Tal.

### Schritt 2: Sensiblen Wärmefluss (H) schätzen

Der **sensible Wärmefluss** H (in W/m²) ist die Energie, die der Boden an die Luft
abgibt — der "Motor" der Thermik. Mehr H = stärkere Thermik.

Berechnung (wenn H nicht direkt von der API kommt):

```
H = (Direktstrahlung × Koeffizient × Topo-Bonus + Diffusstrahlung × Koeffizient) × Vegetationsfaktor
```

- **Topo-Bonus**: Ein Südhang bekommt mehr Sonne als Flachland (bis 1.3x).
  Nur ein gedämpfter Anteil (40%) wirkt auf die Thermik, weil die Hangthermik
  schmaler und turbulenter ist als Flachland-Thermik.
- **Vegetationsfaktor**: Im Frühling (April–Mai) verdunsten Pflanzen viel Wasser.
  Diese Energie geht in Verdunstung statt Thermik → H wird um bis zu 15% reduziert.
- **H-Cap**: Maximaler H-Wert wird begrenzt (Mittelland: 250 W/m², Alpin: 310 W/m²
  im Frühling). Verhindert unphysikalische Überschätzungen.

### Schritt 3: Schnee-Dämpfung

Schneebedeckter Boden reflektiert Sonnenlicht (hohe Albedo) und verbraucht Energie
für das Schmelzen → viel weniger Thermik.

- Mittelland (flache Wiesen): 80% Reduktion
- Alpin (Fels + Schnee gemischt): 50% Reduktion

### Schritt 4: Wolkenbasis (LCL) berechnen

Das **Lifting Condensation Level** ist die Höhe, wo ein aufsteigendes Luftpaket
seinen Taupunkt erreicht und Wolken bildet. Faustregel:

```
LCL = Starthöhe + (Temperatur − Taupunkt) × 125 m
```

Über dem LCL steigt das Paket langsamer (feuchtadiabatisch statt trockenadiabatisch),
weil Kondensationswärme freigesetzt wird.

### Schritt 5: Paketaufstieg mit Entrainment

Ein "Luftpaket" (gedachte Thermikblase) steigt von der Starthöhe auf. Dabei kühlt es
sich ab:
- **Unter dem LCL**: 1°C pro 100m (trockenadiabatisch)
- **Über dem LCL**: 0.6°C pro 100m (feuchtadiabatisch)

Gleichzeitig mischt sich ständig kühlere Umgebungsluft ein (**Entrainment**). Die
Entrainment-Rate ist terrain-abhängig:
- Mittelland: μ = 0.0002 /m (mehr Einmischung, weniger organisierte Thermik)
- Alpin: μ = 0.00015 /m (weniger Einmischung, Felswände + Talwinde organisieren die Thermik)

Das Paket steigt, bis es **kälter wird als die Umgebung** (± 0.5°C Toleranz).
Diese Höhe ist die **Parcel-BLH** — die theoretische Thermik-Obergrenze.

Wenn der erste Aufstieg keine Instabilität findet (< 350m über Start), wird ein
zweiter Aufstieg mit **solar überhitzter Starttemperatur** versucht (ΔT ≈ H/100,
max 2.5°C). Dies bildet die superadiabatische Bodenschicht ab.

### Schritt 6: Encroachment-Cap (Morgen-Begrenzung)

Das **Encroachment-Modell** (Carson/Tennekes 1973) begrenzt die BLH basierend auf
der *kumulierten Tagesheizung*. Morgens ist noch wenig Energie akkumuliert → die
BLH kann nicht sofort auf 2000m springen, selbst wenn das Profil es erlauben würde.

Formel:
```
h² = h₀² + [2 × (1 + 2A) / γ_θ] × Σ(w'θ'_s × Δt)
```

- h₀ = 100m (initiale Mischungsschicht)
- A = 0.2 (Entrainment-Verhältnis)
- γ_θ = Stabilitätsgradient der freien Atmosphäre (aus Profildaten)
- Σ(w'θ'_s × Δt) = kumulierter kinematischer Wärmefluss des Tages

Die Encroachment-BLH steigt monoton (sie sinkt nie!) und liefert eine **physikalisch
glatte Glockenform** morgens. Sie wird als `min(Parcel, Encroachment)` angewendet.

### Schritt 7: Thermal Inertia (H-skalierte Glättung)

Die Grenzschicht fällt nicht sofort zusammen, wenn eine Wolke die Sonne kurz verdeckt.
Die Inertia glättet kurzfristige Einbrüche: die BLH darf nicht unter einen
Mindestwert fallen, der vom vorherigen Maximum abhängt.

**Neu: H-skalierter Verfall** (statt fixem 5%):

| Situation | Verfall pro Stunde | Warum |
|-----------|-------------------|-------|
| H am Tages-Peak | 5% | Glättung gegen Wolkenschwankungen |
| H bei 50% vom Peak | 17.5% | Nachmittags-Abschwächung |
| H bei 10% vom Peak | 27.5% | Abend-Zusammenbruch |
| H = 0 | 30% | Schneller Kollaps, aber nicht instantan |

Die Formel: `decay_rate = 0.05 + (1 − H/peak_H) × 0.25`

### Schritt 8: GFS/Modell-BLH Cap (Triple-Constraint)

Das NWP-Wettermodell (GFS) berechnet die Grenzschichthöhe intern mit dem
**Bulk-Richardson-Schema** — dieses berücksichtigt die vollständige Strahlungsbilanz
inklusive langwelliger Ausstrahlung. Sobald am Abend die Ausstrahlung die
Einstrahlung überwiegt, sinkt die Modell-BLH rapide.

Dieser Cap **überschreibt die Thermal Inertia**:

```
finale_BLH = min(eigene_BLH, GFS_BLH)
```

- **Tagsüber**: GFS-BLH ist höher als unsere Parcel-BLH → kein Effekt
- **Abends**: GFS-BLH sinkt rapide → unser Modell muss folgen

Dies ist der **Triple-Constraint**: Die finale BLH ist immer die niedrigste von:
1. Parcel-BLH (Profil-Stabilität)
2. Encroachment-BLH (kumulierte Energie)
3. GFS-Modell-BLH (Strahlungsbilanz des NWP-Modells)

XC Therm und Regtherm nutzen genau diese NWP-Modell-BLH. Wir nutzen sie als Constraint.

### Schritt 9: H-Schwellenwert (Mindest-Antrieb)

Thermik braucht nicht nur ein instabiles Profil, sondern auch genug Energie am Boden,
um Thermikblasen gegen die Bodenreibung abzulösen.

**Schwellenwert: 30 W/m²** (sensibler Wärmefluss)

Unter 30 W/m² wird die **Monin-Obukhov-Länge** so gross, dass mechanische Turbulenz
die konvektive Turbulenz dominiert — es gibt zwar noch warme Luft am Boden, aber sie
organisiert sich nicht mehr zu nutzbaren Aufwinden.

Wenn H < 30 W/m² → Steigrate wird auf 0.0 m/s gesetzt, unabhängig von der BLH.

### Schritt 9b: Konvektiver Vigor (Abend ohne ICON-BLH)

Das Thermik-Modell **ICON-D2** liefert bei Open-Meteo oft **keine** `boundary_layer_height`
(überall `null`). Der **GFS**-BLH-Cap allein kann den Abend erst spät begrenzen.

Zusätzlich wird die Steigrate mit **min(H / Tages-peak H, SW / Tages-peak SW)**
multipliziert (nicht das Produkt der beiden Quotienten — H und Globalstrahlung sind korreliert,
ein gemeinsamer Faktor genügt). Wenn der Tagesmotor gegen Abend absinkt, dämpft das die
angezeigte Thermik — näher an Tools mit feinerer Auflösung oder stärkerem Modell-BLH (z. B. XC Therm).

### Schritt 10: Steigrate berechnen (Deardorff w*)

Die thermische Aufwindgeschwindigkeit wird nach **Deardorff (1970)** berechnet:

```
w* = [(g/θ_v) × (H / (ρ × cp)) × z_i]^(1/3)
```

- g = 9.81 m/s² (Erdbeschleunigung)
- θ_v = Virtuelle potentielle Temperatur (≈ Oberflächentemp + 273.15 K)
- z_i = BLH über Grund (nach allen Caps)
- ρ = 1.1 kg/m³ (Luftdichte)
- cp = 1005 J/(kg·K) (spezifische Wärmekapazität)

Das Ergebnis wird mit einem **Climb-Factor** (0.5–0.85, jahreszeitabhängig) auf die
reale Gleitschirm-Steigrate kalibriert. Ein Gleitschirm erzielt typisch ~50–85% der
theoretischen w* wegen Eigensinken im Kreisflug und unperfekter Zentrierung.

### Schritt 11: Rating (0–10)

| Steigrate | Rating | Bedeutung |
|-----------|--------|-----------|
| 0 m/s | 0 | Keine Thermik |
| > 0 m/s | 1 | Minimal |
| ≥ 0.2 m/s | 2 | Sehr schwach |
| ≥ 0.5 m/s | 3 | Schwach |
| ≥ 0.8 m/s | 5 | Moderat |
| ≥ 1.5 m/s | 7 | Gut |
| ≥ 2.5 m/s | 9 | Sehr gut |
| ≥ 3.5 m/s | 10 | Exzellent |

Zusätzliche Rating-Korrekturen:
- Extreme Bewölkung (Sun Index < 10): max Rating 2 (Steigrate unverändert aus H/Deardorff)
- Konvektive Hemmung (CIN < −100 J/kg): Rating −2
- Thermikhöhe < 150m über Start: Rating auf max 1, climb = 0
- Bodenfeuchte-Bremse (LE > H): Rating −2

---

## Triple-Constraint: Warum Thermik abends aufhört

```
Stunde  |  H (W/m²)  |  Parcel  |  Encroachment  |  GFS-BLH  |  Finale BLH  |  Climb
--------|------------|---------|----------------|----------|-------------|-------
12:00   |    145     |  1685   |     1685       |   1795   |    1685     |  2.0
15:00   |    148     |  1549   |     2161       |   2430   |    1549     |  1.9
17:00   |     96     |  1502   |     2241       |   1995   |    1502     |  1.6
18:00   |     59     |  1504   |     2255       |   1065   | →  1065 ←  |  ~1.0
19:00   |     27     |  1041   |     2259       |    855   |   H<30→0   |  0.0
```

Der Schlüssel: Um 18:00 greift der **GFS-Cap** (1065m < 1504m). Um 19:00 greift der
**H-Schwellenwert** (27 < 30 W/m²). Die Thermik endet bei ~18:30 MESZ statt ~20:00.

---

## Vergleich mit professionellen Tools

| Tool | BLH-Quelle | Methode |
|------|-----------|---------|
| **XC Therm / Regtherm** | NWP-Modell-BLH direkt (ICON) | Modell-Output + regionale Korrekturen |
| **RASP / DrJack** | WRF-Modell intern (YSU-PBL) | Deardorff w* aus Modell-BLH |
| **AlpTherm** | Energiebudget (≈ Encroachment) | Sounding + Vorwärts-Integration |
| **Soaringmeteo** | GFS/WRF-Modell-BLH | w* aus vorgegebener BLH |
| **Gleitcast** | Hybrid: Parcel + Encroachment + GFS-Cap | Triple-Constraint + Deardorff w* |

---

## Parameter-Konfiguration

Alle kalibrierbaren Parameter befinden sich in `config.py` unter `THERMAL_PARAMS`.
Wichtige Gruppen:

- **Strahlung → H**: `direct_radiation_to_H`, `diffuse_radiation_to_H` (jahreszeitabhängig)
- **H-Cap**: `H_cap`, `alpine_H_cap` (Mittelland vs. Alpin)
- **Topografie**: `topo_bonus_max`, `topo_bonus_H_fraction`
- **Entrainment**: `alpine_MU`, `moist_entrainment_factor`
- **Climb-Factor**: `climb_factor` (jahreszeitabhängig, 0.5–0.85)
- **Terrain-Schwellen**: `terrain_elev_low` (800m), `terrain_elev_high` (1800m)

---

## Productivity-Gate (Mai 2026)

Das `productive_thermal_h`-Gate in `engine/weather_context.py` basiert seit
Mai 2026 ausschliesslich auf `climb_rate` (mit `band_usable` und kein
`*UNUSABLE*`-Tag) — **NICHT mehr auf Cloud-Cover-%**. Begründung: die
Strahlungs-Dämpfung durch Wolken ist über `direct_radiation` + `diffuse_radiation`
bereits in `climb_rate` eingerechnet. Ein zusätzliches Cloud-Gate wäre
Doppelbestrafung (siehe Kommentar im Code `thermik_calculator.py:1367-1369`).

Details: `docs/FLYABILITY_TIER_LOGIK.md`, `docs/BEWOELKUNG_LABELS.md`,
`meteo_research/cloud_cover_thermal_impact.md` Sektion 7.
