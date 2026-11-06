"""Drive the shadow lab (`PI_xpg_shadowlab.py`), one step at a time.

Usage:
    python tools/shadowlab/fly_shadow.py install [--version 1]
    python tools/shadowlab/fly_shadow.py uninstall
    python tools/shadowlab/fly_shadow.py gen --version 2 [--size 1000] [--opacity 0.3] [--sky-lod 200000]
    python tools/shadowlab/fly_shadow.py start --at=khob|santiago|LAT,LON [--msl 2500] [--heading 0]
        [--hour 12] [--fly]
    python tools/shadowlab/fly_shadow.py do [name=value ...] [--view forward] [--shot] [--sample 30]
    python tools/shadowlab/fly_shadow.py sky --kind hidden|solid [--height 1200] [--distances 1,2,4,8,16,32] [--limit 20000]
    python tools/shadowlab/fly_shadow.py cost --count 20 [--spacing 2000] [--ahead 4000]
        [--at khob] [--msl 2800] [--blocks 3] [--seconds 60]
    python tools/shadowlab/fly_shadow.py cost --sky --count 20 --limit 20000 [--height 1200] ...

start: air start, then pause (the view stays put and the glider cannot sink) unless --fly, with
the plugin's own clouds off. do: write `xpg_shadowlab/<name>` values in the order given, then
optionally change the view, take a screenshot (prints its file) and sample the cost.
sky: a post on the ground and a disc in the sky just where the sun should throw the disc's shadow
onto the post's foot, then one screenshot from each distance (km) with the camera 30 degrees above
the ground there, for how far from the camera X-Plane's shadows reach. --limit first writes
X-Plane's private `shadow/csm/far_limit_{exterior,interior}` (250 m by default, lost on a restart).
cost: straight flight in alternating blocks: no shadows, still, all moved in one frame, moved a
slice per frame. Same method as `tools/testpilot/fly_clouds.py cost`: X-Plane's estimate of the
GPU's time per frame and the CPU time of the main thread, plus every frame's length as the lab's
flight loop saw it, so a hitch from moving shows up. With --sky the blocks are: no discs at the
default shadow limit, no discs at --limit, still hidden discs in the sky, and moved ones; the
limit goes back to its default at the end.

The install touches only the lab's own file and folder, never `xp_gliding`.

Measurement tool, not part of the plugin. License: GPL-3.0-or-later.
"""

import argparse
import glob
import math
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

import make_shadow  # noqa: E402
from airstart import KHOB, air_start, weather  # noqa: E402
from pilot import Pilot  # noqa: E402
from thread_cpu import main_thread, thread_times, xplane_pid  # noqa: E402
from xpweb import XPlaneStream, XPlaneWebAPI  # noqa: E402

XPLANE = os.environ.get("XPLANE_DIR", r"D:\Laminar\XP12-Last-Release\X-Plane 12")
PLUGINS = os.path.join(XPLANE, "Resources", "plugins", "PythonPlugins")
LAB_FILE = os.path.join(PLUGINS, "PI_xpg_shadowlab.py")
LAB_DIR = os.path.join(PLUGINS, "xpg_shadowlab")
SHOTS = os.path.join(XPLANE, "Output", "screenshots")
PREFIX = "xpg_shadowlab/"
GPU_TIME = "sim/time/gpu_time_per_frame_sec_approx"
FRAME_PERIOD = "sim/operation/misc/frame_rate_period"
PLUGIN_CLOUDS = "xp_gliding/clouds_enabled"
SUN_PITCH = "sim/graphics/scenery/sun_pitch_degrees"
SUN_HEADING = "sim/graphics/scenery/sun_heading_degrees"
SKY_KINDS = {"solid": 10, "hidden": 11}
# The outside views read one, the views from the seat (cockpit, forward) the other.
FAR_LIMITS = ("sim/private/controls/shadow/csm/far_limit_exterior",
              "sim/private/controls/shadow/csm/far_limit_interior")
DEFAULT_FAR_LIMIT = 250.0
SITES = {"khob": (KHOB[0], KHOB[1], KHOB[2]), "santiago": (-33.46, -70.65, 520.0)}
VIEWS = {"forward": "sim/view/forward_with_nothing", "cockpit": "sim/view/3d_cockpit_cmnd_look",
         "circle": "sim/view/circle", "back": "sim/view/back"}


