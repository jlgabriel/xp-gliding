"""Restart X-Plane from outside, so a plugin change can be loaded without a human.

Usage:
    python tools/testpilot/restart_xplane.py [--xplane "D:/.../X-Plane 12"] [--no-quit]
        [-- X-Plane arguments, e.g. --lock_fr=30]

Sends `sim/operation/quit` through the web API (X-Plane closes in ~16 s and
plugins run their disable/stop code on the way out), waits for the process to
end, launches `X-Plane.exe` again, waits for the web API (~50 s) and then a
grace period (60 s by default): the API answers before X-Plane has finished
loading airports and plugins, and a flight requested in that window can hang
it (seen 2026-11-03). The API can take minutes: on 2026-11-03 the MOZA
plugin alone took ~3.5 min to load, so the wait is up to 10 min. A slow start
can also be X-Plane's Safe Mode dialog waiting for someone to answer it: it
comes up by itself on the start after some crashes (Juan Luis, 2026-11-03), and
must be answered "No Thanks", because "Plugins" would leave xp-gliding unloaded.
Start a flight afterwards with `airstart.py` or any mission
(`POST /api/v3/flight` works from the main menu). Windows only.

Arguments after `--` go to X-Plane. `--lock_fr` and `--fm_per_frame` are
command-line options of X-Plane 12.4.3 (found as strings in X-Plane.exe next
to each other, with no help text; checked 2026-11-03).

Measurement tool, not part of the plugin. License: GPL-3.0-or-later.
"""

import argparse
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from xpweb import XPlaneWebAPI  # noqa: E402

DEFAULT_DIR = os.environ.get("XPLANE_DIR", r"D:\Laminar\XP12-Last-Release\X-Plane 12")


def xplane_running():
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq X-Plane.exe", "/NH"],
                         capture_output=True, text=True).stdout
    return "X-Plane.exe" in out


def api_up(api):
    """Any HTTP answer counts: at the main menu X-Plane serves the API but has no
    datarefs or commands until a flight is loaded."""
    try:
        api.command_id("sim/operation/quit")
    except (RuntimeError, KeyError):
        return True
    except OSError:
        return False
    return True


def restart(xplane_dir, quit_first=True, timeout_s=600.0, xplane_args=(), grace_s=60.0):
    if quit_first and xplane_running():
        # The quit command exists only while a flight is loaded, not at the main menu.
        try:
            XPlaneWebAPI(timeout=5.0).command("sim/operation/quit")
        except (OSError, RuntimeError, KeyError) as exc:
            raise SystemExit(f"could not ask X-Plane to quit: {exc}")
        end = time.monotonic() + 90.0
        while xplane_running():
            if time.monotonic() > end:
                raise SystemExit("X-Plane did not close within 90 s")
            time.sleep(1.0)
        print("X-Plane closed", flush=True)
    if xplane_running():
        raise SystemExit("X-Plane is already running (use without --no-quit)")
    print(f"launching X-Plane {' '.join(xplane_args)}".rstrip(), flush=True)
    subprocess.Popen([os.path.join(xplane_dir, "X-Plane.exe"), *xplane_args], cwd=xplane_dir,
                     creationflags=getattr(subprocess, "DETACHED_PROCESS", 0))
    t0 = time.monotonic()
    while True:
        time.sleep(2.0)
        if api_up(XPlaneWebAPI(timeout=2.0)):
            break
        if time.monotonic() - t0 > timeout_s:
            raise SystemExit(f"web API not up within {timeout_s:.0f} s")
    print(f"X-Plane web API up after {time.monotonic() - t0:.0f} s; waiting {grace_s:.0f} s more",
          flush=True)
    time.sleep(grace_s)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Quit and relaunch X-Plane")
    parser.add_argument("--xplane", default=DEFAULT_DIR, help="X-Plane 12 folder")
    parser.add_argument("--no-quit", action="store_true", help="only launch and wait")
    parser.add_argument("--grace", type=float, default=60.0,
                        help="seconds to wait after the web API is up")
    parser.add_argument("xplane_args", nargs="*", help="arguments for X-Plane, after --")
    args = parser.parse_args(argv)
    restart(args.xplane, quit_first=not args.no_quit, xplane_args=args.xplane_args,
            grace_s=args.grace)


if __name__ == "__main__":
    main()
