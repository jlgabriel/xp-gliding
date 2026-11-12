"""Generate the cumulus object, particle system and texture: xp_gliding/assets/clouds/.

Usage:
    python tools/make_cloud_objs.py

All of it is authored here; nothing comes from another plugin's or simulator's assets. The
output is committed, and a test checks that it matches this script.

The cloud is a few layers of particles over an object with no geometry (see `LAYERS`): shaded
lobes of several sizes for the body and its bottom, small bright lobes on top and small puffs
at the edges. Particles have no speed of their own
and no gravity. With `DRAG` 1 XP12's wind carries them, and in calm air they stay where they
were emitted: the emitter's random offsets (DX, DY, DZ) are the cloud's shape, and rate x
life is the number alive. Two values come per instance, as datarefs of the instance
(`xp_gliding.adapter.clouds`), and drive the emitter's tables:
- rate: 0 stops feeding, 1 is the steady cloud, up to `RATE_TOP` fills it fast.
- scale: 1 is the object's size. It scales the offsets and the particles' size.

The texture bakes the light: billboards always face the camera, so each lobe is lit from
above and shaded below and where one bulge hides another, and initial rotation stays small
to keep that. Each layer can have its own tint. Puffs fade out before the edge of their cell: a puff cut by the cell shows as a
straight line from close up (seen flying through the first version).

The look follows X-Plane 12's own cumulus, by eye (notes/cloud-looks.md): soft, uneven
edges and density that varies through the cloud. Its flatter, greyer base and wisps were
tried as layers of their own and dropped: they showed as a flat band under the body.

Found by trying in X-Plane 12.4.3 under Vulkan (notes/phase2.md, `tools/cloudlab/`):
- An emitter's table can have a dataref of the instance as its slot, and it follows the
  value set with XPLMInstanceSetPosition, per instance, in flight.
- Destroying an instance removes its particles at once.
- It emits when out of view, and shows from 35 km with `ATTR_LOD 0 40000`.
- `MAX_PARTICLES` limits each emitter, not all the emitters of a type together.
- The dataref in a slot must exist when the object loads: the plugin registers it at
  its start, objects load in the flight loop.

The particle system file format has no public specification; the OBJ8 directives are in
https://developer.x-plane.com/article/obj8-file-format-specification/ and the concepts in
https://developer.x-plane.com/article/x-plane-11-particle-system/
License: GPL-3.0-or-later.
"""

import io
import os

import numpy as np
from PIL import Image

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(REPO, "xp_gliding", "assets", "clouds")

NAME = "cumulus"
RATE_DATAREF = "xp_gliding/clouds/rate"
SCALE_DATAREF = "xp_gliding/clouds/scale"

CELLS = 4
CELL_PX = 256
SEED = 20261111
LOD_M = 40000

# Cells of the atlas, by row from the top of the image: (first cell, count).
BASE_CELLS = (0, 4)   # wide, flat-bottomed puffs
LOBE_CELLS = (4, 8)   # shaded cauliflower lobes, two rows
SMALL_CELLS = (12, 2)  # small lobes for edges and tops
WISP_CELLS = (14, 2)  # torn wisps

# Particle life (s): long, so a cloud needs few new ones. CloudParams.ttl_s is the longest.
TTL_S = 180.0
TTL_SPREAD = 0.2
# How fast a particle takes on the speed of the air around it, so XP12's wind carries it.
DRAG = 1.0
# The cloud's half width at scale 1 (m), CLOUD_HALF_WIDTH_M in the engine. Layers' widths are
# fractions of it.
HALF_WIDTH_M = 500.0


class Layer:
    """Particles of one look in one part of the cloud.

    count: alive at rate 1. cells: (first, count) of the atlas. size_m: billboard size, times
    a random factor in `spread`. box: (x low, x high, y low, y high, z low, z high) in m at
    scale 1, y above the cloud's base. tint: RGB, alpha: the most opaque it gets.
    """

    __slots__ = ("name", "count", "cells", "size_m", "spread", "box", "tint", "alpha")

    def __init__(self, name, count, cells, size_m, spread, box, tint, alpha):
        self.name, self.count, self.cells, self.size_m = name, count, cells, size_m
        self.spread, self.box, self.tint, self.alpha = spread, box, tint, alpha


