"""Which thermals the training markers show, and in which variant.

Training mode (off by default) draws a ring and a column
over the thermals near the glider. This module is the part with no simulator:
given the field, the glider's place and the markers already shown, it says
which thermals to mark, how strong their core is and how wide. The adapter
turns that into instanced objects.

What to mark. The sky is dense: with the mean-day defaults about 90 thermals
are alive within 3 km, and 370 within 5 km (4.5 per km2), far more than anyone
can read. So there are three limits:
- `range_m` 3 km: about 2 minutes of flight at 90 km/h, ~100 m of height at the
  ASK 21's glide. At that distance a 40 m ring still spans 1.5 degrees.
- `min_core_ms` 1.5 m/s of lift at the core at the glider's height: below that
  no thermal can be climbed, even in a better glider than the ASK 21 (which
  sinks ~2 m/s circling).
- `max_count` 20: two instances each, and enough to choose from. The best are
  picked by core lift minus a small cost of distance, the same trade the test
  pilot's oracle uses (0.5 m/s for 2.5 km of glide).

No flicker. A marker that is already shown stays while it is within a slightly
wider range and above a slightly lower lift, and it gets a bonus when ranking,
so two similar thermals do not swap places every update. The variants have the
same kind of margin. The limit of 20 is what usually removes a marker while its
thermal is still alive, when a stronger one appears (offline, 2-3 per minute), so
one within `protect_m` of the glider cannot lose its place that way: the thermal
being circled keeps its marker until it fades.

The core is the one thermal's own lift at its centre (life cycle included), not
`ThermalField.lift_at`, which adds its neighbours: it is what the colour says
about this thermal, and costs far less. Where thermals overlap, the air there
is stronger than the marker says.

Pure Python: no `xp`.
"""

import math

from . import updraft
from .field import height_in_thermal

# Ring radii (m) that exist as objects, steps of sqrt(2): instances cannot be
# scaled. They cover the core radius r1 of what passes `min_core_ms` with the
# defaults, from a young, narrow thermal to a wide one (13-102 m at 800 m AGL).
SIZES_M = (10.0, 14.0, 20.0, 28.0, 40.0, 56.0, 80.0, 112.0)
# Core lift (m/s) separating the strength classes: below the first a glider like
# the ASK 21 can only slow its sink; then barely climbing, good, strong.
STRENGTH_LIMITS_MS = (2.0, 3.0, 4.0)
STRENGTH_COUNT = len(STRENGTH_LIMITS_MS) + 1

SIZE_MARGIN = 1.08  # a class is kept until the radius is 8% past its boundary
STRENGTH_MARGIN_MS = 0.15

TOP_ZZI = 1.0 / 1.1  # Allen's mean updraft turns negative above this z/zi (Eq. 11)
PROTECTED_SCORE = 100.0  # more than any core lift can differ by


class MarkerParams:
    __slots__ = ("range_m", "keep_range_m", "min_core_ms", "keep_core_ms", "max_count",
                 "sticky_ms", "cost_ms_per_m", "protect_m")

    def __init__(self, range_m=3000.0, keep_range_m=3300.0, min_core_ms=1.5, keep_core_ms=1.2,
                 max_count=20, sticky_ms=0.5, cost_ms_per_m=0.0002, protect_m=500.0):
        self.range_m = range_m
        self.keep_range_m = keep_range_m
        self.min_core_ms = min_core_ms
        self.keep_core_ms = keep_core_ms
        self.max_count = max_count
        self.sticky_ms = sticky_ms
        self.cost_ms_per_m = cost_ms_per_m
        self.protect_m = protect_m


class Marker:
    """One thermal to mark, at the height it was selected for."""

    __slots__ = ("thermal", "core_ms", "r1_m", "distance_m")

    def __init__(self, thermal, core_ms, r1_m, distance_m):
        self.thermal = thermal
        self.core_ms = core_ms
        self.r1_m = r1_m
        self.distance_m = distance_m


