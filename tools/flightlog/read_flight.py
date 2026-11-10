"""What a hand flight says about its climbs and the clouds over them.

Usage:
    python tools/flightlog/read_flight.py LOG.csv [--wstar 3] [--zi 2000]

Finds where the glider circled, rebuilds the sky (`replay_sky.py`) and says which thermal each
circling belonged to. Then it answers, with numbers, what a pilot is asked after a flight:

- Clouds over hills: the level, how many clouds were raised for the ground, the highest base.
  That a cloud looks right near a hill is for the pilot's eye.
- Size: a bigger cloud against a faster climb, both as flown and as the thermal offered it.
- Top: the highest point of each climb against the cloud's base, whether it was still climbing
  there, and how high that thermal could hold this glider when perfectly centred.
- The cloud overhead: how far the circles were from the emitter, along the climb.

Limits. The field is the oracle: the plugin's instruments never read it. Particles are not
logged, so the place of a cloud is its emitter's, and particles may have drifted from it.
A thermal's `core` and its ceiling leave out neighbours that overlap it. The log's nearest cloud
is read every few seconds; a log older than logger 0.7.0 has no clouds in it, so the base is
then worked out from the first ground of the log and any raising for the ground is missed.

The floors. Since logger 0.8.0 the lift ends with its cloud: each thermal is read from a floor of
its own, which the plugin worked out from the ground (`engine.field.height_in_thermal`). A log that
has them gives a thermal the floor logged while it was the nearest, or else one from its cloud's
logged base, or else from the level. Older logs were flown with the height above the ground, and are read so.

Measurement tool, not part of the plugin. License: GPL-3.0-or-later.
"""

import argparse
import math
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, HERE)

from replay_sky import FPM_TO_MS, load  # noqa: E402
from replay_vario import KT_TO_KMH  # noqa: E402
from xp_gliding.engine import updraft  # noqa: E402
from xp_gliding.engine.clouds import CLOUD_HALF_WIDTH_M, CloudParams, carries_cloud, cloud_scale  # noqa: E402
from xp_gliding.engine.field import (SKIES, SKY_NAMES, FieldConfig, ThermalField, height_in_thermal,  # noqa: E402
                                      sky_time)
from xp_gliding.engine.geo import LocalFrame  # noqa: E402
from xp_gliding.engine.markers import core_of  # noqa: E402

TURN_RATE_DPS = 5.0  # circling: faster than a turn in 72 s
SMOOTH_S = 11  # of the heading's rate, odd
MERGE_S = 25.0  # straight for less than this does not end a circling
MIN_TURN_DEG = 360.0
JUMP_MS = 150.0  # moved with the map, or a new flight: faster than a glider goes
MIN_AGL_M = 20.0
SEARCH_M = 1200.0  # how far from the circles a thermal can be the one being climbed
MIN_OWN_LIFT_MS = 0.3  # less than this from a thermal: the climb is not due to it
TOP_S = 30.0  # the end of a climb, to say whether it was still going up
STILL_CLIMBING_MS = 0.3
SAME_CLOUD_M = 300.0  # the log's nearest cloud is this thermal's within this distance
SAME_NEAREST_M = 50.0  # the log's nearest thermal is this one within this: 1 s of flight, plus a little
CEILING_STEP_M = 10.0


def turned_rate(t, psi):
    """Rate of heading (deg/s) per row, at one sample per second, smoothed."""
    step = (np.diff(psi, prepend=psi[0]) + 180.0) % 360.0 - 180.0
    dt = np.maximum(np.diff(t, prepend=t[0]), 1e-3)
    kernel = np.ones(SMOOTH_S) / SMOOTH_S
    return np.convolve(step / dt, kernel, mode="same"), step


