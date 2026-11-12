# Cloud looks

2026-11-11, a separate session working only on how the cumulus looks, while the thermals work goes on on `main` (Juan Luis decided to try it now, out of curiosity). The SPEC item is *Cloud looks* under stage 2, *Instruments and looks*; the model to follow is X-Plane 12's own cumulus.

## Where it started

The cumulus of 0.7: three particle types (a flat grey base, a white body, small bright tops), 60 + 180 + 80 particles at the steady rate, billboards of 210, 200 and 130 m, one texture of round puffs with a little mottling. From the seat, next to X-Plane's own (Juan Luis, 2026-11-07): small round puffs of one size, evenly bright, with a firm outline.

## First reshape, without changing technique

`tools/make_cloud_objs.py`, same object, same two values per instance (rate, scale), same particle life, about the same number of particles (294 against 320).

**Texture.** A new atlas of 16 cells, all drawn by the script:

| Cells | What | How |
| --- | --- | --- |
| 0-3 | Base | A low dome three times as wide as tall, a flat bottom, a lumpy top; even grey below, lighter higher up |
| 4-11 | Lobes | A density field of four to six round bulges, each with two or three smaller ones on its upper side, wide low down and narrower up; puffy noise inside; lit by summing the density between each pixel and a light above and a little to the side, so bulges are bright on top and shaded where another hides them; a darker belly; the edge eroded with noise |
| 12-13 | Small lobes | The same with three or four bulges, for edges and tops |
| 14-15 | Wisps | Fibres stretched sideways, thin, for the base's loose edges |

The first lobes, drawn as shaded spheres, looked like soap bubbles (hard outlines, dark rims where they met): dropped for the density field.

**Layers** (`LAYERS`), as chosen (v9), at scale 1, heights above the base, in the order they are drawn (last on top):

| Layer | Particles | Size (m) | Where (fraction of the 500 m half width; height) | Tint, alpha |
| --- | --- | --- | --- | --- |
| tower a, b, c | 40, 30, 20 | 270, 240, 220 × 0.6-1.4 | three narrow boxes off the centre, 150-400 m | white, 0.92 |
| top | 25 | 160 × 0.6-1.4 | 0.30, 380-480 m, over tower a | white, 0.88 |
| low | 75 | 290 × 0.6-1.4 | 0.78, 40-200 m | white, 0.95 |
| edge | 50 | 120 × 0.6-1.4 | 0.70, 40-240 m | white, 0.85 |
| wisp | 16 | 240 × 0.7-1.3 | 0.66, 0-120 m | near white, 0.35 |
| base | 40 | 280 × 0.7-1.3 | 0.52, 10-40 m, inside the body | light blue-grey, 0.60 |

