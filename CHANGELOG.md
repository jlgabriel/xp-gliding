# Changelog

What changes for a pilot in each version. Each release on [GitHub](https://github.com/jlgabriel/xp-gliding/releases) has the zip and the same notes, with how to update.

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
