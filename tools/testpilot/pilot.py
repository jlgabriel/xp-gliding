"""Test pilot: fly X-Plane through the web API with the control laws in control.py.

`Pilot.run()` takes the stick (joystick override datarefs), holds an IAS with
the speed-by-pitch cascade and the bank asked for by a lateral guidance
(wings level, a course, a line over the ground, a circle), and writes the yoke
ratios over the WebSocket each time X-Plane pushes new values (~10 Hz).

The controls are given back at the end and whenever something is off: an
error, Ctrl-C, no data from X-Plane for 1 s, paused for more than 20 s, too
low, banked past bank_limit, or speed out of range. If a script is ever
killed hard (no chance to clean up), run `hold.py --release`; until then the
stick does nothing.

With record=True the flight logger is turned on after settle_s seconds and off
at the end, so the log holds only the steady part; run() returns the log's
file name.

Measurement tool, not part of the plugin. License: GPL-3.0-or-later.
"""

import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))  # repository root

from control import SpeedHold  # noqa: E402
from xp_gliding.engine.field import SKIES, SKY_NAMES  # noqa: E402
from xp_gliding.engine.geo import LocalFrame  # noqa: E402
from xpweb import XPlaneStream  # noqa: E402

KT_TO_KMH = 1.852
IAS_RANGE_KMH = (45.0, 180.0)  # an air start can begin below 55 km/h
STALE_S = 1.0
MAX_PAUSE_S = 20.0
THETA_REF_RANGE = (0.0, 5.0)  # deg
LOGGER_TOGGLE = "xp_gliding/flightlog/toggle"
LOGGER_AUTO = "xp_gliding/flightlog/auto"
LOGGER_RECORDING = "xp_gliding/flightlog/recording"
LOG_DIR = r"D:\Laminar\XP12-Last-Release\X-Plane 12\Output\xp-gliding\flightlogs"

OVERRIDES = ("sim/operation/override/override_joystick_pitch",
             "sim/operation/override/override_joystick_roll",
             "sim/operation/override/override_joystick_heading")
YOKE = ("sim/joystick/yoke_pitch_ratio",
        "sim/joystick/yoke_roll_ratio",
        "sim/joystick/yoke_heading_ratio")
PAUSED = "sim/time/paused"
IAS = "sim/flightmodel/position/indicated_airspeed"
THETA = "sim/flightmodel/position/theta"
PHI = "sim/flightmodel/position/phi"
# Pitch damping uses the Euler pitch rate, not the body rate Q: in a steady turn
# Q = g sin^2(bank) / (V cos(bank)) (~16 deg/s at 45 deg), which the damper took
# for a pitch-up and answered nose-down (checked live 2026-11-03).
Q = "sim/flightmodel/position/theta_dot"
P = "sim/flightmodel/position/P"
BETA = "sim/flightmodel/position/beta"
VS = "sim/flightmodel/position/vh_ind"
AGL = "sim/flightmodel/position/y_agl"
LAT = "sim/flightmodel/position/latitude"
LON = "sim/flightmodel/position/longitude"
ELEV = "sim/flightmodel/position/elevation"
VX = "sim/flightmodel/position/local_vx"
VZ = "sim/flightmodel/position/local_vz"
THERMAL = "sim/weather/aircraft/thermal_rate_ms"
TAS = "sim/flightmodel/position/true_airspeed"
TE = "sim/cockpit2/gauges/indicators/total_energy_fpm"
SIM_TIME = "sim/time/total_flight_time_sec"
WATCHED = (PAUSED, IAS, THETA, PHI, Q, P, BETA, VS, AGL, LAT, LON, ELEV, VX, VZ, THERMAL,
           TAS, TE, SIM_TIME)


def release(api):
    """Give the stick back (REST, so it works even if the WebSocket is gone)."""
    for name in OVERRIDES:
        api.set(name, 0)
    print("controls released", flush=True)


def track_deg(v):
    """Course over the ground from X-Plane's local velocity (x east, z south)."""
    return math.degrees(math.atan2(v[VX], -v[VZ])) % 360.0


def take_over_logger(api):
    """The logger records flights by itself: keep it from starting, end what it started."""
    try:
        api.set(LOGGER_AUTO, 0)
        if api.get(LOGGER_RECORDING):
            api.command(LOGGER_TOGGLE)
            time.sleep(0.1)
    except KeyError:  # a logger from before 0.5.0
        pass


def plugin_sky(api):
    """The sky the plugin is flying, so that an oracle sees the same lift."""
    try:
        return SKIES[SKY_NAMES[int(api.get("xp_gliding/sky_index"))]]
    except KeyError:
        print("the plugin does not say its sky (older than this tool): assuming the default", flush=True)
        return SKIES["default"]


def latest_log():
    try:
        names = sorted(n for n in os.listdir(LOG_DIR) if n.endswith(".csv"))
    except OSError:
        return None
    return names[-1] if names else None


