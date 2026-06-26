# Wingcast Smoke Tests

End-to-End Smoke Tests stellen sicher, dass die wichtigsten Frontend-Flows der Wingcast-App tatsächlich funktionieren — nicht nur die Backend-Endpoints, sondern der vollständige Pfad **Browser → Map-Klick → Overlay → SVG-Render**.

Die Tests laufen mit [Playwright](https://playwright.dev/python/) (Chromium, headless) gegen einen lokal laufenden Flask-Server.

---

## Warum diese Tests existieren

Im April 2026 ist ein subtiler Bug aufgetreten: Das Region-Meteogramm wurde nicht mehr gerendert, weil `openRegionOverlay()` einen Stub-Eintrag in `meteogramCache[rid] = { regionName: "..." }` schrieb, und `loadRegionMeteogram()` diesen truthy-Stub mit `if (meteogramCache[rid])` als „Cache-Hit" interpretierte. Anschliessend wurde `renderRegionMeteogram` mit `wxData = undefined` aufgerufen und stürzte beim Zugriff auf `wxData.dates` ab — **still und unsichtbar in der Browser-Konsole**.

Das Backend war komplett gesund (200, korrekte JSON-Daten), `python -m pytest tests/` grün — und trotzdem war die Seite kaputt. Klassische Lücke: Backend-Tests prüfen Daten, aber niemand prüfte, ob das Frontend daraus tatsächlich eine sichtbare Visualisierung baut.

Die Smoke-Tests schliessen genau diese Lücke. Sie sind das automatisierte Pendant zu „kurz die App öffnen und auf alles klicken, was klickbar ist".

---

## Was die Tests abdecken

Die Tests befinden sich in `tests/test_e2e_meteogram.py` und decken drei Szenarien ab:

### 1. `test_spot_meteogram_renders`

**Ziel:** Sicherstellen, dass das Spot-Meteogramm auf der Hauptseite tatsächlich gerendert wird.

**Ablauf:**
1. Browser öffnet `http://127.0.0.1:5000/`
2. Wartet, bis Leaflet-Marker im DOM auftauchen (`.leaflet-marker-icon`)
3. Klickt den ersten sichtbaren Marker
4. Wartet, bis das Overlay sichtbar ist (`.meteogram-overlay.visible`)
5. Wartet, bis darin ein `<svg>` gerendert ist
6. Behauptet: mindestens ein SVG-Element existiert

**Was es fängt:** Renderfehler in `meteogram.js`, kaputte API-Responses für `/api/weather/<spot>` oder `/api/altitude-wind/<spot>`, fehlende Day-Tabs, Marker-Click-Handler-Bugs.

### 2. `test_region_meteogram_renders`

**Ziel:** Sicherstellen, dass das Region-Meteogramm auf der Regionen-Seite tatsächlich gerendert wird. Genau dieser Test wäre beim Cache-Bug rot geworden.

**Ablauf:**
1. Browser öffnet `http://127.0.0.1:5000/regionen` mit `wait_until='networkidle'`
2. Wartet, bis Leaflet-Polygone im DOM existieren (`#regionMap svg path`)
3. Injiziert ein Datum via `window.setRegionDate('YYYY-MM-DD')` — normalerweise käme das aus der InstantDB-Subscription, aber im Testumfeld haben wir keine Cloud-Verbindung
4. Findet das erste interaktive Polygon (`path.leaflet-interactive`), berechnet dessen Bounding-Box-Mittelpunkt
5. Klickt mit `page.mouse.click(cx, cy)` per Maus-Koordinate (nicht `locator.click()`, weil Playwrights interner Hit-Test bei nicht-rechteckigen Polygonen fehlschlägt)
6. Wartet auf `#regionOverlay.visible`
7. Wartet auf `#regionMeteogramChart svg`
8. Behauptet: mindestens ein SVG-Element existiert

**Was es fängt:** Cache-Bugs wie der Region-Meteogramm-Bug, kaputte `/api/region-weather/<rid>` und `/api/region-altitude-wind/<rid>` Endpoints, JS-Errors in `region-map.js` oder `renderRegionMeteogram()`, fehlende DOM-Elemente, kaputte Day-Tab-Logik.

### 3. `test_no_console_errors`

**Ziel:** Während der ersten beiden Tests dürfen keine JavaScript-Fehler in der Browser-Konsole auftauchen.

**Ablauf:**
1. Beim Start wird ein Listener auf `console.error` und `pageerror` Events gehängt
2. Während Test 1 + 2 werden alle Fehler in eine Liste gesammelt
3. Am Ende wird behauptet: die Liste ist leer

**Was es fängt:** Stille TypeErrors, ReferenceErrors, unhandled Promise Rejections, deprecation warnings, fehlende Globals, die der Backend-Test gar nicht sehen kann. Genau diese Klasse von Bugs hatte uns vorher kalt erwischt.

---

## Wie die Tests laufen

### Voraussetzungen

```bash
# Python-Dependencies
pip install playwright

# Browser einmalig herunterladen (~108 MB Chromium)
python -m playwright install chromium
```

### Server starten

In einem separaten Terminal:

```bash
python main.py
```

Der Test prüft als allererstes mit einem GET auf `/api/regionen`, ob der Server erreichbar ist. Wenn nicht, bricht er sofort mit Exit-Code 2 ab und gibt eine klare Anweisung aus.

### Tests ausführen

Direkt:

```bash
python tests/test_e2e_meteogram.py
```

Oder über pytest:

```bash
python -m pytest tests/test_e2e_meteogram.py -v
```

### Output

```
Wingcast E2E Smoke Tests
============================================================
Server erreichbar unter http://127.0.0.1:5000

  [PASS] test_spot_meteogram_renders  — SVG gerendert (1 Element(e))
  [PASS] test_region_meteogram_renders  — SVG gerendert (1 Element(e))
  [PASS] test_no_console_errors  — keine Errors

============================================================
Ergebnis: 3/3 Tests bestanden
```

### Exit-Codes

- `0` — alle Tests grün
- `1` — mindestens ein Test rot
- `2` — Server nicht erreichbar oder Playwright fehlt

---

## Was die Tests bewusst NICHT abdecken

- **Datenkorrektheit**: Die Tests prüfen, ob ein SVG entsteht — nicht, ob die Wind-Werte stimmen oder die Thermik-Berechnung korrekt ist. Dafür existieren die Backend-Tests in `tests/`.
- **Mehrere Spots**: Es wird nur der erste sichtbare Marker getestet, nicht alle 28+ Spots.
- **Mehrere Tage**: Es wird nur der initial gerenderte Day-Tab getestet, kein Tab-Wechsel.
- **Visuelle Regression**: Es wird nicht verglichen, ob das SVG genau gleich aussieht wie gestern. Pixel-Diffing wäre möglich, ist aber für ein Smoke-Test-Setup overkill.
- **Backend-Errors mit Status 200**: Wenn die API ein leeres `{}` zurückgibt, wird der Test rot (kein SVG), aber er zeigt nicht direkt warum.
- **Production-Deploy**: Die Tests laufen ausschliesslich gegen `127.0.0.1:5000`, nicht gegen die produktive Vercel-Umgebung.

---

## Komplementäre Schutzschicht: Error-Monitor

Ergänzend zum Test-Setup läuft im Browser permanent der **Error-Monitor** (`static/js/error-monitor.js`), der via `base.html` als allererstes JS in jeder Seite geladen wird.

Aufgabe: Uncaught JavaScript-Errors und unhandled Promise-Rejections werden NICHT mehr still in der Browser-Konsole versanden, sondern als roter Banner oben am Bildschirm angezeigt — auch dem normalen User, ohne DevTools.

So fangen wir auch im echten Betrieb Fehler, die in der lokalen Test-Umgebung nicht reproduzierbar sind (z.B. Race Conditions mit InstantDB, Browser-spezifische Bugs, kaputte Cloud-Daten).

Die zwei Schichten zusammen:

| Schicht | Was sie macht | Wann sie greift |
| ------- | ------------- | --------------- |
| Smoke-Tests (Playwright) | Klickt automatisch durch und prüft DOM | Vor jedem Push / vor jedem Deploy |
| Error-Monitor (Banner) | Zeigt jeden uncaught JS-Error sichtbar | Im echten Browser, jederzeit |

---

## Ein konkreter Fang

Beim ersten Lauf hat `test_no_console_errors` sofort einen pre-existenten Bug aufgedeckt:

```
TypeError: window.map.invalidateSize is not a function
    at http://127.0.0.1:5000/:783:40
```

**Root Cause:** In `templates/index.html` existiert `<div id="map">`. Der Browser erzeugt daraufhin automatisch einen HTML implicit global `window.map`, der auf das DIV-Element zeigt. Parallel dazu deklariert `static/js/map.js` die Leaflet-Map-Instanz nur lokal innerhalb einer IIFE (`var map;`), ohne sie an `window` zu exportieren. Die sechs `if (window.map) window.map.invalidateSize()` Aufrufe in den Sidebar-Resize-Handlern griffen also auf das DIV-Element zu — das hat keine `invalidateSize()` Methode → TypeError. Der `if (window.map)` Guard greift, weil das DIV truthy ist.

**Fix:** `initMap()` in `map.js` exportiert die Leaflet-Instanz explizit als `window.wingcastMap`, und alle sechs Call-Sites in `index.html` verwenden jetzt diesen kollisionsfreien Namen.

Solche Bugs sind ohne automatisches Klicken praktisch unsichtbar, weil sie nur bei Layout-Events (Drag-Resize, Touch, Window-Load) auftreten und still in der Browser-Konsole sterben. Nach dem Fix: 3/3 Tests grün.

Das ist genau die Klasse von Bug, für die diese Test-Infrastruktur existiert.

---

## Wann die Tests laufen sollten

- **Vor jedem Commit**, der Frontend-JS oder Templates anfasst
- **Vor jedem Deploy**, idealerweise als CI-Step
- **Nach jedem Refactoring** in `region-map.js`, `map.js`, `meteogram.js`
- **Bei jeder Änderung an `instantdb_client.py`**, falls die Subscription-Schnittstelle berührt wird

Die Tests brauchen rund 5–10 Sekunden für alle drei Szenarien plus Browser-Startup. Schnell genug, um sie als Pre-Commit-Hook zu nutzen.

---

## Erweitern

Neue Smoke-Tests dem gleichen Muster folgend in `tests/test_e2e_meteogram.py` hinzufügen:

```python
def test_new_thing(page: Page) -> tuple[bool, str]:
    try:
        page.goto(BASE_URL + "/some-page", timeout=NAV_TIMEOUT_MS)
        page.wait_for_selector("#some-element", timeout=RENDER_TIMEOUT_MS)
        # ... Assertions ...
        return True, "details"
    except PlaywrightTimeout as e:
        return False, f"Timeout: {e}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"
```

Dann in `main()` aufrufen und in `results` einfügen.

Sinnvolle Kandidaten für weitere Tests:
- Day-Tab-Wechsel im Spot-Meteogramm
- Chat-Eingabe und Antwort-Render
- LLM-Analyse-Button (mit gemockter Backend-Response)
- Karte: Marker-Hover, Region-Hover-Tooltip
