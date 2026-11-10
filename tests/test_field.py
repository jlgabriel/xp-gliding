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
    assert cfg.zi_m == f.ZI_TUNED_M == 2000.0
    assert cfg.density_per_km2 == pytest.approx(4.5, abs=0.1)


def test_density_follows_zi_as_allens_does_through_the_tuned_sky():
    tuned = f.FieldConfig().density_per_km2
    for zi in (1000.0, 1333.0, 3000.0, 4667.0):
        density = f.FieldConfig(zi_m=zi).density_per_km2
        assert density == pytest.approx(tuned * (2000.0 / zi) ** 2)
        allen = updraft.allen_density_per_m2(zi) / updraft.allen_density_per_m2(2000.0)
        assert density / tuned == pytest.approx(allen)
    assert f.FieldConfig(zi_m=3000.0, density_per_km2=1.0).density_per_km2 == 1.0


@pytest.mark.parametrize("sky", sorted(f.SKIES))
def test_the_sink_between_thermals_does_not_change_with_zi(sky):
    def sink(zi):
        field = f.ThermalField(f.FieldConfig(seed=1, zi_m=zi, sky=f.SKIES[sky]), LocalFrame(LAT, LON))
        return [field.environment_sink(k * zi, 3.0, zi) for k in (0.2, 0.4, 0.6)]
    tuned = sink(2000.0)
    assert all(-0.5 < w < 0.0 for w in tuned)
    for zi in (1000.0, 1333.0, 3000.0, 4667.0, 8000.0):
        assert sink(zi) == pytest.approx(tuned)


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


# --- a thermal's own height: the lift ends with its cloud -------------------------------------


def one_thermal(floor_m=None, zi=2000.0):
    """A field with a single mature thermal over the origin."""
    field = f.ThermalField(f.FieldConfig(seed=7, day=9800), LocalFrame(LAT, LON))
    th = f.Thermal(LAT, LON, 0.0, 2000.0, 1.5, 1.2)
    th.floor_m = floor_m
    field._tiles[(0, 0, 0)] = [th]
    field._grid_add(th)
    return field, th


def test_the_height_in_a_thermal_comes_from_its_floor():
    th = f.Thermal(LAT, LON, 0.0, 2000.0, 1.0, 1.0)
    assert f.height_in_thermal(th, 800.0, 1500.0) == 800.0  # no floor
    th.floor_m = 500.0
    assert f.height_in_thermal(th, 800.0, None) == 800.0  # no ground
    assert f.height_in_thermal(th, 800.0, 1500.0) == 1800.0  # high ground
    assert f.height_in_thermal(th, 800.0, 500.0) == 800.0  # on the flat, exactly
    assert f.height_in_thermal(th, 800.0, 100.0) == 400.0  # a valley under the floor
    assert f.height_in_thermal(th, 800.0, -1000.0) == f.LOW_HEIGHT_M  # deeper than the climb
    assert f.height_in_thermal(th, 50.0, -1000.0) == 50.0  # never above the glider's own height


def test_with_the_floor_on_the_ground_no_floor_or_no_ground_the_lift_is_the_same():
    field = make_field()
    t = 12 * 3600.0
    points = [(e, n, z) for e in (-900.0, -80.0, 350.0) for n in (-500.0, 60.0, 700.0)
              for z in (30.0, 400.0, 1100.0, 1390.0)]
    before = [field.lift_at(e, n, z, t, WSTAR, ZI) for e, n, z in points]
    # No floor, with a ground: only the search is wider.
    assert [field.lift_at(e, n, z, t, WSTAR, ZI, 712.3) for e, n, z in points] == before
    for th in field.thermals():
        th.floor_m = 712.3
    # A floor, with no ground.
    assert [field.lift_at(e, n, z, t, WSTAR, ZI) for e, n, z in points] == before
    # The floor is the ground under the glider.
    assert [field.lift_at(e, n, z, t, WSTAR, ZI, 712.3) for e, n, z in points] == before


def test_above_the_layer_a_thermal_with_no_floor_gives_nothing_with_or_without_a_ground():
    field = make_field()
    t = 12 * 3600.0
    assert field.lift_at(0.0, 0.0, ZI + 1.0, t, WSTAR, ZI) == 0.0
    assert field.lift_at(0.0, 0.0, ZI + 1.0, t, WSTAR, ZI, 500.0) == 0.0


