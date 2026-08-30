"use client";

import { KEY_HELP } from "@/lib/state";
import { Ticks } from "./Panel";

/**
 * The key map, on demand.
 *
 * During the 90 seconds the presenter never touches the mouse and never reads
 * this. It exists for rehearsal, and for the moment someone else has to drive.
 */
export default function HelpOverlay({
  open,
  onClose,
}: {
  open: boolean;
  onClose(): void;
}) {
  if (!open) return null;
  return (
    <div
      className="absolute inset-0 z-40 flex items-center justify-center"
      style={{ background: "rgba(20,19,14,0.82)" }}
      onClick={onClose}
      role="dialog"
      aria-label="Keyboard shortcuts"
    >
      <div
        className="relative px-8 py-7"
        style={{ background: "var(--ground)" }}
        onClick={(e) => e.stopPropagation()}
      >
        <Ticks colour="var(--bone-dim)" />
        <div
          className="eyebrow"
          style={{ color: "var(--bone-dim)" }}
        >
          Keys
        </div>
        <dl className="mt-4 grid grid-cols-[auto_1fr] gap-x-7 gap-y-2.5">
          {KEY_HELP.map(([key, what]) => (
            <div key={key} className="contents">
              <dt
                className="text-[17px] font-semibold"
                style={{ color: "var(--bone)" }}
              >
                {key}
              </dt>
              <dd
                className="text-[17px]"
                style={{ color: "var(--bone-dim)" }}
              >
                {what}
              </dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  );
}
