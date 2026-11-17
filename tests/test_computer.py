"""The Flight Computer (adapter/computer.py) with a fake `xp` that has browser windows.

Not a simulation of X-Plane's browser: it checks the life cycle the stage 0 lab found (the close
box only hides, so a closed window is destroyed; functions before the URL; the keyboard handed
back after a click; a page that does not answer reloaded once), the Instrument submenu, that the
two instruments share one set of instruments, and that a failure stops only the Flight Computer.
"""

import importlib
import json
import sys
import time

import pytest

from test_plugin_smoke import ADAPTER_MODULES, DATA, OWN_STYLES, dataref, make_fake_xp

ASK21 = "Aircraft/Laminar Research/Schleicher ASK 21/ASK21.acf"


def add_browser(xp):
    """Browser windows as X-Plane 12.4.4 and XPPython3 4.8.0 have them, recorded."""
    xp.WindowContentTypeBrowser = "browser"
    xp.WindowDecorationRoundRectangle = "round"
    xp.WindowLayerFloatingWindows = "floating"
    xp.windows = {}  # id -> dict
    xp.calls_log = []
    counter = iter(range(1, 1000))

    def create(left, top, right, bottom, visible=0, **kw):
        wid = next(counter)
        xp.windows[wid] = {"geometry": [left, top, right, bottom], "visible": visible, "kw": kw,
                           "functions": [], "url": None, "refreshed": 0, "popped": 0}
        xp.calls_log.append(("create", wid))
        return wid

    def add_function(wid, name, function, refCon=None):
        w = xp.windows[wid]
        assert w["url"] is None, "a function added after the URL is ignored by X-Plane"
        w["functions"].append((name, function))

    def set_url(wid, url):
        xp.windows[wid]["url"] = url

    def destroy(wid):
        xp.calls_log.append(("destroy", wid))
        del xp.windows[wid]

    xp.createWindowEx = create
    xp.windowAddBrowserFunction = add_function
    xp.windowSetURL = set_url
    xp.windowRefresh = lambda wid, ignoreCache=0: xp.windows[wid].__setitem__(
        "refreshed", xp.windows[wid]["refreshed"] + 1)
    xp.destroyWindow = destroy
    xp.setWindowTitle = lambda wid, title: xp.windows[wid].__setitem__("title", title)
    xp.setWindowResizingLimits = lambda wid, *limits: None
    xp.getWindowIsVisible = lambda wid: xp.windows[wid]["visible"]
    xp.setWindowIsVisible = lambda wid, visible: wid in xp.windows and xp.windows[wid].__setitem__("visible", visible)
    xp.getWindowGeometry = lambda wid: tuple(xp.windows[wid]["geometry"])
    xp.windowIsPoppedOut = lambda wid: xp.windows[wid]["popped"]
    xp.getScreenBoundsGlobal = lambda: (0, 1440, 2560, 0)
    xp.takeKeyboardFocus = lambda wid: xp.calls_log.append(("focus", wid))


def start(tmp_path, monkeypatch, browser=True, config=None):
    data = dict(DATA)
    data["acf_path"] = ASK21
    data["sim/flightmodel/position/local_vx"] = 0.0
    data["sim/flightmodel/position/local_vz"] = -25.0
    xp = make_fake_xp(tmp_path, data)
    if browser:
        add_browser(xp)
    if config is not None:
        folder = tmp_path / "Output" / "xp-gliding"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "config.json").write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setitem(sys.modules, "xp", xp)
    for mod in ADAPTER_MODULES:
        sys.modules.pop(mod, None)
    plugin_mod = importlib.import_module("xp_gliding.adapter.plugin")
    plugin_mod.OWN_STYLES = str(tmp_path / OWN_STYLES)
    pi = plugin_mod.PythonInterface()
    pi.XPluginStart()
    pi.XPluginEnable()
    pi.hud._load_drawing = lambda: setattr(pi.hud, "window", "hud window")
    pi.hud._drop_drawing = lambda: setattr(pi.hud, "window", None)
    return pi, xp, data


@pytest.fixture
def plugin(tmp_path, monkeypatch):
    pi, xp, data = start(tmp_path, monkeypatch)
    yield pi, xp, data
    pi.XPluginDisable()
    pi.XPluginStop()
    assert not xp.windows  # no window left behind


def choose(xp, label):
    menu = xp.menus["Instrument"]
    refcon = next(refcon for name, refcon in menu["items"] if name == label)
    menu["handler"]("Instrument", refcon)


