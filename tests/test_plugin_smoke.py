"""Smoke test of the XPPython3 plugin with a minimal fake `xp` module.

Not a simulation of X-Plane: it checks that the plugin starts, registers its
datarefs and commands, adds its force to the `*_plug_acf` datarefs once per
frame, respects pause, holds the native thermal setting at 0 and restores it,
and creates, moves and destroys the instances of the training markers and clouds.
"""

import importlib
import itertools
import json
import math
import sys
import types

import pytest

from xp_gliding.engine.clouds import carries_cloud
from xp_gliding.engine.field import sky_named

DATA = {
    "sim/flightmodel/position/latitude": 32.6875,
    "sim/flightmodel/position/longitude": -103.217,
    "sim/flightmodel/position/y_agl": 800.0,
    "sim/flightmodel/position/elevation": 1916.0,
    "sim/flightmodel/position/local_x": 0.0,
    "sim/flightmodel/position/local_y": 916.0,
    "sim/flightmodel/position/local_z": 0.0,
    "sim/flightmodel/position/psi": 90.0,
    "sim/flightmodel/position/phi": 0.0,
    "sim/flightmodel/position/alpha": 0.0,
    "sim/flightmodel/position/beta": 0.0,
    "sim/flightmodel/position/Rrad": 0.0,
    "sim/flightmodel/position/true_airspeed": 28.0,
    "sim/flightmodel/weight/m_total": 541.0,
    "sim/weather/rho": 1.0,
    "sim/time/zulu_time_sec": 43200.0,
    "sim/time/local_time_sec": 18000.0,
    "sim/time/local_date_days": 305,
    "sim/time/paused": 0,
    "sim/time/is_in_replay": 0,
    "sim/flightmodel/forces/faxil_plug_acf": 0.0,
    "sim/flightmodel/forces/fside_plug_acf": 0.0,
    "sim/flightmodel/forces/fnrml_plug_acf": 0.0,
    "sim/flightmodel/forces/L_plug_acf": 0.0,
    "sim/weather/region/thermal_rate_ms": 0.62,
    "sim/time/total_running_time_sec": 100.0,
    "sim/flightmodel/position/indicated_airspeed": 48.6,
    "sim/aircraft/engine/acf_num_engines": 0,
    "sim/weather/aircraft/wind_now_x_msc": 0.0,
    "sim/weather/aircraft/wind_now_z_msc": 0.0,
    # Thirteen layers from near the ground up, 15 kt from the west in all of them by default.
    "sim/weather/aircraft/wind_altitude_msl_m": [300.0 + 500.0 * k for k in range(13)],
    "sim/weather/aircraft/wind_speed_kts": [15.0] * 13,
    "sim/weather/aircraft/wind_direction_degt": [270.0] * 13,
}


ADAPTER_MODULES = ("xp_gliding.adapter.xpio", "xp_gliding.adapter.hud",
                   "xp_gliding.adapter.plugin")


def make_fake_xp(tmp_path, data):
    xp = types.ModuleType("xp")
    xp.accessors = {}
    xp.handlers = {}
    for name in ("Type_Int", "Type_Float", "FlightLoop_Phase_BeforeFlightModel", "CommandBegin",
                 "Menu_Checked", "Menu_Unchecked", "MSG_PLANE_LOADED",
                 "FlightLoop_Phase_AfterFlightModel", "WindowDecorationNone",
                 "WindowLayerFlightOverlay"):
        setattr(xp, name, name)
    xp.findDataRef = lambda name: name
    xp.getDataf = xp.getDatad = lambda ref: float(data[ref])
    xp.getDatai = lambda ref: int(data[ref])
    xp.setDataf = lambda ref, v: data.__setitem__(ref, v)

    def get_vector(ref, values, offset, count):
        values.extend(data[ref][offset:offset + count])
        return count

    xp.getDatavf = get_vector
    xp.getSystemPath = lambda: str(tmp_path)
    xp.getNthAircraftModel = lambda i: ("ASK21.acf", data.get("acf_path", "ASK21.acf"))

    def register(name, kind, writable, readInt=None, writeInt=None, readFloat=None,
                 writeFloat=None, readRefCon=None, writeRefCon=None):
        xp.accessors[name] = (readInt or readFloat, writeInt or writeFloat, readRefCon)
        return name

    xp.registerDataAccessor = register
    xp.unregisterDataAccessor = lambda ref: xp.accessors.pop(ref)
    xp.createCommand = lambda name, desc: name
    xp.registerCommandHandler = lambda cmd, h, before, refcon: xp.handlers.__setitem__(cmd, (h, refcon))
    xp.unregisterCommandHandler = lambda cmd, h, before, refcon: xp.handlers.pop(cmd)
    xp.findPluginsMenu = lambda: "plugins"
    xp.menus = {}  # title -> {"handler", "items": [(label, refcon)], "checked": {index}}

    def create_menu(title, parent, item, handler, refcon):
        xp.menus[title] = {"handler": handler, "items": [], "checked": set()}
        return title

    def append_item(menu, name, refcon):
        if menu not in xp.menus:
            return 0
        xp.menus[menu]["items"].append((name, refcon))
        return len(xp.menus[menu]["items"]) - 1

    def check_item(menu, index, check):
        if check == xp.Menu_Checked:
            xp.menus[menu]["checked"].add(index)
        else:
            xp.menus[menu]["checked"].discard(index)

    xp.appendMenuItem = append_item
    xp.createMenu = create_menu
    xp.appendMenuItemWithCommand = lambda menu, name, cmd: append_item(menu, name, cmd)
    xp.appendMenuSeparator = lambda menu: None
    xp.checkMenuItem = check_item
    xp.destroyMenu = lambda menu: xp.menus.pop(menu)
    xp.removeMenuItem = lambda menu, index: None
    xp.createFlightLoop = lambda cb, phase, refcon: "loop"
    xp.scheduleFlightLoop = lambda loop, interval, relative: None
    xp.destroyFlightLoop = lambda loop: None

    # Objects and instances: enough to count them and see their last position.
    xp.objects = {}  # reference -> path
    xp.instances = {}  # reference -> [object reference, position]
    xp.calls = {"worldToLocal": 0, "loadObject": 0}
    xp.bad_object = None
    xp.deliveries = None  # a list holds the async loads back until they are delivered
    counter = itertools.count(1)

    def load_object(path):
        xp.calls["loadObject"] += 1
        if xp.bad_object and xp.bad_object in path:
            return None
        ref = f"obj{next(counter)}"
        xp.objects[ref] = path
        return ref

    def create_instance(obj, dataRefs=None):
        assert obj in xp.objects
        ref = f"inst{next(counter)}"
        xp.instances[ref] = [obj, None, None, dataRefs]
        return ref

    def world_to_local(lat, lon, alt=0.0):
        xp.calls["worldToLocal"] += 1
        return (lon + 103.0) * 90000.0, alt - 1000.0, -(lat - 32.0) * 110000.0

    def set_position(instance, position, data=None):
        assert len(position) == 6
        xp.instances[instance][1] = tuple(position)
        xp.instances[instance][2] = data
        if xp.instances[instance][3]:
            assert data is not None and len(data) == len(xp.instances[instance][3])

    def load_object_async(path, loaded, refCon=None):
        delivery = lambda: loaded(load_object(path), refCon)  # noqa: E731
        if xp.deliveries is None:
            delivery()
        else:
            xp.deliveries.append(delivery)

    xp.loadObjectAsync = load_object_async
    xp.unloadObject = lambda obj: xp.objects.pop(obj)
    xp.createInstance = create_instance
    xp.destroyInstance = lambda instance: xp.instances.pop(instance)
    xp.worldToLocal = world_to_local
    xp.instanceSetPosition = set_position

    # Terrain probes: the ground is xp.ground(lat, lon), or None where none is loaded.
    xp.ground = lambda lat, lon: 1116.0
    xp.wet = lambda lat, lon: False
    xp.ProbeY = 0
    xp.ProbeHitTerrain = 0
    xp.probes = []

    def create_probe(kind):
        xp.probes.append(kind)
        return f"probe{len(xp.probes)}"

    def probe_terrain(probe, x, y, z):
        assert probe is not None
        lat, lon = 32.0 - z / 110000.0, x / 90000.0 - 103.0
        ground = xp.ground(lat, lon)
        return types.SimpleNamespace(result=2 if ground is None else 0, is_wet=xp.wet(lat, lon), locationX=x,
                                     locationY=(ground or 0.0) - 1000.0, locationZ=z)

    xp.createProbe = create_probe
    xp.destroyProbe = lambda probe: xp.probes.pop()
    xp.probeTerrainXYZ = probe_terrain
    xp.localToWorld = lambda x, y, z: (32.0 - z / 110000.0, x / 90000.0 - 103.0, y + 1000.0)
    xp.shifted = set()
    xp.instanceSetAutoShift = xp.shifted.add
    return xp


