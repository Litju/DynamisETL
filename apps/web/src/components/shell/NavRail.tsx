import { Link, useRouterState } from "@tanstack/react-router";
import {
  Activity,
  Boxes,
  Database,
  FileSearch,
  GitCompareArrows,
  ShieldCheck,
  type LucideIcon,
} from "lucide-react";

import { cn } from "@/lib/cn";

interface NavItem {
  readonly to: string;
  readonly label: string;
  readonly hint: string;
  readonly icon: LucideIcon;
}

/**
 * Two groups: where analysis happens, and where its evidence lives. The
 * separator is the only grouping cue the rail can afford at 48 px.
 */
const ANALYSIS_ITEMS: readonly NavItem[] = [
  { to: "/catalog", label: "Catalog", hint: "Datasets, modalities and rights", icon: Database },
  { to: "/lab", label: "Laboratory", hint: "Signals, field and pose analysis", icon: Activity },
  { to: "/compare", label: "Compare", hint: "Comparative metric analysis", icon: GitCompareArrows },
];

const EVIDENCE_ITEMS: readonly NavItem[] = [
  { to: "/methods", label: "Methodology", hint: "Metric definitions and lineage", icon: FileSearch },
  { to: "/runs", label: "Processing runs", hint: "Reproducible run evidence", icon: Boxes },
  { to: "/quality", label: "Quality & rights", hint: "Validity and usage boundaries", icon: ShieldCheck },
];

/**
 * Activity rail (48 px). Icon-only with accessible names and tooltips; the
 * active surface gets a structural marker, not just a color change.
 */
export function NavRail() {
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  return (
    <nav
      aria-label="Product surfaces"
      className="flex w-rail shrink-0 flex-col items-center gap-1 border-r border-border-subtle bg-surface-0 py-2"
    >
      <span
        className="mb-2 flex size-8 items-center justify-center rounded-control border border-border-strong text-[11px] font-semibold tracking-tight text-accent"
        title="DynamisData Performance Laboratory"
      >
        DD
      </span>
      {ANALYSIS_ITEMS.map((item) => (
        <NavRailLink key={item.to} item={item} pathname={pathname} />
      ))}
      <span aria-hidden="true" className="my-1.5 h-px w-5 bg-border-subtle" />
      {EVIDENCE_ITEMS.map((item) => (
        <NavRailLink key={item.to} item={item} pathname={pathname} />
      ))}
    </nav>
  );
}

function NavRailLink({ item, pathname }: { item: NavItem; pathname: string }) {
  const active = pathname === item.to || pathname.startsWith(`${item.to}/`);
  const Icon = item.icon;
  return (
    <Link
      to={item.to}
      aria-label={item.label}
      title={`${item.label} — ${item.hint}`}
      aria-current={active ? "page" : undefined}
      className={cn(
        "relative flex size-8 items-center justify-center rounded-control text-text-muted transition-colors duration-quick hover:bg-surface-2 hover:text-text-secondary",
        active && "bg-surface-3 text-accent",
      )}
    >
      {active ? (
        <span
          aria-hidden="true"
          className="absolute left-0 h-4 w-0.5 -translate-x-1.5 rounded-r-full bg-accent"
        />
      ) : null}
      <Icon size={16} strokeWidth={1.75} aria-hidden="true" />
    </Link>
  );
}
