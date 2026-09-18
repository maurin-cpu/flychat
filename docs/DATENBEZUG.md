# Datenbezug — Tarife, Verbrauch und Alternativen

> **Zweck:** Festhalten, *woher* die Wetterdaten kommen, was das kostet und
> welche Alternativen wie teuer wären. Ergänzt `WETTERMODELLE.md` (dort steht,
> *welches Modell* welche Grösse liefert — hier steht, *über welchen Weg*).
>
> Alle Zahlen unten sind **am 21.08.2026 gemessen**, nicht geschätzt.
> Wo etwas ungemessen ist, steht es ausdrücklich dabei.

## Stand heute

Sämtliche Wetterdaten kommen von **Open-Meteo**, über den bezahlten
Kunden-Endpunkt `customer-api.open-meteo.com`. Die Umschaltung passiert
automatisch in `config.py:29-44`: Ist `OPENMETEO_API_KEY` gesetzt, geht alles
über den Kunden-Endpunkt, sonst über den freien. Der Key liegt auf dem Server
in `/home/deploy/flychat/.env` (via systemd `EnvironmentFiles`).

Ausnahme: Das **Ensemble** (`convection.py:179`) läuft schon immer über
`ensemble-api.open-meteo.com` — der Kundenendpunkt liefert dort 404.

---

## 1. Wie viel wir verbrauchen

Open-Meteo zählt nicht Anfragen, sondern **gewichtete Calls**:

```
Gewicht = Orte × (Tage / 14) × (Variablen / 10)
```

Eine Anfrage über 705 Orte mit 80 Variablen zählt also wie ~1 200 Calls.

Mengengerüst (aus dem echten Punktaufbau: `spots.load_spots`,
`source_area.get_reference_points` / `get_all_regions` /
`get_precip_reference_points`): 494 Spots · 705 deduplizierte Spot-Punkte ·
29 Regionen · 203 Regions-RPs (davon 28 nur-Region) · 464 Niederschlags-RPs.

Alle **11** Batches aus `fetch_weather.py:1185-1483`, Serverstand
`FORECAST_DAYS=3` (`data/config_overrides.json`):

| Batch | Orte | Vars | Tage | Gewicht |
|---|---|---|---|---|
| Fallback EU | 705 | 80 | 3 | 1 209 |
| Thermal/PL D2 | 705 | 80 | 2 | 806 |
| CH2-Surface | 494 | 25 | 3 | 265 |
| CH1-Surface | 494 | 25 | 2 | 176 |
| Region-CH2 / Region-CH1 | 203 | 25 | 3 / 2 | 181 |
| Region-Thermal / Region-Fallback | 28 | 80 | 3 | 96 |
| GFS / Precip-Dense / Region-GFS | 464–494 | 2–3 | 3 | 61 |
| Synoptik / Föhn / Ensemble | | | | ~5 |
| **Summe pro Tageslauf** | | | | **~2 800** |

Gratis-Rahmen: **10 000/Tag · 5 000/Stunde · 600/Minute · 300 000/Monat.**

| | pro Tag | vom Tageslimit | pro Monat | vom Monatsbudget |
|---|---|---|---|---|
| Server (`FORECAST_DAYS=3`) | 2 798 | **28 %** | 84k | **28 %** |
| bei 5 Prognosetagen | 3 957 | 40 % | 119k | 40 % |

Es ist also Platz für **3,6 volle Läufe pro Tag**. Das Abo wird nicht wegen
der Menge bezahlt, sondern für die kommerzielle Lizenz und die
Verfügbarkeitszusage.

---

## 2. Liefert der Gratis-Zugang dieselben Daten? — Ja

Jeder produktive Abruf wurde einmal gegen **beide** Endpunkte gefahren und
Variable für Variable verglichen:

| Batch | angefragt | frei geliefert | Wertevergleich |
|---|---|---|---|
| CH1-Surface | 25 | 25 | identisch bis auf `et0` |
| Thermal/PL (D2) | 80 | 80 | identisch bis auf `et0` |
| Fallback (EU) | 80 | 80 | identisch bis auf `et0` |
| CH2-Surface | 25 | 25 | identisch bis auf `et0` |
| GFS / Precip-Dense | 3 / 2 | 3 / 2 | identisch |
| Synoptik-Kontext / -Raster | 1 / 3 | 1 / 3 | vollständig |
| Föhn-Indikatoren | 8 | 8 | vollständig |
| Stations-Backfill (`past_days=14`) | 2 | 2 | vollständig, 360 Werte |
| Ensemble ICON-CH2-EPS | 21 Member | 21 Member | **nur frei verfügbar** |

