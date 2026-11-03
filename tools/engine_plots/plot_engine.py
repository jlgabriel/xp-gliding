"""Plots of the atmospheric engine, made outside the simulator.

Usage:
    python tools/engine_plots/plot_engine.py [--out plots] [--wstar 2.56] [--zi 1401]

Writes PNG files:
  allen_fig10.png    single-updraft profiles at four heights (compare with the
                     paper's Fig. 10); paper mode dashed, engine mode solid
  allen_fig12.png    the paper's check case cross-section (Fig. 12)
  field_map.png      lift over 6 km x 6 km at three heights, one instant
  section.png        vertical cross-section w(r, z) through a mature thermal
  life_cycle.png     lift at a thermal's centre over its life
  day_timeline.png   lift at fixed points over two hours (no jumps allowed)

Needs matplotlib (development only; it is not used in the simulator). Run it
from the repository root with the project's Python 3.12 venv.
"""

import argparse
import math
import os
import sys

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

from xp_gliding.engine import field as fld  # noqa: E402
from xp_gliding.engine import updraft as upd  # noqa: E402
from xp_gliding.engine.geo import LocalFrame  # noqa: E402

LAT, LON = -33.45, -70.95
NOON = 12 * 3600.0


def plot_fig10(out, wstar, zi):
    fig, ax = plt.subplots(figsize=(8, 5))
    rs = [k * 0.5 for k in range(0, 501)]
    for zzi in (0.2, 0.4, 0.6, 0.8):
        z = zzi * zi
        paper = [upd.updraft_velocity(r, z, zi, wstar, blend_shapes=False,
                                      stretch_everywhere=False) for r in rs]
        engine = [upd.updraft_velocity(r, z, zi, wstar) for r in rs]
        line, = ax.plot(rs, engine, label=f"z/zi = {zzi}")
        ax.plot(rs, paper, "--", color=line.get_color(), linewidth=0.8)
    ax.axhline(0, color="black", linewidth=0.5)
    ax.set(xlabel="r (m)", ylabel="w (m/s)",
           title=f"Single updraft, no environment sink (w* {wstar}, zi {zi:.0f} m)")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.savefig(os.path.join(out, "allen_fig10.png"), dpi=120, bbox_inches="tight")
    plt.close(fig)


def plot_fig12(out):
    wstar, zi, z = 2.56, 1401.0, 280.0
    r2 = upd.mean_outer_radius(z / zi, zi)
    n = round(0.6 * 1e6 / (zi * r2))
    at = n * math.pi * r2 ** 2
    we = -(at * upd.mean_updraft(z / zi, wstar)) / (1e6 - at)
    centres = [k * 1000.0 / (n + 1) for k in range(1, n + 1)]
    ys = [k * 1.0 for k in range(0, 391)]
    fig, ax = plt.subplots(figsize=(8, 5))
    for label, opts, style in (("paper (Appendix B)", dict(blend_shapes=False, stretch_everywhere=False), "--"),
                               ("engine", {}, "-")):
        w = [upd.updraft_velocity(min(math.hypot(170 - c, y - c) for c in centres),
                                  z, zi, wstar, we=we, **opts) for y in ys]
        ax.plot(ys, w, style, label=label)
    ax.set(xlabel="y (m)", ylabel="w (m/s)", ylim=(-0.5, 3.0),
           title="Allen check case (paper Fig. 12)")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.savefig(os.path.join(out, "allen_fig12.png"), dpi=120, bbox_inches="tight")
    plt.close(fig)


def make_field(range_m=5000.0):
    cfg = fld.FieldConfig(seed=1, day=9800, range_m=range_m)
    field = fld.ThermalField(cfg, LocalFrame(LAT, LON))
    field.update(NOON, LAT, LON)
    return field


