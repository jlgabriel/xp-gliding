"""Check the HUD's instruments in flight against the engine, the oracle they never read.

Usage:
    python tools/hudlab/watch_hud.py [--seconds 300] [--capture DIR]

Run it while the test pilot flies. It samples the HUD's datarefs through the web API and
prints, per bank band, the netto against the applied lift over stretches of 20 s, and the
HUD's cost. A capture of the window is saved every minute. The centring aid is checked by
`check_aid.py`, from the logs: its direction is measured from the circle's centre, which
this cannot see.

Measurement tool, not part of the plugin. License: GPL-3.0-or-later.
"""

import argparse
import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "testpilot"))

from thread_cpu import capture_window, xplane_pid  # noqa: E402
from xpweb import XPlaneWebAPI  # noqa: E402

G = "xp_gliding/"
NAMES = {"netto": G + "hud/netto_ms", "te": G + "hud/te_ms", "average": G + "hud/average_ms",
         "lift": G + "lift_ms", "valid": G + "hud/aid_valid", "amp": G + "hud/aid_amp_ms",
         "sample_us": G + "hud/sample_us",
         "draw_us": G + "hud/draw_us", "frame_us": G + "frame_us",
         "bank": "sim/flightmodel/position/phi", "agl": "sim/flightmodel/position/y_agl"}
STEP_S = 0.5
WINDOW_S = 20.0
BANDS = ((0, 15), (15, 35), (35, 60))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seconds", type=float, default=300.0)
    parser.add_argument("--capture", help="folder for one capture of the window per minute")
    args = parser.parse_args()
    api = XPlaneWebAPI()
    pid = xplane_pid()
    rows, stretch = [], []
    t0 = time.monotonic()
    next_capture = t0 + 30.0
    while time.monotonic() - t0 < args.seconds:
        v = {key: api.get(name) for key, name in NAMES.items()}
        rows.append(v)
        stretch.append(v)
        if len(stretch) >= WINDOW_S / STEP_S:
            print(f"{time.monotonic() - t0:5.0f}s AGL {v['agl']:5.0f} bank {v['bank']:+5.0f} "
                  f"te {v['te']:+.2f} netto {v['netto']:+.2f} avg {v['average']:+.2f} "
                  f"lift {statistics.fmean(s['lift'] for s in stretch):+.2f} "
                  f"aid {'on' if v['valid'] else '--'} amp {v['amp']:.2f}", flush=True)
            stretch = []
        if args.capture and time.monotonic() >= next_capture:
            next_capture += 60.0
            capture_window(pid, os.path.join(args.capture, f"hud_{time.monotonic() - t0:04.0f}.png"))
        time.sleep(STEP_S)

    chunks = [rows[i:i + int(WINDOW_S / STEP_S)] for i in range(0, len(rows), int(WINDOW_S / STEP_S))]
    print("\n| Bank (deg) | Stretches | Netto - lift (m/s) | spread |")
    print("| --- | --- | --- | --- |")
    for lo, hi in BANDS:
        err = [statistics.fmean(r["netto"] - r["lift"] for r in c) for c in chunks
               if lo <= abs(statistics.fmean(r["bank"] for r in c)) < hi]
        if len(err) > 1:
            print(f"| {lo}-{hi} | {len(err)} | {statistics.fmean(err):+.2f} | {statistics.stdev(err):.2f} |")
    for key in ("sample_us", "draw_us", "frame_us"):
        print(f"{key}: {statistics.median(r[key] for r in rows):.0f} µs (median of the ~1 s average)")


if __name__ == "__main__":
    main()
