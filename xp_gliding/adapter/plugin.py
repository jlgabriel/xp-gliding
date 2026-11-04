"""The XPPython3 plugin: flight loop, menu, commands and xp-gliding's own datarefs.

`PI_xp_gliding.py` (installed next to the `xp_gliding` package in
`Resources/plugins/PythonPlugins/`) only re-exports `PythonInterface` from here.

One flight loop runs every frame, before the flight model. While the plugin is
active (enabled, and the user's aircraft is a glider unless `gliders_only` is
off) and the sim is neither paused nor in replay, it reads the aircraft state,
asks the engine for the lift, and adds the forces (see `core` and `xpio`).
About once a second it keeps the thermal field loaded around the aircraft and
re-checks the native thermal setting, and, half a second apart so that the two
never share a frame, updates the training markers if they are on (`markers`).
The soaring HUD runs apart from all this, with its own flight loop (`hud`).

Commands (also in the Plugins > xp-gliding menu):
  xp_gliding/toggle            plugin effect on / off
  xp_gliding/thermals/toggle   our thermals on / off, the plugin stays loaded (issue #30)
  xp_gliding/markers/toggle    training markers on / off (off by default)
  xp_gliding/hud/toggle        soaring HUD on / off

Datarefs (`xp_gliding/...`, see DATAREFS): settings and debug modes are
writable, so the flight logger and the test pilot can read what the adapter
applied and drive the measurements from outside. A plugin reading the
`*_plug_acf` datarefs after the flight model sees 0 (X-Plane clears them), so
these are the way to observe the force.
"""

import math
import os
import time
import traceback

import xp

from .. import __version__
from .aircraft import DEFAULT_GEOMETRY, read_acf_geometry
from .config import load_settings
from .core import AircraftState, Injection, Injector, NativeThermalGuard
from .hud import Hud
from .markers import TrainingMarkers
from .xpio import SkyObjects, XPlaneIO

SLOW_PERIOD_S = 1.0
TAG = "[xp-gliding]"

# (name under xp_gliding/, holder, attribute, type, writable). holder names an
# attribute of the plugin object; the attribute may be dotted.
DATAREFS = (
    ("enabled", "settings", "enabled", "i", 1),
    ("thermals_enabled", "settings", "thermals_enabled", "i", 1),
    ("roll_enabled", "settings", "roll_enabled", "i", 1),
    ("helix_enabled", "settings", "helix_enabled", "i", 1),
    ("markers_enabled", "settings", "markers_enabled", "i", 1),
    ("hud_enabled", "settings", "hud_enabled", "i", 1),
    ("hud/te_ms", "hud", "vario.te_ms", "f", 0),
    ("hud/netto_ms", "hud", "vario.netto_ms", "f", 0),
    ("hud/average_ms", "hud", "vario.average_ms", "f", 0),
    ("hud/aid_valid", "hud", "aid.valid", "i", 0),
    ("hud/aid_core_az_deg", "hud", "aid.core_az_deg", "f", 0),
    ("hud/aid_amp_ms", "hud", "aid.amp_ms", "f", 0),
    ("hud/sample_us", "hud", "sample_us", "f", 0),
    ("hud/draw_us", "hud", "draw_us", "f", 0),
    ("seed", "settings", "seed", "i", 1),
    ("wstar_ms", "settings", "wstar_ms", "f", 1),
    ("zi_m", "settings", "zi_m", "f", 1),
    ("debug/uniform_ms", "injector", "uniform_ms", "f", 1),
    ("debug/dw_dy", "injector", "debug_dwdy", "f", 1),
    ("active", "status", "active", "i", 0),
    ("frame_us", "status", "frame_us", "f", 0),
    ("lift_ms", "out", "w_span", "f", 0),
    ("lift_centre_ms", "out", "w_centre", "f", 0),
    ("lift_left_ms", "out", "w_left", "f", 0),
    ("lift_right_ms", "out", "w_right", "f", 0),
    ("lift_tail_ms", "out", "w_tail", "f", 0),
    ("dw_dy", "out", "dw_dy", "f", 0),
    ("dw_dy_helix", "out", "dw_dy_helix", "f", 0),
    ("force_n", "out", "force_n", "f", 0),
    ("roll_nm", "out", "roll_nm", "f", 0),
    ("nearest/distance_m", "injector", "nearest.distance_m", "f", 0),
    ("nearest/bearing_deg", "injector", "nearest.bearing_deg", "f", 0),
    ("nearest/core_ms", "injector", "nearest.core_ms", "f", 0),
    ("thermals_alive", "injector", "nearest.alive", "i", 0),
    ("native_saved_ms", "guard", "saved", "f", 0),
    ("span_m", "injector", "geometry.span_m", "f", 0),
    ("area_m2", "injector", "geometry.area_m2", "f", 0),
    ("markers/light", "markers", "status.light", "f", 1),
    ("markers/count", "markers", "status.count", "i", 0),
    ("markers/created", "markers", "status.created", "i", 0),
    ("markers/destroyed", "markers", "status.destroyed", "i", 0),
    ("markers/swapped", "markers", "status.swapped", "i", 0),
    ("markers/update_us", "markers", "status.update_us", "f", 0),
    ("markers/update_us_max", "markers", "status.update_us_max", "f", 0),
    ("markers/select_us", "markers", "status.select_us", "f", 0),
    ("markers/probe_distance_m", "markers", "status.probe_distance_m", "f", 0),
    ("markers/probe_local_distance_m", "markers", "status.probe_local_distance_m", "f", 0),
    ("markers/probe_dy_m", "markers", "status.probe_dy_m", "f", 0),
    ("markers/probe_core_ms", "markers", "status.probe_core_ms", "f", 0),
    ("markers/probe_r1_m", "markers", "status.probe_r1_m", "f", 0),
    ("markers/probe_size_m", "markers", "status.probe_size_m", "f", 0),
    ("markers/probe_strength", "markers", "status.probe_strength", "i", 0),
)


