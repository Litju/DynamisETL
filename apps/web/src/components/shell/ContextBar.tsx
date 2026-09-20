import { useQuery } from "@tanstack/react-query";
import { Link, useRouterState } from "@tanstack/react-router";
import { ChevronRight, Command, Moon, Sun } from "lucide-react";

import { CopyableId } from "@/components/common/CopyableId";
import { datasetsQuery, servingStatusQuery, sessionQuery } from "@/lib/api/queries";
import { cn } from "@/lib/cn";
import { useUiStore } from "@/lib/state/ui";

/** One readable step of the context spine. */
export interface ContextCrumb {
  readonly key: string;
  /** Human-readable label shown to the reader. */
  readonly label: string;
  /** Exact machine identity, revealed as secondary evidence. */
  readonly id?: string | undefined;
  readonly idLabel?: string | undefined;
  readonly to?: string | undefined;
}

const SURFACE_LABELS: Record<string, string> = {
  catalog: "Catalog",
  lab: "Laboratory",
  compare: "Compare",
  methods: "Methodology",
  runs: "Processing runs",
  quality: "Quality & rights",
};

/**
 * Resolve the readable context spine for the current location.
 *
 * Human-readable names lead; the exact dataset/session/trial/subject ids stay
 * available as secondary evidence. Resolved names are passed in by the caller
 * (they come from Query), so this stays a pure function over the location.
 */
export function contextCrumbs(
  pathname: string,
  search: string,
  names: {
    readonly dataset?: string | undefined;
    readonly session?: string | undefined;
    readonly trial?: string | undefined;
  } = {},
): ContextCrumb[] {
  const parts = pathname.split("/").filter(Boolean);
  const surface = parts[0];
  if (surface === undefined) return [];
  const crumbs: ContextCrumb[] = [
    { key: "surface", label: SURFACE_LABELS[surface] ?? surface, to: `/${surface}` },
  ];
  if (surface !== "lab") return crumbs;

  const datasetId = parts[1];
  const sessionId = parts[2];
  if (datasetId === undefined) return crumbs;
  crumbs.push({
    key: "dataset",
    label: names.dataset ?? datasetId,
    id: datasetId,
    idLabel: "dataset id",
  });
  if (sessionId === undefined) return crumbs;
  crumbs.push({
    key: "session",
    label: names.session ?? sessionId,
    id: sessionId,
    idLabel: "session id",
  });

  const params = new URLSearchParams(search);
  const trial = params.get("trial");
  if (trial) {
    crumbs.push({ key: "trial", label: names.trial ?? trial, id: trial, idLabel: "trial id" });
  }
  const subject = params.get("subject");
  if (subject) {
    crumbs.push({ key: "subject", label: `Subject ${subject}`, id: subject, idLabel: "subject id" });
  }
  return crumbs;
}

/** Look up readable names for the ids currently in the location. */
function useContextNames(datasetId: string | null, sessionId: string | null) {
  const datasets = useQuery({ ...datasetsQuery(), enabled: datasetId !== null });
  const session = useQuery({
    ...sessionQuery(datasetId ?? "", sessionId ?? ""),
    enabled: Boolean(datasetId && sessionId),
  });
  const dataset = datasets.data?.find((candidate) => candidate.dataset_id === datasetId);
  return {
    dataset: dataset?.name,
    session: session.data?.session.label ?? undefined,
    trials: session.data?.trials ?? [],
  };
}

