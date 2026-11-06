"""XP12's wind carries the sky: the offset, and what the adapter does with it."""

import math

import pytest

from xp_gliding.adapter import aircraft, config
from xp_gliding.adapter.core import AircraftState, Injection, Injector, wind_layers
from xp_gliding.engine.geo import LocalFrame, radii_of_curvature
from xp_gliding.engine.wind import LEAN_FRACTION, LEAN_MAX_SLOPE, LEAN_SMOOTH_S, MAX_STEP_S, AirDrift, Lean

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


def test_where_the_air_is_at_another_time():
    drift = AirDrift()
    drift.advance(10.0, -5.0, 33.0, 100.0)
    m, n = radii_of_curvature(33.0)
    lat, lon = drift.to_ground_at(33.0, -70.0, 200.0)
    assert (lat - 33.0) * math.radians(1.0) * m == pytest.approx(-500.0, abs=1.0)
    assert (lon + 70.0) * math.radians(1.0) * n * math.cos(math.radians(33.0)) == pytest.approx(1000.0, abs=1.0)


def test_in_a_steady_wind_it_does_not_matter_when_one_asks():
    drift = AirDrift()
    drift.advance(8.0, 3.0, 33.0, 0.0)
    first = drift.to_ground_at(33.1, -70.1, -600.0)
    for t in range(1, 1200):
        drift.advance(8.0, 3.0, 33.0, float(t))
    later = drift.to_ground_at(33.1, -70.1, -600.0)
    # Within 20 m: the sky is carried at the latitude of the glider, not of this thermal.
    assert later[0] == pytest.approx(first[0], abs=2e-4)
    assert later[1] == pytest.approx(first[1], abs=2e-4)


def test_with_no_wind_a_thermal_is_where_it_was_drawn():
    drift = AirDrift()
    drift.hold(100.0)
    assert drift.to_ground_at(33.0, -70.0, 900.0) == (33.0, -70.0)


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


# --- the lean ------------------------------------------------------------------------

BASE = 1500.0


def uniform(wind_e, wind_n=0.0, wstar=3.0, **kwargs):
    lean = Lean(**kwargs)
    lean.set_wind((0.0,), (wind_e,), (wind_n,), BASE, wstar, NOON)
    return lean


def test_with_no_wind_there_is_no_lean_exactly():
    lean = uniform(0.0)
    for z in (0.0, 500.0, 1500.0, 3000.0):
        assert lean.at(z) == (0.0, 0.0)


def test_before_any_wind_there_is_no_lean():
    assert Lean().at(500.0) == (0.0, 0.0)


def test_the_lift_is_upwind_of_the_cloud_and_more_so_when_low():
    lean = uniform(7.7)  # toward the east
    slope = LEAN_FRACTION * 7.7 / 3.0
    assert lean.at(BASE)[0] == pytest.approx(0.0, abs=1e-9)
    assert lean.at(500.0)[0] == pytest.approx(-slope * 1000.0, abs=0.1)
    assert lean.at(1000.0)[0] == pytest.approx(-slope * 500.0, abs=0.1)
    assert lean.at(500.0)[1] == 0.0


def test_above_the_base_it_goes_on_with_no_kink():
    lean = uniform(7.7)
    below = lean.at(BASE - 50.0)[0]
    above = lean.at(BASE + 50.0)[0]
    assert above == pytest.approx(-below, abs=1e-6)


@pytest.mark.parametrize("wind_e, wind_n", [(7.7, 0.0), (0.0, -7.7), (-5.0, 5.0)])
def test_it_leans_against_the_wind_whatever_its_direction(wind_e, wind_n):
    e, n = uniform(wind_e, wind_n).at(500.0)
    assert e * wind_e + n * wind_n < 0.0
    assert e * wind_n - n * wind_e == pytest.approx(0.0, abs=1e-6)


def test_a_weaker_day_leans_more():
    assert abs(uniform(7.7, wstar=2.0).at(500.0)[0]) > abs(uniform(7.7, wstar=4.0).at(500.0)[0])


def test_a_stronger_wind_leans_more_up_to_a_limit():
    assert abs(uniform(12.9).at(500.0)[0]) > abs(uniform(7.7).at(500.0)[0])
    strong = uniform(50.0, 0.0).at(500.0)
    assert strong[0] == pytest.approx(-LEAN_MAX_SLOPE * 1000.0, abs=0.1)
    slanted = uniform(40.0, 30.0).at(500.0)
    assert math.hypot(*slanted) == pytest.approx(LEAN_MAX_SLOPE * 1000.0, abs=0.1)


def test_the_layers_shape_it():
    lean = Lean()
    # No wind up to 1000 m, then 10 m/s: nothing leans below 1000 m but what is above it.
    lean.set_wind((1000.0, 1000.1), (0.0, 10.0), (0.0, 0.0), BASE, 3.0, NOON)
    low, high = lean.at(200.0)[0], lean.at(1000.0)[0]
    assert low == pytest.approx(high, abs=0.5)
    assert high == pytest.approx(-LEAN_FRACTION * 10.0 / 3.0 * 500.0, abs=1.0)


def test_a_wind_that_turns_with_height_turns_the_lean():
    lean = Lean()
    # East at the bottom, north at the top: the upper part leans south, and the lower also west.
    lean.set_wind((500.0, 1500.0), (10.0, 0.0), (0.0, 10.0), BASE, 3.0, NOON)
    e, n = lean.at(1400.0)
    assert abs(e) < abs(n) and n < 0.0
    e, n = lean.at(200.0)
    assert e < -100.0 and n < -100.0


