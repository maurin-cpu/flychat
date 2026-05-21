# Wettermodelle — Architektur und Tiering

> **SYNC-PFLICHT für Claude:** Diese Doku ist die **Single Source of Truth**
> der Modell-Auswahl pro Wetterparameter. Wenn ein Modell-Slot in `config.py`
> umgestellt oder ein neuer Tier hinzugefügt wird, MUSS diese Datei
> mit aktualisiert werden — sonst geraten Code, Skills und Doku auseinander.

## Übersicht

Gleitcast nutzt **fünf numerische Wettermodelle** parallel, jedes für die
Parameter, bei denen es physikalisch am ehrlichsten ist. Die Modell-Auswahl
ist nicht statisch — pro Tag wird das beste verfügbare Modell gewählt
(Tag-Voting / Tiering).

| Modell | Anbieter | Auflösung | Horizont | Konvektion | Kalibrierung | Surface | PL | BLH |
|---|---|---|---|---|---|---|---|---|
| **ICON-CH1** | MeteoSwiss | 1.1 km | 33 h | aufgelöst | Schweiz | ✓ | — | — |
| **ICON-CH2** | MeteoSwiss | 2.1 km | 5 d (120 h) | aufgelöst | Schweiz | ✓ | — | — |
| **ICON-D2**  | DWD | 2.2 km | 48 h | aufgelöst | Pan-Europa | (✓) | ✓ | — |
| **ICON-EU**  | DWD | 13 km | 5 d | parametrisiert | Pan-Europa | ✓ | ✓ | — |
| **GFS**      | NOAA | ~25 km | 5 d | parametrisiert | global | (✓) | ✓ | ✓ |

> **Open-Meteo-Limit (Mai 2026 verifiziert):**
> - **CH1/CH2** liefern **nur Surface-Variablen** (kein PL, kein BLH).
> - **D2-Surface** wird nur noch für die Variablen genutzt, die CH-Modelle
>   nicht haben (`soil_moisture_0_to_1cm`, `soil_temperature_0cm`, `updraft`).
> - **BLH** liefert nur GFS (alle ICON-BLH-Felder kommen leer zurück).

---

## Anwendungs-Tabelle (was kommt von wem?)

Surface-Variablen folgen einem **4-Tier-Voting** (siehe unten). Die Tabelle
zeigt den Normalfall innerhalb der CH-Coverage:

| Variable | Tag 1 (0–33h) | Tag 2 | Tag 3–5 | CH-rand Tag 1–2 | CH-rand Tag 3–5 |
|---|---|---|---|---|---|
| **Wind (speed/dir/gusts_10m)** | CH1 | CH2 | CH2 | **D2** | EU |
| **temperature_2m, relative_humidity_2m** | CH1 | CH2 | CH2 | **D2** | EU |
| **cloud_cover (alle Stockwerke), cloud_base** | CH1 | CH2 | CH2 | **D2** | EU |
| **shortwave/direct/diffuse_radiation, sunshine_duration** | CH1 | CH2 | CH2 | **D2** | EU |
| **precipitation, precipitation_probability, rain, weather_code** | CH1 | CH2 | CH2 | **D2** | EU |
| **cape, convective_inhibition, lifted_index** | CH1 | CH2 | CH2 | **D2** | EU |
| **pressure_msl, surface_pressure** | CH1 | CH2 | CH2 | **D2** | EU |
| **et0_fao_evapotranspiration, vapour_pressure_deficit, snow_depth** | CH1 | CH2 | CH2 | **D2** | EU |
| **soil_moisture_0_to_1cm, soil_temperature_0cm, updraft** | D2 | D2 | EU | D2 | EU |
| **alle `*_hPa` (T, Wind, Geopotenzial, Druckniveaus)** | D2 | D2 | EU | D2 | EU |
| **boundary_layer_height** | GFS | GFS | GFS | GFS | GFS |
| **Niederschlag dichte 16-RP-Aggregation** | CH2 | CH2 | CH2 | CH2/EU | EU |

**CH-rand** = Spots/Punkte außerhalb der CH1/CH2-Coverage (~50 km Puffer um
die Schweiz), typisch Tessin Süd Richtung Italien, südliche Walliser Täler,
südliches Engadin Richtung Italien. D2 deckt Alpenraum + Norditalien
großzügig auf 2.2 km ab — deutlich besser als EU-13km.

---

## Modell-Slots in `config.py`

Die zentrale Sektion `WETTERMODELLE` in `config.py` definiert sieben Slots mit
klarer Rolle:

