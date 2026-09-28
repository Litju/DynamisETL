import { useQuery } from "@tanstack/react-query";
import { useNavigate, useSearch } from "@tanstack/react-router";
import { Table2, UserRound } from "lucide-react";
import { useCallback, useEffect, useMemo } from "react";

import type { SeasonFamilyView, SeasonProfileView, SeasonRowView } from "@/api/types";
import { ErrorPanel, LoadingPanel, StatePanel } from "@/components/common/StatePanel";
import { MetricProfile, SplitComparison } from "@/components/season/MetricProfile";
import { SeasonCompareControl, SeasonDenominatorControl, SeasonMetricPicker } from "@/components/season/SeasonControls";
import { SeasonEvidence } from "@/components/season/SeasonEvidence";
import { SeasonFocusCharts } from "@/components/season/SeasonFocusCharts";
import { SeasonNavigator } from "@/components/season/SeasonNavigator";
import { SeasonPopulationTable } from "@/components/season/SeasonPopulationTable";
import {
  seasonEditionsQuery,
  seasonFamilyQuery,
  seasonProfileQuery,
  seasonRowsQuery,
} from "@/lib/api/queries";
import { cn } from "@/lib/cn";
import {
  FAMILY_ORDER,
  playerInitials,
  resolveSelectedMetrics,
  shortTeamName,
  splitCounterparts,
} from "@/lib/season-model";
import type { SeasonFamily, SeasonPopulation, SeasonSearch } from "@/lib/search";

/** Keys whose change is a new analytical context (pushes history). */
const CONTEXT_KEYS: ReadonlySet<keyof SeasonSearch> = new Set([
  "edition",
  "family",
  "team",
  "player",
  "pos",
  "population",
  "min",
  "metrics",
  "compare",
  "view",
]);

function cleanSearch(search: SeasonSearch): SeasonSearch {
  const output: Record<string, string> = {};
  for (const [key, value] of Object.entries(search)) {
    if (typeof value === "string" && value.length > 0) output[key] = value;
  }
  return output as SeasonSearch;
}

export type SeasonUpdate = (patch: Partial<Record<keyof SeasonSearch, string | undefined>>) => void;

/**
 * SeasonLab: PLAYER_SEASON analysis.
 *
 * The URL is the only durable authority (edition → team → player → family, the
 * comparison denominator and the metric panel). TanStack Query owns every served
 * value; a context change swaps query keys, so values from the previous player or
 * population are never shown under the new header.
 */
export function SeasonLab() {
  const search = useSearch({ from: "/season" });
  const navigate = useNavigate();
  const editions = useQuery(seasonEditionsQuery());

  const update = useCallback<SeasonUpdate>(
    (patch) => {
      const contextChange = Object.keys(patch).some((key) => CONTEXT_KEYS.has(key as keyof SeasonSearch));
      void navigate({
        to: "/season",
        search: (previous: SeasonSearch) => cleanSearch({ ...previous, ...patch } as SeasonSearch),
        replace: !contextChange,
      });
    },
    [navigate],
  );

  const edition = useMemo(() => {
    const list = editions.data ?? [];
    return list.find((item) => item.edition_id === search.edition) ?? list[0] ?? null;
  }, [editions.data, search.edition]);

  // Make the resolved edition durable without adding a history entry.
  useEffect(() => {
    if (edition && search.edition !== edition.edition_id) {
      void navigate({
        to: "/season",
        search: (previous: SeasonSearch) => cleanSearch({ ...previous, edition: edition.edition_id }),
        replace: true,
      });
    }
  }, [edition, navigate, search.edition]);

  if (editions.isPending) return <LoadingPanel label="Loading season editions" />;
  if (editions.isError) return <ErrorPanel error={editions.error} onRetry={() => void editions.refetch()} />;
  if (!edition) {
    return (
      <StatePanel
        state="not_materialized"
        title="No season-grain data is materialized."
        detail="SeasonLab opens PLAYER_SEASON / TEAM_SEASON artifacts. Materialize a season aggregate family to analyse it here."
      />
    );
  }

  const available = new Set(edition.families.map((item) => item.family));
  const family: SeasonFamily =
    search.family && available.has(search.family)
      ? search.family
      : (FAMILY_ORDER.find((item) => available.has(item)) ?? "physical");

  return <SeasonWorkspace key={`${edition.edition_id}:${family}`} family={family} search={search} update={update} editionId={edition.edition_id} />;
}

