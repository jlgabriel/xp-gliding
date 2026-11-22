"""PLN soaring tasks: MSFS flight plans (.PLN) holding a soaring task in the "B21/NB21-compatible"
form that MSFS's soaring task tools write: the SSC Task Generator, WeSimGlide's Task Builder, B21
Task Planner. The Sim Soaring Club's tasks come this way.

A PLN is an XML flight plan: a title and a list of `ATCWaypoint`s, each with its name (the `id`
attribute), its place (`WorldPosition`: `N57° 6' 8.03",W3° 53' 28.18",+000889.11`, the last part
feet above sea level) and maybe an ICAO ident. The plan begins at the departure airport and ends at
the destination; the task lies between them. A flight plan has no fields for a task, so the
tools write what it needs into the waypoints' names. The convention comes from B21 Task Planner,
whose help documents it ("Tech appendix"); the rules here follow that planner's own code (read
2026-11-22), the reader the other tools write for:

    *Start+725|5000x5000      the start: elevation 725 ft, at most 5000 ft, 5000 m across
    WP 1+627x1000             a turn point: elevation 627 ft, 1000 m across
    WP 5+28743/28000x1000     at least 28000 ft
    *Finish+1014/1514x2000    the finish: at least 1514 ft, 2000 m across

  *       the start, on the first waypoint so marked; the finish, on the second. A name that
          begins with "start" or "finish" (any case) marks it too.
  +N      the waypoint's elevation, feet above sea level
  |N      the most height allowed in its zone, feet above sea level
  /N      the least height allowed, feet above sea level
  xN      the zone's DIAMETER in metres: the radius is half of it
  ;AAT    an assigned area (";AAThh:mm;" on the start: the task's minimum time)

The parts are read as B21 Task Planner reads them: the elevation is the number after the last "+"; the text after
the last "|" (or, without one, after the last "+") holds the rest, so "x" and "/" count only there,
and "WP 1+627x1000" has a 1000 m zone while "Box Hill" has none. The name shown is what comes
before the first "+" and "|". A start or finish not marked is the second waypoint or the one before
last, as the planner does.

The zones, from the planner's code: the start is a line through the start point, across the first leg, as
long as the zone's diameter, crossed going out along the leg; each turn point a cylinder; the finish
the half of its cylinder beyond the point (on the far side from the point before it), entered. With
no size given, the planner's defaults: 2500 m radius for the start, 500 m for a turn point, 2000 m for the
finish. A zone with height limits counts only within them (`task.py`).

The plan's waypoints before the start and after the finish are not task points: the first is the
takeoff, the last the landing, and any others between are left out, said in the notes. What the
plugin does not fly as written, assigned areas above all, goes in the task's `remarks`, shown with
the task when it is loaded.

The result is a `cup.CupFile` holding one task (or none, with the reason in its notes), so the
Flight Computer loads a PLN as it loads a CUP file. Nothing in a file raises.

Pure Python: no `xp`, nothing of the engine.
"""

import math
import re
import xml.etree.ElementTree as ET

from .cup import CupFile, TaskDef, Waypoint, ZoneSpec

FT_M = 0.3048
DEFAULT_START_RADIUS_M = 2500.0  # B21 Task Planner's DEFAULT_START_RADIUS_M
DEFAULT_POINT_RADIUS_M = 500.0  # the planner's default turn point radius (its setting's default)
DEFAULT_FINISH_RADIUS_M = 2000.0  # the planner's DEFAULT_FINISH_RADIUS_M
FINISH_HALF_DEG = 90.0  # the finish zone: the half cylinder beyond the point
MAX_BYTES = 2_000_000  # a flight plan is a few kilobytes; a bigger file is not one

_NUMBER = re.compile(r"\s*[-+]?(?:\d+\.?\d*|\.\d+)")
_EFB = re.compile(r"^[NS|]\d{0,2}\.")  # an EFB's waypoint named by its place: the planner leaves it as it is
_POSITION = re.compile(
    r"^\s*([NS])\s*(\d+(?:\.\d+)?)\s*°?\s*(?:(\d+(?:\.\d+)?)\s*')?\s*(?:(\d+(?:\.\d+)?)\s*\")?\s*,"
    r"\s*([EW])\s*(\d+(?:\.\d+)?)\s*°?\s*(?:(\d+(?:\.\d+)?)\s*')?\s*(?:(\d+(?:\.\d+)?)\s*\")?"
    r"\s*(?:,\s*([-+]?\d+(?:\.\d*)?))?\s*$", re.IGNORECASE)


