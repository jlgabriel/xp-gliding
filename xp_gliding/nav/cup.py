"""SeeYou CUP files: waypoints and the tasks made of them, for the Flight Computer.

A CUP file is a CSV text in two parts. First the waypoints, one a line, under a header line that
names the columns (in any order; the columns after `style` may be missing). Then, after the line
`-----Related Tasks-----`, the tasks: one line each,

    description, takeoff, start, turn point, ..., finish, landing

naming waypoints from the first part, and after it optional lines that belong to that task:
`Options,...` (start opening, task time and the like: kept, not used), `ObsZone=N,...` (the
observation zone of task point N, the start being 0: the takeoff is not counted), `Point=N,...` (a
task point given in place, with a waypoint's fields, when it is not among the waypoints) and
`STARTS=a,b,...` (other starts sharing the start's zone: noted, not used).

This module only reads: the geometry of zones and the progress along a task are `task.py`'s. It is
written from Naviter's description of the format (version 1.2.2, 2026-11-04) and from real files,
which bend it: the header of older files says `Title,...,Latitude,Longitude,Elevation`; `freq` may
hold any text; task lines may end with an empty field. Nothing in a file raises: a line that does
not parse is skipped and said in `CupFile.notes`, with its line number, for the log.

Lengths and heights are in metres here, whatever unit the file used; latitude and longitude in
degrees, north and east positive (WGS-84).

Pure Python: no `xp`, nothing of the engine.
"""

import csv
import math
import os
import re
import shutil

TASKS_MARK = "-----related tasks-----"

# Units a length or a height may carry; none means metres.
UNITS_M = {"m": 1.0, "ft": 0.3048, "km": 1000.0, "nm": 1852.0, "ml": 1609.344}

# Column names, the old SeeYou header's among them, to the ones used here.
COLUMN_ALIASES = {"title": "name", "latitude": "lat", "longitude": "lon", "elevation": "elev"}
DEFAULT_COLUMNS = ("name", "code", "country", "lat", "lon", "elev", "style", "rwdir", "rwlen", "freq", "desc")

_LAT = re.compile(r"^(\d{1,2})(\d\d(?:\.\d+)?)([NS])$", re.IGNORECASE)
_LON = re.compile(r"^(\d{1,3})(\d\d(?:\.\d+)?)([EW])$", re.IGNORECASE)
_LENGTH = re.compile(r"^([-+]?\d+(?:\.\d*)?|[-+]?\.\d+)\s*([a-z]*)$", re.IGNORECASE)


class Waypoint:
    __slots__ = ("name", "code", "lat", "lon", "elev_m", "style")

    def __init__(self, name, lat, lon, elev_m=None, code="", style=0):
        self.name = name
        self.code = code
        self.lat = lat
        self.lon = lon
        self.elev_m = elev_m  # None when the file gives none
        self.style = style  # Naviter's waypoint style, 0 when unknown

    def __repr__(self):
        return f"Waypoint({self.name!r}, {self.lat:.5f}, {self.lon:.5f})"


class ZoneSpec:
    """An `ObsZone` line as the file gives it: None for each value it leaves out. The height
    limits (metres above sea level) come from other files' tasks (`pln.py`); a CUP file gives none."""

    __slots__ = ("style", "r1_m", "a1_deg", "r2_m", "a2_deg", "a12_deg", "line", "max_alt_m", "min_alt_m")

    def __init__(self, style=None, r1_m=None, a1_deg=None, r2_m=None, a2_deg=None, a12_deg=None, line=False,
                 max_alt_m=None, min_alt_m=None):
        self.style = style
        self.r1_m = r1_m
        self.a1_deg = a1_deg
        self.r2_m = r2_m
        self.a2_deg = a2_deg
        self.a12_deg = a12_deg
        self.line = line
        self.max_alt_m = max_alt_m
        self.min_alt_m = min_alt_m

    def __repr__(self):
        fields = ", ".join(f"{k}={getattr(self, k)!r}" for k in self.__slots__ if getattr(self, k) not in (None, False))
        return f"ZoneSpec({fields})"


class TaskDef:
    """A task as the file gives it: its task points (start first, finish last) and their zones."""

    __slots__ = ("name", "takeoff", "points", "landing", "zones", "options", "line_no", "remarks")

    def __init__(self, name, takeoff, points, landing, zones=None, options=None, line_no=0, remarks=None):
        self.name = name  # "" when the file gives none
        self.takeoff = takeoff  # a Waypoint or None; not a task point
        self.points = points  # [Waypoint], two at least: start, turn points, finish
        self.landing = landing  # a Waypoint or None; not a task point
        self.zones = zones or {}  # task point index (start 0) -> ZoneSpec, only those the file gives
        self.options = options or {}  # the Options line's keys and values, as text
        self.line_no = line_no
        # What the pilot should know when the task is loaded: rules of the file that are not
        # flown as written. Shown with the task, not only logged.
        self.remarks = remarks or []

    def label(self):
        """The name to show: the file's, or the task points' names when it gives none."""
        return self.name or " - ".join(p.name for p in self.points)


