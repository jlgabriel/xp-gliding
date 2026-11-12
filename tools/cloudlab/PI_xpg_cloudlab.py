"""Cloud lab: objects with a particle emitter, placed from outside, to learn what they can do.

Measurement tool, not part of the plugin. `fly_cloud.py install` copies this file and the
output of `make_cloud.py` to `PythonPlugins/`; restart X-Plane, then drive it with
`fly_cloud.py`. Writable datarefs under `xpg_cloudlab/`:

  load        write a version n: load cu<n>_{global,inst,fast}.obj in the background
  rate        the rate dataref cu_global's emitter reads (1: a steady cloud)
  i_rate      exists so the per-instance dataref can be found; instances carry their own
  kind        0 global, 1 per instance, 2 fast: the object of the next place; 3 to 10
              the objects of `make_order.py` (white, red, blue, red1, blue1, pair, pairrev,
              whitepair), when the version loaded was written by it; 11 the plugin's own
              cumulus as `make_cloud.py --plugin` copies it, driven by the plugin's rate and
              scale datarefs (xp_gliding must be running), with `value` as rate and `scale`
  value       the per-instance value of the next place
  ver         the version whose objects the next place uses; 0: the last loaded. Loading a
              version keeps the others loaded, so two looks can stand side by side
  scale       the plugin cumulus's scale (kind 11)
  heading_deg the plugin cumulus's heading; below 0, a random one per cloud
  count, spacing_m, dist_m, bearing_deg, dy_m, grid
              the next place, relative to the aircraft: `count` clouds in a line across the
              view at dist_m, or a square grid centred on the aircraft when grid is 1
  place       write anything: add those clouds
  clear       write anything: destroy every instance
  set_value   write anything: give every per-instance cloud the current `value`
  touch       write k: set the position of the k-th instance placed (from 0) again, unchanged
  destroy_at  write k: destroy the k-th instance placed (from 0); the rest keep their numbers
  recreate    write k: destroy the k-th instance and create it again in the same place

Read only: `instances`, `loaded` (the version whose objects are all here), `errors`.

Positions are set once and left to `instanceSetAutoShift`, which is itself under trial.

License: GPL-3.0-or-later.
"""

import math
import os
import random
import traceback

import xp

LAB = "xpg_cloudlab"
KINDS = ("global", "inst", "fast", "white", "red", "blue", "red1", "blue1", "pair", "pairrev",
         "whitepair", "plugin")
FLOATS = ("rate", "i_rate", "kind", "value", "count", "spacing_m", "dist_m", "bearing_deg",
          "dy_m", "grid", "ver", "scale", "heading_deg")
I_RATE = (f"{LAB}/i_rate",)
PLUGIN_REFS = ("xp_gliding/clouds/rate", "xp_gliding/clouds/scale")


class Lab:
    def __init__(self):
        self.values = {"rate": 1.0, "i_rate": 0.0, "kind": 0.0, "value": 1.0, "count": 1.0,
                       "spacing_m": 2000.0, "dist_m": 5000.0, "bearing_deg": 0.0, "dy_m": 300.0,
                       "grid": 0.0, "ver": 0.0, "scale": 1.0, "heading_deg": -1.0}
        self.folder = os.path.relpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), LAB),
                                      xp.getSystemPath()).replace(os.sep, "/")
        self.objects = {}
        self.expected = []
        self.version = 0
        self.last = 0
        self.instances = []  # (instance, (version, kind), position)
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
                             ("set_value", self.set_value), ("touch", self.touch),
                             ("destroy_at", self.destroy_at), ("recreate", self.recreate)):
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
        for k, (inst, (n_ver, kind), pos) in enumerate(self.instances):
            if inst is not None and n_ver == n:
                xp.destroyInstance(inst)
                self.instances[k] = (None, (n_ver, kind), pos)
        for key in [key for key in self.objects if key[0] == n]:
            xp.unloadObject(self.objects.pop(key))
        root = os.path.join(xp.getSystemPath(), self.folder)
        self.expected = [kind for kind in KINDS if os.path.exists(os.path.join(root, f"cu{n}_{kind}.obj"))]
        for kind in self.expected:
            xp.loadObjectAsync(f"{self.folder}/cu{n}_{kind}.obj", self.loaded, (n, kind))

    def loaded(self, obj, ref):
        n, kind = ref
        if obj is None:
            xp.log(f"cloudlab: could not load cu{n}_{kind}")
            self.errors += 1
            return
        self.objects[(n, kind)] = obj
        if all((n, k) in self.objects for k in self.expected):
            self.last = n
            self.version = n
            xp.log(f"cloudlab: cu{n} loaded")

    def place(self, _):
        v = self.values
        kind = KINDS[int(v["kind"])]
        n_ver = int(v["ver"]) or self.last
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
            # Turned to the bearing, so an object's -z points away from the aircraft (pairs).
            pos = (ax + rx * across + fx * along, ay + v["dy_m"], az + rz * across + fz * along,
                   0.0, math.degrees(psi) % 360.0, 0.0)
            if kind == "plugin":
                heading = v["heading_deg"] if v["heading_deg"] >= 0.0 else random.uniform(0.0, 360.0)
                pos = pos[:4] + (heading, 0.0)
            refs, data = self._data(kind)
            inst = xp.createInstance(self.objects[(n_ver, kind)], refs)
            xp.instanceSetPosition(inst, pos, data)
            xp.instanceSetAutoShift(inst)
            self.instances.append((inst, (n_ver, kind), pos))
        xp.log(f"cloudlab: placed {n} cu{n_ver} {kind}; total {len(self.instances)}")

    def _data(self, kind):
        """The datarefs of an instance of this kind, and their values now."""
        if kind == "inst":
            return I_RATE, (self.values["value"],)
        if kind == "plugin":
            return PLUGIN_REFS, (self.values["value"], self.values["scale"])
        return None, None

    def set_value(self, _):
        for inst, (_n, kind), pos in self.instances:
            if inst is not None and kind in ("inst", "plugin"):
                xp.instanceSetPosition(inst, pos, self._data(kind)[1])

    def touch(self, k):
        inst, (_n, kind), pos = self.instances[k]
        if inst is not None:
            xp.instanceSetPosition(inst, pos, self._data(kind)[1])
            xp.log(f"cloudlab: touched {k}")

    def destroy_at(self, k):
        inst, kind, pos = self.instances[k]
        if inst is not None:
            xp.destroyInstance(inst)
            self.instances[k] = (None, kind, pos)
            xp.log(f"cloudlab: destroyed {k}")

    def recreate(self, k):
        self.destroy_at(k)
        _, (n, kind), pos = self.instances[k]
        refs, data = self._data(kind)
        inst = xp.createInstance(self.objects[(n, kind)], refs)
        xp.instanceSetPosition(inst, pos, data)
        xp.instanceSetAutoShift(inst)
        self.instances[k] = (inst, (n, kind), pos)
        xp.log(f"cloudlab: recreated {k}")

    def clear(self, _):
        for inst, _kind, _pos in self.instances:
            if inst is not None:
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
