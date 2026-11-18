"""The task flown (nav/task.py): zones from the file and our defaults, the zone tests, and the
progress along a task as a glider flies it."""

import json

import pytest

from xp_gliding.nav import cup
from xp_gliding.nav.geodesy import bearing_deg, destination, distance_m
from xp_gliding.nav.task import Progress, Task, Zone, make_zone

HOME = (-33.40, -70.60)


def wp(name, lat, lon):
    return cup.Waypoint(name, lat, lon, 600.0)


def at(origin, bearing, metres):
    return destination(origin[0], origin[1], bearing, metres)


def triangle(zones=None):
    """S, then T1 10 km north, T2 10 km east of T1, finish back at S: a right-hand triangle."""
    s = wp("S", *HOME)
    t1 = wp("T1", *at(HOME, 0.0, 10000.0))
    t2 = wp("T2", *at((t1.lat, t1.lon), 90.0, 10000.0))
    f = wp("F", *HOME)
    return Task(cup.TaskDef("Tri", None, [s, t1, t2, f], None, zones or {}))


def angle_between(a, b):
    return abs((a - b + 180.0) % 360.0 - 180.0)


def test_our_defaults_a_start_line_across_the_first_leg_and_cylinders():
    task = triangle()
    start, t1, t2, finish = task.zones
    assert start.line and start.r1 == 1000.0 and not start.given
    assert angle_between(start.axis, 180.0) < 0.01  # behind the start, away from T1 to the north
    assert t1.is_cylinder and t1.r1 == 500.0
    assert finish.is_cylinder and finish.r1 == 500.0
    t2 = task.points[2]
    assert task.total_m == pytest.approx(20000.0 + distance_m(t2.lat, t2.lon, *HOME), rel=1e-9)


def test_a_symmetrical_zone_lies_outside_the_turn():
    spec = cup.ZoneSpec(style=1, r1_m=3000.0, a1_deg=45.0)
    task = triangle({1: spec, 2: spec})
    # Going north then turning east at T1: the inside of the turn is to the south-east, the zone
    # to the north-west.
    assert angle_between(task.zones[1].axis, 315.0) < 0.2
    assert task.zones[1].given and not task.zones[1].is_cylinder


def test_an_out_and_return_turn_point_has_its_zone_beyond_it():
    s, t = wp("S", *HOME), wp("T", *at(HOME, 30.0, 20000.0))
    spec = cup.ZoneSpec(style=1, r1_m=3000.0, a1_deg=45.0)
    task = Task(cup.TaskDef("OR", None, [s, t, s], None, {1: spec}))
    assert angle_between(task.zones[1].axis, 30.0) < 0.2


@pytest.mark.parametrize("style, a12, expected", [
    (0, 0.0, 180.0),  # A12 points from the zone to the point: the zone lies south
    (0, 123.4, 303.4),
    (2, None, 180.0),  # to next (T2 is east of T1): away from T2, so west... checked below
])
def test_fixed_centre_lines(style, a12, expected):
    spec = cup.ZoneSpec(style=style, r1_m=1000.0, a1_deg=45.0, a12_deg=a12)
    task = triangle({0: spec})
    assert angle_between(task.zones[0].axis, expected) < 0.01


def test_to_next_to_previous_and_to_start():
    task = triangle({1: cup.ZoneSpec(style=2, r1_m=1000.0, a1_deg=45.0),
                     2: cup.ZoneSpec(style=3, r1_m=1000.0, a1_deg=45.0),
                     3: cup.ZoneSpec(style=4, r1_m=1000.0, a1_deg=45.0)})
    assert angle_between(task.zones[1].axis, 270.0) < 0.1  # T1, away from T2 to its east
    assert angle_between(task.zones[2].axis, 90.0) < 0.1  # T2, away from T1 to its west
    # The finish is at the start's place: "to start" has no direction there, so it falls back to
    # away from the previous point.
    t2 = task.points[2]
    assert angle_between(task.zones[3].axis, (bearing_deg(*HOME, t2.lat, t2.lon) + 180.0) % 360.0) < 0.1


def test_missing_values_of_a_given_zone_come_from_the_role():
    task = triangle({1: cup.ZoneSpec(r1_m=2000.0), 0: cup.ZoneSpec(style=2, r1_m=500.0, a1_deg=180.0)})
    assert task.zones[1].is_cylinder and task.zones[1].r1 == 2000.0
    assert not task.zones[0].line and task.zones[0].is_cylinder  # given without Line=1: a cylinder


def test_a_sector_contains_what_lies_within_its_angle_and_radius():
    z = Zone(*HOME, axis=90.0, r1=3000.0, a1=45.0)
    assert z.contains(*at(HOME, 90.0, 2000.0))
    assert z.contains(*at(HOME, 130.0, 2900.0))
    assert not z.contains(*at(HOME, 140.0, 2000.0))
    assert not z.contains(*at(HOME, 90.0, 3100.0))
    assert z.contains(*HOME)  # the point itself, R2 0: the outer sector reaches it


