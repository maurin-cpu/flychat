/* Synoptik-Karte (/synoptik): interaktive Bodendruckkarte im Met-Office-Stil.
 *
 * Rendert Isobaren (4-hPa-Intervall) + H/T-Druckzentren auf Leaflet aus dem
 * dichten Europa-Druckraster (/api/synoptic/grid, engine/synoptic_grid.py).
 * Konturen werden clientseitig mit d3.contours() berechnet: das 25x18-Raster
 * wird bilinear x4 hochgesampelt (glatte Linien), die Konturen entstehen im
 * Index-Raum und werden linear nach lat/lon transformiert — Leaflet macht
 * dann die Mercator-Projektion (keine Doppelprojektion).
 *
 * Zeitsteuerung: automatische Loop-Animation ueber alle Timesteps (Timeline-
 * Scrubber statt Tabs/Chips). Die Kontur-Geometrien werden pro Timestep einmal
 * berechnet und gecacht; der Frame-Wechsel ist ein Crossfade zwischen zwei
 * Leaflet-Panes (A/B), damit nichts flackert. Timestep-Keys sind LOKALE
 * Schweizer Zeit (kein "Z"-Suffix) — Stunden werden direkt aus dem String
 * angezeigt, nie ueber Date-TZ-Konvertierung.
 *
 * Daneben der Wetterlage-Textblock (LLM short/long) aus dem Synoptik-Cache;
 * der Tagesblock des aktuellen Animations-Tags wird hervorgehoben.
 */
