"""Which thermals carry a cumulus, and what each cloud's emitter should do.

The sky must be a consequence of the model (SPEC "Visual cues"): a cumulus marks a
thermal, forms and fades with it, and is the same for anyone with the same seed,
date and place. The clouds are not chosen around the glider; a thermal either
carries a cloud or it does not, from its own fixed numbers. The glider's place only
decides which of them are drawn.

Which thermals. About 4.5 are alive per km2, and a cumulus sky has one cloud every
few km, so about 3% get one: the largest mass flux (`wgain * rgain^2`), which is what
would carry moist air highest, and with a life long enough for the cloud to form and
fade while the thermal lives. With the defaults that is 0.12 clouds per km2, one
every ~2.8 km, measured offline (notes/phase2.md).

A cloud cannot be changed once drawn, only fed. Each is an emitter of long-lived
particles that do not move (see `tools/make_cloud_objs.py`). All that can be
controlled is the rate new ones appear, per instance, and destroying the instance,
which removes its particles at once (flown 2026-11-04). So:
- A cloud forms by emitting at the steady rate from `form_tau` of its thermal's life:
  it builds up over one particle life.
- It thins as its thermal decays: from `thin_tau`, where the field's decay starts, it is fed
  at `thin_level` of the steady rate, so it holds fewer particles about a particle life later.
- It outlives its thermal: it is fed until the thermal dies (`fade_tau` = 1), and its particles,
  oldest first, go over one more life (144-216 s): a thin cloud fading over air that no longer
  rises, half gone after about a minute and a half and all of it after three and a half, as a
  real one lingers after its lift has gone. The instance goes once nothing is left to see. So a full cloud is a mature thermal, a thinning one a weakening
  thermal, and a thin one may be dead (notes/SPEC.md, stage 2, block 3).
- A cloud that comes into range, or the first sky of a flight, should already look as
  old as it is, so it emits fast for a moment (`prewarm`), and then rests.
- Far clouds use fewer particles. At 15 km a third of them looks the same (flown), and
  the rest arrive as the glider approaches, also with a short fast emission.
- Going out of range is a fade too, so no cloud vanishes in sight of the glider.

How high (`ground_points`, `cloud_base_m`). Real bases are level, and a particle stays where it
was emitted, so a cloud keeps one height for life: the higher of a level for the area and the
highest ground under it and along its drift, plus a margin (notes/SPEC.md "Generation").

Under X-Plane's clouds (`shade.py`, SPEC stage 2, block 3): where its layers leave a share of the
clear sky's w*, that share of the clouds keep their cumulus, the same ones for everyone (`shade_keeps`),
and they are drawn that much smaller (`shaded_scale`). In rain the share is 0: no cumulus. A clear
sky changes nothing.

Pure Python: no `xp`. `CloudPlanner.step` returns what to do, the adapter does it.
"""

import math

from .field import CARRIER_MIN_FLUX, CARRIER_MIN_LIFE_S, DECAY_FRACTION, FieldConfig, generate_tile
from .geo import radii_of_curvature
from .rng import hash_key

TOP_ZZI = 1.0 / 1.1  # the lift ends at this z/zi (Allen Eq. 11), the same as the markers' top
CREATE, RATE, DESTROY = 0, 1, 2  # actions of CloudPlanner.step
# Cloud size against wgain x rgain: this value gets the object's size. It keeps the median size
# that a size from rgain alone had (1.07), so the sky is as cloudy (notes/phase3.md).
SCALE_WR = 1.7
SCALE_RANGE = (0.6, 1.4)
# The height of a cloud (notes/phase3.md). First guesses.
BASE_MARGIN_M = 300.0
GROUND_STEP_M = 1000.0  # the ground is read this far apart along a cloud's drift
CLOUD_HALF_WIDTH_M = 500.0  # at scale 1, as `tools/make_cloud_objs.py` draws it
SHADE_MIN_SCALE = 0.3  # the smallest a shaded cloud is drawn, against the object's size


