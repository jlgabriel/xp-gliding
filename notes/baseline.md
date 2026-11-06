# Phase 0 baseline: xplane_thermals in X-Plane 12

Measurements of Alex Ferrer's [xplane_thermals](https://github.com/alexferrer/xplane_thermals) (commit `082dd7d`) with the Laminar ASK 21, so that phase 1 has numbers to beat, plus an audit of the soaring lift XP12 already models natively (tests H–J), which decides what stays native under the SPEC's native-first principle. See the roadmap in [SPEC.md](SPEC.md).

**Done when:** every result table below is filled from a recorded flight log, the predictions section says which predictions held, and the native audit says what XP12 does for ridge, thermals and wave.

**Status:** test A flown on 2026-11-02; tests B, C and the native audit H–J flown by the test pilot on 2026-11-03. Pending: D (frame rate), E (Alex's thermals), F (feel, by hand), G (performance), and a hand-flown look for native thermals under cloud centers.

## Setup

| Item | Value |
| --- | --- |
| X-Plane | 12.4.3 (Vulkan), Windows 11 |
| XPPython3 | 4.7.1, Python 3.12.2, numpy 2.5.4 |
| Reference plugin | xplane_thermals `082dd7d`, installed 2026-11-02 |
| Glider | Laminar Schleicher ASK 21 (ships with XP12) |
| Logger | `tools/flightlog/PI_xpg_flightlog.py` 0.1.0; 0.2.0 from 2026-11-03 05:10 (same columns, plus the `alex_*` datarefs) |

**Installing the reference plugin.** Its files go *flat* into `Resources/plugins/PythonPlugins/`, not in a subfolder (its `install_howto.txt` still names the old `PythonScripts` folder, which is wrong for XPPython3 v4). Runtime files copied: `PI_ThermalSim.py`, `UI_about.py`, `UI_config_glider.py`, `UI_load_kk7.py`, `UI_stats.py`, `UI_thermals.py`, `draw_thermals.py`, `imgui_thermals.py`, `thermal.py`, `thermal_model.py`, `world.py`, `init_values.json`, `t_ring_50.obj`, `t_ring_200.obj`, `t_ring_800.obj`, `mt_scenery.obj`, `mt_scenery.png`, `mt_scenery.pss`, `easteregg.obj`, `EasterEggBaseColor.png`. To remove it, delete exactly those files. Its module names (`world`, `thermal`, ...) are generic top-level names shared with every other Python plugin.

**Factors in use.** The shipped `init_values.json` sets `lift_factor` 14, `thrust_factor` 19, `roll_factor` 4, `pitch_factor` 3 (the code defaults, used only if the file is missing, are 29 / 29 / 50 / 0). Sliders in *Configure Glider* are saved back to that file when X-Plane closes, so write down and restore the values after test C.

## Instruments

- **Flight logger** (`tools/flightlog/PI_xpg_flightlog.py`, copy it into `PythonPlugins/`). Writes one CSV row per frame to `Output/xp-gliding/flightlogs/`. Commands to bind to joystick buttons: `xp_gliding/flightlog/toggle` (start/stop) and `xp_gliding/flightlog/mark` (advance the mark counter; X-Plane speaks the number). It also logs the `*_plug_acf` forces before and after the flight model, and the reference plugin's internal state (calibration mode, the lift its model asked for, factors). Since 0.2.0 (2026-11-03) it also exposes that state as datarefs, `xp_gliding/flightlog/alex_enabled`, `alex_cal_mode`, `alex_cal_ms`, `alex_lift_factor`, `alex_thrust_factor` (writable) and `alex_lift_ms`, `alex_dist_m` (read-only), so the test pilot can run the calibration tests from outside; writing them does not save Alex's preferences, but his plugin saves its current values when X-Plane closes.
- **Analyzer** (`tools/flightlog/analyze_flightlog.py LOG.csv --markdown`). One row per mark: frame rate, IAS, bank, and vertical speed three ways. `vs_te` (fit of energy height h + TAS²/2g against time) is the figure to use: it is not fooled by small speed changes during a segment.
- **Test pilot** (`tools/testpilot/`, added 2026-11-02), so Claude can fly the measurement segments instead of a human. It drives X-Plane from outside through the local web API (port 8086; WebSocket pushes at ~10 Hz, REST requests take ~50 ms each): `airstart.py` starts the ASK 21 in the air over KHOB in calm, clear weather through the Flight Initialization API; `hold.py` takes the stick through the joystick-override datarefs and holds an IAS with wings level, toggling the flight logger around the steady part, and gives the controls back on any anomaly. The control laws (`control.py`) are tested against a crude offline glider model. `calibrate_alex.py` flies tests B and C through the logger's `alex_*` datarefs. Tests that need a human: F (feel) and the visual part of I.
  - Since 2026-11-03 it also flies laterally (`control.py`): a bank command with an integral term, a rudder yaw damper on sideslip, and three guidances on top: hold a course over the ground, follow a straight line over the ground in a crosswind, or circle at a fixed bank. `pilot.py` is the shared runner (safety checks, logger toggling, a hook to switch guidance in flight); `hold.py` is its command line (`--course`, `--circle`); `airstart.py` takes wind layers, clouds and the native thermal setting, or real weather. First checks over KHOB in calm air at 90 km/h: a 90° course change settles within ±2° and ±0.2 km/h in about 25 s; circling at 35° holds the bank within 1° and the speed within 1 km/h, one turn every ~27 s at 2700 m MSL. Signs found: `sim/flightmodel/position/beta` is positive when the nose is right of the flight path (adverse yaw in a left turn), so the yaw damper needs a negative gain (−0.12 per degree brings the slip in a 35° turn from 2.4° to 0.5°).
  - `audit_native.py` flies the native audit (tests H–J) as missions: each pass is its own air start upwind of a straight line, a settle, and a recorded stretch along the line, with one log per pass and a manifest (`Output/xp-gliding/audit/manifest.jsonl`) that maps logs to passes. `analyze_native.py` turns them into lift profiles: native lift per 5 s window is vs_te minus the test A polar (sea-level sink scaled by TAS/IAS, and by cos(bank)^−1.5 in turns), and X-Plane's own terrain under the glider is elevation minus AGL.
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

**The polar as an XCSoar file (2026-11-06).** [`tools/xcsoar/ask21-laminar-541kg.plr`](../tools/xcsoar/ask21-laminar-541kg.plr) holds this polar for XCSoar: reference mass 541 kg, no water, the test pilot's 90, 120 and 140 km/h with their sea-level sink, and the wing area of the `.acf` (17.75 m²). The field order was read from XCSoar's `src/Polar/Parser.cpp`. The parabola through those three points gives 0.877, 0.866, 0.899 m/s at 77, 80, 100 km/h against the measured 0.86, 0.86, 0.90, and 1.04 and 1.43 m/s at the hand-flown 115 and 137 km/h, which it did not see. Its worst point is 0.897 against 0.87 at 73 km/h, since the real curve is flatter below 80. It gives a minimum sink of 0.857 m/s at 86 km/h and a best glide of 31.2 at 106 km/h.

XCSoar's own `ASK-21` is a different glider from this one: 468 kg, 74.1 km/h at −0.67, 101.9 at −0.90, 166.7 at −2.68. Scaled to 541 kg with √m, it sinks 0.77, 1.14 and 1.57 m/s at 90, 120 and 140 km/h, against the 0.86, 1.11 and 1.50 measured here, so it is optimistic by about 0.09 m/s at thermalling speeds.

Limits. The file is true at 541 kg, so XCSoar's all-up mass should be set to 541. It describes straight flight only, so the extra circling sink of this glider ([phase1.md](phase1.md), 0.19 m/s at 35°) is not in it. Above 140 km/h it is extrapolation. Not yet loaded in XCSoar: the plugin sends it no data until the NMEA link of phase 7.

### B–D. Calibration mode

Flown by the test pilot on 2026-11-03 (05:17–05:27 local), `calibrate_alex.py`: each segment is its own air start over KHOB at 2800 m MSL in calm, clear air (test A conditions, 541 kg), Alex's plugin enabled in calibration mode with the slider and factors of the row (set through the logger's `xp_gliding/flightlog/alex_*` datarefs, then restored), 40 s to settle, 35 s recorded at 2650–2700 m MSL. Δvs is measured against the test A polar at the same IAS and TAS. Alex's settings were read before and written back afterwards (enabled 0, factors 14 / 19).