@pytest.fixture
def plugin(tmp_path, monkeypatch):
    data = dict(DATA)
    xp = make_fake_xp(tmp_path, data)
    monkeypatch.setitem(sys.modules, "xp", xp)
    for mod in ADAPTER_MODULES:
        sys.modules.pop(mod, None)
    plugin_mod = importlib.import_module("xp_gliding.adapter.plugin")
    pi = plugin_mod.PythonInterface()
    pi.XPluginStart()
    pi.XPluginEnable()
    yield pi, xp, data
    pi.XPluginDisable()
    pi.XPluginStop()
    assert not xp.instances and not xp.objects  # nothing left behind
    for mod in ADAPTER_MODULES:
        sys.modules.pop(mod, None)


def dataref(xp, name, value=None):
    read, write, refcon = xp.accessors["xp_gliding/" + name]
    if value is not None:
        write(refcon, value)
    return read(refcon)


def frame(pi, data):
    for k in ("faxil", "fside", "fnrml", "L"):
        data[f"sim/flightmodel/forces/{k}_plug_acf"] = 0.0  # X-Plane clears them every frame
    assert pi.flight_loop(0.016, 0.016, 0, None) == -1


def test_uniform_lift_is_added_once_per_frame(plugin):
    pi, xp, data = plugin
    assert dataref(xp, "debug/uniform_ms", 1.0) == 1.0
    data["sim/flightmodel/forces/faxil_plug_acf"] = -10.0  # another plugin's force, same frame
    pi.flight_loop(0.016, 0.016, 0, None)
    expected = -541.0 * 9.80665 * 1.0 / 28.0
    assert data["sim/flightmodel/forces/faxil_plug_acf"] == pytest.approx(expected - 10.0)
    frame(pi, data)
    assert data["sim/flightmodel/forces/faxil_plug_acf"] == pytest.approx(expected)
    assert dataref(xp, "active") == 1
    assert dataref(xp, "force_n") == pytest.approx(-expected)
    assert dataref(xp, "lift_ms") == 1.0
    assert dataref(xp, "span_m") > 10.0


def test_pause_and_toggle_stop_the_force(plugin):
    pi, xp, data = plugin
    dataref(xp, "debug/uniform_ms", 1.0)
    data["sim/time/paused"] = 1
    frame(pi, data)
    assert data["sim/flightmodel/forces/faxil_plug_acf"] == 0.0 and dataref(xp, "active") == 0
    data["sim/time/paused"] = 0
    handler, attr = xp.handlers["xp_gliding/toggle"]
    handler("xp_gliding/toggle", xp.CommandBegin, attr)
    frame(pi, data)
    assert data["sim/flightmodel/forces/faxil_plug_acf"] == 0.0 and dataref(xp, "enabled") == 0


def test_native_thermals_held_at_zero_while_active_and_restored(plugin):
    pi, xp, data = plugin
    frame(pi, data)
    assert data["sim/weather/region/thermal_rate_ms"] == 0.0
    assert dataref(xp, "native_saved_ms") == pytest.approx(0.62)
    dataref(xp, "thermals_enabled", 0)
    frame(pi, data)
    assert data["sim/weather/region/thermal_rate_ms"] == pytest.approx(0.62)


def test_powered_aircraft_is_left_alone(plugin):
    pi, xp, data = plugin
    data["sim/aircraft/engine/acf_num_engines"] = 1
    pi.XPluginReceiveMessage(0, xp.MSG_PLANE_LOADED, 0)
    dataref(xp, "debug/uniform_ms", 1.0)
    frame(pi, data)
    assert data["sim/flightmodel/forces/faxil_plug_acf"] == 0.0
    assert data["sim/weather/region/thermal_rate_ms"] == pytest.approx(0.62)


def test_an_error_stops_the_effect_without_raising(plugin, capsys):
    pi, xp, data = plugin
    frame(pi, data)
    del data["sim/flightmodel/position/y_agl"]
    assert pi.flight_loop(0.016, 0.016, 0, None) == 0
    assert "error in the flight loop" in capsys.readouterr().out
    assert data["sim/weather/region/thermal_rate_ms"] == pytest.approx(0.62)


def test_inert_at_the_main_menu(plugin):
    pi, xp, data = plugin
    data["acf_path"] = str(xp.getSystemPath())  # what X-Plane reports with no aircraft
    pi.XPluginReceiveMessage(0, xp.MSG_PLANE_LOADED, 0)
    dataref(xp, "debug/uniform_ms", 1.0)
    frame(pi, data)
    assert data["sim/flightmodel/forces/faxil_plug_acf"] == 0.0
    assert data["sim/weather/region/thermal_rate_ms"] == pytest.approx(0.62)


# --- training markers -----------------------------------------------------------

def markers_tick(pi, data):
    """Run the frame of a marker update (half a second after the slow path's frame)."""
    frame(pi, data)  # the slow path, if due
    pi.next_slow = float("inf")
    pi.next_markers = 0.0
    frame(pi, data)
    pi.next_slow = 0.0


def test_markers_are_off_by_default(plugin):
    pi, xp, data = plugin
    assert dataref(xp, "markers_enabled") == 0
    pi.injector.is_wet = pi.injector.heights = None  # the field's use of the terrain is not the markers'
    for _ in range(3):
        markers_tick(pi, data)
    assert not xp.instances and not xp.objects
    assert xp.calls == {"worldToLocal": 0, "loadObject": 0}
    assert dataref(xp, "markers/count") == 0 and dataref(xp, "markers/probe_distance_m") == -1.0


def test_markers_create_two_instances_per_thermal_at_the_right_heights(plugin):
    pi, xp, data = plugin
    dataref(xp, "markers_enabled", 1)
    markers_tick(pi, data)
    count = dataref(xp, "markers/count")
    assert 0 < count <= 20
    assert len(xp.instances) == 2 * count and dataref(xp, "markers/created") == count
    rings = [v for v in xp.instances.values() if "ring_" in xp.objects[v[0]]]
    columns = [v for v in xp.instances.values() if "column_" in xp.objects[v[0]]]
    assert len(rings) == len(columns) == count
    for value in xp.instances.values():
        position = value[1]
        assert position is not None and position[3:] == (0.0, 0.0, 0.0)
    # Rings at the glider's height, columns' tops at the top of the lift over its ground.
    assert {v[1][1] for v in rings} == {1916.0 - 1000.0}
    top = 1916.0 - 800.0 + 2000.0 / 1.1
    assert all(v[1][1] == pytest.approx(top - 1000.0) for v in columns)
    # Both instances of a thermal share x and z, and they are the thermal's.
    th = next(iter(pi.markers.shown))
    x, y, z = xp.worldToLocal(th.lat, th.lon, 1916.0)
    assert sum(v[1][0] == x and v[1][2] == z for v in xp.instances.values()) == 2
    # The probe compares the nearest one, in both coordinate systems.
    near = min(pi.markers.shown, key=lambda t: t.e ** 2 + t.n ** 2)
    x, y, z = xp.worldToLocal(near.lat, near.lon, 1916.0)
    assert dataref(xp, "markers/probe_local_distance_m") == pytest.approx((x * x + z * z) ** 0.5)
    assert dataref(xp, "markers/probe_distance_m") == pytest.approx((near.e ** 2 + near.n ** 2) ** 0.5)
    assert dataref(xp, "markers/probe_dy_m") == 0.0
    # Objects are shared, and exist under the assets folder.
    assert len(xp.objects) == 36
    assert all(p.endswith(".obj") and "xp_gliding/assets/markers/" in p for p in xp.objects.values())


def test_rings_follow_the_glider_and_selection_runs_less_often(plugin):
    pi, xp, data = plugin
    dataref(xp, "markers_enabled", 1)
    markers_tick(pi, data)
    before = set(xp.instances)
    data["sim/flightmodel/position/elevation"] += 3.0
    data["sim/flightmodel/position/y_agl"] += 3.0
    markers_tick(pi, data)
    assert set(xp.instances) == before and xp.calls["loadObject"] > 0
    rings = [v for v in xp.instances.values() if "ring_" in xp.objects[v[0]]]
    assert {v[1][1] for v in rings} == {1919.0 - 1000.0}
    assert dataref(xp, "markers/update_us") > 0.0


def test_markers_go_when_switched_off_and_with_the_thermals(plugin):
    pi, xp, data = plugin
    handler, attr = xp.handlers["xp_gliding/markers/toggle"]
    handler("xp_gliding/markers/toggle", xp.CommandBegin, attr)
    assert dataref(xp, "markers_enabled") == 1
    markers_tick(pi, data)
    assert xp.instances
    handler("xp_gliding/markers/toggle", xp.CommandBegin, attr)
    frame(pi, data)
    assert not xp.instances
    assert dataref(xp, "markers/destroyed") == dataref(xp, "markers/created") > 0
    dataref(xp, "markers_enabled", 1)
    markers_tick(pi, data)
    assert xp.instances
    dataref(xp, "thermals_enabled", 0)
    frame(pi, data)
    assert not xp.instances
    dataref(xp, "thermals_enabled", 1)
    markers_tick(pi, data)
    assert xp.instances
    dataref(xp, "enabled", 0)
    frame(pi, data)
    assert not xp.instances


