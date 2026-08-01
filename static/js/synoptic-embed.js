/* Synoptik-Embed fuer den Gleitcast (/briefing): kleine, NICHT-interaktive
 * Karte unter der Wetterlage-Gesamteinschaetzung — Druckbaender, Isobaren und
 * H/T-Badges ueber Europa (KEIN Wind, den gibt es nur auf der interaktiven
 * Karte /synoptik).
 *
 * Gezeigter Timestep: 12:00 des im Briefing GEWAEHLTEN Tages — briefing.js
 * meldet den Tag ueber window.WCSynopticEmbed.setDate(date). Karte und
 * Wetterlage-Text darueber beschreiben damit denselben Tag. Solange kein
 * Tag gemeldet wurde (oder ohne Day-Tabs), faellt die Wahl auf den Timestep
 * am ANALYSEZEITPUNKT (`wetterlage.generated_at`) — den Stand, auf dem der
 * Text beruht. Der gezeigte Stand steht sichtbar in der Kopfzeile.
 * Klick auf die Karte fuehrt zur grossen interaktiven Karte (/synoptik).
 *
 * Bewusst ein eigenstaendiges, schlankes Modul statt einer Wiederverwendung
 * von synoptic-map.js: das Seitenmodul ist eine geschlossene IIFE mit
 * Timeline/Legende/Crossfade — hier braucht es nur EIN statisches Rendering
 * (kompakte Kopie der Kontur-Pipeline, ohne Labels und ohne Animation der
 * Timesteps). Die Wind-Partikel kommen aus synoptic-wind.js (echtes Modul).
 * CSS: nutzt die .syn-center-*-Badge-Styles aus synoptik.css (im Briefing-
 * Template mitgeladen) + .bf-synoptic-Styles aus briefing.css.
 */
