import { useEffect, useMemo } from "react";
import { BufferAttribute, BufferGeometry, Line, LineBasicMaterial, LineSegments, Vector3 } from "three";
import type { ThreeEvent } from "@react-three/fiber";

type Point3 = readonly [number, number, number];

export function Polyline({
  points,
  color,
  transparent = false,
  opacity = 1,
  dashed = false,
  dashSize = 0.2,
  gapSize = 0.12,
  onClick,
  onPointerOver,
  onPointerOut,
}: {
  readonly points: readonly Point3[];
  readonly color: string;
  readonly transparent?: boolean;
  readonly opacity?: number;
  readonly dashed?: boolean;
  readonly dashSize?: number;
  readonly gapSize?: number;
  readonly onClick?: (event: ThreeEvent<MouseEvent>) => void;
  readonly onPointerOver?: () => void;
  readonly onPointerOut?: () => void;
}) {
  const object = useMemo(() => {
    const geometry = new BufferGeometry();
    const material = new LineBasicMaterial({ color, transparent, opacity });
    if (dashed) {
      const positions: number[] = [];
      for (let index = 1; index < points.length; index += 1) {
        const start = new Vector3(...points[index - 1]!);
        const end = new Vector3(...points[index]!);
        const length = start.distanceTo(end);
        const step = Math.max(0.001, dashSize + gapSize);
        for (let offset = 0; offset < length; offset += step) {
          const dashEnd = Math.min(length, offset + dashSize);
          const first = start.clone().lerp(end, offset / length);
          const second = start.clone().lerp(end, dashEnd / length);
          positions.push(first.x, first.y, first.z, second.x, second.y, second.z);
        }
      }
      geometry.setAttribute("position", new BufferAttribute(Float32Array.from(positions), 3));
      return new LineSegments(geometry, material);
    }
    geometry.setFromPoints(points.map((point) => new Vector3(...point)));
    return new Line(geometry, material);
  }, [color, dashSize, dashed, gapSize, opacity, points, transparent]);
  useEffect(() => () => {
    object.geometry.dispose();
    object.material.dispose();
  }, [object]);
  return <primitive object={object} onClick={onClick} onPointerOver={onPointerOver} onPointerOut={onPointerOut} />;
}
