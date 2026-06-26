/**
 * WxDataView — zeigt den EXAKTEN Wetter-Kontext-Text, den die KI zur Bewertung
 * bekommt (Spot- oder Regionen-Ebene). Geteilt von index (map.js) und
 * regionen (region-map.js).
 *
 * Quelle: /api/spot-context/<spot>/<date> bzw. /api/region-context/<region>/<date>
 * (identisch zu _build_single_spot_context / _build_single_region_context).
 *
 * Darstellung: Stundenzeilen → scanbare Spalten-Tabelle (Zeit · Wind · Thermik ·
 * Wolken · Temp · Warnungen). Übrige Zeilen (═══ Abschnitte, → Hinweise) als
 * Header/Body/Callout. Ganz unten der 1:1-Rohtext (aufklappbar) als Wahrheits-
 * anker — die Tabelle ist nur eine Lesehilfe DESSELBEN Texts.
 *
 * Hinweis: NICHT `window.DataView` nennen — das ist ein eingebauter JS-Global.
 *
 *   WxDataView.render(containerEl, 'spot'|'region', id, 'YYYY-MM-DD')
 */
window.WxDataView = (function () {
    'use strict';

    function esc(s) {
        return String(s)
            .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    // Schweregrad eines [TAG]-Inhalts → CSS-Klasse.
    function tagSeverity(inner) {
        var up = inner.toUpperCase();
        if (/DANGER|UNUSABLE|WRONG/.test(up)) return 'danger';
        if (/WARN|DEGRADED|FRAGMENTED|ROUGH/.test(up)) return 'warn';
        if (/\bOK\b|CALM|PRODUKTIV|CLEAN/.test(up)) return 'ok';
        return 'info';
    }

    // Färbt [TAG]-Tokens in beliebigem Text ein (Eingabe bereits escaped).
    function colorizeTags(escaped) {
        return escaped.replace(/\[([^\]]+)\]/g, function (m, inner) {
            return '<span class="dv-tag dv-tag-' + tagSeverity(inner) + '">' + inner + '</span>';
        });
    }

    var HOUR_RE = /^(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2}):\s*(.*)$/;

    // Abschnitts-Titel aus "═══ X ═══" ODER "### X ###" / "### X". null = kein Header.
    function sectionTitle(line) {
        var m = line.match(/^═+\s*(.*?)\s*═+$/);
        if (m) return m[1];
        m = line.match(/^###\s*(.*?)\s*#*$/);
        if (m) return m[1];
        return null;
    }

    // Verlaufszeile? "08:00:clean · 09:00:WARN(...) · ..."
    function isTimeline(line) {
        return /^\d{2}:\d{2}:/.test(line) && line.indexOf(' · ') !== -1;
    }
    function statusSeverity(s) {
        var up = s.toUpperCase();
        if (/DANGER|UNUSABLE|WRONG|NOT.?SAFE|KEINE-THERMIK/.test(up)) return 'danger';
        if (/WARN|DEGRADED|ROUGH|FRAG|SOARING|CONDITIONAL/.test(up)) return 'warn';
        if (/CLEAN|PRODUKTIV|\bOK\b|SAFE/.test(up)) return 'ok';
        return 'info';
    }
    function renderTimeline(line) {
        var chips = line.split(' · ').map(function (item) {
            var p = item.split(':');
            if (p.length < 3) return '<span class="dv-vchip">' + esc(item) + '</span>';
            var time = p[0] + ':' + p[1];
            var status = p.slice(2).join(':');
            return '<span class="dv-vchip dv-vchip-' + statusSeverity(status) + '">'
                + '<b>' + esc(time) + '</b> ' + esc(status) + '</span>';
        }).join('');
        return '<div class="dv-vstrip">' + chips + '</div>';
    }

    // Zahlen-/Datentokens (mit Einheit) in escaptem Text als Chip hervorheben,
    // damit Messwerte aus der Prosa heraus sofort scanbar sind. Operiert NUR auf
    // Text ausserhalb von HTML-Tags (split an <...>), damit Attribute/Klassen der
    // bereits gefaerbten [TAG]-Spans nicht angefasst werden.
    var NUM_RE = /(\d{1,2}:\d{2}(?:[-–]\d{1,2}:\d{2})?|\d+(?:[.,]\d+)?(?:[-–×]\d+(?:[.,]\d+)?)?\s?(?:km\/h|m\/s|hPa|°C|%|°|m|h)|\d+(?:[.,]\d+)?)/g;
    function highlightNums(html) {
        return html.split(/(<[^>]*>)/).map(function (part) {
            if (part.charAt(0) === '<') return part;
            return part.replace(NUM_RE, '<span class="dv-num">$1</span>');
        }).join('');
    }
    // Freitext → escaped, [TAG] gefaerbt, Zahlen hervorgehoben.
    function decorate(s) { return highlightNums(colorizeTags(esc(s))); }

    // "Label: Wert" (auch mehrere via " | ") → KV-Zeilen. null wenn die Zeile
    // kein sauberes Label:Wert ist oder der Wert lange Prosa (> 70 Zeichen) ist.
    function parseKvLine(line) {
        var segs = line.indexOf(' | ') !== -1 ? line.split(' | ') : [line];
        var rows = [];
        for (var i = 0; i < segs.length; i++) {
            var m = segs[i].match(/^([^:]{1,60}?):\s+(.+)$/);
            if (!m) return null;
            var val = m[2].trim();
            if (val.length > 70) return null;   // lange Prosa lieber als Zeile
            rows.push([esc(m[1].trim()), decorate(val)]);
        }
        return rows.length ? rows : null;
    }

    // Section-Body rendern: Datenzeilen → KV-Tabelle, Zahlen hervorgehoben,
    // Bullets/Timelines/→-Hinweise wie gehabt (aber mit Zahlen-Highlight).
    function renderBody(bodyLines) {
        var out = [];
        var bullets = [];
        var kv = [];
        function flushBullets() {
            if (bullets.length) {
                out.push('<ul class="dv-bullets">' + bullets.map(function (b) {
                    return '<li>' + decorate(b) + '</li>';
                }).join('') + '</ul>');
                bullets = [];
            }
        }
        function flushKv() {
            if (kv.length) {
                out.push('<table class="dv-kv"><tbody>' + kv.map(function (r) {
                    return '<tr><td class="dv-kv-k">' + r[0] + '</td><td class="dv-kv-v">' + r[1] + '</td></tr>';
                }).join('') + '</tbody></table>');
                kv = [];
            }
        }
        bodyLines.forEach(function (line) {
            var bm = line.match(/^\s*-\s+(.*)$/);
            if (bm) { flushKv(); bullets.push(bm[1]); return; }
            flushBullets();
            if (/^→/.test(line)) {
                flushKv();
                out.push('<div class="dv-callout">' + decorate(line.replace(/^→\s*/, '')) + '</div>');
                return;
            }
            if (isTimeline(line)) {
                flushKv();
                out.push(renderTimeline(line));
                return;
            }
            var rows = parseKvLine(line);
            if (rows) { rows.forEach(function (r) { kv.push(r); }); return; }
            flushKv();
            // Lange "Label: Prosa"-Zeile: Label fett, Zahlen hervorgehoben.
            var lm = line.match(/^([^:]{1,40}):\s+(.+)$/);
            var inner = lm
                ? '<b class="dv-line-k">' + esc(lm[1]) + ':</b> ' + decorate(lm[2])
                : decorate(line);
            out.push('<div class="dv-line">' + inner + '</div>');
        });
        flushBullets();
        flushKv();
        return out.join('');
    }

    function num(re, s) { var m = s.match(re); return m ? m[1] : null; }

    // Eine Stundenzeile in strukturierte Felder zerlegen. Ziel: JEDES Segment,
    // das an die KI geht, landet auch in der Tabelle — Unbekanntes in o.extra,
    // damit nie still etwas verloren geht.
    function parseHour(time, rest) {
        var segs = rest.split(' | ');
        var o = { time: time, tags: [], aloft: [], extra: [] };
        segs.forEach(function (seg) {
            // Tags aus dem Segment ziehen (überall möglich, meist im Wind-Segment).
            var tagMatch = seg.match(/\[[^\]]+\]/g);
            if (tagMatch) {
                tagMatch.forEach(function (t) {
                    var inner = t.slice(1, -1);
                    if (/^Ref-Wind/i.test(inner)) {   // Referenzhöhen-Wind (Region), Info
                        var rm = inner.match(/Ref-Wind\s*(\d+)m:\s*([\d.]+)\s*km\/h\s*aus\s*(\d+)/);
                        o.refWind = rm ? { alt: rm[1], speed: rm[2], dir: rm[3] } : { raw: inner };
                        return;
                    }
                    o.tags.push(inner);
                });
            }
            var bare = seg.replace(/\[[^\]]+\]/g, '').trim();
            if (!bare) return;
            if (/^Temp /.test(bare)) o.temp = num(/Temp ([\d.\-]+)/, bare);
            else if (/^Wind /.test(bare)) {
                o.windSpeed = num(/Wind ([\d.]+)km\/h/, bare);
                o.windDir = num(/aus (\d+)°/, bare);
                o.turb = num(/Turbulenzrisiko ([\d.]+)km\/h/, bare);   // Spot
                o.excess = num(/Exzess ([+\-\d.]+)km\/h/, bare);       // Spot
            }
            else if (/^\d+hPa\(/.test(bare)) {
                // Höhenwind je Druckniveau: "700hPa(3138m)*: 21/26km/h aus 304°"
                // Flag * = im Flugbereich, ~ = darüber. gust optional (nur "60km/h").
                var am = bare.match(/^(\d+)hPa\((\d+)m\)([*~]?):\s*([\d.]+)(?:\/([\d.]+))?\s*km\/h\s*aus\s*(\d+)/);
                if (am) o.aloft.push({ level: am[1], alt: am[2], flag: am[3], speed: am[4], gust: am[5] || null, dir: am[6] });
                else o.extra.push(bare);
            }
            else if (/^Wolkenbasis/.test(bare)) o.cloudBase = bare.replace(/^Wolkenbasis\s*/, '');
            else if (/^Bew/.test(bare)) {
                o.cloudCover = num(/(\d+)%/, bare);
                o.cloudLow = num(/tief (\d+)%/, bare);
                o.cloudMid = num(/mittel (\d+)%/, bare);
                o.cloudHigh = num(/hoch (\d+)%/, bare);
            }
            else if (/^Strahlung/.test(bare)) {
                o.radGlobal = num(/Strahlung (\d+)/, bare);
                o.radDirect = num(/direkt (\d+)/, bare);
            }
            else if (/^FLUGBEREICH/.test(bare)) {
                var fb = bare.match(/FLUGBEREICH:\s*(.+)$/);
                o.flightBand = fb ? fb[1].replace(/\s*MSL\s*$/, '').trim() : null;
            }
            else if (/^THERMIK-PROXY/.test(bare)) {
                o.climb = num(/([\d.]+) m\/s/, bare);
                o.thermTop = num(/bis (\d+)m/, bare);
                o.lcl = num(/LCL\/Basis (\d+)/, bare);
            }
            else o.extra.push(bare);   // alles Übrige: nichts geht verloren
        });
        return o;
    }

    function fmtKmh(v) { return v == null ? '–' : Math.round(parseFloat(v)) + ''; }

    // Wind/Böen-Tags nach härtester Stufe einfärben. kind='ground' = nur
    // Bodenwind ([WIND-*]/[GUST-*]), kind='aloft' = nur Höhenwind ([ALOFT-*]).
    // Wichtig: Bodenwind-Zelle darf NICHT rot werden, nur weil oben Föhn weht.
    function windClass(o, kind) {
        var sev = 'ok';
        o.tags.forEach(function (t) {
            var up = t.toUpperCase();
            if (!/WIND|GUST/.test(up)) return;
            var isAloft = /ALOFT/.test(up);
            if (kind === 'ground' && isAloft) return;
            if (kind === 'aloft' && !isAloft) return;
            var s = tagSeverity(t);
            if (s === 'danger') sev = 'danger';
            else if (s === 'warn' && sev !== 'danger') sev = 'warn';
        });
        return 'dv-v-' + sev;
    }

    // Höhenwind-Zelle: ein Block je Druckniveau (850/700/600 hPa), aufsteigend.
    // Das im Flugbereich liegende Niveau (*) wird hervorgehoben + nach ALOFT-
    // Warnstufe gefärbt; Niveaus darüber/darunter bleiben neutral.
    function buildAloft(o) {
        if (!o.aloft || !o.aloft.length) return '<span class="dv-muted">–</span>';
        var aloftSev = windClass(o, 'aloft');
        return o.aloft.map(function (a) {
            var inBand = a.flag === '*';
            var cls = inBand ? aloftSev : 'dv-v-ok';
            var spd = a.gust ? esc(a.speed) + '/' + esc(a.gust) : esc(a.speed);
            return '<div class="dv-alvl' + (inBand ? ' dv-alvl-band' : '') + '"'
                + (inBand ? ' title="' + wcT('js.dv.in_band') + '"' : (a.flag === '~' ? ' title="' + wcT('js.dv.above_band') + '"' : '')) + '>'
                + '<span class="dv-alvl-h">' + esc(a.level) + '<small>hPa</small></span>'
                + '<span class="dv-val ' + cls + '">' + spd + '<span class="dv-unit"> km/h</span></span>'
                + '<span class="dv-sub">' + esc(a.dir) + '° · ' + esc(a.alt) + 'm</span>'
                + '</div>';
        }).join('');
    }

    function buildTable(rows) {
        var head = '<thead><tr>'
            + wcT('js.dv.table_head')
            + '</tr></thead>';
        var body = rows.map(function (o) {
            // Wind (Boden) + alle Sub-Infos: Richtung, Turbulenz, Exzess, Ref-Wind.
            var windSub = (o.windDir != null ? '<span class="dv-sub">' + esc(o.windDir) + '°</span>' : '');
            if (o.turb != null) windSub += '<span class="dv-sub">Turb ' + fmtKmh(o.turb) + ' km/h</span>';
            if (o.excess != null) windSub += '<span class="dv-sub">Exzess ' + esc(o.excess) + ' km/h</span>';
            if (o.refWind) windSub += '<span class="dv-sub">Ref ' +
                (o.refWind.raw ? esc(o.refWind.raw)
                    : fmtKmh(o.refWind.speed) + ' km/h ' + esc(o.refWind.dir) + '° @' + esc(o.refWind.alt) + 'm')
                + '</span>';
            var wind = '<span class="dv-val ' + windClass(o, 'ground') + '">' + fmtKmh(o.windSpeed) + '<span class="dv-unit"> km/h</span></span>' + windSub;

            var therm = (o.climb != null)
                ? '<span class="dv-val">' + esc(o.climb) + '<span class="dv-unit"> m/s</span></span>'
                  + (o.thermTop ? '<span class="dv-sub">bis ' + esc(o.thermTop) + 'm</span>' : '')
                  + (o.lcl ? '<span class="dv-sub">LCL ' + esc(o.lcl) + 'm</span>' : '')
                : '<span class="dv-muted">–</span>';

            var cloud = (o.cloudCover != null ? '<span class="dv-val">' + esc(o.cloudCover) + '<span class="dv-unit">%</span></span>' : '');
            if (o.cloudLow != null || o.cloudMid != null || o.cloudHigh != null) {
                cloud += '<span class="dv-sub" title="tief / mittel / hoch">'
                    + esc(o.cloudLow == null ? '–' : o.cloudLow) + '/' + esc(o.cloudMid == null ? '–' : o.cloudMid)
                    + '/' + esc(o.cloudHigh == null ? '–' : o.cloudHigh) + '%</span>';
            }
            if (o.cloudBase) cloud += '<span class="dv-sub">' + esc(o.cloudBase) + '</span>';
            if (!cloud) cloud = '<span class="dv-muted">–</span>';

            var rad = (o.radGlobal != null)
                ? '<span class="dv-val">' + esc(o.radGlobal) + '<span class="dv-unit"> W/m²</span></span>'
                  + (o.radDirect != null ? '<span class="dv-sub">direkt ' + esc(o.radDirect) + '</span>' : '')
                : '<span class="dv-muted">–</span>';

            var band = o.flightBand
                ? '<span class="dv-val dv-band">' + esc(o.flightBand) + '</span>'
                : '<span class="dv-muted">–</span>';

            var temp = o.temp != null ? '<span class="dv-val">' + esc(o.temp) + '<span class="dv-unit">°C</span></span>' : '<span class="dv-muted">–</span>';

            var chipArr = o.tags.map(function (t) { return '<span class="dv-tag dv-tag-' + tagSeverity(t) + '">' + esc(t) + '</span>'; });
            o.extra.forEach(function (e) { chipArr.push('<span class="dv-tag dv-tag-info" title="ungeparstes Feld">' + esc(e) + '</span>'); });
            var chips = chipArr.length ? chipArr.join('') : '<span class="dv-muted">–</span>';

            return '<tr>'
                + '<td class="dv-time">' + esc(o.time) + '</td>'
                + '<td>' + wind + '</td>'
                + '<td class="dv-aloft-cell">' + buildAloft(o) + '</td>'
                + '<td>' + therm + '</td>'
                + '<td>' + cloud + '</td>'
                + '<td>' + rad + '</td>'
                + '<td>' + band + '</td>'
                + '<td>' + temp + '</td>'
                + '<td class="dv-warn-cell">' + chips + '</td>'
                + '</tr>';
        }).join('');
        return '<div class="dv-table-scroll"><table class="dv-table">' + head + '<tbody>' + body + '</tbody></table></div>';
    }

    function buildHtml(text) {
        var lines = (text || '').split('\n');
        var blocks = [];
        var curSection = null;   // {title, body:[]}
        var hourBuf = [];

        function flushHours() {
            if (hourBuf.length) { blocks.push({ type: 'table', rows: hourBuf }); hourBuf = []; }
        }
        function flushSection() {
            if (curSection) { blocks.push(curSection); curSection = null; }
        }

        lines.forEach(function (raw) {
            var line = raw.replace(/\s+$/, '');
            var hm = line.match(HOUR_RE);
            if (hm) { flushSection(); hourBuf.push(parseHour(hm[2], hm[3])); return; }
            flushHours();
            if (line.trim() === '') return;
            var title = sectionTitle(line);
            if (title !== null) { flushSection(); curSection = { type: 'section', title: title, body: [] }; return; }
            if (curSection) curSection.body.push(line);
            else blocks.push({ type: 'loose', line: line });   // Zeilen vor dem ersten Header
        });
        flushHours();
        flushSection();

        var parts = blocks.map(function (b) {
            if (b.type === 'table') return buildTable(b.rows);
            if (b.type === 'loose') return '<div class="dv-meta-top">' + colorizeTags(esc(b.line)) + '</div>';
            return '<section class="dv-section"><h4 class="dv-h">' + esc(b.title) + '</h4>'
                + renderBody(b.body) + '</section>';
        }).join('');

        var html = '<div class="dv-wrap">';
        html += '<div class="dv-note">Genau dieser Text geht an die KI. '
            + '<span class="dv-tag dv-tag-warn">WARN</span> grenzwertig · '
            + '<span class="dv-tag dv-tag-danger">DANGER/UNUSABLE</span> kritisch · '
            + '<span class="dv-tag dv-tag-ok">OK</span> unkritisch.</div>';
        html += parts;
        html += '<details class="dv-raw"><summary>1:1-Rohtext (genau wie an die KI)</summary>'
            + '<pre class="dv-pre">' + esc(text || '') + '</pre></details>';
        html += '</div>';
        return html;
    }

    function render(container, kind, id, dateStr) {
        if (!container) return;
        if (!id || !dateStr) {
            container.innerHTML = '<div class="dv-error">Kein ' + (kind === 'region' ? 'Region' : 'Spot') + '/Datum aktiv</div>';
            return;
        }
        container.innerHTML = '<div class="dv-loading">' + wcT('js.dv.loading') + '</div>';
        var url = '/api/' + kind + '-context/' + encodeURIComponent(id) + '/' + encodeURIComponent(dateStr);
        fetch(url, { headers: { 'Accept': 'application/json' } })
            .then(function (r) { return r.json(); })
            .then(function (d) {
                if (!d || d.error) {
                    container.innerHTML = '<div class="dv-error">' + esc((d && d.error) || wcT('js.av.no_data')) + '</div>';
                    return;
                }
                container.innerHTML = buildHtml(d.text || '');
            })
            .catch(function (err) {
                container.innerHTML = '<div class="dv-error">' + esc(wcT('js.error.prefix', { msg: (err && err.message) || err })) + '</div>';
            });
    }

    return { render: render };
})();
