"""Where is the lift a pilot meets, against the clouds and markers they see? Offline.

Usage:
    python tools/engine_plots/clouds_vs_lift.py [--sky NAME] [--set NAME=VALUE] [--points 6000]

Santiago valley, the plugin's defaults (w* 3, zi 2000), several places, times and days:
- The training markers as drawn: how many have their own cloud or are under any cloud.
- Lift at random points: how much of the good air is under a cloud, and the mean of all the
  air, which conservation of mass wants at zero.
- Lift at a cloud's centre, and by distance from it.
- Overlap of the thermals that carry a cloud: how close the next one is, in units of their
  half-peak radii, and how strong the air gets where lifts add up.

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
from xp_gliding.engine import updraft  # noqa: E402
from xp_gliding.engine.clouds import CloudCatalog, CloudParams, carries_cloud, cloud_scale, feeding_window  # noqa: E402
from xp_gliding.engine.field import FieldConfig, ThermalField  # noqa: E402
from xp_gliding.engine.geo import LocalFrame  # noqa: E402
from xp_gliding.engine.markers import STRENGTH_LIMITS_MS, select_markers  # noqa: E402

WSTAR, ZI = 3.0, 2000.0
BODY_HALF_M = 500.0 * 0.85  # make_cloud_objs: HALF_WIDTH_M * BODY_WIDTH, at scale 1
PLACES = [(-33.46, -70.65), (-33.40, -70.80), (-33.55, -70.75), (-33.30, -70.72)]
TIMES = [54000.0, 57600.0, 61200.0]  # zulu s: 12:00, 13:00, 14:00 local
DAYS = [307, 308]
HEIGHTS = [500.0, 800.0, 1000.0, 1300.0]
NAMES = ("pale", "yellow", "orange", "red")
SAMPLE_RADIUS_M = 6000.0
BANDS_M = ((0, 100), (100, 200), (200, 300), (300, 450), (450, 700), (700, 1200))


def strength_class(core):
    return sum(core >= limit for limit in STRENGTH_LIMITS_MS)


def load(lat, lon, t, day, sky):
    frame = LocalFrame(lat, lon)
    config = FieldConfig(seed=1, day=day, sky=sky)
    field = ThermalField(config, frame)
    for _ in range(200):
        if not field.update(t, lat, lon):
            break
    params = CloudParams()
    catalog = CloudCatalog(config, frame, params)
    for _ in range(5000):
        if not catalog.update(t, lat, lon):
            break
    clouds = []
    for th in catalog.thermals():
        start, stop = feeding_window(th, params)
        if start <= t <= stop + params.mean_ttl_s and math.hypot(th.e, th.n) <= 8000.0:
            clouds.append(th)
    return field, clouds, params


def under_cloud(e, n, clouds):
    for c in clouds:
        half = BODY_HALF_M * cloud_scale(c)
        if abs(e - c.e) <= half and abs(n - c.n) <= half:
            return True
    return False


def half_peak_radius(th, z, t):
    """Half-peak radius of this thermal at its present size, from the profile."""
    strength, rf = th.envelope(t)
    if strength == 0.0:
        return 0.0
    peak = updraft.updraft_velocity(0.0, z, ZI, WSTAR, th.wgain * th.gain, th.rgain * rf)
    r = 0.0
    while r < 1500.0:
        if updraft.updraft_velocity(r / th.stretch, z, ZI, WSTAR, th.wgain * th.gain, th.rgain * rf) < 0.5 * peak:
            return r
        r += 10.0
    return r


def contributors(field, e, n, z, t, we):
    """How many thermals add more than 0.5 m/s at this point."""
    reach = updraft.influence_radius(z, ZI, 2.0) * field.config.sky.max_stretch
    count = 0
    for th, r in field.alive_within(e, n, t, reach):
        s, rf = th.envelope(t)
        w = updraft.updraft_velocity(r / th.stretch, z, ZI, WSTAR, th.wgain * th.gain, th.rgain * rf, we)
        if s * (w - we) > 0.5:
            count += 1
    return count


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n", maxsplit=1)[0])
    add_sky_args(parser)
    parser.add_argument("--points", type=int, default=6000, help="random points per sky and height")
    args = parser.parse_args(argv)
    sky = sky_from_args(args)
    print(f"sky: {describe(sky)}")

    rng = random.Random(1)
    marker_rows = {h: [] for h in HEIGHTS}
    sample_rows = {h: {"under": [], "open": []} for h in HEIGHTS}
    centre_rows = {h: [] for h in HEIGHTS}
    band_rows = {h: {b: [] for b in BANDS_M} for h in HEIGHTS}
    multi_rows = {h: [] for h in HEIGHTS}
    gap_rows = {h: [] for h in HEIGHTS}
    cloud_counts, widths, alive_counts = [], [], []

    for day in DAYS:
        for lat, lon in PLACES:
            for t in TIMES:
                field, clouds, params = load(lat, lon, t, day, sky)
                cloud_counts.append(len(clouds))
                widths.extend(2 * BODY_HALF_M * cloud_scale(c) for c in clouds)
                keys = {(c.lat, c.lon) for c in clouds}
                alive = [th for th, _ in field.alive_within(0.0, 0.0, t, SAMPLE_RADIUS_M + 1000.0)]
                alive_counts.append(len(alive))
                carriers = [th for th in alive if carries_cloud(th, params)]
                for z in HEIGHTS:
                    we = field.environment_sink(z, WSTAR, ZI)
                    for m in select_markers(field, 0.0, 0.0, z, t, WSTAR, ZI):
                        th = m.thermal
                        d = min((math.hypot(th.e - c.e, th.n - c.n) for c in clouds), default=math.inf)
                        marker_rows[z].append((strength_class(m.core_ms), (th.lat, th.lon) in keys, d,
                                               under_cloud(th.e, th.n, clouds)))
                    for _ in range(args.points):
                        a, r = rng.uniform(0, 2 * math.pi), SAMPLE_RADIUS_M * math.sqrt(rng.random())
                        e, n = r * math.cos(a), r * math.sin(a)
                        w = field.lift_at(e, n, z, t, WSTAR, ZI)
                        sample_rows[z]["under" if under_cloud(e, n, clouds) else "open"].append(w)
                        if w >= 2.0:
                            multi_rows[z].append((w, contributors(field, e, n, z, t, we)))
                    for c in clouds:
                        if math.hypot(c.e, c.n) <= SAMPLE_RADIUS_M:
                            centre_rows[z].append(field.lift_at(c.e, c.n, z, t, WSTAR, ZI))
                            for band in BANDS_M:
                                for _ in range(4):
                                    a = rng.uniform(0, 2 * math.pi)
                                    r = rng.uniform(*band)
                                    band_rows[z][band].append(
                                        field.lift_at(c.e + r * math.cos(a), c.n + r * math.sin(a), z, t, WSTAR, ZI))
                    radii = {th: half_peak_radius(th, z, t) for th in carriers}
                    for th in carriers:
                        if radii[th] == 0.0 or math.hypot(th.e, th.n) > SAMPLE_RADIUS_M:
                            continue
                        gap = min((math.hypot(th.e - o.e, th.n - o.n) / (radii[th] + radii[o])
                                   for o in carriers if o is not th and radii[o] > 0.0), default=math.inf)
                        gap_rows[z].append(gap)

    print(f"thermals alive within {(SAMPLE_RADIUS_M + 1000) / 1000:.0f} km per sky: median {st.median(alive_counts)}")
    print(f"clouds within 8 km per sky: median {st.median(cloud_counts)}, "
          f"body width median {st.median(widths):.0f} m, range {min(widths):.0f}-{max(widths):.0f} m")

    print("\nMARKERS (best 20 within 3 km, as drawn)")
    print("height class   n   own cloud  under a cloud  median m to nearest cloud")
    for z in HEIGHTS:
        for k in range(4):
            rows = [r for r in marker_rows[z] if r[0] == k]
            if rows:
                print(f"{z:6.0f} {NAMES[k]:6s} {len(rows):4d} {100 * sum(r[1] for r in rows) / len(rows):8.0f}% "
                      f"{100 * sum(r[3] for r in rows) / len(rows):12.0f}% {st.median(r[2] for r in rows):14.0f}")
        rows = marker_rows[z]
        if rows:
            print(f"{z:6.0f} ALL    {len(rows):4d} {100 * sum(r[1] for r in rows) / len(rows):8.0f}% "
                  f"{100 * sum(r[3] for r in rows) / len(rows):12.0f}% {st.median(r[2] for r in rows):14.0f}")

    print(f"\nLIFT AT RANDOM POINTS (within {SAMPLE_RADIUS_M / 1000:.0f} km)")
    print("height where    n    median  >=+1  >=+2  >=+3 m/s")
    for z in HEIGHTS:
        for where in ("under", "open"):
            w = sample_rows[z][where]
            print(f"{z:6.0f} {where:5s} {len(w):6d} {st.median(w):+7.2f} "
                  f"{100 * sum(x >= 1 for x in w) / len(w):5.1f}% {100 * sum(x >= 2 for x in w) / len(w):5.1f}% "
                  f"{100 * sum(x >= 3 for x in w) / len(w):5.1f}%")
        all_points = sample_rows[z]["under"] + sample_rows[z]["open"]
        share = 100 * len(sample_rows[z]["under"]) / len(all_points)
        for limit in (2.0, 3.0):
            strong = sum(x >= limit for x in all_points)
            under = sum(x >= limit for x in sample_rows[z]["under"])
            print(f"       of air >= +{limit:.0f}: {100 * under / max(strong, 1):.0f}% lies under clouds "
                  f"(clouds cover {share:.0f}% of the sky; {100 * strong / len(all_points):.1f}% of the air is this good)")
        print(f"       mean of all the air {st.mean(all_points):+.3f} m/s; "
              f"environment sink {field.environment_sink(z, WSTAR, ZI):+.3f}")

    print("\nLIFT AT A CLOUD'S CENTRE, AND BY DISTANCE FROM IT (median, field with neighbours)")
    print("height   n  centre  >=+2 | " + " ".join(f"{a:>4d}-{b:<4d}" for a, b in BANDS_M))
    for z in HEIGHTS:
        w = centre_rows[z]
        print(f"{z:6.0f} {len(w):4d} {st.median(w):+6.2f} {100 * sum(x >= 2 for x in w) / len(w):4.0f}% | "
              + " ".join(f"{st.median(band_rows[z][b]):+9.2f}" for b in BANDS_M))

    print("\nOVERLAP of thermals that carry a cloud")
    print("height   n  next one / sum of half-peak radii: p10 median | under 1: lifts overlap | air >= +2: "
          "median, p99, max m/s; share made by 2 or more thermals")
    for z in HEIGHTS:
        gaps = sorted(gap_rows[z])
        strong = sorted(m[0] for m in multi_rows[z])
        multi = sum(m[1] >= 2 for m in multi_rows[z]) / max(len(multi_rows[z]), 1)
        print(f"{z:6.0f} {len(gaps):4d} {gaps[len(gaps) // 10]:6.2f} {st.median(gaps):6.2f} "
              f"| {100 * sum(g < 1.0 for g in gaps) / len(gaps):5.1f}% "
              f"| {st.median(strong):+.2f} {strong[int(0.99 * len(strong))]:+.2f} {strong[-1]:+.2f}; {100 * multi:.0f}%")


if __name__ == "__main__":
    main()
