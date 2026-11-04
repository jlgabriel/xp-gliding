"""xp-gliding flight logger (measurement tool, not part of the plugin).

Records one CSV row per frame while recording is on, so climb rates, sink
rates, frame times and plugin forces can be measured offline with
`analyze_flightlog.py` instead of read from a vario by eye.

Install: copy this single file into `Resources/plugins/PythonPlugins/`.

Commands (bind them to joystick buttons in X-Plane):
  xp_gliding/flightlog/toggle   start / stop recording
  xp_gliding/flightlog/mark     increment the segment mark (start/end of a test)

Logs go to `Output/xp-gliding/flightlogs/flightlog_YYYYMMDD_HHMMSS.csv`.

Two flight loops run while recording: one before the flight model reads the
`*_plug_acf` force datarefs ("pre_" columns); one after the flight model reads
everything else and the same forces again ("post_" columns) and writes the row.
Comparing pre/post shows whether X-Plane resets those datarefs every cycle.

If Alex Ferrer's xplane_thermals plugin is loaded, its shared `world` module
is read to log what its thermal model asked for ("alex_" columns). So that the
test pilot can run the calibration tests from outside, a few of its settings
are also exposed as datarefs (`xp_gliding/flightlog/alex_*`, see
ALEX_CONTROLS; the last two are read-only); nothing writes them unless asked. Writing them does not save
Alex's preferences, but his plugin saves its current settings when X-Plane
closes, so restore them before quitting. Phase 0 only; remove all of this when
the reference plugin goes.

Since 0.3.0, if the xp-gliding plugin is loaded, its own datarefs are logged
("xpg_" columns, see XPG_DATAREFS): the lift at each sample point, the force
and roll moment it applied, its debug modes and its cost per frame.

License: GPL-3.0-or-later.
"""

import os
import sys
import time

import xp

LOGGER_VERSION = "0.4.0"
FLUSH_EVERY_ROWS = 300

# (column, dataref, type) read after the flight model
STATE_DATAREFS = (
    ("t_run_s", "sim/time/total_running_time_sec", "f"),
    ("t_zulu_s", "sim/time/zulu_time_sec", "f"),
    ("frame_period_s", "sim/operation/misc/frame_rate_period", "f"),
    ("paused", "sim/time/paused", "i"),
    ("replay", "sim/time/is_in_replay", "i"),
    ("sim_speed_actual", "sim/time/sim_speed_actual", "f"),
    ("lat_deg", "sim/flightmodel/position/latitude", "d"),
    ("lon_deg", "sim/flightmodel/position/longitude", "d"),
    ("elev_m", "sim/flightmodel/position/elevation", "d"),
    ("agl_m", "sim/flightmodel/position/y_agl", "f"),
    ("vs_ms", "sim/flightmodel/position/vh_ind", "f"),
    ("te_fpm", "sim/cockpit2/gauges/indicators/total_energy_fpm", "f"),
    ("tas_ms", "sim/flightmodel/position/true_airspeed", "f"),
    ("ias_kt", "sim/flightmodel/position/indicated_airspeed", "f"),
    ("alpha_deg", "sim/flightmodel/position/alpha", "f"),
    ("phi_deg", "sim/flightmodel/position/phi", "f"),
    ("theta_deg", "sim/flightmodel/position/theta", "f"),
    ("psi_deg", "sim/flightmodel/position/psi", "f"),
    ("phi_dot_dps", "sim/flightmodel/position/phi_dot", "f"),
    ("theta_dot_dps", "sim/flightmodel/position/theta_dot", "f"),
    ("mass_kg", "sim/flightmodel/weight/m_total", "f"),
    ("wind_ms", "sim/weather/aircraft/wind_now_speed_msc", "f"),
    ("wind_dir_deg", "sim/weather/aircraft/wind_now_direction_degt", "f"),
    ("native_thermal_ms", "sim/weather/aircraft/thermal_rate_ms", "f"),
    ("sun_pitch_deg", "sim/graphics/scenery/sun_pitch_degrees", "f"),
    ("beta_deg", "sim/flightmodel/position/beta", "f"),
)

