"""A tow rope: a chain of point masses that hangs, goes slack, lies on the ground and trails.

The rope is drawn, not felt: its shape follows from where its two ends are, gravity, the air
and the ground, and it applies no force to the aircraft (X-Plane's native tow does that). It
is solved by position-based dynamics, the usual way to keep a chain steady at a game's frame
rate:

1. each free node is pushed by gravity and by the air, as a velocity change;
2. it moves by its velocity;
3. its position is corrected so that no segment is longer than its rest length, none much
   shorter (a rope does not shorten along itself: slack shows as a curve), no two neighbouring
   segments fold back on each other, and no node is under the ground;
4. its velocity becomes the distance it actually moved over the time step.

Two kinds of correction do step 3. *Long-range limits* first (as in cloth solvers): node i can
be no farther than i segments from end A and no farther than N - i segments from end B, which
in one pass makes a taut rope a straight line, with no sag left over from too few iterations.
Then a few Gauss-Seidel sweeps over the segments and the bends, alternating direction, for
the shape of a slack rope. A rope laid out shorter than its length starts as a flat arc to one
side, as on a runway: on flat ground nothing else would tell it which way to curve. Each
correction is exact for one constraint and needs no stiffness, so nothing here can blow up
with the frame time; a long frame is cut into substeps of at most `MAX_SUBSTEP_S`.

The air: drag on the part of a node's velocity through the air that is across the rope, as on
a cylinder (a rope moving along itself feels almost none), applied as an exact decay so it
can never reverse the motion. The ground: a height given each step, level or sloping from one
end of the rope to the other, which holds a node resting on it and never throws it up, with
friction that stops a node sliding along it.

When the ends are farther apart than the rope's length (X-Plane's native rope stretches), the
rest length of every segment grows to match, so the rope is drawn straight and whole.

Frame: any Cartesian frame in meters whose third axis is up, such as east-north-up. The rope
never meets the engine's thermals, so the adapter may use X-Plane's local frame with its axes
renamed: ropes are 60 m long, far too short for the projection to matter.

Pure Python: about 20 nodes, cheaper as lists of floats than as small numpy arrays.
"""

import math

GRAVITY = 9.81
MAX_SUBSTEP_S = 1.0 / 90.0
MAX_SUBSTEPS = 6
SWEEPS = 6
TAUT_SLACK = 1e-6  # m: below this a segment is not corrected
# A rope does not shorten along itself: slack makes it curve. Each segment keeps at least this
# share of its rest length, and two segments apart, their ends at least BEND_MIN of it, which
# keeps a bend between neighbours under about 80 degrees. Without both, a slack rope on the
# ground bunched up, and its segments, drawn at full length, pointed anywhere (seen in X-Plane
# 2026-11-21: white sticks standing by the glider's nose).
MIN_STRETCH = 0.97
BEND_MIN = 1.5

# A typical glider tow rope (verify against a real one when it matters to how it looks).
LENGTH_M = 60.0
SEGMENTS = 20
MASS_PER_M = 0.045  # kg/m: polyester, 8-10 mm
DIAMETER_M = 0.009
DRAG_CD = 1.2  # a cylinder across the flow
GROUND_FRICTION = 0.6  # Coulomb coefficient, rope on grass or asphalt


