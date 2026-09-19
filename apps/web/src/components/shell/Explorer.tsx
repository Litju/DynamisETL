import { useQuery } from "@tanstack/react-query";
import { Link, useRouterState } from "@tanstack/react-router";
import { ChevronDown, ChevronRight } from "lucide-react";
import { useState, type KeyboardEvent as ReactKeyboardEvent } from "react";

import { StatePanel } from "@/components/common/StatePanel";
import { sessionQuery } from "@/lib/api/queries";
import type { LabSearch } from "@/lib/search";
import { cn } from "@/lib/cn";

/**
 * Session explorer: dataset → session → trial/stream navigation. It reads the
 * server state through Query and selection is durable URL context.
 */
export function Explorer() {
  const location = useRouterState({ select: (state) => state.location });
  const parts = location.pathname.split("/").filter(Boolean);
  const datasetId = parts[0] === "lab" ? (parts[1] ?? null) : null;
  const sessionId = parts[0] === "lab" ? (parts[2] ?? null) : null;
  const search = new URLSearchParams(location.searchStr ?? "");
  const selectedStream = search.get("stream");
  const selectedTrial = search.get("trial");

  if (!datasetId || !sessionId) {
    return (
      <StatePanel
        state="empty"
        title="No session open."
        detail="Choose a dataset and session in the Catalog to open the laboratory explorer."
      />
    );
  }
  return (
    <ExplorerForSession
      datasetId={datasetId}
      sessionId={sessionId}
      selectedStream={selectedStream}
      selectedTrial={selectedTrial}
    />
  );
}

function ExplorerForSession({
  datasetId,
  sessionId,
  selectedStream,
  selectedTrial,
}: {
  datasetId: string;
  sessionId: string;
  selectedStream: string | null;
  selectedTrial: string | null;
}) {
  const query = useQuery(sessionQuery(datasetId, sessionId));
  const [trialsOpen, setTrialsOpen] = useState(true);
  const [streamsOpen, setStreamsOpen] = useState(true);
  const [filter, setFilter] = useState("");

  const handleTreeKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    const items = Array.from(
      event.currentTarget.querySelectorAll<HTMLAnchorElement>("a[data-nav-item]"),
    );
    if (items.length === 0) return;
    event.preventDefault();
    const activeIndex = items.findIndex((item) => item === document.activeElement);
    const delta = event.key === "ArrowDown" ? 1 : -1;
    const nextIndex = activeIndex < 0 ? 0 : Math.min(items.length - 1, Math.max(0, activeIndex + delta));
    items[nextIndex]?.focus();
  };

  if (query.isPending) {
    return <StatePanel state="loading" title="Loading session structure" />;
  }
  if (query.isError) {
    return <StatePanel state="error" title="Session could not be loaded." />;
  }
  const { participants, trials, streams } = query.data;
  const needle = filter.trim().toLowerCase();
  const visibleTrials = trials.filter((trial) =>
    `${trial.label ?? ""} ${trial.trial_id}`.toLowerCase().includes(needle),
  );
  const visibleStreams = streams.filter((stream) =>
    `${stream.stream_id} ${stream.modality} ${stream.measurement_class}`
      .toLowerCase()
      .includes(needle),
  );
  return (
    <div className="p-2 text-[12px]" onKeyDown={handleTreeKeyDown}>
      <div className="mb-2 border-b border-border-subtle pb-2">
        <div className="mono truncate text-[11px] text-text-muted">{datasetId}</div>
        <div className="truncate text-text-secondary">{sessionId}</div>
        <div className="text-[11px] text-text-muted">
          {participants.length} participants · {trials.length} trials · {streams.length} streams
        </div>
        <input
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          placeholder="Filter trials and streams"
          aria-label="Filter session structure"
          className="mt-1 h-6 w-full rounded-control border border-border-subtle bg-surface-0 px-2 text-[11px] outline-none focus:border-accent"
        />
      </div>

      <button
        type="button"
        onClick={() => setTrialsOpen((open) => !open)}
        className="flex w-full items-center gap-1 py-1 text-[11px] uppercase tracking-wider text-text-muted hover:text-text-secondary"
      >
        {trialsOpen ? <ChevronDown size={11} /> : <ChevronRight size={11} />} Trials
      </button>
      {trialsOpen ? (
        <ul className="mb-2">
          {visibleTrials.map((trial) => (
            <li key={trial.trial_id}>
              <Link
                to="/lab/$datasetId/$sessionId"
                params={{ datasetId, sessionId }}
                data-nav-item
                search={(previous: LabSearch) => ({
                  ...previous,
                  trial: trial.trial_id,
                })}
                className={cn(
                  "flex items-center justify-between rounded-control px-2 py-1 hover:bg-surface-2",
                  selectedTrial === trial.trial_id && "bg-surface-3 text-text-primary",
                )}
              >
                <span className="truncate">{trial.label ?? trial.trial_id}</span>
                <span className="mono text-[10px] text-text-muted">{trial.trial_id}</span>
              </Link>
            </li>
          ))}
        </ul>
      ) : null}

      <button
        type="button"
        onClick={() => setStreamsOpen((open) => !open)}
        className="flex w-full items-center gap-1 py-1 text-[11px] uppercase tracking-wider text-text-muted hover:text-text-secondary"
      >
        {streamsOpen ? <ChevronDown size={11} /> : <ChevronRight size={11} />} Streams
      </button>
      {streamsOpen ? (
        <ul>
          {visibleStreams.map((stream) => (
            <li key={stream.stream_id}>
              <Link
                to="/lab/$datasetId/$sessionId"
                params={{ datasetId, sessionId }}
                data-nav-item
                search={(previous: LabSearch) => ({
                  ...previous,
                  stream: stream.stream_id,
                  trial: stream.trial_id ?? previous.trial,
                })}
                className={cn(
                  "flex items-center justify-between gap-2 rounded-control px-2 py-1 hover:bg-surface-2",
                  selectedStream === stream.stream_id && "bg-surface-3 text-text-primary",
                )}
                title={`${stream.modality} · ${stream.measurement_class}`}
              >
                <span className="truncate">{stream.stream_id}</span>
                <span className="mono text-[10px] text-text-muted">
                  {stream.nominal_sampling_rate_hz ?? "?"} Hz
                </span>
              </Link>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
