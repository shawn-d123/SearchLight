/**
 * The one place two payload spellings become one view model.
 *
 * ADAPT NOTES — why this file exists
 * ----------------------------------
 * CONTRACT.md and the committed mocks were written against each other but drift
 * in two places that still stand. Both were written in good faith: the contract
 * describes what the orchestrator will emit, the mocks are what Person C's
 * harness actually produces, and validate_mocks.py passes because it checks the
 * field payload, which does agree.
 *
 *   1. fleet_status. CONTRACT §9 says {active, complete, failed, families}.
 *      mocks/fleet_status.json says {sandboxes_active, hypotheses_completed,
 *      runs_completed, runs_failed, ...}. Both accepted; `families` is optional
 *      because the mock carries no such map.
 *
 *   2. evidence. CONTRACT §9 says {lat, lon, t, radius_m, reliability}.
 *      mocks/field_collapsed.json says {location, t_s, radius_m, tolerance_s,
 *      description}. Both accepted.
 *
 * (case_loaded no longer drifts: mocks/case.json is now the §8 extraction
 * payload plus incident metadata, which is a clean superset.)
 *
 * The rule this file follows: **the contract spelling is read first, the mock
 * spelling second.** So when the orchestrator ships the contract shape it wins
 * outright and nothing here needs deleting. Normalising rather than picking a
 * winner is what makes 14:30 a config flip instead of a rewrite — and it means
 * neither B nor C has to change anything they have already built.
 *
 * NOTHING ELSE IN THE APP READS A RAW PAYLOAD. Components consume the *View
 * types below and never see a wire field name.
 */

import {
  decodeGrid,
  type Bounds,
  type Evidence,
  type Extraction,
  type FieldUpdate,
  type FleetStatus,
  type Hypothesis,
  type LatLon,
  type ValidationResult,
  type Zone,
} from "./contract";
import {
  BOUNDS,
  FALLBACK_IPP,
  FALLBACK_RING_RADIUS_M,
  REGION,
} from "./config";

const num = (...vals: unknown[]): number | undefined => {
  for (const v of vals) if (typeof v === "number" && Number.isFinite(v)) return v;
  return undefined;
};

const str = (...vals: unknown[]): string | undefined => {
  for (const v of vals) if (typeof v === "string" && v.length > 0) return v;
  return undefined;
};

// ---------------------------------------------------------------------------
// Case
// ---------------------------------------------------------------------------

export interface CaseView {
  /** Incident designator, shown in the header for the rest of the demo. */
  incident: string;
  subjectName: string;
  category?: string;
  experience?: string;
  clothing?: string;
  injuries?: string;
  age?: number;
  /** Seconds since last contact. */
  lastContactS: number;
  /** Clock time of last contact, when intake supplies one. */
  lastContactTime?: string;
  place?: string;
  conditions?: string;
  ipp: LatLon;
  ringRadiusM: number;
  ringLabel: string;
  bounds: Bounds;
  region: string;
  transcript?: string;
  confidence?: Record<string, number>;
}

const displayElapsed = (s: number): string => {
  const m = Math.round(s / 60);
  if (m < 90) return `${m} MIN`;
  return `${Math.floor(m / 60)}H ${String(m % 60).padStart(2, "0")}M`;
};

export const elapsedLabel = displayElapsed;

/**
 * The case as configured, before anything arrives on the wire.
 *
 * The orchestrator emits `case_loaded` when a RUN starts, not on connect, so
 * between opening the socket and pressing run there is no case at all — and
 * without one there is no ring, no marker and no camera framing. The static
 * frame is the milestone the whole build rests on ("if that frame is on screen
 * you have a skeleton"), so it must not depend on a message that may be
 * minutes away or never come.
 *
 * These are the same values the real case carries; `case_loaded` overwrites
 * them the moment it lands. Nothing here is invented — see FALLBACK_* in
 * lib/config.ts.
 */
export function defaultCaseView(): CaseView {
  return {
    incident: "SL-2084",
    subjectName: "—",
    lastContactS: 0,
    ipp: FALLBACK_IPP,
    ringRadiusM: FALLBACK_RING_RADIUS_M,
    ringLabel: `ISRID RING · 95TH PCTL · ${(FALLBACK_RING_RADIUS_M / 1000).toFixed(1)} KM`,
    bounds: BOUNDS,
    region: REGION,
  };
}

/** Accepts the CONTRACT §8 extraction payload, with or without the incident
 *  metadata mocks/case.json wraps around it. */
export function normaliseCase(raw: unknown): CaseView {
  const r = (raw ?? {}) as Record<string, unknown>;
  const ex = r as unknown as Extraction;

  const subject = (ex.subject ?? {}) as Extraction["subject"];
  const lastKnown = (ex.last_known ?? {}) as Partial<Extraction["last_known"]>;
  const assessment = (ex.assessment ?? {}) as Partial<Extraction["assessment"]>;

  const ipp = (lastKnown.ipp as LatLon | undefined) ?? FALLBACK_IPP;

  const ringRadiusM =
    num(assessment.ring_radius_m, r.ring_radius_m) ?? FALLBACK_RING_RADIUS_M;

  const lastContactS =
    num(
      lastKnown.elapsed_min !== undefined
        ? (lastKnown.elapsed_min as number) * 60
        : undefined,
    ) ?? 0;

  return {
    incident: str(r.incident, r.case_id) ?? "SL-2084",
    subjectName: str(subject.name, r.subject_name) ?? "UNIDENTIFIED",
    category: str(subject.category, r.subject_category),
    experience: str(subject.experience),
    clothing: str(subject.clothing),
    injuries: str(subject.injuries),
    age: num(subject.age),
    lastContactS,
    lastContactTime: str(lastKnown.time),
    place: str(lastKnown.place),
    conditions: str(assessment.conditions),
    ipp,
    ringRadiusM,
    ringLabel:
      str(r.ring_label)?.replace(/-/g, "·").toUpperCase() ??
      `ISRID RING · 95TH PCTL · ${(ringRadiusM / 1000).toFixed(1)} KM`,
    bounds: (r.bounds as Bounds | undefined) ?? BOUNDS,
    region: str(r.region) ?? REGION,
    transcript: str(ex.transcript),
    confidence: ex.confidence,
  };
}