def test_markers_stay_put_while_paused_and_go_when_switched_off_there(plugin):
    pi, xp, data = plugin
    dataref(xp, "markers_enabled", 1)
    markers_tick(pi, data)
    before = dict(xp.instances)
    calls = xp.calls["worldToLocal"]
    data["sim/time/paused"] = 1
    markers_tick(pi, data)
    assert xp.instances == before and xp.calls["worldToLocal"] == calls
    dataref(xp, "markers_enabled", 0)
    frame(pi, data)
    assert not xp.instances


def test_markers_change_with_the_sky(plugin):
    pi, xp, data = plugin
    dataref(xp, "markers_enabled", 1)
    markers_tick(pi, data)
    first = set(pi.markers.shown)
    pi.markers._next_select = 0.0
    dataref(xp, "seed", 2)  # another sky: every thermal is new
    pi.next_slow = 0.0
    markers_tick(pi, data)
    assert first.isdisjoint(pi.markers.shown)
    count = dataref(xp, "markers/count")
    assert dataref(xp, "markers/destroyed") == len(first)
    assert len(xp.instances) == 2 * count
    # Far away: nothing of the old place stays marked past its keep range.
    pi.markers._next_select = 0.0
    data["sim/flightmodel/position/latitude"] += 0.1
    pi.next_slow = 0.0
    markers_tick(pi, data)
    assert all(m.marker.distance_m <= 3300.0 for m in pi.markers.shown.values())
    assert len(xp.instances) == 2 * dataref(xp, "markers/count")


def test_a_marker_object_that_cannot_load_turns_them_off_without_an_error(plugin, capsys):
    pi, xp, data = plugin
    xp.bad_object = "ring_"
    dataref(xp, "markers_enabled", 1)
    markers_tick(pi, data)
    assert not xp.instances and not xp.objects
    assert capsys.readouterr().out.count("could not load the marker object") == 1
    assert dataref(xp, "active") == 1  # the thermals go on
    calls = xp.calls["loadObject"]
    markers_tick(pi, data)
    assert xp.calls["loadObject"] == calls  # tried once, not every update


def test_markers_wait_for_every_object_in_the_background(plugin):
    pi, xp, data = plugin
    xp.deliveries = []
    dataref(xp, "markers_enabled", 1)
    markers_tick(pi, data)
    assert not xp.instances and len(xp.deliveries) == 36  # asked for, none here yet
    markers_tick(pi, data)
    assert len(xp.deliveries) == 36  # not asked for twice
    for delivery in xp.deliveries[:35]:
        delivery()
    markers_tick(pi, data)
    assert not xp.instances
    xp.deliveries[35]()
    markers_tick(pi, data)
    assert xp.instances


def test_an_object_delivered_after_the_plugin_is_disabled_is_not_kept(plugin):
    pi, xp, data = plugin
    xp.deliveries = []
    dataref(xp, "markers_enabled", 1)
    markers_tick(pi, data)
    pi.XPluginDisable()
    for delivery in xp.deliveries:
        delivery()
    assert not xp.objects
    pi.XPluginEnable()


def test_an_error_clears_the_markers(plugin):
    pi, xp, data = plugin
    dataref(xp, "markers_enabled", 1)
    markers_tick(pi, data)
    del data["sim/flightmodel/position/y_agl"]
    assert pi.flight_loop(0.016, 0.016, 0, None) == 0
    assert not xp.instances


def test_hud_reads_the_energy_and_only_when_wanted(plugin):
    pi, xp, data = plugin
    hud = pi.hud
    hud._load_drawing = lambda: setattr(hud, "window", "window")
    xp.setWindowIsVisible = lambda window, visible: None
    xp.destroyWindow = lambda window: None
    pi.settings.hud_enabled = False
    hud.tick()
    assert hud.window is None
    pi.settings.hud_enabled = True
    data["acf_path"] = "Aircraft/Laminar Research/Schleicher ASK 21/ASK21.acf"
    pi.load_aircraft()
    assert hud.vario.has_netto
    for i in range(30):
        data["sim/time/total_running_time_sec"] += 0.1
        data["sim/flightmodel/position/elevation"] -= 0.1
        hud.tick()
    assert dataref(xp, "hud/te_ms") == pytest.approx(-1.0, abs=0.01)
    assert dataref(xp, "hud/netto_ms") > dataref(xp, "hud/te_ms")
    assert hud._te_text == "-1.0"
    assert hud._top_text.startswith("TOP ")
    assert hud.window == "window"


def test_a_failing_draw_stops_the_hud_and_nothing_else(plugin):
    pi, xp, data = plugin
    hud = pi.hud
    hud.window = "window"
    xp.getWindowGeometry = lambda window: 1 / 0
    xp.setWindowIsVisible = lambda window, visible: data.__setitem__("visible", visible)
    xp.destroyWindow = lambda window: None
    hud.on_draw("window", None)
    assert hud.failed
    hud.on_draw("window", None)  # must not raise, must not log again
    hud.tick()
    assert data["visible"] == 0
    frame(pi, data)
    assert dataref(xp, "active") == 1


# --- cumulus ---------------------------------------------------------------------------

def clouds_tick(pi, data):
    """Run the frames of a cloud update: one loading tiles, one planning."""
    frame(pi, data)  # the slow path, if due
    pi.next_slow = float("inf")
    for _ in range(2):
        pi.next_clouds = 0.0
        frame(pi, data)
        pi.next_clouds = 0.0
        pi.clouds._next_plan = 0.0
        frame(pi, data)
        pi.clouds._next_plan = float("inf")
    pi.next_slow = 0.0


def first_clouds(pi, data):
    """Until the first clouds: those within the tiles loaded all around (CloudCatalog.loaded_within_m)."""
    for _ in range(200):
        clouds_tick(pi, data)
        if pi.clouds.instances:
            return
    raise AssertionError("no cloud")


def fill_sky(pi, data):
    """Until every tile has loaded and no new cloud is waiting."""
    for _ in range(2000):
        clouds_tick(pi, data)
        if pi.clouds.catalog is not None and pi.clouds.catalog.started \
                and not pi.clouds.catalog.missing and not pi.clouds.more:
            return
    raise AssertionError("the sky did not fill")


def test_clouds_are_on_by_default_and_fill_the_sky_over_many_updates(plugin):
    pi, xp, data = plugin
    assert dataref(xp, "clouds_enabled") == 1
    first_clouds(pi, data)
    assert 0 < len(xp.instances) - dataref(xp, "clouds/pool_idle") <= 2 * pi.clouds.planner.params.max_new
    assert dataref(xp, "clouds/tiles_missing") > 0
    fill_sky(pi, data)
    count = dataref(xp, "clouds/count")
    idle = dataref(xp, "clouds/pool_idle")  # made in advance for the near rings
    assert count > 40 and len(xp.instances) == count + idle == dataref(xp, "clouds/created")
    assert all("xp_gliding/assets/clouds/cumulus.obj" in p for p in xp.objects.values())
    assert set(xp.instances) == xp.shifted
    assert dataref(xp, "clouds/nearest_m") >= 0.0
    assert dataref(xp, "clouds/nearest_base_m") >= dataref(xp, "clouds/level_m") > 0.0
    assert 0.6 <= dataref(xp, "clouds/nearest_scale") <= 1.4


def test_clouds_carry_their_rate_and_scale_at_the_base_of_the_clouds(plugin):
    pi, xp, data = plugin
    fill_sky(pi, data)
    wanted = ("xp_gliding/clouds/rate", "xp_gliding/clouds/scale")
    for name in wanted:
        assert name in xp.accessors
    # y in the fake's world_to_local is the height minus 1000; the base is above the ground
    # under the glider: 1916 - 800, plus the top of the lift.
    base = 1916.0 - 800.0 + 2000.0 / 1.1
    from xp_gliding.engine.clouds import SCALE_RANGE
    used = {inst for inst, _, _ in pi.clouds.instances.values()}
    assert used
    for ref, (_, position, values, drefs) in xp.instances.items():
        assert drefs == wanted
        if ref in used:
            assert position[1] == pytest.approx(base - 1000.0)
            assert values[0] > 0.0 and SCALE_RANGE[0] <= values[1] <= SCALE_RANGE[1]
        else:  # made in advance for a ring, not used yet
            assert values[0] == 0.0


