/** Stable artifact/session identity options for the pose laboratory. */

import { useMemo } from "react";

import type { ArtifactDetail, SessionParticipantView } from "@/api/types";

/**
 * Prefer identities proven by the artifact. Session participants and a
 * subject-scoped stream are deterministic fallbacks for older API payloads;
 * no current-window probe is involved.
 */
export function stablePoseSubjects(
  artifact: ArtifactDetail | undefined,
  participants: readonly SessionParticipantView[],
  streamSubject: string | null,
): string[] {
  if (artifact?.entity_ids !== undefined && artifact.entity_ids !== null) {
    return [...artifact.entity_ids].sort();
  }
  const ids = new Set<string>();
  if (streamSubject !== null) ids.add(streamSubject);
  for (const participant of participants) ids.add(participant.subject_id);
  return [...ids].sort();
}

export interface PoseSubjects {
  readonly subjects: readonly string[];
}

export function usePoseSubjects(
  artifact: ArtifactDetail | undefined,
  participants: readonly SessionParticipantView[],
  streamSubject: string | null,
): PoseSubjects {
  const subjects = useMemo(
    () => stablePoseSubjects(artifact, participants, streamSubject),
    [artifact, participants, streamSubject],
  );
  return { subjects };
}
