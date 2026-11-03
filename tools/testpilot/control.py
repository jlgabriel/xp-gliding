"""Control laws of the test pilot: hold an indicated airspeed, wings level.

Pure Python, no I/O, so the same code flies the offline model in
`test_testpilot.py` and X-Plane through the web API.

Cascade on the pitch axis, since a glider controls speed with attitude:
  outer  theta_cmd = theta_ref + KV * err + KI * integral(err)     err = IAS - target
  inner  pitch     = KTH * (theta_cmd - theta) - KQ * q + KTI * integral(theta_cmd - theta)
The inner integral acts as the pilot's trim: it carries the steady yoke
deflection a new speed needs, so the attitude error goes back to zero.
Roll:      roll  = -KPHI * phi - KP * p
Rudder centred. Yoke ratios follow X-Plane's `sim/joystick/yoke_*_ratio`:
pitch +1 is full aft (nose up), roll +1 is full right; *verify* both signs
in the simulator before trusting a run (the first flight logs them).

Units: km/h, degrees, deg/s. Gains are first guesses tuned on the offline
model; real tuning happens in X-Plane with the logged traces.
"""


def clamp(x, lim):
    return -lim if x < -lim else lim if x > lim else x


class Gains:
    __slots__ = ("kv", "ki", "kth", "kti", "kq", "kphi", "kp", "pitch_limit", "roll_limit",
                 "theta_span")

    def __init__(self, kv=0.5, ki=0.05, kth=0.05, kti=0.03, kq=0.02, kphi=0.02, kp=0.01,
                 pitch_limit=0.6, roll_limit=0.3, theta_span=12.0):
        self.kv = kv  # deg of pitch per km/h of speed error
        self.ki = ki  # deg per (km/h * s)
        self.kth = kth  # yoke per deg of pitch error
        self.kti = kti  # yoke per (deg * s) of pitch error: automatic trim
        self.kq = kq  # yoke per deg/s of pitch rate
        self.kphi = kphi  # yoke per deg of bank
        self.kp = kp  # yoke per deg/s of roll rate
        self.pitch_limit = pitch_limit
        self.roll_limit = roll_limit
        self.theta_span = theta_span  # theta_cmd within theta_ref +/- this


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

    def step(self, dt, ias_kmh, theta, q, phi, p):
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
        roll = clamp(-g.kphi * phi - g.kp * p, g.roll_limit)
        return pitch, roll, 0.0
