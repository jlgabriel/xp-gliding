XP-Gliding {version}
===================

Thermals for gliders in X-Plane 12: find them by reading the clouds, and climb
in them by hand.

Its known limits are listed in the pilot guide.

Full pilot guide:
https://github.com/jlgabriel/xp-gliding/blob/main/docs/pilot-guide.md


WHAT YOU NEED
-------------

- X-Plane 12 (tried on 12.4.3 and 12.4.4, Windows 11).
- XPPython3, the plugin that runs Python plugins in X-Plane:
  https://xppython3.readthedocs.io/
  Install it and start X-Plane once, so that it creates the folder
  X-Plane 12/Resources/plugins/PythonPlugins/
  The Flight Computer and the Glide Computer need X-Plane 12.4.4 and
  XPPython3 4.8.0 or later; everything else works with earlier versions too.
- A glider. The Laminar ASK 21 that comes with X-Plane is the reference.


INSTALLING
----------

1. Close X-Plane.
2. From this folder, copy these three items:

       PI_xp_gliding.py
       xp_gliding                (the whole folder)
       xp-gliding-cloud-styles   (the folder for cloud styles of your own)

   into:

       X-Plane 12/Resources/plugins/PythonPlugins/

   README.txt and LICENSE do not need to be copied.
3. Start X-Plane. The menu Plugins > XP-Gliding should be there.

Updating from an earlier version: delete the old xp_gliding folder first,
then copy the new one. Your settings are kept. Leave xp-gliding-cloud-styles
as it is, or copy the new one over it: your styles in it are kept.

Removing: delete PI_xp_gliding.py, the xp_gliding folder and the
xp-gliding-cloud-styles folder. Your settings are in
X-Plane 12/Output/xp-gliding/config.json, which can be deleted too.


A FIRST FLIGHT
--------------

1. Weather: fly by day, best from late morning to mid-afternoon, and turn
   off X-Plane's own cumulus clouds. The thermals follow the sun: weak and low
   in the morning, strongest around 1 pm solar time, none with the sun under 10
   degrees, and the first clouds late in the morning, lower than later on. The plugin draws its own
   clouds over its thermals, and X-Plane's clouds mark none of them. Wind is
   fine.
2. Aircraft: the Laminar ASK 21. The plugin does nothing on aircraft with
   engines, unless you choose Treat this aircraft as a glider in the menu,
   which is how a motor glider gets the thermals.
3. For the first climb, turn on Plugins > XP-Gliding > Training markers: a
   ring at your height shows where each nearby thermal is. Turn them off later
   and fly by the clouds.
4. Get airborne and fly towards a cloud, or choose Plugins > XP-Gliding >
   Put me near a cloud to start flying 1.5 km from one, heading for it.
   Check that the airbrakes are closed.
5. When the vario goes up, circle: a bank of about 30 degrees at 90-95 km/h
   works well in the ASK 21.
6. For sound, turn on the AUDIO switch on the ASK 21's panel: X-Plane's own
   audio vario hears the plugin's thermals.

Everything is ready out of the box: no file to edit and nothing to set in
X-Plane's thermal settings.


THE MENU (Plugins > XP-Gliding)
-------------------------------

- Enabled: the plugin on or off.
- Sharper thermal edges (experiment): a jolt into and out of lift, bumps at
  the edge, a ring of sink, more sink between thermals. Off by default.
- Daily cycle: the thermals follow the sun, and are low in the morning. Off:
  the same strength and depth all day.
- Good and bad areas: more and stronger thermals in some areas, fewer and
  weaker in others, so where you fly matters. Off by default.
- Training markers: show where the thermals are.
- Cumulus clouds: turn them off if you like.
- X-Plane's audio vario: X-Plane's own audio vario, for gliders without an
  AUDIO switch on the panel.
- Treat this aircraft as a glider: for a motor glider, remembered by its file.
- Put me near a cloud: start flying 1.5 km from a cloud, heading for it.
- Instrument: the Soaring HUD (the default), the Flight Computer, the Glide
  Computer or none. The Flight Computer is a window with a map of your track,
  larger readings and tasks: put SeeYou CUP files, or the Sim Soaring Club's
  flight plans (.pln, height limits included), in
  X-Plane 12/Output/xp-gliding/tasks/ and choose a task in its TASK tab. An
  empty folder gets an example task, a 29.5 km triangle from Tobalaba,
  Santiago, Chile. The Glide Computer is the same window with the functions
  of Condor 3's flight computer: GLIDE, INFO and THERMAL screens (THERMAL
  close in, its track coloured by climb), Condor's map colours, and commands
  to bind to keys (XP-Gliding computer).
- Day: a whole day at once: Easy, Typical, Demanding, Weak and low, or Blue
  (the same thermals, no clouds to read). The items below set one thing each.
- Sky: wide thermals (the default, easiest), medium, or narrow (hardest).
- Strength of the day, Depth of the thermal layer: stronger or weaker
  thermals (at the best time of the day), higher or lower clouds.
- Seed of the sky: another arrangement of thermals.
- Units: metric (m/s, m and km/h) or aviation (knots, feet and nautical
  miles), for both instruments.
- Cloud style: how the clouds look, like a livery. Billow light is the
  default; your own styles go in xp-gliding-cloud-styles.
- Hotspot flight: thermals only where a file of hotspots from
  thermal.kk7.ch says pilots find them. Put the file in
  X-Plane 12/Output/xp-gliding/hotspots/ and restart X-Plane.
- Cloud base from X-Plane's weather (experiment): the clouds' height from the
  weather you fly, in place of the depth.
- Items marked (experiment) are off by default. The two about the wind are
  best left off.

Your choices are saved for the next session.


SOMETHING WRONG?
----------------

First look at the last line of Plugins > XP-Gliding: it says what the
plugin is doing, or why there are no thermals. The pilot guide has what to
do for each case.

If that does not help, open an issue at
https://github.com/jlgabriel/xp-gliding/issues saying what you did and what
you saw, your X-Plane and XPPython3 versions and the aircraft, and attach
XPPython3Log.txt from your X-Plane 12 folder.


License: GPL-3.0-or-later (see LICENSE).
