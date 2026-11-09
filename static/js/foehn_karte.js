/* Föhn-Karte (/foehn, Admin). Zeigt, was das Briefing zählt, im Tagesverlauf:
   Druckunterschied, Wind in Kammhöhe (zehn Pässe), Wind am Boden (Pfeile), Regionen mit
   Föhnwind (Anteil der Punkte), Täler mit trockenem Föhnwind, Druck Zürich/Lugano.

   Daten: GET {data-api}?tag=N (N = Tagesindex, 0 = heute) → web.py api_foehn_karte:
     { datum, stunden: ["06".."17"], tage: {…|null}, pille, labels, satz (je Tag)
       grid: { meta, zellen: [[lat, lon, regionId|null]], winds: {HH: {u, v}}, rot: {HH: [0|1|2]} }
       druck: {HH: {nord: {druck, t800}, sued: {druck, t800}, dp}}   dp = Lugano − Zürich (hPa)
       kamm: {HH: [{id, speed, dir}]}   dir = Richtung, woher (°), speed in km/h (700 hPa)
       kamm_punkte: [{id, name, lat, lon}]
       taeler: {HH: {talId: {wind, gust, dir, rh, dir_dry, strikt}}}
       talpunkte: [{id, tal, gruppe, lat, lon}]
       stationen: [{seite, name, lat, lon}] }
   rot: 1 = Region mit Südwind, 2 = Region mit Nordwind (Regel karte_punkt_rot), 0 = nicht.
   Zahlen und Texte kommen aus dem Backend; dieses Skript rechnet nur, was es zeigt. */
