/**
 * SEARCHLIGHT — frontend configuration.
 *
 * Everything the demo might need to change under time pressure lives here as a
 * named constant. In particular PITCH and TERRAIN_EXAGGERATION: the whole point
 * is that going from a flat 2D map to the 3D presentation view is changing a
 * number in this file, never a rewrite.
 *
 * Geographic truth comes from data/bbox.json via lib/bbox.json, so this file
 * cannot drift from the terrain arrays the workers use. Do not retype bounds.
 */

import bbox from "./bbox.json";

// ---------------------------------------------------------------------------
// Place — Santa Catalina Mountains, Arizona
// ---------------------------------------------------------------------------

/**
 * The spec assumed Yosemite. The free MapScore subset contains no Yosemite
 * cases — 131 Arizona cases only. Moved to the Santa Catalinas, the densest
 * mountainous cluster: Mount Lemmon at 2,791 m over a ~700 m valley floor is
 * ~2,100 m of relief, so terrain genuinely drives the field.
 *
 * In the pitch, say "the Santa Catalina Mountains".
 */
export const REGION = bbox.region;

/** N 32.576089, S 32.197678, E -110.587766, W -111.069734. 45.3 x 42.1 km. */
export const BOUNDS = {
  north: bbox.north,
  south: bbox.south,
  east: bbox.east,
  west: bbox.west,
} as const;

export const CENTRE: [number, number] = bbox.centre as [number, number];

/**
 * Wider box the terrain tiles are cached for. Deliberately larger than BOUNDS
 * so panning during a judge's question does not hit an empty map, and because
 * terrain needs neighbouring tiles to compute slope at the edges.
 * Mirrors DEFAULTS in scripts/cache-tiles.mjs — keep the two in step.
 *
 * scripts/cache-tiles.mjs also caches a second, much wider box at z8-11 (see
 * HORIZON there) so panning at pitch cannot run off the edge of the DEM.
 */
export const CACHE_BOUNDS = {
  north: 32.67,
  south: 32.11,
  east: -110.49,
  west: -111.17,
} as const;

/**
 * Fallback only — the real values arrive in case_loaded.
 * The demo incident (SL-2084, Marshall Gulch) is FICTIONAL and exists to drive
 * the narrative. The six historical cases in data/bbox.json are real and are
 * what validation scores against. Do not conflate them on stage.
 */
export const FALLBACK_IPP: [number, number] = [32.4102, -110.7314];
export const FALLBACK_RING_RADIUS_M = 9545.9;

// ---------------------------------------------------------------------------
// Camera
// ---------------------------------------------------------------------------

/** Build everything at 0. PITCH_PRESENTING is the 2.5D view, CONTRACT §13. */
export const PITCH = 0;
export const PITCH_PRESENTING = 57;

/** "Show me the hidden ground" pitch, toggled by one key during the demo. */
export const PITCH_FLATTENED = 15;

/** Rotation is disabled outright — a wrong bearing hides the bright zone. */
export const BEARING = 0;

/** Past ~4x terrain stops reading as landscape and starts reading as a game.
 *  Say "vertical exaggeration 3x" once in the pitch. Nobody objects to a
 *  stated exaggeration; they object to an unstated one. */
export const TERRAIN_EXAGGERATION = 3;

export const INITIAL_ZOOM = 10.4;
export const MAX_PITCH = 75;

/** Motion vocabulary, in ms. That is the entire list. */
export const STATE_TRANSITION_MS = 300;
export const CAMERA_MOVE_MS = 1200;
export const FIELD_INTERPOLATE_MS = 800;

// ---------------------------------------------------------------------------
// Terrain
// ---------------------------------------------------------------------------

/** Encoding is `terrarium`, NOT `mapbox` — wrong here produces terrain that
 *  looks like noise rather than landscape. */
export const TERRAIN_ENCODING = "terrarium" as const;

export const TERRAIN_SOURCE: "local" | "remote" =
  process.env.NEXT_PUBLIC_TERRAIN_SOURCE === "remote" ? "remote" : "local";

