"""The order clouds are drawn in: rings of distance, each with instances made in advance.

X-Plane 12 does not sort particles between instances. It draws instances in the reverse of the
order they were created: the newest first, underneath, and the oldest last, on top. Setting an
instance's position or its values again does not change its place in that order (flown
2026-11-07, notes/phase4.md). So a far cloud created before a nearer one in the same direction
is drawn over it, with a sharp edge.

An instance keeps its place for life, wherever it is moved. So at the start of a sky, before any
cloud, instances are made for rings of distance around the glider, the nearest ring first: every
instance of a ring is drawn over every instance of the rings beyond it, and the clouds beyond
the last ring are created as they come, after all of them. A cloud takes an instance of the ring
it is in; one that dies gives it back. When the glider's moves take a cloud into another ring,
an instance of that ring takes over in the same place and the old one stops feeding, and is given
back once its particles have gone. Going away, the new one feeds at the cloud's rate: the
turnover a cloud has anyway. Coming nearer, it fills fast, or the old particles, drawn under the
farther clouds of the new ring, would show them over the cloud for minutes as it is approached;
the cloud holds up to twice its particles until the old ones have gone. Within a ring, a cloud takes an instance newer than those of the clouds of its
ring nearer than it, and older than those of the farther ones: right when it comes in, though the
glider's moves within a ring are not followed.

Pure Python: no `xp`. Instances are whatever the adapter hands in.
"""

import bisect
import math

# Outer edges of the rings (m). The last ring, beyond these, is all the rest of the sky: its
# clouds are small in view, and an error between two of them is left.
RING_EDGES_M = (1500.0, 3000.0, 5000.0, 8000.0)
FAR = len(RING_EDGES_M)
# A cloud changes ring only this far past an edge, so circling near one does not hand it over.
HYSTERESIS_M = 300.0
# Instances made for each near ring: well over the clouds it holds, fed or fading, in the
# skies flown (about 0.2 per km2 with those fading), and those handing over: offline, flying
# straight at 108 km/h for 12 min, (8, 16, 32, 64) ran short a few times.
RING_SIZES = (10, 20, 40, 100)


def ring_bounds(ring):
    low = RING_EDGES_M[ring - 1] if ring > 0 else 0.0
    high = RING_EDGES_M[ring] if ring < FAR else math.inf
    return low, high


def ring_of(r, current=None):
    """The ring of a cloud at r metres from the glider; current: the one it is in, if any."""
    if current is not None:
        low, high = ring_bounds(current)
        if low - HYSTERESIS_M <= r < high + HYSTERESIS_M:
            return current
    return bisect.bisect_right(RING_EDGES_M, r)


class RingPool:
    """The instances made in advance that no cloud is using, by ring, oldest first."""

    def __init__(self):
        self.idle = [[] for _ in range(FAR)]  # per ring: [(rank, instance)], by rank
        self.misses = 0  # a ring had none left
        self.span = [(math.inf, -math.inf) for _ in range(FAR)]  # per ring: its first and last rank

    def add(self, ring, rank, instance):
        bisect.insort(self.idle[ring], (rank, instance), key=lambda ri: ri[0])
        first, last = self.span[ring]
        self.span[ring] = (min(first, rank), max(last, rank))

    def take(self, r, neighbours=()):
        """(ring, rank, instance) for a cloud at r metres, or None in the last ring.

        neighbours: (distance, rank) of the clouds already in its ring. The instance is newer
        than those of the nearer ones and older than those of the farther ones, so that it is
        drawn under the first and over the others, when its ring has one; with no neighbours,
        about as old within the ring as the cloud is near. With none left in its ring, the oldest
        of the next ring out, which is drawn under the rest of its own ring; failing that, None,
        and the cloud is created like a far one.
        """
        ring = ring_of(r)
        if ring >= FAR:
            return None
        for k in range(ring, FAR):
            idle = self.idle[k]
            if idle:
                if k != ring:
                    self.misses += 1
                    i = 0
                else:
                    i = self._choose(idle, ring, r, neighbours)
                rank, instance = idle.pop(i)
                return k, rank, instance
        self.misses += 1
        return None

    def _choose(self, idle, ring, r, neighbours):
        """Which of a ring's idle instances, by index: of those between its neighbours' ranks,
        the one whose place among all the ring's ranks is nearest to its place in the ring's width,
        which leaves room for the clouds that come later on either side."""
        low, high = ring_bounds(ring)
        first, last = self.span[ring]
        target = first + min(max((r - low) / (high - low), 0.0), 1.0) * (last - first)
        below = max((rank for d, rank in neighbours if d < r), default=None)
        above = min((rank for d, rank in neighbours if d >= r), default=None)
        fits = [i for i, (rank, _) in enumerate(idle)
                if (below is None or rank > below) and (above is None or rank < above)]
        if not fits:
            if above is None:
                return len(idle) - 1  # under the nearer ones as far as it can be
            if below is None:
                return 0
            # Nothing between them, or they are out of order already: near the middle.
            target = (below + above) / 2.0
            fits = range(len(idle))
        return min(fits, key=lambda i: abs(idle[i][0] - target))

    def count(self):
        return sum(len(idle) for idle in self.idle)

    def clear(self):
        """Every idle instance, for the adapter to destroy."""
        out = [instance for idle in self.idle for _, instance in idle]
        for idle in self.idle:
            idle.clear()
        self.span = [(math.inf, -math.inf) for _ in range(FAR)]
        return out