def ticked(xp):
    menu = xp.menus["Instrument"]
    return [menu["items"][k][0] for k in sorted(menu["checked"])]


def saved(pi):
    with open(pi.config_path, encoding="utf-8") as f:
        return json.load(f)


def the_window(xp):
    (wid, window), = xp.windows.items()
    return wid, window


def call(window, name, arg=None):
    function = dict(window["functions"])[name]
    return function(None, json.dumps(arg if arg is not None else {}), None)


def tick(pi, seconds=0.1):
    """A tick of the Flight Computer's loop, `seconds` after the last: on the clock the computer
    itself uses (time.monotonic), moved on by each test's own offset so that tests need not wait."""
    pi.test_later = getattr(pi, "test_later", 0.0) + seconds
    pi.computer.tick(time.monotonic() + pi.test_later)


def test_the_instrument_submenu_keeps_at_most_one_on_and_is_saved(plugin):
    pi, xp, data = plugin
    assert [name for name, _ in xp.menus["Instrument"]["items"]] == ["Soaring HUD", "Flight Computer", "None"]
    assert ticked(xp) == ["Soaring HUD"]  # a fresh install shows the HUD, as before
    choose(xp, "Flight Computer")
    assert (pi.settings.hud_enabled, pi.settings.computer_enabled) == (False, True)
    assert ticked(xp) == ["Flight Computer"]
    assert saved(pi)["computer_enabled"] is True and saved(pi)["hud_enabled"] is False
    choose(xp, "None")
    assert (pi.settings.hud_enabled, pi.settings.computer_enabled) == (False, False) and ticked(xp) == ["None"]
    choose(xp, "Soaring HUD")
    assert (pi.settings.hud_enabled, pi.settings.computer_enabled) == (True, False)


def test_each_instruments_command_turns_the_other_off(plugin):
    pi, xp, data = plugin
    for cmd in ("xp_gliding/computer/toggle", "xp_gliding/hud/toggle"):
        assert cmd not in dict(xp.menus["XP-Gliding"]["items"]).values()  # the submenu, not items
    handler, name = xp.handlers["xp_gliding/computer/toggle"]
    handler("xp_gliding/computer/toggle", xp.CommandBegin, name)
    assert (pi.settings.hud_enabled, pi.settings.computer_enabled) == (False, True)
    handler("xp_gliding/computer/toggle", xp.CommandBegin, name)
    assert (pi.settings.hud_enabled, pi.settings.computer_enabled) == (False, False)
    handler, name = xp.handlers["xp_gliding/hud/toggle"]
    handler("xp_gliding/hud/toggle", xp.CommandBegin, name)
    assert (pi.settings.hud_enabled, pi.settings.computer_enabled) == (True, False)
    assert ticked(xp) == ["Soaring HUD"]


def test_both_on_from_the_file_shows_both_and_ticks_neither(tmp_path, monkeypatch):
    pi, xp, data = start(tmp_path, monkeypatch, config={"hud_enabled": True, "computer_enabled": True})
    tick(pi)
    pi.hud.tick()
    assert len(xp.windows) == 1 and pi.hud.window == "hud window"
    assert ticked(xp) == []
    pi.XPluginDisable()
    pi.XPluginStop()


def test_without_browser_windows_the_entry_is_greyed_and_the_hud_stands_in(tmp_path, monkeypatch):
    pi, xp, data = start(tmp_path, monkeypatch, browser=False,
                         config={"hud_enabled": False, "computer_enabled": True})
    assert not pi.computer.available and dataref(xp, "computer/available") == 0
    assert 1 in xp.menus["Instrument"]["disabled"]
    assert (pi.settings.hud_enabled, pi.settings.computer_enabled) == (True, False)
    choose(xp, "Flight Computer")
    assert (pi.settings.hud_enabled, pi.settings.computer_enabled) == (True, False)
    handler, name = xp.handlers["xp_gliding/computer/toggle"]
    handler("xp_gliding/computer/toggle", xp.CommandBegin, name)
    assert not pi.settings.computer_enabled
    pi.computer.tick(1.0)
    pi.XPluginDisable()
    pi.XPluginStop()


