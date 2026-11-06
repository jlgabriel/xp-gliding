import math

import pytest

from xp_gliding.engine import field as f
from xp_gliding.engine import updraft
from xp_gliding.engine.geo import LocalFrame

WSTAR, ZI = 2.56, 1401.0
LAT, LON = -33.45, -70.95  # central Chile


def make_field(lat=LAT, lon=LON, t=12 * 3600.0, range_m=4000.0):
    cfg = f.FieldConfig(seed=7, day=9800, range_m=range_m)
    field = f.ThermalField(cfg, LocalFrame(lat, lon))
    field.update(t, lat, lon)
    return field


def signature(field):
    return sorted((round(th.lat, 9), round(th.lon, 9), round(th.birth, 3)) for th in field.thermals())


def test_life_envelope_is_smooth_and_bounded():
    assert f.life_envelope(-0.01) == (0.0, 0.0)
    assert f.life_envelope(1.0) == (0.0, 0.0)
    assert f.life_envelope(0.0)[0] == 0.0
    assert f.life_envelope(0.5) == (1.0, 1.0)
    steps = [f.life_envelope(k / 10000)[0] for k in range(10000)]
    assert max(abs(b - a) for a, b in zip(steps, steps[1:])) < 0.001
    assert 0.0 < f.MEAN_LIFE_FLUX < 1.0


def test_same_inputs_same_sky_whatever_the_frame_or_order():
    a = make_field()
    # Different local origin, approached from elsewhere, loaded in another order.
    cfg = f.FieldConfig(seed=7, day=9800, range_m=4000.0)
    b = f.ThermalField(cfg, LocalFrame(LAT + 0.3, LON - 0.2))
    b.update(12 * 3600.0, LAT + 0.05, LON)
    b.update(12 * 3600.0, LAT, LON)
    keys = a.wanted_keys(12 * 3600.0, LAT, LON)
    b_same = sorted((round(th.lat, 9), round(th.lon, 9), round(th.birth, 3))
                    for key in keys for th in b._tiles[key])
    assert b_same == signature(a)


def test_seed_and_day_change_the_sky():
    base = signature(make_field())
    cfg = f.FieldConfig(seed=8, day=9800, range_m=4000.0)
    other = f.ThermalField(cfg, LocalFrame(LAT, LON))
    other.update(12 * 3600.0, LAT, LON)
    assert signature(other) != base


def test_alive_density_matches_config():
    field = make_field(range_m=15000.0)
    t = 12 * 3600.0
    # Count alive thermals in a 20 km x 20 km box well inside the loaded area.
    inside = [th for th in field.alive(t) if abs(th.e) < 10000 and abs(th.n) < 10000]
    expected = field.config.density_per_km2 * 400.0
    assert len(inside) == pytest.approx(expected, rel=0.1)


def test_default_density_is_allen_at_zi_ref():
    cfg = f.FieldConfig()
    assert cfg.density_per_km2 == pytest.approx(4.5, abs=0.1)


def test_accept_predicate_removes_without_shifting_the_rest():
    cfg = f.FieldConfig(seed=3)
    everything = f.generate_tile(cfg, -1673, -3548, 24)
    east_half = f.generate_tile(cfg, -1673, -3548, 24, accept=lambda lat, lon, birth: lon > -70.95)
    assert 0 < len(east_half) < len(everything)
    kept = {(th.lat, th.lon) for th in everything if th.lon > -70.95}
    assert {(th.lat, th.lon) for th in east_half} == kept


