"use client";

import type { ReactNode } from "react";

/**
 * The shared panel primitive. Person C's intake screens use this too, so the
 * report does not read as a different application from the map.
 *
 * SIGNATURE ELEMENT: corner registration ticks instead of a full border. It is
 * the detail that makes the screen read as an incident command board rather
 * than a dashboard template — the same marks a survey sheet or a printer's
 * proof carries. Four 1px L-shapes, no fill, no radius, no shadow.
 *
 * Deliberately not a card. Cards are the lazy container, and a column of
 * same-size cards with a heading and a stat is the exact shape of every
 * generated dashboard. These are registration marks around content that is
 * already grouped by spacing.
 */

const TICK = 11;

export function Ticks({ colour }: { colour: string }) {
  const common = {
    position: "absolute" as const,
    width: TICK,
    height: TICK,
    transition: "border-color 300ms ease",
  };
  return (
    <>
      <span
        aria-hidden
        style={{ ...common, top: 0, left: 0, borderTop: `1px solid ${colour}`, borderLeft: `1px solid ${colour}` }}
      />
      <span
        aria-hidden
        style={{ ...common, top: 0, right: 0, borderTop: `1px solid ${colour}`, borderRight: `1px solid ${colour}` }}
      />
      <span
        aria-hidden
        style={{ ...common, bottom: 0, left: 0, borderBottom: `1px solid ${colour}`, borderLeft: `1px solid ${colour}` }}
      />
      <span
        aria-hidden
        style={{ ...common, bottom: 0, right: 0, borderBottom: `1px solid ${colour}`, borderRight: `1px solid ${colour}` }}
      />
    </>
  );
}

export function Panel({
  children,
  label,
  className = "",
  tickColour = "var(--bone-faint)",
}: {
  children: ReactNode;
  label?: string;
  className?: string;
  tickColour?: string;
}) {
  return (
    <section className={`relative px-6 py-4 ${className}`}>
      <Ticks colour={tickColour} />
      {label ? <Eyebrow>{label}</Eyebrow> : null}
      {children}
    </section>
  );
}

/** Small caps at 0.16em. One naming convention across the whole app, so a label
 *  always looks like a label and never competes with a value. */
export function Eyebrow({
  children,
  className = "",
  style,
}: {
  children: ReactNode;
  className?: string;
  style?: React.CSSProperties;
}) {
  return (
    <div className={`eyebrow ${className}`} style={style}>
      {children}
    </div>
  );
}

/** A label/value row. Values are tabular so digits do not jitter as they tick. */
export function Datum({
  label,
  value,
  sub,
  emphasis = false,
}: {
  label: string;
  value: ReactNode;
  sub?: ReactNode;
  emphasis?: boolean;
}) {
  return (
    <div className="flex items-baseline justify-between gap-4">
      <Eyebrow className="shrink-0">{label}</Eyebrow>
      <div className="text-right">
        <div
          className="tabular font-medium leading-tight"
          style={{
            color: "var(--bone)",
            fontSize: emphasis ? 30 : 21,
          }}
        >
          {value}
        </div>
        {sub ? (
          <div
            className="mt-1 text-[14px] leading-tight"
            style={{ color: "var(--bone-dim)" }}
          >
            {sub}
          </div>
        ) : null}
      </div>
    </div>
  );
}
