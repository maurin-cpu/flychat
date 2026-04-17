/**
 * Flychat - Map + Meteogram Overlay
 */
(function () {
    'use strict';

    var map;
    var overlay = document.getElementById('meteogramOverlay');
    var chartContainer = document.getElementById('meteogramChart');
    var windTimelineContainer = document.getElementById('windTimelineChart');
    var textViewContainer = document.getElementById('textViewChart');
    var analyseViewContainer = document.getElementById('analyseViewChart');
    var tabsContainer = document.getElementById('meteogramTabs');
    var viewTabsContainer = document.getElementById('meteogramViewTabs');
    var titleEl = document.getElementById('meteogramTitle');
    var infoEl = document.getElementById('meteogramInfo');
    var ratingBadgeEl = document.getElementById('meteogramRatingBadge');
    var ratingValueEl = document.getElementById('meteogramRatingValue');
    var closeBtn = document.getElementById('meteogramClose');
    var tooltipEl = document.getElementById('tooltip');
    var currentView = 'meteogram';  // 'meteogram', 'windtimeline', or 'text' (analyse is permanent aside)
    var asideEl = document.getElementById('meteogramAside');
    var asideToggleBtn = document.getElementById('meteogramAsideToggle');

    // Safer JSON fetch: prüft r.ok + Content-Type, liefert verständliche Fehlermeldung
    // statt "Unexpected token '<'..." wenn Server HTML (z.B. 500-Page) zurückgibt.
    function fetchJson(url) {
        return fetch(url, { headers: { 'Accept': 'application/json' } }).then(function (r) {
            var ctype = (r.headers.get('content-type') || '').toLowerCase();
            return r.text().then(function (txt) {
                if (!r.ok) {
                    var msg;
                    if (ctype.indexOf('application/json') >= 0) {
                        try { msg = (JSON.parse(txt) || {}).error; } catch (e) { msg = null; }
                    }
                    throw new Error(msg || ('HTTP ' + r.status + ' beim Laden der Wetterdaten'));
                }
                if (ctype.indexOf('application/json') < 0) {
                    throw new Error('Server lieferte keine JSON-Daten (vermutlich Fehlerseite). Bitte kurz warten und erneut versuchen.');
                }
                try {
                    return JSON.parse(txt);
                } catch (e) {
                    throw new Error('Antwort konnte nicht gelesen werden: ' + e.message);
                }
            });
        });
    }

    // Current meteogram state
    var currentWeather = null;
    var currentAltWind = null;
    var currentDates = [];
    var currentDateIdx = 0;
    var currentSpotName = '';
    var markersByName = {}; // Store marker references
    var currentRefLayer = null; // Store reference points overlay
    var _iconUid = 0; // Unique ID counter for SVG defs
    var hideNotSafe = true; // Default: dim not_safe spots

    // Phase 1 (Tool-Use): Layers für Isochrone + User-Standort
    var isochroneLayer = null;
    var userLocationMarker = null;

    // ===== MAP INIT =====
    function initMap() {
        map = L.map('map', {
            center: [46.8, 8.3],
            zoom: 9,
            zoomControl: true,
        });

        L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>',
            subdomains: 'abcd',
            maxZoom: 18,
        }).addTo(map);

        // Expose the Leaflet map instance under a non-colliding name.
        // `window.map` is unusable because `<div id="map">` auto-creates an
        // HTML implicit global pointing to the DIV element, which has no
        // invalidateSize() method and would crash sidebar resize handlers.
        window.flychatMap = map;

        loadSpots();

        // Map Legend (collapsible, bottom-left)
        var legend = L.control({ position: 'bottomleft' });
        legend.onAdd = function () {
            var isMobile = window.innerWidth <= 639;
            var div = L.DomUtil.create('div', 'map-legend' + (isMobile ? ' collapsed' : ''));
            div.innerHTML =
                '<button class="map-legend-toggle" aria-label="Legende ein-/ausblenden">Legende</button>' +
                '<div class="map-legend-body">' +
                '<div class="map-legend-item"><span class="map-legend-dot" style="background:var(--color-safety-excellent)"></span> Sicher &amp; Gut</div>' +
                '<div class="map-legend-item"><span class="map-legend-dot" style="background:var(--color-fly-violet)"></span> Top / XC</div>' +
                '<div class="map-legend-item"><span class="map-legend-dot" style="background:var(--color-fly-gray)"></span> Abgleiter</div>' +
                '<div class="map-legend-item"><span class="map-legend-dot" style="background:var(--color-safety-marginal)"></span> Vorsicht</div>' +
                '<div class="map-legend-item"><span class="map-legend-dot" style="background:var(--color-safety-critical)"></span> Nicht sicher</div>' +
                '<div class="map-legend-item"><span class="map-legend-dot" style="background:var(--color-safety-unknown)"></span> Keine Daten</div>' +
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
    }

    // ===== DIRECTION PARSER =====
    function getDirAngles(dirStr) {
        if (!dirStr) return null;
        var dirs = {
            'N': 0, 'NNO': 22.5, 'NNE': 22.5, 'NO': 45, 'NE': 45, 'ONO': 67.5, 'ENE': 67.5,
            'O': 90, 'E': 90, 'OSO': 112.5, 'ESE': 112.5, 'SO': 135, 'SE': 135, 'SSO': 157.5, 'SSE': 157.5,
            'S': 180, 'SSW': 202.5, 'SW': 225, 'WSW': 247.5,
            'W': 270, 'WNW': 292.5, 'NW': 315, 'NNW': 337.5
        };
        var parts = dirStr.toUpperCase().split('-');
        if (parts.length === 1) {
            var a = dirs[parts[0]];
            if (a === undefined) return null;
            return [a - 22.5, a + 22.5];
        } else if (parts.length === 2) {
            var a1 = dirs[parts[0]];
            var a2 = dirs[parts[1]];
            if (a1 === undefined || a2 === undefined) return null;

            // Normalize so the angular difference is <= 180
            if (Math.abs(a1 - a2) > 180) {
                if (a1 < a2) a1 += 360;
                else a2 += 360;
            }

            // Sort so we always draw the shortest arc clockwise
            return [Math.min(a1, a2), Math.max(a1, a2)];
        }
        return null;
    }

    // ===== STYLE SYSTEM (Traffic Light + Intensity, Light Map) =====
    // safety: 'safe' | 'conditional' | 'not_safe' | 'default' | 'no_data' | 'error'
    // quality: 'gray' (bad) | 'green' (good) | 'violet' (legendary)
    function mapSafetyAndQualityToStyle(safety, quality) {
        // Default / unanalyzed
        if (safety === 'default' || safety === 'no_data') {
            return {
                fill: safety === 'no_data' ? '#9ca3af' : '#6b7280',
                stroke: safety === 'no_data' ? '#6b7280' : '#4b5563',
                glow: null, showStripes: false, showWarning: false,
                safetyLabel: safety === 'no_data' ? 'Keine Daten' : '',
                qualityLabel: ''
            };
        }

        // ERROR — analysis failed (e.g. API budget)
        if (safety === 'error') {
            return {
                fill: '#f87171', stroke: '#b91c1c',
                glow: null, showStripes: false, showWarning: false,
                safetyLabel: 'Analyse-Fehler', qualityLabel: ''
            };
        }

        // NOT SAFE — dark red, stripes
        if (safety === 'not_safe') {
            return {
                fill: '#dc2626', stroke: '#991b1b',
                glow: null, showStripes: true, showWarning: false,
                safetyLabel: 'Nicht sicher', qualityLabel: ''
            };
        }

        // SAFE — green traffic light, quality = intensity
        if (safety === 'safe') {
            if (quality === 'gray') return {
                fill: '#B08D57', stroke: '#8A6D3B',
                glow: null, showStripes: false, showWarning: false,
                safetyLabel: 'Sicher', qualityLabel: 'Abgleiter'
            };
            if (quality === 'violet') return {
                // Legendary spots: violet (matches the "Legendär" / "Top" category in the analysis page)
                fill: '#8b5cf6', stroke: '#6d28d9',
                glow: 'rgba(139, 92, 246, 0.45)', showStripes: false, showWarning: false,
                safetyLabel: 'Sicher', qualityLabel: 'Top'
            };
            return { // green = good
                fill: '#22c55e', stroke: '#15803d',
                glow: null, showStripes: false, showWarning: false,
                safetyLabel: 'Sicher', qualityLabel: 'Gut'
            };
        }

        // CONDITIONAL — amber
        if (quality === 'gray') return {
            fill: '#fbbf24', stroke: '#b45309',
            glow: null, showStripes: false, showWarning: true,
            safetyLabel: 'Vorsicht', qualityLabel: 'Abgleiter'
        };
        if (quality === 'violet') return {
            fill: '#d97706', stroke: '#78350f',
            glow: null, showStripes: false, showWarning: true,
            safetyLabel: 'Vorsicht', qualityLabel: 'Gut*'
        };
        return { // green = good
            fill: '#f59e0b', stroke: '#92400e',
            glow: null, showStripes: false, showWarning: true,
            safetyLabel: 'Vorsicht', qualityLabel: 'Gut'
        };
    }

    // ===== CUSTOM MARKER GENERATOR =====
    // safety: 'safe' | 'conditional' | 'not_safe' | 'default' | 'no_data'
    // quality: 'gray' (bad) | 'green' (good) | 'violet' (legendary)
    function createSpotIcon(props, safety, quality, isHighlighted) {
        var uid = ++_iconUid;
        var style = mapSafetyAndQualityToStyle(safety, quality);
        var svgSize = 44;
        var center = svgSize / 2;
        var radius = isHighlighted ? 8 : 6;

        var html = '<svg width="' + svgSize + '" height="' + svgSize + '" viewBox="0 0 ' + svgSize + ' ' + svgSize + '">';

        // Defs: stripes pattern (unique ID per marker)
        if (style.showStripes) {
            html += '<defs><pattern id="st' + uid + '" width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">';
            html += '<line x1="0" y1="0" x2="0" y2="4" stroke="rgba(255,255,255,0.2)" stroke-width="1.5"/>';
            html += '</pattern></defs>';
        }

        // Wind direction sector
        if (props && props.windrichtung) {
            var angles = getDirAngles(props.windrichtung);
            if (angles) {
                var sectorInner = radius + 1;
                var sectorOuter = radius + 9;
                var startRad = (angles[0] - 90) * Math.PI / 180;
                var endRad = (angles[1] - 90) * Math.PI / 180;
                var ix1 = center + sectorInner * Math.cos(startRad);
                var iy1 = center + sectorInner * Math.sin(startRad);
                var ix2 = center + sectorInner * Math.cos(endRad);
                var iy2 = center + sectorInner * Math.sin(endRad);
                var ox1 = center + sectorOuter * Math.cos(startRad);
                var oy1 = center + sectorOuter * Math.sin(startRad);
                var ox2 = center + sectorOuter * Math.cos(endRad);
                var oy2 = center + sectorOuter * Math.sin(endRad);
                var largeArc = (angles[1] - angles[0]) > 180 ? 1 : 0;

                var d = 'M ' + ox1 + ' ' + oy1 +
                    ' A ' + sectorOuter + ' ' + sectorOuter + ' 0 ' + largeArc + ' 1 ' + ox2 + ' ' + oy2 +
                    ' L ' + ix2 + ' ' + iy2 +
                    ' A ' + sectorInner + ' ' + sectorInner + ' 0 ' + largeArc + ' 0 ' + ix1 + ' ' + iy1 + ' Z';

                html += '<path d="' + d + '" fill="' + style.stroke + '" opacity="0.5" />';
            }
        }

        // Glow — ONLY for safe + legendary (Rule 3)
        if (style.glow && (isHighlighted || (safety === 'safe' && quality === 'violet'))) {
            html += '<circle cx="' + center + '" cy="' + center + '" r="' + (radius + 4) + '" fill="' + style.glow + '" />';
            html += '<circle cx="' + center + '" cy="' + center + '" r="' + (radius + 7) + '" fill="' + style.glow.replace('0.45', '0.15') + '" />';
        }

        // Main circle
        html += '<circle cx="' + center + '" cy="' + center + '" r="' + radius + '" fill="' + style.fill + '" stroke="' + style.stroke + '" stroke-width="' + (isHighlighted ? '2' : '1.5') + '" />';

        // Stripes overlay for not_safe (Rule 1 — accessibility pattern)
        if (style.showStripes) {
            html += '<circle cx="' + center + '" cy="' + center + '" r="' + radius + '" fill="url(#st' + uid + ')" />';
        }

        // Warning triangle for conditional (Rule 2 — accessibility icon)
        if (style.showWarning) {
            var tx = center + radius - 1;
            var ty = center - radius + 1;
            html += '<polygon points="' + tx + ',' + (ty - 5) + ' ' + (tx - 4) + ',' + (ty + 3) + ' ' + (tx + 4) + ',' + (ty + 3) + '" fill="#eab308" stroke="#854d0e" stroke-width="0.5" />';
            html += '<text x="' + tx + '" y="' + (ty + 2.5) + '" text-anchor="middle" fill="#854d0e" font-size="6" font-weight="bold" font-family="sans-serif">!</text>';
        }

        html += '</svg>';

        return L.divIcon({
            html: html,
            className: 'custom-spot-marker',
            iconSize: [svgSize, svgSize],
            iconAnchor: [center, center],
            tooltipAnchor: [0, -radius - 6]
        });
    }

    // ===== TOOLTIP BUILDER =====
    function buildTooltipHtml(p, style) {
        var html = '<b>' + p.name + '</b><br>' +
            p.fluggebiet + ' (' + p.region + ')<br>' +
            p.elevation_m + 'm MSL | Wind: ' + p.windrichtung;
        if (!p.has_weather) {
            html += '<br><span style="color:#F59E0B;">Keine Wetterdaten geladen</span>';
        }
        if (style && style.safetyLabel) {
            html += '<br><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:' + style.fill + ';margin-right:4px;vertical-align:middle;"></span>';
            html += '<span style="color:' + style.stroke + ';">' + style.safetyLabel + '</span>';
            if (style.qualityLabel) {
                html += ' &middot; ' + style.qualityLabel;
            }
        }
        return html;
    }

    // ===== LOAD SPOTS =====
    function loadSpots() {
        fetch('/api/spots')
            .then(function (resp) { return resp.json(); })
            .then(function (geojson) {
                var geoJsonLayer = L.geoJSON(geojson, {
                    pointToLayer: function (feature, latlng) {
                        var initSafety = feature.properties.has_weather ? 'default' : 'no_data';
                        return L.marker(latlng, {
                            icon: createSpotIcon(feature.properties, initSafety, 'green', false)
                        });
                    },
                    onEachFeature: function (feature, layer) {
                        var p = feature.properties;
                        layer.featureProperties = p;
                        layer.currentSafety = p.has_weather ? 'default' : 'no_data';
                        layer.currentQuality = 'green';

                        markersByName[p.name] = layer;
                        // On mobile: use popup (tap-friendly); on desktop: tooltip (hover)
                        var isMobile = window.innerWidth <= 600;
                        if (isMobile) {
                            layer.bindPopup(buildTooltipHtml(p, null), {
                                className: 'map-tooltip',
                                offset: [0, -10],
                                closeButton: false,
                                maxWidth: 260,
                            });
                        } else {
                            layer.bindTooltip(buildTooltipHtml(p, null), {
                                className: 'map-tooltip',
                                direction: 'top',
                                offset: [0, -10],
                            });
                        }
                        layer.on('click', function () {
                            openMeteogram(p.name, p);
                        });
                        
                        // Hover Effect for Reference Points
                        layer.on('mouseover', function () {
                            if (SHOW_REFERENCE_POINTS && p.reference_points && p.reference_points.length > 1) {
                                var refGroup = L.layerGroup();
                                var spotPt = p.reference_points[0]; // Point 0 is the spot itself
                                
                                // Draw lines from spot to each reference point
                                p.reference_points.slice(1).forEach(function(pt) {
                                    // 1. Connection Line
                                    var line = L.polyline([spotPt, pt], {
                                        color: '#0369a1',
                                        weight: 1.5,
                                        dashArray: '5, 5',
                                        opacity: 0.5
                                    });
                                    refGroup.addLayer(line);

                                    // 2. Small markers for the grid points
                                    var circle = L.circleMarker(pt, {
                                        radius: 4,
                                        color: '#0369a1',
                                        fillColor: '#fff',
                                        fillOpacity: 1,
                                        weight: 2
                                    });
                                    refGroup.addLayer(circle);
                                });
                                currentRefLayer = refGroup;
                                map.addLayer(currentRefLayer);
                            }
                        });
                        
                        layer.on('mouseout', function () {
                            if (currentRefLayer) {
                                map.removeLayer(currentRefLayer);
                                currentRefLayer = null;
                            }
                        });
                    },
                }).addTo(map);
            })
            .then(openSpotFromUrl)
            .catch(function (err) {
                console.error('Spots laden fehlgeschlagen:', err);
            });
    }

    // Deep-Link: wenn /?spot=<Name> in der URL steht, entsprechenden Spot öffnen
    function openSpotFromUrl() {
        try {
            var params = new URLSearchParams(window.location.search);
            var spotName = params.get('spot');
            if (!spotName) return;
            var marker = markersByName[spotName];
            if (!marker) return;
            if (marker.getLatLng) {
                map.setView(marker.getLatLng(), Math.max(map.getZoom(), 12));
            }
            // Nur Tooltip öffnen, NICHT automatisch Meteogramm laden
            if (marker.openTooltip) marker.openTooltip();
        } catch (e) {
            console.warn('[map] Spot aus URL konnte nicht geöffnet werden:', e);
        }
    }


    // ===== VIEW TABS (Meteogramm / Windverlauf / Text) =====
    // Analyse is permanently shown in the aside panel next to the chart.
    if (viewTabsContainer) {
        viewTabsContainer.querySelectorAll('.view-tab').forEach(function (btn) {
            btn.addEventListener('click', function () {
                var view = btn.dataset.view;
                if (view === currentView) return;
                currentView = view;
                viewTabsContainer.querySelectorAll('.view-tab').forEach(function (b) {
                    b.classList.toggle('active', b.dataset.view === view);
                });
                chartContainer.style.display = 'none';
                if (windTimelineContainer) windTimelineContainer.style.display = 'none';
                if (textViewContainer) textViewContainer.style.display = 'none';

                if (view === 'meteogram') {
                    chartContainer.style.display = '';
                } else if (view === 'windtimeline') {
                    if (windTimelineContainer) windTimelineContainer.style.display = '';
                    renderWindTimeline();
                } else if (view === 'text') {
                    if (textViewContainer) textViewContainer.style.display = '';
                    renderTextView();
                }
            });
        });
    }

    // ===== ANALYSE ASIDE TOGGLE (mobile collapsible) =====
    if (asideToggleBtn && asideEl) {
        asideToggleBtn.addEventListener('click', function () {
            var collapsed = asideEl.classList.toggle('collapsed');
            asideToggleBtn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
        });
    }

    function renderAnalyseView() {
        if (!analyseViewContainer || !currentDates.length) return;
        var dateStr = currentDates[currentDateIdx];
        // Look up analysis data set globally by index.html
        var analysis = null;
        if (window.analysisData
            && window.analysisData[currentSpotName]
            && window.analysisData[currentSpotName][dateStr]) {
            analysis = window.analysisData[currentSpotName][dateStr];
        }
        if (!Meteogram.renderAnalysisView) {
            analyseViewContainer.innerHTML = '<div class="error-state">Analyse-Ansicht nicht verfügbar.</div>';
            return;
        }
        Meteogram.renderAnalysisView(analyseViewContainer, analysis, {
            spotName: currentSpotName,
            dateStr: dateStr,
        });
        renderRatingBadge(analysis);
    }

    function renderRatingBadge(analysis) {
        if (!ratingBadgeEl || !ratingValueEl) return;
        var rating = analysis && analysis.rating;
        var r = (rating === null || rating === undefined) ? NaN : Number(rating);
        var safetyStatus = (analysis && analysis.safety_status) || '';
        var flyStatus = (analysis && analysis.fly_status) || '';
        var isCond = !!(analysis && analysis.is_conditional);
        var condReason = (analysis && analysis.conditional_reason) || '';

        // Reset tier classes
        ratingBadgeEl.classList.remove('tier-green', 'tier-violet', 'tier-not-safe', 'is-conditional');

        if (!isFinite(r) || r <= 0) {
            // No rating or NO-GO with 0.0 → either hide or show NO-GO
            if (safetyStatus === 'not_safe') {
                ratingValueEl.textContent = '0.0';
                ratingBadgeEl.classList.add('tier-not-safe');
                ratingBadgeEl.title = 'NO-GO: ' + ((analysis && analysis.safety && analysis.safety.reasoning) || 'Nicht sicher fliegbar');
                ratingBadgeEl.style.display = '';
            } else {
                ratingBadgeEl.style.display = 'none';
                ratingBadgeEl.title = '';
            }
            return;
        }

        ratingValueEl.textContent = r.toFixed(1);
        if (flyStatus === 'violet') ratingBadgeEl.classList.add('tier-violet');
        else if (flyStatus === 'green') ratingBadgeEl.classList.add('tier-green');
        // gray tier uses default bronze badge styling
        if (isCond) ratingBadgeEl.classList.add('is-conditional');

        var tooltip = 'Rating ' + r.toFixed(1) + ' / 10';
        if (isCond && condReason) tooltip += ' · Bedingt: ' + condReason;
        ratingBadgeEl.title = tooltip;
        ratingBadgeEl.style.display = '';
    }

    function renderTextView() {
        if (!currentWeather || !currentDates.length || !textViewContainer) return;
        var dateStr = currentDates[currentDateIdx];
        var wxDay = currentWeather.data[dateStr] || {};
        var altProfiles = (currentAltWind && currentAltWind.data && currentAltWind.data[dateStr]) || [];
        var altDay = { profiles: [] };
        altProfiles.forEach(function (p) {
            altDay.profiles.push({
                time: dateStr + 'T' + (p.hour < 10 ? '0' : '') + p.hour + ':00:00',
                levels: p.profiles || [],
            });
        });
        Meteogram.renderTextView(textViewContainer, wxDay, altDay, {
            elevation: currentWeather.elevation_m,
            spotName: currentSpotName,
            dateStr: dateStr,
            source: 'flychat-spot',
        });
    }

    function renderWindTimeline() {
        if (!currentAltWind || !currentDates.length || !windTimelineContainer) return;
        var dateStr = currentDates[currentDateIdx];
        var altProfiles = (currentAltWind.data && currentAltWind.data[dateStr]) || [];
        var elevation = currentWeather ? currentWeather.elevation_m : 1000;

        // Create a tooltip element inside the windtimeline container
        var wtTooltip = windTimelineContainer.querySelector('.wt-tooltip');
        if (!wtTooltip) {
            wtTooltip = document.createElement('div');
            wtTooltip.className = 'wt-tooltip tooltip';
            windTimelineContainer.style.position = 'relative';
            windTimelineContainer.appendChild(wtTooltip);
        }

        WindTimeline.render(windTimelineContainer, wtTooltip, altProfiles, {
            elevation_m: elevation,
            dateStr: dateStr,
        });
    }

    // ===== METEOGRAM OVERLAY =====
    function openMeteogram(spotName, props) {
        currentSpotName = spotName;
        titleEl.textContent = spotName;
        infoEl.textContent = props
            ? props.fluggebiet + ' | ' + props.elevation_m + 'm MSL | ' + props.windrichtung
            : '';
        if (ratingBadgeEl) {
            ratingBadgeEl.style.display = 'none';
            ratingBadgeEl.classList.remove('tier-green', 'tier-violet', 'tier-not-safe', 'is-conditional');
        }
        chartContainer.innerHTML = '<div class="error-state">Lade Daten...</div>';
        if (windTimelineContainer) windTimelineContainer.innerHTML = '';
        if (analyseViewContainer) analyseViewContainer.innerHTML = '<div class="mg-analysis-empty">Lade Analyse...</div>';
        if (textViewContainer) textViewContainer.innerHTML = '';
        tabsContainer.innerHTML = '';
        overlay.style.display = 'flex';
        overlay.classList.add('visible');
        if (window._overlayScrollLock) window._overlayScrollLock();
        closeBtn.focus();

        // Reset to meteogram view
        currentView = 'meteogram';
        chartContainer.style.display = '';
        if (windTimelineContainer) windTimelineContainer.style.display = 'none';
        if (textViewContainer) textViewContainer.style.display = 'none';
        // Aside starts expanded on desktop; on mobile user can collapse it.
        if (asideEl) asideEl.classList.remove('collapsed');
        if (viewTabsContainer) {
            viewTabsContainer.querySelectorAll('.view-tab').forEach(function (b) {
                b.classList.toggle('active', b.dataset.view === 'meteogram');
            });
        }

        Promise.all([
            fetchJson('/api/weather/' + encodeURIComponent(spotName)),
            fetchJson('/api/altitude-wind/' + encodeURIComponent(spotName)),
        ])
            .then(function (results) {
                currentWeather = results[0];
                currentAltWind = results[1];

                if (currentWeather.error) {
                    chartContainer.innerHTML = '<div class="error-state">' + currentWeather.error + '</div>';
                    return;
                }
                if (currentAltWind.error) {
                    chartContainer.innerHTML = '<div class="error-state">' + currentAltWind.error + '</div>';
                    return;
                }

                currentDates = currentWeather.dates || [];
                if (currentDates.length === 0) {
                    chartContainer.innerHTML = '<div class="error-state">Keine Wetterdaten verfuegbar.</div>';
                    return;
                }

                // Build day tabs inside the overlay
                var selectedDate = window.currentDate || currentDates[0];
                currentDateIdx = currentDates.indexOf(selectedDate);
                if (currentDateIdx < 0) currentDateIdx = 0;

                if (currentDates.length > 1) {
                    Meteogram.buildTabs(tabsContainer, currentDates, function (dateStr) {
                        var idx = currentDates.indexOf(dateStr);
                        if (idx >= 0 && idx !== currentDateIdx) {
                            currentDateIdx = idx;
                            window.currentDate = dateStr;
                            renderCurrentDay();
                            // Sync floating map day tabs + marker colours
                            syncFloatingDayTabs(dateStr);
                        }
                    });
                    tabsContainer.style.display = '';
                    // buildTabs marks idx 0 active – correct to selected day
                    var allTabs = tabsContainer.querySelectorAll('.tab-btn');
                    allTabs.forEach(function (b, i) { b.classList.toggle('active', i === currentDateIdx); });
                } else {
                    tabsContainer.style.display = 'none';
                }

                renderCurrentDay();
            })
            .catch(function (err) {
                chartContainer.textContent = '';
                var errBox = document.createElement('div');
                errBox.className = 'error-state';
                errBox.appendChild(document.createTextNode(
                    'Fehler: ' + (err && err.message ? err.message : 'Unbekannt')
                ));
                errBox.appendChild(document.createElement('br'));
                var retryBtn = document.createElement('button');
                retryBtn.className = 'btn btn-secondary btn-sm';
                retryBtn.style.marginTop = '12px';
                retryBtn.textContent = 'Erneut versuchen';
                retryBtn.addEventListener('click', function () {
                    errBox.textContent = 'Lade...';
                    openMeteogram(currentSpotName, null);
                });
                errBox.appendChild(retryBtn);
                chartContainer.appendChild(errBox);
            });
    }

    function renderCurrentDay() {
        var dateStr = currentDates[currentDateIdx];
        if (!dateStr) return;

        var wxDay = currentWeather.data[dateStr] || {};
        var altProfiles = (currentAltWind.data && currentAltWind.data[dateStr]) || [];

        // renderChart expects altDay = {profiles: [{time, levels: [...]}]}
        var altDay = { profiles: [] };
        altProfiles.forEach(function (p) {
            altDay.profiles.push({
                time: dateStr + 'T' + (p.hour < 10 ? '0' : '') + p.hour + ':00:00',
                levels: p.profiles || [],
            });
        });

        // Bodenwind (10m, terrain-korrigiert) pro Stunde -> Lookup {time: data}
        // Safety-relevanter Startwind, getrennt vom freien Höhenwind.
        var groundWindByTime = {};
        var gwList = (currentAltWind.ground_wind && currentAltWind.ground_wind[dateStr]) || [];
        gwList.forEach(function (g) {
            var t = dateStr + 'T' + (g.hour < 10 ? '0' : '') + g.hour + ':00:00';
            groundWindByTime[t] = g;
        });

        Meteogram.renderChart(chartContainer, tooltipEl, wxDay, altDay, {
            elevation: currentWeather.elevation_m,
            windrichtung: currentWeather.windrichtung,
            idealWindMax: currentWeather.ideal_wind_max,
            groundWindByTime: groundWindByTime,
        });

        // Wetter-Zeitstempel unter dem Spot-Meteogramm
        var existingTs = chartContainer.querySelector('.meteogram-weather-ts');
        if (existingTs) existingTs.remove();
        if (currentWeather.last_updated) {
            var tsDiv = document.createElement('div');
            tsDiv.className = 'meteogram-weather-ts';
            tsDiv.style.cssText = 'font-size:10px;color:#94a3b8;text-align:right;padding:2px 8px 0;';
            tsDiv.textContent = 'Wetter-Stand: ' + currentWeather.last_updated.replace('T', ' ').slice(0, 16);
            chartContainer.appendChild(tsDiv);
        }

        // Analyse panel is always visible in the aside – refresh on every day change.
        renderAnalyseView();

        // Also update wind timeline / text view if that view is currently active
        if (currentView === 'windtimeline') {
            renderWindTimeline();
        } else if (currentView === 'text') {
            renderTextView();
        }
    }

    function closeMeteogram() {
        overlay.style.display = 'none';
        overlay.classList.remove('visible');
        tooltipEl.classList.remove('visible');
        currentWeather = null;
        currentAltWind = null;
        if (window._overlayScrollUnlock) window._overlayScrollUnlock();
    }

    /** Sync the navbar day tabs + marker colours after an
     *  overlay-internal day switch. */
    function syncFloatingDayTabs(dateStr) {
        var navDayTabs = document.getElementById('navDayTabs');
        if (navDayTabs) {
            navDayTabs.querySelectorAll('.navbar-day-btn').forEach(function (b) {
                b.classList.toggle('active', b.dataset.date === dateStr);
            });
        }
        window.currentDate = dateStr;
        if (window.updateSpotColors && window.analysisData) {
            window.updateSpotColors(window.analysisData, dateStr);
        }
    }

    // Re-render analysis view when analyses are loaded (API fetch after page load)
    window.addEventListener('flychat-analyses-loaded', function () {
        renderAnalyseView();
    });

    // Listen for day changes from the floating map tabs
    window.addEventListener('flychat-day-change', function (e) {
        if (!currentWeather || !currentDates.length) return;
        var newDate = e.detail && e.detail.date;
        if (!newDate) return;
        var idx = currentDates.indexOf(newDate);
        if (idx >= 0 && idx !== currentDateIdx) {
            currentDateIdx = idx;
            renderCurrentDay();
            // Keep overlay day tabs in sync
            tabsContainer.querySelectorAll('.tab-btn').forEach(function (b, i) {
                b.classList.toggle('active', i === idx);
            });
        }
    });

    // ===== EVENT LISTENERS =====
    closeBtn.addEventListener('click', closeMeteogram);

    overlay.addEventListener('click', function (e) {
        if (e.target === overlay) closeMeteogram();
    });

    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && overlay.classList.contains('visible')) {
            closeMeteogram();
        }
    });
    // ===== HIGHLIGHTING =====
    window.highlightSpots = function (items) {
        // Reset all markers to their current analysis state
        Object.values(markersByName).forEach(function (marker) {
            var safety = marker.currentSafety || 'default';
            var quality = marker.currentQuality || 'green';
            marker.setIcon(createSpotIcon(marker.featureProperties, safety, quality, false));
            if (marker.getElement()) marker.getElement().style.zIndex = '';
        });

        if (!items || !Array.isArray(items)) return;

        // Highlight selected
        items.forEach(function (item) {
            var name = typeof item === 'string' ? item : item.name;
            var marker = markersByName[name];
            if (marker) {
                var safety = marker.currentSafety || 'default';
                var quality = marker.currentQuality || 'green';
                marker.setIcon(createSpotIcon(marker.featureProperties, safety, quality, true));
                if (marker.getElement()) marker.getElement().style.zIndex = 1000;
            }
        });
    };

    // ===== SPOT COLORING (from LLM analyses) =====
    // Traffic light: safety = base color, quality = intensity
    window.updateSpotColors = function (analysisData, dateStr) {
        // analysisData: {spot_name: {date_str: {safety_status, fly_status, ...}}}
        if (!analysisData || !dateStr) return;

        Object.keys(markersByName).forEach(function (name) {
            var marker = markersByName[name];
            var spotAnalysis = analysisData[name];
            var dayData = spotAnalysis && spotAnalysis[dateStr];

            if (!dayData) {
                // No analysis for this date (e.g. Sunday beyond forecast) → reset to no_data
                marker.currentSafety = 'no_data';
                marker.currentQuality = 'green';
                marker.setIcon(createSpotIcon(marker.featureProperties, 'no_data', 'green', false));
                var noDataStyle = mapSafetyAndQualityToStyle('no_data', 'green');
                marker.setTooltipContent(buildTooltipHtml(marker.featureProperties, noDataStyle));
                return;
            }

            var safety = dayData.safety_status || 'safe';
            var quality = dayData.fly_status || 'green';

            marker.currentSafety = safety;
            marker.currentQuality = quality;
            marker.setIcon(createSpotIcon(marker.featureProperties, safety, quality, false));

            // Update tooltip with analysis info
            var style = mapSafetyAndQualityToStyle(safety, quality);
            marker.setTooltipContent(buildTooltipHtml(marker.featureProperties, style));
        });
    };

    // ===== REFRESH SPOT MARKERS =====
    window.refreshSpotMarkers = function () {
        fetch('/api/spots')
            .then(function (resp) { return resp.json(); })
            .then(function (geojson) {
                geojson.features.forEach(function (feature) {
                    var p = feature.properties;
                    var marker = markersByName[p.name];
                    if (marker) {
                        marker.featureProperties = p;
                        // Don't override analysis data if it exists
                        if (!marker.currentSafety || marker.currentSafety === 'default' || marker.currentSafety === 'no_data') {
                            var safety = p.has_weather ? 'default' : 'no_data';
                            marker.currentSafety = safety;
                            marker.currentQuality = 'green';
                            marker.setIcon(createSpotIcon(p, safety, 'green', false));
                        }
                        var style = mapSafetyAndQualityToStyle(marker.currentSafety, marker.currentQuality);
                        marker.setTooltipContent(buildTooltipHtml(p, style));
                    }
                });
            })
            .catch(function (err) {
                console.error('Spot-Status Update fehlgeschlagen:', err);
            });
    };

    // ===== PHASE 1: ISOCHRONE + USER LOCATION OVERLAYS =====
    function drawIsochrone(geojson, label) {
        if (!geojson) return;
        // Vorherige Isochrone entfernen
        clearIsochrone();
        try {
            isochroneLayer = L.geoJSON(geojson, {
                style: function () {
                    return {
                        color: '#0369a1',
                        weight: 2,
                        opacity: 0.85,
                        fillColor: '#0ea5e9',
                        fillOpacity: 0.18,
                        dashArray: '4 4'
                    };
                }
            });
            if (label) {
                isochroneLayer.bindTooltip('Erreichbar in ' + label, {
                    sticky: true,
                    className: 'map-tooltip'
                });
            }
            isochroneLayer.addTo(map);

            // Karte auf Isochrone fitten — falls Layer Bounds liefert
            try {
                var bounds = isochroneLayer.getBounds();
                if (bounds && bounds.isValid()) {
                    map.fitBounds(bounds, { padding: [40, 40], maxZoom: 11 });
                }
            } catch (e) { /* fitBounds optional */ }
        } catch (e) {
            console.error('drawIsochrone fehlgeschlagen:', e);
        }
    }

    function clearIsochrone() {
        if (isochroneLayer) {
            try { map.removeLayer(isochroneLayer); } catch (e) { /* ignore */ }
            isochroneLayer = null;
        }
    }

    function setUserLocation(lat, lon, label) {
        if (typeof lat !== 'number' || typeof lon !== 'number') return;
        clearUserLocation();
        try {
            // Custom div-marker im Indigo-Stil
            var html = '<div style="' +
                'width:18px;height:18px;border-radius:50%;' +
                'background:#0369a1;border:3px solid #fff;' +
                'box-shadow:0 0 0 2px #0369a1,0 2px 8px rgba(0,0,0,0.3);' +
                '"></div>';
            var icon = L.divIcon({
                html: html,
                className: 'user-location-marker',
                iconSize: [24, 24],
                iconAnchor: [12, 12],
                tooltipAnchor: [0, -14]
            });
            userLocationMarker = L.marker([lat, lon], { icon: icon, zIndexOffset: 2000 });
            if (label) {
                userLocationMarker.bindTooltip(label, {
                    permanent: false,
                    direction: 'top',
                    className: 'map-tooltip'
                });
            }
            userLocationMarker.addTo(map);
        } catch (e) {
            console.error('setUserLocation fehlgeschlagen:', e);
        }
    }

    function clearUserLocation() {
        if (userLocationMarker) {
            try { map.removeLayer(userLocationMarker); } catch (e) { /* ignore */ }
            userLocationMarker = null;
        }
    }

    function clearAllOverlays() {
        clearIsochrone();
        clearUserLocation();
        if (typeof window.highlightSpots === 'function') {
            window.highlightSpots(null);
        }
    }

    // Zentrale Frontend-API für Tool-Calls aus dem Chat (Phase 1).
    // Strukturierte Namespace statt loser window-Funktionen.
    window.flymap = {
        get map() { return map; },
        get markers() { return markersByName; },
        drawIsochrone: drawIsochrone,
        clearIsochrone: clearIsochrone,
        setUserLocation: setUserLocation,
        clearUserLocation: clearUserLocation,
        highlightSpots: function (items) {
            if (typeof window.highlightSpots === 'function') {
                window.highlightSpots(items);
            }
        },
        clearHighlights: function () {
            if (typeof window.highlightSpots === 'function') {
                window.highlightSpots(null);
            }
        },
        clearAllOverlays: clearAllOverlays,
        fitBounds: function (bounds) {
            if (map && bounds) {
                try { map.fitBounds(bounds); } catch (e) { /* ignore */ }
            }
        }
    };

    // ===== START =====
    initMap();
})();
