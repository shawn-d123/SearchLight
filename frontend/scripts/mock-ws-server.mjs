/**
 * A reference orchestrator: replays the committed mocks over a real WebSocket
 * in exactly the CONTRACT §9 envelope shape.
 *
 *   npm run ws            # ws://localhost:8000/ws
 *   npm run ws -- --port 8123 --speed 2
 *
 * WHY THIS EXISTS — it is doing three jobs at once.
 *
 * 1. It proves the frontend's live path works. Until this existed, every byte
 *    `lib/wsSource.ts` had ever seen came from the in-process mock replayer, so
 *    "flip DATA_SOURCE to live" was an untested claim. Now it can be run for
 *    real, today, against something that is not the thing being tested.
 *
 * 2. It is an executable spec for Person B. Prose contracts get read once and
 *    misremembered; this is a working server emitting the exact frames the
 *    frontend expects, so the orchestrator can be diffed against it. If B's
 *    server drives this frontend the same way this one does, integration is
 *    done. Run both on different ports and compare.
 *
 * 3. It is the fallback. If the orchestrator is not ready at 14:30, or dies at
 *    16:50, the demo still runs end to end against this with DATA_SOURCE=live —
 *    and it is honest about being canned, because it says so on every connect.
 *
 * WHAT IT DELIBERATELY DOES NOT DO: it does not simulate anything. There is no
 * terrain, no sandbox, no KDE. It reads files Person C generated and posts them
 * on a timer. Its only claim is about the wire format.
 */
import { readFile } from "node:fs/promises";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { WebSocketServer } from "ws";

const HERE = dirname(fileURLToPath(import.meta.url));
const MOCKS = join(HERE, "..", "public", "mocks");

const args = process.argv.slice(2);
const flag = (name, fallback) => {
  const i = args.indexOf(`--${name}`);
  return i >= 0 && args[i + 1] ? args[i + 1] : fallback;
};
const PORT = Number(flag("port", 8000));
/** >1 runs the script faster, for rehearsing without waiting. */
const SPEED = Number(flag("speed", 1));

const FLEET_TICK_MS = 500; // CONTRACT §9: "every 500ms while running"
const RUNS_PER_MESSAGE = 200; // CONTRACT §9: "batched, max 200 runs per message"
const SWEEP_MS = 13_000;

const readJson = async (name) => {
  try {
    return JSON.parse(await readFile(join(MOCKS, name), "utf8"));
  } catch {
    return null;
  }
};

const data = {
  case: await readJson("case.json"),
  simStarted: await readJson("sim_started.json"),
  fleet: (await readJson("fleet_status.json")) ?? [],
  // The stress fixture if it has been generated, else the committed set.
  batches:
    (await readJson("trajectories_12k.json")) ??
    (await readJson("trajectories.json")) ??
    [],
  fieldPartial: await readJson("field_partial.json"),
  field: await readJson("field.json"),
  fieldCollapsed: await readJson("field_collapsed.json"),
  validation: await readJson("validation_result.json"),
  transcript: await readFile(join(MOCKS, "transcript.txt"), "utf8").catch(() => ""),
  extraction: await readJson("extraction.json"),
};

const totalRuns = data.batches.reduce((n, b) => n + (b.runs?.length ?? 0), 0);

/** Pre-split the trajectories once, to the contract's per-message cap. */
const CHUNKS = (() => {
  const out = [];
  let cur = [];
  let runs = 0;
  for (const b of data.batches) {
    cur.push(b);
    runs += b.runs?.length ?? 0;
    if (runs >= RUNS_PER_MESSAGE) {
      out.push(cur);
      cur = [];
      runs = 0;
    }
  }
  if (cur.length) out.push(cur);
  return out;
})();

const wss = new WebSocketServer({ port: PORT, path: "/ws" });

