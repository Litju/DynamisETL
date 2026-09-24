import { Html, Line } from "@react-three/drei";

import type { TrailPoint } from "@/components/pitch/pitch-model";

export interface ContextSubject {
  readonly id: string;
  readonly label: string;
  readonly xM: number;
  readonly yM: number;
}

export interface SourceAlignmentDisplay {
  readonly trackingXY: readonly [number, number];
  readonly poseRootXY: readonly [number, number];
  readonly deltaXYM: readonly [number, number];
  readonly sourceModelIdentity: string;
}

export function ContextLayer({
  selected,
  hovered,
  trail = [],
  alignment = null,
  displayMode = "SOURCE NATIVE",
  visible = true,
}: {
  readonly selected: ContextSubject | null;
  readonly hovered?: ContextSubject | null;
  readonly trail?: readonly TrailPoint[];
  readonly alignment?: SourceAlignmentDisplay | null;
  readonly displayMode?: string;
  readonly visible?: boolean;
}) {
  const trailPoints = trail.map((point) => [point.xM, 0.035, -point.yM] as const);
  const alignmentPoints = alignment
    ? [
        [alignment.trackingXY[0], 0.06, -alignment.trackingXY[1]] as const,
        [alignment.poseRootXY[0], 0.06, -alignment.poseRootXY[1]] as const,
      ]
    : [];

  return (
    <group name="ContextLayer" visible={visible}>
      {trailPoints.length > 1 ? (
        <Line points={trailPoints} color="#d9e1df" lineWidth={1.25} transparent opacity={0.72} />
      ) : null}
      {selected ? (
        <group>
          <mesh position={[selected.xM, 0.04, -selected.yM]} rotation={[-Math.PI / 2, 0, 0]}>
            <ringGeometry args={[0.45, 0.58, 36]} />
            <meshBasicMaterial color="#f4f7f6" transparent opacity={0.95} />
          </mesh>
          <Html position={[selected.xM, 0.75, -selected.yM]} center distanceFactor={24}>
            <span
              role="note"
              aria-label={"Selected player " + selected.label + " " + selected.id}
              className="pointer-events-none whitespace-nowrap rounded border border-white/40 bg-black/80 px-1.5 py-0.5 text-[10px] text-white"
            >
              {selected.label} · {selected.id}
            </span>
          </Html>
        </group>
      ) : null}
      {hovered && hovered.id !== selected?.id ? (
        <mesh position={[hovered.xM, 0.035, -hovered.yM]} rotation={[-Math.PI / 2, 0, 0]}>
          <ringGeometry args={[0.4, 0.48, 28]} />
          <meshBasicMaterial color="#dce7e3" transparent opacity={0.58} />
        </mesh>
      ) : null}
      {alignment ? (
        <>
          <Line points={alignmentPoints} color="#f4f7f6" lineWidth={1.4} dashed dashSize={0.2} gapSize={0.12} />
          <Html
            position={[
              (alignment.trackingXY[0] + alignment.poseRootXY[0]) / 2,
              0.4,
              -(alignment.trackingXY[1] + alignment.poseRootXY[1]) / 2,
            ]}
            center
            distanceFactor={30}
          >
            <span role="note" className="pointer-events-none whitespace-nowrap rounded bg-black/75 px-1.5 py-0.5 text-[9px] text-white">
              ΔXY {alignment.deltaXYM[0].toFixed(2)} m, {alignment.deltaXYM[1].toFixed(2)} m · {alignment.sourceModelIdentity}
            </span>
          </Html>
        </>
      ) : null}
      <Html fullscreen pointerEvents="none">
        <div className="absolute left-2 top-2 pointer-events-none rounded bg-black/70 px-1.5 py-0.5 text-[9px] uppercase tracking-wide text-white">
          {displayMode}
        </div>
      </Html>
    </group>
  );
}
