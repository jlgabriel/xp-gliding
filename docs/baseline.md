# Phase 0 baseline: xplane_thermals in X-Plane 12

Measurements of Alex Ferrer's [xplane_thermals](https://github.com/alexferrer/xplane_thermals) (commit `082dd7d`) with the Laminar ASK 21, so that phase 1 has numbers to beat, plus an audit of the soaring lift XP12 already models natively (tests H–J), which decides what stays native under the SPEC's native-first principle. See the roadmap in [SPEC.md](SPEC.md).

**Done when:** every result table below is filled from a recorded flight log, the predictions section says which predictions held, and the native audit says what XP12 does for ridge, thermals and wave.

**Status:** test A flown on 2026-11-02 (four of six speeds); tests B–J pending.

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
- **Test pilot** (`tools/testpilot/`, added 2026-11-02), so Claude can fly the measurement segments instead of a human. It drives X-Plane from outside through the local web API (port 8086; WebSocket pushes at ~10 Hz, REST requests take ~50 ms each): `airstart.py` starts the ASK 21 in the air over KHOB in calm, clear weather through the Flight Initialization API; `hold.py` takes the stick through the joystick-override datarefs and holds an IAS with wings level, toggling the flight logger around the steady part, and gives the controls back on any anomaly. The control laws (`control.py`) are tested against a crude offline glider model. Not yet reachable from outside: the reference plugin's calibration mode, which lives in its Python module (a small addition to the logger plugin will expose it). Tests that need a human: F (feel) and the visual part of I.
  - First controlled flight (2026-11-02, air start at 2800 m MSL over KHOB, target 90 km/h for 60 s): the yoke signs are as assumed (+ pitch is nose up). Taking over from the dive an untrimmed ASK 21 enters seconds after an air start, it was within 1 km/h of the target after ~35 s and held 90.0–90.3 km/h with wings level from 45 to 60 s, needing +0.25 of aft yoke with the elevator trim at 0. Sink in that stretch, 0.96–0.99 m/s at ~2400 m MSL, agrees with the hand-flown test A (0.99 m/s at 89 km/h). Gotchas found: right after an air start X-Plane reports a placeholder airspeed for a moment, and the glider noses over within seconds unless controlled at once; when the script lets go the untrimmed glider dives again.
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

### Native audit (H–J)

These tests measure XP12's own lift, so the reference plugin is **disabled** throughout (*Plugins → Thermal Simulator → Disable Plugin*) and the logger records as usual. The native lift at any moment is the measured `vs_te` minus the still-air sink from test A at the same IAS and bank. The logger also records `native_thermal_ms` (`sim/weather/aircraft/thermal_rate_ms`, what XP12 says the aircraft feels from thermals) and the wind at the aircraft. Note the location of each pass; the log has lat/lon and AGL.

**H. Native ridge.** Manual weather: steady wind of 20–25 kt, no turbulence, no thermals, clear sky. Pick a long, straight ridge roughly perpendicular to the wind (rotate the wind direction to match it). Fly beats along the windward face at 90 km/h at three heights: about ridge-top level, 100–200 m above, and 300–500 m above. Then cross to the lee side at ridge-top level and fly a straight pass downwind of the crest. One mark pair per pass. Repeat one windward pass at 10–12 kt to see how lift scales with wind. Answers: how strong native ridge is, how high it reaches, whether there is lee-side sink, and whether it feels smooth or turbulent.

**I. Native thermals.** Manual weather: light wind (≤ 5 kt), cumulus layer (few or scattered), thermals switched on in *Customize Weather* with a known slider value; write down the value. Flat terrain away from water, sun high. Fly under several cumulus; for each one, circle under it at ~90 km/h and 30–40° bank for three turns (one mark pair), and fly straight passes between clouds (one mark pair). Note whether each cloud had lift, the climb, how wide the thermal felt, whether there was sink around it, and whether a wing lifts on entry. Then repeat one short series with **real weather** to check whether native thermals appear at all with it (the forum dispute). Answers: native strength against the slider, link to cumulus, size, sink ring, entry feel, and the real-weather question.

