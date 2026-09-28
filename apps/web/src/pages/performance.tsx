import { useQuery } from "@tanstack/react-query";
import { useNavigate, useSearch } from "@tanstack/react-router";
import { ArrowRight, Search } from "lucide-react";
import { useMemo } from "react";

import type { SessionDetail, SessionSummary, TrialView } from "@/api/types";
import { AppLink } from "@/components/common/AppLink";
import { ModalityBadge } from "@/components/common/Badges";
import { Page, PageHeader, SectionHeader } from "@/components/common/Page";
import { ReadinessGlyph } from "@/components/common/Readiness";
import { ErrorPanel, StatePanel } from "@/components/common/StatePanel";
import { VirtualList } from "@/components/common/VirtualList";
import { WorldGlyph } from "@/components/common/WorldGlyph";
import { sessionQuery, sessionsQuery } from "@/lib/api/queries";
import { readinessOf, type StudyNode } from "@/lib/catalog-model";
import type { PerformanceSearch } from "@/lib/search";
import { usePublishContext, type Crumb } from "@/lib/state/context";
import { METADATA_STALE_MS, useCatalog } from "@/lib/use-catalog";
import { performanceWorldTarget, studyTarget } from "@/lib/worlds";

/** Readable trial facts from a provider label of `key=value; …` pairs. */
export function trialFacts(trial: Pick<TrialView, "trial_id" | "label">): { condition: string | null; index: string | null } {
  const pairs = new Map<string, string>();
  for (const part of (trial.label ?? "").split(";")) {
    const [key, value] = part.split("=").map((item) => item.trim());
    if (key && value) pairs.set(key, value);
  }
  const index = /-t(\d+)$/u.exec(trial.trial_id)?.[1] ?? null;
  return { condition: pairs.get("condition") ?? null, index };
}

export function PerformanceEntry() {
  const search = useSearch({ from: "/performance" });
  const catalog = useCatalog();
  const study = catalog.studies.find((item) => item.datasetId === search.dataset) ?? null;

  const crumbs: Crumb[] = [
    { key: "domain", label: "Human Performance", kind: "Domain", target: { to: "/data", search: { domain: "human" } } },
    ...(study ? [{ key: "study", label: study.shortName, kind: "Study", target: studyTarget(study.datasetId) }] : []),
    ...(search.session ? [{ key: "session", label: search.session, kind: "Session" }] : []),
  ];
  usePublishContext({
    owner: `performance-entry:${search.dataset ?? ""}:${search.session ?? ""}`,
    world: "performance",
    crumbs,
  });

  if (catalog.isError) return <ErrorPanel error={catalog.error} onRetry={catalog.refetch} />;
  if (!search.dataset || (!catalog.isPending && !study)) return <StudyChooser studies={catalog.studies} pending={catalog.isPending} missing={Boolean(search.dataset)} />;
  if (!study) return <Page label="Performance World"><div className="d-skeleton h-10 w-80" /></Page>;
  return <StudyContext study={study} search={search} />;
}

function StudyChooser({ studies, pending, missing }: { studies: readonly StudyNode[]; pending: boolean; missing: boolean }) {
  return (
    <Page label="Performance World">
      <PageHeader
        kicker={<><WorldGlyph world="performance" size="sm" className="text-accent" /> Performance World</>}
        title="Choose a study"
        lede="Force, IMU, GNSS and LPT trials. The Performance World is organised Study → Session → Trial → Subject → Signal; no competition or team semantics are imposed on laboratory data."
      />
      {missing ? <p className="mt-4 text-[12px] text-warning">That study is not in the catalog.</p> : null}
      <ul className="mt-8 grid grid-cols-1 gap-3 min-[1100px]:grid-cols-2">
        {pending ? [0, 1].map((index) => <li key={index} className="d-skeleton h-28 rounded-[10px]" />) : null}
        {studies.map((study) => (
          <li key={study.datasetId}>
            <AppLink to={studyTarget(study.datasetId)} transition className="d-card d-card-interactive group flex items-center gap-5 p-5">
              <WorldGlyph world="performance" size="lg" className="text-text-muted group-hover:text-accent" />
              <span className="min-w-0 flex-1">
                <span className="block truncate text-[14px] font-semibold text-text-primary">{study.shortName}</span>
                <span className="mt-0.5 block truncate text-[11.5px] text-text-muted">{study.provider} · {study.modalities.map((modality) => modality.toUpperCase()).join(" · ")}</span>
                <span className="mt-2 flex items-center gap-1.5 text-[11.5px] text-text-secondary">
                  <ReadinessGlyph kind={study.ready ? "ready" : "upstream"} />
                  {study.ready ? `${study.readySessions} of ${study.sessionCount} sessions ready` : "Upstream available · not materialized"}
                </span>
              </span>
              <ArrowRight size={14} aria-hidden="true" className="text-text-faint group-hover:text-accent" />
            </AppLink>
          </li>
        ))}
      </ul>
    </Page>
  );
}

