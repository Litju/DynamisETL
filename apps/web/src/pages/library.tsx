import { useQuery } from "@tanstack/react-query";
import { ArrowRight, ExternalLink } from "lucide-react";
import { useMemo, type ReactNode } from "react";

import { AppLink } from "@/components/common/AppLink";
import { MeasurementClassBadge } from "@/components/common/Badges";
import { Page, PageHeader, SectionHeader } from "@/components/common/Page";
import { LibraryNav } from "@/components/shell/LibraryNav";
import { api, unwrap } from "@/lib/api/client";
import { metricDefinitionsQuery, rightsQuery, seasonEditionsQuery } from "@/lib/api/queries";
import { seasonWorldTarget, type LinkTarget } from "@/lib/worlds";

const FAMILY_LABEL: Record<string, string> = {
  pose: "Pose kinematics",
  locomotor: "Locomotor effort",
  cmj: "Countermovement jump",
  imu: "Inertial",
  cross_sensor: "Cross-sensor agreement",
};

function familyOf(metricId: string): string {
  const head = metricId.split(".")[0] ?? metricId;
  if (FAMILY_LABEL[head]) return head;
  if (head.startsWith("gymaware") || head.startsWith("vision")) return "lpt";
  if (head.startsWith("source_")) return "source";
  return head;
}

const EXTRA_FAMILY_LABEL: Record<string, string> = { lpt: "Linear position transducer", source: "Source-reported" };