def test_the_window_is_a_browser_with_its_functions_before_its_page(plugin):
    pi, xp, data = plugin
    choose(xp, "Flight Computer")
    tick(pi)
    wid, window = the_window(xp)
    assert window["kw"]["contentType"] == "browser" and window["visible"] == 1
    assert [name for name, _ in window["functions"]] == ["xpg_state", "xpg_do"]
    assert window["url"].startswith("file:///") and window["url"].endswith("/xp_gliding/web/index.html")
    assert window["title"] == "XP-Gliding Flight Computer"
    assert dataref(xp, "computer/window") == 1


def test_the_hud_is_hidden_and_its_instruments_run_for_the_computer(plugin):
    pi, xp, data = plugin
    choose(xp, "Flight Computer")
    for _ in range(30):
        data["sim/time/total_running_time_sec"] += 0.1
        data["sim/flightmodel/position/elevation"] -= 0.1
        tick(pi)
        pi.hud.tick()
    assert pi.hud.window is None  # never made
    assert dataref(xp, "hud/te_ms") == pytest.approx(-1.0, abs=0.01)
    wid, window = the_window(xp)
    state = json.loads(call(window, "xpg_state"))
    # The same numbers as the HUD's datarefs: one set of instruments.
    assert state["te_ms"] == pytest.approx(dataref(xp, "hud/te_ms"), abs=0.01)
    assert state["avg_ms"] == pytest.approx(dataref(xp, "hud/average_ms"), abs=0.01)
    assert state["valid"] is True and state["units"] == "metric" and state["poll_hz"] == 5
    assert state["track_deg"] == pytest.approx(0.0) and state["gs_ms"] == pytest.approx(25.0)
    assert state["ias_ms"] == pytest.approx(48.6 * 0.514444, abs=0.01)
    assert state["top_m"] is not None
    assert dataref(xp, "computer/requests") == 1
    # Back to the HUD: the window goes, the HUD shows again.
    choose(xp, "Soaring HUD")
    tick(pi)
    pi.hud.tick()
    assert not xp.windows and pi.hud.window == "hud window"


def test_top_is_left_out_without_our_thermals(plugin):
    pi, xp, data = plugin
    choose(xp, "Flight Computer")
    pi.settings.thermals_enabled = False
    pi.hud.top_m = 500.0
    tick(pi)
    tick(pi)
    wid, window = the_window(xp)
    assert json.loads(call(window, "xpg_state"))["top_m"] is None


def test_the_close_box_closes_the_flight_computer_and_keeps_its_place(plugin):
    pi, xp, data = plugin
    choose(xp, "Flight Computer")
    tick(pi)
    wid, window = the_window(xp)
    window["geometry"] = [300, 1200, 900, 700]  # the pilot moved and resized it
    window["visible"] = 0  # then clicked its close box, which only hides it
    for _ in range(5):  # looked at twice a second
        tick(pi)
    assert not xp.windows and not pi.settings.computer_enabled
    assert ticked(xp) == ["None"]
    assert saved(pi)["computer_enabled"] is False
    assert saved(pi)["computer_window"] == [300, 1200, 900, 700]
    choose(xp, "Flight Computer")
    tick(pi)
    wid, window = the_window(xp)
    assert window["geometry"] == [300, 1200, 900, 700]  # where it was


def test_a_place_off_the_screen_is_not_used(plugin):
    pi, xp, data = plugin
    pi.settings.computer_window = [5000, 1200, 5400, 800]  # a monitor that is gone
    choose(xp, "Flight Computer")
    tick(pi)
    wid, window = the_window(xp)
    assert window["geometry"] == [120, 1280, 600, 860]


def test_a_moved_window_is_saved_once_it_stays_put(plugin):
    pi, xp, data = plugin
    choose(xp, "Flight Computer")
    tick(pi)
    wid, window = the_window(xp)
    for x in range(100, 200, 20):  # a drag
        window["geometry"] = [x, 1200, x + 480, 780]
        tick(pi)
    assert saved(pi)["computer_window"] == []
    for _ in range(20):
        tick(pi)
    assert saved(pi)["computer_window"] == [180, 1200, 660, 780]
    window["popped"] = 1  # popped out: its own OS window, nothing to save
    window["geometry"] = [100010, 710, 101010, 10]
    for _ in range(20):
        tick(pi)
    assert pi.settings.computer_window == [180, 1200, 660, 780]


