# Cloud shadows on the ground: a lab test

Can a cloud's shadow be drawn on the ground from XPPython3, and what does it cost? Measured on 2026-11-06 in X-Plane 12.4.3 under Vulkan, with `tools/shadowlab/`. See "Cloud shadow" in [SPEC.md](SPEC.md).

**Status:** closed by Juan Luis's decision, 2026-11-06. Neither method is a good fit for the plugin, so a visible shadow is set aside. Nothing in `xp_gliding/` changed.

## Answer

- **A draped shape through XPLMInstance does not draw at all.** The object loads, the instance exists and any normal triangles in the same object appear, but the draped triangles are missing.
- **Hidden geometry in the sky does cast X-Plane's own shadow,** in the right place, over land and water, and it moves. By default it reaches only about 250 m from the camera, which is useless from a glider. It reaches about 16 km only after raising two private, global datarefs, and it looks wrong for a cloud: nearly black with a sharp edge.

## What was asked and what was seen

Judged by eye from screenshots read at reduced size. A control post, a tall red prism with no draped part, marks each spot.

| Question | Observed | Limits of the method |
| --- | --- | --- |
| Does a draped instance draw on flat ground (KHOB)? | No. The 1 km quad, in strong red so it could not be missed, did not appear from the forward view or from 1.4 km above. The post did | One position, midday, one graphics setup |
| On rough ground (Santiago)? | No, same result, 7 km ahead of the glider | On the valley floor at 620 m, not on a slope. Since nothing drew, slope, water and objects were not judged for this method |
| Is the object badly written? | Unlikely. The same quad without `ATTR_draped` draws, as a soft red disc. A copy of the line order of Laminar's `gnd_grass_12x30.obj` draws nothing, at 1 km or at 30 m. An object with both kinds of triangle, in the order of Laminar's grandstands, draws only the normal ones | Not tried: the same object placed in a DSF, which would need a scenery package and a tool we don't have installed |
| Do Laminar's own draped objects work through an instance? | The baseball grandstand drew its stands, with no draped field. The grass patch, only draped triangles, did not appear | These objects were not seen in a DSF for comparison, so that they drape there is assumed |
| Does Laminar say? | No. The XPLMInstance page is silent on draping. The OBJ8 page describes draping "for scenery objects in a DSF" and does not state a limit | Only the first 40% of the OBJ8 page was read word for word |
| Does geometry in the sky cast a shadow? | Yes, on the terrain and on water, from a grey disc and from one with 3% alpha and `ATTR_shadow_blend` | Few sites and sun angles |
| Is it where the sun puts it? | Yes, at the post's foot, placed with height / tan(`sun_pitch_degrees`) towards `sun_heading_degrees` | By eye. Heading came as -172 at KHOB, so it can be negative. Both datarefs are in `DataRefs.txt` |
| How far from the camera does it reach by default? | Clear at 100 m, fading at 200 m, gone by 400 m, with `shadow/csm/far_limit_exterior` and `far_limit_interior` both at 250 | Camera 30 degrees above the ground, 100 m disc 60 m up |
| Does a disc high up shadow the ground by default? | No: a 100 m disc at 1200 m gave nothing with the camera 100 m and 200 m from the spot | Whether that is the height or the distance along the sun's ray was not separated |
| With the limits raised to 20 km? | The hidden disc at 1200 m shows at 2, 4, 8 and 16 km and not at 32 km, with `ATTR_LOD` 200 km | Private datarefs, global to the simulator, reset on restart. Only 20 km was tried |
| From the seat? | Only with `far_limit_interior` raised too: the forward and cockpit views read that one, outside views the other. Seen from the cockpit 30 degrees off the nose | The panel hides shadows straight ahead and below. Panel shading looked the same at both limits at midday, not studied further |
| Does it follow rough ground? | No shadow was seen on a slope: the disc tried at Santiago stayed on the valley floor | Not answered for hills |
| Does it move? | Yes. Moved once a second at 50 m/s keeping its altitude, the shadow went east along the valley in screenshots 15 s apart, with no stale copy | Shots 15 s apart cannot show flicker or small jumps. Nobody watched it live |
| Is the disc really hidden? | From below, yes: nothing visible against the sky. From above, no: see below | One view each |

