import type { Family, TrajectoryBatch } from "./contract";

/**
 * Trajectory batches -> TripsLayer rows.
 *
 * Paths float `altitudeM` above the ground rather than being draped: it looks
 * better and avoids z-fighting where lines flicker in and out of hillsides.
 *
 * `elevationAt` is what makes "above the ground" true. Without it every path
 * sits at z = 0 — sea level — and on 3x-exaggerated terrain with 2,154 m of
 * relief that is a multi-kilometre error, which reads on screen as paths that
 * ignore the valleys entirely. Pass the sampler from lib/elevation.ts.
 */

export interface Trip {
  /** [lon, lat, altitude-metres] — flipped from the contract's [lat, lon]. */
  path: [number, number, number][];
  /** Seconds since LKP, parallel to `path`. */
  timestamps: number[];
  family: Family;
}

export interface TripSet {
  trips: Trip[];
  /** Every run the workers reported, including failures. */
  nTotal: number;
  /** status !== "ok". Counted, never plotted. A failure count on screen is
   *  credibility, not weakness. */
  nFailed: number;
  /** Largest timestamp, so the animation clock knows its span. */
  maxTime: number;
}

export function batchesToTrips(
  batches: TrajectoryBatch[],
  altitudeM: number,
  limit = Infinity,
  elevationAt?: (lat: number, lon: number) => number,
): TripSet {
  const trips: Trip[] = [];
  let nTotal = 0;
  let nFailed = 0;
  let maxTime = 0;

  for (const batch of batches) {
    for (const run of batch.runs) {
      nTotal++;
      if (run.status !== "ok" || run.points.length < 2) {
        nFailed++;
        continue;
      }
      // The cap is on what is DRAWN. The full set stays in the data, so the
      // counts in the rail remain honest even when the render is subsetted.
      if (trips.length >= limit) continue;

      const path: [number, number, number][] = [];
      const timestamps: number[] = [];
      for (const [lat, lon, t] of run.points) {
        path.push([lon, lat, (elevationAt ? elevationAt(lat, lon) : 0) + altitudeM]);
        timestamps.push(t);
        if (t > maxTime) maxTime = t;
      }
      trips.push({ path, timestamps, family: batch.family });
    }
  }

  return { trips, nTotal, nFailed, maxTime };
}
