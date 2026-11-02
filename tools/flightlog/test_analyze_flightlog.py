import math

import analyze_flightlog as af

HEADER = [
    "t_run_s", "frame_period_s", "paused", "replay", "elev_m", "tas_ms", "ias_kt",
    "phi_deg", "vs_ms", "te_fpm", "mass_kg", "mark",
]


def write_log(path, rows):
    lines = ["# aircraft=ASK21.acf", ",".join(HEADER)]
    lines += [",".join(str(row[k]) for k in HEADER) for row in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def make_row(t, elev, tas=25.0, mark=0, paused=0):
    return {
        "t_run_s": t, "frame_period_s": 0.02, "paused": paused, "replay": 0,
        "elev_m": elev, "tas_ms": tas, "ias_kt": tas / 0.514444, "phi_deg": -30.0,
        "vs_ms": 0.0, "te_fpm": 0.0, "mass_kg": 520.0, "mark": mark,
    }


def test_segments_report_climb_rate_per_mark(tmp_path):
    rows = [make_row(i * 0.02, 1000 - 0.8 * i * 0.02, mark=1) for i in range(1000)]
    t0 = rows[-1]["t_run_s"]
    rows += [make_row(t0 + i * 0.02, 900 + 1.2 * i * 0.02, mark=2) for i in range(1, 1000)]
    log = tmp_path / "log.csv"
    write_log(log, rows)

    metadata, loaded = af.load_rows(log)
    segments = dict(af.by_mark(loaded, min_duration_s=5))

    assert metadata["aircraft"] == "ASK21.acf"
    assert math.isclose(segments[1]["vs_geo"], -0.8, abs_tol=1e-6)
    assert math.isclose(segments[2]["vs_geo"], 1.2, abs_tol=1e-6)
    assert math.isclose(segments[1]["fps_mean"], 50.0)
    assert math.isclose(segments[1]["bank_deg"], 30.0)


def test_energy_height_removes_speed_changes(tmp_path):
    # Trading speed for height at constant total energy: vs_geo > 0, vs_te == 0.
    rows = []
    for i in range(500):
        t = i * 0.02
        tas = 30.0 - 0.5 * t
        elev = 1000 + (30.0 ** 2 - tas ** 2) / (2 * af.G)
        rows.append(make_row(t, elev, tas=tas, mark=1))
    log = tmp_path / "log.csv"
    write_log(log, rows)

    _, loaded = af.load_rows(log)
    stats = dict(af.by_mark(loaded, min_duration_s=5))[1]

    assert stats["vs_geo"] > 1.0
    assert math.isclose(stats["vs_te"], 0.0, abs_tol=1e-9)


def test_paused_and_frozen_rows_are_dropped():
    rows = [make_row(0.0, 1000), make_row(0.02, 999), make_row(0.02, 500), make_row(0.04, 0, paused=1)]
    kept = af.flying_rows(rows)
    assert [r["elev_m"] for r in kept] == [1000, 999]


def test_short_segments_are_skipped(tmp_path):
    rows = [make_row(i * 0.02, 1000, mark=0) for i in range(100)]
    rows += [make_row(2 + i * 0.02, 1000, mark=1) for i in range(1000)]
    log = tmp_path / "log.csv"
    write_log(log, rows)

    _, loaded = af.load_rows(log)
    assert [mark for mark, _ in af.by_mark(loaded, min_duration_s=10)] == [1]
