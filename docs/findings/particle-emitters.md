# What X-Plane 12's particle emitters do, found by building clouds

Found in X-Plane 12.4.3 under Vulkan, in November 2026, by building cumulus clouds from instanced objects that hold a particle emitter and no geometry. The method works, and each cloud can be driven on its own. Almost everything here was judged by eye from screenshots, usually in a single flight. Only the cost is a timed measurement, and it does not cover the settings a full scene would use.

| Question | Answer | Evidence |
| --- | --- | --- |
| **Does an instanced object with an emitter and no geometry work?** | Yes, loaded with `loadObjectAsync` | No crash in any flight of the series |
| **Can each instance be driven on its own?** | Yes, through a dataref of the instance in a slot of the emitter's tables. Two values together worked | Screenshots |
| **What happens when an instance is destroyed?** | Its particles go at once | Screenshots |
| **Does it emit out of view?** | Yes | One cloud placed behind the glider had filled when looked at |
| **How far is it drawn?** | Seen at 35 km with `ATTR_LOD 0 40000` | Screenshots |
| **Does a limit apply to emitters?** | None seen with 100. `MAX_PARTICLES` seems to apply per emitter | By eye |
| **Does the sim's wind carry particles?** | With drag 1, yes. With drag 0 they stay where they were emitted | By eye, no repeats on record |
| **Which wind, when it changes with height?** | They appear to move at about the wind at the aircraft, not at their own height | An inference from screenshots, in speed shear only |
| **What do 200 of them cost?** | Nothing that can be told from the noise on the GPU estimate, and up to about 1 ms per frame on the main thread | Timed, at a 60 fps cap, with drag 0 and no wind |
| **Does the graphics menu change them?** | Not between the two ends compared, with Cloud Quality at Low in both | By eye, one paused flight |
| **In what order are instances drawn?** | In the reverse of the order they were created, whatever their distance: the oldest last, on top. Setting a position again does not change it | Screenshots of tinted clouds, one look per case |

## How it was tested

| Item | Value |
| --- | --- |
| Simulator | X-Plane 12.4.3 (Vulkan), Windows 11 |
| Glider | Laminar Schleicher ASK 21 |
| Flying | A scripted autopilot through X-Plane's local web API, unless a result says by hand |
| Site | Over Hobbs, New Mexico (KHOB), flat terrain, unless a result says otherwise |
| Graphics | The scripted flights ran at the low end of the graphics menu |
| Reading | Screenshots compared by eye, from the aircraft unless a result says otherwise |

The flights logged no particle data. Where a result says where a cloud is, it comes from a screenshot or from the emitter's position, never from the particles themselves.

The tools are [`tools/cloudlab/`](../../tools/cloudlab/), a small plugin that places test emitters and the scripts that drive it, [`fly_clouds.py`](../../tools/testpilot/fly_clouds.py) for the cost and the draw order in flight, [`make_order.py`](../../tools/cloudlab/make_order.py) for the tinted clouds of the draw order, and [`fly_wind.py`](../../tools/testpilot/fly_wind.py) for the shear. The flight logs and screenshots are not in the repository.

**The object tested.** The technique comes from Alex Ferrer's [xplane_thermals](https://github.com/alexferrer/xplane_thermals) plugin, which draws its cumulus as an almost empty object holding one particle emitter, instanced at cloud base over each thermal. The object, particle system and texture tested here are separately authored, so the results below describe them and not that plugin's clouds. [`make_cloud_objs.py`](../../tools/make_cloud_objs.py) writes them. No public specification of the particle system file format was found. The OBJ8 directives are in Laminar's [file format specification](https://developer.x-plane.com/article/obj8-file-format-specification/), and the concepts in its [particle system article](https://developer.x-plane.com/article/x-plane-11-particle-system/), written for X-Plane 11.

