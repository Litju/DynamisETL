import { Dialog } from "@base-ui/react/dialog";
import { useQuery } from "@tanstack/react-query";
import { Check, Copy, Database, X } from "lucide-react";
import { useState, type ReactNode } from "react";

import type { CatalogResourceView, SourceCapabilityView } from "@/api/types";
import { ReadinessGlyph, ReadinessLadder } from "@/components/common/Readiness";
import { catalogReadModelQuery, sourceCapabilitiesQuery } from "@/lib/api/queries";
import { AppLink } from "@/components/common/AppLink";
import { contestTitle, primaryWorld, readinessOf } from "@/lib/catalog-model";

interface FileFamily {
  readonly family: string;
  readonly key: string;
  readonly sizeBytes: number | null;
  readonly revision: string | null;
  readonly state: string;
}

const FAMILY_LABEL: Record<string, string> = {
  tracking: "Tracking frames",
  dynamic_events: "Dynamic events",
  phases: "Phases of play",
  match_metadata: "Match metadata",
  pose: "Body pose",
};

export function formatBytes(bytes: number | null): string {
  if (bytes === null) return "size unknown";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 ** 2) return `${(bytes / 1024).toFixed(1)} KiB`;
  if (bytes < 1024 ** 3) return `${(bytes / 1024 ** 2).toFixed(1)} MiB`;
  return `${(bytes / 1024 ** 3).toFixed(2)} GiB`;
}

/** Files the source declares for one contest, with their live local state. */
export function fileFamilies(entry: SourceCapabilityView | null): FileFamily[] {
  if (!entry) return [];
  const declared = (entry.provider_metadata as { file_families?: Record<string, Record<string, unknown>> }).file_families ?? {};
  const families: FileFamily[] = Object.entries(declared).map(([family, file]) => ({
    family,
    key: String(file.key ?? family),
    sizeBytes: typeof file.size_bytes === "number" ? file.size_bytes : null,
    revision: typeof file.upstream_revision === "string" ? file.upstream_revision : null,
    state: entry.source_file_states[family] ?? "UNKNOWN",
  }));
  const order = ["match_metadata", "tracking", "dynamic_events", "phases"];
  const rank = (family: string) => {
    const index = order.indexOf(family);
    return index === -1 ? order.length : index;
  };
  return families.sort((a, b) => rank(a.family) - rank(b.family));
}

const STATE_TEXT: Record<string, string> = {
  REGISTERED: "Declared · not acquired",
  ACQUIRED: "Acquired · verified",
  MATERIALIZED: "Materialized",
  READY: "Ready",
  UPSTREAM_UNAVAILABLE: "Not offered upstream",
  UNKNOWN: "State unknown",
};

function stateGlyph(state: string) {
  if (state === "ACQUIRED") return "materialized" as const;
  if (state === "MATERIALIZED" || state === "READY") return "ready" as const;
  if (state === "UPSTREAM_UNAVAILABLE") return "unavailable" as const;
  return "upstream" as const;
}

/**
 * "Prepare locally" for an upstream-only contest.
 *
 * Shows exactly what would be prepared (source, pinned revision, rights,
 * bytes, artifact families) and the deterministic, rights-gated commands that
 * perform it. The serving API is read-only by contract, so the browser never
 * starts an acquisition; while this dialog is open it re-reads *metadata only*
 * so acquisition, verification and materialization appear as they happen.
 * Browsing continues underneath — the dialog is non-blocking.
 */
