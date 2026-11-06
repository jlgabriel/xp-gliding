"""Generate the cumulus object, particle system and texture: xp_gliding/assets/clouds/.

Usage:
    python tools/make_cloud_objs.py

All of it is authored here; nothing comes from another plugin's assets. The output is
committed, and a test checks that it matches this script.

The cloud is three particle types over an object with no geometry: a flat grey base, a
white body, and small bright tops. Particles have no speed, gravity or drag, so they stay
where they were emitted: the emitter's random offsets (DX, DY, DZ) are the cloud's shape,
and rate x life is the number alive. Two values come per instance, as datarefs of the
instance (`xp_gliding.adapter.clouds`), and drive the emitter's tables:
- rate: 0 stops feeding, 1 is the steady cloud, up to `RATE_TOP` fills it fast.
- scale: 1 is the object's size. It scales the offsets and the particles' size.

The texture bakes the light: billboards always face the camera, so each puff is brighter
at its top and greyer at its bottom, and initial rotation stays small to keep that. Puffs
fade out before the edge of their cell: a puff cut by the cell shows as a straight line
from close up (seen flying through the first version).

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
SEED = 20261104
LOD_M = 40000

# Particle life (s): long, so a cloud needs few new ones. CloudParams.ttl_s is the longest.
TTL_S = 180.0
TTL_SPREAD = 0.2
# How fast a particle takes on the speed of the air around it, so XP12's wind carries it.
DRAG = 1.0
# Particles alive per cloud at rate 1, per type.
BASE_N, BODY_N, TOP_N = 60, 180, 80
# Shape at scale 1 (m): half width, and height above the base.
HALF_WIDTH_M = 500.0
BASE_WIDTH, BODY_WIDTH, TOP_WIDTH = 0.75, 0.85, 0.60  # fraction of HALF_WIDTH_M
BASE_DY = (0.0, 40.0)
BODY_DY = (60.0, 320.0)
TOP_DY = (260.0, 480.0)
# Billboard size (m); the particles' curve is multiplied by the initial size.
BASE_SIZE, BODY_SIZE, TOP_SIZE = 210.0, 200.0, 130.0
BASE_TINT, BODY_TINT, TOP_TINT = (0.80, 0.82, 0.86), (0.98, 0.98, 1.00), (1.00, 1.00, 1.00)
ALPHA_BASE, ALPHA_BODY, ALPHA_TOP = 0.80, 0.75, 0.85
MAX_PARTICLES = 2048  # per emitter: far above what rate x life can reach
LIGHT = 1.2  # X-Plane's ambient and diffuse for a particle; at 1.0 clouds looked grey at noon
RATE_TOP = 20.0  # CloudParams.prewarm: fills a cloud in TTL_S / RATE_TOP
SCALE_TOP = 2.0
# The base of a puff reaches below its centre: raise the emitter so the bottom of the cloud,
# not the centre of the lowest puffs, is at the height the instance is placed.
EMITTER_Y_M = 80.0


def noise2(rng, size, octaves=5, base=4):
    """Value noise in [0, 1]."""
    total = np.zeros((size, size))
    amp, norm = 1.0, 0.0
    ys, xs = np.mgrid[0:size, 0:size] / size
    for o in range(octaves):
        n = base * 2 ** o
        grid = rng.random((n + 2, n + 2))
        gx, gy = xs * n, ys * n
        ix, iy = gx.astype(int), gy.astype(int)
        fx, fy = gx - ix, gy - iy
        fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
        top = grid[iy, ix] * (1 - fx) + grid[iy, ix + 1] * fx
        bottom = grid[iy + 1, ix] * (1 - fx) + grid[iy + 1, ix + 1] * fx
        total += amp * (top * (1 - fy) + bottom * fy)
        norm += amp
        amp *= 0.55
    return total / norm


def puff(rng, size, flat):
    """One RGBA puff, floats in [0, 1]. flat: squash its top half, for the base's cells."""
    ys, xs = np.mgrid[0:size, 0:size] / (size - 1) * 2.0 - 1.0
    stretch = np.where(ys < 0.0, 1.0 + flat, 1.0)  # image y grows downward
    r = np.hypot(xs, ys * stretch)
    n = noise2(rng, size)
    edge = np.clip((1.0 - r - 0.9 * (n - 0.5)) / 0.35, 0.0, 1.0)
    alpha = edge * edge * (3.0 - 2.0 * edge)
    border = np.clip((1.0 - np.maximum(np.abs(xs), np.abs(ys))) / 0.12, 0.0, 1.0)
    alpha = alpha * border * border * (3.0 - 2.0 * border)
    light = 0.90 - 0.16 * ys + 0.14 * (n - 0.5)  # top bright, bottom greyer, some mottling
    rgb = np.clip(np.stack((light, light, light * 1.02), axis=-1), 0.0, 1.0)
    return np.dstack((rgb, alpha))


