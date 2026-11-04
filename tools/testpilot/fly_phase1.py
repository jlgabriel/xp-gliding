"""Phase 1 checks of the xp-gliding plugin, flown by the test pilot.

Usage (X-Plane running with the xp-gliding plugin and flight logger 0.3.0):
    python tools/testpilot/fly_phase1.py uniform [--only U90_1 ...]
    python tools/testpilot/fly_phase1.py fps [--only off w1]
    python tools/testpilot/fly_phase1.py roll
    python tools/testpilot/fly_phase1.py thermals [--minutes 20] [--msl 2300] [--seed 1]
    python tools/testpilot/fly_phase1.py orbit [--minutes 30] [--kmh 80] [--bank 45]
    python tools/testpilot/fly_phase1.py report [--orbit] LOG.csv ...

uniform: baseline test B with our physics. Each segment is an air start over
KHOB in calm, clear air (test A conditions, 541 kg) with the plugin's debug
mode `xp_gliding/debug/uniform_ms` (the same w everywhere), a settle and a
recorded stretch. Δvs is vs_te minus the test A polar at the same IAS, TAS and
bank; the energy force should give Δvs = w at every speed and bank. The
segments with w = 0 and thermals off check that the plugin adds nothing then.

fps: frame-rate independence. A w = 0 segment and a w = 1 m/s segment at
90 km/h, at the frame rate X-Plane runs at; X-Plane runs at 60 fps here (its
cap), and `--lock_fr=N` on its command line fixes another rate
(`restart_xplane.py -- --lock_fr=30`).

roll: sign of the gust roll moment. Wings level at 90 km/h with a constant
spanwise gradient (`xp_gliding/debug/dw_dy`); the test pilot's roll trim
integrator ends up holding the yoke that cancels the moment. More lift under
the right wing (dw/dy > 0) must roll the glider left, so it needs right yoke.

thermals: a thermal hunt in the engine's field (the plugin's own thermals,
native thermals at 0) with the same `ThermalHunter` as the native audit: cruise
on a course, circle when the total-energy netto says lift, centre with the
rule of thumb, leave when it weakens. Every circle is framed by two marks;
`report` compares, per circle, the measured netto with the engine's lift at
the glider (`xpg_lift_ms`, logged by the flight logger 0.3.0).

orbit: the same comparison inside thermals, flown by an oracle. The rule-of-
thumb hunt above found no climbable thermal on 2026-11-03: its ~2 s vario lag
puts it past the narrow core before it turns, and its 35 deg, 90 km/h circle
(~110 m radius) is wider than most of the engine's updrafts. The test pilot
therefore builds the plugin's own field (pure Python, deterministic: same
seed, X-Plane's date and zulu time, same thermals), picks the best thermal
within reach, flies to it and orbits its centre at the radius the bank and
speed give (`control.OrbitHold`). A first circle with the thermals off gives
the glider's own circling sink at that bank and speed, so the netto needs no
polar model. Every circle is framed by two marks (the first one is that
reference); `report --orbit` subtracts it.

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
from analyze_flightlog import flying_rows, linear_slope, load_rows  # noqa: E402
from audit_native import ThermalHunter  # noqa: E402
from control import Circle, Gains, OrbitHold  # noqa: E402
from pilot import LOG_DIR, Pilot, release  # noqa: E402
from polar import polar_sink  # noqa: E402
from xp_gliding.engine.field import FieldConfig, ThermalField  # noqa: E402
from xp_gliding.engine.geo import LocalFrame  # noqa: E402
from xpweb import XPlaneWebAPI  # noqa: E402

G = 9.80665
PREFIX = "xp_gliding/"
SETTINGS = ("enabled", "thermals_enabled", "roll_enabled", "helix_enabled", "markers_enabled",
            "wstar_ms", "zi_m", "seed", "debug/uniform_ms", "debug/dw_dy")

# (name, IAS km/h, uniform w m/s, thermals on, bank deg, helix correction on)
UNIFORM = (
    ("A90_off", 90.0, 0.0, 0, 0.0, 1),
    ("U90_1", 90.0, 1.0, 1, 0.0, 1),
    ("U90_2", 90.0, 2.0, 1, 0.0, 1),
    ("U90_3", 90.0, 3.0, 1, 0.0, 1),
    ("A120_off", 120.0, 0.0, 0, 0.0, 1),
    ("U120_1", 120.0, 1.0, 1, 0.0, 1),
    ("U120_2", 120.0, 2.0, 1, 0.0, 1),
    ("U120_3", 120.0, 3.0, 1, 0.0, 1),
    ("A90_c35_off", 90.0, 0.0, 0, 35.0, 1),
    ("U90_c35_2", 90.0, 2.0, 1, 35.0, 1),
    ("U90_c35_2_nohelix", 90.0, 2.0, 1, 35.0, 0),
)

ROLL = (("R0", 0.0), ("R+", 0.03), ("R-", -0.03))

# (name, uniform w m/s, thermals on). The frame rate is X-Plane's own: launch
# it with `--lock_fr=N` (restart_xplane.py -- --lock_fr=30). Each rate gets its
# own w = 0 reference, since the glider's own sink may change with it too.
FPS = (
    ("off", 0.0, 0),
    ("w1", 1.0, 1),
)


def segment_stats(rows):
    t = [r["t_run_s"] for r in rows]
    he = [r["elev_m"] + r["tas_ms"] ** 2 / (2 * G) for r in rows]
    ias = statistics.fmean(r["ias_kt"] for r in rows) * 1.852
    tas = statistics.fmean(r["tas_ms"] for r in rows)
    bank = statistics.fmean(abs(r["phi_deg"]) for r in rows)
    periods = [r["frame_period_s"] for r in rows if r["frame_period_s"]]

    def mean(col):
        vals = [r[col] for r in rows if r.get(col) is not None]
        return statistics.fmean(vals) if vals else float("nan")

    vs_te = linear_slope(t, he)
    still = -polar_sink(ias, tas, bank)
    # Measured 2026-11-03 (A90_c35_off): circling at 35 deg and 90 km/h the ASK 21
    # sinks 1.54 m/s where the polar's cos^-1.5 turn model says 1.36. Scale that
    # empirical excess with sin^2(bank) for the circles of a thermal hunt.
    circle_factor = 1.0 + (1.54 / 1.36 - 1.0) * (math.sin(math.radians(bank))
                                                 / math.sin(math.radians(35.0))) ** 2
    return {
        "seconds": t[-1] - t[0], "vs_te": vs_te, "ias": ias, "tas": tas, "bank": bank,
        "still_air": still, "netto": vs_te - still,
        "netto_circle": vs_te - still * circle_factor,
        "fps": 1 / statistics.fmean(periods), "mass": mean("mass_kg"),
        "agl": mean("agl_m"),
        "active": mean("xpg_active"), "lift": mean("xpg_lift_ms"),
        "force": mean("xpg_force_n"), "roll_nm": mean("xpg_roll_nm"),
        "frame_us": mean("xpg_frame_us"), "pre_faxil": mean("pre_faxil_n"),
        "post_faxil": mean("post_faxil_n"),
    }


def summarize(log):
    _, rows = load_rows(os.path.join(LOG_DIR, log))
    return segment_stats(flying_rows(rows))


def read_settings(api):
    return {name: api.get(PREFIX + name) for name in SETTINGS}


def restore(api, original):
    for name, value in original.items():
        api.set(PREFIX + name, value)


def run_uniform(api, only, seconds, settle):
    results = []
    for name, kmh, w, thermals, bank, helix in UNIFORM:
        if only and name not in only:
            continue
        air_start(api, 2800.0, kmh, 0.0)
        api.set(PREFIX + "thermals_enabled", thermals)
        api.set(PREFIX + "helix_enabled", helix)
        api.set(PREFIX + "debug/uniform_ms", w)
        guidance = Circle(-bank) if bank else None
        pilot = Pilot(api)
        # A wide bank-integrator window, so that a roll-in overshoot cannot leave the
        # circle stuck at a steeper bank: the roll trim then reads the stick needed.
        gains = Gains(phi_i_window=20.0) if bank else None
        try:
            _, log = pilot.run(kmh, seconds, guidance, settle_s=settle, record=True, quiet=True,
                               bank_limit=bank + 15.0, gains=gains)
        except Exception as exc:
            print(f"{name}: aborted: {exc}", flush=True)
            release(api)
            continue
        finally:
            api.set(PREFIX + "debug/uniform_ms", 0.0)
            api.set(PREFIX + "thermals_enabled", 1)
            api.set(PREFIX + "helix_enabled", 1)
        s = summarize(log)
        s["roll_trim"] = pilot.ctrl.roll_trim
        results.append((name, kmh, w, bank, s, log))
        print(f"{name}: IAS {s['ias']:.1f}, bank {s['bank']:.1f}, vs_te {s['vs_te']:+.2f}, "
              f"still air {s['still_air']:+.2f}, delta {s['netto']:+.2f} m/s (w {w}); "
              f"force {s['force']:.0f} N, roll {s['roll_nm']:.0f} N m, roll trim "
              f"{s['roll_trim']:+.3f}, active {s['active']:.2f}, {s['frame_us']:.0f} us, "
              f"fps {s['fps']:.0f}; {log}", flush=True)
        time.sleep(1.0)
    print("\n| Segment | IAS (km/h) | Bank (deg) | w (m/s) | Force (N) | fps | vs_te (m/s) "
          "| Δvs vs A (m/s) |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- |")
    for name, kmh, w, bank, s, _ in results:
        print(f"| {name} | {s['ias']:.1f} | {s['bank']:.0f} | {w:.0f} | {s['force']:.0f} "
              f"| {s['fps']:.0f} | {s['vs_te']:+.2f} | {s['netto']:+.2f} |")


def run_fps(api, only, seconds, settle):
    results = []
    for name, w, thermals in FPS:
        if only and name not in only:
            continue
        air_start(api, 2800.0, 90.0, 0.0)
        api.set(PREFIX + "thermals_enabled", thermals)
        api.set(PREFIX + "debug/uniform_ms", w)
        try:
            _, log = Pilot(api).run(90.0, seconds, settle_s=settle, record=True, quiet=True)
        except Exception as exc:
            print(f"{name}: aborted: {exc}", flush=True)
            release(api)
            continue
        finally:
            api.set(PREFIX + "debug/uniform_ms", 0.0)
            api.set(PREFIX + "thermals_enabled", 1)
        s = summarize(log)
        results.append((name, w, s))
        print(f"{name}: fps {s['fps']:.1f}, IAS {s['ias']:.1f}, vs_te {s['vs_te']:+.3f}, "
              f"still air (test A) {s['still_air']:+.3f}; {log}", flush=True)
        time.sleep(1.0)
    print("\n| Segment | fps | IAS (km/h) | w (m/s) | vs_te (m/s) | Δvs vs test A (m/s) |")
    print("| --- | --- | --- | --- | --- | --- |")
    for name, w, s in results:
        print(f"| {name} | {s['fps']:.1f} | {s['ias']:.1f} | {w:.0f} | {s['vs_te']:+.3f} "
              f"| {s['netto']:+.3f} |")


def run_roll(api, seconds):
    for name, dwdy in ROLL:
        air_start(api, 2800.0, 90.0, 0.0)
        api.set(PREFIX + "debug/dw_dy", dwdy)
        pilot = Pilot(api)
        try:
            pilot.run(90.0, seconds, settle_s=seconds, quiet=True)
            trim = pilot.ctrl.roll_trim
        except Exception as exc:
            print(f"{name}: aborted: {exc}", flush=True)
            release(api)
            continue
        finally:
            api.set(PREFIX + "debug/dw_dy", 0.0)
        moment = api.get(PREFIX + "roll_nm")  # 0 again: debug mode is off now
        print(f"{name}: dw/dy {dwdy:+.3f} 1/s -> roll trim {trim:+.4f} (yoke ratio, + right)"
              f"{'' if moment == 0 else f', moment now {moment:.0f}'}", flush=True)
        time.sleep(1.0)


def run_thermals(api, minutes, msl, course, seed, kmh, bank):
    lat, lon, _ = KHOB
    air_start(api, msl, kmh, course, lat, lon)
    if seed is not None:
        api.set(PREFIX + "seed", seed)
    print(f"engine thermals: w* {api.get(PREFIX + 'wstar_ms'):.1f} m/s, zi "
          f"{api.get(PREFIX + 'zi_m'):.0f} m AGL, seed {api.get(PREFIX + 'seed')}; native "
          f"{api.get('sim/weather/region/thermal_rate_ms'):.2f} m/s", flush=True)
    hunter = ThermalHunter(api, course, bank=bank, min_cruise_s=10.0)
    pilot = Pilot(api, LocalFrame(lat, lon))
    try:
        reason, log = pilot.run(kmh, minutes * 60.0, hunter.cruise, settle_s=20.0, record=True,
                                min_agl=400.0, bank_limit=bank + 10.0, on_step=hunter.on_step)
    except Exception as exc:
        reason, log = f"aborted: {exc}", pilot.log_name
        release(api)
    print(f"hunt: {reason}; {len(hunter.circles)} circles; log {log}", flush=True)
    if log:
        report([log])


LOGGER_MARK = "xp_gliding/flightlog/mark"
TE = "sim/cockpit2/gauges/indicators/total_energy_fpm"
AGL = "sim/flightmodel/position/y_agl"
TAS = "sim/flightmodel/position/true_airspeed"
IAS = "sim/flightmodel/position/indicated_airspeed"
SIM_TIME = "sim/time/total_flight_time_sec"


class OracleOrbits:
    """Reference circle with the thermals off, then orbit the best thermals of
    the engine's field one after another (see the module docstring)."""

    def __init__(self, api, field, zulu0, sim0, kmh, bank, wstar, zi, reach_m=2500.0, ref_turns=3,
                 settle_turns=1.5, min_turns=3, max_turns=10, leave_ms=0.1, top_zzi=0.7):
        self.api, self.field, self.zulu0, self.sim0 = api, field, zulu0, sim0
        self.kmh = kmh
        self.bank, self.wstar, self.zi, self.reach = bank, wstar, zi, reach_m
        self.ref_turns, self.settle_turns = ref_turns, settle_turns
        self.min_turns, self.max_turns = min_turns, max_turns
        self.leave_ms, self.top_zzi = leave_ms, top_zzi
        self.state, self.since = "ref", None
        self.ref_circle = Circle(-bank)
        self.ref_te = []
        self.ref_sink = None
        self.orbit = None
        self.visited = set()
        self.turn_te, self.turns_done = [], 0
        self.circles = []

    def radius(self, tas):
        """tas: the commanded IAS as TAS (not the TAS of the moment, which can be
        far off after a strong thermal)."""
        return tas * tas / (G * math.tan(math.radians(self.bank)))

    def turn_s(self, tas):
        return 2.0 * math.pi * self.radius(tas) / tas

    def mark(self):
        self.api.command(LOGGER_MARK)

    def circle_mean(self, th, z, t, radius, points=24):
        total = 0.0
        for k in range(points):
            a = 2.0 * math.pi * k / points
            total += self.field.lift_at(th.e + radius * math.cos(a), th.n + radius * math.sin(a),
                                        z, t, self.wstar, self.zi)
        return total / points

    def select(self, pilot, z, t, tas):
        self.field.update(t, *pilot.frame.to_latlon(pilot.east, pilot.north))
        # Same field as the plugin's? Its nearest thermal is updated once a second.
        _, mine = self.field.nearest(pilot.east, pilot.north, t, 3000.0)
        print(f"  nearest thermal: {mine:.0f} m here, "
              f"{self.api.get(PREFIX + 'nearest/distance_m'):.0f} m in the plugin", flush=True)
        radius = self.radius(tas)
        best, best_score, best_climb = None, -math.inf, 0.0
        for th in self.field.alive(t):
            if id(th) in self.visited or th.death - t < 600.0:
                continue
            d = math.hypot(th.e - pilot.east, th.n - pilot.north)
            if d > self.reach or self.field.lift_at(th.e, th.n, z, t, self.wstar, self.zi) < 1.0:
                continue
            climb = self.circle_mean(th, z, t, radius) - self.ref_sink
            score = climb - 0.0002 * d  # 0.5 m/s for 2.5 km of glide
            if score > best_score:
                best, best_score, best_climb = th, score, climb
        if best is None:
            raise RuntimeError("no thermal within reach")
        self.visited.add(id(best))
        self.orbit = OrbitHold((best.e, best.n), radius, tas, direction=-1, max_trim=10.0)
        d = math.hypot(best.e - pilot.east, best.n - pilot.north)
        self.circles.append({"predicted": best_climb, "distance": d})
        print(f"  {pilot.flown:6.0f}s target {d:.0f} m away, predicted climb {best_climb:+.2f} m/s "
              f"(radius {radius:.0f} m, AGL {z:.0f})", flush=True)
        pilot.guidance = self.orbit
        self.state, self.since = "approach", None

    def on_step(self, v, pilot):
        t = self.zulu0 + v[SIM_TIME] - self.sim0
        z, te = v[AGL], v[TE] * 0.00508
        ias_ms = v[IAS] * 0.514444
        tas = self.kmh / 3.6 * (v[TAS] / ias_ms if ias_ms > 10.0 else 1.0)
        now = pilot.flown
        if self.state == "ref":
            pilot.guidance = self.ref_circle
            if self.since is None and now >= 30.0:  # rolled in, logger on since 20 s
                self.since = now
                self.mark()
            if self.since is not None:
                self.ref_te.append(te)
                if now - self.since >= self.ref_turns * self.turn_s(tas):
                    self.mark()
                    self.ref_sink = -statistics.fmean(self.ref_te)
                    self.api.set(PREFIX + "thermals_enabled", 1)
                    print(f"  {now:6.0f}s reference circle: vs_te {-self.ref_sink:+.2f} m/s; "
                          f"thermals on", flush=True)
                    self.select(pilot, z, t, tas)
        elif self.state == "approach":
            if self.since is None and self.orbit.distance(pilot.east, pilot.north) < (
                    1.5 * self.orbit.radius):
                self.since = now
            if self.since is not None and now - self.since >= self.settle_turns * self.turn_s(tas):
                self.state, self.since = "orbit", now
                self.turn_te, self.turns_done = [], 0
                self.mark()
        elif self.state == "orbit":
            self.turn_te.append(te)
            if now - self.since >= (self.turns_done + 1) * self.turn_s(tas):
                self.turns_done += 1
                avg = statistics.fmean(self.turn_te)
                self.turn_te = []
                d = self.orbit.distance(pilot.east, pilot.north)
                print(f"  {now:6.0f}s turn {self.turns_done}: vs_te {avg:+.2f} m/s, AGL {z:.0f}, "
                      f"{d:.0f} m from the centre", flush=True)
                if self.turns_done >= self.max_turns or z > self.top_zzi * self.zi or (
                        self.turns_done >= self.min_turns and avg < self.leave_ms):
                    self.mark()
                    self.circles[-1].update(turns=self.turns_done, agl=z)
                    self.select(pilot, z, t, tas)


