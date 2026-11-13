"""The XPPython3 plugin: flight loop, menu, commands and XP-Gliding's own datarefs.

`PI_xp_gliding.py` (installed next to the `xp_gliding` package in
`Resources/plugins/PythonPlugins/`) only re-exports `PythonInterface` from here.

One flight loop runs every frame, before the flight model. While the plugin is
active (enabled, and the user's aircraft is a glider unless `gliders_only` is
off: filed as a glider, with no engines, or treated as one from the menu, which is how a
motor glider gets in) and the sim is neither paused nor in replay, it reads the aircraft state,
asks the engine for the lift, and adds the forces (see `core` and `xpio`).
About once a second it keeps the thermal field loaded around the aircraft and
re-checks the native thermal setting, and, in frames apart so that they never share
one, updates the cumulus (`clouds`) and the training markers if they are on (`markers`).
The soaring HUD runs apart from all this, with its own flight loop (`hud`).

An error in the flight loop stops the plugin's effect: no force, the native thermals back, no
clouds or markers, and the traceback in XPPython3Log.txt. The menu's first item then says so,
and the loop starts again from a clean state with a new flight or aircraft, or when the pilot
unticks and ticks Enabled, up to MAX_RESTARTS times; after that only re-enabling the plugin does.

The Plugins > XP-Gliding menu has the switches below, and submenus to choose the sky, the
day, by name (`config.DAYS`) or one setting at a time, and the HUD's units (`config.MENU_CHOICES`). What is chosen there is saved to `config.json`. Its last item,
greyed out, says what the plugin is doing and, when there are no thermals, why (`status_line`).

Commands (also in the menu):
  xp_gliding/toggle            plugin effect on / off
  xp_gliding/thermals/toggle   our thermals on / off, the plugin stays loaded (issue #30)
  xp_gliding/edge/toggle       sharper thermal edges: a kick on entry and exit, a sink ring and
                               more sink between thermals (on by default since 0.9.1)
  xp_gliding/wind/toggle       XP12's wind carries the thermals, or they stay where they are
  xp_gliding/lean/toggle       thermals lean with the wind (off by default, a first guess)
  xp_gliding/wind/clouds/toggle  the sky moves with the wind at the clouds, not at the glider
                               (off by default, to compare in shear)
  xp_gliding/markers/toggle    training markers on / off (off by default)
  xp_gliding/clouds/toggle     cumulus on / off
  xp_gliding/hud/toggle        soaring HUD on / off
  xp_gliding/day/weather/toggle  zi from the cloud base in X-Plane's weather, not the menu's
                               (off by default; greys out the zi submenu)
  xp_gliding/audio_vario/toggle  X-Plane's own audio vario on / off, for gliders with no switch
                               for it on the panel; X-Plane's setting, not saved by the plugin
  xp_gliding/aircraft/glider/toggle  treat this aircraft as a glider, for a motor glider; saved
                               by its .acf name in `also_gliders`
  xp_gliding/airstart/near_cloud  put the glider in the air near a cloud worth flying to
                               (`engine/airstart.py`)

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
from .config import DAYS, MENU_CHOICES, day_index, load_settings, save_settings
from .core import AircraftState, Injection, Injector, NativeThermalGuard
from ..engine.airstart import SPEED_MS, clouds_from, pick_cloud, place_near, start_height_m
from ..engine.sun import SUN_MIN_DEG
from ..engine.shade import RAIN_OFF
from .clouds import CumulusClouds
from .hud import Hud
from .markers import TrainingMarkers
from .xpio import SkyObjects, XPlaneIO

SLOW_PERIOD_S = 1.0
LEAN_PERIOD_S = 5.0  # X-Plane's layers of wind are read this often
CLOUDS_PERIOD_S = 0.25  # cloud tiles load in small bites
TAG = "[xp-gliding]"
MAX_RESTARTS = 3  # errors in the flight loop after which it is not started again
PLACED_GRACE_S = 15.0  # after putting the glider near a cloud, a new flight's message keeps the sky
ENABLED_LABEL = "Enabled"
AUDIO_LABEL = "X-Plane's audio vario"
# Said when a day is chosen while the cloud base comes from X-Plane's weather, which sets its zi.
DAY_WEATHER_NOTE = ("the cloud base comes from X-Plane's weather, so the day's height is not used; "
                    "untick that to fly it")
FAILED_LABEL = "Enabled: stopped by an error, see XPPython3Log.txt"

# (name under xp_gliding/, holder, attribute, type, writable). holder names an
# attribute of the plugin object; the attribute may be dotted.
DATAREFS = (
    ("enabled", "settings", "enabled", "i", 1),
    ("thermals_enabled", "settings", "thermals_enabled", "i", 1),
    ("edge_enabled", "settings", "edge_enabled", "i", 1),
    ("wind_enabled", "settings", "wind_enabled", "i", 1),
    ("wind_at_clouds", "settings", "wind_at_clouds", "i", 1),
    ("sun_enabled", "settings", "sun_enabled", "i", 1),
    ("sun/elevation_deg", "injector", "sun_elevation_deg", "f", 0),  # ours, against sun_pitch_degrees
    ("sun/share", "injector", "sun_share", "f", 0),  # of a full day's thermals, alive now
    ("day/wstar_ms", "injector", "wstar_ms", "f", 0),  # in use: the menu's times the daily cycle
    ("day/strength_share", "injector", "day_share", "f", 0),  # the daily cycle's share of the peak
    ("day/depth_share", "injector", "depth_share", "f", 0),  # zi now over the afternoon's, at the glider
    ("day/zi_now_m", "injector", "zi_now_m", "f", 0),  # day/zi_m times day/depth_share
    # Good and bad areas (engine/areas.py): on or off, and at the glider the area's quality and the
    # thermals' number and strength there, times the sky's.
    ("areas_enabled", "settings", "areas_enabled", "i", 1),
    ("day/area_quality", "injector", "area_quality", "f", 0),
    ("day/area_density", "injector", "area_density", "f", 0),
    ("day/area_strength", "injector", "area_strength", "f", 0),
    ("wind/e_ms", "injector", "drift.wind_e_ms", "f", 0),  # the wind that carries the sky
    ("wind/n_ms", "injector", "drift.wind_n_ms", "f", 0),
    ("wind/dlat_deg", "injector", "drift.dlat_deg", "f", 0),  # the sky's offset from the ground
    ("wind/dlon_deg", "injector", "drift.dlon_deg", "f", 0),
    ("lean_enabled", "settings", "lean_enabled", "i", 1),
    ("lean/e_m", "injector", "lean_e_m", "f", 0),  # the lift's centre at the glider, from its cloud
    ("lean/n_m", "injector", "lean_n_m", "f", 0),
    ("roll_enabled", "settings", "roll_enabled", "i", 1),
    ("helix_enabled", "settings", "helix_enabled", "i", 1),
    ("markers_enabled", "settings", "markers_enabled", "i", 1),
    ("clouds_enabled", "settings", "clouds_enabled", "i", 1),
    ("blue_day", "settings", "blue_day", "i", 1),
    ("clouds/rate", "clouds", "status.rate_dummy", "f", 0),
    ("clouds/scale", "clouds", "status.scale_dummy", "f", 0),
    ("clouds/count", "clouds", "status.count", "i", 0),
    ("clouds/created", "clouds", "status.created", "i", 0),
    ("clouds/destroyed", "clouds", "status.destroyed", "i", 0),
    ("clouds/rate_changes", "clouds", "status.rate_changes", "i", 0),
    ("clouds/moved", "clouds", "status.moved", "i", 0),
    ("clouds/handed_over", "clouds", "status.handed_over", "i", 0),
    ("clouds/refilled", "clouds", "status.refilled", "i", 0),
    ("clouds/cooling", "clouds", "status.cooling", "i", 0),
    ("clouds/pool_idle", "clouds", "status.pool_idle", "i", 0),
    ("clouds/pool_misses", "clouds", "status.pool_misses", "i", 0),
    ("clouds/order_us", "clouds", "status.order_us", "f", 0),
    ("clouds/tiles_missing", "clouds", "status.tiles_missing", "i", 0),
    ("clouds/update_us", "clouds", "status.update_us", "f", 0),
    ("clouds/update_us_max", "clouds", "status.update_us_max", "f", 0),
    ("clouds/plan_us", "clouds", "status.plan_us", "f", 0),
    ("clouds/nearest_m", "clouds", "status.nearest_m", "f", 0),
    ("clouds/nearest_base_m", "clouds", "status.nearest_base_m", "f", 0),
    ("clouds/nearest_scale", "clouds", "status.nearest_scale", "f", 0),
    ("clouds/level_m", "clouds", "status.level_m", "f", 0),
    ("clouds/raised", "clouds", "status.raised", "i", 0),
    ("clouds/base_max_m", "clouds", "status.base_max_m", "f", 0),
    ("clouds/ground_misses", "clouds", "heights.misses", "i", 0),
    ("clouds/base_us", "clouds", "heights.base_us", "f", 0),
    ("clouds/base_us_max", "clouds", "heights.base_us_max", "f", 0),
    ("hud_enabled", "settings", "hud_enabled", "i", 1),
    ("hud/te_ms", "hud", "vario.te_ms", "f", 0),
    ("hud/netto_ms", "hud", "vario.netto_ms", "f", 0),
    ("hud/average_ms", "hud", "vario.average_ms", "f", 0),
    ("hud/thermal_ms", "hud", "thermal.average_ms", "f", 0),  # since circling began (THM)
    ("hud/aid_valid", "hud", "aid.valid", "i", 0),
    ("hud/aid_core_az_deg", "hud", "aid.core_az_deg", "f", 0),
    ("hud/aid_amp_ms", "hud", "aid.amp_ms", "f", 0),
    ("hud/sample_us", "hud", "sample_us", "f", 0),
    ("hud/draw_us", "hud", "draw_us", "f", 0),
    ("seed", "settings", "seed", "i", 1),
    ("wstar_ms", "settings", "wstar_ms", "f", 1),
    ("zi_m", "settings", "zi_m", "f", 1),  # the setting; day/zi_m is the one in use
    ("weather_base_enabled", "settings", "weather_base_enabled", "i", 1),
    ("day/zi_m", "injector", "zi_m", "f", 0),
    # Less lift under X-Plane's clouds, none in rain (engine/shade.py): the share of w* left now,
    # the share it is heading for, the sun the layers stop, and the rain.
    ("day/shade_share", "injector", "shade.share", "f", 0),
    ("day/shade_target", "injector", "shade.target", "f", 0),
    ("day/sky_cover", "injector", "sky_cover", "f", 0),
    ("day/rain", "injector", "rain", "f", 0),  # the afternoon's: the field's, maybe the weather's
    ("day/weather_base_m", "injector", "weather.published_m", "f", 0),  # m above the ground, -1: none
    ("day/weather_reads", "injector", "weather.reads", "i", 0),
    # The place of the sky in engine.field.SKY_NAMES. Tools can write it; that is not saved.
    ("sky_index", "injector", "sky_index", "i", 1),
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
    ("kick_n", "out", "kick_n", "f", 0),  # the kick's lift (sharper edges), before its split
    ("turbulence_ms", "injector", "turb_ms", "f", 0),  # the edge's bumps, their amplitude
    ("roll_nm", "out", "roll_nm", "f", 0),
    ("water/checked", "injector", "water_checked", "i", 0),
    ("water/rejected", "injector", "water_rejected", "i", 0),
    ("nearest/distance_m", "injector", "nearest.distance_m", "f", 0),
    ("nearest/bearing_deg", "injector", "nearest.bearing_deg", "f", 0),
    ("nearest/core_ms", "injector", "nearest.core_ms", "f", 0),
    ("nearest/floor_m", "injector", "nearest.floor_m", "f", 0),
    ("nearest/depth", "injector", "nearest.depth", "f", 0),  # its zi over the afternoon's; 0: none
    ("floors_us", "injector", "floors_us", "f", 0),
    ("floors_us_max", "injector", "floors_us_max", "f", 0),
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
        self.Name = "XP-Gliding"
        self.Sig = "jlgabriel.xp_gliding"
        self.Desc = "Soaring layer for X-Plane 12: thermals as energy-based forces."

        folder = os.path.join(xp.getSystemPath(), "Output", "xp-gliding")
        os.makedirs(folder, exist_ok=True)
        self.config_path = os.path.join(folder, "config.json")
        self.settings, how = load_settings(self.config_path)
        print(f"{TAG} {__version__} starting; settings {how}")

        self.io = XPlaneIO()
        self.injector = Injector(self.settings, DEFAULT_GEOMETRY)
        self.guard = NativeThermalGuard(self.io.read_native_thermals,
                                        self.io.write_native_thermals)
        self.state = AircraftState()
        self.out = Injection()
        self.status = Status()
        self.markers = TrainingMarkers(SkyObjects(), lambda text: print(f"{TAG} {text}"))
        self.clouds = CumulusClouds(SkyObjects("clouds"), lambda text: print(f"{TAG} {text}"))
        self.injector.is_wet = self.clouds.sky.is_wet  # one probe for both
        self.injector.heights = self.clouds.heights
        self.hud = Hud(self.settings, lambda text: print(f"{TAG} {text}"))
        self.eligible = False
        self.acf_path = ""
        self.acf = ""  # the user's aircraft file name, "" when none is loaded
        self.native_glider = False  # a glider without the pilot saying so: filed as one, or no engines
        self.failed = False  # the flight loop stopped on an error
        self.failures = 0  # errors in the flight loop since the plugin was enabled
        self.placed_at = None  # when the glider was last put near a cloud (time.monotonic)
        self.next_slow = 0.0
        self.next_markers = 0.0
        self.next_clouds = 0.0
        self.next_lean = 0.0
        self.sky_zi_m = None  # the zi the clouds were made for: a new one starts them over
        self.status_item = None  # the menu's last line, greyed out: what the plugin is doing
        self.status_text = None
        self._menu_state = None  # what the menu's ticks show, so they are set only when it changes

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
            (xp.createCommand("xp_gliding/toggle", "XP-Gliding: plugin effect on/off"),
             self.on_toggle, "enabled", ENABLED_LABEL),
            (xp.createCommand("xp_gliding/thermals/toggle", "XP-Gliding: thermals on/off"),
             self.on_toggle, "thermals_enabled", "Thermals"),
            (xp.createCommand("xp_gliding/edge/toggle",
                              "XP-Gliding: sharper thermal edges on/off (a kick, a sink ring, more sink)"),
             self.on_toggle, "edge_enabled", "Sharper thermal edges (experiment)"),
            (xp.createCommand("xp_gliding/day/cycle/toggle",
                              "XP-Gliding: daily cycle on/off (off: the same strength all day, sun or not)"),
             self.on_toggle, "sun_enabled", "Daily cycle"),
            (xp.createCommand("xp_gliding/day/areas/toggle",
                              "XP-Gliding: good and bad areas on/off (off: the same sky everywhere)"),
             self.on_toggle, "areas_enabled", "Good and bad areas"),
            (xp.createCommand("xp_gliding/wind/toggle", "XP-Gliding: thermals follow the wind on/off"),
             self.on_toggle, "wind_enabled", "Thermals follow the wind"),
            (xp.createCommand("xp_gliding/lean/toggle", "XP-Gliding: thermals lean with the wind on/off"),
             self.on_toggle, "lean_enabled", "Thermals lean with the wind (experiment)"),
            (xp.createCommand("xp_gliding/wind/clouds/toggle",
                              "XP-Gliding: the sky moves with the wind at the clouds, not at the glider"),
             self.on_toggle, "wind_at_clouds", "Sky moves with the wind at the clouds (experiment)"),
            (xp.createCommand("xp_gliding/markers/toggle", "XP-Gliding: training markers on/off"),
             self.on_toggle, "markers_enabled", "Training markers"),
            (xp.createCommand("xp_gliding/clouds/toggle", "XP-Gliding: cumulus on/off"),
             self.on_toggle, "clouds_enabled", "Cumulus clouds"),
            (xp.createCommand("xp_gliding/hud/toggle", "XP-Gliding: soaring HUD on/off"),
             self.on_toggle, "hud_enabled", "Soaring HUD"),
            (xp.createCommand("xp_gliding/day/weather/toggle",
                              "XP-Gliding: cloud base from X-Plane's weather, not the menu's zi"),
             self.on_toggle, "weather_base_enabled", "Cloud base from X-Plane's weather (experiment)"),
        )
        self.menu_item = xp.appendMenuItem(xp.findPluginsMenu(), "XP-Gliding", 0)
        self.menu = xp.createMenu("XP-Gliding", xp.findPluginsMenu(), self.menu_item, None, None)
        for cmd, handler, attr, label in self.commands:
            xp.registerCommandHandler(cmd, handler, 1, attr)
            xp.appendMenuItemWithCommand(self.menu, label, cmd)
        self.audio_cmd = xp.createCommand("xp_gliding/audio_vario/toggle",
                                          "XP-Gliding: X-Plane's audio vario on/off (total energy)")
        xp.registerCommandHandler(self.audio_cmd, self.on_audio_toggle, 1, None)
        self.audio_item = xp.appendMenuItemWithCommand(self.menu, AUDIO_LABEL, self.audio_cmd)
        self.glider_cmd = xp.createCommand("xp_gliding/aircraft/glider/toggle",
                                           "XP-Gliding: treat this aircraft as a glider (motor gliders)")
        xp.registerCommandHandler(self.glider_cmd, self.on_glider_toggle, 1, None)
        self.glider_item = xp.appendMenuItemWithCommand(self.menu, "Treat this aircraft as a glider",
                                                        self.glider_cmd)
        self.near_cloud_cmd = xp.createCommand("xp_gliding/airstart/near_cloud",
                                               "XP-Gliding: put the glider in the air near a cloud")
        xp.registerCommandHandler(self.near_cloud_cmd, self.on_near_cloud, 1, None)
        xp.appendMenuItemWithCommand(self.menu, "Put me near a cloud", self.near_cloud_cmd)
        xp.appendMenuSeparator(self.menu)
        self.submenus = []  # (menu, setting, values, in the menu's order)
        # What each submenu item sets. An item carries only its place in this list: a tuple made
        # for the call did not come back intact in X-Plane (2026-11-07), and XPPython3's samples
        # pass plain numbers or functions kept alive elsewhere.
        self.choices = []
        self.zi_item = None  # greyed out while the weather sets zi
        for title, attr, options in MENU_CHOICES:
            item = xp.appendMenuItem(self.menu, title, None)
            if attr == "zi_m":
                self.zi_item = item
            submenu = xp.createMenu(title, self.menu, item, self.on_choice, None)
            for label, value in options:
                xp.appendMenuItem(submenu, label, len(self.choices))
                self.choices.append((attr, value))
            self.submenus.append((submenu, attr, tuple(value for _, value in options)))
        xp.appendMenuSeparator(self.menu)
        self.status_item = xp.appendMenuItem(self.menu, "Starting", None)
        xp.enableMenuItem(self.menu, self.status_item, 0)
        self.refresh_menu()

        self.loop = xp.createFlightLoop(self.flight_loop, xp.FlightLoop_Phase_BeforeFlightModel, None)
        return self.Name, self.Sig, self.Desc

    def XPluginStop(self):
        xp.destroyFlightLoop(self.loop)
        self.hud.stop()
        for cmd, handler, attr, _ in self.commands:
            xp.unregisterCommandHandler(cmd, handler, 1, attr)
        xp.unregisterCommandHandler(self.audio_cmd, self.on_audio_toggle, 1, None)
        xp.unregisterCommandHandler(self.glider_cmd, self.on_glider_toggle, 1, None)
        xp.unregisterCommandHandler(self.near_cloud_cmd, self.on_near_cloud, 1, None)
        for submenu, _, _ in self.submenus:
            xp.destroyMenu(submenu)
        xp.destroyMenu(self.menu)
        xp.removeMenuItem(xp.findPluginsMenu(), self.menu_item)
        for ref in self.datarefs:
            xp.unregisterDataAccessor(ref)

    def XPluginEnable(self):
        self.failed = False
        self.failures = 0
        xp.setMenuItemName(self.menu, 0, ENABLED_LABEL)
        self.load_aircraft()
        xp.scheduleFlightLoop(self.loop, -1, 1)
        self.hud.enable()
        return 1

    def XPluginDisable(self):
        xp.scheduleFlightLoop(self.loop, 0, 1)
        self.guard.release()
        self.markers.shutdown()
        self.clouds.shutdown()
        self.hud.disable()
        self.status.active = 0
        self.out.clear()

    def XPluginReceiveMessage(self, inFromWho, inMessage, inParam):
        if inMessage == xp.MSG_PLANE_LOADED and inParam == 0:
            if self.failed:
                self.restart("a new aircraft")
            else:
                self.load_aircraft()
        elif inMessage == xp.MSG_AIRPORT_LOADED and self.failed:
            self.restart("a new flight")
        elif inMessage == xp.MSG_AIRPORT_LOADED:
            # A new flight with the same aircraft sends this and not MSG_PLANE_LOADED (seen in
            # X-Plane 12.4.3, 2026-11-09): its weather may be another day's. Putting the glider
            # near a cloud sends it too, and keeps the sky.
            if not self.just_placed(time.monotonic()):
                self.injector.weather.reset(time.monotonic())
            self.hud.reset_instruments()
            self.next_slow = 0.0

    # --- aircraft -----------------------------------------------------------

    def load_aircraft(self):
        path = self.io.user_aircraft_path()
        geometry = read_acf_geometry(path) if path else None
        self.injector.set_geometry(geometry or DEFAULT_GEOMETRY)
        engines = self.io.engine_count()
        glider = self.io.is_glider()
        self.clouds.clear()  # a new flight: X-Plane may have dropped the particles
        self.injector.drift.reset()  # and the sky starts where the field drew it
        self.injector.reset_field()  # which ground each thermal was born over depends on that
        self.injector.lean.reset()
        self.injector.sky_wind = None
        self.injector.weather.reset(time.monotonic())  # a new flight, maybe a new day
        self.next_lean = 0.0
        # At the main menu the "aircraft" is X-Plane's own folder: stay inert until
        # a real aircraft is loaded (a plane-loaded message follows).
        self.acf_path = path
        self.acf = os.path.basename(path) if path.lower().endswith(".acf") else ""
        self.native_glider = glider or engines == 0
        self.update_eligibility()
        print(f"{TAG} aircraft {path or '(none)'}: {engines} engines, "
              f"{'filed as a glider' if glider else 'not filed as a glider'}, "
              f"{'treated as a glider' if self.settings.treated_as_glider(self.acf) else 'not in also_gliders'}, "
              f"{'eligible' if self.eligible else 'not a glider, inactive'}; "
              f"{self.injector.geometry}")

    def restart(self, why):
        """Start the flight loop again after an error, from a clean state, while restarts are left."""
        if not self.failed or self.failures > MAX_RESTARTS:
            return
        self.failed = False
        xp.setMenuItemName(self.menu, 0, ENABLED_LABEL)
        self.load_aircraft()
        xp.scheduleFlightLoop(self.loop, -1, 1)
        print(f"{TAG} flight loop started again after an error ({why})")

    def update_eligibility(self):
        """A glider is an aircraft filed as one, one with no engines, or one the pilot treats as a
        glider from the menu: a motor glider, which its author files as something else, since
        X-Plane would launch an aircraft filed as a glider by tow. The air rises for a motor glider
        with its engine running too, so the engine's state does not matter."""
        glider = self.native_glider or self.settings.treated_as_glider(self.acf)
        self.eligible = bool(self.acf) and (glider or not self.settings.gliders_only)
        self.hud.set_aircraft(self.acf_path, self.eligible)
        self.refresh_menu()

    # --- commands and menu ----------------------------------------------------

    def on_toggle(self, commandRef, phase, attr):
        if phase == xp.CommandBegin:
            setattr(self.settings, attr, not getattr(self.settings, attr))
            if attr == "enabled" and self.settings.enabled:
                self.restart("Enabled ticked again")
            if attr == "weather_base_enabled":
                self.injector.weather.reset(time.monotonic())
                self.next_slow = 0.0
            self.refresh_menu()
            print(f"{TAG} {attr} = {getattr(self.settings, attr)}")
            self.save()
        return 1

    def on_audio_toggle(self, commandRef, phase, refcon):
        """X-Plane's own audio vario, on or off: the same switch as the AUDIO on the ASK 21's panel.
        It is X-Plane's, so the plugin does not save it; the menu's tick follows the panel."""
        if phase == xp.CommandBegin:
            on = self.io.te_audio()
            if on is not None:
                self.io.set_te_audio(not on)
                self.refresh_menu()
                print(f"{TAG} X-Plane's audio vario {'off' if on else 'on'}")
        return 1

    def on_glider_toggle(self, commandRef, phase, refcon):
        """Treat the user's aircraft as a glider, or no longer. Nothing to do with no aircraft, or
        with one that is a glider already."""
        if phase == xp.CommandBegin and self.acf and not self.native_glider:
            wanted = not self.settings.treated_as_glider(self.acf)
            self.settings.treat_as_glider(self.acf, wanted)
            self.update_eligibility()
            print(f"{TAG} {self.acf} {'treated as a glider' if wanted else 'no longer treated as a glider'}")
            self.save()
        return 1

    def on_near_cloud(self, commandRef, phase, refcon):
        """Put the glider in the air near a cloud. What went wrong is said on screen and logged;
        an exception would stop the plugin's effect in the next flight loop, so it is only logged."""
        if phase == xp.CommandBegin:
            try:
                why = self.put_near_cloud()
                if why:
                    print(f"{TAG} put near a cloud: {why}")
                    xp.speakString(f"XP-Gliding: {why}")
            except Exception:
                print(f"{TAG} error putting the glider near a cloud, ignored:\n" + traceback.format_exc())
        return 1

    def just_placed(self, now):
        """Was the glider put near a cloud a moment ago? Then the sky, and the weather it was made
        from, stay: X-Plane takes the move as a new flight (seen in X-Plane 12.4.3, 2026-11-11),
        and a new reading of the weather's base, a metre off, made a new sky with no clouds."""
        return self.placed_at is not None and now - self.placed_at < PLACED_GRACE_S

    def why_no_cloud(self, s, catalog):
        """What to tell the pilot when no cloud is worth flying to. In the morning the daily cycle
        is blue, so say from when there will be clouds, in the sim's local time. In rain there are
        no thermals, so no cumulus."""
        if self.injector.rain > RAIN_OFF:
            return "it is raining here: no thermals and no clouds"
        cycle = catalog.cycle
        if cycle is not None:
            when = clouds_from(cycle, s.lat, s.lon, s.sky_t_s)
            t = s.sky_t_s
            if when is None:
                return "no clouds today any more"
            if when > t:
                local = (s.t_local_s + (when - t)) % 86400.0
                return (f"no clouds yet, the morning is blue: the first form at about "
                        f"{int(local // 3600):02d}:{int(local % 3600 // 60):02d} local time, try a few minutes after")
        return "no cloud within reach"

    def put_near_cloud(self):
        """Place the glider (`engine/airstart.py`). None if done, else why not, for the pilot."""
        st = self.settings
        if not (st.enabled and self.eligible and st.thermals_enabled and not self.failed):
            return "no thermals now, see the menu's last line"
        if st.blue_day:
            return "a blue day has no clouds; choose another day"
        if not st.clouds_enabled:
            return "tick Cumulus clouds first"
        catalog, heights, frame = self.clouds.catalog, self.clouds.heights, self.injector.frame
        s = self.state
        if (catalog is None or not catalog.started or heights.level_m is None or frame is None
                or getattr(s, "sky_t_s", None) is None):
            return "the clouds are still forming, try again in a few seconds"
        drift, t = self.injector.drift, s.sky_t_s
        e, n = frame.to_enu(*drift.to_air(s.lat, s.lon))
        th, r = pick_cloud(self.clouds.thermals(), e, n, t, self.clouds.planner.params)
        if th is None:
            return self.why_no_cloud(s, catalog)
        pe, pn, heading = place_near(th.e, th.n, e, n, s.psi_deg)
        lat, lon = drift.to_ground(*frame.to_latlon(pe, pn))
        ground_m = self.clouds.sky.ground_m(lat, lon)
        if ground_m is None:
            ground_m = s.msl_m - s.agl_m
        base_m = heights.base_m(th, t, drift)
        msl_m = start_height_m(ground_m, base_m)
        # Before the call: X-Plane sends its new flight's message from inside it (2026-11-11).
        self.placed_at = time.monotonic()
        self.injector.moved_to(lat, lon, t)
        self.io.place_user(lat, lon, msl_m, heading, SPEED_MS)
        self.hud.reset_instruments()
        self.next_slow = 0.0
        print(f"{TAG} put near a cloud {r / 1000.0:.1f} km away: at {lat:.5f}, {lon:.5f}, "
              f"{msl_m:.0f} m MSL ({msl_m - ground_m:.0f} m above the ground, base {base_m:.0f} m), "
              f"heading {heading:.0f}")
        return None

    def on_choice(self, menuRef, itemRef):
        """A value chosen in a submenu. A new sky or seed gives a new field in the slow path,
        and the clouds and markers follow it. The clouds' base comes from zi when each is
        created, so a new zi starts them over: here at once, and in `step` for any other way.

        An exception here would stay pending and surface in the next flight loop, which would
        stop the plugin's effect, so a failed choice is only written to the log."""
        try:
            attr, value = self.choices[itemRef]
            zi = self.settings.zi_m
            if attr == "day":
                label, values = DAYS[value]
                self.settings.update(values)
                print(f"{TAG} day: {label} ({', '.join(f'{k} = {v}' for k, v in values.items())})")
                if self.settings.weather_base_enabled:
                    # The day's zi is overridden: say so, or a day feels like another (2026-11-12).
                    print(f"{TAG} day: {DAY_WEATHER_NOTE}")
                    xp.speakString(f"XP-Gliding: {DAY_WEATHER_NOTE}")
            else:
                self.settings.update({attr: value})
                print(f"{TAG} {attr} = {getattr(self.settings, attr)}")
            if self.settings.zi_m != zi and not self.settings.weather_base_enabled:
                self.clouds.clear()
            self.next_slow = 0.0
            self.refresh_menu()
            self.save()
        except Exception:
            print(f"{TAG} error in a menu choice, ignored:\n" + traceback.format_exc())

    def save(self):
        failed = save_settings(self.settings, self.config_path)
        if failed:
            print(f"{TAG} {failed}")

    def status_line(self):
        """The menu's last line: what the plugin is doing, and why there are no thermals when
        there are none. Plain ASCII: a menu may not draw other characters."""
        st = self.settings
        if self.failed:
            return "Stopped by an error, see XPPython3Log.txt"
        if not st.enabled:
            return "Off: Enabled is unticked"
        if not self.acf:
            return "Waiting for an aircraft"
        if not self.eligible:
            return "Inactive: this aircraft has engines and is not treated as a glider"
        if not st.thermals_enabled:
            return "No thermals: Thermals is unticked"
        injector = self.injector
        if injector.field is None:
            return "Starting"
        zi, zi_now = injector.zi_m, injector.zi_now_m
        alive = injector.nearest.alive
        if alive == 0:
            if st.sun_enabled and injector.sun_elevation_deg < SUN_MIN_DEG:
                return f"No thermals: the sun is under {SUN_MIN_DEG:.0f} degrees"
            return "No thermals within reach"
        if round(zi_now) < round(zi):
            return f"Active: {alive} thermals within reach, zi {zi_now:.0f} m, {zi:.0f} m by mid-afternoon"
        return f"Active: {alive} thermals within reach, zi {zi:.0f} m"

    def update_status(self):
        if self.status_item is None:
            return
        text = self.status_line()
        if text != self.status_text:
            self.status_text = text
            xp.setMenuItemName(self.menu, self.status_item, text)

    def chosen(self, attr):
        """What a submenu shows as chosen: a setting, or the place in DAYS of the day the settings
        make (None, no tick, when they make none)."""
        return day_index(self.settings) if attr == "day" else getattr(self.settings, attr)

    def refresh_menu(self):
        """The menu's ticks and greyed-out items. Called once a second too, since a dataref can
        change a setting, so the SDK is only called when what the menu shows has changed."""
        self.update_status()
        st = self.settings
        state = (tuple(getattr(st, attr) for _, _, attr, _ in self.commands),
                 tuple(self.chosen(attr) for _, attr, _ in self.submenus),
                 self.acf, self.native_glider, st.treated_as_glider(self.acf), self.io.te_audio())
        if state == self._menu_state:
            return
        self._menu_state = state
        for index, (_, _, attr, _) in enumerate(self.commands):
            check = xp.Menu_Checked if getattr(self.settings, attr) else xp.Menu_Unchecked
            xp.checkMenuItem(self.menu, index, check)
        for submenu, attr, values in self.submenus:
            current = self.chosen(attr)
            for index, value in enumerate(values):
                xp.checkMenuItem(submenu, index, xp.Menu_Checked if value == current else xp.Menu_Unchecked)
        audio = state[-1]
        xp.checkMenuItem(self.menu, self.audio_item, xp.Menu_Checked if audio else xp.Menu_Unchecked)
        xp.enableMenuItem(self.menu, self.audio_item, int(audio is not None))
        # Checked for any glider; only an aircraft with engines that is not filed as a glider can change it.
        glider = self.native_glider or self.settings.treated_as_glider(self.acf)
        xp.checkMenuItem(self.menu, self.glider_item, xp.Menu_Checked if glider else xp.Menu_Unchecked)
        xp.enableMenuItem(self.menu, self.glider_item, int(bool(self.acf) and not self.native_glider))
        if self.zi_item is not None:
            xp.enableMenuItem(self.menu, self.zi_item, int(not self.settings.weather_base_enabled))

    def read_weather(self, s, now):
        """The cloud base from X-Plane's weather, over the ground under the aircraft. A new base
        gives a new sky in the slow update that follows."""
        weather = self.injector.weather
        if weather.read(s.msl_m - s.agl_m, *self.io.air_layers(), now):
            print(f"{TAG} cloud base from X-Plane's weather: {weather.base_m:.0f} m above the ground, "
                  f"zi {self.injector.zi_m:.0f} m (reading {weather.reads})")
        elif weather.base_m is None:
            print(f"{TAG} X-Plane's weather has no temperatures and dew points yet; zi stays "
                  f"{self.settings.zi_m:.0f} m (reading {weather.reads})")

    # --- per frame -------------------------------------------------------------

    def flight_loop(self, sinceLast, elapsedTime, counter, refCon):
        try:
            return self.step()
        except Exception:
            # Never leave a half-working force behind, and never log every frame.
            self.failed = True
            self.failures += 1
            again = ("it starts again with a new flight or aircraft, or by unticking and ticking Enabled"
                     if self.failures <= MAX_RESTARTS else "it starts again only when the plugin is re-enabled")
            print(f"{TAG} error in the flight loop; plugin effect stopped, {again}:\n"
                  + traceback.format_exc())
            xp.setMenuItemName(self.menu, 0, FAILED_LABEL)
            self.update_status()
            self.status.active = 0
            self.out.clear()
            self.guard.release()
            self.markers.clear()
            self.clouds.clear()
            return 0

    def step(self):
        st = self.settings
        now = time.monotonic()
        active = st.enabled and self.eligible
        self.guard.want(active and st.thermals_enabled, now)
        markers = active and st.thermals_enabled and st.markers_enabled
        if not markers and self.markers.shown:
            self.markers.clear()
        clouds = active and st.thermals_enabled and st.clouds_enabled and not st.blue_day
        if not clouds and self.clouds.holding:
            self.clouds.clear()
        if not active or self.io.frozen():
            self.status.active = 0
            self.out.clear()
            return -1
        t0 = time.perf_counter()
        s = self.io.read_state(self.state)
        self.injector.carry(s)
        if now >= self.next_lean:
            self.next_lean = now + LEAN_PERIOD_S
            layers = self.io.wind_layers() if st.lean_enabled or st.wind_at_clouds else None
            if st.wind_at_clouds:
                self.injector.sky_wind_update(s, *layers, s.msl_m,
                                              self.clouds.heights.level_at(self.injector.depth_share))
            if st.lean_enabled:
                self.injector.lean_update(s, *layers, s.msl_m)
            else:
                self.injector.lean.reset()
        if now >= self.next_slow:
            self.next_slow = now + SLOW_PERIOD_S
            self.next_markers = now + 0.5 * SLOW_PERIOD_S
            self.next_clouds = now + CLOUDS_PERIOD_S
            if st.weather_base_enabled and self.injector.weather.due(now):
                self.read_weather(s, now)
            self.injector.slow_update(s, self.io.sky_layers())
            if self.injector.jumped and not self.just_placed(now):
                self.injector.weather.reset(now)  # a new place or time: read its weather
                self.hud.reset_instruments()  # and the vario's average starts over
            zi = self.injector.zi_m
            if zi != self.sky_zi_m:
                if self.sky_zi_m is not None:
                    self.clouds.clear()
                self.sky_zi_m = zi
            self.hud.zi_m = self.injector.zi_now_m
            self.hud.set_top(self.clouds.status.nearest_base_m,
                             self.clouds.heights.level_at(self.injector.depth_share))
            self.refresh_menu()
        elif clouds and now >= self.next_clouds and self.injector.field is not None:
            self.next_clouds = now + CLOUDS_PERIOD_S
            self.clouds.update(self.injector.field, self.injector.frame, s, s.msl_m, self.sky_zi_m, now,
                               self.injector.drift, self.injector.shade.share)
        elif markers and now >= self.next_markers and self.injector.field is not None:
            self.next_markers = now + SLOW_PERIOD_S
            self.markers.update(self.injector.field, self.injector.frame, s, s.msl_m,
                                self.io.local_position(), self.injector.wstar_ms, self.sky_zi_m, now,
                                self.injector.drift, self.injector.lean_e_m, self.injector.lean_n_m)
        self.injector.step(s, self.out)
        self.io.apply(self.out)
        self.status.active = 1
        us = (time.perf_counter() - t0) * 1e6
        self.status.frame_us += 0.02 * (us - self.status.frame_us)
        return -1
