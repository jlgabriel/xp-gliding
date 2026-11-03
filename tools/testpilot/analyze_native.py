"""Lift profiles from the native audit passes (audit_native.py).

Usage:
    python tools/testpilot/analyze_native.py [--names cross_375 ...] [--plot DIR] [--markdown]

For every pass in the manifest (the latest entry per name), the log is cut
into windows of --window seconds and each window gets:

  native lift = vs_te - still-air sink at that IAS, TAS and bank

where vs_te is the slope of energy height h + TAS^2/2g (see
analyze_flightlog.py) and the still-air sink comes from the test A polar
(sea-level sink scaled by TAS/IAS, and by n^1.5 = cos(bank)^-1.5 in a turn).
Positions are reported along and across the pass line, and X-Plane's terrain
under the glider is elevation minus AGL.

Measurement tool, not part of the plugin. License: GPL-3.0-or-later.
"""

import argparse
import json
import math
import os
import statistics
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "flightlog"))

from analyze_flightlog import flying_rows, linear_slope, load_rows  # noqa: E402
from audit_native import MANIFEST  # noqa: E402
from control import LineHold  # noqa: E402
from pilot import LOG_DIR  # noqa: E402
from polar import polar_sink  # noqa: E402
from xp_gliding.engine.geo import LocalFrame  # noqa: E402

G = 9.80665
KT_TO_KMH = 1.852
def latest_entries(names=None):
    entries = {}
    with open(MANIFEST, encoding="utf-8") as f:
        for line in f:
            e = json.loads(line)
            if e.get("log") and (not names or e["name"] in names):
                entries[e["name"]] = e
    return list(entries.values())


