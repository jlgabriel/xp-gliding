"""Does XP12's wind carry the particles of a cloud, and does a cloud stay whole in wind?

Usage (X-Plane running with the xp-gliding plugin):
    python tools/cloudlab/fly_drag.py [--wind-kt 25] [--seconds 240] [--every 60] [--moving] [--shear]

A straight flight across a wind from the east, with screenshots from the front. By default
`wind_enabled` is off, so the emitters stay where they are and any stretch of a cloud along the
wind is the wind moving the particles. With --moving the emitters go with the wind as in normal
use, and a cloud should stay whole. --shear makes the wind grow with height, reaching about
--wind-kt at the clouds, while the emitters travel at the wind of the glider. If the particles
travelled at the wind of the clouds, a cloud would stretch; the flights saw no such stretch, and
the particles appear to move at about the wind at the aircraft (flown 2026-11-06). Compare with the
same flight at --wind-kt 0.

Measurement tool, not part of the plugin. License: GPL-3.0-or-later.
"""

import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, os.path.join(REPO, "tools", "testpilot"))

from airstart import KHOB, air_start, weather  # noqa: E402
from pilot import Pilot, take_over_logger  # noqa: E402
from xpweb import XPlaneWebAPI  # noqa: E402

SCREENSHOT = "sim/operation/screenshot"
FRONT_VIEW, COCKPIT_VIEW = "sim/view/forward_with_nothing", "sim/view/3d_cockpit_cmnd_look"
WIND_ENABLED = "xp_gliding/wind_enabled"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--wind-kt", type=float, default=25.0)
    parser.add_argument("--seconds", type=float, default=240.0)
    parser.add_argument("--every", type=float, default=60.0)
    parser.add_argument("--moving", action="store_true", help="emitters carried by the wind too")
    parser.add_argument("--shear", action="store_true", help="wind growing with height")
    args = parser.parse_args(argv)
    api = XPlaneWebAPI(timeout=30.0)
    lat, lon, elev = KHOB
    # Layers in feet above the field. The glider flies near 4300 ft and the clouds' base is near 4900.
    layers = ((500.0, 1.0), (3000.0, 1.0), (6000.0, 1.0), (12000.0, 1.0))
    if args.shear:
        layers = ((500.0, 0.2), (3000.0, 0.5), (6000.0, 1.2), (12000.0, 2.0))
    wind = [(elev / 0.3048 + alt, args.wind_kt * gain, 90.0, 0.0) for alt, gain in layers] if args.wind_kt > 0.0 else []
    air_start(api, elev + 1300.0, 90.0, 0.0, lat, lon, wx=weather(lat, lon, elev, wind=wind))
    # Plugins' datarefs reach the web API only once a flight is loaded.
    api.set(WIND_ENABLED, 1 if args.moving else 0)
    try:
        take_over_logger(api)
        state = {"next": 30.0}

        def on_step(v, pilot):
            api_view = pilot.flown < 1.0
            if api_view:
                api.command(FRONT_VIEW)
            if pilot.flown >= state["next"]:
                state["next"] = pilot.flown + args.every
                api.command(FRONT_VIEW)
                api.command(SCREENSHOT)
                print(f"{pilot.flown:5.0f} s: screenshot", flush=True)

        reason, _ = Pilot(api).run(90.0, args.seconds, quiet=True, on_step=on_step)
        print(reason)
    finally:
        api.command(COCKPIT_VIEW)
        api.set(WIND_ENABLED, 1)


if __name__ == "__main__":
    main()
