import math
import statistics

import pytest

from xp_gliding.engine import areas as a
from xp_gliding.engine import field as f
from xp_gliding.engine.clouds import CloudCatalog
from xp_gliding.engine.geo import LocalFrame
from xp_gliding.engine.rng import SplitMix64

LAT, LON = -33.45, -70.95  # central Chile


def random_places(count, seed=7):
    r = SplitMix64(seed)
    for _ in range(count):
        yield math.degrees(math.asin(2.0 * r.uniform() - 1.0)), 360.0 * r.uniform() - 180.0


def sample_q(count=6000):
    qs = []
    for k, (lat, lon) in enumerate(random_places(count)):
        qs.append(a.Areas(k % 6, 300 + k % 6).quality(lat, lon))
    return qs


def test_the_same_seed_and_date_give_the_same_map_and_another_date_another():
    one, again = a.Areas(7, 312), a.Areas(7, 312)
    other_day, other_seed = a.Areas(7, 313), a.Areas(8, 312)
    places = list(random_places(50))
    q = [one.quality(*p) for p in places]
    assert q == [again.quality(*p) for p in places]
    assert all(-a.Q_LIMIT <= v <= a.Q_LIMIT for v in q)
    assert sum(abs(x - y) > 0.2 for x, y in zip(q, [other_day.quality(*p) for p in places])) > 30
    assert sum(abs(x - y) > 0.2 for x, y in zip(q, [other_seed.quality(*p) for p in places])) > 30


def test_the_map_is_smooth_over_hundreds_of_metres_and_changes_over_tens_of_km():
    m = a.Areas(1, 312)
    km = 1.0 / 111.2  # degrees of latitude
    steps, far = [], []
    for k in range(200):
        lat, lon = LAT + 0.01 * k, LON + 0.013 * k
        q = m.quality(lat, lon)
        steps.append(abs(m.quality(lat + 0.5 * km, lon) - q))
        far.append(abs(m.quality(lat + 40.0 * km, lon + 25.0 * km / math.cos(math.radians(lat))) - q))
    assert max(steps) < 0.25
    assert statistics.mean(steps) < 0.08
    assert statistics.mean(far) > 0.7  # about two areas apart: as different as two places at random


def test_quality_is_about_a_standard_normal_over_the_globe():
    qs = sample_q()
    assert statistics.mean(qs) == pytest.approx(0.0, abs=0.05)
    assert statistics.pstdev(qs) == pytest.approx(1.0, abs=0.05)
    qs.sort()
    assert qs[int(0.85 * len(qs))] == pytest.approx(1.05, abs=0.1)
    assert qs[int(0.15 * len(qs))] == pytest.approx(-1.05, abs=0.1)


def test_marked_contrast_between_the_best_and_the_worst_areas():
    density, strength = a.factors(1.05)
    assert density == pytest.approx(1.6, abs=0.02)
    assert strength == pytest.approx(1.2, abs=0.01)
    density, strength = a.factors(-1.05)
    assert density == pytest.approx(0.4, abs=0.02)
    assert strength == pytest.approx(0.8, abs=0.01)
    assert a.factors(-3.0)[0] == 0.0  # the very worst draws none


def test_the_sky_as_a_whole_keeps_its_thermals_and_the_flux_is_as_the_field_assumes():
    pairs = [a.factors(q) for q in sample_q()]
    assert statistics.mean(d for d, _ in pairs) == pytest.approx(1.0, abs=0.04)
    assert statistics.mean(s for _, s in pairs) == pytest.approx(1.0, abs=0.02)
    assert statistics.mean(d * s for d, s in pairs) == pytest.approx(a.MEAN_FLUX, abs=0.04)


def test_a_tile_reads_its_centre():
    m = a.Areas(3, 312)
    i, j = math.floor(LAT / 0.02), math.floor(LON / 0.02)
    assert m.at_tile(i, j, 0.02) == a.factors(m.quality((i + 0.5) * 0.02, (j + 0.5) * 0.02))


def test_off_by_default_the_sky_is_as_before():
    assert f.FieldConfig().areas is None
    cfg = f.FieldConfig(seed=3)
    on = f.FieldConfig(seed=3, areas=True)
    assert isinstance(on.areas, a.Areas)
    i, j = math.floor(LAT / 0.02), math.floor(LON / 0.02)
    tile = f.generate_tile(cfg, i, j, 24)
    assert [(th.lat, th.lon, th.gain) for th in tile] == [
        (th.lat, th.lon, th.gain) for th in f.generate_tile(f.FieldConfig(seed=3, areas=False), i, j, 24)]


def best_and_worst_tiles(cfg, around=(LAT, LON), span=30):
    """The best and the worst tile of a box around a place, by the map's quality."""
    i0, j0 = math.floor(around[0] / cfg.tile_deg), math.floor(around[1] / cfg.tile_deg)
    tiles = [(i, j) for i in range(i0 - span, i0 + span, 3) for j in range(j0 - span, j0 + span, 3)]
    tiles.sort(key=lambda ij: cfg.areas.at_tile(ij[0], ij[1], cfg.tile_deg)[0])
    return tiles[-1], tiles[0]


def test_a_good_area_draws_more_and_stronger_thermals_than_a_bad_one():
    on = f.FieldConfig(seed=3, day=312, areas=True)
    off = f.FieldConfig(seed=3, day=312)
    good, bad = best_and_worst_tiles(on)
    dg, sg = on.areas.at_tile(*good, on.tile_deg)
    db, sb = on.areas.at_tile(*bad, on.tile_deg)
    assert dg > 1.5 and db < 0.5 and sg > sb

    def count(cfg, tile):
        return sum(len(f.generate_tile(cfg, *tile, slot)) for slot in range(40))

    assert count(on, good) == pytest.approx(dg * count(off, good), rel=0.15)
    assert count(on, bad) == pytest.approx(db * count(off, bad), rel=0.3)
    for th in f.generate_tile(on, *good, 24):
        assert th.gain == pytest.approx(sg * (on.sky.carrier_gain if f.is_carrier(th.wgain, th.rgain,
                                                                                  th.death - th.birth)
                                              else on.sky.blue_gain))


def test_the_sink_between_thermals_counts_the_areas_flux():
    off = f.ThermalField(f.FieldConfig(seed=1), LocalFrame(LAT, LON))
    on = f.ThermalField(f.FieldConfig(seed=1, areas=True), LocalFrame(LAT, LON))
    w_off = off.environment_sink(800.0, 3.0, 2000.0)
    w_on = on.environment_sink(800.0, 3.0, 2000.0)
    assert w_off < 0.0
    assert w_on / w_off == pytest.approx(a.MEAN_FLUX, rel=0.05)


def test_the_clouds_see_the_fields_areas():
    cfg = f.FieldConfig(seed=5, day=312, areas=True, sky=f.SKIES["wide_carriers"])
    catalog = CloudCatalog(cfg, LocalFrame(LAT, LON))
    assert catalog.config.areas is not None
    good, _ = best_and_worst_tiles(cfg)
    for slot in (23, 24):
        tile = f.generate_tile(catalog.config, *good, slot)
        assert [(th.lat, th.gain) for th in tile] == [(th.lat, th.gain) for th in f.generate_tile(cfg, *good, slot)]
