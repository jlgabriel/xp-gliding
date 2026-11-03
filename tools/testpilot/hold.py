"""Test pilot: hold an indicated airspeed with wings level in X-Plane.

Usage (X-Plane running, glider in flight, nobody touching the stick):
    python tools/testpilot/hold.py --kmh 90 --seconds 60 [--record] [--dry-run]
    python tools/testpilot/hold.py --release      # give the controls back

While it runs, X-Plane ignores the pilot's stick and rudder
(`sim/operation/override/override_joystick_pitch/roll/heading`) and the
script writes the yoke ratios over the web API's WebSocket each time X-Plane
pushes new values (~10 Hz). Control laws are in `control.py`.

The controls are given back at the end and whenever something is off: an
error, Ctrl-C, no data from X-Plane for 1 s, paused for more than 20 s, too
low, too steeply banked, or speed out of range. If the script is ever killed
hard (no chance to clean up), run it with --release; until then the stick
does nothing.

--record turns the flight logger on after --settle seconds and off at the end,
so the log holds only the steady part. --dry-run reads and computes but
never writes.

Measurement tool, not part of the plugin. License: GPL-3.0-or-later.
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from control import SpeedHold  # noqa: E402
from xpweb import XPlaneStream, XPlaneWebAPI  # noqa: E402

KT_TO_KMH = 1.852
MIN_AGL_M = 300.0
MAX_BANK_DEG = 35.0
IAS_RANGE_KMH = (55.0, 180.0)
STALE_S = 1.0
MAX_PAUSE_S = 20.0
THETA_REF_RANGE = (0.0, 5.0)  # deg
LOGGER_TOGGLE = "xp_gliding/flightlog/toggle"

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
Q = "sim/flightmodel/position/Q"
P = "sim/flightmodel/position/P"
VS = "sim/flightmodel/position/vh_ind"
AGL = "sim/flightmodel/position/y_agl"
SIM_TIME = "sim/time/total_flight_time_sec"
WATCHED = (PAUSED, IAS, THETA, PHI, Q, P, VS, AGL, SIM_TIME)


def release(api):
    """Give the stick back (REST, so it works even if the WebSocket is gone)."""
    for name in OVERRIDES:
        api.set(name, 0)
    print("controls released", flush=True)


def check_envelope(v):
    ias = v[IAS] * KT_TO_KMH
    if v[AGL] < MIN_AGL_M:
        raise RuntimeError(f"too low: {v[AGL]:.0f} m AGL")
    if abs(v[PHI]) > MAX_BANK_DEG:
        raise RuntimeError(f"bank too steep: {v[PHI]:.1f} deg")
    if not IAS_RANGE_KMH[0] < ias < IAS_RANGE_KMH[1]:
        raise RuntimeError(f"speed out of range: {ias:.1f} km/h")


def wait_until_flying(stream, timeout=10.0):
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


def fly(api, target_kmh, seconds, settle_s, dry_run, record):
    stream = XPlaneStream(api, WATCHED)
    took_controls = False
    recording = False
    try:
        stream.wait_for(WATCHED)
        v = wait_until_flying(stream)
        check_envelope(v)
        # Reference attitude: the current one, but never a dive or a zoom (an
        # untrimmed glider right after an air start noses over within seconds).
        # The command can move theta_span (12 deg) either way from it, so a
        # negative reference would cap the nose too low for slow speeds.
        theta_ref = max(THETA_REF_RANGE[0], min(THETA_REF_RANGE[1], v[THETA]))
        ctrl = SpeedHold(target_kmh, theta_ref, start_kmh=v[IAS] * KT_TO_KMH)
        print(f"start: IAS {v[IAS] * KT_TO_KMH:.1f} km/h, theta {v[THETA]:+.1f}, "
              f"phi {v[PHI]:+.1f}, AGL {v[AGL]:.0f} m -> target {target_kmh:.0f} km/h"
              f"{' (dry run)' if dry_run else ''}", flush=True)
        if not dry_run:
            stream.set_many({name: 1 for name in OVERRIDES})
            took_controls = True

        flown = 0.0  # unpaused sim seconds under control
        last_sim_t = v[SIM_TIME]
        last_seen = stream.updates
        paused_since = None
        next_print = 0.0
        while flown < seconds:
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
            flown += dt
            check_envelope(v)
            ias = v[IAS] * KT_TO_KMH
            pitch, roll, yaw = ctrl.step(dt, ias, v[THETA], v[Q], v[PHI], v[P])
            if not dry_run:
                stream.set_many({YOKE[0]: pitch, YOKE[1]: roll, YOKE[2]: yaw})
            if record and not recording and flown >= settle_s:
                api.command(LOGGER_TOGGLE)
                recording = True
                print("  flight log ON", flush=True)
            if flown >= next_print:
                next_print += 1.0
                print(f"{flown:5.1f}s IAS {ias:6.1f} | theta {v[THETA]:+5.1f} cmd {ctrl.theta_cmd:+5.1f} "
                      f"yoke {pitch:+.3f} trim {ctrl.trim:+.3f} | phi {v[PHI]:+5.1f} roll {roll:+.3f} "
                      f"| vs {v[VS]:+5.2f} AGL {v[AGL]:5.0f}", flush=True)
            for err in stream.errors():
                raise RuntimeError(f"X-Plane rejected a write: {err}")
    finally:
        if recording:
            api.command(LOGGER_TOGGLE)
            print("  flight log OFF", flush=True)
        if took_controls:
            release(api)
        stream.close()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Hold IAS and wings level via the X-Plane web API")
    parser.add_argument("--kmh", type=float, default=90.0, help="target IAS (km/h)")
    parser.add_argument("--seconds", type=float, default=30.0, help="sim seconds under control")
    parser.add_argument("--settle", type=float, default=20.0, help="seconds before --record starts")
    parser.add_argument("--dry-run", action="store_true", help="read and compute, never write")
    parser.add_argument("--record", action="store_true", help="flight log on for the steady part")
    parser.add_argument("--release", action="store_true", help="only give the controls back")
    args = parser.parse_args(argv)
    api = XPlaneWebAPI()
    if args.release:
        release(api)
        return
    fly(api, args.kmh, args.seconds, args.settle, args.dry_run, args.record)


if __name__ == "__main__":
    main()
