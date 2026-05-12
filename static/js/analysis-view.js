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

    function getStars(a) {
        if (!a) return 0;
        var s = a.experience_stars;
        if (typeof s === 'number') return Math.max(0, Math.min(5, Math.round(s)));
        var r = parseFloat(a.rating || 0);
        if (r >= 9.0) return 5;
        if (r >= 7.6) return 4;
        if (r >= 6.1) return 3;
        if (r >= 4.1) return 2;
        if (r >= 2.1) return 1;
        return 0;
    }

    // RATING_CONCEPT v1.4: 0-10 Rating
    function getRating(a) {
        if (!a) return 0;
        var er = a.experience_rating;
        if (typeof er === 'number') return Math.max(0, Math.min(10, Math.round(er)));
        var sc = a.experience_score;
        if (typeof sc === 'number') {
            if (sc <= 0) return 0;
            if (sc >= 100) return 10;
            return Math.max(1, Math.min(10, Math.ceil(sc / 10)));
        }
        var s = a.experience_stars;
        if (typeof s === 'number') return Math.max(0, Math.min(10, s * 2));
        var r = parseFloat(a.rating || 0);
        if (r > 0) return Math.max(1, Math.min(10, Math.round(r)));
        return 0;
    }

    function getSafetyBand(a) {
        if (!a) return 'no_data';
        var b = a.safety_band;
        if (b === 'green' || b === 'amber' || b === 'red' || b === 'no_data') return b;
        var s = a.safety_status || (a.safety && a.safety.safety_status);
        if (s === 'safe') return 'green';
        if (s === 'conditional') return 'amber';
        if (s === 'not_safe') return 'red';
        if (s === 'error') return 'red';
        return 'no_data';
    }

    // ===== GLYPH =====
    // Kreis in Safety-Farbe; weisses Kreuz bei red, weisse Rating-Ziffer 1-10 sonst.
    var PALETTE = {
        green:   { fill: '#22c55e', stroke: '#15803d' },
        amber:   { fill: '#f59e0b', stroke: '#92400e' },
        red:     { fill: '#ef4444', stroke: '#991b1b' },
        no_data: { fill: '#9ca3af', stroke: '#6b7280' }
    };

    function buildGlyph(band, rating, size) {
        var s = size || 96;
        var c = s / 2;
        var r = s * 0.32;
        var col = PALETTE[band] || PALETTE.no_data;
        var label = (band === 'red') ? 'Nicht fliegbar' :
                    (band === 'no_data') ? 'Keine Analyse' :
                    (rating >= 1 ? 'Rating ' + rating + ' von 10' : 'Bewertung');
        var html = '<svg width="' + s + '" height="' + s + '" viewBox="0 0 ' + s + ' ' + s
                 + '" role="img" aria-label="' + esc(label) + '">';
        html += '<circle cx="' + c + '" cy="' + c + '" r="' + r
              + '" fill="' + col.fill + '" stroke="' + col.stroke + '" stroke-width="3"/>';
        if (band === 'red') {
            var arm = r * 0.55;
            html += '<line x1="' + (c - arm) + '" y1="' + (c - arm)
                  + '" x2="' + (c + arm) + '" y2="' + (c + arm)
                  + '" stroke="#fff" stroke-width="6" stroke-linecap="round"/>';
            html += '<line x1="' + (c + arm) + '" y1="' + (c - arm)
                  + '" x2="' + (c - arm) + '" y2="' + (c + arm)
                  + '" stroke="#fff" stroke-width="6" stroke-linecap="round"/>';
        } else if (band === 'no_data') {
            // schlichtes Fragezeichen-Substitut: drei Punkte
            html += '<text x="' + c + '" y="' + (c + r * 0.32)
                  + '" text-anchor="middle" fill="#fff" font-family="Inter,sans-serif" font-size="'
                  + (r * 0.85).toFixed(1) + '" font-weight="700">…</text>';
        } else if (rating >= 1) {
            // v1.4: zweistellige "10" braucht kleinere Schrift, damit sie reinpasst.
            var twoDigit = rating >= 10;
            var fontSize = (r * (twoDigit ? 0.65 : 0.85)).toFixed(1);
            html += '<text x="' + c + '" y="' + (c + r * 0.34)
                  + '" text-anchor="middle" fill="#fff" font-family="Inter,sans-serif" font-size="'
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

        var html = '<div class="mga-hero ' + band + '">'
                 + '<div class="mga-hero-glyph">' + buildGlyph(band, rating, 96) + '</div>'
                 + '<div class="mga-hero-text">'
                 + '<div class="mga-hero-verdict ' + band + '">' + esc(verdictTxt) + '</div>';
        // Pills: Safety-Band + Safety-Score immer; Experience/Comfort nur wenn nicht red.
        var safScore = null;
        if (typeof a.safety_score === 'number') {
            safScore = Math.round(a.safety_score);
        } else {
            var _nested = a.safety || {};
            var _st = String((a.safety_status || _nested.safety_status || '')).toLowerCase();
            var _fo = String((a.foehn_risk   || _nested.foehn_risk   || 'none')).toLowerCase();
            var _base = (_st === 'safe') ? 85 : (_st === 'conditional') ? 50 : -1;
            if (_base >= 0) {
                var _delta = (_fo === 'medium') ? -15 : (_fo === 'high' || _fo === 'severe') ? -30 : 0;
                safScore = Math.max(0, _base + _delta);
            }
        }
        var expScore = (typeof a.experience_score === 'number') ? a.experience_score : null;
        var comfort  = (typeof a.comfort_index === 'number') ? a.comfort_index : null;
        html += '<div class="mga-hero-pills">';
        html += '<span class="mga-hero-pill ' + band + '">Safety ' + band.toUpperCase() + '</span>';
        if (safScore !== null) {
            html += '<span class="mga-hero-pill">Safety-Score ' + safScore + '/100</span>';
        }
        if (band !== 'red' && band !== 'no_data') {
            if (expScore !== null) {
                html += '<span class="mga-hero-pill">Experience ' + expScore + '/100</span>';
            }
            if (comfort !== null) {
                html += '<span class="mga-hero-pill">Comfort ' + Math.round(comfort) + '/100</span>';
            }
            // Flyability-Tier
            var fly = a.flyability || {};
            var flyTier = fly.flyability_tier || a.fly_status || '';
            // RATING_CONCEPT v1.6: flight_category als Pilot-Sprache (z.B. "Solider Thermikflug").
            // Fallback auf alte tier-Labels bei Caches ohne Kategorie.
            var catDisplay = a.flight_category_display
                          || (fly && fly.flight_category_display)
                          || '';
            var FLY_LABEL_FALLBACK = { green: 'Fliegbar', violet: 'Top', gray: 'Abgleiter', red: 'Nicht fliegbar' };
            if (flyTier && flyTier !== 'no_data') {
                var pillLabel = catDisplay || FLY_LABEL_FALLBACK[flyTier] || flyTier;
                html += '<span class="mga-hero-pill mga-hero-pill--fly mga-hero-pill--' + flyTier + '">' + esc(pillLabel) + '</span>';
            }
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
    var SF_TIER_LABELS = {
        kein_xc: 'kein XC', lokal: 'Lokal', moderat: 'Moderat', top: 'Top-XC'
    };

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
        // Streckenflug-Metric — nur wenn das Feld vom Server geliefert wird (Spot).
        if (a.streckenflug_tier) {
            var sfTier = a.streckenflug_tier;
            var sfRating = a.streckenflug_rating;
            var sfCtxOk = !!a.streckenflug_region_context_available;
            var sfLabel = SF_TIER_LABELS[sfTier] || sfTier;
            var sfHtml = '<span class="mga-sf-badge ' + esc(sfTier) + '">' + esc(sfLabel) + '</span>';
            if (typeof sfRating === 'number' && sfRating > 0) {
                sfHtml += ' <span class="mga-sf-rating">' + sfRating + '/10</span>';
            }
            if (!sfCtxOk && sfTier !== 'kein_xc') {
                sfHtml += ' <span class="mga-sf-ctx-warn" title="Region-Kontext fehlt — reine Spot-Einschaetzung">⚠</span>';
            }
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
        region_wind_aloft:      'Limit: Region-Hoehenwinde',
        weak_regional_thermals: 'Limit: Region-Thermik schwach',
        ceiling_low:            'Limit: Basis zu tief',
        spot_wind_direction:    'Limit: Spot-Windrichtung',
        abgleiter_only:         'Limit: nur Abgleiter',
        spot_not_flyable:       'Limit: Spot nicht fliegbar'
    };

    function renderInsights(a) {
        var safetyFb = a.safety_feedback || a.summary || '';
        var flyFb = a.flyability_feedback || a.recommendation || '';
        var sfFb = a.streckenflug_summary || '';
        if (!safetyFb && !flyFb && !sfFb) return '';

        var html = '<div class="mga-insights">';
        if (safetyFb) {
            html += '<div class="mga-insight safety open">'
                  + '<button class="mga-insight-toggle" type="button">Sicherheits-Einschätzung</button>'
                  + '<div class="mga-insight-body">' + esc(safetyFb) + '</div>'
                  + '</div>';
        }
        if (flyFb) {
            html += '<div class="mga-insight flyability open">'
                  + '<button class="mga-insight-toggle" type="button">Flug-Einschätzung</button>'
                  + '<div class="mga-insight-body">' + esc(flyFb) + '</div>'
                  + '</div>';
        }
        if (sfFb) {
            var limit = a.streckenflug_limiting_factor || 'none';
            var body = esc(sfFb);
            if (limit && limit !== 'none' && SF_LIMIT_LABELS[limit]) {
                body += '<div class="mga-sf-limit-note">' + esc(SF_LIMIT_LABELS[limit]) + '</div>';
            }
            var sfTier = a.streckenflug_tier || 'kein_xc';
            html += '<div class="mga-insight streckenflug ' + esc(sfTier) + ' open">'
                  + '<button class="mga-insight-toggle" type="button">Streckenflug-Einschätzung</button>'
                  + '<div class="mga-insight-body">' + body + '</div>'
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
            wrapper.innerHTML = html;
            container.appendChild(wrapper);
            wireToggles(wrapper);
            return;
        }

        // State C/D: conditional / safe
        var html2 = renderHero(a, false);
        if (!isRegion) html2 += renderStartWindowV4(getV4StartWindow(a));
        html2 += renderTagGroupsV4(getV4Tags(a));
        html2 += renderMetrics(a);
        html2 += renderInsights(a);
        html2 += renderFooter(dateStr);
        wrapper.innerHTML = html2;
        container.appendChild(wrapper);
        wireToggles(wrapper);
    }

    return {
        render: render,
        // Re-exporte fuer Aufrufer (Region-Map nutzt sie fuer Top-Spots-Liste).
        getStars: getStars,
        getRating: getRating,
        getSafetyBand: getSafetyBand,
        parseMaybeList: parseMaybeList,
        buildGlyph: buildGlyph
    };
})();
