"use client";

// Scaffold only. Person A owns the visual direction -- this exists so nobody
// loses an hour tomorrow to the deck.gl / MapLibre camera integration, which
// is the part that reliably eats time if you have not done it before.
//
// What it proves works:
//   - MapLibre dark basemap over the real bounding box
//   - Terrarium terrain-RGB heightfield, exaggeration as one constant
//   - rotation disabled, pitch flat, ready to be raised
//   - TripsLayer animating the mock trajectories
//   - the field decoded from base64 and DRAPED via a MapLibre image source
//
// Deliberately unstyled beyond a dark ground.

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import Map, { useControl, type MapRef } from "react-map-gl/maplibre";
import { MapboxOverlay } from "@deck.gl/mapbox";
import { TripsLayer } from "@deck.gl/geo-layers";
import { ScatterplotLayer } from "@deck.gl/layers";
import "maplibre-gl/dist/maplibre-gl.css";

import {
  BASEMAP_STYLE,
  BOUNDS,
  DATA_SOURCE,
  EXAGGERATION,
  INITIAL_VIEW,
  MOCKS,
  TERRAIN_ENCODING,
  TERRAIN_TILES,
} from "@/lib/config";
import {
  batchesToTrips,
  boundsToCoordinates,
  decodeGrid,
  gridToCanvas,
  type Batch,
  type FieldPayload,
  type Trip,
} from "@/lib/field";

const FIELD_SOURCE = "field-source";
const FIELD_LAYER = "field-layer";
const RING_SOURCE = "ring-source";

function DeckOverlay(props: { layers: unknown[] }) {
  const overlay = useControl(() => new MapboxOverlay({ interleaved: false }));
  // @ts-expect-error deck.gl types accept a heterogeneous layer array
  overlay.setProps(props);
  return null;
}

/** Circle as a GeoJSON polygon. The ring is naive by design -- it is the thing
 *  being argued against -- but it must be labelled with its quantile. An
 *  unlabelled circle invites "where did that number come from?" */
function ringPolygon(centre: [number, number], radiusM: number, steps = 128) {
  const [lat, lon] = centre;
  const dLat = radiusM / 110574;
  const dLon = radiusM / (111320 * Math.cos((lat * Math.PI) / 180));
  const ring: Array<[number, number]> = [];
  for (let i = 0; i <= steps; i++) {
    const a = (i / steps) * 2 * Math.PI;
    ring.push([lon + dLon * Math.cos(a), lat + dLat * Math.sin(a)]);
  }
  return {
    type: "Feature" as const,
    properties: {},
    geometry: { type: "Polygon" as const, coordinates: [ring] },
  };
}

