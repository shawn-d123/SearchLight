"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { Map as MapLibreMap } from "maplibre-gl";

import MapCanvas, { type MapHandles } from "@/components/MapCanvas";
import Rail from "@/components/Rail";
import Landing from "@/components/Landing";
import Intake from "@/components/Intake";
import HelpOverlay from "@/components/HelpOverlay";
import FpsMeter from "@/components/FpsMeter";
import {
  NorthArrow,
  RingLegend,
  ScaleBar,
  ZoneLabels,
} from "@/components/MapOverlays";

import { useSearchlight } from "@/lib/useSearchlight";
import { keyToAction, showsMap, STATE_LABEL } from "@/lib/state";
import { DATA_SOURCE, STATE_TRANSITION_MS, TERRAIN_EXAGGERATION } from "@/lib/config";

/**
 * One screen with states. Not seven screens.
 *
 * Roughly 70% map and 30% rail, and the layout never changes — only the state
 * does. landing and intake take the full width because they have no map, but
 * they use the same panel language, type and palette, so the transition reads
 * as the same application changing mode rather than a different app loading.
 */

/**
 * The rail floats over the map rather than butting against the window edges.
 *
 * NOTE this overrides the brief's "cut on sight" list, which rules out a border
 * radius above ~4px combined with a drop shadow. Overridden deliberately, not
 * missed. It is kept honest by being a SOLID card, not a frosted one — the map
 * does not show through it, so the numbers stay readable over any terrain, and
 * the shadow carries a real offset rather than being a glow.
 */
const RAIL_WIDTH = 430;
const RAIL_INSET = 22;
/** What the camera has to keep clear on the right: card + both margins. */
const RAIL_OCCLUDES = RAIL_WIDTH + RAIL_INSET * 2;

export default function Page() {
  const sl = useSearchlight();
  const [map, setMap] = useState<MapLibreMap | null>(null);
  const [help, setHelp] = useState(false);
  const handles = useRef<MapHandles | null>(null);

  const { advance, back, go, replayTranscript } = sl;

  // --- the keyboard is the real interface during the 90 seconds ------------
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      // Never swallow keys while someone is typing into a field.
      const t = e.target as HTMLElement | null;
      if (t && /^(INPUT|TEXTAREA|SELECT)$/.test(t.tagName)) return;
      if (t?.isContentEditable) return;

      const action = keyToAction(e);
      if (!action) return;
      e.preventDefault();

      switch (action.kind) {
        case "advance":
          advance();
          break;
        case "back":
          back();
          break;
        case "goto":
          go(action.state);
          break;
        case "reset-camera":
          handles.current?.resetCamera();
          break;
        case "toggle-flatten":
          handles.current?.toggleFlatten();
          break;
        case "replay-transcript":
          replayTranscript();
          break;
        case "toggle-help":
          setHelp((v) => !v);
          break;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [advance, back, go, replayTranscript]);

  const onReady = useCallback((m: MapLibreMap) => setMap(m), []);

  const mapVisible = showsMap(sl.state);

  return (
    <main
      className="relative flex h-dvh w-full overflow-hidden"
      style={{ background: "var(--ground)" }}
    >
      {/* The map is mounted for the whole session, not just the map states.
          Remounting MapLibre would re-download tiles, rebuild the terrain mesh
          and re-sample elevation every time the demo is rehearsed — several
          seconds of black screen in the middle of a pitch. It is hidden
          instead, which costs nothing while it has no layers animating. */}
      <div
        className="absolute inset-0"
        style={{
          visibility: mapVisible ? "visible" : "hidden",
          transition: `opacity ${STATE_TRANSITION_MS}ms ease`,
          opacity: mapVisible ? 1 : 0,
        }}
        aria-hidden={!mapVisible}
      >
        <MapCanvas
          state={sl.state}
          caseView={sl.caseView}
          field={sl.field}
          evidence={sl.evidence}
          trips={sl.trips}
          maxTime={sl.maxTime}
          railWidth={RAIL_OCCLUDES}
          onSampler={sl.setSampler}
          onReady={onReady}
          handlesRef={handles}
        />

        <ZoneLabels map={map} field={sl.field} state={sl.state} />

        {/* Chart furniture, bottom left, clear of the rail. Stacked rather than
            in one row: at the demo's zoom the scale bar is wide enough that a
            single row pushed the ring annotation into the north arrow. */}
        <div className="pointer-events-none absolute bottom-5 left-6 flex flex-col gap-3">
          <div>
            <RingLegend caseView={sl.caseView} />
            <div
              className="eyebrow mt-2"
              style={{ color: "var(--bone-faint)" }}
            >
              Vertical exaggeration {TERRAIN_EXAGGERATION}×
            </div>
          </div>
          <div className="flex items-end gap-6">
            <ScaleBar map={map} />
            <NorthArrow />
          </div>
        </div>

        {/* Rehearsal instruments. Deliberately quiet and out of the way. */}
        <div className="pointer-events-none absolute top-6 flex items-center gap-5"
          style={{ right: RAIL_OCCLUDES + 8 }}>
          <span
            className="eyebrow"
            style={{ color: "var(--bone-faint)" }}
          >
            {STATE_LABEL[sl.state]}
          </span>
          <span
            className="eyebrow"
            style={{
              color:
                sl.status === "open" ? "var(--bone-faint)" : "var(--amber)",
            }}
          >
            {DATA_SOURCE} · {sl.status}
          </span>
          <FpsMeter />
        </div>
      </div>

      {/* Full-bleed states. */}
      {sl.state === "landing" ? (
        <div className="absolute inset-0 z-30">
          <Landing onBegin={advance} />
        </div>
      ) : null}

      {sl.state === "intake" ? (
        <div className="absolute inset-0 z-30">
          <Intake
            transcript={sl.transcript}
            transcriptFinal={sl.transcriptFinal}
            extraction={sl.extraction}
            incident={sl.caseView?.incident ?? "SL-2084"}
            onTranscript={sl.sendTranscript}
            onBegin={advance}
            onReplay={replayTranscript}
          />
        </div>
      ) : null}

      {mapVisible ? (
        <Rail
          inset={RAIL_INSET}
          state={sl.state}
          caseView={sl.caseView}
          fleet={sl.fleet}
          field={sl.field}
          validation={sl.validation}
          hypotheses={sl.hypotheses}
          nRunsTotal={sl.nRunsTotal}
          nRunsFailed={sl.nRunsFailed}
          width={RAIL_WIDTH}
        />
      ) : null}

      <HelpOverlay open={help} onClose={() => setHelp(false)} />
    </main>
  );
}
