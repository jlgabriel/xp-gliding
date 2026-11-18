"""The task flown: its points with their observation zones, the zone tests, and the progress along it.

A `Task` is made from a CUP file's task (`cup.TaskDef`): its task points, start first and finish
last, each with a zone. A zone the file gives is used as given, its missing values filled in; a
point the file gives no zone gets ours (DEFAULT_*: SeeYou uses each pilot's own defaults, so there
is nothing to match): a start line 2 km long across the first leg, a 500 m cylinder at each turn
point and at the finish, as XCSoar's racing defaults.

A zone is built around a centre line through its point (Naviter's description of `ObsZone`): the
outer sector lies between R2 and R1 of the point, within A1 of the centre line on each side; the
inner sector inside R2, within A2. `Style` sets where the centre line points, kept here as `axis`,
the bearing from the point into the zone:

  0  fixed: A12 is the bearing from the zone towards the point, so the zone lies at A12 + 180
  1  symmetrical: on the bisector of the two legs, on the outside of the turn; at the start as 2,
     at the finish as 3
  2  to the next point: the zone lies on the far side from the next point (a start sector behind
     the start)
  3  to the previous point: the zone lies on the far side from the previous point (a finish sector
     beyond the finish)
  4  to the start point: on the far side from the start

A line (`Line=1`) goes through the point at right angles to the centre line, R1 on each side, and
the zone is the half-plane on the axis side: behind a start line, beyond a finish line. So every
point is taken the same way: the start on leaving its zone (a line by crossing it within R1 of
the point), each turn point and the finish on entering theirs. Only the point being flown to is
looked at, and the start as long as the first turn point is not reached: crossing the start again
restarts the task. Once a point is taken, being in the next one's zone already takes it (zones may
overlap); after a jump or a step by hand, only an entry seen afterwards does, so a placement on the
map takes nothing, and a point stepped back to stays so until its zone is left and entered again.

Zone tests use the distance and bearing from the point on the sphere (`geodesy`); a line uses the
along- and across-track parts of them, fine within the few kilometres of a line.

This shows a task and guides along it: no scoring, no start time rules, no AAT optimisation. The
pilot can step back and forward by hand, which always wins.

Pure Python: no `xp`, nothing of the engine.
"""

import hashlib
import json
import math

from .geodesy import bearing_deg, destination, distance_m

DEFAULT_START = {"style": 2, "r1_m": 1000.0, "a1_deg": 180.0, "line": True}
DEFAULT_POINT = {"style": 1, "r1_m": 500.0, "a1_deg": 180.0, "line": False}
DEFAULT_FINISH = {"style": 3, "r1_m": 500.0, "a1_deg": 180.0, "line": False}
ARC_STEP_DEG = 5.0  # a sector's arc is drawn with a point at least this often


def _wrap180(deg):
    return (deg + 180.0) % 360.0 - 180.0


