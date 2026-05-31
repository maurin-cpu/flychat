# Thermik-Terrain-Kalibrierung: 5-Zonen-System

> **Zweck:** Entwickler-Leitfaden zur **terrain-differenzierten Parametrisierung**
> des `thermik_calculator.py` nach den 5 Klassen aus `data/regionen.csv`.
>
> **Wissenschaftlicher Hintergrund:** Siehe das tiefe Recherchedokument
> [`meteo_research/thermal_model_calibration.md`](../meteo_research/thermal_model_calibration.md).
>
> **Status:** ✅ **Umgesetzt (Stand Mai 2026).** Alle Schritte 1–8 sind in
> `thermik_calculator.py` und `config.py` produktiv aktiv — die 5-Zonen-Parameter
> liegen in `config.py` (`min_thermal_depth_agl`, `gfs_pbl_cap_mode`,
> `snow_damping_factor`, `h_ramp_*`, `entrainment_mu`, `climb_factor_terrain`,
> `rock_face_*`), die Zonen-Lookups in `thermik_calculator.py`
> (`get_terrain_zone()`, `_get_terrain_param()`). Dieses Dokument ist damit
> beschreibende Doku, kein offener Plan mehr.

---

## Warum 5 Zonen statt 2?

Der heutige `thermik_calculator.py` interpoliert nur zwischen **mittelland**
(<800 m) und **alpin** (>1800 m) — zwei Stützstellen, lineare Mischung. Das
führt zu drei Problemen:

1. **Voralpen werden wie halbes Mittelland behandelt** — obwohl sie thermisch
   schon stark organisierte Hangthermik produzieren.
2. **Hochalpine Regionen (Wallis, Engadin, Tessin) bekommen keine eigenen
   Parameter** — sie erben den „alpin"-Zustand bei 1800 m, obwohl sich
   Strahlungs-, Schnee- und Talwind-Verhalten oberhalb 2000 m fundamental
   verändern.
3. **Jura und Mittelland teilen denselben Parametersatz** — obwohl Jura mit
   ~1200 m bereits orographische Kanalisierung und stärkere Sonneneinstrahlung
   pro m² hat.

Das **5-Zonen-System gibt es bereits** in `data/regionen.csv` (Spalte
`terrain_type`) und wird vom `gust_calculator.py` schon verwendet. Diese
Kalibrierung bringt den Thermik-Calculator auf den gleichen Standard.

---

## Die 5 Terrain-Zonen

| Zone | Höhenbereich | Beispielregionen | Charakteristik |
|---|---|---|---|
| **mittelland** | 600–800 m | Seeland, Mittelland West, Mittelland Ost, Genfersee | Flach, hohe Bodenfeuchte, Mischwald, viel mittelhoher Bewuchs, dominiert von synoptischen Winden |
| **jura** | 900–1280 m | Jura Ost, Jura West, Jura Zentral | Mittelgebirgs-Faltenketten, Kalk, oft karge Höhen, gute Hangthermik |
| **voralpen** | 1300–1500 m | Mittelland Zentral (Napf), Glarnerland, Schwarzsee/Gantrisch | Voralpine Ketten, organisierte Hangthermik, beginnende Tal-Berg-Wind-Systeme |
| **alpen** | 1500–1860 m | Berner Oberland, Alpstein, Tessin Zentral, Chur, Zentralschweizer Voralpen | Alpenhauptkamm-nahe, ausgeprägte Talwindsysteme, gemischte Schnee/Fels-Oberflächen |
| **hochalpin** | 1950–2450 m | Berner Voralpen (Niederhorn), Mattertal, Tessin Nord, Zentralwallis, Engadin, Surselva, Goms | Trockene Luft, hohe direkte Strahlung, Felswand-Heizung, teilweise Gletscher-Einfluss |

`elevation_ref` aus `regionen.csv` ist die typische Flughöhen-Referenz, nicht
der höchste Gipfel der Region.

---

## Was sich pro Zone unterscheiden muss

Sechs Parameter-Familien müssen terrain-differenziert werden. Die Werte sind
wissenschaftlich begründet (siehe Recherche-Dokument für Quellen pro Zelle).