Drei Anmerkungen:

- **Einzige Abweichung: `et0_fao_evapotranspiration`**, konstant ±0.01 mm
  (Rundung auf einer abgeleiteten Grösse). Die Variable wird geholt und in
  `thermik_calculator.py:588` als Parameter durchgereicht, im Rechenweg aber
  **nie verwendet**.
- **Leere Felder sind Modellgrenzen, keine Tarifgrenze:** `cloud_base`,
  `boundary_layer_height`, `updraft` und die Niveaus 875/825/775/750 hPa
  kommen bei ICON-EU leer — auf **beiden** Endpunkten gleich (siehe
  `WETTERMODELLE.md`, deshalb kommt BLH von GFS).
- Das Ensemble läuft ohnehin schon gratis.

---

## 3. Lizenz — der einzige echte Blocker

Open-Meteo erlaubt den Gratis-Zugang **nur für nicht-kommerzielle Nutzung**:
„private oder gemeinnützige Websites/Apps **ohne Abos und ohne Werbung**".
Daten unter **CC-BY 4.0**, Quellenangabe erforderlich.

> **Rückkehr-Bedingung:** Sobald zahlende Nutzer, Werbung oder Verkauf
> dazukommen, muss `OPENMETEO_API_KEY` in `/home/deploy/flychat/.env` wieder
> aktiviert werden — **bevor** das live geht. Darum den Key beim Abschalten
> auskommentieren statt löschen.

Quellenangabe steht bisher nur im Briefing-Mail
(`templates/email/briefing.html:292`), nicht in der Web-App.

---

## 4. Kritisch am Gratis-Zugang: das Minutenlimit

Nicht das Tagesbudget ist eng (28 % ausgelastet), sondern die **600 Calls pro
Minute**. Gemessen mit den produktiven Parametersätzen:

| Konfiguration | Gewicht/Chunk | Ergebnis |
|---|---|---|
| 80 Orte / 3.5 s (heutige Produktion) | 229 | **429 ab dem 2. Chunk** |
| 80 Orte / 35 s | 229 | 429 (2 von 3) |
| **40 Orte / 15 s** | 114 | **4 von 4 sauber** |

Für einen Wechsel müssen also `API_CHUNK_SIZE` (80 → 40) und
`API_DELAY_BETWEEN_CALLS` (3.5 → 15) in `fetch_weather.py:25,32` angepasst
werden. Laufzeit dann ~27 min statt weniger Minuten — für den 06:00-Batch
irrelevant. Eleganter wäre eine Drosselung nach Gewicht (Ziel < 450/min):
Die leichten Batches (Gewicht 28–36/Chunk) dürften voll laufen, gedrosselt
würden nur D2 und EU → ~10 min.

Die 429-Behandlung existiert bereits aus der Gratis-Zeit
(`fetch_weather.py:176-215` Retry mit `Retry-After`, `_wait_for_api_ready()`
als Pre-Check, `DailyLimitExceeded` markiert den Cache als stale).

---

## 5. Alternative: Rohdaten direkt bei DWD / MeteoSchweiz

Beide Quellen sind frei zugänglich, ohne Schlüssel:

- **MeteoSchweiz OGD** — STAC-API auf `data.geo.admin.ch`, GRIB2,
  ICON-CH1-EPS (11 Member, 3-stündlich, 33 h) und ICON-CH2-EPS (21 Member,
  6-stündlich, 120 h).
- **DWD Open Data** — `opendata.dwd.de`, GRIB2 bzip2-gepackt, ICON-D2 /
  ICON-EU inklusive **Druckflächen**.
- **NOAA GFS** — NOMADS, mit serverseitigem Zuschneiden.

### 5.1 Gemessene Grössen

| | Grösse | Inhalt | Davon gebraucht |
|---|---|---|---|
| CH2 Bodendatei | 0.6 MB | 283 876 Gitterpunkte | 700 Punkte |
| CH2 Säulendatei | 45.4 MB | 80 Niveaus × 283 876 Punkte | 13 Niveaus × 700 Punkte = **0.04 %** |
| DWD D2/EU Druckfläche | 1.03 MB | 1 Niveau, 2.2 km, deckt CH ganz | 700 Punkte |
| DWD-Druckflächen komplett | **1.13 GB** | 1 176 Dateien | — |

