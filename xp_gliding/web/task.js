// XP-Gliding Flight Computer: the task. The TASK view (the task loaded, its points with their
// height limits, what of the file is not flown as written, the buttons to step back and forward,
// and the picker: the CUP and PLN files in Output/xp-gliding/tasks/ and their tasks), and the row
// under the strip with the point flown to, seen in every view.
//
// Python does everything that matters (nav/cup.py, nav/pln.py, nav/task.py): reading the files, the zones,
// which point is next, bearing and distance. The page asks for the list (xpg_do list_tasks, then
// xpg_tasks once the snapshot's tasks_rev says it is made) and for the task (xpg_task, when
// task_rev changes), and sends the pilot's choices (load_task, next_point, prev_point,
// clear_task). Names from the files go in with textContent only.
// Classic script, Chromium 117. License: GPL-3.0-or-later.
"use strict";

var xpg = window.xpg || {};
window.xpg = xpg;

xpg.task = (function () {
  var f = xpg.format;
  var els = null;
  var task = null;  // the task as xpg_task gave it, or null
  var taskRev = null;  // the task_rev it came with
  var asked = null;  // the task_rev being asked for
  var listRev = null;  // the tasks_rev of the list shown
  // A list was asked for: the one wanted has a tasks_rev above this; null when none is awaited.
  // Not a flag: a snapshot made before Python read the folder still carries the old list's rev.
  var listAbove = null;
  var listAsking = false;  // an xpg_tasks call in flight
  var loading = null;  // {file, index} clicked, until the task comes
  var fitNext = false;  // the next task comes from the pilot's choice: the map shows it whole
  var lastNav = null;  // the last nav drawn
  var unitsName = null;

  function find() {
    els = {};
    ["navrow", "nav-role", "nav-name", "nav-limit", "nav-arrow", "nav-bearing", "nav-dist", "task-name",
     "task-total", "task-remarks", "task-points", "task-buttons", "task-list", "task-folder", "task-refresh",
     "task-note"].forEach(function (id) {
      els[id] = document.getElementById(id);
    });
    els["task-refresh"].addEventListener("click", list);
    var buttons = els["task-buttons"].querySelectorAll("button");
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].addEventListener("click", function (e) {
        send({cmd: e.currentTarget.getAttribute("data-cmd")});
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

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  // Ask Python to read the tasks folder again; the list comes when tasks_rev changes.
  function list() {
    wantList();
    setText(els["task-note"], "reading the tasks folder");
    send({cmd: "list_tasks"});
  }

  // A list newer than the one shown, or than the empty one Python starts with (rev 0).
  function wantList() {
    listAbove = listRev === null ? 0 : listRev;
  }

  function roleTag(role, index) {
    return role === "start" ? "START" : role === "finish" ? "FINISH" : "TP" + index;
  }

  // --- each state ---------------------------------------------------------------------------

  function draw(s) {
    if (!els) find();
    var x = xpg.bridge();
    if (typeof s.task_rev === "number" && s.task_rev !== taskRev && s.task_rev !== asked && x) {
      asked = s.task_rev;
      x.xpg_task().then(setTask, function () { asked = null; });
    }
    if (listAbove !== null && !listAsking && typeof s.tasks_rev === "number" && s.tasks_rev > listAbove && x) {
      listAsking = true;
      x.xpg_tasks().then(function (r) {
        listAsking = false;
        setList(r);
      }, function () { listAsking = false; });
    }
    if (unitsName !== s.units) {
      unitsName = s.units;
      drawTask();
    }
    drawNav(s);
  }

  // The row under the strip: the point flown to, which way to turn, bearing and distance.
  function drawNav(s) {
    var nav = s.nav;
    document.body.classList.toggle("has-task", !!nav);
    if (!nav) {
      if (lastNav) {
        lastNav = null;
        drawPoints(null);
      }
      return;
    }
    var u = f.units(s.units);
    setText(els["nav-role"], nav.finished ? "DONE" : roleTag(nav.role, nav.index));
    setText(els["nav-name"], nav.name);
    drawLimit(els["nav-limit"], nav, u);
    setText(els["nav-bearing"], f.degrees(nav.bearing_deg));
    setText(els["nav-dist"], f.distance(nav.dist_m, u) + " " + u.distance);
    var turn = f.known(nav.bearing_deg) && f.known(s.heading_deg)
      ? "rotate(" + Math.round(nav.bearing_deg - s.heading_deg) + "deg)" : "";
    if (els["nav-arrow"].style.transform !== turn) els["nav-arrow"].style.transform = turn;
    els.navrow.classList.toggle("in-zone", !!nav.in_zone);
    els.navrow.classList.toggle("done", !!nav.finished);
    if (!lastNav || lastNav.index !== nav.index || lastNav.started !== nav.started ||
        lastNav.finished !== nav.finished || Math.round(lastNav.task_left_m / 100) !== Math.round(nav.task_left_m / 100)) {
      drawPoints(nav);
    }
    lastNav = nav;
  }

  // The height limits of the point flown to, red while the glider is outside them, with what is
  // wrong unless `short` (the Glide Computer's header, where room is short).
  function drawLimit(node, nav, u, short) {
    var text = nav && !nav.finished ? f.limits(nav.max_m, nav.min_m, u) : "";
    var out = !!(text && nav.height);
    if (out && !short) text = (nav.height === "high" ? "TOO HIGH " : "TOO LOW ") + text;
    setText(node, text);
    node.classList.toggle("out", out);
    node.title = !text ? "" : out ? "Too " + nav.height + " for this zone: it counts only within its height limits"
      : "Height limits of this zone, above sea level: it counts only within them";
  }

  // --- the task loaded ----------------------------------------------------------------------

  function setTask(t) {
    if (!t || typeof t !== "object") return;
    taskRev = t.rev;
    task = t.name === null ? null : t;
    loading = null;
    // In the Glide Computer the picker covers the map: a task picked closes it, so the map can
    // show the task whole.
    if (fitNext && task && xpg.glide) xpg.glide.setTaskShown(false);
    xpg.map.setTask(task, fitNext);
    fitNext = false;
    drawTask();
    drawList();
  }

  function drawTask() {
    if (!els) return;
    var u = f.units(unitsName);
    setText(els["task-name"], task ? task.name : "No task loaded");
    setText(els["task-total"], task ? f.distance(task.total_m, u) + " " + u.distance : "");
    els["task-buttons"].style.display = task ? "" : "none";
    var ul = els["task-remarks"];
    while (ul.firstChild) ul.removeChild(ul.firstChild);
    var remarks = task && Array.isArray(task.remarks) ? task.remarks : [];
    for (var i = 0; i < remarks.length; i++) ul.appendChild(el("li", "", String(remarks[i])));
    drawPoints(lastNav);
  }

  // The points, with the leg to each; the one flown to marked, those behind it dimmed.
  function drawPoints(nav) {
    var ol = els["task-points"];
    while (ol.firstChild) ol.removeChild(ol.firstChild);
    if (!task) return;
    var u = f.units(unitsName);
    for (var i = 0; i < task.points.length; i++) {
      var p = task.points[i];
      var li = el("li");
      li.appendChild(el("span", "tag", roleTag(p.role, i)));
      li.appendChild(el("span", "name", p.name));
      var lim = f.limits(p.max_m, p.min_m, u);
      if (lim) li.appendChild(el("span", "lim", lim));
      li.appendChild(el("span", "leg", i > 0 ? f.distance(task.legs_m[i - 1], u) : ""));
      if (nav) {
        if (nav.finished || (nav.started && i < nav.index)) li.className = "taken";
        else if (i === nav.index) li.className = "active";
      }
      ol.appendChild(li);
    }
    if (nav && nav.started && !nav.finished) {
      var left = el("li", "left");
      left.appendChild(el("span", "tag", "LEFT"));
      left.appendChild(el("span", "name", Math.round(nav.task_done * 100) + " % done"));
      left.appendChild(el("span", "leg", f.distance(nav.task_left_m, u)));
      ol.appendChild(left);
    }
  }

  // --- the picker ---------------------------------------------------------------------------

  var files = [];
  var current = null;

  function setList(r) {
    if (!r || typeof r !== "object") return;
    listRev = r.rev;
    if (listAbove !== null && r.rev > listAbove) listAbove = null;  // the list awaited
    files = Array.isArray(r.files) ? r.files : [];
    current = r.current || null;
    var folder = String(r.folder || "");
    setText(els["task-folder"], folder.replace(/^.*[\\\/](Output[\\\/])/, "$1"));
    els["task-folder"].title = folder;
    loading = null;  // a load makes the list again: the task, if it loaded, comes with task_rev
    setText(els["task-note"], files.length ? String(r.note || "") :
      "No task files here. Put CUP or PLN files in X-Plane's Output/xp-gliding/tasks/ folder and press ↻.");
    drawList();
  }

  function drawList() {
    if (!els) return;
    var box = els["task-list"];
    while (box.firstChild) box.removeChild(box.firstChild);
    var u = f.units(unitsName);
    for (var i = 0; i < files.length; i++) {
      var file = files[i];
      box.appendChild(el("div", "file", file.file));
      if (file.error) box.appendChild(el("div", "file-error", file.error));
      for (var j = 0; j < file.tasks.length; j++) {
        var t = file.tasks[j];
        var b = el("button", "pick");
        b.type = "button";
        b.appendChild(el("span", "name", t.name));
        b.appendChild(el("span", "leg", f.distance(t.total_m, u) + " " + u.distance));
        var isCurrent = task && current && current.file === file.file && current.index === t.index;
        var isLoading = loading && loading.file === file.file && loading.index === t.index;
        if (isCurrent) b.classList.add("current");
        if (isLoading) b.classList.add("loading");
        b.addEventListener("click", pick.bind(null, file.file, t.index, String(t.key || "")));
        box.appendChild(b);
      }
    }
  }

  // The key says which task was meant: Python loads it only if the file still has it.
  function pick(file, index, key) {
    loading = {file: file, index: index};
    current = {file: file, index: index};
    fitNext = true;
    wantList();  // Python makes the list again after the load: current as it now is
    send({cmd: "load_task", file: file, index: index, key: key});
    drawList();
  }

  // The TASK view shown: the folder read again, so a file just put there appears.
  function shown() {
    if (!els) find();
    list();
  }

  return {draw: draw, shown: shown, drawLimit: drawLimit};
})();