export function ContextBar() {
  const location = useRouterState({ select: (state) => state.location });
  const theme = useUiStore((state) => state.theme);
  const setTheme = useUiStore((state) => state.setTheme);
  const setPaletteOpen = useUiStore((state) => state.setPaletteOpen);
  const { data: status, isError } = useQuery(servingStatusQuery());

  const parts = location.pathname.split("/").filter(Boolean);
  const datasetId = parts[0] === "lab" ? (parts[1] ?? null) : null;
  const sessionId = parts[0] === "lab" ? (parts[2] ?? null) : null;
  const names = useContextNames(datasetId, sessionId);

  const searchStr = location.searchStr ?? "";
  const trialId = new URLSearchParams(searchStr).get("trial");
  const trialLabel = names.trials.find((trial) => trial.trial_id === trialId)?.label ?? undefined;
  const crumbs = contextCrumbs(location.pathname, searchStr, {
    dataset: names.dataset,
    session: names.session,
    // Trial labels carry the provider's condition/index detail, which is long;
    // the readable trial id is the better spine label.
    trial: trialLabel ? trialId ?? undefined : undefined,
  });

  const databaseOk = Boolean(status) && !isError;
  const goldPublished = status?.gold_published === true;

  return (
    <header className="flex h-11 shrink-0 items-center gap-3 border-b border-border-subtle bg-surface-0 px-3">
      <Link
        to="/catalog"
        className="flex shrink-0 items-baseline gap-1.5 rounded-control text-[14px] font-semibold tracking-tight"
        title="DynamisData Performance Laboratory"
      >
        <span>DynamisData</span>
        <span className="hidden text-[11px] font-normal text-text-muted lg:inline">
          Performance Laboratory
        </span>
      </Link>

      <nav
        aria-label="Analysis context"
        className="flex min-w-0 flex-1 items-center gap-1 overflow-hidden"
      >
        {crumbs.map((crumb, index) => (
          <span key={crumb.key} className="flex min-w-0 items-center gap-1">
            <ChevronRight
              size={12}
              aria-hidden="true"
              className="shrink-0 text-border-strong"
            />
            <span className="flex min-w-0 flex-col justify-center leading-tight">
              {crumb.to && index === 0 ? (
                <Link
                  to={crumb.to}
                  className="truncate text-[12px] text-text-secondary hover:text-text-primary"
                >
                  {crumb.label}
                </Link>
              ) : (
                <span
                  className={cn(
                    "truncate text-[12px]",
                    index === crumbs.length - 1 ? "text-text-primary" : "text-text-secondary",
                  )}
                  title={crumb.label}
                >
                  {crumb.label}
                </span>
              )}
              {crumb.id && crumb.id !== crumb.label ? (
                <CopyableId
                  value={crumb.id}
                  label={crumb.idLabel ?? "identifier"}
                  className="-mt-0.5 max-w-48"
                />
              ) : null}
            </span>
          </span>
        ))}
      </nav>

      <button
        type="button"
        onClick={() => setPaletteOpen(true)}
        className="flex h-7 w-56 shrink-0 items-center gap-2 rounded-control border border-border-subtle bg-surface-1 px-2 text-left text-[12px] text-text-muted transition-colors duration-quick hover:border-border-strong hover:text-text-secondary"
      >
        <Command size={12} aria-hidden="true" />
        <span className="flex-1 truncate">Search or run a command</span>
        <kbd className="mono rounded-[3px] border border-border-subtle px-1 text-[10px]">⌘K</kbd>
      </button>

      <div
        className="flex shrink-0 items-center gap-1.5 text-[11px] text-text-muted"
        title={
          databaseOk
            ? `Serving database ready (${status?.db_schema}); Gold schema ${goldPublished ? "published" : "not published"}`
            : "Serving database unavailable"
        }
      >
        <span
          aria-hidden="true"
          className="size-1.5 rounded-full"
          style={{
            backgroundColor: databaseOk
              ? "var(--d-quality-valid)"
              : "var(--d-quality-unavailable)",
          }}
        />
        <span>{databaseOk ? (goldPublished ? "Gold" : "Control") : "Offline"}</span>
      </div>

      <button
        type="button"
        aria-label={theme === "dark" ? "Switch to Report Light" : "Switch to Instrument Dark"}
        title={theme === "dark" ? "Switch to Report Light" : "Switch to Instrument Dark"}
        onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
        className="flex size-7 shrink-0 items-center justify-center rounded-control text-text-muted transition-colors duration-quick hover:bg-surface-2 hover:text-text-secondary"
      >
        {theme === "dark" ? (
          <Sun size={14} aria-hidden="true" />
        ) : (
          <Moon size={14} aria-hidden="true" />
        )}
      </button>
    </header>
  );
}
