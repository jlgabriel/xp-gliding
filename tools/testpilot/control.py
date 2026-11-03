"""Control laws of the test pilot: hold an indicated airspeed and a bank.

Pure Python, no I/O, so the same code flies the offline model in
`test_testpilot.py` and X-Plane through the web API.

Cascade on the pitch axis, since a glider controls speed with attitude:
  outer  theta_cmd = theta_ref + KV * err + KI * integral(err)     err = IAS - target
  inner  pitch     = KTH * (theta_cmd - theta) - KQ * q + KTI * integral(theta_cmd - theta)
The inner integral acts as the pilot's trim: it carries the steady yoke
deflection a new speed needs, so the attitude error goes back to zero.
Roll:      roll  = KPHI * (phi_cmd - phi) - KP * p + KPHI_I * integral(phi_cmd - phi)
Rudder:    yaw   = KBETA * beta (a yaw damper on sideslip; 0 = rudder centred)
phi_cmd is 0 for wings level; the lateral guidance below sets it to hold a
heading, follow a line over the ground, or circle. Yoke ratios follow
X-Plane's `sim/joystick/yoke_*_ratio`: pitch +1 is full aft (nose up), roll +1
is full right (both confirmed in flight on 2026-11-02).

Units: km/h, degrees, deg/s. Gains are first guesses tuned on the offline
model; real tuning happens in X-Plane with the logged traces.
"""

import math


def clamp(x, lim):
    return -lim if x < -lim else lim if x > lim else x


class Gains:
    __slots__ = ("kv", "ki", "kth", "kti", "kq", "kphi", "kphi_i", "kp", "kbeta", "pitch_limit",
                 "roll_limit", "yaw_limit", "theta_span", "phi_i_window")

    def __init__(self, kv=0.5, ki=0.05, kth=0.05, kti=0.03, kq=0.02, kphi=0.02, kphi_i=0.004,
                 kp=0.01, kbeta=-0.12, pitch_limit=0.8, roll_limit=0.3, yaw_limit=0.5,
                 theta_span=12.0, phi_i_window=5.0):
        self.kv = kv  # deg of pitch per km/h of speed error
        self.ki = ki  # deg per (km/h * s)
        self.kth = kth  # yoke per deg of pitch error
        self.kti = kti  # yoke per (deg * s) of pitch error: automatic trim
        self.kq = kq  # yoke per deg/s of pitch rate
        self.kphi = kphi  # yoke per deg of bank error
        self.kphi_i = kphi_i  # yoke per (deg * s) of bank error: holds a steady bank
        self.kp = kp  # yoke per deg/s of roll rate
        self.kbeta = kbeta  # rudder per deg of sideslip (negative: beta > 0 needs left rudder)
        self.pitch_limit = pitch_limit
        self.roll_limit = roll_limit
        self.yaw_limit = yaw_limit
        self.theta_span = theta_span  # theta_cmd within theta_ref +/- this
        self.phi_i_window = phi_i_window  # deg: the bank integrator runs only this close


class SpeedHold:
    """Speed-by-pitch and wings-level controller with anti-windup."""

    def __init__(self, target_kmh, theta_ref_deg, gains=None, start_kmh=None, ramp_kmh_s=2.0):
        """start_kmh: current speed; the target then moves to target_kmh at
        ramp_kmh_s instead of jumping, so a large change never yanks the stick."""
        self.final = target_kmh
        self.target = target_kmh if start_kmh is None else start_kmh
        self.ramp = ramp_kmh_s
        self.theta_ref = theta_ref_deg
        self.g = gains or Gains()
        self.integral = 0.0
        self.trim = 0.0
        self.theta_cmd = theta_ref_deg
        self.phi_cmd = 0.0  # set by the lateral guidance
        self.roll_trim = 0.0

    def set_target(self, target_kmh):
        """Move to a new speed (ramped like the start)."""
        self.final = target_kmh

    def step(self, dt, ias_kmh, theta, q, phi, p, beta=0.0):
        """One control step; returns (pitch_ratio, roll_ratio, heading_ratio)."""
        g = self.g
        step = self.ramp * dt
        self.target += clamp(self.final - self.target, step)
        err = ias_kmh - self.target  # too fast -> raise the nose
        outer = g.kv * err + g.ki * self.integral
        if abs(outer) < g.theta_span:  # integrate only while the command is not saturated
            self.integral += err * dt
        self.theta_cmd = self.theta_ref + clamp(g.kv * err + g.ki * self.integral, g.theta_span)
        e_theta = self.theta_cmd - theta
        raw = g.kth * e_theta - g.kq * q + self.trim
        if abs(raw) < g.pitch_limit:  # anti-windup, as above
            self.trim += g.kti * e_theta * dt
        pitch = clamp(raw, g.pitch_limit)
        e_phi = self.phi_cmd - phi
        raw = g.kphi * e_phi - g.kp * p + self.roll_trim
        if abs(raw) < g.roll_limit and abs(e_phi) < g.phi_i_window:  # only near the command
            self.roll_trim += g.kphi_i * e_phi * dt
        roll = clamp(raw, g.roll_limit)
        yaw = clamp(g.kbeta * beta, g.yaw_limit)
        return pitch, roll, yaw


# Lateral guidance: each returns the bank command (deg, + is right wing down)
# from the aircraft's state. Courses are true, in degrees clockwise from north.

def wrap180(deg):
    return (deg + 180.0) % 360.0 - 180.0


class HeadingHold:
    """Hold a course over the ground (or a heading in still air)."""

    def __init__(self, course_deg, k=0.7, max_bank=20.0):
        self.course, self.k, self.max_bank = course_deg, k, max_bank

    def bank(self, track_deg, east_m=0.0, north_m=0.0):
        return clamp(self.k * wrap180(self.course - track_deg), self.max_bank)


class LineHold:
    """Follow the straight line through two points of the local east-north
    frame (meters), flying from the first towards the second."""

    def __init__(self, start_en, end_en, k_xt=0.15, max_intercept=40.0, k=0.7, max_bank=20.0):
        (e0, n0), (e1, n1) = start_en, end_en
        self.e0, self.n0 = e0, n0
        length = math.hypot(e1 - e0, n1 - n0)
        self.ue, self.un, self.length = (e1 - e0) / length, (n1 - n0) / length, length
        self.course = math.degrees(math.atan2(self.ue, self.un)) % 360.0
        self.k_xt, self.max_intercept = k_xt, max_intercept
        self.heading = HeadingHold(self.course, k, max_bank)

    def along_cross(self, east_m, north_m):
        """Distance along the line and to its right (m)."""
        de, dn = east_m - self.e0, north_m - self.n0
        return de * self.ue + dn * self.un, de * self.un - dn * self.ue

    def bank(self, track_deg, east_m, north_m):
        _, cross = self.along_cross(east_m, north_m)
        self.heading.course = self.course - clamp(self.k_xt * cross, self.max_intercept)
        return self.heading.bank(track_deg)


class Circle:
    """Constant bank; positive turns right."""

    def __init__(self, bank_deg):
        self.bank_deg = bank_deg

    def bank(self, track_deg=0.0, east_m=0.0, north_m=0.0):
        return self.bank_deg
