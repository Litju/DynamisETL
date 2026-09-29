import { Dialog } from "@base-ui/react/dialog";
import { useQuery } from "@tanstack/react-query";
import { ArrowUpRight, Map as MapIcon, X } from "lucide-react";
import type { ReactNode } from "react";

import type { SessionDetail } from "@/api/types";
import { AppLink } from "@/components/common/AppLink";
import { BrowserReadiness, ReadinessGlyph } from "@/components/common/Readiness";
import { MatchNavigator } from "@/components/matchlab/MatchNavigator";
import { sessionTeams } from "@/components/pitch/pitch-model";
import { useThrottledPlayhead } from "@/hooks/useThrottledPlayhead";
import { seasonLinksQuery, seasonRowsQuery } from "@/lib/api/queries";
import { useAnalysisContext } from "@/lib/analysis-context";
import { useArtifactsLoadState } from "@/lib/browser-cache";
import { useMatchFrameContext } from "@/lib/match-frame-context";
import { participantLabels } from "@/lib/participants";
import { useAnalysisStore } from "@/lib/state/analysis";
import { useUiStore } from "@/lib/state/ui";
import { formatClockNs } from "@/lib/time";
import { useCatalog } from "@/lib/use-catalog";
import { seasonWorldTarget } from "@/lib/worlds";

function frameStatus(availability: "unknown" | "available" | "absent", registered: boolean): string {
  if (!registered) return "unavailable";
  if (availability === "available") return "sample";
  if (availability === "absent") return "gap";
  return "registered";
}

/**
 * Season World bridge for the selected match player.
 *
 * The season subject is dataset-scoped; the link is offered only when the
 * season identity crosswalk lists *this* session among the player's
 * materialized appearances. Names are never compared.
 */
export function useSeasonBridge(session: SessionDetail, subjectId: string | null) {
  const catalog = useCatalog();
  const contest = catalog.resources.find(
    (resource) => resource.resource_kind === "contest" && resource.session_id === session.session.session_id &&
      (resource.dataset_ids ?? []).includes(session.dataset_id),
  );
  const editionId = contest?.edition_id ?? null;
  const seasonReady = Boolean(editionId && catalog.tree.some((sport) => sport.competitions.some((competition) =>
    competition.editions.some((edition) => edition.editionId === editionId && edition.worlds.some((link) => link.world === "season" && link.ready)))));
  const seasonSubject = subjectId ? `${session.dataset_id}/${subjectId}` : null;
  const links = useQuery({
    ...seasonLinksQuery(editionId ?? "", seasonSubject ?? ""),
    enabled: Boolean(seasonReady && editionId && seasonSubject),
    retry: false,
  });
  const verified = Boolean(links.data?.appearances.some(
    (item) => item.dataset_id === session.dataset_id && item.session_id === session.session.session_id,
  ));
  const row = useQuery({
    ...seasonRowsQuery({ editionId: editionId ?? "", family: "physical", metrics: [], subjectIds: seasonSubject ? [seasonSubject] : [], limit: 2 }),
    enabled: verified,
  });
  const teamId = row.data?.rows[0]?.team_id;
  if (!verified || !editionId || !seasonSubject) return null;
  return seasonWorldTarget(editionId, { player: seasonSubject, ...(teamId ? { team: teamId } : {}) });
}

/**
 * Match World instrument strip: one line of *live* analytical state (time,
 * team, player, source frame status, tactical mode, readiness). Match,
 * competition and period live in the global context spine; the Navigator
 * opens as an overlay so it never takes width from the spatial analysis.
 */