def plot_field_map(out, field, wstar, zi):
    half, step = 3000.0, 20.0
    k = int(2 * half / step)
    xs = [-half + i * step for i in range(k + 1)]
    fig, axes = plt.subplots(1, 3, figsize=(16, 5.2), constrained_layout=True)
    for ax, zzi in zip(axes, (0.2, 0.5, 0.8)):
        z = zzi * zi
        grid = [[field.lift_at(e, n, z, NOON, wstar, zi) for e in xs] for n in xs]
        im = ax.imshow(grid, origin="lower", extent=(-half, half, -half, half),
                       cmap="RdBu_r", vmin=-3, vmax=3)
        ax.set(title=f"z = {z:.0f} m AGL (z/zi {zzi})", xlabel="east (m)", ylabel="north (m)")
    fig.colorbar(im, ax=axes, label="w (m/s)", shrink=0.9)
    fig.suptitle(f"Thermal field at 12:00 UTC (w* {wstar}, zi {zi:.0f} m, "
                 f"{field.config.density_per_km2:.1f} thermals/km2)")
    fig.savefig(os.path.join(out, "field_map.png"), dpi=110)
    plt.close(fig)


def strongest_mature(field, t):
    mature = [th for th in field.alive(t) if th.envelope(t)[0] == 1.0]
    return max(mature, key=lambda th: th.wgain * th.rgain)


def plot_section(out, field, wstar, zi):
    th = strongest_mature(field, NOON)
    rs = [-400 + 4 * i for i in range(201)]
    zs = [zi * k / 100 for k in range(1, 101)]
    grid = [[field.lift_at(th.e + r, th.n, z, NOON, wstar, zi) for r in rs] for z in zs]
    fig, ax = plt.subplots(figsize=(9, 5))
    im = ax.imshow(grid, origin="lower", aspect="auto", extent=(rs[0], rs[-1], zs[0], zs[-1]),
                   cmap="RdBu_r", vmin=-3, vmax=3)
    fig.colorbar(im, label="w (m/s)")
    ax.set(xlabel="east of thermal centre (m)", ylabel="z AGL (m)",
           title=f"Vertical section, wgain {th.wgain:.2f}, rgain {th.rgain:.2f}")
    fig.savefig(os.path.join(out, "section.png"), dpi=120, bbox_inches="tight")
    plt.close(fig)


def plot_life_cycle(out, field, wstar, zi):
    th = strongest_mature(field, NOON)
    ts = [th.birth - 60 + k * 5.0 for k in range(int((th.death - th.birth + 120) / 5))]
    fig, ax = plt.subplots(figsize=(9, 4.5))
    for zzi in (0.2, 0.5, 0.8):
        w = [field.lift_at(th.e, th.n, zzi * zi, t, wstar, zi) for t in ts]
        ax.plot([(t - th.birth) / 60 for t in ts], w, label=f"z/zi {zzi}")
    ax.set(xlabel="minutes since birth", ylabel="w at centre (m/s)",
           title=f"Life cycle of one thermal ({(th.death - th.birth) / 60:.1f} min)")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.savefig(os.path.join(out, "life_cycle.png"), dpi=120, bbox_inches="tight")
    plt.close(fig)


def plot_day_timeline(out, wstar, zi):
    field = make_field(range_m=2000.0)
    ts = [NOON + k * 2.0 for k in range(3600)]
    fig, ax = plt.subplots(figsize=(10, 4.5))
    for e, n in ((0, 0), (250, -400), (-600, 300)):
        w = []
        for t in ts:
            field.update(t, LAT, LON)
            w.append(field.lift_at(e, n, 0.4 * zi, t, wstar, zi))
        ax.plot([(t - NOON) / 60 for t in ts], w, linewidth=0.8, label=f"({e}, {n}) m")
    ax.set(xlabel="minutes after 12:00 UTC", ylabel="w (m/s)",
           title="Lift at fixed points, z/zi 0.4: thermals come and go smoothly")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.savefig(os.path.join(out, "day_timeline.png"), dpi=120, bbox_inches="tight")
    plt.close(fig)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", default="plots", help="output directory (default: plots)")
    parser.add_argument("--wstar", type=float, default=2.56, help="convective velocity w* (m/s)")
    parser.add_argument("--zi", type=float, default=1401.0, help="mixing-layer thickness zi (m)")
    args = parser.parse_args(argv)
    os.makedirs(args.out, exist_ok=True)
    plot_fig10(args.out, args.wstar, args.zi)
    plot_fig12(args.out)
    field = make_field()
    plot_field_map(args.out, field, args.wstar, args.zi)
    plot_section(args.out, field, args.wstar, args.zi)
    plot_life_cycle(args.out, field, args.wstar, args.zi)
    plot_day_timeline(args.out, args.wstar, args.zi)
    print(f"plots written to {os.path.abspath(args.out)}")


if __name__ == "__main__":
    main()
