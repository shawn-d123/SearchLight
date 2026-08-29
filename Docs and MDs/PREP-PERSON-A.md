# PERSON A — prep before tomorrow

Searchlight, Daytona HackSprint, Sunday 30 August. Kick-off 10:30, submissions 17:00.

You own the frontend. Everything on screen is yours and you touch nothing else all day.

**Tonight is about removing setup risk, not building the app.** The application gets built at the event. What you want by 10:30 tomorrow is a machine where the hard integrations already work, so your first hour is spent on the product instead of on npm and camera matrices.

Budget: about two hours. If you only have one, do sections 1 to 3.

---

## What you're building tomorrow, in one paragraph

A missing hiker. One screen, roughly 70% map and 30% side rail. The map shows Yosemite terrain with trails, a marker at the last known point, and a plain white circle around it that represents how rescue teams draw search areas today. When the simulation runs, thousands of animated paths spread out across the terrain and accumulate into a probability surface that hugs the valleys, taking maybe a fifth of the circle's area. Then a witness report lands, most of the surface goes dark, and the circle stays exactly the same size. That contrast is the entire pitch.

---

## 1. Project setup

Next.js with Tailwind, then:

```bash
npm i deck.gl @deck.gl/geo-layers @deck.gl/extensions maplibre-gl react-map-gl
```

One page, dark background, nothing styled beyond that. Styling is tomorrow's job and there's a visual direction to follow (section 7).

---

## 2. The camera integration — do this first, it's the one that bites

Getting deck.gl and MapLibre to share a camera is the single most likely thing to eat an hour, because two rendering systems both think they own the view. Symptoms when it's wrong: layers subtly offset from the basemap, or overlays that don't move correctly when you pan.

Reference: https://deck.gl/docs/get-started/using-with-map

Get a deck.gl ScatterplotLayer sitting correctly over a MapLibre basemap and panning in lockstep. That's the whole test. Once it works you never think about it again.

**Then lock the camera:**

```js
map.dragRotate.disable();
map.touchZoomRotate.disableRotation();
```

Pan and zoom stay enabled. Rotation does not, because a wrong bearing can hide the probability field behind a ridge and there'll be no time to recover on stage.

---

## 3. Terrain

Terrain-RGB tiles from AWS, free, no key:

```
https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png
```

Encoding is `terrarium`, not `mapbox`. Getting that wrong produces terrain that looks like noise.

Add it as a MapLibre raster-dem source with terrain enabled.

**Two things that matter:**

Set pitch and exaggeration as named constants at the top of the file. Build everything at **pitch 0**, flat, and raise the camera only once the rest works. If raising the camera is a rewrite rather than changing one number, the architecture is wrong. This is your insurance policy: 2D is a perfectly good demo, 3D is an upgrade.

Cache the tiles locally for the Yosemite area. Venue wifi at 16:50 is not something to rely on, and a demo that can't load terrain is not a demo.

Exaggeration will end up around 3x for drama. Past roughly 4x it stops looking like landscape and starts looking like a video game.

---

## 4. Animated paths

deck.gl `TripsLayer`: https://deck.gl/docs/api-reference/geo-layers/trips-layer

Generate a few hundred fake paths and animate them. What you're checking is performance, not looks.

**Verify 12,000 paths at realistic point counts (about 60 points each).** TripsLayer runs on the GPU so it should hold, but confirm rather than assume. If it stutters, the fix is rendering a visible subset of about 2,000 while the full set still exists in the data. The visual is identical and nobody can count them.

Don't drape the paths onto the terrain. Let them float 20 to 50 metres above ground. Looks better, and avoids z-fighting where lines flicker in and out of hillsides.

---

## 5. The draping test — five minutes, saves an hour tomorrow

This is the subtle one. **deck.gl layers drawn over MapLibre terrain do not automatically follow the ground.** They render in their own pass and float flat, which looks obviously wrong on steep slopes.

Draw one line across a steep slope and look at it from a pitched camera. If it clings to the terrain, you're fine. If it floats, you need one of:

1. **The reliable route:** for the probability surface, don't use a deck.gl layer at all. Paint the grid to an HTML canvas and add it as a **MapLibre image source**, because MapLibre drapes its own raster layers onto terrain natively.
2. `TerrainExtension` from `@deck.gl/extensions`, which drapes deck layers onto the terrain mesh. Works, but it's another thing to debug under time pressure.

Know which one you're using before tomorrow.

