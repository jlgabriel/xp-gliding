"""Checks of the training markers, flown by the test pilot.

Usage (X-Plane running with the xp-gliding plugin and flight logger 0.4.0):
    python tools/testpilot/fly_markers.py look [--msl 1916] [--heading 90] [--seconds 60]
    python tools/testpilot/fly_markers.py cost [--msl 2400] [--blocks 3] [--seconds 60]
    python tools/testpilot/fly_markers.py orbit [--minutes 15] [--kmh 90] [--bank 45]
    python tools/testpilot/fly_markers.py keep [--msl 2400] [--minutes 8]
    python tools/testpilot/fly_markers.py report LOG.csv ...

look: air start with the markers on, straight flight, and screenshots in
`Output/screenshots` from the cockpit and from outside, in turns.

cost: straight flight with the markers off and on in alternating blocks. Prints
the plugin's frame_us (median, 99th percentile), the frame rate and X-Plane's own
estimate of the GPU's time per frame, per block, so the CPU cost and any drawing
cost show against each other, in the same air.

orbit: the oracle orbits of `fly_phase1.py orbit`, markers on. While it orbits,
a marked core should be at the centre of the orbit and the lift should be the
marker's: every few seconds it compares
- the distance glider-marker in X-Plane's own local coordinates with the same
  distance in the engine's frame, both taken by the plugin at the moment of a
  marker update (`markers/probe_local_distance_m`, `markers/probe_distance_m`);
- the ring's height with the glider's, at that same moment (`markers/probe_dy_m`);
- the marker's core lift with the lift the engine gave the glider, in the log.

keep: one orbit, flown until the thermal has faded, around a marked thermal that is
near the end of its life, close by and with no other marker near it. Does the
thermal being circled keep its marker, and when does it go? Every 5 s it asks
whether the marker nearest the glider is the target (same distance, same core), and
afterwards replays the selection along the flown track, with and without the
protection of a marker near the glider.

Measurement tool, not part of the plugin. License: GPL-3.0-or-later.
"""

import argparse
import math
import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "flightlog"))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from airstart import KHOB, air_start  # noqa: E402
from analyze_flightlog import flying_rows, load_rows  # noqa: E402
from control import OrbitHold  # noqa: E402
from fly_phase1 import (AGL, IAS, SIM_TIME, TAS, OracleOrbits, read_settings,  # noqa: E402
                        report_orbit, restore)
from pilot import LOG_DIR, Pilot, plugin_sky, release  # noqa: E402
from xp_gliding.engine import markers as mk  # noqa: E402
from xp_gliding.engine.field import FieldConfig, ThermalField  # noqa: E402
from xp_gliding.engine.geo import LocalFrame  # noqa: E402
from xpweb import XPlaneStream, XPlaneWebAPI  # noqa: E402

PREFIX = "xp_gliding/markers/"
ENABLED = "xp_gliding/markers_enabled"
LIFT = "xp_gliding/lift_ms"
GPU_TIME = "sim/time/gpu_time_per_frame_sec_approx"  # "for entertainment value only" (DataRefs.txt)
COCKPIT_VIEW, OUTSIDE_VIEW = "sim/view/3d_cockpit_cmnd_look", "sim/view/circle"
SCREENSHOT = "sim/operation/screenshot"
STATUS_NAMES = ("count", "created", "destroyed", "swapped", "update_us", "update_us_max",
                "select_us", "probe_distance_m", "probe_local_distance_m", "probe_dy_m",
                "probe_core_ms", "probe_r1_m", "probe_size_m", "probe_strength")
# Read through a stream of its own: a REST read takes ~50 ms, too long to do in the
# middle of the pilot's control loop.
WATCH = (LIFT, GPU_TIME, *(PREFIX + name for name in STATUS_NAMES))


def marker_status(values):
    return {name: values[PREFIX + name] for name in STATUS_NAMES}


