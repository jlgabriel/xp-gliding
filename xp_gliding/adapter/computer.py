"""The Flight Computer: a browser window showing a local page, the other instrument beside the HUD.

The window's content is X-Plane 12.4.4's browser (CEF, SDK 440, through XPPython3 4.8.0): one page
from `xp_gliding/web/` covers it, and Python owns the data. The page asks for it through two
functions, registered before the page is loaded as the SDK requires:

  xplane.xpg_setup()     what the page needs once: the map's tiles and their attribution
  xplane.xpg_state()     the state snapshot (`nav/snapshot.py`), JSON; the page polls it at the
                         rate the snapshot gives (`poll_hz`, 5 by default)
  xplane.xpg_track({epoch, from})
                         the track's points the page does not have yet (`nav/track.py`); the page
                         asks when the snapshot's `track_n` or `track_epoch` say there are some
  xplane.xpg_tasks()     the CUP files in the tasks folder and the tasks in each, for the picker;
                         made again by the next tick after the page asks with "list_tasks", and
                         the snapshot's `tasks_rev` says when it is ready
  xplane.xpg_task()      the task loaded, whole (`nav/task.py`), asked when `task_rev` changes
  xplane.xpg_do({cmd})   an action: "release_keys" (after every click on the page, see below),
                         "set" a view, "log" a line from the page; for tasks "list_tasks",
                         "load_task" (a file's name among those listed, never a path, and the
                         task's number in it), "clear_task", "next_point", "prev_point", all done
                         by the next tick

Both callbacks return a string built beforehand or queue the work for the next tick, so the page
costs Python next to nothing. The page never reads the simulator and computes nothing that matters.

Its own flight loop runs at the HUD's 10 Hz, also while paused, since the window needs looking after
then too. It reads the HUD's instruments (`hud.Hud`: the vario, the 30 s average, the thermal's
climb, the centring aid), never a second copy, and sets `Hud.also_wanted` so they are sampled while
only this instrument is shown. It reads nothing of the engine's thermals: what it shows is what the
glider can observe. Every second tick (5 Hz) it builds the snapshot, only while its window exists.
While the Flight Computer is the chosen instrument, window open or not, it offers the glider's
place to the track, which keeps one point a second of simulator time (none paused or in replay),
and starts the track again when the HUD's instruments start again: a jump or a new flight. With a
task loaded it gives the place to the task's progress too (`nav/task.py`) five times a second, which
takes each point as its zone is reached; a jump makes the progress forget the last place, so no
line is crossed by it. The task chosen is kept in the settings (`computer_task`, "file.cup#n") and
loaded again at start, its progress from the start.

The window, found by measuring (2026-11-17, X-Plane 12.4.4, XPPython3 4.8.0):
- stays inside X-Plane: popped out into a window of its own, X-Plane draws a corner of the page,
  enlarged, so a popped-out Flight Computer is put back at the next look (`_keep_in`);
- exists only while the Flight Computer is wanted: closing it in any way destroys it. Its close box
  only hides it, and a hidden page keeps running and costing, so the next tick sees it hidden,
  saves its place, destroys it and unticks the Flight Computer;
- keeps the keys from the simulator after a click on the page, while X-Plane says the window has
  no keyboard focus. Taking the focus for the window and then giving it to X-Plane gives the keys
  back, so the page asks for that after every pointer release;
- may load its page before `window.xplane` exists on the first window after a cold start: the page
  waits for it, and if no call arrives within LOAD_WATCHDOG_S of the load, the page is reloaded once.

Where X-Plane or XPPython3 is older, there is no Flight Computer (`browser_available`): the menu
greys it out and the HUD is the instrument. An error here stops the Flight Computer only: it is
logged, the window goes at the next tick (never from its own callback), and the thermals go on.
"""

import json
import os
import pathlib
import time
import traceback

import xp

from ..nav import cup
from ..nav.snapshot import snapshot_json, track, wind_from
from ..nav.task import Progress, Task
from ..nav.track import Track

