// A fake window.xplane for developing the page in a desktop browser: open index.html?dev, or
// index.html?dev&offline for a map whose tiles never load, &ago=600 to start ten minutes in, and
// &view=task to open on another view than the map, as the pilot's last one would.
// The glider glides north-east for 40 s, then circles three times in a 2 m/s thermal while drifting in a
// 12 kt wind, again and again; units switch every 20 s. The track is kept one point a second as
// nav/track.py keeps it, and answered in the same form. Tasks: one file with a triangle ahead of
// the glider (its shapes made by nav/task.py once and kept here as they came), one file with
// turn points only; the start is taken once past it, each point within 600 m (a stand-in: the real
// zone tests are Python's). Never loaded in X-Plane (only with ?dev,
// and only while window.xplane is missing). Classic script, Chromium 117. License: GPL-3.0-or-later.
"use strict";

(function () {
  var ago = /[?&]ago=(\d+)/.exec(location.search);  // ?dev&ago=600: ten minutes flown already
  var t0 = Date.now() - (ago ? parseInt(ago[1], 10) * 1000 : 0);
  var offline = /[?&]offline\b/.test(location.search);
  var startView = (/[?&]view=(map|flight|task)\b/.exec(location.search) || [0, "map"])[1];
  var M_PER_DEG = 111195;
  var START = [-33.45, -70.55];
  var WIND_TO = 60, WIND_MS = 6.2;  // the wind blows from 240
  var points = [];  // [lat, lon], one a second
  // nav/task.py's Task.to_json for a fake triangle (written by hand from Python, 2026-11-18).
  var TASK = {"rev":0,"name":"Fake triangle","source":"santiago.cup","points":[{"name":"Fake Start","code":"FST","lat":-33.445503,"lon":-70.540666,"elev_m":700.0,"role":"start","zone":{"kind":"line","ends":[[-33.453291,-70.535276],[-33.437715,-70.546055]]},"zone_given":false},{"name":"Fake North-East","code":"FNE","lat":-33.418507,"lon":-70.484683,"elev_m":900.0,"role":"point","zone":{"kind":"circle","lat":-33.418507,"lon":-70.484683,"r_m":500.0},"zone_given":false},{"name":"Fake South (a long name to cut)","code":"FSO","lat":-33.465233,"lon":-70.452341,"elev_m":800.0,"role":"point","zone":{"kind":"polygons","rings":[[[-33.461694,-70.42028],[-33.464039,-70.420032],[-33.466393,-70.42003],[-33.468737,-70.420274],[-33.471056,-70.420762],[-33.47333,-70.42149],[-33.475542,-70.422453],[-33.477676,-70.423643],[-33.479715,-70.425053],[-33.481644,-70.426669],[-33.483448,-70.428482],[-33.485114,-70.430476],[-33.486628,-70.432637],[-33.487979,-70.434947],[-33.489157,-70.43739],[-33.490153,-70.439947],[-33.490959,-70.442599],[-33.49157,-70.445325],[-33.49198,-70.448104],[-33.465233,-70.452341]]]},"zone_given":true},{"name":"Fake Start","code":"FST","lat":-33.445503,"lon":-70.540666,"elev_m":700.0,"role":"finish","zone":{"kind":"circle","lat":-33.445503,"lon":-70.540666,"r_m":500.0},"zone_given":false}],"legs_m":[6000.0,6000.0,8482.6],"total_m":20482.6,"takeoff":null,"landing":null};
  var LIST = {folder: "D:/Laminar/X-Plane 12/Output/xp-gliding/tasks", files: [
    {file: "santiago.cup", error: null, tasks: [{index: 0, name: TASK.name, points: 4, total_m: TASK.total_m}]},
    {file: "turnpoints only.cup", error: "no tasks in this file", tasks: []}]};
  var taskRev = 0, tasksRev = 0, loaded = false, active = 0, started = false, finished = false;
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

  var R = 6371000, D = Math.PI / 180;
  function dist(a, b) {
    var dp = (b[0] - a[0]) * D, dl = (b[1] - a[1]) * D;
    var h = Math.pow(Math.sin(dp / 2), 2) + Math.cos(a[0] * D) * Math.cos(b[0] * D) * Math.pow(Math.sin(dl / 2), 2);
    return 2 * R * Math.asin(Math.sqrt(h));
  }
  function bearing(a, b) {
    var y = Math.sin((b[1] - a[1]) * D) * Math.cos(b[0] * D);
    var x = Math.cos(a[0] * D) * Math.sin(b[0] * D) - Math.sin(a[0] * D) * Math.cos(b[0] * D) * Math.cos((b[1] - a[1]) * D);
    return (Math.atan2(y, x) / D + 360) % 360;
  }

  function nav(p) {
    if (!loaded) return null;
    var here = [p.lat, p.lon], pts = TASK.points;
    var at = function (i) { return [pts[i].lat, pts[i].lon]; };
    if (!finished) {
      if (active === 0 && dist(at(0), here) > 300 && Math.abs(((bearing(at(0), here) - 60) + 540) % 360 - 180) < 90) {
        active = 1;
        started = true;
      } else if (active > 0 && dist(at(active), here) < 600) {
        if (active === pts.length - 1) finished = true;
        else active++;
      }
    }
    var d = dist(here, at(active));
    var left = finished ? 0 : d + TASK.legs_m.slice(active).reduce(function (a, b) { return a + b; }, 0);
    return {name: pts[active].name, code: pts[active].code, index: active, count: pts.length, role: pts[active].role,
            bearing_deg: bearing(here, at(active)), dist_m: d, task_left_m: left,
            task_done: started ? Math.max(0, 1 - left / TASK.total_m) : 0, in_zone: d < 600,
            started: started, finished: finished};
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
      t: t, local_s: 13 * 3600 + 42 * 60 + t, valid: t > 1.5, units: Math.floor(t / 20) % 2 ? "aviation" : "metric", view: startView, poll_hz: 5,
      lat: p.lat, lon: p.lon, msl_m: p.msl, agl_m: p.msl - 600,
      track_deg: (turn + 8) % 360, heading_deg: turn, gs_ms: 24 + 5 * Math.cos(turn * Math.PI / 180),
      ias_ms: 23.5, tas_ms: 25.0,
      te_ms: te, netto_ms: te + 0.9, avg_ms: 1.7, thm_ms: 1.8, thm_valid: t > 8, thm_active: true,
      circling: p.circling, aid_valid: false, aid_core_az_deg: null, aid_amp_ms: null,
      wind_from_deg: 240, wind_ms: WIND_MS, top_m: 650 - 1.8 * t,
      track_n: points.length, track_epoch: 0,
      task_rev: taskRev, tasks_rev: tasksRev, nav: nav(p)
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
    xpg_tasks: function () {
      // Rev 0 is the empty list Python starts with, before the folder is first read.
      if (tasksRev === 0) return Promise.resolve({rev: 0, folder: "", files: [], current: null, note: ""});
      LIST.rev = tasksRev;
      LIST.current = loaded ? {file: "santiago.cup", index: 0} : null;
      return Promise.resolve(LIST);
    },
    xpg_task: function () {
      if (!loaded) return Promise.resolve({rev: taskRev, name: null});
      TASK.rev = taskRev;
      return Promise.resolve(TASK);
    },
    xpg_do: function (request) {
      var cmd = request && request.cmd;
      if (cmd === "log") console.log("page:", request.text);
      if (cmd === "list_tasks") setTimeout(function () { tasksRev++; }, 150);
      if (cmd === "load_task") setTimeout(function () { loaded = true; active = 0; started = finished = false; taskRev++; }, 150);
      if (cmd === "clear_task") { loaded = false; taskRev++; }
      if (cmd === "next_point" && loaded) {
        if (active === TASK.points.length - 1) finished = true; else active++;
        started = true;
      }
      if (cmd === "prev_point" && loaded) {
        if (finished) finished = false; else if (active > 0) active--;
        started = active > 0;
      }
      return Promise.resolve({ok: true});
    }
  };
})();