(function () {
  "use strict";

  var UPSAMPLE = 4;
  var ISOBAR_STEP = 4;
  var SMOOTH_ITER = 2;
  var BORDER_CELLS = 1.0;
  var FILL_DOMAIN = [980, 1000, 1013, 1026, 1044];
  // Identisch zur grossen Karte (synoptic-map.js) — beide Ansichten muessen
  // dieselbe Lage gleich einfaerben.
  var FILL_RANGE = ["#1d4ed8", "#93c5fd", "#f4f6f8", "#fcd34d", "#d97706"];
  // Gleiche Zurueckhaltung wie auf der grossen Karte: Toenung als Hintergrund,
  // Isobaren und Landkarte bleiben lesbar (vorher 0.42).
  var FILL_OPACITY = 0.22;
  // hPa-Beschriftung der Isobaren. Anders als auf /synoptik wird JEDE Isobare
  // beschriftet (dort nur die 8er-Vielfachen): im Europa-Ausschnitt liegen oft
  // nur zwei, drei Linien im Bild — bei 8er-Schritten bliebe die Karte ohne
  // eine einzige Druckangabe. Die Entzerrung ueber LABEL_MIN_PX verhindert
  // trotzdem Etiketten-Haufen.
  var LABEL_EVERY = 4;
  var LABEL_MIN_POINTS_IN_VIEW = 24;  // kuerzere Linienstuecke bleiben ohne
  var LABEL_MIN_PX = 70;              // Mindestabstand zweier Labels

  var fillScale = null;

  function fillColor(v) {
    if (!fillScale) {
      fillScale = d3.scaleLinear().domain(FILL_DOMAIN).range(FILL_RANGE)
        .interpolate(d3.interpolateLab).clamp(true);
    }
    return fillScale(v);
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  // ===== Kontur-Pipeline (kompakte Kopie aus synoptic-map.js) ==============

  function fillNulls(meta, vals) {
    var out = vals.slice();
    var ny = meta.ny, nx = meta.nx;
    for (var pass = 0; pass < 3; pass++) {
      var missing = false;
      for (var j = 0; j < ny; j++) {
        for (var i = 0; i < nx; i++) {
          if (out[j * nx + i] != null) continue;
          var acc = 0, n = 0;
          [[j - 1, i], [j + 1, i], [j, i - 1], [j, i + 1]].forEach(function (p) {
            if (p[0] >= 0 && p[0] < ny && p[1] >= 0 && p[1] < nx) {
              var v = out[p[0] * nx + p[1]];
              if (v != null) { acc += v; n++; }
            }
          });
          if (n) out[j * nx + i] = acc / n; else missing = true;
        }
      }
      if (!missing) break;
    }
    var sum = 0, cnt = 0;
    for (var k = 0; k < out.length; k++) {
      if (out[k] != null) { sum += out[k]; cnt++; }
    }
    if (cnt) {
      var mean = sum / cnt;
      for (var m = 0; m < out.length; m++) {
        if (out[m] == null) out[m] = mean;
      }
    }
    return out;
  }

  function upsampleBilinear(meta, vals) {
    var W = (meta.nx - 1) * UPSAMPLE + 1;
    var H = (meta.ny - 1) * UPSAMPLE + 1;
    var out = new Float64Array(W * H);
    for (var y = 0; y < H; y++) {
      var gy = y / UPSAMPLE;
      var j0 = Math.min(Math.floor(gy), meta.ny - 2);
      var fy = gy - j0;
      for (var x = 0; x < W; x++) {
        var gx = x / UPSAMPLE;
        var i0 = Math.min(Math.floor(gx), meta.nx - 2);
        var fx = gx - i0;
        var v00 = vals[j0 * meta.nx + i0];
        var v01 = vals[j0 * meta.nx + i0 + 1];
        var v10 = vals[(j0 + 1) * meta.nx + i0];
        var v11 = vals[(j0 + 1) * meta.nx + i0 + 1];
        out[y * W + x] = v00 * (1 - fx) * (1 - fy) + v01 * fx * (1 - fy)
                       + v10 * (1 - fx) * fy + v11 * fx * fy;
      }
    }
    return { W: W, H: H, values: out };
  }

  function idxToLatLng(meta, x, y) {
    return [
      meta.lat0 + y * (meta.dlat / UPSAMPLE),
      meta.lon0 + x * (meta.dlon / UPSAMPLE),
    ];
  }

  function chaikin(points, closed) {
    for (var it = 0; it < SMOOTH_ITER; it++) {
      var n = points.length;
      if (n < 3) return points;
      var out = [];
      if (!closed) out.push(points[0]);
      var last = closed ? n : n - 1;
      for (var i = 0; i < last; i++) {
        var p = points[i], q = points[(i + 1) % n];
        out.push([p[0] * 0.75 + q[0] * 0.25, p[1] * 0.75 + q[1] * 0.25]);
        out.push([p[0] * 0.25 + q[0] * 0.75, p[1] * 0.25 + q[1] * 0.75]);
      }
      if (!closed) out.push(points[n - 1]);
      points = out;
    }
    return points;
  }

  function ringToLineStrings(ring, W, H) {
    function onBorder(p) {
      return p[0] < BORDER_CELLS || p[0] > W - BORDER_CELLS
          || p[1] < BORDER_CELLS || p[1] > H - BORDER_CELLS;
    }
    var lines = [];
    var cur = [];
    for (var k = 0; k < ring.length; k++) {
      var p = ring[k];
      var q = ring[(k + 1) % ring.length];
      if (onBorder(p) && onBorder(q)) {
        if (cur.length > 1) lines.push(cur);
        cur = [];
      } else {
        if (!cur.length) cur.push(p);
        cur.push(q);
      }
    }
    if (cur.length > 1) lines.push(cur);
    return lines;
  }

  function buildIsobars(meta, rawVals) {
    var vals = fillNulls(meta, rawVals);
    var up = upsampleBilinear(meta, vals);
    var min = Infinity, max = -Infinity;
    for (var k = 0; k < up.values.length; k++) {
      if (up.values[k] < min) min = up.values[k];
      if (up.values[k] > max) max = up.values[k];
    }
    var thresholds = d3.range(
      Math.floor(min / ISOBAR_STEP) * ISOBAR_STEP,
      Math.ceil(max / ISOBAR_STEP) * ISOBAR_STEP + ISOBAR_STEP,
      ISOBAR_STEP
    );
    var contours = d3.contours().size([up.W, up.H]).thresholds(thresholds)(up.values);
    return contours.map(function (c) {
      var lines = [];
      var fillRings = [];
      c.coordinates.forEach(function (polygon) {
        polygon.forEach(function (ring) {
          fillRings.push(chaikin(ring, true).map(function (p) { return idxToLatLng(meta, p[0], p[1]); }));
          ringToLineStrings(ring, up.W, up.H).forEach(function (line) {
            lines.push(chaikin(line, false).map(function (p) { return idxToLatLng(meta, p[0], p[1]); }));
          });
        });
      });
      return { value: c.value, lines: lines, fillRings: fillRings };
    });
  }

  // ===== Timestep-Wahl / Formatierung ======================================

  // Timestep-Keys sind lokale CH-Zeit ("2026-07-13T18:00"). Gesucht ist der
  // Schritt, der dem ANALYSEZEITPUNKT am naechsten liegt — nicht der Uhrzeit
  // des Betrachters: Die Karte soll den Stand zeigen, auf dem der
  // Wetterlage-Text beruht. Wer den Cast um 19:00 liest, sieht sonst eine
  // Lage, die der Text nie beschrieben hat.
  //
  // `generated_at` kommt aus dem Synoptik-Cache (ISO ohne TZ-Suffix, lokale
  // CH-Zeit — gleiche Basis wie die Timestep-Keys). Fehlt es (alter Cache),
  // faellt die Wahl auf den ersten Timestep statt auf "jetzt": lieber der
  // Anfang des Prognosezeitraums als ein Zeitpunkt ohne Bezug zum Text.
  function analysisTimestep(timesteps, generatedAt) {
    var ref = generatedAt ? new Date(generatedAt).getTime() : NaN;
    if (isNaN(ref)) return timesteps[0];
    var best = timesteps[0], bestD = Infinity;
    timesteps.forEach(function (ts) {
      var d = Math.abs(new Date(ts) - ref);
      if (d < bestD) { bestD = d; best = ts; }
    });
    return best;
  }

  // Timestep fuer den im Briefing gewaehlten Tag: 12:00 lokale Zeit — die
  // klassische Mittagskarte. Exakter Treffer bevorzugt; fehlt er, der dem
  // Mittag naechste Schritt DESSELBEN Tages; liegt der Tag ganz ausserhalb
  // des Grids (Cache aelter als das Briefing), der insgesamt naechste
  // Schritt zum gewuenschten Mittag. Ohne Datum: Analysezeitpunkt.
  function timestepForDate(timesteps, dateStr, generatedAt) {
    if (!dateStr) return analysisTimestep(timesteps, generatedAt);
    var exact = dateStr + "T12:00";
    if (timesteps.indexOf(exact) !== -1) return exact;
    var ref = new Date(dateStr + "T12:00:00").getTime();
    var sameDay = timesteps.filter(function (ts) {
      return ts.slice(0, 10) === dateStr;
    });
    var pool = sameDay.length ? sameDay : timesteps;
    var best = pool[0], bestD = Infinity;
    pool.forEach(function (ts) {
      var d = Math.abs(new Date(ts) - ref);
      if (d < bestD) { bestD = d; best = ts; }
    });
    return best;
  }

  function fmtTs(ts) {
    var loc = window.WC_LANG === "en" ? "en-GB" : "de-CH";
    var d = new Date(ts.slice(0, 10) + "T12:00:00");
    return d.toLocaleDateString(loc, { weekday: "short", day: "numeric", month: "long" })
      + " · " + ts.slice(11, 16);
  }

  // ===== Karte =============================================================

  // Ausschnitt: Europa, nicht das ganze Datenraster. Das Raster reicht von
  // Groenland bis in den Nahen Osten — auf der Mini-Karte wurde Europa damit
  // zur Briefmarke am Rand. Gezeigt wird der Bereich, in dem die Lage fuer
  // Schweizer Piloten entsteht: Atlantik/Iberien bis Schwarzes Meer,
  // Mittelmeer bis Skandinavien. Isobaren und Flaechen werden weiterhin ueber
  // das volle Raster gerechnet, es wird nur enger geschaut.
  // Fester Europa-Ausschnitt im Zuschnitt klassischer Bodendruckkarten:
  // Nordatlantik bis Schwarzes Meer, Mittelmeer bis Nordskandinavien. Bewusst
  // FEST und nicht datenabhaengig — ein wanderndes Zentrum wuerde den
  // Bildausschnitt sonst taeglich veraendern, und ein Zentrum ueber dem
  // Kaspischen Meer (kommt vor) macht Europa wieder zur Briefmarke.
  // Breitenbereich bewusst knapp: das Kartenfeld ist sehr breit (2.35:1), ein
  // grosser Breitenbereich zieht deshalb automatisch halb Asien mit ins Bild.
  var EUROPE_BOUNDS = L.latLngBounds([35.5, -11.0], [59.0, 27.0]);

  function fitEurope(map) {
    // Padding, damit H/T-Badges am Rand nicht angeschnitten werden — sie
    // ragen ueber ihren Ankerpunkt hinaus (44x54 px Icon).
    map.fitBounds(EUROPE_BOUNDS, { animate: false, padding: [30, 26] });
  }

  // Druckzentren liegen ihrer Natur nach oft ausserhalb eines Europa-Rahmens
  // (am 26.07.2026 lagen ALLE drei knapp draussen: Nordmeer, Ionisches Meer,
  // Kaspisches Meer). Weglassen waere Informationsverlust — der Textblock
  // darueber spricht von genau diesen Gebilden. Solche Zentren werden darum
  // an den Bildrand geheftet und dort als "ausserhalb" gekennzeichnet, statt
  // zu verschwinden oder angeschnitten zu werden.
  // Geklemmt wird in PIXELN, nicht in Grad: das Badge ist 44x54 px gross und
  // haengt an einem Anker 18 px unter seiner Oberkante — ein prozentualer
  // Abstand zur Kartengrenze trifft diese Geometrie nicht und schneidet mal
  // den Buchstaben, mal die hPa-Zahl ab.
  var BADGE_MARGIN = { top: 22, bottom: 40, side: 26 };

  function clampToView(map, c) {
    var size = map.getSize();
    var pt = map.latLngToContainerPoint(L.latLng(c.lat, c.lon));
    var x = Math.min(Math.max(pt.x, BADGE_MARGIN.side), size.x - BADGE_MARGIN.side);
    var y = Math.min(Math.max(pt.y, BADGE_MARGIN.top), size.y - BADGE_MARGIN.bottom);
    return { latlng: map.containerPointToLatLng(L.point(x, y)),
             offmap: (x !== pt.x || y !== pt.y) };
  }

  function render(mapEl, grid, ts) {
    var map = L.map(mapEl, {
      zoomControl: false,
      attributionControl: false,
      dragging: false,
      scrollWheelZoom: false,
      doubleClickZoom: false,
      touchZoom: false,
      boxZoom: false,
      keyboard: false,
      zoomSnap: 0,
    });
    // Basemap wie auf /synoptik: Karte ohne Labels als Grund, darueber die
    // Ortslabels stark gedimmt. Der Embed hatte die Label-Ebene nicht und
    // wirkte dadurch leer — die Darstellung soll in beiden Ansichten
    // dieselbe sein.
    L.tileLayer("https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png", {
      subdomains: "abcd", maxZoom: 18,
    }).addTo(map);
    L.tileLayer("https://{s}.basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}{r}.png", {
      subdomains: "abcd", maxZoom: 18, opacity: 0.38,
    }).addTo(map);

    var allCenters = (grid.centers && grid.centers[ts]) || [];
    fitEurope(map, allCenters);

    var iso = buildIsobars(grid.meta, grid.values[ts]);

    // Druckbaender (Band i = Ringe i, Ringe i+1 als Loecher, evenodd)
    for (var i = 0; i < iso.length; i++) {
      var rings = iso[i].fillRings;
      if (!rings.length) continue;
      var holes = iso[i + 1] ? iso[i + 1].fillRings : [];
      L.polygon(rings.concat(holes), {
        interactive: false, stroke: false, fillRule: "evenodd",
        fillColor: fillColor(iso[i].value + ISOBAR_STEP / 2),
        fillOpacity: FILL_OPACITY, smoothFactor: 1,
      }).addTo(map);
    }

    // Sichtbarer Bereich mit Sicherheitsabstand — Etiketten und Badges ragen
    // ueber ihren Ankerpunkt hinaus und wuerden an der Kante angeschnitten.
    var visible = map.getBounds().pad(-0.07);

    // Positionen der H/T-Badges vorab bestimmen (inkl. Rand-Klemmung) und als
    // besetzt markieren: sonst legt eine Isobaren-Beschriftung sich ueber ein
    // Zentrum — Leaflet stapelt Marker nach Breitengrad, die suedlichere
    // Beschriftung landet dann VOR dem Badge.
    var centerPos = allCenters.map(function (c) {
      return { c: c, pos: clampToView(map, c) };
    });

    // Isobaren-Linien: exakt die Werte von /synoptik (synoptic-map.js) —
    // leichte graue Fuehrungslinien. Dazu die hPa-Beschriftung, gleiche
    // Markup-Klasse wie dort (.syn-isobar-label aus synoptik.css).
    var labelPositions = centerPos.map(function (e) {
      return map.latLngToLayerPoint(e.pos.latlng);
    });
    iso.forEach(function (c) {
      var isMajor = c.value % 8 === 0;
      c.lines.forEach(function (line) {
        L.polyline(line, {
          interactive: false, color: "#94a3b8",
          weight: isMajor ? 1.1 : 0.8,
          opacity: isMajor ? 0.48 : 0.3,
          lineJoin: "round",
          lineCap: "round",
          smoothFactor: 1,
        }).addTo(map);

        if (c.value % LABEL_EVERY !== 0) return;
        // Ankerpunkt aus den Stuetzpunkten IM BILD waehlen, nicht aus der
        // ganzen Linie: die Isobaren laufen weit ueber den Europa-Ausschnitt
        // hinaus, ihre Mitte liegt meist ueber dem Atlantik — das Label waere
        // dann nie zu sehen.
        var inView = line.filter(function (p) {
          return visible.contains(L.latLng(p));
        });
        if (inView.length < LABEL_MIN_POINTS_IN_VIEW) return;
        var mid = inView[Math.floor(inView.length / 2)];
        var pt = map.latLngToLayerPoint(mid);
        var tooClose = labelPositions.some(function (o) {
          return Math.abs(o.x - pt.x) < LABEL_MIN_PX
              && Math.abs(o.y - pt.y) < LABEL_MIN_PX;
        });
        if (tooClose) return;
        labelPositions.push(pt);
        L.marker(mid, {
          interactive: false,
          icon: L.divIcon({
            className: "syn-isobar-label",
            html: String(c.value),
            iconSize: [40, 17],
            iconAnchor: [20, 9],
          }),
        }).addTo(map);
      });
    });

    // H/T-Badges (gleiche Markup/Klassen wie /synoptik -> synoptik.css).
    // Zentren ausserhalb des Ausschnitts werden an den Rand geheftet und mit
    // --offmap gekennzeichnet: sie bleiben sichtbar, ohne angeschnitten zu
    // werden, und geben die Richtung an, in der das Gebilde liegt.
    centerPos.forEach(function (entry) {
      var c = entry.c, pos = entry.pos;
      var isHigh = c.type === "Hoch";
      var letter = wcT(isHigh ? "js.syn.high_letter" : "js.syn.low_letter");
      var aria = wcT(isHigh ? "js.syn.high_aria" : "js.syn.low_aria",
                     { p: Math.round(c.msl_hpa) });
      if (pos.offmap) aria += " — " + wcT("js.syn.center_offmap");
      L.marker(pos.latlng, {
        interactive: false,
        // Badges immer ueber den Isobaren-Etiketten (Leaflets Default sortiert
        // Marker nach Breitengrad, das reicht hier nicht).
        zIndexOffset: 1000,
        icon: L.divIcon({
          className: "syn-center-icon "
            + (isHigh ? "syn-center-icon--hoch" : "syn-center-icon--tief")
            + (pos.offmap ? " syn-center-icon--offmap" : ""),
          html: '<span class="syn-center-badge" role="img" aria-label="' + escapeHtml(aria) + '">'
              + escapeHtml(letter) + "</span>"
              + '<span class="syn-center-value">' + Math.round(c.msl_hpa) + "</span>",
          iconSize: [44, 54],
          iconAnchor: [22, 18],
        }),
      }).addTo(map);
    });

    // KEINE Wind-Partikel: die gehoeren auf die interaktive Karte (/synoptik).
    // Hier traegt der Ausschnitt Druckverteilung und Zentren — bewegte Pfeile
    // waeren auf dem kleinen, statischen Bild nur Unruhe.

    return map;
  }

  // ===== Boot / Tages-Steuerung ============================================
  // briefing.js meldet den gewaehlten Tag ueber WCSynopticEmbed.setDate().
  // Grid-Fetch und Briefing-Fetch laufen parallel — wer zuerst fertig ist,
  // spielt keine Rolle: setDate merkt sich das Datum, show() rendert erst,
  // wenn das Grid da ist.

  var _card = null, _mapEl = null;
  var _grid = null, _generatedAt = null;
  var _map = null;
  var _date = null;      // gewuenschter Briefing-Tag ("YYYY-MM-DD") oder null
  var _shownTs = null;   // aktuell gerenderter Timestep (Re-Render vermeiden)

  function show() {
    if (!_grid || !_card || !_mapEl) return;
    var ts = timestepForDate(_grid.timesteps, _date, _generatedAt);
    if (ts === _shownTs) return;
    // Leaflet-Karte vollstaendig ersetzen: die Kontur-Pipeline haengt am
    // Timestep, ein Layer-Austausch spart nichts Spuerbares bei 1x/Tag-Daten.
    if (_map) { _map.remove(); _map = null; }
    _mapEl.innerHTML = "";
    // Karte erst sichtbar machen (Leaflet braucht reale Groesse), dann rendern
    _card.hidden = false;
    var desc = document.getElementById("bfSynopticSub");
    if (desc) desc.textContent = "· " + wcT("js.syn.embed_sub");
    var sub = document.getElementById("bfSynopticTs");
    if (sub) sub.textContent = "· " + wcT("js.syn.embed_asof") + " " + fmtTs(ts);
    _map = render(_mapEl, _grid, ts);
    _shownTs = ts;
  }

  window.WCSynopticEmbed = {
    setDate: function (dateStr) {
      _date = dateStr || null;
      show();
    },
  };

  document.addEventListener("DOMContentLoaded", function () {
    _card = document.getElementById("bfSynoptic");
    _mapEl = document.getElementById("bfSynopticMap");
    if (!_card || !_mapEl || typeof L === "undefined" || typeof d3 === "undefined") return;

    // Bei Layout-Wechseln (Breakpoint) Karte neu einpassen — EIN Listener,
    // wirkt immer auf die aktuell gerenderte Karte.
    window.addEventListener("resize", function () {
      if (!_map) return;
      _map.invalidateSize();
      fitEurope(_map);
    });

    fetch("/api/synoptic/grid")
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (data) {
        var grid = data && data.grid;
        if (!data.success || !grid || !grid.timesteps || !grid.timesteps.length) return;
        _grid = grid;
        _generatedAt = data.wetterlage && data.wetterlage.generated_at;
        show();
      })
      .catch(function (e) {
        // Kein User-facing Error: die Karte ist ein Zusatz, das Briefing
        // funktioniert ohne sie — Karte bleibt einfach hidden.
        console.info("synoptic-embed: skipped (" + e.message + ")");
      });
  });
})();
