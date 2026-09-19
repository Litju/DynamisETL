/**
 * PixiJS pitch renderer.
 *
 * The renderer owns high-frequency drawing imperatively: React sets the scene
 * once, then frame updates clear and redraw a small vocabulary of Graphics
 * objects. Similar objects are drawn into shared Graphics containers, no masks
 * or filters are used, and non-interactive layers disable event traversal.
 *
 * Detection semantics are structural, not decorative: detected entities are
 * filled, extrapolated entities are hollow, and the selected entity carries a
 * ring plus crosshair so selection never relies on color alone.
 */

import type { Application, Container, Graphics } from "pixi.js";

import { pitchToScreen, screenToPitch, type EntityGroup } from "@/components/pitch/pitch-model";
import { DEFAULT_PITCH, type EntityFrame, type TrailPoint, type Viewport } from "@/components/pitch/pitch-model";

export interface PitchPalette {
  readonly surface: string;
  readonly pitchLine: string;
  readonly home: string;
  readonly away: string;
  readonly ball: string;
  readonly official: string;
  readonly extrapolated: string;
  readonly selection: string;
  readonly trail: string;
}

export interface PitchRendererHandle {
  setFrame(
    entities: readonly EntityFrame[],
    groups: ReadonlyMap<string, EntityGroup>,
    selectedId: string | null,
  ): void;
  setTrail(
    trail: readonly TrailPoint[],
    groups: ReadonlyMap<string, EntityGroup>,
    selectedId: string | null,
  ): void;
  destroy(): void;
}

const FALLBACK_HEX: Record<string, number> = {
  surface: 0x12161c,
  pitchLine: 0x8a939f,
  home: 0x35c1e0,
  away: 0xe0a135,
  ball: 0xe8e8e8,
  official: 0xc678dd,
  extrapolated: 0x9aa4b2,
  selection: 0x6cc7ff,
  trail: 0x7f8a99,
};