/** Library home: definitions and scientific authority, never observations. */
export function LibraryHome() {
  const definitions = useQuery(metricDefinitionsQuery());
  const tactical = useQuery({
    queryKey: ["tactical", "methodology"] as const,
    queryFn: async () => unwrap(await api.GET("/api/tactical/methodology")),
    staleTime: 5 * 60_000,
  });
  const seasons = useQuery(seasonEditionsQuery());
  const rights = useQuery(rightsQuery());
  const runs = useQuery({
    queryKey: ["runs", "count"] as const,
    queryFn: async () => unwrap(await api.GET("/api/runs", { params: { query: { limit: 1 } } })),
    staleTime: 60_000,
  });

  const families = useMemo(() => {
    const map = new Map<string, { count: number; classes: Set<string> }>();
    for (const entry of definitions.data ?? []) {
      const key = familyOf(entry.metric_id);
      const item = map.get(key) ?? { count: 0, classes: new Set<string>() };
      item.count += 1;
      item.classes.add(entry.measurement_class);
      map.set(key, item);
    }
    return [...map.entries()].sort((a, b) => b[1].count - a[1].count);
  }, [definitions.data]);

  const algorithms = useMemo(() => {
    const metrics = ((tactical.data as { metrics?: { algorithm_id: string; algorithm_version: string; level: string; name: string; measurement_class: string }[] } | undefined)?.metrics) ?? [];
    const map = new Map<string, { version: string; levels: Set<string>; names: string[]; classes: Set<string> }>();
    for (const metric of metrics) {
      const item = map.get(metric.algorithm_id) ?? { version: metric.algorithm_version, levels: new Set<string>(), names: [], classes: new Set<string>() };
      item.levels.add(metric.level);
      item.names.push(metric.name);
      item.classes.add(metric.measurement_class);
      map.set(metric.algorithm_id, item);
    }
    return [...map.entries()];
  }, [tactical.data]);

  return (
    <div className="flex h-full min-h-0 flex-col">
      <LibraryNav />
      <Page label="Library">
        <PageHeader
          kicker={<>Library · definitions and authority</>}
          title="Library"
          lede="What a result means, how it was computed and under which rights. The Library holds definitions, methods, provenance and licences; measurements, contests and trials live in Data."
        />

        <div className="mt-9 grid grid-cols-1 gap-3 min-[1100px]:grid-cols-3">
          <EntryCard
            to={{ to: "/methods" }}
            kicker="Metrics & methodology"
            value={definitions.data ? String(definitions.data.length) : null}
            unit="metric definitions"
            detail="Definition, unit, measurement class, algorithm revision, parameters and the exact lineage of any served value."
          />
          <EntryCard
            to={{ to: "/runs" }}
            kicker="Runs & provenance"
            value={runs.data ? runs.data.total.toLocaleString("en-US") : null}
            unit="processing runs"
            detail="Every served value resolves to one run: code revision, parameter hash and input checksums."
          />
          <EntryCard
            to={{ to: "/quality" }}
            kicker="Quality & rights"
            value={rights.data ? String(rights.data.policies.length) : null}
            unit="licence policies"
            detail="Validation findings and the licence terms — attribution, non-commercial and local-only boundaries."
          />
        </div>

        <section className="mt-12" aria-labelledby="lib-families">
          <SectionHeader index="01" id="lib-families" title="Metric families" detail="Pipeline and source definitions served by this data plane" />
          <ul className="d-card divide-y divide-border-subtle overflow-hidden">
            {definitions.isPending ? <li className="p-4"><div className="d-skeleton h-24" /></li> : null}
            {families.map(([family, item]) => (
              <li key={family} className="grid grid-cols-[minmax(0,1fr)_6rem_minmax(0,1fr)_1rem] items-center gap-4 px-5 py-2.5 text-[12.5px]">
                <span className="text-text-primary">{FAMILY_LABEL[family] ?? EXTRA_FAMILY_LABEL[family] ?? family}</span>
                <span className="mono text-right text-text-secondary">{item.count}</span>
                <span className="flex flex-wrap gap-2">{[...item.classes].map((value) => <MeasurementClassBadge key={value} measurementClass={value} compact />)}</span>
                <AppLink to={{ to: "/methods" }} aria-label={`Browse ${family} definitions`} className="text-text-faint hover:text-accent"><ArrowRight size={12} aria-hidden="true" /></AppLink>
              </li>
            ))}
          </ul>
        </section>

        <div className="mt-12 grid grid-cols-12 gap-x-10 gap-y-10">
          <section className="col-span-12 min-[1250px]:col-span-7" aria-labelledby="lib-algorithms">
            <SectionHeader index="02" id="lib-algorithms" title="Methods & algorithms" detail="Tactical method contract (RES-110), by algorithm revision" />
            <ul className="d-card divide-y divide-border-subtle overflow-hidden">
              {tactical.isPending ? <li className="p-4"><div className="d-skeleton h-24" /></li> : null}
              {algorithms.map(([algorithm, item]) => (
                <li key={algorithm} className="px-5 py-3">
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="mono text-[12px] text-text-primary">{algorithm} <span className="text-text-faint">v{item.version}</span></span>
                    <span className="flex items-center gap-2 text-[11px] text-text-muted">
                      Level {[...item.levels].sort().join(" · ")}
                      {[...item.classes].map((value) => <MeasurementClassBadge key={value} measurementClass={value} compact />)}
                    </span>
                  </div>
                  <p className="mt-1 line-clamp-1 text-[11.5px] text-text-muted">{item.names.join(" · ")}</p>
                </li>
              ))}
            </ul>
          </section>
          <section className="col-span-12 min-[1250px]:col-span-5" aria-labelledby="lib-registries">
            <SectionHeader index="03" id="lib-registries" title="Season metric registries" detail="Provider definitions and inclusion rules" />
            <ul className="d-card divide-y divide-border-subtle overflow-hidden">
              {seasons.isPending ? <li className="p-4"><div className="d-skeleton h-20" /></li> : null}
              {(seasons.data ?? []).map((edition) => (
                <li key={edition.edition_id} className="px-5 py-3">
                  <div className="flex items-baseline justify-between gap-3">
                    <AppLink to={seasonWorldTarget(edition.edition_id)} className="text-[12.5px] font-medium text-text-primary hover:text-accent">
                      {edition.competition_name} {edition.edition_label}
                    </AppLink>
                    <MeasurementClassBadge measurementClass={edition.measurement_class} compact />
                  </div>
                  <p className="mt-1 text-[11.5px] text-text-muted">{edition.families.map((family) => family.label).join(" · ")} · {edition.registry_version}</p>
                  <p className="mt-1 line-clamp-2 text-[11px] text-text-faint">{edition.inclusion_rule}</p>
                  {edition.glossary_url ? (
                    <a href={edition.glossary_url} target="_blank" rel="noreferrer" className="mt-1.5 inline-flex items-center gap-1 text-[11px] text-accent hover:underline">
                      Provider glossary <ExternalLink size={10} aria-hidden="true" />
                    </a>
                  ) : null}
                </li>
              ))}
            </ul>
          </section>
        </div>
      </Page>
    </div>
  );
}

function EntryCard({ to, kicker, value, unit, detail }: { to: LinkTarget; kicker: string; value: string | null; unit: string; detail: ReactNode }) {
  return (
    <AppLink to={to} className="d-card d-card-interactive group flex flex-col p-5">
      <span className="t-kicker">{kicker}</span>
      <span className="mt-4 flex items-baseline gap-2">
        {value === null ? <span className="d-skeleton inline-block h-7 w-16" /> : <span className="mono text-[26px] font-medium leading-none tracking-[-0.02em] text-text-primary">{value}</span>}
        <span className="text-[12px] text-text-muted">{unit}</span>
      </span>
      <span className="mt-3 text-[12px] leading-relaxed text-text-muted">{detail}</span>
      <span className="mt-4 flex items-center gap-1 text-[11.5px] text-text-muted group-hover:text-accent">Open <ArrowRight size={12} aria-hidden="true" /></span>
    </AppLink>
  );
}
