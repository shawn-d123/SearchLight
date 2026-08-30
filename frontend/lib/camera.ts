import type { Map as MapLibreMap, PaddingOptions } from "maplibre-gl";
import type { DemoState, LatLon } from "./contract";
import { ringBounds } from "./geometry";
import { CAMERA_MOVE_MS, PITCH_FLATTENED, PITCH_PRESENTING } from "./config";

/**
 * One scripted camera per state, plus the two keys that recover from a judge's
 * question: R resets to the current state's camera, F drops the pitch so ground
 * hidden behind a ridge becomes visible.
 *
 * Framing is computed from the ring rather than hardcoded, so it stays correct
 * if the case changes or the p95 is re-derived. `cameraForBounds` also reads the
 * live viewport, which means the projector's aspect ratio is handled rather than
 * discovered at 16:00.
 *
 * Rehearsal check the contract asks for: confirm the bright zone is visible from
 * the default camera in every state. If it is not, change `margin` here — not
 * the terrain exaggeration.
 */

export interface CameraPose {
  /** Extra margin around the ring, as a fraction of its radius. */
  margin: number;
  pitch: number;
}

/**
 * Pitch stays at the presenting value across the map states: the contract calls
 * for a fixed 55–60°, and a camera that changes angle between beats reads as
 * fidgeting. What changes is how tightly the ring is framed.
 */
export const CAMERA: Record<DemoState, CameraPose> = {
  // No map in these two. Kept total so adding a state is a compile error
  // rather than a blank screen.
  landing: { margin: 0.25, pitch: 0 },
  intake: { margin: 0.25, pitch: 0 },

  /** The ring, whole, with room around it. This frame is the opening image. */
  briefing: { margin: 0.22, pitch: PITCH_PRESENTING },
  /** Unchanged — the paths must spread inside the frame the ring set up. */
  simulating: { margin: 0.22, pitch: PITCH_PRESENTING },
  /** Slightly tighter once the field has something to show. */
  field_ready: { margin: 0.14, pitch: PITCH_PRESENTING },
  /** Tighter again: the collapse is the point, and it is a small area. */
  evidence: { margin: 0.08, pitch: PITCH_PRESENTING },
  /** Back out, so the ring is whole again while the number is read. */
  validation: { margin: 0.22, pitch: PITCH_PRESENTING },
};

/**
 * cameraForBounds solves for pitch 0. A pitched camera spreads the same ground
 * over more screen, so pull back or the ring's far edge leaves the frame.
 * One number, tunable if the projector disagrees.
 */
export const PITCHED_ZOOM_BIAS = 0.45;

export function moveToState(
  map: MapLibreMap,
  state: DemoState,
  ipp: LatLon,
  ringRadiusM: number,
  padding: PaddingOptions,
  opts: { duration?: number; pitchOverride?: number } = {},
) {
  const pose = CAMERA[state];
  const b = ringBounds(ipp, ringRadiusM * (1 + pose.margin));

  const camera = map.cameraForBounds(
    [
      [b.west, b.south],
      [b.east, b.north],
    ],
    { padding },
  );
  if (!camera) return;

  const pitch = opts.pitchOverride ?? pose.pitch;
  map.easeTo({
    center: camera.center,
    zoom: (camera.zoom ?? map.getZoom()) - (pitch > 5 ? PITCHED_ZOOM_BIAS : 0),
    pitch,
    bearing: 0,
    duration: opts.duration ?? CAMERA_MOVE_MS,
    essential: true,
  });
}

/** F key. Returns the pitch to move to. */
export function flattenedPitch(current: number): number {
  return current > PITCH_FLATTENED + 5 ? PITCH_FLATTENED : PITCH_PRESENTING;
}
