import { cn } from "@/lib/cn";
import type { WorldId } from "@/lib/worlds";

/**
 * World glyphs: each draws the *grain* its World is built for, not a brand
 * mark. Match — a pitch with tracked positions; Game — a play-by-play score
 * margin; Season — a population strip with one ranked player; Performance —
 * a countermovement-jump force curve. On a hovered/focused parent (`group`)
 * the glyph performs its grain once (positions move, the scan advances, the
 * marker ranks, the curve draws). Static under reduced motion.
 */
export function WorldGlyph({
  world,
  className,
  size = "md",
}: {
  world: WorldId;
  className?: string;
  size?: "sm" | "md" | "lg";
}) {
  const box = size === "sm" ? "h-3.5 w-5" : size === "lg" ? "h-10 w-[3.75rem]" : "h-6 w-9";
  return (
    <svg
      viewBox="0 0 48 32"
      aria-hidden="true"
      data-world={world}
      className={cn("world-glyph shrink-0 overflow-visible", box, className)}
      fill="none"
      stroke="currentColor"
      strokeWidth={size === "sm" ? 2 : 1.25}
      strokeLinecap="round"
      strokeLinejoin="round"
    >
      {world === "match" ? <MatchGlyph detailed={size !== "sm"} /> : null}
      {world === "game" ? <GameGlyph detailed={size !== "sm"} /> : null}
      {world === "season" ? <SeasonGlyph detailed={size !== "sm"} /> : null}
      {world === "performance" ? <PerformanceGlyph /> : null}
    </svg>
  );
}

function MatchGlyph({ detailed }: { detailed: boolean }) {
  return (
    <>
      <rect x="2" y="3" width="44" height="26" rx="2" opacity={0.55} />
      <path d="M24 3 V29" opacity={0.55} />
      {detailed ? <circle cx="24" cy="16" r="4.5" opacity={0.55} /> : null}
      {detailed ? (
        <g className="wg-move-a">
          <path d="M11 11 L15 13" opacity={0.35} strokeDasharray="1.5 1.5" />
          <circle cx="15" cy="13" r="1.6" fill="currentColor" stroke="none" />
        </g>
      ) : null}
      {detailed ? (
        <g className="wg-move-b">
          <circle cx="31" cy="21" r="1.6" fill="currentColor" stroke="none" opacity={0.7} />
        </g>
      ) : null}
      {detailed ? <circle className="wg-move-c" cx="20" cy="22" r="1.6" fill="currentColor" stroke="none" opacity={0.7} /> : null}
      {detailed ? <circle className="wg-ball" cx="27" cy="12" r="1" fill="var(--d-accent)" stroke="none" /> : null}
    </>
  );
}

function GameGlyph({ detailed }: { detailed: boolean }) {
  const bars = [3, -2, 5, 2, -4, -1, 4, 6, 3, -2, 1, 5];
  return (
    <>
      <path d="M2 16 H46" opacity={0.5} />
      {bars.map((value, index) => (
        <path
          key={index}
          d={`M${5 + index * 3.4} 16 V${16 - value * 1.8}`}
          opacity={value > 0 ? 0.9 : 0.45}
          strokeWidth={detailed ? 1.6 : 2}
        />
      ))}
      {detailed ? <path className="wg-scan" d="M4 4 V28" stroke="var(--d-accent)" opacity={0.9} /> : null}
    </>
  );
}

function SeasonGlyph({ detailed }: { detailed: boolean }) {
  const dots = [6, 9, 11, 14, 15, 17, 19, 20, 22, 23, 25, 27, 28, 31, 33, 36, 40];
  return (
    <>
      <path d="M3 22 H45" opacity={0.45} />
      {dots.map((x, index) => (
        <circle
          key={x}
          cx={x}
          cy={16 + ((index * 7) % 5) - 2}
          r={1.1}
          fill="currentColor"
          stroke="none"
          opacity={0.55}
        />
      ))}
      <path d="M24 9 V23" opacity={0.3} strokeDasharray="1.5 1.5" />
      {detailed ? (
        <g className="wg-rank">
          <circle cx="30" cy="16" r="3" stroke="var(--d-accent)" />
          <circle cx="30" cy="16" r="1.2" fill="var(--d-accent)" stroke="none" />
        </g>
      ) : null}
    </>
  );
}

function PerformanceGlyph() {
  return (
    <>
      <path d="M2 24 H46" opacity={0.3} />
      <path
        className="wg-draw"
        pathLength={1}
        d="M2 18 H10 C12 18 12.5 23 14 23 C16 23 16.5 6 20 6 C22 6 22.5 13 23.5 18 L24.5 24 H31 L32 24 C32.5 24 33 3 34.5 3 C35.5 3 35.8 15 37 17 C38 18 39 18 46 18"
      />
    </>
  );
}
