# Phase 3: wind

The wind is X-Plane's. The plugin reads it and writes none. This records the first step of [the design](SPEC.md#wind), the wind carrying the sky, flown by the test pilot on 2026-11-05 at KHOB in the Laminar ASK 21 (`tools/testpilot/fly_wind.py`, `tools/cloudlab/fly_drag.py`), and then [by hand](#first-flight-by-hand) the same day: staying in a thermal is done, finding one by its cloud is not. The second step, [the lean](#the-lean), is built and checked by the test pilot, and nobody has flown it by hand.

## What was built

- **`engine/wind.py`:** the offset between the ground and a frame that moves with the air, the wind integrated over the sky's clock, in degrees. The field is only asked about positions in the air's frame, and clouds and markers are drawn at their position plus the offset. With no wind the offset stays at exactly zero, so the sky is the same as before, thermal for thermal.
- **The wind used** is the one at the glider, `sim/weather/aircraft/wind_now_x_msc` and `_z_msc`, read every frame.
- **Clouds now move:** in wind each cloud gets a new position about once a second, a quarter of them in each update. In calm air none of this runs.
- **Particles have a drag** (`DRAG_CURVE` 1), so XP12's wind carries them after they are emitted (below).
- **Menu and HUD:** a switch, *Thermals follow the wind*, and the wind's arrow and speed on the HUD ([hud.md](hud.md)).

## `wind_now_*` is the wind that moves the glider

Straight flight, 40–60 s, with the difference between the glider's velocity over the ground and through the air (`measure`):

| Asked for (east, north, m/s) | `wind_now_*` | Ground minus air | The plugin's offset rate |
| --- | --- | --- | --- |
| 15 kt from 270: +7.72, 0.00 | +7.72, 0.00 | +7.72, −0.02 | +7.72, 0.00 |
| 25 kt from 135: −9.09, +9.09 | −9.09, +9.09 | −9.09, +9.11 | −9.09, +9.09 |

So it is the wind at the glider, and it points where the air is going.

## The same thermal in calm air and in wind

The mission picks the best thermal near the start from the plugin's own sky (`wide_carriers`, w\* 3, zi 2000 m), flies a line passing one turn radius to the right of it, rolls left abeam of it, and then holds 35° and 95 km/h with **no correction at all** for six turns. All its guidance is in the air's frame. The wind was uniform, from 270. The six-turn means, with the sink as lift minus climb:

| Wind | Climb, m/s | Lift at the glider, m/s | Sink, m/s | Centre of the circle from the thermal, m | Over the ground in 134 s |
| --- | --- | --- | --- | --- | --- |
| Calm | +0.38 | +1.88 | 1.50 | 56–112 | 114 m |
| 15 kt | +0.36 | +1.89 | 1.53 | 56–112 | 978 m |
| 25 kt | +0.14 | +1.67 | 1.53 | 64–134 | 1768 m |

- **At 15 kt the flight matches the calm one** turn for turn, within 0.02 m/s of climb.
- **At 25 kt the sink is the same,** so the wind costs the glider nothing by itself, and the climb is lower because the lift met is lower. That flight started from another point of the same thermal's history: it got there about a minute earlier and about 50 m higher, and its circle was a little further off centre, so this is not a measured loss from wind.
- The ground track is what the wind should give: 7.3 m/s against 7.7 at 15 kt, 13.2 m/s against 12.9 at 25 kt, over a circle that is not closed at the end of the sample.

Before this, a glider circling at 25 kt would have left a thermal in well under a minute.

## Clouds in wind

Particles of drag 0 stay where they were emitted, and they live about 3 minutes, so at 25 kt a moving emitter leaves a trail of about 2 km. Seen from the cockpit, after 225 s, the clouds ran together into one long flat bank along the wind.

Laminar's [particle article](https://developer.x-plane.com/article/x-plane-11-particle-system/) describes drag as how fast particles reach "the speed of the outside air" but does not say that this includes the sim's wind, so it was tried:

| Emitters | Drag | 25 kt | What it looks like after ~210 s |
| --- | --- | --- | --- |
| Moving with the wind | 0 | Yes | Clouds merged in a bank along the wind: the trail |
| Still (`wind_enabled` off) | 1 | Yes | Round at 30 s, then one continuous band along the wind: **the wind carries the particles** |
| Moving with the wind | 1 | Yes | Separate, compact clouds, as in calm air |
| Moving with the wind | 1 | Shear, 5 to 50 kt from 500 to 12000 ft above the field (16–19 kt at the glider) | Separate, compact clouds |

All judged by eye on screenshots, with low graphics settings. Which drag is enough, and whether 1 has a cost, was not explored.

In shear the particles travel at the wind of the clouds and the emitters at the wind of the glider. A difference of 2 m/s would stretch a cloud by about 360 m over a particle's life, and shift its body from its thermal by about half of that. Larger differences have not been looked at.