def test_clouds_keep_a_level_over_low_ground_and_clear_a_hill(plugin):
    pi, xp, data = plugin
    lon0 = data["sim/flightmodel/position/longitude"]
    level = 1916.0 - 800.0 + 2000.0 / 1.1
    # A hill well above the level, beginning 0.05 deg east of the glider.
    xp.ground = lambda lat, lon: 4000.0 if lon > lon0 + 0.05 else 1116.0
    fill_sky(pi, data)
    assert dataref(xp, "clouds/level_m") == pytest.approx(level)
    bases = {th: entry[1] for th, entry in pi.clouds.instances.items()}
    west = [b for th, b in bases.items() if th.lon < lon0 + 0.04]
    east = [b for th, b in bases.items() if th.lon > lon0 + 0.06]
    assert west and all(b == pytest.approx(level) for b in west)
    assert east and all(b == pytest.approx(4300.0) for b in east)
    assert dataref(xp, "clouds/raised") == sum(b > level + 1.0 for b in bases.values()) >= len(east)
    assert dataref(xp, "clouds/base_max_m") == pytest.approx(4300.0)
    assert dataref(xp, "clouds/base_us") > 0.0
    # What was asked for is where the instance is.
    for th, (instance, base, _) in pi.clouds.instances.items():
        assert xp.instances[instance][1][1] == pytest.approx(base - 1000.0)


def test_a_cloud_is_high_enough_for_the_hill_it_will_drift_into(plugin):
    pi, xp, data = plugin
    lon0 = data["sim/flightmodel/position/longitude"]
    level = 1916.0 - 800.0 + 2000.0 / 1.1
    start, end = lon0 + 0.10, lon0 + 0.15
    xp.ground = lambda lat, lon: 4000.0 if start < lon < end else 1116.0
    data["sim/weather/aircraft/wind_now_x_msc"] = 10.0  # toward the east
    fill_sky(pi, data)
    upwind = {th: e[1] for th, e in pi.clouds.instances.items() if th.lon < start - 0.01}
    downwind = {th: e[1] for th, e in pi.clouds.instances.items() if th.lon > end + 0.01}
    assert any(b == pytest.approx(4300.0) for b in upwind.values())
    assert any(b == pytest.approx(level) for b in upwind.values())
    assert downwind and all(b == pytest.approx(level) for b in downwind.values())


def test_with_no_ground_loaded_a_cloud_stays_at_the_level(plugin):
    pi, xp, data = plugin
    xp.ground = lambda lat, lon: None
    fill_sky(pi, data)
    level = 1916.0 - 800.0 + 2000.0 / 1.1
    assert all(e[1] == pytest.approx(level) for e in pi.clouds.instances.values())
    assert dataref(xp, "clouds/ground_misses") >= 5 * dataref(xp, "clouds/created") > 0
    assert dataref(xp, "clouds/raised") == 0


def test_the_level_stays_for_a_sky_and_is_new_with_the_next(plugin):
    pi, xp, data = plugin
    clouds_tick(pi, data)
    level = dataref(xp, "clouds/level_m")
    # The glider over ground 300 m higher: the sky that is already there keeps its level.
    data["sim/flightmodel/position/y_agl"] -= 300.0
    fill_sky(pi, data)
    assert dataref(xp, "clouds/level_m") == level
    assert len({round(e[1], 3) for e in pi.clouds.instances.values()}) == 1
    pi.injector.reset_field()
    clouds_tick(pi, data)
    assert dataref(xp, "clouds/level_m") == pytest.approx(level + 300.0)


def test_a_tool_can_change_the_sky_without_saving_it(plugin):
    pi, xp, data = plugin
    with open(pi.config_path, encoding="utf-8") as f:
        before = f.read()
    pi.injector.sky_index = 2
    assert dataref(xp, "sky_index") == 2
    pi.injector.sky_index = 99
    assert dataref(xp, "sky_index") == 2  # no such sky
    with open(pi.config_path, encoding="utf-8") as f:
        assert f.read() == before


def test_no_thermal_or_cloud_is_born_over_water(plugin):
    pi, xp, data = plugin
    xp.wet = lambda lat, lon: lon > -103.0  # the sea, east of the glider
    fill_sky(pi, data)
    field = pi.injector.field
    assert dataref(xp, "water/rejected") > 0 and dataref(xp, "water/checked") > dataref(xp, "water/rejected")
    thermals = list(field.thermals())
    clouds = list(pi.clouds.catalog.thermals())
    assert thermals and clouds
    assert all(th.lon <= -103.0 for th in thermals)
    assert all(th.lon <= -103.0 for th in clouds)


def test_water_needs_ground_to_be_water(plugin):
    pi, xp, data = plugin
    xp.ground = lambda lat, lon: None  # the terrain's flag means nothing where nothing is loaded
    xp.wet = lambda lat, lon: True
    fill_sky(pi, data)
    assert dataref(xp, "water/rejected") == 0 and dataref(xp, "water/checked") > 0


def test_the_probe_is_made_once_and_goes_with_the_plugin(plugin):
    pi, xp, data = plugin
    assert not xp.probes  # nothing asked of the terrain before a flight needs it
    fill_sky(pi, data)
    assert len(xp.probes) == 1
    pi.clouds.shutdown()
    assert not xp.probes


def test_a_filled_cloud_settles_to_its_steady_rate(plugin):
    pi, xp, data = plugin
    fill_sky(pi, data)
    params = pi.clouds.planner.params
    assert any(v[2][0] > 1.0 for v in xp.instances.values())  # filling fast
    data["sim/time/zulu_time_sec"] += params.ttl_s / params.prewarm + 1.0
    fill_sky(pi, data)
    data["sim/time/zulu_time_sec"] += 1.0
    clouds_tick(pi, data)
    near = [(v[2][0], th) for th, (inst, _, _) in pi.clouds.instances.items() for v in [xp.instances[inst]]]
    assert dataref(xp, "clouds/rate_changes") > 0
    assert all(rate <= 1.0 + 1e-9 or pi.clouds.planner.shown[th].fast_until
               > data["sim/time/zulu_time_sec"] for rate, th in near)


def settled_sky(pi, data):
    """A full sky, every cloud past its fast fill and its rest: in steps, or it is a new sky."""
    fill_sky(pi, data)
    for _ in range(5):
        data["sim/time/zulu_time_sec"] += 60.0
        clouds_tick(pi, data)
    shown = pi.clouds.planner.shown
    steady = [rate == shown[th].level for th, (_, _, rate) in pi.clouds.instances.items()]
    assert sum(steady) > 0.9 * len(steady)  # but the clouds of new thermals


def order_tick(pi, data):
    """The frame of a cloud update that hands clouds over between rings."""
    pi.next_slow = float("inf")
    pi.next_clouds = 0.0
    pi.clouds._next_plan = float("inf")
    pi.clouds._next_order = 0.0
    frame(pi, data)
    pi.next_slow = 0.0


def made(ref):
    """The order the fake X-Plane created an instance in."""
    return int(ref[len("inst"):])


def distances(pi, data):
    clouds = pi.clouds
    e, n = clouds.frame.to_enu(data["sim/flightmodel/position/latitude"],
                               data["sim/flightmodel/position/longitude"])
    return {th: math.hypot(th.e - e, th.n - n) for th in clouds.instances}


def test_a_nearer_ring_is_always_drawn_over_a_farther_one(plugin):
    from xp_gliding.engine.cloud_order import FAR, RING_SIZES, ring_of
    pi, xp, data = plugin
    fill_sky(pi, data)
    clouds = pi.clouds
    assert len(clouds.instances) > 100
    assert dataref(xp, "clouds/pool_idle") + sum(1 for i, _, _ in clouds.instances.values() if i in clouds.owner) \
        == sum(RING_SIZES)
    assert dataref(xp, "clouds/pool_misses") == 0
    rings = {th: ring_of(r) for th, r in distances(pi, data).items()}
    assert set(rings.values()) == set(range(FAR + 1))
    # Created earlier is drawn later, on top: every instance of a ring before any of the next.
    made_in = {}
    for th, ring in rings.items():
        made_in.setdefault(ring, []).append(made(clouds.instances[th][0]))
    for ring in range(FAR):
        assert max(made_in[ring]) < min(made_in[ring + 1])
    # Within a near ring too, as a new sky is created nearest first.
    r = distances(pi, data)
    for ring in range(FAR):
        by_distance = sorted((r[th], made(clouds.instances[th][0])) for th, k in rings.items() if k == ring)
        assert [m for _, m in by_distance] == sorted(m for _, m in by_distance)
    assert len(xp.instances) == len(clouds.instances) + dataref(xp, "clouds/pool_idle")


