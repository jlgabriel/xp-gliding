"""The flight logger records by itself: when it starts, when it ends, and that a hand wins."""

import importlib.util
import os
import sys
from unittest import mock

import pytest

PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "PI_xpg_flightlog.py")


@pytest.fixture
def logger(monkeypatch):
    fake = mock.MagicMock()
    monkeypatch.setitem(sys.modules, "xp", fake)
    spec = importlib.util.spec_from_file_location("pi_xpg_flightlog_under_test", PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, fake


def fly(auto, seconds, recording=False, glider=True, agl=500.0, speed=25.0, paused=False):
    """One step a second; the first action asked for, and at which second."""
    for s in range(seconds):
        action = auto.step(1.0, recording, glider, agl, speed, paused)
        if action is not None:
            return action, s + 1
    return None, seconds


def test_a_glider_in_the_air_starts_a_log(logger):
    module, _ = logger
    auto = module.AutoRecord()
    action, second = fly(auto, 5)
    assert action == auto.START and second == 2


def test_not_on_the_ground_nor_in_a_powered_aircraft_nor_paused(logger):
    module, _ = logger
    auto = module.AutoRecord()
    assert fly(auto, 60, agl=1.0, speed=0.0)[0] is None
    assert fly(auto, 60, glider=False)[0] is None
    assert fly(auto, 60, paused=True)[0] is None


def test_landing_ends_the_log_it_started(logger):
    module, _ = logger
    auto = module.AutoRecord()
    assert fly(auto, 5)[0] == auto.START
    assert fly(auto, 60, recording=True, agl=100.0, speed=25.0)[0] is None
    assert fly(auto, 10, recording=True, agl=1.0, speed=20.0)[0] is None  # rolling out
    action, second = fly(auto, 60, recording=True, agl=1.0, speed=0.0)
    assert action == auto.STOP and second == 20
    assert fly(auto, 5)[0] == auto.START  # and the next flight gets its own


def test_a_log_started_by_hand_is_not_ended_here(logger):
    module, _ = logger
    auto = module.AutoRecord()
    assert fly(auto, 120, recording=True, agl=1.0, speed=0.0)[0] is None


def test_stopping_by_hand_holds_until_the_next_flight(logger):
    module, _ = logger
    auto = module.AutoRecord()
    assert fly(auto, 5)[0] == auto.START
    auto.stopped_by_hand()
    assert fly(auto, 60)[0] is None
    assert auto.new_flight() is None
    assert fly(auto, 5)[0] == auto.START


def test_a_new_flight_ends_the_log_it_started(logger):
    module, _ = logger
    auto = module.AutoRecord()
    assert fly(auto, 5)[0] == auto.START
    assert auto.new_flight() == auto.STOP
    assert auto.new_flight() is None


def test_turned_off_it_does_nothing(logger):
    module, _ = logger
    auto = module.AutoRecord()
    auto.enabled = False
    assert fly(auto, 60)[0] is None


def test_the_airbrakes_are_a_column(logger):
    module, _ = logger
    assert "speedbrake_ratio" in module.COLUMNS


def test_a_log_can_rebuild_the_sky(logger):
    module, _ = logger
    for column in ("date_days", "t_local_s", "xpg_seed", "xpg_sky_index", "xpg_dlat_deg", "xpg_dlon_deg",
                   "xpg_wstar_ms", "xpg_zi_m", "xpg_cloud_level_m", "xpg_cloud_nearest_base_m"):
        assert column in module.COLUMNS


def test_the_plugin_records_a_flight_by_itself(logger, tmp_path):
    module, fake = logger
    fake.getSystemPath.return_value = str(tmp_path)
    fake.getNthAircraftModel.return_value = ("ASK21.acf", "path")
    fake.getVersions.return_value = (12431, 430, 0)
    data = {"sim/aircraft/engine/acf_num_engines": 0, "sim/flightmodel/position/y_agl": 500.0,
            "sim/flightmodel/position/groundspeed": 25.0, "sim/time/paused": 0, "sim/time/is_in_replay": 0}
    fake.findDataRef.side_effect = lambda name: name
    fake.getDatai.side_effect = lambda ref: data[ref]
    fake.getDataf.side_effect = lambda ref: data[ref]
    module._alex_world = lambda: None
    pi = module.PythonInterface()
    pi.XPluginStart()
    for _ in range(3):
        assert pi.auto_step(1.0, 0.0, 0, None) == 1.0
    assert pi.file is not None
    folder = tmp_path / "Output" / "xp-gliding" / "flightlogs"
    assert len(list(folder.iterdir())) == 1
    data["sim/flightmodel/position/y_agl"] = 1.0
    data["sim/flightmodel/position/groundspeed"] = 0.0
    for _ in range(25):
        pi.auto_step(1.0, 0.0, 0, None)
    assert pi.file is None


def test_rows_are_rounded_and_none_written_while_paused(logger, tmp_path):
    module, fake = logger
    fake.getSystemPath.return_value = str(tmp_path)
    fake.getNthAircraftModel.return_value = ("ASK21.acf", "path")
    fake.getVersions.return_value = (12431, 430, 0)
    data = {"sim/time/paused": 0, "sim/time/is_in_replay": 0,
            "sim/time/total_running_time_sec": 2011.628662109375,
            "sim/flightmodel/position/latitude": 43.63000329256785,
            "sim/flightmodel/position/elevation": 2171.285453229408}
    fake.findDataRef.side_effect = lambda name: name
    for getter in (fake.getDatai, fake.getDataf, fake.getDatad):
        getter.side_effect = lambda ref: data.get(ref, 0.123456789)
    module._alex_world = lambda: None
    pi = module.PythonInterface()
    pi.XPluginStart()
    pi.start_recording()
    pi.after_fm(0.0, 0.0, 0, None)
    data["sim/time/paused"] = 1
    pi.after_fm(0.0, 0.0, 0, None)
    data["sim/time/paused"], data["sim/time/is_in_replay"] = 0, 1
    pi.after_fm(0.0, 0.0, 0, None)
    pi.stop_recording()
    (log,) = (tmp_path / "Output" / "xp-gliding" / "flightlogs").iterdir()
    lines = [line for line in log.read_text().splitlines() if not line.startswith("#")]
    assert len(lines) == 2  # the header and the one frame flown
    row = dict(zip(lines[0].split(","), lines[1].split(",")))
    assert row["t_run_s"] == "2011.629"
    assert row["lat_deg"] == "43.6300033"
    assert row["elev_m"] == "2171.29"
    assert row["tas_ms"] == "0.123457"
