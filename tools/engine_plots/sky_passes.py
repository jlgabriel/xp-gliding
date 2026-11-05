"""A sky measured by straight passes, and core sizes against circles.

Usage:
    python tools/engine_plots/sky_passes.py [--sky NAME] [--set NAME=VALUE]

Straight lines of 5 km through the field at Santiago, counting each stretch with lift over
+1 m/s: how often, how wide and how strong.

Measurement tool, not part of the plugin. License: GPL-3.0-or-later.
"""

import argparse
import math
import os
import random
import statistics as st
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from sky_choice import add_sky_args, describe, sky_from_args  # noqa: E402
from xp_gliding.engine.field import FieldConfig, ThermalField  # noqa: E402
from xp_gliding.engine.geo import LocalFrame  # noqa: E402
from xp_gliding.engine.markers import core_of  # noqa: E402

WSTAR, ZI = 3.0, 2000.0
LAT, LON, T = -33.46, -70.65, 57600.0
STEP = 20.0
LIMIT = 1.0
MIN_WIDTH_M = 40.0


def q(values, p):
    values = sorted(values)
    return values[min(len(values) - 1, int(p * len(values)))] if values else float("nan")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n", maxsplit=1)[0])
    add_sky_args(parser)
    args = parser.parse_args(argv)
    sky = sky_from_args(args)
    print(f"sky: {describe(sky)}")
    frame = LocalFrame(LAT, LON)
    field = ThermalField(FieldConfig(seed=1, day=307, sky=sky), frame)
    for _ in range(200):
        if not field.update(T, LAT, LON):
            break
    rng = random.Random(3)
    for z in (500.0, 800.0, 1000.0, 1300.0):
        bumps, km = [], 0.0
        for _ in range(60):
            a, r = rng.uniform(0, 2 * math.pi), 3000.0 * math.sqrt(rng.random())
            e, n = r * math.cos(a), r * math.sin(a)
            h = rng.uniform(0, 2 * math.pi)
            cur = None
            for _ in range(int(5000 / STEP)):
                e += STEP * math.sin(h)
                n += STEP * math.cos(h)
                w = field.lift_at(e, n, z, T, WSTAR, ZI)
                if w > LIMIT:
                    if cur is None:
                        cur = {"m": 0.0, "peak": w}
                    cur["m"] += STEP
                    cur["peak"] = max(cur["peak"], w)
                elif cur:
                    bumps.append(cur)
                    cur = None
            km += 5.0
        wide = [b for b in bumps if b["m"] >= MIN_WIDTH_M]
        print(f"AGL {z:5.0f}: passes with lift over +{LIMIT:.0f}: {len(wide) / km:.2f} per km, width p10 "
              f"{q([b['m'] for b in wide], .1):.0f} median {q([b['m'] for b in wide], .5):.0f} p90 "
              f"{q([b['m'] for b in wide], .9):.0f} m, peak median {q([b['peak'] for b in wide], .5):+.1f} "
              f"p90 {q([b['peak'] for b in wide], .9):+.1f}")
        we = field.environment_sink(z, WSTAR, ZI)
        cores = [core_of(th, z, T, WSTAR, ZI, we) for th, _ in field.alive_within(0.0, 0.0, T, 5000.0)]
        usable = [c for c in cores if c[0] >= 2.0]
        print(f"           cores alive within 5 km {len(cores)}; r1 median {st.median(c[1] for c in cores if c[1] > 0):.0f} m; "
              f"at +2 or more: {len(usable)}, r1 median {st.median(c[1] for c in usable) if usable else 0:.0f} m, "
              f"p90 {q([c[1] for c in usable], .9):.0f} m")


if __name__ == "__main__":
    main()
