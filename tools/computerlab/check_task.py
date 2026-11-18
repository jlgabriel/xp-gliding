"""Check the Flight Computer's task in a running X-Plane: a short task flown by the test pilot.

Usage:
    python tools/computerlab/check_task.py write      # simcheck.cup in the tasks folder, chosen in config.json
    python tools/computerlab/check_task.py watch --seconds 150
    python tools/computerlab/check_task.py remove     # the file and the choice gone again

`write` puts a three-point task in front of `airstart.py`'s place (over KHOB, heading north):
the start 500 m north (our default start line, 2 km long, across the first leg), a turn point 2 km
north (a 500 m cylinder) and the finish 2 km east of it (a 500 m cylinder); and chooses it in
config.json (`computer_task`), so X-Plane must start after it. Fly it with
`hold.py --course 0` for about 75 s, then `--course 90`.

`watch` reads, once a second, the glider's place and the plugin's `computer/nav_index`,
`nav_dist_m` and `nav_bearing_deg`, and compares the last two with a computation that shares no
code with the plugin's (`nav/geodesy.py` uses the haversine and atan2 of the usual formula; this
uses unit vectors on the sphere), to the point the plugin says it flies to. It prints each change
of point and, at the end, the largest differences, and the plugin's log lines about the task.

Measurement tool, not part of the plugin. License: GPL-3.0-or-later.
"""

import argparse
import json
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "testpilot"))

from xpweb import XPlaneWebAPI  # noqa: E402

XPLANE = os.environ.get("XPLANE_DIR", r"D:\Laminar\XP12-Last-Release\X-Plane 12")
OUT = os.path.join(XPLANE, "Output", "xp-gliding")
FILE = "simcheck.cup"
KHOB = (32.6875, -103.2170)
R = 6371000.0
POINTS = (("Check Start", 500.0, 0.0), ("Check North", 2000.0, 0.0), ("Check East", 2000.0, 2000.0))


def offset(lat, lon, north_m, east_m):
    return lat + north_m / (R * math.pi / 180.0), lon + east_m / (R * math.pi / 180.0 * math.cos(math.radians(lat)))


def cup_angle(value, positive, negative, width):
    hemisphere = positive if value >= 0 else negative
    value = abs(value)
    degrees = int(value)
    return f"{degrees:0{width}d}{(value - degrees) * 60.0:06.3f}{hemisphere}"


def places():
    return [(name,) + offset(*KHOB, n, e) for name, n, e in POINTS]


def write():
    os.makedirs(os.path.join(OUT, "tasks"), exist_ok=True)
    lines = ["name,code,country,lat,lon,elev,style"]
    for name, lat, lon in places():
        lines.append(f'"{name}",,US,{cup_angle(lat, "N", "S", 2)},{cup_angle(lon, "E", "W", 3)},1116m,1')
    lines += ["-----Related Tasks-----", '"Sim check","Check Start","Check Start","Check North","Check East","Check East"']
    with open(os.path.join(OUT, "tasks", FILE), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    choose(f"{FILE}#0")
    print("written", os.path.join(OUT, "tasks", FILE), "and chosen in config.json")


def choose(value):
    path = os.path.join(OUT, "config.json")
    with open(path, encoding="utf-8") as f:
        config = json.load(f)
    config["computer_task"] = value
    with open(path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


def remove():
    try:
        os.remove(os.path.join(OUT, "tasks", FILE))
    except FileNotFoundError:
        pass
    choose("")
    print("removed")


def unit(lat, lon):
    p, l = math.radians(lat), math.radians(lon)
    return (math.cos(p) * math.cos(l), math.cos(p) * math.sin(l), math.sin(p))


def cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0])


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def independent(lat1, lon1, lat2, lon2):
    """(distance m, initial bearing deg) by unit vectors: the angle between them, and the direction
    of the great circle's plane against the local north and east."""
    a, b = unit(lat1, lon1), unit(lat2, lon2)
    c = cross(a, b)
    angle = math.atan2(math.sqrt(dot(c, c)), dot(a, b))
    north = (-math.sin(math.radians(lat1)) * math.cos(math.radians(lon1)),
             -math.sin(math.radians(lat1)) * math.sin(math.radians(lon1)), math.cos(math.radians(lat1)))
    east = (-math.sin(math.radians(lon1)), math.cos(math.radians(lon1)), 0.0)
    towards = cross(c, a)  # the direction of travel at a, tangent to the sphere
    return R * angle, math.degrees(math.atan2(dot(towards, east), dot(towards, north))) % 360.0


def watch(seconds):
    api = XPlaneWebAPI()
    pts = places()
    worst_deg, worst_share, last_index, rows = 0.0, 0.0, None, 0
    end = time.time() + seconds
    while time.time() < end:
        lat = api.get("sim/flightmodel/position/latitude")
        lon = api.get("sim/flightmodel/position/longitude")
        index = api.get("xp_gliding/computer/nav_index")
        dist = api.get("xp_gliding/computer/nav_dist_m")
        brg = api.get("xp_gliding/computer/nav_bearing_deg")
        if index != last_index:
            print(f"{time.strftime('%H:%M:%S')} flying to point {index}"
                  + (f" {pts[index][0]}" if 0 <= index < len(pts) else ""))
            last_index = index
        if 0 <= index < len(pts):
            d, b = independent(lat, lon, pts[index][1], pts[index][2])
            gap_deg = abs((brg - b + 180.0) % 360.0 - 180.0)
            share = abs(dist - d) / d if d > 50.0 else 0.0  # (from the plugin's 5 Hz snapshot: up to 0.2 s old)
            if d > 300.0:  # the bearing means little right at the point
                worst_deg = max(worst_deg, gap_deg)
            worst_share = max(worst_share, share)
            rows += 1
            if rows % 10 == 1:
                print(f"  plugin {dist:7.0f} m {brg:5.1f}°   independent {d:7.0f} m {b:5.1f}°")
        time.sleep(1.0)
    print(f"{rows} samples; largest gaps: bearing {worst_deg:.2f}° (past 300 m), distance {worst_share * 100:.2f} %")
    with open(os.path.join(XPLANE, "Log.txt"), encoding="utf-8", errors="replace") as f:
        for line in f:
            if "Flight Computer" in line and ("task" in line or "taken" in line or "by hand" in line):
                print("  log:", line.rstrip())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="what", required=True)
    sub.add_parser("write")
    sub.add_parser("remove")
    p = sub.add_parser("watch")
    p.add_argument("--seconds", type=float, default=150.0)
    args = parser.parse_args(argv)
    if args.what == "write":
        write()
    elif args.what == "remove":
        remove()
    else:
        watch(args.seconds)


if __name__ == "__main__":
    main()
