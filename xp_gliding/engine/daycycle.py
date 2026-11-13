"""The daily cycle: how strong the thermals are at each hour of the day.

Designed offline, and chosen by Juan Luis (2026-11-10).
The field owns one (`ThermalField.cycle`) when the sun is on, and the injector takes the w* of
the moment from it; the cloud catalog uses `blue` to leave the morning without clouds.

Physics. The convective velocity scale is w* = (g / theta * H * zi)^(1/3): the cube root of the
surface heat flux H times the depth of the mixed layer zi. No dataref gives H, so the sun stands
in for it, worked out from the date, time and place (`sun.py`):

- H goes as sin(elevation) - sin(`ONSET_DEG`), at least 0: positive a while after sunrise and
  until a while before sunset, highest at solar noon.
- zi grows through the morning by encroachment: zi^2 goes with the heat put in since H turned
  positive. zi / zi_peak = sqrt(heat since then / heat by `DEPTH_CAP_SOLAR_H`), at most 1, so it
  stops growing in mid-afternoon.
- The strength is (H / H_noon * zi / zi_peak)^(1/3), divided by its largest value that day, so
  it is 1 at the day's best moment (about 13:00 solar) and the pilot's w* is the day's peak.

A thermal born before zi has grown to `FIRST_CLOUDS_DEPTH` of the afternoon's is blue, so the
morning is blue, and the first cumulus come between about 10:00 and 10:40 solar time, low, under a
base that rises through the day. It was the sky's `cloud_base_zzi` (0.75), which held them until
about noon solar; Juan Luis found that too late and dull (2026-11-11: "seamos un poco más
generosos"), and real first cumulus come late in the morning.

The day is worked out once per place and solar day on a table every `STEP_S` and kept; the place
is taken to `CELL_DEG`, about 10 km, over which the sun moves by under half a minute of time.
Everything is deterministic in (lat, lon, day, t). Pure Python: no `xp`.
"""

import math

from . import sun

ONSET_DEG = sun.SUN_MIN_DEG  # H turns positive with the sun this high (first guess)
DEPTH_CAP_SOLAR_H = 15.0  # zi stops growing at this solar hour
FIRST_CLOUDS_DEPTH = 0.55  # thermals carry clouds once zi is this share of the afternoon's
STEP_S = 300.0  # the table's step
CELL_DEG = 0.1  # the table's place is rounded to this
CACHE_DAYS = 8  # tables kept


class _Day:
    """One solar day at one place: strength and depth every STEP_S from solar midnight."""

    __slots__ = ("start", "strength", "depth")

    def __init__(self, lat, lon, day, noon_utc_s, onset_deg, cap_solar_h):
        sin_onset = math.sin(math.radians(onset_deg))
        self.start = noon_utc_s - 43200.0
        count = int(86400.0 / STEP_S) + 1
        heat = []
        for k in range(count):
            t = self.start + k * STEP_S
            elevation = sun.sun_elevation_deg(lat, lon, day, t)
            heat.append(max(0.0, math.sin(math.radians(elevation)) - sin_onset))
        noon_heat = heat[count // 2]
        # Heat put in since the night, by the trapezoid rule.
        cumulative = [0.0]
        for k in range(1, count):
            cumulative.append(cumulative[-1] + 0.5 * (heat[k - 1] + heat[k]) * STEP_S)
        cap_index = min(count - 1, int(round(cap_solar_h * 3600.0 / STEP_S)))
        cap = cumulative[cap_index]
        self.depth = [min(1.0, math.sqrt(c / cap)) if cap > 0.0 else 0.0 for c in cumulative]
        raw = [(h / noon_heat * d) ** (1.0 / 3.0) if noon_heat > 0.0 else 0.0
               for h, d in zip(heat, self.depth)]
        best = max(raw)
        self.strength = [r / best if best > 0.0 else 0.0 for r in raw]

    def at(self, values, t):
        x = (t - self.start) / STEP_S
        if x <= 0.0:
            return values[0]
        k = int(x)
        if k >= len(values) - 1:
            return values[-1]
        f = x - k
        return values[k] + f * (values[k + 1] - values[k])


def _solar_noon(lon, day, solar_day):
    """The field's t of solar noon on that solar day, from the day alone.

    The table must not depend on the t it was first asked for: the field and the clouds ask at
    different times, and each thermal's depth must be the same for both (found 2026-11-11: the
    noon taken from the asking t moved with the equation of time by a fraction of a second).
    """
    noon = 43200.0 + 86400.0 * solar_day - 240.0 * lon
    for _ in range(3):
        diff = 43200.0 - sun.solar_time_s(lon, day, noon)
        noon += (diff + 43200.0) % 86400.0 - 43200.0
    return noon


class DayCycle:
    """The daily cycle around the sky: strength and depth of the moment, as shares of the day's peak."""

    def __init__(self, day, onset_deg=ONSET_DEG, cap_solar_h=DEPTH_CAP_SOLAR_H):
        self.day = day  # days since 1 January, as `FieldConfig.day`
        self.onset_deg = float(onset_deg)
        self.cap_solar_h = float(cap_solar_h)
        self._days = {}

    def _table(self, lat, lon, t):
        lat_c = round(lat / CELL_DEG) * CELL_DEG
        lon_c = round(lon / CELL_DEG) * CELL_DEG
        noon = t + 43200.0 - sun.solar_time_s(lon_c, self.day, t)
        # The solar day, counted from `day`: its noon is 12:00 UTC less 4 min per degree east,
        # give or take the equation of time (under 17 min), so this rounds to a whole number.
        solar_day = int(round((noon + 240.0 * lon_c - 43200.0) / 86400.0))
        key = (round(lat_c / CELL_DEG), round(lon_c / CELL_DEG), solar_day)
        table = self._days.get(key)
        if table is None:
            if len(self._days) >= CACHE_DAYS:
                self._days.pop(next(iter(self._days)))
            table = _Day(lat_c, lon_c, self.day, _solar_noon(lon_c, self.day, solar_day),
                         self.onset_deg, self.cap_solar_h)
            self._days[key] = table
        return table

    def strength_share(self, lat, lon, t):
        """w* of the moment over the day's peak w*, in [0, 1]. t is the field's t (UTC seconds of `day`)."""
        table = self._table(lat, lon, t)
        return table.at(table.strength, t)

    def depth_share(self, lat, lon, t):
        """zi of the moment over the afternoon's zi, in [0, 1]."""
        table = self._table(lat, lon, t)
        return table.at(table.depth, t)

    def blue(self, lat, lon, birth):
        """Is a thermal born here at `birth` too early for a cloud: zi still shallow?"""
        return self.depth_share(lat, lon, birth) < FIRST_CLOUDS_DEPTH
