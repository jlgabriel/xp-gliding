"""Choose a sky on the command line, for the tools in this folder.

    --sky wide_carriers                       a profile by name (engine.field.SKIES)
    --set carrier_stretch=1.75 --set blue_keep=0.3    change its numbers, to try candidates

Measurement tool, not part of the plugin. License: GPL-3.0-or-later.
"""

import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)

from xp_gliding.engine.field import SKIES, SkyProfile  # noqa: E402


def add_sky_args(parser):
    parser.add_argument("--sky", default="default", choices=sorted(SKIES), help="sky profile by name")
    parser.add_argument("--set", action="append", default=[], metavar="NAME=VALUE",
                        help="change one number of the profile (repeatable)")


def sky_from_args(args):
    base = SKIES[args.sky]
    values = {name: getattr(base, name) for name in SkyProfile.__slots__}
    for item in args.set:
        name, _, value = item.partition("=")
        if name not in values:
            raise SystemExit(f"unknown sky number {name}; there are {', '.join(values)}")
        values[name] = float(value)
    return SkyProfile(**values)


def describe(sky):
    return ", ".join(f"{name} {getattr(sky, name):g}" for name in SkyProfile.__slots__)
