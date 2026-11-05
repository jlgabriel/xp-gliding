"""XP12's wind carries the sky: the offset, and what the adapter does with it."""

import math

import pytest

from xp_gliding.adapter import aircraft, config
from xp_gliding.adapter.core import AircraftState, Injection, Injector
from xp_gliding.engine.geo import LocalFrame, radii_of_curvature
from xp_gliding.engine.wind import MAX_STEP_S, AirDrift

KHOB = (32.6875, -103.2170)
NOON = 12 * 3600.0


def test_no_wind_changes_nothing_exactly():
    d = AirDrift()
    for k in range(100):
        d.advance(0.0, 0.0, KHOB[0], NOON + k)
    assert d.dlat_deg == 0.0 and d.dlon_deg == 0.0
    assert d.to_air(*KHOB) == pytest.approx(KHOB, abs=1e-12)
    assert d.to_ground(*KHOB) == pytest.approx(KHOB, abs=1e-12)


def test_the_sky_travels_at_the_winds_speed_and_direction():
    d = AirDrift()
    for k in range(101):  # 100 s at 10 m/s toward the east, 5 m/s toward the south
        d.advance(10.0, -5.0, KHOB[0], NOON + k)
    frame = LocalFrame(*KHOB)
    e, n = frame.to_enu(*d.to_ground(*KHOB))
    assert e == pytest.approx(1000.0, abs=0.01)
    assert n == pytest.approx(-500.0, abs=0.01)


def test_air_and_ground_are_inverse():
    d = AirDrift()
    d.advance(0.0, 0.0, KHOB[0], NOON)
    d.advance(20.0, 7.0, KHOB[0], NOON + 3.0)
    assert d.to_ground(*d.to_air(*KHOB)) == pytest.approx(KHOB, abs=1e-12)


def test_the_longitude_wraps_at_the_date_line():
    d = AirDrift()
    d.advance(0.0, 0.0, 0.0, NOON)
    d.advance(-100.0, 0.0, 0.0, NOON + 5.0)
    lat, lon = d.to_air(0.0, 179.9999)
    assert -180.0 <= lon < -179.0  # over the line, in the air's frame
    assert d.to_ground(lat, lon)[1] == pytest.approx(179.9999, abs=1e-9)


def carried(lat, lon, wind_e, wind_n, dt):
    """Where X-Plane's wind takes something in dt."""
    m, n = radii_of_curvature(lat)
    k = math.degrees(dt)
    return lat + k * wind_n / m, lon + k * wind_e / (n * math.cos(math.radians(lat)))


def test_a_glider_carried_by_a_changing_wind_stays_put_in_the_air():
    d = AirDrift()
    lat, lon = KHOB
    start = d.to_air(lat, lon)
    d.advance(0.0, 0.0, lat, NOON)
    for k in range(1, 600):
        we, wn = 10.0 + 5.0 * math.sin(k / 30.0), -8.0 * math.cos(k / 50.0)
        lat, lon = carried(lat, lon, we, wn, 1.0)
        d.advance(we, wn, lat, NOON + k)
    # It has travelled kilometres over the ground, and hardly any in the air.
    frame = LocalFrame(*KHOB)
    assert math.hypot(*frame.to_enu(lat, lon)) > 3000.0
    assert math.hypot(*frame.to_enu(*d.to_air(lat, lon))) == pytest.approx(0.0, abs=2.0)
    assert d.to_air(lat, lon) == pytest.approx(start, abs=2e-5)


def test_a_change_of_wind_moves_nothing_at_once():
    d = AirDrift()
    d.advance(5.0, 0.0, KHOB[0], NOON)
    d.advance(5.0, 0.0, KHOB[0], NOON + 1.0)
    before = d.dlon_deg
    d.advance(50.0, 50.0, KHOB[0], NOON + 1.0)  # same clock: paused, or a second read
    assert d.dlon_deg == before and d.dlat_deg == 0.0


@pytest.mark.parametrize("step", [MAX_STEP_S + 1.0, 3600.0, -1.0, -3600.0])
def test_a_jump_of_the_clock_carries_nothing(step):
    d = AirDrift()
    d.advance(10.0, 10.0, KHOB[0], NOON)
    d.advance(10.0, 10.0, KHOB[0], NOON + step)
    assert d.dlat_deg == 0.0 and d.dlon_deg == 0.0
    d.advance(10.0, 0.0, KHOB[0], NOON + step + 1.0)  # and it goes on from there
    assert d.dlon_deg > 0.0


