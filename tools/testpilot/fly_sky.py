"""The sky, flown by the test pilot: its top, changing it in flight, the clock and water.

Usage (X-Plane running with the xp-gliding plugin):
    python tools/testpilot/fly_sky.py top [--sky wide_carriers] [--agl 1100] [--seconds 280]
    python tools/testpilot/fly_sky.py top --site santiago [--below 250] [--wind-kt 15] [--seconds 240]
    python tools/testpilot/fly_sky.py change [--seconds 150] [--in-lift]
    python tools/testpilot/fly_sky.py clock [--wind-kt 15]
    python tools/testpilot/fly_sky.py water [--site coast] [--wind-kt 0] [--seconds 90]

top: how high does a perfectly centred circle go? Starts beside the strongest thermal with a cloud
and in its mature life within 15 km of Hobbs, on flat ground in calm air, and circles until it
stops climbing, centring by the lift as a pilot does. Records a log for `tools/flightlog/read_flight.py`.
With --site santiago: a thermal whose cloud was raised for the ground, found in the height map the
terrain lab scanned there (`tools/terrainlab`), starting --below metres under the cloud's base, or
over it if negative. The oracle gets floors from that map. They are close to the plugin's, not the
same: compare with the log. Over hills any oracle with no floors differs from the plugin.

change: straight flight; the sky is changed by the dataref behind the menu's item, twice. Do the
clouds go, do new ones come, and does the lift match a sky rebuilt offline? With --in-lift, once
inside a thermal: what does the glider feel?

clock: straight flight. The clock jumps two hours (the clouds should start over), then the sim
runs at twice its speed. Does the air stay with the glider?

water: how many thermals go at a site, and a screenshot from the front along a coast.

Each flight is under five minutes. Measurement tool, not part of the plugin.
License: GPL-3.0-or-later.
"""

import argparse
import math
import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from airstart import KHOB, air_start, weather  # noqa: E402
from fly_wind import EXTRA, FRONT_VIEW, LEAN_ON, SCREENSHOT, SKY_E, SKY_N, ShearMission, windy_start  # noqa: E402
from pilot import AGL, ELEV, LAT, LON, SIM_TIME, Pilot, plugin_sky, release, take_over_logger  # noqa: E402
from xp_gliding.adapter.clouds import CloudHeights  # noqa: E402
from xp_gliding.engine.clouds import CloudParams, carries_cloud  # noqa: E402
from xp_gliding.engine.field import SKY_NAMES, FieldConfig, ThermalField, sky_named  # noqa: E402
from xp_gliding.engine.geo import LocalFrame  # noqa: E402
from xpweb import XPlaneStream, XPlaneWebAPI  # noqa: E402

SKY_INDEX = "xp_gliding/sky_index"
COUNT, CREATED, DESTROYED, MISSING = ("xp_gliding/clouds/count", "xp_gliding/clouds/created",
                                      "xp_gliding/clouds/destroyed", "xp_gliding/clouds/tiles_missing")
CHECKED, REJECTED = "xp_gliding/water/checked", "xp_gliding/water/rejected"
LIFT, FORCE, FRAME_US = "xp_gliding/lift_centre_ms", "xp_gliding/force_n", "xp_gliding/frame_us"
NEAREST = "xp_gliding/nearest/distance_m"
ZULU, SPEED, DLON = "sim/time/zulu_time_sec", "sim/time/sim_speed_actual", "xp_gliding/wind/dlon_deg"
SITES = {"hobbs": KHOB, "santiago": (-33.46, -70.55, 560.0), "coast": (-33.02, -71.55, 10.0)}
STOPPED_MS = 0.1  # the climb is over below this, over the last TOP_WINDOW_S
TOP_WINDOW_S = 40.0
RISEN_TAU = 0.25  # a thermal has its full strength from 0.2 of its life
MATURE_TAU = 0.68  # and its decay starts at 0.7
NEAR_M = 2000.0  # the approach is part of the five minutes
SEARCH_M = 15000.0  # flat ground around Hobbs, to look for a thermal worth climbing
APPROACH_M = 1500.0  # the flight starts this far from it
APPROACH_S = 60.0
TERRAIN_GRID = r"D:\Laminar\XP12-Last-Release\X-Plane 12\Output\xp-gliding\terrainlab\scel_grid.csv"
MIN_RAISED_M = 200.0  # over the level: a cloud worth asking about
MIN_AGL_M = 120.0  # over the ground at every point of the approach and the circle
RELOAD_S = 16.0  # the first flight's clock and the second's differ by about this


