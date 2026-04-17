/**
 * WindTimeline — D3-basierter Zeitverlauf-Chart: Wind W(z) + Turbulenzrisiko T(z).
 *
 * Zeigt für eine wählbare Höhe den Tagesverlauf von:
 *   - Blaue Linie: W(z) — mittlerer Modellwind
 *   - Farbiges Band: von W(z) bis T(z) — Turbulenzexzess
 *   - Gestrichelte rote Linie: T(z) — obere Grenze
 *   - Horizontale Referenzlinie: 30 km/h Vorsicht-Schwelle
 *
 * Usage:
 *   WindTimeline.render(container, altWindDay, options)
 *   options: { elevation_m, onHoverCallback }
 */
window.WindTimeline = (function () {
    'use strict';

    // Color scale for absolute T(z) value (same as meteogram turbulence strip)
    function turbulenceColor(tz) {
        if (tz <= 10) return '#059669';
        if (tz <= 20) return '#10B981';
        if (tz <= 25) return '#D97706';
        if (tz <= 30) return '#EA580C';
        return '#DC2626';
    }

    function windColor(speed) {
        if (speed <= 10) return '#059669';
        if (speed <= 20) return '#10B981';
        if (speed <= 25) return '#D97706';
        if (speed <= 30) return '#EA580C';
        return '#DC2626';
    }

    // Direction to text
    function dirText(deg) {
        var dirs = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'];
        return dirs[Math.round(deg / 45) % 8];
    }

    // Height buttons in meters
    var HEIGHTS = [1000, 1500, 2000, 2500, 3000, 3500];

    /**
     * Build height selector buttons.
     * @param {HTMLElement} container - target DOM element
     * @param {number} defaultAlt - default selected altitude
     * @param {function} onSelect - callback(altitudeM)
     */
    function buildHeightSelector(container, defaultAlt, onSelect) {
        container.innerHTML = '';
        var wrapper = document.createElement('div');
        wrapper.className = 'wt-height-selector';

        HEIGHTS.forEach(function (alt) {
            var btn = document.createElement('button');
            btn.className = 'wt-height-btn' + (alt === defaultAlt ? ' active' : '');
            btn.textContent = (alt / 1000).toFixed(1) + 'k';
            btn.dataset.alt = alt;
            btn.addEventListener('click', function () {
                wrapper.querySelectorAll('.wt-height-btn').forEach(function (b) {
                    b.classList.remove('active');
                });
                btn.classList.add('active');
                onSelect(alt);
            });
            wrapper.appendChild(btn);
        });

        container.appendChild(wrapper);
    }

    /**
     * Extract time series for a given altitude from altWindDay profiles.
     * altWindDay = [{hour, profiles: [{altitude, wind_speed, wind_gusts, turbulence_risk, turbulence_excess, wind_direction, ...}]}]
     */
    function extractTimeSeries(altWindDay, targetAlt) {
        if (!altWindDay || !altWindDay.length) return [];

        var series = [];
        altWindDay.forEach(function (hourEntry) {
            var hour = hourEntry.hour;
            var levels = (hourEntry.profiles || []).slice().sort(function (a, b) {
                return a.altitude - b.altitude;
            });
            if (levels.length < 2) return;

            // Interpolate to target altitude
            var below = null, above = null;
            for (var i = 0; i < levels.length; i++) {
                if (levels[i].altitude <= targetAlt) below = levels[i];
                if (levels[i].altitude >= targetAlt && !above) above = levels[i];
            }

            var ws = 0, tr = 0, te = 0, wd = 0;
            if (below && above && below !== above) {
                var frac = (targetAlt - below.altitude) / (above.altitude - below.altitude);
                ws = below.wind_speed + frac * (above.wind_speed - below.wind_speed);
                var trB = below.turbulence_risk != null ? below.turbulence_risk : (below.wind_gusts || below.wind_speed);
                var trA = above.turbulence_risk != null ? above.turbulence_risk : (above.wind_gusts || above.wind_speed);
                tr = trB + frac * (trA - trB);
                var teB = below.turbulence_excess != null ? below.turbulence_excess : 0;
                var teA = above.turbulence_excess != null ? above.turbulence_excess : 0;
                te = teB + frac * (teA - teB);
                wd = below.wind_direction;
            } else if (below) {
                ws = below.wind_speed;
                tr = below.turbulence_risk != null ? below.turbulence_risk : (below.wind_gusts || ws);
                te = below.turbulence_excess != null ? below.turbulence_excess : 0;
                wd = below.wind_direction;
            } else if (above) {
                ws = above.wind_speed;
                tr = above.turbulence_risk != null ? above.turbulence_risk : (above.wind_gusts || ws);
                te = above.turbulence_excess != null ? above.turbulence_excess : 0;
                wd = above.wind_direction;
            }

            series.push({
                hour: hour,
                wind_speed: ws,
                turbulence_risk: Math.max(tr, ws),
                turbulence_excess: Math.max(te, 0),
                wind_direction: wd
            });
        });

        return series.sort(function (a, b) { return a.hour - b.hour; });
    }

    /**
     * Render the wind timeline chart.
     * @param {HTMLElement} chartEl - SVG/div container
     * @param {HTMLElement} tooltipEl - tooltip element
     * @param {Array} altWindDay - altitude wind data for one day
     * @param {Object} opts - {elevation_m, dateStr}
     */
    function render(chartEl, tooltipEl, altWindDay, opts) {
        opts = opts || {};
        var elevation = opts.elevation_m || 1000;

        // Default height: elevation + 1000m, snapped to nearest HEIGHTS value
        var defaultAlt = HEIGHTS.reduce(function (best, h) {
            return Math.abs(h - (elevation + 1000)) < Math.abs(best - (elevation + 1000)) ? h : best;
        }, HEIGHTS[0]);

        chartEl.innerHTML = '';

        // Height selector
        var selectorDiv = document.createElement('div');
        chartEl.appendChild(selectorDiv);

        // Chart area
        var chartDiv = document.createElement('div');
        chartDiv.className = 'wt-chart-area';
        chartEl.appendChild(chartDiv);

        function renderChart(targetAlt) {
            chartDiv.innerHTML = '';
            var series = extractTimeSeries(altWindDay, targetAlt);
            if (!series.length) {
                chartDiv.innerHTML = '<p style="color:#64748B;text-align:center;padding:40px">Keine Daten verfügbar</p>';
                return;
            }

            var margin = { top: 20, right: 20, bottom: 35, left: 45 };
            var width = chartDiv.clientWidth || 500;
            var height = 240;
            var w = width - margin.left - margin.right;
            var h = height - margin.top - margin.bottom;

            var svg = d3.select(chartDiv).append('svg')
                .attr('width', width)
                .attr('height', height);

            var g = svg.append('g')
                .attr('transform', 'translate(' + margin.left + ',' + margin.top + ')');

            // Scales
            var xExtent = d3.extent(series, function (d) { return d.hour; });
            var x = d3.scaleLinear()
                .domain([Math.max(xExtent[0] - 0.5, 0), Math.min(xExtent[1] + 0.5, 23)])
                .range([0, w]);

            var yMax = Math.max(
                40,
                d3.max(series, function (d) { return d.turbulence_risk; }) * 1.15
            );
            var y = d3.scaleLinear()
                .domain([0, yMax])
                .range([h, 0]);

            // Grid lines
            g.append('g')
                .attr('class', 'wt-grid')
                .selectAll('line')
                .data(y.ticks(5))
                .enter().append('line')
                .attr('x1', 0).attr('x2', w)
                .attr('y1', function (d) { return y(d); })
                .attr('y2', function (d) { return y(d); })
                .attr('stroke', '#E5E7EB')
                .attr('stroke-dasharray', '2,2');

            // 30 km/h reference line
            if (yMax >= 30) {
                g.append('line')
                    .attr('x1', 0).attr('x2', w)
                    .attr('y1', y(30)).attr('y2', y(30))
                    .attr('stroke', '#EF4444')
                    .attr('stroke-width', 1)
                    .attr('stroke-dasharray', '6,3')
                    .attr('opacity', 0.5);
                g.append('text')
                    .attr('x', w - 4).attr('y', y(30) - 4)
                    .attr('text-anchor', 'end')
                    .attr('font-size', '9px')
                    .attr('fill', '#EF4444')
                    .attr('opacity', 0.6)
                    .text('30 km/h');
            }

            // Area: turbulence band (W(z) to T(z))
            var area = d3.area()
                .x(function (d) { return x(d.hour); })
                .y0(function (d) { return y(d.wind_speed); })
                .y1(function (d) { return y(d.turbulence_risk); })
                .curve(d3.curveMonotoneX);

            // Color segments for the band
            var defs = svg.append('defs');
            var gradId = 'turb-grad-' + Math.random().toString(36).substr(2, 6);
            var linearGrad = defs.append('linearGradient')
                .attr('id', gradId)
                .attr('x1', '0%').attr('x2', '100%')
                .attr('y1', '0%').attr('y2', '0%');

            series.forEach(function (d, i) {
                var pct = (i / Math.max(1, series.length - 1)) * 100;
                linearGrad.append('stop')
                    .attr('offset', pct + '%')
                    .attr('stop-color', turbulenceColor(d.turbulence_risk))
                    .attr('stop-opacity', 0.35);
            });

            g.append('path')
                .datum(series)
                .attr('d', area)
                .attr('fill', 'url(#' + gradId + ')');

            // W(z) line (blue)
            var windLine = d3.line()
                .x(function (d) { return x(d.hour); })
                .y(function (d) { return y(d.wind_speed); })
                .curve(d3.curveMonotoneX);

            g.append('path')
                .datum(series)
                .attr('d', windLine)
                .attr('fill', 'none')
                .attr('stroke', '#3B82F6')
                .attr('stroke-width', 2.5);

            // T(z) line (dashed red)
            var turbLine = d3.line()
                .x(function (d) { return x(d.hour); })
                .y(function (d) { return y(d.turbulence_risk); })
                .curve(d3.curveMonotoneX);

            g.append('path')
                .datum(series)
                .attr('d', turbLine)
                .attr('fill', 'none')
                .attr('stroke', '#EF4444')
                .attr('stroke-width', 1.5)
                .attr('stroke-dasharray', '5,3');

            // Data points on W(z)
            g.selectAll('.wt-dot-wind')
                .data(series)
                .enter().append('circle')
                .attr('cx', function (d) { return x(d.hour); })
                .attr('cy', function (d) { return y(d.wind_speed); })
                .attr('r', 3)
                .attr('fill', '#3B82F6')
                .attr('stroke', '#fff')
                .attr('stroke-width', 1);

            // X axis
            g.append('g')
                .attr('transform', 'translate(0,' + h + ')')
                .call(d3.axisBottom(x)
                    .tickValues(series.map(function (d) { return d.hour; }))
                    .tickFormat(function (d) { return d + 'h'; })
                )
                .selectAll('text')
                .attr('font-size', '10px');

            // Y axis
            g.append('g')
                .call(d3.axisLeft(y).ticks(5).tickFormat(function (d) { return d + ''; }))
                .selectAll('text')
                .attr('font-size', '10px');

            // Y axis label
            g.append('text')
                .attr('transform', 'rotate(-90)')
                .attr('x', -h / 2).attr('y', -35)
                .attr('text-anchor', 'middle')
                .attr('font-size', '10px')
                .attr('fill', '#64748B')
                .text('km/h');

            // Legend
            var legendY = -8;
            var leg = g.append('g').attr('transform', 'translate(0,' + legendY + ')');
            leg.append('line').attr('x1', 0).attr('x2', 18).attr('y1', 0).attr('y2', 0)
                .attr('stroke', '#3B82F6').attr('stroke-width', 2.5);
            leg.append('text').attr('x', 22).attr('y', 3).attr('font-size', '10px').attr('fill', '#3B82F6')
                .text('Wind W(z)');
            leg.append('line').attr('x1', 95).attr('x2', 113).attr('y1', 0).attr('y2', 0)
                .attr('stroke', '#EF4444').attr('stroke-width', 1.5).attr('stroke-dasharray', '5,3');
            leg.append('text').attr('x', 117).attr('y', 3).attr('font-size', '10px').attr('fill', '#EF4444')
                .text('Turbulenz T(z)');
            leg.append('rect').attr('x', 210).attr('y', -6).attr('width', 14).attr('height', 12)
                .attr('fill', '#EA580C').attr('opacity', 0.3).attr('rx', 2);
            leg.append('text').attr('x', 228).attr('y', 3).attr('font-size', '10px').attr('fill', '#64748B')
                .text('Exzess');

            // Altitude label
            g.append('text')
                .attr('x', w).attr('y', legendY + 3)
                .attr('text-anchor', 'end')
                .attr('font-size', '11px')
                .attr('font-weight', '600')
                .attr('fill', '#334155')
                .text(targetAlt + 'm MSL');

            // Hover overlay
            var overlay = g.append('rect')
                .attr('width', w).attr('height', h)
                .attr('fill', 'transparent')
                .style('cursor', 'crosshair');

            var hoverLine = g.append('line')
                .attr('y1', 0).attr('y2', h)
                .attr('stroke', '#94A3B8')
                .attr('stroke-width', 1)
                .attr('stroke-dasharray', '3,2')
                .style('display', 'none');

            function showWtTooltip(mx, clientX, clientY) {
                var hoverHour = x.invert(mx);
                var nearest = null, minDist = Infinity;
                series.forEach(function (d) {
                    var dist = Math.abs(d.hour - hoverHour);
                    if (dist < minDist) { minDist = dist; nearest = d; }
                });
                if (!nearest || !tooltipEl) return;

                hoverLine.attr('x1', x(nearest.hour)).attr('x2', x(nearest.hour))
                    .style('display', null);

                var html = '<div class="tooltip-title">' + nearest.hour + ':00 — ' + targetAlt + 'm</div>';
                html += '<div class="tooltip-row"><span class="tooltip-label">Wind</span><span class="tooltip-value" style="color:' + windColor(nearest.wind_speed) + '">' + Math.round(nearest.wind_speed) + ' km/h</span></div>';
                html += '<div class="tooltip-row"><span class="tooltip-label">Turbulenzrisiko</span><span class="tooltip-value" style="color:' + turbulenceColor(nearest.turbulence_risk) + '">' + Math.round(nearest.turbulence_risk) + ' km/h</span></div>';
                if (nearest.turbulence_excess > 1) {
                    html += '<div class="tooltip-row"><span class="tooltip-label">Exzess</span><span class="tooltip-value" style="color:' + turbulenceColor(nearest.turbulence_risk) + '">+' + Math.round(nearest.turbulence_excess) + ' km/h</span></div>';
                }
                html += '<div class="tooltip-row"><span class="tooltip-label">Richtung</span><span class="tooltip-value">' + Math.round(nearest.wind_direction) + '\u00B0 (' + dirText(nearest.wind_direction) + ')</span></div>';

                tooltipEl.innerHTML = html;
                tooltipEl.style.display = 'block';

                var rect = chartDiv.getBoundingClientRect();
                var px = clientX - rect.left;
                var py = clientY - rect.top;
                tooltipEl.style.left = Math.min(px + 15, width - 180) + 'px';
                tooltipEl.style.top = (py - 10) + 'px';
            }

            function hideWtTooltip() {
                hoverLine.style('display', 'none');
                if (tooltipEl) tooltipEl.style.display = 'none';
            }

            overlay.on('mousemove', function (event) {
                var coords = d3.pointer(event);
                showWtTooltip(coords[0], event.clientX, event.clientY);
            });

            overlay.on('mouseleave', hideWtTooltip);

            // Touch support
            var wtTouchActive = false;
            overlay.node().addEventListener('touchstart', function (e) {
                e.preventDefault();
                var touch = e.touches[0];
                var coords = d3.pointer(touch, overlay.node());
                showWtTooltip(coords[0], touch.clientX, touch.clientY);
                wtTouchActive = true;
            }, { passive: false });
            overlay.node().addEventListener('touchmove', function (e) {
                if (!wtTouchActive) return;
                var touch = e.touches[0];
                var coords = d3.pointer(touch, overlay.node());
                showWtTooltip(coords[0], touch.clientX, touch.clientY);
            }, { passive: true });
            document.addEventListener('touchstart', function (e) {
                if (wtTouchActive && !overlay.node().contains(e.target)) {
                    hideWtTooltip();
                    wtTouchActive = false;
                }
            }, { passive: true });
        }

        buildHeightSelector(selectorDiv, defaultAlt, renderChart);
        renderChart(defaultAlt);
    }

    return {
        render: render,
        extractTimeSeries: extractTimeSeries
    };
})();
