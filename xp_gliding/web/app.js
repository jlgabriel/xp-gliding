// XP-Gliding Flight Computer: start-up and the bridge to Python (adapter/computer.py).
//
// Targets Chromium 117, X-Plane 12.4.4's browser (CEF): no JavaScript or CSS newer than that
// (no Promise.withResolvers, no Set methods, no CSS nesting); classic scripts, no modules, no
// fetch() of local files, since X-Plane's browser refuses both on file:// pages.
//
// The page draws and computes nothing that matters. It asks Python for the state snapshot
// (xplane.xpg_state) at the rate the snapshot gives (poll_hz), and after every click asks Python
// to give the keyboard back to the simulator (xplane.xpg_do release_keys), since X-Plane's browser
// keeps it after a click. window.xplane may appear after these scripts run (first window after a
// cold start of X-Plane), so the page waits for it. index.html?dev draws from dev/fake.js instead.
// License: GPL-3.0-or-later.
"use strict";

var xpg = window.xpg || {};
window.xpg = xpg;

(function () {
  var WAIT_MS = 100;
  var DEV_AFTER_MS = 300;
  var SAY_WAITING_AFTER_MS = 2000;
  var pollTimer = null;
  var pollHz = null;
  var asking = false;
  var started = Date.now();
  var dev = /[?&]dev\b/.test(location.search);

  function status(text) {
    var el = document.getElementById("status");
    if (el.textContent !== text) el.textContent = text;
  }

  function bridge() {
    return typeof window.xplane === "object" && window.xplane !== null ? window.xplane : null;
  }

  function apply(s) {
    if (!s || typeof s !== "object") return;
    xpg.flight.draw(s);
    status(s.valid ? "" : "waiting for the instruments");
    if (s.poll_hz !== pollHz) setRate(s.poll_hz);
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

  function loadFake() {
    var script = document.createElement("script");
    script.src = "dev/fake.js";
    document.body.appendChild(script);
  }

  function start() {
    if (bridge()) {
      ask();
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
