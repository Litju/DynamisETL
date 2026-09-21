import type { ArtifactDetail, StreamView } from "@/api/types";

/** Stable identities from an artifact/session authority, never a time probe. */
export function stableIndividualIds(
  artifact: Pick<ArtifactDetail, "entity_ids"> | undefined,
  streams: readonly StreamView[],
): string[] {
  if (artifact?.entity_ids !== undefined && artifact.entity_ids !== null) {
    return [...artifact.entity_ids].sort();
  }
  const ids = new Set<string>();
  for (const stream of streams) {
    if (stream.subject_id !== null) ids.add(stream.subject_id);
  }
  return [...ids].sort();
}

/** Resolve the real compatible per-subject stream without crossing subjects. */
export function resolveSignalStream(
  streams: readonly StreamView[],
  current: StreamView | null,
  subjectId: string | null,
): StreamView | null {
  if (subjectId === null) return current;
  if (current?.subject_id === subjectId) return current;
  if (current?.subject_id === null) return current;

  const candidates = streams
    .filter(
      (stream) =>
        stream.sample_artifact_ids.length > 0 &&
        stream.modality === current?.modality &&
        stream.subject_id === subjectId,
    )
    .sort((left, right) => {
      const leftTrial = left.trial_id === current?.trial_id ? 0 : 1;
      const rightTrial = right.trial_id === current?.trial_id ? 0 : 1;
      return leftTrial - rightTrial || left.stream_id.localeCompare(right.stream_id);
    });
  return candidates[0] ?? null;
}
