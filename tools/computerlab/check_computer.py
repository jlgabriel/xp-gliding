"""Check the plugin's Flight Computer in a running X-Plane: its state, the keyboard after a click,
moving its window, and what an open window costs.

Usage:
    python tools/computerlab/check_computer.py status
    python tools/computerlab/check_computer.py keytest        # click in the window, then P
    python tools/computerlab/check_computer.py drag 200 -100  # move it by its title bar (px)
    python tools/computerlab/check_computer.py popout         # click its pop-out button
    python tools/computerlab/check_computer.py measure --poll 5 [--pairs 5 --seconds 12]
    python tools/computerlab/check_computer.py shot out.png
    python tools/computerlab/check_computer.py track [LOG.csv]   # the map's track against the flight log
    python tools/computerlab/check_computer.py tab map        # click the MAP (or FLIGHT) tab

`measure` alternates the Flight Computer closed (its window destroyed) and open with the page
polling at `--poll` Hz, and compares X-Plane's main thread, its child processes (CEF) and its GPU
time estimate, as `lab.py measure` does. The HUD stays off in both, so the open side also carries
the instruments' sampling, which only the Flight Computer then wants: the instrument's whole cost.
`track` has the plugin write the Flight Computer's track (`computer/track_dump`) and compares each
point with the flight log's place at the same simulator time (the newest log unless one is
given), and says whether the page holds every point (`computer/track_shown`).
`keytest` and `drag` move the real mouse; only run them while nobody is using the computer.
Where the window is comes from config.json once it was moved, else from its default place.

Measurement tool, not part of the plugin. License: GPL-3.0-or-later.
"""

import argparse
import bisect
import csv
import ctypes
import glob
import json
import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))  # the repository, for xp_gliding.nav

import lab  # noqa: E402
from lab import XPLANE, capture_window, main_thread, stretch, to_screen, xplane_pid  # noqa: E402
from xpweb import XPlaneWebAPI  # noqa: E402
from xp_gliding.nav.geodesy import distance_m  # noqa: E402

BOUNDS = [0, 1440, 2560, 0]  # X-Plane's global desktop here (the lab's state.json, 2026-11-17)
DEFAULT = (120, 160, 480, 420)  # computer.py: DEFAULT_OFFSET and DEFAULT_SIZE


def window_rect():
    with open(os.path.join(XPLANE, "Output", "xp-gliding", "config.json"), encoding="utf-8") as f:
        rect = json.load(f).get("computer_window") or []
    if rect:
        return rect
    left, top = BOUNDS[0] + DEFAULT[0], BOUNDS[1] - DEFAULT[1]
    return [left, top, left + DEFAULT[2], top - DEFAULT[3]]


def screen(gx, gy):
    return to_screen({"screen_bounds": BOUNDS}, xplane_pid(), gx, gy)


def status(api):
    names = ("computer_enabled", "hud_enabled", "computer/available", "computer/window", "computer/loaded",
             "computer/requests", "computer/tick_us", "computer/poll_hz", "hud/te_ms", "hud/average_ms",
             "hud/thermal_ms", "hud/draw_us")
    return {name: api.get("xp_gliding/" + name) for name in names}


def bring_to_front():
    """X-Plane's window in front, or stop: a click meant for it must never land in another program.
    Windows lets a background program take the foreground only after a key event of its own (Alt)."""
    user32 = ctypes.windll.user32
    _, hwnd = lab.client_rect(xplane_pid())
    user32.ShowWindow(hwnd, 9)  # SW_RESTORE
    user32.keybd_event(0x12, 0, 0, 0)  # Alt down and up
    user32.keybd_event(0x12, 0, 2, 0)
    user32.SetForegroundWindow(hwnd)
    time.sleep(0.5)
    if user32.GetForegroundWindow() != hwnd:
        raise SystemExit("X-Plane is not in front; nothing clicked")


def click(x, y):
    bring_to_front()
    user32 = ctypes.windll.user32
    user32.SetCursorPos(x, y)
    time.sleep(0.2)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    time.sleep(0.05)
    user32.mouse_event(0x0004, 0, 0, 0, 0)


