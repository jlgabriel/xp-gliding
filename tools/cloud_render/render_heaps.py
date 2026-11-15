"""Render the cells of the Billow cloud styles in Blender: heaps of cumulus lit as volumes.

Usage (Blender 5.2, from the repository's root):
    blender -b --factory-startup --python tools/cloud_render/render_heaps.py -- OUT_DIR [--version billow]
    blender -b --factory-startup --python tools/cloud_render/render_heaps.py -- OUT_DIR --cells 0 5

Writes cell00.png to cell15.png in OUT_DIR, 512 px each with a transparent background; then
`make_heaps_style.py` puts them in an atlas and writes the style. Each cell is one whole heap of
cumulus (cells 0-11 heaps, 12-15 smaller pieces), so a cloud can be drawn with a few large
particles whose relief, grey creases and shaded underside come from the render.

A heap is spheres at three scales: some fourteen making the heap, bulges standing out on their
upper sides, small bulges on those, and a fairly level bottom. Geometry nodes' Points to Volume
turns them into a volume five times:
- a core, the spheres smaller (0.72-0.74 of their radius), dense (40), torn inside by fine
  noise, which gives the cauliflower relief and the grey creases, and cut into by a coarse noise,
  which breaks the outline of its spheres;
- four halo shells around it, from 1.0 to 1.9-2.0 of the radius, each thinner (18 down to 5) and
  torn by coarser, more distorted noise, so the edge fades out in loose tufts instead of ending
  at a sphere's outline.
Lit by a sun from above, a little to the side and towards the camera, and a soft blue sky;
an orthographic camera looking level; Cycles on the GPU when there is one.

The first Billow styles (1.1, 2026-11-14) had one halo shell at 1.3-1.36 around a core at
0.85-0.88: in the simulator their outline still read as round balls ending abruptly. Two
shells of density 5 and 1.8 beyond it barely showed; these densities fray it.

Found while making it (2026-11-14): a mesh of metaballs with even density looks like plastic,
and pushing that mesh out with Voronoi cells folds it and crashed Blender. A volume from points
has neither problem.

All of it is authored here; nothing comes from another simulator's or add-on's assets.
License: GPL-3.0-or-later.
"""

import argparse
import math
import os
import random
import sys

import bpy
from mathutils import Vector

RES = 512
SAMPLES = 96
# core: (density, noise scale, erosion, radius factor[, coarse noise (scale, erosion, ramp
# width)]); halos: shells around it, inside out, each (radius factor, density, noise scale,
# erosion, ramp width, distortion). billow-light is lighter in the atlas, with a wider fringe.
VERSIONS = {
    "billow": ((40.0, 14.0, 0.36, 0.74, (3.5, 0.40, 0.22)),
               ((1.00, 18.0, 18.0, 0.42, 0.30, 0.6),
                (1.25, 12.0, 12.0, 0.48, 0.26, 1.2),
                (1.55, 9.0, 8.0, 0.54, 0.22, 2.0),
                (1.90, 6.0, 6.0, 0.58, 0.20, 3.0))),
    "billow-light": ((40.0, 14.0, 0.36, 0.72, (3.5, 0.40, 0.22)),
                     ((1.00, 16.0, 18.0, 0.40, 0.34, 0.6),
                      (1.28, 11.0, 11.0, 0.47, 0.28, 1.2),
                      (1.60, 8.0, 7.5, 0.53, 0.24, 2.0),
                      (2.00, 5.0, 5.5, 0.57, 0.22, 3.0))),
}
# Cell k: (seed, width, height, heap balls, bulges, small bulges). 0-11 heaps, 12-15 small pieces.
CELLS = [(100 + k, 0.9 + 0.4 * ((k * 7) % 5) / 4, 0.6 + 0.35 * ((k * 3) % 4) / 3, 14, 45, 140)
         for k in range(12)] + [(200 + k, 0.7, 0.55, 5, 16, 50) for k in range(4)]


def scene():
    return bpy.context.scene


