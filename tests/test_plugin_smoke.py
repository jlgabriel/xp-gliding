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
    clouds_tick(pi, data)
    assert 0 < len(xp.instances) <= 2 * pi.clouds.planner.params.max_new
    assert dataref(xp, "clouds/tiles_missing") > 0
    fill_sky(pi, data)
    count = dataref(xp, "clouds/count")
    assert count > 40 and len(xp.instances) == count == dataref(xp, "clouds/created")
    assert all("xp_gliding/assets/clouds/cumulus.obj" in p for p in xp.objects.values())
    assert set(xp.instances) == xp.shifted
    assert dataref(xp, "clouds/nearest_m") >= 0.0


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
    for _, position, values, drefs in xp.instances.values():
        assert drefs == wanted
        assert position[1] == pytest.approx(base - 1000.0)
        assert values[0] > 0.0 and SCALE_RANGE[0] <= values[1] <= SCALE_RANGE[1]


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
    clouds_tick(pi, data)
    assert xp.instances
    pi.XPluginReceiveMessage(0, xp.MSG_PLANE_LOADED, 0)
    assert not xp.instances
    clouds_tick(pi, data)
    assert xp.instances
    created = dataref(xp, "clouds/created")
    old = set(xp.instances)
    data["sim/time/zulu_time_sec"] += 3600.0
    clouds_tick(pi, data)
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
    clouds_tick(pi, data)
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
    values = {refcon[1] for _, refcon in xp.menus["Sky"]["items"]}
    assert values == set(importlib.import_module("xp_gliding.engine.field").SKY_NAMES)


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
