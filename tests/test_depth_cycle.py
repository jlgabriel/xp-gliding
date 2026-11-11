"""The daily cycle's step B: each thermal as deep as the day was at its birth (`FieldConfig.depth_cycle`)."""

import math

import pytest

from xp_gliding.engine import sun
from xp_gliding.engine.clouds import CloudCatalog, CloudParams, carries_cloud
from xp_gliding.engine.field import SKIES, FieldConfig, ThermalField, generate_tile
from xp_gliding.engine.geo import LocalFrame
from xp_gliding.engine.markers import select_markers

HOBBS = (32.6875, -103.2170)
DAY = 305  # 2 November
ZI = 2000.0
WSTAR = 3.0
SKY = SKIES["wide_carriers"]


def solar(hour, lon=HOBBS[1]):
    return sun.utc_for_solar(lon, DAY, hour * 3600.0)


def config(depth=True, sun_min_deg=sun.SUN_MIN_DEG, **kw):
    return FieldConfig(seed=1, day=DAY, zi_m=ZI, sky=SKY, range_m=4000.0, sun_min_deg=sun_min_deg,
                       depth_cycle=depth, **kw)


def field_at(hour, depth=True):
    lat, lon = HOBBS
    field = ThermalField(config(depth), LocalFrame(lat, lon))
    field.update(solar(hour), lat, lon)
    return field


def test_off_or_without_the_sun_every_thermal_is_as_deep_as_the_field():
    assert not config(depth=True, sun_min_deg=None).depth_cycle
    for depth in (False, True):
        field = ThermalField(config(depth, sun_min_deg=None), LocalFrame(*HOBBS))
        field.update(solar(10.0), *HOBBS)
        assert field.loaded_count() > 0
        assert all(th.depth == 1.0 for th in field.thermals())
        assert field.depth_share == 1.0
    assert all(th.depth == 1.0 for th in field_at(10.0, depth=False).thermals())


def test_each_thermal_is_as_deep_as_the_day_at_its_birth():
    field = field_at(11.0)
    cycle = field.cycle
    alive = field.alive(solar(11.0))
    assert alive
    for th in alive:
        assert th.depth == cycle.depth_share(th.lat, th.lon, th.birth)
        assert th.zi(ZI) == ZI * th.depth
    assert field.depth_share == pytest.approx(cycle.depth_share(*HOBBS, solar(11.0)))


def test_the_same_thermals_as_without_the_depth_only_shallower():
    plain, deep = field_at(10.0, depth=False), field_at(10.0, depth=True)
    key = lambda th: (th.lat, th.lon, th.birth, th.wgain, th.rgain)  # noqa: E731
    assert sorted(map(key, plain.thermals())) == sorted(map(key, deep.thermals()))
    assert max(th.depth for th in deep.alive(solar(10.0))) < 0.6


def test_morning_thermals_are_shallower_than_the_afternoons():
    morning = [th.depth for th in field_at(10.0).alive(solar(10.0))]
    afternoon = [th.depth for th in field_at(15.5).alive(solar(15.5))]
    assert max(morning) < 0.6
    assert min(afternoon) > 0.95


def test_above_its_own_depth_a_morning_thermal_lifts_nothing():
    field = field_at(10.0)
    t = solar(10.0)
    th = max(field.alive(t), key=lambda x: x.wgain * x.rgain ** 2 * x.envelope(t)[0])
    top = th.zi(ZI)
    assert field.lift_at(th.e, th.n, 0.4 * top, t, WSTAR, ZI) > 1.0
    # Above every thermal alive and the zi of the moment: no lift and no sink at all.
    above = max(x.zi(ZI) for x in field.alive(t))
    above = max(above, ZI * field.depth_share) + 10.0
    assert above < ZI
    assert field.lift_at(th.e, th.n, above, t, WSTAR, ZI) == 0.0
    # Without the depth the same thermal reaches the afternoon's height.
    plain = field_at(10.0, depth=False)
    assert plain.lift_at(th.e, th.n, above, t, WSTAR, ZI) > 0.5


def test_the_sink_between_thermals_is_the_one_for_the_zi_of_the_moment():
    field = field_at(10.0)
    plain = field_at(10.0, depth=False)
    z = 0.3 * ZI * field.depth_share
    assert field.environment_sink(z, WSTAR, ZI * field.depth_share) * field.sink_share < 0.0
    # Shallower thermals cover less of the sky, so less sinks between them than in step A.
    assert (field.environment_sink(z, WSTAR, ZI * field.depth_share)
            > plain.environment_sink(z, WSTAR, ZI))


def test_lift_changes_smoothly_in_time_through_the_morning():
    field = field_at(10.0)
    z = 300.0
    t0 = solar(10.0)
    points = [(x * 61.0, y * 67.0) for x in range(-15, 16, 3) for y in range(-15, 16, 3)]
    prev = [field.lift_at(e, n, z, t0, WSTAR, ZI) for e, n in points]
    for step in range(1, 300):
        t = t0 + step
        if step % 30 == 0:
            field.update(t, *HOBBS)  # the zi of the moment moves on, as in the plugin
        cur = [field.lift_at(e, n, z, t, WSTAR, ZI) for e, n in points]
        assert max(abs(b - a) for a, b in zip(prev, cur)) < 0.1
        prev = cur


def test_the_field_and_the_clouds_give_a_thermal_the_same_depth():
    lat, lon = HOBBS
    t = solar(14.0)
    field = ThermalField(config(), LocalFrame(lat, lon))
    field.update(t, lat, lon)
    catalog = CloudCatalog(field.config, LocalFrame(lat, lon))
    while catalog.update(t, lat, lon):
        pass
    depth = {(th.lat, th.lon, th.birth): th.depth for th in field.thermals()}
    clouds = list(catalog.thermals())
    assert clouds
    for th in clouds:
        key = (th.lat, th.lon, th.birth)
        if key in depth:
            assert th.depth == depth[key]


def test_a_tile_alone_gets_the_same_depths_as_the_field():
    cfg = config()
    i, j = math.floor(HOBBS[0] / cfg.tile_deg), math.floor(HOBBS[1] / cfg.tile_deg)
    slot = math.floor(solar(11.0) / cfg.slot_s)
    alone = generate_tile(cfg, i, j, slot)
    shared = generate_tile(cfg, i, j, slot, cycle=cfg.cycle())
    assert alone and [th.depth for th in alone] == [th.depth for th in shared]


def test_the_first_clouds_stand_lower_than_the_afternoons():
    params = CloudParams()
    base_zzi = SKY.cloud_base_zzi

    def bases(hour):
        field = field_at(hour)
        return [base_zzi * th.zi(ZI) for th in field.alive(solar(hour))
                if carries_cloud(th, params) and not field.cycle.blue(th.lat, th.lon, th.birth, base_zzi)]

    early, late = bases(13.0), bases(15.5)
    assert early and late
    assert max(early) < min(late)
    assert min(early) >= base_zzi * base_zzi * ZI - 1e-6  # no cloud before zi reaches the base
    assert max(late) <= base_zzi * ZI


def test_markers_read_each_thermal_at_its_own_depth():
    field = field_at(10.0)
    t = solar(10.0)
    low = select_markers(field, 0.0, 0.0, 250.0, t, WSTAR, ZI)
    assert low
    above = max(th.zi(ZI) for th in field.alive(t)) + 10.0
    assert select_markers(field, 0.0, 0.0, above, t, WSTAR, ZI) == []
