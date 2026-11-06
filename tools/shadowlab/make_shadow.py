"""Generate the shadow lab's objects: a dark shape to lay on the ground, and a post to find it.

Usage:
    python tools/shadowlab/make_shadow.py OUT_DIR [--version 1] [--size 1000] [--opacity 0.3]

Writes, all authored here:
- shadowN_soft.obj: the candidate. One draped quad `size` metres across, whose texture is black
  with an alpha that fades to nothing at the edge, `opacity` at the centre.
- shadowN_strong.obj: the same quad, opaque-ish red. Only to see beyond doubt where the draped
  triangles are in a screenshot.
- shadowN_grid.obj: the soft shape on a quad split into 8 x 8, in case the number of triangles
  in the object changes how it fits the ground or what it costs.
- postN.obj: a tall thin red prism, not draped, standing on the instance's position. A control:
  it shows that the instance is where it should be whatever the draped part does.

Controls added when a draped instance drew nothing, to rule out the way the object is written:
- shadowN_flat.obj: the strong quad without ATTR_draped, so a mesh, texture and winding check.
- shadowN_mirror.obj: the strong quad, its lines in the order of Laminar's own `gnd_grass_12x30.obj`,
  an object made only of draped triangles (no ATTR_LOD_draped, ATTR_LOD 0 3000).
- shadowN_tiny.obj: the same at 30 m across, about the size of Laminar's.
- shadowN_mixed.obj: post and strong quad in one object, in the order of Laminar's grandstands,
  whose LOD has both kinds of triangle.

For the second idea, geometry in the sky that casts X-Plane's own shadows:
- skyN_solid.obj: a grey disc, seen from both sides, cut out with ATTR_no_blend. A control.
- skyN_hidden.obj: the same with almost no alpha and ATTR_shadow_blend, which should draw next to
  nothing and still cast a shadow.

The version changes between tries because X-Plane may keep a loaded object by its path, so a new
look can be loaded without restarting the simulator.

OBJ8 rules: https://developer.x-plane.com/article/obj8-file-format-specification/ . The header
follows Laminar's own objects with draped parts (TEXTURE_DRAPED, ATTR_layer_group_draped,
ATTR_LOD_draped in the header; ATTR_draped before the draped TRIS).

Measurement tool, not part of the plugin. License: GPL-3.0-or-later.
"""

import argparse
import math
import os

from PIL import Image

TEXTURE_SIZE = 512  # a small texture may reach the screen as its average colour (notes/phase2.md)
LOD_M = 40000  # X-Plane divides this: LOD_bias_rat was 5 here, so 40 km drew to about 8 km
# Above roads, which are above everything on an airport.
LAYER = "ATTR_layer_group_draped roads 5"
POST_HEIGHT_M = 1500.0
POST_RADIUS_M = 8.0
RED = (255, 30, 30)
STRONG_ALPHA = 0.85
GREY = (140, 140, 140)
HIDDEN_ALPHA = 0.03  # of the disc that should cast a shadow without being seen


def smoothstep(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3.0 - 2.0 * x)


def round_texture(rgb, opacity, solid_to=0.45):
    """A disc that fills the image: alpha is `opacity` up to solid_to of the radius, then fades."""
    n = TEXTURE_SIZE
    image = Image.new("RGBA", (n, n))
    pixels = image.load()
    for j in range(n):
        for i in range(n):
            r = math.hypot((i + 0.5) / n * 2.0 - 1.0, (j + 0.5) / n * 2.0 - 1.0)
            fade = 1.0 - smoothstep((r - solid_to) / (1.0 - solid_to))
            pixels[i, j] = (*rgb, round(255 * opacity * fade))
    return image


def flat_texture(rgb):
    return Image.new("RGBA", (64, 64), (*rgb, 255))


def number(x):
    text = f"{x:.5f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


def grid_mesh(size, cells):
    """A horizontal square centred on the origin: (vertices, indices). Clockwise from above."""
    half = size / 2.0
    vertices, indices = [], []
    for j in range(cells + 1):  # north to south
        for i in range(cells + 1):  # west to east
            s, t = i / cells, 1.0 - j / cells
            vertices.append((-half + size * s, 0.0, -half + size * j / cells, 0.0, 1.0, 0.0, s, t))
    for j in range(cells):
        for i in range(cells):
            nw, ne = j * (cells + 1) + i, j * (cells + 1) + i + 1
            sw, se = nw + cells + 1, ne + cells + 1
            indices.extend((ne, se, sw, sw, nw, ne))
    return vertices, indices


