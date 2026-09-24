import { useQuery } from "@tanstack/react-query";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  type ReactNode,
} from "react";

import type { SessionDetail, StreamView } from "@/api/types";
import { sessionQuery } from "@/lib/api/queries";
import { useAnalysisContext, type SubjectSelectionOptions } from "@/lib/analysis-context";
import { effectiveTimeNs, useAnalysisStore } from "@/lib/state/analysis";

export type MatchFrameSourceKind = "tracking" | "pose";
export type MatchFrameAvailability = "unknown" | "available" | "absent";

export interface MatchFrameSource {
  readonly streamId: string;
  readonly periodId: string | null;
  readonly artifactId: string | null;
  readonly measurementClass: string;
  readonly coordinateFrameId: string | null;
  readonly nominalRateHz: number | null;
}

export interface ResolvedMatchFrame {
  readonly identity: string | null;
  readonly canonicalTimeNs: bigint | null;
  readonly availability: MatchFrameAvailability;
}

export interface MatchFrameContextValue {
  readonly datasetId: string;
  readonly sessionId: string;
  readonly matchId: string;
  readonly periodId: string | null;
  readonly canonicalTimeNs: bigint | null;
  readonly selectedPlayerId: string | null;
  readonly hoveredPlayerId: string | null;
  readonly selectedTrackingObjectId: string | null;
  readonly selectedTeamId: string | null;
  readonly selectedTacticalObjectId: string | null;
  readonly hoveredTacticalObjectId: string | null;
  readonly trackingSource: MatchFrameSource | null;
  readonly poseSource: MatchFrameSource | null;
  readonly getResolvedFrame: (kind: MatchFrameSourceKind) => ResolvedMatchFrame;
  readonly reportResolvedFrame: (kind: MatchFrameSourceKind, frame: ResolvedMatchFrame) => void;
  readonly getCurrentTimeNs: () => bigint | null;
  readonly seekCanonicalTime: (timeNs: bigint) => void;
  readonly selectPlayer: (
    playerId: string | null,
    options?: SubjectSelectionOptions & { origin?: "field" | "pose" },
  ) => void;
  readonly selectTrackingObject: (objectId: string | null, objectType?: string | null) => void;
  readonly selectTeam: (teamId: string | null) => void;
  readonly selectTacticalObject: (objectId: string | null) => void;
  readonly hoverTacticalObject: (objectId: string | null) => void;
}

const MatchFrameContext = createContext<MatchFrameContextValue | null>(null);
const EMPTY_STREAMS: readonly StreamView[] = [];
const EMPTY_PARTICIPANTS: SessionDetail["participants"] = [];

export function streamsForPeriod(
  streams: readonly StreamView[],
  periodId: string | null,
): { readonly tracking: StreamView | null; readonly pose: StreamView | null } {
  if (periodId === null) return { tracking: null, pose: null };
  return {
    tracking: streams.find((stream) => stream.modality === "tracking" && stream.trial_id === periodId) ?? null,
    pose: streams.find((stream) => stream.modality === "pose" && stream.trial_id === periodId) ?? null,
  };
}

export function canonicalPlayerIdForTracking(
  objectId: string | null,
  objectType: string | null | undefined,
  participantIds: ReadonlySet<string>,
): string | null {
  return objectId !== null &&
    (objectType === "player" || objectType === "goalkeeper") &&
    participantIds.has(objectId)
    ? objectId
    : null;
}

function sourceFor(stream: StreamView | null): MatchFrameSource | null {
  if (stream === null) return null;
  return {
    streamId: stream.stream_id,
    periodId: stream.trial_id,
    artifactId: stream.sample_artifact_ids[0] ?? null,
    measurementClass: stream.measurement_class,
    coordinateFrameId: stream.coordinate_frame_id,
    nominalRateHz: stream.nominal_sampling_rate_hz,
  };
}

const EMPTY_FRAME: ResolvedMatchFrame = {
  identity: null,
  canonicalTimeNs: null,
  availability: "unknown",
};

