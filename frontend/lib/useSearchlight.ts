"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  DATA_SOURCE,
  DEMO_EVIDENCE,
  N_PATHS_RENDERED,
  PATH_ALTITUDE_M,
} from "./config";
import { STATES } from "./contract";
import type {
  DemoState,
  Envelope,
  Extraction,
  Hypothesis,
  TrajectoryBatch,
  TrajectoryBatchMessage,
} from "./contract";
import {
  EMPTY_FLEET,
  defaultCaseView,
  normaliseCase,
  normaliseField,
  normaliseFleet,
  normaliseHypotheses,
  normaliseValidation,
  type CaseView,
  type EvidenceView,
  type FieldView,
  type FleetView,
  type ValidationView,
} from "./adapt";
import { batchesToTrips, type Trip } from "./trips";
import { createMockSource } from "./mockSource";
import { createWsSource } from "./wsSource";
import type { Source, SourceStatus } from "./source";
import { FIRST_STATE, nextState, prevState } from "./state";
import type { ElevationSampler } from "./elevation";

/**
 * The single reducer between the wire and the screen.
 *
 * Everything on screen is derived from envelopes, whichever producer sent them.
 * No component fetches, and no component parses — they receive view models.
 *
 * The elevation sampler arrives asynchronously (it needs DEM tiles in memory),
 * so trips are converted with whatever sampler exists at the time and
 * recomputed exactly once when it first becomes available. Recomputing on every
 * batch would be 12 passes over 12,000 paths for no visible gain.
 */

export interface SearchlightState {
  state: DemoState;
  status: SourceStatus;
  statusDetail?: string;

  caseView: CaseView | null;
  fleet: FleetView;
  hypotheses: Hypothesis[];
  nPlanned: number;

  trips: Trip[];
  nRunsTotal: number;
  nRunsFailed: number;
  maxTime: number;

  field: FieldView | null;
  evidence: EvidenceView | null;
  validation: ValidationView | null;

  transcript: string;
  transcriptFinal: boolean;
  /** Partial extraction, merged as fields resolve. Drives the intake report,
   *  which must NOT read from caseView — that arrives complete on connect. */
  extraction: Partial<Extraction>;
}

export interface SearchlightApi extends SearchlightState {
  go(state: DemoState): void;
  advance(): void;
  back(): void;
  replayTranscript(): void;
  /** Called by the map once the DEM is sampled. */
  setSampler(s: ElevationSampler | null): void;
}

const INITIAL: SearchlightState = {
  state: FIRST_STATE,
  status: "idle",
  // Seeded, not null: the ring and the marker must be on screen before the
  // orchestrator says anything. See defaultCaseView().
  caseView: defaultCaseView(),
  fleet: EMPTY_FLEET,
  hypotheses: [],
  nPlanned: 0,
  trips: [],
  nRunsTotal: 0,
  nRunsFailed: 0,
  maxTime: 0,
  field: null,
  evidence: null,
  validation: null,
  transcript: "",
  transcriptFinal: false,
  extraction: {},
};

