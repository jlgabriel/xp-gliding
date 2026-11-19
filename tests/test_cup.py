"""CUP files (nav/cup.py): waypoints, tasks, zones, units, encodings and the ways real files bend
the format. The files here are written for the tests; real ones stay out of the repository."""

import os

import pytest

from xp_gliding.nav import cup, geodesy

HEADER = "name,code,country,lat,lon,elev,style,rwdir,rwlen,rwwidth,freq,desc,userdata,pics\n"


def test_latitude_and_longitude():
    assert cup.parse_lat("5107.830N") == pytest.approx(51 + 7.83 / 60)
    assert cup.parse_lat("3327.282S") == pytest.approx(-(33 + 27.282 / 60))
    assert cup.parse_lon("01410.467E") == pytest.approx(14 + 10.467 / 60)
    assert cup.parse_lon("07032.814W") == pytest.approx(-(70 + 32.814 / 60))
    assert cup.parse_lon("11712.000w") == pytest.approx(-(117 + 12 / 60))  # case does not matter
    assert cup.parse_lat("0000.000N") == 0.0


@pytest.mark.parametrize("text", ["", "5107.830", "5160.000N", "9100.000N", "51O7.830N", "N5107.830",
                                  "5107.830E"])
def test_what_is_not_a_latitude(text):
    assert cup.parse_lat(text) is None


@pytest.mark.parametrize("text", ["", "01410.467", "18100.000E", "01460.000W", "01410.467N", "E01410.467"])
def test_what_is_not_a_longitude(text):
    assert cup.parse_lon(text) is None


def test_lengths_carry_their_unit_and_metres_without_one():
    assert cup.parse_length("504.0m") == pytest.approx(504.0)
    assert cup.parse_length("525ft") == pytest.approx(160.02)
    assert cup.parse_length("3km") == pytest.approx(3000.0)
    assert cup.parse_length("1.5nm") == pytest.approx(2778.0)
    assert cup.parse_length("2ml") == pytest.approx(3218.688)
    assert cup.parse_length("400") == pytest.approx(400.0)
    assert cup.parse_length("0.7KM") == pytest.approx(700.0)
    for bad in ("", "m", "12 parsecs", "1,5km", "abc", "9" * 400 + "m"):  # 400 digits: inf as a float
        assert cup.parse_length(bad) is None


def test_waypoints_by_the_header_names_in_any_order():
    text = ("lat,lon,elev,name,code,country,style\n"
            "4621.379N,01410.467E,504.0m,Lesce,LJBL,SI,5\n"
            '5147.809N,00405.003W,525ft,"Cross Hands, A48",CSS,UK,1\n')
    f = cup.parse(text)
    assert list(f.waypoints) == ["Lesce", "Cross Hands, A48"]
    lesce = f.waypoints["Lesce"]
    assert (lesce.code, lesce.style) == ("LJBL", 5)
    assert lesce.lat == pytest.approx(46.35632, abs=1e-5) and lesce.elev_m == pytest.approx(504.0)
    assert f.waypoints["Cross Hands, A48"].lon < 0
    assert f.notes == []


def test_the_old_header_and_a_file_without_one():
    old = ("Title,Code,Country,Latitude,Longitude,Elevation,Style,Direction,Length,Frequency,Description\n"
           '"Tobalaba",SCTB,CL,3327.282S,07032.814W,650.0m,5,010,1400.0m,118.100,"Home"\n')
    assert cup.parse(old).waypoints["Tobalaba"].lat == pytest.approx(-33.45470, abs=1e-5)
    bare = '"Tobalaba",SCTB,CL,3327.282S,07032.814W,650.0m,5,010,1400.0m,118.100,"Home"\n'
    assert list(cup.parse(bare).waypoints) == ["Tobalaba"]


