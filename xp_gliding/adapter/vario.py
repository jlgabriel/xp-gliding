"""The soaring instruments: what a pilot's vario knows, from the aircraft's energy.

Pure Python, no `xp`, and on purpose no link to the engine: these instruments
read what a real glider's instruments could sense (height, airspeed, bank,
heading). The engine's lift and nearest thermal are the oracle, used only by
tests and tools to check them.

Works with force injection: our lift is real energy for the aircraft, so the
total energy rate reads it like moving air, and X-Plane's own total-energy gauge
agrees with it (within 0.03 m/s over 20 s, wings level; docs/hud.md).

- `Polar`: the still-air sink of an aircraft, measured by the test pilot.
- `Vario`: total-energy rate, netto, and the true average over a time window.
- `CentringAid`: which way the core lies, from netto against heading over the
  last turn, the way a pilot reads it from the vario.

All of them expect samples about every `SAMPLE_PERIOD_S`, not every frame: a
vario needs no more, and the sim clock's float precision makes single-frame
differences noisy.
"""

import math

G = 9.80665
SAMPLE_PERIOD_S = 0.1
MAX_ENERGY_RATE_MS = 60.0  # beyond this it is a teleport or an air start, not air
MAX_GAP_S = 1.0


class Polar:
    """Still-air sink against IAS, bank and mass, from a level-flight table at sea level.

    Turning, the load factor n adds induced sink: k (v_ref / IAS) (n^2 - 1),
    the parabolic polar's term. Mass scales the polar by sqrt(m / m_ref), in
    both speed and sink; density by TAS / IAS.
    """

    __slots__ = ("table", "mass_kg", "turn_k_ms", "turn_v_kmh")

    def __init__(self, table, mass_kg, turn_k_ms, turn_v_kmh):
        self.table = table
        self.mass_kg = mass_kg
        self.turn_k_ms = turn_k_ms
        self.turn_v_kmh = turn_v_kmh

    def _level(self, ias_kmh):
        pts = self.table
        if ias_kmh <= pts[0][0]:
            return pts[0][1]
        for (v0, s0), (v1, s1) in zip(pts, pts[1:]):
            if ias_kmh <= v1:
                return s0 + (s1 - s0) * (ias_kmh - v0) / (v1 - v0)
        return pts[-1][1]

    def sink(self, ias_kmh, tas_ms, bank_deg, mass_kg):
        """Still-air sink (m/s, positive down), or 0 with no meaningful airspeed."""
        if ias_kmh < 20.0 or mass_kg <= 0.0:
            return 0.0
        scale = math.sqrt(mass_kg / self.mass_kg)
        v = ias_kmh / scale
        cos_bank = max(math.cos(math.radians(bank_deg)), 0.26)  # 75 degrees at most
        sink_sl = self._level(v) + self.turn_k_ms * (self.turn_v_kmh / v) * (cos_bank ** -2 - 1.0)
        return sink_sl * scale * tas_ms / (ias_kmh / 3.6)


# The Laminar ASK 21 at 541 kg: level flight from test A (docs/baseline.md), the
# turn term fitted to the logged circles of 2026-11-03 (docs/hud.md).
ASK21_LAMINAR = Polar(((77.0, 0.86), (80.0, 0.86), (90.0, 0.86), (100.0, 0.90),
                       (120.0, 1.11), (140.0, 1.50)), 541.0, 0.85, 90.0)


def polar_for(aircraft_path):
    """The measured polar of this aircraft, or None: without one there is no netto."""
    path = aircraft_path.replace("\\", "/").lower()
    return ASK21_LAMINAR if "laminar research/schleicher ask 21/" in path else None


class Vario:
    """Total-energy rate and netto (m/s) with one filter, and a true average.

    The average is the energy difference over the window, so it has no filter
    lag or drift. `update` returns False when the sample was ignored.
    """

    AVERAGE_STEP_S = 1.0

    __slots__ = ("polar", "tau_s", "te_ms", "netto_ms", "average_ms", "has_netto", "valid",
                 "_t", "_energy", "_ring_t", "_ring_e", "_ring_next", "_ring_len", "_ring_at")

    def __init__(self, polar=None, tau_s=1.0, average_s=30.0):
        self.polar = polar
        self.tau_s = tau_s
        size = int(average_s / self.AVERAGE_STEP_S) + 1
        self._ring_t = [0.0] * size
        self._ring_e = [0.0] * size
        self.has_netto = polar is not None
        self.reset()

    def reset(self):
        """Forget everything (paused, teleported, new flight)."""
        self.te_ms = self.netto_ms = self.average_ms = 0.0
        self.valid = False
        self._t = None
        self._energy = 0.0
        self._ring_next = 0
        self._ring_len = 0
        self._ring_at = 0.0

    def update(self, t, elevation_m, tas_ms, ias_kmh, bank_deg, mass_kg):
        energy = elevation_m + tas_ms * tas_ms / (2.0 * G)
        if self._t is None:
            self._t, self._energy = t, energy
            self._push(t, energy)
            return False
        dt = t - self._t
        if dt <= 0.0:
            return False
        rate = (energy - self._energy) / dt
        if dt > MAX_GAP_S or abs(rate) > MAX_ENERGY_RATE_MS:
            self.reset()
            return self.update(t, elevation_m, tas_ms, ias_kmh, bank_deg, mass_kg)
        self._t, self._energy = t, energy
        netto = rate
        if self.polar is not None:
            netto += self.polar.sink(ias_kmh, tas_ms, bank_deg, mass_kg)
        gain = 1.0 - math.exp(-dt / self.tau_s)
        if self.valid:
            self.te_ms += gain * (rate - self.te_ms)
            self.netto_ms += gain * (netto - self.netto_ms)
        else:
            self.te_ms, self.netto_ms = rate, netto
            self.valid = True
        if t >= self._ring_at:
            self._push(t, energy)
        self._average(t, energy)
        return True

    def _push(self, t, energy):
        self._ring_t[self._ring_next] = t
        self._ring_e[self._ring_next] = energy
        self._ring_next = (self._ring_next + 1) % len(self._ring_t)
        self._ring_len = min(self._ring_len + 1, len(self._ring_t))
        self._ring_at = t + self.AVERAGE_STEP_S

    def _average(self, t, energy):
        oldest = (self._ring_next - self._ring_len) % len(self._ring_t)
        span = t - self._ring_t[oldest]
        if span >= 2.0 * self.AVERAGE_STEP_S:
            self.average_ms = (energy - self._ring_e[oldest]) / span


