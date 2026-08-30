"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useTranscription } from "@/lib/useTranscription";
import { elapsedLabel } from "@/lib/adapt";
import type { Extraction } from "@/lib/contract";
import { Ticks } from "./Panel";

/**
 * The call, and the report it produces.
 *
 * OWNERSHIP: CONTRACT §8 assigns the intake states to Person C — the extraction
 * is a model call, which is their territory. This is the shell: the layout, the
 * shared panel language, the staggered reveal, and a transcript replayed from
 * mocks/transcript.txt. C swaps the mock producer for live Web Speech plus a
 * real extraction call and nothing here changes, because both arrive as the
 * same `transcript_partial` and `extraction_update` envelopes.
 *
 * BUILT FOR NINETY SECONDS. The whole pitch is 90s, so this screen gets about
 * eight of them. That drives three things: the transcript streams in word
 * groups rather than one word at a time, the extracted fields are large enough
 * to read from across a room at a glance, and the action out of here is the
 * biggest thing on screen. Nobody should have to hunt for the next step while
 * a room watches.
 *
 * THE TRANSCRIPT IS TEXTURE. THE STRUCTURED EXTRACTION IS THE HERO. A hackathon
 * venue at 5pm is loud and recognition will mangle words. Built so that does
 * not matter: an imperfect transcript still yields a correct report, because a
 * model pulls the fields out of it. If it garbles a word and the card still
 * populates, say so — that reads as robustness.
 *
 * The replay is also the mandatory fallback. If the mic fails: "the room's too
 * loud, here's the recorded version", press T, move on.
 */

const BARS = 40;

function Field({
  label,
  value,
}: {
  label: string;
  value?: string | number | null;
}) {
  const resolved = value !== undefined && value !== null && value !== "";
  return (
    <div
      className="border-b py-2 last:border-b-0"
      style={{
        borderColor: "rgba(93,88,68,0.4)",
        // Fields populate one at a time as extraction returns. The transition
        // is on the resolved state, so a field arriving is a quiet settle
        // rather than a flash.
        opacity: resolved ? 1 : 0.32,
        transition: "opacity 260ms cubic-bezier(0.16,1,0.3,1)",
      }}
    >
      <div className="eyebrow">{label}</div>
      <div
        className="mt-1 truncate text-[17px] font-medium leading-tight"
        style={{ color: resolved ? "var(--bone)" : "var(--bone-faint)" }}
      >
        {resolved ? value : "—"}
      </div>
    </div>
  );
}

function ReportPanel({
  label,
  count,
  total,
  children,
}: {
  label: string;
  count: number;
  total: number;
  children: React.ReactNode;
}) {
  const done = count >= total;
  return (
    <section className="relative px-5 py-3.5">
      <Ticks colour={done ? "var(--amber)" : "var(--bone-faint)"} />
      <header className="flex items-baseline justify-between gap-3">
        <span
          className="eyebrow"
          style={{ color: done ? "var(--amber)" : "var(--bone-dim)" }}
        >
          {label}
        </span>
        <span
          className="tabular text-[12px] font-medium"
          style={{ color: done ? "var(--amber)" : "var(--bone-faint)" }}
        >
          {count}/{total}
        </span>
      </header>
      <div className="mt-1">{children}</div>
    </section>
  );
}

