import math
import random
import time

import pytest

from xp_gliding.engine.rope import Rope


def _dist(p, q):
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(p, q)))


def _settle(rope, a, b, seconds=20.0, dt=1 / 60, **kw):
    for _ in range(int(seconds / dt)):
        rope.step(dt, a, b, **kw)


def _catenary_sag(span, length):
    """Sag of a uniform chain hanging between two points at one height."""
    # length = 2 c sinh(span / 2c); solve for c by bisection, sag = c (cosh(span / 2c) - 1).
    lo, hi = 1e-3, 1e6
    for _ in range(200):
        c = math.sqrt(lo * hi)
        if 2 * c * math.sinh(span / (2 * c)) > length:
            lo = c
        else:
            hi = c
    return c * (math.cosh(span / (2 * c)) - 1)


def test_a_slack_rope_hangs_as_a_catenary():
    rope = Rope(length_m=60.0, segments=20)
    a, b = (0.0, 0.0, 100.0), (50.0, 0.0, 100.0)
    rope.reset(a, b)
    _settle(rope, a, b, seconds=40.0)
    lowest = min(p[2] for p in rope.nodes)
    expected = _catenary_sag(50.0, 60.0)
    assert 100.0 - lowest == pytest.approx(expected, rel=0.08)
    # Hanging still, every segment at its rest length.
    for p, q in zip(rope.nodes, rope.nodes[1:]):
        assert _dist(p, q) == pytest.approx(3.0, abs=0.05)


def test_a_taut_rope_is_straight():
    rope = Rope(length_m=60.0, segments=20)
    a, b = (0.0, 0.0, 300.0), (0.0, 60.0, 302.0)
    rope.reset(a, b)
    _settle(rope, a, b, seconds=5.0)
    for i, p in enumerate(rope.nodes):
        f = i / 20
        on_line = (0.0, 60.0 * f, 300.0 + 2.0 * f)
        assert _dist(p, on_line) < 0.6  # a few dm of sag at most, as a real taut rope


def test_ends_farther_apart_than_the_rope_stretch_it_straight():
    rope = Rope(length_m=60.0, segments=20)
    a, b = (0.0, 0.0, 300.0), (0.0, 66.0, 300.0)
    rope.reset(a, b)
    _settle(rope, a, b, seconds=5.0)
    assert all(abs(p[0]) < 1e-6 and p[2] > 299.8 for p in rope.nodes)
    gaps = [_dist(p, q) for p, q in zip(rope.nodes, rope.nodes[1:])]
    assert max(gaps) == pytest.approx(3.3, abs=0.02)


def test_a_rope_with_its_ends_close_lies_on_the_ground():
    rope = Rope(length_m=60.0, segments=20)
    a, b = (0.0, 0.0, 0.5), (0.0, 40.0, 1.0)
    rope.reset(a, b)
    _settle(rope, a, b, seconds=10.0, ground_up=0.0)
    assert all(p[2] >= 0.0 for p in rope.nodes)
    on_ground = sum(1 for p in rope.nodes if p[2] < 0.01)
    assert on_ground >= 10
    assert all(math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2) < 0.05 for v in rope._vel)


def test_after_release_the_free_end_trails_behind_and_below():
    rope = Rope(length_m=60.0, segments=20)
    speed = 33.0  # the tug flies north
    a, b = (0.0, 60.0, 500.0), (0.0, 0.0, 500.0)
    rope.reset(a, b)
    rope.release_b()
    dt = 1 / 60
    for k in range(int(20 / dt)):
        a = (0.0, 60.0 + speed * (k + 1) * dt, 500.0)
        rope.step(dt, a, None, rho=1.1)
    tail = rope.nodes[-1]
    assert tail[1] < a[1] - 30.0  # behind the tug
    assert tail[2] < a[2] - 5.0  # and hanging, though the air holds it out
    assert tail[2] > a[2] - 60.0


def test_the_wind_blows_a_hanging_rope_downwind():
    rope = Rope(length_m=60.0, segments=20)
    a, b = (0.0, 0.0, 100.0), (50.0, 0.0, 100.0)
    rope.reset(a, b)
    _settle(rope, a, b, seconds=30.0, wind=(0.0, 10.0, 0.0))
    middle = rope.nodes[10]
    assert middle[1] > 2.0


