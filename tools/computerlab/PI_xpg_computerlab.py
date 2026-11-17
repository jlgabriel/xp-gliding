"""Browser window lab: what an SDK 440 browser (CEF) window does in this X-Plane, measured.

Measurement tool, not part of the plugin. It answers the Flight Computer's open questions
(a browser window showing a local page, the page calling Python through `xplane.<name>()`)
before any plugin code depends on them. Install with `lab.py install` (this file and the
`xpg_computerlab/` page folder into `Resources/plugins/PythonPlugins/`), restart X-Plane, and
drive it with `lab.py`.

Driving: writing a code from CMDS to the dataref `xp_gliding/computerlab/cmd` queues that
action; the flight loop carries it out on the main thread, where the SDK wants it.

Results: the flight loop writes `Output/xp-gliding/computerlab/state.json` twice a second
(window, loads, the bridge's counts and timings, the page's last report), and every report the
page sends is appended to `events.jsonl` beside it.

The page calls two functions, registered before the first URL as the SDK requires:
  lab_ping(seq)    the page's poll: answered with the lab's settings (poll rate, pan, push),
                   timed in Python, and the thread it arrives on recorded
  lab_report(obj)  what the page found (script kinds that loaded, storage, tiles, input
                   events, round trips), queued here and written by the flight loop

Needs XPPython3 4.8.0 on X-Plane 12.4.4; without the browser content type it logs so and does
nothing. License: GPL-3.0-or-later.
"""

import json
import os
import pathlib
import threading
import time
import traceback

import xp

LOOP_PERIOD_S = 0.1
STATE_PERIOD_S = 0.5
PAGE_FOLDER = "xpg_computerlab"
SIZE = (480, 420)

CMDS = {
    1: "create_raw",   # URL built as the XPPython3 documentation does: f"file://{path}"
    2: "create_uri",   # URL from pathlib's as_uri(): file:///D:/.../X-Plane%2012/...
    3: "destroy",
    4: "show",
    5: "hide",
    6: "big",          # 1000 x 700
    7: "small",        # back to SIZE
    8: "popout",
    9: "float",
    10: "refresh",
    11: "rate2",
    12: "rate5",
    13: "rate10",
    14: "pan_on",
    15: "pan_off",
    16: "push_on",     # 10 Hz windowInjectScript from the flight loop, page counts arrivals
    17: "push_off",
    18: "late_function",  # add a function after the URL was set: expected to be ignored
    19: "rate0",       # the page stops polling
    20: "focus_none",     # keyboard focus left as CEF and X-Plane leave it
    21: "focus_release",  # the flight loop hands focus back: takeKeyboardFocus(0) when the window has it
    22: "focus_blur",     # the page blurs itself after each pointer release
    23: "kb_zero",        # once: takeKeyboardFocus(0), whatever hasKeyboardFocus says
    24: "kb_cycle",       # once: takeKeyboardFocus(window), then takeKeyboardFocus(0)
}