function SeasonWorkspace({
  editionId,
  family,
  search,
  update,
}: {
  editionId: string;
  family: SeasonFamily;
  search: SeasonSearch;
  update: SeasonUpdate;
}) {
  const familyView = useQuery(seasonFamilyQuery(editionId, family));
  const roster = useQuery(seasonRowsQuery({ editionId, family, metrics: [], limit: 1000 }));

  if (familyView.isPending) return <LoadingPanel label="Preparing season context" />;
  if (familyView.isError) {
    return <ErrorPanel error={familyView.error} onRetry={() => void familyView.refetch()} />;
  }
  return (
    <SeasonWorkbench
      family={family}
      familyView={familyView.data}
      rosterRows={roster.data?.rows ?? null}
      rosterPending={roster.isPending}
      search={search}
      update={update}
    />
  );
}

function SeasonWorkbench({
  family,
  familyView,
  rosterRows,
  rosterPending,
  search,
  update,
}: {
  family: SeasonFamily;
  familyView: SeasonFamilyView;
  rosterRows: readonly SeasonRowView[] | null;
  rosterPending: boolean;
  search: SeasonSearch;
  update: SeasonUpdate;
}) {
  const edition = familyView.edition;
  const registry = familyView.metrics;
  const population: SeasonPopulation = search.population ?? "position";
  const minMatches = search.min ? Number(search.min) : undefined;
  const selected = useMemo(
    () => resolveSelectedMetrics(family, search.metrics, registry),
    [family, registry, search.metrics],
  );
  const profileMetrics = useMemo(
    () => [...selected, ...splitCounterparts(selected, registry)],
    [registry, selected],
  );
  const focus =
    search.focus && registry.some((metric) => metric.column === search.focus)
      ? search.focus
      : (selected[0] ?? null);
  const rowMetrics = useMemo(
    () => (focus && !selected.includes(focus) ? [...selected, focus] : [...selected]),
    [focus, selected],
  );

  // The player's grain row: an explicit team/position narrows it only when the
  // roster confirms such a row exists, so a team filter never produces a 404.
  const playerRows = useMemo(
    () => (search.player ? (rosterRows ?? []).filter((row) => row.subject_id === search.player) : []),
    [rosterRows, search.player],
  );
  const rowTeam = playerRows.some((row) => row.team_id === search.team) ? search.team : undefined;
  const rowPos = playerRows.some(
    (row) => row.position_group === search.pos && (!rowTeam || row.team_id === rowTeam),
  )
    ? search.pos
    : undefined;

  const profile = useQuery({
    ...seasonProfileQuery({
      editionId: edition.edition_id,
      family,
      subjectId: search.player ?? "",
      teamId: rowTeam,
      positionGroup: rowPos,
      population,
      minMatches,
      metrics: profileMetrics,
    }),
    enabled: Boolean(search.player) && !rosterPending,
  });
  const populationScope = profile.data?.population;
  const compare = useQuery({
    ...seasonProfileQuery({
      editionId: edition.edition_id,
      family,
      subjectId: search.compare ?? "",
      population,
      minMatches,
      metrics: profileMetrics,
      populationTeamId: populationScope?.team_id ?? undefined,
      populationPositionGroup: populationScope?.position_group ?? undefined,
    }),
    enabled: Boolean(search.compare) && profile.isSuccess && search.compare !== search.player,
  });

  // Population rows for the distribution/table use exactly the profile's filter.
  const populationRows = useQuery({
    ...seasonRowsQuery({
      editionId: edition.edition_id,
      family,
      metrics: rowMetrics,
      teamId: populationScope?.team_id ?? undefined,
      positionGroup: populationScope?.position_group ?? undefined,
      minMatches,
      limit: 1000,
    }),
    enabled: !search.player || profile.isSuccess,
  });

  const selectedRow = profile.data?.row ?? null;
  const teamLabel = search.team
    ? familyView.teams.find((team) => team.team_id === search.team)?.display_name
    : undefined;

  return (
    <div className="season-lab flex h-full min-h-0 flex-col" data-family={family}>
      <header className="shrink-0 border-b border-border-subtle bg-surface-1 px-4 py-2">
        <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
          <div className="flex items-baseline gap-2.5" aria-label={`Season context: ${[edition.sport_name, edition.competition_name, edition.edition_label, teamLabel ? shortTeamName(teamLabel) : null, selectedRow?.player_name].filter(Boolean).join(" · ")}`}>
            <span className="t-kicker">Season World</span>
            <h1 className="text-[15px] font-semibold tracking-[-0.015em] text-text-primary">SeasonLab</h1>
            <span className="t-label hidden min-[1500px]:inline">{edition.provider} · player season</span>
          </div>
          <FamilyTabs edition={edition} family={family} onChange={(next) => update({ family: next, metrics: undefined, focus: undefined })} />
          <div className="ml-auto flex flex-wrap items-end gap-2">
            <SeasonDenominatorControl
              population={population}
              minMatches={minMatches ?? null}
              rows={populationScope?.rows ?? populationRows.data?.total ?? null}
              label={populationScope?.label ?? `All ${edition.competition_name} ${edition.edition_label} rows`}
              onPopulation={(next) => update({ population: next })}
              onMinMatches={(next) => update({ min: next ? String(next) : undefined })}
            />
            <SeasonMetricPicker
              registry={registry}
              selected={selected}
              onChange={(next) => update({ metrics: next.join(",") || undefined })}
            />
            <ViewToggle view={search.view ?? "profile"} onChange={(view) => update({ view: view === "profile" ? undefined : view })} />
          </div>
        </div>
      </header>

      <div className="season-grid min-h-0 flex-1">
        <SeasonNavigator
          familyView={familyView}
          rows={rosterRows}
          pending={rosterPending}
          teamId={search.team ?? null}
          playerId={search.player ?? null}
          query={search.q ?? ""}
          onTeam={(teamId) => update({ team: teamId ?? undefined })}
          onQuery={(q) => update({ q: q || undefined })}
          onPlayer={(row) =>
            update({
              player: row.subject_id,
              pos: row.position_group,
              team: search.team ? row.team_id : undefined,
              compare: search.compare === row.subject_id ? undefined : search.compare,
            })
          }
        />

        <main className="min-w-0 overflow-y-auto" aria-label="Season analysis">
          {search.view === "table" ? (
            <SeasonPopulationTable
              registry={registry}
              selected={selected}
              query={populationRows}
              selectedKey={selectedRow ? rowKey(selectedRow) : null}
              populationLabel={populationScope?.label ?? `All ${edition.competition_name} ${edition.edition_label} rows`}
              onSelect={(row) => update({ player: row.subject_id, pos: row.position_group, view: undefined })}
            />
          ) : !search.player ? (
            <SeasonOverview
              editionLabel={`${edition.competition_name} ${edition.edition_label}`}
              familyView={familyView}
              focus={focus}
              registry={registry}
              populationRows={populationRows.data?.rows ?? null}
              onFocus={(column) => update({ focus: column })}
            />
          ) : profile.isPending || rosterPending ? (
            <LoadingPanel label="Ranking the selected row" />
          ) : profile.isError ? (
            <ErrorPanel error={profile.error} onRetry={() => void profile.refetch()} />
          ) : (
            <ProfileBody
              family={family}
              profile={profile.data}
              compare={compare.data ?? null}
              comparePending={compare.isFetching}
              playerRows={playerRows}
              rosterRows={rosterRows ?? []}
              registry={registry}
              selected={selected}
              focus={focus}
              populationRows={populationRows.data?.rows ?? null}
              compareId={search.compare ?? null}
              update={update}
            />
          )}
        </main>

        <SeasonEvidence
          familyView={familyView}
          focus={focus}
          profile={profile.data ?? null}
          compare={compare.data ?? null}
          registry={registry}
          playerId={search.player ?? null}
        />
      </div>
    </div>
  );
}