class Pilot:
    def __init__(self, api, frame=None):
        """frame: LocalFrame for the guidance's east/north (default: first position)."""
        self.api = api
        self.frame = frame

    def wait_until_flying(self, stream, timeout=10.0):
        """Wait for unpaused flight with a real airspeed (after an air start X-Plane
        reports initialization values for a moment)."""
        end = time.monotonic() + timeout
        first_t = None
        while True:
            v, _ = stream.snapshot()
            ias = v[IAS] * KT_TO_KMH
            if not v[PAUSED] and IAS_RANGE_KMH[0] < ias < IAS_RANGE_KMH[1]:
                if first_t is None:
                    first_t = v[SIM_TIME]
                elif v[SIM_TIME] - first_t > 0.3:
                    return v
            if time.monotonic() > end:
                return v  # let check_envelope report what is wrong
            time.sleep(0.02)

    @staticmethod
    def check_envelope(v, min_agl, bank_limit):
        ias = v[IAS] * KT_TO_KMH
        if v[AGL] < min_agl:
            raise RuntimeError(f"too low: {v[AGL]:.0f} m AGL")
        if abs(v[PHI]) > bank_limit:
            raise RuntimeError(f"bank too steep: {v[PHI]:.1f} deg")
        if not IAS_RANGE_KMH[0] < ias < IAS_RANGE_KMH[1]:
            raise RuntimeError(f"speed out of range: {ias:.1f} km/h")

    def run(self, target_kmh, seconds, guidance=None, settle_s=20.0, record=False,
            min_agl=300.0, bank_limit=35.0, until=None, on_step=None, gains=None,
            dry_run=False, quiet=False):
        """Fly for `seconds` of unpaused sim time, or until until(v, pilot) is true.

        guidance.bank(track_deg, east_m, north_m) gives the bank command (None:
        wings level). on_step(v, pilot) runs every sample (for missions that
        switch guidance on the fly). Returns (reason, log file name or None).
        """
        api = self.api
        stream = XPlaneStream(api, WATCHED)
        took_controls = False
        recording = False
        log_name = self.log_name = None
        self.guidance = guidance
        reason = "time"
        try:
            stream.wait_for(WATCHED)
            v = self.wait_until_flying(stream)
            if self.frame is None:
                self.frame = LocalFrame(v[LAT], v[LON])
            self.check_envelope(v, min_agl, bank_limit)
            theta_ref = max(THETA_REF_RANGE[0], min(THETA_REF_RANGE[1], v[THETA]))
            ctrl = self.ctrl = SpeedHold(target_kmh, theta_ref, gains,
                                         start_kmh=v[IAS] * KT_TO_KMH)
            if not quiet:
                print(f"start: IAS {v[IAS] * KT_TO_KMH:.1f} km/h, theta {v[THETA]:+.1f}, "
                      f"phi {v[PHI]:+.1f}, AGL {v[AGL]:.0f} m -> target {target_kmh:.0f} km/h"
                      f"{' (dry run)' if dry_run else ''}", flush=True)
            if not dry_run:
                stream.set_many({name: 1 for name in OVERRIDES})
                took_controls = True

            self.flown = 0.0  # unpaused sim seconds under control
            last_sim_t = v[SIM_TIME]
            last_seen = stream.updates
            paused_since = None
            next_print = 0.0
            while self.flown < seconds:
                if stream.updates == last_seen:
                    _, stamp = stream.snapshot()
                    if time.monotonic() - stamp > STALE_S:
                        raise RuntimeError("no data from X-Plane for 1 s")
                    time.sleep(0.005)
                    continue
                last_seen = stream.updates
                v, _ = stream.snapshot()
                if v[PAUSED]:
                    paused_since = paused_since or time.monotonic()
                    if time.monotonic() - paused_since > MAX_PAUSE_S:
                        raise RuntimeError("paused for too long")
                    last_sim_t = v[SIM_TIME]
                    continue
                paused_since = None
                dt = v[SIM_TIME] - last_sim_t
                last_sim_t = v[SIM_TIME]
                if dt <= 0.0:
                    continue
                self.flown += dt
                self.east, self.north = self.frame.to_enu(v[LAT], v[LON])
                self.track = track_deg(v)
                if on_step:
                    on_step(v, self)
                if self.guidance is not None:
                    ctrl.phi_cmd = self.guidance.bank(self.track, self.east, self.north)
                else:
                    ctrl.phi_cmd = 0.0
                self.check_envelope(v, min_agl, bank_limit)
                ias = v[IAS] * KT_TO_KMH
                pitch, roll, yaw = ctrl.step(dt, ias, v[THETA], v[Q], v[PHI], v[P], v[BETA])
                if not dry_run:
                    stream.set_many({YOKE[0]: pitch, YOKE[1]: roll, YOKE[2]: yaw})
                if record and not recording and self.flown >= settle_s:
                    take_over_logger(api)
                    before = latest_log()
                    api.command(LOGGER_TOGGLE)
                    recording = True
                    for _ in range(50):  # the logger creates its file on the next frame
                        log_name = self.log_name = latest_log()
                        if log_name != before:
                            break
                        time.sleep(0.02)
                    if not quiet:
                        print(f"  flight log ON: {log_name}", flush=True)
                if not quiet and self.flown >= next_print:
                    next_print += 2.0
                    print(f"{self.flown:5.1f}s IAS {ias:6.1f} | theta {v[THETA]:+5.1f} "
                          f"yoke {pitch:+.3f} | phi {v[PHI]:+5.1f} cmd {ctrl.phi_cmd:+5.1f} "
                          f"roll {roll:+.3f} beta {v[BETA]:+5.1f} | trk {self.track:5.1f} "
                          f"| vs {v[VS]:+5.2f} th {v[THERMAL]:+5.2f} AGL {v[AGL]:5.0f}",
                          flush=True)
                for err in stream.errors():
                    raise RuntimeError(f"X-Plane rejected a write: {err}")
                if until and until(v, self):
                    reason = "until"
                    break
            self.last = v
        finally:
            if recording:
                api.command(LOGGER_TOGGLE)
                if not quiet:
                    print("  flight log OFF", flush=True)
            if took_controls:
                release(api)
            stream.close()
        return reason, log_name
