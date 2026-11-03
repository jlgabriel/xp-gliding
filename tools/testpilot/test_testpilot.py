"""The test pilot's control laws flying the offline glider model.

The controller runs at 10 Hz on values one sample old, like the web API's
WebSocket pushes, while the model integrates at 200 Hz.
"""

import math
import statistics

from control import Circle, Gains, HeadingHold, LineHold, SpeedHold, wrap180
from glider_model import GliderModel

DT_MODEL = 0.005
DT_CTRL = 0.1


def fly(target_kmh, seconds, model=None, gains=None, disturb=None, guidance=None):
    """Trace rows: t, IAS, bank, pitch yoke, roll yoke, vs, track, east, north."""
    m = model or GliderModel()
    ctrl = SpeedHold(target_kmh, m.theta_deg(), gains, start_kmh=m.ias_kmh())
    trace = []

    def sample():
        return (m.ias_kmh(), m.theta_deg(), m.q_dps(), m.phi_deg(), m.p_dps(),
                m.track_deg(), m.east, m.north)

    stale = sample()
    steps_per_ctrl = round(DT_CTRL / DT_MODEL)
    for k in range(round(seconds / DT_CTRL)):
        if guidance:
            ctrl.phi_cmd = guidance.bank(*stale[5:])
        pitch, roll, _ = ctrl.step(DT_CTRL, *stale[:5])
        m.yoke_pitch, m.yoke_roll = pitch, roll
        stale = sample()
        for _ in range(steps_per_ctrl):
            if disturb:
                disturb(m, k * DT_CTRL)
            m.step(DT_MODEL)
        trace.append((k * DT_CTRL, m.ias_kmh(), m.phi_deg(), pitch, roll, m.vs_ms(),
                      m.track_deg(), m.east, m.north))
    return trace


def window(trace, t0, t1, col):
    return [row[col] for row in trace if t0 <= row[0] < t1]


def test_model_is_trimmed_and_glides_like_an_ask21():
    m = GliderModel()
    for _ in range(round(20 / DT_MODEL)):
        m.step(DT_MODEL)
    assert abs(m.ias_kmh() - 85.0) < 0.5
    glide = m.v * math.cos(m.gamma) / -m.vs_ms()
    assert 28 < glide < 34


def test_holds_90_kmh_from_trim():
    trace = fly(90.0, 90.0)
    ias = window(trace, 50, 90, 1)
    assert abs(statistics.fmean(ias) - 90.0) < 0.5
    assert max(abs(v - 90.0) for v in ias) < 1.5
    assert max(abs(v) for v in window(trace, 0, 90, 2)) < 1.0


def test_reaches_120_and_70_kmh():
    for target in (120.0, 70.0):
        ias = window(fly(target, 120.0), 80, 120, 1)
        assert abs(statistics.fmean(ias) - target) < 0.5, target
        assert statistics.pstdev(ias) < 0.5, target


def test_levels_the_wings():
    m = GliderModel()
    m.phi = math.radians(15.0)
    trace = fly(85.0, 30.0, model=m)
    assert max(abs(v) for v in window(trace, 15, 30, 2)) < 0.5


def test_rejects_a_gust():
    def gust(m, t):
        if 40.0 <= t < 41.0:
            m.q += math.radians(4.0) * DT_MODEL  # sharp nose-up pitch disturbance

    ias = window(fly(90.0, 120.0, disturb=gust), 90, 120, 1)
    assert abs(statistics.fmean(ias) - 90.0) < 0.5


def test_yoke_stays_inside_limits():
    g = Gains()
    trace = fly(140.0, 60.0, gains=g)
    assert max(abs(row[3]) for row in trace) <= g.pitch_limit
    assert max(abs(row[4]) for row in trace) <= g.roll_limit


def test_turns_to_a_heading_and_holds_it():
    trace = fly(90.0, 90.0, guidance=HeadingHold(120.0))
    assert max(abs(v) for v in window(trace, 0, 90, 2)) < 25.0
    assert max(abs(wrap180(v - 120.0)) for v in window(trace, 50, 90, 6)) < 1.0


def test_follows_a_line_in_a_crosswind():
    m = GliderModel()
    m.wind_en = (0.0, -8.0)  # 8 m/s from the north, across an eastbound line
    line = LineHold((0.0, 300.0), (5000.0, 300.0))
    trace = fly(90.0, 150.0, model=m, guidance=line)
    cross = [line.along_cross(e, n)[1] for e, n in zip(window(trace, 90, 150, 7),
                                                        window(trace, 90, 150, 8))]
    assert max(abs(c) for c in cross) < 15.0


def test_circles_at_a_steady_bank_and_speed():
    trace = fly(90.0, 120.0, guidance=Circle(-35.0))
    bank = window(trace, 60, 120, 2)
    assert abs(statistics.fmean(bank) + 35.0) < 1.0
    assert abs(statistics.fmean(window(trace, 60, 120, 1)) - 90.0) < 1.0
