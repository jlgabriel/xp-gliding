"""Coordinate system of the engine.

Every engine position is in a local **east-north-up** (ENU) frame, in meters,
around an origin (lat0, lon0) on the WGS84 ellipsoid:

  e  east of the origin (m)
  n  north of the origin (m)
  z  height above ground level (m); MSL only where a function says so

Lat/lon are converted with the ellipsoid's radii of curvature at the origin
latitude (meridional M and prime vertical N, with the cos(lat0) factor on
longitude). The mapping is exact at the origin and is a bijection everywhere,
so positions stay consistent as long as everything goes through the same
frame. What degrades with distance is the scale of east distances, which is off
by about tan(lat0) * dlat: 0.3% at 20 km north or south of the origin at 45 deg,
i.e. 0.3 m over 100 m. The adapter moves the origin when the aircraft gets far
from it.

Rule for the adapter: aircraft and object *positions* always go through
lat/lon and this frame, never through X-Plane's local OpenGL x/z (X-Plane uses
its own projection, and mixing the two would misplace thermals). X-Plane's
local frame is (x east, y up, z south); `enu_from_xp_local` converts
*directions and velocities* such as `local_vx/vy/vz`, not positions.

Headings follow aviation and X-Plane (`sim/flightmodel/position/psi`):
degrees clockwise from true north. Roll follows X-Plane's `phi`: positive is
right wing down.
"""

import math

# WGS84
A_WGS84 = 6378137.0
F_WGS84 = 1.0 / 298.257223563
E2_WGS84 = F_WGS84 * (2.0 - F_WGS84)


def radii_of_curvature(lat_deg):
    """Meridional (M) and prime vertical (N) radii of curvature at a latitude (m)."""
    s = math.sin(math.radians(lat_deg))
    w = 1.0 - E2_WGS84 * s * s
    n = A_WGS84 / math.sqrt(w)
    m = A_WGS84 * (1.0 - E2_WGS84) / (w * math.sqrt(w))
    return m, n


def wrap_lon_deg(lon):
    """Wrap a longitude difference or value into [-180, 180)."""
    return (lon + 180.0) % 360.0 - 180.0


class LocalFrame:
    """East-north-up tangent frame around (lat0, lon0)."""

    __slots__ = ("lat0", "lon0", "m_per_deg_lat", "m_per_deg_lon")

    def __init__(self, lat0, lon0):
        self.lat0 = float(lat0)
        self.lon0 = wrap_lon_deg(float(lon0))
        m, n = radii_of_curvature(self.lat0)
        self.m_per_deg_lat = math.radians(1.0) * m
        self.m_per_deg_lon = math.radians(1.0) * n * math.cos(math.radians(self.lat0))

    def to_enu(self, lat, lon):
        """(lat, lon) in degrees -> (e, n) in meters."""
        e = wrap_lon_deg(lon - self.lon0) * self.m_per_deg_lon
        n = (lat - self.lat0) * self.m_per_deg_lat
        return e, n

    def to_latlon(self, e, n):
        """(e, n) in meters -> (lat, lon) in degrees."""
        lat = self.lat0 + n / self.m_per_deg_lat
        lon = wrap_lon_deg(self.lon0 + e / self.m_per_deg_lon)
        return lat, lon

    def distance_to_origin(self, lat, lon):
        e, n = self.to_enu(lat, lon)
        return math.hypot(e, n)


def heading_vectors(heading_deg):
    """Unit vectors (forward_e, forward_n, right_e, right_n) for a true heading."""
    h = math.radians(heading_deg)
    s, c = math.sin(h), math.cos(h)
    return s, c, c, -s


def enu_from_xp_local(x, y, z):
    """Vector in X-Plane's local OpenGL axes (x east, y up, z south) -> (e, n, up).

    For directions and velocities only; see the module docstring.
    """
    return x, -z, y
