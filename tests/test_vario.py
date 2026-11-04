"""The soaring instruments, against known energy and against the engine's own profile."""

import math

import pytest

from xp_gliding.adapter.vario import (ASK21_LAMINAR, G, SAMPLE_PERIOD_S, CentringAid, Vario,
                                      height_to_top, polar_for)
from xp_gliding.engine import updraft

DT = SAMPLE_PERIOD_S


def fly(vario, seconds, climb_ms, tas_ms=25.0, ias_kmh=90.0, bank_deg=0.0, mass_kg=541.0,
        t0=100.0, z0=1000.0, tas_of_t=None):
    t = t0
    for i in range(int(seconds / DT)):
        t = t0 + i * DT
        tas = tas_of_t(t - t0) if tas_of_t else tas_ms
        # The aircraft's total energy rises at climb_ms; the height is what is left of it.
        z = z0 + climb_ms * (t - t0) - tas * tas / (2 * G)
        vario.update(t, z, tas, ias_kmh, bank_deg, mass_kg)
    return t


def test_polar_reproduces_the_measured_sinks():
    sink = ASK21_LAMINAR.sink
    assert sink(90.0, 25.0, 0.0, 541.0) == pytest.approx(0.86)
    assert sink(120.0, 120.0 / 3.6, 0.0, 541.0) == pytest.approx(1.11)
    # The reference circle of the orbits: 46 degrees, 93 km/h, TAS 11% over IAS (phase 1).
    assert sink(93.0, 93.0 / 3.6 * 1.11, 46.0, 541.0) == pytest.approx(2.02, abs=0.1)
    # 35 degrees at 90 km/h and 2700 m MSL sinks 1.54 m/s (phase 1).
    assert sink(90.0, 25.0 * 1.15, 35.0, 541.0) == pytest.approx(1.54, abs=0.1)


def test_polar_scales_with_mass():
    # Heavier by 1.21: same polar shape, speed and sink both 1.1 times.
    light = ASK21_LAMINAR.sink(100.0, 100.0 / 3.6, 0.0, 541.0)
    heavy = ASK21_LAMINAR.sink(110.0, 110.0 / 3.6, 0.0, 541.0 * 1.21)
    assert heavy == pytest.approx(1.1 * light)


def test_polar_is_only_known_for_the_laminar_ask21():
    assert polar_for(r"D:\X-Plane 12/Aircraft/Laminar Research/Schleicher ASK 21/ASK21.acf")
    assert polar_for("D:/X-Plane 12/Aircraft/Other/ASK21/ASK21.acf") is None
    assert polar_for("") is None


def test_te_reads_the_energy_rate_and_ignores_stick_thermals():
    vario = Vario(ASK21_LAMINAR)
    # A speed change trades height for speed: total energy does not see it.
    fly(vario, 40.0, 1.5, tas_of_t=lambda s: 25.0 + 4.0 * math.sin(s / 3.0))
    assert vario.te_ms == pytest.approx(1.5, abs=0.02)


def test_netto_is_the_air_when_the_climb_is_air_minus_sink():
    vario = Vario(ASK21_LAMINAR)
    sink = ASK21_LAMINAR.sink(90.0, 25.0, 40.0, 541.0)
    fly(vario, 40.0, 2.0 - sink, bank_deg=40.0)
    assert vario.te_ms == pytest.approx(2.0 - sink, abs=0.01)
    assert vario.netto_ms == pytest.approx(2.0, abs=0.01)


def test_no_polar_no_netto():
    vario = Vario(None)
    fly(vario, 5.0, -1.0)
    assert not vario.has_netto
    assert vario.netto_ms == pytest.approx(vario.te_ms)


def test_average_is_the_energy_difference_over_the_window():
    vario = Vario(None, average_s=30.0)
    t = fly(vario, 60.0, -1.0)
    fly(vario, 15.0, 3.0, t0=t + DT, z0=1000.0 - 60.0)
    # Half the window at +3, half at -1 (the sixty seconds before).
    assert vario.average_ms == pytest.approx(1.0, abs=0.15)


