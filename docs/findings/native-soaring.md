# What X-Plane 12 models natively for soaring

Measured in flight in X-Plane 12.4.3, with the Laminar ASK 21, in November 2026.

| Phenomenon | Result |
| --- | --- |
| **Ridge lift** | Modeled. Vertical air speed is close to wind × slope of the ground directly below, fading with height, and gone by about 1100 m above the ground |
| **Thermals** | None found in about 75 km of straight flight under cumulus. The thermal setting added a uniform sink of about 14% of its value. See the [limits](#limits): this was not a search aimed at the clouds |
| **Wave** | Not found. Air downwind of the Sierra Nevada stayed steady in a wind profile chosen to produce wave |

## How it was measured

| Item | Value |
| --- | --- |
| Simulator | X-Plane 12.4.3 (Vulkan), Windows 11 |
| Glider | Laminar Schleicher ASK 21, 541 kg |
| Flying | A scripted autopilot through X-Plane's local web API, at 90 km/h IAS with wings level |
| Plugins | No plugin applying forces (all `*_plug_acf` forces at 0) |

Lift is not read from X-Plane. It is worked out from the glider's energy: the climb rate of the energy height *h* + TAS²/2g, minus the sink the same glider has in still air at that speed, measured beforehand. This glider sinks 0.86 m/s at 90 km/h (sea-level value, scaled by TAS/IAS at height). Results are per 5 s window.

The tools are [`audit_native.py`](../../tools/testpilot/audit_native.py), which flies the passes, and [`analyze_native.py`](../../tools/testpilot/analyze_native.py), which turns the logs into lift profiles. The flight logs themselves are not in the repository.

## Ridge lift

**Site:** a narrow, straight ridge in central Pennsylvania, from about 40.645 N 78.09 W to 40.745 N 77.80 W, with its crest at 550–700 m MSL and valleys at about 320 m. **Weather:** manual, clear, no turbulence, wind square onto the face at the same speed from 1500 to 12000 ft.

Lift tracks wind × slope closely, with a correlation of 0.85 to 0.92 on the passes flown across the ridge. The ratio between the two depends on height above the ground directly below:

| Height above the ground (m) | 0–150 | 150–300 | 300–450 | 450–600 | 600–800 | 800–1100 |
| --- | --- | --- | --- | --- | --- | --- |
| Lift ÷ (wind × slope) | 1.00 | 0.73 | 0.68 | 0.50 | 0.23 | 0.13 |

Lift scales about linearly with wind: at 175 m above the crest, the peak was +3.1 m/s at 25 kt and +1.6 m/s at 12 kt.

Passes along the windward face, 600 m out from the crest line:

| Height above crest | Wind | Mean lift | Outcome over about 7 km |
| --- | --- | --- | --- |
| About 0 m | 25 kt | +1.36 m/s | Climbed 134 m |
| +150 m | 25 kt | +1.25 m/s | Climbed 110 m |
| +400 m | 25 kt | +0.90 m/s | Held height |
| About 0 m | 12 kt | +0.71 m/s | Lost 53 m |

Other behaviour seen:

- **Lift follows the slope underneath.** It starts where the ground starts rising, with no band upwind of the foot of the slope, and stops at the crest.
- **Lee sink mirrors the windward lift.** It reached −3.7 m/s just behind the crest at 25 kt, and a crest-level pass 600 m out on the lee side lost 200 m in 1.6 km.
- **Every slope counts.** A 25 m rise on the valley floor gave its own +1 to +2 m/s.
- **The air is smooth** with turbulence set to 0, on the lee side as well.

## Thermals

**Site:** over Hobbs, New Mexico (KHOB), flat terrain, at local noon with the sun about 38° high. **Weather:** wind 5 kt, thermal setting in manual weather ("Climb Rate under Cumulus Clouds") as in the table. A screenshot during the custom runs showed a normal field of cumulus at the set height.

| Weather | Thermal setting | Height above ground (m) | Distance (km) | Lift (m/s) |
| --- | --- | --- | --- | --- |
| Custom: cumulus 40%, base 1780 m above ground | 0 | 1450 → 1250 | 6 | −0.01, sd 0.00 |
| Same | 500 ft/min (2.54 m/s) | 1440 → 1170 | 6 | −0.35, sd 0.02 |
| Same | 500 ft/min | 1630 → 400 | 30 | −0.35, sd 0.06 (max −0.17) |
| Same, just below the base | 500 ft/min | 1740 → 1090 | 15 | −0.36, sd 0.04 |
| Preset *vfr_scattered* (cumulus 37.5%) | 500 ft/min | About 1500 → 1100 | 12 | −0.31, sd 0.04 |
| Preset *convective*, flown above the cloud base | 500 ft/min | About 1500 → 1200 | 12.5 | +0.01, sd 0.18 (−0.56 to +0.41) |

- **No thermal was met** on the runs under the clouds. The highest window on the 30 km run was still sink.
- **The setting adds sink everywhere:** about 14% of its value, steady from 400 m above the ground up to the cloud base, and absent with the setting at 0. At 90 km/h this takes the ASK 21 from 0.86 to about 1.2 m/s of sink. It looks like a balancing downdraft spread over the region, but that is a guess.
- **The *convective* run is the only one with real variation.** It was flown above the base, in a different kind of sky, and was not followed up.
- **`sim/weather/aircraft/thermal_rate_ms` is not a local sensor.** It read the regional setting, 2.54 m/s, everywhere, so it cannot show where lift is.

Laminar's [flight model report](https://developer.x-plane.com/article/x-plane-12-flight-model-report/) describes thermals connected to cumulus clouds, rising to the cloud tops, fading below 100 m above the ground, and building from 9 am until fading from 3 to 6 pm. These runs were inside those heights and hours, but the report was written during X-Plane 12's development and may not describe 12.4.3.

## Wave

**Site:** the Sierra Nevada near Bishop, California, flying downwind across the crest and the Owens Valley, from 4 km upwind to 28 km downwind. **Weather:** manual, clear, wind from 250°, square onto the range, rising from 26 kt at 11000 ft to 50 kt at 25000 ft, with no turbulence and X-Plane's default temperature profile.

| Crossing | Height (m MSL) | Lift over the crest (m/s) | Lift 5–28 km downwind (m/s) |
| --- | --- | --- | --- |
| A, 600 m above the crest | 4380 → 3610 | +1.8 / −1.9 | +0.11 ± 0.01 |
| A, 2000 m above the crest | 5780 → 5060 | No crest effect | +0.14 ± 0.02 |
| B, 600 m above the crest | 4250 → 3400 | +3.4 / −5.3 | +0.10 ± 0.01 |

The air was smooth on every pass, with no bands of lift and sink downwind. The only vertical motion was the slope effect near the crest. The steady +0.1 m/s is most likely not air motion: a glider descending into a weaker tailwind gains a little energy.

## Limits

- **The thermal search was not aimed at clouds.** The script cannot see them, so it flew straight lines. Narrow thermals under cloud centres could have been missed. A hand-flown check aiming at the clouds is still to be done, so the result is "not found", not "not modeled".
- **Real weather was not measured.** X-Plane did set a regional thermal rate (0.62 m/s at KHOB), but the glider was upset within seconds of both air starts in a wind of about 40 kt.
- **Few sites and days.** One ridge, one thermal site and two crossings of one range, each on a single session, with one glider.
- **The wave test used one wind profile** and the default temperature profile. A different atmosphere was not tried.
- **Turbulence was set to 0,** so nothing here says how the air behaves with it on.

## What it means in practice

- **If your plugin provides its own thermals,** keep X-Plane's thermal setting at 0, or its uniform sink adds to yours.
- **To detect lift,** use total energy minus the glider's polar, since `thermal_rate_ms` does not vary with position.
- **Ridge lift already works** close to the face, so there is no need to replace it for ridge running.
- **If you script air starts through the web API,** give the payload. After an X-Plane restart the ASK 21 loaded empty (360.6 kg), with its centre of gravity so far aft that it pitched up to 45° at full forward stick.

## Full record

Protocol, every pass and the reasoning are in the [working notes](../../notes/baseline.md#native-audit-hj).
