"""Adapter core: from the aircraft's state to the forces X-Plane must apply.

This is the adapter's logic without the SDK, so it can be tested outside the
simulator; `xpio.py` reads the datarefs into an `AircraftState` and writes an
`Injection` back. Nothing here imports `xp`.

Per frame (`Injector.step`): place the sample points (centre, wing tips, tail)
at their real 3D positions, ask the engine for the vertical air velocity at
each, and turn it into
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

X-Plane's conventions (DataRefs.txt, XP 12.4.3): `faxil_plug_acf` positive
pushes the aircraft *backward*, `fside_plug_acf` positive pushes it right,
`fnrml_plug_acf` positive pushes it up, `L_plug_acf` positive rolls right.
`sim/flightmodel/position/beta` is positive with the nose right of the flight
path (measured, notes/baseline.md), the opposite of the engine's convention.

Debug modes, for measurements: `uniform_ms` replaces the field with the same
w everywhere (repeats baseline test B with our physics); `debug_dwdy` replaces
the spanwise gradient for the roll moment (checks the roll sign).
"""

import math

from ..engine import injection as inj
from ..engine.field import FieldConfig, ThermalField, sky_index, sky_named
from ..engine.geo import LocalFrame
from ..engine.wind import AirDrift, Lean

NEAREST_MAX_M = 5000.0
KT_TO_MS = 0.514444


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

    __slots__ = ("lat", "lon", "agl_m", "psi_deg", "phi_deg", "alpha_deg", "beta_deg",
                 "r_rad", "tas_ms", "mass_kg", "rho", "t_zulu_s", "t_local_s", "sky_t_s", "day",
                 "wind_x_ms", "wind_z_ms")

    def __init__(self):
        self.lat = self.lon = 0.0
        self.agl_m = 0.0
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

    __slots__ = ("faxil_n", "fside_n", "fnrml_n", "roll_nm", "force_n",
                 "w_centre", "w_left", "w_right", "w_tail", "w_span", "dw_dy", "dw_dy_helix")

    def __init__(self):
        self.clear()

    def clear(self):
        self.faxil_n = self.fside_n = self.fnrml_n = self.roll_nm = self.force_n = 0.0
        self.w_centre = self.w_left = self.w_right = self.w_tail = self.w_span = 0.0
        self.dw_dy = self.dw_dy_helix = 0.0


class Nearest:
    """Nearest alive thermal, refreshed by slow_update."""

    __slots__ = ("distance_m", "bearing_deg", "core_ms", "alive", "loaded")

    def __init__(self):
        self.distance_m = -1.0  # -1: none within NEAREST_MAX_M
        self.bearing_deg = 0.0
        self.core_ms = 0.0  # lift at its centre, at the aircraft's height
        self.alive = 0  # thermals alive among those loaded
        self.loaded = 0


