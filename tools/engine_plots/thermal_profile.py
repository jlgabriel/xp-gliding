"""Lift by distance from a thermal's centre: typical thermal and typical cloud carrier.

Usage:
    python tools/engine_plots/thermal_profile.py [--sky NAME] [--set NAME=VALUE]

Takes the median gains of the thermals alive around one place. Prints the profile of one
full-size thermal at several heights, its median lift by bands of distance at 550 m AGL, and
the mass balance.

Measurement tool, not part of the plugin. License: GPL-3.0-or-later.
"""

import argparse
import math
import os
import statistics as st
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from sky_choice import add_sky_args, describe, sky_from_args  # noqa: E402
from xp_gliding.engine import updraft  # noqa: E402
from xp_gliding.engine.clouds import CloudCatalog, CloudParams  # noqa: E402
from xp_gliding.engine.field import FieldConfig, ThermalField, carrier_flux_share, mean_flux_gain  # noqa: E402
from xp_gliding.engine.geo import LocalFrame  # noqa: E402

LAT, LON, T = -33.46, -70.65, 57600.0
WSTAR, ZI = 3.0, 2000.0
RADII = (0, 50, 90, 140, 200, 300, 400, 500)
BANDS_M = ((50, 100), (100, 150), (150, 200), (200, 300), (300, 500))


def lift(r, z, wg, rg, stretch, we):
    return updraft.updraft_velocity(r / stretch, z, ZI, WSTAR, wg, rg, we)


def half_peak(z, wg, rg, stretch, we):
    peak = lift(0.0, z, wg, rg, stretch, we)
    for r in range(0, 2000, 2):
        if lift(float(r), z, wg, rg, stretch, we) - we < 0.5 * (peak - we):
            return peak, r
    return peak, 2000


def band_mean(band, z, wg, rg, stretch, we):
    """Median over a band of distance."""
    lo, hi = band
    values = sorted(lift(lo + (hi - lo) * (k + 0.5) / 40.0, z, wg, rg, stretch, we) for k in range(40))
    return st.median(values)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n", maxsplit=1)[0])
    add_sky_args(parser)
    args = parser.parse_args(argv)
    sky = sky_from_args(args)
    print(f"sky: {describe(sky)}")

    config = FieldConfig(seed=1, day=307, sky=sky)
    frame = LocalFrame(LAT, LON)
    field = ThermalField(config, frame)
    for _ in range(200):
        if not field.update(T, LAT, LON):
            break
    catalog = CloudCatalog(config, frame, CloudParams())
    for _ in range(5000):
        if not catalog.update(T, LAT, LON):
            break
    carriers = list(catalog.thermals())
    alive = [th for th, _ in field.alive_within(0.0, 0.0, T, 5000.0)]
    keys = {(th.lat, th.lon) for th in carriers}
    blue = [th for th in alive if (th.lat, th.lon) not in keys]
    area = math.pi * 25.0
    near = sum(1 for th in alive if (th.lat, th.lon) in keys)
    print(f"alive within 5 km: {len(alive)} ({len(alive) / area:.2f}/km2), of them cloud carriers {near} "
          f"({near / area:.2f}/km2), blue {len(blue)} ({len(blue) / area:.2f}/km2)")
    print(f"mean flux of a drawn thermal: {mean_flux_gain(config):.3f}, as drawn "
          f"{math.exp(config.rgain_sigma ** 2):.3f}; carriers alone as drawn {carrier_flux_share(config):.3f}")

    kinds = [("carrier", st.median(t.wgain for t in carriers) * sky.carrier_gain,
              st.median(t.rgain for t in carriers), sky.carrier_stretch)]
    if blue:
        kinds.append(("blue", st.median(t.wgain for t in blue) * sky.blue_gain,
                      st.median(t.rgain for t in blue), sky.blue_stretch))
        strong = sorted(t.wgain * sky.blue_gain for t in blue)
        print(f"blue wgain with the profile: median {kinds[1][1]:.2f}, p90 {strong[int(0.9 * len(strong))]:.2f}")

    print("\n    z kind    |  r1   r2  half | " + " ".join(f"{r:5d}" for r in RADII) + " | surroundings")
    for z in (400.0, 550.0, 700.0, 1000.0, 1300.0):
        we = field.environment_sink(z, WSTAR, ZI)
        for name, wg, rg, stretch in kinds:
            r1, r2 = updraft.core_radii(z, ZI, rg)
            _, half = half_peak(z, wg, rg, stretch, we)
            vals = [lift(float(r), z, wg, rg, stretch, we) for r in RADII]
            print(f"{z:5.0f} {name:7s} | {r1 * stretch:3.0f} {r2 * stretch:4.0f} {half:5d} | "
                  + " ".join(f"{v:+5.1f}" for v in vals) + f" | {we:+.2f}")

    print("\nBy distance at 550 m AGL")
    print("| Distance (m) | Carrier |")
    print("| --- | --- |")
    _, wg, rg, stretch = kinds[0]
    we = field.environment_sink(550.0, WSTAR, ZI)
    peak, half = half_peak(550.0, wg, rg, stretch, we)
    for band in BANDS_M:
        print(f"| {band[0]}-{band[1]} | {band_mean(band, 550.0, wg, rg, stretch, we):+.1f} |")
    print(f"| Peak, half-peak radius | {peak:+.1f}, {half} m |")
    print(f"| Surroundings | {we:+.2f} |")


if __name__ == "__main__":
    main()
