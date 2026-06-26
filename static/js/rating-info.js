/**
 * Rating-Info-Overlay (RATING_ARCHITECTURE v2.0) — geteilt zwischen
 * Spot-Karte (map.js) und Region-Karte (region-map.js), damit beide Seiten
 * dieselbe "Wie funktioniert das Rating?"-Erklaerung zeigen.
 *
 * API:
 *   window.openRatingInfoOverlay()  — Modal oeffnen
 *   window.closeRatingInfoOverlay() — Modal schliessen
 *
 * Wird beim ersten Aufruf einmalig ans <body> angehaengt; wiederholte
 * Aufrufe schalten nur hidden um.
 */
(function () {
    'use strict';

    // Rating-Tints — Palette v2 (Option C, Mai 2026): green-Band alignt mit
    // Thermik-Kacheln (Lime/Mint-Green/Cyan), Rating 1+2 in Pastell-Mint/Mint.
    // amber bleibt Yellow→Brown. Synchron zu map.js, region-map.js, shared-glyph.js,
    // briefing.js. Source of Truth: docs/RATING_FARBKONZEPT.md.
    function _ratingTint(band, rating) {
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

    function _glyphSvg(band, stars, size) {
        var s = size || 28;
        var center = s / 2;
        var r = s * 0.36;
        var palette = {
            green:   { fill: '#22c55e', stroke: '#15803d' },
            amber:   { fill: '#f59e0b', stroke: '#92400e' },
            red:     { fill: '#ef4444', stroke: '#991b1b' },
            // Palette v3.2 "Royal Premium": violet-Band = Violet-400 (Legendary).
            violet:  { fill: '#a78bfa', stroke: '#6d28d9' },
            no_data: { fill: '#9ca3af', stroke: '#6b7280' }
        };
        var rating = (typeof stars === 'number') ? stars : 0;
        // Display-Band Premium-Override: safe + rating=5 → violett (analog map.js).
        if (band === 'green' && rating >= 5) band = 'violet';

        var c = palette[band] || palette.no_data;
        // Rating-Tint: Hue-Shift fuer 1-4 (green) bzw. 1-5 (amber). Bei violet/red/
        // no_data bleibt es bei der band-Farbe.
        if (rating > 0 && (band === 'green' || band === 'amber')) {
            var tint = _ratingTint(band, rating);
            if (tint) c = tint;
        }

        var html = '<svg width="' + s + '" height="' + s + '" viewBox="0 0 ' + s + ' ' + s + '" aria-hidden="true">';
        html += '<circle cx="' + center + '" cy="' + center + '" r="' + r + '" fill="#ffffff" />';
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
        } else if (rating >= 1) {
            // Text-Kontrast (Palette v3.2): amber 3+, violet (Premium) UND
            // green Rating 4 (Green-500) haben dunkle Bgs → weisser Text.
            var darkBgHere = (band === 'violet')
                || (band === 'amber' && rating >= 3)
                || (band === 'green' && rating >= 4);
            var textFill = darkBgHere ? '#ffffff' : c.stroke;
            html += '<text x="' + center + '" y="' + (center + r * 0.35)
                  + '" text-anchor="middle" fill="' + textFill + '" font-family="Inter,sans-serif" font-size="'
                  + (r * 0.95).toFixed(1) + '" font-weight="700">' + rating + '</text>';
        }
        html += '</svg>';
        return html;
    }

    var _built = false;
    function _init() {
        if (_built) return;
        _built = true;
        var ov = document.createElement('div');
        ov.className = 'rating-info-overlay';
        ov.id = 'ratingInfoOverlay';
        ov.setAttribute('role', 'dialog');
        ov.setAttribute('aria-modal', 'true');
        ov.setAttribute('aria-labelledby', 'ratingInfoTitle');
        ov.hidden = true;

        ov.innerHTML =
            '<div class="rating-info-backdrop" data-action="close"></div>' +
            '<div class="rating-info-modal">' +
              '<div class="rating-info-header">' +
                '<h2 id="ratingInfoTitle">' + wcT('js.ri.title') + '</h2>' +
                '<button class="rating-info-close" data-action="close" aria-label="' + wcT('js.ri.close') + '" type="button">×</button>' +
              '</div>' +
              '<div class="rating-info-body">' +

                '<div class="rating-info-section">' +
                  '<p class="rating-info-lead">' + wcT('js.ri.lead') + '</p>' +
                '</div>' +

                '<div class="rating-info-section">' +
                  '<div class="rating-info-axes">' +
                    '<div class="rating-info-axis-card">' +
                      '<div class="rating-info-axis-title">' + wcT('js.ri.axis_color') + '</div>' +
                      '<div class="rating-info-row">' + _glyphSvg('green', 0, 28) + '<span>' + wcT('js.ri.color_green') + '</span></div>' +
                      '<div class="rating-info-row">' + _glyphSvg('amber', 0, 28) + '<span>' + wcT('js.ri.color_amber') + '</span></div>' +
                      '<div class="rating-info-row">' + _glyphSvg('red', 0, 28)   + '<span>' + wcT('js.ri.color_red') + '</span></div>' +
                    '</div>' +
                    '<div class="rating-info-axis-card">' +
                      '<div class="rating-info-axis-title">' + wcT('js.ri.axis_number') + '</div>' +
                      '<div class="rating-info-row">' + _glyphSvg('green', 1, 28) + '<span>' + wcT('js.ri.fly1') + '</span></div>' +
                      '<div class="rating-info-row">' + _glyphSvg('green', 2, 28) + '<span>' + wcT('js.ri.fly2') + '</span></div>' +
                      '<div class="rating-info-row">' + _glyphSvg('green', 3, 28) + '<span>' + wcT('js.ri.fly3') + '</span></div>' +
                      '<div class="rating-info-row">' + _glyphSvg('green', 4, 28) + '<span>' + wcT('js.ri.fly4') + '</span></div>' +
                      '<div class="rating-info-row">' + _glyphSvg('green', 5, 28) + '<span>' + wcT('js.ri.fly5') + '</span></div>' +
                    '</div>' +
                  '</div>' +
                '</div>' +

                '<div class="rating-info-section">' +
                  '<h3>' + wcT('js.ri.examples') + '</h3>' +
                  '<div class="rating-info-examples">' +
                    '<div class="rating-info-example">' + _glyphSvg('green', 5, 44) + '<div class="rating-info-example-label">' + wcT('js.ri.ex_xc') + '</div></div>' +
                    '<div class="rating-info-example">' + _glyphSvg('green', 4, 44) + '<div class="rating-info-example-label">' + wcT('js.ri.ex_strong') + '</div></div>' +
                    '<div class="rating-info-example">' + _glyphSvg('amber', 3, 44) + '<div class="rating-info-example-label">' + wcT('js.ri.ex_caution') + '</div></div>' +
                    '<div class="rating-info-example">' + _glyphSvg('red', 0, 44)   + '<div class="rating-info-example-label">' + wcT('js.ri.ex_notfly') + '</div></div>' +
                  '</div>' +
                '</div>' +

                '<div class="rating-info-section">' +
                  '<h3>' + wcT('js.ri.detail_title') + '</h3>' +
                  '<div class="rating-info-deeper">' +
                    '<dl>' +
                      '<dt>' + wcT('js.ri.dt_safety') + '</dt>' +
                      '<dd>' + wcT('js.ri.dd_safety') + '</dd>' +
                      '<dt>' + wcT('js.ri.dt_fly') + '</dt>' +
                      '<dd>' + wcT('js.ri.dd_fly') + '</dd>' +
                      '<dt>' + wcT('js.ri.dt_xc') + '</dt>' +
                      '<dd>' + wcT('js.ri.dd_xc') + '</dd>' +
                    '</dl>' +
                  '</div>' +
                '</div>' +

                '<div class="rating-info-section">' +
                  '<h3>' + wcT('js.ri.who_title') + '</h3>' +
                  '<p>' + wcT('js.ri.who_safety') + '</p>' +
                  '<p>' + wcT('js.ri.who_fly') + '</p>' +
                '</div>' +

              '</div>' +
            '</div>';
        document.body.appendChild(ov);

        ov.addEventListener('click', function (e) {
            var t = e.target;
            if (t && t.dataset && t.dataset.action === 'close') {
                window.closeRatingInfoOverlay();
            }
        });
        document.addEventListener('keydown', function (e) {
            if (e.key === 'Escape' && !ov.hidden) window.closeRatingInfoOverlay();
        });
    }

    window.openRatingInfoOverlay = function () {
        _init();
        var ov = document.getElementById('ratingInfoOverlay');
        if (!ov) return;
        ov.hidden = false;
        document.body.style.overflow = 'hidden';
        var closeBtn = ov.querySelector('.rating-info-close');
        if (closeBtn) closeBtn.focus();
    };
    window.closeRatingInfoOverlay = function () {
        var ov = document.getElementById('ratingInfoOverlay');
        if (!ov) return;
        ov.hidden = true;
        document.body.style.overflow = '';
    };

    /**
     * Standardisierte Mini-Legende (Pills + Hint + Info-Button).
     * Verwendet von map.js + region-map.js — gleicher Inhalt auf beiden Karten.
     * Returns Leaflet L.control.
     */
    window.buildRatingMiniLegend = function (L, position) {
        var ctl = L.control({ position: position || 'bottomleft' });
        ctl.onAdd = function () {
            var isMobile = window.innerWidth <= 639;
            var div = L.DomUtil.create('div', 'map-legend' + (isMobile ? ' collapsed' : ''));
            div.innerHTML =
                '<button class="map-legend-toggle" aria-label="' + wcT('js.ri.legend_toggle_aria') + '">' + wcT('js.ri.legend_toggle') + '</button>' +
                '<div class="map-legend-body">' +
                '<div class="map-legend-pills">' +
                    '<span class="map-legend-pill safety-green">' + wcT('js.safety.safe') + '</span>' +
                    '<span class="map-legend-pill safety-amber">' + wcT('js.safety.caution') + '</span>' +
                    '<span class="map-legend-pill safety-red">' + wcT('js.safety.not_flyable') + '</span>' +
                '</div>' +
                '<div class="map-legend-hint">' + wcT('js.ri.legend_hint') + '</div>' +
                '<button class="map-legend-info-btn" data-action="open-rating-info" type="button">' +
                    '<span class="map-legend-info-icon" aria-hidden="true">\u24D8</span>' +
                    '<span>' + wcT('js.ri.title') + '</span>' +
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
                window.openRatingInfoOverlay();
            });
            L.DomEvent.disableClickPropagation(div);
            return div;
        };
        return ctl;
    };
})();
