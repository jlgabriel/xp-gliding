"""Deterministic field of thermals with a life cycle.

Determinism: the same (seed, day, place, time) gives the same thermals on every
machine, whatever the player's path, the order tiles were loaded in, or where
the local frame's origin is. To get that, thermals are generated per *tile* of
a global lat/lon grid and per *time slot*, each (tile, slot) pair with its own
random stream keyed by (seed, day, tile, slot). Positions are stored as
lat/lon and converted to the current local frame only for lookup.

Time t is seconds since 00:00 UTC of `day`, and `day` is any integer that identifies
the date, e.g. days since 2000-01-01. The adapter passes the local date with
`sky_time`, so t runs past 24 h (or starts below 0) rather than wrap at zulu midnight
in the middle of a local day.

Births are a Poisson process in space and time: in each slot of length
`lifetime_max_s`, a tile gets Poisson(density * area * slot / mean lifetime)
thermals, each born at a uniform time in the slot and living a uniform time
between `lifetime_min_s` and `lifetime_max_s` (Allen 2006: updrafts last 5 to
30 min). A thermal alive at t was therefore born in slot floor(t / slot) or
the one before, and on average `density` thermals per unit area are alive at
any time.

The density follows the day's depth as Allen's does (Eq. 20: N = 0.6 / (zi r2), with r2 in
proportion to zi, so N goes as 1 / zi^2): a deeper day has wider thermals farther apart, and
the share of the sky they cover, and with it the sink between them, stays the same. It is
anchored to the sky as tuned and flown, 4.5 per km2 at zi = 2000 m, which is Allen's for
zi = 1400 m (`thermal_density_per_km2`). So the number of thermals, and where each is, depend
on zi: the same seed and date give another sky at another depth (Juan Luis, 2026-11-09).

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

Sky profiles. `SkyProfile` shapes the sky without moving anything in it: the same random
stream draws the same thermals in the same places, then the thermals that carry a cloud
can be stretched and the others thinned out and weakened. The default changes nothing.
See `SkyProfile` for what the numbers mean, and notes/phase2.md for how they were measured.

The wind carries the whole sky from outside (`wind.py`): this module is in the air's frame.
The lean is from outside too: the field is the sky at the clouds' base, and whoever asks at a
height shifts the point by `wind.Lean` first.

The sun (`sun.py`): with `FieldConfig.sun_min_deg` set, a thermal is born only while the sun is
that high at its place and birth, and the environment sink fades with the share of thermals alive
(`ThermalField.sink_share`). The strength of the moment is the caller's w* (`daycycle.py`, step A).

The depth of the moment (`FieldConfig.depth_cycle`, the daily cycle's step B, off by default): a
thermal is as deep as the day was at its birth, `Thermal.depth` of the field's zi, which
`daycycle.DayCycle.depth_share` gives. Its whole profile is Allen's for that zi: a morning thermal
is low and narrow, and keeps the depth it was born with for life, so its cloud keeps one base and
the bases rise through the day as later thermals are born deeper. The sink between thermals is
Allen's for the zi of the moment at the glider (`ThermalField.depth_share`). The number of
thermals stays the one drawn for the field's zi: a morning sky holds as many as the afternoon's,
narrower, so less of it rises and less sinks (notes/phase5.md, *Step B*).

Good and bad areas (`FieldConfig.areas`, `areas.py`): a smooth map over tens of kilometres, from
the seed and the date, raises the number of thermals a tile draws and their strength in good areas,
and lowers both in bad ones; the sky as a whole keeps as many. Off in a `FieldConfig` by default, so
the tools and tests that give none get the sky as before.

Not modeled yet: terrain triggers (stage 3). Ground where no
thermal is born (the adapter: water) is excluded with an optional `accept(lat, lon, birth)`
predicate, which never shifts the random stream; nor does the sun.
"""

import math

from . import sun, updraft
from .areas import MEAN_FLUX as AREAS_MEAN_FLUX, Areas
from .daycycle import DayCycle
from .geo import radii_of_curvature
from .rng import SplitMix64, hash_key

