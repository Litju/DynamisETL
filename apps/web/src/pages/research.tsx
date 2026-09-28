import { useQuery } from "@tanstack/react-query";
import { ArrowRight, ArrowUpRight } from "lucide-react";
import { useMemo } from "react";

import type { CatalogResourceView } from "@/api/types";
import { CatalogSearch } from "@/components/command/CatalogSearch";
import { AppLink } from "@/components/common/AppLink";
import { Page, PageHeader, SectionHeader } from "@/components/common/Page";
import { ReadinessGlyph } from "@/components/common/Readiness";
import { WorldGlyph } from "@/components/common/WorldGlyph";
import { servingStatusQuery } from "@/lib/api/queries";
import { useDenseCacheSummary } from "@/lib/browser-cache";
import {
  contestTitle,
  editionTitle,
  HUMAN_MODALITIES,
  primaryWorld,
  resourceWorlds,
  studiesForModality,
  type SportNode,
  type StudyNode,
} from "@/lib/catalog-model";
import { usePublishContext } from "@/lib/state/context";
import { relativeTime, useRecentContexts, type RecentContext } from "@/lib/state/recent";
import { useCatalog } from "@/lib/use-catalog";
import { studyTarget, targetFromHref, WORLD_IDS, WORLDS, type LinkTarget, type WorldId } from "@/lib/worlds";

interface ReadyItem {
  readonly key: string;
  readonly world: WorldId;
  readonly title: string;
  readonly subtitle: string;
  readonly target: LinkTarget;
  readonly note?: string | undefined;
}

function readyItems(resources: readonly CatalogResourceView[], studies: readonly StudyNode[]): ReadyItem[] {
  const items: ReadyItem[] = [];
  const contests = resources
    .filter((resource) => resource.resource_kind === "contest")
    .map((resource) => ({ resource, world: primaryWorld(resource) }))
    .filter((entry) => entry.world?.target)
    .sort((a, b) =>
      Number((b.resource.materialized_capabilities ?? []).includes("POSE")) -
      Number((a.resource.materialized_capabilities ?? []).includes("POSE")));
  for (const { resource, world } of contests) {
    items.push({
      key: resource.resource_id,
      world: world!.world,
      title: contestTitle(resource),
      subtitle: [resource.competition_name, resource.edition_label].filter(Boolean).join(" · "),
      target: world!.target!,
      note: (resource.materialized_capabilities ?? []).includes("POSE")
        ? "Tracking + Pose"
        : world!.workbench === "Court" ? "Court tracking" : "Tracking",
    });
  }
  for (const resource of resources) {
    if (resource.resource_kind !== "competition_edition") continue;
    for (const link of resourceWorlds(resource)) {
      if (!link.ready || !link.target) continue;
      items.push({
        key: `${resource.resource_id}:${link.workbench}`,
        world: link.world,
        title: editionTitle(resource),
        subtitle: resource.sport_name ?? "",
        target: link.target,
        note: link.world === "game" ? "Play-by-play" : "Season aggregates",
      });
    }
  }
  for (const study of studies.filter((candidate) => candidate.ready)) {
    items.push({
      key: `study:${study.datasetId}`,
      world: "performance",
      title: study.shortName,
      subtitle: `${study.readySessions} sessions · ${study.modalities.map((modality) => modality.toUpperCase()).join(" + ")}`,
      target: studyTarget(study.datasetId),
      note: "Trials",
    });
  }
  return items;
}

