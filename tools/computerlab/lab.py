"""Drive `PI_xpg_computerlab.py` in a running X-Plane and measure what its browser window costs.

Usage:
    python tools/computerlab/lab.py install --xplane "D:/.../X-Plane 12"
    python tools/computerlab/lab.py serve                      # probe server, leave running
    python tools/computerlab/lab.py cmd create_uri [--wait 4]  # names from the plugin's CMDS
    python tools/computerlab/lab.py state [--full]
    python tools/computerlab/lab.py measure --a destroy --b create_uri pan_on [--pairs 4]
    python tools/computerlab/lab.py poke                       # mouse and a Shift key on the window
    python tools/computerlab/lab.py keytest                    # click, then P: does the sim pause?
    python tools/computerlab/lab.py shot out.png

`serve` answers the page's two probe images on 127.0.0.1:8765 and logs each request's
headers (what CEF sends: User-Agent, Referer) to `probe.jsonl` beside the lab's state; one image
may be cached for a day, so a later X-Plane start that shows it without a request proves the
HTTP cache persisted. `measure` alternates two settings of the lab, each held `--seconds`,
and compares X-Plane's main-thread CPU, the CPU of its child processes (CEF runs there), and
X-Plane's GPU time estimate: the frame rate cap hides small costs in the frame time.
`poke` moves the real mouse over the lab window and presses Shift, and `keytest` clicks in it
and presses P (the sim's pause key) to see who gets the key; only run them while nobody is
using the computer.

Measurement tool, not part of the plugin. License: GPL-3.0-or-later.
"""

import argparse
import ctypes
import http.server
import json
import os
import shutil
import statistics
import struct
import subprocess
import sys
import time
import zlib
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "hudlab"))
sys.path.insert(0, os.path.join(HERE, "..", "testpilot"))

from thread_cpu import capture_window, main_thread, thread_times, xplane_pid  # noqa: E402
from xpweb import XPlaneWebAPI  # noqa: E402

XPLANE = os.environ.get("XPLANE_DIR", "D:/Laminar/XP12-Last-Release/X-Plane 12")
CMDS = {"create_raw": 1, "create_uri": 2, "destroy": 3, "show": 4, "hide": 5, "big": 6,
        "small": 7, "popout": 8, "float": 9, "refresh": 10, "rate2": 11, "rate5": 12,
        "rate10": 13, "pan_on": 14, "pan_off": 15, "push_on": 16, "push_off": 17,
        "late_function": 18, "rate0": 19, "focus_none": 20, "focus_release": 21, "focus_blur": 22, "kb_zero": 23, "kb_cycle": 24}
PORT = 8765
def one_pixel_png():
    def chunk(kind, data):
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))
    header = struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\x00")) + chunk(b"IEND", b""))


PNG = one_pixel_png()


def lab_dir(xplane=XPLANE):
    return os.path.join(xplane, "Output", "xp-gliding", "computerlab")


def read_state(xplane=XPLANE):
    with open(os.path.join(lab_dir(xplane), "state.json"), encoding="utf-8") as f:
        return json.load(f)


def send(api, names, wait):
    for name in names:
        api.set("xp_gliding/computerlab/cmd", CMDS[name])
        time.sleep(wait)


# --- install -------------------------------------------------------------------------

def install(xplane):
    dest = os.path.join(xplane, "Resources", "plugins", "PythonPlugins")
    shutil.copy2(os.path.join(HERE, "PI_xpg_computerlab.py"), dest)
    page = os.path.join(dest, "xpg_computerlab")
    shutil.rmtree(page, ignore_errors=True)
    shutil.copytree(os.path.join(HERE, "xpg_computerlab"), page)
    print("installed into", dest)


# --- probe server ------------------------------------------------------------------------

