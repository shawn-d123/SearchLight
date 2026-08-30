# PERSON A — frontend

**Read `CONTRACT.md` first.** Everything on screen is yours. You touch nothing else all day.

---

## The thing you are building

A hiker is missing in the Santa Catalina Mountains north of Tucson. One screen, roughly 70% map, 30% side rail. The layout never changes, only the state does.

The map shows the Catalinas with trails, a marker at the last known point, and a plain dashed circle 9.55 km in radius representing how rescue teams draw search areas today. When the simulation runs, thousands of paths spread across the terrain and accumulate into a probability surface that hugs the ridges and drainages, taking a fraction of the circle's area. Then a witness report lands, most of the surface goes dark, and the circle stays exactly the same size.

**That contrast is the entire pitch.** The circle is the least interesting object on screen and it carries the argument.

---

## The landing screen — yours, and it is cheap

**`landing` state. Purely decorative — no map, no terrain, no live data.** Dark screen, a searchlight silhouette on the left casting a beam to the right, and a panel that intercepts it with a subtle illuminated edge where the light lands. Title, one line of subtitle, one button: **REPORT A MISSING PERSON**.

**A searchlight, not a lighthouse.** Same animation, same collision effect. A lighthouse warns ships away from hazards; this product finds people in them. Costs nothing to get right.

Four constraints so it does not read as a different application:

- **One moving element.** The beam. Nothing else animates
- **Warm light, not white** — the same amber family as the probability field later
- **CSS or SVG, not canvas.** No reason to pay for a render loop here
- **Test the collision glow on a projector.** Soft glows that look right on a laptop often disappear entirely when projected, so push it harder than feels right

**The `intake` states are Person C's**, not yours. They need no terrain and no deck.gl, so they do not compete for your time. Coordinate on shared panel styling — C uses the same corner registration ticks and type so it does not look like a different application.

Build `landing` **last**, after 15:00, once the map states work. It is thirty minutes and it is the first thing to cut.

---

## Build order — do not deviate

### 1. Static frame — target 11:30

Terrain, trails, last known point marker, dashed ring. **Flat, pitch 0. No animation.**

If that frame is on screen at 11:30 you have a skeleton and everything after is additive. Chase the 3D camera first and you can be four hours in with nothing to show.

Data is already in `data/`: terrain arrays, `bbox.json`, and 14,750 display trail ways at 3.4 MB. The full 444k-edge network exists for the workers but is not for rendering.

### 2. Paths animating from mocks — 12:30

`mocks/trajectories.json` is in the repo, validated against the contract. TripsLayer. No backend involved.

**Stress-test at full scale first.** The committed mocks ship 2,400 runs. Regenerate before you judge frame rate:

```bash
python prep/make_mocks.py --runs-per-batch 60
```

If 12,000 stutters, render a visible subset of about 2,000 while the full set stays in the data. The visual is identical and nobody can count them.

### 3. Field layer — 13:30

`mocks/field.json` and `mocks/field_partial.json`. Decode the base64 float32 256×256 grid, paint it to a canvas, add it as a **MapLibre canvas source**.

Canvas rather than image source, because the field arrives as a stream and repaints in place. Both drape onto terrain natively; only canvas updates without re-adding the layer.

**The field accumulates, it does not appear.** Updates arrive roughly every second with a `progress` value. Interpolate between the previous grid and the new one over about 800ms so the surface grows rather than flickering. `field_partial.json` is what a mid-run update looks like.

### 4. Flip to live — 14:30

One flag. If you built it right this is a config change.

### 5. State machine, camera, polish — 15:00 on

---

## Layers, back to front

| Layer | What | Note |
|---|---|---|
| Basemap | MapLibre dark | CARTO dark is the fast option |
| Terrain | Terrain-RGB, **terrarium encoding** | Cache tiles locally. Venue wifi at 16:50 is not a plan |
| Contours | Dim bone lines, every fifth brighter | Reads as a survey sheet, keeps trails legible |
| Trails | deck.gl `PathLayer` | Dark casing under a bright line so they hold up over busy ground |
| Ring | Circle, thin dashed bone | Annotated `ISRID RING · 95th PCTL · 9.55 km` with a leader line |
| Field | **MapLibre canvas source** | See above |
| Paths | `TripsLayer` | Float 20–50 m above ground, do not drape |
| Markers | `ScatterplotLayer` | IPP, witness sighting |

---

## Camera

Fixed pitch 55–60°, vertical exaggeration around 3×. Past roughly 4× it stops looking like landscape and starts looking like a video game.