# Life-cycle envelope, as fractions of the thermal's lifetime (tune by flying).
RISE_FRACTION = 0.2  # strength 0 -> 1
DECAY_FRACTION = 0.3  # strength 1 -> 0 at the end
WIDEN_FRACTION = 0.4  # radius gain RADIUS_START -> 1
RADIUS_START = 0.6

# Sharper thermal edges (stage 2, first guesses to judge by flying, with the kick in
# engine/injection.py): a sink ring around every thermal, from r2 out to (1 + EDGE_RING_WIDTH) r2
# and deepest halfway across at EDGE_RING times its mean updraft, and the sink between thermals
# times EDGE_SINK_GAIN. Both depart from Allen's conservation of mass, whose ring is weak and only
# high up, and whose sink between thermals is -0.14 m/s in the wide sky (notes/SPEC.md, open
# questions). The ring was 0.5 and r2 wide until Juan Luis felt it pull down too long and too far
# out on leaving a thermal (2026-11-12), and 0.3 until it competed with a narrow thermal's lift
# for a glider circling wide in it, on his hand flights the same day (0.2 is his).
EDGE_RING = 0.2
EDGE_RING_WIDTH = 0.5
EDGE_SINK_GAIN = 2.0

# Clamp the per-thermal gains so a lognormal tail cannot make giants.
WGAIN_RANGE = (0.3, 2.5)
RGAIN_RANGE = (0.5, 2.0)

# Which thermals carry a cloud, from their drawn numbers: the largest mass flux, and a life
# long enough for a cloud to form and fade (notes/phase2.md). `clouds.CloudParams` defaults
# to these.
CARRIER_MIN_FLUX = 2.0
CARRIER_MIN_LIFE_S = 720.0

# Allen's mean updraft dies here (Eq. 11), which is where clouds have their base by default.
LIFT_TOP_ZZI = 1.0 / 1.1

BLUE_STREAM = 1  # last part of the key of the second random stream, for thinning

# Below a thermal's floor, in a valley deeper than the sky's level: lift as at this height (m),
# so a thermal still comes from the ground under it, weakly, and nothing jumps at the floor.
LOW_HEIGHT_M = 100.0


def sky_time(zulu_s, local_s):
    """t for the local date: zulu time, not wrapped at zulu midnight.

    A day's sky is keyed by its local date, which changes at local midnight. Zulu time
    wraps elsewhere, 17:00 local at Hobbs, and every thermal would change at once.
    """
    return local_s - ((local_s - zulu_s + 43200.0) % 86400.0 - 43200.0)


def height_in_thermal(thermal, z, ground_m):
    """The height a thermal's profile is read at, for a point z metres over ground_m (m MSL).

    Allen's z is over flat ground, and the lift has to end where its cloud is, whatever the
    ground under the glider is doing. So a thermal with a `floor_m` measures z from there.
    The adapter sets it so that the cloud's base is at the sky's `cloud_base_zzi`: over any ground
    the lift at a cloud's base is what it is on the flat. With no floor, or no ground, it is z.
    """
    if thermal.floor_m is None or ground_m is None:
        return z
    return max(z + (ground_m - thermal.floor_m), min(z, LOW_HEIGHT_M))


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


def envelope_flux(tau):
    """strength * radius^2 at life fraction tau: a thermal's mass flux relative to full size."""
    s, rf = life_envelope(tau)
    return s * rf * rf


def _mean_life_flux(steps=2000):
    """Life-average of `envelope_flux`."""
    return sum(envelope_flux((k + 0.5) / steps) for k in range(steps)) / steps


MEAN_LIFE_FLUX = _mean_life_flux()


def is_carrier(wgain, rgain, life_s):
    """Does a thermal with these drawn numbers carry a cloud?"""
    return wgain * rgain * rgain >= CARRIER_MIN_FLUX and life_s >= CARRIER_MIN_LIFE_S


