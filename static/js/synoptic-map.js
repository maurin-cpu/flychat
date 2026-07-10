/* Synoptik-Karte (/synoptik): interaktive Bodendruckkarte.
 *
 * Redesign 07/2026: Das Druckfeld wird als dezente Farbband-Toenung gerendert
 * (kuehles Blau = Tief, warmes Sand = Hoch, neutral um 1013 hPa), darueber
 * ruhige 4-hPa-Isobaren — Hochs und Tiefs sind so auf einen Blick lesbar.
 * Dazu H/T-Badges im App-Stil, eine Glas-Legende und die Zeitleiste als
 * schwebende Kontrollleiste unten auf der Karte.
 *
 * Rendert aus dem dichten Europa-Druckraster (/api/synoptic/grid,
 * engine/synoptic_grid.py). Konturen werden clientseitig mit d3.contours()
 * berechnet: das 25x18-Raster wird bilinear x4 hochgesampelt (glatte Linien),
 * die Konturen entstehen im Index-Raum und werden linear nach lat/lon
 * transformiert — Leaflet macht dann die Mercator-Projektion (keine
 * Doppelprojektion). Die Farbbaender entstehen aus denselben Konturen:
 * Band k = Ringe von Kontur k + Ringe von Kontur k+1 als Loecher
 * (fillRule evenodd) — keine Opacity-Stapelung, exakte Bandflaechen.
 *
 * Zeitsteuerung: automatische Loop-Animation ueber alle Timesteps (Timeline-
 * Scrubber statt Tabs/Chips). Die Kontur-Geometrien werden pro Timestep einmal
 * berechnet und gecacht; der Frame-Wechsel ist ein Crossfade zwischen zwei
 * Leaflet-Panes (A/B), damit nichts flackert. Timestep-Keys sind LOKALE
 * Schweizer Zeit (kein "Z"-Suffix) — Stunden werden direkt aus dem String
 * angezeigt, nie ueber Date-TZ-Konvertierung.
 *
 * Daneben Wetterlage-Kurzfassung (Lage-Badge + LLM short) ueber der Karte und
 * Tages-Karten (LLM long) darunter; die Karte des aktuellen Animations-Tags
 * wird hervorgehoben.
 */
