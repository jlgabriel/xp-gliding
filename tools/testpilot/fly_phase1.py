"""Phase 1 checks of the xp-gliding plugin, flown by the test pilot.

Usage (X-Plane running with the xp-gliding plugin and flight logger 0.3.0):
    python tools/testpilot/fly_phase1.py uniform [--only U90_1 ...]
    python tools/testpilot/fly_phase1.py fps [--only off w1]
    python tools/testpilot/fly_phase1.py roll
    python tools/testpilot/fly_phase1.py thermals [--minutes 20] [--msl 2300] [--seed 1]
    python tools/testpilot/fly_phase1.py report LOG.csv ...

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
from control import Circle, Gains  # noqa: E402
from pilot import LOG_DIR, Pilot, release  # noqa: E402
from polar import polar_sink  # noqa: E402
from xp_gliding.engine.geo import LocalFrame  # noqa: E402
from xpweb import XPlaneWebAPI  # noqa: E402

G = 9.80665
PREFIX = "xp_gliding/"
SETTINGS = ("enabled", "thermals_enabled", "roll_enabled", "helix_enabled", "wstar_ms", "zi_m",
            "seed", "debug/uniform_ms", "debug/dw_dy")

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


def main(argv=None):
    parser = argparse.ArgumentParser(description="xp-gliding phase 1 checks")
    parser.add_argument("test", choices=("uniform", "fps", "roll", "thermals", "report"))
    parser.add_argument("logs", nargs="*", help="flight logs (report)")
    parser.add_argument("--only", nargs="*", help="segment names (uniform)")
    parser.add_argument("--seconds", type=float, default=75.0, help="sim seconds per segment")
    parser.add_argument("--settle", type=float, default=40.0, help="seconds before recording")
    parser.add_argument("--minutes", type=float, default=20.0, help="thermal hunt duration")
    parser.add_argument("--msl", type=float, default=2300.0, help="hunt start altitude (m MSL)")
    parser.add_argument("--course", type=float, default=90.0, help="hunt cruise course")
    parser.add_argument("--seed", type=int, help="engine seed for the hunt")
    parser.add_argument("--kmh", type=float, default=90.0, help="hunt IAS (km/h)")
    parser.add_argument("--bank", type=float, default=35.0, help="hunt circling bank (deg)")
    args = parser.parse_args(argv)
    if args.test == "report":
        report(args.logs)
        return
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
        else:
            run_thermals(api, args.minutes, args.msl, args.course, args.seed, args.kmh, args.bank)
    finally:
        restore(api, original)


if __name__ == "__main__":
    main()
