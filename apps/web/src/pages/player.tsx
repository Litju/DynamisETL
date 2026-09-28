import { useQueries, useQuery } from "@tanstack/react-query";
import { useParams, useSearch } from "@tanstack/react-router";
import { ArrowRight, ShieldCheck } from "lucide-react";

import type { SeasonEditionView } from "@/api/types";
import { AppLink } from "@/components/common/AppLink";
import { CopyableId } from "@/components/common/CopyableId";
import { Page, PageHeader, SectionHeader } from "@/components/common/Page";
import { ReadinessGlyph, ServerReadiness } from "@/components/common/Readiness";
import { ErrorPanel, StatePanel } from "@/components/common/StatePanel";
import { WorldGlyph } from "@/components/common/WorldGlyph";
import { seasonEditionsQuery, seasonFamilyQuery, seasonLinksQuery, seasonRowsQuery, sessionQuery } from "@/lib/api/queries";
import { contestTitle, readinessOf, resourceWorlds } from "@/lib/catalog-model";
import { DEFAULT_SEASON_METRICS, formatSeasonValue, shortTeamName, unitSuffix } from "@/lib/season-model";
import type { SeasonFamily } from "@/lib/search";
import { usePublishContext, type Crumb } from "@/lib/state/context";
import { useCatalog } from "@/lib/use-catalog";
import { editionTarget, matchWorldTarget, seasonWorldTarget, teamTarget } from "@/lib/worlds";
import { verifiedParticipant } from "@/lib/participants";

