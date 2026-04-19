/* ══════════════════════════════════════════════════════════════
   Flychat – Flugwetter Dashboard
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
      const months = ["Januar","Februar","Maerz","April","Mai","Juni","Juli","August","September","Oktober","November","Dezember"];
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

  const LS_REGION_FILTER_KEY = "flychat.briefing.regionFilter";
  const LS_DAY_IDX_KEY = "flychat.briefing.dayIdx";

  let state = {
    data: null,
    generating: false,
    filterRegions: loadRegionFilter(),
    selectedDayIdx: loadDayIdx(),
    fazitOpen: false,
    mapVisible: false,
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

  function regionPassesFilter(regionId) {
    if (!state.filterRegions || state.filterRegions.size === 0) return true;
    return state.filterRegions.has(regionId || "unknown");
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
    const spots = day.top_spots || [];
    if (!state.filterRegions || state.filterRegions.size === 0) return spots;
    return spots.filter((s) => regionPassesFilter(s.region_id));
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

  // ── Render: Fazit ───────────────────────────────────────────

  function renderFazit(data) {
    const el = $("bfFazit");
    if (!el) return;
    const fazit = data.fazit;
    if (!fazit) { el.hidden = true; return; }

    el.hidden = false;
    const bw = fazit.best_weekday || {};
    const wrating = formatRating(fazit.week_rating);
    const headline = bw.headline || bw.reason || "";
    const summary = fazit.week_summary || "";

    el.innerHTML = `
      <div class="bf-fazit-head">
        <span class="bf-fazit-label">Wochenfazit${bw.weekday ? ` — Bester Tag: ${escapeHtml(bw.weekday)}` : ""}</span>
        <span class="bf-fazit-chevron" aria-hidden="true">▾</span>
      </div>
      <div class="bf-fazit-body"${state.fazitOpen ? "" : " hidden"}>
        ${headline ? `<div class="bf-fazit-best">${escapeHtml(headline)}</div>` : ""}
        ${summary ? `<p class="bf-fazit-text">${escapeHtml(summary)}</p>` : ""}
        ${wrating !== "—" ? `<span class="bf-fazit-rating">${wrating} / 10</span>` : ""}
      </div>
    `;
    el.className = `bf-fazit${state.fazitOpen ? " is-open" : ""}`;

    if (!el._flyBound) {
      el._flyBound = true;
      el.addEventListener("click", () => {
        state.fazitOpen = !state.fazitOpen;
        const body = el.querySelector(".bf-fazit-body");
        if (body) body.hidden = !state.fazitOpen;
        el.classList.toggle("is-open", state.fazitOpen);
      });
    }
  }

  // ── Render: Day Tabs ────────────────────────────────────────

  function renderDayTabs(data) {
    const container = $("bfDayTabs");
    if (!container) return;
    const days = data.days || [];
    if (!days.length) { container.innerHTML = ""; return; }

    const fazit = data.fazit;
    const bestDate = fazit && fazit.best_weekday && fazit.best_weekday.date;

    // Clamp selectedDayIdx
    if (state.selectedDayIdx >= days.length) state.selectedDayIdx = 0;

    container.innerHTML = days.map((d, i) => {
      const isActive = i === state.selectedDayIdx;
      const isBest = d.date === bestDate;
      const counts = computeDayCounts(d);
      const flyable = counts.spots_flyable || 0;

      // Count violet spots
      let violet = 0;
      for (const s of (d.top_spots || [])) {
        if (s.fly_status === "violet") violet++;
      }
      const green = Math.max(0, flyable - violet);

      // Build dots (max 4)
      const dots = [];
      for (let j = 0; j < Math.min(violet, 2); j++) dots.push('<span class="bf-tab-dot violet"></span>');
      for (let j = 0; j < Math.min(green, 2); j++) dots.push('<span class="bf-tab-dot green"></span>');

      const dateObj = new Date(d.date + "T12:00:00");
      const dayNum = dateObj.getDate();
      const wdShort = (d.weekday || "").substring(0, 2);

      const cls = ["bf-day-tab"];
      if (isActive) cls.push("is-active");
      if (isBest) cls.push("is-best");

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
    renderDayTabs(state.data);
    renderDayContent();
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
      resetBtn.disabled = state.filterRegions.size === 0;
      if (!resetBtn._flyBound) {
        resetBtn._flyBound = true;
        resetBtn.addEventListener("click", () => {
          if (state.filterRegions.size === 0) return;
          state.filterRegions.clear();
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
    saveRegionFilter(state.filterRegions);
    renderFilters(state.data);
    renderDayTabs(state.data);
    renderDayContent();
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
      el.innerHTML = '<div class="bf-minimap-fallback">Karte nicht verfuegbar</div>';
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
      mapObj.fitBounds([[45.8, 5.9], [47.9, 10.6]], { padding: [6, 6] });

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
            if (b && b.isValid()) mapObj.fitBounds(b, { padding: [6, 6] });
          } catch (_) {}
          try { renderFilters(state.data); } catch (_) {}
        })
        .catch((err) => console.warn("[briefing] filter-map fetch failed", err));

      requestAnimationFrame(() => { try { mapObj.invalidateSize(); } catch (_) {} });
      setTimeout(() => { try { mapObj.invalidateSize(); } catch (_) {} }, 300);
    } catch (e) {
      console.warn("[briefing] filter-map init failed", e);
      el.innerHTML = '<div class="bf-minimap-fallback">Karte nicht verfuegbar</div>';
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
      contentEl.innerHTML = '<div class="bf-content-empty">Noch keine Prognosedaten vorhanden.</div>';
      return;
    }

    // Day info bar
    const counts = computeDayCounts(day);
    let violet = 0;
    const filteredSpots = filterDaySpots(day);
    for (const s of filteredSpots) {
      if (s.fly_status === "violet") violet++;
    }
    const green = Math.max(0, (counts.spots_flyable || 0) - violet);

    infoEl.innerHTML = `
      <span class="bf-day-title">${escapeHtml(day.weekday || "")} ${formatDateDE(day.date)}</span>
      <span class="bf-day-stats">
        ${violet > 0 ? `<span class="bf-stat-violet"><strong>${violet}</strong> legendaer</span>` : ""}
        ${green > 0 ? `<span class="bf-stat-green"><strong>${green}</strong> fliegbar</span>` : ""}
        ${counts.spots_bronze > 0 ? `<span class="bf-stat-bronze"><strong>${counts.spots_bronze}</strong> Abgleiter</span>` : ""}
        ${counts.spots_nogo > 0 ? `<span><strong>${counts.spots_nogo}</strong> NO-GO</span>` : ""}
      </span>
    `;

    // Spots grouped by region
    const spotsWithDate = filteredSpots.map((s) => Object.assign({}, s, { date: day.date }));
    const groups = groupSpotsByRegion(spotsWithDate);

    // Region meta from day data
    const regionsMap = {};
    for (const r of (day.top_regions || [])) {
      regionsMap[r.region_id] = r;
    }

    // Sort by region rating
    groups.sort((a, b) => {
      const ra = regionsMap[a.region_id] ? regionsMap[a.region_id].rating : (a.spots[0]?.rating || 0);
      const rb = regionsMap[b.region_id] ? regionsMap[b.region_id].rating : (b.spots[0]?.rating || 0);
      return rb - ra;
    });

    if (!groups.length) {
      contentEl.innerHTML = `<div class="bf-content-empty">Keine fliegbaren Spots${state.filterRegions.size ? " in den gefilterten Regionen" : ""} — ${counts.spots_nogo || 0} NO-GO, ${counts.spots_bronze || 0} Abgleiter.</div>`;
      return;
    }

    contentEl.innerHTML = groups.map((g) => renderRegionSection(g, regionsMap[g.region_id])).join("");
  }

  function renderRegionSection(group, meta) {
    const name = (meta && meta.region_name) || group.region_name || (group.region_id === "unknown" ? "Weitere Spots" : group.region_id);
    const rating = meta ? formatRating(meta.rating) : "";
    const spotsHtml = group.spots.map(renderSpotRow).join("");
    return `
      <div class="bf-region">
        <div class="bf-region-head">
          <span class="bf-region-name">${escapeHtml(name)}</span>
          ${rating ? `<span class="bf-region-rating">${rating}</span>` : ""}
        </div>
        <ul class="bf-spot-list">${spotsHtml}</ul>
      </div>
    `;
  }

  // ── Render: Spot Row ────────────────────────────────────────

  function renderSpotRow(spot) {
    if (!spot.spot || !String(spot.spot).trim()) return "";
    const tier = spot.fly_status === "violet" ? "tier-violet" : spot.fly_status === "gray" ? "tier-bronze" : "tier-green";

    // ── Status-Leiste: kompakte Chips mit Analyse-Infos ──
    const ss = spot.safety_status || "";
    const safetyLabel = ss === "safe" ? "Sicher" : ss === "conditional" ? "Bedingt" : "";
    const safetyCls = ss === "safe" ? "bf-chip--safe" : ss === "conditional" ? "bf-chip--cond" : "";

    const chips = [];
    if (safetyLabel) chips.push(`<span class="bf-chip ${safetyCls}">${escapeHtml(safetyLabel)}</span>`);
    if (spot.best_window) chips.push(`<span class="bf-chip bf-chip--window">${escapeHtml(spot.best_window)}</span>`);
    if (spot.flight_type) chips.push(`<span class="bf-chip bf-chip--type">${escapeHtml(spot.flight_type)}</span>`);
    if (spot.peak_climb_rate && Number(spot.peak_climb_rate) > 0) {
      chips.push(`<span class="bf-chip bf-chip--climb">↑${Number(spot.peak_climb_rate).toFixed(1)} m/s</span>`);
    }
    if (spot.flight_duration) chips.push(`<span class="bf-chip">${escapeHtml(spot.flight_duration)}</span>`);
    if (spot.is_conditional && spot.conditional_reason) {
      chips.push(`<span class="bf-chip bf-chip--warn">${escapeHtml(spot.conditional_reason)}</span>`);
    }

    const statusBar = chips.length
      ? `<div class="bf-spot-status">${chips.join("")}</div>`
      : "";

    const mapHref = `/map?spot=${encodeURIComponent(spot.spot)}`;

    // Details (expanded content)
    const analysisForDetails = spot.analysis_full || synthesizeAnalysis(spot);
    const labelsHtml = renderSpotLabels(analysisForDetails);
    const summaryHtml = renderSpotSummary(analysisForDetails);
    const recText = (analysisForDetails.recommendation || (analysisForDetails.flyability || {}).recommendation || "").trim();
    const recHtml = recText ? `<div class="bf-detail-rec"><span class="bf-detail-rec-icon">✍</span> ${escapeHtml(recText)}</div>` : "";
    const hasCoords = spot.lat != null && spot.lon != null;

    const miniMapInner = hasCoords
      ? `<div class="bf-spot-minimap" data-lat="${spot.lat}" data-lon="${spot.lon}" data-spot="${escapeHtml(spot.spot)}" data-href="${escapeHtml(mapHref)}" data-windrichtung="${escapeHtml(spot.windrichtung || "")}" data-safety="${escapeHtml(spot.safety_status || "")}" data-quality="${escapeHtml(spot.fly_status || "")}"></div>`
      : `<div class="bf-spot-minimap bf-spot-minimap--nodata">Keine Koordinaten</div>`;

    return `
      <li class="bf-spot ${tier}">
        <div class="bf-spot-toggle" role="button" tabindex="0" aria-expanded="false">
          <div class="bf-spot-row">
            <span class="bf-spot-name">${escapeHtml(spot.spot)}</span>
            <span class="bf-spot-spacer"></span>
            <a class="bf-spot-map-link" href="${escapeHtml(mapHref)}" title="Karte">📍</a>
            <span class="bf-spot-rating">${formatRating(spot.rating)}</span>
            <span class="bf-spot-chevron" aria-hidden="true">▾</span>
          </div>
          ${statusBar}
        </div>
        <div class="bf-spot-divider"></div>
        <div class="bf-spot-details" hidden>
          <div class="bf-detail-top">
            ${labelsHtml ? `<div class="bf-detail-labels">${labelsHtml}</div>` : ""}
            ${recHtml}
          </div>
          <div class="bf-detail-mapmeteo-row">
            <section class="bf-detail-mapblock">
              <h4 class="bf-detail-title"><span class="bf-detail-icon">🗺</span>Startplatz</h4>
              ${miniMapInner}
            </section>
            <section class="bf-detail-meteoblock">
              <h4 class="bf-detail-title"><span class="bf-detail-icon">📈</span>Meteogramm</h4>
              <div class="bf-spot-meteogram" data-spot="${escapeHtml(spot.spot)}" data-date="${escapeHtml(spot.date || "")}">
                <div class="bf-meteogram-chart"></div>
              </div>
            </section>
          </div>
          ${summaryHtml ? `<div class="bf-detail-summary"><p>${summaryHtml}</p></div>` : ""}
        </div>
      </li>
    `;
  }

  // ── Spot Detail Sections ────────────────────────────────────

  function renderSpotLabels(analysis) {
    if (!analysis || typeof analysis !== "object") return "";
    const a = analysis;
    const saf = a.safety || {};
    const fly = a.flyability || {};
    const s = (v) => (v == null ? "" : String(v).trim());

    const items = [];

    // ── Info: Best window ──
    const win = s(a.best_window || fly.best_window || saf.safe_window);
    if (win && win !== "keins") {
      items.push({ cls: "info", icon: "⏱", text: `Bestes Fenster: ${win}` });
    }

    // ── ↓ No-go reasons (most critical first) ──
    for (const r of (Array.isArray(saf.no_go_reasons) ? saf.no_go_reasons : [])) {
      if (s(r)) items.push({ cls: "bad", icon: "↓", text: s(r) });
    }

    // ── ! Caution notes ──
    for (const c of (Array.isArray(saf.caution_notes) ? saf.caution_notes : [])) {
      if (s(c)) items.push({ cls: "warn", icon: "!", text: s(c) });
    }
    const foehn = s(saf.foehn_risk || a.foehn_risk);
    if (foehn && foehn !== "none") {
      items.push({ cls: "warn", icon: "!", text: `Föhn: ${foehn}` });
    }

    // ── ✓ Positives ──
    const peak = Number(a.peak_climb_rate || fly.peak_climb_rate);
    if (isFinite(peak) && peak > 0) {
      items.push({ cls: "good", icon: "✓", text: `Peak-Thermik ${peak.toFixed(1)} m/s` });
    }

    const windOk = Number(saf.wind_ok_count) || 0;
    const windWrong = Number(saf.wind_wrong_count) || 0;
    if (windOk > 0 && windOk >= windWrong) {
      items.push({ cls: "good", icon: "✓", text: `Gute Windbedingungen (${windOk}h passend)` });
    }

    const xc = s(a.xc_potential || fly.xc_potential);
    if (xc === "high") items.push({ cls: "good", icon: "✓", text: "Hohes XC-Potenzial" });
    else if (xc === "moderate") items.push({ cls: "good", icon: "✓", text: "XC-Potenzial vorhanden" });

    // Booster
    const booster = s(saf.primary_booster);
    if (booster) {
      const bl = { GUTE_EINSTRAHLUNG: "Gute Einstrahlung", XC_BEDINGUNGEN: "XC-Bedingungen" };
      items.push({ cls: "good", icon: "✓", text: bl[booster] || booster.replace(/_/g, " ") });
    }

    // Reducer (only if not already covered in no-go/caution)
    const reducer = s(saf.primary_reducer);
    if (reducer) {
      const existing = [...(saf.no_go_reasons || []), ...(saf.caution_notes || [])].join(" ").toLowerCase();
      if (!existing.includes(reducer.toLowerCase().replace(/_/g, " "))) {
        const rl = { VIEL_BEWOELKUNG: "Viel Bewölkung", REGEN: "Niederschlag" };
        items.push({ cls: "bad", icon: "↓", text: rl[reducer] || reducer.replace(/_/g, " ") });
      }
    }

    if (!items.length) return "";

    return items.map((it) =>
      `<div class="bf-label bf-label--${it.cls}"><span class="bf-label-icon">${it.icon}</span><span class="bf-label-text">${escapeHtml(it.text)}</span></div>`
    ).join("");
  }

  function renderSpotSummary(analysis) {
    if (!analysis || typeof analysis !== "object") return "";
    const saf = analysis.safety || {};
    const text = String(analysis.safety_feedback || saf.summary || "").trim();
    if (!text || text === "0" || text === "null" || text === "None") return "";
    return escapeHtml(text);
  }

  function synthesizeAnalysis(spot) {
    if (!spot) return null;
    return {
      safety_status: spot.safety_status || "",
      fly_status: spot.fly_status || "",
      flight_type: spot.flight_type || "",
      flight_duration_estimate: spot.flight_duration || "",
      xc_potential: spot.xc_potential || "",
      best_window: spot.best_window || "",
      peak_climb_rate: spot.peak_climb_rate || 0,
      recommendation: spot.recommendation || "",
      safety_feedback: spot.safety_feedback || "",
      is_conditional: !!spot.is_conditional,
      conditional_reason: spot.conditional_reason || "",
    };
  }

  // ── Spot Toggle (expand/collapse) ───────────────────────────

  function handleSpotToggle(ev) {
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

  // ── Mini Map ────────────────────────────────────────────────

  const _bfIcon = { uid: 0 };

  function bfGetDirAngles(dirStr) {
    if (!dirStr) return null;
    const dirs = {
      'N':0,'NNO':22.5,'NNE':22.5,'NO':45,'NE':45,'ONO':67.5,'ENE':67.5,
      'O':90,'E':90,'OSO':112.5,'ESE':112.5,'SO':135,'SE':135,'SSO':157.5,'SSE':157.5,
      'S':180,'SSW':202.5,'SW':225,'WSW':247.5,
      'W':270,'WNW':292.5,'NW':315,'NNW':337.5,
    };
    const parts = dirStr.toUpperCase().split('-');
    if (parts.length === 1) {
      const a = dirs[parts[0]];
      if (a === undefined) return null;
      return [a - 22.5, a + 22.5];
    } else if (parts.length === 2) {
      let a1 = dirs[parts[0]], a2 = dirs[parts[1]];
      if (a1 === undefined || a2 === undefined) return null;
      if (Math.abs(a1 - a2) > 180) { if (a1 < a2) a1 += 360; else a2 += 360; }
      return [Math.min(a1, a2), Math.max(a1, a2)];
    }
    return null;
  }

  function bfSafetyQualityStyle(safety, quality) {
    if (safety === 'default' || safety === 'no_data' || !safety) {
      return { fill: safety === 'no_data' ? '#9ca3af' : '#6b7280', stroke: safety === 'no_data' ? '#6b7280' : '#4b5563', glow: null, showStripes: false, showWarning: false };
    }
    if (safety === 'error') return { fill: '#f87171', stroke: '#b91c1c', glow: null, showStripes: false, showWarning: false };
    if (safety === 'not_safe') return { fill: '#dc2626', stroke: '#991b1b', glow: null, showStripes: true, showWarning: false };
    if (safety === 'safe') {
      if (quality === 'gray') return { fill: '#B08D57', stroke: '#8A6D3B', glow: null, showStripes: false, showWarning: false };
      if (quality === 'violet') return { fill: '#8b5cf6', stroke: '#6d28d9', glow: 'rgba(139, 92, 246, 0.45)', showStripes: false, showWarning: false };
      return { fill: '#22c55e', stroke: '#15803d', glow: null, showStripes: false, showWarning: false };
    }
    if (quality === 'gray') return { fill: '#fbbf24', stroke: '#b45309', glow: null, showStripes: false, showWarning: true };
    if (quality === 'violet') return { fill: '#d97706', stroke: '#78350f', glow: null, showStripes: false, showWarning: true };
    return { fill: '#f59e0b', stroke: '#92400e', glow: null, showStripes: false, showWarning: true };
  }

  function bfCreateSpotIcon(windrichtung, safety, quality) {
    const uid = ++_bfIcon.uid;
    const style = bfSafetyQualityStyle(safety, quality);
    const sz = 44, c = sz / 2, r = 7;
    let h = '<svg width="'+sz+'" height="'+sz+'" viewBox="0 0 '+sz+' '+sz+'">';

    if (style.showStripes) {
      h += '<defs><pattern id="bfs'+uid+'" width="4" height="4" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="4" stroke="rgba(255,255,255,0.2)" stroke-width="1.5"/></pattern></defs>';
    }

    const angles = bfGetDirAngles(windrichtung);
    if (angles) {
      const si = r+1, so = r+9;
      const sr = (angles[0]-90)*Math.PI/180, er = (angles[1]-90)*Math.PI/180;
      const ix1=c+si*Math.cos(sr), iy1=c+si*Math.sin(sr), ix2=c+si*Math.cos(er), iy2=c+si*Math.sin(er);
      const ox1=c+so*Math.cos(sr), oy1=c+so*Math.sin(sr), ox2=c+so*Math.cos(er), oy2=c+so*Math.sin(er);
      const la = (angles[1]-angles[0])>180?1:0;
      h += '<path d="M '+ox1+' '+oy1+' A '+so+' '+so+' 0 '+la+' 1 '+ox2+' '+oy2+' L '+ix2+' '+iy2+' A '+si+' '+si+' 0 '+la+' 0 '+ix1+' '+iy1+' Z" fill="'+style.stroke+'" opacity="0.5" />';
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
      el.innerHTML = '<div class="bf-minimap-fallback">Karte nicht verfuegbar</div>';
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

      const icon = bfCreateSpotIcon(el.dataset.windrichtung || "", el.dataset.safety || "", el.dataset.quality || "");
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
      el.innerHTML = '<div class="bf-minimap-fallback">Karte nicht verfuegbar</div>';
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
      chartEl.innerHTML = '<div class="bf-meteogram-fallback">Meteogramm nicht verfuegbar</div>';
      return;
    }
    chartEl.innerHTML = '<div class="bf-meteogram-loading">Lade Meteogramm…</div>';

    fetchMeteogramData(spotName)
      .then((data) => {
        const weather = data.weather || {};
        const altWind = data.altWind || {};
        if (weather.error) { chartEl.innerHTML = '<div class="bf-meteogram-fallback">' + escapeHtml(weather.error) + '</div>'; return; }
        if (altWind.error) { chartEl.innerHTML = '<div class="bf-meteogram-fallback">' + escapeHtml(altWind.error) + '</div>'; return; }
        const wxDay = (weather.data || {})[dateStr] || {};
        const altProfiles = (altWind.data || {})[dateStr] || [];
        if (!wxDay || !altProfiles.length) {
          chartEl.innerHTML = '<div class="bf-meteogram-fallback">Keine Daten fuer ' + escapeHtml(dateStr) + '</div>';
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
          });
        } catch (e) {
          console.warn("[briefing] Meteogram failed", e);
          chartEl.innerHTML = '<div class="bf-meteogram-fallback">Render-Fehler</div>';
        }
      })
      .catch((err) => {
        console.warn("[briefing] meteogram fetch failed", err);
        chartEl.innerHTML = '<div class="bf-meteogram-fallback">Daten nicht verfuegbar</div>';
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
      if (el) el.innerHTML = `<div class="bf-content-empty">Fehler: ${escapeHtml(err.message)}</div>`;
    }
  }

  async function generateFazit() {
    if (state.generating) return;
    state.generating = true;
    const btn = $("bfGenerateBtn");
    const orig = btn.textContent;
    btn.disabled = true;
    btn.textContent = "Generiert…";
    try {
      const res = await fetch("/api/briefing/generate", { method: "POST", headers: { "Content-Type": "application/json" } });
      const data = await res.json();
      if (!data.success) throw new Error(data.error || "Fehlgeschlagen");
      render(data);
    } catch (err) {
      console.error("[briefing] generate failed", err);
      alert(`Fehler: ${err.message}`);
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
    renderFazit(data);
    renderDayTabs(data);
    renderFilters(data);
    renderDayContent();
  }

  // ── Init ────────────────────────────────────────────────────

  function init() {
    const btn = $("bfGenerateBtn");
    if (btn) btn.addEventListener("click", generateFazit);

    const contentEl = $("bfContent");
    if (contentEl) {
      contentEl.addEventListener("click", handleSpotToggle);
      contentEl.addEventListener("keydown", handleSpotKeydown);
    }

    loadBriefing();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
