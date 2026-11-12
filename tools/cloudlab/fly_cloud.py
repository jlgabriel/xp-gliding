"""Drive the cloud lab (`PI_xpg_cloudlab.py`) by hand, one step at a time.

Usage:
    python tools/cloudlab/fly_cloud.py install [--version 1]
    python tools/cloudlab/fly_cloud.py gen --version 2     (a new look, no restart needed)
    python tools/cloudlab/fly_cloud.py gen --version 3 --order   (the objects of make_order.py)
    python tools/cloudlab/fly_cloud.py gen --version 4 --plugin [--rev REV]   (the plugin's own)
    python tools/cloudlab/fly_cloud.py fly [--msl 2400] [--heading 90] [--seconds 1800]
    python tools/cloudlab/fly_cloud.py do [name=value ...] [--view forward] [--shot] [--sample 30]

fly: air start and straight flight with the test pilot, in the background of the rest.
do: write `xpg_cloudlab/<name>` values in the order given, then optionally change the
view, take a screenshot (prints its file) and sample the frame rate and X-Plane's
estimate of the GPU's time per frame.

Measurement tool, not part of the plugin. License: GPL-3.0-or-later.
"""

import argparse
import glob
import os
import shutil
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(REPO, "tools", "testpilot"))
sys.path.insert(0, os.path.join(REPO, "tools", "hudlab"))
sys.path.insert(0, REPO)

import make_cloud  # noqa: E402
import make_order  # noqa: E402
from airstart import air_start  # noqa: E402
from pilot import Pilot  # noqa: E402
from thread_cpu import main_thread, thread_times, xplane_pid  # noqa: E402
from xpweb import XPlaneStream, XPlaneWebAPI  # noqa: E402

XPLANE = os.environ.get("XPLANE_DIR", r"D:\Laminar\XP12-Last-Release\X-Plane 12")
PLUGINS = os.path.join(XPLANE, "Resources", "plugins", "PythonPlugins")
LAB_DIR = os.path.join(PLUGINS, "xpg_cloudlab")
SHOTS = os.path.join(XPLANE, "Output", "screenshots")
PREFIX = "xpg_cloudlab/"
GPU_TIME = "sim/time/gpu_time_per_frame_sec_approx"
FRAME_PERIOD = "sim/operation/misc/frame_rate_period"
VIEWS = {"forward": "sim/view/forward_with_nothing", "cockpit": "sim/view/3d_cockpit_cmnd_look",
         "circle": "sim/view/circle", "back": "sim/view/back"}


def run_do(api, writes, view, shot, sample_s):
    for write in writes:
        name, value = write.split("=")
        api.set(PREFIX + name, float(value))
    if writes:
        time.sleep(0.5)
    print("instances", api.get(PREFIX + "instances"), "loaded", api.get(PREFIX + "loaded"),
          "errors", api.get(PREFIX + "errors"), flush=True)
    if view:
        api.command(VIEWS[view])
        time.sleep(1.0)
    if shot:
        before = set(glob.glob(os.path.join(SHOTS, "*.png")))
        api.command("sim/operation/screenshot")
        for _ in range(50):
            time.sleep(0.2)
            new = set(glob.glob(os.path.join(SHOTS, "*.png"))) - before
            if new:
                print("screenshot", new.pop(), flush=True)
                break
        else:
            print("no screenshot appeared", flush=True)
    if sample_s > 0.0:
        stream = XPlaneStream(api, (GPU_TIME, FRAME_PERIOD))
        stream.wait_for((GPU_TIME, FRAME_PERIOD))
        gpu, period = [], []
        tid = main_thread(xplane_pid())
        t0, cpu0 = time.monotonic(), thread_times(tid)[1]
        end = t0 + sample_s
        while time.monotonic() < end:
            time.sleep(0.2)
            values = stream.snapshot()[0]
            gpu.append(values[GPU_TIME] * 1000.0)
            period.append(values[FRAME_PERIOD] * 1000.0)
        cpu = (thread_times(tid)[1] - cpu0) / (time.monotonic() - t0) * 1e3
        stream.close()
        print(f"main thread {cpu:.0f} ms/s, frame {statistics.median(period):.2f} ms (worst sample {max(period):.1f}), "
              f"gpu {statistics.median(gpu):.2f} ms over {len(gpu)} samples", flush=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="what", required=True)
    p = sub.add_parser("install")
    p.add_argument("--version", type=int, default=1)
    p.add_argument("--order", action="store_true", help="write make_order.py's objects")
    p = sub.add_parser("gen")
    p.add_argument("--version", type=int, required=True)
    p.add_argument("--order", action="store_true", help="write make_order.py's objects")
    p.add_argument("--plugin", action="store_true", help="the plugin's own cumulus (kind 11)")
    p.add_argument("--rev", help="with --plugin: the git revision to take it from")
    p = sub.add_parser("fly")
    p.add_argument("--msl", type=float, default=2400.0)
    p.add_argument("--heading", type=float, default=90.0)
    p.add_argument("--seconds", type=float, default=1800.0)
    p.add_argument("--kmh", type=float, default=90.0)
    p = sub.add_parser("do")
    p.add_argument("writes", nargs="*")
    p.add_argument("--view", choices=sorted(VIEWS))
    p.add_argument("--shot", action="store_true")
    p.add_argument("--sample", type=float, default=0.0)
    args = parser.parse_args(argv)

    if args.what in ("install", "gen"):
        writer = make_order if args.order else make_cloud
        if args.what == "install":
            shutil.copy(os.path.join(HERE, "PI_xpg_cloudlab.py"), PLUGINS)
        if getattr(args, "plugin", False):
            print("wrote", make_cloud.write_plugin(LAB_DIR, args.version, args.rev), "in", LAB_DIR)
        else:
            print("wrote", writer.write_all(LAB_DIR, args.version), "in", LAB_DIR)
    elif args.what == "fly":
        api = XPlaneWebAPI(timeout=30.0)
        air_start(api, args.msl, args.kmh, args.heading)
        print("flying", flush=True)
        print(Pilot(api).run(args.kmh, args.seconds, quiet=True), flush=True)
    else:
        run_do(XPlaneWebAPI(timeout=30.0), args.writes, args.view, args.shot, args.sample)


if __name__ == "__main__":
    main()
