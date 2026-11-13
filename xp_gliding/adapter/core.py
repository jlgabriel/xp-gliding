"""Adapter core: from the aircraft's state to the forces X-Plane must apply.

This is the adapter's logic without the SDK, so it can be tested outside the
simulator; `xpio.py` reads the datarefs into an `AircraftState` and writes an
`Injection` back. Nothing here imports `xp`.

Per frame (`Injector.step`): place the sample points (centre, wing tips, tail)
at their real 3D positions, ask the engine for the vertical air velocity at
each (the tail only once a slow update: nothing but the flight logger reads
it), and turn it into
- the energy force F = m g w / V_TAS along the air-relative velocity, with w
  the span average of the wing samples, split into X-Plane's body axes;
- the gust roll moment from the spanwise gradient of w, plus the gradient
  that cancels the energy force's climbing-turn artifact (`helix_gradient`:
  the glider climbs relative to the air instead of the air rising, which
  would make it overbank in a thermal).

About once a second (`Injector.slow_update`): load and drop thermal tiles
around the aircraft, move the local origin when the aircraft is far from it,
and find the nearest thermal for the instruments.

The wind is X-Plane's. `Injector.carry` integrates it every frame into the offset between
the ground and the air (`engine/wind.py`), and the field is only ever asked about the
aircraft's position in the air's frame. If the thermals lean (off by default), that position
is also shifted by the lean at the aircraft's height, from X-Plane's layers of wind
(`Injector.lean_update`, in the slow path).

Which wind carries the sky. By default the wind at the aircraft, so in shear it stays with its
thermal at any height. With `wind_at_clouds` (off by default) it is the wind at
the clouds' base, from the same layers (`Injector.sky_wind_update`): the emitters move with it,
and the aircraft moves through the sky at the difference. Particles appear to go on moving at
about the wind at the aircraft, so in shear they fall behind their emitters (flown, read from
screenshots).

The lift ends with its cloud. A cloud has one height MSL, whatever the ground under the glider is
doing, so each thermal is read at a height from a floor of its own (`engine.field.height_in_thermal`).
The floor comes from its cloud's base (`clouds.CloudHeights`), set in the slow path when the thermal
loads. With no `heights`, thermals have no floor and the glider's AGL rules.

The day's depth. `zi` is the pilot's setting, or, with `weather_base_enabled`, the cloud base
X-Plane's weather gives (`engine.day.weather_base_m`) over the sky's `cloud_base_zzi`, so the clouds
are where the weather would put them (`Injector.zi_m`). The field is made for that zi, which sets how
many thermals it holds (`engine.field.thermal_density_per_km2`), and made again when it changes. The weather is read when a sky begins and
once more about 90 s later, for real weather that arrives late, then kept (`WeatherBase`).

The daily cycle (`engine/daycycle.py`, unless `sun_enabled` is off): no thermal is born with the sun
low, and the w* in use is the menu's times the share of the day's peak at this hour (`Injector.wstar_ms`)
for the lift, the markers and the lean. X-Plane's cloud layers at the aircraft take a share of it,
and rain all of it, over a few minutes (`engine/shade.py`, always on: a clear sky changes nothing).
Good and bad areas (`engine/areas.py`, setting `areas_enabled`, on by default) vary the number and
strength of the thermals over tens of kilometres, from the seed and the date.
Each thermal is also as deep as the day was at its birth
(`FieldConfig.depth_cycle`): zi above is the afternoon's, and `Injector.zi_now_m` the moment's. None is born over
water (`Injector.accept_thermal`). A thermal keeps its place in the air,
so what counts is the ground under it at its birth, worked out in the present wind: the field and
the clouds load the same thermal at different times, and in a steady wind must agree about it.
Born over land, it can drift out over the sea.

X-Plane's conventions (DataRefs.txt, XP 12.4.3): `faxil_plug_acf` positive
pushes the aircraft *backward*, `fside_plug_acf` positive pushes it right,
`fnrml_plug_acf` positive pushes it up, `L_plug_acf` positive rolls right.
`sim/flightmodel/position/beta` is positive with the nose right of the flight
path (measured by the test pilot, 2026-11-03), the opposite of the engine's convention.

Debug modes, for measurements: `uniform_ms` replaces the field with the same
w everywhere (checks the climb gain at any speed and bank); `debug_dwdy` replaces
the spanwise gradient for the roll moment (checks the roll sign).
"""

