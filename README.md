# xp-gliding

A thermal soaring plugin for X-Plane 12: thermals you can find by reading the clouds and climb in by hand.

It builds on what X-Plane 12 already does well. The weather, the wind, the ridge lift and the flight model stay X-Plane's, and the plugin adds thermals tied to clouds of their own.

![The plugin's soaring HUD while circling in a thermal, in the Laminar ASK 21](docs/images/hud-in-thermal.jpg)

> **Status: in development, not released yet.** It flies, and for now all the work goes into the thermal model, tuned by flying. A release and an install guide come at the end, if the result is good.

## What it does today

- **Thermals** with a life cycle: they grow, peak and fade, and never vanish abruptly. The same seed, date and place give the same sky.
- **Cumulus** drawn by the plugin over the thermals that carry one. Each forms and fades with its thermal, so a cloud means something.
- **Lift with no per-aircraft calibration.** It is applied as the energy rising air would give the glider, and measured within 0.01 m/s of the intended climb at different speeds, banks and frame rates. The reference glider is the Laminar ASK 21.
- **Thermals and clouds that follow the wind.** The wind is X-Plane's, real or set by hand: the plugin reads it and has no wind of its own.
- **A soaring HUD:** total energy, netto, average climb, height to the top of the lift, the wind and a centring aid.
- **A menu** in *Plugins → xp-gliding* to choose the sky and the day, saved between sessions. It grows along with the model.
- **Optional training markers** showing where the thermals are.

## Where it is going

The next work is on the model, in this order: thermals in a wind that changes with height, a sound default sky that respects the terrain, strength and cloud base taken from X-Plane's weather with a daily cycle, and thermals born where the ground and sun would trigger them. The details are in the [roadmap](notes/SPEC.md#phased-roadmap).

## Documentation

- **[Documentation](docs/README.md):** start here, including what was [measured about X-Plane's native soaring](docs/findings/native-soaring.md).
- **[Working notes](notes/README.md):** the full records of the work, with the current design and roadmap.

## What it is not

It is not a simulation of the atmosphere. The thermals start from a published model ([Allen, 2006](https://ntrs.nasa.gov/citations/20060004052)) and are tuned by flying, with each departure from the paper documented. It is not a soaring simulator either: no tasks, no other gliders, no wave. Condor's soaring is the inspiration, not the target, and a glider still flies as well as its own flight model allows.

## Principles

1. **The sky must be readable.** What you see tells you where the lift is.
2. **Native first.** What X-Plane does well is left alone, and that is decided with measurements.
3. **The flight decides.** Papers give the first numbers, and a number stays only if it flies well by hand.

## How it is built

- **Atmospheric engine:** pure Python, deterministic, independent of X-Plane, tested and plotted outside the simulator.
- **X-Plane adapter:** an [XPPython3](https://xppython3.readthedocs.io/) plugin that applies the lift as forces and draws the clouds, markers and HUD.

## Acknowledgements

Inspired by Alex Ferrer's [xplane_thermals](https://github.com/alexferrer/xplane_thermals), which proved that thermal soaring in X-Plane 12 through a plugin is possible.

## License

[GPL-3.0-or-later](LICENSE).