PERIOD_S = 0.1  # as the HUD's sampling
SNAPSHOT_EVERY = 2  # ticks: 5 Hz
NAV_EVERY = 2  # ticks between places given to the task: 5 Hz, steps of about 6 m, enough for a line
LOOK_EVERY = 5  # ticks between looks at the window's close box and place: 2 Hz is soon enough
POLL_HZ = 5  # how often the page asks for the snapshot; xp_gliding/computer/poll_hz changes it for a new window
DEFAULT_SIZE = (480, 420)
DEFAULT_OFFSET = (120, 160)  # the default place, from the screen's top left corner
MIN_SIZE, MAX_SIZE = (320, 240), (1400, 1000)
ON_SCREEN_PX = 80  # a saved place is used only if this much of the window is on the screen
GEOMETRY_SETTLE_S = 1.0  # a moved or resized window is saved once it has stayed so this long
LOAD_WATCHDOG_S = 3.0
TITLE = "XP-Gliding Flight Computer"
KT_TO_MS = 0.514444
WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
PAGE = os.path.join(WEB_DIR, "index.html")
DO_VIEWS = ("map", "flight", "task")  # what "set view" accepts: the built views (config.COMPUTER_VIEWS)
MAX_ZOOM = 17  # the map's closest zoom: OpenTopoMap's last level
TASK_ACTIONS = ("list_tasks", "load_task", "clear_task", "next_point", "prev_point")
NO_TASK = '{"rev":%d,"name":null}'


def browser_available():
    """Browser windows need X-Plane 12.4.4 (SDK 440) and XPPython3 4.8.0."""
    return all(hasattr(xp, name) for name in ("WindowContentTypeBrowser", "windowSetURL",
                                               "windowAddBrowserFunction", "takeKeyboardFocus"))


def overlaps(rect, bounds, margin):
    """Does `margin` of rect (left, top, right, bottom, y up) lie inside bounds, both ways?"""
    left, top, right, bottom = rect
    b_left, b_top, b_right, b_bottom = bounds
    return (min(right, b_right) - max(left, b_left) >= margin
            and min(top, b_top) - max(bottom, b_bottom) >= margin)


