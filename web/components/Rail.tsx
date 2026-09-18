"use client";

import type { CaseView, FieldView, FleetView, ValidationView } from "@/lib/adapt";
import { elapsedLabel } from "@/lib/adapt";
import type { DemoState, Hypothesis } from "@/lib/contract";
import { Datum, Eyebrow } from "./Panel";
import HypothesisTicker from "./HypothesisTicker";

/**
 * The rail. ONE number per beat, and at most two supporting rows.
 *
 * The brief's discipline was "seven numbers total". This goes further, because
 * seven numbers all present at once still asks a judge to work out which one
 * matters. They are watching for ninety seconds and reading from across a room,
 * so each state puts exactly one figure at display size and everything else is
 * support. What is on screen changes; the layout never does.
 *
 *   briefing     the ring       — the search area as it is drawn today
 *   simulating   sandboxes      — the only proof real machines are working
 *   field_ready  field area %   — the argument
 *   evidence     field area %   — the argument, after the collapse
 *   validation   our score      — the number the project is measured by
 *
 * Deliberately absent everywhere: hypothesis family bars, conditions, the zone
 * list beyond one row, coordinates, progress bars. The zones are already
 * labelled on the map; repeating them here is telemetry, not information.
 *
 * Numbers do not count up and panels do not animate in. The paths are the only
 * fast-moving thing on screen; restraint is what makes that land.
 */

const fmt = (n: number) => n.toLocaleString("en-GB");

/**
 * What the next press of space does.
 *
 * The demo is keyboard-driven and the presenter knows the script, so this is
 * not for them. It is for every other case: a rehearsal, someone else driving,
 * a judge given the keyboard — and the state this was written for, `briefing`,
 * which looks completely finished loading and gives no clue that anything is
 * expected of you. Sitting on a static ring waiting for routes that only start
 * on the next keypress is a bad minute to have in front of a room.
 *
 * `simulating` is deliberately absent: it advances itself when the orchestrator
 * says the field is ready, so promising a manual step there would be a lie.
 */
const NEXT_ACTION: Partial<Record<DemoState, string>> = {
  briefing: "Run the simulation",
  field_ready: "Apply the witness report",
  evidence: "Show the validation",
};

/** The single display figure. Nothing else in the card comes close to it. */
function Hero({
  value,
  unit,
  caption,
  note,
  tone = "bone",
}: {
  /** null renders the caption alone. A display-size em-dash reads as a stray
   *  rule rather than an empty state — see the field's empty case. */
  value: string | null;
  unit?: string;
  caption: string;
  note?: string;
  tone?: "bone" | "hot" | "dim";
}) {
  const colour =
    tone === "hot"
      ? "var(--field-hot)"
      : tone === "dim"
        ? "var(--bone-faint)"
        : "var(--bone)";
  if (value === null) {
    return (
      <div>
        <p className="eyebrow">{caption}</p>
        {note ? (
          <p
            className="mt-3 max-w-[34ch] text-[17px] leading-[1.5]"
            style={{ color: "var(--bone-dim)" }}
          >
            {note}
          </p>
        ) : null}
      </div>
    );
  }

  return (
    <div>
      <div className="flex items-baseline gap-2">
        <span
          className="display tabular leading-[0.82]"
          style={{ fontSize: 84, color: colour, letterSpacing: "-0.035em" }}
        >
          {value}
        </span>
        {unit ? (
          <span
            className="display leading-none"
            style={{ fontSize: 30, color: colour }}
          >
            {unit}
          </span>
        ) : null}
      </div>
      <p className="eyebrow mt-3">{caption}</p>
      {note ? (
        <p
          className="mt-2 text-[14px] leading-[1.45]"
          style={{ color: "var(--bone-faint)" }}
        >
          {note}
        </p>
      ) : null}
    </div>
  );
}

