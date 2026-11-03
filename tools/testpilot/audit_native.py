"""Native soaring audit (baseline tests H-J) flown by the test pilot.

Usage (X-Plane running; each pass replaces the current flight):
    python tools/testpilot/audit_native.py ridge|wave [--only NAME ...]
    python tools/testpilot/audit_native.py thermals [--fpm 500] [--minutes 20] [--real]
    python tools/testpilot/audit_native.py list

Each pass is an air start upwind of a straight line, a settle, and a recorded
stretch along the line with wings level at a fixed IAS. One flight log per
pass; `Output/xp-gliding/audit/manifest.jsonl` maps every log to its pass, so
`analyze_native.py` can turn the logs into lift profiles.

Sites are chosen from SRTM elevation data (opentopodata.org, srtm30m/90m,
fetched 2026-11-03); X-Plane's own terrain is logged as elevation minus AGL.

Measurement tool, not part of the plugin. License: GPL-3.0-or-later.
"""

import argparse
import json
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))

from airstart import air_start, weather  # noqa: E402
from control import Circle, HeadingHold, LineHold  # noqa: E402
from pilot import Pilot, release  # noqa: E402
from polar import polar_sink  # noqa: E402
from xp_gliding.engine.geo import LocalFrame  # noqa: E402
from xpweb import XPlaneWebAPI  # noqa: E402

MANIFEST = r"D:\Laminar\XP12-Last-Release\X-Plane 12\Output\xp-gliding\audit\manifest.jsonl"
FT = 0.3048

# Test H site: a narrow, straight ridge in central Pennsylvania from about
# 40.645 N 78.09 W to 40.745 N 77.80 W. Crest fitted on SRTM90 between 78.07
# and 77.87 W: lat = 0.388931 * lon + 71.009445, bearing 62.9 deg true, crest
# 550-700 m MSL (675 m on the SRTM30 cross-section at 78.02 W), valleys about
# 320 m on both sides. Wind from 333 deg is square onto the north-west face.
RIDGE_ORIGIN = (0.388931 * -78.02 + 71.009445, -78.02)  # crest at 78.02 W
RIDGE_BEARING = 62.93
RIDGE_CREST_M = 675.0
RIDGE_ELEV_M = 320.0  # valley floor, for the weather definition
WIND_FROM = (RIDGE_BEARING - 90.0) % 360.0  # 333: onto the north-west face


def ridge_wind(kt):
    """Same wind at every level from the valley up; no turbulence."""
    return [(alt_ft, kt, WIND_FROM, 0.0) for alt_ft in (1500, 3000, 5000, 8000, 12000)]


def ridge_point(along_m, out_m):
    """East-north of a point `along_m` along the crest (towards 063) and
    `out_m` off it towards the north-west (windward) side."""
    b = math.radians(RIDGE_BEARING)
    ue, un = math.sin(b), math.cos(b)
    return along_m * ue - out_m * un, along_m * un + out_m * ue


def ridge_passes():
    """(name, description, wind kt, start_en, end_en, altitude m MSL)."""
    passes = []
    # Crossings: downwind across the crest at 78.02 W, from 4 km windward to
    # 3 km lee, at four heights above the crest.
    for dz in (50, 175, 375, 725):
        passes.append((f"cross_{dz}", f"crossing downwind, crest +{dz} m, 25 kt", 25.0,
                       ridge_point(0, 4000), ridge_point(0, -3000), RIDGE_CREST_M + dz))
    passes.append(("cross_175_12kt", "crossing downwind, crest +175 m, 12 kt", 12.0,
                   ridge_point(0, 4000), ridge_point(0, -3000), RIDGE_CREST_M + 175))
    # Beats along the windward face, 600 m out from the crest line, from
    # 3.5 km south-west of 78.02 W to 3.5 km north-east (the clean part).
    for dz in (0, 150, 400):
        passes.append((f"beat_{dz}", f"windward beat 600 m out, crest +{dz} m, 25 kt", 25.0,
                       ridge_point(-3500, 600), ridge_point(3500, 600), RIDGE_CREST_M + dz))
    passes.append(("lee_0", "lee beat 600 m out, crest level, 25 kt", 25.0,
                   ridge_point(-3500, -600), ridge_point(3500, -600), RIDGE_CREST_M))
    passes.append(("beat_0_12kt", "windward beat 600 m out, crest level, 12 kt", 12.0,
                   ridge_point(-3500, 600), ridge_point(3500, 600), RIDGE_CREST_M))
    return passes


