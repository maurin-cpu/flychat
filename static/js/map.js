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
    var openFoehnBtn = document.getElementById('openFoehnBtn');

    // Current meteogram state
    var currentWeather = null;
    var currentAltWind = null;
    var currentDates = [];
    var currentDateIdx = 0;
    var markersByName = {}; // Store marker references
    var currentRefLayer = null; // Store reference points overlay

    var regionColors = [
        '#6366F1', '#8B5CF6', '#EC4899', '#F59E0B', '#10B981',
        '#3B82F6', '#EF4444', '#14B8A6', '#F97316', '#A855F7',
        '#06B6D4', '#84CC16', '#E879F9', '#22D3EE', '#FB923C'
    ];

    // ===== MAP INIT =====
    function initMap() {
        map = L.map('map', {
            center: [46.8, 8.3],
            zoom: 9,
            zoomControl: true,
        });

        L.tileLayer('https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>',
            subdomains: 'abcd',
            maxZoom: 18,
        }).addTo(map);

        loadRegions();
        loadSpots();
    }

    // ===== LOAD REGIONS =====
    function loadRegions() {
        fetch('/api/regionen')
            .then(function (resp) { return resp.json(); })
            .then(function (geojson) {
                L.geoJSON(geojson, {
                    style: function (feature) {
                        var idx = geojson.features.indexOf(feature) % regionColors.length;
                        return {
                            color: regionColors[idx],
                            weight: 1.5,
                            opacity: 0.6,
                            fill: false,
                            fillOpacity: 0,
                            dashArray: '4, 4'
                        };
                    },
                    onEachFeature: function (feature, layer) {
                        var p = feature.properties;
                        layer.bindTooltip(p.region, {
                            className: 'map-tooltip region-tooltip',
                            direction: 'center',
                            permanent: false,
                            sticky: true,
                        });
                    }
                }).addTo(map);
            })
            .catch(function (err) {
                console.error('Regionen laden fehlgeschlagen:', err);
            });
    }

    // ===== DIRECTION PARSER =====
    function getDirAngles(dirStr) {
        if (!dirStr) return null;
        var dirs = {
            'N': 0, 'NNO': 22.5, 'NO': 45, 'ONO': 67.5,
            'O': 90, 'OSO': 112.5, 'SO': 135, 'SSO': 157.5,
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

    // ===== CUSTOM MARKER GENERATOR =====
    function createSpotIcon(props, status, isHighlighted) {
        var color = '#6366F1'; // Default Indigo
        var stroke = '#818CF8';
        if (status === 'orange') {
            color = '#F59E0B';
            stroke = '#FFF';
        } else if (status === 'green') {
            color = '#10B981';
            stroke = '#FFF';
        }

        var radius = isHighlighted ? 10 : 8;
        var strokeWidth = isHighlighted ? 3 : 2;
        var svgSize = 48;
        var center = svgSize / 2;

        var html = '<svg width="' + svgSize + '" height="' + svgSize + '" viewBox="0 0 ' + svgSize + ' ' + svgSize + '" style="overflow: visible;">';

        // 1. Draw Direction Arc if available
        var dirAngles = getDirAngles(props.windrichtung);
        if (dirAngles) {
            // Arc logic
            var arcRadius = radius + 14;
            var startAngle = (dirAngles[0] - 90) * Math.PI / 180; // SVG 0 is East, so -90 for North
            var endAngle = (dirAngles[1] - 90) * Math.PI / 180;

            var x1 = center + arcRadius * Math.cos(startAngle);
            var y1 = center + arcRadius * Math.sin(startAngle);
            var x2 = center + arcRadius * Math.cos(endAngle);
            var y2 = center + arcRadius * Math.sin(endAngle);

            var largeArcFlag = endAngle - startAngle <= Math.PI ? "0" : "1";

            var d = [
                "M", center, center,
                "L", x1, y1,
                "A", arcRadius, arcRadius, 0, largeArcFlag, 1, x2, y2,
                "Z"
            ].join(" ");

            // Subtle colored wedge pointing in the launch direction
            var wedgeColor = status === 'orange' ? 'rgba(245, 158, 11, 0.25)' :
                status === 'green' ? 'rgba(16, 185, 129, 0.25)' :
                    'rgba(99, 102, 241, 0.25)';
            var wedgeStroke = status === 'orange' ? 'rgba(245, 158, 11, 0.5)' :
                status === 'green' ? 'rgba(16, 185, 129, 0.5)' :
                    'rgba(99, 102, 241, 0.5)';

            html += '<path d="' + d + '" fill="' + wedgeColor + '" stroke="' + wedgeStroke + '" stroke-width="1.5" stroke-dasharray="2,2" />';
        }

        // 2. Main Circle Marker
        var pulseClass = isHighlighted ? 'highlight-pulse' : '';
        html += '<circle class="' + pulseClass + '" cx="' + center + '" cy="' + center + '" r="' + radius + '" fill="' + color + '" stroke="' + stroke + '" stroke-width="' + strokeWidth + '" fill-opacity="0.9" />';

        html += '</svg>';

        return L.divIcon({
            html: html,
            className: 'custom-spot-marker',
            iconSize: [svgSize, svgSize],
            iconAnchor: [center, center],
            tooltipAnchor: [0, -radius - 4]
        });
    }

    // ===== LOAD SPOTS =====
    function loadSpots() {
        fetch('/api/spots')
            .then(function (resp) { return resp.json(); })
            .then(function (geojson) {
                var geoJsonLayer = L.geoJSON(geojson, {
                    pointToLayer: function (feature, latlng) {
                        return L.marker(latlng, {
                            icon: createSpotIcon(feature.properties, 'default', false)
                        });
                    },
                    onEachFeature: function (feature, layer) {
                        var p = feature.properties;
                        // Store feature properties on the marker for later updates
                        layer.featureProperties = p;
                        layer.currentStatus = 'default';

                        markersByName[p.name] = layer; // Store reference
                        var tooltip = '<b>' + p.name + '</b><br>' +
                            p.fluggebiet + ' (' + p.region + ')<br>' +
                            p.elevation_m + 'm MSL | Wind: ' + p.windrichtung;
                        layer.bindTooltip(tooltip, {
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
                                        color: '#6366F1',
                                        weight: 1.5,
                                        dashArray: '5, 5',
                                        opacity: 0.6
                                    });
                                    refGroup.addLayer(line);

                                    // 2. Small markers for the grid points
                                    var circle = L.circleMarker(pt, {
                                        radius: 4,
                                        color: '#6366F1',
                                        fillColor: '#1e1e2f',
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
    if (openFoehnBtn) {
        openFoehnBtn.addEventListener('click', function () {
            openFoehn();
        });
    }

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
        // Reset all markers
        Object.values(markersByName).forEach(function (marker) {
            if (marker.currentStatus !== 'default') {
                marker.currentStatus = 'default';
                marker.setIcon(createSpotIcon(marker.featureProperties, 'default', false));
                marker.getElement().style.zIndex = '';
            }
        });

        if (!items || !Array.isArray(items)) return;

        // Highlight selected
        items.forEach(function (item) {
            var name = typeof item === 'string' ? item : item.name;
            var status = typeof item === 'object' ? item.status : 'green';

            var marker = markersByName[name];
            if (marker) {
                marker.currentStatus = status;
                marker.setIcon(createSpotIcon(marker.featureProperties, status, true));

                // Bring to front by setting a high z-index on the element
                if (marker.getElement()) {
                    marker.getElement().style.zIndex = 1000;
                }
            }
        });
    };

    // ===== START =====
    initMap();
})();
