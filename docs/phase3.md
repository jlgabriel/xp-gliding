# Phase 3: wind

The wind is X-Plane's. The plugin reads it and writes none. This records the first step of [the design](SPEC.md#wind), the wind carrying the sky, flown by the test pilot on 2026-11-05 at KHOB in the Laminar ASK 21 (`tools/testpilot/fly_wind.py`, `tools/cloudlab/fly_drag.py`). **It has not been flown by hand yet.**

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

## Cost

Sampled once each, at the end of a flight, not a proper comparison: `frame_us` 132–160 µs with about 220 clouds moving (118–132 µs in phase 1, before clouds and wind), and the largest cloud update seen is 1.2–2.2 ms, as before this work, since tiles load in that path too. `tools/testpilot/fly_clouds.py cost` has not been run in wind. The HUD with the wind costs 281 µs to draw (265 µs before).

## Still open

- **By hand:** finding a thermal by its cloud in wind, and staying in it. This is the phase's criterion.
- **A climb through shear.** The sky moves at the wind at the glider, so a glider stays with its thermal at any height, by construction. Whether a sky that depends slightly on the glider's height shows anywhere has not been checked. Not flown in a circle.
- **Tilt:** the lift upwind of the cloud, and having to recentre in shear. Nothing yet; see the [design](SPEC.md#wind).
- **Which wind in strong shear:** only the wind at the glider has been tried.
- **The menu's submenus** have tests with a fake `xp`, and load in X-Plane, but nobody has chosen anything in them yet.
- **Time acceleration** and a change of clock: tested offline, not flown.

## Found in passing

- **X-Plane crashed on start** twice this day (06:43, 07:31), about 40 s in, with AviTab as the faulting module in Windows' log (exception `0x40000015`). The same log has crashes in AviTab on 2026-10-31, before this project existed, and our plugin had already been enabled when they happened. Juan Luis removed AviTab, and the next two starts were clean. Two starts prove little.
- **The web API has no plugin datarefs at the main menu:** they appear once a flight is loaded, so a mission must not touch them before its air start.
