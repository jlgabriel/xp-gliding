"""xp-gliding flight logger (measurement tool, not part of the plugin).

Records one CSV row per frame while recording is on, so climb rates, sink
rates, frame times and plugin forces can be measured offline with
`analyze_flightlog.py` instead of read from a vario by eye.

Install: copy this single file into `Resources/plugins/PythonPlugins/`.

Commands (bind them to joystick buttons in X-Plane):
  xp_gliding/flightlog/toggle   start / stop recording
  xp_gliding/flightlog/mark     increment the segment mark (start/end of a test)

Since 0.5.0 it also records by itself (`AutoRecord`), because the best flights were the
ones nobody remembered to record: a glider in the air starts a log, and landing or loading
a new flight ends it. Stopping a log by hand holds this off until the next flight. Since
0.11.0 it writes no row while paused or in replay, and rounds its numbers: about 110 MB per
hour of flight at 60 frames a second (before, about 180, and a paused sim kept writing). `xp_gliding/flightlog/recording` says whether it is
recording, and writing 0 to `xp_gliding/flightlog/auto` turns the automatic part off until
X-Plane restarts, which the test pilot does so that its own start and stop stay its own.

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

LOGGER_VERSION = "0.14.0"
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
    ("speedbrake_ratio", "sim/cockpit2/controls/speedbrake_ratio", "f"),
    ("date_days", "sim/time/local_date_days", "i"),
    ("t_local_s", "sim/time/local_time_sec", "f"),
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
    ("xpg_nearest_floor_m", "xp_gliding/nearest/floor_m", "f"),
    ("xpg_frame_us", "xp_gliding/frame_us", "f"),
    ("xpg_markers", "xp_gliding/markers/count", "i"),
    ("xpg_markers_update_us", "xp_gliding/markers/update_us", "f"),
    # What it takes to rebuild the sky afterwards (tools/flightlog/replay_sky.py).
    ("xpg_seed", "xp_gliding/seed", "i"),
    ("xpg_sky_index", "xp_gliding/sky_index", "i"),
    ("xpg_dlat_deg", "xp_gliding/wind/dlat_deg", "f"),
    ("xpg_dlon_deg", "xp_gliding/wind/dlon_deg", "f"),
    ("xpg_lean_e_m", "xp_gliding/lean/e_m", "f"),
    ("xpg_lean_n_m", "xp_gliding/lean/n_m", "f"),
    ("xpg_wstar_ms", "xp_gliding/day/wstar_ms", "f"),  # in use: the daily cycle's, since 0.9.0
    ("xpg_wstar_setting_ms", "xp_gliding/wstar_ms", "f"),  # the menu's, the day's peak
    ("xpg_zi_m", "xp_gliding/day/zi_m", "f"),  # in use: the weather's, if on; the afternoon's
    # The daily cycle (since 0.10.0): on or off, the depth of the moment, and the nearest thermal's.
    ("xpg_sun_enabled", "xp_gliding/sun_enabled", "i"),
    ("xpg_depth_share", "xp_gliding/day/depth_share", "f"),
    ("xpg_nearest_depth", "xp_gliding/nearest/depth", "f"),
    ("xpg_wind_at_clouds", "xp_gliding/wind_at_clouds", "i"),
    # The sharper thermal edges (since 0.12.0): on or off, the kick's lift before its split
    # into body axes (N), and the amplitude of the edge's bumps (m/s). The ring and the sink
    # between thermals are already in the lift columns.
    ("xpg_edge_enabled", "xp_gliding/edge_enabled", "i"),
    ("xpg_kick_n", "xp_gliding/kick_n", "f"),
    ("xpg_turbulence_ms", "xp_gliding/turbulence_ms", "f"),
    # X-Plane's clouds and rain (since 0.13.0): the share of w* they leave now and the one it
    # heads for, the sun its layers stop, and the rain (engine/shade.py).
    ("xpg_shade_share", "xp_gliding/day/shade_share", "f"),
    ("xpg_shade_target", "xp_gliding/day/shade_target", "f"),
    ("xpg_sky_cover", "xp_gliding/day/sky_cover", "f"),
    ("xpg_rain", "xp_gliding/day/rain", "f"),
    # Good and bad areas (since 0.14.0): on or off, the area's quality at the glider, and the
    # thermals' number and strength there, times the sky's (engine/areas.py).
    ("xpg_areas_enabled", "xp_gliding/areas_enabled", "i"),
    ("xpg_area_quality", "xp_gliding/day/area_quality", "f"),
    ("xpg_area_density", "xp_gliding/day/area_density", "f"),
    ("xpg_area_strength", "xp_gliding/day/area_strength", "f"),
    # The clouds, which rebuilding the sky cannot give: their height reads the ground
    # (tools/flightlog/read_flight.py). Updated every few seconds, not per frame.
    ("xpg_cloud_level_m", "xp_gliding/clouds/level_m", "f"),
    ("xpg_cloud_raised", "xp_gliding/clouds/raised", "i"),
    ("xpg_cloud_created", "xp_gliding/clouds/created", "i"),
    ("xpg_cloud_base_max_m", "xp_gliding/clouds/base_max_m", "f"),
    ("xpg_cloud_nearest_m", "xp_gliding/clouds/nearest_m", "f"),
    ("xpg_cloud_nearest_base_m", "xp_gliding/clouds/nearest_base_m", "f"),
    ("xpg_cloud_nearest_scale", "xp_gliding/clouds/nearest_scale", "f"),
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


# Since 0.11.0 numbers are written to what they can tell, not to 17 digits: degrees to
# 7 decimals (about 1 cm), clocks to the millisecond, the rest to 6 significant digits.
# That halves a row.
DEGREES = {"lat_deg", "lon_deg", "xpg_dlat_deg", "xpg_dlon_deg"}
CLOCKS = {"t_run_s", "t_zulu_s", "t_local_s"}


def _spec(column):
    return ".7f" if column in DEGREES else ".3f" if column in CLOCKS else ".6g"


def _fmt(value, spec=".6g"):
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return format(value, spec)
    return ""


class AutoRecord:
    """When to record without being asked. Pure logic, one `step` about a second apart.

    A log starts once a glider has been in the air for a moment, so a flight loading on
    the runway or a powered aircraft records nothing, and ends once it has sat on the
    ground for a while. Only a log started here is ended here. Time paused does not count.
    """

    START, STOP = 1, 2
    AIRBORNE_AGL_M = 10.0
    GROUND_AGL_M = 3.0
    GROUND_SPEED_MS = 1.0
    START_AFTER_S = 2.0
    STOP_AFTER_S = 20.0

    def __init__(self):
        self.enabled = True
        self.held = False  # stopped by hand: not again until the next flight
        self.started_here = False
        self.airborne_s = 0.0
        self.ground_s = 0.0

    def stopped_by_hand(self):
        self.held = True
        self.started_here = False

    def new_flight(self):
        """A flight or aircraft was loaded. Returns STOP if a log of ours should end."""
        self.held = False
        self.airborne_s = self.ground_s = 0.0
        if self.started_here:
            self.started_here = False
            return self.STOP
        return None

    def step(self, dt, recording, is_glider, agl_m, ground_speed_ms, paused):
        if not self.enabled or paused:
            return None
        self.airborne_s = self.airborne_s + dt if agl_m > self.AIRBORNE_AGL_M else 0.0
        on_ground = agl_m < self.GROUND_AGL_M and ground_speed_ms < self.GROUND_SPEED_MS
        self.ground_s = self.ground_s + dt if on_ground else 0.0
        if recording:
            if self.started_here and (not is_glider or self.ground_s >= self.STOP_AFTER_S):
                self.started_here = False
                return self.STOP
            return None
        if is_glider and not self.held and self.airborne_s >= self.START_AFTER_S:
            self.started_here = True
            return self.START
        return None


class PythonInterface:
    def XPluginStart(self):
        self.Name = "xp-gliding flight log"
        self.Sig = "jlgabriel.xp_gliding.flightlog"
        self.Desc = "Per-frame CSV flight logger for xp-gliding measurements."

        getters = {"f": xp.getDataf, "d": xp.getDatad, "i": xp.getDatai}
        self.state_refs = [(getters[kind], xp.findDataRef(name), _spec(column))
                           for column, name, kind in STATE_DATAREFS]
        self.paused_ref = xp.findDataRef("sim/time/paused")
        self.replay_ref = xp.findDataRef("sim/time/is_in_replay")
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

        self.auto = AutoRecord()
        self.auto_refs = (xp.findDataRef("sim/aircraft/engine/acf_num_engines"),
                          xp.findDataRef("sim/flightmodel/position/y_agl"),
                          xp.findDataRef("sim/flightmodel/position/groundspeed"),
                          xp.findDataRef("sim/time/paused"),
                          xp.findDataRef("sim/time/is_in_replay"))
        self.own_refs = [
            xp.registerDataAccessor("xp_gliding/flightlog/recording", xp.Type_Int, 0,
                                    readInt=self._read_recording),
            xp.registerDataAccessor("xp_gliding/flightlog/auto", xp.Type_Int, 1,
                                    readInt=self._read_auto, writeInt=self._write_auto),
        ]

        self.pre_loop = xp.createFlightLoop(self.before_fm, xp.FlightLoop_Phase_BeforeFlightModel, None)
        self.post_loop = xp.createFlightLoop(self.after_fm, xp.FlightLoop_Phase_AfterFlightModel, None)
        self.auto_loop = xp.createFlightLoop(self.auto_step, xp.FlightLoop_Phase_AfterFlightModel, None)
        return self.Name, self.Sig, self.Desc

    def XPluginStop(self):
        self.stop_recording()
        xp.destroyFlightLoop(self.pre_loop)
        xp.destroyFlightLoop(self.post_loop)
        xp.destroyFlightLoop(self.auto_loop)
        for ref in self.alex_refs + self.own_refs:
            xp.unregisterDataAccessor(ref)
        xp.unregisterCommandHandler(self.toggle_cmd, self.on_toggle, 1, None)
        xp.unregisterCommandHandler(self.mark_cmd, self.on_mark, 1, None)
        xp.destroyMenu(self.menu)
        xp.removeMenuItem(xp.findPluginsMenu(), self.menu_item)

    def XPluginEnable(self):
        xp.scheduleFlightLoop(self.auto_loop, 1.0, 1)
        return 1

    def XPluginDisable(self):
        xp.scheduleFlightLoop(self.auto_loop, 0, 1)
        self.stop_recording()

    def XPluginReceiveMessage(self, inFromWho, inMessage, inParam):
        if inMessage == xp.MSG_AIRPORT_LOADED or (inMessage == xp.MSG_PLANE_LOADED and inParam == 0):
            if self.auto.new_flight() == AutoRecord.STOP:
                self.stop_recording()

    # --- recording by itself ---------------------------------------------------

    def auto_step(self, sinceLast, elapsedTime, counter, refCon):
        engines, agl, speed, paused, replay = self.auto_refs
        action = self.auto.step(sinceLast, self.file is not None, xp.getDatai(engines) == 0,
                                xp.getDataf(agl), xp.getDataf(speed),
                                xp.getDatai(paused) != 0 or xp.getDatai(replay) != 0)
        if action == AutoRecord.START:
            self.start_recording()
        elif action == AutoRecord.STOP:
            self.stop_recording()
        return 1.0

    def _read_recording(self, refCon):
        return int(self.file is not None)

    def _read_auto(self, refCon):
        return int(self.auto.enabled)

    def _write_auto(self, refCon, value):
        self.auto.enabled = bool(value)

    # --- commands -----------------------------------------------------------

    def on_toggle(self, commandRef, phase, refCon):
        if phase == xp.CommandBegin:
            if self.file is None:
                self.start_recording()
            else:
                self.auto.stopped_by_hand()
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
        self.xpg_refs = [(self.getters[kind], xp.findDataRef(name), _spec(column))
                         for column, name, kind in XPG_DATAREFS]
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
        # Paused or in replay, a row says nothing the tools keep (they drop such rows), and a
        # paused sim left open filled more than half of some logs.
        if xp.getDatai(self.paused_ref) or xp.getDatai(self.replay_ref):
            return -1
        values = [_fmt(get(ref), spec) for get, ref, spec in self.state_refs]
        values += [_fmt(v) for v in self.pre_forces]
        values += [_fmt(xp.getDataf(ref)) for ref in self.force_refs]
        values.append(str(self.mark))
        world = _alex_world()
        if world is None:
            values += [""] * len(ALEX_FIELDS)
        else:
            values += [_fmt(getattr(world, attr, None)) for _, attr in ALEX_FIELDS]
        values += [_fmt(get(ref), spec) if ref is not None else "" for get, ref, spec in self.xpg_refs]
        self.buffer.append(",".join(values) + "\n")
        if len(self.buffer) >= FLUSH_EVERY_ROWS:
            self.flush()
        return -1
