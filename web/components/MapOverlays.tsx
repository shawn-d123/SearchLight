"use client";

import { useEffect, useState } from "react";
import type { Map as MapLibreMap } from "maplibre-gl";
import type { CaseView, FieldView } from "@/lib/adapt";
import type { DemoState } from "@/lib/contract";

/**
 * Chart furniture: scale bar, north arrow, the ring's annotation, and the two
 * zone labels. All HTML positioned over the canvas rather than MapLibre symbol
 * layers, because the style ships no glyphs — which is what keeps the map
 * working with the network unplugged.
 */

/** Re-render on camera change. MapLibre fires `move` continuously during an
 *  ease, which is exactly when these need to keep up. */
function useMapTick(map: MapLibreMap | null) {
  const [, setTick] = useState(0);
  useEffect(() => {
    if (!map) return;
    const bump = () => setTick((n) => n + 1);
    map.on("move", bump);
    map.on("zoom", bump);
    bump();
    return () => {
      map.off("move", bump);
      map.off("zoom", bump);
    };
  }, [map]);
}

const NICE_M = [
  100, 200, 500, 1000, 2000, 5000, 10_000, 20_000, 50_000,
];

export function ScaleBar({ map }: { map: MapLibreMap | null }) {
  useMapTick(map);
  if (!map) return null;

  // Metres per pixel at the map's centre latitude.
  const lat = map.getCenter().lat;
  const mpp =
    (156543.03392 * Math.cos((lat * Math.PI) / 180)) / Math.pow(2, map.getZoom());

  const maxPx = 132;
  let metres = NICE_M[0];
  for (const m of NICE_M) if (m / mpp <= maxPx) metres = m;
  const px = Math.round(metres / mpp);
  const label = metres >= 1000 ? `${metres / 1000} km` : `${metres} m`;

  return (
    <div className="flex flex-col gap-1">
      <span
        className="eyebrow"
        style={{ color: "var(--bone-dim)" }}
      >
        {label}
      </span>
      <div
        style={{
          width: px,
          height: 5,
          borderLeft: "1px solid var(--bone-dim)",
          borderRight: "1px solid var(--bone-dim)",
          borderBottom: "1px solid var(--bone-dim)",
        }}
      />
    </div>
  );
}

export function NorthArrow() {
  // Rotation is disabled, so north is always up. Drawn anyway: a survey sheet
  // carries one, and its absence is more noticeable than its redundancy.
  return (
    <svg width="18" height="34" viewBox="0 0 18 34" fill="none" aria-label="North">
      <path d="M9 2 L14 20 L9 16 L4 20 Z" fill="var(--bone-dim)" />
      <text
        x="9"
        y="32"
        textAnchor="middle"
        fill="var(--bone-dim)"
        style={{ font: "600 11px var(--font-instrument), sans-serif", letterSpacing: "0.1em" }}
      >
        N
      </text>
    </svg>
  );
}

/**
 * The ring's annotation. State which quantile it is — an unlabelled circle
 * invites "where did that number come from?", and the answer is the strongest
 * part of the argument.
 */
export function RingLegend({ caseView }: { caseView: CaseView | null }) {
  if (!caseView) return null;
  return (
    <div className="flex items-center gap-2.5">
      <svg width="34" height="6" aria-hidden>
        <line
          x1="0"
          y1="3"
          x2="34"
          y2="3"
          stroke="var(--bone)"
          strokeWidth="1.4"
          strokeDasharray="5 4"
          opacity="0.75"
        />
      </svg>
      <span
        className="eyebrow"
        style={{ color: "var(--bone-dim)" }}
      >
        {caseView.ringLabel}
      </span>
    </div>
  );
}

/**
 * Two zone labels, and never more. The zone list beyond two rows is on the cut
 * list, and on a projector a third label is the one that overlaps the field.
 */
export function ZoneLabels({
  map,
  field,
  state,
}: {
  map: MapLibreMap | null;
  field: FieldView | null;
  state: DemoState;
}) {
  useMapTick(map);
  const show = state === "field_ready" || state === "evidence" || state === "validation";
  if (!map || !field || !show) return null;

  return (
    <>
      {field.zones.slice(0, 2).map((z, i) => {
        const p = map.project([z.centroid[1], z.centroid[0]]);
        if (!Number.isFinite(p.x) || !Number.isFinite(p.y)) return null;
        return (
          <div
            key={`${z.name}-${i}`}
            className="pointer-events-none absolute"
            style={{
              left: p.x,
              top: p.y,
              transform: "translate(-50%, -50%)",
            }}
          >
            <div className="flex flex-col items-center gap-1.5">
              <span
                style={{
                  width: 7,
                  height: 7,
                  border: "1px solid var(--bone)",
                  borderRadius: "50%",
                  background: "transparent",
                }}
              />
              <div
                className="whitespace-nowrap px-1.5 py-0.5 text-center"
                style={{ background: "rgba(20,19,14,0.72)" }}
              >
                <div
                  className="eyebrow"
                  style={{ color: "var(--bone)" }}
                >
                  {z.name}
                </div>
                <div
                  className="tabular text-[15px] font-semibold"
                  style={{ color: "var(--field-hot)" }}
                >
                  {z.pct.toFixed(1)}%
                </div>
              </div>
            </div>
          </div>
        );
      })}
    </>
  );
}
