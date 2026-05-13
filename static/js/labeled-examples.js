/* Admin · Few-Shot-Pool Verwaltung. Filter + Detail/Patch/Delete Aktionen. */
(function () {
    'use strict';

    var tbl = document.getElementById('lxTable');
    var filterTier = document.getElementById('lxFilterTier');
    var filterLabel = document.getElementById('lxFilterLabel');
    var filterRegion = document.getElementById('lxFilterRegion');

    function applyFilters() {
        if (!tbl) return;
        var t = (filterTier.value || '').toLowerCase();
        var l = (filterLabel.value || '').toLowerCase();
        var r = (filterRegion.value || '').toLowerCase().trim();
        tbl.querySelectorAll('tbody tr').forEach(function (row) {
            var rt = (row.dataset.tier || '').toLowerCase();
            var rl = (row.dataset.label || '').toLowerCase();
            var rr = (row.dataset.region || '').toLowerCase();
            var show = (!t || rt === t) && (!l || rl === l) && (!r || rr.indexOf(r) !== -1);
            row.style.display = show ? '' : 'none';
        });
    }
    [filterTier, filterLabel].forEach(function (s) { if (s) s.addEventListener('change', applyFilters); });
    if (filterRegion) filterRegion.addEventListener('input', applyFilters);

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
                var html = '';
                html += '<p><strong>' + escHTML(llm.region_name || e.spot_or_region_id) + '</strong> · '
                     + escHTML(e.target_date) + ' · ' + escHTML(e.terrain_tier) + '</p>';
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
                    window.AnalysisView.render(av, llm, {
                        dateStr: e.target_date,
                        isRegion: true,
                        regionId: e.spot_or_region_id
                    });
                }
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
