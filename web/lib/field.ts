import type { Map as MapLibreMap } from "maplibre-gl";
import { boundsToCoordinates, type Bounds } from "./contract";
import {
  FIELD_FLOOR,
  FRAME_MS,
  FIELD_GAMMA,
  FIELD_INTERPOLATE_MS,
  FIELD_MAX_ALPHA,
  FIELD_RAMP,
} from "./config";

/**
 * The probability field: decode, paint, drape, and grow rather than flicker.
 *
 * WHY A MAPLIBRE IMAGE SOURCE AND NOT A DECK.GL LAYER
 * deck.gl layers over MapLibre terrain do not follow the ground. They render in
 * their own pass at whatever z they are given and float flat across ridges,
 * which is obviously wrong on 2,154 m of relief. MapLibre drapes its own raster
 * sources onto the terrain mesh natively. `_TerrainExtension` would work in
 * principle but is an experimental underscore-prefixed export in deck.gl 9.3
 * that renders nothing at all in overlaid mode.
 *
 * WHY IMAGE AND NOT CANVAS — this one cost real time, so it is written down.
 * A `canvas` source is the obvious choice for a surface that repaints in place,
 * and it works perfectly at pitch 0. At pitch 57 over terrain it TEARS: the
 * field renders as hard-edged polygons that look like a broken shader. Verified
 * by swapping an `image` source with byte-identical pixels and identical
 * coordinates onto the same map at the same camera — the image source drapes
 * cleanly and the canvas source does not. It is not tile residency
 * (`areTilesLoaded` was true), not the size of the quad (a 40%-linear quad tore
 * the same way), and not the number of updates (a single update tore too).
 *
 * The cost of `image` is that `updateImage` only accepts a URL, so every change
 * is a PNG encode. Encoding 60 times a second to interpolate would be absurd,
 * so the transition is done as a CROSS-FADE between two image layers instead:
 * one encode per field_update, and the 800 ms transition is pure
 * `raster-opacity`, which costs nothing.
 *
 * THE FIELD ACCUMULATES, IT DOES NOT APPEAR
 * Updates land roughly every second with a `progress` value. Swapping instantly
 * makes the surface flicker between states; fading over ~800 ms makes it appear
 * to grow, which is literally what is happening statistically, and it fills the
 * dead air between "paths flying" and "here is the field".
 */

const LAYER_A = "sl-field-a";
const LAYER_B = "sl-field-b";
export const FIELD_LAYER_IDS = [LAYER_A, LAYER_B] as const;

