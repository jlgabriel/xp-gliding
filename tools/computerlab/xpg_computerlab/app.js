// Computer lab page: a classic script. It finds what loaded, polls Python through
// xplane.lab_ping at the rate Python asks for, and reports everything every 2 s through
// xplane.lab_report. Measurement tool, not part of the plugin. License: GPL-3.0-or-later.
"use strict";

var xpgLab = (function () {
  var REPORT_MS = 2000;
  var PROBE = "http://127.0.0.1:8765/";
  var TILES = "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png";
  var CENTRE = [-33.45, -70.66];  // Santiago
  var hasXplane = typeof window.xplane === "object" && window.xplane !== null;

  var S = {
    seq: 0, started: performance.now(),
    rate: 5, pan: false, blur: false, blurs: 0, pollTimer: null,
    rtts: [], pingsOk: 0, pingsErr: 0, lastPingErr: "",
    intervals: 0, rafs: 0,
    ev: {wheel: 0, pointerdown: 0, pointermove: 0, pointerup: 0, click: 0, keydown: 0,
         keys: [], focus: 0, blur: 0, visibility: []},
    push: {n: 0, gaps: [], last: null},
    tiles: {load: 0, error: 0, firstMs: null},
    probe: {cached: "pending", fresh: "pending"},
    fetchLocal: "pending", storage: null, errors: [],
    map: null, panDir: 1
  };

  function log(text) {
    var el = document.getElementById("log");
    el.textContent = (text + "\n" + el.textContent).slice(0, 4000);
  }

  window.addEventListener("error", function (e) {
    S.errors.push(String(e.message || e.type) + " @ " + (e.filename || (e.target && e.target.src) || ""));
  }, true);

  // --- what loaded -----------------------------------------------------------------

  function cssOk() {
    return getComputedStyle(document.body).backgroundColor === "rgb(12, 34, 56)";
  }

  function checkStorage() {
    try {
      var n = parseInt(localStorage.getItem("xpgLabRuns") || "0", 10) + 1;
      localStorage.setItem("xpgLabRuns", String(n));
      S.storage = n;
    } catch (e) {
      S.storage = "error: " + e;
    }
  }

  function checkFetch() {
    try {
      fetch("data.json").then(function (r) { return r.json(); })
        .then(function (d) { S.fetchLocal = d.fetched ? "ok" : "odd"; })
        .catch(function (e) { S.fetchLocal = "error: " + e; });
    } catch (e) {
      S.fetchLocal = "throw: " + e;
    }
  }

  function probe(key, url) {
    var img = new Image();
    img.onload = function () { S.probe[key] = "load"; };
    img.onerror = function () { S.probe[key] = "error"; };
    img.src = url;
  }

  function resources() {
    // transferSize 0 with a size known means served from cache (the probe server sends
    // Timing-Allow-Origin so its entries carry sizes).
    return performance.getEntriesByType("resource")
      .filter(function (r) { return r.name.indexOf(PROBE) === 0 || r.name.indexOf("opentopomap") >= 0; })
      .slice(-12)
      .map(function (r) {
        return {name: r.name.replace(/^https?:\/\//, "").slice(0, 60),
                transfer: r.transferSize, body: r.decodedBodySize, ms: Math.round(r.duration)};
      });
  }

  function startMap() {
    if (typeof L === "undefined") {
      S.errors.push("Leaflet not loaded");
      return;
    }
    S.map = L.map("map", {zoomControl: true}).setView(CENTRE, 10);
    var layer = L.tileLayer(TILES, {
      maxZoom: 15, subdomains: "abc", updateWhenIdle: true, keepBuffer: 1,
      attribution: "Map data © OpenStreetMap contributors, SRTM | Map style © OpenTopoMap (CC-BY-SA)"
    }).addTo(S.map);
    layer.on("tileload", function () {
      S.tiles.load++;
      if (S.tiles.firstMs === null) S.tiles.firstMs = Math.round(performance.now() - S.started);
    });
    layer.on("tileerror", function () { S.tiles.error++; });
    L.control.scale().addTo(S.map);
    // Pan back and forth over the same ground: after the first pass tiles come from cache,
    // so the lab never walks the provider's tiles.
    setInterval(function () {
      if (!S.pan) return;
      S.map.panBy([S.panDir * 200, 0], {duration: 1.0});
      S.panDir = -S.panDir;
    }, 1200);
  }

  // --- input and life cycle ----------------------------------------------------------

  ["wheel", "pointerdown", "pointermove", "pointerup", "click"].forEach(function (name) {
    window.addEventListener(name, function () { S.ev[name]++; }, true);
  });
  window.addEventListener("keydown", function (e) {
    S.ev.keydown++;
    if (S.ev.keys.length < 20) S.ev.keys.push(e.key);
  }, true);
  // Focus mode "blur": give the keyboard up after every click, so keys go back to the sim.
  window.addEventListener("pointerup", function () {
    if (!S.blur) return;
    setTimeout(function () {
      if (document.activeElement && document.activeElement.blur) document.activeElement.blur();
      window.blur();
      S.blurs++;
    }, 0);
  }, true);
  window.addEventListener("focus", function () { S.ev.focus++; });
  window.addEventListener("blur", function () { S.ev.blur++; });
  document.addEventListener("visibilitychange", function () {
    S.ev.visibility.push([Math.round(performance.now() - S.started), document.visibilityState]);
  });

  setInterval(function () { S.intervals++; }, 100);
  (function frame() { S.rafs++; requestAnimationFrame(frame); })();

  // --- the bridge --------------------------------------------------------------------

  function ping() {
    var seq = ++S.seq;
    var t0 = performance.now();
    window.xplane.lab_ping(seq).then(function (r) {
      S.rtts.push(performance.now() - t0);
      S.pingsOk++;
      if (r && r.rate !== undefined && r.rate !== S.rate) setRate(r.rate);
      if (r && r.pan !== undefined) S.pan = r.pan;
      if (r && r.blur !== undefined) S.blur = r.blur;
    }, function (e) {
      S.pingsErr++;
      S.lastPingErr = String(e);
    });
  }

  function setRate(rate) {
    S.rate = rate;
    if (S.pollTimer) clearInterval(S.pollTimer);
    S.pollTimer = rate > 0 ? setInterval(ping, 1000 / rate) : null;
  }

  function stats(values) {
    if (!values.length) return null;
    var v = values.slice().sort(function (a, b) { return a - b; });
    function q(p) { return Math.round(v[Math.min(v.length - 1, Math.floor(p * v.length))] * 100) / 100; }
    return {n: v.length, p50: q(0.5), p95: q(0.95), max: q(1)};
  }

  function onPush(n) {
    var now = performance.now();
    if (S.push.last !== null) S.push.gaps.push(now - S.push.last);
    S.push.last = now;
    S.push.n++;
  }

  function report() {
    var r = {
      seq: S.seq, page_ms: Math.round(performance.now() - S.started),
      href: location.href, origin: String(location.origin), ua: navigator.userAgent,
      dpr: window.devicePixelRatio, w: window.innerWidth, h: window.innerHeight,
      classic: true, inline_classic: !!window.inlineClassicOk, css: cssOk(),
      inline_module: !!window.inlineModuleOk, module_file: !!window.moduleFileOk,
      leaflet: typeof L !== "undefined", fetch_local: S.fetchLocal, storage: S.storage,
      hidden: document.hidden, vis: document.visibilityState, has_focus: document.hasFocus(),
      intervals: S.intervals, rafs: S.rafs,
      rate: S.rate, pings_ok: S.pingsOk, pings_err: S.pingsErr, last_ping_err: S.lastPingErr,
      rtt: stats(S.rtts),
      push: {n: S.push.n, gap: stats(S.push.gaps)},
      tiles: S.tiles, probe: S.probe, resources: resources(),
      ev: S.ev, blurs: S.blurs, errors: S.errors.slice(-10)
    };
    S.intervals = 0;
    S.rafs = 0;
    S.rtts = [];
    S.push.gaps = [];
    document.getElementById("status").textContent =
      "report " + r.page_ms + " ms, pings " + S.pingsOk + ", tiles " + S.tiles.load + "/" + S.tiles.error;
    document.getElementById("rtt").textContent = r.rtt ? "rtt p50 " + r.rtt.p50 + " ms" : "";
    if (hasXplane) window.xplane.lab_report(r);
    else log(JSON.stringify(r));
  }

  // --- start ---------------------------------------------------------------------------

  checkStorage();
  checkFetch();
  probe("cached", PROBE + "probe-cached.png");
  probe("fresh", PROBE + "probe.png?t=" + Date.now());
  startMap();
  if (hasXplane) setRate(S.rate);
  else S.errors.push("no window.xplane (desktop browser)");
  setTimeout(report, 500);
  setInterval(report, REPORT_MS);

  return {onPush: onPush, state: S};
})();
