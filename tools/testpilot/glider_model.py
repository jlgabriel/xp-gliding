"""Crude glider model to exercise the test pilot offline (not a flight model).

Point mass in the vertical plane plus a second-order short-period mode and a
first-order roll mode, with ASK 21-like numbers (540 kg, 17.95 m2, aspect
ratio 16.1, best glide ~31). It only has to react to the yoke the way a glider
roughly does (pitch attitude first, then speed over the phugoid) so that the
control laws, their signs and their sample rate can be checked before flying
X-Plane. Sea-level density; IAS equals TAS here.
"""

import math

G = 9.80665
RHO = 1.225


class GliderModel:
    def __init__(self, mass=540.0, area=17.95, cla=5.5, cd0=0.012, k_ind=0.022,
                 omega_sp=3.0, zeta_sp=0.6, alpha_per_yoke_deg=12.0, trim_kmh=85.0,
                 roll_damping=4.0, roll_power=3.0, spiral=0.02):
        self.m, self.s, self.cla, self.cd0, self.k = mass, area, cla, cd0, k_ind
        self.w, self.z = omega_sp, zeta_sp
        self.k_yoke = math.radians(alpha_per_yoke_deg)
        self.lp, self.lda, self.spiral = roll_damping, roll_power, spiral
        # Trim at trim_kmh with the yoke centred: alpha that carries the weight.
        v = trim_kmh / 3.6
        self.alpha0 = self.m * G / (0.5 * RHO * v * v * self.s * self.cla)
        cl = self.cla * self.alpha0
        gamma = -math.atan((self.cd0 + self.k * cl * cl) / cl)
        self.v, self.gamma, self.theta, self.q = v, gamma, gamma + self.alpha0, 0.0
        self.phi, self.p = 0.0, 0.0
        self.h = 0.0
        self.yoke_pitch = self.yoke_roll = 0.0

    def step(self, dt):
        alpha = self.theta - self.gamma
        alpha_e = self.alpha0 + self.k_yoke * self.yoke_pitch  # pull -> higher trimmed alpha
        qbar = 0.5 * RHO * self.v * self.v
        cl = self.cla * alpha
        lift = qbar * self.s * cl
        drag = qbar * self.s * (self.cd0 + self.k * cl * cl)
        weight = self.m * G
        self.q += (-self.w ** 2 * (alpha - alpha_e) - 2 * self.z * self.w * self.q) * dt
        self.theta += self.q * dt
        self.gamma += (lift * math.cos(self.phi) - weight * math.cos(self.gamma)) / (self.m * self.v) * dt
        self.v += (-drag - weight * math.sin(self.gamma)) / self.m * dt
        self.h += self.v * math.sin(self.gamma) * dt
        self.p += (-self.lp * self.p + self.lda * self.yoke_roll + self.spiral * self.phi) * dt
        self.phi += self.p * dt

    # Readings in the units X-Plane's datarefs use.
    def ias_kmh(self):
        return self.v * 3.6

    def theta_deg(self):
        return math.degrees(self.theta)

    def q_dps(self):
        return math.degrees(self.q)

    def phi_deg(self):
        return math.degrees(self.phi)

    def p_dps(self):
        return math.degrees(self.p)

    def vs_ms(self):
        return self.v * math.sin(self.gamma)
