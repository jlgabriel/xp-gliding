"""Hotspot files and the hotspot flight (engine/hotspots.py, field.ThermalField with hotspots)."""

import math
import statistics

import pytest

from xp_gliding.engine import field as f
from xp_gliding.engine import hotspots as h
from xp_gliding.engine.clouds import CloudParams, carries_cloud
from xp_gliding.engine.geo import LocalFrame
from xp_gliding.engine.sun import SUN_MIN_DEG
from xp_gliding.engine.wind import AirDrift

KK7 = """latitude degree WGS84,longitude degree WGS84,altitude in meters AMSL,thermal probability in a circle with 250m radius around the hotspot
-33.34917,-70.30804,2506,100
-33.3027,-70.51506,1400,61
-33.38272,-70.60844,643,82
"""
LAT, LON = -33.38272, -70.60844
NOON = 16.5 * 3600.0  # about 13:00 at Santiago in November, as the field's t (zulu)
DAY = 305


def one(p=1.0, lat=LAT, lon=LON):
    return h.HotspotSet([h.Hotspot(lat, lon, 643.0, p)], name="one.csv")


def test_a_kk7_file_reads_its_hotspots_and_skips_what_is_not_one():
    hotspots, skipped = h.parse(KK7 + "\n-33.3,not a number,10,50\n91,0,0,50\n-33.3,-70.3,0,0\n\n")
    assert skipped == 4  # the header, a broken line, a place off the globe, a probability of 0
    assert [(s.lat, s.lon, s.alt_m) for s in hotspots] == [(-33.34917, -70.30804, 2506.0),
                                                          (-33.3027, -70.51506, 1400.0), (LAT, LON, 643.0)]
    assert [s.p for s in hotspots] == pytest.approx([1.0, 0.61, 0.82])


def test_a_file_is_read_from_disk_and_the_folder_lists_csv_files(tmp_path):
    (tmp_path / "santiago.csv").write_text(KK7, encoding="utf-8")
    (tmp_path / "Alps.CSV").write_text(KK7, encoding="utf-8")
    (tmp_path / "notes.txt").write_text("not a hotspot file", encoding="utf-8")
    assert h.find_files(str(tmp_path)) == ["Alps.CSV", "santiago.csv"]
    assert h.find_files(str(tmp_path / "missing")) == []
    found = h.load(str(tmp_path / "santiago.csv"))
    assert (len(found), found.skipped, found.name) == (3, 1, "santiago.csv")
    with pytest.raises(OSError):
        h.load(str(tmp_path / "missing.csv"))


def test_near_finds_the_hotspots_within_range_only():
    found, _ = h.parse(KK7)
    spots = h.HotspotSet(found)
    assert sorted(spots.near(LAT, LON, 12000.0)) == [2]  # the second is 12.4 km away, the first 28 km
    assert sorted(spots.near(LAT, LON, 13000.0)) == [1, 2]
    assert sorted(spots.near(LAT, LON, 29000.0)) == [0, 1, 2]
    assert spots.near(0.0, 0.0, 30000.0) == []


def config(**kw):
    kw.setdefault("seed", 1)
    kw.setdefault("day", DAY)
    return f.FieldConfig(sky=f.SKIES["wide_carriers"], **kw)


def test_the_same_file_seed_and_date_give_the_same_thermals_whatever_the_order_of_lines():
    found, _ = h.parse(KK7)
    a, b = h.HotspotSet(found), h.HotspotSet(list(reversed(found)))
    cfg = config()
    for slot in range(20, 30):
        mine = [(t.lat, t.lon, t.birth, t.wgain) for t in a.generate(cfg, 2, slot)]
        theirs = [(t.lat, t.lon, t.birth, t.wgain) for t in b.generate(cfg, 0, slot)]
        assert mine == theirs
    other = [(t.lat, t.birth) for slot in range(20, 30) for t in a.generate(config(seed=2), 2, slot)]
    assert other != [(t.lat, t.birth) for slot in range(20, 30) for t in a.generate(cfg, 2, slot)]


def alive_counts(spots, cfg, slots=2000, steps=6):
    """How many of its thermals are alive, at a few times in each of many slots."""
    counts = []
    for s in range(1, slots):
        thermals = spots.generate(cfg, 0, s - 1) + spots.generate(cfg, 0, s)
        for k in range(steps):
            t = (s + k / steps) * cfg.slot_s
            counts.append(sum(1 for th in thermals if th.birth <= t < th.death))
    return counts


@pytest.mark.parametrize("p", [1.0, 0.8, 0.6])
def test_a_hotspot_has_a_thermal_its_probability_of_the_time_one_at_a_time(p):
    counts = alive_counts(one(p), config())
    assert max(counts) == 1  # never two at once, which would add into one too strong
    assert statistics.mean(counts) == pytest.approx(h.duty(p), abs=0.03)
    assert h.duty(1.0) == h.DUTY_MAX  # a pause now and then even at 100%


