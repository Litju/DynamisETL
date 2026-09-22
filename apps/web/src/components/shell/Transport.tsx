import { useQuery } from "@tanstack/react-query";
import { Pause, Play, SkipBack, SkipForward } from "lucide-react";

import { useAnalysisContext } from "@/lib/analysis-context";
import { qualityQuery } from "@/lib/api/queries";
import { cn } from "@/lib/cn";
import { effectiveTimeNs, useAnalysisStore } from "@/lib/state/analysis";
import type { QualityIssuePage } from "@/api/types";
import {
  formatClockNs,
  formatDurationNs,
  stepFrames,
  tryParseNs,
} from "@/lib/time";

const RATES = [0.25, 0.5, 1, 2, 4] as const;
const DEFAULT_STEP_RATE_HZ = 25;

export interface QualitySummary {
  readonly quarantined: number;
  readonly warnings: number;
  readonly infos: number;
}

/** Deterministic quality counts for the transport ribbon. */
export function summarizeQuality(rows: QualityIssuePage["rows"]): QualitySummary {
  let quarantined = 0;
  let warnings = 0;
  let infos = 0;
  for (const row of rows) {
    if (row.state === "QUARANTINED" || row.severity === "ERROR") quarantined += 1;
    else if (row.severity === "WARNING") warnings += 1;
    else infos += 1;
  }
  return { quarantined, warnings, infos };
}

export function qualityRibbonText(summary: QualitySummary | null): string {
  if (summary === null) return "quality context unavailable";
  if (summary.quarantined === 0 && summary.warnings === 0 && summary.infos === 0) {
    return "no flagged intervals in the current selection";
  }
  const parts: string[] = [];
  if (summary.quarantined > 0) parts.push(`${summary.quarantined} quarantined`);
  if (summary.warnings > 0) parts.push(`${summary.warnings} warning`);
  if (summary.infos > 0) parts.push(`${summary.infos} info`);
  return parts.join(" · ");
}

/**
 * Persistent transport: playhead, stepping, playback rate and the committed
 * range read-out. Exists on every route; controls are disabled outside a
 * laboratory context so no durable time can be committed without a session.
 */