def run_orbit(api, minutes, msl, course, seed, kmh, bank):
    lat, lon, _ = KHOB
    air_start(api, msl, kmh, course, lat, lon)
    if seed is not None:
        api.set(PREFIX + "seed", seed)
    api.set(PREFIX + "thermals_enabled", 0)  # for the reference circle
    wstar, zi = api.get(PREFIX + "wstar_ms"), api.get(PREFIX + "zi_m")
    seed = int(api.get(PREFIX + "seed"))
    day = int(api.get("sim/time/local_date_days"))
    zulu0, sim0 = api.get("sim/time/zulu_time_sec"), api.get(SIM_TIME)
    frame = LocalFrame(lat, lon)
    field = ThermalField(FieldConfig(seed=seed, day=day), frame)
    print(f"engine thermals: w* {wstar:.1f} m/s, zi {zi:.0f} m AGL, seed {seed}, day {day}; "
          f"orbits at {bank:.0f} deg and {kmh:.0f} km/h", flush=True)
    oracle = OracleOrbits(api, field, zulu0, sim0, kmh, bank, wstar, zi)
    pilot = Pilot(api, frame)
    try:
        reason, log = pilot.run(kmh, minutes * 60.0, oracle.ref_circle, settle_s=20.0,
                                record=True, min_agl=400.0, bank_limit=bank + 25.0,
                                on_step=oracle.on_step)
    except Exception as exc:
        reason, log = f"aborted: {exc}", pilot.log_name
        release(api)
    print(f"orbits: {reason}; {len(oracle.circles)} thermals; log {log}", flush=True)
    for i, c in enumerate(oracle.circles, 1):
        print(f"  thermal {i}: {c['distance']:.0f} m away, predicted {c['predicted']:+.2f} m/s, "
              f"{c.get('turns', 0)} turns", flush=True)
    if log:
        report_orbit([log])


