"""Deterministic field of thermals with a life cycle.

Determinism: the same (seed, day, place, time) gives the same thermals on every
machine, whatever the player's path, the order tiles were loaded in, or where
the local frame's origin is. To get that, thermals are generated per *tile* of
a global lat/lon grid and per *time slot*, each (tile, slot) pair with its own
random stream keyed by (seed, day, tile, slot). Positions are stored as
lat/lon and converted to the current local frame only for lookup.

Time t is seconds since 00:00 UTC of `day` (the adapter passes X-Plane's zulu
time); `day` is any integer that identifies the date, e.g. days since
2000-01-01.

Births are a Poisson process in space and time: in each slot of length
`lifetime_max_s`, a tile gets Poisson(density * area * slot / mean lifetime)
thermals, each born at a uniform time in the slot and living a uniform time
between `lifetime_min_s` and `lifetime_max_s` (Allen 2006: updrafts last 5 to
30 min). A thermal alive at t was therefore born in slot floor(t / slot) or
the one before, and on average `density` thermals per unit area are alive at
any time.

Life cycle (the original plugin author's TODO, SPEC "Thermal model"): a thermal
starts narrow and weak, grows to full width and strength, and fades out. The
envelope scales the thermal's radius and its whole perturbation of the
environment smoothly from zero, so no thermal ever appears or disappears
abruptly. The shape constants are a
first guess to be tuned by flying.

Lift is the environment sink plus the sum of each nearby thermal's
perturbation from it. Allen uses only the nearest updraft, which jumps when
two thermals' regions overlap; superposition is continuous and lets nearby
thermals merge into a stronger one, which real thermals do.

Not modeled yet (later phases): drift and lean with the wind (phase 2), daily
cycle of w* and zi (phase 2), terrain triggers (phase 5). Water and other
no-thermal ground is excluded with an optional `accept(lat, lon)` predicate
that the adapter builds from terrain probes.
"""

import math

from . import updraft
from .geo import radii_of_curvature
from .rng import SplitMix64, hash_key

# Life-cycle envelope, as fractions of the thermal's lifetime (tune by flying).
RISE_FRACTION = 0.2  # strength 0 -> 1
DECAY_FRACTION = 0.3  # strength 1 -> 0 at the end
WIDEN_FRACTION = 0.4  # radius gain RADIUS_START -> 1
RADIUS_START = 0.6

# Clamp the per-thermal gains so a lognormal tail cannot make giants.
WGAIN_RANGE = (0.3, 2.5)
RGAIN_RANGE = (0.5, 2.0)


def smoothstep(x):
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    return x * x * (3.0 - 2.0 * x)


def life_envelope(tau):
    """Strength and radius factors at life fraction tau in [0, 1]; (0, 0) outside."""
    if tau < 0.0 or tau >= 1.0:
        return 0.0, 0.0
    strength = smoothstep(tau / RISE_FRACTION) * smoothstep((1.0 - tau) / DECAY_FRACTION)
    radius = RADIUS_START + (1.0 - RADIUS_START) * smoothstep(tau / WIDEN_FRACTION)
    return strength, radius


def _mean_life_flux(steps=2000):
    """Life-average of strength * radius^2: a thermal's mass flux relative to full size."""
    total = 0.0
    for k in range(steps):
        s, rf = life_envelope((k + 0.5) / steps)
        total += s * rf * rf
    return total / steps


MEAN_LIFE_FLUX = _mean_life_flux()


class FieldConfig:
    """Parameters of a thermal field. All defaults are first guesses to tune."""

    __slots__ = ("seed", "day", "tile_deg", "density_per_km2", "lifetime_min_s",
                 "lifetime_max_s", "wgain_sigma", "rgain_sigma", "range_m", "cell_m")

    def __init__(self, seed=0, day=0, tile_deg=0.02, density_per_km2=None,
                 lifetime_min_s=300.0, lifetime_max_s=1800.0, wgain_sigma=0.3,
                 rgain_sigma=0.2, range_m=10000.0, cell_m=400.0, zi_ref_m=1400.0):
        self.seed = int(seed)
        self.day = int(day)
        self.tile_deg = float(tile_deg)
        if density_per_km2 is None:
            # Allen Eq. 20 at z/zi = 0.4 for a typical day (4.5 per km2 at zi = 1400 m).
            density_per_km2 = updraft.allen_density_per_m2(zi_ref_m) * 1e6
        self.density_per_km2 = float(density_per_km2)
        self.lifetime_min_s = float(lifetime_min_s)
        self.lifetime_max_s = float(lifetime_max_s)
        self.wgain_sigma = float(wgain_sigma)
        self.rgain_sigma = float(rgain_sigma)
        self.range_m = float(range_m)
        self.cell_m = float(cell_m)

    @property
    def slot_s(self):
        return self.lifetime_max_s

    @property
    def mean_lifetime_s(self):
        return 0.5 * (self.lifetime_min_s + self.lifetime_max_s)


