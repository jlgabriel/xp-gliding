# Phase 1: the XP12 adapter in flight

First flights of the xp-gliding plugin (the engine of `xp_gliding/engine/` flown in X-Plane through `xp_gliding/adapter/`), with thermal strategy A: our thermals replace the native ones, whose setting is held at 0. Measured by the test pilot (`tools/testpilot/fly_phase1.py`) with the Laminar ASK 21 at 541 kg over KHOB, in the conditions of test A in [baseline.md](baseline.md), so every Δvs is against that polar. See the roadmap in [SPEC.md](SPEC.md).

**Done when** (SPEC, phase 1): the ASK 21 climbs ~w m/s above its sink rate without calibration, at different frame rates; it can circle and climb in the engine's thermals. A second glider doing the same with no changes is **deferred** (Juan Luis, 2026-11-03): everything is made complete with the Laminar ASK 21 first, and other gliders come much later. The physics has no per-aircraft constant (the force is m·g·w / V_TAS and the geometry comes from the `.acf`), so nothing is expected to depend on the aircraft.

**Status (2026-11-03, evening):** the plugin loads and flies; uniform lift gives Δvs = w within 0.01 m/s at 90 and 120 km/h, straight and circling, and at 60, 30 and 20 fps. In the engine's own thermals, orbited by the test pilot, the measured netto matches the engine's lift at the glider within 0.02 m/s where the orbit matched the reference circle's bank and speed, and within 0.4 m/s elsewhere, the rest being the sink model (see [Thermals of the engine](#thermals-of-the-engine)). With the field sampled the plugin costs ~120–130 µs per frame. Still open: test F (feel, by hand). The finding of the day is about the sky, not the physics: Allen's mean-day thermals are narrow for an ASK 21.

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