def circles(rows):
    """Rows of each circle: between an odd mark and the next even one."""
    out, current = [], None
    for r in rows:
        m = int(r["mark"] or 0)
        if m % 2 == 1:
            if current is None or current[0] != m:
                current = (m, [])
                out.append(current)
            current[1].append(r)
    return out


def report(logs):
    print("\n| Log | Circle | Turns | Bank (deg) | IAS (km/h) | AGL (m) | vs_te (m/s) "
          "| Netto, polar model (m/s) | Netto, measured circle sink (m/s) | Engine lift (m/s) "
          "| Difference (m/s) |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for log in logs:
        _, rows = load_rows(log if os.path.isabs(log) else os.path.join(LOG_DIR, log))
        rows = flying_rows(rows)
        for mark, crows in circles(rows):
            # Skip the first 10 s (rolling in), keep whole turns of the rest.
            t0 = crows[0]["t_run_s"] + 10.0
            crows = [r for r in crows if r["t_run_s"] >= t0]
            if len(crows) < 100:
                continue
            s = segment_stats(crows)
            turns = s["seconds"] / 27.0
            print(f"| {os.path.basename(log)} | {mark // 2 + 1} | {turns:.1f} | {s['bank']:.0f} "
                  f"| {s['ias']:.0f} | {s['agl']:.0f} | {s['vs_te']:+.2f} | {s['netto']:+.2f} "
                  f"| {s['netto_circle']:+.2f} | {s['lift']:+.2f} "
                  f"| {s['netto_circle'] - s['lift']:+.2f} |")


def report_orbit(logs):
    """Like report(), with the glider's sink measured: the first circle is the
    reference with the thermals off, and each circle's sink is the polar's
    turn model at its own IAS, TAS and bank, scaled so that it matches the
    reference exactly (the orbits do not hold the reference's bank and speed
    to the degree)."""
    print("\n| Log | Circle | Turns | Bank (deg) | IAS (km/h) | AGL (m) | vs_te (m/s) "
          "| Netto, measured (m/s) | Engine lift (m/s) | Difference (m/s) | frame_us |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for log in logs:
        _, rows = load_rows(log if os.path.isabs(log) else os.path.join(LOG_DIR, log))
        rows = flying_rows(rows)
        scale = None
        for mark, crows in circles(rows):
            s = segment_stats(crows)
            turn = 2.0 * math.pi * s["tas"] / (G * math.tan(math.radians(s["bank"])))
            name = os.path.basename(log)
            model = polar_sink(s["ias"], s["tas"], s["bank"])
            if scale is None:
                scale = -s["vs_te"] / model
                print(f"| {name} | ref | {s['seconds'] / turn:.1f} | {s['bank']:.0f} "
                      f"| {s['ias']:.0f} | {s['agl']:.0f} | {s['vs_te']:+.2f} | | {s['lift']:+.2f} "
                      f"| | {s['frame_us']:.0f} |")
                print(f"(reference sink {-s['vs_te']:.2f} m/s = {scale:.3f} x the turn model)")
                continue
            netto = s["vs_te"] + scale * model
            print(f"| {name} | {mark // 2} | {s['seconds'] / turn:.1f} | {s['bank']:.0f} "
                  f"| {s['ias']:.0f} | {s['agl']:.0f} | {s['vs_te']:+.2f} | {netto:+.2f} "
                  f"| {s['lift']:+.2f} | {netto - s['lift']:+.2f} | {s['frame_us']:.0f} |")


def main(argv=None):
    parser = argparse.ArgumentParser(description="xp-gliding phase 1 checks")
    parser.add_argument("test", choices=("uniform", "fps", "roll", "thermals", "orbit",
                                         "report"))
    parser.add_argument("logs", nargs="*", help="flight logs (report)")
    parser.add_argument("--only", nargs="*", help="segment names (uniform)")
    parser.add_argument("--seconds", type=float, default=75.0, help="sim seconds per segment")
    parser.add_argument("--settle", type=float, default=40.0, help="seconds before recording")
    parser.add_argument("--minutes", type=float, default=20.0, help="thermal hunt duration")
    parser.add_argument("--orbit", action="store_true", help="report: logs of the orbit test")
    parser.add_argument("--msl", type=float, default=2300.0, help="hunt start altitude (m MSL)")
    parser.add_argument("--course", type=float, default=90.0, help="hunt cruise course")
    parser.add_argument("--seed", type=int, help="engine seed for the hunt")
    parser.add_argument("--kmh", type=float, help="IAS (km/h; thermals 90, orbit 80)")
    parser.add_argument("--bank", type=float, help="circling bank (deg; thermals 35, orbit 45)")
    args = parser.parse_args(argv)
    if args.test == "report":
        (report_orbit if args.orbit else report)(args.logs)
        return
    orbit = args.test == "orbit"
    kmh = args.kmh or (80.0 if orbit else 90.0)
    bank = args.bank or (45.0 if orbit else 35.0)
    api = XPlaneWebAPI(timeout=30.0)
    try:
        api.dataref_id(PREFIX + "enabled")
    except (RuntimeError, KeyError):
        # At the main menu no dataref exists yet: load a flight first.
        air_start(api, 2800.0, 90.0, 0.0)
    original = read_settings(api)
    if original["enabled"] != 1:
        raise SystemExit("xp-gliding is not enabled (xp_gliding/enabled is 0)")
    try:
        if args.test == "uniform":
            run_uniform(api, set(args.only or ()), args.seconds, args.settle)
        elif args.test == "fps":
            run_fps(api, set(args.only or ()), args.seconds, args.settle)
        elif args.test == "roll":
            run_roll(api, 40.0)
        elif orbit:
            run_orbit(api, args.minutes, args.msl, args.course, args.seed, kmh, bank)
        else:
            run_thermals(api, args.minutes, args.msl, args.course, args.seed, kmh, bank)
    finally:
        restore(api, original)


if __name__ == "__main__":
    main()