class SkyProfile:
    """How a sky differs from the one the random stream draws. Defaults: not at all.

    Deviations from Allen's model, so they stay on record (notes/SPEC.md "Thermal model"):
    - `carrier_stretch` widens a thermal that carries a cloud by this factor, shape and all:
      the lift at r is the lift Allen gives at r / stretch. Raising `rgain` instead would
      follow his Eq. 13, where the core ratio grows with r2, so a wide thermal has a lower
      peak and a flat top with a steep edge. The idea is the same strength, only wider.
    - `carrier_gain` multiplies its strength. The stretch keeps the peak, so 1.0 is enough.
    - `blue_keep` is the share of the other thermals that exist at all. They are blue, with
      no cloud to mark them, and at Allen's density they hold most of the good air, so they
      pull a pilot away from the clouds. The density of `FieldConfig` stays the number drawn.
    - `blue_gain` and `blue_stretch` make those that remain weaker and narrower.
    - `cloud_base_zzi` is the height of the clouds' base, as z/zi. It changes no lift. At the
      default the base is where Allen's lift reaches zero, so no glider can ever get there:
      climbs end about 400 m below it. A lower base is where a typical thermal runs out.

    The environment sink follows from all this by conservation of mass (`mean_flux_gain`),
    so it is an outcome and not a parameter.
    """

    __slots__ = ("carrier_stretch", "carrier_gain", "blue_keep", "blue_gain", "blue_stretch",
                 "cloud_base_zzi")

    def __init__(self, carrier_stretch=1.0, carrier_gain=1.0, blue_keep=1.0, blue_gain=1.0,
                 blue_stretch=1.0, cloud_base_zzi=LIFT_TOP_ZZI):
        self.carrier_stretch = float(carrier_stretch)
        self.carrier_gain = float(carrier_gain)
        self.blue_keep = float(blue_keep)
        self.blue_gain = float(blue_gain)
        self.blue_stretch = float(blue_stretch)
        self.cloud_base_zzi = float(cloud_base_zzi)

    @property
    def max_stretch(self):
        return max(self.carrier_stretch, self.blue_stretch)


# The skies that can be chosen by name (`"sky"` in the plugin's config.json).
SKIES = {
    "default": SkyProfile(),
    # First guesses to judge by flying, measured offline and flown a little (notes/phase2.md).
    "wide_carriers": SkyProfile(carrier_stretch=2.0, blue_keep=0.15, blue_gain=0.6, blue_stretch=0.75,
                                cloud_base_zzi=0.75),
    "medium_carriers": SkyProfile(carrier_stretch=1.5, blue_keep=0.15, blue_gain=0.6, blue_stretch=0.75,
                                  cloud_base_zzi=0.75),
}
SKY_NAMES = tuple(SKIES)  # in a fixed order, to say which one in a dataref


def sky_named(name):
    """The profile of that name; the default one for a name it does not know."""
    return SKIES.get(name, SKIES["default"])


def sky_index(name):
    """The place of that sky in SKY_NAMES; the default one's for a name it does not know."""
    return SKY_NAMES.index(name) if name in SKIES else SKY_NAMES.index("default")


# The depth the sky was tuned and flown at, and its density there: Allen's Eq. 20 at z/zi = 0.4
# for zi = 1400 m, the first choice, kept at 2000 m when that became the default.
ZI_TUNED_M = 2000.0
DENSITY_TUNED_PER_KM2 = updraft.allen_density_per_m2(1400.0) * 1e6


def thermal_density_per_km2(zi_m):
    """Thermals alive per km2 for a day zi_m deep (m): Allen's 1 / zi^2, through the tuned sky."""
    return DENSITY_TUNED_PER_KM2 * (ZI_TUNED_M / zi_m) ** 2