def test_holding_stops_the_sky_with_no_jump_when_it_goes_on():
    d = AirDrift()
    d.advance(10.0, 0.0, KHOB[0], NOON)
    d.advance(10.0, 0.0, KHOB[0], NOON + 1.0)
    before = d.dlon_deg
    for k in range(2, 100):
        d.hold(NOON + k)
    assert d.dlon_deg == before and d.wind_e_ms == 0.0
    d.advance(10.0, 0.0, KHOB[0], NOON + 100.0)  # one second on, not ninety-nine
    assert d.dlon_deg == pytest.approx(2.0 * before)


def test_a_new_flight_starts_from_where_the_field_drew_the_sky():
    d = AirDrift()
    d.advance(10.0, 10.0, KHOB[0], NOON)
    d.advance(10.0, 10.0, KHOB[0], NOON + 1.0)
    d.reset()
    assert d.dlat_deg == 0.0 and d.dlon_deg == 0.0
    d.advance(10.0, 10.0, KHOB[0], NOON + 2.0)  # no step from the old flight's clock
    assert d.dlat_deg == 0.0


# --- the adapter ---------------------------------------------------------------------

def state(lat, lon, t, wind_e=0.0, wind_n=0.0, day=305):
    s = AircraftState()
    s.lat, s.lon, s.agl_m, s.tas_ms = lat, lon, 800.0, 28.0
    s.psi_deg, s.mass_kg, s.rho, s.sky_t_s, s.day = 90.0, 541.0, 1.0, t, day
    s.wind_x_ms, s.wind_z_ms = wind_e, -wind_n  # X-Plane's local axes: z is south
    return s


def injector(**settings):
    return Injector(config.Settings(settings), aircraft.DEFAULT_GEOMETRY)


def near_a_thermal():
    """A place in a thermal's lift at noon, and that lift."""
    inj_ = injector()
    s = state(*KHOB, NOON)
    inj_.slow_update(s)
    assert inj_.nearest.distance_m >= 0.0
    th, _ = inj_.field.nearest(*inj_.frame.to_enu(*KHOB), NOON, 5000.0)
    return inj_.frame.to_latlon(th.e + 20.0, th.n)


def frame(inj_, s, slow):
    inj_.carry(s)
    if slow:
        inj_.slow_update(s)
    return inj_.step(s, Injection()).w_centre


def test_a_glider_carried_by_the_wind_feels_what_it_feels_in_calm_air():
    lat0, lon0 = near_a_thermal()
    calm, windy = injector(), injector()
    lat, lon = lat0, lon0
    lifts = []
    for k in range(240):
        t = NOON + k
        w_calm = frame(calm, state(lat0, lon0, t), k % 30 == 0)
        w_windy = frame(windy, state(lat, lon, t, 12.0, -6.0), k % 30 == 0)
        assert w_windy == pytest.approx(w_calm, abs=1e-3)
        lifts.append(w_calm)
        lat, lon = carried(lat, lon, 12.0, -6.0, 1.0)
    assert max(lifts) > 0.5  # it was in a thermal, or the test proves nothing


def test_a_glider_held_still_over_the_ground_is_left_behind():
    lat0, lon0 = near_a_thermal()
    inj_ = injector()
    lifts = [frame(inj_, state(lat0, lon0, NOON + k, 12.0, 0.0), k % 10 == 0) for k in range(120)]
    assert lifts[0] > 0.5
    assert lifts[-1] < 0.5 * lifts[0]  # the thermal is 1.4 km downwind by now


def test_switched_off_the_thermals_stay_where_they_are():
    lat0, lon0 = near_a_thermal()
    calm, off = injector(), injector(wind_enabled=False)
    for k in range(120):
        t = NOON + k
        w_calm = frame(calm, state(lat0, lon0, t), k % 10 == 0)
        w_off = frame(off, state(lat0, lon0, t, 12.0, 0.0), k % 10 == 0)
        assert w_off == w_calm
    assert off.drift.dlon_deg == 0.0


def test_the_local_axes_of_the_wind_are_east_and_south():
    inj_ = injector()
    s = state(*KHOB, NOON)
    s.wind_x_ms, s.wind_z_ms = 3.0, 4.0
    inj_.carry(s)
    s.sky_t_s = NOON + 1.0
    inj_.carry(s)
    assert inj_.drift.wind_e_ms == 3.0 and inj_.drift.wind_n_ms == -4.0
    assert inj_.drift.dlon_deg > 0.0 and inj_.drift.dlat_deg < 0.0
