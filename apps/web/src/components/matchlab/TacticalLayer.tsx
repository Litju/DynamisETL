import { useEffect, useMemo } from "react";
import { Line } from "@react-three/drei";
import type { ThreeEvent } from "@react-three/fiber";
import { Shape, ShapeGeometry, DoubleSide } from "three";

import type { PitchEvent, TacticalOverlay, TacticalRole } from "@/components/matchlab/render-types";
import type { MatchFrameContextValue } from "@/lib/match-frame-context";

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
  opacity,
  selected,
  objectId,
  matchFrame,
}: {
  readonly points: readonly (readonly [number, number])[];
  readonly color: string;
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
      const vertices = points.map(([xM, yM]) => [xM, 0.025, -yM] as const);
      return points.length > 2 ? [...vertices, vertices[0]!] : vertices;
    },
    [points],
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
          position={[0, 0.018, 0]}
          onClick={select}
          onPointerOver={() => matchFrame.hoverTacticalObject(objectId)}
          onPointerOut={() => matchFrame.hoverTacticalObject(null)}
        >
          <meshBasicMaterial color={color} transparent opacity={opacity} depthWrite={false} side={DoubleSide} />
        </mesh>
      ) : null}
      {linePoints.length > 1 ? (
        <Line
          points={linePoints}
          color={colorValue}
          lineWidth={selected ? 2 : 1}
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
      position={[xM, 0.014, -yM]}
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
      position={[event.xM, 0.16, -event.yM]}
      onClick={(pointer) => {
        pointer.stopPropagation();
        matchFrame.selectTacticalObject(objectId);
      }}
      onPointerOver={() => matchFrame.hoverTacticalObject(objectId)}
      onPointerOut={() => matchFrame.hoverTacticalObject(null)}
    >
      <octahedronGeometry args={[0.22, 0]} />
      <meshBasicMaterial color={color} />
    </mesh>
  );
}

export function TacticalLayer({
  overlay,
  events,
  matchFrame,
  palette,
  visible = true,
}: {
  readonly overlay: TacticalOverlay;
  readonly events: readonly PitchEvent[];
  readonly matchFrame: MatchFrameContextValue;
  readonly palette: TacticalLayerPalette;
  readonly visible?: boolean;
}) {
  return (
    <group name="TacticalLayer" visible={visible}>
      {overlay.hulls.map((hull) => {
        const objectId = "team-shape:" + hull.groupId;
        return (
          <TacticalPolygon
            key={objectId}
            points={hull.points}
            color={roleColor(hull.role, palette)}
            opacity={0.06}
            selected={matchFrame.selectedTacticalObjectId === objectId}
            objectId={objectId}
            matchFrame={matchFrame}
          />
        );
      })}
      {overlay.territoryCells.map((cell) => {
        const objectId = "territory:" + cell.entityId;
        return (
          <TacticalPolygon
            key={objectId}
            points={cell.points}
            color={roleColor(cell.role, palette)}
            opacity={matchFrame.selectedTacticalObjectId === objectId ? 0.16 : 0.06}
            selected={matchFrame.selectedTacticalObjectId === objectId}
            objectId={objectId}
            matchFrame={matchFrame}
          />
        );
      })}
      {overlay.influenceCells.map((cell) => {
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
      })}
      {events.map((event) => (
        <SourceEventMark key={event.eventId} event={event} matchFrame={matchFrame} color={palette.event} />
      ))}
    </group>
  );
}