def find_circlings(t, psi, east, north, agl):
    """Stretches of circling, as (first, last) row indices: t at one sample per second or so."""
    if len(t) < SMOOTH_S:
        return []
    rate, step = turned_rate(t, psi)
    moved = np.hypot(np.diff(east, prepend=east[0]), np.diff(north, prepend=north[0]))
    dt = np.maximum(np.diff(t, prepend=t[0]), 1e-3)
    jump = moved / dt > JUMP_MS
    active = (np.abs(rate) > TURN_RATE_DPS) & (agl > MIN_AGL_M)
    stretches = []
    first = None
    for i in range(len(t)):
        if jump[i] and first is not None:
            stretches.append((first, i - 1))
            first = None
        if active[i]:
            if first is None:
                first = i
            elif t[i] - t[i - 1] > MERGE_S:
                stretches.append((first, i - 1))
                first = i
        elif first is not None:
            # Look ahead: straight for a moment does not end it.
            ahead = i + np.argmax(active[i:]) if active[i:].any() else None
            ends = (ahead is None or t[ahead] - t[i] > MERGE_S or jump[i:ahead + 1].any())
            if ends:
                stretches.append((first, i - 1))
                first = None
    if first is not None:
        stretches.append((first, len(t) - 1))
    return [(a, b) for a, b in stretches if abs(step[a:b + 1].sum()) >= MIN_TURN_DEG]


def spearman(x, y):
    """Rank correlation, or None with fewer than three points or no spread."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    if len(x) < 3 or np.ptp(x) == 0.0 or np.ptp(y) == 0.0:
        return None
    rank = lambda v: np.argsort(np.argsort(v)).astype(float)  # noqa: E731
    return float(np.corrcoef(rank(x), rank(y))[0, 1])


def own_lift(th, field, e, n, z, t, wstar, zi, ground_m=None):
    """This one thermal's part of the lift at a point, as `ThermalField.lift_at` adds it."""
    if z <= 0.0:
        return 0.0
    z = height_in_thermal(th, z, ground_m)
    if z >= zi:
        return 0.0
    s, rf = th.envelope(t)
    if s == 0.0:
        return 0.0
    we = field.environment_sink(z, wstar, zi)
    r = math.hypot(e - th.e, n - th.n)
    w = updraft.updraft_velocity(r / th.stretch, z, zi, wstar, th.wgain * th.gain, th.rgain * rf, we)
    return s * (w - we)


def ceiling_agl(th, field, sink, t, z_from, wstar, zi, ground_m=None):
    """The height (m AGL) where this thermal's core no longer holds up a glider sinking at `sink`."""
    z = max(z_from, CEILING_STEP_M)
    while True:
        zt = height_in_thermal(th, z, ground_m)
        if zt >= zi:
            return z - (zt - zi)
        core, _ = core_of(th, zt, t, wstar, zi, field.environment_sink(zt, wstar, zi))
        if core <= sink:
            return z
        z += CEILING_STEP_M


def logged_floors(field, log, rows, e, n, sky_t):
    """The floors the log says, as {thermal: m MSL}. It logs the nearest thermal's, about once a second.

    Thermals can stand 100 m apart with floors 900 m apart, so which one was the nearest is asked of
    the rebuilt sky; the distance logged only checks it.
    """
    near, floors = log["xpg_nearest_m"], log["xpg_nearest_floor_m"]
    seen = {}
    for i in rows:
        th, r = field.nearest(e[i], n[i], sky_t[i], SEARCH_M)
        if th is not None and abs(r - near[i]) < SAME_NEAREST_M and floors[i] > -1.0:
            seen.setdefault(th, []).append(floors[i])
    return {th: float(np.median(values)) for th, values in seen.items()}


def floor_of(th, seen, log, a, b, sky, zi, carries):
    """This thermal's floor (m MSL) in a log that has floors, and where that comes from.

    `logged_floors` if it was the nearest. If not, from its cloud's logged base or the level, the
    same that the plugin worked it from.
    """
    if th in seen:
        return seen[th], "logged"
    level = log["xpg_cloud_level_m"][b]
    if carries:
        base, source = cloud_base_of(log, a, b, cloud_scale(th), sky, zi)
        return base - sky.cloud_base_zzi * zi, f"from the base, {source}"
    if level > 0.0:
        return float(level) - sky.cloud_base_zzi * zi, "from the level"
    return None, ""


def phase_of_life(th, t):
    tau = (t - th.birth) / (th.death - th.birth)
    if tau < 0.2:
        return "growing"
    return "mature" if tau < 0.7 else "decaying"


class Climb:
    __slots__ = ("t0", "t1", "gain", "rate", "te", "bank", "ias", "sink", "top_msl", "top_agl", "end_te", "th",
                 "scale", "core", "r_parts", "cloud_parts", "under", "half_width", "base", "base_from", "ceiling_msl",
                 "over_ground", "phase", "z_from", "floor", "floor_from")


