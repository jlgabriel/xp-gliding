"""The Glide Computer's glide readings without a polar (nav/glide.py): E, DH, ReqE and VMG."""

import pytest

from xp_gliding.nav.geodesy import destination
from xp_gliding.nav.glide import MAX_LD, WINDOW_S, GlideRatio, height_over, required_ld, vmg

HOME = (-33.40, -70.60)


def glide(ratio, seconds, speed_ms=25.0, bearing=30.0, start_msl=2000.0, t0=0.0):
    """A straight glide at a ratio, a sample a second."""
    e = GlideRatio()
    for i in range(seconds + 1):
        lat, lon = destination(HOME[0], HOME[1], bearing, speed_ms * i)
        e.add(t0 + i, lat, lon, start_msl - speed_ms * i / ratio)
    return e


def test_e_is_the_ground_flown_over_the_height_lost():
    assert glide(30.0, 60).ld == pytest.approx(30.0, rel=1e-3)
    assert glide(12.0, 60).ld == pytest.approx(12.0, rel=1e-3)


def test_e_looks_back_over_its_window_only():
    e = GlideRatio()
    for i in range(121):
        lat, lon = destination(HOME[0], HOME[1], 0.0, 25.0 * i)
        # 10:1 for the first minute, then 40:1
        msl = 2000.0 - 2.5 * min(i, 60) - 0.625 * max(i - 60, 0)
        e.add(float(i), lat, lon, msl)
    assert e.ld == pytest.approx(40.0, rel=1e-3)


def test_no_e_while_climbing_or_level_or_too_soon():
    e = GlideRatio()
    for i in range(61):
        lat, lon = destination(HOME[0], HOME[1], 0.0, 25.0 * i)
        e.add(float(i), lat, lon, 1000.0 + 0.5 * i)
    assert e.ld is None
    assert glide(30.0, int(WINDOW_S * 0.4)).ld is None  # less than half the window: not yet
    assert glide(1000.0, 60).ld is None  # above MAX_LD


def test_e_starts_over_when_time_goes_back():
    e = glide(30.0, 60, t0=100.0)
    lat, lon = destination(HOME[0], HOME[1], 0.0, 100.0)
    e.add(5.0, lat, lon, 1500.0)
    assert e.ld is None


def test_height_over_and_required_ld():
    assert height_over(1500.0, 600.0) == 900.0
    assert height_over(1500.0, None) is None
    assert required_ld(9000.0, 900.0) == pytest.approx(10.0)
    assert required_ld(9000.0, 0.0) is None and required_ld(9000.0, -50.0) is None
    assert required_ld(9000.0, 9000.0 / (MAX_LD + 1)) is None
    assert required_ld(None, 900.0) is None


def test_vmg_is_the_ground_speed_along_the_bearing():
    assert vmg(30.0, 90.0, 90.0) == pytest.approx(30.0)
    assert vmg(30.0, 150.0, 90.0) == pytest.approx(15.0)
    assert vmg(30.0, 270.0, 90.0) == pytest.approx(-30.0)
    assert vmg(30.0, 350.0, 10.0) == pytest.approx(30.0 * 0.9396926)
    assert vmg(30.0, None, 10.0) is None
