import { useQuery } from "@tanstack/react-query";
import {
  createRoute,
  type AnyRoute,
  useNavigate,
  useParams,
  useSearch,
} from "@tanstack/react-router";
import { useCallback, useEffect, useMemo, useRef } from "react";
import { Group, Panel, Separator } from "react-resizable-panels";

import { lazy, Suspense } from "react";

const LabOverview = lazy(() => import("@/components/lab/LabOverview").then((module) => ({ default: module.LabOverview })));
const MatchLabCanvasRoot = lazy(() => import("@/components/matchlab/MatchLabCanvasRoot").then((module) => ({ default: module.MatchLabCanvasRoot })));
const SignalLaboratory = lazy(() => import("@/components/lab/SignalLaboratory").then((module) => ({ default: module.SignalLaboratory })));
const PitchReplay = lazy(() => import("@/components/pitch/PitchReplay").then((module) => ({ default: module.PitchReplay })));
const PoseViewer = lazy(() => import("@/components/pose/PoseViewer"));
const MatchLabContextSpine = lazy(() => import("@/components/matchlab/MatchLabWorkspace").then((module) => ({ default: module.MatchLabContextSpine })));
const MatchLabDashboard = lazy(() => import("@/components/matchlab/MatchLabWorkspace").then((module) => ({ default: module.MatchLabDashboard })));
const MatchLabPoseViewport = lazy(() => import("@/components/matchlab/MatchLabWorkspace").then((module) => ({ default: module.MatchLabPoseViewport })));
import { ErrorPanel, LoadingPanel, StatePanel } from "@/components/common/StatePanel";
import { artifactQuery, sessionQuery } from "@/lib/api/queries";
import { canonicalTimeDefault, defaultMatchPlayerId, patchChangesSearch, resolveLabDefaults } from "@/lib/defaults";
import { sessionSurfaces } from "@/lib/capabilities";
import { cn } from "@/lib/cn";
import { labSearchSchema, parseSearch, WORKBENCH_VIEWS } from "@/lib/search";
import type { LabSearch, WorkbenchView } from "@/lib/search";
import { useAnalysisStore } from "@/lib/state/analysis";
import { formatNsDecimal, tryParseNs } from "@/lib/time";


export function defineLabRoute(parent: AnyRoute) {
  return createRoute({
  getParentRoute: () => parent,
  path: "/lab/$datasetId/$sessionId",
  validateSearch: (search: Record<string, unknown>) => parseSearch(labSearchSchema, search),
  component: LabPage,
});
}