def test_an_inner_sector_inside_r2():
    # A "keyhole": a 500 m cylinder (A2 180) inside a 10 km FAI sector starting at R2.
    z = Zone(*HOME, axis=0.0, r1=10000.0, a1=45.0, r2=500.0, a2=180.0)
    assert z.contains(*at(HOME, 180.0, 400.0))  # behind the point, inside the cylinder
    assert not z.contains(*at(HOME, 180.0, 600.0))
    assert z.contains(*at(HOME, 20.0, 8000.0))
    nothing_inside = Zone(*HOME, axis=0.0, r1=10000.0, a1=45.0, r2=500.0, a2=0.0)
    assert not nothing_inside.contains(*at(HOME, 0.0, 300.0))
    assert nothing_inside.contains(*at(HOME, 0.0, 600.0))


def test_a_line_is_crossed_in_a_direction_and_within_its_length():
    z = Zone(*HOME, axis=180.0, r1=1000.0, line=True)  # the zone is south of an east-west line
    south, north = at(HOME, 180.0, 100.0), at(HOME, 0.0, 100.0)
    assert z.contains(*south) and not z.contains(*north)
    assert z.crossed(south, north) == -1
    assert z.crossed(north, south) == 1
    assert z.crossed(south, at(HOME, 180.0, 300.0)) == 0
    far = at(HOME, 90.0, 1500.0)
    assert z.crossed(at(far, 180.0, 100.0), at(far, 0.0, 100.0)) == 0  # past its end


def fly(progress, points, steps=40):
    """Fly straight lines through the given places, a sample every few tens of metres."""
    taken = []
    for a, b in zip(points, points[1:]):
        d, brg = distance_m(*a, *b), bearing_deg(*a, *b)
        n = max(1, int(d / 50.0))
        for i in range(1, n + 1):
            if progress.update(*destination(a[0], a[1], brg, d * i / n)):
                taken.append(progress.taken[-1])
    return taken


def test_a_triangle_flown_takes_every_point_in_order():
    task = triangle()
    p = Progress(task)
    behind = at(HOME, 180.0, 2000.0)
    t1, t2 = (task.points[1].lat, task.points[1].lon), (task.points[2].lat, task.points[2].lon)
    taken = fly(p, [behind, t1, t2, HOME])
    assert taken == [(0, "line"), (1, "zone"), (2, "zone"), (3, "zone")]
    assert p.finished and p.started


def test_no_start_without_crossing_the_line_the_right_way():
    task = triangle()
    p = Progress(task)
    ahead = at(HOME, 0.0, 2000.0)
    fly(p, [ahead, at(HOME, 270.0, 3000.0)])  # passes beside the line, never across it
    assert not p.started
    fly(p, [at(HOME, 0.0, 500.0), at(HOME, 180.0, 500.0)])  # across it, the wrong way
    assert not p.started and p.active == 0


def test_crossing_the_start_again_before_the_first_point_restarts():
    task = triangle()
    p = Progress(task)
    fly(p, [at(HOME, 180.0, 1000.0), at(HOME, 0.0, 2000.0), at(HOME, 180.0, 1000.0), at(HOME, 0.0, 2000.0)])
    assert [t for t in p.taken] == [(0, "line"), (0, "line")]
    assert p.active == 1 and p.started


def test_a_cylinder_start_is_taken_on_leaving_it():
    task = triangle({0: cup.ZoneSpec(style=2, r1_m=3000.0, a1_deg=180.0)})
    p = Progress(task)
    fly(p, [at(HOME, 0.0, 4000.0), at(HOME, 0.0, 3500.0)])  # outside all along: nothing
    assert not p.started
    fly(p, [at(HOME, 0.0, 2000.0), at(HOME, 0.0, 4000.0)])
    assert p.started and p.taken[-1] == (0, "zone")


def test_a_jump_does_not_cross_a_line():
    task = triangle()
    p = Progress(task)
    p.update(*at(HOME, 180.0, 300.0))
    p.forget_place()
    p.update(*at(HOME, 0.0, 300.0))
    assert not p.started


def test_points_by_hand():
    p = Progress(triangle())
    p.step(-1)
    assert p.active == 0 and not p.started
    p.step(1)
    assert p.active == 1 and p.started
    p.step(1), p.step(1)
    assert p.active == 3 and not p.finished
    p.step(1)
    assert p.finished
    p.step(1)
    assert p.finished and p.active == 3
    p.step(-1)
    assert not p.finished and p.active == 3
    p.step(-1), p.step(-1), p.step(-1)
    assert p.active == 0 and not p.started
    assert p.taken[-1] == (0, "hand")