class Probe(http.server.BaseHTTPRequestHandler):
    log_path = None

    def do_GET(self):
        record = {"t": time.time(), "path": self.path, "headers": dict(self.headers)}
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record) + "\n")
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(PNG)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Timing-Allow-Origin", "*")
        cached = self.path.startswith("/probe-cached")
        self.send_header("Cache-Control", "public, max-age=86400" if cached else "no-store")
        self.end_headers()
        self.wfile.write(PNG)

    def log_message(self, *args):
        pass


def serve(xplane):
    os.makedirs(lab_dir(xplane), exist_ok=True)
    Probe.log_path = os.path.join(lab_dir(xplane), "probe.jsonl")
    print(f"probe server on 127.0.0.1:{PORT}, logging to {Probe.log_path}", flush=True)
    http.server.ThreadingHTTPServer(("127.0.0.1", PORT), Probe).serve_forever()


# --- cost --------------------------------------------------------------------------------

class PROCESSENTRY32(ctypes.Structure):
    _fields_ = [("dwSize", wintypes.DWORD), ("cntUsage", wintypes.DWORD),
                ("th32ProcessID", wintypes.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
                ("th32ModuleID", wintypes.DWORD), ("cntThreads", wintypes.DWORD),
                ("th32ParentProcessID", wintypes.DWORD), ("pcPriClassBase", wintypes.LONG),
                ("dwFlags", wintypes.DWORD), ("szExeFile", ctypes.c_char * 260)]


def descendants(pid):
    """{pid: exe name} of every process below `pid`."""
    k32 = ctypes.windll.kernel32
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)
    entry = PROCESSENTRY32()
    entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
    parents = {}
    more = k32.Process32First(snap, ctypes.byref(entry))
    while more:
        parents[entry.th32ProcessID] = (entry.th32ParentProcessID, entry.szExeFile.decode(errors="replace"))
        more = k32.Process32Next(snap, ctypes.byref(entry))
    k32.CloseHandle(snap)
    found, todo = {}, [pid]
    while todo:
        p = todo.pop()
        for child, (parent, exe) in parents.items():
            if parent == p and child not in found and child != pid:
                found[child] = exe
                todo.append(child)
    return found


def process_cpu(pid):
    k32 = ctypes.windll.kernel32
    handle = k32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        return 0.0
    times = [wintypes.FILETIME() for _ in range(4)]
    ok = k32.GetProcessTimes(handle, *[ctypes.byref(t) for t in times])
    k32.CloseHandle(handle)
    if not ok:
        return 0.0
    v = [(t.dwHighDateTime << 32 | t.dwLowDateTime) for t in times]
    return (v[2] + v[3]) * 1e-7


def gpu_util():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5).stdout
        return float(out.split()[0])
    except Exception:
        return float("nan")


def stretch(api, pid, tid, seconds):
    kids = descendants(pid)
    c0 = {p: process_cpu(p) for p in kids}
    p0, m0, t0 = process_cpu(pid), thread_times(tid)[1], time.monotonic()
    gpu_ms, util = [], []
    while time.monotonic() < t0 + seconds:
        gpu_ms.append(api.get("sim/time/gpu_time_per_frame_sec_approx") * 1e3)
        util.append(gpu_util())
        time.sleep(0.5)
    dt = time.monotonic() - t0
    kids_now = descendants(pid)
    child = sum(process_cpu(p) - c0.get(p, 0.0) for p in kids_now)
    return {"main_ms_s": (thread_times(tid)[1] - m0) / dt * 1e3,
            "xplane_ms_s": (process_cpu(pid) - p0) / dt * 1e3,
            "children_ms_s": child / dt * 1e3,
            "children": len(kids_now),
            "gpu_ms": statistics.median(gpu_ms),
            "gpu_util": statistics.median(util)}


