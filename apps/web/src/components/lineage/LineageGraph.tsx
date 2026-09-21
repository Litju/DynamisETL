import {
  Background,
  Controls,
  Handle,
  MiniMap,
  Position,
  ReactFlow,
  type NodeProps,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";
import { useMemo, useState } from "react";

import { MeasurementClassBadge } from "@/components/common/Badges";
import { KeyValueRow, SectionTitle } from "@/components/common/Panel";
import { cn } from "@/lib/cn";
import { useUiStore } from "@/lib/state/ui";
import type { ProvenanceGraph } from "@/api/types";
import { detailRows, toFlowElements, type LineageNode } from "@/components/lineage/model";

function InstrumentNode({ data, selected }: NodeProps<LineageNode>) {
  return (
    <div
      className={cn(
        "w-56 rounded-panel border bg-surface-2 px-2 py-1.5 text-left",
        selected ? "border-accent" : "border-border-subtle",
      )}
    >
      <Handle type="target" position={Position.Left} className="!size-1.5 !bg-border-strong" />
      <div className="flex items-center justify-between gap-2">
        <span className="t-section mono truncate text-text-muted">
          {data.kind}
        </span>
        {data.measurementClass ? (
          <MeasurementClassBadge measurementClass={data.measurementClass} compact />
        ) : null}
      </div>
      <div className="mt-0.5 truncate text-[12px] text-text-primary" title={data.label}>
        {data.label}
      </div>
      {data.status ? (
        <div className="mono text-[10px] text-text-muted">status: {data.status}</div>
      ) : null}
      <Handle type="source" position={Position.Right} className="!size-1.5 !bg-border-strong" />
    </div>
  );
}

const NODE_TYPES = { instrument: InstrumentNode };

/**
 * Selected-result lineage graph. React Flow provides orientation and
 * relationships; the inspector remains the detailed text surface.
 */
export default function LineageGraph({ graph }: { graph: ProvenanceGraph }) {
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const theme = useUiStore((state) => state.theme);
  const { nodes, edges } = useMemo(() => toFlowElements(graph), [graph]);
  const selectedNode = nodes.find((node) => node.id === selectedId) ?? null;

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="h-80 w-full shrink-0" data-testid="lineage-flow">
        <ReactFlow
          nodes={nodes}
          edges={edges}
          nodeTypes={NODE_TYPES}
          colorMode={theme === "dark" ? "dark" : "light"}
          fitView
          minZoom={0.3}
          maxZoom={1.6}
          nodesDraggable={false}
          nodesConnectable={false}
          elementsSelectable
          onNodeClick={(_event, node) => setSelectedId(node.id)}
          onPaneClick={() => setSelectedId(null)}
        >
          <Background gap={24} size={1} />
          <Controls showInteractive={false} />
          <MiniMap pannable zoomable className="!bg-surface-1" />
        </ReactFlow>
      </div>
      <div className="max-h-56 shrink-0 overflow-y-auto border-t border-border-subtle p-2">
        <p className="mb-1 text-[11px] text-text-muted">{graph.lineage_note}</p>
        {selectedNode ? (
          <>
            <SectionTitle>{selectedNode.data.kind} details</SectionTitle>
            <dl>
              {detailRows(selectedNode.data.details).map(([label, value]) => (
                <KeyValueRow key={label} label={label} mono>
                  {value}
                </KeyValueRow>
              ))}
            </dl>
          </>
        ) : (
          <p className="text-[11px] text-text-muted">
            Select a node to inspect its stored identity; every displayed value resolves through
            this chain.
          </p>
        )}
      </div>
    </div>
  );
}
