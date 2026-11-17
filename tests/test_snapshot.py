"""The Flight Computer's snapshot (nav/snapshot.py): JSON the page can always parse, SI units,
and X-Plane's axes turned into tracks and winds the right way round."""

import json
import math

import pytest

from xp_gliding.nav.snapshot import FIELDS, FLAGS, snapshot_json, track, wind_from


def test_an_empty_snapshot_has_every_key_and_parses():
    out = json.loads(snapshot_json({}))
    assert set(FIELDS) <= set(out) and set(FLAGS) <= set(out)
    assert all(out[key] is None for key in FIELDS)
    assert all(out[key] is False for key in FLAGS)
    assert out["units"] is None and out["poll_hz"] is None


def test_numbers_are_rounded_and_what_is_not_finite_goes_out_as_null():
    out = json.loads(snapshot_json({"lat": -33.123456789, "te_ms": 1.23456, "avg_ms": float("nan"),
                                    "msl_m": float("inf"), "netto_ms": None, "units": "aviation",
                                    "valid": 1, "poll_hz": 5.0, "something_else": 3}))
    assert out["lat"] == -33.123457 and out["te_ms"] == 1.23
    assert out["avg_ms"] is None and out["msl_m"] is None and out["netto_ms"] is None
    assert out["valid"] is True and out["units"] == "aviation" and out["poll_hz"] == 5
    assert "something_else" not in out


def test_a_text_that_is_not_a_string_is_left_out():
    assert json.loads(snapshot_json({"units": 3}))["units"] is None


# X-Plane's local axes: x east, z south.
@pytest.mark.parametrize("vx, vz, expected", [
    (0.0, -20.0, 0.0),  # north
    (20.0, 0.0, 90.0),  # east
    (0.0, 20.0, 180.0),  # south
    (-20.0, 0.0, 270.0),  # west
])
def test_the_track_is_where_the_glider_goes(vx, vz, expected):
    deg, speed = track(vx, vz)
    assert deg == pytest.approx(expected) and speed == pytest.approx(20.0)


def test_no_track_when_standing_still():
    assert track(0.1, -0.2) == (None, pytest.approx(math.hypot(0.1, 0.2)))


@pytest.mark.parametrize("wx, wz, expected", [
    (5.0, 0.0, 270.0),  # the air goes east: a wind from the west
    (0.0, 5.0, 0.0),  # the air goes south: from the north
    (-5.0, 0.0, 90.0),
    (0.0, -5.0, 180.0),
])
def test_the_wind_is_where_it_blows_from(wx, wz, expected):
    deg, speed = wind_from(wx, wz)
    assert deg == pytest.approx(expected) and speed == pytest.approx(5.0)


def test_a_light_air_is_calm():
    deg, speed = wind_from(0.3, 0.2)
    assert deg is None and speed < 0.5
