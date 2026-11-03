"""Short side-by-side check of several gliders, flown by the test pilot.

Usage (X-Plane running with the xp-gliding plugin and flight logger 0.3.0):
    python tools/testpilot/fly_compare.py [--only laminar_ask21 shark ...] [--segments S90 C45]
    python tools/testpilot/fly_compare.py report [--segments ...] NAME=LOG.csv ...

Each glider gets one air start over KHOB at 2300 m MSL in calm, clear air
(test A conditions), the plugin's thermals off, and four recorded segments
in a row, each framed by two logger marks:

  S90   straight, 90 km/h        still-air sink and glide
  S120  straight, 120 km/h       the same, faster
  C45   circle at 45 deg, 90 km/h  circling sink, against the n^1.5 turn model
  U2    straight, 90 km/h, uniform lift 2 m/s (`xp_gliding/debug/uniform_ms`):
        the plugin's lift with no change for this aircraft, Δvs should be 2

About 4 minutes per glider. `--segments` flies (and reports) only some of
them, in the order given. The aircraft's own scripts may set its payload
(the NHAdrian ASK 21 does), so the report gives the mass it actually flew at.

Measurement tool, not part of the plugin. License: GPL-3.0-or-later.
"""

import argparse
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "flightlog"))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from airstart import KHOB, air_start  # noqa: E402
from analyze_flightlog import flying_rows, load_rows  # noqa: E402
from control import Circle, HeadingHold  # noqa: E402
from fly_phase1 import LOGGER_MARK, PREFIX, circles, segment_stats  # noqa: E402
from pilot import LOG_DIR, Pilot, release  # noqa: E402
from xp_gliding.adapter.aircraft import DEFAULT_GEOMETRY, read_acf_geometry  # noqa: E402
from xpweb import XPlaneWebAPI  # noqa: E402

XPLANE_DIR = os.environ.get("XPLANE_DIR", r"D:\Laminar\XP12-Last-Release\X-Plane 12")

# (name, .acf path relative to the X-Plane folder, kg per payload station)
GLIDERS = (
    ("laminar_ask21", "Aircraft/Laminar Research/Schleicher ASK 21/ASK21.acf", (90.2, 90.2)),
    ("shark", "Aircraft/STMA/HpH 304Sv12.3/HpH304s.acf", (90.0,)),
    ("nhadrian_ask21", "Aircraft/NHAdrian/ASK21_B21_NHA/ASK21.acf", (90.2, 90.2)),
    ("shark_claude", "Aircraft/STMA/HpH 304Sv12.3 - Claude/HpH304s.acf", (90.0,)),
)

# (name, IAS km/h, bank deg, uniform lift m/s, settle s, record s)
SEGMENTS = (
    ("S90", 90.0, 0.0, 0.0, 25.0, 30.0),
    ("S120", 120.0, 0.0, 0.0, 30.0, 30.0),
    ("C45", 90.0, 45.0, 0.0, 35.0, 35.0),
    ("U2", 90.0, 0.0, 2.0, 30.0, 30.0),
)
COURSE = 90.0


class Schedule:
    """Fly segments one after another, marking each recorded stretch."""

    def __init__(self, api, segments):
        self.api, self.segments = api, segments
        self.index, self.start, self.marked, self.started = 0, 0.0, False, False
        self.heading = HeadingHold(COURSE)

    def apply(self, pilot):
        name, kmh, bank, w, _, _ = self.segments[self.index]
        pilot.ctrl.set_target(kmh)
        pilot.guidance = Circle(-bank) if bank else self.heading
        self.api.set(PREFIX + "debug/uniform_ms", w)
        print(f"  {pilot.flown:5.0f}s {name}", flush=True)

    def on_step(self, v, pilot):
        if self.index >= len(self.segments):
            return
        if not self.started:
            self.started = True
            self.apply(pilot)
        _, _, _, _, settle, record = self.segments[self.index]
        t = pilot.flown - self.start
        if not self.marked and t >= settle:
            self.api.command(LOGGER_MARK)
            self.marked = True
        elif self.marked and t >= settle + record:
            self.api.command(LOGGER_MARK)
            self.marked = False
            self.index += 1
            self.start = pilot.flown
            if self.index < len(self.segments):
                self.apply(pilot)

    def done(self, v, pilot):
        return self.index >= len(self.segments)


def expected_span(path):
    g = read_acf_geometry(os.path.join(XPLANE_DIR, path))
    return (g or DEFAULT_GEOMETRY).span_m


