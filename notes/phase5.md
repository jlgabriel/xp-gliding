# Phase 5: the day

Working record. Started 2026-11-07. So far this only reads X-Plane's weather and works out a rule offline. **Nothing here is wired into the plugin or flown.**

## What XP12's weather offers for a cloud base

`tools/testpilot/read_weather.py`, X-Plane 12.4.3, an air start in each case, sim paused, datarefs only. `sim/weather/aircraft/temperatures_aloft_deg_c` and `dewpoint_deg_c` are 13 layers at the heights of `sim/weather/region/temperature_altitude_msl_m`, and `aircraft/cloud_*` gives three cloud layers. So the weather API is not needed for this, and these can be read when a sky begins. Each row interpolates the layers at the ground under the glider. The base is `engine/day.py`: 125 m per degree of spread between temperature and dew point (Espy's rule, as the SPEC proposed).

| Case | Ground | Temperature | Dew point | Base above the ground | Base MSL | XP12's clouds |
| --- | --- | --- | --- | --- | --- | --- |
| Hobbs, calm default, no clouds | 1112 m | 7.8 | -14.1 | 2733 m | 3845 m | none |
| Hobbs, custom cumulus, base 2500 m MSL | 1112 m | 7.8 | -3.6 | 1418 m | **2530 m** | cumulus 2500-3500 m |
| Santiago, real weather | 644 m | 19.1 | 11.4 | 958 m | 1601 m | none reported |
| Hobbs, real weather | 1112 m | 28.5 | 0.7 | 3481 m | 4593 m | none reported |

Hour 12 local, day 305 of the tools' date, and the real weather of the moment it was read.

**XP12 sets the dew point to fit its own cumulus.** With the same temperatures, adding a cumulus layer at 2500 m MSL moved the dew point at the ground from -14.1 to -3.6, and the rule then gives 2530 m, within 30 m of the layer asked for. One case. It says the rule and X-Plane agree, so a pilot who sets a cumulus base in X-Plane's weather would get our clouds there either way.

**Real weather comes late.** Read 40 s after loading Santiago, temperatures were still the standard ones, and dew points were 4.8 C at sea level and **-100 above it**, which interpolated to a base of 13.8 km. Read 60 s later they were real, and the same 60 s after that. So -100 means no data, `engine/day.py` leaves it out, and a sky that begins at load can begin before the real day has arrived. The time it takes depends on the download; it was not timed.

**A dry day gives a deep sky.** The real day at Hobbs and the calm default both give a base over 2.7 km above the ground. Today's fixed sky has it at 1500 m. Whether the plugin should cap it is below.

**No strength here.** No dataref gives a surface heat flux. `region/thermal_rate_ms` read 0.12 once under real weather and 0 elsewhere, with the plugin holding it at 0, so what X-Plane means by it was not seen.

## What is built

`xp_gliding/engine/day.py` and `tests/test_day.py`: interpolation in a table, leaving out layers with no data, and the rule. Pure Python. No setting uses them yet.

## Questions for Juan Luis before wiring it

1. **What sets the day by default?** Proposed: fixed settings stay the default, and a menu item "Take cloud base from X-Plane's weather" turns this on, until it has been flown.
2. **A cumulus layer against the rule.** Proposed: only the rule. X-Plane fits its dew point to its layer, so they agree where one is set, and there is one path to test.
3. **Limits.** Proposed: a base between 500 m and 3500 m above the ground, since 2733 m came from a default with nothing set. The numbers are a guess.
4. **When the weather changes in flight.** A new base means a new `zi`, which today starts a new sky. Proposed: read once when a sky begins, and once more about 90 s later for real weather that arrives late, then keep it. So the clouds may start over once, soon after loading.
5. **Strength.** Proposed: leave `w*` a setting for now. Thermals could also be judged from the spread or the lapse rate, but nothing here supports a number.
6. **Height.** A deeper sky also moves each thermal's strength with height, since the model scales with `zi`. A climb under a 3 km base has not been flown, nor one under 958 m.

**Also to mind.** Two pilots at one instant ([open question](SPEC.md#open-questions-and-verifications)) would differ in the depth of the day if their weather differs, as with real weather read at different times.