(function () {
  "use strict";

  // Fallback-Datendomain (config.SYNOPTIC_GRID_*): die Isobaren fuellen exakt
  // diese Laengengrad-Spanne. Nach dem Laden wird auf die echten grid.meta-
  // Bounds praezisiert (fitWidthToData). Die Karte wird randlos auf die
  // BREITE dieser Domain gelegt — nicht enger, nicht breiter: sonst steht
  // leere Basemap neben den Isobaren (oder ihre Enden werden abgeschnitten).
  var DATA_BOUNDS = L.latLngBounds([20, -65], [75, 57.5]);

  var UPSAMPLE = 4;          // Raster-Verfeinerung vor d3.contours
  var ISOBAR_STEP = 4;       // hPa — nur Haupt-Isobaren (Met-Office-Standard);
                             // die frueheren 2-hPa-Zwischenisobaren sind raus:
                             // das Druckfeld traegt jetzt die Farbtoenung
  var LABEL_EVERY = 8;       // Vielfache von 8 beschriften + staerker zeichnen
  var LABEL_MIN_POINTS = 12; // LineStrings kuerzer als das bekommen kein Label
  var LABEL_MIN_PX = 60;     // Mindestabstand zwischen Isobaren-Labels
  var BORDER_CELLS = 1.0;    // Rand-Filter: Segmente im aeussersten Fein-Zellring

  // Druckband-Toenung: diverging um den Normaldruck 1013 hPa.
  // Lab-Interpolation (gleichmaessige Helligkeitsverlaeufe, kein Grau-Knick).
  var FILL_DOMAIN = [980, 1000, 1013, 1026, 1044];
  var FILL_RANGE = ["#1d4ed8", "#93c5fd", "#f4f6f8", "#fcd34d", "#d97706"];
  var FILL_OPACITY = 0.42;

  // Animation-Timing: STEP_MS = Verweildauer pro Timestep, FADE_MS = Pane-
  // Crossfade (muss zur CSS-Transition von .syn-fade-pane passen).
  var STEP_MS = 1200;
  var FADE_MS = 420;

  // Zwei Panes fuer flackerfreien Crossfade: der naechste Timestep wird in das
  // unsichtbare Pane gerendert, dann wird per CSS-Opacity ueberblendet.
  var PANES = ["synIsobarsA", "synIsobarsB"];

  var state = {
    grid: null,
    wetterlage: null,
    timesteps: [],    // ["2026-07-05T00:00", ...] — lokale CH-Zeit, sortiert wie geliefert
    tsIdx: 0,         // Index in timesteps = aktueller Frame
    playing: false,
    paneIdx: 0,       // welches Pane gerade sichtbar ist (0/1)
    cache: {},        // ts -> buildIsobars()-Geometrie (einmal pro Timestep)
    fadeGen: 0,       // Generation-Counter: verwaiste Fade-Cleanups verwerfen
    reducedMotion: false,
  };

  var map = null;
  var groups = [null, null];  // LayerGroups je Pane
  var timer = null;
  var fillScale = null;       // lazy — d3 muss geladen sein

  function $(id) { return document.getElementById(id); }

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  function fillColor(v) {
    if (!fillScale) {
      fillScale = d3.scaleLinear()
        .domain(FILL_DOMAIN)
        .range(FILL_RANGE)
        .interpolate(d3.interpolateLab)
        .clamp(true);
    }
    return fillScale(v);
  }

  // ===== MAP INIT ==========================================================

  // Bounds der Datendomain aus grid.meta (lat0/lon0 + Schrittweiten * n-1).
  function computeDataBounds(meta) {
    if (!meta) return DATA_BOUNDS;
    var latA = meta.lat0, latB = meta.lat0 + meta.dlat * (meta.ny - 1);
    var lonA = meta.lon0, lonB = meta.lon0 + meta.dlon * (meta.nx - 1);
    return L.latLngBounds(
      [Math.min(latA, latB), Math.min(lonA, lonB)],
      [Math.max(latA, latB), Math.max(lonA, lonB)]
    );
  }

  // Karte randlos auf die Laengengrad-Spanne der Daten legen. In Web-Mercator
  // ist px/Laengengrad konstant (256*2^z/360), der exakte Fuell-Zoom ist also
  // direkt loesbar. Die Karte laeuft dabei oben/unten ueber die Domain hinaus
  // (Container meist breiter als hoch) — so enden die Isobaren nie abrupt im
  // Leeren, sondern laufen sauber ueber den oberen/unteren Rand.
  function fitWidthToData(meta) {
    if (!map) return;
    var b = computeDataBounds(meta);
    var w = map.getSize().x;
    if (!w) return;
    var lonSpan = b.getEast() - b.getWest();
    var z = Math.log(w * 360 / (256 * lonSpan)) / Math.LN2;
    map.setMinZoom(z);
    map.setMaxBounds(b.pad(0.01));
    map.setView(b.getCenter(), z, { animate: false });
  }

  function initMap() {
    map = L.map("synMap", {
      minZoom: 2.5,
      maxZoom: 7,
      zoomSnap: 0,                // exakter Fractional-Zoom fuers randlose Breite-Fuellen
      zoomDelta: 0.5,             // Zoom-Schritte per Steuerung/Wheel bleiben grob
      zoomControl: true,
      attributionControl: false,  // Attribution steht in der Hint-Zeile unter der Karte
      maxBoundsViscosity: 1.0,    // harte Grenze — kein Ziehen ueber den Ausschnitt hinaus
    });
    fitWidthToData(null);         // Default-Domain bis die echten meta-Bounds da sind

    // Bei Resize (Breakpoint-Wechsel) neu auf Breite fitten — nur wenn nicht
    // hineingezoomt (sonst wuerde ein Resize die User-Ansicht zuruecksetzen).
    map.on("resize", function () {
      if (map.getZoom() <= map.getMinZoom() + 1e-6) {
        fitWidthToData(state.grid && state.grid.meta);
      }
    });

    // Sehr zurueckhaltende Basemap: die Druckbaender/Isobaren sind die Figur,
    // die Karte nur der Grund. Ortslabels stark gedimmt (nur Orientierung).
    L.tileLayer("https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png", {
      subdomains: "abcd",
      maxZoom: 18,
    }).addTo(map);
    L.tileLayer("https://{s}.basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}{r}.png", {
      subdomains: "abcd",
      maxZoom: 18,
      opacity: 0.38,
    }).addTo(map);

    // A/B-Panes fuer den Crossfade zwischen Timesteps
    for (var i = 0; i < PANES.length; i++) {
      var pane = map.createPane(PANES[i]);
      pane.style.zIndex = String(450 + i);
      pane.style.opacity = "0";
      pane.classList.add("syn-fade-pane");
      groups[i] = L.layerGroup().addTo(map);
    }

    // Nach Zoom die aktuelle Zeit neu rendern (Label-Entzerrung ist
    // zoomabhaengig) — instant, ohne Fade.
    map.on("zoomend", function () {
      if (state.grid && state.timesteps.length) showTimestep(true);
    });

    // Debug-/Tooling-Zugriff analog window.wingcastMap in map.js
    window.wingcastSynMap = map;
  }

  // ===== GRID -> ISOBAREN ==================================================

  // Null-Luecken (selten, ECMWF ist global) mit Nachbar-Mittel fuellen,
  // damit Upsampling/Konturierung nicht an einzelnen Loechern scheitert.
  function fillNulls(meta, vals) {
    var out = vals.slice();
    var ny = meta.ny, nx = meta.nx;
    for (var pass = 0; pass < 3; pass++) {
      var missing = false;
      for (var j = 0; j < ny; j++) {
        for (var i = 0; i < nx; i++) {
          if (out[j * nx + i] != null) continue;
          var acc = 0, n = 0;
          [[j-1,i],[j+1,i],[j,i-1],[j,i+1]].forEach(function (p) {
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
    // Falls nach 3 Paessen noch Loecher bleiben (praktisch nie): mit dem
    // Feld-Mittel fuellen. Sonst wuerde upsampleBilinear null*x=0 rechnen und
    // eine ~1000-hPa-Kante einschleusen.
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

  // d3.contours liefert geschlossene Band-Polygone; die Ringe laufen am
  // Gridrand entlang und wuerden dort einen falschen rechteckigen
  // Isobaren-Rahmen zeichnen. Segmente, deren BEIDE Endpunkte im
  // aeussersten Fein-Zellring liegen, werden gedroppt; der Rest wird in
  // offene LineStrings gesplittet. (Nur fuer die LINIEN — die Fuellflaechen
  // brauchen die vollstaendigen Ringe bis zum Rand.)
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

    // Pro Threshold: LineStrings (randgefiltert) fuer die Isobaren-Linien
    // UND die vollstaendigen Ringe fuer die Band-Fuellung. WICHTIG: hier
    // nicht filtern — die Band-Paarung braucht ALLE Thresholds (auch die
    // unterste Kontur, deren Ring komplett am Rand laeuft und daher keine
    // sichtbare Linie hat).
    return contours.map(function (c) {
      var lines = [];
      var fillRings = [];
      c.coordinates.forEach(function (polygon) {
        polygon.forEach(function (ring) {
          fillRings.push(ring.map(function (p) { return idxToLatLng(meta, p[0], p[1]); }));
          ringToLineStrings(ring, up.W, up.H).forEach(function (line) {
            lines.push(line.map(function (p) { return idxToLatLng(meta, p[0], p[1]); }));
          });
        });
      });
      return { value: c.value, lines: lines, fillRings: fillRings };
    });
  }

  // Geometrie-Cache: buildIsobars ist der teure Schritt — genau einmal pro
  // Timestep rechnen, damit die Animation nie stottert.
  function getIsobars(ts) {
    if (state.cache[ts]) return state.cache[ts];
    var meta = state.grid && state.grid.meta;
    var vals = state.grid && state.grid.values ? state.grid.values[ts] : null;
    if (!meta || !vals) return null;
    var iso = buildIsobars(meta, vals);
    state.cache[ts] = iso;
    return iso;
  }

  // Restliche Timesteps im Hintergrund vorrechnen (gestaffelt, damit die UI
  // nach dem ersten Frame sofort reagiert).
  function precomputeAll() {
    var idx = 0;
    function step() {
      while (idx < state.timesteps.length && state.cache[state.timesteps[idx]]) idx++;
      if (idx >= state.timesteps.length) return;
      try { getIsobars(state.timesteps[idx]); } catch (e) { /* defensiv */ }
      idx++;
      setTimeout(step, 40);
    }
    setTimeout(step, 60);
  }

  // ===== RENDER: BAENDER + ISOBAREN + LABELS + ZENTREN =====================

  // Druckband zwischen Threshold i und i+1: Ringe der Kontur i als Flaeche,
  // Ringe der Kontur i+1 als Loecher — mit fillRule "evenodd" ergibt das die
  // exakte Bandflaeche ohne Opacity-Stapelung ueberlappender Konturen.
  function renderBands(isobars, paneName, group) {
    for (var i = 0; i < isobars.length; i++) {
      var rings = isobars[i].fillRings;
      if (!rings.length) continue;
      var next = isobars[i + 1];
      var holes = next ? next.fillRings : [];
      L.polygon(rings.concat(holes), {
        pane: paneName,
        interactive: false,
        stroke: false,
        fillRule: "evenodd",
        fillColor: fillColor(isobars[i].value + ISOBAR_STEP / 2),
        fillOpacity: FILL_OPACITY,
        smoothFactor: 1,
      }).addTo(group);
    }
  }

  function renderLayers(isobars, ts, paneName, group) {
    renderBands(isobars, paneName, group);

    var labelPositions = [];

    isobars.forEach(function (c) {
      var isMajor = c.value % LABEL_EVERY === 0;
      c.lines.forEach(function (line) {
        L.polyline(line, {
          pane: paneName,
          interactive: false,
          color: "#475569",
          weight: isMajor ? 1.7 : 1,
          opacity: isMajor ? 0.85 : 0.55,
          smoothFactor: 1,
        }).addTo(group);

        // Label am mittleren Vertex der laengeren Linien (nur 8-hPa-Isobaren)
        if (isMajor && line.length >= LABEL_MIN_POINTS) {
          var mid = line[Math.floor(line.length / 2)];
          var pt = map.latLngToLayerPoint(mid);
          var tooClose = labelPositions.some(function (o) {
            return Math.abs(o.x - pt.x) < LABEL_MIN_PX && Math.abs(o.y - pt.y) < LABEL_MIN_PX;
          });
          if (!tooClose) {
            labelPositions.push(pt);
            L.marker(mid, {
              pane: paneName,
              interactive: false,
              icon: L.divIcon({
                className: "syn-isobar-label",
                html: String(c.value),
                iconSize: [40, 17],
                iconAnchor: [20, 9],
              }),
            }).addTo(group);
          }
        }
      });
    });

    renderCenters(ts, paneName, group);
  }

  function renderCenters(ts, paneName, group) {
    var centers = (state.grid.centers && state.grid.centers[ts]) || [];
    centers.forEach(function (c) {
      var isHigh = c.type === "Hoch";
      var letter = wcT(isHigh ? "js.syn.high_letter" : "js.syn.low_letter");
      var aria = wcT(isHigh ? "js.syn.high_aria" : "js.syn.low_aria",
                     { p: Math.round(c.msl_hpa) });
      L.marker([c.lat, c.lon], {
        pane: paneName,
        interactive: false,
        icon: L.divIcon({
          className: "syn-center-icon " + (isHigh ? "syn-center-icon--hoch" : "syn-center-icon--tief"),
          html: '<span class="syn-center-badge" role="img" aria-label="' + escapeHtml(aria) + '">'
              + escapeHtml(letter) + "</span>"
              + '<span class="syn-center-value">' + Math.round(c.msl_hpa) + "</span>",
          iconSize: [44, 54],
          iconAnchor: [22, 18],
        }),
      }).addTo(group);
    });
  }

  // Aktuellen Timestep anzeigen: in das verdeckte Pane rendern, dann
  // Crossfade (CSS-Opacity). instant=true ueberspringt den Fade (Erstrender,
  // Zoom-Rerender, reduced motion).
  function showTimestep(instant) {
    if (!map || !state.grid) return;
    var ts = currentTs();
    if (!ts) return;
    var iso = getIsobars(ts);
    if (!iso) return;

    state.fadeGen++;
    var gen = state.fadeGen;
    var prevIdx = state.paneIdx;
    var nextIdx = 1 - prevIdx;
    var nextGroup = groups[nextIdx];
    var prevGroup = groups[prevIdx];
    var nextPane = map.getPane(PANES[nextIdx]);
    var prevPane = map.getPane(PANES[prevIdx]);
    if (!nextGroup || !prevGroup || !nextPane || !prevPane) return;

    nextGroup.clearLayers();
    renderLayers(iso, ts, PANES[nextIdx], nextGroup);
    state.paneIdx = nextIdx;

    if (instant || state.reducedMotion) {
      nextPane.classList.add("syn-pane-notransition");
      prevPane.classList.add("syn-pane-notransition");
      nextPane.style.opacity = "1";
      prevPane.style.opacity = "0";
      prevGroup.clearLayers();
      // Reflow erzwingen, dann Transition wieder aktivieren
      void nextPane.offsetWidth;
      nextPane.classList.remove("syn-pane-notransition");
      prevPane.classList.remove("syn-pane-notransition");
    } else {
      nextPane.style.opacity = "1";
      prevPane.style.opacity = "0";
      setTimeout(function () {
        // Nur aufraeumen, wenn kein neuerer Frame dazwischenkam (das
        // Pane koennte sonst schon wieder frische Layer tragen).
        if (gen === state.fadeGen) prevGroup.clearLayers();
      }, FADE_MS + 80);
    }
  }

  // ===== ZEITSTEUERUNG / ANIMATION =========================================

  function currentTs() {
    return state.timesteps[state.tsIdx] || null;
  }

  function locale() {
    return window.WC_LANG === "en" ? "en-GB" : "de-CH";
  }

  // dateStr = "2026-07-05" (Kalenderdatum, CH-Zeit). Mittag als Anker, damit
  // der Wochentag in jeder Browser-TZ stimmt.
  function dateObj(dateStr) {
    return new Date(dateStr + "T12:00:00");
  }

  function fmtDayShort(dateStr) {
    var d = dateObj(dateStr);
    var wd = d.toLocaleDateString(locale(), { weekday: "short" });
    return wd + " " + d.getDate() + (window.WC_LANG === "en" ? "" : ".");
  }

  function fmtDayLong(dateStr) {
    return dateObj(dateStr).toLocaleDateString(locale(), {
      weekday: "short", day: "numeric", month: "long",
    });
  }

  // "Mo., 6. Juli · 12:00" — Stunde direkt aus dem Timestep-String (lokale
  // CH-Zeit), NICHT ueber Date (Browser-TZ koennte abweichen).
  function fmtReadout(ts) {
    return fmtDayLong(ts.slice(0, 10)) + " · " + ts.slice(11, 16);
  }

  function buildTimeline() {
    var el = $("synTimeline");
    if (!el) return;
    var N = state.timesteps.length;
    if (!N) { el.innerHTML = ""; return; }
    el.setAttribute("role", "group");
    el.setAttribute("aria-label", wcT("js.syn.timeline_aria"));

    // Timesteps nach Kalendertag gruppieren (Anzahl Tage kommt aus config —
    // hier bewusst NICHT hartkodiert, alles aus dem Array abgeleitet).
    var days = [];
    state.timesteps.forEach(function (ts) {
      var date = ts.slice(0, 10);
      if (!days.length || days[days.length - 1].date !== date) {
        days.push({ date: date, count: 0 });
      }
      days[days.length - 1].count++;
    });

    var daysHtml = days.map(function (d) {
      return '<div class="syn-tl-day-label" style="flex-grow:' + d.count + '">'
        + escapeHtml(fmtDayShort(d.date)) + "</div>";
    }).join("");

    var ticksHtml = state.timesteps.map(function (ts, i) {
      var date = ts.slice(0, 10);
      var hour = ts.slice(11, 16);
      var dayStart = i > 0 && state.timesteps[i - 1].slice(0, 10) !== date;
      var aria = wcT("js.syn.tick_aria", { d: fmtDayLong(date), t: hour });
      return '<button type="button" class="syn-tl-tick' + (dayStart ? " is-day-start" : "")
        + '" data-idx="' + i + '" data-hour="' + escapeHtml(hour)
        + '" aria-label="' + escapeHtml(aria) + '">'
        + '<span class="syn-tl-dot" aria-hidden="true"></span>'
        + '<span class="syn-tl-time">' + escapeHtml(hour) + "</span></button>";
    }).join("");

    el.innerHTML =
      '<div class="syn-tl-days">' + daysHtml + "</div>" +
      '<div class="syn-tl-track">' +
        '<span class="syn-tl-line" aria-hidden="true"></span>' +
        '<span class="syn-tl-fill" id="synTlFill" aria-hidden="true"></span>' +
        ticksHtml +
      "</div>";

    // Linie/Fill zwischen erstem und letztem Dot-Zentrum ausrichten
    // (Dot-Zentren liegen bei (i + 0.5) / N der Trackbreite).
    var pad = (50 / N) + "%";
    var line = el.querySelector(".syn-tl-line");
    if (line) { line.style.left = pad; line.style.right = pad; }
    var fill = $("synTlFill");
    if (fill) { fill.style.left = pad; fill.style.width = "0%"; }

    // Klick auf einen Tick: dorthin springen UND einfrieren (Pause)
    el.querySelectorAll(".syn-tl-tick").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var i = parseInt(btn.getAttribute("data-idx"), 10);
        if (isNaN(i) || !state.timesteps[i]) return;
        pause();
        state.tsIdx = i;
        showTimestep(false);
        updateTimelineUI(false);
      });
    });
  }

  // Aktive/vergangene Ticks, Fortschritts-Fill, Zeit-Readout und
  // Wetterlage-Tageshighlight nachziehen. wrapped=true (Loop-Neustart):
  // Fill springt ohne Transition zurueck statt rueckwaerts zu animieren.
  function updateTimelineUI(wrapped) {
    var N = state.timesteps.length;
    var el = $("synTimeline");
    if (el && N) {
      el.querySelectorAll(".syn-tl-tick").forEach(function (btn) {
        var i = parseInt(btn.getAttribute("data-idx"), 10);
        var active = i === state.tsIdx;
        btn.classList.toggle("is-active", active);
        btn.classList.toggle("is-past", i < state.tsIdx);
        if (active) btn.setAttribute("aria-current", "true");
        else btn.removeAttribute("aria-current");
      });
      var fill = $("synTlFill");
      if (fill) {
        if (wrapped) fill.classList.add("syn-notransition");
        fill.style.width = (state.tsIdx * 100 / N) + "%";
        if (wrapped) {
          void fill.offsetWidth;
          fill.classList.remove("syn-notransition");
        }
      }
    }
    var ro = $("synReadout");
    if (ro) {
      var ts = currentTs();
      ro.textContent = ts ? fmtReadout(ts) : "";
    }
    highlightTextDay();
  }

  function advance() {
    var N = state.timesteps.length;
    if (!N) return;
    var wrapped = state.tsIdx >= N - 1;
    state.tsIdx = (state.tsIdx + 1) % N;
    showTimestep(false);
    updateTimelineUI(wrapped);
  }

  function play() {
    if (state.playing || state.timesteps.length < 2) return;
    state.playing = true;
    updatePlayBtn();
    var tl = $("synTimeline");
    if (tl) tl.classList.add("is-playing");
    // aria-live waehrend der Wiedergabe aussetzen — sonst wuerde der
    // Screenreader alle STEP_MS den neuen Zeitpunkt vorlesen
    var ro = $("synReadout");
    if (ro) ro.removeAttribute("aria-live");
    timer = setInterval(advance, STEP_MS);
  }

  function pause() {
    if (timer) { clearInterval(timer); timer = null; }
    if (!state.playing) return;
    state.playing = false;
    updatePlayBtn();
    var tl = $("synTimeline");
    if (tl) tl.classList.remove("is-playing");
    var ro = $("synReadout");
    if (ro) ro.setAttribute("aria-live", "polite");
  }

  function updatePlayBtn() {
    var btn = $("synPlayBtn");
    if (!btn) return;
    btn.classList.toggle("is-playing", state.playing);
    var label = wcT(state.playing ? "js.syn.pause" : "js.syn.play");
    btn.setAttribute("aria-label", label);
    btn.title = label;
  }

  function bindPlayBtn() {
    var btn = $("synPlayBtn");
    if (!btn) return;
    btn.addEventListener("click", function () {
      if (state.playing) pause(); else play();
    });
    updatePlayBtn();
  }

  // ===== LEGENDE ===========================================================

  // Glas-Legende (Kartenecke): Farbskala der Druckband-Toenung.
  function renderLegend() {
    var el = $("synLegend");
    if (!el) return;
    var lo = FILL_DOMAIN[0];
    var hi = FILL_DOMAIN[FILL_DOMAIN.length - 1];
    var stops = [];
    for (var v = lo; v <= hi; v += 4) {
      stops.push(fillColor(v) + " " + (((v - lo) / (hi - lo)) * 100).toFixed(1) + "%");
    }
    el.innerHTML =
      '<div class="syn-legend-title">' + escapeHtml(wcT("js.syn.legend_title")) + "</div>" +
      '<div class="syn-legend-bar" style="background:linear-gradient(90deg,' + stops.join(",") + ')"></div>' +
      '<div class="syn-legend-scale" aria-hidden="true">' +
        "<span>" + escapeHtml(wcT("js.syn.legend_low")) + "</span>" +
        "<span>1013</span>" +
        "<span>" + escapeHtml(wcT("js.syn.legend_high")) + "</span>" +
      "</div>";
    el.hidden = false;
  }

  // ===== WETTERLAGE: SUMMARY + TAGES-KARTEN ================================

  var HINT_ICON =
    '<svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor"' +
    ' stroke-width="2" stroke-linecap="round" aria-hidden="true">' +
    '<path d="M17.7 7.7a2.5 2.5 0 1 1 1.8 4.3H2"/>' +
    '<path d="M9.6 4.6A2 2 0 1 1 11 8H2"/>' +
    '<path d="M12.6 19.4A2 2 0 1 0 14 16H2"/></svg>';

  // Wolken-/Wetter-Icon fuer das Callout-Panel der Wetterlage-Kurzfassung.
  var SUMMARY_ICON =
    '<span class="syn-summary-icon" aria-hidden="true">' +
    '<svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor"' +
    ' stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' +
    '<path d="M17.5 19a4.5 4.5 0 0 0 .3-9 6 6 0 0 0-11.5 1.5A4 4 0 0 0 6.5 19z"/>' +
    "</svg></span>";

  function renderWetterlageText() {
    var daysEl = $("synWetterlage");
    var sumEl = $("synSummary");
    if (!daysEl) return;
    var wl = state.wetterlage;
    var overview = wl && wl.llm_overview ? wl.llm_overview : null;
    if (!overview || !overview.short) {
      if (sumEl) sumEl.hidden = true;
      daysEl.hidden = false;
      daysEl.innerHTML = '<p class="syn-text-empty">' + escapeHtml(wcT("js.syn.no_text")) + "</p>";
      return;
    }

    // Lage-Label: Strukturfeld liefert den kanonischen DE-Wert; Anzeige
    // uebersetzt via i18n ("js.lage.<value>"), Fallback = DE-Wert (analog
    // briefing.js). Ohne Uebersetzung stuende sonst z.B. "Nordfoehnlage"
    // auf der englischen Seite.
    var lageRaw = (wl.lage_label && wl.lage_label.value) || "";
    var lageLabel = lageRaw
      ? ((window.WC_I18N && window.WC_I18N["js.lage." + lageRaw]) || lageRaw)
      : "";

    // Kurzfassung als Callout-Panel ueber der Karte: Wetter-Icon links,
    // dann Kicker + Lage als Titel, darunter die LLM-Kurzfassung.
    if (sumEl) {
      sumEl.hidden = false;
      sumEl.innerHTML =
        SUMMARY_ICON +
        '<div class="syn-summary-body">' +
          '<div class="syn-summary-head">' +
            '<span class="syn-summary-kicker">' + escapeHtml(wcT("js.syn.wetterlage_title")) + "</span>" +
            (lageLabel ? '<span class="syn-summary-lage">' + escapeHtml(lageLabel) + "</span>" : "") +
          "</div>" +
          '<p class="syn-summary-text">' + escapeHtml(overview.short) + "</p>" +
        "</div>";
    }

    var longEntries = Array.isArray(overview.long_with_sources)
      ? overview.long_with_sources.filter(function (e) { return e && e.text; })
      : [];

    // Tages-Karten: "Wochentag:" am Zeilenanfang wird zum Chip, flight_hint
    // mit Wind-Icon darunter. Jede Karte traegt data-weekday, damit der Tag
    // der laufenden Animation hervorgehoben werden kann. Stagger-Delay
    // inline (CSS animiert das Einblenden).
    var cardsHtml = longEntries.length
      ? longEntries.map(function (e, i) {
          var txt = escapeHtml(e.text);
          var hint = e.flight_hint ? escapeHtml(e.flight_hint) : "";
          var hintHtml = hint
            ? '<p class="syn-day-hint">' + HINT_ICON + "<span>" + hint + "</span></p>"
            : "";
          var delay = ' style="animation-delay:' + (i * 70) + 'ms"';
          var m = txt.match(/^([A-Za-zÀ-ž]+):\s*/);
          if (m) {
            return '<article class="syn-day-card" data-weekday="' + escapeHtml(m[1]) + '"' + delay + ">" +
              '<span class="syn-day-chip">' + m[1] + "</span>" +
              '<p class="syn-day-text">' + txt.slice(m[0].length) + "</p>" +
              hintHtml + "</article>";
          }
          return '<article class="syn-day-card"' + delay + '><p class="syn-day-text">' + txt + "</p>"
            + hintHtml + "</article>";
        }).join("")
      : (overview.long
          ? '<article class="syn-day-card"><p class="syn-day-text">' + escapeHtml(overview.long) + "</p></article>"
          : "");

    daysEl.hidden = !cardsHtml;
    daysEl.innerHTML = cardsHtml;
    daysEl.setAttribute("aria-label", wcT("js.syn.wetterlage_title"));
    highlightTextDay();
  }

  // Tages-Karte des aktuellen Animations-Frames hervorheben (Match ueber den
  // Wochentag, DE und EN — der LLM-Text traegt kein Datumsfeld).
  function highlightTextDay() {
    var el = $("synWetterlage");
    if (!el) return;
    var ts = currentTs();
    if (!ts) return;
    var d = dateObj(ts.slice(0, 10));
    var names = [
      d.toLocaleDateString("de-CH", { weekday: "long" }),
      d.toLocaleDateString("en-GB", { weekday: "long" }),
    ];
    el.querySelectorAll(".syn-day-card").forEach(function (card) {
      var wd = card.getAttribute("data-weekday");
      card.classList.toggle("is-active", !!wd && names.indexOf(wd) !== -1);
    });
  }

  // ===== HEADER / LADEN ====================================================

  function renderHeader() {
    var el = $("synGeneratedAt");
    if (el && state.grid && state.grid.generated_at) {
      var d = new Date(state.grid.generated_at);
      el.textContent = wcT("js.syn.updated", {
        ts: d.toLocaleString(locale(), {
          day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
        }),
      });
    }
    // Hint-Zeile traegt auch die Karten-Attribution (attributionControl ist
    // aus — die schwebende Zeitleiste laege sonst darueber).
    var hint = $("synMapHint");
    if (hint && state.grid) {
      hint.innerHTML = escapeHtml(wcT("js.syn.isobars_hint", { model: state.grid.model || "" })) +
        ' · <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">&copy; OpenStreetMap</a>' +
        ' · <a href="https://carto.com/attributions" target="_blank" rel="noopener">&copy; CARTO</a>';
    }
  }

  function showError(msg) {
    var el = $("synGeneratedAt");
    if (el) el.textContent = msg;
  }

  function hideMapLoading() {
    var el = $("synMapLoading");
    if (el) el.classList.add("is-hidden");
  }

  function showMapError(msg) {
    var el = $("synMapLoading");
    if (!el) return;
    el.classList.remove("is-hidden");
    el.classList.add("is-error");
    var txt = $("synMapLoadingText");
    if (txt) txt.textContent = msg;
  }

  function applyData(data) {
    state.grid = data.grid;
    state.wetterlage = data.wetterlage || null;
    state.timesteps = (data.grid.timesteps || []).slice();
    state.cache = {};

    // Startframe: 12:00 des ersten Tages wenn vorhanden, sonst erster Timestep
    state.tsIdx = 0;
    if (state.timesteps.length) {
      var firstDate = state.timesteps[0].slice(0, 10);
      for (var i = 0; i < state.timesteps.length; i++) {
        if (state.timesteps[i].slice(0, 10) === firstDate
            && state.timesteps[i].slice(11, 16) === "12:00") {
          state.tsIdx = i;
          break;
        }
      }
    }

    // Karte auf die echte Datendomain praezisieren (Fallback-Bounds ersetzen).
    fitWidthToData(data.grid.meta);

    renderHeader();
    renderLegend();
    buildTimeline();
    renderWetterlageText();

    var playBtn = $("synPlayBtn");
    if (playBtn) playBtn.disabled = state.timesteps.length < 2;

    if (!state.timesteps.length) {
      showError(wcT("js.syn.no_data"));
      showMapError(wcT("js.syn.no_data"));
      return;
    }

    showTimestep(true);         // Erstrender ohne Fade
    updateTimelineUI(true);
    hideMapLoading();
    precomputeAll();            // restliche Frames im Hintergrund cachen
  }

  function loadData(autoplay) {
    return fetch("/api/synoptic/grid")
      .then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return r.json();
      })
      .then(function (data) {
        if (!data.success || !data.grid) throw new Error(data.error || "no grid");
        applyData(data);
        // Autoplay-Loop — bei prefers-reduced-motion pausiert starten
        if (autoplay && !state.reducedMotion && state.timesteps.length > 1) play();
      })
      .catch(function (e) {
        console.error("synoptic-map: load failed", e);
        showError(wcT("js.syn.no_data"));
        showMapError(wcT("js.syn.no_data"));
      });
  }

  function bindRefresh() {
    var btn = $("synRefreshBtn");
    if (!btn) return;
    btn.addEventListener("click", function () {
      var orig = btn.textContent;
      var wasPlaying = state.playing;
      pause();
      btn.disabled = true;
      btn.textContent = wcT("js.generating");
      fetch("/api/synoptic/grid/refresh", { method: "POST" })
        .then(function (r) { return r.json(); })
        .then(function (data) {
          if (!data.success) throw new Error(data.error || "refresh failed");
          return loadData(wasPlaying);
        })
        .catch(function (e) {
          console.error("synoptic-map: refresh failed", e);
          showError(wcT("js.syn.load_failed"));
        })
        .then(function () {
          btn.disabled = false;
          btn.textContent = orig;
        });
    });
  }

  // ===== BOOT ==============================================================

  document.addEventListener("DOMContentLoaded", function () {
    if (!$("synMap") || typeof L === "undefined" || typeof d3 === "undefined") return;
    state.reducedMotion = !!(window.matchMedia
      && window.matchMedia("(prefers-reduced-motion: reduce)").matches);
    initMap();
    bindPlayBtn();
    bindRefresh();
    loadData(true);
  });
})();
