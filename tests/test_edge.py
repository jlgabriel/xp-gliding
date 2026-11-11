"""The sharper thermal edges: the sink ring, the sink between thermals and the kick."""

import math

import pytest

from xp_gliding.engine import injection as inj
from xp_gliding.engine import updraft as u

ZI, WSTAR = 2000.0, 3.0


def test_the_ring_sinks_outside_the_thermal_and_leaves_the_inside_alone():
    z = 0.3 * ZI  # low, where Allen has no ring at all
    _, r2 = u.core_radii(z, ZI)
    for rr2 in (0.0, 0.3, 0.6, 0.9):
        assert u.updraft_velocity(rr2 * r2, z, ZI, WSTAR, ring=0.5) == u.updraft_velocity(rr2 * r2, z, ZI, WSTAR)
    plain = u.updraft_velocity(1.5 * r2, z, ZI, WSTAR)
    ringed = u.updraft_velocity(1.5 * r2, z, ZI, WSTAR, ring=0.5)
    assert ringed - plain == pytest.approx(-0.5 * u.mean_updraft(z / ZI, WSTAR), rel=1e-6)
    # It ends where the thermal's influence does.
    assert u.updraft_velocity(2.0 * r2, z, ZI, WSTAR, ring=0.5) == u.updraft_velocity(2.0 * r2, z, ZI, WSTAR)


def test_the_kick_is_the_lift_of_the_angle_of_attack_change():
    # ASK 21: 541 kg, 17.75 m2, aspect ratio 16.7, at 97 km/h near sea level.
    cla = inj.lift_slope(16.7)
    assert inj.kick_force(1.1, 27.0, 17.75, cla, 1.0) == pytest.approx(0.5 * 1.1 * 27.0 * 17.75 * cla)
    tau = inj.heave_time_s(541.0, 1.1, 27.0, 17.75, cla)
    assert 0.3 < tau < 0.6


def test_the_kick_does_no_work():
    for alpha in (-3.0, 0.0, 4.0, 10.0):
        fwd, up = inj.lift_force_body(1000.0, alpha)
        path_fwd, _, path_up = inj.path_force_body(1.0, alpha, 0.0)  # a unit force along the path
        assert fwd * path_fwd + up * path_up == pytest.approx(0.0, abs=1e-9)


def test_the_kick_comes_with_a_change_and_fades():
    hp = inj.HighPass()
    dt, tau = 0.02, 0.4
    assert hp.step(0.0, dt, tau) == 0.0  # the first sample starts it
    out = [hp.step(2.0, dt, tau) for _ in range(400)]  # a step into 2 m/s, 8 s
    assert out[0] == pytest.approx(2.0 * tau / (tau + dt))
    assert abs(out[-1]) < 1e-6  # settled: steady lift gives no kick
    back = [hp.step(0.0, dt, tau) for _ in range(400)]  # and out again: the other way
    assert back[0] < -1.9 and abs(back[-1]) < 1e-6
    assert sum(out) + sum(back) == pytest.approx(0.0, abs=1e-6)  # nothing left over


def test_a_gap_starts_the_kick_over():
    hp = inj.HighPass()
    hp.step(0.0, 0.02, 0.4)
    hp.reset()
    assert hp.step(3.0, 0.02, 0.4) == 0.0


def test_the_bumps_are_the_same_for_everyone_and_within_bounds():
    from xp_gliding.engine.edge import bumps
    values = [bumps(37.0 * k, -11.0 * k, 0.5 * k) for k in range(2000)]
    assert values == [bumps(37.0 * k, -11.0 * k, 0.5 * k) for k in range(2000)]
    assert all(-1.0 <= v <= 1.0 for v in values)
    assert abs(sum(values) / len(values)) < 0.1
    assert max(values) > 0.6 and min(values) < -0.6


def test_no_bumps_in_even_lift_and_more_where_it_changes_faster():
    from xp_gliding.engine.edge import EdgeTurbulence
    even, gentle, steep = EdgeTurbulence(), EdgeTurbulence(), EdgeTurbulence()
    dt, v = 0.02, 27.0
    for k in range(300):
        a = even.step(2.0, 0.0, v, dt)
        b = gentle.step(0.01 * v * dt * k, 0.0, v, dt)  # 0.01 m/s per metre along the track
        c = steep.step(0.03 * v * dt * k, 0.0, v, dt)
    assert a == 0.0
    assert b == pytest.approx(60.0 * 0.01, rel=0.01) and c == pytest.approx(60.0 * 0.03, rel=0.01)
