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
    xp.WindowPositionFree = "free"

    def set_mode(wid, mode, index=-1):
        assert mode == "free"
        xp.windows[wid]["popped"] = 0

    def set_geometry(wid, left, top, right, bottom):
        xp.windows[wid]["geometry"] = [left, top, right, bottom]

    xp.setWindowPositioningMode = set_mode
    xp.setWindowGeometry = set_geometry


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
    assert [name for name, _ in window["functions"]] == ["xpg_setup", "xpg_state", "xpg_track", "xpg_do",
                                                         "xpg_tasks", "xpg_task"]
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
    assert state["local_s"] == data["sim/time/local_time_sec"]  # for the clock
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


def test_a_popped_out_window_is_put_back_inside_x_plane(plugin, capsys):
    pi, xp, data = plugin
    choose(xp, "Flight Computer")
    tick(pi)
    wid, window = the_window(xp)
    placed = list(window["geometry"])
    window["popped"] = 1  # the pilot popped it out, and X-Plane moved it far out of its desktop
    window["geometry"] = [100010, 430, 100490, 10]
    for _ in range(5):
        tick(pi)
    assert window["popped"] == 0 and window["geometry"] == placed
    window["popped"] = 1  # again: put back again, said once in the log
    for _ in range(5):
        tick(pi)
    assert window["popped"] == 0
    assert capsys.readouterr().out.count("kept inside X-Plane") == 1
    for _ in range(20):
        tick(pi)
    assert saved(pi)["computer_window"] == []  # its place was never the popped-out one


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
    assert json.loads(call(window, "xpg_do", {"cmd": "set", "view": "map"}))["ok"] is True
    assert pi.settings.computer_view == "map" and saved(pi)["computer_view"] == "map"
    assert json.loads(call(window, "xpg_do", {"cmd": "set", "view": "flight"}))["ok"] is True
    assert json.loads(call(window, "xpg_do", {"cmd": "set", "view": "../../etc"}))["ok"] is False
    assert json.loads(call(window, "xpg_do", {"cmd": "delete_everything"}))["ok"] is False
    assert json.loads(dict(window["functions"])["xpg_do"](None, "not json", None))["ok"] is False
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


# --- the map's track (nav/track.py) and setup ----------------------------------------------------


def fly(pi, data, seconds, step=0.1, north_ms=25.0):
    """The glider flies north at north_ms: the computer's ticks with the simulator's time and place."""
    for _ in range(round(seconds / step)):
        data["sim/time/total_running_time_sec"] += step
        data["sim/flightmodel/position/latitude"] += north_ms * step / 111195.0
        tick(pi, step)


def test_the_page_is_told_the_maps_tiles_and_their_attribution(plugin):
    pi, xp, data = plugin
    choose(xp, "Flight Computer")
    tick(pi)
    wid, window = the_window(xp)
    setup = json.loads(call(window, "xpg_setup"))
    assert setup["tiles"] == "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png"
    assert "OpenStreetMap" in setup["attribution"] and "OpenTopoMap" in setup["attribution"]
    assert setup["max_zoom"] == 17


def test_the_track_is_kept_once_a_second_and_the_page_gets_it_in_pieces(plugin):
    pi, xp, data = plugin
    choose(xp, "Flight Computer")
    fly(pi, data, 10.0)
    wid, window = the_window(xp)
    state = json.loads(call(window, "xpg_state"))
    epoch = pi.computer.track.epoch  # the aircraft's loading started one
    assert 9 <= state["track_n"] <= 10 and state["track_epoch"] == epoch
    got = json.loads(call(window, "xpg_track", {"epoch": None, "from": 0}))
    assert got["epoch"] == epoch and got["from"] == 0 and len(got["points"]) == got["n"] == pi.computer.track.count
    lats = [lat for lat, lon, msl in got["points"]]
    assert lats == sorted(lats) and got["points"][0][1] == pytest.approx(-103.217)
    assert got["points"][0][2] == round(data["sim/flightmodel/position/elevation"])
    assert dataref(xp, "computer/track_shown") == got["n"]
    fly(pi, data, 3.0)
    more = json.loads(call(window, "xpg_track", {"epoch": epoch, "from": got["n"]}))
    assert more["from"] == got["n"] and len(more["points"]) == 3
    assert dataref(xp, "computer/track_n") == got["n"] + 3


