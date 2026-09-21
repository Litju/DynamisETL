import type { ReactNode } from "react";

import { ApiError } from "@/lib/api/client";
import { cn } from "@/lib/cn";

export type PanelStateKind = "loading" | "empty" | "error" | "unavailable" | "blocked";

const STATE_LABELS: Record<PanelStateKind, string> = {
  loading: "Loading",
  empty: "No data",
  error: "API error",
  unavailable: "Unavailable for this source",
  blocked: "Quality-blocked",
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
  return (
    <div
      role={state === "error" ? "alert" : "status"}
      data-state={state}
      className={cn(
        "flex h-full min-h-24 flex-col items-center justify-center gap-2 p-6 text-center",
        className,
      )}
    >
      <span className="t-section text-text-muted">
        {STATE_LABELS[state]}
      </span>
      {title ? <p className="text-[13px] text-text-secondary">{title}</p> : null}
      {detail ? <div className="max-w-md text-[12px] text-text-muted">{detail}</div> : null}
      {action}
    </div>
  );
}

/** Loading placeholder keeps panel geometry but never mimics scientific values. */
export function LoadingPanel({ label = "Loading" }: { label?: string }) {
  return (
    <div role="status" className="flex h-full min-h-24 flex-col gap-3 p-4" aria-label={label}>
      <div className="h-3 w-40 animate-pulse rounded bg-surface-3" />
      <div className="h-24 w-full animate-pulse rounded bg-surface-2" />
      <div className="h-3 w-64 animate-pulse rounded bg-surface-2" />
      <span className="sr-only">{label}</span>
    </div>
  );
}

export function ErrorPanel({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message =
    error instanceof ApiError
      ? `${error.message} (HTTP ${error.status}${error.state ? `, ${error.state}` : ""})`
      : error instanceof Error
        ? error.message
        : "unknown error";
  return (
    <StatePanel
      state="error"
      title="The API request failed."
      detail={<span className="mono">{message}</span>}
      action={
        onRetry ? (
          <button
            type="button"
            onClick={onRetry}
            className="rounded-control border border-border-strong px-2 py-1 text-[12px] hover:bg-surface-3"
          >
            Retry
          </button>
        ) : null
      }
    />
  );
}
