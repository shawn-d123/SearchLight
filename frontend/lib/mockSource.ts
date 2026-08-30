import {
  MOCKS,
  TRANSCRIPT_TICK_MS,
  TRANSCRIPT_WORDS_PER_TICK,
  TRIPS_SWEEP_S,
} from "./config";
import type { DemoState, FieldUpdate, TrajectoryBatch } from "./contract";
import {
  Emitter,
  Timeline,
  fetchJson,
  fetchText,
  type Source,
} from "./source";

/**
 * Replays the committed mocks as CONTRACT §9 envelopes.
 *
 * This is not a stub to be thrown away at 14:30. It is the thing that lets the
 * whole frontend — state machine, rail, field interpolation, camera, path
 * animation — be built and rehearsed before the orchestrator exists, and it
 * stays useful afterwards as the fallback when the backend is down. The demo
 * must be able to run with zero successful generations; it must also be able to
 * run with zero backend.
 *
 * The timings below are the demo's beats, not arbitrary. §13's script gives
 * paths at 0:18, "same statistics, a fraction of the area" at 0:35, the witness
 * at 0:50. The simulating state has to fill about that much time on its own.
 */

const FLEET_TICK_MS = 500; // CONTRACT §9: "every 500ms while running"
const RUNS_PER_MESSAGE = 200; // CONTRACT §9: "batched, max 200 runs per message"

interface Loaded {
  case: unknown;
  simStarted: unknown;
  fleet: unknown[];
  batches: TrajectoryBatch[];
  fieldPartial: FieldUpdate | null;
  field: FieldUpdate | null;
  fieldCollapsed: FieldUpdate | null;
  validation: unknown;
  transcript: string;
  extraction: Record<string, unknown> | null;
}

