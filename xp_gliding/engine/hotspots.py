"""Hotspot files: places on the ground where thermals start, for a hotspot flight.

A hotspot flight has thermals only where a file says they start, and none elsewhere: the random
field is not drawn (`field.ThermalField` with `hotspots`). The file is a CSV as thermal.kk7.ch gives
it under *Download currently visible hotspots → csv*: a header line, then one hotspot per line,

    latitude degree WGS84,longitude degree WGS84,altitude in meters AMSL,thermal probability ...
    -33.38272,-70.60844,643,100

the probability in percent, of finding a thermal within 250 m of the place. Any file with those four
columns is read the same way. A line that does not parse (the header, a blank or broken line) is
skipped and counted; so is a place off the globe or a probability that is not above 0.

A hotspot is a trigger on the ground, not a thermal, and it works in cycles: one thermal at a
time, then a pause, then the next (Juan Luis's choice, 2026-11-15). The share of the time it has a
thermal is its probability, as kk7 means it (the chance of finding one there), up to `DUTY_MAX`: a
hotspot of 100% has short pauses, one of 60% long ones. A Poisson number of thermals at the
probability's rate, tried first, had a hotspot of 100% working only 63% of the time, and stacking
more would put several thermals within 250 m, which the field adds into one far too strong.

The cycle runs from the hotspot's solar midnight (`chunk_start`), so each day's is worked out on its
own from (seed, day, the hotspot's place, that day): lives uniform as the field's among those long
enough for a cloud, pauses exponential with the mean that gives the probability. Each thermal starts
at a uniform place within `RADIUS_M` of the hotspot, and is placed in the air's frame where that
ground is at its birth (`air_at`), so it then drifts with the wind as any thermal does. Its numbers
are drawn as the field's, but always among those that carry a cloud: a hotspot thermal is a good one,
and a pilot finds it by its cloud. The field loads the thermals born in each slot (`generate`), so a
thermal alive now was born in this slot or the one before, as in the field. The same file, seed and
date give the same sky on every machine, whatever the order of the file's lines. The sun and the
daily cycle's depth apply as in the field; the good and bad areas do not, as they shape the random
field.

Thermals born before the flight began are placed with the wind of the moment, which holds for a
steady wind (`wind.AirDrift.to_air_at`).

Pure Python: no `xp`.
"""

import csv
import io
import math
import os

from . import sun
from .field import (CARRIER_MIN_FLUX, CARRIER_MIN_LIFE_S, RGAIN_RANGE, WGAIN_RANGE, Thermal,
                    is_carrier)
from .geo import radii_of_curvature, wrap_lon_deg
from .rng import SplitMix64, hash_key

HOTSPOT_STREAM = 0x484F5453  # part of every hotspot's key: these values are not any tile's
RADIUS_M = 250.0  # kk7's probability is for a circle this wide around the place
DUTY_MAX = 0.95  # the most of the time a hotspot has a thermal: one of 100% still pauses a little
DAY_S = 86400.0
CHAIN_CACHE = 4096  # days of hotspots' cycles kept
KEY_SCALE = 1e5  # a hotspot's place, rounded to about a metre, keys its stream
INDEX_DEG = 0.05  # the cells of the index for `near`
MIN_AREA_KM2 = 100.0  # the area the sink is spread over, at least, for a file of a few hotspots
DRAW_TRIES = 200  # draws of a thermal's gains before taking the carriers' threshold (1 in 10^5)
EXTENSIONS = (".csv",)


class Hotspot:
    """One place where thermals start: lat/lon (degrees), its altitude (m MSL), and the share of
    the time it works, 0 to 1."""

    __slots__ = ("lat", "lon", "alt_m", "p", "key")

    def __init__(self, lat, lon, alt_m, p):
        self.lat = float(lat)
        self.lon = float(lon)
        self.alt_m = float(alt_m)
        self.p = float(p)
        self.key = (round(self.lat * KEY_SCALE), round(self.lon * KEY_SCALE))


def parse(text):
    """(hotspots, skipped) from a hotspot CSV's text."""
    hotspots, skipped = [], 0
    for row in csv.reader(io.StringIO(text)):
        if not row or not any(field.strip() for field in row):
            continue
        try:
            lat, lon, alt, p = (float(field) for field in row[:4])
        except ValueError:
            skipped += 1
            continue
        if not all(math.isfinite(v) for v in (lat, lon, alt, p)) or abs(lat) > 90.0 or abs(lon) > 180.0 or p <= 0.0:
            skipped += 1
            continue
        hotspots.append(Hotspot(lat, lon, alt, min(p, 100.0) / 100.0))
    return hotspots, skipped