def site(text):
    if text in SITES:
        return SITES[text]
    lat, lon = text.split(",")
    return float(lat), float(lon), 0.0


def screenshot(api):
    before = set(glob.glob(os.path.join(SHOTS, "*.png")))
    api.command("sim/operation/screenshot")
    for _ in range(50):
        time.sleep(0.2)
        new = set(glob.glob(os.path.join(SHOTS, "*.png"))) - before
        if new:
            path = new.pop()
            size = -1
            while size != os.path.getsize(path):  # X-Plane may still be writing it
                size = os.path.getsize(path)
                time.sleep(1.0)
            return path
    return None


def status(api):
    names = ("instances", "loaded", "errors", "ticks", "moves", "ground_m", "wet")
    return {name: round(api.get(PREFIX + name), 1) for name in names}


def timings(api):
    names = ("frame_ms_median", "frame_ms_p99", "frame_ms_max", "update_us_mean", "update_us_max")
    return {name: round(api.get(PREFIX + name), 2) for name in names}


def run_do(api, writes, view, shot, sample_s):
    for write in writes:
        name, value = write.split("=")
        api.set(PREFIX + name, float(value))
    if writes:
        time.sleep(0.5)
    print(status(api), flush=True)
    if view:
        api.command(VIEWS[view])
        time.sleep(1.0)
    if shot:
        print("screenshot", screenshot(api), flush=True)
    if sample_s > 0.0:
        print(sample(api, sample_s), flush=True)


def sample(api, seconds):
    stream = XPlaneStream(api, (GPU_TIME, FRAME_PERIOD))
    stream.wait_for((GPU_TIME, FRAME_PERIOD))
    gpu = []
    tid = main_thread(xplane_pid())
    api.set(PREFIX + "stats", 1)
    t0, cpu0 = time.monotonic(), thread_times(tid)[1]
    while time.monotonic() < t0 + seconds:
        time.sleep(0.2)
        gpu.append(stream.snapshot()[0][GPU_TIME] * 1e3)
    cpu = (thread_times(tid)[1] - cpu0) / (time.monotonic() - t0) * 1e3
    stream.close()
    return {"gpu_ms": round(statistics.median(gpu), 2), "main_thread_ms_s": round(cpu), **timings(api)}


def set_far_limit(api, metres):
    for name in FAR_LIMITS:
        api.set(name, metres)