class CentringAid:
    """Where the core lies, from lift against heading over the last turn.

    A sector per 10 degrees of heading keeps the latest netto flown on it. The
    first harmonic of those values says on which heading the lift peaks: there
    the glider is on the side of the circle nearest the core, which fixes the
    core's direction from the circle's centre (see `solve`). The vario's filter
    lag is taken out of the heading (turn rate times tau).

    Output: `valid` once the sectors of one whole turn are fresh, `core_az_deg`
    the true azimuth to shift the circle towards, `amp_ms` half the lift's swing
    around the circle (small means centred), `mean_ms` the circle's mean.
    """

    SECTORS = 36
    MIN_BANK_DEG = 15.0
    MIN_RATE_DPS = 5.0
    MIN_FILLED = 30  # of SECTORS, to call it a turn
    MAX_TURN_S = 60.0  # a sector older than this is not from the last turn

    __slots__ = ("lag_s", "valid", "core_az_deg", "amp_ms", "mean_ms", "turning",
                 "_value", "_stamp", "_cos", "_sin", "_psi", "_t", "_rate")

    def __init__(self, lag_s=1.0):
        self.lag_s = lag_s
        self._value = [0.0] * self.SECTORS
        self._stamp = [-1e9] * self.SECTORS
        step = 2.0 * math.pi / self.SECTORS
        self._cos = [math.cos((i + 0.5) * step) for i in range(self.SECTORS)]
        self._sin = [math.sin((i + 0.5) * step) for i in range(self.SECTORS)]
        self.reset()

    def reset(self):
        self.valid = False
        self.core_az_deg = self.amp_ms = self.mean_ms = 0.0
        self.turning = 0  # +1 right, -1 left, 0 not circling
        self._psi = None
        self._t = 0.0
        self._rate = 0.0
        for i in range(self.SECTORS):
            self._stamp[i] = -1e9

    def update(self, t, psi_deg, bank_deg, lift_ms):
        """Add a sample. Cheap: one sector write. Call `solve` less often."""
        if self._psi is None or t <= self._t or t - self._t > MAX_GAP_S:
            self._psi, self._t = psi_deg, t
            return
        dpsi = (psi_deg - self._psi + 180.0) % 360.0 - 180.0
        dt = t - self._t
        self._psi, self._t = psi_deg, t
        self._rate += min(dt / 2.0, 1.0) * (dpsi / dt - self._rate)
        turning = 0
        if abs(bank_deg) >= self.MIN_BANK_DEG and abs(self._rate) >= self.MIN_RATE_DPS:
            turning = 1 if self._rate > 0.0 else -1
        if turning != self.turning:
            self.turning = turning
            for i in range(self.SECTORS):  # another circle, or none: start over
                self._stamp[i] = -1e9
            self.valid = False
        if turning:
            flown = psi_deg - self._rate * self.lag_s
            index = int((flown % 360.0) / 360.0 * self.SECTORS) % self.SECTORS
            self._value[index] = lift_ms
            self._stamp[index] = t

    def solve(self):
        """Refresh the output from the sectors."""
        if not self.turning:
            self.valid = False
            return
        oldest = self._t - self.MAX_TURN_S
        n = 0
        total = a = b = 0.0
        for i in range(self.SECTORS):
            if self._stamp[i] >= oldest:
                v = self._value[i]
                n += 1
                total += v
                a += v * self._cos[i]
                b += v * self._sin[i]
        if n < self.MIN_FILLED:
            self.valid = False
            return
        self.mean_ms = total / n
        a -= self.mean_ms * sum(self._cos[i] for i in range(self.SECTORS)
                                if self._stamp[i] >= oldest)
        b -= self.mean_ms * sum(self._sin[i] for i in range(self.SECTORS)
                                if self._stamp[i] >= oldest)
        self.amp_ms = 2.0 * math.hypot(a, b) / n
        best_heading = math.degrees(math.atan2(b, a))
        # Turning right, the circle's centre is 90 degrees right of the heading,
        # so the glider sits at heading - 90 from the centre; left, at heading + 90.
        self.core_az_deg = (best_heading - 90.0 * self.turning) % 360.0
        self.valid = True
