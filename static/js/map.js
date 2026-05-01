/**
 * Gleitcast - Map + Meteogram Overlay
 */
(function () {
    'use strict';

    var map;
    var overlay = document.getElementById('meteogramOverlay');
    var chartContainer = document.getElementById('meteogramChart');
    var analyseViewContainer = document.getElementById('analyseViewChart');
    var tabsContainer = document.getElementById('meteogramTabs');
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

    // Datenquelle für Wind/Höhenwind. ICON-D2 ist der Open-Meteo-Default.
    var WIND_MODEL_LABEL = 'ICON-D2';

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
    var currentSpotProps = null;
    var currentSpotExperienceScore = null;
    var currentSpotExperienceStars = null;
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
            zoom: 7,
            zoomControl: true,
        });

        // Basis ohne Labels
        L.tileLayer('https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>',
            subdomains: 'abcd',
            maxZoom: 18,
        }).addTo(map);

        // Topografie (Schummerung) — zeigt Hügel/Berge ohne das Design zu überladen
        L.tileLayer('https://services.arcgisonline.com/ArcGIS/rest/services/Elevation/World_Hillshade/MapServer/tile/{z}/{y}/{x}', {
            attribution: 'Hillshade &copy; <a href="https://www.esri.com/">Esri</a>',
            opacity: 0.45,
            maxZoom: 16,
        }).addTo(map);

        // Labels über der Schummerung
        L.tileLayer('https://{s}.basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}{r}.png', {
            subdomains: 'abcd',
            maxZoom: 18,
        }).addTo(map);

        // Expose the Leaflet map instance under a non-colliding name.
        // `window.map` is unusable because `<div id="map">` auto-creates an
        // HTML implicit global pointing to the DIV element, which has no
        // invalidateSize() method and would crash sidebar resize handlers.
        window.gleitcastMap = map;

        // Re-fit to all spots — needed on mobile where #map is initially
        // display:none and the original fitBounds runs against a 0-size container.
        window.gleitcastFitToSpots = function () {
            if (!window.gleitcastMap || !window.gleitcastSpotsBounds) return;
            if (!window.gleitcastSpotsBounds.isValid()) return;
            try {
                window.gleitcastMap.fitBounds(window.gleitcastSpotsBounds, { padding: [20, 20] });
            } catch (e) { /* ignore */ }
        };

        loadSpots();

        // Map Legend (RATING_CONCEPT v1.3 §8.4 — 5 Symbole + Mikro-Copy).
        // Mini-Legende: 3 Safety-Pills + Hinweis auf Stern-Zahl.
        // Tiefere Erklaerung lebt im Rating-Info-Overlay (Klick auf "?").
        var legend = L.control({ position: 'bottomleft' });
        legend.onAdd = function () {
            var isMobile = window.innerWidth <= 639;
            var div = L.DomUtil.create('div', 'map-legend' + (isMobile ? ' collapsed' : ''));
            div.innerHTML =
                '<button class="map-legend-toggle" aria-label="Legende ein-/ausblenden">Legende</button>' +
                '<div class="map-legend-body">' +
                '<div class="map-legend-pills">' +
                    '<span class="map-legend-pill safety-green">Sicher</span>' +
                    '<span class="map-legend-pill safety-amber">Vorsicht</span>' +
                    '<span class="map-legend-pill safety-red">Nicht fliegbar</span>' +
                '</div>' +
                '<div class="map-legend-hint">Zahl im Marker = Erlebnis (1–5 Sterne)</div>' +
                '<button class="map-legend-info-btn" data-action="open-rating-info" type="button">' +
                    '<span class="map-legend-info-icon" aria-hidden="true">ⓘ</span>' +
                    '<span>Wie funktioniert das Rating?</span>' +
                '</button>' +
                '</div>';
            var toggle = div.querySelector('.map-legend-toggle');
            toggle.addEventListener('click', function (e) {
                e.stopPropagation();
                div.classList.toggle('collapsed');
            });
            var infoBtn = div.querySelector('.map-legend-info-btn');
            infoBtn.addEventListener('click', function (e) {
                e.stopPropagation();
                openRatingInfoOverlay();
            });
            L.DomEvent.disableClickPropagation(div);
            return div;
        };
        legend.addTo(map);
        _initRatingInfoOverlay();
        _initWelcomeBanner(map);
    }

    // ===== WELCOME-BANNER =====
    // Einmaliger Hinweis nach Einfuehrung des 2-Achsen-Ratings (RATING_CONCEPT
    // v1.3 §8.7). Erscheint beim ersten Karten-Besuch, wird via localStorage
    // dismissed. Kein Modal, kein blockierender Onboarding-Flow.
    var _WELCOME_KEY = 'gleitcast_welcome_v1_dismissed';
    function _initWelcomeBanner(map) {
        try {
            if (localStorage.getItem(_WELCOME_KEY)) return;
        } catch (e) { /* localStorage gesperrt → trotzdem zeigen */ }

        var banner = L.control({ position: 'topright' });
        banner.onAdd = function () {
            var div = L.DomUtil.create('div', 'map-welcome-banner');
            div.innerHTML =
                '<span class="map-welcome-icon" aria-hidden="true">✦</span>' +
                '<span class="map-welcome-text">' +
                  '<b>Neu:</b> Sterne im Marker = Erlebnis (1–5). ' +
                  'Farbe = Sicherheit (gruen / orange / rot).' +
                '</span>' +
                '<button class="map-welcome-link" type="button" data-action="more">Mehr erfahren</button>' +
                '<button class="map-welcome-close" type="button" aria-label="Schliessen" data-action="close">×</button>';

            div.addEventListener('click', function (e) {
                var t = e.target;
                if (!t || !t.dataset || !t.dataset.action) return;
                e.stopPropagation();
                if (t.dataset.action === 'more') {
                    openRatingInfoOverlay();
                } else if (t.dataset.action === 'close') {
                    _dismissWelcomeBanner();
                }
            });
            L.DomEvent.disableClickPropagation(div);
            return div;
        };
        banner.addTo(map);
        // Reference fuer dismiss
        _welcomeBannerCtl = banner;
    }
    var _welcomeBannerCtl = null;
    function _dismissWelcomeBanner() {
        try { localStorage.setItem(_WELCOME_KEY, '1'); } catch (e) {}
        if (_welcomeBannerCtl) {
            _welcomeBannerCtl.remove();
            _welcomeBannerCtl = null;
        }
    }

    // ===== RATING-INFO OVERLAY =====
    // Erzeugt einmalig ein Modal, das das 2-Achsen-Rating-System erklaert.
    // Trigger: Klick auf "Wie funktioniert das Rating?" in der Mini-Legende.
    function _glyphSvg(band, stars, size) {
        var s = size || 28;
        var center = s / 2;
        var r = s * 0.36;
        var palette = {
            green:   { fill: '#22c55e', stroke: '#15803d' },
            amber:   { fill: '#f59e0b', stroke: '#92400e' },
            red:     { fill: '#ef4444', stroke: '#991b1b' },
            no_data: { fill: '#9ca3af', stroke: '#6b7280' }
        };
        var c = palette[band] || palette.no_data;
        var html = '<svg width="' + s + '" height="' + s + '" viewBox="0 0 ' + s + ' ' + s + '" aria-hidden="true">';
        html += '<circle cx="' + center + '" cy="' + center + '" r="' + r
              + '" fill="' + c.fill + '" stroke="' + c.stroke + '" stroke-width="2"/>';
        if (band === 'red') {
            var arm = r * 0.55;
            html += '<line x1="' + (center - arm) + '" y1="' + (center - arm)
                  + '" x2="' + (center + arm) + '" y2="' + (center + arm)
                  + '" stroke="#fff" stroke-width="2.5" stroke-linecap="round"/>';
            html += '<line x1="' + (center + arm) + '" y1="' + (center - arm)
                  + '" x2="' + (center - arm) + '" y2="' + (center + arm)
                  + '" stroke="#fff" stroke-width="2.5" stroke-linecap="round"/>';
        } else if (typeof stars === 'number' && stars >= 1) {
            html += '<text x="' + center + '" y="' + (center + r * 0.35)
                  + '" text-anchor="middle" fill="#fff" font-family="Inter,sans-serif" font-size="'
                  + (r * 0.95).toFixed(1) + '" font-weight="700">' + stars + '</text>';
        }
        html += '</svg>';
        return html;
    }

    var _ratingInfoBuilt = false;
    function _initRatingInfoOverlay() {
        if (_ratingInfoBuilt) return;
        _ratingInfoBuilt = true;
        var ov = document.createElement('div');
        ov.className = 'rating-info-overlay';
        ov.id = 'ratingInfoOverlay';
        ov.setAttribute('role', 'dialog');
        ov.setAttribute('aria-modal', 'true');
        ov.setAttribute('aria-labelledby', 'ratingInfoTitle');
        ov.hidden = true;

        var bodyHtml =
            '<div class="rating-info-backdrop" data-action="close"></div>' +
            '<div class="rating-info-modal">' +
              '<div class="rating-info-header">' +
                '<h2 id="ratingInfoTitle">Wie funktioniert das Rating?</h2>' +
                '<button class="rating-info-close" data-action="close" aria-label="Schliessen" type="button">×</button>' +
              '</div>' +
              '<div class="rating-info-body">' +

                '<div class="rating-info-section">' +
                  '<p class="rating-info-lead">Jeder Spot wird auf <b>zwei unabhaengigen Achsen</b> bewertet — Sicherheit und Erlebnis. Beides siehst du im selben Marker.</p>' +
                '</div>' +

                '<div class="rating-info-section">' +
                  '<div class="rating-info-axes">' +
                    '<div class="rating-info-axis-card">' +
                      '<div class="rating-info-axis-title">Farbe = Sicherheit</div>' +
                      '<div class="rating-info-row">' + _glyphSvg('green', 0, 28) + '<span><b>Gruen</b> — sicher fliegbar</span></div>' +
                      '<div class="rating-info-row">' + _glyphSvg('amber', 0, 28) + '<span><b>Orange</b> — Vorsicht, Caution-Notes</span></div>' +
                      '<div class="rating-info-row">' + _glyphSvg('red', 0, 28)   + '<span><b>Rot</b> — nicht fliegbar</span></div>' +
                    '</div>' +
                    '<div class="rating-info-axis-card">' +
                      '<div class="rating-info-axis-title">Zahl = Erlebnis</div>' +
                      '<div class="rating-info-row">' + _glyphSvg('green', 1, 28) + '<span><b>1 Stern</b> — sicher, kurzer Flug</span></div>' +
                      '<div class="rating-info-row">' + _glyphSvg('green', 3, 28) + '<span><b>3 Sterne</b> — solider Tag, lokal-XC</span></div>' +
                      '<div class="rating-info-row">' + _glyphSvg('green', 5, 28) + '<span><b>5 Sterne</b> — Top-Tag, fettes XC</span></div>' +
                    '</div>' +
                  '</div>' +
                '</div>' +

                '<div class="rating-info-section">' +
                  '<h3>Beispiele</h3>' +
                  '<div class="rating-info-examples">' +
                    '<div class="rating-info-example">' + _glyphSvg('green', 5, 44) + '<div class="rating-info-example-label">Top-Tag</div></div>' +
                    '<div class="rating-info-example">' + _glyphSvg('green', 3, 44) + '<div class="rating-info-example-label">Solider Tag</div></div>' +
                    '<div class="rating-info-example">' + _glyphSvg('amber', 4, 44) + '<div class="rating-info-example-label">Vorsicht — Pro-Tag</div></div>' +
                    '<div class="rating-info-example">' + _glyphSvg('red', 0, 44)   + '<div class="rating-info-example-label">Nicht fliegbar</div></div>' +
                  '</div>' +
                '</div>' +

                '<div class="rating-info-section">' +
                  '<h3>Im Spot-Panel — die Tiefe</h3>' +
                  '<div class="rating-info-deeper">' +
                    '<dl>' +
                      '<dt>Safety-Score</dt>' +
                      '<dd>0–100. Aggregat von 5 Sub-Aspekten: Bodenwind, Boeen, Hoehenwind, Foehn, Wetter (Niederschlag/Gewitter/Sicht). Aggregation per <b>Weakest-Link</b> — der schwaechste Aspekt zieht den Score nach unten. Ein einzelnes Gewitter macht den Tag rot, auch wenn alle anderen 4 perfekt sind.</dd>' +
                      '<dt>Experience-Score</dt>' +
                      '<dd>0–100. <b>Spot</b>: 5 Sub-Ratings — Thermik (30%), Zeitfenster (20%), Wind (10%), XC-Potential (15%), <b>Hoehe ueber Spot</b> (25%). <b>Region</b>: 4 Sub-Ratings — Thermik (35%), Zeitfenster (25%), Wind (25%), XC-Potential (15%) (Region hat keine eindeutige Startplatzhoehe). Sterne im Marker = grobe Skalierung (1–5).</dd>' +
                      '<dt>Comfort-Index</dt>' +
                      '<dd>0–100. Wie glatt (100) oder klapprig (0) der Tag wird. Beeinflusst <b>nicht</b> das Rating — nur dein Wohlbefinden in der Luft.</dd>' +
                    '</dl>' +
                  '</div>' +
                '</div>' +

                '<div class="rating-info-section">' +
                  '<h3>Wer entscheidet was?</h3>' +
                  '<p>KI-Modell + deterministische Regel-Engine arbeiten zusammen: das LLM beurteilt einzelne Aspekte, eine Decision-Engine setzt harte Sicherheits-Schwellen durch (Foehn-Durchbruch, Hoehenwind &gt; 30 km/h, Gewitter). Diese Regeln <b>ueberschreiben</b> das LLM — ein gefaehrlicher Tag kann nicht "weggetextet" werden.</p>' +
                '</div>' +

              '</div>' +
            '</div>';
        ov.innerHTML = bodyHtml;
        document.body.appendChild(ov);

        ov.addEventListener('click', function (e) {
            var t = e.target;
            if (t && t.dataset && t.dataset.action === 'close') {
                closeRatingInfoOverlay();
            }
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && !ov.hidden) closeRatingInfoOverlay();
        });
    }

    function openRatingInfoOverlay() {
        _initRatingInfoOverlay();
        var ov = document.getElementById('ratingInfoOverlay');
        if (!ov) return;
        ov.hidden = false;
        document.body.style.overflow = 'hidden';
        var closeBtn = ov.querySelector('.rating-info-close');
        if (closeBtn) closeBtn.focus();
    }
    function closeRatingInfoOverlay() {
        var ov = document.getElementById('ratingInfoOverlay');
        if (!ov) return;
        ov.hidden = true;
        document.body.style.overflow = '';
    }
    window.openRatingInfoOverlay = openRatingInfoOverlay;

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

    // ===== STYLE SYSTEM (RATING_CONCEPT v1.3 §8.2 — Single-Glyph) =====
    // safetyBand: 'green' | 'amber' | 'red' | 'no_data' | 'default'
    // experienceStars: 0..5 (integer)
    function mapSafetyBandToStyle(band) {
        if (band === 'green') return {
            fill: '#22c55e', stroke: '#15803d',
            label: 'Sicher'
        };
        if (band === 'amber') return {
            fill: '#f59e0b', stroke: '#92400e',
            label: 'Vorsicht'
        };
        if (band === 'red') return {
            fill: '#ef4444', stroke: '#991b1b',
            label: 'Nicht fliegbar'
        };
        if (band === 'no_data') return {
            fill: '#9ca3af', stroke: '#6b7280',
            label: 'Keine Daten'
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

    // ===== CUSTOM MARKER GENERATOR (Single-Glyph v1.3) =====
    // Inner circle = safety band color
    // Inner glyph:
    //   - red                 → white X cross (Sperr-Glyphe)
    //   - stars >= 1          → white digit 1-5 (Erlebnis)
    //   - stars == 0          → small white dot (sicher aber Abgleiter)
    //   - no_data / default   → small white dot (faded)
    function createSpotIcon(props, safetyBand, experienceStars, isHighlighted) {
        var uid = ++_iconUid;
        var style = mapSafetyBandToStyle(safetyBand);
        var isMobile = window.innerWidth <= 600;
        var svgSize = 44;
        var center = svgSize / 2;
        var radius = isHighlighted ? (isMobile ? 10 : 8) : (isMobile ? 8 : 6);
        var stars = (typeof experienceStars === 'number' && experienceStars >= 0 && experienceStars <= 5)
            ? Math.floor(experienceStars) : 0;

        var html = '<svg width="' + svgSize + '" height="' + svgSize + '" viewBox="0 0 ' + svgSize + ' ' + svgSize + '">';
        // Invisible hit-area — extends tap target to full 44x44 (mobile only, WCAG)
        if (isMobile) {
            html += '<circle cx="' + center + '" cy="' + center + '" r="' + (svgSize / 2) + '" fill="rgba(0,0,0,0)" pointer-events="all" />';
        }

        // Wind direction sector (unchanged)
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

        // Highlight glow (selected spot)
        if (isHighlighted) {
            html += '<circle cx="' + center + '" cy="' + center + '" r="' + (radius + 4) + '" fill="' + style.fill + '" opacity="0.25" />';
        }

        // Main circle (safety band color)
        html += '<circle cx="' + center + '" cy="' + center + '" r="' + radius + '" fill="' + style.fill
                + '" stroke="' + style.stroke + '" stroke-width="' + (isHighlighted ? '2' : '1.5') + '" />';

        // Inner glyph
        if (safetyBand === 'red') {
            // White X cross — Sperr-Glyphe
            var arm = radius * 0.55;
            html += '<line x1="' + (center - arm) + '" y1="' + (center - arm)
                  + '" x2="' + (center + arm) + '" y2="' + (center + arm)
                  + '" stroke="#ffffff" stroke-width="2" stroke-linecap="round" />';
            html += '<line x1="' + (center + arm) + '" y1="' + (center - arm)
                  + '" x2="' + (center - arm) + '" y2="' + (center + arm)
                  + '" stroke="#ffffff" stroke-width="2" stroke-linecap="round" />';
        } else if (stars >= 1 && (safetyBand === 'green' || safetyBand === 'amber')) {
            // White digit 1-5 — Erlebnis-Sterne als kompakte Ziffer
            var fontSize = isHighlighted ? 11 : 9;
            html += '<text x="' + center + '" y="' + (center + fontSize * 0.35)
                  + '" text-anchor="middle" fill="#ffffff" font-family="Inter, sans-serif"'
                  + ' font-size="' + fontSize + '" font-weight="700">' + stars + '</text>';
        } else if (safetyBand === 'green' || safetyBand === 'amber') {
            // 0 stars: kleiner weisser Punkt (sicher aber Abgleiter)
            html += '<circle cx="' + center + '" cy="' + center + '" r="1.8" fill="#ffffff" />';
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

    // ===== TOOLTIP BUILDER (RATING_CONCEPT v1.3 §8.2) =====
    // Signature: buildTooltipHtml(p, _legacyStyle, safetyBand, experienceStars, dayData)
    // _legacyStyle bleibt fuer alte Aufrufer, wird ignoriert wenn safetyBand uebergeben wird.
    function buildTooltipHtml(p, _legacyStyle, safetyBand, experienceStars, dayData) {
        var html = '<b>' + p.name + '</b><br>' +
            p.fluggebiet + ' (' + p.region + ')<br>' +
            p.elevation_m + 'm MSL | Wind: ' + p.windrichtung;
        if (!p.has_weather) {
            html += '<br><span style="color:#F59E0B;">Keine Wetterdaten geladen</span>';
        }
        if (safetyBand && safetyBand !== 'default') {
            var s = mapSafetyBandToStyle(safetyBand);
            html += '<br><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:'
                  + s.fill + ';margin-right:4px;vertical-align:middle;"></span>';
            html += '<span style="color:' + s.stroke + ';">' + s.label + '</span>';
            if (safetyBand !== 'red' && typeof experienceStars === 'number' && experienceStars >= 1) {
                html += ' &middot; ' + experienceStars + (experienceStars === 1 ? ' Stern' : ' Sterne');
            }
            if (dayData && typeof dayData.comfort_index === 'number') {
                html += ' &middot; Comfort ' + Math.round(dayData.comfort_index);
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
                        var initBand = feature.properties.has_weather ? 'default' : 'no_data';
                        return L.marker(latlng, {
                            icon: createSpotIcon(feature.properties, initBand, 0, false)
                        });
                    },
                    onEachFeature: function (feature, layer) {
                        var p = feature.properties;
                        layer.featureProperties = p;
                        layer.currentSafetyBand = p.has_weather ? 'default' : 'no_data';
                        layer.currentStars = 0;
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

                // Nach dem Laden an alle Spots anpassen (Gesamtansicht Schweiz)
                try {
                    var bounds = geoJsonLayer.getBounds();
                    if (bounds && bounds.isValid()) {
                        window.gleitcastSpotsBounds = bounds;
                        map.fitBounds(bounds, { padding: [20, 20] });
                    }
                } catch (e) {
                    console.warn('fitBounds fehlgeschlagen:', e);
                }
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
        // Capture experience-score + stars fuer Share-Text (Hero-Block zeigt
        // Rating selbst — kein separates Badge mehr).
        currentSpotExperienceScore = (analysis && typeof analysis.experience_score === 'number') ? analysis.experience_score : null;
        currentSpotExperienceStars = (analysis && typeof analysis.experience_stars === 'number') ? analysis.experience_stars : null;
        renderFeedbackBar(currentSpotName, dateStr, analysis);
    }

    function renderFeedbackBar(spotName, dateStr, analysis) {
        if (!feedbackBar || !spotName) return;
        // Bei Analyse-Fehler / no_data kein Feedback-Widget anzeigen
        var status = analysis && analysis.safety_status;
        if (!status || status === 'error' || status === 'no_data') {
            feedbackBar.innerHTML = '';
            feedbackBar.style.display = 'none';
            return;
        }
        feedbackBar.style.display = '';
        feedbackBar.innerHTML = '';
        var mount = document.createElement('div');
        mount.setAttribute('data-fb-mount', '');
        mount.setAttribute('data-fb-type', 'spot');
        mount.setAttribute('data-fb-target', spotName);
        if (dateStr) mount.setAttribute('data-fb-date', dateStr);
        feedbackBar.appendChild(mount);
        if (window.Feedback && window.Feedback.scan) window.Feedback.scan(feedbackBar);
    }

    // ===== METEOGRAM OVERLAY =====
    function openMeteogram(spotName, props) {
        currentSpotName = spotName;
        currentSpotProps = props || null;
        currentSpotExperienceScore = null;
        currentSpotExperienceStars = null;
        titleEl.textContent = spotName;
        infoEl.textContent = props
            ? props.fluggebiet + ' | ' + props.elevation_m + 'm MSL | ' + props.windrichtung
            : '';
        chartContainer.innerHTML = '<div class="error-state">Lade Daten...</div>';
        if (analyseViewContainer) analyseViewContainer.innerHTML = '<div class="mg-analysis-empty">Lade Analyse...</div>';
        tabsContainer.innerHTML = '';
        if (feedbackBar) { feedbackBar.innerHTML = ''; feedbackBar.style.display = 'none'; }
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
            thresholds: currentWeather.thresholds,
        });

        // Wetter-Zeitstempel + Modell unter dem Spot-Meteogramm
        var existingTs = chartContainer.querySelector('.meteogram-weather-ts');
        if (existingTs) existingTs.remove();
        var tsDiv = document.createElement('div');
        tsDiv.className = 'meteogram-weather-ts';
        tsDiv.style.cssText = 'font-size:10px;color:#94a3b8;text-align:right;padding:2px 8px 0;';
        var parts = ['Modell: ' + WIND_MODEL_LABEL];
        if (currentWeather.last_updated) {
            parts.push('Wetter-Stand: ' + currentWeather.last_updated.replace('T', ' ').slice(0, 16));
        }
        tsDiv.textContent = parts.join(' · ');
        chartContainer.appendChild(tsDiv);

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
    window.addEventListener('gleitcast-analyses-loaded', function () {
        renderAnalyseView();
    });

    // Listen for day changes from the floating map tabs
    window.addEventListener('gleitcast-day-change', function (e) {
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
            if (!currentSpotName || typeof window.gleitcastShare !== 'function') return;
            var regionId = (currentSpotProps && currentSpotProps.region_id) || '';
            var regionName = (currentSpotProps && currentSpotProps.region) || '';
            var rText = '';
            if (currentSpotExperienceStars != null && currentSpotExperienceStars >= 1) {
                rText = ' — ' + currentSpotExperienceStars + (currentSpotExperienceStars === 1 ? ' Stern' : ' Sterne');
                if (currentSpotExperienceScore != null) rText += ' · ' + currentSpotExperienceScore + '/100';
            }
            var dayIdx = 0;
            if (window.currentDate && currentDates && currentDates.length) {
                var idx = currentDates.indexOf(window.currentDate);
                if (idx >= 0) dayIdx = idx;
            }
            window.gleitcastShare({
                region_id: regionId,
                day_idx: dayIdx,
                spot: currentSpotName,
                title: currentSpotName + rText,
                text: currentSpotName + (regionName ? ' (' + regionName + ')' : '') + rText + ' · Gleitcast Flugwetter',
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
        // Reset all markers to their current analysis state
        Object.values(markersByName).forEach(function (marker) {
            var band = marker.currentSafetyBand || 'default';
            var stars = marker.currentStars || 0;
            marker.setIcon(createSpotIcon(marker.featureProperties, band, stars, false));
            if (marker.getElement()) marker.getElement().style.zIndex = '';
        });

        if (!items || !Array.isArray(items)) return;

        // Highlight selected
        items.forEach(function (item) {
            var name = typeof item === 'string' ? item : item.name;
            var marker = markersByName[name];
            if (marker) {
                var band = marker.currentSafetyBand || 'default';
                var stars = marker.currentStars || 0;
                marker.setIcon(createSpotIcon(marker.featureProperties, band, stars, true));
                if (marker.getElement()) marker.getElement().style.zIndex = 1000;
            }
        });
    };

    // ===== SPOT COLORING (from LLM analyses, RATING_CONCEPT v1.3) =====
    // Reads safety_band + experience_stars (with legacy fallback to safety_status/fly_status).
    window.updateSpotColors = function (analysisData, dateStr) {
        // analysisData: {spot_name: {date_str: {safety_band, experience_stars, ...}}}
        if (!analysisData || !dateStr) return;

        Object.keys(markersByName).forEach(function (name) {
            var marker = markersByName[name];
            var spotAnalysis = analysisData[name];
            var dayData = spotAnalysis && spotAnalysis[dateStr];

            if (!dayData) {
                // No analysis for this date → reset to no_data
                marker.currentSafetyBand = 'no_data';
                marker.currentStars = 0;
                marker.currentSafety = 'no_data';
                marker.currentQuality = 'green';
                marker.setIcon(createSpotIcon(marker.featureProperties, 'no_data', 0, false));
                marker.setTooltipContent(buildTooltipHtml(marker.featureProperties, null, 'no_data', 0, dayData));
                return;
            }

            // Prefer new fields, fall back to legacy
            var band = dayData.safety_band || legacySafetyBand(dayData.safety_status);
            var stars = (typeof dayData.experience_stars === 'number') ? dayData.experience_stars : 0;

            marker.currentSafetyBand = band;
            marker.currentStars = stars;
            // Legacy fields for compat (other code paths may still read these)
            marker.currentSafety = dayData.safety_status || 'safe';
            marker.currentQuality = dayData.fly_status || 'green';

            marker.setIcon(createSpotIcon(marker.featureProperties, band, stars, false));
            marker.setTooltipContent(buildTooltipHtml(marker.featureProperties, null, band, stars, dayData));
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
                        var hasAnalysis = marker.currentSafetyBand
                            && marker.currentSafetyBand !== 'default'
                            && marker.currentSafetyBand !== 'no_data';
                        if (!hasAnalysis) {
                            var band = p.has_weather ? 'default' : 'no_data';
                            marker.currentSafetyBand = band;
                            marker.currentStars = 0;
                            marker.currentSafety = band;
                            marker.currentQuality = 'green';
                            marker.setIcon(createSpotIcon(p, band, 0, false));
                        }
                        marker.setTooltipContent(buildTooltipHtml(
                            p, null, marker.currentSafetyBand, marker.currentStars, null
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