```python
# Surface-Tier (4-Tier: CH1 → CH2 → D2 → EU)
SURFACE_PRIMARY_MODEL   = "meteoswiss_icon_ch1"   # Tier 1: Tag 1, CH
SURFACE_SECONDARY_MODEL = "meteoswiss_icon_ch2"   # Tier 2: Tag 2-5, CH
SURFACE_TERTIARY_MODEL  = "icon_d2"               # Tier 3: CH-rand, Tag 1-2
SURFACE_FALLBACK_MODEL  = "icon_eu"               # Tier 4: Notfall

# Pressure-Level (D2 → EU)
PRESSURE_LEVEL_PRIMARY_MODEL  = "icon_d2"
PRESSURE_LEVEL_FALLBACK_MODEL = "icon_eu"

# BLH (GFS-only)
BLH_MODEL = "gfs_seamless"

# Niederschlag dichte 16-RP-Aggregation
PRECIP_DENSE_MODEL = "meteoswiss_icon_ch2"

# Multi-Gust-Merge
GUST_MERGE_MODELS = ["icon_d2", "meteoswiss_icon_ch1", "meteoswiss_icon_ch2"]

# Horizonte
FORECAST_DAYS_CH1 = 2   # real ~33h
FORECAST_DAYS_CH2 = 5
FORECAST_DAYS_D2  = 2   # real 48h
FORECAST_DAYS_EU  = 5
FORECAST_DAYS_GFS = 5

# Surface-Param-Set (was CH1/CH2 ueber Open-Meteo liefern)
CH_SURFACE_PARAMS = [25 Variablen — siehe config.py]
```

Legacy-Aliase (`WIND_MODEL`, `THERMAL_MODEL`, `FALLBACK_MODEL`, `PRECIP_MODEL`,
`CH1_MODEL`, `CH2_MODEL`, `API_MODEL`, `CH1_FORECAST_DAYS`, `CH2_FORECAST_DAYS`)
zeigen weiterhin auf die kanonischen Slots — alte Skripte funktionieren
unverändert.

---

## Tag-Voting / Tiering (Implementierung)

Pro Tag und pro Parameter-Gruppe wird das beste verfügbare Modell gewählt.
**Kein Mischen innerhalb eines Tages** — wenn CH1 für 06:00 valid ist und
für 12:00 nicht, fällt der ganze Tag auf den nächsten Tier.

Implementiert via `is_model_valid_for_day()` in `fetch_weather.py:518–534`:
ein Modell ist "valid für Tag X", wenn für **alle Flugstunden**
(`FLIGHT_HOURS_START..END`) der Test-Parameter (z.B. `wind_speed_10m`)
einen nicht-`None` Wert liefert.

### Surface-Schicht (4-Tier)

```
CH1 (33h, 1.1km)  →  CH2 (5d, 2.1km)  →  D2 (48h, 2.2km)  →  EU (13km, Notfall)
   in-CH Tag 1       in-CH Tag 2-5      CH-rand Tag 1-2     CH-rand Tag 3-5
```

Gilt für **alle 25 Variablen in `CH_SURFACE_PARAMS`** (Mai 2026 erweitert
von ursprünglich nur Wind auf alle CH-fähigen Surface-Variablen, plus D2
als Tier-3 fuer Spots ausserhalb der CH-Coverage).

Implementierung:
- `_process_spot_weather:541–560` baut `wind_model_by_day` (= eigentlich
  `surface_model_by_day`, historischer Variablenname) mit 4-Tier-Fallback.
- `_process_spot_weather:584–593` überschreibt im Per-Stunde-Loop alle
  `CH_SURFACE_PARAMS` aus der per-Tag gewählten Quelle.
- Andere Surface-Variablen (`soil_moisture`, `soil_temperature`, `updraft`)
  kommen weiterhin aus `thermal_model_by_day` (D2 → EU, 2-Tier).
- D2-Batch (`thermal_params`) liefert seit Mai 2026 wieder die vollen
  CH_SURFACE_PARAMS — fuer Tier-3-Fallback und Region-Precip-Aggregation.

### Pressure-Level (2-Tier)

```
D2 (48h, 2.2km) → EU (13km, ab Tag 3 und bei D2-Ausfall)
```

Implementierung: `_process_spot_weather:611–629` für `PRESSURE_LEVEL_PARAMS`,
mit EU-Backfill bei D2-Lücken.

