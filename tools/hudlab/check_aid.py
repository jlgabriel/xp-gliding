"""Check the centring aid on logged circles against the engine's real thermal.

Usage:
    python tools/hudlab/check_aid.py LOG.csv [LOG.csv ...] [--seed 1] [--day 305]

Replays each log through `Vario` and `CentringAid` as the HUD does, and at every moment the
aid is valid rebuilds where the circle's centre was (mean position over the last turn) and,
from the deterministic field, where the nearest thermal is. Prints the aid's direction error
and its amplitude by how far off centre the circle was. The field is the oracle here: the
aid never reads it. Measurement tool, not part of the plugin. License: GPL-3.0-or-later.
"""

import argparse
import math
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "flightlog"))

from replay_vario import KT_TO_KMH, read_log  # noqa: E402
from xp_gliding.adapter.vario import ASK21_LAMINAR, SAMPLE_PERIOD_S, CentringAid, Vario  # noqa: E402
from xp_gliding.engine.field import FieldConfig, ThermalField  # noqa: E402
from xp_gliding.engine.geo import LocalFrame  # noqa: E402

BANDS = ((0, 15), (15, 30), (30, 60), (60, 100), (100, 200))
MIN_BANK_DEG = 25.0


def replay(path, seed, day):
    vario, aid = Vario(ASK21_LAMINAR), CentringAid()
    frame, field = None, None
    track = []  # (east, north, heading turned so far)
    turned, last_psi, next_sample, next_field = 0.0, None, 0.0, 0.0
    samples, n = [], 0
    for row in read_log(path):
        if row["paused"] != "0" or row["replay"] != "0":
            continue
        t = float(row["t_run_s"])
        if t < next_sample:
            continue
        next_sample = t + SAMPLE_PERIOD_S
        lat, lon, zulu = float(row["lat_deg"]), float(row["lon_deg"]), float(row["t_zulu_s"])
        if frame is None:
            frame = LocalFrame(lat, lon)
            field = ThermalField(FieldConfig(seed=seed, day=day), frame)
        if zulu >= next_field:
            next_field = zulu + 5.0
            field.update(zulu, lat, lon)
        psi, bank = float(row["psi_deg"]), float(row["phi_deg"])
        if not vario.update(t, float(row["elev_m"]), float(row["tas_ms"]),
                            float(row["ias_kt"]) * KT_TO_KMH, bank, float(row["mass_kg"])):
            continue
        aid.update(t, psi, bank, vario.netto_ms)
        n += 1
        if n % 5 == 0:
            aid.solve()
        if last_psi is not None:
            turned += abs((psi - last_psi + 180.0) % 360.0 - 180.0)
        last_psi = psi
        e, north = frame.to_enu(lat, lon)
        track.append((e, north, turned))
        while track and turned - track[0][2] > 360.0:
            track.pop(0)
        if not aid.valid or abs(bank) < MIN_BANK_DEG or turned - track[0][2] < 330.0:
            continue
        ce = statistics.fmean(p[0] for p in track)
        cn = statistics.fmean(p[1] for p in track)
        th, offset = field.nearest(ce, cn, zulu, 500.0)
        if th is None:
            continue
        true_az = math.degrees(math.atan2(th.e - ce, th.n - cn)) % 360.0
        error = (aid.core_az_deg - true_az + 180.0) % 360.0 - 180.0
        samples.append((offset, error, aid.amp_ms))
    return samples


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("logs", nargs="+")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--day", type=int, default=305)
    args = parser.parse_args()
    samples = [s for path in args.logs for s in replay(path, args.seed, args.day)]
    print(f"{len(samples)} samples with the aid valid, circling")
    print("| Circle off centre (m) | Samples | Median abs direction error (deg) | Within 45 deg | "
          "Median amp (m/s) |")
    print("| --- | --- | --- | --- | --- |")
    for lo, hi in BANDS:
        band = [s for s in samples if lo <= s[0] < hi]
        if band:
            within = sum(abs(s[1]) <= 45.0 for s in band) / len(band)
            print(f"| {lo}-{hi} | {len(band)} | {statistics.median(abs(s[1]) for s in band):.0f} "
                  f"| {within:.0%} | {statistics.median(s[2] for s in band):.2f} |")


if __name__ == "__main__":
    main()
