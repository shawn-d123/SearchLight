"use client";

import { useEffect, useState } from "react";
import { TARGET_FPS } from "@/lib/config";

/**
 * Frame rate over a rolling second.
 *
 * The 12,000-path question is a number, not a vibe: either it holds on the
 * presenting laptop at venue resolution or it does not, and if it does not we
 * render a visible subset while the full set stays in the data. Also worth
 * watching because on battery the GPU throttles and the frame rate halves.
 *
 * Hidden during the pitch — it is a rehearsal instrument, not part of the demo.
 */
export default function FpsMeter() {
  const [fps, setFps] = useState(0);
  const [low, setLow] = useState(999);

  useEffect(() => {
    // Reads the scene's own frame counter, incremented by the throttled clock
    // in MapCanvas. Not rAF (fires at display refresh whether or not anything
    // was drawn) and not MapLibre's `render` (never fires for path frames,
    // because deck.gl runs its own loop in overlaid mode).
    const w = window as unknown as { __frames?: number };
    let last = performance.now();
    let lastCount = w.__frames ?? 0;
    let raf = 0;
    const tick = () => {
      const now = performance.now();
      if (now - last >= 1000) {
        const count = w.__frames ?? 0;
        const v = Math.round(((count - lastCount) * 1000) / (now - last));
        setFps(v);
        // Ignore the first seconds — startup and data loading skew them. Also
        // ignore zero: the clock only runs while paths are on screen.
        setLow((prev) => (now > 4000 && v > 0 ? Math.min(prev, v) : prev));
        lastCount = count;
        last = now;
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  const colour =
    fps >= TARGET_FPS - 3
      ? "var(--bone-dim)"
      : fps >= 20
        ? "var(--amber)"
        : "var(--field-hot)";

  return (
    <span className="tabular text-[12px] font-medium" style={{ color: colour }}>
      {fps} fps{low < 999 ? ` · min ${low}` : ""}
    </span>
  );
}
