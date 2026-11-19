// XP-Gliding Flight Computer: the MAP view. Leaflet 1.9.4 (vendor/leaflet), north up.
//
// Draws what Python sends and computes nothing that matters: the glider at its place, turned to
// its heading; the wind at the glider, an arrow pointing where it goes (the map is north up) and
// its speed in knots, as on the HUD; the track as Python kept it (xpg_track, one point a second),
// coloured by height from blue (the flight's lowest) to red (its highest), with a legend; raster tiles from the
// address in the settings, with their attribution always shown; a lat/lon grid under the tiles,
// which shows where tiles do not load (no network), so glider and track still have a frame.
// With a task (task.js gives it, as xpg_task sent it): its legs, its points named, each zone as
// Python shaped it (a circle, a line, sectors), the zone flown to marked, and a line from the
// glider to its point. The task is under the track: the pilot's own line stays on top.
//
// Cost (stage 0, V8): a map that moves all the time costs X-Plane's main thread about 116 ms a
// second, so nothing here animates by itself. Follow mode moves the map at most once a second,
// without animation, and only once the glider is a few pixels off the centre; tiles fade in at
// once and a drag stops dead. Zooming is the pilot's, and animates.
//
// Text from settings (the attribution) goes in escaped: Leaflet writes it as HTML, and a link
// would take X-Plane's browser window away from the page.
// Classic script, Chromium 117. License: GPL-3.0-or-later.
"use strict";

var xpg = window.xpg || {};
window.xpg = xpg;

