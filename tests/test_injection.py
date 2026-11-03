import math

import pytest

from xp_gliding.engine import injection as inj

# Schleicher ASK 21: span 17.0 m, wing area 17.95 m2 (aspect ratio 16.1).
SPAN, AREA = 17.0, 17.95


def test_energy_force_delivers_the_power_of_rising_air():
    m, w, v = 520.0, 1.5, 25.0
    force = inj.energy_force(m, w, v)
    assert force * v == pytest.approx(m * inj.G * w)  # P = F V = m g w
    assert inj.energy_force(m, w, 5.0) == 0.0  # no injection on the ground


def test_climb_gain_does_not_depend_on_speed_or_glider():
    # Point-mass glide at constant airspeed: the extra power F V raises the
    # energy height h + V^2/2g by exactly w per second, for any mass and speed.
    for m, v in ((380.0, 22.0), (520.0, 25.0), (600.0, 40.0)):
        w = 2.0
        gain = inj.energy_force(m, w, v) * v / (m * inj.G)
        assert gain == pytest.approx(w)


def test_path_force_body_keeps_magnitude_and_direction():
    fwd, right, up = inj.path_force_body(100.0, 0.0, 0.0)
    assert (fwd, right, up) == pytest.approx((100.0, 0.0, 0.0))
    fwd, right, up = inj.path_force_body(100.0, 6.0, 2.0)
    assert math.sqrt(fwd ** 2 + right ** 2 + up ** 2) == pytest.approx(100.0)
    assert up < 0.0  # nose above the velocity: the velocity points below the body axis
    assert right > 0.0


def test_lift_slope_and_roll_damping():
    ar = SPAN ** 2 / AREA
    cla = inj.lift_slope(ar)
    assert 5.0 < cla < 2 * math.pi
    assert inj.lift_slope(1e6) == pytest.approx(2 * math.pi, rel=1e-3)
    assert inj.roll_damping(ar, taper=1.0) == pytest.approx(-cla / 6)
    assert inj.roll_damping(ar, taper=0.0) == pytest.approx(-cla / 12)


def test_roll_moment_sign_and_strip_theory_value():
    clp = inj.roll_damping(SPAN ** 2 / AREA, taper=1.0)
    # More lift under the right wing: right wing rises, i.e. roll left (negative).
    moment = inj.gust_roll_moment(1.225, 25.0, AREA, SPAN, 0.1, clp)
    assert moment < 0.0
    # Direct strip integration over a rectangular wing with the same lift slope.
    cla = inj.lift_slope(SPAN ** 2 / AREA)
    chord = AREA / SPAN
    q = 0.5 * 1.225 * 25.0 ** 2
    steps = 20000
    dy = SPAN / steps
    strip = 0.0
    for k in range(steps):
        y = -SPAN / 2 + (k + 0.5) * dy
        dlift = q * chord * cla * (0.1 * y / 25.0) * dy
        strip += -y * dlift
    assert moment == pytest.approx(strip, rel=1e-6)


def test_sample_geometry_level_and_banked():
    geo = inj.SampleGeometry(SPAN, tail_arm_m=6.0)
    geo.update(100.0, 200.0, 500.0, heading_deg=0.0, roll_deg=0.0)  # north
    assert (geo.re, geo.rn, geo.rz) == pytest.approx((108.5, 200.0, 500.0))
    assert (geo.le, geo.ln) == pytest.approx((91.5, 200.0))
    assert (geo.te, geo.tn) == pytest.approx((100.0, 194.0))
    geo.update(0.0, 0.0, 500.0, heading_deg=90.0, roll_deg=30.0)  # east, right bank
    assert (geo.re, geo.rn) == pytest.approx((0.0, -8.5 * math.cos(math.radians(30))), abs=1e-9)
    assert geo.rz == pytest.approx(500.0 - 8.5 * 0.5)
    assert geo.lz == pytest.approx(500.0 + 8.5 * 0.5)
    assert (geo.te, geo.tn) == pytest.approx((-6.0, 0.0), abs=1e-9)


def test_bank_attenuates_the_gradient_through_geometry():
    # A horizontal gradient of w toward the east; flying north, right wing east.
    def w_at(e):
        return 0.02 * e

    geo = inj.SampleGeometry(SPAN, 6.0)
    grads = []
    for bank in (0.0, 30.0, 60.0):
        geo.update(0.0, 0.0, 500.0, 0.0, bank)
        grads.append(inj.span_gradient(w_at(geo.le), w_at(geo.re), SPAN))
    assert grads[0] == pytest.approx(0.02)
    assert grads[1] == pytest.approx(0.02 * math.cos(math.radians(30)))
    assert grads[2] == pytest.approx(0.01)


def test_span_average():
    assert inj.span_average(1.0, 1.0, 1.0) == 1.0
    assert inj.span_average(0.0, 3.0, 0.0) == 2.0


def test_helix_gradient_is_the_spanwise_change_of_w_over_v():
    # A station at y sees its angle of attack drop by w / V(y), V(y) = V - r y;
    # the gradient of that drop at y = 0, times V, is -w r / V: the correction is +w r / V.
    w, r, v, dy = 2.0, 0.25, 28.0, 1e-3
    drop = lambda y: w / (v - r * y)  # noqa: E731
    artifact = -(drop(dy) - drop(-dy)) / (2 * dy) * v
    assert inj.helix_gradient(w, r, v) == pytest.approx(-artifact, rel=1e-6)
    assert inj.helix_gradient(w, r, 5.0) == 0.0
