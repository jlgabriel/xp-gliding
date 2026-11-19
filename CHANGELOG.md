# Changelog

What changes for a pilot in each version. Each release on [GitHub](https://github.com/jlgabriel/xp-gliding/releases) has the zip and the same notes, with how to update.

## 2.0 — 2026-11-19

- **The Flight Computer, a second instrument.** *Plugins → XP-Gliding → Instrument* chooses the Soaring HUD (the default), the Flight Computer or none. The Flight Computer is a window you can move and resize, with a strip of total energy, the 30 s average and the altitude, the simulator's local time, and two views. MAP is a topographic map that follows the glider, with the track flown coloured by height, the wind, zoom and a scale; its tiles come from OpenTopoMap over the internet, and without a network the glider and the track still draw on a latitude and longitude grid. FLIGHT has netto, the thermal's climb, height above the ground, airspeed and ground speed, the wind and the height to the cloud: the HUD's own readings, larger. Its place and size are kept, and a click in it leaves the keyboard with X-Plane. It stays inside X-Plane's window: X-Plane 12.4.4 draws a popped-out browser window wrong, so its pop-out button puts it back. It needs X-Plane 12.4.4 and XPPython3 4.8.0 or later; otherwise it is greyed out and the HUD stays. The menu's *Soaring HUD* item is now in *Instrument*, its command `xp_gliding/hud/toggle` works as before, and `xp_gliding/computer/toggle` does the same for the Flight Computer. *Units on the HUD* is now *Units*, for both instruments. How it works: [pilot guide](docs/pilot-guide.md#the-flight-computer).
- **Tasks in the Flight Computer.** Put SeeYou CUP files in `Output/xp-gliding/tasks/` and choose a task in the Flight Computer's new TASK tab. The map draws its legs, points and observation zones, and a row under the strip names the point you are flying to, with which way to turn, its bearing and distance. Each point is taken as you fly into its zone (the start as you leave its zone or cross its line), and *Prev* and *Next* step by hand. Zones come from the file; points without one get a 2 km start line and 500 m cylinders. The task you choose is loaded again at the next start, as long as its file still has it. How it works: [pilot guide](docs/pilot-guide.md#task).
- **Works in X-Plane 12.4.4.** Flown in X-Plane 12.4.4 under Vulkan: the plugin starts, its clouds and HUD show, and a uniform lift of 2 m/s makes the ASK 21 climb 2.00 m/s faster than in still air, as in 12.4.3. Version 1.2 already worked there unchanged.
- **A lighter HUD.** With X-Plane 12.4.4 and XPPython3 4.8.0 or later, the HUD draws with Panel Graphics, X-Plane's newer 2D drawing. It looks the same, and costs about 33 µs a frame instead of about 0.3 ms. With an earlier X-Plane or XPPython3 it draws as before, and if Panel Graphics ever fails it goes back to the old way by itself and notes it in `XPPython3Log.txt`. XPPython3 updates from its own menu, *Plugins → XPPython3*, or from [its page](https://xppython3.readthedocs.io/).
- **A cloud keeps one height, whenever it comes into view.** Each cloud's base clears the high ground along its whole drift, from when it forms. Before, a cloud that came into view after drifting past a hill could sit lower than the same cloud seen earlier, and after a very long flight a cloud's lift could end at another height from the cloud drawn.
- **Settings written through datarefs keep the menu's limits.** Writing `xp_gliding/zi_m`, `xp_gliding/wstar_ms` or another setting from a script or another plugin now gets the same limits as the menu and `config.json`, so a zi of -500 m becomes 1000 m. It also does what the menu does: setting `xp_gliding/enabled` to 1 starts the plugin again after an error, and switching `xp_gliding/weather_base_enabled` reads the weather afresh.
- **No force from a reading that is not a number.** While X-Plane loads an aircraft or a scene, a reading such as the mass or the airspeed can briefly be not a number. The plugin now gives no force for that frame, and carries on with the next good one. Before, it could pass that on to X-Plane as the force, or stop until the next flight. `xp_gliding/bad_frames` counts such frames.

## 1.2 — 2026-11-15

- **Hotspot flight.** *Plugins → XP-Gliding → Hotspot flight* flies the sky of a site from a file of thermal hotspots, in place of the plugin's own sky. Download the hotspots of the area you want from [thermal.kk7.ch](https://thermal.kk7.ch/) (*Download currently visible hotspots → csv*), put the file in `Output/xp-gliding/hotspots/` in your X-Plane folder and restart X-Plane; the file is then listed in the submenu. The thermals are only where the file says pilots find them, and none elsewhere. Each hotspot works in cycles, one thermal at a time, and has one for the share of the time its probability says: a hotspot of 100% almost always, one of 60% a little more than half the time. Each thermal carries a cloud and drifts with the wind, and the daily cycle, the HUD, the training markers and *Put me near a cloud* work as in a normal flight. Where the file has no hotspots there are no thermals. *None: a normal flight* brings the plugin's sky back. How it works: [pilot guide](docs/pilot-guide.md#a-hotspot-flight).
- ***Good and bad areas* off by default.** A first flight now has the same sky everywhere, the easier one; tick the item when you want choosing where to fly to matter. If you have flown an earlier version, your settings file keeps the choice you had.
- **The worst areas are never empty.** With *Good and bad areas* on, the poorest stretches had no thermals at all, which could leave half the sky without a cloud. They now keep at least a fifth of the thermals, weak and under small clouds, so the contrast is still marked but no part of the sky is blank.

## 1.1.1 — 2026-11-15

- **Softer edges for *Billow* and *Billow light*.** Their outline still read as round balls that ended abruptly against the sky. The rendered heaps now fade out through several thinner, looser layers, so the edge frays into tufts and blends with the sky, and the round balls are gone from the outline. The inside keeps a little less relief than in 1.1. The clouds are about the same size as before. Each style's texture is larger, so the zip grows by about 4 MB. If *Billow* or *Billow light* is your style, it is still chosen after the update.
- ***Billow light* is the default cloud style**, in place of *Standard*. If you have flown an earlier version, your settings file keeps the style you had: choose *Billow light* in *Plugins → XP-Gliding → Cloud style* to see it. *Standard* is still the one drawn when a style cannot be loaded.

## 1.1 — 2026-11-14

- **Two new cloud styles: *Billow* and *Billow light*.** A new way of drawing a cloud: each particle is a whole heap of cumulus, rendered in Blender as a lit volume, with sunlit bulges, grey creases, a shaded underside and soft, hairy edges, so a cloud is a few large pieces instead of many small puffs. *Billow light* has lighter shade and a softer fringe. Choose them in *Plugins → XP-Gliding → Cloud style*. Like every style they change only the look: where the clouds are, how big and how long they live are the same.
- ***Sharper thermal edges* off by default.** A first flight now has smooth thermals, to learn them before the rougher air: the jolt into and out of lift, the bumps at the edge, the ring of sink and the sink between thermals. Tick the item when you want them. If you have flown an earlier version, your settings file keeps the choice you had.
- **A new flight takes its own wind at once.** Starting a new flight with the same aircraft, or jumping on the map, kept the last flight's lean of the thermals and training markers for a minute, or for as long as the sim was paused. The lean now follows the new flight's wind as soon as it loads.

## 1.0 — 2026-11-14

- **Cloud styles.** *Plugins → XP-Gliding → Cloud style* chooses how the cumulus look, as a livery does for an aircraft. The plugin comes with four: *Standard*, today's clouds; *Cotton*, the softer, fuller cumulus of 0.8; *Cauliflower*, whiter, with crisp round lobes; and *Popcorn*, Standard with a new texture of round white puffs. Styles of your own go in `xp-gliding-cloud-styles`, a folder the zip now brings, to copy beside the plugin in `Resources/plugins/PythonPlugins/`; a new version of the plugin leaves it alone, and they show in the menu after a restart. A style changes only the look: where the clouds are, how big, how high and how long they live, and so what they say about their thermals, are the same with every style. A style that cannot be loaded gives *Standard*. How to make one, starting from a new texture: [Cloud styles](docs/cloud-styles.md).
- **Pictures in the documentation.** The pilot guide shows the menu, the HUD, the training markers and the sky as seen from the glider, and [Cloud styles](docs/cloud-styles.md) shows its submenu and the four styles side by side, all taken in this version.

## 0.9.2 — 2026-11-13

- **Smaller cumulus.** Every cloud is drawn at 70 % of its former size: a typical one is now about 850 m wide and 420 m tall, from about 1.2 km and 600 m, and the largest no bigger than a typical one was. A cloud is closer to the width of the lift under it, and there is more blue sky between clouds, so neighbours run together less. Their look, number, place, life and lift are unchanged.

## 0.9.1 — 2026-11-13

- **Lighter cumulus.** The flat grey layer along a cloud's base and the wisps under it are gone: seen from near the base's height they drew a horizontal band. The outline is no longer a chain of small round puffs, and the top is made of fewer, larger lobes. The texture, and the clouds' size, place, life and lift are unchanged, and there are fewer particles to draw (183 per cloud, from 311).
- ***Sharper thermal edges* on by default.** The jolt into and out of lift, the bumps at the edge, the ring of sink and the sink between thermals are now part of a first flight. Untick the item to fly without them. If you have flown an earlier version, your settings file keeps the choice you had: tick it in the menu once.
- **The climb in this thermal on the HUD.** `THM` gives the average climb since you began circling, as a glider's computer does. A few straight seconds to move the circle stay in the same thermal; after 20 s straight it is greyed, and it keeps the last thermal's figure until the next one has 10 s of circling. `AVG` is still the last 30 s.
- ***X-Plane's audio vario* in the menu.** It turns X-Plane's own audio vario on and off, the same switch as the AUDIO on the ASK 21's panel, for gliders that have none. Its tick follows the panel's switch. It is X-Plane's setting, so the plugin does not save it.
- **Fewer, smaller cumulus under X-Plane's clouds, none in rain.** Where X-Plane's cloud layers weaken the thermals, fewer of our cumulus form, and smaller, by as much: under a closed overcast about half of them, half the size. In rain they drain away over a few minutes, and *Put me near a cloud* says it is raining. A clear sky changes nothing.
- ***Sharper thermal edges (experiment)*: a weaker ring of sink.** Circling wide in a narrow thermal, the ring took away much of the climb. It is now two thirds as deep (0.2 of the thermal's mean lift, from 0.3).
- **A day chosen under *Cloud base from X-Plane's weather*** now says that its height is not used, since the weather sets the cloud base. Its strength and sky still apply.

## 0.9 — 2026-11-12

- **Good and bad areas.** Over tens of kilometres the thermals are more numerous and stronger in some areas, under more and bigger clouds, and fewer and weaker in others, where some stretches have almost none. In the best areas there are about 1.6 times as many thermals as on average, a fifth stronger; in the worst about 0.4 times as many, a fifth weaker. The sky as a whole holds as many as before, so choosing where to fly by the look of the sky pays. Each date has its own map, and with wind the areas drift with it. *Plugins → XP-Gliding → Good and bad areas* turns them off, for the same sky everywhere.
- **Clouds thin as their thermal weakens, and outlive it.** A full cloud has a thermal at its best; one that thins has a thermal that is fading; and a cloud stays a few minutes after its thermal has died, draining away, so a thin cloud may have nothing left under it. Before, a long-lived thermal lost its cloud while it still climbed well.
- **Less lift under X-Plane's clouds, none in rain.** Under the cloud layers set in X-Plane's weather the thermals weaken, by how much of the sky the layers cover and how thick they are: about half as strong under a closed overcast, a little weaker under scattered cloud, hardly at all under thin cirrus. In rain there are none. The change comes over a few minutes as the weather changes from place to place; a clear sky changes nothing. The plugin's own clouds do not count.
- ***Sharper thermal edges (experiment)*: a narrower, weaker ring of sink.** Leaving a thermal pulled the glider down too hard and too far out. The ring now reaches half as far beyond the thermal and is weaker; the jolt and the bumps on entering are as they were.

## 0.8 — 2026-11-11

- **New cumulus.** The clouds are drawn anew: lighter, with lobes of several sizes shaded where one hides another, towers that rise off the centre, a light grey base and soft edges that fade out instead of a firm outline of round puffs. Each cloud is turned its own way, so no two look alike. Their size, place, life and lift are unchanged, and they cost no more to draw.
- **Clouds earlier in the day.** With *Daily cycle* on, the first cumulus now come between about 10 and 10:40 am solar time, low, instead of around noon, so a morning flight has clouds to read sooner. Solar time is often well behind the clock: at Santiago in November, they come around 11:30 local time.
- ***Put me near a cloud* says why there is none** in the blue early morning, and from what local time the first clouds form.

## 0.7 — 2026-11-11

- **Put me near a cloud.** *Plugins → XP-Gliding → Put me near a cloud* sets the glider flying 1.5 km from the nearest cloud that will last a few minutes more, heading for it, a little over halfway from the ground to the cloud's base. A first flight no longer needs a tow before there is anything to see.
- **Days with a name.** *Plugins → XP-Gliding → Day* chooses a whole day at once: *Easy*, *Typical*, *Demanding*, *Weak and low*, or *Blue*, a day whose thermals climb as usual with no clouds to show where they are. The submenus for the sky, the strength, the depth and the seed stay, for choosing one thing at a time.
- **Sharper thermal edges (experiment).** *Plugins → XP-Gliding → Sharper thermal edges* adds a jolt when you fly into lift and out of it, bumps at a thermal's edge, stronger low down, a ring of sink around each thermal, and twice the sink between thermals. The climb in the thermal is unchanged. Off by default.
- **The name is now XP-Gliding** in the menu, X-Plane's plugin list and the documentation. Commands, datarefs, the settings file and the folders keep `xp_gliding` and `xp-gliding`, so nothing needs changing on your side.

## 0.6 — 2026-11-11

- **Low thermals in the morning, a cloud base that rises.** With *Daily cycle* on, each thermal is as deep as the day was when it was born, and stays so. In the morning they are low and narrow: around 10 am solar time they end at less than half the afternoon's height, and they reach it by mid-afternoon. The first cumulus, around 1 pm solar time, stand a few hundred metres under the afternoon's base (about a sixth of its height), and the base rises to it by 3 pm. The depth chosen in the menu, or the weather's cloud base, is the afternoon's. The HUD's `TOP`, the training markers and the menu's last line follow the depth of the moment.
- **Knots and feet on the HUD.** *Plugins → xp-gliding → Units on the HUD → Aviation* shows the vario in knots and `TOP` in feet. Metric (m/s and m) stays the default, and the wind is in knots with both.

## 0.5 — 2026-11-10

- **The daily cycle.** The thermals follow the sun: weak a little after sunrise, strongest around 1 pm solar time, weaker through the afternoon, with the strength chosen in the menu as the day's best. The morning is blue, and the first cumulus come around solar noon. No thermal is born with the sun under 10° (it was 5°). *Plugins → xp-gliding → Daily cycle* turns it off, for the same strength all day.

## 0.4 — 2026-11-10

- **The thermals' density follows the depth of the day.** A deeper day has fewer, wider thermals and a shallower one more, narrower ones, as in the model the thermals come from, so the sink between thermals is the same at every depth. Under the default depth (2000 m) the sky is the same as before. Where each thermal is now depends on the depth too.
- **Cloud base from X-Plane's weather** is kept between 1000 m and 3500 m above the ground (it was 500–3500 m): under a lower base the thermals are too narrow to climb in.
- **The menu's last line says what the plugin is doing:** how many thermals are within reach and the depth in use, or why there are none (the sun is low, the aircraft has engines, a switch is off, an error).
- **An error no longer stops the plugin until X-Plane restarts.** The menu says so, and a new flight, a new aircraft, or unticking and ticking *Enabled* starts it again.
- **`config.json` is checked when read:** a value of the wrong kind, or not a number, is left out, and a number out of range is brought to the nearest end. The log says which.
- **The HUD's average climb starts over after a jump** (a new flight, a move on the map, a change of time), instead of counting the jump as a climb or a descent.
- The same sky needs calm air and the same time, besides the same place, date and seed; the guide and README said less.
- A little less work per frame.

## 0.3 — 2026-11-09

- **Cloud base from X-Plane's weather (experiment).** *Plugins → xp-gliding → Cloud base from X-Plane's weather* sets the height of the clouds from the temperature and dew point of the weather flown, real or set by hand. It takes the place of the depth chosen in the menu, and the thermals reach as high as their clouds. The weather is read when a sky begins and once more about 90 s later, then kept. Off by default; the strength of the day is still chosen in the menu.

## 0.2 — 2026-11-08

- **No sun, no thermals.** A thermal is born only while the sun is at least 5° above the horizon, so the sky empties over about half an hour around sunset and fills again after sunrise. At night the air is still.
- **Motor gliders.** *Plugins → xp-gliding → Treat this aircraft as a glider* gives the thermals to an aircraft with an engine, running or not. The plugin remembers it by the aircraft's file.

## 0.1 — 2026-11-08

The first public version.

- Thermals that grow, peak and fade, each with a cumulus of its own when it carries one, so a cloud means lift.
- Thermals and clouds drift with X-Plane's wind. The lift ends near the cloud's base, and no thermal starts over water.
- Lift with no per-aircraft calibration. The Laminar ASK 21 is the reference.
- A soaring HUD: total energy, netto, average climb, height to the cloud, wind and a centring aid.
- Optional training markers that show where the thermals are.
- A menu to choose the sky and the day, saved between sessions.