# Test J site: the Sierra Nevada east of its crest near Bishop, CA, over the
# Owens Valley. Crossing A starts at the crest at 37.35 N 118.66 W (3780 m on
# SRTM90), where the escarpment drops to 1900 m within 5 km and the valley
# floor (1250 m) runs 15-27 km east of the crest; crossing B starts at the
# crest at 37.40 N 118.72 W (3650 m), which drops to 1970 m within 5 km. The
# range trends about 160 deg, so a wind from 250 is square onto it.
WAVE_CRESTS = {"A": (37.35, -118.66, 3780.0), "B": (37.40, -118.72, 3650.0)}
WAVE_WIND_FROM = 250.0
WAVE_ELEV_M = 1250.0  # valley floor, for the weather definition


def wave_wind():
    """Westerly wind increasing with height, as in a classic Sierra wave day."""
    return [(alt_ft, kt, WAVE_WIND_FROM, 0.0)
            for alt_ft, kt in ((5000, 10), (8000, 18), (11000, 26), (13000, 32),
                               (16000, 38), (20000, 44), (25000, 50))]


def downwind_point(frame, crest, downwind_m, left_m=0.0):
    """East-north of a point `downwind_m` downwind of a crest point and
    `left_m` to the left of the wind direction (towards 340)."""
    lat, lon, _ = crest
    ec, nc = frame.to_enu(lat, lon)
    b = math.radians(WAVE_WIND_FROM + 180.0)  # direction the wind blows to
    ue, un = math.sin(b), math.cos(b)
    return ec + downwind_m * ue - left_m * un, nc + downwind_m * un + left_m * ue


def wave_passes(frame):
    """(name, description, start_en, end_en, altitude m MSL)."""
    passes = []
    for key in ("A", "B"):
        crest = WAVE_CRESTS[key]
        for dz in (600, 2000):
            passes.append((f"wave_cross{key}_{dz}",
                           f"crossing {key} downwind, from 4 km upwind to 28 km downwind of the "
                           f"crest, crest +{dz} m", downwind_point(frame, crest, -4000),
                           downwind_point(frame, crest, 28000), crest[2] + dz))
    crest = WAVE_CRESTS["A"]
    for dist in (1500, 5000, 9000):
        for dz in (600, 2000):
            passes.append((f"wave_par{dist // 100:03d}_{dz}",
                           f"parallel pass {dist / 1000:.1f} km downwind of crest A, crest +{dz} m",
                           downwind_point(frame, crest, dist, 4000),
                           downwind_point(frame, crest, dist, -4000), crest[2] + dz))
    return passes


