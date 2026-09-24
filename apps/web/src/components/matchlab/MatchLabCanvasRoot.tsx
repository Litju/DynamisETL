import { View } from "@react-three/drei";
import { Canvas, type Renderer } from "@react-three/fiber";
import { useCallback, type ReactNode } from "react";

import { useAnalysisStore } from "@/lib/state/analysis";

type BenchmarkRendererOptions = {
  readonly canvas: EventTarget;
  readonly antialias?: boolean | undefined;
  readonly powerPreference?: "default" | "high-performance" | "low-power" | undefined;
};

/** One persistent WebGL2 renderer for every MatchLab view; portals supply scissored scenes. */
export function MatchLabCanvasRoot({
  children,
  enabled = true,
}: {
  readonly children: ReactNode;
  readonly enabled?: boolean;
}) {
  const playing = useAnalysisStore((state) => state.playing);
  const benchmarkBackend = import.meta.env.DEV && typeof window !== "undefined"
    ? window.localStorage.getItem("dynamis-matchlab-renderer-benchmark")
    : null;
  const benchmarkWebGpu = benchmarkBackend === "webgpu";
  const createWebGpuRenderer = useCallback(async (props: BenchmarkRendererOptions): Promise<Renderer> => {
    const moduleUrl = new URL("/src/components/matchlab/webgpu-benchmark-renderer.ts", window.location.origin).href;
    const module = await import(/* @vite-ignore */ moduleUrl);
    return module.createWebGpuBenchmarkRenderer(props);
  }, []);
  const exposeBenchmarkRenderer = useCallback(({ gl }: { readonly gl: Renderer }) => {
    if (benchmarkBackend !== "webgl2" && benchmarkBackend !== "webgpu") return;
    Object.assign(window, { __dynamisMatchLabBenchmarkRenderer: gl });
  }, [benchmarkBackend]);
  return (
    <div className="relative h-full min-h-0" data-testid="matchlab-canvas-root">
      {children}
      {enabled ? (
        <Canvas
          frameloop={playing ? "always" : "demand"}
          camera={{ position: [0, 0, 5], near: 0.01, far: 100 }}
          dpr={[1, 2]}
          gl={benchmarkWebGpu ? createWebGpuRenderer : { antialias: true, powerPreference: "high-performance" }}
          onCreated={exposeBenchmarkRenderer}
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
