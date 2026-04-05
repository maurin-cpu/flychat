/**
 * Flychat - Map + Meteogram Overlay
 */
(function () {
    'use strict';

    var map;
    var overlay = document.getElementById('meteogramOverlay');
    var chartContainer = document.getElementById('meteogramChart');
    var tabsContainer = document.getElementById('meteogramTabs');
    var titleEl = document.getElementById('meteogramTitle');
    var infoEl = document.getElementById('meteogramInfo');
    var closeBtn = document.getElementById('meteogramClose');
    var tooltipEl = document.getElementById('tooltip');

    // Foehn overlay elements
    var foehnOverlay = document.getElementById('foehnOverlay');
    var foehnChart = document.getElementById('foehnChart');
    var foehnCloseBtn = document.getElementById('foehnClose');

    // Current meteogram state
    var currentWeather = null;
    var currentAltWind = null;
    var currentDates = [];
    var currentDateIdx = 0;
    var markersByName = {}; // Store marker references
    var currentRefLayer = null; // Store reference points overlay
    var _iconUid = 0; // Unique ID counter for SVG defs
    var hideNotSafe = true; // Default: dim not_safe spots

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

        loadSpots();
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
    // safety: 'safe' | 'conditional' | 'not_safe' | 'default' | 'no_data'
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
                fill: '#86efac', stroke: '#16a34a',
                glow: null, showStripes: false, showWarning: false,
                safetyLabel: 'Sicher', qualityLabel: 'Schwach'
            };
            if (quality === 'violet') return {
                fill: '#15803d', stroke: '#14532d',
                glow: 'rgba(22, 163, 74, 0.4)', showStripes: false, showWarning: false,
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
            safetyLabel: 'Vorsicht', qualityLabel: 'Schwach'
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
                        layer.bindTooltip(buildTooltipHtml(p, null), {
                            className: 'map-tooltip',
                            direction: 'top',
                            offset: [0, -10],
                        });
                        layer.on('click', function () {
                            openMeteogram(p.name, p);
                        });
                        
                        // Hover Effect for Reference Points
                        layer.on('mouseover', function () {
                            if (p.reference_points && p.reference_points.length > 1) {
                                var refGroup = L.layerGroup();
                                var spotPt = p.reference_points[0]; // Point 0 is the spot itself
                                
                                // Draw lines from spot to each reference point
                                p.reference_points.slice(1).forEach(function(pt) {
                                    // 1. Connection Line
                                    var line = L.polyline([spotPt, pt], {
                                        color: '#4f46e5',
                                        weight: 1.5,
                                        dashArray: '5, 5',
                                        opacity: 0.5
                                    });
                                    refGroup.addLayer(line);

                                    // 2. Small markers for the grid points
                                    var circle = L.circleMarker(pt, {
                                        radius: 4,
                                        color: '#4f46e5',
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
            .catch(function (err) {
                console.error('Spots laden fehlgeschlagen:', err);
            });
    }


    // ===== METEOGRAM OVERLAY =====
    function openMeteogram(spotName, props) {
        titleEl.textContent = spotName;
        infoEl.textContent = props
            ? props.fluggebiet + ' | ' + props.elevation_m + 'm MSL | ' + props.windrichtung
            : '';
        chartContainer.innerHTML = '<div class="error-state">Lade Daten...</div>';
        tabsContainer.innerHTML = '';
        overlay.style.display = 'flex';
        overlay.classList.add('visible');

        Promise.all([
            fetch('/api/weather/' + encodeURIComponent(spotName)).then(function (r) { return r.json(); }),
            fetch('/api/altitude-wind/' + encodeURIComponent(spotName)).then(function (r) { return r.json(); }),
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

                // Build tabs - buildTabs callback receives date string, not index
                Meteogram.buildTabs(tabsContainer, currentDates, function (dateStr) {
                    currentDateIdx = currentDates.indexOf(dateStr);
                    if (currentDateIdx < 0) currentDateIdx = 0;
                    renderCurrentDay();
                });

                // Render first day
                currentDateIdx = 0;
                renderCurrentDay();
            })
            .catch(function (err) {
                chartContainer.innerHTML = '<div class="error-state">Fehler: ' + err.message + '</div>';
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

        Meteogram.renderChart(chartContainer, tooltipEl, wxDay, altDay, {
            elevation: currentWeather.elevation_m,
        });
    }

    function closeMeteogram() {
        overlay.style.display = 'none';
        overlay.classList.remove('visible');
        tooltipEl.classList.remove('visible');
        currentWeather = null;
        currentAltWind = null;
    }

    // ===== FOEHN OVERLAY =====
    function openFoehn() {
        foehnChart.innerHTML = '<div class="error-state">Lade Föhn-Daten...</div>';
        foehnOverlay.style.display = 'flex';
        foehnOverlay.classList.add('visible');

        fetch('/api/foehn')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (data.error) {
                    foehnChart.innerHTML = '<div class="error-state">' + data.error + '</div>';
                    return;
                }
                var dates = data.dates || [];
                if (dates.length === 0) {
                    foehnChart.innerHTML = '<div class="error-state">Keine Föhn-Daten verfügbar.</div>';
                    return;
                }

                // Flatten all days into one continuous array
                var allData = [];
                dates.forEach(function (dateStr) {
                    var dayArr = data.data[dateStr] || [];
                    dayArr.forEach(function (entry) { allData.push(entry); });
                });

                FoehnDiagram.renderChart(foehnChart, tooltipEl, allData, data.thresholds);
            })
            .catch(function (err) {
                foehnChart.innerHTML = '<div class="error-state">Fehler: ' + err.message + '</div>';
            });
    }

    function closeFoehn() {
        foehnOverlay.style.display = 'none';
        foehnOverlay.classList.remove('visible');
        tooltipEl.classList.remove('visible');
    }

    // ===== EVENT LISTENERS =====
    closeBtn.addEventListener('click', closeMeteogram);

    overlay.addEventListener('click', function (e) {
        if (e.target === overlay) closeMeteogram();
    });

    // Foehn overlay events
    foehnCloseBtn.addEventListener('click', closeFoehn);
    foehnOverlay.addEventListener('click', function (e) {
        if (e.target === foehnOverlay) closeFoehn();
    });

    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') {
            if (foehnOverlay.classList.contains('visible')) {
                closeFoehn();
            } else if (overlay.classList.contains('visible')) {
                closeMeteogram();
            }
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
            if (!spotAnalysis) return;
            var dayData = spotAnalysis[dateStr];
            if (!dayData) return;

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

    // ===== START =====
    initMap();

    window.openFoehn = openFoehn;

    try {
        if (new URLSearchParams(window.location.search).get('foehn') === '1') {
            openFoehn();
            history.replaceState({}, '', window.location.pathname);
        }
    } catch (e) { /* ignore */ }
})();