class Zone:
    """An observation zone around a task point, with its centre line worked out."""

    __slots__ = ("lat", "lon", "axis", "r1", "a1", "r2", "a2", "line", "given")

    def __init__(self, lat, lon, axis, r1, a1=180.0, r2=0.0, a2=0.0, line=False, given=False):
        self.lat, self.lon = lat, lon
        self.axis = axis % 360.0  # bearing from the point into the zone
        self.r1 = max(r1, 1.0)
        self.a1 = min(max(a1, 0.0), 180.0)
        self.r2 = min(max(r2, 0.0), self.r1)
        self.a2 = min(max(a2, 0.0), 180.0)
        self.line = line
        self.given = given  # from the file, not our default

    @property
    def is_cylinder(self):
        return not self.line and self.a1 >= 180.0 and (self.r2 <= 0.0 or self.a2 >= 180.0)

    def polar(self, lat, lon):
        """(distance from the point, angle off the centre line, 0 to 180)."""
        d = distance_m(self.lat, self.lon, lat, lon)
        off = abs(_wrap180(bearing_deg(self.lat, self.lon, lat, lon) - self.axis)) if d > 0.0 else 0.0
        return d, off

    def along_across(self, lat, lon):
        """For a line: (metres along the axis, into the zone positive; metres across it)."""
        d = distance_m(self.lat, self.lon, lat, lon)
        if d == 0.0:
            return 0.0, 0.0
        rel = math.radians(bearing_deg(self.lat, self.lon, lat, lon) - self.axis)
        return d * math.cos(rel), d * math.sin(rel)

    def contains(self, lat, lon):
        if self.line:
            along, across = self.along_across(lat, lon)
            return along > 0.0 and abs(across) <= self.r1
        d, off = self.polar(lat, lon)
        if d <= self.r2 and self.r2 > 0.0:
            return self.a2 > 0.0 and off <= self.a2
        return d <= self.r1 and off <= self.a1

    def crossed(self, before, after):
        """For a line: +1 if going from `before` to `after` crossed it into the zone, -1 out of it,
        0 if not crossed within R1 of the point. Points are (lat, lon)."""
        return self.crossing(self.along_across(*before), self.along_across(*after))

    def crossing(self, before, after):
        """`crossed` from the two places' (along, across), as `along_across` gives them."""
        (a0, c0), (a1, c1) = before, after
        if (a0 > 0.0) == (a1 > 0.0):
            return 0
        f = a0 / (a0 - a1) if a0 != a1 else 0.0
        if abs(c0 + f * (c1 - c0)) > self.r1:
            return 0
        return 1 if a1 > 0.0 else -1

    def shape(self):
        """What the page draws, in degrees: a circle, a line's two ends, or polygons (the outer
        sector, and the inner one where there is one), each a ring of [lat, lon]."""
        if self.line:
            ends = [destination(self.lat, self.lon, self.axis + side, self.r1) for side in (-90.0, 90.0)]
            return {"kind": "line", "ends": [_ll(p) for p in ends]}
        if self.is_cylinder:
            return {"kind": "circle", "lat": round(self.lat, 6), "lon": round(self.lon, 6), "r_m": round(self.r1, 1)}
        rings = [self._sector(self.r1, self.a1, self.r2)]
        if self.r2 > 0.0 and self.a2 > 0.0:
            rings.append(self._sector(self.r2, self.a2, 0.0))
        return {"kind": "polygons", "rings": [[_ll(p) for p in ring] for ring in rings]}

    def _sector(self, outer, half, inner):
        """The ring of a sector between `inner` and `outer`, `half` each side of the axis."""
        ring = self._arc(outer, half)
        if inner > 0.0:
            ring += self._arc(inner, half)[::-1]
        elif half < 180.0:
            ring.append((self.lat, self.lon))
        return ring

    def _arc(self, radius, half):
        steps = max(2, int(math.ceil(2.0 * half / ARC_STEP_DEG)))
        return [destination(self.lat, self.lon, self.axis - half + 2.0 * half * i / steps, radius)
                for i in range(steps + 1)]


def _ll(p):
    return [round(p[0], 6), round(p[1], 6)]


def task_key(taskdef):
    """What a task is, short: its name and its task points' names and places. A file's tasks may
    be reordered or edited between the pilot's choice and its loading, so a task is kept by its
    file, its number and this, and the number is trusted only while this still matches."""
    text = json.dumps([taskdef.label(), [[p.name, round(p.lat, 6), round(p.lon, 6)] for p in taskdef.points]],
                      ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]


def find_task(tasks, index, key):
    """The number of the task in `tasks` (TaskDefs) that `index` and `key` name, or None: `index`
    if its key still matches, else the first task with that key. An empty key trusts the index."""
    if 0 <= index < len(tasks) and (not key or task_key(tasks[index]) == key):
        return index
    if key:
        for i, taskdef in enumerate(tasks):
            if task_key(taskdef) == key:
                return i
    return None