class CupFile:
    def __init__(self):
        self.waypoints = {}  # name -> Waypoint, in the file's order
        self.tasks = []  # [TaskDef]
        self.notes = []  # "line N: what was skipped and why"

    def note(self, line_no, text):
        self.notes.append(f"line {line_no}: {text}")


def parse_lat(text):
    """`DDMM.mmmN` or `S` to degrees; None if it is not one."""
    return _angle(_LAT, text, 90.0, "S")


def parse_lon(text):
    """`DDDMM.mmmE` or `W` to degrees; None if it is not one."""
    return _angle(_LON, text, 180.0, "W")


def _angle(pattern, text, limit, negative):
    m = pattern.match(text.strip())
    if not m:
        return None
    degrees, minutes = int(m.group(1)), float(m.group(2))
    if minutes >= 60.0:
        return None
    value = degrees + minutes / 60.0
    if value > limit:
        return None
    return -value if m.group(3).upper() == negative else value


def parse_length(text):
    """A number with an optional unit (m, ft, km, nm, ml) to metres; None if empty or not one."""
    m = _LENGTH.match(text.strip())
    if not m:
        return None
    unit = m.group(2).lower() or "m"
    if unit not in UNITS_M:
        return None
    value = float(m.group(1)) * UNITS_M[unit]
    return value if math.isfinite(value) else None  # 400 digits are infinite as a float


def _number(text):
    try:
        value = float(text)
    except ValueError:
        return None
    return value if value == value and abs(value) != float("inf") else None


def _fields(line):
    """One CSV line to its fields, stripped; [] if the csv module cannot read it."""
    try:
        row = next(csv.reader([line], skipinitialspace=True))
    except (csv.Error, StopIteration):
        return []
    return [f.strip() for f in row]


def decode(data):
    """A file's bytes to text: UTF-8 (with or without its BOM), else Windows-1252."""
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def load(path):
    with open(path, "rb") as f:
        return parse(decode(f.read()))


# The task files the Flight Computer reads: CUP files, and PLN soaring tasks (`pln.py`).
TASK_EXTENSIONS = (".cup", ".pln")


def find_files(folder, extensions=(".cup",)):
    """The files in a folder with one of `extensions` (CUP files by default), by name, sorted
    without regard to case."""
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    found = [n for n in names if n.lower().endswith(extensions) and os.path.isfile(os.path.join(folder, n))]
    return sorted(found, key=str.lower)


def add_examples(folder, examples):
    """Copy the CUP files of `examples` into `folder` when it holds no task file (CUP or PLN), so
    that a first start has a task to fly. A folder that has a file of its own is left as it is, so
    an example the pilot removed comes back only if every file goes. Returns (the names copied,
    the last error or None): a file that cannot be copied is skipped."""
    if find_files(folder, TASK_EXTENSIONS):
        return [], None
    copied, error = [], None
    for name in find_files(examples):
        try:
            shutil.copyfile(os.path.join(examples, name), os.path.join(folder, name))
            copied.append(name)
        except OSError as exc:
            error = str(exc)
    return copied, error


def parse(text):
    """A CUP file's text to a CupFile. Never raises on what the text holds."""
    cup = CupFile()
    lines = text.splitlines()
    columns, first = _header(lines)
    tasks_at = len(lines)
    for i in range(first, len(lines)):
        if lines[i].strip().lower().startswith(TASKS_MARK):
            tasks_at = i
            break
        _waypoint_line(cup, columns, lines[i], i + 1)
    _task_lines(cup, lines, tasks_at + 1)
    return cup


def _header(lines):
    """The columns' names and the first line of waypoints. A file whose first line is a waypoint
    and not a header is read in the usual order."""
    if not lines:
        return DEFAULT_COLUMNS, 0
    names = [COLUMN_ALIASES.get(f.lower(), f.lower()) for f in _fields(lines[0])]
    if "name" in names and "lat" in names and "lon" in names:
        return tuple(names), 1
    return DEFAULT_COLUMNS, 0


def _waypoint_from(columns, fields):
    """A Waypoint from a line's fields, or the reason it is not one."""
    row = dict(zip(columns, fields))
    name = row.get("name", "")
    if not name:
        return None, "no name"
    lat, lon = parse_lat(row.get("lat", "")), parse_lon(row.get("lon", ""))
    if lat is None or lon is None:
        return None, f"{name!r}: latitude or longitude not understood"
    style = _number(row.get("style", "") or "0")
    style = int(style) if style is not None and style == int(style) and 0 <= style <= 21 else 0
    return Waypoint(name, lat, lon, parse_length(row.get("elev", "")), row.get("code", ""), style), None


