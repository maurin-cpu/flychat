/**
 * Meteogram - Shared chart rendering module for wind/thermik/cloud visualisation.
 *
 * Usage:
 *   Meteogram.buildTabs(container, dates, onSelectCallback)
 *   Meteogram.renderChart(chartContainer, tooltipEl, weatherDay, altWindDay, options)
 */
window.Meteogram = (function () {
    'use strict';

    // ===== COLOR SCALES =====
    function windColor(speed) {
        if (speed <= 10) return '#059669';
        if (speed <= 20) return '#10B981';
        if (speed <= 25) return '#D97706';
        if (speed <= 30) return '#EA580C';
        return '#DC2626';
    }

    function windBgColor(speed) {
        return windColor(speed) + '14';
    }

    function precipColor(mm) {
        if (mm <= 0) return 'transparent';
        if (mm < 1) return '#93C5FD';
        if (mm < 3) return '#3B82F6';
        return '#1D4ED8';
    }

    // xc-therm color scale: climb rate (m/s) -> background color
    function thermClimbColor(rate) {
        if (rate <= 0) return 'transparent';
        if (rate <= 0.25) return '#FEFCE8';
        if (rate <= 0.75) return '#FEF08A';
        if (rate <= 1.25) return '#FDE047';
        if (rate <= 1.75) return '#BEF264';
        if (rate <= 2.25) return '#86EFAC';
        return '#67E8F9';
    }

    // Parabolic thermal profile: local climb rate at a given altitude
    function thermalRateAtAltitude(climbRate, maxHeight, elevation, altitude) {
        if (altitude < elevation || altitude >= maxHeight || climbRate <= 0) return 0;
        var columnH = maxHeight - elevation;
        if (columnH <= 0) return 0;
        var frac = (altitude - elevation) / columnH; // 0 at ground, 1 at top
        // Parabolic profile peaking at ~50% of column height
        var profile = 4 * frac * (1 - frac); // max=1 at frac=0.5
        // At ground (frac=0): ~30% of peak
        var localRate = climbRate * (0.3 + 0.7 * profile);
        // Round to nearest 0.5
        return Math.round(localRate * 2) / 2;
    }

    // ===== ARROW PATH =====
    function arrowPath(speed) {
        const s = Math.max(0.4, Math.min(1, speed / 30));
        const len = 6 + s * 10;
        const headW = 2.5 + s * 2;
        const headL = 3 + s * 2;
        const shaft = 1 + s * 1.2;
        return `M 0 ${len / 2}
            L 0 ${-len / 2 + headL}
            L ${-headW} ${-len / 2 + headL}
            L 0 ${-len / 2}
            L ${headW} ${-len / 2 + headL}
            L 0 ${-len / 2 + headL} Z
            M ${-shaft / 2} ${-len / 2 + headL}
            L ${-shaft / 2} ${len / 2}
            L ${shaft / 2} ${len / 2}
            L ${shaft / 2} ${-len / 2 + headL} Z`;
    }

    // ===== LAYOUT CONSTANTS =====
    const MARGIN = { top: 12, right: 24, bottom: 0, left: 96 };
    const CELL_H = 36;
    const GROUND_ROWS = 4;
    const GROUND_H = GROUND_ROWS * 24;
    const TIME_LABEL_H = 28;

    // ===== TABS =====
    function buildTabs(container, dates, onSelect) {
        container.innerHTML = '';
        const dayNames = ['So', 'Mo', 'Di', 'Mi', 'Do', 'Fr', 'Sa'];
        dates.forEach(function (d, idx) {
            var dt = new Date(d + 'T00:00');
            var label = dayNames[dt.getDay()] + ' ' + dt.getDate() + '.' + (dt.getMonth() + 1) + '.';
            var btn = document.createElement('button');
            btn.className = 'tab-btn' + (idx === 0 ? ' active' : '');
            btn.textContent = label;
            btn.onclick = function () {
                container.querySelectorAll('.tab-btn').forEach(function (b) { b.classList.remove('active'); });
                btn.classList.add('active');
                onSelect(d);
            };
            container.appendChild(btn);
        });
    }

    // ===== RENDER CHART =====
    function renderChart(container, tooltipEl, wxDay, altDay, options) {
        container.innerHTML = '';
        options = options || {};

        if (!altDay || !altDay.profiles || altDay.profiles.length === 0) {
            container.innerHTML = '<div class="error-state">Keine Daten fuer diesen Tag.</div>';
            return;
        }

        var profiles = altDay.profiles;
        var times = profiles.map(function (p) { return p.time; });
        var nCols = times.length;

        // Fixed altitude grid 0-4000m in 250m steps
        var STEP = 250;
        var altitudes = [];
        for (var a = 0; a <= 4000; a += STEP) altitudes.push(a);
        var nRows = altitudes.length;

        // Interpolated grid
        var grid = [];
        for (var r = 0; r < nRows; r++) grid[r] = new Array(nCols).fill(null);

        profiles.forEach(function (p, ci) {
            var levels = p.levels.slice().sort(function (a, b) { return a.altitude - b.altitude; });
            if (levels.length < 2) return;

            altitudes.forEach(function (targetAlt, ri) {
                if (targetAlt < levels[0].altitude - STEP || targetAlt > levels[levels.length - 1].altitude + STEP) return;
                var below = null, above = null;
                for (var i = 0; i < levels.length; i++) {
                    if (levels[i].altitude <= targetAlt) below = levels[i];
                    if (levels[i].altitude >= targetAlt && !above) above = levels[i];
                }
                if (below && above && below !== above) {
                    var frac = (targetAlt - below.altitude) / (above.altitude - below.altitude);
                    grid[ri][ci] = {
                        altitude: targetAlt,
                        wind_speed: below.wind_speed + frac * (above.wind_speed - below.wind_speed),
                        wind_direction: below.wind_direction,
                        temperature: below.temperature + frac * (above.temperature - below.temperature),
                        pressure: below.pressure
                    };
                } else if (below) {
                    grid[ri][ci] = Object.assign({}, below, { altitude: targetAlt });
                } else if (above) {
                    grid[ri][ci] = Object.assign({}, above, { altitude: targetAlt });
                }
            });
        });

        // Weather lookup by time
        var wxByTime = {};
        if (wxDay) {
            ['wind', 'precipitation', 'thermik', 'cloudbase'].forEach(function (key) {
                (wxDay[key] || []).forEach(function (item) {
                    var t = item.time;
                    if (!wxByTime[t]) wxByTime[t] = {};
                    wxByTime[t][key] = item;
                });
            });
        }

        // Dimensions
        var panelWidth = container.clientWidth || 800;
        var minChartW = MARGIN.left + nCols * 40 + MARGIN.right;
        var chartW = Math.max(panelWidth, minChartW);
        var CELL_W = (chartW - MARGIN.left - MARGIN.right) / nCols;
        var chartH = MARGIN.top + nRows * CELL_H + GROUND_H + TIME_LABEL_H + 8;

        var svg = d3.select(container)
            .append('svg')
            .attr('width', chartW)
            .attr('height', chartH)
            .style('display', 'block');

        var chartG = svg.append('g')
            .attr('transform', 'translate(' + MARGIN.left + ', ' + MARGIN.top + ')');

        function rowY(ri) { return (nRows - 1 - ri) * CELL_H; }
        var gridBottom = nRows * CELL_H;
        var elevation = (options && options.elevation) || 0;

        // Helper for altitude to Y coordinate (smooth, not grid-aligned)
        function altToY(alt) {
            var topAlt = altitudes[altitudes.length - 1];
            return (1 - alt / topAlt) * gridBottom;
        }

        // Track cells that have thermik numbers (key: "ri,ci")
        var thermikCells = {};

        // ===== THERMIK BACKGROUND (xc-therm style: colored cells with climb rate numbers) =====
        times.forEach(function (t, ci) {
            var wx = wxByTime[t];
            if (!wx || !wx.thermik) return;
            var climb = wx.thermik.climb_rate || 0;
            if (climb <= 0) return;
            var maxAlt = wx.thermik.max_height || (altitudes[altitudes.length - 1] + 200);

            for (var ri = 0; ri < nRows; ri++) {
                var alt = altitudes[ri];
                var localRate = thermalRateAtAltitude(climb, maxAlt, elevation, alt);
                if (localRate <= 0) continue;

                var bgColor = thermClimbColor(localRate);
                chartG.append('rect')
                    .attr('x', ci * CELL_W + 1).attr('y', rowY(ri) + 1)
                    .attr('width', CELL_W - 2).attr('height', CELL_H - 2)
                    .attr('fill', bgColor).attr('rx', 3).attr('opacity', 0.8);

                chartG.append('text').attr('class', 'therm-value')
                    .attr('x', ci * CELL_W + CELL_W / 2)
                    .attr('y', rowY(ri) + CELL_H - 4)
                    .text(localRate.toFixed(1));

                thermikCells[ri + ',' + ci] = localRate;
            }
        });

        // ===== CLOUD COVER OVERLAY =====
        times.forEach(function (t, ci) {
            var wx = wxByTime[t];
            if (!wx || !wx.cloudbase) return;
            var cover = wx.cloudbase.cover;
            var cloudBase = wx.cloudbase.height;
            if (cover == null || cover < 20 || cloudBase == null) return;

            var startRow = altitudes.findIndex(function (a) { return a >= cloudBase; });
            if (startRow < 0) return;

            for (var ri = startRow; ri < nRows; ri++) {
                chartG.append('rect')
                    .attr('x', ci * CELL_W).attr('y', rowY(ri))
                    .attr('width', CELL_W).attr('height', CELL_H)
                    .attr('fill', 'rgba(156,163,175,' + (cover / 100 * 0.12) + ')');
            }
        });

        // ===== GRID LINES =====
        for (var ri2 = 0; ri2 <= nRows; ri2++) {
            chartG.append('line').attr('class', 'grid-line')
                .attr('x1', 0).attr('x2', nCols * CELL_W)
                .attr('y1', ri2 * CELL_H).attr('y2', ri2 * CELL_H);
        }
        for (var ci2 = 0; ci2 <= nCols; ci2++) {
            chartG.append('line').attr('class', 'grid-line')
                .attr('x1', ci2 * CELL_W).attr('x2', ci2 * CELL_W)
                .attr('y1', 0).attr('y2', gridBottom + GROUND_H);
        }

        // ===== LAUNCH SITE ELEVATION LINE =====
        if (elevation > 0) {
            var elevY = altToY(elevation);
            // Background shadow for the line
            chartG.append('line')
                .attr('x1', 0).attr('x2', nCols * CELL_W)
                .attr('y1', elevY).attr('y2', elevY)
                .attr('stroke', 'rgba(0,0,0,0.4)')
                .attr('stroke-width', 4)
                .attr('stroke-linecap', 'round');

            // Main indicator line
            chartG.append('line')
                .attr('x1', 0).attr('x2', nCols * CELL_W)
                .attr('y1', elevY).attr('y2', elevY)
                .attr('stroke', '#F97316') // Orange-500
                .attr('stroke-width', 2)
                .attr('stroke-dasharray', '6,4')
                .attr('stroke-linecap', 'round');

            // Label
            chartG.append('text')
                .attr('x', 4).attr('y', elevY - 4)
                .attr('fill', '#F97316')
                .attr('font-size', '10px')
                .attr('font-weight', 'bold')
                .text('STARTPLATZ (' + Math.round(elevation) + 'm)');
        }

        // ===== ALTITUDE LABELS =====
        altitudes.forEach(function (alt, ri) {
            if (alt % 500 !== 0) return;
            var displayAlt = alt >= 1000
                ? (alt / 1000).toFixed(alt % 1000 === 0 ? 0 : 1) + 'k'
                : alt.toString();
            chartG.append('text').attr('class', 'axis-label')
                .attr('x', -8).attr('y', rowY(ri) + CELL_H / 2)
                .attr('text-anchor', 'end').attr('dominant-baseline', 'central')
                .text(displayAlt + 'm');
        });

        // ===== TIME LABELS =====
        times.forEach(function (t, ci) {
            var dt = new Date(t);
            chartG.append('text').attr('class', 'time-label')
                .attr('x', ci * CELL_W + CELL_W / 2)
                .attr('y', gridBottom + GROUND_H + TIME_LABEL_H)
                .attr('text-anchor', 'middle')
                .text(dt.getHours() + 'h');
        });

        // ===== WIND ARROWS + VALUES =====
        var allCells = [];
        for (var ri3 = 0; ri3 < nRows; ri3++) {
            for (var ci3 = 0; ci3 < nCols; ci3++) {
                var d = grid[ri3][ci3];
                if (!d) continue;

                var cx = ci3 * CELL_W + CELL_W / 2;
                var hasThermik = thermikCells[ri3 + ',' + ci3] != null;
                var cy = rowY(ri3) + CELL_H * (hasThermik ? 0.35 : 0.42);
                var speed = d.wind_speed;
                var color = windColor(speed);

                // Only draw wind background if no thermik cell (thermik bg already drawn)
                if (!hasThermik) {
                    chartG.append('rect')
                        .attr('x', ci3 * CELL_W + 1).attr('y', rowY(ri3) + 1)
                        .attr('width', CELL_W - 2).attr('height', CELL_H - 2)
                        .attr('fill', windBgColor(speed)).attr('rx', 3);
                }

                var g = chartG.append('g')
                    .attr('transform', 'translate(' + cx + ', ' + cy + ')')
                    .style('filter', 'drop-shadow(0 1px 2px rgba(0,0,0,0.15))')
                    .style('opacity', 0);

                g.append('path')
                    .attr('d', arrowPath(speed))
                    .attr('fill', color)
                    .attr('transform', 'rotate(' + ((d.wind_direction + 180) % 360) + ')');

                // Hide wind speed number in cells that already have a thermik number
                if (!hasThermik) {
                    chartG.append('text').attr('class', 'wind-value')
                        .attr('x', cx).attr('y', rowY(ri3) + CELL_H - 4)
                        .attr('font-size', '9px').attr('fill', color).attr('opacity', 0.7)
                        .text(Math.round(speed));
                }

                allCells.push({ g: g, ci: ci3, ri: ri3 });
            }
        }

        // Entrance animation
        allCells.forEach(function (cell) {
            cell.g.transition().delay(cell.ci * 20 + cell.ri * 3).duration(400)
                .ease(d3.easeCubicOut).style('opacity', 1);
        });

        // ===== CLOUD ICONS =====
        times.forEach(function (t, ci) {
            var wx = wxByTime[t];
            if (!wx || !wx.cloudbase || wx.cloudbase.height == null) return;
            var cbAlt = wx.cloudbase.height;
            var cover = wx.cloudbase.cover || 50;
            if (cbAlt > altitudes[altitudes.length - 1] + 500) return;

            var startRow = altitudes.findIndex(function (a) { return a >= cbAlt; });
            if (startRow < 0) startRow = 0;
            var numIcons = cover > 80 ? 3 : (cover > 40 ? 2 : 1);
            var endRow = Math.min(nRows, startRow + numIcons);

            for (var ri = startRow; ri < endRow; ri++) {
                var cx = ci * CELL_W + CELL_W / 2;
                var cy2 = rowY(ri) + CELL_H / 2;
                var cloudColor = cover > 80 ? '#9CA3AF' : '#F3F4F6';
                var strokeColor = cover > 80 ? '#374151' : '#4B5563';

                var cloudGroup = chartG.append('g')
                    .attr('transform', 'translate(' + (cx - 12) + ', ' + (cy2 - 12) + ')');
                cloudGroup.append('path')
                    .attr('d', 'M17.5 19H9a7 7 0 1 1 6.71-9h1.79a4.5 4.5 0 1 1 0 9Z')
                    .attr('fill', cloudColor).attr('stroke', strokeColor)
                    .attr('stroke-width', '1.5').attr('stroke-linejoin', 'round');
            }
        });

        // ===== GROUND STRIP =====
        var groundY = gridBottom;
        chartG.append('rect').attr('class', 'ground-bg')
            .attr('x', 0).attr('y', groundY)
            .attr('width', nCols * CELL_W).attr('height', GROUND_H);
        chartG.append('line').attr('class', 'ground-divider')
            .attr('x1', 0).attr('x2', nCols * CELL_W)
            .attr('y1', groundY).attr('y2', groundY);

        var groundLabels = ['Boden', 'Boeen', 'Temp / Regen', 'Thermik'];
        groundLabels.forEach(function (lbl, i) {
            chartG.append('text').attr('class', 'ground-label')
                .attr('x', -8).attr('y', groundY + i * 24 + 14)
                .attr('text-anchor', 'end').text(lbl);
        });

        times.forEach(function (t, ci) {
            var wx = wxByTime[t] || {};
            var wind = wx.wind || {};
            var precip = wx.precipitation || {};
            var cx = ci * CELL_W + CELL_W / 2;

            // Row 0: Surface wind
            var spd = wind.speed != null ? Math.round(wind.speed) : null;
            var dir = wind.direction;
            if (spd != null) {
                var wColor = windColor(spd);
                var gArrow = chartG.append('g')
                    .attr('transform', 'translate(' + (cx - 10) + ', ' + (groundY + 13) + ')');
                gArrow.append('path')
                    .attr('d', arrowPath(spd * 0.7))
                    .attr('fill', wColor)
                    .attr('transform', 'rotate(' + (((dir || 0) + 180) % 360) + ') scale(0.65)');
                chartG.append('text').attr('class', 'ground-value')
                    .attr('x', cx + 8).attr('y', groundY + 14)
                    .attr('dominant-baseline', 'central').attr('fill', wColor)
                    .attr('font-size', '11px').text(spd);
            }

            // Row 1: Gusts
            var gusts = wind.gusts != null ? Math.round(wind.gusts) : null;
            if (gusts != null) {
                chartG.append('text').attr('class', 'ground-value')
                    .attr('x', cx).attr('y', groundY + 24 + 14)
                    .attr('dominant-baseline', 'central').attr('fill', windColor(gusts))
                    .attr('font-size', '11px').text(gusts);
            }

            // Row 2: Temp + Precip
            var lowestLevel = grid[0] && grid[0][ci];
            var temp = lowestLevel ? Math.round(lowestLevel.temperature) : null;
            if (temp != null) {
                chartG.append('text').attr('class', 'ground-value ground-temp')
                    .attr('x', cx - 6).attr('y', groundY + 48 + 14)
                    .attr('dominant-baseline', 'central').attr('font-size', '11px')
                    .text(temp + '\u00B0');
            }
            var precipAmt = precip.amount || 0;
            if (precipAmt > 0) {
                var barH = Math.min(20, precipAmt * 5);
                chartG.append('rect').attr('class', 'ground-precip-bar')
                    .attr('x', cx + 8).attr('y', groundY + 48 + 14 - barH / 2)
                    .attr('width', 12).attr('height', barH).attr('rx', 2)
                    .attr('fill', precipColor(precipAmt));
            }

            // Row 3: Thermik (Steigrate m/s) with xc-therm color scale
            var therm = wx.thermik || {};
            if (therm.climb_rate > 0) {
                var thermBg = thermClimbColor(therm.climb_rate);
                chartG.append('rect')
                    .attr('x', ci * CELL_W + 3).attr('y', groundY + 72 + 3)
                    .attr('width', CELL_W - 6).attr('height', 18)
                    .attr('fill', thermBg).attr('rx', 4).attr('opacity', 0.8);

                chartG.append('text').attr('class', 'ground-value')
                    .attr('x', cx).attr('y', groundY + 72 + 13)
                    .attr('dominant-baseline', 'central').attr('font-size', '10px')
                    .attr('font-weight', '700').attr('fill', '#1E293B')
                    .text(therm.climb_rate.toFixed(1));
            }
        });

        // ===== CROSSHAIR + TOOLTIP =====
        var crossV = chartG.append('line').attr('class', 'crosshair-v')
            .attr('y1', 0).attr('y2', gridBottom + GROUND_H);
        var crossH = chartG.append('line').attr('class', 'crosshair-h')
            .attr('x1', 0).attr('x2', nCols * CELL_W);

        chartG.append('rect')
            .attr('width', nCols * CELL_W)
            .attr('height', gridBottom + GROUND_H)
            .attr('fill', 'transparent')
            .on('mousemove', function (event) {
                var coords = d3.pointer(event);
                var mx = coords[0], my = coords[1];
                var ci = Math.floor(mx / CELL_W);
                if (ci < 0 || ci >= nCols) return;

                var colX = ci * CELL_W + CELL_W / 2;
                crossV.attr('x1', colX).attr('x2', colX).classed('visible', true);
                crossH.attr('y1', my).attr('y2', my).classed('visible', true);

                var t = times[ci];
                var dt = new Date(t);
                var timeStr = dt.getHours() + ':00';
                var wx = wxByTime[t] || {};

                var html = '<div class="tooltip-title">' + timeStr + '</div>';
                var ri = nRows - 1 - Math.floor(my / CELL_H);
                if (ri >= 0 && ri < nRows && grid[ri] && grid[ri][ci]) {
                    var dd = grid[ri][ci];
                    html += '<div class="tooltip-row"><span class="tooltip-label">Hoehe</span><span class="tooltip-value">' + Math.round(dd.altitude) + 'm</span></div>';
                    html += '<div class="tooltip-row"><span class="tooltip-label">Wind</span><span class="tooltip-value" style="color:' + windColor(dd.wind_speed) + '">' + Math.round(dd.wind_speed) + ' km/h</span></div>';
                    html += '<div class="tooltip-row"><span class="tooltip-label">Richtung</span><span class="tooltip-value">' + Math.round(dd.wind_direction) + '\u00B0</span></div>';
                    html += '<div class="tooltip-row"><span class="tooltip-label">Temp</span><span class="tooltip-value">' + dd.temperature.toFixed(1) + '\u00B0C</span></div>';
                    // Thermik rate at this altitude
                    var localThermRate = thermikCells[ri + ',' + ci];
                    if (localThermRate != null && localThermRate > 0) {
                        html += '<div class="tooltip-row"><span class="tooltip-label">Steigrate hier</span><span class="tooltip-value" style="color:' + thermClimbColor(localThermRate) + '">' + localThermRate.toFixed(1) + ' m/s</span></div>';
                    }
                }
                if (wx.wind) {
                    html += '<div class="tooltip-row" style="margin-top:6px;padding-top:6px;border-top:1px solid #E5E7EB"><span class="tooltip-label">Boden</span><span class="tooltip-value" style="color:' + windColor(wx.wind.speed) + '">' + Math.round(wx.wind.speed) + ' km/h</span></div>';
                    if (wx.wind.gusts != null) {
                        html += '<div class="tooltip-row"><span class="tooltip-label">Boeen</span><span class="tooltip-value" style="color:' + windColor(wx.wind.gusts) + '">' + Math.round(wx.wind.gusts) + ' km/h</span></div>';
                    }
                }
                if (wx.thermik) {
                    if (wx.thermik.climb_rate > 0) {
                        html += '<div class="tooltip-row" style="margin-top:6px;padding-top:6px;border-top:1px solid #E5E7EB"><span class="tooltip-label">Steigrate</span><span class="tooltip-value">' + wx.thermik.climb_rate.toFixed(1) + ' m/s</span></div>';
                        html += '<div class="tooltip-row"><span class="tooltip-label">Arbeitsh\u00f6he</span><span class="tooltip-value">' + wx.thermik.max_height + ' m MSL</span></div>';
                        html += '<div class="tooltip-row"><span class="tooltip-label">Rating</span><span class="tooltip-value">' + wx.thermik.rating + '/10</span></div>';
                    }
                    if (wx.thermik.cape > 0) html += '<div class="tooltip-row"><span class="tooltip-label">CAPE</span><span class="tooltip-value">' + Math.round(wx.thermik.cape) + ' J/kg</span></div>';
                }
                if (wx.cloudbase && wx.cloudbase.height != null) {
                    html += '<div class="tooltip-row"><span class="tooltip-label">Wolkenbasis</span><span class="tooltip-value">' + Math.round(wx.cloudbase.height) + 'm</span></div>';
                }
                if (wx.precipitation && wx.precipitation.amount > 0) {
                    html += '<div class="tooltip-row"><span class="tooltip-label">Regen</span><span class="tooltip-value">' + wx.precipitation.amount.toFixed(1) + ' mm</span></div>';
                }

                tooltipEl.innerHTML = html;
                tooltipEl.classList.add('visible');

                var tx = event.clientX + 16;
                var ty = event.clientY - 10;
                if (tx + 200 > window.innerWidth) tx = event.clientX - 200;
                if (ty + 250 > window.innerHeight) ty = event.clientY - 250;
                tooltipEl.style.left = tx + 'px';
                tooltipEl.style.top = ty + 'px';
            })
            .on('mouseleave', function () {
                crossV.classed('visible', false);
                crossH.classed('visible', false);
                tooltipEl.classList.remove('visible');
            });
    }

    // Public API
    return {
        windColor: windColor,
        arrowPath: arrowPath,
        buildTabs: buildTabs,
        renderChart: renderChart
    };
})();