export function rowKey(row: Pick<SeasonRowView, "subject_id" | "team_id" | "position_group">): string {
  return `${row.subject_id}|${row.team_id}|${row.position_group}`;
}

function FamilyTabs({
  edition,
  family,
  onChange,
}: {
  edition: SeasonFamilyView["edition"];
  family: SeasonFamily;
  onChange: (family: SeasonFamily) => void;
}) {
  const refs = FAMILY_ORDER.map((item) => edition.families.find((ref) => ref.family === item)).filter(
    (ref): ref is NonNullable<typeof ref> => ref !== undefined,
  );
  return (
    <div role="tablist" aria-label="Metric family" className="flex items-end gap-4">
      {refs.map((ref) => {
        const active = ref.family === family;
        return (
          <button
            key={ref.family}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(ref.family as SeasonFamily)}
            className={cn(
              "relative pb-1.5 text-[13px] transition-colors duration-quick",
              active ? "text-text-primary" : "text-text-muted hover:text-text-secondary",
            )}
          >
            {ref.label}
            <span className="mono ml-1.5 text-[10px] text-text-muted">{ref.row_count}</span>
            {active ? <span aria-hidden="true" className="t-tab-indicator absolute inset-x-0 -bottom-px h-0.5 rounded-full bg-accent" /> : null}
          </button>
        );
      })}
    </div>
  );
}

