"""Generate the training markers' objects: xp_gliding/assets/markers/.

Usage:
    python tools/make_marker_objs.py

Writes one ring per radius and strength class (`xp_gliding.engine.markers`),
one column per strength class, and their two small textures. All of it is
authored here, in OBJ8 by hand; the output is committed, and a test checks that
it matches this script. Nothing comes from another plugin's assets.

The meshes (OBJ8 axes: x east, y up, z south; metres):
- Ring: a vertical band around y = 0, seen from both sides. The ring is always
  at the glider's height, so a flat disc or annulus would be edge-on from the
  cockpit: only height can make it visible.
- Column: a thin 8-sided prism going down from y = 0, which is its top. It is
  placed with its top at the top of the lift, and its bottom goes underground
  whatever zi and the terrain are, where the terrain hides it. Faint, to spot a
  thermal from far without hiding anything.

Each face comes twice with opposite winding where it can be seen from both
sides, since two-sided drawing is deprecated in OBJ8. Texture coordinates are
constant over each mesh (one palette cell).

Found by trying in X-Plane 12.4.3 (2026-11-03, notes/phase2.md):
- The palette must be large: at 32x16 pixels X-Plane showed one mixed colour
  (presumably it reduces textures, and a small one ends up as its average), at
  256x128 the right colours. It compresses to almost nothing anyway.
- `ATTR_light_level` with its optional brightness gave a colour that does not
  depend on the sun. Without it the _LIT texture did nothing in daylight, and the
  shaded side of a ring went dark. (`GLOBAL_no_shadow` and `GLOBAL_luminance` went
  away in the same change, so the brightness is the likely cause, not an isolated
  one.) Its dataref is the plugin's own (`xp_gliding/markers/light`), which must
  exist before the object loads: it is registered at plugin start, objects are
  loaded in the flight loop.
- With plain blending the alpha of the palette had no visible effect. With
  `BLEND_GLASS` far columns look somewhat translucent; near ones still look
  almost solid.

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

from xp_gliding.engine.markers import (SIZES_M, STRENGTH_COUNT, column_object,  # noqa: E402
                                       ring_object)

OUT_DIR = os.path.join(REPO, "xp_gliding", "assets", "markers")

RING_HALF_HEIGHT_M = 3.0  # 6 m of band: 2 pixels at 3 km (the column does the long range),
# and not a wall when flying through it (16 m was: ~30 deg of view from 30 m)
RING_SEGMENTS = 36
COLUMN_RADIUS_M = 4.0  # 8 m wide: ~0.15 deg at the 3 km of the markers' range, about 3 pixels
COLUMN_HEIGHT_M = 6000.0  # taller than any zi plus terrain relief we expect
COLUMN_SIDES = 8
LOD_M = 30000.0

LIGHT_DATAREF = "xp_gliding/markers/light"
LIT_BRIGHTNESS_NTS = 8000  # about as bright as the daylight sky around it

# Strength classes, weak to strong: pale, yellow, orange, red. All contrast with
# the blue sky and with the ground below.
COLOURS = ((225, 235, 245), (255, 215, 20), (255, 125, 10), (255, 25, 70))
RING_ALPHA = 230
COLUMN_ALPHA = 90
COLUMN_LIT = 0.45  # the column glows less than the ring
TEXTURE_CELL = 128  # pixels per palette cell; rows: ring, column. See above: not smaller


def palette_st(strength, row):
    """Texture coordinates of the centre of a palette cell (t runs bottom to top)."""
    return (strength + 0.5) / STRENGTH_COUNT, 1.0 - (row + 0.5) / 2.0


def texture(lit):
    """Palette image: columns are strength classes; rows ring (top) and column."""
    size = (STRENGTH_COUNT * TEXTURE_CELL, 2 * TEXTURE_CELL)
    image = Image.new("RGBA", size)
    for s, rgb in enumerate(COLOURS):
        for row in range(2):
            gain = COLUMN_LIT if lit and row == 1 else 1.0
            alpha = 255 if lit else (RING_ALPHA, COLUMN_ALPHA)[row]
            box = (s * TEXTURE_CELL, row * TEXTURE_CELL, (s + 1) * TEXTURE_CELL,
                   (row + 1) * TEXTURE_CELL)
            image.paste((*(round(gain * c) for c in rgb), alpha), box)
    return image


def png_bytes(image):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def prism(radius, y_low, y_high, sides, st, both_faces):
    """Vertical prism side: (vertices, indices). A vertex is (x, y, z, nx, ny, nz, s, t).

    Going round with a growing angle is clockwise seen from above, so an outward
    face seen from outside is clockwise as (bottom next, top next, top this,
    bottom this): OBJ8's front.
    """
    s, t = st
    vertices, indices = [], []
    for sign in ((1.0, -1.0) if both_faces else (1.0,)):
        base = len(vertices)
        for k in range(sides):
            a = 2.0 * math.pi * k / sides
            c, d = math.cos(a), math.sin(a)
            for y in (y_low, y_high):
                vertices.append((radius * c, y, radius * d, sign * c, 0.0, sign * d, s, t))
        for k in range(sides):
            b0, t0 = base + 2 * k, base + 2 * k + 1
            b1, t1 = base + 2 * ((k + 1) % sides), base + 2 * ((k + 1) % sides) + 1
            quad = (b1, t1, t0, b1, t0, b0)
            indices.extend(quad if sign > 0.0 else reversed(quad))
    return vertices, indices


def _number(x):
    text = f"{x:.5f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def obj_text(vertices, indices, name):
    lines = ["I", f"800\t# xp-gliding training marker: {name}", "OBJ", "",
             "TEXTURE markers.png", "TEXTURE_LIT markers_LIT.png", "BLEND_GLASS",
             f"POINT_COUNTS {len(vertices)} 0 0 {len(indices)}", ""]
    for v in vertices:
        lines.append("VT " + " ".join(_number(x) for x in v))
    lines.append("")
    i = 0
    while i + 10 <= len(indices):
        lines.append("IDX10 " + " ".join(str(k) for k in indices[i:i + 10]))
        i += 10
    lines.extend(f"IDX {k}" for k in indices[i:])
    lines.extend(["", f"ATTR_LOD 0 {LOD_M:.0f}", "ATTR_no_shadow",
                  f"ATTR_light_level 0 1 {LIGHT_DATAREF} {LIT_BRIGHTNESS_NTS}",
                  f"TRIS 0 {len(indices)}", ""])
    return "\n".join(lines)


def outputs():
    """{file name: bytes} of everything in the assets folder."""
    files = {"markers.png": png_bytes(texture(lit=False)),
             "markers_LIT.png": png_bytes(texture(lit=True))}
    for strength in range(STRENGTH_COUNT):
        for size_index, radius in enumerate(SIZES_M):
            name = ring_object(size_index, strength)
            mesh = prism(radius, -RING_HALF_HEIGHT_M, RING_HALF_HEIGHT_M, RING_SEGMENTS,
                         palette_st(strength, 0), both_faces=True)
            files[name + ".obj"] = obj_text(*mesh, name).encode("ascii")
        name = column_object(strength)
        mesh = prism(COLUMN_RADIUS_M, -COLUMN_HEIGHT_M, 0.0, COLUMN_SIDES,
                     palette_st(strength, 1), both_faces=False)
        files[name + ".obj"] = obj_text(*mesh, name).encode("ascii")
    return files


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
