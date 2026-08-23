/**
 * Stufenloser Mausrad-Zoom fuer Leaflet-Karten (Spot-Karte + Regionen-Karte).
 *
 * Warum: Leaflets Standard macht pro Rad-Ereignis EINEN animierten Sprung.
 * Das fuehlt sich "step by step" an — man sieht die Stufen einzeln einrasten.
 * Hier sammeln sich die Rad-Eingaben stattdessen in einem Ziel-Zoom, und ein
 * Tween gleitet pro Bild dorthin (wie Google Maps).
 *
 * Der Trick fuer die Fluessigkeit: waehrend des Gleitens wird derselbe Weg
 * benutzt wie beim Pinch — `map._move(center, zoom, {pinch: true})`. Leaflets
 * GridLayer behandelt einen Pinch-Move als "nur transformieren": die Kacheln
 * werden gedehnt statt neu geladen. Ohne das wuerde bei jedem Ueberschreiten
 * einer Kachelstufe der komplette Satz getauscht — gemessen die Ursache der
 * langen Einzelbilder beim Reinzoomen. Uebernommen (und nachgeladen) wird
 * erst, wenn die Bewegung steht.
 *
 * Voraussetzung dafuer: die Karte muss mit `zoomSnap: 0` laufen (sonst rastet
 * das Ergebnis am Ende wieder auf eine Stufe ein) und ihre Kachel-Layer mit
 * `updateWhenZooming: false`.
 *
 * Gemessene JS-Arbeit pro Gleit-Bild: ~1.6ms (Spitze 3ms) bei 4x gedrosselter
 * CPU und 494 Spots — der Rest des Bildbudgets bleibt dem Browser.
 *
 * Benutzt Leaflet-Interna (_move/_moveStart/_animateZoom, wie Leaflets eigener
 * TouchZoom-Handler). Fehlen sie, passiert nichts und Leaflets Standard-Zoom
 * bleibt aktiv — die Karte funktioniert dann wie vorher.
 */
(function () {
    'use strict';

    var ZOOM_PER_NOTCH = 1.0;   // eine Mausrad-Raste = eine Zoomstufe (wie Google)
    var ZOOM_EASE = 0.22;       // Anteil der Reststrecke pro Bild (~250ms Auslauf)
    var SETTLE_MS = 140;        // Ruhe am Rad, ab der auf eine ganze Stufe gezielt wird

    window.wingcastSmoothWheelZoom = function (map) {
        if (!map || !map.scrollWheelZoom || typeof map._move !== 'function' ||
            typeof map._moveStart !== 'function' || typeof map._animateZoom !== 'function') {
            return false;
        }
        map.scrollWheelZoom.disable();
        var st = { active: false, target: 0, current: 0, anchor: null, raf: 0, settle: 0 };

        // Kacheln sind Rasterbilder: nur auf einer GANZEN Zoomstufe werden sie
        // 1:1 gezeichnet. Auf einem Zwischenwert wird gedehnt — gemessen bis zu
        // 26% weniger Kantenschaerfe (Zoom 9.0: 9.0, Zoom 9.25: 6.6). Hoeher
        // aufgeloeste Kacheln helfen kaum (7.0) und kosten das 2.7-fache an
        // Daten. Deshalb: sobald am Rad Ruhe ist, wird das ZIEL auf die naechste
        // ganze Stufe gerundet — die laufende Bewegung traegt einfach dorthin
        // aus. Kein zweiter Ruck nach der Geste, aber im Ruhezustand scharf.
        function armSettle() {
            clearTimeout(st.settle);
            st.settle = setTimeout(function () {
                if (!st.active) return;
                st.target = clamp(Math.round(st.target));
            }, SETTLE_MS);
        }

        // Rasten aus dem Rad-Ereignis. deltaMode: 0=Pixel, 1=Zeilen, 2=Seiten.
        // Trackpads liefern viele kleine Deltas — die summieren sich von selbst.
        function notchesOf(e) {
            var d = e.deltaY;
            if (!d) return 0;
            if (e.deltaMode === 1) d *= 20;
            else if (e.deltaMode === 2) d *= 400;
            return -d / 120;
        }

        // Haelt den Punkt unter dem Cursor fest (Mathe wie Leaflets
        // setZoomAround, nur ohne dessen sofortigen View-Wechsel).
        function centerFor(zoom) {
            var scale = map.getZoomScale(zoom, map.getZoom()),
                viewHalf = map.getSize().divideBy(2),
                offset = st.anchor.subtract(viewHalf).multiplyBy(1 - 1 / scale);
            return map.containerPointToLatLng(viewHalf.add(offset));
        }

        function clamp(z) {
            return Math.max(map.getMinZoom(), Math.min(map.getMaxZoom(), z));
        }

        function step() {
            st.raf = 0;
            var diff = st.target - st.current;
            if (Math.abs(diff) < 0.002) { finish(); return; }
            st.current = clamp(st.current + diff * ZOOM_EASE);
            map._move(centerFor(st.current), st.current, { pinch: true, round: false });
            st.raf = requestAnimationFrame(step);
        }

        function finish() {
            st.active = false;
            clearTimeout(st.settle);
            // Exakt auf dem Ziel landen (nicht auf dem letzten Tween-Wert):
            // sonst bleibt ein Rest wie 11.0019 stehen und die Kacheln werden
            // trotz Auslauf auf die ganze Stufe minimal gedehnt.
            st.current = clamp(st.target);
            var z = map._limitZoom ? map._limitZoom(st.current) : st.current;
            // Uebernahme wie am Ende einer Pinch-Geste: laedt die Kacheln der
            // neuen Stufe nach und feuert zoomend (daran haengt z.B. die
            // Spot-Groessen-Kompensation in map.js).
            map._animateZoom(centerFor(z), z, true, map.options.zoomSnap);
        }

        map.getContainer().addEventListener('wheel', function (e) {
            var n = notchesOf(e);
            if (!n) return;
            e.preventDefault();          // kein Seiten-Scroll, kein Browser-Zoom
            st.anchor = map.mouseEventToContainerPoint(e);
            if (!st.active) {
                // Eine noch laufende Uebernahme-Animation sauber abschliessen,
                // sonst ueberlagern sich zwei Zoom-Zustaende.
                if (map._animatingZoom && typeof map._onZoomTransitionEnd === 'function') {
                    map._onZoomTransitionEnd();
                }
                map._stop();
                st.current = map.getZoom();
                st.target = st.current;
                st.active = true;
                map._moveStart(true, false);   // feuert zoomstart
            }
            st.target = clamp(st.target + n * ZOOM_PER_NOTCH);
            armSettle();
            if (!st.raf) st.raf = requestAnimationFrame(step);
        }, { passive: false });

        return true;
    };
})();
