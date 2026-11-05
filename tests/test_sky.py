"""Sky profiles: the default changes nothing, a candidate shapes the same draw."""

import math

import pytest

from xp_gliding.engine import clouds as cl
from xp_gliding.engine import field as f
from xp_gliding.engine import markers, updraft
from xp_gliding.engine.geo import LocalFrame
from xp_gliding.engine.rng import SplitMix64

WSTAR, ZI = 3.0, 2000.0
LAT, LON, T = -33.46, -70.65, 57600.0
TILE = (-1673, -3533, 32)
WIDE = f.SKIES["wide_carriers"]


def key(th):
    return (th.lat, th.lon, th.birth, th.death, th.wgain, th.rgain)


def make_field(sky=None, range_m=3000.0, seed=1, accept=None):
    field = f.ThermalField(f.FieldConfig(seed=seed, day=307, range_m=range_m, sky=sky),
                           LocalFrame(LAT, LON), accept)
    field.update(T, LAT, LON)
    return field


def test_the_default_sky_is_the_one_flown_so_far():
    """Numbers from the code before profiles existed (commit 7d073aa)."""
    field = make_field()
    assert field.environment_sink(800.0, WSTAR, ZI) == -0.27618513771573727
    assert sum(1 for _ in field.thermals()) == 1644
    assert field.lift_at(0.0, 0.0, 500.0, T, WSTAR, ZI) == 2.431621224295652
    assert field.lift_at(-900.0, 1200.0, 1100.0, T, WSTAR, ZI) == -0.22330534601453325
    assert field.lift_at(1500.0, 300.0, 1400.0, T, WSTAR, ZI) == -0.049709038339657764
    tile = f.generate_tile(f.FieldConfig(seed=1, day=307), *TILE)
    assert len(tile) == 31
    assert tile[0].lat == -33.45963346192073 and tile[0].wgain == 0.8082460223197785
    assert tile[1].rgain == 1.3617461080331095 and tile[1].death == 58933.498523632676


def test_unknown_sky_name_is_the_default():
    assert f.sky_named("nope") is f.SKIES["default"]
    assert f.sky_named("wide_carriers") is WIDE
    default = f.SKIES["default"]
    assert default.cloud_base_zzi == f.LIFT_TOP_ZZI == cl.TOP_ZZI == markers.TOP_ZZI
    assert all(getattr(default, name) == 1.0 for name in f.SkyProfile.__slots__
               if name != "cloud_base_zzi")


def test_clouds_and_field_agree_on_who_carries_one():
    p = cl.CloudParams()
    assert (p.min_flux, p.min_life_s) == (f.CARRIER_MIN_FLUX, f.CARRIER_MIN_LIFE_S)
    for th in f.generate_tile(f.FieldConfig(seed=1, day=307, sky=WIDE), *TILE):
        assert cl.carries_cloud(th, p) == f.is_carrier(th.wgain, th.rgain, th.death - th.birth)


def test_a_profile_moves_nothing():
    """The thermals kept are the same ones: today's clouds stay where they are."""
    plain = f.generate_tile(f.FieldConfig(seed=1, day=307), *TILE)
    wide = f.generate_tile(f.FieldConfig(seed=1, day=307, sky=WIDE), *TILE)
    assert 0 < len(wide) < len(plain)
    assert {key(th) for th in wide} <= {key(th) for th in plain}
    p = cl.CloudParams()
    assert ({key(th) for th in plain if cl.carries_cloud(th, p)}
            == {key(th) for th in wide if cl.carries_cloud(th, p)})


def test_a_profile_is_deterministic():
    def sky():
        return {key(th) for th in make_field(WIDE).alive(T)}
    assert sky() == sky()
    other = {key(th) for th in make_field(WIDE, seed=2).alive(T)}
    assert sky() != other
    # A different load order and range do not change what is in a tile.
    small = {key(th) for th in make_field(WIDE, range_m=1000.0).thermals()}
    assert small <= {key(th) for th in make_field(WIDE, range_m=3000.0).thermals()}


