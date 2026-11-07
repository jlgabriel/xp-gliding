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