/** Default to the locally cached tiles. Venue wifi at 16:50 is not a plan. */
export const TERRAIN_TILE_URL =
  TERRAIN_SOURCE === "local"
    ? "/tiles/terrarium/{z}/{x}/{y}.png"
    : "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png";

export const TERRAIN_MIN_ZOOM = 8;

/**
 * MUST NOT exceed what is actually on disk. Set this higher than the cache and
 * MapLibre 404s past it and the terrain goes flat SILENTLY — no error, nothing
 * to chase, and the whole visual argument quietly stops working.
 * Overzooming past the cache is fine: terrain is smooth, the interpolation is
 * invisible. Re-run `npm run cache:tiles` before raising it.
 */
export const TERRAIN_MAX_ZOOM = TERRAIN_SOURCE === "local" ? 13 : 15;

export const TERRAIN_TILE_SIZE = 256;

// ---------------------------------------------------------------------------
// Data source — the flag that makes 14:30 a config change, not a debug session
// ---------------------------------------------------------------------------

export type DataSource = "mock" | "live";

export const DATA_SOURCE: DataSource =
  process.env.NEXT_PUBLIC_DATA_SOURCE === "live" ? "live" : "mock";

export const WS_URL = process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/ws";

export const MOCKS = {
  case: "/mocks/case.json",
  trajectories: "/mocks/trajectories.json",
  /**
   * 12,000 runs at 60 points each, for the frame-rate check. Gitignored —
   * regenerate with `python prep/make_mocks.py --stress`. The loader falls back
   * to `trajectories` when it is absent, so a clean clone still runs.
   */
  trajectories12k: "/mocks/trajectories_12k.json",
  field: "/mocks/field.json",
  fieldPartial: "/mocks/field_partial.json",
  fieldCollapsed: "/mocks/field_collapsed.json",
  fleetStatus: "/mocks/fleet_status.json",
  transcript: "/mocks/transcript.txt",
  extraction: "/mocks/extraction.json",
  /** Generated by scripts/make-frontend-mocks.py — see that file's header. */
  simStarted: "/mocks/sim_started.json",
  validation: "/mocks/validation_result.json",
} as const;

export const TRAILS_URL = "/data/trails.geojson";
export const WATER_URL = "/data/water.geojson";
/** Generated by scripts/make-contours.py from data/elevation.npy at 100 m. */
export const CONTOURS_URL = "/data/contours.geojson";

// ---------------------------------------------------------------------------
// Simulation shape
// ---------------------------------------------------------------------------

/** Live is 200 sandboxes x 60 seeds. The committed mocks ship 200 x 12. */
export const N_SIMULATIONS = 12000;

/**
 * How many paths are actually DRAWN. The full set still exists in the data, so
 * every count in the rail stays honest — this caps the render only.
 *
 * Measured on this machine, counting real scene frames (not requestAnimationFrame,
 * which reports the display refresh rate whether or not anything was drawn and
 * made 12,000 paths look like a comfortable 60):
 *
 *     12,000 paths -> 22 fps
 *      8,000 paths -> 23 fps
 *        400 paths -> 22 fps
 *     12,000 paths, trails layer off -> 23 fps
 *
 * So the paths are NOT the bottleneck and neither are the trails. The cost is
 * the 3x-exaggerated terrain mesh being re-rendered at pitch 57 every time the
 * deck overlay asks for a repaint, and it does not move whatever we draw on top
 * of it. Dropping the path count therefore buys nothing, so we draw all of them.
 *
 * If ~22 fps is not enough on the presenting laptop, the lever that actually
 * moves is the camera: PITCH_PRESENTING down, or TERRAIN_EXAGGERATION down, or
 * flat (the brief's own fallback — "2D is not a failure state"). Re-measure with
 * `npm run verify` there before deciding.
 */
export const N_PATHS_RENDERED = 12000;