def measure(api, a, b, pairs, seconds, settle):
    pid = xplane_pid()
    tid = main_thread(pid)
    rows = {"A": [], "B": []}
    for _ in range(pairs):
        for key, names in (("A", a), ("B", b)):
            send(api, names, 0.3)
            time.sleep(settle)
            rows[key].append(stretch(api, pid, tid, seconds))
    print(f"A = {' '.join(a)}   B = {' '.join(b)}   ({pairs} pairs of {seconds:.0f} s)")
    for field in ("main_ms_s", "xplane_ms_s", "children_ms_s", "gpu_ms", "gpu_util"):
        va = [r[field] for r in rows["A"]]
        vb = [r[field] for r in rows["B"]]
        diff = [y - x for x, y in zip(va, vb)]
        print(f"  {field:14s} A {statistics.median(va):8.2f}  B {statistics.median(vb):8.2f}"
              f"  B-A median {statistics.median(diff):7.2f}  pairs {', '.join(f'{d:.1f}' for d in diff)}")
    print("  child processes:", sorted(set(descendants(pid).values())))


# --- input -------------------------------------------------------------------------------

def client_rect(pid):
    """X-Plane's main window client area on screen: (left, top, width, height)."""
    user32 = ctypes.windll.user32
    best = []
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def visit(hwnd, _):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(hwnd):
            r = wintypes.RECT()
            user32.GetClientRect(hwnd, ctypes.byref(r))
            pt = wintypes.POINT(0, 0)
            user32.ClientToScreen(hwnd, ctypes.byref(pt))
            best.append((r.right * r.bottom, (pt.x, pt.y, r.right, r.bottom), hwnd))
        return True

    user32.EnumWindows(proc(visit), 0)
    best.sort(reverse=True)
    return best[0][1], best[0][2]


def to_screen(state, pid, gx, gy):
    (cx, cy, cw, ch), _ = client_rect(pid)
    left, top, right, bottom = state["screen_bounds"]
    scale = cw / float(right - left)
    return int(cx + (gx - left) * scale), int(cy + (top - gy) * scale)


