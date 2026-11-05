"""How much can a thermal lean before a climbing glider loses it? Offline, with a simulated pilot.

Usage:
    python tools/engine_plots/lean_climb.py climb [--sky NAME] [--seeds 6] [--winds 7.7,12.9]
        [--fractions 0,0.05,0.1,0.2,0.3,0.5,1] [--wstar 3] [--max-slope 0.5] [--entry 500]
    python tools/engine_plots/lean_climb.py read [--sky NAME] ...
    python tools/engine_plots/lean_climb.py shear [--sky NAME] ...
    python tools/engine_plots/lean_climb.py section [--sky NAME] [--out plots]

The lean is `engine.wind.Lean`: at a height z below the clouds' base the lift's centre is
upwind of the cloud by
    L(z) = f * U / w* * (base - z)
in a uniform wind, with U the wind and w* the strength of the day. f = 1 is the rigid plume,
tilted by the rise time; a smaller f is a thermal that leans less than that. The wind here
blows toward the east.

`climb`: a thermal with a formed cloud, a glider entering it 60 m off centre at `--entry` m
AGL, all in the air's frame, where the only thing that moves the lift away from the glider
is the lean. Three pilots: one that never corrects, and two that shift the circle toward the
strongest part of it, as read from a vario with a lag, in a direction with an error. It is a
point on a circle (no flight model), with the sink of `circle_climb.py`, so compare the rows
with each other, not with a flight.

`read`: what a pilot sees. At a few heights, under each formed cloud: the lift below the
cloud's centre, the best lift met flying straight through the centre across the wind (a pilot
who ignores the wind), how far upwind of the centre the lift is met flying into the wind, and
whether the lift's centre is still under the cloud's body.

`shear`: the same climb in winds that change with height, with the lean of the engine.

`section`: a picture of the lift from the side, along the wind.

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
sys.path.insert(0, os.path.join(ROOT, "tools", "testpilot"))

from circle_climb import G, KHOB_ELEV, KHOB_LAT, KHOB_LON, TURN_SINK_EXTRA, density_ratio  # noqa: E402
from polar import polar_sink  # noqa: E402
from sky_choice import add_sky_args, describe, sky_from_args  # noqa: E402
from xp_gliding.engine import clouds as cl  # noqa: E402
from xp_gliding.engine.field import FieldConfig, ThermalField  # noqa: E402
from xp_gliding.engine.geo import LocalFrame  # noqa: E402
from xp_gliding.engine.wind import LEAN_FRACTION, LEAN_MAX_SLOPE, Lean  # noqa: E402

ZI = 2000.0
BANK_DEG, IAS_KMH = 35.0, 90.0
DT_S = 1.0
VARIO_LAG_S = 3.0
OFF_ENTRY_M = 60.0
MAX_S = 900.0  # a long climb
GIVE_UP_S = 90.0  # a pilot leaves after this long without gaining height
BODY_HALF_M = 425.0  # make_cloud_objs: half width x body width, at scale 1
GOOD_LIFT_MS = 1.0  # flying through, this much is "I felt something"
KT = 0.514444

# (name, turns between corrections, largest shift in m, error of the direction in deg)
PILOTS = (("never corrects", None, 0.0, 0.0),
          ("lazy", 2, 20.0, 45.0),
          ("good", 1, 40.0, 25.0))

# (name, heights above ground in m, east, north in m/s): winds that change with height.
SHEARS = (
    ("15 kt, uniform", (0.0,), (15 * KT,), (0.0,)),
    ("25 kt, uniform", (0.0,), (25 * KT,), (0.0,)),
    ("5 to 50 kt, 150 to 3650 m", (150.0, 3650.0), (5 * KT, 50 * KT), (0.0, 0.0)),
    ("10 to 30 kt, 500 to 1500 m", (500.0, 1500.0), (10 * KT, 30 * KT), (0.0, 0.0)),
    ("20 kt, turning 90 deg, 500 to 1500 m", (500.0, 1500.0), (20 * KT, 0.0), (0.0, 20 * KT)),
)


class Sky:
    """A field asked about through a lean, on a day of this strength."""

    def __init__(self, lean, wstar):
        self.lean = lean
        self.wstar = wstar

    def upwind_m(self, z):
        return math.hypot(*self.lean.at(z))

    def centre(self, e, n, z):
        """Where the lift's centre is at height z, for a thermal at (e, n) at the base."""
        de, dn = self.lean.at(z)
        return e + de, n + dn

    def lift(self, field, x, y, z, t):
        de, dn = self.lean.at(z)
        return field.lift_at(x - de, y - dn, z, t, self.wstar, ZI)


