/**
 * Gleitcast - Shared Analysis View Renderer
 *
 * Eine Analyse-Darstellung fuer Spot UND Region. Identisches Layout, identische
 * Reihenfolge, identische Wortwahl. Region-Spezifika (Top-Spots-Liste) werden
 * NICHT hier gerendert, sondern vom Aufrufer als separater Block UNTER der
 * Analyse-View eingehaengt.
 *
 * Kanonisches Layout:
 *   1) HERO        verdict + glyph + rationale + score-pills
 *   2) BEST WINDOW (nicht bei not_safe / empty)
 *   3) ALERTS      bei not_safe: PFLICHT-Begruendung
 *   4) METRICS     wind / flugtyp / dauer / peak / xc / streckenflug (spot)
 *   5) INSIGHTS    expandable: safety / fly / xc (spot)
 *   FOOTER         Datestamp
 *
 * Vier States:
 *   A) Empty        a == null oder a.safety_status fehlt -> "Datenanalyse ausstehend"
 *   B) Not-safe     safety_status === 'not_safe' || noAnalysis === true
 *   C) Conditional  safety_status === 'conditional'
 *   D) Safe         safety_status === 'safe'
 *
 * Usage:
 *   AnalysisView.render(container, dayData, { dateStr: '2026-05-01' });
 */
