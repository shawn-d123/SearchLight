import type { Bounds, LatLon } from "./contract";

/**
 * Metres per degree at the demo latitude, from data/meta.json. Using the
 * spherical 111,320 for latitude everywhere costs ~0.7% here, which is 65 m on
 * the ring — visible when the ring is meant to be exactly the published p95.
 */
const M_PER_DEG_LAT = 110_574;

const mPerDegLon = (lat: number) => 111_320 * Math.cos((lat * Math.PI) / 180);

/**
 * A circle of `radiusM` around a [lat, lon] centre, returned as [lon, lat]
 * ready for MapLibre. This is the ISRID ring — naive by design. It is the least
 * interesting object on screen and it carries the entire argument.
 */
export function ringPath(
  centre: LatLon,
  radiusM: number,
  segments = 256,
): [number, number][] {
  const [lat, lon] = centre;
  const mLon = mPerDegLon(lat);
  const pts: [number, number][] = [];
  for (let i = 0; i <= segments; i++) {
    const a = (i / segments) * Math.PI * 2;
    pts.push([
      lon + (Math.cos(a) * radiusM) / mLon,
      lat + (Math.sin(a) * radiusM) / M_PER_DEG_LAT,
    ]);
  }
  return pts;
}

/** Bounding box enclosing a circle, for camera framing. */
export function ringBounds(centre: LatLon, radiusM: number): Bounds {
  const [lat, lon] = centre;
  return {
    north: lat + radiusM / M_PER_DEG_LAT,
    south: lat - radiusM / M_PER_DEG_LAT,
    east: lon + radiusM / mPerDegLon(lat),
    west: lon - radiusM / mPerDegLon(lat),
  };
}

/** Flat-earth distance in metres. Fine over 45 km. */
export function distanceM(a: LatLon, b: LatLon): number {
  const dLat = (a[0] - b[0]) * M_PER_DEG_LAT;
  const dLon = (a[1] - b[1]) * mPerDegLon((a[0] + b[0]) / 2);
  return Math.hypot(dLat, dLon);
}