class Thermal:
    """One thermal. lat/lon/birth/death/gains are fixed; e/n follow the local frame."""

    __slots__ = ("lat", "lon", "birth", "death", "wgain", "rgain", "e", "n", "cell")

    def __init__(self, lat, lon, birth, death, wgain, rgain):
        self.lat = lat
        self.lon = lon
        self.birth = birth
        self.death = death
        self.wgain = wgain
        self.rgain = rgain
        self.e = 0.0
        self.n = 0.0
        self.cell = None

    def envelope(self, t):
        """Life-cycle (strength, radius) factors at time t; (0, 0) if not alive."""
        return life_envelope((t - self.birth) / (self.death - self.birth))


def tile_area_m2(i, j, tile_deg):
    """Area of tile (i, j) of the global grid, from the radii at its centre latitude."""
    lat_c = (i + 0.5) * tile_deg
    m, n = radii_of_curvature(lat_c)
    d = math.radians(tile_deg)
    return (m * d) * (n * math.cos(math.radians(lat_c)) * d)


def generate_tile(config, i, j, slot, accept=None):
    """Thermals born in tile (i, j) during time slot `slot`. Pure function."""
    rng = SplitMix64(hash_key(config.seed, config.day, i, j, slot))
    area_km2 = tile_area_m2(i, j, config.tile_deg) * 1e-6
    lam = config.density_per_km2 * area_km2 * config.slot_s / config.mean_lifetime_s
    count = rng.poisson(lam)
    lat0 = i * config.tile_deg
    lon0 = j * config.tile_deg
    t0 = slot * config.slot_s
    thermals = []
    for _ in range(count):
        # Draw every number before filtering, so `accept` never shifts the stream.
        lat = lat0 + config.tile_deg * rng.uniform()
        lon = lon0 + config.tile_deg * rng.uniform()
        birth = t0 + config.slot_s * rng.uniform()
        life = rng.uniform_range(config.lifetime_min_s, config.lifetime_max_s)
        wgain = min(max(rng.lognormal_unit_mean(config.wgain_sigma), WGAIN_RANGE[0]), WGAIN_RANGE[1])
        rgain = min(max(rng.lognormal_unit_mean(config.rgain_sigma), RGAIN_RANGE[0]), RGAIN_RANGE[1])
        if accept is not None and not accept(lat, lon):
            continue
        thermals.append(Thermal(lat, lon, birth, birth + life, wgain, rgain))
    return thermals