/**
 * Frame rate cap for everything this app drives itself — the path clock and the
 * field cross-fade.
 *
 * Deliberately capped rather than left to run free. 12,000 paths hold 60 fps on
 * the development machine, but the presenting laptop is a different GPU, on a
 * projector, possibly on battery (which halves it). A locked 30 is steadier to
 * watch than a rate that swings between 45 and 60, it halves the GPU load, and
 * it removes the risk of the demo looking worse on the day than in rehearsal.
 *
 * This does not throttle MapLibre's own pan/zoom rendering, only our loops.
 */
export const TARGET_FPS = 30;
export const FRAME_MS = 1000 / TARGET_FPS;

/** Paths float above ground. Draping them causes z-fighting on hillsides. */
export const PATH_ALTITUDE_M = 35;

// ---------------------------------------------------------------------------
// Evidence
// ---------------------------------------------------------------------------

/**
 * The witness report, sent to the orchestrator when the demo enters `evidence`.
 * The orchestrator does not invent one — it filters against whatever it is
 * given — so the values live here, on the frontend that triggers the beat.
 *
 * Location and time are the narrative: a red jacket seen in the eastern
 * drainage at ninety minutes. Only the UNCERTAINTY around them is tuned here,
 * and it is tuned against real trajectories — `prep/tune_evidence.py` runs the
 * pipeline once and sweeps these offline.
 *
 * WHY reliability IS 0.94 AND NOT 1.0.
 * At 1.0 an inconsistent run is discarded outright. Against the mocks that gave
 * a good collapse, but against real terrain-aware simulations it is brutally
 * selective — one live run went from 6.5% of the ring to 0.5%, which is
 * numerically spectacular and visually a handful of pixels. The collapse has to
 * be something a judge can SEE shrink, not something that vanishes.
 *
 * Below 1.0 the model keeps inconsistent runs at reduced weight instead, so the
 * surface DIMS where the witness might be wrong rather than going black. It is
 * the honest knob, not a fudge: real witness reports often are wrong, and the
 * project's own list of stated weaknesses says so. It also stabilises the beat,
 * which matters because the figure swings between runs — the hypotheses are
 * regenerated every time, and two live runs measured 0.5% and 2.2% at identical
 * settings.
 *
 * Measured on a real 12,000-run pipeline (prep/tune_evidence.py), radius 3,250 m:
 *
 *     reliability 1.00 -> 2.2%   too sharp on a selective run
 *     reliability 0.97 -> 2.7%
 *     reliability 0.94 -> 3.2%   <- chosen; ~2x shrink from 6.5%, still visible
 *     reliability 0.90 -> 4.0%
 *     reliability 0.85 -> 4.8%   collapse stops reading as a collapse
 *
 * Widening radius_m instead was rejected: at 5,000 m nearly half the runs
 * survive and the field does not shrink at all.
 *
 * DO NOT REHEARSE A NUMBER FOR THIS. Say "a fraction of the ring".
 */
export const DEMO_EVIDENCE = {
  lat: 32.364754,
  lon: -110.736908,
  t: 5400,
  // The report is aimed at the field's densest zone (see buildEvidence in
  // lib/useSearchlight.ts), which makes radius far more sensitive than it was
  // against a fixed coordinate. Measured live, aimed at the top zone:
  //
  //     3,250 m / 0.94  ->  5.7% collapses to 0.8%
  //     5,000 m / 0.90  ->  7.5% collapses to 7.1%
  //     3,800 m / 0.94  ->  6.9% collapses to 5.2%  (8,669 of 12,000 survive)
  //
  // DO NOT TUNE THIS FURTHER ON SINGLE MEASUREMENTS. The collapsed figure has
  // been observed at 0.5, 0.8, 1.8, 2.2 and 5.2 percent across runs — the
  // hypotheses are model-generated fresh every time, so the run-to-run spread
  // is WIDER than the effect of these parameters. Anything tuned to one run is
  // fitted to noise. What these values buy is the absence of the two failure
  // modes: a field that vanishes, and a filter that discards everything.
  //
  // Area scales with r^2, so radius is by far the stronger term — reliability
  // only softens the edge. A vaguer sighting is also the realistic one: a
  // member of the public pointing at a hillside, not a GPS fix.
  radius_m: 3800,
  tolerance_s: 1800,
  reliability: 0.94,
  description: "Reported sighting - red jacket, eastern drainage",
} as const;

