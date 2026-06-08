"""
Wingcast E2E Smoke Tests
========================

Prüft, ob die Meteogramme auf der Haupt-Seite (/) und der Regionen-Seite (/regionen)
tatsächlich gerendert werden, indem ein echter Chromium-Browser die Seite lädt und
klickt wie ein User.

Was die Tests abdecken:
1. test_spot_meteogram_renders:       Klicke ersten Spot → erwarte SVG im Overlay
2. test_region_meteogram_renders:     Klicke erste Region → erwarte SVG im Overlay
3. test_no_console_errors:            Während beider Klicks keine JS-Console-Errors

Voraussetzung:
- Flask-Server läuft auf http://127.0.0.1:5000 (manuell: `python main.py` in
  separatem Terminal starten)
- Playwright + Chromium installiert:
    pip install playwright
    python -m playwright install chromium

Ausführen:
    python -m pytest tests/test_e2e_meteogram.py -v
    # oder direkt:
    python tests/test_e2e_meteogram.py

Exit-Code 0 = alle Tests grün, ≠0 = mindestens ein Test fehlgeschlagen.
"""
from __future__ import annotations

import sys
import time
from urllib.request import urlopen
from urllib.error import URLError

try:
    from playwright.sync_api import sync_playwright, Page, TimeoutError as PlaywrightTimeout
except ImportError:
    print("FEHLER: playwright nicht installiert.")
    print("  pip install playwright && python -m playwright install chromium")
    sys.exit(2)

BASE_URL = "http://127.0.0.1:5000"
NAV_TIMEOUT_MS = 15_000
RENDER_TIMEOUT_MS = 15_000


# ============================================================================
# Helpers
# ============================================================================

def check_server_up() -> bool:
    """Quick liveness check — fail fast wenn Flask nicht läuft."""
    try:
        with urlopen(BASE_URL + "/api/regionen", timeout=3) as resp:
            return resp.status == 200
    except (URLError, OSError):
        return False


def collect_console_errors(page: Page) -> list:
    """Attach listener that captures all console errors + pageerrors."""
    errors: list[str] = []

    def on_console(msg):
        if msg.type == "error":
            errors.append(f"console.error: {msg.text}")

    def on_pageerror(exc):
        errors.append(f"pageerror: {exc}")

    page.on("console", on_console)
    page.on("pageerror", on_pageerror)
    return errors


def log(ok: bool, name: str, detail: str = "") -> None:
    marker = "PASS" if ok else "FAIL"
    print(f"  [{marker}] {name}" + (f"  — {detail}" if detail else ""))


# ============================================================================
# Test Functions
# ============================================================================