export function PlayerPage() {
  const { subjectId } = useParams({ from: "/data/player/$subjectId" });
  const search = useSearch({ from: "/data/player/$subjectId" });
  const catalog = useCatalog();
  const editions = useQuery(seasonEditionsQuery());
  const datasetId = subjectId.split("/")[0] ?? "";
  const season: SeasonEditionView | null = search.edition
    ? editions.data?.find((item) => item.edition_id === search.edition) ?? null
    : editions.data?.find((item) => item.dataset_id === datasetId) ?? null;
  const editionId = season?.edition_id ?? search.edition ?? null;
  const families = (season?.families ?? []).map((family) => family.family as SeasonFamily);

  const rows = useQueries({
    queries: families.map((family) => ({
      ...seasonRowsQuery({
        editionId: editionId ?? "",
        family,
        metrics: DEFAULT_SEASON_METRICS[family]?.slice(0, 4) ?? [],
        subjectIds: [subjectId],
        limit: 20,
      }),
      enabled: Boolean(editionId),
    })),
  });
  const registries = useQueries({
    queries: families.map((family) => ({ ...seasonFamilyQuery(editionId ?? "", family), enabled: Boolean(editionId) })),
  });
  const links = useQuery({ ...seasonLinksQuery(editionId ?? "", subjectId), enabled: Boolean(editionId) });
  const appearances = links.data?.appearances ?? [];
  const sessions = useQueries({
    queries: appearances.map((item) => sessionQuery(item.dataset_id, item.session_id)),
  });

  const firstRow = rows.map((query) => query.data?.rows[0]).find(Boolean) ?? null;
  const allRows = rows.flatMap((query) => query.data?.rows ?? []);
  const name = firstRow?.player_name ?? null;
  const teams = [...new Map(allRows.map((row) => [row.team_id, row.team_name])).entries()];
  const positions = [...new Set(allRows.map((row) => row.position_group))];
  const matches = Math.max(0, ...allRows.map((row) => row.matches ?? 0));

  const crumbs: Crumb[] = [
    ...(season ? [
      { key: "sport", label: season.sport_name, kind: "Sport", target: { to: "/data", search: { domain: "sports", sport: season.sport_id } } },
      { key: "edition", label: `${season.competition_name} ${season.edition_label}`, kind: "Edition", target: editionTarget(season.edition_id) },
    ] : []),
    ...(teams[0] ? [{ key: "team", label: shortTeamName(teams[0][1]), kind: "Team", target: teamTarget(teams[0][0], editionId) }] : []),
    { key: "player", label: name ?? "Player", kind: "Player", pending: name === null },
  ];
  usePublishContext({ owner: `player:${subjectId}`, world: null, crumbs });

  const rowsPending = rows.some((query) => query.isPending) || editions.isPending;
  if (editions.isError) return <ErrorPanel error={editions.error} onRetry={() => void editions.refetch()} />;
  if (catalog.isError) return <ErrorPanel error={catalog.error} onRetry={catalog.refetch} />;
  const rowsError = rows.find((query) => query.isError);
  if (rowsError?.error) return <ErrorPanel error={rowsError.error} onRetry={() => void rowsError.refetch()} />;
  if (search.edition && !season && !editions.isPending) {
    return <StatePanel state="not_found" title="This edition has no season context for this player." detail="The selected edition is not served for this canonical subject." />;
  }
  if (!rowsPending && !firstRow) {
    return <StatePanel state="not_materialized" title="No season row is materialized for this player." detail="The canonical subject id stays distinct from provider names; a season profile appears only when a served season row names this id." />;
  }

  const byContest = new Map(catalog.resources.filter((item) => item.resource_kind === "contest").map((item) => [item.contest_id, item]));

  return (
    <Page label={name ?? "Player"}>
      <PageHeader
        kicker={<>{season ? `${season.sport_name} · ${season.competition_name} ${season.edition_label}` : "Player"} · Player</>}
        title={name ?? <span className="d-skeleton inline-block h-9 w-80 align-middle" />}
        meta={
          name ? (
            <>
              {teams.map(([teamId, teamName]) => (
                <AppLink key={teamId} to={teamTarget(teamId, editionId)} transition className="text-[12.5px] text-text-secondary hover:text-accent">
                  {teamName}
                </AppLink>
              ))}
              <span className="text-[12px] text-text-muted">{positions.join(" / ")}</span>
              <span className="text-[12px] text-text-muted"><span className="mono text-text-secondary">{matches}</span> matches in season aggregates</span>
            </>
          ) : null
        }
        actions={
          editionId && teams[0] ? (
            <AppLink
              to={seasonWorldTarget(editionId, { player: subjectId, team: teams[0][0] })}
              transition
              className="d-btn d-btn-primary"
            >
              <WorldGlyph world="season" size="sm" /> Open Season World
            </AppLink>
          ) : null
        }
      />

      <section className="mt-10" aria-labelledby="player-season">
        <SectionHeader index="01" id="player-season" title="Season data" detail={season ? `${season.provider} · source-derived season means · ${season.inclusion_rule.split(";")[0]}` : undefined} />
        <div className="grid grid-cols-1 gap-3 min-[1000px]:grid-cols-3">
          {families.map((family, index) => {
            const query = rows[index];
            const registry = registries[index]?.data;
            const row = query?.data?.rows[0];
            const metrics = DEFAULT_SEASON_METRICS[family]?.slice(0, 4) ?? [];
            const label = season?.families.find((item) => item.family === family)?.label ?? family;
            const card = (
              <>
                <div className="flex items-center justify-between">
                  <span className="text-[13.5px] font-semibold text-text-primary">{label}</span>
                  {row ? <span className="text-[11px] text-text-muted group-hover:text-accent">Distribution <ArrowRight size={11} aria-hidden="true" className="inline" /></span> : null}
                </div>
                {query?.isPending ? (
                  <div className="mt-4 space-y-2">{[0, 1, 2].map((key) => <div key={key} className="d-skeleton h-5" />)}</div>
                ) : row ? (
                  <dl className="mt-4 space-y-2.5">
                    {metrics.map((column) => {
                      const metric = registry?.metrics.find((candidate) => candidate.column === column);
                      const unit = metric?.unit ?? "";
                      return (
                        <div key={column} className="grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-3">
                          <dt className="truncate text-[11.5px] text-text-muted" title={metric?.definition}>{metric?.label ?? column}</dt>
                          <dd className="mono text-[13px] text-text-primary">
                            {formatSeasonValue(row.values[column], unit)}
                            <span className="ml-1 text-[10.5px] text-text-faint">{unitSuffix(unit)}</span>
                          </dd>
                        </div>
                      );
                    })}
                  </dl>
                ) : (
                  <StatePanel
                    className="mt-3 min-h-24 flex-1 p-3"
                    state="not_materialized"
                    title={`${label} data is unavailable for this player.`}
                    detail="No season row for this canonical subject exists in this family."
                  />
                )}
                <p className="mt-4 border-t border-border-subtle pt-2.5 text-[10.5px] text-text-faint">
                  {row ? "Values only. Percentiles appear in Season World with their named denominator." : "No values are inferred from the other season families."}
                </p>
              </>
            );
            return row ? (
              <AppLink
                key={family}
                to={seasonWorldTarget(editionId ?? "", { player: subjectId, family, ...(teams[0] ? { team: teams[0][0] } : {}) })}
                transition
                className="d-card d-card-interactive group flex flex-col p-5"
              >
                {card}
              </AppLink>
            ) : (
              <div key={family} className="d-card flex flex-col p-5">{card}</div>
            );
          })}
        </div>
      </section>

      <div className="mt-10 grid grid-cols-12 gap-x-10 gap-y-10">
        <section className="col-span-12 min-[1250px]:col-span-7" aria-labelledby="player-contests">
          <SectionHeader index="02" id="player-contests" title="Materialized contests" detail="Participation proven by the identity crosswalk" />
          {links.isError ? (
            <ErrorPanel error={links.error} onRetry={() => void links.refetch()} />
          ) : links.isPending ? (
            <div className="d-card h-24 p-4"><div className="d-skeleton h-full" /></div>
          ) : appearances.length ? (
            <ul className="d-card divide-y divide-border-subtle overflow-hidden">
              {appearances.map((item, index) => {
                const sessionQuery = sessions[index];
                const session = sessionQuery?.data;
                const participant = verifiedParticipant(session, links.data?.provider_player_ids ?? []);
                const contest = byContest.get(item.contest_id);
                const matchWorld = contest ? resourceWorlds(contest).find((world) => world.world === "match") : null;
                const readiness = contest ? readinessOf(contest) : null;
                const tracking = contest
                  ? (contest.materialized_capabilities ?? []).includes("TRACKING")
                  : session
                    ? session.streams.some((stream) => stream.modality === "tracking")
                    : null;
                const pose = contest
                  ? (contest.materialized_capabilities ?? []).includes("POSE")
                  : session
                    ? session.streams.some((stream) => stream.modality === "pose")
                    : null;
                return (
                  <li key={`${item.dataset_id}/${item.session_id}`} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-4 px-5 py-3">
                    <span className="min-w-0">
                      <span className="block truncate text-[13px] text-text-primary">{contest ? contestTitle(contest) : session?.session.label ?? item.session_id}</span>
                      <span className="mt-0.5 flex items-center gap-3 text-[11px] text-text-muted">
                        <span className="flex items-center gap-1.5"><ReadinessGlyph kind={tracking === null ? "upstream" : tracking ? "ready" : "unavailable"} />{tracking === null ? "Tracking status resolving" : tracking ? "Tracking available" : "Tracking unavailable"}</span>
                        <span className="flex items-center gap-1.5"><ReadinessGlyph kind={pose === null ? "upstream" : pose ? "ready" : "unavailable"} />{pose === null ? "Pose status resolving" : pose ? "Pose available" : "Pose unavailable"}</span>
                        <span>{participant ? `participant ${participant} verified` : sessionQuery?.isPending ? "verifying player identity…" : "player identity unavailable"}</span>
                        {matchWorld?.ready ? <span className="flex items-center gap-1.5"><ReadinessGlyph kind="ready" />Match World ready</span> : readiness ? <ServerReadiness stage={readiness.server} upstream={readiness.upstream} compact /> : <span>{catalog.isPending ? "Resolving Match World readiness" : "Match World readiness unavailable"}</span>}
                      </span>
                    </span>
                    {matchWorld?.ready && participant ? (
                      <AppLink
                        to={matchWorldTarget(item.dataset_id, item.session_id, { subject: participant })}
                        transition
                        className="d-btn border-selected-border text-text-primary"
                      >
                        <WorldGlyph world="match" size="sm" className="text-accent" />
                        Open with player selected
                      </AppLink>
                    ) : null}
                  </li>
                );
              })}
            </ul>
          ) : (
            <StatePanel
              className="d-card min-h-32"
              state="not_materialized"
              title="No materialized contest proves this player's participation."
              detail={`${links.data?.team_contest_ids.length ?? 0} registered contests involve the player's team; participation is unknown until they are materialized.`}
            />
          )}
        </section>
        <section className="col-span-12 min-[1250px]:col-span-5" aria-labelledby="player-identity">
          <SectionHeader index="03" id="player-identity" title="Identity" />
          <div className="d-card space-y-3 p-5 text-[12px]">
            <IdentityRow label="Canonical subject"><CopyableId value={subjectId} label="canonical subject id" /></IdentityRow>
            <IdentityRow label="Authority"><span className="mono break-all text-[11px] text-text-secondary">{links.data?.identity_authority ?? "…"}</span></IdentityRow>
            <IdentityRow label="Provider ids">
              <span className="mono text-[11px] text-text-secondary">
                {links.data ? `${links.data.provider_namespace ?? "—"} · ${links.data.provider_player_ids.join(", ") || "none"}` : "…"}
              </span>
            </IdentityRow>
            <p className="flex items-start gap-2 border-t border-border-subtle pt-3 text-[11.5px] leading-relaxed text-text-muted">
              <ShieldCheck size={13} aria-hidden="true" className="mt-0.5 shrink-0 text-success" />
              Entities are joined only through declared identity crosswalks. No human-performance record is linked to this
              player: none declares an explicit mapping, and display names never merge people.
            </p>
          </div>
        </section>
      </div>
    </Page>
  );
}

function IdentityRow({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-[8rem_minmax(0,1fr)] items-baseline gap-3">
      <span className="t-kicker">{label}</span>
      <span className="min-w-0">{children}</span>
    </div>
  );
}