FORCE_DATAREFS = (
    ("fnrml_n", "sim/flightmodel/forces/fnrml_plug_acf"),
    ("faxil_n", "sim/flightmodel/forces/faxil_plug_acf"),
    ("l_nm", "sim/flightmodel/forces/L_plug_acf"),
    ("m_nm", "sim/flightmodel/forces/M_plug_acf"),
)

# (column, attribute of Alex's `world` module)
ALEX_FIELDS = (
    ("alex_enabled", "PLUGIN_ENABLED"),
    ("alex_cal_mode", "CALIBRATE_MODE"),
    ("alex_cal_ms", "calibrate_factor_ms"),
    ("alex_lift_ms", "cal_lift_force"),
    ("alex_sun_factor", "sun_factor"),
    ("alex_strength_ms", "thermal_strength"),
    ("alex_radius_m", "thermal_radius"),
    ("alex_dist_m", "distance_from_center"),
    ("alex_lift_factor", "lift_factor"),
    ("alex_thrust_factor", "thrust_factor"),
    ("alex_roll_factor", "roll_factor"),
    ("alex_pitch_factor", "pitch_factor"),
)

# (dataref suffix, attribute of Alex's `world` module, X-Plane type, writable)
# exposed as xp_gliding/flightlog/<suffix>
ALEX_CONTROLS = (
    ("alex_enabled", "PLUGIN_ENABLED", "i", 1),
    ("alex_cal_mode", "CALIBRATE_MODE", "i", 1),
    ("alex_cal_ms", "calibrate_factor_ms", "f", 1),
    ("alex_lift_factor", "lift_factor", "f", 1),
    ("alex_thrust_factor", "thrust_factor", "f", 1),
    ("alex_lift_ms", "cal_lift_force", "f", 0),
    ("alex_dist_m", "distance_from_center", "f", 0),
)

# (column, xp-gliding plugin dataref, type): what our own plugin applied, since
# the *_plug_acf datarefs read 0 after the flight model. Empty if not loaded.
XPG_DATAREFS = (
    ("xpg_active", "xp_gliding/active", "i"),
    ("xpg_lift_ms", "xp_gliding/lift_ms", "f"),
    ("xpg_lift_centre_ms", "xp_gliding/lift_centre_ms", "f"),
    ("xpg_lift_left_ms", "xp_gliding/lift_left_ms", "f"),
    ("xpg_lift_right_ms", "xp_gliding/lift_right_ms", "f"),
    ("xpg_lift_tail_ms", "xp_gliding/lift_tail_ms", "f"),
    ("xpg_force_n", "xp_gliding/force_n", "f"),
    ("xpg_roll_nm", "xp_gliding/roll_nm", "f"),
    ("xpg_dw_dy", "xp_gliding/dw_dy", "f"),
    ("xpg_dw_dy_helix", "xp_gliding/dw_dy_helix", "f"),
    ("xpg_uniform_ms", "xp_gliding/debug/uniform_ms", "f"),
    ("xpg_debug_dw_dy", "xp_gliding/debug/dw_dy", "f"),
    ("xpg_nearest_m", "xp_gliding/nearest/distance_m", "f"),
    ("xpg_nearest_core_ms", "xp_gliding/nearest/core_ms", "f"),
    ("xpg_frame_us", "xp_gliding/frame_us", "f"),
    ("xpg_markers", "xp_gliding/markers/count", "i"),
    ("xpg_markers_update_us", "xp_gliding/markers/update_us", "f"),
)

COLUMNS = (
    [c for c, _, _ in STATE_DATAREFS]
    + ["pre_" + c for c, _ in FORCE_DATAREFS]
    + ["post_" + c for c, _ in FORCE_DATAREFS]
    + ["mark"]
    + [c for c, _ in ALEX_FIELDS]
    + [c for c, _, _ in XPG_DATAREFS]
)


