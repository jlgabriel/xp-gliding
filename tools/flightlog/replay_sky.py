"""A logged flight against the sky it flew in, rebuilt from the deterministic field.

Usage:
    python tools/flightlog/replay_sky.py LOG.csv --from 600 --to 1000 [--sky wide_carriers]
        [--seed 1] [--day N] [--wstar 3] [--zi 2000]

--from and --to are `t_run_s` values while the glider was with one thermal: that thermal is
the one reported. A newer log says its day, seed, sky and the wind's offset. An older one
does not, and then the tool works them out, which takes a few minutes and has limits:

- The offset is the wind integrated from the log, plus a constant for the time before the
  log began. The distances to the nearest thermal in the log fix where the thermal is in
  that frame, with the constant unknown.
- The day is searched for: the thermal must be alive all along, near that place, and its
  core must match the log's. A match is judged by eye from the candidates printed.
- The constant is then refined so that the rebuilt lift matches the logged lift.

Prints the thermal's life and its cloud's schedule, the climb and the distance to the centre
over the given stretch, lift by distance, the entry, and the centring aid's error, replayed
as the HUD does and measured in the air's frame. The field is the oracle here: the plugin's
instruments never read it. The cloud's schedule is what the model asks for, not a
measurement of what was drawn: particles are not logged. The sky rebuilt here has no thermal
floors, so over hills its lift is not the plugin's; `read_flight.py` has them.

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

from replay_vario import KT_TO_KMH, read_log  # noqa: E402
from xp_gliding.adapter.vario import ASK21_LAMINAR, SAMPLE_PERIOD_S, CentringAid, Vario  # noqa: E402
from xp_gliding.engine.clouds import CloudParams, carries_cloud, cloud_scale, feeding_window  # noqa: E402
from xp_gliding.engine.field import SKIES, SKY_NAMES, FieldConfig, ThermalField  # noqa: E402
from xp_gliding.engine.geo import LocalFrame  # noqa: E402
from xp_gliding.engine.markers import core_of  # noqa: E402

COLUMNS = ("t_run_s", "t_zulu_s", "lat_deg", "lon_deg", "elev_m", "agl_m", "te_fpm", "tas_ms", "ias_kt",
           "phi_deg", "psi_deg", "wind_ms", "wind_dir_deg", "mass_kg", "xpg_lift_centre_ms",
           "xpg_lift_left_ms", "xpg_lift_right_ms", "xpg_roll_nm", "xpg_nearest_m", "xpg_nearest_core_ms")
OPTIONAL = ("date_days", "t_local_s", "xpg_seed", "xpg_sky_index", "xpg_dlat_deg", "xpg_dlon_deg", "xpg_lean_e_m",
            "xpg_lean_n_m", "xpg_markers", "xpg_wstar_ms", "xpg_zi_m", "xpg_wind_at_clouds", "xpg_cloud_level_m",
            "xpg_cloud_raised", "xpg_cloud_created", "xpg_cloud_base_max_m", "xpg_cloud_nearest_m",
            "xpg_cloud_nearest_base_m", "xpg_cloud_nearest_scale", "xpg_nearest_floor_m")
FPM_TO_MS = 0.00508
FIT_STEP_S = 4.0
NEAR_M = 290.0  # the log's nearest thermal is taken to be this one within this distance
SEARCH_M = 6000.0  # how far the unknown constant can move the thermal from the fitted place
AID_SHOWN_MS = 1.2  # below this half-swing the HUD hides the arrow


def load(path):
    """The log's live rows, as arrays by column."""
    data = {k: [] for k in COLUMNS + OPTIONAL}
    for row in read_log(path):
        if row["paused"] != "0" or row["replay"] != "0":
            continue
        try:
            values = [float(row[k]) for k in COLUMNS]
        except (TypeError, ValueError):
            continue
        for k, v in zip(COLUMNS, values):
            data[k].append(v)
        for k in OPTIONAL:
            if row.get(k):
                data[k].append(float(row[k]))
    return {k: np.array(v) for k, v in data.items()}


def integrated_wind(log):
    """East and north offset of the air since the log began (m), as the plugin integrates it."""
    dt = np.diff(log["t_zulu_s"], prepend=log["t_zulu_s"][0])
    dt[(dt <= 0.0) | (dt > 5.0)] = 0.0  # engine/wind.py: MAX_STEP_S
    direction = np.radians(log["wind_dir_deg"])  # where the wind comes from
    return (np.cumsum(-log["wind_ms"] * np.sin(direction) * dt),
            np.cumsum(-log["wind_ms"] * np.cos(direction) * dt))