(function () {
  "use strict";

  var T = window.FK_TEXT || {};
  var root = document.getElementById("fkRoot");
  var API = root.getAttribute("data-api");
  var CH = [[45.8, 5.9], [47.85, 10.55]];
  var TAKT_MS = 1400;
  var FARBE_STUFEN = ["#94a3b8", "#0ea5e9", "#f59e0b", "#dc2626"];   // schwach → sehr stark
  var FARBE_STAERKE = ["#f1f5f9", "#fef9c3", "#fde047", "#fb923c", "#ef4444", "#7f1d1d"];   // Gesamtstärke 0–5
  var FARBE_TAL = "#dc2626", FARBE_TAL_STARK = "#b91c1c", FARBE_TAL_AUS = "#94a3b8";
  var PFEIL_PFAD = "M7 0 L13 14 L7 10.5 L1 14 Z";

  var map;
  var pfeilLayer = L.layerGroup(), hoehenLayer = L.layerGroup(), regionLayer = null,
      talLayer = L.layerGroup(), stationLayer = L.layerGroup(), druckLayer = L.layerGroup();
  var regionLayers = {};         // region id → Leaflet-Layer (für die Färbung je Stunde)
  var regionCenter = {};         // region id → Mittelpunkt (für die Zahl)
  var regionLabelLayer = L.layerGroup();
  var regionSel = null;          // gewählte Region im Panel
  var regionGeo = null;          // GeoJSON-Features der Regionen
  var regionFlaeche = {};        // region id → Anzahl Rasterzellen
  var aktuell = null;            // letzte API-Antwort (ein Tag)
  var stunden = [];              // ["06", …, "17"]
  var stunde = 0;
  var timer = null;

  function $(id) { return document.getElementById(id); }
  function ebene(id) { return $(id) && $(id).checked; }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  // Windfarben wie auf den Startplätzen (meteogram.js windColor): grün bis 20 km/h,
  // dann gelb-orange, ab 30 km/h rot. Die Schwellen 20 und 30 km/h entsprechen
  // WIND_WARN_KMH und WIND_DANGER_KMH aus config.py.
  var WIND_STUFEN = [[10, "#059669"], [20, "#10B981"], [25, "#D97706"], [30, "#EA580C"]];
  var WIND_UEBER = "#DC2626";
  // Höhenwind 700 hPa (Recherche foehn_altitude_winds.md): grün unter 16, orange ab 16 (Hinweis),
  // rot ab 54 (Vorsicht), dunkelrot ab 90 (Gefahr). Eigene Skala, nicht die der Startplätze.
  var HOEHE_STUFEN = [[16, "#059669"], [54, "#EA580C"], [90, "#DC2626"]];
  var HOEHE_UEBER = "#7F1D1D";
  function farbeHoehe(kmh) {
    for (var i = 0; i < HOEHE_STUFEN.length; i++) {
      if (kmh < HOEHE_STUFEN[i][0]) return HOEHE_STUFEN[i][1];
    }
    return HOEHE_UEBER;
  }
  function farbeWind(kmh) {
    for (var i = 0; i < WIND_STUFEN.length; i++) {
      if (kmh <= WIND_STUFEN[i][0]) return WIND_STUFEN[i][1];
    }
    return WIND_UEBER;
  }
  // Pfeil wie die Synoptik-Pfeile: Linie mit offener Spitze, Länge 8–17 px nach Stärke.
  // winkel = Richtung, in die der Wind weht (0° = Norden, im Uhrzeigersinn).
  function pfeil(winkel, kmh, farbe, groesse, dicke, deckkraft) {
    groesse = groesse || 20; dicke = dicke || 1.4; deckkraft = deckkraft || 0.8;
    var L = 8 + Math.min(1, kmh / 90) * 9, hw = 2.3, t = 10 - L / 2;
    var pfad = "M10 " + (10 + L / 2) + " L10 " + t +
      " M" + (10 - hw) + " " + (t + hw * 1.7) + " L10 " + t + " L" + (10 + hw) + " " + (t + hw * 1.7);
    return '<div class="fk-pfeil" style="transform:rotate(' + winkel + 'deg);width:' + groesse + 'px;height:' + groesse + 'px">' +
      '<svg viewBox="0 0 20 20" aria-hidden="true"><path d="' + pfad + '" fill="none" stroke="' + farbe +
      '" stroke-width="' + dicke + '" stroke-linecap="round" stroke-linejoin="round" opacity="' + deckkraft + '"/></svg></div>';
  }
  // Richtung, in die der Wind weht: 0° = nach Norden, im Uhrzeigersinn
  function weht_nach(u, v) { return Math.atan2(u, v) * 180 / Math.PI; }

  // ---------- Karte ----------

  function initMap() {
    map = L.map("fkMap", { zoomControl: false, attributionControl: true, minZoom: 7, maxZoom: 11 });
    map.fitBounds(CH, { padding: [20, 20] });
    var basis = { subdomains: "abcd", maxZoom: 19, attribution: "&copy; OpenStreetMap, &copy; CARTO" };
    L.tileLayer(window.wcCartoUrl("https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png"), basis).addTo(map);
    L.tileLayer(window.wcCartoUrl("https://{s}.basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}{r}.png"),
      Object.assign({ opacity: 0.38, pane: "shadowPane" }, basis)).addTo(map);
    L.control.zoom({ position: "topright" }).addTo(map);

    regionLayer = L.layerGroup();
    [regionLayer, regionLabelLayer, hoehenLayer, talLayer, stationLayer, druckLayer].forEach(function (l) { l.addTo(map); });

    $("fkPlay").addEventListener("click", togglePlay);
    $("fkPanelBtn").addEventListener("click", function () { panel(true); });
    // Karte passt ihre Größe an: beim Laden, nach dem Fertigstellen des Layouts und bei Größenänderung
    var neuBerechnen = function () { map.invalidateSize(); };
    window.addEventListener("load", neuBerechnen);
    window.addEventListener("resize", neuBerechnen);
    setTimeout(neuBerechnen, 300);
    $("fkClose").addEventListener("click", function () { panel(false); });

    // Ebenen: jede Zeile der Legende schaltet genau ihre Schicht
    var schalter = [
      ["fkEbWind", pfeilLayer], ["fkEbKamm", hoehenLayer], ["fkEbRegion", regionLayer],
      ["fkEbTaeler", talLayer], ["fkEbStation", stationLayer]
    ];
    schalter.forEach(function (s) {
      $(s[0]).addEventListener("change", function () {
        if (this.checked) s[1].addTo(map); else map.removeLayer(s[1]);
        if (s[0] === "fkEbRegion") {        // die Zahlen gehören zur Regions-Ebene
          if (this.checked) regionLabelLayer.addTo(map); else map.removeLayer(regionLabelLayer);
        }
      });
    });
  }

  // Legende wie auf /synoptik: Verlauf der Windfarbskala, Stufen darunter
  // Skala proportional zum Wert (0–35 km/h), Grenzen bei 10, 20, 25, 30 km/h
  function fuelleLegende() {
    var MAX = 35;
    var grenzen = [0].concat(WIND_STUFEN.map(function (x) { return x[0]; }), [MAX]);
    var farben = WIND_STUFEN.map(function (x) { return x[1]; }).concat([WIND_UEBER]);
    var stops = farben.map(function (c, i) {
      return c + " " + (grenzen[i] / MAX * 100).toFixed(1) + "% " + (grenzen[i + 1] / MAX * 100).toFixed(1) + "%";
    });
    $("fkLegBar").style.background = "linear-gradient(90deg," + stops.join(",") + ")";
    $("fkLegBar").style.opacity = "1";
    $("fkLegWind").textContent = T.staerke || "";
    var marken = [["0", 0], ["10", 10], ["20", 20], ["25", 25], ["30+", 30]];
    var HMAX = 100;
    var hGrenzen = [0, 16, 54, 90, HMAX];
    var hFarben = [HOEHE_STUFEN[0][1], HOEHE_STUFEN[1][1], HOEHE_STUFEN[2][1], HOEHE_UEBER];
    var hStops = hFarben.map(function (c, i) {
      return c + " " + (hGrenzen[i] / HMAX * 100).toFixed(1) + "% " + (hGrenzen[i + 1] / HMAX * 100).toFixed(1) + "%";
    });
    $("fkLegHoeheBar").style.background = "linear-gradient(90deg," + hStops.join(",") + ")";
    $("fkLegHoeheScale").innerHTML = [["0", 0], ["16", 16], ["54", 54], ["90+", 90]].map(function (m) {
      return '<span style="left:' + (m[1] / HMAX * 100).toFixed(1) + '%">' + m[0] + "</span>";
    }).join("");
    $("fkLegScale").innerHTML = marken.map(function (m) {
      return '<span style="left:' + (m[1] / MAX * 100).toFixed(1) + '%">' + m[0] + "</span>";
    }).join("");
  }

  // Mitte einer Region: Schwerpunkt des größten Umrisses, falls der innerhalb liegt;
  // sonst der innere Punkt mit dem größten Abstand zum Rand (so sitzt die Zahl nie außerhalb).
  function regionMitte(layer) {
    var ring = ringGroessterUmriss(layer.getLatLngs());
    if (!ring || ring.length < 3) return layer.getBounds().getCenter();
    var c = schwerpunkt(ring);
    if (innen(c, ring)) return c;
    var b = layer.getBounds(), besten = null, bestAbst = -1;
    for (var i = 1; i < 25; i++) {
      for (var j = 1; j < 25; j++) {
        var p = L.latLng(b.getSouth() + (b.getNorth() - b.getSouth()) * i / 25,
                         b.getWest() + (b.getEast() - b.getWest()) * j / 25);
        if (!innen(p, ring)) continue;
        var a = abstandRand(p, ring);
        if (a > bestAbst) { bestAbst = a; besten = p; }
      }
    }
    return besten || b.getCenter();
  }

  function ringGroessterUmriss(ll) {
    var besten = null;
    (function sammle(x) {
      if (!x || !x.length) return;
      if (x[0] && x[0].lat !== undefined) {               // Ring aus LatLngs
        if (!besten || x.length > besten.length) besten = x;
      } else {
        x.forEach(sammle);
      }
    })(ll);
    return besten;
  }

  function schwerpunkt(ring) {
    var a = 0, cx = 0, cy = 0;
    for (var i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      var x0 = ring[j].lng, y0 = ring[j].lat, x1 = ring[i].lng, y1 = ring[i].lat;
      var f = x0 * y1 - x1 * y0;
      a += f; cx += (x0 + x1) * f; cy += (y0 + y1) * f;
    }
    if (Math.abs(a) < 1e-12) return L.latLng(ring[0].lat, ring[0].lng);
    return L.latLng(cy / (3 * a), cx / (3 * a));
  }

  function innen(p, ring) {
    var x = p.lng, y = p.lat, drin = false;
    for (var i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      var xi = ring[i].lng, yi = ring[i].lat, xj = ring[j].lng, yj = ring[j].lat;
      if (((yi > y) !== (yj > y)) && (x < (xj - xi) * (y - yi) / (yj - yi) + xi)) drin = !drin;
    }
    return drin;
  }

  function abstandRand(p, ring) {
    var best = Infinity;
    for (var i = 0; i < ring.length; i++) {
      var a = ring[i], b = ring[(i + 1) % ring.length];
      var dx = b.lng - a.lng, dy = b.lat - a.lat;
      var t = dx || dy ? Math.max(0, Math.min(1, ((p.lng - a.lng) * dx + (p.lat - a.lat) * dy) / (dx * dx + dy * dy))) : 0;
      var qx = a.lng + t * dx - p.lng, qy = a.lat + t * dy - p.lat;
      best = Math.min(best, Math.sqrt(qx * qx + qy * qy));
    }
    return best;
  }

  function ladeRegionen() {
    fetch("/api/regionen", { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (geo) {
        if (!geo) return;
        regionGeo = geo.features || (geo.geojson && geo.geojson.features) || [];
        regionLayer.clearLayers();
        L.geoJSON({ type: "FeatureCollection", features: regionGeo }, {
          style: function () { return { stroke: false, fillOpacity: 0 }; },
          onEachFeature: function (f, layer) {
            var id = f.properties.id;
            regionLayers[id] = layer;
            regionCenter[id] = regionMitte(layer);
            layer.bindTooltip(esc(f.properties.name || f.properties.region_name || id));
            layer.on("click", function () { regionWaehlen(id); });
          }
        }).eachLayer(function (l) { regionLayer.addLayer(l); });
        if (aktuell) zeichneRegionen();
      })
      .catch(function () { /* Regionen fehlen nur als Umriss; die Karte bleibt nutzbar */ });
  }

  // Regionen nach Gesamtstärke (0–5), gleiche Skala und Farben wie Täler und Matrix.
  // Gezeigt werden nur die Regionen, die in dieser Stunde von der Föhnrichtung des Tages betroffen
  // sein können: Norden höher als Süden (Druck Lugano − Zürich < 0) = Nordföhn, sonst Südföhn.
  function zeichneRegionen() {
    regionLabelLayer.clearLayers();
    if (!aktuell) return;
    var hh = stunden[stunde];
    var werte = (aktuell.regionen || {})[hh] || {};
    var richtungen = aktuell.richtungen || {};
    var dp = ((aktuell.druck || {})[hh] || {}).dp;
    var seite = dp == null ? null : dp < 0 ? "nord" : "sued";
    var betroffen = [];
    Object.keys(regionLayers).forEach(function (id) {
      var z = werte[id] || { s: 0 };
      var dabei = seite !== null && (richtungen[id] || []).indexOf(seite) >= 0;
      if (dabei) betroffen.push(id);
      if (dabei) {
        regionLayers[id].setStyle({ stroke: false, fill: true, fillColor: FARBE_STAERKE[z.s], fillOpacity: 0.55 });
        regionLayers[id].setTooltipContent(esc(regionName(id)) + " · " + (seite === "nord" ? "Nordföhn" : "Südföhn") +
          " · Stärke " + z.s + " von 5");
      } else {
        regionLayers[id].setStyle({ stroke: true, color: "#cbd5e1", weight: 0.8, opacity: 0.8,
          fill: true, fillColor: "#f8fafc", fillOpacity: 0.2 });
        regionLayers[id].setTooltipContent(esc(regionName(id)));
      }
    });
    if (betroffen.length) {
      var st = 0, lat = 0, lng = 0;
      betroffen.forEach(function (id) {
        st = Math.max(st, (werte[id] || { s: 0 }).s);
        if (regionCenter[id]) { lat += regionCenter[id].lat; lng += regionCenter[id].lng; }
      });
      L.marker([lat / betroffen.length, lng / betroffen.length], {
        interactive: false,
        icon: L.divIcon({ className: "", html: '<div class="fk-block fk-block--' + seite + '">' +
          (seite === "nord" ? "Nordföhn" : "Südföhn") + " · Stärke " + st + " von 5</div>", iconSize: null, iconAnchor: [0, 0] })
      }).addTo(regionLabelLayer);
    }
    if (regionSel) zeichneRegionDetail();
  }

  function regionName(id) {
    var f = (regionGeo || []).filter(function (x) { return x.properties.id === id; })[0];
    return f ? (f.properties.name || f.properties.region_name || id) : id;
  }

  function regionWaehlen(id) {
    regionSel = id;
    $("fkRegionDetail").hidden = false;
    panel(true);
    zeichneRegionDetail();
    $("fkRegionDetail").scrollIntoView({ block: "nearest" });
  }

  function regionZurueck() {
    regionSel = null;
    $("fkRegionDetail").hidden = true;
    $("fkRegionDetail").innerHTML = "";
  }

  function zeichneRegionDetail() {
    var box = $("fkRegionDetail");
    if (!aktuell || !regionSel) { box.innerHTML = ""; return; }
    var hh = stunden[stunde];
    var z = ((aktuell.regionen || {})[hh] || {})[regionSel] || { n: 0 };
    var d = (aktuell.druck || {})[hh] || {};
    var werte = (aktuell.taeler || {})[hh] || {};
    var taeler = (aktuell.talpunkte || []).filter(function (p) { return p.region_id === regionSel; });
    var vorz = function (v, einheit, stellen) { return v == null ? "—" : (v > 0 ? "+" : "") + v.toFixed(stellen) + " " + einheit; };
    var luv = d.sued && d.nord && d.sued.t800 != null && d.nord.t800 != null ? d.sued.t800 - d.nord.t800 : null;
    var zeile = function (ja, text) {
      return '<li class="' + (ja ? "is-on" : "is-off") + '"><span class="fk-jn">' +
        esc(ja ? T.reg_ja : T.reg_nein) + "</span>" + esc(text) + "</li>";
    };
    var hw = ((aktuell.hoehen || {})[hh] || {})[regionSel];
    var hoehenZeile = hw
      ? '<li class="is-info"><span class="fk-jn">700 hPa</span>' + esc(T.reg_hoehe) + ": " + esc(hw.speed) + " km/h · aus " + esc(hw.dir) + "°</li>"
      : "";
    var talZeile = z.tal_messbar === false
      ? '<li class="is-na"><span class="fk-jn">' + esc(T.reg_nicht_pruefbar) + "</span>" + esc(T.reg_keine_messung) + "</li>"
      : zeile(z.tal, T.reg_tal);
    var html = '<p class="fk-zahl-gross"><span class="fk-zahl fk-zahl--' + z.n + '">' + z.n + "</span> " +
      esc(T.reg_von.replace("{m}", z.m || 4)) + " · " + esc(hh) + ":00</p>" +
      '<ul class="fk-zeichen">' +
      zeile(z.dp, T.reg_druck + ": " + vorz(d.dp, "hPa", 1)) +
      zeile(z.wind, T.reg_wind + ": " + (z.anteil != null ? Math.round(z.anteil * 100) + " % " +
        (z.seite === "sued" ? T.reg_seite_sued : T.reg_seite_nord) : "—")) +
      zeile(z.luv, T.reg_luv + ": " + vorz(luv, "°C", 1)) +
      talZeile + hoehenZeile + "</ul>" +
      '<h3 class="fk-gruppe">' + esc(T.reg_taeler) + "</h3><ul class=\"fk-talliste\">" +
      taeler.map(function (p) {
        var t = werte[p.id];
        return '<li class="' + (t && t.dir_dry ? "is-dry" : "") + '"><b>' + esc(p.tal) + "</b> " +
          (t ? esc(t.wind) + " km/h · Böe " + esc(t.gust) + " · " + esc(t.rh) + " %" : "—") + "</li>";
      }).join("") + "</ul>" +
      '<button type="button" class="fk-zurueck" id="fkZurueck">' + esc(T.zurueck) + "</button>";
    box.innerHTML = html;
    $("fkZurueck").addEventListener("click", regionZurueck);
  }

  // Wind am Boden: jeder zweite Rasterpunkt, Pfeil zeigt die Richtung, Farbe die Stärke
  function zeichneBodenwind() {
    pfeilLayer.clearLayers();
    if (!aktuell || !aktuell.grid || !aktuell.grid.winds) return;
    var g = aktuell.grid, w = (g.winds || {})[stunden[stunde]];
    if (!w) return;
    var nx = g.meta.nx;
    g.zellen.forEach(function (z, k) {
      var j = Math.floor(k / nx), i = k % nx;
      if (j % 2 || i % 2) return;
      var u = w.u[k], v = w.v[k];
      if (u == null || v == null) return;
      var kmh = Math.hypot(u, v) * 3.6;
      L.marker([z[0], z[1]], {
        interactive: false,
        icon: L.divIcon({ className: "", html: pfeil(weht_nach(u, v), kmh, farbeWind(kmh)), iconSize: [20, 20], iconAnchor: [10, 10] })
      }).addTo(pfeilLayer);
    });
  }

  // Kammwind: zehn Pässe mit Pfeil und Geschwindigkeit
  // Höhenwind je Region (700 hPa, Vektormittel der Rasterpunkte): Kreis in der Windfarbe,
  // Zahl = km/h, Pfeil als Ring. Gleiche Gestaltung wie bei den Pässen, jetzt pro Region.
  function zeichneHoehen() {
    hoehenLayer.clearLayers();
    if (!aktuell) return;
    var werte = (aktuell.hoehen || {})[stunden[stunde]] || {};
    Object.keys(werte).forEach(function (rid) {
      var c = regionCenter[rid];
      if (!c) return;
      var w = werte[rid];
      var farbe = farbeHoehe(w.speed);
      var ring = '<svg class="fk-kamm-ring" viewBox="0 0 40 40" aria-hidden="true">' +
        '<path d="M20 2 L20 7 M16 5 L20 1 L24 5" fill="none" stroke="' + farbe + '" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" transform="rotate(' + ((w.dir + 180) % 360) + ' 20 20)"/></svg>';
      var html = '<div class="fk-kamm" style="background:' + farbe + '">' + ring +
        '<span class="fk-kamm-wert">' + esc(w.speed) + "</span></div>";
      L.marker(c, {
        interactive: true, zIndexOffset: 1000,
        icon: L.divIcon({ className: "", html: html, iconSize: [40, 40], iconAnchor: [20, 20] })
      }).bindTooltip("<b>" + esc(regionName(rid)) + "</b><br>700 hPa: " + esc(w.speed) + " km/h · aus " + esc(w.dir) + "°")
        .addTo(hoehenLayer);
    });
  }

  function zeichneDruck() {
    druckLayer.clearLayers();
    if (!aktuell) return;
    var d = (aktuell.druck || {})[stunden[stunde]] || {};
    var s = (aktuell.stationen || []);
    var sued = s.filter(function (x) { return x.seite === "sued"; })[0];
    var nord = s.filter(function (x) { return x.seite === "nord"; })[0];
    if (!sued || !nord || d.dp == null) return;
    var von = d.dp >= 0 ? sued : nord, nach = d.dp >= 0 ? nord : sued;
    var txt = (d.dp >= 0 ? (T.druck_sued || "Süden höher um {x} hPa") : (T.druck_nord || "Norden höher um {x} hPa"))
      .replace("{x}", Math.abs(d.dp).toFixed(1));
    L.polyline([[von.lat, von.lon], [nach.lat, nach.lon]], {
      color: "#0f172a", weight: 3, opacity: 0.7, dashArray: "6 6", interactive: false
    }).addTo(druckLayer);
    L.marker([(von.lat + nach.lat) / 2, (von.lon + nach.lon) / 2], {
      interactive: false,
      icon: L.divIcon({ className: "", html: '<div class="fk-druckpfeil-label">' + esc(txt) + "</div>",
        iconSize: null, iconAnchor: [0, 0] })
    }).addTo(druckLayer);
  }

  function zeichneStationen() {
    stationLayer.clearLayers();
    if (!aktuell) return;
    var d = (aktuell.druck || {})[stunden[stunde]] || {};
    (aktuell.stationen || []).forEach(function (st) {
      var w = d[st.seite] || {};
      L.circleMarker([st.lat, st.lon], { radius: 7, color: "#0f172a", weight: 2, fillColor: "#fff", fillOpacity: 1 })
        .bindTooltip("<b>" + esc(st.name) + "</b><br>" + esc(w.druck != null ? w.druck + " hPa" : "—") +
          (w.t800 != null ? " · 2000 m: " + esc(w.t800) + " °C" : ""))
        .addTo(stationLayer);
    });
  }

  // Talpunkte: rot = trockener Föhnwind (wie das Briefing zählt), dunkelrot = stark
  // Föhntäler: Füllfarbe = Windstärke (wie Kammwinde); dunkler Ring = trockener Föhnwind, doppelter Ring = stark
  function zeichneTaeler() {
    talLayer.clearLayers();
    if (!aktuell) return;
    var werte = (aktuell.taeler || {})[stunden[stunde]] || {};
    (aktuell.talpunkte || []).forEach(function (p) {
      var s = werte[p.id];
      var stufe = ((aktuell.talzeichen || {})[stunden[stunde]] || {})[p.id];
      var st = stufe ? stufe.s : 0;
      var wert = s ? Math.round(s.wind) + "" : "";
      // Füllung = Gesamtstärke des Tals (0–6), dieselbe Farbe wie in der Matrix. Die Zahl ist der Talwind.
      var html = '<div class="fk-talpunkt"><span class="fk-talpunkt-dot fk-mz--s' + st + '"></span>' +
        (wert ? '<span class="fk-talpunkt-wert">' + esc(wert) + "</span>" : "") + "</div>";
      L.marker([p.lat, p.lon], {
        icon: L.divIcon({ className: "", html: html, iconSize: [40, 18], iconAnchor: [7, 9] })
      }).bindTooltip("<b>" + esc(p.tal) + "</b><br>" + (s
        ? esc(s.wind) + " km/h · Böe " + esc(s.gust) + " · " + esc(s.rh) + " % · aus " + esc(s.dir) + "°"
        : "keine Daten")).addTo(talLayer);
    });
  }

  // ---------- Verläufe oben ----------

  function serie(f) { return stunden.map(function (h) { return f(h); }); }

  // Verlauf über den Tag: Kurve, Grenze mit Beschriftung, Stunden über der Grenze farbig hinterlegt
  function zeichneVerlauf(svgId, werte, opt) {
    var svg = $(svgId), W = 300, H = 64, P = 4, n = stunden.length;
    var zahlen = werte.filter(function (v) { return v != null; });
    if (!zahlen.length) { svg.innerHTML = ""; return; }
    var lo = Math.min(opt.min, Math.min.apply(null, zahlen)), hi = Math.max(opt.max, Math.max.apply(null, zahlen));
    var x = function (i) { return n > 1 ? i / (n - 1) * W : W / 2; };
    var y = function (v) { return H - P - (v - lo) / (hi - lo) * (H - 2 * P); };
    var breite = n > 1 ? W / (n - 1) : W;
    var s = "";
    // Stunden, in denen die Grenze überschritten ist, hinterlegt
    werte.forEach(function (v, i) {
      if (v != null && opt.ueber && opt.ueber(v)) {
        s += '<rect class="fk-band" x="' + (x(i) - breite / 2).toFixed(1) + '" y="0" width="' + breite.toFixed(1) +
          '" height="' + H + '" fill="' + opt.bandFarbe + '"/>';
      }
    });
    if (lo < 0 && hi > 0) s += '<line class="fk-null" x1="0" x2="' + W + '" y1="' + y(0) + '" y2="' + y(0) + '"/>';
    (opt.schwellen || []).forEach(function (v) {
      if (v > lo && v < hi) s += '<line class="fk-schwelle" x1="0" x2="' + W + '" y1="' + y(v) + '" y2="' + y(v) + '"/>';
    });
    var pfad = "", offen = false;
    werte.forEach(function (v, i) {
      if (v == null) { offen = false; return; }
      pfad += (offen ? " L " : " M ") + x(i).toFixed(1) + " " + y(v).toFixed(1);
      offen = true;
    });
    s += '<path class="fk-linie" d="' + pfad + '" style="stroke:' + opt.farbe + '"/>';
    var cur = werte[stunde];
    s += '<line class="fk-cursor" x1="' + x(stunde) + '" x2="' + x(stunde) + '" y1="0" y2="' + H + '"/>';
    if (cur != null) s += '<circle class="fk-punkt" cx="' + x(stunde) + '" cy="' + y(cur) + '" r="3.5" style="fill:' + opt.farbe + '"/>';
    svg.innerHTML = s;
    $(svgId.replace("fkV", "fkW")).textContent = cur == null ? "—" : opt.wert(cur);
    var note = $(svgId.replace("fkV", "fkN"));
    if (note && opt.grenze) note.textContent = opt.grenze;
  }

  function zeichneVerlaeufe() {
    if (!aktuell) return;
    var druck = aktuell.druck || {}, kamm = aktuell.kamm || {};
    zeichneVerlauf("fkVDruck", serie(function (h) { return druck[h] ? druck[h].dp : null; }), {
      min: -6, max: 6, schwellen: [4, -4], farbe: "#0f172a", bandFarbe: "rgba(234,88,12,0.22)",
      ueber: function (v) { return Math.abs(v) >= 4; },
      grenze: "Grenze ±4 hPa",
      wert: function (v) { return (v > 0 ? "+" : "") + v.toFixed(1) + " hPa"; }
    });
    zeichneVerlauf("fkVKamm", serie(function (h) {
      var l = kamm[h] || [];
      return l.length ? l.reduce(function (a, b) { return a + b.speed; }, 0) / l.length : null;
    }), {
      min: 0, max: 60, schwellen: [30], farbe: "#0ea5e9", bandFarbe: "rgba(234,88,12,0.22)",
      ueber: function (v) { return v >= 30; },
      grenze: "Grenze 30 km/h (Startplätze)",
      wert: function (v) { return Math.round(v) + " km/h"; }
    });
    zeichneVerlauf("fkVLuv", serie(function (h) {
      var d = druck[h];
      return d && d.sued && d.nord && d.sued.t800 != null && d.nord.t800 != null ? d.sued.t800 - d.nord.t800 : null;
    }), {
      min: -3, max: 3, schwellen: [2, -2], farbe: "#7c3aed", bandFarbe: "rgba(234,88,12,0.22)",
      ueber: function (v) { return Math.abs(v) >= 2; },
      grenze: "Grenze ±2 °C",
      wert: function (v) { return (v > 0 ? "+" : "") + v.toFixed(1) + " °C"; }
    });
    zeichneVerlauf("fkVRh", serie(function (h) {
      var d = druck[h];
      return d && d.sued && d.nord && d.sued.rh != null && d.nord.rh != null ? (d.sued.rh + d.nord.rh) / 2 : null;
    }), {
      min: 0, max: 100, schwellen: [68], farbe: "#0891b2", bandFarbe: "rgba(8,145,178,0.20)",
      ueber: function (v) { return v <= 68; },
      grenze: "Grenze 68 %: trockene Luft darunter",
      wert: function (v) { return Math.round(v) + " %"; }
    });
  }

  // Klick auf einen Verlauf setzt die Stunde
  ["fkVDruck", "fkVKamm", "fkVLuv", "fkVRh"].forEach(function (id) {
    $(id).addEventListener("click", function (e) {
      if (!stunden.length) return;
      var r = this.getBoundingClientRect();
      var i = Math.round((e.clientX - r.left) / r.width * (stunden.length - 1));
      setStunde(Math.max(0, Math.min(stunden.length - 1, i)));
    });
  });

  // ---------- Zeit ----------

  // Zeitleiste im Aufbau von /synoptik: Tick je Flugstunde, Linie mit Fortschritt
  function renderStunden() {
    var el = $("fkTimeline");
    var N = stunden.length;
    if (!N) { el.innerHTML = ""; return; }
    var ticks = stunden.map(function (h, i) {
      return '<button type="button" class="syn-tl-tick" data-idx="' + i + '" data-hour="' + h + ':00" aria-label="' + h + ':00">' +
        '<span class="syn-tl-dot" aria-hidden="true"></span><span class="syn-tl-time">' + h + "</span></button>";
    }).join("");
    el.innerHTML = '<div class="syn-tl-track">' +
      '<span class="syn-tl-line" aria-hidden="true"></span>' +
      '<span class="syn-tl-fill" id="fkFill" aria-hidden="true"></span>' + ticks + "</div>";
    var pad = (50 / N) + "%";
    el.querySelector(".syn-tl-line").style.left = pad;
    el.querySelector(".syn-tl-line").style.right = pad;
    var fill = $("fkFill");
    fill.style.left = pad;
    fill.style.width = "0%";
    el.querySelectorAll(".syn-tl-tick").forEach(function (b) {
      b.addEventListener("click", function () {
        stopPlay();
        setStunde(parseInt(b.getAttribute("data-idx"), 10));
      });
    });
  }

  function setStunde(i) {
    if (!stunden.length) return;
    stunde = i;
    var N = stunden.length;
    document.querySelectorAll("#fkTimeline .syn-tl-tick").forEach(function (b, k) {
      b.classList.toggle("is-active", k === i);
      b.classList.toggle("is-past", k < i);
      if (k === i) b.setAttribute("aria-current", "true"); else b.removeAttribute("aria-current");
    });
    var fill = $("fkFill");
    if (fill) fill.style.width = (i * 100 / N) + "%";
    $("fkReadout").textContent = (aktuell ? aktuell.datum.slice(8, 10) + "." + aktuell.datum.slice(5, 7) + ".  " : "") +
      stunden[i] + ":00";
    zeichneBodenwind();
    zeichneHoehen();
    zeichneDruck();
    zeichneRegionen();
    zeichneStationen();
    zeichneTaeler();
    zeichneVerlaeufe();
    renderRegionenMatrix();
  }

  function togglePlay() {
    if (timer) return stopPlay();
    $("fkPlay").classList.add("is-playing");
    $("fkPlay").setAttribute("aria-label", T.pause || "Pause");
    timer = setInterval(function () { setStunde((stunde + 1) % stunden.length); }, TAKT_MS);
  }

  function stopPlay() {
    clearInterval(timer);
    timer = null;
    $("fkPlay").classList.remove("is-playing");
    $("fkPlay").setAttribute("aria-label", T.play || "Abspielen");
  }

  // ---------- Zeichen, Panel, Laden ----------

  function panel(offen) {
    if (!offen && regionSel) regionZurueck();
    root.classList.toggle("panel-open", offen);
    $("fkPanelBtn").setAttribute("aria-expanded", String(offen));
    setTimeout(function () { map.invalidateSize(); }, 250);
  }

  // Föhntäler × Stunden: Gesamtstärke je Tal und Flugstunde (Summe der Stufen, 0–6).
  // Helle Farbe = wenig Hinweise, dunkle = viele und starke. Gewählte Stunde: Spalte getönt.
  function renderRegionenMatrix() {
    var box = $("fkRegionenMatrix");
    if (!aktuell || !aktuell.talpunkte) { box.textContent = ""; return; }
    var tz = aktuell.talzeichen || {}, max = {};
    aktuell.talpunkte.forEach(function (tp) {
      max[tp.id] = 0;
      stunden.forEach(function (hh) {
        var z = (tz[hh] || {})[tp.id];
        if (z) max[tp.id] = Math.max(max[tp.id], z.s);
      });
    });
    var liste = aktuell.talpunkte.slice().sort(function (a, b) {
      return max[b.id] - max[a.id] || String(a.tal).localeCompare(String(b.tal));
    });
    var html = '<table class="fk-tab fk-kopf-tab"><thead><tr><th></th>' +
      stunden.map(function (h, i) {
        return '<th class="fk-hh' + (i === stunde ? " is-now" : "") + '" scope="col">' + h + "</th>";
      }).join("") + "</tr></thead><tbody>";
    liste.forEach(function (tp) {
      html += '<tr><th scope="row"><button type="button" class="fk-zeilen-knopf" data-region="' + esc(tp.region_id || "") + '">' +
        esc(tp.tal) + "</button></th>";
      stunden.forEach(function (hh, i) {
        var z = (tz[hh] || {})[tp.id] || { s: 0 };
        html += '<td class="fk-mz fk-mz--s' + z.s + (i === stunde ? " is-now" : "") + '" data-hh="' + i +
          '" title="' + esc(tp.tal) + " " + hh + ":00 – Stärke " + z.s + " von 5" + '"></td>';
      });
      html += "</tr>";
    });
    box.innerHTML = html + "</tbody></table>";
    box.querySelectorAll(".fk-zeilen-knopf").forEach(function (b) {
      var rid = b.getAttribute("data-region");
      if (rid) b.addEventListener("click", function () { regionWaehlen(rid); });
    });
    box.querySelectorAll(".fk-mz").forEach(function (td) {
      td.addEventListener("click", function () { setStunde(parseInt(td.getAttribute("data-hh"), 10)); });
    });
  }
  function schalterFuer(aktiv) {
    $("fkEbWind").disabled = !aktiv.wind;
    $("fkEbKamm").disabled = !aktiv.kamm;
    if (!aktiv.wind) $("fkEbWind").checked = false;
    if (!aktiv.kamm) $("fkEbKamm").checked = false;
  }

  function zeigeHinweis(text) {
    var n = $("fkNotice");
    n.textContent = text || "";
    n.hidden = !text;
  }

  function lade(tagIndex) {
    var url = API + (tagIndex ? "?tag=" + tagIndex : "");
    fetch(url, { credentials: "same-origin" })
      .then(function (r) {
        return r.json().then(function (body) {
          if (!r.ok) throw new Error(body.error || r.status);
          return body;
        });
      })
      .then(function (data) {
        aktuell = data;
        stunden = data.stunden || [];
        if (data.erzeugt && $("fkStand")) $("fkStand").textContent = (T.stand || "Stand") + ": " + data.erzeugt.replace("T", " ").slice(0, 16);
        zeigeHinweis("");
        schalterFuer({ wind: !!(data.grid && data.grid.winds && Object.keys(data.grid.winds).length),
                       kamm: !!(data.kamm_punkte && data.kamm_punkte.length) });
        renderStunden();
        setStunde(Math.min(stunde, Math.max(stunden.length - 1, 0)));
        $("fkPlay").disabled = false;
      })
      .catch(function (err) {
        aktuell = null;
        zeigeHinweis((T.nicht_da || "Föhnkarte nicht verfügbar") + ": " + err.message);
        [pfeilLayer, hoehenLayer, talLayer, stationLayer, druckLayer].forEach(function (l) { l.clearLayers(); });
        $("fkPlay").disabled = true;
      });
  }

  window.addEventListener("wingcast-day-change", function (ev) {
    var tasten = Array.prototype.slice.call(document.querySelectorAll("#navDayTabs .navbar-day-btn"));
    var index = tasten.findIndex(function (b) { return b.dataset.date === ev.detail.date; });
    stopPlay();
    lade(index > 0 ? index : 0);
  });

  initMap();
  fuelleLegende();
  ladeRegionen();
  panel(window.matchMedia("(min-width: 640px)").matches);   // Übersicht sichtbar; auf dem Handy schließen
  lade(0);
})();
