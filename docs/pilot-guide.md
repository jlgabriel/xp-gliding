# Pilot guide

How to install xp-gliding, make a first flight and read its sky. This guide is for version 0.3. Its known limits are listed at the end.

## What you need

- **X-Plane 12.** The plugin has been flown in version 12.4.3 under Vulkan, on Windows 11. Other versions and systems have not been tried.
- **[XPPython3](https://xppython3.readthedocs.io/),** the plugin that runs Python plugins in X-Plane. Install it as its page explains, and start X-Plane once, so that it creates the folder `Resources/plugins/PythonPlugins/`. Version 4.7.1 has been tried. Nothing else is needed.
- **A glider.** The reference is the Laminar ASK 21 that comes with X-Plane.

## Installing

1. Download `xp-gliding-0.3.zip` from the [releases page](https://github.com/jlgabriel/xp-gliding/releases) and unzip it.
2. Close X-Plane.
3. From the unzipped folder, copy `PI_xp_gliding.py` and the whole `xp_gliding` folder into `X-Plane 12/Resources/plugins/PythonPlugins/`. The two must sit side by side there. `README.txt` and `LICENSE` do not need to be copied.
4. Start X-Plane. *Plugins → xp-gliding* appears in the menu.

The plugin comes ready to fly: no file to edit, and nothing to set in X-Plane's thermal settings. It holds X-Plane's own thermal rate at 0 while it is active and puts it back afterwards.

**Updating:** delete the old `xp_gliding` folder first, then copy the new one, so that no old file is left behind. Your settings are kept.

**Removing:** delete `PI_xp_gliding.py` and the `xp_gliding` folder. Your settings are in `X-Plane 12/Output/xp-gliding/config.json`, which can be deleted too.

## A first flight

1. **Set the weather.** Fly by day: a thermal is born only while the sun is at least 5° above the horizon, so the sky empties over about half an hour around sunset and fills again after sunrise. Leave out X-Plane's own cumulus clouds: the plugin draws its own over its thermals, and X-Plane's clouds mark none of them, so flying towards one finds nothing. Wind is fine, steady or not.
2. **Choose the glider.** The Laminar ASK 21. The plugin acts only on gliders, and does nothing on the rest. A motor glider counts once you choose *Treat this aircraft as a glider* in the menu (see [The menu](#the-menu)).
3. **Turn on the markers for the first climb.** *Plugins → xp-gliding → Training markers* puts a ring at your height over each nearby thermal, and a thin column up to its cloud. It helps while learning how a climb feels. Turn them off later and fly by the clouds.
4. **Get airborne,** by tow, winch or an air start, and fly towards a cloud.
5. **Check that the airbrakes are closed.** The ASK 21 can start with them open, which feels like a heavy glider and reads as strong sink.
6. **Circle where the lift is.** When the vario goes up, turn. A bank of 28–35° at 90–95 km/h has worked in the ASK 21, flown by hand in X-Plane 12.4.3. Steeper turns cost a lot of climb in this glider.
7. **Listen, if you like.** The AUDIO switch on the ASK 21's panel turns on X-Plane's own audio vario, which hears the plugin's thermals.

In calm air the sky is the same every time for the same place, date, time and seed, so a good thermal can be found again. With wind the sky drifts from where it stood when the flight began, so the same thermal turns up over different ground.

## Reading the sky

- **A cloud means a thermal.** Each of the plugin's clouds sits over a thermal. A few thermals have no cloud, and they are weaker.
- **Clouds are born and die with their thermal.** A thermal lives between 5 and 30 minutes, growing and then fading, and never vanishes at once. A cloud that is fading has a thermal that is weakening.
- **A bigger cloud usually means a stronger thermal.** This holds on average when the two are compared offline, and in the three thermals flown by hand to check it, which is too few to rely on.
- **Everything moves with the wind.** Thermals and clouds drift with X-Plane's wind, as the glider does, so a circle needs no correction for it, even while the ground passes underneath. In strong wind a thermal can carry you towards high ground.
- **A climb ends near its cloud.** The lift fades towards the cloud's base, and usually stops some way under it.
- **Clouds keep to a level for the area,** and stand higher where the ground under them, or along their drift, would reach them.
- **No thermal starts over water.** One born over land can drift out over the sea.
- **X-Plane's ridge lift stays on,** and adds to the thermals where the wind meets a slope.

## The HUD

A small panel on the left of the screen. The vario readings and the centring arrow use only what a real glider could sense, not the plugin's knowledge of where the thermals are.

| Item | What it shows |
| --- | --- |
| Large amber number, and the tape | Total energy rate, m/s |
| `NET` | Netto: the air's own motion, from total energy and the glider's sink. Only the Laminar ASK 21 has a measured polar, and any other glider shows `NET --` |
| `AVG` | The average climb over the last 30 s, m/s |
| `TOP` | Height up to the nearest thermal's cloud, m. It can jump when the nearest cloud changes |
| `WIND` | The wind at the glider, in knots, with an arrow pointing where it goes, relative to the nose |
| Centring arrow | Which way the core lies, when the lift changes enough around the circle to tell. It is most useful 60–100 m off centre, and says little closer in |

## The menu

Everything is in *Plugins → xp-gliding*. What you choose is saved for the next session, and each switch is also a command you can bind to a key or a joystick button in X-Plane's keyboard or joystick settings.

| Item | What it does | Command |
| --- | --- | --- |
| Enabled | The plugin's whole effect | `xp_gliding/toggle` |
| Thermals | The lift, keeping the clouds and the rest | `xp_gliding/thermals/toggle` |
| Thermals follow the wind | The wind carries thermals, clouds and markers. On by default | `xp_gliding/wind/toggle` |
| Thermals lean with the wind (experiment) | Lift upwind of the cloud when low. Off by default, best left off | `xp_gliding/lean/toggle` |
| Sky moves with the wind at the clouds (experiment) | Makes a climb much harder in changing wind. Off by default, best left off | `xp_gliding/wind/clouds/toggle` |
| Training markers | A ring at your height over each nearby thermal, and a column up to its cloud | `xp_gliding/markers/toggle` |
| Cumulus clouds | The plugin's clouds | `xp_gliding/clouds/toggle` |
| Soaring HUD | The panel above | `xp_gliding/hud/toggle` |
| Cloud base from X-Plane's weather (experiment) | The clouds' height from the temperature and dew point of the weather you fly, kept between 1000 m and 2250 m above the ground, in place of the depth below, which is greyed out. A cumulus layer set in X-Plane's weather moves it too, though our clouds can sit a few hundred metres off that layer. Off by default | `xp_gliding/day/weather/toggle` |
| Treat this aircraft as a glider | For a motor glider: the plugin acts on the aircraft loaded, with its engine running or not, and remembers it by its file. Ticked and greyed out for a glider | `xp_gliding/aircraft/glider/toggle` |
| Sky | How wide the thermals are: wide (the default and easiest), medium, or narrow (hardest) | |
| Strength of the day (w\*) | How strong the thermals are. 3 m/s by default | |
| Depth of the thermal layer (zi) | How high they go, and so the height of the clouds. 2000 m by default | |
| Seed of the sky | Another arrangement of thermals | |

Markers appear for up to 20 thermals within 3 km with at least 1.5 m/s at the core. The colour shows the lift at the core at your height: pale below 2 m/s, yellow from 2, orange from 3, and red from 4.

Choosing another sky, seed or depth in flight replaces the clouds at once, and new ones fill in.

## Known limits

- **The day is chosen in the menu.** The strength does not follow X-Plane's weather, so the thermals are as strong on a dry day as on a humid one. The cloud base can follow it, with *Cloud base from X-Plane's weather (experiment)*, off by default.
- **The sun only switches the thermals on and off.** From sunrise to sunset they are as strong as the day chosen in the menu, at 9 in the morning as at 3 in the afternoon.
- **A far cloud can appear in front of a near one at times,** mostly between clouds far away. A cloud you have just come near can look denser for a few minutes.
- **X-Plane's own cumulus mark none of these thermals.** The two can share a sky, but to read it, leave X-Plane's off.
- **The Laminar ASK 21 is the reference.** Other gliders get the lift, and no netto on the HUD. A glider whose wings are not in the usual parts of its file is treated as an ASK 21 for the roll. An aircraft with engines gets nothing unless you treat it as a glider from the menu, which is how a motor glider gets the lift, with its engine running or not, since the air rises for it either way.
- **A glider flies as well as its own flight model allows.** The Laminar ASK 21 sinks about 2.1 m/s circling at 45°, measured by a scripted autopilot in X-Plane 12.4.3, so steep turns cost a lot of climb.
- **Lift is a push on the aircraft, not moving air,** since a plugin has no way to move X-Plane's air at a point. A climbing turn tends to overbank a little, and a glider's own netto instrument may read wrong. Its total energy vario reads right.
- **Two pilots at the same place and time do not see the same sky.**

## Reporting a problem

Open an [issue on GitHub](https://github.com/jlgabriel/xp-gliding/issues) saying what you did and what you saw, with your X-Plane and XPPython3 versions and the aircraft. Attach `XPPython3Log.txt` from your X-Plane folder: the plugin's lines start with `[xp-gliding]`, and the first one gives its version. If something goes wrong in flight, the plugin stops its effect, writes the error there, and its menu's first item reads *Enabled: stopped by an error*. A new flight or aircraft starts it again, and so does unticking and ticking *Enabled*.

What pilots report decides what comes next, so a note on how the thermals feel is welcome too.

## More

The [documentation](README.md) has what was measured about X-Plane along the way. The [working notes](../notes/README.md) hold the full record of the measurements quoted here.