class ThermalField:
    """Thermals around the player, kept in a spatial grid in the local frame.

    Call `update` every second or so (outside the per-frame path if possible);
    call `lift_at` per sample point per frame.
    """

    def __init__(self, config, frame, accept=None):
        self.config = config
        self.frame = frame
        self.accept = accept
        self._tiles = {}  # (i, j, slot) -> list of Thermal
        self._grid = {}  # (cx, cy) -> list of Thermal
        # Effective full-size updrafts per m2 for the environment sink (Eq. 21):
        # life-cycle average of strength * radius^2 times E[rgain^2] (lognormal).
        self._flux_density = (config.density_per_km2 * 1e-6 * MEAN_LIFE_FLUX
                              * math.exp(config.rgain_sigma ** 2))

    # --- loading -----------------------------------------------------------

    def wanted_keys(self, t, lat, lon):
        c = self.config
        m, n = radii_of_curvature(lat)
        tile_h = math.radians(c.tile_deg) * m
        tile_w = math.radians(c.tile_deg) * n * max(math.cos(math.radians(lat)), 1e-6)
        di = math.ceil(c.range_m / tile_h)
        dj = math.ceil(c.range_m / tile_w)
        i0 = math.floor(lat / c.tile_deg)
        j0 = math.floor(lon / c.tile_deg)
        s = math.floor(t / c.slot_s)
        return {(i, j, slot)
                for i in range(i0 - di, i0 + di + 1)
                for j in range(j0 - dj, j0 + dj + 1)
                for slot in (s - 1, s)}

    def update(self, t, lat, lon):
        """Load tiles and slots around (lat, lon) at time t, drop the rest.

        Returns True if the set of thermals changed.
        """
        wanted = self.wanted_keys(t, lat, lon)
        changed = False
        for key in [k for k in self._tiles if k not in wanted]:
            for th in self._tiles.pop(key):
                self._grid_remove(th)
            changed = True
        for key in wanted:
            if key not in self._tiles:
                thermals = generate_tile(self.config, *key, accept=self.accept)
                for th in thermals:
                    th.e, th.n = self.frame.to_enu(th.lat, th.lon)
                    self._grid_add(th)
                self._tiles[key] = thermals
                changed = True
        return changed

    def set_frame(self, frame):
        """Move the local origin; recompute every loaded thermal's position."""
        self.frame = frame
        self._grid.clear()
        for thermals in self._tiles.values():
            for th in thermals:
                th.e, th.n = frame.to_enu(th.lat, th.lon)
                self._grid_add(th)

    def _grid_add(self, th):
        cell = (math.floor(th.e / self.config.cell_m), math.floor(th.n / self.config.cell_m))
        th.cell = cell
        self._grid.setdefault(cell, []).append(th)

    def _grid_remove(self, th):
        bucket = self._grid.get(th.cell)
        if bucket is not None:
            bucket.remove(th)
            if not bucket:
                del self._grid[th.cell]

    # --- queries -----------------------------------------------------------

    def thermals(self):
        for thermals in self._tiles.values():
            yield from thermals

    def alive(self, t):
        return [th for th in self.thermals() if th.birth <= t < th.death]

    def environment_sink(self, z, wstar, zi):
        return updraft.environment_sink(z, zi, wstar, self._flux_density)

    def nearest(self, e, n, t, max_m):
        """Nearest thermal alive at t within max_m of (e, n): (thermal, distance) or (None, inf).

        For instruments and test tools, not for the per-frame path.
        """
        cell_m = self.config.cell_m
        k = math.ceil(max_m / cell_m)
        cx = math.floor(e / cell_m)
        cy = math.floor(n / cell_m)
        best, best_r = None, math.inf
        for ix in range(cx - k, cx + k + 1):
            for iy in range(cy - k, cy + k + 1):
                for th in self._grid.get((ix, iy), ()):
                    if th.birth <= t < th.death:
                        r = math.hypot(e - th.e, n - th.n)
                        if r < best_r and r <= max_m:
                            best, best_r = th, r
        return best, best_r

    def alive_within(self, e, n, t, max_m):
        """(thermal, distance) of every thermal alive at t within max_m of (e, n).

        For the training markers and test tools, not for the per-frame path.
        """
        cell_m = self.config.cell_m
        k = math.ceil(max_m / cell_m)
        cx = math.floor(e / cell_m)
        cy = math.floor(n / cell_m)
        found = []
        for ix in range(cx - k, cx + k + 1):
            for iy in range(cy - k, cy + k + 1):
                for th in self._grid.get((ix, iy), ()):
                    if th.birth <= t < th.death:
                        r = math.hypot(e - th.e, n - th.n)
                        if r <= max_m:
                            found.append((th, r))
        return found

    def lift_at(self, e, n, z, t, wstar, zi):
        """Vertical air velocity (m/s) at local (e, n), height z AGL, time t.

        wstar and zi are the convective scales of the moment (m/s, m AGL).
        """
        if zi <= 0.0 or z <= 0.0 or z >= zi:
            return 0.0
        we = updraft.environment_sink(z, zi, wstar, self._flux_density)
        reach = updraft.influence_radius(z, zi, RGAIN_RANGE[1])
        cell_m = self.config.cell_m
        k = math.ceil(reach / cell_m)
        cx = math.floor(e / cell_m)
        cy = math.floor(n / cell_m)
        grid = self._grid
        total = we
        for ix in range(cx - k, cx + k + 1):
            for iy in range(cy - k, cy + k + 1):
                bucket = grid.get((ix, iy))
                if bucket is None:
                    continue
                for th in bucket:
                    if t < th.birth or t >= th.death:
                        continue
                    r = math.hypot(e - th.e, n - th.n)
                    if r >= reach:
                        continue
                    s, rf = th.envelope(t)
                    if s == 0.0:
                        continue
                    # Scale the whole perturbation, not wgain: Allen's stretch toward
                    # the environment sink (Eq. 23) leaves a residual of about |we|
                    # when wgain -> 0, which would jump at birth and death.
                    w = updraft.updraft_velocity(r, z, zi, wstar, th.wgain, th.rgain * rf, we)
                    total += s * (w - we)
        return total
