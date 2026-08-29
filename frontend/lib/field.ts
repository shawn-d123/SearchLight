// Decode a base64 float32 probability grid into a canvas, so MapLibre can drape
// it on the terrain as an image source.
//
// WHY an image source and not a deck.gl layer: deck.gl layers over MapLibre
// terrain do NOT follow the ground -- they render in their own pass and float
// flat. MapLibre drapes its own raster and image layers onto terrain natively.
// C sends a grid, we paint it to a canvas, the canvas becomes the image source.
// (The alternative, TerrainExtension, works but is another thing to debug.)

import { FIELD_FLOOR, FIELD_MAX_ALPHA, FIELD_RAMP } from "./config";

export type FieldPayload = {
  bounds: { north: number; south: number; east: number; west: number };
  resolution: number;
  grid: string; // base64 float32, row-major, grid[0] is the NORTH edge
  progress: number;
  zones: Array<{ name: string; pct: number; centroid: [number, number] }>;
  n_total: number;
  n_consistent: number;
  ring_radius_m: number;
  field_area_pct: number;
};

/** base64 -> Float32Array. Row-major, row 0 is north. See CONTRACT.md. */
export function decodeGrid(b64: string, resolution: number): Float32Array {
  const bin = atob(b64);
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  const grid = new Float32Array(bytes.buffer);
  if (grid.length !== resolution * resolution) {
    throw new Error(
      `field grid is ${grid.length} floats, expected ${resolution * resolution}`,
    );
  }
  return grid;
}

function ramp(t: number): [number, number, number] {
  for (let i = 1; i < FIELD_RAMP.length; i++) {
    const [t1, c1] = FIELD_RAMP[i];
    if (t <= t1) {
      const [t0, c0] = FIELD_RAMP[i - 1];
      const f = t1 === t0 ? 0 : (t - t0) / (t1 - t0);
      return [
        c0[0] + (c1[0] - c0[0]) * f,
        c0[1] + (c1[1] - c0[1]) * f,
        c0[2] + (c1[2] - c0[2]) * f,
      ];
    }
  }
  return FIELD_RAMP[FIELD_RAMP.length - 1][1];
}

/** Paint a normalised 0..1 grid onto a canvas with the single-hue ramp. */
export function gridToCanvas(
  grid: Float32Array,
  resolution: number,
  canvas?: HTMLCanvasElement,
): HTMLCanvasElement {
  const cv = canvas ?? document.createElement("canvas");
  cv.width = resolution;
  cv.height = resolution;
  const ctx = cv.getContext("2d")!;
  const img = ctx.createImageData(resolution, resolution);

  for (let i = 0; i < grid.length; i++) {
    const v = grid[i];
    const o = i * 4;
    if (v <= FIELD_FLOOR) {
      img.data[o + 3] = 0;
      continue;
    }
    // Rescale above the floor so the ramp uses its full range.
    const t = Math.min(1, (v - FIELD_FLOOR) / (1 - FIELD_FLOOR));
    const [r, g, b] = ramp(t);
    img.data[o] = r;
    img.data[o + 1] = g;
    img.data[o + 2] = b;
    // Ramp alpha too, so low probability fades rather than sitting as a plate.
    img.data[o + 3] = Math.min(FIELD_MAX_ALPHA, FIELD_MAX_ALPHA * Math.sqrt(t));
  }
  ctx.putImageData(img, 0, 0);
  return cv;
}

/** Image-source coordinates, clockwise from top-left. Row 0 is NORTH, so the
 *  first pair is (west, north) -- get this backwards and the field is flipped. */
export function boundsToCoordinates(
  b: FieldPayload["bounds"],
): [[number, number], [number, number], [number, number], [number, number]] {
  return [
    [b.west, b.north],
    [b.east, b.north],
    [b.east, b.south],
    [b.west, b.south],
  ];
}

/** Flatten CONTRACT.md trajectory batches into TripsLayer-ready paths.
 *  Runs with status !== 'ok' are counted, not plotted. */
export type Batch = {
  hypothesis_id: string;
  family: string;
  weight: number;
  generated: boolean;
  runs: Array<{
    run_index: number;
    points: Array<[number, number, number]>; // [lat, lon, t_seconds]
    endpoint: [number, number] | null;
    duration_s: number;
    status: "ok" | "failed";
  }>;
};

export type Trip = {
  path: Array<[number, number]>; // [lon, lat] -- deck.gl wants x,y
  timestamps: number[];
  family: string;
};

export function batchesToTrips(batches: Batch[]): {
  trips: Trip[];
  nTotal: number;
  nFailed: number;
  maxTime: number;
} {
  const trips: Trip[] = [];
  let nTotal = 0;
  let nFailed = 0;
  let maxTime = 0;
  for (const b of batches) {
    for (const run of b.runs) {
      nTotal++;
      if (run.status !== "ok" || run.points.length < 2) {
        nFailed++;
        continue;
      }
      const path: Array<[number, number]> = [];
      const timestamps: number[] = [];
      for (const [lat, lon, t] of run.points) {
        path.push([lon, lat]);
        timestamps.push(t);
        if (t > maxTime) maxTime = t;
      }
      trips.push({ path, timestamps, family: b.family });
    }
  }
  return { trips, nTotal, nFailed, maxTime };
}
