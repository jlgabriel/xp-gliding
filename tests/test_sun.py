import pytest

from xp_gliding.engine import field as f
from xp_gliding.engine import sun
from xp_gliding.engine.clouds import CloudCatalog, CloudParams
from xp_gliding.engine.geo import LocalFrame
from xp_gliding.engine.markers import select_markers

WSTAR, ZI = 3.0, 2000.0
LAT, LON = -33.45, -70.67  # Santiago
SOLSTICE = 354  # 21 December, days since 1 January
H = 3600.0


def crossing(lat, lon, day, start_s, end_s, deg, step_s=10.0):
    """First time in [start_s, end_s) the sun crosses `deg`, either way."""
    t = start_s
    above = sun.sun_elevation_deg(lat, lon, day, t) >= deg
    while t < end_s:
        t += step_s
        if (sun.sun_elevation_deg(lat, lon, day, t) >= deg) != above:
            return t
    raise AssertionError("no crossing")


def test_the_sun_at_known_places_and_times():
    # Santiago at the December solstice: 90 - (33.45 - 23.44) at solar noon, about 16:40 UTC.
    highest = max(sun.sun_elevation_deg(LAT, LON, SOLSTICE, s) for s in range(0, 86400, 60))
    assert highest == pytest.approx(80.0, abs=0.5)
    noon = max(range(0, 86400, 60), key=lambda s: sun.sun_elevation_deg(LAT, LON, SOLSTICE, s))
    assert noon / H == pytest.approx(16.7, abs=0.1)
    # The equator at the March equinox: the sun rises at about 06:00 solar time.
    assert sun.sun_elevation_deg(0.0, 0.0, 79, 6 * H) == pytest.approx(0.0, abs=2.5)
    assert sun.sun_elevation_deg(0.0, 0.0, 79, 12 * H) > 85.0
    # Midnight is dark at mid latitudes, and the sun is up all day at the pole in its summer.
    assert sun.sun_elevation_deg(LAT, LON, SOLSTICE, 16.7 * H + 12 * H) < -20.0
    assert min(sun.sun_elevation_deg(-89.0, 0.0, SOLSTICE, s) for s in range(0, 86400, 600)) > 20.0


def test_the_field_time_may_run_past_a_day_or_start_below_zero():
    # t is seconds from 00:00 UTC of the local date, unwrapped (field.sky_time).
    assert sun.sun_elevation_deg(LAT, LON, SOLSTICE, 25 * H) == pytest.approx(
        sun.sun_elevation_deg(LAT, LON, SOLSTICE + 1, 1 * H), abs=1e-9)
    assert sun.sun_elevation_deg(LAT, LON, SOLSTICE, -1 * H) == pytest.approx(
        sun.sun_elevation_deg(LAT, LON, SOLSTICE - 1, 23 * H), abs=1e-9)


def make_field(t, sun_min_deg=sun.SUN_MIN_DEG, range_m=6000.0):
    config = f.FieldConfig(seed=3, day=SOLSTICE, range_m=range_m, sky=f.sky_named("wide_carriers"),
                           sun_min_deg=sun_min_deg)
    field = f.ThermalField(config, LocalFrame(LAT, LON))
    field.update(t, LAT, LON)
    return field


def signature(thermals):
    return sorted((round(th.lat, 9), round(th.lon, 9), round(th.birth, 3), round(th.wgain, 9))
                  for th in thermals)


def test_by_day_the_sun_changes_nothing():
    t = 17 * H
    with_sun, without = make_field(t), make_field(t, sun_min_deg=None)
    assert signature(with_sun.thermals()) == signature(without.thermals())
    assert with_sun.sink_share == 1.0
    for e in (-2000.0, 0.0, 1500.0):
        assert with_sun.lift_at(e, 300.0, 900.0, t, WSTAR, ZI) == without.lift_at(e, 300.0, 900.0, t, WSTAR, ZI)


