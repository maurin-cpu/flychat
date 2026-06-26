/**
 * OSM Peaks Layer — zeigt benannte Berge / Hügel / Pässe / Sättel
 * aus OpenStreetMap auf Leaflet-Karten an.
 *
 * Daten: data/osm_peaks_major.geojson (Peaks≥2500m + Pässe + Sättel≥2000m)
 *        data/osm_peaks_minor.geojson (Rest)
 *        Generiert via scripts/fetch_osm_peaks.py
 *
 * API:
 *   window.WingcastOsmPeaks.attach(map, options)
 *     options = {
 *       minZoomMajor: 9,    // ab welchem Zoom Major-Layer geladen wird
 *       minZoomMinor: 12,   // ab welchem Zoom Minor-Layer geladen wird
 *       paneZIndex: 450     // unter Spot-Markern (650), über Tiles
 *     }
 *   → returns { remove() }
 */
(function () {
    'use strict';

    // Cache: GeoJSON nur einmal pro Tab fetchen — auch wenn 3 Maps koexistieren
    var _cache = { major: null, minor: null };
    var _pending = { major: null, minor: null };

    function loadTier(tier) {
        if (_cache[tier]) return Promise.resolve(_cache[tier]);
        if (_pending[tier]) return _pending[tier];
        _pending[tier] = fetch('/api/osm_peaks/' + tier, {
            headers: { 'Accept': 'application/geo+json, application/json' }
        }).then(function (r) {
            if (!r.ok) throw new Error('OSM peaks ' + tier + ' HTTP ' + r.status);
            return r.json();
        }).then(function (fc) {
            _cache[tier] = fc;
            _pending[tier] = null;
            return fc;
        }).catch(function (err) {
            _pending[tier] = null;
            console.warn('[osm-peaks] load ' + tier + ' failed:', err.message);
            return { type: 'FeatureCollection', features: [] };
        });
        return _pending[tier];
    }

    // Symbol-Builder — OSM-Carto-Stil (osm.org Standard-Layer).
    // Peaks: kleines braunes Dreieck (ausgefuellt). Sattel: braune U-Form.
    // Pass: brauner Diamond. Alle in OSM-Standardbraun #734a08, ~8px,
    // dezent statt invasiv. Label unter dem Symbol, gleiches Braun, kursiv
    // fuer Hoehe (wie OSM Carto).
    function makeIcon(kind, showLabel, name, ele) {
        var size = 8;
        var svg;
        if (kind === 'saddle') {
            // Sattel: kleines U / Bogen (osm-carto saddle.svg vereinfacht)
            svg = '<svg xmlns="http://www.w3.org/2000/svg" width="' + size + '" height="' + size + '" viewBox="0 0 10 10">'
                + '<path d="M1.5 7.5 Q1.5 3.5 5 3.5 Q8.5 3.5 8.5 7.5" fill="none" stroke="#734a08" stroke-width="1.2" stroke-linecap="round"/>'
                + '</svg>';
        } else if (kind === 'pass') {
            // Pass: kleiner brauner Diamond (osm-carto mountain_pass.svg)
            svg = '<svg xmlns="http://www.w3.org/2000/svg" width="' + size + '" height="' + size + '" viewBox="0 0 10 10">'
                + '<polygon points="5,1 9,5 5,9 1,5" fill="#734a08"/>'
                + '</svg>';
        } else {
            // Peak: gefuelltes Dreieck im OSM-Braun (osm-carto peak.svg)
            svg = '<svg xmlns="http://www.w3.org/2000/svg" width="' + size + '" height="' + size + '" viewBox="0 0 10 10">'
                + '<polygon points="5,1.5 9,8.5 1,8.5" fill="#734a08"/>'
                + '</svg>';
        }

        var labelHtml = '';
        if (showLabel && name) {
            var nameHtml = '<span class="osm-peak-name">' + escapeHtml(name) + '</span>';
            var eleHtml = (ele != null)
                ? '<span class="osm-peak-ele">' + Math.round(ele) + '</span>'
                : '';
            labelHtml = '<div class="osm-peak-label">' + nameHtml + eleHtml + '</div>';
        }

        // Innerer Wrapper zentriert das Symbol; Label haengt darunter.
        var iconHtml = '<div class="osm-peak-icon" data-kind="' + kind + '">'
            + '<div class="osm-peak-sym">' + svg + '</div>'
            + labelHtml
            + '</div>';

        return L.divIcon({
            html: iconHtml,
            className: 'osm-peak-divicon',
            iconSize: [size, size],
            iconAnchor: [size / 2, size / 2],
        });
    }

    function escapeHtml(s) {
        return String(s).replace(/[&<>"']/g, function (c) {
            return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c];
        });
    }

    function injectStyles() {
        if (document.getElementById('osm-peak-styles')) return;
        var st = document.createElement('style');
        st.id = 'osm-peak-styles';
        // OSM-Carto-Style: braune Symbole + Label darunter, kleines Sans-Serif,
        // weiss-halo statt drop-shadow. Genau wie auf osm.org.
        st.textContent = [
            '.osm-peak-divicon { background: transparent !important; border: none !important; }',
            '.osm-peak-icon {',
            '  position: relative; pointer-events: auto;',
            '  display: flex; flex-direction: column; align-items: center;',
            '}',
            '.osm-peak-sym { line-height: 0; }',
            '.osm-peak-sym svg { display: block; }',
            '.osm-peak-label {',
            '  margin-top: 1px;',
            '  display: flex; flex-direction: column; align-items: center;',
            '  pointer-events: none; white-space: nowrap;',
            '  font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;',
            '}',
            '.osm-peak-name {',
            '  font-size: 10px; font-weight: 400; color: #734a08;',
            '  text-shadow: 1px 0 #fff, -1px 0 #fff, 0 1px #fff, 0 -1px #fff,',
            '               1px 1px #fff, -1px -1px #fff, 1px -1px #fff, -1px 1px #fff;',
            '}',
            '.osm-peak-ele {',
            '  font-size: 9px; font-style: italic; font-weight: 400; color: #734a08;',
            '  text-shadow: 1px 0 #fff, -1px 0 #fff, 0 1px #fff, 0 -1px #fff,',
            '               1px 1px #fff, -1px -1px #fff, 1px -1px #fff, -1px 1px #fff;',
            '  margin-top: -1px;',
            '}',
        ].join('\n');
        document.head.appendChild(st);
    }

    /**
     * Hängt Peaks-Layer an eine Leaflet-Karte.
     */
    function attach(map, options) {
        injectStyles();
        var opts = Object.assign({
            minZoomMajor: 10,     // Major-Peaks erst ab brauchbarem Detail
            minZoomMinor: 13,     // Minor erst sehr nah
            labelZoom: 12,        // ab hier Labels einblenden
            paneZIndex: 450,
            viewportPad: 0.25,    // Bbox um 25% erweitern (smoothes Pan)
        }, options || {});

        // Eigene Pane, damit Peaks unter Spot-Markern (markerPane z-index 600) liegen
        var paneName = 'osmPeaksPane';
        if (!map.getPane(paneName)) {
            map.createPane(paneName);
            var pane = map.getPane(paneName);
            pane.style.zIndex = String(opts.paneZIndex);
            pane.style.pointerEvents = 'auto';
        }

        // Marker-Container je Tier — wir rendern bei jedem Move/Zoom nur die
        // sichtbaren Features (Viewport-Culling). Kein DOM-Aufbau fuer
        // Tausende ausserhalb des Sichtbereichs.
        var layers = {
            major: L.layerGroup([], { pane: paneName }),
            minor: L.layerGroup([], { pane: paneName }),
        };
        var loaded = { major: false, minor: false };
        // State pro Tier — vermeidet unnoetige Re-Renders wenn weder Bbox
        // noch Label-Modus sich geaendert haben.
        var lastRender = { major: null, minor: null };

        function renderTier(tier, fc) {
            var z = map.getZoom();
            var showLabel = z >= opts.labelZoom;
            var bounds = map.getBounds().pad(opts.viewportPad);
            var sw = bounds.getSouthWest();
            var ne = bounds.getNorthEast();
            var minLat = sw.lat, maxLat = ne.lat;
            var minLon = sw.lng, maxLon = ne.lng;

            // Skip wenn nichts substantiell geaendert (gleicher Label-State +
            // Viewport hat sich nur minimal verschoben). Cheap-Hash aus Bbox+Label.
            var sig = showLabel + '|' + minLat.toFixed(3) + ',' + minLon.toFixed(3)
                + ',' + maxLat.toFixed(3) + ',' + maxLon.toFixed(3);
            if (lastRender[tier] === sig) return;
            lastRender[tier] = sig;

            layers[tier].clearLayers();
            var feats = fc.features || [];
            var added = 0;
            for (var i = 0; i < feats.length; i++) {
                var f = feats[i];
                var c = f.geometry && f.geometry.coordinates;
                if (!c || c.length < 2) continue;
                var lon = c[0], lat = c[1];
                if (lat < minLat || lat > maxLat || lon < minLon || lon > maxLon) continue;
                var p = f.properties || {};
                var m = L.marker([lat, lon], {
                    icon: makeIcon(p.kind || 'peak', showLabel, p.name || '', p.ele),
                    pane: paneName,
                    keyboard: false,
                    interactive: true,
                    bubblingMouseEvents: false,
                });
                var tip = (p.name || '') + (p.ele != null ? ' · ' + Math.round(p.ele) + ' m' : '');
                if (p.kind === 'pass') tip = 'Pass · ' + tip;
                else if (p.kind === 'saddle') tip = 'Sattel · ' + tip;
                m.bindTooltip(tip, { direction: 'top', offset: [0, -6], opacity: 0.95 });
                layers[tier].addLayer(m);
                added++;
            }
            // Debug-Hook (optional): window._osmPeaksLastCount = added;
        }

        function ensureTier(tier) {
            var minZoom = (tier === 'major') ? opts.minZoomMajor : opts.minZoomMinor;
            if (map.getZoom() < minZoom) {
                if (map.hasLayer(layers[tier])) map.removeLayer(layers[tier]);
                lastRender[tier] = null;
                return;
            }
            if (!loaded[tier]) {
                loaded[tier] = true;
                loadTier(tier).then(function (fc) {
                    if (map.getZoom() >= minZoom) {
                        renderTier(tier, fc);
                        map.addLayer(layers[tier]);
                    }
                });
                return;
            }
            if (_cache[tier]) {
                renderTier(tier, _cache[tier]);
                if (!map.hasLayer(layers[tier])) map.addLayer(layers[tier]);
            }
        }

        // Debounce: Pan feuert moveend oft, aber rerendern erst wenn Bewegung ruht.
        var pending = null;
        function scheduleUpdate() {
            if (pending) return;
            pending = (window.requestAnimationFrame || function (cb) { return setTimeout(cb, 16); })(function () {
                pending = null;
                ensureTier('major');
                ensureTier('minor');
            });
        }

        map.on('moveend', scheduleUpdate);
        map.on('zoomend', scheduleUpdate);
        // Initial-Check (falls Karte schon auf hohem Zoom startet)
        scheduleUpdate();

        return {
            remove: function () {
                map.off('moveend', scheduleUpdate);
                map.off('zoomend', scheduleUpdate);
                if (map.hasLayer(layers.major)) map.removeLayer(layers.major);
                if (map.hasLayer(layers.minor)) map.removeLayer(layers.minor);
            },
        };
    }

    window.WingcastOsmPeaks = { attach: attach };
})();
