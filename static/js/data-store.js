/**
 * data-store.js — Dedupe fuer die grossen API-Fetches.
 *
 * Problem: /api/analyses (bis mehrere MB) und /api/spots wurden beim Seitenladen
 * von mehreren Modulen unabhaengig geholt (index-Inline, map.js, region-map.js)
 * → 2-3 identische Downloads + doppeltes JSON-Parsen.
 *
 * Loesung: ein Modul-globales Promise pro Ressource. Erster Aufrufer startet den
 * Fetch, alle weiteren haengen sich dran. `force=true` (Tab-Fokus-Refetch,
 * expliziter Refresh) erneuert das Promise — dank ETag/304 ist das dann billig.
 *
 * Muss VOR map.js / region-map.js und den Inline-Skripten geladen sein
 * (ohne defer einbinden).
 */
(function () {
    'use strict';

    var promises = {};

    function getJson(url, force) {
        if (force || !promises[url]) {
            var p = fetch(url).then(function (r) {
                if (!r.ok) throw new Error('HTTP ' + r.status + ' ' + url);
                return r.json();
            });
            // Fehlgeschlagene Fetches nicht memoiseren, sonst bleibt der Fehler kleben.
            p.catch(function () { if (promises[url] === p) promises[url] = null; });
            promises[url] = p;
        }
        return promises[url];
    }

    window.wingcastData = {
        getAnalyses: function (force) { return getJson('/api/analyses', force); },
        getRegionAnalyses: function (force) { return getJson('/api/region-analyses', force); },
        getSpots: function (force) { return getJson('/api/spots', force); }
    };
})();