export function ResearchHome() {
  usePublishContext({ owner: "research", world: null, crumbs: [] });
  const catalog = useCatalog();
  const recents = useRecentContexts((state) => state.entries);
  const ready = useMemo(() => readyItems(catalog.resources, catalog.studies), [catalog.resources, catalog.studies]);
  const worldCounts = useMemo(() => {
    const counts: Record<WorldId, number> = { match: 0, game: 0, season: 0, performance: 0 };
    for (const item of ready) counts[item.world] += item.world === "performance" ? 0 : 1;
    counts.performance = catalog.studies.reduce((sum, study) => sum + study.readySessions, 0);
    return counts;
  }, [catalog.studies, ready]);

  return (
    <Page label="Research">
      <div className="grid grid-cols-12 items-end gap-x-10 gap-y-6">
        <div className="col-span-12 xl:col-span-7">
          <PageHeader
            kicker={<>Dynamis · Research</>}
            title="Research"
            lede="Resume an analysis or open any ready context. Browsing reads catalog metadata only; dense data loads when you enter a World."
          />
          <CatalogSearch className="mt-6" />
        </div>
        <div className="col-span-12 xl:col-span-5">
          <DataPlaneReadout catalog={catalog} />
        </div>
      </div>

      <div className="mt-11 grid grid-cols-12 gap-x-10 gap-y-10">
        <section className="col-span-12 lg:col-span-7" aria-labelledby="continue-title">
          <SectionHeader
            index="01"
            id="continue-title"
            title={recents.length ? "Continue" : "Start here"}
            detail={recents.length ? "Recent contexts in this browser" : "The most complete ready context"}
          />
          <ContinueList recents={recents} flagship={ready[0] ?? null} pending={catalog.isPending} />
        </section>
        <section className="col-span-12 lg:col-span-5" aria-labelledby="ready-title">
          <SectionHeader
            index="02"
            id="ready-title"
            title="Ready now"
            detail="Server-side ready"
            action={<AppLink to={{ to: "/data" }} className="text-text-muted hover:text-text-primary">All data</AppLink>}
          />
          <ReadyList items={ready.slice(recents.length ? 0 : 1, recents.length ? 5 : 6)} pending={catalog.isPending} />
        </section>
      </div>

      <section className="mt-11" aria-labelledby="worlds-title">
        <SectionHeader index="03" id="worlds-title" title="Worlds" detail="Analytical environments selected by data grain — never by provider" />
        <div className="grid grid-cols-2 gap-3 min-[1180px]:grid-cols-4">
          {WORLD_IDS.map((id) => (
            <WorldCard key={id} world={id} ready={worldCounts[id]} pending={catalog.isPending} recents={recents} />
          ))}
        </div>
      </section>

      <div className="mt-11 grid grid-cols-12 gap-x-10 gap-y-10">
        <section className="col-span-12 lg:col-span-7" aria-labelledby="sports-title">
          <SectionHeader
            index="04"
            id="sports-title"
            title="Sports"
            action={<AppLink to={{ to: "/data", search: { domain: "sports" } }} className="text-text-muted hover:text-text-primary">Browse</AppLink>}
          />
          <SportsOverview tree={catalog.tree} pending={catalog.isPending} />
        </section>
        <section className="col-span-12 lg:col-span-5" aria-labelledby="human-title">
          <SectionHeader
            index="05"
            id="human-title"
            title="Human Performance"
            action={<AppLink to={{ to: "/data", search: { domain: "human" } }} className="text-text-muted hover:text-text-primary">Browse</AppLink>}
          />
          <HumanOverview studies={catalog.studies} pending={catalog.isPending} />
        </section>
      </div>
    </Page>
  );
}

function DataPlaneReadout({ catalog }: { catalog: ReturnType<typeof useCatalog> }) {
  const status = useQuery(servingStatusQuery());
  const cache = useDenseCacheSummary();
  const { summary } = catalog;
  const ok = status.isSuccess;
  return (
    <div className="d-card p-5">
      <div className="mb-5 flex items-center justify-between">
        <span className="t-kicker">Data plane</span>
        <span className="flex items-center gap-1.5 text-[11px] text-text-muted">
          <span aria-hidden="true" className="size-1.5 rounded-full" style={{ background: ok ? "var(--d-success)" : "var(--d-danger)" }} />
          {ok ? `Serving · Gold ${status.data?.gold_published ? "published" : "pending"}` : status.isPending ? "Connecting" : "API unavailable"}
        </span>
      </div>
      <dl className="space-y-3">
        <PlaneRow
          glyph="upstream"
          label="Upstream available"
          value={catalog.isPending ? null : [`${summary.upstreamOnlyContests} contests`, `${summary.editions - summary.readyEditions} editions`]}
        />
        <PlaneRow
          glyph="ready"
          label="Ready server-side"
          value={catalog.isPending ? null : [`${summary.readyContests} contests`, `${summary.readyEditions} editions`, `${summary.readySessions} sessions`]}
        />
        <PlaneRow
          glyph="loaded"
          label="Loaded in this browser"
          value={[`${cache.artifacts} ${cache.artifacts === 1 ? "artifact" : "artifacts"}`]}
          note={cache.fetching ? "loading" : cache.artifacts ? undefined : "nothing dense yet"}
        />
      </dl>
    </div>
  );
}

function PlaneRow({
  glyph,
  label,
  value,
  note,
}: {
  glyph: "upstream" | "ready" | "loaded";
  label: string;
  value: readonly string[] | null;
  note?: string | undefined;
}) {
  return (
    <div className="grid grid-cols-[10.5rem_minmax(0,1fr)] items-baseline gap-3">
      <dt className="flex items-center gap-2 text-[11.5px] text-text-muted">
        <ReadinessGlyph kind={glyph} />
        {label}
      </dt>
      <dd className="min-w-0 text-[12px] leading-snug">
        {value === null ? (
          <span className="d-skeleton inline-block h-3 w-40 align-middle" />
        ) : (
          <>
            <span className="mono text-text-primary">{value.join(" · ")}</span>
            {note ? <span className="ml-2 text-[11px] text-text-faint">{note}</span> : null}
          </>
        )}
      </dd>
    </div>
  );
}

