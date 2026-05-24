/**
 * Admin-Only Spot-Suche: filtert window.flymap.markers, zoomt auf Treffer.
 * Wird nur eingebunden wenn admin_debug_active=True (siehe templates/index.html).
 */
(function () {
    'use strict';

    var input = document.getElementById('adminSpotSearchInput');
    var list = document.getElementById('adminSpotSearchResults');
    if (!input || !list) return;

    var MAX_RESULTS = 8;
    var ZOOM_LEVEL = 13;
    var activeIdx = -1;
    var currentHits = [];

    function getMarkers() {
        return (window.flymap && window.flymap.markers) || {};
    }

    function normalize(s) {
        return (s || '').toString().toLowerCase();
    }

    function search(query) {
        var q = normalize(query).trim();
        if (!q) return [];
        var markers = getMarkers();
        var hits = [];
        Object.keys(markers).forEach(function (name) {
            if (normalize(name).indexOf(q) >= 0) {
                var m = markers[name];
                var props = (m && m.featureProperties) || {};
                hits.push({ name: name, marker: m, region: props.region || '' });
            }
        });
        hits.sort(function (a, b) {
            var ai = normalize(a.name).indexOf(q);
            var bi = normalize(b.name).indexOf(q);
            if (ai !== bi) return ai - bi;
            return a.name.localeCompare(b.name);
        });
        return hits.slice(0, MAX_RESULTS);
    }

    function render(hits) {
        list.innerHTML = '';
        if (!hits.length) {
            list.hidden = true;
            return;
        }
        hits.forEach(function (h, i) {
            var li = document.createElement('li');
            li.setAttribute('role', 'option');
            li.dataset.idx = String(i);
            var nameSpan = document.createElement('span');
            nameSpan.textContent = h.name;
            li.appendChild(nameSpan);
            if (h.region) {
                var reg = document.createElement('span');
                reg.className = 'hit-region';
                reg.textContent = h.region;
                li.appendChild(reg);
            }
            li.addEventListener('mousedown', function (ev) {
                // mousedown statt click → kein blur-Race mit dem Input
                ev.preventDefault();
                select(i);
            });
            list.appendChild(li);
        });
        list.hidden = false;
        setActive(0);
    }

    function setActive(idx) {
        activeIdx = idx;
        Array.prototype.forEach.call(list.children, function (li, i) {
            li.classList.toggle('is-active', i === idx);
        });
    }

    function select(idx) {
        var hit = currentHits[idx];
        if (!hit || !hit.marker || !window.flymap || !window.flymap.map) return;
        var latlng = hit.marker.getLatLng();
        var map = window.flymap.map;
        map.setView(latlng, Math.max(map.getZoom(), ZOOM_LEVEL));
        // Visuelles Feedback: kurz Popup/Tooltip aufklappen
        if (typeof hit.marker.openPopup === 'function' && hit.marker.getPopup && hit.marker.getPopup()) {
            hit.marker.openPopup();
        } else if (typeof hit.marker.openTooltip === 'function') {
            hit.marker.openTooltip();
        }
        // Suche schliessen, aber Query stehen lassen fuer schnelle Folge-Suche
        list.hidden = true;
    }

    function update() {
        currentHits = search(input.value);
        render(currentHits);
    }

    input.addEventListener('input', update);
    input.addEventListener('focus', function () {
        if (input.value) update();
    });
    input.addEventListener('blur', function () {
        // kleine Verzoegerung, damit mousedown auf einer Option noch durchkommt
        setTimeout(function () { list.hidden = true; }, 120);
    });
    input.addEventListener('keydown', function (ev) {
        if (list.hidden && (ev.key === 'ArrowDown' || ev.key === 'ArrowUp')) {
            update();
            return;
        }
        if (ev.key === 'ArrowDown') {
            ev.preventDefault();
            if (currentHits.length) setActive((activeIdx + 1) % currentHits.length);
        } else if (ev.key === 'ArrowUp') {
            ev.preventDefault();
            if (currentHits.length) setActive((activeIdx - 1 + currentHits.length) % currentHits.length);
        } else if (ev.key === 'Enter') {
            ev.preventDefault();
            if (activeIdx >= 0) select(activeIdx);
        } else if (ev.key === 'Escape') {
            list.hidden = true;
            input.blur();
        }
    });
})();
