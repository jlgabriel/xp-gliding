"""Our tow rope, drawn over X-Plane's native aerotow in place of its straight line.

X-Plane's aerotow pulls the glider by its own rope model and draws the rope as a straight line,
whatever it is doing. This draws a rope that hangs, lies on the runway before the roll, bows
when slack and trails behind the tug after release (`engine/rope.py`), and hides the native
line while it does (`sim/graphics/misc/kill_tow_lines`, made for this). It changes nothing in
how the tow flies: the force is still X-Plane's.

Measured in X-Plane 12.4.4 (2026-11-21, ASK 21 behind the PA-18 at Tobalaba):
- `line_aircraft_xyz` and `line_payload_xyz` are the line's ends in X-Plane's local frame:
  the glider's nose hook (2.6 m ahead of its reference point) and the tug's tail (4.3 m behind
  its). They are there before the tow starts, with the glider waiting on the runway.
- The native rope starts pulling at about 53 m between its ends and stretches like a bungee,
  1.5 mm per newton: 56-57 m in a climb.
- On release `tow_in_progress` goes to 0 and the line's ends stop moving. The tug is AI plane 1
  (`sim/multiplayer/position/plane1_*`), so after release its end of the rope follows the tug,
  from where the tug's hook was seen while towing.

How much it hangs. A real rope pulling a glider hangs a few decimetres (0.04 kg/m over 60 m at
1000 N: 0.2 m), so drawn at the native rope's length it was a straight line, and Juan Luis
asked for the hang Condor and Aerofly FS4 show (2026-11-21). In the air ours is drawn longer
than where the native one starts pulling, `ROPE_LENGTH_M`, so it always has some slack: a chord
c with slack s hangs about sqrt(3 c s / 8). The slack comes from the native rope's stretch, so
the hang follows the pull: 57 m over the 56.1-56.8 m of a climb hangs 2-4 m, less when the tug
pulls harder, more when it eases. Past 57 m between the ends it is straight. On the ground roll
it is the native rope's 53 m, so that it does not lie in a wide curve on the runway, and it
grows to 57 m once the glider is up (`GROUND_AGL_M`, `LENGTH_RATE_MS`). A departure from a real
rope, for the eye; `length_m` (a dataref) changes the length in the air, to tune it.

States: no rope; on the tow (both ends X-Plane's); released (the glider's end free, the other
on the tug while the tug can be seen, for `TRAIL_S` seconds). The glider put somewhere else, a
new flight say, starts over; a shift of X-Plane's local origin moves the rope with it.

Every frame: 21 reads; while there is a rope, also its step and one position per segment,
300-400 us a frame in all (measured in X-Plane 12.4.4). No `xp` here: the SDK calls are in
`xpio.TowIO` and `xpio.SkyObjects`. Frames: the rope is solved in X-Plane's local frame with
its axes renamed (east, north, up) = (x, -z, y), which `engine.rope` allows for a rope this
short.
"""

import math
import time

from ..engine.rope import DRAG_CD, Rope

OBJECT_NAME = "segment"
NATIVE_SLACK_M = 53.0  # where the native rope starts pulling (measured above)
ROPE_LENGTH_M = 57.0  # ours, drawn: see "How much it hangs" above
LENGTH_RANGE_M = (NATIVE_SLACK_M, 62.0)
# The air on our rope, as a share of a real rope's. Across a rope climbing to a tug 30 m above,
# a real rope's drag is two or three times its weight, and it bowed our longer rope up and
# back (Juan Luis, 2026-11-21: "the curve is the wrong way round"). Our hang is there for the
# eye, so gravity must lead: at a fifth it hangs down with the tug level, 15 m or 30 m above (offline: 3.6,
# 3.4 and 2.3 m under the chord), and after release it still streams behind the tug, about
# 30 degrees down.
DRAG_SHARE = 0.2
SEGMENTS = 30
HOOK_REACH_M = 10.0  # the line's glider end is this close to the glider while it is real
LINE_REACH_M = 120.0  # and its tug end this close to the glider end
JUMP_M = 60.0  # the glider moved farther than this in one frame: it jumped
TUG_HOOK_REACH_M = 15.0  # the tug's hook is this close to AI plane 1's reference point
TRAIL_S = 90.0  # the released rope is drawn this long behind the tug
TRAIL_REACH_M = 3000.0  # and while the tug is this close to the glider
MAX_DT_S = 0.1
PROBE_PERIOD_S = 1.0  # the ground under each end of the rope is probed this often
FLOOR_RATE_MS = 0.5  # and the rope's floor follows a new probe this fast, never by a jump
GROUND_AGL_M = 3.0  # the glider is on its ground roll below this
LENGTH_RATE_MS = 0.4  # the drawn length goes from the native rope's to the hanging one this fast