def read_climb(log, sky_t, e, n, frame, a, b, seed, day, sky, wstar, zi):
    """One circling, from row a to row b, against the thermal it belongs to (or none)."""
    c = Climb()
    t, elev, agl = log["t_run_s"], log["elev_m"], log["agl_m"]
    every = max((b - a) // 60, 1)
    rows = np.arange(a, b + 1, every)
    c.t0, c.t1 = t[a], t[b]
    c.gain = elev[b] - elev[a]
    c.rate = c.gain / max(t[b] - t[a], 1e-3)
    te = log["te_fpm"][a:b + 1] * FPM_TO_MS
    c.te = te.mean()
    c.bank = np.abs(log["phi_deg"][a:b + 1]).mean()
    c.ias = log["ias_kt"][a:b + 1].mean() * KT_TO_KMH
    c.sink = (log["xpg_lift_centre_ms"][a:b + 1] - te).mean()
    top = a + int(np.argmax(elev[a:b + 1]))
    c.top_msl, c.top_agl = elev[top], agl[top]
    end = t[a:b + 1] >= t[b] - TOP_S
    c.end_te = te[end].mean()
    c.over_ground = math.hypot(*(np.array(frame.to_enu(log["lat_deg"][b], log["lon_deg"][b]))
                                 - np.array(frame.to_enu(log["lat_deg"][a], log["lon_deg"][a]))))

    lat, lon = frame.to_latlon(e[rows].mean(), n[rows].mean())
    mid = 0.5 * (sky_t[a] + sky_t[b])
    field = ThermalField(FieldConfig(seed=seed, day=day, range_m=SEARCH_M + 2000.0, zi_m=zi, sky=sky), frame)
    field.update(mid, lat, lon)
    floors = log.get("xpg_nearest_floor_m")
    has_floors = floors is not None and len(floors) == len(t)
    ground = elev - agl if has_floors else [None] * len(t)
    seen = logged_floors(field, log, np.arange(a, b + 1, max((b - a) // 400, 1)), e, n, sky_t) if has_floors else {}
    params = CloudParams()
    best, best_lift = None, MIN_OWN_LIFT_MS
    c.floor_from = ""
    for th, _ in field.alive_within(e[rows].mean(), n[rows].mean(), mid, SEARCH_M):
        source = ""
        if has_floors:
            th.floor_m, source = floor_of(th, seen, log, a, b, sky, zi, carries_cloud(th, params))
        lift = np.mean([own_lift(th, field, e[i], n[i], agl[i], sky_t[i], wstar, zi, ground[i]) for i in rows])
        if lift > best_lift:
            c.floor_from = source
            best, best_lift = th, lift
    c.floor = None if best is None else best.floor_m
    c.th, c.scale, c.core, c.r_parts, c.cloud_parts, c.under = best, None, None, [], [], None
    c.base, c.base_from, c.ceiling_msl, c.phase, c.half_width = None, "", None, "", None
    if best is None:
        return c
    z_mid = height_in_thermal(best, float(np.mean(agl[rows])), float(np.mean(ground[rows])) if has_floors else None)
    c.core, _ = core_of(best, z_mid, mid, wstar, zi, field.environment_sink(z_mid, wstar, zi))
    c.phase = phase_of_life(best, mid)
    c.ceiling_msl = (elev[b] - agl[b]) + ceiling_agl(best, field, c.sink, sky_t[b], agl[b], wstar, zi, ground[b])
    r_cloud = np.hypot(e[a:b + 1] - best.e, n[a:b + 1] - best.n)
    lean_e, lean_n = log.get("xpg_lean_e_m"), log.get("xpg_lean_n_m")
    has_lean = lean_e is not None and len(lean_e) == len(t)
    r_lift = (np.hypot(e[a:b + 1] - lean_e[a:b + 1] - best.e, n[a:b + 1] - lean_n[a:b + 1] - best.n)
              if has_lean else r_cloud)
    for part in np.array_split(np.arange(b - a + 1), 4):
        c.r_parts.append(float(np.median(r_lift[part])))
        c.cloud_parts.append(math.hypot(e[a:b + 1][part].mean() - best.e, n[a:b + 1][part].mean() - best.n))
    if carries_cloud(best, params):
        c.scale = cloud_scale(best)
        c.half_width = CLOUD_HALF_WIDTH_M * c.scale
        c.under = float(np.mean(r_cloud < c.half_width))
        c.base, c.base_from = cloud_base_of(log, a, b, c.scale, sky, zi)
    return c


def cloud_base_of(log, a, b, scale, sky, zi):
    """This cloud's base (m MSL), and where that comes from."""
    near, base, size = (log.get(k) for k in ("xpg_cloud_nearest_m", "xpg_cloud_nearest_base_m",
                                             "xpg_cloud_nearest_scale"))
    if near is not None and len(near) == len(log["t_run_s"]):
        m = (near[a:b + 1] >= 0.0) & (near[a:b + 1] < SAME_CLOUD_M) & (np.abs(size[a:b + 1] - scale) < 0.01)
        if m.any():
            return float(np.median(base[a:b + 1][m])), "logged"
        level = log["xpg_cloud_level_m"][b]
        if level > 0.0:
            return float(level), "the level"
    ground = log["elev_m"][0] - log["agl_m"][0]
    return float(ground + sky.cloud_base_zzi * zi), "worked out"


def report_climbs(climbs):
    print("\n## The climbs\n")
    print("| t_run | Time | Gain | Climb | TE | Bank | km/h | Sink | Over ground | Thermal |")
    print("| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for c in climbs:
        if c.th is None:
            own = "none of ours (a slope, or sink)"
        else:
            cloud = f"cloud {c.scale:.2f}" if c.scale else "blue"
            own = f"{cloud}, core {c.core:.2f}, {c.phase}"
            if c.floor is not None:
                own += f", floor {c.floor:.0f} m ({c.floor_from})"
        print(f"| {c.t0:.0f}-{c.t1:.0f} | {c.t1 - c.t0:.0f} s | {c.gain:+.0f} m | {c.rate:+.2f} | {c.te:+.2f} "
              f"| {c.bank:.0f} | {c.ias:.0f} | {c.sink:.2f} | {c.over_ground:.0f} m | {own} |")


def report_hills(log):
    print("\n## Clouds over hills (what the log has; how they looked is for the pilot's eye)\n")
    level = log.get("xpg_cloud_level_m")
    if level is None or len(level) != len(log["t_run_s"]):
        print("This log is older than logger 0.7.0: it has no clouds.")
        return
    ground = log["elev_m"] - log["agl_m"]
    print(f"Level {level[-1]:.0f} m MSL. Ground flown over {ground.min():.0f}-{ground.max():.0f} m MSL. "
          f"Clouds created {log['xpg_cloud_created'][-1]:.0f}, raised for the ground {log['xpg_cloud_raised'][-1]:.0f}, "
          f"highest base {log['xpg_cloud_base_max_m'][-1]:.0f} m MSL.")


def report_size(climbs):
    print("\n## Does a bigger cloud climb faster?\n")
    rows = sorted((c for c in climbs if c.scale is not None), key=lambda c: c.scale)
    if not rows:
        print("No climb under a cloud.")
        return
    print("| Cloud size | Climb flown | Core offered | Circles from the centre | Phase | t_run |")
    print("| --- | --- | --- | --- | --- | --- |")
    for c in rows:
        print(f"| {c.scale:.2f} | {c.rate:+.2f} | {c.core:.2f} | {np.median(c.r_parts):.0f} m | {c.phase} | {c.t0:.0f} |")
    flown, offered = spearman([c.scale for c in rows], [c.rate for c in rows]), spearman(
        [c.scale for c in rows], [c.core for c in rows])
    if flown is None:
        print(f"\n{len(rows)} climb(s): too few to say anything about size.")
    else:
        print(f"\nRank correlation with size over {len(rows)} climbs: flown {flown:+.2f}, offered {offered:+.2f}. "
              "With so few, a single climb can turn it around.")


def report_top(climbs):
    print("\n## How high?\n")
    rows = [c for c in climbs if c.scale is not None]
    if not rows:
        print("No climb under a cloud.")
        return
    print("| t_run | Top | Base | Under the base | Last 30 s | Thermal could hold to | Reading |")
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for c in rows:
        gap = c.base - c.top_msl
        going = c.end_te > STILL_CLIMBING_MS
        if gap <= 0.0:
            reading = "reached the cloud"
        elif going:
            reading = "left still climbing"
        elif c.ceiling_msl < c.base:
            reading = "topped out: this thermal stops short of its cloud"
        else:
            reading = "stopped climbing, though the core could go on: off centre?"
        print(f"| {c.t0:.0f}-{c.t1:.0f} | {c.top_msl:.0f} m ({c.top_agl:.0f} AGL) | {c.base:.0f} m ({c.base_from}) | {gap:+.0f} m "
              f"| {c.end_te:+.2f} | {c.ceiling_msl:.0f} m | {reading} |")


def report_overhead(climbs):
    print("\n## Was the cloud overhead? (the emitter's place, not the particles')\n")
    rows = [c for c in climbs if c.scale is not None]
    if not rows:
        print("No climb under a cloud.")
        return
    print("| t_run | Half width | Under it | Circles' centre from the emitter, by quarter of the climb |")
    print("| --- | --- | --- | --- |")
    for c in rows:
        parts = ", ".join(f"{r:.0f}" for r in c.cloud_parts)
        print(f"| {c.t0:.0f}-{c.t1:.0f} | {c.half_width:.0f} m | {c.under:.0%} | {parts} m |")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("log")
    parser.add_argument("--wstar", type=float, help="older logs do not say; default 3")
    parser.add_argument("--zi", type=float, help="older logs do not say; default 2000")
    args = parser.parse_args(argv)

    log = load(args.log)
    n_rows = len(log["t_run_s"])
    if len(log["xpg_dlat_deg"]) != n_rows or n_rows == 0:
        raise SystemExit("This log does not say its seed and offset (logger before 2026-11-05): use replay_sky.py.")
    wstar = args.wstar or (log["xpg_wstar_ms"][-1] if len(log["xpg_wstar_ms"]) == n_rows else 3.0)
    zi = args.zi or (log["xpg_zi_m"][-1] if len(log["xpg_zi_m"]) == n_rows else 2000.0)
    seed, day = int(log["xpg_seed"][-1]), int(log["date_days"][-1])
    sky_name = SKY_NAMES[int(log["xpg_sky_index"][-1])]
    sky_t = log["t_zulu_s"]
    if len(log["t_local_s"]) == n_rows:
        sky_t = np.array([sky_time(z, o) for z, o in zip(log["t_zulu_s"], log["t_local_s"])])

    frame = LocalFrame(log["lat_deg"][0], log["lon_deg"][0])
    ground = np.array([frame.to_enu(a, o) for a, o in zip(log["lat_deg"], log["lon_deg"])])
    air = np.array([frame.to_enu(a - da, o - do) for a, o, da, do in
                    zip(log["lat_deg"], log["lon_deg"], log["xpg_dlat_deg"], log["xpg_dlon_deg"])])

    t = log["t_run_s"]
    keep = np.unique(np.searchsorted(t, np.arange(t[0], t[-1], 1.0)).clip(0, n_rows - 1))
    circlings = find_circlings(t[keep], log["psi_deg"][keep], ground[keep, 0], ground[keep, 1], log["agl_m"][keep])
    print(f"{args.log}\nt_run {t[0]:.0f}-{t[-1]:.0f}, sky {sky_name}, seed {seed}, day {day}, w* {wstar:.1f}, zi {zi:.0f}, "
          f"wind {log['wind_ms'].min():.1f}-{log['wind_ms'].max():.1f} m/s, "
          f"{'markers on at some point' if (log.get('xpg_markers') is not None and log['xpg_markers'].max() > 0) else 'no markers'}")
    if len(log["xpg_lean_e_m"]) == n_rows and np.abs(log["xpg_lean_e_m"]).max() > 0.0:
        print("The lean was on.")
    if len(log["xpg_wind_at_clouds"]) == n_rows and log["xpg_wind_at_clouds"].max() > 0.0:
        print("The sky moved with the wind at the clouds.")
    climbs = [read_climb(log, sky_t, air[:, 0], air[:, 1], frame, keep[a], keep[b], seed, day, SKIES[sky_name], wstar, zi)
              for a, b in circlings]
    print(f"{len(climbs)} circling(s) of at least one turn.")
    report_climbs(climbs)
    report_hills(log)
    report_size(climbs)
    report_top(climbs)
    report_overhead(climbs)


if __name__ == "__main__":
    main()
