import { useQueries, useQuery } from "@tanstack/react-query";
import { useParams, useSearch } from "@tanstack/react-router";
import { ArrowRight, ShieldCheck } from "lucide-react";

import type { SeasonEditionView, SessionDetail } from "@/api/types";
import { AppLink } from "@/components/common/AppLink";
import { CopyableId } from "@/components/common/CopyableId";
import { Page, PageHeader, SectionHeader } from "@/components/common/Page";
import { ReadinessGlyph } from "@/components/common/Readiness";
import { ErrorPanel, StatePanel } from "@/components/common/StatePanel";
import { WorldGlyph } from "@/components/common/WorldGlyph";
import { seasonEditionsQuery, seasonFamilyQuery, seasonLinksQuery, seasonRowsQuery, sessionQuery } from "@/lib/api/queries";
import { contestTitle } from "@/lib/catalog-model";
import { DEFAULT_SEASON_METRICS, formatSeasonValue, shortTeamName, unitSuffix } from "@/lib/season-model";
import type { SeasonFamily } from "@/lib/search";
import { usePublishContext, type Crumb } from "@/lib/state/context";
import { useCatalog } from "@/lib/use-catalog";
import { editionTarget, matchWorldTarget, seasonWorldTarget, teamTarget } from "@/lib/worlds";

/**
 * The match-session participant that is the *same canonical person*, proven by
 * the provider identity crosswalk (never by display name): the season link
 * lists provider player ids in the provider namespace, and the session must
 * register a participant with exactly that id.
 */
export function verifiedParticipant(session: SessionDetail | undefined, providerIds: readonly string[]): string | null {
  if (!session) return null;
  const ids = new Set(providerIds);
  return session.participants.find((participant) => ids.has(participant.subject_id))?.subject_id ?? null;
}

export function PlayerPage() {
  const { subjectId } = useParams({ from: "/data/player/$subjectId" });
  const search = useSearch({ from: "/data/player/$subjectId" });
  const catalog = useCatalog();
  const editions = useQuery(seasonEditionsQuery());
  const datasetId = subjectId.split("/")[0] ?? "";
  const season: SeasonEditionView | null =
    editions.data?.find((item) => item.edition_id === search.edition) ??
    editions.data?.find((item) => item.dataset_id === datasetId) ??
    null;
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
  if (!rowsPending && !firstRow) {
    return <StatePanel state="not_found" title="No season record names this player." detail="Player context is built from canonical season identities; there is no row for this subject in the selected edition." />;
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
            return (
              <AppLink
                key={family}
                to={seasonWorldTarget(editionId ?? "", { player: subjectId, family, ...(teams[0] ? { team: teams[0][0] } : {}) })}
                transition
                className="d-card d-card-interactive group flex flex-col p-5"
              >
                <div className="flex items-center justify-between">
                  <span className="text-[13.5px] font-semibold text-text-primary">{label}</span>
                  <span className="text-[11px] text-text-muted group-hover:text-accent">Distribution <ArrowRight size={11} aria-hidden="true" className="inline" /></span>
                </div>
                {!row ? (
                  <div className="mt-4 space-y-2">{[0, 1, 2].map((key) => <div key={key} className="d-skeleton h-5" />)}</div>
                ) : (
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
                )}
                <p className="mt-4 border-t border-border-subtle pt-2.5 text-[10.5px] text-text-faint">
                  Values only. Percentiles appear in Season World with their named denominator.
                </p>
              </AppLink>
            );
          })}
        </div>
      </section>

      <div className="mt-10 grid grid-cols-12 gap-x-10 gap-y-10">
        <section className="col-span-12 min-[1250px]:col-span-7" aria-labelledby="player-contests">
          <SectionHeader index="02" id="player-contests" title="Materialized contests" detail="Participation proven by the identity crosswalk" />
          {links.isPending ? (
            <div className="d-card h-24 p-4"><div className="d-skeleton h-full" /></div>
          ) : appearances.length ? (
            <ul className="d-card divide-y divide-border-subtle overflow-hidden">
              {appearances.map((item, index) => {
                const session = sessions[index]?.data;
                const participant = verifiedParticipant(session, links.data?.provider_player_ids ?? []);
                const contest = byContest.get(item.contest_id);
                const pose = (contest?.materialized_capabilities ?? []).includes("POSE");
                return (
                  <li key={`${item.dataset_id}/${item.session_id}`} className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-4 px-5 py-3">
                    <span className="min-w-0">
                      <span className="block truncate text-[13px] text-text-primary">{contest ? contestTitle(contest) : session?.session.label ?? item.session_id}</span>
                      <span className="mt-0.5 flex items-center gap-3 text-[11px] text-text-muted">
                        <span className="flex items-center gap-1.5"><ReadinessGlyph kind="ready" />Tracking</span>
                        <span className="flex items-center gap-1.5"><ReadinessGlyph kind={pose ? "ready" : "unavailable"} />{pose ? "Pose available" : "No Pose"}</span>
                        <span>{participant ? `participant ${participant}` : sessions[index]?.isPending ? "verifying identity…" : "participant not verified"}</span>
                      </span>
                    </span>
                    <AppLink
                      to={matchWorldTarget(item.dataset_id, item.session_id, participant ? { subject: participant } : {})}
                      transition
                      className="d-btn border-selected-border text-text-primary"
                    >
                      <WorldGlyph world="match" size="sm" className="text-accent" />
                      {participant ? "Open with player selected" : "Open match"}
                    </AppLink>
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