> **Wichtigster Hebel:** MeteoSchweiz packt die **ganze** Luftsäule in eine
> Datei, der DWD schneidet **pro Druckniveau**. Für die Höhendaten also DWD
> nehmen — was flychat mit ICON-D2 ohnehin tut.

### 5.2 Volllauf, end-to-end gefahren

ICON-CH2-Bodenvariablen, Blöcke à 32, 16 parallele Downloads, jede Datei auf
GRIB-Kopf und `7777`-Ende geprüft, seriell dekodiert, sofort gelöscht:

| | Messung |
|---|---|
| verarbeitet | 5 888 Dateien, 3.29 GB |
| davon sauber | 5 777 — **111 Fehlschläge (1.9 %)** trotz einem Retry |
| Wanduhr | 25.5 min — **Download 24.8, Dekodieren 0.7** |
| Durchsatz | 2.1 MB/s, 3.8 Dateien/s |
| **Peak Plattenplatz** | **18 MB** |

### 5.3 Lehren aus dem Volllauf

1. **Speicherplatz ist kein Argument.** Mit Löschen im Betrieb 18 MB Spitze
   statt 22 GB. Die 60 GB im Vergleichsprojekt sind ein Aufräum-Artefakt:
   `meteoswiss/grib_loader.py:38` überspringt vorhandene Dateien und löscht
   nie. Dauerhaft bleiben nur die extrahierten Punktwerte — dort **19 MB für
   alle 29 Regionen**, Verhältnis geladen : behalten ≈ **1 : 1 200**.
2. **Rechenleistung ist irrelevant** — 7 ms je Datei. Eine frühere Schätzung
   von 15 min Dekodierzeit war um das Zwanzigfache zu hoch.
3. **Der Download ist der ganze Engpass**, und zwar **anfrage- statt
   volumengebunden**: 3.8 Dateien/s trotz 16 paralleler Verbindungen, weil je
   Datei ein neuer TLS-Handshake anfällt. Mit dauerhaften HTTP-Sessions wäre
   vermutlich ein Mehrfaches drin — **ungemessen**.
4. **Vor dem Download deduplizieren.** Die Blätter-Schleife liefert jedes Item
   rund **4×**. Real sind es **1 573 Dateien / ~0.9 GB** für die 13
   Bodenvariablen, nicht 6 292 / 3.3 GB.
5. **Das blosse Auflisten eines Laufs kostet 8 Minuten** — 983 Seiten,
   98 253 Einträge. Serverseitiges Filtern gibt es nicht: `forecast:variable`
   als Query-Parameter wird stillschweigend ignoriert.
6. **Nur ein Lauf ist gleichzeitig verfügbar, Frist 24 h** (`expires` im
   STAC-Item). Verpasst = endgültig weg, kein Netz darunter. Bei ~10 000
   Dateien/Tag und 1.9 % Ausfallquote sind das ~200 Nachholer täglich —
   innerhalb der Frist.
7. MeteoSchweiz liefert **unkomprimiert** (`.grib2`), der DWD `.grib2.bz2` —
   dort kommt ein Entpackschritt dazu.

**Realistischer Tageslauf** (dedupliziert, alle Modelle: CH2 1 573 + CH1 442 +
DWD-Druckflächen 1 176 + EU/GFS): ~10 000 Dateien, ~12 GB, beim gemessenen
Tempo **~45 min**, mit sauberen Sessions vermutlich 15–25 min. Gegenüber dem
Gratis-Weg über Open-Meteo (~27 min) also **kein Tempogewinn**.

Netzverkehr ~360 GB/Monat — bei Hetzner im Inklusivvolumen. Läuft auf der
bestehenden Maschine (2 CPU, 4 GB RAM, 21 GB frei), **sofern nach dem
Extrahieren gelöscht wird**.

### 5.4 Vollständigkeit: **kein 1:1-Ersatz**

Abgleich unserer 80 angefragten Grössen gegen das, was die Quellen wirklich
publizieren (ICON-CH2: 103 Variablen laut STAC; ICON-D2: 129 laut Verzeichnis):

