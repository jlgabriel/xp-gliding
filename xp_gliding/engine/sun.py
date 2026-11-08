"""The sun: no sun, no thermals (SPEC, stage 1).

A cutoff, not the daily cycle of stage 2. A thermal is born only while the sun is at least
`SUN_MIN_DEG` above the horizon at its place and birth time. Thermals born before the sun goes
down live out their lives, so the sky fades out over about half an hour around sunset, clouds
and all, and fills again after sunrise. `SUN_MIN_DEG` is a first guess to tune by flying.

The sun's elevation is worked out here from the date, the time and the place, not read from
X-Plane: the field needs it at each thermal's birth, which can be half an hour ago, and the same
(seed, day, place, time) must give the same sky on every machine. The formulas are NOAA's
approximation (declination and equation of time as Fourier series in the day of the year,
good to about 0.5 degrees), with no refraction. Compared with X-Plane's
`sim/graphics/scenery/sun_pitch_degrees` in the simulator (notes/SPEC.md).

The environment sink is the thermals' mass coming down between them, so it fades with them:
`ThermalShare` gives the share of a full day's thermal flux alive at a moment, from which births
the sun allowed in the last `lifetime_max_s`.

Pure Python: no `xp`.
"""

import math

SUN_MIN_DEG = 5.0  # a thermal is born only with the sun this high or higher (first guess)
SHARE_STEP_S = 60.0  # step in birth time for the share of thermals alive


def sun_elevation_deg(lat, lon, day, utc_s):
    """The sun's elevation above the horizon (degrees, negative below) at (lat, lon).

    day: days since 1 January, 0 on that day (X-Plane's `sim/time/local_date_days`).
    utc_s: seconds since 00:00 UTC of that day; it may run past a day or start below 0,
    as the field's t does (`field.sky_time`).
    """
    days = day + utc_s / 86400.0
    g = 2.0 * math.pi / 365.0 * (days - 0.5)  # NOAA's fractional year (radians)
    eqtime_min = 229.18 * (0.000075 + 0.001868 * math.cos(g) - 0.032077 * math.sin(g)
                           - 0.014615 * math.cos(2 * g) - 0.040849 * math.sin(2 * g))
    decl = (0.006918 - 0.399912 * math.cos(g) + 0.070257 * math.sin(g)
            - 0.006758 * math.cos(2 * g) + 0.000907 * math.sin(2 * g)
            - 0.002697 * math.cos(3 * g) + 0.00148 * math.sin(3 * g))
    solar_min = (utc_s / 60.0 + eqtime_min + 4.0 * lon) % 1440.0
    hour_angle = math.radians(solar_min / 4.0 - 180.0)
    phi = math.radians(lat)
    cos_zenith = (math.sin(phi) * math.sin(decl)
                  + math.cos(phi) * math.cos(decl) * math.cos(hour_angle))
    return 90.0 - math.degrees(math.acos(min(max(cos_zenith, -1.0), 1.0)))


def sunlit(lat, lon, day, utc_s, min_deg=SUN_MIN_DEG):
    """Can a thermal be born here and now?"""
    return sun_elevation_deg(lat, lon, day, utc_s) >= min_deg


class ThermalShare:
    """The share of a full day's thermal flux alive at a moment, in [0, 1].

    A thermal alive at t was born at t - a, a in [0, lifetime_max_s). Its flux at that age
    is its life envelope, `envelope_flux(a / life)` for a life drawn uniformly in
    [lifetime_min_s, lifetime_max_s]. Summed over the lives, that gives a weight for each age,
    once; the share is then the weighted sum of the ages whose birth the sun allowed. In full
    day it is 1, at night 0, and in between it follows the births the field actually kept.
    """

    def __init__(self, lifetime_min_s, lifetime_max_s, envelope_flux, step_s=SHARE_STEP_S,
                 lives=12, min_deg=SUN_MIN_DEG):
        self.min_deg = min_deg
        self.ages = []
        self.weights = []
        count = max(1, math.ceil(lifetime_max_s / step_s))
        for k in range(count):
            age = (k + 0.5) * lifetime_max_s / count
            weight = 0.0
            for m in range(lives):
                life = lifetime_min_s + (m + 0.5) * (lifetime_max_s - lifetime_min_s) / lives
                if age < life:
                    weight += envelope_flux(age / life)
            self.ages.append(age)
            self.weights.append(weight)
        self.total = sum(self.weights)

    def at(self, lat, lon, day, t):
        """The share at time t (the field's t) for thermals around (lat, lon)."""
        if self.total <= 0.0:
            return 1.0
        lit, dark = 0.0, 0
        for age, weight in zip(self.ages, self.weights):
            if sun_elevation_deg(lat, lon, day, t - age) >= self.min_deg:
                lit += weight
            else:
                dark += 1
        if dark == 0:
            return 1.0  # exactly, as with no sun
        return lit / self.total