class Status:
    __slots__ = ("active", "frame_us")

    def __init__(self):
        self.active = 0
        self.frame_us = 0.0


def _resolve(refcon):
    obj, path = refcon
    *parents, attr = path.split(".")
    for name in parents:
        obj = getattr(obj, name)
    return obj, attr


def _read_int(refcon):
    obj, attr = _resolve(refcon)
    return int(getattr(obj, attr))


def _write_int(refcon, value):
    obj, attr = _resolve(refcon)
    old = getattr(obj, attr)
    setattr(obj, attr, bool(value) if isinstance(old, bool) else int(value))


def _read_float(refcon):
    obj, attr = _resolve(refcon)
    return float(getattr(obj, attr))


def _write_float(refcon, value):
    obj, attr = _resolve(refcon)
    value = float(value)
    if math.isfinite(value):
        setattr(obj, attr, value)


class PythonInterface:
    def XPluginStart(self):
        self.Name = "xp-gliding"
        self.Sig = "jlgabriel.xp_gliding"
        self.Desc = "Soaring layer for X-Plane 12: thermals as energy-based forces."

        folder = os.path.join(xp.getSystemPath(), "Output", "xp-gliding")
        os.makedirs(folder, exist_ok=True)
        self.settings, how = load_settings(os.path.join(folder, "config.json"))
        print(f"{TAG} {__version__} starting; settings {how}")

        self.io = XPlaneIO()
        self.injector = Injector(self.settings, DEFAULT_GEOMETRY)
        self.guard = NativeThermalGuard(self.io.read_native_thermals,
                                        self.io.write_native_thermals)
        self.state = AircraftState()
        self.out = Injection()
        self.status = Status()
        self.markers = TrainingMarkers(SkyObjects(), lambda text: print(f"{TAG} {text}"))
        self.hud = Hud(self.settings, lambda text: print(f"{TAG} {text}"))
        self.eligible = False
        self.failed = False
        self.next_slow = 0.0
        self.next_markers = 0.0

        self.datarefs = []
        for name, holder, attr, kind, writable in DATAREFS:
            refcon = (getattr(self, holder), attr)
            if kind == "i":
                ref = xp.registerDataAccessor(
                    "xp_gliding/" + name, xp.Type_Int, writable, readInt=_read_int,
                    writeInt=_write_int if writable else None,
                    readRefCon=refcon, writeRefCon=refcon)
            else:
                ref = xp.registerDataAccessor(
                    "xp_gliding/" + name, xp.Type_Float, writable, readFloat=_read_float,
                    writeFloat=_write_float if writable else None,
                    readRefCon=refcon, writeRefCon=refcon)
            self.datarefs.append(ref)

        self.commands = (
            (xp.createCommand("xp_gliding/toggle", "xp-gliding: plugin effect on/off"),
             self.on_toggle, "enabled", "Enabled"),
            (xp.createCommand("xp_gliding/thermals/toggle", "xp-gliding: thermals on/off"),
             self.on_toggle, "thermals_enabled", "Thermals"),
            (xp.createCommand("xp_gliding/markers/toggle", "xp-gliding: training markers on/off"),
             self.on_toggle, "markers_enabled", "Training markers"),
            (xp.createCommand("xp_gliding/hud/toggle", "xp-gliding: soaring HUD on/off"),
             self.on_toggle, "hud_enabled", "Soaring HUD"),
        )
        self.menu_item = xp.appendMenuItem(xp.findPluginsMenu(), "xp-gliding", 0)
        self.menu = xp.createMenu("xp-gliding", xp.findPluginsMenu(), self.menu_item, None, None)
        for cmd, handler, attr, label in self.commands:
            xp.registerCommandHandler(cmd, handler, 1, attr)
            xp.appendMenuItemWithCommand(self.menu, label, cmd)
        self.refresh_menu()

        self.loop = xp.createFlightLoop(self.flight_loop, xp.FlightLoop_Phase_BeforeFlightModel, None)
        return self.Name, self.Sig, self.Desc

    def XPluginStop(self):
        xp.destroyFlightLoop(self.loop)
        self.hud.stop()
        for cmd, handler, attr, _ in self.commands:
            xp.unregisterCommandHandler(cmd, handler, 1, attr)
        xp.destroyMenu(self.menu)
        xp.removeMenuItem(xp.findPluginsMenu(), self.menu_item)
        for ref in self.datarefs:
            xp.unregisterDataAccessor(ref)

    def XPluginEnable(self):
        self.load_aircraft()
        xp.scheduleFlightLoop(self.loop, -1, 1)
        self.hud.enable()
        return 1

    def XPluginDisable(self):
        xp.scheduleFlightLoop(self.loop, 0, 1)
        self.guard.release()
        self.markers.shutdown()
        self.hud.disable()
        self.status.active = 0
        self.out.clear()

    def XPluginReceiveMessage(self, inFromWho, inMessage, inParam):
        if inMessage == xp.MSG_PLANE_LOADED and inParam == 0:
            self.load_aircraft()

    # --- aircraft -----------------------------------------------------------

    def load_aircraft(self):
        path = self.io.user_aircraft_path()
        geometry = read_acf_geometry(path) if path else None
        self.injector.set_geometry(geometry or DEFAULT_GEOMETRY)
        engines = self.io.engine_count()
        # At the main menu the "aircraft" is X-Plane's own folder: stay inert until
        # a real aircraft is loaded (a plane-loaded message follows).
        loaded = path.lower().endswith(".acf")
        self.eligible = loaded and (engines == 0 or not self.settings.gliders_only)
        self.hud.set_aircraft(path, self.eligible)
        print(f"{TAG} aircraft {path or '(none)'}: {engines} engines, "
              f"{'eligible' if self.eligible else 'not a glider, inactive'}; "
              f"{self.injector.geometry}")

    # --- commands and menu ----------------------------------------------------

    def on_toggle(self, commandRef, phase, attr):
        if phase == xp.CommandBegin:
            setattr(self.settings, attr, not getattr(self.settings, attr))
            self.refresh_menu()
            print(f"{TAG} {attr} = {getattr(self.settings, attr)}")
        return 1

    def refresh_menu(self):
        for index, (_, _, attr, _) in enumerate(self.commands):
            check = xp.Menu_Checked if getattr(self.settings, attr) else xp.Menu_Unchecked
            xp.checkMenuItem(self.menu, index, check)

    # --- per frame -------------------------------------------------------------

    def flight_loop(self, sinceLast, elapsedTime, counter, refCon):
        try:
            return self.step()
        except Exception:
            # Never leave a half-working force behind, and never log every frame.
            print(f"{TAG} error in the flight loop; plugin effect stopped:\n"
                  + traceback.format_exc())
            self.failed = True
            self.status.active = 0
            self.out.clear()
            self.guard.release()
            self.markers.clear()
            return 0

    def step(self):
        st = self.settings
        now = time.monotonic()
        active = st.enabled and self.eligible
        self.guard.want(active and st.thermals_enabled, now)
        markers = active and st.thermals_enabled and st.markers_enabled
        if not markers and self.markers.shown:
            self.markers.clear()
        if not active or self.io.frozen():
            self.status.active = 0
            self.out.clear()
            return -1
        t0 = time.perf_counter()
        s = self.io.read_state(self.state)
        if now >= self.next_slow:
            self.next_slow = now + SLOW_PERIOD_S
            self.next_markers = now + 0.5 * SLOW_PERIOD_S
            self.injector.slow_update(s)
            self.refresh_menu()
        elif markers and now >= self.next_markers and self.injector.field is not None:
            self.next_markers = now + SLOW_PERIOD_S
            self.markers.update(self.injector.field, self.injector.frame, s, self.io.elevation_m(),
                                self.io.local_position(), st.wstar_ms, st.zi_m, now)
        self.injector.step(s, self.out)
        self.io.apply(self.out)
        self.status.active = 1
        us = (time.perf_counter() - t0) * 1e6
        self.status.frame_us += 0.02 * (us - self.status.frame_us)
        return -1
