"""What does a cloud's size say about its thermal? Offline.

Usage:
    python tools/engine_plots/cloud_size.py [--sky wide_carriers] [--wstar 3] [--zi 2000] [--height 1000]

For the thermals that carry a cloud, at full strength, over several seeds and places: how
each candidate for the cloud's size relates to the core and to what an ASK 21 climbs, and
the sizes that candidate gives. `climb` is the lift on a centred circle of 91 m (35 deg at
90 km/h) minus 1.4 m/s, the ASK 21's sink in that circle, so it counts width as well as peak.

Measurement tool, not part of the plugin. License: GPL-3.0-or-later.
"""

import argparse
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from xp_gliding.engine.clouds import CloudParams, carries_cloud, cloud_scale  # noqa: E402
from xp_gliding.engine.field import SKIES, FieldConfig, ThermalField  # noqa: E402
from xp_gliding.engine.geo import LocalFrame  # noqa: E402
from xp_gliding.engine.markers import core_of  # noqa: E402

SEEDS = (1, 2, 3, 4, 5)
PLACES = ((32.7, -103.2), (-33.4, -70.7))
T = 66000.0
CIRCLE_M = 91.0
SINK_MS = 1.4


def sample(sky, wstar, zi, height):
    """(cloud_scale today, wgain, rgain, core, climb) of each mature carrier."""
    p = CloudParams()
    rows = []
    for seed in SEEDS:
        for lat, lon in PLACES:
            field = ThermalField(FieldConfig(seed=seed, day=302, range_m=15000.0, sky=sky), LocalFrame(lat, lon))
            field.update(T, lat, lon)
            we = field.environment_sink(height, wstar, zi)
            for th in field.thermals():
                life = th.death - th.birth
                if carries_cloud(th, p) and th.birth + 0.3 * life <= T <= th.birth + 0.7 * life:
                    core, _ = core_of(th, height, T, wstar, zi, we)
                    lift = field.lift_at(th.e + CIRCLE_M, th.n, height, T, wstar, zi)
                    rows.append((cloud_scale(th), th.wgain, th.rgain, core, lift - SINK_MS))
    return np.array(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--sky", default="wide_carriers", choices=sorted(SKIES))
    parser.add_argument("--wstar", type=float, default=3.0)
    parser.add_argument("--zi", type=float, default=2000.0)
    parser.add_argument("--height", type=float, default=1000.0)
    args = parser.parse_args()

    a = sample(SKIES[args.sky], args.wstar, args.zi, args.height)
    scale, wgain, rgain, core, climb = a.T
    print(f"{len(a)} thermals at full strength, {args.sky}, w* {args.wstar}, zi {args.zi:.0f}, at {args.height:.0f} m")
    print(f"wgain {wgain.min():.2f}-{wgain.max():.2f}, rgain {rgain.min():.2f}-{rgain.max():.2f}, core {core.min():.2f}-{core.max():.2f}")
    print(f"cloud_scale: p10 {np.percentile(scale, 10):.2f}, median {np.median(scale):.2f}, p90 {np.percentile(scale, 90):.2f}")
    candidates = {
        "cloud_scale": scale,
        "rgain (used until 2026-11-05)": rgain,
        "flux (wgain rgain^2)": wgain * rgain * rgain,
        "wgain": wgain,
        "wgain rgain": wgain * rgain,
        "wgain / rgain": wgain / rgain,
        "core": core,
    }
    print("| Candidate | Correlation with core | With climb |")
    print("| --- | --- | --- |")
    for name, values in candidates.items():
        print(f"| {name} | {np.corrcoef(values, core)[0, 1]:+.2f} | {np.corrcoef(values, climb)[0, 1]:+.2f} |")
    print("\nBy cloud_scale:")
    for lo, hi in ((0.0, 0.8), (0.8, 1.0), (1.0, 1.2), (1.2, 2.5)):
        k = (scale >= lo) & (scale < hi)
        if k.any():
            print(f"  {lo}-{hi}: n {k.sum():4d}  core {np.median(core[k]):.2f} (p10 {np.percentile(core[k], 10):.2f}, "
                  f"p90 {np.percentile(core[k], 90):.2f})  climb {np.median(climb[k]):+.2f}")


if __name__ == "__main__":
    main()