def _axis(style, index, points):
    """The centre line's bearing from point `index` into its zone (see the module's table)."""
    last = len(points) - 1
    p = points[index]

    def away_from(other):
        if distance_m(p.lat, p.lon, other.lat, other.lon) < 1.0:
            return None  # the same place: no direction
        return (bearing_deg(p.lat, p.lon, other.lat, other.lon) + 180.0) % 360.0

    def neighbour():
        """Away from the previous point, or from the next for the start."""
        return away_from(points[index - 1]) if index > 0 else away_from(points[index + 1])

    if style == 1:
        if index == 0:
            style = 2
        elif index == last:
            style = 3
        else:
            b_in = math.radians(bearing_deg(p.lat, p.lon, points[index - 1].lat, points[index - 1].lon))
            b_out = math.radians(bearing_deg(p.lat, p.lon, points[index + 1].lat, points[index + 1].lon))
            x, y = math.sin(b_in) + math.sin(b_out), math.cos(b_in) + math.cos(b_out)
            if math.hypot(x, y) < 1e-9:  # straight through: the bisector is across the course
                return (math.degrees(b_in) + 90.0) % 360.0
            return (math.degrees(math.atan2(x, y)) + 180.0) % 360.0  # the outside of the turn
    if style in (2, 3, 4):
        if style == 2 and index < last:
            axis = away_from(points[index + 1])
        elif style == 3 and index > 0:
            axis = away_from(points[index - 1])
        elif style == 4 and index > 0:
            axis = away_from(points[0])
        else:
            axis = None
        if axis is None:  # no such point, or it is at the same place: a neighbour, else north
            axis = neighbour()
        return 0.0 if axis is None else axis
    return None  # style 0: A12


def make_zone(spec, index, points):
    """The Zone of task point `index`, from the file's ZoneSpec (or None) and our defaults."""
    last = len(points) - 1
    default = DEFAULT_START if index == 0 else DEFAULT_FINISH if index == last else DEFAULT_POINT
    given = spec is not None

    def value(name, fallback):
        v = getattr(spec, name) if given else None
        return fallback if v is None else v

    style = value("style", default["style"])
    line = spec.line if given else default["line"]
    axis = _axis(style, index, points)
    if axis is None:
        axis = (value("a12_deg", 0.0) + 180.0) % 360.0
    p = points[index]
    return Zone(p.lat, p.lon, axis, value("r1_m", default["r1_m"]), value("a1_deg", default["a1_deg"]),
                value("r2_m", 0.0), value("a2_deg", 0.0), line, given)


class Task:
    """A task ready to fly: its points, zones and legs."""

    def __init__(self, taskdef, source=""):
        self.name = taskdef.label()
        self.key = task_key(taskdef)
        self.source = source  # the file it came from, for the page
        self.points = list(taskdef.points)
        self.takeoff, self.landing = taskdef.takeoff, taskdef.landing
        self.zones = [make_zone(taskdef.zones.get(i), i, self.points) for i in range(len(self.points))]
        self.legs_m = [distance_m(a.lat, a.lon, b.lat, b.lon) for a, b in zip(self.points, self.points[1:])]
        self.total_m = sum(self.legs_m)

    def role(self, index):
        return "start" if index == 0 else "finish" if index == len(self.points) - 1 else "point"

    def to_json(self, rev):
        """The whole task for the page (`xpg_task`), drawn once and kept until `rev` changes."""
        def wp(w):
            if w is None:
                return None
            return {"name": w.name, "code": w.code, "lat": round(w.lat, 6), "lon": round(w.lon, 6),
                    "elev_m": None if w.elev_m is None else round(w.elev_m, 1)}

        points = []
        for i, p in enumerate(self.points):
            entry = wp(p)
            entry["role"] = self.role(i)
            entry["zone"] = self.zones[i].shape()
            entry["zone_given"] = self.zones[i].given
            points.append(entry)
        return json.dumps({"rev": rev, "name": self.name, "source": self.source, "points": points,
                           "legs_m": [round(m, 1) for m in self.legs_m], "total_m": round(self.total_m, 1),
                           "takeoff": wp(self.takeoff), "landing": wp(self.landing)},
                          separators=(",", ":"), allow_nan=False)


