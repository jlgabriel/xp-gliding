"""The daily cycle (engine/daycycle.py) and the solar time it rests on (engine/sun.py)."""

import pytest

from xp_gliding.engine import sun
from xp_gliding.engine.daycycle import DayCycle

HOBBS = (32.69, -103.22)
SANTIAGO = (-33.46, -70.55)
NOV_2, NOV_9, JUN_22 = 305, 312, 172


def solar(lon, day, hour):
    """The field's t at this solar hour of the solar day whose noon is nearest 12:00 UTC of `day`."""
    return sun.utc_for_solar(lon, day, 43200.0) + (hour - 12.0) * 3600.0


def at_solar(cycle, place, hour, what="strength"):
    lat, lon = place
    t = solar(lon, cycle.day, hour)
    if what == "strength":
        return cycle.strength_share(lat, lon, t)
    return cycle.depth_share(lat, lon, t)


@pytest.mark.parametrize("lon", [-103.22, -70.55, 0.0, 151.2])
@pytest.mark.parametrize("hour", [3.0, 9.5, 12.0, 17.25])
def test_utc_for_solar_inverts_solar_time(lon, hour):
    t = sun.utc_for_solar(lon, NOV_2, hour * 3600.0)
    assert sun.solar_time_s(lon, NOV_2, t) == pytest.approx(hour * 3600.0, abs=1.0)
    assert abs(t - 43200.0) <= 43200.0


def test_the_sun_is_highest_at_solar_noon():
    lat, lon = HOBBS
    noon = sun.utc_for_solar(lon, NOV_2, 43200.0)
    high = sun.sun_elevation_deg(lat, lon, NOV_2, noon)
    for d in (-1800.0, 1800.0):
        assert sun.sun_elevation_deg(lat, lon, NOV_2, noon + d) < high


@pytest.mark.parametrize("place, day", [(HOBBS, NOV_2), (SANTIAGO, NOV_9), (HOBBS, JUN_22)])
def test_strength_is_a_share_of_the_peak(place, day):
    cycle = DayCycle(day)
    values = [at_solar(cycle, place, h / 4.0) for h in range(96)]
    assert all(0.0 <= v <= 1.0 for v in values)
    assert max(values) == pytest.approx(1.0, abs=0.01)
    assert at_solar(cycle, place, 3.0) == 0.0  # night
    assert at_solar(cycle, place, 22.0) == 0.0


@pytest.mark.parametrize("place, day", [(HOBBS, NOV_2), (SANTIAGO, NOV_9), (HOBBS, JUN_22)])
def test_peak_comes_after_noon(place, day):
    cycle = DayCycle(day)
    hours = [h / 12.0 for h in range(6 * 12, 20 * 12)]
    best = max(hours, key=lambda h: at_solar(cycle, place, h))
    assert 12.5 <= best <= 14.0


def test_strength_rises_through_the_morning_and_falls_in_the_evening():
    cycle = DayCycle(NOV_2)
    morning = [at_solar(cycle, HOBBS, h / 2.0) for h in range(16, 26)]  # 08:00-12:30
    evening = [at_solar(cycle, HOBBS, h / 2.0) for h in range(28, 34)]  # 14:00-16:30
    assert all(b > a for a, b in zip(morning, morning[1:]))
    assert all(b < a for a, b in zip(evening, evening[1:]))


def test_the_numbers_in_the_notes():
    """The shares worked out offline when the daily cycle was designed: Hobbs, 2 November."""
    cycle = DayCycle(NOV_2)
    for hour, share in ((8.0, 0.29), (10.0, 0.76), (12.0, 0.97), (13.0, 1.00), (16.0, 0.63)):
        assert at_solar(cycle, HOBBS, hour) == pytest.approx(share, abs=0.03)
    assert at_solar(cycle, HOBBS, 17.0) == 0.0