def uniform_sky(fraction, wind_ms, base_m, wstar, max_slope):
    lean = Lean(fraction, max_slope, smooth_s=0.0)
    lean.set_wind((0.0,), (wind_ms,), (0.0,), base_m, wstar, 0.0)
    return Sky(lean, wstar)


def turn(z):
    """Radius (m), angular speed (rad/s) and sink (m/s) of the circle at height z."""
    tas = IAS_KMH / 3.6 / math.sqrt(density_ratio(KHOB_ELEV + z))
    radius = tas * tas / (G * math.tan(math.radians(BANK_DEG)))
    return radius, tas / radius, polar_sink(IAS_KMH, tas, BANK_DEG) + TURN_SINK_EXTRA


def formed_clouds(seeds, sky, hour=19.1, day=306, range_m=8000.0):
    """(field, thermal, t) for each thermal with a formed cloud, before its decay, far from its end."""
    found = []
    t = hour * 3600.0
    params = cl.CloudParams()
    for seed in range(1, seeds + 1):
        frame = LocalFrame(KHOB_LAT, KHOB_LON)
        field = ThermalField(FieldConfig(seed=seed, day=day, range_m=range_m, sky=sky), frame)
        field.update(t, KHOB_LAT, KHOB_LON)
        for th, _ in field.alive_within(0.0, 0.0, t, range_m):
            if cl.carries_cloud(th, params):
                start, stop = cl.feeding_window(th, params)
                if start + 0.5 * params.ttl_s <= t < stop - 120.0:
                    found.append((field, th, t))
    return found


def climb(field, th, t0, sky, entry_m, pilot, rng, top_m):
    """Fly it: (height gained, mean climb, median distance from circle to lift's centre)."""
    _, every, max_shift, error_deg = pilot
    z = entry_m
    a = rng.uniform(0.0, 2.0 * math.pi)
    ce0, cn0 = sky.centre(th.e, th.n, z)
    cx, cy = ce0 + OFF_ENTRY_M * math.cos(a), cn0 + OFF_ENTRY_M * math.sin(a)
    theta = rng.uniform(0.0, 2.0 * math.pi)
    vario = None
    samples = []
    since_shift = 0.0
    best_z, best_t = z, t0
    away = []
    t = t0
    while t - t0 < MAX_S and t < th.death and z < top_m and z > 50.0:
        radius, omega, sink = turn(z)
        x, y = cx + radius * math.cos(theta), cy + radius * math.sin(theta)
        w = sky.lift(field, x, y, z, t)
        vario = w if vario is None else vario + (w - vario) * DT_S / VARIO_LAG_S
        samples.append((theta, vario))
        z += (w - sink) * DT_S
        theta += omega * DT_S
        t += DT_S
        since_shift += DT_S
        ce, cn = sky.centre(th.e, th.n, z)
        away.append(math.hypot(cx - ce, cy - cn))
        if z > best_z + 1.0:
            best_z, best_t = z, t
        elif t - best_t > GIVE_UP_S:
            break
        period = 2.0 * math.pi / omega
        if every is not None and since_shift >= every * period:
            # The first harmonic of the last turn, read from the lagging vario, corrected for
            # the lag by a pilot who knows it, with an error of its own.
            last = samples[-int(period / DT_S):]
            c = sum(v * math.cos(p) for p, v in last) * 2.0 / len(last)
            s = sum(v * math.sin(p) for p, v in last) * 2.0 / len(last)
            amp = math.hypot(c, s)
            if amp > 0.15:
                best = math.atan2(s, c) - omega * VARIO_LAG_S + math.radians(rng.gauss(0.0, error_deg))
                shift = min(max_shift, amp * 30.0)
                cx += shift * math.cos(best)
                cy += shift * math.sin(best)
            since_shift = 0.0
    gained = best_z - entry_m
    return gained, gained / max(best_t - t0, 1.0), st.median(away) if away else 0.0


