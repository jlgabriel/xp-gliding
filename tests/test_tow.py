"""Our tow rope's adapter (`adapter/tow.py`) with stand-ins for X-Plane."""

import math

import pytest

from xp_gliding.adapter.tow import (DATAREFS, GROUND_CLEAR_M, GROUND_SLACK_M, HALF_MAX_M,
                                    NATIVE_SLACK_M, NONE, OVERLAP_M, PIECE_M, RELEASED,
                                    ROPE_LENGTH_M, SEGMENTS, TOWING, TRAIL_S, LineReading, TowRope,
                                    body_axes, to_rope)


class FakeIO:
    """A glider on the runway (local y up, z south) with the tug 50 m north, then a tow."""

    def __init__(self):
        self.paused_now = False
        self.replay = False
        self.prepared = 0
        self.hidden = []
        r = self.r = LineReading()
        r.glider = [0.0, 100.0, 0.0]
        r.aircraft = [0.0, 99.5, -2.6]
        r.tug = [0.0, 101.0, -50.0]
        r.payload = [0.0, 100.6, -45.7]
        r.agl_m = 0.5
        r.lat, r.lon = -33.45, -70.55
        r.towing = False

    def paused(self):
        return self.paused_now

    def in_replay(self):
        return self.replay

    def prepare(self):
        self.prepared += 1

    def read_line(self):
        return self.r

    def hide_native_line(self, hide):
        self.hidden.append(hide)

    def ground_y(self, x, y, z):
        return None

    def release(self):
        pass

    def move(self, dx, dy, dz, tug_too=True, line_too=True):
        r = self.r
        for p, on in ((r.glider, True), (r.aircraft, line_too), (r.tug, tug_too), (r.payload, line_too)):
            if on:
                p[0] += dx
                p[1] += dy
                p[2] += dz


class FakeObjects:
    def __init__(self, load=True):
        self.load = load
        self.created = self.destroyed = self.unloaded = 0
        self.positions = {}
        self.data = {}
        self.pending = None
        self.in_update = False  # set by the tests around update: nothing may be made there

    def load_async(self, name, loaded):
        self.pending = (name, loaded)

    def finish(self):
        name, loaded = self.pending
        loaded("obj" if self.load else None, name)

    def unload(self, obj):
        assert obj
        self.unloaded += 1

    def create(self, obj, datarefs=None):
        assert not self.in_update, "an instance made after the flight model"
        assert tuple(datarefs) == DATAREFS
        self.created += 1
        return self.created

    def destroy(self, inst):
        self.destroyed += 1
        self.positions.pop(inst, None)

    def set_position(self, inst, x, y, z, data=None, pitch=0.0, heading=0.0):
        assert data is not None and len(data) == len(DATAREFS)
        self.positions[inst] = (x, y, z, pitch, heading)
        self.data[inst] = data[0]


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def frame(tow, dt=1 / 60, enabled=True):
    """One frame as X-Plane runs it: before the flight model, then after it."""
    tow.prepare(enabled)
    tow.objects.in_update = True
    try:
        tow.update(dt, enabled)
    finally:
        tow.objects.in_update = False


def make(load=True):
    io, objects, clock, logs = FakeIO(), FakeObjects(load), Clock(), []
    tow = TowRope(io, objects, logs.append, clock=clock)
    tow.prepare(True)  # asks for the object
    objects.finish()
    return tow, io, objects, clock, logs


def run(tow, io, clock, seconds, climb_ms=0.0, speed_ms=0.0, dt=1 / 60):
    for _ in range(max(1, round(seconds / dt))):
        clock.t += dt
        io.move(0.0, climb_ms * dt, -speed_ms * dt)
        io.r.lat += speed_ms * dt / 111_195.0
        frame(tow, dt)


def test_waiting_on_the_runway_the_rope_lies_on_the_ground_and_the_native_line_is_hidden():
    tow, io, objects, clock, logs = make()
    run(tow, io, clock, 5.0)
    assert tow.state == TOWING
    assert objects.created == SEGMENTS
    assert io.hidden and all(io.hidden)
    ground = io.r.glider[1] - io.r.agl_m
    lowest = min(p[2] for p in tow.rope.nodes[1:-1])
    assert lowest == pytest.approx(ground + GROUND_CLEAR_M, abs=0.01)  # on it, not in it
    # Drawn where the rope is, in X-Plane's local frame (y up, z south).
    xs = [pos[1] for pos in objects.positions.values()]
    assert min(xs) == pytest.approx(ground + GROUND_CLEAR_M, abs=0.05)


