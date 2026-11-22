"""PLN soaring tasks (nav/pln.py), their height limits in the progress (nav/task.py) and the
task files of both kinds (nav/taskfiles.py). The files here are written for the tests, in the form
the SSC Task Generator, WeSimGlide's Task Builder and B21 Task Planner write; real ones stay out of
the repository. The readings were checked against B21 Task Planner itself on eleven Sim Soaring
Club tasks (2026-11-22): the same points, places, radii, limits and elevations."""

import pytest

from xp_gliding.nav import cup, pln, taskfiles
from xp_gliding.nav.geodesy import destination
from xp_gliding.nav.task import Progress, Task, task_key

FT = 0.3048


def dms(value, positive, negative):
    hemisphere = positive if value >= 0 else negative
    value = abs(value)
    d = int(value)
    m = int((value - d) * 60.0)
    s = (value - d - m / 60.0) * 3600.0
    return f"{hemisphere}{d}° {m}' {s:.2f}\""


def position(lat, lon, ft):
    return f"{dms(lat, 'N', 'S')},{dms(lon, 'E', 'W')},{ft:+010.2f}"


def plan(waypoints, title="Test task", departure="SCTB", destination_id="SCTB"):
    """A flight plan's text: waypoints are (id, lat, lon, feet, type, ident)."""
    items = []
    for wid, lat, lon, ft, kind, ident in waypoints:
        items.append(f"""        <ATCWaypoint id="{wid}">
            <ATCWaypointType>{kind}</ATCWaypointType>
            <WorldPosition>{position(lat, lon, ft)}</WorldPosition>
            <SpeedMaxFP>-1</SpeedMaxFP>
            <ICAO>
                <ICAOIdent>{ident}</ICAOIdent>
            </ICAO>
        </ATCWaypoint>""")
    return f"""<?xml version="1.0" encoding="UTF-8"?>

<SimBase.Document Type="AceXML" version="1,0">
    <Descr>AceXML Document</Descr>
    <!-- Created by a test -->
    <FlightPlan.FlightPlan>
        <Title>{title}</Title>
        <FPType>VFR</FPType>
        <DepartureID>{departure}</DepartureID>
        <DestinationID>{destination_id}</DestinationID>
{chr(10).join(items)}
    </FlightPlan.FlightPlan>
</SimBase.Document>
""".encode("utf-8")


HOME = (-33.4547, -70.5469)  # Tobalaba


def north(m, east=0.0):
    lat, lon = destination(HOME[0], HOME[1], 0.0, m)
    return destination(lat, lon, 90.0, east) if east else (lat, lon)


def triangle(start="*Start+2132|5000x5000", tp1="WP 1+2500x1000", tp2="WP 2+2600/3000x2000",
             finish="*Finish+2132/2500x2000"):
    """Departure, start, two turn points, finish, destination: as the tools lay out a task."""
    return plan([
        ("Tobalaba", *HOME, 2132.0, "Airport", "SCTB"),
        (start, *north(3000), 2132.0, "User", "S0K50P0A"),
        (tp1, *north(20000), 2500.0, "User", "C0HF0500"),
        (tp2, *north(20000, 15000), 2600.0, "User", "D0EV0500"),
        (finish, *north(1000), 2132.0, "User", "F0S60A30"),
        ("Tobalaba", *HOME, 2132.0, "Airport", "SCTB"),
    ])


# --- the names ---------------------------------------------------------------------------------


