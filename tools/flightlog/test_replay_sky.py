"""The pieces of replay_sky.py that do not need a flight."""

import math
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from replay_sky import fit_centre, integrated_wind  # noqa: E402


def test_the_centre_comes_from_distances():
    angles = np.linspace(0.0, 2.0 * math.pi, 40)
    e, n = 120.0 + 150.0 * np.cos(angles), -80.0 + 150.0 * np.sin(angles)
    r = np.hypot(e - 300.0, n - 40.0)
    centre, rms = fit_centre(e, n, r)
    assert abs(centre[0] - 300.0) < 0.01 and abs(centre[1] - 40.0) < 0.01
    assert rms < 0.01


def test_a_wind_from_the_north_carries_the_air_south():
    log = {"t_zulu_s": np.arange(0.0, 11.0), "wind_ms": np.full(11, 5.0), "wind_dir_deg": np.zeros(11)}
    east, north = integrated_wind(log)
    assert abs(east[-1]) < 1e-9
    assert north[-1] == -50.0


def test_the_air_does_not_travel_across_a_jump_of_the_clock():
    zulu = np.array([0.0, 1.0, 2.0, 100.0, 101.0])
    log = {"t_zulu_s": zulu, "wind_ms": np.full(5, 5.0), "wind_dir_deg": np.full(5, 270.0)}
    east, _ = integrated_wind(log)
    assert east[-1] == 15.0  # three steps of one second: the jump counts for nothing
