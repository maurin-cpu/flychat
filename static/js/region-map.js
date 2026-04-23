/**
 * Gleitcast - Region Map + Analysis Overlay (Traffic Light System, Light Theme)
 */
(function () {
    'use strict';

    var map;
    var regionLayersByName = {};
    var labelMarkersGroup = null;
    var regionAnalyses = null;
    var currentDate = null;
    var meteogramCache = {};   // {region_id: {wxData, altData}}
    var regionActiveDate = {}; // {region_id: dateStr} — last selected day per region overlay

    var overlay = document.getElementById('regionOverlay');
    var overlayTitle = document.getElementById('regionOverlayTitle');
    var overlayBody = document.getElementById('regionOverlayBody');
    var overlayClose = document.getElementById('regionOverlayClose');
    var meteogramTooltip = document.getElementById('regionMeteogramTooltip');

    var safetyLabels = { safe: 'Sicher', conditional: 'Vorsicht', not_safe: 'Nicht sicher', no_data: 'Keine Daten', error: 'Fehler' };
    var qualityLabels = { gray: 'Abgleiter', green: 'Gut', violet: 'Top' };

    // Safer JSON fetch: verhindert "Unexpected token '<'..."-Fehler bei HTML-Responses
    function fetchJson(url) {
        return fetch(url, { headers: { 'Accept': 'application/json' } }).then(function (r) {
            var ctype = (r.headers.get('content-type') || '').toLowerCase();
            return r.text().then(function (txt) {
                if (!r.ok) {
                    var msg;
                    if (ctype.indexOf('application/json') >= 0) {
                        try { msg = (JSON.parse(txt) || {}).error; } catch (e) { msg = null; }
                    }
                    throw new Error(msg || ('HTTP ' + r.status));
                }
                if (ctype.indexOf('application/json') < 0) {
                    throw new Error('Server lieferte keine JSON-Daten');
                }
                try {
                    return JSON.parse(txt);
                } catch (e) {
                    throw new Error('Antwort konnte nicht gelesen werden');
                }
            });
        });
    }

    function normalizeFlyTier(ft) {
        if (!ft) return '';
        var k = String(ft).trim().toLowerCase();
        if (k === 'gray' || k === 'green' || k === 'violet') return k;
        if (k === 'yellow') return 'gray';
        if (k === 'orange') return 'green';
        return 'green';
    }

    // Derive quality from fly_status/flyability_tier, NOT from flyability_stars (which doesn't exist)
    function getQuality(dayData) {
        var tier = dayData.flyability_tier || dayData.fly_status || '';
        return normalizeFlyTier(tier) || 'green';
    }

    // Short quality label for map display
    function qualityBadge(quality) {
        if (quality === 'gray') return 'Abgleiter';
        if (quality === 'violet') return 'Top';
        return 'Gut';
    }

    // ===== STYLE SYSTEM (Traffic Light + Intensity, Light Map) =====
    function mapRegionStyle(safety, quality) {
        if (!safety || safety === 'no_data') {
            return {
                fill: '#d1d5db', fillOpacity: 0.25,
                border: '#9ca3af', borderOpacity: 0.4,
                labelColor: '#6b7280', labelShadow: '0 0 3px #fff, 0 0 6px #fff',
                showWarning: false, showStripes: false,
                safetyLabel: 'Keine Daten', qualityLabel: '', isError: false
            };
        }
        if (safety === 'error') {
            return {
                fill: '#fee2e2', fillOpacity: 0.3,
                border: '#f87171', borderOpacity: 0.5,
                labelColor: '#b91c1c', labelShadow: '0 0 3px #fff, 0 0 6px #fff',
                showWarning: false, showStripes: false,
                safetyLabel: 'Fehler', qualityLabel: '', isError: true
            };
        }

        // NOT SAFE — muted red, stripes
        if (safety === 'not_safe') {
            return {
                fill: '#fca5a5', fillOpacity: 0.35,
                border: '#dc2626', borderOpacity: 0.6,
                labelColor: '#b91c1c', labelShadow: '0 0 3px #fff, 0 0 6px #fff',
                showWarning: false, showStripes: true,
                safetyLabel: 'Nicht sicher', qualityLabel: ''
            };
        }

        // SAFE — green
        if (safety === 'safe') {
            if (quality === 'gray') return {
                fill: '#E8D5B8', fillOpacity: 0.4,
                border: '#B08D57', borderOpacity: 0.5,
                labelColor: '#6B5430', labelShadow: '0 0 3px #fff, 0 0 6px #fff',
                showWarning: false, showStripes: false,
                safetyLabel: 'Sicher', qualityLabel: 'Abgleiter'
            };
            if (quality === 'violet') return {
                // Legendary regions: violet (consistent with legendary spots on main map)
                fill: '#c4b5fd', fillOpacity: 0.5,
                border: '#7c3aed', borderOpacity: 0.8,
                labelColor: '#6d28d9', labelShadow: '0 0 3px #fff, 0 0 6px #fff',
                showWarning: false, showStripes: false,
                safetyLabel: 'Sicher', qualityLabel: 'Top'
            };
            return { // green = good
                fill: '#86efac', fillOpacity: 0.4,
                border: '#16a34a', borderOpacity: 0.6,
                labelColor: '#15803d', labelShadow: '0 0 3px #fff, 0 0 6px #fff',
                showWarning: false, showStripes: false,
                safetyLabel: 'Sicher', qualityLabel: 'Gut'
            };
        }

        // CONDITIONAL — amber
        if (quality === 'gray') return {
            fill: '#fef3c7', fillOpacity: 0.4,
            border: '#d97706', borderOpacity: 0.5,
            labelColor: '#92400e', labelShadow: '0 0 3px #fff, 0 0 6px #fff',
            showWarning: true, showStripes: false,
            safetyLabel: 'Vorsicht', qualityLabel: 'Abgleiter'
        };
        if (quality === 'violet') return {
            fill: '#fde68a', fillOpacity: 0.45,
            border: '#b45309', borderOpacity: 0.7,
            labelColor: '#78350f', labelShadow: '0 0 3px #fff, 0 0 6px #fff',
            showWarning: true, showStripes: false,
            safetyLabel: 'Vorsicht', qualityLabel: 'Gut*'
        };
        return {
            fill: '#fef08a', fillOpacity: 0.4,
            border: '#ca8a04', borderOpacity: 0.6,
            labelColor: '#854d0e', labelShadow: '0 0 3px #fff, 0 0 6px #fff',
            showWarning: true, showStripes: false,
            safetyLabel: 'Vorsicht', qualityLabel: 'Gut'
        };
    }

    // ===== MAP INIT =====
    function initMap() {
        map = L.map('regionMap', {
            center: [46.8, 8.3],
            zoom: 7,
            zoomControl: true,
        });

        // Light map tiles — readable in sunshine
        L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>',
            subdomains: 'abcd',
            maxZoom: 18,
        }).addTo(map);

        labelMarkersGroup = L.layerGroup().addTo(map);

        // Re-render Labels bei Zoom-Wechsel (Labels werden je nach Zoom als Pill, Dot oder gar nicht gezeichnet)
        map.on('zoomend', function () {
            if (currentDate && regionAnalyses) colorRegions(currentDate);
        });

        loadRegions();
    }

    // Dedizierte Pill-Palette: maximiert Kontrast zwischen den 6 (safety × quality) Kombinationen
    // Polygon-Farben (style.border) bleiben dabei unverändert; nur die Label-Pill nutzt diese Tabelle,
    // damit "Bronze safe-Abgleiter" nicht mit den Conditional-Gelbtönen verwechselt wird.
    function getPillBg(safety, quality) {
        if (safety === 'safe') {
            if (quality === 'gray')   return '#78716c'; // stone — Abgleiter/so-so
            if (quality === 'violet') return '#7c3aed'; // violet — Top
            return '#16a34a';                            // green — Gut
        }
        if (safety === 'conditional') {
            if (quality === 'violet') return '#b45309'; // amber-900 — caution Top
            return '#d97706';                            // amber — caution (Gut & Abgleiter)
        }
        if (safety === 'not_safe') return '#b91c1c';
        return '#6b7280'; // no_data fallback
    }

    // Label-Variante je nach Zoom: >=9 volle Pill, 7-8 Farbpunkt, <7 nichts
    function buildRegionLabel(style, badge, safety, quality, zoom) {
        if (zoom < 7) return null;

        var pillBg = getPillBg(safety, quality);

        // Dot-Modus (Zoom 7-8): nur farbiger Punkt, keine Schrift
        if (zoom < 9) {
            var dotHtml = '<div style="width:10px;height:10px;border-radius:50%;'
                + 'background:' + pillBg + ';'
                + 'box-shadow:0 0 0 2px rgba(255,255,255,0.85),0 1px 3px rgba(0,0,0,0.2);'
                + '"></div>';
            return { html: dotHtml, size: [12, 12], anchor: [6, 6] };
        }

        // Pill-Modus (Zoom >=9): integrierte Pill, Breite = Textbreite
        var bg = pillBg, txtColor = '#fff', text;
        if (safety === 'not_safe') {
            text = '\u2715 NO-GO';
        } else if (style.isError) {
            bg = '#991b1b';
            text = '\u26A0 Fehler';
        } else if (style.showWarning) {
            // Conditional: Warn-Icon hat Priorität
            text = '\u26A0 ' + badge;
        } else {
            // Safe: Tier-Icon zeigt Qualitaet (Abgleiter / Gut / Top)
            var tierIcon = '';
            if (quality === 'gray')        tierIcon = '\u25CB ';  // \u25CB = Abgleiter
            else if (quality === 'violet') tierIcon = '\u2605 ';  // \u2605 = Top
            else                           tierIcon = '\u2713 ';  // \u2713 = Gut
            text = tierIcon + badge;
        }

        // transform:translate(-50%,-50%) zentriert die Pill auf ihre eigene Breite,
        // size:[0,0] verhindert dass Leaflet das Wrapper-Div auf 120px streckt
        var pillHtml = '<div style="'
            + 'display:inline-block;'
            + 'transform:translate(-50%,-50%);'
            + 'font-size:11px;font-weight:700;color:' + txtColor + ';'
            + 'background:' + bg + ';'
            + 'padding:3px 10px;border-radius:999px;'
            + 'white-space:nowrap;letter-spacing:0.01em;'
            + 'box-shadow:0 1px 3px rgba(0,0,0,0.18),0 0 0 1.5px rgba(255,255,255,0.7);'
            + '">' + text + '</div>';
        return { html: pillHtml, size: [0, 0], anchor: [0, 0] };
    }

    // ===== LOAD REGIONS =====
    function loadRegions() {
        fetch('/api/regionen')
            .then(function (resp) { return resp.json(); })
            .then(function (geojson) {
                var regionsLayer = L.geoJSON(geojson, {
                    style: function () {
                        return {
                            color: '#9ca3af',
                            weight: 1,
                            opacity: 0.3,
                            fill: false,
                            fillOpacity: 0,
                            dashArray: '4, 4'
                        };
                    },
                    onEachFeature: function (feature, layer) {
                        var p = feature.properties;
                        var regionId = p.id || p.region;
                        regionLayersByName[regionId] = layer;
                        layer.regionName = p.region;
                        layer.regionFeature = feature;
                        layer.bindTooltip(p.region, {
                            className: 'region-tooltip',
                            direction: 'center',
                            permanent: false,
                            sticky: true,
                        });
                        layer.on('click', function () {
                            if (!currentDate) return;
                            var ra = regionAnalyses ? regionAnalyses[regionId] : null;
                            var dayData = ra ? ra[currentDate] : null;
                            openRegionOverlay(regionId, dayData || { region_name: p.region, safety_status: 'no_data' });
                        });
                    }
                }).addTo(map);

                // Nach dem Laden an alle Regionen anpassen (Gesamtansicht Schweiz)
                try {
                    var bounds = regionsLayer.getBounds();
                    if (bounds && bounds.isValid()) {
                        map.fitBounds(bounds, { padding: [20, 20] });
                    }
                } catch (e) {
                    console.warn('fitBounds fehlgeschlagen:', e);
                }

                if (regionAnalyses && currentDate) colorRegions(currentDate);
            })
            .catch(function (err) {
                console.error('Regionen laden fehlgeschlagen:', err);
            });
    }

    // ===== COLOR REGIONS =====
    function colorRegions(dateStr) {
        labelMarkersGroup.clearLayers();

        Object.keys(regionLayersByName).forEach(function (rid) {
            var layer = regionLayersByName[rid];
            layer.setStyle({ fill: false, fillOpacity: 0, color: '#9ca3af', weight: 1, opacity: 0.3, dashArray: '4, 4' });
            layer.setTooltipContent(layer.regionName);
        });

        if (!regionAnalyses || !dateStr) return;

        Object.keys(regionLayersByName).forEach(function (rid) {
            var layer = regionLayersByName[rid];
            var ra = regionAnalyses[rid];
            if (!ra) return;
            var dayData = ra[dateStr];
            if (!dayData) return;

            var safety = dayData.safety_status;
            var quality = getQuality(dayData);
            var badge = qualityBadge(quality);
            var style = mapRegionStyle(safety, quality);

            layer.setStyle({
                fill: true,
                fillColor: style.fill,
                fillOpacity: style.fillOpacity,
                color: style.border,
                weight: 1.5,
                opacity: style.borderOpacity,
                dashArray: ''
            });

            // Center label — zoom-responsive (Pill / Dot / nichts)
            var bounds = layer.getBounds();
            var center = bounds.getCenter();
            var label = buildRegionLabel(style, badge, safety, quality, map.getZoom());

            if (label) {
                labelMarkersGroup.addLayer(L.marker(center, {
                    icon: L.divIcon({
                        className: 'region-label',
                        html: label.html,
                        iconSize: label.size,
                        iconAnchor: label.anchor
                    }),
                    interactive: false
                }));
            }

            // Tooltip
            var tipHtml = '<b>' + layer.regionName + '</b>';
            tipHtml += '<br><span style="color:' + style.labelColor + ';">' + style.safetyLabel + '</span>';
            if (style.qualityLabel) tipHtml += ' · ' + style.qualityLabel;
            layer.setTooltipContent(tipHtml);
        });
    }

    // ===== OVERLAY (Pilot Decision Flow) =====
    // Same 5-level hierarchy as meteogram aside:
    //   1. Decision Hero Banner
    //   2. Best Window Highlight
    //   3. Key Metrics Grid
    //   4. Safety Alerts (NO-GO, caution, foehn)
    //   5. AI Insights (expandable)
    function buildAnalysisHtml(a) {
        var safetyStatus = a.safety_status || 'error';
        var quality = getQuality(a);
        var phase2Ok = (safetyStatus === 'safe' || safetyStatus === 'conditional');

        var html = '<div class="mg-analysis-view">';

        // ── Level 1: Decision Hero Banner ──
        var decisionConfig = {
            safe:        { cls: 'safe',        icon: '\u2713', label: 'Fliegbar',          sub: '' },
            conditional: { cls: 'conditional',  icon: '!',      label: 'Bedingt fliegbar',  sub: 'Einschränkungen beachten' },
            not_safe:    { cls: 'not_safe',     icon: '\u2715', label: 'Nicht fliegbar',     sub: 'Sicherheitsrisiken vorhanden' },
            no_data:     { cls: 'unknown',      icon: '?',      label: 'Keine Daten',        sub: 'Wetterdaten unvollständig' },
            error:       { cls: 'unknown',      icon: '\u26A0', label: 'Analyse-Fehler',     sub: escHtml(a.error || 'Analyse fehlgeschlagen') }
        };
        var dc = decisionConfig[safetyStatus] || decisionConfig.error;

        if (phase2Ok) {
            var flyQualLabels = { gray: 'Soaring / Abgleiter', green: 'Gut fliegbar', violet: 'Hervorragend — XC-Tag' };
            dc.sub = flyQualLabels[quality] || dc.sub;
        }

        html += '<div class="mga-decision ' + dc.cls + '">'
            + '<div class="mga-decision-icon">' + dc.icon + '</div>'
            + '<div class="mga-decision-text">'
            + '<div class="mga-decision-status">' + escHtml(dc.label) + '</div>';
        if (dc.sub) {
            html += '<div class="mga-decision-sub">' + escHtml(dc.sub) + '</div>';
        }
        html += '</div>';
        if (phase2Ok) {
            var flyBadgeLabels = { gray: 'Abgleiter', green: 'Thermik', violet: 'XC-Tag' };
            html += '<span class="mga-fly-badge ' + quality + '">'
                + escHtml(flyBadgeLabels[quality] || quality) + '</span>';
        }
        html += '</div>';

        // Early return for error / no_data
        if (safetyStatus === 'no_data' || safetyStatus === 'error') {
            var info = a.safety_feedback || a.summary || '';
            if (info) {
                html += '<div style="padding:8px 12px;font-size:12.5px;color:var(--color-text-light);line-height:1.5;">'
                    + escHtml(info) + '</div>';
            }
            html += '</div>';
            return html;
        }

        // ── Level 2: Best Window ──
        var bestWindow = a.safe_window || a.best_window || '';
        if (bestWindow) {
            html += '<div class="mga-window">'
                + '<div>'
                + '<div class="mga-window-label">Bestes Fenster</div>'
                + '<div class="mga-window-time">' + escHtml(bestWindow) + '</div>'
                + '</div>'
                + '</div>';
        }

        // ── Level 4: Safety & Quality Alerts ──
        var noGoReasons = parseArray(a.no_go_reasons);
        var cautionNotes = parseArray(a.caution_notes);
        var flyabilityLimits = parseArray(a.flyability_limits);
        var highlightNotes = parseArray(a.highlights);
        if (noGoReasons.length > 0 || cautionNotes.length > 0 || flyabilityLimits.length > 0 || highlightNotes.length > 0) {
            html += '<div class="mga-alerts">';
            noGoReasons.forEach(function(r) {
                html += '<div class="mga-alert nogo">'
                    + '<div class="mga-alert-icon">\u2715</div>'
                    + '<div>' + escHtml(r) + '</div></div>';
            });
            cautionNotes.forEach(function(n) {
                html += '<div class="mga-alert caution">'
                    + '<div class="mga-alert-icon">!</div>'
                    + '<div>' + escHtml(n) + '</div></div>';
            });
            if (phase2Ok) {
                flyabilityLimits.forEach(function(l) {
                    html += '<div class="mga-alert flyability">'
                        + '<div class="mga-alert-icon">\u2193</div>'
                        + '<div>' + escHtml(l) + '</div></div>';
                });
                highlightNotes.forEach(function(h) {
                    html += '<div class="mga-alert positive">'
                        + '<div class="mga-alert-icon">\u2713</div>'
                        + '<div>' + escHtml(h) + '</div></div>';
                });
            }
            html += '</div>';
        }

        // ── Level 3: Key Metrics Grid ──
        html += '<div class="mga-metrics">';
        html += '<div class="mga-metric full-width">'
            + '<div class="mga-metric-label">Wind</div>'
            + '<div class="mga-metric-value">' + escHtml(a.wind_summary || '-') + '</div>'
            + '</div>';

        if (phase2Ok) {
            if (a.flight_type) {
                html += '<div class="mga-metric">'
                    + '<div class="mga-metric-label">Flugtyp</div>'
                    + '<div class="mga-metric-value">' + escHtml(a.flight_type) + '</div>'
                    + '</div>';
            }
            var duration = a.flight_duration_estimate || a.flight_duration || '';
            if (duration) {
                html += '<div class="mga-metric">'
                    + '<div class="mga-metric-label">Dauer</div>'
                    + '<div class="mga-metric-value">' + escHtml(duration) + '</div>'
                    + '</div>';
            }
            if (a.peak_climb_rate) {
                html += '<div class="mga-metric">'
                    + '<div class="mga-metric-label">Peak Thermik</div>'
                    + '<div class="mga-metric-value">' + escHtml(a.peak_climb_rate) + ' m/s</div>'
                    + '</div>';
            }
            if (a.xc_potential) {
                html += '<div class="mga-metric">'
                    + '<div class="mga-metric-label">XC-Potenzial</div>'
                    + '<div class="mga-metric-value">' + escHtml(a.xc_potential) + '</div>'
                    + '</div>';
            }
        }
        html += '</div>';

        // ── Level 5: AI Insights (expandable) ──
        var safetyFeedback = a.safety_feedback || a.summary || '';
        var flyFeedback = phase2Ok ? (a.flyability_feedback || a.recommendation || '') : '';

        if (safetyFeedback || flyFeedback) {
            html += '<div class="mga-insights">';
            if (safetyFeedback) {
                html += '<div class="mga-insight safety open">'
                    + '<button class="mga-insight-toggle" type="button">Sicherheits-Einschätzung</button>'
                    + '<div class="mga-insight-body">' + escHtml(safetyFeedback) + '</div>'
                    + '</div>';
            }
            if (flyFeedback) {
                html += '<div class="mga-insight flyability' + (safetyFeedback ? '' : ' open') + '">'
                    + '<button class="mga-insight-toggle" type="button">Flug-Einschätzung</button>'
                    + '<div class="mga-insight-body">' + escHtml(flyFeedback) + '</div>'
                    + '</div>';
            }
            html += '</div>';
        }

        // Timestamp
        if (a.updated_at) {
            var d = new Date(a.updated_at);
            var ts = d.toLocaleDateString('de-CH') + ' ' + d.toLocaleTimeString('de-CH', {hour:'2-digit', minute:'2-digit'});
            html += '<div class="mg-analysis-datestamp">Analyse: ' + ts + '</div>';
        }

        html += '</div>';
        return html;
    }

    // Track current overlay state for day switching
    var overlayRid = null;

    function updateOverlayAnalysis(rid, dateStr) {
        var analysisEl = document.querySelector('.region-overlay-analysis');
        if (!analysisEl) return;
        var ra = regionAnalyses ? regionAnalyses[rid] : null;
        var dayData = ra ? ra[dateStr] : null;
        var regionName = (meteogramCache[rid] && meteogramCache[rid].regionName) || rid;
        analysisEl.innerHTML = buildAnalysisHtml(dayData || { region_name: regionName, safety_status: 'no_data' });
        // Re-wire expandable insight toggles
        analysisEl.querySelectorAll('.mga-insight-toggle').forEach(function(btn) {
            btn.addEventListener('click', function() {
                btn.parentElement.classList.toggle('open');
            });
        });
    }

    function openRegionOverlay(rid, a) {
        if (!overlay) return;
        overlayRid = rid;

        var regionName = a.region_name || rid;
        // Pre-cache region name so renderRegionTextView can include it in JSON payload
        if (!meteogramCache[rid]) meteogramCache[rid] = {};
        meteogramCache[rid].regionName = regionName;
        overlayTitle.textContent = regionName;

        // Build side-by-side layout: analysis left, meteogram right
        var analysisHtml = buildAnalysisHtml(a);

        var bodyHtml = '<div class="region-overlay-day-tabs" id="regionOverlayDayTabs"></div>';
        bodyHtml += '<div class="region-overlay-content">';
        bodyHtml += '<div class="region-overlay-analysis">' + analysisHtml + '</div>';
        bodyHtml += '<div class="region-overlay-meteogram">';
        bodyHtml += '<div class="meteogram-view-tabs" id="regionViewTabs">';
        bodyHtml += '<button class="view-tab active" data-view="meteogram">Meteogramm</button>';
        bodyHtml += '<button class="view-tab" data-view="text">Text</button>';
        bodyHtml += '</div>';
        bodyHtml += '<div class="region-meteogram-chart" id="regionMeteogramChart"><div class="region-meteogram-loading">Meteogramm wird geladen...</div></div>';
        bodyHtml += '<div class="region-meteogram-chart" id="regionTextViewChart" style="display:none;"></div>';
        bodyHtml += '</div></div>';

        overlayBody.innerHTML = bodyHtml;
        showOverlay();

        // Wire up expandable insight toggles
        overlayBody.querySelectorAll('.mga-insight-toggle').forEach(function(btn) {
            btn.addEventListener('click', function() {
                btn.parentElement.classList.toggle('open');
            });
        });

        // View tab switching for region overlay
        var regionViewTabs = document.getElementById('regionViewTabs');
        var regionMeteogramChart = document.getElementById('regionMeteogramChart');
        var regionTextView = document.getElementById('regionTextViewChart');
        var regionCurrentView = 'meteogram';

        if (regionViewTabs) {
            regionViewTabs.querySelectorAll('.view-tab').forEach(function (btn) {
                btn.addEventListener('click', function () {
                    var view = btn.dataset.view;
                    if (view === regionCurrentView) return;
                    regionCurrentView = view;
                    regionViewTabs.querySelectorAll('.view-tab').forEach(function (b) {
                        b.classList.toggle('active', b.dataset.view === view);
                    });
                    regionMeteogramChart.style.display = 'none';
                    if (regionTextView) regionTextView.style.display = 'none';

                    if (view === 'meteogram') {
                        regionMeteogramChart.style.display = '';
                    } else if (view === 'text') {
                        if (regionTextView) regionTextView.style.display = '';
                        renderRegionTextView(rid);
                    }
                });
            });
        }

        // Load meteogram for this region
        loadRegionMeteogram(rid);
    }

    function renderRegionTextView(rid) {
        var chartEl = document.getElementById('regionTextViewChart');
        if (!chartEl) return;

        var cached = meteogramCache[rid];
        if (!cached) {
            chartEl.innerHTML = '<p style="color:#64748B;text-align:center;padding:20px">Daten werden geladen...</p>';
            return;
        }

        var altData = cached.altData;
        var wxData = cached.wxData;
        var dates = wxData.dates || [];
        var activeDate = regionActiveDate[rid]
            || ((currentDate && dates.indexOf(currentDate) >= 0) ? currentDate : dates[0]);
        var altDayRaw = altData.data ? altData.data[activeDate] : null;
        var wxDay = wxData.data ? wxData.data[activeDate] : null;
        var elevation = wxData.elevation_ref || 0;

        if (!altDayRaw || !altDayRaw.length) {
            chartEl.innerHTML = '<p style="color:#64748B;text-align:center;padding:20px">Keine H&ouml;henwinddaten</p>';
            return;
        }

        var altDay = {
            profiles: altDayRaw.map(function (entry) {
                var paddedHour = String(entry.hour).padStart(2, '0');
                return {
                    time: activeDate + 'T' + paddedHour + ':00:00',
                    levels: entry.profiles
                };
            })
        };

        Meteogram.renderTextView(chartEl, wxDay, altDay, {
            elevation: elevation,
            spotName: cached.regionName || rid,
            dateStr: activeDate,
            source: 'gleitcast-region',
        });
    }

    function loadRegionMeteogram(rid) {
        var chartEl = document.getElementById('regionMeteogramChart');

        // Check cache — must contain BOTH wxData AND altData. The cache may already
        // hold a stub object with only `regionName` (pre-set in openRegionOverlay()),
        // which would otherwise short-circuit the fetch and crash renderRegionMeteogram.
        if (meteogramCache[rid] && meteogramCache[rid].wxData && meteogramCache[rid].altData) {
            renderRegionMeteogram(rid, meteogramCache[rid].wxData, meteogramCache[rid].altData, chartEl);
            return;
        }

        // Fetch region weather + altitude-wind in parallel
        Promise.all([
            fetchJson('/api/region-weather/' + encodeURIComponent(rid)),
            fetchJson('/api/region-altitude-wind/' + encodeURIComponent(rid))
        ])
            .then(function (results) {
                var wxData = results[0];
                var altData = results[1];

                if (wxData.error || altData.error) {
                    chartEl.innerHTML = '<div class="region-meteogram-loading">Keine Wetterdaten verfuegbar</div>';
                    return;
                }

                var prevName = meteogramCache[rid] && meteogramCache[rid].regionName;
                meteogramCache[rid] = { wxData: wxData, altData: altData, regionName: prevName };
                renderRegionMeteogram(rid, wxData, altData, chartEl);
            })
            .catch(function (err) {
                chartEl.innerHTML = '<div class="region-meteogram-loading">Fehler: ' + escHtml(err.message) + '</div>';
            });
    }

    function renderRegionMeteogram(rid, wxData, altData, chartEl) {
        if (!wxData.dates || wxData.dates.length === 0) {
            chartEl.innerHTML = '<div class="region-meteogram-loading">Keine Wetterdaten verfuegbar</div>';
            return;
        }

        // Stale-Banner
        if (wxData.stale) {
            var expected = wxData.expected_days || 5;
            var have = (wxData.dates || []).length;
            var lastUpd = wxData.last_updated ? wxData.last_updated.replace('T', ' ').slice(0, 16) : 'unbekannt';
            var bannerContainer = chartEl.parentNode;
            var existingBanner = bannerContainer ? bannerContainer.querySelector('.meteogram-stale-banner') : null;
            if (existingBanner) existingBanner.parentNode.removeChild(existingBanner);
            var bannerDiv = document.createElement('div');
            bannerDiv.className = 'meteogram-stale-banner';
            bannerDiv.innerHTML =
                '<strong>Wetterdaten veraltet:</strong> ' +
                'Nur ' + have + ' von ' + expected + ' Vorhersagetagen verfügbar. ' +
                'Letztes erfolgreiches Update: ' + escHtml(lastUpd) + '.';
            if (bannerContainer) bannerContainer.insertBefore(bannerDiv, chartEl);
        }

        // Find date to display: prefer currentDate if available, else first
        var dates = wxData.dates;
        var activeDate = (currentDate && dates.indexOf(currentDate) >= 0) ? currentDate : dates[0];
        if (rid) regionActiveDate[rid] = activeDate;

        // Build overlay-level day tabs
        var overlayTabsEl = document.getElementById('regionOverlayDayTabs');
        if (overlayTabsEl) {
            overlayTabsEl.innerHTML = '';
            dates.forEach(function (d) {
                var btn = document.createElement('button');
                btn.textContent = Meteogram.formatDayTabLabel(d);
                btn.className = 'tab-btn' + (d === activeDate ? ' active' : '');
                btn.addEventListener('click', function () {
                    overlayTabsEl.querySelectorAll('.tab-btn').forEach(function (b) { b.classList.remove('active'); });
                    btn.classList.add('active');
                    if (rid) regionActiveDate[rid] = d;
                    // Update meteogram
                    renderMeteogramDay(wxData, altData, d, chartEl);
                    // Update analysis panel
                    updateOverlayAnalysis(rid, d);
                    // Update text view if visible
                    var textEl = document.getElementById('regionTextViewChart');
                    if (textEl && textEl.style.display !== 'none') renderRegionTextView(rid);
                    // Sync navbar
                    window.currentDate = d;
                    var navTabs = document.getElementById('navDayTabs');
                    if (navTabs) {
                        navTabs.querySelectorAll('.navbar-day-btn').forEach(function (b) {
                            b.classList.toggle('active', b.dataset.date === d);
                        });
                    }
                });
                overlayTabsEl.appendChild(btn);
            });
        }

        renderMeteogramDay(wxData, altData, activeDate, chartEl);
    }

    function renderMeteogramDay(wxData, altData, dateStr, chartEl) {
        chartEl.innerHTML = '';

        var wxDay = wxData.data ? wxData.data[dateStr] : null;
        var altDayRaw = altData.data ? altData.data[dateStr] : null;

        // Convert altDayRaw (array of {hour, profiles}) to the format Meteogram expects
        var altDay = null;
        if (altDayRaw && altDayRaw.length > 0) {
            altDay = {
                profiles: altDayRaw.map(function (entry) {
                    var paddedHour = String(entry.hour).padStart(2, '0');
                    return {
                        time: dateStr + 'T' + paddedHour + ':00:00',
                        levels: entry.profiles
                    };
                })
            };
        }

        if (!altDay || !altDay.profiles || altDay.profiles.length === 0) {
            chartEl.innerHTML = '<div class="region-meteogram-loading">Keine Daten fuer diesen Tag</div>';
            return;
        }

        // Regionen haben keinen Startplatz — kein Bodenwind-Row, keine
        // Startplatz-Linie. Der Region-Referenzpunkt ist nur ein geografischer
        // Ankerpunkt, nicht repräsentativ für einzelne Spots der Region.
        // `isRegion: true` sorgt dafür, dass Thermik auch in Zeilen UNTER dem
        // Referenzpunkt gerendert wird (Region-Einzugsgebiet hat Spots auf
        // verschiedenen Höhen, nicht nur am Referenzpunkt).
        Meteogram.renderChart(chartEl, meteogramTooltip, wxDay, altDay, {
            elevation: altData.elevation_m || 0,
            isRegion: true,
        });

        // Wetter-Zeitstempel unter dem Meteogramm
        if (wxData.last_updated) {
            var weatherTs = wxData.last_updated.replace('T', ' ').slice(0, 16);
            var tsDiv = document.createElement('div');
            tsDiv.style.cssText = 'font-size:10px;color:#94a3b8;text-align:right;padding:2px 8px 0;';
            tsDiv.textContent = 'Wetter-Stand: ' + weatherTs;
            chartEl.appendChild(tsDiv);
        }
    }

    function showOverlay() {
        overlay.style.display = 'flex';
        overlay.classList.add('visible');
        if (window._overlayScrollLock) window._overlayScrollLock();
        if (overlayClose) overlayClose.focus();
    }

    function closeRegionOverlay() {
        if (!overlay) return;
        overlay.style.display = 'none';
        overlay.classList.remove('visible');
        if (window._overlayScrollUnlock) window._overlayScrollUnlock();
    }

    function parseArray(val) {
        if (!val) return [];
        if (Array.isArray(val)) return val;
        if (typeof val === 'string') {
            try { var p = JSON.parse(val); if (Array.isArray(p)) return p; } catch (e) { /* */ }
            return val ? [val] : [];
        }
        return [];
    }

    function escHtml(str) {
        if (str === null || str === undefined) return '';
        var div = document.createElement('div');
        div.textContent = String(str);
        return div.innerHTML;
    }

    // ===== EVENT LISTENERS =====
    if (overlayClose) overlayClose.addEventListener('click', closeRegionOverlay);

    var overlayShare = document.getElementById('regionOverlayShare');
    if (overlayShare) {
        overlayShare.addEventListener('click', function () {
            if (!overlayRid || typeof window.gleitcastShare !== 'function') return;
            var regionName = (meteogramCache[overlayRid] && meteogramCache[overlayRid].regionName) || overlayRid;
            var dateStr = regionActiveDate[overlayRid] || currentDate || window.currentDate;
            var dayIdx = 0;
            if (dateStr) {
                var now = new Date();
                var today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
                var target = new Date(dateStr + 'T12:00:00');
                dayIdx = Math.max(0, Math.round((target - today) / 86400000));
            }
            window.gleitcastShare({
                region_id: overlayRid,
                day_idx: dayIdx,
                title: regionName + ' · Gleitcast',
                text: regionName + ' · Gleitcast Flugwetter',
            });
        });
    }
    if (overlay) overlay.addEventListener('click', function (e) { if (e.target === overlay) closeRegionOverlay(); });
    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && overlay && overlay.classList.contains('visible')) closeRegionOverlay();
    });

    // Listen for navbar day changes — update open overlay + map coloring
    window.addEventListener('gleitcast-day-change', function (e) {
        var newDate = e.detail && e.detail.date;
        if (!newDate) return;
        currentDate = newDate;
        colorRegions(newDate);

        // If overlay is open, update day tabs + analysis + charts
        if (overlayRid && overlay && overlay.classList.contains('visible')) {
            updateOverlayAnalysis(overlayRid, newDate);
            if (overlayRid) regionActiveDate[overlayRid] = newDate;
            // Sync overlay day tabs
            var overlayTabsEl = document.getElementById('regionOverlayDayTabs');
            if (overlayTabsEl) {
                overlayTabsEl.querySelectorAll('.tab-btn').forEach(function (b) {
                    b.classList.toggle('active', b.textContent === Meteogram.formatDayTabLabel(newDate));
                });
            }
            // Re-render meteogram for new day
            var cache = meteogramCache[overlayRid];
            if (cache && cache.wxData && cache.altData) {
                var chartEl = document.getElementById('regionMeteogramChart');
                if (chartEl) renderMeteogramDay(cache.wxData, cache.altData, newDate, chartEl);
            }
            // Re-render text view if visible
            var textEl = document.getElementById('regionTextViewChart');
            if (textEl && textEl.style.display !== 'none') renderRegionTextView(overlayRid);
        }
    });

    // ===== GLOBAL API =====
    window.setRegionAnalyses = function (nested) {
        regionAnalyses = nested;
        if (currentDate) colorRegions(currentDate);
    };

    window.setRegionDate = function (dateStr) {
        currentDate = dateStr;
        colorRegions(dateStr);
    };

    initMap();
})();
