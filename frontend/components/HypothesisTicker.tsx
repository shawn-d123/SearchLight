"use client";

import { useEffect, useState } from "react";
import type { Hypothesis } from "@/lib/contract";
import { FAMILY_LABEL } from "@/lib/contract";
import { Eyebrow } from "./Panel";

/**
 * Cycles three or four generated hypotheses while the paths spread.
 *
 * This is the only text on screen that changes for its own sake, and it earns
 * it: the descriptions are site-specific ("descended south-west on the path of
 * least resistance, losing 362 m over 2 km") rather than textbook category
 * names, which is what makes the model's reasoning legible instead of hidden
 * inside a code generator. They disappear when the field settles.
 *
 * Where a hypothesis carries `source.kind === "local"`, its label renders as a
 * smaller muted attribution line — the visible payoff of the research pass, and
 * a good fit for a project whose whole identity is evidence over intuition.
 * Handle `source` being absent: most hypotheses will not have one, and until
 * data/local_knowledge.json exists none of them will.
 */

const DWELL_MS = 3400;
const FADE_MS = 300;

export default function HypothesisTicker({
  hypotheses,
  max = 4,
}: {
  hypotheses: Hypothesis[];
  max?: number;
}) {
  const shown = hypotheses.slice(0, max);
  const [i, setI] = useState(0);
  const [visible, setVisible] = useState(true);

  useEffect(() => setI(0), [hypotheses]);

  useEffect(() => {
    if (shown.length < 2) return;
    const hide = setTimeout(() => setVisible(false), DWELL_MS - FADE_MS);
    const swap = setTimeout(() => {
      setI((n) => (n + 1) % shown.length);
      setVisible(true);
    }, DWELL_MS);
    return () => {
      clearTimeout(hide);
      clearTimeout(swap);
    };
  }, [i, shown.length]);

  if (!shown.length) return null;
  const h = shown[i];

  return (
    <div className="px-6">
      <div className="flex items-baseline justify-between gap-3">
        <Eyebrow>Hypotheses</Eyebrow>
        <span
          className="tabular text-[13px] font-medium"
          style={{ color: "var(--bone-faint)" }}
        >
          {i + 1}/{shown.length}
        </span>
      </div>

      <div
        className="mt-2 min-h-[104px]"
        style={{
          opacity: visible ? 1 : 0,
          transition: `opacity ${FADE_MS}ms cubic-bezier(0.16,1,0.3,1)`,
        }}
      >
        <div
          className="eyebrow"
          style={{ color: "var(--bone-faint)" }}
        >
          {FAMILY_LABEL[h.family] ?? h.family}
          {typeof h.weight === "number" ? ` · w ${h.weight.toFixed(2)}` : ""}
        </div>
        <p
          className="mt-2.5 text-[17px] leading-[1.5]"
          style={{ color: "var(--bone)" }}
        >
          {h.description}
        </p>
        {h.source?.kind === "local" && h.source.label ? (
          <p
            className="mt-2 text-[13px] leading-snug"
            style={{ color: "var(--bone-dim)" }}
          >
            {h.source.label}
          </p>
        ) : null}
      </div>
    </div>
  );
}
