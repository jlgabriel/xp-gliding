import io
import math
import os
import sys

import pytest
from PIL import Image

from xp_gliding.engine import clouds as cl
from xp_gliding.engine.field import FieldConfig, ThermalField, generate_tile, tile_area_m2
from xp_gliding.engine.geo import LocalFrame

KHOB = (32.6875, -103.2170)
NOON = 19 * 3600.0


def config():
    return FieldConfig(seed=1, day=306)


def full_catalog(params=None, t=NOON, where=KHOB):
    catalog = cl.CloudCatalog(config(), LocalFrame(*KHOB), params)
    while catalog.update(t, *where):
        pass
    return catalog


def make_thermal(birth=0.0, life=1000.0, wgain=1.5, rgain=1.5, e=0.0, n=0.0):
    from xp_gliding.engine.field import Thermal
    th = Thermal(KHOB[0], KHOB[1], birth, birth + life, wgain, rgain)
    th.e, th.n = e, n
    return th


def run(planner, thermals, e, n, t):
    """A step, with what happened to each thermal as a simple list."""
    return [(a, th, r) for a, th, r in planner.step(thermals, e, n, t)]


# --- which thermals ------------------------------------------------------------------

def test_a_cloud_depends_only_on_the_thermal():
    p = cl.CloudParams()
    assert cl.carries_cloud(make_thermal(wgain=1.5, rgain=1.5, life=1000.0), p)
    assert not cl.carries_cloud(make_thermal(wgain=0.5, rgain=1.0, life=1000.0), p)
    assert not cl.carries_cloud(make_thermal(wgain=1.5, rgain=1.5, life=500.0), p)


def test_density_is_a_cumulus_sky():
    """About one every 3 km: the number notes/phase2.md gives."""
    c = config()
    p = cl.CloudParams()
    area, count = 0.0, 0
    for i in range(1630, 1640):
        for j in range(-5165, -5155):
            area += tile_area_m2(i, j, c.tile_deg) * 1e-6
            for slot in (math.floor(NOON / c.slot_s) - 1, math.floor(NOON / c.slot_s)):
                for th in generate_tile(c, i, j, slot):
                    if not cl.carries_cloud(th, p):
                        continue
                    start, stop = cl.feeding_window(th, p)
                    count += start <= NOON < stop
    assert 0.07 < count / area < 0.2


def test_catalog_has_the_same_thermals_as_the_field():
    frame = LocalFrame(*KHOB)
    field = ThermalField(FieldConfig(seed=1, day=306, range_m=10000.0), frame)
    field.update(NOON, *KHOB)
    catalog = full_catalog()
    p = catalog.params
    key = lambda th: (th.lat, th.lon, th.birth, th.death, th.wgain, th.rgain)  # noqa: E731
    in_field = {key(th) for th in field.thermals() if cl.carries_cloud(th, p)}
    in_catalog = {key(th) for th in catalog.thermals()}
    assert in_field and in_field <= in_catalog
    near = [th for th in catalog.thermals() if math.hypot(th.e, th.n) < 9000.0]
    assert len(near) > 10 and all(key(th) in in_field for th in near)


def test_catalog_is_for_the_fields_zi():
    config = FieldConfig(seed=1, day=306, zi_m=3500.0)
    catalog = cl.CloudCatalog(config, LocalFrame(*KHOB))
    assert catalog.config.zi_m == 3500.0
    assert catalog.config.density_per_km2 == config.density_per_km2 < FieldConfig().density_per_km2


def numbers(thermals):
    return {(th.lat, th.lon, th.birth, th.death, th.wgain, th.rgain) for th in thermals}


def test_catalog_does_not_depend_on_the_path_or_the_frame():
    direct = numbers(full_catalog().thermals())
    frame = LocalFrame(KHOB[0] + 0.1, KHOB[1])
    other = cl.CloudCatalog(config(), frame, cl.CloudParams(tiles_per_update=1))
    for lat, lon in ((KHOB[0] + 0.3, KHOB[1] - 0.3), (KHOB[0] + 0.1, KHOB[1] - 0.1), KHOB):
        for _ in range(200):
            other.update(NOON, lat, lon)  # interrupted: the tiles come in another order
    while other.update(NOON, *KHOB):
        pass
    assert direct == numbers(other.thermals())


