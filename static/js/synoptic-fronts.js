/*
 * Wetterfronten (DWD) auf den Synoptik-Karten — ein Modul fuer beide Karten:
 * die Briefing-Karte (synoptic-embed.js: /briefing, /synoptik/karte) und die
 * grosse Synoptik-Seite (synoptic-map.js: /synoptik).
 *
 * Daten: /api/synoptic/fronts?ts=… (engine/fronten.py) — Linie + Typ je Front
 * (kalt, warm, okklusion), aus den DWD-Karten vektorisiert.
 *
 * Darstellung (ui-ux-pro-max, 17.09.2026): Wetterdienst-Konvention — Kaltfront
 * blau mit Dreiecken, Warmfront rot mit Halbkreisen, Okklusion violett mit
 * beidem im Wechsel. Die Karte lebt von leisen Linien (Isobaren: Slate-400,
 * ~1 px, halbtransparent — siehe synoptic-map.js) und den H/T-Badges; die
 * Fronten uebernehmen genau deren Farben (Hoch-Blau, Tief-Rot) und Zurueck-
 * haltung: duenne Linie, kleine Symbole, kein harter weisser Rand — nur ein
 * weicher, halbtransparenter Saum, damit die Front ueber Wind-Streifen und
 * Tiefdruck-Blau nicht untergeht. (Eine kraeftige Version mit weisser Kontur
 * wirkte wie ein Fremdkoerper auf der Karte.) Die Form der Symbole traegt die
 * Bedeutung, nicht nur die Farbe. Legende im Stil von .syn-legend.
 *
 * Symbolseite: Die Vektoren kennen nur die Linie, nicht auf welcher Seite die
 * Dreiecke/Halbkreise sitzen — und genau die zeigt, wohin die Front zieht.
 * Raten waere irrefuehrend. Deshalb aus dem 700-hPa-Wind des Grids: eine Front
 * zieht etwa mit der Windkomponente quer zu ihrer Linie. Je Front EINE Seite
 * (laengengewichtet ueber alle Abschnitte), wie auf der Bodenkarte.
 *
 * Nutzung:
 *   var fronts = WCSynopticFronts.create(map, { legend: "card"|"compact", scale: 1 });
 *   fronts.update(grid, ts).then(...);   // laedt + zeichnet zum Timestep
 *   fronts.destroy();
 */