def test_a_change_of_wind_moves_the_lift_gently():
    lean = uniform(7.7)
    before = lean.at(500.0)[0]
    lean.set_wind((0.0,), (12.9,), (0.0,), BASE, 3.0, NOON + 5.0)
    after = lean.at(500.0)[0]
    goal = uniform(12.9).at(500.0)[0]
    assert goal < after < before
    assert after - before == pytest.approx((goal - before) * (1.0 - math.exp(-5.0 / LEAN_SMOOTH_S)), abs=1e-6)
    for k in range(2, 200):
        lean.set_wind((0.0,), (12.9,), (0.0,), BASE, 3.0, NOON + 5.0 * k)
    assert lean.at(500.0)[0] == pytest.approx(goal, abs=0.01)


def test_a_paused_clock_changes_nothing_and_a_jump_takes_the_new_wind_at_once():
    lean = uniform(7.7)
    before = lean.at(500.0)
    lean.set_wind((0.0,), (12.9,), (0.0,), BASE, 3.0, NOON)
    assert lean.at(500.0) == before
    lean.set_wind((0.0,), (12.9,), (0.0,), BASE, 3.0, NOON + 3600.0)
    assert lean.at(500.0)[0] == pytest.approx(uniform(12.9).at(500.0)[0], abs=1e-9)


def test_it_is_a_pure_function_of_its_inputs():
    a, b = uniform(7.7, 3.0), uniform(7.7, 3.0)
    assert a.at(777.0) == b.at(777.0)


def test_the_layers_of_x_plane_come_in_height_above_ground_and_where_the_wind_goes():
    heights, east, north = wind_layers((2000.0, 500.0, 500.0, 1000.0), (10.0, 20.0, 30.0, 0.0),
                                       (0.0, 270.0, 90.0, 180.0), 400.0)
    assert heights == [100.0, 600.0, 1600.0]  # sorted, each height once
    assert east[0] == pytest.approx(20.0 * 0.514444, abs=1e-3)  # from the west: toward the east
    assert north[0] == pytest.approx(0.0, abs=1e-9)
    assert east[2] == pytest.approx(0.0, abs=1e-9)
    assert north[2] == pytest.approx(-10.0 * 0.514444, abs=1e-3)  # from the north: toward the south


LAYERS = ([300.0 + 500.0 * k for k in range(13)], [15.0] * 13, [270.0] * 13)


def test_off_by_default_the_layers_of_wind_change_nothing():
    lat0, lon0 = near_a_thermal()
    plain, off = injector(), injector()
    s = state(lat0, lon0, NOON)
    off.lean_update(s, *LAYERS, 1915.0)
    assert frame(plain, s, True) == frame(off, s, True)
    assert off.lean_e_m == 0.0


def test_the_glider_feels_the_lift_upwind_of_where_it_would_be():
    lat0, lon0 = near_a_thermal()
    plain = injector(wind_enabled=True)
    leaning = injector(lean_enabled=True)
    s = state(lat0, lon0, NOON)
    leaning.lean_update(s, *LAYERS, 1915.0)  # 800 m AGL
    de, dn = leaning.lean.at(s.agl_m)
    assert de < -100.0 and dn == pytest.approx(0.0, abs=1e-6)
    upwind = state(*LocalFrame(lat0, lon0).to_latlon(de, dn), NOON)
    leaning.lean_update(upwind, *LAYERS, 1915.0)
    assert frame(leaning, upwind, True) == pytest.approx(frame(plain, s, True), abs=0.01)
    assert leaning.lean_e_m == pytest.approx(de, abs=1e-6)


def test_lean_on_in_calm_air_changes_nothing_exactly():
    lat0, lon0 = near_a_thermal()
    plain, leaning = injector(), injector(lean_enabled=True)
    s = state(lat0, lon0, NOON)
    leaning.lean_update(s, LAYERS[0], [0.0] * 13, LAYERS[2], 1915.0)
    assert frame(leaning, s, True) == frame(plain, s, True)


def test_with_the_wind_switched_off_nothing_leans():
    lat0, lon0 = near_a_thermal()
    plain, off = injector(wind_enabled=False), injector(wind_enabled=False, lean_enabled=True)
    s = state(lat0, lon0, NOON)
    off.lean_update(s, *LAYERS, 1915.0)
    assert frame(off, s, True) == frame(plain, s, True)


def test_a_layer_not_in_use_is_left_out_wherever_its_altitude_is():
    # As X-Plane 12.4.3 gives them: four in use, and the rest at -1 kt among them.
    heights, east, north = wind_layers((1268.0, 2030.0, 2945.0, 4774.0, 3011.0, 4207.0, 5572.0),
                                       (15.0, 15.0, 15.0, 15.0, -1.0, -1.0, -1.0),
                                       (270.0, 270.0, 270.0, 270.0, 0.0, 0.0, 0.0), 1116.0)
    assert heights == pytest.approx([152.0, 914.0, 1829.0, 3658.0])
    assert east == pytest.approx([15.0 * 0.514444] * 4)
    assert north == pytest.approx([0.0] * 4, abs=1e-9)


def test_with_no_layer_in_use_nothing_leans():
    lat0, lon0 = near_a_thermal()
    leaning = injector(lean_enabled=True)
    s = state(lat0, lon0, NOON)
    leaning.lean_update(s, [1000.0] * 3, [-1.0] * 3, [0.0] * 3, 1915.0)
    assert leaning.lean.at(500.0) == (0.0, 0.0)