def test_the_names_as_b21_reads_them():
    c = pln.decode_name("*Burnt Cabins+2310|6000/1000x800")  # the help page's example
    assert (c.name, c.mark, c.elev_ft, c.max_ft, c.min_ft, c.diameter_m, c.radius_m) == \
        ("Burnt Cabins", "*", 2310.0, 6000.0, 1000.0, 800.0, 400.0)
    c = pln.decode_name("WP 1+627x1000")  # no "|": the size is read after the "+"
    assert (c.name, c.mark, c.elev_ft, c.max_ft, c.radius_m) == ("WP 1", None, 627.0, None, 500.0)
    c = pln.decode_name("*Finish+1014/1514x2000")
    assert (c.name, c.min_ft, c.max_ft, c.radius_m) == ("Finish", 1514.0, None, 1000.0)
    c = pln.decode_name("*Start 6000+2174|6000x5000")
    assert (c.name, c.max_ft, c.radius_m) == ("Start 6000", 6000.0, 2500.0)
    c = pln.decode_name("WP 5+5515|6500")
    assert (c.max_ft, c.diameter_m) == (6500.0, None)
    c = pln.decode_name("Burnt Cabins|x800")
    assert (c.name, c.max_ft, c.radius_m) == ("Burnt Cabins", None, 400.0)
    c = pln.decode_name("TP 1 Stoss-Pass Kirche+3162x8000")
    assert (c.name, c.radius_m) == ("TP 1 Stoss-Pass Kirche", 4000.0)


def test_what_a_name_without_the_codes_says():
    for raw in ("Box Hill", "Max x 500", "Lukla"):  # an x outside the codes is not a size
        c = pln.decode_name(raw)
        assert (c.name, c.mark, c.elev_ft, c.max_ft, c.min_ft, c.diameter_m) == (raw, None, None, None, None, None)
    assert pln.decode_name("START+100").mark == "start"  # a name beginning with "start" marks it too
    assert pln.decode_name("Start here").mark == "start" and pln.decode_name("finish line").mark == "finish"
    assert pln.decode_name("N47.123,E9.5").name == "N47.123,E9.5"  # an EFB's place: left as it is
    c = pln.decode_name("WP 3+100x0")
    assert c.diameter_m is None  # no zone of no size: the default


def test_an_assigned_area_and_the_minimum_time():
    assert pln.decode_name("WP 2+500x8000;AAT").aat
    c = pln.decode_name("*Start+500|5000x5000;AAT02:30;")
    assert c.aat and c.aat_min_s == 2 * 3600 + 30 * 60


@pytest.mark.parametrize("text,expected", [
    ("N57° 6' 8.03\",W3° 53' 28.18\",+000889.11", (57.10223, -3.89116, 889.11)),
    ("S44° 26' 17.76\",E169° 23' 23.46\",-000000.00", (-44.43827, 169.38985, 0.0)),
    ("N47° 31' 13.18\",E12° 26' 57.63\"", (47.52033, 12.44934, None)),
    ("N27° 41.5',E86° 43.25'", (27.69167, 86.72083, None)),
])
def test_world_positions(text, expected):
    lat, lon, ft = pln.parse_position(text)
    assert lat == pytest.approx(expected[0], abs=1e-5) and lon == pytest.approx(expected[1], abs=1e-5)
    assert ft == expected[2]


@pytest.mark.parametrize("text", ["", "57.1,-3.9", "N91° 0' 0\",E1° 0' 0\"", "N57° 60' 0\",E1° 0' 0\"",
                                  "N57° 6' 8.03\""])
def test_what_is_not_a_world_position(text):
    assert pln.parse_position(text) is None


# --- the task ----------------------------------------------------------------------------------


def test_a_task_its_airfields_its_zones_and_limits():
    f = pln.parse(triangle())
    assert f.notes == []
    (t,) = f.tasks
    assert t.name == "Test task" and [p.name for p in t.points] == ["Start", "WP 1", "WP 2", "Finish"]
    assert (t.takeoff.name, t.takeoff.code, t.landing.code) == ("Tobalaba", "SCTB", "SCTB")
    assert t.points[1].code == ""  # WSG's encoded idents mean nothing to the pilot
    assert t.points[1].elev_m == pytest.approx(2500.0 * FT)
    start, tp1, tp2, finish = (t.zones[i] for i in range(4))
    assert (start.style, start.line, start.r1_m, start.max_alt_m, start.min_alt_m) == (2, True, 2500.0, 5000 * FT, None)
    assert (tp1.style, tp1.line, tp1.r1_m, tp1.a1_deg, tp1.max_alt_m) == (1, False, 500.0, 180.0, None)
    assert (tp2.r1_m, tp2.min_alt_m) == (1000.0, 3000 * FT)
    assert (finish.style, finish.line, finish.r1_m, finish.a1_deg, finish.min_alt_m) == (3, False, 1000.0, 90.0, 2500 * FT)
    assert t.remarks == []