xpg.map = (function () {
  var FOLLOW_EVERY_MS = 1000;
  var FOLLOW_OFF_PX = 2;  // the map follows once the glider is this far off its centre
  var DEFAULT_ZOOM = 12;
  var MIN_ZOOM = 5;
  // The track's colours, low to high, and how its scale moves: in whole steps, never under a
  // span, so that a climb does not recolour the whole line every second.
  var TRACK_COLOURS = ["#2f6bff", "#00b4d8", "#22c55e", "#d4d81c", "#ff9a1f", "#ff3b30"];
  var TRACK_STEP_M = 100;
  var TRACK_MIN_SPAN_M = 300;
  // Points held at most, as Python keeps them (nav/track.py: six hours at one a second); past
  // this the oldest go, this many at a time, so that the line is built again only now and then.
  var TRACK_CAPACITY = 6 * 3600;
  var TRACK_TRIM = 600;
  var GRID_STEPS = [10, 5, 2, 1, 0.5, 0.2, 0.1, 0.05, 0.02, 0.01, 0.005, 0.002, 0.001];  // degrees
  var GLIDER_SVG =
    '<svg viewBox="-16 -16 32 32" width="32" height="32" aria-hidden="true">' +
    '<g class="outline"><path d="M0,-7 L0,10 M-15,-1.5 L15,-1.5 M-4.5,10 L4.5,10"/></g>' +
    '<g class="body"><path d="M0,-7 L0,10 M-15,-1.5 L15,-1.5 M-4.5,10 L4.5,10"/></g></svg>';

  var map = null;
  var tiles = null;
  var glider = null;
  var gliderEl = null;
  var gliderAt = null;  // the layer pixel the glider was last put at
  var gliderTurn = "";  // and its last rotation
  var windArrow = null;
  var windText = null;
  var windTurn = null;
  var trackLayer = null;  // the track's lines, one per run of a colour
  var held = [];  // every point held, [lat, lon, msl]
  var lo = null, hi = null;  // the colour scale (m MSL)
  var seg = null, segPoints = null, segBand = -1;  // the last line, its points and colour
  var legend = null;
  var grid = null;
  var scale = null;
  var followButton = null;
  var following = true;
  var lastFollow = 0;
  var placed = false;  // the map has a view, from the first known place
  var unitsShown = null;
  var tileErrors = 0;
  var tileLoads = 0;
  var trackEpoch = null;
  var trackNext = 0;  // the number of the point after the last held
  var newLine = null;  // a whole new line for the next state, or null
  var newPoints = [];  // points to add to the line at the next state
  var taskLayer = null;  // the task's legs, zones and names
  var taskZones = [];  // each point's zone layers
  var taskPoints = null;  // [lat, lon] of each point
  var activeIndex = -1;  // the zone marked as the one flown to
  var nextLine = null;  // from the glider to the point flown to
  var pendingFit = null;  // bounds to show once the map is shown: a hidden map measures nothing
  var ZONE_STYLE = {weight: 1.5, opacity: 0.9, fillOpacity: 0.08};
  var ACTIVE_STYLE = {weight: 3, opacity: 1, fillOpacity: 0.22};
  var TASK_COLOUR = "#ff4fd8";

  function escapeText(text) {
    return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function storedZoom() {
    try {
      var z = parseInt(localStorage.getItem("xpg.map.zoom"), 10);
      return isFinite(z) ? z : DEFAULT_ZOOM;
    } catch (e) {
      return DEFAULT_ZOOM;
    }
  }

  function storeZoom() {
    try { localStorage.setItem("xpg.map.zoom", String(map.getZoom())); } catch (e) { /* not kept */ }
  }

  // The scale in the pilot's units: metric as Leaflet draws it, nautical miles (feet below one) for
  // aviation, which Leaflet does not have.
  var Scale = L.Control.Scale.extend({
    options: {position: "bottomleft", metric: true, imperial: false, maxWidth: 90},
    setNautical: function (on) {
      this._nautical = on;
      if (this._map && this._map._loaded) this._update();
    },
    _updateMetric: function (maxMeters) {
      if (!this._nautical) {
        L.Control.Scale.prototype._updateMetric.call(this, maxMeters);
        return;
      }
      var maxNm = maxMeters / 1852;
      if (maxNm >= 1) {
        var nm = this._getRoundNum(maxNm);
        this._updateScale(this._mScale, nm + " nm", nm / maxNm);
      } else {
        var maxFt = maxMeters / 0.3048;
        var ft = this._getRoundNum(maxFt);
        this._updateScale(this._mScale, ft + " ft", ft / maxFt);
      }
    }
  });

  // Follow: on, the map keeps the glider in its centre; a drag turns it off, the button back on.
  var Follow = L.Control.extend({
    options: {position: "topright"},
    onAdd: function () {
      var el = L.DomUtil.create("div", "leaflet-bar follow");
      var a = L.DomUtil.create("a", "", el);
      a.href = "#";
      a.title = "Follow the glider";
      a.setAttribute("role", "button");
      a.innerHTML = '<svg viewBox="-10 -10 20 20" width="18" height="18" aria-hidden="true">' +
        '<circle r="6"/><path d="M0,-9 L0,-4 M0,4 L0,9 M-9,0 L-4,0 M4,0 L9,0"/></svg>';
      L.DomEvent.disableClickPropagation(el);
      L.DomEvent.on(a, "click", function (e) {
        L.DomEvent.preventDefault(e);
        setFollow(!following);
      });
      followButton = el;
      return el;
    }
  });

  // The wind at the glider: an arrow pointing where the air goes, and its speed in knots.
  var Wind = L.Control.extend({
    options: {position: "topright"},
    onAdd: function () {
      var el = L.DomUtil.create("div", "wind-box");
      el.innerHTML = '<svg viewBox="-10 -10 20 20" width="26" height="26" aria-hidden="true">' +
        '<path d="M0,-8 L4,1 L1,1 L1,8 L-1,8 L-1,1 L-4,1 Z"/></svg><span></span>';
      windArrow = el.firstChild;
      windText = el.lastChild;
      L.DomEvent.disableClickPropagation(el);
      return el;
    }
  });

  // Changed only when what it shows changes: a still page draws no frame.
  function drawWind(s) {
    var f = xpg.format;
    var calm = !f.known(s.wind_from_deg);
    var turn = calm ? "" : "rotate(" + ((s.wind_from_deg + 180) % 360).toFixed(0) + "deg)";
    var text = !f.known(s.wind_ms) ? "--" : calm ? "calm" : (s.wind_ms / 0.514444).toFixed(0) + " kt";
    if (turn !== windTurn) {
      windTurn = turn;
      windArrow.style.transform = turn;
      windArrow.style.visibility = calm ? "hidden" : "visible";
    }
    if (text !== windText.textContent) windText.textContent = text;
  }

  function setFollow(on) {
    following = on;
    if (followButton) followButton.classList.toggle("on", on);
    if (map) map.options.scrollWheelZoom = map.options.doubleClickZoom = on ? "center" : true;
    lastFollow = 0;  // at the next state
  }

  // --- the grid, under the tiles ------------------------------------------------------------

  function gridStep(span) {
    for (var i = 0; i < GRID_STEPS.length; i++) {
      if (span / GRID_STEPS[i] >= 3) return GRID_STEPS[i];
    }
    return GRID_STEPS[GRID_STEPS.length - 1];
  }

  function drawGrid() {
    if (!map || !placed) return;
    var b = map.getBounds().pad(0.2);
    var step = gridStep(Math.max(b.getNorth() - b.getSouth(), 1e-6));
    var south = Math.max(-85, b.getSouth()), north = Math.min(85, b.getNorth());
    var west = b.getWest(), east = b.getEast();
    var lines = [];
    var v;
    for (v = Math.ceil(south / step) * step; v <= north; v += step) lines.push([[v, west], [v, east]]);
    for (v = Math.ceil(west / step) * step; v <= east; v += step) lines.push([[south, v], [north, v]]);
    grid.setLatLngs(lines);
  }

  // --- set up -------------------------------------------------------------------------------

  function init(el, setup) {
    map = L.map(el, {
      zoomControl: true,
      attributionControl: false,
      minZoom: MIN_ZOOM,
      maxZoom: (setup && setup.max_zoom) || 17,
      fadeAnimation: false,
      inertia: false,
      scrollWheelZoom: "center",
      doubleClickZoom: "center",
      keyboard: false,
      boxZoom: false,
      worldCopyJump: false
    });
    map.createPane("grid");
    map.getPane("grid").style.zIndex = 150;  // under the tiles (200): seen only where they are missing
    grid = L.polyline([], {pane: "grid", renderer: L.svg({pane: "grid"}), className: "grid-line",
                          interactive: false, weight: 1}).addTo(map);
    L.control.attribution({prefix: "Leaflet"}).addTo(map);
    if (setup && setup.tiles) {
      tiles = L.tileLayer(setup.tiles, {
        subdomains: "abc",
        maxZoom: map.getMaxZoom(),
        maxNativeZoom: map.getMaxZoom(),
        updateWhenIdle: true,
        updateWhenZooming: false,
        keepBuffer: 1,
        attribution: escapeText(setup.attribution || "")
      });
      tiles.on("tileerror", function () { tileErrors++; });
      tiles.on("tileload", function () { tileLoads++; tileErrors = 0; });
      tiles.addTo(map);
    }
    map.createPane("task");
    map.getPane("task").style.zIndex = 350;  // over the tiles, under the track (overlays, 400)
    taskLayer = L.layerGroup().addTo(map);
    trackLayer = L.layerGroup().addTo(map);
    legend = new Legend().addTo(map);
    glider = L.marker([0, 0], {
      icon: L.divIcon({className: "glider", html: GLIDER_SVG, iconSize: [32, 32], iconAnchor: [16, 16]}),
      interactive: false, keyboard: false
    });
    scale = new Scale().addTo(map);
    new Follow().addTo(map);
    new Wind().addTo(map);
    setFollow(true);
    map.on("dragstart", function () { setFollow(false); });
    map.on("moveend", drawGrid);
    map.on("zoomend", storeZoom);
  }

  // --- each state ---------------------------------------------------------------------------

  function draw(s) {
    if (!map) return;
    flushTrack();
    if (unitsShown !== s.units) {
      unitsShown = s.units;
      scale.setNautical(s.units === "aviation");
      drawLegend();
    }
    drawWind(s);
    var f = xpg.format;
    if (!f.known(s.lat) || !f.known(s.lon)) {
      if (glider._map) glider.remove();
      return;
    }
    var here = L.latLng(s.lat, s.lon);
    if (!placed) {
      placed = true;
      map.setView(here, storedZoom(), {animate: false});
    }
    // Moved only once it would show: in straight flight the glider crosses a pixel about once a
    // second, and a page that changes nothing draws no frame for X-Plane to take.
    var at = map.latLngToLayerPoint(here).round();
    var moved = true;
    if (!glider._map) {
      glider.setLatLng(here).addTo(map);
      gliderEl = glider.getElement().firstChild;
      gliderAt = at;
    } else if (!at.equals(gliderAt)) {
      glider.setLatLng(here);
      gliderAt = at;
    } else {
      moved = false;
    }
    drawNext(s.nav, here, moved);
    var turn = f.known(s.heading_deg) ? "rotate(" + s.heading_deg.toFixed(0) + "deg)" : gliderTurn;
    if (turn !== gliderTurn) {
      gliderTurn = turn;
      gliderEl.style.transform = turn;
    }
    follow(here);
  }

  function follow(here) {
    var now = Date.now();
    if (!following || now - lastFollow < FOLLOW_EVERY_MS || !visible()) return;
    lastFollow = now;
    var size = map.getSize();
    var p = map.latLngToContainerPoint(here);
    if (Math.abs(p.x - size.x / 2) >= FOLLOW_OFF_PX || Math.abs(p.y - size.y / 2) >= FOLLOW_OFF_PX) {
      map.panTo(here, {animate: false});
    }
  }

  function visible() {
    return map.getContainer().offsetWidth > 0;
  }

  // --- the track ----------------------------------------------------------------------------

  // What to ask xpg_track for, or null when the page has all the snapshot says there is.
  function trackWanted(s) {
    if (!map || typeof s.track_n !== "number") return null;
    if (s.track_epoch === trackEpoch && s.track_n <= trackNext) return null;
    return {epoch: trackEpoch, from: trackNext};
  }

  // An answer of xpg_track: points from number `from` on. Not where the line ends: start again.
  // The line changes at the next state (flushTrack), so that the page draws one frame for both.
  function addTrack(r) {
    if (!r || !Array.isArray(r.points)) return;
    if (r.epoch !== trackEpoch || r.from !== trackNext) {
      trackEpoch = r.epoch;
      newLine = r.points.slice();
      newPoints = [];
    } else if (newLine) {
      newLine = newLine.concat(r.points);
    } else {
      newPoints = newPoints.concat(r.points);
    }
    trackNext = r.from + r.points.length;
  }

  function flushTrack() {
    if (newLine) {
      held = newLine;
      newLine = null;
      newPoints = [];
      rebuild();
    } else if (newPoints.length) {
      var points = newPoints;
      newPoints = [];
      held = held.concat(points);
      if (held.length > TRACK_CAPACITY + TRACK_TRIM) {
        held = held.slice(-TRACK_CAPACITY);
        rebuild();
      } else if (rescale(points)) rebuild();
      else extend(points);
    }
  }

  // --- the track's colours ------------------------------------------------------------------

  function knownHeight(p) {
    return typeof p[2] === "number" && isFinite(p[2]);
  }

  // Widen the scale to take these points; true if it moved.
  function rescale(points) {
    var low = lo, high = hi;
    for (var i = 0; i < points.length; i++) {
      if (!knownHeight(points[i])) continue;
      var m = points[i][2];
      if (low === null || m < low) low = Math.floor(m / TRACK_STEP_M) * TRACK_STEP_M;
      if (high === null || m > high) high = Math.ceil(m / TRACK_STEP_M) * TRACK_STEP_M;
    }
    if (low === null) return false;
    high = Math.max(high, low + TRACK_MIN_SPAN_M);
    if (low === lo && high === hi) return false;
    lo = low;
    hi = high;
    return true;
  }

  function band(p, before) {
    if (!knownHeight(p) || lo === null) return before < 0 ? 0 : before;
    var k = Math.floor((p[2] - lo) / (hi - lo) * TRACK_COLOURS.length);
    return Math.max(0, Math.min(TRACK_COLOURS.length - 1, k));
  }

  function newSeg(points, b) {
    seg = L.polyline(points, {color: TRACK_COLOURS[b], className: "track", interactive: false, weight: 3,
                              smoothFactor: 1});
    segPoints = points;
    segBand = b;
    trackLayer.addLayer(seg);
  }

  // The whole track again: a new epoch, or a scale that moved.
  function rebuild() {
    trackLayer.clearLayers();
    seg = segPoints = null;
    segBand = -1;
    lo = hi = null;
    rescale(held);
    var runs = [];
    var run = null, b = -1;
    for (var i = 0; i < held.length; i++) {
      var k = band(held[i], b);
      if (run && k !== b) {
        runs.push([run, b]);
        run = [held[i - 1]];  // each run starts where the last ended: one line, no gaps
      }
      if (!run) run = [];
      run.push(held[i]);
      b = k;
    }
    if (run) runs.push([run, b]);
    for (var j = 0; j < runs.length; j++) newSeg(runs[j][0], runs[j][1]);
    drawLegend();
  }

  // New points on the same scale: onto the last line while the colour holds.
  function extend(points) {
    var changed = false;
    for (var i = 0; i < points.length; i++) {
      var k = band(points[i], segBand);
      if (seg && k === segBand) {
        segPoints.push(points[i]);
        changed = true;
      } else {
        if (changed) seg.setLatLngs(segPoints);
        changed = false;
        var last = segPoints && segPoints.length ? segPoints[segPoints.length - 1] : null;
        newSeg(last ? [last, points[i]] : [points[i]], k);
      }
    }
    if (changed) seg.setLatLngs(segPoints);
  }

  // The legend: the scale's top and bottom in the pilot's units, the colours between.
  var Legend = L.Control.extend({
    options: {position: "topleft"},
    onAdd: function () {
      var el = L.DomUtil.create("div", "track-legend");
      var html = '<span class="hi"></span><div class="bar">';
      for (var i = TRACK_COLOURS.length - 1; i >= 0; i--) html += '<i style="background:' + TRACK_COLOURS[i] + '"></i>';
      el.innerHTML = html + '</div><span class="lo"></span>';
      L.DomEvent.disableClickPropagation(el);
      return el;
    }
  });

  function drawLegend() {
    if (!legend) return;
    var el = legend.getContainer();
    var shown = lo !== null;
    el.style.display = shown ? "" : "none";
    if (!shown) return;
    var u = xpg.format.units(unitsShown);
    el.querySelector(".hi").textContent = xpg.format.height(hi, u, false);
    el.querySelector(".lo").textContent = xpg.format.height(lo, u, false) + " " + u.height;
  }

  // --- the task -----------------------------------------------------------------------------

  function taskPath(className, weight, extra) {
    var o = {pane: "task", renderer: taskRenderer(), className: className, interactive: false, weight: weight,
             color: TASK_COLOUR, fillColor: TASK_COLOUR};
    for (var k in extra) o[k] = extra[k];
    return o;
  }

  var renderer = null;
  function taskRenderer() {
    if (!renderer) renderer = L.svg({pane: "task"});
    return renderer;
  }

  function zoneLayers(z) {
    var o = taskPath("task-zone", ZONE_STYLE.weight, {opacity: ZONE_STYLE.opacity, fillOpacity: ZONE_STYLE.fillOpacity});
    if (!z) return [];
    if (z.kind === "circle") return [L.circle([z.lat, z.lon], extendStyle(o, {radius: z.r_m}))];
    if (z.kind === "line") return [L.polyline(z.ends, extendStyle(o, {className: "task-zone task-line"}))];
    if (z.kind === "polygons") return z.rings.map(function (ring) { return L.polygon(ring, o); });
    return [];
  }

  function extendStyle(o, extra) {
    var out = {};
    for (var k in o) out[k] = o[k];
    for (var j in extra) out[j] = extra[j];
    return out;
  }

  // A new task, or none. `fit`: chosen by the pilot just now, so the map shows it whole (and stops
  // following until the pilot asks again).
  function setTask(t, fit) {
    if (!map) return;
    pendingFit = null;  // a fit waiting for the last task is not this one's
    taskLayer.clearLayers();
    taskZones = [];
    taskPoints = null;
    activeIndex = -1;
    if (nextLine) {
      nextLine.remove();
      nextLine = null;
    }
    if (!t || !Array.isArray(t.points) || !t.points.length) return;
    taskPoints = t.points.map(function (p) { return [p.lat, p.lon]; });
    L.polyline(taskPoints, taskPath("task-leg-outline", 5, {color: "#000", opacity: 0.55})).addTo(taskLayer);
    L.polyline(taskPoints, taskPath("task-leg", 2, {})).addTo(taskLayer);
    for (var i = 0; i < t.points.length; i++) {
      var p = t.points[i];
      var layers = zoneLayers(p.zone);
      for (var j = 0; j < layers.length; j++) layers[j].addTo(taskLayer);
      taskZones.push(layers);
      var label = document.createElement("span");
      label.textContent = p.name;  // a name from the file: text, never HTML
      L.circleMarker([p.lat, p.lon], taskPath("task-dot", 1.5, {radius: 3, color: "#000", fillColor: "#fff",
                                                                fillOpacity: 1}))
        .bindTooltip(label, {permanent: true, direction: "right", offset: [5, 0], className: "task-label"})
        .addTo(taskLayer);
    }
    if (fit) {
      var bounds = L.latLngBounds(taskPoints);
      for (var z = 0; z < taskZones.length; z++) {
        for (var k = 0; k < taskZones[z].length; k++) bounds.extend(taskZones[z][k].getBounds());
      }
      if (glider && glider._map) bounds.extend(glider.getLatLng());
      setFollow(false);
      pendingFit = bounds;
      if (visible()) fitPending();
    }
  }

  // The zone flown to marked, and a line to its point, moved only when the glider moved a pixel
  // or the point changed.
  function drawNext(nav, here, moved) {
    var index = nav && taskPoints && !nav.finished ? nav.index : -1;
    if (index >= pointCount()) index = -1;
    if (index !== activeIndex) {
      if (activeIndex >= 0 && taskZones[activeIndex]) setZoneStyle(taskZones[activeIndex], ZONE_STYLE);
      if (index >= 0) setZoneStyle(taskZones[index], ACTIVE_STYLE);
      activeIndex = index;
      moved = true;
    }
    if (index < 0) {
      if (nextLine) {
        nextLine.remove();
        nextLine = null;
      }
      return;
    }
    if (!nextLine) {
      nextLine = L.polyline([here, taskPoints[index]], taskPath("task-next", 2, {color: "#ffd21a", dashArray: "6 6"}))
        .addTo(taskLayer);
    } else if (moved) {
      nextLine.setLatLngs([here, taskPoints[index]]);
    }
  }

  function pointCount() {
    return taskPoints ? taskPoints.length : 0;
  }

  function fitPending() {
    if (!pendingFit) return;
    // More room on the right: the points' names are written to the right of them.
    map.fitBounds(pendingFit, {paddingTopLeft: [24, 24], paddingBottomRight: [90, 24], animate: false, maxZoom: 13});
    pendingFit = null;
  }

  function setZoneStyle(layers, style) {
    for (var i = 0; i < layers.length; i++) layers[i].setStyle(style);
  }

  // --- shown again, resized -----------------------------------------------------------------

  function shown() {
    if (!map) return;
    map.invalidateSize({pan: false});
    fitPending();
    lastFollow = 0;
    drawGrid();
  }

  // A line for the status bar while tiles fail and none load.
  function note() {
    if (!map || !tiles) return map ? "no map tiles set: grid only" : "";
    return tileErrors >= 4 ? "map tiles not loading: grid only" : "";
  }

  return {init: init, draw: draw, trackWanted: trackWanted, addTrack: addTrack, shown: shown, note: note,
          setTask: setTask};
})();