def test_lift_far_from_thermals_is_environment_sink():
    field = make_field()
    t = 12 * 3600.0
    z = 0.4 * ZI
    we = field.environment_sink(z, WSTAR, ZI)
    assert we < 0.0
    reach = updraft.influence_radius(z, ZI, f.RGAIN_RANGE[1])
    alive = field.alive(t)
    # Find a point at least `reach` from every thermal.
    for k in range(2000):
        e, n = (k % 40) * 50.0 - 1000.0, (k // 40) * 50.0 - 1000.0
        if all(math.hypot(e - th.e, n - th.n) > reach for th in alive):
            assert field.lift_at(e, n, z, t, WSTAR, ZI) == pytest.approx(we)
            return
    pytest.fail("no thermal-free point found")


def test_lift_in_a_mature_thermal():
    field = make_field()
    t = 12 * 3600.0
    z = 0.3 * ZI
    mature = [th for th in field.alive(t) if th.envelope(t) == (1.0, 1.0)]
    assert mature
    th = max(mature, key=lambda x: x.wgain)
    w = field.lift_at(th.e, th.n, z, t, WSTAR, ZI)
    alone = updraft.updraft_velocity(0.0, z, ZI, WSTAR, th.wgain, th.rgain,
                                     field.environment_sink(z, WSTAR, ZI))
    assert w >= alone - 1e-9  # neighbours can only add their perturbations
    assert w > 1.0


def test_lift_changes_smoothly_in_time_through_births_and_deaths():
    field = make_field()
    z = 0.3 * ZI
    t0 = 12 * 3600.0
    points = [(x * 37.0, y * 41.0) for x in range(-20, 21, 4) for y in range(-20, 21, 4)]
    prev = [field.lift_at(e, n, z, t0, WSTAR, ZI) for e, n in points]
    for step in range(1, 600):  # 10 minutes, 1 s steps
        t = t0 + step
        cur = [field.lift_at(e, n, z, t, WSTAR, ZI) for e, n in points]
        assert max(abs(b - a) for a, b in zip(prev, cur)) < 0.1
        prev = cur


def test_lift_is_continuous_in_space():
    field = make_field()
    t = 12 * 3600.0
    z = 0.7 * ZI  # with the toroidal downdraft
    for row in range(-5, 6):
        n = row * 173.0
        w = [field.lift_at(e * 1.0, n, z, t, WSTAR, ZI) for e in range(-3000, 3000)]
        assert max(abs(b - a) for a, b in zip(w, w[1:])) < 0.15


def test_slot_change_keeps_alive_thermals():
    cfg = f.FieldConfig(seed=1, range_m=2000.0)
    field = f.ThermalField(cfg, LocalFrame(LAT, LON))
    t = 3 * cfg.slot_s - 1.0
    field.update(t, LAT, LON)
    before = {(th.lat, th.lon) for th in field.alive(t)}
    field.update(t + 2.0, LAT, LON)  # crosses into the next slot
    after = {(th.lat, th.lon) for th in field.alive(t + 2.0)}
    # Only thermals that genuinely died in those 2 s may be missing.
    missing = before - after
    assert len(missing) <= 1


def test_set_frame_moves_positions_not_thermals():
    field = make_field()
    t = 12 * 3600.0
    th = max(field.alive(t), key=lambda x: x.wgain)
    z = 0.3 * ZI
    w_before = field.lift_at(th.e, th.n, z, t, WSTAR, ZI)
    new_frame = LocalFrame(LAT + 0.01, LON + 0.01)
    field.set_frame(new_frame)
    e, n = new_frame.to_enu(th.lat, th.lon)
    assert (th.e, th.n) == (e, n)
    assert field.lift_at(e, n, z, t, WSTAR, ZI) == pytest.approx(w_before, abs=1e-6)


def test_sky_time_is_zulu_without_the_wrap_inside_a_local_day():
    from xp_gliding.engine.field import sky_time
    h = 3600.0
    assert sky_time(19 * h, 12 * h) == 19 * h  # Hobbs at noon
    assert sky_time(1 * h, 18 * h) == 25 * h  # Hobbs after zulu midnight: same local date
    assert sky_time(23 * h, 9 * h) == -1 * h  # east of Greenwich, before zulu midnight
    assert sky_time(5 * h, 12 * h) == 5 * h
