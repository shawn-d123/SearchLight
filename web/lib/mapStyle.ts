import type {
  ExpressionSpecification,
  RasterDEMSourceSpecification,
  StyleSpecification,
} from "maplibre-gl";
import {
  COLOR,
  CONTOURS_URL,
  TERRAIN_ENCODING,
  TERRAIN_MAX_ZOOM,
  TERRAIN_MIN_ZOOM,
  TERRAIN_TILE_SIZE,
  TERRAIN_TILE_URL,
  TRAILS_URL,
  WATER_URL,
} from "./config";

/**
 * A fully self-contained MapLibre style: no remote style JSON, no remote
 * glyphs, no basemap CDN. Everything it needs is the terrarium DEM and three
 * GeoJSON files, all served from public/. The map still renders with the wifi
 * unplugged — which matters, because the alternative is a black rectangle
 * under a working heightfield at 16:50.
 *
 * This replaces the CARTO dark-matter style the scaffold pointed at. That was
 * flagged as an unsolved network dependency and it was the frontend's call;
 * this is the call.
 *
 * NO GLYPHS AND NO SPRITE ON PURPOSE. Nothing here draws text or icons — every
 * label on screen is HTML positioned over the canvas, so there is no font
 * server to reach and no missing-glyph box to discover on stage.
 *
 * Two DEM sources pointing at the same tiles is deliberate, not waste: MapLibre
 * warns if one source drives both 3D terrain and a hillshade layer, because the
 * two want different overzoom behaviour. The tiles come off disk and are shared
 * by the HTTP cache, so the second source costs nothing.
 */

const dem = (): RasterDEMSourceSpecification => ({
  type: "raster-dem",
  tiles: [TERRAIN_TILE_URL],
  encoding: TERRAIN_ENCODING,
  tileSize: TERRAIN_TILE_SIZE,
  minzoom: TERRAIN_MIN_ZOOM,
  maxzoom: TERRAIN_MAX_ZOOM,
  attribution: "Elevation: Mapzen / AWS Terrain Tiles",
});

/**
 * `network_type='all'` over this box returned 105,236 walkable ways, 86,363 of
 * them northern Tucson's pavements. The display set is already cut to
 * path/track/bridleway/steps (14,750 ways, 3.4 MB), but the residential and
 * service spurs that survived still render as a dense white web across the
 * southern third of the frame — the built-up edge of the city, not terrain a
 * lost hiker walks. Dropping them puts the emphasis back on the mountains.
 *
 * `trail_dist` is still rasterised from the FULL 444k-edge network on the
 * worker side, because a subject walks a dirt road as readily as a marked
 * trail. This filter is about what is drawn, never about what is simulated.
 */
const TRAIL_FILTER: ExpressionSpecification = [
  "all",
  ["!", ["in", "residential", ["get", "highway"]]],
  ["!", ["in", "service", ["get", "highway"]]],
];

/** Layer ids other modules insert relative to. Kept here so the order is
 *  readable in one place rather than inferred from insertion calls. */
export const STYLE_LAYERS = {
  ground: "sl-ground",
  hillshade: "sl-hillshade",
  contour: "sl-contour",
  contourIndex: "sl-contour-index",
  water: "sl-water",
  trailCasing: "sl-trail-casing",
  trail: "sl-trail",
} as const;

export function buildMapStyle(): StyleSpecification {
  return {
    version: 8,
    sources: {
      terrain: dem(),
      hillshade: dem(),
      contours: { type: "geojson", data: CONTOURS_URL },
      trails: { type: "geojson", data: TRAILS_URL },
      water: { type: "geojson", data: WATER_URL },
    },
    layers: [
      {
        id: STYLE_LAYERS.ground,
        type: "background",
        paint: { "background-color": COLOR.ground },
      },
      {
        id: STYLE_LAYERS.hillshade,
        type: "hillshade",
        source: "hillshade",
        paint: {
          // Tuned against a near-black ground and a projector that will crush
          // dark greys further. This deliberately reads a little hot on a
          // laptop screen — the alternative is landform that vanishes entirely
          // in a dimmed room, which is the whole point of the map.
          "hillshade-exaggeration": 0.72,
          "hillshade-shadow-color": "#000000",
          "hillshade-highlight-color": "#6B6450",
          "hillshade-accent-color": "#443F2E",
          "hillshade-illumination-direction": 315,
          "hillshade-illumination-anchor": "map",
        },
      },
      {
        id: STYLE_LAYERS.contour,
        type: "line",
        source: "contours",
        filter: ["!", ["get", "index"]],
        // The demo camera sits at zoom ~10.6. Anything that only fades in past
        // 12 is invisible for the entire pitch, which is how the first pass of
        // these lines managed to render at 4% opacity throughout.
        minzoom: 9.8,
        paint: {
          "line-color": "#5A5440",
          "line-width": ["interpolate", ["linear"], ["zoom"], 9.8, 0.4, 14, 0.8],
          "line-opacity": ["interpolate", ["linear"], ["zoom"], 9.8, 0.22, 11.5, 0.5],
        },
      },
      {
        id: STYLE_LAYERS.contourIndex,
        type: "line",
        source: "contours",
        filter: ["get", "index"],
        paint: {
          // Every fifth line brighter — standard practice, and what makes the
          // pattern read as intentional cartography rather than texture.
          "line-color": "#847C5E",
          "line-width": ["interpolate", ["linear"], ["zoom"], 9, 0.7, 14, 1.3],
          "line-opacity": ["interpolate", ["linear"], ["zoom"], 9, 0.55, 12, 0.9],
        },
      },
      {
        id: STYLE_LAYERS.water,
        type: "line",
        source: "water",
        paint: {
          // Barely cooler than the bone linework — enough to separate drainage
          // from trail at a glance, not enough to register as "a colour". The
          // field is the only saturated thing on screen, and at the first pass
          // these read as distinctly blue against the warm ground.
          "line-color": "#5C6360",
          "line-width": ["interpolate", ["linear"], ["zoom"], 9, 0.4, 14, 1.2],
          "line-opacity": ["interpolate", ["linear"], ["zoom"], 9, 0.35, 13, 0.6],
        },
      },
      {
        id: STYLE_LAYERS.trailCasing,
        type: "line",
        source: "trails",
        minzoom: 10.2,
        filter: TRAIL_FILTER,
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          // Dark casing under a bright line so trails hold up over busy ground.
          // Without it they disappear wherever contours cross them.
          "line-color": COLOR.ground,
          "line-width": ["interpolate", ["linear"], ["zoom"], 10.2, 1.3, 14, 3.2],
          "line-opacity": 0.85,
        },
      },
      {
        id: STYLE_LAYERS.trail,
        type: "line",
        source: "trails",
        minzoom: 10.2,
        filter: TRAIL_FILTER,
        layout: { "line-cap": "round", "line-join": "round" },
        paint: {
          // Trails are context, not the subject. In the first pass these were
          // the highest-contrast thing on screen and the terrain read as mush
          // underneath them — the landform has to lead, because the whole
          // argument is that the field follows it.
          "line-color": "#9C9682",
          "line-width": ["interpolate", ["linear"], ["zoom"], 10.2, 0.45, 14, 1.1],
          "line-opacity": ["interpolate", ["linear"], ["zoom"], 10.2, 0.34, 13, 0.7],
        },
      },
    ],
    // Terrain is attached in MapCanvas via setTerrain rather than declared here.
    // Declaring it in the style AND setting it on style.load races, and MapLibre
    // throws reading `elevation` off a terrain object that is not built yet.
  };
}
