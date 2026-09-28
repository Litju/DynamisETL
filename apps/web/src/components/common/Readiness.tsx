import type { ServerStage } from "@/lib/catalog-model";
import { cn } from "@/lib/cn";

/**
 * Readiness is three separate facts, never one conflated status:
 *
 *   upstream  — the provider has it;
 *   server    — registered → materialized → ready on the Dynamis data plane;
 *   browser   — its analytical data is loaded in this session.
 *
 * Every state is text + shape + colour; colour is never the only signal.
 */

export type ReadinessGlyphKind =
  | "upstream"
  | "registered"
  | "materialized"
  | "ready"
  | "loaded"
  | "blocked"
  | "unavailable";

const GLYPH_TOKEN: Record<ReadinessGlyphKind, string> = {
  upstream: "var(--d-ready-upstream)",
  registered: "var(--d-ready-registered)",
  materialized: "var(--d-ready-materialized)",
  ready: "var(--d-ready-ready)",
  loaded: "var(--d-ready-loaded)",
  blocked: "var(--d-ready-blocked)",
  unavailable: "var(--d-unavailable)",
};

/** 10 px shape glyph: dashed ring → ring → half → filled → diamond. */
export function ReadinessGlyph({ kind, className }: { kind: ReadinessGlyphKind; className?: string | undefined }) {
  const color = GLYPH_TOKEN[kind];
  return (
    <svg
      viewBox="0 0 10 10"
      aria-hidden="true"
      data-readiness={kind}
      className={cn("size-2.5 shrink-0", className)}
      style={{ color }}
    >
      {kind === "upstream" ? (
        <circle cx="5" cy="5" r="3.75" fill="none" stroke="currentColor" strokeWidth="1.2" strokeDasharray="1.6 1.4" />
      ) : kind === "registered" ? (
        <>
          <circle cx="5" cy="5" r="3.75" fill="none" stroke="currentColor" strokeWidth="1.2" />
          <circle cx="5" cy="5" r="1" fill="currentColor" />
        </>
      ) : kind === "materialized" ? (
        <>
          <circle cx="5" cy="5" r="3.75" fill="none" stroke="currentColor" strokeWidth="1.2" />
          <path d="M5 1.25 A3.75 3.75 0 0 1 5 8.75 Z" fill="currentColor" />
        </>
      ) : kind === "ready" ? (
        <circle cx="5" cy="5" r="4" fill="currentColor" />
      ) : kind === "loaded" ? (
        <path d="M5 0.8 L9.2 5 L5 9.2 L0.8 5 Z" fill="currentColor" />
      ) : kind === "blocked" ? (
        <path d="M1.5 1.5 L8.5 8.5 M8.5 1.5 L1.5 8.5" stroke="currentColor" strokeWidth="1.4" />
      ) : (
        <path d="M1.5 5 L8.5 5" stroke="currentColor" strokeWidth="1.4" />
      )}
    </svg>
  );
}

export function serverGlyph(stage: ServerStage, upstream: boolean): ReadinessGlyphKind {
  if (stage === "ready") return "ready";
  if (stage === "materialized") return "materialized";
  if (stage === "registered") return "registered";
  return upstream ? "upstream" : "unavailable";
}

export const SERVER_TEXT: Record<ServerStage, string> = {
  none: "Not materialized",
  registered: "Registered · not materialized",
  materialized: "Materialized · not ready",
  ready: "Ready server-side",
};

/** Compact server-readiness statement for rows and cards. */
export function ServerReadiness({
  stage,
  upstream,
  compact = false,
  className,
}: {
  stage: ServerStage;
  upstream: boolean;
  compact?: boolean;
  className?: string;
}) {
  const kind = serverGlyph(stage, upstream);
  const label = stage === "ready"
    ? compact ? "Ready" : "Ready server-side"
    : stage === "materialized"
      ? compact ? "Materialized" : SERVER_TEXT.materialized
      : upstream
        ? compact ? "Upstream only" : "Upstream available · not materialized"
        : "Unavailable";
  return (
    <span
      className={cn("inline-flex items-center gap-1.5 whitespace-nowrap text-[11px]", className)}
      style={{ color: stage === "ready" ? "var(--d-text-secondary)" : "var(--d-text-muted)" }}
      title={`Upstream ${upstream ? "available" : "unavailable"} · server ${SERVER_TEXT[stage].toLowerCase()}`}
    >
      <ReadinessGlyph kind={kind} />
      {label}
    </span>
  );
}

/** The browser-side fact: is this context's analytical data loaded here? */
export function BrowserReadiness({ state, className }: { state: "loaded" | "loading" | "not-loaded"; className?: string }) {
  return (
    <span className={cn("inline-flex items-center gap-1.5 whitespace-nowrap text-[11px] text-text-muted", className)}>
      <ReadinessGlyph kind={state === "loaded" ? "loaded" : "upstream"} className={state === "loading" ? "opacity-70" : undefined} />
      {state === "loaded" ? "Loaded in browser" : state === "loading" ? "Loading in browser" : "Not yet loaded"}
    </span>
  );
}

/**
 * Four-step ladder: upstream → registered → materialized → ready. Reached
 * steps are filled; the label states the furthest step in words.
 */
export function ReadinessLadder({
  stage,
  upstream,
  className,
}: {
  stage: ServerStage;
  upstream: boolean;
  className?: string;
}) {
  const reached = [
    upstream,
    stage === "registered" || stage === "materialized" || stage === "ready",
    stage === "materialized" || stage === "ready",
    stage === "ready",
  ];
  const labels = ["Upstream", "Registered", "Materialized", "Ready"];
  return (
    <span
      className={cn("inline-flex items-center gap-[3px]", className)}
      role="img"
      aria-label={`Readiness: ${labels.filter((_, index) => reached[index]).join(" → ") || "unavailable"}`}
    >
      {reached.map((on, index) => (
        <span
          key={labels[index]}
          title={`${labels[index]}: ${on ? "yes" : "no"}`}
          className="h-[3px] w-3 rounded-full"
          style={{
            background: on
              ? index === 3
                ? "var(--d-ready-ready)"
                : index === 2
                  ? "var(--d-ready-materialized)"
                  : index === 1
                    ? "var(--d-ready-registered)"
                    : "var(--d-ready-upstream)"
              : "var(--d-surface-4)",
          }}
        />
      ))}
    </span>
  );
}