| Test | IAS (km/h) | Slider (m/s) | Lift / thrust factor | fps | vs_te (m/s) | Δvs vs A (m/s) |
| --- | --- | --- | --- | --- | --- | --- |
| B | 90 | 1 | 14 / 19 | 60 | −0.02 | +0.98 |
| B | 90 | 2 | 14 / 19 | 60 | +0.97 | +1.98 |
| B | 90 | 3 | 14 / 19 | 60 | +1.97 | +2.98 |
| B | 120 | 1 | 14 / 19 | 60 | +0.06 | +1.34 |
| B | 120 | 2 | 14 / 19 | 60 | +1.41 | +2.70 |
| B | 120 | 3 | 14 / 19 | 60 | +2.77 | +4.06 |
| C | 90 | 1 | 14 / 0 | 60 | −1.06 | −0.06 |
| C | 90 | 1 | 0 / 19 | 60 | +0.04 | +1.04 |
| D | 90 | 1 | 14 / 19 | ~30 | | not flown |
| D | 90 | 1 | 14 / 19 | max | | not flown: X-Plane runs at a steady 60 fps here (cap), and the test pilot cannot change the frame rate |

**Reading.** The calibration is exact at the speed it was tuned for and wrong everywhere else, for the reason predicted from the code. At 90 km/h the gain is the slider value to within 0.02 m/s, linear from 1 to 3 m/s. At 120 km/h the same slider gives 1.35 times as much (1.34, 2.70, 4.06 m/s), and the TAS ratio between the two speeds is 1.33 (138 / 104 km/h), so the extra climb is a fixed force times speed. The decomposition confirms it: the 140 N normal force alone does nothing (−0.06 m/s, within noise), the 190 N forward force alone gives everything (+1.04 m/s; F·V / m·g = 190 × 28.9 / (541 × 9.81) = 1.03 m/s predicted).

