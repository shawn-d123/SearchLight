# Frontend dependency decisions

Three pins that look like arbitrary version choices and are not. Each cost time
to find. **Do not bump them without re-running `npm run verify`.**

## 1. `maplibre-gl` is `~5.24.0`, not 6.x

The scaffold shipped `^6.6.0`. With MapLibre 6, `MapboxOverlay` from
`@deck.gl/mapbox` throws

```
Cannot read properties of undefined (reading 'elevation')
```

on **every frame**, and the map renders black. Isolated by disabling the deck
overlay — the errors vanish and the map comes back. deck.gl 9.3 declares no
maplibre peer range, so npm will happily install a version that does not work
and nothing warns you.

`~5.24.0` rather than `^5.24.0` because a minor bump is exactly the kind of
change that would reintroduce this quietly.

## 2. `next dev --webpack`, not Turbopack

MapLibre 6 loads its worker via `import.meta.url`, which Turbopack cannot
resolve; the request 404s to Next's HTML error page and the browser rejects it
on MIME type. Less relevant now we are on v5, but the webpack path is the one
that has actually been exercised end to end.

## 3. The scoped `@deck.gl/*` packages, not the `deck.gl` umbrella

The umbrella pulls in `@arcgis/core`, which drags `@vaadin/*` packages that run
postinstall scripts phoning home. Dropping it took `node_modules` from ~1.0 GB
to ~677 MB and removed a package running code nobody asked for. We import from
`@deck.gl/core`, `@deck.gl/layers`, `@deck.gl/geo-layers` and `@deck.gl/mapbox`
directly.

## 4. The field is an `image` source, not a `canvas` source

Not a dependency, but the same category of trap: a thing that looks like a free
choice and is not.

`canvas` is the natural source type for a surface that repaints in place, and it
renders correctly at pitch 0. At pitch 57 over terrain it **tears into
hard-edged polygons**. Swapping in an `image` source with byte-identical pixels
and identical coordinates, on the same map at the same camera, drapes cleanly.

Ruled out along the way: tile residency (`areTilesLoaded` was `true`), the size
of the source quad (a 40%-linear quad tore the same way), and the number of
updates (a single update tore too).

The cost is that `updateImage` only takes a URL, so each change is a PNG encode.
`lib/field.ts` therefore cross-fades two image layers — one encode per
`field_update`, and the 800 ms transition is pure `raster-opacity`.

## Also removed

`react-map-gl` — unused. MapLibre is created imperatively in
`components/MapCanvas.tsx` and deck.gl attaches to it as a control, so there is
no React wrapper in the path and nothing for it to do.

## Things that are not dependencies, deliberately

- **No basemap CDN.** `lib/mapStyle.ts` is a self-contained style: terrain from
  cached tiles, contours/trails/water from `public/data`. The scaffold pointed
  at CARTO's dark-matter style, which meant a black basemap under working
  terrain on a dead network. That was flagged as the frontend's call; this is
  the call.
- **No glyph or sprite server.** Nothing in the style draws text or icons —
  every label is HTML over the canvas. A remote glyph URL would reintroduce the
  network dependency the local style just removed.
- **No font CDN at runtime.** `next/font/google` self-hosts Archivo and IBM Plex
  Mono at build time.

The map renders with the wifi unplugged. That is the point.
