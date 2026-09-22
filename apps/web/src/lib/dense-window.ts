/**
 * Dense-window sizing.
 *
 * A spatial or pose renderer needs exact entity frames: a display-reduced
 * min/max envelope cannot be replayed, because the envelope is a per-bucket
 * extremum rather than an observed position. So the window must be chosen to
 * fit the point budget before the request, not discovered to have overrun it
 * afterwards.
 *
 * The size comes from the artifact's own measured density (rows over its
 * canonical span, divided by the entities sharing that axis when the request is
 * entity-scoped), never from a hard-coded duration that happens to suit one
 * dataset.
 */

import type { ArtifactDetail } from "@/api/types";

/**
 * Average density understates a continuously observed entity, because an
 * artifact's rows are spread over entities that appear and disappear. A
 * quarter-span guard keeps exact entity windows below the source-row budget on
 * uneven real streams rather than relying on a reduction/retry round trip.
 */
const DENSITY_SAFETY_FACTOR = 4;

export interface WindowBounds {
  readonly fromNs: bigint;
  readonly toNs: bigint;
}

export interface CanonicalSpan {
  readonly minNs: bigint;
  readonly maxNs: bigint;
}

/** The artifact's canonical bounds, or null when it holds no samples. */
export function canonicalSpan(artifact: ArtifactDetail | undefined): CanonicalSpan | null {
  if (!artifact) return null;
  const { canonical_time_min_ns: min, canonical_time_max_ns: max } = artifact;
  if (min === null || min === undefined || max === null || max === undefined) return null;
  return { minNs: BigInt(min), maxNs: BigInt(max) };
}

/**
 * Span of recording, in nanoseconds, whose exact rows fit inside `maxPoints`.
 *
 * Returns the full canonical span when the whole artifact already fits, and
 * `null` when the artifact carries no usable density signal.
 */
export function affordableSpanNs(
  artifact: ArtifactDetail | undefined,
  options: { readonly maxPoints: number; readonly entityScoped?: boolean },
): bigint | null {
  const span = canonicalSpan(artifact);
  if (!artifact || span === null) return null;
  const totalNs = span.maxNs - span.minNs;
  if (totalNs <= 0n) return null;
  if (artifact.row_count <= options.maxPoints) return totalNs;

  const entities =
    options.entityScoped && artifact.entity_count && artifact.entity_count > 0
      ? artifact.entity_count
      : 1;
  const rowsPerNs = artifact.row_count / entities / Number(totalNs);
  if (!Number.isFinite(rowsPerNs) || rowsPerNs <= 0) return null;

  const affordable = Math.floor(options.maxPoints / (rowsPerNs * DENSITY_SAFETY_FACTOR));
  if (affordable <= 0) return null;
  const affordableNs = BigInt(affordable);
  return affordableNs > totalNs ? totalNs : affordableNs;
}

/** Clamp a time into the artifact's canonical bounds. */
export function clampToSpan(tNs: bigint, span: CanonicalSpan): bigint {
  if (tNs < span.minNs) return span.minNs;
  if (tNs > span.maxNs) return span.maxNs;
  return tNs;
}

/**
 * The window a renderer should request.
 *
 * An explicit committed range always wins. Otherwise the window is centred on
 * the anchor (the playhead, else the start of the recording) and clamped inside
 * the canonical bounds, so the first frame of a session is fully visible rather
 * than half of a window that starts before the data does.
 */
export function windowAround(
  artifact: ArtifactDetail | undefined,
  options: {
    readonly anchorNs: bigint | null;
    readonly explicit: WindowBounds | null;
    readonly maxPoints: number;
    readonly entityScoped?: boolean;
  },
): (WindowBounds & { readonly explicit: boolean }) | null {
  if (options.explicit !== null) {
    return { ...options.explicit, explicit: true };
  }
  const span = canonicalSpan(artifact);
  const affordable = affordableSpanNs(artifact, {
    maxPoints: options.maxPoints,
    ...(options.entityScoped !== undefined ? { entityScoped: options.entityScoped } : {}),
  });
  if (span === null || affordable === null) return null;

  const anchor = options.anchorNs === null ? span.minNs : clampToSpan(options.anchorNs, span);
  const half = affordable / 2n;
  let fromNs = anchor - half;
  if (fromNs < span.minNs) fromNs = span.minNs;
  let toNs = fromNs + affordable;
  if (toNs > span.maxNs) {
    toNs = span.maxNs;
    fromNs = toNs - affordable;
    if (fromNs < span.minNs) fromNs = span.minNs;
  }
  return { fromNs, toNs, explicit: false };
}