**D2 deckt nur Tag 1–2** — der Wechsel auf EU für Tag 3–5 ist der
**Normalfall**, nicht ein Notfall. Die Auflösung verschlechtert sich
von 2.2 km auf 13 km in der freien Atmosphäre — akzeptabel, weil PL-Daten
über die Synoptik ohnehin großräumig kohärent sind.

### Niederschlag — zwei Pfade

**A) Regulärer 7-RP-Pfad** (im Thermal- bzw. CH-Surface-Batch enthalten):
`precipitation`-Werte sind Teil von `CH_SURFACE_PARAMS`, folgen also dem
Surface-Tier-Voting CH1 → CH2 → EU.

**B) Dense-16-RP-Override** (`fetch_weather.py:_override_precip_with_dense_rps`):
nutzt `PRECIP_DENSE_MODEL` (CH2) für alle 5 Tage. Der Hybrid-Filter
(Peak + Coverage) ersetzt die regulären `precipitation`-Werte im
aggregierten Region-Cache. Siehe `meteo_research/precipitation_aggregation.md`.

### BLH (1-Quelle)

```
GFS (5d, 25km) — keine Alternative
```

ICON-BLH-Felder sind via Open-Meteo seit Mai 2026 alle `null` (D2, EU,
Global, ECMWF auch). Im Code wird GFS-BLH als **optionaler Cap** auf die
Parcel-BLH genutzt (`thermik_calculator.py:1184–1232`), mit drei Modi
pro Terrain-Zone (`gfs_pbl_cap_mode`):

- **`hard`** (Mittelland, Jura): harter Deckel
- **`soft`** (Voralpen, Alpen): 50/50-Blend
- **`sanity_only`** (Hochalpin): nur Warnung (GFS unterschätzt dort)

Die eigentliche BLH wird im Code als **Parcel-BLH** (Tennekes 1973) selbst
berechnet — GFS ist nur Plausibilisierung, nicht Hauptquelle.

---

## Multi-Modell-Böen-Merge

Zusätzlich zum 3-Tier-Surface-Voting läuft auf den **Böen** (`wind_gusts_10m`)
ein konservativer Multi-Max-Merge:

```python
wind_gusts_10m = max(verfügbare aus GUST_MERGE_MODELS)
                = max(D2_gust, CH1_gust, CH2_gust)
```

Implementierung: `_process_spot_weather:677–685`.

**Effektive Modell-Verfügbarkeit pro Tag:**

| Tag | D2 (48h) | CH1 (33h) | CH2 (5d) | Effektiver Merge |
|---|---|---|---|---|
| 1 | ja | ja | ja | max(D2, CH1, CH2) — Vollvergleich |
| 2 | ja | nur ~9h | ja | max(D2, CH2) |
| 3–5 | nein | nein | ja | nur CH2 (kein Merge mehr) |

Begründung: Böen unterschätzen ist gefährlicher als überschätzen
(Fliege-Entscheidung). Maximum aus den verfügbaren Modellen ist
konservativ. Aktiviert via `MULTI_MODEL_GUST_MERGE = True` in `config.py`.

Original-D2-Wert wird unter `wind_gusts_10m_d2` aufbewahrt, falls der
Multi-Max-Merge etwas Höheres liefert. Einzelmodell-Werte
(`wind_gusts_10m_ch1`, `wind_gusts_10m_ch2`) stehen ebenfalls im Cache
für Transparenz/Debug.

---

## Batch-API-Calls (`fetch_all_spots`)

| # | Batch | Modell | Punkte | Vars | Forecast-Days |
|---|---|---|---|---|---|
| 1 | **CH1-Surface** | `SURFACE_PRIMARY_MODEL` | Spots | `CH_SURFACE_PARAMS` (25) | `FORECAST_DAYS_CH1` (2) |
| 2 | **Thermal/PL** | `PRESSURE_LEVEL_PRIMARY_MODEL` | unique RPs | D2-Surface (3) + PL (52) | `FORECAST_DAYS_D2` (2) |
| 3 | **Fallback** | `SURFACE_FALLBACK_MODEL` | unique RPs | alles (Surface + PL) | `FORECAST_DAYS_EU` (5) |
| 4 | **GFS** | `BLH_MODEL` | Spots | BLH + Supplements (3) | `FORECAST_DAYS_GFS` (5) |
| 5 | **CH2-Surface** | `SURFACE_SECONDARY_MODEL` | Spots | `CH_SURFACE_PARAMS` (25) | `FORECAST_DAYS_CH2` (5) |
| 6 | **Precip-Dense** | `PRECIP_DENSE_MODEL` | 16 RPs × N Regionen | precip (2) | 5 |
| 7 | **Region-Thermal** | `THERMAL_MODEL` (alias) | region-only RPs | D2-Surface + PL | 5 |
| 8 | **Region-Fallback** | `FALLBACK_MODEL` (alias) | region-only RPs | alles | 5 |

