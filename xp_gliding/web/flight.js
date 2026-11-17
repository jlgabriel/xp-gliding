// XP-Gliding Flight Computer: the strip and the FLIGHT view, drawn from one snapshot.
// Text goes in with textContent only. Classic script, Chromium 117. License: GPL-3.0-or-later.
"use strict";

var xpg = window.xpg || {};
window.xpg = xpg;

xpg.flight = (function () {
  var f = xpg.format;
  var els = null;
  var shownUnits = null;

  function find() {
    var ids = ["strip-te", "strip-avg", "strip-alt", "te", "te-bar", "netto", "avg", "thm", "msl", "agl",
               "ias", "gs", "wind", "wind-arrow", "top"];
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
    set("strip-te", f.climb(s.te_ms, u));
    set("strip-avg", f.climb(s.avg_ms, u));
    set("strip-alt", f.height(s.msl_m, u, false));
    set("te", f.climb(s.te_ms, u));
    bar(s.te_ms, s.units);
    set("netto", f.climb(s.netto_ms, u));
    set("avg", f.climb(s.avg_ms, u));
    set("thm", s.thm_valid ? f.climb(s.thm_ms, u) : "--");
    els.thm.classList.toggle("left", s.thm_valid && !s.thm_active);
    set("msl", f.height(s.msl_m, u, false));
    set("agl", f.height(s.agl_m, u, false));
    set("ias", f.speed(s.ias_ms, u));
    set("gs", f.speed(s.gs_ms, u));
    set("wind", f.wind(s.wind_from_deg, s.wind_ms));
    windArrow(s);
    set("top", f.height(s.top_m, u, true));
  }

  return {draw: draw};
})();
