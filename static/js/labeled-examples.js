/* Admin · Few-Shot-Pool Verwaltung. Filter + Detail/Patch/Delete Aktionen. */
(function () {
    'use strict';

    var tbl = document.getElementById('lxTable');
    var filterKind = document.getElementById('lxFilterKind');
    var filterTier = document.getElementById('lxFilterTier');
    var filterLabel = document.getElementById('lxFilterLabel');
    var filterRegion = document.getElementById('lxFilterRegion');

    function applyFilters() {
        if (!tbl) return;
        var k = ((filterKind && filterKind.value) || '').toLowerCase();
        var t = (filterTier.value || '').toLowerCase();
        var l = (filterLabel.value || '').toLowerCase();
        var r = (filterRegion.value || '').toLowerCase().trim();
        tbl.querySelectorAll('tbody tr').forEach(function (row) {
            var rk = (row.dataset.kind || '').toLowerCase();
            var rt = (row.dataset.tier || '').toLowerCase();
            var rl = (row.dataset.label || '').toLowerCase();
            var rr = (row.dataset.region || '').toLowerCase();
            var show = (!k || rk === k)
                    && (!t || rt === t)
                    && (!l || rl === l)
                    && (!r || rr.indexOf(r) !== -1);
            row.style.display = show ? '' : 'none';
        });
    }
    [filterKind, filterTier, filterLabel].forEach(function (s) { if (s) s.addEventListener('change', applyFilters); });
    if (filterRegion) filterRegion.addEventListener('input', applyFilters);

    // ===== Sortierung =====
    var tierRank = { mittelland: 1, jura: 2, voralpen: 3, alpen: 4, hochalpin: 5 };
    var safetyRank = { safe: 1, conditional: 2, not_safe: 3 };
    var labelRank = { richtig: 1, zu_optimistisch: 2, zu_pessimistisch: 3 };
    var kindRank = { region: 1, spot: 2 };

    function parseNum(s) {
        var n = parseFloat(String(s).replace(',', '.'));
        return isNaN(n) ? null : n;
    }
    function cellText(row, idx) {
        var td = row.cells[idx];
        return td ? td.textContent.trim() : '';
    }
    function rankOf(map, key) {
        var v = map[(key || '').toLowerCase()];
        return v == null ? 99 : v;
    }
    function getSortValue(row, key) {
        switch (key) {
            case 'date':  return cellText(row, 0);
            case 'kind':  return rankOf(kindRank, row.dataset.kind);
            case 'name':  return cellText(row, 2).toLowerCase();
            case 'tier':  return rankOf(tierRank, row.dataset.tier);
            case 'label': return rankOf(labelRank, row.dataset.label);
            case 'orig':
            case 'corr': {
                var parts = cellText(row, key === 'orig' ? 5 : 6).split('/');
                var exp = parseNum(parts[0]);
                var safetyKey = (parts[1] || '').trim().toLowerCase();
                var safety = rankOf(safetyRank, safetyKey);
                return [exp == null ? -1 : exp, safety];
            }
            case 'dec':   return row.querySelectorAll('.lx-decisions code').length;
        }
        return '';
    }
    function compareValues(a, b) {
        if (Array.isArray(a) && Array.isArray(b)) {
            for (var i = 0; i < a.length; i++) {
                var c = compareValues(a[i], b[i]);
                if (c !== 0) return c;
            }
            return 0;
        }
        if (typeof a === 'number' && typeof b === 'number') return a - b;
        return String(a).localeCompare(String(b), 'de');
    }
    var sortState = { key: null, dir: 1 };
    function updateSortIndicators() {
        if (!tbl) return;
        tbl.querySelectorAll('thead th[data-sort-key]').forEach(function (th) {
            var arrow = th.querySelector('.lx-sort-arrow');
            if (!arrow) return;
            if (th.dataset.sortKey === sortState.key) {
                arrow.textContent = sortState.dir > 0 ? '▲' : '▼';
                th.classList.add('is-sorted');
            } else {
                arrow.textContent = '';
                th.classList.remove('is-sorted');
            }
        });
    }
    function sortBy(key) {
        if (!tbl) return;
        if (sortState.key === key) sortState.dir = -sortState.dir;
        else { sortState.key = key; sortState.dir = 1; }
        var tbody = tbl.querySelector('tbody');
        var rows = Array.prototype.slice.call(tbody.querySelectorAll('tr'));
        rows.sort(function (a, b) {
            return compareValues(getSortValue(a, key), getSortValue(b, key)) * sortState.dir;
        });
        rows.forEach(function (r) { tbody.appendChild(r); });
        updateSortIndicators();
    }
    if (tbl) {
        tbl.querySelectorAll('thead th[data-sort-key]').forEach(function (th) {
            var arrow = document.createElement('span');
            arrow.className = 'lx-sort-arrow';
            th.appendChild(arrow);
            th.addEventListener('click', function () { sortBy(th.dataset.sortKey); });
        });
    }

    // ===== Modal-Helpers =====
    function openModal(id) {
        document.getElementById(id).classList.add('is-open');
    }
    function closeModals() {
        document.querySelectorAll('.lx-modal-backdrop').forEach(function (m) { m.classList.remove('is-open'); });
    }
    document.querySelectorAll('[data-close-modal]').forEach(function (el) {
        el.addEventListener('click', closeModals);
    });
    document.querySelectorAll('.lx-modal-backdrop').forEach(function (b) {
        b.addEventListener('click', function (e) { if (e.target === b) closeModals(); });
    });
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape') closeModals();
    });

    // ===== Detail =====
    function escHTML(s) {
        return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
            return ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]);
        });
    }

    function renderAggregates(agg) {
        if (!agg) return '<p>(keine Aggregates)</p>';
        var rows = [];
        var order = ['wind_10m_max', 'wind_850hpa_mean', 'gust_excess_max',
                     'foehn_risk_peak', 'foehn_direction_dominant', 'climb_peak',
                     'productive_thermal_h', 'blh_max', 'low_cloud_max',
                     'mid_cloud_max', 'rough_pct'];
        order.forEach(function (k) {
            var v = agg[k];
            rows.push('<tr><th>' + escHTML(k) + '</th><td>' + (v == null ? '–' : escHTML(v)) + '</td></tr>');
        });
        return '<table class="lx-agg-table">' + rows.join('') + '</table>';
    }

    // Cache-Eintraege sind nested (safety.*, ggf. flyability.*) — AnalysisView
    // liest aber viele Felder vom Top-Level, insbesondere den Empty-Check
    // auf safety_status. Funktioniert sowohl fuer Region- als auch fuer
    // Spot-Eintraege (bei Spots ist `flyability` leer, Fallback-Picks ziehen
    // die Felder aus dem Top-Level).
    function flattenAnalysisEntry(entry) {
        if (!entry || typeof entry !== 'object') return entry;
        var safety = entry.safety || {};
        var fly = entry.flyability || {};
        var flat = Object.assign({}, entry);
        var picks = [
            ['safety_status', safety.safety_status],
            ['safe_window', safety.safe_window],
            ['safety_feedback', safety.summary],
            ['foehn_risk', safety.foehn_risk],
            ['wind_summary', safety.wind_summary],
            ['hazard_notes', safety.hazard_notes],
            ['no_go_reasons', safety.no_go_reasons],
            ['caution_notes', safety.caution_notes],
            ['primary_no_go', safety.primary_no_go],
            ['primary_caution', safety.primary_caution],
            ['primary_reducer', safety.primary_reducer],
            ['primary_booster', safety.primary_booster],
            ['flyability_feedback', fly.recommendation || entry.recommendation],
            ['peak_climb_rate', fly.peak_climb_rate],
            ['flight_type', fly.flight_type],
            ['flight_duration_estimate', fly.flight_duration_estimate],
            ['xc_potential', fly.xc_potential],
            ['flyability_notes', fly.flyability_notes]
        ];
        picks.forEach(function (p) {
            if (flat[p[0]] == null && p[1] != null) flat[p[0]] = p[1];
        });
        if (!Array.isArray(flat.tags) && Array.isArray(safety.tags)) flat.tags = safety.tags;
        if (!Array.isArray(flat.start_window) && Array.isArray(safety.start_window)) flat.start_window = safety.start_window;
        return flat;
    }

    function setMeteoStatus(msg, isErr) {
        var el = document.getElementById('lxDetailMeteoStatus');
        if (!el) return;
        el.textContent = msg || '';
        el.classList.toggle('lx-meteo-status--err', !!isErr);
    }

    function loadMeteogram(entityType, entityId, dateStr, analysisId) {
        var chartEl = document.getElementById('lxDetailMeteoChart');
        var tooltipEl = document.getElementById('lxMeteoTooltip');
        if (!chartEl || !entityId || !dateStr) return;
        if (typeof d3 === 'undefined' || !window.Meteogram || !window.Meteogram.renderChart) {
            setMeteoStatus('Meteogram-Modul nicht geladen', true);
            return;
        }
        var isRegion = entityType !== 'spot';

        // Bevorzugt: eingebetteter Snapshot aus dem Label selbst (auch fuer
        // alte Daten ausserhalb des Live-Forecast-Fensters).
        // Fallback bei 404 oder fehlendem analysisId: Live-API /api/weather/...
        function renderFromPayload(wxData, altData) {
            var wxDay = wxData && wxData.data ? wxData.data[dateStr] : null;
            var altDayRaw = altData && altData.data ? altData.data[dateStr] : null;
            if (!wxDay || !altDayRaw || !altDayRaw.length) {
                return false;
            }
            var altDay = {
                profiles: altDayRaw.map(function (entry) {
                    var hh = ('0' + entry.hour).slice(-2);
                    return {
                        time: dateStr + 'T' + hh + ':00:00',
                        levels: entry.profiles
                    };
                })
            };
            window.Meteogram.renderChart(chartEl, tooltipEl, wxDay, altDay, {
                elevation: altData.elevation_m || 0,
                isRegion: isRegion,
                thresholds: wxData.thresholds,
                fitToContainer: true
            });
            setMeteoStatus((wxDay.wind ? wxDay.wind.length : 0) + ' Stunden geladen · Wetter-Stand '
                + (wxData.last_updated || '').replace('T', ' ').slice(0, 16), false);
            return true;
        }

        function loadFromLive() {
            var wxUrl = isRegion
                ? '/api/region-weather/' + encodeURIComponent(entityId)
                : '/api/weather/' + encodeURIComponent(entityId);
            var altUrl = isRegion
                ? '/api/region-altitude-wind/' + encodeURIComponent(entityId)
                : '/api/altitude-wind/' + encodeURIComponent(entityId);
            Promise.all([
                fetch(wxUrl).then(function (r) { return r.json(); }),
                fetch(altUrl).then(function (r) { return r.json(); })
            ]).then(function (results) {
                var wxData = results[0];
                var altData = results[1];
                if (wxData.error || altData.error) {
                    setMeteoStatus((isRegion ? 'Region' : 'Spot') + ' nicht gefunden oder keine Wetterdaten', true);
                    return;
                }
                if (!renderFromPayload(wxData, altData)) {
                    var avail = (wxData.dates || []).join(', ') || '–';
                    setMeteoStatus('Datum ' + dateStr + ' nicht (mehr) im Forecast-Fenster. Verfügbar: ' + avail, true);
                }
            }).catch(function (err) {
                setMeteoStatus('Fehler: ' + (err && err.message ? err.message : err), true);
            });
        }

        if (!analysisId) {
            loadFromLive();
            return;
        }

        // Versuche zuerst den eingebetteten Snapshot — funktioniert auch fuer
        // alte Daten, die nicht mehr im Live-Forecast sind.
        fetch('/api/admin/labeled-examples/' + encodeURIComponent(analysisId) + '/meteogram')
            .then(function (r) {
                if (r.status === 404) return null;
                return r.json();
            })
            .then(function (resp) {
                if (resp && resp.ok && resp.wx && resp.alt && renderFromPayload(resp.wx, resp.alt)) {
                    return;
                }
                loadFromLive();
            })
            .catch(function () {
                loadFromLive();
            });
    }

    function loadDetail(aid) {
        var body = document.getElementById('lxDetailBody');
        body.textContent = 'Lade …';
        openModal('lxDetailBackdrop');
        fetch('/api/admin/labeled-examples/' + encodeURIComponent(aid))
            .then(function (r) { return r.json(); })
            .then(function (resp) {
                if (!resp.ok) {
                    body.textContent = 'Fehler: ' + (resp.error || 'unbekannt');
                    return;
                }
                var e = resp.entry;
                var fb = e.user_feedback || {};
                var llm = e.llm_output_full || {};
                var entityType = e.entity_type || 'region';
                var entityLabel = entityType === 'spot' ? 'Spot' : 'Region';
                var displayName = (entityType === 'spot'
                    ? (llm.spot || e.spot_or_region_id)
                    : (llm.region_name || e.spot_or_region_id));
                var html = '';
                html += '<p><strong>' + escHTML(entityLabel) + ': ' + escHTML(displayName) + '</strong> · '
                     + escHTML(e.target_date) + ' · ' + escHTML(e.terrain_tier) + '</p>';
                html += '<h4 style="margin-top:14px;">Meteogramm</h4>';
                html += '<div class="lx-meteo-wrap">'
                      + '  <div class="lx-meteo-chart" id="lxDetailMeteoChart"></div>'
                      + '  <div class="lx-meteo-status" id="lxDetailMeteoStatus">Lade Wetterdaten …</div>'
                      + '</div>';
                html += '<h4 style="margin-top:14px;">Aggregates</h4>';
                html += renderAggregates((e.weather_input || {}).aggregates);
                if (fb.correction_text) {
                    html += '<h4 style="margin-top:14px;">Korrekturtext</h4>';
                    html += '<div class="lx-quote">' + escHTML(fb.correction_text) + '</div>';
                }
                if (e.decisions_applied && e.decisions_applied.length) {
                    html += '<h4 style="margin-top:14px;">Decisions</h4>';
                    html += '<p class="lx-decisions">'
                          + e.decisions_applied.map(function (d) { return '<code>' + escHTML(d) + '</code>'; }).join(' ')
                          + '</p>';
                }
                html += '<h4 style="margin-top:14px;">Original-Analyse</h4>';
                html += '<div id="lxDetailAnalysis"></div>';
                body.innerHTML = html;
                var av = document.getElementById('lxDetailAnalysis');
                if (window.AnalysisView && window.AnalysisView.render && av) {
                    var renderOpts = { dateStr: e.target_date };
                    if (entityType === 'spot') {
                        renderOpts.isRegion = false;
                        renderOpts.spotName = e.spot_or_region_id;
                    } else {
                        renderOpts.isRegion = true;
                        renderOpts.regionId = e.spot_or_region_id;
                    }
                    window.AnalysisView.render(av, flattenAnalysisEntry(llm), renderOpts);
                }
                loadMeteogram(entityType, e.spot_or_region_id, e.target_date, e.analysis_id);
            })
            .catch(function (err) { body.textContent = 'Netzwerkfehler: ' + err; });
    }

    // ===== Patch =====
    function openPatch(aid) {
        document.getElementById('lxPatchId').value = aid;
        fetch('/api/admin/labeled-examples/' + encodeURIComponent(aid))
            .then(function (r) { return r.json(); })
            .then(function (resp) {
                if (!resp.ok) return;
                var fb = (resp.entry || {}).user_feedback || {};
                document.getElementById('lxPatchLabel').value = fb.label || 'richtig';
                document.getElementById('lxPatchRating').value = fb.corrected_experience_rating == null ? '' : String(fb.corrected_experience_rating);
                document.getElementById('lxPatchSafety').value = fb.corrected_safety_status || '';
                document.getElementById('lxPatchText').value = fb.correction_text || '';
                openModal('lxPatchBackdrop');
            });
    }

    var patchForm = document.getElementById('lxPatchForm');
    if (patchForm) {
        patchForm.addEventListener('submit', function (e) {
            e.preventDefault();
            var aid = document.getElementById('lxPatchId').value;
            var ratingRaw = document.getElementById('lxPatchRating').value;
            var safetyRaw = document.getElementById('lxPatchSafety').value;
            var payload = {
                label: document.getElementById('lxPatchLabel').value,
                corrected_experience_rating: ratingRaw === '' ? null : parseInt(ratingRaw, 10),
                corrected_safety_status: safetyRaw === '' ? null : safetyRaw,
                correction_text: document.getElementById('lxPatchText').value || null
            };
            fetch('/api/admin/labeled-examples/' + encodeURIComponent(aid), {
                method: 'PATCH',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            }).then(function (r) { return r.json(); })
            .then(function (resp) {
                if (resp.ok) {
                    closeModals();
                    window.location.reload();
                } else {
                    alert('Fehler: ' + (resp.error || 'unbekannt'));
                }
            });
        });
    }

    // ===== Delete =====
    function deleteEntry(aid) {
        if (!confirm('Diesen Eintrag wirklich löschen?')) return;
        fetch('/api/admin/labeled-examples/' + encodeURIComponent(aid), { method: 'DELETE' })
            .then(function (r) { return r.json(); })
            .then(function (resp) {
                if (resp.ok) {
                    var row = document.querySelector('tr[data-aid="' + aid.replace(/"/g, '\\"') + '"]');
                    if (row) row.remove();
                } else {
                    alert('Fehler: ' + (resp.error || 'unbekannt'));
                }
            });
    }

    // Action-Dispatch
    if (tbl) {
        tbl.addEventListener('click', function (e) {
            var btn = e.target.closest('button[data-act]');
            if (!btn) return;
            var row = btn.closest('tr[data-aid]');
            if (!row) return;
            var aid = row.dataset.aid;
            var act = btn.dataset.act;
            if (act === 'open') loadDetail(aid);
            else if (act === 'patch') openPatch(aid);
            else if (act === 'delete') deleteEntry(aid);
        });
    }
})();
