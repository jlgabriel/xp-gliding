"""Checks of the cumulus, flown by the test pilot.

Usage (X-Plane running with the xp-gliding plugin and flight logger):
    python tools/testpilot/fly_clouds.py look [--msl 2400] [--heading 90] [--seconds 300]
        [--hour 12] [--wind-kt 0] [--native-cover 0] [--every 30] [--back]
    python tools/testpilot/fly_clouds.py cost [--msl 2800] [--blocks 3] [--seconds 60]
    python tools/testpilot/fly_clouds.py under [--msl 2400] [--count 6] [--kmh 100]
    python tools/testpilot/fly_clouds.py climb [--msl 2100] [--minutes 20] [--kmh 85] [--bank 45]

look: air start, straight flight, a screenshot every 30 s from the front with nothing in
the way, and what the plugin reports at each one, to see a sky form. Local time, wind
from the east and a layer of X-Plane's own cumulus can be chosen. With --back, a second
screenshot looking back each time: the clouds already passed, where a far one drawn over a
near one showed most (notes/phase4.md, the order clouds are drawn in).

cost: straight flight with the clouds off and on in alternating blocks. Prints the
plugin's frame_us (median, 99th percentile), the frame rate, X-Plane's own estimate of
the GPU's time per frame and the CPU of X-Plane's main thread, per block, so that CPU
and drawing cost show against each other, in the same air.

under: the question of the phase, a thermal can be found by looking at the clouds. It
flies like a pilot who looks up: toward the nearest cloud ahead, straight through the
point under it, on to the next. It chooses from the same deterministic sky the plugin
draws, but only what a pilot sees: where a cloud is and that it is alive, never how
strong its thermal is. The log gives the lift against the distance from the nearest
cloud, and the report compares it with the air away from them.

climb: the same choice of cloud, but it orbits the point under it and climbs until the
climb is over, then goes to the next one. `fly_phase1.py orbit` with the clouds choosing
the thermal instead of an oracle that knows their lift.

Measurement tool, not part of the plugin. License: GPL-3.0-or-later.
"""

import argparse
import math
import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "tools", "flightlog"))
sys.path.insert(0, os.path.join(REPO, "tools", "hudlab"))
sys.path.insert(0, REPO)

from airstart import KHOB, air_start, weather  # noqa: E402
from control import OrbitHold  # noqa: E402
from fly_phase1 import OracleOrbits, report_orbit  # noqa: E402
from analyze_flightlog import flying_rows, load_rows  # noqa: E402
from pilot import AGL, IAS, LAT, LOG_DIR, LON, SIM_TIME, TAS, Pilot, plugin_sky, release  # noqa: E402
from thread_cpu import main_thread, thread_times, xplane_pid  # noqa: E402
from xp_gliding.engine import clouds as cl  # noqa: E402
from xp_gliding.engine.field import FieldConfig, ThermalField  # noqa: E402
from xp_gliding.engine.geo import LocalFrame  # noqa: E402
from xpweb import XPlaneStream, XPlaneWebAPI  # noqa: E402

PREFIX = "xp_gliding/clouds/"
ENABLED = "xp_gliding/clouds_enabled"
LIFT = "xp_gliding/lift_ms"
GPU_TIME = "sim/time/gpu_time_per_frame_sec_approx"
SCREENSHOT = "sim/operation/screenshot"
FRONT_VIEW, COCKPIT_VIEW = "sim/view/forward_with_nothing", "sim/view/3d_cockpit_cmnd_look"
BACK_VIEW = "sim/view/back"
STATUS_NAMES = ("count", "created", "destroyed", "rate_changes", "tiles_missing", "update_us",
                "update_us_max", "plan_us", "nearest_m", "handed_over", "refilled", "cooling", "pool_idle",
                "pool_misses",
                "order_us")
WATCH = (LIFT, GPU_TIME, *(PREFIX + name for name in STATUS_NAMES))


