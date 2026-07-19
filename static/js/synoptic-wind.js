/* Wind-Partikel-Layer fuer die Synoptik-Karte (/synoptik).
 *
 * Zeichnet das uebergeordnete Stroemungsbild als animierte Partikel-Bahnen
 * (windy.com-Stil) auf einem Canvas ueber den Druckbaendern/Isobaren. Der
 * Wind ist der ECHTE 700-hPa-Modellwind (~3000 m), der pro Timestep als
 * u/v-Feld im Grid-Cache mitgeliefert wird (engine/synoptic_grid.py). Das ist
 * bewusst die Hoehenstroemung (konsistent mit Wetterlage-Callout und
 * Regionen-Hoehenwind), NICHT der Bodenwind. Frueher wurde der Wind
 * geostrophisch aus dem MSLP-Grid abgeleitet — ueber Gebirge (Alpen-Hitzetief)
 * war das nachweislich falsch; siehe docs/pläne/PLAN_synoptik_hoehenwind.md.
 * Fehlt `winds` im Grid (alter Cache), bleibt der Layer aus (kein Rueckfall
 * auf Geostrophie — lieber kein Wind als falscher).
 *
 * Rendering: eigenes Leaflet-Pane "synWind" (z 460 — ueber den Isobaren-
 * Panes 450/451, unter den H/T-Badges 470/471), darin ein Canvas mit
 * leaflet-zoom-hide (Fractional-Zoom-Animation wuerde sonst die Partikel
 * sichtbar von der Karte loesen). Projektion analytisch (Web-Mercator) —
 * keine Leaflet-Calls im Frame-Loop. Trail-Fade via destination-in, damit
 * das Canvas ueber der hellen Basemap transparent bleibt (kein Grauschleier).
 *
 * prefers-reduced-motion: kein Animations-Loop, stattdessen ein statischer
 * Pfeil-Snapshot auf einem ~48px-Raster (Laenge + Farbe = Staerke).
 * Timestep-Wechsel tauschen nur den Feld-Pointer: Partikel behalten ihre
 * Position und "morphen" in die neue Stroemung — kein Reset-Flackern.
 */
