/**
 * FoehnDiagram - D3.js chart module for Föhn pressure-differential diagram.
 *
 * Renders a continuous multi-day timeline with three panels:
 *   1. Delta-P area chart (Südföhn positive/red, Nordföhn negative/blue)
 *   2. Crest wind (700 hPa) bar chart
 *   3. Humidity (Nord) line chart
 *
 * Usage:
 *   FoehnDiagram.renderChart(container, tooltipEl, allData, thresholds)
 *     allData = flat array of hourly entries across all days (with .time ISO string)
 */
window.FoehnDiagram = (function () {
    'use strict';

    // Layout: generous gaps so panels never overlap
    // bottom margin includes space for the date labels under day-start ticks
    function isMobile() {
        return typeof window !== 'undefined' && window.innerWidth < 640;
    }
    var MARGIN_DESKTOP = { top: 44, right: 40, bottom: 46, left: 56 };
    // Mobile: bigger top so the in-chart panel title has breathing room;
    // left wide enough for "+10 hPa" tick labels at 9px; right wide enough for legend pill
    var MARGIN_MOBILE  = { top: 38, right: 12, bottom: 42, left: 48 };
    var DAY_NAMES = ['So', 'Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa'];

    // Crest-wind thresholds (from foehn_indicators.py)
    var TH_CREST_CAUTION = 54;  // km/h
    var TH_CREST_DANGER = 180;  // km/h (off-chart, skip drawing)

    // --- Color helpers ---
    function deltaColor(val) {
        if (val == null) return '#64748B';
        if (val > 0) return 'rgba(239, 68, 68, 0.7)';
        if (val < 0) return 'rgba(59, 130, 246, 0.7)';
        return 'rgba(100, 116, 139, 0.3)';
    }

    function windBarColor(speed) {
        if (speed == null) return '#64748B';
        if (speed <= 20) return '#059669';
        if (speed <= 40) return '#D97706';
        if (speed <= 60) return '#EA580C';
        return '#DC2626';
    }

    function levelBg(level) {
        if (level === 'danger') return 'rgba(239, 68, 68, 0.15)';
        if (level === 'caution') return 'rgba(245, 158, 11, 0.15)';
        return 'transparent';
    }

    function levelLabel(level) {
        if (level === 'danger') return 'Gefahr';
        if (level === 'caution') return 'Vorsicht';
        return 'Kein F\u00f6hn';
    }

    function dirArrow(deg) {
        if (deg == null) return '';
        var arrows = ['\u2193', '\u2199', '\u2190', '\u2196', '\u2191', '\u2197', '\u2192', '\u2198'];
        return arrows[Math.round(deg / 45) % 8];
    }

    function formatDate(dt) {
        return DAY_NAMES[dt.getDay()] + ' ' + dt.getDate() + '.' + (dt.getMonth() + 1) + '.';
    }

    // --- Helper: draw a labeled threshold line inside a panel ---
    function drawThreshold(g, innerW, yScale, value, color, label, side) {
        var yPos = yScale(value);
        // Don't draw if out of visible range
        var range = yScale.range();
        if (yPos < Math.min(range[0], range[1]) - 2 || yPos > Math.max(range[0], range[1]) + 2) return;

        g.append('line').attr('x1', 0).attr('x2', innerW)
            .attr('y1', yPos).attr('y2', yPos)
            .attr('stroke', color).attr('stroke-width', 1)
            .attr('stroke-dasharray', '4,3').attr('opacity', 0.6);
        if (label) {
            var textX = side === 'left' ? 4 : innerW - 4;
            var anchor = side === 'left' ? 'start' : 'end';
            g.append('text').attr('x', textX).attr('y', yPos - 4)
                .attr('text-anchor', anchor)
                .attr('font-size', '9px').attr('fill', color).attr('opacity', 0.7)
                .text(label);
        }
    }

    // --- Helper: draw day separators + day labels on a panel group ---
    // On mobile, date labels are only at the bottom x-axis (avoids duplicates).
    function drawDaySeparators(g, panelH, x, dayBoundaries, innerW, mobile) {
        dayBoundaries.forEach(function (db, i) {
            var bx = x(db.dt);
            if (i > 0) {
                g.append('line')
                    .attr('x1', bx).attr('x2', bx)
                    .attr('y1', 0).attr('y2', panelH)
                    .attr('stroke', 'rgba(255,255,255,0.12)')
                    .attr('stroke-width', 1)
                    .attr('stroke-dasharray', '6,3');
            }
            if (mobile) return;  // skip top date labels on mobile
            var nextBx = (i < dayBoundaries.length - 1) ? x(dayBoundaries[i + 1].dt) : innerW;
            var labelX = bx + (nextBx - bx) / 2;
            g.append('text')
                .attr('x', labelX).attr('y', -6)
                .attr('text-anchor', 'middle')
                .attr('font-size', '10px').attr('font-weight', '600')
                .attr('fill', 'rgba(255,255,255,0.35)')
                .text(formatDate(db.dt));
        });
    }

    // --- Helper: draw x-axis at bottom of a panel ---
    // Day-start ticks additionally get a date label (e.g. "Di 8.4.") below the hour.
    function drawXAxis(g, panelH, x, mobile) {
        // Mobile: every 12h (0h/12h only) — avoids label overlap on narrow viewports
        var everyHours = mobile ? 12 : 6;
        var ticks = x.ticks(d3.timeHour.every(everyHours));
        var daysSeen = {};
        var dayStartTickTimes = {};
        ticks.forEach(function (t) {
            var key = t.getFullYear() + '-' + t.getMonth() + '-' + t.getDate();
            if (!daysSeen[key]) {
                daysSeen[key] = true;
                dayStartTickTimes[t.getTime()] = true;
            }
        });

        var axis = d3.axisBottom(x)
            .tickValues(ticks)
            .tickFormat(function (d) { return d.getHours() + 'h'; });

        var axisG = g.append('g').attr('class', 'foehn-axis')
            .attr('transform', 'translate(0,' + panelH + ')')
            .call(axis);

        if (mobile) {
            axisG.selectAll('text').attr('font-size', '9px');
        }

        // Append a date label under the hour label for the first tick of each day.
        axisG.selectAll('.tick').each(function (d) {
            if (!dayStartTickTimes[d.getTime()]) return;
            d3.select(this).append('text')
                .attr('y', mobile ? 18 : 22)
                .attr('dy', '0.71em')
                .attr('text-anchor', 'middle')
                .attr('font-size', mobile ? '9px' : '10px')
                .attr('font-weight', '600')
                .attr('fill', 'rgba(255,255,255,0.75)')
                .text(mobile
                    ? DAY_NAMES[d.getDay()] + ' ' + d.getDate() + '.'
                    : DAY_NAMES[d.getDay()] + ' ' + d.getDate() + '.' + (d.getMonth() + 1) + '.');
        });
    }

    // --- Main render (all days at once) ---
    function renderChart(container, tooltipEl, allData, thresholds) {
        container.innerHTML = '';
        if (!allData || allData.length === 0) {
            container.innerHTML = '<div class="error-state">' + wcT('foehn.no_data') + '</div>';
            return;
        }

        thresholds = thresholds || {};
        var TH_CAUTION = thresholds.delta_p_caution || 4;
        var TH_DANGER = thresholds.delta_p_danger || 8;
        var TH_HUMIDITY = thresholds.humidity_low || 40;

        // Parse times
        allData.forEach(function (d) { d._dt = new Date(d.time); });

        // Dimensions — recompute mobile flag per render so rotation/resize works
        var mobile = isMobile();
        var MARGIN = mobile ? MARGIN_MOBILE : MARGIN_DESKTOP;
        // Mobile gap: must fit hour label (~11px) + day label (~13px) + title (~14px) + padding
        var PANEL_GAP = mobile ? 56 : 64;

        var viewportW = (typeof window !== 'undefined' && window.innerWidth) || 900;
        var panelWidth = container.clientWidth;
        if (!panelWidth || panelWidth < 50) panelWidth = viewportW - (mobile ? 24 : 80);
        var nHours = allData.length;
        // On mobile: strictly fit the viewport (no horizontal scroll).
        // On desktop: enforce min pixel density for readability.
        var chartW = mobile
            ? Math.min(panelWidth, viewportW)
            : Math.max(panelWidth, MARGIN.left + MARGIN.right + nHours * 10);
        var innerW = chartW - MARGIN.left - MARGIN.right;

        // Mobile: more generous panel heights so charts aren't squished
        var P1_H = mobile ? 160 : 200;  // Delta-P
        var P2_H = mobile ? 95  : 120;  // Crest wind
        var P3_H = mobile ? 80  : 100;  // Humidity
        var totalH = MARGIN.top + P1_H + PANEL_GAP + P2_H + PANEL_GAP + P3_H + MARGIN.bottom;

        var svg = d3.select(container)
            .append('svg')
            .attr('width', chartW)
            .attr('height', totalH)
            .attr('viewBox', '0 0 ' + chartW + ' ' + totalH)
            .attr('preserveAspectRatio', 'xMidYMid meet')
            .style('display', 'block')
            .style('max-width', '100%');

        // X scale
        var tMin = allData[0]._dt;
        var tMax = allData[allData.length - 1]._dt;
        var x = d3.scaleTime().domain([tMin, tMax]).range([0, innerW]);

        var barW = Math.max(2, innerW / nHours * 0.75);

        // Day boundaries
        var dayBoundaries = [];
        var prevDateStr = '';
        allData.forEach(function (d) {
            var ds = d.time.substring(0, 10);
            if (ds !== prevDateStr) {
                dayBoundaries.push({ dateStr: ds, dt: d._dt });
                prevDateStr = ds;
            }
        });

        // ================================================================
        // PANEL 1: Delta-P
        // ================================================================
        var p1Top = MARGIN.top;
        var g1 = svg.append('g').attr('transform', 'translate(' + MARGIN.left + ',' + p1Top + ')');

        // Clip panel content
        svg.append('defs').append('clipPath').attr('id', 'clip-p1')
            .append('rect').attr('width', innerW).attr('height', P1_H);
        var g1Clip = g1.append('g').attr('clip-path', 'url(#clip-p1)');

        var dpValues = allData.map(function (d) { return d.delta_p; }).filter(function (v) { return v != null; });
        var dpMax = Math.max(TH_DANGER + 2, d3.max(dpValues.map(Math.abs)) || TH_DANGER + 2);
        var yDp = d3.scaleLinear().domain([-dpMax, dpMax]).range([P1_H, 0]);

        // Background color zones
        [
            { y0: yDp(dpMax), y1: yDp(TH_DANGER), fill: 'rgba(239, 68, 68, 0.06)' },
            { y0: yDp(TH_DANGER), y1: yDp(TH_CAUTION), fill: 'rgba(245, 158, 11, 0.06)' },
            { y0: yDp(TH_CAUTION), y1: yDp(-TH_CAUTION), fill: 'rgba(16, 185, 129, 0.04)' },
            { y0: yDp(-TH_CAUTION), y1: yDp(-TH_DANGER), fill: 'rgba(245, 158, 11, 0.06)' },
            { y0: yDp(-TH_DANGER), y1: yDp(-dpMax), fill: 'rgba(59, 130, 246, 0.06)' },
        ].forEach(function (z) {
            g1Clip.append('rect').attr('x', 0).attr('y', z.y0)
                .attr('width', innerW).attr('height', z.y1 - z.y0).attr('fill', z.fill);
        });

        // Threshold lines (labels hidden on mobile — panel is too narrow; zones convey intent)
        drawThreshold(g1, innerW, yDp, TH_DANGER, '#EF4444', mobile ? null : 'Gefahr +' + TH_DANGER + ' hPa', 'right');
        drawThreshold(g1, innerW, yDp, TH_CAUTION, '#F59E0B', mobile ? null : 'Vorsicht +' + TH_CAUTION + ' hPa', 'right');
        drawThreshold(g1, innerW, yDp, -TH_CAUTION, '#F59E0B', mobile ? null : 'Vorsicht \u2212' + TH_CAUTION + ' hPa', 'right');
        drawThreshold(g1, innerW, yDp, -TH_DANGER, '#EF4444', mobile ? null : 'Gefahr \u2212' + TH_DANGER + ' hPa', 'right');

        // Zero line
        g1.append('line').attr('x1', 0).attr('x2', innerW)
            .attr('y1', yDp(0)).attr('y2', yDp(0))
            .attr('stroke', 'rgba(255,255,255,0.2)').attr('stroke-width', 1);

        // Area positive (Südföhn)
        g1Clip.append('path').datum(allData)
            .attr('d', d3.area()
                .defined(function (d) { return d.delta_p != null; })
                .x(function (d) { return x(d._dt); })
                .y0(yDp(0))
                .y1(function (d) { return d.delta_p > 0 ? yDp(d.delta_p) : yDp(0); })
                .curve(d3.curveMonotoneX))
            .attr('fill', 'rgba(239, 68, 68, 0.25)');

        // Area negative (Nordföhn)
        g1Clip.append('path').datum(allData)
            .attr('d', d3.area()
                .defined(function (d) { return d.delta_p != null; })
                .x(function (d) { return x(d._dt); })
                .y0(yDp(0))
                .y1(function (d) { return d.delta_p < 0 ? yDp(d.delta_p) : yDp(0); })
                .curve(d3.curveMonotoneX))
            .attr('fill', 'rgba(59, 130, 246, 0.25)');

        // Line
        g1Clip.append('path').datum(allData)
            .attr('d', d3.line()
                .defined(function (d) { return d.delta_p != null; })
                .x(function (d) { return x(d._dt); })
                .y(function (d) { return yDp(d.delta_p); })
                .curve(d3.curveMonotoneX))
            .attr('fill', 'none').attr('stroke', '#F1F5F9').attr('stroke-width', 2);

        // Y axis
        var y1Axis = d3.axisLeft(yDp).ticks(mobile ? 4 : 6).tickFormat(function (v) { return v + ' hPa'; });
        var y1AxisG = g1.append('g').attr('class', 'foehn-axis').call(y1Axis);
        if (mobile) y1AxisG.selectAll('text').attr('font-size', '9px');
        drawXAxis(g1, P1_H, x, mobile);
        drawDaySeparators(g1, P1_H, x, dayBoundaries, innerW, mobile);

        // Panel title — mobile: centered above chart, shorter label; desktop: in left margin
        if (mobile) {
            // Colored inline title acts as its own legend: ↑ Süd (red) − ↓ Nord (blue)
            var titleM = g1.append('text').attr('class', 'foehn-axis-label')
                .attr('x', innerW / 2).attr('y', -12)
                .attr('text-anchor', 'middle').attr('font-size', '11px');
            titleM.append('tspan').attr('fill', '#EF4444').attr('font-weight', '700').text('\u2191 S\u00fcd');
            titleM.append('tspan').text(' \u2212 ');
            titleM.append('tspan').attr('fill', '#3B82F6').attr('font-weight', '700').text('\u2193 Nord');
            titleM.append('tspan').text(' (hPa)');
        } else {
            g1.append('text').attr('class', 'foehn-axis-label')
                .attr('x', -MARGIN.left + 8).attr('y', -20)
                .text(wcT('js.foehn.axis_pressure'));
            // Legend (desktop: inside panel, top-left)
            g1.append('text').attr('x', 4).attr('y', yDp(dpMax * 0.9) + 4)
                .attr('font-size', '10px').attr('fill', '#EF4444').attr('opacity', 0.7)
                .text('\u2191 S\u00fcdf\u00f6hn');
            g1.append('text').attr('x', 4).attr('y', yDp(-dpMax * 0.9))
                .attr('font-size', '10px').attr('fill', '#3B82F6').attr('opacity', 0.7)
                .text('\u2193 Nordf\u00f6hn');
        }

        // ================================================================
        // PANEL 2: Crest Wind 700 hPa
        // ================================================================
        var p2Top = p1Top + P1_H + PANEL_GAP;
        var g2 = svg.append('g').attr('transform', 'translate(' + MARGIN.left + ',' + p2Top + ')');

        var cwValues = allData.map(function (d) { return d.crest_wind_kmh; }).filter(function (v) { return v != null; });
        var cwMax = Math.max(80, d3.max(cwValues) || 80);
        var yCw = d3.scaleLinear().domain([0, cwMax]).range([P2_H, 0]);

        // Grid lines
        yCw.ticks(4).forEach(function (t) {
            g2.append('line').attr('x1', 0).attr('x2', innerW)
                .attr('y1', yCw(t)).attr('y2', yCw(t))
                .attr('stroke', 'rgba(255,255,255,0.05)').attr('stroke-width', 0.5);
        });

        // Crest wind threshold
        drawThreshold(g2, innerW, yCw, TH_CREST_CAUTION, '#F59E0B', mobile ? null : 'Vorsicht ' + TH_CREST_CAUTION + ' km/h', 'right');

        // Bars
        allData.filter(function (d) { return d.crest_wind_kmh != null; }).forEach(function (d) {
            g2.append('rect')
                .attr('x', x(d._dt) - barW / 2)
                .attr('y', yCw(d.crest_wind_kmh))
                .attr('width', barW)
                .attr('height', P2_H - yCw(d.crest_wind_kmh))
                .attr('fill', windBarColor(d.crest_wind_kmh))
                .attr('rx', 1).attr('opacity', 0.8);
        });

        var y2Axis = d3.axisLeft(yCw).ticks(mobile ? 3 : 4).tickFormat(function (v) { return v + ' km/h'; });
        var y2AxisG = g2.append('g').attr('class', 'foehn-axis').call(y2Axis);
        if (mobile) y2AxisG.selectAll('text').attr('font-size', '9px');
        drawXAxis(g2, P2_H, x, mobile);
        drawDaySeparators(g2, P2_H, x, dayBoundaries, innerW, mobile);

        if (mobile) {
            g2.append('text').attr('class', 'foehn-axis-label')
                .attr('x', innerW / 2).attr('y', -12)
                .attr('text-anchor', 'middle').attr('font-size', '11px')
                .text('Kammwind 700 hPa (km/h)');
        } else {
            g2.append('text').attr('class', 'foehn-axis-label')
                .attr('x', -MARGIN.left + 8).attr('y', -20)
                .text('Kammwind 700 hPa (\u2248 3000m)');
        }

        // ================================================================
        // PANEL 3: Humidity Nord
        // ================================================================
        var p3Top = p2Top + P2_H + PANEL_GAP;
        var g3 = svg.append('g').attr('transform', 'translate(' + MARGIN.left + ',' + p3Top + ')');

        var yRh = d3.scaleLinear().domain([0, 100]).range([P3_H, 0]);

        // Dry zone background
        g3.append('rect').attr('x', 0).attr('y', yRh(TH_HUMIDITY))
            .attr('width', innerW).attr('height', P3_H - yRh(TH_HUMIDITY))
            .attr('fill', 'rgba(245, 158, 11, 0.06)');

        // Threshold with label
        drawThreshold(g3, innerW, yRh, TH_HUMIDITY, '#F59E0B', mobile ? null : 'F\u00f6hn trocken <' + TH_HUMIDITY + '%', 'right');

        // Line
        g3.append('path').datum(allData)
            .attr('d', d3.line()
                .defined(function (d) { return d.humidity_nord != null; })
                .x(function (d) { return x(d._dt); })
                .y(function (d) { return yRh(d.humidity_nord); })
                .curve(d3.curveMonotoneX))
            .attr('fill', 'none').attr('stroke', '#38BDF8').attr('stroke-width', 2);

        var y3Axis = d3.axisLeft(yRh).ticks(mobile ? 3 : 4).tickFormat(function (v) { return v + '%'; });
        var y3AxisG = g3.append('g').attr('class', 'foehn-axis').call(y3Axis);
        if (mobile) y3AxisG.selectAll('text').attr('font-size', '9px');
        drawXAxis(g3, P3_H, x, mobile);
        drawDaySeparators(g3, P3_H, x, dayBoundaries, innerW, mobile);

        if (mobile) {
            g3.append('text').attr('class', 'foehn-axis-label')
                .attr('x', innerW / 2).attr('y', -12)
                .attr('text-anchor', 'middle').attr('font-size', '11px')
                .text('Luftfeuchtigkeit Z\u00fcrich (%)');
        } else {
            g3.append('text').attr('class', 'foehn-axis-label')
                .attr('x', -MARGIN.left + 8).attr('y', -20)
                .text('Luftfeuchtigkeit Z\u00fcrich');
        }

        // ================================================================
        // CROSSHAIR + TOOLTIP
        // ================================================================
        var crossV = svg.append('line')
            .attr('y1', p1Top).attr('y2', p3Top + P3_H)
            .attr('stroke', 'rgba(129, 140, 248, 0.3)')
            .attr('stroke-width', 1).attr('stroke-dasharray', '3,3')
            .style('opacity', 0);

        svg.append('rect')
            .attr('x', MARGIN.left).attr('y', p1Top)
            .attr('width', innerW).attr('height', p3Top + P3_H - p1Top)
            .attr('fill', 'transparent')
            .on('mousemove', function (event) {
                var coords = d3.pointer(event);
                var mx = coords[0] - MARGIN.left;
                if (mx < 0 || mx > innerW) return;

                var tHover = x.invert(mx);
                var nearestIdx = 0;
                var minDist = Infinity;
                allData.forEach(function (d, i) {
                    var dist = Math.abs(d._dt - tHover);
                    if (dist < minDist) { minDist = dist; nearestIdx = i; }
                });

                var d = allData[nearestIdx];
                var cx = MARGIN.left + x(d._dt);
                crossV.attr('x1', cx).attr('x2', cx).style('opacity', 1);

                var timeStr = formatDate(d._dt) + ' ' + d.hour + ':00';
                var html = '<div class="tooltip-title">' + timeStr + '</div>';
                if (d.delta_p != null) {
                    var dpLabel = d.delta_p > 0 ? 'S\u00fcdf\u00f6hn' : (d.delta_p < 0 ? 'Nordf\u00f6hn' : 'Neutral');
                    html += '<div class="tooltip-row"><span class="tooltip-label">\u0394P</span><span class="tooltip-value" style="color:' + deltaColor(d.delta_p) + '">' + d.delta_p.toFixed(1) + ' hPa (' + dpLabel + ')</span></div>';
                }
                html += '<div class="tooltip-row"><span class="tooltip-label">Stufe</span><span class="tooltip-value" style="background:' + levelBg(d.level) + ';padding:1px 6px;border-radius:4px">' + levelLabel(d.level) + '</span></div>';
                if (d.crest_wind_kmh != null) {
                    html += '<div class="tooltip-row"><span class="tooltip-label">Kammwind</span><span class="tooltip-value" style="color:' + windBarColor(d.crest_wind_kmh) + '">' + Math.round(d.crest_wind_kmh) + ' km/h</span></div>';
                }
                if (d.crest_dir_deg != null) {
                    html += '<div class="tooltip-row"><span class="tooltip-label">Richtung</span><span class="tooltip-value">' + Math.round(d.crest_dir_deg) + '\u00B0 ' + dirArrow(d.crest_dir_deg) + '</span></div>';
                }
                if (d.humidity_nord != null) {
                    var rhColor = d.humidity_nord < TH_HUMIDITY ? '#F59E0B' : '#38BDF8';
                    html += '<div class="tooltip-row"><span class="tooltip-label">Feuchte</span><span class="tooltip-value" style="color:' + rhColor + '">' + Math.round(d.humidity_nord) + '%</span></div>';
                }

                tooltipEl.innerHTML = html;
                tooltipEl.classList.add('visible');
                var tx = event.clientX + 16;
                var ty = event.clientY - 10;
                if (tx + 220 > window.innerWidth) tx = event.clientX - 220;
                if (ty + 200 > window.innerHeight) ty = event.clientY - 200;
                tooltipEl.style.left = tx + 'px';
                tooltipEl.style.top = ty + 'px';
            })
            .on('mouseleave', function () {
                crossV.style('opacity', 0);
                tooltipEl.classList.remove('visible');
            });

    }

    return { renderChart: renderChart };
})();