function ContinueList({
  recents,
  flagship,
  pending,
}: {
  recents: readonly RecentContext[];
  flagship: ReadyItem | null;
  pending: boolean;
}) {
  if (recents.length === 0) {
    if (pending) return <div className="d-card h-[7.5rem] p-5"><div className="d-skeleton h-full" /></div>;
    if (!flagship) {
      return (
        <div className="d-card px-6 py-5">
          <p className="text-[13px] text-text-secondary">No ready context is available on this data plane yet.</p>
          <p className="mt-1 text-[12px] text-text-muted">Browse Data to see what is available upstream and what can be prepared.</p>
        </div>
      );
    }
    return (
      <AppLink
        to={flagship.target}
        transition
        className="d-card d-card-interactive group flex items-center gap-5 px-5 py-5"
        aria-label={`Open ${flagship.title} in ${WORLDS[flagship.world].label}`}
      >
        <WorldGlyph world={flagship.world} size="lg" className="text-accent" />
        <span className="min-w-0 flex-1">
          <span className="t-kicker">{WORLDS[flagship.world].label} · {flagship.note}</span>
          <span className="mt-1 block truncate text-[17px] font-semibold tracking-[-0.02em] text-text-primary">{flagship.title}</span>
          <span className="mt-0.5 block truncate text-[12px] text-text-muted">
            {flagship.subtitle} · every World you enter is remembered here with its exact URL
          </span>
        </span>
        <span className="d-btn d-btn-primary shrink-0">
          Open <ArrowRight size={13} aria-hidden="true" />
        </span>
      </AppLink>
    );
  }
  const [first, ...rest] = recents;
  return (
    <div className="flex flex-col gap-2">
      <AppLink
        to={targetFromHref(first!.href)}
        transition
        className="d-card d-card-interactive group flex items-center gap-5 px-5 py-4"
        aria-label={`Resume ${first!.title}`}
      >
        <WorldGlyph world={first!.world} size="lg" className="text-accent" />
        <span className="min-w-0 flex-1">
          <span className="t-kicker">{WORLDS[first!.world].label} · {relativeTime(first!.at)}</span>
          <span className="mt-1 block truncate text-[16px] font-semibold tracking-[-0.015em] text-text-primary">{first!.title}</span>
          <span className="mt-0.5 block truncate text-[12px] text-text-muted">{first!.subtitle}</span>
        </span>
        <span className="d-btn d-btn-primary shrink-0">
          Resume <ArrowRight size={13} aria-hidden="true" />
        </span>
      </AppLink>
      {rest.length ? (
        <ul className="d-card divide-y divide-border-subtle overflow-hidden">
          {rest.slice(0, 4).map((entry) => (
            <li key={entry.key}>
              <AppLink
                to={targetFromHref(entry.href)}
                transition
                className="d-row group flex items-center gap-3 px-4 py-2.5"
              >
                <WorldGlyph world={entry.world} size="sm" className="text-text-muted group-hover:text-accent" />
                <span className="min-w-0 flex-1 truncate text-[12.5px] text-text-primary">{entry.title}</span>
                <span className="cq-hide-narrow truncate text-[11px] text-text-muted">{entry.subtitle}</span>
                <span className="w-20 shrink-0 text-right text-[11px] text-text-faint">{relativeTime(entry.at)}</span>
              </AppLink>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}

function ReadyList({ items, pending }: { items: readonly ReadyItem[]; pending: boolean }) {
  if (pending) {
    return (
      <div className="d-card space-y-3 p-4" aria-busy="true">
        {[0, 1, 2, 3, 4].map((index) => <div key={index} className="d-skeleton h-8" />)}
      </div>
    );
  }
  return (
    <ul className="d-card divide-y divide-border-subtle overflow-hidden">
      {items.map((item) => (
        <li key={item.key}>
          <AppLink to={item.target} transition className="d-row group flex items-center gap-3 px-4 py-2.5">
            <WorldGlyph world={item.world} size="sm" className="text-text-muted group-hover:text-accent" />
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[12.5px] text-text-primary">{item.title}</span>
              <span className="block truncate text-[11px] text-text-muted">{item.subtitle}</span>
            </span>
            {item.note ? <span className="shrink-0 text-[10.5px] text-text-faint">{item.note}</span> : null}
            <ArrowUpRight size={13} aria-hidden="true" className="shrink-0 text-text-faint transition-colors group-hover:text-accent" />
          </AppLink>
        </li>
      ))}
    </ul>
  );
}

function WorldCard({
  world,
  ready,
  pending,
  recents,
}: {
  world: WorldId;
  ready: number;
  pending: boolean;
  recents: readonly RecentContext[];
}) {
  const meta = WORLDS[world];
  const last = recents.find((entry) => entry.world === world) ?? null;
  return (
    <AppLink
      to={last ? targetFromHref(last.href) : { to: meta.entry }}
      transition
      className="d-card d-card-interactive group flex min-h-[11.5rem] flex-col p-5"
      aria-label={`${meta.label}: ${meta.question}`}
    >
      <div className="flex items-start justify-between">
        <WorldGlyph world={world} size="lg" className="text-text-secondary transition-colors duration-quick group-hover:text-accent" />
        <span className="t-kicker text-text-faint">{meta.grain.replace("_", " ")}</span>
      </div>
      <div className="mt-auto pt-5">
        <div className="text-[15px] font-semibold tracking-[-0.015em] text-text-primary">{meta.label}</div>
        <p className="mt-1 min-h-[2.75em] text-[12px] leading-snug text-text-muted">{meta.question}</p>
        <div className="mt-4 flex items-center justify-between text-[11px]">
          <span className="flex items-center gap-1.5 text-text-secondary">
            <ReadinessGlyph kind="ready" />
            {pending ? "…" : `${ready} ready`}
          </span>
          <span className="flex items-center gap-1 text-text-muted transition-colors group-hover:text-accent">
            {last ? "Resume" : "Enter"} <ArrowRight size={12} aria-hidden="true" />
          </span>
        </div>
      </div>
    </AppLink>
  );
}

function SportsOverview({ tree, pending }: { tree: readonly SportNode[]; pending: boolean }) {
  if (pending) return <div className="d-card h-40 p-4"><div className="d-skeleton h-full" /></div>;
  return (
    <ul className="d-card divide-y divide-border-subtle overflow-hidden">
      {tree.map((sport) => (
        <li key={sport.sportId} className="grid grid-cols-[8rem_minmax(0,1fr)_auto] items-center gap-4 px-4 py-3">
          <AppLink
            to={{ to: "/data", search: { domain: "sports", sport: sport.sportId } }}
            className="text-[13px] font-medium text-text-primary hover:text-accent"
          >
            {sport.name}
          </AppLink>
          <span className="flex min-w-0 flex-wrap gap-x-3 gap-y-1">
            {sport.competitions.map((competition) => {
              const latestReady = competition.editions.find((edition) => edition.ready) ?? competition.editions[0];
              return latestReady ? (
                <AppLink
                  key={competition.competitionId}
                  to={{ to: "/data/edition/$editionId", params: { editionId: latestReady.editionId } }}
                  transition
                  className="text-[12px] text-text-secondary hover:text-text-primary"
                >
                  {competition.name}
                  <span className="ml-1 text-text-faint">{latestReady.label}</span>
                </AppLink>
              ) : null;
            })}
          </span>
          <span className="whitespace-nowrap text-right text-[11px] text-text-muted">
            <span className="mono text-text-secondary">{sport.readyEditions}</span>/{sport.editionCount} editions ready
          </span>
        </li>
      ))}
    </ul>
  );
}

function HumanOverview({ studies, pending }: { studies: readonly StudyNode[]; pending: boolean }) {
  if (pending) return <div className="d-card h-40 p-4"><div className="d-skeleton h-full" /></div>;
  return (
    <ul className="d-card divide-y divide-border-subtle overflow-hidden">
      {HUMAN_MODALITIES.map((modality) => {
        const list = studiesForModality(studies, modality.id);
        return (
          <li key={modality.id} className="grid grid-cols-[4rem_minmax(0,1fr)] items-baseline gap-4 px-4 py-3">
            <AppLink
              to={{ to: "/data", search: { domain: "human", modality: modality.id } }}
              className="text-[13px] font-medium text-text-primary hover:text-accent"
            >
              {modality.label}
            </AppLink>
            <span className="flex min-w-0 flex-col gap-1">
              {list.length ? list.map((study) => (
                <AppLink
                  key={study.datasetId}
                  to={studyTarget(study.datasetId)}
                  transition
                  className="flex items-center gap-2 text-[12px] text-text-secondary hover:text-text-primary"
                >
                  <ReadinessGlyph kind={study.ready ? "ready" : "upstream"} />
                  <span className="truncate">{study.shortName}</span>
                  <span className="shrink-0 text-[11px] text-text-faint">
                    {study.ready ? `${study.readySessions} sessions` : "upstream only"}
                  </span>
                </AppLink>
              )) : <span className="text-[12px] text-text-faint">No registered study</span>}
            </span>
          </li>
        );
      })}
    </ul>
  );
}
