# Plan: OGN_validation — Real-Flug-Validierung über OpenGliderNetwork

**Status:** Planung / Konzept. Implementierung NICHT gestartet.
**Erstellt:** 2026-06-14
**Branch:** `main` (Single-Branch-Workflow)

**Wiederaufnahme (HIER starten):**
1. Diese Datei lesen. Der **Abschnitt „Abgrenzung" ist die wichtigste Vorgabe** und darf
   NICHT aufgeweicht werden: OGN_validation ist NICHT xcontest_validation und wird nicht
   damit verglichen/vermischt.
2. Es ist noch **kein Code geschrieben**. Es existiert weder `ogn_collector.py` noch
   `data/ogn_tracks.db` noch ein Ordner `ogn_validation/`.
3. Einstieg ist **Phase 0 (Adoptions-Check)** — billig, entscheidet erst, ob der Rest
   überhaupt Sinn hat. Keine DB-Architektur committen, bevor das Signal empirisch belegt
   ist (Projekt-Prinzip „erst belegen, dann lösen").
4. Offene Entscheidungen stehen unter „Offene Entscheidungen" — die sind bewusst noch
   NICHT getroffen, nicht raten.

---

## Abgrenzung — warum OGN_validation ≠ xcontest_validation

Das sind **zwei verschiedene Beweisarten**. Sie speisen dasselbe Ziel (Kalibrierung der
Region-/Spot-Ratings), aber als **eigenständige, nicht vergleichbare Evidenz**. Sie dürfen
nicht in dasselbe Schema, dieselbe Tabelle oder dasselbe „confirm/false-positive"-Urteil
gemischt werden.

| | **xcontest_validation** | **OGN_validation** |
|---|---|---|
| Beobachtungseinheit | *Deklarierte Rekord-Leistung* (Flug ≥ ~40 km, hochgeladen) | *Roh-Telemetrie* eines Tracker-Geräts (jeder Flug, der gesendet wird) |
| Was es misst | „An diesem Spot wurde eine große XC-Strecke geflogen" | „Ein Gerät war hier in der Luft — wie lange, wie hoch, welche Steigwerte" |
| Erfasst auch | nein: nur die guten/langen Flüge | ja: Soaring, kurze Hops, Sledrides, Top-Landungen |
| Bias-Achse | Upload-Motivation + Distanz-Attraktivität der Topografie | **Geräte-Adoption** (FANET/FLARM) — ganz andere Verzerrung |
| Inferenz bei Anwesenheit | starke Untergrenze auf „Bedingungen waren XC-tauglich" | direkter Messwert des *tatsächlichen Flugs* (Airtime/Höhe/Steigen) |
| Inferenz bei Absenz | **uninformativ** | **uninformativ** (anderer Grund: kein Tracker getragen) |

**Konsequenz für die Architektur:**
- Eigener Ordner `flychat/ogn_validation/` (parallel zu, aber getrennt von
  `xcontest_validation/`).
- Eigenes DB-Schema, eigene CSV-Spaltenlogik.
- Eine Querverbindung der beiden ist NUR auf der **Analyse-/Lese-Ebene** erlaubt
  („XContest sagt 0, OGN sagt 5 Gleitschirm-Sessions à 2 h → erzählt eine andere
  Geschichte"). Niemals auf Daten-/Schema-Ebene gemerged.

**Gemeinsam bleibt nur das eine Prinzip:** Aus *Absenz* wird kein Urteil abgeleitet. Nur
*Anwesenheit* ist aussagekräftig — bei beiden, aber aus unterschiedlichen Gründen.

---

## Grundvoraussetzung: OGN ist ein Live-Stream, keine History-API

OGN hält **kein abfragbares Archiv**. Daten kommen aus einem kontinuierlichen
APRS-TCP-Stream (`aprs.glidernet.org`), auf dem man **dauerhaft verbunden** bleiben muss.
Nicht mitgeschnitten = für immer weg. Daraus folgt: **dauerhaft laufender Collector-Daemon**
(eigener systemd-Service), KEIN Cron-Pull. „Regelmäßig" betrifft nur die tägliche
*Aggregation*, nicht das Einsammeln.

Gleitschirm ist über das **Aircraft-Type-Feld** unterscheidbar (FANET Code 1 / FLARM 7),
Delta (FANET 2 / FLARM 6) und Segelflug (FANET 4 / FLARM 1) ebenso. Der Typ ist
**selbstdeklariert** (Gerätekonfig) — für FANET-Instrumente (Skytraxx/XCTracer/Syride =
genau die XC-Gleitschirm-Zielgruppe) i. d. R. korrekt; „unknown" (0) ist eine reale
Restklasse, die weder als Gleitschirm gezählt noch sicher ausgeschlossen werden kann.

---

## Architektur (Ziel-Zustand nach Phase 2)

```
aprs.glidernet.org  ──APRS-TCP (24/7)──►  ogn-collector.service   (NEU, eigener Daemon)
                                          ogn_collector.py
                                          - python-ogn-client
                                          - Server-Filter: BBox + Range
                                          - alle aircraft_type speichern,
                                            Gleitschirm markiert
                                          - no-track-/stealth-Flag respektieren
                                          - Auto-Reconnect
                                                   │ INSERT roh
                                                   ▼
                                          data/ogn_tracks.db (SQLite, WAL,
                                          Klassen-Muster wie station_observations.py)
                                            • beacons  (Rohpunkte, hochvolumig)
                                            • flights  (aggregierte Sessions)
                                                   │ täglich (Hook in scheduler.py)
                                                   ▼
                                          ogn_sessions.py
                                          - Beacons→Flüge (Gap-Split)
                                          - Startpunkt→Spot/Region (shapely, spots.py)
                                          - max Höhe / Höhe-AGL / Airtime
                                          - Roh-Beacons prunen (> Retention)
                                                   │
                                                   ▼
                                          ogn_validation/  (eigener Ordner)
                                          ogn_validation.py
                                          - pro Tag: flights × Region/Spot-Rating
                                          - Präsenz-Signal, EIGENES Schema
                                          - getrennt von xcontest_validation/
```

### Bausteine

**1. `ogn_collector.py` — Daemon (`ogn-collector.service`)**
- `python-ogn-client` (`ogn.client.AprsClient` + `parse`).
- **Server-seitiger APRS-Filter** (BBox + Range) → Volumen runter, bevor es ankommt.
- Speichert **alle** `aircraft_type` (Gleitschirm markiert), damit Delta/Segelflug als
  Vergleichsbasis vorhanden sind.
- Respektiert No-Track-/Stealth-Flag (ethisch/rechtlich, wenn später produktiv).
- Auto-Reconnect bei Stream-Abbruch (sonst Datenloch).
- systemd-Unit nach Vorbild `wingcast.service`, aber **bewusst entkoppelt** vom Webserver:
  `Restart=always`, `RestartSec=10`.

**2. `data/ogn_tracks.db` — SQLite, euer Klassen-Muster (`_connect()`, WAL, `data/*.db`)**
- `beacons`: `device_id, ts, lat, lon, alt_m, climb_rate, aircraft_type, receiver`.
- `flights`: `device_id, date, launch_lat, launch_lon, launch_spot_id, region_id,
  takeoff_ts, landing_ts, duration_min, max_alt_m, max_height_agl_m, aircraft_type`.
- Retention: `beacons` nach Roll-up prunen (Schwelle offen, s.u.); `flights` dauerhaft.

**3. `ogn_sessions.py` — täglicher Roll-up (Hook in `scheduler.py`)**
- Beacons pro `device_id` zu Flügen gruppieren (Split bei Zeit-Gap, Schwelle offen).
- Startpunkt → Spot/Region via `shapely` + bestehende Region-Geometrie/`spots.py`.
- Höhe-AGL braucht Terrain-Lookup (Quelle offen — evtl. vorhandenes Spot-Terrain, sonst SRTM).

**4. `ogn_validation/` + `ogn_validation.py` — der eigentliche Zweck**
- Eigener Ordner, eigenes Schema (NICHT das von xcontest_validation).
- Pro Tag: `flights` × Region/Spot-Rating → Präsenz-Signal
  („Spot X: 6 Gleitschirm-Starts, Σ 9 h Airtime, max +800 m überhöht" gegen Rating).
- Trifft direkt die False-Positive-Jagd (`not_safe`, aber es wurde nachweislich geflogen).

---

## Phasen

### Phase 0 — Adoptions-Check (zuerst, billig, Gate für alles Weitere)
- Nur Collector + `beacons`-Tabelle. 1–2 Wochen laufen lassen.
- Auszählen: **wie viele *Gleitschirm*-Spuren (FANET) an euren Top-Spots?**
- **Entscheidungs-Gate:** Genug Signal → Phase 1. Nur Segelflug-Rauschen → Stopp,
  Erkenntnis dokumentieren, kein Weiterbau.

### Phase 1 — Sessionizer + Spot/Region-Mapping
- `ogn_sessions.py`, `flights`-Tabelle, Retention/Pruning.

### Phase 2 — Validation-Layer
- `ogn_validation/`-Ordner + `ogn_validation.py`, eigenes Korpus.
- Optional: Lese-seitiger Quervergleich zu xcontest_validation (NIE Schema-Merge).

---

## Offene Entscheidungen (NICHT geraten — vor Phase 1 klären)
1. **Geografischer Scope:** ganze CH oder nur Zentralschweiz/eure Spot-Regionen?
2. **Retention Rohpunkte:** wie lange `beacons` halten (7 / 14 / 30 Tage)?
3. **Gap-Schwelle Sessionizing:** ab welcher Beacon-Lücke gilt ein Flug als beendet?
4. **Terrain-/AGL-Quelle:** vorhandenes Spot-Terrain wiederverwendbar oder SRTM nachrüsten?
5. **Ressourcen:** der Host hat knappen RAM (2 GB Swap nachgerüstet). Collector + SQLite
   sind leicht, aber Beacon-Volumen wächst — Pruning-Policy früh festlegen.
6. **No-Track-Policy:** intern (nur Validierung) reicht Respektieren des Flags; bei späterer
   Produktiv-/Public-Nutzung rechtliche Lage prüfen.

---

## Touch-Points (neu anzulegen, noch nichts davon existiert)
- `ogn_collector.py` — Daemon
- `ogn-collector.service` — systemd-Unit (entkoppelt von wingcast.service)
- `data/ogn_tracks.db` — SQLite (Klassen-Wrapper im Stil `station_observations.py`)
- `ogn_sessions.py` — Roll-up, Hook in `scheduler.py`
- `ogn_validation/` — eigener Ordner (README + SCHEMA + tägliche Outputs), getrennt von
  `xcontest_validation/`
- `requirements.txt` — `ogn-client` ergänzen