def test_the_cycle_is_one_after_another_and_the_slots_hold_each_thermal_once():
    spots, cfg = one(0.7), config()
    cycle = spots.cycle_of(cfg, 0, 20)
    assert len(cycle) > 20
    for (_, b0, l0), (_, b1, _) in zip(cycle, cycle[1:]):
        assert b1 >= b0 + l0
    start = h.chunk_start(LON, 20)
    first, last = math.floor(start / cfg.slot_s), math.floor((start + h.DAY_S) / cfg.slot_s)
    from_slots = sorted(th.birth for s in range(first, last + 1) for th in spots.generate(cfg, 0, s)
                        if start <= th.birth < start + h.DAY_S)
    assert from_slots == pytest.approx([b for _, b, _ in cycle])
    assert h.chunk_of(LON, start) == 20 and h.chunk_of(LON, start - 1.0) == 19


def test_its_thermals_start_within_250_m_and_all_carry_a_cloud():
    cfg = config()
    frame = LocalFrame(LAT, LON)
    params = CloudParams()
    thermals = [th for s in range(200) for th in one().generate(cfg, 0, s)]
    assert len(thermals) > 100
    assert max(math.hypot(*frame.to_enu(th.lat, th.lon)) for th in thermals) <= h.RADIUS_M + 1e-6
    assert all(carries_cloud(th, params) for th in thermals)
    assert all((th.gain, th.stretch) == (cfg.sky.carrier_gain, cfg.sky.carrier_stretch) for th in thermals)


def test_none_is_born_with_the_sun_low():
    cfg = config(sun_min_deg=SUN_MIN_DEG)
    births = [th.birth % 86400.0 for s in range(48 * 10) for th in one().generate(cfg, 0, s)]
    assert births
    night = [(t / 3600.0 - 4.7) % 24.0 for t in births]  # local solar hours at -70.6
    assert all(5.0 < hour < 19.0 for hour in night)  # the sun 10 degrees up, in November


def test_with_wind_a_thermal_is_placed_where_its_ground_is_at_its_birth():
    drift = AirDrift()
    drift.advance(0.0, 0.0, LAT, 1000.0)
    drift.advance(10.0, 0.0, LAT, 1060.0)  # 10 m/s from the west, a minute on: 600 m east
    cfg = config()
    still = [th for s in range(3) for th in one().generate(cfg, 0, s)]
    windy = [th for s in range(3) for th in one().generate(cfg, 0, s, air_at=drift.to_air_at)]
    assert len(still) == len(windy) > 0
    for a, b in zip(still, windy):
        assert drift.to_ground_at(b.lat, b.lon, b.birth) == pytest.approx((a.lat, a.lon))


def test_a_hotspot_flight_has_the_files_thermals_only():
    found, _ = h.parse(KK7)
    spots = h.HotspotSet(found)
    frame = LocalFrame(LAT, LON)
    t = 30 * 1800.0 + 900.0
    random_sky = f.ThermalField(config(range_m=13000.0), frame)
    random_sky.update(t, LAT, LON)
    hot = f.ThermalField(config(range_m=13000.0), frame, hotspots=spots)
    hot.update(t, LAT, LON)
    assert random_sky.loaded_count() > 1000
    assert 0 < hot.loaded_count() < 20
    loaded = {(th.lat, th.lon, th.birth) for th in hot.thermals()}
    fired = {(th.lat, th.lon, th.birth) for k in (1, 2) for s in (29, 30) for th in spots.generate(hot.config, k, s)}
    assert loaded == fired  # the two within reach, this slot and the one before
    # Its sink between thermals is its own: far weaker than the full random sky's.
    assert 0.0 > hot.environment_sink(800.0, 3.0, 2000.0) > 0.2 * random_sky.environment_sink(800.0, 3.0, 2000.0)


def test_a_hotspot_upwind_sends_its_thermals_down_the_wind():
    # The glider 15 km east of a hotspot in 10 m/s from the west: a thermal born there 25 min ago
    # has drifted over it, and is loaded although its hotspot is out of range.
    lat, lon = LAT, LON + 15000.0 / (111320.0 * math.cos(math.radians(LAT)))
    drift = AirDrift()
    t = 30 * 1800.0 + 1700.0
    drift.advance(10.0, 0.0, lat, t - 1.0)
    drift.advance(10.0, 0.0, lat, t)
    spots = one(1.0)
    hot = f.ThermalField(config(range_m=5000.0), LocalFrame(lat, lon), hotspots=spots,
                         air_at=drift.to_air_at, ground_at=drift.to_ground_at)
    hot.update(t, *drift.to_air(lat, lon))
    assert hot.loaded_count() > 0


def test_the_clouds_catalog_of_a_hotspot_flight_holds_the_files_thermals_only():
    from xp_gliding.engine.clouds import CloudCatalog
    found, _ = h.parse(KK7)
    spots = h.HotspotSet(found)
    frame = LocalFrame(LAT, LON)
    t = 30 * 1800.0 + 900.0
    catalog = CloudCatalog(config(), frame, hotspots=spots)
    while catalog.update(t, LAT, LON) or not catalog.started:
        pass
    assert catalog.missing == 0 and catalog.loaded_within_m(LAT, LON) == math.inf
    clouds = {(th.lat, th.lon, th.birth) for th in catalog.thermals()}
    fired = {(th.lat, th.lon, th.birth) for k in range(len(spots)) for s in (29, 30)
             for th in spots.generate(catalog.config, k, s)}
    assert clouds and clouds <= fired  # all three hotspots are within the clouds' reach