Do the `*_plug_acf` datarefs reset every flight-model cycle? **Effectively yes.** The measured gain matches exactly one application of the force per frame (an accumulating force would have grown without bound); Alex's code adds to the current value each callback, so without a reset it would run away. The logger's pre/post columns read 0 throughout, even while the force acted, so the order is: logger's before-FM loop, then Alex's legacy callback writes, then the flight model uses the force and X-Plane clears it before the logger's after-FM loop. Those columns cannot see another plugin's force; the energy measurement is the reliable check.

Pitfall found on the way: after an X-Plane restart the Flight Initialization API loads the ASK 21 **empty** (360.6 kg, no pilot) unless the payload is given. The empty glider's CG is so far aft that it pitched up to 45° with full forward stick, which first looked like a problem with Alex's forces. `airstart.py` now always loads 90.2 kg on each of the two seat stations (541 kg total, the test A mass); with that, the 90 km/h sink is −1.00 m/s again, as in test A. Every test H–J flight before the restart was already at 541 kg.

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

Flown by the test pilot on 2026-11-03 (02:55–03:36 local), reference plugin disabled (`alex_enabled` 0, all `*_plug_acf` forces 0), `audit_native.py ridge`. **Site:** a narrow, straight ridge in central Pennsylvania, from about 40.645 N 78.09 W to 40.745 N 77.80 W, bearing 063°, crest 550–700 m MSL (675 m where the crossings were flown, at 78.02 W), valleys about 320 m on both sides; picked from SRTM data (opentopodata.org), and X-Plane's own terrain under the glider, logged as elevation − AGL, matches it. **Weather:** manual, clear, wind from 333° (square onto the north-west face) at the same speed from 1500 to 12000 ft, no turbulence, no thermals. All passes at 90 km/h IAS, wings level, one air start each; the line-following guidance held the track within ~15 m.

