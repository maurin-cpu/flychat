/**
 * Meteogram - Shared chart rendering module for wind/thermik/cloud visualisation.
 *
 * Usage:
 *   Meteogram.buildTabs(container, dates, onSelectCallback)
 *   Meteogram.renderChart(chartContainer, tooltipEl, weatherDay, altWindDay, options)
 */
window.Meteogram = (function () {
    'use strict';

    // ===== TIER SYSTEM =====
    // Drei Tiers matchen die LLM-Bewertung (_hazard_blocks.md KERNREGEL):
    //   calm     = RUHIG       (Wert unter WARN)
    //   caution  = SPORTLICH   (WARN-Level)
    //   danger   = UNFLIEGBAR  (DANGER-Level)
    // Schwellen kommen aus config.py via /api/weather → options.thresholds.
    // Fallback-Defaults entsprechen config.py-Werten, falls API fehlt.
    var DEFAULT_THRESHOLDS = {
        ground_wind: { warn: 20, danger: 30 },
        ground_gust: { warn: 30, danger: 40 },
        aloft_wind:  { warn: 20, danger: 30 },
        aloft_gust:  { warn: 30, danger: 40 },
    };

    function _th(thresholds, metric) {
        return (thresholds && thresholds[metric]) || DEFAULT_THRESHOLDS[metric];
    }

    function classifyTier(value, metric, thresholds) {
        if (value == null) return 'calm';
        var th = _th(thresholds, metric);
        if (value > th.danger) return 'danger';
        if (value > th.warn) return 'caution';
        return 'calm';
    }

    // Tier visual tokens (mirror style.css --tier-* — keep in sync).
    // Danger: heller Rosa-Fill + dunkler Rotton fuer Text/Pfeil → klare Lesbarkeit
    // (vorher solid red + weisse Zahl war zu schreiend und Wind-Zahl wirkte
    // irrefuehrend "danger" wenn nur Boeen die Schwelle reissen).
    var TIER_STYLES = {
        calm:    { text: '#047857', fill: 'transparent',             frame: '#F97316' },  // frame = existing orange launch-frame
        caution: { text: '#78350F', fill: 'rgba(245, 158, 11, 0.38)', frame: '#D97706' },
        danger:  { text: '#9F1239', fill: 'rgba(225, 29, 72, 0.32)',  frame: '#BE123C' },
    };

    function tierTextColor(tier) { return TIER_STYLES[tier].text; }
    function tierFillColor(tier) { return TIER_STYLES[tier].fill; }
    function tierFrameColor(tier) { return TIER_STYLES[tier].frame; }

    var TIER_LABELS = { calm: 'Ruhig', caution: 'Sportlich', danger: 'Unfliegbar' };
    var TIER_DOTS   = { calm: '#10B981', caution: '#F59E0B', danger: '#E11D48' };

    // Leitet den dominanten Python-Tag-Namen aus Windstaerke/Boee + Schwellen ab.
    // Spiegelt die Logik aus weather_context.py (Ground vs Aloft, Wind vs Gust).
    function deriveDominantTag(isGround, speed, gusts, thresholds) {
        var wind = _th(thresholds, isGround ? 'ground_wind' : 'aloft_wind');
        var gust = _th(thresholds, isGround ? 'ground_gust' : 'aloft_gust');
        var tags = [];
        if (speed != null) {
            if (speed > wind.danger) tags.push({ tier: 'danger', name: isGround ? 'WIND-DANGER' : 'ALOFT-WIND-DANGER' });
            else if (speed > wind.warn) tags.push({ tier: 'caution', name: isGround ? 'WIND-WARN' : 'ALOFT-WIND-WARN' });
        }
        if (gusts != null && gusts > speed) {
            if (gusts > gust.danger) tags.push({ tier: 'danger', name: isGround ? 'GUST-DANGER' : 'ALOFT-GUST-DANGER' });
            else if (gusts > gust.warn) tags.push({ tier: 'caution', name: isGround ? 'GUST-WARN' : 'ALOFT-GUST-WARN' });
        }
        // Schlimmstes Tag gewinnt.
        var ORDER = { calm: 0, caution: 1, danger: 2 };
        tags.sort(function (a, b) { return ORDER[b.tier] - ORDER[a.tier]; });
        return tags.length > 0 ? tags[0] : null;
    }

    // ===== COLOR SCALES (legacy gradient — kept for non-semantic uses) =====
    // Only used for the thermik/cloud/precip strips and the map.js ground-arrow
    // fallback. New cell coloring uses tier functions above.
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

    // Stronger background tint used when numbers are hidden, so the speed
    // is visible from the cell color alone. Steps: ruhig → leicht → mittel → stark.
    function windBgColorStrong(speed) {
        if (speed == null) return 'transparent';
        if (speed <= 5) return '#05966914';   // sehr ruhig (8%)
        if (speed <= 12) return '#10B98126';  // moderat (15%)
        if (speed <= 20) return '#10B98140';  // spürbar (25%)
        if (speed <= 25) return '#D9770655';  // stark (33%)
        if (speed <= 30) return '#EA580C66';  // kräftig (40%)
        return '#DC262680';                   // gefährlich (50%)
    }

    // Read user pref: show numeric wind/gust/thermik labels in cells.
    // Default Mobile = OFF (Übersichtlichkeit, Zellen sonst überladen),
    // Default Desktop = ON (genug Platz fuer alle Werte).
    // Toggle in der Tier-Legend kann auf Mobile auf ON stellen.
    // Storage-Werte: '1' = on, '0' = off, null/missing = viewport-default.
    function readShowNumbers() {
        try {
            var v = localStorage.getItem('gleitcast.meteogram.showNumbers');
            if (v === '1') return true;
            if (v === '0') return false;
            return window.innerWidth > 640; // Mobile default OFF, Desktop ON
        } catch (e) { return window.innerWidth > 640; }
    }
    function writeShowNumbers(on) {
        try { localStorage.setItem('gleitcast.meteogram.showNumbers', on ? '1' : '0'); }
        catch (e) { /* ignore */ }
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

    // Parabolic thermal profile: local climb rate at a given altitude.
    // Flyability cap: above LCL (cloud base) is VFR-illegal / not flyable, so return 0.
    function thermalRateAtAltitude(climbRate, maxHeight, elevation, altitude, lcl) {
        if (altitude < elevation || altitude >= maxHeight || climbRate <= 0) return 0;
        if (lcl && altitude >= lcl) return 0;
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
    var MARGIN = { top: 12, right: 24, bottom: 0, left: (window.innerWidth <= 480) ? 72 : 96 };
    var CELL_H = 36;
    // Bodenstrip: 3 Rows mit unterschiedlicher Höhe — Wind (24), Böen (16,
    // schmale "Linie" unter dem Wind), Thermik (24). Wind und Böen sind klar
    // getrennt damit der Pilot sieht: Mittelwind vs. Spitzenwerte.
    // Temperatur weggelassen (fürs Fliegen irrelevant), Niederschlag ist im
    // Cloud-Strip oben (Tropfen + Gewitter-Icons).
    const GROUND_WIND_H = 24;
    const GROUND_GUST_H = 16;
    const GROUND_THERM_H = 24;
    const GROUND_H = GROUND_WIND_H + GROUND_GUST_H + GROUND_THERM_H;
    // Y-Offsets relativ zum groundY-Top.
    const GROUND_WIND_Y = 0;
    const GROUND_GUST_Y = GROUND_WIND_H;            // 24
    const GROUND_THERM_Y = GROUND_WIND_H + GROUND_GUST_H; // 40
    const TIME_LABEL_H = 28;
    const CLOUD_ROW_H = 18;
    const PRECIP_ROW_H = 20;
    const CLOUD_STRIP_H = 3 * CLOUD_ROW_H + PRECIP_ROW_H; // CH, CM, CL + Niederschlag/Gewitter
    const CLOUD_GAP = 6;
    // Warnings strip: small pills under the ground section summarising hour-ranges
    // Warn-Pills sollen schmal bleiben — bei vielen Warnungen kann der Strip
    // sonst >80px hoch werden und das Meteogramm wegdrücken.
    // Cap bei MAX_WARN_ROWS Reihen; alle weiteren Warnungen werden in der
    // letzten Reihe als "+N weitere" Indikator am rechten Rand zusammengefasst.
    const WARN_ROW_H = 13;
    const WARN_ROW_GAP = 1;
    const MAX_WARN_ROWS = 4;

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

    /** Two-line layout (day-name + DD.MM) — matches floating-day-tabs. */
    function formatDayTabParts(dateStr) {
        var d = new Date(dateStr + 'T12:00:00');
        var dayNames = ['SO', 'MO', 'DI', 'MI', 'DO', 'FR', 'SA'];
        var dd = String(d.getDate()).padStart(2, '0');
        var mm = String(d.getMonth() + 1).padStart(2, '0');
        return { name: dayNames[d.getDay()], date: dd + '.' + mm };
    }

    // ===== TABS =====
    function buildTabs(container, dates, onSelect) {
        container.innerHTML = '';
        dates.forEach(function (d, idx) {
            var parts = formatDayTabParts(d);
            var btn = document.createElement('button');
            btn.className = 'tab-btn' + (idx === 0 ? ' active' : '');
            btn.dataset.date = d;
            btn.innerHTML = '<span class="day-name">' + parts.name + '</span><span class="day-date">' + parts.date + '</span>';
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
        // Mobile: 500m-Steps statt 250m → halbiert Reihenanzahl, Pfeile bleiben
        // gross genug für Touch + lesbare Schrift, ohne dass das Chart vertikal
        // scrollen muss.
        // Desktop-Overlay (fitToContainer) auf KLEINEN Bildschirmen (< 950px Höhe,
        // typisch 13"/14" Laptops): ebenfalls 500m-Schritte. Granularität opfern
        // für Sichtbarkeit ist UX-konform (data-density: gröbere Skala statt
        // Scroll). Auf >=950px Höhe bleibt Desktop bei 250m-Auflösung.
        var _isMobile_local = window.innerWidth <= 640;
        var _fitToContainer_local = !!(options && options.fitToContainer);
        var _smallDesktop = !_isMobile_local && _fitToContainer_local && window.innerHeight < 950;
        var _useCoarse = _isMobile_local || _smallDesktop;
        var STEP = _useCoarse ? 500 : 250;
        var FULL_ROWS = _useCoarse ? 9 : 17; // 0-4000m: 9 rows @ 500m, 17 rows @ 250m
        var elevation = (options && options.elevation) || 0;
        var minGridAlt = Math.floor(elevation / STEP) * STEP;
        // Alpine zones (≥1800m, entspricht Terrain-Faktor 1.0) brauchen mehr Headroom
        // Coarse-Mode: deckeln auf elevation + 3000m (deckt 95% der Flüge ab);
        // Fine-Mode (großer Desktop): bleibt bei 4000-5000m absolut.
        var maxGridAlt;
        if (_useCoarse) {
            maxGridAlt = Math.min(elevation >= 1800 ? 5000 : 4000, minGridAlt + 3000);
        } else {
            maxGridAlt = elevation >= 1800 ? 5000 : 4000;
        }
        var altitudes = [];
        for (var a = minGridAlt; a <= maxGridAlt; a += STEP) altitudes.push(a);
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
        // Numbers toggle (mobile only): when off, wind/gust digits in cells are
        // hidden and speed is encoded as cell background tint. The toggle pill
        // above the chart flips this preference (persisted in localStorage).
        // Desktop (>640px) keeps the original layout — Zahlen immer an.
        var isMobileViewport = window.innerWidth <= 640;
        var showNumbers = (options && typeof options.showNumbers === 'boolean')
            ? options.showNumbers : readShowNumbers();
        if (!isMobileViewport) showNumbers = true;

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
        // Desktop bleibt unverändert (Original-Layout). Auf Mobile: Chart
        // passt IMMER in den Container — kein horizontaler Scroll, egal ob
        // Zahlen an oder aus. Numbers werden bei Bedarf kleiner gerendert.
        var isNarrowScreen = window.innerWidth <= 480;
        // Mobile-Margin: 72px reicht für die längsten linken Labels
        // ("Nied./Gew.", "Warnungen") bei 9-11px Schrift ohne Clipping.
        // Mobile-Margin: Höhenzahlen ("1.5km") brauchen ~32px, Icons (14px breit)
        // sitzen rechtsbündig wie die Höhenzahlen → nutzen denselben Bereich.
        // 44px reicht für beides ohne Konflikt und gibt 28px ans Chart zurück.
        MARGIN.left = isMobileViewport ? 44 : 96;
        MARGIN.right = isMobileViewport ? 12 : 24;
        // clientWidth kann während Layout-Race 0 sein → safer fallback aus
        // Viewport-Breite, damit das Chart NIE die Mobile-Viewport sprengt.
        var safeFallback = isMobileViewport
            ? Math.max(240, window.innerWidth - 32)
            : 800;
        var panelWidth = container.clientWidth || safeFallback;
        if (isMobileViewport) {
            // Hard-Cap an Viewport: niemals breiter als Bildschirm minus Body-Padding.
            panelWidth = Math.min(panelWidth, window.innerWidth - 24);
        }
        // Mobile + fitToContainer (Desktop-Overlay): nie breiter als Container —
        // kein horizontaler Scroll. Inline-Briefing/Chat (kein fitToContainer):
        // Original-Floor 40px pro Zelle (kann breiter als Container werden).
        var _fitW = !!(options && options.fitToContainer);
        var minCellW = (isMobileViewport || _fitW) ? 0 : 40;
        var minChartW = MARGIN.left + nCols * minCellW + MARGIN.right;
        var chartW = (isMobileViewport || _fitW) ? panelWidth : Math.max(panelWidth, minChartW);
        var CELL_W = (chartW - MARGIN.left - MARGIN.right) / nCols;
        var isNarrow = CELL_W < 36;

        // ===== COMPUTE PLAIN-LANGUAGE WARNING BANDS =====
        // These are grouped hour-ranges (ci..ci) used later to draw pills
        // BELOW the ground strip in plain German.
        // elevation already extracted above for altitude grid filtering
        var windSectors = parseWindDirection(options.windrichtung || '');
        var idealWindMax = options.idealWindMax || 30;
        var thresholds = options.thresholds || DEFAULT_THRESHOLDS;

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
            // Schwellen aus thresholds-API (config.WIND_*_KMH / GUST_*_KMH).
            if (profile && profile.levels && elevation > 0) {
                var topLimit = (thermik.max_height || (elevation + 2000)) + 1000;
                var aloftWindTh = _th(thresholds, 'aloft_wind');
                var aloftGustTh = _th(thresholds, 'aloft_gust');
                for (var li = 0; li < profile.levels.length; li++) {
                    var lv = profile.levels[li];
                    if (lv == null || lv.altitude == null) continue;
                    if (lv.altitude < elevation || lv.altitude > topLimit) continue;
                    var wsA = lv.wind_speed;
                    var wgA = lv.wind_gusts != null ? lv.wind_gusts : wsA;
                    if (wsA != null) {
                        if (wsA > aloftWindTh.danger) f.aloftDanger = true;
                        else if (wsA > aloftWindTh.warn) f.aloftWarn = true;
                    }
                    if (wgA != null) {
                        if (wgA > aloftGustTh.danger) f.aloftGustDanger = true;
                        else if (wgA > aloftGustTh.warn) f.aloftGustWarn = true;
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

        // Row-pack (greedy) so non-overlapping bands share a row.
        // Cap bei MAX_WARN_ROWS Reihen — alle weiteren Warnungen werden NICHT
        // gerendert, sondern als "+N weitere" Overflow-Pill in der letzten
        // Reihe rechts ausserhalb der Daten zusammengefasst (Tooltip listet
        // alle gedroppten Warnings auf).
        warnBands.forEach(function (b) { b.row = -1; });
        var rowLastEnd = []; // rowLastEnd[row] = last end col used
        var droppedWarns = []; // bands die nicht in MAX_WARN_ROWS passen
        warnBands.forEach(function (b) {
            var r = 0;
            while (rowLastEnd[r] != null && rowLastEnd[r] >= b.start) {
                r++;
            }
            if (r >= MAX_WARN_ROWS) {
                droppedWarns.push(b);
                return; // b.row bleibt -1 → wird beim Render uebersprungen
            }
            b.row = r;
            rowLastEnd[r] = b.end;
        });
        var usedRows = rowLastEnd.length;
        var WARN_STRIP_H = usedRows > 0 ? (usedRows * (WARN_ROW_H + WARN_ROW_GAP) + 4) : 0;

        var chartH = MARGIN.top + CLOUD_STRIP_H + CLOUD_GAP + nRows * cellH + TIME_LABEL_H + GROUND_H + WARN_STRIP_H + 8;

        // COMPACT-FIT: Chart MUSS in den verfügbaren Container passen — KEIN
        // Scroll. Strategie: cellH schrumpfen so weit nötig.
        // - Mobile: immer aktiv (Floor 18px für Touch-Lesbarkeit).
        // - Desktop-Overlay (fitToContainer): kein Floor — Chart MUSS reinpassen,
        //   kleinere Schrift > Scroll-Frust. Skaliert automatisch via `scale`.
        //   Inline-Briefing/Chat-Charts (kein fitToContainer): unverändert.
        // Reserve = Tier-Legend-Bar (Mobile: 60 mit Toggle; Desktop: 40)
        //         + .meteogram-chart Wrapper-Padding (Mobile 16, Desktop 24)
        //         + Sicherheits-Puffer.
        var fitToContainer = !!(options && options.fitToContainer);
        if (isMobileViewport || fitToContainer) {
            var containerH = container.clientHeight || 0;
            if (containerH < 100) {
                containerH = isMobileViewport
                    ? Math.max(280, window.innerHeight - 200)
                    : Math.max(400, window.innerHeight - 200);
            }
            var legendReserve = isMobileViewport ? 60 : 40;
            var chartPaddingReserve = isMobileViewport ? 16 : 24;
            // weather-ts: Modell + Wetter-Stand wird vom Caller (map.js) UNTER
            // das SVG appended (~14px Höhe inkl. padding). Muss in die Reserve
            // damit der Footer-Text nicht aus dem Container scrollt.
            var weatherTsReserve = 16;
            var safetyMargin = isMobileViewport ? 6 : 8;
            var availableH = containerH - legendReserve - chartPaddingReserve - weatherTsReserve - safetyMargin;
            if (chartH > availableH) {
                var fixedH = MARGIN.top + CLOUD_STRIP_H + CLOUD_GAP + TIME_LABEL_H + GROUND_H + WARN_STRIP_H + 8;
                var availForRows = Math.max(0, availableH - fixedH);
                // Mobile: Floor 18 (Touch-Hit-Area). Desktop-Overlay: kein Floor —
                // muss IMMER reinpassen, lieber kleine Schrift als Scroll.
                var minCellHFloor = isMobileViewport ? 18 : 1;
                var newCellH = Math.max(minCellHFloor, Math.floor(availForRows / Math.max(1, nRows)));
                if (newCellH < cellH) {
                    cellH = newCellH;
                    scale = cellH / CELL_H; // proportional, kein Floor — Schrift schrumpft mit
                    chartH = MARGIN.top + CLOUD_STRIP_H + CLOUD_GAP + nRows * cellH + TIME_LABEL_H + GROUND_H + WARN_STRIP_H + 8;
                }
            }
        }

        // ===== TIER LEGEND (Pill-Chips) =====
        // 3 Pills zeigen die Bedeutung der Zell-Farben. Bleibt immer sichtbar,
        // damit der Pilot die Logik auf einen Blick versteht.
        // Während Scrubbing (Mobile) wird der Legenden-Inhalt durch eine
        // Info-Zeile überlagert (gleiche Höhe → kein Layout-Shift).
        var legendBar = document.createElement('div');
        legendBar.className = 'mg-tier-legend';
        legendBar.setAttribute('aria-label', 'Farb-Legende: Ruhig, Sportlich, Unfliegbar');

        var legendContent = document.createElement('div');
        legendContent.className = 'mg-legend-content';
        [
            { tier: 'calm',    label: 'Ruhig',     color: '#10B981' },
            { tier: 'caution', label: 'Sportlich', color: '#F59E0B' },
            { tier: 'danger',  label: 'Unfliegbar', color: '#E11D48' },
        ].forEach(function (entry) {
            var pill = document.createElement('span');
            pill.className = 'mg-tier-pill mg-tier-' + entry.tier;
            var dot = document.createElement('span');
            dot.className = 'mg-tier-dot';
            dot.style.background = entry.color;
            pill.appendChild(dot);
            pill.appendChild(document.createTextNode(entry.label));
            legendContent.appendChild(pill);
        });
        legendBar.appendChild(legendContent);

        // Numbers-Toggle: erlaubt Wind/Böe/Therm-Zahlen ein/aus zu schalten.
        // Touch-Target 44×44 (HIG-Standard), aria-pressed-State für Screen-Reader.
        // Re-Render via existierendem options.showNumbers-Override, damit der
        // Wert sofort wirkt ohne Page-Reload. Nur auf Mobile sichtbar — Desktop
        // hat breite Zellen ohne Crowding-Risiko und forciert Zahlen ohnehin.
        if (isMobileViewport) {
        var toggleBtn = document.createElement('button');
        toggleBtn.type = 'button';
        toggleBtn.className = 'mg-numbers-toggle';
        toggleBtn.setAttribute('aria-label', showNumbers ? 'Zahlen ausblenden' : 'Zahlen einblenden');
        toggleBtn.setAttribute('aria-pressed', showNumbers ? 'true' : 'false');
        toggleBtn.title = showNumbers ? 'Zahlen ausblenden' : 'Zahlen einblenden';
        toggleBtn.innerHTML =
            '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">' +
            '<text x="12" y="16" text-anchor="middle" font-family="Inter,sans-serif" font-size="13" font-weight="700" stroke="none" fill="currentColor">123</text>' +
            (showNumbers ? '' : '<line x1="4" y1="20" x2="20" y2="4" stroke-width="2.4"/>') +
            '</svg>';
        if (!showNumbers) toggleBtn.classList.add('mg-numbers-toggle--off');
        toggleBtn.addEventListener('click', function (e) {
            e.preventDefault();
            var next = !showNumbers;
            writeShowNumbers(next);
            // Re-Render mit neuer Pref. Container/altDay/wxDay/options bleiben gleich,
            // nur showNumbers-Override wird gesetzt.
            var nextOpts = Object.assign({}, options, { showNumbers: next });
            renderChart(container, tooltipEl, wxDay, altDay, nextOpts);
        });
        legendContent.appendChild(toggleBtn);
        } // end if (isMobileViewport)

        // Scrubber-Info: überlagert die Legende während Touch-Drag, damit der
        // Pilot Werte sieht, OHNE den Finger zu heben oder eine Zelle exakt zu
        // treffen. Im Ruhezustand opacity:0, pointer-events:none.
        var scrubInfo = null;
        if (isMobileViewport) {
            scrubInfo = document.createElement('div');
            scrubInfo.className = 'mg-scrub-info';
            scrubInfo.setAttribute('aria-live', 'polite');
            scrubInfo.innerHTML =
                '<span class="mg-scrub-time">--:--</span>' +
                '<span class="mg-scrub-divider">·</span>' +
                '<span class="mg-scrub-vals">ziehe zum Lesen</span>';
            legendBar.appendChild(scrubInfo);
        }

        container.appendChild(legendBar);

        var svg = d3.select(container)
            .append('svg')
            .attr('width', chartW)
            .attr('height', chartH)
            .style('display', 'block');

        var chartG = svg.append('g')
            .attr('transform', 'translate(' + MARGIN.left + ', ' + MARGIN.top + ')');

        // ===== LEFT-AXIS ICONS (Mobile only) =====
        // Auf Mobile ersetzen wir die Text-Labels (Hoch/Mittel/Tief, Nied./Gew.,
        // Wind/Therm, Warnungen) durch kleine SVG-Icons. Spart Platz, Höhenzahlen
        // bleiben unverändert. Right-edge bei x=-8 (matched mit text-anchor='end').
        var ICON_W = 14;
        var ICON_RIGHT = -8;
        var ICON_LEFT = ICON_RIGHT - ICON_W;
        function appendLeftIcon(yCenter, render) {
            var x = ICON_LEFT;
            var y = yCenter - ICON_W / 2;
            var s = ICON_W / 24;
            var g = chartG.append('g')
                .attr('transform', 'translate(' + x + ',' + y + ') scale(' + s + ')');
            render(g);
            return g;
        }
        // Cloud-Silhouette als Pfad in 24×24-viewBox.
        var CLOUD_PATH = 'M 5 18 a 4 4 0 0 1 0 -8 a 5 5 0 0 1 9 -2 a 4 4 0 0 1 7 4 a 3 3 0 0 1 -1 6 H 5 z';
        function drawCloudIcon(g, baseColor, density) {
            // density: 0.3 = high (outline, sehr leicht), 0.6 = mid, 1.0 = low (gefüllt)
            g.append('path')
                .attr('d', CLOUD_PATH)
                .attr('fill', density >= 0.9 ? baseColor : baseColor)
                .attr('fill-opacity', density >= 0.9 ? 0.95 : (density >= 0.5 ? 0.45 : 0.0))
                .attr('stroke', baseColor)
                .attr('stroke-width', 1.6)
                .attr('stroke-linejoin', 'round');
        }
        function drawDropLightningIcon(g) {
            // Klassisches Wetter-Icon: Gewitterwolke mit Blitz UND Regen-Tropfen.
            // Wolke oben, darunter zentral der Blitz, links/rechts daneben je
            // ein Tropfen — Apple-Wetter "Thunderstorm with Rain"-Layout.
            // Wolke (oben, hellgrau gefüllt mit dunkler Outline):
            g.append('path')
                .attr('d', 'M 4 11 a 4 4 0 0 1 0 -7 a 4.5 4.5 0 0 1 8 -1.5 a 3.5 3.5 0 0 1 6 3 a 2.8 2.8 0 0 1 1 5.5 H 4 z')
                .attr('fill', '#94A3B8').attr('fill-opacity', 0.95)
                .attr('stroke', '#475569').attr('stroke-width', 1.2)
                .attr('stroke-linejoin', 'round');
            // Tropfen links (kleines Teardrop):
            g.append('path')
                .attr('d', 'M 5 12.5 C 3.7 14 3.7 16.5 5 17.8 C 6.3 16.5 6.3 14 5 12.5 Z')
                .attr('fill', '#3B82F6').attr('stroke', '#1E40AF')
                .attr('stroke-width', 0.7).attr('stroke-linejoin', 'round');
            // Tropfen rechts:
            g.append('path')
                .attr('d', 'M 20 12.5 C 18.7 14 18.7 16.5 20 17.8 C 21.3 16.5 21.3 14 20 12.5 Z')
                .attr('fill', '#3B82F6').attr('stroke', '#1E40AF')
                .attr('stroke-width', 0.7).attr('stroke-linejoin', 'round');
            // Blitz zentral (kompakter, damit Tropfen Platz haben):
            g.append('path')
                .attr('d', 'M 12 11 L 9 17 L 11.5 17 L 10.5 22 L 14 16 L 11.5 16 Z')
                .attr('fill', '#FBBF24').attr('stroke', '#92400E')
                .attr('stroke-width', 0.9).attr('stroke-linejoin', 'round')
                .attr('stroke-linecap', 'round');
        }
        // Wind/Böen/Thermik nutzen Mini-Text-Labels statt Icons — Glyphs für
        // diese Konzepte waren nicht eindeutig genug (Pfeil-mit-Welle = Therm
        // oder Wind? Spike = Böe oder Stromschlag?). Text ist klarer.
        function drawWarnIcon(g) {
            // Klassisches Warndreieck mit Ausrufezeichen.
            g.append('path')
                .attr('d', 'M12 3 L 22 21 L 2 21 Z')
                .attr('fill', '#FEF3C7').attr('stroke', '#92400E')
                .attr('stroke-width', 1.8).attr('stroke-linejoin', 'round');
            g.append('path')
                .attr('d', 'M12 10 V 16')
                .attr('stroke', '#92400E').attr('stroke-width', 2)
                .attr('stroke-linecap', 'round');
            g.append('circle')
                .attr('cx', 12).attr('cy', 19).attr('r', 1)
                .attr('fill', '#92400E');
        }

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

        // Legend / Labels for cloud types on the left.
        // Mobile: Cloud-Icons mit Dichte-Variation (Hoch=outline, Mittel=halb,
        // Tief=gefüllt) — selbsterklärend, spart Platz.
        // Desktop: klassische Text-Labels.
        cloudLayers.forEach(function (layer, li) {
            var rowYCenter = li * CLOUD_ROW_H + CLOUD_ROW_H / 2;
            if (isMobileViewport) {
                // density: hoch=0.3 (nur Outline), mittel=0.6 (halb), tief=1.0 (full)
                var density = li === 0 ? 0.3 : li === 1 ? 0.6 : 1.0;
                appendLeftIcon(rowYCenter, function (g) {
                    drawCloudIcon(g, layer.baseColor, density);
                });
            } else {
                chartG.append('text').attr('class', 'axis-label')
                    .attr('x', -8)
                    .attr('y', rowYCenter)
                    .attr('text-anchor', 'end').attr('dominant-baseline', 'central')
                    .attr('font-size', '9px').attr('font-weight', '600')
                    .attr('fill', '#64748B')
                    .text(layer.label);
            }

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
                
                // Overlay small percentage with high contrast text.
                // Auf Mobile ueber den showNumbers-Toggle steuerbar (gleich wie
                // Wind/Thermik im Hoehengrid). Desktop: showNumbers ist immer
                // true → Verhalten unveraendert.
                if (showNumbers && cover > 20 && CELL_W > 16) {
                    var isDark = (cover > 70 && li >= 1); // Darker layers with high cover
                    var cloudFontSize = isMobileViewport ? '8px' : '9px';
                    chartG.append('text')
                        .attr('x', ci * CELL_W + CELL_W / 2)
                        .attr('y', rowY + CLOUD_ROW_H / 2 + 1)
                        .attr('text-anchor', 'middle').attr('dominant-baseline', 'central')
                        .attr('font-size', cloudFontSize).attr('font-weight', '700')
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
        if (isMobileViewport) {
            appendLeftIcon(precipRowY + PRECIP_ROW_H / 2, drawDropLightningIcon);
        } else {
            chartG.append('text').attr('class', 'axis-label')
                .attr('x', -8)
                .attr('y', precipRowY + PRECIP_ROW_H / 2)
                .attr('text-anchor', 'end').attr('dominant-baseline', 'central')
                .attr('font-size', '9px').attr('font-weight', '600')
                .attr('fill', '#64748B')
                .text('Nied./Gew.');
        }
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

            if (isMobileViewport) {
                // Mobile: keine Zahlen — Icons zentriert. Regen als Tropfen,
                // Gewitter als Blitz. Beide selbst gezeichnet (SVG path), damit
                // sie schriftunabhängig sauber rendern.
                var iconSize = Math.min(14, PRECIP_ROW_H - 4);
                var iconY = precipRowY + (PRECIP_ROW_H - iconSize) / 2;
                var iconScale = iconSize / 24;
                if (hasStorm) {
                    // Klassischer Blitz-Pfad in viewBox 24x24.
                    var boltX = cx - iconSize * 0.32;
                    chartG.append('path')
                        .attr('d', 'M13 2 L4 14 L11 14 L9 22 L20 10 L13 10 Z')
                        .attr('transform', 'translate(' + boltX + ',' + iconY + ') scale(' + iconScale + ')')
                        .attr('fill', '#92400E')
                        .attr('stroke', '#FBBF24')
                        .attr('stroke-width', 0.8 / iconScale)
                        .attr('stroke-linejoin', 'round');
                } else if (hasPrecip) {
                    // Tropfen-Pfad: Spitze oben (12,2), Kreisboden unten.
                    // Bezier-Kurven formen die klassische Tropfen-Silhouette.
                    var dropX = cx - iconSize * 0.5;
                    var dropColor = precipAmt >= 3 ? '#1D4ED8' : precipAmt >= 1 ? '#2563EB' : '#3B82F6';
                    chartG.append('path')
                        .attr('d', 'M12 2 C12 2 4 12 4 16 C4 20 7.5 22 12 22 C16.5 22 20 20 20 16 C20 12 12 2 12 2 Z')
                        .attr('transform', 'translate(' + dropX + ',' + iconY + ') scale(' + iconScale + ')')
                        .attr('fill', dropColor)
                        .attr('stroke', '#DBEAFE')
                        .attr('stroke-width', 0.8 / iconScale)
                        .attr('stroke-linejoin', 'round');
                }
            } else {
                // Desktop: Self-gezeichnete Icons (gleich wie Mobile) + mm-Wert
                // daneben — kein Emoji-⚡ mehr (no-emoji-icons Regel).
                // Layout: icon links, text rechts, gemeinsam zentriert.
                var dIconSize = 12;
                var dIconY = precipRowY + (PRECIP_ROW_H - dIconSize) / 2;
                var dIconScale = dIconSize / 24;
                var dText = hasPrecip ? precipAmt.toFixed(1) + ' mm' : '';
                var dGap = dText ? 3 : 0;
                // Approx. Textbreite (font 11px, ~6.2px/char).
                var dTextW = dText.length * 6.2;
                var dTotalW = dIconSize + dGap + dTextW;
                var dStartX = cx - dTotalW / 2;
                var dIconX = dStartX;
                var dTextX = dStartX + dIconSize + dGap;

                if (hasStorm) {
                    // Blitz (gleicher Pfad wie Mobile).
                    chartG.append('path')
                        .attr('d', 'M13 2 L4 14 L11 14 L9 22 L20 10 L13 10 Z')
                        .attr('transform', 'translate(' + dIconX + ',' + dIconY + ') scale(' + dIconScale + ')')
                        .attr('fill', '#92400E')
                        .attr('stroke', '#FBBF24')
                        .attr('stroke-width', 0.8 / dIconScale)
                        .attr('stroke-linejoin', 'round');
                } else {
                    // Tropfen (gleicher Pfad wie Mobile).
                    var dDropColor = precipAmt >= 3 ? '#1D4ED8' : precipAmt >= 1 ? '#2563EB' : '#3B82F6';
                    chartG.append('path')
                        .attr('d', 'M12 2 C12 2 4 12 4 16 C4 20 7.5 22 12 22 C16.5 22 20 20 20 16 C20 12 12 2 12 2 Z')
                        .attr('transform', 'translate(' + dIconX + ',' + dIconY + ') scale(' + dIconScale + ')')
                        .attr('fill', dDropColor)
                        .attr('stroke', '#DBEAFE')
                        .attr('stroke-width', 0.8 / dIconScale)
                        .attr('stroke-linejoin', 'round');
                }

                if (dText) {
                    chartG.append('text')
                        .attr('x', dTextX)
                        .attr('y', precipRowY + PRECIP_ROW_H / 2 + 1)
                        .attr('text-anchor', 'start').attr('dominant-baseline', 'central')
                        .attr('font-size', '11px').attr('font-weight', '700')
                        .attr('fill', hasStorm ? '#92400E' : '#1E3A5F')
                        .text(dText);
                }
            }
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
            var lclAlt = wx.thermik.lcl || null;  // Wolkenbasis (MSL), ab hier VFR nicht mehr fliegbar

            for (var ri = 0; ri < nRows; ri++) {
                var alt = altitudes[ri];
                // Row 0 bei Spots = Startplatz-Kachel. Verwende `elevation` für
                // die Thermik-Berechnung (statt altitudes[0]=minGridAlt=1000m
                // bei elevation=1228m), damit die Startplatz-Kachel die
                // Thermik ab Boden zeigt — nicht "unter Startplatz = keine Thermik".
                var thermAlt = (ri === 0 && hasGroundRow && elevation > 0) ? elevation : alt;
                var localRate = thermalRateAtAltitude(climb, maxAlt, thermalBaseAlt, thermAlt, lclAlt);
                if (localRate <= 0) continue;

                var bgColor = thermClimbColor(localRate);
                chartG.append('rect')
                    .attr('x', ci * CELL_W + 1).attr('y', rowY(ri) + 1)
                    .attr('width', CELL_W - 2).attr('height', cellH - 2)
                    .attr('fill', bgColor).attr('rx', 3).attr('opacity', 0.8);

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
        // Typographie = Scope-Indikator fuer LLM-Rating-Zone (siehe _input_map.md).
        // Flugbereich = Spot bis max_thermal_height + 1000m (Lid-Zone inklusive).
        // Puffer      = +500m drueber.
        // Ueber Puffer = rein informativ — LLM bewertet nicht.
        var peakThermikMaxH = 0;
        if (wxDay && wxDay.thermik) {
            wxDay.thermik.forEach(function (t) {
                if (t.max_height && t.max_height > peakThermikMaxH) peakThermikMaxH = t.max_height;
            });
        }
        var flightCeiling = peakThermikMaxH > 0 ? peakThermikMaxH + 1000 : elevation + 2000;
        var bufferTop = flightCeiling + 500;
        var altLabelStep = cellH >= 45 ? 250 : 500;
        var altFontSize = Math.round(11 * Math.min(scale, 1.5));
        altitudes.forEach(function (alt, ri) {
            if (ri === 0 && hasGroundRow && elevation > 0) {
                // Mobile: kompakte Form ohne "Start"-Wort, sonst wird abgeschnitten.
                var startLabel = isMobileViewport
                    ? '\u2605 ' + (elevation >= 1000
                        ? (elevation / 1000).toFixed(elevation % 1000 === 0 ? 0 : 1) + 'k'
                        : Math.round(elevation) + 'm')
                    : '\u2605 Start ' + Math.round(elevation) + 'm';
                chartG.append('text').attr('class', 'axis-label start-label')
                    .attr('x', -8).attr('y', rowY(ri) + cellH / 2)
                    .attr('text-anchor', 'end').attr('dominant-baseline', 'central')
                    .attr('font-size', altFontSize + 'px')
                    .attr('font-weight', '700')
                    .attr('fill', '#C2410C')
                    .text(startLabel);
                return;
            }
            if (alt % altLabelStep !== 0) return;
            var displayAlt = alt >= 1000
                ? (alt / 1000).toFixed(alt % 1000 === 0 ? 0 : 1) + 'k'
                : alt.toString();
            // Scope-Abstufung: Flugbereich normal, Puffer muted, darueber klein+muted.
            var labelFill = '#334155';    // default (Flugbereich)
            var labelWeight = '500';
            var labelSize = altFontSize;
            if (alt > bufferTop) {
                labelFill = '#CBD5E1';     // sehr muted, rein informativ
                labelWeight = '400';
                labelSize = Math.max(9, altFontSize - 1);
            } else if (alt > flightCeiling) {
                labelFill = '#94A3B8';     // muted (Puffer)
                labelWeight = '400';
            }
            chartG.append('text').attr('class', 'axis-label')
                .attr('x', -8).attr('y', rowY(ri) + cellH / 2)
                .attr('text-anchor', 'end').attr('dominant-baseline', 'central')
                .attr('font-size', labelSize + 'px')
                .attr('font-weight', labelWeight)
                .attr('fill', labelFill)
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
                // Layer-Reihenfolge: Wind-Zahl (oben) → Wind-Pfeil (mitte) →
                // Thermik-Zahl (unten). Konsistent unabhängig von Thermik-
                // Status, damit der Pilot weiss wo welcher Wert sitzt.
                var cy = rowY(ri3) + rH3 * 0.5;
                var speed = d.wind_speed;
                var gusts = d.wind_gusts != null ? d.wind_gusts : speed;
                var gustDiff = gusts - speed;
                // Kein Böen-Label anzeigen wenn gusts ≈ speed (z.B. Regionen-
                // Höhenprofil ohne Böen-Addition, wo gusts auf speed zurückfällt).
                var hasRealGust = (Math.round(gusts) > Math.round(speed));

                // Tier-Klassifikation gemaess config.py-Schwellen.
                // Ground-Row: nutzt ground_wind/gust; Altitude-Grid: aloft_wind/gust.
                // Der kombinierte Zell-Tier ist das Maximum aus Wind- und Gust-Tier
                // (= das schlimmere der beiden bestimmt die Zellenwirkung).
                var windMetric = isGround ? 'ground_wind' : 'aloft_wind';
                var gustMetric = isGround ? 'ground_gust' : 'aloft_gust';
                var windTier = classifyTier(speed, windMetric, thresholds);
                var gustTier = hasRealGust ? classifyTier(gusts, gustMetric, thresholds) : 'calm';
                var TIER_ORDER = { calm: 0, caution: 1, danger: 2 };
                var cellTier = TIER_ORDER[gustTier] > TIER_ORDER[windTier] ? gustTier : windTier;

                // Ground-Row: Richtungs-Check gegen erlaubte Sektoren
                var isWrongDir = false;
                if (isGround && windSectors && d.wind_direction != null && speed >= 3) {
                    isWrongDir = !isDirInSectors(d.wind_direction, windSectors, 10);
                }

                var showGusts = hasRealGust;
                // Pfeilfarbe: Tier-basiert. WrongDir überschreibt mit Rot (Richtungs-Warnung).
                // Danger = #9F1239 via TIER_STYLES.danger.text — sichtbar auf
                // hellem rosa Fill (Bodenrow) UND auf weiss/Thermik (Hoehenrow).
                var color = isWrongDir ? '#DC2626' : tierTextColor(windTier);
                // Wind-Zahl Farbe: immer Tier-Farbe der Windstärke (nicht Richtung).
                var speedColor = tierTextColor(windTier);

                // Background — Tier-basiert (calm=leer, caution=38% amber, danger=100% rose).
                // Fill-Intensitaet ist der primaere Glance-Kanal.
                if (isGround) {
                    // WrongDir rot uebersteuert alles (auch calm) — zeigt
                    // "Richtung passt nicht" unabhaengig vom Speed-Tier.
                    var gBgFill = null;
                    if (isWrongDir) gBgFill = 'rgba(220, 38, 38, 0.18)';
                    else if (cellTier !== 'calm') gBgFill = tierFillColor(cellTier);
                    if (gBgFill) {
                        chartG.append('rect')
                            .attr('x', ci3 * CELL_W + 1).attr('y', rowY(ri3) + 1)
                            .attr('width', CELL_W - 2).attr('height', rH3 - 2)
                            .attr('fill', gBgFill)
                            .attr('rx', 3);
                    }
                    // Launch-Cell-Frame: Farbe folgt dem Tier — Frame IST der
                    // Tier-Indikator fuer die Ground-Row. WrongDir rot = Sonderfall.
                    var frameColor = isWrongDir ? '#DC2626' : tierFrameColor(cellTier);
                    var frameWidth = (isWrongDir || cellTier === 'danger') ? 2 : 1.5;
                    chartG.append('rect').attr('class', 'launch-cell-frame')
                        .attr('x', ci3 * CELL_W + 1).attr('y', rowY(ri3) + 1)
                        .attr('width', CELL_W - 2).attr('height', rH3 - 2)
                        .attr('fill', 'none')
                        .attr('stroke', frameColor)
                        .attr('stroke-width', frameWidth)
                        .attr('rx', 3)
                        .style('pointer-events', 'none');
                } else {
                    // Altitude-Grid-Zelle: Tier ueber Perimeter (Border + kleines
                    // Eck-Dreieck bei danger), kein Hintergrund-Fill — Thermik-
                    // Farbe (xc-therm Skala) bleibt ungestoerter Glance-Kanal.
                    // Gedaempfte Hue (orange-700 / rose-800 statt -600/-700)
                    // damit Warnung lesbar, aber nicht "schreiend".
                    // - calm: kein Border
                    // - caution: 1.5px Orange-700 (gedaempfter als #EA580C)
                    // - danger: 1.75px Rose-800 + Eck-Dreieck mit "!" (Form-
                    //   Redundanz fuer Farbenblinde, dezent in Groesse)
                    if (cellTier === 'caution') {
                        chartG.append('rect')
                            .attr('x', ci3 * CELL_W + 1.25).attr('y', rowY(ri3) + 1.25)
                            .attr('width', CELL_W - 2.5).attr('height', rH3 - 2.5)
                            .attr('fill', 'none')
                            .attr('stroke', '#C2410C')
                            .attr('stroke-opacity', 0.75)
                            .attr('stroke-width', 1.5)
                            .attr('rx', 3)
                            .style('pointer-events', 'none');
                    } else if (cellTier === 'danger') {
                        chartG.append('rect')
                            .attr('x', ci3 * CELL_W + 1.5).attr('y', rowY(ri3) + 1.5)
                            .attr('width', CELL_W - 3).attr('height', rH3 - 3)
                            .attr('fill', 'none')
                            .attr('stroke', '#9F1239')
                            .attr('stroke-opacity', 0.8)
                            .attr('stroke-width', 1.75)
                            .attr('rx', 3)
                            .style('pointer-events', 'none');
                        // Eck-Dreieck oben rechts (Form-Redundanz fuer color-not-only).
                        // Dezent: 9px statt 11px, leicht transparent.
                        var bdx = ci3 * CELL_W + CELL_W - 1.5;
                        var bdy = rowY(ri3) + 1.5;
                        var bds = Math.round(9 * Math.min(scale, 1.3));
                        chartG.append('path')
                            .attr('d', 'M ' + (bdx - bds) + ' ' + bdy + ' L ' + bdx + ' ' + bdy + ' L ' + bdx + ' ' + (bdy + bds) + ' Z')
                            .attr('fill', '#9F1239')
                            .attr('fill-opacity', 0.85)
                            .style('pointer-events', 'none');
                        chartG.append('text')
                            .attr('x', bdx - bds * 0.32)
                            .attr('y', bdy + bds * 0.42)
                            .attr('text-anchor', 'middle')
                            .attr('dominant-baseline', 'middle')
                            .attr('font-size', Math.round(bds * 0.6) + 'px')
                            .attr('font-weight', '900')
                            .attr('fill', '#FFFFFF')
                            .style('pointer-events', 'none')
                            .text('!');
                    }
                }

                var arrowScale = Math.min(scale, 1.8);
                var gFilter;
                if (isGround && isWrongDir) {
                    gFilter = 'drop-shadow(0 0 4px rgba(220, 38, 38, 0.8))';
                } else if (isGround && cellTier === 'danger') {
                    // Ground-danger hat noch den rosa Fill → roter Glow betont.
                    gFilter = 'drop-shadow(0 0 3px rgba(225, 29, 72, 0.55))';
                } else {
                    // Hoehen-danger: Border + rote Zahl reichen — kein Glow noetig.
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

                // Wind-Zahl: Tier-Farbe. Boeen-Zahl: nur wenn caution/danger,
                // sonst muted Slate (#64748B) — damit sie sich vom Wind-Gruen
                // absetzt und Hierarchie klar ist (Wind=Tier, Boee=Zusatz-Info).
                // Erst bei Tag-ueberschreitender Boee (>30 km/h) wird sie farbig
                // und sticht als Warnung raus.
                var gustColor = gustTier === 'calm' ? '#64748B' : tierTextColor(gustTier);
                // Tier-Farben kommen direkt aus TIER_STYLES.danger.text (#9F1239).
                // Speed = windTier-Farbe, Gust = gustTier-Farbe → Pilot sieht
                // pro Zahl welche Komponente der Treiber ist (Wind vs Boee).
                // Ausnahme Hoehen-Zelle: wenn cellTier=danger (egal ob Wind oder
                // Boee), beide Zahlen rot → einheitlicher Danger-Look der Cell
                // (Hoehen-Zelle hat keinen Fill, Tier ueber Perimeter + Zahl-Farbe).
                if (cellTier === 'danger' && !isGround) {
                    speedColor = '#9F1239';
                    gustColor = '#9F1239';
                }
                var windFontSize = Math.round((isNarrow ? 7 : 9) * Math.min(scale, 1.8));
                // Font-Weight als 3. Tier-Kanal: 400 / 500 / 700.
                var tierWeight = (cellTier === 'danger') ? '700'
                                : (cellTier === 'caution') ? '600'
                                : '500';
                // Danger-Zellen leicht groesser fuer zusaetzliche Emphase.
                var tierFontSize = cellTier === 'danger' ? windFontSize + 1 : windFontSize;
                // Wind-Zahl OBEN, Pfeil mittig (cy = 0.5), Thermik-Zahl UNTEN.
                // Reihenfolge in der Cell: Zahl → Pfeil → Thermik-Zahl.
                // Y-Position so gewählt dass die Glyph-Oberkante 2-3px Abstand
                // zum oberen Cell-Rahmen hat (sonst überlappt der Text bei
                // alphabetic baseline mit dem Frame).
                var windTextY = rowY(ri3) + Math.round(rH3 * 0.30) + (isMobileViewport ? 2 : 0);
                var thermTextY = rowY(ri3) + rH3 - Math.round(4 * scale);
                // Text-Shadow nur auf Thermik-Zellen (Lesbarkeit ueber gelbem Bg) —
                // auf gefuellten Tier-Zellen nicht noetig (genug Kontrast).
                // Bei danger auf Thermik: starker weisser Halo, damit rote Zahl
                // klar absteht (kein Pill noetig).
                var textShadow = 'none';
                if (hasThermik) {
                    if (cellTier === 'danger') {
                        textShadow = '0 0 3px rgba(255,255,255,0.95), 0 0 2px rgba(255,255,255,0.95)';
                    } else if (cellTier === 'calm') {
                        textShadow = '0 1px 2px rgba(255,255,255,0.8)';
                    }
                }
                // Wind-Zahl IMMER OBEN (unter dem Pfeil), Thermik-Zahl IMMER
                // UNTEN. Konsistenz: Pilot weiss wo welcher Wert sitzt, egal ob
                // Thermik vorhanden ist oder nicht.
                // Desktop: "Wind/Boee" inline in jeder Zelle (auch Bodenrow =
                // Startplatzhoehe), eigene Tier-Farbe pro Wert → Pilot sieht
                // pro Hoehe direkt Wind und Boeenstaerke.
                // Mobile bleibt bei Single-Wert (Cells zu schmal fuer "15/45");
                // Boeen-Info auf Mobile via Bodenstrip-Boeen-Row.
                var showInlineGust = !isMobileViewport && hasRealGust;
                if (showNumbers) {
                    var windText = chartG.append('text').attr('class', 'wind-value')
                        .attr('x', cx).attr('y', windTextY)
                        .attr('font-size', tierFontSize + 'px').attr('fill', speedColor)
                        .attr('opacity', (hasThermik || cellTier !== 'calm') ? 1.0 : 0.8)
                        .attr('font-weight', tierWeight)
                        .style('text-shadow', textShadow)
                        .style('font-variant-numeric', 'tabular-nums');
                    if (showInlineGust) {
                        windText.append('tspan').attr('fill', speedColor).text(Math.round(speed));
                        windText.append('tspan').attr('fill', '#94A3B8').attr('font-weight', '400').text('/');
                        windText.append('tspan').attr('fill', gustColor).text(Math.round(gusts));
                    } else {
                        windText.text(Math.round(speed));
                    }

                    // Thermik-Zahl unten in der Zelle (nur wenn Thermik vorhanden).
                    // Thermik-Background ist meist hell (xc-therm), dunkler Text
                    // mit weissem Halo gibt klaren Kontrast.
                    if (hasThermik) {
                        var localRate = thermikCells[ri3 + ',' + ci3];
                        // Thermik-Zahl gleich gross wie Wind-Zahl (windFontSize).
                        var thermFontSize = Math.round((isNarrow ? 7 : 9) * Math.min(scale, 1.8));
                        chartG.append('text').attr('class', 'therm-value')
                            .attr('x', cx).attr('y', thermTextY)
                            .attr('text-anchor', 'middle')
                            .style('font-size', thermFontSize + 'px')
                            .attr('font-weight', '700').attr('fill', '#1E293B')
                            .style('font-variant-numeric', 'tabular-nums')
                            .style('text-shadow', '0 0 2px rgba(255,255,255,0.85)')
                            .text(localRate.toFixed(1));
                    }
                }

                // Turbulenz-/Böen-Strip im Höhengrid entfernt — Böen-Info kommt
                // konsolidiert im Bodenstrip-Böen-Row. Tier-Border bleibt
                // (zeigt Gefährlichkeit aus max(wind, gust) als Safety-Signal).

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

        // 3 Rows: Wind (Pfeil + Zahl), Böen (schmale "Linie"), Thermik.
        // Wind/Böen/Thermik bleiben als kurzer Text (klarer als abstrakte Icons),
        // Mini-Schrift auf Mobile damit's nicht mehr Platz braucht als Icons.
        // Cloud-Icons im Cloud-Strip bleiben weil Wolken-Glyphs universell sind.
        var groundLabelFontSize = isMobileViewport ? '8.5px' : null;
        function drawGroundLabel(y, text) {
            var t = chartG.append('text').attr('class', 'ground-label')
                .attr('x', -8).attr('y', y)
                .attr('text-anchor', 'end')
                .attr('dominant-baseline', 'central');
            if (groundLabelFontSize) {
                // .style() überschreibt das CSS-Default (font-size: 11px)
                // aus .ground-label — sonst wird die Mobile-Schrift ignoriert.
                t.style('font-size', groundLabelFontSize).style('font-weight', '600');
            }
            t.text(text);
        }
        // Wind-Row: Mobile zweizeilig — "Wind" prominent + "Boden" als kleine
        // Subline drunter macht klar dass es um die Wind-Stärke am Boden geht
        // (Höhengrid hat eigene Wind-Pfeile pro Höhe). Desktop: "Bodenwind".
        if (isMobileViewport) {
            var windRowCenter = groundY + GROUND_WIND_Y + GROUND_WIND_H / 2;
            // .style() statt .attr(), damit das fontsize aus .ground-label
            // CSS-Klasse (font-size: 11px) NICHT überschreibt.
            chartG.append('text').attr('class', 'ground-label')
                .attr('x', -8).attr('y', windRowCenter - 4)
                .attr('text-anchor', 'end')
                .attr('dominant-baseline', 'central')
                .attr('fill', '#334155')
                .style('font-size', '9px').style('font-weight', '700')
                .text('Wind');
            chartG.append('text').attr('class', 'ground-label')
                .attr('x', -8).attr('y', windRowCenter + 5)
                .attr('text-anchor', 'end')
                .attr('dominant-baseline', 'central')
                .attr('fill', '#94A3B8')
                .style('font-size', '6px').style('font-weight', '500')
                .text('(Boden)');
        } else {
            drawGroundLabel(groundY + GROUND_WIND_Y + GROUND_WIND_H / 2, 'Bodenwind');
        }
        if (!isRegion) {
            drawGroundLabel(groundY + GROUND_GUST_Y + GROUND_GUST_H / 2, 'Böen');
        }
        drawGroundLabel(groundY + GROUND_THERM_Y + GROUND_THERM_H / 2,
                        isMobileViewport ? 'Therm' : 'Thermik');

        times.forEach(function (t, ci) {
            var wx = wxByTime[t] || {};
            var wind = wx.wind || {};
            var precip = wx.precipitation || {};
            var cx = ci * CELL_W + CELL_W / 2;
            // Combined Row 0: Surface wind + Gusts
            var spd = wind.speed != null ? Math.round(wind.speed) : null;
            var gusts = wind.gusts != null ? Math.round(wind.gusts) : null;
            var dir = wind.direction;
            
            // Auto-suppress: bei sehr engen Cells (Multi-Tag-Ansicht etc.)
            // sind Zahlen unleserlich → nur Pfeile/Farben rendern.
            var cellTooNarrowForNumbers = CELL_W < 16;
            var renderNumbers = showNumbers && !cellTooNarrowForNumbers;

            // ----- Row 0: Wind (nur Zahl, kein Pfeil) -----
            // Wind-Richtung ist bereits im Höhengrid-Bodenrow (ri=0, ★ Marker)
            // sichtbar. Hier zeigt der Bodenstrip nur noch die WindSTÄRKE am
            // Boden — als prominent zentrierte Zahl.
            if (spd != null) {
                var gWindTier = classifyTier(spd, 'ground_wind', thresholds);
                var windRowTop = groundY + GROUND_WIND_Y;

                // Tier-Fill nur bei sportlich/gefährlich.
                if (gWindTier !== 'calm') {
                    chartG.append('rect')
                        .attr('x', ci * CELL_W + 1).attr('y', windRowTop + 1)
                        .attr('width', CELL_W - 2).attr('height', GROUND_WIND_H - 2).attr('rx', 3)
                        .attr('fill', tierFillColor(gWindTier));
                }

                // Bodenstrip-Zahlen IMMER sichtbar (Zusammenfassungs-Zeile),
                // nicht vom showNumbers-Toggle abhängig — der steuert nur die
                // Zahlen IM Höhengrid. Auto-suppress nur bei zu engen Cells.
                if (CELL_W >= 16) {
                    var gTextColor = tierTextColor(gWindTier);
                    var gTextWeight = gWindTier === 'danger' ? '700'
                                     : gWindTier === 'caution' ? '600' : '500';
                    chartG.append('text').attr('class', 'ground-value')
                        .attr('x', cx).attr('y', windRowTop + GROUND_WIND_H / 2)
                        .attr('text-anchor', 'middle')
                        .attr('dominant-baseline', 'central')
                        .attr('font-weight', gTextWeight)
                        .attr('font-size', isMobileViewport ? '11px' : '12px')
                        .attr('fill', gTextColor)
                        .style('font-variant-numeric', 'tabular-nums')
                        .text(String(spd));
                }
            }

            // ----- Row 1: Böen (schmale "Linie" — Tier-Color-Strip + Zahl) -----
            // Nur wenn Böen-Wert vorhanden UND > Wind (sonst leer = redundant zu Wind).
            // Regionen haben keine Böen → Row weg (vom Layout ist sie da, bleibt leer).
            if (!isRegion && gusts != null && spd != null && gusts > spd) {
                var gustRowTop = groundY + GROUND_GUST_Y;
                var gGustTier = classifyTier(gusts, 'ground_gust', thresholds);

                // Tier-Color-Strip pro Stunde — die "Linie" über der ganzen Cell.
                if (gGustTier !== 'calm') {
                    chartG.append('rect')
                        .attr('x', ci * CELL_W + 1).attr('y', gustRowTop + 1)
                        .attr('width', CELL_W - 2).attr('height', GROUND_GUST_H - 2).attr('rx', 2)
                        .attr('fill', tierFillColor(gGustTier));
                }

                if (CELL_W >= 16) {
                    var gustTextColor = gGustTier === 'calm' ? '#475569' : tierTextColor(gGustTier);
                    var gustTextWeight = gGustTier === 'danger' ? '700'
                                       : gGustTier === 'caution' ? '600' : '500';
                    chartG.append('text').attr('class', 'ground-value')
                        .attr('x', cx).attr('y', gustRowTop + GROUND_GUST_H / 2)
                        .attr('text-anchor', 'middle')
                        .attr('dominant-baseline', 'central')
                        .attr('font-weight', gustTextWeight)
                        .attr('font-size', isMobileViewport ? '9px' : '10px')
                        .attr('fill', gustTextColor)
                        .style('font-variant-numeric', 'tabular-nums')
                        .text(String(gusts));
                }
            }

            // ----- Row 2: Thermik (Steigrate m/s) — xc-therm color scale -----
            var therm = wx.thermik || {};
            if (therm.climb_rate > 0) {
                var thermRowTop = groundY + GROUND_THERM_Y;
                chartG.append('rect')
                    .attr('x', ci * CELL_W + 1).attr('y', thermRowTop + 1)
                    .attr('width', CELL_W - 2).attr('height', GROUND_THERM_H - 2).attr('rx', 3)
                    .attr('fill', thermClimbColor(therm.climb_rate)).attr('opacity', 0.4);

                if (CELL_W >= 16) {
                    chartG.append('text').attr('class', 'ground-value')
                        .attr('x', cx).attr('y', thermRowTop + GROUND_THERM_H / 2)
                        .attr('text-anchor', 'middle')
                        .attr('dominant-baseline', 'central')
                        .attr('font-size', isMobileViewport ? '9px' : '10px')
                        .attr('font-weight', '700').attr('fill', '#1E293B')
                        .style('font-variant-numeric', 'tabular-nums')
                        .text(therm.climb_rate.toFixed(1));
                }
            }
        });

        // ===== WARNINGS STRIP =====
        // Plain-German hour-range pills below the ground strip.
        if (warnBands.length > 0 && WARN_STRIP_H > 0) {
            var warnTop = groundY + GROUND_H + 4;
            // Row label on the left — Icon auf Mobile, Text auf Desktop.
            if (isMobileViewport) {
                appendLeftIcon(warnTop + WARN_ROW_H / 2, drawWarnIcon);
            } else {
                chartG.append('text').attr('class', 'ground-label')
                    .attr('x', -8).attr('y', warnTop + WARN_ROW_H / 2 + 3)
                    .attr('text-anchor', 'end')
                    .attr('fill', '#92400E')
                    .text('Warnungen');
            }

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
                // Rough fit: ~5px per char at 9px font
                var maxChars = Math.floor((bw - 6) / 5);
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
                        .attr('font-size', '9px')
                        .attr('font-weight', '600')
                        .attr('fill', band.color)
                        .text(displayLabel);
                }

                // Tooltip on hover (native title, simple + reliable)
                chartG.append('title').text(fullLabel);
            });

            // Overflow-Indikator: wenn Warnings wegen MAX_WARN_ROWS gedroppt
            // wurden, in der letzten Reihe rechts eine "+N" Pill mit Tooltip
            // (komplette Liste der gedroppten Warnings) zeigen.
            if (droppedWarns.length > 0) {
                var lastRow = MAX_WARN_ROWS - 1;
                var oy = warnTop + lastRow * (WARN_ROW_H + WARN_ROW_GAP);
                var oLabel = '+' + droppedWarns.length;
                var oW = Math.max(28, oLabel.length * 7 + 8);
                var oX = nCols * CELL_W - oW - 1;
                var oG = chartG.append('g');
                oG.append('rect')
                    .attr('x', oX).attr('y', oy)
                    .attr('width', oW).attr('height', WARN_ROW_H)
                    .attr('rx', 4)
                    .attr('fill', '#FEE2E2')
                    .attr('stroke', '#B91C1C')
                    .attr('stroke-width', 0.75)
                    .attr('opacity', 0.95);
                oG.append('text')
                    .attr('x', oX + oW / 2).attr('y', oy + WARN_ROW_H / 2 + 3)
                    .attr('text-anchor', 'middle')
                    .attr('font-size', '9px')
                    .attr('font-weight', '700')
                    .attr('fill', '#991B1B')
                    .text(oLabel);
                var oTooltip = droppedWarns.map(function (b) {
                    return b.label + ' ' + formatHourRange(times, b.start, b.end);
                }).join('\n');
                oG.append('title').text(droppedWarns.length + ' weitere Warnung'
                    + (droppedWarns.length === 1 ? '' : 'en') + ':\n' + oTooltip);
            }
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
                // Tier-Zusammenfassung: der wichtigste Info-Block. Zeigt
                // "● Sportlich — ALOFT-WARN" als Bruecke zum LLM-Rating.
                var ttWind = dd.wind_speed;
                var ttGust = dd.wind_gusts != null ? dd.wind_gusts : ttWind;
                var ttWindTier = classifyTier(ttWind, isGroundCell ? 'ground_wind' : 'aloft_wind', thresholds);
                var ttGustTier = (ttGust > ttWind) ? classifyTier(ttGust, isGroundCell ? 'ground_gust' : 'aloft_gust', thresholds) : 'calm';
                var TT_ORDER = { calm: 0, caution: 1, danger: 2 };
                var ttCellTier = TT_ORDER[ttGustTier] > TT_ORDER[ttWindTier] ? ttGustTier : ttWindTier;
                var ttTag = deriveDominantTag(isGroundCell, ttWind, ttGust, thresholds);
                html += '<div class="tooltip-row" style="margin-top:4px;padding-top:4px;border-top:1px solid #E5E7EB">' +
                    '<span class="tooltip-label">Bewertung</span>' +
                    '<span class="tooltip-value" style="font-weight:700;display:inline-flex;align-items:center;gap:6px">' +
                    '<span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:' + TIER_DOTS[ttCellTier] + '"></span>' +
                    TIER_LABELS[ttCellTier] +
                    (ttTag ? ' <span style="color:#94A3B8;font-weight:500;font-size:10px">[' + ttTag.name + ']</span>' : '') +
                    '</span></div>';
                if (isGroundCell) {
                    html += '<div class="tooltip-row"><span class="tooltip-label" style="color:#C2410C;font-weight:700">\u2605 Startplatz</span><span class="tooltip-value" style="color:#C2410C;font-weight:700">' + Math.round(elevation) + 'm</span></div>';
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

        // ===== TOUCH: Scrubber (Mobile) + Tap-Tooltip (Desktop fallback) =====
        // Mobile-Strategie: Finger berührt das Chart → vertikale Linie folgt
        // dem Finger, Werte erscheinen in der Info-Zeile OBERHALB des Charts
        // (wo der Finger sie nie verdeckt). User muss keine 12px-Zelle treffen,
        // er zieht einfach durch — Werte updaten live. Pattern aus Apple Stocks
        // / Apple Wetter / TradingView (touch-target-chart-Regel: ≥44pt indem
        // ganze Spalte ein Treffer ist).
        var TAP_MOVE_THRESHOLD = 10;
        var SCRUB_HORIZ_INTENT = 8;  // ab welcher X-Bewegung wir Scrub vermuten
        var scrubFadeTimer = null;

        function updateScrubFromCoords(coords) {
            var mx = coords[0], my = coords[1];
            var ci = Math.max(0, Math.min(nCols - 1, Math.floor(mx / CELL_W)));
            var colX = ci * CELL_W + CELL_W / 2;
            crossV.attr('x1', colX).attr('x2', colX).classed('visible', true);

            var t = times[ci];
            var dt = new Date(t);
            var hh = String(dt.getHours()).padStart(2, '0');
            var timeStr = hh + ':00';
            var wx = wxByTime[t] || {};

            // Höhen-Cell unter Finger (falls im Höhengrid).
            var altParts = [];
            var ri;
            var groundTopY = GRID_TOP + (nRows - 1) * cellH;
            if (hasGroundRow && my >= groundTopY && my < gridBottom) ri = 0;
            else ri = nRows - 1 - Math.floor((my - GRID_TOP) / cellH);
            var inGrid = my >= GRID_TOP && ri >= 0 && ri < nRows && grid[ri] && grid[ri][ci];

            if (inGrid) {
                var dd = grid[ri][ci];
                var altLabel = (ri === 0 && hasGroundRow && dd.isGroundRow)
                    ? Math.round(elevation) + 'm'
                    : Math.round(dd.altitude) + 'm';
                altParts.push('<b>' + altLabel + '</b>');
                altParts.push(Math.round(dd.wind_speed) + ' km/h');
                var trVal = dd.turbulence_risk != null ? dd.turbulence_risk : dd.wind_gusts;
                if (trVal != null && Math.round(trVal) > Math.round(dd.wind_speed)) {
                    altParts.push('Böe ' + Math.round(trVal));
                }
            } else if (wx.wind) {
                // Default: Boden-Werte zeigen
                altParts.push('<b>Boden</b>');
                altParts.push(Math.round(wx.wind.speed) + ' km/h');
                if (wx.wind.gusts != null && wx.wind.gusts > wx.wind.speed) {
                    altParts.push('Böe ' + Math.round(wx.wind.gusts));
                }
            }
            if (wx.thermik && wx.thermik.climb_rate > 0) {
                altParts.push('Therm ' + wx.thermik.climb_rate.toFixed(1) + ' m/s');
            }

            if (scrubInfo) {
                var timeEl = scrubInfo.querySelector('.mg-scrub-time');
                var valsEl = scrubInfo.querySelector('.mg-scrub-vals');
                if (timeEl) timeEl.textContent = timeStr;
                if (valsEl) valsEl.innerHTML = altParts.join(' · ');
                legendBar.classList.add('mg-scrubbing');
            }
        }

        function endScrub() {
            crossV.classed('visible', false);
            if (scrubFadeTimer) clearTimeout(scrubFadeTimer);
            scrubFadeTimer = setTimeout(function () {
                if (legendBar) legendBar.classList.remove('mg-scrubbing');
            }, 1500);
        }

        if (isMobileViewport) {
            // Mobile: combined scrub+tap handler, passive:false damit wir bei
            // klar horizontalem Drag das Default-Page-Scroll unterdrücken können.
            // Vertikales Scrollen bleibt ungestört.
            var tStartX = 0, tStartY = 0, tIsScrub = false, tWasTap = true;
            interactRect.node().addEventListener('touchstart', function (e) {
                var touch = e.touches[0];
                tStartX = touch.clientX;
                tStartY = touch.clientY;
                tIsScrub = false;
                tWasTap = true;
                if (scrubFadeTimer) { clearTimeout(scrubFadeTimer); scrubFadeTimer = null; }
            }, { passive: true });
            interactRect.node().addEventListener('touchmove', function (e) {
                var touch = e.touches[0];
                var dx = touch.clientX - tStartX;
                var dy = touch.clientY - tStartY;
                if (!tIsScrub) {
                    // Intent-Detection: erst wenn klar horizontal, scrub starten.
                    // |dx| > |dy| && |dx| > Threshold → User will scrubben.
                    // |dy| > |dx| → User will Page scrollen, nicht stören.
                    if (Math.abs(dx) > SCRUB_HORIZ_INTENT && Math.abs(dx) > Math.abs(dy)) {
                        tIsScrub = true;
                        tWasTap = false;
                    } else if (Math.abs(dx) > TAP_MOVE_THRESHOLD || Math.abs(dy) > TAP_MOVE_THRESHOLD) {
                        tWasTap = false;
                    }
                }
                if (tIsScrub) {
                    e.preventDefault(); // Page-Scroll während Scrub blockieren
                    var coords = d3.pointer(touch, interactRect.node());
                    updateScrubFromCoords(coords);
                }
            }, { passive: false });
            interactRect.node().addEventListener('touchend', function (e) {
                if (tIsScrub) {
                    endScrub();
                } else if (tWasTap) {
                    // Tap → klassisches Detail-Tooltip (existierender Pfad)
                    var touch = e.changedTouches[0];
                    var coords = d3.pointer(touch, interactRect.node());
                    showTooltipAt(coords, touch.clientX, touch.clientY);
                }
                tIsScrub = false;
            }, { passive: true });
            document.addEventListener('touchstart', function (e) {
                if (!interactRect.node().contains(e.target)) {
                    hideTooltip();
                    if (legendBar) legendBar.classList.remove('mg-scrubbing');
                }
            }, { passive: true });
        } else {
            // Desktop: nur Tap-Tooltip-Pfad (existing behaviour, für Tablets/Touchscreens)
            var touchStartX = 0, touchStartY = 0, touchIsTap = false;
            interactRect.node().addEventListener('touchstart', function (e) {
                var touch = e.touches[0];
                touchStartX = touch.clientX;
                touchStartY = touch.clientY;
                touchIsTap = true;
            }, { passive: true });
            interactRect.node().addEventListener('touchmove', function (e) {
                if (!touchIsTap) return;
                var touch = e.touches[0];
                if (Math.abs(touch.clientX - touchStartX) > TAP_MOVE_THRESHOLD ||
                    Math.abs(touch.clientY - touchStartY) > TAP_MOVE_THRESHOLD) {
                    touchIsTap = false;
                }
            }, { passive: true });
            interactRect.node().addEventListener('touchend', function (e) {
                if (!touchIsTap) return;
                touchIsTap = false;
                var touch = e.changedTouches[0];
                var coords = d3.pointer(touch, interactRect.node());
                showTooltipAt(coords, touch.clientX, touch.clientY);
            }, { passive: true });
            document.addEventListener('touchstart', function (e) {
                if (!interactRect.node().contains(e.target)) hideTooltip();
            }, { passive: true });
        }
    }

    // ===== ANALYSE VIEW =====
    // Delegiert an das shared Modul window.AnalysisView, das identisch fuer
    // Spot und Region rendert. Layout/States/Alerts-Pflicht zentral dort.
    function renderAnalysisView(container, analysisDay, options) {
        if (window.AnalysisView && window.AnalysisView.render) {
            window.AnalysisView.render(container, analysisDay, options || {});
            return;
        }
        // Defensive Fallback: kommt nur, wenn analysis-view.js nicht geladen wurde.
        if (container) {
            container.innerHTML = '<div class="mga-hero no_data">'
                + '<div class="mga-hero-text">'
                + '<div class="mga-hero-verdict no_data">Analyse-Ansicht nicht verfuegbar</div>'
                + '<div class="mga-hero-rationale">analysis-view.js wurde nicht geladen.</div>'
                + '</div></div>';
        }
    }


    // Public API
    return {
        windColor: windColor,
        arrowPath: arrowPath,
        formatDayTabLabel: formatDayTabLabel,
        formatDayTabParts: formatDayTabParts,
        buildTabs: buildTabs,
        renderChart: renderChart,
        renderAnalysisView: renderAnalysisView
    };
})();