def test_at_night_there_is_no_thermal_and_no_sink():
    t = 4 * H  # 01:00 local
    field = make_field(t)
    assert list(field.thermals()) == []
    assert field.sink_share == 0.0
    assert field.lift_at(0.0, 0.0, 800.0, t, WSTAR, ZI) == 0.0
    assert select_markers(field, 0.0, 0.0, 800.0, t, WSTAR, ZI) == []


def test_the_sun_keeps_some_thermals_and_shifts_none():
    # Around sunset: those kept are the same thermals, with the same numbers, as with no sun.
    t = crossing(LAT, LON, SOLSTICE, 18 * H, 30 * H, sun.SUN_MIN_DEG)
    with_sun, without = make_field(t), make_field(t, sun_min_deg=None)
    kept = signature(with_sun.thermals())
    assert 0 < len(kept) < len(list(without.thermals()))
    assert set(kept) <= set(signature(without.thermals()))
    assert all(sun.sunlit(th.lat, th.lon, SOLSTICE, th.birth) for th in with_sun.thermals())


def test_the_sky_fades_out_after_sunset_and_back_in_after_sunrise():
    last_birth = crossing(LAT, LON, SOLSTICE, 18 * H, 30 * H, sun.SUN_MIN_DEG)
    first_birth = crossing(LAT, LON, SOLSTICE, 30 * H, 44 * H, sun.SUN_MIN_DEG) - 24 * H
    field = make_field(last_birth, range_m=10000.0)
    alive, shares = [], []
    for minutes in range(-10, 40, 5):
        t = last_birth + minutes * 60.0
        field.update(t, LAT, LON)
        alive.append(len(field.alive(t)))
        shares.append(field.sink_share)
    # From the last birth, fewer thermals minute by minute, none half an hour later, and the
    # sink with them.
    assert alive[0] > 50 and alive[-1] == 0
    after = alive[2:]
    assert all(b <= a for a, b in zip(after, after[1:]))
    assert shares[0] == 1.0 and shares[-1] == 0.0
    assert all(b <= a for a, b in zip(shares, shares[1:]))
    # In the morning the same the other way.
    field = make_field(first_birth - 60.0, range_m=10000.0)
    assert field.alive(first_birth - 60.0) == [] and field.sink_share == 0.0
    t = first_birth + 45 * 60.0
    field.update(t, LAT, LON)
    assert len(field.alive(t)) > 50 and field.sink_share == 1.0


def test_the_share_follows_the_thermals_kept():
    # The sink between thermals is their flux coming down: its share is the flux alive.
    t = crossing(LAT, LON, SOLSTICE, 18 * H, 30 * H, sun.SUN_MIN_DEG) + 10 * 60.0
    with_sun, without = make_field(t, range_m=15000.0), make_field(t, sun_min_deg=None, range_m=15000.0)

    def flux(field):
        return sum(f.envelope_flux((t - th.birth) / (th.death - th.birth)) for th in field.alive(t))

    assert with_sun.sink_share == pytest.approx(flux(with_sun) / flux(without), abs=0.08)


def test_the_share_is_one_all_day_long():
    share = sun.ThermalShare(300.0, 1800.0, f.envelope_flux)
    assert share.at(LAT, LON, SOLSTICE, 17 * H) == 1.0
    assert share.at(LAT, LON, SOLSTICE, 4 * H) == 0.0


def test_clouds_come_from_the_thermals_the_sun_lets_be_born():
    t = 4 * H
    config = make_field(t).config
    catalog = CloudCatalog(config, LocalFrame(LAT, LON), CloudParams(tiles_per_update=1000))
    assert catalog.config.sun_min_deg == sun.SUN_MIN_DEG
    for _ in range(5):
        catalog.update(t, LAT, LON)
    assert list(catalog.thermals()) == []
    by_day = CloudCatalog(make_field(17 * H).config, LocalFrame(LAT, LON), CloudParams(tiles_per_update=1000))
    for _ in range(5):
        by_day.update(17 * H, LAT, LON)
    assert list(by_day.thermals())
