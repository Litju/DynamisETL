import { Combobox } from "@base-ui/react/combobox";
import { Popover } from "@base-ui/react/popover";
import { Check, GitCompareArrows, SlidersHorizontal, X } from "lucide-react";
import { useMemo } from "react";

import type { SeasonMetricView, SeasonProfileView, SeasonRowView } from "@/api/types";
import { cn } from "@/lib/cn";
import { groupMetrics, POPULATION_LABELS, shortTeamName } from "@/lib/season-model";
import { SEASON_POPULATIONS, type SeasonPopulation } from "@/lib/search";

const MIN_MATCH_OPTIONS = [null, 3, 5, 10] as const;

/** The explicit denominator: scope + inclusion threshold, always spelled out. */
export function SeasonDenominatorControl({
  population,
  minMatches,
  rows,
  label,
  onPopulation,
  onMinMatches,
}: {
  population: SeasonPopulation;
  minMatches: number | null;
  rows: number | null;
  label: string;
  onPopulation: (population: SeasonPopulation) => void;
  onMinMatches: (minMatches: number | null) => void;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span className="t-label flex items-center gap-1.5">
        Denominator
        <span className="mono text-text-secondary" aria-live="polite">
          {rows === null ? "…" : `${rows} rows`}
        </span>
      </span>
      <div className="flex items-center gap-1.5">
        <div role="radiogroup" aria-label="Comparison population" className="flex h-7 items-center rounded-control border border-border-subtle bg-surface-0 p-0.5">
          {SEASON_POPULATIONS.map((value) => (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={population === value}
              title={POPULATION_LABELS[value]}
              onClick={() => onPopulation(value)}
              className={cn(
                "h-6 rounded-[3px] px-2 text-[11px] transition-colors duration-quick",
                population === value ? "bg-surface-3 text-text-primary" : "text-text-muted hover:text-text-secondary",
              )}
            >
              {value === "position" ? "Position" : value === "edition" ? "Edition" : "Team"}
            </button>
          ))}
        </div>
        <select
          aria-label="Minimum included matches"
          value={minMatches ?? ""}
          onChange={(event) => onMinMatches(event.target.value ? Number(event.target.value) : null)}
          className="h-7 rounded-control border border-border-subtle bg-surface-0 px-1.5 text-[11px] text-text-secondary outline-none focus:border-accent"
        >
          {MIN_MATCH_OPTIONS.map((value) => (
            <option key={value ?? "source"} value={value ?? ""}>
              {value === null ? "Source rule" : `≥ ${value} matches`}
            </option>
          ))}
        </select>
      </div>
      <span className="sr-only">{label}</span>
    </div>
  );
}

/** Registry-driven metric panel picker; selection lives in the URL. */
export function SeasonMetricPicker({
  registry,
  selected,
  onChange,
}: {
  registry: readonly SeasonMetricView[];
  selected: readonly string[];
  onChange: (next: string[]) => void;
}) {
  const groups = useMemo(() => groupMetrics(registry), [registry]);
  const toggle = (column: string) => {
    onChange(selected.includes(column) ? selected.filter((item) => item !== column) : [...selected, column]);
  };
  return (
    <Popover.Root>
      <Popover.Trigger
        className="flex h-7 items-center gap-1.5 rounded-control border border-border-subtle bg-surface-0 px-2 text-[11px] text-text-secondary transition-colors duration-quick hover:border-border-strong hover:text-text-primary"
        aria-label={`Choose metrics (${selected.length} selected)`}
      >
        <SlidersHorizontal size={12} aria-hidden="true" />
        Metrics
        <span className="mono text-text-muted">{selected.length}</span>
      </Popover.Trigger>
      <Popover.Portal>
        <Popover.Positioner side="bottom" align="end" sideOffset={6} className="z-50">
          <Popover.Popup className="season-popover max-h-[min(34rem,75vh)] w-[26rem] overflow-y-auto rounded-panel border border-border-strong bg-surface-1/95 p-3 shadow-overlay backdrop-blur-md">
            <div className="mb-2 flex items-baseline justify-between">
              <Popover.Title className="t-section">Metric panel</Popover.Title>
              <button
                type="button"
                onClick={() => onChange([])}
                className="text-[11px] text-text-muted underline-offset-2 hover:text-text-secondary hover:underline"
              >
                Reset to default
              </button>
            </div>
            <Popover.Description className="t-label mb-3">
              Provider definitions under the versioned SkillCorner registry. Identical names from
              other providers are never merged.
            </Popover.Description>
            {groups.map((group) => (
              <fieldset key={group.group} className="mb-3">
                <legend className="t-label mb-1">{group.group}</legend>
                <div className="grid grid-cols-1 gap-0.5">
                  {group.metrics.map((metric) => {
                    const checked = selected.includes(metric.column);
                    return (
                      <label
                        key={metric.column}
                        className="flex cursor-pointer items-center gap-2 rounded-control px-1.5 py-1 text-[12px] hover:bg-surface-2"
                      >
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => toggle(metric.column)}
                          className="size-3.5 accent-[var(--d-accent)]"
                        />
                        <span className={cn("min-w-0 flex-1 truncate", checked ? "text-text-primary" : "text-text-secondary")}>
                          {metric.label}
                        </span>
                        <span className="shrink-0 text-[10px] text-text-muted">{metric.basis}</span>
                      </label>
                    );
                  })}
                </div>
              </fieldset>
            ))}
          </Popover.Popup>
        </Popover.Positioner>
      </Popover.Portal>
    </Popover.Root>
  );
}