def test_nothing_is_kept_while_paused_or_in_replay(plugin):
    pi, xp, data = plugin
    choose(xp, "Flight Computer")
    fly(pi, data, 3.0)
    n = pi.computer.track.count
    data["sim/time/paused"] = 1
    fly(pi, data, 3.0)
    data["sim/time/paused"] = 0
    data["sim/time/is_in_replay"] = 1
    fly(pi, data, 3.0)
    assert pi.computer.track.count == n


def test_the_track_is_kept_with_the_window_closed_but_not_with_the_hud_chosen(plugin):
    pi, xp, data = plugin
    choose(xp, "Flight Computer")
    pi.settings.enabled = False  # no window, the Flight Computer still chosen ... but not wanted
    fly(pi, data, 3.0)
    assert pi.computer.track.count == 0
    pi.settings.enabled = True
    fly(pi, data, 3.0)
    n = pi.computer.track.count
    assert n >= 2
    choose(xp, "Soaring HUD")
    fly(pi, data, 3.0)
    assert pi.computer.track.count == n


def test_a_jump_seen_by_the_instruments_starts_the_track_again(plugin):
    pi, xp, data = plugin
    choose(xp, "Flight Computer")
    fly(pi, data, 5.0)
    assert pi.computer.track.count >= 4
    epoch = pi.computer.track.epoch
    pi.hud.reset_instruments()  # the plugin saw a jump, a placement or a new flight
    fly(pi, data, 2.0)
    wid, window = the_window(xp)
    assert json.loads(call(window, "xpg_state"))["track_epoch"] == epoch + 1
    got = json.loads(call(window, "xpg_track", {"epoch": epoch, "from": 5}))
    assert got["epoch"] == epoch + 1 and got["from"] == 0 and len(got["points"]) == pi.computer.track.count <= 2


def test_a_bad_track_request_gets_the_whole_track(plugin):
    pi, xp, data = plugin
    choose(xp, "Flight Computer")
    fly(pi, data, 3.0)
    wid, window = the_window(xp)
    function = dict(window["functions"])["xpg_track"]
    for arg in ("not json", "[1, 2]", '{"from": "x"}'):
        got = json.loads(function(None, arg, None))
        assert got["from"] == 0 and len(got["points"]) == pi.computer.track.count
    assert not pi.computer.failed


def test_the_test_pilot_can_write_the_track_to_a_file(plugin):
    pi, xp, data = plugin
    choose(xp, "Flight Computer")
    fly(pi, data, 4.0)
    dataref(xp, "computer/track_dump", 1)
    tick(pi)
    with open(pi.computer.track_path, encoding="utf-8") as f:
        dumped = json.load(f)
    assert dumped["n"] == len(dumped["points"]) == pi.computer.track.count
    t, lat, lon, msl = dumped["points"][0]
    assert lon == pytest.approx(-103.217) and dataref(xp, "computer/track_dump") == 0


# --- tasks ------------------------------------------------------------------------------------

START_LAT, START_LON = 32.6875, -103.217  # where the fake glider is, flying north (fly)


def cup_angle(value, positive, negative, width):
    hemisphere = positive if value >= 0 else negative
    value = abs(value)
    degrees = int(value)
    return f"{degrees:0{width}d}{(value - degrees) * 60.0:06.3f}{hemisphere}"


def write_tasks(tmp_path, name="short.cup"):
    """A task straight ahead of the glider: its start line 300 m north, a turn point 2 km past
    the start, the finish 4 km past it; with our default zones."""
    folder = tmp_path / "Output" / "xp-gliding" / "tasks"
    folder.mkdir(parents=True, exist_ok=True)
    lines = ["name,code,country,lat,lon,elev,style"]
    for label, north_m in (("Start", 300.0), ("Turn", 2300.0), ("Goal", 4300.0)):
        lat = START_LAT + north_m / 111195.0
        lines.append(f'"{label}",,,{cup_angle(lat, "N", "S", 2)},{cup_angle(START_LON, "E", "W", 3)},1000m,1')
    lines += ["-----Related Tasks-----", '"Short","Start","Start","Turn","Goal","Goal"',
              '"Other","Start","Start","Goal","Start"']
    (folder / name).write_text("\n".join(lines) + "\n", encoding="utf-8")
    (folder / "notes.txt").write_text("not a task file", encoding="utf-8")
    return folder