function ViewToggle({ view, onChange }: { view: "profile" | "table"; onChange: (view: "profile" | "table") => void }) {
  return (
    <div role="radiogroup" aria-label="Season view" className="flex h-7 items-center rounded-control border border-border-subtle bg-surface-0 p-0.5">
      {(
        [
          ["profile", "Profile", UserRound],
          ["table", "Population table", Table2],
        ] as const
      ).map(([value, label, Icon]) => (
        <button
          key={value}
          type="button"
          role="radio"
          aria-checked={view === value}
          onClick={() => onChange(value)}
          title={label}
          className={cn(
            "flex h-6 items-center gap-1.5 rounded-[3px] px-2 text-[11px] transition-colors duration-quick",
            view === value ? "bg-surface-3 text-text-primary" : "text-text-muted hover:text-text-secondary",
          )}
        >
          <Icon size={12} aria-hidden="true" />
          <span className="hidden 2xl:inline">{label}</span>
          <span className="sr-only 2xl:hidden">{label}</span>
        </button>
      ))}
    </div>
  );
}

function SeasonOverview({
  editionLabel,
  familyView,
  focus,
  registry,
  populationRows,
  onFocus,
}: {
  editionLabel: string;
  familyView: SeasonFamilyView;
  focus: string | null;
  registry: SeasonFamilyView["metrics"];
  populationRows: readonly SeasonRowView[] | null;
  onFocus: (column: string) => void;
}) {
  return (
    <div className="flex flex-col gap-6 px-6 py-6">
      <section aria-labelledby="season-overview-title" className="max-w-3xl">
        <p className="t-section">{familyView.family.label} · {editionLabel}</p>
        <h2 id="season-overview-title" className="mt-2 text-[26px] font-semibold leading-tight tracking-[-0.02em] text-text-primary">
          {familyView.population_subjects} players · {familyView.population_rows} season rows
        </h2>
        <p className="t-body mt-2 max-w-2xl">
          Each row is one player × team × position group, aggregated by the provider across
          included match performances. Choose a team and a player to rank them inside an
          explicit population; every percentile names its denominator.
        </p>
      </section>
      <SeasonFocusCharts
        registry={registry}
        focus={focus}
        populationRows={populationRows}
        populationLabel={`All ${editionLabel} rows`}
        selected={null}
        compare={null}
        radarMetrics={[]}
        onFocus={onFocus}
      />
    </div>
  );
}