function StudyContext({ study, search }: { study: StudyNode; search: PerformanceSearch }) {
  const navigate = useNavigate();
  const sessions = useQuery({ ...sessionsQuery(study.datasetId), staleTime: METADATA_STALE_MS });
  const selected = search.session ?? null;
  const readyIds = useMemo(
    () => new Set(study.sessions.filter((item) => readinessOf(item).server === "ready").flatMap((item) => (item.session_id ? [item.session_id] : []))),
    [study.sessions],
  );
  const needle = search.q?.toLocaleLowerCase().trim() ?? "";
  const rows = (sessions.data ?? []).filter((session) => !needle || `${session.session_id} ${session.label ?? ""}`.toLocaleLowerCase().includes(needle));
  const update = (patch: Partial<PerformanceSearch>, replace = false) =>
    void navigate({ to: "/performance", search: (previous: PerformanceSearch) => ({ ...previous, ...patch }), replace });

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="d-atmosphere shrink-0 border-b border-border-subtle px-8 pb-6 pt-7 max-[1400px]:px-6">
        <PageHeader
          kicker={<><WorldGlyph world="performance" size="sm" className="text-accent" /> Performance World · Study</>}
          title={study.shortName}
          meta={
            <>
              <span className="flex items-center gap-1.5">{study.modalities.map((modality) => <ModalityBadge key={modality} modality={modality} />)}</span>
              <span className="text-[12px] text-text-muted">{study.provider} · {study.license ?? "licence unclear"}{study.noncommercial ? " · non-commercial" : ""}</span>
              <span className="text-[12px] text-text-muted">
                <span className="mono text-text-secondary">{study.sessionCount}</span> sessions · <span className="mono text-text-secondary">{study.subjectCount}</span> subjects · <span className="mono text-text-secondary">{study.trialCount}</span> trials
              </span>
            </>
          }
          actions={<AppLink to={{ to: "/compare" }} className="d-btn">Compare sessions</AppLink>}
        />
      </header>
      <div className="grid min-h-0 flex-1 grid-cols-[22rem_minmax(0,1fr)] max-[1400px]:grid-cols-[18rem_minmax(0,1fr)]">
        <aside className="flex min-h-0 flex-col border-r border-border-subtle bg-surface-0" aria-label="Sessions">
          <div className="border-b border-border-subtle p-3">
            <label className="relative flex items-center">
              <Search size={13} aria-hidden="true" className="pointer-events-none absolute left-2.5 text-text-muted" />
              <input value={search.q ?? ""} onChange={(event) => update({ q: event.target.value || undefined }, true)} placeholder="Filter sessions" aria-label="Filter sessions" className="d-input w-full pl-8" />
            </label>
          </div>
          <SessionList rows={rows} selected={selected} readyIds={readyIds} pending={sessions.isPending} onSelect={(sessionId) => update({ session: sessionId })} />
        </aside>
        <section className="min-h-0 overflow-y-auto" aria-label="Session context">
          {selected ? (
            <SessionPanel datasetId={study.datasetId} sessionId={selected} ready={readyIds.size === 0 || readyIds.has(selected)} />
          ) : (
            <StatePanel state="empty" title="Choose a session to see its trials." detail="Session and trial metadata load here; signal windows load only when a trial opens in the Performance World." />
          )}
        </section>
      </div>
    </div>
  );
}

function SessionList({
  rows,
  selected,
  readyIds,
  pending,
  onSelect,
}: {
  rows: readonly SessionSummary[];
  selected: string | null;
  readyIds: ReadonlySet<string>;
  pending: boolean;
  onSelect: (sessionId: string) => void;
}) {
  return (
    <VirtualList
      items={rows}
      rowHeight={52}
      role="listbox"
      ariaLabel="Sessions"
      className="min-h-0 flex-1"
      getKey={(session) => session.session_id}
      renderRow={(session, _index, style) => {
        const active = session.session_id === selected;
        const ready = readyIds.size === 0 || readyIds.has(session.session_id);
        return (
          <button
            type="button"
            role="option"
            aria-selected={active}
            data-selected={active}
            onClick={() => onSelect(session.session_id)}
            style={style}
            className="d-row flex w-full flex-col justify-center border-b border-border-subtle px-4 text-left"
          >
            <span className="flex items-center justify-between gap-2">
              <span className="mono text-[12px] text-text-primary">{session.session_id}</span>
              <ReadinessGlyph kind={ready ? "ready" : "upstream"} />
            </span>
            <span className="text-[11px] text-text-muted">
              {session.trial_count} trials · {session.stream_count} streams · {session.participant_count} subject{session.participant_count === 1 ? "" : "s"}
            </span>
          </button>
        );
      }}
    >
      {pending ? <div className="space-y-2 p-3">{[0, 1, 2, 3, 4].map((index) => <div key={index} className="d-skeleton h-9" />)}</div> : null}
    </VirtualList>
  );
}