def test_depth_grows_to_the_afternoon_and_stays():
    cycle = DayCycle(NOV_2)
    depths = [at_solar(cycle, HOBBS, h / 2.0, "depth") for h in range(12, 40)]  # 06:00-19:30
    assert depths[0] == 0.0
    assert all(b >= a for a, b in zip(depths, depths[1:]))
    assert at_solar(cycle, HOBBS, 15.0, "depth") == pytest.approx(1.0, abs=0.01)
    assert at_solar(cycle, HOBBS, 19.0, "depth") == 1.0


def test_morning_is_blue_until_zi_reaches_the_base():
    cycle = DayCycle(NOV_2)
    lat, lon = HOBBS
    early = solar(lon, NOV_2, 9.0)
    late = solar(lon, NOV_2, 14.0)
    assert cycle.blue(lat, lon, early)
    assert not cycle.blue(lat, lon, late)


def test_no_thermals_when_the_sun_never_gets_high():
    cycle = DayCycle(355)  # 21 December, 75 degrees north: the sun stays under 10 degrees
    assert max(at_solar(cycle, (75.0, 15.0), h / 2.0) for h in range(48)) == 0.0


def test_same_inputs_same_sky():
    lat, lon = SANTIAGO
    t = solar(lon, NOV_9, 10.5)
    a = DayCycle(NOV_9).strength_share(lat, lon, t)
    b = DayCycle(NOV_9).strength_share(lat, lon, t)
    assert a == b


def test_tables_are_kept_and_bounded():
    cycle = DayCycle(NOV_2)
    lat, lon = HOBBS
    t = solar(lon, NOV_2, 11.0)
    for k in range(40):  # a glider crossing many cells
        cycle.strength_share(lat + 0.1 * k, lon, t)
    assert len(cycle._days) <= 8
    # Within one solar day and one cell, one table.
    fresh = DayCycle(NOV_2)
    for h in range(6, 20):
        fresh.strength_share(lat, lon, solar(lon, NOV_2, h))
    assert len(fresh._days) == 1


# --- wired into the field and the clouds ---------------------------------------------------------

def _catalog_at(hour, sky="wide_carriers"):
    from xp_gliding.engine.clouds import CloudCatalog
    from xp_gliding.engine.field import SKIES, FieldConfig
    from xp_gliding.engine.geo import LocalFrame
    lat, lon = HOBBS
    t = solar(lon, NOV_2, hour)
    config = FieldConfig(seed=1, day=NOV_2, range_m=6000.0, sky=SKIES[sky], sun_min_deg=sun.SUN_MIN_DEG)
    catalog = CloudCatalog(config, LocalFrame(lat, lon))
    for _ in range(500):
        if not catalog.update(t, lat, lon) and catalog.started:
            break
    return catalog, t


def test_the_morning_has_no_clouds_and_the_afternoon_has():
    morning, t_morning = _catalog_at(10.0)
    afternoon, t_afternoon = _catalog_at(14.5)
    assert not [th for th in morning.thermals() if th.birth <= t_morning < th.death]
    assert [th for th in afternoon.thermals() if th.birth <= t_afternoon < th.death]


def test_the_field_owns_the_cycle_only_with_the_sun():
    from xp_gliding.engine.field import FieldConfig, ThermalField
    from xp_gliding.engine.geo import LocalFrame
    frame = LocalFrame(*HOBBS)
    with_sun = ThermalField(FieldConfig(day=NOV_2, sun_min_deg=sun.SUN_MIN_DEG), frame)
    without = ThermalField(FieldConfig(day=NOV_2), frame)
    assert with_sun.cycle is not None and with_sun.cycle.onset_deg == sun.SUN_MIN_DEG
    assert without.cycle is None


def test_the_day_does_not_depend_on_the_time_it_was_first_asked_for():
    # The field and the clouds ask at different times and must agree to the last bit.
    lat, lon = HOBBS
    answers = set()
    for first in (25000.0, 50000.0, 70000.0, 95000.0):
        cycle = DayCycle(NOV_2)
        cycle.depth_share(lat, lon, first)
        answers.add(tuple((cycle.depth_share(lat, lon, t), cycle.strength_share(lat, lon, t))
                          for t in (solar(lon, NOV_2, h / 2.0) for h in range(14, 36))))
    assert len(answers) == 1