**J. Native wave.** Manual weather: strong wind roughly perpendicular to a long mountain range (30–40 kt at ridge height, increasing with height), stable air, no thermals, clear sky or a lenticular-looking layer if the weather allows it. Fly straight, slow passes downwind of the range, parallel to it, at 1–2 km, 4–6 km and 8–10 km from the crest, and at two heights (above crest level and well above, e.g. +1500 m). One mark pair per pass. Answers: whether any smooth, steady lift appears downwind (wave) or only ridge and lee sink near the crest. If nothing appears, wave is ours to build.

**After the session.** Check `XPPython3Log.txt` for load errors (prediction 7) and for the paused-log spam (prediction 8). Run the analyzer and paste its Markdown table below.

## Results

### Conditions

| Item | Value |
| --- | --- |
| Date, sim time | 2026-11-02, 16:54–17:12 UTC in the sim (test A) |
| Location (airport / lat, lon) | Hobbs, NM (KHOB, 3661 ft / 1116 m), around 32.69 N, 103.21 W; flat Llano Estacado |
| Sun pitch (deg) | 37.6–38.2 |
| Total mass (kg) | 541 (Laminar default load) |
| Weather settings | Manual, preset Clear, no cloud or wind layers, thermals 0 ft/min, 45 °F at KHOB (ISA +0) |
| Graphics preset, typical fps | 60 fps steady (looks capped) |

### A. Still-air polar

Plugin of reference disabled (`alex_enabled` 0, all `*_plug_acf` forces 0), wind 0, native thermal rate 0. No marks were used: each speed was recorded as its own log (`flightlog_20261102_220548`, `_220719`, `_220923`, `_221051`) and the steady stretch of each was picked from 10 s windows (IAS standard deviation below ~0.5 km/h). Flown at 1700–2400 m MSL, so TAS is 10–16% above IAS; the glide ratio uses TAS and does not depend on density, and the last column scales the sink to sea level (× IAS/TAS) for comparison with the published figures.

**Flown by the test pilot (2026-11-02, 22:46–22:56 local, the reference set).** Same conditions, each speed from its own air start at 2800 m MSL over KHOB, 45 s to settle, then 60 s recorded (`flightlog_20261102_224632` to `_225533`). IAS held within a standard deviation of 0.07–0.40 km/h and bank within 0.1°, at 2660–2710 m MSL. The 70 km/h run settled at 77 km/h because the controller's pitch command hit its limit (fixed afterwards).

| IAS (km/h) | vs_te (m/s) | Glide ratio | Sea-level sink (m/s) | Note |
| --- | --- | --- | --- | --- |
| 77 | −1.01 | 24.9 | 0.86 | target was 70; TAS 91 km/h |
| 80 | −1.00 | 26.0 | 0.86 | TAS 94 km/h |
| 90 | −1.00 | 29.0 | 0.86 | TAS 104 km/h |
| 100 | −1.04 | 30.8 | 0.90 | TAS 115 km/h; best glide |
| 120 | −1.27 | 30.1 | 1.11 | TAS 138 km/h |
| 140 | −1.71 | 26.0 | 1.50 | TAS 160 km/h |

How long a segment needs to be: splitting each 60 s record, any 30 s window gives the same sink within 0.002 m/s up to 120 km/h and 0.011 m/s at 140 km/h; even 10 s windows stay within 0.008 m/s up to 120 km/h (0.029 at 140). In still air with the test pilot, 30 s segments are enough; the time that matters is the ~45 s of settling after each air start. Segments in lift (tests E, I) still need several full turns.

**Flown by hand (2026-11-02, earlier).**