def test_catalog_loads_a_few_tiles_at_a_time_nearest_first():
    catalog = cl.CloudCatalog(config(), LocalFrame(*KHOB), cl.CloudParams(tiles_per_update=2))
    assert catalog.update(NOON, *KHOB)
    assert not catalog._tiles  # working out which ones was enough for one update
    assert catalog.update(NOON, *KHOB)
    assert len(catalog._tiles) == 2
    i0, j0 = math.floor(KHOB[0] / 0.02), math.floor(KHOB[1] / 0.02)
    assert all(abs(i - i0) <= 1 and abs(j - j0) <= 1 for i, j, _ in catalog._tiles)
    while catalog.update(NOON, *KHOB):
        pass
    assert len(catalog._tiles) > 100


def test_catalog_drops_what_is_far_and_follows_the_frame():
    catalog = full_catalog()
    far = (KHOB[0] + 1.0, KHOB[1])
    catalog.update(NOON, *far)
    while catalog.update(NOON, *far):
        pass
    assert all(math.hypot(th.e, th.n) > 50000.0 for th in catalog.thermals())
    frame = LocalFrame(*far)
    catalog.set_frame(frame)
    th = next(catalog.thermals())
    assert (th.e, th.n) == pytest.approx(frame.to_enu(th.lat, th.lon))


# --- a cloud's life -----------------------------------------------------------------

def test_a_young_thermal_has_no_cloud_and_then_one_that_forms_slowly():
    th = make_thermal(birth=0.0, life=1000.0)
    planner = cl.CloudPlanner()
    assert run(planner, [th], 0.0, 0.0, 50.0) == []  # tau 0.05 < form_tau
    assert run(planner, [th], 0.0, 0.0, 100.0) == [(cl.CREATE, th, 1.0)]  # just formed: no hurry
    assert run(planner, [th], 0.0, 0.0, 105.0) == []


def test_a_cloud_a_few_seconds_old_is_not_worth_a_fast_emission():
    """Seen with a step of 5 s, a short fast emission would run on far too long."""
    p = cl.CloudParams()
    th = make_thermal(birth=0.0, life=1000.0)
    planner = cl.CloudPlanner(p)
    age = 0.9 * p.min_fast_s * p.prewarm
    assert run(planner, [th], 0.0, 0.0, 100.0 + age) == [(cl.CREATE, th, 1.0)]
    assert planner.next_change == float("inf")


def test_an_old_cloud_fills_fast_rests_and_settles():
    p = cl.CloudParams()
    th = make_thermal(birth=0.0, life=1000.0)
    planner = cl.CloudPlanner(p)
    t = 500.0  # well past one particle life since it formed
    assert run(planner, [th], 0.0, 0.0, t) == [(cl.CREATE, th, p.prewarm)]
    fill_end = t + p.mean_ttl_s / p.prewarm
    assert planner.next_change == pytest.approx(fill_end)
    assert run(planner, [th], 0.0, 0.0, t + 1.0) == []
    assert run(planner, [th], 0.0, 0.0, fill_end) == [(cl.RATE, th, 0.0)]
    rest_end = fill_end + p.rest_fraction * p.mean_ttl_s
    assert planner.next_change == pytest.approx(rest_end)
    assert run(planner, [th], 0.0, 0.0, rest_end - 1.0) == []
    assert run(planner, [th], 0.0, 0.0, rest_end) == [(cl.RATE, th, 1.0)]
    assert planner.next_change == float("inf")
    assert run(planner, [th], 0.0, 0.0, rest_end + 5.0) == []


