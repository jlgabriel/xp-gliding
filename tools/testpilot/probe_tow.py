"""Look at X-Plane's native aerotow: its line, the line's datarefs and its force.

Stage 0 of the aerotow design. Starts the ASK 21 on runway 01 at Tobalaba
(SCTB) behind a tug (`runway_start` with `tow_type` "tug"), calm and clear at
noon, then:

1. On the ground, chase view: a screenshot with the native line drawn and one
   with `sim/graphics/misc/kill_tow_lines` = 1, to see whether it hides it.
2. Releases the parking brake and records, at ~10 Hz, the line's ends
   (`line_aircraft_xyz`, `line_payload_xyz`), its force (`line_force_xyz`),
   the glider's and the tug's (AI plane 1) positions and attitudes, until
   `--seconds` have passed or the glider is `--release-agl` m above the
   ground; then releases the tow and gives the stick back.

The glider is held by a simple law, enough to stay behind the tug: wings
level toward the tug and, once flying, a pitch that keeps the glider a few
metres above the tug's height (high tow). It is not a model of a pilot; how
hard it has to work is a hint, not a measurement of the feel.

Writes a CSV to --out. Measurement tool, not part of the plugin.
License: GPL-3.0-or-later.
"""

import argparse
import atexit
import csv
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from airstart import ASK21, PAYLOAD_KG, calm_clear_weather  # noqa: E402
from pilot import (AGL, IAS, KT_TO_KMH, OVERRIDES, P, PAUSED, PHI, Q, SIM_TIME, THETA, YOKE,  # noqa: E402
                   give_logger_back, release, take_over_logger)
from xpweb import XPlaneStream, XPlaneWebAPI  # noqa: E402

SCTB = (-33.4562, -70.5467, 648.0)  # lat, lon, field elevation (m), runway 01/19
TUG = "Aircraft/Laminar Research/Piper PA-18 Super Cub/PA-18-150.acf"
KILL = "sim/graphics/misc/kill_tow_lines"
LINE_A = "sim/flightmodel/misc/line_aircraft_xyz"
LINE_P = "sim/flightmodel/misc/line_payload_xyz"
LINE_F = "sim/flightmodel/misc/line_force_xyz"
TOWING = "sim/flightmodel2/misc/tow_in_progress"
PSI = "sim/flightmodel/position/psi"
BETA = "sim/flightmodel/position/beta"
GX, GY, GZ = ("sim/flightmodel/position/local_" + c for c in "xyz")
TX, TY, TZ = ("sim/multiplayer/position/plane1_" + c for c in "xyz")
TPSI = "sim/multiplayer/position/plane1_psi"
TTHE = "sim/multiplayer/position/plane1_the"
TPHI = "sim/multiplayer/position/plane1_phi"
OURS = ("xp_gliding/tow/state", "xp_gliding/tow/sag_m", "xp_gliding/tow/span_m", "xp_gliding/tow/frame_us")
WATCHED = (PAUSED, SIM_TIME, IAS, THETA, PHI, PSI, Q, P, BETA, AGL, GX, GY, GZ,
           LINE_A, LINE_P, LINE_F, TOWING, TX, TY, TZ, TPSI, TTHE, TPHI)
SCREENSHOTS = r"D:\Laminar\XP12-Last-Release\X-Plane 12\Output\screenshots"


def clamp(x, lim):
    return max(-lim, min(lim, x))


def wrap180(deg):
    return (deg + 180.0) % 360.0 - 180.0


def newest_screenshot():
    try:
        names = [os.path.join(SCREENSHOTS, n) for n in os.listdir(SCREENSHOTS)]
    except OSError:
        return None
    return max(names, key=os.path.getmtime) if names else None


def screenshot(api, label):
    before = newest_screenshot()
    api.command("sim/operation/screenshot")
    for _ in range(50):
        time.sleep(0.1)
        now = newest_screenshot()
        if now != before:
            print(f"screenshot ({label}): {now}", flush=True)
            return now
    print(f"screenshot ({label}): none appeared", flush=True)
    return None


