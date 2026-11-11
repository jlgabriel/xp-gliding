import math

from xp_gliding.engine import airstart as a
from xp_gliding.engine.clouds import CloudParams
from xp_gliding.engine.field import Thermal

PARAMS = CloudParams()


def thermal(e, n, birth=0.0, life=1000.0):
    th = Thermal(32.0, -103.0, birth, birth + life, 1.5, 1.5)
    th.e, th.n = e, n
    return th


def test_picks_the_nearest_mature_cloud():
    near, far = thermal(1000.0, 0.0), thermal(5000.0, 0.0)
    th, r = a.pick_cloud([far, near], 0.0, 0.0, 300.0, PARAMS)
    assert th is near and r == 1000.0


def test_skips_a_young_thermal_and_one_about_to_fade():
    young = thermal(500.0, 0.0, birth=250.0)  # 50 s old, of 1000: still growing
    fading = thermal(700.0, 0.0, birth=-450.0)  # fed until 250, 50 s more
    good = thermal(3000.0, 0.0)
    th, _ = a.pick_cloud([young, fading, good], 0.0, 0.0, 300.0, PARAMS)
    assert th is good


def test_none_when_nothing_fits():
    assert a.pick_cloud([], 0.0, 0.0, 0.0, PARAMS) == (None, math.inf)


def test_placed_on_the_gliders_side_heading_for_the_thermal():
    pe, pn, heading = a.place_near(0.0, 0.0, 5000.0, 0.0, 90.0)
    assert (round(pe), round(pn)) == (1500, 0)
    assert round(heading) == 270


def test_placed_behind_the_glider_when_over_the_centre():
    pe, pn, heading = a.place_near(100.0, 100.0, 100.0, 100.0, 0.0)  # heading north
    assert (round(pe), round(pn)) == (100, -1400)
    assert round(heading) % 360 == 0


def test_start_height():
    assert a.start_height_m(1000.0, 2500.0) == 1900.0
    assert a.start_height_m(1000.0, 1100.0) == 1300.0  # never under 300 m above the ground