def load_request(tmp_path, index, file="short.cup"):
    """The page's load_task for task `index` of `file`, with its key as the list gives it."""
    from xp_gliding.nav import cup
    from xp_gliding.nav.task import task_key
    found = cup.load(str(tmp_path / "Output" / "xp-gliding" / "tasks" / file))
    return {"cmd": "load_task", "file": file, "index": index, "key": task_key(found.tasks[index])}


def state_of(window):
    return json.loads(call(window, "xpg_state"))


def test_the_picker_lists_the_task_files_and_loads_one(plugin, tmp_path):
    pi, xp, data = plugin
    write_tasks(tmp_path)
    choose(xp, "Flight Computer")
    tick(pi)
    wid, window = the_window(xp)
    before = state_of(window)
    assert before["nav"] is None and before["task_rev"] == 0
    assert json.loads(call(window, "xpg_do", {"cmd": "list_tasks"}))["ok"]
    tick(pi), tick(pi)
    listed = json.loads(call(window, "xpg_tasks"))
    assert state_of(window)["tasks_rev"] == listed["rev"] > before["tasks_rev"]
    (entry,) = listed["files"]
    assert entry["file"] == "short.cup" and entry["error"] is None
    assert [(t["index"], t["name"], t["points"]) for t in entry["tasks"]] == [(0, "Short", 3), (1, "Other", 2)]
    assert entry["tasks"][0]["total_m"] == pytest.approx(4000.0, abs=5.0)
    assert listed["current"] is None
    assert json.loads(call(window, "xpg_do", load_request(tmp_path, 0)))["ok"]
    tick(pi), tick(pi)
    task = json.loads(call(window, "xpg_task"))
    assert task["name"] == "Short" and [p["role"] for p in task["points"]] == ["start", "point", "finish"]
    assert task["points"][0]["zone"]["kind"] == "line"
    state = state_of(window)
    assert state["task_rev"] == task["rev"] and state["nav"]["name"] == "Start" and state["nav"]["index"] == 0
    assert state["nav"]["dist_m"] == pytest.approx(300.0, abs=3.0)
    assert saved(pi)["computer_task"] == "short.cup#0"
    assert dataref(xp, "computer/nav_index") == 0
    call(window, "xpg_do", {"cmd": "list_tasks"})
    tick(pi)
    assert json.loads(call(window, "xpg_tasks"))["current"] == {"file": "short.cup", "index": 0}


def test_a_task_flown_takes_its_points_in_order(plugin, tmp_path, capsys):
    pi, xp, data = plugin
    write_tasks(tmp_path)
    choose(xp, "Flight Computer")
    tick(pi)
    wid, window = the_window(xp)
    call(window, "xpg_do", load_request(tmp_path, 0))
    tick(pi)
    fly(pi, data, 20.0)  # 500 m: across the start line
    assert dataref(xp, "computer/nav_index") == 1 and state_of(window)["nav"]["started"]
    fly(pi, data, 60.0)  # 2 km on: inside the turn point's cylinder
    assert dataref(xp, "computer/nav_index") == 2
    fly(pi, data, 80.0)
    nav = state_of(window)["nav"]
    assert nav["finished"] and nav["task_left_m"] == 0.0 and nav["task_done"] == 1.0
    out = capsys.readouterr().out
    assert "start 'Start' taken (line)" in out and "point 1 'Turn' taken (zone)" in out
    assert "finish 'Goal' taken (zone)" in out


def test_points_by_hand_and_clearing_the_task(plugin, tmp_path):
    pi, xp, data = plugin
    write_tasks(tmp_path)
    choose(xp, "Flight Computer")
    tick(pi)
    wid, window = the_window(xp)
    call(window, "xpg_do", load_request(tmp_path, 0))
    tick(pi)
    call(window, "xpg_do", {"cmd": "next_point"})
    call(window, "xpg_do", {"cmd": "next_point"})
    tick(pi), tick(pi)
    assert state_of(window)["nav"]["name"] == "Goal"
    call(window, "xpg_do", {"cmd": "prev_point"})
    tick(pi), tick(pi)
    assert state_of(window)["nav"]["name"] == "Turn"
    rev = state_of(window)["task_rev"]
    call(window, "xpg_do", {"cmd": "clear_task"})
    tick(pi), tick(pi)
    state = state_of(window)
    assert state["nav"] is None and state["task_rev"] == rev + 1
    assert json.loads(call(window, "xpg_task"))["name"] is None
    assert saved(pi)["computer_task"] == "" and dataref(xp, "computer/nav_index") == -1