### 1. Mindest-Thermikhöhe AGL (`min_thermal_depth_agl`)

Ersetzt den Hardcode `elevation_m + 150` aus `thermik_calculator.py:972-975`.
Dieser Wert sagt: „Eine Thermik gilt erst dann als nutzbar, wenn die
konvektive Schicht mindestens X m über Grund reicht."

| Zone | Schwelle (m AGL) | Begründung |
|---|---|---|
| mittelland | 400 | Tiefere Inversionen, höhere Mindesthöhe für stabile Ablösung |
| jura | 350 | Mittelgebirge, gute Auslöser, etwas geringer |
| voralpen | 300 | Steile Hänge, früh organisierte Thermik |
| alpen | 200 | Sehr starke Hangwärme, Thermik löst flach aus |
| hochalpin | 150 | Extrem starke direkte Strahlung, dünne Luft, flache Auslösung |

**Effekt:** Tessin Nord und Zentralwallis werden nicht mehr durch das
Hardcode-150-m-Killswitch unterdrückt, wenn die berechnete Thermikhöhe nur
knapp über der Referenzhöhe liegt.

### 2. Schnee-Dämpfung (`snow_damping_factor`, `snow_h_max_w_per_m2`, `snow_dt_excess_max`)

Heutiger Code (`thermik_calculator.py:650-656`) macht bei `snow_depth > 5 cm`
das `dt_excess = 0` für den 2. Aufstieg. Das tötet im April im Tessin und
Wallis sämtliche Thermik, obwohl die **Felswände schneefrei** sind und
mischflächig sehr wohl heizen (Whiteman 1982, Müller & Whiteman 1988).

| Zone | Reduktions-Faktor | H_max bei Schnee | dt_excess max | Grund |
|---|---|---|---|---|
| mittelland | 0.15 (85 % Reduktion) | 50 W/m² | 0.0 °C | Geschlossene Schneedecke, hohe Albedo, kein 2. Aufstieg |
| jura | 0.30 (70 %) | 80 W/m² | 0.5 °C | Teilweise abgeblasen, Felsbänder |
| voralpen | 0.45 (55 %) | 120 W/m² | 1.0 °C | Mischflächen Wald/Wiese/Fels |
| alpen | 0.60 (40 %) | 180 W/m² | 1.5 °C | Felswände dominieren, tiefe Talböden meist schneefrei |
| hochalpin | 0.75 (25 %) | 220 W/m² | 2.0 °C | Steile Felswände heizen extrem, oft trockene Luft |

**Effekt:** Im April-Tessin-Beispiel wechselt die Schnee-Dämpfung von „kompletter
Kill" zu „auf 75 % der schneefreien Heizleistung erlaubt", was XCT-konform ist.

### 3. GFS-PBL-Cap (`gfs_pbl_cap_factor`, `gfs_pbl_cap_mode`)

Heutiger Code (`thermik_calculator.py:812-821`) cappt die Thermikhöhe hart auf
die GFS-Boundary-Layer-Height. Problem: GFS-PBL hat über alpinem Terrain einen
**dokumentierten 200–500 m Bias nach unten** (Guo 2022, De Wekker & Kossmann
2015) — der Cap ist im Hochalpinen aktiv falsch.

| Zone | Modus | Faktor | Bedeutung |
|---|---|---|---|
| mittelland | `hard` | 1.0 | GFS-PBL ist hier verlässlich, Cap bleibt aktiv |
| jura | `hard` | 1.05 | Leichte Erhöhung wegen Gebirgsfaktor |
| voralpen | `soft` | 1.20 | Sigmoid-Übergang, kein scharfer Cut |
| alpen | `soft` | 1.35 | Cap wird nur als Sanity-Limit behandelt |
| hochalpin | `sanity_only` | 1.50 | GFS-PBL nur als Plausibilitätsschutz, Encroachment dominiert |

**Effekt:** Hochalpine Working Ceilings (Wallis 4400 m, Tessin 3700 m) werden
nicht mehr auf GFS-PBL-Niveau (~3000 m) heruntergezogen.

### 4. H-Schwelle als sanfte Rampe (`h_ramp_low`, `h_ramp_high`)

