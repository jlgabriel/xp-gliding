"""XP12's wind and the thermals, flown by the test pilot.

Usage (X-Plane running with the xp-gliding plugin):
    python tools/testpilot/fly_wind.py measure [--wind-kt 15] [--from-deg 270] [--seconds 60]
    python tools/testpilot/fly_wind.py circle [--wind-kt 15] [--from-deg 270] [--turns 6]
        [--bank 35] [--kmh 95] [--agl 1000] [--lean] [--record]
    python tools/testpilot/fly_wind.py layers [--wind-kt 15] [--from-deg 270] [--shear]
    python tools/testpilot/fly_wind.py look [--wind-kt 25] [--from-deg 270] [--agl 700]
    python tools/testpilot/fly_wind.py shear [--profile gentle] [--at-clouds] [--correct] [--turns 10]
        [--agl 600] [--bank 35] [--kmh 95] [--fresh] [--record]
    python tools/testpilot/fly_wind.py stretch [--profile gentle] [--at-clouds] [--agl 800] [--seconds 280]

shear: the circle below in a wind that changes with height, carried by the wind at the glider or
(--at-clouds) at the clouds. With no correction it shows how fast the circle falls off the
thermal. With --correct a pilot reads the lift around the last turn and rolls out for up to 4 s
of the next turn toward its strongest side, up to 100 m per turn (`shear_climb.py`'s hard pilot,
with a perfect vario and no error of direction).

stretch: do clouds stretch? A straight flight across the wind for longer than a particle lives,
with screenshots from the front. The glider sinks about 1 m/s through the shear. A SHOT line per
screenshot gives the camera and the thermals with a cloud, to draw each emitter on it.

layers: do `sim/weather/aircraft/wind_*`, which the thermals' lean reads, agree with the wind at
the glider? Short flights at several heights, comparing the layer at the glider's height with
`wind_now_*`, and the lean the plugin publishes with what the engine gives for those layers.

look: flies at a thermal with a cloud, across the wind, with the markers on, and takes a
screenshot with the lean off and one with it on from about the same place. The column should
lean, with its bottom upwind.

--lean in circle: the same flight with the thermals leaning, and the guidance knows. The lift
at the glider is checked against the engine's at every sample.

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
import json
import math
import os
import statistics
import sys
import time
import types

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)

from airstart import KHOB, air_start, weather  # noqa: E402
from pilot import AGL, BETA, ELEV, IAS, LAT, LON, SIM_TIME, TAS, TE, VX, VZ, Pilot, plugin_sky, release, take_over_logger  # noqa: E402
from xp_gliding.adapter.core import wind_layers  # noqa: E402
from xp_gliding.engine import clouds as cl  # noqa: E402
from xp_gliding.engine.field import FieldConfig, ThermalField  # noqa: E402
from xp_gliding.engine.geo import LocalFrame, wrap_lon_deg  # noqa: E402
from xp_gliding.engine.wind import Lean, _interpolate  # noqa: E402
from xpweb import XPlaneStream, XPlaneWebAPI  # noqa: E402

KT = 0.514444
PSI = "sim/flightmodel/position/psi"
WIND_X, WIND_Z = "sim/weather/aircraft/wind_now_x_msc", "sim/weather/aircraft/wind_now_z_msc"
DLAT, DLON = "xp_gliding/wind/dlat_deg", "xp_gliding/wind/dlon_deg"
LIFT = "xp_gliding/lift_ms"
LIFT_CENTRE = "xp_gliding/lift_centre_ms"
LEAN_ON, LEAN_E, LEAN_N = "xp_gliding/lean_enabled", "xp_gliding/lean/e_m", "xp_gliding/lean/n_m"
PROBE_SKY, PROBE_LOCAL = "xp_gliding/markers/probe_distance_m", "xp_gliding/markers/probe_local_distance_m"
EXTRA = (PSI, WIND_X, WIND_Z, DLAT, DLON, LIFT, LIFT_CENTRE, LEAN_E, LEAN_N)
LEAD_M = 45.0  # before the point abeam of the thermal: the roll takes a few seconds
LEAN_WAIT_S = 7.0  # the plugin reads the layers of wind every 5 s
SCREENSHOT = "sim/operation/screenshot"
FRONT_VIEW, COCKPIT_VIEW = "sim/view/forward_with_nothing", "sim/view/3d_cockpit_cmnd_look"
LAYER_ALT, LAYER_SPEED, LAYER_FROM = ("sim/weather/aircraft/wind_altitude_msl_m",
                                      "sim/weather/aircraft/wind_speed_kts",
                                      "sim/weather/aircraft/wind_direction_degt")
# Layers in feet above the field, and their share of --wind-kt.
UNIFORM = ((500.0, 1.0), (3000.0, 1.0), (6000.0, 1.0), (12000.0, 1.0))
SHEAR = ((500.0, 0.2), (3000.0, 0.5), (6000.0, 1.2), (12000.0, 2.0))
# 3 m/s of difference across the climb at 15 kt: 9 kt up to 500 m above the field, 15 kt from 1500 m.
GENTLE = ((500.0, 0.6), (1640.0, 0.6), (4921.0, 1.0), (12000.0, 1.0))
# (layers, the wind asked for, in kt)
PROFILES = {"uniform": (UNIFORM, 15.0), "gentle": (GENTLE, 15.0), "strong": (SHEAR, 25.0)}
AT_CLOUDS = "xp_gliding/wind_at_clouds"
SKY_E, SKY_N = "xp_gliding/wind/e_ms", "xp_gliding/wind/n_ms"
MAX_SHIFT_M = 100.0  # the most a correction shifts the circle in one turn
SHIFT_PER_MS = 60.0  # metres of shift per m/s of swing in the lift around the last turn
ROLL_OUT_BANK = 5.0  # deg, while shifting


def wind_toward(kt, from_deg):
    """(east, north) m/s of a wind of kt knots from from_deg."""
    a = math.radians(from_deg)
    return -kt * KT * math.sin(a), -kt * KT * math.cos(a)


def windy_start(api, msl, kmh, heading, wind_kt, from_deg, layers=UNIFORM):
    lat, lon, elev = KHOB
    # By default the same wind at every height, through and above where the glider flies.
    wind = [(elev / 0.3048 + alt, wind_kt * share, from_deg, 0.0) for alt, share in layers] if wind_kt > 0.0 else []
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


# --- layers -----------------------------------------------------------------------------

def run_layers(api, wind_kt, from_deg, shear, real=False, heights=(150.0, 500.0, 1000.0, 1500.0, 2500.0), kmh=90.0):
    lat, lon, elev = KHOB
    base = None
    print("| AGL (m) | wind_now e, n (m/s) | Layers at the glider e, n | Off (m/s) | Plugin's lean e, n (m) "
          "| Engine's lean from the layers e, n | Off (m) |")
    print("|" + " --- |" * 7)
    for agl in heights:
        if real:
            air_start(api, elev + agl, kmh, (from_deg + 90.0) % 360.0, lat, lon, wx="use_real_weather")
            take_over_logger(api)
        else:
            windy_start(api, elev + agl, kmh, (from_deg + 90.0) % 360.0, wind_kt, from_deg, SHEAR if shear else UNIFORM)
        api.set(LEAN_ON, 1)
        stream = XPlaneStream(api, EXTRA)
        stream.wait_for(EXTRA)
        try:
            # Long enough for the plugin to read the layers once, with this flight's first read.
            reason, _ = Pilot(api).run(kmh, LEAN_WAIT_S + 3.0, settle_s=5.0, min_agl=30.0, quiet=True)
            values, _ = stream.snapshot()
            msl, here = api.get(ELEV), api.get(AGL)
            alts, speeds, froms = api.get(LAYER_ALT), api.get(LAYER_SPEED), api.get(LAYER_FROM)
        finally:
            stream.close()
        ground = msl - here
        heights_agl, east, north = wind_layers(alts, speeds, froms, ground)
        e_now, n_now = values[WIND_X], -values[WIND_Z]
        e_layer, n_layer = _interpolate(here, heights_agl, east), _interpolate(here, heights_agl, north)
        wstar, zi = api.get("xp_gliding/wstar_ms"), api.get("xp_gliding/zi_m")
        base = plugin_sky(api).cloud_base_zzi * zi
        lean = Lean(smooth_s=0.0)
        lean.set_wind(heights_agl, east, north, base, wstar, 0.0)
        le, ln = lean.at(here)
        print(f"| {here:.0f} | {e_now:+.2f}, {n_now:+.2f} | {e_layer:+.2f}, {n_layer:+.2f} "
              f"| {math.hypot(e_layer - e_now, n_layer - n_now):.2f} "
              f"| {values[LEAN_E]:+.0f}, {values[LEAN_N]:+.0f} | {le:+.0f}, {ln:+.0f} "
              f"| {math.hypot(le - values[LEAN_E], ln - values[LEAN_N]):.1f} |", flush=True)
        if agl == heights[0]:
            print("<!-- layers MSL m: " + ", ".join(f"{a:.0f}" for a in alts) + " | kt: "
                  + ", ".join(f"{s:.1f}" for s in speeds) + " | from: "
                  + ", ".join(f"{d:.0f}" for d in froms) + " -->", flush=True)
    api.set(LEAN_ON, 0)
    print(f"base {base:.0f} m AGL, {reason}")


# --- look -------------------------------------------------------------------------------

def run_look(api, wind_kt, from_deg, agl, kmh=90.0):
    """Toward a thermal with a cloud that lies across the wind, lean off and then on."""
    _, _, elev = KHOB
    heading = (from_deg + 90.0) % 360.0
    windy_start(api, elev + agl, kmh, heading, wind_kt, from_deg)
    api.set(LEAN_ON, 0)
    api.set("xp_gliding/markers_enabled", 1)
    api.set("xp_gliding/thermals_enabled", 1)
    wstar, zi = api.get("xp_gliding/wstar_ms"), api.get("xp_gliding/zi_m")
    seed, day = int(api.get("xp_gliding/seed")), int(api.get("sim/time/local_date_days"))
    zulu0, sim0 = api.get("sim/time/zulu_time_sec"), api.get(SIM_TIME)
    sky = plugin_sky(api)
    stream = XPlaneStream(api, EXTRA + (PROBE_SKY, PROBE_LOCAL))
    stream.wait_for(EXTRA)
    offset = Offset(stream)
    state = {"phase": "start", "since": 0.0}
    mission = types.SimpleNamespace(air_e=0.0, air_n=0.0, air_track=0.0)
    frame_box = {}

    def choose(v, t):
        air = offset.to_air(v[LAT], v[LON])
        frame = frame_box["frame"] = LocalFrame(*air)
        field = ThermalField(FieldConfig(seed=seed, day=day, sky=sky), frame)
        field.update(t, *air)
        params = cl.CloudParams()
        best, best_score = None, -math.inf
        for th in field.alive(t):
            d = math.hypot(th.e, th.n)
            if not 1300.0 < d < 3500.0 or not cl.carries_cloud(th, params):
                continue
            start, stop = cl.feeding_window(th, params)
            if not start + 0.5 * params.ttl_s <= t < stop:
                continue
            bearing = math.degrees(math.atan2(th.e, th.n))
            across = abs(math.sin(math.radians(bearing - from_deg)))
            ahead = math.cos(math.radians(bearing - heading))
            score = across + 0.5 * ahead - d / 20000.0
            if score > best_score:
                best, best_score = th, score
        if best is None:
            raise RuntimeError("no formed cloud within reach")
        print(f"  thermal {math.hypot(best.e, best.n):.0f} m away, bearing "
              f"{math.degrees(math.atan2(best.e, best.n)) % 360.0:.0f}; the wind comes from {from_deg:.0f}", flush=True)
        return best

    def shot(name, values):
        api.command(FRONT_VIEW)
        time.sleep(0.5)
        api.command(SCREENSHOT)
        print(f"  screenshot, {name}: {pilot.flown:.0f} s; lean {values[LEAN_E]:+.0f}, {values[LEAN_N]:+.0f} m; "
              f"marker distance in the sky {values.get(PROBE_SKY, -1):.1f} m, on the scene "
              f"{values.get(PROBE_LOCAL, -1):.1f} m", flush=True)

    def on_step(v, pilot):
        values = offset.read()
        t = zulu0 + v[SIM_TIME] - sim0
        if state["phase"] == "start":
            if pilot.flown < 8.0:
                return
            th = state["th"] = choose(v, t)
            state["line"] = AirLine((th.e, th.n), mission)
            pilot.guidance = state["line"]
            state["phase"] = "toward"
        air = frame_box["frame"].to_enu(*offset.to_air(v[LAT], v[LON]))
        mission.air_e, mission.air_n = air
        mission.air_track = (values[PSI] - v[BETA]) % 360.0
        if state["phase"] == "toward" and state["line"].remaining() < 1500.0:
            shot("lean off", values)
            api.set(LEAN_ON, 1)
            state["phase"], state["since"] = "waiting", pilot.flown
        elif state["phase"] == "waiting" and pilot.flown - state["since"] > 2.0 * LEAN_WAIT_S:
            shot("lean on", values)
            state["phase"], state["since"] = "done", pilot.flown

    pilot = Pilot(api)
    try:
        reason, _ = pilot.run(kmh, 240.0, settle_s=5.0, min_agl=250.0, on_step=on_step,
                              until=lambda v, p: state["phase"] == "done" and p.flown - state["since"] > 3.0,
                              quiet=True)
    finally:
        stream.close()
        api.command(COCKPIT_VIEW)
        api.set(LEAN_ON, 0)
    print(f"look: {reason}, {state['phase']}")


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
        self.oracle = []  # the engine's lift at the glider, minus the plugin's
        self.ground_start = None
        self.wanted = None  # wanted(thermal, t): only these can be chosen
        self.floors = None  # floors(field): gives this oracle the plugin's floors. Without it, over
        # hills its lift differs from the plugin's (notes/phase4.md).
        self.ground_m = None  # the ground under the glider now, for an oracle with floors

    def choose(self, lat, lon, z, t):
        self.frame = LocalFrame(*self.offset.to_air(lat, lon))
        self.field = ThermalField(FieldConfig(seed=self.seed, day=self.day, sky=self.sky), self.frame)
        self.field.update(t, *self.offset.to_air(lat, lon))
        if self.floors:
            self.floors(self.field)
        radius = self.radius
        best, best_score = None, -math.inf
        for th in self.field.alive(t):
            d = math.hypot(th.e, th.n)
            if d > 2500.0 or th.death - t < 900.0 or (self.wanted and not self.wanted(th, t)):
                continue
            ring = statistics.fmean(
                self.field.lift_at(th.e + radius * math.cos(a), th.n + radius * math.sin(a), z, t,
                                   self.wstar, self.zi, self.ground_m)
                for a in (2.0 * math.pi * k / 16 for k in range(16)))
            score = ring - 0.0002 * d
            if score > best_score:
                best, best_score = th, score
        if best is None:
            raise RuntimeError("no thermal within reach")
        self.thermal = best
        self.ce, self.cn = best.e, best.n
        self.air_e, self.air_n = self.sky_position(lat, lon, self.stream.snapshot()[0])
        # A line passing one radius to the right of the thermal, for a turn to the left.
        to_e, to_n = best.e - self.air_e, best.n - self.air_n
        d = math.hypot(to_e, to_n)
        aim = (best.e + radius * to_n / d, best.n - radius * to_e / d)
        self.line = AirLine(aim, self)
        print(f"  thermal at {best.lat:.5f}, {best.lon:.5f}: {d:.0f} m away, "
              f"lift {best_score:+.2f} m/s on a circle of {radius:.0f} m; offset {self.offset.dlon:.4f} deg of longitude",
              flush=True)

    def sky_position(self, lat, lon, values):
        """Where the glider is in the field's sky: in the air's frame, less the lean."""
        e, n = self.frame.to_enu(*self.offset.to_air(lat, lon))
        return e - values[LEAN_E], n - values[LEAN_N]

    def on_step(self, v, pilot):
        values = self.offset.read()
        t = self.zulu0 + v[SIM_TIME] - self.sim0
        if self.floors:
            self.ground_m = v[ELEV] - v[AGL]
        if self.state == "start":
            if pilot.flown < 10.0:  # the speed settles first
                return
            self.choose(v[LAT], v[LON], v[AGL], t)
            self.state = "approach"
            pilot.guidance = self.line
        self.air_e, self.air_n = self.sky_position(v[LAT], v[LON], values)
        self.oracle.append(self.field.lift_at(self.air_e, self.air_n, v[AGL], t, self.wstar, self.zi, self.ground_m)
                           - values[LIFT_CENTRE])
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
                              "te": v[TE] * 0.00508, "lift": values[LIFT], "agl": v[AGL], "msl": v[ELEV],
                              "lat": v[LAT], "lon": v[LON], "ias": v[IAS] * 1.852,
                              "phi": v["sim/flightmodel/position/phi"]})

    def done(self, v, pilot):
        return self.state == "free" and pilot.flown - self.since >= self.turns * self.turn_s

    def report(self, reason):
        print(f"circle: {reason}; {len(self.rows)} samples with the bank held")
        if self.oracle:
            k = len(self.oracle)
            print(f"  the engine's lift minus the plugin's: RMS {math.sqrt(sum(x * x for x in self.oracle) / k):.3f} m/s, "
                  f"mean {sum(self.oracle) / k:+.3f}, over {k} samples")
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


class ShearMission(CircleMission):
    """The circle, in shear: it also records how the circle falls off the thermal, and may correct."""

    def __init__(self, *args, correct=False):
        super().__init__(*args)
        self.correct = correct
        self.turn_start = self.roll_out_until = 0.0
        self.pending = None  # (track to roll out on, seconds)
        self.shifts = []
        self.slip = []  # the wind at the glider minus the one that carries the sky

    def on_step(self, v, pilot):
        super().on_step(v, pilot)
        if self.state != "free":
            return
        values = self.stream.snapshot()[0]
        row = self.rows[-1]
        row["slip"] = math.hypot(values[WIND_X] - values[SKY_E], -values[WIND_Z] - values[SKY_N])
        # The centre of the circle at this moment: a turn to the left, so one radius left of the
        # track. Averaging positions over a turn that is not quite closed wobbles by 20 m or more.
        left = math.radians(self.air_track - 90.0)
        row["centre_e"] = row["e"] + self.radius * math.sin(left)
        row["centre_n"] = row["n"] + self.radius * math.cos(left)
        if self.correct:
            self.recentre(pilot)

    def recentre(self, pilot):
        if self.turn_start == 0.0:
            self.turn_start = pilot.flown
        if self.roll_out_until:
            if pilot.flown >= self.roll_out_until:
                self.roll_out_until = 0.0
                pilot.guidance = FixedBank(-self.bank)
            return
        if self.pending:
            track, seconds = self.pending
            # A turn to the left: the track falls, so start a little before it. It takes a moment to roll.
            if 0.0 <= wrap180(self.air_track - track) <= 25.0:
                self.pending = None
                self.roll_out_until = pilot.flown + seconds
                pilot.guidance = FixedBank(-ROLL_OUT_BANK)
            return
        if pilot.flown - self.turn_start >= self.turn_s:
            rows = [r for r in self.rows if r["flown"] >= self.turn_start]
            self.turn_start = pilot.flown
            ce = statistics.fmean(r["e"] for r in rows)
            cn = statistics.fmean(r["n"] for r in rows)
            angles = [math.atan2(r["n"] - cn, r["e"] - ce) for r in rows]
            c = 2.0 * statistics.fmean(r["lift"] * math.cos(a) for r, a in zip(rows, angles))
            s = 2.0 * statistics.fmean(r["lift"] * math.sin(a) for r, a in zip(rows, angles))
            shift = min(MAX_SHIFT_M, math.hypot(c, s) * SHIFT_PER_MS)
            speed = max(rows[-1]["ias"] / 3.6, 10.0)
            if shift > 10.0:
                # Toward the strongest side. Math angle to compass bearing.
                self.pending = ((90.0 - math.degrees(math.atan2(s, c))) % 360.0, shift / speed)
                self.shifts.append(shift)

    def done(self, v, pilot):
        return super().done(v, pilot) and not self.roll_out_until

    def report(self, reason):
        super().report(reason)
        if not self.rows:
            return
        turn = max(self.turn_s, 1.0)
        start = self.rows[0]["flown"]
        print("  turn | climb m/s | lift m/s | wind at glider minus the sky's m/s | circle's centre: "
              "from the thermal m, moved since the last turn m")
        last = None
        centres = []
        for k in range(self.turns):
            rows = [r for r in self.rows if start + k * turn <= r["flown"] < start + (k + 1) * turn and "centre_e" in r]
            if len(rows) < 10:
                break
            ce = statistics.fmean(r["centre_e"] for r in rows)
            cn = statistics.fmean(r["centre_n"] for r in rows)
            step = math.hypot(ce - last[0], cn - last[1]) if last else float("nan")
            last = ce, cn
            centres.append(last)
            print(f"  {k + 1:4d} | {statistics.fmean(r['te'] for r in rows):+9.2f} | "
                  f"{statistics.fmean(r['lift'] for r in rows):+8.2f} | "
                  f"{statistics.fmean(r.get('slip', 0.0) for r in rows):6.2f} | "
                  f"{math.hypot(ce - self.ce, cn - self.cn):6.0f} {step:6.0f}")
        if len(centres) > 1:
            net = math.hypot(centres[-1][0] - centres[0][0], centres[-1][1] - centres[0][1])
            print(f"  the circle moved {net / (len(centres) - 1):.0f} m per turn through the sky, net")
        if self.correct:
            print(f"  corrections: {len(self.shifts)}, mean {statistics.fmean(self.shifts) if self.shifts else 0.0:.0f} m "
                  f"of the {MAX_SHIFT_M:.0f} m allowed")


def run_shear(api, profile, at_clouds, correct, from_deg, turns, bank, kmh, agl, radius, record, fresh):
    _, _, elev = KHOB
    layers, wind_kt = PROFILES[profile]
    if fresh:
        api.command("sim/operation/reload_aircraft")
        time.sleep(5.0)
    windy_start(api, elev + agl, kmh, 90.0, wind_kt, from_deg, layers)
    api.set("xp_gliding/thermals_enabled", 1)
    api.set(LEAN_ON, 0)
    api.set(AT_CLOUDS, 1 if at_clouds else 0)
    wstar, zi = api.get("xp_gliding/wstar_ms"), api.get("xp_gliding/zi_m")
    seed, day = int(api.get("xp_gliding/seed")), int(api.get("sim/time/local_date_days"))
    zulu0, sim0 = api.get("sim/time/zulu_time_sec"), api.get(SIM_TIME)
    stream = XPlaneStream(api, EXTRA + (SKY_E, SKY_N))
    stream.wait_for(EXTRA)
    mission = ShearMission(api, stream, kmh, bank, turns, wstar, zi, seed, day, plugin_sky(api), zulu0, sim0,
                           radius, correct=correct)
    pilot = Pilot(api)
    print(f"shear: {profile}, carried by the wind at the {'clouds' if at_clouds else 'glider'}, "
          f"{'correcting' if correct else 'no correction'}", flush=True)
    try:
        reason, log = pilot.run(kmh, 900.0, settle_s=5.0, min_agl=200.0, bank_limit=bank + 25.0,
                                on_step=mission.on_step, until=mission.done, quiet=True, record=record)
        if log:
            print(f"  flight log: {log}, flown to {pilot.flown:.0f} s")
    except Exception as exc:
        reason = f"aborted: {exc}"
        release(api)
    stream.close()
    mission.report(reason)
    api.set(AT_CLOUDS, 0)


def run_stretch(api, profile, at_clouds, from_deg, agl, seconds, kmh=90.0):
    _, _, elev = KHOB
    layers, wind_kt = PROFILES[profile]
    heading = (from_deg + 90.0) % 360.0  # across the wind, so a stretch runs across the view
    windy_start(api, elev + agl, kmh, heading, wind_kt, from_deg, layers)  # the reload has no command at the main menu
    api.command("sim/operation/reload_aircraft")  # clears the sky's offset
    time.sleep(5.0)
    windy_start(api, elev + agl, kmh, heading, wind_kt, from_deg, layers)
    api.set(AT_CLOUDS, 1 if at_clouds else 0)
    api.set(LEAN_ON, 0)
    markers = api.get("xp_gliding/markers_enabled")
    api.set("xp_gliding/markers_enabled", 0)
    api.set("xp_gliding/thermals_enabled", 1)
    seed, day = int(api.get("xp_gliding/seed")), int(api.get("sim/time/local_date_days"))
    zulu0, sim0 = api.get("sim/time/zulu_time_sec"), api.get(SIM_TIME)
    sky = plugin_sky(api)
    stream = XPlaneStream(api, EXTRA + (SKY_E, SKY_N))
    stream.wait_for(EXTRA)
    print(f"stretch: {profile}, carried by the wind at the {'clouds' if at_clouds else 'glider'}", flush=True)
    api.command(FRONT_VIEW)
    times = [30.0, 120.0, 200.0, seconds]
    box = {"next": 0}

    def on_step(v, pilot):
        if box["next"] < len(times) and pilot.flown >= times[box["next"]]:
            box["next"] += 1
            api.command(SCREENSHOT)
            values = stream.snapshot()[0]
            print(f"  {pilot.flown:5.0f} s: screenshot, {v[AGL]:.0f} m AGL; at the glider "
                  f"{values[WIND_X]:+.2f}, {-values[WIND_Z]:+.2f} m/s, the sky's {values[SKY_E]:+.2f}, "
                  f"{values[SKY_N]:+.2f}", flush=True)
            t = zulu0 + v[SIM_TIME] - sim0
            air = values[DLAT], values[DLON]
            at_air = v[LAT] - air[0], wrap_lon_deg(v[LON] - air[1])
            field = ThermalField(FieldConfig(seed=seed, day=day, sky=sky), LocalFrame(*at_air))
            field.update(t, *at_air)
            params = cl.CloudParams()
            # For drawing on the screenshot where each cloud's emitter is: one line per screenshot.
            print("SHOT " + json.dumps({
                "flown": pilot.flown, "lat": v[LAT], "lon": v[LON], "msl": v[ELEV], "agl": v[AGL],
                "dlat": air[0], "dlon": air[1], "lift": values[LIFT], "psi": values[PSI],
                "view": {name: api.get("sim/graphics/view/" + name)
                         for name in ("view_heading", "view_pitch", "view_roll", "field_of_view_deg",
                                      "vertical_field_of_view_deg", "window_width", "window_height")},
                "level_m": api.get("xp_gliding/clouds/level_m"),
                "clouds": [{"lat": th.lat, "lon": th.lon, "scale": cl.cloud_scale(th),
                            "feeding": cl.feeding_window(th, params)[0] <= t < cl.feeding_window(th, params)[1]}
                           for th in field.alive(t) if cl.carries_cloud(th, params)]}), flush=True)

    pilot = Pilot(api)
    try:
        reason, _ = pilot.run(kmh, seconds + 5.0, settle_s=5.0, min_agl=150.0, on_step=on_step, quiet=True)
    finally:
        stream.close()
        api.command(COCKPIT_VIEW)
        api.set(AT_CLOUDS, 0)
        api.set("xp_gliding/markers_enabled", markers)
    print(f"stretch: {reason}")


def run_circle(api, wind_kt, from_deg, turns, bank, kmh, agl, radius, lean=False, record=False, fresh=False):
    _, _, elev = KHOB
    if fresh:  # a new flight with the same aircraft keeps the sky's offset; a reload clears it
        api.command("sim/operation/reload_aircraft")
        time.sleep(5.0)
    windy_start(api, elev + agl, kmh, 90.0, wind_kt, from_deg)
    api.set("xp_gliding/thermals_enabled", 1)
    api.set(LEAN_ON, 1 if lean else 0)
    wstar, zi = api.get("xp_gliding/wstar_ms"), api.get("xp_gliding/zi_m")
    seed, day = int(api.get("xp_gliding/seed")), int(api.get("sim/time/local_date_days"))
    zulu0, sim0 = api.get("sim/time/zulu_time_sec"), api.get(SIM_TIME)
    stream = XPlaneStream(api, EXTRA)
    stream.wait_for(EXTRA)
    mission = CircleMission(api, stream, kmh, bank, turns, wstar, zi, seed, day, plugin_sky(api), zulu0, sim0, radius)
    pilot = Pilot(api)
    try:
        reason, log = pilot.run(kmh, 900.0, settle_s=5.0, min_agl=250.0, bank_limit=bank + 25.0,
                                on_step=mission.on_step, until=mission.done, quiet=True, record=record)
        if log:
            print(f"  flight log: {log}, flown to {pilot.flown:.0f} s")
    except Exception as exc:
        reason = f"aborted: {exc}"
        release(api)
    stream.close()
    api.set(LEAN_ON, 0)
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
    p.add_argument("--lean", action="store_true")
    p.add_argument("--record", action="store_true", help="with the flight logger on")
    p.add_argument("--fresh", action="store_true", help="reload the aircraft first, so the sky's offset starts near 0")
    p = sub.add_parser("layers")
    p.add_argument("--wind-kt", type=float, default=15.0)
    p.add_argument("--from-deg", type=float, default=270.0)
    p.add_argument("--shear", action="store_true")
    p.add_argument("--real", action="store_true", help="X-Plane's real weather instead of the wind asked for")
    p = sub.add_parser("look")
    p.add_argument("--wind-kt", type=float, default=25.0)
    p.add_argument("--from-deg", type=float, default=270.0)
    p.add_argument("--agl", type=float, default=700.0)
    p = sub.add_parser("shear")
    p.add_argument("--profile", choices=sorted(PROFILES), default="gentle")
    p.add_argument("--at-clouds", action="store_true", help="the wind at the clouds carries the sky")
    p.add_argument("--correct", action="store_true")
    p.add_argument("--from-deg", type=float, default=270.0)
    p.add_argument("--turns", type=int, default=10)
    p.add_argument("--bank", type=float, default=35.0)
    p.add_argument("--kmh", type=float, default=95.0)
    p.add_argument("--agl", type=float, default=600.0)
    p.add_argument("--radius", type=float, default=105.0)
    p.add_argument("--record", action="store_true")
    p.add_argument("--fresh", action="store_true")
    p = sub.add_parser("stretch")
    p.add_argument("--profile", choices=sorted(PROFILES), default="gentle")
    p.add_argument("--at-clouds", action="store_true")
    p.add_argument("--from-deg", type=float, default=270.0)
    p.add_argument("--agl", type=float, default=800.0)
    p.add_argument("--seconds", type=float, default=280.0)
    args = parser.parse_args(argv)
    api = XPlaneWebAPI(timeout=30.0)
    if args.what == "shear":
        run_shear(api, args.profile, args.at_clouds, args.correct, args.from_deg, args.turns, args.bank, args.kmh,
                  args.agl, args.radius, args.record, args.fresh)
    elif args.what == "stretch":
        run_stretch(api, args.profile, args.at_clouds, args.from_deg, args.agl, args.seconds)
    elif args.what == "measure":
        run_measure(api, args.wind_kt, args.from_deg, args.seconds)
    elif args.what == "layers":
        run_layers(api, args.wind_kt, args.from_deg, args.shear, args.real)
    elif args.what == "look":
        run_look(api, args.wind_kt, args.from_deg, args.agl)
    else:
        run_circle(api, args.wind_kt, args.from_deg, args.turns, args.bank, args.kmh, args.agl, args.radius,
                   args.lean, args.record, args.fresh)


if __name__ == "__main__":
    main()
