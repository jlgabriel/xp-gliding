// XP-Gliding Flight Computer: the MAP view. Leaflet 1.9.4 (vendor/leaflet), north up.
//
// Draws what Python sends and computes nothing that matters: the glider at its place, turned to
// its heading; the wind at the glider, an arrow pointing where it goes (the map is north up) and
// its speed in knots, as on the HUD; the track as Python kept it (xpg_track, one point a second),
// coloured by height from blue (the flight's lowest) to red (its highest), with a legend (on the
// Glide Computer's THERMAL screen by climb instead: see CLIMB_EDGES); raster tiles from the
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
// The Glide Computer (setLayout("glide")) uses the same map with its overlays in the meanings and
// colours of Condor 3's flight computer, drawn our way: the zone flown to red, the others green
// (taken ones fainter), the start red, yellow once armed (the glider in its zone) and green once
// taken; yellow tags T, S, 1..n, F by the names, a yellow cross on each point; a thin black line
// from the glider to the way to fly; a heading tape along the top (blue ticks, the bearing to the
// way to fly a red mark, centred when flying straight at it) and a glide-slope bar down the right
// edge (its mark waits for the polar and MacCready); the wind bottom left as "from/speed", the
// map's width bottom right. GLIDE and INFO keep their own zoom; THERMAL always opens close in, about
// THERMAL_WIDTH_M across whatever the window's size, and a zoom there is not kept. The tiles can be
// turned off (the map's display, a command).
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
  // THERMAL colours the track by the climb along each second instead (nav/track.py), on a scale
  // that never moves, so that a circle shows where it climbs and where it sinks: the same six
  // colours, split at these climbs in the pilot's unit (blue sinking more than 1 m/s, red climbing
  // 3 m/s or more).
  var CLIMB_EDGES = {metric: [-1, 0, 1, 2, 3], aviation: [-2, 0, 2, 4, 6]};
  // Points held at most, as Python keeps them (nav/track.py: six hours at one a second); past
  // this the oldest go, this many at a time, so that the line is built again only now and then.
  var TRACK_CAPACITY = 6 * 3600;
  var TRACK_TRIM = 600;
  var GRID_STEPS = [10, 5, 2, 1, 0.5, 0.2, 0.1, 0.05, 0.02, 0.01, 0.005, 0.002, 0.001];  // degrees
  var GLIDER_SVG =
    '<svg viewBox="-16 -16 32 32" width="48" height="48" aria-hidden="true">' +
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
  var held = [];  // every point held, [lat, lon, msl] with its climb as `.climb` (see held3)
  var byClimb = false;  // the track coloured by climb (THERMAL), not by height
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
  // The Glide Computer's zones: what each colour means is Condor's.
  var RED = "#ff2d2d", GREEN = "#22d33a", YELLOW = "#ffd21a";
  var GLIDE_ZONES = {
    active: {color: RED, fillColor: RED, weight: 3, opacity: 1, fillOpacity: 0.2},
    armed: {color: YELLOW, fillColor: YELLOW, weight: 3, opacity: 1, fillOpacity: 0.22},
    todo: {color: GREEN, fillColor: GREEN, weight: 2, opacity: 0.95, fillOpacity: 0.12},
    // As wide as the ones to come, and only a little fainter: thinner, it was lost on the tiles
    taken: {color: GREEN, fillColor: GREEN, weight: 2, opacity: 0.8, fillOpacity: 0.06}
  };
  var DEFAULT_ZOOMS = {map: DEFAULT_ZOOM, glide: 12, info: 11, thermal: 15};
  var THERMAL_WIDTH_M = 1000;  // THERMAL's map across, to the nearest zoom: a few circles and their drift
  var TAPE_SPAN_DEG = 50;  // the heading tape shows this much each side of the track (Condor's span: to verify)
  var TAPE_STEP_DEG = 10;
  var BAR_TICKS = 10;
  var layout = "flight";
  var zoomKey = "map";  // whose zoom the map keeps: the Flight Computer's map, or a screen
  var tilesOn = true;
  var lastTask = null;  // the task as given, to draw again when the layout changes
  var zoneState = "";  // the Glide Computer's zones as last coloured
  var tapeMark = null, tapeEl = null, barEl = null;
  var tapeAt = null;
  var cornerWind = null, cornerWidth = null;
  var takeoffAt = null;  // [lat, lon] of the task's takeoff, or null

  function escapeText(text) {
    return String(text).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // The Flight Computer's map keeps the key it always had; each Glide Computer screen its own.
  function zoomStore(key) {
    return key === "map" ? "xpg.map.zoom" : "xpg.map.zoom." + key;
  }

  function storedZoom(key) {
    var fallback = DEFAULT_ZOOMS[key] || DEFAULT_ZOOM;
    if (key === "thermal") return fallback;  // not kept: see zoomFor
    try {
      var z = parseInt(localStorage.getItem(zoomStore(key)), 10);
      return isFinite(z) ? z : fallback;
    } catch (e) {
      return fallback;
    }
  }

  function storeZoom() {
    if (zoomKey === "thermal") return;  // THERMAL opens at its own width each time
    try { localStorage.setItem(zoomStore(zoomKey), String(map.getZoom())); } catch (e) { /* not kept */ }
  }

  function stored(name, fallback) {
    try {
      var v = localStorage.getItem(name);
      return v === null ? fallback : v;
    } catch (e) {
      return fallback;
    }
  }

  function store(name, value) {
    try { localStorage.setItem(name, value); } catch (e) { /* not kept */ }
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
      a.innerHTML = '<svg viewBox="-10 -10 20 20" width="24" height="24" aria-hidden="true">' +
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
      el.innerHTML = '<svg viewBox="-10 -10 20 20" width="34" height="34" aria-hidden="true">' +
        '<path d="M0,-8 L4,1 L1,1 L1,8 L-1,8 L-1,1 L-4,1 Z"/></svg><span></span>';
      windArrow = el.firstChild;
      windText = el.lastChild;
      L.DomEvent.disableClickPropagation(el);
      return el;
    }
  });

  // The Glide Computer's corners: the wind bottom left (an arrow where the air goes, "from/speed"
  // in knots), the map's width bottom right. Shown only in its layout (app.css).
  var Corner = L.Control.extend({
    onAdd: function () {
      var el = L.DomUtil.create("div", "corner " + this.options.kind);
      if (this.options.kind === "corner-wind") {
        el.innerHTML = '<svg viewBox="-10 -10 20 20" width="30" height="30" aria-hidden="true">' +
          '<path d="M0,-8 L4,1 L1,1 L1,8 L-1,8 L-1,1 L-4,1 Z"/></svg>';
      }
      el.appendChild(document.createElement("span"));
      L.DomEvent.disableClickPropagation(el);
      return el;
    }
  });

  function setText(el, text) {
    if (el.textContent !== text) el.textContent = text;
  }

  function drawCorners(s) {
    var f = xpg.format;
    var el = cornerWind.getContainer();
    var calm = !f.known(s.wind_from_deg);
    var arrow = el.firstChild;
    var turn = calm ? "" : "rotate(" + ((s.wind_from_deg + 180) % 360).toFixed(0) + "deg)";
    if (arrow.style.transform !== turn) arrow.style.transform = turn;
    arrow.style.visibility = calm ? "hidden" : "visible";
    var d = f.known(s.wind_from_deg) ? ("00" + (Math.round(s.wind_from_deg) % 360 || 360)).slice(-3) : "";
    setText(el.lastChild, !f.known(s.wind_ms) ? "--" : calm ? "calm" : d + "/" + (s.wind_ms / 0.514444).toFixed(0) + " kt");
  }

  // The map's width across its middle, in the pilot's distance unit.
  function drawWidth() {
    if (!map || !placed || !cornerWidth || !visible()) return;
    var size = map.getSize();
    var m = map.distance(map.containerPointToLatLng([0, size.y / 2]), map.containerPointToLatLng([size.x, size.y / 2]));
    var u = xpg.format.units(unitsShown);
    var v = m * u.perDistance;
    setText(cornerWidth.getContainer().lastChild, (v < 9.95 ? v.toFixed(1) : v.toFixed(0)) + " " + u.distance);
  }

  // The heading tape: ticks every TAPE_STEP_DEG across the top, made once; the mark moved to the
  // bearing to fly against the track, held at the edge (and hollow) when outside the tape.
  function makeTape(container) {
    tapeEl = L.DomUtil.create("div", "hdg-tape", container);
    for (var a = -TAPE_SPAN_DEG; a <= TAPE_SPAN_DEG; a += TAPE_STEP_DEG) {
      var tick = L.DomUtil.create("i", a === 0 ? "major" : "", tapeEl);
      tick.style.left = (50 + 50 * a / TAPE_SPAN_DEG) + "%";
    }
    tapeMark = L.DomUtil.create("b", "mark", tapeEl);
    barEl = L.DomUtil.create("div", "gs-bar", container);
    for (var k = 0; k <= BAR_TICKS; k++) {
      var t = L.DomUtil.create("i", k === BAR_TICKS / 2 ? "major" : "", barEl);
      t.style.top = (100 * k / BAR_TICKS) + "%";
    }
  }

  function drawTape(s) {
    var f = xpg.format;
    var target = s.nav && !s.nav.finished ? s.nav.target : (s.nav && s.nav.target && s.nav.target.index === -1 ? s.nav.target : null);
    var course = f.known(s.track_deg) ? s.track_deg : s.heading_deg;
    var at = null;
    if (target && f.known(target.bearing_deg) && f.known(course)) {
      var off = ((target.bearing_deg - course) % 360 + 540) % 360 - 180;
      at = Math.max(-TAPE_SPAN_DEG, Math.min(TAPE_SPAN_DEG, off));
      at = Math.round(at) + (Math.abs(off) > TAPE_SPAN_DEG ? "o" : "");
    }
    if (at === tapeAt) return;
    tapeAt = at;
    tapeMark.style.display = at === null ? "none" : "";
    if (at === null) return;
    tapeMark.classList.toggle("out", String(at).slice(-1) === "o");
    tapeMark.style.left = (50 + 50 * parseFloat(at) / TAPE_SPAN_DEG) + "%";
  }

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
      tilesOn = stored("xpg.map.tiles", "on") !== "off";
      if (tilesOn) tiles.addTo(map);
    }
    map.createPane("task");
    map.getPane("task").style.zIndex = 350;  // over the tiles, under the track (overlays, 400)
    taskLayer = L.layerGroup().addTo(map);
    trackLayer = L.layerGroup().addTo(map);
    legend = new Legend().addTo(map);
    glider = L.marker([0, 0], {
      icon: L.divIcon({className: "glider", html: GLIDER_SVG, iconSize: [48, 48], iconAnchor: [24, 24]}),
      interactive: false, keyboard: false
    });
    scale = new Scale().addTo(map);
    new Follow().addTo(map);
    new Wind().addTo(map);
    cornerWind = new Corner({position: "bottomleft", kind: "corner-wind"}).addTo(map);
    cornerWidth = new Corner({position: "bottomright", kind: "corner-width"}).addTo(map);
    makeTape(map.getContainer());
    setFollow(true);
    map.on("dragstart", function () { setFollow(false); });
    map.on("moveend", drawGrid);
    map.on("moveend", drawWidth);
    map.on("zoomend", storeZoom);
    map.on("resize", drawWidth);
  }

  // --- the two computers --------------------------------------------------------------------

  // "flight" or "glide": the task is drawn again in that computer's way.
  function setLayout(name) {
    if (name === layout) return;
    layout = name;
    zoneState = "";
    tapeAt = undefined;
    if (map) setTask(lastTask, false);
    colourBy();
  }

  // The zoom a screen opens at: THERMAL's from its width, the others' as last left.
  function zoomFor(key) {
    if (key !== "thermal" || !map) return storedZoom(key);
    var size = map.getSize();
    if (!placed || !(size.x > 0)) return DEFAULT_ZOOMS.thermal;  // hidden: nothing to measure
    var m = map.distance(map.containerPointToLatLng([0, size.y / 2]),
                         map.containerPointToLatLng([size.x, size.y / 2]));
    if (!(m > 0)) return DEFAULT_ZOOMS.thermal;
    var z = Math.round(map.getZoom() + Math.log(m / THERMAL_WIDTH_M) / Math.LN2);
    return Math.max(map.getMinZoom(), Math.min(map.getMaxZoom(), z));
  }

  // The zoom of this screen ("map" for the Flight Computer, or a Glide Computer screen). A Glide
  // Computer screen chosen follows the glider again, as Condor's screens are always centred on it.
  function useZoom(key) {
    if (key === zoomKey) return;
    zoomKey = key;
    colourBy();
    if (key !== "map" && map) setFollow(true);
    if (map && placed) {
      var z = zoomFor(key);
      if (z !== map.getZoom()) {
        map.setZoom(z, {animate: false});
        lastFollow = 0;
      }
    }
  }

  // The pilot's commands, as X-Plane passed them to the page (app.js).
  function zoomBy(step) {
    if (!map) return;
    map.setZoom(map.getZoom() + step, {animate: false});
    lastFollow = 0;
  }

  function toggleTiles() {
    if (!map || !tiles) return;
    tilesOn = !tilesOn;
    if (tilesOn) tiles.addTo(map);
    else tiles.remove();
    store("xpg.map.tiles", tilesOn ? "on" : "off");
  }

  // --- each state ---------------------------------------------------------------------------

  function draw(s) {
    if (!map) return;
    flushTrack();
    if (unitsShown !== s.units) {
      unitsShown = s.units;
      scale.setNautical(s.units === "aviation");
      if (byClimb) rebuild();  // the climb's edges are the pilot's units
      drawLegend();
      drawWidth();
    }
    drawWind(s);
    if (layout === "glide") {
      drawCorners(s);
      drawTape(s);
    }
    var f = xpg.format;
    if (!f.known(s.lat) || !f.known(s.lon)) {
      if (glider._map) glider.remove();
      return;
    }
    var here = L.latLng(s.lat, s.lon);
    if (!placed) {
      placed = true;
      map.setView(here, storedZoom(zoomKey), {animate: false});
      if (zoomKey === "thermal") map.setZoom(zoomFor("thermal"), {animate: false});
      drawWidth();
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

  // Python's [lat, lon, msl, climb] as Leaflet takes a point: it reads an array of three as
  // [lat, lon, alt] and refuses one of four. The climb rides along as a property.
  function held3(points) {
    var out = new Array(points.length);
    for (var i = 0; i < points.length; i++) {
      var p = points[i];
      var q = [p[0], p[1], p[2]];
      q.climb = p[3];
      out[i] = q;
    }
    return out;
  }

  // An answer of xpg_track: points from number `from` on. Not where the line ends: start again.
  // The line changes at the next state (flushTrack), so that the page draws one frame for both.
  function addTrack(r) {
    if (!r || !Array.isArray(r.points)) return;
    var points = held3(r.points);
    if (r.epoch !== trackEpoch || r.from !== trackNext) {
      trackEpoch = r.epoch;
      newLine = points;
      newPoints = [];
    } else if (newLine) {
      newLine = newLine.concat(points);
    } else {
      newPoints = newPoints.concat(points);
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
      } else if (rescale(points) && !byClimb) rebuild();
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
    if (byClimb) return climbBand(p, before);
    if (!knownHeight(p) || lo === null) return before < 0 ? 0 : before;
    var k = Math.floor((p[2] - lo) / (hi - lo) * TRACK_COLOURS.length);
    return Math.max(0, Math.min(TRACK_COLOURS.length - 1, k));
  }

  function climbBand(p, before) {
    if (typeof p.climb !== "number" || !isFinite(p.climb)) return before < 0 ? 2 : before;  // unknown: as the last
    var v = p.climb * xpg.format.units(unitsShown).perClimb;
    var edges = CLIMB_EDGES[unitsShown] || CLIMB_EDGES.metric;
    var k = 0;
    while (k < edges.length && v >= edges[k]) k++;
    return k;
  }

  // Height or climb: by climb on the Glide Computer's THERMAL screen. The whole line again when it
  // changes, or when the units move the climb's edges.
  function colourBy() {
    var climb = layout === "glide" && zoomKey === "thermal";
    if (climb === byClimb) return;
    byClimb = climb;
    if (map && trackLayer) rebuild();
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
    var shown = byClimb ? held.length > 0 : lo !== null;
    el.style.display = shown ? "" : "none";
    if (!shown) return;
    var u = xpg.format.units(unitsShown);
    if (byClimb) {  // the top colour's lower edge, the bottom colour's upper one
      var edges = CLIMB_EDGES[unitsShown] || CLIMB_EDGES.metric;
      el.querySelector(".hi").textContent = "+" + edges[edges.length - 1];
      el.querySelector(".lo").textContent = "−" + Math.abs(edges[0]) + " " + u.climb;
      return;
    }
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

  // The Glide Computer's short names: S start, F finish, the turn points by their number.
  function pointTag(p, i) {
    return p.role === "start" ? "S" : p.role === "finish" ? "F" : String(i);
  }

  // A name on the map: in the Glide Computer with its yellow tags in front. Text nodes only.
  function nameLabel(tags, name) {
    var label = document.createElement("span");
    for (var i = 0; layout === "glide" && i < tags.length; i++) {
      var b = document.createElement("b");
      b.className = "ytag";
      b.textContent = tags[i];
      label.appendChild(b);
    }
    label.appendChild(document.createTextNode(name));  // a name from the file: text, never HTML
    return label;
  }

  // The places to mark: in the Glide Computer the takeoff too, and one mark for points at the
  // same place, with all their tags ("T S F" at a home field), so no name hides another.
  function marks(t) {
    var list = [];
    function add(lat, lon, tag, name) {
      if (layout === "glide") {
        for (var k = 0; k < list.length; k++) {
          if (Math.abs(list[k].at[0] - lat) < 1e-5 && Math.abs(list[k].at[1] - lon) < 1e-5) {
            list[k].tags.push(tag);
            return;
          }
        }
      }
      list.push({at: [lat, lon], tags: [tag], name: name});
    }
    if (layout === "glide" && t.takeoff && xpg.format.known(t.takeoff.lat) && xpg.format.known(t.takeoff.lon)) {
      takeoffAt = [t.takeoff.lat, t.takeoff.lon];
      add(t.takeoff.lat, t.takeoff.lon, "T", t.takeoff.name);
    }
    for (var i = 0; i < t.points.length; i++) add(t.points[i].lat, t.points[i].lon, pointTag(t.points[i], i), t.points[i].name);
    return list;
  }

  // A point's place: a dot in the Flight Computer, a yellow cross in the Glide Computer.
  function pointMark(latlng, tags, name) {
    var marker;
    if (layout === "glide") {
      marker = L.marker(latlng, {pane: "task", interactive: false, keyboard: false,
                                 icon: L.divIcon({className: "tp-cross", iconSize: [14, 14], iconAnchor: [7, 7],
                                                  html: '<svg viewBox="-7 -7 14 14" width="14" height="14" aria-hidden="true">' +
                                                        '<path d="M-6,0 L6,0 M0,-6 L0,6"/><path d="M-6,0 L6,0 M0,-6 L0,6"/></svg>'})});
    } else {
      marker = L.circleMarker(latlng, taskPath("task-dot", 1.5, {radius: 3, color: "#000", fillColor: "#fff",
                                                                 fillOpacity: 1}));
    }
    return marker.bindTooltip(nameLabel(tags, name), {permanent: true, direction: "right", offset: [6, 0],
                                                      className: "task-label"});
  }

  // A new task, or none. `fit`: chosen by the pilot just now, so the map shows it whole (and stops
  // following until the pilot asks again).
  function setTask(t, fit) {
    if (!map) return;
    lastTask = t;
    pendingFit = null;  // a fit waiting for the last task is not this one's
    taskLayer.clearLayers();
    taskZones = [];
    taskPoints = null;
    takeoffAt = null;
    activeIndex = -1;
    zoneState = "";
    if (nextLine) {
      nextLine.remove();
      nextLine = null;
    }
    if (!t || !Array.isArray(t.points) || !t.points.length) return;
    taskPoints = t.points.map(function (p) { return [p.lat, p.lon]; });
    L.polyline(taskPoints, taskPath("task-leg-outline", 5, {color: "#000", opacity: 0.55})).addTo(taskLayer);
    L.polyline(taskPoints, taskPath("task-leg", layout === "glide" ? 3 : 2, {})).addTo(taskLayer);
    for (var i = 0; i < t.points.length; i++) {
      var p = t.points[i];
      var layers = zoneLayers(p.zone);
      for (var j = 0; j < layers.length; j++) layers[j].addTo(taskLayer);
      taskZones.push(layers);
    }
    var list = marks(t);
    for (var m = 0; m < list.length; m++) pointMark(list[m].at, list[m].tags, list[m].name).addTo(taskLayer);
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
    if (layout === "glide") {
      drawGlideNext(nav, here, moved);
      return;
    }
    var index = nav && taskPoints && !nav.finished ? nav.index : -1;
    if (index >= pointCount()) index = -1;
    if (index !== activeIndex) {
      if (activeIndex >= 0 && taskZones[activeIndex]) setZoneStyle(taskZones[activeIndex], ZONE_STYLE);
      if (index >= 0) setZoneStyle(taskZones[index], ACTIVE_STYLE);
      activeIndex = index;
      moved = true;
    }
    if (index < 0) {
      dropNextLine();
      return;
    }
    if (!nextLine) {
      nextLine = L.polyline([here, taskPoints[index]], taskPath("task-next", 2, {color: "#ffd21a", dashArray: "6 6"}))
        .addTo(taskLayer);
    } else if (moved) {
      nextLine.setLatLngs([here, taskPoints[index]]);
    }
  }

  function dropNextLine() {
    if (nextLine) {
      nextLine.remove();
      nextLine = null;
    }
  }

  // The Glide Computer: every zone coloured by what it is now, and a thin black line (on a light
  // edge, for dark ground) to the way to fly: the point flown to, or the takeoff when it is the target.
  function drawGlideNext(nav, here, moved) {
    var count = pointCount();
    var state = nav && count ? [nav.index, nav.started, nav.finished, nav.armed].join() : "";
    if (state !== zoneState) {
      zoneState = state;
      for (var i = 0; i < count; i++) setZoneStyle(taskZones[i], GLIDE_ZONES[zoneKind(nav, i)]);
      moved = true;
    }
    var to = null;
    if (nav && nav.target && nav.target.index === -1 && takeoffAt) to = takeoffAt;
    else if (nav && !nav.finished && nav.index < count) to = taskPoints[nav.index];
    if (!to) {
      dropNextLine();
      return;
    }
    var line = [here, to];
    if (!nextLine) {
      nextLine = L.layerGroup([
        L.polyline(line, taskPath("target-edge", 4, {color: "#fff", opacity: 0.7})),
        L.polyline(line, taskPath("target-line", 1.6, {color: "#000", opacity: 1}))
      ]).addTo(taskLayer);
      nextLine.to = to;
    } else if (moved || nextLine.to !== to) {
      nextLine.to = to;
      nextLine.eachLayer(function (l) { l.setLatLngs(line); });
    }
  }

  // What a zone is now, for its colour: Condor's meanings.
  function zoneKind(nav, i) {
    if (!nav) return "todo";
    if (i === 0) {  // the start: red until armed, yellow armed, green taken
      if (nav.started) return "taken";
      return nav.armed ? "armed" : "active";
    }
    if (nav.finished) return "taken";
    if (i === nav.index) return "active";
    return i < nav.index ? "taken" : "todo";
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
    drawWidth();
  }

  // A line for the status bar while tiles fail and none load.
  function note() {
    if (!map || !tiles) return map ? "no map tiles set: grid only" : "";
    if (!tilesOn) return "";  // turned off by the pilot (the map's display)
    return tileErrors >= 4 ? "map tiles not loading: grid only" : "";
  }

  return {init: init, draw: draw, trackWanted: trackWanted, addTrack: addTrack, shown: shown, note: note,
          setTask: setTask, setLayout: setLayout, useZoom: useZoom, zoomBy: zoomBy, toggleTiles: toggleTiles};
})();