import math
import time

from ..engine import injection as inj
from ..engine.day import weather_base_m
from ..engine.areas import factors as area_factors
from ..engine.shade import Shade, sky_cover, strength_share
from ..engine.edge import EdgeTurbulence, bumps
from ..engine.field import (EDGE_RING, EDGE_SINK_GAIN, SKY_NAMES, FieldConfig, ThermalField, sky_index,
                            sky_named)
from ..engine.geo import LocalFrame
from ..engine.sun import SUN_MIN_DEG, sun_elevation_deg
from ..engine.wind import AirDrift, Lean, layer_wind
from .clouds import JUMP_S

NEAREST_MAX_M = 5000.0
JUMP_M = 5000.0  # moved farther than this between slow updates: a new flight, or the map
KT_TO_MS = 0.514444
WEATHER_REREAD_S = 90.0  # real weather arrives late: read once more this long after the first base
WEATHER_RETRY_S = 10.0  # no data yet: ask again this soon (seen with real weather, 2026-11-09)
WEATHER_READS = 2  # readings with data, then the base is kept
WEATHER_KEEP_M = 100.0  # a later base closer than this to the one in use is not worth a new sky
# No lift of this model comes near this (30 m/s at the strongest core offline, w* 8 in the narrow
# sky): more, or a value that is not a number, is a fault, and no force is better than a wrong one.
MAX_LIFT_MS = 50.0
MAX_KICK_GAP_S = 0.25  # frames further apart than this (a pause, a hitch) start the kick over


def wind_layers(altitudes_msl_m, speeds_kt, from_deg, ground_m):
    """X-Plane's layers of wind as (heights above ground, east, north), ascending, in m and m/s.

    Its direction is where the wind comes from, and the engine wants where it goes. A layer not
    in use has a speed of -1 and an altitude that means nothing, among the ones in use (seen in
    X-Plane 12.4.3 on 2026-11-05).
    """
    heights, east, north = [], [], []
    for alt, speed, direction in sorted(zip(altitudes_msl_m, speeds_kt, from_deg)):
        if speed < 0.0 or (heights and alt - ground_m <= heights[-1]):
            continue  # the engine interpolates in height: the same height twice has no slope
        a = math.radians(direction)
        heights.append(alt - ground_m)
        east.append(-speed * KT_TO_MS * math.sin(a))
        north.append(-speed * KT_TO_MS * math.cos(a))
    return heights, east, north


class AircraftState:
    """What the adapter reads from X-Plane each frame."""

    __slots__ = ("lat", "lon", "agl_m", "msl_m", "psi_deg", "phi_deg", "alpha_deg", "beta_deg",
                 "r_rad", "tas_ms", "mass_kg", "rho", "t_zulu_s", "t_local_s", "sky_t_s", "day",
                 "wind_x_ms", "wind_z_ms")

    def __init__(self):
        self.lat = self.lon = 0.0
        self.agl_m = self.msl_m = 0.0
        self.psi_deg = self.phi_deg = self.alpha_deg = self.beta_deg = 0.0
        self.r_rad = 0.0  # body yaw rate, positive yawing right
        self.tas_ms = 0.0
        self.mass_kg = 0.0
        self.rho = 1.225
        self.t_zulu_s = self.t_local_s = 0.0
        self.sky_t_s = 0.0  # the engine's t: `field.sky_time`
        self.day = 0
        self.wind_x_ms = self.wind_z_ms = 0.0  # X-Plane's wind at the aircraft, local axes


class Injection:
    """What the adapter applies, and the lift behind it (also published as datarefs)."""

    __slots__ = ("faxil_n", "fside_n", "fnrml_n", "roll_nm", "force_n", "kick_n",
                 "w_centre", "w_left", "w_right", "w_tail", "w_span", "dw_dy", "dw_dy_helix")

    def __init__(self):
        self.clear()

    def clear(self):
        self.faxil_n = self.fside_n = self.fnrml_n = self.roll_nm = self.force_n = self.kick_n = 0.0
        self.w_centre = self.w_left = self.w_right = self.w_tail = self.w_span = 0.0
        self.dw_dy = self.dw_dy_helix = 0.0


