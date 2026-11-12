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

## Left open

- **The clouds' width against zi**, not tried yet: in CloudLab first, by placing clouds at scale × zi / 2000; the adapter only once Juan Luis chooses.
- Not looked at with the new clouds: flying through one, dusk, wind, the far clouds at 15-35 km, a full sky drawn by the plugin itself (every cloud with its own heading and scale), and Juan Luis's own hand flight.
- The outline is still firmer than X-Plane's own cumulus, and some small lobes on top stand apart.
- The test pilot dropped twice when clouds were placed to fill fast, "no data from X-Plane for 1 s"; the captures then used a paused sim instead. Not looked into.
