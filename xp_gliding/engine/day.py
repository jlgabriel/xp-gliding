"""The depth of the day from XP12's atmosphere: where would a cumulus form?

Pure Python, no `xp`. A parcel lifted from the ground cools by the dry adiabat, about 9.8 C per km,
and its dew point falls by about 1.8 C per km, so they meet about 125 m above the ground per
degree of spread between temperature and dew point (Espy's rule). Good to a few percent for this
use, and it is what soaring pilots use.

The ground's values come from a table of heights, as X-Plane's layers do. Below the first height
or above the last, the end value holds. See notes/phase5.md.
License: GPL-3.0-or-later.
"""

M_PER_C_OF_SPREAD = 125.0
NO_DATA_C = -99.0  # X-Plane's layers can read -100: seen in dew points under real weather


def at_height(height_m, heights_m, values):
    """Interpolate a table at a height. The table's heights must rise."""
    if height_m <= heights_m[0]:
        return values[0]
    for i in range(1, len(heights_m)):
        if height_m <= heights_m[i]:
            below, above = heights_m[i - 1], heights_m[i]
            f = (height_m - below) / (above - below) if above > below else 0.0
            return values[i - 1] + f * (values[i] - values[i - 1])
    return values[len(heights_m) - 1]


def known_layers(heights_m, values):
    """The layers that have a value, as two lists. Both empty if none has."""
    kept = [(h, v) for h, v in zip(heights_m, values) if v > NO_DATA_C]
    return [h for h, _ in kept], [v for _, v in kept]


def cloud_base_above_ground_m(temperature_c, dew_point_c):
    """Where a parcel from the ground condenses, m above it. Saturated air gives 0."""
    return max(temperature_c - dew_point_c, 0.0) * M_PER_C_OF_SPREAD


# A base from the weather is kept within these heights above the ground. First 500-3500 m (Juan
# Luis, 2026-11-09; X-Plane's calm default, with nothing set, gives 2733 m, notes/phase5.md), then
# 1000-2250 m for 0.3.1, while the thermals' density did not follow zi. It does now, so the top is
# 3500 m again: the sink between thermals stays as at the default zi. The bottom stays 1000 m:
# under a lower base Allen's thermals are too narrow to climb in a 30 degree circle, and the sky
# holds more of them than the plugin likes to load (notes/SPEC.md). With the wide sky's base at
# 0.75 zi these give zi 1333-4667 m.
BASE_MIN_M = 1000.0
BASE_MAX_M = 3500.0
MIN_LAYERS = 2  # fewer layers with data than this: the weather has not arrived yet


def weather_base_m(ground_m, heights_m, temperatures_c, dew_points_c):
    """The cloud base over the ground (m above it) from X-Plane's layers, within the limits.

    None if the layers do not have data enough: real weather arrives late, and before it does
    the dew points above the lowest layer read -100.
    """
    t_heights, temps = known_layers(heights_m, temperatures_c)
    d_heights, dews = known_layers(heights_m, dew_points_c)
    if len(temps) < MIN_LAYERS or len(dews) < MIN_LAYERS:
        return None
    base = cloud_base_above_ground_m(at_height(ground_m, t_heights, temps), at_height(ground_m, d_heights, dews))
    return min(max(base, BASE_MIN_M), BASE_MAX_M)