class Rope:
    """A rope of `segments` segments between end A (index 0) and end B (index -1).

    `step` moves it; `nodes` holds the positions as [x, y, up] lists. Each end is pinned
    (moved by the caller) or free (falls with the rest)."""

    __slots__ = ("length_m", "segments", "nodes", "_vel", "_prev_a", "_prev_b", "pinned_a",
                 "pinned_b", "_drag_k", "rest_m")

    def __init__(self, length_m=LENGTH_M, segments=SEGMENTS, mass_per_m=MASS_PER_M,
                 diameter_m=DIAMETER_M, cd=DRAG_CD):
        if length_m <= 0.0 or segments < 1:
            raise ValueError("a rope needs a length and at least one segment")
        self.length_m = float(length_m)
        self.segments = int(segments)
        self.rest_m = self.length_m / self.segments
        # Drag acceleration per (m/s)^2 across the rope, over air density:
        # 0.5 rho cd d |v| v / (mass per metre).
        self._drag_k = 0.5 * cd * diameter_m / mass_per_m
        self.nodes = [[0.0, 0.0, 0.0] for _ in range(self.segments + 1)]
        self._vel = [[0.0, 0.0, 0.0] for _ in range(self.segments + 1)]
        self._prev_a = None
        self._prev_b = None
        self.pinned_a = self.pinned_b = True

    def reset(self, a, b):
        """Lay the rope from a to b, at rest: straight if they are its length apart or more,
        else in a flat arc to one side (a rope laid out on a runway), its whole length.
        Use when a tow begins or the rope jumped."""
        ax, ay, az = a
        dx, dy, dz = b[0] - ax, b[1] - ay, b[2] - az
        n = self.segments
        chord = math.sqrt(dx * dx + dy * dy + dz * dz)
        horizontal = math.sqrt(dx * dx + dy * dy)
        amplitude = 0.0
        sx = sy = 0.0
        if 1e-6 < chord < self.length_m and horizontal > 1e-6:
            sx, sy = dy / horizontal, -dx / horizontal  # to the right of a -> b
            amplitude = _arc_amplitude(chord, self.length_m)
        # Nodes at equal arc length along the half sine, so every segment is its rest length.
        fractions = _equal_arc_fractions(chord, amplitude, n)
        for node, f in zip(self.nodes, fractions):
            off = amplitude * math.sin(math.pi * f)
            node[0], node[1], node[2] = ax + dx * f + sx * off, ay + dy * f + sy * off, az + dz * f
        for v in self._vel:
            v[0] = v[1] = v[2] = 0.0
        self._prev_a = tuple(a)
        self._prev_b = tuple(b)
        self.pinned_a = self.pinned_b = True

    def shift(self, dx, dy, dz):
        """Move every node, as when the caller's frame moves (X-Plane's local origin)."""
        for node in self.nodes:
            node[0] += dx
            node[1] += dy
            node[2] += dz
        for prev in ("_prev_a", "_prev_b"):
            p = getattr(self, prev)
            if p is not None:
                setattr(self, prev, (p[0] + dx, p[1] + dy, p[2] + dz))

    def release_a(self):
        self.pinned_a = False

    def release_b(self):
        self.pinned_b = False

    def end_distance(self):
        a, b = self.nodes[0], self.nodes[-1]
        return math.sqrt((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2 + (b[2] - a[2]) ** 2)

    def step(self, dt, a=None, b=None, wind=(0.0, 0.0, 0.0), ground_up=None, rho=1.2):
        """Advance by dt seconds. a, b: where the pinned ends are now (ignored for a free end).
        wind: the air's velocity. ground_up: height of the ground, None for none, a pair
        (under end A, under end B) for a ground that slopes along the rope, or one height per
        node."""
        if not dt > 0.0:
            return
        if self._prev_a is None:
            self.reset(a if a is not None else self.nodes[0], b if b is not None else self.nodes[-1])
        n_sub = min(MAX_SUBSTEPS, max(1, math.ceil(dt / MAX_SUBSTEP_S)))
        h = dt / n_sub
        a0 = self._prev_a if self.pinned_a and a is not None else None
        b0 = self._prev_b if self.pinned_b and b is not None else None
        for k in range(1, n_sub + 1):
            f = k / n_sub
            pa = _lerp(a0, a, f) if a0 is not None else None
            pb = _lerp(b0, b, f) if b0 is not None else None
            self._substep(h, pa, pb, wind, ground_up, rho)
        if a is not None:
            self._prev_a = tuple(a)
        if b is not None:
            self._prev_b = tuple(b)

    def _substep(self, h, pa, pb, wind, ground_up, rho):
        nodes, vel = self.nodes, self._vel
        last = self.segments
        if ground_up is None:
            floor = None
        elif isinstance(ground_up, (tuple, list)) and len(ground_up) == last + 1:
            floor = ground_up
        elif isinstance(ground_up, (tuple, list)):
            g0, g1 = ground_up
            floor = [g0 + (g1 - g0) * i / last for i in range(last + 1)]
        else:
            floor = [ground_up] * (last + 1)
        old = [tuple(p) for p in nodes]
        drag = self._drag_k * rho
        wx, wy, wz = wind

        # 1-2. External forces and the move, for every node the caller does not hold.
        for i in range(last + 1):
            if (i == 0 and pa is not None) or (i == last and pb is not None):
                continue
            v = vel[i]
            v[2] -= GRAVITY * h
            # Air velocity relative to the node, across the rope's local direction.
            j0, j1 = max(0, i - 1), min(last, i + 1)
            tx = nodes[j1][0] - nodes[j0][0]
            ty = nodes[j1][1] - nodes[j0][1]
            tz = nodes[j1][2] - nodes[j0][2]
            tl = math.sqrt(tx * tx + ty * ty + tz * tz)
            rx, ry, rz = v[0] - wx, v[1] - wy, v[2] - wz
            if tl > 1e-9:
                along = (rx * tx + ry * ty + rz * tz) / tl
                rx -= along * tx / tl
                ry -= along * ty / tl
                rz -= along * tz / tl
            speed = math.sqrt(rx * rx + ry * ry + rz * rz)
            if speed > 0.0:
                # dv/dt = -k |v| v, solved exactly over h: |v| -> |v| / (1 + k |v| h).
                keep = 1.0 / (1.0 + drag * speed * h)
                v[0] -= rx * (1.0 - keep)
                v[1] -= ry * (1.0 - keep)
                v[2] -= rz * (1.0 - keep)
            p = nodes[i]
            p[0] += v[0] * h
            p[1] += v[1] * h
            p[2] += v[2] * h
        if pa is not None:
            nodes[0][0], nodes[0][1], nodes[0][2] = pa
        if pb is not None:
            nodes[last][0], nodes[last][1], nodes[last][2] = pb

        # The rope may stretch with the native one: then every segment shares the stretch.
        # Pulled to its length or beyond, it is the straight line (the long-range limits meet
        # there only as two spheres touching, which projections approach slowly).
        rest = self.rest_m
        taut = False
        if pa is not None and pb is not None:
            span = math.sqrt((pb[0] - pa[0]) ** 2 + (pb[1] - pa[1]) ** 2 + (pb[2] - pa[2]) ** 2)
            rest = max(rest, span / last)
            taut = span >= self.length_m
        if taut:
            for i in range(1, last):
                f = i / last
                p = nodes[i]
                p[0] = pa[0] + (pb[0] - pa[0]) * f
                p[1] = pa[1] + (pb[1] - pa[1]) * f
                p[2] = pa[2] + (pb[2] - pa[2]) * f

        # 3a. Long-range limits from each pinned end.
        if taut:
            pass
        elif pa is not None:
            _limit_from(nodes, 0, range(1, last + (pb is None)), rest)
        if pb is not None:
            _limit_from(nodes, last, range(last - 1, (pa is not None) - 1, -1), rest)

        # 3b. Segments, alternating direction, then the bends; then the ground.
        w = [1.0] * (last + 1)
        if pa is not None:
            w[0] = 0.0
        if pb is not None:
            w[last] = 0.0
        forward = list(range(last))
        backward = forward[::-1]
        for sweep in range(SWEEPS):
            for i in (forward if sweep % 2 == 0 else backward):
                wi, wj = w[i], w[i + 1]
                if wi + wj == 0.0:
                    continue
                p, q = nodes[i], nodes[i + 1]
                dx, dy, dz = q[0] - p[0], q[1] - p[1], q[2] - p[2]
                d = math.sqrt(dx * dx + dy * dy + dz * dz)
                over = d - rest
                if over <= TAUT_SLACK:
                    over = d - MIN_STRETCH * rest
                    if over >= 0.0 or d < 1e-9:
                        continue
                c = over / (d * (wi + wj))
                p[0] += dx * c * wi
                p[1] += dy * c * wi
                p[2] += dz * c * wi
                q[0] -= dx * c * wj
                q[1] -= dy * c * wj
                q[2] -= dz * c * wj
            if taut:
                continue
            bend = BEND_MIN * rest
            for i in range(last - 1):
                wi, wj = w[i], w[i + 2]
                if wi + wj == 0.0:
                    continue
                p, q = nodes[i], nodes[i + 2]
                dx, dy, dz = q[0] - p[0], q[1] - p[1], q[2] - p[2]
                d = math.sqrt(dx * dx + dy * dy + dz * dz)
                if d >= bend or d < 1e-9:
                    continue
                c = (d - bend) / (d * (wi + wj))
                p[0] += dx * c * wi
                p[1] += dy * c * wi
                p[2] += dz * c * wi
                q[0] -= dx * c * wj
                q[1] -= dy * c * wj
                q[2] -= dz * c * wj
        if floor is not None:
            for i in range(last + 1):
                if w[i] and nodes[i][2] < floor[i]:
                    nodes[i][2] = floor[i]

        # 4. Velocities from the moves; friction along the ground.
        inv_h = 1.0 / h
        for i in range(last + 1):
            v, p, o = vel[i], nodes[i], old[i]
            v[0] = (p[0] - o[0]) * inv_h
            v[1] = (p[1] - o[1]) * inv_h
            v[2] = (p[2] - o[2]) * inv_h
            if floor is not None and w[i] and p[2] <= floor[i] + 1e-6:
                # Resting on the ground: the ground holds it, and never throws it. A floor that
                # rose under a node used to launch it as fast as it was lifted, and a rope on the
                # runway bounced (Juan Luis, 2026-11-21).
                v[2] = 0.0
                horizontal = math.sqrt(v[0] * v[0] + v[1] * v[1])
                if horizontal > 0.0:
                    keep = max(0.0, 1.0 - GROUND_FRICTION * GRAVITY * h / horizontal)
                    v[0] *= keep
                    v[1] *= keep

    def segment_poses(self, out=None):
        """Per segment: (middle x, y, up, length, heading deg clockwise from +y, pitch deg up).
        Heading follows the aviation habit when the frame is east-north-up. Reuses `out`."""
        nodes = self.nodes
        if out is None or len(out) != self.segments:
            out = [None] * self.segments
        for i in range(self.segments):
            p, q = nodes[i], nodes[i + 1]
            dx, dy, dz = q[0] - p[0], q[1] - p[1], q[2] - p[2]
            horizontal = math.sqrt(dx * dx + dy * dy)
            length = math.sqrt(horizontal * horizontal + dz * dz)
            heading = math.degrees(math.atan2(dx, dy)) % 360.0 if horizontal > 1e-9 else 0.0
            pitch = math.degrees(math.atan2(dz, horizontal)) if length > 1e-9 else 0.0
            out[i] = ((p[0] + q[0]) * 0.5, (p[1] + q[1]) * 0.5, (p[2] + q[2]) * 0.5, length,
                      heading, pitch)
        return out


def _arc_length(chord, amplitude, samples=64):
    """Length of y = amplitude sin(pi x / chord) over [0, chord]."""
    total = 0.0
    px, py = 0.0, 0.0
    for k in range(1, samples + 1):
        x = chord * k / samples
        y = amplitude * math.sin(math.pi * k / samples)
        total += math.hypot(x - px, y - py)
        px, py = x, y
    return total


def _arc_amplitude(chord, length):
    lo, hi = 0.0, length
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        if _arc_length(chord, mid) < length:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _equal_arc_fractions(chord, amplitude, n, samples=200):
    """Where along the chord (0-1) to put n + 1 nodes equally spaced along the arc."""
    if amplitude <= 0.0:
        return [i / n for i in range(n + 1)]
    cumulative = [0.0]
    px, py = 0.0, 0.0
    for k in range(1, samples + 1):
        x = chord * k / samples
        y = amplitude * math.sin(math.pi * k / samples)
        cumulative.append(cumulative[-1] + math.hypot(x - px, y - py))
        px, py = x, y
    total = cumulative[-1]
    out, k = [], 0
    for i in range(n + 1):
        target = total * i / n
        while k < samples and cumulative[k + 1] < target:
            k += 1
        if k >= samples:
            out.append(1.0)
            continue
        span = cumulative[k + 1] - cumulative[k]
        out.append((k + (target - cumulative[k]) / span) / samples if span > 0 else k / samples)
    return out


def _lerp(p, q, f):
    return (p[0] + (q[0] - p[0]) * f, p[1] + (q[1] - p[1]) * f, p[2] + (q[2] - p[2]) * f)


def _limit_from(nodes, anchor, order, rest):
    """Pull each node in `order` (walking away from `anchor`) to within |i - anchor| segments
    of it."""
    ax, ay, az = nodes[anchor]
    for i in order:
        p = nodes[i]
        dx, dy, dz = p[0] - ax, p[1] - ay, p[2] - az
        d = math.sqrt(dx * dx + dy * dy + dz * dz)
        limit = abs(i - anchor) * rest
        if d > limit and d > 0.0:
            s = limit / d
            p[0], p[1], p[2] = ax + dx * s, ay + dy * s, az + dz * s
