/**
 * Precip-Refpoints Layer — zeigt die 16 Niederschlags-Referenzpunkte
 * pro Region auf Leaflet-Karten an.
 *
 * Visuell klar abgegrenzt von den 7 Haupt-Refpoints:
 *   - Haupt-RPs (region-map.js):   weiss-gefuellt, blauer Rand, Radius 4
 *   - Precip-RPs (DIESER LAYER):   blau-gefuellt halbtransparent, Radius 2.5,
 *                                  ohne Beschriftung, mit Tropfen-Tooltip
 *
 * Datenquelle: /api/regionen-precip-refpoints
 * (statisch aus data/regionen_referenzpunkte_precip.geojson — siehe
 *  scripts/create_precip_refpoints.py)
 *
 * API:
 *   window.GleitcastPrecipRefpoints.attach(map)
 *     → returns { remove() }
 */
(function () {
    'use strict';

    // Cache: nur einmal fetchen pro Tab, auch wenn mehrere Karten den Layer nutzen.
    var _cache = null;
    var _pending = null;

    function loadData() {
        if (_cache) return Promise.resolve(_cache);
        if (_pending) return _pending;
        _pending = fetch('/api/regionen-precip-refpoints', {
            headers: { 'Accept': 'application/json' }
        }).then(function (r) {
            if (!r.ok) throw new Error('precip refpoints HTTP ' + r.status);
            return r.json();
        }).then(function (fc) {
            _cache = fc;
            _pending = null;
            return fc;
        }).catch(function (err) {
            _pending = null;
            console.warn('[precip-refpoints] load failed:', err.message);
            return { type: 'FeatureCollection', features: [] };
        });
        return _pending;
    }

    function attach(map) {
        if (!map) return { remove: function () {} };

        var layer = L.layerGroup().addTo(map);

        loadData().then(function (fc) {
            (fc.features || []).forEach(function (feature) {
                var props = feature.properties || {};
                var regionName = props.region || props.name || props.id || 'Region';
                var pts = props.reference_points || [];
                pts.forEach(function (pt) {
                    if (!Array.isArray(pt) || pt.length < 2) return;
                    var marker = L.circleMarker([pt[0], pt[1]], {
                        radius: 2.5,
                        color: '#1d4ed8',        // dunkles Blau (Rand)
                        weight: 1,
                        fillColor: '#3b82f6',    // helleres Blau (Fuellung)
                        fillOpacity: 0.55,
                        interactive: true,
                    });
                    marker.bindTooltip(
                        'Niederschlags-RP · ' + regionName,
                        { direction: 'top', offset: [0, -2], opacity: 0.9 }
                    );
                    layer.addLayer(marker);
                });
            });
        });

        return {
            remove: function () {
                if (layer) {
                    map.removeLayer(layer);
                    layer = null;
                }
            }
        };
    }

    window.GleitcastPrecipRefpoints = { attach: attach };
})();
