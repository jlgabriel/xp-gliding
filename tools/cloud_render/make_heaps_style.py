"""Write a Billow cloud style from the cells `render_heaps.py` rendered in Blender.

Usage:
    python tools/cloud_render/make_heaps_style.py CELL_DIR --version billow
    python tools/cloud_render/make_heaps_style.py CELL_DIR --version billow-light [--out DIR]

Puts cell00.png to cell15.png in a 2048 x 2048 atlas of 4 x 4 cells, and writes cumulus.png,
cumulus.pss, cumulus.obj and style.txt to xp_gliding/assets/clouds/<version>/ (or --out).

Each particle draws one whole rendered heap, so a cloud is 34 large particles (the standard style
has 183 small lobes): eight in a tower, sixteen in the body, ten smaller pieces low down.

The shade is lightened before it goes in the atlas: X-Plane lights a particle again, so a
render's full contrast came out grey-blue in the simulator (2026-11-14). Each grey keeps a
fraction of its distance from white, 0.45 for billow and 0.35 for billow-light.

License: GPL-3.0-or-later.
"""

import argparse
import io
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import make_cloud_objs as cloud  # noqa: E402
from make_cloud_objs import Layer, _square  # noqa: E402

CELL_PX = 512
EDGE = 0.06  # alpha fades to nothing over this fraction of a cell's half size, at its border
HEAPS = (0, 12)
PIECES = (12, 4)
WHITE = (1.0, 1.0, 1.0)

# version: (menu name, grey kept, heap size factor, spread factor). The factors scale the first
# layout tried, whose heaps were drawn far smaller than the standard style's clouds; with them a
# cloud is about as wide as a standard one, so it still says how wide its thermal is. The
# frayed cells of 1.1.1 frame a wider fringe round the same visible heap, so the heaps were made
# 1.19 and 1.21 times larger than 1.1's 1.8 and 1.9, to keep its visible width (measured on the
# renders, 2026-11-15).
VERSIONS = {
    "billow": ("Billow (rendered heaps)", 0.45, 1.8 * 1.19, 1.6),
    "billow-light": ("Billow light (lighter, softer edges)", 0.35, 1.9 * 1.21, 1.6),
}


def layers(size_k, spread_k):
    """Drawn in this order, last on top. A heap's bottom is about 0.4 of its size under its
    centre: the centres are raised as the heaps grow, so the bottoms stay some 40-60 m above the
    emitter's origin (itself 59 m above the cloud's base)."""
    def box(frac, y0, y1, size, cx=0.0, cz=0.0):
        lift = 0.4 * size * (size_k - 1.0)
        return _square(frac * spread_k, y0 + lift, y1 + lift, cx * spread_k, cz * spread_k)

    return (
        Layer("tower", 8, HEAPS, 360.0 * size_k, (0.8, 1.2), box(0.25, 300.0, 400.0, 360.0, -60.0, 30.0),
              WHITE, 0.95),
        Layer("body", 16, HEAPS, 460.0 * size_k, (0.75, 1.25), box(0.42, 170.0, 280.0, 460.0), WHITE, 0.95),
        Layer("low", 10, PIECES, 300.0 * size_k, (0.8, 1.2), box(0.62, 110.0, 170.0, 300.0), WHITE, 0.95),
    )


def atlas(cell_dir, keep):
    out = np.zeros((4 * CELL_PX, 4 * CELL_PX, 4))
    ys, xs = np.mgrid[0:CELL_PX, 0:CELL_PX] / (CELL_PX - 1) * 2 - 1
    edge = np.clip((1 - np.maximum(abs(xs), abs(ys))) / EDGE, 0, 1)
    for k in range(16):
        a = np.asarray(Image.open(os.path.join(cell_dir, f"cell{k:02d}.png")).convert("RGBA")) / 255.0
        if a.shape[:2] != (CELL_PX, CELL_PX):
            raise SystemExit(f"cell{k:02d}.png is not {CELL_PX} px")
        rgb = 1.0 - (1.0 - a[..., :3]) * keep
        row, col = divmod(k, 4)
        out[row * CELL_PX:(row + 1) * CELL_PX, col * CELL_PX:(col + 1) * CELL_PX] = \
            np.dstack((rgb, a[..., 3] * edge))
    image = Image.fromarray((out * 255.0 + 0.5).astype(np.uint8), "RGBA")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def write(cell_dir, version, out_dir):
    name, keep, size_k, spread_k = VERSIONS[version]
    lay = layers(size_k, spread_k)
    rate_rows = [(0.0, 0.0), (1.0, 1.0), (cloud.RATE_TOP, cloud.RATE_TOP)]
    pss = cloud.system(cloud.NAME, cloud.particles(lay),
                       cloud.emitter(cloud.NAME, rate_rows, 0, 1, [cloud.RATE_DATAREF, cloud.SCALE_DATAREF],
                                     layers=lay))
    files = {f"{cloud.NAME}.png": atlas(cell_dir, keep),
             f"{cloud.NAME}.pss": pss.encode("ascii"),
             f"{cloud.NAME}.obj": cloud.object_text(cloud.NAME, cloud.NAME, lay).encode("ascii"),
             "style.txt": f"name: {name}\nlicense: GPL-3.0-or-later\n".encode("ascii")}
    os.makedirs(out_dir, exist_ok=True)
    for file, data in files.items():
        with open(os.path.join(out_dir, file), "wb") as f:
            f.write(data)
    print(f"wrote {name} ({sum(l.count for l in lay)} particles) to {out_dir}")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("cell_dir")
    parser.add_argument("--version", choices=sorted(VERSIONS), required=True)
    parser.add_argument("--out", help="default: xp_gliding/assets/clouds/<version>")
    args = parser.parse_args(argv)
    out = args.out or os.path.join(cloud.REPO, "xp_gliding", "assets", "clouds", args.version)
    write(args.cell_dir, args.version, out)


if __name__ == "__main__":
    main()
