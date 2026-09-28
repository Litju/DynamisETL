import { useNavigate, useSearch } from "@tanstack/react-router";
import { ArrowRight, Search } from "lucide-react";
import { useMemo } from "react";

import type { CatalogResourceView } from "@/api/types";
import { AppLink } from "@/components/common/AppLink";
import { FilterSelect } from "@/components/common/FilterSelect";
import { Page, PageHeader, SectionHeader } from "@/components/common/Page";
import { ReadinessGlyph, ReadinessLadder } from "@/components/common/Readiness";
import { ErrorPanel } from "@/components/common/StatePanel";
import { WorldGlyph } from "@/components/common/WorldGlyph";
import {
  HUMAN_MODALITIES,
  readinessOf,
  studiesForModality,
  type CompetitionNode,
  type EditionNode,
  type SportNode,
  type StudyNode,
} from "@/lib/catalog-model";
import { cn } from "@/lib/cn";
import type { DataSearch } from "@/lib/search";
import { usePublishContext, type Crumb } from "@/lib/state/context";
import { useCatalog } from "@/lib/use-catalog";
import { editionTarget, studyTarget } from "@/lib/worlds";

/** Legacy `/catalog` links land on the Data Browser with equivalent facets. */
function editionMatches(edition: EditionNode, search: DataSearch): boolean {
  const resources: CatalogResourceView[] = [...(edition.resource ? [edition.resource] : []), ...edition.contests];
  if (search.provider && !resources.some((item) => (item.providers ?? []).includes(search.provider!))) return false;
  if (search.rights === "noncommercial" && !resources.some((item) => item.noncommercial_only)) return false;
  if (search.rights === "commercial" && resources.some((item) => item.noncommercial_only || item.local_only)) return false;
  if (search.rights === "local_only" && !resources.some((item) => item.local_only)) return false;
  if (search.status === "ready" && !edition.ready) return false;
  if (search.status === "upstream" && edition.ready) return false;
  const needle = search.q?.trim().toLocaleLowerCase();
  if (needle) {
    const text = [
      edition.competitionName,
      edition.label,
      edition.sportName,
      ...edition.contests.flatMap((contest) => [contest.label, ...(contest.teams ?? []).map((team) => team.display_name)]),
    ].join(" ").toLocaleLowerCase();
    if (!needle.split(/\s+/).every((part) => text.includes(part))) return false;
  }
  return true;
}

function studyMatches(study: StudyNode, search: DataSearch): boolean {
  if (search.provider && study.provider !== search.provider) return false;
  if (search.rights === "noncommercial" && !study.noncommercial) return false;
  if (search.rights === "commercial" && study.noncommercial) return false;
  if (search.status === "ready" && !study.ready) return false;
  if (search.status === "upstream" && study.ready) return false;
  const needle = search.q?.trim().toLocaleLowerCase();
  if (needle && !`${study.name} ${study.provider}`.toLocaleLowerCase().includes(needle)) return false;
  return true;
}