def _waypoint_line(cup, columns, line, line_no):
    if not line.strip():
        return
    fields = _fields(line)
    wp, why = _waypoint_from(columns, fields)
    if wp is None:
        cup.note(line_no, f"waypoint skipped: {why}")
    elif wp.name in cup.waypoints:
        cup.note(line_no, f"waypoint {wp.name!r} skipped: the name is already used")
    else:
        cup.waypoints[wp.name] = wp


def _task_lines(cup, lines, start):
    """The tasks part: a task line, then the lines that belong to it, until the next task line."""
    block = None
    for i in range(start, len(lines)):
        line, line_no = lines[i].strip(), i + 1
        if not line:
            continue
        key = line.split(",", 1)[0].split("=", 1)[0].strip().lower()
        if key in ("options", "obszone", "point", "starts"):
            if block is None:
                cup.note(line_no, f"{key} line before any task: skipped")
            else:
                block["extra"].append((key, line, line_no))
            continue
        if block is not None:
            _finish_task(cup, block)
        block = {"fields": _fields(line), "line_no": line_no, "extra": []}
    if block is not None:
        _finish_task(cup, block)


def _finish_task(cup, block):
    line_no = block["line_no"]
    fields = list(block["fields"])
    while fields and not fields[-1]:
        fields.pop()  # task lines may end with an empty field
    if len(fields) < 5:
        cup.note(line_no, "task skipped: it needs a takeoff, a start, a finish and a landing")
        return
    name = fields[0]
    named = fields[1:]  # takeoff, task points, landing: 0 is the takeoff
    inline, zones, options = {}, {}, {}
    for key, line, extra_no in block["extra"]:
        if key == "options":
            options.update(_options(line))
        elif key == "obszone":
            index, zone = _zone(line)
            if index is None or not 0 <= index < len(named) - 2:
                cup.note(extra_no, "observation zone skipped: its task point number is missing or not in the task")
            else:
                zones[index] = zone
        elif key == "point":
            index, wp, why = _inline_point(line)
            if wp is None:
                cup.note(extra_no, f"point skipped: {why}")
            elif not 0 <= index < len(named):
                cup.note(extra_no, "point skipped: its number is not in the task")
            else:
                inline[index] = wp
        else:
            cup.note(extra_no, "other starts (STARTS=) not used: the task's own start only")

    def point(position):
        return inline.get(position) or cup.waypoints.get(named[position])

    resolved = [point(p) for p in range(len(named))]
    missing = [named[p] for p in range(1, len(named) - 1) if resolved[p] is None]
    if missing:
        cup.note(line_no, f"task {name or '(no name)'!r} skipped: no waypoint named "
                 + ", ".join(repr(m) for m in missing))
        return
    for p in (0, len(named) - 1):
        if resolved[p] is None and named[p]:
            cup.note(line_no, f"task {name or '(no name)'!r}: no waypoint named {named[p]!r} for its "
                     + ("takeoff" if p == 0 else "landing") + ", left out")
    cup.tasks.append(TaskDef(name, resolved[0], resolved[1:-1], resolved[-1], zones, options, line_no))


def _key_values(line):
    out = {}
    for item in _fields(line):
        if "=" in item:
            k, v = item.split("=", 1)
            out[k.strip().lower()] = v.strip()
    return out


def _options(line):
    return {k: v for k, v in _key_values(line).items() if k != "options"}


def _zone(line):
    """An `ObsZone` line to (task point index, ZoneSpec); index None if it is not given right."""
    kv = _key_values(line)
    index = _number(kv.get("obszone", ""))
    if index is None or index != int(index):
        return None, None
    style = _number(kv.get("style", ""))
    style = int(style) if style is not None and style == int(style) and 0 <= style <= 4 else None
    zone = ZoneSpec(
        style=style,
        r1_m=parse_length(kv["r1"]) if "r1" in kv else None,
        a1_deg=_number(kv["a1"]) if "a1" in kv else None,
        r2_m=parse_length(kv["r2"]) if "r2" in kv else None,
        a2_deg=_number(kv["a2"]) if "a2" in kv else None,
        a12_deg=_number(kv["a12"]) if "a12" in kv else None,
        line=kv.get("line", "").strip().lower() in ("1", "true"),
    )
    return int(index), zone


def _inline_point(line):
    """A `Point=N,<a waypoint's fields>` line to (N, Waypoint, why not). N counts as the task line
    does, the takeoff being 0 (the description: Point=1 is "first turnpoint (after takeoff)")."""
    fields = _fields(line)
    index = _number(fields[0].split("=", 1)[1]) if fields and "=" in fields[0] else None
    if index is None or index != int(index):
        return None, None, "its number is not understood"
    wp, why = _waypoint_from(DEFAULT_COLUMNS, fields[1:])
    return int(index), wp, why
