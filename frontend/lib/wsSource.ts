import { WS_URL } from "./config";
import type { DemoState, Envelope } from "./contract";
import { Emitter, type Source } from "./source";

/**
 * The live orchestrator, over CONTRACT §9's WebSocket.
 *
 * Deliberately thin. It parses the envelope, checks the sequence for gaps, and
 * forwards. Every payload shape question is lib/adapt.ts's problem and every
 * demo-timing question is the reducer's, so flipping DATA_SOURCE to 'live'
 * changes the producer and nothing else.
 *
 * Reconnects on its own, because the one thing worse than a backend that drops
 * at 16:50 is a frontend that needs a page reload to notice it came back —
 * a reload also loses the demo's current state.
 */

const RECONNECT_MS = 1200;
const MAX_RECONNECT_MS = 8000;

export function createWsSource(url = WS_URL): Source {
  const bus = new Emitter();
  let socket: WebSocket | null = null;
  let retry = 0;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let closedByUs = false;
  let lastSeq = -1;

  /** Buffered until the socket opens, so an early keypress is not lost. */
  let pendingState: DemoState | null = null;

  function send(type: string, payload: unknown) {
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type, payload }));
      return true;
    }
    return false;
  }

  function open() {
    closedByUs = false;
    bus.setStatus("connecting", url);

    let ws: WebSocket;
    try {
      ws = new WebSocket(url);
    } catch (err) {
      bus.setStatus("error", String(err));
      scheduleReconnect();
      return;
    }
    socket = ws;

    ws.onopen = () => {
      retry = 0;
      lastSeq = -1;
      bus.setStatus("open", url);
      if (pendingState) {
        send("state_change", { state: pendingState });
        pendingState = null;
      }
    };

    ws.onmessage = (ev) => {
      let env: Envelope;
      try {
        env = JSON.parse(ev.data as string) as Envelope;
      } catch {
        console.warn("[ws] unparseable frame", String(ev.data).slice(0, 200));
        return;
      }
      if (!env || typeof env.type !== "string") {
        console.warn("[ws] frame with no type", env);
        return;
      }
      // A gap means a dropped message, which for trajectory_batch means paths
      // that will never be drawn. Worth a line in the console rather than a
      // silent hole in the field.
      if (typeof env.seq === "number") {
        if (lastSeq >= 0 && env.seq > lastSeq + 1) {
          console.warn(`[ws] seq gap: ${lastSeq} -> ${env.seq}`);
        }
        lastSeq = Math.max(lastSeq, env.seq);
      }
      bus.emit(env.type, env.payload, env.seq);
    };

    ws.onerror = () => bus.setStatus("error", url);

    ws.onclose = () => {
      socket = null;
      bus.setStatus("closed", url);
      if (!closedByUs) scheduleReconnect();
    };
  }

  function scheduleReconnect() {
    if (reconnectTimer) return;
    const delay = Math.min(MAX_RECONNECT_MS, RECONNECT_MS * 2 ** retry++);
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      open();
    }, delay);
  }

  return {
    kind: "live",

    connect() {
      open();
    },

    disconnect() {
      closedByUs = true;
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
      socket?.close();
      socket = null;
      bus.setStatus("closed");
    },

    enter(state) {
      bus.emit("state_change", { state });
      if (!send("state_change", { state })) pendingState = state;

      // The orchestrator does not start work on a state change alone — it waits
      // to be told. Two beats need an explicit command, and without them the
      // live demo sits on a still map while the presenter talks.
      //
      //   simulating -> `run`      kicks off hypotheses, fleet and the sim
      //   evidence   -> `evidence` runs the filter and emits evidence_applied
      //
      // Both are idempotent from our side: re-entering a state re-sends, which
      // is what a second rehearsal wants.
      // `evidence` is NOT sent here — see sendEvidence(). Its payload depends
      // on the field that has just been built.
      if (state === "simulating") send("run", {});
    },

    replayTranscript() {
      send("replay_transcript", {});
    },

    sendEvidence(evidence) {
      send("evidence", evidence);
    },

    on: (fn) => bus.on(fn),
    onStatus: (fn) => bus.onStatus(fn),
  };
}