interface CompareItem {
  readonly value: string;
  readonly label: string;
  readonly detail: string;
}

/** Choose a second player; they are ranked against the first player's population. */
export function SeasonCompareControl({
  rows,
  excludeSubject,
  compareId,
  compare,
  pending,
  onChange,
}: {
  rows: readonly SeasonRowView[];
  excludeSubject: string;
  compareId: string | null;
  compare: SeasonProfileView | null;
  pending: boolean;
  onChange: (subjectId: string | null) => void;
}) {
  const items = useMemo<CompareItem[]>(() => {
    const seen = new Map<string, CompareItem>();
    for (const row of rows) {
      if (row.subject_id === excludeSubject || seen.has(row.subject_id)) continue;
      seen.set(row.subject_id, {
        value: row.subject_id,
        label: row.player_name,
        detail: `${shortTeamName(row.team_name)} · ${row.position_group}`,
      });
    }
    return [...seen.values()].sort((a, b) => a.label.localeCompare(b.label));
  }, [excludeSubject, rows]);
  const value = items.find((item) => item.value === compareId) ?? null;

  if (compareId) {
    return (
      <div className="flex shrink-0 flex-col items-end gap-1">
        <span className="t-label">Compared with</span>
        <span className="flex items-center gap-2 rounded-full border border-quality-warning/60 py-1 pl-2.5 pr-1 text-[12px] text-text-primary">
          <span aria-hidden="true" className="inline-block size-2 rotate-45 border-2 border-quality-warning" />
          {compare?.row.player_name ?? value?.label ?? (pending ? "Loading…" : compareId)}
          <button
            type="button"
            onClick={() => onChange(null)}
            aria-label="Remove comparison"
            className="flex size-5 items-center justify-center rounded-full text-text-muted hover:bg-surface-3 hover:text-text-primary"
          >
            <X size={11} aria-hidden="true" />
          </button>
        </span>
        {compare ? (
          <span className="text-[10px] text-text-muted">
            same denominator · {compare.population.rows} rows
          </span>
        ) : null}
      </div>
    );
  }

  return (
    <Combobox.Root
      items={items}
      value={value}
      onValueChange={(next) => onChange(next ? next.value : null)}
      itemToStringLabel={(item) => item.label}
    >
      <div className="flex shrink-0 flex-col items-end gap-1">
        <label className="t-label flex items-center gap-1" htmlFor="season-compare">
          <GitCompareArrows size={11} aria-hidden="true" /> Compare player
        </label>
        <Combobox.Input
          id="season-compare"
          placeholder="Search a player…"
          className="h-7 w-52 rounded-control border border-border-subtle bg-surface-0 px-2 text-[12px] text-text-primary outline-none placeholder:text-text-muted focus:border-accent"
        />
      </div>
      <Combobox.Portal>
        <Combobox.Positioner sideOffset={4} align="end" className="z-50">
          <Combobox.Popup className="max-h-72 w-64 overflow-y-auto rounded-panel border border-border-strong bg-surface-1/95 p-1 shadow-overlay backdrop-blur-md">
            <Combobox.Empty className="px-2 py-2 text-[12px] text-text-muted">No player found.</Combobox.Empty>
            <Combobox.List>
              {(item: CompareItem) => (
                <Combobox.Item
                  key={item.value}
                  value={item}
                  className="flex cursor-pointer items-center gap-2 rounded-control px-2 py-1.5 text-[12px] text-text-secondary outline-none data-[highlighted]:bg-surface-3 data-[highlighted]:text-text-primary"
                >
                  <Combobox.ItemIndicator>
                    <Check size={11} aria-hidden="true" />
                  </Combobox.ItemIndicator>
                  <span className="min-w-0 flex-1 truncate">{item.label}</span>
                  <span className="shrink-0 text-[10px] text-text-muted">{item.detail}</span>
                </Combobox.Item>
              )}
            </Combobox.List>
          </Combobox.Popup>
        </Combobox.Positioner>
      </Combobox.Portal>
    </Combobox.Root>
  );
}
