"""The wind carries the sky (docs/SPEC.md "Wind").

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
Same seed, date, place, time and offset: same sky. The offset starts at zero with each
flight, and the adapter publishes it so the test pilot's oracles can rebuild the sky.

Pure Python: no `xp`.
"""

import math

from .geo import radii_of_curvature, wrap_lon_deg

# A longer step of the clock than this is not flying: the time was changed, or the sim was
# stopped. The air does not travel across it.
MAX_STEP_S = 5.0


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