def test_a_teleport_resets_instead_of_reading_as_lift():
    vario = Vario(ASK21_LAMINAR)
    t = fly(vario, 10.0, -1.0)
    assert vario.update(t + DT, 5000.0, 25.0, 90.0, 0.0, 541.0) is False
    assert not vario.valid
    assert vario.te_ms == 0.0
    fly(vario, 5.0, -1.0, t0=t + 2 * DT, z0=5000.0)
    assert vario.te_ms == pytest.approx(-1.0, abs=0.05)


def test_a_paused_clock_is_ignored():
    vario = Vario(None)
    t = fly(vario, 5.0, -1.0)
    te = vario.te_ms
    assert vario.update(t, 900.0, 25.0, 90.0, 0.0, 541.0) is False
    assert vario.te_ms == te


def circle_lift(offset_m, az_deg, radius_m, right, seconds=90.0, z=800.0, zi=2000.0, wstar=3.0,
                tau=1.0):
    """Fly a circle whose centre is offset_m from the core towards az_deg's opposite.

    The core is at azimuth az_deg from the circle's centre. Returns the aid after
    being fed the engine's own profile through a vario-like filter.
    """
    east = offset_m * math.sin(math.radians(az_deg))
    north = offset_m * math.cos(math.radians(az_deg))
    we = updraft.environment_sink(z, zi, wstar, 4.5e-6)
    speed, aid = 25.0, CentringAid(lag_s=tau)
    rate = (speed / radius_m) * (1 if right else -1)
    lift = None
    for i in range(int(seconds / DT)):
        t = i * DT
        psi = rate * t  # heading, radians, clockwise from north
        # Turning right the centre is 90 degrees right of the heading.
        side = psi + (-math.pi / 2 if right else math.pi / 2)
        e, n = radius_m * math.sin(side), radius_m * math.cos(side)
        w = updraft.updraft_velocity(math.hypot(e - east, n - north), z, zi, wstar, 1.0, 1.0, we)
        lift = w if lift is None else lift + (1 - math.exp(-DT / tau)) * (w - lift)
        aid.update(t, math.degrees(psi) % 360.0, 40.0 if right else -40.0, lift)
    aid.solve()
    return aid


@pytest.mark.parametrize("right", [True, False])
@pytest.mark.parametrize("az_deg", [0.0, 77.0, 200.0, 310.0])
def test_centring_aid_points_at_the_core(az_deg, right):
    aid = circle_lift(60.0, az_deg, 90.0, right)
    assert aid.valid
    assert aid.turning == (1 if right else -1)
    error = (aid.core_az_deg - az_deg + 180.0) % 360.0 - 180.0
    assert abs(error) < 15.0
    assert aid.amp_ms > 0.3


def test_centring_aid_says_little_when_centred():
    centred = circle_lift(0.0, 0.0, 90.0, True)
    off = circle_lift(60.0, 0.0, 90.0, True)
    assert centred.valid
    assert centred.amp_ms < 0.05
    assert off.amp_ms > 10 * centred.amp_ms


def test_centring_aid_needs_a_whole_turn_and_a_turn():
    aid = CentringAid()
    for i in range(100):  # ten seconds of a 25-second turn
        aid.update(i * DT, (14.4 * i * DT) % 360.0, 40.0, 1.0)
    aid.solve()
    assert aid.turning == 1
    assert not aid.valid
    level = CentringAid()
    for i in range(600):
        level.update(i * DT, 90.0, 2.0, 1.0)
    level.solve()
    assert level.turning == 0
    assert not level.valid


def test_height_to_top_matches_where_the_engine_stops_the_mean_updraft():
    assert height_to_top(2000.0, 1000.0) == pytest.approx(2000.0 / 1.1 - 1000.0)
    assert updraft.mean_updraft(1.0 / 1.1, 3.0) == pytest.approx(0.0, abs=0.01)
    assert height_to_top(2000.0, 1900.0) < 0.0
