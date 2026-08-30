"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Map as MapLibreMap } from "maplibre-gl";
import type { ErrorEvent, PaddingOptions } from "maplibre-gl";
import { MapboxOverlay } from "@deck.gl/mapbox";
import type { Layer } from "@deck.gl/core";
import { TripsLayer } from "@deck.gl/geo-layers";
import "maplibre-gl/dist/maplibre-gl.css";

import { buildMapStyle } from "@/lib/mapStyle";
import { FieldRenderer } from "@/lib/field";
import { buildElevationSampler, type ElevationSampler } from "@/lib/elevation";
import {
  addCaseLayers,
  addEvidenceLayers,
  setCaseVisible,
  setEvidenceVisible,
  updateCase,
  updateEvidence,
} from "@/lib/mapLayers";
import { flattenedPitch, moveToState } from "@/lib/camera";
import { showsMap } from "@/lib/state";
import type { CaseView, EvidenceView, FieldView } from "@/lib/adapt";
import type { DemoState } from "@/lib/contract";
import type { Trip } from "@/lib/trips";
import {
  BEARING,
  BOUNDS,
  CENTRE,
  COLOR,
  FIELD_RESOLUTION,
  INITIAL_ZOOM,
  MAX_PITCH,
  PITCH,
  RGB,
  FRAME_MS,
  TERRAIN_EXAGGERATION,
  TRIPS_SWEEP_S,
  TRIPS_TRAIL_LENGTH_S,
} from "@/lib/config";

/**
 * MapLibre owns the camera; deck.gl rides along as a MapLibre control via
 * MapboxOverlay.
 *
 * This is the whole answer to "getting deck.gl and MapLibre to share a camera".
 * There is no second view state to keep in sync and no projection matrix to
 * reconcile, because deck.gl is handed MapLibre's matrix every frame. The
 * failure mode the prep doc warned about — layers subtly offset from the
 * basemap, overlays that lag when you pan — is structurally impossible here.
 *
 * maplibre-gl is pinned to 5.x deliberately. On 6.x, MapboxOverlay throws
 * `Cannot read properties of undefined (reading 'elevation')` on every frame
 * and the map renders black. deck.gl 9.3 declares no maplibre peer range, so
 * npm will happily install a version that does not work. Do not bump it.
 */

export interface MapHandles {
  resetCamera(): void;
  toggleFlatten(): void;
}

type Props = {
  state: DemoState;
  caseView: CaseView | null;
  field: FieldView | null;
  evidence: EvidenceView | null;
  trips: Trip[];
  maxTime: number;
  /** Pixels of the viewport covered by the rail, so framing avoids it. */
  railWidth: number;
  onSampler(s: ElevationSampler | null): void;
  onReady?(map: MapLibreMap): void;
  handlesRef?: React.MutableRefObject<MapHandles | null>;
};