class Screenshots:
    """Screenshots from the cockpit and from outside, in turns, without stopping the
    pilot: each view gets a moment before its picture, on later calls of step()."""

    def __init__(self, api, every_s, first_s=10.0):
        self.api, self.every_s, self.next_s = api, every_s, first_s
        self.outside = False
        self.pending = None

    def step(self, flown):
        """Returns True when it has just taken a picture."""
        if self.pending is not None and flown >= self.pending:
            self.pending = None
            self.api.command(SCREENSHOT)
            self.outside = not self.outside
            return True
        if self.pending is None and flown >= self.next_s:
            self.next_s = flown + self.every_s
            self.api.command(OUTSIDE_VIEW if self.outside else COCKPIT_VIEW)
            self.pending = flown + 1.0
        return False

    def finish(self):
        self.api.command(COCKPIT_VIEW)


def run_look(api, msl, heading, seconds, kmh):
    air_start(api, msl, kmh, heading)
    api.set(ENABLED, 1)
    pilot = Pilot(api)
    stream = XPlaneStream(api, WATCH)
    stream.wait_for(WATCH)
    shots = Screenshots(api, 15.0)

    def on_step(v, p):
        if shots.step(p.flown):
            print(f"{p.flown:5.0f} s: screenshot; {marker_status(stream.snapshot()[0])}", flush=True)

    try:
        pilot.run(kmh, seconds, quiet=True, on_step=on_step)
    finally:
        shots.finish()
        stream.close()


def block_stats(log):
    _, rows = load_rows(os.path.join(LOG_DIR, log))
    rows = flying_rows(rows)
    us = sorted(r["xpg_frame_us"] for r in rows)
    periods = [r["frame_period_s"] for r in rows if r["frame_period_s"]]
    return {"frames": len(rows), "median": statistics.median(us), "p99": us[int(0.99 * len(us))],
            "fps": 1.0 / statistics.fmean(periods),
            "worst_frame_ms": 1e3 * max(periods)}


