# Working notes

These are the project's working records, written while the work happened. They keep the reasoning, the dead ends and the raw measurements, so they are long, dated and full of internal names, and older parts can be out of date. For a readable account, start with the [documentation](../docs/README.md).

| File | What it records |
| --- | --- |
| [SPEC.md](SPEC.md) | The current design, decisions and roadmap. This one is kept up to date |
| [baseline.md](baseline.md) | Phase 0: measurements of the starting point and an audit of X-Plane's native soaring |
| [phase1.md](phase1.md) | Phase 1: the X-Plane adapter and the lift forces |
| [phase2.md](phase2.md) | Phase 2: training markers, cumulus and the sky under them |
| [phase3.md](phase3.md) | Phase 3: wind |
| [phase4.md](phase4.md) | Phase 4: reading a flight, water, how high a climb goes, changing the sky and the clock, a flight by hand through a cloud, and the lift that ends with its cloud |
| [phase5.md](phase5.md) | Phase 5: the day, what X-Plane's weather offers for a cloud base |
| [hud.md](hud.md) | The soaring HUD: how it is drawn and what it shows |
| [shadows.md](shadows.md) | A lab test of cloud shadows on the ground, set aside |

Names used throughout:

- **Test pilot:** a scripted autopilot (`tools/testpilot/`) that flies measurement segments through X-Plane's local web API. "By hand" means a person flew it.
- **Tests A–J:** the measurements defined in [baseline.md](baseline.md).
- **Alex's plugin:** [xplane_thermals](https://github.com/alexferrer/xplane_thermals), by Alex Ferrer, the project's inspiration and first point of comparison.
