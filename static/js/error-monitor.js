/**
 * Flychat Error Monitor
 * ----------------------
 * Fängt uncaught JavaScript-Errors und unhandled Promise-Rejections,
 * zeigt sie als sichtbaren roten Banner oben am Bildschirm.
 *
 * Zweck: Frontend-Bugs sollen NICHT mehr still in der Browser-Konsole
 * sterben. Sobald irgendwo ein TypeError, ReferenceError o.ä. auftritt,
 * sieht der User es sofort — ohne DevTools öffnen zu müssen.
 *
 * Wird automatisch via base.html in alle Seiten geladen.
 * Hat keine Abhängigkeiten und muss als erstes JS-File geladen werden,
 * damit es Errors aller späteren Skripte abfangen kann.
 */
(function () {
    'use strict';

    var BANNER_ID = 'flychat-error-banner';
    var AUTO_HIDE_MS = 12000;
    var hideTimer = null;

    function ensureBanner() {
        var existing = document.getElementById(BANNER_ID);
        if (existing) return existing;

        var banner = document.createElement('div');
        banner.id = BANNER_ID;
        banner.setAttribute('role', 'alert');
        banner.style.cssText = [
            'position:fixed',
            'top:0',
            'left:0',
            'right:0',
            'z-index:99999',
            'background:#dc2626',
            'color:#fff',
            'font-family:Inter,system-ui,sans-serif',
            'font-size:13px',
            'line-height:1.45',
            'padding:10px 44px 10px 16px',
            'box-shadow:0 4px 16px rgba(0,0,0,0.25)',
            'border-bottom:1px solid #991b1b',
            'display:none',
            'white-space:pre-wrap',
            'word-break:break-word',
            'max-height:40vh',
            'overflow-y:auto'
        ].join(';');

        var closeBtn = document.createElement('button');
        closeBtn.type = 'button';
        closeBtn.textContent = '\u00D7';
        closeBtn.setAttribute('aria-label', 'Schliessen');
        closeBtn.style.cssText = [
            'position:absolute',
            'top:6px',
            'right:10px',
            'background:transparent',
            'border:none',
            'color:#fff',
            'font-size:22px',
            'line-height:1',
            'cursor:pointer',
            'padding:4px 8px',
            'font-family:inherit'
        ].join(';');
        closeBtn.addEventListener('click', hideBanner);
        banner.appendChild(closeBtn);

        var msg = document.createElement('div');
        msg.id = BANNER_ID + '-msg';
        msg.style.paddingRight = '20px';
        banner.appendChild(msg);

        // Insert as first body child if body exists; otherwise queue until DOMContentLoaded
        if (document.body) {
            document.body.insertBefore(banner, document.body.firstChild);
        } else {
            document.addEventListener('DOMContentLoaded', function () {
                document.body.insertBefore(banner, document.body.firstChild);
            });
        }
        return banner;
    }

    function hideBanner() {
        var banner = document.getElementById(BANNER_ID);
        if (banner) banner.style.display = 'none';
        if (hideTimer) {
            clearTimeout(hideTimer);
            hideTimer = null;
        }
    }

    function showError(text) {
        var banner = ensureBanner();
        // If banner was inserted before body existed, the DOMContentLoaded
        // listener will append it later — fall back to a safe display call.
        if (!banner.parentNode) {
            document.addEventListener('DOMContentLoaded', function () {
                showError(text);
            });
            return;
        }
        var msg = document.getElementById(BANNER_ID + '-msg');
        if (msg) msg.textContent = text;
        banner.style.display = 'block';

        if (hideTimer) clearTimeout(hideTimer);
        hideTimer = setTimeout(hideBanner, AUTO_HIDE_MS);
    }

    function formatErrorEvent(ev) {
        // window.error event: ev.message, ev.filename, ev.lineno, ev.colno, ev.error
        var parts = ['\u26A0 JavaScript-Fehler'];
        var msg = ev && (ev.message || (ev.error && ev.error.message)) || 'Unbekannter Fehler';
        parts.push(msg);

        var file = ev && ev.filename;
        if (file) {
            // Shorten /static/js/foo.js to foo.js
            var short = file.split('/').pop().split('?')[0];
            var loc = short;
            if (ev.lineno) loc += ':' + ev.lineno;
            if (ev.colno) loc += ':' + ev.colno;
            parts.push(loc);
        }
        return parts.join('\n');
    }

    function formatRejection(ev) {
        var reason = ev && ev.reason;
        var parts = ['\u26A0 Unhandled Promise Rejection'];
        if (reason) {
            if (typeof reason === 'string') {
                parts.push(reason);
            } else if (reason.message) {
                parts.push(reason.message);
                if (reason.stack) {
                    var firstLine = String(reason.stack).split('\n')[1];
                    if (firstLine) parts.push(firstLine.trim());
                }
            } else {
                try { parts.push(JSON.stringify(reason)); }
                catch (e) { parts.push(String(reason)); }
            }
        }
        return parts.join('\n');
    }

    window.addEventListener('error', function (ev) {
        try {
            // Ignore ResizeObserver loop benign warnings
            if (ev.message && /ResizeObserver loop/.test(ev.message)) return;
            showError(formatErrorEvent(ev));
            // also forward to console for the developer
            if (window.console && console.error && ev.error) console.error(ev.error);
        } catch (e) { /* never let the monitor itself crash the page */ }
    });

    window.addEventListener('unhandledrejection', function (ev) {
        try {
            showError(formatRejection(ev));
            if (window.console && console.error) console.error('Unhandled rejection:', ev.reason);
        } catch (e) { /* swallow */ }
    });

    // Public API for manual reporting
    window.FlychatErrorMonitor = {
        report: function (text) { showError('\u26A0 ' + text); },
        hide: hideBanner
    };
})();