```js
map.dragRotate.disable();
map.touchZoomRotate.disableRotation();
```

Pan and zoom **enabled**. Rotation **disabled** — a wrong bearing hides the field behind a ridge and there is no time to recover on stage.

Two keys:
- **Reset** — snap back to the scripted camera for the current state
- **Flatten** — drop pitch to ~15° so hidden ground becomes visible, toggle back on second press

Camera positions as named constants, one per state, 1200ms transitions.

**Build flat, raise last.** If raising the camera is a rewrite rather than changing one number, the architecture is wrong. 2D is not a failure state — a flat map with trails, a ring and a field that follows the drainages makes every argument the demo needs.

---

## Visual direction

**Reference world: a topographic survey sheet.** USGS quad sheets, avalanche bulletins, incident command boards. Not a sci-fi command centre. The default instinct is dark navy plus electric cyan and it reads as generated.

Warm dark, not blue dark. Charcoal with an olive cast, linework in bone rather than pure white.

**The probability field is the only saturated thing on screen.** Terrain muted, trails bone, ring dashed bone, panels greyscale. Field ramp is a single hue with an opacity ramp: transparent → amber → hot coral. Not a rainbow, not viridis — multi-hue ramps fight the terrain underneath and turn to mud.

Amber for evidence. Nothing else coloured, ever.

Type: IBM Plex Mono for data and labels, Archivo for headings. Avoid Inter.

Chart furniture: corner registration ticks on panels instead of full borders, a scale bar, a north arrow.

**Cut on sight:** glassmorphism, frosted panels, neon glow, gradient text, border radius above ~4px with drop shadows, emoji as icons.

**Motion vocabulary, complete:** paths are the only fast-moving thing, state transitions 200–400ms, camera 1200ms, field interpolation 800ms. Panels do not animate in. Numbers do not count up. Restraint is what makes the simulation explosion land.

---

## Keep the rail quiet

Seven numbers. That is all.

- Subject name and last contact
- **Sandboxes active** — the only thing on screen proving real machines are working
- Simulations run
- Consistent after evidence
- Top zone percentage
- **Field area as a percentage of the ring** — the largest text in the rail by some margin. This is the whole argument in one number

**Cut:** hypothesis family bars, weather and conditions, zone list beyond two rows, coordinate readout if the screen feels busy.

**One exception, during the SIMULATING state only.** `sim_started` carries up to 6 generated hypotheses with plain-English `description` strings. Cycle three or four of them in the rail while the paths spread — one line each, mono, muted. They are site-specific ("followed the drainage south-east from the junction") rather than textbook categories, and they are what makes the model's reasoning legible. They disappear when the field settles. This is the only text on screen that changes for its own sake, and it earns it.

Some hypotheses carry a `source` object. Where `source.kind` is `"local"`, show `source.label` as a smaller muted line beneath the description — *"Pima County SAR incident report, 2019"*. That attribution is the visible payoff of the research pass, and it fits a project whose whole identity is evidence over intuition. Handle `source` being absent; most hypotheses will not have one.

Everything else goes in the pitch, where it is said once and lands better than a permanent label nobody reads.

---

## Timeline

| Time | You |
|---|---|
| 10:30 | Contract lock, 15 min, all three |
| 10:45 | Terrain and trails rendering, flat |
| **11:30** | **Ring, marker — static frame done** |
| 12:30 | TripsLayer animating mocks at full scale |
| 13:30 | Field layer with streamed updates |
| 14:30 | **Flip `DATA_SOURCE` to live** |
| 15:00 | State machine, camera keys |
| 16:00 | Polish, contrast, projector test |
| 16:20 | First clean rehearsal |

**You will be asked to help with the backend around 14:00**, when it looks scarier than the frontend. Say no. A half-finished frontend with a perfect backend loses to the reverse.

**Cut order if behind:** camera choreography → 3D terrain (fall back to flat) → zone detail panels.

---

## Traps

**deck.gl over MapLibre terrain does not automatically drape.** Layers render in their own pass and float flat, obviously wrong on steep slopes. The field uses a MapLibre canvas source for exactly this reason. If you add any other ground-hugging layer, either use a MapLibre layer or `TerrainExtension` from `@deck.gl/extensions`.

**Perspective compression.** At 55° the far side of the map squashes to nothing. Check the bright zone is visible from the default camera in every state. If it is not, move the camera rather than flattening the terrain.

**Projectors** crush dark greys to black and wash out thin strokes. Push contrast well past what looks right on your laptop and test on an external display at venue resolution.

**Battery throttles the GPU** and halves the frame rate. Plugged in, always.
