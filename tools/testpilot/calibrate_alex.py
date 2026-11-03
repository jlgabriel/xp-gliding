"""Baseline tests B and C (Alex Ferrer's calibration mode) flown by the test pilot.

Usage (X-Plane running with flight logger 0.2.0 or later, which exposes
Alex's settings as `xp_gliding/flightlog/alex_*` datarefs):
    python tools/testpilot/calibrate_alex.py [--only B90_1 ...] [--seconds 30]

Each segment is an air start over KHOB in calm, clear air (test A
conditions), Alex's plugin enabled in calibration mode with the slider and
factors of that segment, a settle, and a recorded stretch at a fixed IAS.
The result is vs_te against test A at the same IAS (docs/baseline.md). Alex's
original settings are read first and written back at the end, whatever
happens, because his plugin saves them to init_values.json when X-Plane
closes.

Measurement tool, not part of the plugin. License: GPL-3.0-or-later.
"""

import argparse
import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "flightlog"))

from airstart import air_start  # noqa: E402
from analyze_flightlog import flying_rows, linear_slope, load_rows  # noqa: E402
from pilot import LOG_DIR, Pilot, release  # noqa: E402
from polar import polar_sink  # noqa: E402
from xpweb import XPlaneWebAPI  # noqa: E402

G = 9.80665
PREFIX = "xp_gliding/flightlog/"
SETTINGS = ("alex_enabled", "alex_cal_mode", "alex_cal_ms", "alex_lift_factor",
            "alex_thrust_factor")

# (name, IAS km/h, slider m/s, lift factor, thrust factor)
SEGMENTS = (
    ("B90_1", 90.0, 1, 14, 19),
    ("B90_2", 90.0, 2, 14, 19),
    ("B90_3", 90.0, 3, 14, 19),
    ("B120_1", 120.0, 1, 14, 19),
    ("B120_2", 120.0, 2, 14, 19),
    ("B120_3", 120.0, 3, 14, 19),
    ("C90_lift", 90.0, 1, 14, 0),
    ("C90_thrust", 90.0, 1, 0, 19),
)


def summarize(log):
    _, rows = load_rows(os.path.join(LOG_DIR, log))
    rows = flying_rows(rows)
    t = [r["t_run_s"] for r in rows]
    he = [r["elev_m"] + r["tas_ms"] ** 2 / (2 * G) for r in rows]
    ias = statistics.fmean(r["ias_kt"] for r in rows) * 1.852
    tas = statistics.fmean(r["tas_ms"] for r in rows)
    periods = [r["frame_period_s"] for r in rows if r["frame_period_s"]]
    return {
        "vs_te": linear_slope(t, he), "ias": ias, "tas": tas,
        "still_air": -polar_sink(ias, tas),
        "fps": 1 / statistics.fmean(periods),
        "pre_fnrml": statistics.fmean(r["pre_fnrml_n"] for r in rows),
        "post_fnrml": statistics.fmean(r["post_fnrml_n"] for r in rows),
        "pre_faxil": statistics.fmean(r["pre_faxil_n"] for r in rows),
        "post_faxil": statistics.fmean(r["post_faxil_n"] for r in rows),
        "alex_cal": statistics.fmean(r["alex_cal_mode"] for r in rows),
        "mass": statistics.fmean(r["mass_kg"] for r in rows),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description="Alex's calibration mode, tests B and C")
    parser.add_argument("--only", nargs="*", help="segment names")
    parser.add_argument("--seconds", type=float, default=75.0, help="sim seconds per segment")
    parser.add_argument("--settle", type=float, default=40.0, help="seconds before recording")
    args = parser.parse_args(argv)
    api = XPlaneWebAPI(timeout=30.0)
    original = {name: api.get(PREFIX + name) for name in SETTINGS}
    print(f"Alex's settings before: {original}", flush=True)
    if original["alex_enabled"] < 0:
        raise SystemExit("Alex's plugin is not loaded (the datarefs read -1)")
    results = []
    try:
        for name, kmh, cal, lift_f, thrust_f in SEGMENTS:
            if args.only and name not in args.only:
                continue
            air_start(api, 2800.0, kmh, 0.0)
            for key, value in (("alex_lift_factor", lift_f), ("alex_thrust_factor", thrust_f),
                               ("alex_cal_ms", cal), ("alex_cal_mode", 1), ("alex_enabled", 1)):
                api.set(PREFIX + key, value)
            try:
                _, log = Pilot(api).run(kmh, args.seconds, settle_s=args.settle, record=True,
                                        quiet=True)
            except Exception as exc:
                print(f"{name}: aborted: {exc}", flush=True)
                release(api)
                continue
            finally:
                api.set(PREFIX + "alex_cal_mode", 0)
            s = summarize(log)
            delta = s["vs_te"] - s["still_air"]
            results.append((name, kmh, cal, lift_f, thrust_f, s, delta, log))
            print(f"{name}: IAS {s['ias']:.1f}, vs_te {s['vs_te']:+.2f}, still air "
                  f"{s['still_air']:+.2f}, delta {delta:+.2f} m/s; fps {s['fps']:.0f}; "
                  f"fnrml pre/post {s['pre_fnrml']:.0f}/{s['post_fnrml']:.0f} N, faxil "
                  f"{s['pre_faxil']:.0f}/{s['post_faxil']:.0f} N; cal {s['alex_cal']:.2f}; "
                  f"{log}", flush=True)
            time.sleep(1.0)
    finally:
        for name in SETTINGS:
            api.set(PREFIX + name, original[name])
        print(f"Alex's settings restored: "
              f"{ {name: api.get(PREFIX + name) for name in SETTINGS} }", flush=True)
    print("\n| Test | IAS (km/h) | Slider (m/s) | Lift / thrust factor | fps | vs_te (m/s) "
          "| delta vs A (m/s) |")
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for name, kmh, cal, lift_f, thrust_f, s, delta, _ in results:
        print(f"| {name[0]} | {kmh:.0f} | {cal} | {lift_f} / {thrust_f} | {s['fps']:.0f} "
              f"| {s['vs_te']:+.2f} | {delta:+.2f} |")


if __name__ == "__main__":
    main()
