/* Synoptik-Embed fuer den Gleitcast (/briefing): kleine, NICHT-interaktive
 * Karte unter der Wetterlage-Gesamteinschaetzung — Druckbaender, Isobaren,
 * H/T-Badges und Wind-Partikel (via WingcastWind) fuer den Timestep, der dem
 * ANALYSEZEITPUNKT am naechsten liegt (`wetterlage.generated_at`), NICHT der
 * Uhrzeit des Betrachters. Die Karte belegt den Textblock darueber; ein
 * spaeterer Zeitschritt wuerde eine Lage zeigen, die der Text nie
 * beschrieben hat. Der Stand steht sichtbar in der Kopfzeile.
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

  function fmtTs(ts) {
    var loc = window.WC_LANG === "en" ? "en-GB" : "de-CH";
    var d = new Date(ts.slice(0, 10) + "T12:00:00");
    return d.toLocaleDateString(loc, { weekday: "short", day: "numeric", month: "long" })
      + " · " + ts.slice(11, 16);
  }

  // ===== Karte =============================================================

  function fitWidth(map, meta) {
    var latA = meta.lat0, latB = meta.lat0 + meta.dlat * (meta.ny - 1);
    var lonA = meta.lon0, lonB = meta.lon0 + meta.dlon * (meta.nx - 1);
    var b = L.latLngBounds([Math.min(latA, latB), Math.min(lonA, lonB)],
                           [Math.max(latA, latB), Math.max(lonA, lonB)]);
    var w = map.getSize().x;
    if (!w) return;
    var z = Math.log(w * 360 / (256 * (b.getEast() - b.getWest()))) / Math.LN2;
    map.setView(b.getCenter(), z, { animate: false });
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

    fitWidth(map, grid.meta);

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

    // Isobaren-Linien: exakt die Werte von /synoptik (synoptic-map.js) —
    // leichte graue Fuehrungslinien. Der Embed hatte sie dunkler und dicker,
    // dieselbe Lage sah damit in beiden Ansichten verschieden aus. Ohne
    // hPa-Labels, dafuer ist die Karte hier zu klein.
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
      });
    });

    // H/T-Badges (gleiche Markup/Klassen wie /synoptik -> synoptik.css)
    var centers = (grid.centers && grid.centers[ts]) || [];
    centers.forEach(function (c) {
      var isHigh = c.type === "Hoch";
      var letter = wcT(isHigh ? "js.syn.high_letter" : "js.syn.low_letter");
      var aria = wcT(isHigh ? "js.syn.high_aria" : "js.syn.low_aria",
                     { p: Math.round(c.msl_hpa) });
      L.marker([c.lat, c.lon], {
        interactive: false,
        icon: L.divIcon({
          className: "syn-center-icon " + (isHigh ? "syn-center-icon--hoch" : "syn-center-icon--tief"),
          html: '<span class="syn-center-badge" role="img" aria-label="' + escapeHtml(aria) + '">'
              + escapeHtml(letter) + "</span>"
              + '<span class="syn-center-value">' + Math.round(c.msl_hpa) + "</span>",
          iconSize: [44, 54],
          iconAnchor: [22, 18],
        }),
      }).addTo(map);
    });

    // Wind-Partikel (synoptic-wind.js) — immer an, reduced-motion beachtet
    if (window.WingcastWind) {
      var reduced = !!(window.matchMedia
        && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
      var wind = WingcastWind.create(map, { reducedMotion: reduced });
      // setGrid meldet, ob 700-hPa-Wind vorhanden ist; fehlt er (alter Cache),
      // bleibt der Layer aus und nur Isobaren/Badges werden gezeigt.
      if (wind.setGrid(grid)) {
        wind.setEnabled(true);
        wind.setTimestep(ts);
      }
    }

    // Bei Layout-Wechseln (Breakpoint) Karte neu einpassen
    window.addEventListener("resize", function () {
      map.invalidateSize();
      fitWidth(map, grid.meta);
    });

    return map;
  }

  // ===== Boot ==============================================================

  document.addEventListener("DOMContentLoaded", function () {
    var card = document.getElementById("bfSynoptic");
    var mapEl = document.getElementById("bfSynopticMap");
    if (!card || !mapEl || typeof L === "undefined" || typeof d3 === "undefined") return;

    fetch("/api/synoptic/grid")
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (data) {
        var grid = data && data.grid;
        if (!data.success || !grid || !grid.timesteps || !grid.timesteps.length) return;
        var generatedAt = data.wetterlage && data.wetterlage.generated_at;
        var ts = analysisTimestep(grid.timesteps, generatedAt);
        // Karte erst sichtbar machen (Leaflet braucht reale Groesse), dann rendern
        card.hidden = false;
        var desc = document.getElementById("bfSynopticSub");
        if (desc) desc.textContent = "· " + wcT("js.syn.embed_sub");
        var sub = document.getElementById("bfSynopticTs");
        if (sub) sub.textContent = "· " + wcT("js.syn.embed_asof") + " " + fmtTs(ts);
        render(mapEl, grid, ts);
      })
      .catch(function (e) {
        // Kein User-facing Error: die Karte ist ein Zusatz, das Briefing
        // funktioniert ohne sie — Karte bleibt einfach hidden.
        console.info("synoptic-embed: skipped (" + e.message + ")");
      });
  });
})();