---

## 6. Read the contract

`CONTRACT.md` will be in the repo tonight. Two shapes matter to you.

**Trajectory batches** arrive from the workers. One batch is one hypothesis containing many runs:

```json
{
  "hypothesis_id": "h_00184",
  "family": "route_travelling",
  "weight": 0.22,
  "generated": true,
  "runs": [
    { "run_index": 0, "points": [[lat, lon, t], ...], "endpoint": [lat, lon], "status": "ok" }
  ]
}
```

**Field updates** arrive repeatedly as the probability surface accumulates:

```json
{
  "bounds": {"north": ..., "south": ..., "east": ..., "west": ...},
  "resolution": 256,
  "grid": "<base64 float32, 256*256, row-major, normalised 0..1>",
  "progress": 0.62,
  "zones": [{"name": "Ridge north", "pct": 31.2, "centroid": [lat, lon]}],
  "n_total": 12000,
  "n_consistent": 12000,
  "ring_radius_m": 5800,
  "field_area_pct": 21
}
```

Coordinates are always `[lat, lon]`, WGS84, decimal degrees. Grids are row-major with row 0 at the **north** edge. Times are seconds since the last known point, not wall clock.

**The field is a stream, not a single message.** It arrives partial and sharpens. Interpolate between the previous grid and the new one over about 800ms rather than swapping instantly, so the surface appears to grow rather than flicker between states.

Mock files matching all of this will be in `mocks/` tonight. Build the entire frontend against those with a `DATA_SOURCE` flag switching between `'mock'` and `'live'`. If that flag exists, connecting to the real backend at 14:30 is a config change instead of a debugging session.

---

## 7. Visual direction — read this, don't design tonight

**Reference world: a topographic survey sheet.** USGS quad sheets, OS Explorer maps, avalanche bulletins. Not a sci-fi command centre. The default instinct is dark navy plus electric cyan, and it reads as generated.

Warm dark rather than blue dark. Charcoal with an olive cast, linework in bone rather than pure white.

**The probability field is the only saturated thing on screen.** Terrain muted, trails bone, ring a thin dashed bone line, panels greyscale. Field ramp is a single hue with an opacity ramp, transparent through amber to hot coral. Not a rainbow, not viridis, because multi-hue ramps fight the hillshade underneath and turn to mud on 3D terrain.

Amber for evidence. Nothing else coloured, ever.

Type: IBM Plex Mono for data and labels, Archivo for headings. Avoid Inter.

Contour lines rather than heavy hillshade, every fifth line brighter. Trails with a dark casing under a bright line so they hold up over busy ground.

**Cut on sight:** glassmorphism, frosted panels, neon glow, gradient text, border radius above about 4px with drop shadows, emoji as icons.

**Keep the rail quiet.** Seven numbers total, and `field_area_pct` should be the largest text in it by some margin, because it's the whole argument in one number.

---

## 8. Tomorrow's shape, so tonight makes sense

| Time | You |
|---|---|
| 10:30 | Contract lock, 15 min, all three |
| 10:45 | Terrain and trails rendering, flat |
| 11:30 | **Ring, marker, static frame done** |
| 12:30 | TripsLayer animating from mocks |
| 13:30 | Field layer with incremental updates |
| 14:30 | **Hard integration, flip to live** |
| 15:00 | State machine, camera keys |
| 16:00 | Polish, contrast, projector test |
| 16:20 | First clean rehearsal |

**The static frame by 11:30 is the milestone that matters.** Terrain, trails, marker, white ring, flat, no animation. If that's on screen you have a skeleton and everything after is additive. Chase the 3D camera first and you can be four hours in with nothing to show.

You will be asked to help with the backend around 14:00 when it looks scarier than the frontend. Say no. A half-finished frontend with a perfect backend loses to the reverse.

---

## Checklist

- [ ] Next.js + Tailwind + deck.gl + MapLibre installed and running
- [ ] deck.gl layer sitting correctly over a MapLibre basemap, panning in lockstep
- [ ] Terrain rendering, terrarium encoding, tiles cached locally
- [ ] Rotation disabled, pitch and exaggeration as named constants, currently 0
- [ ] TripsLayer animating fake paths, 12,000 verified for frame rate
- [ ] Draping tested on a steep slope, decision made
- [ ] `CONTRACT.md` read
- [ ] Laptop charger packed. On battery the GPU throttles and the frame rate halves

Bring the charger. Genuinely.
