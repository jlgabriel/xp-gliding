# How it works

How XP-Gliding builds its sky and puts its lift on a glider, for pilots who want to know what they are flying in and for anyone reading or changing the code. It describes version 0.9.2. The [pilot guide](pilot-guide.md) covers flying it.

## Two parts

The plugin is split in two, and the split is the main design decision.

- **The atmospheric engine** (`xp_gliding/engine/`) decides where the thermals are, how strong, what clouds they carry and how they move. It is pure Python, never talks to X-Plane, and is deterministic: given a seed, a date, a place, a time and how far the wind has carried the air, it gives the same sky on every machine. It is tested and plotted outside the simulator.
- **The X-Plane adapter** (`xp_gliding/adapter/`) is the only code that talks to X-Plane, through [XPPython3](https://xppython3.readthedocs.io/). Each frame it reads the glider's state and the wind, asks the engine for the lift, and applies it as a force. It also draws the clouds, the training markers and the HUD, and runs the menu.

Positions in the engine are in metres, east, north and up from a local origin, converted from latitude and longitude with the ellipsoid's radii at the origin (the cos(latitude) factor on longitude). The adapter moves the origin when the glider gets 20 km from it, and nothing in the sky moves when it does.

The weather, the wind, the ridge lift and the flight model stay X-Plane's. While the plugin is active it holds X-Plane's own thermal rate at 0, so no thermal is applied twice, and puts it back afterwards. It acts only on gliders: an aircraft filed as a glider, one with no engines, or one the pilot chooses from the menu.

## Where the thermals are

The world is cut into tiles of 0.02° of latitude and longitude, and time into slots of 30 minutes. Each tile and slot has its own random stream, keyed by the seed, the date, the tile and the slot, so the sky does not depend on the path flown, the order tiles were loaded in or the local origin. The generator is splitmix64, a few lines that give the same numbers in any language.

- **Births** are random in space and time, at an average density that follows the depth of the day, zi: 4.5 thermals alive per km² at zi 2000 m, falling as 1/zi². A deeper day has wider thermals farther apart, and the share of the sky they cover stays the same, so the sink between them does too.
- **Lifetimes** are drawn between 5 and 30 minutes. Each thermal grows from narrow and weak to full size and strength, then fades, so none appears or vanishes at once.
- **No thermal is born over water,** a pond as much as the sea, judged by the ground under it at its birth. Born over land, a thermal can drift out over the sea.
- **No thermal is born with the sun under 10°** at its place and birth time. The sun's height is worked out from the date, time and place (NOAA's approximation, good to about 0.5°), not read from X-Plane, so a sky can be rebuilt for any moment. Those born before sunset live out their lives, so the sky fades over about half an hour.
- **The lift at a point** is the sink of the air between thermals plus the sum of every nearby thermal's own lift. Two thermals that overlap merge into a stronger one, and the lift never jumps from one to the other.

The engine loads the thermals within 10 km of the glider. It costs 42 ms the first time at zi 2000 m, and a few milliseconds as new rows of tiles come into range.

## The shape of a thermal

