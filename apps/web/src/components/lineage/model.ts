/**
 * Selected-result lineage layout.
 *
 * React Flow renders orientation; this module owns the deterministic,
 * testable mapping from the API's provenance graph to layered flow elements.
 * The graph shows only the selected result lineage — never a project-wide DAG.
 */

import type { Edge, Node } from "@xyflow/react";

import type { ProvenanceGraph } from "@/api/types";

export interface LineageNodeData extends Record<string, unknown> {
  label: string;
  kind: string;
  status: string | null;
  measurementClass: string | null;
  details: Record<string, unknown>;
  selected?: boolean;
}

export type LineageNode = Node<LineageNodeData, "instrument">;

export const LINEAGE_LAYER: Record<string, number> = {
  dataset: 0,
  input_checksum: 1,
  silver_artifact: 1,
  derived_artifact: 1,
  sensor_stream: 2,
  metric_definition: 3,
  algorithm: 3,
  processing_run: 4,
  derived_metric: 5,
  gold_row: 6,
};

export const LINEAGE_LAYER_LABEL: Record<number, string> = {
  0: "source",
  1: "artifact",
  2: "canonical stream",
  3: "definition",
  4: "run",
  5: "result",
  6: "serving",
};

export function lineageLayer(kind: string): number {
  return LINEAGE_LAYER[kind] ?? 3;
}

export function toFlowElements(graph: ProvenanceGraph): {
  nodes: LineageNode[];
  edges: Edge[];
} {
  const ordered = [...graph.nodes].sort((left, right) => {
    const layerDelta = lineageLayer(left.kind) - lineageLayer(right.kind);
    if (layerDelta !== 0) return layerDelta;
    return left.id < right.id ? -1 : left.id > right.id ? 1 : 0;
  });
  const perLayer = new Map<number, number>();
  const nodes: LineageNode[] = ordered.map((node) => {
    const layer = lineageLayer(node.kind);
    const index = perLayer.get(layer) ?? 0;
    perLayer.set(layer, index + 1);
    return {
      id: node.id,
      type: "instrument",
      position: { x: layer * 260, y: index * 92 },
      data: {
        label: node.label,
        kind: node.kind,
        status: node.status ?? null,
        measurementClass: node.measurement_class ?? null,
        details: node.details ?? {},
      },
      draggable: false,
    };
  });
  const edges: Edge[] = graph.edges.map((edge) => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    label: edge.label,
    type: "smoothstep",
    animated: false,
  }));
  return { nodes, edges };
}

const DETAIL_PRIORITY = [
  "dataset_id",
  "metric_id",
  "algorithm_id",
  "version",
  "kind",
  "code_git_sha",
  "parameters_hash",
  "run_id",
  "stream_id",
  "relative_path",
  "checksum_sha256",
  "row_count",
  "value_num",
  "si_unit",
  "computed_at",
  "session_id",
  "subject_id",
  "trial_id",
  "started_at",
  "completed_at",
  "layer",
];

/** Deterministic detail rows for the selected node: priority keys first. */
export function detailRows(details: Record<string, unknown>): Array<[string, string]> {
  const keys = Object.keys(details).sort((left, right) => {
    const leftRank = DETAIL_PRIORITY.indexOf(left);
    const rightRank = DETAIL_PRIORITY.indexOf(right);
    const rank = (value: number) => (value === -1 ? DETAIL_PRIORITY.length : value);
    return rank(leftRank) - rank(rightRank) || left.localeCompare(right);
  });
  return keys
    .filter((key) => details[key] !== null && details[key] !== undefined && details[key] !== "")
    .map((key) => [key, formatDetail(details[key])]);
}

function formatDetail(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value, null, 0);
}

export function lineageNote(graph: ProvenanceGraph): string {
  return graph.lineage_note;
}