def post_mesh():
    """Four outward faces, clockwise as seen from outside."""
    r, top = POST_RADIUS_M, POST_HEIGHT_M
    corners = ((r, -r), (r, r), (-r, r), (-r, -r))
    vertices, indices = [], []
    for k in range(4):
        (x0, z0), (x1, z1) = corners[k], corners[(k + 1) % 4]
        nx, nz = (x0 + x1) / (2.0 * r), (z0 + z1) / (2.0 * r)
        base = len(vertices)
        vertices.extend(((x0, 0.0, z0, nx, 0.0, nz, 0.5, 0.5), (x0, top, z0, nx, 0.0, nz, 0.5, 0.5),
                         (x1, top, z1, nx, 0.0, nz, 0.5, 0.5), (x1, 0.0, z1, nx, 0.0, nz, 0.5, 0.5)))
        indices.extend((base, base + 1, base + 2, base + 2, base + 3, base))
    return vertices, indices


def two_sided(mesh):
    """Every triangle again with the opposite winding and normal."""
    vertices, indices = mesh
    n = len(vertices)
    flipped = [(x, y, z, -nx, -ny, -nz, s, t) for x, y, z, nx, ny, nz, s, t in vertices]
    return vertices + flipped, indices + [k + n for k in reversed(indices)]


def sky_text(vertices, indices, texture, mode, lod_m):
    lines = ["I", "800\t# xp-gliding shadow lab", "OBJ", "", f"TEXTURE {texture}",
             f"POINT_COUNTS {len(vertices)} 0 0 {len(indices)}", ""]
    lines.extend("VT " + " ".join(number(x) for x in v) for v in vertices)
    lines.extend(f"IDX {k}" for k in indices)
    lines.extend(("", f"ATTR_LOD 0 {lod_m:.0f}", mode, f"TRIS 0 {len(indices)}", ""))
    return "\n".join(lines)


def mirror_text(vertices, indices, texture):
    """In the order of Laminar's `1000 autogen/EU/industrial/gnd_grass_12x30.obj`."""
    lines = ["I", "800\t# xp-gliding shadow lab", "OBJ", "", f"TEXTURE {texture}", f"TEXTURE_DRAPED {texture}", "",
             f"POINT_COUNTS {len(vertices)} 0 0 {len(indices)}"]
    lines.extend("VT " + " ".join(number(x) for x in v) for v in vertices)
    lines.extend(f"IDX {k}" for k in indices)
    lines.extend(("", "ATTR_LOD 0 3000", "ATTR_draped", "ATTR_layer_group_draped roads -2",
                  f"TRIS 0 {len(indices)}", ""))
    return "\n".join(lines)


def mixed_text(post, quad, post_texture, draped_texture):
    """In the order of Laminar's grandstands: normal triangles, then draped ones in the same LOD."""
    p_vertices, p_indices = post
    q_vertices, q_indices = quad
    shift = len(p_vertices)
    vertices = p_vertices + q_vertices
    indices = p_indices + [k + shift for k in q_indices]
    lines = ["I", "800\t# xp-gliding shadow lab", "OBJ", "", f"TEXTURE {post_texture}",
             f"TEXTURE_DRAPED {draped_texture}", "ATTR_layer_group_draped beaches 4",
             f"POINT_COUNTS {len(vertices)} 0 0 {len(indices)}", ""]
    lines.extend("VT " + " ".join(number(x) for x in v) for v in vertices)
    lines.extend(f"IDX {k}" for k in indices)
    lines.extend(("", "ATTR_LOD 0 8000", f"TRIS 0 {len(p_indices)}", "ATTR_draped",
                  f"TRIS {len(p_indices)} {len(q_indices)}", ""))
    return "\n".join(lines)


