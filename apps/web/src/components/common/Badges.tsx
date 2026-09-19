import type { ReactNode } from "react";

import { cn } from "@/lib/cn";
import {
  MEASUREMENT_CLASSES,
  type MeasurementClass,
  type MeasurementShape,
  QUALITY_STATES,
  type QualityState,
} from "@/lib/measurement";
import type { Modality } from "@/lib/search";

const SHAPE_STYLES: Record<MeasurementShape, string> = {
  circle: "rounded-full",
  diamond: "rotate-45 rounded-[1px]",
  square: "rounded-[1px]",
  triangle: "[clip-path:polygon(50%_0,100%_100%,0_100%)]",
};

export function MeasurementShapeGlyph({
  shape,
  className,
}: {
  shape: MeasurementShape;
  className?: string;
}) {
  return (
    <span
      aria-hidden="true"
      data-shape={shape}
      className={cn("inline-block size-2 shrink-0", SHAPE_STYLES[shape], className)}
    />
  );
}

/**
 * Measurement class badge: text + shape + color, never color alone.
 */
export function MeasurementClassBadge({
  measurementClass,
  compact = false,
}: {
  measurementClass: string;
  compact?: boolean;
}) {
  const descriptor = MEASUREMENT_CLASSES[measurementClass as MeasurementClass];
  if (!descriptor) {
    return (
      <span className="mono text-[11px] text-text-muted" title="unclassified measurement class">
        {measurementClass || "unclassified"}
      </span>
    );
  }
  return (
    <span
      className="inline-flex items-center gap-1.5 whitespace-nowrap"
      title={`${descriptor.label}: ${descriptor.semantics}`}
    >
      <MeasurementShapeGlyph shape={descriptor.shape} className="size-1.5" />
      <span
        className="inline-flex items-center rounded-[3px] border px-1 py-px text-[11px] leading-4"
        style={{
          color: descriptor.token,
          borderColor: descriptor.token,
          backgroundColor: "color-mix(in oklab, " + descriptor.token + " 10%, transparent)",
        }}
      >
        {compact ? descriptor.shortLabel : descriptor.label}
      </span>
    </span>
  );
}

export function QualityBadge({ state, label }: { state: QualityState; label?: string }) {
  const descriptor = QUALITY_STATES[state];
  return (
    <span className="inline-flex items-center gap-1.5 whitespace-nowrap">
      <span aria-hidden="true" style={{ color: descriptor.token }} className="text-[11px]">
        {descriptor.glyph}
      </span>
      <span className="text-[11px]" style={{ color: descriptor.token }}>
        {label ?? descriptor.label}
      </span>
    </span>
  );
}

export function ModalityBadge({ modality }: { modality: Modality | string }) {
  const token = `var(--d-modality-${modality})`;
  return (
    <span
      className="mono inline-flex items-center gap-1 rounded-[3px] border px-1 py-px text-[11px] leading-4"
      style={{ color: token, borderColor: token }}
    >
      {modality}
    </span>
  );
}

export function EntityTag({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <span className={cn("mono rounded-[3px] bg-surface-3 px-1 py-px text-[11px]", className)}>
      {children}
    </span>
  );
}