def test_only_a_listed_file_and_a_task_in_it_can_be_loaded(plugin, tmp_path):
    pi, xp, data = plugin
    folder = write_tasks(tmp_path)
    (folder.parent / "outside.cup").write_text((folder / "short.cup").read_text(), encoding="utf-8")
    choose(xp, "Flight Computer")
    tick(pi)
    wid, window = the_window(xp)
    for bad in ({"file": "../outside.cup", "index": 0}, {"file": "notes.txt", "index": 0},
                {"file": "short.cup", "index": "0"}, {"file": "short.cup", "index": True},
                {"file": "short.cup"}, {"file": None, "index": 0}):
        assert not json.loads(call(window, "xpg_do", {"cmd": "load_task", **bad}))["ok"], bad
    for bad in ({"file": "short.cup", "index": 0}, {"file": "short.cup", "index": 0, "key": ""},
                {"file": "short.cup", "index": 0, "key": 5}):
        assert not json.loads(call(window, "xpg_do", {"cmd": "load_task", **bad}))["ok"], bad
    assert json.loads(call(window, "xpg_do", {"cmd": "load_task", "file": "short.cup", "index": 7,
                                              "key": "0" * 12}))["ok"]
    tick(pi), tick(pi)
    assert pi.computer.task is None and state_of(window)["task_rev"] == 0 and not pi.computer.failed


def test_the_task_chosen_is_loaded_again_at_start(tmp_path, monkeypatch, capsys):
    write_tasks(tmp_path)
    pi, xp, data = start(tmp_path, monkeypatch, config={"computer_enabled": True, "hud_enabled": False,
                                                         "computer_task": "short.cup#1"})
    try:
        assert pi.computer.task is not None and pi.computer.task.name == "Other"
        assert "task 'Other' from short.cup: 2 points" in capsys.readouterr().out
    finally:
        pi.XPluginDisable()
        pi.XPluginStop()


def reorder_tasks(tmp_path, file="short.cup", rename=None):
    """Swap the file's two tasks, as a pilot editing it would; `rename` renames the first."""
    path = tmp_path / "Output" / "xp-gliding" / "tasks" / file
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[-2], lines[-1] = lines[-1], lines[-2]
    if rename:
        lines[-1] = lines[-1].replace('"Short"', f'"{rename}"', 1)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_a_task_moved_in_its_file_after_the_list_is_still_the_one_loaded(plugin, tmp_path):
    pi, xp, data = plugin
    write_tasks(tmp_path)
    choose(xp, "Flight Computer")
    tick(pi)
    wid, window = the_window(xp)
    request = load_request(tmp_path, 0)  # "Short" as listed, first in the file
    reorder_tasks(tmp_path)  # now second
    call(window, "xpg_do", request)
    tick(pi), tick(pi)
    assert pi.computer.task.name == "Short" and json.loads(call(window, "xpg_task"))["name"] == "Short"
    assert saved(pi)["computer_task"] == "short.cup#1"
    assert saved(pi)["computer_task_key"] == request["key"]
    listed = json.loads(call(window, "xpg_tasks"))  # the load made the list again
    assert listed["current"] == {"file": "short.cup", "index": 1} and listed["note"] == ""


def test_a_task_of_the_same_name_with_another_route_is_not_loaded(plugin, tmp_path, capsys):
    pi, xp, data = plugin
    write_tasks(tmp_path)
    choose(xp, "Flight Computer")
    tick(pi)
    wid, window = the_window(xp)
    request = load_request(tmp_path, 0)  # "Short": Start, Turn, Goal
    reorder_tasks(tmp_path, rename="Other")  # both are "Other" now; the one first goes to Goal only
    reorder_tasks(tmp_path)  # and back in place: the number and the name match, the route not
    call(window, "xpg_do", request)
    tick(pi), tick(pi)
    assert pi.computer.task is None and state_of(window)["task_rev"] == 0
    listed = json.loads(call(window, "xpg_tasks"))
    assert listed["current"] is None and "pick it again" in listed["note"]
    assert "it was changed or removed" in capsys.readouterr().out