def texture():
    """Atlas of puffs. The row of cells at the image's bottom is flat, for the base."""
    rng = np.random.default_rng(SEED)
    atlas = np.zeros((CELL_PX * CELLS, CELL_PX * CELLS, 4))
    for row in range(CELLS):
        for col in range(CELLS):
            flat = 1.5 if row == CELLS - 1 else 0.0
            atlas[row * CELL_PX:(row + 1) * CELL_PX, col * CELL_PX:(col + 1) * CELL_PX] = \
                puff(rng, CELL_PX, flat)
    return Image.fromarray((atlas * 255.0 + 0.5).astype(np.uint8), "RGBA")


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


def particles():
    """The three particle types: 0 base, 1 body, 2 tops."""
    return (particle("base", 0, CELLS, BASE_SIZE, BASE_TINT, ALPHA_BASE)
            + particle("body", CELLS, CELLS, BODY_SIZE, BODY_TINT, ALPHA_BODY)
            + particle("top", 2 * CELLS, 2 * CELLS, TOP_SIZE, TOP_TINT, ALPHA_TOP))


def scaled(name, low, high, slot):
    """A random range that grows with the scale slot, or a constant one with no slot."""
    if slot is None:
        return constant(name, low, high)
    return table(name, [(0.0, 0.0, 0.0), (SCALE_TOP, low * SCALE_TOP, high * SCALE_TOP)], slot=slot)


def sub_emitter(kind, count, half_width, dy, rate_rows, rate_slot, scale_slot):
    """Particle type `kind`. rate_rows: rows of (key, multiple of the steady rate)."""
    rate = count / TTL_S
    rows = [(key, rate * factor, rate * factor) for key, factor in rate_rows]
    out = ["SUB_EMITTER", f" PARTICLE_TYPE {kind}"]
    out += table("EMIT_RATE", rows, slot=rate_slot)
    out += constant("INITIAL_SPEED", 0.0, 0.0)
    out += constant("ROTATION_SPEED", 0.0, 0.0)
    out += constant("INITIAL_HEADING", 0.0, 0.0)
    out += constant("INITIAL_PITCH", 0.0, 0.0)
    out += scaled("DX", -half_width, half_width, scale_slot)
    out += scaled("DY", *dy, scale_slot)
    out += scaled("DZ", -half_width, half_width, scale_slot)
    out += constant("DLON", 0.0, 0.0)
    out += constant("DLAT", 0.0, 0.0)
    out += constant("DRAD", 0.0, 0.0)
    out += constant("INITIAL_ROTATION", -12.0, 12.0)
    out += scaled("INITIAL_SIZE", 0.8, 1.2, scale_slot)
    out += constant("INITIAL_ALPHA", 1.0, 1.0)
    out += constant("TIME_TO_LIVE", TTL_S * (1.0 - TTL_SPREAD), TTL_S * (1.0 + TTL_SPREAD))
    out += [" HIDE_UNTIL_COLLIDE 0", " RANDOMIZE_ROLL 0", " THINNING 0.000000", "END_SUB_EMITTER"]
    return out


def emitter(name, rate_rows, rate_slot, scale_slot, drefs):
    out = ["EMITTER", f" NAME {name}", " EMIT_MODE STREAM"]
    out += sub_emitter(0, BASE_N, HALF_WIDTH_M * BASE_WIDTH, BASE_DY, rate_rows, rate_slot, scale_slot)
    out += sub_emitter(1, BODY_N, HALF_WIDTH_M * BODY_WIDTH, BODY_DY, rate_rows, rate_slot, scale_slot)
    out += sub_emitter(2, TOP_N, HALF_WIDTH_M * TOP_WIDTH, TOP_DY, rate_rows, rate_slot, scale_slot)
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


def object_text(system_name, emitter_name):
    return "\n".join((
        "A", "800", "OBJ", "", "TEXTURE", f"PARTICLE_SYSTEM {system_name}.pss", "",
        "POINT_COUNTS 0 0 0 0", "", f"ATTR_LOD 0 {LOD_M}",
        f"EMITTER {emitter_name} 0.0 {EMITTER_Y_M:.1f} 0.0  0.0 0.0 0.0  0", ""))


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