### Defects of the hidden disc

- **It writes depth.** With the 3% alpha disc and with 1%, the terrain behind it looks like a haze-free window, and the shadow is cut where the line of sight passes through the disc, with a stepped edge. From below neither shows.
- **It can hide what is behind it.** A gap appeared in the post at the disc's height, seen nearly edge-on, which is most likely the disc. Our particle clouds behind it were not tried.
- **`ATTR_no_depth` and `ATTR_draw_disable` remove the shadow too,** so those do not fix it.
- **The shadow is hard.** Nearly black with a sharp edge, far from the soft shade of a cumulus. Softening it was not tried.

The disc would have to sit above any viewer, perhaps at the cloud's top, for these to matter less. That was not tested.

## Cost

Only for the hidden discs, since a draped instance draws nothing. Straight flight at KHOB at 2800 m, forward view, the plugin's clouds off, 60 s per block, with the method of `fly_clouds.py cost`. Stopped early once the method was set aside: 20 discs, values from two full rounds, and **200 discs were not measured**. In the round cut short only the first block finished: GPU 5.98 ms, main thread 401 ms/s.

| Block | GPU (ms) | Main thread (ms/s) | Worst frame (ms) | Python, a frame that moves (µs) |
| --- | --- | --- | --- | --- |
| No discs, limit 250 m | 5.45, 5.90 | 415, 407 | 40.7, 34.9 | |
| No discs, limit 20 km | 5.50, 5.89 | 417, 402 | 23.3, 25.9 | |
| 20 discs still, limit 20 km | 4.13, 5.43 | 417, 416 | 27.5, 29.3 | |
| 20 discs moved, a slice a frame, limit 20 km | 5.52, 5.91 | 418, 406 | 30.8, 44.2 | mean 10, max 48 |

**No cost shows above the noise with 20 discs,** either from the raised limit or from the discs, moved or not. Moving them costs about 10 µs of Python in a frame that moves any. That is weak evidence: the frame was held at 16.66 ms by the 60 Hz cap, the GPU estimate varied by more than any difference here (4.13 to 5.98 ms), and the worst frame comes from one sample. The shadows were not checked on screen during these blocks, and a wider shadow range may matter more over scenery with many objects, which KHOB does not have.

## Other findings

- X-Plane's `sim/private/controls/reno/LOD_bias_rat` is 5 here. An object with `ATTR_LOD 0 40000` stopped drawing between 4 and 8 km from the camera, which fits 40 km / 5. This matters for any object of ours, and depends on the graphics settings.
- Flight loops run while the sim is paused, so instances can be placed and moved with the glider held still. `xp.controlCamera` gives a fixed outside view for screenshots, which is what `fly_shadow.py` uses.

## Why it is set aside

The method depends on private datarefs that change every shadow in the simulator and may change in any version, which a published plugin should not do. It also needs a look it does not have, and its artefacts may affect our clouds. One way is still untried: a mesh of quads fitted to the terrain with probes, not draped. It is more work and its look is unknown, and the air and the clouds matter more for finding thermals, so it stays unstarted.

## Running it

```bash
python tools/shadowlab/fly_shadow.py install --sky-lod 200000
python tools/testpilot/restart_xplane.py
python tools/shadowlab/fly_shadow.py start --at=khob --msl 2200
python tools/shadowlab/fly_shadow.py do load=1
python tools/shadowlab/fly_shadow.py sky --kind hidden --height 1200 --limit 20000
python tools/shadowlab/fly_shadow.py cost --sky --count 20
python tools/shadowlab/fly_shadow.py uninstall
```

The install copies only the lab's file and folder, never `xp_gliding`. A flight must be loaded before the lab's datarefs exist, and X-Plane must be restarted for an uninstall to take effect.