Two kinds of pass: **crossings**, flown downwind across the crest from 4 km windward to 3 km lee, which give the lift as a profile across the ridge; and the protocol's **beats** along the face, 600 m out from the crest line, which say whether the ridge can be soared. Lift is per 5 s window (`analyze_native.py`).

| Pass | Side | Height above crest (m) | Wind (kt) | IAS (km/h) | Native lift (m/s) | Note |
| --- | --- | --- | --- | --- | --- | --- |
| `beat_0` | Windward, 600 m out | ~0 (+75 → +210) | 25 | 90 | +1.36 mean (−0.1 to +2.8) | 250–340 m AGL; climbed 134 m in 7 km |
| `beat_150` | Windward, 600 m out | +150 | 25 | 90 | +1.25 mean (0 to +2.1) | 380–460 m AGL; climbed 110 m |
| `beat_400` | Windward, 600 m out | +400 | 25 | 90 | +0.90 mean (+0.2 to +1.6) | 550–690 m AGL; held height |
| `lee_0` | Lee, 600 m out | ~0 | 25 | 90 | −1.43 mean (down to −3.3) | lost 200 m in 1.6 km; aborted at 25 m AGL |
| `beat_0_12kt` | Windward, 600 m out | ~0 | 12 | 90 | +0.71 mean (+0.1 to +1.4) | 90–270 m AGL; lost 53 m in 7 km |

Crossings (lift per window against `wind × terrain slope` under the glider, the slope taken along the wind from the logged X-Plane terrain):

| Pass | Height above crest (m) | Wind (kt) | Max lift (m/s) | Max sink (m/s) | Gain on wind × slope | Correlation r |
| --- | --- | --- | --- | --- | --- | --- |
| `cross_50` | +50 (33 m AGL at the crest) | 25 | +3.9 | −3.7 | 0.82 | 0.90 |
| `cross_175` | +175 | 25 | +3.1 | −3.6 | 0.80 | 0.92 |
| `cross_375` | +375 | 25 | +2.2 | −2.8 | 0.54 | 0.89 |
| `cross_725` | +725 | 25 | +0.9 | −0.9 | 0.18 | 0.85 |
| `cross_175_12kt` | +175 | 12 | +1.6 | −1.6 | 0.71 | 0.91 |

The same gain, pooled over every crossing window with a slope term above 0.8 m/s and binned by height above the terrain directly below: 1.00 (0–150 m AGL), 0.73 (150–300), 0.68 (300–450), 0.50 (450–600), 0.23 (600–800), 0.13 (800–1100).

**Reading.** XP12's ridge lift is a **local slope model**: the vertical air speed is close to *wind × slope of the ground directly under the aircraft*, scaled down with height above that ground (about 1 near the surface, 0.5 at 500 m, roughly gone by 1000–1100 m AGL), and it scales linearly with the wind (the 12 kt crossing has the same gain as the 25 kt ones within noise). Consequences, all visible in the plots (`plots/native/cross_*.png`):

- Lift exists only **over the windward slope**. It starts where the ground starts rising (no lift band upwind of the foot of the slope) and stops at the crest; there is no lift above or ahead of the crest beyond what the slope underneath gives.
- **Lee sink is the mirror image** of windward lift: as strong as the lift on a slope of the same steepness (−3.7 m/s at 25 kt just behind the crest), and it is still there at 600 m out. A crest-level beat on the lee side lost 200 m in 1.6 km.
- **Any slope works the same way**: small bumps on the valley floor give their own lift and sink (+1 to +2 m/s over a 25 m rise in `cross_375` at 6.6 km), and the noise of the beats follows the gullies of the face.
- **Smooth air:** no turbulence, no rotor, no gusts with turbulence set to 0; the glider flew lee passes as smoothly as windward ones.
- **Soarable:** at crest level with 25 kt the ASK 21 gained ~130 m along 7 km of face; with 12 kt it slowly lost height.

