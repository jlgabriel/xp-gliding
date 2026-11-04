import io
import math
import os
import sys

import pytest
from PIL import Image

from xp_gliding.engine import markers as mk
from xp_gliding.engine import updraft
from xp_gliding.engine.field import FieldConfig, ThermalField
from xp_gliding.engine.geo import LocalFrame

KHOB = (32.6875, -103.2170)
WSTAR, ZI = 3.0, 2000.0
NOON = 19 * 3600.0


@pytest.fixture
def field():
    f = ThermalField(FieldConfig(seed=1, day=306), LocalFrame(*KHOB))
    f.update(NOON, *KHOB)
    return f


def test_core_radii_are_the_ones_the_profile_uses():
    r1, r2 = updraft.core_radii(800.0, ZI, 1.2)
    assert r2 == pytest.approx(updraft.mean_outer_radius(0.4, ZI) * 1.2)
    assert r1 == pytest.approx(updraft.core_ratio(r2) * r2)
    assert updraft.core_radii(0.0, ZI) == (0.0, 0.0)
    assert updraft.core_radii(ZI, ZI) == (0.0, 0.0)


def test_alive_within_matches_a_full_scan(field):
    found = field.alive_within(500.0, -300.0, NOON, 2000.0)
    expected = {th for th in field.alive(NOON) if math.hypot(th.e - 500.0, th.n + 300.0) <= 2000.0}
    assert {th for th, _ in found} == expected and expected
    for th, r in found:
        assert r == pytest.approx(math.hypot(th.e - 500.0, th.n + 300.0))


def test_core_is_the_lift_of_a_lone_thermal(field):
    z = 800.0
    we = field.environment_sink(z, WSTAR, ZI)
    th = field.nearest(0.0, 0.0, NOON, 5000.0)[0]
    core, r1 = mk.core_of(th, z, NOON, WSTAR, ZI, we)
    # Alone in the field, lift_at at its centre is this core.
    lone = ThermalField(field.config, field.frame)
    lone._grid_add(th)
    assert core == pytest.approx(lone.lift_at(th.e, th.n, z, NOON, WSTAR, ZI), abs=1e-9)
    assert r1 > 0.0
    assert mk.core_of(th, z, th.death + 1.0, WSTAR, ZI, we) == (we, 0.0)


def test_selection_respects_the_limits_and_is_deterministic(field):
    params = mk.MarkerParams()
    chosen = mk.select_markers(field, 0.0, 0.0, 800.0, NOON, WSTAR, ZI)
    assert 0 < len(chosen) <= params.max_count
    for m in chosen:
        assert m.distance_m <= params.range_m and m.core_ms >= params.min_core_ms
        assert m.r1_m > 0.0
    scores = [m.core_ms - params.cost_ms_per_m * m.distance_m for m in chosen]
    assert scores == sorted(scores, reverse=True)
    again = mk.select_markers(field, 0.0, 0.0, 800.0, NOON, WSTAR, ZI)
    assert [m.thermal for m in again] == [m.thermal for m in chosen]


def test_nothing_is_marked_outside_the_layer_or_above_the_lift(field):
    assert mk.select_markers(field, 0.0, 0.0, 0.0, NOON, WSTAR, ZI) == []
    assert mk.select_markers(field, 0.0, 0.0, ZI + 1.0, NOON, WSTAR, ZI) == []
    assert mk.select_markers(field, 0.0, 0.0, 800.0, NOON, WSTAR, 0.0) == []
    assert mk.select_markers(field, 0.0, 0.0, 0.98 * mk.TOP_ZZI * ZI, NOON, WSTAR, ZI) == []


def test_a_shown_marker_is_kept_past_the_limits_for_a_new_one(field):
    params = mk.MarkerParams(max_count=1000)
    near = {m.thermal: m for m in mk.select_markers(field, 0.0, 0.0, 800.0, NOON, WSTAR, ZI, (),
                                                    params)}
    edge = next(m for m in near.values() if m.distance_m > 2800.0)
    # Move away so that it is 3100 m off: outside range_m, inside keep_range_m.
    dx, dy = edge.thermal.e, edge.thermal.n
    d = math.hypot(dx, dy)
    e, n = -dx / d * (3100.0 - d), -dy / d * (3100.0 - d)
    fresh = mk.select_markers(field, e, n, 800.0, NOON, WSTAR, ZI, (), params)
    assert edge.thermal not in {m.thermal for m in fresh}
    kept = mk.select_markers(field, e, n, 800.0, NOON, WSTAR, ZI, near, params)
    assert edge.thermal in {m.thermal for m in kept}