def setup():
    """An empty scene: Cycles, a transparent film, sun, sky and an orthographic camera."""
    for o in list(bpy.data.objects):
        bpy.data.objects.remove(o, do_unlink=True)
    s = scene()
    s.render.engine = 'CYCLES'
    try:
        prefs = bpy.context.preferences.addons['cycles'].preferences
        for kind in ('OPTIX', 'CUDA', 'HIP', 'METAL', 'ONEAPI'):
            try:
                prefs.compute_device_type = kind
            except TypeError:
                continue
            prefs.refresh_devices()
            gpus = [d for d in prefs.devices if d.type == kind]
            if gpus:
                for d in prefs.devices:
                    d.use = d.type == kind
                s.cycles.device = 'GPU'
                break
    except KeyError:
        pass
    s.cycles.samples = SAMPLES
    s.cycles.use_denoising = True
    s.cycles.volume_bounces = 12
    s.cycles.max_bounces = 16
    s.cycles.transparent_max_bounces = 16
    s.render.film_transparent = True
    s.render.resolution_x = s.render.resolution_y = RES
    s.view_settings.view_transform = 'Standard'
    s.view_settings.look = 'None'
    s.render.image_settings.file_format = 'PNG'
    s.render.image_settings.color_mode = 'RGBA'
    w = bpy.data.worlds.get("World") or bpy.data.worlds.new("World")
    s.world = w
    w.use_nodes = True
    bg = w.node_tree.nodes.get("Background")
    bg.inputs[0].default_value = (0.45, 0.6, 0.9, 1.0)
    bg.inputs[1].default_value = 0.35
    sun_data = bpy.data.lights.new("Sun", 'SUN')
    sun_data.energy = 6.0
    sun_data.angle = math.radians(1.0)
    sun = bpy.data.objects.new("Sun", sun_data)
    s.collection.objects.link(sun)
    # The light travels to the right, away from the camera a little, and down.
    sun.rotation_euler = Vector((0.45, 0.35, -0.82)).normalized().to_track_quat('-Z', 'Y').to_euler()
    cam_data = bpy.data.cameras.new("Cam")
    cam_data.type = 'ORTHO'
    cam = bpy.data.objects.new("Cam", cam_data)
    s.collection.objects.link(cam)
    cam.location = (0, -10, 0)
    cam.rotation_euler = (math.radians(90), 0, 0)
    s.camera = cam


def volume_material(name, density, noise_scale, erode, width, detail, roughness, distortion=0.0, coarse=None):
    """White scattering cloud whose density is cut into by noise in the object's space; with
    coarse = (noise scale, erosion, ramp width), also cut into by a second, coarser noise."""
    m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    pv = nt.nodes.new("ShaderNodeVolumePrincipled")
    pv.inputs["Color"].default_value = (1, 1, 1, 1)
    pv.inputs["Anisotropy"].default_value = 0.3
    tc = nt.nodes.new("ShaderNodeTexCoord")
    nz = nt.nodes.new("ShaderNodeTexNoise")
    nz.inputs["Scale"].default_value = noise_scale
    nz.inputs["Detail"].default_value = detail
    nz.inputs["Roughness"].default_value = roughness
    nz.inputs["Distortion"].default_value = distortion
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    e0, e1 = ramp.color_ramp.elements
    e0.position, e0.color = erode, (0, 0, 0, 1)
    e1.position, e1.color = erode + width, (1, 1, 1, 1)
    mul = nt.nodes.new("ShaderNodeMath")
    mul.operation = 'MULTIPLY'
    mul.inputs[1].default_value = density
    nt.links.new(tc.outputs["Object"], nz.inputs["Vector"])
    nt.links.new(nz.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], mul.inputs[0])
    if coarse:
        cz = nt.nodes.new("ShaderNodeTexNoise")
        cz.inputs["Scale"].default_value = coarse[0]
        cz.inputs["Detail"].default_value = 4.0
        cz.inputs["Roughness"].default_value = 0.55
        cz.inputs["Distortion"].default_value = 0.8
        cramp = nt.nodes.new("ShaderNodeValToRGB")
        c0, c1 = cramp.color_ramp.elements
        c0.position, c0.color = coarse[1], (0, 0, 0, 1)
        c1.position, c1.color = coarse[1] + coarse[2], (1, 1, 1, 1)
        both = nt.nodes.new("ShaderNodeMath")
        both.operation = 'MULTIPLY'
        nt.links.new(tc.outputs["Object"], cz.inputs["Vector"])
        nt.links.new(cz.outputs["Fac"], cramp.inputs["Fac"])
        nt.links.new(ramp.outputs["Color"], both.inputs[0])
        nt.links.new(cramp.outputs["Color"], both.inputs[1])
        nt.links.new(both.outputs[0], mul.inputs[0])
    nt.links.new(mul.outputs[0], pv.inputs["Density"])
    nt.links.new(pv.outputs["Volume"], out.inputs["Volume"])
    return m


def heap(seed, width, height, n_heap, n_mid, n_fine):
    """Centres and radii of a heap: base balls, bulges on their upper sides, small bulges."""
    rng = random.Random(seed)
    balls = []
    for _ in range(n_heap):
        f = rng.random() ** 1.3
        z = -0.25 + height * 0.6 * f
        reach = width * 0.48 * (1 - 0.6 * f)
        balls.append((Vector((rng.uniform(-reach, reach), rng.uniform(-0.12, 0.12), z)),
                      rng.uniform(0.17, 0.23) * (1 - 0.25 * f)))
    for (rmin, rmax, n), out, up in (((0.08, 0.13, n_mid), 0.88, 95), ((0.035, 0.06, n_fine), 0.95, 105)):
        base = list(balls)
        for _ in range(n):
            c, r = rng.choice(base)
            th = math.radians(rng.uniform(-up, up))
            ph = rng.uniform(0, 2 * math.pi)
            dv = Vector((math.sin(th) * math.cos(ph), 0.6 * math.sin(th) * math.sin(ph), math.cos(th))).normalized()
            p = c + dv * r * out
            if p.z < -0.30:  # a fairly level bottom
                continue
            balls.append((p, rng.uniform(rmin, rmax)))
    return balls


