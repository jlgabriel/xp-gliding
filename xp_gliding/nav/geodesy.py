"""Distances and bearings on the Earth taken as a sphere, for the Flight Computer.

A task runs to hundreds of kilometres, beyond the local east-north-up frame of `engine/geo.py`, so
navigation works on the sphere: haversine distance, initial great-circle bearing, and the point a
distance away along a bearing. A sphere of radius R_M is within about 0.5 % of WGS-84's distances,
which is what a soaring computer shows (XCSoar and SeeYou work on a sphere too for display).

Degrees in, degrees out; metres; bearings true, 0 to 360, clockwise from north.
Pure Python: no `xp`, nothing of the engine.
"""

import math

R_M = 6371000.0  # the mean Earth radius


def distance_m(lat1, lon1, lat2, lon2):
    """Great-circle distance between two points (haversine: stable for short distances)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2.0) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    return 2.0 * R_M * math.asin(math.sqrt(min(1.0, a)))


def bearing_deg(lat1, lon1, lat2, lon2):
    """Initial great-circle bearing from the first point to the second. 0 when they are the same."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    if x == 0.0 and y == 0.0:
        return 0.0
    return math.degrees(math.atan2(y, x)) % 360.0


def destination(lat, lon, bearing, distance):
    """(lat, lon) reached from a point going `distance` metres along the initial `bearing`."""
    p1, l1 = math.radians(lat), math.radians(lon)
    b = math.radians(bearing)
    d = distance / R_M
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(b))
    l2 = l1 + math.atan2(math.sin(b) * math.sin(d) * math.cos(p1), math.cos(d) - math.sin(p1) * math.sin(p2))
    return math.degrees(p2), (math.degrees(l2) + 540.0) % 360.0 - 180.0
