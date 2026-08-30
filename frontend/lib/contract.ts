/**
 * CONTRACT.md as TypeScript. The frozen interface, not our preferences.
 *
 * This is the single place the wire format is written down on the frontend
 * side. If the contract changes it changes here, and the compiler names every
 * consumer that breaks. Nothing else in the app parses a payload.
 *
 * Conventions that are easy to get wrong and expensive to debug:
 *   - Coordinates are ALWAYS [lat, lon], WGS84, decimal degrees.
 *     MapLibre and deck.gl both want [lon, lat]. Flip at the boundary, once.
 *   - Grids are row-major. grid[0] is the NORTH edge, grid[r][0] the WEST edge.
 *   - Times are seconds elapsed since the last known point. Not wall clock.
 *   - Distances are metres unless the field name says otherwise.
 *
 * Where the committed mocks still spell a field differently from the contract
 * prose, this file types the CONTRACT as primary and marks the mock spelling
 * optional. Reconciliation lives in lib/adapt.ts and nowhere else.
 */

export type LatLon = [number, number];

/** [lat, lon, seconds-since-LKP] */
export type TrajectoryPoint = [number, number, number];

export type Family =
  | "route_travelling"
  | "direction_sampling"
  | "backtracking"
  | "view_enhancing"
  | "staying_put";

export const FAMILIES: Family[] = [
  "route_travelling",
  "direction_sampling",
  "backtracking",
  "view_enhancing",
  "staying_put",
];

export const FAMILY_LABEL: Record<Family, string> = {
  route_travelling: "Route travelling",
  direction_sampling: "Direction sampling",
  backtracking: "Backtracking",
  view_enhancing: "View enhancing",
  staying_put: "Staying put",
};

export interface Bounds {
  north: number;
  south: number;
  east: number;
  west: number;
}

// ---------------------------------------------------------------------------
// §4 Hypothesis — surfaced on screen via sim_started
// ---------------------------------------------------------------------------

/**
 * Where a hypothesis came from. `kind: "local"` is the payoff of the Parallel
 * research pass — label and url come from its citations and render as an
 * attribution line under the description. Optional throughout: most hypotheses
 * carry none, and data/local_knowledge.json may not exist at all.
 */
export interface HypothesisSource {
  kind: "terrain" | "statistical" | "local";
  label?: string;
  url?: string;
}

export interface Hypothesis {
  hypothesis_id: string;
  family: Family;
  /** Plain English. Rendered in the rail during SIMULATING. */
  description: string;
  /** Plain English. Why the model proposed it. */
  rationale?: string;
  source?: HypothesisSource;
  /**
   * Optional: the live orchestrator's sim_started omits it (it sends only
   * hypothesis_id, family, description and source). Anything reading this must
   * cope with it being absent.
   */
  weight?: number;
  start?: LatLon;
  duration_s?: number;
  n_runs?: number;
  seed_base?: number;
}

// ---------------------------------------------------------------------------
// §6 Trajectory batch — worker to orchestrator
// ---------------------------------------------------------------------------

export interface TrajectoryRun {
  run_index: number;
  /** Downsampled to <= 60 points by the worker. */
  points: TrajectoryPoint[];
  endpoint: LatLon | null;
  duration_s: number;
  status: "ok" | "failed";
}

/** One sandbox, one generated script, many seeded runs. */
export interface TrajectoryBatch {
  hypothesis_id: string;
  family: Family;
  weight: number;
  /** false when the deterministic fallback template ran instead of model code.
   *  This is what feeds the failure count on screen, which is credibility. */
  generated: boolean;
  runs: TrajectoryRun[];
}

// ---------------------------------------------------------------------------
// §7 Field update — orchestrator to frontend
// ---------------------------------------------------------------------------

export interface Zone {
  name: string;
  pct: number;
  centroid: LatLon;
}

/**
 * The witness report, as a spatial and temporal constraint.
 *
 * CONTRACT §9 spells this `{lat, lon, t, radius_m, reliability}`.
 * mocks/field_collapsed.json ships `{location, t_s, radius_m, tolerance_s,
 * description}`. Both are accepted — see normaliseEvidence in lib/adapt.ts.
 */
export interface Evidence {
  lat?: number;
  lon?: number;
  /** Mock spelling of [lat, lon]. */
  location?: LatLon;
  /** Seconds since LKP. Contract spells it `t`, the mock `t_s`. */
  t?: number;
  t_s?: number;
  radius_m: number;
  /** Contract only, 0..1. */
  reliability?: number;
  /** Mock only. Seconds of slack either side of `t`. */
  tolerance_s?: number;
  description?: string;
}

