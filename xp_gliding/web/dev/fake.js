// A fake window.xplane for developing the page in a desktop browser: open index.html?dev.
// It answers xpg_state with a glider circling in a 2 m/s thermal while drifting in a 12 kt wind,
// and switches units every 20 s. Never loaded in X-Plane (only with ?dev, and only while
// window.xplane is missing). Classic script, Chromium 117. License: GPL-3.0-or-later.
"use strict";

(function () {
  var t0 = Date.now();

  function snapshot() {
    var t = (Date.now() - t0) / 1000;
    var turn = (t * 360 / 22) % 360;  // a 22 s circle
    // Every third 10 s a steep dive, for the widest readings (-14.4 kt fits the default window).
    var dive = Math.floor(t / 10) % 3 === 2;
    var te = dive ? -7.41 : 2.0 + 1.6 * Math.sin((turn - 130) * Math.PI / 180) + 0.2 * Math.sin(t * 1.7);
    return {
      t: t, valid: t > 1.5, units: Math.floor(t / 20) % 2 ? "aviation" : "metric", view: "flight", poll_hz: 5,
      lat: -33.45, lon: -70.55, msl_m: 1450 + 1.8 * t, agl_m: 850 + 1.8 * t,
      track_deg: (turn + 8) % 360, heading_deg: turn, gs_ms: 24 + 5 * Math.cos(turn * Math.PI / 180),
      ias_ms: 23.5, tas_ms: 25.0,
      te_ms: te, netto_ms: te + 0.9, avg_ms: 1.7, thm_ms: 1.8, thm_valid: t > 8, thm_active: true, circling: true,
      aid_valid: false, aid_core_az_deg: null, aid_amp_ms: null,
      wind_from_deg: 240, wind_ms: 6.2, top_m: 650 - 1.8 * t
    };
  }

  window.xplane = {
    xpg_state: function () { return Promise.resolve(snapshot()); },
    xpg_do: function (request) {
      if (request && request.cmd === "log") console.log("page:", request.text);
      return Promise.resolve({ok: true});
    }
  };
})();
