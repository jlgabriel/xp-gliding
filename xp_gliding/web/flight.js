// XP-Gliding Flight Computer: the strip and the FLIGHT view, drawn from one snapshot, and the text
// sized to fill their cells. Text goes in with textContent only. Classic script, Chromium 117.
// License: GPL-3.0-or-later.
"use strict";

var xpg = window.xpg || {};
window.xpg = xpg;

xpg.flight = (function () {
  var f = xpg.format;
  var els = null;
  var shownUnits = null;

  function find() {
    var ids = ["clock", "strip-te", "strip-avg", "strip-alt", "te-bar", "netto", "thm", "agl", "ias", "gs", "top",
               "wind", "wind-arrow"];
    els = {};
    ids.forEach(function (id) { els[id] = document.getElementById(id); });
  }

  function set(id, text) {
    var el = els[id];
    if (el.textContent !== text) el.textContent = text;
  }

  function labelUnits(u) {
    var nodes = document.querySelectorAll("[data-unit]");
    for (var i = 0; i < nodes.length; i++) {
      nodes[i].textContent = u[nodes[i].getAttribute("data-unit")];
    }
  }

  // The TE bar: half its height is 5 m/s or 10 kt, as the HUD's tape.
  function bar(te, unitsName) {
    var el = els["te-bar"];
    if (!f.known(te)) {
      el.style.height = "0";
      return;
    }
    var span = unitsName === "aviation" ? 10 * 0.514444 : 5;
    var share = Math.max(-1, Math.min(1, te / span));
    el.style.height = (Math.abs(share) * 50) + "%";
    el.style.top = share >= 0 ? (50 - share * 50) + "%" : "50%";
    el.classList.toggle("down", share < 0);
  }

  // The arrow points where the wind goes, nose up: it turns as the glider circles, as on the HUD.
  function windArrow(s) {
    var el = els["wind-arrow"];
    var calm = !f.known(s.wind_from_deg) || !f.known(s.heading_deg);
    el.classList.toggle("calm", calm);
    if (!calm) el.style.transform = "rotate(" + (s.wind_from_deg + 180 - s.heading_deg) + "deg)";
  }

  function draw(s) {
    if (!els) find();
    var u = f.units(s.units);
    if (shownUnits !== s.units) {
      shownUnits = s.units;
      labelUnits(u);
    }
    document.body.classList.toggle("stale", !s.valid);
    set("clock", f.clock(s.local_s));
    set("strip-te", f.climb(s.te_ms, u));
    bar(s.te_ms, s.units);
    set("strip-avg", f.climb(s.avg_ms, u));
    set("strip-alt", f.height(s.msl_m, u, false));
    set("netto", f.climb(s.netto_ms, u));
    set("thm", s.thm_valid ? f.climb(s.thm_ms, u) : "--");
    els.thm.classList.toggle("left", s.thm_valid && !s.thm_active);
    set("agl", f.height(s.agl_m, u, false));
    set("ias", f.speed(s.ias_ms, u));
    set("gs", f.speed(s.gs_ms, u));
    set("top", f.height(s.top_m, u, true));
    set("wind", f.wind(s.wind_from_deg, s.wind_ms));
    windArrow(s);
  }

  // --- sizes -------------------------------------------------------------------------
  // Measured from the cells, so the numbers fill them in any window (see app.css). A number is
  // at most half its cell's height, and narrow enough for its widest reading: five characters and
  // a small unit ("+3080 ft", "-14.4 kt", about 3.6 times the font size), seven and an arrow for
  // the wind ("179° 12 kt").

  var PAD = 12;  // a cell's padding and border, both sides

  function px(v, lo, hi) {
    return Math.max(lo, Math.min(hi, v)).toFixed(1) + "px";
  }

  function size(el) {
    var r = el.closest(".cell").getBoundingClientRect();
    return {w: r.width - PAD, h: r.height};
  }

  // The FLIGHT view is measured only while shown (display: none measures nothing): the page fits
  // again when it is shown.
  function fit() {
    if (!els) find();
    var style = document.documentElement.style;
    var strip = size(els["strip-avg"]);
    var barW = Math.max(5, Math.min(12, strip.w * 0.05));
    var stripLabel = Math.max(10, Math.min(20, strip.w * 0.12, strip.h * 0.19));
    var stripValue = Math.min((strip.w - barW - 4) / 3.6, (strip.h - stripLabel) * 0.62);
    style.setProperty("--strip", px(stripValue, 12, 72));
    style.setProperty("--strip-unit", px(stripValue * 0.42, 8, 24));
    style.setProperty("--bar", px(barW, 5, 12));
    style.setProperty("--strip-label", px(stripLabel, 10, 20));
    var cell = size(els.netto);
    if (cell.w <= 0) return;
    var wind = size(els.wind);
    var label = Math.max(10, Math.min(20, cell.w * 0.12, cell.h * 0.19));
    var value = Math.min(cell.w / 3.6, (cell.h - label) * 0.62);
    var windValue = Math.min(value, wind.w / 6.4, (wind.h - label) * 0.62);
    style.setProperty("--label", px(label, 10, 20));
    style.setProperty("--value", px(value, 12, 72));
    style.setProperty("--unit", px(value * 0.42, 8, 24));
    style.setProperty("--wind", px(windValue, 11, 72));
    style.setProperty("--arrow", px(windValue, 11, 60));
    style.setProperty("--inner-gap", px(value * 0.15, 2, 10));
  }

  return {draw: draw, fit: fit};
})();
