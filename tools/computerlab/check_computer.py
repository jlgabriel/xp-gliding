"""Check the plugin's Flight Computer in a running X-Plane: its state, the keyboard after a click,
moving its window, and what an open window costs.

Usage:
    python tools/computerlab/check_computer.py status
    python tools/computerlab/check_computer.py keytest        # click in the window, then P
    python tools/computerlab/check_computer.py drag 200 -100  # move it by its title bar (px)
    python tools/computerlab/check_computer.py popout         # click its pop-out button
    python tools/computerlab/check_computer.py measure --poll 5 [--pairs 5 --seconds 12]
    python tools/computerlab/check_computer.py shot out.png

`measure` alternates the Flight Computer closed (its window destroyed) and open with the page
polling at `--poll` Hz, and compares X-Plane's main thread, its child processes (CEF) and its GPU
time estimate, as `lab.py measure` does. The HUD stays off in both, so the open side also carries
the instruments' sampling, which only the Flight Computer then wants: the instrument's whole cost.
`keytest` and `drag` move the real mouse; only run them while nobody is using the computer.
Where the window is comes from config.json once it was moved, else from its default place.

Measurement tool, not part of the plugin. License: GPL-3.0-or-later.
"""

import argparse
import ctypes
import json
import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import lab  # noqa: E402
from lab import XPLANE, capture_window, main_thread, stretch, to_screen, xplane_pid  # noqa: E402
from xpweb import XPlaneWebAPI  # noqa: E402

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
    elif args.what == "shot":
        bring_to_front()
        capture_window(xplane_pid(), args.path)


if __name__ == "__main__":
    main()