export default function MapCanvas({
  state,
  caseView,
  field,
  evidence,
  trips,
  maxTime,
  railWidth,
  onSampler,
  onReady,
  handlesRef,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const overlayRef = useRef<MapboxOverlay | null>(null);
  const fieldRef = useRef<FieldRenderer | null>(null);
  const [ready, setReady] = useState(false);

  const onSamplerRef = useRef(onSampler);
  onSamplerRef.current = onSampler;
  const onReadyRef = useRef(onReady);
  onReadyRef.current = onReady;

  const padding: PaddingOptions = useMemo(
    () => ({ top: 72, bottom: 72, left: 72, right: railWidth + 72 }),
    [railWidth],
  );

  // --- create the map exactly once -----------------------------------------
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new MapLibreMap({
      container: containerRef.current,
      style: buildMapStyle(),
      center: [CENTRE[1], CENTRE[0]], // MapLibre wants [lon, lat]; data is [lat, lon]
      zoom: INITIAL_ZOOM,
      pitch: PITCH,
      bearing: BEARING,
      maxPitch: MAX_PITCH,
      attributionControl: false,
      canvasContextAttributes: {
        // Keeps the drawing buffer readable so the canvas can be screenshotted
        // for the fallback recording. MapLibre 5+ moved this under
        // canvasContextAttributes; it is not a top-level option any more.
        preserveDrawingBuffer: true,
        antialias: true,
        powerPreference: "high-performance",
      },
    });
    mapRef.current = map;

    // Rotation off. A wrong bearing can hide the probability field behind a
    // ridge and there is no time to recover on stage. Pan and zoom stay on:
    // panning exists for one situation, a judge asking to see somewhere
    // specific, and the fact it responds live is itself evidence the map is
    // not a video.
    map.dragRotate.disable();
    map.touchZoomRotate.disableRotation();
    map.keyboard.disableRotation();

    const overlay = new MapboxOverlay({ interleaved: false, layers: [] });
    overlayRef.current = overlay;
    map.addControl(overlay);

    // Handy on the day: `__map` in the console answers "is the camera where I
    // think it is" faster than any amount of guessing.
    (window as unknown as { __map?: MapLibreMap }).__map = map;

    map.on("style.load", () => {
      // Terrain is attached here, not in the style JSON, and only once the
      // style has loaded. Doing both races, and MapLibre throws reading
      // `elevation` off a terrain object that is not built yet.
      //
      // TERRAIN_EXAGGERATION is the one number that turns the flat build into
      // the 3D presentation view. Changing it is a one-line change, by design.
      map.setTerrain({ source: "terrain", exaggeration: TERRAIN_EXAGGERATION });

      // Order matters: the field attaches first so the ring and markers, added
      // after, draw on top of it. The ring has to stay legible through the
      // brightest part of the surface — it is the whole comparison.
      const renderer = new FieldRenderer(FIELD_RESOLUTION);
      renderer.attach(map, BOUNDS);
      fieldRef.current = renderer;

      addCaseLayers(map, CENTRE as [number, number], 1);
      addEvidenceLayers(map);
      setCaseVisible(map, false);

      setReady(true);
      onReadyRef.current?.(map);

      // The DEM has to be in memory before terrain heights can be sampled.
      // Deliberately NOT map.once("idle") — any continuous repaint means the
      // map never goes idle and the sampler would silently never be built,
      // leaving every deck.gl layer at sea level.
      const tryBuild = () => {
        if (!map.isSourceLoaded("terrain")) return false;
        const s = buildElevationSampler(map, BOUNDS, 96);
        (window as unknown as { __samplerMs?: number }).__samplerMs = s.builtInMs;
        onSamplerRef.current(s);
        return true;
      };
      if (!tryBuild()) {
        const onData = () => {
          if (tryBuild()) map.off("sourcedata", onData);
        };
        map.on("sourcedata", onData);
      }
    });

    map.on("error", (e: ErrorEvent) => {
      // Missing DEM tiles outside the cached box are expected while panning;
      // anything else is worth seeing in the console.
      const msg = String(e.error ?? e);
      if (!msg.includes("404")) console.warn("[maplibre]", msg);
    });

    return () => {
      fieldRef.current?.destroy();
      fieldRef.current = null;
      overlayRef.current = null;
      mapRef.current = null;
      map.remove();
    };
  }, []);

  // --- imperative handles for the R and F keys ------------------------------
  const resetCamera = useCallback(() => {
    const map = mapRef.current;
    if (!map || !caseView || !showsMap(state)) return;
    moveToState(map, state, caseView.ipp, caseView.ringRadiusM, padding);
  }, [state, caseView, padding]);

  const toggleFlatten = useCallback(() => {
    const map = mapRef.current;
    if (!map) return;
    map.easeTo({ pitch: flattenedPitch(map.getPitch()), duration: 600 });
  }, []);

  useEffect(() => {
    if (handlesRef) handlesRef.current = { resetCamera, toggleFlatten };
  }, [handlesRef, resetCamera, toggleFlatten]);

  // --- case geometry -------------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !caseView) return;
    updateCase(map, caseView.ipp, caseView.ringRadiusM);
  }, [ready, caseView]);

  // --- state -> layer visibility and camera --------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;

    const onMap = showsMap(state);
    setCaseVisible(map, onMap);
    setEvidenceVisible(map, state === "evidence" || state === "validation");
    fieldRef.current?.setVisible(
      state === "simulating" ||
        state === "field_ready" ||
        state === "evidence" ||
        state === "validation",
    );

    if (onMap && caseView) {
      moveToState(map, state, caseView.ipp, caseView.ringRadiusM, padding);
    }
  }, [ready, state, caseView, padding]);

  // --- field grid ----------------------------------------------------------
  useEffect(() => {
    if (!ready || !fieldRef.current) return;
    if (!field) {
      fieldRef.current.clear();
      return;
    }
    fieldRef.current.update(field.grid, field.bounds);
  }, [ready, field]);

  // --- evidence marker -----------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !evidence) return;
    updateEvidence(map, evidence);
  }, [ready, evidence]);

  // --- path animation clock ------------------------------------------------
  // Only while paths are on screen. The paths are the only fast-moving thing in
  // the entire motion vocabulary, and running this clock in other states would
  // keep the GPU busy for nothing.
  const [time, setTime] = useState(0);
  const animating = state === "simulating" && trips.length > 0;

  useEffect(() => {
    if (!animating) return;
    const span = maxTime || 4320;
    const perMs = span / (TRIPS_SWEEP_S * 1000);
    let raf = 0;
    let last = performance.now();
    let acc = 0;
    const tick = (now: number) => {
      const dt = now - last;
      last = now;
      // Capped to TARGET_FPS. This clock is what drives deck to redraw and
      // MapLibre to repaint, so throttling it here throttles the whole scene —
      // and it advances by the ACCUMULATED time, so the paths still sweep at
      // the same wall-clock speed, just in fewer, larger steps.
      acc += dt;
      if (acc >= FRAME_MS) {
        const step = acc;
        acc = 0;
        // The scene's true frame counter. deck.gl runs its own canvas and loop
        // in overlaid mode, so MapLibre's `render` event does NOT fire for path
        // frames and requestAnimationFrame reports the display refresh rate
        // whether or not anything was drawn. This is the only number that
        // reflects what is actually being animated.
        const w = window as unknown as { __frames?: number };
        w.__frames = (w.__frames ?? 0) + 1;
        // Sweep past the end by a trail length so the last paths finish drawing
        // rather than being cut off mid-flight.
        setTime((t) => (t + step * perMs) % (span + TRIPS_TRAIL_LENGTH_S));
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [animating, maxTime]);

  useEffect(() => {
    if (state === "briefing") setTime(0);
  }, [state]);

  // --- deck.gl layers ------------------------------------------------------
  const layers = useMemo<Layer[]>(() => {
    if (!animating) return [];
    return [
      new TripsLayer<Trip>({
        id: "sl-trips",
        data: trips,
        getPath: (d) => d.path as unknown as number[],
        getTimestamps: (d) => d.timestamps,
        // Amber is for evidence — but the paths ARE the evidence being
        // generated, and they are gone by the time the witness marker appears,
        // so the two never share the screen.
        getColor: RGB.amber,
        opacity: 0.32,
        widthMinPixels: 1.1,
        jointRounded: false,
        capRounded: false,
        fadeTrail: true,
        trailLength: TRIPS_TRAIL_LENGTH_S,
        currentTime: time,
      }),
    ];
  }, [animating, trips, time]);

  useEffect(() => {
    if (!ready) return;
    overlayRef.current?.setProps({ layers });
  }, [layers, ready]);

  // NOTE: sized with h-full/w-full, not `absolute inset-0`.
  // MapLibre stamps `.maplibregl-map { position: relative }` onto this element
  // from its own stylesheet, which loads after Tailwind's utilities and wins.
  // That kills `absolute`, `inset-0` then sizes nothing, and the container
  // collapses to height 0 — a black map with no error anywhere.
  return (
    <div
      ref={containerRef}
      className="h-full w-full"
      style={{ background: COLOR.ground }}
    />
  );
}
