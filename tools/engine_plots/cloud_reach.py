"""Can a glider reach the clouds? How high each mature thermal with a cloud holds a circling glider.

Usage:
    python tools/engine_plots/cloud_reach.py [--sink 1.5] [--radius 105] [--days 20]

For the thermals with a cloud at full strength over a flat area, on many days: the height where
the lift around a centred circle equals the glider's sink in that turn, against the clouds' base.
The field is the whole sky, neighbours included. Prints the share that reach the base, and the
median and the worst of what is left. Offline: no simulator, and a perfectly centred circle.

Measurement tool, not part of the plugin. License: GPL-3.0-or-later.
"""

import argparse
import math
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from xp_gliding.engine.clouds import CloudParams, carries_cloud, cloud_scale  # noqa: E402
from xp_gliding.engine.field import SKIES, FieldConfig, ThermalField  # noqa: E402
from xp_gliding.engine.geo import LocalFrame  # noqa: E402

LAT, LON = 32.7, -103.2  # flat ground, at Hobbs; the place only changes the draw
T = 66000.0
RANGE_M = 8000.0
STEP_M = 25.0
RING = 12


def ceiling(field, th, t, sink, radius, wstar, zi):
    """The height (m AGL) where a circle around this thermal stops climbing; 0 if it never does."""
    top = 0.0
    z = 200.0
    while z < zi:
        lift = statistics.fmean(field.lift_at(th.e + radius * math.cos(a), th.n + radius * math.sin(a), z, t, wstar, zi)
                                for a in (2.0 * math.pi * k / RING for k in range(RING)))
        if lift > sink:
            top = z
        z += STEP_M
    return top


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sink", type=float, default=1.5, help="m/s, in the turn")
    parser.add_argument("--radius", type=float, default=105.0)
    parser.add_argument("--days", type=int, default=20)
    parser.add_argument("--wstar", type=float, default=3.0)
    parser.add_argument("--zi", type=float, default=2000.0)
    args = parser.parse_args()
    params = CloudParams()
    frame = LocalFrame(LAT, LON)
    print(f"sink {args.sink} m/s, circle of {args.radius:.0f} m, w* {args.wstar}, zi {args.zi:.0f} m")
    print("| Sky | Base | Thermals | Reach the base | Median top | 10th percentile | Top against cloud size |")
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for name in ("wide_carriers", "medium_carriers"):
        sky = SKIES[name]
        base = sky.cloud_base_zzi * args.zi
        tops, sizes = [], []
        for day in range(args.days):
            field = ThermalField(FieldConfig(seed=1, day=day, range_m=RANGE_M, sky=sky), frame)
            field.update(T, LAT, LON)
            for th in field.alive(T):
                tau = (T - th.birth) / (th.death - th.birth)
                if carries_cloud(th, params) and 0.2 <= tau < 0.7 and math.hypot(th.e, th.n) < RANGE_M:
                    tops.append(ceiling(field, th, T, args.sink, args.radius, args.wstar, args.zi))
                    sizes.append(cloud_scale(th))
        ranked = sorted(tops)
        small = [t for t, s in zip(tops, sizes) if s < 1.0]
        large = [t for t, s in zip(tops, sizes) if s >= 1.0]
        print(f"| {name} | {base:.0f} m | {len(tops)} | {sum(t >= base for t in tops) / len(tops):.0%} "
              f"| {statistics.median(tops):.0f} m | {ranked[len(ranked) // 10]:.0f} m "
              f"| under 1.0: {statistics.median(small) if small else 0:.0f} m, from 1.0: {statistics.median(large) if large else 0:.0f} m |")


if __name__ == "__main__":
    main()
