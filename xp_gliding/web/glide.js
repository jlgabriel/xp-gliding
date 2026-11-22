// XP-Gliding Glide Computer: its header and its six readings, for the screen shown. The functions
// of Condor 3's flight computer, drawn our way; the map is map.js's, in its "glide" layout.
//
//   GLIDE     Dis  DH   E      /  VMG   DDH  ReqE
//   INFO      tTime tSpd hAGL  /  TTG   GS   tDelta
//   THERMAL   Dis  DH   TAve   /  T4Ave DDH  TGain
//
// Dis, DH, DDH, ReqE, VMG and TTG are worked out for the target (the header's "TO:"), which the
// pilot browses along the task with the arrows or X-Plane commands; Python does all of it
// (nav/task.py, nav/glide.py) and the page formats. DDH and TTG need the polar and a MacCready,
// which come later: "--" until then, and tDelta has no meaning without an AAT task.
// Text goes in with textContent only. Classic script, Chromium 117. License: GPL-3.0-or-later.
"use strict";

var xpg = window.xpg || {};
window.xpg = xpg;

xpg.glide = (function () {
  var f = xpg.format;
  var NONE = "--";
  var SCREENS = ["glide", "info", "thermal"];
  var NAMES = {glide: "GLIDE", info: "INFO", thermal: "THERMAL"};
  var els = null;
  var screen = null;

  function target(s) {
    return s.nav && s.nav.target ? s.nav.target : null;
  }

  function whole(v) {
    return f.known(v) ? Math.round(v).toFixed(0) : NONE;
  }

  // A speed that may be negative: VMG going away from the target.
  function signedSpeed(ms, u) {
    return f.known(ms) ? Math.round(ms * u.perSpeed).toFixed(0) : NONE;
  }

  // Minutes and seconds under an hour, hours and minutes above: [text, its unit].
  function duration(s) {
    if (!f.known(s)) return [NONE, "m:s"];
    var t = Math.max(0, Math.round(s));
    if (t < 3600) return [("0" + Math.floor(t / 60)).slice(-2) + ":" + ("0" + t % 60).slice(-2), "m:s"];
    var m = Math.floor(t / 60);
    return [Math.floor(m / 60) + ":" + ("0" + m % 60).slice(-2), "h:m"];
  }

  // Each reading: its label, its unit (a key of the units, a fixed text, or none), and from the
  // snapshot its text and a class for its colour.
  var DIS = {label: "Dis", unit: "distance", text: function (s, u) { var t = target(s); return f.distance(t && t.dist_m, u); }};
  var DH = {label: "DH", unit: "height", text: function (s, u) { var t = target(s); return f.height(t && t.dh_m, u, false); }};
  var DDH = {label: "DDH", unit: "height", text: function () { return NONE; }};
  var READINGS = {
    glide: [
      DIS, DH,
      {label: "E", text: function (s) { return whole(s.ld); }},
      {label: "VMG", unit: "speed", text: function (s, u) { return signedSpeed(s.vmg_ms, u); }},
      DDH,
      {label: "ReqE", text: function (s) { var t = target(s); return whole(t && t.req_ld); }}
    ],
    info: [
      {label: "tTime", time: function (s) { return s.nav && s.nav.task_s; }},
      {label: "tSpd", unit: "speed", text: function (s, u) { return f.speed(s.nav && s.nav.task_speed_ms, u); }},
      {label: "hAGL", unit: "height", text: function (s, u) { return f.height(s.agl_m, u, false); }},
      {label: "TTG", time: function () { return null; }},
      {label: "GS", unit: "speed", text: function (s, u) { return f.speed(s.gs_ms, u); }},
      {label: "tDelta", time: function () { return null; }}
    ],
    thermal: [
      DIS, DH,
      {label: "TAve", unit: "climb", climb: true,
       text: function (s, u) { return s.thm_valid ? f.climb(s.thm_ms, u) : NONE; }, value: function (s) { return s.thm_valid ? s.thm_ms : null; }},
      {label: "T4Ave", unit: "climb", climb: true,
       text: function (s, u) { return f.climb(s.thm4_ms, u); }, value: function (s) { return s.thm4_ms; }},
      DDH,
      {label: "TGain", unit: "height", text: function (s, u) { return f.height(s.thm_gain_m, u, false); }}
    ]
  };

  function find() {
    els = {screen: document.getElementById("g-screen"), tag: document.getElementById("g-tag"),
           to: document.getElementById("g-to"), toWord: document.querySelector("#g-to .to"),
           limit: document.getElementById("g-limit"),
           name: document.getElementById("g-name"), clock: document.getElementById("g-clock"), cells: []};
    var cells = document.querySelectorAll("#readings .cell");
    for (var i = 0; i < cells.length; i++) {
      els.cells.push({cell: cells[i], label: cells[i].querySelector(".label"), value: cells[i].querySelector(".value")});
    }
    els.screen.addEventListener("click", function () {
      var next = SCREENS[(SCREENS.indexOf(screen) + 1) % SCREENS.length];
      xpg.glide.show(next);
      xpg.glide.chosen = {screen: next, at: Date.now()};  // app.js: until Python has it too
      send({cmd: "set", screen: next});
    });
    document.getElementById("g-task").addEventListener("click", function () {
      setTaskShown(!document.body.hasAttribute("data-gtask"));
    });
    var steps = document.querySelectorAll("#ghead .g-step");
    for (var k = 0; k < steps.length; k++) {
      steps[k].addEventListener("click", function (e) {
        send({cmd: "target", delta: parseInt(e.currentTarget.getAttribute("data-delta"), 10)});
      });
    }
  }

  function send(request) {
    var x = xpg.bridge();
    if (x) x.xpg_do(request);
  }

  function setText(el, text) {
    if (el.textContent !== text) el.textContent = text;
  }

  // The Flight Computer's TASK view, over the map and readings: the picker and the points. Closed
  // again by the button, by a screen chosen, or once a task picked has come (task.js).
  function setTaskShown(on) {
    if (on === document.body.hasAttribute("data-gtask")) return;
    if (on) {
      document.body.setAttribute("data-gtask", "");
      xpg.task.shown();
    } else {
      document.body.removeAttribute("data-gtask");
      xpg.map.shown();
      fit();
    }
  }

  // The screen shown: its name in the header, its zoom on the map.
  function show(name) {
    if (!els) find();
    if (SCREENS.indexOf(name) < 0) name = "glide";
    if (name !== screen) setTaskShown(false);
    if (name === screen) return;
    screen = name;
    setText(els.screen, NAMES[name]);
    document.body.setAttribute("data-screen", name);
    xpg.map.useZoom(name);
  }

  // Back from the Flight Computer, which left the map at its own zoom and colours: the next show
  // applies the screen again, the same screen as before included.
  function forget() {
    screen = null;
  }

  function draw(s) {
    if (!els) find();
    var u = f.units(s.units);
    setText(els.clock, f.clock(s.local_s));
    var t = target(s);
    // The task flown: FINISHED in green in place of TO:, while the target is still the finish.
    var done = !!(s.nav && s.nav.finished && t && t.role === "finish");
    setText(els.toWord, done ? "FINISHED" : "TO:");
    els.to.classList.toggle("done", done);
    setText(els.tag, t ? t.label : "");
    els.tag.style.display = t ? "" : "none";
    setText(els.name, t ? t.name : NONE);
    // The height limits, while the target is the point flown to: they are its zone's.
    xpg.task.drawLimit(els.limit, s.nav && t && t.index === s.nav.index ? s.nav : null, u, true);
    var list = READINGS[screen] || READINGS.glide;
    for (var i = 0; i < els.cells.length; i++) {
      var r = list[i], c = els.cells[i];
      var text, unit = r.unit ? u[r.unit] : "";
      if (r.time) {
        var d = duration(r.time(s));
        text = d[0];
        unit = d[1];
      } else {
        text = r.text(s, u);
      }
      setText(c.label, unit ? r.label + " [" + unit + "]" : r.label);
      setText(c.value, text);
      var v = r.climb ? r.value(s) : null;
      c.cell.classList.toggle("up", r.climb === true && f.known(v) && v > 0.05);
      c.cell.classList.toggle("down", r.climb === true && f.known(v) && v < -0.05);
    }
  }

  // --- sizes: measured from a cell, as flight.js does, so the numbers fill them in any window ---

  function px(v, lo, hi) {
    return Math.max(lo, Math.min(hi, v)).toFixed(1) + "px";
  }

  function fit() {
    if (!els) find();
    var r = els.cells[0].cell.getBoundingClientRect();
    if (r.width <= 0) return;
    var w = r.width - 10, h = r.height;
    var label = Math.max(10, Math.min(18, w * 0.13, h * 0.24));
    var value = Math.min(w / 3.3, (h - label) * 0.78);
    var style = document.documentElement.style;
    style.setProperty("--g-label", px(label, 10, 18));
    style.setProperty("--g-value", px(value, 12, 80));
    var head = document.getElementById("ghead").getBoundingClientRect();
    style.setProperty("--g-head", px(Math.min(head.width / 26, 18), 11, 18));
  }

  return {draw: draw, show: show, forget: forget, fit: fit, setTaskShown: setTaskShown};
})();