def test_accept_does_not_change_who_is_thinned():
    config = f.FieldConfig(seed=3, day=307, sky=WIDE)
    everything = f.generate_tile(config, *TILE)
    cut = sorted(th.lon for th in everything)[len(everything) // 2]
    half = f.generate_tile(config, *TILE, accept=lambda lat, lon: lon > cut)
    assert {key(th) for th in half} == {key(th) for th in everything if th.lon > cut}


def test_blue_keep_is_the_share_kept():
    sky = f.SkyProfile(blue_keep=0.2)
    p = cl.CloudParams()
    drawn = kept = 0
    for j in range(60):
        tile = (-1673, -3533 + j, 32)
        drawn += sum(not cl.carries_cloud(th, p) for th in f.generate_tile(f.FieldConfig(seed=1, day=307), *tile))
        kept += sum(not cl.carries_cloud(th, p)
                    for th in f.generate_tile(f.FieldConfig(seed=1, day=307, sky=sky), *tile))
    assert drawn > 1000
    assert kept / drawn == pytest.approx(0.2, abs=0.03)


def test_carrier_is_stretched_shape_and_all():
    """The lift at r is today's at r / stretch: same peak, twice as wide."""
    field = make_field(WIDE)
    z = 550.0
    th = next(th for th in field.alive(T) if cl.carries_cloud(th, cl.CloudParams()))
    assert (th.gain, th.stretch) == (WIDE.carrier_gain, WIDE.carrier_stretch)
    we = field.environment_sink(z, WSTAR, ZI)
    wide_at = updraft.updraft_velocity(200.0 / th.stretch, z, ZI, WSTAR, th.wgain, th.rgain, we)
    plain_at = updraft.updraft_velocity(100.0, z, ZI, WSTAR, th.wgain, th.rgain, we)
    assert wide_at == pytest.approx(plain_at)
    # As a real thermal of the field: alone in a field of one, against the formula.
    s, rf = th.envelope(T)
    lone = f.ThermalField(field.config, field.frame)
    th2 = f.Thermal(LAT, LON, th.birth, th.death, th.wgain, th.rgain, th.gain, th.stretch)
    lone._grid_add(th2)
    expected = we + s * (updraft.updraft_velocity(100.0, z, ZI, WSTAR, th.wgain, th.rgain * rf, we) - we)
    assert lone.lift_at(th2.e + 200.0, th2.n, z, T, WSTAR, ZI) == pytest.approx(expected)


def test_blue_thermals_are_weaker_and_narrower():
    field = make_field(WIDE)
    th = next(th for th in field.alive(T) if not cl.carries_cloud(th, cl.CloudParams()))
    assert (th.gain, th.stretch) == (WIDE.blue_gain, WIDE.blue_stretch)
    z = 550.0
    we = field.environment_sink(z, WSTAR, ZI)
    core, r1 = markers.core_of(th, z, th.birth + 0.5 * (th.death - th.birth), WSTAR, ZI, we)
    plain = f.Thermal(th.lat, th.lon, th.birth, th.death, th.wgain, th.rgain)
    core0, r10 = markers.core_of(plain, z, th.birth + 0.5 * (th.death - th.birth), WSTAR, ZI, we)
    assert core - we == pytest.approx((core0 - we) * WIDE.blue_gain, rel=0.05)
    assert r1 == pytest.approx(r10 * WIDE.blue_stretch)


@pytest.mark.parametrize("sky", [None, WIDE])
def test_the_grid_finds_every_stretched_thermal(sky):
    """lift_at against summing every thermal alive: nothing is cut off by the search radius."""
    field = make_field(sky)
    for z in (500.0, 1000.0, 1500.0):
        we = field.environment_sink(z, WSTAR, ZI)
        for e, n in ((0.0, 0.0), (420.0, -730.0), (-1100.0, 650.0), (1490.0, 1490.0)):
            total = we
            for th in field.alive(T):
                s, rf = th.envelope(T)
                r = math.hypot(e - th.e, n - th.n)
                w = updraft.updraft_velocity(r / th.stretch, z, ZI, WSTAR, th.wgain * th.gain, th.rgain * rf, we)
                total += s * (w - we)
            assert field.lift_at(e, n, z, T, WSTAR, ZI) == pytest.approx(total, abs=1e-9)


def test_carrier_flux_share_against_a_large_sample():
    config = f.FieldConfig(seed=1, day=307)
    rng = SplitMix64(12345)
    total = carriers = 0.0
    weight = 0.0
    for _ in range(200000):
        wgain = rng.lognormal_unit_mean(config.wgain_sigma)
        rgain = rng.lognormal_unit_mean(config.rgain_sigma)
        life = rng.uniform_range(config.lifetime_min_s, config.lifetime_max_s)
        flux = wgain * rgain * rgain
        # Alive in proportion to its lifetime.
        weight += life
        total += flux * life
        if f.is_carrier(wgain, rgain, life):
            carriers += flux * life
    assert total / weight == pytest.approx(math.exp(config.rgain_sigma ** 2), rel=0.01)
    assert carriers / weight == pytest.approx(f.carrier_flux_share(config), rel=0.03)


def test_mean_flux_gain_of_the_default_is_exact():
    config = f.FieldConfig()
    assert f.mean_flux_gain(config) == math.exp(config.rgain_sigma ** 2)


def test_the_sink_follows_the_flux():
    plain = make_field()
    wide = make_field(WIDE)
    ratio = f.mean_flux_gain(wide.config) / f.mean_flux_gain(plain.config)
    assert 0.3 < ratio < 0.8
    for z in (400.0, 900.0):
        assert (wide.environment_sink(z, WSTAR, ZI) / plain.environment_sink(z, WSTAR, ZI)
                == pytest.approx(ratio, rel=0.15))


@pytest.mark.parametrize("sky", [None, WIDE])
def test_what_goes_up_comes_down(sky):
    """The mean of all the air is near zero below mid height, where Allen has no ring."""
    field = make_field(sky, range_m=6000.0)
    z = 500.0
    n_side = 60
    step = 8000.0 / n_side
    total = 0.0
    for i in range(n_side):
        for j in range(n_side):
            total += field.lift_at(-4000.0 + i * step, -4000.0 + j * step, z, T, WSTAR, ZI)
    assert abs(total / n_side ** 2) < 0.1


def test_catalog_uses_the_same_sky_as_the_field():
    frame = LocalFrame(LAT, LON)
    config = f.FieldConfig(seed=1, day=307, range_m=3000.0, sky=WIDE)
    catalog = cl.CloudCatalog(config, frame, cl.CloudParams(tiles_per_update=1000))
    while catalog.update(T, LAT, LON):
        pass
    assert catalog.config.sky is WIDE
    thermals = list(catalog.thermals())
    assert thermals
    assert all(th.stretch == WIDE.carrier_stretch for th in thermals)


def test_cloud_size_does_not_follow_the_stretch():
    """A cloud's size is from the drawn rgain, not the lift's width."""
    drawn = f.Thermal(LAT, LON, 0.0, 1000.0, 1.0, 1.25, 1.0, 1.0)
    wide = f.Thermal(LAT, LON, 0.0, 1000.0, 1.0, 1.25, 1.0, 2.0)
    assert cl.cloud_scale(wide) == cl.cloud_scale(drawn) == 1.0


def test_the_cloud_base_moves_no_lift():
    low = f.SkyProfile(carrier_stretch=2.0, blue_keep=0.15, blue_gain=0.6, blue_stretch=0.75,
                       cloud_base_zzi=0.5)
    high = f.SkyProfile(carrier_stretch=2.0, blue_keep=0.15, blue_gain=0.6, blue_stretch=0.75)
    a, b = make_field(low), make_field(high)
    assert a.environment_sink(900.0, WSTAR, ZI) == b.environment_sink(900.0, WSTAR, ZI)
    for e, n, z in ((0.0, 0.0, 500.0), (420.0, -730.0, 1200.0), (-1100.0, 650.0, 1700.0)):
        assert a.lift_at(e, n, z, T, WSTAR, ZI) == b.lift_at(e, n, z, T, WSTAR, ZI)


def test_wide_carriers_have_their_base_within_reach():
    """The base is below where the lift ends, and a median carrier still has lift there."""
    base = WIDE.cloud_base_zzi * ZI
    assert base < f.LIFT_TOP_ZZI * ZI
    w = updraft.updraft_velocity(0.0, base, ZI, WSTAR, 1.36, 1.35)
    assert 1.0 < w < 2.0
