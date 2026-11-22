"""Generate the tow rope's segment object: xp_gliding/assets/rope/.

Usage:
    python tools/make_rope_obj.py

One segment of the rope, along the z axis and centred on the origin, as two six-sided prisms
`tow.PIECE_M` long, and its one-colour texture. The adapter draws the rope as one instance of
it per segment of `engine.rope.Rope`, placed at the segment's middle and turned along it
(`adapter/tow.py`), with the per-instance dataref `tow.HALF_DATAREF` at half the segment's
length. Each prism ends at one node, `tow.OVERLAP_M` past it to close the joint at a bend, and
reaches toward the other node: the two overlap in the middle as much as the segment is short,
so the segment is drawn whole at any length from PIECE_M - 2 OVERLAP_M to 2 (PIECE_M -
OVERLAP_M), and nothing sticks out past a joint. The second prism is a hair thicker, so that
where they overlap one face covers the other and they do not fight for the same pixels.
Authored here in OBJ8 by hand; the output is committed, and a test checks that it matches this
script.

Thicker than a real rope (9 mm): seen from the glider's seat at 50 m, a 9 mm line is a third
of a pixel and flickers, so the rope is drawn 25 mm wide, about one pixel there at 1440 lines.
Lit by the sun like any object, so it shades as it turns.

OBJ8 rules: https://developer.x-plane.com/article/obj8-file-format-specification/
License: GPL-3.0-or-later.
"""

import io
import math
import os
import sys

from PIL import Image

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from xp_gliding.adapter.tow import (HALF_DATAREF, HALF_MAX_M, OBJECT_NAME, OVERLAP_M,  # noqa: E402
                                    PIECE_M, ROPE_RADIUS_M)

OUT_DIR = os.path.join(REPO, "xp_gliding", "assets", "rope")
SIDES = 6
OUTER = 1.02  # the second prism's radius over the first's
COLOUR = (236, 226, 196)  # a used white polyester rope, a little cream
TEXTURE_PX = 64  # one colour; small textures are averaged by X-Plane, which here is harmless
LOD_M = 3000.0


def prism(z0, z1, radius, first):
    """(vertices, indices) of one open prism from z0 to z1; indices count from `first`. A vertex
    is (x, y, z, nx, ny, nz, s, t). The sides only: the ends are hidden inside the neighbours."""
    vertices, indices = [], []
    for k in range(SIDES):
        a = 2.0 * math.pi * k / SIDES
        c, s = math.cos(a), math.sin(a)
        for z in (z0, z1):
            vertices.append((radius * c, radius * s, z, c, s, 0.0, 0.5, 0.5))
    for k in range(SIDES):
        n0, f0 = first + 2 * k, first + 2 * k + 1
        n1, f1 = first + 2 * ((k + 1) % SIDES), first + 2 * ((k + 1) % SIDES) + 1
        # Seen from outside, (n0, n1, f1, f0) goes clockwise: OBJ8's front face.
        indices.extend((n0, f1, n1, n0, f0, f1))
    return vertices, indices


def mesh():
    """(vertices, indices, pieces): pieces are (first index, count, z sign) per prism. At the
    dataref's 0 the first prism runs from OVERLAP_M toward -z and the second from -OVERLAP_M
    toward +z; the dataref h moves the first by +h and the second by -h along z, putting their
    outer ends at the segment's nodes, h either side of its middle, OVERLAP_M beyond."""
    va, ia = prism(OVERLAP_M - PIECE_M, OVERLAP_M, ROPE_RADIUS_M, 0)
    vb, ib = prism(-OVERLAP_M, PIECE_M - OVERLAP_M, ROPE_RADIUS_M * OUTER, len(va))
    return va + vb, ia + ib, ((0, len(ia), 1.0), (len(ia), len(ib), -1.0))


def _number(x):
    text = f"{x:.5f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def obj_text(vertices, indices, pieces):
    lines = ["I", "800\t# xp-gliding tow rope segment", "OBJ", "",
             "TEXTURE rope.png", f"POINT_COUNTS {len(vertices)} 0 0 {len(indices)}", ""]
    for v in vertices:
        lines.append("VT " + " ".join(_number(x) for x in v))
    lines.append("")
    i = 0
    while i + 10 <= len(indices):
        lines.append("IDX10 " + " ".join(str(k) for k in indices[i:i + 10]))
        i += 10
    lines.extend(f"IDX {k}" for k in indices[i:])
    lines.extend(["", f"ATTR_LOD 0 {LOD_M:.0f}"])
    for first, count, sign in pieces:
        far = _number(sign * HALF_MAX_M)
        lines.extend(["ANIM_begin",
                      f"ANIM_trans 0 0 0 0 0 {far} 0 {_number(HALF_MAX_M)} {HALF_DATAREF}",
                      f"TRIS {first} {count}",
                      "ANIM_end"])
    lines.append("")
    return "\n".join(lines)


def outputs():
    """{file name: bytes} of everything in the assets folder."""
    image = Image.new("RGB", (TEXTURE_PX, TEXTURE_PX), COLOUR)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return {"rope.png": buffer.getvalue(), OBJECT_NAME + ".obj": obj_text(*mesh()).encode("ascii")}


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    files = outputs()
    for name in os.listdir(OUT_DIR):
        if name not in files:
            os.remove(os.path.join(OUT_DIR, name))
    for name, data in files.items():
        with open(os.path.join(OUT_DIR, name), "wb") as f:
            f.write(data)
    print(f"wrote {len(files)} files to {OUT_DIR}")


if __name__ == "__main__":
    main()