| IAS (km/h) | vs_te (m/s) | Glide ratio | Note |
| --- | --- | --- | --- |
| 73 | −1.01 | 23.3 | 80 s, TAS 85 km/h at 2270 m MSL; sea-level sink 0.87 m/s |
| 89 | −0.99 | 28.4 | 30 s (IAS drifted 90 → 85 afterwards), TAS 101 km/h at 2370 m MSL; sea-level sink 0.87 m/s |
| 100 | | | not flown |
| 115 | −1.14 | 30.6 | 50 s, TAS 126 km/h at 1840 m MSL; sea-level sink 1.04 m/s |
| 137 | −1.55 | 26.6 | 60 s, TAS 149 km/h at 1690 m MSL; sea-level sink 1.43 m/s |

**Reading.** Hand-flown and automatic runs agree within ~0.02 m/s where they overlap (73–77, 89–90 and 137–140 km/h), so the polar is solid. At 541 kg, Laminar's ASK 21 sinks about 0.86 m/s at sea level from 77 to 90 km/h, against the published 0.64 m/s minimum sink and 0.74 m/s at best glide (mass not stated). Its best glide is about 31 at 100 km/h IAS (flat, 30–31 from 100 to 120 km/h), against 34 at 90 km/h for the real glider. So the sim glider is noticeably worse at low speed and its polar is flat below 90 km/h. Mass explains only part of it (sink scales with √m: even at 450 kg the sea-level sink would be ~0.79 m/s). This is the glider's own flight model, which the project does not correct (SPEC: polars are measured, not fixed); it matters because every lift figure is measured as a difference from this polar. Also noted: with the elevator trim at 0, the ASK 21 flies hands-off at about 120 km/h (the test pilot needed no yoke there), which is why it noses over right after an air start at 90 km/h.

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

### H. Native ridge

| Pass | Side | Height above crest (m) | Wind (kt) | IAS (km/h) | vs_te (m/s) | Native lift (m/s) | Note |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Windward | ~0 | | | | | |
| 2 | Windward | 100–200 | | | | | |
| 3 | Windward | 300–500 | | | | | |
| 4 | Lee | ~0 | | | | | |
| 5 | Windward, light wind | ~0 | | | | | |

### I. Native thermals

Thermal slider value: ; weather mode:

| Pass | Under cloud? | Bank (deg) | vs_te (m/s) | Native lift (m/s) | `native_thermal_ms` | Sink around? | Wing lifts on entry? | Note |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | | | | | | | | |
| 2 | | | | | | | | |
| 3 | | | | | | | | |
| Real weather | | | | | | | | |

### J. Native wave

| Pass | Distance downwind of crest (km) | Height (m MSL) | Wind (kt) | vs_te (m/s) | Native lift (m/s) | Smooth or turbulent | Note |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | 1–2 | | | | | | |
| 2 | 4–6 | | | | | | |
| 3 | 8–10 | | | | | | |
| 4 | 1–2 | +1500 | | | | | |
| 5 | 4–6 | +1500 | | | | | |
| 6 | 8–10 | +1500 | | | | | |

### Native audit conclusion

| Phenomenon | Modeled natively? | Good enough to keep? | Gaps found |
| --- | --- | --- | --- |
| Ridge | | | |
| Thermals | | | |
| Wave | | | |

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
| none | A | One log per speed instead of marks (2026-11-02) |

### Other observations

- **Load (prediction 7):** with the flat install both Python plugins load and enable without errors (`XPPython3Log.txt`, 2026-11-02).
- **Replaced datarefs:** at load, X-Plane reports that `sim/weather/wind_speed_kt[0]` and `sim/weather/wind_direction_degt[0]`, which the reference plugin uses for thermal drift, "have been replaced". Whether they still return the wind is to be checked in a test with wind.
- **Native thermal control:** XP 12.4.3's manual weather screen calls the thermal setting "Climb Rate under Cumulus Clouds", in ft/min, which supports the reported link between native thermals and cumulus (test I).
