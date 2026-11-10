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

**Answered by Juan Luis (2026-11-09):** the first four as proposed. Fixed settings stay the default and a menu item turns the weather's base on; only the rule, not X-Plane's cloud layers; a base between 500 m and 3500 m above the ground; read when a sky begins and once more about 90 s later, then kept. Strength stays a setting (5), and height is a matter for flying once it is wired (6).

**Also to mind.** Two pilots at one instant ([open question](SPEC.md#open-questions-and-verifications)) would differ in the depth of the day if their weather differs, as with real weather read at different times.

## Wired

2026-11-09, on Juan Luis's answers above. Off by default.

- `engine/day.weather_base_m`: the rule over the ground, within 500-3500 m, and None unless both temperature and dew point have at least two layers with data. That turns away the Santiago case read 40 s after loading (one dew point left), so a sky does not begin on it.
- `adapter/core.WeatherBase`: a reading when a sky begins (a flight loaded, a new flight with the same aircraft, the setting turned on, or a jump of the place or the clock) and one more 90 s after the first with data, then kept. Without data it asks again every 10 s. The second reading is worked out over the ground of the first, so it moves with the weather and not with the terrain flown over since. A later base within 100 m of the one in use is ignored, so the clouds do not start over for nothing.
- `Injector.zi_m` is the zi in use: the base over the sky's `cloud_base_zzi` (0.75 in both carrier skies, so 1250 m of base is zi 1667 m), or the menu's setting. The field, the clouds' level, the floors, the markers, the lean and the HUD's TOP all take it. A new zi starts the clouds over.
- Menu: *Cloud base from X-Plane's weather (experiment)*, command `xp_gliding/day/weather/toggle`, setting `weather_base_enabled`. The zi submenu is greyed out while it is on; its value is kept for when it is turned off.
- Datarefs: `xp_gliding/day/zi_m` (in use), `day/weather_base_m` (-1: none yet), `day/weather_reads`.
- Checked offline: `tests/test_day.py`, `tests/test_adapter.py`, `tests/test_plugin_smoke.py` (the base, the second reading, no data, off again, a new flight).

### Checked in X-Plane

2026-11-09, X-Plane 12.4.3, by the test pilot (`tools/testpilot/check_weather_base.py`): air starts of the ASK 21, the switch turned on through its dataref (not saved), the wide sky (`cloud_base_zzi` 0.75).

| Case | First reading | Base above the ground | zi | Our clouds | X-Plane's layer |
| --- | --- | --- | --- | --- | --- |
| Hobbs, cumulus set at 2500 m MSL | at load | 1418 m | 1890 m | 2530 m MSL | 2500 m MSL |
| Hobbs, cumulus set at 3500 m MSL | at load | 2004 m | 2673 m | 3116 m MSL | 3500 m MSL |
| Santiago, real weather | no data at load, data 10 s later | 952 m | 1270 m | 1604 m MSL | none |

**Two days, two skies.** The two Hobbs days put our clouds 586 m apart.

**The rule fits X-Plane's layer at 2500 m, not at 3500 m.** With the layer set at 3500 m MSL, X-Plane's dew point at the ground gives a base about 380 m under it. One case, so how X-Plane fits its dew point to a higher layer is not known. Juan Luis chose only the rule (question 2), so our clouds sit under X-Plane's there. To mind if pilots set a cumulus layer and expect our clouds in it.

**Found on the way, fixed:**
- A new flight with the same aircraft, at the same place and time, sends `MSG_AIRPORT_LOADED` and no `MSG_PLANE_LOADED`, and was not seen as a jump. The second Hobbs case kept the first day's base. Now `MSG_AIRPORT_LOADED` starts the readings over.
- Under real weather the first reading at load found no data, and the next came 90 s later. Now it asks again every 10 s until there is data.
- At Santiago the glider flew east for 90 s, over 550 m of rising ground, before the second reading. Over that ground the rule gave 574 m and not 952 m, and the sky started over for the terrain, not for the weather. Now the second reading is worked out over the first one's ground. Flown again with the three fixes: the real weather was there at load this time, 961 m, and the second reading at 90 s, over 530 m more ground, kept it (one sky, clouds at 1605 m MSL). No traceback in the log.

Left: a hand flight under a low base and a high one (question 6).

### By hand under a low base

2026-11-09, Juan Luis, Santiago, 13:00, day 312, the ASK 21 started in the air 510 m under the base, the wide sky, w* 3, no wind, markers on. The day's real weather was cloudy, one layer at 7187 m MSL in X-Plane, and the rule gave a base of 1441 m above the ground, about the menu's default, so the low base came from a cumulus layer set by hand at 1600 m MSL.

- **The rule over a low layer.** That layer gave a base of 1174 m above 644 m of ground: our clouds at 1817 m MSL, about 220 m *over* X-Plane's layer at 1600 m. Over a layer at 2500 m the rule was within 30 m, over one at 3500 m about 380 m under it. One case each, so X-Plane fits its dew point to its layers loosely, in both directions.
- **The climb** (`tools/flightlog/read_flight.py`, log `flightlog_20261109_131909.csv`): one thermal, circled for 160 s, +275 m at +1.72 m/s (total energy +1.58), 36° of bank at 100 km/h, 128 m from the centre of a core offered at 3.80 m/s. He left at 1492 m MSL, 729 m above the ground and 325 m under the base, still climbing +1.40 over the last 30 s. The thermal could have held him to 1812 m.
- **His word:** "bien". A low base gives a thermal that can be climbed.

### By hand under a high base

2026-11-09, Juan Luis, right after the low base: Hobbs, cumulus set at 3500 m MSL, the same sky, w* 3, no wind, markers on, the ASK 21 started in the air 718 m under the base. The rule gave 2005 m above 1112 m of ground: zi 2673 m, our clouds at 3116 m MSL.

- **The climb** (log `flightlog_20261109_132536.csv`): one thermal, circled for 163 s, +306 m at +1.88 m/s (total energy +1.81), 32° at 98 km/h, 155 m from the centre of a decaying thermal whose core offered 2.39 m/s when he entered. He left at 2685 m MSL, 431 m under the base, still at +1.31 over the last 30 s. That was this thermal's ceiling: decaying, it could hold him no higher.
- **His word:** it seemed to have "un poco más de fuerza" than the low base, and the marker ring changed colour as he climbed and ended white. The ring shows the core at the glider's height in four classes (`engine/markers.py`, white under 2 m/s), so white at the top is the thermal weakening towards its ceiling, as the log reads it.
- **Next to X-Plane's cumulus.** Three screenshots of his at 2642 m MSL: our clouds sit as a row of puffs under X-Plane's softer layer, about 380 m above them, and to him they look "bastante bien" together and read as cumulus. The difference in height, which the rule leaves, shows as two levels and did not bother him. X-Plane's clouds still mark none of our thermals.
- **Low against high.** One climb each, so no number can be drawn from it: +1.72 at the low base and +1.88 at the high one, a little more strength in the deeper sky, as he felt it. Both can be climbed, and neither feels wrong to him. Question 6 is answered well enough to release the switch as an experiment.

## Moved to stage 2

2026-11-07, later the same day. With the project's [stages](SPEC.md#stages), the day comes after the first release, which ships with the day chosen in the menu and a simple cutoff when there is no sun. The six questions above wait until then.

## The daily cycle

2026-11-10, designed while Juan Luis rests, after his 0.4 flights. Offline only: nothing here is built or wired yet. It takes the place of stage 1's sun cutoff ([SPEC](SPEC.md), *Daily cycle*: thermals start mid-morning, peak mid-afternoon and fade at sunset; the cloud base rises during the day; tied to radiation and season).

### What the physics says

w* = (g / θ · H · zi)^(1/3): the convective velocity scale goes with the cube root of the surface heat flux H times the depth of the mixed layer zi. Through a day:

- **H follows the sun.** It turns positive a while after sunrise and negative a while before sunset, when the sun is roughly 10° up, and is near its peak around solar noon. Taken here as H ∝ sin(elevation) − sin(10°), at least 0.
- **zi grows through the morning.** The night's stable layer is eaten from below; with a uniform stability above, zi² grows with the heat put in since H turned positive (encroachment). Taken here as zi(t) / zi_peak = √(heat since onset / heat by 15:00 solar), at most 1, so zi stops growing in mid-afternoon, as soundings usually show.
- **So w* peaks after noon.** H is highest at noon and zi later, and their product peaks around 13:00 solar time.

No dataref gives H (phase 5, *No strength here*), so the sun stands in for it, worked out in the engine as stage 1 does (`engine/sun.py`): the sky stays the same for the same seed, date, place and time.

### The numbers

`w*(t) / w*_peak` = (H/H_peak · zi/zi_peak)^(1/3), divided by its own maximum that day, offline (prototype in the session's scratchpad, the sun from `engine/sun.py`). Solar time; X-Plane's clock is about 1.4 h ahead of it at Santiago in November (UTC-3) and about 0.4 h behind it at Hobbs (MST).

| Solar time | Hobbs, 2 Nov (noon sun 43°) | Santiago, 9 Nov (73°) | Hobbs, 22 Jun (81°) | zi / zi_peak, Hobbs Nov |
| --- | --- | --- | --- | --- |
| 07:00 | 0 | 0.34 | 0.39 | 0 |
| 08:00 | 0.29 | 0.54 | 0.57 | 0.10 |
| 09:00 | 0.57 | 0.70 | 0.72 | 0.28 |
| 10:00 | 0.76 | 0.82 | 0.83 | 0.45 |
| 11:00 | 0.89 | 0.91 | 0.92 | 0.60 |
| 12:00 | 0.97 | 0.97 | 0.97 | 0.73 |
| 13:00 | 1.00 | 1.00 | 1.00 | 0.85 |
| 14:00 | 0.97 | 0.99 | 0.99 | 0.94 |
| 15:00 | 0.87 | 0.95 | 0.95 | 1.00 |
| 16:00 | 0.63 | 0.84 | 0.86 | 1.00 |
| 17:00 | 0 | 0.67 | 0.71 | 1.00 |
| 18:00 | 0 | 0 | 0.40 | 1.00 |

The cube root makes a broad plateau: from 10:00 to 15:00 solar, w* stays within a quarter of its peak. The thermals' morning difficulty in real life comes less from w* than from zi: they are low and narrow.

zi reaches 0.75 of its peak, where the wide sky puts the cloud base, at about 12:00 solar in all three cases.

### Proposal, in two steps

**Step A: strength and the first cumulus.** The sky keeps today's geometry, made for the afternoon's zi (the menu's or the weather's).

1. The w* of the moment is the menu's w* times the factor above, worked out at the glider once a second. The menu's w* becomes *the day's peak*. Lift, the sink between thermals (Allen's sink goes with w*), the markers and the lean all take the w* of the moment: today they all read `Settings.wstar_ms`, so one property of the injector feeds them.
2. Thermals are born from the sun at 10° (where H turns positive) instead of 5°, and `ThermalShare` keeps fading the sink with them, as now.
3. A thermal whose birth comes before zi has grown to the cloud base (zi(t) < `cloud_base_zzi` · zi_peak) is blue: no cloud. The morning is blue and the first cumulus appear around solar noon, as on a real day. This touches only the cloud catalog's choice (`clouds.carries_cloud`), which is deterministic from the birth time: the thermal keeps its strength and shape in the field, and only its cloud is left out.

**Step B, later: the depth of the moment.** Morning thermals low and narrow, and the cloud base rising through the day. `lift_at` already takes the zi of the moment, but the field's density, the clouds' level and each thermal's floor are made for one zi per sky, and a new zi starts the clouds over. Rising bases need each cloud to keep the level of its birth. Larger work, and better judged after flying step A.

**Built offline, not wired** (2026-11-10, the same evening): `engine/daycycle.py`, `DayCycle(day)` with `strength_share`, `depth_share` and `blue`, and `sun.solar_time_s` / `sun.utc_for_solar` (the sun's elevation is unchanged, bit for bit). A solar day is worked out once per place, rounded to 0.1°, on a table every 5 minutes: 0.4 ms to build, 1 µs a call after. `tests/test_daycycle.py` pins the table above at Hobbs within 0.03, the peak between 12:30 and 14:00 solar in three cases, the night at 0, the morning blue until zi reaches 0.75, no thermals where the sun stays under 10°, and the same answer for the same inputs. 438 tests pass. Nothing in the plugin calls it until the questions below are answered.

### Questions for Juan Luis

1. **What the menu's w* means.** Proposed: the peak of the day flown, so the season changes only the length of the day. The other choice is the peak of a midsummer day, so that a winter day is also weaker (Hobbs in November would peak at about 0.87 of June's, since sin 43° against sin 81° gives 0.65 of the flux, and w* goes with its cube root).
2. **The morning blue until about noon** (step A.3). Proposed: yes.
3. **Thermals from the sun at 10° instead of 5°.** Proposed: yes; at Hobbs in November the last births come about half an hour earlier than with 0.4.
4. **Step B after flying step A.** Proposed: yes.
5. **The switch.** Proposed: the menu's sun item becomes *Daily cycle*: on, the cycle; off, w* the same all day and no sun at all, as 0.1.

**Answered by Juan Luis (2026-11-10, the same night):** "Sí, las cinco". The menu's w* is the peak of the day flown; the morning is blue; thermals from the sun at 10°; step B after flying step A; a switch called *Daily cycle*. There was no menu item for the sun before (only `config.json` and a dataref), so the switch is a new item, second after *Thermals*, bound to the same setting `sun_enabled`.

### Wired

2026-11-10, the same night. On by default, as the sun cutoff it takes the place of.

- `sun.SUN_MIN_DEG` is 10 (was 5): births and `ThermalShare` follow it, and `daycycle.ONSET_DEG` is the same number.
- `ThermalField.cycle`: a `DayCycle` when the sun is on. `Injector.wstar_ms` is the menu's w* times `cycle.strength_share` at the glider, worked out once a second; the lift, the nearest thermal's core, the markers and the lean take it.
- `CloudCatalog` leaves out the cloud of a thermal born while `depth_share` < the sky's `cloud_base_zzi`, and `CloudHeights.blue` gives such a thermal the level, as any thermal with no cloud, for its floor.
- Menu *Daily cycle*, command `xp_gliding/day/cycle/toggle`. Datarefs `xp_gliding/day/wstar_ms` (in use) and `day/strength_share`.
- Flight logger 0.9.0: `xpg_wstar_ms` is the w* in use, and `xpg_wstar_setting_ms` the menu's. `read_flight.py` takes each climb's own w* from it.
- The smoke tests' clock moved from 13:00 to 14:00 local at Hobbs, since the narrow sky's base (zi / 1.1) is reached only near 13:45 solar; two cloud-ring tests keep 13:00, the sky they were written for. 442 tests pass.
- Pilot guide, release README, README and CHANGELOG (*Unreleased*) say what it does.

### Checked in X-Plane

2026-11-10, X-Plane 12.4.3, by the test pilot: air starts of the ASK 21 at Hobbs, 2 November, calm and clear, the weather's base on (zi 3645 m), w* 3, read 40 s after each. Local time is about 0.4 h behind solar time there.

| Local time | Sun (ours / X-Plane) | Share | w* in use | Our clouds | Frame |
| --- | --- | --- | --- | --- | --- |
| 09:00 | 29.9° / 29.9° | 0.65 | 1.96 m/s | 0 | 146 µs |
| 11:00 | 42.0° / 42.0° | 0.93 | 2.79 m/s | 0 (blue) | 134 µs |
| 14:00 | 31.5° / 31.4° | 0.94 | 2.82 m/s | 13, filling | 153 µs |
| 16:30 | 5.4° / 5.2° | 0 | 0 | 0 | 94 µs |

As offline. No traceback in the log. Left: Juan Luis's hand flights, one in the morning and one in the afternoon.

### By hand, morning and afternoon

2026-11-10 evening, Juan Luis, Hobbs, 2 November, calm and clear, the weather's base on (zi 3645 m, our clouds at 3845 m MSL), the wide sky, w* 3 in the menu, markers on (off later in the second flight). Air starts of the ASK 21, paused until he took over.

| | Morning | Afternoon |
| --- | --- | --- |
| Local time (solar about 0.4 h later) | 09:30 | 14:00 |
| Share of the day's peak, w* in use | 0.74, 2.2 m/s | 0.94, 2.8 m/s |
| Our clouds | none (170 in the pool, none shown) | filling, then many, of all sizes |
| Start | 2300 m MSL | 3100 m MSL, 745 m under the base |
| Log | `flightlog_20261110_194856.csv` | `flightlog_20261110_195719.csv` |
| Climb | 150 s, +266 m at +1.77 (TE +1.54) | 63 s, +43 m at +0.68 (TE +0.71) |
| Circles from the centre | 146 m, core offered 2.99 | 118 m, core offered 2.14 |
| Left at | 2408 m, still +1.62 | 2960 m, still +0.65 |

- **The morning.** Blue, as designed: no cloud of ours in the whole flight. His word: it felt weaker. One climb at +1.77 against +1.88 with w* 3 under the high base the day before.
- **The afternoon.** A 15:00 start was tried first and dropped: the share is 0.79 there, about the morning's, and he saw it look much the same. At 14:00 he found few thermals at first ("no hay muchas térmicas"): with zi at 3645 m the density that follows zi spreads them out, and step A leaves their number alone. He searched for about three and a half minutes, then took a yellow-ring thermal, a mature one with a weaker core than the morning's, and climbed little. So the afternoon's climb says more about which thermal he took than about the hour: one climb each, no number about the cycle can be drawn from them.
- **Then a good one.** He flew on (same log, t_run 609-709): 100 s under a larger cloud (size 1.40), +231 m at +2.31 (TE +2.27), 92 m from the centre of a core offered at 3.66 m/s, left at 3134 m, 711 m under the base, still at +2.30; that thermal could have held him to 3954 m. "Ahí alcancé una bien buena". The afternoon has strong thermals; they are fewer and have to be found.
- **His word:** he likes that it costs: "me gusta que cueste". A day that changes with the hour, the place and the weather, more clouds or fewer, different strength, is "más interesante", and a day like this one is a harder flight, "como niveles de dificultad". Step A reads right to him.