def climb_row(label, sky, clouds, entry, top):
    for pilot in PILOTS:
        rows = []
        for k, (field, th, t) in enumerate(clouds):
            rng = random.Random(1000 * k + 7)  # the same entry for every lean and pilot
            rows.append(climb(field, th, t, sky, entry, pilot, rng, top))
        gains = sorted(r[0] for r in rows)
        print(f"| {label} | {sky.upwind_m(entry):.0f} | {pilot[0]} | {st.median(gains):.0f} "
              f"| {gains[len(gains) // 10]:.0f} | {st.median(r[1] for r in rows):+.2f} "
              f"| {sum(g >= 300.0 for g in gains) / len(gains):.0%} | {st.median(r[2] for r in rows):.0f} |")


CLIMB_COLUMNS = ("Upwind at entry (m) | Pilot | Gained, median (m) | p10 | Mean climb (m/s) | Reached 300 m "
                 "| Off centre, median (m) |")


def run_climb(args, sky):
    clouds = formed_clouds(args.seeds, sky)
    base = sky.cloud_base_zzi * ZI
    print(f"sky: {describe(sky)}")
    print(f"{len(clouds)} clouds; w* {args.wstar}, zi {ZI:.0f}, base {base:.0f} m, entry {args.entry:.0f} m, "
          f"{BANK_DEG:.0f} deg, {IAS_KMH:.0f} km/h\n")
    print("| Wind (m/s) | f | " + CLIMB_COLUMNS)
    print("|" + " --- |" * 9)
    # The top is a bit above the base, the same for all, so a climb that ends there is a full one.
    top = base + 100.0
    for wind in (float(x) for x in args.winds.split(",")):
        for f in (float(x) for x in args.fractions.split(",")):
            climb_row(f"{wind:.1f} | {f:g}", uniform_sky(f, wind, base, args.wstar, args.max_slope),
                      clouds, args.entry, top)


def run_shear(args, sky):
    clouds = formed_clouds(args.seeds, sky)
    base = sky.cloud_base_zzi * ZI
    print(f"sky: {describe(sky)}")
    print(f"{len(clouds)} clouds; w* {args.wstar}, base {base:.0f} m, entry {args.entry:.0f} m; "
          f"f {LEAN_FRACTION:g}, steepest {LEAN_MAX_SLOPE:g}\n")
    print("| Wind | " + CLIMB_COLUMNS)
    print("|" + " --- |" * 8)
    for name, heights, east, north in SHEARS:
        lean = Lean(smooth_s=0.0)
        lean.set_wind(heights, east, north, base, args.wstar, 0.0)
        climb_row(name, Sky(lean, args.wstar), clouds, args.entry, base + 100.0)
    print("\n| Wind | Lift's centre from the cloud, east and north (m), at 500 m | 800 m | 1100 m |")
    print("|" + " --- |" * 4)
    for name, heights, east, north in SHEARS:
        lean = Lean(smooth_s=0.0)
        lean.set_wind(heights, east, north, base, args.wstar, 0.0)
        cells = " | ".join("{:+.0f}, {:+.0f}".format(*lean.at(z)) for z in (500.0, 800.0, 1100.0))
        print(f"| {name} | {cells} |")


def best_along(sky, field, x0, y0, dx, dy, z, t, half_m=800.0, step_m=25.0):
    """Lift along a line through (x0, y0): the best, and where the first GOOD_LIFT_MS is met."""
    best, first = -9.0, None
    s = -half_m
    while s <= half_m:
        w = sky.lift(field, x0 + s * dx, y0 + s * dy, z, t)
        best = max(best, w)
        if first is None and w >= GOOD_LIFT_MS:
            first = s
        s += step_m
    return best, first


