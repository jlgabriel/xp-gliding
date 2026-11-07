"""The pieces of read_flight.py that do not need a flight."""

import math
import os
import sys

import numpy as np
import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from read_flight import ceiling_agl, find_circlings, floor_of, logged_floors, own_lift, spearman  # noqa: E402
from xp_gliding.engine.clouds import cloud_scale  # noqa: E402
from xp_gliding.engine.field import SKIES, FieldConfig, Thermal, ThermalField  # noqa: E402
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


def test_a_log_shorter_than_the_smoothing_is_no_circling():
    assert find_circlings(*path([(5, 9.0)])) == []


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


def test_own_lift_goes_by_the_floor_as_the_field_does():
    field, th = a_field()
    th.floor_m = 500.0
    for r, z, ground in ((0.0, 300.0, 1500.0), (60.0, 800.0, 500.0), (150.0, 1500.0, 100.0), (60.0, 1500.0, -2000.0)):
        whole = field.lift_at(r, 0.0, z, 900.0, 3.0, 2000.0, ground)
        assert abs(own_lift(th, field, r, 0.0, z, 900.0, 3.0, 2000.0, ground)
                   - (whole - field.environment_sink(z, 3.0, 2000.0))) < 1e-9
    assert own_lift(th, field, 0.0, 0.0, 1000.0, 900.0, 3.0, 2000.0, 1600.0) == 0.0  # 2100 m in the thermal


def test_the_ceiling_goes_by_the_floor():
    field, th = a_field()
    flat = ceiling_agl(th, field, 0.9, 900.0, 300.0, 3.0, 2000.0)
    th.floor_m = 500.0
    # The same height over the floor, whatever the ground under the glider.
    assert ceiling_agl(th, field, 0.9, 900.0, 300.0, 3.0, 2000.0, 500.0) == flat
    high = ceiling_agl(th, field, 0.9, 900.0, 300.0, 3.0, 2000.0, 1000.0)
    assert high == pytest.approx(flat - 500.0, abs=10.0)


def test_with_nothing_left_the_ceiling_is_the_top_of_the_layer():
    field, th = a_field()
    assert ceiling_agl(th, field, -9.0, 900.0, 300.0, 3.0, 2000.0) == 2000.0
    th.floor_m = 500.0
    assert ceiling_agl(th, field, -9.0, 900.0, 300.0, 3.0, 2000.0, 1000.0) == 1500.0


def floors_log(near, floors, level=2000.0, length=10):
    return {"t_run_s": np.arange(float(length)), "xpg_nearest_m": np.full(length, near),
            "xpg_nearest_floor_m": np.full(length, floors), "xpg_cloud_level_m": np.full(length, level),
            "xpg_cloud_nearest_m": np.full(length, -1.0), "xpg_cloud_nearest_base_m": np.full(length, -1.0),
            "xpg_cloud_nearest_scale": np.full(length, -1.0), "elev_m": np.full(length, 1900.0),
            "agl_m": np.full(length, 800.0)}


def test_a_thermal_that_was_the_nearest_has_its_floor_from_the_log():
    field, th = a_field()
    rows = np.arange(10)
    e, n, t = np.full(10, 200.0), np.zeros(10), np.full(10, 900.0)
    seen = logged_floors(field, floors_log(210.0, 1234.0), rows, e, n, t)
    assert seen == {th: 1234.0}
    assert floor_of(th, seen, floors_log(210.0, 1234.0), 0, 9, SKIES["wide_carriers"], 2000.0, True) == (1234.0, "logged")


def test_a_neighbour_close_by_does_not_take_the_nearest_ones_floor():
    field, th = a_field()
    other = Thermal(-33.0, -70.0, 0.0, 1800.0, 0.8, 0.9)
    other.e, other.n = 90.0, 0.0
    field._grid_add(other)
    # At 210 m from `th` and 120 m from `other`: the log's nearest, at 120 m, was `other`.
    e, n, t = np.full(10, 210.0), np.zeros(10), np.full(10, 900.0)
    assert logged_floors(field, floors_log(120.0, 500.0), np.arange(10), e, n, t) == {other: 500.0}


def test_a_thermal_that_was_not_the_nearest_goes_by_its_cloud_or_the_level():
    field, th = a_field()
    sky = SKIES["wide_carriers"]
    log = floors_log(210.0, 1234.0)
    floor, source = floor_of(th, {}, log, 0, 9, sky, 2000.0, False)
    assert floor == 2000.0 - sky.cloud_base_zzi * 2000.0 and source == "from the level"
    # A cloud that is the log's nearest, of the same size: its base.
    log["xpg_cloud_nearest_m"][:] = 100.0
    log["xpg_cloud_nearest_base_m"][:] = 2900.0
    log["xpg_cloud_nearest_scale"][:] = cloud_scale(th)
    floor, source = floor_of(th, {}, log, 0, 9, sky, 2000.0, True)
    assert floor == 2900.0 - sky.cloud_base_zzi * 2000.0 and "logged" in source


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
