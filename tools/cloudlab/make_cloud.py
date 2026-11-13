"""Generate the cloud lab's objects: the plugin's cumulus, with other ways to drive it.

Usage:
    python tools/cloudlab/make_cloud.py OUT_DIR [--version 1] [--max-particles N]
    python tools/cloudlab/make_cloud.py OUT_DIR --version 2 --plugin [--rev REV]

Writes cuN_global.obj, cuN_inst.obj, cuN_fast.obj, cuN.pss and cuN.png, from the look in
`tools/make_cloud_objs.py`. The version changes between tries because X-Plane may keep a
loaded particle system by its path, so a new look can be loaded without restarting the
simulator.

The emitters differ only in what drives their rate, which was one of the lab's questions:
- cu_global: a slot on the lab's dataref `xpg_cloudlab/rate`, the same for all clouds.
- cu_inst: a slot on `xpg_cloudlab/i_rate`, a dataref of the instance.
- cu_fast: a fixed high rate, to build a cloud fast.

With --plugin it writes cuN_plugin.obj instead: the plugin's own assets as they are, driven
by the plugin's rate and scale datarefs, so a look is seen exactly as it ships. With --rev
they come from that git revision of the standard cloud style, so an older look can stand
next to the new one (the lab keeps every version it has loaded).

Measurement tool, not part of the plugin. License: GPL-3.0-or-later.
"""

import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import make_cloud_objs as cloud  # noqa: E402


def pss(name, max_particles):
    parts = cloud.particles(max_particles=max_particles)
    rows = [(0.0, 0.0), (1.0, 1.0), (cloud.RATE_TOP, cloud.RATE_TOP)]
    fast = [(0.0, cloud.RATE_TOP), (1.0, cloud.RATE_TOP)]
    emitters = (cloud.emitter("cu_global", rows, 0, None, ["xpg_cloudlab/rate"])
                + cloud.emitter("cu_inst", rows, 0, None, ["xpg_cloudlab/i_rate"])
                + cloud.emitter("cu_fast", fast, None, None, []))
    return cloud.system(name, parts, emitters)


def from_git(rev, name):
    """A file of the plugin's cumulus at git revision `rev`: in `standard/` since the cloud styles,
    in `xp_gliding/assets/clouds/` itself before."""
    for folder in ("xp_gliding/assets/clouds/standard", "xp_gliding/assets/clouds"):
        run = subprocess.run(["git", "show", f"{rev}:{folder}/{name}"], cwd=cloud.REPO, capture_output=True)
        if run.returncode == 0:
            return run.stdout
    raise SystemExit(f"{name} is not in revision {rev}")


def write_plugin(out_dir, version, rev=None):
    """The plugin's cumulus as cuN_plugin.obj, from the generator or from git revision `rev`."""
    name = f"cu{version}"
    os.makedirs(out_dir, exist_ok=True)
    if rev is None:
        files = cloud.outputs()
    else:
        files = {f"{cloud.NAME}.{ext}": from_git(rev, f"{cloud.NAME}.{ext}") for ext in ("png", "pss", "obj")}
    pss_text = files[f"{cloud.NAME}.pss"].decode("ascii").replace(
        f"TEXTURE {cloud.NAME}.png", f"TEXTURE {name}.png")
    obj_text = files[f"{cloud.NAME}.obj"].decode("ascii").replace(
        f"PARTICLE_SYSTEM {cloud.NAME}.pss", f"PARTICLE_SYSTEM {name}.pss")
    with open(os.path.join(out_dir, f"{name}.png"), "wb") as f:
        f.write(files[f"{cloud.NAME}.png"])
    for ext, text in (("pss", pss_text), ("obj", obj_text)):
        path = os.path.join(out_dir, f"{name}.pss" if ext == "pss" else f"{name}_plugin.obj")
        with open(path, "w", newline="\n") as f:
            f.write(text)
    return name


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
    parser.add_argument("--plugin", action="store_true", help="the plugin's own assets")
    parser.add_argument("--rev", help="with --plugin: the git revision to take them from")
    args = parser.parse_args(argv)
    if args.plugin:
        name = write_plugin(args.out_dir, args.version, args.rev)
    else:
        name = write_all(args.out_dir, args.version, args.max_particles)
    print(f"wrote {name} to {args.out_dir}")


if __name__ == "__main__":
    main()
