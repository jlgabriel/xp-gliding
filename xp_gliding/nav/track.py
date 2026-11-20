"""The track flown, for the Flight Computer's map: one point a second, sent to the page in pieces.

`Track.add` is offered the glider's position often (the adapter's 10 Hz tick) and keeps a point
once a second of simulator time, so a paused simulator adds nothing. The last CAPACITY points are
kept (six hours), the oldest dropped first.

Points are numbered from the start of an *epoch*. A new epoch starts, and the track with it, when
the glider jumps: the adapter says so (`restart`: a new flight, a placement, a change of time), and
the track sees it itself when the simulator's time goes back or the glider moved faster than any
glider flies (JUMP_SPEED_MS) since the last point.

Each point has the glider's height above sea level too, to the metre, for the map to colour the
line by, and the climb since the point before: [lat, lon, msl, climb], either null where it is not
known. The climb is the total energy gained over the second between the two points (m/s, to a
tenth), so the line from one point to the next is coloured by exactly the climb flown along it,
with no vario's lag: the Glide Computer's THERMAL screen shows where the glider climbed and sank.

The page holds what it was sent and asks only for what it does not have (`json_from`): its epoch
and the number of the point after its last. Each point is turned into text once, when kept, so an
answer is a join of strings already made, cheap enough to run inside the browser's call.

Pure Python: no `xp`, nothing of the engine.
"""

import json
import math

from .geodesy import distance_m

PERIOD_S = 1.0  # one point a second of simulator time
SOON_S = 0.05  # a point this much before its second is kept: the 10 Hz tick never lands on it
CAPACITY = 6 * 3600  # points kept: six hours at one a second
TRIM = 600  # the oldest points are dropped this many at a time, past CAPACITY
JUMP_SPEED_MS = 150.0  # faster than this between two points is a jump, not flight
SEND_LIMIT = 5000  # points in one answer at most; the page asks again for the rest


class Track:
    def __init__(self, capacity=CAPACITY):
        self.capacity = capacity
        self.epoch = 0
        self.count = 0  # points kept in this epoch, dropped ones included: the next point's number
        self._points = []  # (t, lat, lon, msl), the last ones kept
        self._texts = []  # the same points as JSON text, "[lat,lon,msl,climb]"
        self._energy = None  # (t, total energy as a height, m) at the last point kept, if known
        self.sent = 0  # the number after the last point sent: what the page holds, for the test pilot

    @property
    def start(self):
        """The number of the oldest point still kept."""
        return self.count - len(self._points)

    def restart(self):
        """A new epoch, with no points: the glider jumped, or a new flight began."""
        self.epoch += 1
        self.count = 0
        self._points = []
        self._texts = []
        self._energy = None
        self.sent = 0

    def due(self, t):
        """Would a place at simulator time t be kept? Asked first, so the place is read only then."""
        return not self._points or not 0.0 <= t - self._points[-1][0] < PERIOD_S - SOON_S

    def add(self, t, lat, lon, msl=None, energy=None):
        """Offer the position at simulator time t (s), and the height (m MSL) and the total energy
        as a height (m) if known; True if it was kept as a point."""
        if not (math.isfinite(t) and math.isfinite(lat) and math.isfinite(lon)):
            return False
        if self._points:
            t0, lat0, lon0, _ = self._points[-1]
            dt = t - t0
            if dt < 0.0:
                self.restart()  # time went back: a new flight, or the simulator's clock reset
            elif dt < PERIOD_S - SOON_S:
                return False
            elif distance_m(lat0, lon0, lat, lon) > JUMP_SPEED_MS * dt:
                self.restart()
        if msl is not None and not math.isfinite(msl):
            msl = None
        if energy is not None and not math.isfinite(energy):
            energy = None
        climb = None
        last, self._energy = self._energy, None if energy is None else (t, energy)
        if self._points and last is not None and energy is not None and last[0] == self._points[-1][0]:
            dt = t - last[0]
            if 0.0 < dt <= 2.0 * PERIOD_S:  # the point before a paused or missed second is too far
                climb = (energy - last[1]) / dt
        self._points.append((t, lat, lon, msl))
        height = "null" if msl is None else f"{msl:.0f}"
        rate = "null" if climb is None else f"{climb:.1f}"
        self._texts.append(f"[{lat:.6f},{lon:.6f},{height},{rate}]")
        self.count += 1
        if len(self._points) > self.capacity + TRIM:
            del self._points[:-self.capacity]
            del self._texts[:-self.capacity]
        return True

    def points(self):
        """The points kept, oldest first, as (t, lat, lon, msl)."""
        return list(self._points)

    def json_from(self, epoch, first):
        """The JSON the page gets for `xplane.xpg_track`: the points from number `first` on, if the
        page holds this epoch; else all kept, from the oldest. `from` says where the points sent
        begin: when it is not the page's `first`, the page starts its line again with them.
        `more` is true when SEND_LIMIT cut the answer short."""
        start, count = self.start, self.count
        if epoch != self.epoch or not isinstance(first, int) or first < start or first > count:
            first = start
        end = min(count, first + SEND_LIMIT)
        texts = self._texts[first - start:end - start]
        self.sent = end
        head = json.dumps({"epoch": self.epoch, "from": first, "n": count, "more": end < count},
                          separators=(",", ":"))
        return head[:-1] + ',"points":[' + ",".join(texts) + "]}"