def _square(frac, y0, y1, cx=0.0, cz=0.0):
    """A box `frac` of the half width each way around (cx, cz), from y0 to y1."""
    w = HALF_WIDTH_M * frac
    return (cx - w, cx + w, y0, y1, cz - w, cz + w)


# Shape at scale 1. The body is a few towers off the centre, so a cloud is uneven and differs
# with the side it is seen from; the plugin turns each cloud by its own heading.
# The order is the order they are drawn in, last on top: X-Plane does not sort the emitters of
# one object by distance (notes/phase4.md).
LAYERS = (
    Layer("tower_a", 40, LOBE_CELLS, 270.0, (0.6, 1.4), _square(0.36, 180.0, 400.0, -120.0, 40.0),
          (1.00, 1.00, 1.00), 0.92),
    Layer("tower_b", 30, LOBE_CELLS, 240.0, (0.6, 1.4), _square(0.30, 160.0, 340.0, 160.0, 90.0),
          (1.00, 1.00, 1.00), 0.92),
    Layer("tower_c", 20, LOBE_CELLS, 220.0, (0.6, 1.4), _square(0.26, 150.0, 300.0, 50.0, -190.0),
          (1.00, 1.00, 1.00), 0.92),
    Layer("top", 25, SMALL_CELLS, 160.0, (0.6, 1.4), _square(0.30, 380.0, 480.0, -100.0, 30.0),
          (1.00, 1.00, 1.00), 0.88),
    Layer("low", 75, LOBE_CELLS, 290.0, (0.6, 1.4), _square(0.78, 40.0, 200.0),
          (1.00, 1.00, 1.00), 0.95),
    Layer("edge", 50, SMALL_CELLS, 120.0, (0.6, 1.4), _square(0.70, 40.0, 240.0),
          (1.00, 1.00, 1.00), 0.85),
)
# No flat base layer and no wisps since v14: seen edge on near the base's height, their thin
# layer of wide puffs showed as a flat band sticking out under the body, grey or white, and
# Juan Luis did not want it (notes/cloud-looks.md). The low lobes make the bottom. Their cells
# stay in the atlas, unused.
BY_NAME = {layer.name: layer for layer in LAYERS}
# Sub-emitters per emitter. Eight in one emitter crashed X-Plane 12.4.3 (heap corruption) a few
# seconds after the first cloud was placed (notes/cloud-looks.md); three were always fine.
SUBS_PER_EMITTER = 3

MAX_PARTICLES = 2048  # per emitter: far above what rate x life can reach
LIGHT = 1.7  # X-Plane's ambient and diffuse for a particle. 1.2 and 1.35 too dark to Juan Luis; he
# preferred 1.7 to 2.1 (notes/cloud-looks.md)
RATE_TOP = 20.0  # CloudParams.prewarm: fills a cloud in TTL_S / RATE_TOP
SCALE_TOP = 2.0
# The bottom of a base puff's image (from its centre, as a fraction of its half size).
BASE_BOTTOM = 0.42
# Raise the emitter so the bottom of the cloud, not the centre of the lowest puffs, is at the
# height the instance is placed. Kept at the height the base puffs needed (59 m): the lowest low
# lobes now reach about as far down.
EMITTER_Y_M = 59


# --- texture -------------------------------------------------------------------------