def windows(entry, window_s=5.0):
    """One dict per window of the pass."""
    _, rows = load_rows(os.path.join(LOG_DIR, entry["log"]))
    rows = flying_rows(rows)
    frame = LocalFrame(*entry["origin"])
    line = LineHold(tuple(entry["start_en"]), tuple(entry["end_en"]))
    out = []
    i = 0
    while i < len(rows):
        j = i
        while j < len(rows) and rows[j]["t_run_s"] - rows[i]["t_run_s"] < window_s:
            j += 1
        chunk = rows[i:j]
        if len(chunk) < 10 or chunk[-1]["t_run_s"] - chunk[0]["t_run_s"] < 0.8 * window_s:
            break
        t = [r["t_run_s"] for r in chunk]
        he = [r["elev_m"] + r["tas_ms"] ** 2 / (2 * G) for r in chunk]
        vs_te = linear_slope(t, he)
        ias = statistics.fmean(r["ias_kt"] for r in chunk) * KT_TO_KMH
        tas = statistics.fmean(r["tas_ms"] for r in chunk)
        bank = statistics.fmean(abs(r["phi_deg"]) for r in chunk)
        mid = chunk[len(chunk) // 2]
        e, n = frame.to_enu(mid["lat_deg"], mid["lon_deg"])
        along, cross = line.along_cross(e, n)
        out.append({
            "t": mid["t_run_s"] - rows[0]["t_run_s"],
            "along_m": along, "cross_m": cross,
            "lat": mid["lat_deg"], "lon": mid["lon_deg"],
            "elev_m": statistics.fmean(r["elev_m"] for r in chunk),
            "terrain_m": statistics.fmean(r["elev_m"] - r["agl_m"] for r in chunk),
            "agl_m": statistics.fmean(r["agl_m"] for r in chunk),
            "ias_kmh": ias, "tas_ms": tas, "bank_deg": bank,
            "vs_te": vs_te,
            "lift_ms": vs_te + polar_sink(ias, tas, bank),
            "native_thermal_ms": statistics.fmean(r["native_thermal_ms"] for r in chunk),
            "wind_ms": statistics.fmean(r["wind_ms"] for r in chunk),
            "wind_dir": statistics.fmean(r["wind_dir_deg"] for r in chunk),
        })
        i = j
    return out


def slope_fit(w):
    """For a crossing (flown along the wind): compare the lift with wind x terrain
    slope under the glider (the simplest ridge model). Adds `w_slope` to each
    window and returns (gain, r) of lift ~ gain * w_slope, or None."""
    pairs = []
    for a, b, c in zip(w, w[1:], w[2:]):
        dx = c["along_m"] - a["along_m"]
        if dx <= 0:
            continue
        b["w_slope"] = b["wind_ms"] * (c["terrain_m"] - a["terrain_m"]) / dx
        pairs.append((b["w_slope"], b["lift_ms"]))
    if len(pairs) < 5:
        return None
    xs, ys = zip(*pairs)
    sxx = sum(x * x for x in xs)
    gain = sum(x * y for x, y in pairs) / sxx if sxx else math.nan
    try:
        r = statistics.correlation(xs, ys)
    except statistics.StatisticsError:
        r = math.nan
    return gain, r


def thermal_report(entry):
    """Test I: one line per circle (odd marks) and cruise statistics."""
    _, rows = load_rows(os.path.join(LOG_DIR, entry["log"]))
    rows = flying_rows(rows)
    lines = []
    by_mark = {}
    for r in rows:
        by_mark.setdefault(int(r["mark"]), []).append(r)
    for mark, chunk in sorted(by_mark.items()):
        if mark % 2 == 0 or len(chunk) < 100:
            continue
        chunk = chunk[len(chunk) // 4:]  # skip the first part of the turns (centering)
        t = [r["t_run_s"] for r in chunk]
        he = [r["elev_m"] + r["tas_ms"] ** 2 / (2 * G) for r in chunk]
        vs_te = linear_slope(t, he)
        ias = statistics.fmean(r["ias_kt"] for r in chunk) * KT_TO_KMH
        tas = statistics.fmean(r["tas_ms"] for r in chunk)
        bank = statistics.fmean(abs(r["phi_deg"]) for r in chunk)
        rate = [r["native_thermal_ms"] for r in chunk]
        alex = [r["alex_lift_ms"] for r in chunk if isinstance(r.get("alex_lift_ms"), float)]
        alex_text = f"; Alex's model {statistics.fmean(alex):+.2f} m/s" if alex else ""
        lines.append(f"  circle {mark // 2 + 1}: {t[-1] - t[0]:.0f} s, AGL {chunk[0]['agl_m']:.0f} m, "
                     f"bank {bank:.0f}, IAS {ias:.0f}: climb vs_te {vs_te:+.2f} m/s, "
                     f"lift {vs_te + polar_sink(ias, tas, bank):+.2f} m/s; dataref mean "
                     f"{statistics.fmean(rate):+.2f} (min {min(rate):+.2f}, max {max(rate):+.2f}){alex_text}")
    cruise = [r for r in rows if int(r["mark"]) % 2 == 0 and abs(r["phi_deg"]) < 5]
    if cruise:
        rates = [r["native_thermal_ms"] for r in cruise]
        inside = [x for x in rates if x > 0.1]
        sink = [x for x in rates if x < -0.1]
        # widths of contiguous stretches with the dataref above 0.1 m/s (ground distance)
        widths, run_start = [], None
        for a, b in zip(cruise, cruise[1:]):
            if b["native_thermal_ms"] > 0.1 and run_start is None:
                run_start = b
            elif b["native_thermal_ms"] <= 0.1 and run_start is not None:
                widths.append(_ground_m(run_start, b))
                run_start = None
        lines.append(f"  cruise: {len(cruise)} frames; dataref > 0.1 m/s in {len(inside) / len(rates):.0%}"
                     f" of them, < -0.1 in {len(sink) / len(rates):.0%}; max {max(rates):+.2f}, "
                     f"min {min(rates):+.2f}; lift stretches (m): "
                     f"{', '.join(f'{w:.0f}' for w in widths) or 'none'}")
    return lines


def _ground_m(a, b):
    frame = LocalFrame(a["lat_deg"], a["lon_deg"])
    e, n = frame.to_enu(b["lat_deg"], b["lon_deg"])
    return math.hypot(e, n)


def plot(entries, outdir, window_s):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    os.makedirs(outdir, exist_ok=True)
    for e in entries:
        w = windows(e, window_s)
        if not w:
            continue
        x = [r["along_m"] / 1000 for r in w]
        fig, (ax1, ax2) = plt.subplots(2, 1, sharex=True, figsize=(9, 6))
        ax1.plot(x, [r["terrain_m"] for r in w], color="saddlebrown", label="X-Plane terrain")
        ax1.plot(x, [r["elev_m"] for r in w], color="tab:blue", label="glider")
        ax1.set_ylabel("m MSL")
        ax1.legend(loc="best")
        ax1.set_title(f"{e['name']}: {e['desc']}")
        ax2.axhline(0, color="k", lw=0.5)
        ax2.plot(x, [r["lift_ms"] for r in w], marker=".", label="native lift (vs_te - polar)")
        ax2.plot(x, [r["native_thermal_ms"] for r in w], label="thermal_rate_ms dataref")
        if e["name"].startswith("cross") and slope_fit(w):
            ax2.plot([r["along_m"] / 1000 for r in w if "w_slope" in r],
                     [r["w_slope"] for r in w if "w_slope" in r], ls="--",
                     label="wind x terrain slope")
        ax2.set_ylabel("m/s")
        ax2.set_xlabel("km along the pass")
        ax2.legend(loc="best")
        ax2.grid(alpha=0.3)
        fig.tight_layout()
        fig.savefig(os.path.join(outdir, f"{e['name']}.png"), dpi=90)
        plt.close(fig)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Lift profiles of the native audit passes")
    parser.add_argument("--names", nargs="*", help="pass names (default: all)")
    parser.add_argument("--window", type=float, default=5.0, help="window length (s)")
    parser.add_argument("--plot", help="directory for one PNG per pass")
    parser.add_argument("--rows", action="store_true", help="print every window")
    args = parser.parse_args(argv)
    entries = latest_entries(set(args.names or ()))
    for e in entries:
        w = windows(e, args.window)
        print(f"== {e['name']} ({e['desc']}) {e['log']} {e['result']}")
        if e.get("test") in ("I", "E"):
            print("\n".join(thermal_report(e)))
        if args.rows:
            for r in w:
                print(f"  {r['along_m']:7.0f} m  cross {r['cross_m']:+5.0f}  terrain {r['terrain_m']:5.0f}"
                      f"  agl {r['agl_m']:5.0f}  ias {r['ias_kmh']:5.1f}  vs_te {r['vs_te']:+5.2f}"
                      f"  lift {r['lift_ms']:+5.2f}  wind {r['wind_ms'] / 0.5144:4.1f} kt"
                      f" / {r['wind_dir']:3.0f}")
        fit = slope_fit(w) if e["name"].startswith("cross") else None
        if fit:
            print(f"  lift vs wind x terrain slope: gain {fit[0]:.2f}, r {fit[1]:.2f}")
        if w:
            best = max(w, key=lambda r: r["lift_ms"])
            worst = min(w, key=lambda r: r["lift_ms"])
            print(f"  max lift {best['lift_ms']:+.2f} m/s at {best['along_m']:.0f} m "
                  f"(AGL {best['agl_m']:.0f});  min {worst['lift_ms']:+.2f} m/s at "
                  f"{worst['along_m']:.0f} m (AGL {worst['agl_m']:.0f})")
    if args.plot:
        plot(entries, args.plot, args.window)


if __name__ == "__main__":
    main()
