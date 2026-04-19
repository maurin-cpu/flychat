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

    // Turbulence risk color (based on absolute T(z) value)
    function turbulenceColor(tz) {
        if (tz <= 10) return '#059669';   // Green — ruhig
        if (tz <= 20) return '#10B981';   // Light green — moderat
        if (tz <= 25) return '#D97706';   // Amber — spürbar
        if (tz <= 30) return '#EA580C';   // Orange — kräftig
        return '#DC2626';                 // Red — stark/gefährlich
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
    var MARGIN = { top: 12, right: 24, bottom: 0, left: (window.innerWidth <= 480) ? 56 : 96 };
    var CELL_H = 36;
    const GROUND_ROWS = 3;
    const GROUND_H = GROUND_ROWS * 24;
    const TIME_LABEL_H = 28;
    const CLOUD_ROW_H = 18;
    const PRECIP_ROW_H = 20;
    const CLOUD_STRIP_H = 3 * CLOUD_ROW_H + PRECIP_ROW_H; // CH, CM, CL + Niederschlag/Gewitter
    const CLOUD_GAP = 6;
    // Warnings strip: small pills under the ground section summarising hour-ranges
    const WARN_ROW_H = 16;
    const WARN_ROW_GAP = 2;
    const WARN_MAX_ROWS = 4;

    // WMO weather_code: 95/96/99 = Gewitter
    function isThunderstorm(code) {
        return code === 95 || code === 96 || code === 99;
    }

    // ===== DIRECTION PARSER (compatible with map.js) =====
    // Returns an array of [startDeg, endDeg] sectors (0-360+ possibly), or null.
    // Accepts "SW", "SW-W", "N-NO-O", "W/NW", etc.
    var DIR_TO_DEG = {
        'N': 0, 'NNO': 22.5, 'NNE': 22.5, 'NO': 45, 'NE': 45,
        'ONO': 67.5, 'ENE': 67.5, 'O': 90, 'E': 90,
        'OSO': 112.5, 'ESE': 112.5, 'SO': 135, 'SE': 135,
        'SSO': 157.5, 'SSE': 157.5, 'S': 180,
        'SSW': 202.5, 'SW': 225, 'WSW': 247.5,
        'W': 270, 'WNW': 292.5, 'NW': 315, 'NNW': 337.5
    };

    function parseWindDirection(dirStr) {
        if (!dirStr) return null;
        var clean = String(dirStr).toUpperCase().replace(/\s+/g, '');
        var parts = clean.split(/[\/,]/).filter(function (p) { return p.length > 0; });
        var sectors = [];
        parts.forEach(function (part) {
            var subs = part.split('-').filter(function (p) { return p.length > 0; });
            if (subs.length === 0) return;
            if (subs.length === 1) {
                var a = DIR_TO_DEG[subs[0]];
                if (a == null) return;
                sectors.push([a - 22.5, a + 22.5]);
                return;
            }
            var a1 = DIR_TO_DEG[subs[0]];
            var a2 = DIR_TO_DEG[subs[subs.length - 1]];
            if (a1 == null || a2 == null) return;
            if (Math.abs(a1 - a2) > 180) {
                if (a1 < a2) a1 += 360; else a2 += 360;
            }
            var lo = Math.min(a1, a2) - 22.5;
            var hi = Math.max(a1, a2) + 22.5;
            sectors.push([lo, hi]);
        });
        return sectors.length > 0 ? sectors : null;
    }

    function isDirInSectors(deg, sectors, bufferDeg) {
        if (!sectors || sectors.length === 0 || deg == null) return true; // unknown -> treat as OK
        var buf = bufferDeg || 10;
        for (var i = 0; i < sectors.length; i++) {
            var lo = sectors[i][0] - buf;
            var hi = sectors[i][1] + buf;
            // Normalize wind direction into [lo, lo+360) range
            var d = deg;
            while (d < lo) d += 360;
            if (d >= lo && d <= hi) return true;
        }
        return false;
    }

    // Group consecutive cells where `pred(ci)` returns true into [startCol, endCol] ranges
    function groupConsecutive(nCols, pred) {
        var groups = [];
        var start = null;
        for (var ci = 0; ci < nCols; ci++) {
            if (pred(ci)) {
                if (start == null) start = ci;
            } else if (start != null) {
                groups.push([start, ci - 1]);
                start = null;
            }
        }
        if (start != null) groups.push([start, nCols - 1]);
        return groups;
    }

    // Format a column range as "HH-HHh" using times[]
    function formatHourRange(times, startCi, endCi) {
        var h1 = new Date(times[startCi]).getHours();
        var h2 = new Date(times[endCi]).getHours();
        if (h1 === h2) return h1 + 'h';
        return h1 + '-' + h2 + 'h';
    }

    /** Einheitlich mit Spot-Analysen: MO–SO gross, DD.MM.JJJJ */
    function formatDayTabLabel(dateStr) {
        var d = new Date(dateStr + 'T12:00:00');
        var dayNames = ['SO', 'MO', 'DI', 'MI', 'DO', 'FR', 'SA'];
        var dd = String(d.getDate()).padStart(2, '0');
        var mm = String(d.getMonth() + 1).padStart(2, '0');
        var yyyy = d.getFullYear();
        return dayNames[d.getDay()] + ' ' + dd + '.' + mm + '.' + yyyy;
    }

    // ===== TABS =====
    function buildTabs(container, dates, onSelect) {
        container.innerHTML = '';
        dates.forEach(function (d, idx) {
            var label = formatDayTabLabel(d);
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

        // Fixed altitude grid in 250m steps, starting from launch elevation
        var STEP = 250;
        var FULL_ROWS = 17; // 0-4000m = 17 rows (reference for constant chart height)
        var elevation = (options && options.elevation) || 0;
        var minGridAlt = Math.floor(elevation / STEP) * STEP;
        var altitudes = [];
        for (var a = minGridAlt; a <= 4000; a += STEP) altitudes.push(a);
        var nRows = altitudes.length;
        // Scale cell height so the grid area stays constant regardless of row count
        var cellH = Math.round(FULL_ROWS * CELL_H / nRows);
        var scale = cellH / CELL_H; // 1.0 at 17 rows, ~1.9 at 9 rows

        // Bodenwind-Override: grid[0] bekommt den terrain-korrigierten 10m-Wind
        // (statt PL-Interpolation der freien Atmosphäre). Row bleibt optisch
        // gleich hoch wie alle anderen — der Bodenwind ist physikalisch nur
        // am Boden gültig, keine dicke Schicht. Thermik wird normal gerendert.
        var groundWindByTime = (options && options.groundWindByTime) || null;
        var hasGroundRow = !!(groundWindByTime && elevation > 0);
        // Bei Regionen ist `elevation` nur ein Referenzpunkt, kein Startplatz.
        // Thermik darf dann auch in den Grid-Zeilen UNTER dem Referenzpunkt
        // rendern (Region-Einzugsgebiet umfasst verschiedene Höhen).
        var isRegion = !!(options && options.isRegion);
        var thermalBaseAlt = isRegion ? minGridAlt : elevation;

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
                    var gustBelow = below.wind_gusts != null ? below.wind_gusts : below.wind_speed;
                    var gustAbove = above.wind_gusts != null ? above.wind_gusts : above.wind_speed;
                    var trBelow = below.turbulence_risk != null ? below.turbulence_risk : gustBelow;
                    var trAbove = above.turbulence_risk != null ? above.turbulence_risk : gustAbove;
                    var teBelow = below.turbulence_excess != null ? below.turbulence_excess : 0;
                    var teAbove = above.turbulence_excess != null ? above.turbulence_excess : 0;
                    grid[ri][ci] = {
                        altitude: targetAlt,
                        wind_speed: below.wind_speed + frac * (above.wind_speed - below.wind_speed),
                        wind_gusts: gustBelow + frac * (gustAbove - gustBelow),
                        turbulence_risk: trBelow + frac * (trAbove - trBelow),
                        turbulence_excess: teBelow + frac * (teAbove - teBelow),
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

        // Bodenwind-Injection: grid[0] mit terrain-korrigiertem 10m-Wind
        // überschreiben. Turbulenz-Exzess = Böen − Mittelwind (Gust-Delta),
        // damit der Strip am rechten Rand der Kachel die Böen-Intensität
        // anzeigt (gleiche Logik wie Höhenkacheln).
        if (hasGroundRow) {
            profiles.forEach(function (p, ci) {
                var gw = groundWindByTime[p.time];
                if (!gw) return;
                var ws = gw.wind_speed != null ? gw.wind_speed : 0;
                var wg = gw.wind_gusts != null ? gw.wind_gusts : ws;
                var wd = gw.wind_direction != null ? gw.wind_direction : 0;
                grid[0][ci] = {
                    altitude: elevation,
                    wind_speed: ws,
                    wind_gusts: wg,
                    turbulence_risk: wg,
                    turbulence_excess: Math.max(0, wg - ws),
                    wind_direction: wd,
                    temperature: grid[0][ci] ? grid[0][ci].temperature : 0,
                    pressure: null,
                    isGroundRow: true
                };
            });
        }

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

        // Dimensions (responsive)
        MARGIN.left = (window.innerWidth <= 480) ? 56 : 96;
        var panelWidth = container.clientWidth || 800;
        var minCellW = (window.innerWidth <= 480) ? 28 : 40;
        var minChartW = MARGIN.left + nCols * minCellW + MARGIN.right;
        var chartW = Math.max(panelWidth, minChartW);
        var CELL_W = (chartW - MARGIN.left - MARGIN.right) / nCols;
        var isNarrow = CELL_W < 36;

        // ===== COMPUTE PLAIN-LANGUAGE WARNING BANDS =====
        // These are grouped hour-ranges (ci..ci) used later to draw pills
        // BELOW the ground strip in plain German.
        // elevation already extracted above for altitude grid filtering
        var windSectors = parseWindDirection(options.windrichtung || '');
        var idealWindMax = options.idealWindMax || 30;

        // Per-column boolean flags
        var flagBuf = [];
        for (var wci = 0; wci < nCols; wci++) flagBuf.push({});

        times.forEach(function (t, ci) {
            var wx = wxByTime[t] || {};
            var wind = wx.wind || {};
            var precip = wx.precipitation || {};
            var thermik = wx.thermik || {};
            var profile = profiles[ci];
            var f = flagBuf[ci];

            // Ground wind direction wrong
            if (windSectors && wind.direction != null
                && wind.speed != null && wind.speed >= 3) {
                if (!isDirInSectors(wind.direction, windSectors, 10)) {
                    f.wrong = true;
                }
            }
            // Strong ground wind
            if (wind.speed != null && wind.speed > idealWindMax) {
                f.strong = true;
            }
            // Gusts
            if (wind.gusts != null && wind.speed != null) {
                if (wind.gusts > 40) f.gustDanger = true;
                else if (wind.gusts > 30 && (wind.gusts - wind.speed) > 15) f.gustWarn = true;
                else if (wind.gusts > 30) f.gustWarn = true;
            }
            // Rain
            if (precip.amount != null && precip.amount > 0.05) f.rain = true;
            var wcAll = (precip.weather_code != null) ? precip.weather_code
                      : ((wx.cloudbase && wx.cloudbase.weather_code != null) ? wx.cloudbase.weather_code : null);
            if (isThunderstorm(wcAll)) f.storm = true;
            // CAPE
            if (thermik.cape != null && thermik.cape > 800) f.cape = true;

            // Aloft danger (within flight layer: elevation .. thermal_max + 1000m)
            if (profile && profile.levels && elevation > 0) {
                var topLimit = (thermik.max_height || (elevation + 2000)) + 1000;
                for (var li = 0; li < profile.levels.length; li++) {
                    var lv = profile.levels[li];
                    if (lv == null || lv.altitude == null) continue;
                    if (lv.altitude < elevation || lv.altitude > topLimit) continue;
                    var wsA = lv.wind_speed;
                    var wgA = lv.wind_gusts != null ? lv.wind_gusts : wsA;
                    if (wsA != null) {
                        if (wsA > 40) f.aloftDanger = true;
                        else if (wsA > 30) f.aloftWarn = true;
                    }
                    if (wgA != null) {
                        if (wgA > 40) f.aloftGustDanger = true;
                        else if (wgA > 30) f.aloftGustWarn = true;
                    }
                }
            }
        });

        // Warning type configuration, in priority order
        var WARN_TYPES = [
            { key: 'storm',            label: 'Gewitter',               color: '#92400E', bg: '#FEF3C7' },
            { key: 'rain',             label: 'Regen',                  color: '#1E3A8A', bg: '#DBEAFE' },
            { key: 'gustDanger',       label: 'Böen gefährlich',        color: '#991B1B', bg: '#FEE2E2' },
            { key: 'aloftDanger',      label: 'Höhenwind gefährlich',   color: '#991B1B', bg: '#FEE2E2' },
            { key: 'aloftGustDanger',  label: 'Höhenböen gefährlich',   color: '#991B1B', bg: '#FEE2E2' },
            { key: 'strong',           label: 'Grundwind zu stark',     color: '#991B1B', bg: '#FEE2E2' },
            { key: 'wrong',            label: 'Wind falsche Richtung',  color: '#9A3412', bg: '#FFEDD5' },
            { key: 'gustWarn',         label: 'Böen stark',             color: '#9A3412', bg: '#FFEDD5' },
            { key: 'aloftWarn',        label: 'Höhenwind kräftig',      color: '#9A3412', bg: '#FFEDD5' },
            { key: 'aloftGustWarn',    label: 'Höhenböen kräftig',      color: '#9A3412', bg: '#FFEDD5' },
            { key: 'cape',             label: 'Überentwicklung (CAPE)', color: '#92400E', bg: '#FEF3C7' }
        ];

        // Build groups per warning type
        var warnBands = [];
        WARN_TYPES.forEach(function (wt) {
            var groups = groupConsecutive(nCols, function (ci) { return !!flagBuf[ci][wt.key]; });
            groups.forEach(function (g) {
                warnBands.push({
                    key: wt.key,
                    label: wt.label,
                    color: wt.color,
                    bg: wt.bg,
                    start: g[0],
                    end: g[1],
                });
            });
        });

        // Row-pack (greedy) so non-overlapping bands share a row
        warnBands.forEach(function (b) { b.row = -1; });
        var rowLastEnd = []; // rowLastEnd[row] = last end col used
        warnBands.forEach(function (b) {
            for (var r = 0; r < WARN_MAX_ROWS; r++) {
                if (rowLastEnd[r] == null || rowLastEnd[r] < b.start) {
                    b.row = r;
                    rowLastEnd[r] = b.end;
                    return;
                }
            }
            // overflow: drop lower-priority ones that don't fit
        });
        var usedRows = Math.max(0, rowLastEnd.length);
        var WARN_STRIP_H = usedRows > 0 ? (usedRows * (WARN_ROW_H + WARN_ROW_GAP) + 6) : 0;

        var chartH = MARGIN.top + CLOUD_STRIP_H + CLOUD_GAP + nRows * cellH + TIME_LABEL_H + GROUND_H + WARN_STRIP_H + 8;

        var svg = d3.select(container)
            .append('svg')
            .attr('width', chartW)
            .attr('height', chartH)
            .style('display', 'block');

        var chartG = svg.append('g')
            .attr('transform', 'translate(' + MARGIN.left + ', ' + MARGIN.top + ')');

        var GRID_TOP = CLOUD_STRIP_H + CLOUD_GAP;
        // Alle Rows gleich hoch — Bodenwind ist physikalisch punktuell,
        // keine dicke Schicht. Row 0 zeigt Bodenwind-Daten, Thermik-Farbe
        // bleibt normal gerendert.
        function rowY(ri) { return GRID_TOP + (nRows - 1 - ri) * cellH; }
        function rowHeight(ri) { return cellH; }
        var gridBottom = GRID_TOP + nRows * cellH;

        // Helper for altitude to Y coordinate (smooth, not grid-aligned)
        var bottomAlt = altitudes[0];
        var topAlt = altitudes[altitudes.length - 1];
        function altToY(alt) {
            return GRID_TOP + (1 - (alt - bottomAlt) / (topAlt - bottomAlt)) * (nRows * cellH);
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

        // ===== STARTPLATZ-REIHE Hintergrund (Row 0) =====
        // Row 0 IST der Startplatz — eine eigene KATEGORIE von Wind-Kacheln
        // (Bodenwind, terrain-korrigiert), klar abgegrenzt von den Zeilen
        // darüber (freie Atmosphäre). Gestalt-Prinzip "Common Region":
        //   • Starker Orange-Tint als Zonen-Hintergrund
        //   • Sektions-Trenner (oben) zwischen Row 0 und Row 1+
        //   • Zell-Umrisse pro Kachel (siehe Wind-Cell-Rendering weiter unten)
        // NUR bei Spots — Regionen haben keinen Startplatz.
        if (hasGroundRow && elevation > 0) {
            // Zonen-Hintergrund: Orange-200 mit höherer Opacity.
            // Thermik-Cells (opacity 0.8) überlagern später und mischen sich
            // mit dem Orange — die Zelle bleibt als "Startplatz-Kachel mit
            // Thermik" erkennbar.
            chartG.append('rect').attr('class', 'launch-row-bg')
                .attr('x', 0).attr('y', rowY(0))
                .attr('width', nCols * CELL_W).attr('height', cellH)
                .attr('fill', '#FED7AA')  // Orange-200
                .attr('opacity', 0.7)
                .style('pointer-events', 'none');
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
                // Row 0 bei Spots = Startplatz-Kachel. Verwende `elevation` für
                // die Thermik-Berechnung (statt altitudes[0]=minGridAlt=1000m
                // bei elevation=1228m), damit die Startplatz-Kachel die
                // Thermik ab Boden zeigt — nicht "unter Startplatz = keine Thermik".
                var thermAlt = (ri === 0 && hasGroundRow && elevation > 0) ? elevation : alt;
                var localRate = thermalRateAtAltitude(climb, maxAlt, thermalBaseAlt, thermAlt);
                if (localRate <= 0) continue;

                var bgColor = thermClimbColor(localRate);
                chartG.append('rect')
                    .attr('x', ci * CELL_W + 1).attr('y', rowY(ri) + 1)
                    .attr('width', CELL_W - 2).attr('height', cellH - 2)
                    .attr('fill', bgColor).attr('rx', 3).attr('opacity', 0.8);

                var thermFontSize = Math.round((isNarrow ? 8 : 10) * Math.min(scale, 1.8));
                chartG.append('text').attr('class', 'therm-value')
                    .attr('x', ci * CELL_W + CELL_W / 2)
                    .attr('y', rowY(ri) + cellH - 4 * scale)
                    .attr('font-size', thermFontSize + 'px')
                    .text(localRate.toFixed(1));

                thermikCells[ri + ',' + ci] = localRate;
            }
        });

        // ===== GRID LINES =====
        // Horizontale Linien an den Top-Kanten jeder Row + Bottom der Ground-Row
        for (var ri2 = 0; ri2 < nRows; ri2++) {
            var lineY = rowY(ri2);
            chartG.append('line').attr('class', 'grid-line')
                .attr('x1', 0).attr('x2', nCols * CELL_W)
                .attr('y1', lineY).attr('y2', lineY);
        }
        chartG.append('line').attr('class', 'grid-line')
            .attr('x1', 0).attr('x2', nCols * CELL_W)
            .attr('y1', gridBottom).attr('y2', gridBottom);
        for (var ci2 = 0; ci2 <= nCols; ci2++) {
            chartG.append('line').attr('class', 'grid-line')
                .attr('x1', ci2 * CELL_W).attr('x2', ci2 * CELL_W)
                .attr('y1', GRID_TOP).attr('y2', gridBottom + TIME_LABEL_H + GROUND_H);
        }

        // (Kein horizontaler Balken — Row 0 Kacheln werden pro Zelle mit
        // Orange-Rahmen versehen, siehe Wind-Cell-Rendering weiter unten.)

        // ===== ALTITUDE LABELS =====
        var altLabelStep = cellH >= 45 ? 250 : 500; // label every 250m when cells are large enough
        var altFontSize = Math.round(11 * Math.min(scale, 1.5));
        altitudes.forEach(function (alt, ri) {
            // Row 0 bei Spots: "★ Start XXXm" statt normale Höhen-Beschriftung.
            // Die Reihe IST der Startplatz (Bodenwind-Werte), darum wird das
            // Row-Label selbst zur Startplatz-Kennzeichnung — das ist klarer
            // als ein separates Label irgendwo anders im Grid.
            if (ri === 0 && hasGroundRow && elevation > 0) {
                chartG.append('text').attr('class', 'axis-label start-label')
                    .attr('x', -8).attr('y', rowY(ri) + cellH / 2)
                    .attr('text-anchor', 'end').attr('dominant-baseline', 'central')
                    .attr('font-size', altFontSize + 'px')
                    .attr('font-weight', '700')
                    .attr('fill', '#C2410C')  // Orange-700
                    .text('\u2605 Start ' + Math.round(elevation) + 'm');
                return;
            }
            if (alt % altLabelStep !== 0) return;
            var displayAlt = alt >= 1000
                ? (alt / 1000).toFixed(alt % 1000 === 0 ? 0 : 1) + 'k'
                : alt.toString();
            chartG.append('text').attr('class', 'axis-label')
                .attr('x', -8).attr('y', rowY(ri) + cellH / 2)
                .attr('text-anchor', 'end').attr('dominant-baseline', 'central')
                .attr('font-size', altFontSize + 'px')
                .text(displayAlt + 'm');
        });

        // ===== TIME LABELS (between grid and ground rows) =====
        times.forEach(function (t, ci) {
            var dt = new Date(t);
            chartG.append('text').attr('class', 'time-label')
                .attr('x', ci * CELL_W + CELL_W / 2)
                .attr('y', gridBottom + TIME_LABEL_H - 6)
                .attr('text-anchor', 'middle')
                .text(dt.getHours() + 'h');
        });

        // ===== WIND ARROWS + VALUES + GUST BARS =====
        var allCells = [];
        for (var ri3 = 0; ri3 < nRows; ri3++) {
            for (var ci3 = 0; ci3 < nCols; ci3++) {
                var d = grid[ri3][ci3];
                if (!d) continue;

                var isGround = (ri3 === 0 && hasGroundRow && d.isGroundRow);
                var rH3 = rowHeight(ri3);
                var cx = ci3 * CELL_W + CELL_W / 2;
                var hasThermik = thermikCells[ri3 + ',' + ci3] != null;
                var cy = rowY(ri3) + rH3 * (hasThermik ? 0.5 : 0.42);
                var speed = d.wind_speed;
                var gusts = d.wind_gusts != null ? d.wind_gusts : speed;
                var gustDiff = gusts - speed;
                var isAloftWarning = !isGround && speed > 35;
                var isGustWarning = gustDiff > 15 && gusts > 30;
                var isGustNotable = gustDiff > 10 && gusts > 25;

                // Ground-Row: Richtungs-Check gegen erlaubte Sektoren
                var isWrongDir = false;
                if (isGround && windSectors && d.wind_direction != null && speed >= 3) {
                    isWrongDir = !isDirInSectors(d.wind_direction, windSectors, 10);
                }
                // Ground-Row: Grundwind zu stark?
                var isGroundStrong = isGround && speed > idealWindMax;

                // Always show gusts
                var showGusts = true;
                // `color` = Pfeil-Farbe. Kann bei falscher Windrichtung (Row 0)
                // auf Rot gesetzt werden — signalisiert: Richtung problematisch.
                var color = (isAloftWarning || isGustWarning) ? '#ef4444' : windColor(speed);
                if (isGround && isWrongDir) color = '#DC2626';  // Pfeil rot bei falscher Richtung
                // `speedColor` = Farbe der Wind-Zahl. Ignoriert Windrichtung —
                // wenn die Stärke selbst harmlos ist (z.B. 12 km/h), bleibt
                // die Zahl grün/neutral. Nur Stärken-Warnungen (Böen, Höhenwind)
                // färben die Zahl rot.
                var speedColor = (isAloftWarning || isGustWarning) ? '#ef4444' : windColor(speed);

                // Background — Ground-Row hat eigene warme Tönung (bereits gezeichnet),
                // hier nur noch Warnfarben-Overlay bei Richtungs-/Stärke-Problemen.
                if (isGround) {
                    var gBgFill = null;
                    if (isWrongDir) gBgFill = 'rgba(220, 38, 38, 0.18)';      // Rot — falsche Richtung
                    else if (isGroundStrong || isGustWarning) gBgFill = 'rgba(239, 68, 68, 0.15)';
                    else if (isGustNotable) gBgFill = 'rgba(249, 115, 22, 0.10)';
                    if (gBgFill) {
                        chartG.append('rect')
                            .attr('x', ci3 * CELL_W + 1).attr('y', rowY(ri3) + 1)
                            .attr('width', CELL_W - 2).attr('height', rH3 - 2)
                            .attr('fill', gBgFill)
                            .attr('rx', 3);
                    }
                    // Orange-Rahmen pro Row-0-Kachel — visuelle Abgrenzung als
                    // "Startplatz-Wind-Zelle" (Card-Effekt). Bei Wrong-Dir
                    // bekommt der Rahmen einen roten Akzent als Warnhinweis.
                    chartG.append('rect').attr('class', 'launch-cell-frame')
                        .attr('x', ci3 * CELL_W + 1).attr('y', rowY(ri3) + 1)
                        .attr('width', CELL_W - 2).attr('height', rH3 - 2)
                        .attr('fill', 'none')
                        .attr('stroke', isWrongDir ? '#DC2626' : '#F97316')  // Rot bei Fehler, sonst Orange-500
                        .attr('stroke-width', isWrongDir ? 2 : 1.5)
                        .attr('rx', 3)
                        .style('pointer-events', 'none');
                } else if (!hasThermik) {
                    var bgFill = windBgColor(speed);
                    if (isGustWarning) bgFill = 'rgba(239, 68, 68, 0.15)';
                    else if (isAloftWarning) bgFill = 'rgba(239, 68, 68, 0.15)';
                    else if (isGustNotable) bgFill = 'rgba(249, 115, 22, 0.08)';
                    chartG.append('rect')
                        .attr('x', ci3 * CELL_W + 1).attr('y', rowY(ri3) + 1)
                        .attr('width', CELL_W - 2).attr('height', rH3 - 2)
                        .attr('fill', bgFill)
                        .attr('rx', 3);
                }

                var arrowScale = Math.min(scale, 1.8);
                var gFilter;
                if (isGround && isWrongDir) {
                    gFilter = 'drop-shadow(0 0 4px rgba(220, 38, 38, 0.8))';
                } else if (isAloftWarning || isGustWarning) {
                    gFilter = 'drop-shadow(0 0 3px rgba(239, 68, 68, 0.7))';
                } else {
                    gFilter = 'drop-shadow(0 1px 2px rgba(0,0,0,0.15))';
                }
                var g = chartG.append('g')
                    .attr('transform', 'translate(' + cx + ', ' + cy + ')')
                    .style('filter', gFilter)
                    .style('opacity', 0);

                g.append('path')
                    .attr('d', arrowPath(speed))
                    .attr('fill', color)
                    .attr('transform', 'rotate(' + ((d.wind_direction + 180) % 360) + ') scale(' + arrowScale + ')');

                // Wind speed + gust number
                // Gust color: red if dangerous, orange if notable, otherwise by absolute gust value
                var gustColor = isGustWarning ? '#ef4444' : (isGustNotable ? '#F97316' : windColor(gusts));
                var windFontSize = Math.round((isNarrow ? 7 : 9) * Math.min(scale, 1.8));
                var windTextY = rowY(ri3) + (hasThermik ? Math.round(10 * scale) : rH3 - Math.round(4 * scale));
                if (showGusts) {
                    // Show wind/gust format: "25/32"
                    var windGustText = chartG.append('text').attr('class', 'wind-value')
                        .attr('x', cx).attr('y', windTextY)
                        .attr('font-size', windFontSize + 'px')
                        .attr('font-weight', (isGround || isGustWarning || isAloftWarning) ? 'bold' : '600')
                        .style('text-shadow', hasThermik ? '0 1px 2px rgba(255,255,255,0.8)' : 'none');
                    // Speed part in wind color (nicht rot bei WrongDir — die
                    // Zahl selbst ist ja nicht gefährlich, nur die Richtung)
                    windGustText.append('tspan').attr('fill', speedColor)
                        .text(Math.round(speed));
                    // Separator
                    windGustText.append('tspan').attr('fill', '#94A3B8')
                        .text('/');
                    // Gust part in graduated color
                    windGustText.append('tspan').attr('fill', gustColor)
                        .text(Math.round(gusts));
                } else {
                    chartG.append('text').attr('class', 'wind-value')
                        .attr('x', cx).attr('y', windTextY)
                        .attr('font-size', windFontSize + 'px').attr('fill', speedColor).attr('opacity', hasThermik ? 1.0 : (isAloftWarning ? 1.0 : 0.7))
                        .attr('font-weight', isAloftWarning ? 'bold' : 'normal')
                        .style('text-shadow', hasThermik ? '0 1px 2px rgba(255,255,255,0.8)' : 'none')
                        .text(Math.round(speed));
                }

                // Böen-/Turbulenz-Strip (vertikaler Farbbalken am rechten Rand).
                // In Row 0 zeigt er Bodenböen (gustDiff = Böen−Wind). In Row 1+
                // zeigt er Turbulenz-Risiko (Gauss-Kernel-Exzess über der Höhe).
                // Bei Row 0 leicht nach innen versetzt, damit Orange-Rahmen
                // der Kachel nicht überdeckt wird.
                var tRisk = d.turbulence_risk != null ? d.turbulence_risk : gusts;
                var tExcess = d.turbulence_excess != null ? d.turbulence_excess : gustDiff;
                if (tExcess > 1) {
                    var stripW = Math.round((isNarrow ? 4 : 6) * Math.min(scale, 1.5));
                    var stripMargin = isGround ? 3 : 1;  // Row 0: mehr Abstand für Orange-Rahmen
                    chartG.append('rect')
                        .attr('x', ci3 * CELL_W + CELL_W - stripW - stripMargin)
                        .attr('y', rowY(ri3) + stripMargin)
                        .attr('width', stripW)
                        .attr('height', rH3 - 2 * stripMargin)
                        .attr('fill', turbulenceColor(tRisk))
                        .attr('opacity', 0.7)
                        .attr('rx', 2);
                }

                allCells.push({ g: g, ci: ci3, ri: ri3 });
            }
        }

        // Entrance animation
        allCells.forEach(function (cell) {
            cell.g.transition().delay(cell.ci * 20 + cell.ri * 3).duration(400)
                .ease(d3.easeCubicOut).style('opacity', 1);
        });

        // ===== GROUND STRIP =====
        var groundY = gridBottom + TIME_LABEL_H;
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
                var gustDiffGround = gusts != null ? gusts - spd : 0;
                var isGustWarning = gusts != null && gustDiffGround > 15 && gusts > 30;
                var isGustNotableGround = gusts != null && gustDiffGround > 10 && gusts > 25;
                var gy = groundY + 13;

                // 1. Gust Shadow (if gusts are significantly higher or for visual depth)
                if (gusts != null && gusts > spd) {
                    var gustShadowColor = isGustWarning ? '#ef4444' : (isGustNotableGround ? '#F97316' : windColor(gusts));
                    var gShadow = chartG.append('g')
                        .attr('transform', 'translate(' + (cx - 15) + ', ' + gy + ')');
                    gShadow.append('path')
                        .attr('d', arrowPath(gusts * 0.7))
                        .attr('fill', gustShadowColor)
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

        // ===== WARNINGS STRIP =====
        // Plain-German hour-range pills below the ground strip.
        if (warnBands.length > 0 && WARN_STRIP_H > 0) {
            var warnTop = groundY + GROUND_H + 4;
            // Row label on the left (only on first row, in muted color)
            chartG.append('text').attr('class', 'ground-label')
                .attr('x', -8).attr('y', warnTop + WARN_ROW_H / 2 + 3)
                .attr('text-anchor', 'end')
                .attr('fill', '#92400E')
                .text('Warnungen');

            warnBands.forEach(function (band) {
                if (band.row < 0) return; // dropped due to row overflow
                var bx = band.start * CELL_W + 1;
                var bw = (band.end - band.start + 1) * CELL_W - 2;
                var by = warnTop + band.row * (WARN_ROW_H + WARN_ROW_GAP);
                var bcx = bx + bw / 2;

                // Pill background
                chartG.append('rect')
                    .attr('x', bx).attr('y', by)
                    .attr('width', bw).attr('height', WARN_ROW_H)
                    .attr('rx', 4)
                    .attr('fill', band.bg)
                    .attr('stroke', band.color)
                    .attr('stroke-width', 0.75)
                    .attr('opacity', 0.95);

                // Label text — auto-shorten if pill too narrow
                var rangeStr = formatHourRange(times, band.start, band.end);
                var fullLabel = band.label + ' ' + rangeStr;
                // Rough fit: ~5.5px per char at 10px font
                var maxChars = Math.floor((bw - 6) / 5.5);
                var displayLabel;
                if (fullLabel.length <= maxChars) {
                    displayLabel = fullLabel;
                } else if (band.label.length + 1 + rangeStr.length <= maxChars) {
                    displayLabel = band.label + ' ' + rangeStr;
                } else if (rangeStr.length + 1 <= maxChars) {
                    // Drop label, keep range visible
                    displayLabel = rangeStr;
                } else {
                    displayLabel = '';
                }

                if (displayLabel) {
                    chartG.append('text')
                        .attr('x', bcx).attr('y', by + WARN_ROW_H / 2 + 3)
                        .attr('text-anchor', 'middle')
                        .attr('font-size', '10px')
                        .attr('font-weight', '600')
                        .attr('fill', band.color)
                        .text(displayLabel);
                }

                // Tooltip on hover (native title, simple + reliable)
                chartG.append('title').text(fullLabel);
            });
        }

        // ===== CROSSHAIR + TOOLTIP =====
        var crossV = chartG.append('line').attr('class', 'crosshair-v')
            .attr('y1', 0).attr('y2', gridBottom + TIME_LABEL_H + GROUND_H + WARN_STRIP_H);
        var crossH = chartG.append('line').attr('class', 'crosshair-h')
            .attr('x1', 0).attr('x2', nCols * CELL_W);

        // Shared tooltip builder for mouse and touch
        function showTooltipAt(coords, clientX, clientY) {
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

            // Row-Detection mit Sonder-Handling für Ground-Row (ri=0) mit extra Höhe
            var ri;
            var groundTop = GRID_TOP + (nRows - 1) * cellH;
            if (hasGroundRow && my >= groundTop && my < gridBottom) {
                ri = 0;
            } else {
                ri = nRows - 1 - Math.floor((my - GRID_TOP) / cellH);
            }
            if (my >= GRID_TOP && ri >= 0 && ri < nRows && grid[ri] && grid[ri][ci]) {
                var dd = grid[ri][ci];
                var isGroundCell = ri === 0 && hasGroundRow && dd.isGroundRow;
                if (isGroundCell) {
                    // Ground-Row Tooltip: Startplatz-fokussierte Infos
                    html += '<div class="tooltip-row" style="margin-top:4px;padding-top:4px;border-top:1px solid #F97316"><span class="tooltip-label" style="color:#C2410C;font-weight:700">\u2605 Startplatz</span><span class="tooltip-value" style="color:#C2410C;font-weight:700">' + Math.round(elevation) + 'm</span></div>';
                    html += '<div class="tooltip-row"><span class="tooltip-label">Bodenwind</span><span class="tooltip-value" style="color:' + windColor(dd.wind_speed) + '">' + Math.round(dd.wind_speed) + ' km/h</span></div>';
                    if (dd.wind_gusts != null && Math.round(dd.wind_gusts) > Math.round(dd.wind_speed)) {
                        html += '<div class="tooltip-row"><span class="tooltip-label">Böen</span><span class="tooltip-value" style="color:' + windColor(dd.wind_gusts) + '">' + Math.round(dd.wind_gusts) + ' km/h</span></div>';
                    }
                    html += '<div class="tooltip-row"><span class="tooltip-label">Richtung</span><span class="tooltip-value">' + Math.round(dd.wind_direction) + '\u00B0</span></div>';
                    if (windSectors && dd.wind_direction != null && dd.wind_speed >= 3) {
                        var dirOk = isDirInSectors(dd.wind_direction, windSectors, 10);
                        html += '<div class="tooltip-row"><span class="tooltip-label">Start-Check</span><span class="tooltip-value" style="color:' + (dirOk ? '#059669' : '#DC2626') + ';font-weight:700">' + (dirOk ? '\u2713 OK' : '\u2715 Falsche Richtung') + '</span></div>';
                    }
                } else {
                    html += '<div class="tooltip-row"><span class="tooltip-label">Hoehe</span><span class="tooltip-value">' + Math.round(dd.altitude) + 'm</span></div>';
                    html += '<div class="tooltip-row"><span class="tooltip-label">Wind</span><span class="tooltip-value" style="color:' + windColor(dd.wind_speed) + '">' + Math.round(dd.wind_speed) + ' km/h</span></div>';
                    var tRiskVal = dd.turbulence_risk != null ? dd.turbulence_risk : dd.wind_gusts;
                    var tExcessVal = dd.turbulence_excess != null ? dd.turbulence_excess : (tRiskVal != null ? tRiskVal - dd.wind_speed : 0);
                    if (tRiskVal != null && Math.round(tRiskVal) > Math.round(dd.wind_speed)) {
                        html += '<div class="tooltip-row"><span class="tooltip-label">Turbulenzrisiko</span><span class="tooltip-value" style="color:' + turbulenceColor(tRiskVal) + '">' + Math.round(tRiskVal) + ' km/h</span></div>';
                        if (tExcessVal > 1) {
                            html += '<div class="tooltip-row"><span class="tooltip-label">Exzess</span><span class="tooltip-value" style="color:' + turbulenceColor(tRiskVal) + '">+' + Math.round(tExcessVal) + ' km/h</span></div>';
                        }
                    }
                    html += '<div class="tooltip-row"><span class="tooltip-label">Richtung</span><span class="tooltip-value">' + Math.round(dd.wind_direction) + '\u00B0 <span style="color:#94A3B8;font-size:10px">(freie Atm.)</span></span></div>';
                    if (dd.temperature != null) {
                        html += '<div class="tooltip-row"><span class="tooltip-label">Temp</span><span class="tooltip-value">' + dd.temperature.toFixed(1) + '\u00B0C</span></div>';
                    }
                    // Thermik rate at this altitude
                    var localThermRate = thermikCells[ri + ',' + ci];
                    if (localThermRate != null && localThermRate > 0) {
                        html += '<div class="tooltip-row"><span class="tooltip-label">Steigrate hier</span><span class="tooltip-value" style="color:' + thermClimbColor(localThermRate) + '">' + localThermRate.toFixed(1) + ' m/s</span></div>';
                    }
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

            var tx = clientX + 16;
            var ty = clientY - 10;
            if (tx + 200 > window.innerWidth) tx = clientX - 200;
            if (ty + 250 > window.innerHeight) ty = clientY - 250;
            tooltipEl.style.left = tx + 'px';
            tooltipEl.style.top = ty + 'px';
        }

        function hideTooltip() {
            crossV.classed('visible', false);
            crossH.classed('visible', false);
            tooltipEl.classList.remove('visible');
        }

        var interactRect = chartG.append('rect')
            .attr('width', nCols * CELL_W)
            .attr('height', gridBottom + TIME_LABEL_H + GROUND_H + WARN_STRIP_H)
            .attr('fill', 'transparent')
            .on('mousemove', function (event) {
                showTooltipAt(d3.pointer(event), event.clientX, event.clientY);
            })
            .on('mouseleave', hideTooltip);

        // Touch support: tap to show, tap elsewhere to hide
        var touchActive = false;
        interactRect.node().addEventListener('touchstart', function (e) {
            e.preventDefault();
            var touch = e.touches[0];
            var coords = d3.pointer(touch, interactRect.node());
            showTooltipAt(coords, touch.clientX, touch.clientY);
            touchActive = true;
        }, { passive: false });
        interactRect.node().addEventListener('touchmove', function (e) {
            if (!touchActive) return;
            var touch = e.touches[0];
            var coords = d3.pointer(touch, interactRect.node());
            showTooltipAt(coords, touch.clientX, touch.clientY);
        }, { passive: true });
        interactRect.node().addEventListener('touchend', function () {
            // Keep tooltip visible after touch; next tap elsewhere will hide
        }, { passive: true });
        document.addEventListener('touchstart', function (e) {
            if (touchActive && !interactRect.node().contains(e.target)) {
                hideTooltip();
                touchActive = false;
            }
        }, { passive: true });
    }

    // ===== TEXT VIEW =====
    // Renders ALL meteogram data as a machine-readable JSON document inside a
    // <pre> block, with stable data-attributes so a browser extension (e.g. the
    // Claude browser extension) can locate and parse the payload to compare
    // forecasts (xctherm, etc.) against Flychat. No information from the
    // graphical meteogram is omitted.
    function renderTextView(container, wxDay, altDay, options) {
        container.innerHTML = '';
        options = options || {};
        var elevation = options.elevation || 0;
        var spotName = options.spotName || '';
        var dateStr = options.dateStr || '';
        var sourceLabel = options.source || 'flychat';

        if (!altDay || !altDay.profiles || altDay.profiles.length === 0) {
            container.innerHTML = '<div class="error-state">Keine Daten fuer diesen Tag.</div>';
            return;
        }

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

        // Build wxByTime lookup
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

        // Numeric rounding helper that preserves nulls
        function num(v, decimals) {
            if (v == null || v === '' || (typeof v === 'number' && isNaN(v))) return null;
            var n = Number(v);
            if (isNaN(n)) return null;
            if (decimals == null) return n;
            var p = Math.pow(10, decimals);
            return Math.round(n * p) / p;
        }

        // Build per-hour structured data
        var hours = profiles.map(function (p) {
            var t = p.time;
            var hh = hourFromTime(t);
            var wx = wxByTime[t] || {};
            var wind = wx.wind || {};
            var precip = wx.precipitation || {};
            var therm = wx.thermik || {};
            var cb = wx.cloudbase || {};

            var wc = precip.weather_code != null ? precip.weather_code
                   : (cb.weather_code != null ? cb.weather_code : null);

            // Sort levels ascending by altitude
            var levels = (p.levels || []).slice().sort(function (a, b) {
                return (a.altitude || 0) - (b.altitude || 0);
            });
            var aloft = levels.map(function (l) {
                return {
                    altitude_m: num(l.altitude, 0),
                    wind_speed_kmh: num(l.wind_speed, 1),
                    wind_gusts_kmh: num(l.wind_gusts != null ? l.wind_gusts : l.wind_speed, 1),
                    wind_direction_deg: num(l.wind_direction, 0),
                    temperature_c: num(l.temperature, 1),
                    pressure_hpa: num(l.pressure, 0),
                    turbulence_risk_kmh: num(l.turbulence_risk, 1),
                    turbulence_excess_kmh: num(l.turbulence_excess, 1)
                };
            });

            return {
                hour: hh,
                time: t,
                surface: {
                    wind_speed_kmh: num(wind.speed, 1),
                    wind_gusts_kmh: num(wind.gusts, 1),
                    wind_direction_deg: num(wind.direction, 0),
                    precipitation_mm: num(precip.amount, 2),
                    weather_code: wc,
                    is_thunderstorm: isThunderstorm(wc),
                    cloud_cover_high_pct: num(cb.cover_high, 0),
                    cloud_cover_mid_pct: num(cb.cover_mid, 0),
                    cloud_cover_low_pct: num(cb.cover_low, 0),
                    cloud_base_m: num(cb.height, 0)
                },
                thermal: {
                    climb_rate_ms: num(therm.climb_rate, 2),
                    max_height_m: num(therm.max_height, 0),
                    rating: num(therm.rating, 1),
                    cape_jkg: num(therm.cape, 0)
                },
                aloft: aloft
            };
        });

        var payload = {
            source: sourceLabel,
            schema_version: 1,
            spot: spotName || null,
            elevation_m: num(elevation, 0),
            date: dateStr || null,
            timezone: 'Europe/Zurich',
            generated_at: new Date().toISOString(),
            units: {
                wind: 'km/h',
                altitude: 'm MSL',
                temperature: 'degC',
                precipitation: 'mm/h',
                climb_rate: 'm/s',
                cape: 'J/kg',
                pressure: 'hPa',
                cloud_cover: 'percent',
                wind_direction: 'deg (meteorological FROM)'
            },
            field_descriptions: {
                'surface.wind_speed_kmh': 'ICON-D2 10m mean wind speed',
                'surface.wind_gusts_kmh': 'Multi-model max gusts (D2/CH1/CH2), bias-corrected',
                'aloft.wind_speed_kmh': 'W(z) - raw ICON-D2 model wind at altitude',
                'aloft.wind_gusts_kmh': 'T(z) - turbulence risk product (W(z) + Gauss-blended excess)',
                'aloft.turbulence_excess_kmh': 'T(z) - W(z), surface gust excess attenuated with altitude',
                'thermal.climb_rate_ms': 'Mean column climb rate',
                'thermal.max_height_m': 'Working ceiling (MSL)',
                'thermal.rating': '0-10 thermal quality score'
            },
            hours: hours
        };

        var jsonStr = JSON.stringify(payload, null, 2);

        // Wrapper
        var wrapper = document.createElement('div');
        wrapper.className = 'mg-text-view';

        // Human-readable header bar
        var header = document.createElement('div');
        header.className = 'mg-text-header';
        var headerParts = [];
        if (spotName) headerParts.push('<strong>' + spotName + '</strong>');
        if (dateStr) headerParts.push(dateStr);
        if (elevation) headerParts.push(Math.round(elevation) + ' m MSL');
        headerParts.push(profiles.length + ' Stunden &middot; ' + (profiles[0].levels || []).length + ' Druckniveaus');
        header.innerHTML = headerParts.join(' &middot; ');
        wrapper.appendChild(header);

        // Action bar with copy button
        var actions = document.createElement('div');
        actions.className = 'mg-text-actions';

        var hint = document.createElement('span');
        hint.className = 'mg-text-hint';
        hint.textContent = 'Maschinenlesbar (JSON) - fuer Browser-Extension / xctherm-Vergleich';
        actions.appendChild(hint);

        var copyBtn = document.createElement('button');
        copyBtn.type = 'button';
        copyBtn.className = 'mg-text-copy-btn';
        copyBtn.textContent = 'JSON kopieren';
        copyBtn.addEventListener('click', function () {
            var done = function () {
                var orig = 'JSON kopieren';
                copyBtn.textContent = 'Kopiert!';
                setTimeout(function () { copyBtn.textContent = orig; }, 1500);
            };
            if (navigator.clipboard && navigator.clipboard.writeText) {
                navigator.clipboard.writeText(jsonStr).then(done, function () {
                    // fallback to legacy selection
                    var sel = window.getSelection();
                    var range = document.createRange();
                    range.selectNodeContents(pre);
                    sel.removeAllRanges();
                    sel.addRange(range);
                });
            } else {
                var sel = window.getSelection();
                var range = document.createRange();
                range.selectNodeContents(pre);
                sel.removeAllRanges();
                sel.addRange(range);
            }
        });
        actions.appendChild(copyBtn);
        wrapper.appendChild(actions);

        // <pre> JSON block — extension reads this via data-flychat-textview="json"
        var pre = document.createElement('pre');
        pre.className = 'mg-text-json';
        pre.setAttribute('data-flychat-textview', 'json');
        pre.setAttribute('data-flychat-source', sourceLabel);
        if (spotName) pre.setAttribute('data-flychat-spot', spotName);
        if (dateStr) pre.setAttribute('data-flychat-date', dateStr);
        pre.setAttribute('data-flychat-hours', String(hours.length));
        pre.textContent = jsonStr;
        wrapper.appendChild(pre);

        container.appendChild(wrapper);
    }

    // ===== ANALYSE VIEW =====
    // Pilot-first decision flow: answers "Can I fly?" immediately, then progressively
    // reveals details. Structure:
    //   Level 1: Decision Hero Banner (safety status — large, unmissable)
    //   Level 2: Best Window Highlight (when to fly)
    //   Level 3: Key Metrics Grid (wind, thermal, flight type)
    //   Level 4: Safety Alerts (NO-GO, caution, foehn)
    //   Level 5: AI Insights (expandable text)
    function renderAnalysisView(container, analysisDay, options) {
        container.innerHTML = '';
        options = options || {};
        var spotName = options.spotName || '';
        var dateStr = options.dateStr || '';

        function esc(str) {
            if (str === null || str === undefined) return '';
            return String(str)
                .replace(/&/g, '&amp;')
                .replace(/</g, '&lt;')
                .replace(/>/g, '&gt;')
                .replace(/"/g, '&quot;')
                .replace(/'/g, '&#39;');
        }
        function normalizeFlyTier(ft) {
            if (!ft) return 'green';
            var k = String(ft).trim().toLowerCase();
            if (k === 'gray' || k === 'green' || k === 'violet') return k;
            if (k === 'yellow') return 'gray';
            if (k === 'orange') return 'green';
            return 'green';
        }
        function parseMaybeList(val) {
            if (!val) return [];
            if (Array.isArray(val)) return val;
            if (typeof val === 'string') {
                try { var p = JSON.parse(val); return Array.isArray(p) ? p : [val]; }
                catch (e) { return [val]; }
            }
            return [];
        }

        // ── Empty state ──
        if (!analysisDay || !analysisDay.safety_status) {
            container.innerHTML = '<div class="mg-analysis-empty">'
                + 'Keine Analyse vorhanden.<br>'
                + '<span style="font-size:12px;margin-top:6px;display:inline-block;">'
                + 'Klicke auf <strong>Analyse starten</strong>, um die KI-Bewertung zu erzeugen.</span>'
                + '</div>';
            return;
        }

        var a = analysisDay;
        var safetyStatus = a.safety_status || 'error';
        var phase2Ok = (safetyStatus === 'safe' || safetyStatus === 'conditional');
        var flyStatus = normalizeFlyTier(a.fly_status || '');
        var noGoReasons = parseMaybeList(a.no_go_reasons);
        var cautionNotes = parseMaybeList(a.caution_notes);

        var wrapper = document.createElement('div');
        wrapper.className = 'mg-analysis-view';
        var html = '';

        // ── Level 1: Decision Hero Banner ──
        var decisionConfig = {
            safe:        { cls: 'safe',    icon: '\u2713', label: 'Fliegbar',     sub: '' },
            conditional: { cls: 'conditional', icon: '!',  label: 'Bedingt fliegbar', sub: 'Einschränkungen beachten' },
            not_safe:    { cls: 'not_safe', icon: '\u2715', label: 'Nicht fliegbar', sub: 'Sicherheitsrisiken vorhanden' },
            no_data:     { cls: 'unknown',  icon: '?',     label: 'Keine Daten',    sub: 'Wetterdaten unvollständig' },
            error:       { cls: 'unknown',  icon: '?',     label: 'Fehler',         sub: esc(a.error || 'Analyse fehlgeschlagen') }
        };
        var dc = decisionConfig[safetyStatus] || decisionConfig.error;

        // For safe/conditional: include fly quality in sub-line
        if (phase2Ok) {
            var flyQualLabels = { gray: 'Soaring / Abgleiter', green: 'Gut fliegbar', violet: 'Hervorragend — XC-Tag' };
            dc.sub = flyQualLabels[flyStatus] || dc.sub;
        }

        html += '<div class="mga-decision ' + dc.cls + '">'
            + '<div class="mga-decision-icon">' + dc.icon + '</div>'
            + '<div class="mga-decision-text">'
            + '<div class="mga-decision-status">' + esc(dc.label) + '</div>';
        if (dc.sub) {
            html += '<div class="mga-decision-sub">' + esc(dc.sub) + '</div>';
        }
        html += '</div>';
        // Fly tier badge (inline, right-side)
        if (phase2Ok) {
            var flyBadgeLabels = { gray: 'Abgleiter', green: 'Thermik', violet: 'XC-Tag' };
            html += '<span class="mga-fly-badge ' + flyStatus + '">'
                + esc(flyBadgeLabels[flyStatus] || flyStatus) + '</span>';
        }
        html += '</div>';

        // Early return for error / no_data
        if (safetyStatus === 'no_data' || safetyStatus === 'error') {
            var feedback = a.safety_feedback || a.summary || '';
            if (feedback) {
                html += '<div style="padding:8px 12px;font-size:12.5px;color:var(--color-text-light);line-height:1.5;">'
                    + esc(feedback) + '</div>';
            }
            wrapper.innerHTML = html;
            container.appendChild(wrapper);
            appendDatestamp();
            return;
        }

        // ── Level 2: Best Window ──
        var window_ = a.safe_window || a.best_window || '';
        if (window_) {
            html += '<div class="mga-window">'
                + '<div>'
                + '<div class="mga-window-label">Bestes Fenster</div>'
                + '<div class="mga-window-time">' + esc(window_) + '</div>'
                + '</div>'
                + '</div>';
        }

        // ── Level 4: Safety & Quality Alerts ──
        var flyabilityLimits = parseMaybeList(a.flyability_limits);
        var highlightNotes = parseMaybeList(a.highlights);
        if (noGoReasons.length > 0 || cautionNotes.length > 0 || flyabilityLimits.length > 0 || highlightNotes.length > 0) {
            html += '<div class="mga-alerts">';
            noGoReasons.forEach(function(r) {
                html += '<div class="mga-alert nogo">'
                    + '<div class="mga-alert-icon">\u2715</div>'
                    + '<div>' + esc(r) + '</div></div>';
            });
            cautionNotes.forEach(function(n) {
                html += '<div class="mga-alert caution">'
                    + '<div class="mga-alert-icon">!</div>'
                    + '<div>' + esc(n) + '</div></div>';
            });
            if (phase2Ok) {
                flyabilityLimits.forEach(function(l) {
                    html += '<div class="mga-alert flyability">'
                        + '<div class="mga-alert-icon">\u2193</div>'
                        + '<div>' + esc(l) + '</div></div>';
                });
                highlightNotes.forEach(function(h) {
                    html += '<div class="mga-alert positive">'
                        + '<div class="mga-alert-icon">\u2713</div>'
                        + '<div>' + esc(h) + '</div></div>';
                });
            }
            html += '</div>';
        }

        // ── Level 3: Key Metrics Grid ──
        html += '<div class="mga-metrics">';

        // Wind — always shown
        html += '<div class="mga-metric full-width">'
            + '<div class="mga-metric-label">Wind</div>'
            + '<div class="mga-metric-value">' + esc(a.wind_summary || '-') + '</div>'
            + '</div>';

        // Flight details (only if flyable)
        if (phase2Ok) {
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
                    + '<div class="mga-insight-body">' + esc(safetyFeedback) + '</div>'
                    + '</div>';
            }
            if (flyFeedback) {
                html += '<div class="mga-insight flyability' + (safetyFeedback ? '' : ' open') + '">'
                    + '<button class="mga-insight-toggle" type="button">Flug-Einschätzung</button>'
                    + '<div class="mga-insight-body">' + esc(flyFeedback) + '</div>'
                    + '</div>';
            }
            html += '</div>';
        }

        wrapper.innerHTML = html;

        // Wire up expandable toggles
        wrapper.querySelectorAll('.mga-insight-toggle').forEach(function(btn) {
            btn.addEventListener('click', function() {
                btn.parentElement.classList.toggle('open');
            });
        });

        container.appendChild(wrapper);
        appendDatestamp();

        function appendDatestamp() {
            if (!dateStr) return;
            var d = document.createElement('div');
            d.className = 'mg-analysis-datestamp';
            d.textContent = 'Analyse: ' + dateStr;
            container.appendChild(d);
        }
    }

    // Public API
    return {
        windColor: windColor,
        arrowPath: arrowPath,
        formatDayTabLabel: formatDayTabLabel,
        buildTabs: buildTabs,
        renderChart: renderChart,
        renderTextView: renderTextView,
        renderAnalysisView: renderAnalysisView
    };
})();
