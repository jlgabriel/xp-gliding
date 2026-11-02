# Phase 0 baseline: xplane_thermals in X-Plane 12

Measurements of Alex Ferrer's [xplane_thermals](https://github.com/alexferrer/xplane_thermals) (commit `082dd7d`) with the Laminar ASK 21, so that phase 1 has numbers to beat. See the roadmap in [SPEC.md](SPEC.md).

**Done when:** every result table below is filled from a recorded flight log, and the predictions section says which predictions held.

**Status:** protocol drafted, plugins installed, nothing flown yet.

## Setup

| Item | Value |
| --- | --- |
| X-Plane | 12.4.3 (Vulkan), Windows 11 |
| XPPython3 | 4.7.1, Python 3.12.2, numpy 2.5.4 |
| Reference plugin | xplane_thermals `082dd7d`, installed 2026-11-02 |
| Glider | Laminar Schleicher ASK 21 (ships with XP12) |
| Logger | `tools/flightlog/PI_xpg_flightlog.py` 0.1.0 |

**Installing the reference plugin.** Its files go *flat* into `Resources/plugins/PythonPlugins/`, not in a subfolder (its `install_howto.txt` still names the old `PythonScripts` folder, which is wrong for XPPython3 v4). Runtime files copied: `PI_ThermalSim.py`, `UI_about.py`, `UI_config_glider.py`, `UI_load_kk7.py`, `UI_stats.py`, `UI_thermals.py`, `draw_thermals.py`, `imgui_thermals.py`, `thermal.py`, `thermal_model.py`, `world.py`, `init_values.json`, `t_ring_50.obj`, `t_ring_200.obj`, `t_ring_800.obj`, `mt_scenery.obj`, `mt_scenery.png`, `mt_scenery.pss`, `easteregg.obj`, `EasterEggBaseColor.png`. To remove it, delete exactly those files. Its module names (`world`, `thermal`, ...) are generic top-level names shared with every other Python plugin.

**Factors in use.** The shipped `init_values.json` sets `lift_factor` 14, `thrust_factor` 19, `roll_factor` 4, `pitch_factor` 3 (the code defaults, used only if the file is missing, are 29 / 29 / 50 / 0). Sliders in *Configure Glider* are saved back to that file when X-Plane closes, so write down and restore the values after test C.

## Instruments

- **Flight logger** (`tools/flightlog/PI_xpg_flightlog.py`, copy it into `PythonPlugins/`). Writes one CSV row per frame to `Output/xp-gliding/flightlogs/`. Commands to bind to joystick buttons: `xp_gliding/flightlog/toggle` (start/stop) and `xp_gliding/flightlog/mark` (advance the mark counter; X-Plane speaks the number). It also logs the `*_plug_acf` forces before and after the flight model, and, read-only, the reference plugin's internal state (calibration mode, the lift its model asked for, factors).
- **Analyzer** (`tools/flightlog/analyze_flightlog.py LOG.csv --markdown`). One row per mark: frame rate, IAS, bank, and vertical speed three ways. `vs_te` (fit of energy height h + TAS²/2g against time) is the figure to use: it is not fooled by small speed changes during a segment.
- **XPPython3 Performance window** for µs per frame of each Python plugin (read by eye).
- **Reference plugin's Stats window** for a visual check of thermal strength and distance to center.

**Marks.** Press *mark* once when a test starts (glider trimmed and stable for ~10 s) and once when it ends. Odd marks are tests, even marks are transitions and are ignored. Keep a note of which mark is which test in the log sheet at the end.

## Predictions from reading the code

Written before flying, so the flight can confirm or refute them.

