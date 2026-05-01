/* ══════════════════════════════════════════════════════════════
   Gleitcast — Shared Glyph Renderer (RATING_CONCEPT v1.3 §8.2)
   Single source of truth for the safety_band × experience_stars
   marker glyph used on map, briefing, region header, spot panel.
   Exposes window.gleitcastGlyph.
   ══════════════════════════════════════════════════════════════ */
(function () {
  "use strict";

  function styleFor(band) {
    if (band === "green")   return { fill: "#22c55e", stroke: "#15803d", label: "Sicher" };
    if (band === "amber")   return { fill: "#f59e0b", stroke: "#92400e", label: "Vorsicht" };
    if (band === "red")     return { fill: "#ef4444", stroke: "#991b1b", label: "Nicht fliegbar" };
    if (band === "no_data") return { fill: "#9ca3af", stroke: "#6b7280", label: "Keine Daten" };
    return { fill: "#6b7280", stroke: "#4b5563", label: "" };
  }

  // Legacy-Fallback fuer Spots ohne safety_band-Feld (alte Caches).
  function legacyBand(spot) {
    if (!spot) return "no_data";
    if (spot.safety_band === "green" || spot.safety_band === "amber"
        || spot.safety_band === "red" || spot.safety_band === "no_data") {
      return spot.safety_band;
    }
    var s = spot.safety_status;
    if (s === "not_safe")    return "red";
    if (s === "conditional") return "amber";
    if (s === "safe")        return "green";
    if (s === "no_data" || s === "error") return "no_data";
    return "no_data";
  }

  function legacyStars(spot) {
    if (!spot) return 0;
    if (typeof spot.experience_stars === "number") {
      var s = Math.floor(spot.experience_stars);
      return s < 0 ? 0 : (s > 5 ? 5 : s);
    }
    var r = parseFloat(spot.rating);
    if (!isFinite(r) || r <= 0) return 0;
    if (r >= 9.0) return 5;
    if (r >= 7.6) return 4;
    if (r >= 6.1) return 3;
    if (r >= 4.1) return 2;
    if (r >= 2.1) return 1;
    return 0;
  }

  function experienceScore(spot) {
    if (!spot) return 0;
    if (typeof spot.experience_score === "number") {
      var v = spot.experience_score;
      return v < 0 ? 0 : (v > 100 ? 100 : v);
    }
    var r = parseFloat(spot.rating);
    if (!isFinite(r) || r < 0) return 0;
    return Math.max(0, Math.min(100, Math.round(r * 10)));
  }

  // SVG-String Generator (no Leaflet dep). Inline-bar in HTML.
  // opts = { band, stars, size = 24, ariaLabel? }
  function svg(opts) {
    var band = (opts && opts.band) || "no_data";
    var stars = (opts && typeof opts.stars === "number") ? Math.max(0, Math.min(5, Math.floor(opts.stars))) : 0;
    var size = (opts && opts.size) || 24;
    var st = styleFor(band);
    var center = size / 2;
    // Radius proportional zum Marker-Radius im map.js (8px @ 44 svg = 0.18).
    // Fuer 24px Glyphe ergibt 0.42 → 10px Radius — kompakt aber lesbar.
    var radius = Math.max(6, Math.round(size * 0.42));
    var ariaLabel = (opts && opts.ariaLabel) || (st.label + (band !== "red" && stars > 0 ? ", " + stars + " Sterne" : ""));

    var s = '<svg width="' + size + '" height="' + size + '" viewBox="0 0 ' + size + ' ' + size
          + '" class="gc-glyph gc-glyph--' + band + '" role="img" aria-label="' + ariaLabel + '">';
    s += '<circle cx="' + center + '" cy="' + center + '" r="' + radius
       + '" fill="' + st.fill + '" stroke="' + st.stroke + '" stroke-width="1.5" />';

    if (band === "red") {
      var arm = radius * 0.55;
      var w = Math.max(2, radius * 0.22);
      s += '<line x1="' + (center - arm) + '" y1="' + (center - arm)
         + '" x2="' + (center + arm) + '" y2="' + (center + arm)
         + '" stroke="#ffffff" stroke-width="' + w + '" stroke-linecap="round" />';
      s += '<line x1="' + (center + arm) + '" y1="' + (center - arm)
         + '" x2="' + (center - arm) + '" y2="' + (center + arm)
         + '" stroke="#ffffff" stroke-width="' + w + '" stroke-linecap="round" />';
    } else if (stars >= 1 && (band === "green" || band === "amber")) {
      var fontSize = Math.round(radius * 1.4);
      s += '<text x="' + center + '" y="' + (center + fontSize * 0.35)
         + '" text-anchor="middle" fill="#ffffff" font-family="Inter, sans-serif"'
         + ' font-size="' + fontSize + '" font-weight="800">' + stars + '</text>';
    } else if (band === "green" || band === "amber") {
      s += '<circle cx="' + center + '" cy="' + center + '" r="' + Math.max(1.5, radius * 0.18) + '" fill="#ffffff" />';
    }

    s += "</svg>";
    return s;
  }

  // Worst-Band-Wins (RATING_CONCEPT §3.1): rot > amber > grün > no_data
  var BAND_ORDER = { red: 3, amber: 2, green: 1, no_data: 0 };
  function aggregateBand(spots) {
    var worst = "no_data";
    for (var i = 0; i < (spots || []).length; i++) {
      var b = legacyBand(spots[i]);
      if ((BAND_ORDER[b] || 0) > (BAND_ORDER[worst] || 0)) worst = b;
    }
    return worst;
  }

  // Verteilungs-Counts pro Band fuer Region/Day-Header.
  function bandCounts(spots) {
    var c = { green: 0, amber: 0, red: 0, no_data: 0 };
    for (var i = 0; i < (spots || []).length; i++) {
      var b = legacyBand(spots[i]);
      c[b] = (c[b] || 0) + 1;
    }
    return c;
  }

  function avgStars(spots) {
    if (!spots || !spots.length) return 0;
    var sum = 0, n = 0;
    for (var i = 0; i < spots.length; i++) {
      sum += legacyStars(spots[i]);
      n++;
    }
    return n ? Math.round(sum / n) : 0;
  }

  window.gleitcastGlyph = {
    styleFor: styleFor,
    legacyBand: legacyBand,
    legacyStars: legacyStars,
    experienceScore: experienceScore,
    svg: svg,
    aggregateBand: aggregateBand,
    bandCounts: bandCounts,
    avgStars: avgStars,
    BAND_ORDER: BAND_ORDER,
  };
})();
