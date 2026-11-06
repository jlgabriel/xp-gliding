"""Terrain lab: what `XPLMProbeTerrainXYZ` gives far from the glider, and what it costs.

Measurement tool, not part of the plugin. `fly_terrain.py install` copies this file to
`PythonPlugins/`; restart X-Plane, then drive it with `fly_terrain.py`.

A scan is described in `Output/xp-gliding/terrainlab/plan.json` and started by writing
`xpg_terrainlab/run`. It runs in the flight loop, about 8 ms of it in each frame, and leaves
`Output/xp-gliding/terrainlab/<tag>.csv`. `xpg_terrainlab/done` counts the scans finished, and
`xpg_terrainlab/errors` the exceptions, which go to the log.

Each point is probed twice, as a far probe has to be. The local Y axis is not the local
vertical far from the origin, so the first probe (from the point at 0 m MSL) can land beside
the point asked for. The second starts from the point at the height the first one found.

    el1, el2       height MSL from the first and the second probe
    dh1            how far the first probe landed from the point, horizontally (m)
    result, wet    of the second probe; result 0 hit, 1 error, 2 missed
    nx, ny, nz     normal of the second probe
    us_w2l, us_probe, us_l2w   the first probe's three calls, each timed by itself (microseconds)

Kinds of plan, around `lat`, `lon`:

    rings     `bearings` directions, at each of `dists_km`
    grid      a square of half side `half_km`, every `step_m`
    lines     `lines` straight lines of `points` points, `step_m` apart, starting within
              `radius_km`: what the highest ground along a cloud's drift would ask
    scatter   `points` random points within `radius_km`

License: GPL-3.0-or-later.
"""

import json
import math
import os
import random
import time
import traceback

import xp

LAB = "xpg_terrainlab"
BUDGET_NS = 8_000_000
EARTH_M = 6371000.0
HEADER = ("kind,lat,lon,dist_km,bearing,el1,el2,dh1,result,wet,nx,ny,nz,"
          "us_w2l,us_probe,us_l2w\n")


def destination(lat, lon, bearing_deg, dist_m):
    """The point dist_m away along a great circle, on a sphere: exact enough for a scan."""
    d = dist_m / EARTH_M
    b = math.radians(bearing_deg)
    p1 = math.radians(lat)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    dl = math.atan2(math.sin(b) * math.sin(d) * math.cos(p1),
                    math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), lon + math.degrees(dl)