def noise2(rng, size, octaves=5, base=4, aspect=1.0, gain=0.55):
    """Value noise in [0, 1]. aspect > 1 stretches it along x (fibres)."""
    total = np.zeros((size, size))
    amp, norm = 1.0, 0.0
    ys, xs = np.mgrid[0:size, 0:size] / size
    for o in range(octaves):
        ny = base * 2 ** o
        nx = max(1, int(round(ny / aspect)))
        grid = rng.random((ny + 2, nx + 2))
        gx, gy = xs * nx, ys * ny
        ix, iy = gx.astype(int), gy.astype(int)
        fx, fy = gx - ix, gy - iy
        fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
        top = grid[iy, ix] * (1 - fx) + grid[iy, ix + 1] * fx
        bottom = grid[iy + 1, ix] * (1 - fx) + grid[iy + 1, ix + 1] * fx
        total += amp * (top * (1 - fy) + bottom * fy)
        norm += amp
        amp *= gain
    return total / norm


def _smooth(x):
    x = np.clip(x, 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def _grid(size):
    """x right, y up, both in [-1, 1]."""
    ys, xs = np.mgrid[0:size, 0:size] / (size - 1) * 2.0 - 1.0
    return xs, -ys


def _border(xs, ys):
    """1 inside, 0 at the cell's edge, so no puff is cut by its cell."""
    b = np.clip((1.0 - np.maximum(np.abs(xs), np.abs(ys))) / 0.10, 0.0, 1.0)
    return _smooth(b)


# Light from above and a little to the side, in the image (x right, y up).
LIGHT_2D = (-0.30, 0.95)


def blobs(rng, size, n, reach, low, high, sigma):
    """Density of a cauliflower in [0, 1]: `n` soft bulges, wide low down and narrower up,
    each with smaller bulges on its upper side."""
    xs, ys = _grid(size)
    d = np.zeros((size, size))

    def add(cx, cy, s, w):
        nonlocal d
        d = np.maximum(d, w * np.exp(-((xs - cx) ** 2 + (ys - cy) ** 2) / (2.0 * s * s)))

    for _ in range(n):
        f = rng.random()
        cy = low + (high - low) * f
        r = reach * (1.0 - 0.5 * f)
        cx = rng.uniform(-r, r)
        s = rng.uniform(*sigma) * (1.0 - 0.3 * f)
        add(cx, cy, s, 1.0)
        add(cx * 0.5, (cy + low) * 0.5, s * 1.3, 0.9)  # tie it to the lobe's root
        for _ in range(int(rng.integers(2, 4))):
            a = np.radians(90.0 + rng.uniform(-110.0, 110.0))
            k = rng.uniform(0.9, 1.4) * s
            add(cx + k * np.cos(a), cy + k * np.sin(a), s * rng.uniform(0.42, 0.62), 0.68)
    return d


def _shift(a, dx, dy):
    """a moved by whole pixels, dx right and dy up, zeros coming in."""
    out = np.zeros_like(a)
    h, w = a.shape
    sy, sx = -dy, dx  # image rows grow downward
    ys0, ys1 = max(0, sy), min(h, h + sy)
    xs0, xs1 = max(0, sx), min(w, w + sx)
    out[ys0:ys1, xs0:xs1] = a[ys0 - sy:ys1 - sy, xs0 - sx:xs1 - sx]
    return out


def lit(density, size, steps=12, reach=0.30, absorb=2.2):
    """How much light reaches each pixel: the density between it and the light, summed."""
    total = np.zeros_like(density)
    for k in range(1, steps + 1):
        dist = reach * size / 2.0 * k / steps
        total += _shift(density, int(round(-LIGHT_2D[0] * dist)), int(round(-LIGHT_2D[1] * dist)))
    return np.exp(-absorb * total / steps)


def billow(rng, size, base=4, octaves=5):
    """Puffy noise: folded value noise, bright rounded cells with darker creases."""
    n = noise2(rng, size, octaves=octaves, base=base)
    return 1.0 - np.abs(2.0 * n - 1.0)


def cloud_cell(rng, size, density, edge, soft, belly):
    """RGBA from a density field in [0, 1]: lit from above, darker below, and an edge that
    fades out slowly over the density's outer tail, so no puff shows as a disc (a firm edge
    made the cloud's outline a chain of round bubbles, notes/cloud-looks.md)."""
    xs, ys = _grid(size)
    bill = billow(rng, size, base=4)
    fine = noise2(rng, size, octaves=4, base=16)
    d = density * (0.80 + 0.35 * bill)
    alpha = _smooth((d - edge - 0.25 * (fine - 0.5)) / soft) * (0.92 + 0.08 * fine)
    lum = 0.92 + 0.08 * lit(d, size)
    lum = lum * (1.0 - belly * _smooth((0.1 - ys) / 0.9)) * (0.95 + 0.10 * (bill - 0.5))
    return _rgba(lum, alpha * _border(xs, ys), blue=0.04)


def lobe(rng, size):
    """A cauliflower lobe: bulges of several sizes, lit from above, a soft uneven edge."""
    d = blobs(rng, size, int(rng.integers(4, 7)), 0.40, -0.36, 0.22, (0.20, 0.28))
    return cloud_cell(rng, size, d, 0.10, 0.60, 0.06)


def small(rng, size):
    """A small round lobe for edges and tops: a few bulges."""
    d = blobs(rng, size, int(rng.integers(3, 5)), 0.34, -0.28, 0.18, (0.19, 0.26))
    return cloud_cell(rng, size, d, 0.10, 0.60, 0.05)


def base(rng, size):
    """A wide, soft grey oval, densest in its lower half: the cloud's base.

    A flat, hard bottom drawn in the image looked right from the side but broke into
    horizontal stripes seen from below (notes/cloud-looks.md); the base is flat because its
    puffs are emitted in a thin layer, and each puff stays soft all round.
    """
    xs, ys = _grid(size)
    nz = noise2(rng, size, octaves=5, base=4)
    fine = noise2(rng, size, octaves=4, base=12, aspect=2.0)
    centre = -BASE_BOTTOM + 0.30
    r = np.hypot(xs / 0.88, (ys - centre) / (0.36 + 0.10 * (nz - 0.5)))
    alpha = _smooth((1.0 - r) / 0.55) * (0.85 + 0.15 * nz) * (0.90 + 0.20 * (fine - 0.5))
    # Even and darker below, lighter higher up.
    lum = 0.84 + 0.14 * _smooth((ys - centre + 0.3) / 0.6) + 0.04 * (fine - 0.5)
    return _rgba(lum, alpha * _border(xs, ys), blue=0.05)


def wisp(rng, size):
    """Torn fibres, stretched sideways: loose edges around the base."""
    xs, ys = _grid(size)
    fibres = noise2(rng, size, octaves=6, base=5, aspect=4.0, gain=0.6)
    blob = noise2(rng, size, octaves=3, base=3)
    env = _smooth((1.0 - np.hypot(xs / 0.9, ys / 0.5)) / 0.6)
    alpha = _smooth((fibres + 0.35 * (blob - 0.5) - 0.42) / 0.20) * env * 0.75
    lum = 0.70 + 0.14 * _smooth((ys + 0.3) / 0.6) + 0.08 * (fibres - 0.5)
    return _rgba(lum, alpha * _border(xs, ys), blue=0.04)

def _rgba(lum, alpha, blue):
    rgb = np.stack((lum, lum * (1.0 + 0.4 * blue), lum * (1.0 + blue)), axis=-1)
    return np.dstack((np.clip(rgb, 0.0, 1.0), np.clip(alpha, 0.0, 1.0)))


def texture():
    """Atlas of puffs: cell k is at row k // CELLS, column k % CELLS, from the top left."""
    rng = np.random.default_rng(SEED)
    makers = {}
    for kind, (first, count) in (("base", BASE_CELLS), ("lobe", LOBE_CELLS),
                                 ("small", SMALL_CELLS), ("wisp", WISP_CELLS)):
        for k in range(first, first + count):
            makers[k] = kind
    draw = {"base": base, "lobe": lobe, "small": small, "wisp": wisp}
    atlas = np.zeros((CELL_PX * CELLS, CELL_PX * CELLS, 4))
    for k in range(CELLS * CELLS):
        row, col = divmod(k, CELLS)
        atlas[row * CELL_PX:(row + 1) * CELL_PX, col * CELL_PX:(col + 1) * CELL_PX] = \
            draw[makers[k]](rng, CELL_PX)
    return Image.fromarray((atlas * 255.0 + 0.5).astype(np.uint8), "RGBA")


# --- particle system -----------------------------------------------------------------

def table(name, rows, slot=None):
    out = [name]
    if slot is not None:
        out.append(f"SLOT {slot}")
    out.append("INTERP_MODE LINEAR")
    out.extend("\t" + "\t".join(f"{v:.6f}" for v in row) for row in rows)
    out.append("END_KEYFRAME_TABLE")
    return out


def constant(name, *values):
    return table(name, [(0.0, *values), (1.0, *values)])


def particle(name, first_cell, cell_count, size_m, tint, alpha, max_particles=MAX_PARTICLES):
    out = ["PARTICLE"]
    out += [" " + line for line in (
        f"NAME {name}", f"MAX_PARTICLES {max_particles}", "BILLBOARD_MODE BILLBOARD",
        "BLEND_MODE BLEND", f"TEX_CELLS_X {CELLS}", f"TEX_CELLS_Y {CELLS}",
        f"ANIM_CELL_START {first_cell}", f"ANIM_CELL_COUNT {cell_count}",
        "ANIM_CELL_REPEAT 1", "ANIM_CELL_RANDOM 1")]
    out += constant("ANIM_CELL_KF", 1.0)
    # A slow start and end, so a particle never pops. These curves run on life fraction.
    out += table("SIZE_CURVE", [(0.0, 0.7 * size_m), (0.15, size_m), (1.0, 1.1 * size_m)])
    out += table("ALPHA_CURVE", [(0.0, 0.0), (0.06, alpha), (0.85, alpha), (1.0, 0.0)])
    out += constant("LENGTH_CURVE", 0.1)
    out += constant("INTENSITY_CURVE", 1000.0)
    out += [f" DIFFUSE {LIGHT:.6f}", f" AMBIENT {LIGHT:.6f}"]
    out += table("EMISSIVE", [(0.0, 0.0), (25000.0, 0.0)])
    out += constant("TINT", *tint)
    out += constant("GRAVITY_CURVE", 0.0)
    out += constant("TURBULENCE", 0.0)
    out += constant("DRAG_CURVE", DRAG)
    out += constant("SPIN_CURVE", 0.0)
    out += constant("ELASTICITY", 0.0)
    out += [" COLLISION_MODE NONE", "END_PARTICLE"]
    return out


def particles(layers=LAYERS, prefix="", tint=None, max_particles=MAX_PARTICLES):
    """One particle type per layer, in the order of `layers`. tint: one for all of them."""
    out = []
    for layer in layers:
        out += particle(prefix + layer.name, layer.cells[0], layer.cells[1], layer.size_m,
                        tint or layer.tint, layer.alpha, max_particles)
    return out


def scaled(name, low, high, slot, fixed=1.0):
    """A random range that grows with the scale slot, or one at a fixed scale with no slot."""
    if slot is None:
        return constant(name, low * fixed, high * fixed)
    return table(name, [(0.0, 0.0, 0.0), (SCALE_TOP, low * SCALE_TOP, high * SCALE_TOP)], slot=slot)


def sub_emitter(kind, layer, rate_rows, rate_slot, scale_slot, fixed_scale=1.0):
    """Particle type `kind` for `layer`. rate_rows: rows of (key, multiple of the steady rate)."""
    rate = layer.count / TTL_S
    rows = [(key, rate * factor, rate * factor) for key, factor in rate_rows]
    x0, x1, y0, y1, z0, z1 = layer.box
    out = ["SUB_EMITTER", f" PARTICLE_TYPE {kind}"]
    out += table("EMIT_RATE", rows, slot=rate_slot)
    out += constant("INITIAL_SPEED", 0.0, 0.0)
    out += constant("ROTATION_SPEED", 0.0, 0.0)
    out += constant("INITIAL_HEADING", 0.0, 0.0)
    out += constant("INITIAL_PITCH", 0.0, 0.0)
    out += scaled("DX", x0, x1, scale_slot, fixed_scale)
    out += scaled("DY", y0, y1, scale_slot, fixed_scale)
    out += scaled("DZ", z0, z1, scale_slot, fixed_scale)
    out += constant("DLON", 0.0, 0.0)
    out += constant("DLAT", 0.0, 0.0)
    out += constant("DRAD", 0.0, 0.0)
    out += constant("INITIAL_ROTATION", -10.0, 10.0)
    out += scaled("INITIAL_SIZE", *layer.spread, scale_slot, fixed_scale)
    out += constant("INITIAL_ALPHA", 1.0, 1.0)
    out += constant("TIME_TO_LIVE", TTL_S * (1.0 - TTL_SPREAD), TTL_S * (1.0 + TTL_SPREAD))
    out += [" HIDE_UNTIL_COLLIDE 0", " RANDOMIZE_ROLL 0", " THINNING 0.000000", "END_SUB_EMITTER"]
    return out


def groups(layers):
    """The layers in runs of at most SUBS_PER_EMITTER, one emitter each, in order."""
    return [layers[i:i + SUBS_PER_EMITTER] for i in range(0, len(layers), SUBS_PER_EMITTER)]


def emitter_names(name, layers=LAYERS):
    return [f"{name}_{k}" for k in range(len(groups(layers)))]


def emitter(name, rate_rows, rate_slot, scale_slot, drefs, layers=LAYERS, first_kind=0,
            fixed_scale=1.0):
    """The emitters for `layers`, named as `emitter_names` says."""
    out = []
    kind = first_kind
    for em_name, group in zip(emitter_names(name, layers), groups(layers)):
        out += ["EMITTER", f" NAME {em_name}", " EMIT_MODE STREAM"]
        for layer in group:
            out += sub_emitter(kind, layer, rate_rows, rate_slot, scale_slot, fixed_scale)
            kind += 1
        out.append(f"DATAREFS {len(drefs)}")
        out += [f"DREF {d}" for d in drefs]
        out.append("END_EMITTER")
    return out


def system(name, parts, emitters):
    """A particle system file. name: of its texture."""
    out = ["A", "1200", "PARTICLE_SYSTEM", "", f" TEXTURE {name}.png"]
    out += parts
    out += emitters
    out += [f" TEX_CELLS_X {CELLS}", f" TEX_CELLS_Y {CELLS}", "DATAREFS 0", "END_PARTICLE_SYSTEM", ""]
    return "\n".join(out)


def object_text(system_name, emitter_name, layers=LAYERS):
    lines = ["A", "800", "OBJ", "", "TEXTURE", f"PARTICLE_SYSTEM {system_name}.pss", "",
             "POINT_COUNTS 0 0 0 0", "", f"ATTR_LOD 0 {LOD_M}"]
    lines += [f"EMITTER {em} 0.0 {EMITTER_Y_M:.1f} 0.0  0.0 0.0 0.0  0"
              for em in emitter_names(emitter_name, layers)]
    return "\n".join(lines + [""])


def png_bytes(image):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return buffer.getvalue()


def outputs():
    """File name -> bytes, everything this script writes."""
    rate_rows = [(0.0, 0.0), (1.0, 1.0), (RATE_TOP, RATE_TOP)]
    pss = system(NAME, particles(), emitter(NAME, rate_rows, 0, 1, [RATE_DATAREF, SCALE_DATAREF]))
    return {f"{NAME}.png": png_bytes(texture()),
            f"{NAME}.pss": pss.encode("ascii"),
            f"{NAME}.obj": object_text(NAME, NAME).encode("ascii")}


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for name, data in outputs().items():
        with open(os.path.join(OUT_DIR, name), "wb") as f:
            f.write(data)
    print(f"wrote {NAME}.* to {OUT_DIR}")


if __name__ == "__main__":
    main()
