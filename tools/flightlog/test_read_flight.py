"""The pieces of read_flight.py that do not need a flight."""

import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from read_flight import ceiling_agl, find_circlings, own_lift, spearman  # noqa: E402
from xp_gliding.engine.field import FieldConfig, Thermal, ThermalField  # noqa: E402
from xp_gliding.engine.geo import LocalFrame  # noqa: E402
from xp_gliding.engine.markers import core_of  # noqa: E402


def path(segments):
    """(t, psi, east, north, agl) at 1 Hz, from (seconds, turn rate deg/s) at 25 m/s."""
    t, psi, e, n = [0.0], [0.0], [0.0], [0.0]
    for seconds, rate in segments:
        for _ in range(int(seconds)):
            t.append(t[-1] + 1.0)
            psi.append((psi[-1] + rate) % 360.0)
            e.append(e[-1] + 25.0 * math.sin(math.radians(psi[-1])))
            n.append(n[-1] + 25.0 * math.cos(math.radians(psi[-1])))
    return (np.array(t), np.array(psi), np.array(e), np.array(n), np.full(len(t), 800.0))


def test_straight_flight_is_no_circling():
    assert find_circlings(*path([(300, 0.0)])) == []


def test_half_a_turn_is_no_circling():
    assert find_circlings(*path([(60, 0.0), (20, 9.0), (60, 0.0)])) == []


def test_a_climb_is_found_in_either_direction():
    for rate in (9.0, -9.0):
        found = find_circlings(*path([(60, 0.0), (120, rate), (60, 0.0)]))
        assert len(found) == 1
        assert abs(found[0][0] - 60) <= 8 and abs(found[0][1] - 180) <= 8


def test_rolling_out_for_a_moment_does_not_end_it():
    assert len(find_circlings(*path([(60, 0.0), (80, 9.0), (15, 0.0), (80, 9.0), (60, 0.0)]))) == 1


def test_a_glide_between_two_climbs_ends_it():
    assert len(find_circlings(*path([(60, 0.0), (80, 9.0), (120, 0.0), (80, 9.0), (60, 0.0)]))) == 2


def test_a_move_with_the_map_ends_it():
    t, psi, e, n, agl = path([(200, 9.0)])
    e[100:] += 5000.0
    assert len(find_circlings(t, psi, e, n, agl)) == 2


def test_on_the_ground_is_no_circling():
    t, psi, e, n, agl = path([(200, 9.0)])
    assert find_circlings(t, psi, e, n, agl * 0.0) == []


def test_rank_correlation():
    assert spearman([1, 2, 3, 4], [10, 20, 30, 99]) == 1.0
    assert spearman([1, 2, 3, 4], [9, 7, 5, 1]) == -1.0
    assert spearman([1, 2], [1, 2]) is None
    assert spearman([1, 1, 1], [1, 2, 3]) is None


def a_field():
    frame = LocalFrame(-33.0, -70.0)
    field = ThermalField(FieldConfig(seed=1, day=1, range_m=1000.0), frame)
    th = Thermal(-33.0, -70.0, 0.0, 1800.0, 1.2, 1.3, gain=1.0, stretch=2.0)
    th.e, th.n = 0.0, 0.0
    field._grid_add(th)
    return field, th


def test_own_lift_is_what_the_field_adds_for_a_thermal():
    field, th = a_field()
    for r in (0.0, 60.0, 150.0):
        whole = field.lift_at(r, 0.0, 800.0, 900.0, 3.0, 2000.0)
        assert abs(own_lift(th, field, r, 0.0, 800.0, 900.0, 3.0, 2000.0)
                   - (whole - field.environment_sink(800.0, 3.0, 2000.0))) < 1e-9


def test_own_lift_is_nothing_out_of_the_layer_or_of_its_life():
    field, th = a_field()
    assert own_lift(th, field, 0.0, 0.0, 2100.0, 900.0, 3.0, 2000.0) == 0.0
    assert own_lift(th, field, 0.0, 0.0, 800.0, 5000.0, 3.0, 2000.0) == 0.0


def test_the_ceiling_is_where_the_core_equals_the_sink():
    field, th = a_field()
    z = ceiling_agl(th, field, 0.9, 900.0, 300.0, 3.0, 2000.0)
    below, _ = core_of(th, z - 10.0, 900.0, 3.0, 2000.0, field.environment_sink(z - 10.0, 3.0, 2000.0))
    at, _ = core_of(th, z, 900.0, 3.0, 2000.0, field.environment_sink(z, 3.0, 2000.0))
    assert below > 0.9 >= at
    assert 300.0 < z < 2000.0


def test_a_higher_sink_means_a_lower_ceiling():
    field, th = a_field()
    assert (ceiling_agl(th, field, 1.5, 900.0, 300.0, 3.0, 2000.0)
            < ceiling_agl(th, field, 0.8, 900.0, 300.0, 3.0, 2000.0))