| Part | Value |
| --- | --- |
| Object | `POINT_COUNTS 0 0 0 0`, `ATTR_LOD 0 40000`, one `EMITTER` |
| Particle types | A flat grey base, a white body and small bright tops |
| Particles alive at the steady rate | 60, 180 and 80, 320 in all |
| Particle life | 180 s ± 20% |
| Billboard size | 210, 200 and 130 m |
| Motion | No initial speed, gravity or turbulence. Drag 1 in the current object, 0 in the first tests |
| Shape | The emitter's random offsets (`DX`, `DY`, `DZ`), up to 425 m to the side and 480 m above the base at scale 1 |
| Values per instance | Rate (0 stops feeding, 1 is steady, up to 20 fills it fast) and scale (1 is the object's size, up to 2) |

## What an emitter can do

Each of these was found by looking at screenshots of a test flight with `tools/cloudlab/`.

**Driving each instance.** A slot of an emitter's table can be a dataref of the instance, and it follows the value given to `instanceSetPosition`, per instance, in flight. Rate 0 shows nothing, and raising it builds the cloud. Two such values worked together, rate and scale.

The generator's record adds that a dataref in a slot must exist when the object loads, so it is registered at the plugin's start and the objects load later, in the flight loop. How it fails otherwise is not recorded.

**Destroying an instance.** Its particles go at once.

**Out of view.** A cloud placed behind the glider had filled when looked at, so an emitter feeds while the camera faces away.

**Distance.** Seen at these distances with `ATTR_LOD 0 40000`:

| Distance | Seen |
| --- | --- |
| 8, 15 and 25 km | Clearly, with haze |
| 35 km | Small |

**How many.** No limit was seen with 100 emitters. The later cost flights ran with 193 to 222 instances, and no limit was looked for in them.

**`MAX_PARTICLES`** seems to apply per emitter, not to a particle type overall: 6 clouds with a limit of 60 were each thick. This was judged by eye, and particles were not counted.

**Fewer particles far away.** At 15 km, a cloud with 30% of its particles looks about the same, by eye. That is the only distance on record.

**Puffs and their texture cells.** A puff cut off by the edge of its cell shows as a straight line from close up, seen by flying through a cloud. The texture now fades each puff out inside its cell. No flight checking that fix is on record.

**Creating instances.** X-Plane's log says that creating them in a post-flight-loop callback is discouraged. The lab's callback ran after the flight model and its clouds still drew. No other effect is on record.

**Loading.** The documentation warns (XPD-16090) that loading an object with an emitter in `XPluginStart` or `XPluginEnable` can crash the simulator. That was not tested here: all loading was from the flight loop.

## Draw order

X-Plane does not sort particles between instances. It draws instances in the reverse of the order they were created: the newest first, underneath, and the oldest last, on top. So a far cloud created before a nearer one in the same direction is drawn over it, with a sharp edge and the haze of its own distance, and from the seat it looks like a small cloud stuck on the face of a big one. Laminar's particle article, the OBJ8 specification and the XPLMInstance page say nothing about sorting or depth for particles.

Tested with copies of the cloud object tinted red and blue, so that which one is in front can be read from a screenshot. Two or three clouds were placed ahead of the glider, 2.5 to 7 km away, overlapping in view, created in different orders, and photographed 14 s later. One look per case:

| Case | Seen |
| --- | --- |
| Near created first, then far | The far cloud hidden behind the near one |
| Far created first, then near | The far cloud drawn over the near one |
| Three clouds, in four orders of creation | Each time the first created on top and the last underneath |
| One particle type per cloud instead of three | The same |
| The far cloud's position set again after both were created | No change |
| A third instance created first, then destroyed, then the far cloud created | The far cloud underneath: a new instance does not take the place of a destroyed one |
| The far cloud destroyed and created again in the same place | It refilled underneath |
| One object with two emitters 6 km apart, listed in either order | The same emitter on top both times. It was listed after the other in the particle system file and used later particle types; which of the two decides was not separated |

Instances of different objects followed the order of creation together.

**Working with it.** The order is fixed when an instance is created, and moving an instance keeps its place, so a plugin can choose it. One way, used here: at the start, before any cloud, make idle instances for rings of distance around the aircraft, the nearest ring first, and give each cloud an idle instance of its ring. A nearer ring is then always drawn over a farther one. When the aircraft's moves take a cloud into another ring, an instance of the new ring starts feeding in the same place and the old one stops, and goes back to its ring once its particles have died. Over one particle life the old particles keep their old place in the order, so after a cloud comes nearer, clouds of its new ring a little farther away showed over it for minutes. Filling the new instance fast when a cloud comes nearer covers the old particles within seconds, at the cost of a cloud up to twice as dense until they have died. Within a ring the order is only right when a cloud comes in.

Drawing a far cloud again whenever a nearer one in front of it was created after it was tried first and dropped: a cloud drawn again goes under everything, also under the clouds beyond it, and fixing those in turn took around a hundred new instances a minute when flying straight.

## Wind

Laminar's article describes drag as how fast particles slow to "the speed of the outside air", and does not say that this includes the sim's wind, so it was tried.

### Uniform wind

A straight flight across the wind. With drag 0, particles stay where they were emitted, so a moving emitter leaves a trail, of about 2 km at 25 kt.

| Emitters | Drag | Wind | What it looks like after about 210 s |
| --- | --- | --- | --- |
| Moving with the wind | 0 | 25 kt | Clouds merged in a bank along the wind: the trail |
| Still | 1 | 25 kt | Round at 30 s, then one continuous band along the wind |
| Moving with the wind | 1 | 25 kt | Separate, compact clouds, as in calm air |
| Moving with the wind | 1 | 5 to 50 kt from 500 to 12000 ft above the field (16–19 kt at the glider) | Separate, compact clouds |

The second row is the direct result: emitters that do not move, and particles that do. All of it was judged by eye on screenshots, at low graphics settings, with no repeats on record. Only drag 0 and 1 were tried.

### Wind that changes with height

If particles moved at the wind at their own height, emitters moving at the wind at the glider would leave them behind, and a cloud would stretch by the difference × the particle's life. These flights looked for that stretch.

Straight across a wind from the west, starting at 800 m above the ground and sinking to about 530 m, for 280 s, with screenshots ahead at 30, 120, 200 and 280 s. The clouds' base was at 1500 m above the ground. Particles live 180 s on average, so 200 s is long enough for a stretch to have grown. The gentle profile is 9 to 15 kt from 500 to 1500 m, and the strong one 5 to 50 kt from 500 to 12000 ft.

| Wind | Emitters move at (m/s) | Wind at the base (m/s) | Stretch expected by that arithmetic (m) | Seen |
| --- | --- | --- | --- | --- |
| Uniform 15 kt | 7.7 | 7.7 | 0 | Separate clouds. The control, with no camera log |
| Gentle | 5.4 to 4.7, the wind at the glider | 7.7 | 410–540 | Looks like the control. One far cloud, gentle and uniform, in pixels at about 10 m each: 68 and 70 wide at 120 s, 83 and 83 at 200 s, 102 and 96 at 280 s, where the arithmetic adds about 50 pixels |
| Strong | 5.6 to 4.5, the wind at the glider | About 12, from the layers asked for | About 1300 | Still compact. At 200 s, a cloud 3.6 km away reaches 540–580 m west of its emitter and 370–580 m east, about what the object draws at that size (560 m each way) |
| Gentle | 7.7, the wind at the base | 7.7 | 0 | At 200 s, a cloud 3.7 km away reaches 900–980 m west of its emitter and 240–370 m east: about 300 m upwind, the only flight with a visible displacement |

**Interpretation, not a measurement:** the particles appear to move at about the wind at the aircraft, whatever their height. With 7 m/s between the emitters and the wind at the clouds' height, nothing moved as that wind would have moved it. In the last row, the emitters would run ahead of the particles at about 2.7 m/s, or about 490 m over a particle's life, and a displacement upwind is what was seen, smaller than that.

The limits of this are large:

- **Few samples.** Screenshots from one direction at four moments, with no sequence seen in motion.
- **Coarse reading.** The clouds are irregular and overlap, so the reading is good to 100–150 m, and only for the few standing clear of others: one near cloud and one far one.
- **Missing logs.** The first two flights have no camera log, so the gentle flight was compared with the control by width only, and its displacement from the emitters was not measured.
- **No strong control** with the emitters at the wind at the base.
- **One kind of shear.** Speed shear from one direction, with the glider between 530 and 800 m above the ground, so "at the aircraft" rests on winds near 5 m/s and was not tested by changing the glider's height a lot.
- **Aircraft or camera.** X-Plane could be reading the wind at either. Every shot was from the aircraft, and a chase or tower view was not tried.

## Cost

Straight flight by script, clouds off and on in alternating blocks of 90 s, a 60 fps cap, about 200 clouds, about 25 000 particles by rate × life, with far clouds at 30% of their particles beyond 8 km. `frame_us` is the plugin's own smoothed cost per frame. The GPU time is X-Plane's own estimate, which X-Plane's dataref list calls "for entertainment value only".

| Clouds | Shown | frame_us, median | frame_us, p99 | fps | GPU (ms) | Main thread (ms/s) |
| --- | --- | --- | --- | --- | --- | --- |
| Off | 0 | 113 | 142 | 59.8 | 5.57 | 394 |
| On | 193 | 156 | 182 | 59.9 | 5.55 | 452 |
| Off | 0 | 157 | 214 | 59.9 | 5.50 | 409 |
| On | 222 | 118 | 176 | 59.9 | 5.56 | 415 |
| Off | 0 | 128 | 172 | 59.9 | 5.53 | 408 |
| On | 207 | 134 | 190 | 59.9 | 5.52 | 441 |

The GPU estimate does not move between blocks. The main thread may use up to about 60 ms/s more with the clouds on, up to 1 ms per frame, which is near the noise, with no effect at this frame rate. The estimate does respond to these clouds: flying through one in the lab took it from 7.7 to 8.7 ms, the worst case seen.

These flights do not settle the cost:

- **The 60 fps cap** would hide a small cost in the frame rate.
- **The low end of the graphics menu.** The costs say little about a full scene.
- **Drag 0 and no wind.** Whether drag 1 costs anything was not measured.
- **One machine.** None of this was flown on a weaker one.

## Graphics settings

Flown by hand over Santiago, Chile, and paused, at about 650 m above the ground and 828 m below the clouds' base, with seven screenshots in outside views all around at each setting, compared by eye view by view.

| | Low | High |
| --- | --- | --- |
| Cloud Quality | Low | Low |
| Shadow Quality | Aircraft Only | Low |
| World Objects Density | Minimal | Maximum |
| Vegetation Density | Minimal | Minimal |
| Rendering Distance | Minimal | Maximum |
| `sim/private/controls/reno/LOD_bias_rat` | 5.0 | 1.0 |
| Cloud instances, the plugin's count | 208 | 208 |

The same clouds stood in the same places in each pair of views, small ones near the horizon included. The ground changed a lot: no city, roads or trees at Low. The Low column is from a screenshot of the menu. The High column is the menu as shown before the flight, taken as what it went back to, though the ratio did read 1.0.

**An emitter did not follow the distance rule seen with plain geometry.** A disc with the same `ATTR_LOD 0 40000` stopped drawing between 4 and 8 km with this ratio at 5, which fits 40 km / 5. Clouds show no such limit at 5: the ones low over the horizon stand about 2° above it, which at 828 m below their base would be some 20 km. That distance is a rough figure from an assumed field of view.

Only that one `ATTR_LOD` value is on record, so nothing here says whether it has any effect on an emitter. Not tested: which slider moves the ratio (they moved together), settings between these two, Cloud Quality itself, X-Plane's own clouds, and frame cost. Some high views look slightly lighter, perhaps exposure over the darker city, which was not measured.

## Other things seen

Each of these is one look, judged by eye. The first two come from straight flights of 90–150 s at the low end of the graphics menu, in a sky still filling.

**Next to X-Plane's own cumulus.** With a layer at 50% cover and its base 318 m above these clouds, both drew together, these in front, with no fault of order seen. Flying in or close to an X-Plane cloud was not tried, nor a layer at the same height.

**At dusk.** The particles have `DIFFUSE` and `AMBIENT` of 1.2 and no emissive part.

| Local time | Sun | Clouds |
| --- | --- | --- |
| 17:00 | −0.9° | Pink, darker below, against a graded sky |
| 18:00 | −13.2° | Nothing to see: the whole picture is black but for stars and a few lights. These clouds do not glow |

Nothing between these two was looked at, nor dawn, nor a low sun in front of the clouds. At noon, a value of 1.0 looked grey, which is why it is 1.2.

**Shadows.** Particles do not seem to cast one on the ground. No test aimed at this is on record.

**Inside a cloud,** in a hand flight over Santiago. Far clouds were drawn bright and sharp over the fog of the cloud the glider was in. Near some clouds there were large, smooth, pale shapes, perhaps particles fading near the camera. Neither is explained.

**Twice the sim's speed.** For 40 s at `sim/time/sim_speed` 2, clouds kept filling and frames were normal. Whether particles live half as long in real time was not checked.

## Limits

- **Mostly by eye.** Only the cost is timed. The rest is screenshots, usually of one flight, with no particle count behind them.
- **The fading of a cloud was not measured.** Stopping the rate should remove a cloud over 144 to 216 s, from the particle's life. That is a schedule. In one hand flight the pilot could not be sure that a cloud had shrunk.
- **A shift of X-Plane's local origin:** one, flying east in calm air. Instances here use `instanceSetAutoShift`, and the particles already in the sky stayed in place, by eye: the same clouds 13 s before and 1 s after it, and a marker placed through `worldToLocal` under the cloud ahead 10 s after. Not looked at: north or south, in wind, or in a climb. See [the record](../../notes/phase4.md#a-shift-of-x-planes-local-origin).
- **Time acceleration** above 2× was not tried.
- **Only one object design:** long-lived billboards with no speed and no gravity, at cloud sizes. A smaller or faster effect may behave differently.
- **The draw order was seen with up to three clouds in the lab,** and with about 200 to 400 instances only through the result: near clouds in front once instances were made in that order. Additive and pre-multiplied blending were not tried.
- **Only X-Plane 12.4.3 under Vulkan on Windows,** on one machine.
- **Laminar's article does not describe** the wind behaviour above, so a later version could change it without contradicting anything documented.

## What it means in practice

- **Create instances before the flight model,** as X-Plane's log asks.
- **To drive many effects from one object,** put a dataref of the instance in a slot of the emitter's tables, register it at plugin start, and load the object with `loadObjectAsync` from the flight loop.
- **To remove an effect gently,** set its rate to 0 first, and destroy the instance only after the longest particle life, since destroying it removes the particles at once.
- **To fill a sky quickly,** emit at a high rate for a short time. Twenty times the steady rate gives this cloud its particles in 9 s, by rate × life, and emitters feed out of view.
- **For an effect that should keep its shape in wind,** use drag 1, the only value above 0 tried, and move the emitter at the wind at the aircraft. Moving it at another wind displaced the cloud in the one flight that tried it.
- **To save particles far away,** 30% was enough at 15 km, by eye.
- **Do not take a distance limit measured on geometry as true for an emitter,** or the reverse.
- **Do not read the cost from the frame rate under a cap.** Compare the GPU estimate and the main thread's time, and expect noise.
- **Fade each puff inside its texture cell,** or its edge shows from close up.
- **Create instances in the order they should be drawn:** what is to be on top first. Moving an instance does not change its place, and a new one always goes underneath, so make the instances for near effects in advance and reuse them.

## Full record

The working notes hold the record and the reasoning: [what X-Plane does with an emitter](../../notes/phase2.md#what-x-plane-does-with-an-emitter), [the cost](../../notes/phase2.md#cost), [clouds in wind](../../notes/phase3.md#clouds-in-wind), [which wind carries the sky in shear](../../notes/phase3.md#which-wind-carries-the-sky-in-shear), [the disc and its distance limit](../../notes/shadows.md#other-findings), [next to X-Plane's clouds and at dusk](../../notes/phase4.md#next-to-xp12s-clouds-and-at-dusk), [the graphics menu](../../notes/phase4.md#does-the-graphics-menu-change-the-sky) and [the order clouds are drawn in](../../notes/phase4.md#the-order-clouds-are-drawn-in).