export function MatchWorldStrip({ session, tabs }: { readonly session: SessionDetail; readonly tabs?: ReactNode }) {
  const context = useAnalysisContext();
  const matchFrame = useMatchFrameContext();
  const currentTime = useThrottledPlayhead(200) ?? context?.timeNs ?? null;
  const scalarMode = useAnalysisStore((state) => state.scalarFieldMode);
  const cameraMode = useAnalysisStore((state) => state.fieldCameraMode);
  const participant = session.participants.find((item) => item.subject_id === matchFrame?.selectedPlayerId) ?? null;
  const teams = sessionTeams(session);
  const teamId = matchFrame?.selectedTeamId ?? participant?.group_label ?? null;
  const teamLabel = teamId === null ? "No team" : teams.labels.get(teamId) ?? teamId;
  const tracking = matchFrame?.getResolvedFrame("tracking");
  const pose = matchFrame?.getResolvedFrame("pose");
  const playerLabel = participant ? participantLabels(session).get(participant.subject_id) ?? participant.notes ?? participant.subject_id : "No player selected";
  const browser = useArtifactsLoadState(session.streams.flatMap((stream) => stream.sample_artifact_ids));
  const seasonTarget = useSeasonBridge(session, participant?.subject_id ?? null);
  const cameraLabel = cameraMode === "tactical-map" ? "Tactical Map" : cameraMode === "structure-lift" ? "Structure Lift" : "Perspective";
  const trackingState = frameStatus(tracking?.availability ?? "unknown", Boolean(matchFrame?.trackingSource));
  const poseState = frameStatus(pose?.availability ?? "unknown", Boolean(matchFrame?.poseSource));

  return (
    <header
      data-testid="matchlab-context-spine"
      aria-label="Match World state"
      className="flex h-10 shrink-0 items-center gap-4 border-b border-border-subtle bg-surface-1 pl-2 pr-3 text-[11px]"
    >
      <MatchNavigatorDrawer />
      {tabs}
      <span aria-hidden="true" className="h-4 w-px bg-border-subtle" />
      <span className="mono text-[13px] font-medium tabular text-text-primary" title="Canonical time">
        {currentTime === null ? "—" : formatClockNs(currentTime)}
      </span>
      <StripItem label="Team" value={teamLabel} className="max-[1500px]:hidden" />
      <StripItem label="Player" value={playerLabel} strong />
      {seasonTarget ? (
        <AppLink
          to={seasonTarget}
          transition
          className="flex shrink-0 items-center gap-1 rounded-[5px] px-1.5 py-0.5 text-accent transition-colors hover:bg-hover"
          title="Open this player's season profile in Season World (identity crosswalk verified)"
        >
          Season profile <ArrowUpRight size={12} aria-hidden="true" />
        </AppLink>
      ) : null}
      <span className="flex items-center gap-1.5 text-text-muted" title={`Tracking frame: ${trackingState}`}>
        <ReadinessGlyph kind={trackingState === "sample" ? "ready" : trackingState === "unavailable" ? "unavailable" : "upstream"} />
        Tracking <span className="text-text-secondary">{trackingState}</span>
      </span>
      <span className="flex items-center gap-1.5 text-text-muted" title={`Pose frame: ${poseState}`}>
        <ReadinessGlyph kind={poseState === "sample" ? "ready" : poseState === "unavailable" ? "unavailable" : "upstream"} />
        Pose <span className="text-text-secondary">{poseState}</span>
      </span>
      <StripItem
        label="Tactical"
        value={`${context?.tacticalView ?? "live"} · ${cameraLabel} · ${scalarMode === "elevation" ? "elevation" : scalarMode}`}
        className="max-[1500px]:hidden"
      />
      <StripItem
        label="Alignment"
        value={matchFrame?.poseSource ? "Source native" : "Tracking only"}
        className="max-[1650px]:hidden"
      />
      <span className="ml-auto flex shrink-0 items-center gap-3">
        <span className="flex items-center gap-1.5 text-text-muted"><ReadinessGlyph kind="ready" />Ready server-side</span>
        <BrowserReadiness state={browser} />
      </span>
    </header>
  );
}

function StripItem({ label, value, strong = false, className }: { label: string; value: string; strong?: boolean; className?: string }) {
  return (
    <span className={`flex items-baseline gap-1.5 ${strong ? "shrink-0" : "min-w-0"} ${className ?? ""}`} title={`${label}: ${value}`}>
      <span className="shrink-0 text-text-faint">{label}</span>
      <span className={strong ? "shrink-0 whitespace-nowrap font-medium text-text-primary" : "max-w-48 truncate text-text-secondary"}>{value}</span>
    </span>
  );
}

/**
 * Match Navigator as an L2 overlay drawer over the spatial scene (glass is
 * reserved for exactly this). Base UI owns focus trapping, Escape and focus
 * return; `N` toggles it from anywhere in the World.
 */
export function MatchNavigatorDrawer() {
  const open = useUiStore((state) => state.navigatorOpen);
  const setOpen = useUiStore((state) => state.setNavigatorOpen);
  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger
        className="flex h-7 shrink-0 items-center gap-1.5 rounded-control border border-border-subtle px-2 text-[11.5px] font-medium text-text-secondary transition-colors hover:border-border-strong hover:text-text-primary data-[popup-open]:border-selected-border data-[popup-open]:text-text-primary"
        aria-label="Open Match Navigator"
      >
        <MapIcon size={13} aria-hidden="true" className="text-accent" />
        Navigator
        <kbd className="d-kbd ml-0.5">N</kbd>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Backdrop className="d-backdrop fixed inset-0 top-11 z-40 bg-transparent" />
        <Dialog.Popup
          aria-label="Match Navigator"
          className="d-overlay-glass d-drawer-left fixed bottom-3 left-3 top-[3.25rem] z-50 flex w-[23rem] flex-col overflow-hidden outline-none"
        >
          <Dialog.Title className="sr-only">Match Navigator</Dialog.Title>
          <Dialog.Close
            aria-label="Close Match Navigator"
            className="absolute right-2 top-2 z-10 flex size-7 items-center justify-center rounded-control text-text-muted hover:bg-hover hover:text-text-primary"
          >
            <X size={14} aria-hidden="true" />
          </Dialog.Close>
          <div className="min-h-0 flex-1">
            <MatchNavigator compact />
          </div>
        </Dialog.Popup>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