console.log(
  `reference orchestrator on ws://localhost:${PORT}/ws  (speed ${SPEED}x)\n` +
    `  ${data.batches.length} batches / ${totalRuns.toLocaleString()} runs ` +
    `-> ${CHUNKS.length} trajectory_batch frames\n` +
    `  fleet frames ${data.fleet.length}, field frames ` +
    `${[data.fieldPartial, data.field, data.fieldCollapsed].filter(Boolean).length}\n` +
    `  THIS IS CANNED DATA. It proves the wire format, nothing else.`,
);

wss.on("connection", (socket) => {
  let seq = 0;
  const timers = [];
  const send = (type, payload) => {
    if (socket.readyState !== socket.OPEN) return;
    socket.send(JSON.stringify({ type, seq: seq++, payload }));
  };
  const at = (ms, fn) => timers.push(setTimeout(fn, ms / SPEED));
  const clear = () => {
    for (const t of timers.splice(0)) clearTimeout(t);
  };

  console.log("client connected");
  if (data.case) send("case_loaded", data.case);

  const playIntake = () => {
    const words = String(data.transcript).split(/\s+/).filter(Boolean);
    // Mirrors TRANSCRIPT_* in lib/config.ts — this file cannot import TS.
    const PER_TICK = 2;
    const TICK_MS = 150;
    const ticks = Math.ceil(words.length / PER_TICK);
    for (let i = 0; i < ticks; i++) {
      const upto = Math.min(words.length, (i + 1) * PER_TICK);
      at(150 + i * TICK_MS, () =>
        send("transcript_partial", {
          text: words.slice(0, upto).join(" "),
          is_final: upto >= words.length,
        }),
      );
    }
    const ex = data.extraction;
    if (!ex) return;
    const spoken = 150 + ticks * TICK_MS;
    const steps = [
      { subject: { name: ex.subject?.name } },
      { subject: ex.subject },
      { last_known: ex.last_known },
      { assessment: ex.assessment, confidence: ex.confidence },
    ];
    const from = spoken * 0.5;
    const every = (spoken * 0.5 + 700) / steps.length;
    steps.forEach((s, i) => at(from + i * every, () => send("extraction_update", s)));
  };

  const playSimulating = () => {
    if (data.simStarted) send("sim_started", data.simStarted);
    data.fleet.forEach((f, i) => at(i * FLEET_TICK_MS, () => send("fleet_status", f)));
    const every = Math.max(60, (SWEEP_MS * 0.55) / Math.max(1, CHUNKS.length));
    CHUNKS.forEach((c, i) =>
      at(120 + i * every, () => send("trajectory_batch", { batches: c })),
    );
    if (data.fieldPartial) at(SWEEP_MS * 0.3, () => send("field_update", data.fieldPartial));
    if (data.field) at(SWEEP_MS * 0.78, () => send("field_update", data.field));
  };

  const enter = (state) => {
    clear();
    switch (state) {
      case "intake":
        playIntake();
        break;
      case "simulating":
        playSimulating();
        break;
      case "field_ready":
        if (data.field) send("field_update", data.field);
        break;
      case "evidence":
        if (data.fieldCollapsed) send("evidence_applied", data.fieldCollapsed);
        break;
      case "validation":
        if (data.validation) send("validation_result", data.validation);
        break;
      default:
        break; // landing, briefing: nothing to stream
    }
  };

  socket.on("message", (raw) => {
    let msg;
    try {
      msg = JSON.parse(raw.toString());
    } catch {
      console.warn("  ! unparseable frame from client");
      return;
    }
    // The frontend drives the script; the orchestrator follows. If B decides it
    // should be the other way round, this is the line that changes — and that
    // decision needs making out loud, because both ends currently assume this.
    if (msg?.type === "state_change") {
      console.log(`  <- state_change ${msg.payload?.state}`);
      enter(msg.payload?.state);
    } else if (msg?.type === "replay_transcript") {
      clear();
      playIntake();
    } else {
      console.warn(`  ! unrecognised client frame: ${msg?.type}`);
    }
  });

  socket.on("close", () => {
    clear();
    console.log("client disconnected");
  });
});