class FieldConfig:
    """Parameters of a thermal field. All defaults are first guesses to tune.

    zi_m is the day's depth the field is for, which sets its density; ask `lift_at` with the
    same zi. density_per_km2, if given, replaces that. With depth_cycle (and the sun on), zi_m
    is the afternoon's, and each thermal is as deep as the day was at its birth. With areas, the
    good and bad areas of `areas.py` for this seed and day (`areas` is then an `Areas`, else None).
    """

    __slots__ = ("seed", "day", "tile_deg", "zi_m", "density_per_km2", "lifetime_min_s",
                 "lifetime_max_s", "wgain_sigma", "rgain_sigma", "range_m", "cell_m", "sky",
                 "sun_min_deg", "depth_cycle", "areas")

    def __init__(self, seed=0, day=0, tile_deg=0.02, density_per_km2=None,
                 lifetime_min_s=300.0, lifetime_max_s=1800.0, wgain_sigma=0.3,
                 rgain_sigma=0.2, range_m=10000.0, cell_m=400.0, zi_m=ZI_TUNED_M, sky=None,
                 sun_min_deg=None, depth_cycle=False, areas=False):
        self.seed = int(seed)
        # Days since 1 January (X-Plane's local date). With sun_min_deg it places the sun.
        self.day = int(day)
        self.tile_deg = float(tile_deg)
        self.zi_m = float(zi_m)
        if density_per_km2 is None:
            density_per_km2 = thermal_density_per_km2(self.zi_m)
        self.density_per_km2 = float(density_per_km2)
        self.lifetime_min_s = float(lifetime_min_s)
        self.lifetime_max_s = float(lifetime_max_s)
        self.wgain_sigma = float(wgain_sigma)
        self.rgain_sigma = float(rgain_sigma)
        self.range_m = float(range_m)
        self.cell_m = float(cell_m)
        self.sky = sky if sky is not None else SKIES["default"]
        # A thermal is born only with the sun at least this high (degrees); None: at any hour.
        self.sun_min_deg = None if sun_min_deg is None else float(sun_min_deg)
        # Each thermal as deep as the day at its birth (daily cycle, step B). Only with the sun.
        self.depth_cycle = bool(depth_cycle) and self.sun_min_deg is not None
        # Good and bad areas: the thermals' number and strength vary over tens of km.
        self.areas = Areas(self.seed, self.day) if areas else None

    def cycle(self):
        """The daily cycle of this sky (`daycycle.DayCycle`), or None with the sun off."""
        return None if self.sun_min_deg is None else DayCycle(self.day, onset_deg=self.sun_min_deg)

    @property
    def slot_s(self):
        return self.lifetime_max_s

    @property
    def mean_lifetime_s(self):
        return 0.5 * (self.lifetime_min_s + self.lifetime_max_s)


def carrier_flux_share(config):
    """Mean of `wgain * rgain^2` over the alive thermals, counting only those that carry a cloud.

    A lognormal's partial mean, times the share of alive thermals that live long enough:
    they are alive in proportion to their lifetime, which is uniform. The clamps on the
    gains are left out, as in the sink of the default sky; tests compare it with a large sample.
    """
    wvar, rvar = config.wgain_sigma ** 2, config.rgain_sigma ** 2
    mu = -0.5 * wvar - rvar  # of ln(wgain * rgain^2), whose variance is wvar + 4 rvar
    s2 = wvar + 4.0 * rvar
    partial = (math.exp(rvar)
               * 0.5 * math.erfc((math.log(CARRIER_MIN_FLUX) - mu - s2) / math.sqrt(2.0 * s2)))
    lo, hi = config.lifetime_min_s, config.lifetime_max_s
    long_enough = min(max(CARRIER_MIN_LIFE_S, lo), hi)
    return partial * (hi * hi - long_enough * long_enough) / (hi * hi - lo * lo)


def mean_flux_gain(config):
    """Mean of each drawn thermal's mass flux relative to a mean-size one (thinned ones are 0).

    It is what scales the environment sink: everything that goes up comes down around it.
    """
    sky = config.sky
    blue = sky.blue_keep * sky.blue_gain * sky.blue_stretch ** 2
    carrier = sky.carrier_gain * sky.carrier_stretch ** 2
    return math.exp(config.rgain_sigma ** 2) * blue + carrier_flux_share(config) * (carrier - blue)