class Progress:
    """Where the pilot is along a task: the point flown to, and whether started and finished.

    `update` is given the glider's place a few times a second; a line is crossed between the last
    place given and this one (each line's along and across of the last place are kept), so a jump
    must be followed by `forget_place`: a line is never crossed by a jump, and a zone is entered
    only from a place seen outside it after the jump."""

    def __init__(self, task):
        self.task = task
        self.active = 0  # the point flown to: 0 until started
        self.started = False
        self.finished = False
        self.taken = []  # (index, how): "zone", "line" or "hand", the latest last, for the log
        self._lines = {}  # zone index -> (along, across) of the last place, for its line
        self._in = None  # was the last place in the start's zone
        # Was the last place in the zone of the point flown to: None not known (after a jump or a
        # step by hand: the next place only sets it); False after a point taken, so being inside
        # the next zone already takes it.
        self._point_in = False

    def forget_place(self):
        self._lines = {}
        self._in = None
        self._point_in = None

    def update(self, lat, lon):
        """Look at a new place; True if a point was taken."""
        here = (lat, lon)
        changed = False
        if self.active <= 1 and not self.finished:
            changed = self._watch_start(here)
        if self.active >= 1 and not self.finished and not changed:
            changed = self._watch_point(here)
        return changed

    def _crossing(self, index, here):
        """How the line of zone `index` was crossed since the last place: +1 in, -1 out, 0 not."""
        zone = self.task.zones[index]
        now = zone.along_across(*here)
        before = self._lines.get(index)
        self._lines[index] = now
        return 0 if before is None else zone.crossing(before, now)

    def _watch_start(self, here):
        zone = self.task.zones[0]
        if zone.line:
            left = self._crossing(0, here) == -1
        else:
            inside = zone.contains(*here)
            was, self._in = self._in, inside
            left = was is True and not inside
        if not left:
            return False
        self.started = True
        self.active = 1
        self._in = None
        self._point_in = False
        self.taken.append((0, "line" if zone.line else "zone"))
        return True

    def _watch_point(self, here):
        index = self.active
        zone = self.task.zones[index]
        if zone.line:
            entered = self._crossing(index, here) == 1
        else:
            inside = zone.contains(*here)
            was, self._point_in = self._point_in, inside
            entered = inside and was is False
        if not entered:
            return False
        self._point_in = False
        self.taken.append((index, "line" if zone.line else "zone"))
        if index == len(self.task.points) - 1:
            self.finished = True
        else:
            self.active = index + 1
        return True

    def step(self, delta):
        """The pilot moves the point flown to by hand: +1 or -1."""
        count = len(self.task.points)
        if delta > 0:
            if self.finished:
                return
            if self.active == count - 1:
                self.finished = True
            else:
                self.active += 1
            self.started = True
        elif delta < 0:
            if self.finished:
                self.finished = False
            elif self.active > 0:
                self.active -= 1
            self.started = self.active > 0
        self._in = None
        self._point_in = None
        self.taken.append((self.active, "hand"))

    def nav(self, lat, lon):
        """The snapshot's `nav`: the point flown to, bearing and distance to it, and what is left."""
        task = self.task
        index = self.active
        p = task.points[index]
        dist = distance_m(lat, lon, p.lat, p.lon)
        left = dist + sum(task.legs_m[index:]) if not self.finished else 0.0
        done = 1.0 - left / task.total_m if task.total_m > 0.0 and self.started else 0.0
        return {"name": p.name, "code": p.code, "index": index, "count": len(task.points),
                "role": task.role(index),
                "bearing_deg": round(bearing_deg(lat, lon, p.lat, p.lon), 1), "dist_m": round(dist, 1),
                "task_left_m": round(left, 1), "task_done": round(min(max(done, 0.0), 1.0), 3),
                "in_zone": task.zones[index].contains(lat, lon),
                "started": self.started, "finished": self.finished}