def test_bad_waypoints_are_skipped_and_said():
    text = (HEADER
            + '"Good",,,3900.010N,11945.160W,1438.0m,2,,,,,,\n'
            + '"Bad lat",,,39XX.010N,11945.160W,1438.0m,2,,,,,,\n'
            + ',,,3900.010N,11945.160W,1438.0m,2,,,,,,\n'
            + '"Good",,,3800.000N,11945.160W,1438.0m,2,,,,,,\n'
            + "\n"
            + '"Unclosed,,,3900.010N\n')
    f = cup.parse(text)
    assert list(f.waypoints) == ["Good"]
    assert f.waypoints["Good"].lat == pytest.approx(39.00017, abs=1e-5)  # the first of a name stays
    assert len(f.notes) == 4
    assert f.notes[0].startswith("line 3:")


def test_an_unknown_style_is_zero_and_a_missing_elevation_none():
    f = cup.parse(HEADER + '"A",,,3900.000N,11900.000W,,99,,,,,,\n')
    assert f.waypoints["A"].style == 0 and f.waypoints["A"].elev_m is None


# A file shaped like a real one (Minden, Nevada, a public set of courses): no rwwidth column,
# `freq` used for text, doubled quotes in a description, the takeoff also the finish and landing,
# tasks without zones, one with a zone for its finish only.
MINDEN_LIKE = '''name,code,country,lat,lon,elev,style,rwdir,rwlen,freq,desc,userdata,pics
"Minden - FG",,,3900.010N,11945.160W,1438.0m,2,0,0.0m,"MEV InterSec","MEV InterSec",,
"Sunrise Start",Sunriart,,3901.120N,11940.080W,1582.2m,1,,,,"Dirt Y Int",,
"Eureka Int",,,3930.750N,11557.600W,1981.2m,1,,,,"Be over ""E""",,
"Rawe Pk R/F",,,3911.830N,11929.370W,2478.0m,1,,,,"100k 2nd TP",,
"CedarFlatInt",,,3716.950N,11809.030W,2218.9m,1,,,,"White Mtn TO",,
-----Related Tasks-----
"A Out and Return","Minden - FG","Sunrise Start","Eureka Int","Sunrise Start","Minden - FG"
Options,NearAlt=656.0ft
"G Triangle","Minden - FG","Sunrise Start","CedarFlatInt","Rawe Pk R/F","Sunrise Start","Minden - FG"
Options,NearAlt=656.0ft
ObsZone=3,Style=1,R1=3000m,A1=45
"D Three","Minden - FG","Sunrise Start","Eureka Int","Rawe Pk R/F","Minden - FG","Minden - FG"
'''


def test_a_file_shaped_like_a_real_one():
    f = cup.parse(MINDEN_LIKE)
    assert f.notes == []
    assert len(f.waypoints) == 5
    assert f.waypoints["Eureka Int"].lat == pytest.approx(39.5125)
    assert [t.name for t in f.tasks] == ["A Out and Return", "G Triangle", "D Three"]
    a, g, d = f.tasks
    assert a.takeoff.name == "Minden - FG" and a.landing.name == "Minden - FG"
    assert [p.name for p in a.points] == ["Sunrise Start", "Eureka Int", "Sunrise Start"]
    assert a.options == {"nearalt": "656.0ft"} and a.zones == {}
    assert [p.name for p in g.points] == ["Sunrise Start", "CedarFlatInt", "Rawe Pk R/F", "Sunrise Start"]
    finish = g.zones[3]  # counted from the start, 0: the 3 is G's finish
    assert (finish.style, finish.r1_m, finish.a1_deg, finish.line) == (1, 3000.0, 45.0, False)
    assert finish.r2_m is None and finish.a12_deg is None
    assert [p.name for p in d.points][-1] == "Minden - FG"


