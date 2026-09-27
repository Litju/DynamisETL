import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { ArrowUpRight, Download, ExternalLink } from "lucide-react";
import { useMemo, type ReactNode } from "react";

import type { SeasonFamilyView, SeasonMetricView, SeasonProfileView, SportsCatalogMatchView } from "@/api/types";
import { MeasurementClassBadge } from "@/components/common/Badges";
import { CopyableId } from "@/components/common/CopyableId";
import { seasonLinksQuery, sportsCatalogMatchesQuery } from "@/lib/api/queries";
import { buildSeasonReport } from "@/lib/season-model";

function matchLabel(match: SportsCatalogMatchView | undefined, fallback: string): string {
  if (!match) return fallback;
  const home = match.teams.find((team) => team.side === "home") ?? match.teams[0];
  const away = match.teams.find((team) => team.side === "away") ?? match.teams[1];
  if (home && away) return `${home.display_name} vs ${away.display_name}`;
  return match.label ?? fallback;
}

function matchDate(match: SportsCatalogMatchView | undefined): string | null {
  const value = match?.scheduled_start_at ?? match?.actual_start_at;
  return value ? value.slice(0, 10) : null;
}

/**
 * Evidence rail: what the focused metric means, which population and artifact
 * produced it, who may use it, and which contests the player can legitimately be
 * opened in. Everything technical is one level below the human-readable fact.
 */
export function SeasonEvidence({
  familyView,
  focus,
  profile,
  compare,
  registry,
  playerId,
}: {
  familyView: SeasonFamilyView;
  focus: string | null;
  profile: SeasonProfileView | null;
  compare: SeasonProfileView | null;
  registry: readonly SeasonMetricView[];
  playerId: string | null;
}) {
  const edition = familyView.edition;
  const family = familyView.family;
  const metric = registry.find((item) => item.column === focus) ?? null;

  const downloadReport = () => {
    if (!profile) return;
    const text = buildSeasonReport({ profile, registry, compare, url: window.location.href });
    const blob = new Blob([text], { type: "text/markdown;charset=utf-8" });
    const href = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = href;
    anchor.download = `season-profile-${profile.row.player_name.replace(/\s+/gu, "-").toLowerCase()}-${family.family}.md`;
    anchor.click();
    URL.revokeObjectURL(href);
  };

  return (
    <aside className="season-evidence min-h-0 overflow-y-auto border-l border-border-subtle bg-surface-1" aria-label="Metric evidence">
      <EvidenceSection title="Metric">
        {metric ? (
          <>
            <p className="text-[14px] font-medium text-text-primary">{metric.label}</p>
            <p className="t-body mt-1">{metric.definition}.</p>
            <dl className="mt-3 grid grid-cols-[6.5rem_1fr] gap-x-2 gap-y-1.5 text-[11px]">
              <Fact term="Unit">{metric.unit}</Fact>
              <Fact term="Basis">{metric.basis}</Fact>
              <Fact term="Class">
                <MeasurementClassBadge measurementClass={edition.measurement_class} compact />
              </Fact>
              <Fact term="Metric id">
                <CopyableId value={metric.metric_id} label="metric id" />
              </Fact>
            </dl>
            {edition.glossary_url ? (
              <a
                href={edition.glossary_url}
                target="_blank"
                rel="noreferrer"
                className="mt-2 inline-flex items-center gap-1 text-[11px] text-accent hover:underline"
              >
                Provider glossary <ExternalLink size={10} aria-hidden="true" />
              </a>
            ) : null}
          </>
        ) : (
          <p className="t-body">Select a metric to read its definition.</p>
        )}
      </EvidenceSection>

      <EvidenceSection title="Grain & population">
        <dl className="grid grid-cols-[6.5rem_1fr] gap-x-2 gap-y-1.5 text-[11px]">
          <Fact term="Grain">
            <span className="mono">{family.grain_kind}</span>
          </Fact>
          <Fact term="Axes">{family.grain_axes.join(" × ")}</Fact>
          <Fact term="Edition">
            {edition.competition_name} {edition.edition_label}
          </Fact>
          <Fact term="Rows">
            <span className="mono">{familyView.population_rows}</span> rows ·{" "}
            <span className="mono">{familyView.population_subjects}</span> players
          </Fact>
          {family.source_population_rows !== null ? (
            <Fact term="Source rows">
              <span className="mono">{family.source_population_rows}</span> (reconciled)
            </Fact>
          ) : null}
          {profile ? (
            <Fact term="Denominator">
              {profile.population.label} · <span className="mono">{profile.population.rows}</span>
            </Fact>
          ) : null}
        </dl>
        <p className="t-label mt-2">{edition.inclusion_rule}</p>
        {profile ? <p className="t-label mt-1">{profile.percentile_method}</p> : null}
      </EvidenceSection>

      {playerId ? <MatchLinks editionId={edition.edition_id} subjectId={playerId} /> : null}

      <EvidenceSection title="Provenance">
        <dl className="grid grid-cols-[6.5rem_1fr] gap-x-2 gap-y-1.5 text-[11px]">
          <Fact term="Provider">{edition.provider}</Fact>
          <Fact term="Artifact">
            <CopyableId value={family.artifact_id} label="artifact id" />
          </Fact>
          <Fact term="SHA-256">
            <CopyableId value={family.checksum_sha256} label="artifact checksum" />
          </Fact>
          {family.run_id ? (
            <Fact term="Run">
              <Link to="/runs" search={{ run: family.run_id }} className="text-accent hover:underline">
                <CopyableId value={family.run_id} label="run id" />
              </Link>
            </Fact>
          ) : null}
          {family.source_revision ? (
            <Fact term="Revision">
              <CopyableId value={family.source_revision} label="source revision" />
            </Fact>
          ) : null}
          <Fact term="Registry">
            <span className="mono">{edition.registry_version}</span>
          </Fact>
        </dl>
      </EvidenceSection>

      <EvidenceSection title="Rights">
        <p className="t-body">{edition.license.notice}</p>
      </EvidenceSection>

      <div className="px-4 pb-5 pt-1">
        <button
          type="button"
          onClick={downloadReport}
          disabled={!profile}
          className="flex h-8 w-full items-center justify-center gap-2 rounded-control border border-border-strong text-[12px] text-text-secondary transition-colors duration-quick enabled:hover:border-accent enabled:hover:text-text-primary disabled:cursor-not-allowed disabled:opacity-50"
        >
          <Download size={13} aria-hidden="true" />
          Season profile report
        </button>
        {!profile ? <p className="t-label mt-1.5 text-center">Select a player to generate a report.</p> : null}
      </div>
    </aside>
  );
}

