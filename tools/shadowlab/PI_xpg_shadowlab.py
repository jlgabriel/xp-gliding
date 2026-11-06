"""Shadow lab: a draped object through XPLMInstance, moved from Python, to see what it does.

Measurement tool, not part of the plugin. `fly_shadow.py install` copies this file and the output
of `make_shadow.py` to `PythonPlugins/`; restart X-Plane, then drive it with `fly_shadow.py`.
Writable datarefs under `xpg_shadowlab/`:

  load        write a version n: load shadow<n>_*.obj, post<n>.obj and Laminar's two controls
  kind        an index in KINDS below: the object of the next place
  count, spacing_m, dist_m, bearing_deg, grid, agl_m
              the next place, relative to the aircraft: `count` in a line across the view at
              dist_m, or a square grid centred dist_m ahead when grid is 1. agl_m is added to
              the ground the probe finds. off_e_m and off_n_m shift the place east and north
  place       write anything: add those
  clear       write anything: destroy every instance
  speed_ms, move_bearing_deg, period_s, spread, probe_moves
              move every instance at speed_ms towards move_bearing_deg, each once every
              period_s (0 speed: still). spread 0: all in one frame; 1: a slice each frame.
              probe_moves 0: keep the height above sea level it had when placed, as a cloud does
  step        write metres: one move of everything along move_bearing_deg, now
  cam_up_m, cam_back_m, cam_bearing_deg
              where the outside camera stands: above and away from the first instance
  cam         write 1: take the camera there and hold it (it stays if the instance moves);
              write 0: give it back
  stats       write anything: forget the frame times and update times gathered so far

Read only: `instances`, `loaded` (the version whose objects are all here), `errors`, `ticks`,
`moves`, `ground_m` and `wet` (the last probe of the first instance), `frame_ms_median`,
`frame_ms_p99`, `frame_ms_max` (every frame seen by the flight loop, so a hitch cannot fall
between samples), `update_us_mean`, `update_us_max` (the frames in which something moved).

Instances remember where they are as latitude and longitude, so a shift of the local origin
does not matter. License: GPL-3.0-or-later.
"""

import math
import os
import time
import traceback

import xp

LAB = "xpg_shadowlab"
# 0-3 the lab's own, 4-7 controls for the way the object is written (see make_shadow.py), 8-9
# Laminar's objects with draped triangles, loaded from the default scenery, not copied.
# 10-11 geometry in the sky, for X-Plane's own shadows.
KINDS = ("soft", "strong", "grid", "post", "flat", "mirror", "tiny", "mixed", "lam_grass", "lam_stand",
         "sky_solid", "sky_hidden")
LAMINAR = {"lam_grass": "Resources/default scenery/1000 autogen/EU/industrial/gnd_grass_12x30.obj",
           "lam_stand": "Resources/default scenery/1000 autogen/global_objects/constructions/grandstd_baseball1.obj"}
M_PER_DEG = 111320.0
FLOATS = ("kind", "count", "spacing_m", "dist_m", "bearing_deg", "grid", "agl_m", "speed_ms",
          "move_bearing_deg", "period_s", "spread", "probe_moves", "cam_up_m", "cam_back_m",
          "cam_bearing_deg", "off_e_m", "off_n_m")


class Shadow:
    __slots__ = ("inst", "lat", "lon", "alt", "last_move")

    def __init__(self, inst, lat, lon, now):
        self.inst, self.lat, self.lon, self.alt, self.last_move = inst, lat, lon, 0.0, now