def load(api, path, payload):
    """Air start in `path` and wait until the plugin reports its wing span."""
    lat, lon, _ = KHOB
    air_start(api, 2300.0, 90.0, COURSE, lat, lon, aircraft=path, payload_kg=payload,
              settle_s=0.0)
    span = expected_span(path)
    for _ in range(90):
        try:
            if abs(api.get(PREFIX + "span_m") - span) < 0.01:
                break
        except (RuntimeError, KeyError, OSError):
            pass
        time.sleep(1.0)
    else:
        raise RuntimeError(f"{path} did not load (span {span:.2f} m never reported)")
    # Let scenery and the aircraft's own scripts settle, with the glider frozen.
    api.command("sim/operation/pause_on")
    time.sleep(15.0)
    api.command("sim/operation/pause_off")


def fly(api, name, path, payload, segments):
    print(f"{name}: {path}", flush=True)
    load(api, path, payload)
    api.set(PREFIX + "thermals_enabled", 0)
    schedule = Schedule(api, segments)
    pilot = Pilot(api)
    total = sum(s[4] + s[5] for s in segments) + 5.0
    try:
        reason, log = pilot.run(90.0, total, schedule.heading, settle_s=20.0, record=True,
                                min_agl=400.0, bank_limit=60.0, on_step=schedule.on_step,
                                until=schedule.done)
    except Exception as exc:
        reason, log = f"aborted: {exc}", pilot.log_name
        release(api)
    api.set(PREFIX + "debug/uniform_ms", 0.0)
    print(f"{name}: {reason}; log {log}", flush=True)
    return log


def pick(names):
    """SEGMENTS with these names, in this order (all of them for None)."""
    if not names:
        return SEGMENTS
    by_name = {s[0]: s for s in SEGMENTS}
    return tuple(by_name[n] for n in names)


def report(named_logs, segments=SEGMENTS):
    print("\n| Glider | Mass (kg) | Span (m) | S90 sink (m/s) | S90 L/D | S120 sink (m/s) "
          "| S120 L/D | C45 sink (m/s) | C45 bank, IAS | C45 / S90 (model 1.68) | U2 dvs (m/s) "
          "| Plugin active |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for name, log in named_logs:
        _, rows = load_rows(log if os.path.isabs(log) else os.path.join(LOG_DIR, log))
        segs = {}
        for (mark, crows), seg in zip(circles(flying_rows(rows)), segments):
            segs[seg[0]] = segment_stats(crows)
        if len(segs) < len(segments):
            print(f"| {name} | incomplete: {', '.join(segs)} |")
            continue
        nan = {"vs_te": float("nan"), "tas": float("nan"), "ias": float("nan"),
               "bank": float("nan"), "mass": float("nan"), "active": float("nan")}
        s90, s120, c45, u2 = (segs.get(k, nan) for k in ("S90", "S120", "C45", "U2"))
        span = expected_span(dict((g[0], g[1]) for g in GLIDERS)[name])
        mass = next(seg["mass"] for seg in segs.values())
        print(f"| {name} | {mass:.0f} | {span:.2f} | {-s90['vs_te']:.2f} "
              f"| {s90['tas'] / -s90['vs_te']:.0f} | {-s120['vs_te']:.2f} "
              f"| {s120['tas'] / -s120['vs_te']:.0f} | {-c45['vs_te']:.2f} "
              f"| {c45['bank']:.0f} deg, {c45['ias']:.0f} | {c45['vs_te'] / s90['vs_te']:.2f} "
              f"| {u2['vs_te'] - s90['vs_te']:+.2f} | {u2['active']:.0f} |")
        print(f"|   (IAS) | | | {s90['ias']:.0f} | | {s120['ias']:.0f} | | | | | {u2['ias']:.0f} | |")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Short comparison of gliders")
    parser.add_argument("test", nargs="?", default="fly", choices=("fly", "report"))
    parser.add_argument("logs", nargs="*", help="report: NAME=LOG.csv")
    parser.add_argument("--only", nargs="*", help="glider names")
    parser.add_argument("--segments", nargs="*", help="segment names, in the order to fly")
    args = parser.parse_args(argv)
    segments = pick(args.segments)
    if args.test == "report":
        report([tuple(a.split("=", 1)) for a in args.logs], segments)
        return
    api = XPlaneWebAPI(timeout=30.0)
    logs = []
    try:
        for name, path, payload in GLIDERS:
            if args.only and name not in args.only:
                continue
            log = fly(api, name, path, payload, segments)
            if log:
                logs.append((name, log))
    finally:
        # The plugin's defaults; this mission changes nothing else.
        api.set(PREFIX + "thermals_enabled", 1)
        api.set(PREFIX + "debug/uniform_ms", 0.0)
    report(logs, segments)


if __name__ == "__main__":
    main()
