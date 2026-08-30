import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Without this Next walks up past the repo looking for a lockfile and warns.
  // Pin it to the repo so the build output is the same on every machine.
  outputFileTracingRoot: path.join(__dirname, ".."),

  // The dev indicator renders a badge at bottom-left — directly on top of the
  // scale bar, and visible on the projector if the demo is ever run with
  // `next dev`, which it will be. Compile and runtime errors still surface.
  devIndicators: false,
};

export default nextConfig;
