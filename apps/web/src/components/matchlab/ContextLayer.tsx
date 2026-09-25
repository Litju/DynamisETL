import { Html } from "@react-three/drei";

import { Polyline } from "@/components/matchlab/Polyline";
import { FIELD_RENDER_DEPTH_M } from "@/components/matchlab/render-layer-depths";
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
  visible = true,
}: {
  readonly selected: ContextSubject | null;
  readonly hovered?: ContextSubject | null;
  readonly trail?: readonly TrailPoint[];
  readonly alignment?: SourceAlignmentDisplay | null;
  readonly visible?: boolean;
}) {
  const trailPoints = trail.map((point) => [point.xM, FIELD_RENDER_DEPTH_M.trailPath, -point.yM] as const);
  const alignmentPoints = alignment
    ? [
        [alignment.trackingXY[0], FIELD_RENDER_DEPTH_M.alignmentLine, -alignment.trackingXY[1]] as const,
        [alignment.poseRootXY[0], FIELD_RENDER_DEPTH_M.alignmentLine, -alignment.poseRootXY[1]] as const,
      ]
    : [];

  return (
    <group name="ContextLayer" visible={visible}>
      {trailPoints.length > 1 ? (
        <Polyline points={trailPoints} color="#d9e1df" transparent opacity={0.72} />
      ) : null}
      {selected ? (
        <group>
          <mesh position={[selected.xM, FIELD_RENDER_DEPTH_M.groundRing, -selected.yM]} rotation={[-Math.PI / 2, 0, 0]}>
            <ringGeometry args={[0.45, 0.58, 36]} />
            <meshBasicMaterial color="#f4f7f6" transparent opacity={0.95} />
          </mesh>
        </group>
      ) : null}
      {hovered && hovered.id !== selected?.id ? (
        <mesh position={[hovered.xM, FIELD_RENDER_DEPTH_M.groundRing, -hovered.yM]} rotation={[-Math.PI / 2, 0, 0]}>
          <ringGeometry args={[0.4, 0.48, 28]} />
          <meshBasicMaterial color="#dce7e3" transparent opacity={0.58} />
        </mesh>
      ) : null}
      {alignment ? (
        <>
          <Polyline points={alignmentPoints} color="#f4f7f6" dashed dashSize={0.2} gapSize={0.12} />
          <Html
            position={[
              (alignment.trackingXY[0] + alignment.poseRootXY[0]) / 2,
              FIELD_RENDER_DEPTH_M.alignmentLabel,
              -(alignment.trackingXY[1] + alignment.poseRootXY[1]) / 2,
            ]}
            center
            distanceFactor={100}
          >
            <span role="note" className="pointer-events-none whitespace-nowrap rounded bg-black/75 px-1.5 py-0.5 text-[9px] text-white">
              ΔXY {alignment.deltaXYM[0].toFixed(2)} m, {alignment.deltaXYM[1].toFixed(2)} m · {alignment.sourceModelIdentity}
            </span>
          </Html>
        </>
      ) : null}
    </group>
  );
}
