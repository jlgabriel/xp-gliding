# Phase 4: a sound sky

Working record. Everything here dated 2026-11-06 was flown by the test pilot, not by hand, with X-Plane 12.4.3 and the Laminar ASK 21. Nothing here has been judged from the seat yet. *Added later on 2026-11-06:* that was written before [the flight by hand](#a-flight-by-hand-through-a-cloud) of that evening, the one part of this page flown by a person. What follows it is again by the test pilot.

## Reading a flight afterwards

`tools/flightlog/read_flight.py LOG.csv` finds where a glider circled, rebuilds the sky and says which thermal each circling belonged to. It then gives what a pilot is asked after a flight: the clouds raised for the ground, cloud size against climb, the top of each climb against the cloud's base, and how far the circles were from the cloud's emitter.

Checked against the [night flight](phase3.md#a-flight-by-the-clouds-alone) of 2026-11-05. It finds both thermals, and the first has a core of 4.08 m/s against the 3.7-4.6 noted then. Its stretch is 30 s longer than the one noted (226-410 s against 256-405 s), because it counts from the first turn, so its climb reads +1.72 and not +2.35.

The logger (0.7.0) gained what a replay cannot give: the clouds' level, how many were raised, and the nearest cloud's distance, base and size. These come from `CumulusClouds`, once per plan. It also gained w\*, zi, `wind_at_clouds` and the local time.

**Limits.** Particles are not logged, so the place of a cloud is its emitter's. Core and ceiling leave out overlapping neighbours. How clouds look near a hill is for the pilot's eye.

## No thermals over water

**The rule.** A thermal is not born where X-Plane's terrain probe says `is_wet`. The filter is `Injector.accept_thermal`, through the field's `accept(lat, lon, birth)`, which never shifts the random stream.

**Which ground.** A thermal keeps its place in the air, so the ground under it changes. The filter asks about the ground under it at its birth, in the present wind (`AirDrift.to_ground_at`). The field and the clouds load the same thermal at different times, and asking about the ground under it at that moment would make them disagree: a cloud with no lift, or lift with no cloud. In a steady wind the answer does not depend on when it is asked (`tests/test_wind.py`, within 20 m after 20 minutes). A thermal born over land can drift out over the sea. That was a choice, and it can be changed.

**Small water counts.** The flag does not tell a pond from the sea, and there is no size test. It costs little:

| Site | Left out | Note |
| --- | --- | --- |
| Coast at Viña del Mar, calm | 579 of 1914 (30%) on the first load | |
| Coast, 15 kt from the west | 585 of 2038 (29%) | |
| Santiago, inland | 4 of about 2000 (0.2%), then 1 of 426 | |
| Hobbs, inland | None of 418 after the first load | The first load cannot be told from the end of the flight before: the counters run across flights |

Seen once from the front along the coast, 82 s into a flight, with about 750 of 1048 cloud tiles still to load: clouds over the land and none over the sea. One view of a sky not yet full is weak evidence.

**Cost.** Frames in the flight loop stayed at a median of 100-140 µs, at most 456 µs, in the range of earlier flights, with no flight without the filter to compare. Not measured: the slow path. About 2000 probes on the first load at the [measured 2-5 µs](phase3.md#clouds-over-uneven-ground) would be about 5-10 ms once per flight, next to tiles that cost more.

**Open.**
- The water flag differed at 18 of 44585 points seen from two places, so field and clouds can rarely disagree. Not seen in flight.
- If the wind changes, a thermal asked about later may get another answer.
- A flight beside a shore in wind, looking at whether the lift is under the clouds, has not been flown.
- Sea breeze and thermals weakening over water are not modelled.

## How high does a climb go?

`fly_sky.py top`, calm air on flat ground near Hobbs (about 1120 m), in a mature thermal chosen offline. w\* 3, zi 2000 m, level of the clouds 1500 m AGL (2612-2625 m MSL). The pilot reads the lift and rolls out toward the strong side (`ShearMission`), so its circle's centre is 8-26 m from the thermal after the first quarter.

| Sky | Thermal | Start | Top | Climb | At the end | Lift where it flew |
| --- | --- | --- | --- | --- | --- | --- |
| `wide_carriers` | wgain 2.22, rgain 1.06, size 1.39 | 1206 m AGL | 1436 m, 69 m under the base, out of time | +1.04 | +0.80 | +2.6 |
| `wide_carriers` | the same | 1441 m | 1518 m, **14 m over the base**, out of time | +0.34 | +0.31 | +1.9 |
| `medium_carriers` | wgain 1.41, rgain 1.36 | 1231 m | 1308 m, 192 m under, out of time | +0.33 | +0.30 | +1.8 |

The two skies picked different thermals, so the last row is no comparison between skies. No flight actually stopped climbing: each ran out of its time limit.

**The gap between lift and climb is the glider, not the centring.** The sink in the turn is 1.5 m/s at 34-35° and 95 km/h indicated, at about 2550 m MSL. There the true airspeed makes the circle's radius about 140 m, not the 105 m the mission assumed, so the glider flies well out from the core even when centred. A first reading during the work blamed the centring: the log shows otherwise.

**Offline, across the sky** (`tools/engine_plots/cloud_reach.py`): 142 mature thermals with a cloud, 6 days, neighbours included. Where the lift around a centred circle equals the sink:

| Circle | Sky | Reach the base | Median top | 10th percentile | Under size 1.0 | From size 1.0 |
| --- | --- | --- | --- | --- | --- | --- |
| 140 m, sink 1.5 (as flown) | `wide_carriers` | 19% | 1400 m | 1275 m | 1312 m | 1425 m |
| | `medium_carriers` | 8% | 1325 m | 1200 m | 1275 m | 1362 m |
| 90 m, sink 1.1 (a guess at slower, tighter flying) | `wide_carriers` | 69% | 1525 m | 1425 m | 1475 m | 1550 m |
| | `medium_carriers` | 65% | 1525 m | 1425 m | 1475 m | 1550 m |

**Reading.** How high a pilot gets depends on how the circle is flown about as much as on the sky. Flown as here, a typical cloud's top is 100-175 m under its base, and only the best reach it, slowly. Flown tighter and slower, most reach it. The numbers of the second circle are not measured. The lift's shape has not been changed. A hand flight (point 3 of the list given to Juan Luis) decides whether this feels right. Hobbs is a high place to ask: at Santiago the valley's air is denser, though its base is lower too.

## Changing the sky in flight

`fly_sky.py change`, through a dataref behind the same setting as the menu's item, not saved to `config.json`. Used by hand: still not tried.

- **Clouds go:** 50 to 8 and 66 to 6 within 5 s, then the new sky fills. By the count only, with no screenshot.
- **Cost:** a frame of 894-1080 µs at the change, once.
- **Errors:** none in XPPython3's log.
- **The lift rebuilt offline** matches to 0.000 m/s, but over a straight flight in sinking air between thermals, so this only shows the environment sink of each sky.

**In a thermal** (`change --in-lift`, wide to default): the lift fell from +2.86 to +0.25 m/s and the force from 489 to 42 N in one step, 458 N at most. Normal acceleration did not move: 1.05 g before and after. The glider feels no more than crossing an edge of a thermal. SPEC asks for no jump in the forces, and strictly there is one. Whether to fade it is Juan Luis's to decide; it looks unneeded for something done from a menu.

## The clock and the sim's speed

`fly_sky.py clock`, 15 kt from the west.

- **The clock jumps two hours** (`sim/time/zulu_time_sec`): clouds 29 to 5, then a new sky fills. The offset does not jump, as `MAX_STEP_S` intends. No errors.
- **Twice the sim's speed** (`sim/time/sim_speed` 2, `sim_speed_actual` read 2.00): for 40 s the offset grew by 0.00083° per 10 s of sim time, as at normal speed and as the 7.7 m/s of wind says. Clouds kept filling, frames were normal. No errors.

**Not checked.** Whether particles live half as long in real time. Whether the lift stays right in a climb at that speed. Faster speeds. How it looks.

## A flight by hand through a cloud

Juan Luis, the evening of 2026-11-06, Santiago, Laminar ASK 21 on tow, `wide_carriers`, 15 kt, markers on, landed at Vitacura. Told as it happened, with screenshots. **The main climb was not logged:** the test pilot's missions turn the logger's automatic start off until X-Plane restarts, and X-Plane had been left open after them. The numbers below for that climb are read from the HUD in the screenshots. Missions now turn it back on when they end. `flightlog_20261106_195658.csv` covers only the last 473 s, from when it was turned back on.

**The climb went into the cloud and out of the top.**

| Where | Vario | Netto | HUD's TOP |
| --- | --- | --- | --- |
| Under the cloud | +3.1, then +1.8 | +4.3, then +2.9 to +3.1 | +653, then +483 and +475 m |
| Inside it | +2.4 | +4.0 | +571 m |
| Coming out of the top | +0.8 | +2.8 | +383 m |

So the lift does not end with its cloud. A real thermal ends about at the top of its cumulus. The cause is the [known limit](phase3.md#clouds-over-uneven-ground): a cloud has one height MSL, and the lift ends at zi / 1.1 (1818 m) above the ground under the glider. Over high ground that is well above the cloud. In the logged part, the cloud being circled had its base at 2839 m MSL, 692 m over the level of 2147 m, over ground of about 1500 m, and `read_flight.py` has the thermal holding this glider up to 3045 m, about 200 m over the base.

**The HUD's TOP is not the distance to the cloud over hills.** It is 1500 m less the height over the ground under the glider, so it rose from +475 to +571 m while climbing into a cloud, and it reads +1500 m on the runway.

**The other points.**
- **Cloud overhead:** in the outside views the marker's column goes up into the cloud over the glider, with 15 kt of wind. Only the screenshots say so.
- **Hills:** one large cloud looks to rest on a crest, seen from above, which does not tell. Not settled. Clouds stand at two heights, level over the valley and raised over the hills: 259 of 2866 raised, the highest base 4248 m MSL. Whether that looks natural has not been asked yet.
- **Size against climb:** no data. The logged circling (86 s, -46 m) stayed about 340 m from the centre of a thermal with a core of 3.9 m/s.

**Seen in passing, for when looks get their turn.** Far clouds are drawn bright and sharp over the fog of the cloud the glider is in. Near some clouds there are large, smooth, pale shapes, perhaps particles fading near the camera, not explained.

## The lift ends with its cloud

Built the night of 2026-11-06, the fix Juan Luis approved after the flight above. Flown by the test pilot, not yet by hand.

**The rule.** Each thermal gets a floor, m MSL, and its height is measured from there: floor = its cloud's base - `cloud_base_zzi` x zi (`engine/field.py`: `height_in_thermal`). So over any ground the lift at a cloud's base is what it is on the flat, and it ends about 318 m above the base, at zi / 1.1 - 0.75 zi with zi 2000 m. On flat ground the floor is the ground, and nothing changes. The sink between thermals stays with the height above the ground.

- **A thermal with no cloud** goes by the level. So over ground higher than the level plus 318 m, it gives no lift at all. This follows from the design, and is worth asking from the seat.
- **Below the floor,** in a valley deeper than the level, lift is read as at 100 m, so a thermal still comes from the ground under it, weakly, and nothing jumps at the floor.
- **One base for both.** The field and the clouds load the same thermal as two objects at different times, so `CloudHeights` (`adapter/clouds.py`) keeps each base by (lat, lon, birth), whichever asks first. It reads the ground, so only when a thermal loads.
- **The ground under the glider now only matters for the sink.** A thermal's height is MSL less its floor, so rough ground no longer moves the lift.
- **A new sky** has a new level: a new field (seed, day, range, sky or zi), or a jump since the last slow update, of the clock over 120 s or the glider over 5 km. That is how a new flight with the same aircraft or a move on the map shows up: X-Plane sends no message for it. The clouds start over with it, or they would stand at the old level over the new lift.
- **The HUD's TOP** is now the nearest drawn cloud's base less the height MSL, or the level if none is drawn, or the old formula if neither is known. The nearest cloud is worked out once per plan, every few seconds.
- **The markers** read each thermal at its height, and each column's top is at that thermal's cloud.

**Flown.** `fly_sky.py top`, `wide_carriers`, w\* 3, zi 2000 m. At Santiago, in 15 kt from the west, in the Andes east of the city, picked from the terrain lab's height map. "Rebuilt" is `ThermalField.lift_at` at the logged points with the logged floors. "By AGL" is the same points the way the lift was before. All are the lift at the glider, not at the core.

*A climb under a raised cloud.* Level 3603 m, base 4507 m, 904 m above the level, floor 3007 m. The log begins 211 m under the base. Log `flightlog_20261106_204648.csv`.

| From the base | Logged | Rebuilt | By AGL | From centre | AGL |
| --- | --- | --- | --- | --- | --- |
| -300 to -250 m | +2.13 | +2.14 | +4.10 | 175 m | 1242 m |
| -250 to -200 m | +1.91 | +1.91 | +2.99 | 194 m | 1016 m |
| -200 to -150 m | +2.20 | +2.20 | +4.37 | 159 m | 833 m |
| -150 to -100 m | +2.03 | +2.03 | +3.99 | 172 m | 756 m |

Top 4389 m, **118 m under the base**, climbing +0.12 over the last 30 s. It stopped because this glider sinks 1.5-2 m/s in the turn up there, not because the lift ended. So it shows the climb no longer goes past the cloud, not where the lift ends.

*From above the base, sinking through it.* Two flights, other thermals. Logs `flightlog_20261106_205222.csv` and `flightlog_20261106_205604.csv`.

| Thermal | From the base | Logged | Rebuilt | By AGL | From centre | AGL |
| --- | --- | --- | --- | --- | --- | --- |
| Base 4251 m | +200 to +250 m | +0.40 | +0.40 | +0.60 | 203 m | 1660 m |
| | +150 to +200 m | +0.45 | +0.45 | +0.57 | 200 m | 1648 m |
| | +100 to +150 m | +0.76 | +0.76 | +0.94 | 162 m | 1588 m |
| Base 4303 m | +0 to +50 m | +0.86 | +0.86 | +0.00 | 213 m | 2116 m |
| | -50 to 0 m | +1.07 | +1.07 | -0.15 | 179 m | 1889 m |
| | -100 to -50 m | +1.26 | +1.26 | +0.67 | 175 m | 1605 m |

The first of these stopped by itself after 80 s, so nothing is logged lower down. The second thermal's rows show the old rule could also err the other way: with the ground far below, a thermal gave no lift right under its own cloud.

**Nothing was logged above about +250 m,** so the lift reaching zero at +318 m is the model's, not a measurement. Offline, for the core of the thermal with its base at 4303 m: +1.33 m/s at the base, +0.93 at +100 m, +0.51 at +200 m, +0.08 at +300 m, 0 at +318 m, -0.37 at +400 m, and 0 from +500 m, where the height reaches zi.

**The rebuilt lift matches the logged one to 0.01 m/s** in every row of these flights and the one at Hobbs, so the plugin does what the rule says. A first reading was off by up to 1.9 m/s: a neighbour stood 100 m from the raised thermal with a floor 900 m lower, and `read_flight.py` gave it the wrong one. It now asks the rebuilt sky which thermal was the nearest.

**The floors against the map.** The plugin's floors differed from the oracle's by 5-75 m. The ground is the same, but the oracle has to guess when the plugin first asks and where the glider is at that moment, so the level and the time left differ. Any oracle with no floors differs from the plugin over hills. `replay_sky.py` has none, and says so.

**The TOP.** Two screenshots in the climb under a raised cloud: +229 m at 4274 m MSL and 1608 m AGL, then +227 m at 4280 m MSL and 974 m AGL. Against the 4507 m logged that is about right, and it did not follow the ground. It lags the height a little. The value on the HUD is not logged.

**Hobbs, flat ground, the same thermal as [before](#how-high-does-a-climb-go)** (wgain 2.22, rgain 1.06). Log `flightlog_20261106_210334.csv`.

| | Start | Top | Climb | At the end | Lift where it flew |
| --- | --- | --- | --- | --- | --- |
| Before | 1206 m AGL | 1436 m, 69 m under the base, out of time | +1.04 | +0.80 | +2.6 |
| Now | 1168 m | 1405 m, 95 m under the base, out of time (200 s) | +1.18 | +0.97 | +2.2 to +2.9 |

An oracle with no floors differs from the plugin by 0.005 m/s RMS over 2535 samples. Floor 1116 m, the ground. So flat ground is unchanged, as far as one flight can say.

**Cost.**

| What | Measured |
| --- | --- |
| `lift_at`, four samples, offline | Median 15-39 us before, 39-54 us now, at most 221 us. The search has to reach the widest of all heights |
| A frame in the flight loop, in flight | Median 159-176 us, 99% under 264 us, at most 339 us, of the smoothed value in the log, so a single long frame does not show. It was a median of 100-140 us. The budget is 500 us |
| One cloud's height, new | 77-594 us at most, in 15 kt, reading the ground along the drift. Once 7.2 ms, in the first session after a restart, not explained |
| Giving thermals their floors, in the slow path | 180-230 us when a few load in flight. **44.8 ms at most when a whole sky begins,** one long frame at the start of a flight or after a jump |

**Tools.** The logger is 0.8.0, with `xpg_nearest_floor_m`. `read_flight.py` reads a log with that column with floors in its core, its ceiling and `own_lift`, and older logs as they were flown. `fly_sky.py top --site santiago` takes a raised cloud from the height map, `--below` is negative to start above the base, and `--whole` keeps flying when not climbing. For a flight that started above the base, the reading "reached the cloud" means nothing.

**Found on the way.**
- The sky's offset goes on across a new flight with the same aircraft: 0.06 deg of longitude by the Hobbs flight. Nothing is wrong with the lift, but a sky is not back where the field drew it, so "same seed, same sky" holds only after a new aircraft. Not changed.
- Loading a far place by the API took X-Plane about 6 minutes, right after Juan Luis added photo scenery, marked "Not Responding" meanwhile, and the test pilot's call timed out at 30 s. In that time the datarefs read 0 m MSL and -2719 m AGL. A slow update on such a frame would take a level from garbage, until the next jump. Not seen: the level at Hobbs was right, at 2613 m. No guard was added.
- One flight came up with X-Plane's main menu over it, paused, and the test pilot aborted at 0 km/h. Not explained.
- Where a thermal's height reaches zi its lift goes from about -0.5 m/s to 0 at once, as it did at z = zi before. Nobody flies there.
- In one screenshot a cloud seems to end against a rock wall. It belongs with the big cloud on a crest, below.

**Open, from the seat.**
- Whether it feels right that a climb ends under the cloud, or just into it. This glider up there stops about 100 m short.
- Cloud size against climb: still no data.
- Whether clouds at two heights look natural. Whether a big cloud on a crest touches it.
- The HUD's TOP jumps when the nearest cloud changes, if the two are at different heights. Whether that helps or misleads.