class Nearest:
    """Nearest alive thermal, refreshed by slow_update."""

    __slots__ = ("distance_m", "bearing_deg", "core_ms", "floor_m", "depth", "alive", "loaded")

    def __init__(self):
        self.distance_m = -1.0  # -1: none within NEAREST_MAX_M
        self.bearing_deg = 0.0
        self.core_ms = 0.0  # lift at its centre, at the aircraft's height
        self.floor_m = -1.0  # where its height starts, m MSL; -1: no thermal, or no floor
        self.depth = 0.0  # its zi over the afternoon's (daily cycle); 0: no thermal
        self.alive = 0  # thermals alive among those loaded
        self.loaded = 0


class NativeThermalGuard:
    """Keeps XP12's native thermal setting at 0 while our thermals are active.

    Our thermals replace the native ones, and the native setting only adds a
    uniform sink, so it must be 0 under our thermals. Real weather and a new flight can rewrite
    it, so it is re-checked every `period_s`, not every frame; a nonzero value
    found then is taken as the new one to restore. When our thermals stop, the
    saved value is written back.
    """

    def __init__(self, read, write, period_s=5.0):
        self.read = read
        self.write = write
        self.period_s = period_s
        self.engaged = False
        self.saved = 0.0
        self._next = 0.0

    def want(self, active, now):
        if active and not self.engaged:
            self.saved = self.read()
            self.write(0.0)
            self.engaged = True
            self._next = now + self.period_s
        elif not active and self.engaged:
            self.release()
        elif active and now >= self._next:
            self._next = now + self.period_s
            value = self.read()
            if value != 0.0:
                self.saved = value
                self.write(0.0)

    def release(self):
        if self.engaged:
            self.write(self.saved)
            self.engaged = False


class WeatherBase:
    """The cloud base from X-Plane's weather, read when a sky begins and once more later.

    `reset` starts over: a new flight, or the setting turned on. Then `due` asks for a reading
    now. A reading without data enough is asked again `WEATHER_RETRY_S` later; one with data,
    `WEATHER_REREAD_S` later, and after a second one with data the base is kept. A base is in m
    above the ground under the aircraft at the first reading with data. The second is worked out
    over that same ground, so that it changes with the weather and not with the terrain flown
    over since (seen 2026-11-09 at Santiago: 550 m of rising ground gave 380 m less base).
    """

    __slots__ = ("base_m", "ground_m", "reads", "with_data", "next_s")

    def __init__(self):
        self.reset(0.0)

    def reset(self, now):
        self.base_m = self.ground_m = None
        self.reads = self.with_data = 0
        self.next_s = now

    def due(self, now):
        return now >= self.next_s and self.with_data < WEATHER_READS

    def take(self, base_m, now):
        """A reading (None: no data enough). True if the base in use changed."""
        self.reads += 1
        if base_m is None:
            self.next_s = now + WEATHER_RETRY_S
            return False
        self.with_data += 1
        self.next_s = now + WEATHER_REREAD_S
        if self.base_m is not None and abs(base_m - self.base_m) < WEATHER_KEEP_M:
            return False
        self.base_m = base_m
        return True

    def read(self, ground_m, heights_m, temperatures_c, dew_points_c, now):
        """A reading of X-Plane's layers over the ground under the aircraft (m MSL) now."""
        ground_m = ground_m if self.ground_m is None else self.ground_m
        changed = self.take(weather_base_m(ground_m, heights_m, temperatures_c, dew_points_c), now)
        if self.with_data == 1 and self.ground_m is None:
            self.ground_m = ground_m
        return changed

    @property
    def published_m(self):
        """The base for a dataref: -1 for none yet."""
        return -1.0 if self.base_m is None else self.base_m


