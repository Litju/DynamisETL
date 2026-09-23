/**
 * Deterministic analytical defaults.
 *
 * Opening a real session must land on a real analytical state without asking
 * the reader to discover every selector. Every choice here is derived from the
 * served session: a surface is offered only when a stream of that modality
 * carries a canonical artifact, and a subject or trial is selected only when
 * the session actually declares it. Nothing is invented, and the result is a
 * pure function of the session, so a deep link and a fresh navigation resolve
 * identically.
 */

import type { ArtifactDetail, SessionDetail, StreamView } from "@/api/types";
import {
  sessionSurfaces,
  streamsForSurface,
  surfaceForModality,
  type LabSurface,
} from "@/lib/capabilities";
import type { LabSearch, WorkbenchView } from "@/lib/search";

/**
 * Modality preference inside the signal laboratory. Force plates are the
 * flagship laboratory signal, then inertial, then positional; within a family
 * the registry order decides, so the choice never depends on wall-clock or
 * iteration order.
 */
const SIGNAL_MODALITY_RANK: readonly string[] = ["force", "imu", "lpt", "gnss"];

function compareStreams(left: StreamView, right: StreamView): number {
  const leftRank = SIGNAL_MODALITY_RANK.indexOf(left.modality);
  const rightRank = SIGNAL_MODALITY_RANK.indexOf(right.modality);
  const leftScore = leftRank < 0 ? SIGNAL_MODALITY_RANK.length : leftRank;
  const rightScore = rightRank < 0 ? SIGNAL_MODALITY_RANK.length : rightRank;
  if (leftScore !== rightScore) return leftScore - rightScore;
  return left.stream_id < right.stream_id ? -1 : left.stream_id > right.stream_id ? 1 : 0;
}

/** The stream a surface opens by default, or null when it cannot open. */
export function defaultStreamFor(
  session: SessionDetail,
  surface: LabSurface,
): StreamView | null {
  const candidates = [...streamsForSurface(session.streams, surface)].sort(compareStreams);
  return candidates[0] ?? null;
}

/**
 * The view a session opens on.
 *
 * Overview always wins when it can carry a real analytical summary, because it
 * is the orientation surface. A session with no renderable stream still opens
 * on overview: its metadata and derived metrics are the analysis it has.
 */
export function defaultViewFor(session: SessionDetail): WorkbenchView {
  void session;
  return "overview";
}

export interface ResolvedDefaults {
  /** Search patch to apply; empty when the URL already pins everything. */
  readonly patch: Partial<LabSearch>;
  /** Surfaces this session can actually open, in product order. */
  readonly surfaces: readonly LabSurface[];
}

/**
 * Resolve the durable selections a session should carry.
 *
 * Only absent keys are filled: an explicit deep link always wins, so back and
 * forward navigation and a shared URL keep exactly the state they encoded. The
 * returned patch is empty when nothing needs to change, which lets the caller
 * skip the navigation entirely rather than looping on itself.
 */
export function resolveLabDefaults(
  session: SessionDetail,
  current: Partial<LabSearch>,
): ResolvedDefaults {
  const surfaces = sessionSurfaces(session.streams);
  const patch: Partial<LabSearch> = {};

  // A renderer view the session cannot open (a shared link from another
  // session, a hand-edited URL) resolves to overview instead of an unselected tab.
  const requested = current.view ?? defaultViewFor(session);
  // A session that has a stream of the surface but no artifact keeps the view,
  // so the renderer can state exactly what is missing.
  const unavailable =
    (requested === "signals" || requested === "field" || requested === "pose") &&
    !session.streams.some((stream) => surfaceForModality(stream.modality) === requested);
  const view = (unavailable ? "overview" : requested) as WorkbenchView;
  if (current.view !== view) patch.view = view;

  // The stream must match the surface being shown, so a laboratory tab never
  // opens against a stream of the wrong modality.
  const surfaceForView: LabSurface | null =
    view === "signals" || view === "field" || view === "pose" ? view : null;

  // Outside a renderer view, preselect the first openable surface's stream so
  // switching tabs is immediate rather than another empty state.
  const targetSurface = surfaceForView ?? surfaces[0] ?? null;
  const stream = targetSurface === null ? null : defaultStreamFor(session, targetSurface);

  const currentStream = current.stream
    ? (session.streams.find((candidate) => candidate.stream_id === current.stream) ?? null)
    : null;
  // Replace a stream that cannot serve the visible surface; a stale deep link
  // must degrade to a valid state rather than to an error panel.
  const streamMismatch =
    currentStream !== null &&
    surfaceForView !== null &&
    streamsForSurface(session.streams, surfaceForView).every(
      (candidate) => candidate.stream_id !== currentStream.stream_id,
    );
  const effectiveStream = currentStream !== null && !streamMismatch ? currentStream : stream;
  if (effectiveStream !== null && effectiveStream.stream_id !== current.stream) {
    patch.stream = effectiveStream.stream_id;
  }

  // Trial: the stream's own trial, else the session's first declared trial.
  if (current.trial === undefined) {
    const trialId = effectiveStream?.trial_id ?? session.trials[0]?.trial_id ?? null;
    if (trialId !== null) patch.trial = trialId;
  }

  // Subject: only when the data names one. A per-period stream shared by every
  // participant declares no subject, and guessing one would assert an
  // observation the window has not been read for yet.
  if (current.subject === undefined && effectiveStream?.subject_id) {
    patch.subject = effectiveStream.subject_id;
  }

  return { patch, surfaces };
}

/**
 * The canonical time a renderer view should land on.
 *
 * A laboratory with no committed time has no frame the transport, pitch,
 * tactical pane and Pose scene can agree on, so the durable time is resolved
 * from the selected stream's own artifact: the first canonical frame, or for
 * Pose the selected subject's first observation. A committed time outside the
 * stream's canonical span (a period switch keeps the previous period's time)
 * is equally unrenderable and resolves the same way. Returns `null` when the
 * current time is already valid or the artifact carries no span.
 */
export function canonicalTimeDefault(
  artifact: Pick<ArtifactDetail, "canonical_time_min_ns" | "canonical_time_max_ns" | "entity_observations">,
  options: {
    readonly currentNs: bigint | null;
    readonly view: WorkbenchView;
    readonly subjectId: string | null;
  },
): bigint | null {
  const min = artifact.canonical_time_min_ns;
  const max = artifact.canonical_time_max_ns;
  if (min === null || min === undefined || max === null || max === undefined) return null;
  const minNs = BigInt(min);
  const maxNs = BigInt(max);
  if (options.currentNs !== null && options.currentNs >= minNs && options.currentNs <= maxNs) {
    return null;
  }
  if (options.view === "pose" && options.subjectId !== null) {
    const observation = (artifact.entity_observations ?? []).find(
      (item) => item.entity_id === options.subjectId,
    );
    if (observation && observation.observation_count > 0) {
      return BigInt(observation.first_observed_ns);
    }
  }
  return minNs;
}

/** True when a patch would actually change the durable state. */
export function patchChangesSearch(
  patch: Partial<LabSearch>,
  current: Partial<LabSearch>,
): boolean {
  return Object.entries(patch).some(
    ([key, value]) => current[key as keyof LabSearch] !== value,
  );
}