Against the real thing: real ridge lift peaks ahead of and above the crest, reaches a few hundred meters above it, and the lee holds sink plus rotor turbulence when the wind is strong. XP12 has the right order of magnitude where it matters for ridge running (close to the face), but the band in front of the face and above the crest is missing, and its lee is smooth sink without rotor. These are the candidate gaps for phase 4 (see the native audit conclusion).

### I. Native thermals

Flown by the test pilot on 2026-11-03 (03:38–04:40 local), reference plugin disabled, over KHOB at local noon on 2 November (sun ~38° high), wind 5 kt from 270°, `audit_native.py thermals`. The plan was to cruise, circle in every thermal met and measure it; no thermal was met, so the result is about the air between thermals. Lift per 5 s window as in test H.

| Run | Weather | Thermal setting | Height (m AGL) | Distance flown (km) | Native lift (m/s) |
| --- | --- | --- | --- | --- | --- |
| `thermals_0_straight` | Custom: cumulus 40%, base 9500 ft MSL (1780 m AGL), tops 13000 ft | 0 | 1450 → 1250 | 6 | −0.01, sd 0.00 |
| `thermals_500_straight` | Same | 500 fpm (2.54 m/s) | 1440 → 1170 | 6 | −0.35, sd 0.02 |
| `thermals_500` (hunt) | Same | 500 fpm | 1630 → 400 | 30 | −0.35, sd 0.06 (max −0.17) |
| `thermals_500_2860` | Same, flown just below cloud base | 500 fpm | 1740 → 1090 | 15 | −0.36, sd 0.04 |
| `thermals_vfr_scattered_500_2600` | Preset *vfr_scattered* (cumulus 37.5%, base 2880 m MSL) | 500 fpm | ~1500 → 1100 | 12 | −0.31, sd 0.04 |
| `thermals_convective_500_2600` | Preset *convective* (cumulus and cumulonimbus 12.5%, base 1670 m MSL, i.e. below the glider) | 500 fpm | ~1500 → 1200 | 12.5 | +0.01, sd 0.18 (−0.56 to +0.41) |
| Real weather | `use_real_weather` | 0.62 m/s regional (set by X-Plane) | — | — | not measured: the glider was upset (bank past 70°) within seconds of both air starts, in a ~40 kt real wind |

