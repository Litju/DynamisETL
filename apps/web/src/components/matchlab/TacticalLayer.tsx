import { useEffect, useMemo } from "react";
import type { ThreeEvent } from "@react-three/fiber";
import { Shape, ShapeGeometry, DoubleSide } from "three";

import { Polyline } from "@/components/matchlab/Polyline";
import type { PitchEvent, TacticalOverlay, TacticalRole } from "@/components/matchlab/render-types";
import type { TrackingWindowBuffers } from "@/components/matchlab/frame-buffers";
import type { TacticalV3Frame } from "@/components/pitch/tactical-v3";
import { jsonIds, unitPointInSourceFrame } from "@/components/pitch/tactical-v3";
import type { TacticalRow } from "@/components/pitch/tactical-overlay";
import type { MatchFrameContextValue } from "@/lib/match-frame-context";
import type { TacticalRelationMode } from "@/lib/state/analysis";
import { FIELD_RENDER_DEPTH_M } from "@/components/matchlab/render-layer-depths";

export interface TacticalLayerPalette {
  readonly home: string;
  readonly away: string;
  readonly other: string;
  readonly event: string;
  readonly selection: string;
}

function roleColor(role: TacticalRole, palette: TacticalLayerPalette): string {
  return role === "home" ? palette.home : role === "away" ? palette.away : palette.other;
}

function TacticalPolygon({
  points,
  color,
  depthM,
  opacity,
  selected,
  objectId,
  matchFrame,
}: {
  readonly points: readonly (readonly [number, number])[];
  readonly color: string;
  readonly depthM: number;
  readonly opacity: number;
  readonly selected: boolean;
  readonly objectId: string;
  readonly matchFrame: MatchFrameContextValue;
}) {
  // Worker parses polygon rows once per window; this adapter builds only the currently drawn geometry.
  const shape = useMemo(() => {
    const value = new Shape();
    const first = points[0];
    if (first) {
      value.moveTo(first[0], first[1]);
      for (const point of points.slice(1)) value.lineTo(point[0], point[1]);
      value.closePath();
    }
    return value;
  }, [points]);
  const geometry = useMemo(() => new ShapeGeometry(shape), [shape]);
  const linePoints = useMemo(
    () => {
      const vertices = points.map(([xM, yM]) => [xM, FIELD_RENDER_DEPTH_M.shapeOutline, -yM] as const);
      return points.length > 2 ? [...vertices, vertices[0]!] : vertices;
    },
    [depthM, points],
  );
  useEffect(() => () => geometry.dispose(), [geometry]);
  const colorValue = selected ? matchFrame.selectedTacticalObjectId === objectId ? "#ffffff" : color : color;
  const select = (event: ThreeEvent<MouseEvent>) => {
    event.stopPropagation();
    matchFrame.selectTacticalObject(objectId);
  };
  return (
    <group>
      {points.length >= 3 ? (
        <mesh
          geometry={geometry}
          rotation={[-Math.PI / 2, 0, 0]}
          position={[0, depthM, 0]}
          onClick={select}
          onPointerOver={() => matchFrame.hoverTacticalObject(objectId)}
          onPointerOut={() => matchFrame.hoverTacticalObject(null)}
        >
          <meshBasicMaterial color={color} transparent opacity={opacity} depthWrite={false} side={DoubleSide} />
        </mesh>
      ) : null}
      {linePoints.length > 1 ? (
        <Polyline
          points={linePoints}
          color={colorValue}
          onClick={select}
          onPointerOver={() => matchFrame.hoverTacticalObject(objectId)}
          onPointerOut={() => matchFrame.hoverTacticalObject(null)}
        />
      ) : null}
    </group>
  );
}

function InfluenceCell({
  xM,
  yM,
  widthM,
  heightM,
  arrivalTimeS,
  color,
  objectId,
  selected,
  matchFrame,
}: {
  readonly xM: number;
  readonly yM: number;
  readonly widthM: number;
  readonly heightM: number;
  readonly arrivalTimeS: number;
  readonly color: string;
  readonly objectId: string;
  readonly selected: boolean;
  readonly matchFrame: MatchFrameContextValue;
}) {
  if (![xM, yM, widthM, heightM, arrivalTimeS].every(Number.isFinite) || widthM <= 0 || heightM <= 0) {
    return null;
  }
  const alpha = Math.max(0.05, Math.min(0.2, 0.2 - arrivalTimeS * 0.015));
  return (
    <mesh
      position={[xM, FIELD_RENDER_DEPTH_M.scalarFlat, -yM]}
      rotation={[-Math.PI / 2, 0, 0]}
      onClick={(event) => {
        event.stopPropagation();
        matchFrame.selectTacticalObject(objectId);
      }}
      onPointerOver={() => matchFrame.hoverTacticalObject(objectId)}
      onPointerOut={() => matchFrame.hoverTacticalObject(null)}
    >
      <planeGeometry args={[widthM * 0.72, heightM * 0.72]} />
      <meshBasicMaterial
        color={selected ? "#ffffff" : color}
        transparent
        opacity={selected ? Math.min(0.35, alpha + 0.15) : alpha}
        depthWrite={false}
        side={DoubleSide}
      />
    </mesh>
  );
}