Heutiger Code hat `H_MIN_THRESHOLD = 30.0` als harten Cutoff. Literatur
(Kaimal & Finnigan 1994, Salesky 2017) zeigt, dass Konvektion weich einsetzt,
nicht binär. Der Cutoff erzeugt den „2–4 h zu späten Start" im Vergleich zu XCT.

| Zone | h_ramp_low (W/m²) | h_ramp_high (W/m²) | Bedeutung |
|---|---|---|---|
| mittelland | 25 | 60 | Smoothstep-Gewichtung 0→1 zwischen den Werten |
| jura | 22 | 55 | |
| voralpen | 20 | 50 | |
| alpen | 18 | 45 | |
| hochalpin | 15 | 40 | Niedrigster Threshold, dünne Luft löst früher aus |

**Effekt:** Morgens 09–10 Uhr Lokalzeit setzt die Thermik bei steigender
Sonneneinstrahlung weich ein, statt bei einem festen H-Wert plötzlich auf 0
zu springen.

### 5. Entrainment-Rate μ (`entrainment_mu`)

Heutiger Code: 2-Klassen-Interpolation zwischen `MU = 0.0002` (mittelland) und
`alpine_MU = 0.00015`. Literatur (Lenschow 1980, Stiperski & Rotach 2016)
zeigt deutlich differenziertere Werte:

| Zone | μ-Wert | Begründung |
|---|---|---|
| mittelland | 0.00020 | Hohe Bodenfeuchte → mehr Vermischung |
| jura | 0.00018 | |
| voralpen | 0.00017 | |
| alpen | 0.00015 | Organisierte Thermiken, weniger Einmischung |
| hochalpin | 0.00012 | Sehr trockene Luft, kohärenteste Aufwinde |

### 6. Climb-Faktor (`climb_factor_terrain`)

Der Spring-Faktor 0.85 ist im Mittelland **deutlich überkalibriert**. Im
Hochalpinen aber zu niedrig.

| Zone | Climb-Faktor (Frühling) | Begründung |
|---|---|---|
| mittelland | 0.60 | Hohe Bodenfeuchte, viel latenter Wärmefluss |
| jura | 0.65 | |
| voralpen | 0.70 | |
| alpen | 0.75 | |
| hochalpin | 0.80 | Trocken-adiabatisch, fast keine Latentverluste |

---

## Zusatz: Pressure-Level-Interpolation (`parcel_interp_dz_m`)

**Nicht terrain-differenziert**, aber wichtig für Hochalpin: Heute springt der
Parcel-Ascent zwischen Druckniveaus (z. B. 850 → 800 hPa = ~500 m Schritt).
Im Hochalpinen verfehlt das die Inversionen.

→ **Vor Parcel-Ascent linear auf dz=100 m interpolieren** (Wang 2021, Markowski
& Richardson 2010). Standard in allen modernen Soaring-Modellen (RASP, RegTherm).

---

## Geplante Struktur in `config.py`

Die neue `THERMAL_PARAMS`-Erweiterung soll alle obigen Werte als Dict-of-Dict
exponieren, damit `thermik_calculator.py` per `terrain_type` lookupbar:

```python
THERMAL_PARAMS = {
    # ... bestehende Felder ...

    # ============ TERRAIN-DIFFERENZIERTE PARAMETER (5 Zonen) ============
    "min_thermal_depth_agl": {
        "mittelland": 400, "jura": 350, "voralpen": 300,
        "alpen": 200,    "hochalpin": 150,
    },
    "snow_damping_factor": {
        "mittelland": 0.15, "jura": 0.30, "voralpen": 0.45,
        "alpen": 0.60,    "hochalpin": 0.75,
    },
    "snow_h_max_w_per_m2": {
        "mittelland": 50,  "jura": 80,  "voralpen": 120,
        "alpen": 180,    "hochalpin": 220,
    },
    "snow_dt_excess_max": {
        "mittelland": 0.0, "jura": 0.5, "voralpen": 1.0,
        "alpen": 1.5,    "hochalpin": 2.0,
    },
    "gfs_pbl_cap_mode": {
        "mittelland": "hard", "jura": "hard", "voralpen": "soft",
        "alpen": "soft",    "hochalpin": "sanity_only",
    },
    "gfs_pbl_cap_factor": {
        "mittelland": 1.00, "jura": 1.05, "voralpen": 1.20,
        "alpen": 1.35,    "hochalpin": 1.50,
    },
    "h_ramp_low": {
        "mittelland": 25, "jura": 22, "voralpen": 20,
        "alpen": 18,    "hochalpin": 15,
    },
    "h_ramp_high": {
        "mittelland": 60, "jura": 55, "voralpen": 50,
        "alpen": 45,    "hochalpin": 40,
    },
    "entrainment_mu": {
        "mittelland": 0.00020, "jura": 0.00018, "voralpen": 0.00017,
        "alpen": 0.00015,    "hochalpin": 0.00012,
    },
    "climb_factor_terrain": {
        "mittelland": 0.60, "jura": 0.65, "voralpen": 0.70,
        "alpen": 0.75,    "hochalpin": 0.80,
    },

    # Globale Konstante
    "parcel_interp_dz_m": 100,
}
```

