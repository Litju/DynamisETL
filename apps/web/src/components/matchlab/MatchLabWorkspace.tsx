import { Link } from "@tanstack/react-router";

import type { SessionDetail } from "@/api/types";
import { MeasurementClassBadge } from "@/components/common/Badges";
import { StatePanel } from "@/components/common/StatePanel";
import { PoseAnalysisPane } from "@/components/pose/PoseAnalysisPane";
import { PoseViewer } from "@/components/pose/PoseViewer";
import { TacticalAnalysisPane } from "@/components/shell/TacticalAnalysisPane";
import { useThrottledPlayhead } from "@/hooks/useThrottledPlayhead";
import { useAnalysisContext } from "@/lib/analysis-context";
import { useMatchFrameContext } from "@/lib/match-frame-context";
import { sessionTeams } from "@/components/pitch/pitch-model";
import { participantLabels } from "@/lib/participants";
import { formatClockNs } from "@/lib/time";
import { useAnalysisStore, type DashboardDomain } from "@/lib/state/analysis";

const DOMAIN_TABS: readonly { readonly id: DashboardDomain; readonly label: string }[] = [
  { id: "tactical", label: "Tactical" },
  { id: "biomechanics", label: "Biomechanics" },
  { id: "report", label: "Combined report" },
];

function frameStatus(
  availability: "unknown" | "available" | "absent",
  registered: boolean,
  label: string,
): string {
  if (!registered) return `${label} unavailable`;
  if (availability === "available") return `${label} sample`;
  if (availability === "absent") return `${label} gap`;
  return `${label} registered`;
}

/** Shared match/player/time spine for the integrated workstation. */
export function MatchLabContextSpine({ session }: { readonly session: SessionDetail }) {
  const context = useAnalysisContext();
  const matchFrame = useMatchFrameContext();
  const currentTime = useThrottledPlayhead(200) ?? context?.timeNs ?? null;
  const scalarMode = useAnalysisStore((state) => state.scalarFieldMode);
  const cameraMode = useAnalysisStore((state) => state.fieldCameraMode);
  const poseDisplayMode = useAnalysisStore((state) => state.poseDisplayMode);
  const participant = session.participants.find((item) => item.subject_id === matchFrame?.selectedPlayerId) ?? null;
  const teams = sessionTeams(session);
  const teamId = matchFrame?.selectedTeamId ?? participant?.group_label ?? null;
  const teamLabel = teamId === null ? "No team" : teams.labels.get(teamId) ?? teamId;
  const tracking = matchFrame?.getResolvedFrame("tracking");
  const pose = matchFrame?.getResolvedFrame("pose");
  const activeSurface = scalarMode === "elevation" ? "Analytical elevation" : `Scalar ${scalarMode}`;

  const items = [
    { label: "Match", value: session.session.label ?? session.session.session_id },
    { label: "Period", value: matchFrame?.periodId ?? context?.trialId ?? "—" },
    { label: "Time", value: currentTime === null ? "—" : formatClockNs(currentTime), mono: true },
    { label: "Team", value: teamLabel },
    { label: "Player", value: participant?.notes ? participantLabels(session).get(participant.subject_id) ?? participant.notes : participant?.subject_id ?? "Select a player" },
    { label: "Tracking", value: frameStatus(tracking?.availability ?? "unknown", matchFrame?.trackingSource !== null && matchFrame?.trackingSource !== undefined, "Tracking") },
    { label: "Pose", value: frameStatus(pose?.availability ?? "unknown", matchFrame?.poseSource !== null && matchFrame?.poseSource !== undefined, "Pose") },
    { label: "Tactical", value: `${context?.tacticalView ?? "live"} · ${cameraMode === "tactical-map" ? "Tactical Map" : cameraMode === "structure-lift" ? "Structure Lift" : "Perspective Explore"} · ${activeSurface}` },
    { label: "Alignment", value: matchFrame?.poseSource ? `Source native · ${poseDisplayMode === "body-local" ? "body-local display" : "match context"}` : "Tracking only · no Pose alignment" },
  ];

  return (
    <header data-testid="matchlab-context-spine" className="flex shrink-0 flex-wrap items-center gap-x-4 gap-y-1 border-b border-border-subtle bg-surface-1 px-3 py-1.5">
      {items.map((item) => (
        <div key={item.label} className="flex min-w-0 items-baseline gap-1.5" title={`${item.label}: ${item.value}`}>
          <span className="t-section shrink-0 text-text-muted">{item.label}</span>
          <span className={`${item.mono ? "mono tabular" : ""} max-w-56 truncate text-[10px] text-text-secondary`}>
            {item.value}
          </span>
        </div>
      ))}
    </header>
  );
}

