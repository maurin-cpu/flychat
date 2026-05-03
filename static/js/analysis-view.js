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

    // ===== REASON-MAP =====
    // Server liefert kanonische Reason-Keys (nur fuer Spots heute). Wir bilden
    // zusaetzlich generische Defaults ab, damit Region (ohne noAnalysis-Feld)
    // ueber den summary-Fallback trotzdem lesbaren Text bekommt.
    var REASON_MAP = {
        wind_direction_mismatch:
            'Windrichtung passt ganztaegig nicht zum Startplatz — kein fliegbares Fenster.',
        all_day_rain:
            'Nahezu ganztaegiger Niederschlag — kein nutzbares Flugfenster.',
        all_day_thunderstorm:
            'Praktisch ganztaegig Gewitter — kein fliegbares Fenster.',
        out_of_season:
            'Spot ist ausserhalb der Saison.'
    };

    // Rationale-Fallback-Kette — beide Panels gleich.
    function buildRationale(a) {
        var safety = a.safety || {};
        var candidates = [
            a.summary,
            safety.summary,
            a.safety_feedback,
            parseMaybeList(a.no_go_reasons)[0],
            REASON_MAP[a.noAnalysisReason || a.no_analysis_reason || ''],
            a.error
        ];
        for (var i = 0; i < candidates.length; i++) {
            if (candidates[i]) return candidates[i];
        }
        // State-Default
        var band = getSafetyBand(a);
        if (band === 'red') return 'Bedingungen sind eindeutig nicht fliegbar.';
        if (band === 'amber') return 'Bedingungen mit Einschraenkungen.';
        if (band === 'green') return 'Bedingungen sind fliegbar.';
        return '';
    }

    function shortenRationale(text) {
        if (!text) return '';
        var firstDot = text.indexOf('.');
        return firstDot > 30 ? text.substring(0, firstDot + 1) : text.substring(0, 140);
    }

    // ===== ALERT-LISTE bei not_safe (PFLICHT) =====
    // Layer 3 darf bei rotem Hero NIE leer sein. Reihenfolge:
    //   1) explizite no_go_reasons
    //   2) gemappter noAnalysisReason
    //   3) summary / safety_feedback als Klartext
    //   4) error
    //   5) generischer Fallback
    function buildNoGoAlerts(a) {
        var alerts = parseMaybeList(a.no_go_reasons);
        if (alerts.length > 0) return alerts;

        var key = a.noAnalysisReason || a.no_analysis_reason || '';
        if (REASON_MAP[key]) return [REASON_MAP[key]];

        var safety = a.safety || {};
        var txt = a.summary || safety.summary || a.safety_feedback || a.error;
        if (txt) return [txt];

        return ['Grund nicht ermittelbar — Analyse erneut starten.'];
    }

    // ===== HERO =====
    function renderHero(a, isEmpty) {
        if (isEmpty) {
            return '<div class="mga-hero no_data">'
                 + '<div class="mga-hero-glyph">' + buildGlyph('no_data', 0, 96) + '</div>'
                 + '<div class="mga-hero-text">'
                 + '<div class="mga-hero-verdict no_data">Datenanalyse ausstehend</div>'
                 + '<div class="mga-hero-rationale">'
                 + 'Fuer diesen Tag liegt noch keine Bewertung vor. '
                 + 'Sie wird automatisch erstellt, sobald die naechste Auswertung laeuft.'
                 + '</div></div></div>';
        }

        var band = getSafetyBand(a);
        var rating = getRating(a);
        var verdictTxt = (band === 'green') ? 'Sicher' :
                         (band === 'amber') ? 'Vorsicht' :
                         (band === 'red')   ? 'Nicht fliegbar' : 'Keine Daten';
        var rationale = shortenRationale(buildRationale(a));

        var html = '<div class="mga-hero ' + band + '">'
                 + '<div class="mga-hero-glyph">' + buildGlyph(band, rating, 96) + '</div>'
                 + '<div class="mga-hero-text">'
                 + '<div class="mga-hero-verdict ' + band + '">' + esc(verdictTxt) + '</div>';
        if (rationale) {
            html += '<div class="mga-hero-rationale">' + esc(rationale) + '</div>';
        }
        // Pills: Safety-Band + Safety-Score immer; Experience/Comfort nur wenn nicht red.
        var safScore = (typeof a.safety_score === 'number') ? a.safety_score : null;
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
        }
        html += '</div></div></div>';
        return html;
    }

    // ===== BEST WINDOW =====
    function renderWindow(a) {
        var w = a.safe_window || a.best_window || '';
        var clean = String(w || '').trim().toLowerCase();
        var empty = !w || clean === 'keins' || clean === 'kein'
                 || clean === '-' || clean === '–' || clean === '—' || clean === '?';
        if (empty) return '';
        return '<div class="mga-window">'
             + '<div>'
             + '<div class="mga-window-label">Bestes Fenster</div>'
             + '<div class="mga-window-time">' + esc(w) + '</div>'
             + '</div></div>';
    }

    // ===== ALERTS =====
    function renderAlerts(a, mode) {
        // mode: 'notsafe' | 'fliegbar'
        var html = '';
        var noGoReasons, cautionNotes, flyabilityLimits, highlightNotes;
        var foehnRisk = (a.foehn_risk || '').toString().toLowerCase();

        if (mode === 'notsafe') {
            noGoReasons = buildNoGoAlerts(a);  // immer >= 1 Eintrag
            cautionNotes = parseMaybeList(a.caution_notes);
            flyabilityLimits = [];
            highlightNotes = [];
        } else {
            noGoReasons = parseMaybeList(a.no_go_reasons);
            cautionNotes = parseMaybeList(a.caution_notes);
            flyabilityLimits = parseMaybeList(a.flyability_limits);
            highlightNotes = parseMaybeList(a.highlights);
        }

        var hasFoehnInNotes = cautionNotes.concat(noGoReasons).some(function (t) {
            var s = (t || '').toString().toLowerCase();
            return s.indexOf('föhn') >= 0 || s.indexOf('foehn') >= 0;
        });
        var showFoehn = (foehnRisk && foehnRisk !== 'none') && !hasFoehnInNotes;

        var any = noGoReasons.length || cautionNotes.length
               || flyabilityLimits.length || highlightNotes.length || showFoehn;
        if (!any) return '';

        html += '<div class="mga-alerts">';
        noGoReasons.forEach(function (r) {
            html += '<div class="mga-alert nogo">'
                  + '<div class="mga-alert-icon">✕</div>'
                  + '<div>' + esc(r) + '</div></div>';
        });
        cautionNotes.forEach(function (n) {
            html += '<div class="mga-alert caution">'
                  + '<div class="mga-alert-icon">!</div>'
                  + '<div>' + esc(n) + '</div></div>';
        });
        if (showFoehn) {
            var label = foehnRisk === 'high' ? 'Föhn-Gefahr' : 'Föhn-Vorsicht';
            var cls = foehnRisk === 'high' ? 'nogo' : 'caution';
            var icon = foehnRisk === 'high' ? '✕' : '!';
            html += '<div class="mga-alert ' + cls + '">'
                  + '<div class="mga-alert-icon">' + icon + '</div>'
                  + '<div>' + esc(label) + ' (foehn_risk: ' + esc(foehnRisk) + ')</div></div>';
        }
        flyabilityLimits.forEach(function (l) {
            html += '<div class="mga-alert flyability">'
                  + '<div class="mga-alert-icon">↓</div>'
                  + '<div>' + esc(l) + '</div></div>';
        });
        highlightNotes.forEach(function (h) {
            html += '<div class="mga-alert positive">'
                  + '<div class="mga-alert-icon">✓</div>'
                  + '<div>' + esc(h) + '</div></div>';
        });
        html += '</div>';
        return html;
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
            html += '<div class="mga-insight flyability' + (safetyFb ? '' : ' open') + '">'
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
            var alreadyOpen = (!safetyFb && !flyFb);
            var sfTier = a.streckenflug_tier || 'kein_xc';
            html += '<div class="mga-insight streckenflug ' + esc(sfTier) + (alreadyOpen ? ' open' : '') + '">'
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
            html += renderAlerts(a, 'notsafe');
            html += renderFooter(dateStr);
            wrapper.innerHTML = html;
            container.appendChild(wrapper);
            wireToggles(wrapper);
            return;
        }

        // State C/D: conditional / safe
        var html2 = renderHero(a, false);
        html2 += renderWindow(a);
        html2 += renderAlerts(a, 'fliegbar');
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
