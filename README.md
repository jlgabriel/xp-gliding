# xp-gliding

Good thermals for X-Plane 12: you find them by reading the clouds and climb in them by hand.

X-Plane 12 draws cumulus and has good ridge lift, but in our tests no thermal could be found under its clouds. This plugin adds them. X-Plane keeps the weather, the ridge lift and the flight model.

> **Status: in development, not released yet.** It flies, and the thermal model is being tuned by flying. A release and an install guide will come once the model is done. For now it only works in calm air: wind is next. The specification and roadmap are in [docs/SPEC.md](docs/SPEC.md).

## What it does today

- **Thermals** with a life cycle: they grow, peak and fade, and never vanish abruptly. The same seed, date and place give the same sky.
- **Cumulus** drawn by the plugin over the thermals that carry one. Each forms and fades with its thermal, so a cloud means something.
- **Lift with no per-aircraft calibration.** It is applied as the energy rising air would give the glider, and measured within 0.01 m/s of the intended climb at different speeds, banks and frame rates. The reference glider is the Laminar ASK 21.
- **A soaring HUD:** total energy, netto, average climb, height to the top of the lift and a centring aid.
- **Optional training markers** showing where the thermals are.

## What is missing

- **Wind.** Thermals are fixed to the ground for now, so a glider circling in wind leaves them. This comes first.
- **Terrain.** Thermals can appear over water, and cloud heights in the mountains use the ground under the glider. Later, thermals should be born where they would be in reality, from the ground type, slope and sun.
- **X-Plane's own clouds.** Not flown together with ours yet.
- **The day from X-Plane's weather.** Strength and cloud base are fixed settings, with no daily cycle or cloud shadow.

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
- [docs/hud.md](docs/hud.md): drawing from XPPython3 under Vulkan, and what it costs.

## Acknowledgements

Inspired by Alex Ferrer's [xplane_thermals](https://github.com/alexferrer/xplane_thermals), which proved that thermal soaring in X-Plane 12 through a plugin is possible.

## License

[GPL-3.0-or-later](LICENSE).
