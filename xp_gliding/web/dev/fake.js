// A fake window.xplane for developing the page in a desktop browser: open index.html?dev, or
// index.html?dev&offline for a map whose tiles never load, and &ago=600 to start ten minutes in.
// The glider glides north-east for 40 s, then circles three times in a 2 m/s thermal while drifting in a
// 12 kt wind, again and again; units switch every 20 s. The track is kept one point a second as
// nav/track.py keeps it, and answered in the same form. Never loaded in X-Plane (only with ?dev,
// and only while window.xplane is missing). Classic script, Chromium 117. License: GPL-3.0-or-later.
"use strict";

(function () {
  var ago = /[?&]ago=(\d+)/.exec(location.search);  // ?dev&ago=600: ten minutes flown already
  var t0 = Date.now() - (ago ? parseInt(ago[1], 10) * 1000 : 0);
  var offline = /[?&]offline\b/.test(location.search);
  var M_PER_DEG = 111195;
  var START = [-33.45, -70.55];
  var WIND_TO = 60, WIND_MS = 6.2;  // the wind blows from 240
  var points = [];  // [lat, lon], one a second
  var lastSecond = -1;

  function place(t) {
    // Where the glider is at t (s): a straight glide, then a circle, drifting with the wind.
    var D = Math.PI / 180;
    var cycle = t % 106, legs = Math.floor(t / 106);  // 40 s gliding, three 22 s circles
    var leg = 24 * 40;  // each glide's length; the circles end where they began
    var east = legs * leg * Math.sin(60 * D), north = legs * leg * Math.cos(60 * D);
    var heading;
    if (cycle < 40) {
      heading = 60;
      east += 24 * cycle * Math.sin(heading * D);
      north += 24 * cycle * Math.cos(heading * D);
    } else {
      // A right turn: the circle's centre is r to the right of where the glide ended.
      var r = 24 * 22 / (2 * Math.PI);
      heading = (60 + (cycle - 40) * 360 / 22) % 360;
      east += leg * Math.sin(60 * D) + r * (Math.sin(150 * D) + Math.sin((heading - 90) * D));
      north += leg * Math.cos(60 * D) + r * (Math.cos(150 * D) + Math.cos((heading - 90) * D));
    }
    east += WIND_MS * t * Math.sin(WIND_TO * Math.PI / 180);
    north += WIND_MS * t * Math.cos(WIND_TO * Math.PI / 180);
    // Sinking 1 m/s in the glide, climbing 2 m/s in the circles.
    var msl = 1200 + legs * 92 + (cycle < 40 ? -cycle : -40 + 2 * (cycle - 40));
    return {msl: msl, lat: START[0] + north / M_PER_DEG,
            lon: START[1] + east / (M_PER_DEG * Math.cos(START[0] * Math.PI / 180)),
            heading: heading, circling: cycle >= 40};
  }

  function snapshot() {
    var t = (Date.now() - t0) / 1000;
    var p = place(t);
    while (lastSecond < Math.floor(t)) {
      lastSecond++;
      var q = place(lastSecond);
      points.push([q.lat, q.lon, Math.round(q.msl)]);
    }
    var turn = p.heading;
    // Every third 10 s a steep dive, for the widest readings (-14.4 kt fits the default window).
    var dive = Math.floor(t / 10) % 3 === 2;
    var te = dive ? -7.41 : 2.0 + 1.6 * Math.sin((turn - 130) * Math.PI / 180) + 0.2 * Math.sin(t * 1.7);
    return {
      t: t, local_s: 13 * 3600 + 42 * 60 + t, valid: t > 1.5, units: Math.floor(t / 20) % 2 ? "aviation" : "metric", view: "map", poll_hz: 5,
      lat: p.lat, lon: p.lon, msl_m: p.msl, agl_m: p.msl - 600,
      track_deg: (turn + 8) % 360, heading_deg: turn, gs_ms: 24 + 5 * Math.cos(turn * Math.PI / 180),
      ias_ms: 23.5, tas_ms: 25.0,
      te_ms: te, netto_ms: te + 0.9, avg_ms: 1.7, thm_ms: 1.8, thm_valid: t > 8, thm_active: true,
      circling: p.circling, aid_valid: false, aid_core_az_deg: null, aid_amp_ms: null,
      wind_from_deg: 240, wind_ms: WIND_MS, top_m: 650 - 1.8 * t,
      track_n: points.length, track_epoch: 0
    };
  }

  function track(request) {
    var from = request && request.epoch === 0 && request.from >= 0 && request.from <= points.length
      ? request.from : 0;
    var end = Math.min(points.length, from + 5000);
    return {epoch: 0, from: from, n: points.length, more: end < points.length, points: points.slice(from, end)};
  }

  window.xplane = {
    xpg_setup: function () {
      return Promise.resolve({
        tiles: offline ? "https://tiles.invalid/{z}/{x}/{y}.png" : "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
        attribution: "Map data: © OpenStreetMap contributors, SRTM | Map style: © OpenTopoMap (CC-BY-SA)",
        max_zoom: 17
      });
    },
    xpg_state: function () { return Promise.resolve(snapshot()); },
    xpg_track: function (request) { return Promise.resolve(track(request)); },
    xpg_do: function (request) {
      if (request && request.cmd === "log") console.log("page:", request.text);
      return Promise.resolve({ok: true});
    }
  };
})();
