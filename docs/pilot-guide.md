# Pilot guide

How to install xp-gliding, make a first flight and read its sky.

> **Draft.** xp-gliding has not been released, so this describes the current development version, and details will change before the first release.

## What you need

- X-Plane 12. The plugin has been flown in version 12.4.3 under Vulkan, on Windows 11. Other versions and systems have not been tried.
- [XPPython3](https://xppython3.readthedocs.io/), the plugin that runs Python plugins in X-Plane, started once so that it creates its folders. Version 4.7.1 has been tried. Nothing else is needed.
- A glider. The reference is the Laminar ASK 21 that comes with X-Plane.

## Installing

1. Copy `PI_xp_gliding.py` and the `xp_gliding` folder into `Resources/plugins/PythonPlugins/` in your X-Plane folder.
2. Restart X-Plane. XPPython3's "Reload scripts" is not reliable for this.
3. Check that *Plugins → xp-gliding* appears in the menu.

To remove the plugin, delete those two items. Your settings are kept in `Output/xp-gliding/config.json`, which can be deleted too.

The plugin acts only on an aircraft with no engines. On any other aircraft it does nothing.

## A first flight

1. **Set the weather.** Use X-Plane's weather with no cumulus layer of its own: X-Plane's clouds mark none of the plugin's thermals, so flying towards one finds nothing. A steady wind is fine. Fly by day, since the thermals do not follow the sun yet, and at night there is nothing to see.
2. **Choose the sky.** In *Plugins → xp-gliding → Sky*, choose *Wide thermals under the clouds (x2)*. It is the sky with the most flying behind it. The narrow sky is hard to climb in with this glider.
3. **Turn on the markers for the first climb.** *Training markers* shows where the thermals are, which helps while learning how a climb feels. Turn them off to fly by the clouds.
4. **Get airborne,** by tow or with an air start, and fly towards a cloud.
5. **Check that the airbrakes are closed.** The ASK 21 can start with them open, which feels like a heavy glider and reads as strong sink.
6. **Circle where the lift is.** A bank of 28–35° at 90–95 km/h has worked in the ASK 21. Two climbs flown by hand in X-Plane 12.4.3 gave +2.31 m/s over 126 s at 35° and 95 km/h, and +1.19 m/s over 653 s at 28° and 92 km/h, the second in 15 kt of wind on the way up to near the cloud.
7. **Listen to the vario, if you like.** On the Laminar ASK 21, the AUDIO switch on the panel turns on X-Plane's own audio vario, which reads the plugin's lift.

The native thermal setting is held at 0 while the plugin is active and restored afterwards, so there is nothing to change there. X-Plane's ridge lift stays on and adds to the thermals where the ground slopes.

## Reading the sky

- **A cloud means a thermal.** Each cloud is drawn by the plugin over a thermal that carries one. In the wide sky, few thermals have no cloud, and they are weaker.
- **Clouds are born and die with their thermal.** A thermal lives between 5 and 30 minutes, growing and then fading, and never vanishes at once. A cloud that is fading has a thermal that is weakening.
- **A bigger cloud usually means a stronger thermal.** This holds on average in an offline comparison of the two, and in three thermals flown by hand, which is too few to rely on.
- **Everything moves with the wind.** Thermals and clouds drift with X-Plane's wind, as the glider does, so a circle needs no correction for it, even while the ground passes underneath. In strong wind this can make a turn look odd, and a thermal can carry you towards high ground.
- **A climb ends near its cloud.** The lift fades towards the cloud's base. A scripted flight in a strong thermal reached the base, and offline a typical one stops 100–175 m under it at 35° and 95 km/h, closer when flown tighter and slower.
- **Clouds keep to a level for the area,** and stand higher where the ground under them or along their drift would reach them.
- **No thermal starts over water.** One born over land can drift out over the sea.

## The HUD

A small panel on the screen. The vario readings and the centring arrow use only what a real glider could sense, not the plugin's knowledge of where the thermals are.

| Item | What it shows |
| --- | --- |
| Large amber number, and the tape | Total energy rate, m/s |
| `NET` | Netto: the air's own motion, from total energy and the glider's sink. Only the Laminar ASK 21 has a measured polar, and any other glider shows `NET --` |
| `AVG` | The average climb over the last 30 s, m/s |
| `TOP` | Height up to the nearest thermal's cloud, m. It can jump when the nearest cloud changes |
| `WIND` | The wind at the glider, in knots, with an arrow pointing where it goes, relative to the nose |
| Centring arrow | Which way the core lies, when the lift swings enough around the circle to tell. In scripted circles it was right 89% of the time within 45° from 60 to 100 m off centre, and about half the time from 30 to 60 m. Closer than that it says little |

## The menu

Everything is in *Plugins → xp-gliding*. What you choose is saved for the next session, and each switch is also a command you can bind to a key.

| Item | What it does | Command |
| --- | --- | --- |
| Enabled | The plugin's whole effect | `xp_gliding/toggle` |
| Thermals | The lift, without turning off the rest | `xp_gliding/thermals/toggle` |
| Thermals follow the wind | The wind carries thermals, clouds and markers | `xp_gliding/wind/toggle` |
| Thermals lean with the wind | An experiment: lift upwind of the cloud when low. Off by default | `xp_gliding/lean/toggle` |
| Sky moves with the wind at the clouds | An experiment that makes a climb much harder in shear. Off by default | `xp_gliding/wind/clouds/toggle` |
| Training markers | A ring at your height over each nearby thermal, and a thin column up to its cloud | `xp_gliding/markers/toggle` |
| Cumulus clouds | The plugin's clouds | `xp_gliding/clouds/toggle` |
| Soaring HUD | The panel above | `xp_gliding/hud/toggle` |
| Sky | How wide the thermals are and how many have no cloud | |
| Strength of the day (w\*) | How strong the thermals are | |
| Depth of the thermal layer (zi) | How high they go, and so the height of the clouds | |
| Seed of the sky | A different arrangement of thermals | |

Markers appear for up to 20 thermals within 3 km with at least 1.5 m/s at the core. The colour shows the lift at the core at your height: pale below 2 m/s, yellow from 2, orange from 3, and red from 4.

Choosing another sky, seed or depth in flight replaces the clouds at once, and new ones fill in. Nothing was felt in a thermal when flown by hand.

## Known limits

- **The day is chosen in the menu.** Strength and cloud base do not follow X-Plane's weather yet, so the thermals are the same on a dry day and a humid one.
- **The sun is not read.** Thermals and clouds are there at any hour.
- **A far cloud can appear in front of a near one,** with a sharp edge, most of all close to a big cloud. The likely cause is the order in which the simulator draws them.
- **X-Plane's own cumulus mark none of these thermals.** The two can share a sky, and to read it, leave X-Plane's off.
- **The Laminar ASK 21 is the reference.** Other gliders get the lift and no netto. A glider whose wings are not in the usual parts of its file is treated as an ASK 21 for the roll. An aircraft with engines gets nothing, so a motor glider is left out.
- **A glider flies as well as its own flight model allows.** The Laminar ASK 21 sinks about 2.1 m/s circling at 45°, measured by a scripted autopilot in X-Plane 12.4.3, so steep turns cost a lot of climb.
- **Lift is a force on the aircraft, not moving air,** since X-Plane has no way to move air at a point. A climbing turn tends to overbank a little even with the plugin's correction, and a glider's own netto instrument may read wrong. Its total energy reads right.
- **Two pilots at the same place and time do not see the same sky.**

## Reporting a problem

Open an [issue on GitHub](https://github.com/jlgabriel/xp-gliding/issues) saying what you did and what you saw, along with your X-Plane and XPPython3 versions and the aircraft. Attach `XPPython3Log.txt` from your X-Plane folder: the plugin's lines start with `[xp-gliding]`, and if something goes wrong in flight, it stops its effect and writes the error there.

## More

The [documentation](README.md) has what was measured about X-Plane along the way. The [working notes](../notes/README.md) hold the full record of the measurements quoted here.