class CloudParams:
    __slots__ = ("min_flux", "min_life_s", "form_tau", "thin_tau", "thin_level", "fade_tau",
                 "range_m", "keep_range_m",
                 "near_m", "near_keep_m", "far_rate", "ttl_s", "mean_ttl_s", "prewarm",
                 "rest_fraction", "refill_factor", "min_fast_s", "tiles_per_update", "max_new")

    def __init__(self, min_flux=CARRIER_MIN_FLUX, min_life_s=CARRIER_MIN_LIFE_S, form_tau=0.1,
                 thin_tau=1.0 - DECAY_FRACTION, thin_level=0.5, fade_tau=1.0,
                 range_m=20000.0, keep_range_m=21000.0, near_m=8000.0, near_keep_m=9000.0,
                 far_rate=0.3, ttl_s=216.0, mean_ttl_s=180.0, prewarm=20.0, rest_fraction=0.4,
                 refill_factor=5.0, min_fast_s=2.0, tiles_per_update=2, max_new=8):
        self.min_flux = min_flux
        self.min_life_s = min_life_s
        self.form_tau = form_tau  # life fraction where the cloud starts to form
        self.thin_tau = thin_tau  # where it thins: the field's decay starts here
        self.thin_level = thin_level  # its share of the steady rate from then on (first guess)
        self.fade_tau = fade_tau  # and where it stops being fed: at its thermal's death
        self.range_m = range_m  # clouds are drawn this far from the glider
        self.keep_range_m = keep_range_m  # a drawn cloud is fed until this far
        self.near_m = near_m  # all of a cloud's particles within this distance
        self.near_keep_m = near_keep_m
        self.far_rate = far_rate  # fraction of the particles beyond it
        self.ttl_s = ttl_s  # longest particle life (make_cloud_objs.py)
        self.mean_ttl_s = mean_ttl_s  # and the mean: rate x this is the number alive
        self.prewarm = prewarm  # the fastest rate (the top of the object's table)
        self.rest_fraction = rest_fraction  # rest after a fast fill, of a particle's mean life
        self.refill_factor = refill_factor  # extra rate when a cloud has to catch up
        self.min_fast_s = min_fast_s  # shorter than this it is not worth a fast emission
        self.tiles_per_update = tiles_per_update  # ~200 us each, flown
        self.max_new = max_new  # new clouds per step: each costs two SDK calls in that frame


def carries_cloud(thermal, params):
    """Does this thermal carry a cumulus? Its own numbers only: the same for everyone."""
    return (thermal.wgain * thermal.rgain * thermal.rgain >= params.min_flux
            and thermal.death - thermal.birth >= params.min_life_s)


def cloud_scale(thermal):
    """Size of the cloud relative to the object's: stronger thermals have bigger clouds, mostly.

    In Allen's model a wider thermal has slower air, so a size from rgain alone made the
    biggest clouds the weakest thermals, and a size from wgain alone would rank them exactly.
    The product reads as a pilot should expect: a big cloud is usually a good one, not always.
    """
    size = thermal.wgain * thermal.gain * thermal.rgain / SCALE_WR
    return min(max(size, SCALE_RANGE[0]), SCALE_RANGE[1])


def shade_draw(thermal):
    """A fixed number in [0, 1) for this thermal, from its place and birth: the same for everyone."""
    key = hash_key(round(thermal.lat * 1e7), round(thermal.lon * 1e7), round(thermal.birth))
    return (key >> 11) * (1.0 / (1 << 53))


def shade_keeps(thermal, share):
    """Does this cloud form under X-Plane's clouds, where they leave `share` of the clear sky's w*?

    Fewer cumulus by as much as the thermals weaken (Juan Luis, 2026-11-12, after flying under a
    closed deck): as the share falls, the clouds whose own draw is above it go,
    the same ones always, so no cloud comes and goes as the share wavers. None in rain.
    """
    return share >= 1.0 or shade_draw(thermal) < share


def shaded_scale(thermal, share):
    """The cloud's size under X-Plane's clouds: smaller by as much as the thermals weaken."""
    if share >= 1.0:
        return cloud_scale(thermal)
    return cloud_scale(thermal) * max(share, SHADE_MIN_SCALE)


def feeding_window(thermal, params):
    """Times between which the cloud is fed: (start, stop)."""
    life = thermal.death - thermal.birth
    return thermal.birth + params.form_tau * life, thermal.birth + params.fade_tau * life


def thinning_from(thermal, params):
    """When the cloud starts to thin, as its thermal starts to decay."""
    return thermal.birth + params.thin_tau * (thermal.death - thermal.birth)


def cloud_seconds_left(thermal, t, params):
    """How long something of this cloud will be in the sky: it is fed until `stop`, then lasts
    one particle life, past its thermal's death."""
    _, stop = feeding_window(thermal, params)
    return max(stop + params.ttl_s - t, 0.0)