/** One persistent right-side instrument containing the accepted analysis panes. */
export function MatchLabDashboard({ session }: { readonly session: SessionDetail }) {
  const context = useAnalysisContext();
  const matchFrame = useMatchFrameContext();
  const domain = useAnalysisStore((state) => state.dashboardDomain);
  const selectedPlayerId = matchFrame?.selectedPlayerId ?? "";
  const participant = session.participants.find((item) => item.subject_id === selectedPlayerId) ?? null;
  const labels = participantLabels(session);
  const teams = sessionTeams(session);
  const teamId = matchFrame?.selectedTeamId ?? participant?.group_label ?? null;
  const teamLabel = teamId === null ? "No team" : teams.labels.get(teamId) ?? teamId;
  const currentTime = useThrottledPlayhead(200) ?? context?.timeNs ?? null;

  const selectDomain = (next: DashboardDomain) => {
    const previous = useAnalysisStore.getState().dashboardDomain;
    if (next === "report") {
      context?.selectTacticalView?.("report");
      useAnalysisStore.getState().setPoseAnalysisSection("Range");
    } else if (next === "tactical" && previous === "report" && context?.tacticalView === "report") {
      context.selectTacticalView?.("live");
    }
    useAnalysisStore.getState().setDashboardDomain(next);
  };

  const poseUnavailable = (
    <StatePanel
      state="unsupported"
      title="Pose unavailable for this period"
      detail="This session has no registered Pose stream for the selected period. Tracking and tactical analysis remain available; no biomechanical values are inferred."
    />
  );

  return (
    <section aria-label="Analysis Dashboard" data-testid="matchlab-analysis-dashboard" className="flex h-full min-h-0 flex-col border-l border-border-subtle bg-surface-1">
      <header className="sticky top-0 z-10 shrink-0 border-b border-border-subtle bg-surface-1">
        <div className="px-3 py-2">
          <div className="flex items-center justify-between gap-2">
            <h2 className="t-section text-text-muted">Analysis Dashboard</h2>
            {matchFrame?.trackingSource ? (
              <MeasurementClassBadge measurementClass={matchFrame.trackingSource.measurementClass} compact />
            ) : null}
          </div>
          <label className="mt-1.5 block text-[10px] text-text-muted">
            Selected player
            <select
              aria-label="Dashboard selected player"
              value={selectedPlayerId}
              onChange={(event) => matchFrame?.selectPlayer(event.currentTarget.value || null, { origin: "dashboard" })}
              className="mono mt-0.5 block w-full rounded-control border border-border-subtle bg-surface-0 px-2 py-1 text-[11px] text-text-primary"
            >
              <option value="">No player selected</option>
              {session.participants.map((item) => (
                <option key={item.subject_id} value={item.subject_id}>
                  {labels.get(item.subject_id) ?? item.subject_id}
                </option>
              ))}
            </select>
          </label>
          <div className="mt-1 flex flex-wrap items-center justify-between gap-x-2 gap-y-0.5 text-[10px] text-text-muted">
            <span className="truncate">{teamLabel}{participant?.cohort ? ` · ${participant.cohort}` : ""}</span>
            <span className="mono tabular">{currentTime === null ? "—" : formatClockNs(currentTime)}</span>
          </div>
          <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-[9px] text-text-muted">
            <span>Tracking</span>
            {matchFrame?.trackingSource ? <MeasurementClassBadge measurementClass={matchFrame.trackingSource.measurementClass} compact /> : <span>unavailable</span>}
            <span className="ml-1">Pose</span>
            {matchFrame?.poseSource ? <MeasurementClassBadge measurementClass={matchFrame.poseSource.measurementClass} compact /> : <span>unavailable</span>}
          </div>
          <details className="mt-1 text-[9px] text-text-muted">
            <summary className="cursor-pointer hover:text-text-secondary">Source, measurement class and alignment</summary>
            <dl className="mt-1 space-y-1 border-l border-border-strong pl-2">
              <div>Tracking · {matchFrame?.trackingSource?.measurementClass ?? "unavailable"} · {matchFrame?.trackingSource?.coordinateFrameId ?? "coordinate frame unavailable"}</div>
              <div>Pose · {matchFrame?.poseSource?.measurementClass ?? "unavailable"} · {matchFrame?.poseSource?.coordinateFrameId ?? "coordinate frame unavailable"}</div>
              <div>Source timestamps resolve independently against canonical time; source XY is not silently fused.</div>
            </dl>
          </details>
        </div>
        <div role="tablist" aria-label="Analysis Dashboard domains" className="flex border-t border-border-subtle px-1">
          {DOMAIN_TABS.map((tab) => (
            <button
              key={tab.id}
              id={`matchlab-domain-${tab.id}`}
              type="button"
              role="tab"
              aria-selected={domain === tab.id}
              aria-controls="matchlab-dashboard-panel"
              onClick={() => selectDomain(tab.id)}
              className={`relative min-w-0 flex-1 px-1.5 py-1.5 text-[10px] ${domain === tab.id ? "font-medium text-text-primary" : "text-text-muted hover:text-text-secondary"}`}
            >
              {tab.label}
              {domain === tab.id ? <span aria-hidden="true" className="t-tab-indicator absolute inset-x-1 bottom-0 h-0.5 rounded-full bg-accent" /> : null}
            </button>
          ))}
        </div>
      </header>
      <div
        id="matchlab-dashboard-panel"
        role="tabpanel"
        aria-labelledby={`matchlab-domain-${domain}`}
        className="min-h-0 flex-1 overflow-hidden"
      >
        {domain === "tactical" ? <TacticalAnalysisPane embedded /> : null}
        {domain === "biomechanics" ? (
          matchFrame?.poseSource ? <PoseAnalysisPane embedded /> : poseUnavailable
        ) : null}
        {domain === "report" ? (
          <div className="h-full min-h-0 overflow-y-auto px-3 py-2">
            <p className="mono mb-2 text-[9px] text-text-muted">
              Selected range · {context?.fromNs !== null && context?.fromNs !== undefined && context.toNs !== null
                ? `${formatClockNs(context.fromNs)}–${formatClockNs(context.toNs)}`
                : "no committed range"} · exact canonical time {currentTime === null ? "unavailable" : formatClockNs(currentTime)}
            </p>
            <section aria-label="Tactical range report" className="border-b border-border-subtle pb-2">
              <h3 className="t-section mb-1 text-text-muted">Tactical · RES-110 / MatchLab V3</h3>
              <TacticalAnalysisPane embedded reportOnly />
            </section>
            <section aria-label="Pose range report" className="pt-2">
              <h3 className="t-section mb-1 text-text-muted">Biomechanics · RES-111</h3>
              {matchFrame?.poseSource
                ? <PoseAnalysisPane embedded sectionOverride="Range" />
                : poseUnavailable}
            </section>
          </div>
        ) : null}
      </div>
      <nav aria-label="Analysis evidence" className="flex shrink-0 flex-wrap gap-x-3 gap-y-1 border-t border-border-subtle px-3 py-2 text-[10px]">
        <Link to="/methods" className="text-accent hover:underline">Methods</Link>
        <Link to="/runs" search={{ dataset: context?.datasetId }} className="text-accent hover:underline">Runs / provenance</Link>
        <Link to="/quality" search={{ dataset: context?.datasetId }} className="text-accent hover:underline">Quality / rights</Link>
      </nav>
    </section>
  );
}

/** The centre viewport stays a real 3D Pose scene, with an explicit fail-closed source state. */
export function MatchLabPoseViewport() {
  const matchFrame = useMatchFrameContext();
  return (
    <section aria-label="Pose 3D" data-testid="matchlab-pose-viewport" className="h-full min-h-0 overflow-hidden bg-transparent">
      {matchFrame?.poseSource ? (
        <PoseViewer compactControls />
      ) : (
        <div data-testid="matchlab-pose-unavailable" className="flex h-full min-h-0 items-center justify-center border-l border-border-subtle px-4">
          <StatePanel
            state="unsupported"
            title="Pose unavailable for this period"
            detail="The selected session has registered tracking but no Pose stream. The 3D player view and biomechanics remain unavailable; tactical analysis continues from the accepted tracking source."
          />
        </div>
      )}
    </section>
  );
}
