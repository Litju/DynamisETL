import { useNavigate, useRouterState } from "@tanstack/react-router";
import { useMemo, type ReactNode } from "react";

import { AnalysisContext, type AnalysisContextValue } from "@/lib/analysis-context";
import { MatchFrameContextProvider } from "@/lib/match-frame-context";
import { normalizeLabSearch, type LabSearch, type TacticalView } from "@/lib/search";
import { formatNsDecimal, tryParseNs } from "@/lib/time";

/**
 * Durable analysis context for the whole shell.
 *
 * The provider lives at the root layout, not inside the laboratory route, so
 * shell-level consumers (transport, inspector, explorer) see the same durable
 * context as the route content. URL search remains the single authority; commit
 * helpers navigate on interaction boundaries only.
 */
export function AnalysisContextProvider({ children }: { children: ReactNode }) {
  const navigate = useNavigate();
  const location = useRouterState({ select: (state) => state.location });
  const parts = location.pathname.split("/").filter(Boolean);
  const datasetId = parts[0] === "lab" ? (parts[1] ?? null) : null;
  const sessionId = parts[0] === "lab" ? (parts[2] ?? null) : null;
  const search = normalizeLabSearch(location.search);

  const value = useMemo<AnalysisContextValue | null>(() => {
    if (datasetId === null || sessionId === null) return null;
    const update = (patch: Record<string, unknown>) => {
      void navigate({
        to: "/lab/$datasetId/$sessionId",
        params: { datasetId, sessionId },
        search: (previous: LabSearch) => ({ ...previous, ...patch }),
        replace: true,
      });
    };
    return {
      datasetId,
      sessionId,
      trialId: search.trial ?? null,
      subjectId: search.subject ?? null,
      entityId: search.entity ?? null,
      timeNs: tryParseNs(search.t_ns),
      streamId: search.stream ?? null,
      fromNs: tryParseNs(search.from_ns),
      toNs: tryParseNs(search.to_ns),
      metricId: search.metric ?? null,
      derivedMetricId: search.result ?? null,
      view: search.view ?? "overview",
      tacticalView: search.tactical ?? "live",
      commitTime: (tNs) =>
        update({ t_ns: tNs === null ? undefined : formatNsDecimal(tNs) }),
      commitRange: (range) =>
        update(
          range === null
            ? { from_ns: undefined, to_ns: undefined }
            : { from_ns: formatNsDecimal(range.fromNs), to_ns: formatNsDecimal(range.toNs) },
        ),
      selectSubject: (subjectIdValue, options) =>
        void navigate({
          to: "/lab/$datasetId/$sessionId",
          params: { datasetId, sessionId },
          search: (previous: LabSearch) => ({
            ...previous,
            subject: subjectIdValue === null ? undefined : subjectIdValue,
            ...(subjectIdValue !== null ? { entity: undefined } : {}),
            ...(options?.targetTimeNs !== undefined
              ? { t_ns: formatNsDecimal(options.targetTimeNs) }
              : {}),
          }),
          replace: options?.replace ?? false,
        }),
      selectFieldEntity: (entityIdValue) =>
        update({
          subject: undefined,
          entity: entityIdValue === null ? undefined : entityIdValue,
        }),
      selectStream: (streamIdValue) =>
        update({ stream: streamIdValue === null ? undefined : streamIdValue }),
      selectResult: (derivedMetricId) =>
        update({ result: derivedMetricId === null ? undefined : derivedMetricId }),
      selectTacticalView: (view: TacticalView) => update({ tactical: view }),
    };
  }, [datasetId, navigate, search.result, search.stream, search.subject, search.t_ns, search.to_ns, search.from_ns, search.metric, search.tactical, search.trial, search.entity, search.view, sessionId]);

  return (
    <AnalysisContext.Provider value={value}>
      <MatchFrameContextProvider poseVisible={search.view === "pose" || search.view === "split"}>
        {children}
      </MatchFrameContextProvider>
    </AnalysisContext.Provider>
  );
}
