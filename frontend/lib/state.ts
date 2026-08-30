/**
 * The demo state machine. CONTRACT §9: landing, intake, briefing, simulating,
 * field_ready, evidence, validation, in that order.
 *
 * "Progression is scripted and advances on a single key. The pitch never
 * depends on finding a button." So this keyboard map is the real interface
 * during the 90 seconds, and every binding is one keystroke with no modifier.
 */

import { STATES, type DemoState } from "./contract";

export const FIRST_STATE: DemoState = "landing";

export function nextState(s: DemoState): DemoState {
  return STATES[Math.min(STATES.length - 1, STATES.indexOf(s) + 1)];
}

export function prevState(s: DemoState): DemoState {
  return STATES[Math.max(0, STATES.indexOf(s) - 1)];
}

/** Which states draw the map. landing and intake are panels only. */
export const showsMap = (s: DemoState) => s !== "landing" && s !== "intake";

/** The rail appears with the map and never moves after that. */
export const showsRail = showsMap;

export const STATE_LABEL: Record<DemoState, string> = {
  landing: "Standby",
  intake: "Intake",
  briefing: "Briefing",
  simulating: "Simulating",
  field_ready: "Field ready",
  evidence: "Evidence applied",
  validation: "Validation",
};

// ---------------------------------------------------------------------------
// Keyboard
// ---------------------------------------------------------------------------

export type DemoAction =
  | { kind: "advance" }
  | { kind: "back" }
  | { kind: "goto"; state: DemoState }
  | { kind: "reset-camera" }
  | { kind: "toggle-flatten" }
  | { kind: "replay-transcript" }
  | { kind: "toggle-help" };

/** Returns null for keys we do not own, so typing in a field is unaffected. */
export function keyToAction(e: KeyboardEvent): DemoAction | null {
  if (e.metaKey || e.ctrlKey || e.altKey) return null;

  switch (e.key) {
    case " ":
    case "Enter":
    case "ArrowRight":
      return { kind: "advance" };
    case "ArrowLeft":
      return { kind: "back" };
    case "r":
    case "R":
      return { kind: "reset-camera" };
    case "f":
    case "F":
      return { kind: "toggle-flatten" };
    case "t":
    case "T":
      return { kind: "replay-transcript" };
    case "?":
      return { kind: "toggle-help" };
  }

  // 1-7 jump straight to a state. Recovery, not choreography: if a rehearsal
  // goes wrong there is no time to press space six times.
  const n = Number(e.key);
  if (Number.isInteger(n) && n >= 1 && n <= STATES.length) {
    return { kind: "goto", state: STATES[n - 1] };
  }
  return null;
}

/** Shown in the help overlay. Kept beside keyToAction so they cannot drift. */
export const KEY_HELP: Array<[string, string]> = [
  ["Space", "Advance"],
  ["←", "Back"],
  ["1–7", "Jump to state"],
  ["R", "Reset camera"],
  ["F", "Flatten pitch"],
  ["T", "Replay the call"],
  ["?", "Close this"],
];