Each thermal follows the model in [Allen (2006)](https://ntrs.nasa.gov/citations/20060004052), from NASA's work on soaring drones: a bell-shaped core whose width and strength come from the strength of the day, w\*, the depth of the day, zi, and the height in the layer. The mean updraft is strongest at about a quarter of zi, at 0.45 w\*, and ends a little below zi, so a climb fades before the clouds' base. Between thermals the air sinks gently, as much as the thermals carry up. The transcription reproduces the paper's check case, and tests hold it there.

The tuned sky departs from the paper in these ways, most of them settled by flying:

| Departure | Why |
| --- | --- |
| The shapes of the paper's table are blended between rows, and its stretch towards the sink between thermals is applied at every radius | The paper's rules leave small steps in the lift, which a pilot feels as bumps with no cause. Each can be switched off to reproduce the paper |
| The lift of nearby thermals is added together | The paper uses only the nearest thermal, which jumps where two overlap |
| Thermals that carry a cloud are twice as wide, shape and all (*wide*, the default sky) or 1.5 times (*medium*). Of the others, 15% are kept, at 0.6 of the strength and 0.75 of the width | The paper's thermals are about as wide as an ASK 21's circle, and few could be climbed at the bank a pilot flies. The *narrow* sky in the menu is the paper's |
| About twice the paper's density of thermals, for the same zi | The density was tuned and flown at zi 1400 m and kept when the default depth became 2000 m |
| With *Sharper thermal edges*, on by default: a ring of sink around each thermal, from its outer radius to 1.5 times it, deepest at 0.2 of its mean updraft; twice the sink between thermals; a jolt on entering and leaving lift; and bumps at the edges | In the paper the ring exists only in the upper half of the layer and is weak, and its edges are smooth. A pilot finds a thermal by its edge |

The jolt is the extra lift a wing gets when its angle of attack rises with the air, ½ ρ V S C<sub>Lα</sub> w, applied only while the air's speed is changing, and fading over the wing's own response time, about 0.4 s in the ASK 21. It is square to the flight path, so it adds no energy. The bumps are a field of small cells of vertical air, 20 m across, as strong as the lift changes where the glider is: none in even air, more at the edges and low down. Both change only how the climb feels, never the climb itself.

## The day

The menu sets the day: the sky (wide, medium or narrow thermals), the strength w\* at the best hour, the depth zi in the afternoon, and the seed. A named day sets all of them at once.

- **Daily cycle,** on by default. No data in X-Plane gives the heat the ground puts into the air, so the sun stands in for it. The heat goes with the sun's height above 10°. The depth grows through the morning with the heat put in so far, and stops growing in mid-afternoon. The strength goes as the cube root of heat times depth, as w\* does in the atmosphere, scaled so that the day's best moment, around 13:00 solar time, gets the menu's w\*. Each thermal keeps the depth of the hour it was born, so the morning's are low and narrow and the base rises through the day.
- **A blue morning.** A thermal born before the depth reaches 0.55 of the afternoon's carries no cloud, so the first cumulus come between about 10:00 and 10:40 solar time, low.
- **Cloud base from X-Plane's weather,** an experiment, off by default. Temperature and dew point at the ground, from X-Plane's weather layers, give the height where a rising parcel would condense: about 125 m per degree of spread between them (Espy's rule). That base, kept between 1000 m and 3500 m above the ground, takes the place of the menu's depth.
- **Good and bad areas,** on by default. A smooth map over the globe, with features 10 to 25 km across, drawn from the seed and the date, sets how many thermals each tile gets and how strong they are: about 1.6 times as many and 1.2 times as strong in the best 15% of the map, about 0.4 and 0.8 in the worst 15%. The sky as a whole holds as many as without it. The areas drift with the wind, as an air mass does.
- **X-Plane's clouds take the sun away.** X-Plane gives its cloud layers at the aircraft, their type and coverage, but not where each of its clouds is. Each layer screens the sun by its coverage times a weight for its type (cirrus little, stratus much), and the heat that reaches the ground is 1 − 0.9 C², with C the sky's combined cover. The strength goes with its cube root: about 92% of a clear sky's at half cover, 46% under a closed overcast. In rain there are no thermals. The change follows the weather over a few minutes, since ground does not heat or cool at once.

## Clouds

The plugin draws its own cumulus. X-Plane's clouds carry no thermal of this plugin, and its cumulus are best left off.

- **Which thermals carry one.** About 3% of them: those with the largest flow of air, width squared times strength, which would carry moist air highest, and long-lived enough for a cloud to form and fade. With the defaults that is one cloud every 2.8 km or so. Which thermals carry a cloud depends on their own numbers, never on where the glider is.
- **A cloud follows its thermal's life.** It forms as the thermal grows, is full while it is at its best, thins as it fades, and lingers a few minutes after it dies: half gone after about a minute and a half, all gone after three and a half. A thin cloud may have nothing left under it.
- **Its size** goes with its thermal's strength and width, smaller under X-Plane's clouds, and fewer of them form there. A typical cloud is about 850 m wide and 420 m tall.
- **Its height.** Real bases are level, so each cloud keeps one height for life: the higher of a level for the area, set at 0.75 zi above the ground where the sky begins, and the highest ground under it and along its drift plus 300 m.
- **The lift ends with its cloud.** Each thermal's height is counted from a floor of its own, set so that its cloud's base is at the top of its lift, over any ground. A thermal with no cloud ends at the area's level.
- **How they are drawn.** Each cloud is one X-Plane object with a particle emitter. Particles live 144 to 216 s and stay where they were born, so a cloud is shaped by how fast it is fed. Far clouds get fewer particles, and the rest fill in as the glider approaches. X-Plane draws such objects in the reverse of the order they were made and does not sort them by distance, so at the start of a sky the plugin makes them in rings of distance, nearest first, and hands a cloud over to another ring's object as the glider moves. What was found about X-Plane's emitters along the way is in [this finding](findings/particle-emitters.md).

## Wind

The wind is X-Plane's, real or set by hand. The plugin reads it and writes none.

Thermals and clouds keep the places they were generated with, in a frame that moves with the air. The plugin integrates the wind at the glider over time into an offset, asks the engine for the lift at the glider's position minus that offset, and draws clouds and markers at theirs plus it. In a steady wind glider and thermal drift together, and a circle needs no correction: flown by script in X-Plane 12.4.3 at 15 kt, a circle with no correction climbed within 0.02 m/s of the same circle in calm air. A change of wind moves nothing at once, only the rate of drift. With no wind the offset stays at zero and the sky is the calm one.

In wind shear, the wind at the glider carries the sky. It keeps a glider with its thermal at any height. Two experiments are in the menu, off by default: thermals that lean upwind lower down, as real ones do under a cloud, and the sky carried by the wind at the clouds' base.

## The lift on the glider

A plugin cannot move X-Plane's air at a point, only push on the aircraft. So the lift is applied as the energy rising air would give the glider. Air rising at w gives power m g w to a glider of mass m, and a force F along the flight path gives F V, so

F = m g w / V<sub>TAS</sub>

along the airspeed vector, split into the aircraft's axes by its angle of attack and sideslip, makes any glider climb w faster than in still air at any speed. There is no constant to calibrate per aircraft. Measured by script in X-Plane 12.4.3 in the Laminar ASK 21, the gain in climb is w within 0.01 m/s at different speeds and banks, and within 0.002 m/s at 60, 30 and 20 frames per second.

- **Where the air is sampled:** at the centre, both wingtips and the tail, at their real positions, so a banked wing spans less ground. The energy uses the average across the span.
- **The roll.** A lift that changes across the span turns each part of the wing's angle of attack as a roll rate would, so the moment is the aircraft's own roll damping applied to that rate, ¼ ρ V S b² C<sub>lp</sub> g, with g the change of lift per metre of span. C<sub>lp</sub> comes from the wing's shape, read from the aircraft's file: its span, area and taper. A glider whose wing is not in the usual parts of its file is treated as an ASK 21 for this.
- **Overbanking.** A force makes the glider rise through the air, which real rising air does not. In a turn the outer wing is faster, so it loses less angle of attack and lifts more, and a climbing turn overbanks. The plugin adds the opposite roll moment, which takes away about two thirds of the extra stick it would ask for.
- **Each frame** the force is added to X-Plane's force inputs before the flight model runs, so it counts once whatever the frame rate. Pause and replay are respected.

Because the lift is a force, a glider's own instrument that computes netto from its polar may read wrong. X-Plane's total energy reads it right, within 0.03 m/s over 20 s, so its audio vario hears the thermals.

## The HUD and the markers

The HUD uses only what a glider could sense. Total energy is X-Plane's. Netto subtracts the glider's sink, from a polar measured by script in the Laminar ASK 21, the one glider with a measured polar. The centring arrow comes from how netto changes with heading around the circle, never from where the engine knows the thermal is, and is reliable from about 60 m off centre.

The training markers show up to 20 thermals within 3 km with at least 1.5 m/s at their core at the glider's height: the core's own lift, without the neighbours'.

## Cost

Measured in X-Plane 12.4.3 on Windows 11: the flight loop takes 140 to 195 µs a frame, and the HUD about 0.3 ms, most of it in drawing text. A frame at 60 frames per second lasts 16.7 ms.

## Known limits of the design

- The day's strength is the menu's, not the weather's. Only the cloud base can come from X-Plane's weather.
- The sky depends a little on the flight: where there is water, the clouds' level and each thermal's floor are read from the ground as the glider meets it, and the wind's offset starts at zero when the aircraft is loaded. So two pilots at the same place and time do not see the same sky.
- Only the Laminar ASK 21 has a measured polar, so other gliders get no netto.
- The numbers of the tuned sky are first guesses, kept or changed by flying.
