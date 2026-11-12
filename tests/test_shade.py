"""Less lift under X-Plane's clouds, and none in rain."""

import pytest

from xp_gliding.engine import shade as sh

CIRRUS, STRATUS, CUMULUS, CB = 0.0, 1.0, 2.0, 3.0


def test_a_clear_sky_takes_nothing():
    assert sh.strength_share((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), 0.0) == 1.0
    assert sh.strength_share((STRATUS, STRATUS, STRATUS), (0.0, 0.0, 0.0), 0.0) == 1.0


def test_more_cover_less_lift_and_a_closed_overcast_about_half():
    shares = [sh.strength_share((STRATUS,), (c,), 0.0) for c in (0.25, 0.5, 0.75, 1.0)]
    assert shares == sorted(shares, reverse=True)
    assert shares[1] == pytest.approx(0.918, abs=0.005)
    assert shares[2] == pytest.approx(0.790, abs=0.005)
    assert shares[3] == pytest.approx(0.464, abs=0.005)


def test_cirrus_shades_less_than_stratus_and_types_blend():
    assert sh.strength_share((CIRRUS,), (1.0,), 0.0) > sh.strength_share((CUMULUS,), (1.0,), 0.0) \
        > sh.strength_share((STRATUS,), (1.0,), 0.0)
    assert sh.type_weight(0.5) == pytest.approx(0.65)
    assert sh.type_weight(-1.0) == sh.TYPE_WEIGHT[0] and sh.type_weight(9.0) == sh.TYPE_WEIGHT[-1]


def test_layers_add_up_as_screens():
    one = sh.sky_cover((STRATUS,), (0.5,))
    two = sh.sky_cover((STRATUS, STRATUS), (0.5, 0.5))
    assert one == pytest.approx(0.5) and two == pytest.approx(0.75)
    assert sh.sky_cover((STRATUS, STRATUS), (1.0, 1.0)) == pytest.approx(1.0)


def test_rain_stops_the_thermals():
    assert sh.strength_share((CIRRUS,), (0.1,), 0.2) == 0.0
    assert sh.strength_share((CIRRUS,), (0.1,), 0.01) > 0.9


def test_the_ground_takes_minutes_to_follow():
    shade = sh.Shade()
    assert shade.step(1.0, 0.0) == 1.0
    assert shade.step(0.0, sh.TAU_S) == pytest.approx(1.0 - 0.632, abs=0.001)
    assert shade.step(0.0, 5.0 * sh.TAU_S) < 0.01
    shade.reset()  # a new flight: at the weather at once
    assert shade.step(0.8, 10.0 * sh.TAU_S) == 0.8
    assert shade.step(0.5, 0.0) == 0.5  # the clock went back: start over