311 particles at the steady rate. `LIGHT` (the particles' diffuse and ambient) 1.7.

The towers off the centre make a cloud uneven, so the same object would show the same silhouette everywhere; the adapter now gives each cloud a heading of its own (`cloud_heading`, from the thermal's place and birth, the same for every pilot). Particles are billboards, so the heading only turns where they are emitted.

**Offline preview.** To iterate without the simulator, a rough compositor of the billboards (perspective, back to front, a guess at X-Plane's light, box filtering for mipmaps) was used for shape only. It is not kept: the light in X-Plane decides. In it the new clouds read as cumulus with a flat grey base and lobed towers, against the old even white balls; they also came out greyer and a little busier, and were brightened once.

## In the simulator

KHOB, X-Plane 12.4.3 under Vulkan, noon, calm, a layer of X-Plane's cumulus (30% cover) at the height of ours for reference, the plugin's own clouds off (`xp_gliding/clouds_enabled` 0). CloudLab gained a kind that places the plugin's own cumulus as it ships (`make_cloud.py --plugin`, with `--rev` for an older one from git), driven by the plugin's rate and scale datarefs, and keeps every version it has loaded, so the cumulus of 0.7 and the new one stand side by side in one picture, in the same light. Each capture: an air start, both clouds placed and filled fast for 10 s of free flight, a second air start in the same place so the glider is level again (the clouds stay), paused, a screenshot ahead.

**Eight sub-emitters in one emitter crashed X-Plane** a few seconds after the first new cloud was placed: heap corruption (`0xc0000374` in ntdll), nothing in X-Plane's log. The old cloud alone in the same lab was fine, and the new one split into emitters of at most three sub-emitters (the most any earlier object had) has not crashed since, in some 15 placements and a sky of 196. So the generator writes one emitter per three layers, listed in the object, in the order they are drawn. Where exactly the limit is was not looked for.

One change at a time, each judged on a capture:

| Version | What changed | Seen |
| --- | --- | --- |
| cu5 | The first reshape, lightened after Juan Luis found the offline preview "un poco oscura" | Lobes and a flat base, but the base stood out like a separate plate, the cloud was narrower than the old one, and both ours were greyer than X-Plane's |
| cu6 | Body and edges wider, the base narrower and inside the body, `LIGHT` 1.2 → 1.35 | Greyer than the old one and with gaps: each lobe was darkened at its bottom, which is most of what is seen from below |
| cu7 | Lobes lighter (light 0.86-1.0, a slight belly), more opaque, more low lobes | As bright as the old one; a cumulus at 3.5 km |
| cu8 | Base puffs soft ovals instead of flat-bottomed domes, more of them; edge puffs closer in; wisps fainter | From 1.5 km below the base: a flat even base and lobes of several sizes rising in towers. From 650 m, 60 m under the base: an even grey belly with soft lumps. cu7's flat-bottomed base puffs had broken into horizontal stripes there |

Juan Luis watched these on the screen and took his own screenshots as they ran. On the side-by-side at 1.5 km (0.7 on the left, cu8 on the right) he still preferred 0.7's; on a softer base, "ahí un poco mejor"; then, more than once, too dark, lighter as he asked; and on the bases seen near their height, "qué mal se ven esas bases": a thin, flat, darker sheet sticking out sideways under the towers, like a shelf. On a row of cu8 (the cost test's grid, every cloud from one template, which is also why they looked repeated), the bases looked like stacked flat pancakes.

| Version | What changed | Seen |
| --- | --- | --- |
| cu9 | A bold step lighter: `LIGHT` 1.35 → 1.7, lobes 0.92-1.0, every tint white but the base's; base puffs fewer (40), more transparent (0.6), narrower than the body (0.52), wisps fainter | As light as 0.7's or lighter; no plate under the body from 120 m below the base nor from further below. Some small lobes on top stand a little apart. Juan Luis: "esta salió mejor pero la quiero más clara" |
| cu10 | Lighter again: `LIGHT` 2.1, lobes 0.95-1.0, the base near white | Lighter, but by less than the step: X-Plane seems to compress the brightest tones. Side by side with cu9, **Juan Luis preferred cu9** |

**Chosen: cu9** (Juan Luis, 2026-11-11), the version in the generator now.

**Cost.** 196 clouds in a grid 2.8 km apart, paused after filling, 30 s each, two rounds, in the order none, 0.7's, new:

| Clouds | Main thread (ms/s) | GPU estimate (ms) |
| --- | --- | --- |
| None | 315, 317 | 5.99, 5.64 |
| 0.7's | 366, 371 | 5.57, 5.44 |
| New | 382, 374 | 5.57, 5.60 |

The GPU estimate does not move; the main thread takes about 50-65 ms/s more with clouds, as in phase 2, and the new ones 3-16 ms/s more than the old, within the noise. Paused, so the frame period read nothing; graphics as the menu stood.

## His first flight with v9

2026-11-11, late evening, Juan Luis by hand, installed from this branch (20ce233), an aerotow over mountains, the plugin drawing the full sky. His words: "interesante, pero hay que seguir trabajando"; "igual tienen algo que las veo como más reales"; and, comparing with 0.7's, those looked like many cotton balls or cauliflower, these look more like cloud. So the direction holds.

What his screenshots show, my reading: the irregular outline, the towers and the lighter tone work, and the middle-sized clouds look good from afar. Left to do:

- Seen from below, a soft translucent disc sticks out past the body on one side of the big clouds: the base puffs, wider from below than the body.
- The outline is a chain of round bubbles of about one size, too crisp: the particles show as circles.
- From below in sunlight the belly is white and flat, with no grey.
- Young or dying clouds, a few tiny puffs, look like popcorn rather than small cumulus.

He showed a screenshot of an X-Plane 11 cloud add-on's page as a reference, for inspiration only: very white clouds with body from soft grey where lobes overlap, and edges that dissolve into transparency with no sprite showing. That points at the puff texture (softer, larger, an edge that fades out slowly) more than at the layout.

## Softer edges (v12)

Juan Luis chose to work on the edges first. Only the lobe texture changed (`cloud_cell`, `lobe`, `small`): an edge that fades out over the density's outer tail instead of a short ramp, lobes filling more of their cell, and the small bulges on each lobe's upper side fainter, since they were what drew the bubble chain. Layout, light and tints as v9.

| Version | Edge (threshold, ramp) | Small bulges (weight) | Seen |
| --- | --- | --- | --- |
| v11 | 0.04, 0.90 | 0.55 | Offline: no bubbles left, but the lobes lose their shape and the cloud goes towards fog. Not shown in X-Plane |
| v12 | 0.10, 0.60 | 0.68 | Offline and in X-Plane, from 1.8 km below the base next to v9: a soft outline with no chain of round bubbles, still a cumulus. **Juan Luis: "v12 mejor, vamos bien"**, from the offline preview of v9, v12 and v11 |

On the X-Plane capture (left v9, right v12, 1.8 km below the base), **Juan Luis: "ganó la de la derecha"**: v12. To watch: the lower part of the base should not turn to haze; its lower left already looks a little foggy there.

v12 installed from this branch and flown by Juan Luis the same night: "me gustan mucho más, pasémoslas a producción". **Chosen: v12**, for `main`.

## Left open

- **The clouds' width against zi**, not tried yet: in CloudLab first, by placing clouds at scale × zi / 2000; the adapter only once Juan Luis chooses.
- Not looked at with the new clouds: flying through one, dusk, wind, the far clouds at 15-35 km, a full sky drawn by the plugin itself (every cloud with its own heading and scale), and Juan Luis's own hand flight.
- The outline is still firmer than X-Plane's own cumulus, and some small lobes on top stand apart.
- The test pilot dropped twice when clouds were placed to fill fast, "no data from X-Plane for 1 s"; the captures then used a paused sim instead. Not looked into.

## X-Plane 11 cloud add-ons, as reference

2026-11-12. Juan Luis left seven X-Plane 11 cloud add-ons from artists and the community in a folder next to the repository, to study: CloudArt 3.3, *Clouds* (by alian2000), GoodMorningXP, Unique Clouds Variety Pack 1.5 (four sets), Vivid Sky 1.1, X-Pilot Realistic Clouds 1.2 and Y Clouds 4. Read for ideas only; nothing from them goes into the repository.

**What they are.** None is a plugin. Each replaces X-Plane 11's cloud textures (`Resources/bitmaps/world/clouds/cloud_puff0-5.png`, some also `smoke_puff`, `cloud_puffs` and the sky colours) and most add a FlyWithLua script that sets X-Plane 11's art controls once (`sim/private/controls/clouds/*`: `plot_radius`, `first_res_3d`, `overdraw_control`, `ambient_gain`, `diffuse_gain`, `light_curve_ratio` and `light_curve_power` for a lit top and a dark base, the cloud shadows; plus sun, atmosphere, water and shadow controls). GoodMorningXP and Unique Clouds are textures only. X-Plane 12 draws its clouds another way, so neither the textures nor those controls apply to it as they are (not checked in the simulator; not worth a side measurement).

**Their textures.** Every `cloud_puff` is an atlas of 4 x 4 cells, the layout of our `cumulus.png` (`TEX_CELLS_X 4`, `TEX_CELLS_Y 4`), at 512 to 4096 px a side, so 128 to 1024 px a cell; ours is 1024, 256 a cell. Y Clouds 4 reuses Vivid Sky's and CloudArt's files (same contents). Laid out on a blue sky:

- **A whole cloud per cell.** Each cell is a complete small cumulus, a cumulus fragment, a stratus band or cirrus, often photographic, with crisp cauliflower edges and 16 different shapes per atlas. Ours are parts that the layers build a cloud from: bases, lobes, small lobes, wisps.
- **Shading painted in.** Bright tops, a flat, greyer base, grey where lobes overlap; the art controls then add a lit top and dark base on top of that.
- **The ones closest to a fair-weather cumulus with a flat base**: X-Pilot 1.2's `cloud_puff3-5` and alian2000's `cloud_puff3-5` (their lower rows). Unique Clouds' sets range from soft blobs to cotton-wool heaps; CloudArt's cells are small clouds in a mostly empty cell.
- **Colour**: white with a faint blue in the grey, about (0.88, 0.90, 0.92) weighted by alpha; ours (0.90, 0.91, 0.94).
- **Cost**: GoodMorningXP warns that its 2K textures cost frames under a dense sky.

**Licences.** None is open. GoodMorningXP allows mixing it into other mods for non-commercial use with credit; Y Clouds says the rights stay with the original authors of what it gathers; the rest say nothing. This project is GPL-3.0-or-later, so their textures are a reference, like Alex Ferrer's code, never a source.

**Cell by cell.** Four of their best cells (X-Pilot 1.2's `cloud_puff3` cell 5 and `cloud_puff4` cell 14, alian2000's `cloud_puff5` cell 14, Unique Clouds set 4's `cloud_puff3` cell 9) next to four of ours (cells 0, 5, 12, 14), all at one size on a blue sky:

- Their soft lobe (Unique Clouds) has grey patches inside, as if its density varied; ours are evenly white from edge to edge. This is what X-Plane 12's own cumulus showed on 2026-11-07 (density that varies through the cloud).
- Their base oval (alian2000) darkens towards its bottom; ours is pale, with a lighter rim, nearly the reverse. Part of the white belly from below.
- X-Pilot's cumulus have cauliflower at several scales, small bubbles on the large ones, with a crisp outline. Our v12 edges are soft on purpose, so only the fine grain inside the lit part is the lesson, not the outline.
- X-Pilot's cells are whole cumulus with a flat base, one cloud per cell.

**For our cumulus**, to weigh with the rest of this note when the cloud looks come back, the first two most promising (cheap, generator only, and aimed at what was seen in flight):

1. Grey inside the lobes: vary the density, and so the shading, inside `lobe` and `small`, without changing the layers.
2. A base cell grey towards its bottom instead of pale with a light rim (painted grey, not a flat-bottomed layout: that one broke into stripes seen from below).
3. Fine detail inside the silhouette, on the lit side, keeping v12's soft outline.
4. Cells that read as a small cloud on their own, for the young and dying clouds (the popcorn above) or the far ones. The largest and least certain: close to the billboard weighed with ChatGPT's proposal, and switching kinds by distance without a visible jump is hard.

Also: more distinct shapes (our lobes are eight cells of one kind), and 512 px a cell only if a closer look shows the cells soft, with its cost measured.

## Round 2: grey inside and underneath (v13)

2026-11-12, a separate session again, looks only, on branch `claude/cloud-looks-2-234b04`. Aim: the white flat belly and the evenly white lobes left by v12, following the lessons of the XP11 add-ons above, without going grey overall (Juan Luis liked them "más claras").

**Offline preview.** A new rough compositor in the session's scratch space (not kept, like the first): billboards in perspective, back to front, one rough light, the same particles for every version, four views: a row at 3 km from the side, one cloud from 1.8 km below the base, the belly from 150 m under the base, and young clouds with a quarter of the particles.

All changes are in the texture only; layers, light, particle counts and v12's outline as before. The detail inside the cells draws from random streams of its own (`Detail`), so the shapes and outlines of the lobes are exactly v12's.

| Try | What changed | Seen offline |
| --- | --- | --- |
| a | Lobes: self-shadow between bulges 0.08 → 0.18, grey pockets of thicker cloud (slow noise, 0.16) | Grey all over: the drift to grey he does not want. Dropped |
| b | Self-shadow 0.10, pockets 0.14 and only in a lobe's lower and middle part (`SHADE`, `POCKETS`) | Grey patches inside, tops white |
| c | Base cell grey towards its bottom and its core (0.72 at the bottom, 0.96 at the top) instead of pale with a light rim (`BASE_GREY`) | A grey belly from below and a natural darker base from the side; but a grey streak now stuck out past the body from below: the halo seen in flight, made visible |
| d | Base ovals narrower in their cell (half width 0.88 → 0.72, `BASE_WIDTH`), bottom 0.75 | The streak mostly gone |
| e | Fine cauliflower grain in the lit upper part of the lobes (billow at 12 cells, 0.10) | Too coarse: dents under the belly from close by |
| f/g | Grain finer and fainter (24 cells, 0.07, `GRAIN`), on its own stream | Barely visible except near; the cell outline unchanged. v13 = g |
| v13 + grey low layer | My own idea: the `low` layer tinted (0.91, 0.92, 0.95) instead of white | The lower third of the cloud a little greyer from every side, towers white; the belly grey more even. Risk: greyer overall |

Not addressed: the popcorn of young and dying clouds. When the rate drops, particles die at random in every layer, so what is left is scattered puffs; changing that means changing how a cloud grows and dies, outside the looks.

**In X-Plane.** CloudLab (`make_cloud.py --plugin`) at KHOB, noon, calm, clear, the plugin's own clouds off, the three in a row 4.5-5 km ahead with one heading (cu31 v12 from git, cu32 v13, cu33 v13 with the grey low layer). From 900 m under the base the differences were small: X-Plane's light flattens the grey inside, all three a similar blue-grey. From the side, v13's base was greyer. Juan Luis looked in the sim himself and chose **the left one, v12**, and added: "en las tres esa capa horizontal no me gusta mucho".

The band: seen near the base's height, each cloud has a flat band under its body, sticking out sideways. It is the `base` layer (40 wide ovals emitted in a layer 30 m thick) and the `wisp` layer (16 horizontal fibres); edge on they add up to a sheet. v13's grey made it stand out more. The offline compositor barely shows it, so the choice was made in the sim, three new clouds 3.5 km ahead, the glider 60 m above their base:

| Lab | What | Particles | Seen |
| --- | --- | --- | --- |
| cu31 | v12 | 311 | The flat translucent band under the body |
| cu34 | v12 without `base` and `wisp` | 255 | No band; the bottom made by the low lobes, rounder |
| cu35 | v12 with a base of grey lobes (40 lobe cells, 240 m, tint 0.90, 30-70 m, narrower than the body) instead of ovals and wisps | 295 | A darker, flatter bottom, but still read as a horizontal band |

**Juan Luis: "la de al medio me gusta más, definitivamente no me gusta esa franja horizontal de las otras dos".** So **v14** = v12 without the base and wisp layers: v12's texture unchanged (the base and wisp cells stay in the atlas, unused), the emitter's height kept at 59 m, since the lowest low lobes reach about as far down as the base puffs did. Fewer particles (255 against 311), so no cost measured.

What this leaves: the base puffs were also the halo seen from below in his v9 flight (a translucent disc wider than the body), so that should be gone; to check in his flight. The white belly from below stays as in v12 (v13's grey inside did not show enough in X-Plane to win), and the popcorn of young and dying clouds is untouched.

**Less puffy (v15).** Juan Luis asked for variations of v14 "menos pomposas" without losing it. Three, next to v14 in the lab, 4 km ahead, 60 m above their base:

| Lab | What | Particles |
| --- | --- | --- |
| cu34 | v14 | 255 |
| cu36 | Smoother lobe texture: the small bulges on each lobe fainter (0.68 → 0.50), the puffy noise inside weaker (density 0.80 + 0.35 billow → 0.88 + 0.18, shading 0.10 → 0.05) | 255 |
| cu37 | v14's texture; no `edge` layer (50 small puffs of 120 m), the `top` 18 lobes of 220 m instead of 25 small ones of 160 m | 183 |
| cu38 | Both | 183 |

Juan Luis hesitated between the last two, leaning to cu37; my reading the same: the small puffs were what made the outline a puffy chain, and cu37 keeps the texture already flown, while the smoother texture leans towards v11's fog. **Chosen: cu37 as v15** (2026-11-12). Fewer particles, so no cost measured. Installed for his hand flight.

**His flights with v15.** 2026-11-12 evening, Juan Luis by hand over Santiago, first at 18:00 local, then at noon: "¿no son muy grandes? pareciera que estuviera nublado", then "quizás el problema es que son tan iguales que se confunden; cuando están juntas parecen una sola". His log at 18:00: nearest cloud scale 0.96-1.09, zi 2000 m, so each cloud was its usual size; neighbours close together merged into one white wall. Every cloud is one object with one tower layout, only turned by its heading.

**Clouds that merge.** In the lab, four clouds in a row 1.1 km apart, 4.5 km ahead, base 350 m above the glider, random headings, four rows:

| Row | What | Seen |
| --- | --- | --- |
| 1 | v15 x4 | Touching and merging into one band, as in his flight |
| 2 | v15 with the `low` layer narrower (0.78 → 0.65 of the half width), x4 | Sky between them; all four alike |
| 3 | v15 plus three other layouts of the same 170-183 particles: one tall central tower, two low wide towers, towers leaning to one side | Each cloud reads as its own; still close |
| 4 | The four layouts, all with the narrower `low` layer | Each its own, with sky between: the clearest |

Not chosen yet: shown to him at the end of the day ("última prueba por hoy"). Row 4 would mean several cloud objects and the adapter picking one per thermal, deterministically (the same for every pilot); the lift is unchanged, though a cloud narrower at its bottom than the engine's 500 m half width (used for its shade and ground points) is worth weighing.