| Klasse | Anteil | Beispiele |
|---|---|---|
| **direkt vorhanden** | ~55 % | `temperature_2m`←T_2M · `wind_gusts_10m`←VMAX_10M · `cloud_cover_*`←CLCT/CLCL/CLCM/CLCH · `cape`←CAPE_ML · `convective_inhibition`←CIN_ML · `pressure_msl`←PMSL · `surface_pressure`←PS · `snow_depth`←H_SNOW · `lifted_index`←SLI · alle 52 Druckflächen←DWD `t`/`u`/`v`/`fi` |
| **einfach ableitbar** | ~15 % | `wind_speed/direction_10m`←U/V · `relative_humidity_2m`←T_2M+TD_2M · `vapour_pressure_deficit` · `geopotential_height`←fi/9.81 |
| **aufsummiert → entkumulieren** | ~10 % | `precipitation`←TOT_PREC · `rain`←RAIN_GSP · `shortwave/direct/diffuse_radiation`←ASWDIR_S+ASWDIFD_S · `sunshine_duration`←DURSUN |
| **fehlt, Nachbau nötig** | **~20 %** | siehe unten |

Die vier Lücken — **drei davon tragend**:

1. **`weather_code` — nicht vorhanden.** MeteoSchweiz liefert kein
   WMO-Wettercode-Feld (der DWD hat `ww`, MeteoSchweiz nicht); Open-Meteo
   klassifiziert selbst. Bei uns ist 95/96/99 das **Gewittersignal**
   (`config.py:447,602`) und die einzige Grösse, über die
   `convection.py:193` die Ensemble-Wahrscheinlichkeit rechnet.
2. **`precipitation_probability` — im deterministischen Lauf nicht
   vorhanden.** Open-Meteo leitet sie aus dem Ensemble ab. Selbst rechnen
   hiesse: alle **21 Member** laden statt nur den Kontrolllauf — für diese
   eine Grösse das 21-Fache an Daten.
3. **`cloud_base` — kein direktes Feld.** HBAS_SC und CEILING bedeuten etwas
   anderes. Der Wert steuert die Basis-Bewertung
   (`engine/decision_engine.py:664`).
4. `et0_fao_evapotranspiration` (reine Formel, ohnehin ungenutzt) und
   `updraft` (Definition bei Open-Meteo unklar; DWD hat `w` / `w_ctmax`).

> **Konsequenz:** Ein Umstieg ist kein Umstecken der Datenquelle, sondern der
> Nachbau fremder Rechenwege. Das Entkumulieren der Summenwerte ist zusätzlich
> die klassische stille Fehlerquelle — die Zahlen sehen plausibel aus und sind
> trotzdem falsch. **Ein Parallelbetrieb mit Wert-für-Wert-Vergleich gegen
> Open-Meteo ist zwingend, nicht optional.**

**Gegenwert:** Mit den Rohdaten bekämen wir alle 21 Ensemble-Member für
**jede** Variable, nicht nur für `weather_code` — mehr, als Open-Meteo heute
liefert. Gerade beim Gewitter, wo die Unsicherheit am grössten ist.

### 5.5 Startpunkt für einen Umbau

`C:\Users\user\Projekte\wettermodell_vergleich` — dort läuft der Direktbezug
bereits: STAC-Client, paralleler GRIB2-Download, bilineare Interpolation auf
Regionspunkte, ~2 000 Zeilen Python (`meteoswiss/stac_client.py`,
`grib_loader.py`, `interpolation.py`, `sources/meteoswiss.py`), Stack
`cfgrib` / `xarray` / `ecmwflibs`.

Zu ergänzen wären: Löschen nach dem Extrahieren · Deduplizieren vor dem
Download · DWD-Zweig für die Druckflächen · Abbildung auf unsere
Variablennamen · Nachbau der fehlenden 20 % · Nachhol-Logik innerhalb der
24-Stunden-Frist.

---

## 6. Entscheidungslage

| Weg | Kosten | Aufwand | Vollständigkeit |
|---|---|---|---|
| **Abo Open-Meteo** (heute) | ~350 CHF/Jahr | — | Referenz |
| **Gratis Open-Meteo** | 0 | 1 Konfig-Änderung (Chunk-Grösse) | **1:1 gemessen** |
| **Direktbezug DWD/MeteoSchweiz** | 0 | Wochen + Parallelbetrieb | ~80 %, Rest Nachbau |
| Open-Meteo selbst hosten | ~7–15 €/Mt. zusätzliche Maschine | mittel | 1:1 |

Solange Wingcast nicht kommerziell ist, ist der **Gratis-Zugang** die klare
Wahl. Der **Direktbezug** ist die Antwort für den Fall, dass Wingcast Geld
verdient und der Gratis-Zugang wegfällt — dann als Projekt mit Parallelbetrieb,
nicht als Umstellung über Nacht.
