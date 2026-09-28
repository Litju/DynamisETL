import { Autocomplete } from "@base-ui/react/autocomplete";
import { Search } from "lucide-react";
import { useMemo, useState } from "react";

import { useGoTo } from "@/components/common/AppLink";
import { ReadinessGlyph } from "@/components/common/Readiness";
import { WorldGlyph } from "@/components/common/WorldGlyph";
import { searchCatalog, type CatalogHit } from "@/lib/catalog-model";
import { cn } from "@/lib/cn";
import { useCatalog } from "@/lib/use-catalog";

const KIND_LABEL: Record<CatalogHit["kind"], string> = {
  edition: "Competition",
  contest: "Contest",
  team: "Team",
  study: "Study",
  session: "Session",
};

/**
 * Global catalog search (metadata only). Base UI Autocomplete owns the
 * combobox semantics, keyboard highlight and popup focus behaviour.
 */
export function CatalogSearch({
  size = "lg",
  placeholder = "Search competitions, matches, teams, studies",
  className,
}: {
  size?: "lg" | "md";
  placeholder?: string;
  className?: string;
}) {
  const [query, setQuery] = useState("");
  const catalog = useCatalog();
  const goTo = useGoTo();
  const hits = useMemo(
    () => searchCatalog(catalog.resources, catalog.studies, query, 9),
    [catalog.resources, catalog.studies, query],
  );

  return (
    <Autocomplete.Root
      items={hits}
      filter={null}
      value={query}
      onValueChange={(value) => setQuery(value)}
      itemToStringValue={(hit: CatalogHit) => hit.title}
      autoHighlight
    >
      <Autocomplete.InputGroup
        className={cn(
          "group flex items-center gap-3 rounded-[10px] border border-border-subtle bg-surface-1 transition-[border-color,box-shadow] duration-quick focus-within:border-selected-border focus-within:shadow-[0_0_0_4px_color-mix(in_oklab,var(--d-accent)_12%,transparent)]",
          size === "lg" ? "h-12 px-4" : "h-9 px-3",
          className,
        )}
      >
        <Search size={size === "lg" ? 16 : 14} aria-hidden="true" className="shrink-0 text-text-muted" />
        <Autocomplete.Input
          aria-label="Search the catalog"
          placeholder={placeholder}
          className={cn(
            "h-full min-w-0 flex-1 bg-transparent text-text-primary outline-none placeholder:text-text-faint",
            size === "lg" ? "text-[14px]" : "text-[12.5px]",
          )}
        />
        <span className="hidden shrink-0 items-center gap-1 text-[10.5px] text-text-faint sm:flex">
          metadata only
        </span>
      </Autocomplete.InputGroup>
      <Autocomplete.Portal hidden={query.trim() === ""}>
        <Autocomplete.Positioner sideOffset={6} align="start" className="z-50 outline-none">
          <Autocomplete.Popup className="d-overlay d-pop w-[var(--anchor-width)] max-w-[var(--available-width)] overflow-hidden p-1">
            <Autocomplete.Empty>
              <p className="px-3 py-4 text-[12px] text-text-muted">No catalog record matches “{query}”.</p>
            </Autocomplete.Empty>
            <Autocomplete.List className="max-h-[min(24rem,var(--available-height))] overflow-y-auto">
              {(hit: CatalogHit) => (
                <Autocomplete.Item
                  key={hit.key}
                  value={hit}
                  onClick={() => goTo(hit.target, { transition: true })}
                  className="group grid cursor-default grid-cols-[1.75rem_minmax(0,1fr)_auto] items-center gap-2.5 rounded-[6px] px-2.5 py-2 outline-none data-[highlighted]:bg-hover"
                >
                  <span className="flex justify-center text-text-muted group-data-[highlighted]:text-accent">
                    {hit.world ? <WorldGlyph world={hit.world} size="sm" /> : <span className="t-kicker">{KIND_LABEL[hit.kind].slice(0, 2)}</span>}
                  </span>
                  <span className="min-w-0">
                    <span className="block truncate text-[12.5px] text-text-primary">{hit.title}</span>
                    <span className="block truncate text-[11px] text-text-muted">
                      {KIND_LABEL[hit.kind]} · {hit.subtitle}
                    </span>
                  </span>
                  <span className="inline-flex items-center gap-1.5 text-[10.5px] text-text-muted">
                    <ReadinessGlyph kind={hit.ready ? "ready" : "upstream"} />
                    {hit.ready ? "Ready" : "Upstream"}
                  </span>
                </Autocomplete.Item>
              )}
            </Autocomplete.List>
          </Autocomplete.Popup>
        </Autocomplete.Positioner>
      </Autocomplete.Portal>
    </Autocomplete.Root>
  );
}