class NativeThermalGuard:
    """Keeps XP12's native thermal setting at 0 while our thermals are active.

    Thermal strategy A (SPEC): the native setting only adds a uniform sink, so
    it must be 0 under our thermals. Real weather and a new flight can rewrite
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


class Injector:
    def __init__(self, settings, geometry):
        self.settings = settings
        self.uniform_ms = 0.0
        self.debug_dwdy = 0.0
        self.samples = None
        self.clp = 0.0
        self.geometry = None
        self.set_geometry(geometry)
        self.frame = None
        self.field = None
        self._field_key = None
        self.drift = AirDrift()
        self.lean = Lean()
        self.lean_e_m = self.lean_n_m = 0.0  # the lean at the aircraft, last frame: published
        self.nearest = Nearest()

    def set_geometry(self, geometry):
        self.geometry = geometry
        self.samples = inj.SampleGeometry(geometry.span_m, geometry.tail_arm_m)
        self.clp = inj.roll_damping(geometry.aspect_ratio, geometry.taper)

    @property
    def sky_index(self):
        return sky_index(self.settings.sky)

    def reset_field(self):
        """Forget the loaded thermals (they are regenerated identically on demand)."""
        self.field = None
        self._field_key = None

    # --- the wind ---------------------------------------------------------

    def carry(self, s):
        """Every frame, first: X-Plane's wind moves the sky as it moves the aircraft."""
        if self.settings.wind_enabled:
            # Local axes: x east, z south (engine/geo.py).
            self.drift.advance(s.wind_x_ms, -s.wind_z_ms, s.lat, s.sky_t_s)
        else:
            self.drift.hold(s.sky_t_s)

    def lean_update(self, s, altitudes_msl_m, speeds_kt, from_deg, msl_m):
        """Every few seconds: X-Plane's layers of wind lean the sky, if that is on."""
        st = self.settings
        if not (st.lean_enabled and st.wind_enabled):
            self.lean.reset()
            return
        heights, east, north = wind_layers(altitudes_msl_m, speeds_kt, from_deg, msl_m - s.agl_m)
        if heights:
            self.lean.set_wind(heights, east, north, sky_named(st.sky).cloud_base_zzi * st.zi_m,
                               st.wstar_ms, s.sky_t_s)

    def sky_position(self, s):
        """Where the aircraft is in the field's sky (m in the local frame), whatever it feels."""
        e, n = self.frame.to_enu(*self.drift.to_air(s.lat, s.lon))
        if self.settings.lean_enabled and self.settings.wind_enabled:
            self.lean_e_m, self.lean_n_m = self.lean.at(s.agl_m)
            return e - self.lean_e_m, n - self.lean_n_m
        self.lean_e_m = self.lean_n_m = 0.0
        return e, n

    # --- about once a second ----------------------------------------------

    def slow_update(self, s):
        """Keep the field loaded around the aircraft. Not for every frame."""
        st = self.settings
        lat, lon = self.drift.to_air(s.lat, s.lon)
        key = (st.seed, s.day, st.range_m, st.sky)
        if self.field is None or key != self._field_key:
            self.frame = LocalFrame(lat, lon)
            config = FieldConfig(seed=st.seed, day=s.day, range_m=st.range_m, sky=sky_named(st.sky))
            self.field = ThermalField(config, self.frame)
            self._field_key = key
        elif self.frame.distance_to_origin(lat, lon) > st.recentre_m:
            self.frame = LocalFrame(lat, lon)
            self.field.set_frame(self.frame)
        self.field.update(s.sky_t_s, lat, lon)

        near = self.nearest
        e, n = self.sky_position(s)
        th, r = self.field.nearest(e, n, s.sky_t_s, NEAREST_MAX_M)
        if th is None:
            near.distance_m, near.bearing_deg, near.core_ms = -1.0, 0.0, 0.0
        else:
            near.distance_m = r
            near.bearing_deg = math.degrees(math.atan2(th.e - e, th.n - n)) % 360.0
            near.core_ms = self.field.lift_at(th.e, th.n, s.agl_m, s.sky_t_s,
                                              st.wstar_ms, st.zi_m)
        near.alive = len(self.field.alive(s.sky_t_s))
        near.loaded = sum(1 for _ in self.field.thermals())

    # --- every frame ---------------------------------------------------------

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
            f, t, wstar, zi = self.field, s.sky_t_s, st.wstar_ms, st.zi_m
            wc = f.lift_at(g.ce, g.cn, g.cz, t, wstar, zi)
            wl = f.lift_at(g.le, g.ln, g.lz, t, wstar, zi)
            wr = f.lift_at(g.re, g.rn, g.rz, t, wstar, zi)
            wt = f.lift_at(g.te, g.tn, g.tz, t, wstar, zi)
        else:
            wl = wc = wr = wt = 0.0
        w = inj.span_average(wl, wc, wr)
        force = inj.energy_force(s.mass_kg, w, s.tas_ms)
        # The engine's beta is positive with the velocity right of the nose; X-Plane's
        # is positive with the nose right of the velocity.
        fwd, right, up = inj.path_force_body(force, s.alpha_deg, -s.beta_deg)
        span = self.geometry.span_m
        dw_dy = self.debug_dwdy if self.debug_dwdy != 0.0 else inj.span_gradient(wl, wr, span)
        helix = inj.helix_gradient(w, s.r_rad, s.tas_ms) if st.helix_enabled else 0.0
        dw_dy += helix
        roll = 0.0
        if st.roll_enabled:
            roll = inj.gust_roll_moment(s.rho, s.tas_ms, self.geometry.area_m2, span,
                                        dw_dy, self.clp)
        out.faxil_n = -fwd
        out.fside_n = right
        out.fnrml_n = up
        out.roll_nm = roll
        out.force_n = force
        out.w_centre, out.w_left, out.w_right, out.w_tail = wc, wl, wr, wt
        out.w_span = w
        out.dw_dy = dw_dy
        out.dw_dy_helix = helix
        return out