def test_no_blow_up_at_any_frame_rate_or_motion():
    rng = random.Random(7)
    for dt in (1 / 15, 1 / 30, 1 / 60, 1 / 144, 1 / 250):
        rope = Rope()
        a, b = [0.0, 0.0, 10.0], [0.0, 55.0, 10.0]
        rope.reset(a, b)
        t = 0.0
        while t < 15.0:
            t += dt
            for p in (a, b):
                p[0] += rng.uniform(-1, 1) * 30 * dt
                p[1] += 30.0 * dt + rng.uniform(-1, 1) * 10 * dt
                p[2] += rng.uniform(-1, 1) * 10 * dt
            # keep the ends within the rope's reach now and then, beyond it at other times
            rope.step(dt, tuple(a), tuple(b), ground_up=0.0, wind=(3.0, -2.0, 0.0))
            for p in rope.nodes:
                assert all(math.isfinite(c) for c in p)
                assert p[2] >= -1e-9
        span = _dist(a, b)
        rest = max(60.0, span) / 20
        for p, q in zip(rope.nodes, rope.nodes[1:]):
            assert _dist(p, q) < rest * 1.15


def test_shift_moves_everything():
    rope = Rope()
    a, b = (0.0, 0.0, 100.0), (0.0, 50.0, 100.0)
    rope.reset(a, b)
    _settle(rope, a, b, seconds=2.0)
    before = [list(p) for p in rope.nodes]
    rope.shift(1000.0, -500.0, 0.0)
    a2, b2 = (1000.0, -500.0, 100.0), (1000.0, -450.0, 100.0)
    rope.step(1 / 60, a2, b2)
    for p, q in zip(before, rope.nodes):
        assert _dist((p[0] + 1000.0, p[1] - 500.0, p[2]), q) < 0.5


def test_segment_poses_point_along_the_rope():
    rope = Rope(length_m=10.0, segments=2)
    rope.reset((0.0, 0.0, 0.0), (10.0, 0.0, 0.0))
    poses = rope.segment_poses()
    assert len(poses) == 2
    x, y, up, length, heading, pitch = poses[0]
    assert (x, y, up) == pytest.approx((2.5, 0.0, 0.0))
    assert length == pytest.approx(5.0)
    assert heading == pytest.approx(90.0)  # toward +x, east
    assert pitch == pytest.approx(0.0)
    rope.reset((0.0, 0.0, 0.0), (0.0, 0.0, -10.0))
    assert rope.segment_poses()[0][5] == pytest.approx(-90.0)


def test_cost_per_frame():
    rope = Rope()
    a, b = (0.0, 0.0, 100.0), (0.0, 50.0, 100.0)
    rope.reset(a, b)
    frames = 300
    start = time.perf_counter()
    for k in range(frames):
        rope.step(1 / 60, a, (0.0, 50.0 + 0.01 * k, 100.0), ground_up=0.0)
    per_frame_ms = (time.perf_counter() - start) / frames * 1e3
    assert per_frame_ms < 2.0  # generous for slow CI; measured locally below


def test_bad_arguments():
    with pytest.raises(ValueError):
        Rope(length_m=0.0)
    with pytest.raises(ValueError):
        Rope(segments=0)
    rope = Rope()
    rope.step(0.0, (0, 0, 0), (0, 1, 0))  # nothing happens, no error
    rope.step(float("nan"), (0, 0, 0), (0, 1, 0))


def test_slack_on_the_ground_curves_and_keeps_its_segments_whole():
    rope = Rope(length_m=53.0, segments=20)
    a, b = (0.0, 0.0, 0.3), (0.0, 46.0, 0.5)
    rope.reset(a, b)
    rest = 53.0 / 20
    for p, q in zip(rope.nodes, rope.nodes[1:]):
        assert _dist(p, q) == pytest.approx(rest, rel=0.02)  # laid out at full length
    for k in range(600):
        b = (0.0, 46.0 + 0.002 * k, 0.5)  # the tug creeps forward
        rope.step(1 / 60, a, b, ground_up=0.0)
    for p, q in zip(rope.nodes, rope.nodes[1:]):
        assert _dist(p, q) > 0.9 * rest
    for p, q, r in zip(rope.nodes, rope.nodes[1:], rope.nodes[2:]):
        u = [qi - pi for pi, qi in zip(p, q)]
        v = [ri - qi for qi, ri in zip(q, r)]
        cos = sum(x * y for x, y in zip(u, v)) / (_dist(p, q) * _dist(q, r))
        assert cos > math.cos(math.radians(85))  # no sharp kink
    assert max(abs(p[0]) for p in rope.nodes) > 2.0  # the slack went sideways
    assert all(p[2] < 0.6 for p in rope.nodes)  # lying down


def test_overrun_in_the_air_makes_a_bow_below():
    rope = Rope(length_m=53.0, segments=20)
    a, b = (0.0, 0.0, 500.0), (0.0, 56.0, 500.0)
    rope.reset(a, b)
    for k in range(120):  # the glider gains 15 m on the tug in 2 s
        a = (0.0, 15.0 * k / 120, 500.0)
        rope.step(1 / 60, a, b, rho=1.1)
    middle = rope.nodes[10]
    assert middle[2] < 499.0
    for p, q in zip(rope.nodes, rope.nodes[1:]):
        assert _dist(p, q) > 0.9 * 53.0 / 20