function rampColour(t: number): [number, number, number] {
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

/** 256 entries turns the per-pixel ramp search into an array index.
 *  The gamma is applied here, once, rather than per pixel per paint. */
const LUT = (() => {
  const lut = new Uint8ClampedArray(256 * 4);
  for (let i = 0; i < 256; i++) {
    const t = Math.pow(i / 255, FIELD_GAMMA);
    const [r, g, b] = rampColour(t);
    lut[i * 4] = r;
    lut[i * 4 + 1] = g;
    lut[i * 4 + 2] = b;
    // Alpha ramps too, so low probability fades in rather than sitting as a
    // plate with a hard edge. sqrt on top of the gamma lifts the low end
    // enough to survive a projector without fogging the whole box.
    lut[i * 4 + 3] = Math.min(FIELD_MAX_ALPHA, FIELD_MAX_ALPHA * Math.sqrt(t));
  }
  return lut;
})();

/** A fully transparent 1x1 PNG, so both layers can exist before any data. */
const EMPTY_PNG =
  "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==";

export class FieldRenderer {
  private canvas: HTMLCanvasElement;
  private ctx: CanvasRenderingContext2D;
  private image: ImageData;
  private resolution: number;

  private map: MapLibreMap | null = null;
  private bounds: Bounds | null = null;

  /** Which layer is currently the visible one. */
  private front: typeof LAYER_A | typeof LAYER_B = LAYER_A;
  private raf = 0;
  /** Guards against an older encode landing after a newer one. */
  private seq = 0;
  private visible = false;

  constructor(resolution: number) {
    this.resolution = resolution;
    this.canvas = document.createElement("canvas");
    this.canvas.width = resolution;
    this.canvas.height = resolution;
    const ctx = this.canvas.getContext("2d");
    if (!ctx) throw new Error("field: 2d context unavailable");
    this.ctx = ctx;
    this.image = ctx.createImageData(resolution, resolution);
  }

  /**
   * Add both sources and layers once, then toggle visibility. Adding and
   * removing sources mid-demo is a good way to find a new bug on stage.
   */
  attach(map: MapLibreMap, bounds: Bounds, beforeId?: string) {
    this.map = map;
    this.bounds = bounds;
    const coordinates = boundsToCoordinates(bounds);

    for (const id of FIELD_LAYER_IDS) {
      map.addSource(id, { type: "image", url: EMPTY_PNG, coordinates });
      map.addLayer(
        {
          id,
          type: "raster",
          source: id,
          paint: {
            "raster-opacity": 0,
            // MapLibre's own cross-fade would fight ours.
            "raster-fade-duration": 0,
            // The grid is a smoothed density, so it should read as a
            // continuous surface. `nearest` would expose the 256px cells as
            // visible squares once the camera is close, which reads as a
            // low-resolution image rather than a field.
            "raster-resampling": "linear",
          },
          layout: { visibility: "none" },
        },
        beforeId,
      );
    }
  }

  setVisible(visible: boolean) {
    this.visible = visible;
    const map = this.map;
    if (!map) return;
    for (const id of FIELD_LAYER_IDS) {
      if (map.getLayer(id)) {
        map.setLayoutProperty(id, "visibility", visible ? "visible" : "none");
      }
    }
  }

  private setCoordinates(bounds: Bounds) {
    const map = this.map;
    if (!map || !this.bounds) return;
    const a = this.bounds;
    if (
      a.north === bounds.north &&
      a.south === bounds.south &&
      a.east === bounds.east &&
      a.west === bounds.west
    ) {
      return;
    }
    this.bounds = bounds;
    const coordinates = boundsToCoordinates(bounds);
    for (const id of FIELD_LAYER_IDS) {
      const src = map.getSource(id);
      if (src && "setCoordinates" in src) {
        (src as { setCoordinates: (c: unknown) => void }).setCoordinates(
          coordinates,
        );
      }
    }
  }

  /** Move to a new grid, cross-fading over FIELD_INTERPOLATE_MS. */
  async update(grid: Float32Array, bounds?: Bounds) {
    const n = this.resolution * this.resolution;
    if (grid.length !== n) {
      throw new Error(`field: grid is ${grid.length} floats, expected ${n}`);
    }
    const map = this.map;
    if (!map) return;
    if (bounds) this.setCoordinates(bounds);

    const mine = ++this.seq;
    const url = this.encode(grid);

    // Decode before handing the URL to MapLibre, so the fade starts against a
    // texture that already exists rather than a blank frame.
    await this.preload(url);
    if (mine !== this.seq || !this.map) return;

    const back = this.front === LAYER_A ? LAYER_B : LAYER_A;
    const src = map.getSource(back);
    if (!src || !("updateImage" in src)) return;
    (src as { updateImage: (o: { url: string }) => void }).updateImage({ url });

    // One more frame so the new texture is uploaded before it is faded up.
    await new Promise<void>((r) => requestAnimationFrame(() => r()));
    if (mine !== this.seq || !this.map) return;

    this.fade(back, this.front, FIELD_INTERPOLATE_MS);
    this.front = back;
  }

  /** Set a grid with no transition. First paint, and reset between rehearsals. */
  async set(grid: Float32Array, bounds?: Bounds) {
    const map = this.map;
    if (!map) return;
    if (bounds) this.setCoordinates(bounds);
    const mine = ++this.seq;
    const url = this.encode(grid);
    await this.preload(url);
    if (mine !== this.seq || !this.map) return;

    const src = map.getSource(this.front);
    if (src && "updateImage" in src) {
      (src as { updateImage: (o: { url: string }) => void }).updateImage({ url });
    }
    this.stopFade();
    map.setPaintProperty(this.front, "raster-opacity", 1);
    map.setPaintProperty(
      this.front === LAYER_A ? LAYER_B : LAYER_A,
      "raster-opacity",
      0,
    );
  }

  /** Clear to nothing. Used when re-entering briefing for a second rehearsal. */
  clear() {
    const map = this.map;
    if (!map) return;
    this.seq++;
    this.stopFade();
    for (const id of FIELD_LAYER_IDS) {
      map.setPaintProperty(id, "raster-opacity", 0);
      const src = map.getSource(id);
      if (src && "updateImage" in src) {
        (src as { updateImage: (o: { url: string }) => void }).updateImage({
          url: EMPTY_PNG,
        });
      }
    }
  }

  private stopFade() {
    if (this.raf) cancelAnimationFrame(this.raf);
    this.raf = 0;
  }

  private fade(inId: string, outId: string, ms: number) {
    const map = this.map;
    if (!map) return;
    this.stopFade();
    const t0 = performance.now();
    let lastPaint = 0;
    const step = () => {
      if (!this.map) return;
      const elapsed = performance.now() - t0;
      // Capped to TARGET_FPS like the path clock. An 800ms fade does not need
      // sixty samples, and this keeps the two loops from fighting for frames
      // while the field settles over paths that are still animating.
      if (elapsed - lastPaint < FRAME_MS && elapsed < ms) {
        this.raf = requestAnimationFrame(step);
        return;
      }
      lastPaint = elapsed;
      const t = Math.min(1, elapsed / ms);
      // Exponential ease-out: the surface leaps toward the new state and
      // settles, rather than crawling linearly.
      const e = 1 - Math.pow(1 - t, 3);
      map.setPaintProperty(inId, "raster-opacity", e);
      map.setPaintProperty(outId, "raster-opacity", 1 - e);
      if (t < 1) {
        this.raf = requestAnimationFrame(step);
      } else {
        this.raf = 0;
      }
    };
    this.raf = requestAnimationFrame(step);
  }

  private preload(url: string): Promise<void> {
    return new Promise((resolve) => {
      const img = new Image();
      img.onload = () => resolve();
      img.onerror = () => resolve();
      img.src = url;
    });
  }

  private encode(grid: Float32Array): string {
    const data = this.image.data;
    for (let i = 0; i < grid.length; i++) {
      const v = grid[i];
      const o = i * 4;
      if (v <= FIELD_FLOOR) {
        // RGB must be cleared too, not just alpha: PNG encoding keeps the
        // colour channels, and a transparent pixel carrying a stale hot colour
        // bleeds into its neighbours when the texture is filtered.
        data[o] = 0;
        data[o + 1] = 0;
        data[o + 2] = 0;
        data[o + 3] = 0;
        continue;
      }
      // Rescale above the floor so the ramp uses its full range rather than
      // spending its first sixth on values that never render.
      const t = Math.min(1, (v - FIELD_FLOOR) / (1 - FIELD_FLOOR));
      const k = (t * 255) | 0;
      data[o] = LUT[k * 4];
      data[o + 1] = LUT[k * 4 + 1];
      data[o + 2] = LUT[k * 4 + 2];
      data[o + 3] = LUT[k * 4 + 3];
    }
    this.ctx.putImageData(this.image, 0, 0);
    return this.canvas.toDataURL("image/png");
  }

  destroy() {
    this.stopFade();
    this.seq++;
    this.map = null;
  }

  /** True while the layers are showing. Read by the rig/verify harness. */
  get isVisible() {
    return this.visible;
  }
}
