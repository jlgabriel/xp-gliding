# Phase 3: wind

The wind is X-Plane's. The plugin reads it and writes none. This records the first step of [the design](SPEC.md#wind), the wind carrying the sky, flown by the test pilot on 2026-11-05 at KHOB in the Laminar ASK 21 (`tools/testpilot/fly_wind.py`, `tools/cloudlab/fly_drag.py`), and then [by hand](#first-flight-by-hand) the same day: staying in a thermal is done, finding one by its cloud is not.

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

## Cost

Sampled once each, at the end of a flight, not a proper comparison: `frame_us` 132–160 µs with about 220 clouds moving (118–132 µs in phase 1, before clouds and wind), and the largest cloud update seen is 1.2–2.2 ms, as before this work, since tiles load in that path too. `tools/testpilot/fly_clouds.py cost` has not been run in wind. The HUD with the wind costs 281 µs to draw (265 µs before).

## Still open

- **By hand:** finding a thermal by its cloud in wind, with the markers off, now that [a bigger cloud is usually a stronger thermal](#first-flight-by-hand). This is what is left of the phase's first criterion. It is also the first look at the new sizes.
- **A climb as high as it goes,** in wind. The thermal of the first flight died before one was made.
- **A climb through shear.** The sky moves at the wind at the glider, so a glider stays with its thermal at any height, by construction. Whether a sky that depends slightly on the glider's height shows anywhere has not been checked. Not flown in a circle.
- **Tilt:** the lift upwind of the cloud, and having to recentre in shear. Nothing yet; see the [design](SPEC.md#wind).
- **Which wind in strong shear:** only the wind at the glider has been tried.
- **The menu's submenus** read well in X-Plane ("excellent", Juan Luis), and each showed the right setting, but changing a sky in flight has not been tried.
- **Time acceleration** and a change of clock: tested offline, not flown.

## Found in passing

- **X-Plane crashed on start** twice this day (06:43, 07:31), about 40 s in, with AviTab as the faulting module in Windows' log (exception `0x40000015`). The same log has crashes in AviTab on 2026-10-31, before this project existed, and our plugin had already been enabled when they happened. Juan Luis removed AviTab, and the next two starts were clean. Two starts prove little.
- **The web API has no plugin datarefs at the main menu:** they appear once a flight is loaded, so a mission must not touch them before its air start.
