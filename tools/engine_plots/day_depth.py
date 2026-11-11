"""The depth of the moment through a day: how high and how well a glider climbs at each hour.

Usage:
    python tools/engine_plots/day_depth.py [--zi 2000] [--wstar 3] [--day 305] [--seeds 4]
        [--sample 15] [--sky NAME]

For Hobbs on that day, at each solar hour from 08:00 to 17:00, with the daily cycle's strength
(step A) and with and without its depth (step B, `FieldConfig.depth_cycle`): the zi of the moment,
then over a sample of the strong mature thermals alive within 5 km (life 0.2-0.7, the numbers that
carry a cloud, whether or not the morning leaves it blue) the best climb of an
ASK 21 in a centred circle at 0.4 of the thermal's own zi, the share that give more than 0.5 m/s
there, and the median height where the best of three turns stops climbing. Clouds: the share of
mature thermals with a cloud and the median base of those, over the ground. Flat ground, perfect
centring, no wind. Offline only.

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

from polar import polar_sink  # noqa: E402
from sky_choice import add_sky_args, sky_from_args  # noqa: E402
from xp_gliding.engine import sun  # noqa: E402
from xp_gliding.engine.clouds import CloudParams, carries_cloud  # noqa: E402
from xp_gliding.engine.field import FieldConfig, ThermalField  # noqa: E402
from xp_gliding.engine.geo import LocalFrame  # noqa: E402

G = 9.80665
LAT, LON, ELEV = 32.6875, -103.2170, 1115.0
TURNS = ((35.0, 90.0), (45.0, 85.0), (50.0, 80.0))
POINTS = 24
STEP_M = 50.0
WITHIN_M = 5000.0


def density_ratio(msl_m):
    return (1.0 - 2.25577e-5 * msl_m) ** 4.2559


def best_climb(field, th, z, t, wstar, zi):
    """The best of TURNS: circle-averaged lift less the ASK 21's sink in that turn."""
    sigma = density_ratio(ELEV + z)
    best = -math.inf
    for bank, ias in TURNS:
        tas = ias / 3.6 / math.sqrt(sigma)
        radius = tas * tas / (G * math.tan(math.radians(bank)))
        lift = sum(field.lift_at(th.e + radius * math.cos(a), th.n + radius * math.sin(a), z, t, wstar, zi)
                   for a in (2.0 * math.pi * k / POINTS for k in range(POINTS))) / POINTS
        best = max(best, lift - polar_sink(ias, tas, bank))
    return best


def ceiling(field, th, t, wstar, zi):
    """The highest height (m AGL) at which the best turn still climbs; 0 if none does."""
    top = 0.0
    z = STEP_M
    while z < th.zi(zi):
        if best_climb(field, th, z, t, wstar, zi) > 0.0:
            top = z
        z += STEP_M
    return top


def strong_mature(field, t, params):
    """The mature thermals within reach whose numbers carry a cloud, in a fixed order."""
    return sorted((th for th in field.alive(t) if math.hypot(th.e, th.n) <= WITHIN_M
                   and 0.2 <= (t - th.birth) / (th.death - th.birth) < 0.7 and carries_cloud(th, params)),
                  key=lambda th: (th.lat, th.lon, th.birth))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--zi", type=float, default=2000.0, help="the afternoon's, m")
    parser.add_argument("--wstar", type=float, default=3.0, help="the day's peak, m/s")
    parser.add_argument("--day", type=int, default=305)
    parser.add_argument("--seeds", type=int, default=4, help="skies pooled: seeds 1..N")
    parser.add_argument("--sample", type=int, default=15, help="thermals measured per sky and hour")
    add_sky_args(parser)
    args = parser.parse_args(argv)
    sky = sky_from_args(args)
    base_zzi = sky.cloud_base_zzi
    params = CloudParams()
    frame = LocalFrame(LAT, LON)
    print(f"Hobbs, day {args.day}, seeds 1-{args.seeds}, w* peak {args.wstar}, zi peak {args.zi:.0f} m, "
          f"cloud base at {base_zzi} zi")
    print()
    print("| Solar | zi now | w* now | Step | Sink between at 0.4 zi | Climb at 0.4 zi, median "
          "| > 0.5 m/s | Top, median | Thermals | With a cloud | Cloud base, median |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for hour in range(8, 18):
        t = sun.utc_for_solar(LON, args.day, hour * 3600.0)
        for depth in (False, True):
            climbs, tops, bases, strong_count, sink = [], [], [], 0, 0.0
            for seed in range(1, args.seeds + 1):
                field = ThermalField(FieldConfig(seed=seed, day=args.day, zi_m=args.zi, sky=sky,
                                                 range_m=WITHIN_M + 2000.0, sun_min_deg=sun.SUN_MIN_DEG,
                                                 depth_cycle=depth), frame)
                field.update(t, LAT, LON)
                wstar = args.wstar * field.cycle.strength_share(LAT, LON, t)
                zi_now = args.zi * field.cycle.depth_share(LAT, LON, t)
                if wstar <= 0.0:
                    break
                z_sink = 0.4 * (zi_now if depth else args.zi)
                sink = field.environment_sink(z_sink, wstar, args.zi * field.depth_share) * field.sink_share
                strong = strong_mature(field, t, params)
                strong_count += len(strong)
                picked = strong[::max(1, len(strong) // args.sample)][:args.sample]
                climbs += [best_climb(field, th, 0.4 * th.zi(args.zi), t, wstar, args.zi) for th in picked]
                tops += [ceiling(field, th, t, wstar, args.zi) for th in picked]
                bases += [base_zzi * th.zi(args.zi) for th in strong
                          if not field.cycle.blue(th.lat, th.lon, th.birth, base_zzi)]
            step = "B" if depth else "A"
            if not climbs:
                print(f"| {hour:02d}:00 | {zi_now:.0f} m | {wstar:.2f} | {step} | | no thermals | | | | | |")
                continue
            base_text = f"{statistics.median(bases):.0f} m" if bases else "blue"
            print(f"| {hour:02d}:00 | {zi_now:.0f} m | {wstar:.2f} | {step} | {sink:+.2f} | {statistics.median(climbs):+.2f} "
                  f"| {sum(c > 0.5 for c in climbs) / len(climbs):.0%} | {statistics.median(tops):.0f} m "
                  f"| {strong_count} | {len(bases) / strong_count:.0%} | {base_text} |")


if __name__ == "__main__":
    main()