class PythonInterface:
    def XPluginStart(self):
        self.ok = hasattr(xp, "WindowContentTypeBrowser") and hasattr(xp, "windowSetURL")
        self.cmd_queue = []
        self.window = None
        self.url = ""
        self.loads, self.errors, self.cmd_log = [], [], []
        self.main_ident = None
        self.ping_threads = {}
        self.pings = 0
        self.ping_us_sum = 0.0
        self.ping_us_max = 0.0
        self.reports = []  # queued by the callback, written by the loop
        self.report_count = 0
        self.last_report = None
        self.last_report_t = None
        self.settings = {"rate": 5, "pan": False, "push": False, "focus": "none"}
        self.focus_seen = 0      # loop ticks that found the window holding the keyboard
        self.focus_released = 0  # takeKeyboardFocus(0) calls made
        self.pushes = 0
        self.push_us_sum = 0.0
        self.next_state = 0.0
        self.created_at = None
        folder = os.path.join(xp.getSystemPath(), "Output", "xp-gliding", "computerlab")
        os.makedirs(folder, exist_ok=True)
        self.state_path = os.path.join(folder, "state.json")
        self.events_path = os.path.join(folder, "events.jsonl")
        self.page_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), PAGE_FOLDER)
        self.refs = [xp.registerDataAccessor("xp_gliding/computerlab/cmd", xp.Type_Int, 1,
                                             readInt=lambda _: 0,
                                             writeInt=lambda _, v: self.cmd_queue.append(int(v)))]
        self.loop = xp.createFlightLoop(self.on_loop, xp.FlightLoop_Phase_AfterFlightModel, None)
        xp.log("[computerlab] browser windows " + ("available" if self.ok else
               "NOT available (needs XPPython3 4.8.0 on X-Plane 12.4.4): the lab does nothing"))
        return "xp-gliding computer lab", "jlgabriel.xp_gliding.computerlab", "Browser window checks."

    def XPluginEnable(self):
        xp.scheduleFlightLoop(self.loop, LOOP_PERIOD_S, 1)
        self.event({"kind": "plugin", "what": "enable"})
        return 1

    def XPluginDisable(self):
        xp.scheduleFlightLoop(self.loop, 0, 1)
        self.event({"kind": "plugin", "what": "disable", "window": self.window is not None})
        self.destroy()
        self.write_state()

    def XPluginStop(self):
        xp.destroyFlightLoop(self.loop)
        for ref in self.refs:
            xp.unregisterDataAccessor(ref)

    def XPluginReceiveMessage(self, inFromWho, inMessage, inParam):
        pass

    # --- window -------------------------------------------------------------

    def page_url(self, mode):
        index = os.path.join(self.page_dir, "index.html")
        if mode == "raw":
            root = f"{xp.getSystemPath()}Resources/plugins/PythonPlugins/{PAGE_FOLDER}"
            return f"file://{root}/index.html"
        return pathlib.Path(index).as_uri()

    def create(self, mode):
        if not self.ok or self.window is not None:
            return
        left, top, right, bottom = xp.getScreenBoundsGlobal()
        x, y = left + 120, top - 160
        self.window = xp.createWindowEx(
            x, y, x + SIZE[0], y - SIZE[1], visible=1,
            decoration=xp.WindowDecorationRoundRectangle, layer=xp.WindowLayerFloatingWindows,
            contentType=xp.WindowContentTypeBrowser,
            browserLoadFinished=self.on_load, browserLoadError=self.on_error)
        xp.setWindowTitle(self.window, "XP-Gliding computer lab")
        xp.setWindowResizingLimits(self.window, 320, 240, 1400, 1000)
        xp.windowAddBrowserFunction(self.window, "lab_ping", self.on_ping)
        xp.windowAddBrowserFunction(self.window, "lab_report", self.on_report)
        self.url = self.page_url(mode)
        self.created_at = xp.getElapsedTime()
        xp.windowSetURL(self.window, self.url)

    def destroy(self):
        if self.window is not None:
            xp.destroyWindow(self.window)
            self.window = None

    def set_size(self, w, h):
        left, top, _, _ = xp.getWindowGeometry(self.window)
        xp.setWindowGeometry(self.window, left, top, left + w, top - h)

    # --- callbacks from CEF ---------------------------------------------------

    def on_load(self, window_id, url, ref):
        self.loads.append([round(xp.getElapsedTime(), 3), url])
        self.event({"kind": "load", "url": url})

    def on_error(self, window_id, url, error, ref):
        self.errors.append([round(xp.getElapsedTime(), 3), url, error])
        self.event({"kind": "load_error", "url": url, "error": error})

    def on_ping(self, window_id, json_str, ref):
        t0 = time.perf_counter()
        try:
            ident = threading.get_ident()
            self.ping_threads[ident] = self.ping_threads.get(ident, 0) + 1
            seq = json.loads(json_str)
            out = json.dumps({"seq": seq, "rate": self.settings["rate"], "pan": self.settings["pan"],
                              "blur": self.settings["focus"] == "blur"})
        except Exception:
            out = '{"error": "lab_ping failed"}'
        us = (time.perf_counter() - t0) * 1e6
        self.pings += 1
        self.ping_us_sum += us
        self.ping_us_max = max(self.ping_us_max, us)
        return out

    def on_report(self, window_id, json_str, ref):
        try:
            self.reports.append(json_str)
        except Exception:
            pass
        return '{"ok": true}'

    # --- flight loop: commands, push, state ---------------------------------------

    def on_loop(self, since, elapsed, counter, ref):
        try:
            self.main_ident = threading.get_ident()
            while self.cmd_queue:
                self.run(self.cmd_queue.pop(0))
            if self.window is not None and xp.hasKeyboardFocus(self.window):
                self.focus_seen += 1
                if self.settings["focus"] == "release":
                    xp.takeKeyboardFocus(0)
                    self.focus_released += 1
            if self.settings["push"] and self.window is not None and self.loads:
                t0 = time.perf_counter()
                xp.windowInjectScript(self.window, "xpgLab.onPush(%d)" % self.pushes)
                self.push_us_sum += (time.perf_counter() - t0) * 1e6
                self.pushes += 1
            while self.reports:
                raw = self.reports.pop(0)
                report = json.loads(raw)
                self.report_count += 1
                self.last_report = report
                self.last_report_t = round(xp.getElapsedTime(), 3)
                self.event({"kind": "report", "report": report})
            now = xp.getElapsedTime()
            if now >= self.next_state:
                self.next_state = now + STATE_PERIOD_S
                self.write_state()
        except Exception:
            xp.log("[computerlab] loop error\n" + traceback.format_exc())
        return LOOP_PERIOD_S

    def run(self, code):
        name = CMDS.get(code, "unknown")
        self.cmd_log.append([round(xp.getElapsedTime(), 3), name])
        self.event({"kind": "cmd", "cmd": name})
        if name in ("create_raw", "create_uri"):
            self.create(name[7:])
        elif name == "destroy":
            self.destroy()
        elif self.window is None and name in ("show", "hide", "big", "small", "popout", "float",
                                              "refresh", "late_function"):
            self.event({"kind": "cmd_skipped", "cmd": name, "why": "no window"})
        elif name == "show":
            xp.setWindowIsVisible(self.window, 1)
        elif name == "hide":
            xp.setWindowIsVisible(self.window, 0)
        elif name == "big":
            self.set_size(1000, 700)
        elif name == "small":
            self.set_size(*SIZE)
        elif name == "popout":
            xp.setWindowPositioningMode(self.window, xp.WindowPopOut, -1)
        elif name == "float":
            xp.setWindowPositioningMode(self.window, xp.WindowPositionFree, -1)
        elif name == "refresh":
            xp.windowRefresh(self.window, 0)
        elif name.startswith("rate"):
            self.settings["rate"] = int(name[4:])
        elif name in ("pan_on", "pan_off"):
            self.settings["pan"] = name == "pan_on"
        elif name in ("push_on", "push_off"):
            self.settings["push"] = name == "push_on"
        elif name == "kb_zero":
            xp.takeKeyboardFocus(0)
        elif name == "kb_cycle":
            xp.takeKeyboardFocus(self.window)
            self.event({"kind": "kb", "window_after_take": xp.hasKeyboardFocus(self.window)})
            xp.takeKeyboardFocus(0)
        elif name.startswith("focus_"):
            self.settings["focus"] = name[6:]
        elif name == "late_function":
            xp.windowAddBrowserFunction(self.window, "lab_late", lambda w, j, r: '"late"')

    # --- output ---------------------------------------------------------------

    def event(self, obj):
        obj["t"] = round(xp.getElapsedTime(), 3)
        with open(self.events_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj) + "\n")

    def write_state(self):
        w = self.window
        state = {
            "t": round(xp.getElapsedTime(), 3),
            "ok": self.ok,
            "main_ident": self.main_ident,
            "window": w is not None,
            "url": self.url,
            "created_at": self.created_at,
            "screen_bounds": list(xp.getScreenBoundsGlobal()),
            "loads": self.loads[-10:],
            "errors": self.errors[-10:],
            "cmds": self.cmd_log[-20:],
            "settings": self.settings,
            "pings": self.pings,
            "ping_threads": {str(k): v for k, v in self.ping_threads.items()},
            "ping_us_mean": self.ping_us_sum / self.pings if self.pings else None,
            "ping_us_max": self.ping_us_max,
            "pushes": self.pushes,
            "push_us_mean": self.push_us_sum / self.pushes if self.pushes else None,
            "reports": self.report_count,
            "focus_seen": self.focus_seen,
            "focus_released": self.focus_released,
            "kb_xplane": xp.hasKeyboardFocus(0),
            "last_report_t": self.last_report_t,
            "last_report": self.last_report,
        }
        if w is not None:
            state["visible"] = xp.getWindowIsVisible(w)
            state["kb_window"] = xp.hasKeyboardFocus(w)
            state["popped_out"] = xp.windowIsPoppedOut(w)
            state["geometry"] = list(xp.getWindowGeometry(w))
            if state["popped_out"]:
                state["geometry_os"] = list(xp.getWindowGeometryOS(w))
        tmp = self.state_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=1)
        os.replace(tmp, self.state_path)
