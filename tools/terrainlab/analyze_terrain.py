"""Read the terrain lab's scans: reach and cost of probes, then the rule for clouds' height.

Usage:
    python tools/terrainlab/analyze_terrain.py [--folder Output/xp-gliding/terrainlab]

Offline, from the CSVs that fly_terrain.py leaves. `rule` applies the rule for a cloud's base
(`engine.clouds.cloud_base_m`) to the height map scanned at Santiago.

Measurement tool, not part of the plugin. License: GPL-3.0-or-later.
"""

import argparse
import csv
import math
import os

import numpy as np

XPLANE = os.environ.get("XPLANE_DIR", r"D:\Laminar\XP12-Last-Release\X-Plane 12")
DEFAULT_FOLDER = os.path.join(XPLANE, "Output", "xp-gliding", "terrainlab")

NUMERIC = ("lat", "lon", "dist_km", "bearing", "el1", "el2", "dh1", "result", "wet", "nx", "ny",
           "nz", "us_w2l", "us_probe", "us_l2w")


def load(folder, tag):
    path = os.path.join(folder, f"{tag}.csv")
    if not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return {k: np.array([float(r[k]) for r in rows]) for k in NUMERIC}


def reach(folder, tag):
    d = load(folder, tag)
    if d is None:
        return
    print(f"\n{tag}: by distance (24 bearings)")
    print("  km    hit  missed  wet  |el|<1m  el min  median    max  dh1 max  |el1-el2| max")
    for km in np.unique(d["dist_km"]):
        m = d["dist_km"] == km
        el = d["el2"][m]
        print(f"{km:5.0f} {np.sum(d['result'][m] == 0):5d} {np.sum(d['result'][m] == 2):6d} "
              f"{np.sum(d['wet'][m] == 1):5d} {np.sum(np.abs(el) < 1.0):7d} {el.min():8.0f} "
              f"{np.median(el):6.0f} {el.max():6.0f} {d['dh1'][m].max():8.1f} "
              f"{np.abs(d['el1'][m] - d['el2'][m]).max():10.1f}")


def cost(folder, tag):
    d = load(folder, tag)
    if d is None:
        return
    total = d["us_w2l"] + d["us_probe"] + d["us_l2w"]
    print(f"\n{tag}: {len(total)} points, microseconds per call")
    for name, values in (("worldToLocal", d["us_w2l"]), ("probe", d["us_probe"]),
                         ("localToWorld", d["us_l2w"]), ("all three", total)):
        print(f"  {name:13s} median {np.median(values):7.1f}  p90 {np.percentile(values, 90):7.1f}  "
              f"p99 {np.percentile(values, 99):7.1f}  max {values.max():8.1f}")
    print(f"  40 points would take {40.0 * np.median(total) / 1000.0:.2f} ms by the median")


def compare(folder, a, b):
    da, db = load(folder, a), load(folder, b)
    if da is None or db is None:
        return
    diff = db["el2"] - da["el2"]
    hit = (da["result"] == 0) & (db["result"] == 0)
    print(f"\n{a} against {b}: {len(diff)} points, both hit {np.sum(hit)}, "
          f"wet differs at {np.sum(da['wet'] != db['wet'])}")
    print(f"  height difference: median {np.median(diff[hit]):.2f}, "
          f"p1 {np.percentile(diff[hit], 1):.2f}, p99 {np.percentile(diff[hit], 99):.2f}, "
          f"min {diff[hit].min():.2f}, max {diff[hit].max():.2f} m")


class HeightMap:
    def __init__(self, d):
        self.lats = np.unique(d["lat"])
        self.lons = np.unique(d["lon"])
        self.h = d["el2"].reshape(len(self.lats), len(self.lons))
        self.wet = d["wet"].reshape(len(self.lats), len(self.lons))
        self.step_n = (self.lats[1] - self.lats[0]) * 111195.0
        self.step_e = (self.lons[1] - self.lons[0]) * 111195.0 * math.cos(math.radians(self.lats.mean()))
        self.half_n = self.step_n * (len(self.lats) - 1) / 2.0
        self.half_e = self.step_e * (len(self.lons) - 1) / 2.0

    def at(self, e, n):
        """Nearest cell to metres (e, n) from the map's centre; arrays welcome."""
        r = np.clip(np.rint((n + self.half_n) / self.step_n).astype(int), 0, self.h.shape[0] - 1)
        c = np.clip(np.rint((e + self.half_e) / self.step_e).astype(int), 0, self.h.shape[1] - 1)
        return self.h[r, c]