// ---------------------------------------------------------------------------
// Intake pacing
// ---------------------------------------------------------------------------

/**
 * The whole pitch is 90 seconds, so intake gets about eight of them. Real
 * speech-to-text emits in bursts rather than one word at a time, so the
 * transcript streams in small word groups: it covers the script quickly AND
 * looks more like live recognition than a typewriter effect did.
 *
 * scripts/mock-ws-server.mjs mirrors these numbers — it cannot import TS.
 */
export const TRANSCRIPT_WORDS_PER_TICK = 2;
export const TRANSCRIPT_TICK_MS = 150;

/** Wall-clock seconds for the path animation to sweep the full duration. */
export const TRIPS_SWEEP_S = 13;
export const TRIPS_TRAIL_LENGTH_S = 2400;

// ---------------------------------------------------------------------------
// Palette — topographic survey sheet, warm dark. CONTRACT §11.
// ---------------------------------------------------------------------------

export const COLOR = {
  /** Charcoal with an olive cast. Chart paper in low light, not a terminal. */
  ground: "#14130E",
  groundLift: "#1C1A13",
  /** Linework is bone, never pure white. */
  bone: "#E8E2D0",
  boneDim: "#8A8574",
  boneFaint: "#4A4636",
  /** Amber is for evidence. Nothing else is ever coloured. */
  amber: "#E8A33D",
  /** The probability field is the only saturated thing on screen. */
  fieldHot: "#FF5A47",
} as const;

/** deck.gl wants RGB arrays. */
export const RGB = {
  bone: [232, 226, 208] as [number, number, number],
  boneDim: [138, 133, 116] as [number, number, number],
  boneFaint: [74, 70, 54] as [number, number, number],
  amber: [232, 163, 61] as [number, number, number],
  fieldHot: [255, 90, 71] as [number, number, number],
  casing: [12, 11, 8] as [number, number, number],
} as const;

// ---------------------------------------------------------------------------
// Field rendering
// ---------------------------------------------------------------------------

/**
 * Single hue, opacity ramp: transparent -> amber -> hot coral. NOT a rainbow,
 * not viridis. Multi-hue ramps fight the hillshade underneath and turn to mud
 * on 3D terrain; a single hue reads as "more of one thing", which is what a
 * probability is.
 */
export const FIELD_RAMP: Array<[number, [number, number, number]]> = [
  [0.0, [40, 22, 8]],
  [0.15, [110, 52, 14]],
  [0.4, [196, 118, 26]],
  [0.7, [232, 163, 61]],
  [1.0, [255, 90, 71]],
];

/**
 * Values below this render fully transparent, so the field does not fog the
 * whole box. Raise it if the map looks hazy on the projector.
 *
 * Measured against the committed mocks: the settled field has a mean cell value
 * of 0.032 and only 12.4% of cells above 0.06, so a floor of 0.06 rendered the
 * headline state as a faint smudge while the rail claimed 23.7%. At 0.02 that
 * becomes 18.6% of cells and the surface actually reads.
 */
export const FIELD_FLOOR = 0.02;

/**
 * Display gamma applied above the floor. A probability field normalised to
 * 0..1 puts almost all of its cells in the bottom tenth of the range — linear
 * mapping spends the entire visible ramp on the handful of cells near the peak
 * and renders everything else as near-black.
 *
 * This is a DISPLAY transform only. It never touches field_area_pct, which is
 * computed from the mass in model/field.py and is the number that carries the
 * argument. Lower = more of the tail visible.
 */
export const FIELD_GAMMA = 0.45;

export const FIELD_MAX_ALPHA = 210;
export const FIELD_RESOLUTION = 256;
