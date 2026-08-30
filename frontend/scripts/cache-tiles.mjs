/**
 * Cache terrarium terrain tiles locally for the Santa Catalina Mountains.
 *
 * Venue wifi at 16:50 is not something to rely on, and a demo that can't load
 * terrain is not a demo. Run once with a network connection; after that the
 * map renders offline.
 *
 *   node scripts/cache-tiles.mjs
 *   node scripts/cache-tiles.mjs --minzoom 8 --maxzoom 14
 *
 * Bounds default to CACHE_BOUNDS in lib/config.ts — keep the two in step. They
 * are data/bbox.json padded outward, because MapLibre loads a buffer beyond the
 * viewport and terrain needs neighbouring tiles to compute slope at the edges.
 *
 * maxzoom MUST match TERRAIN_MAX_ZOOM in lib/config.ts. Set that higher than
 * what is on disk and MapLibre 404s past the cache and the terrain goes flat
 * SILENTLY, with no error to chase.
 */
import { mkdir, writeFile, access } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT_ROOT = join(HERE, "..", "public", "tiles", "terrarium");
const REMOTE = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium";

// Mirrors CACHE_BOUNDS in lib/config.ts. data/bbox.json padded outward.
const DEFAULTS = {
  north: 32.67,
  south: 32.11,
  east: -110.49,
  west: -111.17,
  minzoom: 8,
  maxzoom: 13,
  concurrency: 16,
  // Extra ring of tiles around the box, in tiles rather than degrees.
  // MapLibre loads a buffer beyond the visible viewport, and terrain needs
  // neighbours to compute slope at the edges, so a box sized exactly to the
  // demo area still 404s along its border at every zoom.
  margin: 2,
};

/**
 * SECOND PASS — low zoom over a much wider box. Insurance, not a fix.
 *
 * At pitch 57 the camera sees far past the demo bounding box. The low zooms of
 * the first pass already cover a lot of that incidentally (one z8 tile spans
 * ~1.4°, and `margin` adds two more in each direction), so distant terrain
 * mostly renders without this. What this guarantees is that panning at pitch —
 * the one interaction the demo allows during questions — cannot run off the
 * edge of the DEM.
 *
 * It is z8-11 only, because distant ground is drawn at low zoom: ~330 extra
 * tiles and 33 MB, against the several hundred MB that extending z12-13 across
 * the same area would cost.
 *
 * NOT the fix for the probability field tearing at pitch. That was chased here
 * first and it was the wrong tree: the cause was MapLibre's `canvas` source
 * failing to drape, and the fix is the `image` source in lib/field.ts. Drop
 * this pass if the repo size matters more than pan headroom.
 */
const HORIZON = {
  north: 33.3,
  south: 31.6,
  east: -109.8,
  west: -111.9,
  minzoom: 8,
  maxzoom: 11,
};

function parseArgs() {
  const out = { ...DEFAULTS };
  const argv = process.argv.slice(2);
  for (let i = 0; i < argv.length; i += 2) {
    const key = argv[i].replace(/^--/, "");
    if (key in out) out[key] = Number(argv[i + 1]);
  }
  return out;
}

const lonToX = (lon, z) => Math.floor(((lon + 180) / 360) * 2 ** z);
const latToY = (lat, z) => {
  const r = (lat * Math.PI) / 180;
  return Math.floor(
    ((1 - Math.log(Math.tan(r) + 1 / Math.cos(r)) / Math.PI) / 2) * 2 ** z,
  );
};

function enumerateTiles(cfg) {
  const tiles = [];
  for (let z = cfg.minzoom; z <= cfg.maxzoom; z++) {
    const span = 2 ** z;
    const clamp = (v) => Math.max(0, Math.min(span - 1, v));
    const x0 = clamp(lonToX(cfg.west, z) - cfg.margin);
    const x1 = clamp(lonToX(cfg.east, z) + cfg.margin);
    const y0 = clamp(latToY(cfg.north, z) - cfg.margin); // north edge is smaller y
    const y1 = clamp(latToY(cfg.south, z) + cfg.margin);
    for (let x = x0; x <= x1; x++) {
      for (let y = y0; y <= y1; y++) tiles.push({ z, x, y });
    }
  }
  return tiles;
}

const exists = (p) => access(p).then(() => true).catch(() => false);

async function fetchTile({ z, x, y }, attempt = 1) {
  const dest = join(OUT_ROOT, String(z), String(x), `${y}.png`);
  if (await exists(dest)) return { status: "cached", bytes: 0 };
  try {
    const res = await fetch(`${REMOTE}/${z}/${x}/${y}.png`);
    if (!res.ok) {
      // 404 past the dataset's max zoom for a given area is expected, not a failure.
      if (res.status === 404) return { status: "missing", bytes: 0 };
      throw new Error(`HTTP ${res.status}`);
    }
    const buf = Buffer.from(await res.arrayBuffer());
    await mkdir(dirname(dest), { recursive: true });
    await writeFile(dest, buf);
    return { status: "fetched", bytes: buf.length };
  } catch (err) {
    if (attempt < 4) {
      await new Promise((r) => setTimeout(r, 250 * attempt));
      return fetchTile({ z, x, y }, attempt + 1);
    }
    return { status: "failed", bytes: 0, err: String(err) };
  }
}

async function main() {
  const cfg = parseArgs();
  // Both passes, deduplicated. The horizon pass is skipped only if the caller
  // narrowed the box by hand, because then they are doing something specific.
  const explicit = process.argv.length > 2;
  const seen = new Set();
  const tiles = [];
  for (const pass of explicit ? [cfg] : [cfg, { ...cfg, ...HORIZON }]) {
    for (const t of enumerateTiles(pass)) {
      const k = `${t.z}/${t.x}/${t.y}`;
      if (seen.has(k)) continue;
      seen.add(k);
      tiles.push(t);
    }
  }
  console.log(
    `terrarium z${cfg.minzoom}-${cfg.maxzoom} over ` +
      `[${cfg.south},${cfg.west}] .. [${cfg.north},${cfg.east}]` +
      (explicit
        ? ""
        : ` + horizon z${HORIZON.minzoom}-${HORIZON.maxzoom} over ` +
          `[${HORIZON.south},${HORIZON.west}] .. [${HORIZON.north},${HORIZON.east}]`) +
      ` → ${tiles.length} tiles`,
  );

  const tally = { fetched: 0, cached: 0, missing: 0, failed: 0 };
  let bytes = 0;
  let cursor = 0;
  const failures = [];

  async function worker() {
    while (cursor < tiles.length) {
      const tile = tiles[cursor++];
      const r = await fetchTile(tile);
      tally[r.status]++;
      bytes += r.bytes;
      if (r.status === "failed") failures.push({ ...tile, err: r.err });
      const done = tally.fetched + tally.cached + tally.missing + tally.failed;
      if (done % 100 === 0 || done === tiles.length) {
        process.stdout.write(
          `\r  ${done}/${tiles.length}  ${(bytes / 1e6).toFixed(1)} MB`,
        );
      }
    }
  }

  await Promise.all(
    Array.from({ length: cfg.concurrency }, () => worker()),
  );

  console.log(
    `\ndone — fetched ${tally.fetched}, already cached ${tally.cached}, ` +
      `absent upstream ${tally.missing}, failed ${tally.failed} ` +
      `(${(bytes / 1e6).toFixed(1)} MB)`,
  );
  if (failures.length) {
    console.log("failed tiles (re-run to retry):");
    for (const f of failures.slice(0, 10)) console.log(`  ${f.z}/${f.x}/${f.y} ${f.err}`);
    process.exitCode = 1;
  }
}

main();
