"""Allen (2006) model: check case from the paper, then the engine's deviations."""

import math

import pytest

from xp_gliding.engine import updraft as u

# Paper check case (Section VI, Appendix A): mean day, z/zi = 0.2,
# five updrafts on the diagonal of a 1000 m x 1000 m area.
WSTAR, ZI, Z = 2.56, 1401.0, 280.0
AREA = 1000.0 * 1000.0


def check_case_profile(**options):
    r2 = u.mean_outer_radius(Z / ZI, ZI)
    n = round(0.6 * AREA / (ZI * r2))
    at = n * math.pi * r2 ** 2
    we = -(at * u.mean_updraft(Z / ZI, WSTAR)) / (AREA - at)
    centres = [k * 1000.0 / (n + 1) for k in range(1, n + 1)]
    # Fig. 12: cross-section at x = 170 m, y = 0..390 m, nearest updraft.
    profile = {}
    for y in range(0, 400, 10):
        r = min(math.hypot(170.0 - c, y - c) for c in centres)
        profile[y] = u.updraft_velocity(r, Z, ZI, WSTAR, we=we, **options)
    return r2, n, we, profile


def test_paper_check_case_numbers():
    r2, n, we, _ = check_case_profile()
    assert r2 == pytest.approx(79.4, abs=0.05)  # "yielded 79.4 m"
    assert n == 5  # "was five"
    assert we == pytest.approx(-0.128, abs=0.001)  # Fig. 12 far field


def test_paper_fig12_exact_mode():
    # Values read from the paper's Fig. 12 (grid of 0.5 m/s, read to ~0.03).
    _, _, _, w = check_case_profile(blend_shapes=False, stretch_everywhere=False)
    read_from_fig12 = {80: -0.11, 90: 0.12, 100: 0.45, 140: 2.41, 150: 2.63,
                       170: 2.72, 200: 2.15, 230: 0.57, 250: -0.04, 300: -0.13}
    for y, expected in read_from_fig12.items():
        assert w[y] == pytest.approx(expected, abs=0.03), y


def test_default_mode_stays_close_to_paper():
    _, _, _, exact = check_case_profile(blend_shapes=False, stretch_everywhere=False)
    _, _, _, smooth = check_case_profile()
    assert max(abs(exact[y] - smooth[y]) for y in exact) < 0.1
    assert smooth[170] == pytest.approx(exact[170], abs=0.01)


def test_fig10_profiles_without_environment_sink():
    # Fig. 10 (w* 2.56, zi 1401, no environment sink): centre values and the
    # ~ -0.1 m/s ring at z/zi = 0.6 and 0.8.
    centre = {0.2: 2.74, 0.4: 2.43, 0.6: 1.67, 0.8: 0.65}
    for zzi, expected in centre.items():
        w0 = u.updraft_velocity(0.0, zzi * ZI, ZI, WSTAR, blend_shapes=False)
        assert w0 == pytest.approx(expected, abs=0.05), zzi
    for zzi in (0.6, 0.8):
        ring = min(u.updraft_velocity(r, zzi * ZI, ZI, WSTAR) for r in range(100, 250, 2))
        assert ring == pytest.approx(-0.1, abs=0.03), zzi
    ring_low = min(u.updraft_velocity(r, 0.4 * ZI, ZI, WSTAR) for r in range(100, 250, 2))
    assert ring_low == 0.0  # no toroid below z/zi = 0.5


def test_mean_updraft_shape():
    # Eq. 11: maximum ~0.45 w* "at approximately 0.25" (exactly z/zi = 1/4.4),
    # negative above 1/1.1.
    best = max((u.mean_updraft(k / 1000, 1.0), k / 1000) for k in range(1, 1000))
    assert best[0] == pytest.approx(0.45, abs=0.01)
    assert best[1] == pytest.approx(1 / 4.4, abs=0.001)
    assert u.mean_updraft(0.92, 1.0) < 0.0 < u.mean_updraft(0.9, 1.0)


def test_outside_layer_is_zero():
    for z in (-10.0, 0.0, ZI, ZI + 500.0):
        assert u.updraft_velocity(0.0, z, ZI, WSTAR, we=-0.2) == 0.0
    assert u.environment_sink(ZI + 1.0, ZI, WSTAR, 1e-6) == 0.0


def test_blended_shapes_are_continuous_in_height():
    # Climbing through a shape-table boundary must not make lift jump. On the
    # mean day r2 crosses the first boundary (r1/r2 = 0.195) at z ~ 62 m, where
    # the paper's nearest-row rule jumps by ~0.17 m/s at r = 30 m.
    r = 30.0
    zs = [20.0 + k * 0.25 for k in range(800)]
    w = [u.updraft_velocity(r, z, ZI, WSTAR) for z in zs]
    assert max(abs(b - a) for a, b in zip(w, w[1:])) < 0.01
    jumps = [u.updraft_velocity(r, z, ZI, WSTAR, blend_shapes=False) for z in zs]
    assert max(abs(b - a) for a, b in zip(jumps, jumps[1:])) > 0.1


def test_stretch_everywhere_removes_step_at_core_radius():
    zzi = 0.3
    r2 = u.mean_outer_radius(zzi, ZI)
    r1 = u.core_ratio(r2) * r2
    we = -0.3
    inside = u.updraft_velocity(r1 - 1e-6, zzi * ZI, ZI, WSTAR, we=we)
    outside = u.updraft_velocity(r1 + 1e-6, zzi * ZI, ZI, WSTAR, we=we)
    assert inside == pytest.approx(outside, abs=1e-4)
    paper_in = u.updraft_velocity(r1 - 1e-6, zzi * ZI, ZI, WSTAR, we=we, stretch_everywhere=False)
    paper_out = u.updraft_velocity(r1 + 1e-6, zzi * ZI, ZI, WSTAR, we=we, stretch_everywhere=False)
    assert abs(paper_in - paper_out) > 1e-3


def test_influence_radius_covers_the_profile():
    for zzi in (0.1, 0.3, 0.6, 0.85):
        z = zzi * ZI
        reach = u.influence_radius(z, ZI)
        we = -0.2
        assert u.updraft_velocity(reach, z, ZI, WSTAR, we=we) == pytest.approx(we, abs=1e-9)
        assert u.updraft_velocity(reach * 2, z, ZI, WSTAR, we=we) == pytest.approx(we, abs=1e-9)
