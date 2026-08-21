/* ══════════════════════════════════════════════════════════════
   Wingcast – Subscribe: Region-Filter mit Chips + Karte
   Spiegelt die Briefing-UX (static/js/briefing.js) auf dem
   Abo-Formular. Auswahl via Chip oder Klick aufs Polygon.
   Hidden <input>s werden für den POST synchronisiert.
   ══════════════════════════════════════════════════════════════ */

(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);

  function escapeHtml(str) {
    if (str === null || str === undefined) return "";
    return String(str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  const root = $("spRegionFilters");
  if (!root) return;

  let regions = [];
  try { regions = JSON.parse(root.dataset.regions || "[]"); } catch (e) { regions = []; }

  let prefill = [];
  try { prefill = JSON.parse(root.dataset.prefill || "[]"); } catch (e) { prefill = []; }

  const selected = new Set(prefill);
  const mapState = { map: null, layer: null, pathById: new Map(), visible: true };

  const chipsEl = $("spFilterChips");
  const resetBtn = $("spFilterReset");
  const mapBtn = $("spMapToggle");
  const mapEl = $("spFilterMap");
  const inputsEl = $("spRegionInputs");

  function syncHiddenInputs() {
    if (!inputsEl) return;
    inputsEl.innerHTML = Array.from(selected).map((id) =>
      `<input type="hidden" name="regions" value="${escapeHtml(id)}">`
    ).join("");
  }

  function renderChips() {
    if (!chipsEl) return;
    chipsEl.innerHTML = regions.map((r) => {
      const active = selected.has(r.id);
      return `<button type="button" class="sp-filter-chip${active ? " is-active" : ""}" data-region-id="${escapeHtml(r.id)}" aria-pressed="${active}">${escapeHtml(r.region)}</button>`;
    }).join("");
    if (resetBtn) {
      // Beschriftung bleibt immer "Alle" — nur visueller Status (is-active)
      // zeigt an, ob bereits alle ausgewaehlt sind. Klick togglet trotzdem
      // (alle <-> keine), damit der Button beide Richtungen kann.
      const allActive = regions.length > 0 && regions.every((r) => selected.has(r.id));
      resetBtn.disabled = regions.length === 0;
      resetBtn.textContent = wcT("js.regions.all");
      resetBtn.classList.toggle("is-active", allActive);
      resetBtn.setAttribute(
        "aria-label",
        allActive ? wcT("js.regions.deselect_all") : wcT("js.regions.select_all")
      );
      resetBtn.setAttribute("aria-pressed", allActive ? "true" : "false");
    }
  }

  function toggle(id) {
    if (!id) return;
    if (selected.has(id)) selected.delete(id);
    else selected.add(id);
    renderChips();
    syncHiddenInputs();
    updateMapStyles();
  }

  if (chipsEl) {
    chipsEl.addEventListener("click", (ev) => {
      const btn = ev.target.closest(".sp-filter-chip");
      if (!btn) return;
      toggle(btn.dataset.regionId);
    });
  }

  if (resetBtn) {
    resetBtn.addEventListener("click", () => {
      if (regions.length === 0) return;
      const allActive = regions.every((r) => selected.has(r.id));
      if (allActive) {
        selected.clear();
      } else {
        selected.clear();
        regions.forEach((r) => selected.add(r.id));
      }
      renderChips();
      syncHiddenInputs();
      updateMapStyles();
    });
  }

  function mapStyle(regionId) {
    const active = selected.has(regionId);
    if (active) {
      return { color: "#8c2d1f", weight: 2.5, opacity: 1, fillColor: "#c94a36", fillOpacity: 0.55 };
    }
    return { color: "#6b635a", weight: 1.2, opacity: 1, fillColor: "#c4bdb0", fillOpacity: 0.45 };
  }

  function updateMapStyles() {
    if (!mapState.layer) return;
    mapState.pathById.forEach((lyr, id) => {
      try { lyr.setStyle(mapStyle(id)); } catch (_) { }
    });
  }

  function initMap() {
    if (!mapEl || mapState.map) {
      updateMapStyles();
      return;
    }
    if (typeof L === "undefined") {
      mapEl.innerHTML = '<div class="sp-minimap-fallback">' + wcT('js.map.unavailable') + '</div>';
      return;
    }

    try {
      const mapObj = L.map(mapEl, {
        center: [46.8, 8.2], zoom: 7,
        zoomSnap: 0.1,
        zoomControl: true, attributionControl: false,
        scrollWheelZoom: false, dragging: true, touchZoom: true, doubleClickZoom: false,
      });
      L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
        subdomains: 'abcd', maxZoom: 14,
      }).addTo(mapObj);
      mapState.map = mapObj;

      fetch("/api/regionen-polygone", { cache: "no-cache" })
        .then((r) => r.json())
        .then((geojson) => {
          if (!geojson || !Array.isArray(geojson.features) || !geojson.features.length) return;

          const layer = L.geoJSON(geojson, {
            style: (feature) => mapStyle(feature.properties.id),
            onEachFeature: (feature, lyr) => {
              const props = feature.properties || {};
              const rid = props.id;
              if (!rid) return;
              mapState.pathById.set(rid, lyr);

              lyr.bindTooltip(props.region || props.name || rid, {
                className: "sp-region-label", direction: "center", permanent: false, sticky: true,
              });

              lyr.on("click", () => toggle(rid));
              lyr.on("mouseover", function () {
                this.setStyle(Object.assign({}, mapStyle(rid), { weight: 3.5, fillOpacity: 0.7 }));
              });
              lyr.on("mouseout", function () { this.setStyle(mapStyle(rid)); });
            },
          }).addTo(mapObj);
          mapState.layer = layer;

          const fit = () => {
            try { mapObj.invalidateSize(); } catch (_) { }
            try {
              const b = layer.getBounds();
              if (!b || !b.isValid()) return;
              const z = mapObj.getBoundsZoom(b, false);
              mapObj.setView(b.getCenter(), z, { animate: false });
            } catch (_) { }
          };
          fit();
          // Container hat u.U. bei Laden noch nicht seine Endgrösse -> nachkorrigieren
          requestAnimationFrame(fit);
          setTimeout(fit, 300);
        })
        .catch((err) => console.warn("[subscribe] filter-map fetch failed", err));
    } catch (e) {
      console.warn("[subscribe] filter-map init failed", e);
      mapEl.innerHTML = '<div class="sp-minimap-fallback">' + wcT('js.map.unavailable') + '</div>';
    }
  }

  if (mapBtn) {
    mapBtn.addEventListener("click", () => {
      mapState.visible = !mapState.visible;
      if (mapEl) mapEl.hidden = !mapState.visible;
      mapBtn.classList.toggle("is-active", mapState.visible);
      if (mapState.visible) initMap();
    });
  }

  renderChips();
  syncHiddenInputs();

  // Karte standardmässig aufgeklappt
  if (mapEl) mapEl.hidden = false;
  if (mapBtn) mapBtn.classList.add("is-active");
  initMap();
})();
