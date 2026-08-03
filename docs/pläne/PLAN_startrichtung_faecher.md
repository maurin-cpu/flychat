# Plan: Wind-Fächer der Spots korrigieren (Optimal- vs. Rand-Sektoren)

**Status:** Entwurf, noch nicht begonnen
**Erstellt:** 2026-05-29
**Auslöser:** Fiesch zeigt auf der Hauptkarte einen riesigen Fächer (Ost→Süd→West),
wirkt wie "zeigt nach links", obwohl die Hauptstartrichtung sauber Süden ist.

---

## 1. Problem (verifiziert)

Die PGE-Quelldaten gewichten Startrichtungen mit **0 / 1 / 2**:

- `2` = optimale Hauptrichtung
- `1` = Randrichtung ("geht auch noch")
- `0` = gesperrt

Beispiel **Fiesch** (`data/_pge_ch_snapshot.json`, id 6604):

```
N:0  NE:0  E:1  SE:2  S:2  SW:2  W:1  NW:0
```

→ Hauptrichtung wäre **SO-S-SW** (135°, sauber Süd-zentriert).

Aber `scripts/build_pge_csv.py` Zeile 84 plättet **alles ≥1 auf 1**:

```python
sectors_bin = {k: (1 if v >= 1 else 0) for k, v in sectors_raw.items()}
```

→ In `fluggebiete_pge.csv` steht `E:1,SE:1,S:1,SW:1,W:1`
→ `spots.py` synthetisiert daraus `windrichtung = "O-SO-S-SW-W"`
→ Renderer zeichnet einen **225°-Fächer** von Ost (rechts) bis West (links).

Die Render-Mathematik (`map.js:getDirAngles`, `briefing.js:bfGetDirAngles`) ist
**korrekt** — der Fächer ist um 180° (Süd) zentriert. Das Problem ist allein die
**weggeworfene Gewichtung**.

### Tragweite (aus Snapshot gemessen)

- 565 PGE-Features gesamt
- **483** haben mind. einen `2`-Sektor (Optimal-Info vorhanden, aktuell verworfen)
- **88** Spots: Optimal-Fächer wäre schmaler als der Binär-Fächer (sichtbare Änderung)
- **12** Spots haben nur `1`-Sektoren (keine Verschmälerung möglich → bleiben wie sind)
- Ø Fächer binär: ~91° → Ø Fächer optimal: ~75°

---

## 2. Datenfluss (Ist-Zustand)

```
data/_pge_ch_snapshot.json  (0/1/2 Gewichtung)
        │  scripts/build_pge_csv.py  ← PLÄTTET 0/1/2 auf 0/1  ❌ (Verlust hier)
        ▼
data/fluggebiete_pge.csv  (wind_N..wind_NW als 0/1)
        │  spots.py:load_spots() → _sectors_to_windrichtung()
        ▼
windrichtung = "O-SO-S-SW-W"
        │
        ├── chat_engine.get_spots_geojson() → /api/spots → map.js (Karte)
        ├── briefing.js (Minimap)
        └── weather_context.py → _parse_wind_range() / _is_wind_in_range()  (SAFETY)
```

Wichtig: `windrichtung` speist **zwei** Konsumenten:
- **(A) Karte/Optik** — map.js + briefing.js
- **(B) Safety-Logik** — weather_context.py (LLM-Kontext + Startfenster-Bewertung)

---

## 3. Offene Entscheidung (vor Umsetzung klären)

**Soll der engere Optimal-Fächer auch die Safety-Bewertung (B) steuern, oder nur die Karte (A)?**

- **Variante "nur Karte" (risikoarm, empfohlen):**
  Safety nutzt weiter ALLE freigegebenen Sektoren (≥1, unverändert). Nur die Karte
  zeigt Kern (2) kräftig + Rand (1) blass. **Kein Spot wird strenger bewertet**,
  keine Re-Analyse nötig.

- **Variante "Karte + Safety" (konsequenter):**
  `windrichtung` = nur Optimal-Sektoren. 88 Spots werden an Randrichtungen strenger
  (mehr `conditional`). Erfordert Re-Analyse + Prüfung der Auswirkung auf
  Golden-Tests / Validierung.

> **TODO @user:** Variante wählen, bevor Schritt 4 begonnen wird.
> (Tendenz: "nur Karte" — löst das sichtbare Problem ohne Bewertungs-Risiko.)

---

## 4. Umsetzungsschritte

### Schritt 1 — CSV-Schema um Gewichtung erweitern
**Datei:** `scripts/build_pge_csv.py`

- Zeile 84: `sectors_bin` NICHT mehr auf 0/1 plätten — den Rohwert `0/1/2` behalten.
- `load_pge()`: `sectors` als `0/1/2` durchreichen (Variable ggf. umbenennen
  `sectors_bin` → `sectors_weighted`).
- Output: `wind_N..wind_NW` schreiben `0/1/2` statt `0/1`.
- Doc-Kommentar Kopf (Zeile 3-5) anpassen: "PGE 0/1/2 erhalten" statt "collapsed to 0/1".
- Sektor-Statistik am Ende (`sec_counts`) auf gewichtete Werte anpassen (optional).

**Rückwärtskompatibilität:** `2` ist truthy → bestehender `>= 1`-Code in `spots.py`
liest weiterhin korrekt. Kein Bruch für Konsumenten, die nur 0/1 erwarten.

### Schritt 2 — CSV neu generieren
```
python scripts/build_pge_csv.py
```
- Erzeugt `data/fluggebiete_pge.csv` mit 0/1/2-Werten.
- **Spot-Namen bleiben identisch** → keine Cache-Invalidierung, keine Test-Namen-Brüche.
- Diff prüfen: nur die `wind_*`-Spalten ändern sich (manche 1→2), sonst nichts.

