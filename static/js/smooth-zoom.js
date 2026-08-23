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
        var st = { active: false, raw: 0, target: 0, current: 0, anchor: null, raf: 0,
                   dir: 0, letzteRichtung: 0, endeZeit: 0 };

        // Nachlauf-Schutz. Praezisions-Raeder und Trackpads schicken nach dem
        // Wisch noch kleine Impulse, teils in die Gegenrichtung. Trifft so
        // einer NACH dem Gesten-Ende ein, startete er bisher eine neue Geste —
        // und wurde durch das richtungstreue Runden auf eine ganze Stufe
        // rueckwaerts verstaerkt. Das war das sichtbare "zoomt am Schluss
        // wieder raus". Deshalb: kurz nach einer Geste zaehlen kleine
        // Gegenimpulse nicht.
        var NACHLAUF_MS = 350;
        var NACHLAUF_MIN = 0.5;   // Rasten, ab denen es eine echte neue Geste ist

        // Rueckwaerts-Korrekturen sind das, was der Nutzer als "zoomt am Ende
        // wieder ein Stueck raus" sieht. Erlaubt ist deshalb nur eine winzige
        // Korrektur (RUECK_TOLERANZ, ~5% Massstab — unsichtbar); alles darueber
        // wird nach VORN gerundet, also in die Richtung, in die man gerade
        // gezoomt hat. So bewegt sich die Karte nie gegen die eigene Geste.
        var RUECK_TOLERANZ = 0.08;
        function rasterZiel(z, richtung) {
            var nah = Math.round(z);
            if (richtung > 0 && nah < z - RUECK_TOLERANZ) return Math.ceil(z - 1e-6);
            if (richtung < 0 && nah > z + RUECK_TOLERANZ) return Math.floor(z + 1e-6);
            return nah;
        }

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
            st.letzteRichtung = st.dir;
            st.endeZeit = performance.now();
            // Exakt auf dem Ziel landen (nicht auf dem letzten Tween-Wert):
            // sonst bleibt ein Rest wie 11.0019 stehen und die Kacheln werden
            // trotz Auslauf auf die ganze Stufe minimal gedehnt.
            st.current = clamp(st.target);
            var z = st.current;
            // Uebernahme SOFORT statt ueber Leaflets 250ms-Zoomanimation: der
            // Zoom steht hier schon (Restdistanz < 0.002), die Animation waere
            // unsichtbar — aber waehrend ihr rechnet die Treffer-Erkennung mit
            // den alten Ebenen-Positionen, und ein Klick in dem Fenster geht
            // daneben ("erster Klick ignoriert"). setView ohne Animation
            // feuert zoomend/moveend, laedt Kacheln nach und schliesst die
            // Geste im selben Frame ab.
            map.setView(centerFor(z), z, { animate: false });
        }

        // --- Pinch (Leaflets eigener TouchZoom) ---
        // Am Gesten-Ende rundet Leaflet ueber map._limitZoom auf die naechste
        // ganze Stufe — also potenziell bis zu einer halben Stufe ZURUECK.
        // Dieselbe Regel wie oben anwenden: nur winzige Korrekturen rueckwaerts,
        // sonst nach vorn. Greift nur waehrend einer laufenden Geste, damit
        // setView/fitBounds unveraendert bleiben.
        var geste = { aktiv: false, von: 0 };
        map.on('zoomstart', function () {
            if (geste.aktiv) return;
            geste.aktiv = true;
            geste.von = map.getZoom();
        });
        map.on('zoomend', function () { geste.aktiv = false; });
        var origLimitZoom = map._limitZoom;
        map._limitZoom = function (z) {
            if (geste.aktiv && this.options.zoomSnap) {
                var d = z - geste.von;
                if (Math.abs(d) > 1e-6) {
                    return Math.max(this.getMinZoom(),
                           Math.min(this.getMaxZoom(), rasterZiel(z, d > 0 ? 1 : -1)));
                }
            }
            return origLimitZoom.call(this, z);
        };

        // --- Eigener Pinch-Pfad (ersetzt Leaflets TouchZoom) ---
        // Leaflets Pinch skaliert die Ebenen per CSS mit der Geste. Beim
        // RAUSzoomen schrumpft dabei die ganze Kartenflaeche und rundherum
        // wird der Container-Untergrund sichtbar (gemessen: grauer Rand mitten
        // in der Geste). Der Rad-Pfad hat das nicht, weil er pro Bild echt
        // neu zeichnet (map._move mit pinch:true — die Vektor-Grundkarte
        // rendert dann jeden Zwischenzustand). Deshalb laeuft der Pinch jetzt
        // ueber denselben Weg: Zoom aus dem Fingerabstand, Anker unter den
        // Fingern, ein _move pro Frame. Am Ende dieselbe Uebernahme wie beim
        // Rad (finish-Logik: richtungstreu auf eine ganze Stufe).
        if (map.touchZoom) {
            map.touchZoom.disable();
            var pz = { aktiv: false, startZoom: 0, startLatLng: null, startDist: 1, mitte: null, raf: 0 };

            function containerPoint(t) {
                var r = map.getContainer().getBoundingClientRect();
                return L.point(t.clientX - r.left, t.clientY - r.top);
            }

            function pinchFrame() {
                pz.raf = 0;
                if (!pz.aktiv) return;
                // Center so, dass der Start-Weltpunkt unter der aktuellen
                // Fingermitte liegt (Mathe wie Leaflets TouchZoom).
                var z = pz.zoom;
                var centerPt = map.project(pz.startLatLng, z)
                    .subtract(pz.mitte)
                    .add(map.getSize().divideBy(2));
                map._move(map.unproject(centerPt, z), z, { pinch: true, round: false });
            }

            map.getContainer().addEventListener('touchstart', function (e) {
                if (e.touches.length !== 2 || pz.aktiv) return;
                if (map._animatingZoom && typeof map._onZoomTransitionEnd === 'function') {
                    map._onZoomTransitionEnd();
                }
                map._stop();
                var p1 = containerPoint(e.touches[0]), p2 = containerPoint(e.touches[1]);
                var mitte = p1.add(p2).divideBy(2);
                pz.aktiv = true;
                pz.startZoom = map.getZoom();
                pz.zoom = pz.startZoom;
                pz.startDist = Math.max(1, p1.distanceTo(p2));
                pz.startLatLng = map.containerPointToLatLng(mitte);
                pz.mitte = mitte;
                map._moveStart(true, false);   // feuert zoomstart
            }, { passive: true });

            map.getContainer().addEventListener('touchmove', function (e) {
                if (!pz.aktiv || e.touches.length !== 2) return;
                e.preventDefault();            // kein Browser-Pinch auf der Seite
                var p1 = containerPoint(e.touches[0]), p2 = containerPoint(e.touches[1]);
                pz.mitte = p1.add(p2).divideBy(2);
                pz.zoom = clamp(pz.startZoom + Math.log(p1.distanceTo(p2) / pz.startDist) / Math.LN2);
                if (!pz.raf) pz.raf = requestAnimationFrame(pinchFrame);
            }, { passive: false });

            var pinchEnde = function (e) {
                if (!pz.aktiv || (e.touches && e.touches.length >= 2)) return;
                pz.aktiv = false;
                if (pz.raf) { cancelAnimationFrame(pz.raf); pz.raf = 0; }
                // Uebergabe an die Rad-Logik (finish-Auslauf). ANDERS als am
                // Rad wird zur NAECHSTGELEGENEN Stufe gerundet: das leichte
                // Ueberziehen der Finger ist beim Pinch Absicht, kein Nachlauf-
                // Rauschen. Die richtungstreue Regel schob hier ein Loslassen
                // bei 11.19 auf 12 weiter — alles wanderte nach der Geste
                // (gemessen 51px) und der erste Tipp ging daneben.
                st.anchor = pz.mitte;
                st.current = pz.zoom;
                st.raw = pz.zoom;
                st.dir = (pz.zoom >= pz.startZoom) ? 1 : -1;
                if (Math.abs(pz.zoom - pz.startZoom) < 1e-6) st.dir = 0;
                st.target = clamp(Math.round(pz.zoom));
                st.active = true;
                if (!st.raf) st.raf = requestAnimationFrame(step);
            };
            map.getContainer().addEventListener('touchend', pinchEnde, { passive: true });
            map.getContainer().addEventListener('touchcancel', pinchEnde, { passive: true });
        }

        map.getContainer().addEventListener('wheel', function (e) {
            var n = notchesOf(e);
            if (!n) return;
            e.preventDefault();          // kein Seiten-Scroll, kein Browser-Zoom
            var richtung = (n > 0 ? 1 : -1);
            if (!st.active && st.letzteRichtung && richtung !== st.letzteRichtung &&
                Math.abs(n) < NACHLAUF_MIN &&
                (performance.now() - st.endeZeit) < NACHLAUF_MS) {
                return;   // Nachlauf der eben beendeten Geste, keine neue
            }
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
                st.dir = 0;
                st.active = true;
                map._moveStart(true, false);   // feuert zoomstart
            }
            if (!st.dir) st.dir = richtung;
            // Praezisions-Raeder und Trackpads schicken am Ende eines Wischs
            // kleine Impulse in die GEGENRICHTUNG (Nachlauf). Zaehlte man die
            // mit, rutschte das Ziel eine Stufe zurueck — sichtbar als
            // Rauszoomen am Schluss. Innerhalb einer Geste zaehlt deshalb nur,
            // was in die urspruengliche Richtung geht.
            if (richtung !== st.dir) return;
            st.raw = clamp(st.raw + n * ZOOM_PER_NOTCH);
            st.target = clamp(rasterZiel(st.raw, st.dir));
            if (!st.raf) st.raf = requestAnimationFrame(step);
        }, { passive: false });

        return true;
    };
})();
