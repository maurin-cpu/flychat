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
 * Der Ruhepunkt ist immer eine GANZE Zoomstufe (`zoomSnap: 1` auf der Karte),
 * weil Rasterkacheln nur dort 1:1 scharf sind. Gerundet wird aber schon bei der
 * Eingabe, nicht nach der Bewegung — sonst zieht die Karte am Ende sichtbar
 * zurueck.
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

    window.wingcastSmoothWheelZoom = function (map) {
        if (!map || !map.scrollWheelZoom || typeof map._move !== 'function' ||
            typeof map._moveStart !== 'function' || typeof map._animateZoom !== 'function') {
            return false;
        }
        map.scrollWheelZoom.disable();
        // roh = die Summe aller Rad-Eingaben, ziel = die daraus gerundete
        // ganze Zoomstufe. Getrennt, damit kleine Trackpad-Deltas sich
        // aufsummieren koennen, ohne einzeln verschluckt zu werden.
        var st = { active: false, raw: 0, target: 0, current: 0, anchor: null, raf: 0 };

        // Kacheln sind Rasterbilder: nur auf einer GANZEN Zoomstufe werden sie
        // 1:1 gezeichnet. Auf einem Zwischenwert wird gedehnt — gemessen bis zu
        // 26% weniger Kantenschaerfe (Zoom 9.0: 9.0, Zoom 9.25: 6.6). Hoeher
        // aufgeloeste Kacheln helfen kaum (7.0) und kosten das 2.7-fache an
        // Daten. Deshalb ist der Ruhepunkt immer eine ganze Stufe.
        //
        // WICHTIG ist der Zeitpunkt des Rundens: es passiert SOFORT bei der
        // Eingabe, nicht nach der Bewegung. Wurde erst hinterher gerundet, lief
        // die Karte auf z.B. 11.4 zu und zog danach auf 11 zurueck — sichtbar
        // als "zoomt am Schluss wieder ein Stueck raus". Jetzt steht das Ziel
        // von der ersten Bewegung an fest, die Karte laeuft nur noch hin.

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
                st.raw = st.current;
                st.target = st.current;
                st.active = true;
                map._moveStart(true, false);   // feuert zoomstart
            }
            st.raw = clamp(st.raw + n * ZOOM_PER_NOTCH);
            st.target = clamp(Math.round(st.raw));
            if (!st.raf) st.raf = requestAnimationFrame(step);
        }, { passive: false });

        return true;
    };
})();
