"use client";

/**
 * The opening screen. Purely decorative — no map, no terrain, no live data.
 *
 * A LIGHTHOUSE, ON REQUEST. Note that CONTRACT §8 and the frontend brief both
 * argue the other way: "a searchlight, not a lighthouse — a lighthouse warns
 * ships away from hazards and this product finds people in them." That is a
 * real objection and someone may raise it. It was overridden deliberately, not
 * missed. If it ever needs reverting, this file is the only thing that changes.
 *
 * The constraints from the brief still hold:
 *   - ONE moving system. The lamp turns; the lit panel edge and the lens flare
 *     are driven by that same cycle at fixed phase offsets, so nothing animates
 *     on its own schedule.
 *   - Warm light, not white — the same amber the probability field uses later.
 *   - CSS and SVG, not canvas. No render loop on a screen that does not need one.
 *   - The glow is pushed harder than looks right on a laptop, because projectors
 *     crush soft light to nothing.
 *
 * SCALE IS THE POINT. The tower runs off the bottom of the frame and the lantern
 * sits high, so the structure reads as monumental and the viewer as standing
 * under it. A lighthouse drawn small is a pictogram; drawn at this size it is a
 * building that exists to find people in the dark, which is the whole reason the
 * metaphor was worth having.
 *
 * HOW THE ROTATION WORKS, AND WHY IT IS NOT A PLAIN rotate().
 * Rotating a beam 360° is wrong in a side elevation: a lighthouse turns in a
 * horizontal plane, so from the side its beam never points up at the sky or down
 * through its own base. What a side view actually shows is FORESHORTENING — a
 * beam at angle θ from the viewer projects to length cos θ. So each beam holds a
 * heading and animates `rotate(-SWING·cos θ) scaleX(cos θ)` about the lamp:
 *
 *   θ = 0°    full length out to the right, swung up by SWING     -> panel lights
 *   θ = 90°   collapsed to nothing, level, pointing at the viewer  -> flare fires
 *   θ = 180°  full length out to the left, swung down by SWING
 *
 * The scale term gives the foreshortening and the rotation term gives the
 * visible swing, so it reads as a turning light rather than a bar that grows.
 *
 * Two beams 180° apart, as a real bi-directional Fresnel lens throws, so one is
 * always sweeping the panel side while the other is behind the tower. The panel
 * beat therefore lands twice a revolution and the flare once, which keeps the
 * flare the rare event rather than a strobe.
 *
 * ON THE FLARE. Built as an optical artifact rather than a decorative bloom:
 * additive blending, an anamorphic streak, diffraction spikes, and ghosts spaced
 * along the axis from the lamp through the centre of the frame — which is where
 * a real lens puts them. That is the difference between this and the "neon glow"
 * the brief says to cut on sight.
 */

const CYCLE_S = 9;

/** Lamp position, in viewport units. Everything else is placed off these. */
const LAMP_X = 27;
const LAMP_Y = 23;

/** Degrees the beam swings either side of level across a full turn. */
const SWING = 13;

// --- the tower, and its lean -------------------------------------------------
// The drawing is authored in a 420x1080 viewBox and rendered at SCALE, so one
// set of path coordinates serves any size. Stroke is non-scaling, which keeps
// the linework a hairline at any scale rather than fattening into a cartoon.
const VB_W = 420;
const VB_H = 1080;
const SCALE = 1.46;

/** Pisa leans about 4°. Positive tilts the top toward the copy. */
const LEAN = 5;
/** It pivots about the base, the way a real settling tower does. */
const PIVOT: [number, number] = [210, 1080];
/** Where the lantern sits before the lean is applied. */
const LANTERN: [number, number] = [210, 132];

/**
 * The lantern after the lean, in rendered pixels. The beam originates from
 * --lamp-x/--lamp-y, so the SVG has to be offset by exactly this much or the
 * light detaches from the lamp as soon as the tower tilts.
 */
const [SVG_LAMP_X, SVG_LAMP_Y] = (() => {
  const r = (LEAN * Math.PI) / 180;
  const dx = LANTERN[0] - PIVOT[0];
  const dy = LANTERN[1] - PIVOT[1];
  return [
    (PIVOT[0] + dx * Math.cos(r) - dy * Math.sin(r)) * SCALE,
    (PIVOT[1] + dx * Math.sin(r) + dy * Math.cos(r)) * SCALE,
  ];
})();

const SVG_W = VB_W * SCALE;
const SVG_H = VB_H * SCALE;

