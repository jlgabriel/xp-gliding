"""Where to put the glider in the air near a cloud ("Put me near a cloud" in the menu).

A first flight should not need a tow before there is anything to see. The pilot chooses the
item and the glider is set in level flight `DISTANCE_M` from a cloud's thermal, on the side it
was already on, heading for it, at `HEIGHT_SHARE` of the way from the ground to the cloud's
base. Near, not in it: the pilot still reads the cloud and flies to it.

Which cloud: the nearest whose thermal has reached full strength and has at least `MIN_LEFT_S`
before it starts to decay (and its cloud to thin), so that it is still worth climbing when the
glider gets there.

Everything here is in the air's frame (`engine/wind.py`): thermals keep their place in it, and
the adapter turns the answer into a place over the ground.

Pure Python: no `xp`.
"""

import math

from .clouds import thinning_from
from .field import RISE_FRACTION

DISTANCE_M = 1500.0  # from the thermal's centre: about a minute's glide
HEIGHT_SHARE = 0.6  # of the way from the ground to the cloud's base
MIN_AGL_M = 300.0
MIN_LEFT_S = 300.0  # at full strength at least this much longer
SPEED_MS = 27.0  # about 97 km/h, the ASK 21's speed between thermals


def pick_cloud(thermals, e, n, t, params, min_left_s=MIN_LEFT_S):
    """The nearest thermal with a cloud worth flying to: (thermal, distance m), or (None, inf).

    thermals: those that carry a cloud (`CloudCatalog.thermals`), with e and n set.
    """
    best, best_r = None, math.inf
    for th in thermals:
        life = th.death - th.birth
        if t < th.birth + RISE_FRACTION * life or thinning_from(th, params) - t < min_left_s:
            continue
        r = math.hypot(th.e - e, th.n - n)
        if r < best_r:
            best, best_r = th, r
    return best, best_r


def place_near(th_e, th_n, e, n, heading_deg, distance_m=DISTANCE_M):
    """Where to put the glider (e, n) and its heading (degrees true) to fly at the thermal.

    On the line from the thermal to where the glider is now; right over the centre, behind
    the glider as it heads.
    """
    de, dn = e - th_e, n - th_n
    r = math.hypot(de, dn)
    if r < 1.0:
        a = math.radians(heading_deg)
        de, dn, r = -math.sin(a), -math.cos(a), 1.0
    pe, pn = th_e + de / r * distance_m, th_n + dn / r * distance_m
    heading = math.degrees(math.atan2(th_e - pe, th_n - pn)) % 360.0
    return pe, pn, heading


def clouds_from(cycle, lat, lon, t, step_s=300.0, horizon_s=12 * 3600.0):
    """When the morning's blue ends here: the first sky time from t on at which a thermal born
    would carry a cloud (`daycycle.DailyCycle.blue`), or None if not within the horizon. t itself
    if it is not blue now. To tell the pilot why there is no cloud yet."""
    k = 0
    while k * step_s <= horizon_s:
        when = t + k * step_s
        if not cycle.blue(lat, lon, when):
            return when
        k += 1
    return None


def start_height_m(ground_m, base_m, share=HEIGHT_SHARE, min_agl_m=MIN_AGL_M):
    """Height to start at (m MSL): share of the way from the ground up to the base."""
    return max(ground_m + share * (base_m - ground_m), ground_m + min_agl_m)