def test_on_the_tow_and_after_release_the_rope_trails_behind_the_tug():
    tow, io, objects, clock, logs = make()
    io.r.towing = True
    io.r.agl_m = 200.0
    run(tow, io, clock, 10.0, climb_ms=3.0, speed_ms=30.0)
    assert tow.state == TOWING
    io.r.towing = False  # released: X-Plane's line freezes, the tug flies on
    run_free = 15.0
    for _ in range(int(run_free * 60)):
        clock.t += 1 / 60
        io.move(0.0, 0.0, -30.0 / 60, line_too=False)
        io.r.lat += 0.5 / 111_195.0
        frame(tow)
    assert tow.state == RELEASED
    hook = tow.rope.nodes[-1]
    tug = to_rope(*io.r.tug)
    assert math.dist(hook, tug) < 5.0  # on the tug's tail
    tail = tow.rope.nodes[0]
    assert tail[1] < hook[1] - 25.0  # behind it (north is +y here)
    assert tail[2] < hook[2] - 3.0  # and below


def test_the_trailing_rope_goes_after_a_while():
    tow, io, objects, clock, logs = make()
    io.r.towing = True
    run(tow, io, clock, 2.0)
    io.r.towing = False
    io.move(0.0, 0.0, 0.0)
    run(tow, io, clock, TRAIL_S + 1.0)
    assert tow.state == NONE
    assert objects.destroyed == SEGMENTS
    assert io.hidden[-1] is False


def test_a_new_flight_elsewhere_drops_the_rope_and_an_origin_shift_keeps_it():
    tow, io, objects, clock, logs = make()
    io.r.towing = True
    run(tow, io, clock, 2.0)
    before = [list(p) for p in tow.rope.nodes]
    io.move(5000.0, 0.0, 3000.0)  # the local origin moved; same place on the Earth
    clock.t += 1 / 60
    frame(tow)
    assert tow.state == TOWING
    moved = (before[10][0] + 5000.0, before[10][1] - 3000.0, before[10][2])
    assert math.dist(tow.rope.nodes[10], moved) < 1.0
    io.r.lat += 0.1  # 11 km away: a new flight
    clock.t += 1 / 60
    frame(tow)
    assert tow.state in (NONE, TOWING)  # dropped, and picked up again if a tow is set up there
    assert objects.destroyed == SEGMENTS


def test_switched_off_gives_the_native_line_back_and_paused_holds_still():
    tow, io, objects, clock, logs = make()
    run(tow, io, clock, 1.0)
    io.paused_now = True
    nodes = [list(p) for p in tow.rope.nodes]
    run(tow, io, clock, 1.0)
    assert [list(p) for p in tow.rope.nodes] == nodes
    io.paused_now = False
    frame(tow, enabled=False)
    assert tow.state == NONE
    assert io.hidden[-1] is False
    assert objects.destroyed == SEGMENTS


def test_an_object_that_does_not_load_leaves_the_native_line():
    tow, io, objects, clock, logs = make(load=False)
    run(tow, io, clock, 1.0)
    assert objects.created == 0
    assert io.hidden == []
    assert any("did not load" in text for text in logs)


def test_no_line_no_rope():
    tow, io, objects, clock, logs = make()
    io.r.aircraft = [0.0, 0.0, 0.0]  # X-Plane's values with no tow set up
    io.r.payload = [0.0, 0.0, 0.0]
    run(tow, io, clock, 1.0)
    assert tow.state == NONE
    assert objects.created == 0


def test_body_axes():
    right, up, forward = body_axes(0.0, 0.0, 0.0)
    assert forward == pytest.approx((0.0, 1.0, 0.0))
    assert right == pytest.approx((1.0, 0.0, 0.0))
    assert up == pytest.approx((0.0, 0.0, 1.0))
    right, up, forward = body_axes(90.0, 0.0, 90.0)  # heading east, right wing straight down
    assert forward == pytest.approx((1.0, 0.0, 0.0), abs=1e-9)
    assert right == pytest.approx((0.0, 0.0, -1.0), abs=1e-9)
    assert up == pytest.approx((0.0, -1.0, 0.0), abs=1e-9)  # the canopy faces south
    _, up, forward = body_axes(0.0, 30.0, 0.0)
    assert forward == pytest.approx((0.0, math.cos(math.radians(30)), 0.5))
    assert up[2] == pytest.approx(math.cos(math.radians(30)))