def test_after_a_click_the_keyboard_goes_back_to_the_sim(plugin):
    pi, xp, data = plugin
    choose(xp, "Flight Computer")
    tick(pi)
    wid, window = the_window(xp)
    assert json.loads(call(window, "xpg_do", {"cmd": "release_keys"})) == {"ok": True}
    assert ("focus", 0) not in xp.calls_log  # not from CEF's call: the next tick does it
    tick(pi)
    assert xp.calls_log[-2:] == [("focus", wid), ("focus", 0)]
    tick(pi)
    assert xp.calls_log[-2:] == [("focus", wid), ("focus", 0)]  # once per click


def test_the_page_may_set_its_view_and_nothing_else(plugin):
    pi, xp, data = plugin
    choose(xp, "Flight Computer")
    tick(pi)
    wid, window = the_window(xp)
    assert json.loads(call(window, "xpg_do", {"cmd": "set", "view": "flight"}))["ok"] is True
    assert json.loads(call(window, "xpg_do", {"cmd": "set", "view": "../../etc"}))["ok"] is False
    assert json.loads(call(window, "xpg_do", {"cmd": "delete_everything"}))["ok"] is False
    assert json.loads(window["functions"][1][1](None, "not json", None))["ok"] is False
    assert pi.settings.computer_view == "flight" and not pi.computer.failed


def test_a_page_that_does_not_answer_after_loading_is_reloaded_once(plugin):
    pi, xp, data = plugin
    choose(xp, "Flight Computer")
    tick(pi)
    wid, window = the_window(xp)
    on_load = window["kw"]["browserLoadFinished"]
    on_load(wid, "about:blank", None)  # CEF's own blank page first: ignored
    assert dataref(xp, "computer/loaded") == 0
    on_load(wid, window["url"], None)
    on_load(wid, window["url"], None)  # it can come twice for one load
    assert dataref(xp, "computer/loaded") == 1
    tick(pi, seconds=-pi.test_later)  # back to the load's own time: not yet overdue
    assert window["refreshed"] == 0
    tick(pi, seconds=5.0)  # no call for 5 s: window.xplane was missing
    assert window["refreshed"] == 1
    on_load(wid, window["url"], None)
    call(window, "xpg_state")  # now the page answers
    tick(pi, seconds=5.0)
    assert window["refreshed"] == 1


def test_a_page_that_answers_is_left_alone(plugin):
    pi, xp, data = plugin
    choose(xp, "Flight Computer")
    tick(pi)
    wid, window = the_window(xp)
    window["kw"]["browserLoadFinished"](wid, window["url"], None)
    call(window, "xpg_state")
    tick(pi, seconds=5.0)
    assert window["refreshed"] == 0


def test_the_computer_needs_a_glider_and_the_plugin_enabled(plugin):
    pi, xp, data = plugin
    choose(xp, "Flight Computer")
    tick(pi)
    assert xp.windows
    pi.settings.enabled = False
    tick(pi)
    assert not xp.windows and pi.settings.computer_enabled  # gone, but still chosen
    pi.settings.enabled = True
    pi.hud.eligible = False
    tick(pi)
    assert not xp.windows and not pi.hud.also_wanted


def test_a_failure_stops_the_computer_and_nothing_else(plugin, capsys):
    pi, xp, data = plugin
    choose(xp, "Flight Computer")
    tick(pi)
    del data["sim/flightmodel/position/local_vx"]  # the snapshot fails
    for _ in range(3):
        assert pi.computer.on_loop(0.1, 0.1, 0, None) == pytest.approx(0.1)
    out = capsys.readouterr().out
    assert out.count("Flight Computer stopped") == 1
    assert pi.computer.failed and not xp.windows and not pi.hud.also_wanted
    # The thermals go on.
    data["sim/flightmodel/position/local_vx"] = 0.0
    assert pi.flight_loop(0.016, 0.016, 0, None) == -1


def test_disabling_the_plugin_destroys_the_window(plugin):
    pi, xp, data = plugin
    choose(xp, "Flight Computer")
    tick(pi)
    assert xp.windows
    pi.XPluginDisable()
    assert not xp.windows
    pi.XPluginEnable()
    tick(pi)
    assert xp.windows


def test_a_slower_poll_reaches_the_page_through_the_snapshot(plugin):
    pi, xp, data = plugin
    choose(xp, "Flight Computer")
    dataref(xp, "computer/poll_hz", 2)
    tick(pi)
    wid, window = the_window(xp)
    assert json.loads(call(window, "xpg_state"))["poll_hz"] == 2