**Mai 2026 Änderung:** Die separate "Batch Wind"-Anfrage entfällt — der
CH1-Surface-Batch (Nr. 1) ist jetzt sowohl primäre Surface-Quelle als auch
CH1-Anker für den Multi-Gust-Merge. `batch_ch1 = batch_wind` im Code.

---

## Per-Spot-Verarbeitung (`_process_spot_weather`)

| Schritt | Quelle |
|---|---|
| `entry[CH_SURFACE_PARAMS]` (25 Vars) | CH1 → CH2 → **D2** → EU (4-Tier) |
| `entry[soil_moisture, soil_temperature, updraft]` | D2 (Tag 1–2) → EU |
| `entry[PRESSURE_LEVEL_PARAMS]` | D2 (Tag 1–2) → EU |
| `entry[wind_gusts_10m]` (Override) | `max(D2, CH1, CH2)` (Multi-Merge) |
| `entry[boundary_layer_height_gfs]` | GFS |
| `entry[lifted_index, convective_inhibition]` | GFS (Supplement) |

---

## Region-Pfad

Regionen nutzen denselben `_process_spot_weather`-Pfad, aber ohne
`data_ch2` (CH2-Batch läuft nur für Spots). Folge: Regionen sind
**de facto 1-Tier auf D2/EU** (Surface). Surface-CH-Voting fällt durch
auf den Fallback (D2 thermal → EU).

Für Niederschlag greift der Dense-Override (CH2 aus dem Precip-Dense-Batch),
unabhängig vom Spot/Region-Pfad.

**Offen:** Falls Regionen ebenfalls CH-Surface-Voting brauchen, müsste
ein `batch_region_ch1` + `batch_region_ch2` ergänzt werden (heute nicht
im Code).

---

## Coverage-Eigenheiten

- **ICON-CH1/CH2** decken Schweiz + Randbereich (~50 km Puffer). Sehr
  randige Spots (Tessin Süd, Lago Maggiore Süd, Genfersee West) können
  punktuell `None` zurückgeben. Tag-Voting fällt dann automatisch auf
  den nächsten Tier zurück.
- **ICON-D2** deckt Deutschland + Alpenraum großzügig — keine Lücken
  in der Schweiz erwartet.
- **ICON-EU** und **GFS**: globale Abdeckung, keine Lücken.

---

## Begründung der Default-Wahl

### Warum CH1 für Surface-Tier-1?
1.1 km Auflösung in der Schweiz — beste Talwind-, Hangeffekt- und
Channeling-Auflösung. Wichtig für Bodenwind-Richtung, Wolken-Aufbau
über Bergrücken und konvektive Schauerzellen. Schweiz-Kalibrierung
(MeteoSwiss) schlägt DWD-Pan-Europa für die CH-Geographie.

### Warum CH2 für Surface-Tier-2?
2.1 km MeteoSwiss-Kalibrierung schlägt 13 km DWD-Pan-Europa für die
Schweiz deutlich. Surface-Korrektur (ICON Surface Scheme) ist auf
alpines Gelände abgestimmt. 5 Tage Horizont schließt die Lücke
zwischen CH1 (33h) und Cast-Ende komplett.

### Warum D2 für Pressure-Level (Tag 1–2)?
DWD ICON-D2 hat die ausgereifteste 2-km-PL-Coverage via Open-Meteo
(CH1/CH2 liefern keine PL, EU nur 13 km). Konvektionsauflösend,
PL-Coverage ausreichend für Höhenwindprofil und T_850/T_700-Stabilität.
**Horizont ist auf 48 h begrenzt** — Tag 3–5 fallen zwangsläufig auf
EU zurück.

### Warum D2 als Tier-3 (CH-rand-Fallback)?
2.2 km Pan-Europa-Coverage. Deckt Alpenraum + Norditalien + Süddeutschland
großzügig ab — fängt damit Spots auf, die ausserhalb der CH1/CH2-Coverage
liegen (Tessin Süd, Walliser Südtäler, südliches Engadin). Deutlich besser
als direkt auf EU (13 km) zurückzufallen. Beschränkt durch D2-Horizont:
nur Tag 1–2, danach übernimmt EU.