export default function Home() {
  const mapRef = useRef<MapRef | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [trips, setTrips] = useState<Trip[]>([]);
  const [maxTime, setMaxTime] = useState(1);
  const [time, setTime] = useState(0);
  const [field, setField] = useState<FieldPayload | null>(null);
  const [caseInfo, setCaseInfo] = useState<{
    subject_name: string;
    ipp: [number, number];
    ring_radius_m: number;
    ring_label: string;
    region: string;
  } | null>(null);
  const [status, setStatus] = useState("loading mocks...");

  // --- data ---------------------------------------------------------------
  useEffect(() => {
    if (DATA_SOURCE !== "mock") {
      setStatus("DATA_SOURCE is 'live' -- connect the orchestrator WS");
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const [c, t, f] = await Promise.all([
          fetch(MOCKS.case).then((r) => r.json()),
          fetch(MOCKS.trajectories).then((r) => r.json()),
          fetch(MOCKS.field).then((r) => r.json()),
        ]);
        if (cancelled) return;
        setCaseInfo(c);
        const { trips, nTotal, nFailed, maxTime } = batchesToTrips(t as Batch[]);
        setTrips(trips);
        setMaxTime(maxTime || 1);
        setField(f as FieldPayload);
        setStatus(
          `${trips.length} paths - ${nFailed}/${nTotal} failed - field ${(
            f as FieldPayload
          ).field_area_pct}% of ring`,
        );
      } catch (e) {
        setStatus(`mock load failed: ${(e as Error).message}`);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  // --- animation ----------------------------------------------------------
  useEffect(() => {
    if (!trips.length) return;
    let raf = 0;
    const loop = () => {
      // ~90 s of subject time per second of wall clock; the paths are the only
      // fast-moving thing on screen.
      setTime((t) => (t + maxTime / 600) % (maxTime * 1.15));
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [trips, maxTime]);

  // --- map setup ----------------------------------------------------------
  const onLoad = useCallback(() => {
    const map = mapRef.current?.getMap();
    if (!map) return;

    // A wrong bearing hides the bright zone behind a ridge. Spec section 13.
    map.dragRotate.disable();
    map.touchZoomRotate.disableRotation();

    if (!map.getSource("terrain")) {
      map.addSource("terrain", {
        type: "raster-dem",
        tiles: [TERRAIN_TILES],
        encoding: TERRAIN_ENCODING,
        tileSize: 256,
        maxzoom: 14,
      });
      // Pitch is 0 tonight, so terrain is invisible -- but wiring it now means
      // raising the camera later is one constant, not a rewrite.
      map.setTerrain({ source: "terrain", exaggeration: EXAGGERATION });
    }
  }, []);

  // --- field as a draped image source -------------------------------------
  useEffect(() => {
    const map = mapRef.current?.getMap();
    if (!map || !field) return;
    const add = () => {
      const grid = decodeGrid(field.grid, field.resolution);
      // Repaint the SAME canvas element every update. The source holds a
      // reference to it, so new pixels appear without re-adding the layer --
      // which matters once C is streaming field_update roughly every second.
      canvasRef.current = gridToCanvas(
        grid,
        field.resolution,
        canvasRef.current ?? undefined,
      );
      if (map.getSource(FIELD_SOURCE)) {
        map.triggerRepaint();
        return;
      }
      map.addSource(FIELD_SOURCE, {
        type: "canvas",
        canvas: canvasRef.current,
        coordinates: boundsToCoordinates(field.bounds),
        // animate:true re-uploads the texture each frame. At 256x256 that is
        // ~256 KB and negligible, and it is what makes streamed updates show
        // up at all. Set false only if the field is known to be static.
        animate: true,
      });
      map.addLayer({
        id: FIELD_LAYER,
        type: "raster",
        source: FIELD_SOURCE,
        paint: { "raster-opacity": 0.85, "raster-resampling": "linear" },
      });
    };
    if (map.isStyleLoaded()) add();
    else map.once("load", add);
  }, [field]);

  // --- ring ---------------------------------------------------------------
  useEffect(() => {
    const map = mapRef.current?.getMap();
    if (!map || !caseInfo) return;
    const add = () => {
      if (map.getSource(RING_SOURCE)) return;
      map.addSource(RING_SOURCE, {
        type: "geojson",
        data: ringPolygon(caseInfo.ipp, caseInfo.ring_radius_m),
      });
      map.addLayer({
        id: "ring-line",
        type: "line",
        source: RING_SOURCE,
        paint: {
          "line-color": "#d8d2c4", // bone, not white
          "line-width": 1.2,
          "line-dasharray": [4, 3],
          "line-opacity": 0.8,
        },
      });
    };
    if (map.isStyleLoaded()) add();
    else map.once("load", add);
  }, [caseInfo]);

  // --- deck layers --------------------------------------------------------
  const layers = useMemo(() => {
    const out: unknown[] = [];
    if (trips.length) {
      out.push(
        new TripsLayer({
          id: "trips",
          data: trips,
          getPath: (d: Trip) => d.path,
          getTimestamps: (d: Trip) => d.timestamps,
          getColor: [255, 176, 74],
          opacity: 0.6,
          widthMinPixels: 1.4,
          trailLength: maxTime * 0.28,
          currentTime: time,
          // Do NOT drape the paths. Floating above the ground looks better and
          // avoids z-fighting where lines flicker in and out of hillsides.
          parameters: { depthTest: false },
        }),
      );
    }
    if (caseInfo) {
      out.push(
        new ScatterplotLayer({
          id: "ipp",
          data: [caseInfo],
          getPosition: (d: typeof caseInfo) => [d.ipp[1], d.ipp[0]],
          getFillColor: [232, 226, 212],
          getRadius: 90,
          radiusMinPixels: 4,
          parameters: { depthTest: false },
        }),
      );
    }
    return out;
  }, [trips, time, maxTime, caseInfo]);

  return (
    <main style={{ position: "fixed", inset: 0, background: "#14140f" }}>
      <Map
        ref={mapRef}
        initialViewState={INITIAL_VIEW}
        mapStyle={BASEMAP_STYLE}
        onLoad={onLoad}
        maxBounds={[
          BOUNDS.west - 0.35,
          BOUNDS.south - 0.35,
          BOUNDS.east + 0.35,
          BOUNDS.north + 0.35,
        ]}
        style={{ width: "100%", height: "100%" }}
      >
        <DeckOverlay layers={layers} />
      </Map>

      <div
        style={{
          position: "absolute",
          left: 12,
          bottom: 12,
          padding: "8px 10px",
          font: "12px ui-monospace, monospace",
          color: "#d8d2c4",
          background: "rgba(20,20,15,0.82)",
          whiteSpace: "pre-line",
        }}
      >
        {[
          caseInfo?.region ?? BOUNDS.region,
          caseInfo ? `${caseInfo.subject_name} - ${caseInfo.ring_label}` : "",
          status,
          `DATA_SOURCE=${DATA_SOURCE}  pitch=${INITIAL_VIEW.pitch}  exaggeration=${EXAGGERATION}`,
        ]
          .filter(Boolean)
          .join("\n")}
      </div>
    </main>
  );
}
