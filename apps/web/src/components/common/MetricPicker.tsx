import { useId, useMemo, useState } from "react";

import type { MetricCatalogEntry } from "@/api/types";
import { cn } from "@/lib/cn";

/**
 * Metric discovery from the registered vocabulary.
 *
 * A reader should never have to know an internal metric id to start an
 * analysis. The list is the real catalog, filtered as they type across the
 * readable name, the id and the datasets that serve it, and each option shows
 * its unit and how many values exist — so a metric with nothing behind it is
 * visible as such rather than silently yielding an empty surface.
 */
export function MetricPicker({
  label,
  value,
  options,
  isPending,
  allowEmpty = false,
  onChange,
}: {
  label: string;
  value: string | null;
  options: readonly MetricCatalogEntry[];
  isPending: boolean;
  allowEmpty?: boolean;
  onChange: (metricId: string | null) => void;
}) {
  const listId = useId();
  const inputId = useId();
  const [draft, setDraft] = useState<string | null>(null);
  const text = draft ?? value ?? "";

  const selected = useMemo(
    () => options.find((entry) => entry.metric_id === value) ?? null,
    [options, value],
  );

  const matches = useMemo(() => {
    const needle = text.trim().toLowerCase();
    if (needle.length === 0) return options.slice(0, 60);
    return options
      .filter((entry) =>
        `${entry.metric_id} ${entry.name} ${entry.dataset_ids.join(" ")}`
          .toLowerCase()
          .includes(needle),
      )
      .slice(0, 60);
  }, [options, text]);

  const commit = (next: string) => {
    const trimmed = next.trim();
    setDraft(null);
    if (trimmed.length === 0) {
      if (allowEmpty) onChange(null);
      return;
    }
    // Accept a readable name as well as an exact id.
    const exact = options.find((entry) => entry.metric_id === trimmed);
    const byName = options.find(
      (entry) => entry.name.toLowerCase() === trimmed.toLowerCase(),
    );
    const resolved = exact ?? byName ?? null;
    onChange(resolved?.metric_id ?? trimmed);
  };

  return (
    <label htmlFor={inputId} className="flex min-w-0 flex-col gap-1 text-[11px] text-text-muted">
      {label}
      <span className="flex items-center gap-1.5">
        <input
          id={inputId}
          list={listId}
          value={text}
          disabled={isPending}
          placeholder={isPending ? "Loading metric catalog…" : "Search metrics by name or id"}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={(event) => commit(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              commit((event.target as HTMLInputElement).value);
            }
          }}
          className={cn(
            "h-7 w-72 rounded-control border border-border-subtle bg-surface-0 px-2 text-[12px] text-text-secondary outline-none transition-colors duration-quick focus:border-accent",
            isPending && "opacity-60",
          )}
        />
        {allowEmpty && value !== null ? (
          <button
            type="button"
            onClick={() => {
              setDraft(null);
              onChange(null);
            }}
            className="rounded-control border border-border-subtle px-1.5 py-1 text-[11px] text-text-muted hover:border-border-strong hover:text-text-secondary"
          >
            Clear
          </button>
        ) : null}
      </span>
      <datalist id={listId}>
        {matches.map((entry) => (
          <option key={entry.metric_id} value={entry.metric_id}>
            {entry.name} · {entry.si_unit} · {entry.value_count.toLocaleString("en-US")} values
          </option>
        ))}
      </datalist>
      {selected ? (
        <span className="max-w-72 truncate text-[10px] text-text-muted" title={selected.name}>
          {selected.name} · {selected.dataset_ids.join(", ")}
        </span>
      ) : null}
    </label>
  );
}
