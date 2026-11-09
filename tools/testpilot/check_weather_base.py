"""Check the cloud base the plugin takes from X-Plane's weather, in two set days and a real one.

Usage (X-Plane running, xp-gliding installed):
    python tools/testpilot/check_weather_base.py [--only TEXT] [--watch 100]

For each case: an air start of the ASK 21, `xp_gliding/weather_base_enabled` turned on through its
dataref (not saved to config.json, and turned off again at the end), then the plugin's base, zi
and cloud level against the rule worked out here from the same layers (`engine.day`) and X-Plane's
own cloud layers. Under real weather it watches for `--watch` seconds, to see the second reading
about 90 s after the flight loaded. Measurement tool, not part of the plugin.
License: GPL-3.0-or-later.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from airstart import KHOB, air_start, weather  # noqa: E402
from xp_gliding.engine.day import weather_base_m  # noqa: E402
from xpweb import XPlaneWebAPI  # noqa: E402

SANTIAGO = (-33.46, -70.55, 560.0)
A = "sim/weather/aircraft/"
R = "sim/weather/region/"
P = "xp_gliding/"


def expected(api):
    """The base the rule gives over the ground under the glider now, m above it (None: no data)."""
    ground = api.get("sim/flightmodel/position/elevation") - api.get("sim/flightmodel/position/y_agl")
    base = weather_base_m(ground, api.get(R + "temperature_altitude_msl_m"),
                          api.get(A + "temperatures_aloft_deg_c"), api.get(A + "dewpoint_deg_c"))
    return ground, base


def report(api, label, t0):
    ground, base = expected(api)
    ours = api.get(P + "day/weather_base_m")
    level = api.get(P + "clouds/level_m")
    xp_bases = [b for b, c in zip(api.get(A + "cloud_base_msl_m"), api.get(A + "cloud_coverage_percent")) if c > 0]
    rule = "no data" if base is None else f"{base:.0f} m"
    print(f"  {label} t+{time.monotonic() - t0:4.0f} s: readings {api.get(P + 'day/weather_reads')}, "
          f"plugin base {ours:.0f} m AGL, zi {api.get(P + 'day/zi_m'):.0f} m, cloud level {level:.0f} m MSL; "
          f"ground {ground:.0f} m, rule now {rule}; X-Plane's cloud bases "
          f"{', '.join(f'{b:.0f}' for b in xp_bases) or 'none'} m MSL", flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", default="", help="only the cases whose label has this text")
    parser.add_argument("--watch", type=float, default=100.0, help="seconds to watch real weather")
    args = parser.parse_args()
    api = XPlaneWebAPI(timeout=30.0)
    lat, lon, elev = KHOB
    cases = (
        ("Hobbs, cumulus at 2500 m MSL", (lat, lon, elev),
         weather(lat, lon, elev, clouds=(("cumulus", 0.4, 2500.0 / 0.3048, 3500.0 / 0.3048),)), 20.0),
        ("Hobbs, cumulus at 3500 m MSL", (lat, lon, elev),
         weather(lat, lon, elev, clouds=(("cumulus", 0.4, 3500.0 / 0.3048, 4500.0 / 0.3048),)), 20.0),
        ("Santiago, real weather", SANTIAGO, "use_real_weather", args.watch),
    )
    try:
        for label, (la, lo, el), wx, watch in cases:
            if args.only not in label:
                continue
            print(f"== {label}", flush=True)
            air_start(api, el + 1500.0, 90.0, 90.0, la, lo, wx=wx, thermal_ms=None, settle_s=5.0)
            t0 = time.monotonic()
            api.set(P + "weather_base_enabled", 1)
            while time.monotonic() - t0 < watch:
                time.sleep(10.0)
                report(api, label, t0)
    finally:
        api.set(P + "weather_base_enabled", 0)
        api.command("sim/operation/pause_on")


if __name__ == "__main__":
    main()
