"""Is a cloud worth flying to? Offline: the climb under clouds against any other thermal.

Usage:
    python tools/engine_plots/cloud_climb.py [--seed 1] [--wstar 3] [--zi 2000]
        [--hour 19.1] [--day 306] [--range 8000]

Takes every thermal alive within range of KHOB, and those with a formed cloud
(`engine/clouds.py`, what a pilot can see). For each, at a few heights, the lift over a
circle centred on the thermal, minus the ASK 21's sink in that turn, as in
`circle_climb.py`: perfect centring, in this turn, no search. Prints the median and
90th percentile climb and the share that give more than 0, 0.5 and 1 m/s.

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
from xp_gliding.engine import clouds as cl  # noqa: E402
from xp_gliding.engine.field import FieldConfig, ThermalField  # noqa: E402
from xp_gliding.engine.geo import LocalFrame  # noqa: E402

TURNS = ((35.0, 90.0), (45.0, 85.0))
HEIGHTS = (500.0, 800.0, 1100.0, 1400.0)


def row(label, climbs):
    climbs = sorted(climbs)
    n = len(climbs)
    if not n:
        return
    print(f"| {label} | {n} | {statistics.median(climbs):+.2f} | {climbs[int(0.9 * n)]:+.2f} "
          f"| {sum(c > 0.0 for c in climbs) / n:.0%} | {sum(c > 0.5 for c in climbs) / n:.0%} "
          f"| {sum(c > 1.0 for c in climbs) / n:.0%} |")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--wstar", type=float, default=3.0)
    parser.add_argument("--zi", type=float, default=2000.0)
    parser.add_argument("--hour", type=float, default=19.1)
    parser.add_argument("--day", type=int, default=306)
    parser.add_argument("--range", type=float, default=8000.0)
    args = parser.parse_args(argv)
    t = args.hour * 3600.0
    frame = LocalFrame(KHOB_LAT, KHOB_LON)
    field = ThermalField(FieldConfig(seed=args.seed, day=args.day, range_m=args.range), frame)
    field.update(t, KHOB_LAT, KHOB_LON)
    params = cl.CloudParams()
    alive = [th for th, _ in field.alive_within(0.0, 0.0, t, args.range)]
    formed = []
    for th in alive:
        if cl.carries_cloud(th, params):
            start, stop = cl.feeding_window(th, params)
            if start + 0.5 * params.ttl_s <= t < stop:
                formed.append(th)
    print(f"{len(alive)} thermals alive within {args.range / 1000:.0f} km, {len(formed)} with a formed cloud")
    print("\n| Thermals, height AGL, turn | Count | Climb, median (m/s) | p90 | > 0 | > 0.5 | > 1 |")
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for bank, kmh in TURNS:
        for z in HEIGHTS:
            sigma = density_ratio(KHOB_ELEV + z)
            tas = kmh / 3.6 / math.sqrt(sigma)
            radius = tas * tas / (G * math.tan(math.radians(bank)))
            sink = polar_sink(kmh, tas, bank) + TURN_SINK_EXTRA
            for label, thermals in (("all", alive), ("under a cloud", formed)):
                climbs = [circle_mean(field, th.e, th.n, z, t, args.wstar, args.zi, radius) - sink
                          for th in thermals]
                row(f"{label}, {z:.0f} m, {bank:.0f}° {kmh:.0f} km/h", climbs)


if __name__ == "__main__":
    main()
