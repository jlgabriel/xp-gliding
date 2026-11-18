// XP-Gliding Flight Computer: start-up, the tabs and the bridge to Python (adapter/computer.py).
//
// Targets Chromium 117, X-Plane 12.4.4's browser (CEF): no JavaScript or CSS newer than that
// (no Promise.withResolvers, no Set methods, no CSS nesting); classic scripts, no modules, no
// fetch() of local files, since X-Plane's browser refuses both on file:// pages.
//
// The page draws and computes nothing that matters. Once, it asks Python for its setup (the
// map's tiles, xplane.xpg_setup); then for the state snapshot (xplane.xpg_state) at the rate the
// snapshot gives (poll_hz), and for the track's new points (xplane.xpg_track) when the snapshot
// says there are some. After every click it asks Python to give the keyboard back to the
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
  var VIEWS = ["map", "flight"];
  var pollTimer = null;
  var pollHz = null;
  var asking = false;
  var askingTrack = false;
  var view = null;  // the view shown; the first snapshot's until the pilot picks one
  var started = Date.now();
  var dev = /[?&]dev\b/.test(location.search);

  function status(text) {
    var el = document.getElementById("status");
    if (el.textContent !== text) el.textContent = text;
  }

  function bridge() {
    return typeof window.xplane === "object" && window.xplane !== null ? window.xplane : null;
  }

  function show(name) {
    if (VIEWS.indexOf(name) < 0 || name === view) return;
    view = name;
    document.body.setAttribute("data-view", name);
    if (name === "map") xpg.map.shown();
    else xpg.flight.fit();
  }

  function apply(s) {
    if (!s || typeof s !== "object") return;
    if (view === null) show(s.view || "map");
    xpg.flight.draw(s);
    xpg.map.draw(s);
    status(s.valid ? (view === "map" ? xpg.map.note() : "") : "waiting for the instruments");
    if (s.poll_hz !== pollHz) setRate(s.poll_hz);
    askTrack(xpg.map.trackWanted(s));
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
  window.addEventListener("resize", xpg.flight.fit);

  start();
})();