def test_a_task_line_without_a_name_and_ending_in_a_comma():
    text = (HEADER
            + '"Home",,,3900.000N,11900.000W,1000m,4,,,,,,\n'
            + '"TP",,,3910.000N,11900.000W,1000m,1,,,,,,\n'
            + "-----Related Tasks-----\n"
            + ',"Home","Home","TP","Home","Home",\n')
    (task,) = cup.parse(text).tasks
    assert task.name == "" and task.label() == "Home - TP - Home"
    assert len(task.points) == 3


def test_zones_with_every_value_and_with_a_line():
    text = (HEADER
            + '"S",,,3900.000N,11900.000W,1000m,1,,,,,,\n'
            + '"T",,,3930.000N,11900.000W,1000m,1,,,,,,\n'
            + '"F",,,3900.000N,11930.000W,1000m,1,,,,,,\n'
            + "-----Related Tasks-----\n"
            + '"Z","S","S","T","F","F"\n'
            + "Options,NoStart=12:34:56,TaskTime=01:45:12,WpDis=False\n"
            + "ObsZone=0,Style=2,R1=400m,A1=180,Line=1\n"
            + "ObsZone=1,Style=0,R1=35km,A1=30,R2=12000m,A2=12,A12=123.4\n"
            + "ObsZone=2,Style=3,R1=1.5nm,A1=180\n")
    (task,) = cup.parse(text).tasks
    start, tp, finish = task.zones[0], task.zones[1], task.zones[2]
    assert (start.style, start.r1_m, start.line) == (2, 400.0, True)
    assert (tp.style, tp.r1_m, tp.a1_deg, tp.r2_m, tp.a2_deg, tp.a12_deg) == (0, 35000.0, 30.0, 12000.0, 12.0, 123.4)
    assert finish.r1_m == pytest.approx(2778.0) and finish.line is False
    assert task.options["nostart"] == "12:34:56" and task.options["wpdis"] == "False"


def test_a_zone_past_the_task_or_before_any_task_is_skipped():
    text = (HEADER
            + '"S",,,3900.000N,11900.000W,1000m,1,,,,,,\n'
            + '"T",,,3930.000N,11900.000W,1000m,1,,,,,,\n'
            + "-----Related Tasks-----\n"
            + "ObsZone=0,Style=2,R1=400m,A1=180\n"
            + '"Z","S","S","T","S","S"\n'
            + "ObsZone=3,Style=2,R1=400m,A1=180\n"
            + "ObsZone=x,Style=2,R1=400m,A1=180\n")
    f = cup.parse(text)
    (task,) = f.tasks
    assert task.zones == {}
    assert len(f.notes) == 3


def test_a_task_naming_a_missing_waypoint_is_skipped_but_a_missing_takeoff_is_not():
    # (An empty landing cannot be told from the empty field some files end their task lines with,
    # so a missing takeoff or landing is tried with a name the file does not have.)
    text = (HEADER
            + '"S",,,3900.000N,11900.000W,1000m,1,,,,,,\n'
            + '"T",,,3930.000N,11900.000W,1000m,1,,,,,,\n'
            + "-----Related Tasks-----\n"
            + '"Lost","S","S","Nowhere","S","S"\n'
            + '"Kept","Somewhere","S","T","S","Elsewhere"\n'
            + '"Short","S","S","S"\n')
    f = cup.parse(text)
    assert [t.name for t in f.tasks] == ["Kept"]
    assert f.tasks[0].takeoff is None and f.tasks[0].landing is None
    assert any("'Nowhere'" in n for n in f.notes)
    assert any("'Somewhere'" in n and "takeoff" in n for n in f.notes)
    assert any("'Elsewhere'" in n and "landing" in n for n in f.notes)
    assert any("Short" not in n and "needs a takeoff" in n for n in f.notes)


def test_a_point_given_in_place_counts_from_the_takeoff():
    text = (HEADER
            + '"S",,,3900.000N,11900.000W,1000m,1,,,,,,\n'
            + "-----Related Tasks-----\n"
            + '"Inline","S","S","Point_2","S","S"\n'
            + 'Point=2,"Point_2",PNT_2,,4627.136N,01412.856E,0.0m,1,,,,,,,\n'
            + "STARTS=S,T\n")
    f = cup.parse(text)
    (task,) = f.tasks
    assert task.points[1].name == "Point_2" and task.points[1].lat == pytest.approx(46.45227, abs=1e-5)
    assert any("STARTS" in n for n in f.notes)