**Settings** start from `Output/xp-gliding/config.json` (written with the defaults on first start): w* 3.0 m/s, zi 2000 m AGL, seed 1, range 10 km. Everything the test pilot needs is a dataref under `xp_gliding/`: `enabled`, `thermals_enabled`, `roll_enabled`, `helix_enabled`, `wstar_ms`, `zi_m`, `seed` and the debug modes `debug/uniform_ms`, `debug/dw_dy` are writable; `active`, `lift_ms` (span average), `lift_centre_ms`, `lift_left_ms`, `lift_right_ms`, `lift_tail_ms`, `dw_dy`, `dw_dy_helix`, `force_n`, `roll_nm`, `nearest/distance_m`, `nearest/bearing_deg`, `nearest/core_ms`, `thermals_alive`, `native_saved_ms`, `frame_us`, `span_m`, `area_m2` are read-only. Menu *Plugins → xp-gliding* with *Enabled* and *Thermals*, also as commands `xp_gliding/toggle` and `xp_gliding/thermals/toggle` (issue #30). The training markers, added afterwards, are in [phase2.md](phase2.md).

## Results

### Load

X-Plane 12.4.3 loads the plugin without errors (`XPPython3Log.txt`). On first start it writes `Output/xp-gliding/config.json` with the defaults, and it logs the aircraft it finds:

```
[xp-gliding] aircraft .../Schleicher ASK 21/ASK21.acf: 0 engines, eligible; WingGeometry(span 17.24 m, area 17.75 m2, AR 16.7, taper 0.37, tail arm 4.56 m, ...)
```

Over KHOB at noon on 2 November, with the defaults, about 2800 thermals are alive within the 10 km loaded around the glider, and the native thermal setting reads 0 while the plugin is active.

**Cost per frame** (the plugin's own `frame_us`, averaged over ~1 s, from the logs): 37–43 µs at 60 fps with the field loaded but not sampled (thermals off or uniform mode), against the SPEC's budget of 500 µs. The same work reads 66 µs at 30 fps and ~88 µs at 20 fps, so part of it is the machine rather than the plugin (presumably the CPU clocking down between slower frames). With the field sampled at four points every frame (thermal hunt and orbits, 2026-11-03, 60 fps): median 118–132 µs, 99th percentile 150–190 µs, against 42 µs with the field loaded but thermals off in the same flights. The four `lift_at` calls cost ~80–90 µs, about twice the offline estimate of ~40 µs; still well inside the budget, and the first place to look if it ever matters (the four samples share z, the environment sink and the cell search). The first load of the field takes ~40 ms, once, when the flight starts.

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

**Test pilot note.** Its bank integrator only works within 5° of the commanded bank (`control.Gains.phi_i_window`, now a parameter). After a roll-in that overshoots beyond that, it can stay stuck at a steeper bank. The circles above use 20°. Since the orbits below, the roll trim decays (5 s) when the bank is farther than that from the command (`roll_trim_leak_s`), so it can no longer hold the glider away from a new bank.

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

Flown 2026-11-03 (17:25–19:22 local), w* 3 m/s, zi 2000 m AGL, seed 1, 2 November, ~19 h zulu (noon at KHOB), native thermals at 0, calm air.

**Rule-of-thumb hunt** (`fly_phase1.py thermals`, 35°, 90 km/h): air start at 1180 m AGL, cruise east, circle when the total-energy netto passes 0.8 m/s. It found **no climbable thermal**: after 10 min it was down to 400 m AGL (the abort height) after three circles, all in sink.

| Circle | AGL (m) | Netto, measured circle sink (m/s) | Engine lift (m/s) | Difference (m/s) |
| --- | --- | --- | --- | --- |
| 1 | 968 | −0.34 | −0.27 | −0.07 |
| 2 | 617 | −0.31 | −0.25 | −0.06 |
| 3 | 498 | −0.28 | −0.23 | −0.05 |

The physics held (the measured netto follows the engine's environment sink), but the hunt never got into a core. The log says why:
- **The density is right.** The nearest thermal had a median distance of 243 m; for 4.5 thermals per km² placed at random the expected value is 236 m.
- **The cores are narrow and the hunter is slow.** With the defaults, the outer radius r2 is ~135 m at this height, and the strong core (r1 ≈ 0.29 r2) is only ~40 m. The hunter's netto is smoothed over ~2 s (50 m of flight), so by the time it says "lift" the glider is leaving the core, and it then always turns left on a ~110 m circle.
- **Between thermals the air sinks** −0.26 m/s (Allen's mass-conservation environment sink, Eq. 21), which the glider met ~90% of the time.

**Can an ASK 21 climb in them at all?** `tools/engine_plots/circle_climb.py` answers offline with perfect centring: for every thermal alive within 5 km, the lift averaged over a circle centred on it, minus the glider's circling sink (the test A polar's n^1.5 turn model plus the 0.18 m/s it fell short at 35°).

| AGL (m) | Bank, IAS | Radius (m) | Sink (m/s) | Centre lift, median (m/s) | Climb, median (m/s) | Climb, p90 (m/s) | Climbable (> 0) |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 800 | 35°, 90 km/h | 110 | 1.45 | +2.25 | −1.18 | +0.05 | 10% |
| 800 | 40°, 85 km/h | 82 | 1.59 | +2.25 | −0.70 | +0.85 | 25% |
| 800 | 45°, 80 km/h | 61 | 1.77 | +2.25 | −0.29 | +1.31 | 39% |
| 800 | 50°, 80 km/h | 51 | 2.01 | +2.25 | −0.31 | +1.33 | 40% |
| 1100 | 45°, 80 km/h | 63 | 1.79 | +1.75 | −0.58 | +0.69 | 27% |
| 1400 | 45°, 80 km/h | 65 | 1.82 | +1.06 | −1.05 | −0.30 | 5% |

At 35° only one thermal in ten can be climbed even perfectly centred; at 45° and 80 km/h about four in ten, best around 500–800 m AGL, and almost none above 0.7 zi (Allen's thermals weaken well before zi). On what is a good day by its numbers (w* 3 m/s), the best 10% of thermals give the ASK 21 ~1.3 m/s. That answers the SPEC's open question on thermal width: *barely, and only circling tight*.

**Orbits** (`fly_phase1.py orbit`). To measure the physics inside thermals anyway, the test pilot became an oracle: it builds the plugin's own field (same seed, X-Plane's date and zulu time; the distance to the nearest thermal matched the plugin's within 3 m every time), picks the best thermal within 2.5 km, flies to it and orbits its centre at the radius of the commanded bank and speed (`control.OrbitHold`). A first circle with the thermals off measures the glider's own circling sink, and each circle's netto is vs_te plus the turn model at that circle's IAS, TAS and bank, scaled to match the reference exactly.

The ASK 21 cannot fly 45° at 80 km/h: read live, the test pilot's pitch yoke sat at its 0.8 limit with α ≈ 11.5° (in a 45° turn the stall speed rises by √1.41 ≈ 1.19). It circled at 90–105 km/h instead (partly for another reason, see *Why the orbits ran fast*), so the orbits came out steeper than the reference.

| Flight | Thermal | Turns | Bank (deg) | IAS (km/h) | AGL (m) | vs_te (m/s) | Netto, measured (m/s) | Engine lift (m/s) | Difference (m/s) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | ref | 3.0 | 46 | 93 | 992 | −2.02 | | 0 | |
| 1 | 1 | 7.9 | 43 | 90 | 901 | +0.53 | +2.38 | +2.39 | −0.01 |
| 1 | 2 | 9.1 | 44 | 92 | 990 | +2.01 | +3.96 | +3.80 | +0.16 |
| 1 | 3 | 10.9 | 51 | 101 | 1123 | +0.69 | +3.20 | +3.16 | +0.04 |
| 1 | 4 | 10.0 | 47 | 91 | 1237 | +0.25 | +2.36 | +2.38 | −0.02 |
| 1 | 5 | 2.8 | 46 | 91 | 865 | +0.05 | +2.06 | +2.08 | −0.02 |
| 1 | 6 | 3.7 | 41 | 91 | 851 | +0.68 | +2.47 | +2.78 | −0.31 |
| 3 | ref | 2.8 | 47 | 91 | 1052 | −2.11 | | 0 | |
| 3 | 1 | 5.2 | 52 | 101 | 876 | +0.40 | +2.95 | +2.68 | +0.27 |
| 3 | 2 | 9.0 | 48 | 97 | 901 | +1.03 | +3.23 | +3.25 | −0.02 |
| 3 | 3 | 9.9 | 51 | 99 | 966 | +0.70 | +3.13 | +3.02 | +0.11 |
| 3 | 4 | 10.0 | 52 | 102 | 1057 | +0.72 | +3.36 | +3.24 | +0.12 |
| 3 | 5 | 3.5 | 46 | 95 | 1035 | +0.10 | +2.19 | +2.12 | +0.07 |
| 3 | 6 | 3.2 | 52 | 100 | 952 | −0.14 | +2.43 | +2.27 | +0.16 |
| 3 | 7 | 3.1 | 52 | 103 | 931 | −0.27 | +2.39 | +2.25 | +0.15 |
| 3 | 8 | 3.2 | 52 | 102 | 845 | −0.42 | +2.21 | +2.15 | +0.06 |
| 4 (90 km/h) | ref | 3.1 | 46 | 91 | 1055 | −2.05 | | 0 | |
| 4 | 1 | 5.7 | 52 | 103 | 898 | +0.27 | +2.92 | +2.61 | +0.31 |
| 4 | 2 | 11.3 | 53 | 105 | 925 | +1.09 | +3.81 | +3.43 | +0.38 |
| 4 | 3 | 5.7 | 52 | 104 | 1085 | +0.54 | +3.22 | +2.97 | +0.25 |
| 4 | 4 | 10.8 | 52 | 103 | 1053 | +0.57 | +3.18 | +2.98 | +0.20 |
| 4 | 5 | 11.1 | 52 | 103 | 1069 | +0.25 | +2.89 | +2.71 | +0.18 |
| 4 | 6 | 4.8 | 52 | 101 | 1015 | −0.35 | +2.25 | +2.02 | +0.23 |
| 4 | 7 | 3.4 | 53 | 104 | 937 | −0.83 | +1.94 | +1.91 | +0.02 |
| 4 | 8 | 3.4 | 52 | 103 | 918 | −0.28 | +2.30 | +2.14 | +0.15 |
| 4 | 9 | 3.4 | 53 | 104 | 757 | −1.25 | +1.49 | +1.44 | +0.05 |

Flights 1 and 3 commanded 80 km/h, flight 4 90 km/h. Flight 2 was aborted early (bank limit, see below). Flight 1's thermal 6 was cut by the end of the run in the middle of its entry.

**Reading.** In real, non-uniform thermals the climb matches the engine's lift at the glider. Where an orbit was flown at the reference's bank and speed (within ~3° and ~2 km/h: flight 1's thermals 1, 4 and 5, flight 3's thermal 2) the difference is −0.01 to −0.02 m/s, as good as uniform lift. The rest (but for flight 1's truncated thermal 6) read high by up to +0.38 m/s, and the error grows with the distance from the reference: flights 3 and 4 orbited ~6° steeper and 10–12 km/h faster, and averaged +0.11 and +0.20. That residual is the measurement, not the physics: away from the reference, the sink comes from the turn model, which is only exact there. The engine's lift itself is the span average over the real wing positions, so the gust roll and the helix correction were active all along, and the glider stayed controllable in cores of +3 to +4 m/s.

**Why the orbits ran fast.** The test pilot holds speed with pitch attitude, within θ_ref ± 12° (`Gains.theta_span`), and θ_ref is the attitude at the start clamped to 0–5°. Climbing at w in a turn needs about w/V (7° at 3 m/s) more nose-up than circling in still air. Flight 1 started at θ +32° (the unpaused settle, below), so θ_ref was 5° and the cap 17°: its orbits reached θ 22° and held the reference's 93 km/h. Flights 3 and 4 started nose-down, so θ_ref was 0° and the cap 12°: the attitude sat at the cap in the cores (90th percentile 14°) and the speed ran to 100–105 km/h. To fix before the next orbits: a fixed θ_ref and a wider span, or a reference circle per orbit at its own bank and speed.

**Test pilot fixes found by these flights:**
- *Air-start settle.* `restart_xplane.py` now waits 60 s after the web API is up (X-Plane goes on loading airports and plugins for ~30 s after it answers), and `air_start()` holds the sim paused for 15 s once the flight has loaded. Unpaused, the glider flew those 15 s alone into a phugoid (174 km/h, θ +32° when the pilot took over).
- *Roll trim stuck after an orbit.* See the test pilot note under uniform lift: after ten turns at 45°, the frozen roll trim held the glider at −9° for 6 min while the approach to the next thermal commanded −20°.
- *Pitch damping.* It used X-Plane's body pitch rate `Q`, which in a steady turn is g·sin²φ / (V cos φ) (read live: 4.1–4.9 deg/s at 25°, against 4.3–4.9 computed; ~16 deg/s at 45°), and answered it nose-down. It now uses `theta_dot`, the Euler pitch rate. The earlier missions flew with `Q`; their results are differences at matched conditions and do not change.
- *Orbit radius.* It came from the TAS of the moment, which after a strong core can be 30% high; it now comes from the commanded IAS.

### Other gliders (a short comparison)

Flown 2026-11-03 (19:41–20:05 local) with `tools/testpilot/fly_compare.py`, at Juan Luis's request, to see whether the Laminar ASK 21's high circling sink is the aircraft or X-Plane: one air start per glider at 2300 m MSL over KHOB in calm air, the plugin's thermals off, and four stretches of 30–35 s (straight at 90 and 120 km/h, a 45° circle at 90 km/h, and 2 m/s of uniform lift at 90 km/h). The other gliders stay out of the project for now (decision of the same day); this only measures them.

| Glider | Mass (kg) | Span (m) | Sink at 90 km/h (m/s) | L/D at 90 | Sink at 120 km/h (m/s) | L/D at 120 | 45° circle: sink (m/s), bank, IAS | Uniform 2 m/s: Δvs (m/s) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Laminar ASK 21 | 541 | 17.24 | 0.98 | 29 | 1.24 | 30 | 2.01, 46°, 90 km/h | +1.98 |
| NHAdrian ASK 21 (B21) | 450 | 17.00 (default) | 0.86 | 33 | 1.58 | 24 | 2.26, 53°, 95 km/h | +1.92 |
| STMA HpH 304S Shark | 569 | 17.62 | 0.62 | 45 | 0.74 | 51 | 1.11, 45°, 120 km/h | +1.99 |
| STMA HpH 304S, "Claude" copy | 569 | 17.62 | 0.62 | 45 | 0.74 | 51 | 1.11, 45°, 120 km/h | +1.99 |

Sinks are at 2300 m MSL (TAS ~12% above IAS), so they read ~12% higher than at sea level.

**Reading.**
- **The plugin needs nothing per aircraft.** Uniform lift gives Δvs = w within 0.02 m/s on the ASK 21 and the Shark, and within 0.08 on the NHAdrian ASK 21, whose geometry the plugin could not read (below).
- **X-Plane can fly a good glider.** The Shark glides 45 at 90 km/h and 51 at 120 km/h, close to the real 18 m Shark (~50), and circles at 45° and 120 km/h sinking 1.11 m/s, about half of what the Laminar ASK 21 sinks at 45° and 90 km/h. So the Laminar ASK 21's high circling sink belongs to that aircraft's model, not to X-Plane's flight model.
- **The two Sharks fly identically** (same numbers to 0.01): the "Claude" copy only changed instruments and scripts (vario, MacCready, transponder, volume), and its `.acf` is the same file.
- **The NHAdrian ASK 21** sets its own payload from its weight script (450 kg here, one pilot), so it is not at the Laminar one's 541 kg. It glides better at 90 km/h (33 against 29) and worse at 120 (24 against 30), partly because it is lighter. Scaled from 53° to 45° with the n^1.5 model its circle would sink ~1.8 m/s, against the Laminar one's 2.0.

**Not comparable, the test pilot's fault.** Its gains were tuned on the Laminar ASK 21. On the Shark it holds 90 km/h straight with a ±9° pitch oscillation, and in the 45° circle it stays at 120 km/h with the nose at −1° (it never slowed down; changing the order of the stretches did not help). On the NHAdrian ASK 21 the overbanking tendency at 45° pushes the bank beyond the bank integrator's 5° window, and it settles at 53°. A 45° circle at 90 km/h on these two needs gains per aircraft or a wider integrator window.

**Found in passing: the plugin cannot read the NHAdrian ASK 21's wings.** It looks for the main wings in Plane Maker's slots 0–7, as Laminar uses them; this `.acf` has them in slots 8 and 9 (and the horizontal tail in 16 and 17), so the plugin falls back to its default geometry (the real ASK 21's, harmless here). Finding the wings by size instead of by slot would fix it.
