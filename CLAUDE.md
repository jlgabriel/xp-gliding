# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project

xp-gliding adds good thermals to X-Plane 12: thermals you find by reading the clouds and climb in by hand. Written in Python on top of XPPython3. Anything beyond that is out of scope unless the maintainer brings it back (see "Set aside" in the spec).

**[docs/SPEC.md](docs/SPEC.md) is the source of truth.** Read it before any design decision. If the simulator contradicts it, the observation wins and the spec gets updated in the same change. Items marked *verify* in the spec are assumptions, not facts.

## Working agreements

- **Language:** everything committed (code, comments, docs, commit messages, issues, PRs) is in English. Conversation with the maintainer is in Spanish.
- **Pace:** quality over speed. Work phase by phase as laid out in the spec's roadmap; each phase ends with a criterion verified by flying. Hand flights by the maintainer are the final judge of how the thermals feel.
- **Keep the spec current:** when a phase finishes or a *verify* item is resolved, update `docs/SPEC.md` (tick the checkbox, record the finding).
- **Commits:** only when the maintainer asks.

## Architecture rules

- The atmospheric engine is pure Python and **never imports `xp`**. It must be deterministic (seed + date + area → same sky) and testable outside X-Plane.
- The XP12 adapter is the only code that talks to the SDK. Minimize `xp.*` calls per frame; look up datarefs once; no object allocation in the per-frame loop.
- Use one explicit, documented coordinate system (east-north-up meters around a local origin); convert lat/lon with cos(lat).
- Lift is injected as energy (F = m·g·w / V_TAS), never with per-glider calibration constants.
- Target **Python 3.12** (XPPython3's bundled interpreter): no 3.13-only features. numpy is available in-sim.
- Plugin layout: `PI_xp_gliding.py` + package `xp_gliding/` with relative imports. In-sim "Reload scripts" is unreliable (crashes with numpy/imgui), so iterate on the engine outside the simulator with tests and plots.

## Reference code

`reference/xplane_thermals/` is a local, git-ignored clone of Alex Ferrer's plugin. Read it for ideas and behavior; **do not copy code from it** (its licensing is GPL-2.0 file / unversioned "GPL" headers, and the spec lists the design problems to avoid). This project is GPL-3.0-or-later.

## Local environment

Machine-specific paths (X-Plane install, Python) live in `CLAUDE.local.md`, which is git-ignored.
