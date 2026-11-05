"""Is a cloud worth flying to? Offline: the climb under clouds against any other thermal.

Usage:
    python tools/engine_plots/cloud_climb.py [--sky NAME] [--set NAME=VALUE] [--seed 1]
        [--wstar 3] [--zi 2000] [--hour 19.1] [--day 306] [--range 8000] [--offset 0]

Takes every thermal alive within range of KHOB, and those with a formed cloud
(`engine/clouds.py`, what a pilot can see). For each, at a few heights, the lift over a
circle centred on the thermal, minus the ASK 21's sink in that turn, as in
`circle_climb.py`: perfect centring (or `--offset` metres off), in this turn, no search.
Prints the circle's mean lift, which says nothing about the glider, and the median and
90th percentile climb and the share that give more than 0, 0.5 and 1 m/s. Then how high the
climb goes under a formed cloud: the highest height with a climb above 0, against the base.

The turns are a shallow one for wide thermals (31 deg, 83 km/h) and the 45 deg of the earlier tables.

Measurement tool, not part of the plugin. License: GPL-3.0-or-later.
"""

import argparse
import math
import os
import statistics
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools", "testpilot"))

from circle_climb import G, KHOB_ELEV, KHOB_LAT, KHOB_LON, TURN_SINK_EXTRA, circle_mean, density_ratio  # noqa: E402
from polar import polar_sink  # noqa: E402
from sky_choice import add_sky_args, describe, sky_from_args  # noqa: E402
from xp_gliding.engine import clouds as cl  # noqa: E402
from xp_gliding.engine.field import FieldConfig, ThermalField  # noqa: E402
from xp_gliding.engine.geo import LocalFrame  # noqa: E402

TURNS = ((31.0, 83.0), (45.0, 85.0))
HEIGHTS = (500.0, 800.0, 1100.0, 1400.0)
TOP_STEP_M = 50.0


def turn(bank, kmh, z):
    """Radius (m) and sink (m/s) of this turn at height z."""
    tas = kmh / 3.6 / math.sqrt(density_ratio(KHOB_ELEV + z))
    return tas * tas / (G * math.tan(math.radians(bank))), polar_sink(kmh, tas, bank) + TURN_SINK_EXTRA


def row(label, radius, means, sink):
    climbs = sorted(m - sink for m in means)
    n = len(climbs)
    if not n:
        return
    print(f"| {label} | {radius:.0f} | {n} | {statistics.median(means):+.2f} | {statistics.median(climbs):+.2f} "
          f"| {climbs[int(0.9 * n)]:+.2f} | {sum(c > 0.0 for c in climbs) / n:.0%} "
          f"| {sum(c > 0.5 for c in climbs) / n:.0%} | {sum(c > 1.0 for c in climbs) / n:.0%} |")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    add_sky_args(parser)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--wstar", type=float, default=3.0)
    parser.add_argument("--zi", type=float, default=2000.0)
    parser.add_argument("--hour", type=float, default=19.1)
    parser.add_argument("--day", type=int, default=306)
    parser.add_argument("--range", type=float, default=8000.0)
    parser.add_argument("--offset", type=float, default=0.0, help="circle's centre this far from the thermal's")
    args = parser.parse_args(argv)
    sky = sky_from_args(args)
    t = args.hour * 3600.0
    frame = LocalFrame(KHOB_LAT, KHOB_LON)
    field = ThermalField(FieldConfig(seed=args.seed, day=args.day, range_m=args.range, sky=sky), frame)
    field.update(t, KHOB_LAT, KHOB_LON)
    params = cl.CloudParams()
    alive = [th for th, _ in field.alive_within(0.0, 0.0, t, args.range)]
    formed = []
    for th in alive:
        if cl.carries_cloud(th, params):
            start, stop = cl.feeding_window(th, params)
            if start + 0.5 * params.ttl_s <= t < stop:
                formed.append(th)
    print(f"sky: {describe(sky)}; offset {args.offset:.0f} m")
    print(f"{len(alive)} thermals alive within {args.range / 1000:.0f} km, {len(formed)} with a formed cloud")
    print("\n| Thermals, height AGL, turn | Radius (m) | Count | Circle's mean lift (m/s) | Climb, median (m/s) "
          "| p90 | > 0 | > 0.5 | > 1 |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")

    def mean_lift(th, z, radius):
        return circle_mean(field, th.e + args.offset, th.n, z, t, args.wstar, args.zi, radius)

    for bank, kmh in TURNS:
        for z in HEIGHTS:
            radius, sink = turn(bank, kmh, z)
            for label, thermals in (("all", alive), ("under a cloud", formed)):
                row(f"{label}, {z:.0f} m, {bank:.0f}° {kmh:.0f} km/h", radius,
                    [mean_lift(th, z, radius) for th in thermals], sink)

    base = cl.TOP_ZZI * args.zi
    print(f"\nHow high under a formed cloud (base at {base:.0f} m AGL, {len(formed)} clouds):")
    print("| Turn | Top of the climb, median (m AGL) | p10 | p90 | Below the base, median (m) | Never climbs |")
    print("| --- | --- | --- | --- | --- | --- |")
    for bank, kmh in TURNS:
        tops, never = [], 0
        for th in formed:
            top = None
            z = TOP_STEP_M
            while z < args.zi:
                radius, sink = turn(bank, kmh, z)
                if mean_lift(th, z, radius) - sink > 0.0:
                    top = z
                z += TOP_STEP_M
            if top is None:
                never += 1
            else:
                tops.append(top)
        if tops:
            tops.sort()
            print(f"| {bank:.0f}° {kmh:.0f} km/h | {statistics.median(tops):.0f} | {tops[int(0.1 * len(tops))]:.0f} "
                  f"| {tops[int(0.9 * len(tops))]:.0f} | {base - statistics.median(tops):.0f} | {never} of {len(formed)} |")
        else:
            print(f"| {bank:.0f}° {kmh:.0f} km/h | none | | | | {never} of {len(formed)} |")


if __name__ == "__main__":
    main()
