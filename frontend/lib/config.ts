// Scaffold config for Person A. Everything the demo needs to change late is a
// named constant here, so raising the camera is one edit rather than a hunt.

import bbox from "./bbox.json";

/** 'mock' reads mocks/*.json from /public. 'live' reads the orchestrator WS.
 *  The 14:30 integration point is flipping this and finding out what breaks. */
export const DATA_SOURCE: "mock" | "live" = "mock";

export const WS_URL = "ws://localhost:8000/ws";

// --- camera -----------------------------------------------------------------
// Build flat and raise the camera once everything works. Spec section 22:
// "that should be changing one number, not a rewrite".
//
// PITCH 0 tonight. On the day: 55-60 for the 2.5D look.
// Past ~4x exaggeration terrain stops reading as landscape and starts reading
// as a video game. Say "vertical exaggeration 3x" once in the pitch.
export const PITCH = 0;
export const PITCH_PRESENTING = 57;
export const PITCH_FLATTENED = 15; // one key drops to this to reveal hidden ground
export const EXAGGERATION = 3.0;
export const BEARING = 0; // rotation is disabled; a wrong bearing hides the bright zone

export const BOUNDS = bbox as unknown as {
  north: number; south: number; east: number; west: number;
  centre: [number, number]; width_km: number; height_km: number;
  region: string; case_ids: string[];
};

export const INITIAL_VIEW = {
  longitude: BOUNDS.centre[1],
  latitude: BOUNDS.centre[0],
  zoom: 10.4,
  pitch: PITCH,
  bearing: BEARING,
};

// --- basemap + terrain ------------------------------------------------------
export const BASEMAP_STYLE =
  "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json";

// AWS public terrain tiles. No key, no rate limit. Cache these locally before
// the venue -- do not trust venue wifi at 16:50.
export const TERRAIN_TILES =
  "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png";
export const TERRAIN_ENCODING = "terrarium" as const;

// --- field rendering --------------------------------------------------------
// Single hue, opacity ramp: transparent -> amber -> hot coral. NOT a rainbow,
// not viridis. Multi-hue ramps fight the hillshade and turn to mud on 3D
// terrain; a single hue reads as "more of one thing", which is what
// probability is.
export const FIELD_RAMP: Array<[number, [number, number, number]]> = [
  [0.0, [0, 0, 0]],
  [0.15, [90, 40, 10]],
  [0.4, [200, 120, 20]],
  [0.7, [240, 160, 40]],
  [1.0, [255, 90, 60]],
];

/** Values below this render fully transparent, so the field does not fog the
 *  whole box. Raise it if the map looks hazy on the projector. */
export const FIELD_FLOOR = 0.06;
export const FIELD_MAX_ALPHA = 210;

export const MOCKS = {
  case: "/mocks/case.json",
  trajectories: "/mocks/trajectories.json",
  field: "/mocks/field.json",
  fieldPartial: "/mocks/field_partial.json",
  fieldCollapsed: "/mocks/field_collapsed.json",
  fleetStatus: "/mocks/fleet_status.json",
};
