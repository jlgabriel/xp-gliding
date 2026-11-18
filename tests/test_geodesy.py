"""Distances and bearings on the sphere (nav/geodesy.py), against values worked out by hand and
against each other."""

import math

import pytest

from xp_gliding.nav.geodesy import R_M, bearing_deg, destination, distance_m

DEGREE_M = R_M * math.pi / 180.0  # one degree of a great circle: 111.195 km


def test_a_degree_of_latitude_and_of_longitude_on_the_equator():
    assert distance_m(0.0, 0.0, 1.0, 0.0) == pytest.approx(DEGREE_M, rel=1e-9)
    assert distance_m(0.0, 0.0, 0.0, 1.0) == pytest.approx(DEGREE_M, rel=1e-9)
    assert DEGREE_M == pytest.approx(111194.9, abs=0.1)


def test_a_degree_of_longitude_shrinks_with_the_cosine_of_latitude():
    lat = -33.4
    assert distance_m(lat, -70.0, lat, -70.001) == pytest.approx(0.001 * DEGREE_M * math.cos(math.radians(lat)),
                                                                 rel=1e-6)


def test_short_distances_stay_exact_and_a_point_is_nowhere_from_itself():
    assert distance_m(-33.0, -70.0, -33.0, -70.0) == 0.0
    assert distance_m(-33.0, -70.0, -33.0 + 1e-6, -70.0) == pytest.approx(DEGREE_M * 1e-6, rel=1e-6)


def test_half_the_world_away():
    assert distance_m(10.0, 20.0, -10.0, -160.0) == pytest.approx(math.pi * R_M, rel=1e-7)


def test_a_known_task_leg():
    # Santiago (Tobalaba) to San Felipe, about 74 km a little west of north (worked out with the
    # spherical law of cosines, a different formula from the haversine).
    a, b = (-33.4547, -70.5469), (-32.7498, -70.7258)
    p1, p2, dl = math.radians(a[0]), math.radians(b[0]), math.radians(b[1] - a[1])
    expected = R_M * math.acos(math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * math.cos(dl))
    assert distance_m(*a, *b) == pytest.approx(expected, rel=1e-6)
    assert 345.0 < bearing_deg(*a, *b) < 350.0


def test_bearings_to_the_four_quarters():
    assert bearing_deg(0.0, 0.0, 1.0, 0.0) == pytest.approx(0.0)
    assert bearing_deg(0.0, 0.0, 0.0, 1.0) == pytest.approx(90.0)
    assert bearing_deg(0.0, 0.0, -1.0, 0.0) == pytest.approx(180.0)
    assert bearing_deg(0.0, 0.0, 0.0, -1.0) == pytest.approx(270.0)
    assert bearing_deg(5.0, 5.0, 5.0, 5.0) == 0.0


def test_a_great_circle_east_starts_north_of_east_in_the_north():
    # Along a parallel is not a great circle: heading for a point due east, the great circle
    # leaves a little poleward of east.
    assert 89.0 < bearing_deg(50.0, 0.0, 50.0, 1.0) < 90.0
    assert 90.0 < bearing_deg(-50.0, 0.0, -50.0, 1.0) < 91.0


@pytest.mark.parametrize("bearing", [0.0, 37.0, 90.0, 181.0, 300.0])
@pytest.mark.parametrize("distance", [10.0, 5000.0, 300000.0])
def test_destination_goes_back_to_the_distance_and_bearing_it_was_given(bearing, distance):
    lat, lon = destination(-33.45, -70.55, bearing, distance)
    assert distance_m(-33.45, -70.55, lat, lon) == pytest.approx(distance, rel=1e-6)
    turn = (bearing_deg(-33.45, -70.55, lat, lon) - bearing + 180.0) % 360.0 - 180.0
    assert turn == pytest.approx(0.0, abs=1e-5)


def test_destination_wraps_the_date_line():
    lat, lon = destination(0.0, 179.9, 90.0, 2 * 0.1 * DEGREE_M)
    assert lat == pytest.approx(0.0, abs=1e-9) and lon == pytest.approx(-179.9, abs=1e-9)
