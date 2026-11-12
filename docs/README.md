# XP-Gliding documentation

XP-Gliding's current version is 0.8. This documentation is growing with it, and describes what is true today.

## Flying it

- [Pilot guide](pilot-guide.md): installing the plugin, a first flight, reading the sky, the HUD, the menu and the known limits.

## Findings

What was measured about X-Plane 12 along the way, written for plugin authors and anyone curious about how it handles soaring. Each finding gives its method and limits, so the results can be checked or repeated.

- [Measuring X-Plane 12's native soaring](findings/native-soaring.md): ridge lift, thermals and wave, measured in flight, with the thermal part still incomplete.
- [What X-Plane 12's particle emitters do, found by building clouds](findings/particle-emitters.md): driving each instance, drawing distance, the order instances are drawn in, what the wind does to particles and the cost, mostly judged by eye from screenshots.

## Still to come

- **How it works:** the thermal model, how lift is applied, the clouds and the wind. To be written once the model settles.
- **More findings:** how plugin forces behave, what drawing costs, and how X-Plane's native thermals behave.

## For contributors

- [Writing guide](writing-guide.md): how these pages are written.
- [Working notes](../notes/README.md): the full records of the work, including the current design and [stages](../notes/SPEC.md#stages).
