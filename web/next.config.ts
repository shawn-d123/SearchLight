import path from "node:path";
import { fileURLToPath } from "node:url";
import type { NextConfig } from "next";

// `import.meta.url`, not `__dirname`. Next compiles this file before loading
// it, and which module format it targets depends on which SWC binary loaded:
// the native one emits CommonJS, the WASM fallback emits ESM, where __dirname
// does not exist and the build dies with a ReferenceError before it starts.
// The fallback is not exotic — any machine whose OS blocks the unsigned native
// binary lands on it, which is where this was found.
const HERE = path.dirname(fileURLToPath(import.meta.url));

const nextConfig: NextConfig = {
  // Without this Next walks up past the repo looking for a lockfile and warns.
  // Pin it to the repo so the build output is the same on every machine.
  outputFileTracingRoot: path.join(HERE, ".."),

  // The dev indicator renders a badge at bottom-left, directly on top of the
  // scale bar, and it is visible on a projector if the demo is ever run with
  // `next dev`, which it will be. Compile and runtime errors still surface.
  devIndicators: false,
};

export default nextConfig;
