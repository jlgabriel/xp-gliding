"""Can an ASK 21 climb in the engine's thermals? Offline, with perfect centring.

Usage:
    python tools/engine_plots/circle_climb.py [--seed 1] [--wstar 3] [--zi 2000]
        [--hour 19.1] [--day 305]

For every thermal alive within 5 km of KHOB at that moment (zulu hour, day as
X-Plane's `local_date_days`), and at a few heights, the lift is averaged over a
circle centred on the thermal (the best a pilot can do for a round thermal),
with the radius the ASK 21 flies at each bank and IAS: R = TAS^2 / (g tan bank).
The climb is that average minus the glider's sink in the turn, from the test A
polar and its n^1.5 turn model plus the 0.18 m/s that the model fell short of
the measured circling sink at 35 deg and 90 km/h (phase1.md). Prints, per
height and turn, the median and 90th percentile climb and the share of thermals
that give more than 0, 0.5 and 1 m/s.

Measurement tool, not part of the plugin. License: GPL-3.0-or-later.
"""

import argparse
import math
import os
import statistics
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools", "testpilot"))

from polar import polar_sink  # noqa: E402
from xp_gliding.engine.field import FieldConfig, ThermalField  # noqa: E402
from xp_gliding.engine.geo import LocalFrame  # noqa: E402

G = 9.80665
KHOB_LAT, KHOB_LON, KHOB_ELEV = 32.6875, -103.2170, 1115.0
TURN_SINK_EXTRA = 0.18  # measured circling sink minus the turn model (35 deg, 90 km/h)
TURNS = ((35.0, 90.0), (40.0, 85.0), (45.0, 85.0), (45.0, 80.0), (50.0, 80.0))
HEIGHTS = (500.0, 800.0, 1100.0, 1400.0)
POINTS = 72


def density_ratio(msl_m):
    """ISA density ratio below 11 km."""
    return (1.0 - 2.25577e-5 * msl_m) ** 4.2559


def circle_mean(field, e, n, z, t, wstar, zi, radius):
    total = 0.0
    for k in range(POINTS):
        a = 2.0 * math.pi * k / POINTS
        total += field.lift_at(e + radius * math.cos(a), n + radius * math.sin(a), z, t, wstar, zi)
    return total / POINTS


def main(argv=None):
    parser = argparse.ArgumentParser(description="Circle-averaged climb in the engine's thermals")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--day", type=int, default=305)
    parser.add_argument("--hour", type=float, default=19.1, help="zulu hour")
    parser.add_argument("--wstar", type=float, default=3.0)
    parser.add_argument("--zi", type=float, default=2000.0)
    parser.add_argument("--within", type=float, default=5000.0, help="metres from KHOB")
    args = parser.parse_args(argv)

    frame = LocalFrame(KHOB_LAT, KHOB_LON)
    field = ThermalField(FieldConfig(seed=args.seed, day=args.day), frame)
    t = args.hour * 3600.0
    field.update(t, KHOB_LAT, KHOB_LON)
    alive = [th for th in field.alive(t) if math.hypot(th.e, th.n) <= args.within]
    print(f"seed {args.seed}, day {args.day}, {args.hour:.2f} h zulu, w* {args.wstar} m/s, "
          f"zi {args.zi:.0f} m: {len(alive)} thermals alive within {args.within / 1000:.0f} km")
    print("\n| AGL (m) | Bank (deg) | IAS (km/h) | Radius (m) | Sink (m/s) | Centre lift, median "
          "| Climb, median | Climb, p90 | > 0 | > 0.5 | > 1 |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for z in HEIGHTS:
        sigma = density_ratio(KHOB_ELEV + z)
        centre = [field.lift_at(th.e, th.n, z, t, args.wstar, args.zi) for th in alive]
        for bank, ias in TURNS:
            tas = ias / 3.6 / math.sqrt(sigma)
            radius = tas * tas / (G * math.tan(math.radians(bank)))
            sink = polar_sink(ias, tas, bank) + TURN_SINK_EXTRA
            climbs = sorted(circle_mean(field, th.e, th.n, z, t, args.wstar, args.zi, radius) - sink
                            for th in alive)
            share = [sum(c > x for c in climbs) / len(climbs) for x in (0.0, 0.5, 1.0)]
            print(f"| {z:.0f} | {bank:.0f} | {ias:.0f} | {radius:.0f} | {sink:.2f} "
                  f"| {statistics.median(centre):+.2f} | {statistics.median(climbs):+.2f} "
                  f"| {climbs[int(0.9 * (len(climbs) - 1))]:+.2f} "
                  f"| {share[0]:.0%} | {share[1]:.0%} | {share[2]:.0%} |")


if __name__ == "__main__":
    main()