class Lab:
    def __init__(self):
        self.values = {"kind": 0.0, "count": 1.0, "spacing_m": 2000.0, "dist_m": 4000.0,
                       "bearing_deg": 0.0, "grid": 0.0, "agl_m": 0.0, "speed_ms": 0.0,
                       "move_bearing_deg": 90.0, "period_s": 1.0, "spread": 1.0, "probe_moves": 1.0,
                       "cam_up_m": 1500.0, "cam_back_m": 1500.0, "cam_bearing_deg": 180.0, "off_e_m": 0.0, "off_n_m": 0.0}
        self.folder = os.path.relpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), LAB),
                                      xp.getSystemPath()).replace(os.sep, "/")
        self.objects = {}
        self.version = 0
        self.shadows = []
        self.errors = 0
        self.ticks = 0
        self.moves = 0
        self.ground_m = 0.0
        self.wet = 0
        self.frames = []
        self.updates = []
        self.last_all = 0.0
        self.camera_at = None
        self.pending = []
        self.refs = []
        self.probe = xp.createProbe(xp.ProbeY)
        self.lat = xp.findDataRef("sim/flightmodel/position/latitude")
        self.lon = xp.findDataRef("sim/flightmodel/position/longitude")
        self.psi = xp.findDataRef("sim/flightmodel/position/true_psi")
        for name in FLOATS:
            self.refs.append(xp.registerDataAccessor(
                f"{LAB}/{name}", xp.Type_Float, 1, readFloat=self.read_value,
                writeFloat=self.write_value, readRefCon=name, writeRefCon=name))
        for name, action in (("load", self.load), ("place", self.place), ("clear", self.clear),
                             ("step", self.step), ("cam", self.cam), ("stats", self.reset_stats)):
            self.refs.append(xp.registerDataAccessor(
                f"{LAB}/{name}", xp.Type_Int, 1, readInt=lambda _: 0, writeInt=self.ask,
                writeRefCon=action))
        for name, read in (("instances", lambda _: len(self.shadows)), ("loaded", lambda _: self.version),
                           ("errors", lambda _: self.errors), ("ticks", lambda _: self.ticks),
                           ("moves", lambda _: self.moves), ("wet", lambda _: self.wet)):
            self.refs.append(xp.registerDataAccessor(f"{LAB}/{name}", xp.Type_Int, 0, readInt=read))
        for name, read in (("ground_m", lambda _: self.ground_m),
                           ("frame_ms_median", lambda _: self.frame_ms(0.5)),
                           ("frame_ms_p99", lambda _: self.frame_ms(0.99)),
                           ("frame_ms_max", lambda _: self.frame_ms(1.0)),
                           ("update_us_mean", lambda _: sum(self.updates) / len(self.updates) if self.updates else 0.0),
                           ("update_us_max", lambda _: max(self.updates, default=0.0))):
            self.refs.append(xp.registerDataAccessor(f"{LAB}/{name}", xp.Type_Float, 0, readFloat=read))
        self.floop = xp.createFlightLoop(self.loop, xp.FlightLoop_Phase_BeforeFlightModel, None)
        xp.scheduleFlightLoop(self.floop, -1)

    def read_value(self, name):
        return self.values[name]

    def write_value(self, name, value):
        self.values[name] = value

    def ask(self, action, value):
        """Writes come at any moment; the work happens in the flight loop."""
        self.pending.append((action, int(value)))

    def frame_ms(self, fraction):
        if not self.frames:
            return 0.0
        ordered = sorted(self.frames)
        return ordered[min(len(ordered) - 1, int(fraction * len(ordered)))]

    def reset_stats(self, _):
        self.frames = []
        self.updates = []

    def load(self, n):
        self.version = 0
        self.clear(0)
        for obj in self.objects.values():
            xp.unloadObject(obj)
        self.objects = {}
        for kind in KINDS:
            name = (f"post{n}" if kind == "post" else f"sky{n}_{kind[4:]}" if kind.startswith("sky_")
                    else f"shadow{n}_{kind}")
            path = LAMINAR.get(kind, f"{self.folder}/{name}.obj")
            xp.loadObjectAsync(path, self.loaded, (n, kind))

    def loaded(self, obj, ref):
        n, kind = ref
        if obj is None:
            xp.log(f"shadowlab: could not load version {n} {kind}")
            self.errors += 1
            return
        self.objects[kind] = obj
        if len(self.objects) == len(KINDS):
            self.version = n
            xp.log(f"shadowlab: version {n} loaded")

    def ground(self, lat, lon):
        """Local x, ground y, z under a place. The probe needs a y: any will do for a ProbeY."""
        x, y, z = xp.worldToLocal(lat, lon, 0.0)
        info = xp.probeTerrainXYZ(self.probe, x, y, z)
        self.ground_m = xp.localToWorld(info.locationX, info.locationY, info.locationZ)[2]
        self.wet = int(info.is_wet)
        return x, info.locationY, z

    def put(self, shadow, probe=True):
        if probe:
            x, y, z = self.ground(shadow.lat, shadow.lon)
            y += self.values["agl_m"]
            shadow.alt = xp.localToWorld(x, y, z)[2]
        else:
            x, y, z = xp.worldToLocal(shadow.lat, shadow.lon, shadow.alt)
        xp.instanceSetPosition(shadow.inst, (x, y, z, 0.0, 0.0, 0.0))

    def place(self, _):
        v = self.values
        obj = self.objects[KINDS[int(v["kind"])]]
        lat, lon = xp.getDatad(self.lat), xp.getDatad(self.lon)
        cos_lat = math.cos(math.radians(lat))
        psi = math.radians(xp.getDataf(self.psi) + v["bearing_deg"])
        fe, fn = math.sin(psi), math.cos(psi)  # forward, as east and north
        re, rn = math.cos(psi), -math.sin(psi)  # right
        n = int(v["count"])
        if v["grid"]:
            side = math.ceil(math.sqrt(n))
            spots = [((i % side - (side - 1) / 2.0) * v["spacing_m"],
                      (i // side - (side - 1) / 2.0) * v["spacing_m"] + v["dist_m"]) for i in range(n)]
        else:
            spots = [((i - (n - 1) / 2.0) * v["spacing_m"], v["dist_m"]) for i in range(n)]
        now = time.perf_counter()
        for k, (across, along) in enumerate(spots):
            east = re * across + fe * along + v["off_e_m"]
            north = rn * across + fn * along + v["off_n_m"]
            shadow = Shadow(xp.createInstance(obj), lat + north / M_PER_DEG,
                            lon + east / (M_PER_DEG * cos_lat), now + k * v["period_s"] / n)
            self.put(shadow)
            xp.instanceSetAutoShift(shadow.inst)
            self.shadows.append(shadow)
        xp.log(f"shadowlab: placed {n} {KINDS[int(v['kind'])]} at ground {self.ground_m:.0f} m, wet {self.wet}; "
               f"total {len(self.shadows)}")

    def clear(self, _):
        for shadow in self.shadows:
            xp.destroyInstance(shadow.inst)
        self.shadows = []

    def advance(self, shadow, metres):
        bearing = math.radians(self.values["move_bearing_deg"])
        shadow.lat += metres * math.cos(bearing) / M_PER_DEG
        shadow.lon += metres * math.sin(bearing) / (M_PER_DEG * math.cos(math.radians(shadow.lat)))
        self.moves += 1

    def step(self, metres):
        for shadow in self.shadows:
            self.advance(shadow, metres)
            self.put(shadow)

    def move(self, now):
        """Every instance whose period is over: a slice of them per frame."""
        v = self.values
        moved = False
        for shadow in self.shadows:
            elapsed = now - shadow.last_move
            if elapsed >= v["period_s"]:
                # last_move starts staggered at placing, so these come a few per frame.
                self.advance(shadow, v["speed_ms"] * elapsed)
                self.put(shadow, bool(v["probe_moves"]))
                shadow.last_move = now
                moved = True
        return moved

    def move_all(self, now):
        """All together, at the same instant."""
        v = self.values
        if now - self.last_all < v["period_s"]:
            return False
        elapsed = v["period_s"]
        self.last_all = now
        for shadow in self.shadows:
            self.advance(shadow, v["speed_ms"] * elapsed)
            self.put(shadow, bool(v["probe_moves"]))
            shadow.last_move = now
        return True

    def cam(self, on):
        if not on:
            xp.dontControlCamera()
            self.camera_at = None
            return
        v = self.values
        first = self.shadows[0]
        self.ground(first.lat, first.lon)
        bearing = math.radians(v["cam_bearing_deg"])
        cos_lat = math.cos(math.radians(first.lat))
        self.camera_at = (first.lat + v["cam_back_m"] * math.cos(bearing) / M_PER_DEG,
                          first.lon + v["cam_back_m"] * math.sin(bearing) / (M_PER_DEG * cos_lat),
                          self.ground_m + v["cam_up_m"],
                          -math.degrees(math.atan2(v["cam_up_m"], v["cam_back_m"])),
                          (v["cam_bearing_deg"] + 180.0) % 360.0)
        xp.controlCamera(xp.ControlCameraForever, self.camera)

    def camera(self, position, losing, _):
        if losing or position is None or self.camera_at is None:
            return 0
        lat, lon, alt, pitch, heading = self.camera_at
        position[0], position[1], position[2] = xp.worldToLocal(lat, lon, alt)
        position[3], position[4], position[5], position[6] = pitch, heading, 0.0, 1.0
        return 1

    def loop(self, since_last, *_):
        self.ticks += 1
        if since_last > 0.0:
            self.frames.append(since_last * 1e3)
        try:
            while self.pending:
                action, arg = self.pending.pop(0)
                action(arg)
            if self.values["speed_ms"] and self.shadows:
                t0 = time.perf_counter()
                moved = self.move(t0) if self.values["spread"] else self.move_all(t0)
                if moved:
                    self.updates.append((time.perf_counter() - t0) * 1e6)
        except Exception:
            self.errors += 1
            xp.log("shadowlab: " + traceback.format_exc())
        return -1

    def stop(self):
        xp.dontControlCamera()
        self.clear(0)
        for obj in self.objects.values():
            xp.unloadObject(obj)
        xp.destroyFlightLoop(self.floop)
        xp.destroyProbe(self.probe)
        for ref in self.refs:
            xp.unregisterDataAccessor(ref)


class PythonInterface:
    def XPluginStart(self):
        self.lab = Lab()
        return "xp-gliding shadow lab", "jlgabriel.xp_gliding.shadowlab", "Draped shapes through instances."

    def XPluginStop(self):
        self.lab.stop()

    def XPluginEnable(self):
        return 1

    def XPluginDisable(self):
        pass

    def XPluginReceiveMessage(self, inFromWho, inMessage, inParam):
        pass