def test_the_rope_object_matches_its_generator():
    import importlib.util
    import os

    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    script = os.path.join(repo, "tools", "make_rope_obj.py")
    spec = importlib.util.spec_from_file_location("make_rope_obj", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    folder = os.path.join(repo, "xp_gliding", "assets", "rope")
    files = module.outputs()
    assert sorted(os.listdir(folder)) == sorted(files)
    for name, data in files.items():
        with open(os.path.join(folder, name), "rb") as f:
            assert f.read() == data, name


def test_on_the_tow_the_drawn_rope_hangs_and_hangs_less_as_the_native_one_stretches():
    sags = []
    for span in (56.1, 56.8, 57.5):
        tow, io, objects, clock, logs = make()
        io.r.towing = True
        io.r.agl_m = 300.0
        io.r.aircraft = [0.0, 400.0, -2.6]
        io.r.payload = [0.0, 400.0, -2.6 - span]
        io.r.glider = [0.0, 400.6, 0.0]
        run(tow, io, clock, 20.0)
        sags.append(tow.status.sag_m)
    assert 1.5 < sags[0] < 5.0
    assert sags[1] < sags[0]
    assert sags[2] < 0.05  # past its length it is straight


def test_the_length_can_be_tuned_within_limits():
    tow, io, objects, clock, logs = make()
    tow.length_m = 100.0
    assert tow.length_m == 62.0
    tow.length_m = 10.0
    assert tow.length_m == 53.0
    tow.length_m = float("nan")
    assert tow.length_m == 53.0


def test_with_the_tug_well_above_the_rope_still_hangs_down():
    tow, io, objects, clock, logs = make()
    rope = tow.rope
    rope.length_m, rope.rest_m = ROPE_LENGTH_M, ROPE_LENGTH_M / rope.segments  # the length in the air
    span, dz = 56.5, 30.0
    dy = math.sqrt(span ** 2 - dz ** 2)
    rope.reset((0.0, 0.0, 500.0), (0.0, dy, 500.0 + dz))
    for k in range(1200):
        s = 25.0 * (k + 1) / 60  # both fly on at 25 m/s
        rope.step(1 / 60, (0.0, s, 500.0), (0.0, dy + s, 500.0 + dz), rho=1.1)
    a, b, middle = rope.nodes[0], rope.nodes[-1], rope.nodes[len(rope.nodes) // 2]
    assert middle[2] < (a[2] + b[2]) / 2 - 1.0


def test_on_the_runway_the_rope_is_as_long_as_the_hooks_are_apart_and_pays_out():
    tow, io, objects, clock, logs = make()
    hooks = math.dist(io.r.aircraft, io.r.payload)  # 43.1 m: the tug nearer than 53 m
    run(tow, io, clock, 2.0)
    assert tow.state == TOWING
    assert tow.rope.length_m == pytest.approx(hooks + GROUND_SLACK_M)
    assert tow.status.sag_m < 1.5  # nearly straight, not the wide arc of a 53 m rope
    # The tug takes up the slack: the rope pays out with it, up to the native rope's length.
    for _ in range(4 * 60):
        clock.t += 1 / 60
        io.r.tug[2] -= 3.0 / 60
        io.r.payload[2] -= 3.0 / 60
        frame(tow)
    assert tow.rope.length_m == NATIVE_SLACK_M
    assert tow.status.sag_m < 0.05


def test_on_the_ground_roll_the_rope_is_the_native_length_and_grows_after_lift_off():
    tow, io, objects, clock, logs = make()
    io.r.towing = True
    io.r.payload[2] = io.r.aircraft[2] - 55.0  # the native rope pulling
    io.r.tug[2] = io.r.payload[2] - 4.3
    run(tow, io, clock, 2.0)
    assert tow.rope.length_m == NATIVE_SLACK_M
    io.r.agl_m = 20.0
    run(tow, io, clock, 5.0)
    assert NATIVE_SLACK_M < tow.rope.length_m < ROPE_LENGTH_M
    run(tow, io, clock, 10.0)
    assert tow.rope.length_m == ROPE_LENGTH_M


class SlopedIO(FakeIO):
    """A runway that the probe reads 3 cm higher every second, as uneven ground under a moving
    rope would."""

    def __init__(self):
        super().__init__()
        self.ground = 99.4
        self.probes = 0

    def ground_y(self, x, y, z):
        self.probes += 1
        self.ground += 0.015
        return self.ground


def test_a_rope_lying_on_the_runway_does_not_bounce():
    io, objects, clock = SlopedIO(), FakeObjects(), Clock()
    tow = TowRope(io, objects, lambda text: None, clock=clock)
    tow.prepare(True)
    objects.finish()
    run(tow, io, clock, 3.0)
    fastest_up = 0.0
    third = SEGMENTS // 3
    for _ in range(int(10 * 60)):
        clock.t += 1 / 60
        before = [p[2] for p in tow.rope.nodes]
        frame(tow)
        ups = [(p[2] - b) * 60 for p, b in zip(tow.rope.nodes[third:-third], before[third:-third])]
        fastest_up = max(fastest_up, max(ups))
    assert io.probes >= 10
    # Lifted only as fast as the floor eases (FLOOR_RATE_MS), never thrown up by a floor that
    # jumped with each probe.
    assert fastest_up < 0.6


def test_in_a_replay_ours_goes_and_the_native_line_comes_back():
    tow, io, objects, clock, logs = make()
    io.r.towing = True
    io.r.agl_m = 200.0
    run(tow, io, clock, 2.0, climb_ms=3.0, speed_ms=30.0)
    assert tow.state == TOWING and objects.created == SEGMENTS
    io.replay = True
    run(tow, io, clock, 1.0, speed_ms=30.0)  # the aircraft move in the replay
    assert tow.state == NONE
    assert objects.destroyed == SEGMENTS
    assert io.hidden[-1] is False
    io.replay = False  # back to the flight, still on the tow
    run(tow, io, clock, 1.0, climb_ms=3.0, speed_ms=30.0)
    assert tow.state == TOWING
    assert objects.created == 2 * SEGMENTS
    assert io.hidden[-1] is True


def test_a_restart_near_where_the_tow_ended_starts_without_the_old_rope():
    tow, io, objects, clock, logs = make()
    io.r.towing = True
    run(tow, io, clock, 2.0)
    io.r.towing = False  # released on the runway, the tug rolls on
    for _ in range(60):
        clock.t += 1 / 60
        io.move(0.0, 0.0, -10.0 / 60, line_too=False)
        frame(tow)
    assert tow.state == RELEASED
    tow.new_flight()  # X-Plane says: a new flight; the glider starts where it was
    assert tow.state == NONE
    assert objects.destroyed == SEGMENTS
    assert io.hidden[-1] is False
    io.r.payload = [0.0, 100.6, -48.0]  # the new tug's tail, the line there before the tow
    io.r.tug = [0.0, 101.0, -52.3]
    run(tow, io, clock, 1.0)
    assert tow.state == TOWING
    assert tow.rope.pinned_a and math.dist(tow.rope.nodes[0], to_rope(*io.r.aircraft)) < 0.01


def test_a_line_set_up_again_where_the_rope_is_lays_the_rope_out_afresh():
    tow, io, objects, clock, logs = make()
    run(tow, io, clock, 1.0)
    io.r.payload = [30.0, 100.6, -40.0]  # the tug's end 30 m to one side in one frame
    io.r.tug = [30.0, 101.0, -44.3]
    run(tow, io, clock, 1 / 60)
    assert tow.state == TOWING
    b = to_rope(*io.r.payload)
    assert math.dist(tow.rope.nodes[-1], b) < 0.01
    # Laid out between the new ends at once, not dragged across.
    assert max(math.dist(p, b) for p in tow.rope.nodes) < tow.rope.length_m + 0.5


def test_each_segment_is_drawn_at_its_length():
    tow, io, objects, clock, logs = make()
    io.r.towing = True
    io.r.agl_m = 300.0
    io.r.aircraft = [0.0, 400.0, -2.6]
    io.r.payload = [0.0, 400.0, -2.6 - 64.0]  # stretched past the drawn 57 m
    io.r.glider = [0.0, 400.6, 0.0]
    run(tow, io, clock, 2.0)
    poses = tow.rope.segment_poses()
    for inst, pose in zip(tow.instances, poses):
        assert objects.data[inst] == pytest.approx(pose[3] / 2)
    assert all(pose[3] == pytest.approx(64.0 / SEGMENTS) for pose in poses)
    # Lengths the object draws whole, without a gap or a piece past a joint: a stretched rope,
    # a short one on the runway, and the longest the dataref allows, shortened or stretched.
    assert PIECE_M - 2 * OVERLAP_M < 64.0 / SEGMENTS < 2 * (PIECE_M - OVERLAP_M)
    assert PIECE_M - 2 * OVERLAP_M < 0.97 * 36.0 / SEGMENTS
    assert 2 * (PIECE_M - OVERLAP_M) > 1.08 * 62.0 / SEGMENTS
    assert HALF_MAX_M > PIECE_M


def test_instances_are_made_before_the_flight_model():
    tow, io, objects, clock, logs = make()
    frame(tow)  # the first frame of a rope: none yet, X-Plane's line still shows
    assert tow.state == TOWING and objects.created == 0 and not any(io.hidden)
    frame(tow)
    assert objects.created == SEGMENTS and io.hidden[-1] is True
    assert io.prepared >= 2


def test_an_object_that_did_not_load_is_not_unloaded():
    tow, io, objects, clock, logs = make(load=False)
    tow.shutdown()
    assert objects.unloaded == 0
    tow, io, objects, clock, logs = make()
    tow.shutdown()
    assert objects.unloaded == 1