def ground_points(lat, lon, half_width_m, wind_e_ms, wind_n_ms, seconds, step_m=GROUND_STEP_M):
    """Where to read the ground for a cloud at (lat, lon) now: a list of (lat, lon).

    A cross of the cloud's width under it, then three lanes along its drift, in this wind for
    `seconds`. If the wind changes later, the cloud's height was worked out for another path.
    """
    m, n = radii_of_curvature(lat)
    to_lat = math.degrees(1.0 / m)
    to_lon = math.degrees(1.0 / (n * max(math.cos(math.radians(lat)), 1e-6)))
    points = [(lat, lon), (lat + half_width_m * to_lat, lon), (lat - half_width_m * to_lat, lon),
              (lat, lon + half_width_m * to_lon), (lat, lon - half_width_m * to_lon)]
    wind = math.hypot(wind_e_ms, wind_n_ms)
    steps = math.ceil(wind * seconds / step_m)
    if steps:
        # Across the track: the wind turned a quarter, as long as the cloud's half width.
        side_e, side_n = wind_n_ms / wind * half_width_m, -wind_e_ms / wind * half_width_m
        for k in range(1, steps + 1):
            s = seconds * k / steps
            e, c = wind_e_ms * s, wind_n_ms * s
            for side in (0.0, 1.0, -1.0):
                points.append((lat + (c + side * side_n) * to_lat, lon + (e + side * side_e) * to_lon))
    return points


def cloud_base_m(level_m, grounds_m, margin_m=BASE_MARGIN_M):
    """A cloud's base (m MSL): the level, or the margin over the highest ground if that is higher.

    grounds_m: heights MSL, None where the ground could not be read.
    """
    known = [g for g in grounds_m if g is not None]
    return max(level_m, max(known) + margin_m) if known else level_m


class CloudCatalog:
    """The thermals that carry a cloud, far around the glider.

    Same tiles and streams as `ThermalField`, so the same thermals, but it keeps only
    these few and reaches farther. Loading a tile costs ~200 us in the simulator, so at
    most `tiles_per_update` per update, the nearest first: a sky fills from the glider out.
    Working out which tiles are needed (rarely) takes a whole update of its own.
    """

    def __init__(self, config, frame, params=None, accept=None):
        self.params = params or CloudParams()
        self.config = FieldConfig(seed=config.seed, day=config.day, tile_deg=config.tile_deg,
                                  zi_m=config.zi_m, density_per_km2=config.density_per_km2,
                                  lifetime_min_s=config.lifetime_min_s,
                                  lifetime_max_s=config.lifetime_max_s,
                                  wgain_sigma=config.wgain_sigma, rgain_sigma=config.rgain_sigma,
                                  range_m=self.params.keep_range_m, cell_m=config.cell_m,
                                  sky=config.sky, sun_min_deg=config.sun_min_deg,
                                  depth_cycle=config.depth_cycle,
                                  areas=config.areas is not None)
        self.frame = frame
        self.accept = accept
        # With the sun on, a thermal born before zi has grown to the cloud base has no cloud:
        # the morning is blue (daycycle.py). Its lift is the field's, unchanged. The same cycle
        # gives each thermal its depth, with the depth cycle, as the field's does.
        self.cycle = self.config.cycle()
        self._tiles = {}  # (i, j, slot) -> list of Thermal with a cloud
        self._where = None  # the (i, j, slot) the missing tiles were worked out for
        self._missing = []  # keys to load, the farthest first

    @property
    def started(self):
        return self._where is not None

    @property
    def missing(self):
        return len(self._missing)

    def _plan(self, t, lat, lon):
        """Work out the tiles needed, when the glider changes tile or the time its slot.

        Returns True if it did, which is enough work for one update.
        """
        c = self.config
        tile = c.tile_deg
        i0, j0, s = math.floor(lat / tile), math.floor(lon / tile), math.floor(t / c.slot_s)
        where = (i0, j0, s)
        if where == self._where:
            return False
        self._where = where
        m, n = radii_of_curvature(lat)
        tile_h = math.radians(tile) * m
        tile_w = math.radians(tile) * n * max(math.cos(math.radians(lat)), 1e-6)
        di, dj = math.ceil(c.range_m / tile_h), math.ceil(c.range_m / tile_w)
        wanted = {(i, j, slot) for i in range(i0 - di, i0 + di + 1)
                  for j in range(j0 - dj, j0 + dj + 1) for slot in (s - 1, s)}
        for key in [k for k in self._tiles if k not in wanted]:
            del self._tiles[key]
        self._missing = sorted((k for k in wanted if k not in self._tiles),
                               key=lambda k: -((k[0] - i0) ** 2 * tile_h ** 2
                                               + (k[1] - j0) ** 2 * tile_w ** 2))
        return True

    def update(self, t, lat, lon):
        """Load up to `tiles_per_update` tiles. Returns True while some are missing."""
        if self._plan(t, lat, lon):
            return bool(self._missing)
        for _ in range(min(self.params.tiles_per_update, len(self._missing))):
            key = self._missing.pop()
            kept = [th for th in generate_tile(self.config, *key, accept=self.accept, cycle=self.cycle)
                    if carries_cloud(th, self.params) and not self._blue(th)]
            for th in kept:
                th.e, th.n = self.frame.to_enu(th.lat, th.lon)
            self._tiles[key] = kept
        return bool(self._missing)

    def _blue(self, thermal):
        """Born too early in the day for a cloud?"""
        return self.cycle is not None and self.cycle.blue(thermal.lat, thermal.lon, thermal.birth)

    def loaded_within_m(self, lat, lon):
        """How far from (lat, lon) every tile has loaded (m): no new thermal can turn up nearer."""
        if not self._missing:
            return math.inf
        tile = self.config.tile_deg
        m, n = radii_of_curvature(lat)
        to_n, to_e = math.radians(1.0) * m, math.radians(1.0) * n * max(math.cos(math.radians(lat)), 1e-6)
        nearest = math.inf
        for i, j, _ in self._missing:
            dlat = max(i * tile - lat, 0.0, lat - (i + 1) * tile)
            dlon = max(j * tile - lon, 0.0, lon - (j + 1) * tile)
            nearest = min(nearest, math.hypot(dlat * to_n, dlon * to_e))
        return nearest

    def set_frame(self, frame):
        self.frame = frame
        for thermals in self._tiles.values():
            for th in thermals:
                th.e, th.n = frame.to_enu(th.lat, th.lon)

    def thermals(self):
        for thermals in self._tiles.values():
            yield from thermals


