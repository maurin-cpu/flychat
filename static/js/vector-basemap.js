/**
 * Vektor-Grundkarte (MapLibre GL) unter der bestehenden Leaflet-Karte.
 *
 * Warum: Rasterkacheln sind fertige Bilder pro Ausschnitt und Zoomstufe —
 * jede Bewegung in neues Gebiet und jede Stufe heisst Nachladen, sichtbar als
 * graue Felder (gemessen 60-87% der Flaeche beim Ziehen auf langsamem Netz).
 * Kaschieren (Vorladen, grobe Unterlage) drueckt das auf ~1%, ersetzt Grau
 * aber durch sichtbare Unschaerfe. Die Vektorkarte loest es an der Wurzel:
 * die Rohdaten kommen einmal an, gezeichnet wird lokal auf der GPU — beim
 * Zoomen wird gerechnet statt geladen, Labels sind auf jeder Stufe scharf.
 * Prototyp-Messung 23.08.: 0.7% grau nach Ziehen (gedrosselt), Bildrate
 * unveraendert 8.3ms, Zwischenzoom voll scharf, Optik identisch (derselbe
 * Carto-Stil, nur als GL-Variante).
 *
 * Es wird NUR die Grundkarte getauscht. Leaflet, Spots (Canvas), Regionen,
 * smooth-zoom — alles bleibt; die GL-Ebene liegt zuunterst im tilePane.
 * Liefert false, wenn MapLibre fehlt oder kein WebGL da ist — der Aufrufer
 * behaelt dann den Raster-Stack (Rueckfallweg = bisheriger Stand).
 */
(function () {
    'use strict';

    // Derselbe Kartenstil wie die bisherigen Raster-Kacheln (Carto Positron,
    // "light"), nur als Vektor. Labels sind im Stil enthalten.
    var STYLE_URL = 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json';

    function webglVerfuegbar() {
        try {
            var cv = document.createElement('canvas');
            return !!(cv.getContext('webgl2') || cv.getContext('webgl') ||
                      cv.getContext('experimental-webgl'));
        } catch (e) { return false; }
    }

    window.wingcastVectorBasemap = function (map) {
        if (!map || typeof L === 'undefined' || typeof L.maplibreGL !== 'function' ||
            typeof window.maplibregl === 'undefined' || !webglVerfuegbar()) {
            return false;
        }
        try {
            var gl = L.maplibreGL({
                style: STYLE_URL,
                interactive: false,      // Eingaben macht Leaflet, nicht MapLibre
                pane: 'tilePane',
                // Lizenzpflicht: haengt im Raster-Zweig an der Grundkarte,
                // hier am GL-Layer (L.Layer.getAttribution liest options).
                attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>',
            });
            gl.addTo(map);
            // Zuunterst im tilePane: Hillshade (Raster, Desktop) und alle
            // Overlays liegen darueber.
            var c = (typeof gl.getContainer === 'function') ? gl.getContainer() : gl._container;
            if (c) {
                c.style.zIndex = '0';
                var pane = map.getPane('tilePane');
                if (pane && c.parentNode === pane) pane.insertBefore(c, pane.firstChild);
            }
            return true;
        } catch (e) {
            // Nie die Karte kosten: im Zweifel Raster-Stack behalten.
            try { if (gl) map.removeLayer(gl); } catch (e2) { /* egal */ }
            return false;
        }
    };
})();
