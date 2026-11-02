# xp-gliding

A soaring layer for X-Plane 12: coherent thermals, ridge and wave lift, cumulus that live and die with their thermals, and AI gliders that share the same air — aiming for a Condor-like soaring experience anywhere in the world.

> **Status: design phase.** Nothing is ready to install yet. The full specification and roadmap are in [docs/SPEC.md](docs/SPEC.md).

## Guiding principle

**The air must be coherent.** Clouds, terrain, sun, wind and time of day tell the same story, and the glider flies inside that air mass. Every source of lift comes from a single atmospheric model; what you see in the sky is a consequence of that model.

## Architecture at a glance

- **Atmospheric engine** — pure Python, deterministic, independent of X-Plane, testable and visualizable outside the simulator.
- **XP12 adapter** — an [XPPython3](https://xppython3.readthedocs.io/) plugin that feeds the engine with position, time and weather, and applies lift as energy-based forces.
- **Offline tools** — terrain trigger maps, weather briefing, IGC analysis and replay.

## Acknowledgements

Inspired by Alex Ferrer's [xplane_thermals](https://github.com/alexferrer/xplane_thermals), which proved that thermal soaring in X-Plane 12 through a plugin is possible.

## License

[GPL-3.0-or-later](LICENSE).