def status_of(values):
    return {name: round(values[PREFIX + name], 1) for name in STATUS_NAMES}


def run_look(api, msl, heading, seconds, kmh, hour=12.0, wind_kt=0.0, native_cover=0.0, every=30.0,
             back=False):
    lat, lon, elev = KHOB
    wind = ()
    if wind_kt > 0.0:
        wind = [(elev / 0.3048 + alt, wind_kt, 90.0, 0.0) for alt in (500.0, 5000.0, 12000.0)]
    clouds = ()
    if native_cover > 0.0:  # base and top: the layer of our own clouds
        base_ft = (elev + 1500.0) / 0.3048
        clouds = (("cumulus", native_cover, base_ft, base_ft + 3000.0),)
    air_start(api, msl, kmh, heading, lat, lon, wx=weather(lat, lon, elev, wind=wind, clouds=clouds),
              hour=hour)
    api.set(ENABLED, 1)
    api.command(FRONT_VIEW)
    stream = XPlaneStream(api, WATCH)
    stream.wait_for(WATCH)
    state = {"next": 0.0}

    def on_step(v, p):
        if p.flown >= state["next"]:
            state["next"] = p.flown + every
            api.command(SCREENSHOT)
            print(f"{p.flown:5.0f} s: screenshot; {status_of(stream.snapshot()[0])}", flush=True)
            if back:
                api.command(BACK_VIEW)
                time.sleep(1.0)
                api.command(SCREENSHOT)
                time.sleep(1.0)
                api.command(FRONT_VIEW)
                print(f"{p.flown:5.0f} s: screenshot looking back", flush=True)

    try:
        reason, _ = Pilot(api).run(kmh, seconds, quiet=True, on_step=on_step)
        print(reason, status_of(stream.snapshot()[0]), flush=True)
    finally:
        api.command(COCKPIT_VIEW)
        stream.close()


def block_stats(log):
    _, rows = load_rows(os.path.join(LOG_DIR, log))
    rows = flying_rows(rows)
    us = sorted(r["xpg_frame_us"] for r in rows)
    periods = [r["frame_period_s"] for r in rows if r["frame_period_s"]]
    return {"frames": len(rows), "median": statistics.median(us), "p99": us[int(0.99 * len(us))],
            "fps": 1.0 / statistics.fmean(periods), "worst_frame_ms": 1e3 * max(periods)}