def _alex_world():
    """Alex's plugin keeps its state in a top-level module named `world`."""
    world = sys.modules.get("world")
    if world is not None and hasattr(world, "lift_factor") and hasattr(world, "CALIBRATE_MODE"):
        return world
    return None


def _read_alex_int(attr):
    world = _alex_world()
    return int(bool(getattr(world, attr, 0))) if world is not None else -1


def _write_alex_int(attr, value):
    world = _alex_world()
    if world is not None:
        setattr(world, attr, bool(value))


def _read_alex_float(attr):
    world = _alex_world()
    return float(getattr(world, attr, 0.0)) if world is not None else -1.0


def _write_alex_float(attr, value):
    world = _alex_world()
    if world is not None:
        old = getattr(world, attr, 0.0)
        # Keep ints as ints: Alex's sliders are imgui int sliders.
        setattr(world, attr, int(round(value)) if isinstance(old, int) else float(value))


def _fmt(value):
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return repr(value)
    return ""


class PythonInterface:
    def XPluginStart(self):
        self.Name = "xp-gliding flight log"
        self.Sig = "jlgabriel.xp_gliding.flightlog"
        self.Desc = "Per-frame CSV flight logger for xp-gliding measurements."

        getters = {"f": xp.getDataf, "d": xp.getDatad, "i": xp.getDatai}
        self.state_refs = [(getters[kind], xp.findDataRef(name)) for _, name, kind in STATE_DATAREFS]
        self.force_refs = [xp.findDataRef(name) for _, name in FORCE_DATAREFS]
        self.pre_forces = [0.0] * len(self.force_refs)

        self.getters = getters
        self.xpg_refs = []
        self.file = None
        self.buffer = []
        self.mark = 0

        self.toggle_cmd = xp.createCommand("xp_gliding/flightlog/toggle", "xp-gliding: start/stop flight log")
        self.mark_cmd = xp.createCommand("xp_gliding/flightlog/mark", "xp-gliding: next flight log mark")
        xp.registerCommandHandler(self.toggle_cmd, self.on_toggle, 1, None)
        xp.registerCommandHandler(self.mark_cmd, self.on_mark, 1, None)

        self.menu_item = xp.appendMenuItem(xp.findPluginsMenu(), "xp-gliding flight log", 0)
        self.menu = xp.createMenu("xp-gliding flight log", xp.findPluginsMenu(), self.menu_item, None, None)
        xp.appendMenuItemWithCommand(self.menu, "Start / stop recording", self.toggle_cmd)
        xp.appendMenuItemWithCommand(self.menu, "Next mark", self.mark_cmd)

        self.alex_refs = []
        for suffix, attr, kind, writable in ALEX_CONTROLS:
            name = "xp_gliding/flightlog/" + suffix
            if kind == "i":
                ref = xp.registerDataAccessor(name, xp.Type_Int, writable,
                                              readInt=_read_alex_int,
                                              writeInt=_write_alex_int if writable else None,
                                              readRefCon=attr, writeRefCon=attr)
            else:
                ref = xp.registerDataAccessor(name, xp.Type_Float, writable,
                                              readFloat=_read_alex_float,
                                              writeFloat=_write_alex_float if writable else None,
                                              readRefCon=attr, writeRefCon=attr)
            self.alex_refs.append(ref)

        self.pre_loop = xp.createFlightLoop(self.before_fm, xp.FlightLoop_Phase_BeforeFlightModel, None)
        self.post_loop = xp.createFlightLoop(self.after_fm, xp.FlightLoop_Phase_AfterFlightModel, None)
        return self.Name, self.Sig, self.Desc

    def XPluginStop(self):
        self.stop_recording()
        xp.destroyFlightLoop(self.pre_loop)
        xp.destroyFlightLoop(self.post_loop)
        for ref in self.alex_refs:
            xp.unregisterDataAccessor(ref)
        xp.unregisterCommandHandler(self.toggle_cmd, self.on_toggle, 1, None)
        xp.unregisterCommandHandler(self.mark_cmd, self.on_mark, 1, None)
        xp.destroyMenu(self.menu)
        xp.removeMenuItem(xp.findPluginsMenu(), self.menu_item)

    def XPluginEnable(self):
        return 1

    def XPluginDisable(self):
        self.stop_recording()

    def XPluginReceiveMessage(self, inFromWho, inMessage, inParam):
        pass

    # --- commands -----------------------------------------------------------

    def on_toggle(self, commandRef, phase, refCon):
        if phase == xp.CommandBegin:
            if self.file is None:
                self.start_recording()
            else:
                self.stop_recording()
        return 1

    def on_mark(self, commandRef, phase, refCon):
        if phase == xp.CommandBegin and self.file is not None:
            self.mark += 1
            xp.speakString(f"mark {self.mark}")
        return 1

    # --- recording ----------------------------------------------------------

    def start_recording(self):
        folder = os.path.join(xp.getSystemPath(), "Output", "xp-gliding", "flightlogs")
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, time.strftime("flightlog_%Y%m%d_%H%M%S.csv"))
        self.file = open(path, "w", encoding="utf-8", newline="\n")
        self.mark = 0
        acf_file, acf_path = xp.getNthAircraftModel(0)
        xp_version, xplm_version, _ = xp.getVersions()
        self.file.write(f"# logger_version={LOGGER_VERSION}\n")
        self.file.write(f"# xplane_version={xp_version} xplm_version={xplm_version}\n")
        self.file.write(f"# aircraft={acf_file}\n")
        self.file.write(f"# aircraft_path={acf_path}\n")
        self.file.write(f"# alex_plugin_loaded={int(_alex_world() is not None)}\n")
        # Looked up here, not at start: the xp-gliding plugin may load after this one.
        self.xpg_refs = [(self.getters[kind], xp.findDataRef(name)) for _, name, kind in XPG_DATAREFS]
        self.file.write(f"# xp_gliding_loaded={int(self.xpg_refs[0][1] is not None)}\n")
        self.file.write(",".join(COLUMNS) + "\n")
        xp.scheduleFlightLoop(self.pre_loop, -1, 1)
        xp.scheduleFlightLoop(self.post_loop, -1, 1)
        xp.speakString("flight log on")
        print(f"[xp-gliding flightlog] recording to {path}")

    def stop_recording(self):
        if self.file is None:
            return
        xp.scheduleFlightLoop(self.pre_loop, 0, 1)
        xp.scheduleFlightLoop(self.post_loop, 0, 1)
        self.flush()
        self.file.close()
        self.file = None
        xp.speakString("flight log off")
        print("[xp-gliding flightlog] recording stopped")

    def flush(self):
        if self.buffer:
            self.file.write("".join(self.buffer))
            self.buffer.clear()

    # --- flight loops -------------------------------------------------------

    def before_fm(self, sinceLast, elapsedTime, counter, refCon):
        for i, ref in enumerate(self.force_refs):
            self.pre_forces[i] = xp.getDataf(ref)
        return -1

    def after_fm(self, sinceLast, elapsedTime, counter, refCon):
        values = [_fmt(get(ref)) for get, ref in self.state_refs]
        values += [_fmt(v) for v in self.pre_forces]
        values += [_fmt(xp.getDataf(ref)) for ref in self.force_refs]
        values.append(str(self.mark))
        world = _alex_world()
        if world is None:
            values += [""] * len(ALEX_FIELDS)
        else:
            values += [_fmt(getattr(world, attr, None)) for _, attr in ALEX_FIELDS]
        values += [_fmt(get(ref)) if ref is not None else "" for get, ref in self.xpg_refs]
        self.buffer.append(",".join(values) + "\n")
        if len(self.buffer) >= FLUSH_EVERY_ROWS:
            self.flush()
        return -1
