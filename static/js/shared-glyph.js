/* ══════════════════════════════════════════════════════════════
   Gleitcast — Shared Glyph Renderer (RATING_CONCEPT v1.4 §8.2)
   Single source of truth for the safety_band × experience_rating
   marker glyph used on map, briefing, region header, spot panel.
   Skala 1-10 (0 = not_safe / no flight).
   Exposes window.gleitcastGlyph.
   ══════════════════════════════════════════════════════════════ */
(function () {
  "use strict";

  function styleFor(band) {
    if (band === "violet")  return { fill: "#8b5cf6", stroke: "#6d28d9", label: "Top" };
    if (band === "green")   return { fill: "#22c55e", stroke: "#15803d", label: "Sicher" };
    if (band === "amber")   return { fill: "#f59e0b", stroke: "#92400e", label: "Vorsicht" };
    if (band === "red")     return { fill: "#ef4444", stroke: "#991b1b", label: "Nicht fliegbar" };
    if (band === "no_data") return { fill: "#9ca3af", stroke: "#6b7280", label: "Keine Daten" };
    return { fill: "#6b7280", stroke: "#4b5563", label: "" };
  }

  // Display-Band: safe + rating>=8 wird visuell als violett dargestellt.
  // Safety-Filter und Filter-Logik bleiben aber bei "green" — violett ist
  // nur ein optischer Premium-Marker fuer top-bewertete sichere Spots/Regionen.
  function displayBand(band, rating) {
    if (band === "green" && typeof rating === "number" && rating >= 8) return "violet";
    return band;
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

  // Rating 1-10. Bevorzugt experience_rating, fallback auf score/10 oder rating.
  function legacyRating(spot) {
    if (!spot) return 0;
    if (typeof spot.experience_rating === "number") {
      var r = Math.floor(spot.experience_rating);
      return r < 0 ? 0 : (r > 10 ? 10 : r);
    }
    // Fallback: experience_score (0-100) / 10, conservative ceil.
    if (typeof spot.experience_score === "number") {
      var s = spot.experience_score;
      if (s <= 0) return 0;
      if (s >= 100) return 10;
      return Math.max(1, Math.min(10, Math.ceil(s / 10)));
    }
    // Legacy-Legacy: rating 0-10 direkt.
    var rt = parseFloat(spot.rating);
    if (!isFinite(rt) || rt <= 0) return 0;
    return Math.max(1, Math.min(10, Math.round(rt)));
  }

  // Backwards-compat fuer Code, der noch auf 0-5 Sterne basiert
  // (z.B. Briefing-Bubble-Layout). Buckets aus alter v1.3-Tabelle.
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
  // opts = { band, rating, size = 24, ariaLabel? }
  // Rating 1-10. 0 wird wie no-flight behandelt (Punkt statt Zahl).
  // Backwards-Compat: opts.stars (0-5) wird auf rating (stars*2) gemappt.
  function svg(opts) {
    var band = (opts && opts.band) || "no_data";
    var rating = 0;
    if (opts && typeof opts.rating === "number") {
      rating = Math.max(0, Math.min(10, Math.floor(opts.rating)));
    } else if (opts && typeof opts.stars === "number") {
      rating = Math.max(0, Math.min(10, Math.floor(opts.stars) * 2));
    }
    var size = (opts && opts.size) || 24;
    var visBand = displayBand(band, rating);
    var st = styleFor(visBand);
    var center = size / 2;
    // Marker leicht groesser als v1.3 (0.42 → 0.46), damit zweistellige
    // Zahl gut lesbar ist.
    var radius = Math.max(7, Math.round(size * 0.46));
    var ratingLabel = (rating > 0 && band !== "red") ? (", Rating " + rating + "/10") : "";
    var ariaLabel = (opts && opts.ariaLabel) || (st.label + ratingLabel);

    // Farbintensitaet skaliert linear mit Rating — moderater Dynamikbereich.
    // Rating 1 ~0.28, Rating 5 ~0.60, Rating 10 = 1.0. Sichtbar abgestuft, aber
    // nicht so extrem dass schwache Spots fast verschwinden.
    var fillOpacity = 1.0;
    if (visBand === "green" || visBand === "amber" || visBand === "violet") {
      fillOpacity = rating > 0 ? (0.20 + (rating / 10) * 0.80) : 0.20;
    }
    var fillScales = (visBand === "green" || visBand === "amber" || visBand === "violet");

    var s = '<svg width="' + size + '" height="' + size + '" viewBox="0 0 ' + size + ' ' + size
          + '" class="gc-glyph gc-glyph--' + visBand + '" role="img" aria-label="' + ariaLabel + '">';
    // Weisser Hintergrund-Kreis bei skalierter Deckkraft, damit die Farbe sauber
    // wirkt und die Ziffer auch ueber farbigen Karten lesbar bleibt.
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
      // Zahl 1-10. Zweistellig "10" braucht kleinere Schrift damit's reinpasst.
      var twoDigit = rating >= 10;
      var fontSize = Math.round(radius * (twoDigit ? 1.05 : 1.4));
      var yOffset = fontSize * 0.35;
      // Bei geringer Deckkraft (kleines Rating) ist weisse Schrift unlesbar —
      // dann auf den dunklen Stroke-Ton wechseln (parallel zu map.js).
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

  // v1.4: Durchschnitts-Rating 1-10 fuer Region-Header.
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
    styleFor: styleFor,
    displayBand: displayBand,
    legacyBand: legacyBand,
    legacyStars: legacyStars,
    legacyRating: legacyRating,
    experienceScore: experienceScore,
    svg: svg,
    aggregateBand: aggregateBand,
    bandCounts: bandCounts,
    avgStars: avgStars,
    avgRating: avgRating,
    BAND_ORDER: BAND_ORDER,
  };
})();
