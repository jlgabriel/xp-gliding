# Writing guide

The project keeps two kinds of text. [`notes/`](../notes/README.md) records how the work went. `docs/` says how things are, for a reader who knows nothing about the project's history. When a page here and a note disagree about the plugin's design, check [`notes/SPEC.md`](../notes/SPEC.md) and fix whichever is wrong.

## Rules for `docs/`

- **Describe the present.** Write "thermals follow the wind", not "thermals were changed to follow the wind". The history belongs in the notes.
- **Give reasons, not people or dates.** A decision is explained by why it holds. Dates appear only to say when something was measured.
- **Use no internal names.** Phase numbers and test letters mean nothing to a reader. Name the thing, and link to the notes for the full record.
- **Say how each number was obtained.** Give the X-Plane version, the glider and the method, and whether it was flown by hand or by script.
- **Separate what was measured from what it might mean.** Mark an interpretation as one.
- **State what was not found precisely.** "Not found in these flights" is a result. "Does not exist" needs more evidence.
- **Keep to measurements about other people's work.** Describe what X-Plane and other plugins do, without judging them.
- **Present the plugin as another option for soaring in X-Plane.** Say what it does, without ranking it against what the simulator offers.
- **Write in plain English,** with SI units first and aviation units where pilots expect them (wind in knots).

## Shape of a finding

Each page in [`findings/`](findings/) covers one question about X-Plane, and is useful without installing the plugin:

1. **The answer,** in the first lines.
2. **How it was measured:** setup, method and tools.
3. **Results,** with tables a reader can check.
4. **Limits:** what was not tested, and what could change the answer.
5. **What it means in practice** for someone building on X-Plane.
6. **Where the full record is** in the notes.
