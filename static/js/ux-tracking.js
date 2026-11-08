/* Sichtbarkeits-Messung einzelner Bloecke (Spot-/Regionsansicht).
 *
 * wcTrackVisible(el, props) misst, wie lange ein Block im Bildschirm stand,
 * und sendet EINMAL pro Seitenaufruf das PostHog-Event `block_seen`
 * { ...props, ms_visible }, sobald die Seite verlassen oder der Tab
 * verborgen wird. Unter MIN_MS wird nichts gesendet (nur durchgewischt).
 *
 * "Sichtbar" heisst: mindestens die Haelfte des Blocks ist im Bild, ODER der
 * Block fuellt mindestens die Haelfte des Bildschirms. Die zweite Regel
 * braucht es fuer lange Bloecke (Analyse-Kette, Regionsliste), die auf dem
 * Handy nie zur Haelfte gleichzeitig sichtbar sind.
 *
 * Senden laeuft ueber window.wcTrack (No-op ohne PostHog, z.B. Admin oder
 * Analytics aus). Messung darf die Seite nie stoeren: alles in try/catch.
 * Event-Liste und Zweck: docs/ANALYTICS.md
 */
(function () {
    'use strict';

    var MIN_MS = 1000;
    var records = [];
    var observer = null;

    function now() {
        return (window.performance && performance.now) ? performance.now() : Date.now();
    }

    function stopTimer(rec, t) {
        if (rec.since !== null) {
            rec.ms += t - rec.since;
            rec.since = null;
        }
    }

    function isShown(entry) {
        if (!entry.isIntersecting) return false;
        var h = entry.boundingClientRect.height || 0;
        var vh = window.innerHeight || document.documentElement.clientHeight || 0;
        var seen = entry.intersectionRect.height || 0;
        if (h <= 0 || vh <= 0) return false;
        return seen >= 0.5 * h || seen >= 0.5 * vh;
    }

    function getObserver() {
        if (observer) return observer;
        var steps = [];
        for (var i = 0; i <= 20; i++) steps.push(i / 20);
        observer = new IntersectionObserver(function (entries) {
            var t = now();
            entries.forEach(function (entry) {
                var rec = entry.target.__wcVisible;
                if (!rec || rec.sent) return;
                rec.inView = isShown(entry);
                if (rec.inView && document.visibilityState !== 'hidden') {
                    if (rec.since === null) rec.since = t;
                } else {
                    stopTimer(rec, t);
                }
            });
        }, { threshold: steps });
        return observer;
    }

    function flush() {
        var t = now();
        records.forEach(function (rec) {
            if (rec.sent) return;
            stopTimer(rec, t);
            if (rec.ms < MIN_MS) return;
            rec.sent = true;
            var props = {};
            for (var k in rec.props) {
                if (Object.prototype.hasOwnProperty.call(rec.props, k)) props[k] = rec.props[k];
            }
            props.ms_visible = Math.round(rec.ms);
            if (window.wcTrack) window.wcTrack('block_seen', props, { transport: 'sendBeacon' });
        });
    }

    window.wcTrackVisible = function (el, props) {
        try {
            if (!el || el.__wcVisible || !('IntersectionObserver' in window)) return;
            var rec = { props: props || {}, ms: 0, since: null, inView: false, sent: false };
            el.__wcVisible = rec;
            records.push(rec);
            getObserver().observe(el);
        } catch (e) { /* Messung darf die Seite nie stoeren */ }
    };

    // Tab verborgen oder Seite verlassen: Zeit stoppen und einmal senden.
    // Handy-Browser feuern beim App-Wechsel oft nur visibilitychange, kein pagehide.
    document.addEventListener('visibilitychange', function () {
        try { if (document.visibilityState === 'hidden') flush(); } catch (e) {}
    });
    window.addEventListener('pagehide', function () {
        try { flush(); } catch (e) {}
    });
})();
