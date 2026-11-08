xp-gliding {version}
===================

Thermals for gliders in X-Plane 12: find them by reading the clouds, and climb
in them by hand.

This is the first public version. Its known limits are listed in the pilot
guide.

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
3. Start X-Plane. The menu Plugins > xp-gliding should be there.

Updating from an earlier version: delete the old xp_gliding folder first,
then copy the new one. Your settings are kept.

Removing: delete PI_xp_gliding.py and the xp_gliding folder. Your settings are
in X-Plane 12/Output/xp-gliding/config.json, which can be deleted too.


A FIRST FLIGHT
--------------

1. Weather: fly by day, and turn off X-Plane's own cumulus clouds. The plugin
   draws its own clouds over its thermals, and X-Plane's clouds mark none of
   them. Wind is fine.
2. Aircraft: the Laminar ASK 21. The plugin does nothing on aircraft with
   engines.
3. For the first climb, turn on Plugins > xp-gliding > Training markers: a
   ring at your height shows where each nearby thermal is. Turn them off later
   and fly by the clouds.
4. Get airborne and fly towards a cloud. Check that the airbrakes are closed.
5. When the vario goes up, circle: a bank of about 30 degrees at 90-95 km/h
   works well in the ASK 21.
6. For sound, turn on the AUDIO switch on the ASK 21's panel: X-Plane's own
   audio vario hears the plugin's thermals.

Everything is ready out of the box: no file to edit and nothing to set in
X-Plane's thermal settings.


THE MENU (Plugins > xp-gliding)
-------------------------------

- Enabled: the plugin on or off.
- Training markers: show where the thermals are.
- Cumulus clouds, Soaring HUD: turn each off if you like.
- Sky: wide thermals (the default, easiest), medium, or narrow (hardest).
- Strength of the day, Depth of the thermal layer: stronger or weaker
  thermals, higher or lower clouds.
- Seed of the sky: another arrangement of thermals.
- Items marked (experiment) are off by default and best left off.

Your choices are saved for the next session.


SOMETHING WRONG?
----------------

Open an issue at https://github.com/jlgabriel/xp-gliding/issues saying what
you did and what you saw, your X-Plane and XPPython3 versions and the
aircraft, and attach XPPython3Log.txt from your X-Plane 12 folder.


License: GPL-3.0-or-later (see LICENSE).
