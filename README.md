# Gleitcast - Thermik & Wetter Assistant

Dieses Projekt dient der Analyse und Vorhersage von Thermikbedingungen für Gleitschirmflieger.

## Projektstruktur

Um den Hauptordner übersichtlich zu halten, gilt:

### 📂 `tests/`
**Automatisierte Tests** (pytest) und dauerhafte Verifikationsskripte.
- Neue Funktionalität abgesichert hier testen, nicht im Root.
- Beispiele: `verify_regtherm.py`, `test_api_analyze.py`.

### 📂 `debug_scripts/`
**Manuelle Debug-Skripte**, Dateninspektion, Einmal-Checks, **kein** Produktions-Entry-Point.
- Übersicht: [debug_scripts/DEBUG_INVENTORY.md](debug_scripts/DEBUG_INVENTORY.md).
- Ausführung immer vom Projektroot: `python debug_scripts/inspect_data.py ...`
- Skripte nutzen `Path(__file__).parent.parent`, damit Imports auch aus diesem Ordner funktionieren.

### 📂 `docs/`
**Projektdokumentation** (z. B. Modellbeschreibungen), nicht der laufende Code.
- Thermik-Architektur: [docs/THERMIK_MODELL.md](docs/THERMIK_MODELL.md)

### 📂 `meteo_research/` & `marktresearch/`
Notizen und Recherche — getrennt vom Code.

### 📂 `scripts/`
Kleine Wartungs- oder Hilfsskripte (z. B. GeoJSON erzeugen), wenn sie nicht nur Debug sind.

### 📂 `data/`
Cache und lokale Datenspeicher (z. B. Wetter-JSONs).

### 📂 `static/` & `templates/`
Frontend für die Web-Oberfläche.

---

## Richtlinien für neue Dateien
1. **Keine** neuen Skripte oder Dumps im **Hauptordner** — außer zentrale Einstiegspunkte (`main.py`, `app.py`, `web.py`, `config.py`, …).
2. **Debug / manuelle Tests** → `debug_scripts/`.
3. **Pytest / Regression** → `tests/`.
4. **Längere Doku** → `docs/` oder `meteo_research/`, je nach Thema.
