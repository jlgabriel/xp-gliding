"""Glide readings for the Glide Computer: the glide ratio achieved, the one needed, the height over
the target, and the speed made good towards it.

- E, the glide ratio achieved (`GlideRatio`): the distance flown over the ground in the last
  WINDOW_S seconds against the height lost in them. Not shown while the glider holds or gains
  height (no loss to divide by), nor above MAX_LD, where it means nothing.
- DH (`height_over`): the glider's height above the target's elevation; unknown when the file gives
  the point no elevation.
- ReqE (`required_ld`): the distance to the target along the route against DH; unknown with the
  target at or above the glider. No polar, no wind: the geometry alone.
- VMG (`vmg`): the ground speed's part along the bearing to the route's first point.

What needs a polar and a MacCready (the arrival height, the time to go) is not here yet.

Pure Python: no `xp`, nothing of the engine.
"""

import math
from collections import deque

from .geodesy import distance_m

WINDOW_S = 30.0  # E looks this far back (Condor does not say how far its E looks: to verify)
MAX_LD = 300.0  # above this, E is not a glide ratio worth showing
MIN_LOSS_M = 1.0  # less height lost than this: E is not shown


class GlideRatio:
    """E: fed a sample a second (simulator time, place, height MSL); `ld` is None when unknown."""

    def __init__(self, window_s=WINDOW_S):
        self.window_s = window_s
        self._samples = deque()  # (t, lat, lon, msl, metres flown from the first sample kept)

    def reset(self):
        self._samples.clear()

    def add(self, t, lat, lon, msl):
        if not all(math.isfinite(v) for v in (t, lat, lon, msl)):
            return
        samples = self._samples
        if samples and t <= samples[-1][0]:
            samples.clear()  # time went back: a new flight
        flown = 0.0
        if samples:
            last = samples[-1]
            flown = last[4] + distance_m(last[1], last[2], lat, lon)
        samples.append((t, lat, lon, msl, flown))
        while len(samples) > 2 and t - samples[1][0] >= self.window_s:
            samples.popleft()

    @property
    def ld(self):
        samples = self._samples
        if len(samples) < 2:
            return None
        first, last = samples[0], samples[-1]
        if last[0] - first[0] < 0.5 * self.window_s:
            return None
        loss = first[3] - last[3]
        if loss < MIN_LOSS_M:
            return None
        ld = (last[4] - first[4]) / loss
        return ld if ld <= MAX_LD else None


def height_over(msl_m, elev_m):
    """DH: metres above the target's elevation, or None."""
    if msl_m is None or elev_m is None or not math.isfinite(msl_m) or not math.isfinite(elev_m):
        return None
    return msl_m - elev_m


def required_ld(dist_m, dh_m):
    """ReqE: the glide ratio needed to reach the target with no height left, or None."""
    if dist_m is None or dh_m is None or dh_m <= 0.0:
        return None
    ld = dist_m / dh_m
    return ld if ld <= MAX_LD else None


def vmg(gs_ms, track_deg, bearing_deg):
    """The ground speed made good towards a bearing (m/s, negative going away), or None."""
    if gs_ms is None or track_deg is None or bearing_deg is None:
        return None
    return gs_ms * math.cos(math.radians(track_deg - bearing_deg))
