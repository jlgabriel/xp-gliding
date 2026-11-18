"""The flown track (nav/track.py): one point a second, epochs on jumps, and pieces for the page."""

import json

import pytest

from xp_gliding.nav import track as track_mod
from xp_gliding.nav.geodesy import destination
from xp_gliding.nav.track import JUMP_SPEED_MS, SEND_LIMIT, Track


def fly(track, seconds, t0=100.0, lat=-33.45, lon=-70.55, speed=25.0, bearing=90.0, rate_hz=10):
    """Offer the track a straight glide at `rate_hz`, as the adapter's tick does."""
    for k in range(int(seconds * rate_hz)):
        dt = k / rate_hz
        track.add(t0 + dt, *destination(lat, lon, bearing, speed * dt))


def answer(track, epoch, first):
    return json.loads(track.json_from(epoch, first))


def test_one_point_a_second_of_simulator_time():
    track = Track()
    fly(track, 10.0)
    assert track.count == 10 and track.start == 0
    times = [t for t, _, _ in track.points()]
    assert times == pytest.approx([100.0 + k for k in range(10)])


def test_a_paused_simulator_adds_nothing():
    track = Track()
    for _ in range(50):
        track.add(100.0, -33.45, -70.55)  # the tick runs, simulator time stands still
    assert track.count == 1


def test_what_is_not_a_number_is_not_kept():
    track = Track()
    assert not track.add(float("nan"), -33.45, -70.55)
    assert not track.add(1.0, float("inf"), -70.55)
    assert track.count == 0


def test_a_jump_starts_a_new_epoch():
    track = Track()
    fly(track, 5.0)
    assert track.epoch == 0 and track.count == 5
    # Put on the map 30 km away: no glider flies 30 km in a second.
    t, lat, lon = track.points()[-1]
    far = destination(lat, lon, 0.0, 30000.0)
    assert track.add(t + 1.0, *far)
    assert track.epoch == 1 and track.count == 1 and track.points() == [(t + 1.0, *far)]


def test_fast_flight_is_not_a_jump():
    track = Track()
    fly(track, 5.0, speed=0.9 * JUMP_SPEED_MS)
    assert track.epoch == 0 and track.count == 5


def test_a_long_gap_at_flying_speed_is_not_a_jump():
    track = Track()
    track.add(100.0, -33.45, -70.55)
    # The Flight Computer was not chosen for ten minutes, while the glider flew on 12 km.
    assert track.add(700.0, *destination(-33.45, -70.55, 45.0, 12000.0))
    assert track.epoch == 0 and track.count == 2


def test_time_going_back_starts_a_new_epoch():
    track = Track()
    fly(track, 5.0)
    track.add(10.0, -33.45, -70.55)
    assert track.epoch == 1 and track.count == 1


def test_restart_empties_the_track():
    track = Track()
    fly(track, 3.0)
    track.restart()
    assert (track.epoch, track.count, track.points()) == (1, 0, [])
    assert answer(track, 1, 0) == {"epoch": 1, "from": 0, "n": 0, "more": False, "points": []}


def test_the_oldest_points_go_first_and_numbers_keep_counting():
    track = Track(capacity=100)
    fly(track, 1000.0, rate_hz=1)
    assert track.count == 1000
    kept = len(track.points())
    assert 100 <= kept <= 100 + track_mod.TRIM
    assert track.start == 1000 - kept
    assert track.points()[-1][0] == pytest.approx(100.0 + 999)


def test_the_page_gets_what_it_does_not_have():
    track = Track()
    fly(track, 10.0)
    first = answer(track, None, 0)  # a new page knows no epoch: everything
    assert first["epoch"] == 0 and first["from"] == 0 and first["n"] == 10 and len(first["points"]) == 10
    lat0, lon0 = track.points()[0][1:]
    assert first["points"][0] == [pytest.approx(lat0, abs=1e-6), pytest.approx(lon0, abs=1e-6)]
    fly(track, 3.0, t0=110.0, lat=track.points()[-1][1], lon=track.points()[-1][2])
    more = answer(track, 0, 10)
    assert more["from"] == 10 and more["n"] == 13 and len(more["points"]) == 3
    assert answer(track, 0, 13)["points"] == []


def test_a_page_from_another_epoch_or_out_of_range_gets_everything_again():
    track = Track()
    fly(track, 10.0)
    track.restart()
    fly(track, 4.0, t0=500.0)
    for epoch, first in ((0, 10), (1, 99), (1, -3), (1, "2"), (None, None)):
        got = answer(track, epoch, first)
        assert got["epoch"] == 1 and got["from"] == 0 and len(got["points"]) == 4


def test_a_page_behind_the_oldest_kept_point_starts_again_from_it():
    track = Track(capacity=100)
    fly(track, 1000.0, rate_hz=1)
    got = answer(track, 0, 5)
    assert got["from"] == track.start and len(got["points"]) == track.count - track.start


def test_a_long_track_goes_in_pieces():
    track = Track()
    fly(track, SEND_LIMIT + 500.0, rate_hz=1)
    first = answer(track, 0, 0)
    assert len(first["points"]) == SEND_LIMIT and first["more"] is True
    rest = answer(track, 0, SEND_LIMIT)
    assert len(rest["points"]) == 500 and rest["more"] is False


def test_a_six_hour_track_is_answered_quickly():
    import time
    track = Track()
    fly(track, 6 * 3600.0, rate_hz=1)
    t0 = time.perf_counter()
    for first in range(0, track.count, SEND_LIMIT):
        json.loads(track.json_from(0, first))
    assert time.perf_counter() - t0 < 0.5  # all of it; one piece is a few milliseconds


def test_due_says_when_a_place_would_be_kept():
    track = Track()
    assert track.due(5.0)  # an empty track takes the first place
    track.add(5.0, -33.45, -70.55)
    assert not track.due(5.5)
    assert track.due(5.97)  # the 10 Hz tick may land just before the second
    assert track.due(4.0)  # time went back: kept, as a new epoch
