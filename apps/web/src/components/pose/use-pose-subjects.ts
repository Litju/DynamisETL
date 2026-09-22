/** Stable artifact/session identity options for the pose laboratory. */

import { useMemo } from "react";

import type { ArtifactDetail, SessionParticipantView } from "@/api/types";
import { api, unwrap } from "@/lib/api/client";

export interface PoseSubjectObservation {
  readonly entityId: string;
  readonly firstObservedNs: bigint;
  readonly lastObservedNs: bigint;
  readonly observationCount: number;
}

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
    const observed = new Set((artifact.entity_observations ?? []).map((item) => item.entity_id));
    return [...artifact.entity_ids].sort((left, right) => {
      const observedOrder = Number(observed.has(right)) - Number(observed.has(left));
      return observedOrder || left.localeCompare(right);
    });
  }
  const ids = new Set<string>();
  if (streamSubject !== null) ids.add(streamSubject);
  for (const participant of participants) ids.add(participant.subject_id);
  return [...ids].sort();
}

export interface PoseSubjects {
  readonly subjects: readonly string[];
  readonly observations: readonly PoseSubjectObservation[];
}

export function poseSubjectObservations(
  artifact: Pick<ArtifactDetail, "entity_observations"> | undefined,
): PoseSubjectObservation[] {
  return (artifact?.entity_observations ?? []).map((item) => ({
    entityId: item.entity_id,
    firstObservedNs: BigInt(item.first_observed_ns),
    lastObservedNs: BigInt(item.last_observed_ns),
    observationCount: item.observation_count,
  }));
}

/** Choose a real canonical target; the fallback is never an invented t=0. */
export function firstPoseObservationInRange(
  observation: PoseSubjectObservation | undefined,
  fromNs: bigint | null,
  toNs: bigint | null,
): bigint | null {
  if (!observation || observation.observationCount < 1) return null;
  const lower = fromNs ?? observation.firstObservedNs;
  const upper = toNs ?? observation.lastObservedNs;
  if (observation.lastObservedNs < lower || observation.firstObservedNs > upper) return null;
  if (observation.firstObservedNs >= lower) return observation.firstObservedNs;
  return null;
}

export async function fetchPoseObservationsInRange(
  artifactId: string,
  fromNs: bigint | null,
  toNs: bigint | null,
  signal: AbortSignal,
): Promise<PoseSubjectObservation[]> {
  const requestSignal = AbortSignal.any([signal, AbortSignal.timeout(15_000)]);
  const payload = await unwrap(
    await api.GET("/api/artifacts/{artifact_id}/observations", {
      params: {
        path: { artifact_id: artifactId },
        query: {
          ...(fromNs !== null ? { from_ns: Number(fromNs) } : {}),
          ...(toNs !== null ? { to_ns: Number(toNs) } : {}),
        },
      },
      signal: requestSignal,
    }),
  );
  return poseSubjectObservations({ entity_observations: payload });
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
  const observations = useMemo(() => poseSubjectObservations(artifact), [artifact]);
  return { subjects, observations };
}
