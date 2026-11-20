"""The Flight Computer and the Glide Computer: a browser window showing a local page, the other
instrument beside the HUD.

Both computers are this one window and page, in two layouts (`computer_layout`): the Flight
Computer's strip, MAP, FLIGHT and TASK; or the Glide Computer's three screens, GLIDE, INFO and
THERMAL, with the functions of Condor 3's flight computer drawn our own way. What follows says
"Flight Computer" for both.

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
                         "set" a view or a screen, "target" (delta +1 or -1: browse the Glide
                         Computer's target), "log" a line from the page; for tasks "list_tasks",
                         "load_task" (a file's name among those listed, never a path, the task's
                         number in it and its key as listed), "clear_task", "next_point",
                         "prev_point", all done by the next tick; a load also makes the list
                         again, so the page sees the file as it now is

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
line is crossed by it nor zone entered. A jump it is not told of, such as a short move on X-Plane's
map, the progress sees by itself from the speed between two places (`nav.task.Progress.update`). The task chosen is kept in the settings (`computer_task`,
"file.cup#n", and `computer_task_key`, `nav.task.task_key`) and loaded again at start, its progress
from the start. A file may be edited after the choice: the number is trusted only while the key
matches, else the task with that key is loaded, and with none nothing is (the pilot picks again).

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

Commands, shipped with no key: the pilot binds them in X-Plane's settings (Condor's keys would
clash with X-Plane's own). They act while a computer is shown:
  xp_gliding/computer/screen_next, screen_prev     the next or previous screen (the Glide
                                                   Computer's) or view (the Flight Computer's)
  xp_gliding/computer/zoom_in, zoom_out            the map's zoom
  xp_gliding/computer/map_mode_next, map_mode_prev the map's display: with tiles, or the grid only
  xp_gliding/computer/target_next, target_prev     browse the target along the task (and back to
                                                   the takeoff), never changing the progress
The zoom and the map's display are the page's own: those commands go to it in the snapshot
(`keys`, numbered, so each is done once). The screen and the target are Python's.

The Glide Computer goes to THERMAL by itself (`computer_auto_thermal`, on by default) once the
glider has turned one way for AUTO_IN_S, so a turn onto a new course does not; and back to the
screen it was on once it has flown straight for AUTO_OUT_S, as the thermal's average ends
(`ThermalAverage.LEAVE_S`). A screen the pilot chooses meanwhile is kept.

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
from ..nav.glide import GlideRatio, height_over, required_ld, vmg
from ..nav.snapshot import snapshot_json, track, wind_from
from ..nav.task import Progress, Task, find_task, task_key
from ..nav.track import Track
from .config import COMPUTER_SCREENS

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
# A window that will not open is tried again this long after: seen in X-Plane 12.4.4 when a flight
# loads under its main menu (2026-11-19, a flight started through the web API), where
# setWindowResizingLimits raised that it "is available only in XPLM300 and up".
OPEN_RETRY_S = 5.0
TITLES = {"flight": "XP-Gliding Flight Computer", "glide": "XP-Gliding Glide Computer"}
# (name, what X-Plane's keyboard settings show for it)
COMMANDS = (
    ("screen_next", "next screen"),
    ("screen_prev", "previous screen"),
    ("zoom_in", "zoom the map in"),
    ("zoom_out", "zoom the map out"),
    ("map_mode_next", "next map display"),
    ("map_mode_prev", "previous map display"),
    ("target_next", "next target"),
    ("target_prev", "previous target"),
)
PAGE_COMMANDS = ("zoom_in", "zoom_out", "map_mode_next", "map_mode_prev")  # done by the page
KEYS_KEPT = 8  # the page's commands, the last ones, in each snapshot
AUTO_IN_S = 15.0  # turning one way this long (simulator time): circling, THERMAL shown
AUTO_OUT_S = 20.0  # straight this long: the thermal left, the screen before it back
KT_TO_MS = 0.514444
WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")
PAGE = os.path.join(WEB_DIR, "index.html")
DO_VIEWS = ("map", "flight", "task")  # what "set view" accepts: the built views (config.COMPUTER_VIEWS)
MAX_ZOOM = 17  # the map's closest zoom: OpenTopoMap's last level
TASK_ACTIONS = ("list_tasks", "load_task", "clear_task", "next_point", "prev_point")
NO_TASK = '{"rev":%d,"name":null}'
GONE_NOTE = "That task is no longer in its file as listed: pick it again."


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
        self.open_failures = 0  # tries in a row that did not open the window
        self._open_after = 0.0  # no try before this (time.monotonic)
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
        self._tasks_json = '{"rev":0,"folder":"","files":[],"current":null,"note":""}'
        self._list_note = ""  # why the last load failed, shown with the next list
        self._save_settings = False  # the settings changed at start, before the plugin can save them
        self._actions = []  # the page's task actions, done by the next tick
        self._nav_ticks = 0
        self._nav = None  # the snapshot's nav, the last made
        self.nav_index = -1  # for the test pilot: the point flown to, -1 without a task
        self.nav_dist_m = 0.0
        self.nav_bearing_deg = 0.0
        self.target_index = -2  # for the test pilot: the target's index, -1 the takeoff, -2 no task
        self.target_dist_m = 0.0
        self.glide = GlideRatio()  # E
        self.ld = 0.0  # E for the test pilot, 0 when not shown
        self._keys = []  # [number, command] of the page's last commands
        self._key_number = 0
        self._title = None
        self._turn_since = None  # simulator time the glider began turning this way, or None
        self._turn_way = 0
        self._straight_since = None
        self.auto_thermal = False  # THERMAL shown by itself, for the test pilot too
        self._auto_back = None  # the screen to go back to, None to stay
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
        self.commands = []
        for name, what in COMMANDS:
            cmd = xp.createCommand(f"xp_gliding/computer/{name}", f"XP-Gliding computer: {what}")
            xp.registerCommandHandler(cmd, self.on_command, 1, name)
            self.commands.append((cmd, name))
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
        for cmd, name in self.commands:
            xp.unregisterCommandHandler(cmd, self.on_command, 1, name)
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
        if self._save_settings:  # the saved task found elsewhere in its file at start
            self._save_settings = False
            self.on_settings_changed()
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
        if self.settings.computer_layout == "glide" and self.settings.computer_auto_thermal:
            self._auto_screen(xp.getDataf(self._time))
        elif self.auto_thermal:
            self.auto_thermal = False
            self._auto_back = None
        if self._actions:
            self._do_actions()
        if window is None:
            if now < self._open_after:
                return
            try:
                self._open(now)
            except Exception:
                self._open_failed(now)
                return
            if self.open_failures:
                self.log(f"Flight Computer opened, after {self.open_failures} tries that did not")
                self.open_failures = 0
            window = self.window
        if self._title != self.settings.computer_layout:  # the other computer chosen, window open
            self._set_title(window)
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
        self._set_title(window)
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

    def _set_title(self, window):
        self._title = self.settings.computer_layout
        xp.setWindowTitle(window, TITLES.get(self._title, TITLES["flight"]))

    def _open_failed(self, now):
        """The window did not open: what was made of it goes, unsaved, and it is tried again
        later, rather than the Flight Computer stopping for the session. Logged the first time."""
        self.open_failures += 1
        if self.open_failures == 1:
            self.log(f"Flight Computer window did not open; trying again every {OPEN_RETRY_S:.0f} s:\n"
                     + traceback.format_exc())
        window, self.window = self.window, None
        if window is not None:
            try:
                xp.destroyWindow(window)
            except Exception:
                pass
        self._open_after = now + OPEN_RETRY_S

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
            self.glide.reset()
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
            msl = xp.getDatad(self._elevation)
            self.track.add(t, lat, lon, msl)
            self.glide.add(t, lat, lon, msl)
        if progress is not None and progress.update(lat, lon, t):
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
                self._list_note = action.get("note", "")
                self._list_tasks()
            elif cmd == "load_task":
                if not self._load_task(action["file"], action["index"], action["key"]):
                    self._list_note = GONE_NOTE
                self._list_tasks()
            elif cmd == "target":
                if self.progress is not None:
                    self.progress.browse(action["delta"])
            elif cmd == "clear_task":
                if self.task is not None:
                    self._set_task(None)
                    self.settings.computer_task = ""
                    self.settings.computer_task_key = ""
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
                    entry["tasks"].append({"index": i, "name": taskdef.label(), "key": task_key(taskdef),
                                           "points": len(taskdef.points),
                                           "total_m": round(Task(taskdef).total_m, 1)})
                if not found.tasks:
                    entry["error"] = "no tasks in this file"
            files.append(entry)
        current = None
        if self.task is not None:  # the task loaded, as this list has it: maybe moved, maybe gone
            file = self.settings.computer_task.rpartition("#")[0]
            for entry in files:
                if entry["file"] == file:
                    current = next(({"file": file, "index": t["index"]} for t in entry["tasks"]
                                    if t["key"] == self.task.key), None)
        self.tasks_rev += 1
        self._tasks_json = json.dumps({"rev": self.tasks_rev, "folder": self.tasks_folder or "",
                                       "files": files, "current": current, "note": self._list_note},
                                      separators=(",", ":"))
        self._list_note = ""

    def _load_task(self, file, index, key, saved=False):
        """Load the task of `file` (a name in the tasks folder, never a path) that `index` and `key`
        name (`nav.task.find_task`). True if loaded."""
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
        at = find_task(found.tasks, index, key)
        if at is None:
            self.log(f"Flight Computer: {file} has no task {index} as chosen (key {key!r}): "
                     "it was changed or removed")
            return False
        task = Task(found.tasks[at], file)
        self._set_task(task)
        self.log(f"Flight Computer: task {task.name!r} from {file}: {len(task.points)} points, "
                 f"{task.total_m / 1000.0:.1f} km" + (f" (now task {at} of the file)" if at != index else ""))
        if not saved or at != index or key != task.key:
            self.settings.computer_task = f"{file}#{at}"
            self.settings.computer_task_key = task.key
            if saved:  # at start: saved by the first tick
                self._save_settings = True
            else:
                self.on_settings_changed()
        return True

    def _load_saved_task(self):
        file, _, index = self.settings.computer_task.rpartition("#")
        if (not file or not index.isdigit()
                or not self._load_task(file, int(index), self.settings.computer_task_key, saved=True)):
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
        t = getf(self._time)
        msl = xp.getDatad(self._elevation)
        thermal_gain = thermal.gain_m if thermal.valid else None
        target_vmg = None
        if self.progress is not None:
            nav = self._nav = self.progress.nav(lat, lon, t)
            self.nav_index, self.nav_dist_m, self.nav_bearing_deg = nav["index"], nav["dist_m"], nav["bearing_deg"]
            target = nav["target"]
            dh = height_over(msl, target["elev_m"])
            req = required_ld(target["dist_m"], dh)
            target["dh_m"] = None if dh is None else round(dh, 1)
            target["req_ld"] = None if req is None else round(req, 1)
            target_vmg = vmg(gs_ms, track_deg, target["bearing_deg"])
            self.target_index, self.target_dist_m = target["index"], target["dist_m"]
        else:
            self.target_index, self.target_dist_m = -2, 0.0
        ld = self.glide.ld
        self.ld = ld or 0.0
        values = {
            "t": t, "local_s": getf(self._local),
            "valid": vario.valid and not hud.failed,
            "units": st.hud_units,
            "view": st.computer_view,
            "layout": st.computer_layout, "screen": st.computer_screen, "keys": self._keys,
            "poll_hz": self.poll_hz,
            "lat": lat, "lon": lon,
            "msl_m": msl, "agl_m": getf(self._agl),
            "track_deg": track_deg, "heading_deg": getf(self._psi), "gs_ms": gs_ms,
            "ias_ms": getf(self._ias) * KT_TO_MS, "tas_ms": getf(self._tas),
            "te_ms": vario.te_ms, "netto_ms": vario.netto_ms if vario.has_netto else None,
            "avg_ms": vario.average_ms,
            "thm_ms": thermal.average_ms, "thm_valid": thermal.valid, "thm_active": thermal.active,
            "thm_gain_m": thermal_gain, "thm4_ms": thermal.recent_ms,
            "ld": ld, "vmg_ms": target_vmg,
            "circling": aid.turning,
            "aid_valid": aid.valid, "aid_core_az_deg": aid.core_az_deg, "aid_amp_ms": aid.amp_ms,
            "wind_from_deg": wind_deg, "wind_ms": wind_ms,
            "top_m": hud.top_m if st.thermals_enabled else None,
            "track_n": self.track.count, "track_epoch": self.track.epoch,
            "task_rev": self.task_rev, "tasks_rev": self.tasks_rev,
            "nav": self._nav if self.progress is not None else None,
        }
        return snapshot_json(values)

    # --- THERMAL by itself -------------------------------------------------------------

    def _auto_screen(self, t):
        st = self.settings
        turning = self.hud.aid.turning
        if turning:
            if self._turn_since is None or turning != self._turn_way or t < self._turn_since:
                self._turn_since, self._turn_way = t, turning
            self._straight_since = None
            if not self.auto_thermal and t - self._turn_since >= AUTO_IN_S:
                self.auto_thermal = True
                self._auto_back = st.computer_screen if st.computer_screen != "thermal" else None
                st.computer_screen = "thermal"
            return
        self._turn_since = None
        if not self.auto_thermal:
            return
        if self._straight_since is None or t < self._straight_since:
            self._straight_since = t
        elif t - self._straight_since >= AUTO_OUT_S:
            self.auto_thermal = False
            if self._auto_back is not None and st.computer_screen == "thermal":
                st.computer_screen = self._auto_back
            self._auto_back = None

    def _screen_chosen(self):
        """The pilot chose a screen: an automatic THERMAL does not take it back."""
        self._auto_back = None

    # --- the computers' commands --------------------------------------------------------

    def on_command(self, commandRef, phase, name):
        if phase == xp.CommandBegin:
            try:
                if self.wanted:
                    self.command(name)
            except Exception:
                self._fail(f"its command {name}")
        return 1

    def command(self, name):
        st = self.settings
        if name in ("screen_next", "screen_prev"):
            step = 1 if name == "screen_next" else -1
            if st.computer_layout == "glide":
                at = COMPUTER_SCREENS.index(st.computer_screen) if st.computer_screen in COMPUTER_SCREENS else 0
                st.computer_screen = COMPUTER_SCREENS[(at + step) % len(COMPUTER_SCREENS)]
                self._screen_chosen()
            else:
                at = DO_VIEWS.index(st.computer_view) if st.computer_view in DO_VIEWS else 0
                st.computer_view = DO_VIEWS[(at + step) % len(DO_VIEWS)]
            self.on_settings_changed()
        elif name in PAGE_COMMANDS:
            self._key_number += 1
            self._keys = (self._keys + [[self._key_number, name]])[-KEYS_KEPT:]
        elif name in ("target_next", "target_prev") and self.progress is not None:
            self.progress.browse(1 if name == "target_next" else -1)

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
            elif cmd == "set" and request.get("screen") in COMPUTER_SCREENS:
                if self.settings.computer_screen != request["screen"]:
                    self.settings.computer_screen = request["screen"]
                    self._screen_chosen()
                    self.on_settings_changed()
            elif cmd == "target" and request.get("delta") in (-1, 1) and not isinstance(request.get("delta"), bool):
                self._actions.append({"cmd": "target", "delta": request["delta"]})  # by the next tick
            elif cmd in TASK_ACTIONS:
                action = {"cmd": cmd}
                if cmd == "load_task":
                    file, index, key = request.get("file"), request.get("index"), request.get("key")
                    if (not isinstance(file, str) or not isinstance(index, int) or isinstance(index, bool)
                            or not isinstance(key, str) or not key or len(key) > 64):
                        return '{"ok": false, "error": "no such task"}'
                    if file not in self._task_files():  # removed or renamed since the list was made
                        self._actions.append({"cmd": "list_tasks", "note": GONE_NOTE})
                        return '{"ok": false, "error": "no such task"}'
                    action.update(file=file, index=index, key=key)
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