(function () {
  "use strict";

  // Sichtbarer Kartenausschnitt (= maximale Zoom-out-Stufe): Europa inkl.
  // Island, etwas Nordafrika und Atlantik — ohne Groenland. Bewusst enger
  // als die Daten-Domain (config.SYNOPTIC_GRID_*): die Isobaren laufen so
  // sauber ueber den Kartenrand hinaus, statt an der Domaingrenze zu enden.
  var VIEW_BOUNDS = L.latLngBounds([30, -30], [67, 35]);

  var UPSAMPLE = 4;          // Raster-Verfeinerung vor d3.contours
  var ISOBAR_STEP = 2;       // hPa — Konturierungs-Schritt (inkl. Zwischenisobaren)
  var MAIN_EVERY = 4;        // Vielfache von 4 = durchgezogene Haupt-Isobaren
                             // (Met-Office-Standard); dazwischen (1002, 1006, ...)
                             // gestrichelte Zwischenisobaren — fuellen flache
                             // Druckfelder (z.B. Sahara-Hitzetief im Sommer)
  var LABEL_EVERY = 8;       // Vielfache von 8 beschriften
  var LABEL_MIN_POINTS = 12; // LineStrings kuerzer als das bekommen kein Label
  var LABEL_MIN_PX = 60;     // Mindestabstand zwischen Isobaren-Labels
  var BORDER_CELLS = 1.0;    // Rand-Filter: Segmente im aeussersten Fein-Zellring

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

  function $(id) { return document.getElementById(id); }

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  // ===== MAP INIT ==========================================================

  function initMap() {
    map = L.map("synMap", {
      minZoom: 2.5,
      maxZoom: 7,
      zoomSnap: 0.5,
      zoomControl: true,
      maxBoundsViscosity: 1.0,  // harte Grenze — kein Ziehen ueber den Ausschnitt hinaus
    });
    map.fitBounds(VIEW_BOUNDS);
    map.setMaxBounds(VIEW_BOUNDS.pad(0.02));
    map.setMinZoom(map.getBoundsZoom(VIEW_BOUNDS));

    // Basis + Labels wie map.js — Hillshade weggelassen (auf synoptischer
    // Skala nur Rauschen unter den Isobaren).
    L.tileLayer("https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png", {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; <a href="https://carto.com/">CARTO</a>',
      subdomains: "abcd",
      maxZoom: 18,
      opacity: 0.9,
    }).addTo(map);
    L.tileLayer("https://{s}.basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}{r}.png", {
      subdomains: "abcd",
      maxZoom: 18,
      opacity: 0.65,
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
  // offene LineStrings gesplittet.
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

    // Pro Threshold: alle Ringe -> LineStrings in lat/lng
    return contours.map(function (c) {
      var lines = [];
      c.coordinates.forEach(function (polygon) {
        polygon.forEach(function (ring) {
          ringToLineStrings(ring, up.W, up.H).forEach(function (line) {
            lines.push(line.map(function (p) { return idxToLatLng(meta, p[0], p[1]); }));
          });
        });
      });
      return { value: c.value, lines: lines };
    }).filter(function (c) { return c.lines.length > 0; });
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

  // ===== RENDER: ISOBAREN + LABELS + ZENTREN ===============================

  function renderLayers(isobars, ts, paneName, group) {
    var labelPositions = [];

    isobars.forEach(function (c) {
      var isMain = c.value % MAIN_EVERY === 0;
      var isMajor = c.value % LABEL_EVERY === 0;
      c.lines.forEach(function (line) {
        L.polyline(line, {
          pane: paneName,
          interactive: false,
          color: isMain ? "#334155" : "#64748b",
          weight: isMain ? (isMajor ? 1.8 : 1.1) : 0.8,
          opacity: isMain ? 0.9 : 0.5,
          dashArray: isMain ? null : "4 4",
          smoothFactor: 1,
        }).addTo(group);

        // Label am mittleren Vertex der laengeren Linien (nur Haupt-Isobaren)
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
          html: '<span class="syn-center-letter" role="img" aria-label="' + escapeHtml(aria) + '">'
              + escapeHtml(letter) + "</span>"
              + '<span class="syn-center-value">' + Math.round(c.msl_hpa) + "</span>",
          iconSize: [44, 44],
          iconAnchor: [22, 22],
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

  // ===== WETTERLAGE-TEXTPANEL ==============================================

  function renderWetterlageText() {
    var el = $("synWetterlage");
    if (!el) return;
    var wl = state.wetterlage;
    var overview = wl && wl.llm_overview ? wl.llm_overview : null;
    if (!overview || !overview.short) {
      el.hidden = false;
      el.innerHTML = '<p class="syn-text-empty">' + escapeHtml(wcT("js.syn.no_text")) + "</p>";
      return;
    }

    var lageLabel = (wl.lage_label && wl.lage_label.value) || "";
    var longEntries = Array.isArray(overview.long_with_sources)
      ? overview.long_with_sources.filter(function (e) { return e && e.text; })
      : [];

    // Wie briefing.js renderWetterlage: "Wochentag:" am Zeilenanfang fett,
    // flight_hint kursiv darunter. Jeder Tagesblock traegt data-weekday,
    // damit der Tag der laufenden Animation hervorgehoben werden kann.
    var longHtml = longEntries.length
      ? longEntries.map(function (e) {
          var txt = escapeHtml(e.text);
          var hint = e.flight_hint ? escapeHtml(e.flight_hint) : "";
          var hintHtml = hint
            ? '<p class="syn-text-hint"><span aria-hidden="true">⏵</span> ' + hint + "</p>"
            : "";
          var m = txt.match(/^([A-Za-zÀ-ž]+):\s*/);
          if (m) {
            return '<div class="syn-text-day-block" data-weekday="' + escapeHtml(m[1]) + '">' +
              '<p><strong>' + m[1] + ":</strong> " + txt.slice(m[0].length) + "</p>" +
              hintHtml + "</div>";
          }
          return '<div class="syn-text-day-block"><p>' + txt + "</p>" + hintHtml + "</div>";
        }).join("")
      : (overview.long ? "<p>" + escapeHtml(overview.long) + "</p>" : "");

    el.hidden = false;
    el.innerHTML =
      '<div class="syn-text-head">' +
        '<span class="syn-text-icon" aria-hidden="true">☼</span>' +
        '<span class="syn-text-title">' + escapeHtml(wcT("js.syn.wetterlage_title")) + "</span>" +
        (lageLabel ? '<span class="syn-text-lage">' + escapeHtml(lageLabel) + "</span>" : "") +
      "</div>" +
      '<div class="syn-text-summary"><p>' + escapeHtml(overview.short) + "</p></div>" +
      '<div class="syn-text-long">' + longHtml + "</div>";
    highlightTextDay();
  }

  // Tagesblock des aktuellen Animations-Frames hervorheben (Match ueber den
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
    el.querySelectorAll(".syn-text-day-block").forEach(function (block) {
      var wd = block.getAttribute("data-weekday");
      block.classList.toggle("is-active", !!wd && names.indexOf(wd) !== -1);
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
    var hint = $("synMapHint");
    if (hint && state.grid) {
      hint.textContent = wcT("js.syn.isobars_hint", { model: state.grid.model || "" });
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

    renderHeader();
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