export function Transport({ nominalRateHz }: { nominalRateHz: number | null }) {
  const context = useAnalysisContext();
  const committedTimeNs = useAnalysisStore((state) => state.committedTimeNs);
  const committedRangeNs = useAnalysisStore((state) => state.committedRangeNs);
  const playing = useAnalysisStore((state) => state.playing);
  const playbackStatus = useAnalysisStore((state) => state.playbackStatus);
  const playbackRate = useAnalysisStore((state) => state.playbackRate);
  const setPlaying = useAnalysisStore((state) => state.setPlaying);
  const setPlaybackRate = useAnalysisStore((state) => state.setPlaybackRate);
  const setPlayhead = useAnalysisStore((state) => state.setPlayhead);

  const effective = useAnalysisStore(effectiveTimeNs);
  const disabled = context === null;
  const stepRate = nominalRateHz ?? DEFAULT_STEP_RATE_HZ;
  const quality = useQuery({
    ...qualityQuery({
      datasetId: context?.datasetId,
      sessionId: context?.sessionId,
      limit: 200,
    }),
    enabled: context !== null,
  });
  const qualitySummary = quality.data ? summarizeQuality(quality.data.rows) : null;

  const commit = (tNs: bigint) => {
    setPlayhead(tNs);
    context?.commitTime(tNs);
  };

  const togglePlaying = () => {
    const next = !playing;
    setPlaying(next);
    if (!next && context) {
      const now = effectiveTimeNs(useAnalysisStore.getState());
      if (now !== null) context.commitTime(now);
    }
  };

  return (
    <footer
      aria-label="Transport and timeline"
      className="flex h-12 shrink-0 items-center gap-3 border-t border-border-subtle bg-surface-0 px-3"
    >
      <div className="flex items-center gap-1">
        <button
          type="button"
          aria-label="Step back one frame"
          title="Step back one frame (←)"
          disabled={disabled}
          onClick={() => {
            if (effective === null) return;
            commit(stepFrames(effective, -1, stepRate));
          }}
          className="flex size-7 items-center justify-center rounded-control text-text-secondary hover:bg-surface-2 disabled:opacity-40"
        >
          <SkipBack size={14} aria-hidden="true" />
        </button>
        <button
          type="button"
          aria-label={playing ? "Pause playback" : "Play"}
          title="Play/pause (Space)"
          disabled={disabled}
          onClick={togglePlaying}
          className="flex size-7 items-center justify-center rounded-control border border-border-strong text-text-primary hover:bg-surface-2 disabled:opacity-40"
        >
          {playing ? (
            <Pause size={14} aria-hidden="true" />
          ) : (
            <Play size={14} aria-hidden="true" />
          )}
        </button>
        <button
          type="button"
          aria-label="Step forward one frame"
          title="Step forward one frame (→)"
          disabled={disabled}
          onClick={() => {
            if (effective === null) return;
            commit(stepFrames(effective, 1, stepRate));
          }}
          className="flex size-7 items-center justify-center rounded-control text-text-secondary hover:bg-surface-2 disabled:opacity-40"
        >
          <SkipForward size={14} aria-hidden="true" />
        </button>
      </div>

      <label className="t-label flex items-center gap-1 text-text-muted">
        rate
        <select
          aria-label="Playback rate"
          disabled={disabled}
          value={playbackRate}
          onChange={(event) => setPlaybackRate(Number(event.target.value))}
          className="mono rounded-control border border-border-subtle bg-surface-1 px-1 py-0.5 text-[11px] text-text-secondary"
        >
          {RATES.map((rate) => (
            <option key={rate} value={rate}>
              {rate}×
            </option>
          ))}
        </select>
      </label>

      <div className="flex items-baseline gap-4">
        <div>
          <span className="t-section mr-2 text-text-muted">
            playhead
          </span>
          <span className="t-value mono tabular">
            {effective !== null ? formatClockNs(effective) : "—"}
          </span>
          <span className="mono ml-2 text-[10px] text-text-muted">
            {effective !== null ? `${effective} ns` : "unavailable"}
          </span>
        </div>
        <div>
          <span className="t-section mr-2 text-text-muted">range</span>
          <span className="mono text-[12px] tabular text-text-secondary">
            {committedRangeNs
              ? `${formatDurationNs(committedRangeNs.toNs - committedRangeNs.fromNs)}`
              : "none"}
          </span>
        </div>
        <div>
          <span className="t-section mr-2 text-text-muted">
            committed
          </span>
          <span className="mono text-[12px] tabular text-text-secondary">
            {committedTimeNs !== null ? formatClockNs(committedTimeNs) : "—"}
          </span>
        </div>
        {playbackStatus === "buffering" ? (
          <span data-testid="playback-buffering" className="t-label text-quality-warning">
            BUFFERING · waiting for exact next chunk
          </span>
        ) : playbackStatus === "ended" ? (
          <span data-testid="playback-ended" className="t-label text-text-muted">end of artifact</span>
        ) : null}
      </div>

      <div
        className={cn(
          "t-label ml-auto flex h-6 min-w-64 flex-1 items-center gap-2 rounded-control border border-border-subtle bg-surface-1 px-2 text-text-muted",
        )}
        title="Quality and availability ribbon: quarantined intervals, pose availability, detected/extrapolated tracking"
      >
        <span className="t-section">quality ribbon</span>
        <span className="truncate">
          {disabled
            ? "open a laboratory session to see availability"
            : quality.isPending
              ? "loading quality context"
              : quality.isError
                ? "quality context unavailable"
                : qualityRibbonText(qualitySummary)}
        </span>
      </div>
    </footer>
  );
}

/** Read a durable playhead from URL text without throwing inside render. */
export function parseDurableTime(text: string | undefined | null): bigint | null {
  return tryParseNs(text ?? undefined);
}
