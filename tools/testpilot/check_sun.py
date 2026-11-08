"""Our sun against X-Plane's: the elevation `engine.sun` works out, and `sun_pitch_degrees`.

Usage (X-Plane running, any aircraft, anywhere):
    python tools/testpilot/check_sun.py            # now
    python tools/testpilot/check_sun.py --sweep    # every hour of the day, then the time put back

The plugin needs no part in it: both elevations come from X-Plane's date, time and place.
`--sweep` writes `sim/time/zulu_time_sec`, which moves X-Plane's clock. Measurement tool, not part
of the plugin. License: GPL-3.0-or-later.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from xp_gliding.engine.field import sky_time  # noqa: E402
from xp_gliding.engine.sun import sun_elevation_deg  # noqa: E402
from xpweb import XPlaneWebAPI  # noqa: E402

NAMES = ("sim/flightmodel/position/latitude", "sim/flightmodel/position/longitude",
         "sim/time/local_date_days", "sim/time/zulu_time_sec", "sim/time/local_time_sec",
         "sim/graphics/scenery/sun_pitch_degrees")


def compare(api):
    lat, lon, day, zulu, local, xplane = (api.get(name) for name in NAMES)
    ours = sun_elevation_deg(lat, lon, int(day), sky_time(zulu, local))
    print(f"day {int(day):3d}  local {local / 3600:5.2f} h  zulu {zulu / 3600:5.2f} h  "
          f"X-Plane {xplane:6.2f}  ours {ours:6.2f}  difference {ours - xplane:+5.2f} deg")
    return ours - xplane


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sweep", action="store_true", help="every hour of the day")
    args = parser.parse_args()
    api = XPlaneWebAPI(timeout=60.0)
    lat, lon = api.get(NAMES[0]), api.get(NAMES[1])
    print(f"at {lat:.4f}, {lon:.4f}")
    if not args.sweep:
        compare(api)
        return
    start = api.get("sim/time/zulu_time_sec")
    worst = 0.0
    try:
        for hour in range(24):
            api.set("sim/time/zulu_time_sec", (start + hour * 3600.0) % 86400.0)
            time.sleep(1.0)
            worst = max(worst, abs(compare(api)))
    finally:
        api.set("sim/time/zulu_time_sec", start)
    print(f"largest difference {worst:.2f} deg")


if __name__ == "__main__":
    main()
