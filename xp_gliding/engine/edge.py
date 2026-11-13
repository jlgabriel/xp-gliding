"""Turbulence at a thermal's edge, for the sharper thermal edges (to judge by flying).

Allen's profiles are smooth: a wide thermal's lift changes over a couple of hundred metres, seven
seconds at 97 km/h, so the kick it gives (engine/injection.py) is under 0.1 g. Real edges are
broken up, and the bumps are what a pilot feels on entering and leaving lift. They come here as
a small-scale field of vertical air, `TURB_CELL_M` across, as strong as the lift changes where
the glider is: `TURB_LENGTH_M` times the gradient of the smooth lift. So there is none between
thermals, more at their edges, and more low down, where thermals are narrow. It drifts slowly,
so a circle does not meet the same bumps each turn.

It feeds only the kick and the roll moment, which do no work, never the energy force: the climb
is the smooth field's. The numbers are first guesses.

Pure Python: no `xp`.
"""

import math

TURB_CELL_M = 20.0  # size of the bumps
TURB_LENGTH_M = 60.0  # their strength: this many metres of the lift's gradient
TURB_DRIFT_MS = (1.1, 0.7)  # the bumps move through the air this fast (east, north)
GRADIENT_TAU_S = 1.0  # the gradient is smoothed over about this long
MAX_AMPLITUDE_MS = 3.0


def _hash(ix, iy):
    """A value in [-1, 1) for a grid point, the same everywhere and every time."""
    h = (ix * 0x27D4EB2D ^ iy * 0x165667B1) & 0xFFFFFFFF
    h ^= h >> 15
    h = (h * 0x2C1B3C6D) & 0xFFFFFFFF
    h ^= h >> 12
    h = (h * 0x297A2D39) & 0xFFFFFFFF
    h ^= h >> 15
    return h / 2147483648.0 - 1.0


def _smooth(x):
    return x * x * (3.0 - 2.0 * x)


def bumps(e, n, t):
    """The small-scale field at (e, n) m in the air's frame and sky time t s: about -1 to 1."""
    x = (e - TURB_DRIFT_MS[0] * t) / TURB_CELL_M
    y = (n - TURB_DRIFT_MS[1] * t) / TURB_CELL_M
    ix, iy = math.floor(x), math.floor(y)
    fx, fy = _smooth(x - ix), _smooth(y - iy)
    a, b = _hash(ix, iy), _hash(ix + 1, iy)
    c, d = _hash(ix, iy + 1), _hash(ix + 1, iy + 1)
    return (a + (b - a) * fx) + ((c + (d - c) * fx) - (a + (b - a) * fx)) * fy


class EdgeTurbulence:
    """How strong the bumps are where the glider is: TURB_LENGTH_M times the smooth lift's gradient,
    across the span and along the track, smoothed. Reset on any gap."""

    __slots__ = ("gradient", "_last_w")

    def __init__(self):
        self.gradient = 0.0  # 1/s
        self._last_w = None

    def reset(self):
        self.gradient = 0.0
        self._last_w = None

    def step(self, w_centre, dw_dy, tas_ms, dt_s):
        """Amplitude (m/s) for this frame. dw_dy: the smooth lift's gradient across the span (1/s)."""
        if self._last_w is None or tas_ms <= 0.0:
            self._last_w = w_centre
            return min(TURB_LENGTH_M * self.gradient, MAX_AMPLITUDE_MS)
        if dt_s <= 0.0:  # a frame within the clock's resolution: measured with the next one
            return min(TURB_LENGTH_M * self.gradient, MAX_AMPLITUDE_MS)
        along = (w_centre - self._last_w) / (tas_ms * dt_s)
        self._last_w = w_centre
        now = math.hypot(along, dw_dy)
        self.gradient += (now - self.gradient) * dt_s / (GRADIENT_TAU_S + dt_s)
        return min(TURB_LENGTH_M * self.gradient, MAX_AMPLITUDE_MS)
