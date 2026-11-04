"""Measure each drawing method of `PI_xpg_hudlab.py` in a running X-Plane.

Usage:
    python tools/hudlab/measure_hud.py [--cycles 6] [--seconds 8] [--modes 1 2 3 4 8 5 6 7]
                                       [--hud-command RCHud/toggleHUD]

Needs a flight loaded and the lab plugin installed; pause the sim first, so that the
scenery under a moving glider does not add to the noise. Each method is flown as paired
stretches, off then on, because the frame rate cap hides a small cost in the frame time.
The cost reads as the difference in CPU time of X-Plane's main thread and in its GPU time
estimate, median and spread over the pairs (one stray stretch must not decide a method). The
lab also times its own draw callback, which is far more precise where it applies.

`--hud-command` measures another plugin's HUD with the command that toggles it, expecting
it to start shown; the lab's modes stay off. The window is captured at the end of each method
into `--capture DIR` (X-Plane's own screenshot leaves 2D windows out).
Mode 7 (imgui) goes last on purpose: never use XPPython3's "Reload scripts" after it.

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

from thread_cpu import capture_window, main_thread, thread_times, xplane_pid  # noqa: E402
from xpweb import XPlaneWebAPI  # noqa: E402

LAB = "xp_gliding/hudlab/"
SETTLE_S = 2.0


def stretch(api, tid, seconds):
    """Main-thread CPU (ms per second) and median GPU time (ms) over one stretch."""
    gpu = []
    t0, cpu0 = time.monotonic(), thread_times(tid)[1]
    end = t0 + seconds
    while time.monotonic() < end:
        gpu.append(api.get("sim/time/gpu_time_per_frame_sec_approx") * 1e3)
        time.sleep(0.5)
    cpu = (thread_times(tid)[1] - cpu0) / (time.monotonic() - t0) * 1e3
    return cpu, statistics.median(gpu)


def median_spread(values):
    """Median and half the interquartile range."""
    low, _, high = statistics.quantiles(values, n=4)
    return statistics.median(values), (high - low) / 2.0


def run_method(api, tid, label, show, hide, cycles, seconds, read_lab, capture):
    cpu_diff, gpu_diff, draws, draw_p50, draw_p99 = [], [], [], [], []
    for _ in range(cycles):
        hide()
        time.sleep(SETTLE_S)
        cpu_off, gpu_off = stretch(api, tid, seconds)
        show()
        time.sleep(SETTLE_S)
        if read_lab:
            api.set(LAB + "reset", 1)
        cpu_on, gpu_on = stretch(api, tid, seconds)
        cpu_diff.append(cpu_on - cpu_off)
        gpu_diff.append(gpu_on - gpu_off)
        if read_lab:
            time.sleep(1.2)  # the lab publishes once a second
            draw_p50.append(api.get(LAB + "draw_us_p50"))
            draw_p99.append(api.get(LAB + "draw_us_p99"))
            draws.append(api.get(LAB + "draws_per_s"))
    if capture:
        capture_window(xplane_pid(), os.path.join(capture, label.replace("/", "_") + ".png"))
    hide()
    cpu, cpu_se = median_spread(cpu_diff)
    gpu, gpu_se = median_spread(gpu_diff)
    own = (f"{statistics.median(draw_p50):.0f} | {statistics.median(draw_p99):.0f} "
           f"| {statistics.median(draws):.0f}") if read_lab else "- | - | -"
    print(f"| {label} | {own} | {cpu:+.0f} ± {cpu_se:.0f} | {cpu / 60 * 1e3:+.0f} "
          f"| {gpu:+.2f} ± {gpu_se:.2f} |", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cycles", type=int, default=6)
    parser.add_argument("--seconds", type=float, default=8.0)
    parser.add_argument("--modes", type=int, nargs="*", default=[1, 2, 3, 4, 8, 5, 6, 7])
    parser.add_argument("--hud-command")
    parser.add_argument("--capture", help="folder for a capture of the window per method")
    args = parser.parse_args()
    api = XPlaneWebAPI()
    tid = main_thread(xplane_pid())
    print("| Method | Own draw p50 (µs) | Own draw p99 (µs) | Draws/s | Main thread (ms per s) "
          "| Same, per frame at 60 fps (µs) | GPU (ms per frame) |")
    print("| --- | --- | --- | --- | --- | --- | --- |")
    if args.hud_command:
        toggle = lambda: api.command(args.hud_command)
        api.set(LAB + "mode", 0)
        run_method(api, tid, args.hud_command, toggle, toggle, args.cycles, args.seconds, False,
                   args.capture)
        return
    for mode in args.modes:
        run_method(api, tid, f"mode {mode}", lambda m=mode: api.set(LAB + "mode", m),
                   lambda: api.set(LAB + "mode", 0), args.cycles, args.seconds, True, args.capture)


if __name__ == "__main__":
    main()
