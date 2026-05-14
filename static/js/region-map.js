/**
 * Gleitcast - Region Map + Analysis Overlay (Traffic Light System, Light Theme)
 */
(function () {
    'use strict';

    var map;
    var regionLayersByName = {};
    var labelMarkersGroup = null;
    var regionAnalyses = null;
    var currentDate = null;
    var meteogramCache = {};   // {region_id: {wxData, altData}}
    var spotAnalyses = null;   // lazy-loaded fuer Top-Spots-Liste pro Region
    var spotAnalysesPromise = null;
    var spotRegionMap = null;  // {spotName: region_id} aus /api/spots-Properties.
                               // Notwendig weil spot_analyses.json kein region_id-
                               // Feld persistiert — Region-Zuordnung kommt aus
                               // find_region_for_point (Backend liefert via GeoJSON).
    var regionActiveDate = {}; // {region_id: dateStr} — last selected day per region overlay
    var regionJsonDebugActive = false;
    var regionHazardDebugActive = false;

    // ResizeObserver-State: re-rendert das Meteogramm wenn sich die
    // Container-Breite aendert (z.B. Browser-Resize, Aside aufklappen,
    // Container-Query-Layoutwechsel). Ohne das wuerde das Chart in der
    // Initial-Render-Breite eingefroren bleiben.
    var chartResizeObserver = null;
    var chartResizeContext = null; // { wxData, altData, dateStr, chartEl }
    var chartResizeLastWidth = 0;
    var chartResizeLastHeight = 0;
    var chartResizeTimer = null;

    var overlay = document.getElementById('regionOverlay');
    var overlayTitle = document.getElementById('regionOverlayTitle');
    var overlayBody = document.getElementById('regionOverlayBody');
    var overlayClose = document.getElementById('regionOverlayClose');
    var meteogramTooltip = document.getElementById('regionMeteogramTooltip');

    var safetyLabels = { safe: 'Sicher', conditional: 'Vorsicht', not_safe: 'Nicht sicher', no_data: 'Keine Daten', error: 'Fehler' };
    var qualityLabels = { gray: 'Abgleiter', green: 'Gut', violet: 'Top' };

    // Safer JSON fetch: verhindert "Unexpected token '<'..."-Fehler bei HTML-Responses
    function fetchJson(url) {
        return fetch(url, { headers: { 'Accept': 'application/json' } }).then(function (r) {
            var ctype = (r.headers.get('content-type') || '').toLowerCase();
            return r.text().then(function (txt) {
                if (!r.ok) {
                    var msg;
                    if (ctype.indexOf('application/json') >= 0) {
                        try { msg = (JSON.parse(txt) || {}).error; } catch (e) { msg = null; }
                    }
                    throw new Error(msg || ('HTTP ' + r.status));
                }
                if (ctype.indexOf('application/json') < 0) {
                    throw new Error('Server lieferte keine JSON-Daten');
                }
                try {
                    return JSON.parse(txt);
                } catch (e) {
                    throw new Error('Antwort konnte nicht gelesen werden');
                }
            });
        });
    }

    function normalizeFlyTier(ft) {
        if (!ft) return '';
        var k = String(ft).trim().toLowerCase();
        if (k === 'gray' || k === 'green' || k === 'violet') return k;
        if (k === 'yellow') return 'gray';
        if (k === 'orange') return 'green';
        return 'green';
    }

    // RATING_ARCHITECTURE v2.0: experience_rating (1-6) → tier (gray/green/violet)
    function getQuality(dayData) {
        var er = parseInt(dayData && dayData.experience_rating, 10);
        if (!isFinite(er) || er <= 0) return 'gray';
        if (er >= 6) return 'violet';
        if (er >= 3) return 'green';
        return 'gray';
    }

    function qualityBadge(quality) {
        if (quality === 'gray') return 'Abgleiter';
        if (quality === 'violet') return 'Klassiker';
        return 'Thermikflug';
    }

    // experience_rating (1-6) direkt.
    function getRating(dayData) {
        if (!dayData) return 0;
        var er = parseInt(dayData.experience_rating, 10);
        if (isFinite(er) && er >= 1) return Math.min(6, er);
        return 0;
    }
    function getSafetyBand(dayData) {
        if (!dayData) return 'no_data';
        var s = dayData.safety_status
            || (dayData.safety && dayData.safety.safety_status);
        if (s === 'safe')        return 'green';
        if (s === 'conditional') return 'amber';
        if (s === 'not_safe')    return 'red';
        return 'no_data';
    }
    // ===== STYLE SYSTEM (RATING_CONCEPT v1.3 §4.3) =====
    // 4 Farben rein nach safety_band — gleiche Hex-Werte wie Spot-Marker.
    // Rot + grau bekommen dashed border (Sperr-Visualisierung).
    function mapRegionStyle(band, _legacyQuality) {
        // Eingang: safety_band (green/amber/red/no_data/violet). violet ist der
        // visuelle Premium-Marker fuer safe + rating=6 (Klassiker, v2.0) — wird vom Aufrufer gesetzt.
        if (band === 'safe')             band = 'green';
        else if (band === 'conditional') band = 'amber';
        else if (band === 'not_safe')    band = 'red';
        else if (band !== 'green' && band !== 'amber' && band !== 'red' && band !== 'violet') band = 'no_data';

        if (band === 'violet') {
            return {
                fill: '#8b5cf6', fillOpacity: 0.42,
                border: '#6d28d9', borderOpacity: 0.75,
                labelColor: '#fff', labelShadow: '-1px -1px 0 rgba(0,0,0,0.85), 1px -1px 0 rgba(0,0,0,0.85), -1px 1px 0 rgba(0,0,0,0.85), 1px 1px 0 rgba(0,0,0,0.85), 0 0 6px rgba(0,0,0,0.5)',
                safetyLabel: 'Top'
            };
        }

        // Alle durchgezogen — User-Wunsch: konsistente Optik
        if (band === 'no_data') {
            return {
                fill: '#9ca3af', fillOpacity: 0.30,
                border: '#6b7280', borderOpacity: 0.5,
                labelColor: '#374151', labelShadow: '-1px -1px 0 #fff, 1px -1px 0 #fff, -1px 1px 0 #fff, 1px 1px 0 #fff, 0 0 6px #fff',
                safetyLabel: 'Keine Daten'
            };
        }
        if (band === 'red') {
            return {
                fill: '#ef4444', fillOpacity: 0.40,
                border: '#991b1b', borderOpacity: 0.7,
                labelColor: '#fff', labelShadow: '-1px -1px 0 rgba(0,0,0,0.85), 1px -1px 0 rgba(0,0,0,0.85), -1px 1px 0 rgba(0,0,0,0.85), 1px 1px 0 rgba(0,0,0,0.85), 0 0 6px rgba(0,0,0,0.5)',
                safetyLabel: 'Nicht fliegbar'
            };
        }
        if (band === 'amber') {
            return {
                fill: '#f59e0b', fillOpacity: 0.42,
                border: '#92400e', borderOpacity: 0.7,
                labelColor: '#fff', labelShadow: '-1px -1px 0 rgba(0,0,0,0.85), 1px -1px 0 rgba(0,0,0,0.85), -1px 1px 0 rgba(0,0,0,0.85), 1px 1px 0 rgba(0,0,0,0.85), 0 0 6px rgba(0,0,0,0.5)',
                safetyLabel: 'Vorsicht'
            };
        }
        // green
        return {
            fill: '#22c55e', fillOpacity: 0.42,
            border: '#15803d', borderOpacity: 0.7,
            labelColor: '#fff', labelShadow: '-1px -1px 0 rgba(0,0,0,0.85), 1px -1px 0 rgba(0,0,0,0.85), -1px 1px 0 rgba(0,0,0,0.85), 1px 1px 0 rgba(0,0,0,0.85), 0 0 6px rgba(0,0,0,0.5)',
            safetyLabel: 'Sicher'
        };
    }

    // ===== MAP INIT =====
    function initMap() {
        map = L.map('regionMap', {
            center: [46.8, 8.3],
            zoom: 7,
            zoomControl: true,
        });

        // Expose the Leaflet map instance under a non-colliding name.
        // `window.regionMap` is otherwise the implicit-global DIV element
        // (id="regionMap"), which has no invalidateSize() — so the resize/
        // tab-switch hooks in regionen.html were silent no-ops, leaving the
        // map blank-white until a later zoom/pan forced a redraw.
        window.regionMap = map;

        // Light map tiles — readable in sunshine
        L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>',
            subdomains: 'abcd',
            maxZoom: 18,
        }).addTo(map);

        labelMarkersGroup = L.layerGroup().addTo(map);

        // Re-render Labels bei Zoom-Wechsel (Labels werden je nach Zoom als Pill, Dot oder gar nicht gezeichnet)
        map.on('zoomend', function () {
            if (currentDate && regionAnalyses) colorRegions(currentDate);
        });

        // Mini-Legende — identisch zur Spot-Karte. Geteiltes Rating-Info-Overlay
        // ueber rating-info.js (window.buildRatingMiniLegend + openRatingInfoOverlay).
        if (typeof window.buildRatingMiniLegend === 'function') {
            window.buildRatingMiniLegend(L, 'bottomleft').addTo(map);
        }

        loadRegions();
    }

    // Dedizierte Pill-Palette: maximiert Kontrast zwischen den 6 (safety × quality) Kombinationen
    // Polygon-Farben (style.border) bleiben dabei unverändert; nur die Label-Pill nutzt diese Tabelle,
    // damit "Bronze safe-Abgleiter" nicht mit den Conditional-Gelbtönen verwechselt wird.
    function getPillBg(safety, quality) {
        if (safety === 'safe') {
            if (quality === 'gray')   return '#78716c'; // stone — Abgleiter/so-so
            if (quality === 'violet') return '#7c3aed'; // violet — Top
            return '#16a34a';                            // green — Gut
        }
        if (safety === 'conditional') {
            if (quality === 'violet') return '#b45309'; // amber-900 — caution Top
            return '#d97706';                            // amber — caution (Gut & Abgleiter)
        }
        if (safety === 'not_safe') return '#b91c1c';
        return '#6b7280'; // no_data fallback
    }

    // Region-Label im Polygon-Centroid: konsistente Glas-Pille (rund) fuer
    // alle Baender — gleicher Aufbau, nur Ring-Farbe + Inhalt unterscheidet
    // sich. Family-Look statt zwei verschiedene Stile.
    function buildRegionLabel(style, badge, band, rating, zoom) {
        var n = (typeof rating === 'number') ? Math.max(0, Math.min(6, rating)) : 0;
        // band kommt direkt vom Aufrufer (safety_band — Single Source of Truth).
        // Legacy-Toleranz fuer Aufrufer, die noch safety_status uebergeben.
        // 'violet' ist Display-Band fuer safe + rating=6 (RATING_ARCHITECTURE v2.0).
        if (band === 'safe')             band = 'green';
        else if (band === 'conditional') band = 'amber';
        else if (band === 'not_safe')    band = 'red';
        else if (band !== 'green' && band !== 'amber' && band !== 'red' && band !== 'violet') band = 'no_data';

        if (band === 'no_data') return null;
        var label;
        if (band === 'red') {
            label = '\u2715';
        } else if (n >= 1) {
            label = String(n);
        } else {
            label = '\u2013';
        }

        // Einheitliche Palette: weisse Glas-Pille + farbiger Ring + farbiger Text.
        // Bei red: gleicher Aufbau, nur roter Ring + rotes Kreuz drin.
        var palette = {
            green:  { ink: '#166534', ring: '#22c55e' },
            amber:  { ink: '#92400e', ring: '#f59e0b' },
            red:    { ink: '#991b1b', ring: '#ef4444' },
            violet: { ink: '#5b21b6', ring: '#8b5cf6' }
        };
        var p = palette[band];
        // Runde Pille (Kreis). Ratings 1-6 sind immer einstellig.
        var size = zoom < 7 ? 30 : zoom < 9 ? 36 : 42;
        var fontSize = Math.round(size * 0.5);
        var html = '<div style="'
            + 'width:' + size + 'px;'
            + 'height:' + size + 'px;'
            + 'display:flex;'
            + 'align-items:center;'
            + 'justify-content:center;'
            + 'background:rgba(255,255,255,0.9);'
            + '-webkit-backdrop-filter:blur(6px);'
            + 'backdrop-filter:blur(6px);'
            + 'border:1.5px solid ' + p.ring + ';'
            + 'border-radius:50%;'
            + 'box-shadow:0 1px 3px rgba(0,0,0,0.12), 0 0 0 4px rgba(255,255,255,0.35);'
            + 'pointer-events:none;'
            + 'font-size:' + fontSize + 'px;'
            + 'font-weight:700;'
            + 'line-height:1;'
            + 'color:' + p.ink + ';'
            + 'font-variant-numeric:tabular-nums;'
            + 'letter-spacing:-0.02em;'
            + '">' + label + '</div>';
        // Container etwas grosser fuer den Halo-Schatten
        var box = size + 10;
        return { html: html, size: [box, box], anchor: [box / 2, box / 2] };
    }
    // Mini-Helper fuer Label-Text (escHtml ist erst spaeter definiert)
    function escHtmlSafe(s) {
        return String(s == null ? '' : s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    // ===== LOAD REGIONS =====
    function loadRegions() {
        fetch('/api/regionen')
            .then(function (resp) { return resp.json(); })
            .then(function (geojson) {
                var regionsLayer = L.geoJSON(geojson, {
                    style: function () {
                        return {
                            color: '#9ca3af',
                            weight: 1,
                            opacity: 0.3,
                            fill: false,
                            fillOpacity: 0,
                            dashArray: '4, 4'
                        };
                    },
                    onEachFeature: function (feature, layer) {
                        var p = feature.properties;
                        var regionId = p.id || p.region;
                        regionLayersByName[regionId] = layer;
                        layer.regionName = p.region;
                        layer.regionFeature = feature;
                        layer.bindTooltip(p.region, {
                            className: 'region-tooltip',
                            direction: 'center',
                            permanent: false,
                            sticky: true,
                        });
                        layer.on('click', function () {
                            if (!currentDate) return;
                            var ra = regionAnalyses ? regionAnalyses[regionId] : null;
                            var dayData = ra ? ra[currentDate] : null;
                            openRegionOverlay(regionId, dayData || { region_name: p.region, safety_status: 'no_data' });
                        });
                    }
                }).addTo(map);

                // Nach dem Laden an alle Regionen anpassen (Gesamtansicht Schweiz)
                try {
                    var bounds = regionsLayer.getBounds();
                    if (bounds && bounds.isValid()) {
                        map.fitBounds(bounds, { padding: [20, 20] });
                    }
                } catch (e) {
                    console.warn('fitBounds fehlgeschlagen:', e);
                }

                // Fallback auf window.currentDate falls setRegionDate noch nicht
                // aufgerufen wurde (Race Condition mit /api/region-analyses-Fetch)
                var d = currentDate || window.currentDate;
                if (regionAnalyses && d) {
                    if (!currentDate) currentDate = d;
                    colorRegions(d);
                }
                // Map-invalidateSize fuer den Fall dass Container erst nach Map-Init
                // sein finales Layout bekommt — sonst rendert Leaflet im falschen Viewport
                setTimeout(function () { try { map.invalidateSize(); } catch (e) {} }, 50);
            })
            .catch(function (err) {
                console.error('Regionen laden fehlgeschlagen:', err);
            });
    }

    // ===== COLOR REGIONS =====
    function colorRegions(dateStr) {
        labelMarkersGroup.clearLayers();

        Object.keys(regionLayersByName).forEach(function (rid) {
            var layer = regionLayersByName[rid];
            layer.setStyle({ fill: false, fillOpacity: 0, color: '#9ca3af', weight: 1, opacity: 0.3, dashArray: '' });
            layer.setTooltipContent(layer.regionName);
        });

        if (!regionAnalyses || !dateStr) return;

        Object.keys(regionLayersByName).forEach(function (rid) {
            var layer = regionLayersByName[rid];
            var ra = regionAnalyses[rid];
            var dayData = ra ? ra[dateStr] : null;

            // Polygon existiert, aber keine Analyse fuer dieses Datum (Cache zu alt /
            // Region neu in CSV / Refresh-Job uebersprungen). No-Data-Fill statt
            // Default-Outline, damit Pilot sofort sieht "Polygon da, Daten fehlen".
            if (!dayData) {
                var ndStyle = mapRegionStyle('no_data', null);
                layer.setStyle({
                    fill: true,
                    fillColor: ndStyle.fill,
                    fillOpacity: ndStyle.fillOpacity,
                    color: ndStyle.border,
                    weight: 1.2,
                    opacity: ndStyle.borderOpacity,
                    dashArray: ''
                });
                var zoom = map.getZoom();
                if (zoom >= 7) {
                    // Polygon-Centroid statt bbox-Center: bei irregulaeren Shapes
                    // (Surselva, Mittelland Zentral) liegt der bbox-Center oft am
                    // Rand oder ausserhalb des Polygons.
                    var ndCenter;
                    try { ndCenter = layer.getCenter(); }
                    catch (e) { ndCenter = layer.getBounds().getCenter(); }
                    var ndHtml;
                    if (zoom < 9) {
                        ndHtml = '<div style="width:10px;height:10px;border-radius:50%;'
                            + 'background:#9ca3af;'
                            + 'box-shadow:0 0 0 2px rgba(255,255,255,0.85),0 1px 3px rgba(0,0,0,0.2);'
                            + '"></div>';
                        labelMarkersGroup.addLayer(L.marker(ndCenter, {
                            icon: L.divIcon({ className: 'region-label', html: ndHtml,
                                iconSize: [12, 12], iconAnchor: [6, 6] }),
                            interactive: false
                        }));
                    } else {
                        ndHtml = '<div style="display:inline-block;'
                            + 'transform:translate(-50%,-50%);'
                            + 'font-size:11px;font-weight:600;color:#fff;'
                            + 'background:#6b7280;padding:3px 10px;border-radius:999px;'
                            + 'white-space:nowrap;'
                            + 'box-shadow:0 1px 3px rgba(0,0,0,0.18),0 0 0 1.5px rgba(255,255,255,0.7);'
                            + '">? Keine Daten</div>';
                        labelMarkersGroup.addLayer(L.marker(ndCenter, {
                            icon: L.divIcon({ className: 'region-label', html: ndHtml,
                                iconSize: [0, 0], iconAnchor: [0, 0] }),
                            interactive: false
                        }));
                    }
                }
                layer.setTooltipContent('<b>' + layer.regionName + '</b>'
                    + '<br><span style="color:#6b7280;">Keine Analyse fuer diesen Tag</span>');
                return;
            }

            // Polygon-Farbe + Label aus safety_band (Decision-Engine-Output,
            // RATING_CONCEPT v1.3 §3.1) — gleiche Quelle wie Briefing-Region-Header
            // und Detail-Pille. Frueher wurde safety_status (LLM-Roh) genutzt, was
            // bei Mismatch zwischen LLM-Aussage und Decision-Engine zu inkonsistenten
            // Karten-Polygonen fuehrte (gruen statt amber).
            var band = getSafetyBand(dayData);
            var rating = getRating(dayData);
            // Premium-Marker: safe + rating=6 (Klassiker) → violett (RATING_ARCHITECTURE v2.0).
            if (band === 'green' && rating >= 6) band = 'violet';
            var style = mapRegionStyle(band);

            // Polygon-Style: solid bei green/amber/violet. baseFillOpacity wird fuer Hover gespeichert.
            // Linearer Dynamikbereich: Rating 1 ~0.19, Rating 3 ~0.38, Rating 6 = 0.65 (experience_rating 1-6).
            var baseOpacity = style.fillOpacity;
            if (rating > 0 && (band === 'green' || band === 'amber' || band === 'violet')) {
                baseOpacity = 0.10 + (rating / 6) * 0.55;
            }
            
            layer._baseFillOpacity = baseOpacity;
            layer.setStyle({
                fill: true,
                fillColor: style.fill,
                fillOpacity: baseOpacity,
                color: style.border,
                weight: 1.5,
                opacity: style.borderOpacity,
                dashArray: ''
            });

            // Hover-Effekt §4.3: fillOpacity auf 0.65 hochziehen
            layer.off('mouseover').off('mouseout');
            layer.on('mouseover', function (ev) {
                ev.target.setStyle({ fillOpacity: 0.65 });
            });
            layer.on('mouseout', function (ev) {
                ev.target.setStyle({ fillOpacity: ev.target._baseFillOpacity || baseOpacity });
            });

            // Rating muss VOR buildRegionLabel berechnet sein — mit `var` waere es
            // zwar hoisted, aber `undefined`, sodass das Label in den En-Dash-Fallback
            // fallen wuerde (Pille zeigt "–" statt Rating-Zahl).
            // (rating wurde oben deklariert fuer intensity)
            // RATING_ARCHITECTURE v2.0: nur experience_rating (1-6).

            // Center-Label — Pille mit Rating-Zahl 1-10 (RATING_CONCEPT v1.4 §4.3).
            // Polygon-Centroid (layer.getCenter) statt bbox-Center: bei irregulaeren
            // Shapes (Surselva, Mittelland Zentral) faellt der bbox-Mittelpunkt
            // sonst an den Rand oder ausserhalb des Polygons.
            var center;
            try { center = layer.getCenter(); }
            catch (e) { center = layer.getBounds().getCenter(); }
            var label = buildRegionLabel(style, layer.regionName, band, rating, map.getZoom());

            if (label) {
                labelMarkersGroup.addLayer(L.marker(center, {
                    icon: L.divIcon({
                        className: 'region-label',
                        html: label.html,
                        iconSize: label.size,
                        iconAnchor: label.anchor
                    }),
                    interactive: false
                }));
            }

            // Tooltip — Zahl + Score (konsistent zu Pille auf Polygon, keine Sterne)
            var tipHtml = '<b>' + layer.regionName + '</b>';
            tipHtml += '<br><span style="color:' + style.labelColor + ';">' + style.safetyLabel + '</span>';
            if (rating > 0) {
                tipHtml += ' · <b>Rating ' + rating + '/6</b>';
            }
            layer.setTooltipContent(tipHtml);
        });
    }

    function loadSpotAnalysesLazy() {
        if (spotAnalyses && spotRegionMap) return Promise.resolve(spotAnalyses);
        if (spotAnalysesPromise) return spotAnalysesPromise;
        // Parallel: Analysen + Spot-Properties (fuer name→region_id-Mapping).
        spotAnalysesPromise = Promise.all([
            fetch('/api/analyses').then(function (r) { return r.json(); }),
            fetch('/api/spots').then(function (r) { return r.json(); })
        ]).then(function (results) {
            spotAnalyses = results[0].spot_analyses || results[0] || {};
            var geo = results[1] || {};
            var features = geo.features || [];
            var map = {};
            features.forEach(function (f) {
                var p = (f && f.properties) || {};
                if (p.name && p.region_id) map[p.name] = p.region_id;
            });
            spotRegionMap = map;
            return spotAnalyses;
        }).catch(function () {
            spotAnalysesPromise = null;
            return {};
        });
        return spotAnalysesPromise;
    }

    // best_window kann ein Satz sein ("Das beste Zeitfenster ist von 10:00 bis
    // 13:00 Uhr.") oder bereits kurz ("10-13"). Wir ziehen die ersten zwei
    // Stundenzahlen als kompakten Range. Falls nichts findbar → ''.
    function shortenWindow(s) {
        if (!s) return '';
        var str = String(s).trim();
        if (!str || str.toLowerCase() === 'keins') return '';
        // Bereits kompakt? (z.B. "10-13", "10–13")
        var m = str.match(/^(\d{1,2})\s*[-–]\s*(\d{1,2})/);
        if (m) return m[1] + '–' + m[2];
        // Aus Satz extrahieren: erste zwei Stundenwerte.
        var nums = str.match(/\b\d{1,2}(?=:\d{2}|\s*Uhr|\s*[-–])/g);
        if (nums && nums.length >= 2) return nums[0] + '–' + nums[1];
        return '';
    }

    // Spot-Strip: horizontale Pill-Reihe mit Rating-Zahl (0-10) je Spot der
    // Region. Wird UNTER dem Meteogramm gerendert (nicht im Aside) — Pilot
    // sieht ohne Aufklappen welche Spots heute gehen. Sortiert nach
    // experience_rating desc. Klick = Deep-Link auf /?spot=<name>.
    function buildSpotStripHtml(rid, dateStr) {
        if (!spotAnalyses || !rid || !dateStr) return '';
        var entries = [];
        for (var name in spotAnalyses) {
            var dayData = spotAnalyses[name] && spotAnalyses[name][dateStr];
            if (!dayData) continue;
            // Region-Zuordnung aus /api/spots (siehe loadSpotAnalysesLazy).
            // Fallback auf record.region_id falls Backend das doch liefert.
            var spotRid = (spotRegionMap && spotRegionMap[name]) || dayData.region_id || '';
            if (spotRid !== rid) continue;
            // Status liegt entweder oben (legacy) oder unter safety.safety_status.
            var ss = dayData.safety_status
                || (dayData.safety && dayData.safety.safety_status)
                || dayData.status;
            if (ss === 'no_data' || ss === 'error' || ss === 'not_safe') continue;
            var rating = getRating(dayData);
            if (rating < 5) continue;
            var band = getSafetyBand(dayData);
            entries.push({
                name: name,
                band: band,
                rating: rating,
                window: shortenWindow(dayData.best_window)
            });
        }
        if (!entries.length) {
            var totalForDay = 0;
            var flyableForDay = 0;
            for (var sn in spotAnalyses) {
                var dd = spotAnalyses[sn] && spotAnalyses[sn][dateStr];
                if (!dd) continue;
                var srid = (spotRegionMap && spotRegionMap[sn]) || dd.region_id || '';
                if (srid !== rid) continue;
                totalForDay++;
                var dss = dd.safety_status || (dd.safety && dd.safety.safety_status) || dd.status;
                if (dss !== 'no_data' && dss !== 'error' && dss !== 'not_safe') flyableForDay++;
            }
            var msg = (totalForDay === 0)
                ? 'Keine Spot-Daten an diesem Tag'
                : (flyableForDay === 0)
                    ? 'Heute kein fliegbarer Spot in dieser Region'
                    : 'Kein Spot mit Rating ≥ 5 in dieser Region';
            return '<div class="region-spot-strip-empty">' + msg + '</div>';
        }
        entries.sort(function (a, b) { return b.rating - a.rating; });

        var html = '<div class="region-spot-strip-header">'
            + '<span class="region-spot-strip-title">Top-Spots</span>'
            + '<span class="region-spot-strip-count">' + entries.length + ' fliegbar</span>'
            + '</div>'
            + '<div class="region-spot-strip-scroll" role="list">';
        entries.forEach(function (e) {
            var bandClass = 'is-' + (e.band || 'green');
            var safetyStr = e.safetyScore !== null ? 'S:' + e.safetyScore : '';
            html += '<button type="button" class="region-spot-pill ' + bandClass + '"'
                + ' role="listitem"'
                + ' data-spot-name="' + escHtml(e.name) + '"'
                + ' aria-label="' + escHtml(e.name) + ', Bewertung ' + e.rating + ' von 6'
                + (safetyStr ? ', Safety ' + e.safetyScore + ' von 100' : '')
                + (e.window ? ', Fenster ' + escHtml(e.window) : '') + '">'
                + '<span class="region-spot-pill-rating">' + e.rating + '</span>'
                + '<span class="region-spot-pill-name">' + escHtml(e.name) + '</span>'
                + (safetyStr ? '<span class="region-spot-pill-safety">' + safetyStr + '</span>' : '')
                + (e.window
                    ? '<span class="region-spot-pill-window">' + escHtml(e.window) + '</span>'
                    : '<span class="region-spot-pill-window">&nbsp;</span>')
                + '</button>';
        });
        html += '</div>';
        return html;
    }

    function renderSpotStrip(rid, dateStr) {
        var stripEl = document.getElementById('regionOverlaySpotStrip');
        if (!stripEl) return;
        if (!spotAnalyses) {
            stripEl.innerHTML = '';
            stripEl.style.display = 'none';
            return;
        }
        var html = buildSpotStripHtml(rid, dateStr);
        if (!html) {
            stripEl.innerHTML = '';
            stripEl.style.display = 'none';
            return;
        }
        stripEl.innerHTML = html;
        stripEl.style.display = '';
    }


    // Track current overlay state for day switching
    var overlayRid = null;

    // Rendert die Analyse-View (shared Modul) plus Region-only Top-Spots-Liste
    // als separaten Block UNTER der Analyse. Aufrufer: openRegionOverlay (initial)
    // und updateOverlayAnalysis (Tag-Wechsel).
    function renderRegionAnalysisInto(bodyEl, dayData, dateStr, rid) {
        if (!bodyEl) return;
        var regionName = (meteogramCache[rid] && meteogramCache[rid].regionName) || rid;
        var data = dayData || { region_name: regionName, safety_status: 'no_data' };

        bodyEl.innerHTML = '';
        var analysisContainer = document.createElement('div');
        bodyEl.appendChild(analysisContainer);
        if (window.AnalysisView && window.AnalysisView.render) {
            window.AnalysisView.render(analysisContainer, data, { dateStr: dateStr, isRegion: true, regionId: rid });
        }
        // Top-Spots wandern aus dem Aside in den eigenen Strip unterhalb des
        // Meteogramms (siehe renderSpotStrip / region-spot-strip).
    }

    function updateOverlayAnalysis(rid, dateStr) {
        var asideEl = document.querySelector('.region-overlay-analysis');
        var ra = regionAnalyses ? regionAnalyses[rid] : null;
        var dayData = ra ? ra[dateStr] : null;
        if (asideEl) {
            var bodyEl = asideEl.querySelector('.meteogram-aside-body') || asideEl;
            renderRegionAnalysisInto(bodyEl, dayData, dateStr, rid);
        }
        renderRegionFeedbackBar(rid, dateStr, dayData);
        // Spot-Strip unter dem Meteogramm aktualisieren.
        var ss = dayData && dayData.safety_status;
        if (ss === 'safe' || ss === 'conditional') {
            renderSpotStrip(rid, dateStr);
        } else {
            var stripEl = document.getElementById('regionOverlaySpotStrip');
            if (stripEl) { stripEl.innerHTML = ''; stripEl.style.display = 'none'; }
        }
    }

    function renderRegionFeedbackBar(rid, dateStr, dayData) {
        var bar = document.getElementById('regionFeedbackBar');
        if (!bar || !rid) return;
        // Widget anzeigen sobald die Region offen ist; nur bei echtem
        // Backend-Error verstecken. 'no_data' oder fehlendes dayData darf
        // das Widget NICHT verbergen — Pilot soll trotzdem Feedback geben
        // können.
        var status = dayData && dayData.safety_status;
        if (status === 'error') {
            bar.innerHTML = '';
            bar.style.display = 'none';
            return;
        }
        var existing = bar.querySelector('[data-fb-mount]');
        if (existing
            && existing.getAttribute('data-fb-target') === rid
            && existing.getAttribute('data-fb-date') === (dateStr || '')) {
            bar.style.display = 'flex';
            return;
        }
        bar.innerHTML = '';
        var mount = document.createElement('div');
        mount.setAttribute('data-fb-mount', '');
        mount.setAttribute('data-fb-type', 'region');
        mount.setAttribute('data-fb-target', rid);
        if (dateStr) mount.setAttribute('data-fb-date', dateStr);
        bar.appendChild(mount);
        bar.style.display = 'flex';
        if (window.Feedback && window.Feedback.scan) window.Feedback.scan(bar);
    }

    function openRegionOverlay(rid, a) {
        if (!overlay) return;
        overlayRid = rid;

        var regionName = a.region_name || rid;
        if (!meteogramCache[rid]) meteogramCache[rid] = {};
        meteogramCache[rid].regionName = regionName;
        overlayTitle.textContent = regionName;

        // Layout matches Spot-Overlay: meteogram first, analysis as
        // collapsible aside below (narrow) / right (wide). Bei schmalem
        // Fenster (<=1199px, identisch zum CSS-Breakpoint in regionen.html)
        // startet das Aside collapsed — der Pilot tippt zum Aufklappen,
        // gleicher Pattern wie Mobile.
        var initialDate = regionActiveDate[rid] || currentDate || window.currentDate || a.date || '';
        var isNarrowOverlay = window.innerWidth <= 1199;
        var asideClass = 'region-overlay-analysis meteogram-aside' + (isNarrowOverlay ? ' collapsed' : '');
        var asideExpanded = isNarrowOverlay ? 'false' : 'true';

        var bodyHtml = '<div class="meteogram-tab-row region-overlay-tab-row">';
        bodyHtml += '<div class="region-overlay-day-tabs" id="regionOverlayDayTabs"></div>';
        bodyHtml += '</div>';
        bodyHtml += '<div class="region-overlay-content">';
        bodyHtml += '<div class="region-overlay-meteogram">';
        bodyHtml += '<div class="region-meteogram-chart" id="regionMeteogramChart"><div class="region-meteogram-loading">Meteogramm wird geladen...</div></div>';
        bodyHtml += '</div>';
        bodyHtml += '<aside class="' + asideClass + '" id="regionAnalysisAside">';
        bodyHtml += '<div class="meteogram-aside-header">';
        bodyHtml += '<span class="meteogram-aside-title">Analyse</span>';
        bodyHtml += '<span class="meteogram-aside-cta">Tippen zum Aufklappen</span>';
        bodyHtml += '<button class="meteogram-aside-toggle" type="button" aria-label="Analyse ein-/ausblenden" aria-expanded="' + asideExpanded + '">&#x25BE;</button>';
        bodyHtml += '</div>';
        bodyHtml += '<div class="meteogram-feedback-bar" id="regionFeedbackBar"></div>';
        bodyHtml += '<div class="meteogram-aside-body"></div>';
        bodyHtml += '<div class="region-overlay-spot-strip" id="regionOverlaySpotStrip" style="display:none"></div>';
        bodyHtml += '</aside>';
        bodyHtml += '</div>';

        overlayBody.innerHTML = bodyHtml;
        showOverlay();

        // Aside toggle (header tap or button) — same pattern as Spot-Overlay.
        var asideEl = document.getElementById('regionAnalysisAside');
        if (asideEl) {
            var asideHeader = asideEl.querySelector('.meteogram-aside-header');
            var asideBtn = asideEl.querySelector('.meteogram-aside-toggle');
            var toggleAside = function (ev) {
                if (ev && ev.target && ev.target.closest && ev.target.closest('.meteogram-aside-body')) return;
                var collapsed = asideEl.classList.toggle('collapsed');
                if (asideBtn) asideBtn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
            };
            if (asideHeader) asideHeader.addEventListener('click', toggleAside);
        }

        // Initiale Analyse + (sobald da) Top-Spots rendern.
        var asideBody = asideEl ? asideEl.querySelector('.meteogram-aside-body') : null;
        renderRegionAnalysisInto(asideBody, a, initialDate, rid);

        // Top-Spots-Strip lazy nachladen — danach Re-Render des Strips.
        loadSpotAnalysesLazy().then(function () {
            if (overlayRid === rid && overlay && overlay.classList.contains('visible')) {
                var d = regionActiveDate[rid] || currentDate || window.currentDate || a.date;
                updateOverlayAnalysis(rid, d);
            }
        });

        // Klick-Delegation auf den Spot-Strip — tippen auf eine Pill oeffnet
        // den Spot via Deep-Link (existing /?spot=<name>-Pattern in map.js).
        var stripEl = document.getElementById('regionOverlaySpotStrip');
        if (stripEl && !stripEl.dataset.clickBound) {
            stripEl.dataset.clickBound = '1';
            stripEl.addEventListener('click', function (ev) {
                var pill = ev.target.closest && ev.target.closest('.region-spot-pill');
                if (!pill) return;
                var name = pill.getAttribute('data-spot-name');
                if (!name) return;
                window.location.href = '/?spot=' + encodeURIComponent(name);
            });
        }

        // Render feedback bar above meteogram
        renderRegionFeedbackBar(rid, initialDate, a);

        // Load meteogram for this region
        loadRegionMeteogram(rid);
    }

    function loadRegionMeteogram(rid) {
        var chartEl = document.getElementById('regionMeteogramChart');

        // Check cache — must contain BOTH wxData AND altData. The cache may already
        // hold a stub object with only `regionName` (pre-set in openRegionOverlay()),
        // which would otherwise short-circuit the fetch and crash renderRegionMeteogram.
        if (meteogramCache[rid] && meteogramCache[rid].wxData && meteogramCache[rid].altData) {
            renderRegionMeteogram(rid, meteogramCache[rid].wxData, meteogramCache[rid].altData, chartEl);
            return;
        }

        // Fetch region weather + altitude-wind in parallel
        Promise.all([
            fetchJson('/api/region-weather/' + encodeURIComponent(rid)),
            fetchJson('/api/region-altitude-wind/' + encodeURIComponent(rid))
        ])
            .then(function (results) {
                var wxData = results[0];
                var altData = results[1];

                if (wxData.error || altData.error) {
                    chartEl.innerHTML = '<div class="region-meteogram-loading">Keine Wetterdaten verfuegbar</div>';
                    return;
                }

                var prevName = meteogramCache[rid] && meteogramCache[rid].regionName;
                meteogramCache[rid] = { wxData: wxData, altData: altData, regionName: prevName };
                renderRegionMeteogram(rid, wxData, altData, chartEl);
            })
            .catch(function (err) {
                chartEl.innerHTML = '<div class="region-meteogram-loading">Fehler: ' + escHtml(err.message) + '</div>';
            });
    }

    function renderRegionMeteogram(rid, wxData, altData, chartEl) {
        if (!wxData.dates || wxData.dates.length === 0) {
            chartEl.innerHTML = '<div class="region-meteogram-loading">Keine Wetterdaten verfuegbar</div>';
            return;
        }

        // Stale-Banner
        if (wxData.stale) {
            var expected = wxData.expected_days || 5;
            var have = (wxData.dates || []).length;
            var lastUpd = wxData.last_updated ? wxData.last_updated.replace('T', ' ').slice(0, 16) : 'unbekannt';
            var bannerContainer = chartEl.parentNode;
            var existingBanner = bannerContainer ? bannerContainer.querySelector('.meteogram-stale-banner') : null;
            if (existingBanner) existingBanner.parentNode.removeChild(existingBanner);
            var bannerDiv = document.createElement('div');
            bannerDiv.className = 'meteogram-stale-banner';
            bannerDiv.innerHTML =
                '<strong>Wetterdaten veraltet:</strong> ' +
                'Nur ' + have + ' von ' + expected + ' Vorhersagetagen verfügbar. ' +
                'Letztes erfolgreiches Update: ' + escHtml(lastUpd) + '.';
            if (bannerContainer) bannerContainer.insertBefore(bannerDiv, chartEl);
        }

        // Find date to display: prefer currentDate if available, else first
        var dates = wxData.dates;
        var activeDate = (currentDate && dates.indexOf(currentDate) >= 0) ? currentDate : dates[0];
        if (rid) regionActiveDate[rid] = activeDate;

        // Build overlay-level day tabs
        var overlayTabsEl = document.getElementById('regionOverlayDayTabs');
        if (overlayTabsEl) {
            overlayTabsEl.innerHTML = '';
            dates.forEach(function (d) {
                var btn = document.createElement('button');
                var parts = Meteogram.formatDayTabParts(d);
                btn.dataset.date = d;
                btn.innerHTML = '<span class="day-name">' + parts.name + '</span><span class="day-date">' + parts.date + '</span>';
                btn.className = 'tab-btn' + (d === activeDate ? ' active' : '');
                btn.addEventListener('click', function () {
                    overlayTabsEl.querySelectorAll('.tab-btn').forEach(function (b) { b.classList.remove('active'); });
                    btn.classList.add('active');
                    if (rid) regionActiveDate[rid] = d;
                    // Update meteogram (oder Debug-View, falls aktiv)
                    if (regionJsonDebugActive) renderRegionJsonDebug();
                    else if (regionHazardDebugActive) renderRegionHazardDebug();
                    else renderMeteogramDay(wxData, altData, d, chartEl);
                    // Update analysis panel
                    updateOverlayAnalysis(rid, d);
                    // Sync navbar
                    window.currentDate = d;
                    var navTabs = document.getElementById('navDayTabs');
                    if (navTabs) {
                        navTabs.querySelectorAll('.navbar-day-btn').forEach(function (b) {
                            b.classList.toggle('active', b.dataset.date === d);
                        });
                    }
                });
                overlayTabsEl.appendChild(btn);
            });
        }

        renderMeteogramDay(wxData, altData, activeDate, chartEl);
    }

    function renderMeteogramDay(wxData, altData, dateStr, chartEl) {
        chartEl.innerHTML = '';

        var wxDay = wxData.data ? wxData.data[dateStr] : null;
        var altDayRaw = altData.data ? altData.data[dateStr] : null;

        // Convert altDayRaw (array of {hour, profiles}) to the format Meteogram expects
        var altDay = null;
        if (altDayRaw && altDayRaw.length > 0) {
            altDay = {
                profiles: altDayRaw.map(function (entry) {
                    var paddedHour = String(entry.hour).padStart(2, '0');
                    return {
                        time: dateStr + 'T' + paddedHour + ':00:00',
                        levels: entry.profiles
                    };
                })
            };
        }

        if (!altDay || !altDay.profiles || altDay.profiles.length === 0) {
            chartEl.innerHTML = '<div class="region-meteogram-loading">Keine Daten fuer diesen Tag</div>';
            return;
        }

        // Regionen haben keinen Startplatz — kein Bodenwind-Row, keine
        // Startplatz-Linie. Der Region-Referenzpunkt ist nur ein geografischer
        // Ankerpunkt, nicht repräsentativ für einzelne Spots der Region.
        // `isRegion: true` sorgt dafür, dass Thermik auch in Zeilen UNTER dem
        // Referenzpunkt gerendert wird (Region-Einzugsgebiet hat Spots auf
        // verschiedenen Höhen, nicht nur am Referenzpunkt).
        Meteogram.renderChart(chartEl, meteogramTooltip, wxDay, altDay, {
            elevation: altData.elevation_m || 0,
            isRegion: true,
            thresholds: wxData.thresholds,
            fitToContainer: true,
        });

        // Wetter-Zeitstempel unter dem Meteogramm
        if (wxData.last_updated) {
            var weatherTs = wxData.last_updated.replace('T', ' ').slice(0, 16);
            var tsDiv = document.createElement('div');
            tsDiv.style.cssText = 'font-size:10px;color:#94a3b8;text-align:right;padding:2px 8px 0;';
            tsDiv.textContent = 'Wetter-Stand: ' + weatherTs;
            chartEl.appendChild(tsDiv);
        }

        // Aktuellen Render-Context speichern + Observer aufsetzen, damit
        // das Chart bei Container-Resize automatisch neu skaliert.
        chartResizeContext = { wxData: wxData, altData: altData, dateStr: dateStr, chartEl: chartEl };
        ensureChartResizeObserver();
    }

    function ensureChartResizeObserver() {
        if (typeof ResizeObserver === 'undefined') return;
        if (chartResizeObserver) return; // already wired
        var target = document.querySelector('.region-overlay-meteogram');
        if (!target) return;
        chartResizeLastWidth = target.clientWidth || 0;
        chartResizeLastHeight = target.clientHeight || 0;
        chartResizeObserver = new ResizeObserver(function (entries) {
            if (!chartResizeContext) return;
            var rect = entries[0] && entries[0].contentRect;
            if (!rect) return;
            var w = rect.width;
            var h = rect.height;
            // Nur re-rendern wenn sich Breite ODER Hoehe spuerbar geaendert hat
            // (>=8px) — vermeidet unnoetige Re-Renders durch Sub-Pixel-Drift
            // und potenzielle Observer-Loops.
            if (Math.abs(w - chartResizeLastWidth) < 8 && Math.abs(h - chartResizeLastHeight) < 8) return;
            chartResizeLastWidth = w;
            chartResizeLastHeight = h;
            clearTimeout(chartResizeTimer);
            chartResizeTimer = setTimeout(function () {
                if (!chartResizeContext) return;
                var ctx = chartResizeContext;
                // chartEl ist im DOM nur sichtbar wenn das Overlay offen ist —
                // sonst nichts tun.
                if (!ctx.chartEl || !document.body.contains(ctx.chartEl)) return;
                renderMeteogramDay(ctx.wxData, ctx.altData, ctx.dateStr, ctx.chartEl);
            }, 120);
        });
        chartResizeObserver.observe(target);
    }

    function teardownChartResizeObserver() {
        if (chartResizeObserver) {
            chartResizeObserver.disconnect();
            chartResizeObserver = null;
        }
        chartResizeContext = null;
        chartResizeLastWidth = 0;
        chartResizeLastHeight = 0;
        clearTimeout(chartResizeTimer);
    }

    function showOverlay() {
        overlay.style.display = 'flex';
        overlay.classList.add('visible');
        if (window._overlayScrollLock) window._overlayScrollLock();
        if (overlayClose) overlayClose.focus();
    }

    function closeRegionOverlay() {
        if (!overlay) return;
        overlay.style.display = 'none';
        overlay.classList.remove('visible');
        teardownChartResizeObserver();
        if (window._overlayScrollUnlock) window._overlayScrollUnlock();
        // Debug-Buttons zuruecksetzen, damit naechste Region wieder Meteogramm zeigt
        var jsonBtn = document.getElementById('regionJsonDebug');
        var hazBtn = document.getElementById('regionHazardDebug');
        if (regionJsonDebugActive) { regionJsonDebugActive = false; if (jsonBtn) jsonBtn.classList.remove('active'); }
        if (regionHazardDebugActive) { regionHazardDebugActive = false; if (hazBtn) hazBtn.classList.remove('active'); }
    }

    // ===== REGION DEBUG VIEWS (JSON + Hazard/Flyability Notes) =====
    function _escDebugHtml(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

    function renderRegionJsonDebug() {
        var chartEl = document.getElementById('regionMeteogramChart');
        if (!chartEl || !overlayRid) return;
        var dateStr = regionActiveDate[overlayRid] || currentDate || window.currentDate;
        var entry = (regionAnalyses && regionAnalyses[overlayRid] && dateStr)
            ? regionAnalyses[overlayRid][dateStr]
            : null;
        chartEl.innerHTML = '<pre style="margin:0;padding:12px;font-size:11px;line-height:1.5;overflow:auto;height:100%;box-sizing:border-box;white-space:pre-wrap;word-break:break-all;color:#e2e8f0;background:#0f172a;border-radius:6px;">'
            + (entry ? _escDebugHtml(JSON.stringify(entry, null, 2)) : '(keine Analyse fuer ' + _escDebugHtml(overlayRid) + ' / ' + _escDebugHtml(dateStr || '?') + ')')
            + '</pre>';
    }

    function renderRegionHazardDebug() {
        var chartEl = document.getElementById('regionMeteogramChart');
        if (!chartEl || !overlayRid) return;
        var dateStr = regionActiveDate[overlayRid] || currentDate || window.currentDate;
        if (!dateStr) {
            chartEl.innerHTML = '<div style="padding:12px;color:#f87171;">Kein Datum aktiv</div>';
            return;
        }
        chartEl.innerHTML = '<div style="padding:12px;color:#94a3b8;font-size:12px;">Lade Debug-Daten…</div>';
        var url = '/api/region-debug/' + encodeURIComponent(overlayRid) + '/' + encodeURIComponent(dateStr);
        fetchJson(url).then(function (d) {
            if (d.error) { chartEl.innerHTML = '<div style="padding:12px;color:#f87171;">' + _escDebugHtml(d.error) + '</div>'; return; }
            var lines = [];
            lines.push('=== SAFETY ===');
            lines.push('Status: ' + (d.safety_status || '?') + '  |  Foehn: ' + (d.foehn_risk || '?'));
            lines.push('');
            lines.push('--- Sub-Ratings (1-10) ---');
            if (d.sub_ratings) Object.keys(d.sub_ratings).forEach(function (k) {
                lines.push('  ' + k.replace('_safety_rating', '').padEnd(15) + ': ' + (d.sub_ratings[k] != null ? d.sub_ratings[k] : '–'));
            });
            lines.push('');
            lines.push('--- Hazard Notes ---');
            if (d.hazard_notes) Object.keys(d.hazard_notes).forEach(function (k) {
                lines.push('  [' + k + '] ' + _escDebugHtml(d.hazard_notes[k] || ''));
            });
            lines.push('');
            if (d.wind_summary) { lines.push('--- Wind Summary ---'); lines.push(_escDebugHtml(d.wind_summary)); lines.push(''); }
            if (d.wind_shear) { lines.push('--- Wind Shear ---'); lines.push(_escDebugHtml(d.wind_shear)); lines.push(''); }
            lines.push('=== FLYABILITY ===');
            lines.push('Experience-Rating: ' + (d.experience_rating != null ? d.experience_rating + '/6' : '?'));
            lines.push('');
            lines.push('--- Flyability Notes ---');
            if (d.flyability_notes) Object.keys(d.flyability_notes).forEach(function (k) {
                lines.push('  [' + k + '] ' + _escDebugHtml(d.flyability_notes[k] || ''));
            });
            lines.push('');
            lines.push('=== DECISIONS APPLIED ===');
            lines.push((d._decisions_applied && d._decisions_applied.length) ? d._decisions_applied.join(', ') : '(keine)');
            chartEl.innerHTML = '<pre style="margin:0;padding:12px;font-size:11px;line-height:1.6;overflow:auto;height:100%;box-sizing:border-box;white-space:pre-wrap;word-break:break-all;color:#e2e8f0;background:#0f172a;border-radius:6px;">'
                + lines.join('\n') + '</pre>';
        }).catch(function (err) {
            chartEl.innerHTML = '<div style="padding:12px;color:#f87171;">Fehler: ' + _escDebugHtml(err.message || err) + '</div>';
        });
    }

    function restoreRegionMeteogramFromCache() {
        if (!overlayRid) return;
        var chartEl = document.getElementById('regionMeteogramChart');
        if (!chartEl) return;
        var cached = meteogramCache[overlayRid];
        if (!cached || !cached.wxData || !cached.altData) {
            // Fallback: kompletter Reload (sollte nach Erstoeffnung selten passieren).
            loadRegionMeteogram(overlayRid);
            return;
        }
        var dateStr = regionActiveDate[overlayRid] || currentDate || window.currentDate || cached.wxData.dates[0];
        renderMeteogramDay(cached.wxData, cached.altData, dateStr, chartEl);
    }

    function parseArray(val) {
        if (!val) return [];
        if (Array.isArray(val)) return val;
        if (typeof val === 'string') {
            try { var p = JSON.parse(val); if (Array.isArray(p)) return p; } catch (e) { /* */ }
            return val ? [val] : [];
        }
        return [];
    }

    function escHtml(str) {
        if (str === null || str === undefined) return '';
        var div = document.createElement('div');
        div.textContent = String(str);
        return div.innerHTML;
    }

    // ===== EVENT LISTENERS =====
    if (overlayClose) overlayClose.addEventListener('click', closeRegionOverlay);

    var regionJsonDebugBtn = document.getElementById('regionJsonDebug');
    if (regionJsonDebugBtn) {
        regionJsonDebugBtn.addEventListener('click', function () {
            regionJsonDebugActive = !regionJsonDebugActive;
            regionJsonDebugBtn.classList.toggle('active', regionJsonDebugActive);
            if (regionHazardDebugActive) {
                regionHazardDebugActive = false;
                var hazBtn = document.getElementById('regionHazardDebug');
                if (hazBtn) hazBtn.classList.remove('active');
            }
            if (regionJsonDebugActive) renderRegionJsonDebug();
            else restoreRegionMeteogramFromCache();
        });
    }

    var regionHazardDebugBtn = document.getElementById('regionHazardDebug');
    if (regionHazardDebugBtn) {
        regionHazardDebugBtn.addEventListener('click', function () {
            regionHazardDebugActive = !regionHazardDebugActive;
            regionHazardDebugBtn.classList.toggle('active', regionHazardDebugActive);
            if (regionJsonDebugActive) {
                regionJsonDebugActive = false;
                if (regionJsonDebugBtn) regionJsonDebugBtn.classList.remove('active');
            }
            if (regionHazardDebugActive) renderRegionHazardDebug();
            else restoreRegionMeteogramFromCache();
        });
    }

    var overlayShare = document.getElementById('regionOverlayShare');
    if (overlayShare) {
        overlayShare.addEventListener('click', function () {
            if (!overlayRid || typeof window.gleitcastShare !== 'function') return;
            var regionName = (meteogramCache[overlayRid] && meteogramCache[overlayRid].regionName) || overlayRid;
            var dateStr = regionActiveDate[overlayRid] || currentDate || window.currentDate;
            var dayIdx = 0;
            if (dateStr) {
                var now = new Date();
                var today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
                var target = new Date(dateStr + 'T12:00:00');
                dayIdx = Math.max(0, Math.round((target - today) / 86400000));
            }
            window.gleitcastShare({
                region_id: overlayRid,
                day_idx: dayIdx,
                title: regionName + ' · Gleitcast',
                text: regionName + ' · Gleitcast Flugwetter',
            });
        });
    }
    if (overlay) overlay.addEventListener('click', function (e) { if (e.target === overlay) closeRegionOverlay(); });
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && overlay && overlay.classList.contains('visible')) closeRegionOverlay();
    });

    // Listen for navbar day changes — update open overlay + map coloring
    window.addEventListener('gleitcast-day-change', function (e) {
        var newDate = e.detail && e.detail.date;
        if (!newDate) return;
        currentDate = newDate;
        colorRegions(newDate);

        // If overlay is open, update day tabs + analysis + charts
        if (overlayRid && overlay && overlay.classList.contains('visible')) {
            updateOverlayAnalysis(overlayRid, newDate);
            if (overlayRid) regionActiveDate[overlayRid] = newDate;
            // Sync overlay day tabs
            var overlayTabsEl = document.getElementById('regionOverlayDayTabs');
            if (overlayTabsEl) {
                overlayTabsEl.querySelectorAll('.tab-btn').forEach(function (b) {
                    b.classList.toggle('active', b.dataset.date === newDate);
                });
            }
            // Re-render meteogram for new day (oder Debug-View, falls aktiv)
            if (regionJsonDebugActive) {
                renderRegionJsonDebug();
            } else if (regionHazardDebugActive) {
                renderRegionHazardDebug();
            } else {
                var cache = meteogramCache[overlayRid];
                if (cache && cache.wxData && cache.altData) {
                    var chartEl = document.getElementById('regionMeteogramChart');
                    if (chartEl) renderMeteogramDay(cache.wxData, cache.altData, newDate, chartEl);
                }
            }
        }
    });

    // ===== GLOBAL API =====
    window.setRegionAnalyses = function (nested) {
        regionAnalyses = nested;
        // Fallback auf window.currentDate (Race-Condition mit Day-Tabs)
        var d = currentDate || window.currentDate;
        if (d) {
            if (!currentDate) currentDate = d;
            colorRegions(d);
        }
    };

    window.setRegionDate = function (dateStr) {
        currentDate = dateStr;
        colorRegions(dateStr);
    };

    initMap();
})();
