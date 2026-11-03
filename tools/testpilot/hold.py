"""Test pilot: hold an indicated airspeed with wings level, a course, or a bank.

Usage (X-Plane running, glider in flight, nobody touching the stick):
    python tools/testpilot/hold.py --kmh 90 --seconds 60 [--record] [--dry-run]
    python tools/testpilot/hold.py --kmh 90 --course 270      # hold a course over the ground
    python tools/testpilot/hold.py --kmh 90 --circle -35      # circle left at 35 deg of bank
    python tools/testpilot/hold.py --release                  # give the controls back

While it runs, X-Plane ignores the pilot's stick and rudder. See pilot.py for
the safety checks; control laws are in control.py.

--record turns the flight logger on after --settle seconds and off at the end,
so the log holds only the steady part. --dry-run reads and computes but
never writes.

Measurement tool, not part of the plugin. License: GPL-3.0-or-later.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from control import Circle, Gains, HeadingHold  # noqa: E402
from pilot import Pilot, release  # noqa: E402
from xpweb import XPlaneWebAPI  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="Hold IAS and a bank via the X-Plane web API")
    parser.add_argument("--kmh", type=float, default=90.0, help="target IAS (km/h)")
    parser.add_argument("--seconds", type=float, default=30.0, help="sim seconds under control")
    parser.add_argument("--settle", type=float, default=20.0, help="seconds before --record starts")
    parser.add_argument("--course", type=float, help="hold this course over the ground (deg true)")
    parser.add_argument("--circle", type=float, help="circle at this bank (deg, + right)")
    parser.add_argument("--kbeta", type=float, default=Gains().kbeta, help="rudder per deg of sideslip")
    parser.add_argument("--min-agl", type=float, default=300.0, help="release below this (m)")
    parser.add_argument("--dry-run", action="store_true", help="read and compute, never write")
    parser.add_argument("--record", action="store_true", help="flight log on for the steady part")
    parser.add_argument("--release", action="store_true", help="only give the controls back")
    args = parser.parse_args(argv)
    api = XPlaneWebAPI()
    if args.release:
        release(api)
        return
    guidance = None
    if args.course is not None:
        guidance = HeadingHold(args.course)
    elif args.circle is not None:
        guidance = Circle(args.circle)
    reason, log = Pilot(api).run(args.kmh, args.seconds, guidance, args.settle, args.record,
                                 args.min_agl, bank_limit=max(35.0, abs(args.circle or 0) + 12),
                                 gains=Gains(kbeta=args.kbeta),
                                 dry_run=args.dry_run)
    if log:
        print(f"log: {log}")


if __name__ == "__main__":
    main()
