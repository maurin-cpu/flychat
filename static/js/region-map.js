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
        var s = dayData.safety_status;
        if (s === 'safe')        return 'green';
        if (s === 'conditional') return 'amber';
        if (s === 'not_safe')    return 'red';
        return 'no_data';
    }
    function starsGlyph(n) {
        n = Math.max(0, Math.min(5, n || 0));
        var html = '';
        for (var i = 0; i < n; i++) html += '\u2605';
        return html;
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

        if (band === 'no_data') {
            return {
                fill: '#9ca3af', fillOpacity: 0.30,
                border: '#6b7280', borderOpacity: 0.5,
                labelColor: '#374151', labelShadow: '0 0 3px #fff, 0 0 6px #fff',
                showWarning: false, showStripes: false,
                dashed: true,
                safetyLabel: 'Keine Daten', qualityLabel: '', isError: false
            };
        }
        if (band === 'red') {
            return {
                fill: '#ef4444', fillOpacity: 0.40,
                border: '#991b1b', borderOpacity: 0.7,
                labelColor: '#7f1d1d', labelShadow: '0 0 3px #fff, 0 0 6px #fff',
                showWarning: false, showStripes: false,
                dashed: true,
                safetyLabel: 'Nicht fliegbar', qualityLabel: '',
                isError: (safety === 'error')
            };
        }
        if (band === 'amber') {
            return {
                fill: '#f59e0b', fillOpacity: 0.42,
                border: '#92400e', borderOpacity: 0.7,
                labelColor: '#78350f', labelShadow: '0 0 3px #fff, 0 0 6px #fff',
                showWarning: true, showStripes: false,
                dashed: false,
                safetyLabel: 'Vorsicht', qualityLabel: ''
            };
        }
        // green
        return {
            fill: '#22c55e', fillOpacity: 0.42,
            border: '#15803d', borderOpacity: 0.7,
            labelColor: '#14532d', labelShadow: '0 0 3px #fff, 0 0 6px #fff',
            showWarning: false, showStripes: false,
            dashed: false,
            safetyLabel: 'Sicher', qualityLabel: ''
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

        // Legend (collapsible, bottom-left). Standardmaessig eingeklappt —
        // Pilot kann via Klick aufklappen wenn Farben unklar sind.
        var legend = L.control({ position: 'bottomleft' });
        legend.onAdd = function () {
            var div = L.DomUtil.create('div', 'map-legend collapsed');
            div.innerHTML =
                '<button class="map-legend-toggle" aria-label="Legende ein-/ausblenden">Legende</button>' +
                '<div class="map-legend-body">' +
                '<div class="map-legend-item"><span class="map-legend-dot" style="background:#16a34a"></span> Sicher</div>' +
                '<div class="map-legend-item"><span class="map-legend-dot" style="background:#d97706"></span> Vorsicht</div>' +
                '<div class="map-legend-item"><span class="map-legend-dot" style="background:#b91c1c"></span> Nicht fliegbar</div>' +
                '<div class="map-legend-item"><span class="map-legend-dot" style="background:#9ca3af"></span> Keine Daten</div>' +
                '<div class="map-legend-item" style="margin-top:4px;font-size:10.5px;color:#64748b;">' +
                  '\u2605 \u2605 \u2605 = Erlebnis (1\u20135 Sterne)</div>' +
                '</div>';
            var toggle = div.querySelector('.map-legend-toggle');
            toggle.addEventListener('click', function (e) {
                e.stopPropagation();
                div.classList.toggle('collapsed');
            });
            L.DomEvent.disableClickPropagation(div);
            return div;
        };
        legend.addTo(map);

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

    // Region-Label im Polygon-Centroid (RATING_CONCEPT v1.3 §4.3):
    // **Region-Name + Sterne** in Safety-Farbe — kein eigener Marker, weil
    // das eingefaerbte Polygon SELBST schon die Glyphe ist.
    //   Zoom < 7: nichts
    //   Zoom 7-8: Region-Name (kompakt) + Sterne (klein darunter)
    //   Zoom >= 9: Region-Name (groesser) + Sterne (deutlich)
    function buildRegionLabel(style, badge, safety, quality, stars, zoom) {
        if (zoom < 7) return null;
        var n = (typeof stars === 'number') ? Math.max(0, Math.min(5, stars)) : 0;
        var band = (safety === 'safe')        ? 'green' :
                   (safety === 'conditional') ? 'amber' :
                   (safety === 'not_safe')    ? 'red'   : 'no_data';
        var nameSize = zoom < 9 ? 10 : 12;
        var starsSize = zoom < 9 ? 9 : 11;
        var color = style.labelColor;
        var shadow = style.labelShadow;
        // Region-Name + (bei red Kreuz, sonst Sterne)
        var label = '';
        if (band === 'red') {
            label = '\u2715';
            color = '#7f1d1d';
        } else if (n > 0 && band !== 'no_data') {
            label = '';
            for (var i = 0; i < n; i++) label += '\u2605';
        }
        var html = '<div style="'
            + 'display:inline-block;'
            + 'transform:translate(-50%,-50%);'
            + 'text-align:center;'
            + 'pointer-events:none;'
            + 'white-space:nowrap;'
            + 'color:' + color + ';'
            + 'text-shadow:' + shadow + ';'
            + '">'
            + '<div style="font-size:' + nameSize + 'px;font-weight:700;line-height:1.2;letter-spacing:0.01em;">'
            + escHtmlSafe(badge) + '</div>';
        if (label) {
            html += '<div style="font-size:' + starsSize + 'px;font-weight:700;line-height:1.1;letter-spacing:1px;margin-top:1px;">'
                + label + '</div>';
        }
        html += '</div>';
        return { html: html, size: [0, 0], anchor: [0, 0] };
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

                if (regionAnalyses && currentDate) colorRegions(currentDate);
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
            layer.setStyle({ fill: false, fillOpacity: 0, color: '#9ca3af', weight: 1, opacity: 0.3, dashArray: '4, 4' });
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
                    dashArray: '4, 4'
                });
                var zoom = map.getZoom();
                if (zoom >= 7) {
                    var ndCenter = layer.getBounds().getCenter();
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

            var safety = dayData.safety_status;
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
                dashArray: style.dashed ? '4, 4' : ''
            });

            // Hover-Effekt §4.3: fillOpacity auf 0.65 hochziehen
            layer.off('mouseover').off('mouseout');
            layer.on('mouseover', function (ev) {
                ev.target.setStyle({ fillOpacity: 0.65 });
            });
            layer.on('mouseout', function (ev) {
                ev.target.setStyle({ fillOpacity: ev.target._baseFillOpacity || baseOpacity });
            });

            // Center-Label — Region-Name + Sterne (RATING_CONCEPT v1.3 §4.3).
            var bounds = layer.getBounds();
            var center = bounds.getCenter();
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

            // Tooltip — RATING_CONCEPT v1.3: Sterne + Score statt Tier-Wort
            var stars = getStars(dayData);
            var expScore = (typeof dayData.experience_score === 'number') ? dayData.experience_score : null;
            var tipHtml = '<b>' + layer.regionName + '</b>';
            tipHtml += '<br><span style="color:' + style.labelColor + ';">' + style.safetyLabel + '</span>';
            if (stars > 0) {
                tipHtml += ' · <span style="color:' + style.labelColor + ';letter-spacing:1px;">'
                    + starsGlyph(stars) + '</span> ' + stars + (stars === 1 ? ' Stern' : ' Sterne');
                if (expScore !== null) tipHtml += ' (' + expScore + '/100)';
            }
            layer.setTooltipContent(tipHtml);
        });
    }

    // ===== OVERLAY (Pilot Decision Flow) =====
    // Same 5-level hierarchy as meteogram aside:
    //   1. Decision Hero Banner
    //   2. Best Window Highlight
    //   3. Key Metrics Grid
    //   4. Safety Alerts (NO-GO, caution, foehn)
    //   5. AI Insights (expandable)
    function buildAnalysisHtml(a) {
        var safetyStatus = a.safety_status || 'error';
        var quality = getQuality(a);
        var phase2Ok = (safetyStatus === 'safe' || safetyStatus === 'conditional');

        var html = '<div class="mg-analysis-view">';

        // ── Hero-Block (RATING_CONCEPT v1.3 §8.6) — identisch zu Spot-Panel.
        // Ersetzt den alten Decision-Hero-Banner (war doppelt).
        var stars = getStars(a);
        var band = getSafetyBand(a);
        var expScore = (typeof a.experience_score === 'number') ? a.experience_score : null;
        var safScore = (typeof a.safety_score === 'number') ? a.safety_score : null;
        var comfortIdx = (typeof a.comfort_index === 'number') ? a.comfort_index : null;
        // Verdict: nur Status-Wort (analog Spot-Hero). Sterne in der Glyph,
        // Score-Detail in den Pills — keine doppelte Information im Text.
        var verdictTxt = (band === 'green') ? 'Sicher' :
                         (band === 'amber') ? 'Vorsicht' :
                         (band === 'red')   ? 'Nicht fliegbar' : 'Keine Daten';
        var rationale = a.summary || '';
        var rationaleShort = '';
        if (rationale) {
            var firstDot = rationale.indexOf('.');
            rationaleShort = firstDot > 30 ? rationale.substring(0, firstDot + 1) : rationale.substring(0, 140);
        }
        // Glyph: Kreis in Safety-Farbe, weisse Ziffer (Sterne) oder weisses Kreuz (red)
        var glyphSize = 96;
        var gC = glyphSize / 2;
        var gR = glyphSize * 0.32;
        var pal = {
            green:   { fill: '#22c55e', stroke: '#15803d' },
            amber:   { fill: '#f59e0b', stroke: '#92400e' },
            red:     { fill: '#ef4444', stroke: '#991b1b' },
            no_data: { fill: '#9ca3af', stroke: '#6b7280' }
        };
        var pc = pal[band] || pal.no_data;
        var glyphSvg = '<svg width="' + glyphSize + '" height="' + glyphSize + '" viewBox="0 0 ' + glyphSize + ' ' + glyphSize + '" aria-hidden="true">';
        glyphSvg += '<circle cx="' + gC + '" cy="' + gC + '" r="' + gR + '" fill="' + pc.fill + '" stroke="' + pc.stroke + '" stroke-width="3"/>';
        if (band === 'red') {
            var arm = gR * 0.55;
            glyphSvg += '<line x1="' + (gC - arm) + '" y1="' + (gC - arm)
                + '" x2="' + (gC + arm) + '" y2="' + (gC + arm)
                + '" stroke="#fff" stroke-width="6" stroke-linecap="round"/>';
            glyphSvg += '<line x1="' + (gC + arm) + '" y1="' + (gC - arm)
                + '" x2="' + (gC - arm) + '" y2="' + (gC + arm)
                + '" stroke="#fff" stroke-width="6" stroke-linecap="round"/>';
        } else if (stars >= 1) {
            glyphSvg += '<text x="' + gC + '" y="' + (gC + gR * 0.34)
                + '" text-anchor="middle" fill="#fff" font-family="Inter,sans-serif" font-size="'
                + (gR * 0.85).toFixed(1) + '" font-weight="700">' + stars + '</text>';
        }
        glyphSvg += '</svg>';

        html += '<div class="mga-hero ' + band + '">'
            + '<div class="mga-hero-glyph">' + glyphSvg + '</div>'
            + '<div class="mga-hero-text">'
            + '<div class="mga-hero-verdict ' + band + '">' + escHtml(verdictTxt) + '</div>';
        if (rationaleShort) {
            html += '<div class="mga-hero-rationale">' + escHtml(rationaleShort) + '</div>';
        }
        html += '<div class="mga-hero-pills">';
        html += '<span class="mga-hero-pill ' + band + '">Safety ' + band.toUpperCase() + '</span>';
        if (safScore !== null)  html += '<span class="mga-hero-pill">Safety-Score ' + safScore + '/100</span>';
        if (expScore !== null)  html += '<span class="mga-hero-pill">Experience ' + expScore + '/100</span>';
        if (comfortIdx !== null) html += '<span class="mga-hero-pill">Comfort ' + Math.round(comfortIdx) + '/100</span>';
        html += '</div></div></div>';

        // Early return for error / no_data
        if (safetyStatus === 'no_data' || safetyStatus === 'error') {
            var info = a.safety_feedback || a.summary || '';
            if (info) {
                html += '<div style="padding:8px 12px;font-size:12.5px;color:var(--color-text-light);line-height:1.5;">'
                    + escHtml(info) + '</div>';
            }
            html += '</div>';
            return html;
        }

        // ── Level 2: Best Window ──
        var bestWindow = a.safe_window || a.best_window || '';
        if (bestWindow) {
            html += '<div class="mga-window">'
                + '<div>'
                + '<div class="mga-window-label">Bestes Fenster</div>'
                + '<div class="mga-window-time">' + escHtml(bestWindow) + '</div>'
                + '</div>'
                + '</div>';
        }

        // ── Level 4: Safety & Quality Alerts ──
        var noGoReasons = parseArray(a.no_go_reasons);
        var cautionNotes = parseArray(a.caution_notes);
        var flyabilityLimits = parseArray(a.flyability_limits);
        var highlightNotes = parseArray(a.highlights);
        var foehnRisk = (a.foehn_risk || '').toString().toLowerCase();
        var hasFoehnInNotes = cautionNotes.concat(noGoReasons).some(function(t) {
            var s = (t || '').toString().toLowerCase();
            return s.indexOf('föhn') >= 0 || s.indexOf('foehn') >= 0;
        });
        var showFoehnBadge = (foehnRisk && foehnRisk !== 'none') && !hasFoehnInNotes;
        if (noGoReasons.length > 0 || cautionNotes.length > 0 || flyabilityLimits.length > 0 || highlightNotes.length > 0 || showFoehnBadge) {
            html += '<div class="mga-alerts">';
            noGoReasons.forEach(function(r) {
                html += '<div class="mga-alert nogo">'
                    + '<div class="mga-alert-icon">\u2715</div>'
                    + '<div>' + escHtml(r) + '</div></div>';
            });
            cautionNotes.forEach(function(n) {
                html += '<div class="mga-alert caution">'
                    + '<div class="mga-alert-icon">!</div>'
                    + '<div>' + escHtml(n) + '</div></div>';
            });
            if (showFoehnBadge) {
                var foehnLabel = foehnRisk === 'high' ? 'Föhn-Gefahr' : 'Föhn-Vorsicht';
                var foehnCls = foehnRisk === 'high' ? 'nogo' : 'caution';
                var foehnIcon = foehnRisk === 'high' ? '\u2715' : '!';
                html += '<div class="mga-alert ' + foehnCls + '">'
                    + '<div class="mga-alert-icon">' + foehnIcon + '</div>'
                    + '<div>' + escHtml(foehnLabel) + ' (foehn_risk: ' + escHtml(foehnRisk) + ')</div></div>';
            }
            if (phase2Ok) {
                flyabilityLimits.forEach(function(l) {
                    html += '<div class="mga-alert flyability">'
                        + '<div class="mga-alert-icon">\u2193</div>'
                        + '<div>' + escHtml(l) + '</div></div>';
                });
                highlightNotes.forEach(function(h) {
                    html += '<div class="mga-alert positive">'
                        + '<div class="mga-alert-icon">\u2713</div>'
                        + '<div>' + escHtml(h) + '</div></div>';
                });
            }
            html += '</div>';
        }

        // ── Level 3: Key Metrics Grid ──
        html += '<div class="mga-metrics">';
        html += '<div class="mga-metric full-width">'
            + '<div class="mga-metric-label">Wind</div>'
            + '<div class="mga-metric-value">' + escHtml(a.wind_summary || '-') + '</div>'
            + '</div>';

        if (phase2Ok) {
            if (a.flight_type) {
                html += '<div class="mga-metric">'
                    + '<div class="mga-metric-label">Flugtyp</div>'
                    + '<div class="mga-metric-value">' + escHtml(a.flight_type) + '</div>'
                    + '</div>';
            }
            var duration = a.flight_duration_estimate || a.flight_duration || '';
            if (duration) {
                html += '<div class="mga-metric">'
                    + '<div class="mga-metric-label">Dauer</div>'
                    + '<div class="mga-metric-value">' + escHtml(duration) + '</div>'
                    + '</div>';
            }
            if (a.peak_climb_rate) {
                html += '<div class="mga-metric">'
                    + '<div class="mga-metric-label">Peak Thermik</div>'
                    + '<div class="mga-metric-value">' + escHtml(a.peak_climb_rate) + ' m/s</div>'
                    + '</div>';
            }
            if (a.xc_potential) {
                html += '<div class="mga-metric">'
                    + '<div class="mga-metric-label">XC-Potenzial</div>'
                    + '<div class="mga-metric-value">' + escHtml(a.xc_potential) + '</div>'
                    + '</div>';
            }
        }
        html += '</div>';

        // ── Level 5: AI Insights (expandable) ──
        var safetyFeedback = a.safety_feedback || a.summary || '';
        var flyFeedback = phase2Ok ? (a.flyability_feedback || a.recommendation || '') : '';

        if (safetyFeedback || flyFeedback) {
            html += '<div class="mga-insights">';
            if (safetyFeedback) {
                html += '<div class="mga-insight safety open">'
                    + '<button class="mga-insight-toggle" type="button">Sicherheits-Einschätzung</button>'
                    + '<div class="mga-insight-body">' + escHtml(safetyFeedback) + '</div>'
                    + '</div>';
            }
            if (flyFeedback) {
                html += '<div class="mga-insight flyability' + (safetyFeedback ? '' : ' open') + '">'
                    + '<button class="mga-insight-toggle" type="button">Flug-Einschätzung</button>'
                    + '<div class="mga-insight-body">' + escHtml(flyFeedback) + '</div>'
                    + '</div>';
            }
            html += '</div>';
        }

        // Timestamp
        if (a.updated_at) {
            var d = new Date(a.updated_at);
            var ts = d.toLocaleDateString('de-CH') + ' ' + d.toLocaleTimeString('de-CH', {hour:'2-digit', minute:'2-digit'});
            html += '<div class="mg-analysis-datestamp">Analyse: ' + ts + '</div>';
        }

        html += '</div>';
        return html;
    }

    // Track current overlay state for day switching
    var overlayRid = null;

    function updateOverlayAnalysis(rid, dateStr) {
        var asideEl = document.querySelector('.region-overlay-analysis');
        if (!asideEl) return;
        var bodyEl = asideEl.querySelector('.meteogram-aside-body') || asideEl;
        var ra = regionAnalyses ? regionAnalyses[rid] : null;
        var dayData = ra ? ra[dateStr] : null;
        var regionName = (meteogramCache[rid] && meteogramCache[rid].regionName) || rid;
        bodyEl.innerHTML = buildAnalysisHtml(
            dayData || { region_name: regionName, safety_status: 'no_data' }
        );
        // Re-wire expandable insight toggles
        bodyEl.querySelectorAll('.mga-insight-toggle').forEach(function(btn) {
            btn.addEventListener('click', function(e) {
                e.stopPropagation();
                btn.parentElement.classList.toggle('open');
            });
        });
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
        var initialDate = regionActiveDate[rid] || currentDate || window.currentDate || '';
        var analysisHtml = buildAnalysisHtml(a);
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
        bodyHtml += '<div class="meteogram-aside-body">' + analysisHtml + '</div>';
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

        // Wire up expandable insight toggles
        overlayBody.querySelectorAll('.mga-insight-toggle').forEach(function(btn) {
            btn.addEventListener('click', function(e) {
                e.stopPropagation();
                btn.parentElement.classList.toggle('open');
            });
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
        if (currentDate) colorRegions(currentDate);
    };

    window.setRegionDate = function (dateStr) {
        currentDate = dateStr;
        colorRegions(dateStr);
    };

    initMap();
})();