### Warum EU als Tier-4 / Fallback?
13 km Pan-Europa, sehr stabil, keine Coverage-Lücken, alle Variablen
inkl. allen Druckniveaus. Suboptimale Auflösung, aber als Notfall
besser als kein Wert. Greift nur noch Tag 3+ ausserhalb der CH-Coverage,
weil D2-Horizont auf 48h begrenzt ist.

### Warum GFS für BLH?
Einzige verfügbare Quelle via Open-Meteo (Mai 2026 verifiziert).
ICON-BLH-Felder (D2, EU, Global) kommen alle `null` zurück, ECMWF
auch nicht. GFS ist 25 km — grob, aber für Plausibilisierung der
Parcel-BLH (selbst berechnet) ausreichend.

### Warum CH2 für Precip-Dense?
Konvektionsauflösend (im Gegensatz zu EU) **und** auf den Alpenraum
kalibriert (im Gegensatz zu D2). Schauer-Geographie (Stau, Lee, Föhn)
realistischer. Der Hybrid-Filter aus `precipitation_aggregation.md`
funktioniert nur sinnvoll auf konvektionsauflösenden Modellen.

---

## Changelog

- **Mai 2026** — **4-Tier-Surface-Voting eingeführt**: CH1 → CH2 → **D2** → EU.
  Vorher fielen CH-rand-Spots (Tessin Süd, Walliser Südtäler) direkt auf
  EU (13 km) zurück — jetzt fängt D2 (2.2 km, Pan-Europa) sie Tag 1–2 auf.
  D2-Batch holt wieder die vollen `CH_SURFACE_PARAMS` (war kurzzeitig nur
  soil/updraft/PL). Neuer Slot `SURFACE_TERTIARY_MODEL = "icon_d2"` in
  `config.py`. Behebt zudem die Region-Precip-Aggregation-Regression
  (EU-13 km als Fallback war zu grob für konvektive Schauerzellen).
- **Mai 2026** — **Surface-Tier-Voting auf alle CH-fähigen Variablen
  erweitert** (vorher nur Wind). Spots beziehen Wolken, Temperatur,
  Strahlung, Precip, CAPE jetzt von CH1 (Tag 1) → CH2 (Tag 2–5) → EU
  statt D2-Tag-1-2 / EU-Tag-3-5. D2 bleibt für `soil_moisture`,
  `soil_temperature`, `updraft` und alle PL-Daten. Config-Slots
  umbenannt zu `SURFACE_PRIMARY/SECONDARY/FALLBACK_MODEL` +
  `PRESSURE_LEVEL_PRIMARY/FALLBACK_MODEL` + `BLH_MODEL` +
  `PRECIP_DENSE_MODEL` + `GUST_MERGE_MODELS`. Alte Slots als Aliase
  erhalten. Separate "Batch Wind"-Anfrage entfällt — CH1-Surface-Batch
  ist jetzt sowohl primäre Surface-Quelle als auch Multi-Gust-Anker.
- **Mai 2026** — Doku-Fix: ICON-D2 hat nur 48h (2d) Horizont via Open-Meteo,
  nicht 5d.
- **Mai 2026** — BLH-Lookup: ICON-BLH (D2/EU/Global) sind via Open-Meteo
  alle `null`. Einzige BLH-Quelle ist GFS.
- **Mai 2026** — `PRECIP_DENSE_MODEL` (vorher `PRECIP_MODEL`) als eigener
  Slot, default `meteoswiss_icon_ch2`. Vorher nutzte Precip-Dense
  `FALLBACK_MODEL` (EU, 13 km) — Hybrid-Filter war auf parametrisierter
  Konvektion wirkungslos.
- **Mai 2026** — Wind-Tag-Voting auf 3-Tier (CH1 → CH2 → EU). Vorher fiel
  Tag 2–5 direkt auf EU (13 km) zurück.
- **Apr 2026** — Multi-Modell-Gust-Merge eingeführt (max(D2, CH1, CH2)).
  Höhenkorrektur via Brasseur-Decay.
- **Apr 2026** — Bodenwind-vs-PL-Diskrepanz dokumentiert: Open-Meteo
  `wind_direction_10m` ist terrain-korrigiert via ICON Surface Scheme,
  PL-Wind ist freie Atmosphäre. Bodenwind (10m) ist maßgeblich für
  Windrichtungs-Check.