def run_cost(api, count, spacing, ahead, at, msl, blocks, seconds, kmh, speed, sky=False, limit=None,
             height=1200.0):
    lat, lon, elev = site(at)
    air_start(api, msl, kmh, 90.0, lat=lat, lon=lon, wx=weather(lat, lon, elev))
    plugin_clouds(api, 0)
    api.command(VIEWS["forward"])
    api.set(PREFIX + "load", 1)
    time.sleep(3.0)
    # Off, still, then moved two ways: a block's shadows are placed anew ahead of the glider.
    modes = (("none", 0, 0.0, 0, None), ("still", count, 0.0, 0, None), ("all in a frame", count, speed, 0, None),
             ("a slice a frame", count, speed, 1, None))
    kind, agl = 0, 0.0
    if sky:
        modes = ((f"none, limit {DEFAULT_FAR_LIMIT:.0f}", 0, 0.0, 0, DEFAULT_FAR_LIMIT),
                 (f"none, limit {limit:.0f}", 0, 0.0, 0, limit), ("still", count, 0.0, 0, limit),
                 ("a slice a frame", count, speed, 1, limit))
        kind, agl = SKY_KINDS["hidden"], height
    stream = XPlaneStream(api, (GPU_TIME, FRAME_PERIOD))
    stream.wait_for((GPU_TIME, FRAME_PERIOD))
    tid = main_thread(xplane_pid())
    results = []
    for block in range(blocks):
        for name, n, ms, spread, far in modes:
            if far is not None:
                set_far_limit(api, far)
            api.set(PREFIX + "speed_ms", 0.0)
            api.set(PREFIX + "clear", 1)
            if n:
                for key, value in (("kind", kind), ("count", n), ("grid", 1), ("spacing_m", spacing),
                                   ("dist_m", ahead), ("bearing_deg", 0), ("agl_m", agl), ("spread", spread),
                                   ("probe_moves", 0 if sky else 1), ("period_s", 1.0), ("move_bearing_deg", 90.0)):
                    api.set(PREFIX + key, float(value))
                api.set(PREFIX + "place", 1)
                time.sleep(0.5)
                api.set(PREFIX + "speed_ms", ms)
            marks = {}
            gpu = []

            def on_step(_v, p):
                if p.flown > 8.0:
                    if "cpu" not in marks:
                        api.set(PREFIX + "stats", 1)
                        marks["t"], marks["cpu"] = time.monotonic(), thread_times(tid)[1]
                    gpu.append(stream.snapshot()[0][GPU_TIME])

            Pilot(api).run(kmh, seconds, settle_s=8.0, quiet=True, on_step=on_step)
            cpu = (thread_times(tid)[1] - marks["cpu"]) / (time.monotonic() - marks["t"]) * 1e3
            row = {"mode": name, "n": n, "gpu_ms": round(1e3 * statistics.median(gpu), 2),
                   "main_thread_ms_s": round(cpu), **timings(api)}
            results.append(row)
            print(block, row, flush=True)
    api.set(PREFIX + "speed_ms", 0.0)
    api.set(PREFIX + "clear", 1)
    if sky:
        set_far_limit(api, DEFAULT_FAR_LIMIT)
    stream.close()
    print("\n| Mode | Shown | GPU (ms) | Main thread (ms/s) | Frame median (ms) | Frame p99 (ms) | Frame max (ms) "
          "| Update mean (us) | Update max (us) |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for r in results:
        print(f"| {r['mode']} | {r['n']} | {r['gpu_ms']} | {r['main_thread_ms_s']} | {r['frame_ms_median']} "
              f"| {r['frame_ms_p99']} | {r['frame_ms_max']} | {r['update_us_mean']} | {r['update_us_max']} |")


def run_sky(api, kind, height, distances, dist_m, limit=None, bearing=0.0):
    if limit is not None:
        set_far_limit(api, limit)
    pitch, heading = api.get(SUN_PITCH), api.get(SUN_HEADING)
    throw = height / math.tan(math.radians(pitch))
    east, north = throw * math.sin(math.radians(heading)), throw * math.cos(math.radians(heading))
    print(f"sun {pitch:.1f} deg up, from {heading:.0f}; a disc {height:.0f} m up throws its shadow {throw:.0f} m",
          flush=True)
    api.set(PREFIX + "cam", 0)
    api.set(PREFIX + "clear", 1)
    for name, value in (("count", 1), ("grid", 0), ("dist_m", dist_m), ("bearing_deg", bearing), ("agl_m", 0),
                        ("off_e_m", 0), ("off_n_m", 0), ("kind", 3)):
        api.set(PREFIX + name, float(value))
    api.set(PREFIX + "place", 1)
    time.sleep(1.0)
    for name, value in (("agl_m", height), ("off_e_m", east), ("off_n_m", north), ("kind", SKY_KINDS[kind])):
        api.set(PREFIX + name, float(value))
    api.set(PREFIX + "place", 1)
    time.sleep(1.0)
    print(status(api), flush=True)
    for km in distances:
        back, up = km * 1000.0 * math.cos(math.radians(30.0)), km * 1000.0 * math.sin(math.radians(30.0))
        for name, value in (("cam_up_m", up), ("cam_back_m", back), ("cam_bearing_deg", (heading + 90.0) % 360.0)):
            api.set(PREFIX + name, float(value))
        api.set(PREFIX + "cam", 1)
        time.sleep(4.0)
        print(km, "km", screenshot(api), flush=True)
    api.set(PREFIX + "cam", 0)


def plugin_clouds(api, on):
    try:
        api.set(PLUGIN_CLOUDS, on)
    except (KeyError, RuntimeError) as exc:
        print("plugin clouds not reached:", exc, flush=True)


def install(version, size, opacity, sky_lod, hidden_alpha, hidden_mode=None):
    shutil.copy(os.path.join(HERE, "PI_xpg_shadowlab.py"), PLUGINS)
    print("installed", make_shadow.write_all(LAB_DIR, version, size, opacity, sky_lod, hidden_alpha, hidden_mode), "in", LAB_DIR)


def uninstall():
    if os.path.exists(LAB_FILE):
        os.remove(LAB_FILE)
    for cached in glob.glob(os.path.join(PLUGINS, "__pycache__", "PI_xpg_shadowlab*")):
        os.remove(cached)
    shutil.rmtree(LAB_DIR, ignore_errors=True)
    print("removed the lab from", PLUGINS)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="what", required=True)
    for name in ("install", "gen"):
        p = sub.add_parser(name)
        p.add_argument("--version", type=int, default=1)
        p.add_argument("--size", type=float, default=1000.0)
        p.add_argument("--opacity", type=float, default=0.3)
        p.add_argument("--sky-lod", type=float, default=make_shadow.LOD_M)
        p.add_argument("--hidden-alpha", type=float, default=make_shadow.HIDDEN_ALPHA)
        p.add_argument("--hidden-mode", help="the disc's attributes, comma separated")
    sub.add_parser("uninstall")
    p = sub.add_parser("start")
    p.add_argument("--at", default="khob")
    p.add_argument("--msl", type=float, default=2500.0)
    p.add_argument("--heading", type=float, default=0.0)
    p.add_argument("--hour", type=float, default=12.0)
    p.add_argument("--kmh", type=float, default=90.0)
    p.add_argument("--fly", action="store_true")
    p = sub.add_parser("do")
    p.add_argument("writes", nargs="*")
    p.add_argument("--view", choices=sorted(VIEWS))
    p.add_argument("--shot", action="store_true")
    p.add_argument("--sample", type=float, default=0.0)
    p = sub.add_parser("sky")
    p.add_argument("--kind", choices=sorted(SKY_KINDS), required=True)
    p.add_argument("--height", type=float, default=1200.0)
    p.add_argument("--distances", default="1,2,4,8,16,32")
    p.add_argument("--dist", type=float, default=4000.0)
    p.add_argument("--limit", type=float)
    p.add_argument("--bearing", type=float, default=0.0, help="off the nose, degrees")
    p = sub.add_parser("cost")
    p.add_argument("--count", type=int, required=True)
    p.add_argument("--spacing", type=float, default=2000.0)
    p.add_argument("--ahead", type=float, default=4000.0)
    p.add_argument("--at", default="khob")
    p.add_argument("--msl", type=float, default=2800.0)
    p.add_argument("--blocks", type=int, default=3)
    p.add_argument("--seconds", type=float, default=60.0)
    p.add_argument("--kmh", type=float, default=90.0)
    p.add_argument("--speed", type=float, default=10.0, help="shadows' speed, m/s")
    p.add_argument("--sky", action="store_true", help="hidden discs in the sky instead of draped shapes")
    p.add_argument("--limit", type=float, default=20000.0, help="shadow far limit with --sky")
    p.add_argument("--height", type=float, default=1200.0, help="of the discs with --sky")
    args = parser.parse_args(argv)

    if args.what == "install":
        install(args.version, args.size, args.opacity, args.sky_lod, args.hidden_alpha, args.hidden_mode)
    elif args.what == "uninstall":
        uninstall()
    elif args.what == "gen":
        print("wrote", make_shadow.write_all(LAB_DIR, args.version, args.size, args.opacity, args.sky_lod,
                                             args.hidden_alpha, args.hidden_mode), "in", LAB_DIR)
    elif args.what == "start":
        api = XPlaneWebAPI(timeout=30.0)
        lat, lon, elev = site(args.at)
        air_start(api, args.msl, args.kmh, args.heading, lat=lat, lon=lon, hour=args.hour,
                  wx=weather(lat, lon, elev))
        plugin_clouds(api, 0)
        if not args.fly:
            api.command("sim/operation/pause_on")
        print("at", lat, lon, args.msl, flush=True)
    elif args.what == "sky":
        run_sky(XPlaneWebAPI(timeout=30.0), args.kind, args.height,
                [float(km) for km in args.distances.split(",")], args.dist, args.limit, args.bearing)
    elif args.what == "do":
        run_do(XPlaneWebAPI(timeout=30.0), args.writes, args.view, args.shot, args.sample)
    else:
        run_cost(XPlaneWebAPI(timeout=30.0), args.count, args.spacing, args.ahead, args.at, args.msl,
                 args.blocks, args.seconds, args.kmh, args.speed, args.sky, args.limit, args.height)


if __name__ == "__main__":
    main()
