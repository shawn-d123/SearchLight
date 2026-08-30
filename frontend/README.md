# Searchlight — frontend

Person A owns this directory. One screen with states; the layout never changes,
only the state does.

```bash
npm install
npm run dev          # http://localhost:3000
```

Then press **space** repeatedly. That is the whole demo.

## Keys

The keyboard is the real interface during the pitch — the presenter never
touches the mouse.

| Key | |
|---|---|
| `Space` / `→` | Advance state |
| `←` | Back |
| `1`–`7` | Jump straight to a state (recovery, not choreography) |
| `R` | Reset camera to the current state's framing |
| `F` | Drop pitch to 15° to reveal hidden ground, press again to restore |
| `T` | Replay the intake call |
| `?` | Key list |

Panning and zooming are enabled; **rotation is disabled**, because a wrong
bearing hides the bright zone behind a ridge and there is no recovering from
that on stage. Pan exists for one situation: a judge asks to see somewhere
specific, and the fact it responds live is itself evidence the map is not a
video. Press `R` before continuing.

## The states

`landing → intake → briefing → simulating → field_ready → evidence → validation`

`landing` and `intake` are full-bleed and have no map. The map component stays
mounted underneath them the whole time — remounting MapLibre would re-download
tiles, rebuild the terrain mesh and re-sample elevation on every rehearsal.

## Architecture

```
lib/contract.ts      CONTRACT.md as types. The only place the wire shape is written down
lib/adapt.ts         two payload spellings -> one view model. READ THE HEADER
lib/source.ts        Source interface + emitter + cancellable timeline
lib/mockSource.ts    replays mocks/ as CONTRACT §9 envelopes
lib/wsSource.ts      the live orchestrator, same envelopes
lib/useSearchlight.ts the single reducer between wire and screen
lib/field.ts         decode -> paint -> drape -> interpolate over 800 ms
lib/mapStyle.ts      self-contained style. No CDN, no glyphs
lib/mapLayers.ts     ring, IPP, witness — MapLibre layers, so they drape
lib/elevation.ts     terrain height sampler for deck.gl geometry
lib/camera.ts        one scripted camera per state
lib/state.ts         state machine + key map
components/MapCanvas MapLibre owns the camera; deck.gl rides as a control
components/Panel     corner registration ticks. The shared primitive
```

**The live orchestrator and the mocks emit the same envelopes.** Nothing above
`source` knows which one it is talking to, which is what makes 14:30 a config
flip rather than a debugging session:

```bash
NEXT_PUBLIC_DATA_SOURCE=live NEXT_PUBLIC_WS_URL=ws://localhost:8000/ws npm run dev
```

`lib/adapt.ts` reads the CONTRACT spelling first and the mock spelling second,
so when the orchestrator ships the contract shape it wins outright and nothing
needs deleting.

## Scripts

```bash
npm run verify        # drives all 7 states in real Chrome, measures fps, screenshots
npm run cache:tiles   # terrain tiles, offline
npm run mocks         # sim_started.json + validation_result.json
npm run contours      # contours.geojson from data/elevation.npy
```

`npm run verify` needs the dev server running. It writes `verification/`. **Run
it on the presenting laptop at venue resolution before trusting the frame
rate** — and plug in, because on battery the GPU throttles and it halves.

## Things that will bite you

Read `DEPENDENCIES.md` before changing a version. Short list:

- **`maplibre-gl` is pinned to 5.x.** On 6.x, `MapboxOverlay` throws on every
  frame and the map renders black.
- **`TERRAIN_MAX_ZOOM` must not exceed what is on disk.** Too high and MapLibre
  404s past the cache and the terrain goes flat *silently*.
- **The field is a MapLibre raster source, not a deck.gl layer.** deck.gl does
  not drape onto terrain; it floats flat across ridges.
- **…and specifically an `image` source, NOT a `canvas` source.** Canvas is the
  obvious choice for a surface that repaints in place and it works perfectly at
  pitch 0 — but at pitch 57 over terrain it tears into hard-edged polygons that
  look like a broken shader. Byte-identical pixels in an image source drape
  cleanly. See the header of `lib/field.ts`.
- **deck.gl draws at z = 0.** Anything deck-side must be lifted through
  `lib/elevation.ts` or it sits at sea level under 2,154 m of relief.
- **Nothing may repaint the map continuously.** The elevation sampler is built
  off `sourcedata`, not `idle`, because any always-animating source means the
  map never goes idle and the sampler is silently never built — leaving every
  deck.gl layer at sea level. This is why the field animates via
  `raster-opacity` rather than a per-frame texture upload.

## Known gaps

- **`sim_started` and `validation_result` are generated locally** by
  `scripts/make-frontend-mocks.py`, because `mocks/` does not carry them yet.
  The hypothesis prose is derived from the committed terrain arrays and every
  figure in it is measured. **No citation is invented** — `source.kind` is
  `"terrain"` with no label, because the Parallel research pass never ran. The
  rail already renders the `"local"` attribution line for when it does.
- `validation_result.our_score` is `null` until Person C's validation run.
  It renders as "pending" rather than a rehearsed number.
- **`public/tiles` is now 105 MB** (1,060 tiles) rather than the 21 MB / 189
  tiles the repo shipped: z8–13 over the demo box, plus z8–11 across a much
  wider box so panning at pitch cannot run off the edge of the DEM. That second
  pass is insurance, not a requirement — drop it back to ~73 MB if repo size
  matters more than pan headroom. The root `.gitignore` is C's and currently
  commits this directory on purpose.
