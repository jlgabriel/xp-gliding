"""The Flight Computer: a browser window showing a local page, the other instrument beside the HUD.

The window's content is X-Plane 12.4.4's browser (CEF, SDK 440, through XPPython3 4.8.0): one page
from `xp_gliding/web/` covers it, and Python owns the data. The page asks for it through two
functions, registered before the page is loaded as the SDK requires:

  xplane.xpg_state()     the state snapshot (`nav/snapshot.py`), JSON; the page polls it at the
                         rate the snapshot gives (`poll_hz`, 5 by default)
  xplane.xpg_do({cmd})   an action: "release_keys" (after every click on the page, see below),
                         "set" a view, "log" a line from the page

Both callbacks return a string built beforehand or queue the work for the next tick, so the page
costs Python next to nothing. The page never reads the simulator and computes nothing that matters.

Its own flight loop runs at the HUD's 10 Hz, also while paused, since the window needs looking after
then too. It reads the HUD's instruments (`hud.Hud`: the vario, the 30 s average, the thermal's
climb, the centring aid), never a second copy, and sets `Hud.also_wanted` so they are sampled while
only this instrument is shown. It reads nothing of the engine's thermals: what it shows is what the
glider can observe. Every second tick (5 Hz) it builds the snapshot, only while its window exists.

The window, found by measuring (2026-11-17, X-Plane 12.4.4, XPPython3 4.8.0):
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

from ..nav.snapshot import snapshot_json, track, wind_from

PERIOD_S = 0.1  # as the HUD's sampling
SNAPSHOT_EVERY = 2  # ticks: 5 Hz
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
DO_VIEWS = ("flight",)  # what "set view" accepts: the built views (config.COMPUTER_VIEWS)


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
    def __init__(self, settings, hud, log, on_settings_changed):
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
        self._wind_x = ref("sim/weather/aircraft/wind_now_x_msc")
        self._wind_z = ref("sim/weather/aircraft/wind_now_z_msc")
        self.loop = xp.createFlightLoop(self.on_loop, xp.FlightLoop_Phase_AfterFlightModel, None)
        if not self.available:
            log("Flight Computer: not available here (it needs X-Plane 12.4.4 and XPPython3 4.8.0); "
                "the HUD is the instrument")

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
        xp.windowAddBrowserFunction(window, "xpg_state", self.on_state)
        xp.windowAddBrowserFunction(window, "xpg_do", self.on_do)
        self._ticks = 0
        self._state = self.snapshot()
        self._refreshed = False
        self._loaded_at = None
        self._error_logged = False
        self._seen_geometry = list(rect)
        self._seen_since = now
        self._placed = list(rect)
        xp.windowSetURL(window, self.url)

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

    # --- the snapshot ---------------------------------------------------------------

    def snapshot(self):
        hud = self.hud
        vario, thermal, aid = hud.vario, hud.thermal, hud.aid
        getf = xp.getDataf
        track_deg, gs_ms = track(getf(self._vx), getf(self._vz))
        wind_deg, wind_ms = wind_from(getf(self._wind_x), getf(self._wind_z))
        st = self.settings
        values = {
            "t": getf(self._time),
            "valid": vario.valid and not hud.failed,
            "units": st.hud_units,
            "view": st.computer_view,
            "poll_hz": self.poll_hz,
            "lat": xp.getDatad(self._lat), "lon": xp.getDatad(self._lon),
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
        }
        return snapshot_json(values)

    # --- callbacks from the page and from CEF ------------------------------------------

    def on_state(self, windowID, json_str, refCon):
        self.requests += 1
        return self._state

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
