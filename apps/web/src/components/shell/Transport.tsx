import { useQuery } from "@tanstack/react-query";
import { Pause, Play, SkipBack, SkipForward } from "lucide-react";
import { useRef } from "react";

import { useAnalysisContext } from "@/lib/analysis-context";
import { artifactQuery, qualityQuery, sessionQuery } from "@/lib/api/queries";
import { cn } from "@/lib/cn";
import { canonicalSpan } from "@/lib/dense-window";
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
 * Persistent transport: playhead, stepping, playback rate, a seekable timeline
 * over the selected stream's canonical span and the committed range read-out.
 * Exists on every route; controls are disabled outside a laboratory context so
 * no durable time can be committed without a session.
 *
 * Only the leaf read-outs subscribe to the per-frame playhead, so playback
 * re-renders the clock and the timeline thumb, never the whole footer.
 */
export function Transport({ nominalRateHz }: { nominalRateHz: number | null }) {
  const context = useAnalysisContext();
  const committedRangeNs = useAnalysisStore((state) => state.committedRangeNs);
  const playing = useAnalysisStore((state) => state.playing);
  const playbackStatus = useAnalysisStore((state) => state.playbackStatus);
  const playbackRate = useAnalysisStore((state) => state.playbackRate);
  const playbackDirection = useAnalysisStore((state) => state.playbackDirection);
  const setPlaying = useAnalysisStore((state) => state.setPlaying);
  const setPlaybackRate = useAnalysisStore((state) => state.setPlaybackRate);
  const setPlaybackDirectionAndPlay = useAnalysisStore((state) => state.setPlaybackDirectionAndPlay);
  const setPlayhead = useAnalysisStore((state) => state.setPlayhead);
  const hasTime = useAnalysisStore((state) => effectiveTimeNs(state) !== null);

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
  const step = (frames: number) => {
    const effective = effectiveTimeNs(useAnalysisStore.getState());
    if (effective === null) return;
    commit(stepFrames(effective, frames, stepRate));
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
      <div className="flex shrink-0 items-center gap-1">
        <button
          type="button"
          aria-label="Step back one frame"
          title="Step back one frame (←)"
          disabled={disabled || !hasTime}
          onClick={() => step(-1)}
          className="t-control flex size-7 items-center justify-center rounded-control text-text-secondary hover:bg-surface-2 disabled:opacity-40"
        >
          <SkipBack size={14} aria-hidden="true" />
        </button>
        <button
          type="button"
          aria-label={playing ? "Pause playback" : "Play"}
          title="Play/pause (Space)"
          disabled={disabled}
          onClick={togglePlaying}
          className="t-control flex size-7 items-center justify-center rounded-control border border-border-strong text-text-primary hover:bg-surface-2 disabled:opacity-40"
        >
          {playing ? (
            <Pause size={14} aria-hidden="true" />
          ) : (
            <Play size={14} aria-hidden="true" />
          )}
        </button>
        <button
          type="button"
          data-testid="playback-direction"
          data-direction={playbackDirection === -1 ? "reverse" : "forward"}
          aria-label={playbackDirection === -1 ? "Forward" : "Reverse"}
          title={playbackDirection === -1 ? "Play forward" : "Play in reverse"}
          disabled={disabled}
          onClick={() => {
            setPlaybackDirectionAndPlay(playbackDirection === -1 ? 1 : -1);
          }}
          className="t-control flex h-7 items-center justify-center rounded-control border border-border-subtle px-1.5 text-[10px] text-text-secondary hover:bg-surface-2 disabled:opacity-40"
        >
          {playbackDirection === -1 ? "forward" : "reverse"}
        </button>
        <button
          type="button"
          aria-label="Step forward one frame"
          title="Step forward one frame (→)"
          disabled={disabled || !hasTime}
          onClick={() => step(1)}
          className="t-control flex size-7 items-center justify-center rounded-control text-text-secondary hover:bg-surface-2 disabled:opacity-40"
        >
          <SkipForward size={14} aria-hidden="true" />
        </button>
      </div>

      <label className="t-label flex shrink-0 items-center gap-1 text-text-muted">
        rate
        <select
          aria-label="Playback rate"
          disabled={disabled}
          value={playbackRate}
          onChange={(event) => setPlaybackRate(Number(event.target.value))}
          className="t-control mono rounded-control border border-border-subtle bg-surface-1 px-1 py-0.5 text-[11px] text-text-secondary"
        >
          {RATES.map((rate) => (
            <option key={rate} value={rate}>
              {rate}×
            </option>
          ))}
        </select>
      </label>

      <PlayheadReadout />
      <Timeline stepRateHz={stepRate} />

      <div className="flex shrink-0 items-baseline gap-3">
        <div>
          <span className="t-section mr-2 text-text-muted">range</span>
          <span className="mono text-[12px] tabular text-text-secondary">
            {committedRangeNs
              ? `${formatDurationNs(committedRangeNs.toNs - committedRangeNs.fromNs)}`
              : "none"}
          </span>
        </div>
        {playbackStatus === "buffering" ? (
          <span data-testid="playback-buffering" className="t-label text-quality-warning">
            BUFFERING
          </span>
        ) : playbackStatus === "ended" ? (
          <span data-testid="playback-ended" className="t-label text-text-muted">end of artifact</span>
        ) : null}
      </div>

      <div
        className={cn(
          "t-label flex h-6 min-w-40 max-w-72 shrink items-center gap-2 rounded-control border border-border-subtle bg-surface-1 px-2 text-text-muted",
        )}
        title="Quality and availability ribbon: quarantined intervals, pose availability, detected/extrapolated tracking"
      >
        <span className="t-section shrink-0">quality</span>
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

/** Clock read-out; with the timeline thumb, the only per-frame subscriber. */
function PlayheadReadout() {
  const effective = useAnalysisStore(effectiveTimeNs);
  const committedTimeNs = useAnalysisStore((state) => state.committedTimeNs);
  return (
    <div className="flex shrink-0 items-baseline gap-2">
      <span className="t-section text-text-muted">playhead</span>
      <span className="t-value mono tabular">
        {effective !== null ? formatClockNs(effective) : "—"}
      </span>
      <span data-testid="playhead-ns" className="mono text-[10px] text-text-muted">
        {effective !== null ? `${effective} ns` : "unavailable"}
      </span>
      <span className="t-section ml-2 text-text-muted" title="Durable time in the URL; playback commits on pause">committed</span>
      <span className="mono text-[11px] tabular text-text-secondary">
        {committedTimeNs !== null ? formatClockNs(committedTimeNs) : "—"}
      </span>
    </div>
  );
}

function clampNs(value: bigint, lower: bigint, upper: bigint): bigint {
  return value < lower ? lower : value > upper ? upper : value;
}

/**
 * Seekable timeline over the selected stream's canonical span.
 *
 * Dragging moves only the transient playhead; releasing (pointer or key)
 * commits the frame-aligned time durably. The span always comes from the
 * artifact authority, never from what happens to be loaded.
 */
function Timeline({ stepRateHz }: { stepRateHz: number }) {
  const context = useAnalysisContext();
  const session = useQuery({
    ...sessionQuery(context?.datasetId ?? "", context?.sessionId ?? ""),
    enabled: Boolean(context?.datasetId && context?.sessionId),
  });
  const stream = session.data?.streams.find((item) => item.stream_id === context?.streamId) ?? null;
  const artifactId = stream?.sample_artifact_ids[0] ?? null;
  const artifact = useQuery({ ...artifactQuery(artifactId ?? ""), enabled: Boolean(artifactId) });
  const span = canonicalSpan(artifact.data);
  const effective = useAnalysisStore(effectiveTimeNs);
  const committedRangeNs = useAnalysisStore((state) => state.committedRangeNs);
  const setPlayhead = useAnalysisStore((state) => state.setPlayhead);
  const seeking = useRef(false);

  if (context === null || span === null || span.maxNs <= span.minNs) {
    return (
      <div className="flex min-w-24 flex-1 items-center" title="Select a stream to enable the timeline">
        <div aria-hidden="true" className="h-1 w-full rounded-full bg-surface-2" />
      </div>
    );
  }
  const frameNs = BigInt(Math.max(1, Math.round(1e9 / stepRateHz)));
  const durationMs = Number(span.maxNs - span.minNs) / 1e6;
  const offsetPercent = (value: bigint) =>
    (Number(clampNs(value, span.minNs, span.maxNs) - span.minNs) / 1e6 / durationMs) * 100;
  const valueMs = effective === null
    ? 0
    : Number(clampNs(effective, span.minNs, span.maxNs) - span.minNs) / 1e6;
  const toNs = (ms: number) => {
    const offset = BigInt(Math.round(ms * 1e6));
    return clampNs(span.minNs + (offset / frameNs) * frameNs, span.minNs, span.maxNs);
  };
  const commit = () => {
    if (!seeking.current) return;
    seeking.current = false;
    const now = effectiveTimeNs(useAnalysisStore.getState());
    if (now !== null) context.commitTime(now);
  };
  const rangeLeft = committedRangeNs ? offsetPercent(committedRangeNs.fromNs) : null;
  const rangeWidth = committedRangeNs && rangeLeft !== null
    ? offsetPercent(committedRangeNs.toNs) - rangeLeft
    : null;
  return (
    <div className="flex min-w-24 flex-1 items-center gap-2">
      <span className="mono shrink-0 text-[10px] tabular text-text-muted">{formatClockNs(span.minNs)}</span>
      <div className="relative flex h-6 flex-1 items-center">
        {rangeLeft !== null && rangeWidth !== null ? (
          <span
            aria-hidden="true"
            className="pointer-events-none absolute top-1/2 h-2 -translate-y-1/2 rounded-sm bg-accent/25"
            style={{ left: `${rangeLeft}%`, width: `${Math.max(rangeWidth, 0.5)}%` }}
          />
        ) : null}
        <input
          type="range"
          data-testid="transport-timeline"
          aria-label={`Seek within ${stream?.stream_id ?? "stream"}`}
          aria-valuetext={effective === null ? "no time" : formatClockNs(effective)}
          min={0}
          max={durationMs}
          step={Number(frameNs) / 1e6}
          value={valueMs}
          onChange={(event) => {
            seeking.current = true;
            setPlayhead(toNs(Number(event.target.value)));
          }}
          onPointerUp={commit}
          onKeyUp={commit}
          onBlur={commit}
          className="t-timeline w-full"
        />
      </div>
      <span className="mono shrink-0 text-[10px] tabular text-text-muted">{formatClockNs(span.maxNs)}</span>
    </div>
  );
}

/** Read a durable playhead from URL text without throwing inside render. */
export function parseDurableTime(text: string | undefined | null): bigint | null {
  return tryParseNs(text ?? undefined);
}
