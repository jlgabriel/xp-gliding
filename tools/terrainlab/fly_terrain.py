"""Drive the terrain lab: reach and cost of terrain probes far from the glider.

Usage:
    python tools/terrainlab/fly_terrain.py install
    python tools/terrainlab/fly_terrain.py run
    python tools/terrainlab/fly_terrain.py clouds [--wind-kt 15] [--seconds 70] [--no-hills]

`install` copies the lab plugin to PythonPlugins/ (restart X-Plane afterwards). `run` starts a
flight over each site, pauses it, and runs the scans. Results stay in
Output/xp-gliding/terrainlab/, read with analyze_terrain.py.

`clouds` checks the height of clouds in the plugin itself: a flight toward the Andes (or over
Hobbs, with --no-hills) in a west wind, what the plugin reports, and screenshots.

The 6000 m flight in `run` leaves the cockpit view black after a few minutes: X-Plane's lack of
oxygen, noticed by Juan Luis on 2026-11-06. Outside views are not affected.

The sites: Hobbs (KHOB) is far inland and nearly flat, so a height near 0 there can only mean
the ground is not loaded. Santiago has the coast 100 km to the west and the Andes 40 km to the
east, for the water flag and for the rule on the height of clouds. Its grid is scanned from a
second flight 110 km away, to see whether the same point gives the same height.

Measurement tool, not part of the plugin. License: GPL-3.0-or-later.
"""

import argparse
import json
import os
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "testpilot"))

from airstart import air_start, weather  # noqa: E402
from xpweb import XPlaneWebAPI  # noqa: E402

XPLANE = os.environ.get("XPLANE_DIR", r"D:\Laminar\XP12-Last-Release\X-Plane 12")
FOLDER = os.path.join(XPLANE, "Output", "xp-gliding", "terrainlab")
PLUGIN = "PI_xpg_terrainlab.py"

KHOB = (32.6875, -103.2170, 1116.0, 2800.0)  # lat, lon, field elevation, flight height MSL
SCEL = (-33.46, -70.65, 500.0, 3000.0)
SCEL_FAR = (-33.46, -69.47, 3000.0, 6000.0)  # 110 km east of SCEL, over the Andes

DISTS_KM = (1, 2, 5, 10, 15, 20, 30, 40, 50, 60, 75, 100, 125, 150, 175, 200, 250, 300, 350, 400,
            500, 600, 800, 1000)


def rings(tag, site):
    return {"tag": tag, "kind": "rings", "lat": site[0], "lon": site[1], "bearings": 24,
            "dists_km": DISTS_KM}


def cost(tag, site):
    """Two kinds of use: along a cloud's drift, and scattered over the clouds' range."""
    return [{"tag": f"{tag}_lines", "kind": "lines", "lat": site[0], "lon": site[1], "lines": 200,
             "points": 40, "step_m": 500.0, "radius_km": 20.0, "seed": 1},
            {"tag": f"{tag}_scatter", "kind": "scatter", "lat": site[0], "lon": site[1],
             "points": 8000, "radius_km": 20.0, "seed": 2}]


def grid(tag, site):
    return {"tag": tag, "kind": "grid", "lat": site[0], "lon": site[1], "half_km": 60.0, "step_m": 500.0}


def wait_done(api, before, timeout_s=600.0):
    end = time.monotonic() + timeout_s
    while time.monotonic() < end:
        if api.get("xpg_terrainlab/errors"):
            raise SystemExit("the lab reported an error: see XPPython3Log.txt")
        if api.get("xpg_terrainlab/done") > before:
            return
        time.sleep(1.0)
    raise SystemExit("a scan did not finish in time")


def scan(api, plan):
    with open(os.path.join(FOLDER, "plan.json"), "w", encoding="utf-8") as f:
        json.dump(plan, f)
    before = api.get("xpg_terrainlab/done")
    t0 = time.monotonic()
    api.set("xpg_terrainlab/run", 1)
    wait_done(api, before)
    print(f"  {plan['tag']}: {time.monotonic() - t0:.0f} s", flush=True)


def fly(api, site, label):
    lat, lon, elev, msl = site
    print(f"{label}: starting a flight at {lat}, {lon}", flush=True)
    air_start(api, msl, 90.0, 0.0, lat=lat, lon=lon, wx=weather(lat, lon, elev), settle_s=5.0)
    api.command("sim/operation/pause_on")
    print(f"  aircraft ground height {api.get('sim/flightmodel/position/elevation') - api.get('sim/flightmodel/position/y_agl'):.1f} m MSL",
          flush=True)


def run(api):
    os.makedirs(FOLDER, exist_ok=True)
    fly(api, KHOB, "khob")
    scan(api, rings("khob_rings_t0", KHOB))
    time.sleep(60.0)
    scan(api, rings("khob_rings_t60", KHOB))
    for plan in cost("khob", KHOB):
        scan(api, plan)
    time.sleep(120.0)
    scan(api, rings("khob_rings_t200", KHOB))

    fly(api, SCEL, "scel")
    scan(api, rings("scel_rings_t0", SCEL))
    for plan in cost("scel", SCEL):
        scan(api, plan)
    scan(api, grid("scel_grid", SCEL))
    time.sleep(60.0)
    scan(api, rings("scel_rings_t60", SCEL))

    fly(api, SCEL_FAR, "scel_far")
    scan(api, grid("scel_grid_from_far", SCEL))
    api.command("sim/operation/pause_off")


def clouds(api, wind_kt, seconds, hills):
    lat, lon, elev, _ = SCEL if hills else KHOB
    msl = elev + 1800.0
    wind = [(alt, wind_kt, 270.0, 0.0) for alt in (elev / 0.3048 + 500.0, 15000.0, 25000.0)]
    air_start(api, msl, 95.0, 90.0, lat=lat, lon=lon, wx=weather(lat, lon, elev, wind=wind), settle_s=5.0)
    time.sleep(seconds)
    api.command("sim/operation/pause_on")
    for name in ("count", "created", "tiles_missing", "level_m", "raised", "base_max_m", "ground_misses",
                 "base_us", "base_us_max", "update_us_max", "plan_us"):
        print(f"  clouds/{name}: {api.get('xp_gliding/clouds/' + name):.1f}")
    print(f"  glider {api.get('sim/flightmodel/position/elevation'):.0f} m MSL, "
          f"{api.get('sim/flightmodel/position/y_agl'):.0f} m AGL")
    api.command("sim/view/chase")
    time.sleep(4.0)
    api.command("sim/operation/screenshot")
    time.sleep(2.0)
    api.command("sim/view/forward_with_panel")
    time.sleep(4.0)
    api.command("sim/operation/screenshot")
    time.sleep(2.0)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("what", choices=("install", "run", "clouds"))
    parser.add_argument("--wind-kt", type=float, default=15.0)
    parser.add_argument("--seconds", type=float, default=70.0)
    parser.add_argument("--no-hills", action="store_true")
    args = parser.parse_args(argv)
    if args.what == "clouds":
        clouds(XPlaneWebAPI(timeout=30.0), args.wind_kt, args.seconds, not args.no_hills)
        return
    if args.what == "install":
        dest = os.path.join(XPLANE, "Resources", "plugins", "PythonPlugins", PLUGIN)
        shutil.copy2(os.path.join(HERE, PLUGIN), dest)
        print("installed", dest, "- restart X-Plane to load it")
    else:
        run(XPlaneWebAPI(timeout=30.0))


if __name__ == "__main__":
    main()
