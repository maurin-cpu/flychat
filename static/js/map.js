/**
 * Wingcast - Map + Meteogram Overlay
 */
(function () {
    'use strict';

    var map;
    var overlay = document.getElementById('meteogramOverlay');
    var chartContainer = document.getElementById('meteogramChart');
    var analyseViewContainer = document.getElementById('analyseViewChart');
    var tabsContainer = document.getElementById('meteogramTabs');
    var tabRow = document.getElementById('meteogramTabRow');
    var feedbackBar = document.getElementById('meteogramFeedback');
    var titleEl = document.getElementById('meteogramTitle');
    var infoEl = document.getElementById('meteogramInfo');
    // ratingBadgeEl / ratingValueEl entfernt (RATING_CONCEPT v1.3 §8.6) —
    // der Hero-Block im Spot-Panel zeigt Verdict + Stars + Score und macht
    // das alte 0-10 Tier-Badge redundant.
    var closeBtn = document.getElementById('meteogramClose');
    var shareBtn = document.getElementById('meteogramShare');
    var tooltipEl = document.getElementById('tooltip');
    var asideEl = document.getElementById('meteogramAside');
    var asideToggleBtn = document.getElementById('meteogramAsideToggle');
    var jsonDebugBtn = document.getElementById('meteogramJsonDebug');
    var jsonDebugActive = false;
    var hazardDebugBtn = document.getElementById('meteogramHazardDebug');
    var hazardDebugActive = false;
    var viewToggleEl = document.getElementById('meteogramViewToggle');
    var dataViewActive = false;

    // Modell-Mapping fuer das Surface-Tier-Voting (siehe docs/WETTERMODELLE.md).
    // Codes kommen vom Backend (api_weather → data_sources[date]).
    var MODEL_INFO = {
        ch1: { label: 'ICON-CH1', resolution: '1.1 km', color: '#2563eb' },
        ch2: { label: 'ICON-CH2', resolution: '2.1 km', color: '#0891b2' },
        d2:  { label: 'ICON-D2',  resolution: '2.2 km', color: '#d97706' },
        eu:  { label: 'ICON-EU',  resolution: '13 km',  color: '#64748b' },
    };
    var MODEL_INFO_UNKNOWN = { label: 'unbekannt', resolution: '', color: '#94a3b8' };

    function modelInfoFor(code) {
        return MODEL_INFO[code] || MODEL_INFO_UNKNOWN;
    }
    window.modelInfoFor = modelInfoFor;

    // Safer JSON fetch: prüft r.ok + Content-Type, liefert verständliche Fehlermeldung
    // statt "Unexpected token '<'..." wenn Server HTML (z.B. 500-Page) zurückgibt.
    function fetchJson(url) {
        return fetch(url, { headers: { 'Accept': 'application/json' } }).then(function (r) {
            var ctype = (r.headers.get('content-type') || '').toLowerCase();
            return r.text().then(function (txt) {
                if (!r.ok) {
                    var msg;
                    if (ctype.indexOf('application/json') >= 0) {
                        try { msg = (JSON.parse(txt) || {}).error; } catch (e) { msg = null; }
                    }
                    throw new Error(msg || wcT('js.map.http_loading', { status: r.status }));
                }
                if (ctype.indexOf('application/json') < 0) {
                    throw new Error(wcT('js.map.no_json_long'));
                }
                try {
                    return JSON.parse(txt);
                } catch (e) {
                    throw new Error('Antwort konnte nicht gelesen werden: ' + e.message);
                }
            });
        });
    }

    // Current meteogram state
    var currentWeather = null;
    var currentAltWind = null;
    var currentDates = [];
    var currentDateIdx = 0;
    var currentSpotName = '';
    var currentSpotProps = null;
    var currentSpotExperienceScore = null;
    var currentSpotExperienceStars = null;
    var currentSpotExperienceRating = null;
    var markersByName = {}; // Store marker references
    var spotRenderer = null; // gemeinsamer Canvas-Renderer fuer alle Spot-Marker
    var currentRefLayer = null; // Store reference points overlay
    var hideNotSafe = true; // Default: dim not_safe spots

    // Phase 1 (Tool-Use): Layers für Isochrone + User-Standort
    var isochroneLayer = null;
    var userLocationMarker = null;

    // ===== MAP INIT =====
    function initMap() {
        map = L.map('map', {
            center: [46.8, 8.3],
            zoom: 7,
            zoomControl: true,
            // Zoom-Raster fuer das ENDE einer Geste. Waehrend der Bewegung
            // ist der Zoom stufenlos (Pinch von Leaflet, Mausrad ueber
            // smooth-zoom.js) — nur der Ruhepunkt wird auf eine ganze Stufe
            // gelegt. Grund: Rasterkacheln sind ausschliesslich auf einer
            // ganzen Stufe 1:1 scharf; auf einem Zwischenwert misst sich bis
            // zu 26% weniger Kantenschaerfe. Der Weg dorthin wird animiert,
            // ist also ein Auslaufen und kein Sprung.
            zoomSnap: 1,
            zoomDelta: 0.5,             // nur fuer +/- Buttons und Tastatur
            // Das Mausrad uebernimmt smooth-zoom.js — Leaflets eigener
            // Rad-Zoom wird dort abgeschaltet, seine wheel*-Optionen sind
            // deshalb wirkungslos.
        });

        // Gemeinsame Tile-Optionen gegen graue Kacheln:
        // - updateWhenIdle:false — Kacheln schon WAEHREND des Pannens laden
        //   (Leaflet-Default auf Mobile: erst nach Gesten-Ende → grau beim Ziehen)
        // - keepBuffer:4 — mehr Nachbar-Kacheln behalten (Default 2), Zurueck-Pannen ohne Grau
        // - subdomains:'a' — EINE HTTP/2-Verbindung statt 4 TLS-Handshakes zu a-d
        //   (Sharding stammt aus HTTP/1.1-Zeiten und ist heute kontraproduktiv)
        // - updateWhenZooming — Kachelstufen schon WAEHREND der Zoom-Geste
        //   nachladen? Gemessen im echten Fenster (identische Bildrate, 8.3ms
        //   Median in beiden Faellen):
        //     aus: Bildschaerfe waehrend des Zooms 1.86, am Ende 2.08 — die
        //          Karte bleibt unscharf und schnappt am Gesten-Ende scharf.
        //          Dieses Nachschaerfen liest sich als Ruckler, obwohl kein
        //          einziges Bild ausfaellt.
        //     an:  2.06 durchgehend, kein Sprung — kostet aber gut das
        //          Dreifache an Kachel-Downloads (264 statt 80 pro Zoomfahrt).
        //   Deshalb: an, wo Bandbreite und Rechenleistung da sind; aus auf
        //   kleinen Screens, im Sparmodus und bei langsamer Verbindung.
        var conn = navigator.connection || {};
        var sparsam = window.innerWidth <= 900 || conn.saveData === true ||
                      /(^|-)(2g|3g)$/.test(conn.effectiveType || '');
        // minZoom:0 ist PFLICHT, sobald irgendein Layer ein eigenes minZoom
        // setzt (hier die Vorschau-Unterlage mit 9): Leaflet bildet die
        // Mindest-Zoomstufe der KARTE aus den Layern, und zwar nur aus denen,
        // die eines deklarieren. Ohne diese Zeile wurde map.getMinZoom() zu 9 —
        // die Startansicht konnte nicht mehr auf Stufe 8 herauszoomen und
        // zeigte statt aller 494 Spots nur noch 346.
        var tileOpts = { updateWhenIdle: false, updateWhenZooming: !sparsam, keepBuffer: 4, minZoom: 0 };

        // Grundkarte in zwei Phasen (Begruendung: vector-basemap.js, Kopf):
        // SOFORT der bewaehrte Raster-Stack — Karte augenblicklich sichtbar
        // und bedienbar. Im Leerlauf laedt die VEKTOR-Karte (MapLibre GL,
        // GPU-gezeichnet: 0.1-1% grau beim Ziehen statt 60-87%, Zwischenzoom
        // scharf, gleiche Optik) dazu und loest die Carto-Rasterebenen ab,
        // sobald sie ihr 'load' meldet. Schlaegt irgendetwas fehl, bleibt
        // einfach der Raster-Stack — selbstheilend, kein Fehler beim Nutzer.
        var cartoRasterEbenen = [];

        // Vorschau-Unterlage: dieselbe Karte, aber grob (nie feiner als Stufe 9)
        // und weit gepuffert. Sie liegt unter allem und ist praktisch immer
        // geladen — dadurch erscheint dort, wo die scharfen Kacheln noch fehlen,
        // ein unscharfes Kartenbild statt der grauen Flaeche. Die paar groben
        // Kacheln kosten fast nichts, weil sie ueber viele Zoomstufen halten.
        // maxNativeZoom 6: die ganze Schweiz sind auf Stufe 6 nur ein paar
        // Kacheln — die sind nach dem ersten Laden praktisch immer im Cache
        // und decken JEDE Zoomrichtung ab. Mit der frueheren Stufe-9-Unterlage
        // (minZoom 9) blieb das RAUSzoomen unter Stufe 9 ungedeckt: genau da
        // sah man wieder graue Kacheln, solange die Vektor-Karte noch nicht
        // uebernommen hat.
        cartoRasterEbenen.push(L.tileLayer('https://a.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}.png', {
            maxNativeZoom: 6, maxZoom: 18, minZoom: 0, keepBuffer: 16,
            updateWhenIdle: false, updateWhenZooming: false,
            className: 'wc-tiles-preview',
        }).addTo(map));

        // Basis ohne Labels. Mobil in Normalaufloesung ({r} weglassen): Retina-
        // Kacheln (@2x) vervierfachen die Pixel-Dekodier-/Rasterlast — bei der
        // flachen Farbflaechen-Grundkarte auf kleinem Display nicht sichtbar,
        // beim Pannen aber deutlich spuerbar. Labels-Layer bleibt @2x (Textschaerfe).
        var baseTileUrl = (window.innerWidth <= 900)
            ? 'https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}.png'
            : 'https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png';
        cartoRasterEbenen.push(L.tileLayer(baseTileUrl, Object.assign({
            attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>',
            subdomains: 'a',
            maxZoom: 18,
        }, tileOpts)).addTo(map));

        // Topografie (Schummerung) — zeigt Hügel/Berge ohne das Design zu überladen.
        // NICHT auf kleinen Screens: der halbtransparente Zusatz-Layer verdreifacht
        // die Compositing-Arbeit pro Frame — auf Handys die Hauptursache fuer
        // "Bild stockt kurz" beim Zoomen/Ziehen. Auf dem kleinen Display ist die
        // Schummerung ohnehin kaum sichtbar.
        // Beim Zoomen sah man rechteckige helle Bloecke ("weisse Kacheln"):
        // Die Schummerung ist die EINZIGE Rasterebene, die nach der
        // Vektor-Uebernahme bestehen bleibt (sie steht nicht in
        // cartoRasterEbenen), und sie deckt 45%. Wo ihre Kacheln beim Zoomen
        // noch fehlen, ist die Karte schlagartig heller — und weil Kacheln
        // rechteckig sind, sieht man genau das Muster.
        // Zwei Massnahmen, beide ohne zweite Ebene (die wuerde sich mit ihrer
        // eigenen Halbtransparenz aufaddieren und die Karte verdunkeln):
        //   updateWhenZooming: false → waehrend der Geste werden die
        //     vorhandenen Kacheln gedehnt statt neue angefordert; nachgeladen
        //     wird erst, wenn die Bewegung steht. Bei einem weichen Relief mit
        //     45% Deckung faellt die Dehnung nicht auf — anders als bei der
        //     Grundkarte mit Beschriftung (Schaerfe-Entscheid 23.08.).
        //   keepBuffer 8 → mehr Kacheln bleiben ausserhalb des Bildes stehen,
        //     das deckt kleine Zoom- und Pan-Spruenge ohne Nachladen ab.
        // Zwei Varianten wurden gemessen und VERWORFEN, beide machten es
        // schlechter: eine feinere Reserve (maxNativeZoom 9) ist beim
        // Rauszoomen selbst noch nicht geladen (Ueberhelligkeit 9.44 statt
        // 2.49), und eine schwaecher deckende Reserve (62%) fuellt die Luecke
        // nur halb (5.83). Sie muss grob UND voll deckend sein.
        //
        // Dazu eine grobe Reserve-Schummerung darunter, nach demselben Muster
        // wie die Vorschau-Unterlage der Grundkarte: Stufe 7 sind fuer die
        // Schweiz eine Handvoll Kacheln, die nach dem ersten Laden immer da
        // sind und JEDE Zoomstufe abdecken. Damit bleibt beim Zoomen nie eine
        // Flaeche ohne Relief.
        //
        // Der Kniff gegen das Aufaddieren: beide Ebenen zeichnen mit voller
        // Deckung in ein EIGENES Pane, und erst das Pane ist zu 45%
        // durchsichtig. Die Hillshade-Kacheln sind undurchsichtige Graubilder,
        // die scharfe Ebene ueberdeckt die grobe also vollstaendig. Lege man
        // stattdessen zwei je 45%-Ebenen uebereinander, ergaebe das dort, wo
        // beide liegen, 70% — die Karte wuerde fleckig dunkler.
        if (window.innerWidth > 900) {
            var schummerPane = map.createPane('schummerPane');
            schummerPane.style.zIndex = '350';      // ueber der Grundkarte, unter Labels (400)
            schummerPane.style.opacity = '0.45';
            schummerPane.style.pointerEvents = 'none';
            var schummerUrl = 'https://services.arcgisonline.com/ArcGIS/rest/services/Elevation/World_Hillshade/MapServer/tile/{z}/{y}/{x}';
            L.tileLayer(schummerUrl, {
                pane: 'schummerPane', maxNativeZoom: 7, maxZoom: 18, minZoom: 0,
                keepBuffer: 16, updateWhenIdle: false, updateWhenZooming: false,
            }).addTo(map);
            // Die scharfe Ebene laedt WAEHREND des Zoomens nach (kein
            // updateWhenZooming:false mehr): die Reserve darunter deckt jede
            // Luecke ab, also gibt es keinen Grund mehr zu warten. Mit dem
            // Warten blieb das grobe Relief unnoetig lange stehen — sichtbar
            // als „beim Rauszoomen ist ein Teil noch unscharf".
            L.tileLayer(schummerUrl, Object.assign({}, tileOpts, {
                pane: 'schummerPane',
                attribution: 'Hillshade &copy; <a href="https://www.esri.com/">Esri</a>',
                maxZoom: 16,
                keepBuffer: 8,
            })).addTo(map);
        }

        // Labels über der Schummerung (der Vektor-Stil bringt eigene mit,
        // deshalb gehoert auch diese Ebene zu den abloesbaren Raster-Ebenen)
        cartoRasterEbenen.push(L.tileLayer('https://{s}.basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}{r}.png', Object.assign({
            subdomains: 'a',
            maxZoom: 18,
        }, tileOpts)).addTo(map));

        // Vektor-Karte im Leerlauf dazuladen; uebernimmt erst wenn fertig.
        if (typeof window.wingcastVectorBasemap === 'function') {
            window.wingcastVectorBasemap(map, {
                onReady: function () {
                    cartoRasterEbenen.forEach(function (l) {
                        try { map.removeLayer(l); } catch (e) { /* egal */ }
                    });
                    cartoRasterEbenen = [];
                },
            });
        }

        // Canvas-Pane fuer Spot-Marker: ueber OSM-Peaks (450), Position des
        // frueheren markerPane-Stacks. padding 0.5 = Canvas deckt 2x Viewport,
        // Pan innerhalb des Puffers braucht kein Neuzeichnen. tolerance 6 =
        // zusaetzlicher Hit-Spielraum fuer Touch.
        map.createPane('spotPane').style.zIndex = '600';

        // Leaflets Canvas-Renderer skaliert seine Zeichenflaeche waehrend einer
        // Zoombewegung per CSS mit. Fuer die Spots ist das doppelt schaedlich:
        // damit sie gleich gross BLEIBEN, muessten sie um 1/Faktor kleiner
        // gezeichnet werden — und werden anschliessend wieder aufgeblasen. Bei
        // Faktor 2 sieht man sie also in halber Aufloesung: unscharf, genau
        // waehrend man hinschaut.
        // Deshalb hier: bei jeder Zoomaenderung NEU PROJIZIEREN statt skalieren
        // (_reset = Flaeche auf die aktuelle Ansicht setzen, alle Marker neu
        // verorten, neu zeichnen). Die Spots sind damit in jeder Phase 1:1
        // gezeichnet — immer scharf, unabhaengig vom Zoomfaktor.
        // 'zoom' feuert bei jedem map._move, also pro Bild waehrend Pinch und
        // Mausrad-Gleiten. Die kurzen CSS-Animationen (Zoom-Buttons, Auslauf
        // am Gesten-Ende) laufen weiter ueber zoomanim + Groessen-Kompensation.
        var SpotCanvas = L.Canvas.extend({
            _onZoom: function () { this._reset(); }
        });
        spotRenderer = new SpotCanvas({ pane: 'spotPane', padding: 0.5, tolerance: 6 });

        // ===== ZOOM-KOMPENSATION (konstante Spot-Groesse, live) =====
        // Leaflet skaliert den Spot-Canvas waehrend jeder Zoom-Geste per CSS
        // mit der Karte mit. Damit die Spots dabei NICHT mitwachsen, wird der
        // gezeichnete Radius laufend um 1/scale gegenskaliert — die Groesse
        // passt sich WAEHREND des Zoomens an, nicht danach.
        //
        // Der Faktor wird GEMESSEN, nicht aus Leaflet-Events geschaetzt. Die
        // frueheren Schaetzungen stimmten waehrend der Geste, aber nicht an
        // deren Ende — zwei Bruchstellen, beide als Groessen-Pop sichtbar:
        //   1. zoomend schaltete die Kompensation sofort ab, obwohl Leaflet den
        //      Canvas danach noch ~250ms weiter animiert.
        //   2. Der Release-Frame des Pinch landete im Pinch-Zweig, weil Leaflet
        //      ihn mit noUpdate = options.zoomSnap (0.25 → truthy) feuert.
        // Gemessen wird direkt im Zeichenpfad (compFactor/currentSpotScale, oben)
        // — Zeichnung und Kartenzustand koennen so gar nicht auseinanderlaufen.
        // Diese Schleife sorgt nur dafuer, dass waehrend der Geste ueberhaupt
        // neu gezeichnet wird.
        function compRedraw() {
            if (spotRenderer && spotRenderer._redraw) spotRenderer._redraw();
        }
        function compCancel() {
            if (_zoomComp.raf) { cancelAnimationFrame(_zoomComp.raf); _zoomComp.raf = 0; }
            _zoomComp.running = false;
        }
        // EINE rAF-Schleife fuer die ganze Zoomphase inkl. Auslauf: hoechstens
        // ein Redraw pro Frame, und nur wenn sich sichtbar etwas aendert.
        function compStep() {
            _zoomComp.raf = 0;
            _zoomComp.stamp = 0;            // frische Messung erzwingen
            var f = compFactor();
            // Nur zeichnen, wenn es sichtbar etwas aendert (0.5% ≈ 1/25 Pixel).
            if (Math.abs(f - _zoomComp.drawn) > _zoomComp.drawn * 0.005) {
                _zoomComp.drawn = f;
                compRedraw();
            }
            if (_zoomComp.ended) {
                var settled = Math.abs(f - 1) < 0.002;
                // Notbremse NUR nach dem Gesten-Ende: die Geste selbst darf
                // beliebig lange dauern (langsamer Pinch). Ein Deckel, der
                // waehrend der Geste greift, stellt die Kompensation mitten im
                // Zoomen ab — dann stehen alle Spots schlagartig in voller
                // Gestenvergroesserung da. Und selbst die Notbremse setzt den
                // Faktor NICHT auf 1: compFactor misst danach weiter je
                // Zeichnung, das laeuft ohne Sprung aus.
                var overdue = _zoomComp.t0 && (performance.now() - _zoomComp.t0) > 1500;
                if (settled || overdue) {
                    _zoomComp.running = false;
                    if (settled) {
                        _zoomComp.factor = 1;
                        if (_zoomComp.drawn !== 1) { _zoomComp.drawn = 1; compRedraw(); }
                    }
                    return;
                }
            }
            _zoomComp.raf = requestAnimationFrame(compStep);
        }
        function compStart() {
            if (_zoomComp.running) return;
            _zoomComp.running = true;
            _zoomComp.raf = requestAnimationFrame(compStep);
        }
        // Stufenloser Mausrad-Zoom (smooth-zoom.js, geteilt mit der
        // Regionen-Karte). Ohne das Modul bleibt Leaflets Standard aktiv.
        if (typeof window.wingcastSmoothWheelZoom === 'function') window.wingcastSmoothWheelZoom(map);

        // Jede Transform-Aenderung macht die Messung ungueltig — Leaflet setzt
        // sie in seinen eigenen Handlern fuer dieselben Events. 'zoom' deckt
        // zusaetzlich das Gleiten des Mausrad-Zooms ab (map._move mit pinch).
        map.on('zoom zoomanim zoomend viewreset', compInvalidate);
        spotRenderer.on('update', compInvalidate);
        map.on('zoomstart', function () {
            _zoomComp.ended = false;
            _zoomComp.t0 = 0;          // waehrend der Geste keine Frist
            compStart();
        });
        map.on('zoomend', function () {
            // NICHT sofort abschalten: Leaflet animiert den Transform u.U. noch
            // weiter. Die Schleife laeuft aus, sobald gemessen 1.0 anliegt.
            _zoomComp.ended = true;
            _zoomComp.t0 = performance.now();
            compStart();
        });
        map.on('unload', compCancel);

        // Expose the Leaflet map instance under a non-colliding name.
        // `window.map` is unusable because `<div id="map">` auto-creates an
        // HTML implicit global pointing to the DIV element, which has no
        // invalidateSize() method and would crash sidebar resize handlers.
        window.wingcastMap = map;

        // Re-fit to all spots — needed on mobile where #map is initially
        // display:none and the original fitBounds runs against a 0-size container.
        window.wingcastFitToSpots = function () {
            if (!window.wingcastMap || !window.wingcastSpotsBounds) return;
            if (!window.wingcastSpotsBounds.isValid()) return;
            try {
                window.wingcastMap.fitBounds(window.wingcastSpotsBounds, { padding: [20, 20] });
            } catch (e) { /* ignore */ }
        };

        loadSpots();

        // Mini-Legende — geteilt mit Region-Karte ueber rating-info.js
        if (typeof window.buildRatingMiniLegend === 'function') {
            window.buildRatingMiniLegend(L, 'bottomleft').addTo(map);
        }

        // OSM Peaks/Pässe/Sättel — geteiltes Modul (osm-peaks-layer.js).
        // Steuerbar via Admin-UI: config.SHOW_OSM_PEAKS → window.SHOW_OSM_PEAKS.
        if (window.SHOW_OSM_PEAKS && window.WingcastOsmPeaks) {
            window.WingcastOsmPeaks.attach(map);
        }

        // Niederschlags-Referenzpunkte (16 pro Region) — eigener Layer.
        // Gekoppelt an SHOW_REFERENCE_POINTS — sichtbar sobald die 7 Haupt-RPs aktiv sind.
        if ((window.SHOW_REFERENCE_POINTS || window.SHOW_PRECIP_REFPOINTS) && window.WingcastPrecipRefpoints) {
            window.WingcastPrecipRefpoints.attach(map);
        }
    }

    // ===== DIRECTION PARSER =====
    // Liefert Array von [start, end]-Arcs (mehrere bei disjoint mit '/').
    // Unterstuetzt PGE-synthetisierte Strings:
    //   'O-SO-S-SW-W'   → ein Arc 90°-270° (first..last)
    //   'NW-N-NO'       → ein Arc 315°-45° (Wraparound)
    //   'S/N'           → zwei Arcs (S-Sektor + N-Sektor)
    //   'NO-O/W-NW'     → zwei Arcs
    function getDirAngles(dirStr) {
        if (!dirStr) return null;
        var dirs = {
            'N': 0, 'NNO': 22.5, 'NNE': 22.5, 'NO': 45, 'NE': 45, 'ONO': 67.5, 'ENE': 67.5,
            'O': 90, 'E': 90, 'OSO': 112.5, 'ESE': 112.5, 'SO': 135, 'SE': 135, 'SSO': 157.5, 'SSE': 157.5,
            'S': 180, 'SSW': 202.5, 'SW': 225, 'WSW': 247.5,
            'W': 270, 'WNW': 292.5, 'NW': 315, 'NNW': 337.5
        };
        var arcs = [];
        var disjointParts = dirStr.toUpperCase().split('/');
        for (var d = 0; d < disjointParts.length; d++) {
            var run = disjointParts[d].trim();
            if (!run) continue;
            var parts = run.split('-');
            var angles = [];
            for (var i = 0; i < parts.length; i++) {
                var a = dirs[parts[i].trim()];
                if (a !== undefined) angles.push(a);
            }
            if (angles.length === 0) continue;
            // parts kommen clockwise-geordnet aus spots._sectors_to_windrichtung
            // (PGE_SECTOR_ORDER). Span = anzahl-sektoren * 45°, beginnend 22.5°
            // vor dem ersten Mittelpunkt. Echtes Wraparound (z.B. 'NW-N-NE')
            // bleibt erhalten (292.5° -> 427.5°), eine breite Nicht-Wraparound-
            // Sequenz (z.B. 'O-SO-S-SW-W') wird NICHT faelschlich gespiegelt.
            var start = angles[0] - 22.5;
            var end = start + angles.length * 45;
            arcs.push([start, end]);
        }
        return arcs.length ? arcs : null;
    }

    // Diskrete Rating-Tints — Palette v2 (Option C, Mai 2026): green-Band alignt
    // mit Thermik-Kacheln fuer Rating 3-5 (Lime/Mint-Green/Cyan), Rating 1+2 in
    // Pastell-Mint/Mint. amber bleibt Yellow→Brown. Identisch zu region-map.js,
    // shared-glyph.js, briefing.js. Source of Truth: docs/RATING_FARBKONZEPT.md.
    function getRatingTint(band, rating) {
        var r = Math.max(1, Math.min(5, rating | 0));
        if (band === 'green') {
            // v3.2 Royal Premium: Sky-100 → Sky-200 → Lime → Green-500 → Violet
            return {
                fill:   ['#e0f2fe', '#bae6fd', '#BEF264', '#22c55e', '#a78bfa'][Math.min(4, r - 1)],
                stroke: ['#38bdf8', '#0ea5e9', '#65a30d', '#15803d', '#6d28d9'][Math.min(4, r - 1)]
            };
        }
        if (band === 'amber') {
            return {
                fill:   ['#fef08a', '#facc15', '#f97316', '#c2410c', '#7c2d12'][Math.min(4, r - 1)],
                stroke: ['#ca8a04', '#a16207', '#9a3412', '#7c2d12', '#431407'][Math.min(4, r - 1)]
            };
        }
        return null;
    }

    // ===== STYLE SYSTEM (RATING_CONCEPT v1.3 §8.2 — Single-Glyph) =====
    // safetyBand: 'green' | 'amber' | 'red' | 'no_data' | 'default'
    // experienceStars: 0..5 (integer)
    function mapSafetyBandToStyle(band) {
        if (band === 'violet') return {
            // Palette v3.2 "Royal Premium": Premium-Tier = Violet-400 (Legendary).
            fill: '#a78bfa', stroke: '#6d28d9',
            label: 'Top'
        };
        if (band === 'green') return {
            fill: '#22c55e', stroke: '#15803d',
            label: wcT('js.safety.safe')
        };
        if (band === 'amber') return {
            fill: '#f59e0b', stroke: '#92400e',
            label: wcT('js.safety.caution')
        };
        if (band === 'red') return {
            fill: '#ef4444', stroke: '#991b1b',
            label: wcT('js.safety.not_flyable')
        };
        if (band === 'no_data') return {
            fill: '#9ca3af', stroke: '#6b7280',
            label: wcT('js.av.no_data')
        };
        // default / unanalyzed
        return {
            fill: '#6b7280', stroke: '#4b5563',
            label: ''
        };
    }

    // Legacy-Mapping fuer alte Cache-Daten ohne safety_band-Feld.
    // Erlaubt graceful migration — entfernt sobald alle Caches reanalysiert sind.
    function legacySafetyBand(safetyStatus) {
        if (safetyStatus === 'not_safe') return 'red';
        if (safetyStatus === 'conditional') return 'amber';
        if (safetyStatus === 'safe') return 'green';
        if (safetyStatus === 'no_data' || safetyStatus === 'error') return 'no_data';
        return 'default';
    }

    // ===== CANVAS-MARKER (RATING_ARCHITECTURE v2.0) =====
    // Alle 494 Spots werden auf EINE Canvas-Flaeche gezeichnet statt als 494
    // DOM-Elemente (~4000 SVG-Knoten). Grund: bei vielen sichtbaren Spots war
    // Pannen/Zoomen spuerbar zaeher als bei wenigen — der Browser musste die
    // aufgeblaehte Marker-Pane rastern. Canvas = ein Element, egal wie viele.
    // Klick/Tooltip/Popup/Suche laufen unveraendert ueber Leaflet: SpotMarker
    // ist eine L.CircleMarker-Subklasse (Hit-Test = Kreis mit SPOT_HIT_RADIUS),
    // nur das Zeichnen ist durch drawSpot ersetzt.
    // Redraw-Region pro Marker (deckt Maximalgroesse inkl. Windsektor ab).
    // Hit-Test ist separat (SpotMarker._containsPoint), sonst waere das Tap-Ziel
    // absurd gross.
    var SPOT_DRAW_BOUNDS = 56;

    // Spots haben auf JEDER Zoomstufe dieselbe Bildschirmgroesse. Konstant zu
    // bleiben ist aber nicht gratis: Leaflet skaliert den Canvas waehrend der
    // Zoom-Geste mit der Karte mit. Deshalb wird der gezeichnete Radius live um
    // genau denselben Faktor GEGENskaliert (_zoomComp) — die Groesse passt sich
    // also waehrend des Zoomens laufend an, statt hinterher zu springen.
    // Originalgroessen (unveraendert seit jeher): Handy groesser als Desktop.
    function spotRadius(highlighted) {
        var isMobile = window.innerWidth <= 600;
        return highlighted ? (isMobile ? 9 : 8) : (isMobile ? 8 : 7);
    }
    var _zoomComp = { factor: 1, drawn: 1, stamp: 0, raf: 0, running: false, ended: true, t0: 0 };

    // Tatsaechlich anliegende CSS-Skalierung des Spot-Canvas. getComputedStyle
    // liefert waehrend einer Transition den INTERPOLIERTEN Wert — deckt Pinch
    // (Inline-Transform pro Frame) und Wheel/Buttons (Transition) gleich ab.
    function currentSpotScale() {
        var el = spotRenderer && spotRenderer._container;
        if (!el || typeof DOMMatrixReadOnly === 'undefined') return 1;
        var t = getComputedStyle(el).transform;
        if (!t || t === 'none') return 1;
        try {
            var a = new DOMMatrixReadOnly(t).a;
            return (isFinite(a) && a > 0) ? a : 1;
        } catch (err) { return 1; }
    }

    // Der Kompensationsfaktor wird beim ZEICHNEN gemessen (hoechstens alle 4ms
    // neu), nicht vorab gesetzt. Damit kann kein Zeichenpfad mit einem
    // veralteten Wert malen — auch nicht Leaflets eigene Redraws am Gesten-Ende,
    // die frueher einen Frame lang die volle Gestenvergroesserung zeigten.
    // Im Ruhezustand kostet das nichts: Faktor 1, keine Messung.
    function compFactor() {
        if (_zoomComp.factor === 1 && !_zoomComp.running && !(map && map._animatingZoom)) return 1;
        var now = performance.now();
        if (now - _zoomComp.stamp >= 4) {
            _zoomComp.stamp = now;
            _zoomComp.factor = 1 / currentSpotScale();
        }
        return _zoomComp.factor;
    }

    // Messung verwerfen: die naechste Zeichnung misst frisch. Noetig bei JEDER
    // Transform-Aenderung, sonst zeichnet ein Durchgang, der innerhalb des
    // 4ms-Fensters startet, mit dem alten Wert — genau das liess am Gesten-Ende
    // einen Frame lang alle Spots in voller Gestenvergroesserung stehen.
    // Innerhalb EINES Durchgangs bleibt der Wert dagegen stabil (alle Marker
    // gleich gross), weil die erste Messung den Zeitstempel neu setzt.
    function compInvalidate() { _zoomComp.stamp = 0; }

    // ===== SPRITE-CACHE =====
    // Ein Spot besteht aus bis zu 8 Pfaden plus einer Ziffer (Text ist der mit
    // Abstand teuerste Canvas-Aufruf). Waehrend der Zoom-Geste muessten die 494
    // Marker das pro Frame neu aufbauen — gemessen ~4ms/Frame auf dem Desktop,
    // ein Vielfaches auf dem Handy: das war die Ruckel-Ursache.
    // Stattdessen wird jedes Erscheinungsbild EINMAL in ein kleines Offscreen-
    // Canvas gezeichnet und danach nur noch gestempelt (drawImage = GPU-Blit).
    // Der Cache ist geteilt: gleich aussehende Spots benutzen dasselbe Sprite.
    var SPRITE_SS = 2;            // Sprite-Aufloesung (wie Leaflets Retina-Canvas)
    var SPRITE_CACHE_MAX = 600;   // Deckel gegen unbegrenztes Wachstum
    var spotSprites = new Map();

    function spriteKey(layer) {
        var props = layer.featureProperties || {};
        return (layer.currentSafetyBand || 'default')
            + '|' + (typeof layer.currentRating === 'number' ? Math.floor(layer.currentRating) : 0)
            + '|' + (layer._wcHighlight ? 1 : 0)
            + '|' + (layer._wcHover ? 1 : 0)
            + '|' + (props.windrichtung || '')
            + '|' + (window.innerWidth <= 600 ? 'm' : 'd');
    }

    // Verwirft alle Sprites (Font nachgeladen, Breakpoint gewechselt) und
    // zeichnet neu — sonst blieben alte Glyphen/Groessen eingebrannt.
    function invalidateSpotSprites() {
        spotSprites.clear();
        if (spotRenderer && spotRenderer._redraw && spotRenderer._map) spotRenderer._redraw();
    }

    function spriteFor(layer) {
        var key = spriteKey(layer);
        var sprite = spotSprites.get(key);
        if (sprite) return sprite;
        var highlighted = !!layer._wcHighlight;
        var radius = spotRadius(highlighted) + (layer._wcHover ? 1 : 0);
        // Aussenradius: Windsektor (r+9) + Schattenversatz/Strich → 11 Reserve.
        var pad = radius + 11;
        var cv = document.createElement('canvas');
        cv.width = cv.height = Math.ceil(pad * 2 * SPRITE_SS);
        var sctx = cv.getContext('2d');
        sctx.scale(SPRITE_SS, SPRITE_SS);
        sctx.translate(pad, pad);
        drawSpot(sctx, 0, 0, layer);
        sprite = { canvas: cv, pad: pad };
        if (spotSprites.size >= SPRITE_CACHE_MAX) spotSprites.clear();
        spotSprites.set(key, sprite);
        return sprite;
    }

    // Sprites verwerfen, sobald die Web-Font wirklich geladen ist (sonst waere
    // die Fallback-Schrift in die Ziffern eingebrannt) und wenn der Handy/
    // Desktop-Breakpoint wechselt (andere Spot-Groesse).
    if (document.fonts && document.fonts.ready && document.fonts.ready.then) {
        document.fonts.ready.then(invalidateSpotSprites).catch(function () {});
    }
    var _spotBreakpointMobile = window.innerWidth <= 600;
    window.addEventListener('resize', function () {
        var m = window.innerWidth <= 600;
        if (m !== _spotBreakpointMobile) { _spotBreakpointMobile = m; invalidateSpotSprites(); }
    });

    // Laeuft gerade eine Zoombewegung? Nicht am Kompensationsfaktor ablesbar:
    // seit SpotCanvas pro Bild neu projiziert (statt den Canvas zu skalieren)
    // steht die CSS-Skalierung waehrend der ganzen Geste auf 1, der Faktor also
    // ebenfalls. Deshalb die Gesten-Flags direkt fragen.
    function zoomBewegtSich() {
        return _zoomComp.running || !_zoomComp.ended || !!(map && map._animatingZoom);
    }

    // Zeichnen auf dem Karten-Canvas: ein einziger Blit, live gegenskaliert.
    function stampSpot(ctx, x, y, layer) {
        var sprite = spriteFor(layer);
        var comp = compFactor();
        var half = sprite.pad * comp;
        var d = half * 2;
        if (!zoomBewegtSich()) {
            // In RUHE auf ganze Pixel legen: sonst liegt der Marker auf krummen
            // Koordinaten, drawImage interpoliert und er wird weich, obwohl er
            // in voller Aufloesung vorliegt (gemessen: staerkste Kante 108
            // statt 169).
            var dr = Math.round(d);
            ctx.drawImage(sprite.canvas, Math.round(x - half), Math.round(y - half), dr, dr);
            return;
        }
        // Waehrend der BEWEGUNG darf nicht gerundet werden. Die Grundkarte
        // gleitet stufenlos, gerundete Marker springen dagegen in Ganzpixel-
        // Stufen: gemessen ein Versatz zwischen Spot und Karte von bis zu
        // 0.89px, der pro Bild umschlaegt — sichtbar als Zappeln der Spots,
        // am deutlichsten kurz vor dem Einrasten, wo der Zoom nur noch
        // kriecht und mehrere Bilder auf demselben ganzen Pixel liegen.
        // Die Unschaerfe im Bruchteil eines Pixels faellt in Bewegung nicht auf.
        ctx.drawImage(sprite.canvas, x - half, y - half, d, d);
    }

    // Zeichnet einen Spot ins Sprite — Optik identisch zum frueheren SVG-DivIcon:
    // Windsektor(e), Highlight-Glow, Schatten, weisser Grund, Band-Kreis, Glyphe.
    function drawSpot(ctx, x, y, layer) {
        var band = layer.currentSafetyBand || 'default';
        var rating = (typeof layer.currentRating === 'number') ? Math.floor(layer.currentRating) : 0;
        if (rating === 6) rating = 5; // Migration-Tolerance: alter Cache-Wert 6 → 5
        rating = Math.max(0, Math.min(5, rating));
        var highlighted = !!layer._wcHighlight;
        var props = layer.featureProperties || {};
        var style = mapSafetyBandToStyle(band);
        var radius = spotRadius(highlighted);
        if (layer._wcHover) radius += 1; // Hover-Feedback (ersetzt CSS :hover scale)

        // Alles ab hier wird um den Ursprung gezeichnet, in Originalgroesse.
        // Die Zoom-Gegenskalierung passiert erst beim Stempeln (stampSpot) —
        // so bleiben die Original-Proportionen (Sektor r+1/r+9, Schatten 1.2px
        // versetzt, Strichbreiten) in jeder Zoomphase exakt erhalten.
        ctx.save();
        ctx.translate(x, y);

        // Display-Band Premium-Override: safe + rating=5 (xc_tag/Klassiker) →
        // Violet-400 (Palette v3.2 Royal Premium).
        if (band === 'green' && rating >= 5) {
            band = 'violet';
            style = { fill: '#a78bfa', stroke: '#6d28d9' };
        }

        // Wind direction sector (PGE: kann mehrere disjunkte Arcs liefern)
        if (props.windrichtung) {
            var arcs = getDirAngles(props.windrichtung);
            if (arcs && arcs.length) {
                var ri = radius + 1, ro = radius + 9;
                ctx.globalAlpha = 0.5;
                ctx.fillStyle = style.stroke;
                for (var ai = 0; ai < arcs.length; ai++) {
                    var a0 = (arcs[ai][0] - 90) * Math.PI / 180;
                    var a1 = (arcs[ai][1] - 90) * Math.PI / 180;
                    ctx.beginPath();
                    ctx.arc(0, 0, ro, a0, a1, false);
                    ctx.arc(0, 0, ri, a1, a0, true);
                    ctx.closePath();
                    ctx.fill();
                }
                ctx.globalAlpha = 1;
            }
        }

        // Highlight glow (selected spot)
        if (highlighted) {
            ctx.globalAlpha = 0.25;
            ctx.fillStyle = style.fill;
            ctx.beginPath();
            ctx.arc(0, 0, radius + 4, 0, Math.PI * 2);
            ctx.fill();
            ctx.globalAlpha = 1;
        }

        // Schatten (Nachbildung von drop-shadow(0 1px 3px …) ohne Blur)
        ctx.fillStyle = 'rgba(0,0,0,0.13)';
        ctx.beginPath();
        ctx.arc(0, 1.2, radius + 1, 0, Math.PI * 2);
        ctx.fill();

        // Weisser Hintergrund-Kreis, damit die Karte bei hellem Fill nicht durchscheint
        ctx.fillStyle = '#ffffff';
        ctx.beginPath();
        ctx.arc(0, 0, radius, 0, Math.PI * 2);
        ctx.fill();

        // Rating-Tint: Hue-Shift quer durch verwandte Farbtoene
        // (Source of Truth: docs/RATING_FARBKONZEPT.md)
        var markerFill = style.fill;
        var markerStroke = style.stroke;
        if (rating > 0 && (band === 'green' || band === 'amber')) {
            var tint = getRatingTint(band, rating);
            if (tint) { markerFill = tint.fill; markerStroke = tint.stroke; }
        }

        // Main circle (safety band color)
        ctx.beginPath();
        ctx.arc(0, 0, radius, 0, Math.PI * 2);
        ctx.fillStyle = markerFill;
        ctx.fill();
        ctx.lineWidth = highlighted ? 2 : 1.5;
        ctx.strokeStyle = markerStroke;
        ctx.stroke();

        // Inner glyph
        if (band === 'red') {
            // White X cross — Sperr-Glyphe
            var arm = radius * 0.55;
            ctx.strokeStyle = '#ffffff';
            ctx.lineWidth = Math.max(2, radius * 0.22);
            ctx.lineCap = 'round';
            ctx.beginPath();
            ctx.moveTo(-arm, -arm); ctx.lineTo(arm, arm);
            ctx.moveTo(arm, -arm); ctx.lineTo(-arm, arm);
            ctx.stroke();
            ctx.lineCap = 'butt';
        } else if (rating >= 1 && (band === 'green' || band === 'amber' || band === 'violet')) {
            // Ziffer 1-5 — dunkler Text auf hellen Fills, weiss auf saturierten
            var fontSize = Math.round(radius * 1.5);
            var darkBgHere = (band === 'violet')
                || (band === 'amber' && rating >= 3)
                || (band === 'green' && rating >= 4);
            ctx.fillStyle = darkBgHere ? '#ffffff' : markerStroke;
            ctx.font = '800 ' + fontSize + 'px Inter, sans-serif';
            ctx.textAlign = 'center';
            ctx.textBaseline = 'middle';
            ctx.fillText(String(rating), 0, 0.5);
        } else if (band === 'green' || band === 'amber' || band === 'violet') {
            // 0 rating: kleiner weisser Punkt (sicher aber Abgleiter)
            ctx.fillStyle = '#ffffff';
            ctx.beginPath();
            ctx.arc(0, 0, 1.8, 0, Math.PI * 2);
            ctx.fill();
        }
        ctx.restore();
    }

    // CircleMarker-Subklasse: Leaflet liefert Events/Tooltip/Popup,
    // gezeichnet wird via drawSpot auf dem gemeinsamen Canvas.
    // options.radius (= SPOT_DRAW_BOUNDS) bestimmt nur die Redraw-Region;
    // der Hit-Test ist zoomabhaengig und deutlich enger.
    var SpotMarker = L.CircleMarker.extend({
        // Position OHNE Leaflets Rundungen. Leaflets latLngToLayerPoint rundet
        // die Projektion auf ganze Pixel, und der Pixelursprung (_move →
        // _getNewPixelOrigin) wird ebenfalls gerundet. Bei stufenlosem Zoom
        // gleitet die Grundkarte deshalb weich, waehrend die Spots in
        // Ganzpixel-Stufen nachspringen — gemessen ein Versatz zur idealen
        // Position von +-0.84px, der zwischen zwei Bildern um bis zu 1.38px
        // umschlaegt (11 von 50 Bildern ueber 0.5px). Genau das sieht der
        // Nutzer als Zappeln, am staerksten kurz vor dem Einrasten, wo der
        // Zoom nur noch kriecht.
        // Der eigene Ursprung ist derselbe Ausdruck wie Leaflets, nur ohne das
        // abschliessende _round(). Die Abweichung zu Leaflets Layer-Koordinaten
        // bleibt damit unter einem Pixel — unkritisch fuer das Culling
        // (SPOT_DRAW_BOUNDS = 56 Reserve) und fuer den Hit-Test (Radius 10-22px).
        _project: function () {
            var m = this._map;
            if (!m) return;
            var z = m.getZoom();
            var ursprungExakt = m.project(m.getCenter(), z)
                .subtract(m.getSize().divideBy(2))
                .add(m._getMapPanePos());
            this._point = m.project(this._latlng, z).subtract(ursprungExakt);
            this._updateBounds();
        },
        _updatePath: function () {
            var r = this._renderer;
            if (!r || !r._ctx || !this._point) return;
            // Viewport-Culling: Leaflets Canvas._draw() prueft bei einem
            // VOLL-Redraw nicht gegen den sichtbaren Bereich und zeichnet auch
            // alle Spots ausserhalb. Waehrend der Zoom-Geste laeuft das pro
            // Frame ueber alle 494 Marker → das ist die teuerste Stelle.
            // _bounds und _point liegen beide in Layer-Koordinaten.
            var b = r._bounds, p = this._point;
            if (b && (p.x < b.min.x - SPOT_DRAW_BOUNDS || p.x > b.max.x + SPOT_DRAW_BOUNDS ||
                      p.y < b.min.y - SPOT_DRAW_BOUNDS || p.y > b.max.y + SPOT_DRAW_BOUNDS)) return;
            stampSpot(r._ctx, p.x, p.y, this);
        },
        _containsPoint: function (p) {
            // Grosszuegiges Tap-Ziel auf Touch (WCAG ~44px Durchmesser), enger
            // mit der Maus. Nicht groesser, sonst ueberlappen sich die
            // Trefferflaechen dicht stehender Spots.
            var isTouch = ('ontouchstart' in window) || (navigator.maxTouchPoints > 0);
            var hitR = isTouch ? 22 : Math.max(10, spotRadius(false) * 1.4);
            return p.distanceTo(this._point) <= hitR + this._clickTolerance();
        }
    });

    // Visuellen Zustand eines Markers setzen. Signatur-Guard: unveraendert →
    // gar nichts tun (haeufigster Fall beim Tab-Fokus-Refetch). Sonst genuegt
    // redraw() — der Canvas-Renderer sammelt alle Aenderungen in EINEM
    // Frame-Repaint statt 494 einzelner DOM-Operationen.
    function applySpotVisual(marker, band, rating, highlighted) {
        var sig = band + '|' + rating + '|' + (highlighted ? 1 : 0);
        if (marker._wcSig === sig) return false;
        marker._wcSig = sig;
        marker._wcHighlight = !!highlighted;
        if (marker._map) marker.redraw();
        return true;
    }

    // ===== TOOLTIP BUILDER (RATING_CONCEPT v1.4 §8.2) =====
    // Signature: buildTooltipHtml(p, _legacyStyle, safetyBand, experienceRating, dayData)
    // experienceRating ist 0-10 (0 = kein Flug). _legacyStyle bleibt fuer alte
    // Aufrufer, wird ignoriert wenn safetyBand uebergeben wird.
    function buildTooltipHtml(p, _legacyStyle, safetyBand, experienceRating, dayData) {
        var html = '<b>' + p.name + '</b><br>' +
            p.fluggebiet + ' (' + p.region + ')<br>' +
            p.elevation_m + 'm MSL | Wind: ' + p.windrichtung;
        if (!p.has_weather) {
            html += '<br><span style="color:#F59E0B;">' + wcT('js.map.no_weather_loaded') + '</span>';
        }
        if (safetyBand && safetyBand !== 'default') {
            var s = mapSafetyBandToStyle(safetyBand);
            html += '<br><span style="display:inline-block;width:8px;height:8px;border-radius:50%;background:'
                  + s.fill + ';margin-right:4px;vertical-align:middle;"></span>';
            html += '<span style="color:' + s.stroke + ';">' + s.label + '</span>';
            if (safetyBand !== 'red' && typeof experienceRating === 'number' && experienceRating >= 1) {
                html += ' &middot; Rating ' + experienceRating;
            }
        }
        return html;
    }

    // ===== LOAD SPOTS =====
    function loadSpots() {
        // via data-store: dedupliziert mit region-map.js (ein Download)
        window.wingcastData.getSpots()
            .then(function (geojson) {
                var geoJsonLayer = L.geoJSON(geojson, {
                    pointToLayer: function (feature, latlng) {
                        // Canvas-Marker: Optik kommt komplett aus drawSpot,
                        // radius dient nur Hit-Test + Redraw-Region.
                        return new SpotMarker(latlng, {
                            renderer: spotRenderer,
                            pane: 'spotPane',
                            radius: SPOT_DRAW_BOUNDS,
                            stroke: false,
                            fill: false,
                            bubblingMouseEvents: false,
                        });
                    },
                    onEachFeature: function (feature, layer) {
                        var p = feature.properties;
                        layer.featureProperties = p;
                        layer.currentSafetyBand = p.has_weather ? 'default' : 'no_data';
                        layer.currentRating = 0;
                        layer.currentStars = 0;
                        // Signatur des initial gesetzten Icons (siehe applySpotVisual)
                        layer._wcSig = layer.currentSafetyBand + '|0|0';
                        // Legacy compat-Felder (fuer Highlight/Tooltip-Pfade die noch davon lesen)
                        layer.currentSafety = p.has_weather ? 'default' : 'no_data';
                        layer.currentQuality = 'green';

                        markersByName[p.name] = layer;
                        // On mobile: use popup (tap-friendly); on desktop: tooltip (hover)
                        var isMobile = window.innerWidth <= 600;
                        if (isMobile) {
                            layer.bindPopup(buildTooltipHtml(p, null), {
                                className: 'map-tooltip',
                                offset: [0, -10],
                                closeButton: false,
                                maxWidth: 260,
                            });
                        } else {
                            layer.bindTooltip(buildTooltipHtml(p, null), {
                                className: 'map-tooltip',
                                direction: 'top',
                                offset: [0, -10],
                            });
                        }
                        layer.on('click', function () {
                            openMeteogram(p.name, p);
                        });
                        
                        // Hover Effect for Reference Points
                        layer.on('mouseover', function () {
                            // Hover-Grow (ersetzt frueheres CSS :hover scale auf dem SVG)
                            layer._wcHover = true;
                            layer.redraw();
                            if (SHOW_REFERENCE_POINTS && p.reference_points && p.reference_points.length > 1) {
                                var refGroup = L.layerGroup();
                                var spotPt = p.reference_points[0]; // Point 0 is the spot itself

                                // Farbe nach aktuellem Surface-Modell fuer Tag 1
                                // (subtil — siehe docs/WETTERMODELLE.md Tier-Voting).
                                // Fallback auf Slate wenn data_sources noch nicht geladen.
                                var srcCode = null;
                                if (p.data_sources && typeof p.data_sources === 'object') {
                                    var dsKeys = Object.keys(p.data_sources).sort();
                                    if (dsKeys.length) srcCode = p.data_sources[dsKeys[0]];
                                }
                                var refInfo = (window.modelInfoFor ? window.modelInfoFor(srcCode)
                                    : { color: '#0369a1' });

                                // Draw lines from spot to each reference point
                                p.reference_points.slice(1).forEach(function(pt) {
                                    // 1. Connection Line
                                    var line = L.polyline([spotPt, pt], {
                                        color: refInfo.color,
                                        weight: 1.5,
                                        dashArray: '5, 5',
                                        opacity: 0.5
                                    });
                                    refGroup.addLayer(line);

                                    // 2. Small markers for the grid points
                                    var circle = L.circleMarker(pt, {
                                        radius: 4,
                                        color: refInfo.color,
                                        fillColor: '#fff',
                                        fillOpacity: 1,
                                        weight: 2
                                    });
                                    refGroup.addLayer(circle);
                                });
                                currentRefLayer = refGroup;
                                map.addLayer(currentRefLayer);
                            }
                        });
                        
                        layer.on('mouseout', function () {
                            layer._wcHover = false;
                            layer.redraw();
                            if (currentRefLayer) {
                                map.removeLayer(currentRefLayer);
                                currentRefLayer = null;
                            }
                        });
                    },
                }).addTo(map);

                // Nach dem Laden an alle Spots anpassen (Gesamtansicht Schweiz)
                try {
                    var bounds = geoJsonLayer.getBounds();
                    if (bounds && bounds.isValid()) {
                        window.wingcastSpotsBounds = bounds;
                        map.fitBounds(bounds, { padding: [20, 20] });
                        // Dieser erste Fit rechnet oft noch mit der falschen
                        // Containergroesse (Sidebar klappt auf, Schriften laden).
                        // Frueher fiel das nicht auf, weil der Zoom auf feine
                        // Zwischenstufen rasten durfte; seit der Ruhepunkt eine
                        // GANZE Stufe ist, wird daraus schnell eine Stufe zu nah
                        // — gemessen fehlten dann 148 der 494 Spots im Bild.
                        // Deshalb einmal nachfitten, sobald das Layout steht —
                        // aber nur, solange der Nutzer die Karte nicht selbst
                        // angefasst hat.
                        var userTouched = false;
                        ['wheel', 'mousedown', 'touchstart', 'keydown'].forEach(function (ev) {
                            map.getContainer().addEventListener(ev, function () { userTouched = true; },
                                { once: true, passive: true });
                        });
                        var refit = function () {
                            if (userTouched || !window.wingcastSpotsBounds) return;
                            map.invalidateSize({ animate: false });
                            map.fitBounds(window.wingcastSpotsBounds, { padding: [20, 20], animate: false });
                        };
                        requestAnimationFrame(refit);
                        setTimeout(refit, 400);
                    }
                } catch (e) {
                    console.warn('fitBounds fehlgeschlagen:', e);
                }

                // (Frueheres Viewport-Culling entfernt: der Canvas-Renderer
                // zeichnet von sich aus nur Marker im Sichtbereich, und fuer den
                // Hit-Test muessen alle Marker angehaengt bleiben.)
            })
            .then(function () {
                // Race-Fix: falls /api/analyses VOR /api/spots zurueckkam,
                // lief updateSpotColors ueber ein leeres markersByName (no-op).
                // Marker bleiben dann grau (default/no_data) bis User Day-Tab wechselt.
                // Jetzt sind Marker da → einmal nach-coloren wenn Analyse vorhanden.
                if (window.analysisData && window.updateSpotColors) {
                    window.updateSpotColors(window.analysisData, window.currentDate);
                }
            })
            .then(openSpotFromUrl)
            .catch(function (err) {
                console.error('Spots laden fehlgeschlagen:', err);
            });
    }

    // Deep-Link: wenn /?spot=<Name> in der URL steht, Spot zentrieren + Meteogramm öffnen
    function openSpotFromUrl() {
        try {
            var params = new URLSearchParams(window.location.search);
            var spotName = params.get('spot');
            if (!spotName) return;
            var dateParam = params.get('date');
            if (dateParam) window.currentDate = dateParam;
            var marker = markersByName[spotName];
            if (!marker) return;
            if (marker.getLatLng) {
                map.setView(marker.getLatLng(), Math.max(map.getZoom(), 12));
            }
            var props = marker.featureProperties || (marker.feature && marker.feature.properties) || null;
            openMeteogram(spotName, props);
        } catch (e) {
            console.warn('[map] Spot aus URL konnte nicht geöffnet werden:', e);
        }
    }


    // ===== ANALYSE ASIDE TOGGLE (mobile collapsible) =====
    // Toggle wird durch Button ODER Header-Tap ausgelöst (grössere Tap-Target).
    if (asideEl) {
        var asideHeader = asideEl.querySelector('.meteogram-aside-header');
        var toggleAside = function (ev) {
            // Verhindern, dass interaktive Inhalte im Body den Toggle triggern
            if (ev && ev.target && ev.target.closest && ev.target.closest('.meteogram-aside-body')) return;
            var collapsed = asideEl.classList.toggle('collapsed');
            if (asideToggleBtn) {
                asideToggleBtn.setAttribute('aria-expanded', collapsed ? 'false' : 'true');
            }
        };
        // Header bekommt den Handler (Button bubbled hinauf — kein Doppel-Toggle).
        if (asideHeader) asideHeader.addEventListener('click', toggleAside);
        else if (asideToggleBtn) asideToggleBtn.addEventListener('click', toggleAside);
    }

    // ===== JSON DEBUG (Testmodus) =====
    function renderJsonDebug() {
        if (!chartContainer || !currentSpotName || !currentDates.length) return;
        var dateStr = currentDates[currentDateIdx];
        var analysis = (window.analysisData && window.analysisData[currentSpotName] && window.analysisData[currentSpotName][dateStr])
            ? window.analysisData[currentSpotName][dateStr]
            : null;
        chartContainer.innerHTML = '<pre id="jsonDebugPre" style="margin:0;padding:12px;font-size:11px;line-height:1.5;overflow:auto;height:100%;box-sizing:border-box;white-space:pre-wrap;word-break:break-all;color:#e2e8f0;background:#0f172a;border-radius:6px;">'
            + (analysis ? JSON.stringify(analysis, null, 2).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;') : '(keine Analyse für ' + currentSpotName + ' / ' + dateStr + ')')
            + '</pre>';
    }

    if (jsonDebugBtn) {
        jsonDebugBtn.addEventListener('click', function () {
            jsonDebugActive = !jsonDebugActive;
            jsonDebugBtn.classList.toggle('active', jsonDebugActive);
            if (hazardDebugActive) { hazardDebugActive = false; if (hazardDebugBtn) hazardDebugBtn.classList.remove('active'); }
            if (jsonDebugActive) {
                renderJsonDebug();
            } else {
                renderCurrentDay();
            }
        });
    }

    // ===== DATAVIEW (Meteogramm ⇄ Daten) — fuer alle Flieger =====
    function renderDataView() {
        if (!chartContainer || !currentSpotName || !currentDates.length) return;
        WxDataView.render(chartContainer, 'spot', currentSpotName, currentDates[currentDateIdx]);
    }

    function setDataView(active, skipRender) {
        dataViewActive = active;
        if (active) {
            // Andere (Test-)Debug-Ansichten deaktivieren.
            if (jsonDebugActive) { jsonDebugActive = false; if (jsonDebugBtn) jsonDebugBtn.classList.remove('active'); }
            if (hazardDebugActive) { hazardDebugActive = false; if (hazardDebugBtn) hazardDebugBtn.classList.remove('active'); }
        }
        if (viewToggleEl) {
            viewToggleEl.querySelectorAll('.dv-toggle-btn').forEach(function (b) {
                var on = (b.dataset.view === 'daten') === active;
                b.classList.toggle('active', on);
                b.setAttribute('aria-selected', on ? 'true' : 'false');
            });
        }
        if (!skipRender) renderCurrentDay();
    }

    if (viewToggleEl) {
        viewToggleEl.querySelectorAll('.dv-toggle-btn').forEach(function (b) {
            b.addEventListener('click', function () { setDataView(b.dataset.view === 'daten'); });
        });
    }

    function _escHtml(s) { return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }

    function renderHazardDebug() {
        if (!chartContainer || !currentSpotName || !currentDates.length) return;
        var dateStr = currentDates[currentDateIdx];
        chartContainer.innerHTML = '<div id="hazardDebugLoading" style="padding:12px;color:#94a3b8;font-size:12px;">Lade Debug-Daten…</div>';
        var url = '/api/spot-debug/' + encodeURIComponent(currentSpotName) + '/' + encodeURIComponent(dateStr);
        fetch(url).then(function(r){ return r.json(); }).then(function(d) {
            if (d.error) { chartContainer.innerHTML = '<div style="padding:12px;color:#f87171;">'+_escHtml(d.error)+'</div>'; return; }
            var lines = [];
            lines.push('=== SAFETY ===');
            lines.push('Status: ' + (d.safety_status||'?') + '  |  Band: ' + (d.safety_band||'?') + '  |  Score: ' + (d.safety_score!=null?d.safety_score:'?') + '  |  Foehn: ' + (d.foehn_risk||'?'));
            lines.push('');
            lines.push('--- Sub-Ratings (1-10) ---');
            if (d.sub_ratings) Object.keys(d.sub_ratings).forEach(function(k){ lines.push('  ' + k.replace('_safety_rating','').padEnd(15) + ': ' + (d.sub_ratings[k]!=null?d.sub_ratings[k]:'–')); });
            lines.push('');
            lines.push('--- Hazard Notes ---');
            if (d.hazard_notes) Object.keys(d.hazard_notes).forEach(function(k){ lines.push('  [' + k + '] ' + _escHtml(d.hazard_notes[k]||'')); });
            lines.push('');
            if (d.wind_summary) { lines.push('--- Wind Summary ---'); lines.push(_escHtml(d.wind_summary)); lines.push(''); }
            if (d.wind_shear) { lines.push('--- Wind Shear ---'); lines.push(_escHtml(d.wind_shear)); lines.push(''); }
            lines.push('=== FLYABILITY ===');
            lines.push('Experience-Rating: ' + (d.experience_rating!=null?d.experience_rating:'?'));
            lines.push('');
            lines.push('--- Flyability Notes ---');
            if (d.flyability_notes) Object.keys(d.flyability_notes).forEach(function(k){ lines.push('  [' + k + '] ' + _escHtml(d.flyability_notes[k]||'')); });
            lines.push('');
            lines.push('=== DECISIONS APPLIED ===');
            lines.push((d._decisions_applied && d._decisions_applied.length) ? d._decisions_applied.join(', ') : '(keine)');
            chartContainer.innerHTML = '<pre style="margin:0;padding:12px;font-size:11px;line-height:1.6;overflow:auto;height:100%;box-sizing:border-box;white-space:pre-wrap;word-break:break-all;color:#e2e8f0;background:#0f172a;border-radius:6px;">'
                + lines.join('\n') + '</pre>';
        }).catch(function(err){
            chartContainer.innerHTML = '<div style="padding:12px;color:#f87171;">Fehler: '+_escHtml(err)+'</div>';
        });
    }

    if (hazardDebugBtn) {
        hazardDebugBtn.addEventListener('click', function () {
            hazardDebugActive = !hazardDebugActive;
            hazardDebugBtn.classList.toggle('active', hazardDebugActive);
            if (jsonDebugActive) { jsonDebugActive = false; if (jsonDebugBtn) jsonDebugBtn.classList.remove('active'); }
            if (hazardDebugActive) {
                renderHazardDebug();
            } else {
                renderCurrentDay();
            }
        });
    }

    function renderAnalyseView() {
        if (!analyseViewContainer || !currentDates.length) return;
        var dateStr = currentDates[currentDateIdx];
        // Look up analysis data set globally by index.html
        var analysis = null;
        if (window.analysisData
            && window.analysisData[currentSpotName]
            && window.analysisData[currentSpotName][dateStr]) {
            analysis = window.analysisData[currentSpotName][dateStr];
        }
        if (!Meteogram.renderAnalysisView) {
            analyseViewContainer.innerHTML = '<div class="error-state">' + wcT('js.map.analysis_unavailable') + '</div>';
            return;
        }
        Meteogram.renderAnalysisView(analyseViewContainer, analysis, {
            spotName: currentSpotName,
            dateStr: dateStr,
        });
        // Capture experience-score + stars fuer Share-Text (Hero-Block zeigt
        // Rating selbst — kein separates Badge mehr).
        // experience_score / experience_stars in v2.0 entfernt
        currentSpotExperienceRating = (analysis && typeof analysis.experience_rating === 'number') ? analysis.experience_rating : null;
        renderFeedbackBar(currentSpotName, dateStr, analysis);
    }

    function renderFeedbackBar(spotName, dateStr, analysis) {
        if (!feedbackBar || !spotName) return;
        // Widget wird angezeigt sobald ein Spot offen ist — analysis kann
        // beim Open noch fehlen (race mit /api/spot_analyses), oder
        // safety_status kann 'no_data' sein. Pilot soll trotzdem Feedback
        // geben können. Nur bei echtem Backend-Error ('error') macht es
        // keinen Sinn → Widget hidden.
        var status = analysis && analysis.safety_status;
        if (status === 'error') {
            feedbackBar.innerHTML = '';
            feedbackBar.style.display = 'none';
            return;
        }
        // Re-mount nicht jedesmal — wenn das Widget schon für diesen
        // Spot+Date gemountet ist, nichts tun (vermeidet __fbBound-Reset).
        var existing = feedbackBar.querySelector('[data-fb-mount]');
        if (existing
            && existing.getAttribute('data-fb-target') === spotName
            && existing.getAttribute('data-fb-date') === (dateStr || '')) {
            feedbackBar.style.display = 'flex';
            return;
        }
        feedbackBar.innerHTML = '';
        var mount = document.createElement('div');
        mount.setAttribute('data-fb-mount', '');
        mount.setAttribute('data-fb-type', 'spot');
        mount.setAttribute('data-fb-target', spotName);
        if (dateStr) mount.setAttribute('data-fb-date', dateStr);
        feedbackBar.appendChild(mount);
        feedbackBar.style.display = 'flex';
        if (window.Feedback && window.Feedback.scan) window.Feedback.scan(feedbackBar);
    }

    // ===== METEOGRAM OVERLAY =====
    function openMeteogram(spotName, props) {
        currentSpotName = spotName;
        currentSpotProps = props || null;
        setDataView(false, true);  // neuer Spot startet im Meteogramm
        currentSpotExperienceScore = null;
        currentSpotExperienceStars = null;
        currentSpotExperienceRating = null;
        titleEl.textContent = spotName;
        infoEl.textContent = props
            ? props.fluggebiet + ' | ' + props.elevation_m + 'm MSL | ' + props.windrichtung
            : '';

        // Modell-Badge neben spot-info — wird in renderCurrentDay pro Tag
        // befuellt (Surface-Tier-Voting CH1 → CH2 → D2 → EU).
        var modelBadge = document.getElementById('meteogramModelBadge');
        if (!modelBadge && infoEl && infoEl.parentNode) {
            modelBadge = document.createElement('span');
            modelBadge.id = 'meteogramModelBadge';
            modelBadge.className = 'meteogram-model-badge';
            infoEl.parentNode.appendChild(modelBadge);
        }
        if (modelBadge) modelBadge.textContent = '';
        chartContainer.innerHTML = '<div class="error-state">' + wcT('js.map.loading_data') + '</div>';
        if (analyseViewContainer) analyseViewContainer.innerHTML = '<div class="mg-analysis-empty">' + wcT('js.map.loading_analysis') + '</div>';
        tabsContainer.innerHTML = '';
        if (tabRow) tabRow.style.display = 'none';
        // feedbackBar: nur leeren, Display via CSS (:empty hidden, :not(:empty) shown).
        // Inline style.display würde sonst das CSS überschreiben und das Widget
        // unsichtbar lassen, auch wenn renderFeedbackBar später mountet.
        if (feedbackBar) feedbackBar.innerHTML = '';
        overlay.style.display = 'flex';
        overlay.classList.add('visible');
        if (window._overlayScrollLock) window._overlayScrollLock();
        closeBtn.focus();

        chartContainer.style.display = '';
        // Aside startet expanded auf Desktop, collapsed auf Mobile (Sheet-Pattern):
        // Auf Mobile sieht der User zuerst das Meteogramm in voller Höhe, kann
        // die Analyse via Toggle-Button ausklappen.
        if (asideEl) {
            var isMobile = window.innerWidth <= 640;
            asideEl.classList.toggle('collapsed', isMobile);
            if (asideToggleBtn) {
                asideToggleBtn.setAttribute('aria-expanded', isMobile ? 'false' : 'true');
            }
        }

        Promise.all([
            fetchJson('/api/weather/' + encodeURIComponent(spotName)),
            fetchJson('/api/altitude-wind/' + encodeURIComponent(spotName)),
        ])
            .then(function (results) {
                currentWeather = results[0];
                currentAltWind = results[1];

                if (currentWeather.error) {
                    chartContainer.innerHTML = '<div class="error-state">' + currentWeather.error + '</div>';
                    return;
                }
                if (currentAltWind.error) {
                    chartContainer.innerHTML = '<div class="error-state">' + currentAltWind.error + '</div>';
                    return;
                }

                // Always render `expected_days` tabs (default 5). Days without
                // data fall through to the existing "Keine Daten" / "Keine
                // Analyse" empty states — that way it's always clear WHY a
                // day is empty (cache stale, analysis missing) instead of
                // silently dropping the tab.
                var expected = parseInt(currentWeather.expected_days, 10);
                if (!isFinite(expected) || expected < 1) {
                    expected = (currentWeather.dates || []).length || 1;
                }
                var _today = new Date();
                _today.setHours(0, 0, 0, 0);
                currentDates = [];
                for (var _i = 0; _i < expected; _i++) {
                    var _d = new Date(_today);
                    _d.setDate(_today.getDate() + _i);
                    currentDates.push(
                        _d.getFullYear() + '-'
                        + String(_d.getMonth() + 1).padStart(2, '0') + '-'
                        + String(_d.getDate()).padStart(2, '0')
                    );
                }

                // Build day tabs inside the overlay
                var selectedDate = window.currentDate || currentDates[0];
                currentDateIdx = currentDates.indexOf(selectedDate);
                if (currentDateIdx < 0) currentDateIdx = 0;

                if (currentDates.length > 1) {
                    Meteogram.buildTabs(tabsContainer, currentDates, function (dateStr) {
                        var idx = currentDates.indexOf(dateStr);
                        if (idx >= 0 && idx !== currentDateIdx) {
                            currentDateIdx = idx;
                            window.currentDate = dateStr;
                            renderCurrentDay();
                            // Sync floating map day tabs + marker colours
                            syncFloatingDayTabs(dateStr);
                        }
                    });
                    tabsContainer.style.display = '';
                    // buildTabs marks idx 0 active – correct to selected day
                    var allTabs = tabsContainer.querySelectorAll('.tab-btn');
                    allTabs.forEach(function (b, i) { b.classList.toggle('active', i === currentDateIdx); });
                } else {
                    tabsContainer.style.display = 'none';
                }
                // Tab-Row IMMER sichtbar wenn Daten geladen — auch bei nur 1 Tag,
                // damit das Feedback-Widget rechts in der Zeile sichtbar bleibt.
                // Tabs selbst werden separat hidden wenn nur 1 Tag.
                if (tabRow) tabRow.style.display = '';

                renderCurrentDay();
            })
            .catch(function (err) {
                chartContainer.textContent = '';
                var errBox = document.createElement('div');
                errBox.className = 'error-state';
                errBox.appendChild(document.createTextNode(
                    'Fehler: ' + (err && err.message ? err.message : 'Unbekannt')
                ));
                errBox.appendChild(document.createElement('br'));
                var retryBtn = document.createElement('button');
                retryBtn.className = 'btn btn-secondary btn-sm';
                retryBtn.style.marginTop = '12px';
                retryBtn.textContent = 'Erneut versuchen';
                retryBtn.addEventListener('click', function () {
                    errBox.textContent = 'Lade...';
                    openMeteogram(currentSpotName, null);
                });
                errBox.appendChild(retryBtn);
                chartContainer.appendChild(errBox);
            });
    }

    function renderCurrentDay() {
        if (hazardDebugActive) { renderHazardDebug(); renderAnalyseView(); return; }
        if (jsonDebugActive) { renderJsonDebug(); renderAnalyseView(); return; }
        if (dataViewActive) { renderDataView(); renderAnalyseView(); return; }
        var dateStr = currentDates[currentDateIdx];
        if (!dateStr) return;

        var wxDay = currentWeather.data[dateStr] || {};
        var altProfiles = (currentAltWind.data && currentAltWind.data[dateStr]) || [];

        // renderChart expects altDay = {profiles: [{time, levels: [...]}]}
        var altDay = { profiles: [] };
        altProfiles.forEach(function (p) {
            altDay.profiles.push({
                time: dateStr + 'T' + (p.hour < 10 ? '0' : '') + p.hour + ':00:00',
                levels: p.profiles || [],
            });
        });

        // Bodenwind (10m, terrain-korrigiert) pro Stunde -> Lookup {time: data}
        // Safety-relevanter Startwind, getrennt vom freien Höhenwind.
        var groundWindByTime = {};
        var gwList = (currentAltWind.ground_wind && currentAltWind.ground_wind[dateStr]) || [];
        gwList.forEach(function (g) {
            var t = dateStr + 'T' + (g.hour < 10 ? '0' : '') + g.hour + ':00:00';
            groundWindByTime[t] = g;
        });

        Meteogram.renderChart(chartContainer, tooltipEl, wxDay, altDay, {
            elevation: currentWeather.elevation_m,
            windrichtung: currentWeather.windrichtung,
            idealWindMax: currentWeather.ideal_wind_max,
            groundWindByTime: groundWindByTime,
            thresholds: currentWeather.thresholds,
            fitToContainer: true,
        });

        // Modell-Badge im Header neben Spot-Info aktualisieren (Surface-Tier-
        // Voting CH1/CH2/D2/EU pro Tag, siehe docs/WETTERMODELLE.md).
        var modelBadgeEl = document.getElementById('meteogramModelBadge');
        if (modelBadgeEl) {
            var srcCode = (currentWeather.data_sources && currentWeather.data_sources[dateStr]) || null;
            var info = modelInfoFor(srcCode);
            modelBadgeEl.innerHTML = '';
            modelBadgeEl.title = 'Datenquelle Surface fuer diesen Tag. Tier-Voting CH1 → CH2 → D2 → EU.';
            var dot = document.createElement('span');
            dot.style.cssText = 'display:inline-block;width:7px;height:7px;border-radius:50%;background:'
                + info.color + ';margin-right:4px;vertical-align:middle;';
            modelBadgeEl.appendChild(dot);
            modelBadgeEl.appendChild(document.createTextNode(
                info.label + (info.resolution ? ' · ' + info.resolution : '')
            ));
        }

        // Footer: nur Wetter-Stand (Modell-Info ist jetzt im Header).
        var existingTs = chartContainer.querySelector('.meteogram-weather-ts');
        if (existingTs) existingTs.remove();
        if (currentWeather.last_updated) {
            var tsDiv = document.createElement('div');
            tsDiv.className = 'meteogram-weather-ts';
            tsDiv.style.cssText = 'font-size:10px;color:#94a3b8;text-align:right;padding:2px 8px 0;';
            tsDiv.textContent = wcT('js.map.weather_as_of') + currentWeather.last_updated.replace('T', ' ').slice(0, 16);
            chartContainer.appendChild(tsDiv);
        }

        // Analyse panel is always visible in the aside – refresh on every day change.
        renderAnalyseView();
    }

    function closeMeteogram() {
        overlay.style.display = 'none';
        overlay.classList.remove('visible');
        tooltipEl.classList.remove('visible');
        currentWeather = null;
        currentAltWind = null;
        if (window._overlayScrollUnlock) window._overlayScrollUnlock();
        // Debug-Buttons zurücksetzen
        if (jsonDebugActive) {
            jsonDebugActive = false;
            if (jsonDebugBtn) jsonDebugBtn.classList.remove('active');
        }
        if (hazardDebugActive) {
            hazardDebugActive = false;
            if (hazardDebugBtn) hazardDebugBtn.classList.remove('active');
        }
    }

    /** Sync the navbar day tabs + marker colours after an
     *  overlay-internal day switch. */
    function syncFloatingDayTabs(dateStr) {
        var navDayTabs = document.getElementById('navDayTabs');
        if (navDayTabs) {
            navDayTabs.querySelectorAll('.navbar-day-btn').forEach(function (b) {
                b.classList.toggle('active', b.dataset.date === dateStr);
            });
        }
        window.currentDate = dateStr;
        if (window.updateSpotColors && window.analysisData) {
            window.updateSpotColors(window.analysisData, dateStr);
        }
    }

    // Re-render analysis view when analyses are loaded (API fetch after page load)
    window.addEventListener('wingcast-analyses-loaded', function () {
        renderAnalyseView();
    });

    // Listen for day changes from the floating map tabs
    window.addEventListener('wingcast-day-change', function (e) {
        if (!currentWeather || !currentDates.length) return;
        var newDate = e.detail && e.detail.date;
        if (!newDate) return;
        var idx = currentDates.indexOf(newDate);
        if (idx >= 0 && idx !== currentDateIdx) {
            currentDateIdx = idx;
            renderCurrentDay();
            // Keep overlay day tabs in sync
            tabsContainer.querySelectorAll('.tab-btn').forEach(function (b, i) {
                b.classList.toggle('active', i === idx);
            });
        }
    });

    // ===== EVENT LISTENERS =====
    closeBtn.addEventListener('click', closeMeteogram);

    if (shareBtn) {
        shareBtn.addEventListener('click', function () {
            if (!currentSpotName || typeof window.wingcastShare !== 'function') return;
            var regionId = (currentSpotProps && currentSpotProps.region_id) || '';
            var regionName = (currentSpotProps && currentSpotProps.region) || '';
            var rText = '';
            if (currentSpotExperienceRating != null && currentSpotExperienceRating >= 1) {
                rText = ' — Rating ' + currentSpotExperienceRating;
            }
            var dayIdx = 0;
            if (window.currentDate && currentDates && currentDates.length) {
                var idx = currentDates.indexOf(window.currentDate);
                if (idx >= 0) dayIdx = idx;
            }
            window.wingcastShare({
                region_id: regionId,
                day_idx: dayIdx,
                spot: currentSpotName,
                title: currentSpotName + rText,
                text: currentSpotName + (regionName ? ' (' + regionName + ')' : '') + rText + ' · Wingcast Flugwetter',
            });
        });
    }

    overlay.addEventListener('click', function (e) {
        if (e.target === overlay) closeMeteogram();
    });

    document.addEventListener('keydown', function (e) {
        if (e.key === 'Escape' && overlay.classList.contains('visible')) {
            closeMeteogram();
        }
    });

    // ===== HIGHLIGHTING =====
    window.highlightSpots = function (items) {
        // Ein Durchlauf statt Reset-aller + Neu-Setzen: nur Marker, deren
        // Highlight-Zustand sich tatsaechlich aendert, werden angefasst.
        var wanted = {};
        if (items && Array.isArray(items)) {
            items.forEach(function (item) {
                wanted[typeof item === 'string' ? item : item.name] = true;
            });
        }
        Object.keys(markersByName).forEach(function (name) {
            var marker = markersByName[name];
            var band = marker.currentSafetyBand || 'default';
            var rating = (typeof marker.currentRating === 'number') ? marker.currentRating : 0;
            var hl = !!wanted[name];
            var changed = applySpotVisual(marker, band, rating, hl);
            // Hervorgehobene zuletzt zeichnen (Canvas-Aequivalent von zIndex)
            if (changed && hl && marker._map) marker.bringToFront();
        });
    };

    // ===== SPOT COLORING (from LLM analyses, RATING_CONCEPT v1.4) =====
    // Reads safety_status + experience_rating (1-6, RATING_ARCHITECTURE v2.0).
    window.updateSpotColors = function (analysisData, dateStr) {
        // analysisData: {spot_name: {date_str: {safety_band, experience_rating, ...}}}
        if (!analysisData || !dateStr) return;

        Object.keys(markersByName).forEach(function (name) {
            var marker = markersByName[name];
            var spotAnalysis = analysisData[name];
            var dayData = spotAnalysis && spotAnalysis[dateStr];

            if (!dayData) {
                // No analysis for this date → reset to no_data
                marker.currentSafetyBand = 'no_data';
                marker.currentRating = 0;
                marker.currentStars = 0;
                marker.currentSafety = 'no_data';
                marker.currentQuality = 'green';
                applySpotVisual(marker, 'no_data', 0, false);
                marker.setTooltipContent(buildTooltipHtml(marker.featureProperties, null, 'no_data', 0, dayData));
                return;
            }

            // RATING_ARCHITECTURE v2.1: safety_status → band (FE-Mapping).
            var band = legacySafetyBand(dayData.safety_status);
            var rating = parseInt(dayData.experience_rating, 10);
            if (!isFinite(rating) || rating < 0) rating = 0;
            // Migration-Tolerance: 6 → 5
            if (rating === 6) rating = 5;
            rating = Math.min(5, rating);

            marker.currentSafetyBand = band;
            marker.currentRating = rating;
            marker.currentSafety = dayData.safety_status || 'safe';

            applySpotVisual(marker, band, rating, false);
            marker.setTooltipContent(buildTooltipHtml(marker.featureProperties, null, band, rating, dayData));
        });
    };

    // ===== REFRESH SPOT MARKERS =====
    window.refreshSpotMarkers = function () {
        // force=true: expliziter Refresh soll wirklich neu laden (ETag macht es billig)
        window.wingcastData.getSpots(true)
            .then(function (geojson) {
                geojson.features.forEach(function (feature) {
                    var p = feature.properties;
                    var marker = markersByName[p.name];
                    if (marker) {
                        marker.featureProperties = p;
                        // Don't override analysis data if it exists
                        var hasAnalysis = marker.currentSafetyBand
                            && marker.currentSafetyBand !== 'default'
                            && marker.currentSafetyBand !== 'no_data';
                        if (!hasAnalysis) {
                            var band = p.has_weather ? 'default' : 'no_data';
                            marker.currentSafetyBand = band;
                            marker.currentRating = 0;
                            marker.currentStars = 0;
                            marker.currentSafety = band;
                            marker.currentQuality = 'green';
                            applySpotVisual(marker, band, 0, false);
                        }
                        var ratingTip = (typeof marker.currentRating === 'number') ? marker.currentRating : 0;
                        marker.setTooltipContent(buildTooltipHtml(
                            p, null, marker.currentSafetyBand, ratingTip, null
                        ));
                    }
                });
            })
            .catch(function (err) {
                console.error('Spot-Status Update fehlgeschlagen:', err);
            });
    };

    // ===== PHASE 1: ISOCHRONE + USER LOCATION OVERLAYS =====
    function drawIsochrone(geojson, label) {
        if (!geojson) return;
        // Vorherige Isochrone entfernen
        clearIsochrone();
        try {
            isochroneLayer = L.geoJSON(geojson, {
                style: function () {
                    return {
                        color: '#0369a1',
                        weight: 2,
                        opacity: 0.85,
                        fillColor: '#0ea5e9',
                        fillOpacity: 0.18,
                        dashArray: '4 4'
                    };
                }
            });
            if (label) {
                isochroneLayer.bindTooltip('Erreichbar in ' + label, {
                    sticky: true,
                    className: 'map-tooltip'
                });
            }
            isochroneLayer.addTo(map);

            // Karte auf Isochrone fitten — falls Layer Bounds liefert
            try {
                var bounds = isochroneLayer.getBounds();
                if (bounds && bounds.isValid()) {
                    map.fitBounds(bounds, { padding: [40, 40], maxZoom: 11 });
                }
            } catch (e) { /* fitBounds optional */ }
        } catch (e) {
            console.error('drawIsochrone fehlgeschlagen:', e);
        }
    }

    function clearIsochrone() {
        if (isochroneLayer) {
            try { map.removeLayer(isochroneLayer); } catch (e) { /* ignore */ }
            isochroneLayer = null;
        }
    }

    function setUserLocation(lat, lon, label) {
        if (typeof lat !== 'number' || typeof lon !== 'number') return;
        clearUserLocation();
        try {
            // Custom div-marker im Indigo-Stil
            var html = '<div style="' +
                'width:18px;height:18px;border-radius:50%;' +
                'background:#0369a1;border:3px solid #fff;' +
                'box-shadow:0 0 0 2px #0369a1,0 2px 8px rgba(0,0,0,0.3);' +
                '"></div>';
            var icon = L.divIcon({
                html: html,
                className: 'user-location-marker',
                iconSize: [24, 24],
                iconAnchor: [12, 12],
                tooltipAnchor: [0, -14]
            });
            userLocationMarker = L.marker([lat, lon], { icon: icon, zIndexOffset: 2000 });
            if (label) {
                userLocationMarker.bindTooltip(label, {
                    permanent: false,
                    direction: 'top',
                    className: 'map-tooltip'
                });
            }
            userLocationMarker.addTo(map);
        } catch (e) {
            console.error('setUserLocation fehlgeschlagen:', e);
        }
    }

    function clearUserLocation() {
        if (userLocationMarker) {
            try { map.removeLayer(userLocationMarker); } catch (e) { /* ignore */ }
            userLocationMarker = null;
        }
    }

    function clearAllOverlays() {
        clearIsochrone();
        clearUserLocation();
        if (typeof window.highlightSpots === 'function') {
            window.highlightSpots(null);
        }
    }

    // Zentrale Frontend-API für Tool-Calls aus dem Chat (Phase 1).
    // Strukturierte Namespace statt loser window-Funktionen.
    window.flymap = {
        get map() { return map; },
        get markers() { return markersByName; },
        drawIsochrone: drawIsochrone,
        clearIsochrone: clearIsochrone,
        setUserLocation: setUserLocation,
        clearUserLocation: clearUserLocation,
        highlightSpots: function (items) {
            if (typeof window.highlightSpots === 'function') {
                window.highlightSpots(items);
            }
        },
        clearHighlights: function () {
            if (typeof window.highlightSpots === 'function') {
                window.highlightSpots(null);
            }
        },
        clearAllOverlays: clearAllOverlays,
        fitBounds: function (bounds) {
            if (map && bounds) {
                try { map.fitBounds(bounds); } catch (e) { /* ignore */ }
            }
        }
    };

    // ===== START =====
    initMap();
})();
