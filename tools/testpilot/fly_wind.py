"""XP12's wind and the thermals, flown by the test pilot.

Usage (X-Plane running with the xp-gliding plugin):
    python tools/testpilot/fly_wind.py measure [--wind-kt 15] [--from-deg 270] [--seconds 60]
    python tools/testpilot/fly_wind.py circle [--wind-kt 15] [--from-deg 270] [--turns 6]
        [--bank 35] [--kmh 95] [--agl 1000]

measure: straight flight in a uniform wind. Is `sim/weather/aircraft/wind_now_*` the wind
that moves the glider, with the sign the plugin assumes? It compares the dataref, and the
offset the plugin integrates from it, against the difference between the glider's velocity
over the ground and through the air, and against the wind asked for.

circle: the same thermal in calm air and in wind. It rebuilds the plugin's sky and picks the
best thermal near the start. With all its guidance in the air's frame, it flies a straight
line that passes one turn radius to the right of the thermal, and rolls into a left turn
abeam of it, so the circle starts around the thermal with no orbit controller to swing it.
Then it holds the bank with no correction at all, which is the test: in a uniform wind the
circle should stay on the thermal as it does in calm air. Run it at 0, 15 and 25 kt and
compare. Same seed, day, hour and place, so the same thermal.

Measurement tool, not part of the plugin. License: GPL-3.0-or-later.
"""

import argparse
import math
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)

from airstart import KHOB, air_start, weather  # noqa: E402
from pilot import AGL, BETA, IAS, LAT, LON, SIM_TIME, TAS, TE, VX, VZ, Pilot, plugin_sky, release, take_over_logger  # noqa: E402
from xp_gliding.engine.field import FieldConfig, ThermalField  # noqa: E402
from xp_gliding.engine.geo import LocalFrame, wrap_lon_deg  # noqa: E402
from xpweb import XPlaneStream, XPlaneWebAPI  # noqa: E402

KT = 0.514444
PSI = "sim/flightmodel/position/psi"
WIND_X, WIND_Z = "sim/weather/aircraft/wind_now_x_msc", "sim/weather/aircraft/wind_now_z_msc"
DLAT, DLON = "xp_gliding/wind/dlat_deg", "xp_gliding/wind/dlon_deg"
LIFT = "xp_gliding/lift_ms"
EXTRA = (PSI, WIND_X, WIND_Z, DLAT, DLON, LIFT)
LEAD_M = 45.0  # before the point abeam of the thermal: the roll takes a few seconds


def wind_toward(kt, from_deg):
    """(east, north) m/s of a wind of kt knots from from_deg."""
    a = math.radians(from_deg)
    return -kt * KT * math.sin(a), -kt * KT * math.cos(a)


def windy_start(api, msl, kmh, heading, wind_kt, from_deg):
    lat, lon, elev = KHOB
    # The same wind at every height, through and above where the glider flies.
    wind = [(elev / 0.3048 + alt, wind_kt, from_deg, 0.0) for alt in (500.0, 3000.0, 6000.0, 12000.0)] if wind_kt > 0.0 else []
    air_start(api, msl, kmh, heading, lat, lon, wx=weather(lat, lon, elev, wind=wind))
    take_over_logger(api)


class Offset:
    """The plugin's offset, and positions in the air's frame."""

    def __init__(self, stream):
        self.stream = stream
        self.dlat = self.dlon = 0.0

    def read(self):
        values, _ = self.stream.snapshot()
        self.dlat, self.dlon = values[DLAT], values[DLON]
        return values

    def to_air(self, lat, lon):
        return lat - self.dlat, wrap_lon_deg(lon - self.dlon)


# --- measure ----------------------------------------------------------------------------

def run_measure(api, wind_kt, from_deg, seconds, kmh=90.0):
    lat0, lon0, elev = KHOB
    # Across the wind, so the two velocities differ the most.
    windy_start(api, elev + 1500.0, kmh, (from_deg + 90.0) % 360.0, wind_kt, from_deg)
    stream = XPlaneStream(api, EXTRA)
    stream.wait_for(EXTRA)
    frame = LocalFrame(lat0, lon0)
    rows = []

    def on_step(v, pilot):
        if pilot.flown < 20.0:  # the speed and the wings settle first
            return
        values, _ = stream.snapshot()
        path = math.radians(values[PSI] - v[BETA])  # X-Plane's beta: nose right of the path
        ve, vn = v[VX], -v[VZ]
        rows.append({"t": v[SIM_TIME],
                     "ground_air_e": ve - v[TAS] * math.sin(path),
                     "ground_air_n": vn - v[TAS] * math.cos(path),
                     "now_e": values[WIND_X], "now_n": -values[WIND_Z],
                     "dlat": values[DLAT], "dlon": values[DLON]})

    pilot = Pilot(api, frame)
    try:
        reason, _ = pilot.run(kmh, seconds + 20.0, settle_s=5.0, min_agl=300.0, on_step=on_step, quiet=True)
    finally:
        stream.close()
    print(f"measure: {reason}; {len(rows)} samples over {rows[-1]['t'] - rows[0]['t']:.0f} s")
    asked = wind_toward(wind_kt, from_deg)
    mean = lambda key: statistics.fmean(r[key] for r in rows)  # noqa: E731
    first, last = rows[0], rows[-1]
    span = last["t"] - first["t"]
    e, n = frame.to_enu(lat0 + last["dlat"] - first["dlat"], lon0 + last["dlon"] - first["dlon"])
    print(f"  asked for                 e {asked[0]:+6.2f}  n {asked[1]:+6.2f} m/s")
    print(f"  wind_now_*                e {mean('now_e'):+6.2f}  n {mean('now_n'):+6.2f} m/s")
    print(f"  ground minus air          e {mean('ground_air_e'):+6.2f}  n {mean('ground_air_n'):+6.2f} m/s")
    print(f"  the plugin's offset rate  e {e / span:+6.2f}  n {n / span:+6.2f} m/s")