class Thermal:
    """One thermal. lat/lon/birth/death/gains are fixed; e/n follow the local frame.

    wgain and rgain are as drawn, which is what decides a cloud and its size. gain and
    stretch are what the sky's profile does to the lift (`SkyProfile`). floor_m, if set from
    outside, is where its height is measured from (`height_in_thermal`), m MSL. depth is its zi
    as a share of the field's: 1, or the day's at its birth with `FieldConfig.depth_cycle`.
    """

    __slots__ = ("lat", "lon", "birth", "death", "wgain", "rgain", "gain", "stretch", "e", "n",
                 "cell", "floor_m", "depth")

    def __init__(self, lat, lon, birth, death, wgain, rgain, gain=1.0, stretch=1.0, depth=1.0):
        self.lat = lat
        self.lon = lon
        self.birth = birth
        self.death = death
        self.wgain = wgain
        self.rgain = rgain
        self.gain = gain
        self.stretch = stretch
        self.e = 0.0
        self.n = 0.0
        self.cell = None
        self.floor_m = None
        self.depth = depth

    def zi(self, zi):
        """Its own zi (m) in a field made for zi."""
        return zi * self.depth

    def envelope(self, t):
        """Life-cycle (strength, radius) factors at time t; (0, 0) if not alive."""
        return life_envelope((t - self.birth) / (self.death - self.birth))


def tile_area_m2(i, j, tile_deg):
    """Area of tile (i, j) of the global grid, from the radii at its centre latitude."""
    lat_c = (i + 0.5) * tile_deg
    m, n = radii_of_curvature(lat_c)
    d = math.radians(tile_deg)
    return (m * d) * (n * math.cos(math.radians(lat_c)) * d)


