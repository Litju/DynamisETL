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

import type { Application, Container, Graphics, Text } from "pixi.js";

import {
  DEFAULT_PITCH_LAYERS,
  type PitchEvent,
  type PitchLayers,
  type TacticalOverlay,
  type TacticalRole,
} from "@/components/matchlab/render-types";
import type { PitchPalette, PitchRendererHandle } from "@/components/pitch/pitch-renderer-types";
import { pitchToScreen, screenToPitch, teamRole } from "@/components/pitch/pitch-model";
import { DEFAULT_PITCH, type TrailPoint, type Viewport } from "@/components/pitch/pitch-model";
import { TRACKING_KIND, type TrackingWindowBuffers } from "@/components/matchlab/frame-buffers";

export {
  DEFAULT_PITCH_LAYERS,
  EMPTY_TACTICAL_OVERLAY,
  type PitchEvent,
  type PitchLayers,
  type TacticalHull,
  type TacticalInfluenceCell,
  type TacticalOverlay,
  type TacticalRole,
  type TacticalTerritoryCell,
} from "@/components/matchlab/render-types";
export type { PitchPalette, PitchRendererHandle } from "@/components/pitch/pitch-renderer-types";

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
  label: 0xc8d0da,
  event: 0xd8b25a,
  halo: 0x111418,
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
  onSelect: (objectId: string, objectType: string) => void,
): Promise<PitchRendererHandle> {
  const pixi = await import("pixi.js");
  const app: Application = new pixi.Application();
  await app.init({
    // The surface is sized explicitly in `syncToHost`, which also refits the
    // viewport; `resizeTo` would move the canvas without the viewport and the
    // pitch would drift out of step with the entities drawn over it.
    width: Math.max(1, host.clientWidth),
    height: Math.max(1, host.clientHeight),
    backgroundAlpha: 0,
    antialias: true,
    autoDensity: true,
    resolution: typeof window !== "undefined" ? window.devicePixelRatio : 1,
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
    label: toPixiColor(palette.label, FALLBACK_HEX.label!),
    event: toPixiColor(palette.event, FALLBACK_HEX.event!),
    halo: toPixiColor(palette.halo, FALLBACK_HEX.halo!),
  };

  // Two coordinate spaces, deliberately separated.
  //
  // `world` carries the metres -> pixels transform and holds pitch geometry
  // drawn in metres, so the lines stay true to the surveyed pitch at any zoom.
  // `overlay` is untransformed and holds entities and trails, which are placed
  // through `pitchToScreen` and therefore keep a constant on-screen size: an
  // analyst reads a player marker, not a marker that grows with the zoom.
  //
  // Drawing entities in pixel coordinates *inside* the scaled world would apply
  // the transform twice and put every entity far outside the viewport.
  const world: Container = new pixi.Container();
  const overlay: Container = new pixi.Container();
  app.stage.addChild(world, overlay);
  // Draw order is the analytical hierarchy: tactical surfaces are the lowest
  // context (model influence < territory < hull outline), then trails, source
  // events, entities and labels. A tactical overlay can therefore never cover a
  // player, the ball or the selection a reader is tracking.
  const trailLayer: Graphics = new pixi.Graphics();
  const eventLayer: Graphics = new pixi.Graphics();
  const tacticalLayer: Graphics = new pixi.Graphics();
  const entityLayer: Graphics = new pixi.Graphics();
  const labelLayer: Container = new pixi.Container();
  trailLayer.eventMode = "none";
  eventLayer.eventMode = "none";
  entityLayer.eventMode = "none";
  labelLayer.eventMode = "none";
  overlay.eventMode = "none";
  tacticalLayer.eventMode = "none";
  overlay.addChild(tacticalLayer, trailLayer, eventLayer, entityLayer, labelLayer);

  const viewport: { current: Viewport } = {
    current: fitViewport(host.clientWidth, host.clientHeight),
  };

  const staticPitch: Graphics = new pixi.Graphics();
  staticPitch.eventMode = "none";
  world.addChildAt(staticPitch, 0);
  drawPitch(staticPitch, colors.pitchLine, colors.surface);
  applyViewport(world, viewport.current);

  let lastTrackingBuffers: TrackingWindowBuffers | null = null;
  let lastFrameIndex = -1;
  let lastTeamOrder: readonly string[] = [];
  let lastSelected: string | null = null;
  let lastTrail: readonly TrailPoint[] = [];
  let lastEvents: readonly PitchEvent[] = [];
  let lastTactical: TacticalOverlay = { hulls: [], territoryCells: [], influenceCells: [] };
  let layers: PitchLayers = DEFAULT_PITCH_LAYERS;
  let entityLabels: ReadonlyMap<string, string> = new Map();

  // Label text objects are pooled: a match frame relabels the same 23 objects
  // every step rather than allocating new ones at playback frequency.
  const labelPool: Text[] = [];

  function labelAt(index: number): Text {
    const existing = labelPool[index];
    if (existing) return existing;
    const created = new pixi.Text({
      text: "",
      style: {
        fill: colors.label,
        fontSize: 10,
        fontFamily: "monospace",
      },
    });
    created.eventMode = "none";
    created.resolution = 2;
    labelPool.push(created);
    labelLayer.addChild(created);
    return created;
  }

  function drawEntityRow(row: number, pass: "base" | "ball" | "selected" = "base") {
    const buffers = lastTrackingBuffers;
    if (!buffers) return;
    const objectId = buffers.entityIds[buffers.entityIndexes[row]!] ?? "";
    const kind = buffers.objectKinds[row] ?? TRACKING_KIND.other;
    const isBall = kind === TRACKING_KIND.ball;
    const selected = objectId === lastSelected;
    if (
      (pass === "base" && (selected || isBall)) ||
      (pass === "ball" && (!isBall || selected)) ||
      (pass === "selected" && !selected)
    ) return;
    const xM = buffers.positionsXY[row * 2] ?? Number.NaN;
    const yM = buffers.positionsXY[row * 2 + 1] ?? Number.NaN;
    if (!Number.isFinite(xM) || !Number.isFinite(yM)) return;
    const groupIndex = buffers.teamIndexes[row] ?? -1;
    const groupId = groupIndex < 0 ? null : (buffers.teamIds[groupIndex] ?? null);
    const role =
      kind === TRACKING_KIND.ball
        ? "ball"
        : kind === TRACKING_KIND.official
          ? "official"
          : groupId === null
            ? "other"
            : teamRole(groupId, lastTeamOrder);
    const color =
      role === "home"
        ? colors.home
        : role === "away"
          ? colors.away
          : role === "ball"
            ? colors.ball
            : role === "official"
              ? colors.official
              : colors.extrapolated;
    const point = pitchToScreen(xM, yM, viewport.current, DEFAULT_PITCH);
    const radius = isBall ? 4 : 6;
    if (isBall) {
      entityLayer.circle(point.x, point.y, radius + 2).fill({ color: colors.halo, alpha: 0.85 });
    }
    if (buffers.detectionState[row] !== 0) {
      entityLayer.circle(point.x, point.y, radius).fill({ color });
    } else {
      entityLayer.circle(point.x, point.y, radius).stroke({ width: 1.5, color });
    }
    if (selected) {
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

  function drawEntities() {
    entityLayer.clear();
    const buffers = lastTrackingBuffers;
    if (!buffers || lastFrameIndex < 0) return;
    const start = buffers.frameOffsets[lastFrameIndex]!;
    const end = buffers.frameOffsets[lastFrameIndex + 1]!;
    // Draw field players first, then the ball, then the selected identity.
    for (let row = start; row < end; row += 1) drawEntityRow(row, "base");
    for (let row = start; row < end; row += 1) {
      if ((buffers.objectKinds[row] ?? TRACKING_KIND.other) === TRACKING_KIND.ball) drawEntityRow(row, "ball");
    }
    if (lastSelected !== null) {
      for (let row = start; row < end; row += 1) {
        if (
          (buffers.objectKinds[row] ?? TRACKING_KIND.other) !== TRACKING_KIND.ball &&
          buffers.entityIds[buffers.entityIndexes[row]!] === lastSelected
        ) drawEntityRow(row, "selected");
      }
    }
  }

  /**
   * Entity labels with a simple, stable collision rule.
   *
   * A label is placed only when its box clears every label already placed this
   * frame, and the selected entity and the ball are considered first so the
   * marks a reader is tracking never lose their label to a neighbour. Labels
   * appear only once the zoom makes them legible, because 23 overlapping ids
   * are less readable than none.
   */
  function drawLabels() {
    for (const label of labelPool) label.visible = false;
    if (!layers.labels) return;
    const buffers = lastTrackingBuffers;
    if (!buffers || lastFrameIndex < 0) return;
    const legible = viewport.current.scale >= 6;
    const placed: Array<{ x: number; y: number; width: number; height: number }> = [];
    let slot = 0;
    const placeLabel = (row: number, isFocus: boolean) => {
      const objectId = buffers.entityIds[buffers.entityIndexes[row]!] ?? "";
      if (!legible && !isFocus) return;
      const xM = buffers.positionsXY[row * 2] ?? Number.NaN;
      const yM = buffers.positionsXY[row * 2 + 1] ?? Number.NaN;
      if (!Number.isFinite(xM) || !Number.isFinite(yM)) return;
      const point = pitchToScreen(xM, yM, viewport.current, DEFAULT_PITCH);
      const label = labelAt(slot);
      label.text = entityLabels.get(objectId) ?? shortEntityLabel(objectId);
      label.style.fill = isFocus ? colors.selection : colors.label;
      const box = {
        x: point.x + 8,
        y: point.y - 14,
        width: label.width,
        height: label.height,
      };
      const collides = placed.some(
        (other) =>
          box.x < other.x + other.width &&
          box.x + box.width > other.x &&
          box.y < other.y + other.height &&
          box.y + box.height > other.y,
      );
      if (collides && !isFocus) return;
      label.position.set(box.x, box.y);
      label.visible = true;
      placed.push(box);
      slot += 1;
    };

    const start = buffers.frameOffsets[lastFrameIndex]!;
    const end = buffers.frameOffsets[lastFrameIndex + 1]!;
    if (lastSelected !== null) {
      for (let row = start; row < end; row += 1) {
        if (buffers.entityIds[buffers.entityIndexes[row]!] === lastSelected) {
          placeLabel(row, true);
          break;
        }
      }
    }
    for (let row = start; row < end; row += 1) {
      if ((buffers.objectKinds[row] ?? TRACKING_KIND.other) === TRACKING_KIND.ball) {
        if (buffers.entityIds[buffers.entityIndexes[row]!] !== lastSelected) placeLabel(row, false);
        break;
      }
    }
    for (let row = start; row < end; row += 1) {
      const objectId = buffers.entityIds[buffers.entityIndexes[row]!] ?? "";
      if (objectId === lastSelected || (buffers.objectKinds[row] ?? TRACKING_KIND.other) === TRACKING_KIND.ball) {
        continue;
      }
      placeLabel(row, false);
    }
  }

  /**
   * Event marks: a small diamond at the recorded pitch location, subordinate to
   * the entities. Events are context for the frame, not the frame itself, so
   * they never carry a fill that competes with a current position.
   */
  function drawEvents() {
    eventLayer.clear();
    if (!layers.events) return;
    for (const event of lastEvents) {
      if (!Number.isFinite(event.xM) || !Number.isFinite(event.yM)) continue;
      const point = pitchToScreen(event.xM, event.yM, viewport.current, DEFAULT_PITCH);
      const size = 3.5;
      eventLayer
        .moveTo(point.x, point.y - size)
        .lineTo(point.x + size, point.y)
        .lineTo(point.x, point.y + size)
        .lineTo(point.x - size, point.y)
        .closePath()
        .stroke({ width: 1, color: colors.event, alpha: 0.8 });
    }
  }

  /**
   * Tactical overlays in a stable visual language.
   *
   * Deterministic geometry (hull, territory) is drawn as polygons: thin solid
   * outlines with a faint fill. The MODEL_ESTIMATED influence surface is drawn
   * as inset tiles, a visibly different texture, so a reader never mistakes the
   * arrival-time model for measured territory. Colour always follows the team
   * role of the entity markers.
   */
  function drawTactical() {
    tacticalLayer.clear();
    const roleColor = (role: TacticalRole) =>
      role === "home" ? colors.home : role === "away" ? colors.away : colors.extrapolated;
    if (layers.influence) {
      for (const cell of lastTactical.influenceCells) {
        const point = pitchToScreen(cell.xM, cell.yM, viewport.current);
        const alpha = Math.max(0.05, Math.min(0.2, 0.2 - cell.arrivalTimeS * 0.015));
        const width = cell.widthM * viewport.current.scale * 0.72;
        const height = cell.heightM * viewport.current.scale * 0.72;
        tacticalLayer
          .rect(point.x - width / 2, point.y - height / 2, width, height)
          .fill({ color: roleColor(cell.role), alpha });
      }
    }
    if (layers.territory) {
      for (const cell of lastTactical.territoryCells) {
        if (cell.points.length < 3) continue;
        const first = pitchToScreen(cell.points[0]![0], cell.points[0]![1], viewport.current);
        tacticalLayer.moveTo(first.x, first.y);
        for (const point of cell.points.slice(1)) {
          const screen = pitchToScreen(point[0], point[1], viewport.current);
          tacticalLayer.lineTo(screen.x, screen.y);
        }
        tacticalLayer.closePath().fill({ color: roleColor(cell.role), alpha: 0.06 }).stroke({
          width: 0.6,
          color: roleColor(cell.role),
          alpha: 0.35,
        });
      }
    }
    if (layers.geometry) {
      for (const hull of lastTactical.hulls) {
        if (hull.points.length < 2) continue;
        const first = pitchToScreen(hull.points[0]![0], hull.points[0]![1], viewport.current);
        tacticalLayer.moveTo(first.x, first.y);
        for (const point of hull.points.slice(1)) {
          const screen = pitchToScreen(point[0], point[1], viewport.current);
          tacticalLayer.lineTo(screen.x, screen.y);
        }
        tacticalLayer.closePath().stroke({ width: 1.25, color: roleColor(hull.role), alpha: 0.75 });
      }
    }
  }

  function drawTrail() {
    trailLayer.clear();
    if (!layers.trails || lastTrail.length < 2) return;
    const buffers = lastTrackingBuffers;
    const entityIndex = buffers?.entityIds.indexOf(lastTrail[0]!.objectId) ?? -1;
    let role: "home" | "away" | "other" = "other";
    if (buffers && entityIndex >= 0) {
      for (let row = 0; row < buffers.entityIndexes.length; row += 1) {
        if (buffers.entityIndexes[row] !== entityIndex) continue;
        const groupIndex = buffers.teamIndexes[row] ?? -1;
        const groupId = groupIndex < 0 ? null : (buffers.teamIds[groupIndex] ?? null);
        if (groupId !== null) role = teamRole(groupId, lastTeamOrder);
        break;
      }
    }
    const color =
      role === "home" ? colors.home : role === "away" ? colors.away : colors.trail;
    const first = pitchToScreen(lastTrail[0]!.xM, lastTrail[0]!.yM, viewport.current);
    trailLayer.moveTo(first.x, first.y);
    for (const point of lastTrail.slice(1)) {
      const screen = pitchToScreen(point.xM, point.yM, viewport.current);
      trailLayer.lineTo(screen.x, screen.y);
    }
    trailLayer.stroke({ width: 1.5, color, alpha: 0.75 });
  }

  // Direct selection: nearest entity within 1.5 m of the pointer position.
  const handleSelectPointerDown = (event: PointerEvent) => {
    const rect = host.getBoundingClientRect();
    const pitch = screenToPitch(
      event.clientX - rect.left,
      event.clientY - rect.top,
      viewport.current,
    );
    const buffers = lastTrackingBuffers;
    if (!buffers || lastFrameIndex < 0) return;
    let best: { id: string; objectType: string; distance: number } | null = null;
    const start = buffers.frameOffsets[lastFrameIndex]!;
    const end = buffers.frameOffsets[lastFrameIndex + 1]!;
    for (let row = start; row < end; row += 1) {
      const xM = buffers.positionsXY[row * 2] ?? Number.NaN;
      const yM = buffers.positionsXY[row * 2 + 1] ?? Number.NaN;
      const distance = Math.hypot(xM - pitch.xM, yM - pitch.yM);
      if (distance <= 1.5 && (best === null || distance < best.distance)) {
        const entityIndex = buffers.entityIndexes[row]!;
        const kind = buffers.objectKinds[row] ?? TRACKING_KIND.other;
        best = {
          id: buffers.entityIds[entityIndex] ?? "",
          objectType:
            kind === TRACKING_KIND.player
              ? "player"
              : kind === TRACKING_KIND.goalkeeper
                ? "goalkeeper"
                : kind === TRACKING_KIND.ball
                  ? "ball"
                  : kind === TRACKING_KIND.official
                    ? "official"
                    : "other",
          distance,
        };
      }
    }
    if (best) onSelect(best.id, best.objectType);
  };

  // Zoom and pan are renderer-local interaction state; React never re-renders.
  // Once the reader adjusts the viewport it becomes theirs, and a later resize
  // keeps it instead of snapping back to the fitted pitch.
  let readerAdjusted = false;

  let dragging: { x: number; y: number } | null = null;
  const handleWheel = (event: WheelEvent) => {
    event.preventDefault();
    const factor = Math.exp(-event.deltaY * 0.0012);
    const next = Math.min(40, Math.max(1.5, viewport.current.scale * factor));
    viewport.current = { ...viewport.current, scale: next };
    readerAdjusted = true;
    redraw();
  };
  const handleDragStart = (event: PointerEvent) => {
    dragging = { x: event.clientX, y: event.clientY };
  };
  const handlePointerMove = (event: PointerEvent) => {
    if (dragging === null || event.buttons === 0) return;
    const dx = event.clientX - dragging.x;
    const dy = event.clientY - dragging.y;
    dragging = { x: event.clientX, y: event.clientY };
    viewport.current = {
      ...viewport.current,
      offsetX: viewport.current.offsetX + dx,
      offsetY: viewport.current.offsetY + dy,
    };
    readerAdjusted = true;
    redraw();
  };
  const handlePointerUp = () => {
    dragging = null;
  };
  host.addEventListener("pointerdown", handleSelectPointerDown);
  host.addEventListener("wheel", handleWheel, { passive: false });
  host.addEventListener("pointerdown", handleDragStart);
  host.addEventListener("pointermove", handlePointerMove);
  host.addEventListener("pointerup", handlePointerUp);

  /** Reapply the viewport and repaint every layer that depends on it. */
  function redraw() {
    applyViewport(world, viewport.current);
    drawTrail();
    drawTactical();
    drawEvents();
    drawEntities();
    drawLabels();
  }

  /**
   * Keep the drawing surface and the viewport in step with the host.
   *
   * The renderer is created before the workbench pane has its final size, so
   * the first fit is computed against a provisional box. `fitViewport` keeps an
   * existing scale on purpose — a reader's zoom must survive a resize — which
   * means the provisional scale would otherwise be frozen for the session, and
   * the pitch would stay mis-sized against the entities placed from the host's
   * real dimensions. Until the reader adjusts the viewport, a resize refits.
   */
  function syncToHost() {
    const width = host.clientWidth;
    const height = host.clientHeight;
    if (width <= 0 || height <= 0) return;
    app.renderer.resize(width, height);
    viewport.current = readerAdjusted
      ? fitViewport(width, height, viewport.current)
      : fitViewport(width, height);
    redraw();
  }

  const resizeObserver = new ResizeObserver(() => {
    syncToHost();
  });
  resizeObserver.observe(host);

  return {
    setFrame(buffers, frameIndex, selectedId, teamOrder) {
      lastTrackingBuffers = buffers;
      lastFrameIndex = frameIndex;
      lastTeamOrder = teamOrder;
      lastSelected = selectedId;
      drawEntities();
      drawLabels();
    },
    setTrail(trail, selectedId) {
      lastTrail = trail;
      lastSelected = selectedId;
      drawTrail();
      drawEntities();
      drawLabels();
    },
    setEntityLabels(next) {
      entityLabels = next;
      drawLabels();
    },
    setEvents(events) {
      lastEvents = events;
      drawEvents();
    },
    setTacticalOverlay(next) {
      lastTactical = next;
      drawTactical();
    },
    setLayers(next) {
      layers = next;
      redraw();
    },
    resetView() {
      // Dropping the previous scale makes `fitViewport` frame the pitch again,
      // and hands the viewport back to the automatic fit.
      readerAdjusted = false;
      syncToHost();
    },
    destroy() {
      resizeObserver.disconnect();
      host.removeEventListener("pointerdown", handleSelectPointerDown);
      host.removeEventListener("wheel", handleWheel);
      host.removeEventListener("pointerdown", handleDragStart);
      host.removeEventListener("pointermove", handlePointerMove);
      host.removeEventListener("pointerup", handlePointerUp);
      app.destroy(true, { children: true });
    },
  };
}

/**
 * Compact on-pitch identity for a tracked object.
 *
 * Providers publish opaque object ids: a DFL object is `DFL-OBJ-0037YC`, and
 * twenty-two of those at full length bury the pitch they sit on. The trailing
 * segment is the part that distinguishes one object from another, so it is
 * what the mark carries; the exact id stays in the selection read-out and the
 * inspector.
 */
export function shortEntityLabel(objectId: string): string {
  const segments = objectId.split("-").filter(Boolean);
  return segments.length > 1 ? (segments.at(-1) ?? objectId) : objectId;
}

/** Pixel margin kept around the pitch so touchline play stays visible. */
const PITCH_MARGIN_M = 4;

export function fitViewport(
  widthPx: number,
  heightPx: number,
  previous?: Viewport,
): Viewport {
  const lengthM = DEFAULT_PITCH.lengthM + PITCH_MARGIN_M * 2;
  const widthM = DEFAULT_PITCH.widthM + PITCH_MARGIN_M * 2;
  const fitted = Math.min(widthPx / lengthM, heightPx / widthM);
  const scale = previous?.scale ?? fitted;
  return {
    scale: Number.isFinite(scale) && scale > 0 ? scale : 5,
    offsetX: widthPx / 2,
    offsetY: heightPx / 2,
  };
}

function applyViewport(world: Container, viewport: Viewport) {
  // The pitch Y axis points up the screen, matching `pitchToScreen`.
  world.scale.set(viewport.scale, -viewport.scale);
  world.position.set(viewport.offsetX, viewport.offsetY);
}

/**
 * Stroke one arc as its own path.
 *
 * Pixi keeps a current point across path commands, so an `arc` issued after
 * another shape draws a connector line from wherever the previous shape ended
 * to the arc's start. Moving to the arc's first point makes each marking an
 * independent stroke instead of leaving stray lines across the pitch.
 */
function strokeArc(
  graphics: Graphics,
  centreX: number,
  centreY: number,
  radius: number,
  startAngle: number,
  endAngle: number,
  width: number,
  color: number,
  alpha: number,
): void {
  graphics
    .moveTo(centreX + radius * Math.cos(startAngle), centreY + radius * Math.sin(startAngle))
    .arc(centreX, centreY, radius, startAngle, endAngle)
    .stroke({ width, color, alpha });
}

/**
 * Surveyed pitch geometry, drawn in metres.
 *
 * Dimensions follow the IFAB-recommended full-size pitch the canonical frames
 * declare: 105 x 68 m, 16.5 m penalty area, 5.5 m goal area, 9.15 m centre
 * circle and penalty arc, 11 m penalty mark, 1 m corner arc. The markings are
 * orientation for the tracked entities, so they stay a quiet substrate: thin
 * lines, low-contrast fill, no turf texture competing with the data.
 */
function drawPitch(graphics: Graphics, line: number, surface: number) {
  const { lengthM, widthM } = DEFAULT_PITCH;
  const half = { x: lengthM / 2, y: widthM / 2 };
  const lineWidth = 0.12;
  const penaltyAreaDepth = 16.5;
  const penaltyAreaWidth = 40.32;
  const goalAreaDepth = 5.5;
  const goalAreaWidth = 18.32;
  const penaltyMark = 11;
  const circleRadius = 9.15;
  const goalDepth = 1.5;
  const goalWidth = 7.32;

  graphics
    .rect(-half.x, -half.y, lengthM, widthM)
    .fill({ color: surface, alpha: 0.35 })
    .stroke({ width: lineWidth * 1.6, color: line });

  graphics.moveTo(0, -half.y).lineTo(0, half.y).stroke({ width: lineWidth, color: line });
  graphics.circle(0, 0, circleRadius).stroke({ width: lineWidth, color: line });
  graphics.circle(0, 0, 0.3).fill({ color: line });

  for (const side of [-1, 1]) {
    const goalLine = side * half.x;
    graphics
      .rect(
        Math.min(goalLine, goalLine - side * penaltyAreaDepth),
        -penaltyAreaWidth / 2,
        penaltyAreaDepth,
        penaltyAreaWidth,
      )
      .stroke({ width: lineWidth, color: line });
    graphics
      .rect(
        Math.min(goalLine, goalLine - side * goalAreaDepth),
        -goalAreaWidth / 2,
        goalAreaDepth,
        goalAreaWidth,
      )
      .stroke({ width: lineWidth, color: line });

    const spotX = goalLine - side * penaltyMark;
    graphics.circle(spotX, 0, 0.3).fill({ color: line });

    // Penalty arc: only the part outside the penalty area is marked.
    const areaEdge = goalLine - side * penaltyAreaDepth;
    const offset = Math.abs(areaEdge - spotX);
    if (offset < circleRadius) {
      const sweep = Math.acos(offset / circleRadius);
      const centre = side > 0 ? Math.PI : 0;
      strokeArc(
        graphics,
        spotX,
        0,
        circleRadius,
        centre - sweep,
        centre + sweep,
        lineWidth,
        line,
        1,
      );
    }

    // Goals sit behind the goal line, so the frame reads as depth.
    graphics
      .rect(
        Math.min(goalLine, goalLine + side * goalDepth),
        -goalWidth / 2,
        goalDepth,
        goalWidth,
      )
      .stroke({ width: lineWidth, color: line, alpha: 0.7 });

    for (const corner of [-1, 1]) {
      const start =
        side > 0 ? (corner > 0 ? Math.PI : Math.PI / 2) : corner > 0 ? -Math.PI / 2 : 0;
      const end =
        side > 0 ? (corner > 0 ? (3 * Math.PI) / 2 : Math.PI) : corner > 0 ? 0 : Math.PI / 2;
      strokeArc(graphics, goalLine, corner * half.y, 1, start, end, lineWidth, line, 0.7);
    }
  }
}
