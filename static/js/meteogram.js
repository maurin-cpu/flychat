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
        // At ground (frac=0): ~45% of peak (increased from 30% to improve visibility near ground)
        var localRate = climbRate * (0.45 + 0.55 * profile);
        // Ensure at least 0.1 m/s if thermal is present and within range, to avoid "jumping" start height
        return Math.max(0.1, Math.round(localRate * 10) / 10);
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
    const GROUND_ROWS = 3;
    const GROUND_H = GROUND_ROWS * 24;
    const TIME_LABEL_H = 28;
    const CLOUD_ROW_H = 18;
    const PRECIP_ROW_H = 20;
    const CLOUD_STRIP_H = 3 * CLOUD_ROW_H + PRECIP_ROW_H; // CH, CM, CL + Niederschlag/Gewitter
    const CLOUD_GAP = 6;

    // WMO weather_code: 95/96/99 = Gewitter
    function isThunderstorm(code) {
        return code === 95 || code === 96 || code === 99;
    }

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

        // Filter to 06:00 - 18:00
        var MIN_HOUR = 6, MAX_HOUR = 18;
        function hourFromTime(t) { return new Date(t).getHours(); }

        var profiles = altDay.profiles.filter(function (p) {
            var h = hourFromTime(p.time);
            return h >= MIN_HOUR && h <= MAX_HOUR;
        });
        if (profiles.length === 0) {
            container.innerHTML = '<div class="error-state">Keine Daten fuer diesen Tag.</div>';
            return;
        }

        // Also filter weather data to same range
        if (wxDay) {
            var filtered = {};
            ['wind', 'precipitation', 'thermik', 'cloudbase'].forEach(function (key) {
                if (wxDay[key]) {
                    filtered[key] = wxDay[key].filter(function (item) {
                        var h = hourFromTime(item.time);
                        return h >= MIN_HOUR && h <= MAX_HOUR;
                    });
                }
            });
            wxDay = filtered;
        }

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
        var chartH = MARGIN.top + CLOUD_STRIP_H + CLOUD_GAP + nRows * CELL_H + GROUND_H + TIME_LABEL_H + 8;

        var svg = d3.select(container)
            .append('svg')
            .attr('width', chartW)
            .attr('height', chartH)
            .style('display', 'block');

        var chartG = svg.append('g')
            .attr('transform', 'translate(' + MARGIN.left + ', ' + MARGIN.top + ')');

        var GRID_TOP = CLOUD_STRIP_H + CLOUD_GAP;
        function rowY(ri) { return GRID_TOP + (nRows - 1 - ri) * CELL_H; }
        var gridBottom = GRID_TOP + nRows * CELL_H;
        var elevation = (options && options.elevation) || 0;

        // Helper for altitude to Y coordinate (smooth, not grid-aligned)
        function altToY(alt) {
            var topAlt = altitudes[altitudes.length - 1];
            return GRID_TOP + (1 - alt / topAlt) * (nRows * CELL_H);
        }

        // ===== CLOUD STRIP (Smooth Area Charts) =====
        var defs = svg.append("defs");

        // Sky gradient
        var skyGrad = defs.append("linearGradient")
            .attr("id", "skyGradient")
            .attr("x1", "0%").attr("y1", "0%")
            .attr("x2", "0%").attr("y2", "100%");
        skyGrad.append("stop").attr("offset", "0%").style("stop-color", "#F1F5F9"); // Slate-100 (Neutraler)
        skyGrad.append("stop").attr("offset", "100%").style("stop-color", "#F8FAFC"); // Slate-50

        // Cloud gradients mapped to UserSpace so small clouds only sample the transparent bottom
        // y1 = Bottom of strip (CLOUD_STRIP_H), y2 = Top of strip (0)
        var gradHigh = defs.append("linearGradient").attr("id", "gradHigh").attr("gradientUnits", "userSpaceOnUse")
            .attr("x1", 0).attr("y1", CLOUD_STRIP_H).attr("x2", 0).attr("y2", 0);
        gradHigh.append("stop").attr("offset", "0%").style("stop-color", "#94A3B8").style("stop-opacity", 0.05);
        gradHigh.append("stop").attr("offset", "100%").style("stop-color", "#94A3B8").style("stop-opacity", 0.65);

        var gradMid = defs.append("linearGradient").attr("id", "gradMid").attr("gradientUnits", "userSpaceOnUse")
            .attr("x1", 0).attr("y1", CLOUD_STRIP_H).attr("x2", 0).attr("y2", 0);
        gradMid.append("stop").attr("offset", "0%").style("stop-color", "#475569").style("stop-opacity", 0.1);
        gradMid.append("stop").attr("offset", "100%").style("stop-color", "#475569").style("stop-opacity", 0.85);

        var gradLow = defs.append("linearGradient").attr("id", "gradLow").attr("gradientUnits", "userSpaceOnUse")
            .attr("x1", 0).attr("y1", CLOUD_STRIP_H).attr("x2", 0).attr("y2", 0);
        gradLow.append("stop").attr("offset", "0%").style("stop-color", "#0F172A").style("stop-opacity", 0.15);
        gradLow.append("stop").attr("offset", "100%").style("stop-color", "#020617").style("stop-opacity", 0.95);

        var cloudLayers = [
            { key: 'cover_high', label: 'Hoch', baseColor: '#94A3B8' }, // Slate-400
            { key: 'cover_mid', label: 'Mittel', baseColor: '#64748B' }, // Slate-500
            { key: 'cover_low', label: 'Tief', baseColor: '#475569' }     // Slate-600
        ];

        // Sky background (nur ueber den 3 Wolkenzeilen, nicht ueber Niederschlag-Zeile)
        chartG.append('rect')
            .attr('x', 0).attr('y', 0)
            .attr('width', nCols * CELL_W).attr('height', 3 * CLOUD_ROW_H)
            .attr('fill', 'url(#skyGradient)').attr('rx', 4);

        // Legend / Labels for cloud types on the left
        cloudLayers.forEach(function (layer, li) {
            chartG.append('text').attr('class', 'axis-label')
                .attr('x', -8)
                .attr('y', li * CLOUD_ROW_H + CLOUD_ROW_H / 2) 
                .attr('text-anchor', 'end').attr('dominant-baseline', 'central')
                .attr('font-size', '9px').attr('font-weight', '600')
                .attr('fill', '#64748B')
                .text(layer.label);
            
            // Subtle horizontal separator between layers
            if (li < cloudLayers.length - 1) {
                chartG.append('line')
                    .attr('x1', 0).attr('x2', nCols * CELL_W)
                    .attr('y1', (li + 1) * CLOUD_ROW_H).attr('y2', (li + 1) * CLOUD_ROW_H)
                    .attr('stroke', 'rgba(148, 163, 184, 0.2)').attr('stroke-width', 1);
            }
        });

        // Draw each layer as a discrete horizontal strip (Proposal A)
        cloudLayers.forEach(function (layer, li) {
            var rowY = li * CLOUD_ROW_H;
            
            times.forEach(function (t, ci) {
                var wx = wxByTime[t];
                var cover = (wx && wx.cloudbase && wx.cloudbase[layer.key]) ? wx.cloudbase[layer.key] : 0;
                if (cover <= 0) return;

                // Softened intensity-based rendering
                chartG.append('rect')
                    .attr('x', ci * CELL_W + 1)
                    .attr('y', rowY + 1)
                    .attr('width', CELL_W - 2)
                    .attr('height', CLOUD_ROW_H - 2)
                    .attr('fill', layer.baseColor)
                    .attr('opacity', 0.15 + (cover / 100) * 0.7)
                    .attr('rx', 2);
                
                // Overlay small percentage with high contrast text
                if (cover > 20 && CELL_W > 25) {
                    var isDark = (cover > 70 && li >= 1); // Darker layers with high cover
                    chartG.append('text')
                        .attr('x', ci * CELL_W + CELL_W / 2)
                        .attr('y', rowY + CLOUD_ROW_H / 2 + 1)
                        .attr('text-anchor', 'middle').attr('dominant-baseline', 'central')
                        .attr('font-size', '9px').attr('font-weight', '700')
                        .attr('fill', isDark ? '#F8FAFC' : '#1E293B')
                        .style('text-shadow', isDark ? '0 0 2px rgba(0,0,0,0.3)' : '0 0 2px rgba(255,255,255,0.8)')
                        .text(Math.round(cover));
                }
            });
        });

        // Zeile: Niederschlag / Gewitter pro Stunde
        var precipRowY = 3 * CLOUD_ROW_H;
        chartG.append('line')
            .attr('x1', 0).attr('x2', nCols * CELL_W)
            .attr('y1', precipRowY).attr('y2', precipRowY)
            .attr('stroke', 'rgba(148, 163, 184, 0.2)').attr('stroke-width', 1);
        chartG.append('text').attr('class', 'axis-label')
            .attr('x', -8)
            .attr('y', precipRowY + PRECIP_ROW_H / 2)
            .attr('text-anchor', 'end').attr('dominant-baseline', 'central')
            .attr('font-size', '9px').attr('font-weight', '600')
            .attr('fill', '#64748B')
            .text('Nied./Gew.');
        times.forEach(function (t, ci) {
            var wx = wxByTime[t];
            if (!wx) return;
            var precip = wx.precipitation || {};
            var precipAmt = precip.amount || 0;
            var wc = precip.weather_code != null ? precip.weather_code : (wx.cloudbase && wx.cloudbase.weather_code);
            var cx = ci * CELL_W + CELL_W / 2;
            var hasPrecip = precipAmt > 0;
            var hasStorm = isThunderstorm(wc);
            if (!hasPrecip && !hasStorm) return;

            // Gefuellter Hintergrund – sofort sichtbar
            var fillColor = hasStorm ? 'rgba(245, 158, 11, 0.5)' : (precipColor(precipAmt) + '99');
            chartG.append('rect')
                .attr('x', ci * CELL_W + 1)
                .attr('y', precipRowY + 1)
                .attr('width', CELL_W - 2)
                .attr('height', PRECIP_ROW_H - 2)
                .attr('fill', fillColor)
                .attr('rx', 3)
                .attr('title', hasPrecip ? precipAmt.toFixed(1) + ' mm' + (hasStorm ? ' + Gewitter' : '') : 'Gewitter');

            // Einfacher Text: mm-Wert oder "Blitz"
            var label = hasStorm && hasPrecip ? precipAmt.toFixed(1) + ' \u26A1' : (hasStorm ? 'Blitz' : precipAmt.toFixed(1) + ' mm');
            chartG.append('text')
                .attr('x', cx)
                .attr('y', precipRowY + PRECIP_ROW_H / 2 + 1)
                .attr('text-anchor', 'middle').attr('dominant-baseline', 'central')
                .attr('font-size', '12px').attr('font-weight', '700')
                .attr('fill', hasStorm ? '#92400E' : '#1E3A5F')
                .text(label);
        });

        // Separator line between cloud strip and altitude grid
        chartG.append('line')
            .attr('x1', 0).attr('x2', nCols * CELL_W)
            .attr('y1', CLOUD_STRIP_H + CLOUD_GAP / 2).attr('y2', CLOUD_STRIP_H + CLOUD_GAP / 2)
            .attr('stroke', '#94A3B8').attr('stroke-width', 1.5);

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

        // ===== GRID LINES =====
        for (var ri2 = 0; ri2 <= nRows; ri2++) {
            chartG.append('line').attr('class', 'grid-line')
                .attr('x1', 0).attr('x2', nCols * CELL_W)
                .attr('y1', GRID_TOP + ri2 * CELL_H).attr('y2', GRID_TOP + ri2 * CELL_H);
        }
        for (var ci2 = 0; ci2 <= nCols; ci2++) {
            chartG.append('line').attr('class', 'grid-line')
                .attr('x1', ci2 * CELL_W).attr('x2', ci2 * CELL_W)
                .attr('y1', GRID_TOP).attr('y2', gridBottom + GROUND_H);
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
                var cy = rowY(ri3) + CELL_H * (hasThermik ? 0.5 : 0.42);
                var speed = d.wind_speed;
                var isAloftWarning = speed > 35;
                var color = isAloftWarning ? '#ef4444' : windColor(speed); // Red for ALOFT-WARN

                // Only draw wind background if no thermik cell (thermik bg already drawn)
                if (!hasThermik) {
                    chartG.append('rect')
                        .attr('x', ci3 * CELL_W + 1).attr('y', rowY(ri3) + 1)
                        .attr('width', CELL_W - 2).attr('height', CELL_H - 2)
                        .attr('fill', isAloftWarning ? 'rgba(239, 68, 68, 0.15)' : windBgColor(speed)) // Red tint if warning
                        .attr('rx', 3);
                }

                var g = chartG.append('g')
                    .attr('transform', 'translate(' + cx + ', ' + cy + ')')
                    .style('filter', isAloftWarning ? 'drop-shadow(0 0 3px rgba(239, 68, 68, 0.7))' : 'drop-shadow(0 1px 2px rgba(0,0,0,0.15))')
                    .style('opacity', 0);

                g.append('path')
                    .attr('d', arrowPath(speed))
                    .attr('fill', color)
                    .attr('transform', 'rotate(' + ((d.wind_direction + 180) % 360) + ')');

                // Show wind speed number in all cells. Put it at the top if there's thermik data at the bottom.
                var windTextY = rowY(ri3) + (hasThermik ? 9 : CELL_H - 4);
                chartG.append('text').attr('class', 'wind-value')
                    .attr('x', cx).attr('y', windTextY)
                    .attr('font-size', '9px').attr('fill', color).attr('opacity', hasThermik ? 1.0 : (isAloftWarning ? 1.0 : 0.7))
                    .attr('font-weight', isAloftWarning ? 'bold' : 'normal')
                    .style('text-shadow', hasThermik ? '0 1px 2px rgba(255,255,255,0.8)' : 'none')
                    .text(Math.round(speed));

                allCells.push({ g: g, ci: ci3, ri: ri3 });
            }
        }

        // Entrance animation
        allCells.forEach(function (cell) {
            cell.g.transition().delay(cell.ci * 20 + cell.ri * 3).duration(400)
                .ease(d3.easeCubicOut).style('opacity', 1);
        });

        // ===== GROUND STRIP =====
        var groundY = gridBottom;
        chartG.append('rect').attr('class', 'ground-bg')
            .attr('x', 0).attr('y', groundY)
            .attr('width', nCols * CELL_W).attr('height', GROUND_H);
        chartG.append('line').attr('class', 'ground-divider')
            .attr('x1', 0).attr('x2', nCols * CELL_W)
            .attr('y1', groundY).attr('y2', groundY);

        var groundLabels = ['Wind / Böen', 'Temp / Regen', 'Thermik'];
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

            // Combined Row 0: Surface wind + Gusts
            var spd = wind.speed != null ? Math.round(wind.speed) : null;
            var gusts = wind.gusts != null ? Math.round(wind.gusts) : null;
            var dir = wind.direction;
            
            if (spd != null) {
                var wColor = windColor(spd);
                var isGustWarning = gusts != null && (gusts > spd + 15);
                var gy = groundY + 13;

                // 1. Gust Shadow (if gusts are significantly higher or for visual depth)
                if (gusts != null && gusts > spd) {
                    var gShadow = chartG.append('g')
                        .attr('transform', 'translate(' + (cx - 15) + ', ' + gy + ')');
                    gShadow.append('path')
                        .attr('d', arrowPath(gusts * 0.7))
                        .attr('fill', isGustWarning ? '#ef4444' : '#F97316') // Red if warning, else Orange
                        .attr('opacity', 0.3)
                        .attr('transform', 'rotate(' + (((dir || 0) + 180) % 360) + ') scale(0.65)');
                }

                // 2. Primary Wind Arrow
                var gArrow = chartG.append('g')
                    .attr('transform', 'translate(' + (cx - 15) + ', ' + gy + ')');
                gArrow.append('path')
                    .attr('d', arrowPath(spd * 0.7))
                    .attr('fill', wColor)
                    .attr('transform', 'rotate(' + (((dir || 0) + 180) % 360) + ') scale(0.65)');
                
                // 3. Combined Text: "Wind / Böen"
                var label = spd.toString();
                if (gusts != null) label += ' / ' + gusts;

                chartG.append('text').attr('class', 'ground-value')
                    .attr('x', cx + 6).attr('y', gy + 1)
                    .attr('dominant-baseline', 'central')
                    .attr('fill', isGustWarning ? '#ef4444' : wColor)
                    .attr('font-weight', isGustWarning ? 'bold' : 'normal')
                    .attr('font-size', '10px')
                    .text(label);
            }

            // Row 1: Temp + Precip
            var lowestLevel = grid[0] && grid[0][ci];
            var temp = lowestLevel ? Math.round(lowestLevel.temperature) : null;
            if (temp != null) {
                chartG.append('text').attr('class', 'ground-value ground-temp')
                    .attr('x', cx - 6).attr('y', groundY + 24 + 14)
                    .attr('dominant-baseline', 'central').attr('font-size', '11px')
                    .text(temp + '\u00B0');
            }
            var precipAmt = precip.amount || 0;
            if (precipAmt > 0) {
                var barH = Math.min(20, precipAmt * 5);
                chartG.append('rect').attr('class', 'ground-precip-bar')
                    .attr('x', cx + 8).attr('y', groundY + 24 + 14 - barH / 2)
                    .attr('width', 12).attr('height', barH).attr('rx', 2)
                    .attr('fill', precipColor(precipAmt));
            }

            // Row 3: Thermik (Steigrate m/s) with xc-therm color scale
            var therm = wx.thermik || {};
            if (therm.climb_rate > 0) {
                var thermBg = thermClimbColor(therm.climb_rate);
                chartG.append('rect')
                    .attr('x', ci * CELL_W + 1).attr('y', groundY + 48 + 1)
                    .attr('width', CELL_W - 2).attr('height', 22).attr('rx', 3)
                    .attr('fill', thermBg).attr('opacity', 0.4);
                
                chartG.append('text').attr('class', 'ground-value')
                    .attr('x', cx).attr('y', groundY + 48 + 14)
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

                // Cloud info
                if (wx.cloudbase) {
                    var cb = wx.cloudbase;
                    var hasCloud = (cb.cover_low > 0) || (cb.cover_mid > 0) || (cb.cover_high > 0);
                    if (hasCloud) {
                        html += '<div class="tooltip-row" style="margin-bottom:4px"><span class="tooltip-label">Wolken</span><span class="tooltip-value" style="font-size:10px">';
                        if (cb.cover_high > 0) html += 'H:' + Math.round(cb.cover_high) + '% ';
                        if (cb.cover_mid > 0) html += 'M:' + Math.round(cb.cover_mid) + '% ';
                        if (cb.cover_low > 0) html += 'T:' + Math.round(cb.cover_low) + '%';
                        html += '</span></div>';
                    }
                    if (cb.height != null) {
                        html += '<div class="tooltip-row"><span class="tooltip-label">Wolkenbasis</span><span class="tooltip-value">' + Math.round(cb.height) + 'm</span></div>';
                    }
                }

                var ri = nRows - 1 - Math.floor((my - GRID_TOP) / CELL_H);
                if (my >= GRID_TOP && ri >= 0 && ri < nRows && grid[ri] && grid[ri][ci]) {
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
                if (wx.precipitation && wx.precipitation.amount > 0) {
                    html += '<div class="tooltip-row"><span class="tooltip-label">Regen</span><span class="tooltip-value">' + wx.precipitation.amount.toFixed(1) + ' mm</span></div>';
                }
                var wc = (wx.precipitation && wx.precipitation.weather_code != null) ? wx.precipitation.weather_code : (wx.cloudbase && wx.cloudbase.weather_code);
                if (isThunderstorm(wc)) {
                    html += '<div class="tooltip-row"><span class="tooltip-label">Gewitter</span><span class="tooltip-value">\u26A1 vorhergesagt</span></div>';
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