def test_over_high_ground_the_lift_ends_above_the_floor_and_not_above_the_ground():
    zi = 2000.0
    field, th = one_thermal(floor_m=500.0, zi=zi)
    t = 1000.0
    ground = 1500.0
    # Allen's mean updraft ends at zi/1.1 over the floor: 2318 m MSL, 818 m over this ground.
    top = 500.0 + zi / 1.1 - ground
    assert field.lift_at(0.0, 0.0, top - 300.0, t, WSTAR, zi, ground) > 1.0
    assert field.lift_at(0.0, 0.0, top + 5.0, t, WSTAR, zi, ground) < 0.0
    assert field.lift_at(0.0, 0.0, top + 300.0, t, WSTAR, zi, ground) < 0.0
    # The same point read by the ground under the glider, as it was: strong lift well past it.
    assert field.lift_at(0.0, 0.0, top + 300.0, t, WSTAR, zi) > 1.5
    # Past zi of the floor it is out of the thermal altogether.
    assert field.lift_at(0.0, 0.0, 500.0 + zi + 10.0 - ground, t, WSTAR, zi, ground) == pytest.approx(
        field.environment_sink(500.0 + zi + 10.0 - ground, WSTAR, zi))


def test_at_its_clouds_base_the_lift_over_a_hill_is_what_it_is_on_the_flat():
    zi, base_zzi = 2000.0, 0.75
    t = 1000.0
    flat, _ = one_thermal(floor_m=1000.0, zi=zi)
    hill, _ = one_thermal(floor_m=1000.0 + 1300.0, zi=zi)  # its cloud raised by 1300 m
    base = 1000.0 + base_zzi * zi
    over_flat = flat.lift_at(0.0, 0.0, base - 1000.0, t, WSTAR, zi, 1000.0)
    z_hill = base + 1300.0 - 2400.0  # over ground of 2400 m, near the cloud
    over_hill = hill.lift_at(0.0, 0.0, z_hill, t, WSTAR, zi, 2400.0)
    # All but the sink between thermals, which stays with the height above the ground.
    own = over_flat - flat.environment_sink(base - 1000.0, WSTAR, zi)
    assert over_hill - hill.environment_sink(z_hill, WSTAR, zi) == pytest.approx(own)


def test_in_a_valley_deeper_than_the_level_the_lift_is_as_at_the_low_height():
    zi = 2000.0
    t = 1000.0
    field, _ = one_thermal(floor_m=2000.0, zi=zi)
    low, _ = one_thermal(zi=zi)
    z = 800.0
    lift = field.lift_at(0.0, 0.0, z, t, WSTAR, zi, 500.0)
    own = low.lift_at(0.0, 0.0, f.LOW_HEIGHT_M, t, WSTAR, zi) - low.environment_sink(f.LOW_HEIGHT_M, WSTAR, zi)
    assert lift - field.environment_sink(z, WSTAR, zi) == pytest.approx(own)
    assert lift > 0.0


def test_no_jump_where_a_valley_meets_the_floor():
    zi = 2000.0
    field, _ = one_thermal(floor_m=1000.0, zi=zi)
    lifts = [field.lift_at(30.0, 0.0, float(z), 1000.0, WSTAR, zi, 0.0) for z in range(900, 1300)]
    assert max(abs(b - a) for a, b in zip(lifts, lifts[1:])) < 0.02


def test_thermals_at_two_floors_each_end_at_their_own_height():
    zi = 2000.0
    field, near = one_thermal(floor_m=500.0, zi=zi)
    far = f.Thermal(LAT, LON + 0.02, 0.0, 2000.0, 1.5, 1.2)
    far.floor_m = 1500.0
    far.e, far.n = field.frame.to_enu(far.lat, far.lon)
    field._tiles[(0, 0, 1)] = [far]
    field._grid_add(far)
    # The same point in the air: 2600 m MSL, over ground of 1400 m.
    z, ground = 1200.0, 1400.0
    assert field.lift_at(0.0, 0.0, z, 1000.0, WSTAR, zi, ground) < 0.0  # 2100 m in the first
    assert field.lift_at(far.e, far.n, z, 1000.0, WSTAR, zi, ground) > 1.0  # 1100 m in the second