def keytest(api):
    left, top, right, bottom = window_rect()
    click(*screen((left + right) // 2, (top + bottom) // 2))
    time.sleep(0.8)
    p0 = api.get("sim/time/paused")
    user32 = ctypes.windll.user32
    user32.keybd_event(0x50, 0, 0, 0)  # P, X-Plane's pause key
    time.sleep(0.05)
    user32.keybd_event(0x50, 0, 2, 0)
    time.sleep(1.0)
    p1 = api.get("sim/time/paused")
    if p1 != p0:
        api.command("sim/operation/pause_toggle")
    print(f"after a click in the window, P: pause {p0} -> {p1}: "
          + ("THE SIM GOT THE KEY" if p1 != p0 else "the sim did NOT get the key"))


def popout():
    """Click the pop-out button at the right end of the window's title bar."""
    left, top, right, bottom = window_rect()
    click(*screen(right - 9, top + 22))
    print("clicked the pop-out button")


def tab(name):
    """Click a tab. Where they are follows app.css: the strip one row of the view's 3 (4 when tall,
    2 when wide), then the tabs, about 22 px high, the two side by side."""
    left, top, right, bottom = window_rect()
    width, height = right - left, top - bottom
    rows = 4 if width / height < 0.75 else 2 if width / height >= 1.6 else 3
    strip = (height - 5 - 7.5 - 22) / (rows + 1)
    x = left + width * (0.25 if name == "map" else 0.75)
    y = top - (2.5 + strip + 2.5 + 11)
    click(*screen(int(x), int(y)))
    print("clicked the", name, "tab at", (int(x), int(y)))


def drag(dx, dy):
    """Drag the window by its title bar, just above its top edge, by dx, dy screen pixels."""
    left, top, right, bottom = window_rect()
    x, y = screen((left + right) // 2, top + 12)
    bring_to_front()
    user32 = ctypes.windll.user32
    user32.SetCursorPos(x, y)
    time.sleep(0.2)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    for k in range(1, 21):
        user32.SetCursorPos(x + dx * k // 20, y + dy * k // 20)
        time.sleep(0.03)
    user32.mouse_event(0x0004, 0, 0, 0, 0)
    print("dragged from", (x, y), "by", (dx, dy))


def read_log(path):
    """(times, lats, lons) of a flight log's rows, in order; paused and replay rows left out."""
    times, lats, lons = [], [], []
    with open(path, encoding="utf-8", newline="") as f:
        rows = csv.DictReader(line for line in f if not line.startswith("#"))
        for row in rows:
            if row["paused"] == "1" or row["replay"] == "1":
                continue
            times.append(float(row["t_run_s"]))
            lats.append(float(row["lat_deg"]))
            lons.append(float(row["lon_deg"]))
    return times, lats, lons


def track(api, log_path):
    api.set("xp_gliding/computer/track_dump", 1)
    time.sleep(1.0)
    with open(os.path.join(XPLANE, "Output", "xp-gliding", "computer-track.json"), encoding="utf-8") as f:
        dump = json.load(f)
    if log_path is None:
        logs = glob.glob(os.path.join(XPLANE, "Output", "xp-gliding", "flightlogs", "flightlog_*.csv"))
        log_path = max(logs, key=os.path.getmtime)
    times, lats, lons = read_log(log_path)
    gaps = []
    outside = 0
    for t, lat, lon in dump["points"]:
        k = bisect.bisect_left(times, t)
        if k == 0 or k >= len(times):
            outside += 1
            continue
        t0, t1 = times[k - 1], times[k]
        share = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
        log_lat = lats[k - 1] + share * (lats[k] - lats[k - 1])
        log_lon = lons[k - 1] + share * (lons[k] - lons[k - 1])
        gaps.append(distance_m(lat, lon, log_lat, log_lon))
    pts = dump["points"]
    span = distance_m(pts[0][1], pts[0][2], pts[-1][1], pts[-1][2]) if pts else 0.0
    print(f"track: epoch {dump['epoch']}, {dump['n']} points kept ({len(pts)} held), "
          f"{pts[-1][0] - pts[0][0]:.0f} s, first to last {span:.0f} m" if pts else "track: empty")
    print(f"log {os.path.basename(log_path)}: {len(times)} rows; {len(gaps)} points inside it, {outside} outside")
    if gaps:
        print(f"  track point to the log's place at its time: median {statistics.median(gaps):.2f} m, "
              f"max {max(gaps):.2f} m")
    print("  computer/track_n", api.get("xp_gliding/computer/track_n"), " computer/track_shown (held by the page)",
          api.get("xp_gliding/computer/track_shown"))


def measure(api, poll, pairs, seconds, settle):
    pid = xplane_pid()
    tid = main_thread(pid)
    api.set("xp_gliding/computer/poll_hz", poll)
    api.set("xp_gliding/hud_enabled", 0)
    rows = {"closed": [], "open": []}
    for _ in range(pairs):
        for key, on in (("closed", 0), ("open", 1)):
            api.set("xp_gliding/computer_enabled", on)
            time.sleep(settle)
            rows[key].append(stretch(api, pid, tid, seconds))
    print(f"Flight Computer closed against open, page polling at {poll} Hz ({pairs} pairs of {seconds:.0f} s)")
    for field in ("main_ms_s", "xplane_ms_s", "children_ms_s", "gpu_ms", "gpu_util"):
        va = [r[field] for r in rows["closed"]]
        vb = [r[field] for r in rows["open"]]
        diff = [b - a for a, b in zip(va, vb)]
        print(f"  {field:14s} closed {statistics.median(va):8.2f}  open {statistics.median(vb):8.2f}"
              f"  open-closed median {statistics.median(diff):7.2f}  pairs {', '.join(f'{d:.1f}' for d in diff)}")
    print("  computer/tick_us", round(api.get("xp_gliding/computer/tick_us"), 1),
          " requests", api.get("xp_gliding/computer/requests"))


def main(argv=None):
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="what", required=True)
    sub.add_parser("status")
    sub.add_parser("keytest")
    sub.add_parser("popout")
    p = sub.add_parser("drag")
    p.add_argument("dx", type=int)
    p.add_argument("dy", type=int)
    p = sub.add_parser("measure")
    p.add_argument("--poll", type=int, required=True)
    p.add_argument("--pairs", type=int, default=5)
    p.add_argument("--seconds", type=float, default=12.0)
    p.add_argument("--settle", type=float, default=3.0)
    p = sub.add_parser("shot")
    p.add_argument("path")
    p = sub.add_parser("tab")
    p.add_argument("name", choices=("map", "flight"))
    p = sub.add_parser("track")
    p.add_argument("log", nargs="?")
    args = parser.parse_args(argv)
    api = XPlaneWebAPI()
    if args.what == "status":
        print(json.dumps(status(api), indent=1))
    elif args.what == "keytest":
        keytest(api)
    elif args.what == "popout":
        popout()
    elif args.what == "drag":
        drag(args.dx, args.dy)
    elif args.what == "measure":
        measure(api, args.poll, args.pairs, args.seconds, args.settle)
    elif args.what == "tab":
        tab(args.name)
    elif args.what == "track":
        track(api, args.log)
    elif args.what == "shot":
        bring_to_front()
        capture_window(xplane_pid(), args.path)


if __name__ == "__main__":
    main()
