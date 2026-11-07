"""Generate the cloud lab's objects for the question of draw order: which cloud is drawn on top?

Usage:
    python tools/cloudlab/make_order.py OUT_DIR [--version 1]

Writes cuN_<kind>.obj, cuN.pss and cuN.png for the kinds in ORDER_KINDS, which the lab
(`PI_xpg_cloudlab.py`) loads like its other objects. Every emitter here runs at the fast rate
of the plugin's cumulus, with no dataref, so a cloud fills in about 9 s and stays dense:

- white: the plugin's cumulus, three particle types (base, body, top), as drawn in flight.
- red, blue: the same shape with their own three particle types, tinted, so that which one
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
# Particle types, in this order in the file: (name, first cell, cells, size, tint, alpha).
TYPES = []
for _tint_name, _tints in (("white", (cloud.BASE_TINT, cloud.BODY_TINT, cloud.TOP_TINT)),
                           ("red", (RED, RED, RED)), ("blue", (BLUE, BLUE, BLUE))):
    TYPES += [(f"{_tint_name}_base", 0, cloud.CELLS, cloud.BASE_SIZE, _tints[0], cloud.ALPHA_BASE),
              (f"{_tint_name}_body", cloud.CELLS, cloud.CELLS, cloud.BODY_SIZE, _tints[1], cloud.ALPHA_BODY),
              (f"{_tint_name}_top", 2 * cloud.CELLS, 2 * cloud.CELLS, cloud.TOP_SIZE, _tints[2], cloud.ALPHA_TOP)]
INDEX = {t[0]: i for i, t in enumerate(TYPES)}
ORDER_KINDS = ("white", "red", "blue", "red1", "blue1", "pair", "pairrev", "whitepair")


def sub(type_name, count, half_width, dy):
    """One sub-emitter at the fast rate, its shape at SCALE."""
    rate = count / cloud.TTL_S * cloud.RATE_TOP
    out = ["SUB_EMITTER", f" PARTICLE_TYPE {INDEX[type_name]}"]
    out += cloud.constant("EMIT_RATE", rate, rate)
    for name in ("INITIAL_SPEED", "ROTATION_SPEED", "INITIAL_HEADING", "INITIAL_PITCH"):
        out += cloud.constant(name, 0.0, 0.0)
    out += cloud.constant("DX", -half_width * SCALE, half_width * SCALE)
    out += cloud.constant("DY", dy[0] * SCALE, dy[1] * SCALE)
    out += cloud.constant("DZ", -half_width * SCALE, half_width * SCALE)
    for name in ("DLON", "DLAT", "DRAD"):
        out += cloud.constant(name, 0.0, 0.0)
    out += cloud.constant("INITIAL_ROTATION", -12.0, 12.0)
    out += cloud.constant("INITIAL_SIZE", SCALE, SCALE)
    out += cloud.constant("INITIAL_ALPHA", 1.0, 1.0)
    low = cloud.TTL_S * (1.0 - cloud.TTL_SPREAD)
    out += cloud.constant("TIME_TO_LIVE", low, cloud.TTL_S * (1.0 + cloud.TTL_SPREAD))
    out += [" HIDE_UNTIL_COLLIDE 0", " RANDOMIZE_ROLL 0", " THINNING 0.000000", "END_SUB_EMITTER"]
    return out


def three_types(name, tint_name):
    w = cloud.HALF_WIDTH_M
    out = ["EMITTER", f" NAME {name}", " EMIT_MODE STREAM"]
    out += sub(f"{tint_name}_base", cloud.BASE_N, w * cloud.BASE_WIDTH, cloud.BASE_DY)
    out += sub(f"{tint_name}_body", cloud.BODY_N, w * cloud.BODY_WIDTH, cloud.BODY_DY)
    out += sub(f"{tint_name}_top", cloud.TOP_N, w * cloud.TOP_WIDTH, cloud.TOP_DY)
    return out + ["DATAREFS 0", "END_EMITTER"]


def one_type(name, tint_name):
    count = cloud.BASE_N + cloud.BODY_N + cloud.TOP_N
    out = ["EMITTER", f" NAME {name}", " EMIT_MODE STREAM"]
    out += sub(f"{tint_name}_body", count, cloud.HALF_WIDTH_M * cloud.BODY_WIDTH, (0.0, cloud.TOP_DY[1]))
    return out + ["DATAREFS 0", "END_EMITTER"]


def obj(system_name, emitters):
    """emitters: (emitter name, z offset in m) in the order they are listed."""
    lines = ["A", "800", "OBJ", "", "TEXTURE", f"PARTICLE_SYSTEM {system_name}.pss", "",
             "POINT_COUNTS 0 0 0 0", "", f"ATTR_LOD 0 {cloud.LOD_M}"]
    lines += [f"EMITTER {name} 0.0 {cloud.EMITTER_Y_M:.1f} {z:.1f}  0.0 0.0 0.0  0" for name, z in emitters]
    return "\n".join(lines + [""])


def write_all(out_dir, version):
    name = f"cu{version}"
    parts = []
    for t in TYPES:
        parts += cloud.particle(t[0], t[1], t[2], t[3], t[4], t[5], 16384)
    emitters = (three_types("e_white", "white") + three_types("e_red", "red") + three_types("e_blue", "blue")
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
