/* ══════════════════════════════════════════════════════════════
   Wingcast – Flugwetter Dashboard
   Tab-based day selector, region filter chips, compact spot rows.
   ══════════════════════════════════════════════════════════════ */

(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);

  // ── Utilities ───────────────────────────────────────────────

  function escapeHtml(str) {
    if (str === null || str === undefined) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function formatDateDE(dateStr) {
    try {
      const d = new Date(dateStr + "T12:00:00");
      const months = [wcT("month.1"),wcT("month.2"),wcT("month.3"),wcT("month.4"),wcT("month.5"),wcT("month.6"),wcT("month.7"),wcT("month.8"),wcT("month.9"),wcT("month.10"),wcT("month.11"),wcT("month.12")];
      return `${d.getDate()}. ${months[d.getMonth()]}`;
    } catch (e) { return dateStr; }
  }

  function formatDateShort(dateStr) {
    try {
      const d = new Date(dateStr + "T12:00:00");
      return `${d.getDate()}.${d.getMonth() + 1}.`;
    } catch (e) { return dateStr; }
  }

  function formatRating(r) {
    const n = Number(r);
    if (!isFinite(n) || n <= 0) return "—";
    return n.toFixed(1);
  }

  function formatGeneratedAt(ts) {
    if (!ts) return "";
    try {
      const d = new Date(ts);
      const dd = String(d.getDate()).padStart(2, "0");
      const mm = String(d.getMonth() + 1).padStart(2, "0");
      const hh = String(d.getHours()).padStart(2, "0");
      const mi = String(d.getMinutes()).padStart(2, "0");
      return `Stand ${dd}.${mm}. ${hh}:${mi}`;
    } catch (e) { return ""; }
  }

  // ── State ───────────────────────────────────────────────────

  const LS_REGION_FILTER_KEY = "wingcast.briefing.regionFilter";
  const LS_DAY_IDX_KEY = "wingcast.briefing.dayIdx";
  const LS_TIER_FILTER_KEY = "wingcast.briefing.tierFilter";       // legacy key (read-only fallback)
  const LS_SAFETY_FILTER_KEY = "wingcast.briefing.safetyFilter";   // v1.3
  const LS_MIN_STARS_KEY = "wingcast.briefing.minStars";           // legacy key (read-only fallback, v1.3 stars)
  const LS_MIN_RATING_KEY = "wingcast.briefing.minRating6";        // v2.0 rating 0-6 (experience_rating)
  const LS_MIN_RATING_KEY_LEGACY = "wingcast.briefing.minRating10"; // v1.4 legacy key (0-10), gets migrated
  const LS_COLLAPSED_REGIONS_KEY = "wingcast.briefing.collapsedRegions";
  const LS_EXPAND_HINT_SEEN_KEY = "wingcast.briefing.expandHintSeen";
  const LS_SHOW_NUMBERS_KEY = "wingcast.meteogram.showNumbers";

  // Safety-Baender (RATING_ARCHITECTURE v2.1): genau 3 Filter-Kategorien aus
  // safety_status (safe/conditional/not_safe). "violet" (Top) ist nur ein
  // Marker-Effekt fuer xc_tag/Klassiker (rating=5) auf 'green'-Spots — KEIN Filter.
  const SAFETY_DEFS = [
    { id: "green",  label: wcT("js.safety.safe"),        short: wcT("js.safety.safe") },
    { id: "amber",  label: wcT("js.safety.caution"),      short: wcT("js.safety.caution") },
    { id: "red",    label: wcT("js.safety.not_flyable"), short: wcT("js.safety.not_flyable") },
  ];
  const DEFAULT_SAFETY = ["green", "amber"];

  let state = {
    data: null,
    generating: false,
    filterRegions: loadRegionFilter(),
    selectedDayIdx: loadDayIdx(),
    safetyFilters: loadSafetyFilter(),
    minRating: loadMinRating(),
    wetterlageOpen: false,
    mapVisible: false,
    collapsedRegions: loadCollapsedRegions(),
    expandHintSeen: loadExpandHintSeen(),
    showNumbers: loadShowNumbers(),
    // focusSpot: ephemer via URL-Param gesetzt, zeigt nur diesen einen Spot.
    // Nicht persistiert — wird beim Reload geleert wenn URL-Param weg ist.
    focusSpot: null,
  };

  function loadRegionFilter() {
    try {
      const raw = localStorage.getItem(LS_REGION_FILTER_KEY);
      if (!raw) return new Set();
      const arr = JSON.parse(raw);
      return new Set(Array.isArray(arr) ? arr : []);
    } catch (e) { return new Set(); }
  }

  function saveRegionFilter(set) {
    try { localStorage.setItem(LS_REGION_FILTER_KEY, JSON.stringify(Array.from(set))); } catch (e) {}
  }

  function loadDayIdx() {
    try { return parseInt(localStorage.getItem(LS_DAY_IDX_KEY), 10) || 0; } catch (e) { return 0; }
  }

  function saveDayIdx(idx) {
    try { localStorage.setItem(LS_DAY_IDX_KEY, String(idx)); } catch (e) {}
  }

  function loadSafetyFilter() {
    try {
      const raw = localStorage.getItem(LS_SAFETY_FILTER_KEY);
      if (raw === null) return new Set(DEFAULT_SAFETY);
      const arr = JSON.parse(raw);
      if (!Array.isArray(arr)) return new Set(DEFAULT_SAFETY);
      const set = new Set(arr.filter((t) => SAFETY_DEFS.some((d) => d.id === t)));
      // Migration v2.0: alter "violet"-Filter wird ignoriert (existiert nicht mehr).
      // Falls "green" gespeichert ist, ist alles ok — Top-Spots zaehlen jetzt als "Sicher".
      return set;
    } catch (e) { return new Set(DEFAULT_SAFETY); }
  }

  function saveSafetyFilter(set) {
    try { localStorage.setItem(LS_SAFETY_FILTER_KEY, JSON.stringify(Array.from(set))); } catch (e) {}
  }

  function loadMinRating() {
    try {
      const raw = localStorage.getItem(LS_MIN_RATING_KEY);
      if (raw !== null) {
        const v = parseInt(raw, 10);
        if (!isFinite(v) || v < 0) return 0;
        // v2.1: Skala 0-5. Alte persistierte Werte 6 (waren Klassiker) auf 5 mappen.
        return Math.min(5, v);
      }
      // Migration v1.4 0-10 → v2.1 0-5: alten Wert auf neue Skala mappen.
      const legacy10 = localStorage.getItem(LS_MIN_RATING_KEY_LEGACY);
      if (legacy10 !== null) {
        const v10 = parseInt(legacy10, 10);
        if (isFinite(v10) && v10 > 0) {
          return Math.min(5, Math.max(0, Math.round((v10 / 10) * 5)));
        }
      }
      // Migration v1.3 stars (0-5) → v2.1 rating (0-5): direkte 1:1.
      const legacyStars = localStorage.getItem(LS_MIN_STARS_KEY);
      if (legacyStars !== null) {
        const sv = parseInt(legacyStars, 10);
        if (isFinite(sv) && sv > 0 && sv <= 5) return sv;
      }
      return 0;
    } catch (e) { return 0; }
  }

  function saveMinRating(v) {
    try { localStorage.setItem(LS_MIN_RATING_KEY, String(v)); } catch (e) {}
  }

  function loadCollapsedRegions() {
    try {
      const raw = localStorage.getItem(LS_COLLAPSED_REGIONS_KEY);
      if (!raw) return new Set();
      const arr = JSON.parse(raw);
      return new Set(Array.isArray(arr) ? arr : []);
    } catch (e) { return new Set(); }
  }

  function saveCollapsedRegions(set) {
    try { localStorage.setItem(LS_COLLAPSED_REGIONS_KEY, JSON.stringify(Array.from(set))); } catch (e) {}
  }

  function loadExpandHintSeen() {
    try { return localStorage.getItem(LS_EXPAND_HINT_SEEN_KEY) === "1"; } catch (e) { return false; }
  }

  function markExpandHintSeen() {
    if (state.expandHintSeen) return;
    state.expandHintSeen = true;
    try { localStorage.setItem(LS_EXPAND_HINT_SEEN_KEY, "1"); } catch (e) {}
    document.body.classList.add("bf-hint-seen");
  }

  function loadShowNumbers() {
    try { return localStorage.getItem(LS_SHOW_NUMBERS_KEY) === "1"; } catch (e) { return false; }
  }

  function saveShowNumbers(on) {
    try { localStorage.setItem(LS_SHOW_NUMBERS_KEY, on ? "1" : "0"); } catch (e) {}
  }

  function regionPassesFilter(regionId) {
    if (!state.filterRegions || state.filterRegions.size === 0) return true;
    return state.filterRegions.has(regionId || "unknown");
  }

  // RATING_CONCEPT v1.3: zwei orthogonale Achsen.
  // RATING_ARCHITECTURE v2.0: Safety-Band aus safety_status, Rating aus experience_rating 1-6.
  function spotSafetyBand(spot) {
    return (window.wingcastGlyph && window.wingcastGlyph.legacyBand)
      ? window.wingcastGlyph.legacyBand(spot)
      : "no_data";
  }

  function spotStars(spot) {
    return (window.wingcastGlyph && window.wingcastGlyph.legacyStars)
      ? window.wingcastGlyph.legacyStars(spot)
      : 0;
  }

  function spotRating(spot) {
    return (window.wingcastGlyph && window.wingcastGlyph.legacyRating)
      ? window.wingcastGlyph.legacyRating(spot)
      : (typeof spot.experience_rating === "number" ? Math.floor(spot.experience_rating) : 0);
  }

  function spotPassesSafetyFilter(spot) {
    const bands = state.safetyFilters;
    if (!bands || bands.size === 0) return false;
    const baseBand = spotSafetyBand(spot);
    if (baseBand === "no_data") {
      return bands.has("green") || bands.has("amber") || bands.has("red");
    }
    // RATING_ARCHITECTURE v2.0: Filter genau auf safety_status (green/amber/red).
    // Marker-Display kann weiterhin "violet" sein (Klassiker), das ist nur Optik.
    return bands.has(baseBand);
  }

  function spotPassesRatingFilter(spot) {
    const min = state.minRating || 0;
    if (min <= 0) return true;
    return spotRating(spot) >= min;
  }

  function collectAllRegions(data) {
    const map = new Map();
    for (const r of (data.regions || [])) {
      if (!r || !r.region_id) continue;
      map.set(r.region_id, { id: r.region_id, name: r.region_name || r.region_id });
    }
    for (const d of (data.days || [])) {
      for (const s of (d.top_spots || [])) {
        const rid = s.region_id || "unknown";
        if (!map.has(rid)) {
          map.set(rid, { id: rid, name: s.region_name || (rid === "unknown" ? "Weitere" : rid) });
        }
      }
    }
    if (_filterMap && _filterMap.pathById) {
      _filterMap.pathById.forEach((lyr, id) => {
        if (map.has(id)) return;
        let name = id;
        try {
          const p = lyr && lyr.feature && lyr.feature.properties;
          if (p) name = p.region || p.name || id;
        } catch (_) {}
        map.set(id, { id, name });
      });
    }
    return Array.from(map.values()).sort((a, b) => {
      if (a.id === "unknown") return 1;
      if (b.id === "unknown") return -1;
      return (a.name || "").localeCompare(b.name || "", "de");
    });
  }

  // ── Data helpers ────────────────────────────────────────────

  function getSelectedDay() {
    if (!state.data || !state.data.days || !state.data.days.length) return null;
    const idx = Math.min(state.selectedDayIdx, state.data.days.length - 1);
    return state.data.days[Math.max(0, idx)];
  }

  function computeDayCounts(day) {
    const base = day.counts || {};
    if (!state.filterRegions || state.filterRegions.size === 0) {
      return {
        spots_flyable: base.spots_flyable || 0,
        spots_bronze: base.spots_bronze || 0,
        spots_nogo: base.spots_nogo || 0,
        spots_conditional: base.spots_conditional || 0,
      };
    }
    const cbr = day.counts_by_region || {};
    let fly = 0, br = 0, ng = 0, co = 0;
    for (const rid of state.filterRegions) {
      const c = cbr[rid];
      if (!c) continue;
      fly += c.flyable || 0;
      br  += c.bronze  || 0;
      ng  += c.nogo    || 0;
      co  += c.conditional || 0;
    }
    return { spots_flyable: fly, spots_bronze: br, spots_nogo: ng, spots_conditional: co };
  }

  // ── Risk-Reward-Matrix (echtes 2-Achsen-Scatter, Spot-Ebene) ──
  // X = Experience-Score (0..100, Reward)
  // Y = Safety-Score (0..100, höher = sicherer) — invertiert dargestellt:
  //     Sweet-Spot oben rechts (high reward + high safety).
  // Bubble-Farbe = Region (kategorial). Bubble-Größe = Sterne.
  // not_safe/red Spots werden ausgefiltert ("X ausgeblendet"-Hinweis).
  function _bandFromSpot(s)  { return spotSafetyBand(s); }
  function _starsFromSpot(s) { return spotStars(s); }
  function _scoreFromSpot(s) {
    return (window.wingcastGlyph && window.wingcastGlyph.experienceScore)
      ? window.wingcastGlyph.experienceScore(s)
      : Math.max(0, Math.min(100, Math.round((parseFloat(s.rating || 0) || 0) * 10)));
  }
  // Safety-Score: aus Cache, sonst Fallback aus status + foehn_risk.
  function _safetyScoreFromSpot(s) {
    if (s && typeof s.safety_score === 'number') {
      return Math.max(0, Math.min(100, Math.round(s.safety_score)));
    }
    const nested = (s && s.safety) || {};
    const status = String((s && s.safety_status) || nested.safety_status || '').toLowerCase();
    const foehn = String((s && s.foehn_risk) || nested.foehn_risk || 'none').toLowerCase();
    let base;
    if (status === 'safe') base = 85;
    else if (status === 'conditional') base = 50;
    else base = 0;
    let foehnDelta = 0;
    if (foehn === 'medium') foehnDelta = -15;
    else if (foehn === 'high' || foehn === 'severe') foehnDelta = -30;
    return Math.max(0, Math.min(100, base + foehnDelta));
  }
  // Deterministischer 2D-Jitter (FNV-1a hash → -1..+1 für x und y).
  function _spotJitter2D(name) {
    let h = 2166136261;
    const s = String(name || '');
    for (let i = 0; i < s.length; i++) {
      h ^= s.charCodeAt(i);
      h = Math.imul(h, 16777619);
    }
    const u = (h >>> 0);
    const jx = ((u % 2000) / 1000) - 1;            // -1..+1
    const jy = (((u >>> 11) % 2000) / 1000) - 1;   // -1..+1
    return { jx, jy };
  }
  // Kategorische Region-Palette (10 Töne, gut unterscheidbar im Light-Mode).
  // Reihenfolge nach Wahrnehmungs-Distanz — Region 1 vs 2 maximaler Kontrast.
  const REGION_PALETTE = [
    '#2563eb', // blau
    '#dc2626', // rot
    '#059669', // grün
    '#d97706', // amber
    '#7c3aed', // violett
    '#0891b2', // cyan
    '#db2777', // pink
    '#65a30d', // lime
    '#475569', // slate
    '#c2410c', // orange
  ];
  const REGION_PALETTE_FALLBACK = '#94a3b8'; // grau für 11+
  function buildSpotMatrixData(spots) {
    let hidden = 0;
    const items = [];
    const regionOrder = []; // erste Begegnung → stabile Farb-Zuordnung
    const regionMap = {};   // rid → { name, color, count }
    for (const s of spots || []) {
      if (!s.spot || !s.region_id) continue;
      const band = _bandFromSpot(s);
      if (band !== 'green' && band !== 'amber') { hidden++; continue; }
      const rid = s.region_id;
      if (!regionMap[rid]) {
        regionMap[rid] = { rid, name: s.region_name || rid, count: 0, color: '' };
        regionOrder.push(rid);
      }
      regionMap[rid].count++;
      items.push({
        rid,
        region_name: s.region_name || rid,
        spot: s.spot,
        band,
        score: _scoreFromSpot(s),
        safety: _safetyScoreFromSpot(s),
        stars: _starsFromSpot(s),
      });
    }
    // Regionen nach Spot-Anzahl sortieren (häufigste zuerst → bekommen kräftige Farben).
    regionOrder.sort((a, b) => regionMap[b].count - regionMap[a].count);
    regionOrder.forEach((rid, i) => {
      regionMap[rid].color = i < REGION_PALETTE.length
        ? REGION_PALETTE[i]
        : REGION_PALETTE_FALLBACK;
    });
    return {
      items,
      hiddenCount: hidden,
      regions: regionOrder.map((rid) => regionMap[rid]),
    };
  }

  function renderBubbleMatrix(day, filteredSpots) {
    const host = $("bfBubbleMatrix");
    if (!host) return;
    if (!filteredSpots || filteredSpots.length < 2) { host.hidden = true; return; }
    const { items, hiddenCount, regions } = buildSpotMatrixData(filteredSpots);
    if (items.length < 2) { host.hidden = true; return; }
    host.hidden = false;

    // Layout
    const W = host.clientWidth || 800;
    const isMobile = W < 640;
    const H = isMobile ? 280 : 320;
    const margin = { top: 16, right: 16, bottom: 38, left: isMobile ? 48 : 56 };
    const innerW = Math.max(200, W - margin.left - margin.right);
    const innerH = H - margin.top - margin.bottom;

    // Skalen
    const xScale = (v) => margin.left + (Math.max(0, Math.min(100, v)) / 100) * innerW;
    // Y invertiert: hoher Safety-Score → oben, niedriger → unten
    const yScale = (v) => margin.top + (1 - Math.max(0, Math.min(100, v)) / 100) * innerH;
    // Sterne → Radius (6..13px) — kompakt für 2D-Scatter
    const rScale = (stars) => 6 + Math.max(0, Math.min(5, stars || 0)) * 1.4;

    // Region-Color-Lookup
    const colorByRid = {};
    for (const r of regions) colorByRid[r.rid] = r.color;

    let svg = '<svg viewBox="0 0 ' + W + ' ' + H + '" preserveAspectRatio="xMidYMid meet" '
            + 'role="img" aria-label="Risk-Reward-Matrix">';

    // Quadranten-Hintergrund (Sweet-Spot rechts oben hervorgehoben)
    const midX = xScale(50);
    const midY = yScale(50);
    // Sweet-Spot (rechts oben): high reward + high safety
    svg += '<rect class="quad quad--sweet" x="' + midX + '" y="' + margin.top
        + '" width="' + (margin.left + innerW - midX) + '" height="' + (midY - margin.top) + '" />';
    // Niedriger Reward + sicher (links oben): "verschenkt"
    svg += '<rect class="quad quad--low" x="' + margin.left + '" y="' + margin.top
        + '" width="' + (midX - margin.left) + '" height="' + (midY - margin.top) + '" />';
    // High reward + risikant (rechts unten): "Caution-Zone"
    svg += '<rect class="quad quad--caution" x="' + midX + '" y="' + midY
        + '" width="' + (margin.left + innerW - midX) + '" height="' + (margin.top + innerH - midY) + '" />';
    // Links unten: schlecht
    svg += '<rect class="quad quad--bad" x="' + margin.left + '" y="' + midY
        + '" width="' + (midX - margin.left) + '" height="' + (margin.top + innerH - midY) + '" />';

    // Quadranten-Label oben rechts (Sweet-Spot Hint)
    svg += '<text class="quad-label" x="' + (margin.left + innerW - 6) + '" y="' + (margin.top + 14)
        + '" text-anchor="end">★ Sweet-Spot</text>';

    // Gridlines (25/50/75 auf beiden Achsen)
    [25, 50, 75].forEach((v) => {
      const x = xScale(v);
      const y = yScale(v);
      svg += '<line class="grid" x1="' + x + '" y1="' + margin.top + '" x2="' + x + '" y2="' + (margin.top + innerH) + '" />';
      svg += '<line class="grid" x1="' + margin.left + '" y1="' + y + '" x2="' + (margin.left + innerW) + '" y2="' + y + '" />';
    });

    // Achsen-Tick-Labels (X: 0/50/100, Y: 0/50/100)
    [0, 50, 100].forEach((v) => {
      const x = xScale(v);
      svg += '<text class="tick-label" x="' + x + '" y="' + (margin.top + innerH + 14)
          + '" text-anchor="middle">' + v + '</text>';
    });
    [0, 50, 100].forEach((v) => {
      const y = yScale(v);
      svg += '<text class="tick-label" x="' + (margin.left - 6) + '" y="' + (y + 3)
          + '" text-anchor="end">' + v + '</text>';
    });

    // Achsen-Titel
    svg += '<text class="axis-title" x="' + (margin.left + innerW / 2) + '" y="' + (H - 4)
        + '" text-anchor="middle">Reward · Experience-Score →</text>';
    svg += '<text class="axis-title" x="' + (margin.left - 36) + '" y="' + (margin.top + innerH / 2)
        + '" text-anchor="middle" transform="rotate(-90 ' + (margin.left - 36) + ' ' + (margin.top + innerH / 2) + ')">' + escapeHtml(wcT('js.matrix.axis_safety')) + '</text>';

    // Bubbles — Sweet-Spot zuletzt zeichnen (überlappen schlechtere)
    const drawOrder = items.slice().sort((a, b) => {
      // niedrige Sicherheit zuerst, dann niedriger Score → top-right Bubbles oben
      const sa = a.safety + a.score;
      const sb = b.safety + b.score;
      return sa - sb;
    });
    for (const it of drawOrder) {
      const { jx, jy } = _spotJitter2D(it.spot);
      const cx = xScale(it.score) + jx * 4;       // ±4px Streuung
      const cy = yScale(it.safety) + jy * 4;
      const r = rScale(it.stars);
      const color = colorByRid[it.rid] || REGION_PALETTE_FALLBACK;
      // amber-Spots leicht reduzierter Stroke-Kontrast (visuell zurückhaltend)
      const strokeOpacity = it.band === 'amber' ? 0.5 : 0.85;
      svg += '<g class="bubble" '
          + 'data-spot="' + escapeAttr(it.spot) + '" '
          + 'data-rid="' + escapeAttr(it.rid) + '" '
          + 'data-region-name="' + escapeAttr(it.region_name) + '" '
          + 'data-score="' + it.score + '" '
          + 'data-safety="' + it.safety + '" '
          + 'data-stars="' + it.stars + '" '
          + 'data-band="' + it.band + '" '
          + 'tabindex="0" role="button" '
          + 'aria-label="' + escapeAttr(wcT('js.matrix.bubble_aria', { spot: it.spot, region: it.region_name, score: it.score, safety: it.safety, stars: it.stars })) + '">'
          + '<circle cx="' + cx.toFixed(2) + '" cy="' + cy.toFixed(2) + '" r="' + r.toFixed(2)
          + '" fill="' + color + '" stroke="' + color + '" stroke-opacity="' + strokeOpacity + '" />'
          + '</g>';
    }
    svg += '</svg>';

    // Region-Legende (kompakte Pills)
    const legendItems = regions.map((r) => {
      const dimmed = r.color === REGION_PALETTE_FALLBACK ? ' is-dim' : '';
      return '<button type="button" class="bf-region-chip' + dimmed
        + '" data-rid="' + escapeAttr(r.rid) + '" title="' + escapeAttr(r.name) + '">'
        + '<span class="bf-region-chip-dot" style="background:' + r.color + '"></span>'
        + '<span class="bf-region-chip-name">' + escapeHtml(r.name) + '</span>'
        + '<span class="bf-region-chip-count">' + r.count + '</span>'
        + '</button>';
    }).join('');

    const hiddenHint = hiddenCount > 0
      ? '<span class="bf-bubble-matrix-hidden">' + escapeHtml(wcT('js.matrix.hidden', { n: hiddenCount })) + '</span>'
      : '';

    host.innerHTML =
      '<div class="bf-bubble-matrix-header">'
      + '<span class="bf-bubble-matrix-title">Risk-Reward-Matrix</span>'
      + '<span class="bf-bubble-matrix-legend-meta">'
      + '<span class="legend-item legend-item--size">' + escapeHtml(wcT('js.matrix.legend_size')) + '</span>'
      + hiddenHint
      + '</span>'
      + '</div>'
      + '<div class="bf-bubble-matrix-svg-wrap">' + svg + '</div>'
      + '<div class="bf-region-legend">' + legendItems + '</div>'
      + '<div class="bf-bubble-tooltip" hidden></div>';

    const tooltip = host.querySelector('.bf-bubble-tooltip');
    const wrap = host.querySelector('.bf-bubble-matrix-svg-wrap');
    function showTooltip(g, evt) {
      if (!tooltip || !wrap) return;
      const spot = g.getAttribute('data-spot') || '';
      const region = g.getAttribute('data-region-name') || '';
      const score = g.getAttribute('data-score') || '';
      const safety = g.getAttribute('data-safety') || '';
      const stars = parseInt(g.getAttribute('data-stars') || '0', 10);
      const band = g.getAttribute('data-band') || '';
      const bandLabel = band === 'green' ? 'safe' : (band === 'amber' ? 'conditional' : band);
      const starGlyph = '★'.repeat(Math.max(0, Math.min(5, stars))) + '☆'.repeat(5 - Math.max(0, Math.min(5, stars)));
      tooltip.innerHTML =
        '<div class="bf-bubble-tooltip-name">' + escapeHtml(spot) + '</div>'
        + '<div class="bf-bubble-tooltip-region">' + escapeHtml(region) + '</div>'
        + '<div class="bf-bubble-tooltip-grid">'
        +   '<div class="bf-bubble-tooltip-cell"><span class="lbl">Reward</span><span class="val">' + score + '</span></div>'
        +   '<div class="bf-bubble-tooltip-cell"><span class="lbl">' + escapeHtml(wcT('js.matrix.tt_safety')) + '</span><span class="val">' + safety + '</span></div>'
        + '</div>'
        + '<div class="bf-bubble-tooltip-row"><span class="bf-bubble-tooltip-stars">' + starGlyph + '</span>'
        + '<span class="bf-bubble-tooltip-band bf-bubble-tooltip-band--' + band + '">' + bandLabel + '</span></div>';
      tooltip.hidden = false;
      const wrapRect = wrap.getBoundingClientRect();
      const circ = g.querySelector('circle');
      let cx = wrapRect.width / 2, cy = 0;
      if (circ) {
        const cr = circ.getBoundingClientRect();
        cx = cr.left - wrapRect.left + cr.width / 2;
        cy = cr.top - wrapRect.top;
      } else if (evt) {
        cx = evt.clientX - wrapRect.left;
        cy = evt.clientY - wrapRect.top;
      }
      const tw = tooltip.offsetWidth;
      const th = tooltip.offsetHeight;
      let left = cx - tw / 2;
      left = Math.max(4, Math.min(wrapRect.width - tw - 4, left));
      let top = cy - th - 10;
      if (top < 4) top = cy + 18;
      tooltip.style.left = left + 'px';
      tooltip.style.top = top + 'px';
    }
    function hideTooltip() {
      if (tooltip) tooltip.hidden = true;
    }

    function activateBubble(g) {
      const spot = g.getAttribute('data-spot');
      const rid = g.getAttribute('data-rid');
      let target = null;
      const spotEls = document.querySelectorAll('.bf-spot');
      for (const el of spotEls) {
        const nameEl = el.querySelector('.bf-spot-name');
        if (nameEl && nameEl.textContent.trim() === spot) { target = el; break; }
      }
      if (!target && rid) target = document.querySelector('[data-region-id="' + escapeAttr(rid) + '"]');
      if (target) {
        target.scrollIntoView({ behavior: 'smooth', block: 'center' });
        target.classList.add('bf-region-flash');
        setTimeout(() => target.classList.remove('bf-region-flash'), 1200);
      }
      hideTooltip();
    }

    host.querySelectorAll('.bubble').forEach((g) => {
      g.addEventListener('mouseenter', (e) => showTooltip(g, e));
      g.addEventListener('mouseleave', hideTooltip);
      g.addEventListener('focus', () => showTooltip(g, null));
      g.addEventListener('blur', hideTooltip);
      g.addEventListener('click', () => activateBubble(g));
      g.addEventListener('keydown', (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); activateBubble(g); }
      });
    });

    // Region-Chip-Hover/Klick: alle anderen Regionen ausgrauen + Region-Card scrollen
    host.querySelectorAll('.bf-region-chip').forEach((chip) => {
      const rid = chip.getAttribute('data-rid');
      chip.addEventListener('mouseenter', () => {
        host.querySelectorAll('.bubble').forEach((g) => {
          if (g.getAttribute('data-rid') !== rid) g.classList.add('is-faded');
        });
      });
      chip.addEventListener('mouseleave', () => {
        host.querySelectorAll('.bubble.is-faded').forEach((g) => g.classList.remove('is-faded'));
      });
      chip.addEventListener('click', () => {
        const target = document.querySelector('[data-region-id="' + escapeAttr(rid) + '"]');
        if (target) {
          target.scrollIntoView({ behavior: 'smooth', block: 'start' });
          target.classList.add('bf-region-flash');
          setTimeout(() => target.classList.remove('bf-region-flash'), 1200);
        }
      });
    });
  }

  function escapeAttr(s) {
    return String(s || '').replace(/[&<>"']/g, (c) => ({
      '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
    }[c]));
  }

  function groupSpotsByRegion(spots) {
    const groups = {};
    for (const s of spots || []) {
      if (!s.spot || !String(s.spot).trim()) continue;
      const rid = s.region_id || "unknown";
      if (!groups[rid]) groups[rid] = { region_id: rid, region_name: s.region_name || "", spots: [] };
      if (!groups[rid].region_name && s.region_name) groups[rid].region_name = s.region_name;
      groups[rid].spots.push(s);
    }
    return Object.values(groups);
  }

  function filterDaySpots(day) {
    if (!day) return [];
    let spots = day.top_spots || [];
    if (state.filterRegions && state.filterRegions.size > 0) {
      spots = spots.filter((s) => regionPassesFilter(s.region_id));
    }
    if (state.focusSpot) {
      // Focus-Modus (Deep-Link): Tier/Rating-Filter ignorieren, damit der Spot
      // immer sichtbar ist auch wenn der Filter ihn sonst ausblenden wuerde.
      const want = state.focusSpot.toLowerCase();
      spots = spots.filter((s) => (s.spot || "").toLowerCase() === want);
    } else {
      spots = spots.filter(spotPassesSafetyFilter);
      spots = spots.filter(spotPassesRatingFilter);
    }
    return spots;
  }

  // ── Render: Header ──────────────────────────────────────────

  function renderHeader(data) {
    const dates = data.forecast_dates || [];
    const first = dates[0];
    const last = dates[dates.length - 1];
    const rangeEl = $("bfDateRange");
    if (rangeEl) {
      rangeEl.textContent = first && last ? `${formatDateShort(first)} – ${formatDateShort(last)}` : "";
    }
    const tsEl = $("bfGeneratedAt");
    if (tsEl) tsEl.textContent = formatGeneratedAt(data.generated_at);
  }

  // ── Render: Day Tabs ────────────────────────────────────────

  function renderDayTabs(data) {
    const container = $("bfDayTabs");
    if (!container) return;
    const days = data.days || [];
    if (!days.length) { container.innerHTML = ""; return; }

    // Clamp selectedDayIdx
    if (state.selectedDayIdx >= days.length) state.selectedDayIdx = 0;

    container.innerHTML = days.map((d, i) => {
      const isActive = i === state.selectedDayIdx;

      // RATING_CONCEPT v1.3: Day-Tabs zaehlen safety_band-Verteilung +
      // Top-Sterne als Hingucker. flyable = green + amber.
      let topCount = 0, greenCount = 0, amberCount = 0;
      for (const s of (d.top_spots || [])) {
        const b = spotSafetyBand(s);
        if (b === "red" || b === "no_data") continue;
        if (spotStars(s) >= 4) topCount++;
        else if (b === "green") greenCount++;
        else if (b === "amber") amberCount++;
      }
      const flyable = topCount + greenCount + amberCount;

      // Build dots (max 4 visuell): Top zuerst, dann green, dann amber
      const dots = [];
      for (let j = 0; j < Math.min(topCount, 2); j++) dots.push('<span class="bf-tab-dot top"></span>');
      for (let j = 0; j < Math.min(greenCount, 2); j++) dots.push('<span class="bf-tab-dot green"></span>');
      if (dots.length < 4) {
        for (let j = 0; j < Math.min(amberCount, 4 - dots.length); j++) dots.push('<span class="bf-tab-dot amber"></span>');
      }

      const dateObj = new Date(d.date + "T12:00:00");
      const dayNum = dateObj.getDate();
      const wdShort = (d.weekday || "").substring(0, 2);

      const cls = ["bf-day-tab"];
      if (isActive) cls.push("is-active");

      return `
        <button type="button" class="${cls.join(" ")}" role="tab"
                aria-selected="${isActive}" data-day-idx="${i}">
          <span class="bf-tab-weekday">${escapeHtml(wdShort)}</span>
          <span class="bf-tab-date">${dayNum}</span>
          ${dots.length ? `<span class="bf-tab-dots">${dots.join("")}</span>` : ""}
          ${flyable > 0 ? `<span class="bf-tab-count">${flyable}</span>` : ""}
        </button>
      `;
    }).join("");

    if (!container._flyBound) {
      container._flyBound = true;
      container.addEventListener("click", (ev) => {
        const btn = ev.target.closest(".bf-day-tab");
        if (!btn) return;
        const idx = parseInt(btn.dataset.dayIdx, 10);
        if (!isFinite(idx)) return;
        selectDay(idx);
      });
    }
  }

  function selectDay(idx) {
    state.selectedDayIdx = idx;
    saveDayIdx(idx);
    // Bei manuellem Tab-Wechsel Spot-Focus loesen, sonst sieht User
    // in anderen Tagen leeren State weil der Spot nur an einem Tag ist.
    state.focusSpot = null;
    renderDayTabs(state.data);
    // Wetterlage + Synoptik-Karte folgen dem gewaehlten Tag
    renderWetterlage(state.data);
    syncSynopticDate();
    renderDayContent();
  }

  // Datum des aktuell gewaehlten Tages ("YYYY-MM-DD") oder null.
  function selectedDate() {
    const days = (state.data && state.data.days) || [];
    const d = days[state.selectedDayIdx];
    return d && d.date ? d.date : null;
  }

  // Synoptik-Mini-Karte auf den gewaehlten Tag stellen (12:00-Timestep).
  // synoptic-embed.js laedt das Grid asynchron und merkt sich das Datum,
  // falls es noch nicht bereit ist — die Reihenfolge ist damit egal.
  function syncSynopticDate() {
    if (window.WCSynopticEmbed) window.WCSynopticEmbed.setDate(selectedDate());
  }

  // ── Render: Filters ─────────────────────────────────────────

  function renderFilters(data) {
    const chipsEl = $("bfFilterChips");
    const resetBtn = $("bfFilterReset");
    if (!chipsEl) return;

    const regions = collectAllRegions(data);
    if (!regions.length) return;

    // Clean stale filter IDs
    const mapReady = !!(_filterMap && _filterMap.pathById && _filterMap.pathById.size > 0);
    if (mapReady) {
      const validIds = new Set(regions.map((r) => r.id));
      let changed = false;
      for (const id of Array.from(state.filterRegions)) {
        if (!validIds.has(id)) { state.filterRegions.delete(id); changed = true; }
      }
      if (changed) saveRegionFilter(state.filterRegions);
    }

    chipsEl.innerHTML = regions.map((r) => {
      const active = state.filterRegions.has(r.id);
      return `<button type="button" class="bf-filter-chip${active ? " is-active" : ""}" data-region-id="${escapeHtml(r.id)}" aria-pressed="${active}">${escapeHtml(r.name)}</button>`;
    }).join("");

    if (!chipsEl._flyBound) {
      chipsEl._flyBound = true;
      chipsEl.addEventListener("click", (ev) => {
        const btn = ev.target.closest(".bf-filter-chip");
        if (!btn) return;
        const id = btn.dataset.regionId;
        if (!id) return;
        if (state.filterRegions.has(id)) state.filterRegions.delete(id);
        else state.filterRegions.add(id);
        applyFilter();
      });
    }

    if (resetBtn) {
      // Toggle: wenn bereits alle Regionen aktiv sind -> abwaehlen, sonst alle auswaehlen.
      // Leeres Set = "kein Region-Filter" (zeigt auch alle) — visuell wie nichts aktiv.
      const allIds = regions.map((r) => r.id);
      const allActive = allIds.length > 0 && allIds.every((id) => state.filterRegions.has(id));
      resetBtn.disabled = allIds.length === 0;
      resetBtn.textContent = allActive ? wcT("js.regions.none") : wcT("js.regions.all");
      resetBtn.classList.toggle("is-active", allActive);
      resetBtn.setAttribute(
        "aria-label",
        allActive ? wcT("js.regions.deselect_all") : wcT("js.regions.select_all"),
      );
      if (!resetBtn._flyBound) {
        resetBtn._flyBound = true;
        resetBtn.addEventListener("click", () => {
          const regionsNow = collectAllRegions(state.data);
          const ids = regionsNow.map((r) => r.id);
          if (!ids.length) return;
          const allSel = ids.every((id) => state.filterRegions.has(id));
          if (allSel) state.filterRegions.clear();
          else state.filterRegions = new Set(ids);
          applyFilter();
        });
      }
    }

    // Map toggle
    const mapBtn = $("bfMapToggle");
    if (mapBtn && !mapBtn._flyBound) {
      mapBtn._flyBound = true;
      mapBtn.addEventListener("click", () => {
        state.mapVisible = !state.mapVisible;
        const mapEl = $("bfFilterMap");
        if (mapEl) mapEl.hidden = !state.mapVisible;
        mapBtn.classList.toggle("is-active", state.mapVisible);
        if (state.mapVisible) initFilterMap(regions);
      });
    }

    if (state.mapVisible) initFilterMap(regions);
  }

  function applyFilter() {
    // Manueller Region-Filter-Toggle loest Spot-Focus (User erkundet neu).
    state.focusSpot = null;
    saveRegionFilter(state.filterRegions);
    renderFilters(state.data);
    renderDayTabs(state.data);
    renderDayContent();
  }

  // ── Render: Safety-Band + Stars Filter (RATING_CONCEPT v1.3) ─

  function renderTierFilter() {
    const chipsEl = $("bfTierChips");
    const slider = $("bfRatingSlider");
    const valueEl = $("bfRatingValue");
    if (!chipsEl || !slider || !valueEl) return;

    // Safety-Chips: 3 Baender (gruen/amber/rot) als Toggle.
    chipsEl.innerHTML = SAFETY_DEFS.map((t) => {
      const active = state.safetyFilters.has(t.id);
      const glyph = (window.wingcastGlyph && window.wingcastGlyph.svg)
        ? window.wingcastGlyph.svg({ band: t.id, stars: 0, size: 16, ariaLabel: t.label })
        : `<span class="bf-tier-dot"></span>`;
      return `<button type="button" class="bf-tier-chip bf-tier-chip--${t.id}${active ? " is-active" : ""}" data-band="${t.id}" aria-pressed="${active}">
        ${glyph}<span class="bf-tier-label">${escapeHtml(t.label)}</span>
      </button>`;
    }).join("");

    if (!chipsEl._flyBound) {
      chipsEl._flyBound = true;
      chipsEl.addEventListener("click", (ev) => {
        const btn = ev.target.closest(".bf-tier-chip");
        if (!btn) return;
        const id = btn.dataset.band;
        if (!id) return;
        if (state.safetyFilters.has(id)) state.safetyFilters.delete(id);
        else state.safetyFilters.add(id);
        saveSafetyFilter(state.safetyFilters);
        state.focusSpot = null;
        renderTierFilter();
        renderDayContent();
      });
    }

    // Fliegbarkeit-Slider (0–5, experience_rating-Skala v2.1)
    if (slider.max !== "5" || slider.step !== "1") {
      slider.min = "0";
      slider.max = "5";
      slider.step = "1";
    }
    const v = Number(state.minRating || 0);
    slider.value = String(v);
    updateSliderVisual(slider, valueEl, v);

    if (!slider._flyBound) {
      slider._flyBound = true;
      slider.addEventListener("input", (ev) => {
        const val = parseInt(ev.target.value, 10) || 0;
        state.minRating = val;
        updateSliderVisual(slider, valueEl, val);
      });
      slider.addEventListener("change", () => {
        saveMinRating(state.minRating);
        state.focusSpot = null;
        renderDayContent();
      });
    }
  }

  function updateSliderVisual(slider, valueEl, v) {
    valueEl.textContent = v > 0 ? "\u2265 " + v + " / 5" : "alle";
    slider.classList.toggle("is-active", v > 0);
    const min = parseFloat(slider.min) || 0;
    const max = parseFloat(slider.max) || 5;
    const pct = max > min ? ((v - min) / (max - min)) * 100 : 0;
    slider.style.setProperty("--fill", pct.toFixed(1) + "%");
  }

  // ── Filter Map (Leaflet) ────────────────────────────────────

  const _filterMap = { map: null, layer: null, pathById: new Map() };

  function filterMapStyle(regionId) {
    const active = state.filterRegions.has(regionId);
    if (active) {
      return { color: "#8c2d1f", weight: 2.5, opacity: 1, fillColor: "#c94a36", fillOpacity: 0.55 };
    }
    return { color: "#6b635a", weight: 1.2, opacity: 1, fillColor: "#c4bdb0", fillOpacity: 0.45 };
  }

  function updateFilterMapStyles() {
    if (!_filterMap.layer) return;
    _filterMap.pathById.forEach((lyr, id) => {
      try { lyr.setStyle(filterMapStyle(id)); } catch (_) {}
    });
  }

  function initFilterMap(regions) {
    const el = $("bfFilterMap");
    if (!el) return;

    if (_filterMap.map) {
      updateFilterMapStyles();
      return;
    }
    if (typeof L === "undefined") {
      el.innerHTML = '<div class="bf-minimap-fallback">' + wcT('js.map.unavailable') + '</div>';
      return;
    }

    try {
      const mapObj = L.map(el, {
        center: [46.8, 8.2], zoom: 7,
        zoomControl: true, attributionControl: false,
        scrollWheelZoom: false, dragging: true, touchZoom: true, doubleClickZoom: false,
      });
      L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
        subdomains: 'abcd', maxZoom: 14,
      }).addTo(mapObj);
      _filterMap.map = mapObj;
      mapObj.fitBounds([[45.8, 5.9], [47.9, 10.6]], { padding: [20, 20], maxZoom: 7 });

      fetch("/api/regionen-polygone", { cache: "no-store" })
        .then((r) => r.json())
        .then((geojson) => {
          if (!geojson || !Array.isArray(geojson.features) || !geojson.features.length) return;

          const layer = L.geoJSON(geojson, {
            style: (feature) => filterMapStyle(feature.properties.id),
            onEachFeature: (feature, lyr) => {
              const props = feature.properties || {};
              const rid = props.id;
              if (!rid) return;
              _filterMap.pathById.set(rid, lyr);

              lyr.bindTooltip(props.region || props.name || rid, {
                className: "bf-region-label", direction: "center", permanent: false, sticky: true,
              });

              lyr.on("click", () => {
                if (state.filterRegions.has(rid)) state.filterRegions.delete(rid);
                else state.filterRegions.add(rid);
                applyFilter();
              });
              lyr.on("mouseover", function () {
                this.setStyle(Object.assign({}, filterMapStyle(rid), { weight: 3.5, fillOpacity: 0.7 }));
              });
              lyr.on("mouseout", function () { this.setStyle(filterMapStyle(rid)); });
            },
          }).addTo(mapObj);
          _filterMap.layer = layer;

          try { mapObj.invalidateSize(); } catch (_) {}
          try {
            const b = layer.getBounds();
            if (b && b.isValid()) mapObj.fitBounds(b, { padding: [20, 20], maxZoom: 7 });
          } catch (_) {}
          try { renderFilters(state.data); } catch (_) {}
        })
        .catch((err) => console.warn("[briefing] filter-map fetch failed", err));

      requestAnimationFrame(() => { try { mapObj.invalidateSize(); } catch (_) {} });
      setTimeout(() => { try { mapObj.invalidateSize(); } catch (_) {} }, 300);
    } catch (e) {
      console.warn("[briefing] filter-map init failed", e);
      el.innerHTML = '<div class="bf-minimap-fallback">' + wcT('js.map.unavailable') + '</div>';
    }
  }

  // ── Render: Day Content ─────────────────────────────────────

  function renderDayContent() {
    const infoEl = $("bfDayInfo");
    const contentEl = $("bfContent");
    if (!infoEl || !contentEl) return;

    const day = getSelectedDay();
    if (!day) {
      infoEl.innerHTML = "";
      contentEl.innerHTML = '<div class="bf-content-empty">' + escapeHtml(wcT('js.empty.no_forecast')) + '</div>';
      return;
    }

    // Day info bar — RATING_CONCEPT v1.3: safety_band-Verteilung des gesamten
    // Tages (Region-Filter respektiert, Safety/Stars-Filter NICHT) — damit der
    // User sieht, was er gerade per Filter ausblendet.
    const filteredSpots = filterDaySpots(day);
    const G = window.wingcastGlyph;
    const allSpotsRegionFiltered = (day.top_spots || []).filter((s) => regionPassesFilter(s.region_id));
    const counts = G && G.bandCounts ? G.bandCounts(allSpotsRegionFiltered) : { green: 0, amber: 0, red: 0, no_data: 0 };
    let topStars = 0;
    for (const s of allSpotsRegionFiltered) {
      if (spotStars(s) >= 4 && spotSafetyBand(s) !== "red") topStars++;
    }

    infoEl.innerHTML = `
      <span class="bf-day-title">${escapeHtml(day.weekday || "")} ${formatDateDE(day.date)}</span>
      <span class="bf-day-stats">
        ${counts.green > 0 ? `<span class="bf-stat bf-stat--green"><strong>${counts.green}</strong> ${wcT('js.stat.green')}</span>` : ""}
        ${counts.amber > 0 ? `<span class="bf-stat bf-stat--amber"><strong>${counts.amber}</strong> ${wcT('js.stat.amber')}</span>` : ""}
        ${counts.red > 0 ? `<span class="bf-stat bf-stat--red"><strong>${counts.red}</strong> ${wcT('js.stat.red')}</span>` : ""}
        ${topStars > 0 ? `<span class="bf-stat bf-stat--top">★ <strong>${topStars}</strong> ${wcT('js.stat.top')}</span>` : ""}
      </span>
    `;

    // Spots grouped by region
    const spotsWithDate = filteredSpots.map((s) => Object.assign({}, s, { date: day.date }));
    let groups = groupSpotsByRegion(spotsWithDate);

    // Region meta from day data
    const regionsMap = {};
    for (const r of (day.top_regions || [])) {
      regionsMap[r.region_id] = r;
    }

    // Sortierung: Regionen werden im Wingcast NICHT mehr farblich/per-Rating
    // bewertet (User-Wunsch — "Pilot sucht eine Region und will dann nur die
    // Spots darin sehen"). Wir sortieren aber Regionen weiter so, dass die mit
    // den besten Spots oben stehen — abgeleitet aus Spot-Ratings, ohne dass
    // dies dem User im Region-Header angezeigt werden muss.
    const groupSpotScore = (g) => {
      let best = 0;
      for (const s of g.spots) {
        const r = spotRating(s);
        if (r > best) best = r;
      }
      return best;
    };
    groups.sort((a, b) => groupSpotScore(b) - groupSpotScore(a));

    // Focus-Banner (wenn Nutzer aus E-Mail auf einen spezifischen Spot kam)
    const focusBanner = state.focusSpot
      ? `<div class="bf-focus-banner" role="status">
           <span class="bf-focus-text">${wcT('js.focus.show_only_pre')} <strong>${escapeHtml(state.focusSpot)}</strong></span>
           <button type="button" class="bf-focus-clear" onclick="window.__bf_clearFocus && window.__bf_clearFocus()">${wcT('js.focus.show_all')}</button>
         </div>`
      : "";

    if (!groups.length) {
      let emptyMsg;
      if (state.focusSpot) {
        emptyMsg = wcT('js.empty.spot_not_found', { spot: escapeHtml(state.focusSpot) });
      } else {
        const filterActive = (state.safetyFilters.size < SAFETY_DEFS.length) || state.minRating > 0 || state.filterRegions.size > 0;
        const filterHint = filterActive
          ? `<button type="button" class="bf-empty-reset" onclick="window.__bf_resetFilters && window.__bf_resetFilters()">${wcT('js.filter.reset')}</button>`
          : "";
        const cRed = counts.red || 0;
        const cAmber = counts.amber || 0;
        emptyMsg = `<div class="bf-empty-msg">${wcT('js.empty.no_match_pre')}${state.filterRegions.size ? wcT('js.empty.in_filtered_regions') : ""}${wcT('js.empty.no_match_post')}</div><div class="bf-empty-counts">${wcT('js.empty.counts_hidden', { red: cRed, amber: cAmber })}</div>${filterHint}`;
      }
      contentEl.innerHTML = focusBanner + `<div class="bf-content-empty">${emptyMsg}</div>`;
      return;
    }

    // Bulk-Toggle-Bar: Pilot soll mit einem Klick alle Regionen auf/zu klappen.
    // Label spiegelt den naechsten Zustand wider — wenn aktuell ueberwiegend
    // eingeklappt, zeige "Alle ausklappen", sonst "Alle einklappen".
    const allRegionIds = groups.map((g) => g.region_id || "");
    const collapsedCount = allRegionIds.filter((rid) => state.collapsedRegions.has(rid)).length;
    const willExpandAll = collapsedCount >= allRegionIds.length / 2;
    const bulkLabel = willExpandAll ? wcT("js.bulk.expand_all") : wcT("js.bulk.collapse_all");
    const bulkIcon = willExpandAll ? "▾" : "▴";
    const bulkBar = groups.length > 1
      ? `<div class="bf-bulk-toggle-bar">
           <button type="button" class="bf-bulk-toggle" data-bulk-action="${willExpandAll ? "expand" : "collapse"}"
                   aria-label="${escapeHtml(bulkLabel)}">
             <span class="bf-bulk-toggle-icon" aria-hidden="true">${bulkIcon}</span>
             <span class="bf-bulk-toggle-label">${escapeHtml(bulkLabel)}</span>
           </button>
         </div>`
      : "";

    contentEl.innerHTML = focusBanner + bulkBar + groups.map((g) => renderRegionSection(g, regionsMap[g.region_id])).join("");

    // Focus-Modus: die eine verbleibende Spot-Kachel direkt aufklappen.
    if (state.focusSpot) {
      requestAnimationFrame(() => autoExpandFocusSpot());
    }
  }

  function autoExpandFocusSpot() {
    const contentEl = $("bfContent");
    if (!contentEl) return;
    const li = contentEl.querySelector(".bf-spot");
    if (!li || li.classList.contains("is-expanded")) return;
    const toggle = li.querySelector(".bf-spot-toggle");
    const details = li.querySelector(".bf-spot-details");
    if (!toggle || !details) return;
    li.classList.add("is-expanded");
    toggle.setAttribute("aria-expanded", "true");
    details.removeAttribute("hidden");
    const miniMap = details.querySelector(".bf-spot-minimap");
    if (miniMap && !miniMap.classList.contains("bf-spot-minimap--nodata")) initMiniMap(miniMap);
    const meteogramEl = details.querySelector(".bf-spot-meteogram");
    if (meteogramEl) initMeteogram(meteogramEl);
    requestAnimationFrame(() => {
      try { li.scrollIntoView({ behavior: "smooth", block: "start" }); } catch (_) {}
    });
  }

  // Erste Aussage-Saetze aus der LLM-Region-recommendation extrahieren — voller
  // Satz als Tooltip-Quelle.
  function extractRegionSummary(rec) {
    if (!rec || typeof rec !== "string") return "";
    let txt = rec.trim().replace(/^Unsere Einsch[aä]tzung:\s*/i, "");
    const m = txt.match(/^[^.!?]+[.!?]/);
    let first = m ? m[0].trim() : txt;
    if (first.length < 40) {
      const rest = txt.slice(first.length).trim();
      const m2 = rest.match(/^[^.!?]+[.!?]/);
      if (m2) first = first + " " + m2[0].trim();
    }
    return first;
  }

  // hex (#rrggbb) → rgba mit alpha — fuer transparente Pill/Spot-Backgrounds.
  function hexToRgba(hex, alpha) {
    if (!hex || hex[0] !== "#") return hex;
    const h = hex.slice(1);
    const r = parseInt(h.slice(0, 2), 16);
    const g = parseInt(h.slice(2, 4), 16);
    const b = parseInt(h.slice(4, 6), 16);
    return `rgba(${r},${g},${b},${alpha})`;
  }

  // Region-Pill: Label deterministisch aus Rating-Tier, Farbe 1:1 aus der
  // Karten-Palette (region-map.js getRatingTint) — gleiche Hue+Lightness-Stufen
  // damit Pill und Polygon konsistent sind. Voller LLM-Satz als Tooltip.
  function regionPillSpec(meta) {
    if (!meta) return null;
    const rawBand = meta.safety_band || meta.safety_status || "";
    const rating = Math.max(0, Math.min(5, parseInt(meta.experience_rating, 10) || 0));

    if (rawBand === "red" || rawBand === "not_safe") {
      return { label: wcT("js.safety.not_flyable"), hex: "#ef4444", border: "#991b1b", text: "#ffffff", darkBg: true };
    }
    if (rating <= 0) return null;

    if (rawBand === "amber" || rawBand === "conditional") {
      // Conditional bleibt Yellow→Gold→Orange→Burnt→Brown (Warnsignal-Spektrum).
      const labels = [wcT("js.pill.tier0"), wcT("js.pill.tier1"), wcT("js.pill.tier2"), wcT("js.pill.tier3"), wcT("js.pill.tier4")];
      const bgs    = ["#fef08a", "#facc15", "#f97316", "#c2410c", "#7c2d12"];
      const borders= ["#ca8a04", "#a16207", "#9a3412", "#7c2d12", "#431407"];
      const texts  = ["#713f12", "#713f12", "#ffffff", "#ffffff", "#ffffff"];
      const darkBg = [false, false, true, true, true];
      const i = Math.min(4, rating - 1);
      return { label: labels[i], hex: bgs[i], border: borders[i], text: texts[i], darkBg: darkBg[i] };
    }

    // Safe-Band v3.2 — "Royal Premium" finale Palette (Mai 2026):
    // Sky-100 → Sky-200 → Lime → Green-500 → Violet-Premium.
    const labels = [wcT("js.pill.tier0"), wcT("js.pill.safe_tier1"), wcT("js.pill.tier2"), wcT("js.pill.tier3"), wcT("js.pill.tier4")];
    const bgs    = ["#e0f2fe", "#bae6fd", "#BEF264", "#22c55e", "#a78bfa"];
    const borders= ["#38bdf8", "#0ea5e9", "#65a30d", "#15803d", "#6d28d9"];
    const texts  = ["#075985", "#075985", "#3f6212", "#ffffff", "#ffffff"];
    const darkBg = [false, false, false, true, true];
    const i = Math.min(4, rating - 1);
    return { label: labels[i], hex: bgs[i], border: borders[i], text: texts[i], darkBg: darkBg[i] };
  }

  function renderRegionSection(group, meta) {
    const name = (meta && meta.region_name) || group.region_name || (group.region_id === "unknown" ? "Weitere Spots" : group.region_id);
    // Sortierung nach Rating absteigend — Filter kommen vom Slider + Safety-Chips
    // (filterDaySpots), kein zusaetzlicher Hard-Cutoff hier, damit der Slider-Wert
    // verlaesslich gilt (User setzt Slider auf 4 → sieht alle 4er-Spots).
    const displaySpots = state.focusSpot
      ? group.spots
      : group.spots.slice().sort((a, b) => spotRating(b) - spotRating(a));
    const spotsHtml = displaySpots.map(renderSpotRow).join("");
    const spotCount = displaySpots.length;

    // Region-Header bewusst minimal: nur Name, Spot-Anzahl, Share, Chevron.
    // KEIN Glyph, KEIN Rating, KEIN Farb-Band — Bewertung passiert auf Spot-Ebene.
    // Mental-Modell: Region = struktureller Divider ("Welche Region?"),
    // Spot = der eigentliche Inhalt ("Wie gut sind die Plaetze?").
    const shareBtn = group.region_id && group.region_id !== "unknown"
      ? `<button type="button" class="bf-share-btn bf-share-btn--region"
                 data-share-kind="region"
                 data-share-region="${escapeHtml(group.region_id)}"
                 data-share-region-name="${escapeHtml(name)}"
                 title="Region teilen" aria-label="Region teilen">${window.wingcastShareIconSVG || "⇪"}</button>`
      : "";
    const isCollapsed = state.collapsedRegions.has(group.region_id);
    const collapsedCls = isCollapsed ? " is-collapsed" : "";
    const ariaExpanded = isCollapsed ? "false" : "true";
    const regionDebugHtml = meta ? renderDebugNotes(meta) : "";
    const fullSummary = extractRegionSummary(meta && meta.recommendation);
    const pill = regionPillSpec(meta);
    // Transparenz: dunkle Bgs (white text) brauchen mehr Saettigung fuer Kontrast,
    // helle Bgs koennen mehr atmen.
    const pillBg = pill ? hexToRgba(pill.hex, pill.darkBg ? 0.78 : 0.55) : "";
    const pillBorder = pill ? hexToRgba(pill.border, 0.55) : "";
    const summaryHtml = pill
      ? `<span class="bf-region-pill" style="background:${pillBg};border-color:${pillBorder};color:${pill.text}" title="${escapeAttr(fullSummary || pill.label)}">${escapeHtml(pill.label)}</span>`
      : "";
    return `
      <div class="bf-region${collapsedCls}" data-region-id="${escapeHtml(group.region_id)}">
        <div class="bf-region-head" role="button" tabindex="0" aria-expanded="${ariaExpanded}" aria-label="Region ${escapeHtml(name)} ein-/ausklappen">
          <span class="bf-region-name">${escapeHtml(name)}</span>
          ${summaryHtml}
          <span class="bf-region-spacer" aria-hidden="true"></span>
          <span class="bf-region-count" aria-hidden="true">${spotCount} ${spotCount === 1 ? "Spot" : "Spots"}</span>
          ${shareBtn}
          <span class="bf-region-chevron" aria-hidden="true">▾</span>
        </div>
        <ul class="bf-spot-list">${spotsHtml}</ul>
        ${regionDebugHtml}
      </div>
    `;
  }

  // ── Render: Spot Row ────────────────────────────────────────

  function renderSpotRow(spot) {
    if (!spot.spot || !String(spot.spot).trim()) return "";
    // RATING_CONCEPT v1.4: safety_band + experience_rating (1-10) als Primaer-Achsen.
    const band = spotSafetyBand(spot);
    const stars = spotStars(spot);
    const rating = spotRating(spot);
    const safetyCls = "safety-" + band;
    const glyphHtml = (window.wingcastGlyph && window.wingcastGlyph.svg)
      ? window.wingcastGlyph.svg({ band, rating, size: 24 })
      : "";

    // ── Status-Leiste: nur sachliche Chips (Best-Window, Flugtyp, Steigwerte).
    // Sicherheit + Erlebnis sind im Glyph kodiert — kein zusaetzlicher "Sicher"/"Bedingt"-Chip noetig.
    const chips = [];
    if (spot.best_window) chips.push(`<span class="bf-chip bf-chip--window">${escapeHtml(spot.best_window)}</span>`);
    if (spot.flight_type) chips.push(`<span class="bf-chip bf-chip--type">${escapeHtml(spot.flight_type)}</span>`);
    if (spot.peak_climb_rate && Number(spot.peak_climb_rate) > 0) {
      chips.push(`<span class="bf-chip bf-chip--climb">↑${Number(spot.peak_climb_rate).toFixed(1)} m/s</span>`);
    }
    if (spot.flight_duration) chips.push(`<span class="bf-chip">${escapeHtml(spot.flight_duration)}</span>`);

    const statusBar = chips.length
      ? `<div class="bf-spot-status">${chips.join("")}</div>`
      : "";

    // Score-Pille: gleiche Rating-Tint-Palette wie Region-Pill (synchron zur
    // Karte). Alpha-Softening konsistent: helle Bgs 0.55, dunkle 0.78.
    const scorePills = [];
    if (band !== 'red' && band !== 'no_data' && rating > 0) {
      const sp = regionPillSpec({ safety_band: band, experience_rating: rating });
      if (sp) {
        const spBg = hexToRgba(sp.hex, sp.darkBg ? 0.78 : 0.55);
        const spBorder = hexToRgba(sp.border, 0.55);
        scorePills.push(`<span class="bf-score-pill" style="background:${spBg};border-color:${spBorder};color:${sp.text}">${escapeHtml(sp.label)}</span>`);
      }
    }
    const scoreBar = scorePills.length ? `<div class="bf-spot-scores">${scorePills.join("")}</div>` : "";

    const mapHref = `/map?spot=${encodeURIComponent(spot.spot)}${spot.date ? `&date=${encodeURIComponent(spot.date)}` : ''}`;

    // Details (expanded content)
    const analysisForDetails = spot.analysis_full || synthesizeAnalysis(spot);
    let labelsHtml = renderSpotLabels(analysisForDetails);
    // conditional_reason in v2.0 entfernt — primary_caution wird via renderSpotLabels gerendert.
    const assessmentsHtml = renderAssessmentSections(spot, analysisForDetails);
    const hasCoords = spot.lat != null && spot.lon != null;

    const miniMapInner = hasCoords
      ? `<div class="bf-spot-minimap" data-lat="${spot.lat}" data-lon="${spot.lon}" data-spot="${escapeHtml(spot.spot)}" data-href="${escapeHtml(mapHref)}" data-windrichtung="${escapeHtml(spot.windrichtung || "")}" data-safety="${escapeHtml(spot.safety_status || "")}" data-rating="${rating}" data-band="${escapeHtml(band)}"></div>`
      : `<div class="bf-spot-minimap bf-spot-minimap--nodata">${wcT('js.spot.no_coords')}</div>`;

    const shareRatingAttr = rating > 0 && band !== "red" ? String(rating) : "";
    const shareBtn = `<button type="button" class="bf-share-btn bf-share-btn--spot"
             data-share-kind="spot"
             data-share-region="${escapeHtml(spot.region_id || "")}"
             data-share-region-name="${escapeHtml(spot.region_name || "")}"
             data-share-spot="${escapeHtml(spot.spot)}"
             data-share-rating="${shareRatingAttr}"
             title="Startplatz teilen" aria-label="Startplatz teilen">${window.wingcastShareIconSVG || "⇪"}</button>`;
    // RATING_ARCHITECTURE v2.1 — Farbintensität skaliert linear mit experience_rating (1-5).
    // Premium-Marker: safe + rating=5 (xc_tag/Klassiker) → violett (siehe shared-glyph.displayBand).
    const fillNorm = (rating > 0 && band !== "red" && band !== "no_data") ? rating / 5 : 0;
    const G2 = window.wingcastGlyph;
    const visBand = (G2 && G2.displayBand) ? G2.displayBand(band, rating) : band;
    const visCls = "safety-" + visBand;
    // Rating-Tint fuer Spot-Hintergrund — gleiche Palette wie Region-Pill,
    // aber sehr subtil. Bg basiert auf der saturierten Border-Farbe (nicht auf
    // dem hellen Fill), damit auch niedrige Ratings sichtbar sind. Alpha
    // skaliert mit Rating.
    const spotTint = regionPillSpec({ safety_band: band, experience_rating: rating });
    let spotStyle = `--bf-rating-fill: ${fillNorm.toFixed(2)};`;
    if (spotTint) {
      const tintSrc = spotTint.border || spotTint.hex;
      const bgAlpha = 0.07 + fillNorm * 0.13; // rating 1 ~0.10, rating 5 ~0.20
      const borderAlpha = 0.35 + fillNorm * 0.55; // rating 1 ~0.46, rating 5 ~0.90
      spotStyle += ` background: ${hexToRgba(tintSrc, bgAlpha)}; border-left-color: ${hexToRgba(tintSrc, borderAlpha)};`;
    }
    return `
      <li class="bf-spot ${visCls}" data-band="${band}" data-display-band="${visBand}" data-stars="${stars}" data-rating="${rating}" style="${spotStyle}">
        <div class="bf-spot-toggle" role="button" tabindex="0" aria-expanded="false">
          <div class="bf-spot-row">
            <span class="bf-spot-glyph" aria-hidden="true">${glyphHtml}</span>
            <span class="bf-spot-name">${escapeHtml(spot.spot)}</span>
            <span class="bf-spot-spacer"></span>
            <a class="bf-spot-map-link" href="${escapeHtml(mapHref)}" title="Karte">📍</a>
            ${shareBtn}
            <span class="bf-spot-chevron" aria-hidden="true">▾</span>
          </div>
          ${statusBar}
          ${scoreBar}
        </div>
        <div class="bf-spot-divider"></div>
        <div class="bf-spot-details" hidden>
          <div class="bf-detail-top">
            ${labelsHtml ? `<div class="bf-detail-labels">${labelsHtml}</div>` : ""}
          </div>
          ${assessmentsHtml}
          <div class="bf-detail-mapmeteo-row">
            <section class="bf-detail-mapblock">
              <h4 class="bf-detail-title"><span class="bf-detail-icon">🗺</span>Startplatz</h4>
              ${miniMapInner}
            </section>
            <section class="bf-detail-meteoblock">
              <h4 class="bf-detail-title"><span class="bf-detail-icon">📈</span>${wcT('js.meteogram.title')}</h4>
              <div class="bf-spot-meteogram" data-spot="${escapeHtml(spot.spot)}" data-date="${escapeHtml(spot.date || "")}">
                <div class="bf-meteogram-toolbar">
                  <button type="button" class="bf-meteogram-numbers-toggle" data-meteogram-numbers
                          aria-pressed="${state.showNumbers ? "true" : "false"}"
                          title="${wcT('js.meteogram.numbers_toggle')}">
                    <span class="bf-meteogram-numbers-toggle-icon" aria-hidden="true">123</span>
                    <span>${wcT('js.meteogram.numbers')}</span>
                  </button>
                </div>
                <div class="bf-meteogram-chart"></div>
              </div>
            </section>
          </div>
        </div>
      </li>
    `;
  }

  // ── Spot Detail Sections ────────────────────────────────────

  // ── Tag-System v4 — siehe docs/TAGS.md ────────────────────────────
  // Single Source of Truth: analysis.tags[] + analysis.start_window[]
  // (deterministisch im Backend gebaut). Frontend rendert nur.

  // Severity-Reihenfolge: STOP > WARN (Sicherheit) > REDUCER (Fliegbarkeits-
  // Minderer) > GOOD (Pluspunkte). Siehe docs/TAGS.md.
  const TAG_SEVERITY_ORDER = ["stop", "warn", "reducer", "good"];
  const TAG_SEVERITY_LABEL = {
    stop: "STOP", warn: "WARN", reducer: "Reducer", good: "GOOD",
  };
  const TAG_SEVERITY_ICON = {
    stop: "⛔", warn: "⚠", reducer: "↓", good: "✓",
  };
  const TAG_TOPIC_ORDER = [
    "WIND_GROUND", "WIND_ALOFT", "FOEHN", "RAIN", "THUNDERSTORM",
    "CLOUDS", "BASE", "THERMAL", "XC", "INVERSION", "WINDOW",
    "SUNSHINE", "CONVERGENCE", "TURBULENCE",
  ];
  const WINDOW_STATE_LABEL = {
    startbar: wcT("js.window.state_startbar"),
    sportlich: wcT("js.window.state_sportlich"),
    blockiert: wcT("js.window.state_blockiert"),
    neutral: wcT("js.window.state_neutral"),
  };

  function _topicSortKey(topic) {
    const idx = TAG_TOPIC_ORDER.indexOf(topic);
    return idx === -1 ? 999 : idx;
  }

  // Fester Anzeige-Rahmen 06:00–21:00 — Pilot soll IMMER den ganzen Flug-Tag
  // sehen (gleiche horizontale Achse Tag fuer Tag, gleiche Spot fuer Spot).
  // Fehlende Stunden im Backend-Output werden als "neutral" aufgefuellt.
  const WINDOW_HOUR_START = 6;
  const WINDOW_HOUR_END = 21; // exklusiv — letzte gezeigte Stunde ist 20

  function renderStartWindow(startWindow) {
    if (!Array.isArray(startWindow)) return "";
    const byHour = {};
    for (const e of startWindow) {
      if (!e || typeof e.hour !== "number") continue;
      byHour[e.hour] = e.state || "neutral";
    }
    const sorted = [];
    for (let h = WINDOW_HOUR_START; h < WINDOW_HOUR_END; h++) {
      sorted.push({ hour: h, state: byHour[h] || "neutral" });
    }

    // Laengsten zusammenhaengenden Run pro State berechnen.
    function longestRun(targetState) {
      let best = { len: 0, start: null, end: null };
      let cur = { state: null, len: 0, start: null, end: null };
      for (const e of sorted) {
        if (e.state === cur.state) { cur.len += 1; cur.end = e.hour; }
        else {
          if (cur.state === targetState && cur.len > best.len) best = { ...cur };
          cur = { state: e.state, len: 1, start: e.hour, end: e.hour };
        }
      }
      if (cur.state === targetState && cur.len > best.len) best = { ...cur };
      return best;
    }
    const bestStartbar = longestRun("startbar");
    const bestSportlich = longestRun("sportlich");

    // Kontinuierliche Farbleiste: ein Segment pro Stunde, voll-flaechig.
    // Klar, ruhig, ohne ASCII-Glyphs in jeder Zelle.
    const segmentsHtml = sorted.map((e) => {
      const state = e.state || "neutral";
      const hourLbl = String(e.hour).padStart(2, "0");
      const lbl = WINDOW_STATE_LABEL[state] || "—";
      return `<span class="bf-window-seg bf-window-seg--${state}" title="${wcT('js.window.hour_tooltip', { h: hourLbl, lbl: lbl })}"></span>`;
    }).join("");

    // Tick-Achse: nur alle 3 Stunden (06, 09, 12, 15, 18, 21) damit's ruhig wirkt.
    const ticksHtml = sorted.map((e) => {
      const show = e.hour % 3 === 0;
      const lbl = show ? String(e.hour).padStart(2, "0") : "";
      return `<span class="bf-window-tick${show ? " bf-window-tick--major" : ""}">${lbl}</span>`;
    }).join("");

    // Inline-SVG-Icons (Lucide-Style, currentColor) statt Unicode-Glyphs —
    // konsistent mit Brand-Sprache, kein Font-Fallback-Risiko.
    const ICON_CHECK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="20 6 9 17 4 12"/></svg>';
    const ICON_ALERT = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>';
    const ICON_X     = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>';

    // Primaer-Summary: was der Pilot zuerst sehen muss.
    let primaryIcon, primaryText, primaryClass;
    if (bestStartbar.len > 0) {
      const s = String(bestStartbar.start).padStart(2, "0");
      const e = String(bestStartbar.end + 1).padStart(2, "0");
      primaryIcon = ICON_CHECK;
      primaryClass = "is-good";
      primaryText = wcT('js.window.time_range', { s: s, e: e });
    } else if (bestSportlich.len > 0) {
      const ss = String(bestSportlich.start).padStart(2, "0");
      const ee = String(bestSportlich.end + 1).padStart(2, "0");
      primaryIcon = ICON_ALERT;
      primaryClass = "is-warn";
      primaryText = wcT('js.window.sporty_only', { s: ss, e: ee });
    } else {
      primaryIcon = ICON_X;
      primaryClass = "is-bad";
      primaryText = wcT('js.window.not_launchable');
    }
    const durationHtml = bestStartbar.len > 0
      ? `<span class="bf-window-duration">${bestStartbar.len} h</span>`
      : (bestSportlich.len > 0
          ? `<span class="bf-window-duration">${bestSportlich.len} h</span>`
          : "");

    // Sekundaere Info (nur wenn Startbar UND Sportlich vorhanden)
    let secondary = "";
    if (bestStartbar.len > 0 && bestSportlich.len > 0) {
      const ss = String(bestSportlich.start).padStart(2, "0");
      const ee = String(bestSportlich.end + 1).padStart(2, "0");
      secondary = `<div class="bf-window-secondary"><span class="bf-window-dot bf-window-dot--sportlich"></span>${wcT('js.window.sporty_secondary', { s: ss, e: ee })}</div>`;
    }

    return `
      <section class="bf-window">
        <header class="bf-window-head">
          <span class="bf-window-title">Startfenster</span>
          <span class="bf-window-summary bf-window-summary--${primaryClass}">
            <span class="bf-window-summary-icon" aria-hidden="true">${primaryIcon}</span>
            <span class="bf-window-summary-text">${escapeHtml(primaryText)}</span>
            ${durationHtml}
          </span>
        </header>
        <div class="bf-window-bar" role="img" aria-label="Startfenster-Verlauf ueber den Tag">${segmentsHtml}</div>
        <div class="bf-window-axis" aria-hidden="true">${ticksHtml}</div>
        ${secondary}
      </section>
    `;
  }

  // SVG-Icons fuer Niederschlags-Coverage-Klassen. Eigenes Icon-Set damit
  // wir unabhaengig von Emoji-Rendering sind und konsistent in jedem
  // Browser/Email-Client aussehen. Tropfen-Cluster mit zunehmender Dichte:
  //   widespread (flaechig)  → 3 grosse Tropfen, eng beieinander
  //   scattered  (verstreut) → 2 Tropfen mit Luecke
  //   isolated   (vereinzelt) → 1 Tropfen
  // Stroke + Fill in Tag-Severity-Farbe (rot/orange via CSS-Variable).
  function rainGlyphSvg(klass) {
    const W = 36, H = 14;
    // drop(cx): vereinfachter Wassertropfen mit Spitze oben, breit unten.
    const drop = (cx) =>
      `<path d="M ${cx} 1.5
                C ${cx-3.2} 5, ${cx-3.6} 8, ${cx-3.6} 9.5
                A 3.6 3.6 0 1 0 ${cx+3.6} 9.5
                C ${cx+3.6} 8, ${cx+3.2} 5, ${cx} 1.5 Z"
              fill="currentColor" opacity="0.85"/>`;
    let drops = "";
    if (klass === "widespread") {
      drops = drop(6) + drop(18) + drop(30);
    } else if (klass === "scattered") {
      drops = drop(10) + drop(26);
    } else if (klass === "isolated") {
      drops = drop(18);
    } else {
      drops = drop(18);  // default Tropfen
    }
    return `<svg class="bf-rain-glyph" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}"
             role="img" aria-label="Coverage ${klass || 'regen'}">${drops}</svg>`;
  }

  function renderTagGroups(tags) {
    if (!Array.isArray(tags) || !tags.length) return "";
    // Group by severity. "info" als Legacy-Severity wird auf "reducer" gemappt
    // (siehe docs/TAGS.md, Migration 2026-05-05).
    const byLevel = { stop: [], warn: [], reducer: [], good: [] };
    for (const t of tags) {
      if (!t) continue;
      const sev = t.severity === "info" ? "reducer" : t.severity;
      if (!byLevel[sev]) continue;
      byLevel[sev].push(t);
    }
    // Sort each group by topic order
    for (const sev of TAG_SEVERITY_ORDER) {
      byLevel[sev].sort((a, b) => _topicSortKey(a.topic) - _topicSortKey(b.topic));
    }

    const groupsHtml = TAG_SEVERITY_ORDER
      .filter((sev) => byLevel[sev].length > 0)
      .map((sev) => {
        const rowsHtml = byLevel[sev].map((t) => {
          // RAIN-Tag bekommt SVG-Glyph (Tropfen-Cluster) vor dem Klassen-Label.
          let valueInner = escapeHtml(t.value || "");
          if (t.topic === "RAIN" && t.rain_class) {
            valueInner = rainGlyphSvg(t.rain_class) + " " + valueInner;
          }
          const value = t.value || t.rain_class ? `<span class="bf-tag-value">${valueInner}</span>` : `<span class="bf-tag-value"></span>`;
          const time = t.time ? `<span class="bf-tag-time">${escapeHtml(t.time)}</span>` : `<span class="bf-tag-time"></span>`;
          return `<div class="bf-tag-row">
            <span class="bf-tag-topic">${escapeHtml(t.label || t.topic)}</span>
            ${value}
            ${time}
          </div>`;
        }).join("");
        return `<div class="bf-tag-group bf-tag-group--${sev}">
          <div class="bf-tag-group-header">
            <span class="bf-tag-group-icon" aria-hidden="true">${TAG_SEVERITY_ICON[sev]}</span>
            <span class="bf-tag-group-label">${TAG_SEVERITY_LABEL[sev]}</span>
          </div>
          <div class="bf-tag-rows">${rowsHtml}</div>
        </div>`;
      })
      .join("");

    return groupsHtml;
  }

  function renderSpotLabels(analysis) {
    if (!analysis || typeof analysis !== "object") return "";
    const a = analysis;
    // V4: Tag-System aus Backend (siehe docs/TAGS.md). Bevorzugt analysis.tags
    // und analysis.start_window. Fallback: alte Logik (caution_notes etc.) NICHT
    // mehr genutzt — Backend befuellt jeden Cache-Eintrag mit tags + start_window.
    const tags = Array.isArray(a.tags) ? a.tags : (a.safety && Array.isArray(a.safety.tags) ? a.safety.tags : []);
    const startWindow = Array.isArray(a.start_window) ? a.start_window : (a.safety && Array.isArray(a.safety.start_window) ? a.safety.start_window : []);

    const windowHtml = renderStartWindow(startWindow);
    const tagsHtml = renderTagGroups(tags);

    if (!windowHtml && !tagsHtml) return "";
    return windowHtml + tagsHtml;
  }

  function cleanAssessmentText(value) {
    const text = String(value == null ? "" : value).trim();
    if (!text || text === "0" || text === "null" || text === "None") return "";
    return text;
  }

  function renderAssessmentSections(spot, analysis) {
    const a = analysis && typeof analysis === "object" ? analysis : {};
    const saf = a.safety || {};
    const fly = a.flyability || {};

    const safetyText = cleanAssessmentText(spot.safety_feedback || a.safety_feedback || saf.summary);
    const flyText = cleanAssessmentText(spot.flyability_feedback || a.recommendation || fly.recommendation);

    const sections = [
      { key: "safety", label: wcT("js.assess.safety"), text: safetyText },
      { key: "fly", label: wcT("js.assess.flight"), text: flyText },
    ].filter((s) => s.text);

    if (!sections.length) return "";

    const debugHtml = renderDebugNotes(spot);

    return `<div class="bf-detail-assessments">${sections.map((s) => `
      <details class="bf-assessment bf-assessment--${s.key}">
        <summary class="bf-assessment-toggle">
          <span class="bf-assessment-name">${s.label}</span>
          <span class="bf-assessment-spacer"></span>
          <span class="bf-assessment-chevron" aria-hidden="true">▾</span>
        </summary>
        <div class="bf-assessment-body">${escapeHtml(s.text)}</div>
      </details>
    `).join("")}${debugHtml}</div>`;
  }

  function renderDebugNotes(spot) {
    if (!window.wingcastDebugMode) return "";
    const hn = spot.hazard_notes;
    const fn = spot.flyability_notes;
    if (!hn && !fn) return "";

    const rows = (obj, label) => {
      if (!obj || typeof obj !== "object") return "";
      const entries = Object.entries(obj);
      if (!entries.length) return "";
      return `<div class="bf-debug-group">
        <div class="bf-debug-group-label">${escapeHtml(label)}</div>
        ${entries.map(([k, v]) => `
          <div class="bf-debug-row">
            <span class="bf-debug-key">${escapeHtml(k)}</span>
            <span class="bf-debug-val">${escapeHtml(v || "—")}</span>
          </div>`).join("")}
      </div>`;
    };

    return `
      <details class="bf-assessment bf-assessment--debug">
        <summary class="bf-assessment-toggle">
          <span class="bf-assessment-name">🔍 Debug: Hazard &amp; Flyability Notes</span>
          <span class="bf-assessment-spacer"></span>
          <span class="bf-assessment-chevron" aria-hidden="true">▾</span>
        </summary>
        <div class="bf-assessment-body bf-debug-notes">
          ${rows(hn, "Hazard Notes (Safety)")}
          ${rows(fn, "Flyability Notes")}
        </div>
      </details>`;
  }

  function synthesizeAnalysis(spot) {
    if (!spot) return null;
    return {
      safety_status: spot.safety_status || "",
      experience_rating: spot.experience_rating || 0,
      flight_type: spot.flight_type || "",
      flight_duration_estimate: spot.flight_duration || "",
      xc_potential: spot.xc_potential || "",
      best_window: spot.best_window || "",
      peak_climb_rate: spot.peak_climb_rate || 0,
      recommendation: spot.recommendation || "",
      safety_feedback: spot.safety_feedback || "",
      is_conditional: !!spot.is_conditional,
    };
  }

  // ── Spot Toggle (expand/collapse) ───────────────────────────

  function handleSpotToggle(ev) {
    if (ev.target.closest(".bf-share-btn")) return;
    if (ev.target.closest(".bf-spot-map-link")) return;
    if (ev.target.closest(".bf-spot-minimap")) return;
    if (ev.target.closest(".bf-spot-meteogram")) return;
    const toggle = ev.target.closest(".bf-spot-toggle");
    if (!toggle) return;
    const li = toggle.closest(".bf-spot");
    if (!li) return;
    const details = li.querySelector(".bf-spot-details");
    if (!details) return;
    const isOpen = li.classList.toggle("is-expanded");
    toggle.setAttribute("aria-expanded", String(isOpen));
    if (isOpen) {
      markExpandHintSeen();
      details.removeAttribute("hidden");
      const miniMap = details.querySelector(".bf-spot-minimap");
      if (miniMap && !miniMap.classList.contains("bf-spot-minimap--nodata")) initMiniMap(miniMap);
      const meteogramEl = details.querySelector(".bf-spot-meteogram");
      if (meteogramEl) initMeteogram(meteogramEl);
      // Smooth scroll the expanded spot into view
      requestAnimationFrame(() => {
        const rect = li.getBoundingClientRect();
        if (rect.top < 0 || rect.bottom > window.innerHeight) {
          li.scrollIntoView({ behavior: "smooth", block: "start" });
        }
      });
    } else {
      details.setAttribute("hidden", "");
    }
  }

  function handleSpotKeydown(ev) {
    if (ev.key !== "Enter" && ev.key !== " ") return;
    const toggle = ev.target.closest(".bf-spot-toggle");
    if (!toggle || toggle !== ev.target) return;
    ev.preventDefault();
    handleSpotToggle(ev);
  }

  // ── Region Toggle (expand/collapse) ─────────────────────────

  function handleBulkToggle(ev) {
    const btn = ev.target.closest(".bf-bulk-toggle");
    if (!btn) return;
    ev.preventDefault();
    ev.stopPropagation();
    const expand = btn.dataset.bulkAction === "expand";
    const contentEl = $("bfContent");
    if (!contentEl) return;
    const regions = contentEl.querySelectorAll(".bf-region");
    regions.forEach((region) => {
      const rid = region.dataset.regionId || "";
      const head = region.querySelector(".bf-region-head");
      region.classList.toggle("is-collapsed", !expand);
      if (head) head.setAttribute("aria-expanded", String(expand));
      if (expand) state.collapsedRegions.delete(rid);
      else state.collapsedRegions.add(rid);
    });
    saveCollapsedRegions(state.collapsedRegions);
    markExpandHintSeen();
    // Label des Buttons fuer naechsten Toggle-Zustand aktualisieren.
    btn.dataset.bulkAction = expand ? "collapse" : "expand";
    const icon = btn.querySelector(".bf-bulk-toggle-icon");
    const label = btn.querySelector(".bf-bulk-toggle-label");
    if (icon)  icon.textContent  = expand ? "▴" : "▾";
    if (label) label.textContent = expand ? wcT("js.bulk.collapse_all") : wcT("js.bulk.expand_all");
    btn.setAttribute("aria-label", label ? label.textContent : "");
  }

  function handleRegionToggle(ev) {
    if (ev.target.closest(".bf-share-btn")) return;
    if (ev.target.closest(".bf-spot")) return;
    if (ev.target.closest(".bf-bulk-toggle")) return;
    const head = ev.target.closest(".bf-region-head");
    if (!head) return;
    const region = head.closest(".bf-region");
    if (!region) return;
    const rid = region.dataset.regionId || "";
    const willCollapse = !region.classList.contains("is-collapsed");
    region.classList.toggle("is-collapsed", willCollapse);
    head.setAttribute("aria-expanded", String(!willCollapse));
    if (willCollapse) state.collapsedRegions.add(rid);
    else state.collapsedRegions.delete(rid);
    saveCollapsedRegions(state.collapsedRegions);
    markExpandHintSeen();
  }

  function handleRegionKeydown(ev) {
    if (ev.key !== "Enter" && ev.key !== " ") return;
    const head = ev.target.closest(".bf-region-head");
    if (!head || head !== ev.target) return;
    ev.preventDefault();
    handleRegionToggle(ev);
  }

  // ── Meteogram numbers toggle ────────────────────────────────

  function handleNumbersToggle(ev) {
    const btn = ev.target.closest("[data-meteogram-numbers]");
    if (!btn) return;
    ev.preventDefault();
    ev.stopPropagation();
    state.showNumbers = !state.showNumbers;
    saveShowNumbers(state.showNumbers);
    document.body.classList.toggle("bf-show-numbers", state.showNumbers);
    document.querySelectorAll("[data-meteogram-numbers]").forEach((b) => {
      b.setAttribute("aria-pressed", String(state.showNumbers));
    });
    // Re-render every currently-open meteogram in place.
    document.querySelectorAll(".bf-spot.is-expanded .bf-spot-meteogram").forEach((el) => {
      el._flyInited = false;
      const chartEl = el.querySelector(".bf-meteogram-chart");
      if (chartEl) chartEl.innerHTML = "";
      initMeteogram(el);
    });
  }

  function handleShareClick(ev) {
    const btn = ev.target.closest(".bf-share-btn");
    if (!btn) return;
    ev.preventDefault();
    ev.stopPropagation();
    const kind = btn.dataset.shareKind;
    const regionId = btn.dataset.shareRegion || "";
    const regionName = btn.dataset.shareRegionName || "";
    const spotName = btn.dataset.shareSpot || "";
    const rating = btn.dataset.shareRating || "";
    const dayIdx = state.selectedDayIdx || 0;
    let title, text;
    if (kind === "spot") {
      const rtxt = rating && rating !== "—" ? wcT('js.share.flyability_suffix', { rating: rating }) : "";
      title = `${spotName}${rtxt}`;
      text = `${spotName}${regionName ? " (" + regionName + ")" : ""}${rtxt}${wcT('js.share.brand_suffix')}`;
    } else {
      const rtxt = rating && rating !== "—" ? wcT('js.share.flyability_suffix', { rating: rating }) : "";
      title = `${regionName || wcT("js.share.region")}${rtxt}`;
      text = `${regionName || wcT("js.share.region")}${rtxt}${wcT('js.share.brand_suffix')}`;
    }
    if (typeof window.wingcastShare === "function") {
      window.wingcastShare({
        region_id: regionId,
        day_idx: dayIdx,
        spot: kind === "spot" ? spotName : undefined,
        title: title,
        text: text,
      });
    }
  }

  // ── Mini Map ────────────────────────────────────────────────

  const _bfIcon = { uid: 0 };

  // Liefert Array von [start,end]-Arcs. Unterstuetzt PGE-Mehrfach-Sektoren
  // ('O-SO-S-SW-W', Wraparound 'NW-N-NO', disjoint 'S/N', 'NO-O/W-NW').
  function bfGetDirAngles(dirStr) {
    if (!dirStr) return null;
    const dirs = {
      'N':0,'NNO':22.5,'NNE':22.5,'NO':45,'NE':45,'ONO':67.5,'ENE':67.5,
      'O':90,'E':90,'OSO':112.5,'ESE':112.5,'SO':135,'SE':135,'SSO':157.5,'SSE':157.5,
      'S':180,'SSW':202.5,'SW':225,'WSW':247.5,
      'W':270,'WNW':292.5,'NW':315,'NNW':337.5,
    };
    const arcs = [];
    const disjoint = dirStr.toUpperCase().split('/');
    for (const run of disjoint) {
      const r = run.trim();
      if (!r) continue;
      const parts = r.split('-');
      const angles = [];
      for (const p of parts) {
        const a = dirs[p.trim()];
        if (a !== undefined) angles.push(a);
      }
      if (!angles.length) continue;
      // parts kommen clockwise-geordnet aus spots._sectors_to_windrichtung
      // (PGE_SECTOR_ORDER). Span = anzahl-sektoren * 45°, beginnend 22.5° vor
      // dem ersten Mittelpunkt. So bleibt eine Wraparound-Sequenz (z.B.
      // 'NW-N-NE') als echtes Wraparound erhalten (292.5° -> 427.5°), und
      // eine breite Nicht-Wraparound-Sequenz (z.B. 'O-SO-S-SW-W') wird NICHT
      // faelschlich als Wraparound interpretiert (67.5° -> 292.5°).
      const start = angles[0] - 22.5;
      const end = start + angles.length * 45;
      arcs.push([start, end]);
    }
    return arcs.length ? arcs : null;
  }

  // Mini-Map Marker-Style nutzt direkt regionPillSpec → identische Rating-Tint-
  // Palette wie Region-Pill, Spot-Bg und Karten-Polygon.
  function bfSafetyRatingStyle(safety, rating) {
    if (safety === 'default' || safety === 'no_data' || !safety) {
      return { fill: safety === 'no_data' ? '#9ca3af' : '#6b7280', stroke: safety === 'no_data' ? '#6b7280' : '#4b5563', glow: null, showStripes: false, showWarning: false };
    }
    if (safety === 'error') return { fill: '#f87171', stroke: '#b91c1c', glow: null, showStripes: false, showWarning: false };
    if (safety === 'not_safe') return { fill: '#dc2626', stroke: '#991b1b', glow: null, showStripes: true, showWarning: false };
    const sp = regionPillSpec({ safety_band: safety === 'safe' ? 'green' : 'amber', experience_rating: rating });
    if (!sp) return { fill: '#9ca3af', stroke: '#6b7280', glow: null, showStripes: false, showWarning: false };
    const glow = (rating >= 5) ? hexToRgba(sp.hex, 0.45) : null;
    return { fill: sp.hex, stroke: sp.border, glow, showStripes: false, showWarning: safety === 'conditional' };
  }

  function bfCreateSpotIcon(windrichtung, safety, ratingOrQuality) {
    const uid = ++_bfIcon.uid;
    // ratingOrQuality kann Zahl (neu, rating 1-5) oder Legacy-String (gray/green/violet) sein.
    let rating = 0;
    if (typeof ratingOrQuality === 'number') rating = ratingOrQuality;
    else if (typeof ratingOrQuality === 'string') {
      const n = parseInt(ratingOrQuality, 10);
      if (isFinite(n)) rating = n;
      else if (ratingOrQuality === 'violet') rating = 5;
      else if (ratingOrQuality === 'green') rating = 3;
      else if (ratingOrQuality === 'gray') rating = 1;
    }
    const style = bfSafetyRatingStyle(safety, rating);
    const sz = 44, c = sz / 2, r = 7;
    let h = '<svg width="'+sz+'" height="'+sz+'" viewBox="0 0 '+sz+' '+sz+'">';

    if (style.showStripes) {
      h += '<defs><pattern id="bfs'+uid+'" width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="4" stroke="rgba(255,255,255,0.2)" stroke-width="1.5"/></pattern></defs>';
    }

    const arcs = bfGetDirAngles(windrichtung);
    if (arcs && arcs.length) {
      const si = r+1, so = r+9;
      for (const angles of arcs) {
        const sr = (angles[0]-90)*Math.PI/180, er = (angles[1]-90)*Math.PI/180;
        const ix1=c+si*Math.cos(sr), iy1=c+si*Math.sin(sr), ix2=c+si*Math.cos(er), iy2=c+si*Math.sin(er);
        const ox1=c+so*Math.cos(sr), oy1=c+so*Math.sin(sr), ox2=c+so*Math.cos(er), oy2=c+so*Math.sin(er);
        const la = (angles[1]-angles[0])>180?1:0;
        h += '<path d="M '+ox1+' '+oy1+' A '+so+' '+so+' 0 '+la+' 1 '+ox2+' '+oy2+' L '+ix2+' '+iy2+' A '+si+' '+si+' 0 '+la+' 0 '+ix1+' '+iy1+' Z" fill="'+style.stroke+'" opacity="0.5" />';
      }
    }

    if (style.glow) {
      h += '<circle cx="'+c+'" cy="'+c+'" r="'+(r+4)+'" fill="'+style.glow+'" />';
      h += '<circle cx="'+c+'" cy="'+c+'" r="'+(r+7)+'" fill="'+style.glow.replace('0.45','0.15')+'" />';
    }
    h += '<circle cx="'+c+'" cy="'+c+'" r="'+r+'" fill="'+style.fill+'" stroke="'+style.stroke+'" stroke-width="1.5" />';
    if (style.showStripes) h += '<circle cx="'+c+'" cy="'+c+'" r="'+r+'" fill="url(#bfs'+uid+')" />';
    if (style.showWarning) {
      const tx=c+r-1, ty=c-r+1;
      h += '<polygon points="'+tx+','+(ty-5)+' '+(tx-4)+','+(ty+3)+' '+(tx+4)+','+(ty+3)+'" fill="#eab308" stroke="#854d0e" stroke-width="0.5" />';
      h += '<text x="'+tx+'" y="'+(ty+2.5)+'" text-anchor="middle" fill="#854d0e" font-size="6" font-weight="bold" font-family="sans-serif">!</text>';
    }
    h += '</svg>';
    return L.divIcon({ html: h, className: 'custom-spot-marker', iconSize: [sz,sz], iconAnchor: [c,c], tooltipAnchor: [0,-r-6] });
  }

  function initMiniMap(el) {
    if (!el || el._flyInited) return;
    el._flyInited = true;
    const lat = parseFloat(el.dataset.lat), lon = parseFloat(el.dataset.lon);
    const spotName = el.dataset.spot || "";
    const href = el.dataset.href || "";

    if (typeof L === "undefined" || !isFinite(lat) || !isFinite(lon)) {
      el.innerHTML = '<div class="bf-minimap-fallback">' + wcT('js.map.unavailable') + '</div>';
      return;
    }
    try {
      const mapObj = L.map(el, {
        center: [lat, lon], zoom: 13,
        dragging: true, touchZoom: true, scrollWheelZoom: true, doubleClickZoom: true,
        boxZoom: true, keyboard: true, zoomControl: true, attributionControl: false,
      });
      L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
        subdomains: 'abcd', maxZoom: 18,
      }).addTo(mapObj);

      const icon = bfCreateSpotIcon(el.dataset.windrichtung || "", el.dataset.safety || "", parseInt(el.dataset.rating, 10) || 0);
      L.marker([lat, lon], { icon }).addTo(mapObj).bindTooltip(spotName, { direction: "top" });

      if (href) {
        const ctrl = L.control({ position: "topright" });
        ctrl.onAdd = function () {
          const a = L.DomUtil.create("a", "bf-map-openlink");
          a.href = href;
          a.innerHTML = "↗ Karte";
          L.DomEvent.disableClickPropagation(a);
          L.DomEvent.disableScrollPropagation(a);
          return a;
        };
        ctrl.addTo(mapObj);
      }

      requestAnimationFrame(() => { try { mapObj.invalidateSize(); } catch (_) {} });
      setTimeout(() => { try { mapObj.invalidateSize(); } catch (_) {} }, 250);
    } catch (e) {
      console.warn("[briefing] mini-map init failed", e);
      el.innerHTML = '<div class="bf-minimap-fallback">' + wcT('js.map.unavailable') + '</div>';
    }
  }

  // ── Meteogram ───────────────────────────────────────────────

  const _mgCache = Object.create(null);

  function fetchMeteogramData(spotName) {
    if (_mgCache[spotName]) return _mgCache[spotName];
    const p = Promise.all([
      fetch("/api/weather/" + encodeURIComponent(spotName)).then((r) => r.json()),
      fetch("/api/altitude-wind/" + encodeURIComponent(spotName)).then((r) => r.json()),
    ]).then((res) => ({ weather: res[0], altWind: res[1] }));
    _mgCache[spotName] = p;
    p.catch(() => { delete _mgCache[spotName]; });
    return p;
  }

  function initMeteogram(el) {
    if (!el || el._flyInited) return;
    el._flyInited = true;
    const spotName = el.dataset.spot || "";
    const dateStr = el.dataset.date || "";
    const chartEl = el.querySelector(".bf-meteogram-chart");
    if (!chartEl || !spotName || !dateStr) return;

    if (typeof window.Meteogram === "undefined" || typeof d3 === "undefined") {
      chartEl.innerHTML = '<div class="bf-meteogram-fallback">' + escapeHtml(wcT('js.meteogram.unavailable')) + '</div>';
      return;
    }
    chartEl.innerHTML = '<div class="bf-meteogram-loading">' + escapeHtml(wcT('js.meteogram.loading')) + '</div>';

    fetchMeteogramData(spotName)
      .then((data) => {
        const weather = data.weather || {};
        const altWind = data.altWind || {};
        if (weather.error) { chartEl.innerHTML = '<div class="bf-meteogram-fallback">' + escapeHtml(weather.error) + '</div>'; return; }
        if (altWind.error) { chartEl.innerHTML = '<div class="bf-meteogram-fallback">' + escapeHtml(altWind.error) + '</div>'; return; }
        const wxDay = (weather.data || {})[dateStr] || {};
        const altProfiles = (altWind.data || {})[dateStr] || [];
        if (!wxDay || !altProfiles.length) {
          chartEl.innerHTML = '<div class="bf-meteogram-fallback">' + escapeHtml(wcT('js.meteogram.no_data_for', { date: dateStr })) + '</div>';
          return;
        }
        const altDay = { profiles: [] };
        altProfiles.forEach((p) => {
          const hh = (p.hour < 10 ? "0" : "") + p.hour;
          altDay.profiles.push({ time: dateStr + "T" + hh + ":00:00", levels: p.profiles || [] });
        });
        const groundWindByTime = {};
        ((altWind.ground_wind && altWind.ground_wind[dateStr]) || []).forEach((g) => {
          const hh = (g.hour < 10 ? "0" : "") + g.hour;
          groundWindByTime[dateStr + "T" + hh + ":00:00"] = g;
        });
        chartEl.innerHTML = "";
        const tooltipEl = document.getElementById("bfMeteogramTooltip");
        try {
          window.Meteogram.renderChart(chartEl, tooltipEl, wxDay, altDay, {
            elevation: weather.elevation_m,
            windrichtung: weather.windrichtung,
            idealWindMax: weather.ideal_wind_max,
            groundWindByTime: groundWindByTime,
            showNumbers: state.showNumbers,
          });
        } catch (e) {
          console.warn("[briefing] Meteogram failed", e);
          chartEl.innerHTML = '<div class="bf-meteogram-fallback">' + escapeHtml(wcT('js.meteogram.render_error')) + '</div>';
        }
      })
      .catch((err) => {
        console.warn("[briefing] meteogram fetch failed", err);
        chartEl.innerHTML = '<div class="bf-meteogram-fallback">' + escapeHtml(wcT('js.meteogram.data_unavailable')) + '</div>';
      });
  }

  // ── API ─────────────────────────────────────────────────────

  async function loadBriefing() {
    try {
      const res = await fetch("/api/briefing", { cache: "no-store" });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      render(data);
    } catch (err) {
      console.error("[briefing] load failed", err);
      const el = $("bfContent");
      if (el) el.innerHTML = `<div class="bf-content-empty">${escapeHtml(wcT('js.error.prefix', { msg: err.message }))}</div>`;
    }
  }

  async function generateFazit() {
    if (state.generating) return;
    state.generating = true;
    const btn = $("bfGenerateBtn");
    const orig = btn.textContent;
    btn.disabled = true;
    btn.textContent = wcT("js.generating");
    try {
      // POST /api/briefing/generate triggert Wetterlage-Refresh +
      // Fazit-Neugenerierung serverseitig. Die Response enthaelt das neue
      // Fazit, aber NICHT das Wetterlage-Strukturfeld (das landet im Cache).
      // Wir laden danach via loadBriefing() neu — das holt alles frisch
      // inkl. dem neu generierten Wetterlage-Block.
      const res = await fetch("/api/briefing/generate", { method: "POST", headers: { "Content-Type": "application/json" } });
      const data = await res.json();
      if (!data.success) throw new Error(data.error || wcT("js.failed"));
      // Wetterlage-Refresh-Status loggen (kein User-facing Error, Block
      // wird einfach ausgeblendet wenn er nicht generierbar war).
      if (data.wetterlage_refresh && data.wetterlage_refresh !== "ok") {
        console.info("[briefing] wetterlage_refresh:", data.wetterlage_refresh);
      }
      await loadBriefing();
    } catch (err) {
      console.error("[briefing] generate failed", err);
      alert(wcT('js.error.prefix', { msg: err.message }));
    } finally {
      state.generating = false;
      btn.disabled = false;
      btn.textContent = orig;
    }
  }

  // ── Orchestration ───────────────────────────────────────────

  function render(data) {
    state.data = data;
    renderHeader(data);
    // Tabs VOR der Wetterlage: renderDayTabs clampt selectedDayIdx,
    // und renderWetterlage haengt am gewaehlten Tag.
    renderDayTabs(data);
    renderWetterlage(data);
    syncSynopticDate();
    renderFilters(data);
    renderTierFilter();
    renderDayContent();
  }

  // ── Render: Wetterlage ──────────────────────────────────────
  // Block fuer die grossraeumige Synoptik (1x/Tag vom Scheduler generiert,
  // deterministisch + LLM-Prosa). Zeigt die Kurzfassung initial sichtbar;
  // bei Klick auf Toggle wird die Langfassung eingeblendet.

  function renderWetterlage(data) {
    const el = $("bfWetterlage");
    if (!el) return;
    const wl = data.wetterlage;
    const overview = wl && wl.llm_overview ? wl.llm_overview : null;

    // Wenn kein LLM-Overview vorhanden (Refresh fehlgeschlagen,
    // Strukturfeld unvollstaendig, alle Saetze vom Post-Filter verworfen):
    // Block ausblenden — keine Halluzination, kein Fallback-Text.
    if (!overview || !overview.short) {
      el.hidden = true;
      el.innerHTML = "";
      return;
    }

    // Lage-Label: Strukturfeld liefert den kanonischen DE-Wert; Anzeige
    // uebersetzt via i18n ("js.lage.<value>"), Fallback = DE-Wert.
    const lageRaw = (wl.lage_label && wl.lage_label.value) || "";
    const lageLabel = lageRaw
      ? ((window.WC_I18N && window.WC_I18N["js.lage." + lageRaw]) || lageRaw)
      : "";
    const shortText = overview.short || "";
    const longText = overview.long || "";

    // Ein Tages-Eintrag: "Wochentag:" am Zeilenanfang wird als <strong>
    // hervorgehoben, flight_hint (optional) darunter als Pilotensicht-Zeile —
    // visuell deutlich von der Wetterbeschreibung getrennt.
    const dayBlockHtml = (e) => {
      const txt = escapeHtml(e.text);
      const hint = e.flight_hint ? escapeHtml(e.flight_hint) : "";
      const hintHtml = hint
        ? `<p class="bf-wetterlage-hint"><span class="bf-wetterlage-hint-icon" aria-hidden="true">⏵</span> ${hint}</p>`
        : "";
      const m = txt.match(/^(Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday):\s*/);
      const body = m
        ? `<p class="bf-wetterlage-day"><strong>${m[1]}:</strong> ${txt.slice(m[0].length)}</p>`
        : `<p class="bf-wetterlage-lead">${txt}</p>`;
      return `<div class="bf-wetterlage-day-block">${body}${hintHtml}</div>`;
    };

    // Synoptik 2.0: `zones` = 4 Flugwetter-Zonen mit je einem Eintrag pro Tag.
    // Angezeigt wird NUR der gewaehlte Tag (Day-Tabs zuoberst steuern die
    // ganze Seite) — der Tages-Eintrag jeder Zone, immer sichtbar, ohne
    // Toggle. Legacy-Fallback (`long_with_sources`) bleibt fuer alte Caches
    // beim alten Toggle-Verhalten, damit ein noch nicht refreshter Cache den
    // Block nicht leert.
    const zones = Array.isArray(overview.zones)
      ? overview.zones.filter(z => z && Array.isArray(z.days) && z.days.length)
      : [];
    const longEntries = Array.isArray(overview.long_with_sources)
      ? overview.long_with_sources.filter(e => e && e.text)
      : [];

    // Gewaehlten Briefing-Tag auf den Wetterlage-Index abbilden. Die
    // forecast_dates der Wetterlage koennen vom Briefing abweichen (aelterer
    // Cache) — dann gibt es fuer den Tag schlicht keinen Zonen-Text.
    const selDate = selectedDate();
    const wlDates = Array.isArray(wl.forecast_dates) ? wl.forecast_dates : [];
    const wlIdx = selDate ? wlDates.indexOf(selDate) : -1;

    // `short` enthaelt jetzt Synoptik + Flug-Bilanz als EINEN Fliesstext
    // (siehe synoptic_overview.md Skill). Wird als ein Absatz gerendert.
    // Backward-compat: falls ein alter Cache noch flight_outlook hat,
    // haengen wir den Text dran — neue Caches haben das Feld nicht.
    const outlookLegacy = wl.llm_overview && wl.llm_overview.flight_outlook;
    const outlookLegacyText = outlookLegacy && outlookLegacy.text ? outlookLegacy.text : "";
    const summaryParas = [
      shortText ? `<p>${escapeHtml(shortText)}</p>` : "",
      outlookLegacyText ? `<p>${escapeHtml(outlookLegacyText)}</p>` : "",
    ].filter(Boolean).join("");

    let dayHtml = "";
    let legacyHtml = "";
    if (zones.length) {
      if (wlIdx >= 0) {
        dayHtml = zones.map(z => {
          const d = z.days[wlIdx];
          if (!d || !d.text) return "";
          return `
            <section class="bf-wetterlage-zone">
              <h4 class="bf-wetterlage-zone-title">${escapeHtml(z.label || z.zone || "")}</h4>
              ${dayBlockHtml(d)}
            </section>
          `;
        }).join("");
      }
      if (!dayHtml) {
        dayHtml = `<p class="bf-wetterlage-noday">${escapeHtml(wcT("js.wetterlage.no_day"))}</p>`;
      }
    } else if (longEntries.length) {
      legacyHtml = longEntries.map(dayBlockHtml).join("");
    } else if (longText && longText !== shortText) {
      legacyHtml = `<p>${escapeHtml(longText)}</p>`;
    }

    el.hidden = false;
    el.innerHTML = `
      <div class="bf-wetterlage-head">
        <span class="bf-wetterlage-icon" aria-hidden="true">☼</span>
        <span class="bf-wetterlage-label">${escapeHtml(wcT("js.wetterlage.heading"))}${lageLabel ? ` — ${escapeHtml(lageLabel)}` : ""}</span>
        <a class="bf-wetterlage-maplink" href="/synoptik">${escapeHtml(wcT("js.wetterlage.to_map"))} →</a>
      </div>
      <div class="bf-wetterlage-summary">${summaryParas}</div>
      ${dayHtml ? `<div class="bf-wetterlage-long">${dayHtml}</div>` : ""}
      ${legacyHtml ? `
        <button type="button" class="bf-wetterlage-toggle" aria-expanded="${state.wetterlageOpen ? "true" : "false"}">
          ${state.wetterlageOpen ? wcT("js.wetterlage.less") : wcT("js.wetterlage.detail")} <span class="bf-wetterlage-chevron" aria-hidden="true">▾</span>
        </button>
        <div class="bf-wetterlage-long"${state.wetterlageOpen ? "" : " hidden"}>${legacyHtml}</div>
      ` : ""}
    `;
    el.classList.toggle("is-open", !!state.wetterlageOpen);

    const toggle = el.querySelector(".bf-wetterlage-toggle");
    if (toggle && !toggle._wlBound) {
      toggle._wlBound = true;
      toggle.addEventListener("click", () => {
        state.wetterlageOpen = !state.wetterlageOpen;
        const longEl = el.querySelector(".bf-wetterlage-long");
        if (longEl) longEl.hidden = !state.wetterlageOpen;
        toggle.setAttribute("aria-expanded", state.wetterlageOpen ? "true" : "false");
        toggle.firstChild.textContent = (state.wetterlageOpen ? wcT("js.wetterlage.less") : wcT("js.wetterlage.detail")) + " ";
        el.classList.toggle("is-open", state.wetterlageOpen);
      });
    }
  }

  // ── Deep-Link via URL-Params (E-Mail-Briefing -> Dashboard) ─
  // Erwartete Params:
  //   regions=<id1>,<id2>,...  -> ueberschreibt state.filterRegions
  //   day=<N>                  -> waehlt den Tag-Tab mit Index N
  //   spot=<name>              -> ephemerer Focus auf genau diesen Spot
  // Nach Anwendung wird die URL bereinigt, damit Bookmarks/History die
  // Params nicht dauerhaft mitschleppen. Fehlen alle Params -> Fallback
  // auf das bestehende localStorage-Verhalten.
  function parseUrlParams() {
    try {
      const params = new URLSearchParams(window.location.search);
      const regionsParam = params.get("regions");
      const dayParam = params.get("day");
      const spotParam = params.get("spot");
      let touched = false;

      if (regionsParam) {
        const ids = regionsParam.split(",").map(s => s.trim()).filter(Boolean);
        if (ids.length > 0) {
          state.filterRegions = new Set(ids);
          saveRegionFilter(state.filterRegions);
          touched = true;
        }
      }

      if (dayParam !== null) {
        const idx = parseInt(dayParam, 10);
        if (isFinite(idx) && idx >= 0) {
          state.selectedDayIdx = idx;
          saveDayIdx(idx);
          touched = true;
        }
      }

      if (spotParam) {
        state.focusSpot = spotParam.trim();
        touched = true;
      } else {
        state.focusSpot = null;
      }

      if (touched) {
        try {
          history.replaceState({}, "", window.location.pathname);
        } catch (e) { /* ignore */ }
      }
    } catch (e) {
      console.warn("[briefing] URL param parse failed", e);
    }
  }

  function clearFocusSpot() {
    if (!state.focusSpot) return;
    state.focusSpot = null;
    try {
      if (state.data) renderDayContent();
    } catch (e) { /* ignore */ }
  }

  // Expose fuer onclick im Focus-Banner
  window.__bf_clearFocus = clearFocusSpot;

  function resetAllFilters() {
    state.filterRegions = new Set();
    state.safetyFilters = new Set(SAFETY_DEFS.map((t) => t.id));
    state.minRating = 0;
    saveRegionFilter(state.filterRegions);
    saveSafetyFilter(state.safetyFilters);
    saveMinRating(0);
    renderFilters(state.data);
    renderTierFilter();
    renderDayTabs(state.data);
    renderDayContent();
  }
  window.__bf_resetFilters = resetAllFilters;

  // ── Init ────────────────────────────────────────────────────

  function init() {
    parseUrlParams();

    if (state.expandHintSeen) document.body.classList.add("bf-hint-seen");
    if (state.showNumbers) document.body.classList.add("bf-show-numbers");

    const btn = $("bfGenerateBtn");
    if (btn) btn.addEventListener("click", generateFazit);

    const contentEl = $("bfContent");
    if (contentEl) {
      contentEl.addEventListener("click", handleNumbersToggle);
      contentEl.addEventListener("click", handleBulkToggle);
      contentEl.addEventListener("click", handleRegionToggle);
      contentEl.addEventListener("keydown", handleRegionKeydown);
      contentEl.addEventListener("click", handleSpotToggle);
      contentEl.addEventListener("keydown", handleSpotKeydown);
      contentEl.addEventListener("click", handleShareClick);
    }

    loadBriefing();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