// ---------------------------------------------------------------------------
// Fleet
// ---------------------------------------------------------------------------

export interface FleetView {
  /** The only thing on screen proving real machines are doing work. */
  active: number;
  ready: number;
  requested: number;
  hypothesesComplete: number;
  runsComplete: number;
  runsFailed: number;
  progress: number;
  families: Record<string, number>;
  elapsedS?: number;
}

export const EMPTY_FLEET: FleetView = {
  active: 0,
  ready: 0,
  requested: 0,
  hypothesesComplete: 0,
  runsComplete: 0,
  runsFailed: 0,
  progress: 0,
  families: {},
};

export function normaliseFleet(raw: unknown): FleetView {
  const f = (raw ?? {}) as FleetStatus;
  return {
    active: num(f.active, f.sandboxes_active) ?? 0,
    ready: num(f.sandboxes_ready) ?? 0,
    requested: num(f.sandboxes_requested) ?? 0,
    hypothesesComplete: num(f.hypotheses_completed) ?? 0,
    // CONTRACT §9 does not say what `complete` counts. The orchestrator
    // increments it per successful RUN (pipeline.py `_stats["complete"] += ok`),
    // so it belongs here and not on the hypothesis counter.
    runsComplete: num(f.runs_completed, f.complete) ?? 0,
    runsFailed: num(f.failed, f.runs_failed) ?? 0,
    progress: num(f.progress) ?? 0,
    families: f.families ?? {},
    elapsedS: num(f.elapsed_s),
  };
}

// ---------------------------------------------------------------------------
// Evidence
// ---------------------------------------------------------------------------

export interface EvidenceView {
  lat: number;
  lon: number;
  /** Seconds since LKP. */
  tS: number;
  radiusM: number;
  toleranceS?: number;
  reliability?: number;
  description?: string;
}

export function normaliseEvidence(raw: unknown): EvidenceView | undefined {
  if (!raw) return undefined;
  const e = raw as Evidence;
  const lat = num(e.lat, e.location?.[0]);
  const lon = num(e.lon, e.location?.[1]);
  if (lat === undefined || lon === undefined) return undefined;
  return {
    lat,
    lon,
    tS: num(e.t, e.t_s) ?? 0,
    radiusM: num(e.radius_m) ?? 0,
    toleranceS: num(e.tolerance_s),
    reliability: num(e.reliability),
    description: str(e.description),
  };
}

// ---------------------------------------------------------------------------
// Field
// ---------------------------------------------------------------------------

export interface FieldView {
  bounds: Bounds;
  resolution: number;
  /** Decoded once, here. Components never see base64. */
  grid: Float32Array;
  progress: number;
  zones: Zone[];
  nTotal: number;
  nConsistent: number;
  ringRadiusM: number;
  fieldAreaPct: number;
  evidence?: EvidenceView;
}

export function normaliseField(raw: unknown): FieldView {
  const f = raw as FieldUpdate;
  return {
    bounds: f.bounds,
    resolution: f.resolution,
    grid: decodeGrid(f.grid, f.resolution),
    progress: num(f.progress) ?? 0,
    zones: Array.isArray(f.zones) ? f.zones : [],
    nTotal: num(f.n_total) ?? 0,
    nConsistent: num(f.n_consistent) ?? 0,
    ringRadiusM: num(f.ring_radius_m) ?? FALLBACK_RING_RADIUS_M,
    fieldAreaPct: num(f.field_area_pct) ?? 0,
    evidence: normaliseEvidence(f.evidence),
  };
}

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

export interface ValidationView {
  nCases: number;
  ourScore: number | null;
  /**
   * The ring on the SAME cases with the SAME metric — 0.761, not the published
   * 0.78. Quoting 0.78 compares six cases against 376 and is not honest.
   */
  ringBaseline: number;
  ci95?: [number, number];
  perCase?: number[];
}

export function normaliseValidation(raw: unknown): ValidationView {
  const v = (raw ?? {}) as ValidationResult;
  return {
    nCases: num(v.n_cases) ?? 6,
    ourScore: typeof v.our_score === "number" ? v.our_score : null,
    ringBaseline: num(v.ring_baseline) ?? 0.761,
    ci95: v.ci95,
    perCase: v.per_case,
  };
}

// ---------------------------------------------------------------------------
// Hypotheses
// ---------------------------------------------------------------------------

/** Tolerates a bare array as well as the §7 envelope {n_planned, hypotheses}. */
export function normaliseHypotheses(raw: unknown): Hypothesis[] {
  if (Array.isArray(raw)) return raw as Hypothesis[];
  const h = (raw as { hypotheses?: unknown })?.hypotheses;
  return Array.isArray(h) ? (h as Hypothesis[]) : [];
}
