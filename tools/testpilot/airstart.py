"""Start a test flight in the air through the Flight Initialization API.

Usage:
    python tools/testpilot/airstart.py [--msl 2800] [--kmh 90] [--heading 0]

Replaces the current flight with the Laminar ASK 21 flying over Hobbs, NM
(KHOB, where the first measurements were flown) at the given altitude and airspeed, in calm, clear
weather at local noon, and sets the native thermal rate to zero. Matches the
conditions the still-air polar was measured in (`polar.py`).

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
# Payload per station (kg). Without it the Flight Initialization API loads the
# ASK 21 empty (360.6 kg, CG far aft: it pitches up with full forward stick;
# seen 2026-11-03 after an X-Plane restart). The polar was flown at 541 kg total;
# 180.4 kg is split over the two seats ("Passenger front", "Pilot aft").
PAYLOAD_KG = [90.2, 90.2, 0, 0, 0, 0, 0, 0, 0]


def weather(lat, lon, elev_m, wind=(), clouds=(), thermal_fpm=0.0, temperature_c=None):
    """Custom weather for the Flight Initialization API.

    wind: (altitude ft MSL, speed kt, direction deg true, turbulence 0-1) per
    layer, up to 13; none means calm. clouds: (type, cover 0-1, base ft MSL,
    top ft MSL) per layer, up to 3. thermal_fpm: native "climb rate under
    cumulus". temperature_c: at the definition's elevation (default ISA).
    """
    layers = [{"altitude_in_feet_msl": alt, "speed_in_knots": kt,
               "direction_in_degrees_true": deg, "turbulence_ratio": turb}
              for alt, kt, deg, turb in wind]
    if not layers:
        layers = [{"altitude_in_feet_msl": elev_m / 0.3048 + 500.0, "speed_in_knots": 0.0,
                   "direction_in_degrees_true": 0.0, "turbulence_ratio": 0.0}]
    definition = {
        "latitude_in_degrees": lat,
        "longitude_in_degrees": lon,
        "elevation_in_meters": elev_m,
        "visibility_in_kilometers": 60.0,
        "clouds": [{"type": kind, "cover_ratio": cover, "bases_in_feet_msl": base,
                    "tops_in_feet_msl": top} for kind, cover, base, top in clouds],
        "wind": layers,
    }
    if temperature_c is not None:
        definition["temperature_in_degrees_celsius"] = temperature_c
    # X-Plane 12.4.3 rejects a custom definition unless the scenario keys are
    # present too (the article lists them only for presets).
    return {
        "vertical_speed_in_thermal_in_feet_per_minute": thermal_fpm,
        "wave_height_in_meters": 0,
        "wave_direction_in_degrees": 0,
        "terrain_state": "dry",
        "variation_across_region_percentage": 0,
        "evolution_over_time_enum": "static",
        "definition": definition,
    }


def calm_clear_weather(lat, lon, elev_m):
    return weather(lat, lon, elev_m)


def air_start(api, msl_m, kmh, heading, lat=KHOB[0], lon=KHOB[1], wx=None, hour=12.0,
              day_of_year=DAY_OF_YEAR, thermal_ms=0.0, settle_s=15.0, aircraft=ASK21,
              payload_kg=PAYLOAD_KG):
    """Start the ASK 21 in the air. wx: weather() result or "use_real_weather"
    (default: calm and clear at KHOB). thermal_ms is written to the regional
    native thermal rate once the flight has loaded (None: left alone). Once the
    datarefs appear, the sim is paused for settle_s so scenery and plugins finish
    loading before anything else is asked of X-Plane; paused, the glider keeps
    its air-start state instead of flying on its own (seen 2026-11-03: 15 s
    unpaused ended in a phugoid at 174 km/h). aircraft: path relative to the
    X-Plane folder; payload_kg: kg per payload station."""
    init = {
        "aircraft": {"path": aircraft},
        "weight": {"payload_weight_in_kilograms": list(payload_kg),
                   "fueltank_weight_in_kilograms": [0] * 9},
        "lle_air_start": {"latitude": lat, "longitude": lon, "elevation_in_meters": msl_m,
                          "heading_true": heading, "speed_in_meters_per_second": kmh / 3.6},
        "local_time": {"day_of_year": day_of_year, "time_in_24_hours": hour},
        "weather": wx or calm_clear_weather(lat, lon, KHOB[2]),
    }
    api.start_flight(init)
    # Loading takes a few seconds; the dataref list is empty until it is done.
    for _ in range(60):
        time.sleep(1.0)
        try:
            if thermal_ms is None:
                api.get("sim/weather/region/thermal_rate_ms")
            else:
                api.set("sim/weather/region/thermal_rate_ms", thermal_ms)
        except (RuntimeError, KeyError, OSError):
            continue
        if settle_s > 0.0:
            api.command("sim/operation/pause_on")
            time.sleep(settle_s)
            api.command("sim/operation/pause_off")
        return
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
