# Changelog

What changes for a pilot in each version. Each release on [GitHub](https://github.com/jlgabriel/xp-gliding/releases) has the zip and the same notes, with how to update.

## Unreleased

- **The climb in this thermal on the HUD.** `THM` gives the average climb since you began circling, as a glider's computer does. A few straight seconds to move the circle stay in the same thermal; after 20 s straight it is greyed, and it keeps the last thermal's figure until the next one has 10 s of circling. `AVG` is still the last 30 s.
- ***X-Plane's audio vario* in the menu.** It turns X-Plane's own audio vario on and off, the same switch as the AUDIO on the ASK 21's panel, for gliders that have none. Its tick follows the panel's switch. It is X-Plane's setting, so the plugin does not save it.

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