def test_a_cloud_the_glider_moves_into_another_ring_is_handed_over(plugin):
    from xp_gliding.engine.cloud_order import ring_of
    pi, xp, data = plugin
    settled_sky(pi, data)
    clouds = pi.clouds
    old = {th: inst for th, (inst, _, _) in clouds.instances.items()}
    before = {th: (xp.instances[inst][1], xp.instances[inst][2]) for th, inst in old.items()}
    rings_before = dict(clouds.rings)
    for _ in range(3):  # 3 km east, a slow update at each step: not a jump
        data["sim/flightmodel/position/longitude"] += 1000.0 / (111320.0 * math.cos(math.radians(32.6875)))
        clouds_tick(pi, data)
    for _ in range(20):
        order_tick(pi, data)
    handed = [th for th, (inst, _, _) in clouds.instances.items() if th in old and inst != old[th]]
    assert handed and dataref(xp, "clouds/handed_over") == len(handed) == dataref(xp, "clouds/cooling")
    assert dataref(xp, "clouds/order_us") > 0.0
    r = distances(pi, data)
    for th in handed:
        new = xp.instances[clouds.instances[th][0]]
        assert new[1][:3] == before[th][0][:3] and new[2][0] == clouds.instances[th][2] > 0.0
        assert xp.instances[old[th]][2][0] == 0.0  # the old one fed no more
        assert clouds.rings[th] == ring_of(r[th])
    # Coming nearer, the new instance fills fast; going away, it goes on at the cloud's rate.
    nearer = [th for th in handed if clouds.rings[th] < rings_before[th]]
    assert nearer and dataref(xp, "clouds/refilled") == len(nearer) < len(handed)
    prewarm = clouds.planner.params.prewarm
    # As the planner has it: fast for most, not for a cloud too young to need it.
    assert all(clouds.instances[th][2] == clouds.planner.shown[th].rate for th in nearer)
    assert sum(clouds.instances[th][2] == prewarm for th in nearer) > len(nearer) / 2
    assert all(clouds.instances[th][2] < prewarm * 0.3 for th in handed if th not in nearer)
    # Every cloud is in its ring now: nothing more to hand over.
    order_tick(pi, data)
    assert dataref(xp, "clouds/handed_over") == len(handed)
    # Once its particles have gone, an instance of a ring goes back to it; one of the far sky goes.
    params = clouds.planner.params
    idle = dataref(xp, "clouds/pool_idle")
    pooled = [th for th in handed if old[th] in clouds.owner]
    for _ in range(4):
        data["sim/time/zulu_time_sec"] += (params.ttl_s - 1.0) / 4
        clouds_tick(pi, data)
    assert all(old[th] in xp.instances for th in handed)
    data["sim/time/zulu_time_sec"] += 2.0
    clouds_tick(pi, data)
    assert dataref(xp, "clouds/cooling") == 0
    assert all((old[th] in xp.instances) == (th in pooled) for th in handed)
    assert dataref(xp, "clouds/pool_idle") >= idle + len(pooled) - dataref(xp, "clouds/handed_over") + len(handed)


def test_instances_waiting_or_idle_go_with_the_clouds(plugin):
    pi, xp, data = plugin
    settled_sky(pi, data)
    data["sim/flightmodel/position/longitude"] += 0.02
    clouds_tick(pi, data)
    order_tick(pi, data)
    assert pi.clouds.cooling and pi.clouds.pool.count()
    pi.clouds.clear()
    assert not xp.instances and not pi.clouds.cooling and not pi.clouds.owner and not pi.clouds.pool.count()


def test_clouds_go_when_switched_off_and_with_the_thermals(plugin):
    pi, xp, data = plugin
    handler, attr = xp.handlers["xp_gliding/clouds/toggle"]
    clouds_tick(pi, data)
    assert xp.instances
    handler("xp_gliding/clouds/toggle", xp.CommandBegin, attr)
    assert dataref(xp, "clouds_enabled") == 0
    frame(pi, data)
    assert not xp.instances and dataref(xp, "clouds/count") == 0
    handler("xp_gliding/clouds/toggle", xp.CommandBegin, attr)
    clouds_tick(pi, data)
    assert xp.instances
    dataref(xp, "thermals_enabled", 0)
    frame(pi, data)
    assert not xp.instances


def test_clouds_stay_put_while_paused(plugin):
    pi, xp, data = plugin
    clouds_tick(pi, data)
    before = {k: (v[1], v[2]) for k, v in xp.instances.items()}
    calls = xp.calls["worldToLocal"]
    data["sim/time/paused"] = 1
    clouds_tick(pi, data)
    assert {k: (v[1], v[2]) for k, v in xp.instances.items()} == before
    assert xp.calls["worldToLocal"] == calls


def test_clouds_start_over_with_a_new_flight_and_when_the_clock_jumps(plugin):
    pi, xp, data = plugin
    first_clouds(pi, data)
    pi.XPluginReceiveMessage(0, xp.MSG_PLANE_LOADED, 0)
    assert not xp.instances
    first_clouds(pi, data)
    created = dataref(xp, "clouds/created")
    old = set(xp.instances)
    data["sim/time/zulu_time_sec"] += 3600.0
    clouds_tick(pi, data)
    assert not old & set(xp.instances)
    first_clouds(pi, data)
    assert not old & set(xp.instances) and dataref(xp, "clouds/created") > created


def test_an_error_takes_the_clouds_away_with_the_rest(plugin, capsys):
    pi, xp, data = plugin
    clouds_tick(pi, data)
    assert xp.instances
    del data["sim/flightmodel/position/y_agl"]
    assert pi.flight_loop(0.016, 0.016, 0, None) == 0
    assert not xp.instances


def test_a_cloud_object_still_loading_when_switched_off_is_not_left_behind(plugin):
    pi, xp, data = plugin
    xp.deliveries = []
    clouds_tick(pi, data)
    assert len(xp.deliveries) == 1 and not xp.instances
    clouds_tick(pi, data)
    assert len(xp.deliveries) == 1  # asked for once
    pi.XPluginDisable()
    xp.deliveries.pop()()
    assert not xp.objects
    pi.XPluginEnable()
    xp.deliveries = None
    clouds_tick(pi, data)
    assert xp.instances


def test_the_sky_does_not_change_at_zulu_midnight(plugin):
    pi, xp, data = plugin
    data["sim/time/zulu_time_sec"], data["sim/time/local_time_sec"] = 86390.0, 61190.0
    first_clouds(pi, data)
    before = set(xp.instances)
    assert before
    data["sim/time/zulu_time_sec"], data["sim/time/local_time_sec"] = 10.0, 61210.0
    clouds_tick(pi, data)
    assert before <= set(xp.instances)
    assert pi.state.sky_t_s == 86410.0


def test_a_cloud_object_that_will_not_load_leaves_the_flight_alone(plugin, capsys):
    pi, xp, data = plugin
    xp.loadObjectAsync = lambda path, loaded, ref=None: loaded(None, ref)
    clouds_tick(pi, data)
    clouds_tick(pi, data)
    assert not xp.instances and pi.clouds.failed
    assert "could not load the cloud object" in capsys.readouterr().out
    assert dataref(xp, "active") == 1


# --- the wind ---------------------------------------------------------------------

def test_in_calm_air_the_clouds_are_not_moved(plugin):
    pi, xp, data = plugin
    fill_sky(pi, data)
    assert pi.clouds.instances
    for _ in range(8):
        data["sim/time/zulu_time_sec"] += 1.0
        clouds_tick(pi, data)
    assert dataref(xp, "clouds/moved") == 0


def test_the_wind_moves_every_cloud_about_once_a_second_downwind(plugin):
    pi, xp, data = plugin
    fill_sky(pi, data)
    before = {th: xp.instances[entry[0]][1] for th, entry in pi.clouds.instances.items()}
    data["sim/weather/aircraft/wind_now_x_msc"] = 10.0
    pi.next_clouds = 0.0
    frame(pi, data)  # the clock starts for the wind
    for _ in range(5):
        data["sim/time/zulu_time_sec"] += 1.0
        frame(pi, data)
    assert dataref(xp, "wind/e_ms") == 10.0 and dataref(xp, "wind/dlon_deg") > 0.0
    pi.clouds._next_plan = float("inf")
    pi.next_slow = float("inf")
    for _ in range(4 + 1):  # slices of a round, and the round's start
        pi.next_clouds = 0.0
        frame(pi, data)
    pi.next_slow = 0.0
    assert dataref(xp, "clouds/moved") >= len(before)
    after = {th: xp.instances[entry[0]][1] for th, entry in pi.clouds.instances.items()}
    assert all(after[th] != before[th] for th in before if th in after)


def test_a_moved_cloud_keeps_its_rate_and_scale(plugin):
    pi, xp, data = plugin
    fill_sky(pi, data)
    th, entry = next(iter(pi.clouds.instances.items()))
    rate = xp.instances[entry[0]][2]
    data["sim/weather/aircraft/wind_now_x_msc"] = 10.0
    frame(pi, data)
    data["sim/time/zulu_time_sec"] += 1.0
    frame(pi, data)
    pi.clouds._next_plan = float("inf")
    pi.next_slow = float("inf")
    for _ in range(5):
        pi.next_clouds = 0.0
        frame(pi, data)
    pi.next_slow = 0.0
    assert xp.instances[pi.clouds.instances[th][0]][2] == rate


def test_a_new_flight_puts_the_sky_back(plugin):
    pi, xp, data = plugin
    data["sim/weather/aircraft/wind_now_x_msc"] = 10.0
    frame(pi, data)
    data["sim/time/zulu_time_sec"] += 1.0
    frame(pi, data)
    assert dataref(xp, "wind/dlon_deg") > 0.0
    pi.XPluginReceiveMessage("x", xp.MSG_PLANE_LOADED, 0)
    assert dataref(xp, "wind/dlon_deg") == 0.0