Die alten Felder (`H_cap`, `alpine_H_cap`, `alpine_MU`, `alpine_snow_*`,
`terrain_elev_low`, `terrain_elev_high`) werden **nicht entfernt**, sondern
auf das Mittelland-/Hochalpin-Pendant der neuen Tabellen umgeleitet, damit
keine bestehende Logik bricht. Die 2-Klassen-`_terrain_factor()`-Funktion wird
durch eine `_terrain_zone(spot)`-Lookup-Funktion ersetzt, die `regionen.csv`
liest (analog zu `gust_calculator._load_region_terrain()`).

---

## Wie `thermik_calculator.py` die Zone abfragen soll

Vorbild: `gust_calculator._load_region_terrain()` liest beim Modul-Import
die `regionen.csv` einmal in einen Dict cache. Pro Spot wird via Region-Mapping
oder Nearest-Neighbor die `terrain_type`-Klasse bestimmt.

Pseudocode für die Integration:

```python
# Im thermik_calculator.py:
from gust_calculator import get_terrain_zone_for_spot  # ggf. extrahieren

def calculate_thermal_profile(..., spot_name=None, region_id=None):
    zone = get_terrain_zone_for_spot(spot_name, region_id)  # → "hochalpin" etc.

    # Statt:
    #   factor = _terrain_factor(elevation_m)
    #   H_cap = (1-factor)*250 + factor*310
    # jetzt:
    H_cap = THERMAL_PARAMS["H_cap_terrain"][zone][season]
    mu    = THERMAL_PARAMS["entrainment_mu"][zone]
    snow_factor = THERMAL_PARAMS["snow_damping_factor"][zone]
    min_depth   = THERMAL_PARAMS["min_thermal_depth_agl"][zone]
    cap_mode    = THERMAL_PARAMS["gfs_pbl_cap_mode"][zone]
    # ...
```