### Schritt 3 — `spots.py` erweitern
**Datei:** `spots.py`

- `_sectors_to_windrichtung(sectors, min_strength=1)`: Parameter ergänzen (Schwelle
  `>= min_strength` statt fest `>= 1`).
- In `load_spots()` zwei Felder berechnen:
  - `windrichtung` = `_sectors_to_windrichtung(sectors, 1)` (alle, wie bisher → Safety bleibt stabil)
  - `windrichtung_optimal` = `_sectors_to_windrichtung(sectors, 2)` (Kern-Fächer)
  - Fallback: wenn `windrichtung_optimal` leer (kein 2-Sektor), = `windrichtung`.
- Beide Felder ins Spot-Dict aufnehmen.

### Schritt 4 — GeoJSON-Property ergänzen
**Datei:** `chat_engine.py` (`get_spots_geojson`, ~Zeile 535)

- `"windrichtung_optimal": spot.get("windrichtung_optimal")` zu `properties` hinzufügen.
- Ebenso in den weiteren `windrichtung`-Ausgaben prüfen, ob Optimal mitgegeben werden
  soll: `web.py:1831` (snap), `web.py:1968/3633` (api_weather → briefing-Minimap).

### Schritt 5 — Karten-Renderer: Kern + Rand zeichnen
**Dateien:** `static/js/map.js`, `static/js/briefing.js`

- `getDirAngles` / `bfGetDirAngles` bleiben unverändert (Mathematik ist korrekt).
- In `createSpotIcon` (map.js ~287) / `bfCreateSpotIcon` (briefing.js ~1913):
  - Kern-Fächer aus `windrichtung_optimal` → volle Deckkraft (`opacity 0.5` wie heute).
  - Rand-Fächer = `windrichtung` MINUS `windrichtung_optimal` → blass (`opacity ~0.18`) und/oder dünner.
  - Reihenfolge: erst Rand (blass) zeichnen, dann Kern drüber.
- Fallback: fehlt `windrichtung_optimal`, exakt heutiges Verhalten (nur `windrichtung`).

### Schritt 6 — (NUR falls Variante "Karte + Safety")
- `weather_context.py`: `_parse_wind_range(spot["windrichtung"])` ggf. auf
  `windrichtung_optimal` umstellen (Zeilen 429, 581, 1395, 1591).
- Re-Analyse aller Spots, Golden-Tests neu freezen, Validierung gegen
  `validation/xcontest/` prüfen.
- **Bei Variante "nur Karte": Schritt 6 entfällt komplett.**

---

## 5. Tests & Verifikation

- `python -m pytest tests/test_spots_data.py` — lädt CSV, prüft Spalten.
  - Prüfen: Test erwartet `ideal_wind_min`/`ideal_wind_max` — Felder, die im aktuellen
    PGE-Schema evtl. gar nicht existieren. **Test-Status vorab klären** (läuft er heute grün?).
- Neuer Mini-Test: `_sectors_to_windrichtung({E:1,SE:2,S:2,SW:2,W:1}, 2) == "SO-S-SW"`.
- Node-Smoke (ASCII-Raster wie in der Analyse) für Fiesch: Kern zeigt Süd.
- Manuell: App starten, Fiesch auf Karte ansehen → kräftiger Süd-Fächer, blasse
  Ost/West-Ränder.
- `git diff data/fluggebiete_pge.csv` — nur `wind_*`-Spalten geändert, Zeilenzahl gleich.

---

## 6. Risiken & Hinweise

- **Cache/Wetter-Archiv:** Spot-Namen bleiben gleich → `data/weather_archive/*.json`,
  `cost_testing/golden/*`, in-memory Caches bleiben gültig. Nur bei Variante
  "Karte + Safety" müssen Analysen neu laufen.
- **`fluggebiete_dhv.csv`** (Legacy, `USE_SPOT_CSV=dhv`) hat KEINE Gewichtung
  (Format `OSO-SSO`). Dort gibt es nichts zu verschmälern — `windrichtung_optimal`
  fällt auf `windrichtung` zurück. Kein Bruch.
- **Nicht anfassen:** `static/js/meteogram.js` hat eine vorbestehende, unabhängige
  uncommittete Änderung (CAPE-/Überentwicklungs-Feature) — gehört NICHT zu diesem Plan.
- Die Meteogramm-Windpfeile zeigen den TATSÄCHLICHEN Stundenwind, nicht die
  Gelände-Startrichtung — sind von diesem Plan nicht betroffen.

---

## 7. Betroffene Dateien (Übersicht)

| Datei | Änderung |
|---|---|
| `scripts/build_pge_csv.py` | 0/1/2 erhalten statt plätten |
| `data/fluggebiete_pge.csv` | neu generiert (wind_* = 0/1/2) |
| `spots.py` | `windrichtung_optimal` ableiten |
| `chat_engine.py` | GeoJSON-Property ergänzen |
| `web.py` | Optimal-Feld in weitere windrichtung-Ausgaben (Minimap) |
| `static/js/map.js` | Kern+Rand-Fächer zeichnen |
| `static/js/briefing.js` | Kern+Rand-Fächer zeichnen |
| `weather_context.py` | NUR bei Variante "Karte + Safety" |
| `tests/` | Mini-Test für Optimal-Synthese |

---

## 8. Nächster Schritt beim Fortsetzen

1. Variante entscheiden (Abschnitt 3).
2. `tests/test_spots_data.py` Ist-Status prüfen (grün/rot heute?).
3. Mit Schritt 1 (build_pge_csv.py) beginnen.
