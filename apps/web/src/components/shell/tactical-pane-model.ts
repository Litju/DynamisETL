/**
 * Tactical Analysis pane model: pure capability/materialization resolution,
 * exact current-frame team rows and the deterministic report payload.
 *
 * Every tab resolves to exactly one of: unsupported by the source authority,
 * supported but not materialized locally, or available with named artifacts.
 * Nothing here infers a tactical label the processors do not emit.
 */

import type { ArtifactRef, TacticalCapabilityView } from "@/api/types";
import {
  indexTacticalRows,
  latestRowsAtOrBefore,
  type TacticalRow,
} from "@/components/pitch/tactical-overlay";

export type TacticalLevel = "A" | "B" | "C" | "D" | "E" | "V3";

export const LEVEL_NAMES: Record<TacticalLevel, string> = {
  A: "Level A · team geometry",
  B: "Level B · clipped territory",
  C: "Level C · arrival-time influence",
  D: "Level D · source-event snapshots",
  E: "Level E · shape / phase",
  V3: "MatchLab V3 · functional structure",
};

const CAPABILITY_KEYS: Record<TacticalLevel, keyof TacticalCapabilityView["capabilities"]> = {
  A: "level_a_geometry",
  B: "level_b_territory",
  C: "level_c_influence",
  D: "level_d_event_linked",
  E: "level_e_shape_phase",
  V3: "matchlab_v3_functional_units",
};

export const ALGORITHMS: Record<TacticalLevel, string> = {
  A: "tactical.team_geometry",
  B: "tactical.spatial_territory",
  C: "tactical.arrival_time",
  D: "tactical.source_event_snapshot",
  E: "tactical.team_shape",
  V3: "tactical.matchlab_shape",
};

export type LevelStatus =
  | { readonly kind: "unsupported"; readonly capability: string; readonly reasons: readonly string[] }
  | { readonly kind: "not_materialized"; readonly capability: string; readonly algorithmId: string }
  | { readonly kind: "available"; readonly capability: string; readonly artifacts: readonly ArtifactRef[] };

/** Keywords that tie a dataset's unavailable reasons to one level. */
const REASON_KEYWORDS: Record<TacticalLevel, RegExp> = {
  A: /geometry|team|pitch/i,
  B: /territor|opposing|pitch/i,
  C: /influence|velocity|model/i,
  D: /event/i,
  E: /formation|phase|shape|temporal/i,
  V3: /role|roster|shape|possession|direction/i,
};

export function levelStatus(
  level: TacticalLevel,
  capability: TacticalCapabilityView,
  artifacts: readonly ArtifactRef[],
): LevelStatus {
  const value = String(capability.capabilities[CAPABILITY_KEYS[level]] ?? "unavailable");
  if (!value.startsWith("supported")) {
    const specific = capability.unavailable_reasons.filter((reason) => REASON_KEYWORDS[level].test(reason));
    return { kind: "unsupported", capability: value, reasons: specific.length > 0 ? specific : capability.unavailable_reasons };
  }
  const own = artifacts.filter((artifact) => artifact.artifact_metadata?.tactical_level === level);
  if (own.length === 0) {
    return { kind: "not_materialized", capability: value, algorithmId: ALGORITHMS[level] };
  }
  return { kind: "available", capability: value, artifacts: own };
}

export function levelArtifact(status: LevelStatus, seriesName: string): ArtifactRef | null {
  if (status.kind !== "available") return null;
  return status.artifacts.find((artifact) => artifact.artifact_metadata?.series_name === seriesName) ?? null;
}

/**
 * A request window aligned to fixed buckets of canonical time, so a read-out
 * that follows the playhead changes its query key once per bucket, not once
 * per animation frame.
 */
export function bucketBounds(timeNs: bigint, bucketNs: bigint): { fromNs: bigint; toNs: bigint } {
  const index = timeNs >= 0n ? timeNs / bucketNs : (timeNs - bucketNs + 1n) / bucketNs;
  const fromNs = index * bucketNs;
  return { fromNs, toNs: fromNs + bucketNs - 1n };
}

