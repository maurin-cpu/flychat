# Debug Scripts Inventory

Dieses Verzeichnis enthält **Ad-hoc-Debug-Skripte**, **manuelle Tests** und Hilfen zur Dateninspektion.  
**Nicht** hier: produktiver App-Code (`main.py`, `web.py`, … im Projektroot) und **pytest**-Tests unter `tests/`.

> [!IMPORTANT]
> **Regel für neue Skripte**: Zuerst prüfen, ob `inspect_data.py` oder `debug_thermals_refined.py` reicht. Sonst neues Skript **direkt hier** anlegen — nicht im Hauptordner.

## Kurzüberblick (weitere Skripte)

| Datei | Zweck |
|--------|--------|
| `refresh_cache.py` | Wetter-Cache neu ziehen (`fetch_all_spots`), optional langsameres API-Tempo |
| `test_all.py`, `test_fuerenalp*.py` | Manuelle Fetch-/API-Checks (Fürenalp, Balderen) |
| `debug_balderen*.py` | Einmalige Balderen-Dumps aus `data/wetterdaten.json` |
| `debug_evening_decay.py` | Thermik-Diagnose (Abendverhalten) |
| `debug_json.py` | Schneller Check von `wetterdaten.json` (z. B. Fürenalp) |
| `debug_om.py` | Direktaufruf Open-Meteo-API / Referenzpunkte |

## Available Tools

### 1. `inspect_data.py`
A flexible CLI tool to query `data/wetterdaten.json`.
- **Usage**: `python debug_scripts/inspect_data.py --spot <NAME> --date <YYYY-MM-DD> --type <wind|cloud|thermal|radiation|all>`
- **Example**: `python debug_scripts/inspect_data.py --spot Balderen --date 2026-03-15 --type wind`
- **Features**: Filter by spot and date, list available spots, see specific weather parameters.

### 2. `debug_thermals_refined.py`
Detailed analysis of the thermal profile calculation for a specific spot and day.
- **Usage**: `python debug_scripts/debug_thermals_refined.py --spot <NAME> --date <YYYY-MM-DD>`
- **Features**: Shows climb rates, thermal tops, ratings, and diagnostic values like heat flux and sun index.

### 3. `debug_foehn.py`
Tests the Foehn indicator logic.
- **Usage**: `python debug_scripts/debug_foehn.py`

### 4. `debug_json_struct.py`
A simple check for the structure of `wetterdaten.json` (kept for quick connectivity tests).

---

## Richtlinien für neue Skripte
- **Projektwurzel**: `sys.path.insert(0, str(Path(__file__).resolve().parent.parent))` — nicht `os.getcwd()`, damit es aus jedem Arbeitsverzeichnis läuft.
- **Namen**: sprechend (`debug_foehn_station.py`), nicht `debug1.py`.
- **Temporäres**: nach der Session löschen oder sinnvoll in `inspect_data.py` / `debug_thermals_refined.py` integrieren.