def test_the_zones_shapes_as_b21_draws_them():
    task = Task(pln.parse(triangle()).tasks[0])
    start, finish = task.zones[0], task.zones[-1]
    # The start line, 5 km long, across the first leg (due north): the zone behind it, south
    assert start.line and start.r1 == 2500.0 and start.axis == pytest.approx(180.0, abs=0.1)
    # The finish: the half of its 1 km cylinder beyond the point, on the far side from WP 2
    beyond = destination(finish.lat, finish.lon, finish.axis, 900.0)
    before = destination(finish.lat, finish.lon, finish.axis + 180.0, 300.0)
    assert finish.contains(*beyond) and not finish.contains(*before)
    assert task.zones[1].is_cylinder and task.zones[1].r1 == 500.0


def test_the_defaults_without_a_size():
    f = pln.parse(triangle(start="*Start+2132", tp1="WP 1+2500", tp2="WP 2", finish="*Finish+2132"))
    sizes = [f.tasks[0].zones[i].r1_m for i in range(4)]
    assert sizes == [2500.0, 500.0, 500.0, 2000.0]  # B21 Task Planner's: start, turn point, finish


def test_without_marks_the_second_and_the_one_before_last():
    f = pln.parse(triangle(start="Start point+2132", tp1="WP 1", tp2="WP 2", finish="Goal"))
    # "Start point" begins with "start": the planner takes it as the start; the finish is the one before last
    assert [p.name for p in f.tasks[0].points] == ["Start point", "WP 1", "WP 2", "Goal"]
    f = pln.parse(triangle(start="Alpha", tp1="WP 1", tp2="WP 2", finish="Omega"))
    assert [p.name for p in f.tasks[0].points] == ["Alpha", "WP 1", "WP 2", "Omega"]


def test_points_before_the_start_and_after_the_finish_are_left_out():
    data = plan([
        ("Tobalaba", *HOME, 2132.0, "Airport", "SCTB"),
        ("Climb here", *north(1000), 3000.0, "User", ""),
        ("*Start+2132|5000x5000", *north(3000), 2132.0, "User", ""),
        ("WP 1+2500x1000", *north(20000), 2500.0, "User", ""),
        ("*Finish+2132x2000", *north(1000), 2132.0, "User", ""),
        ("Circuit", *north(500), 2500.0, "User", ""),
        ("Tobalaba", *HOME, 2132.0, "Airport", "SCTB"),
    ])
    f = pln.parse(data)
    t = f.tasks[0]
    assert [p.name for p in t.points] == ["Start", "WP 1", "Finish"] and t.takeoff.name == t.landing.name == "Tobalaba"
    assert f.notes == ["not task points, left out: 'Climb here', 'Circuit'"]


def test_a_start_or_finish_that_is_an_airfield_has_no_takeoff_or_landing():
    data = plan([
        ("*Tobalaba+2132|5000x5000", *HOME, 2132.0, "Airport", "SCTB"),
        ("WP 1+2500x1000", *north(20000), 2500.0, "User", ""),
        ("*Home+2132x2000", *north(1000), 2132.0, "User", ""),
    ])
    t = pln.parse(data).tasks[0]
    assert t.takeoff is None and t.landing is None and len(t.points) == 3


def test_the_elevation_the_name_gives_or_the_place():
    near = plan([("Tobalaba", *HOME, 2132.4, "Airport", "SCTB"), ("*S+2132x5000", *north(3000), 2132.4, "User", ""),
                 ("*F+2000x2000", *north(1000), 1990.0, "User", ""), ("Tobalaba", *HOME, 0.0, "Airport", "SCTB")])
    t = pln.parse(near).tasks[0]
    assert t.points[0].elev_m == pytest.approx(2132.4 * FT)  # within half a foot: the place's, finer
    assert t.points[1].elev_m == pytest.approx(2000 * FT)  # else the name's
    assert t.takeoff.elev_m == pytest.approx(2132.4 * FT)
    assert t.landing.elev_m is None  # no code and 0 in the place: not known