export function MatchFrameContextProvider({
  poseVisible,
  children,
}: {
  readonly poseVisible: boolean;
  readonly children: ReactNode;
}) {
  const durable = useAnalysisContext();
  const sessionQueryResult = useQuery({
    ...sessionQuery(durable?.datasetId ?? "", durable?.sessionId ?? ""),
    enabled: Boolean(durable?.datasetId && durable?.sessionId),
  });
  const session = sessionQueryResult.data as SessionDetail | undefined;
  const streams = session?.streams ?? EMPTY_STREAMS;
  const selectedStream = streams.find((stream) => stream.stream_id === durable?.streamId) ?? null;
  const periodId = durable?.trialId ?? selectedStream?.trial_id ?? null;
  const pair = useMemo(() => streamsForPeriod(streams, periodId), [periodId, streams]);
  const participants = session?.participants ?? EMPTY_PARTICIPANTS;
  const participantIds = useMemo(
    () => new Set(participants.map((participant) => participant.subject_id)),
    [participants],
  );
  const durableSubject = durable?.subjectId ?? null;
  const selectedPlayerId =
    durableSubject !== null
      ? participantIds.has(durableSubject) ? durableSubject : null
      : durable?.entityId && participantIds.has(durable.entityId)
        ? durable.entityId
        : null;
  const hoveredEntityId = useAnalysisStore((state) => state.hoveredEntityId);
  const selectedTeamId = useAnalysisStore((state) => state.selectedTeamId);
  const selectedTacticalObjectId = useAnalysisStore((state) => state.selectedTacticalObjectId);
  const hoveredTacticalObjectId = useAnalysisStore((state) => state.hoveredTacticalObjectId);
  const sourceFramesRef = useRef<Record<MatchFrameSourceKind, ResolvedMatchFrame>>({
    tracking: EMPTY_FRAME,
    pose: EMPTY_FRAME,
  });
  const reportResolvedFrame = useCallback(
    (kind: MatchFrameSourceKind, frame: ResolvedMatchFrame) => {
      const previous = sourceFramesRef.current[kind];
      if (
        previous.identity !== frame.identity ||
        previous.canonicalTimeNs !== frame.canonicalTimeNs ||
        previous.availability !== frame.availability
      ) {
        sourceFramesRef.current[kind] = frame;
      }
    },
    [],
  );
  const getResolvedFrame = useCallback(
    (kind: MatchFrameSourceKind) => sourceFramesRef.current[kind],
    [],
  );

  useEffect(() => {
    sourceFramesRef.current = { tracking: EMPTY_FRAME, pose: EMPTY_FRAME };
  }, [durable?.datasetId, durable?.sessionId, periodId, pair.tracking?.stream_id, pair.pose?.stream_id]);

  const getCurrentTimeNs = useCallback(
    () => effectiveTimeNs(useAnalysisStore.getState()) ?? durable?.timeNs ?? null,
    [durable?.timeNs],
  );
  const seekCanonicalTime = useCallback(
    (timeNs: bigint) => {
      useAnalysisStore.getState().setPlaying(false);
      useAnalysisStore.getState().commitTime(timeNs);
      durable?.commitTime(timeNs);
    },
    [durable],
  );

  const selectPlayer = useCallback<MatchFrameContextValue["selectPlayer"]>(
    (playerId, options) => {
      if (durable === null) return;
      if (playerId === null) {
        sourceFramesRef.current.pose = EMPTY_FRAME;
        durable.selectFieldEntity(null);
        return;
      }
      const targetTimeNs = options?.targetTimeNs ?? getCurrentTimeNs();
      if (playerId !== selectedPlayerId) sourceFramesRef.current.pose = EMPTY_FRAME;
      if (
        playerId !== selectedPlayerId &&
        (options?.origin === "pose" || poseVisible) &&
        pair.pose !== null &&
        targetTimeNs !== null
      ) {
        useAnalysisStore.getState().beginSubjectSwitch(selectedPlayerId, targetTimeNs);
      } else if (targetTimeNs !== null) {
        useAnalysisStore.getState().commitTime(targetTimeNs);
      }
      durable.selectSubject(playerId, {
        ...(options?.replace !== undefined ? { replace: options.replace } : {}),
        ...(targetTimeNs !== null ? { targetTimeNs } : {}),
      });
    },
    [durable, getCurrentTimeNs, pair.pose, poseVisible, selectedPlayerId, sourceFramesRef],
  );

  const selectTrackingObject = useCallback<MatchFrameContextValue["selectTrackingObject"]>(
    (objectId, objectType) => {
      const playerId = canonicalPlayerIdForTracking(objectId, objectType, participantIds);
      if (playerId !== null) {
        selectPlayer(playerId, { origin: "field" });
      } else {
        sourceFramesRef.current.pose = EMPTY_FRAME;
        durable?.selectFieldEntity(objectId);
      }
    },
    [durable, participantIds, selectPlayer, sourceFramesRef],
  );
  const selectTeam = useCallback(
    (teamId: string | null) => useAnalysisStore.getState().selectTeam(teamId),
    [],
  );
  const selectTacticalObject = useCallback(
    (objectId: string | null) => useAnalysisStore.getState().selectTacticalObject(objectId),
    [],
  );
  const hoverTacticalObject = useCallback(
    (objectId: string | null) => useAnalysisStore.getState().hoverTacticalObject(objectId),
    [],
  );

  const value = useMemo<MatchFrameContextValue | null>(() => {
    if (durable === null) return null;
    return {
      datasetId: durable.datasetId,
      sessionId: durable.sessionId,
      matchId: session?.session.session_id ?? durable.sessionId,
      periodId,
      canonicalTimeNs: durable.timeNs,
      selectedPlayerId,
      hoveredPlayerId: hoveredEntityId !== null && participantIds.has(hoveredEntityId) ? hoveredEntityId : null,
      selectedTrackingObjectId:
        durable.subjectId !== null ? selectedPlayerId : selectedPlayerId ?? durable.entityId ?? null,
      selectedTeamId,
      selectedTacticalObjectId,
      hoveredTacticalObjectId,
      trackingSource: sourceFor(pair.tracking),
      poseSource: sourceFor(pair.pose),
      getResolvedFrame,
      reportResolvedFrame,
      getCurrentTimeNs,
      seekCanonicalTime,
      selectPlayer,
      selectTrackingObject,
      selectTeam,
      selectTacticalObject,
      hoverTacticalObject,
    };
  }, [
    durable,
    getResolvedFrame,
    getCurrentTimeNs,
    hoveredEntityId,
    hoverTacticalObject,
    hoveredTacticalObjectId,
    pair.pose,
    pair.tracking,
    participantIds,
    periodId,
    reportResolvedFrame,
    selectPlayer,
    seekCanonicalTime,
    selectTacticalObject,
    selectTeam,
    selectTrackingObject,
    selectedPlayerId,
    selectedTacticalObjectId,
    selectedTeamId,
    session?.session.session_id,
  ]);

  return <MatchFrameContext.Provider value={value}>{children}</MatchFrameContext.Provider>;
}

export function useMatchFrameContext(): MatchFrameContextValue | null {
  return useContext(MatchFrameContext);
}
