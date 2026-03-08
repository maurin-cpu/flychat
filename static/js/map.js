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

    // Current meteogram state
    var currentWeather = null;
    var currentAltWind = null;
    var currentDates = [];
    var currentDateIdx = 0;
    var markersByName = {}; // Store marker references

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

        loadSpots();
    }

    // ===== LOAD SPOTS =====
    function loadSpots() {
        fetch('/api/spots')
            .then(function (resp) { return resp.json(); })
            .then(function (geojson) {
                var geoJsonLayer = L.geoJSON(geojson, {
                    pointToLayer: function (feature, latlng) {
                        return L.circleMarker(latlng, {
                            radius: 8,
                            fillColor: '#6366F1',
                            color: '#818CF8',
                            weight: 2,
                            opacity: 1,
                            fillOpacity: 0.8,
                            className: 'spot-marker'
                        });
                    },
                    onEachFeature: function (feature, layer) {
                        var p = feature.properties;
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
    window.highlightSpots = function (names) {
        if (!names || !Array.isArray(names)) {
            // Reset all
            Object.values(markersByName).forEach(function (marker) {
                marker.setStyle({
                    fillColor: '#6366F1',
                    color: '#818CF8',
                    radius: 8,
                    weight: 2
                });
                if (marker.getElement()) {
                    marker.getElement().classList.remove('highlight-pulse');
                }
            });
            return;
        }

        // Reset first
        Object.values(markersByName).forEach(function (marker) {
            marker.setStyle({
                fillColor: '#6366F1',
                color: '#818CF8',
                radius: 8,
                weight: 2
            });
            if (marker.getElement()) {
                marker.getElement().classList.remove('highlight-pulse');
            }
        });

        // Highlight selected
        names.forEach(function (name) {
            var marker = markersByName[name];
            if (marker) {
                marker.setStyle({
                    fillColor: '#10B981', // Emerald Green
                    color: '#FFF',
                    radius: 9,
                    weight: 3
                });
                marker.bringToFront();
                if (marker.getElement()) {
                    marker.getElement().classList.add('highlight-pulse');
                }
            }
        });
    };

    // ===== START =====
    initMap();
})();
