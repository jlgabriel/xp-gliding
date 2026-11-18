// XP-Gliding Flight Computer: numbers to text, in the pilot's units. The snapshot is SI and degrees
// true (nav/snapshot.py); only this file knows units. Metric: m/s, m, km/h. Aviation: knots, feet,
// knots. The wind is in knots with both, as on the HUD and in X-Plane's weather settings.
// Classic script, Chromium 117. License: GPL-3.0-or-later.
"use strict";

var xpg = window.xpg || {};
window.xpg = xpg;

xpg.format = (function () {
  var KT_PER_MS = 1 / 0.514444;
  var FT_PER_M = 1 / 0.3048;
  var KMH_PER_MS = 3.6;
  var NONE = "--";

  var UNITS = {
    metric: {climb: "m/s", height: "m", speed: "km/h", perClimb: 1, perHeight: 1, heightStep: 1, perSpeed: KMH_PER_MS},
    aviation: {climb: "kt", height: "ft", speed: "kt", perClimb: KT_PER_MS, perHeight: FT_PER_M, heightStep: 10, perSpeed: KT_PER_MS}
  };

  function units(name) {
    return UNITS[name] || UNITS.metric;
  }

  function known(v) {
    return typeof v === "number" && isFinite(v);
  }

  function signed(v, decimals) {
    var text = v.toFixed(decimals);
    if (text === (0).toFixed(decimals) || text === "-" + (0).toFixed(decimals)) return (0).toFixed(decimals);
    return (v > 0 ? "+" : "") + text;
  }

  function climb(ms, u) {
    return known(ms) ? signed(ms * u.perClimb, 1) : NONE;
  }

  function height(m, u, withSign) {
    if (!known(m)) return NONE;
    var v = Math.round(m * u.perHeight / u.heightStep) * u.heightStep;
    return withSign ? signed(v, 0) : v.toFixed(0);
  }

  // Never below zero: X-Plane's indicated airspeed goes negative with the wind from behind on the
  // ground, which no airspeed indicator shows.
  function speed(ms, u) {
    return known(ms) ? (Math.max(0, ms) * u.perSpeed).toFixed(0) : NONE;
  }

  function degrees(deg) {
    if (!known(deg)) return NONE;
    var d = Math.round(deg) % 360;
    if (d === 0) d = 360;
    return ("00" + d).slice(-3) + "°";
  }

  function wind(fromDeg, ms) {
    if (!known(ms)) return NONE;
    if (!known(fromDeg)) return "calm";
    return degrees(fromDeg) + " " + (ms * KT_PER_MS).toFixed(0);
  }

  // The simulator's local time of day, from seconds since midnight: "14:05".
  function clock(s) {
    if (!known(s)) return "--:--";
    var m = Math.floor(s / 60) % 1440;
    if (m < 0) m += 1440;
    return ("0" + Math.floor(m / 60)).slice(-2) + ":" + ("0" + m % 60).slice(-2);
  }

  return {units: units, known: known, climb: climb, height: height, speed: speed, degrees: degrees, wind: wind,
          clock: clock};
})();
