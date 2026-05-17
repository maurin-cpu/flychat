/**
 * ChatCharts - Rendering module for chat visualizations.
 *
 * Provides four entry points called after each bot message:
 *   ChatCharts.renderTemplateCharts(el)  — D3 templates (wind_timeline, thermal_timeline, foehn, wind_profile)
 *   ChatCharts.renderMeteograms(el)      — Full Meteogram via Meteogram.renderChart()
 *   ChatCharts.renderMaps(el)            — Mini Leaflet maps
 *   ChatCharts.renderChartjsBlocks(el)   — Chart.js dynamic fallback
 */
window.ChatCharts = (function () {
    'use strict';

    // ── Helpers ──────────────────────────────────────────

    function parseParams(paramStr) {
        var params = {};
        paramStr.split('|').forEach(function (part) {
            var eq = part.indexOf('=');
            if (eq > 0) params[part.substring(0, eq).trim()] = part.substring(eq + 1).trim();
        });
        return params;
    }

    function showLoading(el) {
        el.innerHTML = '<div class="chart-loading">Daten werden geladen\u2026</div>';
    }

    function showError(el, msg) {
        el.innerHTML = '<div class="chart-error">' + (msg || 'Fehler beim Laden') + '</div>';
    }

    function todayStr() {
        var d = new Date();
        return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
    }

    function resolveDate(params) {
        return params.date || todayStr();
    }

    function fetchJSON(url) {
        return fetch(url).then(function (r) {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.json();
        });
    }

    // ── Color scales (reuse from Meteogram when available) ──

    function windColor(speed) {
        if (window.Meteogram && window.Meteogram.windColor) return window.Meteogram.windColor(speed);
        if (speed <= 10) return '#059669';
        if (speed <= 20) return '#10B981';
        if (speed <= 25) return '#D97706';
        if (speed <= 30) return '#EA580C';
        return '#DC2626';
    }

    // Aligned to sustained_peak pilot bands — Palette v3.2 Royal Premium (final),
    // synchron zu meteogram.js:thermClimbColor und docs/RATING_FARBKONZEPT.md.
    // <1.0 Abgleiter | 1.0-1.5 mau | 1.5-2.0 solide | 2.0-2.5 stark/XC | >=2.5 Klassiker
    function thermClimbColor(rate) {
        if (rate <= 0) return 'transparent';
        if (rate < 1.0) return '#e0f2fe';  // Sky-100 (Rating 1)
        if (rate < 1.5) return '#bae6fd';  // Sky-200 (Rating 2)
        if (rate < 2.0) return '#BEF264';  // Lime-300 (Rating 3)
        if (rate < 2.5) return '#22c55e';  // Green-500 (Rating 4, klassisches Safety-Green)
        return '#a78bfa';                   // Violet-400 (Rating 5, Royal Premium)
    }

    function thermalRateAtAltitude(climbRate, maxHeight, elevation, altitude) {
        if (window.Meteogram && window.Meteogram.thermalRateAtAltitude) {
            return window.Meteogram.thermalRateAtAltitude(climbRate, maxHeight, elevation, altitude);
        }
        if (altitude < elevation || altitude >= maxHeight || climbRate <= 0) return 0;
        var columnH = maxHeight - elevation;
        if (columnH <= 0) return 0;
        var frac = (altitude - elevation) / columnH;
        var profile = 4 * frac * (1 - frac);
        var localRate = climbRate * (0.45 + 0.55 * profile);
        return Math.max(0.1, Math.round(localRate * 10) / 10);
    }

    // ── Tooltip helper ──────────────────────────────────

    function createTooltip(parentEl) {
        var tip = document.createElement('div');
        tip.className = 'chart-tooltip';
        tip.style.display = 'none';
        parentEl.appendChild(tip);
        return {
            show: function (x, y, html) {
                tip.innerHTML = html;
                tip.style.display = 'block';
                tip.style.left = x + 12 + 'px';
                tip.style.top = y - 10 + 'px';
            },
            hide: function () { tip.style.display = 'none'; }
        };
    }

    // ================================================================
    // A) Template Charts (D3)
    // ================================================================

    function renderTemplateCharts(containerEl) {
        var placeholders = containerEl.querySelectorAll('.chat-chart-placeholder[data-chart-type]');
        placeholders.forEach(function (el) {
            var type = el.getAttribute('data-chart-type');
            var params = parseParams(el.getAttribute('data-chart-params') || '');
            switch (type) {
                case 'wind_timeline': renderWindTimeline(el, params); break;
                case 'thermal_timeline': renderThermalTimeline(el, params); break;
                case 'foehn': renderFoehn(el, params); break;
                case 'wind_profile': renderWindProfile(el, params); break;
                default: showError(el, 'Unbekannter Chart-Typ: ' + type);
            }
        });
    }

    // ── Wind Timeline ──────────────────────────────────

    function renderWindTimeline(el, params) {
        var spot = params.spot;
        var date = resolveDate(params);
        if (!spot) { showError(el, 'Kein Spot angegeben'); return; }
        showLoading(el);

        fetchJSON('/api/weather/' + encodeURIComponent(spot)).then(function (resp) {
            var dayData = (resp.data || {})[date];
            if (!dayData || !dayData.wind || dayData.wind.length === 0) {
                showError(el, 'Keine Winddaten f\u00fcr ' + spot + ' am ' + date);
                return;
            }
            el.innerHTML = '';
            if (params.title) {
                var titleEl = document.createElement('div');
                titleEl.className = 'chat-chart-title';
                titleEl.textContent = params.title;
                el.appendChild(titleEl);
            }
            drawWindTimeline(el, dayData.wind);
        }).catch(function (err) { showError(el, 'Fehler: ' + err.message); });
    }

    function drawWindTimeline(container, windData) {
        var margin = { top: 16, right: 20, bottom: 32, left: 44 };
        var width = Math.max(container.clientWidth || 400, 300);
        var height = 220;
        var innerW = width - margin.left - margin.right;
        var innerH = height - margin.top - margin.bottom;

        var svg = d3.select(container).append('svg')
            .attr('viewBox', '0 0 ' + width + ' ' + height)
            .attr('preserveAspectRatio', 'xMidYMid meet');

        var g = svg.append('g').attr('transform', 'translate(' + margin.left + ',' + margin.top + ')');

        // Filter to 06-18h
        var data = windData.filter(function (d) {
            var h = new Date(d.time).getHours();
            return h >= 6 && h <= 18;
        });
        if (data.length === 0) { showError(container, 'Keine Daten 06-18h'); return; }

        var x = d3.scalePoint().domain(data.map(function (d) { return d.time; })).range([0, innerW]).padding(0.3);
        var maxVal = d3.max(data, function (d) { return Math.max(d.speed || 0, d.gusts || 0); }) || 30;
        var y = d3.scaleLinear().domain([0, maxVal * 1.15]).range([innerH, 0]);

        // Grid
        g.selectAll('.grid-line').data(y.ticks(5)).enter().append('line')
            .attr('class', 'grid-line')
            .attr('x1', 0).attr('x2', innerW)
            .attr('y1', function (d) { return y(d); })
            .attr('y2', function (d) { return y(d); });

        // X axis labels
        g.selectAll('.x-label').data(data).enter().append('text')
            .attr('class', 'axis-label')
            .attr('x', function (d) { return x(d.time); })
            .attr('y', innerH + 20)
            .attr('text-anchor', 'middle')
            .text(function (d) { return String(new Date(d.time).getHours()).padStart(2, '0'); });

        // Y axis labels
        g.selectAll('.y-label').data(y.ticks(5)).enter().append('text')
            .attr('class', 'axis-label')
            .attr('x', -8).attr('y', function (d) { return y(d) + 3; })
            .attr('text-anchor', 'end')
            .text(function (d) { return d + ' km/h'; });

        // Böen-Daten vorhanden? Regionen liefern gusts=null → keine Gust-Visualisierung.
        var hasGusts = data.some(function (d) { return d.gusts != null && d.gusts > d.speed; });

        var windLine = d3.line()
            .x(function (d) { return x(d.time); })
            .y(function (d) { return y(d.speed || 0); })
            .curve(d3.curveMonotoneX);

        if (hasGusts) {
            var gustLine = d3.line()
                .x(function (d) { return x(d.time); })
                .y(function (d) { return y(d.gusts || d.speed || 0); })
                .curve(d3.curveMonotoneX);

            // Area between wind and gusts
            var area = d3.area()
                .x(function (d) { return x(d.time); })
                .y0(function (d) { return y(d.speed || 0); })
                .y1(function (d) { return y(d.gusts || d.speed || 0); })
                .curve(d3.curveMonotoneX);

            g.append('path').datum(data)
                .attr('d', area)
                .attr('fill', 'rgba(234, 88, 12, 0.12)');

            // Gust line
            g.append('path').datum(data)
                .attr('d', gustLine)
                .attr('fill', 'none')
                .attr('stroke', '#EA580C')
                .attr('stroke-width', 1.5)
                .attr('stroke-dasharray', '4,3');
        }

        // Wind line
        g.append('path').datum(data)
            .attr('d', windLine)
            .attr('fill', 'none')
            .attr('stroke', '#10B981')
            .attr('stroke-width', 2);

        // Dots
        var tip = createTooltip(container);
        g.selectAll('.wind-dot').data(data).enter().append('circle')
            .attr('cx', function (d) { return x(d.time); })
            .attr('cy', function (d) { return y(d.speed || 0); })
            .attr('r', 3.5)
            .attr('fill', function (d) { return windColor(d.speed || 0); })
            .attr('stroke', 'white')
            .attr('stroke-width', 1.5)
            .on('mouseover', function (event, d) {
                var h = new Date(d.time).getHours();
                var gustLine = (d.gusts != null && d.gusts > d.speed)
                    ? '<br>B\u00f6en: ' + d.gusts + ' km/h'
                    : '';
                tip.show(event.offsetX, event.offsetY,
                    '<b>' + h + ':00</b><br>Wind: ' + (d.speed || 0) + ' km/h' + gustLine +
                    (d.direction_label ? '<br>Richtung: ' + d.direction_label : ''));
            })
            .on('mouseout', function () { tip.hide(); });

        // Legend
        var legend = document.createElement('div');
        legend.className = 'chart-legend';
        legend.innerHTML =
            '<span class="chart-legend-item"><span class="chart-legend-swatch" style="background:#10B981"></span> Wind</span>' +
            '<span class="chart-legend-item"><span class="chart-legend-swatch" style="background:#EA580C"></span> B\u00f6en</span>';
        container.appendChild(legend);
    }

    // ── Thermal Timeline (Heatmap) ──────────────────────

    function renderThermalTimeline(el, params) {
        var spot = params.spot;
        var date = resolveDate(params);
        if (!spot) { showError(el, 'Kein Spot angegeben'); return; }
        showLoading(el);

        fetchJSON('/api/weather/' + encodeURIComponent(spot)).then(function (resp) {
            var dayData = (resp.data || {})[date];
            var elevation = resp.elevation_m || 850;
            if (!dayData || !dayData.thermik || dayData.thermik.length === 0) {
                showError(el, 'Keine Thermikdaten f\u00fcr ' + spot + ' am ' + date);
                return;
            }
            el.innerHTML = '';
            if (params.title) {
                var titleEl = document.createElement('div');
                titleEl.className = 'chat-chart-title';
                titleEl.textContent = params.title;
                el.appendChild(titleEl);
            }
            drawThermalTimeline(el, dayData.thermik, elevation);
        }).catch(function (err) { showError(el, 'Fehler: ' + err.message); });
    }

    function drawThermalTimeline(container, thermikData, elevation) {
        // Filter 06-18h and only entries with climb_rate > 0
        var data = thermikData.filter(function (d) {
            var h = new Date(d.time).getHours();
            return h >= 6 && h <= 18 && d.climb_rate > 0;
        });
        if (data.length === 0) {
            showError(container, 'Keine Thermik an diesem Tag');
            return;
        }

        var margin = { top: 16, right: 20, bottom: 32, left: 56 };
        var width = Math.max(container.clientWidth || 400, 300);
        var height = 280;
        var innerW = width - margin.left - margin.right;
        var innerH = height - margin.top - margin.bottom;

        // Build altitude steps (every 200m from elevation to max height)
        var maxH = d3.max(data, function (d) { return d.max_height || 0; }) || 3000;
        var altSteps = [];
        for (var a = Math.ceil(elevation / 200) * 200; a <= maxH; a += 200) altSteps.push(a);
        if (altSteps.length === 0) altSteps = [elevation + 200];

        var times = data.map(function (d) { return d.time; });

        var x = d3.scaleBand().domain(times).range([0, innerW]).padding(0.05);
        var y = d3.scaleBand().domain(altSteps).range([innerH, 0]).padding(0.05);

        var svg = d3.select(container).append('svg')
            .attr('viewBox', '0 0 ' + width + ' ' + height)
            .attr('preserveAspectRatio', 'xMidYMid meet');

        var g = svg.append('g').attr('transform', 'translate(' + margin.left + ',' + margin.top + ')');

        // X labels
        g.selectAll('.x-label').data(times).enter().append('text')
            .attr('class', 'axis-label')
            .attr('x', function (d) { return x(d) + x.bandwidth() / 2; })
            .attr('y', innerH + 18)
            .attr('text-anchor', 'middle')
            .text(function (d) { return String(new Date(d).getHours()).padStart(2, '0'); });

        // Y labels
        g.selectAll('.y-label').data(altSteps).enter().append('text')
            .attr('class', 'axis-label')
            .attr('x', -8).attr('y', function (d) { return y(d) + y.bandwidth() / 2 + 3; })
            .attr('text-anchor', 'end')
            .text(function (d) { return d + 'm'; });

        // Cells
        var tip = createTooltip(container);
        data.forEach(function (d) {
            altSteps.forEach(function (alt) {
                var rate = thermalRateAtAltitude(d.climb_rate, d.max_height || maxH, elevation, alt);
                if (rate <= 0) return;
                var color = thermClimbColor(rate);
                g.append('rect')
                    .attr('x', x(d.time))
                    .attr('y', y(alt))
                    .attr('width', x.bandwidth())
                    .attr('height', y.bandwidth())
                    .attr('fill', color)
                    .attr('rx', 2)
                    .on('mouseover', function (event) {
                        tip.show(event.offsetX, event.offsetY,
                            '<b>' + new Date(d.time).getHours() + ':00 / ' + alt + 'm</b><br>' +
                            'Steigen: ' + rate + ' m/s');
                    })
                    .on('mouseout', function () { tip.hide(); });

                // Rate text
                if (rate >= 0.3 && x.bandwidth() > 18 && y.bandwidth() > 12) {
                    g.append('text')
                        .attr('x', x(d.time) + x.bandwidth() / 2)
                        .attr('y', y(alt) + y.bandwidth() / 2 + 3)
                        .attr('text-anchor', 'middle')
                        .attr('font-size', '9px')
                        .attr('font-weight', '600')
                        .attr('fill', '#1E293B')
                        .text(rate.toFixed(1));
                }
            });
        });

        // Legend
        var legend = document.createElement('div');
        legend.className = 'chart-legend';
        legend.innerHTML = [
            ['#e0f2fe', '0.3-0.75'], ['#bae6fd', '0.75-1.25'], ['#BEF264', '1.25-1.75'],
            ['#22c55e', '1.75-2.25'], ['#a78bfa', '>2.25']
        ].map(function (p) {
            return '<span class="chart-legend-item"><span class="chart-legend-swatch" style="background:' + p[0] + '"></span>' + p[1] + ' m/s</span>';
        }).join('');
        container.appendChild(legend);
    }

    // ── F\u00f6hn Chart ──────────────────────────────────

    function renderFoehn(el, params) {
        var date = resolveDate(params);
        showLoading(el);

        fetchJSON('/api/foehn').then(function (resp) {
            var dayData = (resp.data || resp)[date];
            if (!dayData || dayData.length === 0) {
                showError(el, 'Keine F\u00f6hndaten f\u00fcr ' + date);
                return;
            }
            el.innerHTML = '';
            if (params.title) {
                var titleEl = document.createElement('div');
                titleEl.className = 'chat-chart-title';
                titleEl.textContent = params.title;
                el.appendChild(titleEl);
            }
            drawFoehn(el, dayData);
        }).catch(function (err) { showError(el, 'Fehler: ' + err.message); });
    }

    function drawFoehn(container, data) {
        var margin = { top: 16, right: 56, bottom: 32, left: 48 };
        var width = Math.max(container.clientWidth || 400, 300);
        var height = 220;
        var innerW = width - margin.left - margin.right;
        var innerH = height - margin.top - margin.bottom;

        var svg = d3.select(container).append('svg')
            .attr('viewBox', '0 0 ' + width + ' ' + height)
            .attr('preserveAspectRatio', 'xMidYMid meet');

        var g = svg.append('g').attr('transform', 'translate(' + margin.left + ',' + margin.top + ')');

        var x = d3.scalePoint().domain(data.map(function (d) { return d.hour; })).range([0, innerW]).padding(0.3);

        // Delta-P axis (left)
        var dpExtent = d3.extent(data, function (d) { return d.delta_p; });
        var dpMin = Math.min(dpExtent[0] || -5, -5);
        var dpMax = Math.max(dpExtent[1] || 5, 5);
        var yDP = d3.scaleLinear().domain([dpMin, dpMax]).range([innerH, 0]);

        // Wind axis (right)
        var windMax = d3.max(data, function (d) { return d.crest_wind_kmh || 0; }) || 80;
        var yWind = d3.scaleLinear().domain([0, windMax * 1.15]).range([innerH, 0]);

        // Zero line for delta-P
        g.append('line')
            .attr('x1', 0).attr('x2', innerW)
            .attr('y1', yDP(0)).attr('y2', yDP(0))
            .attr('stroke', '#94a3b8').attr('stroke-dasharray', '3,3');

        // Grid
        g.selectAll('.grid-line').data(yDP.ticks(5)).enter().append('line')
            .attr('class', 'grid-line')
            .attr('x1', 0).attr('x2', innerW)
            .attr('y1', function (d) { return yDP(d); })
            .attr('y2', function (d) { return yDP(d); });

        // X labels
        g.selectAll('.x-label').data(data).enter().append('text')
            .attr('class', 'axis-label')
            .attr('x', function (d) { return x(d.hour); })
            .attr('y', innerH + 20)
            .attr('text-anchor', 'middle')
            .text(function (d) { return String(d.hour).padStart(2, '0'); });

        // Left Y labels (delta-P)
        g.selectAll('.y-dp-label').data(yDP.ticks(5)).enter().append('text')
            .attr('class', 'axis-label')
            .attr('x', -8).attr('y', function (d) { return yDP(d) + 3; })
            .attr('text-anchor', 'end')
            .text(function (d) { return d + ' hPa'; });

        // Right Y labels (wind)
        g.selectAll('.y-wind-label').data(yWind.ticks(4)).enter().append('text')
            .attr('class', 'axis-label')
            .attr('x', innerW + 8).attr('y', function (d) { return yWind(d) + 3; })
            .attr('text-anchor', 'start')
            .text(function (d) { return d + ' km/h'; });

        // Delta-P line
        var dpLine = d3.line()
            .x(function (d) { return x(d.hour); })
            .y(function (d) { return yDP(d.delta_p || 0); })
            .curve(d3.curveMonotoneX)
            .defined(function (d) { return d.delta_p != null; });

        g.append('path').datum(data)
            .attr('d', dpLine)
            .attr('fill', 'none')
            .attr('stroke', '#0369a1')
            .attr('stroke-width', 2);

        // Wind line
        var wLine = d3.line()
            .x(function (d) { return x(d.hour); })
            .y(function (d) { return yWind(d.crest_wind_kmh || 0); })
            .curve(d3.curveMonotoneX)
            .defined(function (d) { return d.crest_wind_kmh != null; });

        g.append('path').datum(data)
            .attr('d', wLine)
            .attr('fill', 'none')
            .attr('stroke', '#EA580C')
            .attr('stroke-width', 1.5);

        // Foehn level background bands
        var tip = createTooltip(container);
        var levelColors = { none: 'transparent', low: 'rgba(234,179,8,0.08)', moderate: 'rgba(234,179,8,0.18)', high: 'rgba(220,38,38,0.12)' };
        data.forEach(function (d, i) {
            var next = data[i + 1];
            var w = next ? (x(next.hour) - x(d.hour)) : x.step ? x.step() : 20;
            var color = levelColors[d.level] || 'transparent';
            if (color !== 'transparent') {
                g.append('rect')
                    .attr('x', x(d.hour) - w / 2)
                    .attr('y', 0)
                    .attr('width', w)
                    .attr('height', innerH)
                    .attr('fill', color);
            }
        });

        // Dots with tooltip
        g.selectAll('.dp-dot').data(data.filter(function (d) { return d.delta_p != null; })).enter().append('circle')
            .attr('cx', function (d) { return x(d.hour); })
            .attr('cy', function (d) { return yDP(d.delta_p || 0); })
            .attr('r', 3)
            .attr('fill', '#0369a1')
            .attr('stroke', 'white').attr('stroke-width', 1)
            .on('mouseover', function (event, d) {
                tip.show(event.offsetX, event.offsetY,
                    '<b>' + d.hour + ':00</b><br>\u0394P: ' + (d.delta_p != null ? d.delta_p + ' hPa' : '-') +
                    '<br>Kammwind: ' + (d.crest_wind_kmh || '-') + ' km/h' +
                    '<br>Level: ' + (d.level || '-'));
            })
            .on('mouseout', function () { tip.hide(); });

        // Legend
        var legend = document.createElement('div');
        legend.className = 'chart-legend';
        legend.innerHTML =
            '<span class="chart-legend-item"><span class="chart-legend-swatch" style="background:#0369a1"></span> \u0394P (hPa)</span>' +
            '<span class="chart-legend-item"><span class="chart-legend-swatch" style="background:#EA580C"></span> Kammwind</span>';
        container.appendChild(legend);
    }

    // ── Wind Profile (Vertical) ──────────────────────

    function renderWindProfile(el, params) {
        var spot = params.spot;
        var date = resolveDate(params);
        var hours = (params.hours || '10,12,14,16').split(',').map(Number);
        if (!spot) { showError(el, 'Kein Spot angegeben'); return; }
        showLoading(el);

        fetchJSON('/api/altitude-wind/' + encodeURIComponent(spot)).then(function (resp) {
            var dayProfiles = (resp.data || {})[date];
            if (!dayProfiles || dayProfiles.length === 0) {
                showError(el, 'Keine H\u00f6henwinddaten f\u00fcr ' + spot + ' am ' + date);
                return;
            }
            el.innerHTML = '';
            if (params.title) {
                var titleEl = document.createElement('div');
                titleEl.className = 'chat-chart-title';
                titleEl.textContent = params.title;
                el.appendChild(titleEl);
            }
            drawWindProfile(el, dayProfiles, hours);
        }).catch(function (err) { showError(el, 'Fehler: ' + err.message); });
    }

    function drawWindProfile(container, dayProfiles, selectedHours) {
        // Filter to selected hours
        var profiles = dayProfiles.filter(function (p) { return selectedHours.indexOf(p.hour) >= 0; });
        if (profiles.length === 0) profiles = dayProfiles.slice(0, 4);

        var margin = { top: 16, right: 20, bottom: 32, left: 56 };
        var width = Math.max(container.clientWidth || 400, 300);
        var height = 260;
        var innerW = width - margin.left - margin.right;
        var innerH = height - margin.top - margin.bottom;

        var svg = d3.select(container).append('svg')
            .attr('viewBox', '0 0 ' + width + ' ' + height)
            .attr('preserveAspectRatio', 'xMidYMid meet');

        var g = svg.append('g').attr('transform', 'translate(' + margin.left + ',' + margin.top + ')');

        // Collect all altitudes and wind speeds
        var allAlts = [];
        var allSpeeds = [];
        profiles.forEach(function (p) {
            (p.profiles || []).forEach(function (lev) {
                allAlts.push(lev.altitude_m);
                allSpeeds.push(lev.speed_kmh || 0);
                if (lev.gust_kmh) allSpeeds.push(lev.gust_kmh);
            });
        });

        if (allAlts.length === 0) { showError(container, 'Keine Profildaten'); return; }

        var x = d3.scaleLinear().domain([0, d3.max(allSpeeds) * 1.15 || 50]).range([0, innerW]);
        var y = d3.scaleLinear().domain([d3.min(allAlts), d3.max(allAlts)]).range([innerH, 0]);

        // Grid
        g.selectAll('.grid-line').data(x.ticks(5)).enter().append('line')
            .attr('class', 'grid-line')
            .attr('x1', function (d) { return x(d); }).attr('x2', function (d) { return x(d); })
            .attr('y1', 0).attr('y2', innerH);

        // X labels
        g.selectAll('.x-label').data(x.ticks(5)).enter().append('text')
            .attr('class', 'axis-label')
            .attr('x', function (d) { return x(d); })
            .attr('y', innerH + 20)
            .attr('text-anchor', 'middle')
            .text(function (d) { return d + ' km/h'; });

        // Y labels
        g.selectAll('.y-label').data(y.ticks(6)).enter().append('text')
            .attr('class', 'axis-label')
            .attr('x', -8).attr('y', function (d) { return y(d) + 3; })
            .attr('text-anchor', 'end')
            .text(function (d) { return d + 'm'; });

        var colors = ['#0369a1', '#10B981', '#EA580C', '#8B5CF6', '#EC4899'];
        var tip = createTooltip(container);

        profiles.forEach(function (p, idx) {
            var levels = (p.profiles || []).slice().sort(function (a, b) { return a.altitude_m - b.altitude_m; });
            var color = colors[idx % colors.length];

            var line = d3.line()
                .x(function (d) { return x(d.speed_kmh || 0); })
                .y(function (d) { return y(d.altitude_m); })
                .curve(d3.curveMonotoneY);

            g.append('path').datum(levels)
                .attr('d', line)
                .attr('fill', 'none')
                .attr('stroke', color)
                .attr('stroke-width', 2);

            g.selectAll('.dot-' + idx).data(levels).enter().append('circle')
                .attr('cx', function (d) { return x(d.speed_kmh || 0); })
                .attr('cy', function (d) { return y(d.altitude_m); })
                .attr('r', 3)
                .attr('fill', color)
                .attr('stroke', 'white').attr('stroke-width', 1)
                .on('mouseover', function (event, d) {
                    tip.show(event.offsetX, event.offsetY,
                        '<b>' + p.hour + ':00 / ' + d.altitude_m + 'm</b><br>' +
                        'Wind: ' + (d.speed_kmh || 0) + ' km/h' +
                        (d.gust_kmh ? '<br>B\u00f6en: ' + d.gust_kmh + ' km/h' : '') +
                        (d.direction_deg != null ? '<br>Richtung: ' + d.direction_deg + '\u00b0' : ''));
                })
                .on('mouseout', function () { tip.hide(); });
        });

        // Legend
        var legend = document.createElement('div');
        legend.className = 'chart-legend';
        legend.innerHTML = profiles.map(function (p, idx) {
            return '<span class="chart-legend-item"><span class="chart-legend-swatch" style="background:' + colors[idx % colors.length] + '"></span>' + p.hour + ':00</span>';
        }).join('');
        container.appendChild(legend);
    }

    // ================================================================
    // B) Meteograms
    // ================================================================

    function renderMeteograms(containerEl) {
        var placeholders = containerEl.querySelectorAll('.chat-meteogram[data-meteogram-params]');
        placeholders.forEach(function (el) {
            var params = parseParams(el.getAttribute('data-meteogram-params') || '');
            if (params.spot) {
                renderSpotMeteogram(el, params);
            } else if (params.region) {
                renderRegionMeteogram(el, params);
            } else {
                showError(el, 'Kein Spot oder Region angegeben');
            }
        });
    }

    function renderSpotMeteogram(el, params) {
        var spot = params.spot;
        var date = resolveDate(params);
        showLoading(el);

        Promise.all([
            fetchJSON('/api/weather/' + encodeURIComponent(spot)),
            fetchJSON('/api/altitude-wind/' + encodeURIComponent(spot))
        ]).then(function (results) {
            var wxResp = results[0];
            var altResp = results[1];

            var wxDay = (wxResp.data || {})[date];
            var altProfiles = (altResp.data || {})[date];
            var elevation = wxResp.elevation_m || 850;

            if (!altProfiles || altProfiles.length === 0) {
                showError(el, 'Keine Daten f\u00fcr ' + spot + ' am ' + date);
                return;
            }

            // Transform alt data for Meteogram.renderChart
            var altDay = {
                profiles: altProfiles.map(function (e) {
                    return {
                        time: date + 'T' + String(e.hour).padStart(2, '0') + ':00:00',
                        levels: e.profiles
                    };
                })
            };

            el.innerHTML = '';
            var chartDiv = document.createElement('div');
            chartDiv.className = 'meteogram-chart';
            el.appendChild(chartDiv);

            var tooltipDiv = document.createElement('div');
            tooltipDiv.className = 'tooltip';
            el.appendChild(tooltipDiv);

            if (window.Meteogram && window.Meteogram.renderChart) {
                window.Meteogram.renderChart(chartDiv, tooltipDiv, wxDay || {}, altDay, { elevation: elevation });
            } else {
                showError(el, 'Meteogram-Modul nicht geladen');
            }
        }).catch(function (err) { showError(el, 'Fehler: ' + err.message); });
    }

    function renderRegionMeteogram(el, params) {
        var region = params.region;
        var date = resolveDate(params);
        showLoading(el);

        Promise.all([
            fetchJSON('/api/region-weather/' + encodeURIComponent(region)),
            fetchJSON('/api/region-altitude-wind/' + encodeURIComponent(region))
        ]).then(function (results) {
            var wxResp = results[0];
            var altResp = results[1];

            var wxDay = (wxResp.data || {})[date];
            var altProfiles = (altResp.data || {})[date];
            var elevation = wxResp.elevation_ref || wxResp.elevation_m || 1200;

            if (!altProfiles || altProfiles.length === 0) {
                showError(el, 'Keine Daten f\u00fcr Region ' + region + ' am ' + date);
                return;
            }

            var altDay = {
                profiles: altProfiles.map(function (e) {
                    return {
                        time: date + 'T' + String(e.hour).padStart(2, '0') + ':00:00',
                        levels: e.profiles
                    };
                })
            };

            el.innerHTML = '';
            var chartDiv = document.createElement('div');
            chartDiv.className = 'meteogram-chart';
            el.appendChild(chartDiv);

            var tooltipDiv = document.createElement('div');
            tooltipDiv.className = 'tooltip';
            el.appendChild(tooltipDiv);

            if (window.Meteogram && window.Meteogram.renderChart) {
                window.Meteogram.renderChart(chartDiv, tooltipDiv, wxDay || {}, altDay, { elevation: elevation });
            } else {
                showError(el, 'Meteogram-Modul nicht geladen');
            }
        }).catch(function (err) { showError(el, 'Fehler: ' + err.message); });
    }

    // ================================================================
    // C) Mini Maps
    // ================================================================

    function renderMaps(containerEl) {
        var placeholders = containerEl.querySelectorAll('.chat-minimap[data-map-params]');
        placeholders.forEach(function (el) {
            var params = parseParams(el.getAttribute('data-map-params') || '');
            renderMiniMap(el, params);
        });
    }

    function renderMiniMap(el, params) {
        showLoading(el);

        var spotNames = params.spots ? params.spots.split(',').map(function (s) { return s.trim(); }) : [];
        var regionId = params.region || null;

        var fetches = [];
        if (spotNames.length > 0) fetches.push(fetchJSON('/api/spots'));
        if (regionId) fetches.push(fetchJSON('/api/regionen'));

        if (fetches.length === 0) {
            showError(el, 'Keine Spots oder Region angegeben');
            return;
        }

        Promise.all(fetches).then(function (results) {
            el.innerHTML = '';
            el.style.height = '250px';

            // Ensure Leaflet CSS is loaded
            if (!document.querySelector('link[href*="leaflet"]')) {
                var link = document.createElement('link');
                link.rel = 'stylesheet';
                link.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css';
                document.head.appendChild(link);
            }

            var map = L.map(el, {
                zoomControl: false,
                attributionControl: false,
                dragging: true,
                scrollWheelZoom: false
            });

            L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
                maxZoom: 18
            }).addTo(map);

            var bounds = L.latLngBounds();
            var resultIdx = 0;

            // Add spot markers
            if (spotNames.length > 0) {
                var spotsGeoJSON = results[resultIdx++];
                (spotsGeoJSON.features || []).forEach(function (f) {
                    var name = f.properties.name;
                    if (spotNames.indexOf(name) < 0) return;
                    var coords = f.geometry.coordinates;
                    var latlng = L.latLng(coords[1], coords[0]);
                    bounds.extend(latlng);

                    L.circleMarker(latlng, {
                        radius: 6,
                        fillColor: '#0369a1',
                        fillOpacity: 0.9,
                        color: 'white',
                        weight: 2
                    }).addTo(map).bindTooltip(name, {
                        permanent: true,
                        direction: 'top',
                        offset: [0, -8],
                        className: 'map-tooltip'
                    });
                });
            }

            // Add region polygon
            if (regionId) {
                var regionGeoJSON = results[resultIdx++];
                (regionGeoJSON.features || []).forEach(function (f) {
                    var rid = f.properties.id || f.properties.name;
                    if (rid !== regionId && (f.properties.id || '').toLowerCase() !== regionId.toLowerCase()) return;

                    var layer = L.geoJSON(f, {
                        style: {
                            fillColor: '#0369a1',
                            fillOpacity: 0.15,
                            color: '#0369a1',
                            weight: 2
                        }
                    }).addTo(map);

                    bounds.extend(layer.getBounds());
                });
            }

            if (bounds.isValid()) {
                map.fitBounds(bounds, { padding: [30, 30], maxZoom: 12 });
            } else {
                map.setView([46.8, 8.2], 8);
            }

            // Fix Leaflet rendering in dynamic containers
            setTimeout(function () { map.invalidateSize(); }, 100);

        }).catch(function (err) { showError(el, 'Kartenfehler: ' + err.message); });
    }

    // ================================================================
    // D) Chart.js Fallback
    // ================================================================

    var chartjsLoaded = false;
    var chartjsLoadPromise = null;

    function loadChartjs() {
        if (chartjsLoaded) return Promise.resolve();
        if (chartjsLoadPromise) return chartjsLoadPromise;
        chartjsLoadPromise = new Promise(function (resolve, reject) {
            var script = document.createElement('script');
            script.src = 'https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js';
            script.onload = function () { chartjsLoaded = true; resolve(); };
            script.onerror = function () { reject(new Error('Chart.js konnte nicht geladen werden')); };
            document.head.appendChild(script);
        });
        return chartjsLoadPromise;
    }

    function renderChartjsBlocks(containerEl) {
        var codeBlocks = containerEl.querySelectorAll('pre code.language-chartjs');
        if (codeBlocks.length === 0) return;

        codeBlocks.forEach(function (codeEl) {
            var preEl = codeEl.parentElement;
            var wrapper = document.createElement('div');
            wrapper.className = 'chartjs-container';
            wrapper.innerHTML = '<div class="chart-loading">Chart wird geladen\u2026</div>';
            preEl.parentNode.replaceChild(wrapper, preEl);

            var jsonStr = codeEl.textContent.trim();
            // Extract JSON object even if trailing non-JSON text is present
            var braceStart = jsonStr.indexOf('{');
            if (braceStart > 0) jsonStr = jsonStr.substring(braceStart);
            // Find matching closing brace
            if (braceStart >= 0) {
                var depth = 0;
                var end = -1;
                for (var ci = 0; ci < jsonStr.length; ci++) {
                    if (jsonStr[ci] === '{') depth++;
                    else if (jsonStr[ci] === '}') { depth--; if (depth === 0) { end = ci; break; } }
                }
                if (end > 0 && end < jsonStr.length - 1) jsonStr = jsonStr.substring(0, end + 1);
            }
            var config;
            try {
                config = JSON.parse(jsonStr);
            } catch (e) {
                showError(wrapper, 'Ung\u00fcltiges JSON f\u00fcr Chart');
                return;
            }

            loadChartjs().then(function () {
                wrapper.innerHTML = '';
                var canvas = document.createElement('canvas');
                wrapper.appendChild(canvas);
                try {
                    new Chart(canvas.getContext('2d'), config);
                } catch (e) {
                    showError(wrapper, 'Chart-Fehler: ' + e.message);
                }
            }).catch(function (err) { showError(wrapper, err.message); });
        });
    }

    // ================================================================
    // Public API
    // ================================================================

    return {
        renderTemplateCharts: renderTemplateCharts,
        renderMeteograms: renderMeteograms,
        renderMaps: renderMaps,
        renderChartjsBlocks: renderChartjsBlocks
    };

})();