def test_an_assigned_area_task_is_said_with_the_task():
    t = pln.parse(triangle(start="*Start+2132|5000x5000;AAT02:30;", tp1="WP 1+2500x8000;AAT",
                           tp2="WP 2+2600x10000;AAT")).tasks[0]
    assert t.remarks == ["Assigned areas (AAT) flown as cylinders, to be entered: WP 1, WP 2. "
                         "The task is not scored as an AAT.", "Minimum task time 2:30 not used."]
    assert t.zones[1].r1_m == 4000.0


@pytest.mark.parametrize("data,note", [
    (b"", "not read: not XML"),
    (b"<a><b></a>", "not read: not XML"),
    (b"<SimBase.Document><Other/></SimBase.Document>", "not read: no FlightPlan.FlightPlan in it"),
    (b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>', "not read: it declares"),
    (b"<FlightPlan.FlightPlan><Title>t</Title></FlightPlan.FlightPlan>", "no task: a task needs"),
    (b" " * (pln.MAX_BYTES + 1), "not read: too big"),
])
def test_what_is_not_a_task(data, note):
    f = pln.parse(data)
    assert f.tasks == [] and f.notes[0].startswith(note)


def test_a_finish_before_its_start_and_a_bad_place():
    data = plan([("Tobalaba", *HOME, 0.0, "Airport", "SCTB"), ("Start", *north(3000), 0.0, "User", ""),
                 ("Finish", *north(1000), 0.0, "User", ""), ("WP 1", *north(9000), 0.0, "User", ""),
                 ("Tobalaba", *HOME, 0.0, "Airport", "SCTB")])
    data = data.replace(b'id="WP 1"', b'id="Start again"')  # a later start mark overrides
    f = pln.parse(data)
    assert f.tasks == [] and "is not after its start" in f.notes[0]
    bad = triangle().replace(b"<WorldPosition>S33", b"<WorldPosition>nowhere S33", 1)
    f = pln.parse(bad)
    assert "its WorldPosition is not understood" in f.notes[0]


def test_a_cup_tasks_key_has_no_height_limits_in_it():
    text = ("name,code,country,lat,lon,elev,style\n"
            '"A",,,3327.282S,07032.814W,650m,1\n"B",,,3320.000S,07032.814W,650m,1\n'
            "-----Related Tasks-----\n" '"T","A","A","B","A"\n')
    t = cup.parse(text).tasks[0]
    assert task_key(t) == task_key(t)  # nothing random
    t.zones[0] = cup.ZoneSpec(style=2, r1_m=1000.0, line=True)
    plain = task_key(t)
    t.zones[0] = cup.ZoneSpec(style=2, r1_m=1000.0, line=True, max_alt_m=1500.0)
    assert task_key(t) != plain


# --- height limits in the progress -----------------------------------------------------------


def progress_of(data):
    task = Task(pln.parse(data).tasks[0])
    return task, Progress(task)


def fly_north(progress, from_m, to_m, msl, east=0.0, t0=0.0, step=10.0):
    """Places every `step` metres from `from_m` to `to_m` north of HOME, at 25 m/s."""
    n = int(abs(to_m - from_m) / step)
    t = t0
    for k in range(n + 1):
        t = t0 + k * step / 25.0
        lat, lon = north(from_m + (to_m - from_m) * k / n, east)
        progress.update(lat, lon, t, msl)
    return t


def test_the_start_is_taken_only_below_its_maximum():
    task, p = progress_of(triangle())
    t = fly_north(p, 2500.0, 3500.0, 1600.0)  # across the start line, over 5000 ft (1524 m)
    assert not p.started and p.refused == [(0, "high", 1600.0)]
    t = fly_north(p, 3500.0, 2500.0, 1600.0, t0=t + 1.0)  # back across: going the wrong way
    assert not p.started and len(p.refused) == 1
    fly_north(p, 2500.0, 3500.0, 1500.0, t0=t + 1.0)
    assert p.started and p.active == 1 and p.taken == [(0, "line")]


def test_a_turn_point_is_taken_inside_it_once_within_its_limits():
    task, p = progress_of(triangle(tp1="WP 1+2500|8000x1000"))  # at most 8000 ft, 2438.4 m
    p.step(1)
    t = fly_north(p, 18000.0, 20000.0, 2600.0)  # in the cylinder, too high
    assert p.active == 1 and p.refused == [(1, "high", 2600.0)]
    nav = p.nav(*north(20000), msl=2600.0)
    assert nav["height"] == "high" and nav["max_m"] == pytest.approx(2438.4) and nav["min_m"] is None
    p.update(*north(20000), t + 1.0, 2400.0)  # down into the band, still inside: taken
    assert p.active == 2 and p.taken[-1] == (1, "zone")
    assert len(p.refused) == 1  # once each time the zone is reached, not at every place


def test_a_minimum_at_a_turn_point_and_at_the_finish():
    task, p = progress_of(triangle())  # WP 2 at least 3000 ft (914.4 m), finish at least 2500 ft
    p.step(1), p.step(1)
    lat, lon = north(20000, 15000)
    p.update(lat - 0.02, lon, 0.0, 800.0)  # outside
    p.update(lat, lon, 100.0, 800.0)  # inside, too low
    assert p.active == 2 and p.refused == [(2, "low", 800.0)]
    p.update(lat, lon, 101.0, 950.0)
    assert p.active == 3
    finish = task.zones[3]
    inside = destination(finish.lat, finish.lon, finish.axis, 500.0)
    outside = destination(finish.lat, finish.lon, finish.axis + 180.0, 1500.0)
    p.update(*outside, 200.0, 700.0)
    p.update(*inside, 260.0, 700.0)  # 700 m is under 2500 ft (762 m)
    assert not p.finished and p.refused[-1] == (3, "low", 700.0)
    p.update(*inside, 261.0, 800.0)
    assert p.finished


def test_no_height_given_meets_every_limit():
    task, p = progress_of(triangle())
    fly_north(p, 2500.0, 3500.0, None)
    assert p.started and p.refused == []
    assert p.nav(*north(3500))["height"] is None


def test_a_task_without_limits_reads_none():
    task, p = progress_of(triangle(start="*Start+2132x5000", finish="*Finish+2132x2000"))
    nav = p.nav(*north(2000), msl=5000.0)
    assert (nav["max_m"], nav["min_m"], nav["height"]) == (None, None, None)


def test_the_task_for_the_page_has_its_limits_and_remarks():
    import json
    task = Task(pln.parse(triangle(tp1="WP 1+2500x8000;AAT")).tasks[0], "test.pln")
    page = json.loads(task.to_json(3))
    assert page["points"][0]["max_m"] == 1524.0 and page["points"][0]["min_m"] is None
    assert page["points"][3]["min_m"] == 762.0
    assert page["remarks"] and "WP 1" in page["remarks"][0]
    assert page["points"][3]["zone"]["kind"] == "polygons"  # the half cylinder


# --- task files of both kinds ----------------------------------------------------------------


def test_the_task_files_of_both_kinds(tmp_path):
    (tmp_path / "b.PLN").write_bytes(triangle())
    (tmp_path / "a.cup").write_text("name,code,country,lat,lon,elev,style\n", encoding="utf-8")
    (tmp_path / "c.txt").write_text("no", encoding="utf-8")
    assert taskfiles.find_files(str(tmp_path)) == ["a.cup", "b.PLN"]
    assert taskfiles.load(str(tmp_path / "b.PLN")).tasks[0].name == "Test task"
    assert taskfiles.load(str(tmp_path / "a.cup")).tasks == []


def test_a_folder_with_only_flight_plans_gets_no_example(tmp_path):
    examples = tmp_path / "examples"
    examples.mkdir()
    (examples / "home.cup").write_text("name,code,country,lat,lon,elev,style\n", encoding="utf-8")
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "ssc.pln").write_bytes(triangle())
    assert cup.add_examples(str(tasks), str(examples)) == ([], None)
