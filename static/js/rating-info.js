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
        var rating = (typeof stars === 'number') ? stars : 0;
        
        var fillOpacity = 1.0;
        if (rating > 0 && (band === 'green' || band === 'amber' || band === 'violet')) {
            fillOpacity = 0.4 + (Math.min(5, rating) / 5) * 0.6;
        }
        
        var html = '<svg width="' + s + '" height="' + s + '" viewBox="0 0 ' + s + ' ' + s + '" aria-hidden="true">';
        html += '<circle cx="' + center + '" cy="' + center + '" r="' + r + '" fill="#ffffff" />';
        html += '<circle cx="' + center + '" cy="' + center + '" r="' + r
              + '" fill="' + c.fill + '" fill-opacity="' + fillOpacity + '" stroke="' + c.stroke + '" stroke-width="2"/>';
        if (band === 'red') {
            var arm = r * 0.55;
            html += '<line x1="' + (center - arm) + '" y1="' + (center - arm)
                  + '" x2="' + (center + arm) + '" y2="' + (center + arm)
                  + '" stroke="#fff" stroke-width="2.5" stroke-linecap="round"/>';
            html += '<line x1="' + (center + arm) + '" y1="' + (center - arm)
                  + '" x2="' + (center - arm) + '" y2="' + (center + arm)
                  + '" stroke="#fff" stroke-width="2.5" stroke-linecap="round"/>';
        } else if (rating >= 1) {
            var textFill = (fillOpacity < 0.65) ? c.stroke : '#ffffff';
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
                '<h2 id="ratingInfoTitle">Wie funktioniert das Rating?</h2>' +
                '<button class="rating-info-close" data-action="close" aria-label="Schliessen" type="button">×</button>' +
              '</div>' +
              '<div class="rating-info-body">' +

                '<div class="rating-info-section">' +
                  '<p class="rating-info-lead">Jeder Spot oder Region wird auf <b>zwei unabhaengigen Achsen</b> eingeschaetzt — Sicherheit und Fliegbarkeit. Beides siehst du im selben Marker.</p>' +
                '</div>' +

                '<div class="rating-info-section">' +
                  '<div class="rating-info-axes">' +
                    '<div class="rating-info-axis-card">' +
                      '<div class="rating-info-axis-title">Farbe = Sicherheit</div>' +
                      '<div class="rating-info-row">' + _glyphSvg('green', 0, 28) + '<span><b>Gruen</b> — sicher fliegbar</span></div>' +
                      '<div class="rating-info-row">' + _glyphSvg('amber', 0, 28) + '<span><b>Orange</b> — Vorsicht, Caution-Notes beachten</span></div>' +
                      '<div class="rating-info-row">' + _glyphSvg('red', 0, 28)   + '<span><b>Rot</b> — nicht fliegbar</span></div>' +
                    '</div>' +
                    '<div class="rating-info-axis-card">' +
                      '<div class="rating-info-axis-title">Zahl = Fliegbarkeit (1\u20135)</div>' +
                      '<div class="rating-info-row">' + _glyphSvg('green', 1, 28) + '<span><b>1</b> — Abgleiter</span></div>' +
                      '<div class="rating-info-row">' + _glyphSvg('green', 2, 28) + '<span><b>2</b> — Kurzer Thermikflug (Suchtag)</span></div>' +
                      '<div class="rating-info-row">' + _glyphSvg('green', 3, 28) + '<span><b>3</b> — Solider Thermikflug</span></div>' +
                      '<div class="rating-info-row">' + _glyphSvg('green', 4, 28) + '<span><b>4</b> — Starker Thermikflug</span></div>' +
                      '<div class="rating-info-row">' + _glyphSvg('green', 5, 28) + '<span><b>5</b> — XC-Tag (Top-Tage als "Klassiker")</span></div>' +
                    '</div>' +
                  '</div>' +
                '</div>' +

                '<div class="rating-info-section">' +
                  '<h3>Beispiele</h3>' +
                  '<div class="rating-info-examples">' +
                    '<div class="rating-info-example">' + _glyphSvg('green', 5, 44) + '<div class="rating-info-example-label">XC-Tag / Klassiker</div></div>' +
                    '<div class="rating-info-example">' + _glyphSvg('green', 4, 44) + '<div class="rating-info-example-label">Starker Thermikflug</div></div>' +
                    '<div class="rating-info-example">' + _glyphSvg('amber', 3, 44) + '<div class="rating-info-example-label">Vorsicht — solid moeglich</div></div>' +
                    '<div class="rating-info-example">' + _glyphSvg('red', 0, 44)   + '<div class="rating-info-example-label">Nicht fliegbar</div></div>' +
                  '</div>' +
                '</div>' +

                '<div class="rating-info-section">' +
                  '<h3>Im Detail-Panel — die Tiefe</h3>' +
                  '<div class="rating-info-deeper">' +
                    '<dl>' +
                      '<dt>Sicherheits-Rating</dt>' +
                      '<dd>0–10. Aggregat aus bis zu 8 Sub-Aspekten: Bodenwind, Boeen, Hoehenwind, Foehn, Niederschlag, Gewitter, CAPE, Sicht. Aggregation per <b>Weakest-Link</b> — der schwaechste Aspekt zieht das Rating nach unten. Ein einzelnes Gewitter macht den Tag rot, auch wenn alle anderen Aspekte perfekt sind.</dd>' +
                      '<dt>Fliegbarkeit — Kategorie (1\u20135)</dt>' +
                      '<dd>Statt einer Zahl vergibt die KI eine <b>Kategorie</b> die der Pilot kennt: <b>Abgleiter</b> (1, keine Thermik), <b>Kurzer Thermikflug</b> (2, Suchtag mit 1\u20132h Thermik wenn Glueck), <b>Solider Thermikflug</b> (3, mehrere Stunden), <b>Starker Thermikflug</b> (4, lokal-XC), <b>XC-Tag</b> (5, Strecke 50\u2013150km+; "Klassiker" als Auszeichnung an Top-Tagen). Bei <b>nicht fliegbar</b> wird die Fliegbarkeit auf 1 gesetzt.</dd>' +
                      '<dt>Streckenflug-Rating (nur Spot)</dt>' +
                      '<dd>1\u20135 fuer XC-Potenzial. Kann sich stark von der Fliegbarkeit unterscheiden — ein Spot kann lokal stark sein (Fliegbarkeit 4) aber die Region erlaubt kein Wegfliegen (Streckenflug 2).</dd>' +
                    '</dl>' +
                  '</div>' +
                '</div>' +

                '<div class="rating-info-section">' +
                  '<h3>Wer entscheidet was?</h3>' +
                  '<p><b>Sicherheit:</b> KI + Decision-Engine. Das LLM beurteilt Aspekte, harte Sicherheits-Schwellen (Foehn-Durchbruch, Hoehenwind &gt; 30 km/h, Gewitter) <b>ueberschreiben</b> das LLM — ein gefaehrlicher Tag kann nicht "weggetextet" werden.</p>' +
                  '<p><b>Fliegbarkeit (Kategorie):</b> reine KI-Einschaetzung. Die KI waehlt eine der 5 Kategorien aus dem Pilot-Vokabular — kein Rechnen, kein Mittelwert. Bei <b>nicht sicher</b> faellt die Fliegbarkeit automatisch auf 1 (keine Belohnung ohne Sicherheit).</p>' +
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
                '<button class="map-legend-toggle" aria-label="Legende ein-/ausblenden">Legende</button>' +
                '<div class="map-legend-body">' +
                '<div class="map-legend-pills">' +
                    '<span class="map-legend-pill safety-green">Sicher</span>' +
                    '<span class="map-legend-pill safety-amber">Vorsicht</span>' +
                    '<span class="map-legend-pill safety-red">Nicht fliegbar</span>' +
                '</div>' +
                '<div class="map-legend-hint">Zahl im Marker = Fliegbarkeit (1\u20135)</div>' +
                '<button class="map-legend-info-btn" data-action="open-rating-info" type="button">' +
                    '<span class="map-legend-info-icon" aria-hidden="true">\u24D8</span>' +
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
                window.openRatingInfoOverlay();
            });
            L.DomEvent.disableClickPropagation(div);
            return div;
        };
        return ctl;
    };
})();