/**
 * Flare ghosts, spaced along the lamp -> frame-centre axis and continuing past
 * it. `k` is the distance along that axis as a multiple of lamp->centre.
 */
const CENTRE_X = 50;
const CENTRE_Y = 50;
const GHOSTS: Array<{ k: number; size: number; alpha: number; hue: string; ring?: boolean }> = [
  { k: 0.28, size: 34, alpha: 0.1, hue: "232,163,61" },
  { k: 0.52, size: 84, alpha: 0.07, hue: "232,163,61", ring: true },
  { k: 0.78, size: 24, alpha: 0.17, hue: "255,200,120" },
  { k: 1.04, size: 130, alpha: 0.05, hue: "232,163,61", ring: true },
  { k: 1.32, size: 46, alpha: 0.13, hue: "255,120,80" },
  { k: 1.66, size: 190, alpha: 0.045, hue: "232,163,61" },
  { k: 1.98, size: 62, alpha: 0.09, hue: "255,90,71" },
];

/** cos θ sampled every 22.5°, as [percent, cos] — the beam keyframe basis. */
const SAMPLES = Array.from({ length: 17 }, (_, i) => {
  const pct = i * 6.25;
  const c = Math.cos((2 * Math.PI * i) / 16);
  return { pct, c: Math.abs(c) < 1e-6 ? 0 : c };
});

/**
 * transform: rotate(-SWING·cos θ) scaleX(cos θ), plus opacity sqrt|cos θ| so the
 * shaft fades as it turns edge-on. Without that fade the collapsed wedge leaves
 * a hard sliver standing over the lantern, which reads as a rendering fault
 * rather than as a beam pointing at you.
 */
function scanKeyframes(name: string, sign: 1 | -1): string {
  const rows = SAMPLES.map(({ pct, c }) => {
    const s = sign * c;
    const sx = Math.abs(s) < 1e-6 ? sign * 0.001 : s;
    return (
      `    ${pct}% { transform: rotate(${(-SWING * s).toFixed(2)}deg) ` +
      `scaleX(${sx.toFixed(3)}); opacity: ${Math.sqrt(Math.abs(c)).toFixed(2)}; }`
    );
  });
  return `  @keyframes ${name} {\n${rows.join("\n")}\n  }`;
}

