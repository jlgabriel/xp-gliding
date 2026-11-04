"""Cloud lab: objects with a particle emitter, placed from outside, to learn what they can do.

Measurement tool, not part of the plugin. `fly_cloud.py install` copies this file and the
output of `make_cloud.py` to `PythonPlugins/`; restart X-Plane, then drive it with
`fly_cloud.py`. Writable datarefs under `xpg_cloudlab/`:

  load        write a version n: load cu<n>_{global,inst,fast}.obj in the background
  rate        the rate dataref cu_global's emitter reads (1: a steady cloud)
  i_rate      exists so the per-instance dataref can be found; instances carry their own
  kind        0 global, 1 per instance, 2 fast: the object of the next place
  value       the per-instance value of the next place
  count, spacing_m, dist_m, bearing_deg, dy_m, grid
              the next place, relative to the aircraft: `count` clouds in a line across the
              view at dist_m, or a square grid centred on the aircraft when grid is 1
  place       write anything: add those clouds
  clear       write anything: destroy every instance
  set_value   write anything: give every per-instance cloud the current `value`

Read only: `instances`, `loaded` (the version whose objects are all here), `errors`.

Positions are set once and left to `instanceSetAutoShift`, which is itself under trial.

License: GPL-3.0-or-later.
"""

import math
import os
import traceback

import xp

LAB = "xpg_cloudlab"
KINDS = ("global", "inst", "fast")
FLOATS = ("rate", "i_rate", "kind", "value", "count", "spacing_m", "dist_m", "bearing_deg",
          "dy_m", "grid")
I_RATE = (f"{LAB}/i_rate",)


class Lab:
    def __init__(self):
        self.values = {"rate": 1.0, "i_rate": 0.0, "kind": 0.0, "value": 1.0, "count": 1.0,
                       "spacing_m": 2000.0, "dist_m": 5000.0, "bearing_deg": 0.0, "dy_m": 300.0,
                       "grid": 0.0}
        self.folder = os.path.relpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), LAB),
                                      xp.getSystemPath()).replace(os.sep, "/")
        self.objects = {}
        self.version = 0
        self.instances = []  # (instance, kind, position)
        self.errors = 0
        self.refs = []
        self.pending = []
        self.lx = xp.findDataRef("sim/flightmodel/position/local_x")
        self.ly = xp.findDataRef("sim/flightmodel/position/local_y")
        self.lz = xp.findDataRef("sim/flightmodel/position/local_z")
        self.psi = xp.findDataRef("sim/flightmodel/position/true_psi")
        for name in FLOATS:
            self.refs.append(xp.registerDataAccessor(
                f"{LAB}/{name}", xp.Type_Float, 1, readFloat=self.read_value,
                writeFloat=self.write_value, readRefCon=name, writeRefCon=name))
        for name, action in (("load", self.load), ("place", self.place), ("clear", self.clear),
                             ("set_value", self.set_value)):
            self.refs.append(xp.registerDataAccessor(
                f"{LAB}/{name}", xp.Type_Int, 1, readInt=lambda _: 0, writeInt=self.ask,
                writeRefCon=action))
        self.refs.append(xp.registerDataAccessor(f"{LAB}/instances", xp.Type_Int, 0,
                                                 readInt=lambda _: len(self.instances)))
        self.refs.append(xp.registerDataAccessor(f"{LAB}/loaded", xp.Type_Int, 0,
                                                 readInt=lambda _: self.version))
        self.refs.append(xp.registerDataAccessor(f"{LAB}/errors", xp.Type_Int, 0,
                                                 readInt=lambda _: self.errors))
        self.floop = xp.createFlightLoop(self.loop, xp.FlightLoop_Phase_BeforeFlightModel, None)
        xp.scheduleFlightLoop(self.floop, -1)

    def read_value(self, name):
        return self.values[name]

    def write_value(self, name, value):
        self.values[name] = value

    def ask(self, action, value):
        """Writes come at any moment; the work happens in the flight loop."""
        self.pending.append((action, int(value)))

    def load(self, n):
        self.version = 0
        self.clear(0)
        for obj in self.objects.values():
            xp.unloadObject(obj)
        self.objects = {}
        for kind in KINDS:
            xp.loadObjectAsync(f"{self.folder}/cu{n}_{kind}.obj", self.loaded, (n, kind))

    def loaded(self, obj, ref):
        n, kind = ref
        if obj is None:
            xp.log(f"cloudlab: could not load cu{n}_{kind}")
            self.errors += 1
            return
        self.objects[kind] = obj
        if len(self.objects) == len(KINDS):
            self.version = n
            xp.log(f"cloudlab: cu{n} loaded")

    def place(self, _):
        v = self.values
        kind = KINDS[int(v["kind"])]
        ax, ay, az = xp.getDataf(self.lx), xp.getDataf(self.ly), xp.getDataf(self.lz)
        psi = math.radians(xp.getDataf(self.psi) + v["bearing_deg"])
        fx, fz = math.sin(psi), -math.cos(psi)  # forward, in local x (east), z (south)
        rx, rz = math.cos(psi), math.sin(psi)  # right
        n = int(v["count"])
        if v["grid"]:
            side = math.ceil(math.sqrt(n))
            spots = [((i % side - (side - 1) / 2.0) * v["spacing_m"],
                      (i // side - (side - 1) / 2.0) * v["spacing_m"]) for i in range(n)]
        else:
            spots = [((i - (n - 1) / 2.0) * v["spacing_m"], v["dist_m"]) for i in range(n)]
        for across, along in spots:
            pos = (ax + rx * across + fx * along, ay + v["dy_m"], az + rz * across + fz * along,
                   0.0, 0.0, 0.0)
            per_instance = kind == "inst"
            inst = xp.createInstance(self.objects[kind], I_RATE if per_instance else None)
            xp.instanceSetPosition(inst, pos, (v["value"],) if per_instance else None)
            xp.instanceSetAutoShift(inst)
            self.instances.append((inst, kind, pos))
        xp.log(f"cloudlab: placed {n} {kind}; total {len(self.instances)}")

    def set_value(self, _):
        for inst, kind, pos in self.instances:
            if kind == "inst":
                xp.instanceSetPosition(inst, pos, (self.values["value"],))

    def clear(self, _):
        for inst, _kind, _pos in self.instances:
            xp.destroyInstance(inst)
        self.instances = []

    def loop(self, *_):
        try:
            while self.pending:
                action, arg = self.pending.pop(0)
                action(arg)
        except Exception:
            self.errors += 1
            xp.log("cloudlab: " + traceback.format_exc())
        return -1

    def stop(self):
        self.clear(0)
        for obj in self.objects.values():
            xp.unloadObject(obj)
        xp.destroyFlightLoop(self.floop)
        for ref in self.refs:
            xp.unregisterDataAccessor(ref)


class PythonInterface:
    def XPluginStart(self):
        self.lab = Lab()
        return "xp-gliding cloud lab", "jlgabriel.xp_gliding.cloudlab", "Particle clouds: what they can do."

    def XPluginStop(self):
        self.lab.stop()

    def XPluginEnable(self):
        return 1

    def XPluginDisable(self):
        pass

    def XPluginReceiveMessage(self, inFromWho, inMessage, inParam):
        pass
