XP-Gliding {version}
===================

Thermals for gliders in X-Plane 12: find them by reading the clouds, and climb
in them by hand.

Its known limits are listed in the pilot guide.

Full pilot guide:
https://github.com/jlgabriel/xp-gliding/blob/main/docs/pilot-guide.md


WHAT YOU NEED
-------------

- X-Plane 12 (tried on 12.4.3, Windows 11).
- XPPython3, the plugin that runs Python plugins in X-Plane:
  https://xppython3.readthedocs.io/
  Install it and start X-Plane once, so that it creates the folder
  X-Plane 12/Resources/plugins/PythonPlugins/
- A glider. The Laminar ASK 21 that comes with X-Plane is the reference.


INSTALLING
----------

1. Close X-Plane.
2. From this folder, copy these two items:

       PI_xp_gliding.py
       xp_gliding          (the whole folder)

   into:

       X-Plane 12/Resources/plugins/PythonPlugins/

   README.txt and LICENSE do not need to be copied.
3. Start X-Plane. The menu Plugins > XP-Gliding should be there.

Updating from an earlier version: delete the old xp_gliding folder first,
then copy the new one. Your settings are kept.

Removing: delete PI_xp_gliding.py and the xp_gliding folder. Your settings are
in X-Plane 12/Output/xp-gliding/config.json, which can be deleted too.


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
- Daily cycle: the thermals follow the sun, and are low in the morning. Off:
  the same strength and depth all day.
- Training markers: show where the thermals are.
- Sharper thermal edges (experiment): a jolt into and out of lift, bumps at
  the edge, a ring of sink, more sink between thermals. On by default.
- Cumulus clouds, Soaring HUD: turn each off if you like.
- Treat this aircraft as a glider: for a motor glider, remembered by its file.
- Put me near a cloud: start flying 1.5 km from a cloud, heading for it.
- Day: a whole day at once: Easy, Typical, Demanding, Weak and low, or Blue
  (the same thermals, no clouds to read). The items below set one thing each.
- Sky: wide thermals (the default, easiest), medium, or narrow (hardest).
- Strength of the day, Depth of the thermal layer: stronger or weaker
  thermals (at the best time of the day), higher or lower clouds.
- Seed of the sky: another arrangement of thermals.
- Units on the HUD: metric (m/s and m) or aviation (knots and feet).
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