# --- circle -----------------------------------------------------------------------------

def wrap180(a):
    return (a + 180.0) % 360.0 - 180.0


class AirLine:
    """Straight at a point of the air's frame, using the track through the air."""

    def __init__(self, aim, mission, k=0.7, max_bank=20.0):
        self.ae, self.an = aim
        self.mission, self.k, self.max_bank = mission, k, max_bank

    def remaining(self):
        return math.hypot(self.ae - self.mission.air_e, self.an - self.mission.air_n)

    def bank(self, track_deg, east_m, north_m):
        m = self.mission
        course = math.degrees(math.atan2(self.ae - m.air_e, self.an - m.air_n))
        return max(-self.max_bank, min(self.max_bank, self.k * wrap180(course - m.air_track)))


class FixedBank:
    def __init__(self, bank_deg):
        self.value = bank_deg

    def bank(self, track_deg, east_m, north_m):
        return self.value


class CircleMission:
    def __init__(self, api, stream, kmh, bank, turns, wstar, zi, seed, day, sky, zulu0, sim0, radius):
        self.api, self.offset, self.stream = api, Offset(stream), stream
        self.kmh, self.bank, self.turns = kmh, bank, turns
        self.wstar, self.zi = wstar, zi
        self.seed, self.day, self.sky = seed, day, sky
        self.zulu0, self.sim0 = zulu0, sim0
        self.radius = radius  # of the circle this glider really flies at this bank (measured)
        self.frame = self.field = self.thermal = self.line = None
        self.ce = self.cn = 0.0
        self.air_e = self.air_n = self.air_track = 0.0
        self.state, self.since = "start", 0.0
        self.turn_s = 0.0
        self.rows = []
        self.ground_start = None

    def choose(self, lat, lon, z, t):
        self.frame = LocalFrame(*self.offset.to_air(lat, lon))
        self.field = ThermalField(FieldConfig(seed=self.seed, day=self.day, sky=self.sky), self.frame)
        self.field.update(t, *self.offset.to_air(lat, lon))
        radius = self.radius
        best, best_score = None, -math.inf
        for th in self.field.alive(t):
            d = math.hypot(th.e, th.n)
            if d > 2500.0 or th.death - t < 900.0:
                continue
            ring = statistics.fmean(
                self.field.lift_at(th.e + radius * math.cos(a), th.n + radius * math.sin(a), z, t,
                                   self.wstar, self.zi)
                for a in (2.0 * math.pi * k / 16 for k in range(16)))
            score = ring - 0.0002 * d
            if score > best_score:
                best, best_score = th, score
        if best is None:
            raise RuntimeError("no thermal within reach")
        self.thermal = best
        self.ce, self.cn = best.e, best.n
        self.air_e, self.air_n = self.frame.to_enu(*self.offset.to_air(lat, lon))
        # A line passing one radius to the right of the thermal, for a turn to the left.
        to_e, to_n = best.e - self.air_e, best.n - self.air_n
        d = math.hypot(to_e, to_n)
        aim = (best.e + radius * to_n / d, best.n - radius * to_e / d)
        self.line = AirLine(aim, self)
        print(f"  thermal at {best.lat:.5f}, {best.lon:.5f}: {d:.0f} m away, "
              f"lift {best_score:+.2f} m/s on a circle of {radius:.0f} m", flush=True)

    def on_step(self, v, pilot):
        values = self.offset.read()
        t = self.zulu0 + v[SIM_TIME] - self.sim0
        if self.state == "start":
            if pilot.flown < 10.0:  # the speed settles first
                return
            self.choose(v[LAT], v[LON], v[AGL], t)
            self.state = "approach"
            pilot.guidance = self.line
        self.air_e, self.air_n = self.frame.to_enu(*self.offset.to_air(v[LAT], v[LON]))
        self.air_track = (values[PSI] - v[BETA]) % 360.0
        d = math.hypot(self.ce - self.air_e, self.cn - self.air_n)
        if self.state == "approach" and self.line.remaining() < LEAD_M:
            self.state, self.since = "rolling", pilot.flown
            pilot.guidance = FixedBank(-self.bank)  # to the left
            print(f"  {pilot.flown:5.0f}s abeam of the thermal, {d:.0f} m from it: rolling in", flush=True)
        elif self.state == "rolling" and pilot.flown - self.since >= 15.0:
            self.state, self.since = "free", pilot.flown
            self.turn_s = 2.0 * math.pi * self.radius / max(v[TAS], 10.0)
            print(f"  {pilot.flown:5.0f}s in the turn, {d:.0f} m from the centre: "
                  f"counting turns of about {self.turn_s:.0f} s", flush=True)
        if self.state == "free":
            self.rows.append({"flown": pilot.flown, "d": d, "e": self.air_e, "n": self.air_n,
                              "te": v[TE] * 0.00508, "lift": values[LIFT], "agl": v[AGL],
                              "lat": v[LAT], "lon": v[LON], "ias": v[IAS] * 1.852,
                              "phi": v["sim/flightmodel/position/phi"]})

    def done(self, v, pilot):
        return self.state == "free" and pilot.flown - self.since >= self.turns * self.turn_s

    def report(self, reason):
        print(f"circle: {reason}; {len(self.rows)} samples with the bank held")
        if not self.rows:
            return
        turn = max(self.turn_s, 1.0)
        start = self.rows[0]["flown"]
        print("  turn | climb m/s | lift m/s | from centre: mean, min, max m | circle's centre from the thermal, m")
        for k in range(self.turns):
            rows = [r for r in self.rows if start + k * turn <= r["flown"] < start + (k + 1) * turn]
            if len(rows) < 10:
                break
            ce = statistics.fmean(r["e"] for r in rows)
            cn = statistics.fmean(r["n"] for r in rows)
            print(f"  {k + 1:4d} | {statistics.fmean(r['te'] for r in rows):+9.2f} | "
                  f"{statistics.fmean(r['lift'] for r in rows):+8.2f} | "
                  f"{statistics.fmean(r['d'] for r in rows):6.0f} {min(r['d'] for r in rows):6.0f} "
                  f"{max(r['d'] for r in rows):6.0f} | "
                  f"{math.hypot(ce - self.ce, cn - self.cn):6.0f}")
        first, last = self.rows[0], self.rows[-1]
        frame = LocalFrame(first["lat"], first["lon"])
        ground = math.hypot(*frame.to_enu(last["lat"], last["lon"]))
        print(f"  over {last['flown'] - first['flown']:.0f} s: climbed {last['agl'] - first['agl']:+.0f} m "
              f"({first['agl']:.0f} to {last['agl']:.0f} AGL), {ground:.0f} m over the ground; "
              f"IAS {statistics.fmean(r['ias'] for r in self.rows):.0f} km/h, "
              f"bank {statistics.fmean(abs(r['phi']) for r in self.rows):.0f} deg")