def rule(folder, tag, agl_m=1500.0, margin_m=300.0, wind_ms=7.72, wind_to_deg=90.0, radius_m=20000.0,
         n=4000, seed=1, step_m=1000.0, half_width_m=500.0):
    """The rule's clouds around the map's centre, in one wind: where do their bases go?

    Clouds at random places and ages, not the engine's: the question is the shape of the ground.
    Three ways are compared: the rule built, the ground under the cloud only (it may run into a
    hill), and that with the cloud fading before it would meet the ground ("cut").
    """
    d = load(folder, tag)
    if d is None:
        return
    hm = HeightMap(d)
    rng = np.random.default_rng(seed)
    level = float(hm.at(np.array(0.0), np.array(0.0))) + agl_m
    th = rng.uniform(0.0, 2.0 * math.pi, n)
    r = radius_m * np.sqrt(rng.uniform(0.0, 1.0, n))
    e0, n0 = r * np.sin(th), r * np.cos(th)
    left_s = rng.uniform(300.0, 1400.0, n)  # what a cloud has left, for a life of 5-30 min
    ue, un = (wind_ms * math.sin(math.radians(wind_to_deg)), wind_ms * math.cos(math.radians(wind_to_deg)))
    sx, sn = (un / max(wind_ms, 1e-6) * half_width_m, -ue / max(wind_ms, 1e-6) * half_width_m)
    under = np.zeros(n)
    along = np.zeros(n)
    kept = np.ones(n)
    for i in range(n):
        cross = [hm.at(np.array(e0[i] + de), np.array(n0[i] + dn))
                 for de, dn in ((0.0, 0.0), (half_width_m, 0.0), (-half_width_m, 0.0),
                                (0.0, half_width_m), (0.0, -half_width_m))]
        under[i] = max(float(c) for c in cross)
        along[i] = under[i]
        steps = math.ceil(wind_ms * left_s[i] / step_m)
        base_under = max(level, under[i] + margin_m)
        for k in range(1, steps + 1):
            t = left_s[i] * k / steps
            g = max(float(hm.at(np.array(e0[i] + ue * t + side * sx), np.array(n0[i] + un * t + side * sn)))
                    for side in (0.0, 1.0, -1.0))
            along[i] = max(along[i], g)
            if kept[i] == 1.0 and g + margin_m > base_under:
                kept[i] = (k - 1) / steps
    below = hm.at(e0, n0)
    print(f"\nrule on {tag}: level {level:.0f} m MSL, margin {margin_m:.0f} m, wind {wind_ms} m/s toward "
          f"{wind_to_deg:.0f} deg, radius {radius_m / 1000:.0f} km; ground below: median {np.median(below):.0f}, max {below.max():.0f}")
    for name, base in (("along its drift (built)", np.maximum(level, along + margin_m)),
                       ("under it only", np.maximum(level, under + margin_m))):
        print(f"  {name:24s} at the level {100.0 * np.mean(base <= level):5.1f}%, p90 base {np.percentile(base, 90):5.0f}, "
              f"max {base.max():5.0f}; over 2000 m above the ground below it: {100.0 * np.mean(base - below > 2000.0):4.1f}%")
    cut = kept < 1.0
    print(f"  under it only, and cut: {100.0 * np.mean(cut):5.1f}% of clouds fade early, keeping "
          f"{100.0 * np.median(kept[cut]) if cut.any() else 100.0:.0f}% of what they had left (median)")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--folder", default=DEFAULT_FOLDER)
    args = parser.parse_args(argv)
    for tag in ("khob_rings_t0", "khob_rings_t60", "khob_rings_t200", "scel_rings_t0", "scel_rings_t60"):
        reach(args.folder, tag)
    for tag in ("khob_lines", "khob_scatter", "scel_lines", "scel_scatter", "scel_grid"):
        cost(args.folder, tag)
    compare(args.folder, "scel_grid", "scel_grid_from_far")
    for wind_ms, to_deg in ((0.0, 90.0), (7.72, 90.0), (7.72, 270.0), (12.9, 90.0), (12.9, 270.0)):
        rule(args.folder, "scel_grid", wind_ms=wind_ms, wind_to_deg=to_deg)


if __name__ == "__main__":
    main()
