"""Which wind should carry the sky in shear? Offline, with a simulated pilot.

Usage:
    python tools/engine_plots/shear_climb.py climb [--sky NAME] [--seeds 6] [--entry 500] [--wstar 3]
        [--carriers A,B,half,cap1] [--shears 1,2,5]
    python tools/engine_plots/shear_climb.py clouds [--sky NAME]
    python tools/engine_plots/shear_climb.py slip [--sky NAME]

The sky is carried by one wind, and the glider by the wind at its height, so in the sky's frame
the glider moves at the difference (notes/SPEC.md "Wind"):

    A   the wind at the glider. It never moves through the sky's frame. The emitters do not move
        with the particles, which X-Plane carries at the clouds' height: a cloud stretches.
    B   the wind at the clouds' base. Emitters and particles move together. The glider moves
        through the sky at W(z) - W(base), which is largest low down and nothing at the base.
    half, cap1   between them, offline only: half of the difference, or at most 1 m/s of it.

`climb`: `lean_climb.py`'s climb, a point on a circle with the sink of `circle_climb.py` and
made-up pilots, so compare the rows with each other and none of them with a flight.
`clouds`: what A does to clouds, by arithmetic: stretch and shift of the body over a particle's life.
`slip`: what B does to the circle, by arithmetic: metres per turn at each height.

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

from lean_climb import PILOTS, Sky, ZI, climb, formed_clouds, turn  # noqa: E402
from sky_choice import add_sky_args, describe, sky_from_args  # noqa: E402
from xp_gliding.engine.clouds import CloudParams  # noqa: E402
from xp_gliding.engine.wind import LEAN_FRACTION, Lean, _interpolate  # noqa: E402

KT = 0.514444
FT = 0.3048

# On top of lean_climb's three: a pilot who rolls out for up to 4 s of every turn (about 100 m at
# 90 km/h) and reads the vario as well as the good one. Harder work than anyone wants for long.
HARD = ("hard", 1, 100.0, 25.0, 60.0)
# The same, who notices the circle keeps sliding the same way and starts doing it by habit.
HABIT = ("hard, by habit", 1, 100.0, 25.0, 30.0, 0.3)
ALL_PILOTS = PILOTS + (HARD, HABIT)


def profile(name, layers):
    """layers: (height AGL in m, kt, degrees where it goes), ascending."""
    heights = tuple(h for h, _, _ in layers)
    east = tuple(kt * KT * math.sin(math.radians(to)) for _, kt, to in layers)
    north = tuple(kt * KT * math.cos(math.radians(to)) for _, kt, to in layers)
    return name, heights, east, north


# `fly_wind.py`'s SHEAR at 25 kt: layers of 5, 12.5, 30 and 50 kt at 500, 3000, 6000, 12000 ft.
STRONG = ((500 * FT, 5.0, 90.0), (3000 * FT, 12.5, 90.0), (6000 * FT, 30.0, 90.0), (12000 * FT, 50.0, 90.0))
SHEARS = (
    profile("Uniform 15 kt", ((0.0, 15.0, 90.0),)),
    profile("Gentle: 9 to 15 kt, 500 to 1500 m", ((500.0, 9.0, 90.0), (1500.0, 15.0, 90.0))),
    profile("Gentle backwards: 15 to 9 kt", ((500.0, 15.0, 90.0), (1500.0, 9.0, 90.0))),
    profile("Gentle turning: 15 kt, 25 deg", ((500.0, 15.0, 65.0), (1500.0, 15.0, 90.0))),
    profile("Middle: 3 to 15 kt, 500 to 1500 m", ((500.0, 3.0, 90.0), (1500.0, 15.0, 90.0))),
    profile("Strong: 5 to 50 kt, 500 to 12000 ft", STRONG),
)


def wind_at(z, heights, east, north):
    return _interpolate(z, heights, east), _interpolate(z, heights, north)


def carrier(name, heights, east, north, base):
    """slip(z): how fast the glider moves through the sky's frame, in this wind."""
    base_e, base_n = wind_at(base, heights, east, north)

    def to_base(z):
        e, n = wind_at(z, heights, east, north)
        return e - base_e, n - base_n

    if name == "A":
        return None
    if name == "B":
        return to_base
    if name == "half":
        return lambda z: tuple(0.5 * v for v in to_base(z))
    if name == "cap1":
        def capped(z):
            e, n = to_base(z)
            d = math.hypot(e, n)
            return (e, n) if d <= 1.0 else (e / d, n / d)
        return capped
    raise ValueError(name)