def generate_tile(config, i, j, slot, accept=None, cycle=None):
    """Thermals born in tile (i, j) during time slot `slot`. Pure function.

    cycle: the sky's `DayCycle`, which gives each thermal its depth with `config.depth_cycle`;
    made here if not given.
    """
    if config.depth_cycle and cycle is None:
        cycle = config.cycle()
    rng = SplitMix64(hash_key(config.seed, config.day, i, j, slot))
    area_km2 = tile_area_m2(i, j, config.tile_deg) * 1e-6
    lam = config.density_per_km2 * area_km2 * config.slot_s / config.mean_lifetime_s
    area_strength = 1.0
    if config.areas is not None:
        area_density, area_strength = config.areas.at_tile(i, j, config.tile_deg)
        lam *= area_density
    count = rng.poisson(lam)
    lat0 = i * config.tile_deg
    lon0 = j * config.tile_deg
    t0 = slot * config.slot_s
    sky = config.sky
    # A stream of its own, so thinning moves nothing: the thermals kept are as today's.
    thin = None
    if sky.blue_keep < 1.0:
        thin = SplitMix64(hash_key(config.seed, config.day, i, j, slot, BLUE_STREAM))
    thermals = []
    for _ in range(count):
        # Draw every number before filtering, so `accept` never shifts the stream.
        lat = lat0 + config.tile_deg * rng.uniform()
        lon = lon0 + config.tile_deg * rng.uniform()
        birth = t0 + config.slot_s * rng.uniform()
        life = rng.uniform_range(config.lifetime_min_s, config.lifetime_max_s)
        wgain = min(max(rng.lognormal_unit_mean(config.wgain_sigma), WGAIN_RANGE[0]), WGAIN_RANGE[1])
        rgain = min(max(rng.lognormal_unit_mean(config.rgain_sigma), RGAIN_RANGE[0]), RGAIN_RANGE[1])
        if is_carrier(wgain, rgain, life):
            gain, stretch = sky.carrier_gain, sky.carrier_stretch
        else:
            if thin is not None and thin.uniform() >= sky.blue_keep:
                continue
            gain, stretch = sky.blue_gain, sky.blue_stretch
        gain *= area_strength
        if config.sun_min_deg is not None and not sun.sunlit(lat, lon, config.day, birth,
                                                              config.sun_min_deg):
            continue
        if accept is not None and not accept(lat, lon, birth):
            continue
        depth = cycle.depth_share(lat, lon, birth) if config.depth_cycle else 1.0
        thermals.append(Thermal(lat, lon, birth, birth + life, wgain, rgain, gain, stretch, depth))
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
        # life-cycle average of strength * radius^2 times the mean flux of a thermal.
        # With areas, more thermals are stronger too, so the mean flux is higher (`areas.MEAN_FLUX`).
        self._flux_density = (config.density_per_km2 * 1e-6 * MEAN_LIFE_FLUX
                              * mean_flux_gain(config)
                              * (AREAS_MEAN_FLUX if config.areas is not None else 1.0))
        self._max_stretch = config.sky.max_stretch
        # The share of a full day's thermals alive, which scales the sink between them. 1 with
        # no sun; with it, set by `update`.
        self.sink_share = 1.0
        # The sharper thermal edges (switch `edge_enabled`): set from outside, read by lift_at.
        self.ring = 0.0  # a sink ring around every thermal, of this share of its mean updraft
        self.sink_gain = 1.0  # the sink between thermals, times this
        self._share = None
        if config.sun_min_deg is not None:
            self._share = sun.ThermalShare(config.lifetime_min_s, config.lifetime_max_s, envelope_flux,
                                           min_deg=config.sun_min_deg)
        # The daily cycle: the strength of the moment as a share of the day's peak (daycycle.py).
        self.cycle = config.cycle()
        # zi of the moment at the glider over the field's, for the sink between thermals. 1 with
        # no depth cycle; with it, set by `update`.
        self.depth_share = 1.0

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

        Returns True if the set of thermals changed. With the sun, also sets `sink_share`, and
        with the depth cycle `depth_share`.
        """
        if self._share is not None:
            self.sink_share = self._share.at(lat, lon, self.config.day, t)
        if self.config.depth_cycle:
            self.depth_share = self.cycle.depth_share(lat, lon, t)
        wanted = self.wanted_keys(t, lat, lon)
        changed = False
        for key in [k for k in self._tiles if k not in wanted]:
            for th in self._tiles.pop(key):
                self._grid_remove(th)
            changed = True
        for key in wanted:
            if key not in self._tiles:
                thermals = generate_tile(self.config, *key, accept=self.accept, cycle=self.cycle)
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

    def loaded_count(self):
        """How many thermals are loaded, without visiting each."""
        return sum(len(thermals) for thermals in self._tiles.values())

    def alive(self, t):
        return [th for th in self.thermals() if th.birth <= t < th.death]

    def environment_sink(self, z, wstar, zi):
        """The sink of a full day at z, which each thermal's profile is drawn against. The air
        between thermals sinks at this times `sink_share`, at the zi of the moment."""
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

    def lift_at(self, e, n, z, t, wstar, zi, ground_m=None):
        """Vertical air velocity (m/s) at local (e, n), height z AGL, time t.

        wstar is the convective velocity of the moment (m/s) and zi the field's depth (m AGL),
        which each thermal reads at its own `depth`. ground_m is the
        ground's height MSL under the point: with it, a thermal with a floor is read at its
        own height (`height_in_thermal`). The sink between thermals stays with z, and is
        the one for the zi of the moment (`depth_share`).
        """
        if zi <= 0.0 or z <= 0.0 or (z >= zi and ground_m is None):
            return 0.0
        we = updraft.environment_sink(z, zi * self.depth_share, wstar, self._flux_density)
        # With floors a thermal can be at any height of its own, so the widest of them all.
        reach_z = z if ground_m is None else 0.999 * zi
        reach = updraft.influence_radius(reach_z, zi, RGAIN_RANGE[1]) * self._max_stretch
        cell_m = self.config.cell_m
        k = math.ceil(reach / cell_m)
        cx = math.floor(e / cell_m)
        cy = math.floor(n / cell_m)
        grid = self._grid
        total = we * self.sink_share * self.sink_gain
        ring = self.ring
        # Most thermals share a floor, the level's, and without the depth cycle a zi.
        last_z, last_zi, last_we = z, zi * self.depth_share, we
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
                    zt = z
                    if ground_m is not None and th.floor_m is not None:
                        zt = height_in_thermal(th, z, ground_m)
                    zit = zi * th.depth
                    if zt >= zit:
                        continue  # above its own layer: nothing of it, nor of its sink
                    if zt != last_z or zit != last_zi:
                        last_z, last_zi = zt, zit
                        last_we = updraft.environment_sink(zt, zit, wstar, self._flux_density)
                    w = updraft.updraft_velocity(r / th.stretch, zt, zit, wstar, th.wgain * th.gain,
                                                 th.rgain * rf, last_we, ring=ring,
                                                 ring_width=EDGE_RING_WIDTH)
                    total += s * (w - last_we)
        return total
