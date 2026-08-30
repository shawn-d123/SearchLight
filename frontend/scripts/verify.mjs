/**
 * Drive the whole demo in a real Chrome window and record what it actually does.
 *
 * This exists because "it looked fine on my screen" is not a check you can run
 * again at 16:00 under pressure. It uses the system Chrome (channel: 'chrome')
 * so the GPU is the real one — a software-rendered frame rate would be
 * meaningless for the 12,000-path question.
 *
 *   npm run verify                 # headed, real GPU, trustworthy fps
 *   npm run verify -- --headless
 *   VERIFY_URL=http://localhost:3000 npm run verify
 *
 * Screenshots land in verification/. Re-run it on the PRESENTING laptop at
 * venue resolution before trusting any of the numbers, and plug in — on battery
 * the GPU throttles and the frame rate halves.
 */
import { chromium } from "playwright";
import { mkdir, writeFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const OUT = join(HERE, "..", "verification");
const URL_BASE = process.env.VERIFY_URL ?? "http://localhost:3000";
const HEADLESS = process.argv.includes("--headless");

/**
 * The demo, beat by beat. `settle` is how long to wait for tiles, the camera
 * ease and the field interpolation before judging the frame.
 */
const STEPS = [
  { key: "1", file: "1-landing", settle: 1200, needsMap: false },
  { key: "2", file: "2-intake", settle: 7500, needsMap: false },
  { key: "3", file: "3-briefing", settle: 3000 },
  { key: "4", file: "4-simulating", settle: 7000, measureFps: true },
  { key: "5", file: "5-field-ready", settle: 3000 },
  { key: "6", file: "6-evidence", settle: 3000 },
  { key: "7", file: "7-validation", settle: 2500 },
  { key: "3", file: "8-briefing-flat", settle: 2500, flatten: true },
];

/**
 * Count the frames the scene actually draws over `ms`.
 *
 * Deliberately neither requestAnimationFrame nor MapLibre's `render` event:
 * rAF fires at the display refresh rate whether or not anything was drawn (it
 * reported a confident 60 while the scene was capped at 30), and `render` never
 * fires for path frames because deck.gl runs its own canvas and loop in
 * overlaid mode (it reported 0 while paths were plainly animating).
 * `window.__frames` is incremented by the throttled clock in MapCanvas, so it
 * is the only counter that tracks what is on screen.
 */
const measure = (ms) =>
  new Promise((resolve) => {
    const w = window;
    const start = w.__frames ?? 0;
    const t0 = performance.now();
    setTimeout(() => {
      const drawn = (w.__frames ?? 0) - start;
      resolve(Math.round((drawn * 1000) / (performance.now() - t0)));
    }, ms);
  });

async function main() {
  await mkdir(OUT, { recursive: true });

  const browser = await chromium.launch({
    channel: "chrome",
    headless: HEADLESS,
    args: HEADLESS ? ["--enable-unsafe-swiftshader"] : [],
  });
  const page = await browser.newPage({
    viewport: { width: 1600, height: 900 },
    deviceScaleFactor: 1,
  });

  const errors = [];
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text().slice(0, 200));
  });
  page.on("pageerror", (e) => errors.push(`pageerror: ${String(e).slice(0, 200)}`));
  page.on("crash", () => {
    errors.push("*** RENDERER CRASHED ***");
    console.error("*** RENDERER CRASHED ***");
  });

  await page.goto(URL_BASE, { waitUntil: "networkidle", timeout: 180_000 });

  // Wait for MapLibre to report a loaded style rather than guessing with sleeps.
  await page.waitForFunction(() => window.__map && window.__map.isStyleLoaded(), null, {
    timeout: 60_000,
  });
  // ...and for the DEM to actually have tiles, which is what terrain needs.
  await page
    .waitForFunction(() => window.__map.isSourceLoaded("terrain"), null, { timeout: 60_000 })
    .catch(() => console.warn("  ! DEM source never reported loaded"));

  const results = [];
  for (const step of STEPS) {
    process.stdout.write(`  ${step.file.padEnd(20)} `);
    await page.keyboard.press(step.key);
    if (step.flatten) await page.keyboard.press("f");
    await page.waitForTimeout(step.settle);

    const fps = step.measureFps ? await page.evaluate(measure, 3000) : null;
    // The 12k stress fixture is 12 MB; a busy page can exceed the default
    // screenshot timeout. Loading slowly is acceptable, hanging is not.
    await page.screenshot({ path: join(OUT, `${step.file}.png`), timeout: 120_000 });

    // Is the map canvas actually painting, or is it a black rectangle?
    const ink =
      step.needsMap === false
        ? null
        : await page.evaluate(() => {
            const c = document.querySelector(".maplibregl-canvas");
            if (!c) return null;
            const g = document.createElement("canvas");
            g.width = 160;
            g.height = 90;
            const ctx = g.getContext("2d");
            ctx.drawImage(c, 0, 0, 160, 90);
            const d = ctx.getImageData(0, 0, 160, 90).data;
            const seen = new Set();
            let sum = 0;
            for (let i = 0; i < d.length; i += 4) {
              sum += d[i] + d[i + 1] + d[i + 2];
              seen.add(`${d[i] >> 4},${d[i + 1] >> 4},${d[i + 2] >> 4}`);
            }
            return {
              meanLuma: +(sum / (d.length / 4) / 3).toFixed(1),
              distinctColours: seen.size,
            };
          });

    const camera = await page.evaluate(() => ({
      pitch: Math.round(window.__map.getPitch()),
      zoom: +window.__map.getZoom().toFixed(2),
      bearing: Math.round(window.__map.getBearing()),
    }));

    results.push({ step: step.file, fps, camera, ...(ink ?? {}) });
    console.log(
      `pitch ${String(camera.pitch).padStart(2)} zoom ${String(camera.zoom).padStart(5)}` +
        (ink ? `  luma ${String(ink.meanLuma).padStart(5)}  colours ${String(ink.distinctColours).padStart(4)}` : "  (no map)") +
        (fps === null ? "" : `  ${fps} fps`),
    );
  }

  const samplerMs = await page.evaluate(() => window.__samplerMs ?? null);

  await writeFile(
    join(OUT, "results.json"),
    JSON.stringify({ results, samplerMs, errors }, null, 2),
  );

  console.log(`\nelevation sampler built in ${samplerMs?.toFixed?.(0) ?? "?"} ms`);
  console.log(`console errors: ${errors.length}`);
  for (const e of errors.slice(0, 8)) console.log(`  ${e}`);

  await browser.close();
  // A bearing other than 0 means rotation lock failed, which would let a wrong
  // camera hide the bright zone on stage. Treat it as a failure, not a note.
  const rotated = results.find((r) => r.camera.bearing !== 0);
  if (rotated) {
    console.error(`\n!! bearing is ${rotated.camera.bearing} at ${rotated.step}`);
    process.exitCode = 1;
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