class Injector:
    def __init__(self, settings, geometry):
        self.settings = settings
        self.uniform_ms = 0.0
        self.debug_dwdy = 0.0
        self.samples = None
        self.clp = self.cla = 0.0
        self.geometry = None
        self.kick = inj.HighPass()  # what changes in the lift, for the kick (sharper edges)
        self._kick_t = None  # time.monotonic of the kick's last frame
        self.turbulence = EdgeTurbulence()  # how strong the edge's bumps are where the glider is
        self.turb_ms = 0.0  # their amplitude, last frame: published
        self.set_geometry(geometry)
        self.frame = None
        self.field = None
        self._field_key = None
        self.drift = AirDrift()
        self.lean = Lean()
        self.lean_e_m = self.lean_n_m = 0.0  # the lean at the aircraft, last frame: published
        self.sky_wind = None  # (east, north) at the clouds' base, if that carries the sky
        self.nearest = Nearest()
        self.is_wet = None  # is_wet(lat, lon), set by the plugin: the terrain is not ours to read
        self.heights = None  # clouds.CloudHeights, set by the plugin: the lift ends with its cloud
        self._last_place = None  # (t, lat, lon) at the last slow update
        self.floors_us = self.floors_us_max = 0.0  # the last time thermals got their floors
        self.water_checked = self.water_rejected = 0  # thermals asked about, and left out
        self.sun_elevation_deg = 0.0  # the engine's sun at the aircraft, to compare with X-Plane's
        self.sun_share = 1.0  # the share of a full day's thermals alive (`ThermalField.sink_share`)
        self.day_share = 1.0  # w* of the moment over the menu's, the day's peak (daily cycle)
        self.depth_share = 1.0  # zi of the moment over the afternoon's (the daily cycle's depth)
        self.shade = Shade()  # less lift under X-Plane's clouds, none in rain
        self.sky_cover = 0.0  # the share of the sun X-Plane's layers stop, at the aircraft
        self.rain = 0.0  # X-Plane's rain_percent
        # The good or bad area at the aircraft (engine/areas.py), in the air's frame: its quality
        # and the thermals' number and strength there, times. 0, 1, 1 with the areas off.
        self.area_quality = 0.0
        self.area_density = self.area_strength = 1.0
        self.weather = WeatherBase()
        self.jumped = False  # the last slow update found a jump: a new flight, the map, the clock
        # The tail's sample feeds only a dataref the flight logger reads (pitch is not modelled),
        # so it is taken once a slow update, not every frame.
        self._tail_due = True
        self.w_tail = 0.0

    def set_geometry(self, geometry):
        self.geometry = geometry
        self.samples = inj.SampleGeometry(geometry.span_m, geometry.tail_arm_m)
        self.clp = inj.roll_damping(geometry.aspect_ratio, geometry.taper)
        self.cla = inj.lift_slope(geometry.aspect_ratio)

    @property
    def sky_index(self):
        return sky_index(self.settings.sky)

    @sky_index.setter
    def sky_index(self, index):
        if 0 <= index < len(SKY_NAMES):
            self.settings.sky = SKY_NAMES[index]

    @property
    def zi_m(self):
        """The day's depth in use: from the weather's cloud base if that is on and read, if not the setting."""
        st = self.settings
        if st.weather_base_enabled and self.weather.base_m is not None:
            return self.weather.base_m / sky_named(st.sky).cloud_base_zzi
        return st.zi_m

    @property
    def zi_now_m(self):
        """The depth of the moment at the aircraft: `zi_m`, the afternoon's, with the daily cycle."""
        return self.zi_m * self.depth_share

    @property
    def wstar_ms(self):
        """The w* of the moment: the menu's, the day's peak, times the daily cycle's share and
        what X-Plane's clouds and rain leave of it."""
        return self.settings.wstar_ms * self.day_share * self.shade.share

    def reset_field(self):
        """Forget the loaded thermals (they are regenerated identically on demand)."""
        self.field = None
        self._field_key = None

    def accept_thermal(self, lat, lon, birth):
        """The field's filter. Called as tiles load, and only for thermals not thinned out."""
        self.water_checked += 1
        if self.is_wet(*self.drift.to_ground_at(lat, lon, birth)):
            self.water_rejected += 1
            return False
        return True

    # --- the wind ---------------------------------------------------------

    def carry(self, s):
        """Every frame, first: X-Plane's wind moves the sky as it moves the aircraft."""
        if not self.settings.wind_enabled:
            self.drift.hold(s.sky_t_s)
        elif self.settings.wind_at_clouds and self.sky_wind is not None:
            self.drift.advance(self.sky_wind[0], self.sky_wind[1], s.lat, s.sky_t_s)
        else:
            # Local axes: x east, z south (engine/geo.py).
            self.drift.advance(s.wind_x_ms, -s.wind_z_ms, s.lat, s.sky_t_s)

    def sky_wind_update(self, s, altitudes_msl_m, speeds_kt, from_deg, msl_m, level_m=None):
        """Every few seconds, if the wind at the clouds carries the sky: read it from the layers.

        level_m: the clouds' level (m MSL), if they have one yet; if not, where they would have it.
        With no layer in use it stays with the wind at the aircraft.
        """
        heights, east, north = wind_layers(altitudes_msl_m, speeds_kt, from_deg, 0.0)
        if not heights:
            self.sky_wind = None
            return
        if level_m is None:
            level_m = msl_m - s.agl_m + sky_named(self.settings.sky).cloud_base_zzi * self.zi_now_m
        self.sky_wind = layer_wind(level_m, heights, east, north)

    def lean_update(self, s, altitudes_msl_m, speeds_kt, from_deg, msl_m):
        """Every few seconds: X-Plane's layers of wind lean the sky, if that is on."""
        st = self.settings
        if not (st.lean_enabled and st.wind_enabled):
            self.lean.reset()
            return
        heights, east, north = wind_layers(altitudes_msl_m, speeds_kt, from_deg, msl_m - s.agl_m)
        if heights:
            self.lean.set_wind(heights, east, north, sky_named(st.sky).cloud_base_zzi * self.zi_now_m,
                               self.wstar_ms, s.sky_t_s)

    def sky_position(self, s):
        """Where the aircraft is in the field's sky (m in the local frame), whatever it feels."""
        e, n = self.frame.to_enu(*self.drift.to_air(s.lat, s.lon))
        if self.settings.lean_enabled and self.settings.wind_enabled:
            self.lean_e_m, self.lean_n_m = self.lean.at(s.agl_m)
            return e - self.lean_e_m, n - self.lean_n_m
        self.lean_e_m = self.lean_n_m = 0.0
        return e, n

    # --- about once a second ----------------------------------------------

    def _jumped(self, s):
        """Did the clock or the aircraft jump since the last slow update? That is how a new
        flight with the same aircraft, or a move on the map, shows up."""
        last, self._last_place = self._last_place, (s.sky_t_s, s.lat, s.lon)
        return last is not None and (abs(s.sky_t_s - last[0]) > JUMP_S
                                     or LocalFrame(last[1], last[2]).distance_to_origin(s.lat, s.lon) > JUMP_M)

    def moved_to(self, lat, lon, sky_t_s):
        """The plugin moved the aircraft here itself (`engine/airstart.py`): the same sky, not a jump."""
        self._last_place = (sky_t_s, lat, lon)

    def _ground(self, s):
        """The ground under the aircraft for the field, m MSL. None: no floors, the old way."""
        return None if self.heights is None else s.msl_m - s.agl_m

    def slow_update(self, s, sky_layers=None):
        """Keep the field loaded around the aircraft. Not for every frame.

        sky_layers: X-Plane's (cloud types, coverages, rain) at the aircraft (`XPlaneIO.sky_layers`),
        or None for a clear sky.
        """
        st = self.settings
        lat, lon = self.drift.to_air(s.lat, s.lon)
        key = (st.seed, s.day, st.range_m, st.sky, self.zi_m, st.sun_enabled, st.blue_day,
               st.areas_enabled)
        new_sky = self.jumped = self._jumped(s)
        if self.field is None or key != self._field_key:
            new_sky = True
            self.frame = LocalFrame(lat, lon)
            config = FieldConfig(seed=st.seed, day=s.day, range_m=st.range_m, zi_m=self.zi_m,
                                 sky=sky_named(st.sky), sun_min_deg=SUN_MIN_DEG if st.sun_enabled else None,
                                 depth_cycle=st.sun_enabled, areas=st.areas_enabled)
            self.field = ThermalField(config, self.frame, self.accept_thermal if self.is_wet else None)
            self._field_key = key
        elif self.frame.distance_to_origin(lat, lon) > st.recentre_m:
            self.frame = LocalFrame(lat, lon)
            self.field.set_frame(self.frame)
        changed = self.field.update(s.sky_t_s, lat, lon)
        self.field.ring = EDGE_RING if st.edge_enabled else 0.0
        self.field.sink_gain = EDGE_SINK_GAIN if st.edge_enabled else 1.0
        if new_sky:
            self.kick.reset()  # a new sky's lift is not air the glider flew into
            self.turbulence.reset()
        if self.jumped:
            self.shade.reset()  # a new place or time: its weather at once
        kinds, covers, self.rain = sky_layers if sky_layers is not None else ((), (), 0.0)
        self.sky_cover = sky_cover(kinds, covers)
        self.shade.step(strength_share(kinds, covers, self.rain), s.sky_t_s)
        self.sun_elevation_deg = sun_elevation_deg(s.lat, s.lon, s.day, s.sky_t_s)
        self.sun_share = self.field.sink_share
        cycle = self.field.cycle
        self.day_share = 1.0 if cycle is None else cycle.strength_share(lat, lon, s.sky_t_s)
        self.depth_share = self.field.depth_share
        areas = self.field.config.areas
        self.area_quality = 0.0 if areas is None else areas.quality(lat, lon)
        self.area_density, self.area_strength = area_factors(self.area_quality)
        if self.heights is not None:
            self._set_floors(s, new_sky, changed)

        near = self.nearest
        e, n = self.sky_position(s)
        th, r = self.field.nearest(e, n, s.sky_t_s, NEAREST_MAX_M)
        if th is None:
            near.distance_m, near.bearing_deg, near.core_ms, near.floor_m, near.depth = -1.0, 0.0, 0.0, -1.0, 0.0
        else:
            near.distance_m = r
            near.bearing_deg = math.degrees(math.atan2(th.e - e, th.n - n)) % 360.0
            near.core_ms = self.field.lift_at(th.e, th.n, s.agl_m, s.sky_t_s,
                                              self.wstar_ms, self.zi_m, self._ground(s))
            near.floor_m = -1.0 if th.floor_m is None else th.floor_m
            near.depth = th.depth
        near.alive = len(self.field.alive(s.sky_t_s))
        near.loaded = self.field.loaded_count()
        self._tail_due = True

    def _set_floors(self, s, new_sky, changed):
        """Give each thermal its floor when it loads. A new sky has a new level, from the ground
        under the aircraft now, and every thermal gets its floor again."""
        heights = self.heights
        zi = self.zi_m
        base_zzi = self.field.config.sky.cloud_base_zzi
        if new_sky:
            heights.reset()
            heights.span_m = base_zzi * zi
            heights.level_m = s.msl_m - s.agl_m + heights.span_m
            cycle = self.field.cycle
            if self.settings.blue_day:  # no thermal has a cloud: each goes by the level
                heights.blue = lambda th: True
            else:
                heights.blue = (None if cycle is None
                                else lambda th: cycle.blue(th.lat, th.lon, th.birth))
        if new_sky or changed:
            t0 = time.perf_counter()
            for th in self.field.thermals():
                if new_sky or th.floor_m is None:
                    th.floor_m = heights.floor_m(th, s.sky_t_s, self.drift, base_zzi, zi)
            self.floors_us = (time.perf_counter() - t0) * 1e6
            self.floors_us_max = max(self.floors_us_max, self.floors_us)

    # --- every frame ---------------------------------------------------------

    def _kick(self, s, w, wl, wc, wr):
        """The kick's lift (N) and the gradient (1/s) the edge's bumps add across the span.

        The kick is the lift of a change in w as the wing meets it (engine/injection.py), w with
        the edge's bumps added (engine/edge.py). Neither does work: the climb stays the energy
        force's, from the smooth lift.
        """
        now = time.monotonic()
        dt = 0.0 if self._kick_t is None else now - self._kick_t
        self._kick_t = now
        if dt > MAX_KICK_GAP_S:
            self.kick.reset()
            self.turbulence.reset()
        span = self.geometry.span_m
        amp = self.turbulence.step(wc, inj.span_gradient(wl, wr, span), s.tas_ms, dt)
        self.turb_ms = amp
        g, t = self.samples, s.sky_t_s
        if amp > 0.0 and self.uniform_ms == 0.0:
            w += amp * bumps(g.ce, g.cn, t)
            bumps_dwdy = amp * (bumps(g.re, g.rn, t) - bumps(g.le, g.ln, t)) / span
        else:
            bumps_dwdy = 0.0
        area = self.geometry.area_m2
        tau = inj.heave_time_s(s.mass_kg, s.rho, s.tas_ms, area, self.cla)
        return inj.kick_force(s.rho, s.tas_ms, area, self.cla, self.kick.step(w, dt, tau)), bumps_dwdy

    def _no_kick(self):
        self.kick.reset()
        self.turbulence.reset()
        self._kick_t = None
        self.turb_ms = 0.0
        return 0.0, 0.0

    def step(self, s, out):
        """Fill `out` with the forces for this frame. Call slow_update first, once."""
        st = self.settings
        if s.tas_ms < inj.MIN_TAS_MS or self.field is None:
            out.clear()
            return out
        g = self.samples
        if self.uniform_ms != 0.0:
            wl = wc = wr = wt = self.uniform_ms
        elif st.thermals_enabled:
            e, n = self.sky_position(s)
            g.update(e, n, s.agl_m, s.psi_deg, s.phi_deg)
            f, t, wstar, zi = self.field, s.sky_t_s, self.wstar_ms, self.zi_m
            ground = self._ground(s)
            wc = f.lift_at(g.ce, g.cn, g.cz, t, wstar, zi, ground)
            wl = f.lift_at(g.le, g.ln, g.lz, t, wstar, zi, ground)
            wr = f.lift_at(g.re, g.rn, g.rz, t, wstar, zi, ground)
            if self._tail_due:
                self._tail_due = False
                self.w_tail = f.lift_at(g.te, g.tn, g.tz, t, wstar, zi, ground)
            wt = self.w_tail
        else:
            wl = wc = wr = wt = 0.0
        w = inj.span_average(wl, wc, wr)
        force = inj.energy_force(s.mass_kg, w, s.tas_ms)
        # The engine's beta is positive with the velocity right of the nose; X-Plane's
        # is positive with the nose right of the velocity.
        fwd, right, up = inj.path_force_body(force, s.alpha_deg, -s.beta_deg)
        span = self.geometry.span_m
        dw_dy = self.debug_dwdy if self.debug_dwdy != 0.0 else inj.span_gradient(wl, wr, span)
        # The sharper edges: the kick, and the edge's bumps, which also roll the wing.
        kick, bumps_dwdy = self._kick(s, w, wl, wc, wr) if st.edge_enabled else self._no_kick()
        dw_dy += bumps_dwdy
        helix = inj.helix_gradient(w, s.r_rad, s.tas_ms) if st.helix_enabled else 0.0
        dw_dy += helix
        roll = 0.0
        if st.roll_enabled:
            roll = inj.gust_roll_moment(s.rho, s.tas_ms, self.geometry.area_m2, span,
                                        dw_dy, self.clp)
        if not (abs(w) <= MAX_LIFT_MS and math.isfinite(roll) and math.isfinite(kick)):
            out.clear()
            return out
        kick_fwd, kick_up = inj.lift_force_body(kick, s.alpha_deg)
        out.faxil_n = -(fwd + kick_fwd)
        out.fside_n = right
        out.fnrml_n = up + kick_up
        out.roll_nm = roll
        out.force_n = force
        out.kick_n = kick
        out.w_centre, out.w_left, out.w_right, out.w_tail = wc, wl, wr, wt
        out.w_span = w
        out.dw_dy = dw_dy
        out.dw_dy_helix = helix
        return out