class NameCode:
    """What a waypoint's name says, as B21 Task Planner reads it. Heights in feet, the diameter in metres; None
    for what the name does not say."""

    __slots__ = ("name", "mark", "elev_ft", "max_ft", "min_ft", "diameter_m", "aat", "aat_min_s")

    def __init__(self, name):
        self.name = name
        self.mark = None  # "*", "start" or "finish"
        self.elev_ft = self.max_ft = self.min_ft = self.diameter_m = None
        self.aat = False
        self.aat_min_s = None

    @property
    def radius_m(self):
        return None if self.diameter_m is None else self.diameter_m / 2.0


def leading_number(text):
    """The number a text begins with, as JavaScript's parseFloat reads it ("725|5000" is 725); None
    if it begins with none, or it is not finite."""
    m = _NUMBER.match(text)
    if not m:
        return None
    value = float(m.group(0))
    return value if math.isfinite(value) else None


def decode_name(raw):
    """A waypoint's name to its NameCode, as B21 Task Planner decodes it (`decode_wp_name`)."""
    code = NameCode(raw.strip())
    name = code.name
    if _EFB.match(name):
        return code
    lower = name.lower()
    if lower.startswith("start"):
        code.mark = "start"
    elif lower.startswith("finish"):
        code.mark = "finish"
    elif name.startswith("*"):
        code.mark = "*"
        name = name[1:]
    tail = ""
    plus = name.split("+")
    if len(plus) > 1:
        tail = plus[-1]
        code.elev_ft = leading_number(tail)
    bar = name.split("|")
    if len(bar) > 1:
        tail = bar[-1]
        code.max_ft = leading_number(tail)
    slash = tail.split("/")
    if len(slash) > 1:
        code.min_ft = leading_number(slash[-1])
    cross = tail.split("x")
    if len(cross) > 1:
        d = leading_number(cross[-1])
        code.diameter_m = d if d is not None and d > 0.0 else None
    if ";AAT" in tail:
        code.aat = True
        at = tail.index(";AAT")
        clock = tail[at:at + 10]  # ";AAThh:mm;", as the planner reads it
        if clock[6:7] == ":" and clock[9:10] == ";" and clock[4:6].isdigit() and clock[7:9].isdigit():
            code.aat_min_s = int(clock[4:6]) * 3600 + int(clock[7:9]) * 60
    code.name = name.split("+")[0].split("|")[0].strip() or name.strip()
    return code


def parse_position(text):
    """`WorldPosition` to (lat, lon, feet above sea level or None); None if it is not one."""
    m = _POSITION.match(text or "")
    if not m:
        return None
    g = m.groups()

    def angle(hemi, d, mins, secs, limit, negative):
        value = float(d) + float(mins or 0.0) / 60.0 + float(secs or 0.0) / 3600.0
        if (mins and float(mins) >= 60.0) or (secs and float(secs) >= 60.0) or value > limit:
            return None
        return -value if hemi.upper() == negative else value

    lat = angle(g[0], g[1], g[2], g[3], 90.0, "S")
    lon = angle(g[4], g[5], g[6], g[7], 180.0, "W")
    if lat is None or lon is None:
        return None
    alt = float(g[8]) if g[8] is not None else None
    return lat, lon, alt if alt is None or math.isfinite(alt) else None


def load(path):
    with open(path, "rb") as f:
        return parse(f.read(MAX_BYTES + 1))


def _text(element, tag):
    found = element.find(tag)
    return (found.text or "").strip() if found is not None else ""


