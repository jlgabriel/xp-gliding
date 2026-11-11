"""X-Plane datarefs and objects of the adapter. With `plugin` and `hud`, the only modules with `xp`.

Every dataref is looked up once, when the plugin starts. Per frame the adapter
makes 17 reads of the aircraft state and the wind and reads and writes the four force
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
    ("msl_m", "sim/flightmodel/position/elevation", "d"),
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
    ("wind_x_ms", "sim/weather/aircraft/wind_now_x_msc", "f"),
    ("wind_z_ms", "sim/weather/aircraft/wind_now_z_msc", "f"),
)

WIND_LAYERS = 13  # sim/weather/aircraft/wind_*: float[13]
AIR_LAYERS = 13  # temperatures and dew points aloft, at region/temperature_altitude_msl_m: float[13]


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
        # The "Glider" category ticked in Plane Maker: how a motor glider says it is one.
        self._is_glider = xp.findDataRef("sim/aircraft2/metadata/is_glider")
        self._local = tuple(xp.findDataRef("sim/flightmodel/position/local_" + c) for c in "xyz")
        self._wind_alt = xp.findDataRef("sim/weather/aircraft/wind_altitude_msl_m")
        self._wind_speed = xp.findDataRef("sim/weather/aircraft/wind_speed_kts")
        self._wind_from = xp.findDataRef("sim/weather/aircraft/wind_direction_degt")
        self._air_alt = xp.findDataRef("sim/weather/region/temperature_altitude_msl_m")
        self._air_temp = xp.findDataRef("sim/weather/aircraft/temperatures_aloft_deg_c")
        self._air_dew = xp.findDataRef("sim/weather/aircraft/dewpoint_deg_c")

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

    def local_position(self):
        """Aircraft (x, y, z) in X-Plane's local coordinates. Only the slow path needs it."""
        return tuple(xp.getDatad(ref) for ref in self._local)

    def wind_layers(self):
        """Altitudes MSL (m), speeds (kt) and where the wind comes from (deg). Not per frame."""
        layers = [], [], []
        for ref, values in zip((self._wind_alt, self._wind_speed, self._wind_from), layers):
            xp.getDatavf(ref, values, 0, WIND_LAYERS)
        return layers

    def air_layers(self):
        """Heights MSL (m), temperatures and dew points (C) of X-Plane's layers; -100 is no data.
        Only when a sky begins and once more later (`core.WeatherBase`)."""
        layers = [], [], []
        for ref, values in zip((self._air_alt, self._air_temp, self._air_dew), layers):
            xp.getDatavf(ref, values, 0, AIR_LAYERS)
        return layers

    def engine_count(self):
        return xp.getDatai(self._engines)

    def is_glider(self):
        """True if the aircraft's author filed it as a glider. False where X-Plane has no such dataref."""
        return self._is_glider is not None and bool(xp.getDatai(self._is_glider))

    @staticmethod
    def user_aircraft_path():
        _, path = xp.getNthAircraftModel(0)
        return path

    @staticmethod
    def place_user(lat, lon, msl_m, heading_deg, speed_ms):
        """Put the user's aircraft in level flight here (XPLMPlaceUserAtLocation, X-Plane 12)."""
        xp.placeUserAtLocation(lat, lon, msl_m, heading_deg, speed_ms)


class SkyObjects:
    """The SDK calls behind the markers and the clouds (`markers.py`, `clouds.py`): never
    per frame. folder: under `xp_gliding/assets/`."""

    def __init__(self, folder="markers"):
        assets = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                              "assets", folder)
        # XPLMLoadObject wants a path relative to X-Plane's folder, which Windows cannot give
        # across drives (a development link to the package on another drive, say).
        try:
            self.folder = os.path.relpath(assets, xp.getSystemPath()).replace(os.sep, "/")
        except ValueError:
            raise RuntimeError(f"xp_gliding's assets ({assets}) are on another drive than X-Plane "
                               f"({xp.getSystemPath()}): install the plugin inside X-Plane's folder") from None
        self._probe = None

    def ground_m(self, lat, lon):
        """The ground's height at a place, m MSL; None where no ground is loaded, which begins
        at about 125 km from the glider (notes/phase3.md). Far from the local origin one probe
        lands a little beside the place: within about 20 m of height at 40 km, in the Andes."""
        info = self._probed(lat, lon)
        if info.result != xp.ProbeHitTerrain:
            return None
        return xp.localToWorld(info.locationX, info.locationY, info.locationZ)[2]

    def is_wet(self, lat, lon):
        """Is this place on water, a pond or a river as much as the sea? Not where no ground is
        loaded (notes/phase3.md)."""
        info = self._probed(lat, lon)
        return info.result == xp.ProbeHitTerrain and bool(info.is_wet)

    def _probed(self, lat, lon):
        if self._probe is None:
            self._probe = xp.createProbe(xp.ProbeY)
        return xp.probeTerrainXYZ(self._probe, *xp.worldToLocal(lat, lon, 0.0))

    def release_probe(self):
        if self._probe is not None:
            xp.destroyProbe(self._probe)
            self._probe = None

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
    def set_position(instance, x, y, z, data=None, pitch=0.0, heading=0.0):
        xp.instanceSetPosition(instance, (x, y, z, pitch, heading, 0.0), data)

    @staticmethod
    def auto_shift(instance):
        xp.instanceSetAutoShift(instance)
