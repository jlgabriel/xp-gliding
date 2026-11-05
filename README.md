# xp-gliding

A thermal soaring plugin for X-Plane 12: thermals you can find by reading the clouds and climb in by hand.

It builds on what X-Plane 12 already does well. The weather, the wind, the ridge lift and the flight model stay X-Plane's, and the plugin adds thermals tied to clouds of their own.

> **Status: in development, not released yet.** It flies, and for now all the work goes into the thermal model, tuned by flying. A release and an install guide come at the end, if the result is good. Thermals and clouds now follow X-Plane's wind, flown so far by the test pilot and not yet by hand. The full specification is in [docs/SPEC.md](docs/SPEC.md).

## What it does today

- **Thermals** with a life cycle: they grow, peak and fade, and never vanish abruptly. The same seed, date and place give the same sky.
- **Cumulus** drawn by the plugin over the thermals that carry one. Each forms and fades with its thermal, so a cloud means something.
- **Lift with no per-aircraft calibration.** It is applied as the energy rising air would give the glider, and measured within 0.01 m/s of the intended climb at different speeds, banks and frame rates. The reference glider is the Laminar ASK 21.
- **Thermals and clouds that follow the wind.** The wind is X-Plane's, real or set by hand: the plugin reads it and has no wind of its own.
- **A soaring HUD:** total energy, netto, average climb, height to the top of the lift, the wind and a centring aid.
- **A menu** in *Plugins → xp-gliding* to choose the sky and the day, saved between sessions. It grows along with the model.
- **Optional training markers** showing where the thermals are.

## Where it is going

This stage is the model only, in this order:

1. **Wind (in progress).** Flown by hand in a uniform wind. Then shear: in a wind that changes with height, thermals do not tilt or deform yet, and the lift should sit upwind of its cloud.
2. **A sound sky.** A default sky chosen by flying, and the feel of a thermal judged by hand. Thermals that respect the terrain, since today they can appear over water and cloud heights in the mountains use the ground under the glider. Next to X-Plane's own clouds, which have not been flown with ours yet.
3. **The day.** Strength and cloud base from X-Plane's weather instead of two fixed settings, a daily cycle and cloud shadow.
4. **Terrain triggers.** Thermals born where they would be in reality, from the ground type, slope and sun.

At the end, if the result is good: refining the HUD, an audio vario, XCSoar, an install guide and a release, and a readable section with the findings for the community.

Set aside, with no plans: wave, ridge corrections, convergence lines, AI gliders, briefing, IGC and replay, force feedback, multiplayer, a native C++ plugin, racing.

## What it is not

It is not a simulation of the atmosphere. The thermals start from a published model ([Allen, 2006](https://ntrs.nasa.gov/citations/20060004052)) and are tuned by flying, with each departure from the paper documented. It is not a soaring simulator either: no tasks, no other gliders, no wave. Condor's soaring is the inspiration, not the target, and a glider still flies as well as its own flight model allows.

## Principles

1. **The sky must be readable.** What you see tells you where the lift is.
2. **Native first.** What X-Plane does well is left alone, and that is decided with measurements.
3. **The flight decides.** Papers give the first numbers, and a number stays only if it flies well by hand.

## How it is built

- **Atmospheric engine:** pure Python, deterministic, independent of X-Plane, tested and plotted outside the simulator.
- **X-Plane adapter:** an [XPPython3](https://xppython3.readthedocs.io/) plugin that applies the lift as forces and draws the clouds, markers and HUD.

## What we measured

Many of these findings may be useful to other X-Plane developers:

- [docs/baseline.md](docs/baseline.md): X-Plane 12's native ridge, thermals and wave, and the Laminar ASK 21's polar.
- [docs/phase1.md](docs/phase1.md): plugin forces, frame-rate independence and climbs in the engine's thermals.
- [docs/phase2.md](docs/phase2.md): instanced markers, particle clouds driven per instance, and their cost.
- [docs/phase3.md](docs/phase3.md): X-Plane's wind against a thermal, and particles carried by the wind.
- [docs/hud.md](docs/hud.md): drawing from XPPython3 under Vulkan, and what it costs.

## Acknowledgements

Inspired by Alex Ferrer's [xplane_thermals](https://github.com/alexferrer/xplane_thermals), which proved that thermal soaring in X-Plane 12 through a plugin is possible.

## License

[GPL-3.0-or-later](LICENSE).
