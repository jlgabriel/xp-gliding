"""X-Plane datarefs and objects of the adapter. With `plugin`, the only modules with `xp`.

Every dataref is looked up once, when the plugin starts. Per frame the adapter
makes 13 reads of the aircraft state and reads and writes the four force
datarefs; nothing else crosses into the SDK in the per-frame path.

Forces: DataRefs.txt says to *add* to the `*_plug_acf` datarefs, and X-Plane
clears them every frame (baseline test B: a plugin that adds to the current
value applies its force exactly once per frame). So the adapter reads each
one and adds its own force once per frame from its before-flight-model loop,
which keeps any other plugin's force written earlier in the same frame.
"""

import os

import xp

from ..engine.field import sky_time

STATE = (
    ("lat", "sim/flightmodel/position/latitude", "d"),
    ("lon", "sim/flightmodel/position/longitude", "d"),
    ("agl_m", "sim/flightmodel/position/y_agl", "f"),
    ("psi_deg", "sim/flightmodel/position/psi", "f"),
    ("phi_deg", "sim/flightmodel/position/phi", "f"),
    ("alpha_deg", "sim/flightmodel/position/alpha", "f"),
    ("beta_deg", "sim/flightmodel/position/beta", "f"),
    ("r_rad", "sim/flightmodel/position/Rrad", "f"),
    ("tas_ms", "sim/flightmodel/position/true_airspeed", "f"),
    ("mass_kg", "sim/flightmodel/weight/m_total", "f"),
    ("rho", "sim/weather/rho", "f"),
    ("t_zulu_s", "sim/time/zulu_time_sec", "f"),
    ("t_local_s", "sim/time/local_time_sec", "f"),
    ("day", "sim/time/local_date_days", "i"),
)


class XPlaneIO:
    def __init__(self):
        get = {"f": xp.getDataf, "d": xp.getDatad, "i": xp.getDatai}
        self._state = tuple((attr, get[kind], xp.findDataRef(name)) for attr, name, kind in STATE)
        self._paused = xp.findDataRef("sim/time/paused")
        self._replay = xp.findDataRef("sim/time/is_in_replay")
        self._faxil = xp.findDataRef("sim/flightmodel/forces/faxil_plug_acf")
        self._fside = xp.findDataRef("sim/flightmodel/forces/fside_plug_acf")
        self._fnrml = xp.findDataRef("sim/flightmodel/forces/fnrml_plug_acf")
        self._roll = xp.findDataRef("sim/flightmodel/forces/L_plug_acf")
        self._native = xp.findDataRef("sim/weather/region/thermal_rate_ms")
        self._engines = xp.findDataRef("sim/aircraft/engine/acf_num_engines")
        self._elevation = xp.findDataRef("sim/flightmodel/position/elevation")
        self._local = tuple(xp.findDataRef("sim/flightmodel/position/local_" + c) for c in "xyz")

    def frozen(self):
        """True while paused or in replay: no force is applied then."""
        return bool(xp.getDatai(self._paused) or xp.getDatai(self._replay))

    def read_state(self, s):
        for attr, get, ref in self._state:
            setattr(s, attr, get(ref))
        s.sky_t_s = sky_time(s.t_zulu_s, s.t_local_s)
        return s

    def apply(self, out):
        getf, setf = xp.getDataf, xp.setDataf
        setf(self._faxil, getf(self._faxil) + out.faxil_n)
        setf(self._fside, getf(self._fside) + out.fside_n)
        setf(self._fnrml, getf(self._fnrml) + out.fnrml_n)
        setf(self._roll, getf(self._roll) + out.roll_nm)

    def read_native_thermals(self):
        return xp.getDataf(self._native)

    def write_native_thermals(self, value):
        xp.setDataf(self._native, value)

    def elevation_m(self):
        """Aircraft height MSL (m). Not part of the state: only the slow path needs it."""
        return xp.getDatad(self._elevation)

    def local_position(self):
        """Aircraft (x, y, z) in X-Plane's local coordinates. Only the slow path needs it."""
        return tuple(xp.getDatad(ref) for ref in self._local)

    def engine_count(self):
        return xp.getDatai(self._engines)

    @staticmethod
    def user_aircraft_path():
        _, path = xp.getNthAircraftModel(0)
        return path


class SkyObjects:
    """The SDK calls behind the markers and the clouds (`markers.py`, `clouds.py`): never
    per frame. folder: under `xp_gliding/assets/`."""

    def __init__(self, folder="markers"):
        assets = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "assets", folder)
        # XPLMLoadObject wants a path relative to X-Plane's folder.
        self.folder = os.path.relpath(assets, xp.getSystemPath()).replace(os.sep, "/")

    def load_async(self, name, loaded):
        """Load in the background; later, on the main thread, loaded(reference or None, name)."""
        xp.loadObjectAsync(f"{self.folder}/{name}.obj", loaded, name)

    @staticmethod
    def unload(obj):
        xp.unloadObject(obj)

    @staticmethod
    def create(obj, datarefs=None):
        return xp.createInstance(obj, datarefs)

    @staticmethod
    def destroy(instance):
        xp.destroyInstance(instance)

    @staticmethod
    def world_to_local(lat, lon, msl_m):
        return xp.worldToLocal(lat, lon, msl_m)

    @staticmethod
    def set_position(instance, x, y, z, data=None):
        xp.instanceSetPosition(instance, (x, y, z, 0.0, 0.0, 0.0), data)

    @staticmethod
    def auto_shift(instance):
        xp.instanceSetAutoShift(instance)
