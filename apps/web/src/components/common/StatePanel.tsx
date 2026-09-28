import {
  CircleDashed,
  CircleOff,
  CloudOff,
  FileWarning,
  Filter,
  Hourglass,
  Loader,
  SearchX,
  ShieldAlert,
  ShieldX,
  TimerOff,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";
import type { ReactNode } from "react";

import { ApiError } from "@/lib/api/client";
import { cn } from "@/lib/cn";

/**
 * World-aware states (RES-112 UX §4, RES-129 §8): the system says *why*
 * nothing is shown whenever it knows, never a generic "no data". Every state
 * is text + glyph + tone; colour is never the only signal.
 */
export type PanelStateKind =
  | "loading"
  | "preparing"
  | "empty"
  | "error"
  | "api_unavailable"
  | "unavailable"
  | "not_found"
  | "blocked"
  | "unsupported"
  | "not_materialized"
  | "upstream"
  | "artifact_mismatch"
  | "no_frame"
  | "filtered"
  | "rights";

const STATE_LABELS: Record<PanelStateKind, string> = {
  loading: "Loading",
  preparing: "Preparing analytical context",
  empty: "No data",
  error: "API error",
  api_unavailable: "API unavailable",
  unavailable: "Unavailable for this source",
  not_found: "Not found",
  blocked: "Quality-blocked",
  unsupported: "Unsupported by this source",
  not_materialized: "Not materialized",
  upstream: "Upstream available · not materialized",
  artifact_mismatch: "Artifact missing or mismatched",
  no_frame: "No data at this time",
  filtered: "Filtered out",
  rights: "Rights-restricted",
};

const STATE_GLYPH: Record<PanelStateKind, LucideIcon> = {
  loading: Loader,
  preparing: Hourglass,
  empty: CircleDashed,
  error: TriangleAlert,
  api_unavailable: CloudOff,
  unavailable: CircleOff,
  not_found: SearchX,
  blocked: ShieldX,
  unsupported: CircleOff,
  not_materialized: CircleDashed,
  upstream: CircleDashed,
  artifact_mismatch: FileWarning,
  no_frame: TimerOff,
  filtered: Filter,
  rights: ShieldAlert,
};

const STATE_TONE: Partial<Record<PanelStateKind, string>> = {
  error: "var(--d-danger)",
  api_unavailable: "var(--d-danger)",
  artifact_mismatch: "var(--d-danger)",
  blocked: "var(--d-warning)",
  rights: "var(--d-warning)",
};

export function StatePanel({
  state,
  title,
  detail,
  action,
  className,
}: {
  state: PanelStateKind;
  title?: string;
  detail?: ReactNode;
  action?: ReactNode;
  className?: string;
}) {
  const Glyph = STATE_GLYPH[state];
  const tone = STATE_TONE[state] ?? "var(--d-text-muted)";
  return (
    <div
      role={state === "error" || state === "api_unavailable" ? "alert" : "status"}
      data-state={state}
      className={cn(
        "d-reveal flex h-full min-h-24 flex-col items-center justify-center gap-2 p-6 text-center",
        className,
      )}
    >
      <span
        aria-hidden="true"
        className="mb-1 flex size-9 items-center justify-center rounded-full border"
        style={{ color: tone, borderColor: `color-mix(in oklab, ${tone} 35%, transparent)`, background: `color-mix(in oklab, ${tone} 7%, transparent)` }}
      >
        <Glyph size={16} strokeWidth={1.75} className={state === "loading" ? "motion-safe:animate-spin" : undefined} />
      </span>
      <span className="t-kicker" style={{ color: tone }}>
        {STATE_LABELS[state]}
      </span>
      {title ? <p className="max-w-md text-[13.5px] font-medium text-text-primary">{title}</p> : null}
      {detail ? <div className="max-w-md text-[12px] leading-relaxed text-text-muted">{detail}</div> : null}
      {action ? <div className="mt-2">{action}</div> : null}
    </div>
  );
}

/** Loading placeholder keeps panel geometry but never mimics scientific values. */
export function LoadingPanel({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" className="flex h-full min-h-24 flex-col gap-3 p-4" aria-label={label}>
      <div className="d-skeleton h-3 w-40" />
      <div className="d-skeleton h-24 w-full" />
      <div className="d-skeleton h-3 w-64" />
      <span className="sr-only">{label}</span>
    </div>
  );
}

/** True when the analytical API itself is unreachable (not a request error). */
export function isApiUnavailable(error: unknown): boolean {
  if (error instanceof ApiError) return error.status === 502 || error.status === 503 || error.status === 504;
  return error instanceof TypeError;
}

export function ErrorPanel({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message =
    error instanceof ApiError
      ? `${error.message} (HTTP ${error.status}${error.state ? `, ${error.state}` : ""})`
      : error instanceof Error
        ? error.message
        : "unknown error";
  const unavailable = isApiUnavailable(error);
  return (
    <StatePanel
      state={unavailable ? "api_unavailable" : "error"}
      title={unavailable ? "The analytical API is not reachable." : "The API request failed."}
      detail={
        unavailable ? (
          <>
            Start it with <span className="mono text-text-secondary">uv run dynamis-serve</span>; no cached value is shown in its place.
            <span className="mono mt-1 block text-[10.5px] text-text-faint">{message}</span>
          </>
        ) : (
          <span className="mono">{message}</span>
        )
      }
      action={
        onRetry ? (
          <button type="button" onClick={onRetry} className="d-btn">
            Retry
          </button>
        ) : null
      }
    />
  );
}
