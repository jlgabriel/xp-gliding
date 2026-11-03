# Phase 1: the XP12 adapter in flight

First flights of the xp-gliding plugin (the engine of `xp_gliding/engine/` flown in X-Plane through `xp_gliding/adapter/`), with thermal strategy A: our thermals replace the native ones, whose setting is held at 0. Measured by the test pilot (`tools/testpilot/fly_phase1.py`) with the Laminar ASK 21 at 541 kg over KHOB, in the conditions of test A in [baseline.md](baseline.md), so every Δvs is against that polar. See the roadmap in [SPEC.md](SPEC.md).

**Done when** (SPEC, phase 1): the ASK 21 climbs ~w m/s above its sink rate without calibration, at different frame rates; it can circle and climb in the engine's thermals; a second glider does the same with no changes (not flown yet: only the Laminar ASK 21 is in use).

**Status (2026-11-03):** the plugin loads and flies; uniform lift gives Δvs = w within 0.01 m/s at 90 and 120 km/h, straight and circling, and at 60, 30 and 20 fps. Still open: the thermal hunt in the engine's field (`fly_phase1.py thermals` is ready; X-Plane kept hanging or closing while starting up, which Juan Luis says it already did before these tests), the plugin's cost per frame with the thermal field sampled, and a second glider.

## The plugin

| Item | Value |
| --- | --- |
| X-Plane | 12.4.3 (Vulkan), Windows 11, 60 fps cap |
| XPPython3 | 4.7.1, Python 3.12.2 |
| Plugin | `PI_xp_gliding.py` + `xp_gliding/` 0.1.0.dev0, installed with `tools/install_plugin.py` |
| Flight logger | 0.3.0 (adds the plugin's `xp_gliding/*` datarefs as `xpg_` columns, and `beta_deg`) |
| Test pilot | `fly_phase1.py` (missions and report), `restart_xplane.py` (quit, relaunch with X-Plane options, wait for the web API) |
| Alex Ferrer's plugin | installed, disabled (`alex_enabled` 0) |

**How it works.** One flight loop runs every frame before the flight model. It reads 13 datarefs (position, AGL, heading, bank, α, β, yaw rate, TAS, mass, air density, zulu time, date), places the four sample points at their 3D positions (centre, wing tips at the real span, tail), asks the engine for the vertical air velocity at each, and adds to X-Plane's `*_plug_acf` datarefs:

- the energy force F = m·g·w / V_TAS along the air-relative velocity, w being the span average of the wing samples (Simpson), split into body axes with α and β;
- the gust roll moment ¼ ρ V S b² C_lp · dw/dy, with C_lp from the wing's aspect ratio and taper, and dw/dy the spanwise gradient of w plus the correction for the energy force's climbing-turn overbanking (w·r / V, see the uniform-lift results).

About once a second it loads the thermal tiles around the aircraft (10 km), moves the local origin when the aircraft is 20 km from it, finds the nearest thermal for the instruments, and re-checks the native thermal setting. Paused or in replay it applies nothing. It acts only on aircraft without engines (`gliders_only`), and an error in the loop stops the effect and logs once instead of every frame.

**Aircraft geometry** comes from the aircraft's own `.acf` (Plane Maker's wing parts: span, area, taper, tail arm), because the SDK exposes wing parts but not their positions. For the Laminar ASK 21 it reads span 17.24 m, area 17.75 m², aspect ratio 16.7, taper 0.37, tail arm 4.56 m (the real glider: 17.0 m, 17.95 m²).

**Signs** (DataRefs.txt, XP 12.4.3): `faxil_plug_acf` positive pushes the aircraft backward, `fside_plug_acf` right, `fnrml_plug_acf` up, `L_plug_acf` positive rolls right; X-Plane's β is positive with the nose right of the flight path. DataRefs.txt says to *add* to the `*_plug_acf` datarefs; X-Plane clears them every frame (baseline test B), so the plugin reads each one and adds its own force once per frame, which also keeps any force another plugin wrote earlier in the same frame.