export interface FieldUpdate {
  bounds: Bounds;
  resolution: number;
  /** base64 float32, resolution^2, row-major, normalised 0..1 */
  grid: string;
  /** 0..1 — whether this is a partial or a final field. */
  progress: number;
  zones: Zone[];
  n_total: number;
  n_consistent: number;
  ring_radius_m: number;
  /**
   * The area of the smallest region containing 50% of the probability mass, as
   * a percentage of the ring's area. The headline number.
   *
   * NOT "cells above a threshold" — that is arbitrary and shifts with
   * normalisation. Computed identically for the ring, so the comparison is
   * like-for-like rather than rhetorical. Implemented in model/field.py.
   */
  field_area_pct: number;
  /** Present only on evidence_applied. */
  evidence?: Evidence;
}

// ---------------------------------------------------------------------------
// §8 Intake — extraction, which is also the case_loaded payload
// ---------------------------------------------------------------------------

export interface Extraction {
  transcript?: string;
  subject: {
    name?: string;
    age?: number;
    category?: string;
    experience?: string;
    clothing?: string;
    injuries?: string;
  };
  last_known: {
    place?: string;
    time?: string;
    elapsed_min?: number;
    ipp: LatLon;
  };
  assessment: {
    ring_radius_m: number;
    conditions?: string;
  };
  confidence?: Record<string, number>;
}

// ---------------------------------------------------------------------------
// §9 WebSocket
// ---------------------------------------------------------------------------

export type MessageType =
  | "transcript_partial"
  | "extraction_update"
  | "case_loaded"
  | "sim_started"
  | "fleet_status"
  | "trajectory_batch"
  | "field_update"
  | "evidence_applied"
  | "validation_result"
  | "state_change";

export interface Envelope<T = unknown> {
  type: MessageType;
  seq: number;
  payload: T;
}

export interface TranscriptPartial {
  text: string;
  is_final: boolean;
}

export interface SimStarted {
  n_planned: number;
  /** At most 6, the highest-weighted. */
  hypotheses: Hypothesis[];
}

/**
 * §9 spells this `{active, complete, failed, families}`.
 * mocks/fleet_status.json ships the `sandboxes_*` / `runs_*` spelling.
 * Both are accepted — see normaliseFleet in lib/adapt.ts.
 */
export interface FleetStatus {
  active?: number;
  complete?: number;
  failed?: number;
  families?: Record<string, number>;
  // Mock spelling.
  elapsed_s?: number;
  sandboxes_requested?: number;
  sandboxes_ready?: number;
  sandboxes_active?: number;
  hypotheses_completed?: number;
  runs_completed?: number;
  runs_failed?: number;
  progress?: number;
}

export interface TrajectoryBatchMessage {
  batches: TrajectoryBatch[];
}

export interface ValidationResult {
  n_cases: number;
  our_score: number | null;
  /** The ring on the SAME cases with the SAME metric. 0.761, never 0.78. */
  ring_baseline: number;
  per_case?: number[];
  ci95?: [number, number];
}

export interface StateChange {
  state: DemoState;
}

// ---------------------------------------------------------------------------
// States, in order
// ---------------------------------------------------------------------------

export type DemoState =
  | "landing"
  | "intake"
  | "briefing"
  | "simulating"
  | "field_ready"
  | "evidence"
  | "validation";

export const STATES: DemoState[] = [
  "landing",
  "intake",
  "briefing",
  "simulating",
  "field_ready",
  "evidence",
  "validation",
];

// ---------------------------------------------------------------------------
// The conversions that are easy to get subtly wrong
// ---------------------------------------------------------------------------

/**
 * Decode a base64 float32 grid into a Float32Array of length resolution^2,
 * row-major with row 0 at the north edge.
 *
 * The trap: base64 -> binary string -> Uint8Array -> Float32Array must share
 * one buffer, and the byte length must be a multiple of 4. If the field ever
 * renders as noise, check here first.
 */
export function decodeGrid(base64: string, resolution: number): Float32Array {
  const binary = atob(base64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) bytes[i] = binary.charCodeAt(i);

  const expected = resolution * resolution * 4;
  if (bytes.byteLength !== expected) {
    throw new Error(
      `grid decode: got ${bytes.byteLength} bytes, expected ${expected} ` +
        `for ${resolution}x${resolution} float32`,
    );
  }
  return new Float32Array(bytes.buffer, bytes.byteOffset, resolution * resolution);
}

/** Contract [lat, lon] -> deck.gl / MapLibre [lon, lat]. */
export const toLngLat = ([lat, lon]: LatLon): [number, number] => [lon, lat];

/**
 * Canvas/image source coordinates, clockwise from top-left.
 * Row 0 is NORTH, so the first pair is (west, north). Get this backwards and
 * the field renders vertically mirrored — easy to miss on a blobby surface, and
 * impossible to miss once someone asks why the bright zone moved.
 */
export function boundsToCoordinates(
  b: Bounds,
): [[number, number], [number, number], [number, number], [number, number]] {
  return [
    [b.west, b.north],
    [b.east, b.north],
    [b.east, b.south],
    [b.west, b.south],
  ];
}