def volume_object(balls, name, material, voxel):
    """A volume from spheres, through geometry nodes' Points to Volume."""
    me = bpy.data.meshes.new(name + "_pts")
    me.from_pydata([tuple(c) for c, _ in balls], [], [])
    attr = me.attributes.new("radius", 'FLOAT', 'POINT')
    attr.data.foreach_set("value", [r for _, r in balls])
    o = bpy.data.objects.new(name, me)
    scene().collection.objects.link(o)
    ng = bpy.data.node_groups.new(name + "_gn", 'GeometryNodeTree')
    ng.interface.new_socket("Geometry", in_out='INPUT', socket_type='NodeSocketGeometry')
    ng.interface.new_socket("Geometry", in_out='OUTPUT', socket_type='NodeSocketGeometry')
    n = ng.nodes
    gi, go = n.new("NodeGroupInput"), n.new("NodeGroupOutput")
    m2p = n.new("GeometryNodeMeshToPoints")
    rad = n.new("GeometryNodeInputNamedAttribute")
    rad.data_type = 'FLOAT'
    rad.inputs["Name"].default_value = "radius"
    p2v = n.new("GeometryNodePointsToVolume")
    p2v.inputs["Density"].default_value = 1.0
    try:
        p2v.resolution_mode = 'VOXEL_SIZE'
    except (AttributeError, TypeError):
        p2v.inputs["Resolution Mode"].default_value = 'Size'
    p2v.inputs["Voxel Size"].default_value = voxel
    sm = n.new("GeometryNodeSetMaterial")
    sm.inputs["Material"].default_value = material
    ng.links.new(gi.outputs[0], m2p.inputs["Mesh"])
    ng.links.new(m2p.outputs[0], p2v.inputs["Points"])
    ng.links.new(rad.outputs[0], m2p.inputs["Radius"])  # Mesh to Points sets its own radius otherwise
    ng.links.new(rad.outputs[0], p2v.inputs["Radius"])
    ng.links.new(p2v.outputs[0], sm.inputs["Geometry"])
    ng.links.new(sm.outputs[0], go.inputs[0])
    o.modifiers.new("volume", 'NODES').node_group = ng
    return o


def render_cell(k, version, out_dir):
    (cd, cn, ce, core_k, *coarse), halos = VERSIONS[version]
    core_mat = volume_material("Core", cd, cn, ce, 0.18, detail=10.0, roughness=0.62,
                               coarse=coarse[0] if coarse else None)
    for o in [o for o in scene().objects if o.type == 'MESH']:
        bpy.data.objects.remove(o, do_unlink=True)
    balls = heap(*CELLS[k])
    volume_object([(c, r * core_k) for c, r in balls], "Core", core_mat, 0.008)
    for i, (halo_k, hd, hn, he, hw, hdist) in enumerate(halos):
        name = "Halo" if i == 0 else f"Halo{i}"
        mat = volume_material(name, hd, hn, he, hw, detail=14.0, roughness=0.7, distortion=hdist)
        halo = [(c, r * halo_k) for c, r in balls]
        volume_object(halo, name, mat, 0.01 if i == 0 else 0.014)
    lo_x, hi_x = min(c.x - r for c, r in halo), max(c.x + r for c, r in halo)
    lo_z, hi_z = min(c.z - r for c, r in halo), max(c.z + r for c, r in halo)
    cam = scene().camera
    cam.location = ((lo_x + hi_x) / 2, -10, (lo_z + hi_z) / 2)
    cam.data.ortho_scale = max(hi_x - lo_x, hi_z - lo_z) * 1.08
    print(f"cell {k:02d} frame {cam.data.ortho_scale:.3f}", flush=True)
    scene().render.filepath = os.path.join(out_dir, f"cell{k:02d}.png")
    bpy.ops.render.render(write_still=True)


def main():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("out_dir")
    parser.add_argument("--version", choices=sorted(VERSIONS), default="billow")
    parser.add_argument("--cells", type=int, nargs="*", default=list(range(16)))
    args = parser.parse_args(argv)
    os.makedirs(args.out_dir, exist_ok=True)
    setup()
    for k in args.cells:
        render_cell(k, args.version, os.path.abspath(args.out_dir))
        print(f"cell {k:02d} done", flush=True)


if __name__ == "__main__":
    main()
