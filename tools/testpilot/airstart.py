"""Start a test flight in the air through the Flight Initialization API.

Usage:
    python tools/testpilot/airstart.py [--msl 2800] [--kmh 90] [--heading 0]

Replaces the current flight with the Laminar ASK 21 flying over Hobbs, NM
(KHOB, the phase 0 site) at the given altitude and airspeed, in calm, clear
weather at local noon, and sets the native thermal rate to zero. Matches the
still-air conditions of test A in docs/baseline.md.

Reference: https://developer.x-plane.com/article/flight-initialization-api/
(`lle_air_start`, custom weather definition). Measurement tool, not part of
the plugin. License: GPL-3.0-or-later.
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from xpweb import XPlaneWebAPI  # noqa: E402

ASK21 = "Aircraft/Laminar Research/Schleicher ASK 21/ASK21.acf"
KHOB = (32.6875, -103.2170, 1116.0)  # lat, lon, field elevation (m)
DAY_OF_YEAR = 305  # 2 November (0 = 1 January)


def calm_clear_weather(lat, lon, elev_m):
    # X-Plane 12.4.3 rejects a custom definition unless the scenario keys are
    # present too (the article lists them only for presets).
    return {
        "vertical_speed_in_thermal_in_feet_per_minute": 0,
        "wave_height_in_meters": 0,
        "wave_direction_in_degrees": 0,
        "terrain_state": "dry",
        "variation_across_region_percentage": 0,
        "evolution_over_time_enum": "static",
        "definition": {
        "latitude_in_degrees": lat,
        "longitude_in_degrees": lon,
        "elevation_in_meters": elev_m,
        "visibility_in_kilometers": 60.0,
        "clouds": [],
        "wind": [{"altitude_in_feet_msl": elev_m / 0.3048 + 500.0,
                  "speed_in_knots": 0.0, "direction_in_degrees_true": 0.0,
                  "turbulence_ratio": 0.0}],
    }}


def air_start(api, msl_m, kmh, heading, lat=KHOB[0], lon=KHOB[1]):
    init = {
        "aircraft": {"path": ASK21},
        "lle_air_start": {"latitude": lat, "longitude": lon, "elevation_in_meters": msl_m,
                          "heading_true": heading, "speed_in_meters_per_second": kmh / 3.6},
        "local_time": {"day_of_year": DAY_OF_YEAR, "time_in_24_hours": 12.0},
        "weather": calm_clear_weather(lat, lon, KHOB[2]),
    }
    api.start_flight(init)
    # Loading takes a few seconds; the dataref list is empty until it is done.
    for _ in range(60):
        time.sleep(1.0)
        try:
            api.set("sim/weather/region/thermal_rate_ms", 0.0)
            return
        except (RuntimeError, KeyError, OSError):
            continue
    raise TimeoutError("flight did not load within 60 s")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Start the ASK 21 in the air over KHOB")
    parser.add_argument("--msl", type=float, default=2800.0, help="altitude (m MSL)")
    parser.add_argument("--kmh", type=float, default=90.0, help="initial airspeed (km/h)")
    parser.add_argument("--heading", type=float, default=0.0, help="true heading (deg)")
    args = parser.parse_args(argv)
    api = XPlaneWebAPI(timeout=30.0)
    air_start(api, args.msl, args.kmh, args.heading)
    print(f"flying at {args.msl:.0f} m MSL over KHOB, {args.kmh:.0f} km/h, heading {args.heading:.0f}")


if __name__ == "__main__":
    main()