def obj_text(vertices, indices, texture, draped):
    lines = ["I", "800\t# xp-gliding shadow lab", "OBJ", "", f"TEXTURE {texture}"]
    if draped:
        lines.extend((f"TEXTURE_DRAPED {texture}", LAYER, f"ATTR_LOD_draped {LOD_M}"))
    lines.extend((f"POINT_COUNTS {len(vertices)} 0 0 {len(indices)}", ""))
    lines.extend("VT " + " ".join(number(x) for x in v) for v in vertices)
    lines.append("")
    lines.extend(f"IDX {k}" for k in indices)
    lines.extend(("", f"ATTR_LOD 0 {LOD_M}"))
    if draped:
        lines.append("ATTR_draped")
    else:
        lines.append("ATTR_no_shadow")
    lines.extend((f"TRIS 0 {len(indices)}", ""))
    return "\n".join(lines)


def write_all(folder, version, size_m, opacity, sky_lod_m=LOD_M, hidden_alpha=HIDDEN_ALPHA, hidden_mode=None):
    os.makedirs(folder, exist_ok=True)
    round_texture((0, 0, 0), opacity).save(os.path.join(folder, f"shadow{version}_soft.png"))
    round_texture(RED, STRONG_ALPHA, solid_to=0.9).save(os.path.join(folder, f"shadow{version}_strong.png"))
    flat_texture(RED).save(os.path.join(folder, f"post{version}.png"))
    round_texture(GREY, 1.0, solid_to=0.95).save(os.path.join(folder, f"sky{version}_solid.png"))
    round_texture(GREY, hidden_alpha, solid_to=0.95).save(os.path.join(folder, f"sky{version}_hidden.png"))
    objects = {
        f"shadow{version}_soft": (*grid_mesh(size_m, 1), f"shadow{version}_soft.png", True),
        f"shadow{version}_strong": (*grid_mesh(size_m, 1), f"shadow{version}_strong.png", True),
        f"shadow{version}_grid": (*grid_mesh(size_m, 8), f"shadow{version}_soft.png", True),
        f"post{version}": (*post_mesh(), f"post{version}.png", False),
    }
    for name, (vertices, indices, texture, draped) in objects.items():
        with open(os.path.join(folder, name + ".obj"), "w", encoding="ascii", newline="\n") as f:
            f.write(obj_text(vertices, indices, texture, draped))
    strong = f"shadow{version}_strong.png"
    extras = {
        f"shadow{version}_flat": obj_text(*grid_mesh(size_m, 1), strong, False),
        f"shadow{version}_mirror": mirror_text(*grid_mesh(size_m, 1), strong),
        f"shadow{version}_tiny": mirror_text(*grid_mesh(30.0, 1), strong),
        f"sky{version}_solid": sky_text(*two_sided(grid_mesh(size_m, 1)), f"sky{version}_solid.png",
                                        "ATTR_no_blend 0.5", sky_lod_m),
        f"sky{version}_hidden": sky_text(*two_sided(grid_mesh(size_m, 1)), f"sky{version}_hidden.png",
                                         (hidden_mode or f"ATTR_shadow_blend {hidden_alpha / 2.0:.3f}").replace(",", "\n"), sky_lod_m),
        f"shadow{version}_mixed": mixed_text(post_mesh(), grid_mesh(size_m, 1), f"post{version}.png", strong),
    }
    for name, text in extras.items():
        with open(os.path.join(folder, name + ".obj"), "w", encoding="ascii", newline="\n") as f:
            f.write(text)
    return sorted(objects) + sorted(extras)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("out_dir")
    parser.add_argument("--version", type=int, default=1)
    parser.add_argument("--size", type=float, default=1000.0, help="across, metres")
    parser.add_argument("--opacity", type=float, default=0.3, help="at the centre, 0-1")
    parser.add_argument("--sky-lod", type=float, default=LOD_M, help="ATTR_LOD of the sky discs, metres")
    parser.add_argument("--hidden-alpha", type=float, default=HIDDEN_ALPHA)
    parser.add_argument("--hidden-mode", help="the disc's attributes, comma separated")
    args = parser.parse_args()
    print("wrote", write_all(args.out_dir, args.version, args.size, args.opacity, args.sky_lod, args.hidden_alpha, args.hidden_mode), "in", args.out_dir)


if __name__ == "__main__":
    main()
