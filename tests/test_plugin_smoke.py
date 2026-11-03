"""Smoke test of the XPPython3 plugin with a minimal fake `xp` module.

Not a simulation of X-Plane: it checks that the plugin starts, registers its
datarefs and commands, adds its force to the `*_plug_acf` datarefs once per
frame, respects pause, holds the native thermal setting at 0 and restores it.
"""

import importlib
import sys
import types

import pytest

DATA = {
    "sim/flightmodel/position/latitude": 32.6875,
    "sim/flightmodel/position/longitude": -103.217,
    "sim/flightmodel/position/y_agl": 800.0,
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
    "sim/aircraft/engine/acf_num_engines": 0,
}


def make_fake_xp(tmp_path, data):
    xp = types.ModuleType("xp")
    xp.accessors = {}
    xp.handlers = {}
    for name in ("Type_Int", "Type_Float", "FlightLoop_Phase_BeforeFlightModel", "CommandBegin",
                 "Menu_Checked", "Menu_Unchecked", "MSG_PLANE_LOADED"):
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
    return xp


@pytest.fixture
def plugin(tmp_path, monkeypatch):
    data = dict(DATA)
    xp = make_fake_xp(tmp_path, data)
    monkeypatch.setitem(sys.modules, "xp", xp)
    for mod in ("xp_gliding.adapter.xpio", "xp_gliding.adapter.plugin"):
        sys.modules.pop(mod, None)
    plugin_mod = importlib.import_module("xp_gliding.adapter.plugin")
    pi = plugin_mod.PythonInterface()
    pi.XPluginStart()
    pi.XPluginEnable()
    yield pi, xp, data
    pi.XPluginDisable()
    pi.XPluginStop()
    for mod in ("xp_gliding.adapter.xpio", "xp_gliding.adapter.plugin"):
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
