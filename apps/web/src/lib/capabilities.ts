/**
 * Analytical capability derivation.
 *
 * Which laboratories a dataset or session actually supports is read from the
 * served registry, never assumed: a surface is offered only when a real stream
 * of the matching modality exists. This is the single authority behind catalog
 * entry actions, laboratory tab availability and deterministic defaults, so the
 * product can never advertise an analysis the data cannot produce.
 */

import type { SessionDetail, StreamView } from "@/api/types";

/** Laboratory surfaces the workbench can open for a real selection. */
export type LabSurface = "signals" | "field" | "pose";

export const LAB_SURFACE_LABELS: Record<LabSurface, string> = {
  signals: "Signals",
  field: "Field",
  pose: "Pose",
};

/**
 * Modalities the signal laboratory can plot as a time series. Tracking, pose
 * and event streams are dense spatial/discrete products with their own
 * renderers; they are deliberately excluded.
 */
export const SIGNAL_MODALITIES: ReadonlySet<string> = new Set([
  "force",
  "imu",
  "gnss",
  "lpt",
]);

/** The modality that each laboratory surface consumes. */
export function surfaceForModality(modality: string): LabSurface | null {
  if (SIGNAL_MODALITIES.has(modality)) return "signals";
  if (modality === "tracking") return "field";
  if (modality === "pose") return "pose";
  return null;
}

function orderSurfaces(found: ReadonlySet<LabSurface>): LabSurface[] {
  return (["signals", "field", "pose"] as const).filter((surface) => found.has(surface));
}

/**
 * Surfaces a dataset can open, from its registered source modalities.
 *
 * `streamCount` is the gate: a dataset may declare a modality whose canonical
 * streams are not ingested, and offering a laboratory for it would advertise an
 * analysis that cannot render. Session-level capability stays authoritative for
 * anything that actually opens a renderer.
 */
export function datasetSurfaces(
  modalities: readonly string[],
  streamCount = 1,
): LabSurface[] {
  if (streamCount <= 0) return [];
  const found = new Set<LabSurface>();
  for (const modality of modalities) {
    const surface = surfaceForModality(modality);
    if (surface !== null) found.add(surface);
  }
  return orderSurfaces(found);
}

/** True when the dataset declares discrete event data backed by a stream. */
export function datasetHasEvents(modalities: readonly string[], streamCount = 1): boolean {
  return streamCount > 0 && modalities.includes("event");
}

/**
 * Surfaces a session can genuinely open: a stream of the matching modality
 * exists *and* carries at least one registered canonical artifact. A stream
 * with no artifact cannot be rendered, so it is not advertised.
 */
export function sessionSurfaces(streams: readonly StreamView[]): LabSurface[] {
  const found = new Set<LabSurface>();
  for (const stream of streams) {
    if (stream.sample_artifact_ids.length === 0) continue;
    const surface = surfaceForModality(stream.modality);
    if (surface !== null) found.add(surface);
  }
  return orderSurfaces(found);
}

/** Renderable streams of one modality family, in registry order. */
export function streamsForSurface(
  streams: readonly StreamView[],
  surface: LabSurface,
): StreamView[] {
  return streams.filter(
    (stream) =>
      stream.sample_artifact_ids.length > 0 && surfaceForModality(stream.modality) === surface,
  );
}

/** Event streams with a canonical artifact, used for field/overview overlays. */
export function eventStreams(streams: readonly StreamView[]): StreamView[] {
  return streams.filter(
    (stream) => stream.modality === "event" && stream.sample_artifact_ids.length > 0,
  );
}

export interface SessionCapabilities {
  readonly surfaces: readonly LabSurface[];
  readonly hasEvents: boolean;
  /** True when no renderer-backed stream exists at all. */
  readonly isMetadataOnly: boolean;
}

export function sessionCapabilities(session: SessionDetail): SessionCapabilities {
  const surfaces = sessionSurfaces(session.streams);
  return {
    surfaces,
    hasEvents: eventStreams(session.streams).length > 0,
    isMetadataOnly: surfaces.length === 0,
  };
}
