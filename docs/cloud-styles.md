# Cloud styles

A cloud style sets how XP-Gliding's cumulus look, the way a livery sets how an aircraft looks. Where the clouds are, how big, how high and how long they live stay the plugin's, because a cloud tells the pilot about the thermal under it. A style changes only how the cloud is drawn.

*Plugins → XP-Gliding → Cloud style* lists the styles found when X-Plane starts. The one ticked is the one drawn. Choosing another replaces the clouds at once, and new ones fill in over a few seconds. The choice is saved. The command `xp_gliding/clouds/style/next` steps to the next style; bound to a key in X-Plane's keyboard settings, it compares styles in flight.

## Installing a style

A style is a folder. Put it in `X-Plane 12/Resources/plugins/PythonPlugins/xp-gliding-cloud-styles/`, beside the plugin's `xp_gliding` folder. The plugin's zip brings that folder, and the plugin makes it if it is missing. Updating the plugin replaces only `xp_gliding` and `PI_xp_gliding.py`, so your styles survive updates. Restart X-Plane, and the style is in the menu.

The plugin comes with three styles, in `xp_gliding/assets/clouds/`:

- *Standard*, the default: lobes of several sizes, soft edges, no layer under the base.
- *Cotton (soft edges)*: the cumulus of version 0.8, softer and fuller, with a light layer of flat puffs and wisps under the base.
- *Cauliflower (crisp, bright lobes)*: a whiter cloud of round lobes with firm outlines, with the same layer under the base.

All three are drawn at the same size over the same thermals. A style of your own with the same folder name as one of the plugin's is left out.

If a style cannot be loaded, the clouds are drawn with *Standard* and the log, `XPPython3Log.txt`, says why. The menu then ticks *Standard*. Your choice stays saved, for when the style is mended. The log also lists the styles found at start, and any folder left out.

## What a style holds

```
xp-gliding-cloud-styles/
  my-style/
    cumulus.obj    the object each cloud is an instance of (required)
    cumulus.pss    its particle system, named in cumulus.obj
    cumulus.png    its texture, named in cumulus.pss
    style.txt      its name, author and license, for the menu (optional)
```

`style.txt` holds up to three lines:

```
name: Soft cumulus
author: Your name
license: CC-BY-4.0
```

The menu shows "Soft cumulus, by Your name". Without the file, it shows the folder's name. The menu can only show plain ASCII, so accents are dropped there: they stay in the file.

## Making one: repaint the texture

The simplest style is a copy of *Standard* with a new texture, the way a livery is a new paint on the same model.

1. Copy `xp_gliding/assets/clouds/standard/` to `xp-gliding-cloud-styles/my-style/`, both in `PythonPlugins/`.
2. Edit `style.txt`.
3. Repaint `cumulus.png`.
4. Restart X-Plane and choose *my-style* in the menu.

The texture is a 1024 × 1024 RGBA image cut into 4 × 4 cells of 256 px, numbered 0 to 15 from the top left, row by row. Each particle draws one cell, picked at random from the cells of its kind. In *Standard* only cells 4 to 11, the middle two rows, are drawn: shaded lobes of the cloud's body. The top row (wide, flat-bottomed puffs) and the bottom row (small lobes and wisps) are in the image but no particle uses them.

The image's alpha is the cloud's shape: each puff should fade to fully transparent before the edge of its cell. A puff cut by its cell shows as a straight line from close up. Particles are billboards that always face the camera, so the light is painted into the texture: lit from above and shaded below. X-Plane's own light on them is set in `cumulus.pss` (`DIFFUSE` and `AMBIENT`).

X-Plane may keep a texture or particle system it has loaded until it restarts. After you edit a file, restart X-Plane to see the change.

## Going further: the particle system

`cumulus.pss` sets each layer of particles: which cells it draws, how big its billboards are, where in the cloud they appear and how opaque they get. The file format has no public specification. The concepts are in Laminar's [particle system article](https://developer.x-plane.com/article/x-plane-11-particle-system/), and *Standard*'s file is written by `tools/make_cloud_objs.py`, whose comments say what each part does. What was found about X-Plane's emitters while building it is in [this finding](findings/particle-emitters.md).

A style keeps the clouds honest to their thermals only if it keeps these:

- **The two datarefs.** Every emitter must read `xp_gliding/clouds/rate` and `xp_gliding/clouds/scale` as its slots, as *Standard*'s do. The plugin sets both for each cloud. *Rate* 0 stops feeding the cloud, 1 keeps it steady, and up to 20 fills it fast. *Scale* 1 is the cloud's base size, and it goes up to 2: the emission offsets and the particle sizes grow with it. A style that ignores rate never fades with its thermal, and one that ignores scale draws every cloud the same size.
- **The size.** At scale 1 *Standard*'s particles are emitted up to 500 m each side of the cloud's centre and up to 450 m above its base; a typical cloud is drawn about 850 m wide and 420 m tall. A much wider or narrower cloud no longer says how wide its thermal is.
- **The base.** The object's origin is the cloud's base. Particles below it put cloud where the pilot expects clear air under the base.
- **The life of a particle.** The plugin times a cloud's fading and the reuse of its objects on particles living at most 216 s. Longer-lived particles linger after their cloud has gone.
- **No speed and no gravity.** Particles stay where they are born and drift only with the wind (`DRAG_CURVE` 1), so a cloud stays over its thermal.

Two things about cost and stability, measured in X-Plane 12.4.3 under Vulkan while building *Standard*:

- **At most three sub-emitters per emitter.** Eight in one emitter crashed X-Plane a few seconds after the first cloud appeared. Three were always fine.
- **Particles cost frame time.** *Standard* keeps 183 alive in a full cloud, and dozens of clouds can be in view. Check your frame rate with the clouds on and off before you share a style.

## Sharing a style

Share the folder, zipped, with its `style.txt`. Say in it under which license others may use it. Use only images you made or may share: textures taken from another simulator or add-on usually may not be shared. *Standard* is GPL-3.0-or-later, like the plugin, and a style made from it carries that license unless all of its files are your own.