## First flight by hand

Juan Luis, 2026-11-05, KHOB, Laminar ASK 21: a uniform 15 kt from the north set by hand in XP12's weather, no turbulence or gusts, no XP12 clouds or thermals, `wide_carriers`, w\* 3, zi 2000 m, seed 1, markers on (`flightlog_20261105_175954.csv`). It started on the runway and was moved up with the map to about 950 m AGL. Told as it happened and measured from the log afterwards with `tools/flightlog/replay_sky.py`.

**The sky was rebuilt exactly.** That log had neither the day nor the offset, so the tool worked them out: day 302, and an offset of 1683 m south when the log began. With those, the rebuilt lift matches the logged lift within 0.01 m/s RMS, so what follows about the thermal and the circle is the sky that was flown. The flight log now records the day, seed, sky and offset, so this search is not needed again.

**Staying in a thermal: done.** It needed no special handling, and the two climbs below were flown by hand with the markers on, around a thermal with a core of 5.3–5.7 m/s:

| t_run (s) | Distance to centre, median and p10–p90 (m) | Lift (m/s) | Climb (m/s) | Sink (m/s) | Bank (deg) | Height gained (m) | Over the ground (m) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 600–690 | 188, 112–208 | 2.61 | +1.32 | 1.29 | 22 | +116 | 1022 |
| 780–870 | 188, 141–232 | 2.18 | +1.00 | 1.19 | 24 | +86 | 583 |