export default function Landing({ onBegin }: { onBegin(): void }) {
  return (
    <div
      className="sl-stage relative h-full w-full overflow-hidden"
      style={{ background: "var(--ground)" }}
    >
      <style>{`
        .sl-stage {
          --lamp-x: ${LAMP_X}vw;
          --lamp-y: ${LAMP_Y}vh;
          --cycle: ${CYCLE_S}s;
          /* Where the copy column starts, so the beam can be stopped there
             rather than washing across the text it is meant to illuminate. */
          --panel-left: max(0px, calc(91vw - 460px));
        }

${scanKeyframes("sl-scan-a", 1)}
${scanKeyframes("sl-scan-b", -1)}

        /* The panel's edge, lit whenever a beam reaches full extension to the
           right — twice a revolution, once per lens face. */
        @keyframes sl-incident {
          0%   { opacity: 1; }
          11%  { opacity: 0.04; }
          39%  { opacity: 0.04; }
          50%  { opacity: 1; }
          61%  { opacity: 0.04; }
          89%  { opacity: 0.04; }
          100% { opacity: 1; }
        }
        /* The flare, fired as the beam turns through the viewer at θ=90°. */
        @keyframes sl-flare {
          0%, 13%   { opacity: 0; }
          21%       { opacity: 0.8; }
          25%       { opacity: 1; }
          30%       { opacity: 0.72; }
          38%, 100% { opacity: 0; }
        }
        /* The lamp blooms on the same beat. It never goes dark: the lens is lit
           throughout, it is only aimed elsewhere. */
        @keyframes sl-bloom {
          0%, 12%   { opacity: 0.42; transform: translate(-50%, -50%) scale(1); }
          25%       { opacity: 1;    transform: translate(-50%, -50%) scale(1.7); }
          40%, 100% { opacity: 0.42; transform: translate(-50%, -50%) scale(1); }
        }

        .sl-scan-a { animation: sl-scan-a   var(--cycle) linear infinite; }
        .sl-scan-b { animation: sl-scan-b   var(--cycle) linear infinite; }
        .sl-edge   { animation: sl-incident var(--cycle) linear infinite; }
        .sl-flare  { animation: sl-flare    var(--cycle) linear infinite; }
        .sl-bloom  { animation: sl-bloom    var(--cycle) linear infinite; }

        /* Frozen just off the flare beat, so a viewer who asked for less motion
           still gets the designed image rather than a dark screen. */
        @media (prefers-reduced-motion: reduce) {
          .sl-scan-a { animation: none; transform: rotate(-9deg) scaleX(0.72); opacity: 0.85; }
          .sl-scan-b { animation: none; transform: rotate(9deg) scaleX(-0.72); opacity: 0.85; }
          .sl-edge   { animation: none; opacity: 0.8; }
          .sl-flare  { animation: none; opacity: 0.45; }
          .sl-bloom  { animation: none; opacity: 0.85;
                       transform: translate(-50%, -50%) scale(1.35); }
        }
      `}</style>

      {/* Atmosphere. Static: the light is the only thing that moves. Without it
          the beams end in hard vacuum and read as flat painted wedges. */}
      <div
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            `radial-gradient(130% 100% at ${LAMP_X}vw ${LAMP_Y}vh, rgba(232,163,61,0.13), transparent 64%)`,
        }}
      />

      {/* --- the two lens faces ----------------------------------------------
          Clipped to stop at the copy column: the panel is a solid thing the
          light falls on, so the beam should end there rather than wash over the
          words. That is also the collision the brief asks for. */}
      <div
        className="pointer-events-none absolute inset-y-0 left-0 overflow-hidden"
        style={{
          width: "var(--panel-left)",
          // Feathered rather than cut. A hard edge where the clip ends reads as
          // a clipping artifact; this dissolves the shaft as it arrives, and the
          // lit panel edge supplies the arrival itself.
          maskImage:
            "linear-gradient(90deg, #000 0%, #000 62%, rgba(0,0,0,0.55) 84%, transparent 100%)",
          WebkitMaskImage:
            "linear-gradient(90deg, #000 0%, #000 62%, rgba(0,0,0,0.55) 84%, transparent 100%)",
        }}
      >
        {(["sl-scan-a", "sl-scan-b"] as const).map((cls) => (
          <div
            key={cls}
            className={`${cls} absolute`}
            style={{
              left: "var(--lamp-x)",
              top: "var(--lamp-y)",
              width: "170vw",
              height: "72vh",
              marginTop: "-36vh",
              transformOrigin: "0% 50%",
              // A wedge opening away from the lamp. Narrow: a wide one reads as
              // a painted shape rather than a shaft of light.
              clipPath: "polygon(0% 48.7%, 100% 0%, 100% 100%, 0% 51.3%)",
              // Near-white at the lamp, falling to amber and out. A beam that is
              // amber along its whole length reads as a brown wedge, not light.
              background:
                "linear-gradient(90deg, rgba(255,244,224,0.62) 0%, rgba(246,198,116,0.30) 8%, rgba(232,163,61,0.13) 26%, rgba(232,163,61,0.04) 48%, rgba(232,163,61,0) 72%)",
              filter: "blur(6px)",
              mixBlendMode: "screen",
              willChange: "transform, opacity",
            }}
          />
        ))}
      </div>

      {/* --- the headland the tower stands on ---------------------------------
          Gives the structure something to be founded on, and a base line for
          the eye. Kept almost black: it is scale, not scenery. */}
      <svg
        className="pointer-events-none absolute inset-x-0 bottom-0"
        height="190"
        viewBox="0 0 1600 190"
        preserveAspectRatio="none"
        aria-hidden
        style={{ width: "100%" }}
      >
        <path
          d="M0 78 L120 54 L240 66 L360 40 L470 58 L560 44 L700 72 L860 58 L1010 84 L1180 66 L1340 90 L1480 74 L1600 96 L1600 190 L0 190 Z"
          fill="#0C0B08"
        />
        <path
          d="M0 78 L120 54 L240 66 L360 40 L470 58 L560 44 L700 72 L860 58 L1010 84 L1180 66 L1340 90 L1480 74 L1600 96"
          fill="none"
          stroke="var(--bone-faint)"
          strokeWidth="1"
          opacity="0.5"
        />
      </svg>

      {/* --- the tower --------------------------------------------------------
          Monumental, running off the bottom of the frame. Silhouette, so the
          light reads as coming from the lantern rather than floating over it. */}
      <svg
        className="pointer-events-none absolute"
        style={{
          left: `calc(var(--lamp-x) - ${SVG_LAMP_X}px)`,
          top: `calc(var(--lamp-y) - ${SVG_LAMP_Y}px)`,
        }}
        width={SVG_W}
        height={SVG_H}
        viewBox={`0 0 ${VB_W} ${VB_H}`}
        fill="none"
        aria-hidden
      >
        <g
          transform={`rotate(${LEAN} ${PIVOT[0]} ${PIVOT[1]})`}
          stroke="var(--bone-dim)"
          strokeWidth="1.6"
          fill="#0C0B08"
          // Hairlines at any scale. Without this the linework thickens with the
          // tower and the drawing stops reading as a survey elevation.
          vectorEffect="non-scaling-stroke"
        >
          {/* finial and lightning rod */}
          <path d="M210 14 L210 44" strokeWidth="1.2" />
          <circle cx="210" cy="50" r="5" />
          {/* domed roof */}
          <path d="M146 100 Q210 40 274 100 Z" />
          <path d="M146 100 L274 100" strokeWidth="1.2" />
          {/* lantern room — left unfilled so the lamp inside reads through */}
          <path d="M154 100 L266 100 L266 176 L154 176 Z" fill="none" />
          <path
            d="M172 100 L172 176 M191 100 L191 176 M210 100 L210 176 M229 100 L229 176 M248 100 L248 176"
            strokeWidth="0.9"
            opacity="0.85"
          />
          {/* gallery deck and rail */}
          <path d="M128 176 L292 176 L292 194 L128 194 Z" />
          <path d="M118 194 L302 194" strokeWidth="1.2" />
          <path
            d="M132 194 L132 226 M166 194 L166 226 M210 194 L210 226 M254 194 L254 226 M288 194 L288 226"
            strokeWidth="0.9"
          />
          <path d="M124 226 L296 226" strokeWidth="1.2" />
          {/* corbels under the gallery */}
          <path d="M140 226 L152 250 M210 226 L210 250 M280 226 L268 250" strokeWidth="0.9" opacity="0.7" />
          {/* watch room */}
          <path d="M152 250 L268 250 L272 316 L148 316 Z" />
          {/* the shaft, battered outward all the way down */}
          <path d="M148 316 L272 316 L330 1080 L90 1080 Z" />
          {/* daymark bands */}
          <path d="M162 430 L258 430" strokeWidth="1.1" opacity="0.5" />
          <path d="M172 600 L248 600" strokeWidth="1.1" opacity="0.5" />
          <path d="M182 770 L238 770" strokeWidth="1.1" opacity="0.5" />
          <path d="M192 940 L228 940" strokeWidth="1.1" opacity="0.5" />
          {/* windows, narrowing with the taper */}
          <path d="M203 352 L217 352 L217 380 L203 380 Z" strokeWidth="0.9" opacity="0.75" />
          <path d="M201 500 L219 500 L219 532 L201 532 Z" strokeWidth="0.9" opacity="0.75" />
          <path d="M199 672 L221 672 L221 708 L199 708 Z" strokeWidth="0.9" opacity="0.75" />
        </g>
      </svg>

      {/* --- the lamp --------------------------------------------------------- */}
      <div
        className="sl-bloom pointer-events-none absolute"
        style={{
          left: "var(--lamp-x)",
          top: "var(--lamp-y)",
          width: 200,
          height: 200,
          borderRadius: "50%",
          background:
            "radial-gradient(circle, rgba(255,240,212,0.98) 0%, rgba(232,163,61,0.6) 20%, rgba(232,163,61,0.16) 46%, transparent 72%)",
          mixBlendMode: "screen",
        }}
      />

      {/* --- lens flare -------------------------------------------------------
          Additive, and laid out the way a lens actually puts it: a bloom at the
          source, an anamorphic streak across it, diffraction spikes, and ghosts
          spaced along the axis from the lamp through the centre of the frame. */}
      <div
        className="sl-flare pointer-events-none absolute inset-0"
        style={{ mixBlendMode: "screen" }}
      >
        <div
          style={{
            position: "absolute",
            left: "var(--lamp-x)",
            top: "var(--lamp-y)",
            width: "180vw",
            height: 4,
            transform: "translate(-50%, -50%)",
            background:
              "linear-gradient(90deg, transparent 0%, rgba(232,163,61,0.5) 33%, rgba(255,238,208,0.98) 50%, rgba(232,163,61,0.5) 67%, transparent 100%)",
            filter: "blur(3px)",
          }}
        />
        <div
          style={{
            position: "absolute",
            left: "var(--lamp-x)",
            top: "var(--lamp-y)",
            width: "130vw",
            height: 30,
            transform: "translate(-50%, -50%)",
            background:
              "linear-gradient(90deg, transparent 0%, rgba(232,163,61,0.22) 40%, rgba(232,163,61,0.32) 50%, rgba(232,163,61,0.22) 60%, transparent 100%)",
            filter: "blur(18px)",
          }}
        />
        {[16, -16, 72, -72].map((deg) => (
          <div
            key={deg}
            style={{
              position: "absolute",
              left: "var(--lamp-x)",
              top: "var(--lamp-y)",
              width: Math.abs(deg) > 45 ? "40vw" : "74vw",
              height: 2,
              transform: `translate(-50%, -50%) rotate(${deg}deg)`,
              background:
                "linear-gradient(90deg, transparent, rgba(255,224,178,0.42) 50%, transparent)",
              filter: "blur(2px)",
            }}
          />
        ))}
        <div
          style={{
            position: "absolute",
            left: "var(--lamp-x)",
            top: "var(--lamp-y)",
            width: 360,
            height: 360,
            transform: "translate(-50%, -50%)",
            borderRadius: "50%",
            background:
              "radial-gradient(circle, rgba(255,242,220,0.62) 0%, rgba(232,163,61,0.24) 28%, transparent 68%)",
          }}
        />
        {GHOSTS.map((g, i) => {
          const x = LAMP_X + (CENTRE_X - LAMP_X) * g.k;
          const y = LAMP_Y + (CENTRE_Y - LAMP_Y) * g.k;
          return (
            <div
              key={i}
              style={{
                position: "absolute",
                left: `${x}%`,
                top: `${y}%`,
                width: g.size,
                height: g.size,
                transform: "translate(-50%, -50%)",
                borderRadius: "50%",
                ...(g.ring
                  ? {
                      border: `1px solid rgba(${g.hue},${g.alpha * 3})`,
                      background: `radial-gradient(circle, transparent 58%, rgba(${g.hue},${g.alpha}) 78%, transparent 100%)`,
                    }
                  : {
                      background: `radial-gradient(circle, rgba(${g.hue},${g.alpha * 2.4}) 0%, rgba(${g.hue},${g.alpha}) 45%, transparent 72%)`,
                    }),
                filter: "blur(0.5px)",
              }}
            />
          );
        })}
      </div>

      {/* --- the panel the beam intercepts ------------------------------------ */}
      <div className="relative flex h-full items-center justify-end pr-[9vw]">
        <div className="relative w-[460px] max-w-[46vw]">
          <div
            className="sl-edge pointer-events-none absolute inset-y-0 -left-px w-px"
            style={{
              background:
                "linear-gradient(180deg, transparent, var(--amber) 20%, var(--amber) 80%, transparent)",
              boxShadow: "0 0 26px 1px rgba(232,163,61,0.62)",
            }}
          />
          <div
            className="absolute inset-y-0 -left-px w-px"
            style={{ background: "var(--bone-faint)" }}
          />

          <div className="py-2 pl-10">
            <p
              className="eyebrow"
              style={{ letterSpacing: "0.26em", color: "var(--bone-dim)" }}
            >
              Search and rescue decision support
            </p>
            <h1
              className="display mt-5 uppercase leading-[0.88]"
              style={{
                fontSize: "clamp(40px, 4.1vw, 62px)",
                letterSpacing: "-0.03em",
                color: "var(--bone)",
              }}
            >
              Searchlight
            </h1>
            <p
              className="mt-6 max-w-[42ch] text-[19px] leading-[1.6]"
              style={{ color: "var(--bone-dim)" }}
            >
              Rescue teams draw rings because published statistics say a hiker is
              usually found within a certain distance. People do not walk in
              circles.
            </p>

            {/* The action is the headline. The wordmark names the product; this
                is the only thing on the screen anyone is meant to DO, so it gets
                the weight — full column width, display type, and the highest
                contrast pairing in the palette. Still a real <button>: keeping
                the semantics costs nothing and keeps it keyboard-reachable. */}
            <button
              onClick={onBegin}
              className="group display mt-9 flex w-full items-center justify-between gap-6 px-8 py-7 text-left uppercase transition-transform"
              style={{
                fontSize: "clamp(19px, 1.85vw, 27px)",
                lineHeight: 1,
                fontWeight: 600,
                letterSpacing: "0.02em",
                color: "var(--ground)",
                background: "var(--bone)",
                border: "1px solid var(--bone)",
              }}
            >
              <span>
                Report a<br />
                missing person
              </span>
              <span
                aria-hidden
                className="shrink-0 transition-transform duration-200 group-hover:translate-x-1.5"
                style={{ fontSize: "1.15em", letterSpacing: 0 }}
              >
                →
              </span>
            </button>

            <p
              className="eyebrow mt-5"
              style={{ color: "var(--bone-dim)" }}
            >
              Or press space
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
