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
    var regionActiveDate = {}; // {region_id: dateStr} — last selected day per region overlay

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

    // Derive quality from fly_status/flyability_tier, NOT from flyability_stars (which doesn't exist)
    function getQuality(dayData) {
        var tier = dayData.flyability_tier || dayData.fly_status || '';
        return normalizeFlyTier(tier) || 'green';
    }

    // Short quality label for map display
    function qualityBadge(quality) {
        if (quality === 'gray') return 'Abgleiter';
        if (quality === 'violet') return 'Top';
        return 'Gut';
    }

    // RATING_CONCEPT v1.3: experience_stars bevorzugt, Fallback aus rating
    function getStars(dayData) {
        if (!dayData) return 0;
        var s = dayData.experience_stars;
        if (typeof s === 'number') return Math.max(0, Math.min(5, Math.round(s)));
        // Fallback aus rating (gleiche Schwellen wie email_service._stars_for_spot)
        var r = parseFloat(dayData.rating || 0);
        if (r >= 9.0)  return 5;
        if (r >= 7.6)  return 4;
        if (r >= 6.1)  return 3;
        if (r >= 4.1)  return 2;
        if (r >= 2.1)  return 1;
        return 0;
    }
    function getSafetyBand(dayData) {
        if (!dayData) return 'no_data';
        var b = dayData.safety_band;
        if (b === 'green' || b === 'amber' || b === 'red' || b === 'no_data') return b;
        var s = dayData.safety_status
            || (dayData.safety && dayData.safety.safety_status);
        if (s === 'safe')        return 'green';
        if (s === 'conditional') return 'amber';
        if (s === 'not_safe')    return 'red';
        if (s === 'error')       return 'red';  // konsistent zu mapRegionStyle
        return 'no_data';
    }
    // ===== STYLE SYSTEM (RATING_CONCEPT v1.3 §4.3) =====
    // 4 Farben rein nach safety_band — gleiche Hex-Werte wie Spot-Marker.
    // Rot + grau bekommen dashed border (Sperr-Visualisierung).
    function mapRegionStyle(safety, quality) {
        // Legacy-Signatur beibehalten (quality-Argument wird ignoriert), damit
        // alle Aufrufer unveraendert bleiben. Neue Logik nur ueber safety_band.
        var band = (safety === 'safe')        ? 'green' :
                   (safety === 'conditional') ? 'amber' :
                   (safety === 'not_safe')    ? 'red'   :
                   (safety === 'error')       ? 'red'   : 'no_data';

        // Alle durchgezogen — User-Wunsch: konsistente Optik
        if (band === 'no_data') {
            return {
                fill: '#9ca3af', fillOpacity: 0.30,
                border: '#6b7280', borderOpacity: 0.5,
                labelColor: '#374151', labelShadow: '-1px -1px 0 #fff, 1px -1px 0 #fff, -1px 1px 0 #fff, 1px 1px 0 #fff, 0 0 6px #fff',
                safetyLabel: 'Keine Daten', isError: false
            };
        }
        if (band === 'red') {
            return {
                fill: '#ef4444', fillOpacity: 0.40,
                border: '#991b1b', borderOpacity: 0.7,
                labelColor: '#fff', labelShadow: '-1px -1px 0 rgba(0,0,0,0.85), 1px -1px 0 rgba(0,0,0,0.85), -1px 1px 0 rgba(0,0,0,0.85), 1px 1px 0 rgba(0,0,0,0.85), 0 0 6px rgba(0,0,0,0.5)',
                safetyLabel: 'Nicht fliegbar',
                isError: (safety === 'error')
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
    function buildRegionLabel(style, badge, safety, quality, stars, zoom) {
        var n = (typeof stars === 'number') ? Math.max(0, Math.min(5, stars)) : 0;
        var band = (safety === 'safe')        ? 'green' :
                   (safety === 'conditional') ? 'amber' :
                   (safety === 'not_safe')    ? 'red'   :
                   (safety === 'error')       ? 'red'   : 'no_data';

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
            green: { ink: '#166534', ring: '#22c55e' },
            amber: { ink: '#92400e', ring: '#f59e0b' },
            red:   { ink: '#991b1b', ring: '#ef4444' }
        };
        var p = palette[band];
        // Runde Pille (Kreis): weil Inhalt einstellig (Zahl/Kreuz/Strich)
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

            // safety_status liegt im Cache mal top-level (post-processed),
            // mal nur im 'safety'-Sub-Dict (split-phase, halb-fertig). Beide Pfade tolerieren.
            var safety = dayData.safety_status
                || (dayData.safety && dayData.safety.safety_status)
                || 'no_data';
            var quality = getQuality(dayData);
            var style = mapRegionStyle(safety, quality);

            // Polygon-Style nach §4.3: dashed bei red/no_data, solid bei green/amber.
            // baseFillOpacity wird gespeichert fuer Hover-Effekt.
            var baseOpacity = style.fillOpacity;
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

            // Stars muss VOR buildRegionLabel berechnet sein — mit `var` waere sie
            // zwar hoisted, aber `undefined`, sodass das Label in den En-Dash-Fallback
            // fallen wuerde (Pille zeigt "–" statt Rating-Zahl).
            var stars = getStars(dayData);
            var expScore = (typeof dayData.experience_score === 'number') ? dayData.experience_score : null;

            // Center-Label — Pille mit Rating-Zahl 1-5 (RATING_CONCEPT v1.3 §4.3).
            // Polygon-Centroid (layer.getCenter) statt bbox-Center: bei irregulaeren
            // Shapes (Surselva, Mittelland Zentral) faellt der bbox-Mittelpunkt
            // sonst an den Rand oder ausserhalb des Polygons.
            var center;
            try { center = layer.getCenter(); }
            catch (e) { center = layer.getBounds().getCenter(); }
            var label = buildRegionLabel(style, layer.regionName, safety, quality, stars, map.getZoom());

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
            if (stars > 0) {
                tipHtml += ' · <b>Rating ' + stars + '/5</b>';
                if (expScore !== null) tipHtml += ' (' + expScore + '/100)';
            }
            layer.setTooltipContent(tipHtml);
        });
    }

    function loadSpotAnalysesLazy() {
        if (spotAnalyses) return Promise.resolve(spotAnalyses);
        if (spotAnalysesPromise) return spotAnalysesPromise;
        spotAnalysesPromise = fetch('/api/analyses')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                spotAnalyses = data.spot_analyses || data || {};
                return spotAnalyses;
            })
            .catch(function () { spotAnalysesPromise = null; return {}; });
        return spotAnalysesPromise;
    }

    // Top-Spots-Liste fuer eine Region/Tag (RATING_CONCEPT v1.3 §4.3).
    // Zeigt bis zu 5 Spots der Region (sortiert nach experience_score).
    // Erfordert spotAnalyses geladen — sonst leerer String, wird per Re-Render
    // ergaenzt sobald Daten da sind.
    function buildTopSpotsHtml(rid, dateStr) {
        if (!spotAnalyses || !rid || !dateStr) return '';
        var entries = [];
        for (var name in spotAnalyses) {
            var dayData = spotAnalyses[name] && spotAnalyses[name][dateStr];
            if (!dayData) continue;
            if ((dayData.region_id || '') !== rid) continue;
            var ss = dayData.safety_status;
            if (ss === 'no_data' || ss === 'error') continue;
            var stars = getStars(dayData);
            var band = getSafetyBand(dayData);
            var score = (typeof dayData.experience_score === 'number') ? dayData.experience_score : null;
            entries.push({
                name: name, band: band, stars: stars,
                score: score == null ? -1 : score,
                rating: dayData.rating || 0,
                window: dayData.best_window || ''
            });
        }
        if (!entries.length) return '';
        entries.sort(function (a, b) {
            if (b.score !== a.score) return b.score - a.score;
            return b.rating - a.rating;
        });
        var top = entries.slice(0, 5);
        var palette = {
            green: { ink: '#166534', ring: '#22c55e' },
            amber: { ink: '#92400e', ring: '#f59e0b' },
            red:   { ink: '#991b1b', ring: '#ef4444' }
        };
        var html = '<div class="region-overlay-top-spots" style="margin:14px 12px 6px;">'
            + '<div style="font-size:10px;font-weight:700;color:#64748b;letter-spacing:0.5px;text-transform:uppercase;margin-bottom:6px;">Top-Spots heute</div>';
        top.forEach(function (e) {
            var p = palette[e.band] || palette.green;
            var label = (e.band === 'red') ? '\u2715' : (e.stars >= 1 ? String(e.stars) : '\u2013');
            var scoreTxt = e.score >= 0 ? (e.score + '/100') : '';
            html += '<div style="display:flex;align-items:center;gap:10px;padding:6px 0;border-bottom:1px solid #f1f5f9;">'
                + '<div style="flex-shrink:0;width:26px;height:26px;display:flex;align-items:center;justify-content:center;'
                + 'background:rgba(255,255,255,0.95);border:1.5px solid ' + p.ring + ';border-radius:50%;'
                + 'font-size:13px;font-weight:700;color:' + p.ink + ';line-height:1;font-variant-numeric:tabular-nums;">'
                + label + '</div>'
                + '<div style="flex:1;min-width:0;font-size:12.5px;font-weight:600;color:#0f172a;'
                + 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">' + escHtml(e.name) + '</div>'
                + (e.window ? '<div style="font-size:11px;color:#64748b;font-variant-numeric:tabular-nums;">' + escHtml(e.window) + '</div>' : '')
                + (scoreTxt ? '<div style="font-size:11px;color:' + p.ink + ';font-weight:700;font-variant-numeric:tabular-nums;">' + scoreTxt + '</div>' : '')
                + '</div>';
        });
        html += '</div>';
        return html;
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
            window.AnalysisView.render(analysisContainer, data, { dateStr: dateStr });
        }

        // Top-Spots-Block — nur sinnvoll wenn die Region fliegbar ist UND Spot-
        // Daten geladen sind. Bei not_safe / no_data ueberspringen.
        var ss = data.safety_status;
        if (rid && dateStr && spotAnalyses && (ss === 'safe' || ss === 'conditional')) {
            var topHtml = buildTopSpotsHtml(rid, dateStr);
            if (topHtml) {
                var sep = document.createElement('div');
                sep.innerHTML = topHtml;
                bodyEl.appendChild(sep);
            }
        }
    }

    function updateOverlayAnalysis(rid, dateStr) {
        var asideEl = document.querySelector('.region-overlay-analysis');
        if (!asideEl) return;
        var bodyEl = asideEl.querySelector('.meteogram-aside-body') || asideEl;
        var ra = regionAnalyses ? regionAnalyses[rid] : null;
        var dayData = ra ? ra[dateStr] : null;
        renderRegionAnalysisInto(bodyEl, dayData, dateStr, rid);
        renderRegionFeedbackBar(rid, dateStr, dayData);
    }

    function renderRegionFeedbackBar(rid, dateStr, dayData) {
        var bar = document.getElementById('regionFeedbackBar');
        if (!bar || !rid) return;
        var status = dayData && dayData.safety_status;
        if (!status || status === 'error' || status === 'no_data') {
            bar.innerHTML = '';
            bar.style.display = 'none';
            return;
        }
        bar.style.display = '';
        bar.innerHTML = '';
        var mount = document.createElement('div');
        mount.setAttribute('data-fb-mount', '');
        mount.setAttribute('data-fb-type', 'region');
        mount.setAttribute('data-fb-target', rid);
        if (dateStr) mount.setAttribute('data-fb-date', dateStr);
        bar.appendChild(mount);
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
        // collapsible aside below (mobile) / right (desktop). On mobile the
        // aside starts collapsed so the meteogram is the primary view —
        // identical pattern to map.js.
        var initialDate = regionActiveDate[rid] || currentDate || window.currentDate || a.date || '';
        var isMobile = window.innerWidth <= 640;
        var asideClass = 'region-overlay-analysis meteogram-aside' + (isMobile ? ' collapsed' : '');
        var asideExpanded = isMobile ? 'false' : 'true';

        var bodyHtml = '<div class="region-overlay-day-tabs" id="regionOverlayDayTabs"></div>';
        bodyHtml += '<div class="meteogram-feedback-bar" id="regionFeedbackBar"></div>';
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
        bodyHtml += '<div class="meteogram-aside-body"></div>';
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

        // Top-Spots-Liste lazy nachladen — danach Re-Render damit der Block erscheint.
        loadSpotAnalysesLazy().then(function () {
            if (overlayRid === rid && overlay && overlay.classList.contains('visible')) {
                var d = regionActiveDate[rid] || currentDate || window.currentDate || a.date;
                updateOverlayAnalysis(rid, d);
            }
        });

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
                    // Update meteogram
                    renderMeteogramDay(wxData, altData, d, chartEl);
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
        });

        // Wetter-Zeitstempel unter dem Meteogramm
        if (wxData.last_updated) {
            var weatherTs = wxData.last_updated.replace('T', ' ').slice(0, 16);
            var tsDiv = document.createElement('div');
            tsDiv.style.cssText = 'font-size:10px;color:#94a3b8;text-align:right;padding:2px 8px 0;';
            tsDiv.textContent = 'Wetter-Stand: ' + weatherTs;
            chartEl.appendChild(tsDiv);
        }
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
        if (window._overlayScrollUnlock) window._overlayScrollUnlock();
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
            // Re-render meteogram for new day
            var cache = meteogramCache[overlayRid];
            if (cache && cache.wxData && cache.altData) {
                var chartEl = document.getElementById('regionMeteogramChart');
                if (chartEl) renderMeteogramDay(cache.wxData, cache.altData, newDate, chartEl);
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