def test_a_saved_task_is_found_by_its_key_when_its_file_was_reordered(tmp_path, monkeypatch, capsys):
    write_tasks(tmp_path)
    key = load_request(tmp_path, 1)["key"]  # "Other"
    reorder_tasks(tmp_path)  # now first
    pi, xp, data = start(tmp_path, monkeypatch, config={"computer_enabled": True, "hud_enabled": False,
                                                         "computer_task": "short.cup#1",
                                                         "computer_task_key": key})
    try:
        assert pi.computer.task.name == "Other"
        assert "(now task 0 of the file)" in capsys.readouterr().out
        tick(pi)  # saved by the first tick: at start the plugin cannot save yet
        assert saved(pi)["computer_task"] == "short.cup#0" and saved(pi)["computer_task_key"] == key
    finally:
        pi.XPluginDisable()
        pi.XPluginStop()


def test_a_saved_task_no_longer_in_its_file_is_not_loaded(tmp_path, monkeypatch, capsys):
    write_tasks(tmp_path)
    pi, xp, data = start(tmp_path, monkeypatch, config={"computer_enabled": True, "hud_enabled": False,
                                                         "computer_task": "short.cup#1",
                                                         "computer_task_key": "0123456789ab"})
    try:
        assert pi.computer.task is None
        assert "was not loaded" in capsys.readouterr().out
    finally:
        pi.XPluginDisable()
        pi.XPluginStop()


def test_a_jump_into_the_turn_points_zone_does_not_take_it(plugin, tmp_path):
    pi, xp, data = plugin
    write_tasks(tmp_path)
    choose(xp, "Flight Computer")
    tick(pi)
    wid, window = the_window(xp)
    call(window, "xpg_do", load_request(tmp_path, 0))
    fly(pi, data, 20.0)  # across the start line
    assert dataref(xp, "computer/nav_index") == 1
    data["sim/flightmodel/position/latitude"] = START_LAT + 2300.0 / 111195.0  # placed on the turn point
    pi.hud.reset_instruments()
    fly(pi, data, 2.0)
    assert dataref(xp, "computer/nav_index") == 1 and state_of(window)["nav"]["in_zone"]


def test_a_short_move_on_the_map_into_the_zone_does_not_take_it(plugin, tmp_path):
    pi, xp, data = plugin
    write_tasks(tmp_path)
    choose(xp, "Flight Computer")
    tick(pi)
    wid, window = the_window(xp)
    call(window, "xpg_do", load_request(tmp_path, 0))
    fly(pi, data, 20.0)  # across the start line, 1.3 km short of the turn point's cylinder
    assert dataref(xp, "computer/nav_index") == 1
    resets = pi.hud.resets
    data["sim/flightmodel/position/latitude"] = START_LAT + 2200.0 / 111195.0  # moved, nobody told
    fly(pi, data, 2.0)
    assert pi.hud.resets == resets  # the adapter's own jump test did not see it
    assert dataref(xp, "computer/nav_index") == 1 and state_of(window)["nav"]["in_zone"]


def test_a_file_gone_since_the_list_was_made_makes_the_list_again(plugin, tmp_path):
    pi, xp, data = plugin
    folder = write_tasks(tmp_path)
    choose(xp, "Flight Computer")
    tick(pi)
    wid, window = the_window(xp)
    call(window, "xpg_do", {"cmd": "list_tasks"})
    tick(pi)
    rev = json.loads(call(window, "xpg_tasks"))["rev"]
    request = load_request(tmp_path, 0)
    (folder / "short.cup").rename(folder / "renamed.cup")
    assert not json.loads(call(window, "xpg_do", request))["ok"]
    tick(pi)
    listed = json.loads(call(window, "xpg_tasks"))
    assert listed["rev"] > rev and [f["file"] for f in listed["files"]] == ["renamed.cup"]
    assert "pick it again" in listed["note"] and pi.computer.task is None
    call(window, "xpg_do", {"cmd": "list_tasks"})
    tick(pi)
    assert json.loads(call(window, "xpg_tasks"))["note"] == ""


def test_a_jump_does_not_take_the_start(plugin, tmp_path):
    pi, xp, data = plugin
    write_tasks(tmp_path)
    choose(xp, "Flight Computer")
    tick(pi)
    wid, window = the_window(xp)
    call(window, "xpg_do", load_request(tmp_path, 0))
    fly(pi, data, 1.0)
    data["sim/flightmodel/position/latitude"] += 600.0 / 111195.0  # placed past the start line
    pi.hud.reset_instruments()
    fly(pi, data, 2.0)
    assert dataref(xp, "computer/nav_index") == 0 and not state_of(window)["nav"]["started"]