def start(api):
    lat, lon, elev = SCTB
    api.start_flight({
        "aircraft": {"path": ASK21},
        "weight": {"payload_weight_in_kilograms": list(PAYLOAD_KG),
                   "fueltank_weight_in_kilograms": [0] * 9},
        "runway_start": {"airport_id": "SCTB", "runway": "01", "tow_type": "tug",
                         "tow_aircraft": {"path": TUG}},
        "local_time": {"day_of_year": 305, "time_in_24_hours": 12.0},
        "weather": calm_clear_weather(lat, lon, elev),
    })
    for _ in range(90):
        time.sleep(1.0)
        try:
            api.get(TOWING)
            return
        except (RuntimeError, KeyError, OSError):
            continue
    raise TimeoutError("flight did not load within 90 s")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seconds", type=float, default=120.0, help="longest tow recorded")
    parser.add_argument("--release-agl", type=float, default=300.0, help="release height (m)")
    parser.add_argument("--high-tow-m", type=float, default=3.0, help="glider above the tug (m)")
    parser.add_argument("--out", required=True, help="CSV file to write")
    parser.add_argument("--shots-agl", type=float, default=60.0, help="in-flight screenshots here (m)")
    parser.add_argument("--after-s", type=float, default=10.0, help="recorded after the release (s)")
    parser.add_argument("--no-start", action="store_true", help="use the flight already loaded")
    args = parser.parse_args(argv)

    api = XPlaneWebAPI(timeout=30.0)
    if not args.no_start:
        start(api)
        time.sleep(8.0)  # scenery and plugins
        if api.get(PAUSED):
            # 12.4.4: an API start can leave the main menu up, which pauses the sim. Toggle it
            # only then: toggling with no menu up opens it.
            api.command("sim/operation/toggle_main_menu")
            time.sleep(2.0)

    try:
        take_over_logger(api)  # the logger's datarefs exist once a flight is loaded
    except RuntimeError as exc:
        print(f"flight logger not taken over: {exc}", flush=True)
    watched = WATCHED
    try:
        api.dataref_id(OURS[0])
        watched = WATCHED + OURS
    except (KeyError, RuntimeError):
        print("XP-Gliding's tow rope datarefs are not there", flush=True)
    stream = XPlaneStream(api, watched)
    stream.wait_for(watched, timeout=10.0)
    v, _ = stream.snapshot()
    print(f"loaded: towing {v[TOWING]}, kill_tow_lines {api.get(KILL)}, paused {v[PAUSED]}", flush=True)
    print(f"  glider local {v[GX]:.1f} {v[GY]:.1f} {v[GZ]:.1f}  line_aircraft {v[LINE_A]}", flush=True)
    print(f"  tug    local {v[TX]:.1f} {v[TY]:.1f} {v[TZ]:.1f}  line_payload  {v[LINE_P]}", flush=True)
    print(f"  line force {v[LINE_F]}", flush=True)

    api.command("sim/view/chase")
    time.sleep(2.0)
    shots = [screenshot(api, "native line")]
    api.set(KILL, 1)
    time.sleep(1.5)
    shots.append(screenshot(api, "kill_tow_lines = 1"))
    api.set(KILL, 0)

    atexit.register(release, api)
    stream.set_many({name: 1 for name in OVERRIDES})
    api.command("sim/flight_controls/park_brake_release")
    print("brake released, recording", flush=True)

    t0 = None
    last_t = None
    next_print = 0.0
    released = False
    released_at = None
    air_shots = False
    after_shot = False
    rows = []
    try:
        while True:
            time.sleep(0.02)
            v, stamp = stream.snapshot()
            if time.monotonic() - stamp > 2.0:
                raise RuntimeError("no data from X-Plane for 2 s")
            if v[PAUSED] or v[SIM_TIME] == last_t:
                continue
            last_t = v[SIM_TIME]
            t0 = v[SIM_TIME] if t0 is None else t0
            t = v[SIM_TIME] - t0
            ax, ay, az = v[LINE_A]
            px, py, pz = v[LINE_P]
            fx, fy, fz = v[LINE_F]
            dx, dy, dz = px - ax, py - ay, pz - az
            length = math.sqrt(dx * dx + dy * dy + dz * dz)
            force = math.sqrt(fx * fx + fy * fy + fz * fz)
            # Line direction toward the tug; X-Plane's local x is east, z south.
            to_tug = math.degrees(math.atan2(dx, -dz)) % 360.0
            err = wrap180(to_tug - v[PSI]) if length > 1.0 else 0.0
            ias = v[IAS] * KT_TO_KMH
            flying = v[AGL] > 1.5
            phi_cmd = clamp(1.0 * err, 15.0) if flying else 0.0
            roll = clamp(0.03 * (phi_cmd - v[PHI]) - 0.01 * v[P], 0.7)
            rudder = clamp(0.03 * err + 0.02 * v[BETA], 0.6)
            if ias < 60.0:
                theta_cmd = 0.0
                pitch = 0.0
            else:
                # dy > 0: the tug is above the line's glider end. High tow wants it high_tow_m below.
                theta_cmd = clamp(3.0 + 0.4 * (dy + args.high_tow_m), 12.0)
                pitch = clamp(0.06 * (theta_cmd - v[THETA]) - 0.02 * v[Q], 0.6)
            stream.set_many({YOKE[0]: pitch, YOKE[1]: roll, YOKE[2]: rudder})
            rows.append([round(t, 3), v[TOWING], round(ias, 2), round(v[AGL], 2), round(v[THETA], 2),
                         round(v[PHI], 2), round(v[PSI], 2), round(v[BETA], 2),
                         round(v[GX], 2), round(v[GY], 2), round(v[GZ], 2),
                         round(v[TX], 2), round(v[TY], 2), round(v[TZ], 2), round(v[TPSI], 2),
                         round(v[TTHE], 2), round(v[TPHI], 2),
                         round(ax, 2), round(ay, 2), round(az, 2), round(px, 2), round(py, 2), round(pz, 2),
                         round(fx, 1), round(fy, 1), round(fz, 1), round(length, 2), round(force, 1),
                         round(pitch, 3), round(roll, 3), round(rudder, 3)])
            if t >= next_print:
                next_print += 2.0
                print(f"{t:5.1f}s IAS {ias:5.1f} AGL {v[AGL]:6.1f} th {v[THETA]:+5.1f} phi {v[PHI]:+5.1f} "
                      f"err {err:+5.1f} | line {length:5.1f} m dy {dy:+5.1f} | F {force:7.0f} N "
                      f"({fx:+.0f} {fy:+.0f} {fz:+.0f}) | yoke {pitch:+.2f} {roll:+.2f} {rudder:+.2f}"
                      + (f" | ours {v[OURS[0]]} sag {v[OURS[1]]:.2f} span {v[OURS[2]]:.1f} "
                         f"{v[OURS[3]]:.0f} us" if OURS[0] in v else ""), flush=True)
            if abs(v[PHI]) > 45.0:
                print(f"bank {v[PHI]:+.0f}: stopping", flush=True)
                break
            if not air_shots and v[AGL] >= args.shots_agl:
                air_shots = True
                shots.append(screenshot(api, f"native line at {v[AGL]:.0f} m"))
                api.set(KILL, 1)
                time.sleep(0.5)
                shots.append(screenshot(api, "kill_tow_lines = 1 in flight"))
                api.set(KILL, 0)
            if released_at is None and (v[AGL] >= args.release_agl or t >= args.seconds):
                api.command("sim/flight_controls/glider_tow_release")
                released = True
                released_at = t
                print(f"{t:5.1f}s tow released", flush=True)
            if released_at is not None and not after_shot and t - released_at >= 4.0:
                after_shot = True
                shots.append(screenshot(api, "4 s after release"))
            if released_at is not None and t - released_at >= args.after_s:
                break
            if released_at is None and t > 20.0 and not v[TOWING]:
                print("the tow ended by itself", flush=True)
                break
    finally:
        if v.get(TOWING) and not released:
            api.command("sim/flight_controls/glider_tow_release")
            released = True
        release(api)
        give_logger_back(api)
        stream.close()
        with open(args.out, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["t", "towing", "ias_kmh", "agl", "theta", "phi", "psi", "beta",
                        "gx", "gy", "gz", "tx", "ty", "tz", "tpsi", "tthe", "tphi",
                        "ax", "ay", "az", "px", "py", "pz", "fx", "fy", "fz", "line_m", "force_n",
                        "yoke_pitch", "yoke_roll", "yoke_rudder"])
            w.writerows(rows)
        print(f"{len(rows)} rows -> {args.out}; tow released by us: {released}; shots: {shots}", flush=True)


if __name__ == "__main__":
    main()