A screenshot from the chase view during the custom runs (X-Plane's own `sim/operation/screenshot` command) shows a normal field of cumulus at the base height, with their shadows on the ground, so the clouds were there.

**Reading.**

- **No thermal was found** in about 75 km of straight flight under 40% cumulus cover (custom and preset), between 400 m AGL and just below cloud base. A real day like that has a usable thermal every few kilometers. Whatever XP12 does under its cumulus, a glider flying straight does not run into it; whether it exists at all, and how narrow it is, needs one hand-flown check aiming at cloud centers (the test pilot cannot see the clouds).
- **Turning the thermals on adds a uniform sink everywhere**: −0.35 m/s at the 500 fpm setting (about 14% of the setting), constant to ±0.05 m/s over 30 km and from 400 m AGL up to cloud base, and absent (−0.01 m/s) with the setting at 0. It looks like a mass-balance sink spread over the whole region. That makes the setting worse than useless for a glider on such a day: it costs ~35% extra sink on the ASK 21 (0.86 → ~1.2 m/s at 90 km/h) with nothing found in return.
- **`sim/weather/aircraft/thermal_rate_ms` is not a sensor.** It reads exactly the regional setting (2.54 m/s) everywhere, in or out of lift, so it cannot tell where native thermals are. The logger's `native_thermal_ms` column therefore says nothing about the aircraft's position. The test pilot now detects lift with the glider's own total-energy vario plus the test A polar (netto).
- **Real weather does set a thermal rate** (0.62 m/s at KHOB that night), so the forum report that the slider stays at 0 with real weather did not hold here.

### J. Native wave

Flown by the test pilot on 2026-11-03 (04:36–05:08 local), reference plugin disabled, `audit_native.py wave`. **Site:** the Sierra Nevada near Bishop, CA. Crossing A starts at the crest at 37.35 N 118.66 W (3780 m on SRTM), where the escarpment drops to 1900 m within 5 km and the Owens Valley floor (1250 m) lies 15–27 km east of the crest; crossing B starts at the crest at 37.40 N 118.72 W (3650 m), which drops to 1970 m within 5 km. **Weather:** manual, clear, wind from 250° (square onto the range) increasing with height: 10 kt at 5000 ft, 26 kt at 11000, 32 kt at 13000, 38 kt at 16000, 44 kt at 20000, 50 kt at 25000 ft; no turbulence, no thermals, X-Plane's default (ISA, stable) temperature profile. Each crossing runs downwind at 90 km/h IAS from 4 km upwind of the crest to 28 km downwind, i.e. across the whole valley where a Sierra wave stands. The protocol's parallel passes were dropped after three crossings: the crossings already cover every distance from the crest, and they showed nothing to look for.

| Pass | Distance downwind of crest (km) | Height (m MSL) | Wind (kt) | Native lift (m/s) | Smooth or turbulent | Note |
| --- | --- | --- | --- | --- | --- | --- |
| `wave_crossA_600` | −4 to 28 | 4380 → 3610 | 29–34 | +1.8 / −1.9 over the crest; **+0.11 ± 0.01 from 5 to 28 km** | Smooth | 2300–2550 m AGL over the valley |
| `wave_crossA_2000` | −4 to 28 | 5780 → 5060 | 39–42 | **+0.14 ± 0.02 everywhere** (no crest effect either) | Smooth | 2500–4000 m AGL |
| `wave_crossB_600` | −4 to 28 | 4250 → 3400 | 27–33 | +3.4 / −5.3 over the crest; **+0.10 ± 0.01 from 5 to 28 km** | Smooth | 1360–2430 m AGL over the valley |

**Reading.** **XP12 does not model mountain waves.** Downwind of the Sierra, in a wind profile that gives classic wave days, the air over the Owens Valley is dead still: the lift is flat to ±0.02 m/s over 23 km at both heights, where a real wave would give bands of 1–5 m/s every 8–15 km, and there is no rotor or turbulence below either. The only vertical motion is the local slope effect found in test H, close over the crest and the lee slopes (up to +3.4 / −5.3 m/s at 300–650 m AGL), and it is gone 2000 m above the crest. The small constant +0.1 m/s is not air motion but the descent through the wind gradient (a glider sinking into weaker tailwind gains a little energy against the air); it is the same at every distance. Wave is entirely the plugin's job (phase 4), as the SPEC assumed.

### Native audit conclusion

| Phenomenon | Modeled natively? | Good enough to keep? | Gaps found |
| --- | --- | --- | --- |
| Ridge | **Yes**: vertical air speed ≈ wind × slope of the ground directly below, fading with height above it (gain ~1 near the ground, ~0.5 at 500 m, ~0 by ~1100 m AGL), linear in wind speed, smooth | **Yes for ridge running** close to the face; real air moves, so the vario and the flight model see it | No lift band upwind of the foot of the slope or above and ahead of the crest; lee sink is the exact mirror of the windward lift and has no rotor or turbulence; every bump of the terrain makes its own lift and sink. AI gliders will need the same local-slope model to ridge-soar where the player does |
| Thermals | **Not found** with the thermal setting on (custom and preset cumulus, ~75 km flown); the only measurable effect is a uniform sink of ~14% of the setting (−0.35 m/s at 500 fpm) | **No**: as measured, turning native thermals on only adds sink. Strategy C (modulate native thermals) has nothing to modulate | Everything. `sim/weather/aircraft/thermal_rate_ms` just repeats the regional setting, so native lift cannot even be located. One hand-flown check aiming at cloud centers is still worth doing before closing this |
| Wave | **No**: dead still air over the Owens Valley downwind of the Sierra in a classic wave wind profile | — | Everything: wave (and rotor) is the plugin's |

What this means for the plugin, for the SPEC to take up: ridge stays native (phase 4 adds only the gaps above, and only if they do not stack with the native lift); thermals point to strategy A (replace), with the native thermal setting kept at 0 so that its background sink does not add to ours; wave is ours.

### Predictions checked

| # | Prediction | Result |
| --- | --- | --- |
| 1 | Only the thrust term adds energy | **Held** (test C): normal force alone −0.06 m/s, forward force alone +1.04 m/s against 1.03 predicted |
| 2 | Calibration gain grows with speed | **Held** (test B): ×1.35 from 90 to 120 km/h, TAS ratio ×1.33 |
| 3 | Lift depends on frame rate above 100 fps | Not tested (60 fps cap). The force is applied once per frame and cleared, so above 100 fps the 0.01 s callback would skip frames and the gain would drop, as predicted |
| 4 | Roll direction is right | |
| 5 | Pitch follows the wing difference | |
| 6 | Thermal lift is 4/3 × model × sun factor | |
| 7 | Issue #34 is a missing `init_values.json` | Consistent so far: with the flat install it loads without errors (two X-Plane starts on 2026-11-02 and 2026-11-03); the failing install was not reproduced |
| 8 | Log spam while paused | |

### Log sheet

| Mark | Test | Note |
| --- | --- | --- |
| none | A | One log per speed instead of marks (2026-11-02) |
| none | B, C | One log per segment, `flightlog_20261103_051702` to `_052614` (2026-11-03) |
| none | H, I, J, E | One log per pass; `Output/xp-gliding/audit/manifest.jsonl` maps each log to its pass; in the thermal hunts odd marks are circles (2026-11-03) |

### Other observations

- **Load (prediction 7):** with the flat install both Python plugins load and enable without errors (`XPPython3Log.txt`, 2026-11-02).
- **Replaced datarefs:** at load, X-Plane reports that `sim/weather/wind_speed_kt[0]` and `sim/weather/wind_direction_degt[0]`, which the reference plugin uses for thermal drift, "have been replaced". Whether they still return the wind is to be checked in a test with wind.
- **Restarting X-Plane from outside works (2026-11-03):** the web API's `sim/operation/quit` command closes X-Plane in ~16 s (Alex's plugin saves its settings on the way out), the web server is up ~50 s after relaunching `X-Plane.exe`, before the main menu is usable, and `POST /api/v3/flight` starts a flight straight from the main menu. So a plugin change no longer needs a human at the keyboard. Remember the payload (see tests B–D).
- **Test E not done:** with Alex's plugin enabled in calm air over KHOB, the test pilot cruised 20 km without meeting a thermal. His random map puts 200 thermals on a 200 × 200 km grid (one per ~200 km²), and the logged `distance_from_center` stayed at 540–570 km, so the map was not around the glider (why is not known yet: it was first enabled over KHOB during test B; maybe that attribute is not what it seems). The map is only refreshed every 60 minutes or when it is empty. To fly E, disable and re-enable the plugin from its menu over the test site first (that clears the map), or expose a refresh to the test pilot.
- **Changing the frame rate (2026-11-03):** X-Plane 12.4.3 accepts `--lock_fr=N` on its command line and then runs at exactly N fps (checked at 30 and 20; it cannot go above the 60 fps cap). `tools/testpilot/restart_xplane.py -- --lock_fr=30` relaunches it that way, so test D can now be flown. Phase 1 used it for our own plugin ([phase1.md](phase1.md)).
- **Native thermal control:** XP 12.4.3's manual weather screen calls the thermal setting "Climb Rate under Cumulus Clouds", in ft/min, which supports the reported link between native thermals and cumulus (test I).