export function DataBrowser() {
  const search = useSearch({ from: "/data" });
  const navigate = useNavigate();
  const catalog = useCatalog();
  const domain = search.domain ?? (search.modality ? "human" : "sports");

  const update = (patch: Partial<DataSearch>, replace = true) => {
    void navigate({
      to: "/data",
      search: (previous: DataSearch) => ({ ...previous, ...patch }),
      replace,
    });
  };

  const providers = useMemo(() => {
    const set = new Set<string>();
    for (const resource of catalog.resources) for (const provider of resource.providers ?? []) set.add(provider);
    for (const study of catalog.studies) set.add(study.provider);
    return [...set].sort();
  }, [catalog.resources, catalog.studies]);

  const sport = catalog.tree.find((node) => node.sportId === search.sport) ?? null;
  const modality = HUMAN_MODALITIES.find((item) => item.id === search.modality) ?? null;

  const crumbs: Crumb[] = [
    { key: "domain", label: domain === "human" ? "Human Performance" : "Sports", kind: "Domain", target: { to: "/data", search: { domain } } },
    ...(domain === "sports" && sport ? [{ key: "sport", label: sport.name, kind: "Sport" }] : []),
    ...(domain === "human" && modality ? [{ key: "modality", label: modality.label, kind: "Modality" }] : []),
  ];
  usePublishContext({ owner: `data:${domain}:${search.sport ?? ""}:${search.modality ?? ""}`, world: null, crumbs });

  const visibleSports = catalog.tree
    .filter((node) => !sport || node.sportId === sport.sportId)
    .map((node) => ({
      ...node,
      competitions: node.competitions
        .map((competition) => ({ ...competition, editions: competition.editions.filter((edition) => editionMatches(edition, search)) }))
        .filter((competition) => competition.editions.length > 0),
    }))
    .filter((node) => node.competitions.length > 0);
  const visibleStudies = catalog.studies.filter(
    (study) => (!modality || study.modalities.includes(modality.id)) && studyMatches(study, search),
  );

  return (
    <div className="flex h-full min-h-0">
      <DataTree
        tree={catalog.tree}
        studies={catalog.studies}
        domain={domain}
        sport={search.sport ?? null}
        modality={search.modality ?? null}
        pending={catalog.isPending}
      />
      <Page label="Data">
        <PageHeader
          kicker={<>Data · {domain === "human" ? "Human Performance" : "Sports"}</>}
          title={domain === "human" ? (modality ? modality.label : "Human Performance") : (sport ? sport.name : "Sports")}
          lede={domain === "human"
            ? "Laboratory and field trials by measurement modality. Each study opens into the Performance World; no competition semantics are imposed on laboratory data."
            : "Competitions and editions by sport. Provider is provenance, not a destination: every item routes to the World its capabilities and grain support."}
        />

        <div className="sticky top-0 z-20 -mx-2 mt-7 flex flex-wrap items-center gap-2 bg-[color-mix(in_oklab,var(--d-surface-0)_88%,transparent)] px-2 py-2.5 backdrop-blur-md">
          <label className="relative flex min-w-64 flex-1 items-center">
            <Search size={13} aria-hidden="true" className="pointer-events-none absolute left-2.5 text-text-muted" />
            <input
              value={search.q ?? ""}
              onChange={(event) => update({ q: event.target.value || undefined })}
              placeholder={domain === "human" ? "Filter studies" : "Filter competitions, editions, teams"}
              aria-label="Filter data"
              className="d-input w-full max-w-md pl-8"
            />
          </label>
          <FilterSelect
            label="Status"
            value={search.status ?? ""}
            onChange={(value) => update({ status: (value || undefined) as DataSearch["status"] })}
            options={[
              { value: "", label: "Any" },
              { value: "ready", label: "Ready server-side" },
              { value: "upstream", label: "Upstream only" },
            ]}
          />
          <FilterSelect
            label="Provider"
            value={search.provider ?? ""}
            onChange={(value) => update({ provider: value || undefined })}
            options={[{ value: "", label: "Any" }, ...providers.map((provider) => ({ value: provider, label: provider }))]}
          />
          <FilterSelect
            label="Rights"
            value={search.rights ?? ""}
            onChange={(value) => update({ rights: (value || undefined) as DataSearch["rights"] })}
            options={[
              { value: "", label: "Any" },
              { value: "commercial", label: "Commercial use allowed" },
              { value: "noncommercial", label: "Non-commercial only" },
              { value: "local_only", label: "Local-only" },
            ]}
          />
        </div>

        <div className="mt-6">
          {catalog.isError ? <ErrorPanel error={catalog.error} onRetry={catalog.refetch} /> : null}
          {catalog.isPending ? <BrowserSkeleton /> : null}
          {!catalog.isPending && !catalog.isError && domain === "sports" ? (
            visibleSports.length ? (
              <div className="space-y-10">
                {visibleSports.map((node) => <SportSection key={node.sportId} sport={node} showTitle={!sport} />)}
              </div>
            ) : <NoMatch />
          ) : null}
          {!catalog.isPending && !catalog.isError && domain === "human" ? (
            <HumanSection studies={visibleStudies} modalityFilter={modality?.id ?? null} />
          ) : null}
        </div>
      </Page>
    </div>
  );
}

function NoMatch() {
  return (
    <div className="d-card px-6 py-10 text-center">
      <p className="text-[13px] text-text-secondary">Nothing matches these filters.</p>
      <p className="mt-1 text-[12px] text-text-muted">Filters apply to catalog metadata; clear one to widen the view.</p>
    </div>
  );
}

function BrowserSkeleton() {
  return (
    <div className="space-y-3" aria-busy="true" aria-label="Loading catalog metadata">
      {[0, 1, 2, 3].map((index) => <div key={index} className="d-skeleton h-16 rounded-[10px]" />)}
    </div>
  );
}