def run_read(args, sky_profile):
    clouds = formed_clouds(args.seeds, sky_profile)
    base = sky_profile.cloud_base_zzi * ZI
    print(f"sky: {describe(sky_profile)}")
    print(f"{len(clouds)} clouds; base {base:.0f} m\n")
    print("| Wind (m/s) | f | Height (m) | Upwind by design (m) | Below the cloud's centre, median (m/s) | "
          "Across the wind through the centre: best, median | Felt +1 | Into the wind: met upwind of "
          "the centre, median (m) | Lift's centre under the cloud |")
    print("|" + " --- |" * 9)
    for wind in (float(x) for x in args.winds.split(",")):
        for f in (float(x) for x in args.fractions.split(",")):
            sky = uniform_sky(f, wind, base, args.wstar, args.max_slope)
            for z in (500.0, 800.0, 1100.0):
                below, across, upwind = [], [], []
                for field, th, t in clouds:
                    below.append(sky.lift(field, th.e, th.n, z, t))
                    best, _ = best_along(sky, field, th.e, th.n, 0.0, 1.0, z, t)  # across: the wind is east
                    across.append(best)
                    # Flying west, into the wind, from downwind: s runs from east to west.
                    _, first = best_along(sky, field, th.e, th.n, -1.0, 0.0, z, t)
                    if first is not None:
                        upwind.append(first)
                under = sum(sky.upwind_m(z) <= BODY_HALF_M * cl.cloud_scale(th) for _, th, _ in clouds)
                print(f"| {wind:.1f} | {f:g} | {z:.0f} | {sky.upwind_m(z):.0f} | {st.median(below):+.2f} "
                      f"| {st.median(across):+.2f} | {sum(a >= GOOD_LIFT_MS for a in across) / len(across):.0%} "
                      f"| {st.median(upwind) if upwind else float('nan'):.0f} | {under / len(clouds):.0%} |")


def run_section(args, sky_profile):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np

    base = sky_profile.cloud_base_zzi * ZI
    clouds = formed_clouds(args.seeds, sky_profile)
    # The most typical cloud: the one whose lift at mid height is the median.
    mid = sorted(clouds, key=lambda c: c[0].lift_at(c[1].e, c[1].n, 800.0, c[2], args.wstar, ZI))
    field, th, t = mid[len(mid) // 2]
    xs = np.arange(-1400.0, 801.0, 20.0)
    zs = np.arange(50.0, base + 101.0, 25.0)
    panels = (("No lean", 0.0), ("15 kt", 15 * KT), ("25 kt", 25 * KT))
    fig, axes = plt.subplots(1, 3, figsize=(12, 4.4), sharey=True, constrained_layout=True)
    for ax, (title, wind) in zip(axes, panels):
        sky = uniform_sky(LEAN_FRACTION if wind else 0.0, wind, base, args.wstar, LEAN_MAX_SLOPE)
        lift = np.array([[sky.lift(field, th.e + x, th.n, z, t) for x in xs] for z in zs])
        mesh = ax.pcolormesh(xs, zs, np.clip(lift, 0.0, None), cmap="Blues", vmin=0.0, vmax=5.0, shading="auto")
        half = BODY_HALF_M * cl.cloud_scale(th)
        ax.fill_between([-half, half], base, base + 100.0, color="0.55", lw=0)
        ax.annotate("cloud", (0.0, base + 50.0), ha="center", va="center", color="white", fontsize=9)
        centre = [sky.centre(0.0, 0.0, z)[0] for z in zs]
        ax.plot(centre, zs, color="0.15", lw=1.5, ls="--")
        ax.set_title(title, loc="left", fontsize=11)
        ax.spines[["top", "right"]].set_visible(False)
        ax.tick_params(length=0)
    fig.supxlabel("Metres from the cloud's centre (the wind blows to the right)", fontsize=10)
    axes[0].set_ylabel("Height above ground (m)")
    fig.colorbar(mesh, ax=axes, label="Lift (m/s)", shrink=0.85)
    os.makedirs(args.out, exist_ok=True)
    path = os.path.join(args.out, "lean_section.png")
    fig.savefig(path, dpi=130)
    print(f"{path}: core {field.lift_at(th.e, th.n, 800.0, t, args.wstar, ZI):+.1f} m/s at 800 m, "
          f"cloud scale {cl.cloud_scale(th):.2f}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("what", choices=("climb", "read", "shear", "section"))
    add_sky_args(parser)
    parser.add_argument("--seeds", type=int, default=6)
    parser.add_argument("--winds", default="7.7,12.9")
    parser.add_argument("--fractions", default="0,0.05,0.1,0.2,0.3,0.5,1")
    parser.add_argument("--entry", type=float, default=500.0)
    parser.add_argument("--wstar", type=float, default=3.0)
    parser.add_argument("--max-slope", type=float, default=100.0, help="the steepest lean, m per m of height")
    parser.add_argument("--out", default="plots")
    args = parser.parse_args(argv)
    runs = {"climb": run_climb, "read": run_read, "shear": run_shear, "section": run_section}
    runs[args.what](args, sky_from_args(args))


if __name__ == "__main__":
    main()
