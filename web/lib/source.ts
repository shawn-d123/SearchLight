import type { DataSource } from "./config";
import type { DemoState, Envelope } from "./contract";

/**
 * One envelope stream, two producers.
 *
 * The live orchestrator sends CONTRACT §9 envelopes over a WebSocket. The mock
 * source synthesises the *same envelopes* from the committed JSON files. So the
 * application reduces exactly one message shape and has no idea which producer
 * it is talking to — which is what makes 14:30 a config flip rather than a
 * debugging session, and what stops the mock path rotting the moment live data
 * shows up.
 *
 * `enter(state)` is the one concession to the demo being keyboard-driven rather
 * than wall-clock driven. Live maps it to a `state_change` sent up the socket,
 * so the orchestrator stays in step with the presenter. Mock maps it to
 * replaying that state's slice of the script.
 */

export type Listener = (e: Envelope) => void;

export type SourceStatus =
  | "idle"
  | "connecting"
  | "open"
  | "closed"
  | "error";

export interface Source {
  readonly kind: DataSource;
  connect(): void;
  disconnect(): void;
  /** The demo advanced. Replay or announce, depending on the producer. */
  enter(state: DemoState): void;
  /** Re-run the intake transcript without changing state. The T key. */
  replayTranscript(): void;
  /**
   * The witness report. Separate from enter() because the payload depends on
   * the field that has just been built, which only the reducer knows.
   */
  sendEvidence(evidence: Record<string, unknown>): void;
  /**
   * Words from the live microphone, going UP the socket.
   *
   * Live relays them to every client and, on is_final, runs the extraction --
   * which must happen server-side, because a browser holding the OpenAI key is
   * a published key. Mock has no microphone and ignores it.
   */
  sendTranscript(payload: { text: string; is_final: boolean }): void;
  on(fn: Listener): () => void;
  onStatus(fn: (s: SourceStatus, detail?: string) => void): () => void;
}

/** Shared emitter plumbing, so both producers behave identically. */
export class Emitter {
  private listeners = new Set<Listener>();
  private statusListeners = new Set<(s: SourceStatus, d?: string) => void>();
  private seq = 0;
  status: SourceStatus = "idle";

  on(fn: Listener) {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  }

  onStatus(fn: (s: SourceStatus, d?: string) => void) {
    this.statusListeners.add(fn);
    fn(this.status);
    return () => this.statusListeners.delete(fn);
  }

  setStatus(s: SourceStatus, detail?: string) {
    this.status = s;
    for (const fn of this.statusListeners) fn(s, detail);
  }

  /** Emit an envelope with a locally assigned seq. Live overrides seq with the
   *  server's, because gaps there are diagnostic. */
  emit<T>(type: Envelope["type"], payload: T, seq?: number) {
    const env: Envelope<T> = { type, seq: seq ?? this.seq++, payload };
    for (const fn of this.listeners) fn(env as Envelope);
  }

  clear() {
    this.listeners.clear();
    this.statusListeners.clear();
  }
}

/**
 * A cancellable sequence of delayed steps. The mock script is a list of "at
 * t+N ms, emit this", and every one of them has to be cancellable, or advancing
 * the demo early leaves timers firing into a state that has moved on — which
 * looks exactly like a bug on stage.
 */
export class Timeline {
  private timers: ReturnType<typeof setTimeout>[] = [];

  at(ms: number, fn: () => void) {
    this.timers.push(setTimeout(fn, ms));
    return this;
  }

  /** Run `fn` `count` times, `every` ms apart, starting at `from`. */
  repeat(from: number, every: number, count: number, fn: (i: number) => void) {
    for (let i = 0; i < count; i++) this.at(from + i * every, () => fn(i));
    return this;
  }

  cancel() {
    for (const t of this.timers) clearTimeout(t);
    this.timers = [];
  }
}

/** Fetch JSON, returning null rather than throwing when a file is absent.
 *  `trajectories_12k.json` is gitignored, so a clean clone must still run. */
export async function fetchJson<T>(url: string): Promise<T | null> {
  try {
    const res = await fetch(url);
    if (!res.ok) return null;
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

export async function fetchText(url: string): Promise<string | null> {
  try {
    const res = await fetch(url);
    if (!res.ok) return null;
    return await res.text();
  } catch {
    return null;
  }
}
