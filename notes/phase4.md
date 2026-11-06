# Phase 4: a sound sky

Working record. Everything here dated 2026-11-06 was flown by the test pilot, not by hand, with X-Plane 12.4.3 and the Laminar ASK 21. Nothing here has been judged from the seat yet.

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