export default function Rail({
  state,
  caseView,
  fleet,
  field,
  validation,
  hypotheses,
  nRunsTotal,
  nRunsFailed,
  width,
  inset,
}: {
  state: DemoState;
  caseView: CaseView | null;
  fleet: FleetView;
  field: FieldView | null;
  validation: ValidationView | null;
  hypotheses: Hypothesis[];
  nRunsTotal: number;
  nRunsFailed: number;
  width: number;
  inset: number;
}) {
  const topZone = field?.zones?.[0];

  /** The one figure for whichever beat we are on. */
  const hero = (() => {
    if (state === "validation") {
      const score = validation?.ourScore;
      return (
        <Hero
          value={score == null ? null : score.toFixed(3)}
          caption="Searchlight score"
          note={
            score == null
              ? "Pending the validation run. No number is shown until there is one."
              : `${validation?.nCases ?? 6} real historical cases, same metric as the ring.`
          }
          tone={score == null ? "dim" : "bone"}
        />
      );
    }
    if (state === "evidence" || state === "field_ready") {
      return (
        <Hero
          value={field ? field.fieldAreaPct.toFixed(1) : null}
          unit="%"
          caption="of the ring's area"
          note="Smallest region holding 50% of the probability mass"
          tone={field ? "hot" : "dim"}
        />
      );
    }
    if (state === "simulating") {
      return (
        <Hero
          value={fmt(fleet.active)}
          caption="Sandboxes running"
          note={
            fleet.requested
              ? `of ${fmt(fleet.requested)} requested`
              : "Real machines, executing model-written code"
          }
        />
      );
    }
    // briefing
    return (
      <Hero
        value={caseView ? (caseView.ringRadiusM / 1000).toFixed(2) : null}
        unit="km"
        caption="ISRID ring · 95th percentile"
        note="This is the search area as it is drawn today."
        tone={caseView ? "bone" : "dim"}
      />
    );
  })();

  return (
    <aside
      className="absolute z-20 flex flex-col overflow-y-auto px-7 py-7"
      style={{
        width,
        top: inset,
        right: inset,
        bottom: inset,
        // Solid, not frosted. The card sits over terrain that changes colour
        // under it, and a translucent panel would make every number in here
        // depend on what happens to be behind it.
        background: "var(--ground-lift)",
        border: "1px solid var(--bone-faint)",
        borderRadius: 12,
        // Offset and blur, not a zero-offset halo: this is a card lifted off
        // the map, and it should cast light the way an object would.
        boxShadow: "0 18px 48px -12px rgba(0,0,0,0.85), 0 2px 8px rgba(0,0,0,0.5)",
      }}
    >
      <header className="flex shrink-0 items-baseline justify-between gap-3">
        <h1
          className="display uppercase leading-none"
          style={{ fontSize: 28, color: "var(--bone)" }}
        >
          Searchlight
        </h1>
        <span
          className="tabular text-[15px] font-medium"
          style={{ color: "var(--bone-dim)" }}
        >
          {caseView?.incident ?? "—"}
        </span>
      </header>

      {/* Who this is. Two lines, then never repeated. */}
      <div className="mt-7 shrink-0">
        <div
          className="display leading-none"
          style={{ fontSize: 30, color: "var(--bone)" }}
        >
          {caseView?.subjectName ?? "—"}
        </div>
        <div className="mt-2.5 text-[17px]" style={{ color: "var(--bone-dim)" }}>
          {[caseView?.age, caseView?.category, caseView?.experience]
            .filter(Boolean)
            .join(" · ") || "—"}
        </div>
      </div>

      <div
        className="my-7 h-px shrink-0"
        style={{ background: "var(--bone-faint)", opacity: 0.55 }}
      />

      <div className="shrink-0">{hero}</div>

      {/* At most two supporting rows, and only the ones this beat needs. */}
      <div className="mt-8 flex shrink-0 flex-col gap-4">
        {state === "briefing" && caseView ? (
          <Datum
            label="Last contact"
            value={elapsedLabel(caseView.lastContactS)}
            sub={caseView.lastContactTime ? `at ${caseView.lastContactTime}` : undefined}
          />
        ) : null}

        {state === "simulating" ? (
          <Datum
            label="Simulations"
            value={fmt(nRunsTotal)}
            // A failure count on screen is credibility, not weakness.
            sub={nRunsFailed > 0 ? `${fmt(nRunsFailed)} failed` : undefined}
          />
        ) : null}

        {state === "field_ready" ? (
          <>
            <Datum
              label="Simulations"
              value={fmt(nRunsTotal)}
              sub={nRunsFailed > 0 ? `${fmt(nRunsFailed)} failed` : undefined}
            />
            {topZone ? (
              <Datum
                label="Top zone"
                value={`${topZone.pct.toFixed(1)}%`}
                sub={topZone.name}
              />
            ) : null}
          </>
        ) : null}

        {state === "evidence" && field ? (
          <>
            <Datum
              label="Consistent"
              value={fmt(field.nConsistent)}
              sub={`of ${fmt(field.nTotal)} simulations`}
            />
            <Datum
              label="ISRID ring"
              value={`${(field.ringRadiusM / 1000).toFixed(2)} km`}
              sub="unchanged"
            />
          </>
        ) : null}

        {state === "validation" && validation ? (
          <Datum
            label="ISRID ring, same cases"
            value={validation.ringBaseline.toFixed(3)}
            sub="the number to beat"
          />
        ) : null}
      </div>

      {/* Simulating only: the model's reasoning, in its own words. Gone the
          moment the field settles. */}
      {state === "simulating" && hypotheses.length ? (
        <div className="-mx-7 mt-8 shrink-0">
          <HypothesisTicker hypotheses={hypotheses} />
        </div>
      ) : null}

      <div className="min-h-6 flex-1" />

      <footer className="shrink-0">
        {NEXT_ACTION[state] ? (
          <div
            className="mb-4 flex items-center gap-3 border-t pt-4"
            style={{ borderColor: "var(--bone-faint)" }}
          >
            <kbd
              className="shrink-0 px-2.5 py-1 text-[12px] font-semibold uppercase tracking-[0.12em]"
              style={{
                color: "var(--ground)",
                background: "var(--bone-dim)",
                borderRadius: 3,
              }}
            >
              Space
            </kbd>
            <span className="text-[15px]" style={{ color: "var(--bone-dim)" }}>
              {NEXT_ACTION[state]}
            </span>
          </div>
        ) : null}
        <Eyebrow style={{ color: "var(--bone-faint)", lineHeight: 1.7 }}>
          Decision support. Surfaces hypotheses, not certainties.
        </Eyebrow>
      </footer>
    </aside>
  );
}