def parse(data):
    """A PLN file's bytes to a CupFile with its task. Never raises on what the file holds."""
    plan = CupFile()
    if len(data) > MAX_BYTES:
        plan.notes.append("not read: too big for a flight plan")
        return plan
    head = data[:4096].lower()
    if b"<!doctype" in head or b"<!entity" in head:  # a flight plan has neither; entities can bloat
        plan.notes.append("not read: it declares a DOCTYPE or entities, which a flight plan has not")
        return plan
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        plan.notes.append(f"not read: not XML ({exc})")
        return plan
    fp = root if root.tag == "FlightPlan.FlightPlan" else root.find("FlightPlan.FlightPlan")
    if fp is None:
        plan.notes.append("not read: no FlightPlan.FlightPlan in it")
        return plan
    title = _text(fp, "Title")
    airports = {_text(fp, "DepartureID").upper(), _text(fp, "DestinationID").upper()} - {""}
    entries = []  # (Waypoint, NameCode)
    for n, element in enumerate(fp.findall("ATCWaypoint"), start=1):
        raw = element.get("id", "")
        place = parse_position(_text(element, "WorldPosition"))
        if place is None:
            plan.notes.append(f"waypoint {n} ({raw!r}) skipped: its WorldPosition is not understood")
            continue
        code = decode_name(raw)
        ident = _text(element, "ICAO/ICAOIdent")
        is_airport = _text(element, "ATCWaypointType").lower() == "airport" or ident.upper() in airports
        if code.elev_ft is not None:
            # As the planner: the name's, unless the place's says the same more finely (within half a foot)
            near = place[2] is not None and abs(code.elev_ft - place[2]) <= 0.5
            elev_m = (place[2] if near else code.elev_ft) * FT_M
        elif place[2] is not None and place[2] != 0.0:
            elev_m = place[2] * FT_M  # the planner's help: a user waypoint's is not to be trusted; 0 is no height
        else:
            elev_m = None
        wp = Waypoint(code.name or raw.strip() or f"WP {n}", place[0], place[1], elev_m,
                      ident if is_airport else "", 5 if is_airport else 1)
        entries.append((wp, code))
    task = _task(plan, title, entries)
    if task is not None:
        plan.tasks.append(task)
        for wp in [task.takeoff] + task.points + [task.landing]:
            if wp is not None:
                plan.waypoints.setdefault(wp.name, wp)
    return plan


def _task(plan, title, entries):
    count = len(entries)
    if count < 2:
        plan.notes.append("no task: a task needs a start and a finish")
        return None
    start = finish = None
    for i, (_, code) in enumerate(entries):  # in the planner's order: a later mark overrides
        if code.mark == "start":
            start = i
        elif code.mark == "finish":
            finish = i
        elif code.mark == "*":
            if start is None:
                start = i
            else:
                finish = i
    if start is None:
        start = 1 if count > 2 else 0
    if finish is None:
        finish = count - 2 if count > 2 else count - 1
    if finish <= start:
        plan.notes.append(f"no task: its finish (waypoint {finish + 1}) is not after its start "
                          f"(waypoint {start + 1})")
        return None
    remarks = []
    takeoff = entries[0][0] if start > 0 else None
    landing = entries[-1][0] if finish < count - 1 else None
    skipped = [wp.name for wp, _ in entries[1:start]] + [wp.name for wp, _ in entries[finish + 1:-1]]
    if skipped:
        plan.notes.append("not task points, left out: " + ", ".join(repr(s) for s in skipped))
    points, zones, aat = [], {}, []
    last = finish - start
    for k, (wp, code) in enumerate(entries[start:finish + 1]):
        points.append(wp)
        max_m = None if code.max_ft is None else code.max_ft * FT_M
        min_m = None if code.min_ft is None else code.min_ft * FT_M
        radius = code.radius_m
        if k == 0:
            zones[k] = ZoneSpec(style=2, r1_m=radius or DEFAULT_START_RADIUS_M, a1_deg=180.0, line=True,
                                max_alt_m=max_m, min_alt_m=min_m)
        elif k == last:
            zones[k] = ZoneSpec(style=3, r1_m=radius or DEFAULT_FINISH_RADIUS_M, a1_deg=FINISH_HALF_DEG,
                                max_alt_m=max_m, min_alt_m=min_m)
        else:
            zones[k] = ZoneSpec(style=1, r1_m=radius or DEFAULT_POINT_RADIUS_M, a1_deg=180.0,
                                max_alt_m=max_m, min_alt_m=min_m)
            if code.aat:
                aat.append(wp.name)
    if aat:
        remarks.append("Assigned areas (AAT) flown as cylinders, to be entered: "
                       + ", ".join(aat) + ". The task is not scored as an AAT.")
    start_code = entries[start][1]
    if start_code.aat_min_s:
        h, m = divmod(start_code.aat_min_s // 60, 60)
        remarks.append(f"Minimum task time {h}:{m:02d} not used.")
    return TaskDef(title, takeoff, points, landing, zones, {}, 0, remarks)
