"""Good and bad areas: a slow variation of the thermals' number and strength (SPEC stage 2, block 3).

Real days are not even: over tens of kilometres some areas work better than others, and choosing
where to go is part of the flight. Here a smooth field over the globe, the area's quality q,
raises the number and the strength of the thermals born in good areas and lowers them in bad ones.
A pilot sees it as more and bigger clouds where the air is better (a cloud's size goes with its
thermal's `gain`, `clouds.cloud_scale`), and fewer, smaller ones where it is worse.

- The field is value noise in three dimensions, read on the sphere (so it is the same everywhere,
  with no seam and no stretching towards the poles): an octave of `CELL_KM` and one of
  `DETAIL_CELL_KM` at `DETAIL_AMPLITUDE`, so the areas are tens of kilometres across and not a
  regular grid. Its lattice values come from (seed, day): each date has its own map (Juan Luis,
  2026-11-12), and the same seed and date give the same one on every machine.
- q is that noise over its standard deviation (`NOISE_STD`), so q is about a standard normal,
  within `Q_LIMIT`.
- A tile of the field draws `density(q)` = 1 + `DENSITY_SPAN` q times its number of thermals, and
  each thermal born in it has `strength(q)` = 1 + `STRENGTH_SPAN` q times its gain, both read at
  the tile's centre (2 km, a fifth of the smallest octave: the step between neighbours is a few
  per cent). Marked, by Juan Luis's choice: the best 15% of the map has about 1.6 times the
  thermals and 1.2 times the strength, the worst 15% about 0.4 and 0.8. Both average 1, so the
  sky as a whole holds as many thermals as before.
- The areas are in the air's frame, as the thermals are: with wind they drift with it, as an air
  mass does. They are not the ground: that is the terrain triggers (stage 3, and the light
  version in stage 2).

The sink between thermals stays the sky's, not the area's. Where density and strength rise
together the mean mass flux rises with them (`MEAN_FLUX`), and the field's sink takes it into
account. First guesses, to judge by flying. Pure Python: no `xp`.
"""

import math

from .rng import hash_key

SPHERE_RADIUS_KM = 6371.0  # the areas need no ellipsoid, only a smooth place on the globe

AREAS_STREAM = 0x41524541  # part of every lattice key: these values are not any thermal's
CELL_KM = 25.0  # the areas' scale
DETAIL_CELL_KM = 10.0  # a second octave, so they are not a regular grid
DETAIL_AMPLITUDE = 0.5
NOISE_STD = 0.41  # of the two octaves together, measured over the globe (tests pin it)
Q_LIMIT = 3.0
DENSITY_SPAN = 0.58  # q at the best 15% is about 1.05: 1.6 times the thermals
STRENGTH_SPAN = 0.19  # and 1.2 times their strength
MEAN_FLUX = 1.0 + DENSITY_SPAN * STRENGTH_SPAN  # mean of density * strength, q standard
CACHE_LIMIT = 4096  # lattice values and tiles kept, each


def _smooth(x):
    return x * x * (3.0 - 2.0 * x)


class Areas:
    """The map of good and bad areas for one seed and date."""

    __slots__ = ("seed", "day", "_lattice", "_tiles")

    def __init__(self, seed, day):
        self.seed = int(seed)
        self.day = int(day)
        self._lattice = {}
        self._tiles = {}

    def _value(self, octave, ix, iy, iz):
        key = (octave, ix, iy, iz)
        v = self._lattice.get(key)
        if v is None:
            if len(self._lattice) >= CACHE_LIMIT:
                self._lattice.clear()
            h = hash_key(self.seed, self.day, AREAS_STREAM, octave, ix, iy, iz)
            v = (h >> 11) * (2.0 / (1 << 53)) - 1.0  # uniform in [-1, 1)
            self._lattice[key] = v
        return v

    def _octave(self, octave, x, y, z):
        """Value noise at (x, y, z) in lattice units, in [-1, 1]."""
        ix, iy, iz = math.floor(x), math.floor(y), math.floor(z)
        fx, fy, fz = _smooth(x - ix), _smooth(y - iy), _smooth(z - iz)
        v = self._value
        c00 = v(octave, ix, iy, iz) + fx * (v(octave, ix + 1, iy, iz) - v(octave, ix, iy, iz))
        c10 = v(octave, ix, iy + 1, iz) + fx * (v(octave, ix + 1, iy + 1, iz) - v(octave, ix, iy + 1, iz))
        c01 = v(octave, ix, iy, iz + 1) + fx * (v(octave, ix + 1, iy, iz + 1) - v(octave, ix, iy, iz + 1))
        c11 = (v(octave, ix, iy + 1, iz + 1)
               + fx * (v(octave, ix + 1, iy + 1, iz + 1) - v(octave, ix, iy + 1, iz + 1)))
        c0 = c00 + fy * (c10 - c00)
        c1 = c01 + fy * (c11 - c01)
        return c0 + fz * (c1 - c0)

    def noise(self, lat, lon):
        """The two octaves together, before standardizing."""
        la, lo = math.radians(lat), math.radians(lon)
        r_km = SPHERE_RADIUS_KM
        x = r_km * math.cos(la) * math.cos(lo)
        y = r_km * math.cos(la) * math.sin(lo)
        z = r_km * math.sin(la)
        main = self._octave(0, x / CELL_KM, y / CELL_KM, z / CELL_KM)
        detail = self._octave(1, x / DETAIL_CELL_KM, y / DETAIL_CELL_KM, z / DETAIL_CELL_KM)
        return main + DETAIL_AMPLITUDE * detail

    def quality(self, lat, lon):
        """The area's quality q at (lat, lon): about a standard normal, 0 an average area."""
        q = self.noise(lat, lon) / NOISE_STD
        return min(max(q, -Q_LIMIT), Q_LIMIT)

    def at_tile(self, i, j, tile_deg):
        """(density, strength) of the field's tile (i, j), read at its centre."""
        key = (i, j, tile_deg)
        found = self._tiles.get(key)
        if found is None:
            if len(self._tiles) >= CACHE_LIMIT:
                self._tiles.clear()
            found = factors(self.quality((i + 0.5) * tile_deg, (j + 0.5) * tile_deg))
            self._tiles[key] = found
        return found


def factors(q):
    """(density, strength) for an area of quality q: the thermals' number and strength, times."""
    return max(0.0, 1.0 + DENSITY_SPAN * q), max(0.0, 1.0 + STRENGTH_SPAN * q)
