"""Lift injection: from air velocity at sample points to forces and moments.

X-Plane cannot move the air at a point, so local lift becomes a force on the
aircraft (SPEC "Injection physics"). Everything here is plain math on numbers
the adapter reads from datarefs; no per-glider calibration constant appears.

Energy force. Air rising at w delivers power m g w to a glider that holds its
airspeed. A force F along the air-relative velocity delivers F V, so

    F = m g w / V_TAS

makes the glider climb w faster than in still air at the same airspeed, for
any glider and any speed. The force goes along the velocity vector, so in body
axes it is split with the angle of attack and sideslip (`path_force_body`).

Sample points. The air velocity is sampled at the centre, both wing tips and
the tail (`SampleGeometry`), at their real 3D positions: a banked wing's tips
are closer together horizontally and at different heights, so the bank
attenuation the SPEC asks for comes out of the geometry instead of a factor.
The energy uses the span average of the wing samples (Simpson's rule).

Gust roll moment. A vertical air velocity that varies linearly across the span,
w(y) = g y (y to the right), changes each wing station's angle of attack by
g y / V, exactly as a roll rate p = g does. So the rolling moment it causes is
the aircraft's own roll damping applied to p = g:

    L = (1/4) rho V S b^2 Clp g          (positive = right wing down)

with Clp < 0 the roll-damping derivative per unit p b / 2V. Clp comes from
the wing's geometry (lifting-line lift slope and a taper correction), never
from a tuned constant. Note it grows with V: at a given spatial gradient a
faster glider is rolled harder, as in reality. *Verify* by flying (test F).

Not covered yet: the pitch moment from the tail sample (needs tail area and
arm), and the transient load factor from the angle-of-attack change when
entering lift ("the seat kick"); the energy force alone gives the right climb
but a softer entry. Both are phase 1 items to measure in the simulator.
"""

import math

G = 9.80665
MIN_TAS_MS = 10.0  # below this (ground roll, tail slide) no lift is injected


def energy_force(mass_kg, w_ms, tas_ms):
    """Force (N) along the flight path that adds the power of air rising at w."""
    if tas_ms < MIN_TAS_MS:
        return 0.0
    return mass_kg * G * w_ms / tas_ms


def path_force_body(force_n, alpha_deg, beta_deg):
    """Split a force along the air-relative velocity into body axes.

    Returns (forward, right, up) in newtons. alpha is positive nose above the
    velocity vector; beta is positive with the velocity vector to the right of
    the nose. *Verify* X-Plane's sign of beta (`sim/flightmodel/position/beta`)
    and of each `*_plug_acf` axis in the adapter.
    """
    a = math.radians(alpha_deg)
    b = math.radians(beta_deg)
    cb = math.cos(b)
    return (force_n * math.cos(a) * cb,
            force_n * math.sin(b),
            -force_n * math.sin(a) * cb)


def lift_slope(aspect_ratio):
    """Wing lift slope (1/rad) from the Helmbold equation (unswept wing)."""
    return 2.0 * math.pi * aspect_ratio / (2.0 + math.sqrt(aspect_ratio ** 2 + 4.0))


def roll_damping(aspect_ratio, taper=0.5):
    """Roll-damping derivative Clp (per unit p b / 2V), straight tapered wing.

    Strip theory with the wing's lift slope: Clp = -(CLa / 12) (1 + 3 taper) /
    (1 + taper), which is -CLa/6 for a rectangular wing. Typical glider wings
    have a taper ratio near 0.4-0.5; the default is a generic value, not a
    per-glider tuning.
    """
    return -(lift_slope(aspect_ratio) / 12.0) * (1.0 + 3.0 * taper) / (1.0 + taper)


def gust_roll_moment(rho, tas_ms, wing_area_m2, span_m, dw_dy, clp):
    """Rolling moment (N m, positive right wing down) from a spanwise gradient of w.

    dw_dy is the gradient of vertical air velocity along the span toward the
    right wing (1/s): more lift under the right wing gives dw_dy > 0, a
    negative moment, and the right wing rises.
    """
    if tas_ms < MIN_TAS_MS:
        return 0.0
    return 0.25 * rho * tas_ms * wing_area_m2 * span_m * span_m * clp * dw_dy


class SampleGeometry:
    """Positions of the sample points in the local frame, reused every frame.

    Points: centre (c), left tip (l), right tip (r), tail (t). Heights are
    above ground; pitch is ignored (a few degrees moves the tips by centimetres).
    """

    __slots__ = ("half_span", "tail_arm",
                 "ce", "cn", "cz", "le", "ln", "lz", "re", "rn", "rz", "te", "tn", "tz")

    def __init__(self, span_m, tail_arm_m):
        self.half_span = 0.5 * span_m
        self.tail_arm = tail_arm_m
        self.ce = self.cn = self.cz = 0.0
        self.le = self.ln = self.lz = 0.0
        self.re = self.rn = self.rz = 0.0
        self.te = self.tn = self.tz = 0.0

    def update(self, e, n, z_agl, heading_deg, roll_deg):
        h = math.radians(heading_deg)
        fe, fn = math.sin(h), math.cos(h)  # forward
        re_, rn_ = fn, -fe  # right
        phi = math.radians(roll_deg)
        horiz = self.half_span * math.cos(phi)
        vert = self.half_span * math.sin(phi)  # right tip goes down when phi > 0
        self.ce, self.cn, self.cz = e, n, z_agl
        self.re, self.rn, self.rz = e + horiz * re_, n + horiz * rn_, z_agl - vert
        self.le, self.ln, self.lz = e - horiz * re_, n - horiz * rn_, z_agl + vert
        self.te, self.tn, self.tz = e - self.tail_arm * fe, n - self.tail_arm * fn, z_agl


def helix_gradient(w_ms, yaw_rate_rad, tas_ms):
    """Spanwise gradient (1/s) that undoes the climbing-turn artifact of the energy force.

    In real rising air a circling glider still descends relative to the air:
    its helix through the air is the one of still air. With the energy force
    it climbs w faster relative to the air, so each wing station's angle of
    attack drops by w / V(y). In a turn the stations' airspeeds differ,
    V(y) = V - r y (r yaw rate, positive right; y toward the right wing), so
    the drop is not uniform: it is a spanwise gradient equivalent to a vertical
    air gradient of -w r / V, which makes the outer wing lift more and the
    glider overbank (seen in flight, 2026-11-03: with 2 m/s of uniform lift
    the test pilot's 35 deg circle ran away to 46 deg). Adding this gradient to
    the roll moment's dw/dy cancels it.
    """
    if tas_ms < MIN_TAS_MS:
        return 0.0
    return w_ms * yaw_rate_rad / tas_ms


def span_average(w_left, w_centre, w_right):
    """Simpson's rule over the span: exact for a quadratic distribution of w."""
    return (w_left + 4.0 * w_centre + w_right) / 6.0


def span_gradient(w_left, w_right, span_m):
    """dw/dy along the span toward the right tip (1/s)."""
    return (w_right - w_left) / span_m
