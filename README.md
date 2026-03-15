# FlyChat - Thermik & Wetter Assistant

Dieses Projekt dient der Analyse und Vorhersage von Thermikbedingungen für Gleitschirmflieger.

## Projektstruktur

Um den Hauptordner (`/`) übersichtlich zu halten, folgen wir dieser Struktur:

### 📂 `tests/`
Hier befinden sich **dauerhafte Verifizierungs-Scripte** und automatisierte Tests.
- Wenn du eine neue Funktion implementierst und sicherstellen willst, dass sie auch in Zukunft funktioniert, erstelle hier einen Test.
- Beispiel: `verify_regtherm.py`, `test_api_analyze.py`.

### 📂 `debug_scripts/`
Hier kommen **temporäre Debug-Scripte, Logs und Dumps** hin.
- Scripte, die nur zur einmaligen Fehlersuche dienen oder Rohdaten-Dumps enthalten.
- Diese Dateien sollten regelmäßig aufgeräumt werden und gehören nicht in den Hauptordner.
- Beispiel: `debug_issues.py`, `log.txt`, `context_dump.txt`.

### 📂 `data/`
Cache und lokale Datenspeicher (z.B. Wetter-JSONs).

### 📂 `static/` & `templates/`
Frontend-Dateien für die Web-Oberfläche.

---

## Richtlinien für neue Dateien
1. **Keine neuen Scripte im Hauptordner**, es sei denn, sie sind zentrale Einstiegspunkte (wie `main.py`, `web.py`).
2. **Debug-Scripte** sofort in `debug_scripts/` erstellen oder dorthin verschieben.
3. **Tests** in `tests/` ablegen.