def test_the_wind_can_be_switched_off(plugin):
    pi, xp, data = plugin
    handler, attr = xp.handlers["xp_gliding/wind/toggle"]
    data["sim/weather/aircraft/wind_now_x_msc"] = 10.0
    handler("xp_gliding/wind/toggle", xp.CommandBegin, attr)
    assert dataref(xp, "wind_enabled") == 0
    frame(pi, data)
    data["sim/time/zulu_time_sec"] += 1.0
    frame(pi, data)
    assert dataref(xp, "wind/dlon_deg") == 0.0


def test_markers_are_drawn_where_the_wind_took_their_thermals(plugin):
    pi, xp, data = plugin
    dataref(xp, "markers_enabled", 1)
    markers_tick(pi, data)
    th = next(iter(pi.markers.shown))
    before = xp.instances[pi.markers.shown[th].ring][1]
    data["sim/weather/aircraft/wind_now_x_msc"] = 10.0
    frame(pi, data)
    data["sim/time/zulu_time_sec"] += 1.0
    markers_tick(pi, data)
    assert th in pi.markers.shown
    assert xp.instances[pi.markers.shown[th].ring][1] != before


# --- the lean ---------------------------------------------------------------------

def test_thermals_do_not_lean_unless_asked(plugin):
    pi, xp, data = plugin
    assert dataref(xp, "lean_enabled") == 0
    data["sim/weather/aircraft/wind_now_x_msc"] = 7.7
    frame(pi, data)
    assert dataref(xp, "lean/e_m") == 0.0 and dataref(xp, "lean/n_m") == 0.0


def test_the_lean_comes_from_the_layers_of_wind_and_is_published(plugin):
    pi, xp, data = plugin
    dataref(xp, "lean_enabled", 1)
    pi.next_lean = 0.0
    frame(pi, data)
    # 15 kt toward the east, w* 3, base at Allen's top of 2000 m, the glider well below it.
    assert dataref(xp, "lean/e_m") < -100.0
    assert dataref(xp, "lean/n_m") == pytest.approx(0.0, abs=1.0)


def test_switching_the_lean_off_takes_it_away_and_the_menu_shows_it(plugin):
    pi, xp, data = plugin
    dataref(xp, "lean_enabled", 1)
    pi.next_lean = 0.0
    frame(pi, data)
    assert dataref(xp, "lean/e_m") != 0.0
    handler, attr = xp.handlers["xp_gliding/lean/toggle"]
    handler("xp_gliding/lean/toggle", xp.CommandBegin, attr)
    assert not pi.settings.lean_enabled
    frame(pi, data)
    assert dataref(xp, "lean/e_m") == 0.0


def test_the_ring_is_at_the_lift_and_the_column_leans_from_the_cloud_through_it(plugin):
    pi, xp, data = plugin
    dataref(xp, "markers_enabled", 1)
    markers_tick(pi, data)
    th = next(iter(pi.markers.shown))
    ring0 = xp.instances[pi.markers.shown[th].ring][1]
    column0 = xp.instances[pi.markers.shown[th].column][1]
    assert column0[3:] == (0.0, 0.0, 0.0)  # upright with no lean

    dataref(xp, "lean_enabled", 1)
    pi.next_lean = 0.0
    frame(pi, data)
    lean_e = dataref(xp, "lean/e_m")
    assert lean_e < -100.0
    markers_tick(pi, data)
    th = next(iter(pi.markers.shown))
    item = pi.markers.shown[th]
    ring = xp.instances[item.ring][1]
    column = xp.instances[item.column][1]
    top_dy = column[1] - ring[1]
    assert ring[0] - column[0] == pytest.approx(lean_e, abs=1e-3)  # local x is east
    assert ring[2] == pytest.approx(column[2], abs=1.0)
    assert column[3] == pytest.approx(math.degrees(math.atan2(-lean_e, top_dy)), abs=0.1)
    assert column[4] == pytest.approx(270.0, abs=1.0)  # the bottom swings upwind, to the west


# --- which wind carries the sky ---------------------------------------------------

def shear_layers(data):
    """9 kt below 1000 m MSL, then more with height: 15 kt from 3000 m up, all from the west."""
    data["sim/weather/aircraft/wind_altitude_msl_m"] = [1000.0, 3000.0] + [-1.0] * 11
    data["sim/weather/aircraft/wind_speed_kts"] = [9.0, 15.0] + [-1.0] * 11
    data["sim/weather/aircraft/wind_direction_degt"] = [270.0, 270.0] + [0.0] * 11


def test_by_default_the_wind_at_the_glider_carries_the_sky_whatever_the_layers(plugin):
    pi, xp, data = plugin
    assert dataref(xp, "wind_at_clouds") == 0
    shear_layers(data)
    data["sim/weather/aircraft/wind_now_x_msc"] = 5.0
    data["sim/weather/aircraft/wind_now_z_msc"] = -2.0  # toward the north
    frame(pi, data)
    assert dataref(xp, "wind/e_ms") == 5.0 and dataref(xp, "wind/n_ms") == 2.0


def test_the_wind_at_the_clouds_comes_from_the_layers_at_their_level(plugin):
    pi, xp, data = plugin
    shear_layers(data)
    data["sim/weather/aircraft/wind_now_x_msc"] = 1.0  # at the glider: it must not matter
    dataref(xp, "wind_at_clouds", 1)
    pi.next_lean = 0.0
    frame(pi, data)
    # With no clouds yet, where they would be: 1116 m of ground and Allen's top of a 2000 m zi.
    expected = 9.0 + (1116.0 + 2000.0 / 1.1 - 1000.0) / 2000.0 * 6.0
    frame(pi, data)
    assert dataref(xp, "wind/e_ms") == pytest.approx(expected * 0.514444, abs=1e-3)
    assert dataref(xp, "wind/n_ms") == pytest.approx(0.0, abs=1e-6)
    # With clouds, at their level, wherever the glider is.
    pi.injector.heights.level_m = 2000.0
    pi.next_lean = 0.0
    data["sim/flightmodel/position/elevation"] += 500.0
    frame(pi, data)
    frame(pi, data)
    assert dataref(xp, "wind/e_ms") == pytest.approx(12.0 * 0.514444, abs=1e-3)


def test_the_height_of_a_cloud_reads_the_wind_that_carries_the_sky(plugin):
    pi, xp, data = plugin
    shear_layers(data)
    data["sim/weather/aircraft/wind_now_x_msc"] = 0.0  # calm at the glider
    dataref(xp, "wind_at_clouds", 1)
    pi.next_lean = 0.0
    lon0 = data["sim/flightmodel/position/longitude"]
    # A hill to the east: only a cloud that drifts will be raised for it, and only under
    # the wind at the clouds, since the glider's is calm.
    start, end = lon0 + 0.10, lon0 + 0.15
    xp.ground = lambda lat, lon: 4000.0 if start < lon < end else 1116.0
    fill_sky(pi, data)
    upwind = [e[1] for th, e in pi.clouds.instances.items() if th.lon < start - 0.01]
    assert any(b == pytest.approx(4300.0) for b in upwind)


def test_with_no_shear_the_offset_is_the_same_with_the_setting_on_or_off(plugin):
    pi, xp, data = plugin
    wind = 15.0 * 0.514444  # the layers of the fixture: 15 kt from 270 at every height
    data["sim/weather/aircraft/wind_now_x_msc"] = wind
    pi.next_lean = 0.0
    frame(pi, data)
    off = (dataref(xp, "wind/e_ms"), dataref(xp, "wind/n_ms"))
    dataref(xp, "wind_at_clouds", 1)
    pi.next_lean = 0.0
    frame(pi, data)
    frame(pi, data)
    on = (dataref(xp, "wind/e_ms"), dataref(xp, "wind/n_ms"))
    assert on == pytest.approx(off, abs=1e-4)


def test_no_layers_in_use_leaves_the_wind_at_the_glider(plugin):
    pi, xp, data = plugin
    data["sim/weather/aircraft/wind_speed_kts"] = [-1.0] * 13
    data["sim/weather/aircraft/wind_now_x_msc"] = 3.0
    dataref(xp, "wind_at_clouds", 1)
    pi.next_lean = 0.0
    frame(pi, data)
    frame(pi, data)
    assert dataref(xp, "wind/e_ms") == 3.0


def test_the_setting_has_a_switch_in_the_menu_saved_and_taken_back_at_once(plugin):
    pi, xp, data = plugin
    shear_layers(data)
    data["sim/weather/aircraft/wind_now_x_msc"] = 1.0
    handler, attr = xp.handlers["xp_gliding/wind/clouds/toggle"]
    handler("xp_gliding/wind/clouds/toggle", xp.CommandBegin, attr)
    assert pi.settings.wind_at_clouds
    assert saved(pi)["wind_at_clouds"] is True
    assert "Sky moves with the wind at the clouds" in checked(xp, "xp-gliding")
    pi.next_lean = 0.0
    frame(pi, data)
    frame(pi, data)
    assert dataref(xp, "wind/e_ms") != 1.0
    handler("xp_gliding/wind/clouds/toggle", xp.CommandBegin, attr)
    frame(pi, data)
    frame(pi, data)
    assert dataref(xp, "wind/e_ms") == 1.0