def start(api, msl, kmh, heading, site="hobbs", wind_kt=0.0, from_deg=270.0):
    lat, lon, elev = SITES[site]
    wind = [(elev / 0.3048 + a, wind_kt, from_deg, 0.0) for a in (500.0, 3000.0, 6000.0, 12000.0)] if wind_kt else []
    air_start(api, msl, kmh, heading, lat, lon, wx=weather(lat, lon, elev, wind=wind))
    take_over_logger(api)
    api.set("xp_gliding/thermals_enabled", 1)
    api.set(LEAN_ON, 0)


# --- top ------------------------------------------------------------------------------------


class TopMission(ShearMission):
    """Centres as a pilot does: reads the lift around the last turn, and rolls out toward the strong side."""

    def __init__(self, *args, seconds, place=None, whole=False):
        super().__init__(*args, correct=True)
        self.seconds = seconds
        self.whole = whole  # fly all the time, even when not climbing: to read the air on the way down
        self.place = place
        params = CloudParams()

        def mature_cloud(th, t):
            life = th.death - th.birth
            return (carries_cloud(th, params) and math.hypot(th.e, th.n) < NEAR_M
                    and t > th.birth + RISEN_TAU * life and t + seconds < th.birth + MATURE_TAU * life)
        self.wanted = mature_cloud
        if place is not None:
            self.wanted = lambda th, t: (th.lat, th.lon, th.birth) == place.key
            self.floors = place.give_floors

    def done(self, v, pilot):
        if self.state != "free":
            return False
        elapsed = pilot.flown - self.since
        rows = [r["te"] for r in self.rows if r["flown"] > pilot.flown - TOP_WINDOW_S]
        return elapsed >= self.seconds or (not self.whole and elapsed > 2.0 * TOP_WINDOW_S
                                           and statistics.fmean(rows) < STOPPED_MS)

    def report_top(self, reason, base_zzi, zi):
        print(f"top: {reason}")
        if self.oracle:
            k = len(self.oracle)
            print(f"  this oracle's lift minus the plugin's: RMS {math.sqrt(sum(x * x for x in self.oracle) / k):.3f} m/s, "
                  f"mean {sum(self.oracle) / k:+.3f}, over {k} samples, {'with' if self.floors else 'no'} floors")
        if not self.rows:
            return
        print("  AGL band | climb m/s | lift m/s | from centre m")
        bands = {}
        for r in self.rows:
            bands.setdefault(int(r["agl"] // 100) * 100, []).append(r)
        for band in sorted(bands):
            rows = bands[band]
            print(f"  {band:5d}-{band + 100:<5d} | {statistics.fmean(r['te'] for r in rows):+6.2f} | "
                  f"{statistics.fmean(r['lift'] for r in rows):+6.2f} | {statistics.fmean(r['d'] for r in rows):5.0f}")
        top = max(r["agl"] for r in self.rows)
        last = [r["te"] for r in self.rows[-max(len(self.rows) // 8, 1):]]
        if self.place is not None:
            self.report_base(self.place.base_m)
        print(f"  from {self.rows[0]['agl']:.0f} to {top:.0f} m AGL in {self.rows[-1]['flown'] - self.rows[0]['flown']:.0f} s, "
              f"climbing {statistics.fmean(last):+.2f} at the end; the clouds' level is {base_zzi * zi:.0f} m AGL "
              f"({top - base_zzi * zi:+.0f} m from it); thermal wgain {self.thermal.wgain:.2f}, rgain {self.thermal.rgain:.2f}")


    def report_base(self, base_m):
        print(f"  m from the base ({base_m:.0f} m MSL) | climb m/s | lift m/s | from centre m")
        bands = {}
        for r in self.rows:
            bands.setdefault(int((r["msl"] - base_m) // 50) * 50, []).append(r)
        for band in sorted(bands):
            rows = bands[band]
            print(f"  {band:+6d} to {band + 50:+6d} | {statistics.fmean(r['te'] for r in rows):+6.2f} | "
                  f"{statistics.fmean(r['lift'] for r in rows):+6.2f} | {statistics.fmean(r['d'] for r in rows):5.0f}")
        top = max(r["msl"] for r in self.rows)
        print(f"  from {self.rows[0]['msl']:.0f} to {top:.0f} m MSL: {top - base_m:+.0f} m from the base")


class HeightMap:
    """The ground the terrain lab scanned: a regular grid of lat, lon, height MSL."""

    def __init__(self, path):
        with open(path, encoding="utf-8") as f:
            names = f.readline().strip().split(",")
            lat_at, lon_at, height_at, result_at = (names.index(k) for k in ("lat", "lon", "el1", "result"))
            rows = [line.split(",") for line in f]
        points = [(float(r[lat_at]), float(r[lon_at]), float(r[height_at]))
                  for r in rows if r[result_at] == "0"]
        self.lats = sorted({p[0] for p in points})
        self.lons = sorted({p[1] for p in points})
        self.dlat = (self.lats[-1] - self.lats[0]) / (len(self.lats) - 1)
        self.dlon = (self.lons[-1] - self.lons[0]) / (len(self.lons) - 1)
        self.heights = {(round((a - self.lats[0]) / self.dlat), round((o - self.lons[0]) / self.dlon)): h
                        for a, o, h in points}

    def __call__(self, lat, lon):
        """Height (m MSL) at a place, bilinear; None outside the map."""
        x, y = (lat - self.lats[0]) / self.dlat, (lon - self.lons[0]) / self.dlon
        i, j = math.floor(x), math.floor(y)
        corners = [self.heights.get((i + a, j + b)) for a in (0, 1) for b in (0, 1)]
        if None in corners:
            return None
        u, v = x - i, y - j
        return ((1 - u) * ((1 - v) * corners[0] + v * corners[1])
                + u * ((1 - v) * corners[2] + v * corners[3]))


class FixedDrift:
    """What the plugin's `AirDrift` says as the flight starts. Its offset goes on across a new flight
    with the same aircraft: X-Plane sends no message of a new aircraft for it."""

    def __init__(self, dlat_deg, dlon_deg, wind_e_ms, wind_n_ms):
        self.dlat_deg, self.dlon_deg = dlat_deg, dlon_deg
        self.wind_e_ms, self.wind_n_ms = wind_e_ms, wind_n_ms

    def to_ground(self, lat, lon):
        return lat + self.dlat_deg, lon + self.dlon_deg


class RaisedPlace:
    """Where to start, for a thermal whose cloud is raised, and what this oracle knows about it."""

    def __init__(self, heights, sky, zi, t, drift, th, base_m, lat, lon, msl_m, heading, ground_m):
        self.heights, self.sky, self.zi, self.t, self.drift = heights, sky, zi, t, drift
        self.key = (th.lat, th.lon, th.birth)
        self.base_m, self.lat, self.lon, self.msl_m, self.heading = base_m, lat, lon, msl_m, heading
        self.ground_m = ground_m

    def give_floors(self, field):
        for th in field.thermals():
            th.floor_m = self.heights.floor_m(th, self.t, self.drift, self.sky.cloud_base_zzi, self.zi)


def raised_place(terrain, site, sky, below, seconds, wstar, zi, seed, day, t, wind_ms, from_deg, radius, dlat=0.0, dlon=0.0):
    """The best thermal with a raised cloud around a site, the ground allowing the flight.

    dlat, dlon: the sky's offset from the ground now. The field is in the air's frame, the map on the ground.
    """
    lat0, lon0, _ = SITES[site]
    frame = LocalFrame(lat0 - dlat, lon0 - dlon)
    field = ThermalField(FieldConfig(seed=seed, day=day, range_m=2.0 * SEARCH_M, sky=sky), frame)
    field.update(t, lat0 - dlat, lon0 - dlon)
    to = math.radians(from_deg + 180.0)
    wind_e, wind_n = wind_ms * math.sin(to), wind_ms * math.cos(to)
    drift = FixedDrift(dlat, dlon, wind_e, wind_n)
    params = CloudParams()
    heading = (from_deg + 180.0) % 360.0  # the approach is downwind, or east if calm
    side = -math.sin(math.radians(heading)), -math.cos(math.radians(heading))
    best = None
    for th in field.alive(t):
        life = th.death - th.birth
        if (not carries_cloud(th, params) or t < th.birth + RISEN_TAU * life
                or t + seconds + APPROACH_S > th.birth + MATURE_TAU * life or th.death - t < 900.0):
            continue
        lat, lon = drift.to_ground(*frame.to_latlon(th.e + APPROACH_M * side[0], th.n + APPROACH_M * side[1]))
        ground_start = terrain(lat, lon)
        if ground_start is None:
            continue
        # The level of a flight starting there.
        heights = CloudHeights(terrain, params)
        heights.level_m = ground_start + sky.cloud_base_zzi * zi
        base = heights.base_m(th, t, drift)
        if base < heights.level_m + MIN_RAISED_M:
            continue
        msl = base - below
        path = [frame.to_latlon(th.e + k * 0.1 * APPROACH_M * side[0], th.n + k * 0.1 * APPROACH_M * side[1])
                for k in range(11)]
        path += [frame.to_latlon(th.e + 2.0 * radius * math.cos(k * math.pi / 8), th.n + 2.0 * radius * math.sin(k * math.pi / 8))
                 for k in range(16)]
        grounds = [terrain(*drift.to_ground(a, o)) for a, o in path]
        if None in grounds or msl - max(grounds) < MIN_AGL_M:
            continue
        floor = base - sky.cloud_base_zzi * zi
        th.floor_m = floor
        z = msl - grounds[0]
        lift = field.lift_at(th.e + radius, th.n, z, t, wstar, zi, grounds[0])
        if best is None or lift > best[0]:
            best = lift, RaisedPlace(heights, sky, zi, t, drift, th, base, lat, lon, msl, heading, grounds[0]), th, grounds[0]
    if best is None:
        raise RuntimeError("no mature thermal with a raised cloud and room under it")
    lift, place, th, ground = best
    print(f"  chose wgain {th.wgain:.2f} rgain {th.rgain:.2f} at {th.lat:.5f}, {th.lon:.5f}: its cloud's base {place.base_m:.0f} m MSL, "
          f"{place.base_m - place.heights.level_m:+.0f} m from the level of {place.heights.level_m:.0f} m, ground under it {ground:.0f} m; "
          f"lift {lift:+.2f} m/s at {radius:.0f} m from it, starting at {place.msl_m:.0f} m MSL", flush=True)
    return place


def best_place(api, sky, agl, seconds, wstar, zi, seed, day, radius):
    """Beside the strongest mature thermal with a cloud around Hobbs: (lat, lon, what it is)."""
    lat, lon, _ = KHOB
    dlat, dlon = api.get("xp_gliding/wind/dlat_deg"), api.get("xp_gliding/wind/dlon_deg")
    frame = LocalFrame(lat - dlat, lon - dlon)
    field = ThermalField(FieldConfig(seed=seed, day=day, range_m=SEARCH_M, sky=sky), frame)
    t = api.get(ZULU)
    field.update(t, lat - dlat, lon - dlon)
    params = CloudParams()
    best, best_lift = None, -math.inf
    for th in field.alive(t):
        life = th.death - th.birth
        if (not carries_cloud(th, params) or math.hypot(th.e, th.n) > SEARCH_M
                or t < th.birth + RISEN_TAU * life or t + seconds + APPROACH_S > th.birth + MATURE_TAU * life):
            continue
        lift = field.lift_at(th.e + radius, th.n, agl, t, wstar, zi)
        if lift > best_lift:
            best, best_lift = th, lift
    if best is None:
        raise RuntimeError("no mature thermal with a cloud")
    east, north = best.e - APPROACH_M, best.n  # to its west, for a start heading east
    a, o = frame.to_latlon(east, north)
    print(f"  chose wgain {best.wgain:.2f} rgain {best.rgain:.2f}: lift {best_lift:+.2f} m/s at {radius:.0f} m from it", flush=True)
    return a + dlat, o + dlon


def run_top_raised(api, site, sky_name, below, seconds, bank, kmh, radius, wind_kt, from_deg, whole):
    """The climb under a cloud raised for the ground: does it stop by the cloud?"""
    lat0, lon0, elev = SITES[site]
    terrain = HeightMap(TERRAIN_GRID)
    start(api, elev + 2500.0, kmh, 90.0, site=site, wind_kt=wind_kt, from_deg=from_deg)
    api.set(SKY_INDEX, SKY_NAMES.index(sky_name))
    time.sleep(1.0)
    wstar, zi = api.get("xp_gliding/wstar_ms"), api.get("xp_gliding/zi_m")
    seed, day = int(api.get("xp_gliding/seed")), int(api.get("sim/time/local_date_days"))
    sky = plugin_sky(api)
    place = raised_place(terrain, site, sky, below, seconds, wstar, zi, seed, day, api.get(ZULU), wind_kt * 0.514444,
                         from_deg, radius, api.get("xp_gliding/wind/dlat_deg"), api.get("xp_gliding/wind/dlon_deg"))
    wind = [(elev / 0.3048 + a, wind_kt, from_deg, 0.0) for a in (500.0, 3000.0, 6000.0, 12000.0)] if wind_kt else []
    air_start(api, place.msl_m, kmh, place.heading, place.lat, place.lon, wx=weather(lat0, lon0, elev, wind=wind))
    take_over_logger(api)
    api.set(LEAN_ON, 0)
    zulu0, sim0 = api.get(ZULU), api.get(SIM_TIME)
    stream = XPlaneStream(api, EXTRA + (SKY_E, SKY_N))
    stream.wait_for(EXTRA + (SKY_E, SKY_N))
    mission = TopMission(api, stream, kmh, bank, 1, wstar, zi, seed, day, sky, zulu0, sim0, radius, seconds=seconds,
                         place=place, whole=whole)
    pilot = Pilot(api)
    log = None
    try:
        reason, log = pilot.run(kmh, seconds + 90.0, settle_s=5.0, min_agl=60.0, bank_limit=bank + 25.0,
                                on_step=mission.on_step, until=mission.done, quiet=True, record=True)
    except Exception as exc:
        reason = f"aborted: {exc}"
        release(api)
    stream.close()
    mission.report_top(reason, sky.cloud_base_zzi, zi)
    print(f"  flight log: {log}")
    print(f"  the plugin: level {api.get('xp_gliding/clouds/level_m'):.0f} m, nearest thermal's floor "
          f"{api.get('xp_gliding/nearest/floor_m'):.0f} m (this oracle: {place.base_m - sky.cloud_base_zzi * zi:.0f} m), "
          f"nearest cloud's base {api.get('xp_gliding/clouds/nearest_base_m'):.0f} m, frame {api.get(FRAME_US):.0f} us, "
          f"setting floors {api.get('xp_gliding/floors_us_max'):.0f} us at most, one cloud's height "
          f"{api.get('xp_gliding/clouds/base_us_max'):.0f} us at most")


def run_top(api, sky_name, agl, seconds, bank, kmh, radius):
    _, _, elev = KHOB
    windy_start(api, elev + agl, kmh, 90.0, 0.0, 270.0)
    api.set("xp_gliding/thermals_enabled", 1)
    api.set(LEAN_ON, 0)
    api.set(SKY_INDEX, SKY_NAMES.index(sky_name))
    time.sleep(1.0)
    wstar, zi = api.get("xp_gliding/wstar_ms"), api.get("xp_gliding/zi_m")
    seed, day = int(api.get("xp_gliding/seed")), int(api.get("sim/time/local_date_days"))
    lat, lon = best_place(api, plugin_sky(api), agl, seconds, wstar, zi, seed, day, radius)
    air_start(api, elev + agl, kmh, 90.0, lat, lon, wx=weather(KHOB[0], KHOB[1], elev))
    take_over_logger(api)
    api.set(LEAN_ON, 0)
    zulu0, sim0 = api.get(ZULU), api.get(SIM_TIME)
    stream = XPlaneStream(api, EXTRA + (SKY_E, SKY_N))
    stream.wait_for(EXTRA + (SKY_E, SKY_N))
    sky = plugin_sky(api)
    mission = TopMission(api, stream, kmh, bank, 1, wstar, zi, seed, day, sky, zulu0, sim0, radius, seconds=seconds)
    pilot = Pilot(api)
    log = None
    try:
        reason, log = pilot.run(kmh, seconds + 90.0, settle_s=5.0, min_agl=250.0, bank_limit=bank + 25.0,
                                on_step=mission.on_step, until=mission.done, quiet=True, record=True)
    except Exception as exc:
        reason = f"aborted: {exc}"
        release(api)
    stream.close()
    mission.report_top(reason, sky.cloud_base_zzi, zi)
    print(f"  flight log: {log}")


# --- a straight flight with something happening ---------------------------------------------


def straight(api, names, kmh, seconds, on_step):
    stream = XPlaneStream(api, names)
    stream.wait_for(names)
    pilot = Pilot(api)

    def step(v, p):
        on_step(v, p, stream.snapshot()[0])
    try:
        reason, _ = pilot.run(kmh, seconds, settle_s=5.0, min_agl=150.0, bank_limit=30.0, on_step=step, quiet=True)
    except Exception as exc:
        reason = f"aborted: {exc}"
        release(api)
    stream.close()
    return reason


def run_change_in_lift(api):
    """Change the sky in the middle of a thermal: what does the glider feel?"""
    _, _, elev = KHOB
    start(api, elev + 1000.0, 95.0, 90.0)
    wstar, zi = api.get("xp_gliding/wstar_ms"), api.get("xp_gliding/zi_m")
    seed, day = int(api.get("xp_gliding/seed")), int(api.get("sim/time/local_date_days"))
    lat, lon = best_place(api, plugin_sky(api), 1000.0, 60.0, wstar, zi, seed, day, 105.0)
    air_start(api, elev + 1000.0, 95.0, 90.0, lat, lon, wx=weather(KHOB[0], KHOB[1], elev))
    take_over_logger(api)
    first = int(api.get(SKY_INDEX))
    names = (LIFT, FORCE, COUNT, SKY_INDEX, "sim/flightmodel/forces/g_nrml")
    state = {"previous": None, "changed": None, "rows": []}

    def on_step(v, pilot, x):
        if state["changed"] is None and x[LIFT] > 2.0:
            state["changed"] = pilot.flown
            print(f"  {pilot.flown:5.1f}s in {x[LIFT]:+.2f} m/s, force {x[FORCE]:.0f} N: the sky changes", flush=True)
            api.set(SKY_INDEX, SKY_NAMES.index("default"))
        if state["changed"] is not None and pilot.flown - state["changed"] < 4.0:
            state["rows"].append((pilot.flown - state["changed"], x[LIFT], x[FORCE], x["sim/flightmodel/forces/g_nrml"]))

    try:
        print("change in lift:", straight(api, names, 95.0, 70.0, on_step))
    finally:
        api.set(SKY_INDEX, first)
    rows = state["rows"]
    for t, lift, force, g in rows[::max(len(rows) // 16, 1)]:
        print(f"  {t:5.2f}s lift {lift:+.2f} force {force:7.0f} N normal g {g:.2f}")
    if rows:
        print(f"  biggest step between samples {max(abs(a[2] - b[2]) for a, b in zip(rows, rows[1:])):.0f} N, "
              f"normal g {min(r[3] for r in rows):.2f} to {max(r[3] for r in rows):.2f}")


def run_change(api, seconds):
    _, _, elev = KHOB
    start(api, elev + 1000.0, 95.0, 90.0)
    zi, wstar, seed = api.get("xp_gliding/zi_m"), api.get("xp_gliding/wstar_ms"), int(api.get("xp_gliding/seed"))
    day = int(api.get("sim/time/local_date_days"))
    zulu0, sim0 = api.get(ZULU), api.get(SIM_TIME)
    first = int(api.get(SKY_INDEX))
    plan = [(45.0, (first + 1) % len(SKY_NAMES)), (100.0, first)]
    names = (COUNT, CREATED, DESTROYED, MISSING, LIFT, FORCE, FRAME_US, SKY_INDEX)
    state = {"previous": None, "next": 0, "printed": -10.0, "worst": 0.0, "worst_now": 0.0, "rows": [],
             "changed": None}

    def on_step(v, pilot, x):
        if state["next"] < len(plan) and pilot.flown >= plan[state["next"]][0]:
            index = plan[state["next"]][1]
            print(f"  {pilot.flown:5.0f}s to {SKY_NAMES[index]}: lift {x[LIFT]:+.2f}, clouds {x[COUNT]:.0f}", flush=True)
            api.set(SKY_INDEX, index)
            state["next"] += 1
            state["changed"] = pilot.flown
            state["worst_now"] = 0.0
        if state["previous"] is not None:
            step = abs(x[FORCE] - state["previous"])
            state["worst"] = max(state["worst"], step)
            if state["changed"] is not None and pilot.flown - state["changed"] < 3.0:
                state["worst_now"] = max(state["worst_now"], step)
        state["previous"] = x[FORCE]
        if pilot.flown - state["printed"] >= 5.0:
            state["printed"] = pilot.flown
            print(f"  {pilot.flown:5.0f}s sky {x[SKY_INDEX]:.0f} clouds {x[COUNT]:3.0f} created {x[CREATED]:4.0f} "
                  f"destroyed {x[DESTROYED]:4.0f} tiles {x[MISSING]:3.0f} lift {x[LIFT]:+.2f} force {x[FORCE]:7.1f} N "
                  f"frame {x[FRAME_US]:.0f} us; worst step of force after the last change {state['worst_now']:.0f} N", flush=True)
        if state["changed"] is not None and pilot.flown >= state["changed"] + 3.0:
            state["rows"].append((x[SKY_INDEX], v[LAT], v[LON], v[AGL], zulu0 + v[SIM_TIME] - sim0, x[LIFT]))

    reason = straight(api, names, 95.0, seconds, on_step)
    print(f"change: {reason}; worst step of force in the flight {state['worst']:.0f} N")
    errors = {}
    for index, lat, lon, z, t, lift in state["rows"][::40]:
        frame = LocalFrame(lat, lon)
        field = ThermalField(FieldConfig(seed=seed, day=day, range_m=3000.0, sky=sky_named(SKY_NAMES[int(index)])), frame)
        field.update(t, lat, lon)
        errors.setdefault(int(index), []).append(field.lift_at(0.0, 0.0, z, t, wstar, zi) - lift)
    for index, values in errors.items():
        print(f"  sky {SKY_NAMES[index]}: lift rebuilt offline minus the plugin's, RMS "
              f"{math.sqrt(sum(e * e for e in values) / len(values)):.3f} m/s over {len(values)} samples")


def run_clock(api, wind_kt):
    _, _, elev = KHOB
    start(api, elev + 1000.0, 95.0, 90.0, wind_kt=wind_kt)
    names = (COUNT, CREATED, DESTROYED, NEAREST, LIFT, ZULU, SPEED, DLON, FRAME_US)
    state = {"printed": -10.0, "stage": 0}

    def on_step(v, pilot, x):
        if state["stage"] == 0 and pilot.flown >= 30.0:
            state["stage"] = 1
            print(f"  {pilot.flown:5.0f}s the clock jumps two hours; dlon {x[DLON]:.5f}, clouds {x[COUNT]:.0f}", flush=True)
            api.set(ZULU, (x[ZULU] + 7200.0) % 86400.0)
        if state["stage"] == 1 and pilot.flown >= 70.0:
            state["stage"] = 2
            print(f"  {pilot.flown:5.0f}s the sim to twice its speed; dlon {x[DLON]:.5f}", flush=True)
            api.set("sim/time/sim_speed", 2)
        if state["stage"] == 2 and pilot.flown >= 110.0:
            state["stage"] = 3
            print(f"  {pilot.flown:5.0f}s back to normal; dlon {x[DLON]:.5f}", flush=True)
            api.set("sim/time/sim_speed", 1)
        if pilot.flown - state["printed"] >= 5.0:
            state["printed"] = pilot.flown
            print(f"  {pilot.flown:5.0f}s zulu {x[ZULU]:7.0f} speed {x[SPEED]:.2f} clouds {x[COUNT]:3.0f} "
                  f"created {x[CREATED]:4.0f} destroyed {x[DESTROYED]:4.0f} nearest {x[NEAREST]:6.0f} m "
                  f"lift {x[LIFT]:+.2f} dlon {x[DLON]:.5f} frame {x[FRAME_US]:.0f} us", flush=True)

    try:
        print("clock:", straight(api, names, 95.0, 140.0, on_step))
    finally:
        api.set("sim/time/sim_speed", 1)


def run_water(api, site, wind_kt, seconds):
    _, _, elev = SITES[site]
    start(api, elev + 1400.0, 95.0, 0.0, site=site, wind_kt=wind_kt)
    names = (CHECKED, REJECTED, COUNT, FRAME_US, NEAREST, MISSING)
    state = {"printed": -10.0, "shot": False, "frames": []}

    def on_step(v, pilot, x):
        state["frames"].append(x[FRAME_US])
        if pilot.flown - state["printed"] >= 10.0:
            state["printed"] = pilot.flown
            print(f"  {pilot.flown:5.0f}s checked {x[CHECKED]:6.0f} left out {x[REJECTED]:5.0f} "
                  f"({x[REJECTED] / max(x[CHECKED], 1.0):.1%}) clouds {x[COUNT]:3.0f} tiles {x[MISSING]:3.0f} "
                  f"nearest thermal {x[NEAREST]:6.0f} m frame {x[FRAME_US]:.0f} us", flush=True)
        if not state["shot"] and pilot.flown >= seconds - 8.0:
            state["shot"] = True
            api.command(FRONT_VIEW)
            time.sleep(1.5)
            api.command(SCREENSHOT)
            print(f"  screenshot from the front at {pilot.flown:.0f} s", flush=True)

    print(f"water at {site}:", straight(api, names, 95.0, seconds, on_step))
    print(f"  frame median {statistics.median(state['frames']):.0f} us, at most {max(state['frames']):.0f} us")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="mission", required=True)
    p = sub.add_parser("top")
    p.add_argument("--sky", default="wide_carriers", choices=SKY_NAMES)
    p.add_argument("--agl", type=float, default=1100.0)
    p.add_argument("--seconds", type=float, default=280.0)
    p.add_argument("--bank", type=float, default=35.0)
    p.add_argument("--kmh", type=float, default=95.0)
    p.add_argument("--radius", type=float, default=105.0)
    p.add_argument("--site", default="hobbs", choices=("hobbs", "santiago"))
    p.add_argument("--below", type=float, default=250.0, help="at a site with hills: start this far under the cloud's base")
    p.add_argument("--wind-kt", type=float, default=0.0, help="at a site with hills")
    p.add_argument("--from-deg", type=float, default=270.0, help="at a site with hills")
    p.add_argument("--whole", action="store_true", help="at a site with hills: fly all the time, even sinking")
    p = sub.add_parser("change")
    p.add_argument("--seconds", type=float, default=150.0)
    p.add_argument("--in-lift", action="store_true", help="change the sky once, inside a thermal")
    p = sub.add_parser("clock")
    p.add_argument("--wind-kt", type=float, default=15.0)
    p = sub.add_parser("water")
    p.add_argument("--site", default="coast", choices=sorted(SITES))
    p.add_argument("--wind-kt", type=float, default=0.0)
    p.add_argument("--seconds", type=float, default=90.0)
    args = parser.parse_args(argv)
    api = XPlaneWebAPI(timeout=30.0)
    if args.mission == "top" and args.site != "hobbs":
        run_top_raised(api, args.site, args.sky, args.below, args.seconds, args.bank, args.kmh, args.radius,
                       args.wind_kt, args.from_deg, args.whole)
    elif args.mission == "top":
        run_top(api, args.sky, args.agl, args.seconds, args.bank, args.kmh, args.radius)
    elif args.mission == "change":
        if args.in_lift:
            run_change_in_lift(api)
        else:
            run_change(api, args.seconds)
    elif args.mission == "clock":
        run_clock(api, args.wind_kt)
    else:
        run_water(api, args.site, args.wind_kt, args.seconds)


if __name__ == "__main__":
    main()
