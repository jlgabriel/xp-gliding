"""Measure each drawing method of `PI_xpg_hudlab.py` in a running X-Plane.

Usage:
    python tools/hudlab/measure_hud.py [--seconds 20] [--modes 0 1 2 3 4 5 6 7]
                                       [--toggle-command RCHud/toggleHUD]

Needs a flight loaded and the lab plugin installed. For each mode: switch, let it settle,
reset the lab's statistics, wait, and print a Markdown row. `--toggle-command` measures
another plugin's HUD instead: mode 0 with the command fired once before the second row
(it must start shown or hidden as the first row says).

Mode 7 (imgui) comes last on purpose: never use XPPython3's "Reload scripts" after it.

Measurement tool, not part of the plugin. License: GPL-3.0-or-later.
"""

import argparse
import os
import statistics
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "testpilot"))

from xpweb import XPlaneWebAPI  # noqa: E402

LAB = "xp_gliding/hudlab/"
SETTLE_S = 3.0


def measure(api, seconds):
    api.set(LAB + "reset", 1)
    gpu, frame = [], []
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        gpu.append(api.get("sim/time/gpu_time_per_frame_sec_approx") * 1e3)
        frame.append(api.get("sim/time/framerate_period") * 1e3)
        time.sleep(0.5)
    time.sleep(1.2)  # the lab publishes once a second
    return {
        "draw_p50": api.get(LAB + "draw_us_p50"), "draw_p99": api.get(LAB + "draw_us_p99"),
        "window_p50": api.get(LAB + "window_us_p50"), "window_p99": api.get(LAB + "window_us_p99"),
        "draws": api.get(LAB + "draws_per_s"),
        "gpu": statistics.median(gpu), "frame": statistics.median(frame),
    }


def row(label, m):
    per_second = m["draw_p50"] * m["draws"] / 1e3
    print(f"| {label} | {m['draw_p50']:.0f} | {m['draw_p99']:.0f} | {m['draws']:.0f} "
          f"| {per_second:.1f} | {m['window_p50']:.0f} | {m['window_p99']:.0f} "
          f"| {m['gpu']:.2f} | {m['frame']:.2f} |", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seconds", type=float, default=20.0)
    parser.add_argument("--modes", type=int, nargs="*", default=[0, 1, 2, 3, 4, 5, 6, 0, 7, 0])
    parser.add_argument("--toggle-command")
    args = parser.parse_args()
    api = XPlaneWebAPI()
    print("| Method | Draw p50 (µs) | Draw p99 (µs) | Draws/s | ms CPU per s | Phase_Window p50 (µs) "
          "| Phase_Window p99 (µs) | GPU (ms) | Frame (ms) |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    if args.toggle_command:
        api.set(LAB + "mode", 0)
        for label in ("as it started", "after the toggle", "toggled back"):
            time.sleep(SETTLE_S)
            row(f"{args.toggle_command}: {label}", measure(api, args.seconds))
            api.command(args.toggle_command)
        return
    for mode in args.modes:
        api.set(LAB + "mode", mode)
        time.sleep(SETTLE_S)
        row(f"mode {mode}", measure(api, args.seconds))
    api.set(LAB + "mode", 0)


if __name__ == "__main__":
    main()
