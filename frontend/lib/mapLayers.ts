import type { GeoJSONSource, Map as MapLibreMap } from "maplibre-gl";
import type { LatLon } from "./contract";
import type { EvidenceView } from "./adapt";
import { ringPath } from "./geometry";
import { COLOR } from "./config";

/**
 * Ground-hugging features live in MapLibre, not deck.gl.
 *
 * MapLibre drapes its own line and circle layers onto the terrain mesh for
 * free. deck.gl layers do not — they render in a separate pass at whatever z
 * they are given, and `_TerrainExtension` (an experimental underscored export
 * in deck.gl 9.3) draws nothing at all in overlaid mode. Verified on the prep
 * build: a deck.gl PathLayer across a steep slope floats flat over the ridges.
 *
 * So the split is:
 *   ring, markers, trails, contours, probability field -> MapLibre
 *   animated trajectories                              -> deck.gl, lifted
 *
 * Everything here is added once and toggled with `visibility`, because adding
 * and removing sources mid-demo is a good way to find a new bug on stage.
 *
 * These layers are added AFTER the field attaches, so they draw on top of it.
 * The ring in particular must stay legible through the brightest part of the
 * surface — it is the comparison the whole pitch rests on.
 */

export const LAYERS = {
  ring: "sl-ring-line",
  ippHalo: "sl-ipp-halo",
  ippDot: "sl-ipp-dot",
  evidenceRadius: "sl-evidence-radius",
  evidenceHalo: "sl-evidence-halo",
  evidenceDot: "sl-evidence-dot",
} as const;

const SOURCES = {
  ring: "sl-ring",
  ipp: "sl-ipp",
  evidence: "sl-evidence",
  evidenceRadius: "sl-evidence-radius",
} as const;

const point = (lat: number, lon: number): GeoJSON.Feature => ({
  type: "Feature",
  properties: {},
  geometry: { type: "Point", coordinates: [lon, lat] },
});

const lineString = (coords: [number, number][]): GeoJSON.Feature => ({
  type: "Feature",
  properties: {},
  geometry: { type: "LineString", coordinates: coords },
});

/** ISRID ring and the last known point. Added once, updated in place. */
export function addCaseLayers(map: MapLibreMap, ipp: LatLon, radiusM: number) {
  map.addSource(SOURCES.ring, {
    type: "geojson",
    data: lineString(ringPath(ipp, radiusM)),
  });
  map.addLayer({
    id: LAYERS.ring,
    type: "line",
    source: SOURCES.ring,
    paint: {
      // A survey feature: thin, dashed, bone. Naive by design. State the
      // quantile in the label — an unlabelled circle invites "where did that
      // number come from?"
      "line-color": COLOR.bone,
      "line-width": 1.4,
      "line-opacity": 0.75,
      "line-dasharray": [5, 4],
    },
  });

  map.addSource(SOURCES.ipp, { type: "geojson", data: point(ipp[0], ipp[1]) });
  map.addLayer({
    id: LAYERS.ippHalo,
    type: "circle",
    source: SOURCES.ipp,
    paint: {
      // A ringed dot, not an icon. No emoji, no pin graphic — they are the
      // fastest way to make a serious tool look like a template.
      "circle-radius": 9,
      "circle-color": "rgba(0,0,0,0)",
      "circle-stroke-width": 1.5,
      "circle-stroke-color": COLOR.bone,
    },
  });
  map.addLayer({
    id: LAYERS.ippDot,
    type: "circle",
    source: SOURCES.ipp,
    paint: { "circle-radius": 3, "circle-color": COLOR.bone },
  });
}

export function updateCase(map: MapLibreMap, ipp: LatLon, radiusM: number) {
  const ring = map.getSource(SOURCES.ring) as GeoJSONSource | undefined;
  ring?.setData(lineString(ringPath(ipp, radiusM)));
  const p = map.getSource(SOURCES.ipp) as GeoJSONSource | undefined;
  p?.setData(point(ipp[0], ipp[1]));
}

/** The witness sighting. Amber, and the only amber thing on the map. */
export function addEvidenceLayers(map: MapLibreMap) {
  map.addSource(SOURCES.evidenceRadius, {
    type: "geojson",
    data: { type: "FeatureCollection", features: [] },
  });
  map.addSource(SOURCES.evidence, {
    type: "geojson",
    data: { type: "FeatureCollection", features: [] },
  });

  map.addLayer({
    id: LAYERS.evidenceRadius,
    type: "line",
    source: SOURCES.evidenceRadius,
    paint: {
      "line-color": COLOR.amber,
      "line-width": 1,
      "line-opacity": 0.5,
      "line-dasharray": [2, 3],
    },
  });
  map.addLayer({
    id: LAYERS.evidenceHalo,
    type: "circle",
    source: SOURCES.evidence,
    paint: {
      "circle-radius": 10,
      "circle-color": "rgba(0,0,0,0)",
      "circle-stroke-width": 1.5,
      "circle-stroke-color": COLOR.amber,
    },
  });
  map.addLayer({
    id: LAYERS.evidenceDot,
    type: "circle",
    source: SOURCES.evidence,
    paint: { "circle-radius": 3.5, "circle-color": COLOR.amber },
  });

  setEvidenceVisible(map, false);
}

export function updateEvidence(map: MapLibreMap, e: EvidenceView) {
  const dot = map.getSource(SOURCES.evidence) as GeoJSONSource | undefined;
  dot?.setData(point(e.lat, e.lon));
  const radius = map.getSource(SOURCES.evidenceRadius) as
    | GeoJSONSource
    | undefined;
  radius?.setData(
    e.radiusM > 0
      ? lineString(ringPath([e.lat, e.lon], e.radiusM))
      : { type: "FeatureCollection", features: [] },
  );
}

const setVisible = (map: MapLibreMap, ids: string[], visible: boolean) => {
  for (const id of ids) {
    if (map.getLayer(id)) {
      map.setLayoutProperty(id, "visibility", visible ? "visible" : "none");
    }
  }
};

export const setCaseVisible = (map: MapLibreMap, visible: boolean) =>
  setVisible(map, [LAYERS.ring, LAYERS.ippHalo, LAYERS.ippDot], visible);

export const setEvidenceVisible = (map: MapLibreMap, visible: boolean) =>
  setVisible(
    map,
    [LAYERS.evidenceRadius, LAYERS.evidenceHalo, LAYERS.evidenceDot],
    visible,
  );