export function PrepareDialog({
  resource,
  trigger,
  open: controlledOpen,
  onOpenChange,
}: {
  resource: CatalogResourceView;
  trigger: ReactNode;
  /** Controlled open state, so the dialog survives its row becoming ready. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}) {
  const [localOpen, setLocalOpen] = useState(false);
  const open = controlledOpen ?? localOpen;
  const setOpen = onOpenChange ?? setLocalOpen;
  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger
        render={<button type="button" />}
        className="d-btn"
        aria-label={`Prepare ${contestTitle(resource)} locally`}
      >
        {trigger}
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Backdrop className="d-backdrop fixed inset-0 z-40" />
        <Dialog.Viewport className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto px-4 py-[8vh]">
          <Dialog.Popup className="d-overlay d-pop w-[40rem] max-w-full outline-none">
            {open ? <PreparePlan resource={resource} onDone={() => setOpen(false)} /> : null}
          </Dialog.Popup>
        </Dialog.Viewport>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function PreparePlan({ resource, onDone }: { resource: CatalogResourceView; onDone: () => void }) {
  const datasetId = resource.dataset_ids?.[0] ?? "";
  // Live metadata only: per-file source state and the routed readiness.
  const sources = useQuery({ ...sourceCapabilitiesQuery(datasetId), refetchInterval: 4000, enabled: Boolean(datasetId) });
  const readModel = useQuery({ ...catalogReadModelQuery(), refetchInterval: 4000 });
  const live = readModel.data?.resources?.find((item) => item.resource_id === resource.resource_id) ?? resource;
  const readiness = readinessOf(live);
  const entry = sources.data?.find((candidate) => (resource.source_entry_ids ?? []).includes(candidate.entry_id)) ?? null;
  const files = fileFamilies(entry);
  const acquirable = files.filter((file) => file.state !== "UPSTREAM_UNAVAILABLE");
  const total = acquirable.reduce((sum, file) => sum + (file.sizeBytes ?? 0), 0);
  const unknownSize = acquirable.some((file) => file.sizeBytes === null);
  const revision = acquirable.find((file) => file.revision)?.revision ?? null;
  const providerId = resource.external_ids?.[0] ?? resource.session_id ?? "";
  const acquired = acquirable.length > 0 && acquirable.every((file) => file.state === "ACQUIRED" || file.state === "MATERIALIZED" || file.state === "READY");
  const materializing = acquirable.some((file) => file.state === "MATERIALIZED" || file.state === "READY");
  const world = readiness.server === "ready" ? primaryWorld(live) : null;
  const versionFlag = revision ? ` --version ${revision}` : "";
  const commands = [
    { label: "Plan (downloads nothing)", command: `uv run dynamis-fetch ${datasetId}${versionFlag} --match ${providerId} --dry-run` },
    { label: "Acquire into verified Bronze", command: `uv run dynamis-fetch ${datasetId}${versionFlag} --match ${providerId}` },
    { label: "Ingest canonical Silver + register", command: `uv run dynamis-ingest ${datasetId}${versionFlag} --match ${providerId}` },
  ];
  const pose = (entry?.provider_metadata as { pose_availability?: string } | undefined)?.pose_availability;

  return (
    <div>
      <header className="flex items-start justify-between gap-4 border-b border-border-subtle px-6 pb-4 pt-5">
        <div className="min-w-0">
          <div className="t-kicker flex items-center gap-2"><Database size={11} aria-hidden="true" /> Prepare locally</div>
          <Dialog.Title className="mt-2 truncate text-[17px] font-semibold tracking-[-0.02em] text-text-primary">
            {contestTitle(resource)}
          </Dialog.Title>
          <Dialog.Description className="mt-1 text-[12px] text-text-muted">
            {[resource.sport_name, resource.competition_name, resource.edition_label].filter(Boolean).join(" · ")}
          </Dialog.Description>
        </div>
        <Dialog.Close aria-label="Close" className="flex size-7 shrink-0 items-center justify-center rounded-control text-text-muted hover:bg-hover hover:text-text-primary">
          <X size={14} aria-hidden="true" />
        </Dialog.Close>
      </header>

      <div className="space-y-5 px-6 py-5">
        <div className="grid grid-cols-3 gap-4 text-[11.5px]">
          <Fact label="Source">{(resource.providers ?? []).join(", ") || "—"}</Fact>
          <Fact label="Rights">
            {(resource.rights_identifiers ?? []).join(", ") || "unclear"}
            {resource.local_only ? " · local-only" : resource.noncommercial_only ? " · non-commercial" : " · attribution"}
          </Fact>
          <Fact label="Estimated size">
            <span className="mono text-text-primary">{entry ? `${formatBytes(total)}${unknownSize ? " +" : ""}` : "…"}</span>
          </Fact>
        </div>

        <div>
          <div className="mb-2 flex items-center justify-between">
            <span className="t-kicker">Artifact families</span>
            <span className="mono text-[10.5px] text-text-faint" title="Pinned upstream revision">{revision ? `rev ${revision.slice(0, 10)}` : ""}</span>
          </div>
          <ul className="divide-y divide-border-subtle rounded-[8px] border border-border-subtle" aria-live="polite">
            {sources.isPending ? <li className="px-3 py-3"><div className="d-skeleton h-4" /></li> : null}
            {files.map((file) => (
              <li key={file.family} className="grid grid-cols-[minmax(0,1fr)_6rem_10rem] items-center gap-3 px-3 py-2 text-[11.5px]">
                <span className="min-w-0">
                  <span className="block text-text-primary">{FAMILY_LABEL[file.family] ?? file.family}</span>
                  <span className="mono block truncate text-[10px] text-text-faint">{file.key}</span>
                </span>
                <span className="mono text-right text-text-secondary">{formatBytes(file.sizeBytes)}</span>
                <span className="flex items-center gap-1.5 text-text-muted">
                  <ReadinessGlyph kind={stateGlyph(file.state)} />
                  {STATE_TEXT[file.state] ?? file.state.toLowerCase()}
                </span>
              </li>
            ))}
            {pose === "UPSTREAM_UNAVAILABLE" ? (
              <li className="grid grid-cols-[minmax(0,1fr)_6rem_10rem] items-center gap-3 px-3 py-2 text-[11.5px]">
                <span className="text-text-muted">Body pose</span>
                <span />
                <span className="flex items-center gap-1.5 text-text-muted"><ReadinessGlyph kind="unavailable" />Not offered upstream</span>
              </li>
            ) : null}
          </ul>
        </div>

        <div>
          <div className="t-kicker mb-2">Deterministic preparation</div>
          <ol className="space-y-1.5">
            {commands.map((item, index) => <CommandLine key={item.label} index={index + 1} label={item.label} command={item.command} />)}
          </ol>
          <p className="mt-2 text-[11px] leading-relaxed text-text-muted">
            The serving API is read-only by contract and never downloads data from navigation. Run these rights-gated
            commands on this workstation; this dialog watches the metadata and updates as files are acquired, verified and
            materialized. You can keep browsing.
          </p>
        </div>

        <div className="flex items-center justify-between rounded-[8px] border border-border-subtle bg-surface-1 px-4 py-3">
          <div className="flex items-center gap-3">
            <ReadinessLadder stage={readiness.server} upstream={readiness.upstream} />
            <span className="text-[12px] text-text-secondary" role="status" aria-live="polite">
              {readiness.server === "ready"
                ? "Materialized and ready server-side"
                : materializing
                  ? "Materialized · resolving capability routes"
                  : acquired
                    ? "Acquired and verified · awaiting ingest"
                    : "Upstream available · not materialized"}
            </span>
          </div>
          {world?.target ? (
            <AppLink to={world.target} transition onClick={onDone} className="d-btn d-btn-primary">
              <Check size={13} aria-hidden="true" /> {world.label}
            </AppLink>
          ) : readiness.server === "ready" ? <Check size={15} aria-hidden="true" className="text-success" /> : null}
        </div>
      </div>
    </div>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <div className="t-kicker mb-1">{label}</div>
      <div className="text-text-secondary">{children}</div>
    </div>
  );
}

function CommandLine({ index, label, command }: { index: number; label: string; command: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <li className="grid grid-cols-[1.25rem_minmax(0,1fr)_auto] items-center gap-2">
      <span className="mono text-[10.5px] text-text-faint">{index}</span>
      <span className="min-w-0 rounded-[6px] border border-border-subtle bg-surface-0 px-2.5 py-1.5">
        <span className="block text-[10.5px] text-text-muted">{label}</span>
        <code className="mono block truncate text-[11px] text-text-primary" title={command}>{command}</code>
      </span>
      <button
        type="button"
        aria-label={`Copy command: ${label}`}
        onClick={() => {
          void navigator.clipboard?.writeText(command).then(() => {
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1400);
          });
        }}
        className="flex size-7 items-center justify-center rounded-control text-text-muted hover:bg-hover hover:text-text-primary"
      >
        {copied ? <Check size={13} aria-hidden="true" className="text-success" /> : <Copy size={13} aria-hidden="true" />}
      </button>
    </li>
  );
}