/**
 * Read window for a current-frame read-out: the playhead's bucket plus a
 * look-back, because the frame drawn at a time just after a bucket boundary
 * lies in the previous bucket (and a <=1 Hz model grid may be older still).
 */
export function liveReadWindow(
  timeNs: bigint,
  bucketNs: bigint,
  lookbackNs: bigint,
): { fromNs: bigint; toNs: bigint } {
  const bucket = bucketBounds(timeNs, bucketNs);
  return { fromNs: bucket.fromNs - lookbackNs, toNs: bucket.toNs };
}

/** Rows (one per team) at the frame the playhead is on, or none. */
export function rowsAtFrame(
  rows: readonly TacticalRow[] | undefined,
  timeNs: bigint | null,
  maxAgeNs: number,
): readonly TacticalRow[] {
  if (!rows || timeNs === null) return [];
  return latestRowsAtOrBefore(indexTacticalRows(rows), Number(timeNs), maxAgeNs)?.rows ?? [];
}

export function numberOf(row: TacticalRow | undefined, key: string): number | null {
  const value = row?.[key];
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** Per-team rows in session team order; unknown teams follow. */
export function byTeam(
  rows: readonly TacticalRow[],
  teamOrder: readonly string[],
): Array<{ readonly groupId: string; readonly row: TacticalRow }> {
  const entries = rows.flatMap((row) => {
    const groupId = row["group_id"];
    return typeof groupId === "string" ? [{ groupId, row }] : [];
  });
  const rank = (groupId: string) => {
    const index = teamOrder.indexOf(groupId);
    return index < 0 ? teamOrder.length : index;
  };
  return entries.sort((left, right) => rank(left.groupId) - rank(right.groupId) || left.groupId.localeCompare(right.groupId));
}

export interface ReportInput {
  readonly datasetId: string;
  readonly sessionId: string;
  readonly streamId: string | null;
  readonly timeNs: bigint | null;
  readonly range: { readonly fromNs: bigint; readonly toNs: bigint } | null;
  readonly capability: TacticalCapabilityView;
  readonly statuses: Readonly<Record<TacticalLevel, LevelStatus>>;
  readonly teamLabels: ReadonlyMap<string, string>;
  readonly rangeTeamRows: number;
  readonly eventRows: number;
}

/** Deterministic, conclusion-free report: identities, provenance and counts. */
export function reportPayload(input: ReportInput): Record<string, unknown> {
  const levels = Object.fromEntries(
    (Object.keys(input.statuses) as TacticalLevel[]).map((level) => {
      const status = input.statuses[level];
      return [
        level,
        {
          name: LEVEL_NAMES[level],
          capability: status.capability,
          status: status.kind,
          ...(status.kind === "unsupported" ? { reasons: status.reasons } : {}),
          ...(status.kind === "not_materialized" ? { algorithm_id: status.algorithmId } : {}),
          ...(status.kind === "available"
            ? {
                artifacts: status.artifacts
                  .map((artifact) => ({
                    artifact_id: artifact.artifact_id,
                    series_name: artifact.artifact_metadata?.series_name ?? null,
                    run_id: artifact.run_id ?? null,
                    algorithm_id: artifact.algorithm_id ?? null,
                    algorithm_version: artifact.algorithm_version ?? null,
                    parameters_hash: artifact.parameters_hash ?? null,
                    measurement_class: artifact.measurement_class ?? null,
                    checksum_sha256: artifact.checksum_sha256,
                  }))
                  .sort((left, right) => left.artifact_id.localeCompare(right.artifact_id)),
              }
            : {}),
        },
      ];
    }),
  );
  return {
    report: "dynamis.tactical.v1",
    dataset_id: input.datasetId,
    session_id: input.sessionId,
    stream_id: input.streamId,
    time_ns: input.timeNs === null ? null : input.timeNs.toString(),
    range_ns: input.range === null ? null : { from: input.range.fromNs.toString(), to: input.range.toNs.toString() },
    teams: Object.fromEntries(input.teamLabels),
    levels,
    counts: { range_team_geometry_rows: input.rangeTeamRows, source_event_rows: input.eventRows },
    unavailable_reasons: input.capability.unavailable_reasons,
    conclusion_policy: "quantitative summary only; unsupported tactical conclusions are omitted",
  };
}