- **The glider travelled about 1 km over the ground in 90 s and stayed in the thermal.** Between the climbs it left the thermal and came back to it.
- **The roll on entry was felt, unprompted:** "it lifted the right wing a little". The log agrees: the thermal was 22–55° to the right of the nose, the right side's lift was up to 0.48 m/s more than the left's, and the roll moment reached −988 N m before the bank began.
- **Between clouds,** the air sank 0.13 m/s, against the −0.12 m/s from conservation of mass ([phase2.md](phase2.md#against-the-faas-handbook-and-a-narrower-sky)).

**The climb was less than this thermal offers,** because of the circle and not of the wind. Lift by distance from the centre, while the core was near its best:

| Distance (m) | 60–100 | 100–130 | 130–160 | 160–190 | 190–220 | 220–260 | 260–320 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Lift (m/s) | 4.95 | 4.45 | 3.40 | 2.40 | 1.66 | 0.87 | 0.04 |

By arithmetic, at 90 km/h with the sink of [hud.md](hud.md#the-instruments) and a centred circle: 22° gives a radius of 158 m and about +2.3 m/s, 35° gives 91 m and about +3.5 m/s. Not flown.

**A thermal dying, seen from inside.** Juan Luis saw the same column go red, orange, yellow and pale, with the height almost unchanged, and asked whether something was wrong. It was the life cycle, and the times agree with what was seen:

| t_run (s) | 790 | 880 | 898 | 940 | 980 | 1006 | 1014 | 1119 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Thermal | Decay starts | | Orange | Yellow | Pale | | No marker | Dies |
| Its cloud | No longer fed | About half gone | | | | Last particle | | |

The thermal lived 1097 s. Its core went from 5.3 to 2 m/s in about 190 s, which is what a pilot climbing in it meets, and whether that is too fast is for flying to say: the first impression was only surprise. **Its cloud's times are the model's schedule, not a measurement:** particles are not logged. By that schedule the cloud leads the lift, as it should: half gone before the marker turns orange, and gone when the core is about 1.4 m/s. By eye, Juan Luis could not be sure that it had shrunk. The large cloud still overhead at the end, with a column in it, was another thermal's, 280 m away, with a core of 2.2 m/s.

**A bigger cloud meant a weaker thermal, which a pilot would not expect.** That neighbour's cloud was much larger than the one over the 5.7 m/s thermal, and it was not a coincidence. A cloud's size followed the thermal's `rgain`, and in Allen's model a wider thermal has slower air. Offline, over 1012 thermals at full strength (5 seeds, 2 places, 1000 m AGL, `wide_carriers`), the correlation between size and core was −0.75:

| Cloud scale | Thermals | Core, median and p10–p90 (m/s) | Core radius (m) |
| --- | --- | --- | --- |
| Under 0.8 | 12 | 5.4, 4.9–5.8 | 79 |
| 0.8–1.0 | 276 | 3.8, 3.2–4.9 | 107 |
| 1.0–1.2 | 529 | 2.8, 2.3–3.6 | 134 |
| 1.2 and over | 195 | 2.2, 1.8–3.1 | 174 |

**Changed the same day, at Juan Luis's request:** a cloud's size now follows `wgain` × `rgain`, divided by 1.7 and kept within the same limits (`engine/clouds.py`, `tools/engine_plots/cloud_size.py`). `climb` below is the lift on a centred circle of 91 m minus 1.4 m/s of sink, so it counts width as well as peak:

| Size from | Correlation with core | With climb |
| --- | --- | --- |
| `rgain` (before) | −0.74 | −0.63 |
| `wgain` × `rgain` (now) | +0.80 | +0.73 |
| `wgain` | +1.00 | +0.88 |
| `wgain` × `rgain`² (mass flux) | +0.21 | +0.23 |

`wgain` alone would rank every cloud exactly, so the biggest in sight would always be the best, which no sky does. Mass flux says little about lift. The product keeps some of a thermal's width in its cloud, and leaves room to be wrong:

| Cloud scale | Thermals | Core, median and p10–p90 (m/s) | Climb, median (m/s) |
| --- | --- | --- | --- |
| Under 0.8 | 13 | 1.8, 1.5–1.9 | +0.4 |
| 0.8–1.0 | 339 | 2.4, 2.0–2.9 | +1.0 |
| 1.0–1.2 | 418 | 3.1, 2.5–3.9 | +1.7 |
| 1.2 and over | 242 | 3.9, 3.0–5.3 | +2.5 |

The median size stays at 1.07, and the air stays under the clouds as before (`clouds_vs_lift.py`: 97–100% of the air at +2 m/s or more, clouds covering 13% of the sky). The clouds' sizes now run a little wider, 535–1190 m of body instead of 619–1190 m. The flown pair swap places: the 5.7 m/s thermal's cloud goes from 0.81 to 1.16, and its weak neighbour's from 1.30 to about 0.85. Which cloud is at which size has changed, not the thermals: lift is the same. **Offline only: nobody has seen this in the simulator yet.**

**The centring aid works in wind.** Replayed as the HUD does and measured in the air's frame, for this flight: when the arrow is shown, it is within 12° of the true direction at the median, and within 45° in all of 676 samples. It is hidden when the circle is within 30 m of the centre, as it should be. One thing the first look got wrong: the arrow says where to shift the circle, from its centre, so it does not point at the column as seen from the cockpit, and that looked like an error in flight.

| Circle off centre (m) | Samples | Median error (deg) | Within 45° | Median half-swing (m/s) | Arrow shown |
| --- | --- | --- | --- | --- | --- |
| 0–30 | 582 | 27 | 82% | 0.33 | 0% |
| 30–60 | 1207 | 10 | 100% | 1.17 | 46% |
| 60–100 | 183 | 17 | 100% | 0.75 | 30% |
| 100–320 | 76 | 31 | 100% | 2.07 | 80% |

**Also seen in this flight:**

- **The wind near the ground is not the wind set.** The HUD read 9 kt on the runway and 15 kt in the air, with 15 kt set in every layer. In the air it was 7.72 m/s at every height flown, 620–976 m AGL. The offset when the log began fits 9 kt for the 364 s on the runway. So on the ground the sky moved at 9 kt while the particles, up at the clouds, should move at 15 kt: 3.1 m/s, or about 550 m of stretch over a particle's life by the estimate above. Juan Luis saw the clouds change shape quickly from the runway, and that may be the reason. It was not measured, and it ends in the air.
- **Markers in wind step about once a second.** It shows against the ground, since a column is a thin line reaching it.
- **The columns stay vertical** while the sky drifts. Juan Luis noticed, and expects thermals to lean. That is the second step of the wind.
- **`TOP` again read as wrong.** It is right: 1500 m minus AGL, within 17 m of the clouds' base here, since they take their ground height from the glider's when they are created. Why it looked wrong was not asked yet. The same thing happened on 2026-11-04 ([phase2.md](phase2.md#first-flight-by-hand)), so the label is a candidate for when the HUD is refined.
- **Why the airbrakes open.** Laminar's script for this aircraft (`plugins/xlua/scripts/ask21_basics/ask21_basics.lua`) opens the airbrakes and the wheel brake at every flight start on the ground, and closes them above 10 ft. The two are linked, as in the real glider. A hardware lever does nothing until it moves, and moving up with the map does not run that code again. So a flight from the runway that is moved up with the map keeps them open until the lever is moved (here until 416 s, and everything before that is ignored above). It is the aircraft, not the plugin.

## A flight by the clouds alone

Juan Luis, 2026-11-05 night, Santiago, Laminar ASK 21, 15 kt from the west (7.72 m/s at every height from 100 m AGL up), `wide_carriers`, w\* 3, zi 2000 m, seed 1, lean off (`flightlog_20261105_212503.csv`). He turned the markers off 146 s into the log, before either thermal, and flew from then on by the clouds. He told what he did, and the rest is measured from the log. The clouds' places, sizes and heights are the planner's, replayed from the log's offset: particles are not logged, so what was drawn was not measured.

The airbrakes were open until 118 s, as [before](#first-flight-by-hand). `Native` below is what is left of the climb once our lift and the polar's sink are accounted for, so the polar's errors are in it.

| t_run (s) | What | Height (m MSL) | AGL, median (m) | IAS (km/h) | Bank (deg) | TE (m/s) | Our lift (m/s) | Native (m/s) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 135–253 | Looking, over the valley | 1379 to 1262 | 563 | 101 | 16 | −0.87 | −0.01 | +0.30 |
| 256–405 | First thermal | 1249 to 1606 | 561 | 95 | 27 | +2.35 | +3.08 | +0.49 |
| 405–530 | Ridge, low | 1608 to 1863 | 177 | 87 | 4 | +1.96 | +0.19 | +2.75 |
| 530–672 | Ridge, higher | 1863 to 1953 | 331 | 95 | 11 | +0.77 | +0.11 | +1.72 |
| 672–790 | Glide into the wind | 1951 to 1858 | 759 | 114 | 5 | −0.74 | −0.12 | +0.55 |
| 790–900 | Second thermal | 1857 to 1876 | 721 | 120 | 29 | +0.46 | +1.50 | +0.49 |

Over 135–900 s, our lift gave 647 m, the native air 815 m and the sink took 903 m. The top was 1981 m MSL at 661 s, 170 m under the lowest clouds.

**Finding a thermal by its cloud, with the markers off: done, twice, in 15 kt.** This was what was left of the phase's first criterion.

- **First thermal.** From 204 s he turned toward the nearest cloud, the next being over 2 km further. At 222 s he met a weak thermal with no good core (1.7 m/s), turned once around it and lost about 45 m, then went on to the cloud's thermal, reaching it at 258 s.
- **Second thermal.** At 744 s, with a cloud 1.8 km off and 62° to the right, he turned to it, and flew about 1.5 km straight, keeping it 10–19° off the nose, until the lift began at 790 s. A cloud had been nearer and dead ahead (1.95 km at 700 s), but that one had already stopped being fed and was fading. One case, so it may be chance.

**The first thermal was worked as in calm air.** It gained 356 m in 149 s, and drifted 1335 m east over the ground. The circle was within 30 m of the centre for 83% of the samples. The core was 3.7–4.6 m/s, and he left it at 410 s, still at 3.7. Native lift gave about a fifth of that climb: the ground rose under it from 790 to 966 m, and `wind × slope` fits the 0.3–0.9 m/s found there. So this climb should not be set against ones over flat ground.

**The second thermal gave far less, and it was the circle.** The core was about the same (3.2–3.6 m/s), but at 110–148 km/h and 32–35° the circle's radius was about 200 m, and it swung 36–482 m from the centre, so the lift went from 0 to 3.4 m/s on every turn. By arithmetic, the first thermal's circle in this one (130–160 m, 2.84 m/s, sink 1.2, native 0.5) would have climbed about +2 m/s. Why the speed stayed so high was not asked.

**A bigger cloud was a stronger thermal, three out of three, too few to prove it.** The first look at [the new sizes](#first-flight-by-hand), which he has not yet judged by eye:

| Cloud scale | Core (m/s) | Result |
| --- | --- | --- |
| 1.40 | 4.2 | Passed at 270–300 m at 549 and 591 s, never centred |
| 1.15 | 4.2–4.6 | The first thermal |
| 0.94 | 3.2–3.6 | The second thermal |

The 1.40 cloud's thermal was the best one on offer and was missed. It was to his left, toward the hill, and he turned right, away from the hill, as a pilot should near a slope. Peak lift 1.9 m/s.

**Ridge soaring works in 15 kt, with our thermals on the same flight.** Running south along the west face, with the plugin's lift about zero, the air rose 3.6–4.0 m/s at 117–141 m AGL over 450–510 s, and TE read +2.6 to +3.0 at 81–85 km/h. He gained 345 m this way in 267 s. It agrees with [test H](SPEC.md#native-soaring-in-xp12), which is a local slope model: from a plane fitted to the terrain under the track, `wind × slope × height factor` against the native lift gives a correlation of 0.61 over 94 samples, a mean of 0.88 against 0.67 m/s. That is a rough check, since a single track fits the slope poorly. By height, with steeper ground mixed in at the low end:

| AGL (m) | 100–150 | 150–200 | 200–300 | 300–400 | 400–500 | 600–800 | 800–1000 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Native (m/s) | +3.52 | +2.63 | +1.70 | +1.51 | +1.24 | +0.50 | +0.38 |

He flew as low as 33 m AGL (633 s), and for 68 s under 150 m.

**The clouds over uneven ground are at very different heights.** A cloud takes its base from the ground under the glider when it is created ([`adapter/clouds.py`](../xp_gliding/adapter/clouds.py)), so a flight into the hills leaves a sky of mixed layers. Clouds created at the start have their base at 2151 m MSL, those created while he was on the ridge at 2838–3401 m, and those created on the way back at 2382–2797 m. At 650 s, within 2.5 km: 2151, 2326, 2847 and 3143 m. This is the replay, not a look at the sky. **It shows:** asked afterwards, Juan Luis said that some clouds seemed to go into the hill. Clouds with a base set over the valley can do that, and the wind carries them east toward higher ground, but neither is measured: particles are not logged, and the log only has the ground under the glider. Lift does not follow them either: it ends at zi above the ground under the glider, so under a 2151 m cloud over 1200 m of ground it would go on about 1050 m past the cloud's base. Nobody has climbed that high yet.

It does not close a climb as high as it goes: the top stayed under the clouds, and he left both thermals still climbing. That was his choice, not a limit of the thermals: he leaves when he has climbed enough or wants to fly on, and would go to the top in a task with few thermals. So a climb to the top has to be flown on purpose.

## The lean

Second step of the wind, built on 2026-11-05 and [checked by the test pilot](#the-lean-in-the-simulator) the same evening. **Nobody has flown it by hand:** *Thermals lean with the wind* in the menu is off by default, so the sky flown so far is unchanged. The FAA's handbook asks for the lift to be upwind of the cloud, further the stronger the wind, the weaker the thermals and the lower the glider (10-4), and for plumes that tilt in a steady wind (9-8). It gives no number for how much.

**The form.** The field holds the sky as it is at the clouds' base. At a height z, all the lift is that sky shifted upwind by

```math
L(z) = \int_z^{base} \min\left(f \frac{U(z')}{w_*},\ s_{max}\right) dz'
```

with the wind's direction at each height, and f = 0.1 and a steepest slope `s_max` of 0.5 as first guesses (`engine/wind.py`, `Lean`). A cloud sits at the base, where L = 0, so it stays where it is. With no wind L is exactly 0. It is one lookup per frame, the same shift for every thermal, and `lean/e_m` and `lean/n_m` publish it for the flight log and `replay_sky.py`.

**A departure from a real plume.** Its slope would be U / w\*, which is f = 1. This model leans a tenth of that because the point of the first step was to keep a glider with its thermal, and a pilot has to be able to follow the lean. Every thermal leaning alike is also a simplification: a stronger thermal should lean less than a weaker one on the same day.

**How much can be followed.** `tools/engine_plots/lean_climb.py climb`: 110 thermals with a formed cloud (6 seeds), entering 60 m off centre at 500 m AGL, in the air's frame, at 35° and 90 km/h, w\* 3, base 1500 m. A point on a circle with the sink of `circle_climb.py`, not a flight model. The pilots are made up: one never corrects, *lazy* shifts up to 20 m every two turns with 45° of error, *good* shifts up to 40 m every turn with 25° of error. So compare rows with each other, and none of them with a flight. Median height gained, in metres:

| Wind | f | Slope | `wide_carriers`: never, lazy, good | `medium_carriers`: never, lazy, good |
| --- | --- | --- | --- | --- |
| Any | 0 | 0 | 698, 700, 709 | 586, 648, 655 |
| 15 kt | 0.05 | 0.13 | 682, 697, 704 | 514, 619, 649 |
| 15 kt | 0.1 | 0.26 | 579, 656, 692 | 431, 561, 641 |
| 15 kt | 0.2 | 0.51 | 415, 525, 649 | 300, 418, 606 |
| 15 kt | 0.5 | 1.28 | 194, 267, 474 | 142, 210, 435 |
| 15 kt | 1 (rigid) | 2.57 | 103, 134, 305 | 75, 107, 277 |
| 25 kt | 0.05 | 0.21 | 608, 676, 701 | 454, 586, 644 |
| 25 kt | 0.1 | 0.43 | 462, 571, 665 | 334, 464, 617 |
| 25 kt | 0.2 | 0.86 | 281, 379, 570 | 199, 298, 516 |
| 25 kt | 1 (rigid) | 4.30 | 63, 81, 194 | 47, 63, 176 |

The rigid plume is out, as the arithmetic said: nobody climbs 300 m in it at 25 kt except a few of the *good* pilot's thermals. At f = 0.1 a pilot who centres loses 2–6% of the height, and one who never corrects loses 17–43%. So correcting pays, without being a fight: at a climb of 1.3 m/s the lift moves away at 0.3–0.6 m/s, 8–14 m per turn. On a weak day the lean is larger and the climbs are smaller: at w\* 2 and 25 kt, where `s_max` already limits it, the *good* pilot gains 363 m against 384 with no lean in `wide_carriers`, and 282 against 300 in `medium_carriers`.

**What a pilot sees.** `lean_climb.py read`, the same thermals with a wind toward the east. Whether a pilot who ignores the wind and flies straight through the centre of the cloud, across the wind, feels +1 m/s, and how far upwind of the centre the lift is met flying into the wind (negative: before reaching the centre). At f = 0.1:

| Wind | Height (m AGL) | Lift's centre upwind of the cloud's (m) | `wide_carriers`: feels +1, met at (m) | `medium_carriers`: feels +1, met at (m) | Lift's centre under the cloud's body |
| --- | --- | --- | --- | --- | --- |
| 15 kt | 500 | 257 | 54%, +25 | 18%, +75 | 100% |
| 15 kt | 800 | 180 | 100%, −75 | 94%, −25 | 100% |
| 15 kt | 1100 | 103 | 100%, −150 | 100%, −100 | 100% |
| 25 kt | 500 | 430 | 24%, +188 | 19%, +250 | 66% |
| 25 kt | 800 | 301 | 32%, +25 | 16%, +100 | 100% |
| 25 kt | 1100 | 172 | 100%, −100 | 94%, −25 | 100% |

With no lean every row is 100%. So a thermal that was always under the middle of its cloud now needs reading the wind when low: high up the centre of a cloud still works, low down and in more wind the pilot has to aim upwind, and the lift is still under the cloud nearly everywhere. f = 0.15 is where this starts to fail: at 25 kt and 500 m the lift's centre is under no cloud's body at all. That, with the table before, is why 0.1. `lean_climb.py section` draws it from the side, in `plots/lean_section.png`.

**Other forms, not built.**

- **A train of bubbles** from a source fixed to the ground: a glider stays with one, and meets the next one U × the time between them further upwind. About 1 km at 10 m/s and 100 s, so the same escape as a plume, in steps. With a source drifting with the air, there is no lean at all.
- **A lean that follows each glider:** the lift stays with it. That breaks determinism, since the sky would depend on who is flying and how.
- **Only moving the cloud** downwind of a vertical column: nothing to follow, but it is not lower-means-further, and the column stays vertical.

**In shear.** `lean_climb.py shear`, f = 0.1. The lean comes from X-Plane's 13 layers of wind (`sim/weather/aircraft/wind_*`), read every 5 s, and takes about 60 s to reach a new wind, so no lift jumps. A wind that turns with height turns the lean, and a glider follows it as well as in a uniform wind: with the wind turning 90° from 500 to 1500 m, 571, 660 and 692 m in `wide_carriers`. So shear **does not make the climb harder** in this model: the sky still moves at the wind at the glider, and the lean's slope depends on the wind at each height, not on how fast it changes. The criterion that a pilot has to recentre in shear is met only as far as it is in a uniform wind.

**Markers.** The ring goes to the lift's centre at the glider's height, and the column leans straight from the cloud through the ring (`markers.py`). So it is straight even if the lean is not, and the instance's pitch and heading are worked out from X-Plane's conventions, not seen yet.

**By hand:** whether the upwind offset reads from the seat, and whether f = 0.1 is too much or too little. Terrain is not handled: the height is above the ground under the glider, so flying over a ridge moves L by the slope × the change in height. That is part of [the terrain under each thermal](SPEC.md#phased-roadmap), phase 4.

**Cost:** in XPPython3's Python 3.12, outside X-Plane, about 0.4 µs for the lookup, once per frame, and about 30 µs to build the table, every 5 s. In the simulator, `frame_us` was 134–139 µs at the median with the lean on, not a proper comparison with it off.

### The lean in the simulator

The test pilot, 2026-11-05, KHOB, Laminar ASK 21, `wide_carriers`, w\* 3, zi 2000 m (`tools/testpilot/fly_wind.py`: `layers`, `look`, `circle --lean`). Not a judgement of how it feels.

**The layers of wind agree with the wind at the glider.** The layer at the glider's height against `wind_now_*`, m/s:

| Weather | Heights (m AGL) | Difference | The lean the plugin publishes against the engine's |
| --- | --- | --- | --- |
| Uniform 15 kt | 140–1490 | 0.00 | Within 0.1 m |
| 25 kt at the clouds, 5 to 50 kt from 500 to 12000 ft above the field | 141–2493 | 0.00 | Within 0.3 m |
| X-Plane's real weather (about 30 kt that evening) | 139–2483 | 1.3–1.6 | Within 0.2 m |

**It found a mistake the tests could not.** A layer not in use has a speed of −1 kt, a direction of 0 and a meaningless altitude, among the layers in use. They were read as wind: 2487 m AGL in a uniform 15 kt read 0.5 m/s toward the north. `wind_layers` now leaves them out, and a test pins it.

**The same thermal with the lean off and on.** The same start with the aircraft reloaded first, entering around the lift's centre at the height of entry, then 35° and 95 km/h with no correction for ten turns:

| Wind | Lean | Lift's centre from the cloud at entry | Height gained | Climb, turn 1 and turn 10 (m/s) | Circle's centre from the lift's centre, turn 1 and turn 10 (m) |
| --- | --- | --- | --- | --- | --- |
| 15 kt | Off | 0 | +156 m, 554 to 710 AGL | +0.54, +0.94 | 67, 94 |
| 15 kt | On | About 245 m | +156 m, 547 to 703 AGL | +0.53, +1.08 | 73, 138 |
| 25 kt | Off | 0 | +145 m, 545 to 690 AGL | +0.51, +0.93 | 73, 106 |
| 25 kt | On | About 420 m | +162 m, 528 to 690 AGL | +0.52, +1.24 | 80, 174 |

- **The glider climbs the same with the lean,** though its circle is hundreds of metres from where it would be with the lift under the cloud. One thermal, flown once each way, and a climb that is weak for this thermal, so it says the lean costs nothing over 226 s, not more.
- **The circle falls behind as the arithmetic says:** the slope × the height gained is 40 m at 15 kt and 69 m at 25 kt, and turn 10 is 44 m and 68 m further off than with the lean off.
- **The sink is the same,** 1.5 m/s, and the plugin's lift is the engine's within 0.002 m/s RMS in all four flights. So the [offline tables](#the-lean) ask the right lift of the right place, at this height.
- **Not flown:** a climb with corrections, or as high as it goes. In shear only the layers were checked, not a circle.

**The marker.** With the lean off, the column is straight up under the cloud. Turned on at 25 kt about 600 m AGL, the lean was 384 m, and the column leaned with its bottom upwind, through a ring moved upwind and up to its cloud, seen on two screenshots. The ring is where the lift is: the distance to it in the sky and on the scene agree within 0.4 m.

**The flight log** has `xpg_lean_e_m` and `xpg_lean_n_m`, and `replay_sky.py` rebuilds the flight with them. It now uses the exact conversion, and picks the thermal by place when the log has the offset: this flight's thermal overlaps another, which fooled its match by the core, by 1.6 m/s.

**Found in passing:**

- **A new flight with the same aircraft keeps the sky's offset,** at least through the web API: no plane-loaded message comes, and after several flights it stood at 0.16° of longitude, about 15 km. So the sky goes on rather than starting again, which does no harm, but it is not what this phase said. Reloading the aircraft clears it. Missions that compare flights need `--fresh`.
- **The first circle of a session ran at a mean bank of 43° instead of 35°,** with the lean off, and sank about 0.3 m/s more. The seven circles after it held 35°. Not understood; it has nothing to do with the lean, which was off.

## Clouds over uneven ground

Built on 2026-11-06, the rule Juan Luis approved that morning. Checked by the test pilot, not flown by hand.

**The rule.** A cloud keeps one height for life, since a particle stays where it was emitted: the higher of a level for the area and the highest ground under it and along its drift, plus 300 m (`engine/clouds.py`: `ground_points`, `cloud_base_m`). The level is today's height, the sky's `cloud_base_zzi` x zi over the ground under the glider, taken when the first cloud of a sky is created and kept until the sky is cleared. The drift is read in the wind at that moment, for as long as the cloud will last: a cross of the cloud's width under it, then three lanes 1 km apart in steps along the way. These are clouds only: the lift's top still uses the glider's AGL.

**What terrain probes do (`tools/terrainlab/`, X-Plane 12.4.3, 2026-11-06).** Paused flights at Hobbs and Santiago, 24 bearings at each of 24 distances, 8000 points along lines and 8000 scattered within 20 km, and a 120 km square every 500 m at Santiago.

| Question | Measured |
| --- | --- |
| How far is the ground loaded? | Every probe hits out to 125 km at both sites, some out to 250 km, none at 300 km. The same at 0, 60 and 200 s after a flight starts |
| What happens beyond that? | `result` 2 (missed), and a height with no meaning, rising with distance (16 m at 300 km, about 1860 m at 1000 km). Laminar says it returns the height of a 0 MSL sphere, so only `result` can be trusted |
| Is the height right? | At 1 km from the glider, 1107-1116 m against the 1112 m under it at Hobbs, 540-562 m against 549 m at Santiago |
| Does one probe do, far from the local origin? | The local Y axis is not the vertical there, so a probe from 0 m lands a little beside the point. Against a second probe from the height found: within 0.3 m to 40 km at Hobbs, within 21 m at 40 km and 66 m at 100 km in the Andes. One is enough under a 300 m margin |
| The same ground from elsewhere? | The Santiago square from a flight 110 km east, 44585 points hit from both: median -0.01 m, 98% within -0.8 and +0.4 m, at most 7.8 m. The water flag differs at 18 points |
| Cost, with the calls from XPPython3? | Probe 1.2-1.8 us at the median, 2.6-4.7 us at p99, 166 us at most. With `worldToLocal` and `localToWorld`, 1.8-2.5 us. Laminar calls probes expensive; here 200 take about 0.4 ms. Measured paused, with about 8 ms of probing in each frame |

The water flag is set on small water too: one bearing at 15 km from Hobbs, one at 15 and one at 30 km at Santiago. Not looked at further, since thermals over water are a separate item.

**What the rule does at Santiago, offline** (`analyze_terrain.py`, on the square above). Level 2049 m MSL, clouds within 20 km with what they have left drawn at random, not the engine's: the question is the shape of the ground.

| Wind | At the level | 90% of bases below | Over 2000 m above the ground below it | If instead only the ground under it counted, and it faded before meeting a hill |
| --- | --- | --- | --- | --- |
| Calm | 94% | 2049 m | 0% | No cloud fades |
| 15 kt from the west, toward the Andes | 83% | 2746 m | 2.7% | 17% fade early, with 25% of what they had left |
| 25 kt from the west | 72% | 2965 m | 7.3% | 28% fade early, with 43% |
| 15 and 25 kt from the east | 93-94% | 2049 m | 0% | 1-2% fade early |

So the highest base is about 3470 m in every case, and the part about the drift has a price: with the wind toward the mountains, some clouds still over the valley are too high to reach, up to about 1400 m above their neighbours. The spread is about as wide as in [the night flight](#a-flight-by-the-clouds-alone) (1250 m), but now most clouds share one level, and unless the wind changes none should go into a hill. Fading them early would touch about as many clouds as it would bring down to the level. The rule stays as approved, for the eye to judge.

**In the plugin, by the test pilot.** `fly_terrain.py clouds`, 15 kt from the west, 170 s flying with no hand on the stick.

| Site | Clouds | Level | Above it | Highest base | Ground not found | Cost of one cloud's height |
| --- | --- | --- | --- | --- | --- | --- |
| Hobbs | 180 | 2611 m | 0 | 2611 m | 0 | 88 us, 133 us at most |
| Santiago | 175 | 2050 m | 36 (21%) | 3494 m | 0 | 36 us, 168 us at most |

The 21% agrees with the offline 17%. At 8 new clouds per update that is at most about 1.3 ms, only while a sky fills. The largest cloud update in the second flight was 7.1 ms against 0.8 ms in the first; it spans the change of flight, when 180 clouds are destroyed, which is the likely cause and was not separated. Screenshots from under the clouds over the valley show a level base. Nobody has yet looked at clouds near a hill.

**Open.** The level depends on where a flight starts, so two pilots at Santiago can differ, until it comes from XP12's atmosphere (phase 5). Flying up a long valley leaves the level behind, and over high ground the clouds are then only 300 m up. Further into the Andes bases would pass 5000 m, out of reach of the lift, and near the height where X-Plane's lack of oxygen blacked out the cockpit view. Not tried.

## Cost

Sampled once each, at the end of a flight, not a proper comparison: `frame_us` 132–160 µs with about 220 clouds moving (118–132 µs in phase 1, before clouds and wind), and the largest cloud update seen is 1.2–2.2 ms, as before this work, since tiles load in that path too. `tools/testpilot/fly_clouds.py cost` has not been run in wind. The HUD with the wind costs 281 µs to draw (265 µs before).

## Still open

- **Does a bigger cloud read as a stronger thermal, by eye?** [Flown](#a-flight-by-the-clouds-alone), three clouds agree, and he has not been asked.
- **A climb as high as it goes,** in wind. The thermal of the first flight died before one was made, and [the night flight](#a-flight-by-the-clouds-alone) left its thermals still climbing.
- **Clouds and lift over uneven ground:** the clouds' height is [built](#clouds-over-uneven-ground), and has not been seen near a hill by hand. The lift still ends at zi above the ground under the glider (phase 6).
- **A climb through shear, by hand.** [Flown by the test pilot](#which-wind-carries-the-sky-in-shear), in a circle, under both winds. Whether a sky that depends slightly on the glider's height shows anywhere has not been checked.
- **The lean, by hand:** whether it reads from the seat, and f. [Checked by the test pilot](#the-lean-in-the-simulator), and off by default.
- **Which wind in strong shear:** only the wind at the glider has been tried.
- **The menu's submenus** read well in X-Plane ("excellent", Juan Luis), and each showed the right setting, but changing a sky in flight has not been tried.
- **Time acceleration** and a change of clock: tested offline, not flown.

## Found in passing

- **X-Plane crashed on start** twice this day (06:43, 07:31), about 40 s in, with AviTab as the faulting module in Windows' log (exception `0x40000015`). The same log has crashes in AviTab on 2026-10-31, before this project existed, and our plugin had already been enabled when they happened. Juan Luis removed AviTab, and the next two starts were clean. Two starts prove little.
- **X-Plane's lack of oxygen looks like a broken screen.** A test flight left over the Andes at 5700-6000 m turned the cockpit view black, with the HUD still drawn at 60 fps. Juan Luis recognised it (2026-11-06). The chase view was normal at the same moment, and a new flight at 3000 m came back dim. The height where it starts was not measured.
- **The web API has no plugin datarefs at the main menu:** they appear once a flight is loaded, so a mission must not touch them before its air start.