function MatchLinks({ editionId, subjectId }: { editionId: string; subjectId: string }) {
  const links = useQuery(seasonLinksQuery(editionId, subjectId));
  const matches = useQuery(sportsCatalogMatchesQuery());
  const byContest = useMemo(
    () => new Map((matches.data ?? []).map((match) => [match.contest_id, match])),
    [matches.data],
  );
  const appearances = links.data?.appearances ?? [];
  const appearanceContests = new Set(appearances.map((item) => item.contest_id));
  const teamOnly = (links.data?.team_contest_ids ?? []).filter((id) => !appearanceContests.has(id));

  return (
    <EvidenceSection title="Match linkage">
      {links.isPending ? (
        <p className="t-label">Resolving identity…</p>
      ) : links.isError ? (
        <p className="t-label">Match linkage is unavailable.</p>
      ) : (
        <>
          {appearances.length > 0 ? (
            <ul className="flex flex-col gap-1">
              {appearances.map((item) => {
                const match = byContest.get(item.contest_id);
                return (
                  <li key={`${item.dataset_id}/${item.session_id}`}>
                    <Link
                      to="/lab/$datasetId/$sessionId"
                      params={{ datasetId: item.dataset_id, sessionId: item.session_id }}
                      search={{ view: "matchlab" }}
                      className="group flex items-center gap-2 rounded-control border border-border-subtle px-2 py-1.5 transition-colors duration-quick hover:border-accent"
                    >
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-[12px] text-text-primary">
                          {matchLabel(match, `Match ${item.session_id}`)}
                        </span>
                        <span className="block text-[10px] text-text-muted">
                          {matchDate(match) ?? "date unavailable"} · appeared · ready in MatchLab
                        </span>
                      </span>
                      <ArrowUpRight size={13} aria-hidden="true" className="text-text-muted group-hover:text-accent" />
                    </Link>
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="t-body">
              No materialized match proves this player's participation
              {links.data?.provider_player_ids.length ? "" : " (no provider identity crosswalk yet)"}.
            </p>
          )}
          {teamOnly.length > 0 ? (
            <p className="t-label mt-2">
              {teamOnly.length} other registered contest{teamOnly.length === 1 ? " involves" : "s involve"}{" "}
              this player's team. Participation is unknown until they are materialized; season values are
              never decomposed into matches.
            </p>
          ) : null}
          <p className="t-evidence mt-2 break-all">identity: {links.data?.identity_authority}</p>
        </>
      )}
    </EvidenceSection>
  );
}

function EvidenceSection({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="border-b border-border-subtle px-4 py-3.5">
      <h3 className="t-section mb-2">{title}</h3>
      {children}
    </section>
  );
}

function Fact({ term, children }: { term: string; children: ReactNode }) {
  return (
    <>
      <dt className="text-text-muted">{term}</dt>
      <dd className="min-w-0 text-text-secondary">{children}</dd>
    </>
  );
}