def points_of(plan):
    """Yield (lat, lon, dist_km, bearing) for a plan."""
    kind, lat, lon = plan["kind"], plan["lat"], plan["lon"]
    rng = random.Random(plan.get("seed", 1))
    if kind == "rings":
        for dist in plan["dists_km"]:
            for i in range(plan["bearings"]):
                bearing = 360.0 * i / plan["bearings"]
                yield (*destination(lat, lon, bearing, dist * 1000.0), dist, bearing)
    elif kind == "grid":
        half, step = plan["half_km"] * 1000.0, plan["step_m"]
        rows = int(2.0 * half / step) + 1
        dlat = math.degrees(step / EARTH_M)
        dlon = dlat / math.cos(math.radians(lat))
        for r in range(rows):
            for c in range(rows):
                dn, de = r * step - half, c * step - half
                yield (lat + (r - rows // 2) * dlat, lon + (c - rows // 2) * dlon,
                       math.hypot(dn, de) / 1000.0, math.degrees(math.atan2(de, dn)) % 360.0)
    elif kind == "lines":
        for _ in range(plan["lines"]):
            bearing0 = rng.uniform(0.0, 360.0)
            dist0 = plan["radius_km"] * 1000.0 * math.sqrt(rng.random())
            lat0, lon0 = destination(lat, lon, bearing0, dist0)
            bearing = rng.uniform(0.0, 360.0)
            for i in range(plan["points"]):
                yield (*destination(lat0, lon0, bearing, i * plan["step_m"]), dist0 / 1000.0, bearing)
    elif kind == "scatter":
        for _ in range(plan["points"]):
            bearing = rng.uniform(0.0, 360.0)
            dist = plan["radius_km"] * 1000.0 * math.sqrt(rng.random())
            yield (*destination(lat, lon, bearing, dist), dist / 1000.0, bearing)
    else:
        raise ValueError(f"unknown kind {kind}")


class Lab:
    def __init__(self):
        self.folder = os.path.join(xp.getSystemPath(), "Output", "xp-gliding", "terrainlab")
        os.makedirs(self.folder, exist_ok=True)
        self.probe = xp.createProbe(xp.ProbeY)
        self.done = 0
        self.errors = 0
        self.asked = False
        self.points = None
        self.plan = None
        self.rows = []
        self.refs = [
            xp.registerDataAccessor(f"{LAB}/run", xp.Type_Int, 1, readInt=lambda _: 0,
                                    writeInt=self.ask),
            xp.registerDataAccessor(f"{LAB}/done", xp.Type_Int, 0, readInt=lambda _: self.done),
            xp.registerDataAccessor(f"{LAB}/errors", xp.Type_Int, 0, readInt=lambda _: self.errors),
        ]
        self.floop = xp.createFlightLoop(self.loop, xp.FlightLoop_Phase_BeforeFlightModel, None)
        xp.scheduleFlightLoop(self.floop, -1)

    def ask(self, _ref, _value):
        self.asked = True

    def begin(self):
        with open(os.path.join(self.folder, "plan.json"), encoding="utf-8") as f:
            self.plan = json.load(f)
        self.points = points_of(self.plan)
        self.rows = []

    def one(self, kind, lat, lon, dist, bearing):
        clock = time.perf_counter_ns
        probe = self.probe
        t0 = clock()
        x, y, z = xp.worldToLocal(lat, lon, 0.0)
        t1 = clock()
        first = xp.probeTerrainXYZ(probe, x, y, z)
        t2 = clock()
        hit_x, hit_y, hit_z = first.locationX, first.locationY, first.locationZ
        _hit_lat, _hit_lon, el1 = xp.localToWorld(hit_x, hit_y, hit_z)
        t3 = clock()
        x2, y2, z2 = xp.worldToLocal(lat, lon, el1)
        info = xp.probeTerrainXYZ(probe, x2, y2, z2)
        _lat2, _lon2, el2 = xp.localToWorld(info.locationX, info.locationY, info.locationZ)
        return (f"{kind},{lat:.6f},{lon:.6f},{dist:.3f},{bearing:.1f},{el1:.2f},{el2:.2f},"
                f"{math.hypot(hit_x - x2, hit_z - z2):.2f},{info.result},{int(info.is_wet)},"
                f"{info.normalX:.4f},{info.normalY:.4f},{info.normalZ:.4f},"
                f"{(t1 - t0) / 1000.0:.1f},{(t2 - t1) / 1000.0:.1f},{(t3 - t2) / 1000.0:.1f}\n")

    def finish(self):
        path = os.path.join(self.folder, f"{self.plan['tag']}.csv")
        with open(path, "w", encoding="utf-8") as f:
            f.write(HEADER)
            f.writelines(self.rows)
        xp.log(f"terrainlab: {len(self.rows)} points in {path}")
        self.points = self.plan = None
        self.rows = []
        self.done += 1

    def loop(self, *_):
        try:
            if self.asked and self.points is None:
                self.asked = False
                self.begin()
            if self.points is not None:
                kind = self.plan["kind"]
                end = time.perf_counter_ns() + BUDGET_NS
                while time.perf_counter_ns() < end:
                    point = next(self.points, None)
                    if point is None:
                        self.finish()
                        break
                    self.rows.append(self.one(kind, *point))
        except Exception:
            self.errors += 1
            self.points = self.plan = None
            xp.log("terrainlab: " + traceback.format_exc())
        return -1

    def stop(self):
        xp.destroyFlightLoop(self.floop)
        xp.destroyProbe(self.probe)
        for ref in self.refs:
            xp.unregisterDataAccessor(ref)


class PythonInterface:
    def XPluginStart(self):
        self.lab = Lab()
        return "xp-gliding terrain lab", "jlgabriel.xp_gliding.terrainlab", "Terrain probes: reach and cost."

    def XPluginStop(self):
        self.lab.stop()

    def XPluginEnable(self):
        return 1

    def XPluginDisable(self):
        pass

    def XPluginReceiveMessage(self, inFromWho, inMessage, inParam):
        pass