export function LabPage() {
  const { datasetId, sessionId } = useParams({ from: "/lab/$datasetId/$sessionId" });
  const search = useSearch({ from: "/lab/$datasetId/$sessionId" });
  const navigate = useNavigate();
  const hydrate = useAnalysisStore((state) => state.hydrate);
  const setNominalRate = useAnalysisStore((state) => state.setNominalRate);
  const session = useQuery(sessionQuery(datasetId, sessionId));

  const durableTimeNs = tryParseNs(search.t_ns);
  const durableSubject = search.subject ?? null;
  const durableView = search.view ?? "overview";
  const previousLabView = useRef(durableView);
  const previousRendererContext = useRef({
    datasetId,
    sessionId,
    view: durableView,
    trialId: search.trial ?? null,
    streamId: search.stream ?? null,
    modality: null as string | null,
    synchronizationSpecId: null as string | null,
    subjectId: search.subject ?? null,
    timeText: search.t_ns ?? null,
  });
  const preserveCanonicalTime = useRef(false);
  useEffect(() => {
    hydrate({
      committedTimeNs: durableTimeNs,
      focusedPanel: durableView,
    });
  }, [hydrate, durableTimeNs, durableView]);
  useEffect(() => {
    const previous = previousLabView.current;
    previousLabView.current = durableView;
    if (durableView !== "matchlab" || previous === "matchlab") return;
    useAnalysisStore.getState().setFieldCameraMode("tactical-map");
    useAnalysisStore.getState().setDashboardDomain("tactical");
    useAnalysisStore.getState().setPoseAnalysisSection("Live");
  }, [durableView]);
  useEffect(() => () => {
    useAnalysisStore.getState().resetTransient();
  }, [datasetId, sessionId]);

  const selectedStream = useMemo(() => {
    const streams = session.data?.streams ?? [];
    return streams.find((stream) => stream.stream_id === search.stream) ?? null;
  }, [search.stream, session.data]);
  useEffect(() => {
    setNominalRate(selectedStream?.nominal_sampling_rate_hz ?? null);
    return () => setNominalRate(null);
  }, [selectedStream, setNominalRate]);

  const updateSearch = useCallback(
    (patch: Partial<LabSearch>) => {
      void navigate({
        to: "/lab/$datasetId/$sessionId",
        params: { datasetId, sessionId },
        search: (previous: LabSearch) => ({ ...previous, ...patch }),
        replace: true,
      });
    },
    [datasetId, navigate, sessionId],
  );

  // Deterministic real-data defaults. Only keys the URL leaves open are filled,
  // so an explicit deep link and back/forward navigation keep exactly the state
  // they encoded; `replace` keeps the resolution out of the history stack.
  const detail = session.data;
  useEffect(() => {
    if (!detail) return;
    const { patch } = resolveLabDefaults(detail, search);
    if (!patchChangesSearch(patch, search)) return;
    updateSearch(patch);
  }, [detail, search, updateSearch]);

  // Canonical time authority: a renderer view always has a committed frame that
  // lies inside the selected stream's canonical span (RES-112 F-01/F-08/P-01).
  const rendererView =
    durableView === "signals" || durableView === "field" || durableView === "pose" || durableView === "matchlab";
  const timeArtifactId = rendererView ? (selectedStream?.sample_artifact_ids[0] ?? null) : null;
  const timeArtifact = useQuery({
    ...artifactQuery(timeArtifactId ?? ""),
    enabled: Boolean(timeArtifactId),
  });
  const poseStreamForMatch = detail?.streams.find(
    (stream) => stream.modality === "pose" && stream.trial_id === (selectedStream?.trial_id ?? search.trial),
  );
  const poseSubjectArtifactId = durableView === "matchlab" && search.subject === undefined && selectedStream?.modality === "tracking"
    ? poseStreamForMatch?.sample_artifact_ids[0] ?? null
    : null;
  const poseSubjectArtifact = useQuery({
    ...artifactQuery(poseSubjectArtifactId ?? ""),
    enabled: Boolean(poseSubjectArtifactId),
  });
  const awaitingPoseSubject = durableView === "pose" && search.subject === undefined;
  useEffect(() => {
    if (
      durableView !== "matchlab" ||
      search.subject !== undefined ||
      !detail ||
      (poseSubjectArtifactId !== null && poseSubjectArtifact.isPending)
    ) return;
    const selectedSubject = defaultMatchPlayerId(detail, poseSubjectArtifact.data, timeArtifact.data);
    if (selectedSubject !== null) updateSearch({ subject: selectedSubject });
  }, [
    detail,
    durableView,
    poseSubjectArtifact.data,
    poseSubjectArtifact.isPending,
    poseSubjectArtifactId,
    search.subject,
    timeArtifact.data,
    updateSearch,
  ]);
  useEffect(() => {
    const previous = previousRendererContext.current;
    const trialId = search.trial ?? selectedStream?.trial_id ?? null;
    const streamId = search.stream ?? null;
    const subjectId = search.subject ?? null;
    const periodChanged = previous.datasetId !== datasetId ||
      previous.sessionId !== sessionId ||
      previous.trialId !== trialId;
    // A linked Field/Pose view change shares canonical time even when the Pose
    // artifact has no exact sample at that instant.
    const explicitPoseTime =
      durableView === "pose" &&
      search.t_ns !== undefined &&
      durableTimeNs !== null &&
      !periodChanged;
    const streamChanged = previous.streamId !== streamId;
    const subjectChanged = previous.subjectId !== subjectId;
    const pairedFieldPoseSwitch =
      previous.view !== durableView &&
      previous.timeText === (search.t_ns ?? null) &&
      search.t_ns !== undefined &&
      previous.trialId !== null &&
      previous.trialId === trialId &&
      previous.subjectId === subjectId &&
      previous.synchronizationSpecId !== null &&
      previous.synchronizationSpecId === selectedStream?.synchronization_spec_id &&
      ((previous.modality === "tracking" && selectedStream?.modality === "pose") ||
        (previous.modality === "pose" && selectedStream?.modality === "tracking"));
    if (periodChanged) preserveCanonicalTime.current = false;
    else if (pairedFieldPoseSwitch) preserveCanonicalTime.current = true;
    else if (streamChanged || subjectChanged) preserveCanonicalTime.current = false;
    else if (previous.view !== durableView && previous.timeText === (search.t_ns ?? null) && search.t_ns !== undefined) {
      preserveCanonicalTime.current = true;
    }
    previousRendererContext.current = {
      datasetId,
      sessionId,
      view: durableView,
      trialId,
      streamId,
      modality: selectedStream?.modality ?? null,
      synchronizationSpecId: selectedStream?.synchronization_spec_id ?? null,
      subjectId,
      timeText: search.t_ns ?? null,
    };
    // An explicit Pose time is query state. Preserve gaps so Pose can report
    // observation bounds instead of moving the global playhead.
    if (explicitPoseTime) {
      preserveCanonicalTime.current = false;
      return;
    }
    if (preserveCanonicalTime.current) {
      if (!timeArtifact.data || awaitingPoseSubject) return;
      preserveCanonicalTime.current = false;
      return;
    }
    if (!timeArtifact.data || awaitingPoseSubject) return;
    const target = canonicalTimeDefault(timeArtifact.data, {
      currentNs: durableTimeNs,
      view: durableView,
      subjectId: durableSubject,
    });
    if (target === null) return;
    updateSearch({ t_ns: formatNsDecimal(target) });
  }, [awaitingPoseSubject, datasetId, durableSubject, durableTimeNs, durableView, search.stream, search.subject, search.t_ns, search.trial, selectedStream, sessionId, timeArtifact.data, updateSearch]);

  if (session.isPending) return <LoadingPanel label="Loading laboratory session" />;
  if (session.isError) {
    return <ErrorPanel error={session.error} onRetry={() => void session.refetch()} />;
  }

  const view: WorkbenchView = search.view ?? "overview";
  // A laboratory tab is offered only when this session has a stream that can
  // open it, so the workbench never advertises an analysis the data cannot
  // render. Provenance follows the selected result and is always reachable.
  const surfaces = sessionSurfaces(session.data.streams);
  // A deep link to a view this session offers no stream for keeps that view
  // selected, so the laboratory itself can state why it is empty (RES-112 S-02).
  const availableViews: WorkbenchView[] = [
    "overview",
    ...WORKBENCH_VIEWS.filter(
      (candidate): candidate is WorkbenchView =>
        candidate !== "overview" &&
        (candidate === "provenance" || candidate === view ||
          (candidate === "matchlab"
            ? surfaces.includes("field")
            : surfaces.includes(candidate as never))),
    ),
  ];
  const viewLabels: Record<WorkbenchView, string> = {
    overview: "overview",
    signals: "signals",
    field: "field",
    pose: "pose",
    matchlab: "MatchLab",
    provenance: "provenance",
  };
  return (
    <Suspense fallback={<LoadingPanel label="Opening laboratory" />}>
      <MatchLabCanvasRoot
        enabled={
          (view === "field" || view === "pose" || view === "matchlab") &&
          Boolean(selectedStream?.sample_artifact_ids[0])
        }
      >
        <div className="relative z-10 flex h-full min-h-0 flex-col">
        <div
          role="tablist"
          aria-label="Laboratory views"
          className="flex h-9 shrink-0 items-center gap-0.5 border-b border-border-subtle bg-surface-1 px-2"
        >
          {availableViews.map((candidate) => (
            <button
              key={candidate}
              type="button"
              role="tab"
              aria-selected={view === candidate}
              onClick={() => updateSearch({ view: candidate })}
              className={cn(
                "t-context relative rounded-control px-2.5 py-1 capitalize transition-colors duration-quick",
                view === candidate
                  ? "bg-surface-3 font-medium text-text-primary"
                  : "text-text-muted hover:bg-surface-2 hover:text-text-secondary",
              )}
            >
              {viewLabels[candidate]}
              {view === candidate ? (
                <span
                  aria-hidden="true"
                  className="t-tab-indicator absolute inset-x-2 -bottom-[5px] h-0.5 rounded-full bg-accent"
                />
              ) : null}
            </button>
          ))}
          <span className="ml-auto flex items-center gap-2 text-[11px] text-text-muted">
            {search.trial ? (
              <span title={`Selected trial ${search.trial}`}>
                Trial <span className="mono text-text-secondary">{search.trial}</span>
              </span>
            ) : null}
            {search.subject ? (
              <span title={`Selected subject ${search.subject}`}>
                Subject <span className="mono text-text-secondary">{search.subject}</span>
              </span>
            ) : null}
          </span>
        </div>
        {view === "matchlab" ? (
          <Suspense fallback={<div className="h-10 shrink-0 border-b border-border-subtle bg-surface-1" />}>
            <MatchLabContextSpine session={session.data} />
          </Suspense>
        ) : null}
        <div className="min-h-0 flex-1">
          {view === "overview" ? (
            <LabOverview
              datasetId={datasetId}
              sessionId={sessionId}
              streamFilter={search.stream ?? null}
              selectedResult={search.result ?? null}
              onSelectStream={(streamId) => updateSearch({ stream: streamId ?? undefined })}
              onSelectResult={(metricId, derivedMetricId) =>
                updateSearch({ metric: metricId, result: derivedMetricId })
              }
              onSelectSubject={(subjectId) => updateSearch({ subject: subjectId })}
            />
          ) : view === "signals" ? (
            <SignalLaboratory />
          ) : view === "field" ? (
            <PitchReplay />
          ) : view === "pose" ? (
            <Suspense fallback={<LoadingPanel label="Loading 3D laboratory" />}>
              <PoseViewer />
            </Suspense>
          ) : view === "matchlab" ? (
            <Group
              orientation="horizontal"
              id="matchlab-composition"
              data-testid="matchlab-composition"
              className="flex h-full min-h-0"
              resizeTargetMinimumSize={{ coarse: 28, fine: 6 }}
            >
              <Panel id="matchlab-field" defaultSize="48%" minSize="38%" className="min-w-0 overflow-hidden bg-transparent">
                <section aria-label="Field Tactical Map" data-testid="matchlab-field-panel" className="h-full min-h-0 overflow-hidden bg-transparent">
                  {selectedStream?.modality === "tracking" ? (
                    <PitchReplay />
                  ) : (
                    <StatePanel state="unsupported" title="Tactical tracking unavailable for this period" detail="MatchLab requires a registered tracking artifact for the left Tactical Map. No tactical positions are inferred from Pose." />
                  )}
                </section>
              </Panel>
              <Separator aria-label="Resize Field and Pose panels" className="w-px shrink-0 bg-border-subtle transition-colors data-[separator]:hover:bg-accent" />
              <Panel id="matchlab-pose" defaultSize="30%" minSize="24%" className="min-w-0 overflow-hidden bg-transparent">
                <MatchLabPoseViewport />
              </Panel>
              <Separator aria-label="Resize Pose and Analysis panels" className="w-px shrink-0 bg-border-subtle transition-colors data-[separator]:hover:bg-accent" />
              <Panel id="matchlab-analysis" defaultSize="22%" minSize="18%" className="min-w-0 overflow-hidden bg-surface-1">
                <MatchLabDashboard session={session.data} />
              </Panel>
            </Group>
          ) : (
            <StatePanel
              state="empty"
              title={`${view} view`}
              detail={
                selectedStream
                  ? `Preparing ${selectedStream.modality} stream ${selectedStream.stream_id}.`
                  : "Select a stream in the explorer or overview to populate this view."
              }
            />
          )}
        </div>
        </div>
      </MatchLabCanvasRoot>
    </Suspense>
  );
}