def run_cost(api, msl, blocks, seconds, kmh):
    air_start(api, msl, kmh, 90.0)
    stream = XPlaneStream(api, WATCH)
    stream.wait_for(WATCH)
    results = []
    for block in range(2 * blocks):
        on = block % 2
        api.set(ENABLED, on)
        time.sleep(0.5)
        pilot = Pilot(api)
        gpu = []

        def on_step(v, p):
            if p.flown > 8.0:
                gpu.append(stream.snapshot()[0][GPU_TIME])

        try:
            _, log = pilot.run(kmh, seconds, settle_s=8.0, record=True, quiet=True, on_step=on_step)
        except Exception as exc:
            print(f"block {block}: aborted: {exc}", flush=True)
            release(api)
            break
        s = block_stats(log)
        s["gpu_ms"] = 1e3 * statistics.median(gpu)
        status = marker_status(stream.snapshot()[0])
        results.append((on, s, status))
        print(f"markers {'on ' if on else 'off'}: {s['frames']} frames, frame_us median "
              f"{s['median']:.0f}, p99 {s['p99']:.0f}, {s['fps']:.1f} fps, GPU {s['gpu_ms']:.2f} ms, worst "
              f"frame {s['worst_frame_ms']:.1f} ms; {int(status['count'])} markers, update "
              f"{status['update_us']:.0f} us (max {status['update_us_max']:.0f}), select "
              f"{status['select_us']:.0f} us; {log}", flush=True)
    print("\n| Markers | Markers shown | frame_us median | frame_us p99 | fps | GPU (ms) "
          "| Worst frame (ms) | Update (µs) | Update max (µs) | Select (µs) |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for on, s, status in results:
        print(f"| {'on' if on else 'off'} | {int(status['count'])} | {s['median']:.0f} "
              f"| {s['p99']:.0f} | {s['fps']:.1f} | {s['gpu_ms']:.2f} | {s['worst_frame_ms']:.1f} "
              f"| {status['update_us']:.0f} | {status['update_us_max']:.0f} "
              f"| {status['select_us']:.0f} |")
    stream.close()


class MarkedOrbits(OracleOrbits):
    """The oracle's orbits, comparing every few seconds the marker with the glider."""

    def __init__(self, *args, stream, **kwargs):
        super().__init__(*args, **kwargs)
        self.stream = stream
        self.next_check = 0.0
        self.shots = Screenshots(self.api, 45.0, first_s=0.0)
        self.checks = []

    def on_step(self, v, pilot):
        super().on_step(v, pilot)
        if self.state == "orbit":
            self.shots.step(pilot.flown)
        if self.state == "ref" or pilot.flown < self.next_check:
            return
        self.next_check = pilot.flown + 5.0
        values, _ = self.stream.snapshot()
        engine_d = values[PREFIX + "probe_distance_m"]
        local_d = values[PREFIX + "probe_local_distance_m"]
        dy = values[PREFIX + "probe_dy_m"]
        if engine_d < 0.0:
            return
        core = values[PREFIX + "probe_core_ms"]
        r1 = values[PREFIX + "probe_r1_m"]
        size = values[PREFIX + "probe_size_m"]
        self.checks.append({"state": self.state, "local_d": local_d, "engine_d": engine_d, "dy": dy,
                            "core": core, "r1": r1, "size": size,
                            "lift": values[LIFT], "count": values[PREFIX + "count"]})


def summarize_checks(checks):
    if not checks:
        print("no marker checks")
        return
    print("\n| Check | Median | Worst |")
    print("| --- | --- | --- |")
    for label, values in (
            ("|distance in X-Plane − in the engine| (m)",
             [abs(c["local_d"] - c["engine_d"]) for c in checks]),
            ("|height glider − ring| (m)", [abs(c["dy"]) for c in checks]),
            ("markers shown", [c["count"] for c in checks])):
        if values:
            print(f"| {label} | {statistics.median(values):.2f} | {max(values):.2f} |")


def run_orbit(api, minutes, msl, course, seed, kmh, bank):
    lat, lon, _ = KHOB
    air_start(api, msl, kmh, course, lat, lon)
    if seed is not None:
        api.set("xp_gliding/seed", seed)
    api.set(ENABLED, 1)
    api.set("xp_gliding/thermals_enabled", 0)  # for the reference circle
    wstar, zi = api.get("xp_gliding/wstar_ms"), api.get("xp_gliding/zi_m")
    seed = int(api.get("xp_gliding/seed"))
    day = int(api.get("sim/time/local_date_days"))
    zulu0 = api.get("sim/time/zulu_time_sec")
    sim0 = api.get("sim/time/total_flight_time_sec")
    frame = LocalFrame(lat, lon)
    field = ThermalField(FieldConfig(seed=seed, day=day, sky=plugin_sky(api)), frame)
    stream = XPlaneStream(api, WATCH)
    stream.wait_for(WATCH)
    oracle = MarkedOrbits(api, field, zulu0, sim0, kmh, bank, wstar, zi, stream=stream)
    pilot = Pilot(api, frame)
    try:
        reason, log = pilot.run(kmh, minutes * 60.0, oracle.ref_circle, settle_s=20.0, record=True,
                                min_agl=400.0, bank_limit=bank + 25.0, on_step=oracle.on_step)
    except Exception as exc:
        reason, log = f"aborted: {exc}", pilot.log_name
        release(api)
    print(f"orbits: {reason}; {len(oracle.circles)} thermals; log {log}", flush=True)
    print(marker_status(stream.snapshot()[0]))
    oracle.shots.finish()
    stream.close()
    summarize_checks(oracle.checks)
    if log:
        report_orbit([log])


class KeptOrbit(MarkedOrbits):
    """One orbit around one thermal, to the end of the flight, whatever the lift."""

    NEVER = 10 ** 6

    def __init__(self, *args, target, **kwargs):
        super().__init__(*args, min_turns=self.NEVER, max_turns=self.NEVER, top_zzi=1.0, **kwargs)
        self.target = target
        self.state = "wait"
        self.shots.every_s = 120.0

    def select(self, pilot, z, t, tas):
        pass

    def start_orbit(self, v, pilot):
        """Once the speed has settled: right after an air start TAS/IAS is far off, and
        the radius would come out far too large for the bank it is flown at."""
        tas = self.kmh / 3.6 * v[TAS] / (v[IAS] * 0.514444)
        radius = self.radius(tas)
        self.orbit = OrbitHold((self.target.e, self.target.n), radius, tas, direction=-1,
                               max_trim=10.0)
        pilot.guidance = self.orbit
        self.state = "approach"
        print(f"  {pilot.flown:6.0f}s orbit of radius {radius:.0f} m, TAS {tas:.1f} m/s", flush=True)

    def on_step(self, v, pilot):
        if self.state == "wait" and pilot.flown >= 8.0:
            self.start_orbit(v, pilot)
        before = len(self.checks)
        super().on_step(v, pilot)
        if len(self.checks) > before:
            self.checks[-1].update(flown=pilot.flown, e=pilot.east, n=pilot.north, z=v[AGL],
                                   t=self.zulu0 + v[SIM_TIME] - self.sim0)


def choose_target(chosen, t, min_life_s=200.0, max_life_s=500.0, max_m=1200.0, alone_m=300.0):
    """The nearest marked thermal that fades within the flight, with no marker near it."""
    for m in sorted(chosen, key=lambda m: m.distance_m):
        th = m.thermal
        alone = all(o is m or math.hypot(o.thermal.e - th.e, o.thermal.n - th.n) > alone_m
                    for o in chosen)
        if m.distance_m <= max_m and min_life_s <= th.death - t <= max_life_s and alone:
            return m
    raise RuntimeError("no marked thermal suits this check here")


def replay_selection(field, checks, shown, target, wstar, zi, params):
    """Flight seconds at which the target leaves the selection along the track, or None."""
    shown = set(shown)
    for c in checks:
        field.update(c["t"], *field.frame.to_latlon(c["e"], c["n"]))
        shown = {m.thermal for m in mk.select_markers(field, c["e"], c["n"], c["z"], c["t"], wstar, zi,
                                                      shown, params)}
        if target not in shown:
            return c["flown"]
    return None


def report_keep(field, checks, shown, target, wstar, zi):
    print("\n flown  state     target_d  probe_d  target_core  probe_core  markers  is_target")
    last_seen = None
    lost_while_alive = 0
    for c in checks:
        d = math.hypot(c["e"] - target.e, c["n"] - target.n)
        we = field.environment_sink(c["z"], wstar, zi)
        core, _ = mk.core_of(target, c["z"], c["t"], wstar, zi, we)
        c["is_target"] = abs(c["engine_d"] - d) < 40.0 and abs(c["core"] - core) < 0.4
        if c["is_target"]:
            last_seen = c["flown"]
        elif c["state"] == "orbit" and core >= mk.MarkerParams().keep_core_ms:
            lost_while_alive += 1
        print(f"{c['flown']:6.0f}  {c['state']:8s} {d:8.0f} {c['engine_d']:8.0f} {core:12.2f} "
              f"{c['core']:11.2f} {c['count']:8.0f}  {c['is_target']}")
    with_p = replay_selection(field, checks, shown, target, wstar, zi, mk.MarkerParams())
    without = replay_selection(field, checks, shown, target, wstar, zi, mk.MarkerParams(protect_m=0.0))
    print(f"\ntarget last seen as the nearest marker at {last_seen} s; checks in orbit without it "
          f"while its core was above the keep limit: {lost_while_alive}")
    print(f"replay of the selection: target leaves at {with_p} s with the protection, "
          f"{without} s without it; it dies at "
          f"{target.death - checks[0]['t'] + checks[0]['flown']:.0f} s")


def run_keep(api, minutes, msl, heading, seed, kmh, bank):
    lat, lon, _ = KHOB
    air_start(api, msl, kmh, heading, lat, lon)
    if seed is not None:
        api.set("xp_gliding/seed", seed)
    api.set(ENABLED, 1)
    wstar, zi = api.get("xp_gliding/wstar_ms"), api.get("xp_gliding/zi_m")
    seed = int(api.get("xp_gliding/seed"))
    zulu0 = api.get("sim/time/zulu_time_sec")
    sim0 = api.get(SIM_TIME)
    frame = LocalFrame(lat, lon)
    field = ThermalField(FieldConfig(seed=seed, day=int(api.get("sim/time/local_date_days")),
                                     sky=plugin_sky(api)), frame)
    field.update(zulu0, lat, lon)
    z = api.get(AGL)
    chosen = mk.select_markers(field, 0.0, 0.0, z, zulu0, wstar, zi)
    shown = {m.thermal for m in chosen}
    target = choose_target(chosen, zulu0)
    print(f"target: {target.distance_m:.0f} m away, core {target.core_ms:.2f} m/s at {z:.0f} m AGL, "
          f"dies in {target.thermal.death - zulu0:.0f} s; {len(chosen)} markers", flush=True)
    stream = XPlaneStream(api, WATCH)
    stream.wait_for(WATCH)
    oracle = KeptOrbit(api, field, zulu0, sim0, kmh, bank, wstar, zi, stream=stream,
                       target=target.thermal)
    pilot = Pilot(api, frame)
    try:
        reason, log = pilot.run(kmh, minutes * 60.0, settle_s=10.0, record=True,
                                min_agl=400.0, bank_limit=bank + 25.0, on_step=oracle.on_step)
    except Exception as exc:
        reason, log = f"aborted: {exc}", pilot.log_name
        release(api)
    print(f"keep: {reason}; log {log}", flush=True)
    print(marker_status(stream.snapshot()[0]))
    oracle.shots.finish()
    stream.close()
    report_keep(field, oracle.checks, shown, target.thermal, wstar, zi)


def main(argv=None):
    parser = argparse.ArgumentParser(description="xp-gliding training marker checks")
    parser.add_argument("test", choices=("look", "cost", "orbit", "keep", "report"))
    parser.add_argument("logs", nargs="*", help="flight logs (report)")
    parser.add_argument("--msl", type=float, default=2300.0, help="start altitude (m MSL)")
    parser.add_argument("--heading", type=float, default=90.0, help="true heading")
    parser.add_argument("--seconds", type=float, default=60.0, help="sim seconds per block")
    parser.add_argument("--blocks", type=int, default=3, help="pairs of blocks (cost)")
    parser.add_argument("--minutes", type=float, default=15.0, help="orbit duration")
    parser.add_argument("--seed", type=int, help="engine seed")
    parser.add_argument("--kmh", type=float, default=90.0, help="IAS (km/h)")
    parser.add_argument("--bank", type=float, default=45.0, help="circling bank (deg)")
    args = parser.parse_args(argv)
    if args.test == "report":
        report_orbit(args.logs)
        return
    api = XPlaneWebAPI(timeout=30.0)
    try:
        api.dataref_id(ENABLED)
    except (RuntimeError, KeyError):
        # At the main menu no dataref exists yet: load a flight first.
        air_start(api, 2800.0, 90.0, 0.0)
    original = read_settings(api)
    try:
        if args.test == "look":
            run_look(api, args.msl, args.heading, args.seconds, args.kmh)
        elif args.test == "cost":
            run_cost(api, args.msl, args.blocks, args.seconds, args.kmh)
        elif args.test == "keep":
            run_keep(api, args.minutes, args.msl, args.heading, args.seed, args.kmh, args.bank)
        else:
            run_orbit(api, args.minutes, args.msl, args.heading, args.seed, args.kmh, args.bank)
    finally:
        restore(api, original)


if __name__ == "__main__":
    main()
