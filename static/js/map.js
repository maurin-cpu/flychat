/**
 * Wingcast - Map + Meteogram Overlay
 */
(function () {
    'use strict';

    var map;
    var overlay = document.getElementById('meteogramOverlay');
    var chartContainer = document.getElementById('meteogramChart');
    var analyseViewContainer = document.getElementById('analyseViewChart');
    var tabsContainer = document.getElementById('meteogramTabs');
    var tabRow = document.getElementById('meteogramTabRow');
    var feedbackBar = document.getElementById('meteogramFeedback');
    var titleEl = document.getElementById('meteogramTitle');
    var infoEl = document.getElementById('meteogramInfo');
    // ratingBadgeEl / ratingValueEl entfernt (RATING_CONCEPT v1.3 §8.6) —
    // der Hero-Block im Spot-Panel zeigt Verdict + Stars + Score und macht
    // das alte 0-10 Tier-Badge redundant.
    var closeBtn = document.getElementById('meteogramClose');
    var shareBtn = document.getElementById('meteogramShare');
    var tooltipEl = document.getElementById('tooltip');
    var asideEl = document.getElementById('meteogramAside');
    var asideToggleBtn = document.getElementById('meteogramAsideToggle');
    var jsonDebugBtn = document.getElementById('meteogramJsonDebug');
    var jsonDebugActive = false;
    var hazardDebugBtn = document.getElementById('meteogramHazardDebug');
    var hazardDebugActive = false;
    var viewToggleEl = document.getElementById('meteogramViewToggle');
    var dataViewActive = false;

    // Modell-Mapping fuer das Surface-Tier-Voting (siehe docs/WETTERMODELLE.md).
    // Codes kommen vom Backend (api_weather → data_sources[date]).
    var MODEL_INFO = {
        ch1: { label: 'ICON-CH1', resolution: '1.1 km', color: '#2563eb' },
        ch2: { label: 'ICON-CH2', resolution: '2.1 km', color: '#0891b2' },
        d2:  { label: 'ICON-D2',  resolution: '2.2 km', color: '#d97706' },
        eu:  { label: 'ICON-EU',  resolution: '13 km',  color: '#64748b' },
    };
    var MODEL_INFO_UNKNOWN = { label: 'unbekannt', resolution: '', color: '#94a3b8' };

    function modelInfoFor(code) {
        return MODEL_INFO[code] || MODEL_INFO_UNKNOWN;
    }
    window.modelInfoFor = modelInfoFor;

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
                    throw new Error(msg || wcT('js.map.http_loading', { status: r.status }));
                }
                if (ctype.indexOf('application/json') < 0) {
                    throw new Error(wcT('js.map.no_json_long'));
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
    var currentSpotProps = null;
    var currentSpotExperienceScore = null;
    var currentSpotExperienceStars = null;
    var currentSpotExperienceRating = null;
    var markersByName = {}; // Store marker references
    var spotRenderer = null; // gemeinsamer Canvas-Renderer fuer alle Spot-Marker
    var currentRefLayer = null; // Store reference points overlay
    var hideNotSafe = true; // Default: dim not_safe spots

    // Phase 1 (Tool-Use): Layers für Isochrone + User-Standort
    var isochroneLayer = null;
    var userLocationMarker = null;

    // ===== MAP INIT =====
    function initMap() {
        map = L.map('map', {
            center: [46.8, 8.3],
            zoom: 7,
            zoomControl: true,
            // Feine Zoom-Raststufen: ohne das rastet der Pinch-Zoom am Gesten-Ende
            // auf GANZE Stufen ein (sichtbarer Sprung beim Loslassen, "springt grob").
            zoomSnap: 0.25,
            zoomDelta: 0.5,
            wheelPxPerZoomLevel: 120,
        });

        // Gemeinsame Tile-Optionen gegen graue Kacheln:
        // - updateWhenIdle:false — Kacheln schon WAEHREND des Pannens laden
        //   (Leaflet-Default auf Mobile: erst nach Gesten-Ende → grau beim Ziehen)
        // - keepBuffer:4 — mehr Nachbar-Kacheln behalten (Default 2), Zurueck-Pannen ohne Grau
        // - subdomains:'a' — EINE HTTP/2-Verbindung statt 4 TLS-Handshakes zu a-d
        //   (Sharding stammt aus HTTP/1.1-Zeiten und ist heute kontraproduktiv)
        var tileOpts = { updateWhenIdle: false, keepBuffer: 4 };

        // Basis ohne Labels. Mobil in Normalaufloesung ({r} weglassen): Retina-
        // Kacheln (@2x) vervierfachen die Pixel-Dekodier-/Rasterlast — bei der
        // flachen Farbflaechen-Grundkarte auf kleinem Display nicht sichtbar,
        // beim Pannen aber deutlich spuerbar. Labels-Layer bleibt @2x (Textschaerfe).
        var baseTileUrl = (window.innerWidth <= 900)
            ? 'https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}.png'
            : 'https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png';
        L.tileLayer(baseTileUrl, Object.assign({
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>',
            subdomains: 'a',
            maxZoom: 18,
        }, tileOpts)).addTo(map);

        // Topografie (Schummerung) — zeigt Hügel/Berge ohne das Design zu überladen.
        // NICHT auf kleinen Screens: der halbtransparente Zusatz-Layer verdreifacht
        // die Compositing-Arbeit pro Frame — auf Handys die Hauptursache fuer
        // "Bild stockt kurz" beim Zoomen/Ziehen. Auf dem kleinen Display ist die
        // Schummerung ohnehin kaum sichtbar.
        if (window.innerWidth > 900) {
            L.tileLayer('https://services.arcgisonline.com/ArcGIS/rest/services/Elevation/World_Hillshade/MapServer/tile/{z}/{y}/{x}', Object.assign({
                attribution: 'Hillshade &copy; <a href="https://www.esri.com/">Esri</a>',
                opacity: 0.45,
                maxZoom: 16,
            }, tileOpts)).addTo(map);
        }

        // Labels über der Schummerung
        L.tileLayer('https://{s}.basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}{r}.png', Object.assign({
            subdomains: 'a',
            maxZoom: 18,
        }, tileOpts)).addTo(map);

        // Canvas-Pane fuer Spot-Marker: ueber OSM-Peaks (450), Position des
        // frueheren markerPane-Stacks. padding 0.5 = Canvas deckt 2x Viewport,
        // Pan innerhalb des Puffers braucht kein Neuzeichnen. tolerance 6 =
        // zusaetzlicher Hit-Spielraum fuer Touch.
        map.createPane('spotPane').style.zIndex = '600';
        spotRenderer = L.canvas({ pane: 'spotPane', padding: 0.5, tolerance: 6 });

        // Expose the Leaflet map instance under a non-colliding name.
        // `window.map` is unusable because `<div id="map">` auto-creates an
        // HTML implicit global pointing to the DIV element, which has no
        // invalidateSize() method and would crash sidebar resize handlers.
        window.wingcastMap = map;

        // Re-fit to all spots — needed on mobile where #map is initially
        // display:none and the original fitBounds runs against a 0-size container.
        window.wingcastFitToSpots = function () {
            if (!window.wingcastMap || !window.wingcastSpotsBounds) return;
            if (!window.wingcastSpotsBounds.isValid()) return;
            try {
                window.wingcastMap.fitBounds(window.wingcastSpotsBounds, { padding: [20, 20] });
            } catch (e) { /* ignore */ }
        };

        loadSpots();

        // Mini-Legende — geteilt mit Region-Karte ueber rating-info.js
        if (typeof window.buildRatingMiniLegend === 'function') {
            window.buildRatingMiniLegend(L, 'bottomleft').addTo(map);
        }

        // OSM Peaks/Pässe/Sättel — geteiltes Modul (osm-peaks-layer.js).
        // Steuerbar via Admin-UI: config.SHOW_OSM_PEAKS → window.SHOW_OSM_PEAKS.
        if (window.SHOW_OSM_PEAKS && window.WingcastOsmPeaks) {
            window.WingcastOsmPeaks.attach(map);
        }

        // Niederschlags-Referenzpunkte (16 pro Region) — eigener Layer.
        // Gekoppelt an SHOW_REFERENCE_POINTS — sichtbar sobald die 7 Haupt-RPs aktiv sind.
        if ((window.SHOW_REFERENCE_POINTS || window.SHOW_PRECIP_REFPOINTS) && window.WingcastPrecipRefpoints) {
            window.WingcastPrecipRefpoints.attach(map);
        }
    }

    // ===== DIRECTION PARSER =====
    // Liefert Array von [start, end]-Arcs (mehrere bei disjoint mit '/').
    // Unterstuetzt PGE-synthetisierte Strings:
    //   'O-SO-S-SW-W'   → ein Arc 90°-270° (first..last)
    //   'NW-N-NO'       → ein Arc 315°-45° (Wraparound)
    //   'S/N'           → zwei Arcs (S-Sektor + N-Sektor)
    //   'NO-O/W-NW'     → zwei Arcs
    function getDirAngles(dirStr) {
        if (!dirStr) return null;
        var dirs = {
            'N': 0, 'NNO': 22.5, 'NNE': 22.5, 'NO': 45, 'NE': 45, 'ONO': 67.5, 'ENE': 67.5,
            'O': 90, 'E': 90, 'OSO': 112.5, 'ESE': 112.5, 'SO': 135, 'SE': 135, 'SSO': 157.5, 'SSE': 157.5,
            'S': 180, 'SSW': 202.5, 'SW': 225, 'WSW': 247.5,
            'W': 270, 'WNW': 292.5, 'NW': 315, 'NNW': 337.5
        };
        var arcs = [];
        var disjointParts = dirStr.toUpperCase().split('/');
        for (var d = 0; d < disjointParts.length; d++) {
            var run = disjointParts[d].trim();
            if (!run) continue;
            var parts = run.split('-');
            var angles = [];
            for (var i = 0; i < parts.length; i++) {
                var a = dirs[parts[i].trim()];
                if (a !== undefined) angles.push(a);
            }
            if (angles.length === 0) continue;
            // parts kommen clockwise-geordnet aus spots._sectors_to_windrichtung
            // (PGE_SECTOR_ORDER). Span = anzahl-sektoren * 45°, beginnend 22.5°
            // vor dem ersten Mittelpunkt. Echtes Wraparound (z.B. 'NW-N-NE')
            // bleibt erhalten (292.5° -> 427.5°), eine breite Nicht-Wraparound-
            // Sequenz (z.B. 'O-SO-S-SW-W') wird NICHT faelschlich gespiegelt.
            var start = angles[0] - 22.5;
            var end = start + angles.length * 45;
            arcs.push([start, end]);
        }
        return arcs.length ? arcs : null;
    }

    // Diskrete Rating-Tints — Palette v2 (Option C, Mai 2026): green-Band alignt
    // mit Thermik-Kacheln fuer Rating 3-5 (Lime/Mint-Green/Cyan), Rating 1+2 in
    // Pastell-Mint/Mint. amber bleibt Yellow→Brown. Identisch zu region-map.js,
    // shared-glyph.js, briefing.js. Source of Truth: docs/RATING_FARBKONZEPT.md.
    function getRatingTint(band, rating) {
        var r = Math.max(1, Math.min(5, rating | 0));
        if (band === 'green') {
            // v3.2 Royal Premium: Sky-100 → Sky-200 → Lime → Green-500 → Violet
            return {
                fill:   ['#e0f2fe', '#bae6fd', '#BEF264', '#22c55e', '#a78bfa'][Math.min(4, r - 1)],
                stroke: ['#38bdf8', '#0ea5e9', '#65a30d', '#15803d', '#6d28d9'][Math.min(4, r - 1)]
            };
        }
        if (band === 'amber') {
            return {
                fill:   ['#fef08a', '#facc15', '#f97316', '#c2410c', '#7c2d12'][Math.min(4, r - 1)],
                stroke: ['#ca8a04', '#a16207', '#9a3412', '#7c2d12', '#431407'][Math.min(4, r - 1)]
            };
        }
        return null;
    }

    // ===== STYLE SYSTEM (RATING_CONCEPT v1.3 §8.2 — Single-Glyph) =====
    // safetyBand: 'green' | 'amber' | 'red' | 'no_data' | 'default'
    // experienceStars: 0..5 (integer)
    function mapSafetyBandToStyle(band) {
        if (band === 'violet') return {
            // Palette v3.2 "Royal Premium": Premium-Tier = Violet-400 (Legendary).
            fill: '#a78bfa', stroke: '#6d28d9',
            label: 'Top'
        };
        if (band === 'green') return {
            fill: '#22c55e', stroke: '#15803d',
            label: wcT('js.safety.safe')
        };
        if (band === 'amber') return {
            fill: '#f59e0b', stroke: '#92400e',
            label: wcT('js.safety.caution')
        };
        if (band === 'red') return {
            fill: '#ef4444', stroke: '#991b1b',
            label: wcT('js.safety.not_flyable')
        };
        if (band === 'no_data') return {
            fill: '#9ca3af', stroke: '#6b7280',
            label: wcT('js.av.no_data')
        };
        // default / unanalyzed
        return {
            fill: '#6b7280', stroke: '#4b5563',
            label: ''
        };
    }

    // Legacy-Mapping fuer alte Cache-Daten ohne safety_band-Feld.
    // Erlaubt graceful migration — entfernt sobald alle Caches reanalysiert sind.
    function legacySafetyBand(safetyStatus) {
        if (safetyStatus === 'not_safe') return 'red';
        if (safetyStatus === 'conditional') return 'amber';
        if (safetyStatus === 'safe') return 'green';
        if (safetyStatus === 'no_data' || safetyStatus === 'error') return 'no_data';
        return 'default';
    }

    // ===== CANVAS-MARKER (RATING_ARCHITECTURE v2.0) =====
    // Alle 494 Spots werden auf EINE Canvas-Flaeche gezeichnet statt als 494
    // DOM-Elemente (~4000 SVG-Knoten). Grund: bei vielen sichtbaren Spots war
    // Pannen/Zoomen spuerbar zaeher als bei wenigen — der Browser musste die
    // aufgeblaehte Marker-Pane rastern. Canvas = ein Element, egal wie viele.
    // Klick/Tooltip/Popup/Suche laufen unveraendert ueber Leaflet: SpotMarker
    // ist eine L.CircleMarker-Subklasse (Hit-Test = Kreis mit SPOT_HIT_RADIUS),
    // nur das Zeichnen ist durch drawSpot ersetzt.
    var SPOT_HIT_RADIUS = 20; // Hit-/Redraw-Radius; grosszuegiges Tap-Ziel (WCAG)

    // Zeichnet einen Spot — Optik identisch zum frueheren SVG-DivIcon:
    // Windsektor(en), Highlight-Glow, Schatten, weisser Grund, Band-Kreis, Glyphe.
    function drawSpot(ctx, x, y, layer) {
        var band = layer.currentSafetyBand || 'default';
        var rating = (typeof layer.currentRating === 'number') ? Math.floor(layer.currentRating) : 0;
        if (rating === 6) rating = 5; // Migration-Tolerance: alter Cache-Wert 6 → 5
        rating = Math.max(0, Math.min(5, rating));
        var highlighted = !!layer._wcHighlight;
        var props = layer.featureProperties || {};
        var style = mapSafetyBandToStyle(band);
        var isMobile = window.innerWidth <= 600;
        var radius = highlighted ? (isMobile ? 9 : 8) : (isMobile ? 8 : 7);
        if (layer._wcHover) radius += 1; // Hover-Feedback (ersetzt CSS :hover scale)

        // Display-Band Premium-Override: safe + rating=5 (xc_tag/Klassiker) →
        // Violet-400 (Palette v3.2 Royal Premium).
        if (band === 'green' && rating >= 5) {
            band = 'violet';
            style = { fill: '#a78bfa', stroke: '#6d28d9' };
        }

        // Wind direction sector (PGE: kann mehrere disjunkte Arcs liefern)
        if (props.windrichtung) {
            var arcs = getDirAngles(props.windrichtung);
            if (arcs && arcs.length) {
                var ri = radius + 1, ro = radius + 9;
                ctx.globalAlpha = 0.5;
                ctx.fillStyle = style.stroke;
                for (var ai = 0; ai < arcs.length; ai++) {
                    var a0 = (arcs[ai][0] - 90) * Math.PI / 180;
                    var a1 = (arcs[ai][1] - 90) * Math.PI / 180;
                    ctx.beginPath();
                    ctx.arc(x, y, ro, a0, a1, false);
                    ctx.arc(x, y, ri, a1, a0, true);
                    ctx.closePath();
                    ctx.fill();
                }
                ctx.globalAlpha = 1;
            }
        }

        // Highlight glow (selected spot)
        if (highlighted) {
            ctx.globalAlpha = 0.25;
            ctx.fillStyle = style.fill;
            ctx.beginPath();
            ctx.arc(x, y, radius + 4, 0, Math.PI * 2);
            ctx.fill();
            ctx.globalAlpha = 1;
        }

        // Schatten (Nachbildung von drop-shadow(0 1px 3px …) ohne Blur)
        ctx.fillStyle = 'rgba(0,0,0,0.13)';
        ctx.beginPath();
        ctx.arc(x, y + 1.2, radius + 1, 0, Math.PI * 2);
        ctx.fill();

        // Weisser Hintergrund-Kreis, damit die Karte bei hellem Fill nicht durchscheint
        ctx.fillStyle = '#ffffff';
        ctx.beginPath();
        ctx.arc(x, y, radius, 0, Math.PI * 2);
        ctx.fill();

        // Rating-Tint: Hue-Shift quer durch verwandte Farbtoene
        // (Source of Truth: docs/RATING_FARBKONZEPT.md)
        var markerFill = style.fill;
        var markerStroke = style.stroke;
        if (rating > 0 && (band === 'green' || band === 'amber')) {
            var tint = getRatingTint(band, rating);
            if (tint) { markerFill = tint.fill; markerStroke = tint.stroke; }
        }

        // Main circle (safety band color)
        ctx.beginPath();
        ctx.arc(x, y, radius, 0, Math.PI * 2);
        ctx.fillStyle = markerFill;
        ctx.fill();
        ctx.lineWidth = highlighted ? 2 : 1.5;
        ctx.strokeStyle = markerStroke;
        ctx.stroke();

        // Inner glyph
        if (band === 'red') {
            // White X cross — Sperr-Glyphe
            var arm = radius * 0.55;
            ctx.strokeStyle = '#ffffff';
            ctx.lineWidth = Math.max(2, radius * 0.22);
            ctx.lineCap = 'round';
            ctx.beginPath();
            ctx.moveTo(x - arm, y - arm); ctx.lineTo(x + arm, y + arm);
            ctx.moveTo(x + arm, y - arm); ctx.lineTo(x - arm, y + arm);
            ctx.stroke();
            ctx.lineCap = 'butt';
        } else if (rating >= 1 && (band === 'green' || band === 'amber' || band === 'violet')) {
            // Ziffer 1-5 — dunkler Text auf hellen Fills, weiss auf saturierten
            var fontSize = Math.round(radius * 1.5);
            var darkBgHere = (band === 'violet')
                || (band === 'amber' && rating >= 3)
                || (band === 'green' && rating >= 4);
            ctx.fillStyle = darkBgHere ? '#ffffff' : markerStroke;
            ctx.font = '800 ' + fontSize + 'px Inter, sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(String(rating), x, y + 0.5);
        } else if (band === 'green' || band === 'amber' || band === 'violet') {
            // 0 rating: kleiner weisser Punkt (sicher aber Abgleiter)
            ctx.fillStyle = '#ffffff';
            ctx.beginPath();
            ctx.arc(x, y, 1.8, 0, Math.PI * 2);
            ctx.fill();
        }
    }

    // CircleMarker-Subklasse: Leaflet liefert Events/Tooltip/Popup/Hit-Test,
    // gezeichnet wird via drawSpot auf dem gemeinsamen Canvas.
    var SpotMarker = L.CircleMarker.extend({
        _updatePath: function () {
            if (this._renderer && this._renderer._ctx) {
                drawSpot(this._renderer._ctx, this._point.x, this._point.y, this);
            }
        }
    });

    // Visuellen Zustand eines Markers setzen. Signatur-Guard: unveraendert →
    // gar nichts tun (haeufigster Fall beim Tab-Fokus-Refetch). Sonst genuegt
    // redraw() — der Canvas-Renderer sammelt alle Aenderungen in EINEM
    // Frame-Repaint statt 494 einzelner DOM-Operationen.
    function applySpotVisual(marker, band, rating, highlighted) {
        var sig = band + '|' + rating + '|' + (highlighted ? 1 : 0);
        if (marker._wcSig === sig) return false;
        marker._wcSig = sig;
        marker._wcHighlight = !!highlighted;
        if (marker._map) marker.redraw();
        return true;
    }

    // ===== TOOLTIP BUILDER (RATING_CONCEPT v1.4 §8.2) =====
    // Signature: buildTooltipHtml(p, _legacyStyle, safetyBand, experienceRating, dayData)
    // experienceRating ist 0-10 (0 = kein Flug). _legacyStyle bleibt fuer alte
    // Aufrufer, wird ignoriert wenn safetyBand uebergeben wird.
    function buildTooltipHtml(p, _legacyStyle, safetyBand, experienceRating, dayData) {
        var html = '<b>' + p.name + '</b><br>' +
            p.fluggebiet + ' (' + p.region + ')<br>' +
            p.elevation_m + 'm MSL | Wind: ' + p.windrichtung;
        if (!p.has_weather) {
            html += '<br><span style="color:#F59E0B;">' + wcT('js.map.no_weather_loaded') + '</span>';
        }
        if (safetyBand && safetyBand !== 'default') {
            var s = mapSafetyBandToStyle(safetyBand);
            html += '<br><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:'
                  + s.fill + ';margin-right:4px;vertical-align:middle;"></span>';
            html += '<span style="color:' + s.stroke + ';">' + s.label + '</span>';
            if (safetyBand !== 'red' && typeof experienceRating === 'number' && experienceRating >= 1) {
                html += ' &middot; Rating ' + experienceRating;
            }
        }
        return html;
    }

    // ===== LOAD SPOTS =====
    function loadSpots() {
        // via data-store: dedupliziert mit region-map.js (ein Download)
        window.wingcastData.getSpots()
            .then(function (geojson) {
                var geoJsonLayer = L.geoJSON(geojson, {
                    pointToLayer: function (feature, latlng) {
                        // Canvas-Marker: Optik kommt komplett aus drawSpot,
                        // radius dient nur Hit-Test + Redraw-Region.
                        return new SpotMarker(latlng, {
                            renderer: spotRenderer,
                            pane: 'spotPane',
                            radius: SPOT_HIT_RADIUS,
                            stroke: false,
                            fill: false,
                            bubblingMouseEvents: false,
                        });
                    },
                    onEachFeature: function (feature, layer) {
                        var p = feature.properties;
                        layer.featureProperties = p;
                        layer.currentSafetyBand = p.has_weather ? 'default' : 'no_data';
                        layer.currentRating = 0;
                        layer.currentStars = 0;
                        // Signatur des initial gesetzten Icons (siehe applySpotVisual)
                        layer._wcSig = layer.currentSafetyBand + '|0|0';
                        // Legacy compat-Felder (fuer Highlight/Tooltip-Pfade die noch davon lesen)
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
                            // Hover-Grow (ersetzt frueheres CSS :hover scale auf dem SVG)
                            layer._wcHover = true;
                            layer.redraw();
                            if (SHOW_REFERENCE_POINTS && p.reference_points && p.reference_points.length > 1) {
                                var refGroup = L.layerGroup();
                                var spotPt = p.reference_points[0]; // Point 0 is the spot itself

                                // Farbe nach aktuellem Surface-Modell fuer Tag 1
                                // (subtil — siehe docs/WETTERMODELLE.md Tier-Voting).
                                // Fallback auf Slate wenn data_sources noch nicht geladen.
                                var srcCode = null;
                                if (p.data_sources && typeof p.data_sources === 'object') {
                                    var dsKeys = Object.keys(p.data_sources).sort();
                                    if (dsKeys.length) srcCode = p.data_sources[dsKeys[0]];
                                }
                                var refInfo = (window.modelInfoFor ? window.modelInfoFor(srcCode)
                                    : { color: '#0369a1' });

                                // Draw lines from spot to each reference point
                                p.reference_points.slice(1).forEach(function(pt) {
                                    // 1. Connection Line
                                    var line = L.polyline([spotPt, pt], {
                                        color: refInfo.color,
                                        weight: 1.5,
                                        dashArray: '5, 5',
                                        opacity: 0.5
                                    });
                                    refGroup.addLayer(line);

                                    // 2. Small markers for the grid points
                                    var circle = L.circleMarker(pt, {
                                        radius: 4,
                                        color: refInfo.color,
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
                            layer._wcHover = false;
                            layer.redraw();
                            if (currentRefLayer) {
                                map.removeLayer(currentRefLayer);
                                currentRefLayer = null;
                            }
                        });
                    },
                }).addTo(map);

                // Nach dem Laden an alle Spots anpassen (Gesamtansicht Schweiz)
                try {
                    var bounds = geoJsonLayer.getBounds();
                    if (bounds && bounds.isValid()) {
                        window.wingcastSpotsBounds = bounds;
                        map.fitBounds(bounds, { padding: [20, 20] });
                    }
                } catch (e) {
                    console.warn('fitBounds fehlgeschlagen:', e);
                }

                // (Frueheres Viewport-Culling entfernt: der Canvas-Renderer
                // zeichnet von sich aus nur Marker im Sichtbereich, und fuer den
                // Hit-Test muessen alle Marker angehaengt bleiben.)
            })
            .then(function () {
                // Race-Fix: falls /api/analyses VOR /api/spots zurueckkam,
                // lief updateSpotColors ueber ein leeres markersByName (no-op).
                // Marker bleiben dann grau (default/no_data) bis User Day-Tab wechselt.
                // Jetzt sind Marker da → einmal nach-coloren wenn Analyse vorhanden.
                if (window.analysisData && window.updateSpotColors) {
                    window.updateSpotColors(window.analysisData, window.currentDate);
                }
            })
            .then(openSpotFromUrl)
            .catch(function (err) {
                console.error('Spots laden fehlgeschlagen:', err);
            });
    }

    // Deep-Link: wenn /?spot=<Name> in der URL steht, Spot zentrieren + Meteogramm öffnen
    function openSpotFromUrl() {
        try {
            var params = new URLSearchParams(window.location.search);
            var spotName = params.get('spot');
            if (!spotName) return;
            var dateParam = params.get('date');
            if (dateParam) window.currentDate = dateParam;
            var marker = markersByName[spotName];
            if (!marker) return;
            if (marker.getLatLng) {
                map.setView(marker.getLatLng(), Math.max(map.getZoom(), 12));
            }
            var props = marker.featureProperties || (marker.feature && marker.feature.properties) || null;
            openMeteogram(spotName, props);
        } catch (e) {
            console.warn('[map] Spot aus URL konnte nicht geöffnet werden:', e);
        }
    }


    // ===== ANALYSE ASIDE TOGGLE (mobile collapsible) =====
    // Toggle wird durch Button ODER Header-Tap ausgelöst (grössere Tap-Target).
    if (asideEl) {
        var asideHeader = asideEl.querySelector('.meteogram-aside-header');
        var toggleAside = function (ev) {
            // Verhindern, dass interaktive Inhalte im Body den Toggle triggern
            if (ev && ev.target && ev.target.closest && ev.target.closest('.meteogram-aside-body')) return;
            var collapsed = asideEl.classList.toggle('collapsed');
            if (asideToggleBtn) {
                asideToggleBtn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
            }
        };
        // Header bekommt den Handler (Button bubbled hinauf — kein Doppel-Toggle).
        if (asideHeader) asideHeader.addEventListener('click', toggleAside);
        else if (asideToggleBtn) asideToggleBtn.addEventListener('click', toggleAside);
    }

    // ===== JSON DEBUG (Testmodus) =====
    function renderJsonDebug() {
        if (!chartContainer || !currentSpotName || !currentDates.length) return;
        var dateStr = currentDates[currentDateIdx];
        var analysis = (window.analysisData && window.analysisData[currentSpotName] && window.analysisData[currentSpotName][dateStr])
            ? window.analysisData[currentSpotName][dateStr]
            : null;
        chartContainer.innerHTML = '<pre id="jsonDebugPre" style="margin:0;padding:12px;font-size:11px;line-height:1.5;overflow:auto;height:100%;box-sizing:border-box;white-space:pre-wrap;word-break:break-all;color:#e2e8f0;background:#0f172a;border-radius:6px;">'
            + (analysis ? JSON.stringify(analysis, null, 2).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;') : '(keine Analyse für ' + currentSpotName + ' / ' + dateStr + ')')
            + '</pre>';
    }

    if (jsonDebugBtn) {
        jsonDebugBtn.addEventListener('click', function () {
            jsonDebugActive = !jsonDebugActive;
            jsonDebugBtn.classList.toggle('active', jsonDebugActive);
            if (hazardDebugActive) { hazardDebugActive = false; if (hazardDebugBtn) hazardDebugBtn.classList.remove('active'); }
            if (jsonDebugActive) {
                renderJsonDebug();
            } else {
                renderCurrentDay();
            }
        });
    }

    // ===== DATAVIEW (Meteogramm ⇄ Daten) — fuer alle Flieger =====
    function renderDataView() {
        if (!chartContainer || !currentSpotName || !currentDates.length) return;
        WxDataView.render(chartContainer, 'spot', currentSpotName, currentDates[currentDateIdx]);
    }

    function setDataView(active, skipRender) {
        dataViewActive = active;
        if (active) {
            // Andere (Test-)Debug-Ansichten deaktivieren.
            if (jsonDebugActive) { jsonDebugActive = false; if (jsonDebugBtn) jsonDebugBtn.classList.remove('active'); }
            if (hazardDebugActive) { hazardDebugActive = false; if (hazardDebugBtn) hazardDebugBtn.classList.remove('active'); }
        }
        if (viewToggleEl) {
            viewToggleEl.querySelectorAll('.dv-toggle-btn').forEach(function (b) {
                var on = (b.dataset.view === 'daten') === active;
                b.classList.toggle('active', on);
                b.setAttribute('aria-selected', on ? 'true' : 'false');
            });
        }
        if (!skipRender) renderCurrentDay();
    }

    if (viewToggleEl) {
        viewToggleEl.querySelectorAll('.dv-toggle-btn').forEach(function (b) {
            b.addEventListener('click', function () { setDataView(b.dataset.view === 'daten'); });
        });
    }

    function _escHtml(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

    function renderHazardDebug() {
        if (!chartContainer || !currentSpotName || !currentDates.length) return;
        var dateStr = currentDates[currentDateIdx];
        chartContainer.innerHTML = '<div id="hazardDebugLoading" style="padding:12px;color:#94a3b8;font-size:12px;">Lade Debug-Daten…</div>';
        var url = '/api/spot-debug/' + encodeURIComponent(currentSpotName) + '/' + encodeURIComponent(dateStr);
        fetch(url).then(function(r){ return r.json(); }).then(function(d) {
            if (d.error) { chartContainer.innerHTML = '<div style="padding:12px;color:#f87171;">'+_escHtml(d.error)+'</div>'; return; }
            var lines = [];
            lines.push('=== SAFETY ===');
            lines.push('Status: ' + (d.safety_status||'?') + '  |  Band: ' + (d.safety_band||'?') + '  |  Score: ' + (d.safety_score!=null?d.safety_score:'?') + '  |  Foehn: ' + (d.foehn_risk||'?'));
            lines.push('');
            lines.push('--- Sub-Ratings (1-10) ---');
            if (d.sub_ratings) Object.keys(d.sub_ratings).forEach(function(k){ lines.push('  ' + k.replace('_safety_rating','').padEnd(15) + ': ' + (d.sub_ratings[k]!=null?d.sub_ratings[k]:'–')); });
            lines.push('');
            lines.push('--- Hazard Notes ---');
            if (d.hazard_notes) Object.keys(d.hazard_notes).forEach(function(k){ lines.push('  [' + k + '] ' + _escHtml(d.hazard_notes[k]||'')); });
            lines.push('');
            if (d.wind_summary) { lines.push('--- Wind Summary ---'); lines.push(_escHtml(d.wind_summary)); lines.push(''); }
            if (d.wind_shear) { lines.push('--- Wind Shear ---'); lines.push(_escHtml(d.wind_shear)); lines.push(''); }
            lines.push('=== FLYABILITY ===');
            lines.push('Experience-Rating: ' + (d.experience_rating!=null?d.experience_rating:'?'));
            lines.push('');
            lines.push('--- Flyability Notes ---');
            if (d.flyability_notes) Object.keys(d.flyability_notes).forEach(function(k){ lines.push('  [' + k + '] ' + _escHtml(d.flyability_notes[k]||'')); });
            lines.push('');
            lines.push('=== DECISIONS APPLIED ===');
            lines.push((d._decisions_applied && d._decisions_applied.length) ? d._decisions_applied.join(', ') : '(keine)');
            chartContainer.innerHTML = '<pre style="margin:0;padding:12px;font-size:11px;line-height:1.6;overflow:auto;height:100%;box-sizing:border-box;white-space:pre-wrap;word-break:break-all;color:#e2e8f0;background:#0f172a;border-radius:6px;">'
                + lines.join('\n') + '</pre>';
        }).catch(function(err){
            chartContainer.innerHTML = '<div style="padding:12px;color:#f87171;">Fehler: '+_escHtml(err)+'</div>';
        });
    }

    if (hazardDebugBtn) {
        hazardDebugBtn.addEventListener('click', function () {
            hazardDebugActive = !hazardDebugActive;
            hazardDebugBtn.classList.toggle('active', hazardDebugActive);
            if (jsonDebugActive) { jsonDebugActive = false; if (jsonDebugBtn) jsonDebugBtn.classList.remove('active'); }
            if (hazardDebugActive) {
                renderHazardDebug();
            } else {
                renderCurrentDay();
            }
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
            analyseViewContainer.innerHTML = '<div class="error-state">' + wcT('js.map.analysis_unavailable') + '</div>';
            return;
        }
        Meteogram.renderAnalysisView(analyseViewContainer, analysis, {
            spotName: currentSpotName,
            dateStr: dateStr,
        });
        // Capture experience-score + stars fuer Share-Text (Hero-Block zeigt
        // Rating selbst — kein separates Badge mehr).
        // experience_score / experience_stars in v2.0 entfernt
        currentSpotExperienceRating = (analysis && typeof analysis.experience_rating === 'number') ? analysis.experience_rating : null;
        renderFeedbackBar(currentSpotName, dateStr, analysis);
    }

    function renderFeedbackBar(spotName, dateStr, analysis) {
        if (!feedbackBar || !spotName) return;
        // Widget wird angezeigt sobald ein Spot offen ist — analysis kann
        // beim Open noch fehlen (race mit /api/spot_analyses), oder
        // safety_status kann 'no_data' sein. Pilot soll trotzdem Feedback
        // geben können. Nur bei echtem Backend-Error ('error') macht es
        // keinen Sinn → Widget hidden.
        var status = analysis && analysis.safety_status;
        if (status === 'error') {
            feedbackBar.innerHTML = '';
            feedbackBar.style.display = 'none';
            return;
        }
        // Re-mount nicht jedesmal — wenn das Widget schon für diesen
        // Spot+Date gemountet ist, nichts tun (vermeidet __fbBound-Reset).
        var existing = feedbackBar.querySelector('[data-fb-mount]');
        if (existing
            && existing.getAttribute('data-fb-target') === spotName
            && existing.getAttribute('data-fb-date') === (dateStr || '')) {
            feedbackBar.style.display = 'flex';
            return;
        }
        feedbackBar.innerHTML = '';
        var mount = document.createElement('div');
        mount.setAttribute('data-fb-mount', '');
        mount.setAttribute('data-fb-type', 'spot');
        mount.setAttribute('data-fb-target', spotName);
        if (dateStr) mount.setAttribute('data-fb-date', dateStr);
        feedbackBar.appendChild(mount);
        feedbackBar.style.display = 'flex';
        if (window.Feedback && window.Feedback.scan) window.Feedback.scan(feedbackBar);
    }

    // ===== METEOGRAM OVERLAY =====
    function openMeteogram(spotName, props) {
        currentSpotName = spotName;
        currentSpotProps = props || null;
        setDataView(false, true);  // neuer Spot startet im Meteogramm
        currentSpotExperienceScore = null;
        currentSpotExperienceStars = null;
        currentSpotExperienceRating = null;
        titleEl.textContent = spotName;
        infoEl.textContent = props
            ? props.fluggebiet + ' | ' + props.elevation_m + 'm MSL | ' + props.windrichtung
            : '';

        // Modell-Badge neben spot-info — wird in renderCurrentDay pro Tag
        // befuellt (Surface-Tier-Voting CH1 → CH2 → D2 → EU).
        var modelBadge = document.getElementById('meteogramModelBadge');
        if (!modelBadge && infoEl && infoEl.parentNode) {
            modelBadge = document.createElement('span');
            modelBadge.id = 'meteogramModelBadge';
            modelBadge.className = 'meteogram-model-badge';
            infoEl.parentNode.appendChild(modelBadge);
        }
        if (modelBadge) modelBadge.textContent = '';
        chartContainer.innerHTML = '<div class="error-state">' + wcT('js.map.loading_data') + '</div>';
        if (analyseViewContainer) analyseViewContainer.innerHTML = '<div class="mg-analysis-empty">' + wcT('js.map.loading_analysis') + '</div>';
        tabsContainer.innerHTML = '';
        if (tabRow) tabRow.style.display = 'none';
        // feedbackBar: nur leeren, Display via CSS (:empty hidden, :not(:empty) shown).
        // Inline style.display würde sonst das CSS überschreiben und das Widget
        // unsichtbar lassen, auch wenn renderFeedbackBar später mountet.
        if (feedbackBar) feedbackBar.innerHTML = '';
        overlay.style.display = 'flex';
        overlay.classList.add('visible');
        if (window._overlayScrollLock) window._overlayScrollLock();
        closeBtn.focus();

        chartContainer.style.display = '';
        // Aside startet expanded auf Desktop, collapsed auf Mobile (Sheet-Pattern):
        // Auf Mobile sieht der User zuerst das Meteogramm in voller Höhe, kann
        // die Analyse via Toggle-Button ausklappen.
        if (asideEl) {
            var isMobile = window.innerWidth <= 640;
            asideEl.classList.toggle('collapsed', isMobile);
            if (asideToggleBtn) {
                asideToggleBtn.setAttribute('aria-expanded', isMobile ? 'false' : 'true');
            }
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

                // Always render `expected_days` tabs (default 5). Days without
                // data fall through to the existing "Keine Daten" / "Keine
                // Analyse" empty states — that way it's always clear WHY a
                // day is empty (cache stale, analysis missing) instead of
                // silently dropping the tab.
                var expected = parseInt(currentWeather.expected_days, 10);
                if (!isFinite(expected) || expected < 1) {
                    expected = (currentWeather.dates || []).length || 1;
                }
                var _today = new Date();
                _today.setHours(0, 0, 0, 0);
                currentDates = [];
                for (var _i = 0; _i < expected; _i++) {
                    var _d = new Date(_today);
                    _d.setDate(_today.getDate() + _i);
                    currentDates.push(
                        _d.getFullYear() + '-'
                        + String(_d.getMonth() + 1).padStart(2, '0') + '-'
                        + String(_d.getDate()).padStart(2, '0')
                    );
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
                // Tab-Row IMMER sichtbar wenn Daten geladen — auch bei nur 1 Tag,
                // damit das Feedback-Widget rechts in der Zeile sichtbar bleibt.
                // Tabs selbst werden separat hidden wenn nur 1 Tag.
                if (tabRow) tabRow.style.display = '';

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
        if (hazardDebugActive) { renderHazardDebug(); renderAnalyseView(); return; }
        if (jsonDebugActive) { renderJsonDebug(); renderAnalyseView(); return; }
        if (dataViewActive) { renderDataView(); renderAnalyseView(); return; }
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
            thresholds: currentWeather.thresholds,
            fitToContainer: true,
        });

        // Modell-Badge im Header neben Spot-Info aktualisieren (Surface-Tier-
        // Voting CH1/CH2/D2/EU pro Tag, siehe docs/WETTERMODELLE.md).
        var modelBadgeEl = document.getElementById('meteogramModelBadge');
        if (modelBadgeEl) {
            var srcCode = (currentWeather.data_sources && currentWeather.data_sources[dateStr]) || null;
            var info = modelInfoFor(srcCode);
            modelBadgeEl.innerHTML = '';
            modelBadgeEl.title = 'Datenquelle Surface fuer diesen Tag. Tier-Voting CH1 → CH2 → D2 → EU.';
            var dot = document.createElement('span');
            dot.style.cssText = 'display:inline-block;width:7px;height:7px;border-radius:50%;background:'
                + info.color + ';margin-right:4px;vertical-align:middle;';
            modelBadgeEl.appendChild(dot);
            modelBadgeEl.appendChild(document.createTextNode(
                info.label + (info.resolution ? ' · ' + info.resolution : '')
            ));
        }

        // Footer: nur Wetter-Stand (Modell-Info ist jetzt im Header).
        var existingTs = chartContainer.querySelector('.meteogram-weather-ts');
        if (existingTs) existingTs.remove();
        if (currentWeather.last_updated) {
            var tsDiv = document.createElement('div');
            tsDiv.className = 'meteogram-weather-ts';
            tsDiv.style.cssText = 'font-size:10px;color:#94a3b8;text-align:right;padding:2px 8px 0;';
            tsDiv.textContent = wcT('js.map.weather_as_of') + currentWeather.last_updated.replace('T', ' ').slice(0, 16);
            chartContainer.appendChild(tsDiv);
        }

        // Analyse panel is always visible in the aside – refresh on every day change.
        renderAnalyseView();
    }

    function closeMeteogram() {
        overlay.style.display = 'none';
        overlay.classList.remove('visible');
        tooltipEl.classList.remove('visible');
        currentWeather = null;
        currentAltWind = null;
        if (window._overlayScrollUnlock) window._overlayScrollUnlock();
        // Debug-Buttons zurücksetzen
        if (jsonDebugActive) {
            jsonDebugActive = false;
            if (jsonDebugBtn) jsonDebugBtn.classList.remove('active');
        }
        if (hazardDebugActive) {
            hazardDebugActive = false;
            if (hazardDebugBtn) hazardDebugBtn.classList.remove('active');
        }
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
    window.addEventListener('wingcast-analyses-loaded', function () {
        renderAnalyseView();
    });

    // Listen for day changes from the floating map tabs
    window.addEventListener('wingcast-day-change', function (e) {
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

    if (shareBtn) {
        shareBtn.addEventListener('click', function () {
            if (!currentSpotName || typeof window.wingcastShare !== 'function') return;
            var regionId = (currentSpotProps && currentSpotProps.region_id) || '';
            var regionName = (currentSpotProps && currentSpotProps.region) || '';
            var rText = '';
            if (currentSpotExperienceRating != null && currentSpotExperienceRating >= 1) {
                rText = ' — Rating ' + currentSpotExperienceRating;
            }
            var dayIdx = 0;
            if (window.currentDate && currentDates && currentDates.length) {
                var idx = currentDates.indexOf(window.currentDate);
                if (idx >= 0) dayIdx = idx;
            }
            window.wingcastShare({
                region_id: regionId,
                day_idx: dayIdx,
                spot: currentSpotName,
                title: currentSpotName + rText,
                text: currentSpotName + (regionName ? ' (' + regionName + ')' : '') + rText + ' · Wingcast Flugwetter',
            });
        });
    }

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
        // Ein Durchlauf statt Reset-aller + Neu-Setzen: nur Marker, deren
        // Highlight-Zustand sich tatsaechlich aendert, werden angefasst.
        var wanted = {};
        if (items && Array.isArray(items)) {
            items.forEach(function (item) {
                wanted[typeof item === 'string' ? item : item.name] = true;
            });
        }
        Object.keys(markersByName).forEach(function (name) {
            var marker = markersByName[name];
            var band = marker.currentSafetyBand || 'default';
            var rating = (typeof marker.currentRating === 'number') ? marker.currentRating : 0;
            var hl = !!wanted[name];
            var changed = applySpotVisual(marker, band, rating, hl);
            // Hervorgehobene zuletzt zeichnen (Canvas-Aequivalent von zIndex)
            if (changed && hl && marker._map) marker.bringToFront();
        });
    };

    // ===== SPOT COLORING (from LLM analyses, RATING_CONCEPT v1.4) =====
    // Reads safety_status + experience_rating (1-6, RATING_ARCHITECTURE v2.0).
    window.updateSpotColors = function (analysisData, dateStr) {
        // analysisData: {spot_name: {date_str: {safety_band, experience_rating, ...}}}
        if (!analysisData || !dateStr) return;

        Object.keys(markersByName).forEach(function (name) {
            var marker = markersByName[name];
            var spotAnalysis = analysisData[name];
            var dayData = spotAnalysis && spotAnalysis[dateStr];

            if (!dayData) {
                // No analysis for this date → reset to no_data
                marker.currentSafetyBand = 'no_data';
                marker.currentRating = 0;
                marker.currentStars = 0;
                marker.currentSafety = 'no_data';
                marker.currentQuality = 'green';
                applySpotVisual(marker, 'no_data', 0, false);
                marker.setTooltipContent(buildTooltipHtml(marker.featureProperties, null, 'no_data', 0, dayData));
                return;
            }

            // RATING_ARCHITECTURE v2.1: safety_status → band (FE-Mapping).
            var band = legacySafetyBand(dayData.safety_status);
            var rating = parseInt(dayData.experience_rating, 10);
            if (!isFinite(rating) || rating < 0) rating = 0;
            // Migration-Tolerance: 6 → 5
            if (rating === 6) rating = 5;
            rating = Math.min(5, rating);

            marker.currentSafetyBand = band;
            marker.currentRating = rating;
            marker.currentSafety = dayData.safety_status || 'safe';

            applySpotVisual(marker, band, rating, false);
            marker.setTooltipContent(buildTooltipHtml(marker.featureProperties, null, band, rating, dayData));
        });
    };

    // ===== REFRESH SPOT MARKERS =====
    window.refreshSpotMarkers = function () {
        // force=true: expliziter Refresh soll wirklich neu laden (ETag macht es billig)
        window.wingcastData.getSpots(true)
            .then(function (geojson) {
                geojson.features.forEach(function (feature) {
                    var p = feature.properties;
                    var marker = markersByName[p.name];
                    if (marker) {
                        marker.featureProperties = p;
                        // Don't override analysis data if it exists
                        var hasAnalysis = marker.currentSafetyBand
                            && marker.currentSafetyBand !== 'default'
                            && marker.currentSafetyBand !== 'no_data';
                        if (!hasAnalysis) {
                            var band = p.has_weather ? 'default' : 'no_data';
                            marker.currentSafetyBand = band;
                            marker.currentRating = 0;
                            marker.currentStars = 0;
                            marker.currentSafety = band;
                            marker.currentQuality = 'green';
                            applySpotVisual(marker, band, 0, false);
                        }
                        var ratingTip = (typeof marker.currentRating === 'number') ? marker.currentRating : 0;
                        marker.setTooltipContent(buildTooltipHtml(
                            p, null, marker.currentSafetyBand, ratingTip, null
                        ));
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