def chosen(args):
    if not args.shears:
        return SHEARS
    return tuple(SHEARS[int(k)] for k in args.shears.split(","))


def run_climb(args, sky):
    clouds = formed_clouds(args.seeds, sky)
    base = sky.cloud_base_zzi * ZI
    print(f"sky: {describe(sky)}")
    print(f"{len(clouds)} clouds; w* {args.wstar}, base {base:.0f} m, entry {args.entry:.0f} m\n")
    print("| Wind | Carried by | Lean f | Pilot | Gained, median (m) | p10 | Reached 300 m | Mean climb (m/s) "
          "| Off centre, median (m) | Recentring (m per turn) |")
    print("|" + " --- |" * 10)
    top = base + 100.0
    for name, heights, east, north in chosen(args):
        for how in args.carriers.split(","):
            slip = carrier(how, heights, east, north, base)
            for f in (0.0, LEAN_FRACTION):
                lean = Lean(f, smooth_s=0.0)
                lean.set_wind(heights, east, north, base, args.wstar, 0.0)
                view = Sky(lean, args.wstar)
                for pilot in ALL_PILOTS:
                    rows = []
                    for k, (field, th, t) in enumerate(clouds):
                        rng = random.Random(1000 * k + 7)  # the same entry for every case
                        rows.append(climb(field, th, t, view, args.entry, pilot, rng, top, slip))
                    gains = sorted(r[0] for r in rows)
                    print(f"| {name} | {how} | {f:g} | {pilot[0]} | {st.median(gains):.0f} "
                          f"| {gains[len(gains) // 10]:.0f} | {sum(g >= 300.0 for g in gains) / len(gains):.0%} "
                          f"| {st.median(r[1] for r in rows):+.2f} | {st.median(r[2] for r in rows):.0f} "
                          f"| {st.median(r[3] for r in rows):.0f} |", flush=True)


def difference(z, base, heights, east, north):
    e, n = wind_at(z, heights, east, north)
    base_e, base_n = wind_at(base, heights, east, north)
    return math.hypot(e - base_e, n - base_n)


def run_slip(args, sky):
    base = sky.cloud_base_zzi * ZI
    period = {z: 2.0 * math.pi / turn(z)[1] for z in (500.0, 800.0, 1100.0, 1400.0)}
    print(f"A turn at 35 deg and 90 km/h takes {period[500.0]:.0f} s at 500 m, {period[1400.0]:.0f} s at 1400 m.\n")
    print("| Wind | W(z) - W(base), m/s, and metres per turn, at 500 m | 800 m | 1100 m | 1400 m |")
    print("|" + " --- |" * 5)
    for name, heights, east, north in chosen(args):
        cells = []
        for z, t in period.items():
            d = difference(z, base, heights, east, north)
            cells.append(f"{d:.1f}, {d * t:.0f} m")
        print(f"| {name} | " + " | ".join(cells) + " |")


def run_clouds(args, sky):
    base = sky.cloud_base_zzi * ZI
    life = CloudParams().mean_ttl_s
    print(f"A particle's mean life is {life:.0f} s. Under A, with the glider at z and the cloud at the base "
          f"({base:.0f} m), a particle ends |W(base) - W(z)| x life from the emitter, and the body of the "
          "cloud is about half of that from its thermal.\n")
    print("| Wind | Glider at 500 m: stretch, shift of the body (m) | 800 m | 1100 m | 1400 m |")
    print("|" + " --- |" * 5)
    for name, heights, east, north in chosen(args):
        cells = []
        for z in (500.0, 800.0, 1100.0, 1400.0):
            d = difference(z, base, heights, east, north) * life
            cells.append(f"{d:.0f}, {d / 2:.0f}")
        print(f"| {name} | " + " | ".join(cells) + " |")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("what", choices=("climb", "clouds", "slip"))
    add_sky_args(parser)
    parser.add_argument("--seeds", type=int, default=6)
    parser.add_argument("--entry", type=float, default=500.0)
    parser.add_argument("--wstar", type=float, default=3.0)
    parser.add_argument("--carriers", default="A,B", help="A, B, half, cap1")
    parser.add_argument("--shears", default="", help="places in SHEARS, default all")
    args = parser.parse_args(argv)
    runs = {"climb": run_climb, "clouds": run_clouds, "slip": run_slip}
    runs[args.what](args, sky_from_args(args))


if __name__ == "__main__":
    main()