def run_circle(api, wind_kt, from_deg, turns, bank, kmh, agl, radius):
    _, _, elev = KHOB
    windy_start(api, elev + agl, kmh, 90.0, wind_kt, from_deg)
    api.set("xp_gliding/thermals_enabled", 1)
    wstar, zi = api.get("xp_gliding/wstar_ms"), api.get("xp_gliding/zi_m")
    seed, day = int(api.get("xp_gliding/seed")), int(api.get("sim/time/local_date_days"))
    zulu0, sim0 = api.get("sim/time/zulu_time_sec"), api.get(SIM_TIME)
    stream = XPlaneStream(api, EXTRA)
    stream.wait_for(EXTRA)
    mission = CircleMission(api, stream, kmh, bank, turns, wstar, zi, seed, day, plugin_sky(api), zulu0, sim0, radius)
    pilot = Pilot(api)
    try:
        reason, _ = pilot.run(kmh, 900.0, settle_s=5.0, min_agl=250.0, bank_limit=bank + 25.0,
                              on_step=mission.on_step, until=mission.done, quiet=True)
    except Exception as exc:
        reason = f"aborted: {exc}"
        release(api)
    stream.close()
    mission.report(reason)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = parser.add_subparsers(dest="what", required=True)
    p = sub.add_parser("measure")
    p.add_argument("--wind-kt", type=float, default=15.0)
    p.add_argument("--from-deg", type=float, default=270.0)
    p.add_argument("--seconds", type=float, default=60.0)
    p = sub.add_parser("circle")
    p.add_argument("--wind-kt", type=float, default=15.0)
    p.add_argument("--from-deg", type=float, default=270.0)
    p.add_argument("--turns", type=int, default=6)
    p.add_argument("--bank", type=float, default=35.0)
    p.add_argument("--kmh", type=float, default=95.0)
    p.add_argument("--agl", type=float, default=1000.0)
    p.add_argument("--radius", type=float, default=105.0)
    args = parser.parse_args(argv)
    api = XPlaneWebAPI(timeout=30.0)
    if args.what == "measure":
        run_measure(api, args.wind_kt, args.from_deg, args.seconds)
    else:
        run_circle(api, args.wind_kt, args.from_deg, args.turns, args.bank, args.kmh, args.agl, args.radius)


if __name__ == "__main__":
    main()
