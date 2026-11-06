"""The wind carries the sky (notes/SPEC.md "Wind").

The wind is X-Plane's: it carries the glider, and nothing here models it. To carry the
thermals along with the glider, the field keeps the positions it generated in a frame that
moves with the air. `AirDrift` holds the offset between that frame and the ground, as the
wind integrated over the sky's clock:

  air position    = ground position - offset   what the field is asked about
  ground position = air position + offset      where a cloud or a marker is drawn

The offset is in degrees of latitude and longitude, not meters, for two reasons. A glider
carried by the wind then keeps exactly the same air position, whatever the frame's origin.
And the field's frame can be recentred without moving anything, however far the air has
travelled. East distances in the air's frame are scaled for the air's latitude and not the
ground's, which is about 0.1% for every 2 km of north-south travel at 33 deg: nothing a
glider circling a thermal can tell.

With no wind the offset stays at zero and this changes nothing, thermal for thermal.
Same seed, date, place, time and offset: same sky. The offset starts at zero when the
aircraft is loaded, and the adapter publishes it so the test pilot's oracles can rebuild the sky.

The lean (`Lean`, off by default, notes/phase3.md): the field holds the sky as it is at the
clouds' base, and at a height z the lift is that sky shifted upwind by
    L(z) = integral from z to the base of f * U(z') / w* dz', with each slope capped.
A rigid plume tilted by its rise time would be f = 1, and runs away from a climbing glider.
So it leans a tenth of that: enough to put the lift upwind of the cloud, more when low and
in more wind and on a weaker day, as the FAA's handbook describes (10-4), and little enough
to be followed by hand. A departure from the plume's geometry, a first guess to judge by
flying. A cloud sits at the base, where L = 0, so nothing moves it.

Pure Python: no `xp`.
"""

import math

from .geo import radii_of_curvature, wrap_lon_deg

# A longer step of the clock than this is not flying: the time was changed, or the sim was
# stopped. The air does not travel across it.
MAX_STEP_S = 5.0

# The lean: first guesses to judge by flying (notes/phase3.md).
LEAN_FRACTION = 0.1  # of the slope of a plume tilted by its rise time, U / w*
LEAN_MAX_SLOPE = 0.5  # metres upwind per metre of height, the steepest at any height
LEAN_STEP_M = 100.0  # the table's spacing in height
LEAN_TOP_M = 4000.0  # above this it stays as it is here
LEAN_SMOOTH_S = 60.0  # a new wind takes about this long to lean the sky, so no lift jumps
LEAN_MAX_GAP_S = 60.0  # a longer step of the clock than this is not flying: no smoothing


class AirDrift:
    __slots__ = ("dlat_deg", "dlon_deg", "wind_e_ms", "wind_n_ms", "_last_t")

    def __init__(self):
        self.reset()

    def reset(self):
        """A new flight: the sky starts where the field drew it."""
        self.dlat_deg = self.dlon_deg = 0.0
        self.wind_e_ms = self.wind_n_ms = 0.0
        self._last_t = None

    def advance(self, wind_e_ms, wind_n_ms, lat_deg, t_s):
        """Carry the sky to the sky's time t_s, in this wind (m/s, toward east and north)."""
        self.wind_e_ms, self.wind_n_ms = wind_e_ms, wind_n_ms
        dt = 0.0 if self._last_t is None else t_s - self._last_t
        self._last_t = t_s
        if 0.0 < dt <= MAX_STEP_S:
            m, n = radii_of_curvature(lat_deg)
            k = math.degrees(dt)
            self.dlat_deg += k * wind_n_ms / m
            self.dlon_deg += k * wind_e_ms / (n * math.cos(math.radians(lat_deg)))

    def hold(self, t_s):
        """The clock runs and the sky stays: no jump if it is carried again later."""
        self.wind_e_ms = self.wind_n_ms = 0.0
        self._last_t = t_s

    def to_air(self, lat, lon):
        return lat - self.dlat_deg, wrap_lon_deg(lon - self.dlon_deg)

    def to_ground(self, lat, lon):
        return lat + self.dlat_deg, wrap_lon_deg(lon + self.dlon_deg)


def _interpolate(x, xs, ys):
    """Linear in xs (ascending), and constant beyond its ends."""
    if x <= xs[0]:
        return ys[0]
    for k in range(1, len(xs)):
        if x <= xs[k]:
            u = (x - xs[k - 1]) / (xs[k] - xs[k - 1])
            return ys[k - 1] + u * (ys[k] - ys[k - 1])
    return ys[-1]


def layer_wind(z, heights_m, east_ms, north_ms):
    """The wind at a height, from layers of wind (ascending): (east, north), in m/s."""
    return _interpolate(z, heights_m, east_ms), _interpolate(z, heights_m, north_ms)


class Lean:
    """Where the lift's centre is at each height, from the cloud above it, in metres.

    `set_wind` is for the slow path; `at` is cheap enough for every frame. The table starts
    at zero everywhere, which is no lean, and `reset` goes back to that.
    """

    __slots__ = ("fraction", "max_slope", "smooth_s", "_e", "_n", "_t")

    def __init__(self, fraction=LEAN_FRACTION, max_slope=LEAN_MAX_SLOPE, smooth_s=LEAN_SMOOTH_S):
        self.fraction = float(fraction)
        self.max_slope = float(max_slope)
        self.smooth_s = float(smooth_s)
        self.reset()

    def reset(self):
        count = int(LEAN_TOP_M / LEAN_STEP_M) + 1
        self._e = [0.0] * count
        self._n = [0.0] * count
        self._t = None

    def _slope(self, z, heights, east, north, wstar):
        ue = _interpolate(z, heights, east)
        un = _interpolate(z, heights, north)
        k = self.fraction / wstar
        slope = k * math.hypot(ue, un)
        if slope > self.max_slope:
            k *= self.max_slope / slope
        return k * ue, k * un

    def set_wind(self, heights_m, east_ms, north_ms, base_m, wstar_ms, t_s):
        """The wind by height above ground (ascending), toward east and north, at the sky's time."""
        count = len(self._e)
        e, n = [0.0] * count, [0.0] * count
        if wstar_ms > 0.0:
            for k in range(1, count):  # upward from the ground, by the middle of each step
                se, sn = self._slope((k - 0.5) * LEAN_STEP_M, heights_m, east_ms, north_ms, wstar_ms)
                e[k] = e[k - 1] + se * LEAN_STEP_M
                n[k] = n[k - 1] + sn * LEAN_STEP_M
            # The lean at the base is zero: the cloud stays over its own thermal.
            at_e = self._lookup(base_m, e)
            at_n = self._lookup(base_m, n)
            e = [v - at_e for v in e]
            n = [v - at_n for v in n]
        dt = None if self._t is None else t_s - self._t
        self._t = t_s
        if dt is None or dt < 0.0 or dt > LEAN_MAX_GAP_S or self.smooth_s <= 0.0:
            self._e, self._n = e, n
        elif dt > 0.0:
            a = 1.0 - math.exp(-dt / self.smooth_s)
            self._e = [old + a * (new - old) for old, new in zip(self._e, e)]
            self._n = [old + a * (new - old) for old, new in zip(self._n, n)]

    @staticmethod
    def _lookup(z, table):
        x = max(z, 0.0) / LEAN_STEP_M
        k = int(x)
        if k >= len(table) - 1:
            return table[-1]
        return table[k] + (x - k) * (table[k + 1] - table[k])

    def at(self, z):
        """(east, north) of the lift's centre from its cloud, at height z above ground (m)."""
        return self._lookup(z, self._e), self._lookup(z, self._n)