Spots ohne Regions-Zuordnung fallen auf einen Default zurück (typischerweise
`alpen` als „mittlere" Zone, dokumentiert in der Lookup-Funktion).

---

## Erwartete Auswirkung pro Region

Validiert anhand der DI 07.04.2026 Vergleichsdaten:

| Region | Heute (FC) | Nach Kalibrierung (Erwartung) | XCT (Referenz) |
|---|---|---|---|
| Tessin Nord | 0.0 m/s | ~2.0–2.3 m/s | 2.2 m/s |
| Zentralwallis | 1.4 m/s | ~2.2–2.4 m/s | 2.4 m/s |
| Engadin Unter | 1.6 m/s | ~2.0–2.3 m/s | 2.2 m/s |
| Mittelland Zentral | 1.4 m/s | ~1.6–1.8 m/s (kleine Korrektur, climb_factor) | 2.5 m/s* |
| Schwarzsee | 2.0 m/s | ~2.0–2.2 m/s (fast unverändert) | 1.9 m/s |
| Berner Oberland | 1.9 m/s | ~2.0 m/s (fast unverändert) | 2.0 m/s |
| Jura West | 1.8 m/s | unverändert | 1.8 m/s |

\* Mittelland Zentral bei XCT bleibt eine offene Diskrepanz — XCT könnte hier
ein Gain haben, der mit dem Volumeneffekt zusammenhängt, den Gleitcast nicht
modelliert (siehe Recherche-Dokument, Abschnitt „Limitierungen").

**Working-Ceiling-Erwartungen:**

| Region | Heute (FC) | Nach Kalibrierung | XCT |
|---|---|---|---|
| Tessin Nord | – | ~3700 m | 3700 m |
| Zentralwallis | 3274 m | ~4300 m | 4400 m |
| Engadin Unter | 3274 m | ~4100 m | 4400 m |

---

## Implementierungs-Reihenfolge (nach Freigabe)

1. **Pressure-Level-Interpolation** (dz=100 m) — kleinster Eingriff, größter Effekt
   im Hochalpinen, kein neuer Konfigurations-Lookup nötig.
2. **`min_thermal_depth_agl`** ersetzt 150-m-Hardcode — entfernt den Tessin-Killer.
3. **`gfs_pbl_cap_mode` + `gfs_pbl_cap_factor`** — gibt Wallis/Engadin/Tessin
   ihre Working Ceilings zurück.
4. **Schnee-Parameter-Trio** (`snow_damping_factor`, `snow_h_max_w_per_m2`,
   `snow_dt_excess_max`) — nuancierte Behandlung von Mischflächen.
5. **`h_ramp_low/high`** — verschiebt Thermik-Start-Time auf XCT-Level.
6. **`entrainment_mu`** + **`climb_factor_terrain`** — Feinkalibrierung.

Jeder Schritt einzeln testbar gegen die DI-07.04.2026-Referenz. Smoke-Test
wäre `tests/test_e2e_meteogram.py` plus ein neuer `test_terrain_zones.py`.

---

## Was *nicht* angefasst wird

Diese Kalibrierung berührt **nicht**:

- Die Energiekette (`direct_radiation_to_H`, `diffuse_radiation_to_H`) — die
  Modell-Strahlungs-Konversion bleibt seasonalisiert, nicht terrainisiert.
- Die DWD-Updraft-Blending-Logik (`use_dwd_updraft_blending`).
- Die Cloud-Aggregation (30th-Perzentil) — die ist orthogonal.
- Die Wind-Pipeline (`gust_calculator.py`) — terrain-Zonen sind dort schon
  korrekt implementiert, dieses Doc bringt nur den Thermik-Calculator nach.
- Den `THERMIK_MODELL.md`-Erklärtext für Endnutzer — der wird in einem
  separaten Schritt ergänzt, sobald die Kalibrierung implementiert ist.

---

## Schritt 7 — Rock-Face Rescue (Zentralwallis-Fix)

**Motivation (April 2026 Produktionsbefund):** Obwohl die Schritte 1–6 alle
implementiert waren, zeigte Zentralwallis (hochalpin, elev_ref 2100 m) am
7. April 2026 durchgehend `climb_rate=0` — während LLM-Analyse und Referenz-
Piloten von ~2 m/s und 4-5 h Thermikflug sprachen. Debugging (siehe
`debug_scripts/debug_zentralwallis_profile.py`) ergab:

- Schneedecke 2.1 m drückt T2m auf 4.6 °C
- Pressure-Level-Environment bei 2100 m: **7.6 °C** (Warmluftadvektion)
- → künstliche **bodennahe Inversion von ~3 K**
- Parcel-Aufstieg scheitert unmittelbar, `max_thermal_height` pinnt bei 2167 m
- `min_thermal_depth_agl=150 m` (Schritt 2) killt `rating/climb` komplett

**Ursache der Regional-Bias:** In `_regions`-Mittelwerten dominieren die
grossflächig schneebedeckten Nordhänge und Plateaus. Die **subgrid-skaligen
schneefreien Südwände** (20–30 °C Oberflächentemperatur in der
Frühlingssonne) sind in T2m und `snow_depth` nicht abgebildet, liefern aber
in Wirklichkeit den Grossteil der alpinen Frühlingsthermik.

Alte Code-Logik in `thermik_calculator.py:846` blockierte bei `snow_depth > 5 cm`
die solare Überhitzung vollständig (`dt_excess = 0.0`) — und damit die einzige
Chance, die künstliche Inversion zu durchbrechen.

**Fix:** `terrain_zone in ("voralpen", "alpen", "hochalpin")` bei
`shortwave_radiation > 300 W/m²` erhält einen partiellen solaren Boost:

```
dt_excess = base_dt × rock_face_base_fraction + rock_face_dt_boost_C
dt_excess = min(dt_excess, solar_max × 2.5)   # Safety Cap
```

Neue Config-Parameter in `THERMAL_PARAMS`:

| Zone | `rock_face_dt_boost_C` | `rock_face_base_fraction` |
|---|---|---|
| mittelland | 0.0 | 0.0 |
| jura | 0.0 | 0.0 |
| voralpen | 0.8 | 0.3 |
| alpen | 1.5 | 0.5 |
| hochalpin | 2.5 | 0.7 |

Mittelland und Jura bleiben bei vollständiger Blockade — dort gibt es keine
relevanten Felswände, homogene Wiesen-/Wald-Schneedecke.

**Resultat Zentralwallis 7. April 2026:** rating 7, peak 2.5 m/s bei 14:00,
`max_h` 3253 m (1153 m AGL). Deckt sich mit Pilotenerfahrung und LLM-Analyse.

---

## Schritt 7b — Winter-Gates für Rock-Face Rescue

**Motivation:** Schritt 7 hatte nur zwei Bedingungen (`zone in alpin-Familie`
und `shortwave_radiation > 300`). Im Tiefwinter (Dez/Jan) bei klaren Tagen an
Hochalpin-Regionen wird `shortwave_radiation > 300` trotz tiefen Sonnenstands
durchaus erreicht — wäre der Branch dann aktiv, könnte er **fälschlich
Thermik in einer Saison erzeugen, in der Piloten empirisch keine nutzbaren
Thermiken finden**.

Empirische Paragliding-Saison im Alpenraum:
- November–Mitte Februar: keine zentrierbaren Thermiken am Hochalpinen
- Mitte Februar (Südalpen) bzw. März (Nordalpen): Saisonstart
- April–Oktober: Vollsaison

**Ansatz:** Statt ad-hoc-Schwellen werden zwei **physikalisch begründete
Gates** hinzugefügt, beide aus der publizierten Literatur abgeleitet:

### Gate 1 — Geometrisches Gate: `direct_radiation > 400 W/m²`

Die Strahlung auf eine vertikale südexponierte Felswand skaliert mit dem
Sonnenstand. Open-Meteo liefert `direct_radiation` auf horizontaler Fläche,
was einem Proxy für den Sonnenstand entspricht (bei DNI ≈ 800 W/m² in der
klaren Bergluft):

| Datum (47°N) | Sonnenhöhe Mittag | sin(h) | direct_radiation (horizontal) |
|---|---|---|---|
| 21. Dez | 19.5° | 0.33 | **267 W/m²** ✗ |
| 21. Jan | 22° | 0.37 | 300 W/m² ✗ |
| 15. Feb | 30° | 0.50 | **400 W/m²** ✓ (Schwelle) |
| 21. Mär | 43° | 0.68 | 545 W/m² ✓ |
| 21. Apr | 55° | 0.82 | 656 W/m² ✓ |

Die 400-W/m²-Schwelle entspricht genau dem Übergang Sonnenhöhe 30°, der bei
**Hahn & Ohmura (1992)** *Trend of total solar radiation in the Swiss Alps*
(Theor. Appl. Climatol. 46, 161–170) als Mindest-Sonnenstand für nutzbare
Konvektion in den Schweizer Alpen identifiziert wurde.

### Gate 2 — Energetisches Gate: `H > 25 W/m²`

Organisierte Konvektion (im Sinne zentrierbarer Thermikschläuche statt
chaotischer Mikro-Eddies) benötigt einen minimalen sensiblen Wärmestrom:

- **Whiteman (2000)** *Mountain Meteorology: Fundamentals and Applications*
  §6.3: Anabatische Hangwinde entwickeln sich erst bei `H ≥ 25–50 W/m²`
  sustained.
- **Stull (1988)** *Boundary Layer Meteorology* §11.4: Konvektive Initiation
  in stabilen Profilen erfordert `H > 30 W/m²`.
- **Reiter & Tang (1984)** *Plateau Effects on Diurnal Circulation* (MWR 112,
  638–651): Hangwindsysteme im Alpenraum messbar erst bei Boden-Luft-
  Differenzen > 5 K UND durchbrochener Inversion.

**Wichtig:** `H` ist hier bereits *nach* `snow_damping_factor` (Schritt 4)
angewendet worden. Das heisst, das Gate misst die **effektive** Heizleistung
der Region als Ganzes (Schnee-Mittel über Süd-/Nord-Hänge), nicht das
theoretische Maximum auf einer einzelnen Felswand. Im Tiefwinter mit
grossflächiger Schneedecke und flacher Sonne bleibt `H` regional unter der
Schwelle → Branch wird korrekt deaktiviert.

### Implementierung

`thermik_calculator.py:846`, UND-Verknüpfung aller vier Bedingungen:

```python
rock_face_zone = terrain_zone in ("voralpen", "alpen", "hochalpin")
sw_ok = shortwave_radiation is not None and shortwave_radiation > 300
direct_ok = direct_radiation is not None and direct_radiation > 400
h_ok = H > 25

if rock_face_zone and sw_ok and direct_ok and h_ok:
    # Rock-Face Rescue (Schritt 7)
    ...
else:
    dt_excess = 0.0
    # blockers-Liste ins data_warnings (Debugging-Transparenz)
```

Warnmeldung erklärt welches Gate gesperrt hat:

```
"Keine solare Überhitzung wegen Schneedecke
 (Rock-Face Gates: dir_rad=280<400, H=15<25)."
```

### Validierung gegen die vier Eckfälle

| Fall | Bedingungen | Resultat | Erwartet |
|---|---|---|---|
| **A — Zentralwallis 7. April 14 h** | T2m=4.6 °C, SW=850, dir_rad≈700, H≈60 | **Branch aktiv** → rating 7, climb 2.5 m/s | ✓ Frühlings-Fall erhalten |
| **B — Zentralwallis 7. Januar 14 h** (hypothetisch) | T2m=-8 °C, SW≈450, dir_rad≈280, H≈10 | Branch blockiert (dir_rad<400, H<25) → 0 | ✓ Tiefwinter korrekt |
| **C — Zentralwallis Mitte März klar** | T2m≈0 °C, SW≈700, dir_rad≈540, H≈30 | Branch aktiv → rating 3-4, schwach | ✓ Saisonanfang plausibel |
| **D — Zentralwallis Mitte Februar** | T2m≈-3 °C, SW≈550, dir_rad≈400 (Grenze), H≈15 | Branch blockiert (H<25) → 0 | ✓ noch zu früh |

### Validierung April-Cache (alle 29 Regionen)

Run von `debug_scripts/debug_all_alpine.py` gegen `data/wetterdaten.json`
(2026-04-07) nach Implementierung der Gates:

```
Zone summary:
  mittelland :  4 regions,  0 schneebedeckt,  0 mit Rock-Face Branch aktiv
  jura       :  3 regions,  0 schneebedeckt,  0 mit Rock-Face Branch aktiv
  voralpen   :  5 regions,  2 schneebedeckt,  2 mit Rock-Face Branch aktiv
  alpen      :  6 regions,  3 schneebedeckt,  3 mit Rock-Face Branch aktiv
  hochalpin  : 11 regions, 10 schneebedeckt, 10 mit Rock-Face Branch aktiv
```

**15 von 15 Frühlings-Treffern unverändert** aktiv. Zentralwallis weiterhin
rating 7, peak 2.5 m/s bei 14:00, `max_h` 3253 m (1153 m AGL). Die Gates
lassen den kalibrierten Frühlingsfall vollständig durch.

---

## Schritt 8 — Depth-Ramp (Weiche Thermikhöhen-Schwelle)

**Motivation (April 2026):** Unterwallis (hochalpin, elevation_ref=2200m) zeigte
im Meteogram keinen Morgenübergang — die Thermik sprang von 0 direkt auf volle
Stärke bei ~3 km. XC-Therm/Regtherm dagegen zeigt eine saubere Glocke mit
0.4 m/s ab 07:00, graduell steigend auf 2.1 m/s. Der Grund: der harte Cutoff
in Schritt 2 (`if max_thermal_height < elevation_m + min_depth_agl: avg_climb = 0.0`)
unterdrückte jegliche Thermik, solange die Thermiktiefe unter der Schwelle lag.

**Problem:** Das Deardorff w*-Scaling (`w* = (g/θ · H · z_i)^(1/3)`) ist eine
stetige Kubikwurzel — bei flacher konvektiver Schicht entstehen automatisch
kleine w*-Werte, nicht Null. Ein binärer Cutoff widerspricht dieser Physik und
erzeugt unrealistische Sprünge. Kein operationelles Soaring-Modell (RASP/DrJack,
BLIPMAP, RegTherm) verwendet eine solche Mindest-Tiefe als Killswitch.

**Lösung:** Linearer Dimmer (Ramp) statt Lichtschalter. Gleiche Muster wie die
bestehende H-Ramp (Schritt 5):

```
depth_agl = max_thermal_height - elevation_m

if depth_agl <= 0:
    factor = 0.0  (kein Steigen, physikalisch korrekt)
elif depth_agl < min_depth_agl:
    factor = depth_agl / min_depth_agl  (lineare Rampe)
else:
    factor = 1.0  (unveraendert)

avg_climb *= factor
rating = min(rating, max(1, round(rating * factor)))
```

Kein neuer Config-Parameter — `min_thermal_depth_agl` wird als obere Grenze der
Rampe wiederverwendet.

### Beispielwerte (hochalpin, min_depth=150m)

| depth_agl | factor | Effekt |
|---|---|---|
| 0 m | 0.00 | Kein Steigen (unterhalb Start) |
| 30 m | 0.20 | ~0.4 m/s statt 2.0 m/s |
| 75 m | 0.50 | ~1.0 m/s (halbes Steigen) |
| 120 m | 0.80 | ~1.6 m/s (fast voll) |
| 150 m | 1.00 | Unveränderter Wert |
| 300 m | 1.00 | Nachmittag: volle Tiefe, kein Einfluss |

### Vergleich: XC-Therm Valais Central Do 16.04

| Uhrzeit | XC-Therm | Gleitcast vorher | Gleitcast nachher |
|---|---|---|---|
| 07:00 | 0.4 m/s | 0.0 m/s | ~0.3–0.5 m/s |
| 09:00 | 0.8 m/s | 0.0 m/s | ~0.6–0.9 m/s |
| 11:00 | 1.5 m/s | 0.0 m/s | ~1.2–1.5 m/s |
| 13:00 | 2.1 m/s | 2.1 m/s | 2.1 m/s (unverändert) |
| 15:00 | 1.8 m/s | 1.8 m/s | 1.8 m/s (unverändert) |

### Physikalische Referenzen

- **Stull (1988)** *Boundary Layer Meteorology* §11: w* ist stetig, Kubikwurzel
  erzeugt natürlichen „Glocken"-Verlauf der Steigwerte über den Tag.
- **Kaimal & Finnigan (1994)** *Atmospheric Boundary Layer Flows* §4: Konvektive
  Turbulenz setzt graduell ein, kein diskreter Threshold.
- **RASP/BLIPMAP** (DrJack): Verwendet kein `min_thermal_depth` Gate — w* wird
  direkt aus BLH und H berechnet, kleine BLH → kleine w* → kleiner Climb.

---

## Quellen und tiefe Begründung

Alle obigen Zahlen sind in `meteo_research/thermal_model_calibration.md` mit
Peer-Reviewed-Quellen unterlegt (Lenschow 1980, Stull 1988, Kaimal & Finnigan
1994, Whiteman 1982, Müller & Whiteman 1988, De Wekker & Kossmann 2015,
Stiperski & Rotach 2016, Guo 2022, Salesky 2017, Allen 2006, Markowski &
Richardson 2010, Wang 2021 u.a., insgesamt 28 Quellen).

Bei Kalibrierungs-Diskussionen oder Werte-Anpassungen bitte zuerst dort
nachschlagen — dieser Leitfaden ist die *Anwendungs-Sicht*, das
Recherche-Dokument die *Begründungs-Sicht*.