def fit_centre(e, n, r):
    """The point whose distance to each (e, n) best matches r: Gauss-Newton."""
    c = np.array([e.mean(), n.mean()])
    for _ in range(60):
        de, dn = e - c[0], n - c[1]
        d = np.hypot(de, dn)
        c = c - np.linalg.lstsq(np.c_[-de / d, -dn / d], d - r, rcond=None)[0]
    return c, float(np.sqrt(np.mean((np.hypot(e - c[0], n - c[1]) - r) ** 2)))


def core_error(thermal, field, log, rows, wstar, zi):
    """RMS difference (m/s) between this thermal's core and the log's nearest core."""
    errors = []
    for i in rows:
        z, t = log["agl_m"][i], log["t_zulu_s"][i]
        core, _ = core_of(thermal, z, t, wstar, zi, field.environment_sink(z, wstar, zi))
        errors.append(core - log["xpg_nearest_core_ms"][i])
    return math.sqrt(sum(x * x for x in errors) / len(errors))


def find_thermal(frame, seed, day, sky, log, rows, lat, lon, centre, wstar, zi):
    """Candidates for one day: (core error, day, thermal), thermals alive all along near `centre`."""
    field = ThermalField(FieldConfig(seed=seed, day=day, range_m=SEARCH_M + 2000.0, zi_m=zi, sky=sky), frame)
    field.update(log["t_zulu_s"][rows[0]], lat, lon)
    found = []
    for th in field.thermals():
        if th.birth < log["t_zulu_s"][rows[0]] and th.death > log["t_zulu_s"][rows[-1]]:
            if math.hypot(th.e - centre[0], th.n - centre[1]) < SEARCH_M:
                found.append((core_error(th, field, log, rows, wstar, zi), day, th))
    return field, found


def refine_constant(field, frame, log, e, n, start, wstar, zi):
    """Search the constant for the rebuilt lift nearest the logged lift. Returns it and the RMS."""
    rows = np.where(log["xpg_lift_centre_ms"] > 0.5)[0][::40]  # where the lift says where the glider is

    def rms(c):
        total = 0.0
        for i in rows:
            total += (field.lift_at(e[i] - c[0], n[i] - c[1], log["agl_m"][i], log["t_zulu_s"][i], wstar, zi)
                      - log["xpg_lift_centre_ms"][i]) ** 2
        return math.sqrt(total / len(rows))

    best, best_rms = np.array(start), rms(start)
    for step in (40.0, 20.0, 10.0, 5.0, 2.0, 1.0):
        improved = True
        while improved:
            improved = False
            for de, dn in ((step, 0), (-step, 0), (0, step), (0, -step)):
                c = best + (de, dn)
                value = rms(c)
                if value < best_rms:
                    best, best_rms, improved = c, value, True
    return best, best_rms


def report_life(th, zero):
    p = CloudParams()
    start, stop = feeding_window(th, p)
    life = th.death - th.birth
    print(f"Thermal: life {life:.0f} s, wgain {th.wgain:.2f}, rgain {th.rgain:.2f}, stretch {th.stretch:.1f}")
    print(f"  t_run: born {th.birth - zero:.0f}, decay starts {th.birth + 0.7 * life - zero:.0f}, dies {th.death - zero:.0f}")
    if carries_cloud(th, p):
        print(f"  Cloud (the model's schedule): scale {cloud_scale(th):.2f}, fed from {start - zero:.0f} to "
              f"{stop - zero:.0f}, half gone about {stop - zero + p.mean_ttl_s / 2:.0f}, "
              f"last particle {stop - zero + p.ttl_s:.0f}")
    else:
        print("  No cloud")


def report_colours(th, field, zero, z, t_end, wstar, zi):
    """When the marker's colour changes, at a typical height of this flight."""
    names = ((4.0, "red"), (3.0, "orange"), (2.0, "yellow"), (1.2, "pale"), (-99.0, "no marker"))
    previous = None
    t = th.birth
    while t < min(th.death, t_end + zero):
        core, _ = core_of(th, z, t, wstar, zi, field.environment_sink(z, wstar, zi))
        name = next(n for limit, n in names if core >= limit)
        if name != previous:
            print(f"  {t - zero:6.0f}  core {core:5.2f}  {name}")
            previous = name
        t += 1.0