function DataTree({
  tree,
  studies,
  domain,
  sport,
  modality,
  pending,
}: {
  tree: readonly SportNode[];
  studies: readonly StudyNode[];
  domain: "sports" | "human";
  sport: string | null;
  modality: string | null;
  pending: boolean;
}) {
  return (
    <nav aria-label="Data hierarchy" className="flex w-60 shrink-0 flex-col gap-6 overflow-y-auto border-r border-border-subtle bg-surface-0 px-3 py-6 max-[1400px]:w-52">
      <div>
        <AppLink
          to={{ to: "/data", search: { domain: "sports" } }}
          className={cn("t-kicker mb-2 block px-2", domain === "sports" && !sport && "text-text-primary")}
        >
          Sports
        </AppLink>
        <ul className="space-y-px">
          {pending ? [0, 1, 2].map((index) => <li key={index} className="d-skeleton mx-2 my-2 h-4" />) : null}
          {tree.map((node) => (
            <li key={node.sportId}>
              <AppLink
                to={{ to: "/data", search: { domain: "sports", sport: node.sportId } }}
                aria-current={domain === "sports" && sport === node.sportId ? "true" : undefined}
                className="d-row flex items-center justify-between rounded-[6px] px-2 py-1.5 text-[12.5px] text-text-secondary hover:text-text-primary aria-[current=true]:text-text-primary"
              >
                <span>{node.name}</span>
                <span className="mono text-[10.5px] text-text-faint" title={`${node.readyEditions} of ${node.editionCount} editions ready`}>
                  {node.readyEditions}/{node.editionCount}
                </span>
              </AppLink>
            </li>
          ))}
        </ul>
      </div>
      <div>
        <AppLink
          to={{ to: "/data", search: { domain: "human" } }}
          className={cn("t-kicker mb-2 block px-2", domain === "human" && !modality && "text-text-primary")}
        >
          Human Performance
        </AppLink>
        <ul className="space-y-px">
          {HUMAN_MODALITIES.map((item) => {
            const count = studiesForModality(studies, item.id).length;
            return (
              <li key={item.id}>
                <AppLink
                  to={{ to: "/data", search: { domain: "human", modality: item.id } }}
                  aria-current={domain === "human" && modality === item.id ? "true" : undefined}
                  className="d-row flex items-center justify-between rounded-[6px] px-2 py-1.5 text-[12.5px] text-text-secondary hover:text-text-primary aria-[current=true]:text-text-primary"
                >
                  <span>{item.label}</span>
                  <span className="mono text-[10.5px] text-text-faint">{count}</span>
                </AppLink>
              </li>
            );
          })}
        </ul>
      </div>
      <p className="mt-auto px-2 text-[10.5px] leading-relaxed text-text-faint">
        Browsing reads metadata only. Dense tracking, Pose, play-by-play and signals load inside a World.
      </p>
    </nav>
  );
}

function SportSection({ sport, showTitle }: { sport: SportNode; showTitle: boolean }) {
  return (
    <section aria-label={sport.name}>
      {showTitle ? (
        <SectionHeader
          title={sport.name}
          detail={`${sport.readyEditions} of ${sport.editionCount} editions ready · ${sport.readyContests} contests ready`}
          action={<AppLink to={{ to: "/data", search: { domain: "sports", sport: sport.sportId } }} className="text-text-muted hover:text-text-primary">Open</AppLink>}
        />
      ) : null}
      <div className="space-y-4">
        {sport.competitions.map((competition) => <CompetitionBlock key={competition.competitionId} competition={competition} />)}
      </div>
    </section>
  );
}

function CompetitionBlock({ competition }: { competition: CompetitionNode }) {
  const provider = competition.editions[0]?.resource?.providers?.[0] ?? competition.editions[0]?.contests[0]?.providers?.[0] ?? "";
  const ready = competition.editions.filter((edition) => edition.ready);
  const upstream = competition.editions.filter((edition) => !edition.ready);
  return (
    <div className="d-card overflow-hidden">
      <div className="flex items-baseline justify-between gap-4 border-b border-border-subtle px-5 py-3.5">
        <div className="flex items-baseline gap-3">
          <h3 className="text-[14px] font-semibold tracking-[-0.01em] text-text-primary">{competition.name}</h3>
          <span className="text-[11px] text-text-muted">{provider}</span>
        </div>
        <span className="text-[11px] text-text-muted">
          <span className="mono text-text-secondary">{ready.length}</span> ready · {upstream.length} upstream-only
        </span>
      </div>
      <ul className="divide-y divide-border-subtle">
        {ready.map((edition) => <EditionRow key={edition.editionId} edition={edition} />)}
      </ul>
      {upstream.length ? <UpstreamEditions editions={upstream} /> : null}
    </div>
  );
}