(function () {
  "use strict";

  // exakt die Badge-Farben (.syn-center-icon--hoch / --tief) + Violet-600
  var COLORS = { kalt: "#1d4ed8", warm: "#dc2626", okklusion: "#7c3aed" };
  var LINE_OPACITY = 0.74;
  var HALO = "rgba(255, 255, 255, 0.34)";
  var LABEL_KEYS = {
    kalt: ["js.syn.front_cold", "Cold front"],
    warm: ["js.syn.front_warm", "Warm front"],
    okklusion: ["js.syn.front_occl", "Occlusion"],
  };
  // Masse bei scale 1 (Briefing-Karte); die grosse Synoptik-Karte skaliert hoch.
  // Linie knapp ueber den Haupt-Isobaren (1.1 px), Symbole klein und luftig.
  var BASE = { line: 1.45, halo: 3.4, size: 3.8, spacing: 46 };
  var PANE = "wcFronts";

  var _cache = {};       // ts -> Promise(Antwort oder null)

  function load(ts) {
    if (!_cache[ts]) {
      _cache[ts] = fetch("/api/synoptic/fronts?ts=" + encodeURIComponent(ts))
        .then(function (r) { return r.ok ? r.json() : null; })
        .catch(function () { return null; });
    }
    return _cache[ts];
  }

  function t(key, fallback) {
    return (typeof wcT === "function" && wcT(key) !== key) ? wcT(key) : fallback;
  }

  // 700-hPa-Wind (u, v in m/s) am naechsten Gitterpunkt, oder null.
  // Raster zeilenweise: index = Breiten-Index * nx + Laengen-Index.
  function windAt(grid, ts, lat, lon) {
    var w = grid && grid.winds && grid.winds[ts];
    var m = grid && grid.meta;
    if (!w || !m || !w.u || !w.v) return null;
    var row = Math.round((lat - m.lat0) / m.dlat);
    var col = Math.round((lon - m.lon0) / m.dlon);
    if (row < 0 || col < 0 || row >= m.ny || col >= m.nx) return null;
    var u = w.u[row * m.nx + col], v = w.v[row * m.nx + col];
    return (u == null || v == null) ? null : { u: u, v: v };
  }

  // Zugseite einer Front: +1 = Normale (dy, -dx) im Bildschirm, -1 = Gegenseite.
  // Wind im Bildschirm: Ost = +x, Nord = -y.
  function motionSide(pts, lls, grid, ts) {
    var sum = 0;
    for (var k = 1; k < pts.length; k++) {
      var dx = pts[k].x - pts[k - 1].x, dy = pts[k].y - pts[k - 1].y;
      var len = Math.sqrt(dx * dx + dy * dy);
      if (!len) continue;
      var w = windAt(grid, ts, (lls[k].lat + lls[k - 1].lat) / 2,
                     (lls[k].lng + lls[k - 1].lng) / 2);
      if (!w) continue;
      sum += len * ((dy / len) * w.u + (-dx / len) * (-w.v));
    }
    return sum >= 0 ? 1 : -1;
  }

  // Die vektorisierten Fronten haben nur 10-15 Stuetzpunkte, und die zittern
  // (Rasterfehler der Vektorisierung) — als Polygonzug wirken sie zackig,
  // echte Fronten sind weich geschwungen. Deshalb: erst das Zittern glaetten
  // (gewichteter Mittelwert ueber drei Punkte), dann zweimal Chaikin-Ecken-
  // schnitt wie bei den Isobaren (synoptic-map.js), dann Catmull-Rom-Spline
  // fuer die Kurve. Endpunkte bleiben fest, die Front wandert dabei hoechstens
  // um wenige Pixel — weit unter der Unschaerfe der DWD-Karte selbst.
  var SMOOTH_STEPS = 6;
  function denoise(pts) {
    if (pts.length < 3) return pts;
    var out = [pts[0]];
    for (var i = 1; i < pts.length - 1; i++) {
      out.push(L.point(0.25 * pts[i - 1].x + 0.5 * pts[i].x + 0.25 * pts[i + 1].x,
                       0.25 * pts[i - 1].y + 0.5 * pts[i].y + 0.25 * pts[i + 1].y));
    }
    out.push(pts[pts.length - 1]);
    return out;
  }
  function chaikin(pts) {
    if (pts.length < 3) return pts;
    var out = [pts[0]];
    for (var i = 0; i < pts.length - 1; i++) {
      var a = pts[i], b = pts[i + 1];
      out.push(L.point(0.75 * a.x + 0.25 * b.x, 0.75 * a.y + 0.25 * b.y));
      out.push(L.point(0.25 * a.x + 0.75 * b.x, 0.25 * a.y + 0.75 * b.y));
    }
    out.push(pts[pts.length - 1]);
    return out;
  }
  function spline(pts) {
    if (pts.length < 3) return pts;
    var out = [pts[0]];
    for (var i = 0; i < pts.length - 1; i++) {
      var p0 = pts[Math.max(i - 1, 0)], p1 = pts[i],
          p2 = pts[i + 1], p3 = pts[Math.min(i + 2, pts.length - 1)];
      for (var k = 1; k <= SMOOTH_STEPS; k++) {
        var u = k / SMOOTH_STEPS, u2 = u * u, u3 = u2 * u;
        out.push(L.point(
          0.5 * ((2 * p1.x) + (-p0.x + p2.x) * u + (2 * p0.x - 5 * p1.x + 4 * p2.x - p3.x) * u2
                 + (-p0.x + 3 * p1.x - 3 * p2.x + p3.x) * u3),
          0.5 * ((2 * p1.y) + (-p0.y + p2.y) * u + (2 * p0.y - 5 * p1.y + 4 * p2.y - p3.y) * u2
                 + (-p0.y + 3 * p1.y - 3 * p2.y + p3.y) * u3)));
      }
    }
    return out;
  }
  // Kraeftig glaetten: dreimal entzittern, viermal Eckenschnitt (naehert sich
  // einer B-Spline — die Kurve laeuft NICHT mehr durch jeden Stuetzpunkt,
  // sondern schwingt wie eine Isobare), dann Spline fuer die Rundung. Die
  // Front weicht dabei an scharfen Knicken bis ~15 px vom Polygonzug ab —
  // unter der Unschaerfe der DWD-Vektorisierung.
  function smooth(pts) {
    // Kein Spline mehr obendrauf: nach vier Eckenschnitten liegen die Punkte
    // ~5 px auseinander, und Leaflet rundet jeden auf ganze Pixel — ein
    // dichter Spline wird dadurch zum Mikro-Zickzack (perlige Linie).
    var p = denoise(denoise(denoise(pts)));
    return chaikin(chaikin(chaikin(chaikin(p))));
  }

  function triangle(cx, cy, ex, ey, mx, my, s) {
    return [[cx - ex * s, cy - ey * s],
            [cx + ex * s, cy + ey * s],
            [cx + mx * s * 1.35, cy + my * s * 1.35]];
  }

  function semicircle(cx, cy, ex, ey, mx, my, s) {
    var out = [];
    for (var i = 0; i <= 10; i++) {
      var a = Math.PI * i / 10;
      out.push([cx + ex * s * Math.cos(a) + mx * s * Math.sin(a),
                cy + ey * s * Math.cos(a) + my * s * Math.sin(a)]);
    }
    return out;
  }

  // Symbole in festem Pixelabstand entlang der Linie. Okklusion: Dreieck und
  // Halbkreis im Wechsel.
  function symbols(pts, side, typ, dims) {
    var out = [], count = 0, offset = dims.spacing / 2;
    for (var k = 1; k < pts.length; k++) {
      var a = pts[k - 1], b = pts[k];
      var dx = b.x - a.x, dy = b.y - a.y, len = Math.sqrt(dx * dx + dy * dy);
      if (!len) continue;
      var ex = dx / len, ey = dy / len;
      var mx = side * ey, my = side * -ex;
      var d = offset;
      while (d <= len) {
        var cx = a.x + ex * d, cy = a.y + ey * d;
        var tri = typ === "kalt" || (typ === "okklusion" && count % 2 === 0);
        out.push(tri ? triangle(cx, cy, ex, ey, mx, my, dims.size)
                     : semicircle(cx, cy, ex, ey, mx, my, dims.size));
        count++;
        d += dims.spacing;
      }
      offset = d - len;
    }
    return out;
  }

  // Legenden-Muster: kurze Linie mit einem Symbol, in Frontfarbe auf hellem Grund
  function legendSample(typ) {
    var c = COLORS[typ];
    var sym = typ === "warm"
      ? '<path d="M10 8 A5 5 0 0 1 20 8 Z" fill="' + c + '"/>'
      : typ === "kalt"
        ? '<path d="M10 8 L20 8 L15 1.5 Z" fill="' + c + '"/>'
        : '<path d="M3 8 L11 8 L7 2.5 Z" fill="' + c + '"/><path d="M17 8 A4 4 0 0 1 25 8 Z" fill="' + c + '"/>';
    return '<svg class="wc-fronts-sample" width="28" height="10" viewBox="0 0 28 10" aria-hidden="true">'
      + '<line x1="0" y1="8" x2="28" y2="8" stroke="' + c + '" stroke-width="2.5"/>' + sym + '</svg>';
  }

  function create(map, opts) {
    opts = opts || {};
    var scale = opts.scale || 1;
    var dims = { line: BASE.line * scale, halo: BASE.halo * scale,
                 size: BASE.size * scale, spacing: BASE.spacing * scale };
    if (!map.getPane(PANE)) {
      var pane = map.createPane(PANE);
      pane.style.zIndex = 450;          // ueber Isobaren, unter den H/T-Badges
      pane.style.pointerEvents = "none";
    }
    var group = L.layerGroup().addTo(map);
    var state = { data: null, grid: null, ts: null, token: 0 };
    var legendEl = null;

    // Legende: Card oben rechts wie .syn-legend (/synoptik) oder kompakt unten
    // links (Briefing-Karte). Beide dieselbe Glas-Optik der App.
    if (opts.legend) {
      legendEl = L.DomUtil.create("div",
        "wc-fronts-legend" + (opts.legend === "card" ? " wc-fronts-legend--card" : " wc-fronts-legend--compact"),
        map.getContainer());
      legendEl.hidden = true;
      legendEl.setAttribute("aria-label", t("js.syn.fronts_src", "Fronts: DWD"));
    }

    function renderLegend() {
      if (!legendEl) return;
      var fc = state.data && state.data.fronts;
      if (!fc || !fc.features || !fc.features.length) { legendEl.hidden = true; return; }
      // Nur Typen, die im Kartenausschnitt wirklich zu sehen sind — sonst steht
      // "Okklusion" in der Legende, obwohl die einzige weit draussen liegt.
      var bounds = map.getBounds();
      var present = {};
      fc.features.forEach(function (f) {
        var inView = (f.geometry.coordinates || []).some(function (c) {
          return bounds.contains(L.latLng(c[1], c[0]));
        });
        if (inView) present[f.properties.typ] = true;
      });
      var rows = Object.keys(LABEL_KEYS).filter(function (k) { return present[k]; });
      if (!rows.length) { legendEl.hidden = true; return; }
      // Namensnennung nach GeoNutzV gehoert sichtbar dazu
      legendEl.innerHTML = '<div class="wc-fronts-legend-title">'
        + t("js.syn.fronts_src", "Fronts: DWD") + "</div>"
        + rows.map(function (k) {
            return '<div class="wc-fronts-legend-row">' + legendSample(k)
              + "<span>" + t(LABEL_KEYS[k][0], LABEL_KEYS[k][1]) + "</span></div>";
          }).join("");
      legendEl.title = state.data.copyright || "";
      legendEl.hidden = false;
    }

    function addPoly(poly, style) {
      L.polygon(poly.map(function (p) { return map.layerPointToLatLng(L.point(p[0], p[1])); }),
                Object.assign({ pane: PANE, interactive: false }, style)).addTo(group);
    }

    function redraw() {
      group.clearLayers();
      var fc = state.data && state.data.fronts;
      if (!fc || !fc.features) return;
      var drawn = [];
      fc.features.forEach(function (f) {
        var typ = f.properties && f.properties.typ;
        var color = COLORS[typ];
        var coords = f.geometry && f.geometry.coordinates;
        if (!color || !coords || coords.length < 2) return;
        var rawLls = coords.map(function (c) { return L.latLng(c[1], c[0]); });
        var rawPts = rawLls.map(function (ll) { return map.latLngToLayerPoint(ll); });
        var side = motionSide(rawPts, rawLls, state.grid, state.ts);
        var pts = smooth(rawPts);
        var lls = pts.map(function (p) { return map.layerPointToLatLng(p); });
        drawn.push({ lls: lls, color: color, polys: symbols(pts, side, typ, dims) });
      });
      // Zwei Durchgaenge: erst der weiche Saum unter ALLEN Fronten, dann die
      // Farbe — so ueberdeckt kein Saum eine benachbarte Front.
      drawn.forEach(function (d) {
        L.polyline(d.lls, { pane: PANE, color: HALO, weight: dims.halo, opacity: 1,
                            lineCap: "round", lineJoin: "round", smoothFactor: 0.7,
                            interactive: false }).addTo(group);
      });
      drawn.forEach(function (d) {
        L.polyline(d.lls, { pane: PANE, color: d.color, weight: dims.line,
                            opacity: LINE_OPACITY, lineCap: "round", lineJoin: "round",
                            smoothFactor: 0.7, interactive: false }).addTo(group);
        d.polys.forEach(function (poly) {
          addPoly(poly, { stroke: false, fillColor: d.color, fillOpacity: LINE_OPACITY });
        });
      });
    }

    // Symbole haben eine feste Pixelgroesse — bei Zoom neu setzen; die Legende
    // haengt am Ausschnitt
    map.on("zoomend viewreset", redraw);
    map.on("moveend", renderLegend);

    return {
      update: function (grid, ts) {
        state.grid = grid;
        state.ts = ts;
        var mine = ++state.token;
        return load(ts).then(function (data) {
          if (mine !== state.token) return;
          state.data = data && data.success && data.fronts ? data : null;
          redraw();
          renderLegend();
        });
      },
      destroy: function () {
        state.token++;
        map.off("zoomend viewreset", redraw);
        map.off("moveend", renderLegend);
        group.remove();
        if (legendEl && legendEl.parentNode) legendEl.parentNode.removeChild(legendEl);
      },
    };
  }

  window.WCSynopticFronts = {
    create: create,
    // fuer Tests/Diagnose
    _motionSide: motionSide,
    _windAt: windAt,
  };
})();