def find_files(folder):
    """The hotspot files in a folder, by name, sorted; none if it is missing."""
    try:
        names = os.listdir(folder)
    except OSError:
        return []
    return sorted((name for name in names
                   if name.lower().endswith(EXTENSIONS) and os.path.isfile(os.path.join(folder, name))),
                  key=str.lower)


def load(path):
    """The `HotspotSet` in a file. Raises OSError if it cannot be read."""
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        hotspots, skipped = parse(f.read())
    return HotspotSet(hotspots, skipped, os.path.basename(path))


class HotspotSet:
    """The hotspots of one file, indexed by place, and the thermals they fire."""

    def __init__(self, hotspots, skipped=0, name=""):
        self.hotspots = list(hotspots)
        self.skipped = int(skipped)
        self.name = name
        self._index = {}
        self._cycles = {}  # see `cycle_of`
        for k, h in enumerate(self.hotspots):
            self._index.setdefault(self._cell(h.lat, h.lon), []).append(k)

    def __len__(self):
        return len(self.hotspots)

    @staticmethod
    def _cell(lat, lon):
        return math.floor(lat / INDEX_DEG), math.floor(wrap_lon_deg(lon) / INDEX_DEG)

    def near(self, lat, lon, range_m):
        """Indices of the hotspots within range_m of (lat, lon) on the ground."""
        m, n = radii_of_curvature(lat)
        cos_lat = max(math.cos(math.radians(lat)), 1e-6)
        di = math.ceil(range_m / (math.radians(INDEX_DEG) * m))
        dj = math.ceil(range_m / (math.radians(INDEX_DEG) * n * cos_lat))
        i0, j0 = self._cell(lat, lon)
        cells_around = round(360.0 / INDEX_DEG)
        found = []
        for i in range(i0 - di, i0 + di + 1):
            for j in range(j0 - dj, j0 + dj + 1):
                jj = (j + cells_around // 2) % cells_around - cells_around // 2  # across 180°
                for k in self._index.get((i, jj), ()):
                    h = self.hotspots[k]
                    de = math.radians(wrap_lon_deg(h.lon - lon)) * n * cos_lat
                    dn = math.radians(h.lat - lat) * m
                    if de * de + dn * dn <= range_m * range_m:
                        found.append(k)
        return found

    def area_km2(self):
        """The area the file covers: its hotspots' bounding box, at least `MIN_AREA_KM2`."""
        if not self.hotspots:
            return MIN_AREA_KM2
        lats = [h.lat for h in self.hotspots]
        lons = [h.lon for h in self.hotspots]
        lat_c = 0.5 * (min(lats) + max(lats))
        m, n = radii_of_curvature(lat_c)
        height = math.radians(max(lats) - min(lats)) * m
        width = math.radians(max(lons) - min(lons)) * n * math.cos(math.radians(lat_c))
        return max(height * width * 1e-6, MIN_AREA_KM2)

    def alive_per_km2(self):
        """Hotspot thermals alive on average per km2 over the file's area."""
        return sum(duty(h.p) for h in self.hotspots) / self.area_km2()

    def cycle_of(self, config, index, chunk):
        """The cycle of hotspot `index` over day `chunk` (`chunk_start`): (n, birth, life) of each
        thermal, in order, one after another, all within the day. Kept, as each of the day's
        slots asks for it."""
        h = self.hotspots[index]
        life_lo, life_hi = _lives(config)
        key = (config.seed, config.day, index, chunk, life_lo, life_hi)
        found = self._cycles.get(key)
        if found is not None:
            return found
        if len(self._cycles) >= CHAIN_CACHE:
            self._cycles.clear()
        rng = SplitMix64(hash_key(config.seed, config.day, HOTSPOT_STREAM, h.key[0], h.key[1], chunk))
        mean_pause = 0.5 * (life_lo + life_hi) * (1.0 - duty(h.p)) / duty(h.p)
        start = chunk_start(h.lon, chunk)
        end = start + DAY_S
        found, when = [], start
        while True:
            when += -mean_pause * math.log(1.0 - rng.uniform())  # the pause before this one
            life = rng.uniform_range(life_lo, life_hi)
            if when + life > end:  # none crosses solar midnight, where the next day's cycle begins
                break
            found.append((len(found), when, life))
            when += life
        self._cycles[key] = found
        return found

    def generate(self, config, index, slot, air_at=None, cycle=None):
        """Thermals of hotspot `index` born in time slot `slot`. Pure function of its arguments.

        air_at(lat, lon, t) gives where a point of the ground at time t is in the air's frame;
        None: no wind, the same place. cycle: the sky's `DayCycle`, for each thermal's depth.
        """
        h = self.hotspots[index]
        if config.depth_cycle and cycle is None:
            cycle = config.cycle()
        t0 = slot * config.slot_s
        t1 = t0 + config.slot_s
        m, n = radii_of_curvature(h.lat)
        cos_lat = max(math.cos(math.radians(h.lat)), 1e-6)
        sky = config.sky
        thermals = []
        for chunk in range(chunk_of(h.lon, t0), chunk_of(h.lon, t1) + 1):
            for k, birth, life in self.cycle_of(config, index, chunk):
                if not t0 <= birth < t1:
                    continue
                # Its own stream, so where and how strong it is never moves its cycle.
                rng = SplitMix64(hash_key(config.seed, config.day, HOTSPOT_STREAM, h.key[0], h.key[1],
                                          chunk, k))
                r = RADIUS_M * math.sqrt(rng.uniform())
                a = 2.0 * math.pi * rng.uniform()
                lat = h.lat + math.degrees(r * math.cos(a) / m)
                lon = wrap_lon_deg(h.lon + math.degrees(r * math.sin(a) / (n * cos_lat)))
                wgain, rgain = _carrier_gains(rng, config, life)
                if config.sun_min_deg is not None and not sun.sunlit(lat, lon, config.day, birth,
                                                                      config.sun_min_deg):
                    continue
                if air_at is not None:
                    lat, lon = air_at(lat, lon, birth)
                depth = cycle.depth_share(lat, lon, birth) if config.depth_cycle else 1.0
                thermals.append(Thermal(lat, lon, birth, birth + life, wgain, rgain,
                                        sky.carrier_gain, sky.carrier_stretch, depth))
        return thermals


def duty(p):
    """The share of the time a hotspot of probability p (0 to 1) has a thermal."""
    return min(p, DUTY_MAX)


def chunk_start(lon, chunk):
    """When day `chunk` of a hotspot's cycle begins: its solar midnight, in the field's t (UTC s)."""
    return chunk * DAY_S - lon / 360.0 * DAY_S


def chunk_of(lon, t):
    """The day of a hotspot's cycle that time t is in."""
    return math.floor((t + lon / 360.0 * DAY_S) / DAY_S)


def _lives(config):
    """The thermals' shortest and longest lives (s): the field's, long enough for a cloud."""
    return min(max(CARRIER_MIN_LIFE_S, config.lifetime_min_s), config.lifetime_max_s), config.lifetime_max_s


def _carrier_gains(rng, config, life):
    """(wgain, rgain) drawn as the field's, among those that carry a cloud."""
    for _ in range(DRAW_TRIES):
        wgain = min(max(rng.lognormal_unit_mean(config.wgain_sigma), WGAIN_RANGE[0]), WGAIN_RANGE[1])
        rgain = min(max(rng.lognormal_unit_mean(config.rgain_sigma), RGAIN_RANGE[0]), RGAIN_RANGE[1])
        if is_carrier(wgain, rgain, life):
            return wgain, rgain
    return CARRIER_MIN_FLUX, 1.0  # just a carrier: wgain * rgain^2 at the threshold


def carrier_mean_flux(config):
    """Mean of wgain * rgain^2 among the drawn thermals that carry a cloud (clamps left out).

    A lognormal's mean above the threshold: E[X | X >= c] = e^(mu + s2/2) Phi(mu + s2 - ln c) /
    Phi(mu - ln c), with the field's mu and s2 for wgain * rgain^2 (`field.carrier_flux_share`).
    """
    wvar, rvar = config.wgain_sigma ** 2, config.rgain_sigma ** 2
    mu = -0.5 * wvar - rvar
    s2 = wvar + 4.0 * rvar
    s = math.sqrt(2.0 * s2)
    lnc = math.log(CARRIER_MIN_FLUX)
    above = 0.5 * math.erfc((lnc - mu - s2) / s)
    share = 0.5 * math.erfc((lnc - mu) / s)
    return math.exp(mu + 0.5 * s2) * above / share