export default function Intake({
  transcript,
  transcriptFinal,
  extraction,
  incident,
  onBegin,
  onReplay,
  onTranscript,
}: {
  transcript: string;
  transcriptFinal: boolean;
  /**
   * The PARTIAL extraction, merged as fields resolve — deliberately not the
   * CaseView. case_loaded arrives complete on connect (it has to, so the map
   * and rail can build the ring), and rendering the report from it pre-fills
   * every field before the caller has finished the first sentence, which
   * throws away the entire point of this screen.
   */
  extraction: Partial<Extraction>;
  incident: string;
  onBegin(): void;
  onReplay(): void;
  /**
   * Live microphone words, sent up the socket as `transcript_partial`. Omitted
   * in mock mode, where there is no server to extract with.
   */
  onTranscript?(payload: { text: string; is_final: boolean }): void;
}) {
  const send = useCallback(
    (payload: { text: string; is_final: boolean }) => onTranscript?.(payload),
    [onTranscript],
  );
  const mic = useTranscription(send);

  const subject = extraction.subject;
  const lastKnown = extraction.last_known;
  const assessment = extraction.assessment;
  const ready = Boolean(lastKnown?.ipp && assessment?.ring_radius_m);

  const n = (...vals: unknown[]) =>
    vals.filter((v) => v !== undefined && v !== null && v !== "").length;

  // Call timer. Starts when the first words land, holds when the call ends.
  //
  // Keyed on whether there IS a transcript, never on its text: transcript_partial
  // arrives every 150ms, so depending on the string tore the interval down and
  // rebuilt it before its 250ms tick could ever fire, and the clock sat at 00:00
  // for the whole call.
  const [seconds, setSeconds] = useState(0);
  const startedAt = useRef<number | null>(null);
  const started = Boolean(transcript);
  useEffect(() => {
    if (!started) {
      startedAt.current = null;
      setSeconds(0);
      return;
    }
    if (startedAt.current === null) startedAt.current = Date.now();
    const tick = () =>
      setSeconds(Math.floor((Date.now() - (startedAt.current ?? Date.now())) / 1000));
    tick();
    if (transcriptFinal) return; // hold the final duration on screen
    const id = setInterval(tick, 250);
    return () => clearInterval(id);
  }, [started, transcriptFinal]);

  const live = Boolean(transcript) && !transcriptFinal;

  return (
    <div
      className="h-full w-full overflow-hidden"
      style={{ background: "var(--ground)" }}
    >
      <style>{`
        @keyframes sl-rec { 0%,100% { opacity: 1; } 50% { opacity: 0.25; } }
        @keyframes sl-bar { 0%,100% { transform: scaleY(0.16); } 50% { transform: scaleY(1); } }
        .sl-rec { animation: sl-rec 1.1s ease-in-out infinite; }
        .sl-bar { animation: sl-bar 900ms ease-in-out infinite; transform-origin: center; }
        @media (prefers-reduced-motion: reduce) {
          .sl-rec, .sl-bar { animation: none; }
          .sl-bar { transform: scaleY(0.5); }
        }
      `}</style>

      <div className="mx-auto flex h-full max-w-[1320px] flex-col gap-5 px-12 py-7">
        {/* Big wordmark, same as the landing, so this is unmistakably the same
            application rather than a form that appeared. */}
        <header className="flex items-end justify-between gap-8">
          <div>
            <h1
              className="display uppercase leading-[0.85]"
              style={{ fontSize: "clamp(38px, 3.8vw, 58px)", color: "var(--bone)" }}
            >
              Searchlight
            </h1>
            <p className="eyebrow mt-2">Incoming report</p>
          </div>
          <div className="text-right">
            <div className="eyebrow">Incident</div>
            <div
              className="tabular display mt-1.5 text-[22px]"
              style={{ color: "var(--bone)" }}
            >
              {incident}
            </div>
          </div>
        </header>

        {/* --- the call ----------------------------------------------------- */}
        <section className="relative px-6 py-4">
          <Ticks colour={live ? "var(--amber)" : "var(--bone-faint)"} />

          <header className="flex items-center justify-between gap-6">
            <div className="flex items-center gap-3">
              <span
                className={live ? "sl-rec" : undefined}
                style={{
                  width: 11,
                  height: 11,
                  borderRadius: "50%",
                  background: live ? "var(--amber)" : "var(--bone-faint)",
                  boxShadow: live ? "0 0 14px 2px rgba(232,163,61,0.75)" : "none",
                }}
                aria-hidden
              />
              <span
                className="eyebrow"
                style={{ color: live ? "var(--amber)" : "var(--bone-dim)" }}
              >
                {live ? "Live call" : transcriptFinal ? "Call ended" : "Awaiting call"}
              </span>

              {/* WHICH PATH IS RUNNING, always visible while audio is arriving.
                  A recorded replay with a real extraction is entirely honest;
                  presenting it as a live microphone is not, and it is the one
                  thing here a judge can catch by asking to speak themselves. */}
              {mic.mode !== "idle" && (
                <span
                  className="eyebrow"
                  style={{
                    padding: "2px 7px",
                    border: "1px solid",
                    borderColor:
                      mic.mode === "live" ? "var(--amber)" : "var(--bone-faint)",
                    color:
                      mic.mode === "live" ? "var(--amber)" : "var(--bone-dim)",
                  }}
                >
                  {mic.mode === "live" ? "MIC" : "RECORDED"}
                </span>
              )}
            </div>
            <span
              className="tabular text-[15px] font-medium"
              style={{ color: "var(--bone-dim)" }}
            >
              {String(Math.floor(seconds / 60)).padStart(2, "0")}:
              {String(seconds % 60).padStart(2, "0")}
            </span>
          </header>

          {/* Level meter. The visual signal that audio is arriving — a block of
              text alone does not read as a phone call from ten metres away. */}
          <div
            className="mt-3 flex h-7 items-center gap-[3px]"
            aria-hidden
            style={{ opacity: live ? 1 : 0.22 }}
          >
            {Array.from({ length: BARS }, (_, i) => (
              <span
                key={i}
                className={live ? "sl-bar" : undefined}
                style={{
                  flex: 1,
                  height: "100%",
                  background: "var(--amber)",
                  opacity: 0.55,
                  transform: live ? undefined : "scaleY(0.16)",
                  // Irrational stagger so the bars never fall into a visible
                  // repeating wave, which reads as decoration rather than audio.
                  animationDelay: `${((i * 137) % 900) - 900}ms`,
                  animationDuration: `${760 + ((i * 53) % 420)}ms`,
                }}
              />
            ))}
          </div>

          <p
            className="mt-3 min-h-[84px] max-w-[96ch] text-[19px] leading-[1.45]"
            style={{ color: "var(--bone)" }}
          >
            {transcript || (
              <span style={{ color: "var(--bone-faint)" }}>Waiting for the call…</span>
            )}
            {live ? (
              <span
                aria-hidden
                className="sl-rec ml-1 inline-block h-[1.05em] w-[0.42ch] align-text-bottom"
                style={{ background: "var(--amber)" }}
              />
            ) : null}
          </p>
        </section>

        {/* --- the report ---------------------------------------------------
            Same registration ticks as the rail, so this does not look like a
            different application. Each panel shows how much of it has resolved,
            which turns the staggered extraction into something legible rather
            than fields quietly brightening. */}
        <div className="grid gap-4 md:grid-cols-3">
          <ReportPanel
            label="Subject"
            total={5}
            count={n(
              subject?.name,
              subject?.age,
              subject?.category,
              subject?.clothing,
              subject?.injuries,
            )}
          >
            <Field label="Name" value={subject?.name} />
            <Field label="Age / category" value={
              subject?.age && subject?.category
                ? `${subject.age} · ${subject.category}`
                : subject?.category ?? subject?.age
            } />
            <Field label="Experience" value={subject?.experience} />
            <Field label="Clothing" value={subject?.clothing} />
            <Field label="Injuries" value={subject?.injuries} />
          </ReportPanel>

          <ReportPanel
            label="Last known"
            total={4}
            count={n(
              lastKnown?.place,
              lastKnown?.time,
              lastKnown?.elapsed_min,
              lastKnown?.ipp,
            )}
          >
            <Field label="Place" value={lastKnown?.place} />
            <Field label="Time" value={lastKnown?.time} />
            <Field
              label="Elapsed"
              value={
                lastKnown?.elapsed_min ? elapsedLabel(lastKnown.elapsed_min * 60) : null
              }
            />
            <Field
              label="Coordinates"
              value={
                lastKnown?.ipp
                  ? `${lastKnown.ipp[0].toFixed(4)}, ${lastKnown.ipp[1].toFixed(4)}`
                  : null
              }
            />
          </ReportPanel>

          <ReportPanel
            label="Assessment"
            total={3}
            count={n(
              assessment?.ring_radius_m,
              assessment?.conditions,
              assessment?.ring_radius_m,
            )}
          >
            <Field
              label="Ring radius"
              value={
                assessment?.ring_radius_m
                  ? `${(assessment.ring_radius_m / 1000).toFixed(2)} km · ISRID 95th`
                  : null
              }
            />
            <Field label="Conditions" value={assessment?.conditions} />
            <Field
              label="Hypotheses"
              value={assessment?.ring_radius_m ? "200 pending" : null}
            />
            <p
              className="pt-3 text-[13px] leading-[1.55]"
              style={{ color: "var(--bone-faint)" }}
            >
              Ring radius is derived from ISRID priors keyed on category. The
              model reads the call; the statistics do not come from it.
            </p>
          </ReportPanel>
        </div>

        {/* --- out of here ---------------------------------------------------
            The primary action is the largest thing below the fold and it is
            never ambiguous: it enables the moment the report can support a
            search, and says why while it cannot. */}
        <div className="mt-auto flex flex-wrap items-center gap-5 pt-2">
          <button
            onClick={onBegin}
            disabled={!ready}
            className="group display flex items-center gap-5 px-8 py-5 uppercase"
            style={{
              fontSize: "clamp(19px, 1.8vw, 26px)",
              lineHeight: 1,
              letterSpacing: "0.01em",
              color: ready ? "var(--ground)" : "var(--bone-faint)",
              background: ready ? "var(--bone)" : "transparent",
              border: `1px solid ${ready ? "var(--bone)" : "var(--bone-faint)"}`,
              cursor: ready ? "pointer" : "not-allowed",
              transition: "background 200ms, color 200ms",
            }}
          >
            Begin search
            <span
              aria-hidden
              className="transition-transform duration-200 group-enabled:group-hover:translate-x-1.5"
              style={{ fontSize: "1.1em" }}
            >
              →
            </span>
          </button>

          {/* Live microphone. Only offered when the browser can actually do
              it (Chrome and Edge; Firefox and Safari have no
              SpeechRecognition) and when there is a server to extract with.
              Hidden rather than disabled elsewhere -- a dead button on stage
              invites the one question you do not want. */}
          {onTranscript && mic.supported && (
            <button
              onClick={mic.listening ? mic.stop : mic.startLive}
              className="px-6 py-4 text-[13px] font-semibold uppercase tracking-[0.14em]"
              style={{
                color: mic.listening ? "var(--ground)" : "var(--amber)",
                border: "1px solid var(--amber)",
                background: mic.listening ? "var(--amber)" : "transparent",
              }}
            >
              {mic.listening && mic.mode === "live" ? "Stop" : "Speak"}
            </button>
          )}

          <button
            onClick={onReplay}
            className="px-6 py-4 text-[13px] font-semibold uppercase tracking-[0.14em]"
            style={{
              color: "var(--bone-dim)",
              border: "1px solid var(--bone-faint)",
              background: "transparent",
            }}
          >
            Replay call
          </button>

          <p className="text-[13px]" style={{ color: "var(--bone-faint)" }}>
            {ready ? (
              <>
                Or press <strong style={{ color: "var(--bone-dim)" }}>space</strong>
              </>
            ) : (
              "Waiting on the last known point and the ring radius"
            )}
          </p>
        </div>
      </div>
    </div>
  );
}