export function useSearchlight(): SearchlightApi {
  const [s, setS] = useState<SearchlightState>(INITIAL);

  const sourceRef = useRef<Source | null>(null);
  const samplerRef = useRef<ElevationSampler | null>(null);
  /** Raw batches, kept so trips can be recomputed once the sampler lands. */
  const batchesRef = useRef<TrajectoryBatch[]>([]);

  const lift = useCallback(
    () =>
      samplerRef.current
        ? (lat: number, lon: number) => samplerRef.current!.at(lat, lon)
        : undefined,
    [],
  );

  // --- source lifecycle ----------------------------------------------------
  useEffect(() => {
    const source =
      DATA_SOURCE === "live" ? createWsSource() : createMockSource();
    sourceRef.current = source;

    const offStatus = source.onStatus((status, statusDetail) =>
      setS((p) => ({ ...p, status, statusDetail })),
    );

    const off = source.on((env: Envelope) => {
      switch (env.type) {
        case "case_loaded": {
          const caseView = normaliseCase(env.payload);
          setS((p) => ({ ...p, caseView }));
          break;
        }

        case "transcript_partial": {
          const t = env.payload as { text: string; is_final: boolean };
          setS((p) => ({
            ...p,
            transcript: t.text,
            transcriptFinal: Boolean(t.is_final),
          }));
          break;
        }

        case "extraction_update": {
          const patch = env.payload as Record<string, unknown>;
          setS((p) => {
            const extraction: Record<string, unknown> = { ...p.extraction };
            for (const [k, v] of Object.entries(patch)) {
              const prev = extraction[k];
              // Merge one level down: extraction arrives as {subject:{name}}
              // then {subject:{...everything}}, and replacing wholesale would
              // make a resolved field flicker back to empty.
              extraction[k] =
                prev && typeof prev === "object" && v && typeof v === "object"
                  ? { ...(prev as object), ...(v as object) }
                  : v;
            }
            // Once the assessment lands the extraction is a complete §8
            // payload, so the case view can be built from it directly.
            const caseView =
              "assessment" in extraction || "last_known" in extraction
                ? normaliseCase({ ...p.caseView, ...extraction })
                : p.caseView;
            return { ...p, extraction: extraction as Partial<Extraction>, caseView };
          });
          break;
        }

        case "sim_started": {
          const payload = env.payload as { n_planned?: number };
          setS((p) => ({
            ...p,
            hypotheses: normaliseHypotheses(env.payload),
            nPlanned: payload?.n_planned ?? p.nPlanned,
          }));
          break;
        }

        case "fleet_status":
          setS((p) => ({ ...p, fleet: normaliseFleet(env.payload) }));
          break;

        case "trajectory_batch": {
          const msg = env.payload as TrajectoryBatchMessage | TrajectoryBatch[];
          const incoming = Array.isArray(msg) ? msg : (msg?.batches ?? []);
          if (!incoming.length) break;
          batchesRef.current = batchesRef.current.concat(incoming);

          setS((p) => {
            // Convert only the new chunk and append. The cap is on what is
            // drawn; the counts stay honest because they come from every run.
            const room = Math.max(0, N_PATHS_RENDERED - p.trips.length);
            const chunk = batchesToTrips(
              incoming,
              PATH_ALTITUDE_M,
              room,
              lift(),
            );
            return {
              ...p,
              trips: room > 0 ? p.trips.concat(chunk.trips) : p.trips,
              nRunsTotal: p.nRunsTotal + chunk.nTotal,
              nRunsFailed: p.nRunsFailed + chunk.nFailed,
              maxTime: Math.max(p.maxTime, chunk.maxTime),
            };
          });
          break;
        }

        case "field_update":
          setS((p) => ({ ...p, field: normaliseField(env.payload) }));
          break;

        case "evidence_applied": {
          const field = normaliseField(env.payload);
          setS((p) => ({
            ...p,
            field,
            evidence: field.evidence ?? p.evidence,
          }));
          break;
        }

        case "validation_result":
          setS((p) => ({ ...p, validation: normaliseValidation(env.payload) }));
          break;

        case "state_change": {
          // The orchestrator drives the state too, and it must be allowed to:
          // when the pipeline finishes it emits `field_ready` itself, and that
          // is the only moment that genuinely knows the field is complete.
          // It also echoes our own `state_change` back, so this has to be a
          // no-op when it matches where we already are, or the echo would fight
          // the presenter's keypress.
          const next = (env.payload as { state?: DemoState })?.state;
          if (next && STATES.includes(next)) {
            setS((p) => (p.state === next ? p : { ...p, state: next }));
            stateRef.current = next;
          }
          break;
        }

        default:
          // Unknown types are ignored on purpose so the orchestrator can add
          // messages without breaking the screen. `log` is the exception: it
          // carries pipeline errors and silently swallowing those during
          // integration is how an afternoon disappears.
          if (env.type === ("log" as string)) {
            console.warn("[orchestrator]", env.payload);
          }
          break;
      }
    });

    source.connect();
    source.enter(FIRST_STATE);

    return () => {
      off();
      offStatus();
      source.disconnect();
      sourceRef.current = null;
    };
  }, [lift]);

  // --- navigation ----------------------------------------------------------
  // The current state is mirrored into a ref so advance/back can read it
  // without a setState updater. Deriving it inside an updater looks tidier but
  // React may invoke that updater twice, and `enter()` is a side effect — a
  // double call replays the mock timeline twice and the paths animate at
  // double density from a doubled trajectory stream.
  const stateRef = useRef<DemoState>(s.state);
  stateRef.current = s.state;
  /** The field as last received, so the witness report can be aimed at it. */
  const fieldRef = useRef<FieldView | null>(s.field);
  fieldRef.current = s.field;

  const go = useCallback((state: DemoState) => {
    if (stateRef.current === state) return;
    stateRef.current = state;

    setS((p) => {
      // Re-entering briefing means a fresh run: drop what the last one built,
      // so a second rehearsal starts from exactly where the first did.
      if (state === "briefing") {
        batchesRef.current = [];
        return {
          ...p,
          state,
          trips: [],
          nRunsTotal: 0,
          nRunsFailed: 0,
          maxTime: 0,
          field: null,
          evidence: null,
          fleet: EMPTY_FLEET,
          hypotheses: [],
        };
      }
      return { ...p, state };
    });
    sourceRef.current?.enter(state);

    if (state === "evidence") sourceRef.current?.sendEvidence(buildEvidence());
  }, []);

  /**
   * Where the witness saw them.
   *
   * The location CANNOT be a fixed coordinate. The hypotheses are regenerated
   * on every run, so the trajectories land somewhere different each time; a
   * hardcoded sighting eventually falls where no simulation went, the filter
   * discards everything, and the model raises "grid sums to zero - no
   * probability mass to enclose". That happened live: the evidence beat did
   * nothing at all and the field never updated.
   *
   * So the report is aimed at the field that was actually produced — the
   * highest-probability zone. That is not cheating the demo: the witness is
   * fictional either way, and a sighting somewhere people plausibly go is more
   * realistic than one in empty desert. The filter is still doing real work,
   * discarding every run that was not near that point at that time.
   *
   * Falls back to the configured coordinate when there are no zones yet.
   */
  const buildEvidence = useCallback((): Record<string, unknown> => {
    const zone = fieldRef.current?.zones?.[0];
    return {
      ...DEMO_EVIDENCE,
      lat: zone ? zone.centroid[0] : DEMO_EVIDENCE.lat,
      lon: zone ? zone.centroid[1] : DEMO_EVIDENCE.lon,
    };
  }, []);

  const advance = useCallback(() => go(nextState(stateRef.current)), [go]);
  const back = useCallback(() => go(prevState(stateRef.current)), [go]);

  const replayTranscript = useCallback(() => {
    setS((p) => ({ ...p, transcript: "", transcriptFinal: false, extraction: {} }));
    sourceRef.current?.replayTranscript();
  }, []);

  // --- elevation -----------------------------------------------------------
  const setSampler = useCallback((sampler: ElevationSampler | null) => {
    const first = !samplerRef.current && sampler;
    samplerRef.current = sampler;
    if (!first || !batchesRef.current.length) return;

    // The sampler just became available and paths are already on screen at sea
    // level. Recompute once, in place.
    setS((p) => {
      const all = batchesToTrips(
        batchesRef.current,
        PATH_ALTITUDE_M,
        N_PATHS_RENDERED,
        (lat, lon) => sampler!.at(lat, lon),
      );
      return { ...p, trips: all.trips };
    });
  }, []);

  return useMemo(
    () => ({ ...s, go, advance, back, replayTranscript, setSampler }),
    [s, go, advance, back, replayTranscript, setSampler],
  );
}