def fly_pass(api, frame, name, desc, wx, start_en, end_en, alt_m, kmh=90.0, lead_m=900.0,
             settle_s=25.0, min_agl=25.0, extra=None):
    """Air start `lead_m` before start_en on the line, settle, then fly the
    line with the logger on until past end_en. Returns the manifest entry."""
    line = LineHold(start_en, end_en)
    lead_e = start_en[0] - line.ue * lead_m
    lead_n = start_en[1] - line.un * lead_m
    lat, lon = frame.to_latlon(lead_e, lead_n)
    # The glider dives for a few seconds after an air start: start a bit high.
    air_start(api, alt_m + 30.0, kmh, line.course, lat, lon, wx)
    entry = {"name": name, "desc": desc, "start_en": start_en, "end_en": end_en,
             "origin": [frame.lat0, frame.lon0], "alt_m": alt_m, "kmh": kmh,
             "course": line.course, "time": time.strftime("%Y-%m-%d %H:%M:%S")}
    if extra:
        entry.update(extra)
    pilot = Pilot(api, frame)

    def past_end(v, p):
        return line.along_cross(p.east, p.north)[0] > line.length

    try:
        reason, log = pilot.run(kmh, 900.0, line, settle_s=settle_s, record=True,
                                min_agl=min_agl, until=past_end, quiet=True)
        entry.update(result=reason, log=log)
    except Exception as exc:  # the pass ends early; keep whatever was logged
        entry.update(result=f"aborted: {exc}", log=getattr(pilot, "log_name", None))
        try:
            release(api)
        except Exception:
            pass
    os.makedirs(os.path.dirname(MANIFEST), exist_ok=True)
    with open(MANIFEST, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    print(f"{name}: {entry['result']} -> {entry.get('log')}", flush=True)
    return entry


def run_ridge(api, only):
    frame = LocalFrame(*RIDGE_ORIGIN)
    for name, desc, kt, start_en, end_en, alt in ridge_passes():
        if only and name not in only:
            continue
        wx = weather(RIDGE_ORIGIN[0], RIDGE_ORIGIN[1], RIDGE_ELEV_M, wind=ridge_wind(kt))
        fly_pass(api, frame, name, desc, wx, start_en, end_en, alt,
                 extra={"test": "H", "wind_kt": kt, "wind_from": WIND_FROM,
                        "crest_m": RIDGE_CREST_M})


# Test I site: KHOB (flat, the test A site), light wind, a cumulus layer.
KHOB = (32.6875, -103.2170, 1116.0)
LOGGER_MARK = "xp_gliding/flightlog/mark"
AGL_REF = "sim/flightmodel/position/y_agl"


class ThermalHunter:
    """Cruise on a course; on native lift circle while it lasts, then go on.

    The sensor is netto lift from the glider's own total-energy vario
    (`total_energy_fpm` plus the test A polar sink at the current IAS, TAS and
    bank), smoothed over ~2 s: `sim/weather/aircraft/thermal_rate_ms` cannot
    be used, it only repeats the regional thermal setting (seen 2026-11-03).
    Centering is the usual rule of thumb: while the lift is getting stronger,
    ease the bank for a moment, which moves the circle towards it. A circle
    lasts at least `min_turns` turns and goes on while the last turn averaged
    more than `stay_ms`, up to `max_turns`. Every circle is framed by two
    marks in the flight log (odd marks are circles)."""

    def __init__(self, api, course=90.0, enter_ms=0.8, stay_ms=0.4, bank=35.0, turn_s=27.0,
                 min_turns=2, max_turns=8, min_cruise_s=30.0):
        self.api, self.enter_ms, self.stay_ms, self.bank = api, enter_ms, stay_ms, bank
        self.turn_s, self.min_turns, self.max_turns = turn_s, min_turns, max_turns
        self.min_cruise_s = min_cruise_s
        self.cruise = HeadingHold(course)
        self.circle = Circle(-bank)
        self.state, self.since = "cruise", 0.0
        self.netto, self.last_netto, self.eased_until = 0.0, 0.0, 0.0
        self.turn_sum, self.turn_n, self.turns_done = 0.0, 0, 0
        self.circles = []

    def on_step(self, v, pilot):
        ias = v["sim/flightmodel/position/indicated_airspeed"] * 1.852
        tas = v["sim/flightmodel/position/true_airspeed"]
        te = v["sim/cockpit2/gauges/indicators/total_energy_fpm"] * 0.00508
        raw = te + polar_sink(ias, tas, abs(v["sim/flightmodel/position/phi"]))
        self.netto += 0.05 * (raw - self.netto)  # ~2 s at 10 Hz
        t = pilot.flown
        if self.state == "cruise":
            pilot.guidance = self.cruise
            if self.netto > self.enter_ms and t - self.since > self.min_cruise_s:
                self.state, self.since = "circle", t
                self.turn_sum, self.turn_n, self.turns_done = 0.0, 0, 0
                self.api.command(LOGGER_MARK)
                self.circles.append({"t0": t, "netto0": self.netto, "agl0": v[AGL_REF]})
                print(f"  {t:6.0f}s netto {self.netto:+.2f} m/s, AGL {v[AGL_REF]:.0f}: circling",
                      flush=True)
        else:
            if self.netto > self.last_netto + 0.01:
                self.eased_until = t + 2.0
            self.circle.bank_deg = -(self.bank - 15.0 if t < self.eased_until else self.bank)
            pilot.guidance = self.circle
            self.turn_sum += self.netto
            self.turn_n += 1
            if t - self.since > (self.turns_done + 1) * self.turn_s:
                self.turns_done += 1
                turn_avg = self.turn_sum / max(1, self.turn_n)
                self.turn_sum, self.turn_n = 0.0, 0
                print(f"  {t:6.0f}s turn {self.turns_done}: netto {turn_avg:+.2f} m/s, "
                      f"AGL {v[AGL_REF]:.0f}", flush=True)
                if self.turns_done >= self.max_turns or (
                        self.turns_done >= self.min_turns and turn_avg < self.stay_ms):
                    self.state, self.since = "cruise", t
                    self.api.command(LOGGER_MARK)
                    self.circles[-1].update(t1=t, turns=self.turns_done, agl1=v[AGL_REF])
                    print(f"  {t:6.0f}s back to cruise", flush=True)
        self.last_netto = self.netto


def run_thermals(api, fpm, minutes, real, msl=2600.0, course=90.0, hunt=True, preset=None,
                 alex=False):
    """Test I (native thermals); with alex=True, test E instead: calm, clear
    air and Alex Ferrer's plugin enabled with its random thermal map (needs
    flight logger 0.2.0 for the `xp_gliding/flightlog/alex_enabled` dataref)."""
    lat, lon, elev = KHOB
    if alex:
        wx, thermal_ms, desc = None, 0.0, "calm and clear, Alex's plugin enabled"
    elif real:
        wx, thermal_ms, desc = "use_real_weather", None, "real weather"
    elif preset:
        wx = dict(weather(lat, lon, elev, thermal_fpm=fpm), definition=preset)
        thermal_ms, desc = fpm * 0.00508, f"preset {preset}, {fpm} fpm"
    else:
        wx = weather(lat, lon, elev, wind=[(4500, 5.0, 270.0, 0.0), (8000, 5.0, 270.0, 0.0)],
                     clouds=[("cumulus", 0.4, 9500, 13000)], thermal_fpm=fpm)
        thermal_ms, desc = fpm * 0.00508, f"manual: cumulus 0.4 at 9500-13000 ft, {fpm} fpm"
    air_start(api, msl, 90.0, course, lat, lon, wx, thermal_ms=thermal_ms)
    if alex:
        api.set("xp_gliding/flightlog/alex_enabled", 1)
    region = api.get("sim/weather/region/thermal_rate_ms")
    print(f"weather: {desc}; regional thermal rate {region:.2f} m/s", flush=True)
    hunter = ThermalHunter(api, course)
    pilot = Pilot(api, LocalFrame(lat, lon))
    name = "thermals_real" if real else f"thermals_{preset + '_' if preset else ''}{fpm:.0f}"
    if alex:
        name = "thermals_alex"
    name += f"_{msl:.0f}"
    if not hunt:
        hunter.enter_ms = float("inf")
        name += "_straight"
    entry = {"name": name, "test": "E" if alex else "I",
             "desc": desc, "region_thermal_ms": region, "origin": [lat, lon], "alt_m": msl,
             "course": course, "time": time.strftime("%Y-%m-%d %H:%M:%S"),
             "start_en": [0.0, 0.0], "end_en": [math.sin(math.radians(course)) * 1000,
                                                math.cos(math.radians(course)) * 1000]}
    try:
        reason, log = pilot.run(90.0, minutes * 60.0, hunter.cruise, settle_s=20.0, record=True,
                                min_agl=400.0, bank_limit=45.0, on_step=hunter.on_step)
        entry.update(result=reason, log=log)
    except Exception as exc:
        entry.update(result=f"aborted: {exc}", log=pilot.log_name)
        try:
            release(api)
        except Exception:
            pass
    finally:
        if alex:
            api.set("xp_gliding/flightlog/alex_enabled", 0)
    entry["circles"] = hunter.circles
    with open(MANIFEST, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    print(f"{entry['name']}: {entry['result']} -> {entry.get('log')}; "
          f"{len(hunter.circles)} circles", flush=True)


def run_wave(api, only):
    lat, lon, _ = WAVE_CRESTS["A"]
    frame = LocalFrame(lat, lon)
    for name, desc, start_en, end_en, alt in wave_passes(frame):
        if only and name not in only:
            continue
        wx = weather(lat, lon, WAVE_ELEV_M, wind=wave_wind())
        fly_pass(api, frame, name, desc, wx, start_en, end_en, alt, min_agl=150.0,
                 extra={"test": "J", "wind_from": WAVE_WIND_FROM})


def main(argv=None):
    parser = argparse.ArgumentParser(description="Native soaring audit flown by the test pilot")
    parser.add_argument("test", choices=("ridge", "wave", "thermals", "list"))
    parser.add_argument("--only", nargs="*", help="pass names to fly")
    parser.add_argument("--fpm", type=float, default=500.0, help="native thermal setting")
    parser.add_argument("--minutes", type=float, default=20.0, help="thermal hunt duration")
    parser.add_argument("--real", action="store_true", help="thermal hunt in real weather")
    parser.add_argument("--straight", action="store_true", help="cruise only, never circle")
    parser.add_argument("--preset", help="weather preset instead of the custom cumulus layer")
    parser.add_argument("--alex", action="store_true", help="test E: Alex's thermals, calm air")
    parser.add_argument("--msl", type=float, default=2600.0, help="start altitude (m MSL)")
    args = parser.parse_args(argv)
    if args.test == "list":
        for p in ridge_passes():
            print(p[0], "-", p[1])
        for p in wave_passes(LocalFrame(*WAVE_CRESTS["A"][:2])):
            print(p[0], "-", p[1])
        return
    api = XPlaneWebAPI(timeout=30.0)
    if args.test == "ridge":
        run_ridge(api, set(args.only or ()))
    elif args.test == "wave":
        run_wave(api, set(args.only or ()))
    elif args.test == "thermals":
        run_thermals(api, args.fpm, args.minutes, args.real, args.msl, hunt=not args.straight,
                     preset=args.preset, alex=args.alex)


if __name__ == "__main__":
    main()