function SessionPanel({ datasetId, sessionId, ready }: { datasetId: string; sessionId: string; ready: boolean }) {
  const detail = useQuery(sessionQuery(datasetId, sessionId));
  if (detail.isPending) {
    return <div className="space-y-3 p-8" aria-busy="true"><div className="d-skeleton h-6 w-72" /><div className="d-skeleton h-40" /></div>;
  }
  if (detail.isError) return <ErrorPanel error={detail.error} onRetry={() => void detail.refetch()} />;
  return <SessionTrials detail={detail.data} ready={ready} />;
}

function SessionTrials({ detail, ready }: { detail: SessionDetail; ready: boolean }) {
  const byCondition = new Map<string, TrialView[]>();
  for (const trial of detail.trials) {
    const condition = trialFacts(trial).condition ?? "Trials";
    byCondition.set(condition, [...(byCondition.get(condition) ?? []), trial]);
  }
  const participant = detail.participants[0];
  return (
    <div key={detail.session.session_id} className="d-reveal px-8 py-7 max-[1400px]:px-6">
      <div className="flex items-start justify-between gap-6">
        <div className="min-w-0">
          <div className="t-kicker">Session</div>
          <h2 className="mono mt-1.5 text-[20px] font-medium text-text-primary">{detail.session.session_id}</h2>
          <p className="mt-1 max-w-2xl text-[12px] text-text-muted">{detail.session.label}</p>
          {participant ? (
            <p className="mt-2 text-[11.5px] text-text-muted">
              Subject <span className="mono text-text-secondary">{participant.subject_id}</span>
              {participant.cohort ? ` · ${participant.cohort}` : ""}
            </p>
          ) : null}
        </div>
        {ready && detail.trials[0] ? (
          <AppLink
            to={performanceWorldTarget(detail.dataset_id, detail.session.session_id, { trial: detail.trials[0].trial_id })}
            transition
            className="d-btn d-btn-primary shrink-0"
          >
            <WorldGlyph world="performance" size="sm" /> Open first trial
          </AppLink>
        ) : null}
      </div>
      {!ready ? (
        <StatePanel className="mt-6 d-card min-h-28" state="not_materialized" title="This session is registered but its signals are not materialized." detail="Trials are listed from metadata; the signal workbench opens once canonical streams exist." />
      ) : null}
      {[...byCondition.entries()].map(([condition, trials]) => (
        <section key={condition} className="mt-7" aria-label={`Condition ${condition}`}>
          <SectionHeader title={condition === "Trials" ? "Trials" : `Condition · ${condition}`} detail={`${trials.length} trials`} />
          <ul className="d-card divide-y divide-border-subtle overflow-hidden">
            {trials.map((trial) => {
              const streams = detail.streams.filter((stream) => stream.trial_id === trial.trial_id);
              const facts = trialFacts(trial);
              return (
                <li key={trial.trial_id}>
                  <AppLink
                    to={performanceWorldTarget(detail.dataset_id, detail.session.session_id, { trial: trial.trial_id, ...(streams[0] ? { stream: streams[0].stream_id } : {}) })}
                    transition
                    className="d-row group grid grid-cols-[4.5rem_minmax(0,1fr)_minmax(0,1fr)_1rem] items-center gap-4 px-5 py-2.5 text-[12.5px]"
                    aria-disabled={!ready}
                  >
                    <span className="mono text-text-primary">T{facts.index ?? "—"}</span>
                    <span className="mono truncate text-[11px] text-text-muted" title={trial.label ?? trial.trial_id}>{trial.trial_id}</span>
                    <span className="flex flex-wrap items-center gap-1.5">
                      {streams.map((stream) => (
                        <span key={stream.stream_id} className="flex items-center gap-1 text-[11px] text-text-muted">
                          <ModalityBadge modality={stream.modality} />
                          {stream.nominal_sampling_rate_hz ? <span className="mono">{stream.nominal_sampling_rate_hz} Hz</span> : null}
                        </span>
                      ))}
                    </span>
                    <ArrowRight size={12} aria-hidden="true" className="text-text-faint group-hover:text-accent" />
                  </AppLink>
                </li>
              );
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}