def run_cost(api, msl, blocks, seconds, kmh):
    air_start(api, msl, kmh, 90.0)
    stream = XPlaneStream(api, WATCH)
    stream.wait_for(WATCH)
    tid = main_thread(xplane_pid())
    results = []
    for block in range(2 * blocks):
        on = block % 2
        api.set(ENABLED, on)
        time.sleep(0.5)
        pilot = Pilot(api)
        gpu = []
        marks = {}

        def on_step(v, p):
            # The first block with clouds needs time to fill: a tile bite 4 times a second.
            if p.flown > 8.0:
                if "cpu" not in marks:
                    marks["t"], marks["cpu"] = time.monotonic(), thread_times(tid)[1]
                gpu.append(stream.snapshot()[0][GPU_TIME])

        try:
            _, log = pilot.run(kmh, seconds, settle_s=8.0, record=True, quiet=True, on_step=on_step)
        except Exception as exc:
            print(f"block {block}: aborted: {exc}", flush=True)
            release(api)
            break
        cpu = (thread_times(tid)[1] - marks["cpu"]) / (time.monotonic() - marks["t"]) * 1e3
        s = block_stats(log)
        s["gpu_ms"], s["cpu"] = 1e3 * statistics.median(gpu), cpu
        status = status_of(stream.snapshot()[0])
        results.append((on, s, status))
        print(f"clouds {'on ' if on else 'off'}: {s['frames']} frames, {status}, {s}; {log}", flush=True)
    print("\n| Clouds | Shown | frame_us median | frame_us p99 | fps | GPU (ms) | Main thread (ms/s) "
          "| Worst frame (ms) | Update (µs) | Update max (µs) | Plan (µs) |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for on, s, st in results:
        print(f"| {'on' if on else 'off'} | {int(st['count']) if on else 0} | {s['median']:.0f} "
              f"| {s['p99']:.0f} | {s['fps']:.1f} | {s['gpu_ms']:.2f} | {s['cpu']:.0f} "
              f"| {s['worst_frame_ms']:.1f} | {st['update_us']:.0f} | {st['update_us_max']:.0f} "
              f"| {st['plan_us']:.0f} |")
    stream.close()


class CloudHopper:
    """Bank commands to fly from cloud to cloud, through the point under each."""

    REACHED_M = 150.0
    GAIN_DEG_PER_DEG = 1.0
    MAX_BANK = 30.0

    def __init__(self, catalog, count, on_target):
        self.catalog = catalog
        self.left = count
        self.on_target = on_target
        self.done = set()
        self.target = None

    def choose(self, e, n, track, t):
        """The nearest cloud a pilot would pick: alive, ahead rather than behind, and fully
        formed, since a pilot cannot judge the strength of the air under it."""
        p = self.catalog.params
        best, best_cost = None, math.inf
        for th in self.catalog.thermals():
            if th in self.done:
                continue
            start, stop = cl.feeding_window(th, p)
            if not (start + 0.5 * p.ttl_s <= t < stop):
                continue
            dx, dy = th.e - e, th.n - n
            r = math.hypot(dx, dy)
            if r < 1000.0 or r > 12000.0:
                continue
            off = abs((math.degrees(math.atan2(dx, dy)) - track + 180.0) % 360.0 - 180.0)
            cost = r * (1.0 + off / 60.0)
            if cost < best_cost:
                best, best_cost = th, cost
        return best

    def bank(self, track, e, n, t):
        if self.target is not None and math.hypot(self.target.e - e, self.target.n - n) < self.REACHED_M:
            self.done.add(self.target)
            self.target = None
            self.left -= 1
        if self.left <= 0:
            return 0.0
        if self.target is None:
            self.target = self.choose(e, n, track, t)
            if self.target is None:
                return 0.0
            self.on_target(self.target)
        want = math.degrees(math.atan2(self.target.e - e, self.target.n - n))
        error = (want - track + 180.0) % 360.0 - 180.0
        return max(-self.MAX_BANK, min(self.MAX_BANK, self.GAIN_DEG_PER_DEG * error))


def report_under(log, catalog):
    """Lift against the distance from the nearest cloud that was alive and formed at that time."""
    _, rows = load_rows(os.path.join(LOG_DIR, log))
    rows = flying_rows(rows)
    frame = catalog.frame
    p = catalog.params
    thermals = list(catalog.thermals())
    bins = (0, 50, 100, 150, 200, 300, 500, 1000, 2000, 5000)
    lifts = {b: [] for b in bins}
    for k, row in enumerate(rows):
        if k % 10:
            continue
        t = row["t_zulu_s"]
        e, n = frame.to_enu(row["lat_deg"], row["lon_deg"])
        best = math.inf
        for th in thermals:
            start, stop = cl.feeding_window(th, p)
            if start <= t < stop:
                best = min(best, math.hypot(th.e - e, th.n - n))
        for low, high in zip(bins, bins[1:]):
            if low <= best < high:
                lifts[low].append(row["xpg_lift_ms"])
                break
    print("\n| Distance from the cloud's centre (m) | Samples | Lift, median (m/s) | p10 | p90 |")
    print("| --- | --- | --- | --- | --- |")
    for low, high in zip(bins, bins[1:]):
        values = sorted(lifts[low])
        if values:
            print(f"| {low}–{high} | {len(values)} | {statistics.median(values):+.2f} "
                  f"| {values[len(values) // 10]:+.2f} | {values[9 * len(values) // 10]:+.2f} |")


def run_under(api, msl, count, kmh, heading):
    lat, lon, _ = KHOB
    air_start(api, msl, kmh, heading, lat, lon)
    api.set(ENABLED, 1)
    seed = int(api.get("xp_gliding/seed"))
    day = int(api.get("sim/time/local_date_days"))
    zulu0 = api.get("sim/time/zulu_time_sec")
    sim0 = api.get(SIM_TIME)
    frame = LocalFrame(lat, lon)
    catalog = cl.CloudCatalog(FieldConfig(seed=seed, day=day, sky=plugin_sky(api)), frame)
    while catalog.update(zulu0, lat, lon):
        pass

    def on_target(th):
        print(f"next cloud at ({th.e:.0f}, {th.n:.0f}), {th.rgain=:.2f} {th.wgain=:.2f}", flush=True)

    hopper = CloudHopper(catalog, count, on_target)

    class Guidance:
        def __init__(self):
            self.t = zulu0

        def bank(self, track, e, n):
            return hopper.bank(track, e, n, self.t)

    guidance = Guidance()
    stream = XPlaneStream(api, WATCH)
    stream.wait_for(WATCH)

    def on_step(v, p):
        guidance.t = zulu0 + v[SIM_TIME] - sim0
        catalog.update(guidance.t, v[LAT], v[LON])

    pilot = Pilot(api, frame)
    reached = lambda v, p: hopper.left <= 0  # noqa: E731
    try:
        reason, log = pilot.run(kmh, 1800.0, guidance, settle_s=10.0, record=True, min_agl=300.0,
                                until=reached, on_step=on_step, quiet=True)
    except Exception as exc:
        reason, log = f"aborted: {exc}", pilot.log_name
        release(api)
    print(f"under: {reason}; {count - hopper.left} clouds; log {log}; "
          f"{status_of(stream.snapshot()[0])}", flush=True)
    stream.close()
    if log:
        report_under(log, catalog)


class CloudOrbits(OracleOrbits):
    """Orbit under one cloud after another, chosen as a pilot looking up would."""

    def __init__(self, *args, catalog, **kwargs):
        super().__init__(*args, min_turns=6, max_turns=12, **kwargs)  # 3 turns only just centre it
        self.catalog = catalog
        self.hopper = CloudHopper(catalog, 0, lambda th: None)
        self.state = "wait"
        self.ref_sink = 0.0

    def select(self, pilot, z, t, tas):
        self.catalog.update(t, *pilot.frame.to_latlon(pilot.east, pilot.north))
        th = self.hopper.choose(pilot.east, pilot.north, pilot.track, t)
        if th is None:
            raise RuntimeError("no cloud in sight")
        self.hopper.done.add(th)
        self.field.update(t, *pilot.frame.to_latlon(pilot.east, pilot.north))
        radius = self.radius(tas)
        lift = self.circle_mean(th, z, t, radius)
        self.orbit = OrbitHold((th.e, th.n), radius, tas, direction=-1, max_trim=10.0)
        d = math.hypot(th.e - pilot.east, th.n - pilot.north)
        self.circles.append({"predicted": lift, "distance": d})
        print(f"  {pilot.flown:6.0f}s cloud {d:.0f} m away; engine lift on the circle {lift:+.2f} m/s, "
              f"radius {radius:.0f} m, AGL {z:.0f}, thermal age {(t - th.birth) / 60:.0f} of "
              f"{(th.death - th.birth) / 60:.0f} min", flush=True)
        pilot.guidance = self.orbit
        self.state, self.since = "approach", None

    def on_step(self, v, pilot):
        if self.state == "wait" and pilot.flown >= 8.0:
            ias_ms = v[IAS] * 0.514444
            tas = self.kmh / 3.6 * (v[TAS] / ias_ms if ias_ms > 10.0 else 1.0)
            self.select(pilot, v[AGL], self.zulu0 + v[SIM_TIME] - self.sim0, tas)
        else:
            super().on_step(v, pilot)


def run_climb(api, msl, minutes, kmh, bank, heading):
    lat, lon, _ = KHOB
    air_start(api, msl, kmh, heading, lat, lon)
    api.set(ENABLED, 1)
    wstar, zi = api.get("xp_gliding/wstar_ms"), api.get("xp_gliding/zi_m")
    seed = int(api.get("xp_gliding/seed"))
    day = int(api.get("sim/time/local_date_days"))
    zulu0, sim0 = api.get("sim/time/zulu_time_sec"), api.get(SIM_TIME)
    frame = LocalFrame(lat, lon)
    config = FieldConfig(seed=seed, day=day, sky=plugin_sky(api))
    catalog = cl.CloudCatalog(config, frame)
    while catalog.update(zulu0, lat, lon):
        pass
    field = ThermalField(config, frame)
    orbits = CloudOrbits(api, field, zulu0, sim0, kmh, bank, wstar, zi, catalog=catalog)
    stream = XPlaneStream(api, WATCH)
    stream.wait_for(WATCH)
    pilot = Pilot(api, frame)
    try:
        reason, log = pilot.run(kmh, minutes * 60.0, settle_s=5.0, record=True, min_agl=350.0,
                                bank_limit=bank + 25.0, on_step=orbits.on_step)
    except Exception as exc:
        reason, log = f"aborted: {exc}", pilot.log_name
        release(api)
    print(f"climb: {reason}; {len(orbits.circles)} clouds; log {log}; "
          f"{status_of(stream.snapshot()[0])}", flush=True)
    stream.close()
    if log:
        report_orbit([log])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="what", required=True)
    p = sub.add_parser("look")
    p.add_argument("--msl", type=float, default=2400.0)
    p.add_argument("--heading", type=float, default=90.0)
    p.add_argument("--seconds", type=float, default=300.0)
    p.add_argument("--kmh", type=float, default=90.0)
    p.add_argument("--hour", type=float, default=12.0)
    p.add_argument("--wind-kt", type=float, default=0.0)
    p.add_argument("--native-cover", type=float, default=0.0)
    p.add_argument("--every", type=float, default=30.0)
    p.add_argument("--back", action="store_true", help="a screenshot looking back too")
    p = sub.add_parser("cost")
    p.add_argument("--msl", type=float, default=2800.0)
    p.add_argument("--blocks", type=int, default=3)
    p.add_argument("--seconds", type=float, default=60.0)
    p.add_argument("--kmh", type=float, default=90.0)
    p = sub.add_parser("under")
    p.add_argument("--msl", type=float, default=2400.0)
    p.add_argument("--count", type=int, default=6)
    p.add_argument("--kmh", type=float, default=100.0)
    p.add_argument("--heading", type=float, default=90.0)
    p = sub.add_parser("climb")
    p.add_argument("--msl", type=float, default=2100.0)
    p.add_argument("--minutes", type=float, default=20.0)
    p.add_argument("--kmh", type=float, default=85.0)
    p.add_argument("--bank", type=float, default=45.0)
    p.add_argument("--heading", type=float, default=90.0)
    args = parser.parse_args(argv)
    api = XPlaneWebAPI(timeout=30.0)
    if args.what == "look":
        run_look(api, args.msl, args.heading, args.seconds, args.kmh, args.hour, args.wind_kt,
                 args.native_cover, args.every, args.back)
    elif args.what == "cost":
        run_cost(api, args.msl, args.blocks, args.seconds, args.kmh)
    elif args.what == "climb":
        run_climb(api, args.msl, args.minutes, args.kmh, args.bank, args.heading)
    else:
        run_under(api, args.msl, args.count, args.kmh, args.heading)


if __name__ == "__main__":
    main()
