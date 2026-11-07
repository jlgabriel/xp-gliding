"""What X-Plane's weather offers to work out a cloud base from: read, not flown.

Usage (X-Plane running):
    python tools/testpilot/read_weather.py [--wait 40]

Air starts at Santiago and Hobbs under real weather, and at Hobbs under X-Plane's calm default and
a custom cumulus, then prints the layers of temperature and dew point, the ground's, the
cloud layers and the cloud base the parcel rule gives (`engine.day`). Reads datarefs only, since
the weather API is not needed for any of it. Measurement tool, not part of the plugin.
License: GPL-3.0-or-later.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from airstart import KHOB, air_start, weather  # noqa: E402
from xp_gliding.engine.day import at_height, cloud_base_above_ground_m, known_layers  # noqa: E402
from xpweb import XPlaneWebAPI  # noqa: E402

SANTIAGO = (-33.46, -70.55, 560.0)
A = "sim/weather/aircraft/"
R = "sim/weather/region/"
POS = "sim/flightmodel/position/"


def read(api, label):
    agl, msl = api.get(POS + "y_agl"), api.get(POS + "elevation")
    ground = msl - agl
    heights = api.get(R + "temperature_altitude_msl_m")
    temps, dews = api.get(A + "temperatures_aloft_deg_c"), api.get(A + "dewpoint_deg_c")
    t, td = at_height(ground, heights, temps), at_height(ground, *known_layers(heights, dews))
    print(f"== {label}: source {api.get(R + 'weather_source')}, real {api.get('sim/weather/use_real_weather_bool')}, ground {ground:.0f} m")
    print("  height " + " ".join(f"{h:6.0f}" for h in heights[:8]))
    print("  temp   " + " ".join(f"{x:6.1f}" for x in temps[:8]))
    print("  dew    " + " ".join(f"{x:6.1f}" for x in dews[:8]))
    print(f"  at the ground: {t:.1f} C, dew {td:.1f} C -> base {cloud_base_above_ground_m(t, td):.0f} m above it, "
          f"{ground + cloud_base_above_ground_m(t, td):.0f} m MSL")
    kinds, cover = api.get(A + "cloud_type"), api.get(A + "cloud_coverage_percent")
    bases, tops = api.get(A + "cloud_base_msl_m"), api.get(A + "cloud_tops_msl_m")
    for i in range(3):
        print(f"  clouds {i}: type {kinds[i]:.0f} cover {cover[i]:5.1f} base {bases[i]:6.0f} top {tops[i]:6.0f} m MSL")
    print(f"  native thermal rate: region {api.get(R + 'thermal_rate_ms'):.2f}, aircraft {api.get(A + 'thermal_rate_ms'):.2f}", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--wait", type=float, default=40.0)
    parser.add_argument("--only", default="", help="only the cases whose label has this text")
    args = parser.parse_args()
    api = XPlaneWebAPI(timeout=30.0)
    lat, lon, elev = KHOB
    cases = (("Hobbs, calm default", (lat, lon, elev), None),
             ("Hobbs, custom cumulus at 2500 m MSL", (lat, lon, elev),
              weather(lat, lon, elev, clouds=(("cumulus", 0.4, 2500.0 / 0.3048, 3500.0 / 0.3048),))),
             ("Santiago, real weather", SANTIAGO, "use_real_weather"),
             ("Hobbs, real weather", (lat, lon, elev), "use_real_weather"))
    for label, (la, lo, el), wx in cases:
        if args.only not in label:
            continue
        air_start(api, el + 1500.0, 90.0, 90.0, la, lo, wx=wx, thermal_ms=None)
        api.command("sim/operation/pause_on")
        time.sleep(args.wait)
        read(api, label)
        time.sleep(args.wait)
        read(api, label + ", later")
    api.command("sim/operation/pause_off")


if __name__ == "__main__":
    main()