(function () {
  "use strict";

  // Geometrie / Cap
  var EARTH_R = 6378137;          // Web-Mercator-Radius
  var VMAX_MS = 60;               // reiner Ausreisser-Schutz (~216 km/h); der
                                  // echte 700-hPa-Wind wird nur bei Fehlwerten
                                  // gekappt, nicht kuenstlich gedaempft

  // Partikel / Look — bewusst ruhig gehalten: weniger, aber laengere Bahnen
  // lesen sich als fliessende Stroemung statt als dichtes Gewusel.
  var DENSITY_PX2 = 900;          // 1 Partikel je ~900 px2 (frueher 550 = dichter)
  var COUNT_MIN = 280;
  var COUNT_MAX = 1500;
  var TTL_MIN = 50, TTL_MAX = 150;  // Frames bis Respawn (laengere Bahnen)
  var FADE_ALPHA = 0.94;          // destination-in Trail-Fade pro Frame — hoeher
                                  // = laengere, ruhigere Streifen (weniger Flimmern)
  var LINE_WIDTH = 1.1;
  var LINE_ALPHA = 0.6;           // weicher (frueher 0.75) — dezenter ueber der Karte
  var SPEED_FACTOR = 55000;       // visuelle Uebertreibung: ~60 km/h => ~100 px/s
                                  // bei minZoom (skaliert mit Zoom via pxPerMeter)
  // Geschwindigkeits-KONTRAST: der Partikel-Schritt waechst super-linear mit
  // dem Windbetrag (Schritt ~ v^SPEED_GAMMA statt v). So kriecht schwacher Wind
  // sichtbar langsam, waehrend Starkwind deutlich schneller zieht. Rein
  // visuell — der Farb-Bucket zeigt weiter den echten km/h-Wert.
  var SPEED_GAMMA = 2.6;          // >1 spreizt langsam/schnell; hoch = extrem:
                                  // schwacher Wind quasi eingefroren, Starkwind zischt
  var SPEED_REF_MS = 8;           // Pivot (~29 km/h): hier Faktor 1; darunter stark
                                  // gedrueckt (0 km/h -> Stillstand), darueber beschleunigt
  var EMPH_MAX = 4.0;             // Deckel gegen ueberschnelle Partikel bei Starkwind
  var MAX_DT = 0.05;              // s — rAF-Luecken (Tab-Wechsel) kappen

  // Speed-Farbskala (km/h) — App-Tokens, bewusst abgesetzt von der blau/sand
  // Drucktoenung: ruhig = Slate, kraeftig = Primary, stark = Amber/Rose.
  // An der REALEN 700-hPa-Verteilung kalibriert (2026-07-18, 16560 Samples:
  // Median 30, P75 43, P90 55, P99 78, max 106 km/h) — Stops auf Median/P90/P99,
  // sonst bleibt alles blau oder saturiert zu frueh. Der echte Hoehenwind ist
  // staerker als der frueher gedaempfte Geostrophie-Output.
  var SPEED_STOPS = [
    [0,  "#64748b"],
    [30, "#0369a1"],
    [55, "#F59E0B"],
    [80, "#E11D48"],
  ];
  var SPEED_MAX_KMH = 90;
  var BUCKETS = 8;

  function speedScale() {
    return d3.scaleLinear()
      .domain(SPEED_STOPS.map(function (s) { return s[0]; }))
      .range(SPEED_STOPS.map(function (s) { return s[1]; }))
      .interpolate(d3.interpolateLab)
      .clamp(true);
  }

  // CSS-Gradient-Stops fuer die Legende (0..SPEED_MAX_KMH)
  function legendGradient() {
    var sc = speedScale();
    var stops = [];
    for (var v = 0; v <= SPEED_MAX_KMH; v += 10) {
      stops.push(sc(v) + " " + ((v / SPEED_MAX_KMH) * 100).toFixed(1) + "%");
    }
    return "linear-gradient(90deg," + stops.join(",") + ")";
  }

  // ===== WINDFELD (echter 700-hPa-Wind aus dem Grid-Cache) =================

  // Null-Luecken mit Nachbar-Mittel fuellen (Logik wie fillNulls in
  // synoptic-map.js — bewusst lokale Kopie, beide Module sind geschlossene
  // IIFEs und der Block ist klein).
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

  // 3x3-Binomial-Glaettung (1-2-1 x 1-2-1, Rand geclampt) gegen Grid-Rauschen
  // in den Ableitungen.
  function smooth3x3(meta, vals) {
    var ny = meta.ny, nx = meta.nx;
    var out = new Float64Array(ny * nx);
    for (var j = 0; j < ny; j++) {
      for (var i = 0; i < nx; i++) {
        var acc = 0, wsum = 0;
        for (var dj = -1; dj <= 1; dj++) {
          var jj = Math.min(ny - 1, Math.max(0, j + dj));
          var wj = dj === 0 ? 2 : 1;
          for (var di = -1; di <= 1; di++) {
            var ii = Math.min(nx - 1, Math.max(0, i + di));
            var w = wj * (di === 0 ? 2 : 1);
            acc += vals[jj * nx + ii] * w;
            wsum += w;
          }
        }
        out[j * nx + i] = acc / wsum;
      }
    }
    return out;
  }

  // Feld aus dem echten 700-hPa-u/v (m/s) des Grid-Cache bauen: Null-Luecken
  // fuellen, eine leichte 3x3-Glaettung gegen Grid-Rauschen, VMAX_MS nur als
  // Ausreisser-Schutz. Die Pipeline ist quellenagnostisch — Sampling/Rendering
  // bleiben unveraendert, es wechselt nur die Windquelle.
  function buildField(meta, wind) {
    var ny = meta.ny, nx = meta.nx;
    var us = smooth3x3(meta, fillNulls(meta, wind.u));
    var vs = smooth3x3(meta, fillNulls(meta, wind.v));
    var u = new Float32Array(ny * nx);
    var v = new Float32Array(ny * nx);
    for (var k = 0; k < ny * nx; k++) {
      var uu = us[k], vv = vs[k];
      var sp = Math.sqrt(uu * uu + vv * vv);
      if (sp > VMAX_MS) { uu *= VMAX_MS / sp; vv *= VMAX_MS / sp; }
      u[k] = uu;
      v[k] = vv;
    }
    return { u: u, v: v, ny: ny, nx: nx };
  }

  // ===== LAYER =============================================================

  function create(map, opts) {
    opts = opts || {};

    var pane = map.getPane("synWind") || map.createPane("synWind");
    pane.style.zIndex = "460";
    pane.style.pointerEvents = "none";

    var canvas = document.createElement("canvas");
    canvas.className = "syn-wind-canvas leaflet-zoom-hide";
    pane.appendChild(canvas);
    var ctx = canvas.getContext("2d");

    var st = {
      grid: null,             // { meta, winds, ... } (Referenz aufs Grid-Objekt)
      fields: {},             // ts -> buildField()-Ergebnis (lazy)
      field: null,            // aktives Feld
      enabled: false,
      reducedMotion: !!opts.reducedMotion,
      particles: null,        // Float32Array [x, y, age, ttl] * N
      count: 0,
      raf: null,
      lastT: 0,
      lastFrameMs: 0,
      // View-Konstanten (pro move/zoom aktualisiert, nie im Frame-Loop):
      view: { w: 0, h: 0, scale: 0, wx0: 0, wy0: 0 },
      colors: [],             // Bucket-Farben
      segs: [],               // Bucket -> flaches Segment-Array [x0,y0,x1,y1,...]
    };

    // Bucket-Farben einmal vorrechnen (Bucket b deckt Speed-Bereich
    // b/BUCKETS..(b+1)/BUCKETS von SPEED_MAX_KMH ab; Farbe am Bucket-Mittel).
    var sc = speedScale();
    for (var b = 0; b < BUCKETS; b++) {
      st.colors.push(sc((b + 0.5) * SPEED_MAX_KMH / BUCKETS));
      st.segs.push([]);
    }

    // ---- View / Projektion ----

    function refreshView() {
      var size = map.getSize();
      st.view.w = size.x;
      st.view.h = size.y;
      st.view.scale = 256 * Math.pow(2, map.getZoom());
      var tl = map.getPixelBounds().min;   // Welt-Pixel der Container-Ecke
      st.view.wx0 = tl.x;
      st.view.wy0 = tl.y;
      L.DomUtil.setPosition(canvas, map.containerPointToLayerPoint([0, 0]));
    }

    function resizeCanvas() {
      refreshView();
      var dpr = Math.min(window.devicePixelRatio || 1, 1.5);
      canvas.width = Math.round(st.view.w * dpr);
      canvas.height = Math.round(st.view.h * dpr);
      canvas.style.width = st.view.w + "px";
      canvas.style.height = st.view.h + "px";
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      spawnAll();
    }

    // Container-Pixel -> Breitengrad (inverse Web-Mercator); Laengengrad ist
    // linear in x, wird direkt in gridX gerechnet.
    function pxToLat(y) {
      var n = Math.PI - 2 * Math.PI * (st.view.wy0 + y) / st.view.scale;
      return (180 / Math.PI) * Math.atan(0.5 * (Math.exp(n) - Math.exp(-n)));
    }

    function pxToLon(x) {
      return (st.view.wx0 + x) / st.view.scale * 360 - 180;
    }

    function pxPerMeter(lat) {
      return st.view.scale / (2 * Math.PI * EARTH_R * Math.cos(lat * Math.PI / 180));
    }

    // Bilineares Sampling des aktiven u/v-Felds in GRID-Koordinaten;
    // ausserhalb der Datendomain -> null (Partikel respawnt).
    function sampleUV(gx, gy, out) {
      var f = st.field;
      if (!f) return null;
      if (gx < 0 || gy < 0 || gx > f.nx - 1 || gy > f.ny - 1) return null;
      var i0 = Math.min(Math.floor(gx), f.nx - 2);
      var j0 = Math.min(Math.floor(gy), f.ny - 2);
      var fx = gx - i0, fy = gy - j0;
      var k00 = j0 * f.nx + i0, k01 = k00 + 1, k10 = k00 + f.nx, k11 = k10 + 1;
      out.u = f.u[k00] * (1 - fx) * (1 - fy) + f.u[k01] * fx * (1 - fy)
            + f.u[k10] * (1 - fx) * fy + f.u[k11] * fx * fy;
      out.v = f.v[k00] * (1 - fx) * (1 - fy) + f.v[k01] * fx * (1 - fy)
            + f.v[k10] * (1 - fx) * fy + f.v[k11] * fx * fy;
      return out;
    }

    // ---- Partikel ----

    function targetCount() {
      var n = st.view.w * st.view.h / DENSITY_PX2;
      // Beim Reinzoomen ausduennen: die Partikel-Schrittweite waechst mit dem
      // Zoom (px/m), die Bahnen werden laenger und schneller -> das Bild wuerde
      // sonst deutlich dichter wirken. Pro Zoomstufe ueber minZoom die Dichte
      // reduzieren haelt es ruhig.
      var over = Math.max(0, map.getZoom() - map.getMinZoom());
      if (over > 0) n = n / (1 + over * 0.6);
      n = Math.max(COUNT_MIN, Math.min(COUNT_MAX, Math.round(n)));
      var coarse = window.matchMedia
        && (window.matchMedia("(max-width: 560px)").matches
            || window.matchMedia("(pointer: coarse)").matches);
      if (coarse) n = Math.round(n * 0.5);
      return n;
    }

    function spawnOne(k) {
      var P = st.particles;
      P[k] = Math.random() * st.view.w;
      P[k + 1] = Math.random() * st.view.h;
      P[k + 2] = 0;
      P[k + 3] = TTL_MIN + Math.random() * (TTL_MAX - TTL_MIN);
    }

    function spawnAll() {
      st.count = targetCount();
      st.particles = new Float32Array(st.count * 4);
      for (var k = 0; k < st.count * 4; k += 4) spawnOne(k);
      ctx.clearRect(0, 0, st.view.w, st.view.h);
    }

    var _uv = { u: 0, v: 0 };  // wiederverwendetes Sample-Objekt (keine Allokation im Loop)

    function frame(t) {
      st.raf = null;
      if (!st.enabled || st.reducedMotion || !st.field) return;
      var t0 = performance.now();

      var dt = st.lastT ? Math.min((t - st.lastT) / 1000, MAX_DT) : 0.016;
      st.lastT = t;

      // Trail-Fade: Alpha des bestehenden Bilds abbauen — Canvas bleibt
      // transparent (destination-in), kein weisses Rect ueber der Basemap.
      ctx.globalCompositeOperation = "destination-in";
      ctx.fillStyle = "rgba(0, 0, 0, " + FADE_ALPHA + ")";
      ctx.fillRect(0, 0, st.view.w, st.view.h);
      ctx.globalCompositeOperation = "source-over";

      var meta = st.grid.meta;
      var P = st.particles;
      var bMax = BUCKETS - 1;
      var segs = st.segs;
      for (var b = 0; b < BUCKETS; b++) segs[b].length = 0;

      for (var k = 0; k < st.count * 4; k += 4) {
        var x = P[k], y = P[k + 1];
        var lat = pxToLat(y);
        var lon = pxToLon(x);
        var gx = (lon - meta.lon0) / meta.dlon;
        var gy = (lat - meta.lat0) / meta.dlat;

        if (P[k + 2]++ > P[k + 3] || !sampleUV(gx, gy, _uv)) {
          spawnOne(k);
          continue;
        }

        var ppm = pxPerMeter(lat);
        // Kontrast-Betonung: Schritt ~ v^SPEED_GAMMA (emph=1 bei SPEED_REF_MS).
        var sp = Math.sqrt(_uv.u * _uv.u + _uv.v * _uv.v);
        var emph = sp > 0.1
          ? Math.min(EMPH_MAX, Math.pow(sp / SPEED_REF_MS, SPEED_GAMMA - 1))
          : 0;
        var step = ppm * dt * SPEED_FACTOR * emph;
        var nx2 = x + _uv.u * step;
        var ny2 = y - _uv.v * step;                     // v>0 = nordwaerts = y faellt

        if (nx2 < 0 || ny2 < 0 || nx2 > st.view.w || ny2 > st.view.h) {
          spawnOne(k);
          continue;
        }

        var kmh = sp * 3.6;
        var bucket = Math.min(bMax, Math.floor(kmh / SPEED_MAX_KMH * BUCKETS));
        var s = segs[bucket];
        s.push(x, y, nx2, ny2);

        P[k] = nx2;
        P[k + 1] = ny2;
      }

      // Segmente gebatcht pro Farb-Bucket zeichnen (1 stroke() je Bucket)
      ctx.lineWidth = LINE_WIDTH;
      ctx.globalAlpha = LINE_ALPHA;
      for (var bb = 0; bb < BUCKETS; bb++) {
        var arr = segs[bb];
        if (!arr.length) continue;
        ctx.strokeStyle = st.colors[bb];
        ctx.beginPath();
        for (var q = 0; q < arr.length; q += 4) {
          ctx.moveTo(arr[q], arr[q + 1]);
          ctx.lineTo(arr[q + 2], arr[q + 3]);
        }
        ctx.stroke();
      }
      ctx.globalAlpha = 1;

      st.lastFrameMs = performance.now() - t0;
      schedule();
    }

    function schedule() {
      if (st.raf == null && st.enabled && !st.reducedMotion && st.field
          && !document.hidden) {
        st.raf = requestAnimationFrame(frame);
      }
    }

    function stop() {
      if (st.raf != null) { cancelAnimationFrame(st.raf); st.raf = null; }
      st.lastT = 0;
    }

    // ---- Statischer Pfeil-Snapshot (prefers-reduced-motion) ----

    function drawArrows() {
      ctx.clearRect(0, 0, st.view.w, st.view.h);
      if (!st.field || !st.grid) return;
      var meta = st.grid.meta;
      var GRID = 48;                       // Screen-Raster in px
      ctx.lineWidth = 1.6;
      ctx.lineCap = "round";
      ctx.globalAlpha = 0.8;
      for (var y = GRID / 2; y < st.view.h; y += GRID) {
        var lat = pxToLat(y);
        for (var x = GRID / 2; x < st.view.w; x += GRID) {
          var lon = pxToLon(x);
          var gx = (lon - meta.lon0) / meta.dlon;
          var gy = (lat - meta.lat0) / meta.dlat;
          if (!sampleUV(gx, gy, _uv)) continue;
          var kmh = Math.sqrt(_uv.u * _uv.u + _uv.v * _uv.v) * 3.6;
          if (kmh < 2) continue;
          // Screen-Richtung: x = Ost, y = Sued (v>0 zeigt nach oben)
          var ang = Math.atan2(-_uv.v, _uv.u);
          var len = 10 + Math.min(1, kmh / SPEED_MAX_KMH) * 12;
          var cos = Math.cos(ang), sin = Math.sin(ang);
          var x1 = x + cos * len / 2, y1 = y + sin * len / 2;
          var x0 = x - cos * len / 2, y0 = y - sin * len / 2;
          var bucket = Math.min(BUCKETS - 1, Math.floor(kmh / SPEED_MAX_KMH * BUCKETS));
          ctx.strokeStyle = st.colors[bucket];
          ctx.beginPath();
          ctx.moveTo(x0, y0);
          ctx.lineTo(x1, y1);
          // Pfeilspitze
          var hw = 3.2;
          ctx.moveTo(x1 - cos * hw * 1.8 - sin * hw, y1 - sin * hw * 1.8 + cos * hw);
          ctx.lineTo(x1, y1);
          ctx.lineTo(x1 - cos * hw * 1.8 + sin * hw, y1 - sin * hw * 1.8 - cos * hw);
          ctx.stroke();
        }
      }
      ctx.globalAlpha = 1;
    }

    function repaint() {
      if (!st.enabled) return;
      if (st.reducedMotion) drawArrows();
      else schedule();
    }

    // ---- Map-Events ----

    function onMove() {
      refreshView();
      if (st.enabled && st.reducedMotion) drawArrows();
    }

    function onZoomStart() { stop(); }

    function onZoomEnd() {
      refreshView();
      // Alte Trails sind im neuen Massstab falsch. Partikel neu aufsetzen, damit
      // die zoomabhaengige Dichte (targetCount) im neuen Massstab greift —
      // spawnAll leert dabei auch das Canvas.
      spawnAll();
      repaint();
    }

    function onVisibility() {
      if (document.hidden) stop(); else repaint();
    }

    map.on("move", onMove);
    map.on("zoomstart", onZoomStart);
    map.on("zoomend", onZoomEnd);
    map.on("resize", resizeCanvas);
    document.addEventListener("visibilitychange", onVisibility);

    resizeCanvas();

    // ---- Public API ----

    var api = {
      // Grid setzen. Return: true, wenn 700-hPa-Wind vorhanden ist (Layer
      // aktivierbar); false bei altem Cache ohne `winds` (Aufrufer soll dann
      // den Toggle disabled lassen — kein Rueckfall auf Geostrophie).
      setGrid: function (grid) {
        st.grid = grid;
        st.fields = {};
        st.field = null;
        return !!(grid && grid.winds && Object.keys(grid.winds).length);
      },
      hasWind: function () {
        return !!(st.grid && st.grid.winds && Object.keys(st.grid.winds).length);
      },
      setTimestep: function (ts) {
        var w = st.grid && st.grid.winds && st.grid.winds[ts];
        if (!w) { st.field = null; return; }
        if (!st.fields[ts]) {
          st.fields[ts] = buildField(st.grid.meta, w);
        }
        st.field = st.fields[ts];
        repaint();
      },
      setEnabled: function (on) {
        on = !!on;
        if (on === st.enabled) return;
        st.enabled = on;
        if (on) {
          pane.style.display = "";
          repaint();
        } else {
          stop();
          ctx.clearRect(0, 0, st.view.w, st.view.h);
          pane.style.display = "none";
        }
      },
      isEnabled: function () { return st.enabled; },
      setReducedMotion: function (rm) {
        st.reducedMotion = !!rm;
        stop();
        ctx.clearRect(0, 0, st.view.w, st.view.h);
        repaint();
      },
      destroy: function () {
        stop();
        map.off("move", onMove);
        map.off("zoomstart", onZoomStart);
        map.off("zoomend", onZoomEnd);
        map.off("resize", resizeCanvas);
        document.removeEventListener("visibilitychange", onVisibility);
        if (canvas.parentNode) canvas.parentNode.removeChild(canvas);
      },
      // Debug/Test-Zugriff (Playwright-Asserts)
      get particleCount() { return st.count; },
      get lastFrameMs() { return st.lastFrameMs; },
    };

    // Debug-Handle analog window.wingcastSynMap
    window.wingcastSynWind = api;
    return api;
  }

  window.WingcastWind = {
    create: create,
    legendGradient: legendGradient,
    SPEED_MAX_KMH: SPEED_MAX_KMH,
  };
})();