function SourceEventMark({
  event,
  matchFrame,
  color,
}: {
  readonly event: PitchEvent;
  readonly matchFrame: MatchFrameContextValue;
  readonly color: string;
}) {
  const objectId = "event:" + event.eventId;
  return (
    <mesh
      position={[event.xM, FIELD_RENDER_DEPTH_M.sourceEvent, -event.yM]}
      rotation={[-Math.PI / 2, 0, Math.PI / 4]}
      onClick={(pointer) => {
        pointer.stopPropagation();
        matchFrame.selectTacticalObject(objectId);
      }}
      onPointerOver={() => matchFrame.hoverTacticalObject(objectId)}
      onPointerOut={() => matchFrame.hoverTacticalObject(null)}
    >
      <circleGeometry args={[0.24, 4]} />
      <meshBasicMaterial color={color} />
    </mesh>
  );
}

export function TacticalLayer({
  overlay,
  tacticalV3,
  events,
  matchFrame,
  palette,
  relationMode,
  trackingBuffers,
  trackingFrameIndex,
  layers = { geometry: true, territory: true, influence: true, events: true },
  visible = true,
}: {
  readonly overlay: TacticalOverlay;
  readonly tacticalV3: TacticalV3Frame;
  readonly events: readonly PitchEvent[];
  readonly matchFrame: MatchFrameContextValue;
  readonly palette: TacticalLayerPalette;
  readonly relationMode: TacticalRelationMode;
  readonly trackingBuffers: TrackingWindowBuffers | null;
  readonly trackingFrameIndex: number;
  readonly layers?: {
    readonly geometry: boolean;
    readonly territory: boolean;
    readonly influence: boolean;
    readonly events: boolean;
  };
  readonly visible?: boolean;
}) {
  const positions = useMemo(() => {
    const output = new Map<string, readonly [number, number]>();
    if (trackingBuffers === null || trackingFrameIndex < 0) return output;
    const start = trackingBuffers.frameOffsets[trackingFrameIndex]!;
    const end = trackingBuffers.frameOffsets[trackingFrameIndex + 1]!;
    for (let row = start; row < end; row += 1) {
      const id = trackingBuffers.entityIds[trackingBuffers.entityIndexes[row]!];
      if (!id) continue;
      output.set(id, [trackingBuffers.positionsXY[row * 2]!, trackingBuffers.positionsXY[row * 2 + 1]!]);
    }
    return output;
  }, [trackingBuffers, trackingFrameIndex]);
  const teamIds = [...new Set(tacticalV3.units.map((row) => row["group_id"]).filter((id): id is string => typeof id === "string"))];
  const focusId = matchFrame.selectedTrackingObjectId ?? matchFrame.selectedPlayerId;
  const graphEdges = relationMode === "stable-graph"
    ? tacticalV3.edges.filter((row) => row["stable_edge"] === true && (
      focusId !== null
        ? row["player_a_id"] === focusId || row["player_b_id"] === focusId
        : row["group_id"] === (matchFrame.selectedTeamId ?? teamIds[0])
    ))
    : [];
  const localTriangles = relationMode === "selected-triangles" && focusId !== null
    ? tacticalV3.triangles.filter((row) => row["stable_triangle"] === true && jsonIds(row["triangle_player_ids_json"]).includes(focusId))
    : [];
  const relationRows = relationMode === "attacker-defender"
    ? tacticalV3.interactions.filter((row) => row["attacker_id"] === focusId || matchFrame.selectedTacticalObjectId === `attacker-defender:${row["attacker_id"]}:${row["nearest_defender_id"]}`)
    : [];
  return (
    <group name="TacticalLayer" visible={visible}>
      <FunctionalStructure rows={tacticalV3.units} teamOrder={teamIds} palette={palette} matchFrame={matchFrame} positions={positions} />
      {relationMode === "stable-graph" ? graphEdges.map((row) => {
        const a = String(row["player_a_id"] ?? "");
        const b = String(row["player_b_id"] ?? "");
        const first = positions.get(a);
        const second = positions.get(b);
        if (!first || !second) return null;
        const objectId = `shape-edge:${row["group_id"]}:${a}:${b}`;
        const selected = matchFrame.selectedTacticalObjectId === objectId;
        return <Polyline key={objectId} points={[[first[0], FIELD_RENDER_DEPTH_M.stableGraph, -first[1]], [second[0], FIELD_RENDER_DEPTH_M.stableGraph, -second[1]]]} color={selected ? "#ffffff" : roleColor(row["group_id"] === teamIds[0] ? "home" : row["group_id"] === teamIds[1] ? "away" : "other", palette)} opacity={selected ? 1 : 0.82} onClick={(event) => { event.stopPropagation(); matchFrame.selectTacticalObject(objectId); }} onPointerOver={() => matchFrame.hoverTacticalObject(objectId)} onPointerOut={() => matchFrame.hoverTacticalObject(null)} />;
      }) : null}
      {localTriangles.map((row) => {
        const ids = jsonIds(row["triangle_player_ids_json"]);
        const vertices = ids.map((id) => positions.get(id)).filter((point): point is readonly [number, number] => point !== undefined);
        if (vertices.length !== 3) return null;
        const objectId = `tactical-triangle:${row["group_id"]}:${ids.join(":")}`;
        const color = matchFrame.selectedTacticalObjectId === objectId ? "#ffffff" : palette.selection;
        return <group key={objectId}><Polyline points={[...vertices.map(([x, y]) => [x, FIELD_RENDER_DEPTH_M.localTriangle, -y] as const), [vertices[0]![0], FIELD_RENDER_DEPTH_M.localTriangle, -vertices[0]![1]]]} color={color} opacity={0.95} onClick={(event) => { event.stopPropagation(); matchFrame.selectTacticalObject(objectId); }} onPointerOver={() => matchFrame.hoverTacticalObject(objectId)} onPointerOut={() => matchFrame.hoverTacticalObject(null)} /></group>;
      })}
      {relationRows.map((row) => {
        const attacker = String(row["attacker_id"] ?? "");
        const defender = String(row["nearest_defender_id"] ?? "");
        const first = positions.get(attacker);
        const second = positions.get(defender);
        if (!first || !second) return null;
        const objectId = `attacker-defender:${attacker}:${defender}`;
        return <group key={objectId}><Polyline points={[[first[0], FIELD_RENDER_DEPTH_M.attackerDefender, -first[1]], [second[0], FIELD_RENDER_DEPTH_M.attackerDefender, -second[1]]]} color={matchFrame.selectedTacticalObjectId === objectId ? "#ffffff" : palette.event} dashed onClick={(event) => { event.stopPropagation(); matchFrame.selectTacticalObject(objectId); }} onPointerOver={() => matchFrame.hoverTacticalObject(objectId)} onPointerOut={() => matchFrame.hoverTacticalObject(null)} /></group>;
      })}
      {layers.geometry ? overlay.hulls.map((hull) => {
        const objectId = "team-shape:" + hull.groupId;
        return (
          <TacticalPolygon
            key={objectId}
            points={hull.points}
            color={roleColor(hull.role, palette)}
            depthM={FIELD_RENDER_DEPTH_M.hullFill}
            opacity={0.06}
            selected={matchFrame.selectedTacticalObjectId === objectId}
            objectId={objectId}
            matchFrame={matchFrame}
          />
        );
      }) : null}
      {layers.territory ? overlay.territoryCells.map((cell) => {
        const objectId = "territory:" + cell.entityId;
        return (
          <TacticalPolygon
            key={objectId}
            points={cell.points}
            color={roleColor(cell.role, palette)}
            depthM={FIELD_RENDER_DEPTH_M.territoryFill}
            opacity={matchFrame.selectedTacticalObjectId === objectId ? 0.16 : 0.06}
            selected={matchFrame.selectedTacticalObjectId === objectId}
            objectId={objectId}
            matchFrame={matchFrame}
          />
        );
      }) : null}
      {layers.influence ? overlay.influenceCells.map((cell) => {
        const objectId = "influence:" + cell.groupId + ":" + cell.xM + ":" + cell.yM;
        return (
          <InfluenceCell
            key={objectId}
            {...cell}
            objectId={objectId}
            color={roleColor(cell.role, palette)}
            selected={matchFrame.selectedTacticalObjectId === objectId}
            matchFrame={matchFrame}
          />
        );
      }) : null}
      {layers.events ? events.map((event) => (
        <SourceEventMark key={event.eventId} event={event} matchFrame={matchFrame} color={palette.event} />
      )) : null}
    </group>
  );
}