function ProfileBody({
  family,
  profile,
  compare,
  comparePending,
  playerRows,
  rosterRows,
  registry,
  selected,
  focus,
  populationRows,
  compareId,
  update,
}: {
  family: SeasonFamily;
  profile: SeasonProfileView;
  compare: SeasonProfileView | null;
  comparePending: boolean;
  playerRows: readonly SeasonRowView[];
  rosterRows: readonly SeasonRowView[];
  registry: SeasonFamilyView["metrics"];
  selected: readonly string[];
  focus: string | null;
  populationRows: readonly SeasonRowView[] | null;
  compareId: string | null;
  update: SeasonUpdate;
}) {
  const row = profile.row;
  const selectedRanked = profile.metrics.filter((metric) => selected.includes(metric.column));
  const otherRows = playerRows.filter((item) => rowKey(item) !== rowKey(row));
  return (
    <div className="season-profile flex flex-col">
      <section className="season-masthead border-b border-border-subtle px-6 pb-5 pt-5" aria-label="Selected player">
        <div className="flex items-start gap-4">
          <div aria-hidden="true" className="season-monogram mono flex size-12 shrink-0 items-center justify-center rounded-full text-[15px] font-medium">
            {playerInitials(row.player_name)}
          </div>
          <div className="min-w-0 flex-1">
            <p className="t-section">{shortTeamName(row.team_name)} · {row.position_group}</p>
            <h2 className="mt-1 truncate text-[28px] font-semibold leading-none tracking-[-0.025em] text-text-primary">
              {row.player_name}
            </h2>
            <dl className="mt-3 flex flex-wrap gap-x-6 gap-y-1">
              <MastheadFact label="Included matches" value={row.matches === null ? "—" : String(row.matches)} />
              <MastheadFact label="Denominator" value={`${profile.population.rows} rows`} />
              <MastheadFact label="Population" value={profile.population.label} wide />
            </dl>
            {otherRows.length > 0 ? (
              <div className="mt-3 flex flex-wrap items-center gap-1.5">
                <span className="t-label">Other rows this season</span>
                {otherRows.map((item) => (
                  <button
                    key={rowKey(item)}
                    type="button"
                    onClick={() => update({ pos: item.position_group, team: item.team_id !== row.team_id ? item.team_id : undefined })}
                    className="rounded-full border border-border-subtle px-2 py-0.5 text-[11px] text-text-secondary transition-colors duration-quick hover:border-border-strong hover:text-text-primary"
                  >
                    {item.position_group}
                    {item.team_id !== row.team_id ? ` · ${shortTeamName(item.team_name)}` : ""}
                    <span className="mono ml-1 text-text-muted">{item.matches ?? "—"}</span>
                  </button>
                ))}
              </div>
            ) : null}
          </div>
          <SeasonCompareControl
            rows={rosterRows}
            excludeSubject={row.subject_id}
            compareId={compareId}
            compare={compare}
            pending={comparePending}
            onChange={(subjectId) => update({ compare: subjectId ?? undefined })}
          />
        </div>
      </section>

      <div className="season-analysis grid gap-px bg-border-subtle">
        <section className="bg-surface-0 px-6 py-4" aria-labelledby="season-profile-heading">
          <div className="mb-3 flex items-baseline justify-between gap-3">
            <h3 id="season-profile-heading" className="t-section">Metric profile</h3>
            <span className="t-label">
              value · population range · rank / valid n · percentile
            </span>
          </div>
          <MetricProfile
            registry={registry}
            ranked={selectedRanked}
            compare={compare}
            focus={focus}
            onFocus={(column) => update({ focus: column })}
          />
        </section>
        <section className="bg-surface-0 px-6 py-4" aria-label="Focused metric distribution">
          <SeasonFocusCharts
            registry={registry}
            focus={focus}
            populationRows={populationRows}
            populationLabel={profile.population.label}
            selected={row}
            compare={compare?.row ?? null}
            radarMetrics={selectedRanked}
            compareRanked={compare?.metrics ?? null}
            onFocus={(column) => update({ focus: column })}
          />
        </section>
        {family === "physical" ? (
          <section className="bg-surface-0 px-6 py-4" aria-labelledby="season-split-heading">
            <div className="mb-3 flex items-baseline justify-between gap-3">
              <h3 id="season-split-heading" className="t-section">In possession vs out of possession</h3>
              <span className="t-label">TIP = team in possession · OTIP = opponent in possession</span>
            </div>
            <SplitComparison registry={registry} selected={selected} ranked={profile.metrics} />
          </section>
        ) : null}
      </div>
    </div>
  );
}

function MastheadFact({ label, value, wide = false }: { label: string; value: string; wide?: boolean }) {
  return (
    <div className={cn("flex items-baseline gap-2", wide && "min-w-0")}>
      <dt className="t-label">{label}</dt>
      <dd className={cn("text-[12px] text-text-secondary", wide ? "truncate" : "mono")}>{value}</dd>
    </div>
  );
}
