"""Replay logged flights through the HUD's vario and compare with the engine's lift.

Usage:
    python tools/flightlog/replay_vario.py LOG.csv [LOG.csv ...]

Feeds `xp_gliding.adapter.vario.Vario` the logged state at its 10 Hz sample rate,
then, over steady 20 s stretches, compares its netto with the lift the plugin
applied (`xpg_lift_ms`) and X-Plane's own total-energy gauge with its TE. The lift
is the oracle here: the vario never sees it. Prints the residual per bank band.

Measurement tool, not part of the plugin. License: GPL-3.0-or-later.
"""

import csv
import os
import statistics
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from xp_gliding.adapter.vario import ASK21_LAMINAR, SAMPLE_PERIOD_S, Vario  # noqa: E402

KT_TO_KMH = 1.852
FPM_TO_MS = 0.3048 / 60.0
WINDOW_S = 20.0
BANDS = ((0, 5), (5, 20), (20, 35), (35, 42), (42, 48), (48, 60))


def read_log(path):
    with open(path, newline="") as f:
        for row in csv.DictReader(line for line in f if not line.startswith("#")):
            yield row


def replay(path):
    """Return stretches of WINDOW_S with steady bank and speed, each a dict of means."""
    vario = Vario(ASK21_LAMINAR)
    stretches, current, next_sample = [], [], 0.0
    for row in read_log(path):
        if row["paused"] != "0" or row["replay"] != "0":
            vario.reset()
            current = []
            continue
        t = float(row["t_run_s"])
        if t < next_sample:
            continue
        next_sample = t + SAMPLE_PERIOD_S
        ias, bank = float(row["ias_kt"]) * KT_TO_KMH, abs(float(row["phi_deg"]))
        tas = float(row["tas_ms"])
        ok = vario.update(t, float(row["elev_m"]), tas, ias, bank, float(row["mass_kg"]))
        if not ok or float(row["agl_m"]) < 100.0:
            current = []
            continue
        lift = float(row["xpg_lift_ms"] or 0.0)
        current.append((t, ias, bank, vario.te_ms, vario.netto_ms, lift,
                        float(row["te_fpm"]) * FPM_TO_MS))
        if t - current[0][0] >= WINDOW_S:
            cols = list(zip(*current))
            if statistics.pstdev(cols[1]) < 4.0 and statistics.pstdev(cols[2]) < 4.0 \
                    and statistics.fmean(cols[1]) > 60.0:
                stretches.append({
                    "ias": statistics.fmean(cols[1]), "bank": statistics.fmean(cols[2]),
                    "te": statistics.fmean(cols[3]), "netto": statistics.fmean(cols[4]),
                    "lift": statistics.fmean(cols[5]), "gauge": statistics.fmean(cols[6]),
                })
            current = []
    return stretches


def main(argv):
    if not argv:
        raise SystemExit(__doc__)
    stretches = [s for path in argv for s in replay(path)]
    print(f"{len(stretches)} steady stretches of {WINDOW_S:.0f} s")
    print("| Bank (deg) | n | IAS (km/h) | Netto - lift (m/s) | spread | Gauge - TE (m/s) | spread |")
    print("| --- | --- | --- | --- | --- | --- | --- |")
    for lo, hi in BANDS:
        band = [s for s in stretches if lo <= s["bank"] < hi]
        if not band:
            continue
        err = [s["netto"] - s["lift"] for s in band]
        gauge = [s["gauge"] - s["te"] for s in band]
        print(f"| {lo}-{hi} | {len(band)} | {statistics.fmean(s['ias'] for s in band):.0f} "
              f"| {statistics.fmean(err):+.3f} | {statistics.pstdev(err):.3f} "
              f"| {statistics.fmean(gauge):+.3f} | {statistics.pstdev(gauge):.3f} |")


if __name__ == "__main__":
    main(sys.argv[1:])
