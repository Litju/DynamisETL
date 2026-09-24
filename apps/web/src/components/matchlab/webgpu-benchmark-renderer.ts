import { type Renderer } from "@react-three/fiber";
import { WebGPURenderer } from "three/webgpu";

type BenchmarkRendererOptions = {
  readonly canvas: EventTarget;
  readonly antialias?: boolean | undefined;
  readonly powerPreference?: "default" | "high-performance" | "low-power" | undefined;
};

export async function createWebGpuBenchmarkRenderer(props: BenchmarkRendererOptions): Promise<Renderer> {
  const renderer = new WebGPURenderer({
    canvas: props.canvas as HTMLCanvasElement,
    antialias: props.antialias,
    powerPreference: props.powerPreference === "default" ? undefined : props.powerPreference,
  });
  await renderer.init();
  return renderer;
}
