/* Admin Reference Point Editor — Leaflet map + drag/edit/save flow.
 *
 * Modes:
 *   - 'regions': edit 7 reference_points per region (saved to GeoJSON)
 *   - 'spots':   edit lat/lon per spot (saved to CSV)
 */
(function () {
    'use strict';

    var state = {
        mode: 'regions',
        regions: [],          // loaded from /api/admin/refpoints/regions
        spots: [],            // loaded from /api/admin/refpoints/spots
        currentRegion: null,  // selected region object
        currentSpot: null,    // selected spot object
        points: [],           // working copy of region refpoints [[lat,lon],...] (length 7)
        baseline: [],         // last-saved snapshot for reset
        spotCoords: null,     // {lat, lon} working copy for selected spot
        spotBaseline: null,
        dirty: false,
    };

    var map = null;
    var polygonLayer = null;
    var refMarkers = [];        // 7 draggable markers (region mode)
    var spotMarkers = [];       // all-spot overview markers (spot mode)
    var selectedSpotMarker = null; // bigger draggable marker for selected spot

    // ---------------- Map init ----------------
    function initMap() {
        map = L.map('rp-map', {
            center: [46.8, 8.3],
            zoom: 8,
            maxZoom: 18,
            minZoom: 6,
            attributionControl: true,
        });

        L.tileLayer('https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png', {
            attribution: '© OpenStreetMap, © CARTO',
            subdomains: 'abcd', maxZoom: 19,
        }).addTo(map);

        L.tileLayer('https://services.arcgisonline.com/ArcGIS/rest/services/Elevation/World_Hillshade/MapServer/tile/{z}/{y}/{x}', {
            attribution: 'Hillshade: Esri', opacity: 0.35, maxZoom: 19,
        }).addTo(map);

        L.tileLayer('https://{s}.basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}{r}.png', {
            attribution: '', subdomains: 'abcd', maxZoom: 19, pane: 'shadowPane',
        }).addTo(map);

        // OSM Peaks/Pässe/Sättel — geteiltes Modul (osm-peaks-layer.js).
        // Steuerbar via Admin-UI: config.SHOW_OSM_PEAKS → window.SHOW_OSM_PEAKS.
        if (window.SHOW_OSM_PEAKS && window.GleitcastOsmPeaks) {
            window.GleitcastOsmPeaks.attach(map);
        }

        // Niederschlags-Referenzpunkte (16 pro Region) — im Admin-Editor
        // IMMER eingeblendet (read-only), damit der Editor die Verteilung
        // sieht, auch wenn das globale SHOW_PRECIP_REFPOINTS Flag aus ist.
        if (window.GleitcastPrecipRefpoints) {
            window.GleitcastPrecipRefpoints.attach(map);
        }
    }

    // ---------------- Fetch ----------------
    function fetchJSON(url, opts) {
        return fetch(url, opts || {}).then(function (r) {
            return r.json().then(function (data) {
                if (!r.ok) throw new Error(data && data.error || ('HTTP ' + r.status));
                return data;
            });
        });
    }

    function loadAll() {
        setHint('Lade Regionen & Spots…');
        Promise.all([
            fetchJSON('/api/admin/refpoints/regions'),
            fetchJSON('/api/admin/refpoints/spots'),
        ]).then(function (results) {
            state.regions = results[0].regions || [];
            state.spots = results[1].spots || [];
            populateRegionFilter();
            renderSelector();
            renderPanel();
            updateButtons();
            setHint(state.regions.length + ' Regionen · ' + state.spots.length + ' Spots');
        }).catch(function (e) {
            flashError('Laden fehlgeschlagen: ' + e.message);
        });
    }

    // ---------------- UI population ----------------
    function populateRegionFilter() {
        var filter = document.getElementById('rp-region-filter');
        filter.innerHTML = '<option value="">Alle Regionen</option>';
        var names = {};
        state.spots.forEach(function (s) { names[s.region] = true; });
        Object.keys(names).sort().forEach(function (n) {
            var o = document.createElement('option');
            o.value = n; o.textContent = n; filter.appendChild(o);
        });
    }

    function renderSelector() {
        var sel = document.getElementById('rp-selector');
        sel.innerHTML = '';
        var placeholder = document.createElement('option');
        placeholder.value = '';
        placeholder.textContent = state.mode === 'regions' ? '— Region wählen —' : '— Spot wählen —';
        sel.appendChild(placeholder);

        if (state.mode === 'regions') {
            state.regions.forEach(function (r) {
                var o = document.createElement('option');
                o.value = r.id; o.textContent = r.name;
                sel.appendChild(o);
            });
        } else {
            var regionFilter = document.getElementById('rp-region-filter').value;
            state.spots
                .filter(function (s) { return !regionFilter || s.region === regionFilter; })
                .forEach(function (s) {
                    var o = document.createElement('option');
                    o.value = s.id;
                    o.textContent = s.region + ' · ' + s.fluggebiet + ' · ' + s.site_name;
                    sel.appendChild(o);
                });
        }
    }

    // ---------------- Mode toggle ----------------
    function setMode(mode) {
        if (state.dirty && !confirm('Ungespeicherte Änderungen verwerfen?')) return;
        state.mode = mode;
        state.currentRegion = null;
        state.currentSpot = null;
        state.points = [];
        state.baseline = [];
        state.spotCoords = null;
        state.spotBaseline = null;
        state.dirty = false;

        document.getElementById('rp-mode-regions').classList.toggle('is-active', mode === 'regions');
        document.getElementById('rp-mode-spots').classList.toggle('is-active', mode === 'spots');
        document.getElementById('rp-mode-regions').setAttribute('aria-selected', mode === 'regions');
        document.getElementById('rp-mode-spots').setAttribute('aria-selected', mode === 'spots');
        document.getElementById('rp-region-filter').style.display = mode === 'spots' ? '' : 'none';

        clearMapLayers();
        if (mode === 'spots') renderAllSpotMarkers();
        renderSelector();
        renderPanel();
        updateButtons();
    }

    function clearMapLayers() {
        if (polygonLayer) { map.removeLayer(polygonLayer); polygonLayer = null; }
        refMarkers.forEach(function (m) { map.removeLayer(m); }); refMarkers = [];
        spotMarkers.forEach(function (m) { map.removeLayer(m); }); spotMarkers = [];
        if (selectedSpotMarker) { map.removeLayer(selectedSpotMarker); selectedSpotMarker = null; }
    }

    // ---------------- Region mode ----------------
    function selectRegion(regionId) {
        var region = state.regions.find(function (r) { return r.id === regionId; });
        if (!region) return;
        state.currentRegion = region;
        state.points = (region.reference_points || []).map(function (p) { return [Number(p[0]), Number(p[1])]; });
        state.baseline = JSON.parse(JSON.stringify(state.points));
        state.dirty = false;

        clearMapLayers();
        renderRegionPolygon(region);
        renderRefMarkers();
        renderPanel();
        updateButtons();

        if (polygonLayer) {
            try { map.fitBounds(polygonLayer.getBounds(), { padding: [40, 40] }); }
            catch (e) { /* ignore */ }
        }
    }

    function renderRegionPolygon(region) {
        if (!region.polygon) return;
        polygonLayer = L.geoJSON(region.polygon, {
            style: { color: '#0369a1', weight: 2, fill: false, dashArray: '4 4' },
        }).addTo(map);
    }

    function renderRefMarkers() {
        refMarkers.forEach(function (m) { map.removeLayer(m); }); refMarkers = [];
        state.points.forEach(function (pt, idx) {
            var icon = L.divIcon({
                className: '',
                html: '<div class="rp-refmarker-label">' + (idx + 1) + '</div>',
                iconSize: [22, 22], iconAnchor: [11, 11],
            });
            var marker = L.marker([pt[0], pt[1]], { draggable: true, icon: icon, title: 'Punkt ' + (idx + 1) });
            marker.on('drag dragend', function (ev) {
                var ll = ev.target.getLatLng();
                state.points[idx] = [Number(ll.lat.toFixed(5)), Number(ll.lng.toFixed(5))];
                state.dirty = true;
                syncInputsFromState();
                updateButtons();
            });
            marker.addTo(map);
            refMarkers.push(marker);
        });
    }

    function syncInputsFromState() {
        if (state.mode === 'regions') {
            for (var i = 0; i < 7; i++) {
                var latIn = document.getElementById('rp-lat-' + i);
                var lonIn = document.getElementById('rp-lon-' + i);
                if (latIn && lonIn && state.points[i]) {
                    latIn.value = state.points[i][0].toFixed(4);
                    lonIn.value = state.points[i][1].toFixed(4);
                }
            }
        } else if (state.spotCoords) {
            var latS = document.getElementById('rp-spot-lat');
            var lonS = document.getElementById('rp-spot-lon');
            if (latS) latS.value = state.spotCoords.lat.toFixed(4);
            if (lonS) lonS.value = state.spotCoords.lon.toFixed(4);
        }
    }

    // ---------------- Spot mode ----------------
    function renderAllSpotMarkers() {
        spotMarkers.forEach(function (m) { map.removeLayer(m); }); spotMarkers = [];
        var regionFilter = document.getElementById('rp-region-filter').value;
        var list = state.spots.filter(function (s) { return !regionFilter || s.region === regionFilter; });
        list.forEach(function (s) {
            var m = L.circleMarker([s.lat, s.lon], {
                radius: 4, color: '#0369a1', weight: 1,
                fillColor: '#7dd3fc', fillOpacity: 0.7,
            });
            m.bindTooltip(s.region + ' · ' + s.fluggebiet + ' · ' + s.site_name, { direction: 'top' });
            m.on('click', function () { selectSpot(s.id); });
            m.addTo(map);
            spotMarkers.push(m);
        });
        if (list.length > 0) {
            try {
                var bounds = L.latLngBounds(list.map(function (s) { return [s.lat, s.lon]; }));
                map.fitBounds(bounds, { padding: [40, 40] });
            } catch (e) { /* ignore */ }
        }
    }

    function selectSpot(spotId) {
        var spot = state.spots.find(function (s) { return s.id === spotId; });
        if (!spot) return;
        state.currentSpot = spot;
        state.spotCoords = { lat: Number(spot.lat), lon: Number(spot.lon) };
        state.spotBaseline = { lat: Number(spot.lat), lon: Number(spot.lon) };
        state.dirty = false;

        if (selectedSpotMarker) { map.removeLayer(selectedSpotMarker); selectedSpotMarker = null; }
        var icon = L.divIcon({
            className: '',
            html: '<div style="width:18px;height:18px;border-radius:50%;background:#ef4444;border:3px solid #fff;box-shadow:0 1px 4px rgba(0,0,0,0.5);"></div>',
            iconSize: [18, 18], iconAnchor: [9, 9],
        });
        selectedSpotMarker = L.marker([spot.lat, spot.lon], { draggable: true, icon: icon, zIndexOffset: 1000 });
        selectedSpotMarker.on('drag dragend', function (ev) {
            var ll = ev.target.getLatLng();
            state.spotCoords = { lat: Number(ll.lat.toFixed(5)), lon: Number(ll.lng.toFixed(5)) };
            state.dirty = true;
            syncInputsFromState();
            updateButtons();
        });
        selectedSpotMarker.addTo(map);
        map.setView([spot.lat, spot.lon], 14);

        // sync selector
        var sel = document.getElementById('rp-selector');
        if (sel.value !== spot.id) sel.value = spot.id;

        renderPanel();
        updateButtons();
    }

    // ---------------- Panel rendering ----------------
    function renderPanel() {
        var panel = document.getElementById('rp-panel-content');
        var actions = document.getElementById('rp-actions');
        if (state.mode === 'regions') {
            if (!state.currentRegion) {
                panel.className = 'rp-empty';
                panel.textContent = 'Region oben auswählen, um die 7 Reference-Points zu editieren.';
                actions.style.display = 'none';
                return;
            }
            panel.className = '';
            var html = '<h3>' + escapeHtml(state.currentRegion.name) + '</h3>';
            html += '<div class="rp-hint">7 Referenzpunkte. Marker ziehen, Lat/Lon-Felder editieren oder 7 Zeilen <code>lat, lon</code> in ein Lat-Feld pasten.</div>';
            html += '<details class="rp-bulk">';
            html += '<summary>📋 Bulk-Paste (7 Zeilen <code>lat, lon</code>)</summary>';
            html += '<textarea id="rp-bulk-text" rows="8" placeholder="46.9700, 7.4900&#10;47.1300, 7.2500&#10;... (7 Zeilen)"></textarea>';
            html += '<div class="rp-bulk-actions">';
            html += '<button type="button" class="rp-btn rp-btn--secondary" id="rp-bulk-apply">Übernehmen</button>';
            html += '<span id="rp-bulk-msg" class="rp-bulk-msg"></span>';
            html += '</div>';
            html += '</details>';
            for (var i = 0; i < 7; i++) {
                var p = state.points[i] || [0, 0];
                html += '<div class="rp-point-row" data-idx="' + i + '">';
                html += '<div class="rp-idx">' + (i + 1) + '</div>';
                html += '<input type="number" step="0.0001" id="rp-lat-' + i + '" data-idx="' + i + '" data-axis="lat" value="' + p[0].toFixed(4) + '" aria-label="Punkt ' + (i + 1) + ' Latitude">';
                html += '<input type="number" step="0.0001" id="rp-lon-' + i + '" data-idx="' + i + '" data-axis="lon" value="' + p[1].toFixed(4) + '" aria-label="Punkt ' + (i + 1) + ' Longitude">';
                html += '</div>';
            }
            panel.innerHTML = html;
            attachInputListeners();
            attachBulkPasteListener();
            actions.style.display = 'flex';
        } else {
            if (!state.currentSpot) {
                panel.className = 'rp-empty';
                panel.textContent = 'Spot auf der Karte anklicken oder oben auswählen.';
                actions.style.display = 'none';
                return;
            }
            panel.className = '';
            var s = state.currentSpot;
            var html2 = '<h3>' + escapeHtml(s.site_name) + '</h3>';
            html2 += '<div class="rp-spot-info">';
            html2 += '<strong>' + escapeHtml(s.region) + ' · ' + escapeHtml(s.fluggebiet) + '</strong>';
            html2 += 'Höhe: ' + (s.elevation_m || '?') + ' m · Wind: ' + escapeHtml(s.windrichtung || '–');
            html2 += '<br>Analyse-Region: ' + escapeHtml(s.analyse_region || '–');
            html2 += '</div>';
            html2 += '<div class="rp-hint">Marker auf der Karte ziehen oder Lat/Lon-Felder bearbeiten.</div>';
            html2 += '<div class="rp-point-row">';
            html2 += '<div class="rp-idx">📍</div>';
            html2 += '<input type="number" step="0.0001" id="rp-spot-lat" value="' + state.spotCoords.lat.toFixed(4) + '" aria-label="Latitude">';
            html2 += '<input type="number" step="0.0001" id="rp-spot-lon" value="' + state.spotCoords.lon.toFixed(4) + '" aria-label="Longitude">';
            html2 += '</div>';
            panel.innerHTML = html2;
            attachSpotInputListeners();
            actions.style.display = 'flex';
        }
    }

    function attachInputListeners() {
        var inputs = document.querySelectorAll('#rp-panel-content input[data-idx]');
        inputs.forEach(function (inp) {
            inp.addEventListener('input', function () {
                var idx = Number(inp.dataset.idx);
                var axis = inp.dataset.axis;
                var val = parseFloat(inp.value);
                if (isNaN(val)) return;
                if (!state.points[idx]) state.points[idx] = [0, 0];
                if (axis === 'lat') state.points[idx][0] = val;
                else state.points[idx][1] = val;
                state.dirty = true;
                if (refMarkers[idx]) refMarkers[idx].setLatLng([state.points[idx][0], state.points[idx][1]]);
                updateButtons();
            });
            inp.addEventListener('paste', function (ev) {
                var text = (ev.clipboardData || window.clipboardData).getData('text');
                var pts = parseBulkCoords(text);
                if (pts.length >= 2) {
                    ev.preventDefault();
                    var startIdx = Number(inp.dataset.idx) || 0;
                    applyBulkPoints(pts, startIdx);
                    showBulkMsg(pts.length + ' Punkte ab Zeile ' + (startIdx + 1) + ' übernommen', 'ok');
                }
            });
        });
    }

    // ---------------- Bulk paste ----------------
    function parseBulkCoords(text) {
        // Akzeptiert pro Zeile zwei Zahlen, getrennt durch Komma/Semikolon/Whitespace.
        // Filtert Leerzeilen, Code-Fences (```), und Kommentar-Suffixe (# ...).
        if (!text) return [];
        var lines = text.split(/\r?\n/);
        var pts = [];
        for (var i = 0; i < lines.length; i++) {
            var raw = lines[i].split('#')[0].trim();
            if (!raw || raw.startsWith('```')) continue;
            // entferne führende/anhängende eckige Klammern (Python-Listen-Form)
            raw = raw.replace(/^\[|\],?$/g, '').trim();
            var m = raw.match(/^(-?\d+(?:\.\d+)?)\s*[,;\s]\s*(-?\d+(?:\.\d+)?)/);
            if (!m) continue;
            var lat = parseFloat(m[1]);
            var lon = parseFloat(m[2]);
            if (isNaN(lat) || isNaN(lon)) continue;
            // CH-Plausibilität (gleiche Bounds wie web.py _validate_latlon)
            if (lat < 45.0 || lat > 48.5 || lon < 5.0 || lon > 11.5) continue;
            pts.push([lat, lon]);
            if (pts.length >= 7) break;
        }
        return pts;
    }

    function applyBulkPoints(points, startIdx) {
        if (!points || !points.length) return;
        var start = Math.max(0, Math.min(6, startIdx | 0));
        for (var i = 0; i < points.length && (start + i) < 7; i++) {
            state.points[start + i] = [points[i][0], points[i][1]];
        }
        state.dirty = true;
        renderRefMarkers();
        syncInputsFromState();
        updateButtons();
    }

    function attachBulkPasteListener() {
        var btn = document.getElementById('rp-bulk-apply');
        var ta = document.getElementById('rp-bulk-text');
        if (!btn || !ta) return;
        btn.addEventListener('click', function () {
            var pts = parseBulkCoords(ta.value);
            if (pts.length === 0) {
                showBulkMsg('Keine gültigen Koordinaten erkannt (erwartet: lat, lon — eine pro Zeile)', 'err');
                return;
            }
            if (pts.length < 7) {
                showBulkMsg('Nur ' + pts.length + ' von 7 Zeilen erkannt — Rest bleibt unverändert', 'warn');
            } else {
                showBulkMsg('Alle 7 Punkte übernommen — Speichern nicht vergessen', 'ok');
            }
            applyBulkPoints(pts, 0);
        });
    }

    function showBulkMsg(text, kind) {
        var el = document.getElementById('rp-bulk-msg');
        if (!el) return;
        el.textContent = text;
        el.className = 'rp-bulk-msg rp-bulk-msg--' + (kind || 'ok');
    }

    function attachSpotInputListeners() {
        var latIn = document.getElementById('rp-spot-lat');
        var lonIn = document.getElementById('rp-spot-lon');
        function handler() {
            var lat = parseFloat(latIn.value);
            var lon = parseFloat(lonIn.value);
            if (isNaN(lat) || isNaN(lon)) return;
            state.spotCoords = { lat: lat, lon: lon };
            state.dirty = true;
            if (selectedSpotMarker) selectedSpotMarker.setLatLng([lat, lon]);
            updateButtons();
        }
        latIn.addEventListener('input', handler);
        lonIn.addEventListener('input', handler);
    }

    // ---------------- Buttons ----------------
    function updateButtons() {
        var saveBtn = document.getElementById('rp-save');
        var resetBtn = document.getElementById('rp-reset');
        var dirty = document.getElementById('rp-dirty');
        var canEdit = (state.mode === 'regions' && state.currentRegion)
                   || (state.mode === 'spots' && state.currentSpot);
        saveBtn.disabled = !(canEdit && state.dirty);
        resetBtn.disabled = !(canEdit && state.dirty);
        dirty.style.display = state.dirty ? 'block' : 'none';
    }

    function doSave() {
        clearFlash();
        if (state.mode === 'regions') {
            if (!state.currentRegion) return;
            var url = '/api/admin/refpoints/region/' + encodeURIComponent(state.currentRegion.id);
            fetchJSON(url, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ points: state.points }),
            }).then(function (resp) {
                state.points = resp.points.map(function (p) { return [Number(p[0]), Number(p[1])]; });
                state.baseline = JSON.parse(JSON.stringify(state.points));
                // update region in local cache
                state.currentRegion.reference_points = JSON.parse(JSON.stringify(state.points));
                state.dirty = false;
                renderRefMarkers();
                syncInputsFromState();
                updateButtons();
                flashOk('Gespeichert: ' + state.currentRegion.name + ' (' + state.points.length + ' Punkte)');
            }).catch(function (e) { flashError('Speichern fehlgeschlagen: ' + e.message); });
        } else {
            if (!state.currentSpot || !state.spotCoords) return;
            fetchJSON('/api/admin/refpoints/spot', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    id: state.currentSpot.id,
                    lat: state.spotCoords.lat,
                    lon: state.spotCoords.lon,
                }),
            }).then(function (resp) {
                state.spotCoords = { lat: resp.lat, lon: resp.lon };
                state.spotBaseline = { lat: resp.lat, lon: resp.lon };
                // update spot in local cache + overview marker
                state.currentSpot.lat = resp.lat;
                state.currentSpot.lon = resp.lon;
                state.dirty = false;
                syncInputsFromState();
                renderAllSpotMarkers(); // refresh overview circles
                updateButtons();
                flashOk('Gespeichert: ' + state.currentSpot.site_name + ' → ' + resp.lat + ', ' + resp.lon);
            }).catch(function (e) { flashError('Speichern fehlgeschlagen: ' + e.message); });
        }
    }

    function doReset() {
        clearFlash();
        if (state.mode === 'regions') {
            state.points = JSON.parse(JSON.stringify(state.baseline));
            renderRefMarkers();
        } else if (state.spotBaseline) {
            state.spotCoords = { lat: state.spotBaseline.lat, lon: state.spotBaseline.lon };
            if (selectedSpotMarker) selectedSpotMarker.setLatLng([state.spotCoords.lat, state.spotCoords.lon]);
        }
        state.dirty = false;
        syncInputsFromState();
        updateButtons();
    }

    // ---------------- Helpers ----------------
    function setHint(txt) { document.getElementById('rp-status-hint').textContent = txt; }
    function flashOk(msg) {
        var el = document.getElementById('rp-flash');
        el.innerHTML = '<div class="rp-flash rp-flash--ok">' + escapeHtml(msg) + '</div>';
    }
    function flashError(msg) {
        var el = document.getElementById('rp-flash');
        el.innerHTML = '<div class="rp-flash rp-flash--err">' + escapeHtml(msg) + '</div>';
    }
    function clearFlash() { document.getElementById('rp-flash').innerHTML = ''; }
    function escapeHtml(s) {
        if (s == null) return '';
        return String(s).replace(/[&<>"']/g, function (c) {
            return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
        });
    }

    // ---------------- Wire-up ----------------
    document.addEventListener('DOMContentLoaded', function () {
        initMap();
        document.getElementById('rp-mode-regions').addEventListener('click', function () { setMode('regions'); });
        document.getElementById('rp-mode-spots').addEventListener('click', function () { setMode('spots'); });
        document.getElementById('rp-selector').addEventListener('change', function (ev) {
            var v = ev.target.value;
            if (!v) return;
            if (state.mode === 'regions') selectRegion(v);
            else selectSpot(v);
        });
        document.getElementById('rp-region-filter').addEventListener('change', function () {
            if (state.mode === 'spots') {
                renderAllSpotMarkers();
                renderSelector();
            }
        });
        document.getElementById('rp-save').addEventListener('click', doSave);
        document.getElementById('rp-reset').addEventListener('click', doReset);
        window.addEventListener('beforeunload', function (e) {
            if (state.dirty) { e.preventDefault(); e.returnValue = ''; }
        });
        loadAll();
    });
})();
