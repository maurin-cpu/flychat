/**
 * Vektor-Grundkarte (MapLibre GL) unter der bestehenden Leaflet-Karte.
 *
 * Warum: Rasterkacheln sind fertige Bilder pro Ausschnitt und Zoomstufe —
 * jede Bewegung heisst Nachladen, sichtbar als graue Felder (gemessen 60-87%
 * beim Ziehen auf langsamem Netz). Die Vektorkarte zeichnet lokal auf der
 * GPU: beim Zoomen wird gerechnet statt geladen (0.1-1% grau, Zwischenzoom
 * scharf, Optik identisch — derselbe Carto-Stil als GL-Variante).
 *
 * ABLAUF (Lehre vom ersten Rollout, 23.08. abends): Die erste Version hat die
 * GL-Karte SOFORT initialisiert und den Raster-Stack weggelassen. Auf Handys
 * gab das JS-Fehler (GL-Start in noch verborgenem Container) und einen
 * blockierten ersten Fingerkontakt (Bibliothek parsen + GL-Init auf dem
 * Main-Thread, waehrend noch kein fertiges Kartenbild da war). Deshalb jetzt:
 *
 *   1. Der Aufrufer baut IMMER zuerst den Raster-Stack — die Karte ist sofort
 *      sichtbar und bedienbar wie bisher.
 *   2. Die GL-Ebene wird erst im Leerlauf angehaengt (requestIdleCallback),
 *      und nur wenn der Karten-Container tatsaechlich Groesse hat (auf dem
 *      Handy startet #map verborgen) — sonst wird gewartet.
 *   3. Erst wenn die GL-Karte ihr 'load' meldet, wird onReady gerufen und der
 *      Aufrufer nimmt die Carto-Rasterebenen weg.
 *   4. Geht IRGENDETWAS schief (kein WebGL, CDN nicht geladen, Style-Fehler,
 *      spaeterer Laufzeitfehler aus maplibre), bleibt bzw. wird die
 *      Rasterkarte der Zustand — die GL-Ebene wird abgeraeumt, kein zweiter
 *      Versuch. Selbstheilung statt Fehlerbanner.
 */
(function () {
    'use strict';

    var STYLE_URL = 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json';
    var WARTE_INTERVALL_MS = 400;   // Poll: Bibliothek geladen? Container sichtbar?
    var WARTE_MAX_MS = 30000;       // danach endgueltig beim Raster bleiben

    function webglVerfuegbar() {
        try {
            var cv = document.createElement('canvas');
            return !!(cv.getContext('webgl2') || cv.getContext('webgl') ||
                      cv.getContext('experimental-webgl'));
        } catch (e) { return false; }
    }

    // opts.onReady() — GL-Karte fertig geladen, Raster kann weg.
    // opts.onGiveup() — optional; endgueltig beim Raster geblieben.
    window.wingcastVectorBasemap = function (map, opts) {
        opts = opts || {};
        var gl = null;
        var fertig = false;         // onReady schon gerufen
        var aufgegeben = false;
        var start = Date.now();

        function aufgeben() {
            if (aufgegeben) return;
            aufgegeben = true;
            if (gl) { try { map.removeLayer(gl); } catch (e) { /* egal */ } gl = null; }
            if (typeof opts.onGiveup === 'function') { try { opts.onGiveup(); } catch (e) { /* egal */ } }
        }

        // Selbstheilung: wirft maplibre spaeter einen unbehandelten Fehler,
        // GL abraeumen — der Raster-Stack ist (noch) da bzw. wird via
        // onGiveup wiederhergestellt. error-monitor.js blendet Fehler aus
        // maplibre-Dateien aus, WEIL dieser Handler sie behandelt.
        window.addEventListener('error', function (ev) {
            if (aufgegeben || !ev || !ev.filename) return;
            if (ev.filename.indexOf('maplibre') === -1) return;
            aufgeben();
        });

        var brueckeAngefragt = false;
        function brueckeLaden() {
            // Die Leaflet-Bruecke braucht L UND maplibregl — bei async-Laden
            // ist deren Reihenfolge nicht garantiert, deshalb laedt SIE erst,
            // wenn beide da sind.
            if (brueckeAngefragt) return;
            brueckeAngefragt = true;
            var sc = document.createElement('script');
            sc.src = 'https://unpkg.com/@maplibre/maplibre-gl-leaflet@0.0.22/leaflet-maplibre-gl.js';
            sc.onerror = aufgeben;
            document.head.appendChild(sc);
        }

        function versuchen() {
            if (aufgegeben || fertig) return;
            if (Date.now() - start > WARTE_MAX_MS) { aufgeben(); return; }

            if (typeof L !== 'undefined' && typeof window.maplibregl !== 'undefined' &&
                typeof L.maplibreGL !== 'function') {
                brueckeLaden();
            }
            var bereit = (typeof L !== 'undefined') && (typeof L.maplibreGL === 'function') &&
                (typeof window.maplibregl !== 'undefined');
            var groesse = map.getSize();
            var sichtbar = groesse && groesse.x > 0 && groesse.y > 0;
            if (!sichtbar) {
                // Verborgene Karte (Mobil-Tab) zaehlt nicht gegen die Frist —
                // sonst bliebe Raster fuer immer, wenn der Karten-Tab erst
                // nach 30s geoeffnet wird. Das Polling ist billig.
                start = Date.now();
                setTimeout(versuchen, WARTE_INTERVALL_MS);
                return;
            }
            if (!bereit) {
                setTimeout(versuchen, WARTE_INTERVALL_MS);
                return;
            }
            if (!webglVerfuegbar()) { aufgeben(); return; }

            try {
                gl = L.maplibreGL({
                    style: STYLE_URL,
                    interactive: false,      // Eingaben macht Leaflet, nicht MapLibre
                    pane: 'tilePane',
                    // Lizenzpflicht — im Raster-Zweig haengt sie an der
                    // Grundkarte, hier am GL-Layer (L.Layer liest options).
                    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>',
                });
                gl.addTo(map);
                var c = (typeof gl.getContainer === 'function') ? gl.getContainer() : gl._container;
                if (c) {
                    c.style.zIndex = '0';
                    var pane = map.getPane('tilePane');
                    if (pane && c.parentNode === pane) pane.insertBefore(c, pane.firstChild);
                }
                var glMap = gl.getMaplibreMap ? gl.getMaplibreMap() : gl._glMap;
                if (!glMap) { aufgeben(); return; }
                // Style-/Kachelfehler nur loggen — MapLibre wirft sie sonst
                // als Error-Event bis in die Konsole.
                glMap.on('error', function (e) {
                    if (window.console && console.warn) console.warn('vector-basemap:', e && e.error);
                });
                glMap.once('load', function () {
                    if (aufgegeben) return;
                    fertig = true;
                    if (typeof opts.onReady === 'function') { try { opts.onReady(); } catch (e) { /* egal */ } }
                });
            } catch (e) {
                aufgeben();
            }
        }

        // Nicht in den Seitenaufbau druecken: erst wenn der Browser Luft hat.
        if (typeof requestIdleCallback === 'function') {
            requestIdleCallback(versuchen, { timeout: 3000 });
        } else {
            setTimeout(versuchen, 1200);
        }
        return true;   // Versuch laeuft; Ergebnis kommt via onReady/onGiveup
    };
})();
