/**
 * Durable analysis context.
 *
 * The laboratory route provides this context; it is the only bridge that may
 * serialize transient state into the URL. Renderers publish hover/selection into
 * the Zustand spine and call `commitTime`/`commitRange` on interaction
 * boundaries, never on every animation frame.
 */

import { createContext, useContext } from "react";

export interface DurableRange {
  readonly fromNs: bigint;
  readonly toNs: bigint;
}

export interface AnalysisContextValue {
  readonly datasetId: string;
  readonly sessionId: string;
  readonly trialId: string | null;
  readonly subjectId: string | null;
  readonly streamId: string | null;
  readonly fromNs: bigint | null;
  readonly toNs: bigint | null;
  readonly metricId: string | null;
  readonly derivedMetricId: string | null;
  /** Commit a playhead selection; serialized as decimal `t_ns` text. */
  readonly commitTime: (tNs: bigint | null) => void;
  /** Commit a brushed range. */
  readonly commitRange: (range: DurableRange | null) => void;
  /** Select an entity (player/joint subject) durably. */
  readonly selectSubject: (subjectId: string | null) => void;
  /** Select a stream durably (which renderer the laboratory shows). */
  readonly selectStream: (streamId: string | null) => void;
  /** Select the result whose methodology/provenance the inspector follows. */
  readonly selectResult: (derivedMetricId: string | null) => void;
}

export const AnalysisContext = createContext<AnalysisContextValue | null>(null);

export function useAnalysisContext(): AnalysisContextValue | null {
  return useContext(AnalysisContext);
}
