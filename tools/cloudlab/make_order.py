"""Generate the cloud lab's objects for the question of draw order: which cloud is drawn on top?

Usage:
    python tools/cloudlab/make_order.py OUT_DIR [--version 1]

Writes cuN_<kind>.obj, cuN.pss and cuN.png for the kinds in ORDER_KINDS, which the lab
(`PI_xpg_cloudlab.py`) loads like its other objects. Every emitter here runs at the fast rate
of the plugin's cumulus, with no dataref, so a cloud fills in about 9 s and stays dense:

- white: the plugin's cumulus, its layers (base, wisps, body, edges, towers, tops), as drawn in flight.
- red, blue: the same shape with their own particle types, tinted, so that which one
  is drawn over the other can be told in a screenshot.
- red1, blue1: one particle type each for the whole cloud.
- pair, pairrev: one object with two emitters, red at the object's origin and blue 6 km along
  its -z (ahead, once the lab turns the instance to the aircraft's heading). pairrev lists
  blue first.
- whitepair: the same with two white emitters, the plugin's own particle types.

Measurement tool, not part of the plugin. License: GPL-3.0-or-later.
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import make_cloud_objs as cloud  # noqa: E402

RED = (1.00, 0.45, 0.40)
BLUE = (0.40, 0.60, 1.00)
SCALE = 1.5  # the clouds' size, as the plugin's scale
PAIR_M = 6000.0  # how far ahead the second emitter of a pair is
TINTS = ("white", "red", "blue")
ONE = cloud.Layer("one", sum(layer.count for layer in cloud.LAYERS), cloud.LOBE_CELLS,
                  cloud.BY_NAME["low"].size_m, cloud.BY_NAME["low"].spread,
                  (-cloud.HALF_WIDTH_M * 0.6, cloud.HALF_WIDTH_M * 0.6, 0.0, 480.0,
                   -cloud.HALF_WIDTH_M * 0.6, cloud.HALF_WIDTH_M * 0.6), (1.0, 1.0, 1.0), 0.9)
ORDER_KINDS = ("white", "red", "blue", "red1", "blue1", "pair", "pairrev", "whitepair")
FAST = [(0.0, cloud.RATE_TOP), (1.0, cloud.RATE_TOP)]


def types():
    """Particle types: each tint's layers, then the one-type clouds' red and blue."""
    out = cloud.particles(prefix="white_", max_particles=16384)
    out += cloud.particles(prefix="red_", tint=RED, max_particles=16384)
    out += cloud.particles(prefix="blue_", tint=BLUE, max_particles=16384)
    out += cloud.particles((ONE,), prefix="red", tint=RED, max_particles=16384)
    out += cloud.particles((ONE,), prefix="blue", tint=BLUE, max_particles=16384)
    return out


def all_layers(name, tint_name):
    """The plugin's layers at SCALE and the fast rate, in one tint."""
    first = TINTS.index(tint_name) * len(cloud.LAYERS)
    return cloud.emitter(name, FAST, None, None, [], first_kind=first, fixed_scale=SCALE)


def one_type(name, tint_name):
    first = len(TINTS) * len(cloud.LAYERS) + (0 if tint_name == "red" else 1)
    return cloud.emitter(name, FAST, None, None, [], layers=(ONE,), first_kind=first,
                         fixed_scale=SCALE)


def obj(system_name, emitters):
    """emitters: (emitter name, z offset in m) in the order they are listed."""
    lines = ["A", "800", "OBJ", "", "TEXTURE", f"PARTICLE_SYSTEM {system_name}.pss", "",
             "POINT_COUNTS 0 0 0 0", "", f"ATTR_LOD 0 {cloud.LOD_M}"]
    lines += [f"EMITTER {em} 0.0 {cloud.EMITTER_Y_M:.1f} {z:.1f}  0.0 0.0 0.0  0"
              for name, z in emitters
              for em in cloud.emitter_names(name, (ONE,) if name.endswith("1") else cloud.LAYERS)]
    return "\n".join(lines + [""])


def write_all(out_dir, version):
    name = f"cu{version}"
    parts = types()
    emitters = (all_layers("e_white", "white") + all_layers("e_red", "red") + all_layers("e_blue", "blue")
                + one_type("e_red1", "red") + one_type("e_blue1", "blue"))
    os.makedirs(out_dir, exist_ok=True)
    cloud.texture().save(os.path.join(out_dir, f"{name}.png"), optimize=True)
    with open(os.path.join(out_dir, f"{name}.pss"), "w", newline="\n") as f:
        f.write(cloud.system(name, parts, emitters))
    objects = {"white": [("e_white", 0.0)], "red": [("e_red", 0.0)], "blue": [("e_blue", 0.0)],
               "red1": [("e_red1", 0.0)], "blue1": [("e_blue1", 0.0)],
               "pair": [("e_red", 0.0), ("e_blue", -PAIR_M)],
               "pairrev": [("e_blue", -PAIR_M), ("e_red", 0.0)],
               "whitepair": [("e_white", 0.0), ("e_white", -PAIR_M)]}
    for kind in ORDER_KINDS:
        with open(os.path.join(out_dir, f"{name}_{kind}.obj"), "w", newline="\n") as f:
            f.write(obj(name, objects[kind]))
    return name


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("out_dir")
    parser.add_argument("--version", type=int, default=1)
    args = parser.parse_args(argv)
    print(f"wrote {write_all(args.out_dir, args.version)} to {args.out_dir}")


if __name__ == "__main__":
    main()