class _Shown:
    __slots__ = ("thermal", "rate", "level", "near", "fast_rate", "fast_until", "rest_until",
                 "stopped_at", "level_at_stop")

    def __init__(self, thermal):
        self.thermal = thermal
        self.rate = 0.0  # what the emitter was last told
        self.level = 0.0  # the steady rate it is at, or going to
        self.near = False  # fed with all its particles (within near_m), not far_rate
        self.fast_rate = 0.0
        self.fast_until = 0.0  # emitting at fast_rate until this time
        self.rest_until = 0.0  # and then nothing until this time
        self.stopped_at = None  # when it was told to stop feeding
        self.level_at_stop = 0.0


class CloudPlanner:
    """Which clouds to draw, and how fast each one should emit. Holds no simulator state."""

    def __init__(self, params=None):
        self.params = params or CloudParams()
        self.shown = {}  # Thermal -> _Shown
        self.more_waiting = False  # the last step left new clouds for the next one
        self.next_change = math.inf  # the next time a rate must change, between steps

    def _steady(self, item, r, t):
        """The steady rate for a cloud r m away at t: fewer particles far away, and as its
        thermal decays."""
        p = self.params
        item.near = r <= (p.near_keep_m if item.near else p.near_m)
        rate = 1.0 if item.near else p.far_rate
        return rate * p.thin_level if t >= thinning_from(item.thermal, p) else rate

    def _plan_new(self, thermal, r, t):
        """A new cloud, emitting for what it should have formed by now.

        All the particles of a fast fill are the same age, so none dies before the shortest
        life. It is followed by a rest, and the steady rate then replaces them as they go,
        within about +40% and -20% of the steady number. Without the rest a cloud reaches
        twice that number (found in review).
        """
        item = _Shown(thermal)
        item.level = self._steady(item, r, t)
        self._fill(item, t)
        return item

    def _fill(self, item, t):
        p = self.params
        start, _ = feeding_window(item.thermal, p)
        filled = min((t - start) / p.mean_ttl_s, 1.0)  # how much of it has formed by now
        fill_s = filled * p.mean_ttl_s / p.prewarm
        if fill_s >= p.min_fast_s:
            item.fast_rate = item.level * p.prewarm
            item.fast_until = t + fill_s
            item.rest_until = item.fast_until + p.rest_fraction * filled * p.mean_ttl_s
        item.rate = self._rate_now(item, t)

    def refill(self, thermal, t):
        """The rate for a new instance taking over a drawn cloud that should look whole at once:
        it fills fast and rests, as a new cloud would, while the old instance's particles go.

        For a while the cloud has both, up to twice its particles. Not for a cloud that is
        fading, which keeps its rate. The caller should plan again soon after `next_change`.
        """
        item = self.shown[thermal]
        if item.stopped_at is None and item.level > 0.0:
            self._fill(item, t)
            self._note_change(item, t)
        return item.rate

    @staticmethod
    def _rate_now(item, t):
        if t < item.fast_until:
            return item.fast_rate
        if t < item.rest_until:
            return 0.0
        return item.level

    def step(self, thermals, e, n, t, loaded_m=math.inf):
        """Actions for now: a list of (action, thermal, rate). thermals: the catalog's.

        action is CREATE (a new cloud emitting at rate), RATE (a new rate for a drawn
        cloud) or DESTROY. Same inputs and same state, same answer. Call this soon after
        `next_change`, or a fast emission runs on for as long as it is late. The creations
        come last, nearest first, and should be done in that order; a new cloud farther than
        loaded_m (`CloudCatalog.loaded_within_m`) waits, since a nearer one may still turn up.
        """
        p = self.params
        actions = []
        seen = set()
        new = []  # (distance, thermal) of clouds that could be created
        self.more_waiting = False
        self.next_change = math.inf
        for th in thermals:
            # Most of the catalog is not alive now: not worth any work. A shown cloud outlives
            # its thermal by a particle life, and fades meanwhile.
            if t < th.birth or (t >= th.death and th not in self.shown):
                continue
            start, stop = feeding_window(th, p)
            r = math.hypot(th.e - e, th.n - n)
            item = self.shown.get(th)
            seen.add(th)
            if item is None:
                if start <= t < stop and r <= p.range_m:
                    if r > loaded_m:
                        self.more_waiting = True
                    else:
                        new.append((r, th))
                continue
            self._step_shown(item, r, t, start, stop, actions)
            self._note_change(item, t)
        # No longer in the catalog: its tile was dropped, far from the glider, so its numbers
        # for the distance go stale. The particles are still in the sky, so it fades as usual.
        for th in [th for th in self.shown if th not in seen]:
            self._fade(self.shown[th], t, actions)
        actions.sort(key=lambda a: (a[0], a[1].lat, a[1].lon))
        # New clouds last, the nearest first: X-Plane draws the newest instance underneath, so
        # created in this order the far ones are drawn under the near ones (cloud_order.py).
        new.sort(key=lambda rt: (rt[0], rt[1].lat, rt[1].lon))
        self.more_waiting = self.more_waiting or len(new) > p.max_new
        for r, th in new[:p.max_new]:
            item = self.shown[th] = self._plan_new(th, r, t)
            actions.append((CREATE, th, item.rate))
            self._note_change(item, t)
        return actions

    def _note_change(self, item, t):
        for when in (item.fast_until, item.rest_until):
            if t < when < self.next_change:
                self.next_change = when

    def _fade(self, item, t, actions):
        """Stop feeding the cloud; later, with nothing left to see, it goes."""
        if item.stopped_at is None:
            item.stopped_at = t
            item.level_at_stop = item.level
            item.level = item.rate = item.fast_until = item.rest_until = 0.0
            item.near = False
            actions.append((RATE, item.thermal, 0.0))
        elif t - item.stopped_at >= self.params.ttl_s:
            del self.shown[item.thermal]
            actions.append((DESTROY, item.thermal, 0.0))

    def _step_shown(self, item, r, t, start, stop, actions):
        p = self.params
        th = item.thermal
        feeding = start <= t < stop
        if item.stopped_at is not None:
            # Fed again only well inside the keep range, so a glider circling on the limit
            # does not stop and restart it.
            if not feeding or r > p.range_m:
                self._fade(item, t, actions)
                return
            left = max(1.0 - (t - item.stopped_at) / p.mean_ttl_s, 0.0)
            have = item.level_at_stop * left
            item.stopped_at = None
            item.level = 0.0
            self._raise_level(item, self._steady(item, r, t), have, t)
            item.rate = self._rate_now(item, t)
            actions.append((RATE, th, item.rate))
            return
        if not feeding or r > p.keep_range_m:
            self._fade(item, t, actions)
            return
        steady = self._steady(item, r, t)
        if steady > item.level:
            self._raise_level(item, steady, item.level, t)
        else:
            item.level = steady
        rate = self._rate_now(item, t)
        if rate != item.rate:
            item.rate = rate
            actions.append((RATE, th, rate))

    def _raise_level(self, item, steady, have, t):
        """Coming nearer, or fed again: what is missing arrives fast, if it is worth it."""
        p = self.params
        missing = steady - have
        item.level = steady
        fast_s = missing * p.mean_ttl_s / p.refill_factor
        if fast_s >= p.min_fast_s:
            item.fast_rate = steady + p.refill_factor
            item.fast_until = t + fast_s
        item.rest_until = 0.0

    def clear(self):
        """Forget every cloud (the adapter destroys the instances)."""
        self.shown.clear()
        self.next_change = math.inf