def test_a_refill_fills_a_drawn_cloud_fast_rests_and_settles_again():
    # A new instance taking over a cloud that comes nearer (cloud_order.py).
    p = cl.CloudParams()
    th = make_thermal(birth=0.0, life=2000.0)
    planner = cl.CloudPlanner(p)
    run(planner, [th], 0.0, 0.0, 500.0)
    t = 700.0
    run(planner, [th], 0.0, 0.0, t)
    assert planner.shown[th].rate == 1.0 and planner.next_change == float("inf")
    assert planner.refill(th, t) == p.prewarm
    fill_end = t + p.mean_ttl_s / p.prewarm
    assert planner.next_change == pytest.approx(fill_end)
    assert run(planner, [th], 0.0, 0.0, fill_end) == [(cl.RATE, th, 0.0)]
    rest_end = fill_end + p.rest_fraction * p.mean_ttl_s
    assert run(planner, [th], 0.0, 0.0, rest_end) == [(cl.RATE, th, 1.0)]


def test_a_fading_cloud_is_not_refilled():
    p = cl.CloudParams()
    th = make_thermal(birth=0.0, life=1000.0)
    planner = cl.CloudPlanner(p)
    run(planner, [th], 0.0, 0.0, 500.0)
    run(planner, [th], 0.0, 0.0, 700.0)  # past fade_tau: stopped
    assert planner.shown[th].stopped_at is not None
    assert planner.refill(th, 701.0) == 0.0
    assert planner.shown[th].fast_until < 701.0


def alive_particles(th, planner, t0, t1, dt=1.0):
    """How many particles (in units of a steady cloud) the planner's rates keep alive, for
    lives spread evenly over 0.8-1.2 of the mean: (t, alive) from t0 to t1."""
    p = planner.params
    rate, born, out = 0.0, [], []
    t = t0
    while t <= t1:
        for action, _, r in run(planner, [th], 0.0, 0.0, t):
            if action != cl.DESTROY:
                rate = r
        born.append((t, rate * dt / p.mean_ttl_s))
        alive = 0.0
        for when, n in born:
            age = t - when
            shortest, longest = 0.8 * p.mean_ttl_s, 1.2 * p.mean_ttl_s
            alive += n * min(max((longest - age) / (longest - shortest), 0.0), 1.0)
        out.append((t, alive))
        t += dt
    return out


def test_a_filled_cloud_stays_about_as_big_as_a_steady_one():
    th = make_thermal(birth=0.0, life=5000.0)
    curve = alive_particles(th, cl.CloudPlanner(), 1000.0, 1800.0)
    after_fill = [a for t, a in curve if t >= 1012.0]
    assert 0.75 < min(after_fill) and max(after_fill) < 1.45
    assert [a for t, a in curve if t >= 1600.0][-1] == pytest.approx(1.0, abs=0.02)


def test_a_partly_formed_cloud_fills_only_as_far_as_it_should():
    p = cl.CloudParams()
    th = make_thermal(birth=0.0, life=1000.0)
    planner = cl.CloudPlanner(p)
    t = 100.0 + 0.5 * p.mean_ttl_s
    run(planner, [th], 0.0, 0.0, t)
    assert planner.shown[th].fast_until == pytest.approx(t + 0.5 * p.mean_ttl_s / p.prewarm)


def test_a_cloud_fades_with_its_thermal_and_goes_when_nothing_is_left():
    p = cl.CloudParams()
    th = make_thermal(birth=0.0, life=1000.0)
    planner = cl.CloudPlanner(p)
    run(planner, [th], 0.0, 0.0, 100.0)
    assert run(planner, [th], 0.0, 0.0, 699.0) == []
    assert run(planner, [th], 0.0, 0.0, 700.0) == [(cl.RATE, th, 0.0)]
    assert run(planner, [th], 0.0, 0.0, 700.0 + p.ttl_s - 1.0) == []
    assert run(planner, [th], 0.0, 0.0, 700.0 + p.ttl_s) == [(cl.DESTROY, th, 0.0)]
    assert not planner.shown


