import { useQuery } from "@tanstack/react-query";
import { createRoute, type AnyRoute, Link, useNavigate, useSearch } from "@tanstack/react-router";
import { ArrowRight, Search } from "lucide-react";

import type { CatalogResourceView } from "@/api/types";
import { ErrorPanel, LoadingPanel, StatePanel } from "@/components/common/StatePanel";
import { catalogReadModelQuery } from "@/lib/api/queries";
import { cn } from "@/lib/cn";
import { catalogSearchSchema, parseSearch } from "@/lib/search";
import type { CatalogSearch } from "@/lib/search";

export function defineCatalogRoute(parent: AnyRoute) {
  return createRoute({
    getParentRoute: () => parent,
    path: "/catalog",
    validateSearch: (search: Record<string, unknown>) => parseSearch(catalogSearchSchema, search),
    component: CatalogPage,
  });
}

function CatalogPage() {
  const search = useSearch({ from: "/catalog" });
  const navigate = useNavigate();
  const catalog = useQuery(catalogReadModelQuery());
  const resources = catalog.data?.resources ?? [];
  const sports: [string, string][] = [...new Map(resources
    .filter((item) => item.sport_id)
    .map((item): [string, string] => [item.sport_id!, item.sport_name ?? item.sport_id!]))];
  const providers = [...new Set(resources.flatMap((item) => item.providers ?? []))].sort();

  const update = (patch: Partial<CatalogSearch>) => {
    void navigate({
      to: "/catalog",
      search: (previous: CatalogSearch) => ({ ...previous, ...patch }),
      replace: true,
    });
  };
  const query = search.q?.toLocaleLowerCase() ?? "";
  const visible = resources.filter((item) => {
    if (search.kind && item.resource_kind !== search.kind) return false;
            if (
              search.sport === "__human__"
              && item.resource_kind !== "performance_dataset"
              && item.resource_kind !== "performance_session"
            ) return false;
    if (search.sport && search.sport !== "__human__" && item.sport_id !== search.sport) return false;
    if (search.provider && !(item.providers ?? []).includes(search.provider)) return false;
    if (search.rights === "noncommercial" && !item.noncommercial_only) return false;
    if (search.rights === "commercial" && (item.noncommercial_only || item.local_only)) return false;
    if (search.rights === "local_only" && !item.local_only) return false;
    if (query && !resourceSearchText(item).includes(query)) return false;
    return true;
  });

  return (
    <main className="flex h-full min-h-0 flex-col" aria-label="Data Library">
      <header className="shrink-0 border-b border-border-subtle bg-surface-1 px-4 py-3">
        <h1 className="t-product-title">Data Library</h1>
        <p className="mt-0.5 max-w-3xl text-[12px] text-text-secondary">
          Browse contests, competition editions and human-performance sessions. Upstream, registered,
          materialized and ready states come from metadata; browsing never acquires dense data.
        </p>
      </header>

      <section className="flex min-h-0 flex-1 flex-col" aria-label="Semantic catalog">
        <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-border-subtle bg-surface-1 px-3 py-2">
          <label className="relative flex items-center">
            <Search size={13} aria-hidden="true" className="pointer-events-none absolute left-2 text-text-muted" />
            <input
              value={search.q ?? ""}
              onChange={(event) => update({ q: event.target.value || undefined })}
              placeholder="Search contests, teams, editions"
              aria-label="Search data library"
              className="h-7 w-64 rounded-control border border-border-subtle bg-surface-0 pl-7 pr-2 text-[12px] outline-none focus:border-accent"
            />
          </label>
          <FilterSelect
            label="World"
            value={search.sport ?? ""}
            onChange={(value) => update({ sport: value || undefined })}
            options={[["", "All worlds"], ["__human__", "Human performance"], ...sports.map(([id, name]) => [id, name] as [string, string])]}
          />
          <FilterSelect
            label="Record"
            value={search.kind ?? ""}
            onChange={(value) => update({ kind: (value || undefined) as CatalogSearch["kind"] })}
            options={[
              ["", "All records"],
              ["contest", "Contests"],
              ["competition_edition", "Competition editions"],
              ["performance_dataset", "Performance datasets"],
              ["performance_session", "Performance sessions"],
            ]}
          />
          <FilterSelect
            label="Provider"
            value={search.provider ?? ""}
            onChange={(value) => update({ provider: value || undefined })}
            options={[["", "All providers"], ...providers.map((provider) => [provider, provider] as [string, string])]}
          />
          <FilterSelect
            label="Rights"
            value={search.rights ?? "all"}
            onChange={(value) => update({ rights: value as CatalogSearch["rights"] })}
            options={[
              ["all", "Any rights"],
              ["commercial", "Commercial use allowed"],
              ["noncommercial", "Non-commercial only"],
              ["local_only", "Local-only"],
            ]}
          />
          <span className="ml-auto text-[11px] tabular text-text-muted">
            {catalog.isSuccess ? `${visible.length} of ${resources.length} records` : " "}
          </span>
        </div>

        <div className="min-h-0 flex-1 overflow-auto">
          {catalog.isPending ? <LoadingPanel label="Loading semantic catalog" /> : null}
          {catalog.isError ? <ErrorPanel error={catalog.error} onRetry={() => void catalog.refetch()} /> : null}
          {catalog.isSuccess && visible.length === 0 ? (
            <StatePanel
              state="empty"
              title="No records match these filters."
              detail="Try another sport, record type, provider or search term."
            />
          ) : null}
          {catalog.isSuccess && visible.length > 0 ? <ResourceTable resources={visible} /> : null}
        </div>
      </section>
    </main>
  );
}