def test_a_new_aircraft_forgets_the_wind_at_the_clouds(plugin):
    pi, xp, data = plugin
    dataref(xp, "wind_at_clouds", 1)
    pi.next_lean = 0.0
    frame(pi, data)
    assert pi.injector.sky_wind is not None
    pi.load_aircraft()
    assert pi.injector.sky_wind is None


# --- the settings menu ------------------------------------------------------------

def choose(xp, title, label):
    menu = xp.menus[title]
    refcon = next(refcon for name, refcon in menu["items"] if name == label)
    menu["handler"](title, refcon)


def checked(xp, title):
    menu = xp.menus[title]
    return [menu["items"][k][0] for k in sorted(menu["checked"])]


def saved(pi):
    with open(pi.config_path, encoding="utf-8") as f:
        return json.load(f)


def test_the_menu_shows_the_current_choices(plugin):
    pi, xp, data = plugin
    assert checked(xp, "Sky") == ["Narrow thermals, as the paper"]
    assert checked(xp, "Strength of the day (w*)") == ["3 m/s"]
    assert checked(xp, "Depth of the thermal layer (zi)") == ["2000 m"]
    assert checked(xp, "Seed of the sky") == ["1"]


def test_every_sky_in_the_menu_exists_and_every_sky_is_in_the_menu(plugin):
    pi, xp, data = plugin
    values = {pi.choices[refcon][1] for _, refcon in xp.menus["Sky"]["items"]}
    assert values == set(importlib.import_module("xp_gliding.engine.field").SKY_NAMES)


def test_a_menu_item_carries_a_plain_number_and_not_an_object_made_for_the_call(plugin):
    # A tuple made in the loop did not come back intact in X-Plane, which stopped the plugin.
    pi, xp, data = plugin
    for title in ("Sky", "Strength of the day (w*)", "Depth of the thermal layer (zi)", "Seed of the sky"):
        assert all(type(refcon) is int for _, refcon in xp.menus[title]["items"])


def test_a_bad_menu_choice_is_logged_and_does_not_stop_the_plugin(plugin, capsys):
    pi, xp, data = plugin
    sky = pi.settings.sky
    pi.on_choice("Sky", 9999)
    pi.on_choice("Sky", ("not", "a place"))
    assert pi.settings.sky == sky
    assert "error in a menu choice" in capsys.readouterr().out
    frame(pi, data)
    assert not pi.failed


def test_choosing_a_sky_changes_it_and_saves_it(plugin):
    pi, xp, data = plugin
    frame(pi, data)
    choose(xp, "Sky", "Wide thermals under the clouds (x2)")
    assert pi.settings.sky == "wide_carriers"
    assert checked(xp, "Sky") == ["Wide thermals under the clouds (x2)"]
    assert saved(pi)["sky"] == "wide_carriers"
    old = pi.injector.field
    frame(pi, data)  # at once, not up to a second later
    assert pi.injector.field is not old
    assert pi.injector.field.config.sky is importlib.import_module("xp_gliding.engine.field").SKIES["wide_carriers"]


def test_choosing_a_new_day_keeps_the_numbers_as_numbers(plugin):
    pi, xp, data = plugin
    choose(xp, "Strength of the day (w*)", "4 m/s")
    choose(xp, "Seed of the sky", "3")
    assert pi.settings.wstar_ms == 4.0 and pi.settings.seed == 3 and isinstance(pi.settings.seed, int)
    assert saved(pi)["wstar_ms"] == 4.0 and saved(pi)["seed"] == 3


def test_a_new_depth_starts_the_clouds_over_at_their_new_base(plugin):
    pi, xp, data = plugin
    fill_sky(pi, data)
    assert pi.clouds.instances
    choose(xp, "Depth of the thermal layer (zi)", "1500 m")
    assert pi.settings.zi_m == 1500.0
    assert not pi.clouds.instances


def test_a_switch_is_saved_too(plugin):
    pi, xp, data = plugin
    handler, attr = xp.handlers["xp_gliding/hud/toggle"]
    handler("xp_gliding/hud/toggle", xp.CommandBegin, attr)
    assert saved(pi)["hud_enabled"] is False


def test_a_value_outside_the_menu_checks_nothing_and_stays(plugin):
    pi, xp, data = plugin
    dataref(xp, "zi_m", 1800.0)
    frame(pi, data)
    assert checked(xp, "Depth of the thermal layer (zi)") == []
    assert pi.settings.zi_m == 1800.0


def test_a_config_that_cannot_be_written_only_says_so(plugin, capsys):
    pi, xp, data = plugin
    pi.config_path = str(pi.config_path) + "/not/a/folder/config.json"
    choose(xp, "Seed of the sky", "2")
    assert pi.settings.seed == 2
    assert "could not write" in capsys.readouterr().out


# --- the wind on the HUD ----------------------------------------------------------

@pytest.mark.parametrize("wind_x, wind_z, psi, right, up", [
    (10.0, 0.0, 0.0, 1.0, 0.0),  # blowing toward the east, nose north: to the right
    (10.0, 0.0, 90.0, 0.0, 1.0),  # nose east: a tailwind, up
    (10.0, 0.0, 270.0, 0.0, -1.0),  # nose west: a headwind, down
    (0.0, -10.0, 0.0, 0.0, 1.0),  # toward the north (z is south), nose north: up
    (0.0, 10.0, 90.0, 1.0, 0.0),  # toward the south, nose east: to the right
])
def test_the_wind_arrow_points_where_the_wind_goes_from_the_nose(plugin, wind_x, wind_z, psi, right, up):
    hud = importlib.import_module("xp_gliding.adapter.hud")
    dx, dy = hud.wind_arrow(wind_x, wind_z, psi)
    assert dx == pytest.approx(right * hud.WIND_RADIUS, abs=1e-6)
    assert dy == pytest.approx(up * hud.WIND_RADIUS, abs=1e-6)


def hud_samples(pi, xp, data, count=30):
    hud = pi.hud
    hud._load_drawing = lambda: setattr(hud, "window", "window")
    xp.setWindowIsVisible = lambda window, visible: None
    xp.destroyWindow = lambda window: None
    for _ in range(count):
        data["sim/time/total_running_time_sec"] += 0.1
        hud.tick()


def test_the_hud_gives_the_wind_in_knots_and_says_when_it_is_calm(plugin):
    pi, xp, data = plugin
    hud_samples(pi, xp, data)
    assert pi.hud._wind_text == "WIND calm" and pi.hud._wind_arrow is None
    data["sim/weather/aircraft/wind_now_x_msc"] = 7.72
    hud_samples(pi, xp, data)
    assert pi.hud._wind_text == "WIND 15 kt" and pi.hud._wind_arrow is not None


# --- the lift ends with its cloud -----------------------------------------------------------------


def hill_east(xp, data, height=3000.0):
    """A long hill beginning 0.05 deg east of the glider, whose ground is 1116 m."""
    edge = data["sim/flightmodel/position/longitude"] + 0.05
    xp.ground = lambda lat, lon: height if lon > edge else 1116.0
    return edge


def test_each_thermal_gets_the_floor_that_puts_its_cloud_at_the_skys_share_of_zi(plugin):
    pi, xp, data = plugin
    edge = hill_east(xp, data)
    frame(pi, data)
    heights, field = pi.injector.heights, pi.injector.field
    zi, base_zzi = pi.settings.zi_m, field.config.sky.cloud_base_zzi
    level = 1116.0 + base_zzi * zi
    assert heights.level_m == pytest.approx(level)
    params = pi.clouds.planner.params
    raised = 0
    for th in field.thermals():
        assert th.floor_m is not None
        if carries_cloud(th, params) and th.lon > edge + 0.01:
            assert th.floor_m == pytest.approx(3300.0 - base_zzi * zi)
            raised += 1
        elif not carries_cloud(th, params):
            assert th.floor_m == pytest.approx(1116.0)
    assert raised
    assert dataref(xp, "nearest/floor_m") >= 1116.0


def test_the_lift_at_a_drawn_cloud_ends_by_the_height_that_cloud_was_drawn_at(plugin):
    pi, xp, data = plugin
    edge = hill_east(xp, data)
    fill_sky(pi, data)
    zi = pi.settings.zi_m
    base_zzi = pi.injector.field.config.sky.cloud_base_zzi
    by_key = {(th.lat, th.lon, th.birth): th for th in pi.injector.field.thermals()}
    both = [(c, by_key[(c.lat, c.lon, c.birth)]) for c in pi.clouds.instances
            if (c.lat, c.lon, c.birth) in by_key]
    assert both and any(c.lon > edge + 0.01 for c, _ in both)
    for cloud, th in both:
        assert th.floor_m == pytest.approx(pi.clouds.instances[cloud][1] - base_zzi * zi)


