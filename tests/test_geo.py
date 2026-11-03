import math

import pytest

from xp_gliding.engine.geo import LocalFrame, enu_from_xp_local, heading_vectors, radii_of_curvature


def test_one_degree_matches_wgs84_reference_lengths():
    # Standard WGS84 figures: 1 deg of longitude at the equator, 1 deg of
    # latitude at the equator and at 45 deg (to the metre).
    m0, n0 = radii_of_curvature(0.0)
    assert math.radians(1) * n0 == pytest.approx(111319.49, abs=0.01)
    assert math.radians(1) * m0 == pytest.approx(110574.3, abs=1.0)
    m45, _ = radii_of_curvature(45.0)
    assert math.radians(1) * m45 == pytest.approx(111132.1, abs=1.0)


def test_round_trip_and_cos_lat():
    frame = LocalFrame(-33.0, -70.5)
    e, n = frame.to_enu(-33.01, -70.49)
    assert e > 0 and n < 0
    lat, lon = frame.to_latlon(e, n)
    assert lat == pytest.approx(-33.01, abs=1e-12)
    assert lon == pytest.approx(-70.49, abs=1e-12)
    # East scale shrinks with cos(lat): ~16% shorter than north at 33 deg.
    assert frame.m_per_deg_lon / frame.m_per_deg_lat == pytest.approx(
        math.cos(math.radians(33.0)), rel=0.01)


def test_antimeridian_wraps():
    frame = LocalFrame(10.0, 179.99)
    e, _ = frame.to_enu(10.0, -179.99)
    assert e == pytest.approx(0.02 * frame.m_per_deg_lon)
    _, lon = frame.to_latlon(e, 0.0)
    assert lon == pytest.approx(-179.99)


def test_heading_vectors():
    fe, fn, re_, rn = heading_vectors(90.0)  # flying east: right is south
    assert (fe, fn) == pytest.approx((1.0, 0.0), abs=1e-12)
    assert (re_, rn) == pytest.approx((0.0, -1.0), abs=1e-12)


def test_xp_local_axes():
    assert enu_from_xp_local(1.0, 2.0, 3.0) == (1.0, -3.0, 2.0)
