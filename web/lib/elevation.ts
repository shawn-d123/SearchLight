import type { Map as MapLibreMap } from "maplibre-gl";
import type { Bounds } from "./contract";

/**
 * Terrain height lookup, for placing deck.gl geometry at the right altitude.
 *
 * Why this is needed at all: MapLibre draws its own layers on the terrain mesh,
 * but deck.gl layers are drawn at whatever `z` we give them, and z defaults to
 * 0 — sea level. Measured on the prep build at 3x exaggeration, that put
 * deck.gl geometry up to 115 px from the ground feature it belonged to at pitch
 * 55, and ~60 px out even at pitch 0. Markers slide off ridges and paths stop
 * following the valleys, which is the entire visual argument. The Catalinas
 * carry 2,154 m of relief, so the error here is larger than it was in testing.
 *
 * `map.queryTerrainElevation` is the correct answer per point but far too slow
 * for 12,000 paths x 60 points. So sample it once onto a coarse grid and
 * bilinearly interpolate — terrain is smooth at this scale and the residual is
 * a few metres, which is invisible.
 *
 * NOTE: the values include the terrain exaggeration, which is what we want:
 * deck.gl has to match the mesh as drawn, not the real world.
 *
 * The workers already hold the DEM as numpy arrays and could return elevation
 * per trajectory point for free — cheaper and more accurate than sampling in
 * the browser. Raised with B and C; this exists either way, because the markers
 * and the witness pin need heights the contract does not carry.
 */
export interface ElevationSampler {
  /** Exaggerated ground height in metres at [lat, lon]. */
  at(lat: number, lon: number): number;
  readonly resolution: number;
  readonly builtInMs: number;
}

export function buildElevationSampler(
  map: MapLibreMap,
  bounds: Bounds,
  resolution = 96,
): ElevationSampler {
  const t0 = performance.now();
  const grid = new Float32Array(resolution * resolution);

  const latSpan = bounds.north - bounds.south;
  const lonSpan = bounds.east - bounds.west;

  for (let r = 0; r < resolution; r++) {
    // Row 0 is the north edge, matching the contract's grid convention.
    const lat = bounds.north - (latSpan * r) / (resolution - 1);
    for (let c = 0; c < resolution; c++) {
      const lon = bounds.west + (lonSpan * c) / (resolution - 1);
      grid[r * resolution + c] = map.queryTerrainElevation([lon, lat]) ?? 0;
    }
  }

  const builtInMs = performance.now() - t0;

  return {
    resolution,
    builtInMs,
    at(lat: number, lon: number): number {
      // Fractional grid coordinates, clamped so points outside the sampled box
      // get the nearest edge value rather than nonsense.
      const fr = ((bounds.north - lat) / latSpan) * (resolution - 1);
      const fc = ((lon - bounds.west) / lonSpan) * (resolution - 1);
      const r0 = Math.max(0, Math.min(resolution - 1, Math.floor(fr)));
      const c0 = Math.max(0, Math.min(resolution - 1, Math.floor(fc)));
      const r1 = Math.min(resolution - 1, r0 + 1);
      const c1 = Math.min(resolution - 1, c0 + 1);
      const dr = Math.max(0, Math.min(1, fr - r0));
      const dc = Math.max(0, Math.min(1, fc - c0));

      const a = grid[r0 * resolution + c0];
      const b = grid[r0 * resolution + c1];
      const c = grid[r1 * resolution + c0];
      const d = grid[r1 * resolution + c1];

      return (
        a * (1 - dr) * (1 - dc) +
        b * (1 - dr) * dc +
        c * dr * (1 - dc) +
        d * dr * dc
      );
    },
  };
}