def test_on_flat_ground_the_force_is_what_it_was_with_no_floors(plugin):
    pi, xp, data = plugin
    pi.injector.slow_update(pi.io.read_state(pi.state))
    th, _ = pi.injector.field.nearest(0.0, 0.0, pi.state.sky_t_s, 5000.0)
    data["sim/flightmodel/position/latitude"], data["sim/flightmodel/position/longitude"] = th.lat, th.lon
    frame(pi, data)
    with_floors = dataref(xp, "lift_centre_ms")
    assert dataref(xp, "nearest/floor_m") == pytest.approx(1116.0, abs=0.01)
    pi.injector.heights = None
    frame(pi, data)
    assert dataref(xp, "lift_centre_ms") == pytest.approx(with_floors, abs=1e-6)


def glider_over_raised_thermal(pi, xp, data):
    """Over a thermal with a raised cloud, on the hill: (thermal, ground there)."""
    hill_east(xp, data)
    data["sim/weather/aircraft/wind_now_x_msc"] = 0.0
    frame(pi, data)
    params = pi.clouds.planner.params
    t = pi.state.sky_t_s
    th = next(th for th in pi.injector.field.alive(t)
              if carries_cloud(th, params) and th.floor_m > 1117.0 and th.envelope(t)[0] == 1.0)
    data["sim/flightmodel/position/latitude"], data["sim/flightmodel/position/longitude"] = th.lat, th.lon
    return th, 3000.0


def test_over_a_hill_a_climb_ends_at_its_cloud_and_not_above_the_ground_under_it(plugin):
    pi, xp, data = plugin
    th, ground = glider_over_raised_thermal(pi, xp, data)
    zi = pi.settings.zi_m
    above = th.floor_m + zi / 1.1 + 50.0  # over the top of the lift
    data["sim/flightmodel/position/elevation"], data["sim/flightmodel/position/y_agl"] = above, above - ground
    frame(pi, data)
    assert dataref(xp, "lift_centre_ms") < 0.0
    # Under it, close over this hill, it climbs.
    low = ground + 50.0
    data["sim/flightmodel/position/elevation"], data["sim/flightmodel/position/y_agl"] = low, low - ground
    frame(pi, data)
    assert dataref(xp, "lift_centre_ms") > 0.3


def test_a_jump_is_a_new_sky_with_a_new_level_and_new_floors(plugin):
    pi, xp, data = plugin
    clouds_tick(pi, data)
    heights = pi.injector.heights
    level, resets = heights.level_m, heights.resets
    assert level == pytest.approx(1116.0 + pi.injector.field.config.sky.cloud_base_zzi * pi.settings.zi_m)
    # A small step changes nothing, whatever the ground does.
    data["sim/flightmodel/position/longitude"] += 0.01
    data["sim/flightmodel/position/y_agl"] -= 300.0
    frame(pi, data)
    pi.next_slow = 0.0
    frame(pi, data)
    assert heights.level_m == level and heights.resets == resets
    # Moved on the map, over other ground, same aircraft: no message from X-Plane says so.
    old = set(xp.instances)
    assert old
    data["sim/flightmodel/position/longitude"] += 0.2
    pi.next_slow = 0.0
    frame(pi, data)
    assert heights.resets == resets + 1
    assert heights.level_m == pytest.approx(level + 300.0)
    assert all(th.floor_m == pytest.approx(1416.0) for th in pi.injector.field.thermals()
               if not carries_cloud(th, pi.clouds.planner.params))
    # The clouds go with it, or they would stand at the old level over the new lift.
    clouds_tick(pi, data)
    assert not old & set(xp.instances)


def test_the_clock_jumping_is_a_new_sky_too(plugin):
    pi, xp, data = plugin
    frame(pi, data)
    heights = pi.injector.heights
    resets = heights.resets
    pi.next_slow = 0.0
    frame(pi, data)
    assert heights.resets == resets
    data["sim/time/zulu_time_sec"] += 3600.0
    pi.next_slow = 0.0
    frame(pi, data)
    assert heights.resets == resets + 1


def test_a_new_zi_is_a_new_sky_even_written_by_a_tool(plugin):
    pi, xp, data = plugin
    frame(pi, data)
    field = pi.injector.field
    base_zzi = field.config.sky.cloud_base_zzi
    dataref(xp, "zi_m", 1500.0)
    pi.next_slow = 0.0
    frame(pi, data)
    assert pi.injector.field is not field
    assert pi.injector.heights.level_m == pytest.approx(1116.0 + base_zzi * 1500.0)


def test_the_top_on_the_hud_is_the_distance_up_to_the_clouds(plugin):
    pi, xp, data = plugin
    zi, agl = pi.settings.zi_m, data["sim/flightmodel/position/y_agl"]
    pi.next_slow = 0.0
    frame(pi, data)
    base_zzi = pi.injector.field.config.sky.cloud_base_zzi
    # With no cloud drawn, the level.
    assert pi.clouds.status.nearest_base_m == -1.0
    hud_samples(pi, xp, data, count=3)
    assert pi.hud._top_text == f"TOP {1116.0 + base_zzi * zi - 1916.0:+.0f} m"
    # With one, how far its base is from the glider: the ground under the glider does not count.
    pi.clouds.status.nearest_base_m = 3000.0
    pi.next_slow = 0.0
    frame(pi, data)
    hud_samples(pi, xp, data, count=3)
    assert pi.hud._top_text == "TOP +1084 m"
    data["sim/flightmodel/position/y_agl"] = agl - 500.0  # climbing into a hill's cloud, over the hill
    hud_samples(pi, xp, data, count=3)
    assert pi.hud._top_text == "TOP +1084 m"
    data["sim/flightmodel/position/elevation"] += 1.0
    hud_samples(pi, xp, data, count=3)
    assert pi.hud._top_text == "TOP +1083 m"


def test_the_top_on_the_hud_with_nothing_known_is_the_forecast(plugin):
    pi, xp, data = plugin
    pi.hud.set_top(-1.0, None)
    hud_samples(pi, xp, data, count=3)
    assert pi.hud.top_msl_m is None
    base_zzi = sky_named(pi.settings.sky).cloud_base_zzi
    assert pi.hud._top_text == f"TOP {pi.settings.zi_m * base_zzi - 800.0:+.0f} m"


def test_each_column_stands_at_its_own_thermals_cloud(plugin):
    pi, xp, data = plugin
    hill_east(xp, data)
    dataref(xp, "markers_enabled", 1)
    data["sim/flightmodel/position/longitude"] += 0.05
    frame(pi, data)
    # Some of the markers raised, some not, to see the difference.
    markers_tick(pi, data)
    assert pi.markers.shown
    zi = pi.settings.zi_m
    base_zzi = pi.injector.field.config.sky.cloud_base_zzi
    floors = [1116.0, 1500.0]
    for k, th in enumerate(pi.markers.shown):
        th.floor_m = floors[k % 2]
    markers_tick(pi, data)
    msl = data["sim/flightmodel/position/elevation"]
    tops = set()
    for item in pi.markers.shown.values():
        ring = xp.instances[item.ring][1]
        column = xp.instances[item.column][1]
        assert column[1] - ring[1] == pytest.approx(item.thermal.floor_m + base_zzi * zi - msl)
        tops.add(round(column[1], 3))
    assert len(tops) == 2


def test_each_column_leans_by_its_own_height(plugin):
    pi, xp, data = plugin
    dataref(xp, "markers_enabled", 1)
    dataref(xp, "lean_enabled", 1)
    pi.next_lean = 0.0
    frame(pi, data)
    markers_tick(pi, data)
    assert len(pi.markers.shown) >= 2
    a, b = list(pi.markers.shown)[:2]
    a.floor_m, b.floor_m = 1116.0, 1300.0
    markers_tick(pi, data)
    lean = math.hypot(dataref(xp, "lean/e_m"), dataref(xp, "lean/n_m"))
    assert lean > 0.0
    for th in (a, b):
        item = pi.markers.shown[th]
        ring, column = xp.instances[item.ring][1], xp.instances[item.column][1]
        assert column[3] == pytest.approx(math.degrees(math.atan2(lean, column[1] - ring[1])), abs=0.01)
    assert xp.instances[pi.markers.shown[a].column][1][3] != xp.instances[pi.markers.shown[b].column][1][3]


def test_the_floors_read_the_ground_only_when_a_thermal_loads(plugin):
    pi, xp, data = plugin
    reads = []
    hill = xp.ground
    xp.ground = lambda lat, lon: reads.append(1) or hill(lat, lon)
    pi.clouds.heights.ground_m = pi.clouds.sky.ground_m
    frame(pi, data)
    assert reads
    count = len(reads)
    pi.next_clouds = pi.next_markers = float("inf")
    for _ in range(3):
        frame(pi, data)
    assert len(reads) == count
