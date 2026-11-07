"""A shift of X-Plane's local origin, flown by the test pilot.

Usage (X-Plane running with the xp-gliding plugin):
    python tools/testpilot/fly_origin.py [--short-m 4400] [--seconds 270] [--every 15]

Do the clouds stay where they are when X-Plane moves its local origin? Instances follow it with
`instanceSetAutoShift`, and nothing says what happens to particles already in the air. The markers
go through `worldToLocal` every second, so a column standing in its cloud before and after the
shift says the cloud stayed with the ground.

X-Plane's origin sits on a whole degree of longitude, and it moved one degree east when the glider
got about 61-63 km east of it (61.0 km and 62.9 km in the two tries of 2026-11-07, near Hobbs,
the second by sliding the glider). So: an air start, paused, the glider slid east in steps too
small for the plugin to take for a move on the map, to --short-m before the shift. Then straight
flight across it, with a screenshot every --every s and a few just after the shift. It stops
a minute after the shift, or at --seconds if there was none: then slide less far or more.

Under five minutes. Measurement tool, not part of the plugin. License: GPL-3.0-or-later.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

from airstart import KHOB, air_start  # noqa: E402
from pilot import Pilot, release, take_over_logger  # noqa: E402
from xpweb import XPlaneStream, XPlaneWebAPI  # noqa: E402

POS = "sim/flightmodel/position/"
LAT_REF, LON_REF, LOCAL_X, LON = POS + "lat_ref", POS + "lon_ref", POS + "local_x", POS + "longitude"
PAUSE = "sim/operation/pause_toggle"
PAUSED = "sim/time/paused"
SCREENSHOT = "sim/operation/screenshot"
FRONT_VIEW, COCKPIT_VIEW = "sim/view/forward_with_nothing", "sim/view/3d_cockpit_cmnd_look"
MARKERS = "xp_gliding/markers_enabled"
PLUGIN = "xp_gliding/"
WATCH = (LAT_REF, LON_REF, LOCAL_X, LON, PLUGIN + "clouds/count", PLUGIN + "clouds/created",
         PLUGIN + "clouds/destroyed", PLUGIN + "markers/count", PLUGIN + "lift_centre_ms",
         PLUGIN + "force_n", PLUGIN + "nearest/distance_m", PLUGIN + "frame_us",
         PLUGIN + "markers/probe_dy_m", PLUGIN + "markers/probe_local_distance_m",
         PLUGIN + "markers/probe_distance_m")
SHIFT_X_M = 61000.0  # east of the origin, measured: see the docstring
START_LON = -102.55
SLIDE_STEP_M = 2500.0  # the plugin takes 5 km between its slow updates for a move on the map
AFTER_SHIFT_S = 60.0
BURST_S = (1.0, 3.0, 6.0, 10.0)


def slide(api, target_x):
    x = api.get(LOCAL_X)
    print(f"air start: lon {api.get(LON):.4f}, ref {api.get(LAT_REF):.0f} {api.get(LON_REF):.0f}, x {x:.0f}", flush=True)
    if not api.get(PAUSED):
        api.command(PAUSE)
    while x + SLIDE_STEP_M < target_x:
        x += SLIDE_STEP_M
        api.set(LOCAL_X, x)
        time.sleep(2.0)
        x = api.get(LOCAL_X)
    api.set(LOCAL_X, target_x)
    time.sleep(2.0)
    print(f"slid: lon {api.get(LON):.4f}, x {api.get(LOCAL_X):.0f}, ref {api.get(LON_REF):.0f}", flush=True)
    api.command(PAUSE)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--short-m", type=float, default=2500.0)
    parser.add_argument("--seconds", type=float, default=270.0)
    parser.add_argument("--every", type=float, default=15.0)
    parser.add_argument("--kmh", type=float, default=90.0)
    args = parser.parse_args()
    api = XPlaneWebAPI()
    lat, _, elev = KHOB
    air_start(api, elev + 1000.0, args.kmh, 90.0, lat, START_LON)
    take_over_logger(api)
    markers_before = api.get(MARKERS)
    api.set(MARKERS, 1)
    api.command(FRONT_VIEW)
    stream = XPlaneStream(api, WATCH)
    stream.wait_for(WATCH)
    slide(api, SHIFT_X_M - args.short_m)
    state = {"next": 0.0, "printed": -5.0, "ref": None, "at": None, "burst": list(BURST_S)}

    def shot(pilot, why):
        api.command(SCREENSHOT)
        print(f"{pilot.flown:6.1f} s screenshot ({why})", flush=True)

    def on_step(v, pilot):
        x = stream.snapshot()[0]
        ref = (x[LAT_REF], x[LON_REF])
        if state["ref"] is None:
            state["ref"] = ref
        if ref != state["ref"] and state["at"] is None:
            state["at"] = pilot.flown
            print(f"{pilot.flown:6.1f} s SHIFT: ref {state['ref']} -> {ref}, lon {x[LON]:.4f}, x {x[LOCAL_X]:.0f}", flush=True)
            shot(pilot, "shift")
        if state["at"] is not None and state["burst"] and pilot.flown - state["at"] >= state["burst"][0]:
            shot(pilot, f"+{state['burst'].pop(0):.0f} s")
        if pilot.flown >= state["next"]:
            state["next"] = pilot.flown + args.every
            shot(pilot, "regular")
        if pilot.flown - state["printed"] >= 2.0:
            state["printed"] = pilot.flown
            print(f"{pilot.flown:6.1f} s lon {x[LON]:.4f} x {x[LOCAL_X]:7.0f} ref {x[LON_REF]:.0f} clouds {x[PLUGIN + 'clouds/count']:3.0f} "
                  f"created {x[PLUGIN + 'clouds/created']:4.0f} destroyed {x[PLUGIN + 'clouds/destroyed']:4.0f} "
                  f"markers {x[PLUGIN + 'markers/count']:2.0f} near {x[PLUGIN + 'nearest/distance_m']:6.0f} m "
                  f"lift {x[PLUGIN + 'lift_centre_ms']:+.2f} force {x[PLUGIN + 'force_n']:6.0f} N "
                  f"frame {x[PLUGIN + 'frame_us']:.0f} us", flush=True)

    def until(v, pilot):
        return state["at"] is not None and pilot.flown - state["at"] >= AFTER_SHIFT_S

    try:
        reason, log = Pilot(api).run(args.kmh, args.seconds, on_step=on_step, until=until, quiet=True, record=True)
        print("ended:", reason, "log:", log, "shift at", state["at"], flush=True)
    finally:
        stream.close()
        api.set(MARKERS, markers_before)
        api.command(COCKPIT_VIEW)
        release(api)


if __name__ == "__main__":
    main()