def test_nothing_in_a_file_raises():
    for text in ("", "\n\n", "-----Related Tasks-----\n", "name,lat,lon\n" + "\x00" * 10,
                 '"a","b\n', "-----Related Tasks-----\n,,,,,\nOptions\nObsZone=\nPoint=\nPoint=1\n"):
        cup.parse(text)


def test_encodings(tmp_path):
    body = HEADER + '"Peñuelas",,,3300.000S,07100.000W,100m,1,,,,"Ñuñoa",,\n'
    for name, data in (("utf8.cup", body.encode("utf-8")),
                       ("bom.cup", b"\xef\xbb\xbf" + body.encode("utf-8")),
                       ("legacy.cup", body.encode("cp1252"))):
        (tmp_path / name).write_bytes(data)
        assert list(cup.load(str(tmp_path / name)).waypoints) == ["Peñuelas"], name


def test_find_files(tmp_path):
    for name in ("b.cup", "A.CUP", "notes.txt"):
        (tmp_path / name).write_text("")
    (tmp_path / "dir.cup").mkdir()
    assert cup.find_files(str(tmp_path)) == ["A.CUP", "b.cup"]
    assert cup.find_files(str(tmp_path / "missing")) == []


def test_examples_go_into_a_folder_without_cup_files_only(tmp_path):
    examples = tmp_path / "examples"
    examples.mkdir()
    (examples / "home.cup").write_text("x", encoding="utf-8")
    (examples / "readme.txt").write_text("not a task", encoding="utf-8")
    tasks = tmp_path / "tasks"
    tasks.mkdir()
    (tasks / "notes.txt").write_text("", encoding="utf-8")
    assert cup.add_examples(str(tasks), str(examples)) == (["home.cup"], None)
    assert sorted(p.name for p in tasks.iterdir()) == ["home.cup", "notes.txt"]
    # The pilot's own file in place of the example: nothing comes back.
    (tasks / "home.cup").unlink()
    (tasks / "mine.cup").write_text("y", encoding="utf-8")
    assert cup.add_examples(str(tasks), str(examples)) == ([], None)
    assert sorted(p.name for p in tasks.iterdir()) == ["mine.cup", "notes.txt"]


def test_an_example_that_cannot_be_copied_is_said_not_raised(tmp_path):
    examples = tmp_path / "examples"
    examples.mkdir()
    (examples / "home.cup").write_text("x", encoding="utf-8")
    copied, error = cup.add_examples(str(tmp_path / "missing"), str(examples))
    assert copied == [] and error


def test_the_example_task_that_comes_with_the_plugin():
    # A 29.5 km triangle from Tobalaba, Santiago, flown by hand on 2026-11-19. The folder is
    # adapter.plugin.EXAMPLE_TASKS, which needs `xp` to import.
    folder = os.path.join(os.path.dirname(cup.__file__), os.pardir, "assets", "tasks")
    assert cup.find_files(folder) == ["santiago-short-triangle.cup"]
    found = cup.load(os.path.join(folder, "santiago-short-triangle.cup"))
    assert found.notes == [] and len(found.tasks) == 1
    task = found.tasks[0]
    assert task.label() == "Santiago short triangle" and task.zones == {}
    assert [p.name for p in task.points] == ["Tobalaba", "Cerro Manquehue", "Cerro San Cristobal", "Tobalaba"]
    legs = [geodesy.distance_m(a.lat, a.lon, b.lat, b.lon) for a, b in zip(task.points, task.points[1:])]
    assert [round(d / 100) / 10 for d in legs] == [11.5, 9.3, 8.7]
