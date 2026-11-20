// XP-Gliding Flight Computer and Glide Computer: start-up, the layout, the tabs and the bridge to
// Python (adapter/computer.py). The snapshot says which computer the page is (layout) and, for the
// Glide Computer, its screen; the pilot's zoom and map display commands come in it too (keys).
//
// Targets Chromium 117, X-Plane 12.4.4's browser (CEF): no JavaScript or CSS newer than that
// (no Promise.withResolvers, no Set methods, no CSS nesting); classic scripts, no modules, no
// fetch() of local files, since X-Plane's browser refuses both on file:// pages.
//
// The page draws and computes nothing that matters. Once, it asks Python for its setup (the
// map's tiles, xplane.xpg_setup); then for the state snapshot (xplane.xpg_state) at the rate the
// snapshot gives (poll_hz), and for the track's new points (xplane.xpg_track) when the snapshot
// says there are some; for the task's list and the task when the snapshot's tasks_rev and
// task_rev change (task.js). After every click it asks Python to give the keyboard back to the
// simulator (xplane.xpg_do release_keys), since X-Plane's browser keeps it after a click.
// window.xplane may appear after these scripts run (first window after a cold start of X-Plane),
// so the page waits for it. index.html?dev draws from dev/fake.js instead.
// License: GPL-3.0-or-later.
"use strict";

var xpg = window.xpg || {};
window.xpg = xpg;

(function () {
  var WAIT_MS = 100;
  var DEV_AFTER_MS = 300;
  var SAY_WAITING_AFTER_MS = 2000;
  var VIEWS = ["map", "flight", "task"];
  var pollTimer = null;
  var pollHz = null;
  var asking = false;
  var askingTrack = false;
  var view = null;  // the view shown; the first snapshot's until the pilot picks one
  var viewSent = null;  // the view as Python last sent it: a new one (a command) is shown
  var layout = null;  // "flight" or "glide": which computer the page is
  var lastKey = null;  // the number of the last command done, from the snapshot's keys
  var started = Date.now();
  var dev = /[?&]dev\b/.test(location.search);

  function status(text) {
    var el = document.getElementById("status");
    if (el.textContent !== text) el.textContent = text;
  }

  function bridge() {
    return typeof window.xplane === "object" && window.xplane !== null ? window.xplane : null;
  }
  xpg.bridge = bridge;

  function show(name) {
    if (VIEWS.indexOf(name) < 0 || name === view) return;
    view = name;
    document.body.setAttribute("data-view", name);
    if (name === "map") xpg.map.shown();
    else if (name === "task") xpg.task.shown();
    else xpg.flight.fit();
  }

  // The computer the page is: the Flight Computer's views, or the Glide Computer's screens. Its map
  // is the same Leaflet map in either, drawn in that computer's way.
  function setLayout(name) {
    name = name === "glide" ? "glide" : "flight";
    if (name === layout) return;
    layout = name;
    document.body.setAttribute("data-layout", name);
    xpg.map.setLayout(name);
    if (name === "flight") {
      xpg.map.useZoom("map");
      var shown = view;
      view = null;
      show(shown || "map");
    }
    xpg.map.shown();
    fit();
  }

  // The pilot's commands that are the page's own: each done once, in order. The first snapshot's
  // are from before this page and are not done.
  function doKeys(keys) {
    if (!Array.isArray(keys)) return;
    for (var i = 0; i < keys.length; i++) {
      var n = keys[i][0], name = keys[i][1];
      if (lastKey !== null && n > lastKey) {
        if (name === "zoom_in") xpg.map.zoomBy(1);
        else if (name === "zoom_out") xpg.map.zoomBy(-1);
        else if (name === "map_mode_next" || name === "map_mode_prev") xpg.map.toggleTiles();
      }
      if (lastKey === null || n > lastKey) lastKey = n;
    }
    if (lastKey === null) lastKey = 0;
  }

  function apply(s) {
    if (!s || typeof s !== "object") return;
    setLayout(s.layout);
    if (layout === "glide") {
      xpg.glide.show(s.screen);
      xpg.glide.draw(s);
    } else {
      if (view === null || (s.view && s.view !== viewSent)) show(s.view || "map");
      xpg.flight.draw(s);
    }
    viewSent = s.view;
    doKeys(s.keys);
    xpg.map.draw(s);
    xpg.task.draw(s);
    var onMap = layout === "glide" || view === "map";
    status(s.valid ? (onMap ? xpg.map.note() : "") : "waiting for the instruments");
    if (s.poll_hz !== pollHz) setRate(s.poll_hz);
    askTrack(xpg.map.trackWanted(s));
  }

  function fit() {
    if (layout === "glide") xpg.glide.fit();
    else xpg.flight.fit();
  }

  function ask() {
    if (asking) return;  // one call in flight at a time
    asking = true;
    bridge().xpg_state().then(function (s) {
      asking = false;
      apply(s);
    }, function (e) {
      asking = false;
      status("no answer from X-Plane: " + e);
    });
  }

  // The track's points the page does not have; again at once while Python says there are more.
  function askTrack(wanted) {
    if (!wanted || askingTrack) return;
    askingTrack = true;
    bridge().xpg_track(wanted).then(function (r) {
      askingTrack = false;
      xpg.map.addTrack(r);
      if (r && r.more) askTrack({epoch: r.epoch, from: r.from + r.points.length});
    }, function () {
      askingTrack = false;
    });
  }

  function setRate(hz) {
    pollHz = hz;
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = typeof hz === "number" && hz > 0 ? setInterval(ask, 1000 / hz) : null;
  }

  // After a click the keys would stay with the page: Python hands them back to the simulator.
  window.addEventListener("pointerup", function () {
    var x = bridge();
    if (x) x.xpg_do({cmd: "release_keys"});
  }, true);

  window.addEventListener("error", function (e) {
    var x = bridge();
    if (x) x.xpg_do({cmd: "log", text: String(e.message) + " @ " + e.filename + ":" + e.lineno});
  });

  // The tabs: shown at once, and kept by Python for the next window.
  var buttons = document.querySelectorAll("#tabs button");
  for (var i = 0; i < buttons.length; i++) {
    buttons[i].addEventListener("click", function (e) {
      var name = e.currentTarget.getAttribute("data-view");
      show(name);
      var x = bridge();
      if (x) x.xpg_do({cmd: "set", view: name});
    });
  }

  function loadFake() {
    var script = document.createElement("script");
    script.src = "dev/fake.js";
    document.body.appendChild(script);
  }

  function begin(setup) {
    try {
      xpg.map.init(document.getElementById("map"), setup);
    } catch (e) {
      status("the map did not start: " + e);
    }
    ask();
  }

  function start() {
    var x = bridge();
    if (x) {
      x.xpg_setup().then(begin, function () { begin(null); });
      return;
    }
    var waited = Date.now() - started;
    if (dev && waited >= DEV_AFTER_MS && !xpg.fakeLoading) {
      xpg.fakeLoading = true;
      loadFake();
    }
    if (waited >= SAY_WAITING_AFTER_MS) status("waiting for X-Plane");
    setTimeout(start, WAIT_MS);
  }

  // The text follows the window's size (flight.js); a resize from X-Plane's frame reaches the page
  // as the viewport's (X-Plane resizes it, never scales it).
  xpg.flight.fit();
  window.addEventListener("resize", fit);

  start();
})();