def poke(api):
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    user32 = ctypes.windll.user32
    pid = xplane_pid()
    state = read_state()
    if not state.get("window") or state.get("popped_out"):
        raise SystemExit("needs the lab window open and not popped out")
    l, t, r, b = state["geometry"]
    before = state["last_report"]["ev"]
    _, hwnd = client_rect(pid)
    user32.SetForegroundWindow(hwnd)
    x, y = to_screen(state, pid, (l + r) // 2, (t + b) // 2)
    print("window centre on screen:", x, y)
    user32.SetCursorPos(x, y)
    time.sleep(0.3)
    for _ in range(3):
        user32.mouse_event(0x0800, 0, 0, 120, 0)  # wheel up
        time.sleep(0.2)
    user32.mouse_event(0x0002, 0, 0, 0, 0)  # left down
    for i in range(10):
        user32.SetCursorPos(x + 10 * i, y + 5 * i)
        time.sleep(0.03)
    user32.mouse_event(0x0004, 0, 0, 0, 0)  # left up
    time.sleep(0.3)
    user32.mouse_event(0x0002, 0, 0, 0, 0)
    user32.mouse_event(0x0004, 0, 0, 0, 0)
    time.sleep(0.3)
    user32.keybd_event(0x10, 0, 0, 0)  # Shift down, up
    user32.keybd_event(0x10, 0, 2, 0)
    time.sleep(2.5)
    after = read_state()["last_report"]["ev"]
    for k in ("wheel", "pointerdown", "pointermove", "pointerup", "click", "keydown", "focus", "blur"):
        print(f"  {k:12s} {after[k] - before[k]:+d}")
    print("  keys", after["keys"][len(before["keys"]):])


def keytest(api, click=True, between=()):
    """Click inside the lab window, then press P: does the sim still get the key?

    P is X-Plane's default pause key. Prints whether the pause toggled and whether the page
    saw the key; a toggled pause is toggled back.
    """
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
    user32 = ctypes.windll.user32
    pid = xplane_pid()
    state = read_state()
    if not state.get("window") or state.get("popped_out"):
        raise SystemExit("needs the lab window open and not popped out")
    l, t, r, b = state["geometry"]
    before = state["last_report"]["ev"]
    x, y = to_screen(state, pid, (l + r) // 2, t - 40)
    if click:
        user32.SetCursorPos(x, y)
        time.sleep(0.2)
        user32.mouse_event(0x0002, 0, 0, 0, 0)
        time.sleep(0.05)
        user32.mouse_event(0x0004, 0, 0, 0, 0)
        time.sleep(0.8)
    send(api, between, 0.5)
    focus_after_click = read_state()
    paused0 = api.get("sim/time/paused")
    user32.keybd_event(0x50, 0, 0, 0)
    time.sleep(0.05)
    user32.keybd_event(0x50, 0, 2, 0)
    time.sleep(1.0)
    paused1 = api.get("sim/time/paused")
    if paused1 != paused0:
        api.command("sim/operation/pause_toggle")
    time.sleep(2.2)
    after = read_state()
    page_keys = after["last_report"]["ev"]["keydown"] - before["keydown"]
    print(f"focus mode {after['settings'].get('focus')}: sim pause {paused0} -> {paused1} "
          f"({'SIM GOT THE KEY' if paused1 != paused0 else 'sim did not get the key'}); "
          f"page keydowns +{page_keys}; clicks +{after['last_report']['ev']['click'] - before['click']}; "
          f"window focus after click {focus_after_click.get('kb_window')}, "
          f"focus seen {after.get('focus_seen')}, released {after.get('focus_released')}, "
          f"page blurs {after['last_report'].get('blurs')}")


# --- main ------------------------------------------------------------------------------

def show_state(full):
    s = read_state()
    if not full and s.get("last_report"):
        rep = s["last_report"]
        s["last_report"] = {k: rep[k] for k in ("page_ms", "w", "h", "hidden", "vis", "has_focus",
                                                 "intervals", "rafs", "rate", "pings_ok", "pings_err",
                                                 "rtt", "push", "tiles", "probe", "storage") if k in rep}
    print(json.dumps(s, indent=1))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--xplane", default=XPLANE)
    sub = parser.add_subparsers(dest="what", required=True)
    sub.add_parser("install")
    sub.add_parser("serve")
    p = sub.add_parser("cmd")
    p.add_argument("names", nargs="+", choices=sorted(CMDS))
    p.add_argument("--wait", type=float, default=0.5)
    p = sub.add_parser("state")
    p.add_argument("--full", action="store_true")
    p = sub.add_parser("measure")
    p.add_argument("--a", nargs="+", required=True, choices=sorted(CMDS))
    p.add_argument("--b", nargs="+", required=True, choices=sorted(CMDS))
    p.add_argument("--pairs", type=int, default=4)
    p.add_argument("--seconds", type=float, default=8.0)
    p.add_argument("--settle", type=float, default=3.0)
    sub.add_parser("poke")
    p = sub.add_parser("keytest")
    p.add_argument("--no-click", action="store_true")
    p.add_argument("--between", nargs="*", default=[], choices=sorted(CMDS))
    p = sub.add_parser("shot")
    p.add_argument("path")
    args = parser.parse_args(argv)
    if args.what == "install":
        install(args.xplane)
    elif args.what == "serve":
        serve(args.xplane)
    elif args.what == "cmd":
        send(XPlaneWebAPI(), args.names, args.wait)
    elif args.what == "state":
        show_state(args.full)
    elif args.what == "measure":
        measure(XPlaneWebAPI(), args.a, args.b, args.pairs, args.seconds, args.settle)
    elif args.what == "keytest":
        keytest(XPlaneWebAPI(), not args.no_click, args.between)
    elif args.what == "poke":
        poke(XPlaneWebAPI())
    elif args.what == "shot":
        capture_window(xplane_pid(), args.path)


if __name__ == "__main__":
    main()
