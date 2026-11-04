"""Smoke test of the XPPython3 plugin with a minimal fake `xp` module.

Not a simulation of X-Plane: it checks that the plugin starts, registers its
datarefs and commands, adds its force to the `*_plug_acf` datarefs once per
frame, respects pause, holds the native thermal setting at 0 and restores it,
and creates, moves and destroys the training markers' instances.
"""

import importlib
import itertools
import sys
import types

import pytest

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
    xp.appendMenuItem = lambda menu, name, refcon: 0
    xp.createMenu = lambda *a: "menu"
    xp.appendMenuItemWithCommand = lambda menu, name, cmd: 0
    xp.checkMenuItem = lambda menu, index, check: None
    xp.destroyMenu = lambda menu: None
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
        xp.instances[ref] = [obj, None]
        return ref

    def world_to_local(lat, lon, alt=0.0):
        xp.calls["worldToLocal"] += 1
        return (lon + 103.0) * 90000.0, alt - 1000.0, -(lat - 32.0) * 110000.0

    def set_position(instance, position, data=None):
        assert len(position) == 6
        xp.instances[instance][1] = tuple(position)

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
    for _, position in xp.instances.values():
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