def report_stretch(log, r, a, b):
    m = (log["t_run_s"] >= a) & (log["t_run_s"] < b)
    te = log["te_fpm"][m] * FPM_TO_MS
    lift = log["xpg_lift_centre_ms"][m]
    east = log["lon_deg"][m] * 111000.0 * math.cos(math.radians(log["lat_deg"][m][0]))
    north = log["lat_deg"][m] * 111000.0
    print(f"{a:6.0f}-{b:<6.0f}| {np.median(r[m]):5.0f} | {np.percentile(r[m], 10):4.0f}-{np.percentile(r[m], 90):<4.0f}"
          f"| {lift.mean():5.2f} | {te.mean():+5.2f} | {(lift - te).mean():4.2f} | {np.abs(log['phi_deg'][m]).mean():4.0f} "
          f"| {log['ias_kt'][m].mean() * KT_TO_KMH:4.0f} | {log['agl_m'][m][-1] - log['agl_m'][m][0]:+5.0f} "
          f"| {math.hypot(east[-1] - east[0], north[-1] - north[0]):5.0f}")


def report_aid(log, e, n, th):
    vario, aid = Vario(ASK21_LAMINAR), CentringAid(lag_s=Vario(ASK21_LAMINAR).tau_s)
    track, out = [], []
    turned, last_psi, next_sample, count = 0.0, None, 0.0, 0
    for i in range(len(log["t_run_s"])):
        t = log["t_run_s"][i]
        if t < next_sample:
            continue
        next_sample = t + SAMPLE_PERIOD_S
        psi, bank = log["psi_deg"][i], log["phi_deg"][i]
        if not vario.update(t, log["elev_m"][i], log["tas_ms"][i], log["ias_kt"][i] * KT_TO_KMH, bank, log["mass_kg"][i]):
            continue
        aid.update(t, psi, bank, vario.netto_ms)
        count += 1
        if count % 5 == 0:
            aid.solve()
        if last_psi is not None:
            turned += abs((psi - last_psi + 180.0) % 360.0 - 180.0)
        last_psi = psi
        track.append((e[i], n[i], turned))
        while track and turned - track[0][2] > 360.0:
            track.pop(0)
        if not aid.valid or turned - track[0][2] < 330.0:
            continue
        ce, cn = np.mean([p[0] for p in track]), np.mean([p[1] for p in track])
        off = math.hypot(th.e - ce, th.n - cn)
        if off < 320.0:
            az = math.degrees(math.atan2(th.e - ce, th.n - cn)) % 360.0
            out.append((off, (aid.core_az_deg - az + 180.0) % 360.0 - 180.0, aid.amp_ms))
    out = np.array(out)
    print("| Circle off centre (m) | Samples | Median abs error (deg) | Within 45 deg | Median half-swing (m/s) | Arrow shown |")
    print("| --- | --- | --- | --- | --- | --- |")
    for lo, hi in ((0, 30), (30, 60), (60, 100), (100, 320)):
        k = (out[:, 0] >= lo) & (out[:, 0] < hi)
        if k.any():
            print(f"| {lo}-{hi} | {k.sum()} | {np.median(np.abs(out[k, 1])):.0f} | {np.mean(np.abs(out[k, 1]) <= 45):.0%} "
                  f"| {np.median(out[k, 2]):.2f} | {np.mean(out[k, 2] > AID_SHOWN_MS):.0%} |")
    k = out[:, 2] > AID_SHOWN_MS
    print(f"When shown: {k.sum()} samples, median error {np.median(np.abs(out[k, 1])):.0f} deg, "
          f"{np.mean(np.abs(out[k, 1]) <= 45):.0%} within 45")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("log")
    parser.add_argument("--from", dest="t0", type=float, required=True)
    parser.add_argument("--to", dest="t1", type=float, required=True)
    parser.add_argument("--sky", choices=sorted(SKIES))
    parser.add_argument("--seed", type=int)
    parser.add_argument("--day", type=int)
    parser.add_argument("--wstar", type=float, default=3.0)
    parser.add_argument("--zi", type=float, default=2000.0)
    args = parser.parse_args()

    log = load(args.log)
    t, zulu = log["t_run_s"], log["t_zulu_s"]
    zero = zulu[0] - t[0]
    has_offset = len(log["xpg_dlat_deg"]) == len(t)
    seed = args.seed if args.seed is not None else int(log["xpg_seed"][-1]) if has_offset else 1
    sky_name = args.sky or (SKY_NAMES[int(log["xpg_sky_index"][-1])] if has_offset else "default")
    sky = SKIES[sky_name]
    day = args.day if args.day is not None else int(log["date_days"][-1]) if has_offset else None
    print(f"{len(t)} live rows, t_run {t[0]:.0f}-{t[-1]:.0f}, sky {sky_name}, seed {seed}")

    lat0, lon0 = log["lat_deg"][0], log["lon_deg"][0]
    frame = LocalFrame(lat0, lon0)
    east, north = zip(*(frame.to_enu(a, o) for a, o in zip(log["lat_deg"], log["lon_deg"])))
    east, north = np.array(east), np.array(north)
    wanted = (t >= args.t0) & (t < args.t1) & (log["xpg_nearest_m"] < NEAR_M)
    rows = np.where(wanted)[0]
    rows = rows[np.searchsorted(t[rows], np.arange(args.t0, args.t1, FIT_STEP_S)).clip(0, len(rows) - 1)]
    rows = np.unique(rows)

    if has_offset:
        e, n = zip(*(frame.to_enu(a - da, o - do) for a, o, da, do in
                     zip(log["lat_deg"], log["lon_deg"], log["xpg_dlat_deg"], log["xpg_dlon_deg"])))
        e, n = np.array(e), np.array(n)
        if len(log["xpg_lean_e_m"]) == len(t):  # the thermals' lean, if the plugin had it on
            e = e - log["xpg_lean_e_m"]
            n = n - log["xpg_lean_n_m"]
        centre, rms = fit_centre(e[rows], n[rows], log["xpg_nearest_m"][rows])
        constant = np.zeros(2)
    else:
        wind_e, wind_n = integrated_wind(log)
        e, n = east - wind_e, north - wind_n
        centre, rms = fit_centre(e[rows], n[rows], log["xpg_nearest_m"][rows])
    print(f"Thermal's place from the log's distances: {centre[0]:.0f} E, {centre[1]:.0f} N, RMS {rms:.0f} m")
    lat, lon = frame.to_latlon(*centre)

    candidates, fields = [], {}
    for d in ([day] if day is not None else range(366)):
        fields[d], found = find_thermal(frame, seed, d, sky, log, rows, lat, lon, centre, args.wstar, args.zi)
        candidates += found
    if has_offset:  # the place is known: the thermal is the one there. The core alone can be fooled
        candidates.sort(key=lambda c: math.hypot(c[2].e - centre[0], c[2].n - centre[1]))  # by overlapping ones
    else:
        candidates.sort(key=lambda c: c[0])
    print("Candidates: core RMS (m/s), day, its offset from the fitted place (E, N, m)")
    for error, d, th in candidates[:6]:
        print(f"  {error:.3f}  {d:3d}  {th.e - centre[0]:7.0f} {th.n - centre[1]:7.0f}")
    _, day, th = candidates[0]
    field = fields[day]

    if not has_offset:
        constant, lift_rms = refine_constant(field, frame, log, e, n, centre - (th.e, th.n), args.wstar, args.zi)
        print(f"Offset when the log began: {constant[0]:.0f} E, {constant[1]:.0f} N m. Rebuilt lift against the log: RMS {lift_rms:.2f} m/s")
        e, n = e - constant[0], n - constant[1]
    r = np.hypot(e - th.e, n - th.n)

    print(f"Day {day}")
    report_life(th, zero)
    print("Marker colour at the stretch's mean height (t_run):")
    report_colours(th, field, zero, float(np.mean(log["agl_m"][rows])), t[-1], args.wstar, args.zi)

    print("\nt_run | r median | r p10-p90 | lift | TE | sink | bank | IAS km/h | height | over ground (m)")
    span = args.t1 - args.t0
    for a in np.arange(args.t0, args.t1, max(span / 4.0, 20.0)):
        report_stretch(log, r, a, min(a + max(span / 4.0, 20.0), args.t1))

    m = (t >= args.t0) & (t < args.t1)
    print("\nLift by distance over the stretch, while the core is at least 80% of its best:")
    for lo, hi in ((0, 60), (60, 100), (100, 130), (130, 160), (160, 190), (190, 220), (220, 260), (260, 320)):
        k = m & (r >= lo) & (r < hi) & (log["xpg_nearest_core_ms"] >= 0.8 * log["xpg_nearest_core_ms"][rows].max())
        if k.sum() > 50:
            print(f"  {lo}-{hi} m: {log['xpg_lift_centre_ms'][k].mean():.2f} m/s ({k.sum()} rows)")

    print("\nEntry: the first seconds under 300 m")
    first = int(np.argmax((t >= args.t0 - 60.0) & (r < 300.0)))
    for a in np.arange(t[first], t[first] + 12.0, 2.0):
        i = int(np.argmax(t >= a))
        bearing = (math.degrees(math.atan2(th.e - e[i], th.n - n[i])) - log["psi_deg"][i] + 180.0) % 360.0 - 180.0
        print(f"  {t[i]:6.0f}  r {r[i]:4.0f}  thermal at {bearing:+4.0f} deg  right-left lift "
              f"{log['xpg_lift_right_ms'][i] - log['xpg_lift_left_ms'][i]:+.2f} m/s  roll {log['xpg_roll_nm'][i]:+5.0f} N m  bank {log['phi_deg'][i]:+.1f}")

    print("\nCentring aid, in the air's frame:")
    report_aid(log, e, n, th)


if __name__ == "__main__":
    main()