1. **Only the thrust term adds energy.** In steady flight a force perpendicular to the flight path does no work. The reference plugin adds `lift × 10 × lift_factor` along the body Y axis (≈ perpendicular to the path) and `−lift × 10 × thrust_factor` along the body Z axis (forward). So the climb gain should come almost entirely from the thrust term: Δvs ≈ F_thrust · V_TAS / (m · g). With the default factors and calibration at 1 m/s, F_thrust = 190 N; for m ≈ 500 kg at 90 km/h that is ≈ 0.97 m/s, close to 1 m/s by calibration, not by physics.
2. **Calibration gain grows with speed.** Because the thrust is a fixed force, the delivered power is proportional to speed: Δvs at 120 km/h should be ~1.33× the Δvs at 90 km/h. A physical lift injection gives the same Δvs at every speed.
3. **The 0.01 s callback may make lift depend on frame rate.** The plugin uses a legacy flight loop every 0.01 s and *adds* to the current value of each `*_plug_acf` dataref. If X-Plane resets those datarefs every flight-model cycle (the logger's pre/post columns will show it), then above 100 fps the force is missing on some frames and the climb gain drops roughly as 100/fps.
4. **Roll direction may be right after all.** SPEC diagnosis #3 says the wing sample points are rotated 90°. Re-reading with X-Plane's local frame (x east, y up, z *south*; `psi` clockwise from north) the "left wing" point lands on the aircraft's *right* side and the "right wing" point on its left, i.e. the labels are swapped, not rotated, and the roll formula `(right − left)` swaps the sign back. The tail point (heading + 90) is correctly behind. Prediction: with the core on your left, the left wing rises (roll right); flying through the core, no roll. Test F decides between this and the SPEC's reading. On magnitude: the wing points sit 75 m from the center (`wing_size` 25 × 3) against the ASK 21's ~8.5 m half-span, and `roll_factor` is applied twice (once in `calc_thermalx`, again in the flight loop), so the roll moment scales with its square.
5. **Pitch follows the wing difference, not wings versus tail.** `pitch = (right − left) × pitch_factor`: with the core on your left the nose pitches up, with the core on your right it pitches down, and flying straight into the core gives no pitch change. `pitch_factor` is also applied twice.
6. **Lift in a thermal is 4/3 of the model value, times the sun factor.** Four samples are summed and divided by 3, then multiplied by `(sun_pitch + 10) / 100`. The logger's `alex_lift_ms` already includes both.
7. **Issue #34 ("error on loading").** The issue has no details. `world.py` reads `Resources/plugins/PythonPlugins/init_values.json` at import time and calls `.get()` on the result; if the file is not at that path (for example, installed into a subfolder or the old `PythonScripts` folder) the result is `None` and the import fails with `AttributeError`, so the whole plugin fails to load. With a flat install it should load.
8. **Log spam while paused.** The plugin prints `"P "` every 10 ms while the sim is paused.

## Protocol

**Session conditions (all tests).** Laminar ASK 21, default load (the log records total mass). Weather set manually: no wind, no turbulence, no native thermals, clear sky. Flat terrain away from water and mountains. Daytime with the sun high, since the plugin scales thermals by sun elevation (the log records sun pitch). Start each test series at 1500–2000 m AGL. Logger recording during the whole session.

**A. Still-air polar, reference plugin disabled.** *Plugins → Thermal Simulator → Disable Plugin* (this also deletes its thermals). Straight, wings level, at IAS 70, 80, 90, 100, 120 and 140 km/h, at least 30 s each (60 s better). Gives the ASK 21's own sink in X-Plane, the baseline for every delta below, and shows whether Laminar's model flies like the real glider.

Reference figures for the real ASK 21 (checked 2026-11-02). No official numeric polar was found: the Schleicher manual that is online is for the ASK 21 Mi motor glider, and its polar is only a chart. The published figures come from secondary sources and state no mass:

| Figure | Value | Source |
| --- | --- | --- |
| Best glide | 34 at 90 km/h (≈ 0.74 m/s sink) | [Wikipedia](https://en.wikipedia.org/wiki/Schleicher_ASK_21), citing Jane's All the World's Aircraft 1988–89; [Waikerie Gliding Club](https://www.waikerieglidingclub.com.au/ask-21/) ("about 34 at 48.5 knots") |
| Minimum sink | 0.64 m/s at 67 km/h | Wikipedia (Jane's); Waikerie gives 0.65 m/s single-seated, no speed |
| Stall | 65 km/h | Wikipedia |
| Mass | empty 360–382 kg, maximum 600 kg | Wikipedia; Waikerie |

Treat them as a sanity check (within ~10%), not as a target: the sink depends on mass, and the log records Laminar's mass.

**B. Calibration mode, default factors.** Enable the plugin, open *Configure Glider*, tick *Calibrate Mode* (a constant lift everywhere, not scaled by the sun). Fly straight at 90 and 120 km/h with the calibration slider at 1, 2 and 3 m/s (6 segments). Δvs = vs_te(B) − vs_te(A) at the same IAS; ideal is Δvs = slider value at both speeds. Checks predictions 1 and 2.

**C. Decompose the force.** Calibration 1 m/s, 90 km/h: once with thrust factor 0 (lift 14), once with lift factor 0 (thrust 19). Checks prediction 1. Restore 14 / 19 / 4 / 3 afterwards.

**D. Frame rate.** Repeat B at 90 km/h, 1 m/s, at two frame rates: ~30 fps and the highest you can reach (above 100 fps if possible), using the GPU driver's frame cap or the graphics settings. Checks prediction 3; the logger records the actual frame rate and the pre/post forces.

**E. Thermals.** Calibration off. *Generate Random Thermals* with the defaults (strength 5 m/s, size 1500 m, 200 thermals, 1000 m separation), rings on to find them, Stats window open. In three different thermals, circle at ~90 km/h and 30–40° bank for at least three full turns, one mark pair per thermal. Compare the measured climb with `alex_lift_ms` and with the still-air sink from A corrected for bank.

**F. Roll and pitch feel.** Rings on, 90 km/h, straight and level, through the same thermal three times: core ~50–100 m to the left, core ~50–100 m to the right, straight through the core. Note which wing rises, whether the nose moves, and rate 1–5: perceptible, direction right, magnitude, smoothness. The log has roll and pitch rates. Checks predictions 4 and 5.

**G. Performance.** Same place, same view, 60 s straight glide each: plugin disabled, then enabled with 200 thermals and rings off. Read the reference plugin's µs/frame in the XPPython3 Performance window; the log gives mean and 1%-low fps.

**After the session.** Check `XPPython3Log.txt` for load errors (prediction 7) and for the paused-log spam (prediction 8). Run the analyzer and paste its Markdown table below.

## Results

Nothing recorded yet.

### Conditions

| Item | Value |
| --- | --- |
| Date, local time | |
| Location (airport / lat, lon) | |
| Sun pitch (deg) | |
| Total mass (kg) | |
| Weather settings | |
| Graphics preset, typical fps | |

### A. Still-air polar

| IAS (km/h) | vs_te (m/s) | Glide ratio | Note |
| --- | --- | --- | --- |
| 70 | | | |
| 80 | | | |
| 90 | | | |
| 100 | | | |
| 120 | | | |
| 140 | | | |

### B–D. Calibration mode

| Test | IAS (km/h) | Slider (m/s) | Lift / thrust factor | fps | vs_te (m/s) | Δvs vs A (m/s) |
| --- | --- | --- | --- | --- | --- | --- |
| B | 90 | 1 | 14 / 19 | | | |
| B | 90 | 2 | 14 / 19 | | | |
| B | 90 | 3 | 14 / 19 | | | |
| B | 120 | 1 | 14 / 19 | | | |
| B | 120 | 2 | 14 / 19 | | | |
| B | 120 | 3 | 14 / 19 | | | |
| C | 90 | 1 | 14 / 0 | | | |
| C | 90 | 1 | 0 / 19 | | | |
| D | 90 | 1 | 14 / 19 | ~30 | | |
| D | 90 | 1 | 14 / 19 | max | | |

Do the `*_plug_acf` datarefs reset every flight-model cycle (pre vs post columns)?

### E. Thermals

| Thermal | Model lift `alex_lift_ms` (m/s) | Bank (deg) | IAS (km/h) | vs_te (m/s) | Expected climb (m/s) |
| --- | --- | --- | --- | --- | --- |
| 1 | | | | | |
| 2 | | | | | |
| 3 | | | | | |

### F. Roll and pitch feel

| Pass | Wing that rose | Nose | Perceptible (1–5) | Direction right | Magnitude (1–5) | Smoothness (1–5) |
| --- | --- | --- | --- | --- | --- | --- |
| Core left | | | | | | |
| Core right | | | | | | |
| Through core | | | | | | |

### G. Performance

| Case | Mean fps | 1%-low fps | Plugin µs/frame |
| --- | --- | --- | --- |
| Plugin disabled | | | |
| Enabled, 200 thermals | | | |

### Predictions checked

| # | Prediction | Result |
| --- | --- | --- |
| 1 | Only the thrust term adds energy | |
| 2 | Calibration gain grows with speed | |
| 3 | Lift depends on frame rate above 100 fps | |
| 4 | Roll direction is right | |
| 5 | Pitch follows the wing difference | |
| 6 | Thermal lift is 4/3 × model × sun factor | |
| 7 | Issue #34 is a missing `init_values.json` | |
| 8 | Log spam while paused | |

### Log sheet

| Mark | Test | Note |
| --- | --- | --- |
| | | |