function EditionRow({ edition }: { edition: EditionNode }) {
  const readiness = edition.resource ? readinessOf(edition.resource) : null;
  const worlds = edition.worlds.filter((link) => link.ready);
  const matchReady = edition.readyContests > 0;
  return (
    <li>
      <AppLink
        to={editionTarget(edition.editionId)}
        transition
        className="d-row group grid grid-cols-[9rem_minmax(0,1fr)_auto_1.25rem] items-center gap-4 px-5 py-3"
      >
        <span className="text-[13px] font-medium text-text-primary">{edition.label}</span>
        <span className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1 text-[11.5px] text-text-muted">
          {edition.contests.length ? (
            <span>
              <span className="mono text-text-secondary">{edition.readyContests}</span>/{edition.contests.length} contests ready
            </span>
          ) : null}
          {worlds.map((link) => (
            <span key={link.workbench} className="flex items-center gap-1.5 text-text-secondary">
              <WorldGlyph world={link.world} size="sm" className="text-text-muted" />
              {link.workbench === "GameLab" ? "Game" : link.workbench === "SeasonLab" ? "Season" : link.workbench}
            </span>
          ))}
          {matchReady ? (
            <span className="flex items-center gap-1.5 text-text-secondary">
              <WorldGlyph world="match" size="sm" className="text-text-muted" />
              Match
            </span>
          ) : null}
        </span>
        {readiness ? <ReadinessLadder stage={readiness.server} upstream={readiness.upstream} /> : <span />}
        <ArrowRight size={13} aria-hidden="true" className="text-text-faint transition-colors group-hover:text-accent" />
      </AppLink>
    </li>
  );
}

function UpstreamEditions({ editions }: { editions: readonly EditionNode[] }) {
  return (
    <details className="group/upstream border-t border-border-subtle">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-5 py-2.5 text-[11.5px] text-text-muted hover:text-text-secondary">
        <ReadinessGlyph kind="upstream" />
        {editions.length} upstream-only edition{editions.length === 1 ? "" : "s"}
        <span className="text-text-faint">· available at source, not registered locally</span>
        <span className="ml-auto text-text-faint group-open/upstream:hidden">Show</span>
        <span className="ml-auto hidden text-text-faint group-open/upstream:inline">Hide</span>
      </summary>
      <ul className="grid grid-cols-[repeat(auto-fill,minmax(7.5rem,1fr))] gap-1.5 px-5 pb-4 pt-1">
        {editions.map((edition) => (
          <li key={edition.editionId}>
            <AppLink
              to={editionTarget(edition.editionId)}
              transition
              className="flex items-center justify-between rounded-[6px] border border-dashed border-border-subtle px-2.5 py-1.5 text-[11.5px] text-text-muted transition-colors hover:border-border-strong hover:text-text-secondary"
            >
              {edition.label}
            </AppLink>
          </li>
        ))}
      </ul>
    </details>
  );
}

function HumanSection({ studies, modalityFilter }: { studies: readonly StudyNode[]; modalityFilter: string | null }) {
  const groups = HUMAN_MODALITIES.filter((modality) => !modalityFilter || modality.id === modalityFilter);
  if (studies.length === 0) return <NoMatch />;
  return (
    <div className="space-y-10">
      {groups.map((modality) => {
        const list = studiesForModality(studies, modality.id);
        if (!list.length) return null;
        return (
          <section key={modality.id} aria-label={modality.label}>
            <SectionHeader title={modality.label} detail={modality.detail} />
            <div className="grid grid-cols-1 gap-3 min-[1100px]:grid-cols-2">
              {list.map((study) => <StudyCard key={`${modality.id}:${study.datasetId}`} study={study} />)}
            </div>
          </section>
        );
      })}
    </div>
  );
}

function StudyCard({ study }: { study: StudyNode }) {
  return (
    <AppLink to={studyTarget(study.datasetId)} transition className="d-card d-card-interactive group flex flex-col p-5">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="truncate text-[14px] font-semibold tracking-[-0.01em] text-text-primary">{study.shortName}</div>
          <div className="mt-0.5 truncate text-[11.5px] text-text-muted">{study.provider} · {study.license ?? "licence unclear"}{study.noncommercial ? " · non-commercial" : ""}</div>
        </div>
        <WorldGlyph world="performance" className="text-text-muted group-hover:text-accent" />
      </div>
      <dl className="mt-5 grid grid-cols-3 gap-3 text-[11px]">
        <div><dt className="t-kicker">Sessions</dt><dd className="mono mt-1 text-[15px] text-text-primary">{study.sessionCount}</dd></div>
        <div><dt className="t-kicker">Subjects</dt><dd className="mono mt-1 text-[15px] text-text-primary">{study.subjectCount}</dd></div>
        <div><dt className="t-kicker">Trials</dt><dd className="mono mt-1 text-[15px] text-text-primary">{study.trialCount}</dd></div>
      </dl>
      <div className="mt-5 flex items-center justify-between border-t border-border-subtle pt-3 text-[11.5px]">
        <span className="flex items-center gap-1.5 text-text-secondary">
          <ReadinessGlyph kind={study.ready ? "ready" : "upstream"} />
          {study.ready ? `${study.readySessions} sessions ready` : "Upstream available · not materialized"}
        </span>
        <span className="flex items-center gap-1 text-text-muted group-hover:text-accent">
          {study.ready ? "Open study" : "Inspect"} <ArrowRight size={12} aria-hidden="true" />
        </span>
      </div>
    </AppLink>
  );
}