**Settings** start from `Output/xp-gliding/config.json` (written with the defaults on first start): w* 3.0 m/s, zi 2000 m AGL, seed 1, range 10 km. Everything the test pilot needs is a dataref under `xp_gliding/`: `enabled`, `thermals_enabled`, `roll_enabled`, `helix_enabled`, `wstar_ms`, `zi_m`, `seed` and the debug modes `debug/uniform_ms`, `debug/dw_dy` are writable; `active`, `lift_ms` (span average), `lift_centre_ms`, `lift_left_ms`, `lift_right_ms`, `lift_tail_ms`, `dw_dy`, `dw_dy_helix`, `force_n`, `roll_nm`, `nearest/distance_m`, `nearest/bearing_deg`, `nearest/core_ms`, `thermals_alive`, `native_saved_ms`, `frame_us`, `span_m`, `area_m2` are read-only. Menu *Plugins → xp-gliding* with *Enabled* and *Thermals*, also as commands `xp_gliding/toggle` and `xp_gliding/thermals/toggle` (issue #30).

## Results

### Load

X-Plane 12.4.3 loads the plugin without errors (`XPPython3Log.txt`). On first start it writes `Output/xp-gliding/config.json` with the defaults, and it logs the aircraft it finds:

```
[xp-gliding] aircraft .../Schleicher ASK 21/ASK21.acf: 0 engines, eligible; WingGeometry(span 17.24 m, area 17.75 m2, AR 16.7, taper 0.37, tail arm 4.56 m, ...)
```

Over KHOB at noon on 2 November, with the defaults, about 2800 thermals are alive within the 10 km loaded around the glider, and the native thermal setting reads 0 while the plugin is active.

**Cost per frame** (the plugin's own `frame_us`, averaged over ~1 s, from the logs): 37–43 µs at 60 fps with the field loaded but not sampled (thermals off or uniform mode), against the SPEC's budget of 500 µs. The same work reads 66 µs at 30 fps and ~88 µs at 20 fps, so part of it is the machine rather than the plugin (presumably the CPU clocking down between slower frames). The cost with the field sampled at four points every frame is still to be logged in a thermal hunt; the offline estimate is ~40 µs more. The first load of the field takes ~40 ms, once, when the flight starts.

**Startup.** With no aircraft loaded (main menu) X-Plane reports its own folder as the user's aircraft. Since the second build the plugin stays inert until a real `.acf` is loaded, so it never touches the native thermal setting at the main menu.

### Roll sign

Flown 2026-11-03, `fly_phase1.py roll`: wings level at 90 km/h for 40 s with a constant spanwise gradient in the plugin's debug mode; the test pilot's roll-trim integrator ends up holding the yoke that cancels the moment.

| dw/dy (1/s) | Roll trim (yoke ratio, + right) |
| --- | --- |
| 0 | −0.004 |
| +0.03 (more lift under the right wing) | +0.075 |
| −0.03 | −0.076 |

More lift under the right wing rolls the glider left (the pilot needs right stick), as it must, and the response is symmetric. At 2700 m MSL and 90 km/h, dw/dy = 0.03 /s is a moment of about 780 N·m (computed, ρ ≈ 0.95 kg/m³), which takes about 8% of stick travel to hold. For scale: 0.03 /s is 0.5 m/s of difference across the span, what a wing tip meets entering a moderate core.

### Uniform lift (test B with our physics)

Flown 2026-11-03 (07:28–07:58 local), `fly_phase1.py uniform`. Each segment is its own air start over KHOB at 2800 m MSL in calm, clear air, with 40 s to settle and 35 s recorded at 2650–2700 m MSL, and `xp_gliding/debug/uniform_ms` set to w. The w = 0 segments have the thermals switched off with the plugin active, to check that it adds nothing. Straight segments are measured against the test A polar; circles against the circle flown without lift, at the same bank and speed.

| Segment | IAS (km/h) | Bank (deg) | w (m/s) | Force (N) | fps | vs_te (m/s) | Δvs (m/s) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| A90_off | 90.1 | 0 | 0 | 0 | 60 | −1.00 | −0.00 |
| U90_1 | 90.1 | 0 | 1 | 182 | 60 | −0.00 | +1.00 |
| U90_2 | 90.2 | 0 | 2 | 363 | 60 | +1.00 | +2.00 |
| U90_3 | 90.3 | 0 | 3 | 543 | 60 | +2.00 | +3.01 |
| A120_off | 120.4 | 0 | 0 | 0 | 60 | −1.27 | +0.01 |
| U120_1 | 120.2 | 0 | 1 | 138 | 60 | −0.27 | +1.01 |
| U120_2 | 120.4 | 0 | 2 | 275 | 60 | +0.72 | +2.01 |
| U120_3 | 120.3 | 0 | 3 | 412 | 60 | +1.72 | +3.01 |
| A90_c35_off | 90.1 | 35 | 0 | 0 | 60 | −1.54 | reference circle |
| U90_c35_2 | 90.2 | 35 | 2 | 360 | 60 | +0.45 | +1.99 |
| U90_c35_2_nohelix | 90.2 | 35 | 2 | 360 | 60 | +0.43 | +1.97 |

**Reading.** The energy force does exactly what it was designed for:
- **Climb gain:** w within 0.01 m/s at 90 and 120 km/h, linear from 1 to 3 m/s, and the same in a 35° circle, with no calibration constant anywhere. Alex Ferrer's plugin, calibrated at 90 km/h, gave 1.35 w at 120 km/h (baseline test B).
- **Force:** it drops with speed as 1/V_TAS (182 N at 104 km/h TAS, 138 N at 138 km/h), so that the delivered power stays m·g·w.

**Circling sink of the ASK 21.** At 35° of bank and 90 km/h it sinks 1.54 m/s at 2700 m MSL, where the polar's cos^−1.5 turn model (`tools/testpilot/polar.py`) gives 1.36 m/s, 0.19 m/s less. `fly_phase1.py report` therefore also shows the netto with that measured excess, scaled with sin² of the bank. The uniform circle checks it: 2.004 m/s measured for w = 2.

**Overbanking from the energy force (found by flying, corrected).** In the first circle with 2 m/s of uniform lift, the test pilot's 35° circle ran away to 46° of bank and stayed there. The cause is physical, and it is a limitation of injecting lift as a force:
- **The cause:** in real rising air a circling glider still descends *relative to the air*; with the force, it climbs relative to the air. In a turn each wing station has a different airspeed, V(y) = V − r·y. Climbing w relative to the air therefore lowers each station's angle of attack by a different amount, w / V(y). The outer wing loses less, lifts more, and the glider overbanks.
- **The correction:** that spanwise difference is equivalent to a vertical air gradient of −w·r / V, so the plugin adds +w·r / V to the gradient behind the gust roll moment (`injection.helix_gradient`, setting `helix_enabled`, on by default).

It was measured with the test pilot's roll trim: the steady stick needed to hold 35°, with the bank integrator window widened to 20° so that every circle settles at 35°.

| Circle at 35°, 90 km/h | Roll trim (yoke, + right) |
| --- | --- |
| Still air | +0.126 |
| w = 2 m/s, no correction | +0.178 |
| w = 2 m/s, with the correction (327 N·m) | +0.145 |

The artifact asks for 0.052 more stick, and the correction removes ~63% of it: right sign, a bit short in size. The likely reason is that the generic strip-theory roll damping (C_lp from aspect ratio and taper) is smaller than what Laminar's model uses. It is left as is for now: a scale factor would be a calibration constant, so it is better revisited with test F (feel), by hand. The climb is not affected (Δvs +1.97 without the correction, +1.99 with it).

**Test pilot note.** Its bank integrator only works within 5° of the commanded bank (`control.Gains.phi_i_window`, now a parameter). After a roll-in that overshoots beyond that, it can stay stuck at a steeper bank. The circles above use 20°.

### Frame rate

Flown 2026-11-03 (08:01–08:12 local), `fly_phase1.py fps`: at each frame rate, one segment with w = 0 (thermals off) and one with w = 1 m/s, at 90 km/h, conditions as above.

X-Plane runs at 60 fps here. **`--lock_fr=N` on X-Plane's command line fixes a lower rate.** Juan Luis found the option mentioned on a forum, and it is present as a string in `X-Plane.exe` 12.4.3, with no help text; `restart_xplane.py -- --lock_fr=30` passes it to X-Plane. With it, `sim/operation/misc/frame_rate_period` reads exactly 1/N. It does not raise the rate: `--lock_fr=120` still gave 60 fps.

| X-Plane options | fps | vs_te, w = 0 (m/s) | vs_te, w = 1 (m/s) | Δvs (m/s) |
| --- | --- | --- | --- | --- |
| none | 59.6 / 59.9 | −1.000 | −0.001 | +0.999 |
| `--lock_fr=30` | 29.9 / 30.0 | −1.000 | −0.001 | +0.999 |
| `--lock_fr=20` | 19.9 / 20.0 | −1.000 | −0.002 | +0.998 |
| `--lock_fr=20 --fm_per_frame=4` | 19.9 / 20.0 | −1.000 | −0.001 | +0.999 |

**Reading.** Between 20 and 60 fps, neither the injected lift nor the ASK 21's own sink depends on the frame rate (to within 0.002 m/s). The force is added once per frame from a before-flight-model loop, and X-Plane integrates it over that frame's time step.

**`--fm_per_frame`.** It is another command-line option, found next to `--lock_fr` in the executable. X-Plane logs it as accepted, but no dataref shows the number of flight-model runs per frame, so whether it did anything is unknown; if it did, it changed nothing measurable. Frame rates above 60 fps cannot be flown on this machine.

### Thermals of the engine

Not flown yet. `fly_phase1.py thermals` is ready:
- air start over KHOB at 2300 m MSL (1180 m AGL, z/zi = 0.6 with the defaults) and cruise east at 90 km/h;
- circle at 35° when the total-energy netto passes 0.8 m/s, centre with the rule of thumb, and leave when the last turn averaged under 0.4 m/s;
- `report` then compares, circle by circle, the measured netto with the engine's lift at the glider (`xpg_lift_ms`).

Two attempts on 2026-11-03 ended with X-Plane hanging or closing during start-up (once right after loading the MOZA plugin), before any flight. Juan Luis had already seen the same before these tests.

**What to expect,** from the engine offline (seed 1, 2 November, noon, w* 3 m/s, zi 2000 m):
- **Density:** about 4.5 thermals alive per km².
- **Strength:** the lift at the centre of the thermals alive near KHOB has a median of +2.3 m/s at 800 m AGL and +1.6 m/s at 1200 m (90th percentile +3.4 and +2.4; strongest +7.1 and +4.9).
- **Size:** the mean outer radius is 135–146 m.

At that height, the ASK 21 at 35° and 90 km/h flies a circle of ~110 m radius, so it meets only part of the core: on the strongest thermal at 1200 m, the lift averaged over a 100 m circle is +1.7 m/s, against +4.9 at the centre. Circling slower or steeper (`--kmh`, `--bank`) will matter. Whether Allen's mean-day thermals are wide enough for an ASK 21 is one of the SPEC's open questions.
