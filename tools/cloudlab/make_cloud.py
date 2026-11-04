"""Generate the cloud lab's objects: the plugin's cumulus, with other ways to drive it.

Usage:
    python tools/cloudlab/make_cloud.py OUT_DIR [--version 1] [--max-particles N]

Writes cuN_global.obj, cuN_inst.obj, cuN_fast.obj, cuN.pss and cuN.png, from the look in
`tools/make_cloud_objs.py`. The version changes between tries because X-Plane may keep a
loaded particle system by its path, so a new look can be loaded without restarting the
simulator.

The emitters differ only in what drives their rate, which was one of the lab's questions:
- cu_global: a slot on the lab's dataref `xpg_cloudlab/rate`, the same for all clouds.
- cu_inst: a slot on `xpg_cloudlab/i_rate`, a dataref of the instance.
- cu_fast: a fixed high rate, to build a cloud fast.

Measurement tool, not part of the plugin. License: GPL-3.0-or-later.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import make_cloud_objs as cloud  # noqa: E402


def pss(name, max_particles):
    parts = (cloud.particle("base", 0, cloud.CELLS, cloud.BASE_SIZE, cloud.BASE_TINT,
                            cloud.ALPHA_BASE, max_particles)
             + cloud.particle("body", cloud.CELLS, cloud.CELLS, cloud.BODY_SIZE, cloud.BODY_TINT,
                              cloud.ALPHA_BODY, max_particles)
             + cloud.particle("top", 2 * cloud.CELLS, 2 * cloud.CELLS, cloud.TOP_SIZE, cloud.TOP_TINT,
                              cloud.ALPHA_TOP, max_particles))
    rows = [(0.0, 0.0), (1.0, 1.0), (cloud.RATE_TOP, cloud.RATE_TOP)]
    fast = [(0.0, cloud.RATE_TOP), (1.0, cloud.RATE_TOP)]
    emitters = (cloud.emitter("cu_global", rows, 0, None, ["xpg_cloudlab/rate"])
                + cloud.emitter("cu_inst", rows, 0, None, ["xpg_cloudlab/i_rate"])
                + cloud.emitter("cu_fast", fast, None, None, []))
    return cloud.system(name, parts, emitters)


def write_all(out_dir, version, max_particles=16384):
    name = f"cu{version}"
    os.makedirs(out_dir, exist_ok=True)
    cloud.texture().save(os.path.join(out_dir, f"{name}.png"), optimize=True)
    with open(os.path.join(out_dir, f"{name}.pss"), "w", newline="\n") as f:
        f.write(pss(name, max_particles))
    for variant, em in (("global", "cu_global"), ("inst", "cu_inst"), ("fast", "cu_fast")):
        with open(os.path.join(out_dir, f"{name}_{variant}.obj"), "w", newline="\n") as f:
            f.write(cloud.object_text(name, em))
    return name


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("out_dir")
    parser.add_argument("--version", type=int, default=1)
    parser.add_argument("--max-particles", type=int, default=16384)
    args = parser.parse_args(argv)
    print(f"wrote {write_all(args.out_dir, args.version, args.max_particles)} to {args.out_dir}")


if __name__ == "__main__":
    main()
