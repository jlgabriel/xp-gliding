"""Summarize a flight log written by PI_xpg_flightlog.py, one row per mark.

Usage:
    python analyze_flightlog.py LOG.csv [--markdown] [--min-duration 10]

Each mark value (the counter the pilot advances with the "mark" command) is
one segment. For every segment it reports frame rate, speeds, bank, and three
vertical speeds:

  vs_geo  slope of a least-squares fit of altitude against time (m/s)
  vs_te   same fit on energy height h + TAS^2 / 2g, which removes the effect
          of speeding up or slowing down during the segment (m/s)
  vs_ind  mean of X-Plane's own vertical speed (m/s), as a cross-check

Rows recorded while paused or in replay, and rows where the sim clock did not
advance, are dropped. Pure standard library; runs on Python 3.12+.
"""

import argparse
import csv
import math
import statistics
import sys

G = 9.80665
KT_TO_KMH = 1.852
FPM_TO_MS = 0.00508


def load_rows(path):
    """Read a log, skipping '#' metadata lines. Returns (metadata, rows)."""
    metadata = {}
    with open(path, encoding="utf-8", newline="") as f:
        lines = []
        for line in f:
            if line.startswith("#"):
                key, _, value = line[1:].strip().partition("=")
                metadata[key.strip()] = value.strip()
            else:
                lines.append(line)
    rows = []
    for raw in csv.DictReader(lines):
        rows.append({k: _num(v) for k, v in raw.items()})
    return metadata, rows


def _num(text):
    if text is None or text == "":
        return None
    try:
        return float(text)
    except ValueError:
        return text


def flying_rows(rows):
    """Drop paused / replay rows and rows where the sim clock did not move."""
    kept = []
    last_t = None
    for row in rows:
        if row.get("paused") or row.get("replay"):
            continue
        t = row["t_run_s"]
        if last_t is not None and t <= last_t:
            continue
        kept.append(row)
        last_t = t
    return kept


def linear_slope(xs, ys):
    """Least-squares slope of ys against xs."""
    mean_x = statistics.fmean(xs)
    mean_y = statistics.fmean(ys)
    sxx = sum((x - mean_x) ** 2 for x in xs)
    if sxx == 0:
        return math.nan
    return sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / sxx


def _mean(rows, key):
    values = [r[key] for r in rows if isinstance(r.get(key), float)]
    return statistics.fmean(values) if values else math.nan


def _stdev(rows, key):
    values = [r[key] for r in rows if isinstance(r.get(key), float)]
    return statistics.stdev(values) if len(values) > 1 else math.nan


def _percentile(values, q):
    ordered = sorted(values)
    if not ordered:
        return math.nan
    index = min(len(ordered) - 1, max(0, math.ceil(q * len(ordered)) - 1))
    return ordered[index]


def segment_stats(rows):
    """Statistics for one contiguous group of flying rows."""
    t = [r["t_run_s"] for r in rows]
    h = [r["elev_m"] for r in rows]
    he = [r["elev_m"] + r["tas_ms"] ** 2 / (2 * G) for r in rows]
    periods = [r["frame_period_s"] for r in rows if r["frame_period_s"]]
    return {
        "duration_s": t[-1] - t[0],
        "frames": len(rows),
        "fps_mean": 1 / statistics.fmean(periods) if periods else math.nan,
        "fps_1pct_low": 1 / _percentile(periods, 0.99) if periods else math.nan,
        "ias_kmh": _mean(rows, "ias_kt") * KT_TO_KMH,
        "ias_sd_kmh": _stdev(rows, "ias_kt") * KT_TO_KMH,
        "tas_ms": _mean(rows, "tas_ms"),
        "bank_deg": statistics.fmean(abs(r["phi_deg"]) for r in rows),
        "vs_geo": linear_slope(t, h),
        "vs_te": linear_slope(t, he),
        "vs_ind": _mean(rows, "vs_ms"),
        "te_vario": _mean(rows, "te_fpm") * FPM_TO_MS,
        "mass_kg": _mean(rows, "mass_kg"),
        "wind_ms": _mean(rows, "wind_ms"),
        "native_thermal_ms": _mean(rows, "native_thermal_ms"),
        "sun_pitch_deg": _mean(rows, "sun_pitch_deg"),
        "pre_fnrml_n": _mean(rows, "pre_fnrml_n"),
        "post_fnrml_n": _mean(rows, "post_fnrml_n"),
        "pre_faxil_n": _mean(rows, "pre_faxil_n"),
        "post_faxil_n": _mean(rows, "post_faxil_n"),
        "pre_l_nm": _mean(rows, "pre_l_nm"),
        "post_l_nm": _mean(rows, "post_l_nm"),
        "alex_cal_mode": _mean(rows, "alex_cal_mode"),
        "alex_cal_ms": _mean(rows, "alex_cal_ms"),
        "alex_lift_ms": _mean(rows, "alex_lift_ms"),
    }