function toPixiColor(css: string, fallback: number): number {
  if (css.startsWith("#")) {
    return Number.parseInt(css.slice(1), 16);
  }
  if (typeof document === "undefined") return fallback;
  try {
    const canvas = document.createElement("canvas");
    canvas.width = 1;
    canvas.height = 1;
    const context = canvas.getContext("2d");
    if (!context) return fallback;
    context.fillStyle = "#000000";
    context.fillStyle = css;
    const parsed = context.fillStyle;
    if (typeof parsed === "string" && parsed.startsWith("#")) {
      return Number.parseInt(parsed.slice(1), 16);
    }
    const match = /rgba?\((\d+),\s*(\d+),\s*(\d+)/.exec(parsed);
    if (match) {
      const r = Number(match[1]);
      const g = Number(match[2]);
      const b = Number(match[3]);
      return (r << 16) | (g << 8) | b;
    }
  } catch {
    return fallback;
  }
  return fallback;
}

export async function createPitchRenderer(
  host: HTMLElement,
  palette: PitchPalette,
  onSelect: (objectId: string) => void,
): Promise<PitchRendererHandle> {
  const pixi = await import("pixi.js");
  const app: Application = new pixi.Application();
  await app.init({
    resizeTo: host,
    backgroundAlpha: 0,
    antialias: true,
    autoDensity: true,
  });
  host.appendChild(app.canvas);

  const colors = {
    surface: toPixiColor(palette.surface, FALLBACK_HEX.surface!),
    pitchLine: toPixiColor(palette.pitchLine, FALLBACK_HEX.pitchLine!),
    home: toPixiColor(palette.home, FALLBACK_HEX.home!),
    away: toPixiColor(palette.away, FALLBACK_HEX.away!),
    ball: toPixiColor(palette.ball, FALLBACK_HEX.ball!),
    official: toPixiColor(palette.official, FALLBACK_HEX.official!),
    extrapolated: toPixiColor(palette.extrapolated, FALLBACK_HEX.extrapolated!),
    selection: toPixiColor(palette.selection, FALLBACK_HEX.selection!),
    trail: toPixiColor(palette.trail, FALLBACK_HEX.trail!),
  };

  const world: Container = new pixi.Container();
  app.stage.addChild(world);
  const trailLayer: Graphics = new pixi.Graphics();
  const entityLayer: Graphics = new pixi.Graphics();
  trailLayer.eventMode = "none";
  entityLayer.eventMode = "none";
  world.addChild(trailLayer, entityLayer);

  const viewport: { current: Viewport } = {
    current: fitViewport(host.clientWidth, host.clientHeight),
  };

  const staticPitch: Graphics = new pixi.Graphics();
  staticPitch.eventMode = "none";
  world.addChildAt(staticPitch, 0);
  drawPitch(staticPitch, colors.pitchLine, colors.surface);
  applyViewport(world, viewport.current);

  let lastEntities: readonly EntityFrame[] = [];
  let lastGroups: ReadonlyMap<string, EntityGroup> = new Map();
  let lastSelected: string | null = null;
  let lastTrail: readonly TrailPoint[] = [];

  function drawEntities() {
    entityLayer.clear();
    for (const entity of lastEntities) {
      if (!Number.isFinite(entity.xM) || !Number.isFinite(entity.yM)) continue;
      const point = pitchToScreen(entity.xM, entity.yM, viewport.current, DEFAULT_PITCH);
      const group = lastGroups.get(entity.objectId) ?? "other";
      const color =
        group === "home"
          ? colors.home
          : group === "away"
            ? colors.away
            : group === "ball"
              ? colors.ball
              : group === "official"
                ? colors.official
                : colors.extrapolated;
      const radius = entity.isBall ? 4 : 6;
      const filled = entity.detected !== false;
      if (filled) {
        entityLayer.circle(point.x, point.y, radius).fill({ color });
      } else {
        entityLayer.circle(point.x, point.y, radius).stroke({ width: 1.5, color });
      }
      if (entity.objectId === lastSelected) {
        entityLayer
          .circle(point.x, point.y, radius + 4)
          .stroke({ width: 2, color: colors.selection });
        entityLayer
          .moveTo(point.x - radius - 8, point.y)
          .lineTo(point.x + radius + 8, point.y)
          .moveTo(point.x, point.y - radius - 8)
          .lineTo(point.x, point.y + radius + 8)
          .stroke({ width: 1, color: colors.selection });
      }
    }
  }

  function drawTrail() {
    trailLayer.clear();
    if (lastTrail.length < 2) return;
    const group = lastGroups.get(lastTrail[0]!.objectId) ?? "other";
    const color =
      group === "home" ? colors.home : group === "away" ? colors.away : colors.trail;
    const first = pitchToScreen(lastTrail[0]!.xM, lastTrail[0]!.yM, viewport.current);
    trailLayer.moveTo(first.x, first.y);
    for (const point of lastTrail.slice(1)) {
      const screen = pitchToScreen(point.xM, point.yM, viewport.current);
      trailLayer.lineTo(screen.x, screen.y);
    }
    trailLayer.stroke({ width: 1.5, color, alpha: 0.75 });
  }

  // Direct selection: nearest entity within 1.5 m of the pointer position.
  host.addEventListener("pointerdown", (event) => {
    const rect = host.getBoundingClientRect();
    const pitch = screenToPitch(
      event.clientX - rect.left,
      event.clientY - rect.top,
      viewport.current,
    );
    let best: { id: string; distance: number } | null = null;
    for (const entity of lastEntities) {
      const distance = Math.hypot(entity.xM - pitch.xM, entity.yM - pitch.yM);
      if (distance <= 1.5 && (best === null || distance < best.distance)) {
        best = { id: entity.objectId, distance };
      }
    }
    if (best) onSelect(best.id);
  });

  // Zoom and pan are renderer-local interaction state; React never re-renders.
  host.addEventListener(
    "wheel",
    (event) => {
      event.preventDefault();
      const factor = Math.exp(-event.deltaY * 0.0012);
      const next = Math.min(40, Math.max(1.5, viewport.current.scale * factor));
      viewport.current = { ...viewport.current, scale: next };
      applyViewport(world, viewport.current);
      drawEntities();
      drawTrail();
    },
    { passive: false },
  );

  let dragging: { x: number; y: number } | null = null;
  host.addEventListener("pointerdown", (event) => {
    dragging = { x: event.clientX, y: event.clientY };
  });
  host.addEventListener("pointermove", (event) => {
    if (dragging === null || event.buttons === 0) return;
    const dx = event.clientX - dragging.x;
    const dy = event.clientY - dragging.y;
    dragging = { x: event.clientX, y: event.clientY };
    viewport.current = {
      ...viewport.current,
      offsetX: viewport.current.offsetX + dx,
      offsetY: viewport.current.offsetY + dy,
    };
    applyViewport(world, viewport.current);
    drawEntities();
    drawTrail();
  });
  host.addEventListener("pointerup", () => {
    dragging = null;
  });

  const resizeObserver = new ResizeObserver(() => {
    viewport.current = fitViewport(host.clientWidth, host.clientHeight, viewport.current);
    applyViewport(world, viewport.current);
    drawEntities();
    drawTrail();
  });
  resizeObserver.observe(host);

  return {
    setFrame(entities, groups, selectedId) {
      lastEntities = entities;
      lastGroups = groups;
      lastSelected = selectedId;
      drawEntities();
    },
    setTrail(trail, groups, selectedId) {
      lastTrail = trail;
      lastGroups = groups;
      lastSelected = selectedId;
      drawTrail();
      drawEntities();
    },
    destroy() {
      resizeObserver.disconnect();
      app.destroy(true, { children: true });
    },
  };
}

export function fitViewport(
  widthPx: number,
  heightPx: number,
  previous?: Viewport,
): Viewport {
  const scale = previous?.scale ?? Math.min(widthPx / 120, heightPx / 80);
  return {
    scale: Number.isFinite(scale) && scale > 0 ? scale : 5,
    offsetX: widthPx / 2,
    offsetY: heightPx / 2,
  };
}

function applyViewport(world: Container, viewport: Viewport) {
  world.scale.set(viewport.scale);
  world.position.set(viewport.offsetX, viewport.offsetY);
}

function drawPitch(graphics: Graphics, line: number, surface: number) {
  const { lengthM, widthM } = DEFAULT_PITCH;
  const half = { x: lengthM / 2, y: widthM / 2 };
  // Geometry is drawn in metres; the world container carries the pixel scale.
  const lineWidth = 0.12;
  graphics
    .rect(-half.x, -half.y, lengthM, widthM)
    .fill({ color: surface, alpha: 0.35 })
    .stroke({ width: lineWidth * 2, color: line });
  graphics
    .moveTo(0, -half.y)
    .lineTo(0, half.y)
    .stroke({ width: lineWidth, color: line });
  graphics.circle(0, 0, 9.15).stroke({ width: lineWidth, color: line });
  for (const side of [-1, 1]) {
    graphics
      .rect(side * half.x - side * 16.5, -20.16, 16.5, 40.32)
      .stroke({ width: lineWidth, color: line });
    graphics
      .rect(side * half.x - side * 5.5, -9.16, 5.5, 18.32)
      .stroke({ width: lineWidth, color: line });
  }
}