NONE, TOWING, RELEASED = 0, 1, 2


def to_rope(x, y, z):
    return (x, -z, y)


def body_axes(psi_deg, theta_deg, phi_deg):
    """An aircraft's right, up and forward axes in (east, north, up), from X-Plane's heading,
    pitch and roll (positive phi: right wing down)."""
    psi, th, phi = math.radians(psi_deg), math.radians(theta_deg), math.radians(phi_deg)
    forward = (math.sin(psi) * math.cos(th), math.cos(psi) * math.cos(th), math.sin(th))
    right0 = (math.cos(psi), -math.sin(psi), 0.0)
    up0 = (right0[1] * forward[2] - right0[2] * forward[1],
           right0[2] * forward[0] - right0[0] * forward[2],
           right0[0] * forward[1] - right0[1] * forward[0])
    c, s = math.cos(phi), math.sin(phi)
    right = tuple(r * c - u * s for r, u in zip(right0, up0))
    up = tuple(u * c + r * s for r, u in zip(right0, up0))
    return right, up, forward


def _dist(p, q):
    return math.sqrt((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 + (p[2] - q[2]) ** 2)


def _ground_m(place, other):
    """Roughly how far apart two (lat, lon) are, m: enough to tell a jump from a frame's move."""
    north = (place[0] - other[0]) * 111_195.0
    east = (place[1] - other[1]) * 111_195.0 * math.cos(math.radians(place[0]))
    return math.hypot(north, east)


class LineReading:
    """One frame of what `tow.TowRope` reads, reused frame after frame. Positions are X-Plane's
    local (x, y, z), lists of three."""

    __slots__ = ("aircraft", "payload", "glider", "tug", "towing", "agl_m", "lat", "lon",
                 "wind_x", "wind_z", "rho", "tug_psi", "tug_theta", "tug_phi")

    def __init__(self):
        self.aircraft, self.payload, self.glider, self.tug = [], [], [0.0] * 3, [0.0] * 3
        self.towing = False
        self.agl_m = self.lat = self.lon = self.wind_x = self.wind_z = 0.0
        self.rho = 1.2
        self.tug_psi = self.tug_theta = self.tug_phi = 0.0


class TowStatus:
    """Published as datarefs, for the test pilot."""

    __slots__ = ("state", "frame_us", "sag_m", "span_m")

    def __init__(self):
        self.state = NONE
        self.frame_us = 0.0
        self.sag_m = 0.0  # the farthest node from the straight line between the ends
        self.span_m = 0.0  # between the ends


class TowRope:
    """io: `xpio.TowIO` or a stand-in; objects: `xpio.SkyObjects("rope")` or a stand-in."""

    def __init__(self, io, objects, log, clock=time.monotonic):
        self.io = io
        self.objects = objects
        self.log = log
        self.clock = clock
        self.status = TowStatus()
        self.rope = Rope(ROPE_LENGTH_M, SEGMENTS, cd=DRAG_CD * DRAG_SHARE)
        self.obj = None
        self.loading = False
        self.instances = []
        self.native_hidden = False
        self._poses = None
        self._hook = None  # the tug's hook in its (right, up, forward) axes, seen while towing
        self._prev_glider = None
        self._prev_place = None
        self._released_at = None
        self._was_towing = False
        self._spent = None  # the glider's end of the native line as it froze on release
        self._floor = None  # [under end A, under end B], local y, eased toward the probes
        self._floor_target = None
        self._next_probe = 0.0
        self._air_length = ROPE_LENGTH_M

    @property
    def state(self):
        return self.status.state

    @property
    def length_m(self):
        """The drawn length in the air, within LENGTH_RANGE_M (a dataref, to tune the hang). On
        the ground roll the rope is the native one's length, so that it lies nearly straight
        between the glider and the tug (Juan Luis, 2026-11-21: all curved on the runway); it
        grows to this one after lift-off at LENGTH_RATE_MS."""
        return self._air_length

    @length_m.setter
    def length_m(self, value):
        value = float(value)
        if value == value:  # not NaN
            self._air_length = min(LENGTH_RANGE_M[1], max(LENGTH_RANGE_M[0], value))

    def _set_rope_length(self, value):
        self.rope.length_m = value
        self.rope.rest_m = value / self.rope.segments

    def _length_toward(self, target, dt):
        now = self.rope.length_m
        step = LENGTH_RATE_MS * dt
        self._set_rope_length(min(now + step, target) if target > now else max(now - step, target))

    # --- per frame -------------------------------------------------------------

    def update(self, dt, enabled):
        """One frame. enabled: the pilot wants our rope."""
        if not enabled:
            self.clear()
            return
        if self.obj is None:
            self._load()
        io = self.io
        if io.frozen():
            return
        t0 = time.perf_counter()
        line = io.read_line()
        a, b = to_rope(*line.aircraft), to_rope(*line.payload)
        glider = to_rope(*line.glider)
        towing = line.towing
        # A jump of the glider in X-Plane's local frame is either the frame's origin moving (the
        # glider stays where it is on the Earth) or the glider put somewhere else: a new flight.
        moved = self._prev_glider is not None and _dist(glider, self._prev_glider) > JUMP_M
        shift = tuple(g - p for g, p in zip(glider, self._prev_glider)) if moved else None
        place = (line.lat, line.lon)
        elsewhere = self._prev_place is not None and _ground_m(place, self._prev_place) > JUMP_M
        self._prev_glider, self._prev_place = glider, place
        live = (_dist(a, glider) < HOOK_REACH_M and 1.0 < _dist(a, b) < LINE_REACH_M)
        state = self.status.state
        if elsewhere:
            self._spent = None
        if elsewhere and state != NONE:
            self._drop()
            state = NONE
            self._was_towing = False
        elif shift is not None and state != NONE:
            self.rope.shift(*shift)

        if state == NONE:
            # Waiting on the runway the line is there before the tow; after a release its frozen
            # ends may still be beside a glider that stopped, and are not a new tow.
            fresh = self._spent is None or _dist(a, self._spent) > 0.05
            if live and (towing or (line.agl_m < 2.0 and fresh)):
                self._attach(a, b, line)
                state = TOWING
        elif state == TOWING:
            if self._was_towing and not towing:
                self._spent = a
                self._release(line)
                state = RELEASED
            elif not live:
                self._drop()
                state = NONE
        elif state == RELEASED:
            if live and towing:
                self._attach(a, b, line)  # a new tow
                state = TOWING
            elif self.clock() - self._released_at > TRAIL_S:
                self._drop()
                state = NONE
        self._was_towing = towing
        self.status.state = state
        if state == NONE:
            self._hide_native(False)
            return

        wind = (line.wind_x, -line.wind_z, 0.0)
        dt = min(MAX_DT_S, max(0.0, dt))
        on_ground = state == TOWING and line.agl_m < GROUND_AGL_M
        self._length_toward(NATIVE_SLACK_M if on_ground else self._air_length, dt)
        ground = self._ground_under(line, dt)
        if state == TOWING:
            self._learn_hook(line, b)
            self.rope.step(dt, a, b, wind=wind, ground_up=ground, rho=line.rho)
        else:
            hook = self._tug_hook(line)
            if hook is None or _dist(hook, glider) > TRAIL_REACH_M:
                self._drop()
                self.status.state = NONE
                self._hide_native(False)
                return
            self.rope.step(dt, None, hook, wind=wind, ground_up=ground, rho=line.rho)
        self._draw()
        self._hide_native(True)
        self._measure()
        us = (time.perf_counter() - t0) * 1e6
        self.status.frame_us += 0.05 * (us - self.status.frame_us)

    # --- states ----------------------------------------------------------------

    def _ground_under(self, line, dt):
        """The runway under the rope's two ends, probed: `y_agl` is not the wheels' height (the
        ASK 21's hook sat 0.55 m under its reference point while y_agl read 0.03, 2026-11-21).
        A new probe is followed at FLOOR_RATE_MS: a floor that jumped threw the rope up."""
        now = self.clock()
        fallback = line.glider[1] - line.agl_m
        if now >= self._next_probe or self._floor_target is None:
            self._next_probe = now + PROBE_PERIOD_S
            target = []
            for node in (self.rope.nodes[0], self.rope.nodes[-1]):
                e, n, u = node
                y = self.io.ground_y(e, u, -n)
                target.append(fallback if y is None else y)
            self._floor_target = target
            if self._floor is None:
                self._floor = list(target)
        step = FLOOR_RATE_MS * dt
        for i in (0, 1):
            d = self._floor_target[i] - self._floor[i]
            self._floor[i] += max(-step, min(step, d))
        return (self._floor[0], self._floor[1])

    def _attach(self, a, b, line):
        self._floor = self._floor_target = None
        self._set_rope_length(NATIVE_SLACK_M if line.agl_m < GROUND_AGL_M else self._air_length)
        self.rope.reset(a, b)
        self._hook = None
        self._released_at = None
        self.log("tow rope: on the tow, ours drawn in place of X-Plane's line")

    def _release(self, line):
        self.rope.release_a()
        self._released_at = self.clock()
        self.log("tow rope: released" + ("" if self._hook else "; the tug cannot be followed, the rope goes"))

    def _drop(self):
        self._destroy_instances()
        self._hook = None
        self._released_at = None

    def clear(self):
        """No rope drawn and X-Plane's line given back."""
        self._drop()
        self.status.state = NONE
        self._was_towing = False
        self._hide_native(False)

    def shutdown(self):
        self.clear()
        self.io.release()
        if self.obj is not None:
            self.objects.unload(self.obj)
            self.obj = None

    # --- the tug ---------------------------------------------------------------

    def _learn_hook(self, line, b):
        tug = to_rope(*line.tug)
        d = (b[0] - tug[0], b[1] - tug[1], b[2] - tug[2])
        if math.sqrt(d[0] ** 2 + d[1] ** 2 + d[2] ** 2) > TUG_HOOK_REACH_M:
            self._hook = None  # plane 1 is not the tug
            return
        axes = body_axes(line.tug_psi, line.tug_theta, line.tug_phi)
        self._hook = tuple(sum(di * ai for di, ai in zip(d, axis)) for axis in axes)

    def _tug_hook(self, line):
        if self._hook is None:
            return None
        tug = to_rope(*line.tug)
        axes = body_axes(line.tug_psi, line.tug_theta, line.tug_phi)
        return tuple(tug[i] + sum(h * axis[i] for h, axis in zip(self._hook, axes)) for i in range(3))

    # --- drawing ---------------------------------------------------------------

    def _load(self):
        if self.loading:
            return
        self.loading = True

        def loaded(obj, _name):
            self.loading = False
            if obj is None:
                self.log("tow rope: its object did not load; X-Plane's line stays")
                self.obj = False  # do not try again
                return
            self.obj = obj

        self.objects.load_async(OBJECT_NAME, loaded)

    def _draw(self):
        if not self.obj:
            return
        if not self.instances:
            self.instances = [self.objects.create(self.obj) for _ in range(SEGMENTS)]
        self._poses = self.rope.segment_poses(self._poses)
        set_position = self.objects.set_position
        for inst, (e, n, u, _length, heading, pitch) in zip(self.instances, self._poses):
            set_position(inst, e, u, -n, pitch=pitch, heading=heading)

    def _destroy_instances(self):
        for inst in self.instances:
            self.objects.destroy(inst)
        self.instances = []

    def _hide_native(self, hide):
        # Only while ours is drawn: X-Plane's line stays whenever ours cannot be.
        # Written every frame while ours is drawn: something else (a script, the test pilot) may
        # have turned X-Plane's line back on (seen 2026-11-21). One write a frame.
        hide = bool(hide and self.instances)
        if hide or hide != self.native_hidden:
            self.io.hide_native_line(hide)
            self.native_hidden = hide

    def _measure(self):
        nodes = self.rope.nodes
        a, b = nodes[0], nodes[-1]
        span = _dist(a, b)
        sag = 0.0
        if span > 1e-6:
            u = tuple((q - p) / span for p, q in zip(a, b))
            for p in nodes:
                d = tuple(pi - ai for pi, ai in zip(p, a))
                along = sum(di * ui for di, ui in zip(d, u))
                off = math.sqrt(max(0.0, sum(di * di for di in d) - along * along))
                sag = max(sag, off)
        self.status.sag_m = sag
        self.status.span_m = span