class Computer:
    def __init__(self, settings, hud, log, on_settings_changed, track_path=None, tasks_folder=None):
        self.settings = settings
        self.hud = hud
        self.log = log
        self.on_settings_changed = on_settings_changed  # the plugin saves them and updates its menu
        self.available = browser_available()
        self.window = None
        self.failed = False
        self.loaded = 0  # 1 once the window's page has loaded
        self.requests = 0  # bridge calls served, for the test pilot to see the page is alive
        self.tick_us = 0.0
        self.poll_hz = POLL_HZ
        self.track = Track()
        self.track_dump = 0  # the test pilot writes 1: the track goes to track_path at the next tick
        self.track_path = track_path
        self._resets_seen = hud.resets
        self.tasks_folder = tasks_folder
        self.task = None  # nav.task.Task, or None
        self.progress = None  # nav.task.Progress of the task
        self.task_rev = 0  # changes with each task loaded or cleared: the page asks for it again
        self._task_json = NO_TASK % 0
        self.tasks_rev = 0  # changes with each list of the tasks folder made
        self._tasks_json = '{"rev":0,"folder":"","files":[],"current":null}'
        self._actions = []  # the page's task actions, done by the next tick
        self._nav_ticks = 0
        self._nav = None  # the snapshot's nav, the last made
        self.nav_index = -1  # for the test pilot: the point flown to, -1 without a task
        self.nav_dist_m = 0.0
        self.nav_bearing_deg = 0.0
        self.url = pathlib.Path(PAGE).as_uri()
        self._state = snapshot_json({})
        self._ticks = 0
        self._looks = 0
        self._release_keys = False
        self._loaded_at = None  # when the page last loaded, until its first call after that
        self._requests_at_load = 0
        self._refreshed = False  # the watchdog reloads a window's page once at most
        self._error_logged = False
        self._seen_geometry = None
        self._seen_since = 0.0
        self._placed = None  # where the window was put or last saved: a place only a move changes
        self._popped_logged = False
        ref = xp.findDataRef
        self._lat = ref("sim/flightmodel/position/latitude")
        self._lon = ref("sim/flightmodel/position/longitude")
        self._elevation = ref("sim/flightmodel/position/elevation")
        self._agl = ref("sim/flightmodel/position/y_agl")
        self._vx = ref("sim/flightmodel/position/local_vx")
        self._vz = ref("sim/flightmodel/position/local_vz")
        self._psi = ref("sim/flightmodel/position/psi")
        self._ias = ref("sim/flightmodel/position/indicated_airspeed")
        self._tas = ref("sim/flightmodel/position/true_airspeed")
        self._time = ref("sim/time/total_running_time_sec")
        self._local = ref("sim/time/local_time_sec")
        self._paused = ref("sim/time/paused")
        self._replay = ref("sim/time/is_in_replay")
        self._wind_x = ref("sim/weather/aircraft/wind_now_x_msc")
        self._wind_z = ref("sim/weather/aircraft/wind_now_z_msc")
        self.loop = xp.createFlightLoop(self.on_loop, xp.FlightLoop_Phase_AfterFlightModel, None)
        if not self.available:
            log("Flight Computer: not available here (it needs X-Plane 12.4.4 and XPPython3 4.8.0); "
                "the HUD is the instrument")
        elif settings.computer_task:
            self._load_saved_task()

    # --- life cycle ------------------------------------------------------------

    def enable(self):
        xp.scheduleFlightLoop(self.loop, PERIOD_S, 1)

    def disable(self):
        xp.scheduleFlightLoop(self.loop, 0, 1)
        self.hud.also_wanted = False
        self._close()

    def stop(self):
        xp.destroyFlightLoop(self.loop)
        self._close()

    @property
    def window_open(self):
        return int(self.window is not None)

    @property
    def wanted(self):
        st = self.settings
        return (st.enabled and st.computer_enabled and self.hud.eligible and self.available
                and not self.failed)

    def _fail(self, where):
        self.failed = True
        self.hud.also_wanted = False
        self.log(f"Flight Computer stopped, error in {where}:\n" + traceback.format_exc())

    # --- ten times a second -------------------------------------------------------

    def on_loop(self, sinceLast, elapsedTime, counter, refCon):
        t0 = time.perf_counter()
        try:
            self.tick(time.monotonic())
        except Exception:
            self._fail("its loop")
            try:
                self._close()
            except Exception:
                pass
        self.tick_us += 0.05 * ((time.perf_counter() - t0) * 1e6 - self.tick_us)
        return PERIOD_S

    def tick(self, now):
        wanted = self.wanted
        self.hud.also_wanted = wanted
        window = self.window
        self._looks += 1
        look = self._looks >= LOOK_EVERY
        if look:
            self._looks = 0
        if window is not None and look and not xp.getWindowIsVisible(window):
            # Its close box, which only hides it: the pilot closed the Flight Computer.
            self._close()
            self.settings.computer_enabled = False
            self.hud.also_wanted = False
            self.log("Flight Computer closed")
            self.on_settings_changed()
            return
        if not wanted:
            self._close()
            return
        self._record()
        if self._actions:
            self._do_actions()
        if window is None:
            self._open(now)
            window = self.window
        if self._release_keys:
            self._release_keys = False
            # After a click the page keeps the keys although X-Plane says it has no focus:
            # taking it for the window and then giving it to X-Plane gives them back (V7).
            xp.takeKeyboardFocus(window)
            xp.takeKeyboardFocus(0)
        if look:
            if xp.windowIsPoppedOut(window):
                self._keep_in(window)
            self._watch_geometry(window, now)
        self._watch_load(window, now)
        self._ticks += 1
        if self._ticks >= SNAPSHOT_EVERY:
            self._ticks = 0
            self._state = self.snapshot()

    def _open(self, now):
        st = self.settings
        bounds = xp.getScreenBoundsGlobal()
        rect = st.computer_window
        if not rect or not overlaps(rect, bounds, ON_SCREEN_PX):
            left, top = bounds[0] + DEFAULT_OFFSET[0], bounds[1] - DEFAULT_OFFSET[1]
            rect = [left, top, left + DEFAULT_SIZE[0], top - DEFAULT_SIZE[1]]
        left, top, right, bottom = rect
        window = xp.createWindowEx(left, top, right, bottom, visible=1,
                                   decoration=xp.WindowDecorationRoundRectangle,
                                   layer=xp.WindowLayerFloatingWindows,
                                   contentType=xp.WindowContentTypeBrowser,
                                   browserLoadFinished=self.on_load, browserLoadError=self.on_load_error)
        self.window = window
        xp.setWindowTitle(window, TITLE)
        xp.setWindowResizingLimits(window, MIN_SIZE[0], MIN_SIZE[1], MAX_SIZE[0], MAX_SIZE[1])
        # Before the first URL: functions added after it are ignored.
        xp.windowAddBrowserFunction(window, "xpg_setup", self.on_setup)
        xp.windowAddBrowserFunction(window, "xpg_state", self.on_state)
        xp.windowAddBrowserFunction(window, "xpg_track", self.on_track)
        xp.windowAddBrowserFunction(window, "xpg_do", self.on_do)
        xp.windowAddBrowserFunction(window, "xpg_tasks", self.on_tasks)
        xp.windowAddBrowserFunction(window, "xpg_task", self.on_task)
        self._ticks = 0
        self._state = self.snapshot()
        self._refreshed = False
        self._loaded_at = None
        self._error_logged = False
        self._seen_geometry = list(rect)
        self._seen_since = now
        self._placed = list(rect)
        xp.windowSetURL(window, self.url)

    def _keep_in(self, window):
        """Popped out into a window of its own, X-Plane 12.4.4 draws a browser window's page wrong:
        a corner of it, enlarged and blurred, while the page itself measures the right size
        (measured 2026-11-17; reloading does not help). So it goes back inside X-Plane, at its
        last place and size, until X-Plane draws it right."""
        xp.setWindowPositioningMode(window, xp.WindowPositionFree, -1)
        if self._placed is not None:
            xp.setWindowGeometry(window, *self._placed)
        if not self._popped_logged:
            self._popped_logged = True
            self.log("Flight Computer: kept inside X-Plane; popped out, X-Plane 12.4.4 does not draw "
                     "its page right")

    def _close(self):
        window = self.window
        if window is None:
            return
        self.window = None
        self.loaded = 0
        self._loaded_at = None
        try:
            self._save_geometry(window)
        finally:
            xp.destroyWindow(window)

    def _geometry(self, window):
        """The window's place, or None while it is popped out into a window of its own."""
        if xp.windowIsPoppedOut(window):
            return None
        return list(xp.getWindowGeometry(window))

    def _save_geometry(self, window):
        """Saved only once the pilot moved or resized it: the default place is not written."""
        rect = self._geometry(window)
        if rect is not None and rect != self._placed:
            self._placed = rect
            self.settings.computer_window = rect
            self.on_settings_changed()

    def _watch_geometry(self, window, now):
        """Saved once it has stayed put for GEOMETRY_SETTLE_S, not at every step of a drag."""
        rect = self._geometry(window)
        if rect is None:
            return
        if rect != self._seen_geometry:
            self._seen_geometry = rect
            self._seen_since = now
        elif now - self._seen_since >= GEOMETRY_SETTLE_S:
            self._save_geometry(window)

    def _watch_load(self, window, now):
        """A page loaded but not calling: `window.xplane` was missing, or the page broke. Reload once."""
        if self._loaded_at is None:
            return
        if self.requests != self._requests_at_load:
            self._loaded_at = None
        elif now - self._loaded_at >= LOAD_WATCHDOG_S:
            self._loaded_at = None
            if not self._refreshed:
                self._refreshed = True
                self.log("Flight Computer: the page did not answer after loading; reloading it once")
                xp.windowRefresh(window, 0)
            else:
                self.log("Flight Computer: the page still does not answer")

    # --- the track -------------------------------------------------------------------

    def _record(self):
        """Offer the glider's place to the track once a second of simulator time, and to the
        task's progress at each tick."""
        if self.hud.resets != self._resets_seen:
            self._resets_seen = self.hud.resets
            self.track.restart()
            if self.progress is not None:
                self.progress.forget_place()
        if self.track_dump:
            self.track_dump = 0
            self._dump_track()
        progress = self.progress
        if progress is not None:
            self._nav_ticks += 1
            if self._nav_ticks >= NAV_EVERY:
                self._nav_ticks = 0
            else:
                progress = None  # not this tick
        t = xp.getDataf(self._time)
        due = self.track.due(t)
        if (not due and progress is None) or xp.getDatai(self._paused) or xp.getDatai(self._replay):
            return
        lat, lon = xp.getDatad(self._lat), xp.getDatad(self._lon)
        if due:
            self.track.add(t, lat, lon, xp.getDatad(self._elevation))
        if progress is not None and progress.update(lat, lon):
            self._log_taken()

    def _dump_track(self):
        """For the test pilot: the track as kept, to compare with the flight log."""
        if not self.track_path:
            return
        with open(self.track_path, "w", encoding="utf-8") as f:
            json.dump({"epoch": self.track.epoch, "start": self.track.start, "n": self.track.count,
                       "points": self.track.points()}, f)
        self.log(f"Flight Computer: track written to {self.track_path}")

    # --- tasks ---------------------------------------------------------------------------

    def _log_taken(self):
        index, how = self.progress.taken[-1]
        name = self.task.points[index].name
        if self.progress.finished:
            what = "finish"
        elif index == 0:
            what = "start"
        else:
            what = f"point {index}"
        self.log(f"Flight Computer: {what} {name!r} taken ({how})")

    def _do_actions(self):
        actions, self._actions = self._actions, []
        for action in actions:
            cmd = action["cmd"]
            if cmd == "list_tasks":
                self._list_tasks()
            elif cmd == "load_task":
                self._load_task(action["file"], action["index"])
            elif cmd == "clear_task":
                if self.task is not None:
                    self._set_task(None)
                    self.settings.computer_task = ""
                    self.on_settings_changed()
                    self.log("Flight Computer: task cleared")
            elif self.progress is not None:
                self.progress.step(1 if cmd == "next_point" else -1)
                index = self.progress.active
                self.log(f"Flight Computer: by hand to point {index} {self.task.points[index].name!r}"
                         + (", finished" if self.progress.finished else ""))

    def _task_files(self):
        return cup.find_files(self.tasks_folder) if self.tasks_folder else []

    def _list_tasks(self):
        """The picker's list: each CUP file with its tasks, or why it offers none."""
        files = []
        for name in self._task_files():
            entry = {"file": name, "tasks": [], "error": None}
            try:
                found = cup.load(os.path.join(self.tasks_folder, name))
            except OSError as exc:
                entry["error"] = str(exc)
            else:
                for i, taskdef in enumerate(found.tasks):
                    entry["tasks"].append({"index": i, "name": taskdef.label(), "points": len(taskdef.points),
                                           "total_m": round(Task(taskdef).total_m, 1)})
                if not found.tasks:
                    entry["error"] = "no tasks in this file"
            files.append(entry)
        current = None
        if self.task is not None:
            file, _, index = self.settings.computer_task.rpartition("#")
            current = {"file": file, "index": int(index) if index.isdigit() else None}
        self.tasks_rev += 1
        self._tasks_json = json.dumps({"rev": self.tasks_rev, "folder": self.tasks_folder or "",
                                       "files": files, "current": current}, separators=(",", ":"))

    def _load_task(self, file, index, saved=False):
        """Load task `index` of `file` (a name in the tasks folder, never a path). True if loaded."""
        if file not in self._task_files():
            self.log(f"Flight Computer: no task file {file!r} in {self.tasks_folder}")
            return False
        path = os.path.join(self.tasks_folder, file)
        try:
            found = cup.load(path)
        except OSError as exc:
            self.log(f"Flight Computer: could not read {path}: {exc}")
            return False
        for note in found.notes[:20]:
            self.log(f"Flight Computer: {file}, {note}")
        if not 0 <= index < len(found.tasks):
            self.log(f"Flight Computer: {file} has no task {index}")
            return False
        task = Task(found.tasks[index], file)
        self._set_task(task)
        self.log(f"Flight Computer: task {task.name!r} from {file}: {len(task.points)} points, "
                 f"{task.total_m / 1000.0:.1f} km")
        if not saved:
            self.settings.computer_task = f"{file}#{index}"
            self.on_settings_changed()
        return True

    def _load_saved_task(self):
        file, _, index = self.settings.computer_task.rpartition("#")
        if not file or not index.isdigit() or not self._load_task(file, int(index), saved=True):
            self.log(f"Flight Computer: the task saved ({self.settings.computer_task!r}) was not loaded")

    def _set_task(self, task):
        self.task = task
        self.progress = Progress(task) if task is not None else None
        self.task_rev += 1
        self._task_json = task.to_json(self.task_rev) if task is not None else NO_TASK % self.task_rev
        self._nav = None
        self.nav_index = -1

    # --- the snapshot ---------------------------------------------------------------

    def snapshot(self):
        hud = self.hud
        vario, thermal, aid = hud.vario, hud.thermal, hud.aid
        getf = xp.getDataf
        track_deg, gs_ms = track(getf(self._vx), getf(self._vz))
        wind_deg, wind_ms = wind_from(getf(self._wind_x), getf(self._wind_z))
        st = self.settings
        lat, lon = xp.getDatad(self._lat), xp.getDatad(self._lon)
        if self.progress is not None:
            nav = self._nav = self.progress.nav(lat, lon)
            self.nav_index, self.nav_dist_m, self.nav_bearing_deg = nav["index"], nav["dist_m"], nav["bearing_deg"]
        values = {
            "t": getf(self._time), "local_s": getf(self._local),
            "valid": vario.valid and not hud.failed,
            "units": st.hud_units,
            "view": st.computer_view,
            "poll_hz": self.poll_hz,
            "lat": lat, "lon": lon,
            "msl_m": xp.getDatad(self._elevation), "agl_m": getf(self._agl),
            "track_deg": track_deg, "heading_deg": getf(self._psi), "gs_ms": gs_ms,
            "ias_ms": getf(self._ias) * KT_TO_MS, "tas_ms": getf(self._tas),
            "te_ms": vario.te_ms, "netto_ms": vario.netto_ms if vario.has_netto else None,
            "avg_ms": vario.average_ms,
            "thm_ms": thermal.average_ms, "thm_valid": thermal.valid, "thm_active": thermal.active,
            "circling": aid.turning,
            "aid_valid": aid.valid, "aid_core_az_deg": aid.core_az_deg, "aid_amp_ms": aid.amp_ms,
            "wind_from_deg": wind_deg, "wind_ms": wind_ms,
            "top_m": hud.top_m if st.thermals_enabled else None,
            "track_n": self.track.count, "track_epoch": self.track.epoch,
            "task_rev": self.task_rev, "tasks_rev": self.tasks_rev,
            "nav": self._nav if self.progress is not None else None,
        }
        return snapshot_json(values)

    # --- callbacks from the page and from CEF ------------------------------------------

    def on_setup(self, windowID, json_str, refCon):
        self.requests += 1
        st = self.settings
        return json.dumps({"tiles": st.map_tiles, "attribution": st.map_attribution, "max_zoom": MAX_ZOOM})

    def on_state(self, windowID, json_str, refCon):
        self.requests += 1
        return self._state

    def on_tasks(self, windowID, json_str, refCon):
        self.requests += 1
        return self._tasks_json

    def on_task(self, windowID, json_str, refCon):
        self.requests += 1
        return self._task_json

    def on_track(self, windowID, json_str, refCon):
        """The points the page does not have: it says its epoch and the number of its next point."""
        try:
            self.requests += 1
            try:
                request = json.loads(json_str)
            except ValueError:
                request = None
            if not isinstance(request, dict):
                request = {}
            return self.track.json_from(request.get("epoch"), request.get("from"))
        except Exception:
            self._fail("xpg_track")
            return '{"epoch":-1,"from":0,"n":0,"more":false,"points":[]}'

    def on_do(self, windowID, json_str, refCon):
        try:
            self.requests += 1
            try:
                request = json.loads(json_str)
            except ValueError:
                return '{"ok": false, "error": "not JSON"}'
            cmd = request.get("cmd") if isinstance(request, dict) else None
            if cmd == "release_keys":
                self._release_keys = True  # done by the next tick, outside CEF's call
            elif cmd == "set" and request.get("view") in DO_VIEWS:
                if self.settings.computer_view != request["view"]:
                    self.settings.computer_view = request["view"]
                    self.on_settings_changed()
            elif cmd in TASK_ACTIONS:
                action = {"cmd": cmd}
                if cmd == "load_task":
                    file, index = request.get("file"), request.get("index")
                    if (not isinstance(file, str) or not isinstance(index, int) or isinstance(index, bool)
                            or file not in self._task_files()):
                        return '{"ok": false, "error": "no such task"}'
                    action.update(file=file, index=index)
                self._actions.append(action)  # done by the next tick, outside CEF's call
            elif cmd == "log":
                self.log("Flight Computer page: " + str(request.get("text", ""))[:300])
            else:
                return '{"ok": false, "error": "unknown command"}'
            return '{"ok": true}'
        except Exception:
            self._fail("xpg_do")
            return '{"ok": false, "error": "failed"}'

    def on_load(self, windowID, url, refCon):
        if url.startswith("about:"):  # CEF's own blank page before ours (XPPython3's documentation)
            return
        # It can fire twice for one load (seen in the lab, 2026-11-17): the second only restarts the watch.
        self.loaded = 1
        self._loaded_at = time.monotonic()
        self._requests_at_load = self.requests

    def on_load_error(self, windowID, url, error, refCon):
        if not self._error_logged:
            self._error_logged = True
            self.log(f"Flight Computer: its page did not load ({url}): {error}")