function FunctionalStructure({
  rows,
  teamOrder,
  palette,
  matchFrame,
  positions,
}: {
  readonly rows: readonly TacticalRow[];
  readonly teamOrder: readonly string[];
  readonly palette: TacticalLayerPalette;
  readonly matchFrame: MatchFrameContextValue;
  readonly positions: ReadonlyMap<string, readonly [number, number]>;
}) {
  const teams = [...new Set(rows.map((row) => row["group_id"]).filter((id): id is string => typeof id === "string"))]
    .sort((a, b) => teamOrder.indexOf(a) - teamOrder.indexOf(b));
  return <group name="FunctionalUnitStructure">{teams.map((teamId) => {
    const teamRows = rows.filter((row) => row["group_id"] === teamId);
    const byRole = new Map(teamRows.flatMap((row) => typeof row["functional_unit"] === "string" ? [[row["functional_unit"], row] as const] : []));
    const color = roleColor(teamId === teamOrder[0] ? "home" : teamId === teamOrder[1] ? "away" : "other", palette);
    const orderedRoles = ["DEF", "MID", "ATT"];
    const centers = orderedRoles.map((role) => ({ role, row: byRole.get(role), point: unitPointInSourceFrame(byRole.get(role) ?? {}) })).filter((item): item is { role: string; row: TacticalRow; point: readonly [number, number] } => item.row !== undefined && item.point !== null);
    return <group key={teamId}>
      {centers.length > 1 ? <Polyline points={centers.map(({ point }) => [point[0], FIELD_RENDER_DEPTH_M.structureSpine, -point[1]] as const)} color={color} opacity={0.88} /> : null}
      {centers.map(({ role, row, point }) => {
        const objectId = `functional-unit:${teamId}:${role}`;
        const flip = row["attacking_direction"] === "right_to_left" ? -1 : 1;
        const orientation = row["orientation_deg"];
        const majorSd = row["major_axis_sd_m"];
        const minorSd = row["minor_axis_sd_m"];
        const angle = typeof orientation === "number" ? orientation * Math.PI / 180 : null;
        const memberPoints = jsonIds(row["role_ids_json"]).flatMap((id) => {
          const member = positions.get(id);
          return member ? [[member[0], FIELD_RENDER_DEPTH_M.structureSpine, -member[1]] as const] : [];
        });
        const majorEnds = angle !== null && typeof majorSd === "number" && majorSd > 0.08 ? [
          [point[0] - Math.cos(angle) * flip * majorSd, FIELD_RENDER_DEPTH_M.structureSpine, -(point[1] - Math.sin(angle) * flip * majorSd)] as const,
          [point[0] + Math.cos(angle) * flip * majorSd, FIELD_RENDER_DEPTH_M.structureSpine, -(point[1] + Math.sin(angle) * flip * majorSd)] as const,
        ] : null;
        const minorEnds = angle !== null && typeof minorSd === "number" && minorSd > 0.08 ? [
          [point[0] + Math.sin(angle) * flip * minorSd, FIELD_RENDER_DEPTH_M.structureSpine, -(point[1] - Math.cos(angle) * flip * minorSd)] as const,
          [point[0] - Math.sin(angle) * flip * minorSd, FIELD_RENDER_DEPTH_M.structureSpine, -(point[1] + Math.cos(angle) * flip * minorSd)] as const,
        ] : null;
        const memberIds = jsonIds(row["role_ids_json"]);
        const selected = memberIds.includes(matchFrame.selectedTrackingObjectId ?? "");
        return <group key={objectId}>
          {memberPoints.length === 2 ? <Polyline points={memberPoints} color={color} opacity={0.92} /> : null}
          {majorEnds ? <Polyline points={majorEnds} color={color} opacity={0.9} /> : null}
          {minorEnds ? <Polyline points={minorEnds} color={color} opacity={0.75} /> : null}
          <mesh position={[point[0], FIELD_RENDER_DEPTH_M.structureNode, -point[1]]} rotation={[-Math.PI / 2, 0, Math.PI / 4]} onClick={(event) => { event.stopPropagation(); matchFrame.selectTeam(teamId); matchFrame.selectTacticalObject(objectId); }}>
            <circleGeometry args={[0.34, 4]} />
            <meshBasicMaterial color={selected ? "#ffffff" : color} />
          </mesh>
        </group>;
      })}
    </group>;
  })}</group>;
}
