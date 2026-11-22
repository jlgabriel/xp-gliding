"""Generate the tow rope's segment object: xp_gliding/assets/rope/.

Usage:
    python tools/make_rope_obj.py

One short six-sided prism along the z axis, centred on the origin, and its one-colour texture.
The adapter draws the rope as one instance of it per segment of `engine.rope.Rope`, placed at
the segment's middle and turned along it (`adapter/tow.py`). It is a hair longer than a
segment, so neighbours overlap where the rope bends or stretches and no gap shows. Authored
here in OBJ8 by hand; the output is committed, and a test checks that it matches this script.

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

from xp_gliding.adapter.tow import OBJECT_NAME, ROPE_LENGTH_M, SEGMENTS  # noqa: E402

OUT_DIR = os.path.join(REPO, "xp_gliding", "assets", "rope")
RADIUS_M = 0.0125
SIDES = 6
# The prism's length over a segment's rest length. At 1.12 the ends that stuck out past each
# joint showed as little sticks along the rope (Juan Luis, 2026-11-21: "can we get rid of
# the sticks?"); 1.03 is 2-3 cm, enough to close a joint at the bends the rope allows.
OVERLAP = 1.03
COLOUR = (236, 226, 196)  # a used white polyester rope, a little cream
TEXTURE_PX = 64  # one colour; small textures are averaged by X-Plane, which here is harmless
LOD_M = 3000.0


def mesh():
    """(vertices, indices); a vertex is (x, y, z, nx, ny, nz, s, t). The sides only: the ends
    are hidden inside the neighbouring segments."""
    half = 0.5 * OVERLAP * ROPE_LENGTH_M / SEGMENTS
    vertices, indices = [], []
    for k in range(SIDES):
        a = 2.0 * math.pi * k / SIDES
        c, s = math.cos(a), math.sin(a)
        for z in (-half, half):
            vertices.append((RADIUS_M * c, RADIUS_M * s, z, c, s, 0.0, 0.5, 0.5))
    for k in range(SIDES):
        n0, f0 = 2 * k, 2 * k + 1
        n1, f1 = 2 * ((k + 1) % SIDES), 2 * ((k + 1) % SIDES) + 1
        # Seen from outside, (n0, n1, f1, f0) goes clockwise: OBJ8's front face.
        indices.extend((n0, f1, n1, n0, f0, f1))
    return vertices, indices


def _number(x):
    text = f"{x:.5f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def obj_text(vertices, indices):
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
    lines.extend(["", f"ATTR_LOD 0 {LOD_M:.0f}", f"TRIS 0 {len(indices)}", ""])
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