def test_spot_meteogram_renders(page: Page) -> tuple[bool, str]:
    """Öffnet /, klickt ersten Spot-Marker, erwartet <svg> im Overlay."""
    try:
        page.goto(BASE_URL + "/", timeout=NAV_TIMEOUT_MS)
        # Leaflet-Karte + Marker laden
        page.wait_for_selector(".leaflet-marker-icon", timeout=NAV_TIMEOUT_MS)
        # Ersten Marker klicken (der meistens sichtbar ist)
        markers = page.locator(".leaflet-marker-icon")
        count = markers.count()
        if count == 0:
            return False, "Keine Leaflet-Marker gefunden"
        markers.first.click()
        # Overlay wird sichtbar
        page.wait_for_selector(".meteogram-overlay.visible", timeout=RENDER_TIMEOUT_MS)
        # SVG im Chart-Container
        page.wait_for_selector(".meteogram-overlay.visible svg", timeout=RENDER_TIMEOUT_MS)
        svg_count = page.locator(".meteogram-overlay.visible svg").count()
        if svg_count == 0:
            return False, "Kein SVG gerendert"
        return True, f"SVG gerendert ({svg_count} Element(e))"
    except PlaywrightTimeout as e:
        return False, f"Timeout: {e}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def test_region_meteogram_renders(page: Page) -> tuple[bool, str]:
    """Öffnet /regionen, klickt erste Region, erwartet <svg> im #regionMeteogramChart.

    Hinweis: region-map.js ignoriert Klicks so lange currentDate == null ist.
    currentDate wird normalerweise erst gesetzt, wenn der InstantDB-Subscription-
    Handler feuert. Im Test injizieren wir das direkt über window.setRegionDate,
    damit wir nicht auf Cloud-Daten angewiesen sind.
    """
    import datetime
    today = datetime.date.today().isoformat()

    try:
        # wait_until='networkidle' ist wichtig: loadRegions() in region-map.js
        # fetched /api/regionen asynchron nach initMap() — erst dann existieren
        # die Polygon-Paths im DOM.
        page.goto(BASE_URL + "/regionen", timeout=NAV_TIMEOUT_MS,
                  wait_until="networkidle")
        page.wait_for_selector("#regionMap svg path", timeout=NAV_TIMEOUT_MS)

        # setRegionDate wird normalerweise von InstantDB gesetzt; wir forcieren es.
        page.wait_for_function(
            "typeof window.setRegionDate === 'function'",
            timeout=NAV_TIMEOUT_MS,
        )
        page.evaluate(f"window.setRegionDate('{today}')")
        # Kurze Pause, damit colorRegions() durchläuft und das DOM stabil ist
        page.wait_for_timeout(500)

        # Auf erstes Leaflet-Polygon klicken. Wir verwenden page.mouse.click
        # statt locator.click, weil Playwright bei komplexen SVG-Pfaden
        # (z.B. L-förmigen Polygonen) intern einen Treffer-Test macht, der
        # bei nicht-rechteckigen Shapes fehlschlägt, selbst mit force=True.
        # Wir berechnen stattdessen den Mittelpunkt der Bounding-Box und
        # klicken direkt per Maus-Koordinate.
        path_info = page.evaluate(
            """
            () => {
                const paths = document.querySelectorAll(
                    '#regionMap svg path.leaflet-interactive'
                );
                if (paths.length === 0) return null;
                const r = paths[0].getBoundingClientRect();
                return {
                    count: paths.length,
                    cx: r.x + r.width / 2,
                    cy: r.y + r.height / 2,
                };
            }
            """
        )
        if not path_info:
            return False, "Keine interaktiven Leaflet-Polygone gefunden"
        # Clamp in den sichtbaren Bereich
        cx = max(10, min(1390, path_info["cx"]))
        cy = max(10, min(890, path_info["cy"]))
        page.mouse.click(cx, cy)

        # Overlay sichtbar
        page.wait_for_selector("#regionOverlay.visible", timeout=RENDER_TIMEOUT_MS)
        # Chart-Container existiert
        page.wait_for_selector("#regionMeteogramChart", timeout=RENDER_TIMEOUT_MS)
        # Warte auf SVG im Chart — DAS ist der Test, der beim vorherigen
        # Cache-Bug fehlgeschlagen wäre, weil renderRegionMeteogram wegen
        # des poisoned cache nie bis zum SVG-Erzeugen kam.
        page.wait_for_selector("#regionMeteogramChart svg", timeout=RENDER_TIMEOUT_MS)
        svg_count = page.locator("#regionMeteogramChart svg").count()
        if svg_count == 0:
            return False, "Kein SVG im #regionMeteogramChart"
        return True, f"SVG gerendert ({svg_count} Element(e))"
    except PlaywrightTimeout as e:
        return False, f"Timeout: {e} — evtl. render-Bug oder Daten fehlen"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def test_no_console_errors(errors: list) -> tuple[bool, str]:
    """Prüft, ob während der vorherigen Tests irgendwelche JS-Errors auftraten."""
    if not errors:
        return True, "keine Errors"
    return False, f"{len(errors)} Error(s): " + " | ".join(errors[:3])


# ============================================================================
# Runner
# ============================================================================

def main() -> int:
    print("Wingcast E2E Smoke Tests")
    print("=" * 60)

    if not check_server_up():
        print(f"FEHLER: Flask-Server nicht erreichbar unter {BASE_URL}")
        print("Bitte erst `python main.py` in separatem Terminal starten.")
        return 2

    print(f"Server erreichbar unter {BASE_URL}")
    print()

    results: list[tuple[str, bool, str]] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1400, "height": 900})
        page = context.new_page()

        errors = collect_console_errors(page)

        # Test 1: Spot-Meteogramm
        ok, detail = test_spot_meteogram_renders(page)
        log(ok, "test_spot_meteogram_renders", detail)
        results.append(("test_spot_meteogram_renders", ok, detail))

        # Kleine Pause, damit async Fehler noch in den Listener kommen
        time.sleep(0.5)

        # Test 2: Region-Meteogramm
        ok, detail = test_region_meteogram_renders(page)
        log(ok, "test_region_meteogram_renders", detail)
        results.append(("test_region_meteogram_renders", ok, detail))

        time.sleep(0.5)

        # Test 3: Console-Errors
        ok, detail = test_no_console_errors(errors)
        log(ok, "test_no_console_errors", detail)
        results.append(("test_no_console_errors", ok, detail))

        browser.close()

    print()
    print("=" * 60)
    total = len(results)
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"Ergebnis: {passed}/{total} Tests bestanden")

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