def test_sticky_ranking_does_not_swap_similar_thermals(field):
    params = mk.MarkerParams(max_count=5)
    first = mk.select_markers(field, 0.0, 0.0, 800.0, NOON, WSTAR, ZI, (), params)
    shown = {m.thermal for m in first}
    # 200 m further on, with the same thermals shown, the same five remain.
    moved = mk.select_markers(field, 200.0, 0.0, 800.0, NOON, WSTAR, ZI, shown, params)
    assert {m.thermal for m in moved} == shown


def test_the_thermal_being_circled_is_not_ranked_out(field):
    all_near = mk.select_markers(field, 0.0, 0.0, 800.0, NOON, WSTAR, ZI, (),
                                 mk.MarkerParams(max_count=1000))
    weakest_close = min((m for m in all_near if m.distance_m <= 500.0), key=lambda m: m.core_ms)
    th = weakest_close.thermal
    # With room for few, the weakest thermal nearby loses its place unless it is shown.
    small = mk.MarkerParams(max_count=3)
    assert th not in {m.thermal for m in mk.select_markers(field, 0.0, 0.0, 800.0, NOON, WSTAR, ZI,
                                                           (), small)}
    assert th in {m.thermal for m in mk.select_markers(field, 0.0, 0.0, 800.0, NOON, WSTAR, ZI,
                                                       {th}, small)}
    # Not when it is far away: there the sticky bonus is all it gets.
    d = math.hypot(th.e, th.n)
    far = mk.MarkerParams(max_count=3, protect_m=d / 2.0)
    assert th not in {m.thermal for m in mk.select_markers(field, 0.0, 0.0, 800.0, NOON, WSTAR, ZI,
                                                           {th}, far)}


def test_marker_goes_when_the_thermal_fades(field):
    params = mk.MarkerParams()
    chosen = mk.select_markers(field, 0.0, 0.0, 800.0, NOON, WSTAR, ZI, (), params)
    th = min(chosen, key=lambda m: m.thermal.death).thermal
    shown = {th}
    assert th in {m.thermal for m in mk.select_markers(field, 0.0, 0.0, 800.0, NOON, WSTAR, ZI,
                                                       shown, params)}
    late = th.death - 1.0  # the life-cycle envelope is ~0 here
    assert th not in {m.thermal for m in mk.select_markers(field, 0.0, 0.0, 800.0, late, WSTAR, ZI,
                                                           shown, params)}


def test_size_class_is_the_nearest_with_a_margin():
    assert mk.SIZES_M[mk.size_class(38.0)] == 40.0
    assert mk.SIZES_M[mk.size_class(4.0)] == 10.0
    assert mk.SIZES_M[mk.size_class(400.0)] == 112.0
    boundary = 40.0 * math.sqrt(math.sqrt(2.0))  # geometric middle of 40 and 56
    assert mk.SIZES_M[mk.size_class(boundary * 1.02)] == 56.0
    assert mk.SIZES_M[mk.size_class(boundary * 1.02, previous=4)] == 40.0
    assert mk.SIZES_M[mk.size_class(boundary * 1.2, previous=4)] == 56.0


def test_strength_class_has_limits_with_a_margin():
    assert [mk.strength_class(w) for w in (1.5, 2.5, 3.5, 4.5)] == [0, 1, 2, 3]
    assert mk.strength_class(2.05) == 1
    assert mk.strength_class(2.05, previous=0) == 0
    assert mk.strength_class(2.3, previous=0) == 1
    assert mk.strength_class(1.9, previous=1) == 1
    assert mk.strength_class(1.7, previous=1) == 0
    assert mk.strength_class(9.0, previous=3) == 3
    assert mk.strength_class(-1.0, previous=0) == 0


def test_assets_match_their_generator():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "tools"))
    try:
        import make_marker_objs as gen
    finally:
        sys.path.pop(0)
    files = gen.outputs()
    assert set(os.listdir(gen.OUT_DIR)) == set(files)
    for name, data in files.items():
        with open(os.path.join(gen.OUT_DIR, name), "rb") as f:
            on_disk = f.read()
        if name.endswith(".png"):  # the same pixels: compression depends on the Pillow version
            on_disk, data = (Image.open(io.BytesIO(d)).tobytes() for d in (on_disk, data))
        assert on_disk == data, name
    for strength in range(mk.STRENGTH_COUNT):
        assert mk.column_object(strength) + ".obj" in files
        for size in range(len(mk.SIZES_M)):
            assert mk.ring_object(size, strength) + ".obj" in files