def test_a_thermal_past_its_feeding_gets_no_new_cloud():
    th = make_thermal(birth=0.0, life=1000.0)
    assert run(cl.CloudPlanner(), [th], 0.0, 0.0, 750.0) == []


def test_the_fade_ends_before_or_about_when_the_thermal_does():
    """The shortest life a cloud can have still fits its fade in the thermal's decay."""
    p = cl.CloudParams()
    th = make_thermal(birth=0.0, life=p.min_life_s)
    _, stop = cl.feeding_window(th, p)
    assert stop + p.ttl_s == pytest.approx(th.death)


# --- range ---------------------------------------------------------------------------

def test_a_far_cloud_uses_fewer_particles_and_gets_the_rest_coming_nearer():
    p = cl.CloudParams()
    th = make_thermal(birth=0.0, life=2000.0, e=15000.0)
    planner = cl.CloudPlanner(p)
    run(planner, [th], 0.0, 0.0, 200.0)  # formed at tau 0.1, t = 200: slow start, far
    assert planner.shown[th].rate == pytest.approx(p.far_rate)
    # Near now: a short fast emission for what is missing, then steady.
    a = run(planner, [th], 15000.0 - p.near_m + 1.0, 0.0, 210.0)
    assert len(a) == 1 and a[0][0] == cl.RATE and a[0][2] > 1.0
    until = planner.shown[th].fast_until
    assert planner.next_change == pytest.approx(until)
    assert until - 210.0 == pytest.approx((1.0 - p.far_rate) * p.mean_ttl_s / p.refill_factor)
    assert run(planner, [th], 15000.0, 0.0, until - 0.1) == []
    assert run(planner, [th], 15000.0, 0.0, until) == [(cl.RATE, th, 1.0)]
    # Far again, past the margin only: it just stops being fed so much.
    assert run(planner, [th], 15000.0 - p.near_m - 500.0, 0.0, until + 5.0) == []
    assert run(planner, [th], 15000.0 - p.near_keep_m - 1.0, 0.0, until + 10.0) == \
        [(cl.RATE, th, p.far_rate)]


def test_leaving_the_range_is_a_fade_and_coming_well_back_feeds_it_again():
    p = cl.CloudParams()
    th = make_thermal(birth=0.0, life=2000.0, e=19000.0)
    planner = cl.CloudPlanner(p)
    run(planner, [th], 0.0, 0.0, 200.0)
    assert run(planner, [th], -1500.0, 0.0, 300.0) == []  # 20.5 km: within the margin
    assert run(planner, [th], -3000.0, 0.0, 310.0) == [(cl.RATE, th, 0.0)]
    # Back inside the keep range but outside the range: still fading.
    assert run(planner, [th], -1500.0, 0.0, 320.0) == []
    assert planner.shown[th].stopped_at == 310.0
    a = run(planner, [th], 0.0, 0.0, 330.0)
    assert len(a) == 1 and a[0][0] == cl.RATE and a[0][2] == pytest.approx(p.far_rate)
    assert planner.shown[th].stopped_at is None


def test_a_glider_circling_on_the_limit_does_not_thicken_a_cloud():
    p = cl.CloudParams()
    th = make_thermal(birth=200.0, life=5000.0, e=p.keep_range_m + 100.0)  # just formed
    planner = cl.CloudPlanner(p)
    run(planner, [th], 1500.0, 0.0, 700.0)  # in range
    actions = []
    for k in range(600):
        t = 701.0 + k
        e = 150.0 * math.cos(2.0 * math.pi * k / 40.0)
        actions += [a for a, _, _ in run(planner, [th], e, 0.0, t)]
    assert actions == [cl.RATE, cl.DESTROY]  # stopped once, and gone a particle life later