function resourceSearchText(item: CatalogResourceView): string {
  return [
    item.label,
    item.sport_name,
    item.competition_name,
    item.edition_label,
    ...(item.teams ?? []).flatMap((team) => [team.display_name, team.team_id]),
    ...(item.providers ?? []),
    ...(item.dataset_ids ?? []),
    ...(item.external_ids ?? []),
  ].filter(Boolean).join(" ").toLocaleLowerCase();
}

function ResourceTable({ resources }: { resources: readonly CatalogResourceView[] }) {
  return (
    <table className="w-full border-collapse text-left" aria-label="Catalog resources">
      <thead className="sticky top-0 z-10 bg-surface-1 text-[10px] uppercase tracking-wide text-text-muted">
        <tr>
          <th className="px-3 py-2 font-medium">Resource</th>
          <th className="px-2 py-2 font-medium">Upstream</th>
          <th className="px-2 py-2 font-medium">Registered</th>
          <th className="px-2 py-2 font-medium">Materialized</th>
          <th className="px-2 py-2 font-medium">Ready</th>
          <th className="px-3 py-2 font-medium">Open</th>
        </tr>
      </thead>
      <tbody>
        {resources.map((item) => (
          <tr key={`${item.resource_kind}:${item.resource_id}`} className="border-t border-border-subtle align-top hover:bg-surface-1">
            <td className="min-w-64 px-3 py-2">
              <div className="text-[12px] font-medium text-text-primary">{item.label}</div>
              <div className="mt-0.5 text-[10px] text-text-secondary">
                {resourceContext(item)}
              </div>
              <div className="mt-1 flex flex-wrap gap-x-2 text-[10px] text-text-muted">
                <span>Provider: {(item.providers ?? []).join(", ") || "—"}</span>
                <span>Source: {(item.dataset_ids ?? []).join(", ") || "—"}</span>
                <span>Rights: {(item.rights_identifiers ?? []).join(", ") || "unclear"}
                  {item.local_only ? " · local-only" : item.noncommercial_only ? " · non-commercial" : ""}
                </span>
                {item.availability_state ? <span>Source state: {item.availability_state}</span> : null}
              </div>
              {(item.materialized_capabilities ?? []).length ? (
                <div className="mt-1 text-[10px] text-text-muted">
                  Local: {(item.materialized_capabilities ?? []).join(" · ")}
                  {(item.materialized_grains ?? []).length ? ` · ${(item.materialized_grains ?? []).join(" / ")}` : ""}
                </div>
              ) : (item.upstream_capabilities ?? []).length ? (
                <div className="mt-1 text-[10px] text-text-muted">
                  Upstream: {(item.upstream_capabilities ?? []).join(" · ")}
                </div>
              ) : null}
            </td>
            <td className="px-2 py-2"><Stage value={item.stages.upstream} /></td>
            <td className="px-2 py-2"><Stage value={item.stages.registered} /></td>
            <td className="px-2 py-2"><Stage value={item.stages.materialized} /></td>
            <td className="px-2 py-2"><Stage value={item.stages.ready} /></td>
            <td className="min-w-44 px-3 py-2">
              <ResourceActions item={item} />
              {item.preparation_eligible ? (
                <div className="mt-1 text-[10px] text-text-muted">
                  Preparation eligible: {(item.preparation_actions ?? []).join(" / ")}
                </div>
              ) : null}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function resourceContext(item: CatalogResourceView): string {
  if (item.resource_kind === "performance_dataset") return "Human performance · dataset";
  if (item.resource_kind === "performance_session") return "Human performance · session";
  return [item.sport_name, item.competition_name, item.edition_label, item.resource_kind.replaceAll("_", " ")]
    .filter(Boolean).join(" · ");
}

function ResourceActions({ item }: { item: CatalogResourceView }) {
  const routes = item.routes ?? [];
  const ready = (product: string) => routes.some((route) => route.product === product && route.ready);
  const linkClass = "mb-1 inline-flex items-center gap-1 rounded-control border border-border-subtle px-2 py-1 text-[11px] text-text-secondary hover:border-border-strong hover:bg-surface-2";
  const datasetId = item.dataset_ids?.[0];
  const links = [];

  if (ready("MatchLab") && item.session_id && datasetId) {
    links.push(
      <Link key="matchlab" to="/lab/$datasetId/$sessionId" params={{ datasetId, sessionId: item.session_id }} search={{ view: "matchlab" }} className={linkClass}>
        MatchLab <ArrowRight size={11} aria-hidden="true" />
      </Link>,
    );
  }
  if (ready("GameLab") && item.edition_id) {
    links.push(
      <Link key="gamelab" to="/games" search={{ edition: item.edition_id, ...(item.contest_id ? { game: item.contest_id } : {}) }} className={linkClass}>
        GameLab <ArrowRight size={11} aria-hidden="true" />
      </Link>,
    );
  }
  if (ready("SeasonLab") && item.edition_id) {
    links.push(
      <Link key="seasonlab" to="/season" search={{ edition: item.edition_id }} className={linkClass}>
        SeasonLab <ArrowRight size={11} aria-hidden="true" />
      </Link>,
    );
  }
  if (ready("PerformanceLab") && item.session_id && datasetId) {
    links.push(
      <Link key="performance" to="/lab/$datasetId/$sessionId" params={{ datasetId, sessionId: item.session_id }} search={{ view: "overview" }} className={linkClass}>
        Performance lab <ArrowRight size={11} aria-hidden="true" />
      </Link>,
    );
  }
  if (item.basketball_spatial_ready && item.contest_id) {
    links.push(
      <Link key="basketball-spatial" to="/basketball" search={{ contest: item.contest_id }} className={linkClass}>
        Basketball spatial <ArrowRight size={11} aria-hidden="true" />
      </Link>,
    );
  }

  return links.length ? <div className="flex flex-wrap gap-1">{links}</div> : (
    <span className={cn("text-[10px] text-text-muted", !routes.length && "hidden")}>
      Waiting for local capability and grain
    </span>
  );
}

function Stage({ value }: { value: string }) {
  const ready = value === "ready" || value === "materialized" || value === "registered" || value === "available";
  return (
    <span className={cn(
      "inline-flex rounded-[3px] border px-1.5 py-0.5 text-[10px]",
      ready ? "border-border-strong text-text-secondary" : "border-border-subtle text-text-muted",
    )}>
      {value.replaceAll("_", " ")}
    </span>
  );
}

function FilterSelect({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: readonly (readonly [string, string])[];
  onChange: (value: string) => void;
}) {
  return (
    <label className="flex items-center gap-1 text-[10px] text-text-muted">
      <span>{label}</span>
      <select
        aria-label={label}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-7 rounded-control border border-border-subtle bg-surface-0 px-1.5 text-[11px] text-text-secondary outline-none focus:border-accent"
      >
        {options.map(([optionValue, optionLabel]) => (
          <option key={optionValue} value={optionValue}>{optionLabel}</option>
        ))}
      </select>
    </label>
  );
}