export function createMockSource(): Source {
  const bus = new Emitter();
  let timeline = new Timeline();
  let data: Loaded | null = null;
  let loading: Promise<Loaded> | null = null;

  async function load(): Promise<Loaded> {
    if (data) return data;
    if (loading) return loading;

    loading = (async () => {
      // Stress fixture first: Person A must judge frame rate against 12,000
      // runs, not the 2,400 the repo ships. Absent on a clean clone, so fall
      // back rather than failing to start.
      const stress = await fetchJson<TrajectoryBatch[]>(MOCKS.trajectories12k);
      const batches =
        stress ?? (await fetchJson<TrajectoryBatch[]>(MOCKS.trajectories)) ?? [];

      const [
        caseJson,
        simStarted,
        fleet,
        fieldPartial,
        field,
        fieldCollapsed,
        validation,
        transcript,
        extraction,
      ] = await Promise.all([
        fetchJson<unknown>(MOCKS.case),
        fetchJson<unknown>(MOCKS.simStarted),
        fetchJson<unknown[]>(MOCKS.fleetStatus),
        fetchJson<FieldUpdate>(MOCKS.fieldPartial),
        fetchJson<FieldUpdate>(MOCKS.field),
        fetchJson<FieldUpdate>(MOCKS.fieldCollapsed),
        fetchJson<unknown>(MOCKS.validation),
        fetchText(MOCKS.transcript),
        fetchJson<Record<string, unknown>>(MOCKS.extraction),
      ]);

      data = {
        case: caseJson,
        simStarted,
        fleet: fleet ?? [],
        batches,
        fieldPartial,
        field,
        fieldCollapsed,
        validation,
        transcript: transcript ?? "",
        extraction,
      };
      if (stress) console.info("[mock] using the 12k stress fixture");
      return data;
    })();

    return loading;
  }

  /** The call, transcribed a word at a time, then the fields resolving. */
  function playIntake(d: Loaded) {
    const words = d.transcript.split(/\s+/).filter(Boolean);
    if (!words.length) return;

    // Emitted in small word groups, the way real recognition arrives, rather
    // than one word at a time. Ninety seconds is the whole pitch; a transcript
    // that takes twenty-five of them to read itself out is not affordable.
    const ticks = Math.ceil(words.length / TRANSCRIPT_WORDS_PER_TICK);
    timeline.repeat(150, TRANSCRIPT_TICK_MS, ticks, (i) => {
      const upto = Math.min(words.length, (i + 1) * TRANSCRIPT_WORDS_PER_TICK);
      bus.emit("transcript_partial", {
        text: words.slice(0, upto).join(" "),
        is_final: upto >= words.length,
      });
    });

    const spoken = 150 + ticks * TRANSCRIPT_TICK_MS;
    const ex = d.extraction;
    if (!ex) return;

    // Fields populate one at a time as extraction returns, not all at once.
    // That staggering is the visual payoff of the transcription.
    const steps: Array<Record<string, unknown>> = [
      { subject: { name: (ex.subject as Record<string, unknown>)?.name } },
      { subject: ex.subject },
      { last_known: ex.last_known },
      { assessment: ex.assessment, confidence: ex.confidence },
    ];

    // Resolution starts partway through the call, not after it. A real
    // streaming extraction does not wait for the caller to stop talking, and
    // a report that sits empty for twenty-five seconds and then fills at once
    // gives the presenter nothing to point at while the call plays.
    const from = spoken * 0.5;
    const every = (spoken * 0.5 + 700) / steps.length;
    timeline.repeat(from, every, steps.length, (i) => {
      bus.emit("extraction_update", steps[i]);
    });
  }

  function playSimulating(d: Loaded) {
    if (d.simStarted) bus.emit("sim_started", d.simStarted);

    // Fleet counter: the only thing on screen proving real machines are
    // working. Ticks at the contract's cadence for as long as the mock has
    // frames, then holds on the last one.
    timeline.repeat(0, FLEET_TICK_MS, d.fleet.length, (i) => {
      bus.emit("fleet_status", d.fleet[i]);
    });

    // Trajectories arrive in chunks while the fleet is still working, so the
    // field starts forming early rather than appearing at the end.
    const chunks: TrajectoryBatch[][] = [];
    let runs = 0;
    let current: TrajectoryBatch[] = [];
    for (const b of d.batches) {
      current.push(b);
      runs += b.runs.length;
      if (runs >= RUNS_PER_MESSAGE) {
        chunks.push(current);
        current = [];
        runs = 0;
      }
    }
    if (current.length) chunks.push(current);

    const sweepMs = TRIPS_SWEEP_S * 1000;
    const chunkEvery = Math.max(60, (sweepMs * 0.55) / Math.max(1, chunks.length));
    timeline.repeat(120, chunkEvery, chunks.length, (i) => {
      bus.emit("trajectory_batch", { batches: chunks[i] });
    });

    // The field accumulates: a vague smear that sharpens into distinct zones.
    // Two real updates is enough to read as growth, because the renderer
    // interpolates between them over 800 ms.
    if (d.fieldPartial) timeline.at(sweepMs * 0.3, () => bus.emit("field_update", d.fieldPartial));
    if (d.field) timeline.at(sweepMs * 0.78, () => bus.emit("field_update", d.field));
  }

  function replay(state: DemoState, d: Loaded) {
    switch (state) {
      case "landing":
        break;
      case "intake":
        playIntake(d);
        break;
      case "briefing":
        // case_loaded already went out on connect; the ring and marker are
        // drawn from it. Nothing further to send.
        break;
      case "simulating":
        playSimulating(d);
        break;
      case "field_ready":
        // Ensure the settled field is on screen even if the operator skipped
        // ahead before the simulating timeline finished.
        if (d.field) bus.emit("field_update", d.field);
        break;
      case "evidence":
        if (d.fieldCollapsed) bus.emit("evidence_applied", d.fieldCollapsed);
        break;
      case "validation":
        if (d.validation) bus.emit("validation_result", d.validation);
        break;
    }
  }

  return {
    kind: "mock",

    connect() {
      bus.setStatus("connecting");
      load()
        .then((d) => {
          bus.setStatus("open", "mocks");
          if (d.case) bus.emit("case_loaded", d.case);
        })
        .catch((err) => bus.setStatus("error", String(err)));
    },

    disconnect() {
      timeline.cancel();
      bus.setStatus("closed");
    },

    enter(state) {
      // Cancel the previous state's pending steps first. Advancing early must
      // not leave timers firing into a state that has moved on.
      timeline.cancel();
      timeline = new Timeline();
      bus.emit("state_change", { state });
      load().then((d) => replay(state, d));
    },

    // The mock replays a pre-computed field_collapsed.json, so it has nothing
    // to do with a live witness report.
    sendEvidence() {},

    replayTranscript() {
      timeline.cancel();
      timeline = new Timeline();
      load().then((d) => playIntake(d));
    },

    on: (fn) => bus.on(fn),
    onStatus: (fn) => bus.onStatus(fn),
  };
}
