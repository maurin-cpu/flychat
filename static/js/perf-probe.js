/**
 * TEMPORÄRE Mess-Sonde für Karten-Ruckler (23.08.2026).
 *
 * Zweck: Ruckeln/Blockaden beim Zoomen liessen sich in Testbrowsern nicht
 * reproduzieren — diese Sonde misst dort, wo es auftritt: in der echten
 * Sitzung des Nutzers, auf dem echten Gerät.
 *
 * NICHT eingebunden — bewusst: sie soll im Normalbetrieb nicht mitlaufen.
 * Zum Messen diese Zeile in templates/index.html vor map.js einfuegen:
 *   <script defer src="{{ url_for('static', filename='js/perf-probe.js') }}"></script>
 * Dann:  ?perf=1 an die URL haengen (bleibt aktiv), ?perf=0 schaltet aus.
 *
 * Gemessen wird pro Zoom-Geste (zoomstart bis 1s nach zoomend):
 *   - Bildabstände (Median / schlechtestes Bild / Anzahl über 33ms)
 *   - blockierende Aufgaben über 50ms (PerformanceObserver 'longtask')
 * Ergebnis: kleine Anzeige unten rechts, Konsole (Praefix [WCPERF]) und
 * localStorage['wcPerf'] (letzte 10 Gesten) — damit auch spaeter auslesbar.
 *
 * Ergebnis der Messung vom 23.08.: 8.3ms Median, 0 von 236 Bildern ueber 33ms,
 * 0 Blockaden — das gemeldete "Ruckeln" war kein Bildausfall, sondern ein
 * Schaerfe-Sprung. Deshalb aufgehoben: solche Meldungen zuerst messen.
 */
(function () {
    'use strict';

    try {
        var q = new URLSearchParams(location.search).get('perf');
        if (q === '1') localStorage.setItem('wcPerfOn', '1');
        if (q === '0') localStorage.removeItem('wcPerfOn');
        if (localStorage.getItem('wcPerfOn') !== '1') return;
    } catch (e) { return; }

    var gaps = [], longTasks = [], last = 0, recording = false, stopAt = 0;
    var box = null;

    try {
        new PerformanceObserver(function (list) {
            if (!recording) return;
            list.getEntries().forEach(function (e) { longTasks.push(Math.round(e.duration)); });
        }).observe({ entryTypes: ['longtask'] });
    } catch (e) { /* Safari kennt longtask nicht */ }

    (function loop() {
        if (recording) {
            var t = performance.now();
            if (last) gaps.push(t - last);
            last = t;
            if (stopAt && t > stopAt) finish();
        }
        requestAnimationFrame(loop);
    })();

    function q50(a) { var s = a.slice().sort(function (x, y) { return x - y; }); return s.length ? s[Math.floor(s.length / 2)] : 0; }

    function finish() {
        recording = false; stopAt = 0;
        var res = {
            zeit: new Date().toISOString().slice(11, 19),
            bilder: gaps.length,
            median_ms: +q50(gaps).toFixed(1),
            schlechtestes_ms: +Math.max.apply(null, gaps.concat(0)).toFixed(1),
            ueber33ms: gaps.filter(function (x) { return x > 33; }).length,
            blockaden: longTasks.length,
            blockiert_ms: longTasks.reduce(function (a, b) { return a + b; }, 0),
            laengste_blockade_ms: Math.max.apply(null, longTasks.concat(0)),
            fenster: window.innerWidth + 'x' + window.innerHeight + '@' + (window.devicePixelRatio || 1),
            zoom: window.wcPerfMap ? +window.wcPerfMap.getZoom().toFixed(2) : null
        };
        console.log('[WCPERF]', JSON.stringify(res));
        try {
            var log = JSON.parse(localStorage.getItem('wcPerf') || '[]');
            log.push(res);
            localStorage.setItem('wcPerf', JSON.stringify(log.slice(-10)));
        } catch (e) { /* Speicher voll — egal */ }
        show(res);
    }

    function show(r) {
        if (!box) {
            box = document.createElement('div');
            box.style.cssText = 'position:fixed;right:8px;bottom:8px;z-index:99999;background:rgba(17,24,39,.92);' +
                'color:#fff;font:12px/1.45 ui-monospace,Menlo,monospace;padding:8px 10px;border-radius:8px;' +
                'pointer-events:none;white-space:pre;max-width:60vw';
            document.body.appendChild(box);
        }
        box.textContent =
            'Zoom-Messung (' + r.zeit + ')\n' +
            'Bild-Median      ' + r.median_ms + ' ms\n' +
            'schlechtestes    ' + r.schlechtestes_ms + ' ms\n' +
            'Bilder >33ms     ' + r.ueber33ms + ' von ' + r.bilder + '\n' +
            'Blockaden >50ms  ' + r.blockaden + ' (' + r.blockiert_ms + ' ms, laengste ' + r.laengste_blockade_ms + ')\n' +
            'Fenster ' + r.fenster + '  Zoom ' + r.zoom;
    }

    function start() {
        gaps = []; longTasks = []; last = 0; recording = true; stopAt = 0;
    }

    function armStop() {
        stopAt = performance.now() + 1500;   // 1.5s nach Gesten-Ende weitermessen
    }

    var tries = 0;
    (function hook() {
        var m = window.wingcastMap || window.regionMap;   // Spot- oder Regionen-Karte
        if (m && m.on) {
            window.wcPerfMap = m;
            m.on('zoomstart', start);
            m.on('zoomend', armStop);
            console.log('[WCPERF] Sonde aktiv — jetzt ein paar Mal zoomen.');
            return;
        }
        if (tries++ < 100) setTimeout(hook, 200);
    })();
})();