def test_fed_again_soon_only_replaces_what_went():
    p = cl.CloudParams()
    th = make_thermal(birth=0.0, life=2000.0, e=19000.0)
    planner = cl.CloudPlanner(p)
    run(planner, [th], 0.0, 0.0, 200.0)
    run(planner, [th], -3000.0, 0.0, 300.0)
    a = run(planner, [th], 0.0, 0.0, 305.0)
    assert a == [(cl.RATE, th, pytest.approx(p.far_rate))]
    assert planner.next_change == float("inf")


def test_new_clouds_come_a_few_at_a_time():
    p = cl.CloudParams(max_new=2)
    thermals = [make_thermal(birth=0.0, life=2000.0, e=100.0 * i) for i in range(5)]
    planner = cl.CloudPlanner(p)
    assert len(run(planner, thermals, 0.0, 0.0, 700.0)) == 2 and planner.more_waiting
    assert len([a for a in run(planner, thermals, 0.0, 0.0, 701.0) if a[0] == cl.CREATE]) == 2
    assert len([a for a in run(planner, thermals, 0.0, 0.0, 702.0) if a[0] == cl.CREATE]) == 1
    assert not planner.more_waiting


def test_new_clouds_are_created_last_and_the_nearest_first():
    # X-Plane draws the newest instance underneath (cloud_order.py).
    p = cl.CloudParams(max_new=3)
    thermals = [make_thermal(birth=0.0, life=2000.0, e=d) for d in (5000.0, -1000.0, 9000.0, 3000.0, -7000.0)]
    planner = cl.CloudPlanner(p)
    first = run(planner, thermals, 0.0, 0.0, 700.0)
    assert [th.e for _, th, _ in first] == [-1000.0, 3000.0, 5000.0]
    second = run(planner, thermals, 0.0, 0.0, 701.0)
    assert [th.e for a, th, _ in second if a == cl.CREATE] == [-7000.0, 9000.0]
    assert all(a == cl.CREATE for a, _, _ in second[-2:])


def test_a_cloud_whose_tile_was_dropped_fades_instead_of_vanishing():
    p = cl.CloudParams()
    th = make_thermal(birth=0.0, life=2000.0)
    planner = cl.CloudPlanner(p)
    run(planner, [th], 0.0, 0.0, 700.0)
    assert run(planner, [], 0.0, 0.0, 701.0) == [(cl.RATE, th, 0.0)]
    assert run(planner, [], 0.0, 0.0, 701.0 + p.ttl_s - 1.0) == []
    assert run(planner, [], 0.0, 0.0, 701.0 + p.ttl_s) == [(cl.DESTROY, th, 0.0)]
    assert not planner.shown


def test_the_plan_does_not_depend_on_how_the_catalog_was_loaded():
    params = cl.CloudParams(max_new=10000)

    def plan(catalog):
        actions = cl.CloudPlanner(params).step(catalog.thermals(), 0.0, 0.0, NOON)
        assert len(actions) > 20
        return [(a, th.lat, th.lon, rate) for a, th, rate in actions]

    other = cl.CloudCatalog(config(), LocalFrame(*KHOB), cl.CloudParams(tiles_per_update=1))
    for _ in range(200):
        other.update(NOON, KHOB[0] + 0.2, KHOB[1] + 0.2)
    while other.update(NOON, *KHOB):
        pass
    assert plan(full_catalog(params)) == plan(other)


def test_scale_follows_the_thermal_within_limits():
    assert cl.cloud_scale(make_thermal(wgain=cl.SCALE_WR, rgain=1.0)) == 1.0
    assert cl.cloud_scale(make_thermal(wgain=0.1, rgain=0.1)) == cl.SCALE_RANGE[0]
    assert cl.cloud_scale(make_thermal(wgain=9.0, rgain=9.0)) == cl.SCALE_RANGE[1]


# --- assets --------------------------------------------------------------------------

def gen_module():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "tools"))
    try:
        import make_cloud_objs as gen
    finally:
        sys.path.pop(0)
    return gen


