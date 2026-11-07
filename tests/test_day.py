"""The depth of the day from the atmosphere's layers."""
import pytest

from xp_gliding.engine.day import at_height, cloud_base_above_ground_m, known_layers

HEIGHTS = [0.0, 540.0, 988.0]
TEMPS = [15.0, 11.5, 8.6]


def test_interpolates_between_layers():
    assert at_height(270.0, HEIGHTS, TEMPS) == pytest.approx(13.25)


def test_a_layer_gives_its_own_value():
    assert at_height(540.0, HEIGHTS, TEMPS) == pytest.approx(11.5)


def test_ends_hold():
    assert at_height(-10.0, HEIGHTS, TEMPS) == 15.0
    assert at_height(5000.0, HEIGHTS, TEMPS) == 8.6


def test_rising_table_with_a_repeat_does_not_divide_by_zero():
    assert at_height(100.0, [100.0, 100.0, 200.0], [1.0, 2.0, 3.0]) == 1.0


def test_espy_rule():
    assert cloud_base_above_ground_m(25.0, 13.0) == pytest.approx(1500.0)


def test_saturated_air_condenses_at_the_ground():
    assert cloud_base_above_ground_m(10.0, 10.0) == 0.0
    assert cloud_base_above_ground_m(10.0, 11.0) == 0.0


def test_layers_with_no_data_are_left_out():
    assert known_layers([0.0, 540.0, 988.0], [4.8, -100.0, -100.0]) == ([0.0], [4.8])
    assert known_layers([0.0], [-100.0]) == ([], [])