def by_mark(rows, min_duration_s):
    """Group flying rows by mark value; keep segments of at least min_duration_s."""
    groups = {}
    for row in flying_rows(rows):
        groups.setdefault(int(row["mark"]), []).append(row)
    result = []
    for mark in sorted(groups):
        group = groups[mark]
        if len(group) >= 3 and group[-1]["t_run_s"] - group[0]["t_run_s"] >= min_duration_s:
            result.append((mark, segment_stats(group)))
    return result


REPORT_COLUMNS = (
    ("mark", "{:d}"),
    ("duration_s", "{:.0f}"),
    ("fps_mean", "{:.0f}"),
    ("fps_1pct_low", "{:.0f}"),
    ("ias_kmh", "{:.1f}"),
    ("ias_sd_kmh", "{:.1f}"),
    ("bank_deg", "{:.0f}"),
    ("vs_geo", "{:+.2f}"),
    ("vs_te", "{:+.2f}"),
    ("vs_ind", "{:+.2f}"),
    ("te_vario", "{:+.2f}"),
    ("alex_cal_mode", "{:.0f}"),
    ("alex_cal_ms", "{:.1f}"),
    ("alex_lift_ms", "{:.2f}"),
    ("pre_fnrml_n", "{:.0f}"),
    ("post_fnrml_n", "{:.0f}"),
    ("pre_faxil_n", "{:.0f}"),
    ("post_faxil_n", "{:.0f}"),
)


def _cell(fmt, value):
    if isinstance(value, float) and math.isnan(value):
        return "-"
    return fmt.format(value)


def format_report(segments, markdown):
    header = [name for name, _ in REPORT_COLUMNS]
    body = []
    for mark, stats in segments:
        values = dict(stats, mark=mark)
        body.append([_cell(fmt, values[name]) for name, fmt in REPORT_COLUMNS])
    if markdown:
        lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
        lines += ["| " + " | ".join(row) + " |" for row in body]
        return "\n".join(lines)
    widths = [max(len(h), *(len(r[i]) for r in body)) if body else len(h) for i, h in enumerate(header)]
    lines = ["  ".join(h.rjust(w) for h, w in zip(header, widths))]
    lines += ["  ".join(c.rjust(w) for c, w in zip(row, widths)) for row in body]
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("log", help="CSV written by PI_xpg_flightlog.py")
    parser.add_argument("--markdown", action="store_true", help="print a Markdown table")
    parser.add_argument("--min-duration", type=float, default=10.0, help="skip shorter segments (s)")
    args = parser.parse_args(argv)

    metadata, rows = load_rows(args.log)
    for key, value in metadata.items():
        print(f"{key}: {value}")
    flying = flying_rows(rows)
    if flying:
        whole = segment_stats(flying)
        print(f"flying: {whole['duration_s']:.0f} s, {whole['frames']} frames, "
              f"{whole['fps_mean']:.0f} fps mean, {whole['fps_1pct_low']:.0f} fps 1% low, "
              f"mass {whole['mass_kg']:.0f} kg")
    print()
    print(format_report(by_mark(rows, args.min_duration), args.markdown))
    return 0


if __name__ == "__main__":
    sys.exit(main())
