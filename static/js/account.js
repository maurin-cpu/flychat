/* ════════════════════════════════════════════════════════════════
   Account-Seite: Tier-Chips, Rating-Slider, Wochentage-Chips.
   Region-Picker laeuft via subscribe.js (gleiche IDs spRegionFilters etc.).
   Tier + Weekday: Klick auf Label togglet 'is-active' synchron mit
   dem Hidden-Checkbox-Input — der Form-POST liest die Checkboxen.
   ════════════════════════════════════════════════════════════════ */

(function () {
  "use strict";

  /* ----- Tier-Chips: Klick togglet die Checkbox + visuellen State ----- */
  document.querySelectorAll(".ac-tier-chip").forEach(function (chip) {
    var cb = chip.querySelector("input[type='checkbox']");
    if (!cb) return;
    chip.addEventListener("click", function (ev) {
      // Klick auf inneres Element soll nicht doppelt zaehlen.
      // Standard-Label-Verhalten triggert checkbox-change automatisch — wir
      // synchronisieren nur die is-active Klasse.
      if (ev.target !== cb) {
        // Manueller Toggle, wenn Klick nicht direkt auf der versteckten Checkbox war.
        // Aber: das Label umschliesst die Checkbox -> Browser togglet eh.
      }
      // Use rAF um nach dem nativen Toggle die Klasse zu setzen
      requestAnimationFrame(function(){
        chip.classList.toggle("is-active", cb.checked);
      });
    });
  });

  /* ----- Wochentage: gleiches Pattern wie Tier-Chips ----- */
  document.querySelectorAll(".ac-weekday-chip").forEach(function (chip) {
    var cb = chip.querySelector("input[type='checkbox']");
    if (!cb) return;
    chip.addEventListener("click", function () {
      requestAnimationFrame(function(){
        chip.classList.toggle("is-active", cb.checked);
      });
    });
  });

  /* ----- Pause-Zeitraum: flatpickr Range-Picker (single calendar, click-click) ----- */
  var rangeInput = document.getElementById("acPauseRange");
  var pausedFrom = document.getElementById("acPausedFrom");
  var pausedUntil = document.getElementById("acPausedUntil");
  var winterBtn = document.getElementById("acPauseWinter");
  var clearBtn = document.getElementById("acPauseClear");

  function formatISO(d) {
    var y = d.getFullYear();
    var m = String(d.getMonth() + 1).padStart(2, "0");
    var dd = String(d.getDate()).padStart(2, "0");
    return y + "-" + m + "-" + dd;
  }

  var fp = null;
  if (rangeInput && typeof flatpickr !== "undefined") {
    var initialDates = [];
    if (pausedFrom && pausedFrom.value) initialDates.push(pausedFrom.value);
    if (pausedUntil && pausedUntil.value) initialDates.push(pausedUntil.value);

    fp = flatpickr(rangeInput, {
      mode: "range",
      dateFormat: "Y-m-d",
      altInput: true,
      altFormat: "j. M Y",
      locale: (window.flatpickr && window.flatpickr.l10ns && window.flatpickr.l10ns.de) || "default",
      minDate: "today",
      defaultDate: initialDates.length === 2 ? initialDates : null,
      onChange: function (selectedDates) {
        // Bei Range: erstes Datum = Start, zweites = Ende. Erst nach 2 Klicks fuellen.
        if (selectedDates.length === 2) {
          pausedFrom.value = formatISO(selectedDates[0]);
          pausedUntil.value = formatISO(selectedDates[1]);
        } else if (selectedDates.length === 0) {
          pausedFrom.value = "";
          pausedUntil.value = "";
        }
      },
    });
  }

  if (winterBtn) {
    winterBtn.addEventListener("click", function () {
      // Winterpause: kontextabhaengig
      //   Jan/Feb -> ab heute bis 28. Feb dieses Jahr
      //   Maerz-Okt -> 1. Nov dieses Jahr bis 28. Feb naechstes Jahr
      //   Nov/Dez -> ab heute bis 28. Feb naechstes Jahr
      var now = new Date();
      var month = now.getMonth();
      var year = now.getFullYear();
      var fromDate, toDate;
      if (month <= 1) {
        fromDate = now;
        toDate = new Date(year, 1, 28);
      } else if (month >= 10) {
        fromDate = now;
        toDate = new Date(year + 1, 1, 28);
      } else {
        fromDate = new Date(year, 10, 1);
        toDate = new Date(year + 1, 1, 28);
      }
      if (fp) {
        fp.setDate([fromDate, toDate], true); // true = trigger onChange
      } else {
        // Fallback ohne flatpickr (z.B. CDN nicht geladen)
        pausedFrom.value = formatISO(fromDate);
        pausedUntil.value = formatISO(toDate);
      }
    });
  }

  if (clearBtn) {
    clearBtn.addEventListener("click", function () {
      if (fp) {
        fp.clear();
      }
      pausedFrom.value = "";
      pausedUntil.value = "";
    });
  }

  /* ----- Rating-Slider: Live-Update von Wert + Fortschrittsbalken ----- */
  var slider = document.getElementById("acRatingSlider");
  var output = document.getElementById("acRatingValue");
  if (slider) {
    function updateSlider() {
      var v = parseFloat(slider.value || "0");
      var pct = (v / parseFloat(slider.max || "10")) * 100;
      slider.style.setProperty("--rating-percent", pct + "%");
      if (output) {
        output.textContent = v <= 0 ? "alle" : "≥ " + v.toFixed(1);
      }
    }
    slider.addEventListener("input", updateSlider);
    slider.addEventListener("change", updateSlider);
    updateSlider();
  }
})();
