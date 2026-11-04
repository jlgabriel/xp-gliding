"""Smoke test of the XPPython3 plugin with a minimal fake `xp` module.

Not a simulation of X-Plane: it checks that the plugin starts, registers its
datarefs and commands, adds its force to the `*_plug_acf` datarefs once per
frame, respects pause, holds the native thermal setting at 0 and restores it,
and creates, moves and destroys the instances of the training markers and clouds.
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
    near = [(v[2][0], th) for th, (inst, _) in pi.clouds.instances.items() for v in [xp.instances[inst]]]
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