def test_nav_bearing_distance_and_what_is_left():
    task = triangle()
    p = Progress(task)
    here = at(HOME, 225.0, 5000.0)
    nav = p.nav(*here)
    assert nav["name"] == "S" and nav["role"] == "start" and nav["index"] == 0 and nav["count"] == 4
    assert nav["dist_m"] == pytest.approx(5000.0, abs=0.1)
    assert nav["bearing_deg"] == pytest.approx(bearing_deg(*here, *HOME), abs=0.05)
    assert nav["task_left_m"] == pytest.approx(5000.0 + task.total_m, abs=0.5)
    assert nav["task_done"] == 0.0 and not nav["started"]
    p.step(1), p.step(1)  # flying to T2, from T1
    t1 = (task.points[1].lat, task.points[1].lon)
    nav = p.nav(*t1)
    assert nav["role"] == "point" and nav["name"] == "T2"
    assert nav["task_left_m"] == pytest.approx(task.legs_m[1] + task.legs_m[2], abs=0.5)
    assert nav["task_done"] == pytest.approx(task.legs_m[0] / task.total_m, abs=0.001)
    p.step(1), p.step(1)
    nav = p.nav(*HOME)
    assert nav["finished"] and nav["task_left_m"] == 0.0 and nav["task_done"] == 1.0 and nav["in_zone"]


def test_the_task_for_the_page():
    spec = cup.ZoneSpec(style=1, r1_m=10000.0, a1_deg=45.0, r2_m=500.0, a2_deg=180.0)
    task = triangle({1: spec, 2: cup.ZoneSpec(style=1, r1_m=3000.0, a1_deg=45.0)})
    data = json.loads(task.to_json(7))
    assert data["rev"] == 7 and data["name"] == "Tri" and len(data["points"]) == 4
    roles = [p["role"] for p in data["points"]]
    assert roles == ["start", "point", "point", "finish"]
    start, keyhole, fai, finish = (p["zone"] for p in data["points"])
    assert start["kind"] == "line" and len(start["ends"]) == 2
    assert distance_m(*start["ends"][0], *start["ends"][1]) == pytest.approx(2000.0, rel=1e-3)
    assert keyhole["kind"] == "polygons" and len(keyhole["rings"]) == 2
    assert fai["kind"] == "polygons" and len(fai["rings"]) == 1
    t2 = task.points[2]
    for lat, lon in fai["rings"][0]:  # every corner within the sector's radius of its point
        assert distance_m(t2.lat, t2.lon, lat, lon) <= 3000.5
    assert finish == {"kind": "circle", "lat": round(HOME[0], 6), "lon": round(HOME[1], 6), "r_m": 500.0}
    assert data["points"][1]["zone_given"] and not data["points"][0]["zone_given"]
    assert data["total_m"] == pytest.approx(task.total_m, abs=0.1)


def test_a_task_from_a_file_with_a_zone_on_its_finish():
    text = ('name,code,country,lat,lon,elev,style\n'
            '"Home",,,3900.000N,11945.000W,1400m,2\n'
            '"Start",,,3901.000N,11940.000W,1500m,1\n'
            '"North",,,3930.000N,11940.000W,1500m,1\n'
            '"East",,,3915.000N,11900.000W,1500m,1\n'
            '-----Related Tasks-----\n'
            '"G","Home","Start","North","East","Start","Home"\n'
            'ObsZone=3,Style=1,R1=3000m,A1=45\n')
    (taskdef,) = cup.parse(text).tasks
    task = Task(taskdef, "g.cup")
    finish, east = task.zones[3], task.points[2]
    # Symmetrical at the finish is "to previous": the sector beyond the finish, away from East.
    away = (bearing_deg(finish.lat, finish.lon, east.lat, east.lon) + 180.0) % 360.0
    assert angle_between(finish.axis, away) < 0.01 and finish.a1 == 45.0
    assert task.zones[0].line and task.zones[1].is_cylinder


def test_make_zone_of_a_two_point_task():
    a, b = wp("A", *HOME), wp("B", *at(HOME, 90.0, 5000.0))
    start = make_zone(None, 0, [a, b])
    finish = make_zone(cup.ZoneSpec(style=1, r1_m=1000.0, a1_deg=45.0), 1, [a, b])
    assert angle_between(start.axis, 270.0) < 0.1  # (the great circle's bearing turns a little over 5 km)
    assert angle_between(finish.axis, 90.0) < 0.1


def test_symmetrical_zones_point_where_seeyou_points_them():
    # A real task as SeeYou wrote it (Naviter's QR-code example in its format repository, a
    # triangle from Lienz, Austria): the points' places, and the direction SeeYou worked out for
    # each zone, given there as A12 (the zone lies at A12 + 180). Moelltal's A12 is exactly 270, set
    # by its author rather than worked out, so it is left out.
    places = [("Lienz mesto", 46.83917, 12.76612, 253.5), ("Toblach", 46.72888, 12.22972, 55.7),
              ("Matrei", 47.00083, 12.53862, 157.7), ("Moelltal", 46.93722, 13.21222, None),
              ("Berg", 46.74805, 13.13528, 331.0), ("Lienz", 46.79805, 12.88555, 106.3)]
    points = [wp(name, lat, lon) for name, lat, lon, _ in places]
    spec = cup.ZoneSpec(style=1, r1_m=3000.0, a1_deg=45.0)
    task = Task(cup.TaskDef("Lienz", None, points, None, {i: spec for i in range(len(points))}))
    for (name, _, _, a12), zone in zip(places, task.zones):
        if a12 is not None:
            assert angle_between(zone.axis, a12 + 180.0) < 0.5, name