def core_of(thermal, z, t, wstar, zi, we, sink_share=1.0):
    """This thermal's lift at its centre (m/s) and core radius r1 (m) at height z and time t.

    zi is the field's, which the thermal reads at its own depth. we is the environment sink at z
    (`ThermalField.environment_sink`) for the thermal's zi, and sink_share the share of it the air
    between thermals has now (`ThermalField.sink_share`), as the lift has.
    """
    strength, radius = thermal.envelope(t)
    if strength == 0.0:
        return we * sink_share, 0.0
    rgain = thermal.rgain * radius
    zit = thermal.zi(zi)
    w = updraft.updraft_velocity(0.0, z, zit, wstar, thermal.wgain * thermal.gain, rgain, we)
    r1, _ = updraft.core_radii(z, zit, rgain)
    return we * sink_share + strength * (w - we), r1 * thermal.stretch


def select_markers(field, e, n, z, t, wstar, zi, shown=(), params=None, ground_m=None):
    """Markers to show around (e, n) at height z and time t, best first.

    shown: the thermals already marked (a set or dict of Thermal). Same inputs,
    same answer: ties are broken by position. ground_m: the ground's height MSL under the
    glider; with it each thermal is read at its own height (`height_in_thermal`), as the lift is.
    """
    params = params or MarkerParams()
    if zi <= 0.0 or z <= 0.0 or (z >= zi and ground_m is None):
        return []
    ranked = []
    for th, r in field.alive_within(e, n, t, params.keep_range_m):
        kept = th in shown
        if not kept and r > params.range_m:
            continue
        zt = height_in_thermal(th, z, ground_m)
        core, r1 = core_of(th, zt, t, wstar, zi, field.environment_sink(zt, wstar, th.zi(zi)),
                           field.sink_share)
        if core < (params.keep_core_ms if kept else params.min_core_ms):
            continue
        score = core - params.cost_ms_per_m * r + (params.sticky_ms if kept else 0.0)
        if kept and r <= params.protect_m:
            score += PROTECTED_SCORE
        ranked.append((-score, th.lat, th.lon, Marker(th, core, r1, r)))
    ranked.sort(key=lambda item: item[:3])
    return [item[3] for item in ranked[:params.max_count]]


def ring_object(size_index, strength):
    """Name of the ring object of a size and strength class (tools/make_marker_objs.py)."""
    return f"ring_r{SIZES_M[size_index]:03.0f}_s{strength}"


def column_object(strength):
    """Name of the column object of a strength class."""
    return f"column_s{strength}"


def all_objects():
    """Names of every marker object."""
    names = [column_object(s) for s in range(STRENGTH_COUNT)]
    for s in range(STRENGTH_COUNT):
        names.extend(ring_object(i, s) for i in range(len(SIZES_M)))
    return names


def size_class(r1_m, previous=None):
    """Index in SIZES_M for a core radius; `previous` keeps its class within a margin."""
    if previous is not None and r1_m > 0.0:
        half_step = math.sqrt(math.sqrt(2.0)) * SIZE_MARGIN
        if SIZES_M[previous] / half_step <= r1_m <= SIZES_M[previous] * half_step:
            return previous
    best = 0
    for i, size in enumerate(SIZES_M):
        if abs(math.log(max(r1_m, 1.0) / size)) < abs(math.log(max(r1_m, 1.0) / SIZES_M[best])):
            best = i
    return best


def strength_class(core_ms, previous=None):
    """Strength class 0..STRENGTH_COUNT-1; `previous` keeps its class within a margin."""
    if previous is not None:
        low = STRENGTH_LIMITS_MS[previous - 1] if previous > 0 else -math.inf
        high = STRENGTH_LIMITS_MS[previous] if previous < len(STRENGTH_LIMITS_MS) else math.inf
        if low - STRENGTH_MARGIN_MS <= core_ms < high + STRENGTH_MARGIN_MS:
            return previous
    for i, limit in enumerate(STRENGTH_LIMITS_MS):
        if core_ms < limit:
            return i
    return len(STRENGTH_LIMITS_MS)