def test_assets_match_their_generator():
    gen = gen_module()
    files = gen.outputs()
    assert set(os.listdir(gen.OUT_DIR)) == set(files)
    for name, data in files.items():
        with open(os.path.join(gen.OUT_DIR, name), "rb") as f:
            on_disk = f.read()
        if name.endswith(".png"):  # the same pixels: compression depends on the Pillow version
            on_disk, data = (Image.open(io.BytesIO(d)).tobytes() for d in (on_disk, data))
        assert on_disk == data, name


def test_the_planner_agrees_with_the_assets():
    gen = gen_module()
    p = cl.CloudParams()
    assert p.ttl_s == pytest.approx(gen.TTL_S * (1.0 + gen.TTL_SPREAD))
    assert p.mean_ttl_s == gen.TTL_S
    assert 1.0 + p.refill_factor <= gen.RATE_TOP
    assert p.prewarm == gen.RATE_TOP
    assert cl.SCALE_RANGE[1] <= gen.SCALE_TOP


def test_puffs_fade_out_before_the_edge_of_their_cell():
    gen = gen_module()
    atlas = gen.texture()
    alpha = atlas.getchannel("A")
    for k in range(gen.CELLS + 1):
        at = min(k * gen.CELL_PX, atlas.width - 1)
        assert max(alpha.crop((at, 0, at + 1, atlas.height)).get_flattened_data()) == 0
        assert max(alpha.crop((0, at, atlas.width, at + 1)).get_flattened_data()) == 0


# --- how high ------------------------------------------------------------------------

def test_with_no_wind_the_ground_is_read_only_under_the_cloud():
    points = cl.ground_points(KHOB[0], KHOB[1], 500.0, 0.0, 0.0, 1000.0)
    assert len(points) == 5 and points[0] == (KHOB[0], KHOB[1])
    frame = LocalFrame(KHOB[0], KHOB[1])
    offsets = sorted(tuple(round(v) for v in frame.to_enu(*p)) for p in points)
    assert offsets == [(-500, 0), (0, -500), (0, 0), (0, 500), (500, 0)]


def test_in_wind_the_ground_is_read_along_three_lanes_of_the_drift():
    points = cl.ground_points(KHOB[0], KHOB[1], 500.0, 15.0, 0.0, 1000.0)  # toward the east
    assert len(points) == 5 + 3 * 15
    frame = LocalFrame(KHOB[0], KHOB[1])
    last = sorted(tuple(round(v) for v in frame.to_enu(*p)) for p in points[-3:])
    assert last == [(15000, -500), (15000, 0), (15000, 500)]
    # No gap between readings along the way, whichever way the wind blows.
    east = sorted(frame.to_enu(*p)[0] for p in points[5::3])
    assert max(b - a for a, b in zip(east, east[1:])) <= cl.GROUND_STEP_M + 1.0


def test_a_cloud_is_at_the_level_unless_the_ground_asks_for_more():
    assert cl.cloud_base_m(2000.0, [500.0, 1000.0]) == 2000.0
    assert cl.cloud_base_m(2000.0, [500.0, 1700.0]) == 2000.0
    assert cl.cloud_base_m(2000.0, [500.0, 1701.0]) == 2001.0
    assert cl.cloud_base_m(2000.0, [3000.0, 500.0], margin_m=100.0) == 3100.0


def test_ground_that_cannot_be_read_is_left_out():
    assert cl.cloud_base_m(2000.0, [None, 3000.0, None]) == 3300.0
    assert cl.cloud_base_m(2000.0, [None, None]) == 2000.0


def test_a_cloud_lasts_one_particle_life_after_it_stops_being_fed_but_not_past_its_thermal():
    p = cl.CloudParams(fade_tau=0.7, ttl_s=216.0)
    assert cl.cloud_seconds_left(make_thermal(birth=0.0, life=1000.0), 100.0, p) == 816.0
    assert cl.cloud_seconds_left(make_thermal(birth=0.0, life=500.0), 100.0, p) == 400.0
    assert cl.cloud_seconds_left(make_thermal(birth=0.0, life=500.0), 600.0, p) == 0.0
