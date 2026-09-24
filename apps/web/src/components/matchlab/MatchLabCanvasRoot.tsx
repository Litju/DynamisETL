import { View } from "@react-three/drei";
import { Canvas } from "@react-three/fiber";
import type { ReactNode } from "react";

import { useAnalysisStore } from "@/lib/state/analysis";

/** One persistent WebGL2 renderer for every MatchLab view; portals supply scissored scenes. */
export function MatchLabCanvasRoot({
  children,
  enabled = true,
}: {
  readonly children: ReactNode;
  readonly enabled?: boolean;
}) {
  const playing = useAnalysisStore((state) => state.playing);
  return (
    <div className="relative h-full min-h-0" data-testid="matchlab-canvas-root">
      {children}
      {enabled ? (
        <Canvas
          frameloop={playing ? "always" : "demand"}
          camera={{ position: [0, 0, 5], near: 0.01, far: 100 }}
          dpr={[1, 2]}
          gl={{ antialias: true, powerPreference: "high-performance" }}
          className="z-0"
          style={{ position: "absolute", inset: 0, pointerEvents: "none" }}
          data-testid="matchlab-canvas"
        >
          <View.Port />
        </Canvas>
      ) : null}
    </div>
  );
}