window.AnalysisView = (function () {
    'use strict';

    // ===== UTIL =====
    function esc(str) {
        if (str === null || str === undefined) return '';
        var div = document.createElement('div');
        div.textContent = String(str);
        return div.innerHTML;
    }

    function parseMaybeList(val) {
        if (!val) return [];
        if (Array.isArray(val)) return val;
        if (typeof val === 'string') {
            try { var p = JSON.parse(val); if (Array.isArray(p)) return p; } catch (e) { /* fall through */ }
            return val ? [val] : [];
        }
        return [];
    }

    // RATING_ARCHITECTURE v2.1: experience_rating 1-5
    function getRating(a) {
        if (!a) return 0;
        var er = parseInt(a.experience_rating, 10);
        if (!isFinite(er) || er < 1) return 0;
        // Migration-Tolerance: 6 → 5
        if (er === 6) return 5;
        return Math.min(5, er);
    }

    function getSafetyBand(a) {
        if (!a) return 'no_data';
        var s = a.safety_status || (a.safety && a.safety.safety_status);
        if (s === 'safe') return 'green';
        if (s === 'conditional') return 'amber';
        if (s === 'not_safe') return 'red';
        if (s === 'error') return 'red';
        return 'no_data';
    }

    // ===== GLYPH =====
    // Kreis in Rating-Tint-Farbe; weisses Kreuz bei red, Rating-Ziffer 1-5 sonst.
    // Palette v2 (Option C, Mai 2026) — synchron zu region-map.js, map.js,
    // shared-glyph.js, briefing.js. Source of Truth: docs/RATING_FARBKONZEPT.md.
    var PALETTE = {
        green:   { fill: '#22c55e', stroke: '#15803d' },
        amber:   { fill: '#f59e0b', stroke: '#92400e' },
        red:     { fill: '#ef4444', stroke: '#991b1b' },
        // v3 Royal Premium: violet-Band = Violet-400 (Legendaer/Top).
        violet:  { fill: '#a78bfa', stroke: '#6d28d9' },
        no_data: { fill: '#9ca3af', stroke: '#6b7280' }
    };

    function hexToRgbStr(hex) {
        if (!hex || hex[0] !== '#') return '0,0,0';
        var h = hex.slice(1);
        return parseInt(h.slice(0, 2), 16) + ',' + parseInt(h.slice(2, 4), 16) + ',' + parseInt(h.slice(4, 6), 16);
    }

    // Rating-Tint analog briefing.js:regionPillSpec — gibt {fill, stroke, text,
    // darkBg} fuer die {band, rating}-Kombination zurueck. Verwendet fuer
    // Hero-Glyph + Rating-Pill + Container-Akzent im Spot/Region-Detail.
    function ratingTintSpec(band, rating) {
        var r = Math.max(0, Math.min(5, parseInt(rating, 10) || 0));
        if (band === 'red') {
            return { label: 'Nicht fliegbar', fill: '#ef4444', stroke: '#991b1b', text: '#ffffff', darkBg: true };
        }
        if (band === 'no_data') {
            return { label: 'Keine Daten', fill: '#9ca3af', stroke: '#6b7280', text: '#374151', darkBg: false };
        }
        if (r <= 0) return null;
        if (band === 'amber') {
            var aLabels = ['Abgleiter', 'Schwacher Thermiktag', 'Solider Thermiktag', 'Starker Thermiktag', 'XC-Tag'];
            var aBgs    = ['#fef08a', '#facc15', '#f97316', '#c2410c', '#7c2d12'];
            var aBorders= ['#ca8a04', '#a16207', '#9a3412', '#7c2d12', '#431407'];
            var aTexts  = ['#713f12', '#713f12', '#ffffff', '#ffffff', '#ffffff'];
            var aDark   = [false, false, true, true, true];
            var ai = Math.min(4, r - 1);
            return { label: aLabels[ai], fill: aBgs[ai], stroke: aBorders[ai], text: aTexts[ai], darkBg: aDark[ai] };
        }
        // safe/green v3.2 Royal Premium: Sky-100 → Sky-200 → Lime → Green-500 → Violet (Top)
        var gLabels = ['Abgleiter', 'Kurzer Thermikflug', 'Solider Thermiktag', 'Starker Thermiktag', 'XC-Tag'];
        var gBgs    = ['#e0f2fe', '#bae6fd', '#BEF264', '#22c55e', '#a78bfa'];
        var gBorders= ['#38bdf8', '#0ea5e9', '#65a30d', '#15803d', '#6d28d9'];
        var gTexts  = ['#075985', '#075985', '#3f6212', '#ffffff', '#ffffff'];
        var gDarkBg = [false, false, false, true, true];  // Rating 4 (Green-500) + 5 (Violet) = weisser Text
        var gi = Math.min(4, r - 1);
        return { label: gLabels[gi], fill: gBgs[gi], stroke: gBorders[gi], text: gTexts[gi], darkBg: gDarkBg[gi] };
    }

    function buildGlyph(band, rating, size) {
        var s = size || 96;
        var c = s / 2;
        var r = s * 0.32;
        // Rating-Tint statt flacher Band-Farbe — synchron zu shared-glyph.js.
        var tint = ratingTintSpec(band, rating);
        var fill = tint ? tint.fill : (PALETTE[band] || PALETTE.no_data).fill;
        var stroke = tint ? tint.stroke : (PALETTE[band] || PALETTE.no_data).stroke;
        var textFill = (tint && tint.darkBg) ? '#ffffff' : (tint ? tint.stroke : '#ffffff');
        var label = (band === 'red') ? 'Nicht fliegbar' :
                    (band === 'no_data') ? 'Keine Analyse' :
                    (rating >= 1 ? 'Rating ' + rating + ' von 5' : 'Bewertung');
        var html = '<svg width="' + s + '" height="' + s + '" viewBox="0 0 ' + s + ' ' + s
                 + '" role="img" aria-label="' + esc(label) + '">';
        html += '<circle cx="' + c + '" cy="' + c + '" r="' + r
              + '" fill="' + fill + '" stroke="' + stroke + '" stroke-width="3"/>';
        if (band === 'red') {
            var arm = r * 0.55;
            html += '<line x1="' + (c - arm) + '" y1="' + (c - arm)
                  + '" x2="' + (c + arm) + '" y2="' + (c + arm)
                  + '" stroke="#fff" stroke-width="6" stroke-linecap="round"/>';
            html += '<line x1="' + (c + arm) + '" y1="' + (c - arm)
                  + '" x2="' + (c - arm) + '" y2="' + (c + arm)
                  + '" stroke="#fff" stroke-width="6" stroke-linecap="round"/>';
        } else if (band === 'no_data') {
            html += '<text x="' + c + '" y="' + (c + r * 0.32)
                  + '" text-anchor="middle" fill="#fff" font-family="Inter,sans-serif" font-size="'
                  + (r * 0.85).toFixed(1) + '" font-weight="700">…</text>';
        } else if (rating >= 1) {
            var fontSize = (r * 0.85).toFixed(1);
            html += '<text x="' + c + '" y="' + (c + r * 0.34)
                  + '" text-anchor="middle" fill="' + textFill + '" font-family="Inter,sans-serif" font-size="'
                  + fontSize + '" font-weight="700">' + rating + '</text>';
        } else {
            html += '<circle cx="' + c + '" cy="' + c + '" r="3" fill="#fff"/>';
        }
        html += '</svg>';
        return html;
    }

    // ===== HERO =====
    // Hero zeigt Glyph (Rating im Kreis) + Verdict-Label + Pills.
    // Die textuelle Einschaetzung gehoert NICHT hier rein — sie wird unten in
    // renderInsights als aufklappbare "Sicherheits-Einschaetzung" gezeigt.
    function renderHero(a, isEmpty) {
        if (isEmpty) {
            return '<div class="mga-hero no_data">'
                 + '<div class="mga-hero-glyph">' + buildGlyph('no_data', 0, 96) + '</div>'
                 + '<div class="mga-hero-text">'
                 + '<div class="mga-hero-verdict no_data">Datenanalyse ausstehend</div>'
                 + '</div></div>';
        }

        var band = getSafetyBand(a);
        var rating = getRating(a);
        var verdictTxt = (band === 'green') ? 'Sicher' :
                         (band === 'amber') ? 'Vorsicht' :
                         (band === 'red')   ? 'Nicht fliegbar' : 'Keine Daten';

        // Container-Tint aus Rating-Tint-Palette (Option C). Soft bg (12% alpha)
        // + saturierter Border-Left — gleiche Logik wie Spot-Bg in briefing.js,
        // damit ein gruener Tag mit Rating 4 hier auch Mint-Green wirkt, nicht
        // einheitlich "green".
        var heroTint = ratingTintSpec(band, rating);
        var heroStyle = '';
        if (heroTint && band !== 'no_data') {
            var hRgb = hexToRgbStr(heroTint.fill);
            heroStyle = 'style="background:rgba(' + hRgb + ',0.12);border-color:' + heroTint.stroke + '"';
        }
        var html = '<div class="mga-hero ' + band + '" ' + heroStyle + '>'
                 + '<div class="mga-hero-glyph">' + buildGlyph(band, rating, 96) + '</div>'
                 + '<div class="mga-hero-text">'
                 + '<div class="mga-hero-verdict ' + band + '">' + esc(verdictTxt) + '</div>';
        // Pills: Safety-Band + Rating. RATING_ARCHITECTURE v2.0 + Palette v2.
        html += '<div class="mga-hero-pills">';
        html += '<span class="mga-hero-pill ' + band + '">Safety ' + band.toUpperCase() + '</span>';
        if (band !== 'red' && band !== 'no_data') {
            // Rating-Pill mit Rating-Tint-Farbe (Palette v2 Option C) — inline-style
            // damit alle 5 Stufen visuell unterscheidbar sind, nicht nur 3 Tiers.
            if (rating >= 1) {
                var pTint = ratingTintSpec(band, rating);
                if (pTint) {
                    var pBg = pTint.fill;
                    var pBorder = pTint.stroke;
                    var pText = pTint.text;
                    html += '<span class="mga-hero-pill mga-hero-pill--fly"'
                         + ' style="background:' + pBg + ';border:1px solid ' + pBorder + ';color:' + pText + '">'
                         + esc(pTint.label) + ' (' + rating + '/5)</span>';
                }
            }
            var fly = a.flyability || {};
            // Key flyability fields
            if (fly.flight_type)              html += '<span class="mga-hero-pill">Typ: ' + esc(fly.flight_type) + '</span>';
            if (fly.flight_duration_estimate) html += '<span class="mga-hero-pill">' + esc(fly.flight_duration_estimate) + '</span>';
            if (typeof fly.peak_climb_rate === 'number' && fly.peak_climb_rate > 0) {
                html += '<span class="mga-hero-pill">Peak ↑' + fly.peak_climb_rate.toFixed(1) + ' m/s</span>';
            }
            if (fly.xc_potential && fly.xc_potential !== 'none') {
                html += '<span class="mga-hero-pill">XC: ' + esc(fly.xc_potential) + '</span>';
            }
        }
        html += '</div></div></div>';
        return html;
    }

    // ===== V4/V5 TAG-SYSTEM (siehe docs/TAGS.md) =====
    // Single source of truth: a.tags + a.start_window aus Backend (Hybrid v5).

    var TAG_SEVERITY_ORDER_V4 = ['stop', 'warn', 'good', 'info'];
    var TAG_SEVERITY_LABEL_V4 = { stop: 'STOP', warn: 'WARN', good: 'GOOD', info: 'Hinweis' };
    var TAG_SEVERITY_ICON_V4  = { stop: '⛔', warn: '⚠', good: '✓', info: 'ℹ' };
    var TAG_TOPIC_ORDER_V4 = [
        'WIND_GROUND', 'WIND_ALOFT', 'FOEHN', 'RAIN',
        'THUNDERSTORM', 'CLOUDS', 'THERMAL', 'XC', 'TURBULENCE'
    ];
    var WINDOW_LABEL_V4 = { startbar: 'Startbar', sportlich: 'Sportlich', blockiert: 'Blockiert', neutral: 'Ausserhalb' };

    function _topicSortKeyV4(topic) {
        var i = TAG_TOPIC_ORDER_V4.indexOf(topic);
        return i === -1 ? 999 : i;
    }

    // Fester Anzeige-Rahmen 06:00–21:00 (parallel zum Wochencast).
    var WINDOW_HOUR_START_V4 = 6;
    var WINDOW_HOUR_END_V4 = 21;

    // Startfenster — UI/UX-Pro-Max Layout (parallel zum Wochencast):
    // Antwort zuerst (✓/▲/✕ + Zeitspanne + Dauer-Pille), dann durchgehende
    // Farbleiste, Tick-Achse alle 3 h, optional Sportlich-Sekundaerinfo.
    // Achse ist immer 6h-20h, fehlende Stunden = neutral.
    function renderStartWindowV4(startWindow) {
        if (!Array.isArray(startWindow)) return '';
        var byHour = {};
        for (var bi = 0; bi < startWindow.length; bi++) {
            var be = startWindow[bi];
            if (!be || typeof be.hour !== 'number') continue;
            byHour[be.hour] = be.state || 'neutral';
        }
        var sorted = [];
        for (var h = WINDOW_HOUR_START_V4; h < WINDOW_HOUR_END_V4; h++) {
            sorted.push({ hour: h, state: byHour[h] || 'neutral' });
        }

        function fmt(h) { return ('0' + h).slice(-2); }

        // Laengsten Run pro State suchen.
        function longestRun(state) {
            var best = { len: 0, start: null, end: null };
            var cur = { state: null, len: 0, start: null, end: null };
            for (var i = 0; i < sorted.length; i++) {
                var e = sorted[i];
                if (e.state === cur.state) { cur.len += 1; cur.end = e.hour; }
                else {
                    if (cur.state === state && cur.len > best.len) { best = { len: cur.len, start: cur.start, end: cur.end }; }
                    cur = { state: e.state, len: 1, start: e.hour, end: e.hour };
                }
            }
            if (cur.state === state && cur.len > best.len) { best = { len: cur.len, start: cur.start, end: cur.end }; }
            return best;
        }
        var bestStartbar = longestRun('startbar');
        var bestSport = longestRun('sportlich');

        // Kontinuierliche Farbleiste — ein Segment pro Stunde, ohne Glyphs.
        var segments = sorted.map(function (e) {
            var st = e.state || 'neutral';
            var hr = fmt(e.hour);
            var lbl = WINDOW_LABEL_V4[st] || '—';
            return '<span class="mga-window-seg mga-window-seg--' + st + '" '
                 + 'title="' + hr + ':00 Uhr · ' + lbl + '"></span>';
        }).join('');

        // Tick-Achse — Beschriftung nur alle 3 Stunden.
        var ticks = sorted.map(function (e) {
            var show = e.hour % 3 === 0;
            var lbl = show ? fmt(e.hour) : '';
            return '<span class="mga-window-tick' + (show ? ' mga-window-tick--major' : '') + '">' + lbl + '</span>';
        }).join('');

        // Inline-SVG-Icons (Lucide-Style) statt Unicode-Glyphs.
        var ICON_CHECK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="20 6 9 17 4 12"/></svg>';
        var ICON_ALERT = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>';
        var ICON_X     = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';

        // Primaer-Antwort.
        var primaryIcon, primaryText, primaryClass, durationLen = 0;
        if (bestStartbar.len > 0) {
            primaryIcon = ICON_CHECK;
            primaryClass = 'is-good';
            primaryText = fmt(bestStartbar.start) + ':00 – ' + fmt(bestStartbar.end + 1) + ':00 Uhr';
            durationLen = bestStartbar.len;
        } else if (bestSport.len > 0) {
            primaryIcon = ICON_ALERT;
            primaryClass = 'is-warn';
            primaryText = 'Nur sportlich ' + fmt(bestSport.start) + ':00 – ' + fmt(bestSport.end + 1) + ':00 Uhr';
            durationLen = bestSport.len;
        } else {
            primaryIcon = ICON_X;
            primaryClass = 'is-bad';
            primaryText = 'Heute nicht startbar';
        }
        var durationHtml = durationLen > 0
            ? '<span class="mga-window-duration">' + durationLen + ' h</span>'
            : '';

        // Sekundaerinfo (Sportlich-Hinweis, falls auch Startbar vorhanden).
        var secondary = '';
        if (bestStartbar.len > 0 && bestSport.len > 0) {
            secondary = '<div class="mga-window-secondary">'
                      + '<span class="mga-window-dot mga-window-dot--sportlich"></span>'
                      + 'Sportlich ' + fmt(bestSport.start) + ':00 – ' + fmt(bestSport.end + 1) + ':00 Uhr'
                      + '</div>';
        }

        return '<section class="mga-window-v4">'
             + '<header class="mga-window-v4-head">'
             + '<span class="mga-window-v4-title">Startfenster</span>'
             + '<span class="mga-window-v4-summary mga-window-v4-summary--' + primaryClass + '">'
             + '<span class="mga-window-v4-summary-icon" aria-hidden="true">' + primaryIcon + '</span>'
             + '<span class="mga-window-v4-summary-text">' + esc(primaryText) + '</span>'
             + durationHtml
             + '</span>'
             + '</header>'
             + '<div class="mga-window-v4-bar" role="img" aria-label="Startfenster-Verlauf ueber den Tag">' + segments + '</div>'
             + '<div class="mga-window-v4-axis" aria-hidden="true">' + ticks + '</div>'
             + secondary
             + '</section>';
    }

    function renderTagGroupsV4(tags) {
        if (!Array.isArray(tags) || !tags.length) return '';
        var byLevel = { stop: [], warn: [], good: [], info: [] };
        for (var i = 0; i < tags.length; i++) {
            var t = tags[i];
            if (!t || !byLevel[t.severity]) continue;
            byLevel[t.severity].push(t);
        }
        for (var j = 0; j < TAG_SEVERITY_ORDER_V4.length; j++) {
            var sev = TAG_SEVERITY_ORDER_V4[j];
            byLevel[sev].sort(function (a, b) { return _topicSortKeyV4(a.topic) - _topicSortKeyV4(b.topic); });
        }
        var groupsHtml = TAG_SEVERITY_ORDER_V4
            .filter(function (sev) { return byLevel[sev].length > 0; })
            .map(function (sev) {
                var rows = byLevel[sev].map(function (t) {
                    var v = t.value ? '<span class="mga-tag-value">' + esc(t.value) + '</span>' : '<span class="mga-tag-value"></span>';
                    var tm = t.time ? '<span class="mga-tag-time">' + esc(t.time) + '</span>' : '<span class="mga-tag-time"></span>';
                    return '<div class="mga-tag-row">'
                         + '<span class="mga-tag-topic">' + esc(t.label || t.topic) + '</span>'
                         + v + tm + '</div>';
                }).join('');
                return '<div class="mga-tag-group mga-tag-group--' + sev + '">'
                     + '<div class="mga-tag-group-header">'
                     + '<span class="mga-tag-group-icon" aria-hidden="true">' + TAG_SEVERITY_ICON_V4[sev] + '</span>'
                     + '<span class="mga-tag-group-label">' + TAG_SEVERITY_LABEL_V4[sev] + '</span>'
                     + '</div>'
                     + '<div class="mga-tag-rows">' + rows + '</div>'
                     + '</div>';
            }).join('');
        return groupsHtml;
    }

    function getV4Tags(a) {
        if (!a) return [];
        if (Array.isArray(a.tags)) return a.tags;
        if (a.safety && Array.isArray(a.safety.tags)) return a.safety.tags;
        return [];
    }

    function getV4StartWindow(a) {
        if (!a) return [];
        if (Array.isArray(a.start_window)) return a.start_window;
        if (a.safety && Array.isArray(a.safety.start_window)) return a.safety.start_window;
        return [];
    }

    // ===== METRICS =====
    function renderMetrics(a) {
        var html = '<div class="mga-metrics">';
        html += '<div class="mga-metric full-width">'
              + '<div class="mga-metric-label">Wind</div>'
              + '<div class="mga-metric-value">' + esc(a.wind_summary || '-') + '</div>'
              + '</div>';
        if (a.flight_type) {
            html += '<div class="mga-metric">'
                  + '<div class="mga-metric-label">Flugtyp</div>'
                  + '<div class="mga-metric-value">' + esc(a.flight_type) + '</div>'
                  + '</div>';
        }
        var duration = a.flight_duration_estimate || a.flight_duration || '';
        if (duration) {
            html += '<div class="mga-metric">'
                  + '<div class="mga-metric-label">Dauer</div>'
                  + '<div class="mga-metric-value">' + esc(duration) + '</div>'
                  + '</div>';
        }
        if (a.peak_climb_rate) {
            html += '<div class="mga-metric">'
                  + '<div class="mga-metric-label">Peak Thermik</div>'
                  + '<div class="mga-metric-value">' + esc(a.peak_climb_rate) + ' m/s</div>'
                  + '</div>';
        }
        if (a.xc_potential) {
            html += '<div class="mga-metric">'
                  + '<div class="mga-metric-label">XC-Potenzial</div>'
                  + '<div class="mga-metric-value">' + esc(a.xc_potential) + '</div>'
                  + '</div>';
        }
        // Streckenflug-Metric (Spot) — RATING_ARCHITECTURE v2.1: rating 1-5 + limiting_factor.
        var sfRating = parseInt(a.streckenflug_rating, 10);
        if (isFinite(sfRating) && sfRating >= 1) {
            var SF_RATING_LABELS = {
                1: 'kein XC', 2: 'ganz kurz', 3: 'lokal', 4: 'kurz wegfliegen',
                5: 'weit', 6: 'klassiker'
            };
            var sfLabel = SF_RATING_LABELS[sfRating] || ('Rating ' + sfRating);
            var sfTierClass = (sfRating >= 5) ? 'top' : (sfRating >= 4 ? 'moderat' : (sfRating >= 3 ? 'lokal' : 'kein_xc'));
            var sfHtml = '<span class="mga-sf-badge ' + sfTierClass + '">' + esc(sfLabel) + '</span>'
                       + ' <span class="mga-sf-rating">' + sfRating + '/6</span>';
            html += '<div class="mga-metric full-width streckenflug">'
                  + '<div class="mga-metric-label">Streckenflug</div>'
                  + '<div class="mga-metric-value">' + sfHtml + '</div>'
                  + '</div>';
        }
        html += '</div>';
        return html;
    }

    // ===== INSIGHTS =====
    var SF_LIMIT_LABELS = {
        none:                   '',
        region_wind_aloft:      'Region-Höhenwinde bremsen den Streckenflug.',
        weak_regional_thermals: 'Region-Thermik ist zu schwach für Strecke.',
        ceiling_low:            'Basis bleibt zu tief für längere Strecken.',
        spot_wind_direction:    'Wind kommt aus falschem Sektor.',
        abgleiter_only:         'Nur Abgleiter möglich — keine Strecke.',
        spot_not_flyable:       'Spot heute nicht fliegbar.',
        region_context_missing: 'Region-Kontext fehlt — reine Spot-Einschätzung.'
    };

    var SF_RATING_LABELS = {
        1: 'Kein Streckenflug',
        2: 'Lokal fliegbar (kein Wegfliegen)',
        3: 'Kurzes Wegfliegen möglich (~10–30 km)',
        4: 'Weite Strecke möglich (~30–100 km)',
        5: 'Klassiker (>100 km)'
    };

    var RATING_LABELS_LONG = {
        1: 'Abgleiter — kein Thermikflug',
        2: 'Kurzer Thermikflug — Suchtag (1–2 h mit Glück)',
        3: 'Solider Thermikflug — typischer Sommertag',
        4: 'Starker Thermikflug — lokal-XC möglich',
        5: 'XC-Tag — 50–150 km+ (Top-Tage als "Klassiker")'
    };

    function renderInsights(a) {
        var safetyFb = a.safety_feedback || a.summary || '';
        var flyFb = a.flyability_feedback || a.recommendation || '';
        var rating = parseInt(a.experience_rating, 10);
        var sfLimit = a.streckenflug_limiting_factor || 'none';
        var sfRating = parseInt(a.streckenflug_rating, 10);
        var hasRating = isFinite(rating) && rating >= 1;
        var hasSfRating = isFinite(sfRating) && sfRating >= 1;

        if (!safetyFb && !flyFb && !hasRating && !hasSfRating) return '';

        var html = '<div class="mga-insights">';
        if (safetyFb) {
            html += '<div class="mga-insight safety open">'
                  + '<button class="mga-insight-toggle" type="button">Sicherheits-Einschätzung</button>'
                  + '<div class="mga-insight-body">' + esc(safetyFb) + '</div>'
                  + '</div>';
        }
        if (flyFb || hasRating) {
            var flyBody = '';
            if (hasRating) {
                flyBody += '<div class="mga-insight-rating"><b>' + esc(RATING_LABELS_LONG[rating] || ('Rating ' + rating))
                         + '</b> (' + rating + '/5)</div>';
            }
            if (flyFb) flyBody += '<div>' + esc(flyFb) + '</div>';
            html += '<div class="mga-insight flyability open">'
                  + '<button class="mga-insight-toggle" type="button">Flug-Einschätzung</button>'
                  + '<div class="mga-insight-body">' + flyBody + '</div>'
                  + '</div>';
        }
        if (hasSfRating) {
            var sfBody = '<div class="mga-insight-rating"><b>' + esc(SF_RATING_LABELS[sfRating] || ('Rating ' + sfRating))
                       + '</b> (' + sfRating + '/5)</div>';
            var limitText = SF_LIMIT_LABELS[sfLimit] || '';
            if (limitText) sfBody += '<div>' + esc(limitText) + '</div>';
            html += '<div class="mga-insight streckenflug open">'
                  + '<button class="mga-insight-toggle" type="button">Streckenflug-Einschätzung</button>'
                  + '<div class="mga-insight-body">' + sfBody + '</div>'
                  + '</div>';
        }
        html += '</div>';
        return html;
    }

    // ===== FOOTER =====
    function renderFooter(dateStr) {
        if (!dateStr) return '';
        return '<div class="mg-analysis-datestamp">Analyse: ' + esc(dateStr) + '</div>';
    }

    function wireToggles(root) {
        root.querySelectorAll('.mga-insight-toggle').forEach(function (btn) {
            btn.addEventListener('click', function (e) {
                e.stopPropagation();
                btn.parentElement.classList.toggle('open');
            });
        });
    }

    // ===== ADMIN-FEEDBACK (Few-Shot-Pipeline Schritt 1) =====
    var EXPERIENCE_LABELS = [
        [1, '1 — Abgleiter'],
        [2, '2 — Kurzer Thermikflug (Suchtag)'],
        [3, '3 — Solider Thermikflug'],
        [4, '4 — Starker Thermikflug'],
        [5, '5 — XC-Tag / Klassiker']
    ];
    var SAFETY_OPTIONS = [
        ['safe', 'Safe'],
        ['conditional', 'Conditional'],
        ['not_safe', 'Not safe']
    ];

    function _regionIdFor(a) {
        // Cache verwendet stabilen Slug als Dict-Key; im Frontend liegt der
        // Slug oft nicht direkt am Analyse-Objekt. region_id wird bei Bedarf
        // vom Aufrufer via opts.regionId gesetzt; sonst Fallback auf region_name.
        return (a && (a.region_id || a.regionSlug)) || '';
    }

    // Slugify-Mirror der Python-Funktion engine.labeled_examples.slugify_spot.
    // Umlaute expandieren (ae/oe/ue/ss), alles Nicht-Alphanumeric zu '_'.
    function _slugifySpot(name) {
        if (!name) return '';
        var s = String(name).toLowerCase()
            .replace(/\u00e4/g, 'ae').replace(/\u00f6/g, 'oe').replace(/\u00fc/g, 'ue')
            .replace(/\u00df/g, 'ss');
        s = s.replace(/[^a-z0-9]+/g, '_');
        return s.replace(/^_+|_+$/g, '');
    }

    function renderAdminFeedback(a, dateStr, opts) {
        // opts: { isRegion, regionId, spotName }
        opts = opts || {};
        var kind, entityId;
        if (opts.isRegion) {
            kind = 'region';
            entityId = opts.regionId || _regionIdFor(a);
        } else {
            kind = 'spot';
            entityId = _slugifySpot(opts.spotName || (a && a.spot) || '');
        }
        var analysisId = kind + '_' + entityId + '_' + dateStr;
        var ratingOpts = '<option value="">— unverändert —</option>' +
            EXPERIENCE_LABELS.map(function (p) {
                return '<option value="' + p[0] + '">' + esc(p[1]) + '</option>';
            }).join('');
        var safetyOpts = '<option value="">— unverändert —</option>' +
            SAFETY_OPTIONS.map(function (p) {
                return '<option value="' + p[0] + '">' + esc(p[1]) + '</option>';
            }).join('');
        return '' +
            '<div class="mga-admin-feedback" data-analysis-id="' + esc(analysisId) + '" data-entity-kind="' + esc(kind) + '" data-entity-id="' + esc(entityId) + '">' +
            '  <div class="mga-admin-feedback__title">Few-Shot-Feedback (Admin) · ' + esc(kind === 'spot' ? 'Spot' : 'Region') + '</div>' +
            '  <div class="mga-admin-feedback__actions">' +
            '    <button type="button" data-fb-action="good">Als guten Fall speichern</button>' +
            '    <button type="button" data-fb-action="toggle">Bewertung korrigieren ▾</button>' +
            '  </div>' +
            '  <div class="mga-admin-feedback__panel" data-fb-panel>' +
            '    <label>Korrektur-Typ' +
            '      <select data-fb-label>' +
            '        <option value="zu_optimistisch">Zu optimistisch</option>' +
            '        <option value="zu_pessimistisch">Zu pessimistisch</option>' +
            '      </select>' +
            '    </label>' +
            '    <label>experience_rating' +
            '      <select data-fb-rating>' + ratingOpts + '</select>' +
            '    </label>' +
            '    <label>safety_status' +
            '      <select data-fb-safety>' + safetyOpts + '</select>' +
            '    </label>' +
            '    <label>Begründung (optional, max 500)' +
            '      <textarea data-fb-text rows="3" maxlength="500"></textarea>' +
            '    </label>' +
            '    <button type="button" data-fb-action="send">Senden</button>' +
            '  </div>' +
            '  <div class="mga-admin-feedback__toast" data-fb-toast></div>' +
            '</div>';
    }

    function wireAdminFeedback(root) {
        var wrap = root.querySelector('.mga-admin-feedback');
        if (!wrap) return;
        var analysisId = wrap.getAttribute('data-analysis-id');
        var panel = wrap.querySelector('[data-fb-panel]');
        var toast = wrap.querySelector('[data-fb-toast]');

        function showToast(msg, kind) {
            toast.textContent = msg;
            toast.className = 'mga-admin-feedback__toast is-' + (kind || 'ok');
            setTimeout(function () { toast.textContent = ''; toast.className = 'mga-admin-feedback__toast'; }, 3000);
        }

        function send(payload) {
            return fetch('/api/admin/labeled-examples', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            }).then(function (r) { return r.json().then(function (d) { return { status: r.status, data: d }; }); });
        }

        wrap.querySelectorAll('[data-fb-action]').forEach(function (btn) {
            btn.addEventListener('click', function (e) {
                e.stopPropagation();
                var action = btn.getAttribute('data-fb-action');
                if (action === 'toggle') {
                    panel.classList.toggle('is-open');
                    return;
                }
                if (action === 'good') {
                    send({ analysis_id: analysisId, label: 'richtig' }).then(function (res) {
                        if (res.data && res.data.ok) showToast('✓ Gespeichert');
                        else showToast('✗ ' + ((res.data && res.data.error) || 'Fehler'), 'err');
                    }).catch(function () { showToast('✗ Netzwerkfehler', 'err'); });
                    return;
                }
                if (action === 'send') {
                    var labelEl = wrap.querySelector('[data-fb-label]');
                    var ratingEl = wrap.querySelector('[data-fb-rating]');
                    var safetyEl = wrap.querySelector('[data-fb-safety]');
                    var textEl = wrap.querySelector('[data-fb-text]');
                    var rating = ratingEl.value ? parseInt(ratingEl.value, 10) : null;
                    var safety = safetyEl.value || null;
                    if (rating === null && safety === null) {
                        showToast('Bitte experience_rating oder safety_status setzen', 'err');
                        return;
                    }
                    var payload = {
                        analysis_id: analysisId,
                        label: labelEl.value,
                        correction_text: textEl.value || null
                    };
                    if (rating !== null) payload.corrected_experience_rating = rating;
                    if (safety !== null) payload.corrected_safety_status = safety;
                    send(payload).then(function (res) {
                        if (res.data && res.data.ok) {
                            showToast('✓ Gespeichert');
                            panel.classList.remove('is-open');
                        } else {
                            showToast('✗ ' + ((res.data && res.data.error) || 'Fehler'), 'err');
                        }
                    }).catch(function () { showToast('✗ Netzwerkfehler', 'err'); });
                }
            });
        });
    }

    // ===== MAIN RENDER =====
    function render(container, a, opts) {
        if (!container) return;
        opts = opts || {};
        var dateStr = opts.dateStr || (a && a.date) || '';
        // Regionen haben kein Startfenster (kein konkreter Startplatz).
        // Erkennung: explizite Option ODER Feld region_name im Cache-Eintrag.
        var isRegion = opts.isRegion === true || (a && typeof a.region_name === 'string' && a.region_name.length > 0);

        container.innerHTML = '';
        var wrapper = document.createElement('div');
        wrapper.className = 'mg-analysis-view';

        // State A: Empty (keine Analyse, oder no_data ohne jede Aussage)
        var safetyStatus = a && a.safety_status;
        var isEmpty = !a || !safetyStatus || safetyStatus === 'no_data';
        if (isEmpty) {
            wrapper.innerHTML = renderHero(a || {}, true) + renderFooter(dateStr);
            container.appendChild(wrapper);
            return;
        }

        // Few-Shot-Feedback: Region braucht regionId, Spot braucht spotName.
        // Wenn keiner geliefert ist, kann kein gueltiger analysis_id-Slug
        // gebildet werden -> Block bleibt versteckt.
        var fbOpts = { isRegion: isRegion, regionId: opts.regionId, spotName: opts.spotName };
        var hasEntity = isRegion ? !!opts.regionId : !!opts.spotName;
        var showAdminFb = !!(window.gleitcastIsAdmin && dateStr && hasEntity);

        // State B: Not-safe (inklusive noAnalysis-Pfad)
        var notSafe = (safetyStatus === 'not_safe')
                   || (a.noAnalysis === true)
                   || (a.no_analysis === true)
                   || (safetyStatus === 'error');
        if (notSafe) {
            var html = renderHero(a, false);
            if (!isRegion) html += renderStartWindowV4(getV4StartWindow(a));
            html += renderTagGroupsV4(getV4Tags(a));
            html += renderFooter(dateStr);
            if (showAdminFb) html += renderAdminFeedback(a, dateStr, fbOpts);
            wrapper.innerHTML = html;
            container.appendChild(wrapper);
            wireToggles(wrapper);
            if (showAdminFb) wireAdminFeedback(wrapper);
            return;
        }

        // State C/D: conditional / safe
        var html2 = renderHero(a, false);
        if (!isRegion) html2 += renderStartWindowV4(getV4StartWindow(a));
        html2 += renderTagGroupsV4(getV4Tags(a));
        html2 += renderMetrics(a);
        html2 += renderInsights(a);
        html2 += renderFooter(dateStr);
        if (showAdminFb) html2 += renderAdminFeedback(a, dateStr, fbOpts);
        wrapper.innerHTML = html2;
        container.appendChild(wrapper);
        wireToggles(wrapper);
        if (showAdminFb) wireAdminFeedback(wrapper);
    }

    return {
        render: render,
        getRating: getRating,
        getSafetyBand: getSafetyBand,
        parseMaybeList: parseMaybeList,
        buildGlyph: buildGlyph
    };
})();
