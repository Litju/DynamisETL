import { Popover } from "@base-ui/react/popover";
import { ShieldAlert, ShieldCheck } from "lucide-react";

import type { components } from "@/api/schema";

type License = components["schemas"]["LicenseView"];

/**
 * Rights at a glance: one line with the governing boundary (local-only,
 * non-commercial, attribution), and the full served notice one click away.
 * Restrictive terms are text + icon + colour; never colour alone.
 */
export function RightsChip({ license, label }: { license: License; label?: string }) {
  const restrictive = license.local_only || license.noncommercial_only;
  const boundary = license.local_only
    ? "Local-only · no redistribution"
    : license.noncommercial_only
      ? "Non-commercial"
      : license.attribution_required
        ? "Attribution required"
        : "Open";
  return (
    <Popover.Root>
      <Popover.Trigger
        aria-label={label ?? (license.local_only ? "Local-only source rights" : "Source rights")}
        className={`flex h-7 shrink-0 items-center gap-1.5 rounded-control border px-2 text-[11px] transition-colors ${
          restrictive
            ? "border-[color-mix(in_oklab,var(--d-warning)_45%,transparent)] text-text-secondary hover:bg-[color-mix(in_oklab,var(--d-warning)_8%,transparent)]"
            : "border-border-subtle text-text-muted hover:border-border-strong hover:text-text-secondary"
        }`}
      >
        {restrictive ? <ShieldAlert size={12} aria-hidden="true" className="text-warning" /> : <ShieldCheck size={12} aria-hidden="true" className="text-success" />}
        <span className="mono">{license.identifier ?? "licence unclear"}</span>
        <span className="text-text-faint">·</span>
        <span>{boundary}</span>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Positioner sideOffset={6} align="end" className="z-50">
          <Popover.Popup className="d-overlay d-pop w-[26rem] p-4 text-[12px] outline-none">
            <Popover.Title className="t-kicker mb-2">Rights · {license.identifier ?? "unclear"}</Popover.Title>
            <Popover.Description className="leading-relaxed text-text-secondary">{license.notice}</Popover.Description>
            <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1.5 text-[11px]">
              <dt className="text-text-muted">Redistribution</dt><dd className="text-text-primary">{license.redistribution}</dd>
              <dt className="text-text-muted">Attribution</dt><dd className="text-text-primary">{license.attribution_required ? "required" : "not required"}</dd>
              <dt className="text-text-muted">Commercial use</dt><dd className="text-text-primary">{license.noncommercial_only ? "not permitted" : "permitted"}</dd>
              <dt className="text-text-muted">Local-only</dt><dd className="text-text-primary">{license.local_only ? "yes — keep acquired data local" : "no"}</dd>
            </dl>
          </Popover.Popup>
        </Popover.Positioner>
      </Popover.Portal>
    </Popover.Root>
  );
}
