/* ══════════════════════════════════════════════════════════════
   Gleitcast — Shared Glyph Renderer (RATING_ARCHITECTURE v2.1)
   FE leitet Farben aus safety_status + experience_rating ab.
   Skala 1-5 (1=abgleiter, 2=kurzer, 3=solider, 4=starker, 5=xc_tag/klassiker).
   Exposes window.gleitcastGlyph.
   ══════════════════════════════════════════════════════════════ */
(function () {
  "use strict";

  // safety_status → Marker-Farbband (green/amber/red/no_data).
  function bandFromStatus(status) {
    if (status === "safe") return "green";
    if (status === "conditional") return "amber";
    if (status === "not_safe") return "red";
    return "no_data";
  }

  // experience_rating (1-5) → Tier (gray/green/violet) fuer Premium-Optik.
  // 1-2 → gray, 3-4 → green, 5 → violet.
  function tierFromRating(rating) {
    var r = parseInt(rating, 10);
    if (!isFinite(r) || r <= 0) return "gray";
    if (r >= 5) return "violet";
    if (r >= 3) return "green";
    return "gray";
  }

  function styleFor(band) {
    if (band === "violet")  return { fill: "#8b5cf6", stroke: "#6d28d9", label: "Top" };
    if (band === "green")   return { fill: "#22c55e", stroke: "#15803d", label: "Sicher" };
    if (band === "amber")   return { fill: "#f59e0b", stroke: "#92400e", label: "Vorsicht" };
    if (band === "red")     return { fill: "#ef4444", stroke: "#991b1b", label: "Nicht fliegbar" };
    if (band === "no_data") return { fill: "#9ca3af", stroke: "#6b7280", label: "Keine Daten" };
    return { fill: "#6b7280", stroke: "#4b5563", label: "" };
  }

  // Display-Band: safe + rating 5 (xc_tag/Klassiker) → violett-Premium-Marker.
  function displayBand(band, rating) {
    if (band === "green" && typeof rating === "number" && rating >= 5) return "violet";
    return band;
  }

  // Spot/Region → Band aus safety_status (FE-Mapping, kein safety_band-Feld mehr).
  function legacyBand(spot) {
    if (!spot) return "no_data";
    return bandFromStatus(spot.safety_status);
  }

  // experience_rating 1-5. Bei not_safe oder fehlend → 0.
  function legacyRating(spot) {
    if (!spot) return 0;
    var r = parseInt(spot.experience_rating, 10);
    if (!isFinite(r) || r <= 0) return 0;
    // Migration-Tolerance: alte Cache-Werte 6 → 5 mappen
    if (r === 6) return 5;
    return Math.max(1, Math.min(5, r));
  }

  // Stars 0-5 (Briefing-Bubble Layout). Aus rating 1-5 abgeleitet — 1:1.
  function legacyStars(spot) {
    var r = legacyRating(spot);
    if (r <= 0) return 0;
    return r;
  }

  // SVG-String Generator (no Leaflet dep).
  // opts = { band, rating, size = 24, ariaLabel? }
  function svg(opts) {
    var band = (opts && opts.band) || "no_data";
    var rating = 0;
    if (opts && typeof opts.rating === "number") {
      var rRaw = Math.max(0, Math.min(6, Math.floor(opts.rating)));
      // Migration-Tolerance: 6 → 5
      rating = rRaw === 6 ? 5 : Math.min(5, rRaw);
    }
    var size = (opts && opts.size) || 24;
    var visBand = displayBand(band, rating);
    var st = styleFor(visBand);
    var center = size / 2;
    var radius = Math.max(7, Math.round(size * 0.46));
    var ratingLabel = (rating > 0 && band !== "red") ? (", Rating " + rating + "/5") : "";
    var ariaLabel = (opts && opts.ariaLabel) || (st.label + ratingLabel);

    // Farbintensitaet skaliert mit Rating 1-5.
    var fillOpacity = 1.0;
    if (visBand === "green" || visBand === "amber" || visBand === "violet") {
      fillOpacity = rating > 0 ? (0.30 + (rating / 5) * 0.70) : 0.30;
    }
    var fillScales = (visBand === "green" || visBand === "amber" || visBand === "violet");

    var s = '<svg width="' + size + '" height="' + size + '" viewBox="0 0 ' + size + ' ' + size
          + '" class="gc-glyph gc-glyph--' + visBand + '" role="img" aria-label="' + ariaLabel + '">';
    if (fillScales) {
      s += '<circle cx="' + center + '" cy="' + center + '" r="' + radius + '" fill="#ffffff" />';
    }
    s += '<circle cx="' + center + '" cy="' + center + '" r="' + radius
       + '" fill="' + st.fill + '" fill-opacity="' + fillOpacity.toFixed(2) + '"'
       + ' stroke="' + st.stroke + '" stroke-width="1.5" />';

    if (band === "red") {
      var arm = radius * 0.55;
      var w = Math.max(2, radius * 0.22);
      s += '<line x1="' + (center - arm) + '" y1="' + (center - arm)
         + '" x2="' + (center + arm) + '" y2="' + (center + arm)
         + '" stroke="#ffffff" stroke-width="' + w + '" stroke-linecap="round" />';
      s += '<line x1="' + (center + arm) + '" y1="' + (center - arm)
         + '" x2="' + (center - arm) + '" y2="' + (center + arm)
         + '" stroke="#ffffff" stroke-width="' + w + '" stroke-linecap="round" />';
    } else if (rating >= 1 && (visBand === "green" || visBand === "amber" || visBand === "violet")) {
      var fontSize = Math.round(radius * 1.4);
      var yOffset = fontSize * 0.35;
      var textFill = (fillOpacity < 0.65) ? st.stroke : "#ffffff";
      s += '<text x="' + center + '" y="' + (center + yOffset)
         + '" text-anchor="middle" fill="' + textFill + '" font-family="Inter, sans-serif"'
         + ' font-size="' + fontSize + '" font-weight="800">' + rating + '</text>';
    } else if (visBand === "green" || visBand === "amber" || visBand === "violet") {
      s += '<circle cx="' + center + '" cy="' + center + '" r="' + Math.max(1.5, radius * 0.18) + '" fill="#ffffff" />';
    }

    s += "</svg>";
    return s;
  }

  // Worst-Band-Wins: rot > amber > gruen > no_data
  var BAND_ORDER = { red: 3, amber: 2, green: 1, no_data: 0 };
  function aggregateBand(spots) {
    var worst = "no_data";
    for (var i = 0; i < (spots || []).length; i++) {
      var b = legacyBand(spots[i]);
      if ((BAND_ORDER[b] || 0) > (BAND_ORDER[worst] || 0)) worst = b;
    }
    return worst;
  }

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

  function avgRating(spots) {
    if (!spots || !spots.length) return 0;
    var sum = 0, n = 0;
    for (var i = 0; i < spots.length; i++) {
      var r = legacyRating(spots[i]);
      if (r > 0) { sum += r; n++; }
    }
    return n ? Math.round(sum / n) : 0;
  }

  window.gleitcastGlyph = {
    bandFromStatus: bandFromStatus,
    tierFromRating: tierFromRating,
    styleFor: styleFor,
    displayBand: displayBand,
    legacyBand: legacyBand,
    legacyStars: legacyStars,
    legacyRating: legacyRating,
    svg: svg,
    aggregateBand: aggregateBand,
    bandCounts: bandCounts,
    avgStars: avgStars,
    avgRating: avgRating,
    BAND_ORDER: BAND_ORDER,
  };
})();
