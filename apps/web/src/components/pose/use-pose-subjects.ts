/**
 * Observed pose subjects.
 *
 * A SkillCorner pose stream covers a whole period and declares no subject of
 * its own, so the laboratory cannot know which subject to render from the
 * registry alone. This probes a short window of the canonical artifact and
 * reports the subjects actually observed in it — never the session roster,
 * which would offer a subject the window holds no landmark for.
 */

import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import type { ArtifactDetail } from "@/api/types";
import { windowQuery } from "@/lib/api/queries";
import { canonicalSpan } from "@/lib/dense-window";

/** Probe length. Long enough to see who is on the pitch, short enough to be exact. */
const PROBE_NS = 1_000_000_000n;
const PROBE_MAX_POINTS = 20_000;

/** Distinct observed subject ids in row order, sorted for a stable default. */
export function observedSubjects(rows: ReadonlyArray<Record<string, unknown>>): string[] {
  const found = new Set<string>();
  for (const row of rows) {
    const value = row["subject_id"];
    if (typeof value === "string" && value.length > 0) found.add(value);
    else if (typeof value === "number") found.add(String(value));
  }
  return [...found].sort((left, right) => (left < right ? -1 : left > right ? 1 : 0));
}

export interface PoseSubjects {
  readonly subjects: readonly string[];
  readonly isPending: boolean;
  readonly isError: boolean;
}

/**
 * Subjects observed near `anchorNs` (or at the start of the recording). The
 * probe is bounded and cached, so switching subjects never refetches it.
 */
export function usePoseSubjects(
  artifactId: string | null,
  artifact: ArtifactDetail | undefined,
  anchorNs: bigint | null,
): PoseSubjects {
  const bounds = useMemo(() => {
    const span = canonicalSpan(artifact);
    if (span === null) return null;
    const anchor = anchorNs === null ? span.minNs : anchorNs;
    let fromNs = anchor < span.minNs ? span.minNs : anchor;
    if (fromNs > span.maxNs) fromNs = span.maxNs;
    let toNs = fromNs + PROBE_NS;
    if (toNs > span.maxNs) toNs = span.maxNs;
    return { fromNs, toNs };
  }, [anchorNs, artifact]);

  const probe = useQuery({
    ...windowQuery({
      artifactId: artifactId ?? "",
      ...(bounds ? { fromNs: Number(bounds.fromNs), toNs: Number(bounds.toNs) } : {}),
      columns: ["t_rel_ns", "subject_id"],
      maxPoints: PROBE_MAX_POINTS,
    }),
    enabled: Boolean(artifactId) && bounds !== null,
    staleTime: 5 * 60_000,
  });

  const subjects = useMemo(
    () => (probe.data ? observedSubjects(probe.data.rows) : []),
    [probe.data],
  );
  return { subjects, isPending: probe.isPending, isError: probe.isError };
}
